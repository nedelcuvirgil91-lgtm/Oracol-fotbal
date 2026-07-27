"""Teste pentru provider_selector.py (ADR-034, PR5 — Selection Engine, shadow
mode) — fără rețea, izolate prin fakes injectate pe toate cele 4 dependințe
(Registry, capabilities_fn, league_state_fn, health_fn)."""
from __future__ import annotations

import pytest

from league_mapping import Confidence, LeagueProviderState, ProviderState
from provider_capabilities import DataType
from provider_health import ProviderHealth
from provider_registry import ProviderRecord, ProviderRegistry
from provider_selector import (
    ALGORITHM_VERSION, CandidateProvider, ProviderRecommendation, ProviderScore,
    ScoreComponents, SELECTION_WEIGHTS, SelectionWeights, ShadowObservation,
    ShadowStatistics, compute_shadow_statistics, compute_weighted_total,
    find_candidates, recommend_provider, render_reason_text, score_provider,
)


_FAKE_PROVIDERS = (
    ProviderRecord("alpha", "Alpha", requires_credentials=True),
    ProviderRecord("beta", "Beta", requires_credentials=True),
    ProviderRecord("gamma", "Gamma (public)", requires_credentials=False),
)


class _FakeKeyManager:
    def is_available(self, provider_id):
        return provider_id in ("alpha", "beta")

    def get_headers(self, provider_id):
        return None

    def record_request(self, provider_id):
        pass

    def get_status(self):
        return {"month": "2026-07", "providers": {}}


def _registry() -> ProviderRegistry:
    return ProviderRegistry(key_manager=_FakeKeyManager(), providers=_FAKE_PROVIDERS)


def _capabilities_fn(supported: set[str]):
    def _fn(provider_id: str, data_type: DataType) -> bool:
        return provider_id in supported
    return _fn


def _league_state_fn(states: dict[str, LeagueProviderState]):
    def _fn(league: str, provider_id: str) -> LeagueProviderState | None:
        return states.get(provider_id)
    return _fn


def _health_fn(healths: dict[str, ProviderHealth]):
    def _fn(provider_id: str) -> ProviderHealth | None:
        return healths.get(provider_id)
    return _fn


def _state(provider_id: str, state=ProviderState.AVAILABLE, confidence=Confidence.CONFIRMED) -> LeagueProviderState:
    return LeagueProviderState(league="Test League", provider_id=provider_id,
                                legacy_key=provider_id, state=state, confidence=confidence)


def _health(available=True, reliability=0.9, latency=100.0, quota_pct=80.0) -> ProviderHealth:
    return ProviderHealth(
        provider_id="x", available=available, reliability=reliability, avg_latency_ms=latency,
        quota_remaining_pct=quota_pct, consecutive_failures=0, total_calls=10, total_errors=1,
    )


# ── SelectionWeights / ScoreComponents — validare ───────────────────────────

def test_selection_weights_must_sum_to_one():
    with pytest.raises(ValueError):
        SelectionWeights(availability=0.5, coverage=0.5, reliability=0.5,
                          quota=0.0, latency=0.0, priority=0.0)


def test_default_selection_weights_sum_to_one():
    total = (SELECTION_WEIGHTS.availability + SELECTION_WEIGHTS.coverage
              + SELECTION_WEIGHTS.reliability + SELECTION_WEIGHTS.quota
              + SELECTION_WEIGHTS.latency + SELECTION_WEIGHTS.priority)
    assert total == pytest.approx(1.0)


def test_score_components_rejects_out_of_range():
    with pytest.raises(ValueError):
        ScoreComponents(availability=1.5, coverage=0.5, reliability=0.5,
                         quota=0.5, latency=0.5, priority=0.5)


def test_compute_weighted_total_matches_manual_formula():
    components = ScoreComponents(availability=1.0, coverage=1.0, reliability=1.0,
                                  quota=1.0, latency=1.0, priority=1.0)
    assert compute_weighted_total(components) == pytest.approx(1.0)

    components_zero = ScoreComponents(availability=0.0, coverage=0.0, reliability=0.0,
                                       quota=0.0, latency=0.0, priority=0.0)
    assert compute_weighted_total(components_zero) == pytest.approx(0.0)


# ── CandidateProvider — Fail Loud pe stare invalidă ─────────────────────────

def test_candidate_provider_rejects_non_available_state():
    with pytest.raises(ValueError):
        CandidateProvider(provider_id="alpha", league="L", data_type=DataType.FIXTURES,
                           state=ProviderState.PLAN_RESTRICTED, confidence=Confidence.CONFIRMED)


def test_candidate_provider_accepts_available_state():
    c = CandidateProvider(provider_id="alpha", league="L", data_type=DataType.FIXTURES,
                           state=ProviderState.AVAILABLE, confidence=Confidence.CONFIRMED)
    assert c.provider_id == "alpha"


# ── find_candidates — filtrare tare ─────────────────────────────────────────

def test_find_candidates_excludes_unavailable_provider():
    reg = _registry()
    states = {"alpha": _state("alpha"), "beta": _state("beta", state=ProviderState.PLAN_RESTRICTED,
                                                          confidence=Confidence.CONFIRMED)}
    candidates = find_candidates(
        "L", DataType.FIXTURES, registry=reg,
        capabilities_fn=_capabilities_fn({"alpha", "beta"}),
        league_state_fn=_league_state_fn(states),
    )
    ids = {c.provider_id for c in candidates}
    assert ids == {"alpha"}


def test_find_candidates_excludes_untested_state():
    """Decizie explicita de design: doar AVAILABLE, niciodata UNTESTED."""
    reg = _registry()
    states = {"alpha": _state("alpha", state=ProviderState.UNTESTED, confidence=Confidence.UNKNOWN)}
    candidates = find_candidates(
        "L", DataType.FIXTURES, registry=reg,
        capabilities_fn=_capabilities_fn({"alpha"}),
        league_state_fn=_league_state_fn(states),
    )
    assert candidates == ()


def test_find_candidates_excludes_unsupported_data_type():
    reg = _registry()
    states = {"alpha": _state("alpha")}
    candidates = find_candidates(
        "L", DataType.ODDS, registry=reg,
        capabilities_fn=_capabilities_fn(set()),  # nimeni nu suporta ODDS
        league_state_fn=_league_state_fn(states),
    )
    assert candidates == ()


def test_find_candidates_excludes_keyless_unavailable_provider():
    """gamma nu are credentiale in Registry-ul fake -> is_available() ar fi
    True conform PR1 (fara gate de credential) - dar in acest test fake_km
    nu-l cunoaste deloc; gamma.requires_credentials=False deci tot trece
    is_available prin Registry, testam ca League Mapping tot poate exclude."""
    reg = _registry()
    states = {"gamma": _state("gamma", state=ProviderState.UNAVAILABLE, confidence=Confidence.CONFIRMED)}
    candidates = find_candidates(
        "L", DataType.FIXTURES, registry=reg,
        capabilities_fn=_capabilities_fn({"gamma"}),
        league_state_fn=_league_state_fn(states),
    )
    assert candidates == ()


def test_find_candidates_preserves_registry_declaration_order():
    reg = _registry()
    states = {"alpha": _state("alpha"), "beta": _state("beta"), "gamma": _state("gamma")}
    candidates = find_candidates(
        "L", DataType.FIXTURES, registry=reg,
        capabilities_fn=_capabilities_fn({"alpha", "beta", "gamma"}),
        league_state_fn=_league_state_fn(states),
    )
    assert [c.provider_id for c in candidates] == ["alpha", "beta", "gamma"]


# ── score_provider — general-purpose, orice provider cunoscut ──────────────

def test_score_provider_none_for_unknown_provider():
    reg = _registry()
    assert score_provider("necunoscut", "L", DataType.FIXTURES, registry=reg,
                           capabilities_fn=_capabilities_fn(set()),
                           league_state_fn=_league_state_fn({}),
                           health_fn=_health_fn({})) is None


def test_score_provider_works_for_non_candidate_current_provider():
    """current_provider poate fi scorat chiar daca e respins de filtrarea
    tare (plan_restricted) - necesar pentru explicabilitate completa."""
    reg = _registry()
    states = {"alpha": _state("alpha", state=ProviderState.PLAN_RESTRICTED, confidence=Confidence.CONFIRMED)}
    score = score_provider("alpha", "L", DataType.FIXTURES, registry=reg,
                            capabilities_fn=_capabilities_fn({"alpha"}),
                            league_state_fn=_league_state_fn(states),
                            health_fn=_health_fn({}))
    assert score is not None
    assert score.components.coverage == 0.0  # plan_restricted -> 0.0


def test_score_provider_reliability_neutral_default_when_no_health():
    reg = _registry()
    states = {"alpha": _state("alpha")}
    score = score_provider("alpha", "L", DataType.FIXTURES, registry=reg,
                            capabilities_fn=_capabilities_fn({"alpha"}),
                            league_state_fn=_league_state_fn(states),
                            health_fn=_health_fn({}))
    assert score.components.reliability == 0.5
    assert score.components.latency == 0.5


def test_score_provider_priority_defaults_to_neutral_when_not_injected():
    """[ADR-041 Faza 1] Fara priority_fn -> tie-breaker static 0.5, identic
    comportamentul de dinainte de injectare (zero regresie)."""
    reg = _registry()
    states = {"alpha": _state("alpha")}
    score = score_provider("alpha", "L", DataType.FIXTURES, registry=reg,
                            capabilities_fn=_capabilities_fn({"alpha"}),
                            league_state_fn=_league_state_fn(states),
                            health_fn=_health_fn({}))
    assert score.components.priority == 0.5


def test_score_provider_priority_uses_injected_priority_fn():
    """[ADR-041 Faza 1] priority_fn injectat (ex. din config Supabase, prin
    sync_provider_manager.py) — acest modul rămâne pur, nu citește Supabase
    direct (Dependency Direction, docstring modul)."""
    reg = _registry()
    states = {"alpha": _state("alpha")}
    score = score_provider("alpha", "L", DataType.FIXTURES, registry=reg,
                            capabilities_fn=_capabilities_fn({"alpha"}),
                            league_state_fn=_league_state_fn(states),
                            health_fn=_health_fn({}),
                            priority_fn=lambda pid: {"alpha": 0.9}.get(pid, 0.5))
    assert score.components.priority == 0.9


def test_score_provider_quota_full_when_no_quota_concept():
    reg = _registry()
    states = {"gamma": _state("gamma")}
    health = ProviderHealth(provider_id="gamma", available=True, reliability=None,
                             avg_latency_ms=None, quota_remaining_pct=None,
                             consecutive_failures=0, total_calls=0, total_errors=0)
    score = score_provider("gamma", "L", DataType.FIXTURES, registry=reg,
                            capabilities_fn=_capabilities_fn({"gamma"}),
                            league_state_fn=_league_state_fn(states),
                            health_fn=_health_fn({"gamma": health}))
    assert score.components.quota == 1.0


def test_score_provider_coverage_reflects_confidence():
    reg = _registry()
    states_confirmed = {"alpha": _state("alpha", confidence=Confidence.CONFIRMED)}
    states_assumed = {"alpha": _state("alpha", confidence=Confidence.ASSUMED)}
    kwargs = dict(registry=reg, capabilities_fn=_capabilities_fn({"alpha"}), health_fn=_health_fn({}))
    score_confirmed = score_provider("alpha", "L", DataType.FIXTURES,
                                      league_state_fn=_league_state_fn(states_confirmed), **kwargs)
    score_assumed = score_provider("alpha", "L", DataType.FIXTURES,
                                    league_state_fn=_league_state_fn(states_assumed), **kwargs)
    assert score_confirmed.components.coverage == 1.0
    assert score_assumed.components.coverage == 0.5


# ── recommend_provider — pipeline complet ───────────────────────────────────

def test_recommend_provider_no_change_when_current_is_best():
    reg = _registry()
    states = {"alpha": _state("alpha"), "beta": _state("beta")}
    healths = {"alpha": _health(reliability=0.99, latency=10.0, quota_pct=99.0),
               "beta": _health(reliability=0.1, latency=1900.0, quota_pct=1.0)}
    rec = recommend_provider(
        "L", DataType.FIXTURES, "alpha", registry=reg,
        capabilities_fn=_capabilities_fn({"alpha", "beta"}),
        league_state_fn=_league_state_fn(states), health_fn=_health_fn(healths),
    )
    assert rec.recommended_provider == "alpha"
    assert rec.decision_changed is False


def test_recommend_provider_changes_when_better_candidate_exists():
    reg = _registry()
    states = {"alpha": _state("alpha"), "beta": _state("beta")}
    healths = {"alpha": _health(reliability=0.1, latency=1900.0, quota_pct=1.0),
               "beta": _health(reliability=0.99, latency=10.0, quota_pct=99.0)}
    rec = recommend_provider(
        "L", DataType.FIXTURES, "alpha", registry=reg,
        capabilities_fn=_capabilities_fn({"alpha", "beta"}),
        league_state_fn=_league_state_fn(states), health_fn=_health_fn(healths),
    )
    assert rec.recommended_provider == "beta"
    assert rec.decision_changed is True
    assert rec.reason is not None
    # suma deltas trebuie sa reconstituie EXACT diferenta de scor total (Regula de Aur #3)
    total_delta = rec.recommended_score.total - rec.current_score.total
    assert sum(rec.reason.component_deltas.values()) == pytest.approx(total_delta)


def test_recommend_provider_propagates_injected_priority_fn():
    """[ADR-041 Faza 1] priority_fn injectat trebuie folosit atat pentru
    candidati cat si pentru providerul curent (altfel comparatia ar fi
    inconsistenta)."""
    reg = _registry()
    states = {"alpha": _state("alpha"), "beta": _state("beta")}
    # Health identic pentru ambii -- doar priority ii diferentiaza.
    healths = {"alpha": _health(reliability=0.5, latency=1000.0, quota_pct=50.0),
               "beta": _health(reliability=0.5, latency=1000.0, quota_pct=50.0)}
    rec = recommend_provider(
        "L", DataType.FIXTURES, "alpha", registry=reg,
        capabilities_fn=_capabilities_fn({"alpha", "beta"}),
        league_state_fn=_league_state_fn(states), health_fn=_health_fn(healths),
        priority_fn=lambda pid: {"alpha": 0.1, "beta": 0.9}.get(pid, 0.5),
    )
    assert rec.recommended_provider == "beta"
    assert rec.current_score.components.priority == 0.1
    assert rec.recommended_score.components.priority == 0.9


def test_recommend_provider_none_when_no_candidates():
    reg = _registry()
    rec = recommend_provider(
        "L", DataType.FIXTURES, "alpha", registry=reg,
        capabilities_fn=_capabilities_fn(set()),
        league_state_fn=_league_state_fn({}), health_fn=_health_fn({}),
    )
    assert rec.recommended_provider is None
    assert rec.recommended_score is None
    assert rec.reason is None
    assert rec.decision_changed is False


def test_recommend_provider_current_score_none_for_unknown_current_provider():
    reg = _registry()
    states = {"alpha": _state("alpha")}
    rec = recommend_provider(
        "L", DataType.FIXTURES, "necunoscut-provider", registry=reg,
        capabilities_fn=_capabilities_fn({"alpha"}),
        league_state_fn=_league_state_fn(states), health_fn=_health_fn({}),
    )
    assert rec.current_score is None
    assert rec.recommended_provider == "alpha"
    assert rec.decision_changed is True


# ── Regula de Aur #4 — determinism complet ──────────────────────────────────

def test_recommend_provider_is_deterministic_across_1000_calls():
    reg = _registry()
    states = {"alpha": _state("alpha"), "beta": _state("beta")}
    healths = {"alpha": _health(reliability=0.4, latency=900.0, quota_pct=50.0),
               "beta": _health(reliability=0.7, latency=300.0, quota_pct=70.0)}

    results = [
        recommend_provider(
            "L", DataType.FIXTURES, "alpha", registry=reg,
            capabilities_fn=_capabilities_fn({"alpha", "beta"}),
            league_state_fn=_league_state_fn(states), health_fn=_health_fn(healths),
        )
        for _ in range(1000)
    ]
    assert all(r == results[0] for r in results)


def test_score_provider_is_deterministic_across_1000_calls():
    reg = _registry()
    states = {"alpha": _state("alpha")}
    healths = {"alpha": _health()}
    results = [
        score_provider("alpha", "L", DataType.FIXTURES, registry=reg,
                        capabilities_fn=_capabilities_fn({"alpha"}),
                        league_state_fn=_league_state_fn(states), health_fn=_health_fn(healths))
        for _ in range(1000)
    ]
    assert all(r == results[0] for r in results)


def test_recommend_provider_tie_break_uses_registry_order_not_dict_order():
    """Scoruri identice pentru alpha si beta -> castiga primul din ordinea
    declarata in Provider Registry (tuple fix), nu ordinea (arbitrara la
    nivel de garantie) a vreunui dict/set intern."""
    reg = _registry()
    states = {"alpha": _state("alpha"), "beta": _state("beta")}
    same_health = _health(reliability=0.5, latency=500.0, quota_pct=50.0)
    healths = {"alpha": same_health, "beta": same_health}
    rec = recommend_provider(
        "L", DataType.FIXTURES, "gamma", registry=reg,
        capabilities_fn=_capabilities_fn({"alpha", "beta"}),
        league_state_fn=_league_state_fn(states), health_fn=_health_fn(healths),
    )
    assert rec.recommended_provider == "alpha"  # primul in _FAKE_PROVIDERS


# ── render_reason_text — pur, text uman ─────────────────────────────────────

def test_render_reason_text_contains_expected_sections():
    reg = _registry()
    states = {"alpha": _state("alpha"), "beta": _state("beta")}
    healths = {"alpha": _health(reliability=0.1, latency=1900.0, quota_pct=1.0),
               "beta": _health(reliability=0.99, latency=10.0, quota_pct=99.0)}
    rec = recommend_provider(
        "L", DataType.FIXTURES, "alpha", registry=reg,
        capabilities_fn=_capabilities_fn({"alpha", "beta"}),
        league_state_fn=_league_state_fn(states), health_fn=_health_fn(healths),
    )
    text = render_reason_text(rec)
    assert "Current provider:" in text
    assert "Recommendation:" in text
    assert "Reason:" in text
    assert "Decision changed:  YES" in text


def test_render_reason_text_no_candidates_case():
    reg = _registry()
    rec = recommend_provider(
        "L", DataType.FIXTURES, "alpha", registry=reg,
        capabilities_fn=_capabilities_fn(set()),
        league_state_fn=_league_state_fn({}), health_fn=_health_fn({}),
    )
    text = render_reason_text(rec)
    assert "(niciun candidat eligibil)" in text
    assert "Decision changed:  NO" in text


# ── compute_shadow_statistics — pur, agregare peste ShadowObservation ──────

def test_compute_shadow_statistics_counts_correctly():
    observations = [
        ShadowObservation(decision_changed=False, recommended_provider="alpha",
                           current_total=0.8, recommended_total=0.8),
        ShadowObservation(decision_changed=True, recommended_provider="beta",
                           current_total=0.5, recommended_total=0.9),
        ShadowObservation(decision_changed=True, recommended_provider="beta",
                           current_total=0.6, recommended_total=0.4),  # decizie schimbata dar NU mai buna
        ShadowObservation(decision_changed=False, recommended_provider=None,
                           current_total=None, recommended_total=None),
    ]
    stats = compute_shadow_statistics(observations)
    assert stats.total_recommendations == 4
    assert stats.identical_recommendations == 1
    assert stats.different_recommendations == 2
    assert stats.provider_unavailable == 1
    assert stats.provider_better_than_current == 1


def test_compute_shadow_statistics_empty_list():
    stats = compute_shadow_statistics([])
    assert stats == ShadowStatistics(0, 0, 0, 0, 0)


def test_compute_shadow_statistics_is_deterministic():
    observations = [
        ShadowObservation(decision_changed=True, recommended_provider="beta",
                           current_total=0.5, recommended_total=0.9),
    ]
    results = [compute_shadow_statistics(observations) for _ in range(100)]
    assert all(r == results[0] for r in results)


# ── ALGORITHM_VERSION — constanta de domeniu, nu derivata din infra ────────

def test_algorithm_version_is_static_int_constant():
    assert isinstance(ALGORITHM_VERSION, int)
    assert ALGORITHM_VERSION >= 1


# ── Dependency Direction — regresie structurala ─────────────────────────────

def test_provider_selector_never_imports_infrastructure():
    import provider_selector
    source_modules = {"supabase_client", "key_manager", "oracle_api", "football_providers", "shadow_recorder"}
    forbidden_found = source_modules & set(vars(provider_selector).keys())
    assert forbidden_found == set(), f"provider_selector.py importa infra interzisa: {forbidden_found}"
