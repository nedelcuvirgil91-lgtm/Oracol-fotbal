"""
================================================================================
FOOTBALL ORACLE — Equivalence Root Cause (ADR-040, G2)
================================================================================
Module: equivalence_root_cause.py

Enum centralizat + funcții dedicate de clasificare — extensibil prin
adăugarea unei intrări în dicționar, NICIODATĂ prin extinderea unui CASE
gigantic (decizie explicită proprietar produs, G2, principiul 4). Zero I/O,
zero cunoaștere de entitate specifică (`scheduled_fixtures` sau oricare
alta) — orice evaluator viitor poate reutiliza acest modul neschimbat.

Fiecare funcție e o clasificare EURISTICĂ, etichetată ca atare — nu o
dovadă de cauzalitate („Verificat, nu presupus", CLAUDE.md). `UNKNOWN` e
un rezultat acceptat, nu un eșec al clasificării.
================================================================================
"""
from __future__ import annotations

VENUE_PRIORITY = "VENUE_PRIORITY"
LEAGUE_MAPPING = "LEAGUE_MAPPING"
KICKOFF_CONFLICT = "KICKOFF_CONFLICT"
MISSING_PROVIDER_ID = "MISSING_PROVIDER_ID"
PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
TEAM_NORMALIZATION = "TEAM_NORMALIZATION"  # rezervat — neatribuit automat azi, fără semnal determinist
UNKNOWN = "UNKNOWN"

ALL_CATEGORIES = frozenset({
    VENUE_PRIORITY, LEAGUE_MAPPING, KICKOFF_CONFLICT,
    MISSING_PROVIDER_ID, PROVIDER_TIMEOUT, TEAM_NORMALIZATION, UNKNOWN,
})

# Extensibil: o intrare nouă (nume-câmp -> categorie) pentru o entitate
# viitoare se adaugă AICI, nu prin atingerea evaluatorului care o apelează.
_FIELD_TO_CATEGORY: dict[str, str] = {
    "venue_city": VENUE_PRIORITY,
    "league": LEAGUE_MAPPING,
    "kickoff_utc": KICKOFF_CONFLICT,
}


def classify_field_difference(field: str) -> str:
    return _FIELD_TO_CATEGORY.get(field, UNKNOWN)


def classify_provider_id_difference(scheduled_value) -> str:
    """`scheduled_value` = valoarea persistată azi pentru acel identificator
    de provider (None => lipsă, altfel => conflict cu valoarea live)."""
    if scheduled_value is None:
        return MISSING_PROVIDER_ID
    # Ambele valori prezente, diferite -- ar viola invariantul COALESCE-only
    # al FixtureMergePolicy (migrarea 023). Nu e un caz cu semnal determinist
    # de cauză -- doar prioritate maximă de investigare (ADR-040, Principiul 5).
    return UNKNOWN


def classify_missing_scheduled() -> str:
    """Meci prezent în calea live, absent din tabela canonică — presupunere
    ETICHETATĂ (poate fi și sync neexecutat, nu doar timeout de provider)."""
    return PROVIDER_TIMEOUT


def classify_missing_live() -> str:
    """Rând persistat fără corespondent în calea live curentă ("fantomă") —
    deliberat neclasificat (a distinge reprogramare reală de eroare de
    normalizare ar cere o euristică de similaritate de nume, neimplementată
    speculativ)."""
    return UNKNOWN
