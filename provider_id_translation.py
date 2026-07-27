"""
================================================================================
FOOTBALL ORACLE — Legacy Provider ID Translation Adapter
================================================================================
Module: provider_id_translation.py

UNICUL scop al acestui fișier: traduce cheile istorice folosite în
mappings.py (`football_data`/`tsdb`/`odds`/`freelf`/`api_football`/`espn`)
către provider_id-urile canonice din provider_registry.py (`footballdata`/
`thesportsdb`/`oddsapi`/`freelivefootball`/`apifootball`/`espn`).

Izolat aici EXPLICIT, per Regula de Aur #3 (niciun strat nou nu are voie
să cunoască detalii legacy ale altui strat — legacy trebuie izolat într-un
adaptor dedicat, niciodată propagat): `league_mapping.py` (și orice strat
viitor) apelează `to_canonical()`/`to_legacy()`, nu cunoaște niciodată
denumirile vechi direct. Acest fișier va dispărea (sau se va goli) când
mappings.py va fi migrat să folosească direct provider_id-uri canonice —
e proiectat să fie ținta unică a acelei migrări, nu răspândită oriunde.

Nu introduce niciun comportament nou: pură traducere de string, fără
I/O, fără dependințe de key_manager/mappings/oracle_api.
================================================================================
"""
from __future__ import annotations

from types import MappingProxyType
from typing import Mapping

LEGACY_TO_CANONICAL: Mapping[str, str] = MappingProxyType({
    "football_data": "footballdata",
    "tsdb": "thesportsdb",
    "odds": "oddsapi",
    "freelf": "freelivefootball",
    "api_football": "apifootball",
    "espn": "espn",
    # [ADAUGAT] Etapa C, Sprint 1 (ADR-041 Faza 1) — provider NOU, nu migrare
    # dintr-un nume legacy: auto-mapare, cheia din mappings.py e deja
    # canonica. Pastreaza contractul bijectiv al acestui fisier fara sa
    # introduca logica noua in league_mapping.py.
    "soccerfootballinfo": "soccerfootballinfo",
})

CANONICAL_TO_LEGACY: Mapping[str, str] = MappingProxyType(
    {canonical: legacy for legacy, canonical in LEGACY_TO_CANONICAL.items()}
)

# Fail loud, la import, nu doar la testare: daca vreo editare viitoare
# introduce doua chei legacy care traduc catre acelasi canonical_id,
# CANONICAL_TO_LEGACY ar pierde tacit una dintre ele (last-write-wins in
# dict comprehension) - bijectivitatea trebuie sa fie adevarata structural,
# nu doar verificata ulterior de teste.
if len(set(LEGACY_TO_CANONICAL.values())) != len(LEGACY_TO_CANONICAL):
    raise AssertionError(
        "LEGACY_TO_CANONICAL nu e bijectiv - exista valori (canonical_id) "
        "duplicate, cel putin doua chei legacy ar traduce catre acelasi provider."
    )


def to_canonical(legacy_key: str) -> str | None:
    return LEGACY_TO_CANONICAL.get(legacy_key)


def to_legacy(canonical_provider_id: str) -> str | None:
    return CANONICAL_TO_LEGACY.get(canonical_provider_id)
