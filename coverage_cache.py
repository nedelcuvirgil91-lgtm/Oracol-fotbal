"""
================================================================================
FOOTBALL ORACLE — Coverage Cache (R4.1, ADR-038)
================================================================================
Strat subtire peste supabase_client.get_league_coverage/set_league_coverage
(tabela api_football_league_coverage, migrare 016 — proiectata, neaplicata
pana la confirmare explicita) — adauga logica de prospetime DIFERENTIATA,
exact designul aprobat si inghetat (audit §2, citat de ADR-038):

    7 zile  — daca starea observata e "pre-sezon" (toate flag-urile relevante
              din schema oficiala `coverage` sunt false — sezonul nu a
              inceput inca; recomandare oficiala de re-verificare saptamanala)
    30 zile — daca sezonul e confirmat activ (cel putin un flag true) sau
              starea e `plan_restricted` stabil (planul nu se schimba des)

Fara Supabase configurat, sau fara nicio intrare inca: `get_cached_coverage`
intoarce None — apelantul trateaza asta ca "necunoscut", nu ca "verificat si
nesuportat" (Regula #8, CLAUDE.md). Populare exclusiv prin `record_coverage`,
apelata sub Request Manager (§4/§8) — un singur apel controlat `/leagues?id=`
per liga monitorizata, niciodata verificari simultane necontrolate.
================================================================================
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger("FootballOracle.CoverageCache")

_TTL_PRESEASON_DAYS = 7.0
_TTL_ACTIVE_DAYS = 30.0

_COVERAGE_TOP_LEVEL_FLAGS = (
    "standings", "players", "top_scorers", "top_assists",
    "top_cards", "injuries", "predictions", "odds",
)
_COVERAGE_FIXTURES_FLAGS = ("events", "lineups", "statistics_fixtures", "statistics_players")


def _is_preseason(coverage_raw: dict | None) -> bool:
    """True doar daca exista cel putin un flag citit SI toate sunt false —
    stare oficiala "competitie care nu a inceput inca" (audit §2). Un
    `coverage_raw` gol/absent NU e tratat ca pre-sezon (ar fi o presupunere,
    nu o confirmare) — intoarce False, deci TTL implicit ramane cel activ."""
    if not coverage_raw:
        return False
    flags: list[bool] = []
    for key in _COVERAGE_TOP_LEVEL_FLAGS:
        if key in coverage_raw:
            flags.append(bool(coverage_raw.get(key)))
    fixtures = coverage_raw.get("fixtures") or {}
    for key in _COVERAGE_FIXTURES_FLAGS:
        if key in fixtures:
            flags.append(bool(fixtures.get(key)))
    return bool(flags) and not any(flags)


def is_fresh(entry: dict) -> bool:
    """`entry` = randul intors de supabase_client.get_league_coverage()."""
    verified_at_raw = entry.get("verified_at")
    if not verified_at_raw:
        return False
    try:
        verified_at = datetime.fromisoformat(str(verified_at_raw).replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return False
    age_days = (datetime.now(timezone.utc) - verified_at).total_seconds() / 86400.0

    if entry.get("fixtures_supported") == "plan_restricted":
        ttl_days = _TTL_ACTIVE_DAYS
    else:
        ttl_days = _TTL_PRESEASON_DAYS if _is_preseason(entry.get("coverage_raw")) else _TTL_ACTIVE_DAYS
    return age_days < ttl_days


def get_cached_coverage(league_id_canonical: str, api_football_league_id: int, season: int) -> dict | None:
    """Intoarce intrarea DOAR daca e inca proaspata — altfel None, semnal
    catre apelant sa re-verifice live (sub Request Manager, nu direct)."""
    import supabase_client as _sb

    entry = _sb.get_league_coverage(league_id_canonical, api_football_league_id, season)
    if entry is None:
        return None
    if not is_fresh(entry):
        logger.debug(
            "[CoverageCache] intrare expirata pentru %s/%s/%s",
            league_id_canonical, api_football_league_id, season,
        )
        return None
    return entry


def record_coverage(
    league_id_canonical: str, api_football_league_id: int, season: int,
    fixtures_supported: str, coverage_raw: dict | None = None,
    season_restriction: str | None = None, verified_via: str = "live_call",
    raw_error_payload: dict | None = None,
) -> bool:
    import supabase_client as _sb

    return _sb.set_league_coverage(
        league_id_canonical, api_football_league_id, season,
        fixtures_supported=fixtures_supported, coverage_raw=coverage_raw,
        season_restriction=season_restriction, verified_via=verified_via,
        raw_error_payload=raw_error_payload,
    )
