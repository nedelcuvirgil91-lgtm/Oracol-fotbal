"""
================================================================================
FOOTBALL ORACLE — Sync Adapter (generic interface, ADR-039)
================================================================================
Generalizează `FootballDataProvider` (football_providers.py) la orice
provider, nu doar API-Football — interfața comună pe care orice viitor
adaptor de sincronizare o implementează, exact cum football_providers.py
însuși descrie în propriul docstring de la început: „orice provider viitor
implementează aceeași interfață, fără să schimbe nimic în
FootballOracleEngine".

Pas nou față de `FootballDataProvider`: `validate()` — separat explicit de
`normalize()`, formalizând ce era până acum informal (parsare defensivă
împrăștiată în fiecare `_normalize_*`). `fetch`/`normalize`/`persist` rămân
conceptual identice cu tiparul deja dovedit.

[NOTĂ DE DISCIPLINĂ] Interfața de mai jos e strict un contract de METODE —
NU definește tipuri concrete de înregistrări (Fixture/OddsSnapshot/
WeatherSnapshot/etc.). Acelea se definesc per adaptor concret, la migrarea
efectivă a fiecărui provider (R-Sync-2 și următoarele, ADR-039 audit §8/§6),
nu presupuse acum — exact disciplina deja aplicată în tot proiectul
(niciun feature/tabelă/abstracție nu se construiește înainte de un caz de
utilizare real dovedit).

Niciun adaptor concret nu se implementează aici. Acest modul e strict
interfața — Sync Orchestrator (sync_orchestrator.py) și Request Manager
(request_manager.py) nu cunosc niciun detaliu concret despre vreun provider,
lucrează exclusiv prin acest contract.
================================================================================
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class SyncAdapter(ABC):
    """Orice viitor adaptor de sincronizare (API-Football, Odds API,
    Weather, football-data.org, FreeLF, ESPN, TheSportsDB, orice provider
    viitor) implementează această interfață."""

    provider_id: str

    @abstractmethod
    def fetch(self, params: dict) -> Any | None:
        """Unicul punct de apel HTTP către provider — trece prin Request
        Manager (RAM cache, dedup, gating de buget), niciodată direct."""
        ...

    @abstractmethod
    def normalize(self, raw_payload: Any) -> list[Any]:
        """Transformă răspunsul brut în înregistrări canonice — forma
        specifică tipului de date, definită de fiecare adaptor concret."""
        ...

    @abstractmethod
    def validate(self, records: list[Any]) -> list[Any]:
        """Filtrează/respinge înregistrări invalide (plajă de valori, nu
        doar formă de payload) — NICIODATĂ nu aruncă excepție pentru un
        rând individual invalid, doar îl exclude (Regula #8 — degradare
        grațioasă, nu oprire completă pentru o singură înregistrare proastă)."""
        ...

    @abstractmethod
    def persist(self, records: list[Any]) -> bool:
        """Scrie în Supabase — owner unic de scriere per tip de date
        (disciplina ADR-036). Niciodată apelat de Oracle Engine/ML/
        Feature Engineering — exclusiv de Sync Layer."""
        ...

    def coverage_check(self, context: dict) -> bool:
        """Opțional — implicit True (fără restricție de coverage). Doar
        providerii cu concept real de coverage (ex. API-Football, per
        ligă+sezon) suprascriu asta — Weather/Kaggle nu au nevoie
        (audit §2, „capacitate opțională a adaptorului, nu obligatorie")."""
        return True
