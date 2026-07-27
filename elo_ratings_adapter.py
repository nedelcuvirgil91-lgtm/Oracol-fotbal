"""
================================================================================
FOOTBALL ORACLE — National Team ELO Adapter (R-Sync-4, ADR-039)
================================================================================
A treia implementare reală a `SyncAdapter` (sync_adapter.py, R-Sync-1) —
ELO pentru echipele NAȚIONALE, sursa eloratings.net. Înlocuiește fallback-ul
live din cascada de ELO a `oracle_engine._build_profile()`
(`self.api.get_elo_rating(canonical)`) cu un flux
fetch → normalize → validate → persist, rulat DOAR de Sync Layer
(`sync/sync_national_team_elo.py`), niciodată de Oracle Engine.

Corecție de scope (audit §6c): NU e TheSportsDB — eloratings.net e un
provider distinct (scrape HTML), confundat inițial cu TheSportsDB în
auditul original. TheSportsDB team stats rămâne, deliberat, neatins aici
— R-Sync-8, după Universal Match Discovery Layer.

Tipar identic R-Sync-3 (`footballdata_form_adapter.py`): un singur
`fetch()` produce ratinguri pentru TOATE echipele naționale cunoscute
dintr-un scrape — `normalize()` produce MULTIPLE înregistrări per apel,
nu una per echipă.
================================================================================
"""
from __future__ import annotations

import logging
from typing import Any

from sync_adapter import SyncAdapter

logger = logging.getLogger("FootballOracle.SyncAdapters.EloRatings")


class EloRatingsAdapter(SyncAdapter):
    provider_id = "eloratings"

    def __init__(self, api=None):
        if api is None:
            from oracle_api import FootballOracleAPI
            api = FootballOracleAPI()
        self._api = api

    def fetch(self, params: dict) -> dict | None:
        """`params` neutilizat — un singur scrape produce TOATE echipele
        naționale cunoscute deodată, nu există un parametru de filtrare
        (spre deosebire de football-data.org, care cere `comp_code` per
        ligă)."""
        return self._api.get_national_elo_ratings_raw()

    def normalize(self, raw_payload: dict | None) -> list[dict]:
        """Iterează TOATE echipele din dicționarul `{nume: elo}` —
        `fetch()` produce mai multe înregistrări, la fel ca
        `footballdata_form_adapter.normalize()` (R-Sync-3).

        `team_name` e trecut EXPLICIT prin `normalize_team_name()`
        (mappings.py — TEAM_ALIASES, ADR-039 Principiul 7), deși
        `get_national_elo_ratings_raw()` întoarce deja chei canonice
        (`_fetch_elo_ratings()` normalizează intern la scrape) —
        re-aplicarea e idempotentă și păstrează tiparul explicit uniform
        cu celelalte adaptoare, ca gardă împotriva unei schimbări
        viitoare tăcute a sursei interne."""
        if not raw_payload:
            return []
        from mappings import normalize_team_name

        records: list[dict] = []
        for raw_name, elo_value in raw_payload.items():
            if not raw_name:
                continue
            canonical_name = normalize_team_name(raw_name)
            records.append({"team_name": canonical_name, "elo_rating": elo_value})
        return records

    def validate(self, records: list[dict]) -> list[dict]:
        """Exclude, nu aruncă excepție — un rând fără `team_name` valid sau
        cu un ELO nepozitiv nu poate fi persistat (Regula #8: mai bine
        lipsă decât greșit)."""
        valid: list[dict] = []
        for r in records:
            if not r.get("team_name"):
                logger.warning("[EloRatingsAdapter] rând fără team_name, exclus: %r", r)
                continue
            elo = r.get("elo_rating")
            if not isinstance(elo, (int, float)) or elo <= 0:
                continue
            valid.append(r)
        return valid

    def persist(self, records: list[dict]) -> bool:
        from database.queries import upsert_national_team_elo

        ok = True
        for r in records:
            success = upsert_national_team_elo(r["team_name"], int(r["elo_rating"]))
            ok = ok and success
        return ok

    def coverage_check(self, context: dict) -> bool:
        """[DELIBERAT, nu omisiune] Fără concept de coverage — eloratings.net
        e un provider public, un singur tabel global, fără restricții de
        plan/ligă/sezon (spre deosebire de API-Football/football-data.org).
        Suprascrierea de mai jos (True, identică cu default-ul din
        SyncAdapter) există explicit, nu implicit, ca următorul
        dezvoltator să nu creadă că lipsește dintr-o scăpare — exact
        tiparul din `footballdata_form_adapter.coverage_check()`
        (R-Sync-3)."""
        return True
