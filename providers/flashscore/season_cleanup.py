"""
================================================================================
FOOTBALL ORACLE — Season Cleanup (Dry Run ONLY, TASK APROBAT M1 / regula 8)
================================================================================
Module: providers/flashscore/season_cleanup.py

"Raspuns oficial - Foundation Data Layer (clarificari finale)", pct. 2/3:
Season Cleanup NU e prioritate acum. Se implementeaza DOAR infrastructura -
Discovery + Cleanup Report (dry-run). NU se implementeaza stergere automata,
NU exista DELETE in acest modul, NU exista cron.

Fluxul oficial complet (viitor, doar primii 2 pasi implementati aici):
  Discovery -> Validation -> Cleanup Report -> Backup -> Delete ->
  Integrity Check -> Final Report

Politica de retentie: sezonul curent (LIVE) + ultimele 5 sezoane istorice
complete = 6 sezoane total. Scope EXCLUSIV Foundation Data Layer (tabelele
introduse de migratiile 035-038) - NU match_history/match_events/
player_match_stats de baza (impact direct asupra istoricului ML,
`used_for_training`), NU odds_history (document Frozen, ADR-005/006/010 -
orice atingere cere ADR dedicat, nu poate intra tacit in scope-ul acestui
job).

Definitia sezonului: STRICT ce ofera providerul (coloana `season`,
migratia 038) - randurile fara sezon (`NULL`, providerul nu l-a oferit)
sunt raportate SEPARAT, niciodata tratate ca sezon real sau aproximate
printr-o regula calendaristica proprie (interzis explicit).
================================================================================
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("FootballOracle.Flashscore.SeasonCleanup")

RETENTION_SEASON_COUNT = 6

# Scope EXCLUSIV Foundation Data Layer (Raspuns oficial, pct. 2) - NU
# match_history/match_events/player_match_stats de baza, NU odds_history.
FOUNDATION_DATA_LAYER_SEASON_TABLES: tuple[str, ...] = (
    "match_statistics_extended",
    "player_match_stats_extended",
    "flashscore_match_context",
    "flashscore_standings_snapshot",
    "flashscore_raw_extraction",
    "flashscore_data_completeness",
)


def discover_seasons(table_counts: dict[str, dict[str | None, int]]) -> dict[str, Any]:
    """Pura, fara I/O - primeste `{tabel: {season: count}}` (deja
    interogat de apelant) si calculeaza sezoanele candidate pentru
    cleanup, sub politica de retentie (6 sezoane: curent + 5 istorice).

    Sezoanele sunt sortate LEXICAL ("YYYY-YYYY" - sortarea lexicala
    coincide cu cea cronologica pentru acest format, verificat). Cele mai
    recente `RETENTION_SEASON_COUNT` sezoane REALE gasite sunt pastrate;
    restul (mai vechi) sunt candidate. Randurile fara sezon (`None` -
    providerul nu l-a oferit) sunt raportate SEPARAT
    (`unknown_season_row_counts`), NICIODATA tratate ca sezon real sau ca
    substitut pentru unul lipsa (North Star #8) - NU intra in calculul de
    candidati."""
    all_seasons: set[str] = set()
    unknown_counts: dict[str, int] = {}
    for table, counts in table_counts.items():
        for season, count in counts.items():
            if season is None:
                if count:
                    unknown_counts[table] = count
            else:
                all_seasons.add(season)

    sorted_seasons = sorted(all_seasons)
    if len(sorted_seasons) <= RETENTION_SEASON_COUNT:
        cleanup_candidates: list[str] = []
        seasons_to_keep = sorted_seasons
    else:
        cleanup_candidates = sorted_seasons[: len(sorted_seasons) - RETENTION_SEASON_COUNT]
        seasons_to_keep = sorted_seasons[len(sorted_seasons) - RETENTION_SEASON_COUNT:]

    return {
        "known_seasons_found": sorted_seasons,
        "seasons_to_keep": seasons_to_keep,
        "cleanup_candidates": cleanup_candidates,
        "unknown_season_row_counts": unknown_counts,
        "retention_policy": f"{RETENTION_SEASON_COUNT} sezoane (curent + {RETENTION_SEASON_COUNT - 1} istorice)",
        "scope": list(FOUNDATION_DATA_LAYER_SEASON_TABLES),
        "dry_run": True,
        "delete_executed": False,
    }


def build_cleanup_dry_run_report() -> dict[str, Any]:
    """I/O - interogheaza Supabase (per tabel din scope, `select("season")`)
    si delega calculul pur catre `discover_seasons()`. NU sterge nimic -
    `delete_executed` e mereu `False` in aceasta etapa (infrastructura
    DOAR, "Raspuns oficial" pct. 3 - DELETE ramane dezactivat pana la un
    flag dedicat, activat separat, ulterior).

    [Nota de scalabilitate] Agregarea se face client-side (fara RPC de
    GROUP BY dedicat) - potrivit pentru volumul actual (0 randuri reale,
    faza de infrastructura); de revizuit daca volumul creste semnificativ
    inainte de activarea reala a stergerii."""
    from database.queries import get_client

    client = get_client()
    if client is None:
        return {
            "error": "supabase_unavailable", "dry_run": True, "delete_executed": False,
            "scope": list(FOUNDATION_DATA_LAYER_SEASON_TABLES),
        }

    table_counts: dict[str, dict[str | None, int]] = {}
    tables_failed: list[str] = []
    for table in FOUNDATION_DATA_LAYER_SEASON_TABLES:
        try:
            res = client.table(table).select("season").execute()
            rows = res.data or []
        except Exception as exc:
            logger.warning("[SeasonCleanup] %s: interogare esuata, exclus din raport: %s", table, exc)
            tables_failed.append(table)
            continue
        counts: dict[str | None, int] = {}
        for row in rows:
            season = row.get("season")
            counts[season] = counts.get(season, 0) + 1
        table_counts[table] = counts

    report = discover_seasons(table_counts)
    report["tables_scanned"] = list(table_counts.keys())
    if tables_failed:
        report["tables_failed"] = tables_failed
    return report
