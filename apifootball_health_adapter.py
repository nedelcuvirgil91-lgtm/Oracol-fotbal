"""
================================================================================
FOOTBALL ORACLE — API-Football Health Adapter (R-Sync-2, ADR-039)
================================================================================
Prima implementare reală a `SyncAdapter` (sync_adapter.py, R-Sync-1) —
injuries+coaches per echipă, consumatorul real al bugetului API-Football
(audit API-Football §1). Înlocuiește apelul live inline din
`oracle_engine.py` cu un flux fetch → normalize → validate → persist,
rulat DOAR de Sync Layer (`sync/sync_team_health.py`), niciodată de Oracle
Engine.

`fetch()`/`normalize()` reutilizează EXACT ce există deja, dovedit, în
`football_providers.ApiFootballProvider` (`get_injuries`/`get_coaches`,
deja trec prin Request Manager — R4.1) — nu se rescrie logica HTTP/parsare
deja funcțională (ADR-038, principiul „no defect, no rewrite").
`validate()`/`persist()` sunt genuine adăugiri R-Sync-2.

Coverage: NU verificată separat la nivel de adaptor — `get_injuries()`/
`get_coaches()` deja auto-gatează prin `_covered()` intern (confirmat,
football_providers.py), inclusiv defectul reparat în R4.1 pentru
`get_coaches()`. Nu se dublează gating-ul printr-un mecanism paralel
(Coverage Cache/migrare 016 rămâne neatinsă/nepopulată — decizie
deliberată, nu omisiune, ca să nu introducă o dependință de o tabelă încă
goală).
================================================================================
"""
from __future__ import annotations

import logging
from typing import Any

from sync_adapter import SyncAdapter
from football_providers import ApiFootballProvider

logger = logging.getLogger("FootballOracle.SyncAdapters.ApiFootballHealth")


class ApiFootballHealthAdapter(SyncAdapter):
    provider_id = "apifootball"

    def __init__(self, provider: ApiFootballProvider | None = None):
        self._provider = provider or ApiFootballProvider()

    def resolve_team_id(self, team_name: str) -> int | None:
        """Passthrough public — evită accesul din exterior la atributul
        `_provider` al acestei clase."""
        return self._provider.resolve_team_id(team_name)

    def fetch(self, params: dict) -> dict | None:
        """`params`: `{"team_name", "team_id", "league", "season"}`."""
        team_name = params["team_name"]
        team_id = params["team_id"]
        league = params["league"]
        season = params.get("season")
        injuries = self._provider.get_injuries(team_name, team_id, league, season)
        coaches = self._provider.get_coaches(team_name, team_id, league)
        return {"team_name": team_name, "injuries": injuries, "coaches": coaches}

    def normalize(self, raw_payload: dict | None) -> list[dict]:
        """`Injury`/`CoachInfo` sunt deja normalizate de `ApiFootballProvider`
        — aici doar le convertim la dict-uri simple, serializabile JSONB.

        `team_name` e trecut EXPLICIT prin `normalize_team_name()`
        (mappings.py — TEAM_ALIASES, mecanismul canonic deja existent în
        proiect, ADR-039 Principiul 7), nu se presupune că apelantul l-a
        normalizat deja. Deși azi apelantul (`sync/sync_team_health.py`,
        via `oracle_api.get_matches_for_week()`) chiar produce nume deja
        normalizate, a te baza pe o garanție amonte nescrisă local e exact
        tiparul de fragilitate deja documentat în
        `docs/03_ENGINE/TEAM_IDENTITY_AUDIT.md` (writeri care presupun
        normalizare fără s-o aplice explicit, cauza reală a 137 de identități
        de echipă fragmentate). `normalize()` e punctul unde se stabilește
        identitatea canonică — responsabilitatea stă aici, nu la apelant."""
        if not raw_payload:
            return []
        from mappings import normalize_team_name

        canonical_name = normalize_team_name(raw_payload["team_name"])
        injuries = [vars(i) for i in raw_payload.get("injuries", [])]
        coaches = [vars(c) for c in raw_payload.get("coaches", [])]
        return [{
            "team_name": canonical_name,
            "injuries": injuries,
            "coaches": coaches,
        }]

    def validate(self, records: list[dict]) -> list[dict]:
        """Exclude, nu aruncă excepție — un rând fără `team_name` valid nu
        poate fi persistat (Regula #8: mai bine lipsă decât greșit)."""
        valid: list[dict] = []
        for r in records:
            if not r.get("team_name"):
                logger.warning("[ApiFootballHealthAdapter] rând fără team_name, exclus: %r", r)
                continue
            valid.append(r)
        return valid

    def persist(self, records: list[dict]) -> bool:
        from database.queries import upsert_team_health

        ok = True
        for r in records:
            success = upsert_team_health(
                r["team_name"], r["injuries"], r["coaches"],
                source_provider=self.provider_id,
            )
            ok = ok and success
        return ok

    def coverage_check(self, context: dict) -> bool:
        """[DELIBERAT, nu omisiune] NU consultă Coverage Cache
        (`api_football_league_coverage`, migrare 016) — tabela e goală azi,
        nimic nu a scris vreodată în ea (verificat, `list_tables`: 0 rânduri).
        Un gate legat de o tabelă goală ar bloca silențios ORICE
        sincronizare de team health, fără avertisment.

        Coverage e deja aplicată corect, la nivelul corect: `fetch()` de mai
        sus apelează `get_injuries()`/`get_coaches()`, care verifică intern
        `_covered()` (`football_providers.py`, pe baza
        `mappings.LEAGUE_PROVIDERS`) ÎNAINTE de orice cerere HTTP — același
        mecanism care a reparat deja defectul real găsit la `get_coaches()`
        (R4.1, ADR-038 audit §16). Suprascrierea de mai jos (True, identică
        cu default-ul din SyncAdapter) există explicit, nu implicit, ca
        următorul dezvoltator să nu creadă că lipsește dintr-o scăpare.

        TODO (viitor, neplanificat/neaprobat încă): odată ce Coverage Cache
        e populată efectiv de un task de sync dedicat (nescris încă — ar fi
        o extindere de scope neaprobată aici), acest adaptor poate trece la
        `coverage_cache.get_cached_coverage(...)` ca gate suplimentar —
        schimbare separată, cu propria aprobare explicită."""
        return True
