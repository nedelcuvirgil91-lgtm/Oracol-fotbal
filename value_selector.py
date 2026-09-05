"""
================================================================================
FOOTBALL ORACLE — Value Selector V1 (ADR-071)
================================================================================
Module: value_selector.py

Nucleul PUR al radarului de meciuri. Primeste candidaturi deja construite
(`SelectionCandidate`, vezi `value_selector_adapter.py`) si decide, printr-o
politica versionata, care dintre ele merita atentia utilizatorului.

Contract de produs (ADR-071): Top Value Bets e un RADAR de meciuri, nu un
sistem de recomandare a pariului. Iesirea e o lista scurta de meciuri pe care
proprietarul produsului le investigheaza manual; decizia de a paria si
executia raman integral in afara aplicatiei.

Doua concepte care NU se confunda niciodata:
  - VALUE      — cat de mult difera probabilitatea modelului de cea a pietei;
  - ACTIONABILITY — cat de mult merita selectia atentia utilizatorului.

Ordinea conceptuala a portilor (ADR-071 §8), respectata literal de
`_GATE_ORDER` de mai jos:
    VALID -> DATA QUALITY -> PLAUSIBILITY -> PROBABILITY -> VALUE -> ACTIONABILITY

Invarianti impusi de acest modul (verificati de tests/test_value_selector*.py):
  I1  Functie pura: fara I/O, fara retea, fara Supabase, fara ceas de sistem.
      `evaluated_at` si varstele sunt INJECTATE de apelant, niciodata citite aici.
  I2  Zero logica conditionata de tipul selectiei (1/X/2). Acest fisier nu
      contine niciun literal de selectie — simetria H/X/A e structurala, nu
      declarativa. Impus prin garda AST (`tests/test_value_selector_purity.py`).
  I3  `model_p` nu e modificat niciodata. `p_shr` e o marime interna a
      selectorului, expusa separat, folosita doar la ordonare.
  I4  Fiecare candidat primeste exact o categorie si, daca nu e TOP, cel putin
      un motiv dintr-un enum inchis.
  I5  Un candidat cu date insuficiente (`neutral`/fallback) NU devine niciodata
      LONGSHOT — merge la REJECTED. Longshot inseamna "valoare reala cu
      probabilitate mai mica", nu "date proaste".
  I6  Fara completare artificiala: daca trec 3 meciuri, se intorc 3, nu 5.
  I7  Orice schimbare de prag/pondere schimba `policy_id` — face verificabila
      mecanic regula "politica ramane inghetata pe durata F3".

NU importa `oracle_engine`, `oracle_api`, `feature_engine`, `ml_predictor`,
`supabase_client` sau `database.*` — dependinta "in sus" e interzisa
(North Star #10) si verificata prin garda AST.
================================================================================
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Callable, Iterable, Sequence

SELECTOR_VERSION = "v1"


# ── Vocabular inchis ─────────────────────────────────────────────────────────

class Verdict(str, Enum):
    """Verdictul unei porti. `UNKNOWN` inseamna "informatia lipseste" si NU
    respinge candidatul (Regula #8: o stare necunoscuta ramane necunoscuta, nu
    se aproximeaza nici spre PASS, nici spre FAIL). `NOT_APPLICABLE` inseamna
    "poarta nu e configurata in aceasta politica" — se vede in diagnostic ca
    nu a fost o trecere, ci o absenta."""
    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class GateId(str, Enum):
    ODDS_PRESENT = "odds_present"
    MARKET_OPEN = "market_open"
    ODDS_FRESH = "odds_fresh"
    PREDICTION_FRESH = "prediction_fresh"
    DATA_QUALITY = "data_quality"
    MIN_MATCHES_ANALYSED = "min_matches_analysed"
    RANK_IN_MATCH = "rank_in_match"
    MARKET_PLAUSIBILITY = "market_plausibility"
    PROBABILITY_FLOOR = "probability_floor"
    POSITIVE_VALUE = "positive_value"
    MIN_ABS_EDGE = "min_abs_edge"
    ODDS_CEILING = "odds_ceiling"
    LEGACY_RELATIVE_EDGE = "legacy_relative_edge"


class RejectionReason(str, Enum):
    ODDS_MISSING = "odds_missing"
    ODDS_INVALID = "odds_invalid"
    MARKET_CLOSED = "market_closed"
    ODDS_STALE = "odds_stale"
    PREDICTION_STALE = "prediction_stale"
    DATA_QUALITY_INSUFFICIENT = "data_quality_insufficient"
    INSUFFICIENT_HISTORY = "insufficient_history"
    NOT_MODEL_LEADER = "not_model_leader"
    MARKET_IMPLAUSIBLE = "market_implausible"
    BELOW_PROBABILITY_FLOOR = "below_probability_floor"
    NON_POSITIVE_VALUE = "non_positive_value"
    BELOW_ABS_EDGE = "below_abs_edge"
    ABOVE_ODDS_CEILING = "above_odds_ceiling"
    BELOW_LEGACY_RELATIVE_EDGE = "below_legacy_relative_edge"
    OUTRANKED_TOP_N = "outranked_top_n"
    OUTRANKED_SAME_MATCH = "outranked_same_match"


class Category(str, Enum):
    TOP = "top"
    LONGSHOT = "longshot"
    REJECTED = "rejected"


_GATE_REASON: dict[GateId, RejectionReason] = {
    GateId.ODDS_PRESENT: RejectionReason.ODDS_INVALID,
    GateId.MARKET_OPEN: RejectionReason.MARKET_CLOSED,
    GateId.ODDS_FRESH: RejectionReason.ODDS_STALE,
    GateId.PREDICTION_FRESH: RejectionReason.PREDICTION_STALE,
    GateId.DATA_QUALITY: RejectionReason.DATA_QUALITY_INSUFFICIENT,
    GateId.MIN_MATCHES_ANALYSED: RejectionReason.INSUFFICIENT_HISTORY,
    GateId.RANK_IN_MATCH: RejectionReason.NOT_MODEL_LEADER,
    GateId.MARKET_PLAUSIBILITY: RejectionReason.MARKET_IMPLAUSIBLE,
    GateId.PROBABILITY_FLOOR: RejectionReason.BELOW_PROBABILITY_FLOOR,
    GateId.POSITIVE_VALUE: RejectionReason.NON_POSITIVE_VALUE,
    GateId.MIN_ABS_EDGE: RejectionReason.BELOW_ABS_EDGE,
    GateId.ODDS_CEILING: RejectionReason.ABOVE_ODDS_CEILING,
    GateId.LEGACY_RELATIVE_EDGE: RejectionReason.BELOW_LEGACY_RELATIVE_EDGE,
}

# Portile de "marime/risc": o cadere EXCLUSIV pe ele inseamna "valoare reala,
# probabilitate mai mica" -> LONGSHOT. Orice alta cadere (validitate, calitate
# a datelor, istoric insuficient, valoare nepozitiva) inseamna ca informatia
# insasi nu e buna -> REJECTED, niciodata LONGSHOT (ADR-071 §13).
_LONGSHOT_GATES: frozenset[GateId] = frozenset({
    GateId.RANK_IN_MATCH,
    GateId.MARKET_PLAUSIBILITY,
    GateId.PROBABILITY_FLOOR,
    GateId.ODDS_CEILING,
})

# Ordinea conceptuala din ADR-071 §8. Portile se evalueaza TOATE, niciodata cu
# scurt-circuit — altfel lista de motive ar fi incompleta si diagnosticul din
# F2 ar pierde exact informatia pentru care exista.
_GATE_ORDER: tuple[GateId, ...] = (
    GateId.ODDS_PRESENT,
    GateId.MARKET_OPEN,
    GateId.ODDS_FRESH,
    GateId.PREDICTION_FRESH,
    GateId.DATA_QUALITY,
    GateId.MIN_MATCHES_ANALYSED,
    GateId.RANK_IN_MATCH,
    GateId.MARKET_PLAUSIBILITY,
    GateId.PROBABILITY_FLOOR,
    GateId.POSITIVE_VALUE,
    GateId.MIN_ABS_EDGE,
    GateId.ODDS_CEILING,
    GateId.LEGACY_RELATIVE_EDGE,
)

MIN_VALID_ODDS = 1.01


# ── Contracte de date ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SelectionCandidate:
    """O selectie posibila a unui meci, deja adaptata din `MatchPrediction`.

    `selection_code` e o eticheta OPACA pentru acest modul — e transportata si
    raportata, niciodata comparata cu o valoare literala. Simetria H/X/A vine
    din faptul ca nu exista niciun cod care sa o inspecteze.

    Campurile de varsta si `seconds_to_kickoff` sunt INJECTATE de apelant
    (I1). `None` inseamna "nu stim", nu "e in regula"."""
    fixture_id: str
    match_label: str
    league: str
    kickoff_utc: str
    market: str
    selection_code: str
    selection_label: str
    model_p: float
    fair_p: float
    bk_odds: float
    bookmaker: str | None = None
    data_quality: str | None = None
    data_quality_is_sufficient: bool | None = None
    matches_analysed: int | None = None
    prediction_age_s: float | None = None
    odds_age_s: float | None = None
    seconds_to_kickoff: float | None = None


@dataclass(frozen=True)
class CandidateMetrics:
    e_abs_pp: float
    e_rel_pct: float
    p_shr: float
    ev_raw: float
    ev_shr: float
    rank_in_match: int


@dataclass(frozen=True)
class GateResult:
    gate_id: GateId
    verdict: Verdict
    detail: str | None = None


@dataclass(frozen=True)
class ScoredCandidate:
    candidate: SelectionCandidate
    metrics: CandidateMetrics
    gates: tuple[GateResult, ...]
    score: float
    category: Category
    rejection_reasons: tuple[RejectionReason, ...] = ()
    rank_in_day: int | None = None


@dataclass(frozen=True)
class SelectorStats:
    n_input: int
    n_candidates: int
    n_top: int
    n_longshot: int
    n_rejected: int
    rejections_by_reason: dict[str, int] = field(default_factory=dict)
    gates_unknown: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class SelectorResult:
    policy_id: str
    ranker_id: str
    top: tuple[ScoredCandidate, ...]
    longshot: tuple[ScoredCandidate, ...]
    rejected: tuple[ScoredCandidate, ...]
    stats: SelectorStats


# ── Politica ─────────────────────────────────────────────────────────────────

# Campurile care influenteaza EFECTIV selectia — si numai ele — intra in
# amprenta `policy_id`. Flagurile de activare/logare nu schimba ce s-ar fi
# selectat, deci nu au ce cauta acolo.
_POLICY_SELECTION_FIELDS: tuple[str, ...] = (
    "shrinkage_w",
    "require_rank_one",
    "market_plausibility_floor",
    "probability_floor",
    "min_abs_edge_pp",
    "odds_ceiling",
    "require_sufficient_data_quality",
    "min_matches_analysed",
    "max_odds_age_s",
    "max_prediction_age_s",
    "require_positive_value",
    "legacy_relative_edge_floor_pct",
    "top_n_matches",
    "one_selection_per_match",
    "ranker_id",
)


@dataclass(frozen=True)
class SelectorPolicy:
    """Toate pragurile sunt `None`/`False` implicit: politica implicita e
    permisiva si reproduce comportamentul istoric (profilul `legacy`).
    Nicio poarta noua nu porneste activa (North Star #3)."""
    profile: str = "legacy"
    ranker_id: str = "legacy_relative_edge"
    shrinkage_w: float = 1.0
    require_rank_one: bool = False
    market_plausibility_floor: float | None = None
    probability_floor: float | None = None
    min_abs_edge_pp: float | None = None
    odds_ceiling: float | None = None
    require_sufficient_data_quality: bool = False
    min_matches_analysed: int | None = None
    max_odds_age_s: float | None = None
    max_prediction_age_s: float | None = None
    require_positive_value: bool = False
    legacy_relative_edge_floor_pct: float | None = 5.0
    top_n_matches: int | None = None
    one_selection_per_match: bool = False

    def fingerprint(self) -> str:
        payload = {name: getattr(self, name) for name in _POLICY_SELECTION_FIELDS}
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:8]

    @property
    def policy_id(self) -> str:
        return f"{self.profile}@{SELECTOR_VERSION}:{self.fingerprint()}"


LEGACY_POLICY = SelectorPolicy()


# ── Shrinkage (familia w) ────────────────────────────────────────────────────

def shrink_probability(model_p: float, fair_p: float, w: float) -> float:
    """`p_shr = w·p + (1−w)·f`.

    `w = 1.0` -> increderea totala in model (identic cu `p`).
    `w = 0.0` -> control market-only (identic cu `f`).

    ATENTIE, proprietate matematica documentata deliberat: la `w = 0`,
    `ev_shr = f·cota − 1 = 1/S − 1 < 0` pentru ORICE selectie (unde `S` e suma
    probabilitatilor implicite brute, mereu > 1 din cauza marjei). Deci un
    control market-only NU poate folosi o poarta pe EV pozitiv — ar selecta
    mereu multimea vida. Controlul de piata foloseste ordonare dupa `p_shr`,
    fara poarta de valoare pozitiva. Nu e un defect de reparat."""
    if not 0.0 <= w <= 1.0:
        raise ValueError(f"shrinkage_w trebuie sa fie in [0,1], primit {w!r}")
    return w * model_p + (1.0 - w) * fair_p


# ── Metrici ──────────────────────────────────────────────────────────────────

def compute_metrics(candidate: SelectionCandidate, *, w: float, rank_in_match: int) -> CandidateMetrics:
    p = candidate.model_p
    f = candidate.fair_p
    odds = candidate.bk_odds
    p_shr = shrink_probability(p, f, w)
    e_rel = ((p - f) / f * 100.0) if f > 0 else 0.0
    return CandidateMetrics(
        e_abs_pp=(p - f) * 100.0,
        e_rel_pct=e_rel,
        p_shr=p_shr,
        ev_raw=p * odds - 1.0,
        ev_shr=p_shr * odds - 1.0,
        rank_in_match=rank_in_match,
    )


# ── Rankere ──────────────────────────────────────────────────────────────────
# Fiecare ranker e o functie pura (metrici, candidat) -> scor. Niciunul nu
# inspecteaza tipul selectiei. Se compara prospectiv in F2 — niciunul nu e
# declarat castigator aici.

_ABS_EDGE_NORMALISER_PP = 20.0   # 20 pp = saturatie a componentei de valoare
_ABS_EDGE_COEFFICIENT = 0.25     # ponderea maxima a valorii in ranker-ul B


def _rank_probability_first(m: CandidateMetrics, c: SelectionCandidate) -> float:
    """A — probabilitate contractata, atat. Valoarea ramane departajare."""
    return m.p_shr


def _rank_probability_plus_value(m: CandidateMetrics, c: SelectionCandidate) -> float:
    """B — probabilitate + valoare absoluta normalizata si plafonata."""
    value_component = min(max(m.e_abs_pp, 0.0) / _ABS_EDGE_NORMALISER_PP, 1.0)
    return m.p_shr + value_component * _ABS_EDGE_COEFFICIENT


def _rank_shrunk_ev(m: CandidateMetrics, c: SelectionCandidate) -> float:
    """C — EV contractat, ponderat cu probabilitatea contractata.

    Se pastreaza ca varianta experimentala pentru F2, NU ca ranker implicit:
    masurat pe date reale, un ranker pe EV promoveaza exact divergentele
    extreme model-vs-piata (cota mare × probabilitate pretinsa mare), adica
    reproduce patologia edge-ului relativ intr-o alta forma."""
    return m.ev_shr * m.p_shr


def _rank_market_controlled(m: CandidateMetrics, c: SelectionCandidate) -> float:
    """D — identic formal cu A; exista ca id separat pentru ca in F2 sa poata
    fi perechea "acelasi ranker, alta poarta de piata", comparabila direct."""
    return m.p_shr


def _rank_legacy_relative_edge(m: CandidateMetrics, c: SelectionCandidate) -> float:
    """E — baseline obligatoriu: exact ordonarea din productie de azi."""
    return m.e_rel_pct


RANKERS: dict[str, Callable[[CandidateMetrics, SelectionCandidate], float]] = {
    "probability_first": _rank_probability_first,
    "probability_plus_value": _rank_probability_plus_value,
    "shrunk_ev": _rank_shrunk_ev,
    "market_controlled": _rank_market_controlled,
    "legacy_relative_edge": _rank_legacy_relative_edge,
}


# ── Porti ────────────────────────────────────────────────────────────────────

def _gate_threshold(value: float | None, threshold: float | None, *,
                    gate: GateId, label: str, at_least: bool) -> GateResult:
    if threshold is None:
        return GateResult(gate, Verdict.NOT_APPLICABLE)
    if value is None:
        return GateResult(gate, Verdict.UNKNOWN, f"{label} necunoscut")
    ok = value >= threshold if at_least else value <= threshold
    detail = f"{label}={value:.4g} {'>=' if at_least else '<='} {threshold:.4g}"
    return GateResult(gate, Verdict.PASS if ok else Verdict.FAIL, detail)


def evaluate_gates(candidate: SelectionCandidate, metrics: CandidateMetrics,
                   policy: SelectorPolicy) -> tuple[GateResult, ...]:
    """Evalueaza TOATE portile, in ordinea conceptuala din ADR-071 §8, fara
    scurt-circuit. Rezultatul e complet chiar si pentru un candidat care a
    cazut la prima poarta — asta face diagnosticul din F2 utilizabil."""
    results: dict[GateId, GateResult] = {}

    # 1. VALID
    odds = candidate.bk_odds
    if odds is None or odds <= 0:
        results[GateId.ODDS_PRESENT] = GateResult(GateId.ODDS_PRESENT, Verdict.FAIL, "cota lipsa")
    elif odds <= MIN_VALID_ODDS:
        results[GateId.ODDS_PRESENT] = GateResult(GateId.ODDS_PRESENT, Verdict.FAIL, f"cota={odds:.4g}")
    else:
        results[GateId.ODDS_PRESENT] = GateResult(GateId.ODDS_PRESENT, Verdict.PASS)

    if candidate.seconds_to_kickoff is None:
        results[GateId.MARKET_OPEN] = GateResult(GateId.MARKET_OPEN, Verdict.UNKNOWN, "timp pana la start necunoscut")
    else:
        open_ = candidate.seconds_to_kickoff > 0
        results[GateId.MARKET_OPEN] = GateResult(
            GateId.MARKET_OPEN, Verdict.PASS if open_ else Verdict.FAIL,
            f"secunde_pana_la_start={candidate.seconds_to_kickoff:.0f}")

    results[GateId.ODDS_FRESH] = _gate_threshold(
        candidate.odds_age_s, policy.max_odds_age_s,
        gate=GateId.ODDS_FRESH, label="varsta_cota_s", at_least=False)
    results[GateId.PREDICTION_FRESH] = _gate_threshold(
        candidate.prediction_age_s, policy.max_prediction_age_s,
        gate=GateId.PREDICTION_FRESH, label="varsta_predictie_s", at_least=False)

    # 2. DATA QUALITY
    if not policy.require_sufficient_data_quality:
        results[GateId.DATA_QUALITY] = GateResult(GateId.DATA_QUALITY, Verdict.NOT_APPLICABLE)
    elif candidate.data_quality_is_sufficient is None:
        results[GateId.DATA_QUALITY] = GateResult(GateId.DATA_QUALITY, Verdict.UNKNOWN, "calitate necunoscuta")
    else:
        ok = bool(candidate.data_quality_is_sufficient)
        results[GateId.DATA_QUALITY] = GateResult(
            GateId.DATA_QUALITY, Verdict.PASS if ok else Verdict.FAIL,
            f"calitate={candidate.data_quality or 'necunoscuta'}")

    results[GateId.MIN_MATCHES_ANALYSED] = _gate_threshold(
        None if candidate.matches_analysed is None else float(candidate.matches_analysed),
        None if policy.min_matches_analysed is None else float(policy.min_matches_analysed),
        gate=GateId.MIN_MATCHES_ANALYSED, label="meciuri_analizate", at_least=True)

    # 3. PLAUSIBILITY
    if not policy.require_rank_one:
        results[GateId.RANK_IN_MATCH] = GateResult(GateId.RANK_IN_MATCH, Verdict.NOT_APPLICABLE)
    else:
        ok = metrics.rank_in_match == 1
        results[GateId.RANK_IN_MATCH] = GateResult(
            GateId.RANK_IN_MATCH, Verdict.PASS if ok else Verdict.FAIL,
            f"rang_in_meci={metrics.rank_in_match}")

    results[GateId.MARKET_PLAUSIBILITY] = _gate_threshold(
        candidate.fair_p, policy.market_plausibility_floor,
        gate=GateId.MARKET_PLAUSIBILITY, label="prob_piata", at_least=True)

    # 4. PROBABILITY
    results[GateId.PROBABILITY_FLOOR] = _gate_threshold(
        candidate.model_p, policy.probability_floor,
        gate=GateId.PROBABILITY_FLOOR, label="prob_model", at_least=True)

    # 5. VALUE
    if not policy.require_positive_value:
        results[GateId.POSITIVE_VALUE] = GateResult(GateId.POSITIVE_VALUE, Verdict.NOT_APPLICABLE)
    else:
        ok = metrics.e_abs_pp > 0
        results[GateId.POSITIVE_VALUE] = GateResult(
            GateId.POSITIVE_VALUE, Verdict.PASS if ok else Verdict.FAIL,
            f"e_abs_pp={metrics.e_abs_pp:.2f}")

    results[GateId.MIN_ABS_EDGE] = _gate_threshold(
        metrics.e_abs_pp, policy.min_abs_edge_pp,
        gate=GateId.MIN_ABS_EDGE, label="e_abs_pp", at_least=True)

    # 6. ACTIONABILITY
    results[GateId.ODDS_CEILING] = _gate_threshold(
        candidate.bk_odds, policy.odds_ceiling,
        gate=GateId.ODDS_CEILING, label="cota", at_least=False)

    results[GateId.LEGACY_RELATIVE_EDGE] = _gate_threshold(
        metrics.e_rel_pct, policy.legacy_relative_edge_floor_pct,
        gate=GateId.LEGACY_RELATIVE_EDGE, label="e_rel_pct", at_least=True)

    return tuple(results[gate_id] for gate_id in _GATE_ORDER)


def _failed_gates(gates: Sequence[GateResult]) -> tuple[GateId, ...]:
    return tuple(g.gate_id for g in gates if g.verdict is Verdict.FAIL)


def classify(gates: Sequence[GateResult]) -> tuple[Category, tuple[RejectionReason, ...]]:
    """TOP daca nicio poarta nu a cazut. LONGSHOT doar daca TOATE caderile sunt
    porti de marime/risc. Orice cadere pe validitate/calitate/istoric/valoare
    trimite la REJECTED — inclusiv atunci cand exista si o cadere de tip
    longshot (I5: datele proaste nu devin niciodata "value cu risc mai mare")."""
    failed = _failed_gates(gates)
    if not failed:
        return Category.TOP, ()
    reasons = tuple(_GATE_REASON[g] for g in failed)
    if all(g in _LONGSHOT_GATES for g in failed):
        return Category.LONGSHOT, reasons
    return Category.REJECTED, reasons


# ── Selectie ─────────────────────────────────────────────────────────────────

def _rank_within_matches(candidates: Sequence[SelectionCandidate]) -> dict[int, int]:
    """Rangul fiecarei selectii in meciul ei, dupa `model_p` descrescator.
    Cheia e `id()` pozitional (indexul in secventa), nu obiectul — candidatii
    sunt frozen dataclasses, deci egali structural s-ar putea ciocni.

    Departajare determinista la probabilitati egale: ordinea de intrare. Nu
    exista nicio referire la tipul selectiei (I2)."""
    by_fixture: dict[str, list[int]] = {}
    for index, candidate in enumerate(candidates):
        by_fixture.setdefault(candidate.fixture_id, []).append(index)

    ranks: dict[int, int] = {}
    for indices in by_fixture.values():
        ordered = sorted(indices, key=lambda i: (-candidates[i].model_p, i))
        for position, index in enumerate(ordered, start=1):
            ranks[index] = position
    return ranks


def _sort_key(scored: ScoredCandidate) -> tuple:
    """Ordonare total determinata (I7 al designului): scor, apoi valoare
    absoluta, apoi identitate stabila. Doua rulari pe aceleasi intrari produc
    exact aceeasi lista."""
    return (
        -scored.score,
        -scored.metrics.e_abs_pp,
        scored.candidate.fixture_id,
        scored.candidate.selection_code,
    )


def select(candidates: Sequence[SelectionCandidate],
           policy: SelectorPolicy = LEGACY_POLICY) -> SelectorResult:
    """Aplica politica pe candidaturile UNEI ferestre de selectie (tipic: o zi).
    Apelantul grupeaza pe zi — vezi `select_by_day()`.

    Nu completeaza niciodata lista: daca trec 3 meciuri, se intorc 3 (I6)."""
    ranker = RANKERS.get(policy.ranker_id)
    if ranker is None:
        raise ValueError(f"ranker necunoscut: {policy.ranker_id!r}")

    ranks = _rank_within_matches(candidates)

    scored: list[ScoredCandidate] = []
    for index, candidate in enumerate(candidates):
        metrics = compute_metrics(candidate, w=policy.shrinkage_w, rank_in_match=ranks[index])
        gates = evaluate_gates(candidate, metrics, policy)
        category, reasons = classify(gates)
        scored.append(ScoredCandidate(
            candidate=candidate, metrics=metrics, gates=gates,
            score=ranker(metrics, candidate), category=category,
            rejection_reasons=reasons,
        ))

    eligible = sorted([s for s in scored if s.category is Category.TOP], key=_sort_key)
    others = [s for s in scored if s.category is not Category.TOP]

    top: list[ScoredCandidate] = []
    demoted: list[ScoredCandidate] = []
    seen_fixtures: set[str] = set()
    for scored_candidate in eligible:
        fixture_id = scored_candidate.candidate.fixture_id
        if policy.one_selection_per_match and fixture_id in seen_fixtures:
            demoted.append(_demote(scored_candidate, RejectionReason.OUTRANKED_SAME_MATCH))
            continue
        if policy.top_n_matches is not None and len(seen_fixtures) >= policy.top_n_matches \
                and fixture_id not in seen_fixtures:
            demoted.append(_demote(scored_candidate, RejectionReason.OUTRANKED_TOP_N))
            continue
        seen_fixtures.add(fixture_id)
        top.append(ScoredCandidate(
            candidate=scored_candidate.candidate, metrics=scored_candidate.metrics,
            gates=scored_candidate.gates, score=scored_candidate.score,
            category=Category.TOP, rejection_reasons=(), rank_in_day=len(top) + 1,
        ))

    longshot = tuple(sorted([s for s in others if s.category is Category.LONGSHOT], key=_sort_key))
    rejected = tuple(sorted(
        [s for s in others if s.category is Category.REJECTED] + demoted, key=_sort_key))

    return SelectorResult(
        policy_id=policy.policy_id, ranker_id=policy.ranker_id,
        top=tuple(top), longshot=longshot, rejected=rejected,
        stats=_build_stats(scored, top, longshot, rejected),
    )


def _demote(scored: ScoredCandidate, reason: RejectionReason) -> ScoredCandidate:
    return ScoredCandidate(
        candidate=scored.candidate, metrics=scored.metrics, gates=scored.gates,
        score=scored.score, category=Category.REJECTED,
        rejection_reasons=scored.rejection_reasons + (reason,), rank_in_day=None,
    )


def _build_stats(scored: Sequence[ScoredCandidate], top: Sequence[ScoredCandidate],
                 longshot: Sequence[ScoredCandidate],
                 rejected: Sequence[ScoredCandidate]) -> SelectorStats:
    reasons: dict[str, int] = {}
    for item in list(longshot) + list(rejected):
        for reason in item.rejection_reasons:
            reasons[reason.value] = reasons.get(reason.value, 0) + 1
    unknown: dict[str, int] = {}
    for item in scored:
        for gate in item.gates:
            if gate.verdict is Verdict.UNKNOWN:
                unknown[gate.gate_id.value] = unknown.get(gate.gate_id.value, 0) + 1
    n_candidates = sum(1 for s in scored if s.metrics.e_abs_pp > 0)
    return SelectorStats(
        n_input=len(scored), n_candidates=n_candidates, n_top=len(top),
        n_longshot=len(longshot), n_rejected=len(rejected),
        rejections_by_reason=reasons, gates_unknown=unknown,
    )


def select_by_day(candidates: Sequence[SelectionCandidate],
                  policy: SelectorPolicy = LEGACY_POLICY) -> dict[str, SelectorResult]:
    """Grupeaza pe ziua calendaristica a loviturii de start (primele 10
    caractere din `kickoff_utc`, format ISO) si aplica `select()` pe fiecare zi.
    Plafonul de meciuri e per zi, nu pe tot setul."""
    by_day: dict[str, list[SelectionCandidate]] = {}
    for candidate in candidates:
        by_day.setdefault((candidate.kickoff_utc or "")[:10], []).append(candidate)
    return {day: select(items, policy) for day, items in sorted(by_day.items())}


# ── Contract de iesire pentru shadow (F2) ────────────────────────────────────

def to_shadow_rows(result: SelectorResult, *, run_id: str, evaluated_at: str,
                   policy: SelectorPolicy) -> list[dict]:
    """Serializeaza TOATE deciziile — acceptate, longshot si respinse — intr-o
    lista de dict-uri gata de persistat de un scriitor din F2. Functie pura:
    nu scrie nimic, nu citeste ceasul, `evaluated_at` e injectat.

    `leakage_suspect` e calculat aici, nu de scriitor: o decizie luata dupa
    lovitura de start nu poate intra intr-o evaluare prospectiva."""
    rows: list[dict] = []
    for bucket in (result.top, result.longshot, result.rejected):
        for item in bucket:
            candidate = item.candidate
            seconds = candidate.seconds_to_kickoff
            rows.append({
                "run_id": run_id,
                "evaluated_at": evaluated_at,
                "policy_id": result.policy_id,
                "policy_profile": policy.profile,
                "ranker_id": result.ranker_id,
                "shrinkage_w": policy.shrinkage_w,
                "fixture_id": candidate.fixture_id,
                "match_label": candidate.match_label,
                "league": candidate.league,
                "kickoff_utc": candidate.kickoff_utc,
                "market": candidate.market,
                "selection_code": candidate.selection_code,
                "model_p": candidate.model_p,
                "fair_p": candidate.fair_p,
                "bk_odds": candidate.bk_odds,
                "bookmaker": candidate.bookmaker,
                "e_abs_pp": item.metrics.e_abs_pp,
                "e_rel_pct": item.metrics.e_rel_pct,
                "p_shr": item.metrics.p_shr,
                "ev_raw": item.metrics.ev_raw,
                "ev_shr": item.metrics.ev_shr,
                "rank_in_match": item.metrics.rank_in_match,
                "actionability_score": item.score,
                "rank_in_day": item.rank_in_day,
                "category": item.category.value,
                "rejection_reasons": [r.value for r in item.rejection_reasons],
                "gate_results": {g.gate_id.value: g.verdict.value for g in item.gates},
                "gate_details": {g.gate_id.value: g.detail for g in item.gates if g.detail},
                "data_quality": candidate.data_quality,
                "matches_analysed": candidate.matches_analysed,
                "prediction_age_s": candidate.prediction_age_s,
                "odds_age_s": candidate.odds_age_s,
                "seconds_to_kickoff": seconds,
                "leakage_suspect": None if seconds is None else seconds <= 0,
            })
    return rows


def explain(item: ScoredCandidate) -> str:
    """Motivul principal, in limbaj natural, pentru coloana "DE CE acest meci".
    Pentru TOP descrie ce a facut selectia interesanta; pentru restul, prima
    poarta cazuta."""
    if item.category is Category.TOP:
        return (f"model {item.candidate.model_p * 100:.1f}% vs piata "
                f"{item.candidate.fair_p * 100:.1f}% (+{item.metrics.e_abs_pp:.1f} pp), "
                f"rezultatul cel mai probabil al modelului")
    if item.rejection_reasons:
        return item.rejection_reasons[0].value
    return "fara motiv inregistrat"
