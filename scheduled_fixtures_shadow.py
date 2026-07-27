"""
================================================================================
FOOTBALL ORACLE — Scheduled Fixtures Shadow (R-Sync-7b, ADR-039/ADR-040)
================================================================================
Module: scheduled_fixtures_shadow.py

Comparație strict observațională între calea live de discovery
(`oracle_api.get_matches_for_week()`) și stratul canonic de persistare
introdus la R-Sync-7a (`scheduled_fixtures`). Nu modifică niciodată
`matches`, nu influențează nicio decizie.

[G2, ADR-040, principiul 1 — evaluator PUR, decizie explicită proprietar
produs] `evaluate()` NU face I/O, NU face SQL, NU loghează — produce
STRICT un `ScheduledFixturesShadowReport`. Persistența (`equivalence_
governance.persist_equivalence_evaluation()` → `database.queries.
upsert_equivalence_evaluation()`) și orchestrarea (hook-ul din
`oracle_api.py`) trăiesc în alte module. Fluxul complet:

    matches live -> evaluate() -> ScheduledFixturesShadowReport
        -> equivalence_governance.persist_equivalence_evaluation()
        -> database.queries.upsert_equivalence_evaluation()
        -> equivalence_evaluations (Supabase)

[DELIBERAT] `evaluate()` primește lista COMPLETĂ de rânduri din
`scheduled_fixtures` pentru fereastra de date (via
`database.queries.list_scheduled_fixtures(d_from, d_to)`), nu lookup-uri
punctuale per meci live — un lookup punctual nu poate produce niciodată
`missing_live` nevid. Detectarea meciurilor „fantomă" cere enumerarea
completă a tabelei pentru fereastră.

Demo Mode (`source` care începe cu "demo-") exclus explicit din comparație
— scheduled_fixtures nu conține niciodată meciuri demo.

`provider_breakdown` (G2, ADR-040 principiul 3) e construit AUTOMAT din
setul de valori `source` întâlnite efectiv în `matches` — nicio listă
fixă de provideri folosită pentru iterare/raportare. `_PROVIDER_FIELD_MAP`
de mai jos rămâne cunoaștere de schemă (care coloană din
`scheduled_fixtures` corespunde cărui câmp live, per provider) —
inevitabilă pentru un evaluator legat de o singură entitate, dar NU
folosită ca sursă a listei de provideri raportate.

`exception_policy` (G2, ADR-040 principiul 5): `KNOWN_EXCEPTIONS` — un
registru static, în cod, al diferențelor de câmp CUNOSCUTE și tolerate,
cu severitate (SAFE/EXPECTED/WARNING). `provider_id_differences` NU intră
niciodată în acest registru — sunt CRITICAL prin construcția codului
(ar viola invariantul COALESCE-only al FixtureMergePolicy, migrarea 023).
================================================================================
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import equivalence_root_cause as root_cause
from mappings import match_key

MAX_EXAMPLES = 20

_GOVERNED_FIELDS: tuple[str, ...] = ("league", "kickoff_utc", "venue_city")

# "source" (câmpul din dict-ul de meci produs de oracle_api.py) -> provider_id
# canonic + lista (câmp_live, coloană_scheduled_fixtures) de identificatori
# proprii providerului respectiv. Un singur meci live provine mereu de la UN
# singur provider (primul care l-a raportat în _add()) — comparăm doar
# identificatorii providerului care a produs acel meci.
_PROVIDER_FIELD_MAP: dict[str, dict] = {
    "freelivefootball": {
        "provider_id": "freelf",
        "ids": (
            ("_freelf_event_id", "freelf_event_id"),
            ("home_team_id", "freelf_home_team_id"),
            ("away_team_id", "freelf_away_team_id"),
        ),
    },
    "the-odds-api": {
        "provider_id": "oddsapi",
        "ids": (
            ("_odds_api_id", "odds_api_event_id"),
            ("_sport_key", "odds_api_sport_key"),
        ),
    },
    "football-data.org": {
        "provider_id": "fd",
        "ids": (
            ("home_team_id", "fd_home_team_id"),
            ("away_team_id", "fd_away_team_id"),
        ),
    },
    "espn": {
        "provider_id": "espn",
        "ids": (
            ("home_team_id", "espn_home_team_id"),
            ("away_team_id", "espn_away_team_id"),
        ),
    },
    "thesportsdb": {
        "provider_id": "tsdb",
        "ids": (
            ("home_team_id", "tsdb_home_team_id"),
            ("away_team_id", "tsdb_away_team_id"),
        ),
    },
    "apifootball": {
        "provider_id": "apifootball",
        "ids": (
            ("fixture_id", "apifootball_fixture_id"),
            ("home_team_id", "apifootball_home_team_id"),
            ("away_team_id", "apifootball_away_team_id"),
        ),
    },
}

# (field, source) -> politică. Extensibil prin adăugarea unei intrări, nu prin
# atingerea logicii de mai jos (ADR-040, principiul 5). CRITICAL nu apare
# niciodată aici prin construcție — provider_id_differences nu consultă
# deloc acest registru (vezi bucla din evaluate()).
KNOWN_EXCEPTIONS: dict[tuple[str, str], str] = {
    # R-Sync-7a: football-data.org nu are oraș (doar țară în payload).
    ("venue_city", "football-data.org"): "SAFE",
    # R-Sync-7a: _fetch_matches_fd() nu apelează normalize_league_name().
    ("league", "football-data.org"): "SAFE",
    # R-Sync-7a: kickoff_utc nu are ierarhie de calitate -- niciun provider
    # nu are un defect demonstrat, doar tie-break determinist arbitrar.
    ("kickoff_utc", "freelivefootball"): "EXPECTED",
    ("kickoff_utc", "the-odds-api"): "EXPECTED",
    ("kickoff_utc", "football-data.org"): "EXPECTED",
    ("kickoff_utc", "espn"): "EXPECTED",
    ("kickoff_utc", "thesportsdb"): "EXPECTED",
    ("kickoff_utc", "apifootball"): "EXPECTED",
}

_ACCEPTED_POLICIES = frozenset({"SAFE", "EXPECTED", "WARNING"})


@dataclass
class ScheduledFixturesShadowReport:
    timestamp: str
    live_count: int
    scheduled_count: int
    matched: int
    # Eșantioane plafonate (max MAX_EXAMPLES) mai jos -- pentru numărul REAL,
    # folosiți întotdeauna câmpurile `*_count`, NU len() pe liste (ar
    # subnumăra dacă diferențele reale depășesc plafonul de eșantionare).
    missing_scheduled_count: int = 0
    missing_live_count: int = 0
    field_difference_count: int = 0
    provider_id_difference_count: int = 0
    accepted_exception_count: int = 0
    # prezente în calea live, lipsă din scheduled_fixtures (top MAX_EXAMPLES)
    missing_scheduled: list[str] = field(default_factory=list)
    # prezente în scheduled_fixtures, lipsă din calea live (top MAX_EXAMPLES)
    missing_live: list[str] = field(default_factory=list)
    field_differences: list[dict] = field(default_factory=list)
    provider_id_differences: list[dict] = field(default_factory=list)
    provider_breakdown: dict = field(default_factory=dict)
    root_cause_summary: dict = field(default_factory=dict)

    @property
    def is_clean(self) -> bool:
        return not (
            self.missing_scheduled_count or self.missing_live_count
            or self.field_difference_count or self.provider_id_difference_count
        )


def _live_match_key(m: dict) -> str | None:
    home = m.get("home_team", "") or ""
    away = m.get("away_team", "") or ""
    ko_date = m.get("kickoff_date", "") or ""
    if not home or not away or not ko_date:
        return None
    return match_key(home, away, ko_date)


def _scheduled_match_key(row: dict) -> str | None:
    home = row.get("home_team_canonical", "") or ""
    away = row.get("away_team_canonical", "") or ""
    ko_date = row.get("kickoff_date", "") or ""
    if not home or not away or not ko_date:
        return None
    return match_key(home, away, ko_date)


def _pb_bucket(provider_breakdown: dict, source: str) -> dict:
    return provider_breakdown.setdefault(
        source, {"matched": 0, "field_diff": 0, "id_diff": 0, "missing_scheduled": 0},
    )


def _bump_root_cause(root_cause_summary: dict, category: str) -> None:
    root_cause_summary[category] = root_cause_summary.get(category, 0) + 1


def evaluate(
    matches: list[dict],
    scheduled_rows: list[dict],
) -> ScheduledFixturesShadowReport:
    """
    `matches` — rezultatul `get_matches_for_week()` (calea live). `scheduled_rows`
    — TOATE rândurile din `scheduled_fixtures` pentru aceeași fereastră de
    date (de regulă `database.queries.list_scheduled_fixtures(d_from, d_to)`).
    """
    live_by_key: dict[str, dict] = {}
    for m in matches:
        source = m.get("source") or ""
        if source.startswith("demo-"):
            continue
        mk = _live_match_key(m)
        if mk is None:
            continue
        live_by_key[mk] = m

    scheduled_by_key: dict[str, dict] = {}
    for row in scheduled_rows:
        mk = _scheduled_match_key(row)
        if mk is None:
            continue
        scheduled_by_key[mk] = row

    live_keys = set(live_by_key.keys())
    scheduled_keys = set(scheduled_by_key.keys())
    matched_keys = live_keys & scheduled_keys

    field_differences: list[dict] = []
    provider_id_differences: list[dict] = []
    accepted_exception_count = 0
    provider_breakdown: dict = {}
    root_cause_summary: dict = {}

    # provider_breakdown -- setul de provideri e derivat DIN DATE (sursele
    # întâlnite efectiv), nu dintr-o listă fixă (ADR-040, principiul 3).
    for mk, m in live_by_key.items():
        src = m.get("source") or "unknown"
        bucket = _pb_bucket(provider_breakdown, src)
        if mk in matched_keys:
            bucket["matched"] += 1
        else:
            bucket["missing_scheduled"] += 1
            _bump_root_cause(root_cause_summary, root_cause.classify_missing_scheduled())

    for mk in scheduled_keys - live_keys:
        _bump_root_cause(root_cause_summary, root_cause.classify_missing_live())

    for mk in sorted(matched_keys):
        live_m = live_by_key[mk]
        sched_row = scheduled_by_key[mk]
        src = live_m.get("source") or "unknown"
        bucket = _pb_bucket(provider_breakdown, src)

        for field_name in _GOVERNED_FIELDS:
            live_val = live_m.get(field_name) or None
            sched_val = sched_row.get(field_name) or None
            if live_val != sched_val:
                category = root_cause.classify_field_difference(field_name)
                _bump_root_cause(root_cause_summary, category)
                policy = KNOWN_EXCEPTIONS.get((field_name, src))
                if policy in _ACCEPTED_POLICIES:
                    accepted_exception_count += 1
                else:
                    bucket["field_diff"] += 1
                field_differences.append({
                    "match_key": mk, "field": field_name,
                    "live": live_val, "scheduled": sched_val,
                    "exception_policy": policy,
                })

        provider_map = _PROVIDER_FIELD_MAP.get(src)
        if provider_map is None:
            continue
        for live_field, sched_col in provider_map["ids"]:
            raw = live_m.get(live_field)
            if raw is None or raw == "":
                continue
            live_val = str(raw)
            sched_val = sched_row.get(sched_col)
            if sched_val is None or str(sched_val) != live_val:
                category = root_cause.classify_provider_id_difference(sched_val)
                _bump_root_cause(root_cause_summary, category)
                bucket["id_diff"] += 1
                provider_id_differences.append({
                    "match_key": mk, "provider": provider_map["provider_id"],
                    "field": sched_col, "live": live_val, "scheduled": sched_val,
                })

    missing_scheduled_sorted = sorted(live_keys - scheduled_keys)
    missing_live_sorted = sorted(scheduled_keys - live_keys)

    return ScheduledFixturesShadowReport(
        timestamp=datetime.now(timezone.utc).isoformat(),
        live_count=len(live_keys),
        scheduled_count=len(scheduled_keys),
        matched=len(matched_keys),
        missing_scheduled_count=len(missing_scheduled_sorted),
        missing_live_count=len(missing_live_sorted),
        field_difference_count=len(field_differences),
        provider_id_difference_count=len(provider_id_differences),
        accepted_exception_count=accepted_exception_count,
        missing_scheduled=missing_scheduled_sorted[:MAX_EXAMPLES],
        missing_live=missing_live_sorted[:MAX_EXAMPLES],
        field_differences=field_differences[:MAX_EXAMPLES],
        provider_id_differences=provider_id_differences[:MAX_EXAMPLES],
        provider_breakdown=provider_breakdown,
        root_cause_summary=root_cause_summary,
    )
