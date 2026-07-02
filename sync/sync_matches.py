"""
================================================================================
FOOTBALL ORACLE v4.0 — Sync Matches
================================================================================
Module: sync/sync_matches.py

Sincronizează meciuri istorice din toate sursele disponibile în Supabase
(tabela match_history). Elimină duplicatele automat prin fixture_id unic.

Surse (în ordine de prioritate):
  1. football-data.org — rezultate + statistici (plan gratuit, 10 req/min)
  2. openfootball    — rezultate istorice simple (GitHub, fără limit)

Strategia de deduplicare:
  - fixture_id e unic în match_history (unique index)
  - Înainte de inserare, verificăm care fixture_id-uri există deja
  - Inserăm doar meciuri noi (upsert cu on_conflict="fixture_id")
================================================================================
"""
from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# Adăugăm root-ul proiectului în path
root = Path(__file__).parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from database.queries import (
    upsert_matches_bulk,
    get_existing_fixture_ids,
    upsert_sync_status,
    count_matches_with_result,
)

logger = logging.getLogger("FootballOracle.Sync.Matches")


@dataclass
class SyncReport:
    """Raport de sincronizare pentru o sursă."""
    source:          str
    leagues_synced:  list[str]    = field(default_factory=list)
    matches_fetched: int          = 0
    matches_new:     int          = 0
    matches_skipped: int          = 0
    errors:          int          = 0
    duration_sec:    float        = 0.0


def _deduplicate(
    matches: list[dict], existing_ids: set[str]
) -> tuple[list[dict], int]:
    """
    Separă meciurile noi de cele deja existente în Supabase.
    Returnează (new_matches, skipped_count).
    """
    new_matches = []
    skipped = 0
    seen_in_batch: set[str] = set()

    for m in matches:
        fid = m.get("fixture_id", "")
        if not fid:
            continue
        if fid in existing_ids or fid in seen_in_batch:
            skipped += 1
        else:
            new_matches.append(m)
            seen_in_batch.add(fid)

    return new_matches, skipped


def sync_from_football_data(
    leagues: list[str] | None = None,
    seasons: list[int] | None = None,
) -> SyncReport:
    """
    Sincronizează meciuri din football-data.org.
    Respectă automat rate limit-ul de 10 req/min.
    """
    import time
    from sync.sources.football_data import fetch_all_leagues

    start = time.time()
    report = SyncReport(source="football_data")

    logger.info("[SyncMatches] Începe sincronizarea din football-data.org...")

    all_matches: list[dict] = []

    for league, season, matches in fetch_all_leagues(leagues, seasons):
        if matches:
            all_matches.extend(matches)
            if league not in report.leagues_synced:
                report.leagues_synced.append(league)
            logger.info(
                "[SyncMatches] FD: %s %d → %d meciuri",
                league, season, len(matches)
            )

    report.matches_fetched = len(all_matches)

    if all_matches:
        # Verificăm ce există deja
        all_ids = [m["fixture_id"] for m in all_matches]
        existing = get_existing_fixture_ids(all_ids)

        new_matches, skipped = _deduplicate(all_matches, existing)
        report.matches_skipped = skipped

        if new_matches:
            ok, errors = upsert_matches_bulk(new_matches)
            report.matches_new = ok
            report.errors      = errors
        else:
            logger.info("[SyncMatches] FD: Niciun meci nou de adăugat.")

    report.duration_sec = round(time.time() - start, 1)

    # Actualizăm sync_status
    upsert_sync_status(
        source          = "football_data",
        last_sync       = datetime.now(timezone.utc).isoformat(),
        matches_added   = report.matches_new,
        matches_updated = 0,
        status          = "ok" if report.errors == 0 else "partial",
        notes           = f"fetched={report.matches_fetched} skipped={report.matches_skipped}",
    )

    return report


def sync_from_openfootball(
    leagues: list[str] | None = None,
    seasons: list[str] | None = None,
) -> SyncReport:
    """
    Sincronizează meciuri din openfootball (GitHub).
    Fără rate limit semnificativ.
    """
    import time
    from sync.sources.openfootball import fetch_all_leagues

    start = time.time()
    report = SyncReport(source="openfootball")

    logger.info("[SyncMatches] Începe sincronizarea din openfootball...")

    all_matches: list[dict] = []

    for league, season, matches in fetch_all_leagues(leagues, seasons):
        if matches:
            all_matches.extend(matches)
            if league not in report.leagues_synced:
                report.leagues_synced.append(league)
            logger.info(
                "[SyncMatches] OF: %s %s → %d meciuri",
                league, season, len(matches)
            )

    report.matches_fetched = len(all_matches)

    if all_matches:
        all_ids  = [m["fixture_id"] for m in all_matches]
        existing = get_existing_fixture_ids(all_ids)

        new_matches, skipped = _deduplicate(all_matches, existing)
        report.matches_skipped = skipped

        if new_matches:
            ok, errors = upsert_matches_bulk(new_matches)
            report.matches_new = ok
            report.errors      = errors
        else:
            logger.info("[SyncMatches] OF: Niciun meci nou de adăugat.")

    report.duration_sec = round(time.time() - start, 1)

    upsert_sync_status(
        source          = "openfootball",
        last_sync       = datetime.now(timezone.utc).isoformat(),
        matches_added   = report.matches_new,
        matches_updated = 0,
        status          = "ok" if report.errors == 0 else "partial",
        notes           = f"fetched={report.matches_fetched} skipped={report.matches_skipped}",
    )

    return report


def sync_all(
    use_football_data: bool = True,
    use_openfootball:  bool = True,
    leagues:           list[str] | None = None,
) -> list[SyncReport]:
    """
    Rulează toate sursele de sincronizare și returnează lista de rapoarte.
    Prioritate: football-data.org (mai complet) → openfootball (fallback/completare)
    """
    reports: list[SyncReport] = []

    if use_football_data:
        try:
            report = sync_from_football_data(leagues=leagues)
            reports.append(report)
        except Exception as exc:
            logger.error("[SyncMatches] football-data.org a picat: %s", exc)
            reports.append(SyncReport(source="football_data", errors=1))

    if use_openfootball:
        try:
            report = sync_from_openfootball(leagues=leagues)
            reports.append(report)
        except Exception as exc:
            logger.error("[SyncMatches] openfootball a picat: %s", exc)
            reports.append(SyncReport(source="openfootball", errors=1))

    return reports
