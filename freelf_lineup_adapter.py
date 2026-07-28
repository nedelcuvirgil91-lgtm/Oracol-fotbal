"""
================================================================================
FOOTBALL ORACLE — Free Live Football Lineup Adapter (R-Sync-10, ADR-039)
================================================================================
Aliniamente (lineup) + absențe confirmate Free Live Football, per meci —
înlocuiește ultimul apel live rămas care MODIFICĂ efectiv predicția servită
(`injury_manager.get_lineup_absences()` → `oracle_api.get_lineup()`,
`oracle_engine.py`, Sprint 3 audit complet) cu un flux
fetch → normalize → validate → persist, rulat DOAR de Sync Layer
(`sync/sync_lineup_freelf.py`), niciodată de Oracle Engine.

Cadență DEDICATĂ, separată de `run_daily.py` (o singură dată/zi, prea rar
pentru date care se confirmă aproape de kickoff) —
`.github/workflows/lineup_sync.yml`, la 15 minute, doar pentru meciurile
din fereastra apropiată de kickoff (`scheduled_fixtures`, R-Sync-7a).

`fetch()` reutilizează EXACT `oracle_api.get_lineup()`, deja funcțională —
nicio logică HTTP nouă (ADR-038, „no defect, no rewrite"), apelată de DOUĂ
ori per meci (acasă + oaspete), la fel cum `oracle_api._fetch_odds()` face
mai multe sub-apeluri per `fetch()` (h2h+totals, apoi btts separat).
================================================================================
"""
from __future__ import annotations

import logging

from sync_adapter import SyncAdapter

logger = logging.getLogger("FootballOracle.SyncAdapters.FreelfLineup")


class FreelfLineupAdapter(SyncAdapter):
    provider_id = "freelivefootball"

    def __init__(self, api=None):
        if api is None:
            from oracle_api import FootballOracleAPI
            api = FootballOracleAPI()
        self._api = api

    def fetch(self, params: dict) -> dict | None:
        """`params`: `{"home_team_canonical", "away_team_canonical",
        "kickoff_date", "freelf_event_id"}` — event_id-ul vine deja gata
        rezolvat din `scheduled_fixtures` (R-Sync-7a)."""
        event_id = int(params["freelf_event_id"])
        home = self._api.get_lineup(event_id, is_home=True)
        away = self._api.get_lineup(event_id, is_home=False)
        if not home and not away:
            return None
        return {
            "home_team_canonical": params["home_team_canonical"],
            "away_team_canonical": params["away_team_canonical"],
            "kickoff_date": params["kickoff_date"],
            "freelf_event_id": params["freelf_event_id"],
            "home_lineup": home,
            "away_lineup": away,
        }

    def normalize(self, raw_payload: dict | None) -> list[dict]:
        if not raw_payload:
            return []
        home_lineup = raw_payload.get("home_lineup") or {}
        away_lineup = raw_payload.get("away_lineup") or {}
        return [{
            "home_team": raw_payload["home_team_canonical"],
            "away_team": raw_payload["away_team_canonical"],
            "kickoff_date": raw_payload["kickoff_date"],
            "freelf_event_id": raw_payload["freelf_event_id"],
            "home_confirmed": bool(home_lineup.get("confirmed", False)),
            "home_formation": home_lineup.get("formation", "") or "",
            "home_unavailable": home_lineup.get("unavailable") or [],
            "away_confirmed": bool(away_lineup.get("confirmed", False)),
            "away_formation": away_lineup.get("formation", "") or "",
            "away_unavailable": away_lineup.get("unavailable") or [],
        }]

    def validate(self, records: list[dict]) -> list[dict]:
        """Exclude, nu aruncă excepție — un rând fără ambele echipe valide
        nu poate fi persistat (Regula #8)."""
        valid: list[dict] = []
        for r in records:
            if not r.get("home_team") or not r.get("away_team"):
                logger.warning("[FreelfLineupAdapter] rând fără echipe, exclus: %r", r)
                continue
            valid.append(r)
        return valid

    def persist(self, records: list[dict]) -> bool:
        from database.queries import upsert_freelf_lineup_snapshot

        ok = True
        for r in records:
            success = upsert_freelf_lineup_snapshot(
                r["home_team"], r["away_team"], r["kickoff_date"], r["freelf_event_id"],
                r["home_confirmed"], r["home_formation"], r["home_unavailable"],
                r["away_confirmed"], r["away_formation"], r["away_unavailable"],
            )
            ok = ok and success
        return ok

    def coverage_check(self, context: dict) -> bool:
        """[DELIBERAT, nu omisiune] NU consultă Coverage Cache — coverage e
        deja aplicată corect, la nivelul corect:
        `sync/sync_lineup_freelf.py` iterează exclusiv fixture-urile deja
        prezente în `scheduled_fixtures` cu un `freelf_event_id` populat,
        în fereastra de kickoff relevantă. Suprascrierea de mai jos (True,
        identică cu default-ul din SyncAdapter) există explicit — exact
        tiparul din `freelf_h2h_adapter.coverage_check()` (R-Sync-9)."""
        return True
