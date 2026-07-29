"""
================================================================================
FOOTBALL ORACLE — Provider Registry (ADR-034, Strat 1/6)
================================================================================
Module: provider_registry.py

ProviderRegistry este singurul boundary arhitectural dintre Selection
Architecture (ADR-034 — Capability Registry, League Mapping v2, Health
Monitor, Selection Engine) și KeyManager. Începând cu acest fișier, orice
modul NOU accesează providerii exclusiv prin ProviderRegistry — acces direct
la key_manager.PROVIDERS/APIKeyManager rămâne permis doar în cod legacy
(oracle_api.py, football_providers.py existent) până la o migrare completă,
neprogramată încă, care ar necesita un ADR propriu.

Model de DOMENIU, nu de implementare: Provider Registry descrie „providerii
existenți în sistem", nu „providerii care folosesc chei". Lista canonică e
DECLARATĂ AICI, independent de key_manager.PROVIDERS — nu derivă din el.
ESPN și TheSportsDB sunt provideri valizi, prezenți în registry, deși nu au
nicio cheie/credențial — key_manager rămâne relevant DOAR pentru providerii
care chiar necesită credențiale (`requires_credentials=True`); pentru cei
fără, Registry răspunde direct, fără să atingă key_manager deloc. Dacă
key_manager.py ar dispărea mâine complet, Provider Registry tot ar exista
și ar descrie corect toți providerii — asta e testul de „model de domeniu,
nu de implementare".

Expune DOAR metodele necesare consumatorilor definiți de ADR-034 — nu un
wrapper complet peste APIKeyManager. Administrarea cheilor (alerts,
summary_line, add_key, reset_month, mark_exhausted) rămâne exclusiv în
key_manager.py — nu aparține Registry-ului.

Nu introduce niciun comportament nou: nicio scriere Supabase, niciun apel
HTTP, nicio schimbare de flux.
================================================================================
"""
from __future__ import annotations

from dataclasses import dataclass

from acquisition_tier import AcquisitionTier


@dataclass(frozen=True)
class ProviderRecord:
    provider_id: str
    name: str
    requires_credentials: bool
    # [ADAUGAT UDAL Faza 0, ADR-042] Aditiv, cu default — toți cei 9
    # provideri declarați azi rămân AcquisitionTier.API fără să fie atinși
    # individual (niciunul nu e un scraper sau un target Playwright).
    tier: AcquisitionTier = AcquisitionTier.API


# Declarație de domeniu, canonică, independentă de key_manager.PROVIDERS.
# Un provider nou (credențiat SAU nu) se adaugă DOAR aici — niciodată prin
# derivare automată dintr-un alt registry (key_manager e infrastructură,
# nu sursa de adevăr pentru „ce provideri există").
_PROVIDER_DECLARATIONS: tuple[ProviderRecord, ...] = (
    ProviderRecord("apifootball", "API-Football (api-sports.io)", requires_credentials=True),
    ProviderRecord("sportapi", "SportAPI (RapidAPI / Sofascore)", requires_credentials=True),
    ProviderRecord("freelivefootball", "Free Live Football (RapidAPI)", requires_credentials=True),
    ProviderRecord("oddsapi", "The Odds API", requires_credentials=True),
    ProviderRecord("footballdata", "football-data.org", requires_credentials=True),
    ProviderRecord("weatherapi", "WeatherAPI", requires_credentials=True),
    ProviderRecord("espn", "ESPN (public API)", requires_credentials=False),
    ProviderRecord("thesportsdb", "TheSportsDB (free tier)", requires_credentials=False),
    # [ADAUGAT] Etapa C, Sprint 1 (ADR-041 Faza 1) — verificat live 2026-07-27
    # (POC izolat, sters dupa test): Romania Liga I confirmata (important=true),
    # UEFA Champions/Europa/Conference League + qualifiers confirmate, meci real
    # verificat integral (Dinamo Bucuresti - Universitatea Craiova, 25.07.2026).
    ProviderRecord("soccerfootballinfo", "Soccer Football Info (RapidAPI)", requires_credentials=True),
)


class ProviderRegistry:
    def __init__(self, key_manager=None, providers: tuple[ProviderRecord, ...] | None = None):
        # key_manager e folosit DOAR pentru providerii cu
        # requires_credentials=True, în cele 4 metode operaționale de mai
        # jos — list_providers()/get_provider() nu-l ating niciodată.
        #
        # Rezolvare LENEȘĂ (TECH-DEBT-ADR034-001, rezolvat în PR4): dacă nu
        # e injectat explicit, key_manager NU se importă/instanțiază la
        # construirea Registry-ului, ci abia la primul apel care chiar are
        # nevoie de el — un Registry folosit exclusiv pentru provideri fără
        # credențiale (espn, thesportsdb) nu atinge niciodată key_manager.py.
        # Rezultatul se cache-uiește după prima rezolvare (un singur import
        # per instanță de Registry).
        self._km = key_manager
        self._providers = providers if providers is not None else _PROVIDER_DECLARATIONS

    def _resolve_km(self):
        if self._km is None:
            from key_manager import get_key_manager
            self._km = get_key_manager()
        return self._km

    def list_providers(self) -> list[ProviderRecord]:
        return list(self._providers)

    def get_provider(self, provider_id: str) -> ProviderRecord | None:
        for record in self._providers:
            if record.provider_id == provider_id:
                return record
        return None

    def is_available(self, provider_id: str) -> bool:
        record = self.get_provider(provider_id)
        if record is None:
            return False
        if not record.requires_credentials:
            return True  # niciun gate de credential nu se aplica
        return self._resolve_km().is_available(provider_id)

    def get_headers(self, provider_id: str) -> dict | None:
        record = self.get_provider(provider_id)
        if record is None or not record.requires_credentials:
            return None  # fara schema de autentificare
        return self._resolve_km().get_headers(provider_id)

    def record_result(self, provider_id: str, success: bool = True) -> None:
        """
        Înregistrează un apel efectuat. Cota se consumă indiferent de
        rezultat (așa se comportă și providerii reali — un 404/429 tot
        consumă din cotă), de-asta record_request() se apelează
        necondiționat pentru providerii cu credențiale. Pentru cei fără
        credențiale, nu există concept de cotă — no-op. 'success' e
        păstrat pentru Health Monitor (PR4), care are nevoie de eșecuri
        pentru scorul de reliability — semnătura rămâne stabilă de acum,
        nu se rupe contractul în PR4.
        """
        record = self.get_provider(provider_id)
        if record is None or not record.requires_credentials:
            return
        self._resolve_km().record_request(provider_id)

    def get_quota_status(self, provider_id: str) -> dict | None:
        record = self.get_provider(provider_id)
        if record is None or not record.requires_credentials:
            return None  # fara concept de cota
        status = self._resolve_km().get_status()
        return status.get("providers", {}).get(provider_id)


_registry_instance: ProviderRegistry | None = None


def get_provider_registry() -> ProviderRegistry:
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = ProviderRegistry()
    return _registry_instance
