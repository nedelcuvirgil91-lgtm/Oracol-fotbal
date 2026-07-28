"""
================================================================================
FOOTBALL ORACLE — Match Statistics Adapter (Sprint 1, ADR-039)
================================================================================
Implementare `SyncAdapter` (sync_adapter.py, R-Sync-1) — posesie + xG real
post-meci, owner NOU (FreeLF `get_match_statistics()`, `oracle_api.py:534`,
zero apelanți până acum — motivul real al golului 0% populare, `home/
away_possession`/`home/away_xg_actual`, confirmat live pe Supabase).

Scope inițial, Sprint 1 („foarte solid, nu foarte mare"): DOAR
`home/away_possession` + `home/away_xg_actual`. [EXTINS Sprint 3,
Prioritatea 1, Regula 4 — „nu accepta implementări parțiale, completează
adaptorul existent"] `get_match_statistics()` întoarce deja, verificat prin
citire de cod, `home/away_shots_ot` — scris acum ca
`home/away_shots_on_target`, COALESCE-only (ADR-036): owner-ul PRIMAR
rămâne mirror-ul football_data_co_uk (`sync/backfill_match_stats.py`), care
scrie primul dacă rulează primul; FreeLF completează DOAR rândurile încă
NULL, niciodată nu suprascrie. `big_chance` rămâne neatins — coloană
inexistentă azi în `match_history`, scriere ar necesita o migrare de schemă
neaprobată în acest pas.

Rezoluția `event_id` NU trăiește aici — deleagă la
`freelf_event_resolver.FreelfEventResolver` (componentă reutilizabilă Sync
Layer, nu logică duplicată per adaptor, decizie explicită proprietar
produs).
================================================================================
"""
from __future__ import annotations

import logging
from typing import Any

from sync_adapter import SyncAdapter

logger = logging.getLogger("FootballOracle.SyncAdapters.MatchStatistics")


class MatchStatisticsAdapter(SyncAdapter):
    provider_id = "freelivefootball"

    def __init__(self, api=None, resolver=None):
        if api is None:
            from oracle_api import FootballOracleAPI
            api = FootballOracleAPI()
        self._api = api
        if resolver is None:
            from freelf_event_resolver import get_freelf_event_resolver
            resolver = get_freelf_event_resolver()
        self._resolver = resolver

    def fetch(self, params: dict) -> dict | None:
        """`params`: `{"home_team", "away_team", "kickoff_date", "league"}`.
        Rezolvă event_id prin resolver-ul reutilizabil, apoi apelează
        `get_match_statistics()` (deja existentă, deja cache-uită per
        event_id — nu se rescrie). `event_id` nerezolvat -> `None`,
        niciodată aproximat (Regula #8)."""
        home_team = params["home_team"]
        away_team = params["away_team"]
        kickoff_date = params["kickoff_date"]
        league = params["league"]

        event_id = self._resolver.resolve(home_team, away_team, kickoff_date, league)
        if event_id is None:
            return None
        stats = self._api.get_match_statistics(event_id)
        if not stats:
            return None
        return {
            "home_team": home_team, "away_team": away_team, "kickoff_date": kickoff_date,
            **stats,
        }

    def normalize(self, raw_payload: dict | None) -> list[dict]:
        """Mapează câmpurile brute (`home_xg`/`home_possession`/
        `home_shots_ot`, tiparul deja folosit de `get_match_statistics()`)
        pe numele canonice din `match_history`. [EXTINS Sprint 3] +
        `home/away_shots_on_target` — vezi docstring-ul modulului."""
        if not raw_payload:
            return []
        from mappings import normalize_team_name

        home = normalize_team_name(raw_payload["home_team"])
        away = normalize_team_name(raw_payload["away_team"])
        return [{
            "home_team": home, "away_team": away,
            "kickoff_date": raw_payload["kickoff_date"],
            "home_possession": raw_payload.get("home_possession"),
            "away_possession": raw_payload.get("away_possession"),
            "home_xg_actual": raw_payload.get("home_xg"),
            "away_xg_actual": raw_payload.get("away_xg"),
            "home_shots_on_target": raw_payload.get("home_shots_ot"),
            "away_shots_on_target": raw_payload.get("away_shots_ot"),
            "stats_source": "freelivefootball",
        }]

    def validate(self, records: list[dict]) -> list[dict]:
        """Exclude, nu aruncă excepție (Regula #8). Respinge rânduri fără
        cheia naturală (home/away/kickoff_date) SAU fără nicio valoare utilă
        (toate cele 6 câmpuri lipsă — nimic de scris)."""
        valid: list[dict] = []
        for r in records:
            if not r.get("home_team") or not r.get("away_team") or not r.get("kickoff_date"):
                logger.warning("[MatchStatisticsAdapter] rând fără cheie naturală, exclus: %r", r)
                continue
            has_value = any(r.get(k) is not None for k in
                             ("home_possession", "away_possession", "home_xg_actual", "away_xg_actual",
                              "home_shots_on_target", "away_shots_on_target"))
            if not has_value:
                logger.debug("[MatchStatisticsAdapter] rând fără nicio valoare utilă, exclus: %r", r)
                continue
            valid.append(r)
        return valid

    def persist(self, records: list[dict]) -> bool:
        """`upsert_match()` — RPC canonic `upsert_match_canonical`, deja
        COALESCE-only (Canonical Feature Ownership, ADR-036) — niciodată nu
        suprascrie o valoare deja scrisă de alt owner. Zero migrare nouă:
        toate cele 5 coloane (`home/away_possession`, `home/away_xg_actual`,
        `stats_source`) există deja în `match_history` (migrarea 008)."""
        from database.queries import upsert_match

        ok = True
        for r in records:
            success = upsert_match(r)
            ok = ok and success
        return ok

    def coverage_check(self, context: dict) -> bool:
        """[DELIBERAT, ca la ApiFootballHealthAdapter] Coverage FreeLF e deja
        aplicată la nivelul corect — `resolve_freelf_finished_match_id()`
        (`oracle_api.py`) verifică intern `FREE_LF_LEAGUE_IDS.get(league)`
        înainte de orice cerere HTTP. Suprascriere explicită, nu implicită."""
        return True
