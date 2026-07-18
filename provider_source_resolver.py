"""
================================================================================
FOOTBALL ORACLE — Provider Source Resolver (ADR-034, PR5 — adaptor infra)
================================================================================
Module: provider_source_resolver.py

Traduce vocabularul PROPRIU al lui oracle_api.py (câmpul "source" din
fiecare dict de meci — "the-odds-api", "football-data.org" etc., o A TREIA
vocabulară de nume, diferită atât de mappings.py cât și de canonicul din
Provider Registry) către provider_id canonic, și determină "current
provider"-ul per ligă pentru shadow logging (PR5).

Izolat aici, deliberat (Regula de Aur #3) — provider_selector.py (domeniu)
nu cunoaște niciodată acest vocabular, primește doar current_provider: str
deja tradus, ca parametru simplu.

current_provider = providerul canonic cu CELE MAI MULTE meciuri pentru liga
respectivă, în rezultatul final — NU primul întâlnit, independent de
ordinea reală a fallback-ului din oracle_api.py (decizie explicită de
design). Egalitate -> tie-break prin fallback_priority (reflectă ordinea
curentă a pașilor din get_matches_for_week(), DOAR ca tie-break, nu ca
definiție).
================================================================================
"""
from __future__ import annotations

from types import MappingProxyType

_ORACLE_SOURCE_TO_CANONICAL: MappingProxyType[str, str] = MappingProxyType({
    "the-odds-api": "oddsapi",
    "football-data.org": "footballdata",
    # freelivefootball / espn / thesportsdb / apifootball sunt deja identice
    # cu provider_id canonic — nicio traducere necesară.
})

# Reflectă ordinea reală a pașilor 1-6 din oracle_api.get_matches_for_week()
# la data scrierii acestui modul — folosită STRICT ca tie-break determinist,
# nu ca definiție a lui "current provider".
FALLBACK_PRIORITY: tuple[str, ...] = (
    "oddsapi", "freelivefootball", "footballdata", "espn", "thesportsdb", "apifootball",
)


def _canonical_source(raw_source: str) -> str:
    return _ORACLE_SOURCE_TO_CANONICAL.get(raw_source, raw_source)


def determine_current_provider(
    league: str, matches: list[dict], fallback_priority: tuple[str, ...] = FALLBACK_PRIORITY,
) -> str | None:
    counts: dict[str, int] = {}
    for m in matches:
        if m.get("league") != league:
            continue
        raw_source = m.get("source") or ""
        if raw_source.startswith("demo-"):
            continue  # nu e provider real — Fail Loud, nu se numără ca sursă
        canonical = _canonical_source(raw_source)
        counts[canonical] = counts.get(canonical, 0) + 1

    if not counts:
        return None

    max_count = max(counts.values())
    for provider_id in fallback_priority:  # tuple fix -> tie-break determinist
        if counts.get(provider_id, 0) == max_count:
            return provider_id
    return None
