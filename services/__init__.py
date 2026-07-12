"""
services/ — Domain services ale Football Oracle.

Fiecare serviciu de aici e independent de orchestratori (ex. sync/run_daily.py):
poate fi importat și reutilizat identic din backfill, CLI manual, un cron cu
altă cadență, sau un worker viitor.

Momentan conține:
  - odds_persistence_service.py — OddsPersistenceService (persistare cote
    de piață în odds_history, conform docs/03_ENGINE/ODDS_PERSISTENCE_DESIGN.md)
"""
