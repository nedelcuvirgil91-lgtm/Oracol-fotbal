"""Teste pentru sync_provider_manager.py (ADR-041 Faza 1) — fara retea, fara
Supabase live (supabase_client.load_config e mock-uit peste tot)."""
from __future__ import annotations

import sync_provider_manager as spm
from provider_selector import ProviderRecommendation, ProviderScore, ScoreComponents


def _fake_load_config(enabled: bool):
    def _load(default):
        return {"selection_engine_v2": enabled}
    return _load


def test_flag_disabled_by_default_uses_static_chain(monkeypatch):
    monkeypatch.setattr(spm.sb, "load_config", _fake_load_config(False))
    choice = spm.choose_provider("match_statistics", "Romania SuperLiga")
    assert choice.provider_id == "soccerfootballinfo"
    assert choice.via_selection_engine is False
    assert choice.weights_name is None


def test_flag_disabled_unknown_domain_returns_none():
    # Nu are nevoie de mock — flag-ul implicit e False oricum (fail-open,
    # fara Supabase live in teste), lantul static pentru un domeniu necunoscut e gol.
    choice = spm.choose_provider("nonexistent_domain", "Romania SuperLiga")
    assert choice.provider_id is None
    assert choice.via_selection_engine is False


def test_flag_enabled_domain_not_covered_by_selection_engine_falls_back(monkeypatch):
    monkeypatch.setattr(spm.sb, "load_config", _fake_load_config(True))
    # "team_form" e in _STATIC_FALLBACK_CHAINS dar NU in _DOMAIN_TO_DATA_TYPE
    # (decizie deschisa, Sprint 1 v6 S2) -- trebuie sa ramana pe calea statica.
    choice = spm.choose_provider("team_form", "Romania SuperLiga")
    assert choice.provider_id == "freelivefootball"
    assert choice.via_selection_engine is False
    assert "neacoperit" in choice.reason


def test_flag_enabled_domain_unknown_to_static_chain_too_returns_none(monkeypatch):
    monkeypatch.setattr(spm.sb, "load_config", _fake_load_config(True))
    choice = spm.choose_provider("nonexistent_domain", "Romania SuperLiga")
    assert choice.provider_id is None
    assert choice.via_selection_engine is False


def test_flag_enabled_no_candidates_falls_back_to_static(monkeypatch):
    monkeypatch.setattr(spm.sb, "load_config", _fake_load_config(True))

    def _fake_recommend(league, data_type, current_provider, weights, priority_fn=None):
        return ProviderRecommendation(
            league=league, data_type=data_type, current_provider=current_provider,
            current_score=None, recommended_provider=None, recommended_score=None,
            reason=None, decision_changed=False,
        )
    monkeypatch.setattr(spm, "recommend_provider", _fake_recommend)

    choice = spm.choose_provider("match_statistics", "Romania SuperLiga")
    assert choice.provider_id == "soccerfootballinfo"  # primul din lantul static
    assert choice.via_selection_engine is False
    assert "niciun candidat eligibil" in choice.reason


def test_flag_enabled_uses_selection_engine_when_candidate_found(monkeypatch):
    monkeypatch.setattr(spm.sb, "load_config", _fake_load_config(True))

    components = ScoreComponents(availability=1.0, coverage=1.0, reliability=0.9,
                                  quota=0.8, latency=0.7, priority=0.5)
    fake_score = ProviderScore(provider_id="freelivefootball", components=components, total=0.9)

    def _fake_recommend(league, data_type, current_provider, weights, priority_fn=None):
        return ProviderRecommendation(
            league=league, data_type=data_type, current_provider=current_provider,
            current_score=None, recommended_provider="freelivefootball",
            recommended_score=fake_score, reason=None, decision_changed=True,
        )
    monkeypatch.setattr(spm, "recommend_provider", _fake_recommend)

    choice = spm.choose_provider("match_statistics", "Romania SuperLiga")
    assert choice.provider_id == "freelivefootball"
    assert choice.via_selection_engine is True
    assert choice.weights_name == "LIVE"
    assert choice.weights_version == 1


def test_backfill_intent_uses_backfill_weights(monkeypatch):
    monkeypatch.setattr(spm.sb, "load_config", _fake_load_config(True))

    captured = {}

    def _fake_recommend(league, data_type, current_provider, weights, priority_fn=None):
        captured["weights"] = weights
        return ProviderRecommendation(
            league=league, data_type=data_type, current_provider=current_provider,
            current_score=None, recommended_provider="sportapi",
            recommended_score=None, reason=None, decision_changed=True,
        )
    monkeypatch.setattr(spm, "recommend_provider", _fake_recommend)

    choice = spm.choose_provider("match_statistics", "Romania SuperLiga", intent=spm.Intent.BACKFILL)
    assert choice.provider_id == "sportapi"
    assert choice.weights_name == "BACKFILL"
    assert captured["weights"] is spm.SELECTION_WEIGHTS_BACKFILL


def test_live_and_backfill_weights_are_distinct_presets():
    assert spm.SELECTION_WEIGHTS.quota != spm.SELECTION_WEIGHTS_BACKFILL.quota
    assert spm.SELECTION_WEIGHTS.latency != spm.SELECTION_WEIGHTS_BACKFILL.latency


def test_default_flag_is_off_when_config_missing(monkeypatch):
    # load_config intoarce default-ul cand nu exista nimic in Supabase --
    # Regula #3 CLAUDE.md: niciun flag nou nu porneste implicit activ.
    def _load(default):
        return dict(default)
    monkeypatch.setattr(spm.sb, "load_config", _load)
    assert spm.is_selection_engine_v2_enabled() is False


def test_fallback_chain_returns_full_static_chain_for_known_domain():
    chain = spm.fallback_chain("match_statistics")
    assert chain == ("soccerfootballinfo", "freelivefootball", "sportapi")


def test_fallback_chain_returns_empty_tuple_for_unknown_domain():
    assert spm.fallback_chain("nonexistent_domain") == ()


def test_fallback_chain_matches_static_chains_source_of_truth():
    for domain, chain in spm._STATIC_FALLBACK_CHAINS.items():
        assert spm.fallback_chain(domain) == chain


def test_provider_priority_fn_defaults_to_neutral_when_config_missing(monkeypatch):
    # [ADR-041 Faza 1] Regula #3 CLAUDE.md -- fara "provider_priority" in
    # config, comportamentul ramane identic celui de dinainte (0.5 pentru toti).
    monkeypatch.setattr(spm.sb, "load_config", lambda default: dict(default))
    assert spm._provider_priority_fn("soccerfootballinfo") == 0.5
    assert spm._provider_priority_fn("freelivefootball") == 0.5


def test_provider_priority_fn_reads_from_supabase_config(monkeypatch):
    monkeypatch.setattr(spm.sb, "load_config",
                         lambda default: {"provider_priority": {"soccerfootballinfo": 0.8}})
    assert spm._provider_priority_fn("soccerfootballinfo") == 0.8
    assert spm._provider_priority_fn("freelivefootball") == 0.5  # neconfigurat -> neutru


def test_choose_provider_passes_provider_priority_fn_to_recommend_provider(monkeypatch):
    monkeypatch.setattr(spm.sb, "load_config", _fake_load_config(True))
    captured = {}

    def _fake_recommend(league, data_type, current_provider, weights, priority_fn):
        captured["priority_fn"] = priority_fn
        return ProviderRecommendation(
            league=league, data_type=data_type, current_provider=current_provider,
            current_score=None, recommended_provider="soccerfootballinfo",
            recommended_score=None, reason=None, decision_changed=True,
        )
    monkeypatch.setattr(spm, "recommend_provider", _fake_recommend)

    spm.choose_provider("match_statistics", "Romania SuperLiga")
    assert captured["priority_fn"] is spm._provider_priority_fn
