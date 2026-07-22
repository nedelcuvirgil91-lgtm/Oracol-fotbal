"""
================================================================================
FOOTBALL ORACLE — football-data.org Form Adapter (R-Sync-3, ADR-039)
================================================================================
A doua implementare reală a `SyncAdapter` (sync_adapter.py, R-Sync-1) —
formă/standings per echipă, sursa football-data.org. Înlocuiește NUMAI
Level 3 din cascada `oracle_engine._build_profile()`
(`self.api.get_standings_form(team_id, league)`) cu un flux
fetch → normalize → validate → persist, rulat DOAR de Sync Layer
(`sync/sync_team_form_footballdata.py`), niciodată de Oracle Engine.

Scope explicit, corectat (audit §6b): DOAR formă/standings. Fixtures
(`_fetch_matches_fd`, descoperire meciuri) rămân neatinse — R-Sync-7,
Universal Match Discovery Layer.

Diferență structurală față de `apifootball_health_adapter.py` (R-Sync-2):
sincronizarea se face PE LIGĂ, nu per echipă — `get_team_form_fd()`
(oracle_api.py) cerea un `team_id` deja cunoscut (`fd_<id>`), disponibil
azi doar din meciuri deja descoperite (machinery de fixtures, explicit
în afara scope-ului R-Sync-3). `fetch()` folosește în schimb
`get_competition_standings_raw(comp_code)` — tabelul de clasament
COMPLET al unei competiții, o singură cerere — iar `normalize()` produce
MAI MULTE înregistrări per apel (toate echipele din ligă), prima
demonstrare reală a capacității multi-record a `SyncAdapter.normalize()`.
================================================================================
"""
from __future__ import annotations

import logging
from typing import Any

from sync_adapter import SyncAdapter

logger = logging.getLogger("FootballOracle.SyncAdapters.FootballDataForm")


class FootballDataFormAdapter(SyncAdapter):
    provider_id = "footballdata"

    def __init__(self, api=None):
        if api is None:
            from oracle_api import FootballOracleAPI
            api = FootballOracleAPI()
        self._api = api

    def fetch(self, params: dict) -> dict | None:
        """`params`: `{"comp_code"}` — codul competiției football-data.org
        (ex. `"PL"`), NU un `team_id` — sincronizare pe ligă, nu pe echipă."""
        comp_code = params["comp_code"]
        return self._api.get_competition_standings_raw(comp_code)

    def normalize(self, raw_payload: dict | None) -> list[dict]:
        """Iterează TOATE echipele din tabelul de clasament al unei
        competiții — un singur `fetch()` produce mai multe înregistrări
        (spre deosebire de R-Sync-2, unde fetch/normalize sunt 1:1 per
        echipă).

        `team_name` e trecut EXPLICIT prin `normalize_team_name()`
        (mappings.py — TEAM_ALIASES, ADR-039 Principiul 7), la fel ca în
        `apifootball_health_adapter.normalize()` — identitatea canonică se
        stabilește aici, nu la apelant."""
        if not raw_payload:
            return []
        from mappings import normalize_team_name

        records: list[dict] = []
        for grp in raw_payload.get("standings", []):
            for entry in grp.get("table", []):
                raw_name = (entry.get("team") or {}).get("name", "")
                if not raw_name:
                    continue
                canonical_name = normalize_team_name(raw_name)
                records.append({
                    "team_name": canonical_name,
                    "played": entry.get("playedGames") or 0,
                    "goals_for": entry.get("goalsFor") or 0,
                    "goals_against": entry.get("goalsAgainst") or 0,
                    "form": entry.get("form", "") or "",
                })
        return records

    def validate(self, records: list[dict]) -> list[dict]:
        """Exclude, nu aruncă excepție — un rând fără `team_name` valid sau
        fără meciuri jucate (`played == 0`, ex. sezon neîncep încă) nu
        poate produce formă utilizabilă (Regula #8: mai bine lipsă decât
        greșit)."""
        valid: list[dict] = []
        for r in records:
            if not r.get("team_name"):
                logger.warning("[FootballDataFormAdapter] rând fără team_name, exclus: %r", r)
                continue
            if not r.get("played"):
                continue
            valid.append(r)
        return valid

    def persist(self, records: list[dict]) -> bool:
        from database.queries import upsert_team_form_footballdata

        ok = True
        for r in records:
            success = upsert_team_form_footballdata(
                r["team_name"], r["played"], r["goals_for"], r["goals_against"], r["form"],
            )
            ok = ok and success
        return ok

    def coverage_check(self, context: dict) -> bool:
        """[DELIBERAT, nu omisiune] NU consultă Coverage Cache
        (`api_football_league_coverage`, migrare 016 — nume istoric legat
        de API-Football, dar oricum goală azi, nefolosită de niciun
        provider încă). Coverage e deja aplicată corect, la nivelul
        corect: `sync/sync_team_form_footballdata.py` iterează exclusiv
        `mappings.FD_COMPETITIONS` — ligile care AU deja un cod de
        competiție football-data.org confirmat (`LEAGUE_PROVIDERS`,
        filtrat, fără `None`); o ligă neconfirmată nu ajunge niciodată să
        apeleze `fetch()`. Suprascrierea de mai jos (True, identică cu
        default-ul din SyncAdapter) există explicit, nu implicit, ca
        următorul dezvoltator să nu creadă că lipsește dintr-o scăpare —
        exact tiparul din `apifootball_health_adapter.coverage_check()`
        (R-Sync-2)."""
        return True
