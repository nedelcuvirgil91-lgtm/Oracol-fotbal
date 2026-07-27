"""
================================================================================
FOOTBALL ORACLE — Selection Engine (ADR-034, Strat 5/6) — SHADOW MODE (PR5)
================================================================================
Module: provider_selector.py

Strat subțire deasupra straturilor 1-4 (Provider Registry, Capability
Registry, League Mapping, Health Monitor). Filtrare tare (cine POATE fi
recomandat) → scor ponderat (cât de BUN e fiecare candidat) → recomandare
(diferența față de providerul folosit azi, explicată complet).

Pipeline de domeniu:

    Registry -> find_candidates() -> CandidateProvider
             -> score_provider()  -> ProviderScore
             -> recommend_provider() -> ProviderRecommendation

Regula de Aur #4 — Determinism complet: nicio funcție din acest modul nu
citește ceasul, nu generează UUID/random, nu depinde de ordinea unui
`dict`/`set` (doar `tuple`/`list` cu ordine fixă). Aceleași input-uri produc
mereu un rezultat structural identic (`==`), niciodată doar "același
provider". Determinism = egalitate structurală, nu identitate de obiect —
niciun cache intern, niciun singleton de rezultate.

Regula de Aur #5 — Funcții pure: find_candidates(), score_provider(),
recommend_provider(), render_reason_text(), compute_shadow_statistics() nu
scriu niciodată nicăieri, nu loghează, nu fac HTTP, nu țin cache. Cele care
citesc stare externă (Registry/Health/League Mapping, prin dependințe
injectabile) produc mereu același rezultat pentru aceeași stare externă —
exact disciplina de "agregare deterministă" stabilită la PR4.

Shadow Mode e PUR observațional (ADR-034, PR5) — niciodată nu schimbă
providerul folosit, nu consumă cotă, nu scrie cache, nu modifică metrici,
nu schimbă ordinea fallback-ului. `shadow_run_id`/`observed_at` NU există
aici — sunt generate exclusiv de infrastructură (shadow_recorder.py) la
momentul persistării; obiectele din acest modul rămân atemporale prin
construcție.

Dependency Direction: acest modul importă STRICT provider_registry,
provider_capabilities, league_mapping, provider_health — niciodată
supabase_client, key_manager, oracle_api, football_providers.
================================================================================
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable, Mapping

from provider_capabilities import DataType, supports
from provider_health import ProviderHealth, get_provider_health
from provider_registry import ProviderRegistry, get_provider_registry
from league_mapping import Confidence, LeagueProviderState, ProviderState, get_league_provider_state


# ────────────────────────────────────────────────────────────────────────────
# Formula de scor — constantă unică (ADR-034 §Decision, neschimbată)
# ────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SelectionWeights:
    availability: float
    coverage: float
    reliability: float
    quota: float
    latency: float
    priority: float
    # [ADAUGAT] ADR-041 Faza 1 — versiunea ACESTUI preset de ponderi, distinctă
    # de ALGORITHM_VERSION (care versionează structura formulei pe 6
    # componente, neschimbată). Fiecare preset (LIVE, BACKFILL, orice preset
    # viitor) își ține propria linie de versionare, incrementată DOAR manual,
    # la o recalibrare reală bazată pe date din shadow mode — niciodată
    # dedusă din git/commit. Scop: decizii istorice reproductibile — un
    # consumator care loghează (weights_name, weights.version) alături de o
    # decizie poate reconstitui exact ce calibrare a produs-o.
    version: int = 1

    def __post_init__(self) -> None:
        total = (self.availability + self.coverage + self.reliability
                  + self.quota + self.latency + self.priority)
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"SelectionWeights trebuie să însumeze 1.0, nu {total}")


# LIVE — implicit, folosit de oracle_api.py (shadow, ADR-034), neschimbat.
SELECTION_WEIGHTS = SelectionWeights(
    availability=0.40, coverage=0.25, reliability=0.15,
    quota=0.10, latency=0.05, priority=0.05,
    version=1,
)

# [ADAUGAT] BACKFILL — ADR-041 Faza 1. Prioritizează cota rămasă (0.40, cea
# mai mare pondere) și elimină latența (irelevantă pentru sincronizare
# offline) — opusul calibrării LIVE, aceeași formulă pe 6 componente,
# neschimbată (compute_weighted_total() rămâne identic). Motivează exact
# comportamentul cerut explicit: un backfill mare nu epuizează providerul
# premium rezervat pentru LIVE, ci se redistribuie spre cel cu cotă mai mare,
# pe măsură ce starea reală de cotă se actualizează între apeluri succesive.
SELECTION_WEIGHTS_BACKFILL = SelectionWeights(
    availability=0.20, coverage=0.15, reliability=0.15,
    quota=0.40, latency=0.00, priority=0.10,
    version=1,
)

# Se incrementează DOAR manual, la o recalibrare reală a STRUCTURII formulei
# (numărul/semnificația componentelor) — niciodată a valorilor unui preset,
# acelea își au propriul SelectionWeights.version — niciodată dedusă din
# git/commit/altă infrastructură (ar rupe Regula de Aur #4/#5).
ALGORITHM_VERSION = 1

# Tie-breaker static — neutru (0.5) pentru toți providerii până la o
# calibrare reală din date de shadow mode (ADR-034, §Consequences: "nu
# poate fi ghicită corect din prima"). Rămâne default-ul folosit când
# apelantul nu injectează un `priority_fn` propriu (vezi mai jos) — zero
# schimbare de comportament pentru orice cod existent.
_PROVIDER_PRIORITY: Mapping[str, float] = MappingProxyType({})


def _default_priority_fn(provider_id: str) -> float:
    return _PROVIDER_PRIORITY.get(provider_id, 0.5)

_LATENCY_REFERENCE_MS = 2000.0

_COVERAGE_BY_CONFIDENCE: Mapping[Confidence, float] = MappingProxyType({
    Confidence.CONFIRMED: 1.0,
    Confidence.DOCUMENTED: 0.75,
    Confidence.ASSUMED: 0.5,
    Confidence.UNKNOWN: 0.25,
})


# ────────────────────────────────────────────────────────────────────────────
# Obiecte de domeniu
# ────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ScoreComponents:
    availability: float
    coverage: float
    reliability: float
    quota: float
    latency: float
    priority: float

    def __post_init__(self) -> None:
        for name in ("availability", "coverage", "reliability", "quota", "latency", "priority"):
            value = getattr(self, name)
            if not (0.0 <= value <= 1.0):
                raise ValueError(f"ScoreComponents.{name}={value} trebuie să fie în [0.0, 1.0]")


@dataclass(frozen=True)
class ProviderScore:
    provider_id: str
    components: ScoreComponents
    total: float


@dataclass(frozen=True)
class CandidateProvider:
    """Provider ELIGIBIL pentru (league, data_type) — a trecut filtrarea
    tare. Separă explicit eligibilitatea de scorare (cerință explicită de
    design): un CandidateProvider nu are scor încă, doar dreptul de a fi
    scorat și, eventual, recomandat."""
    provider_id: str
    league: str
    data_type: DataType
    state: ProviderState
    confidence: Confidence

    def __post_init__(self) -> None:
        if self.state != ProviderState.AVAILABLE:
            raise ValueError(
                f"CandidateProvider nu poate exista pentru state={self.state!r} — "
                f"doar ProviderState.AVAILABLE trece filtrarea tare (PR5, decizie explicită)."
            )


@dataclass(frozen=True)
class RecommendationReason:
    # contribuții PONDERATE (recommended - current), per componentă — suma
    # lor reconstituie EXACT diferența de scor total (Regula de Aur #3).
    component_deltas: Mapping[str, float]


@dataclass(frozen=True)
class ProviderRecommendation:
    league: str
    data_type: DataType
    current_provider: str
    current_score: ProviderScore | None        # None doar dacă provider_id necunoscut Registry-ului
    recommended_provider: str | None           # None dacă niciun candidat trece filtrarea tare
    recommended_score: ProviderScore | None
    reason: RecommendationReason | None        # None dacă recommended_provider is None
    decision_changed: bool


@dataclass(frozen=True)
class ShadowObservation:
    """Formă de domeniu a unei observații shadow deja persistate — conversia
    din rândul brut de bază de date se face în shadow_recorder.py, niciodată
    aici (acest modul nu cunoaște Supabase)."""
    decision_changed: bool
    recommended_provider: str | None
    current_total: float | None
    recommended_total: float | None


@dataclass(frozen=True)
class ShadowStatistics:
    total_recommendations: int
    identical_recommendations: int
    different_recommendations: int
    provider_unavailable: int
    provider_better_than_current: int


# ────────────────────────────────────────────────────────────────────────────
# Funcții pure
# ────────────────────────────────────────────────────────────────────────────

def compute_weighted_total(components: ScoreComponents, weights: SelectionWeights = SELECTION_WEIGHTS) -> float:
    return (
        components.availability * weights.availability
        + components.coverage * weights.coverage
        + components.reliability * weights.reliability
        + components.quota * weights.quota
        + components.latency * weights.latency
        + components.priority * weights.priority
    )


def _coverage_component(mapping_state: LeagueProviderState | None, capability_supported: bool) -> float:
    if not capability_supported:
        return 0.0
    if mapping_state is None:
        return 0.0
    if mapping_state.state == ProviderState.AVAILABLE:
        return _COVERAGE_BY_CONFIDENCE[mapping_state.confidence]
    if mapping_state.state in (ProviderState.UNTESTED, ProviderState.UNKNOWN):
        return 0.1
    return 0.0  # UNAVAILABLE / PLAN_RESTRICTED / DEAD_KEY / QUOTA_EXHAUSTED


def _latency_component(avg_latency_ms: float | None) -> float:
    if avg_latency_ms is None:
        return 0.5
    return max(0.0, min(1.0, 1.0 - avg_latency_ms / _LATENCY_REFERENCE_MS))


def find_candidates(
    league: str, data_type: DataType, *,
    registry: ProviderRegistry | None = None,
    capabilities_fn: Callable[[str, DataType], bool] | None = None,
    league_state_fn: Callable[[str, str], LeagueProviderState | None] | None = None,
) -> tuple[CandidateProvider, ...]:
    registry = registry or get_provider_registry()
    capabilities_fn = capabilities_fn or supports
    league_state_fn = league_state_fn or get_league_provider_state

    candidates: list[CandidateProvider] = []
    for record in registry.list_providers():  # tuple fix, ordine deterministă
        if not registry.is_available(record.provider_id):
            continue
        if not capabilities_fn(record.provider_id, data_type):
            continue
        mapping_state = league_state_fn(league, record.provider_id)
        if mapping_state is None or mapping_state.state != ProviderState.AVAILABLE:
            continue
        candidates.append(CandidateProvider(
            provider_id=record.provider_id, league=league, data_type=data_type,
            state=mapping_state.state, confidence=mapping_state.confidence,
        ))
    return tuple(candidates)


def score_provider(
    provider_id: str, league: str, data_type: DataType, *,
    registry: ProviderRegistry | None = None,
    capabilities_fn: Callable[[str, DataType], bool] | None = None,
    league_state_fn: Callable[[str, str], LeagueProviderState | None] | None = None,
    health_fn: Callable[[str], ProviderHealth | None] | None = None,
    priority_fn: Callable[[str], float] | None = None,
    weights: SelectionWeights = SELECTION_WEIGHTS,
) -> ProviderScore | None:
    """General-purpose — funcționează pentru ORICE provider cunoscut
    Registry-ului, candidat sau nu (necesar pentru a putea scora providerul
    curent chiar și atunci când el e respins de filtrarea tare — altfel
    Reason n-ar putea explica de ce a pierdut).

    `priority_fn` [ADAUGAT ADR-041 Faza 1] — dependință injectabilă, exact
    tiparul deja folosit de `health_fn`/`league_state_fn` — NU o citire
    directă de Supabase aici (ar încălca "Dependency Direction" din
    docstring-ul modulului: acest fișier nu importă niciodată
    `supabase_client`). Implicit `_default_priority_fn` (tie-breaker static
    0.5, neschimbat) — un apelant din Sync Layer (`sync_provider_manager.py`,
    care POATE importa `supabase_client`) poate injecta o sursă de
    configurare externă, fără să atingă puritatea acestui modul."""
    registry = registry or get_provider_registry()
    capabilities_fn = capabilities_fn or supports
    league_state_fn = league_state_fn or get_league_provider_state
    if health_fn is None:
        health_fn = lambda pid: get_provider_health(pid, registry=registry)  # noqa: E731
    priority_fn = priority_fn or _default_priority_fn

    record = registry.get_provider(provider_id)
    if record is None:
        return None

    availability = 1.0 if registry.is_available(provider_id) else 0.0
    capability_supported = capabilities_fn(provider_id, data_type)
    mapping_state = league_state_fn(league, provider_id)
    coverage = _coverage_component(mapping_state, capability_supported)

    health = health_fn(provider_id)
    reliability = 0.5 if (health is None or health.reliability is None) else health.reliability
    quota = 1.0 if (health is None or health.quota_remaining_pct is None) else health.quota_remaining_pct / 100.0
    latency = _latency_component(health.avg_latency_ms if health is not None else None)
    priority = priority_fn(provider_id)

    components = ScoreComponents(
        availability=availability, coverage=coverage, reliability=reliability,
        quota=quota, latency=latency, priority=priority,
    )
    return ProviderScore(provider_id=provider_id, components=components,
                          total=compute_weighted_total(components, weights))


def _weighted_contribution(components: ScoreComponents, weights: SelectionWeights) -> dict[str, float]:
    # Ordine literală fixă — aceeași la fiecare apel (Regula de Aur #4).
    return {
        "availability": components.availability * weights.availability,
        "coverage": components.coverage * weights.coverage,
        "reliability": components.reliability * weights.reliability,
        "quota": components.quota * weights.quota,
        "latency": components.latency * weights.latency,
        "priority": components.priority * weights.priority,
    }


def _build_reason(current: ProviderScore | None, recommended: ProviderScore,
                   weights: SelectionWeights) -> RecommendationReason:
    rec_contrib = _weighted_contribution(recommended.components, weights)
    cur_contrib = ({k: 0.0 for k in rec_contrib} if current is None
                    else _weighted_contribution(current.components, weights))
    deltas = {k: rec_contrib[k] - cur_contrib[k] for k in rec_contrib}
    return RecommendationReason(component_deltas=MappingProxyType(deltas))


def recommend_provider(
    league: str, data_type: DataType, current_provider: str, *,
    registry: ProviderRegistry | None = None,
    capabilities_fn: Callable[[str, DataType], bool] | None = None,
    league_state_fn: Callable[[str, str], LeagueProviderState | None] | None = None,
    health_fn: Callable[[str], ProviderHealth | None] | None = None,
    priority_fn: Callable[[str], float] | None = None,
    weights: SelectionWeights = SELECTION_WEIGHTS,
) -> ProviderRecommendation:
    registry = registry or get_provider_registry()
    capabilities_fn = capabilities_fn or supports
    league_state_fn = league_state_fn or get_league_provider_state
    if health_fn is None:
        health_fn = lambda pid: get_provider_health(pid, registry=registry)  # noqa: E731
    priority_fn = priority_fn or _default_priority_fn

    candidates = find_candidates(league, data_type, registry=registry,
                                  capabilities_fn=capabilities_fn, league_state_fn=league_state_fn)

    best: ProviderScore | None = None
    for candidate in candidates:  # tuple, ordine fixă -> primul maxim câștigă determinist
        score = score_provider(candidate.provider_id, league, data_type,
                                registry=registry, capabilities_fn=capabilities_fn,
                                league_state_fn=league_state_fn, health_fn=health_fn,
                                priority_fn=priority_fn, weights=weights)
        if score is not None and (best is None or score.total > best.total):
            best = score

    current_score = score_provider(current_provider, league, data_type,
                                    registry=registry, capabilities_fn=capabilities_fn,
                                    league_state_fn=league_state_fn, health_fn=health_fn,
                                    priority_fn=priority_fn, weights=weights)

    if best is None:
        return ProviderRecommendation(
            league=league, data_type=data_type, current_provider=current_provider,
            current_score=current_score, recommended_provider=None, recommended_score=None,
            reason=None, decision_changed=False,
        )

    return ProviderRecommendation(
        league=league, data_type=data_type, current_provider=current_provider,
        current_score=current_score, recommended_provider=best.provider_id,
        recommended_score=best, reason=_build_reason(current_score, best, weights),
        decision_changed=best.provider_id != current_provider,
    )


def render_reason_text(recommendation: ProviderRecommendation) -> str:
    lines = ["Current provider:"]
    current_suffix = (f"  (scor total: {recommendation.current_score.total:.2f})"
                       if recommendation.current_score is not None else "  (scor indisponibil)")
    lines.append(f"    {recommendation.current_provider}{current_suffix}")
    lines.append("")
    lines.append("Recommendation:")
    if recommendation.recommended_provider is None:
        lines.append("    (niciun candidat eligibil)")
    else:
        lines.append(f"    {recommendation.recommended_provider}  "
                      f"(scor total: {recommendation.recommended_score.total:.2f})")
    if recommendation.reason is not None:
        lines.append("Reason:")
        for name, delta in recommendation.reason.component_deltas.items():
            sign = "+" if delta >= 0 else ""
            lines.append(f"    {name:<12} {sign}{delta:.2f}")
    lines.append(f"Decision changed:  {'YES' if recommendation.decision_changed else 'NO'}")
    return "\n".join(lines)


def compute_shadow_statistics(observations: list[ShadowObservation]) -> ShadowStatistics:
    total = len(observations)
    identical = sum(1 for o in observations if not o.decision_changed and o.recommended_provider is not None)
    different = sum(1 for o in observations if o.decision_changed)
    unavailable = sum(1 for o in observations if o.recommended_provider is None)
    better = sum(
        1 for o in observations
        if o.decision_changed and o.current_total is not None and o.recommended_total is not None
        and o.recommended_total > o.current_total
    )
    return ShadowStatistics(
        total_recommendations=total, identical_recommendations=identical,
        different_recommendations=different, provider_unavailable=unavailable,
        provider_better_than_current=better,
    )
