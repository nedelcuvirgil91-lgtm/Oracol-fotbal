"""
================================================================================
FOOTBALL ORACLE — Flashscore Persistence (Foundation Data Layer, migratia 035/036)
================================================================================
Module: providers/flashscore/persistence.py

Orchestreaza scrierea in Supabase a rezultatului `normalize_*()`
(normalizer.py, pur, fara I/O) - singurul loc din providerul Flashscore
care atinge reteaua/DB. Separatia normalizer(parsare)/persistence(I/O) e
deliberata (acelasi principiu ca `recalibration.py` - functie pura,
niciun amestec cu efectele de scriere).

Fiecare functie de mai jos e idempotenta prin constructie - toate
scrierile trec prin `database.queries.upsert_*`, care folosesc
ON CONFLICT DO UPDATE pe cheile UNIQUE reale ale schemei (migratia 035);
un rerun cu acelasi payload produce acelasi set de randuri, niciodata
duplicate noi (cerinta explicita M0, reafirmata la Foundation Data Layer:
"reruns produc no duplicates").

`persist_match_foundation_data()` e punctul de intrare unic pentru UN
meci - primeste `pages` (dict tab->html, deja citit de adapter.py) +
`competition` optional (pentru standings). Rezolva intai match_id prin
`upsert_match_and_get_id` (statisticile de baza + attendance/capacity/
goalkeeper_saves, toate deja mapate pe coloane canonice match_history),
apoi scrie tot ce depinde de acel id.
"""
from __future__ import annotations

import logging
from typing import Any

from database.queries import (
    upsert_match_and_get_id,
    upsert_match_context,
    upsert_match_statistics_extended,
    upsert_player_match_stats_extended,
    upsert_player_roster,
    upsert_raw_extraction,
    upsert_standings_snapshot,
)
from udal_validation import validate_flat_identity

from .normalizer import (
    normalize_match_context,
    normalize_match_statistics,
    normalize_match_statistics_extended,
    normalize_player_match_stats,
    normalize_player_match_stats_table,
    normalize_standings,
)

logger = logging.getLogger("FootballOracle.Flashscore.Persistence")


def _join_player_stats_with_roster(
    stats_table_rows: list[dict], roster_rows: list[dict],
) -> list[dict]:
    """Rezolva `team` pentru fiecare rand din tab-ul Player Stats prin
    potrivire de nume cu roster-ul din Lineups (limitare cunoscuta,
    documentata in normalizer.py - tabelul Player Stats nu are coloana
    de echipa). Randuri fara potrivire raman FARA `team` - excluse
    explicit la persist (`upsert_player_match_stats_extended`), niciodata
    ghicite."""
    roster_by_name = {r["player_name"]: r["team"] for r in roster_rows}
    joined: list[dict] = []
    for row in stats_table_rows:
        team = roster_by_name.get(row["player_name"])
        if team is None:
            logger.warning(
                "[Flashscore.Persistence] player stats '%s' fara potrivire in roster - exclus",
                row["player_name"],
            )
        joined.append({**row, "team": team})
    return joined


def persist_match_foundation_data(
    pages: dict[str, str], competition: str | None = None,
) -> dict[str, Any]:
    """Punct de intrare unic pentru persistarea completa a unui meci
    Flashscore (Foundation Data Layer). Returneaza un raport
    `{"match_id": int | None, "ok": bool, "steps": {...}}` - niciodata
    doar True/False, ca eșecul parțial să fie vizibil (North Star #9,
    trasabilitate completa)."""
    steps: dict[str, bool] = {}

    base = normalize_match_statistics(pages)
    if not base.get("home_team") or not base.get("away_team") or not base.get("kickoff_date"):
        logger.error("[Flashscore.Persistence] cheie naturala lipsa, abandonez: %r", base)
        return {"match_id": None, "ok": False, "steps": steps}

    match_id = upsert_match_and_get_id(base)
    steps["match_history"] = match_id is not None
    if match_id is None:
        return {"match_id": None, "ok": False, "steps": steps}

    extended_stats = normalize_match_statistics_extended(pages, match_id)
    steps["match_statistics_extended"] = upsert_match_statistics_extended(match_id, extended_stats)

    roster_rows = normalize_player_match_stats(pages, match_id)
    steps["player_roster"] = upsert_player_roster(match_id, roster_rows)

    stats_table_rows = normalize_player_match_stats_table(pages)
    joined_rows = _join_player_stats_with_roster(stats_table_rows, roster_rows)
    steps["player_match_stats_extended"] = upsert_player_match_stats_extended(match_id, joined_rows)

    context_rows = normalize_match_context(
        pages, match_id, base.get("home_team"), base.get("away_team"),
    )
    steps["match_context"] = upsert_match_context(context_rows)

    if competition:
        standings_rows = normalize_standings(pages, competition)
        steps["standings_snapshot"] = upsert_standings_snapshot(standings_rows)
    else:
        steps["standings_snapshot"] = True

    ok = all(steps.values())
    return {"match_id": match_id, "ok": ok, "steps": steps}


def _raw_snapshot_by_tab(pages: dict[str, str], competition: str | None) -> dict[str, Any]:
    """Snapshot RAW per tab - output `normalize_*()` INAINTE de rezolvarea
    match_id-ului canonic (RAW e independent de CANONICAL, per Data Trust
    Layer - se scrie chiar daca validarea/scrierea canonica eșuează).
    Campurile FK-dependente (`context_match_id`) raman `None` in acest
    snapshot - rezolvate abia la scrierea CANONICAL, niciodata aproximate
    aici (North Star #8)."""
    base = normalize_match_statistics(pages)
    snapshot: dict[str, Any] = {"stats": base}
    if pages.get("player_stats"):
        snapshot["player_stats"] = normalize_player_match_stats_table(pages)
    if pages.get("h2h"):
        snapshot["h2h"] = normalize_match_context(
            pages, None, base.get("home_team"), base.get("away_team"),
        )
    if competition and pages.get("standings"):
        snapshot["standings"] = normalize_standings(pages, competition)
    return snapshot


def persist_match_with_data_trust_layer(
    pages: dict[str, str], match_ref: str, competition: str | None = None,
) -> dict[str, Any]:
    """Punct de intrare Data Trust Layer (RAW -> VALIDATED -> CANONICAL,
    ADR-044 - "Nu exista bypass"): scrierea CANONICAL
    (`persist_match_foundation_data`) ruleaza DOAR daca validarea
    identitatii (`udal_validation.validate_flat_identity`) trece. RAW
    (`flashscore_raw_extraction`) se scrie INDIFERENT de rezultat -
    dovada de audit completa chiar si pentru meciuri respinse (North
    Star #9, trasabilitate completa). `match_ref` e identitatea stabila
    PRE-canonica (ex. URL/mid Flashscore) - furnizata de apelant
    (`adapter.py`), nu derivata aici."""
    raw_snapshot = _raw_snapshot_by_tab(pages, competition)
    base = raw_snapshot.get("stats", {})

    validation = validate_flat_identity([base], source_tier="playwright", source_id="flashscore")
    is_valid = bool(validation.valid)
    errors = [r.reason for r in validation.rejected] if not is_valid else None

    canonical_report: dict[str, Any] = {"match_id": None, "ok": False, "steps": {}}
    if is_valid:
        canonical_report = persist_match_foundation_data(pages, competition=competition)
    else:
        logger.warning(
            "[Flashscore.Persistence] validare esuata pentru %s, scriere CANONICAL sarita: %s",
            match_ref, errors,
        )

    validation_status = "valid" if is_valid else "rejected"
    canonical_written = bool(canonical_report.get("ok"))
    for tab_name, raw in raw_snapshot.items():
        upsert_raw_extraction(
            match_ref, tab_name, raw,
            validation_status=validation_status,
            validation_errors=errors,
            canonical_written=canonical_written,
        )

    return {
        **canonical_report,
        "match_ref": match_ref,
        "validation_status": validation_status,
        "validation_errors": errors,
    }
