"""
================================================================================
FOOTBALL ORACLE v4.0 — Sync Results (zilnic automat)
================================================================================
Module: sync/sync_results.py

Descarcă rezultatele meciurilor terminate ieri din football-data.org și
actualizează match_history în Supabase cu scorurile reale.

Rulat zilnic de run_daily.py la 03:00 UTC — meciurile de ieri sunt deja
terminate și scorurile finale sunt disponibile.

Flux:
  1. Descarcă meciurile terminate ieri din football-data.org
  2. Caută în match_history meciurile fără scor (actual_result IS NULL)
     care se potrivesc cu home_team + away_team + kickoff_date
  3. Actualizează scorurile + marchează pentru backfill
  4. Calculează feature-urile ML pentru meciurile nou-completate
================================================================================
"""
from __future__ import annotations

import logging
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

root = Path(__file__).parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

import requests

logger = logging.getLogger("FootballOracle.Sync.Results")

FD_BASE_URL = "https://api.football-data.org/v4"
FD_API_KEY  = "3934542be32c47f88a194f9eec0f44a1"

# Rate limit: 10 req/min
REQUEST_INTERVAL = 6.1
_last_request_time: float = 0.0


def _rate_limited_get(url: str, params: dict | None = None) -> dict | None:
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < REQUEST_INTERVAL:
        time.sleep(REQUEST_INTERVAL - elapsed)
    try:
        resp = requests.get(
            url,
            headers={"X-Auth-Token": FD_API_KEY},
            params=params or {},
            timeout=15,
        )
        _last_request_time = time.time()
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 429:
            logger.warning("[SyncResults] Rate limit — aștept 60s")
            time.sleep(60)
            return None
        logger.warning("[SyncResults] HTTP %d pentru %s", resp.status_code, url)
        return None
    except Exception as exc:
        logger.error("[SyncResults] Eroare fetch: %s", exc)
        _last_request_time = time.time()
        return None


COMPETITION_TO_LEAGUE = {
    "PL":  "Premier League",
    "PD":  "La Liga",
    "SA":  "Serie A",
    "BL1": "Bundesliga",
    "FL1": "Ligue 1",
    "CL":  "Champions League",
}


def fetch_yesterday_results(target_date: str | None = None) -> list[dict]:
    """
    Descarcă rezultatele meciurilor terminate într-o zi specifică.
    target_date: format YYYY-MM-DD (default: ieri)
    """
    if target_date is None:
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
        target_date = yesterday.isoformat()

    logger.info("[SyncResults] Descarcă rezultate pentru %s", target_date)

    data = _rate_limited_get(
        f"{FD_BASE_URL}/matches",
        params={
            "dateFrom": target_date,
            "dateTo":   target_date,
            "status":   "FINISHED",
        }
    )

    if not data:
        return []

    results = []
    for match in data.get("matches", []):
        try:
            comp_code = (match.get("competition") or {}).get("tla", "")
            league    = COMPETITION_TO_LEAGUE.get(comp_code)
            if not league:
                continue

            home_team  = (match.get("homeTeam") or {}).get("name", "")
            away_team  = (match.get("awayTeam") or {}).get("name", "")
            score      = match.get("score", {})
            ft         = score.get("fullTime", {})
            home_goals = ft.get("home")
            away_goals = ft.get("away")

            if not home_team or not away_team:
                continue
            if home_goals is None or away_goals is None:
                continue

            home_goals = int(home_goals)
            away_goals = int(away_goals)

            actual_result = (
                "H" if home_goals > away_goals
                else "A" if home_goals < away_goals
                else "D"
            )

            utc_date    = match.get("utcDate", "")
            kickoff_date = utc_date[:10] if utc_date else target_date

            results.append({
                "fd_id":           match.get("id"),
                "home_team":       home_team,
                "away_team":       away_team,
                "league":          league,
                "kickoff_date":    kickoff_date,
                "home_goals":      home_goals,
                "away_goals":      away_goals,
                "actual_result":   actual_result,
            })
        except Exception as exc:
            logger.debug("[SyncResults] Parse error: %s", exc)
            continue

    logger.info("[SyncResults] %d meciuri terminate găsite pentru %s",
                len(results), target_date)
    return results


def update_results_in_supabase(results: list[dict]) -> tuple[int, int]:
    """
    Actualizează scorurile în match_history pentru meciurile terminate.
    Caută potriviri după home_team + away_team + kickoff_date.
    Returnează (updated_count, not_found_count).
    """
    from supabase_client import get_client
    client = get_client()
    if client is None:
        return 0, len(results)

    updated    = 0
    not_found  = 0

    for r in results:
        try:
            # Căutăm meciul în match_history fără scor
            res = (
                client.table("match_history")
                .select("id,fixture_id")
                .eq("home_team",    r["home_team"])
                .eq("away_team",    r["away_team"])
                .eq("league",       r["league"])
                .eq("kickoff_date", r["kickoff_date"])
                .is_("actual_result", "null")
                .execute()
            )

            rows = res.data or []

            if not rows:
                # Încearcă și cu fixture_id fd_
                fd_fixture_id = f"fd_{r['fd_id']}" if r.get("fd_id") else None
                if fd_fixture_id:
                    res2 = (
                        client.table("match_history")
                        .select("id,fixture_id")
                        .eq("fixture_id", fd_fixture_id)
                        .is_("actual_result", "null")
                        .execute()
                    )
                    rows = res2.data or []

            if not rows:
                logger.debug(
                    "[SyncResults] Nu am găsit: %s vs %s (%s)",
                    r["home_team"], r["away_team"], r["kickoff_date"]
                )
                not_found += 1
                continue

            # Actualizăm primul rând găsit
            match_id = rows[0]["id"]
            client.table("match_history").update({
                "actual_home_goals": r["home_goals"],
                "actual_away_goals": r["away_goals"],
                "actual_result":     r["actual_result"],
                "backfill_done":     False,  # va fi procesat de backfill
            }).eq("id", match_id).execute()

            updated += 1
            logger.debug(
                "[SyncResults] Actualizat: %s vs %s → %d-%d (%s)",
                r["home_team"], r["away_team"],
                r["home_goals"], r["away_goals"], r["actual_result"]
            )

        except Exception as exc:
            logger.error("[SyncResults] Update failed pentru %s vs %s: %s",
                         r.get("home_team"), r.get("away_team"), exc)
            not_found += 1

    logger.info("[SyncResults] Actualizate: %d | Negăsite: %d", updated, not_found)
    return updated, not_found


def sync_yesterday_results() -> dict:
    """
    Funcția principală — descarcă și salvează rezultatele de ieri.
    Apelată din run_daily.py.
    """
    results = fetch_yesterday_results()
    if not results:
        return {"status": "ok", "updated": 0, "not_found": 0, "message": "Niciun meci ieri"}

    updated, not_found = update_results_in_supabase(results)

    # Dacă s-au actualizat meciuri, rulăm backfill pentru ele
    if updated > 0:
        logger.info("[SyncResults] Rulăm backfill pentru %d meciuri noi...", updated)
        try:
            from sync.backfill_features import run_backfill
            # Backfill doar pentru meciurile recent actualizate (backfill_done=False)
            run_backfill(batch_size=50)
        except Exception as exc:
            logger.warning("[SyncResults] Backfill după sync eșuat: %s", exc)

    return {
        "status":    "ok",
        "updated":   updated,
        "not_found": not_found,
    }
