"""
================================================================================
FOOTBALL ORACLE — Flashscore Extraction Map (R-Sync-FLASH-01, ADR-042)
================================================================================
Module: providers/flashscore/extractor.py

DATE, nu cod — o hartă de extracție declarativă (`udal_extraction.extract()`,
Faza 1.5) peste selectorii `data-testid="wcl-*"` confirmați structural în
`UDAL_FLASHSCORE_POC_10MATCHES_REPORT.md` (secțiunea 5) prin verificare
manuală directă pe evidența brută — nicio valoare din harta de mai jos e
ghicită.

Nu conține niciun cod de fetch/navigare. Selectorii marcați cu status
"neconfirmat" în POC (H2H rows, coach, bench complet) sunt DELIBERAT
absenți din hartă — mai bine lipsă decât o presupunere silențioasă
(North Star #8, „nicio stare necunoscută nu se aproximează").
================================================================================
"""
from __future__ import annotations

# Confirmat in POC (SuperLiga #1, UCL #6) - vezi grep-uri directe pe
# evidenta bruta, sectiunea 5 a raportului.
MATCH_SUMMARY_EXTRACTION_MAP: dict = {
    "referee": {"selector": "[data-testid='wcl-summaryMatchInformation']", "field": "referee_name"},
    "venue": {"selector": "[data-testid='wcl-summaryMatchInformation']", "field": "venue_name"},
    "attendance": {"selector": "[data-testid='wcl-summaryMatchInformation']", "field": "attendance_value"},
    "statistics": {
        "selector": "[data-testid='wcl-statistics-value']",
        "repeated": True,
        "fields": ["home_value", "away_value"],
    },
}

LINEUPS_EXTRACTION_MAP: dict = {
    "players": {
        "selector": "[data-testid='wcl-lineupsParticipantName']",
        "repeated": True,
        "fields": ["shirt_number", "player_name"],
    },
    "ratings": {"selector": "[data-testid='wcl-badgeRating']", "repeated": True, "fields": ["rating_value"]},
    "substitution_events": {
        "selector": "[data-testid='wcl-lineupsParticipantsSubstitution-left'], "
                    "[data-testid='wcl-lineupsParticipantsSubstitution-right']",
        "repeated": True,
    },
}

# Explicit GOALE - camp neconfirmat in POC, nu se declara o harta pe o
# presupunere (bench complet / nume antrenor / randuri H2H reale / cote
# sub selectorul asteptat initial - vezi raport, sectiunea 6).
UNCONFIRMED_FIELDS = ("coach_name", "bench_full_list", "h2h_history_rows")
