"""
================================================================================
FOOTBALL ORACLE — Odds API Recent Results Adapter (R-Sync-6, ADR-039)
================================================================================
A șasea implementare reală a `SyncAdapter` (sync_adapter.py, R-Sync-1) —
meciuri TERMINATE recente (Odds API `/scores`), sursă CANONICĂ UNICĂ din
care se derivă, la citire, ATÂT formă per echipă (Level 2 din
`_build_profile()`) CÂT ȘI H2H (nivelul Odds API din `_build_h2h()`) —
decizie explicită, proprietar produs (audit R-Sync-6, opțiunea A): un
singur adaptor, nu două implementări separate ale aceleiași date brute.

`fetch()` reutilizează `oracle_api.get_recent_completed_matches_raw()`
(pură adăugire peste `_fetch_scores_odds_api()`, deja funcțională) — nu se
rescrie logica HTTP/parsare (ADR-039 Principiul 4).

Zero dependență de Match Discovery — verificat prin audit: ia doar
`sport_key` (static, `mappings.ODDS_SPORT_KEYS`), la fel ca
`footballdata_form_adapter.py` (R-Sync-3).
================================================================================
"""
from __future__ import annotations

import logging
from typing import Any

from sync_adapter import SyncAdapter

logger = logging.getLogger("FootballOracle.SyncAdapters.OddsApiRecentResults")


class OddsApiRecentResultsAdapter(SyncAdapter):
    provider_id = "oddsapi"

    def __init__(self, api=None):
        if api is None:
            from oracle_api import FootballOracleAPI
            api = FootballOracleAPI()
        self._api = api

    def fetch(self, params: dict) -> list[dict] | None:
        """`params`: `{"sport_key"}` — codul de sport Odds API, NU un
        `team_id`/`event_id` — sincronizare pe ligă, ca la R-Sync-3/4."""
        sport_key = params["sport_key"]
        return self._api.get_recent_completed_matches_raw(sport_key, days_back=3)

    def normalize(self, raw_payload: list[dict] | None) -> list[dict]:
        """Iterează TOATE meciurile terminate recente dintr-o ligă — un
        singur `fetch()` produce mai multe înregistrări.

        `home_team`/`away_team` sunt trecute EXPLICIT prin
        `normalize_team_name()` (ADR-039 Principiul 7), deși payload-ul
        brut le întoarce deja canonice (`_fetch_scores_odds_api()` le
        normalizează intern) — re-aplicarea e idempotentă, aceeași gardă
        defensivă folosită la R-Sync-4/6."""
        if not raw_payload:
            return []
        from mappings import normalize_team_name

        records: list[dict] = []
        for r in raw_payload:
            home = normalize_team_name(r.get("home_team", ""))
            away = normalize_team_name(r.get("away_team", ""))
            if not home or not away:
                continue
            records.append({
                "home_team":     home,
                "away_team":     away,
                "kickoff_date":  r.get("kickoff_date", ""),
                "league":        r.get("league", ""),
                "home_score":    r.get("home_score"),
                "away_score":    r.get("away_score"),
            })
        return records

    def validate(self, records: list[dict]) -> list[dict]:
        """Exclude, nu aruncă excepție — un rând fără echipe/dată valide
        sau fără scor complet nu poate fi persistat ca rezultat
        (Regula #8)."""
        valid: list[dict] = []
        for r in records:
            if not r.get("home_team") or not r.get("away_team"):
                logger.warning("[OddsApiRecentResultsAdapter] echipe lipsă, exclus: %r", r)
                continue
            if not r.get("kickoff_date"):
                continue
            if r.get("home_score") is None or r.get("away_score") is None:
                continue
            valid.append(r)
        return valid

    def persist(self, records: list[dict]) -> bool:
        from database.queries import upsert_odds_recent_result

        ok = True
        for r in records:
            success = upsert_odds_recent_result(
                r["home_team"], r["away_team"], r["kickoff_date"],
                r.get("league", ""), r["home_score"], r["away_score"],
            )
            ok = ok and success
        return ok

    def coverage_check(self, context: dict) -> bool:
        """[DELIBERAT, nu omisiune] Fără concept de coverage separat —
        gating-ul real e deja la apelant
        (sync/sync_odds_recent_results.py, iterează exclusiv
        `mappings.ODDS_SPORT_KEYS`). Suprascrierea de mai jos (True,
        identică cu default-ul din SyncAdapter) există explicit — tiparul
        din `footballdata_form_adapter.coverage_check()` (R-Sync-3)."""
        return True
