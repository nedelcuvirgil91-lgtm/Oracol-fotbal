"""
================================================================================
FOOTBALL ORACLE — FreeLF Form Adapter (R-Sync-6, ADR-039)
================================================================================
A cincea implementare reală a `SyncAdapter` (sync_adapter.py, R-Sync-1) —
standings/formă per echipă, sursa Free Live Football. Înlocuiește Level 0
(`self.api.get_freelf_standings()`) + Level 1
(`self.api.get_team_form_freelf()`) din cascada
`oracle_engine._build_profile()` — fuzionate aici într-un singur flux,
fiindcă amândouă citeau deja ACELAȘI răspuns FreeLF standings (Level 1
folosea `team_id`-ul produs de Level 0, nu de discovery — verificat prin
audit R-Sync-6, zero dependență de Match Discovery, spre deosebire de
FreeLF H2H, care rămâne live, deferred la R-Sync-8).

`fetch()` reutilizează EXACT `oracle_api.get_freelf_standings()` (deja
publică, deja funcțională) — nu se rescrie logica HTTP/parsare
(ADR-039 Principiul 4).

[GĂSIT LA AUDIT R-SYNC-6, nu ascuns] `get_team_form_freelf()` (calea live
veche) returnează întotdeauna `[]` în producție — `get_freelf_standings()`
nu copiază niciodată un câmp `"form"` din răspunsul brut FreeLF în
dicționarele sale normalizate (bug preexistent, confirmat prin citire de
cod). `normalize()` de mai jos reproduce fidel acest comportament — NU
ghicește numele câmpului real din payload-ul brut (decizie explicită,
proprietar produs: „Verificat, nu presupus"). Vezi task separat
R-Sync-6a (neînceput) pentru verificarea live și repararea ulterioară.
================================================================================
"""
from __future__ import annotations

import logging
from typing import Any

from sync_adapter import SyncAdapter

logger = logging.getLogger("FootballOracle.SyncAdapters.FreeLfForm")


class FreeLfFormAdapter(SyncAdapter):
    provider_id = "freelivefootball"

    def __init__(self, api=None):
        if api is None:
            from oracle_api import FootballOracleAPI
            api = FootballOracleAPI()
        self._api = api

    def fetch(self, params: dict) -> list[dict] | None:
        """`params`: `{"league"}` — codul de ligă intern FreeLF e rezolvat
        deja de `get_freelf_standings()` din `mappings.FREE_LF_LEAGUE_IDS`."""
        league = params["league"]
        return self._api.get_freelf_standings(league)

    def normalize(self, raw_payload: list[dict] | None) -> list[dict]:
        """Iterează TOATE echipele din tabelul de clasament FreeLF — un
        singur `fetch()` produce mai multe înregistrări, la fel ca
        `footballdata_form_adapter.normalize()` (R-Sync-3).

        `team_name` e trecut EXPLICIT prin `normalize_team_name()`
        (ADR-039 Principiul 7), deși `get_freelf_standings()` întoarce
        deja chei canonice — re-aplicarea e idempotentă, aceeași gardă
        defensivă folosită la R-Sync-4."""
        if not raw_payload:
            return []
        from mappings import normalize_team_name

        records: list[dict] = []
        for entry in raw_payload:
            raw_name = entry.get("team", "")
            if not raw_name:
                continue
            canonical_name = normalize_team_name(raw_name)
            records.append({
                "team_name":      canonical_name,
                "played":         entry.get("played", 0),
                "wins":           entry.get("wins", 0),
                "draws":          entry.get("draws", 0),
                "losses":         entry.get("losses", 0),
                "goals_for":      entry.get("goals_for", 0),
                "goals_against":  entry.get("goals_against", 0),
                "points":         entry.get("points", 0),
                "position":       entry.get("position"),
                # [GĂSIT LA AUDIT, nu ascuns] get_freelf_standings() nu
                # include niciodată "form" — vezi docstring-ul modulului.
                "form":           entry.get("form", "") or "",
            })
        return records

    def validate(self, records: list[dict]) -> list[dict]:
        """Exclude, nu aruncă excepție — un rând fără `team_name` valid
        sau fără meciuri jucate nu poate produce formă utilizabilă
        (Regula #8)."""
        valid: list[dict] = []
        for r in records:
            if not r.get("team_name"):
                logger.warning("[FreeLfFormAdapter] rând fără team_name, exclus: %r", r)
                continue
            if not r.get("played"):
                continue
            valid.append(r)
        return valid

    def persist(self, records: list[dict]) -> bool:
        from database.queries import upsert_team_form_freelf

        ok = True
        for r in records:
            success = upsert_team_form_freelf(
                r["team_name"], r["played"], r["wins"], r["draws"], r["losses"],
                r["goals_for"], r["goals_against"], r["points"], r.get("position"), r["form"],
            )
            ok = ok and success
        return ok

    def coverage_check(self, context: dict) -> bool:
        """[DELIBERAT, nu omisiune] Fără concept de coverage separat —
        gating-ul real e deja la apelant (sync/sync_team_form_freelf.py,
        iterează exclusiv `mappings.FREE_LF_LEAGUE_IDS`). Suprascrierea de
        mai jos (True, identică cu default-ul din SyncAdapter) există
        explicit — tiparul din `footballdata_form_adapter.coverage_check()`
        (R-Sync-3)."""
        return True
