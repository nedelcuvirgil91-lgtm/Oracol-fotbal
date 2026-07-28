"""
================================================================================
FOOTBALL ORACLE — Free Live Football H2H Adapter (R-Sync-9, ADR-039)
================================================================================
Confruntări directe (H2H) Free Live Football pentru o pereche de echipe —
înlocuiește ultimul apel live rămas, eliminabil, din
`oracle_engine._build_h2h()` (`self.api.get_h2h(event_id, home_name,
away_name)`) cu un flux fetch → normalize → validate → persist, rulat DOAR
de Sync Layer (`sync/sync_h2h_freelf.py`), niciodată de Oracle Engine.

`fetch()` reutilizează EXACT `oracle_api.get_h2h()`, deja funcțională —
nicio logică HTTP nouă (ADR-038, principiul „no defect, no rewrite").

`tsdb_team_stats_adapter.py` (R-Sync-8) e precedentul structural direct:
`event_id`/nume vin deja gata rezolvate din `scheduled_fixtures`
(`freelf_event_id`, `home_team_canonical`, `away_team_canonical` —
R-Sync-7a) — Sync Layer NU mai caută fixture-ul, doar citește identitatea
deja descoperită.
================================================================================
"""
from __future__ import annotations

import logging

from sync_adapter import SyncAdapter

logger = logging.getLogger("FootballOracle.SyncAdapters.FreelfH2h")


class FreelfH2hAdapter(SyncAdapter):
    provider_id = "freelivefootball"

    def __init__(self, api=None):
        if api is None:
            from oracle_api import FootballOracleAPI
            api = FootballOracleAPI()
        self._api = api

    def fetch(self, params: dict) -> dict | None:
        """`params`: `{"home_team_canonical", "away_team_canonical",
        "freelf_event_id"}` — orientarea (acasă/oaspete) și event_id-ul vin
        deja gata rezolvate din `scheduled_fixtures`."""
        home_team = params["home_team_canonical"]
        away_team = params["away_team_canonical"]
        event_id = params["freelf_event_id"]
        h2h = self._api.get_h2h(int(event_id), home_team, away_team)
        if not h2h:
            return None
        return {
            "home_team_canonical": home_team, "away_team_canonical": away_team,
            "freelf_event_id": event_id, "h2h": h2h,
        }

    def normalize(self, raw_payload: dict | None) -> list[dict]:
        if not raw_payload:
            return []
        h2h = raw_payload.get("h2h") or {}
        return [{
            "home_team": raw_payload["home_team_canonical"],
            "away_team": raw_payload["away_team_canonical"],
            "freelf_event_id": raw_payload["freelf_event_id"],
            "meetings": h2h.get("meetings", 0),
            "home_wins": h2h.get("home_wins", 0),
            "draws": h2h.get("draws", 0),
            "away_wins": h2h.get("away_wins", 0),
            "home_goals_avg": h2h.get("home_goals_avg", 0.0),
            "away_goals_avg": h2h.get("away_goals_avg", 0.0),
            "last_5": h2h.get("last_5") or [],
            "h2h_modifier": h2h.get("h2h_modifier", 0.0),
            "summary": h2h.get("summary", ""),
        }]

    def validate(self, records: list[dict]) -> list[dict]:
        """Exclude, nu aruncă excepție — un rând fără echipe valide sau
        fără confruntări reale (`meetings < 1`) nu poate produce H2H
        utilizabil (Regula #8: mai bine lipsă decât inventat)."""
        valid: list[dict] = []
        for r in records:
            if not r.get("home_team") or not r.get("away_team"):
                logger.warning("[FreelfH2hAdapter] rând fără echipe, exclus: %r", r)
                continue
            if not r.get("meetings"):
                continue
            valid.append(r)
        return valid

    def persist(self, records: list[dict]) -> bool:
        from database.queries import upsert_freelf_h2h_snapshot

        ok = True
        for r in records:
            success = upsert_freelf_h2h_snapshot(
                r["home_team"], r["away_team"], r["freelf_event_id"],
                r["meetings"], r["home_wins"], r["draws"], r["away_wins"],
                r["home_goals_avg"], r["away_goals_avg"], r["last_5"],
                r["h2h_modifier"], r["summary"],
            )
            ok = ok and success
        return ok

    def coverage_check(self, context: dict) -> bool:
        """[DELIBERAT, nu omisiune] NU consultă Coverage Cache — coverage e
        deja aplicată corect, la nivelul corect: `sync/sync_h2h_freelf.py`
        iterează exclusiv fixture-urile deja prezente în `scheduled_fixtures`
        cu un `freelf_event_id` populat (o ligă neacoperită de FreeLF
        discovery nu produce niciodată un astfel de rând). Suprascrierea de
        mai jos (True, identică cu default-ul din SyncAdapter) există
        explicit, nu implicit — exact tiparul din
        `tsdb_team_stats_adapter.coverage_check()` (R-Sync-8)."""
        return True
