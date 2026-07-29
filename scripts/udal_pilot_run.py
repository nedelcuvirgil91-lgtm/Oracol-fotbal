"""
================================================================================
UDAL Faza 1 — Pilot Runner (ADR-042)
================================================================================
Rulează end-to-end pipeline-ul UDAL (Registry → Selector map → Adaptor →
Validation Layer → observabilitate) contra fixture-ului HTML static
(`docs/06_UDAL/fixtures/pilot_match_statistics.html`) — NICIUN acces live.

Două demonstrații separate, deliberat:
  1. Gate-ul ToS blochează fetch live — apelăm `preflight()` și confirmăm
     că ridică `ScraperPreflightError` (tos_reviewed=False pentru pilot).
  2. Pipeline-ul de shadow rulează pe fixture — `preflight()` NU se aplică
     aici (fixture local = zero contact cu o sursă reală, gate-ul ToS
     există pentru risc legal, care nu există pentru un fișier local).

Scrie UN singur rând real în `acquisition_run_log` (tabelă UDAL, creată
în Faza 0, NU canonică) — restul (match_history, orice tabelă canonică)
rămâne complet neatins, per constrângerea explicită a Fazei 1.

Rulare: `python scripts/udal_pilot_run.py`
================================================================================
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

root = Path(__file__).parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

FIXTURE_PATH = root / "docs" / "06_UDAL" / "fixtures" / "pilot_match_statistics.html"
SCRAPER_ID = "udal_pilot_generic_html_stats"

SELECTOR_MAP = {
    "row_selector": "table.match-stats tbody tr",
    "fields": {
        "home_team": "td.home-team",
        "away_team": "td.away-team",
        "kickoff_date": "td.date",
        "home_corners": "td.home-corners",
        "away_corners": "td.away-corners",
        "home_cards": "td.home-cards",
        "away_cards": "td.away-cards",
        "home_fouls": "td.home-fouls",
        "away_fouls": "td.away-fouls",
    },
}


def main() -> dict:
    import supabase_client as sb
    from generic_html_stats_scraper_adapter import (
        GenericHtmlStatsScraperAdapter, LiveFetchNotAllowedError,
    )
    from scraper_adapter_base import ScraperPreflightError
    from udal_validation import check_conflicts_with_match_history

    report: dict = {"scraper_id": SCRAPER_ID}

    # ── 1. Demonstrează gate-ul ToS (blochează live, per design Faza 0) ──
    adapter = GenericHtmlStatsScraperAdapter(SCRAPER_ID, SELECTOR_MAP)
    try:
        adapter.preflight()
        report["tos_gate_blocked_correctly"] = False
    except ScraperPreflightError as exc:
        report["tos_gate_blocked_correctly"] = True
        report["tos_gate_message"] = str(exc)

    try:
        adapter.fetch({"mode": "live", "url": "https://neconfirmat.example.invalid"})
        report["live_fetch_blocked_correctly"] = False
    except LiveFetchNotAllowedError as exc:
        report["live_fetch_blocked_correctly"] = True
        report["live_fetch_block_message"] = str(exc)

    # ── 2. Scrie harta de selectori în scraper_selector_registry (real,
    #        tabelă UDAL Faza 0, NU canonică) — round-trip complet. ──
    write_ok = sb.set_scraper_selector_map(SCRAPER_ID, SELECTOR_MAP, "udal-pilot-runner")
    loaded_map = sb.get_scraper_selector_map(SCRAPER_ID)
    report["selector_registry_write_ok"] = write_ok
    report["selector_registry_roundtrip_ok"] = (loaded_map == SELECTOR_MAP)

    # ── 3. Pipeline shadow, contra fixture — fetch/normalize/validate ──
    t0 = time.perf_counter()
    raw_html = adapter.fetch({"mode": "fixture", "fixture_path": str(FIXTURE_PATH)})
    fetch_latency_ms = (time.perf_counter() - t0) * 1000

    records = adapter.normalize(raw_html)
    validation = adapter.validate(records)
    persist_ok = adapter.persist(validation.valid)  # no-op deliberat, Faza 1

    conflicts = check_conflicts_with_match_history(validation.valid)

    report.update({
        "records_fetched": len(records),
        "records_valid": len(validation.valid),
        "records_rejected": len(validation.rejected),
        "rejection_reasons": [r.reason for r in validation.rejected],
        "validation_rate": round(validation.validation_rate, 4),
        "fetch_latency_ms": round(fetch_latency_ms, 3),
        "persist_returned": persist_ok,
        "conflicts_with_match_history": len(conflicts),
        "conflict_rate": round(len(conflicts) / len(validation.valid), 4) if validation.valid else 0.0,
    })

    # ── 4. Observabilitate reală — acquisition_run_log (NU canonic) ──
    run_log_ok = sb.record_acquisition_run(
        target_data_type="statistics", target_league="Romania SuperLiga",
        tier="http_scraper", mode="HISTORICAL", source_id=SCRAPER_ID,
        target_season="pilot-fixture",
        records_fetched=len(records), records_validated=len(validation.valid),
        records_persisted=0,  # niciodata >0 in Faza 1 - persist() e no-op
        records_rejected=len(validation.rejected),
        duration_ms=fetch_latency_ms,
    )
    report["acquisition_run_log_write_ok"] = run_log_ok

    return report


if __name__ == "__main__":
    result = main()
    print(json.dumps(result, indent=2, ensure_ascii=False))
