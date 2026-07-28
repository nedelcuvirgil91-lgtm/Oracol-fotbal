"""
================================================================================
UDAL Faza 1.5 — Generic Scraper Validation Runner (ADR-042)
================================================================================
Rulează ACELAȘI cod de adaptor (`GenericRichMatchScraperAdapter` pt.
worldfootball/soccerway/footystats — Tier 1 CSS; `GenericJsonMatchScraperAdapter`
pt. sofascore — Tier 1 JSON path; `GenericPlaywrightMatchScraperAdapter` pt.
flashscore/aiscore — Tier 2, doar normalize()) contra fixture-urilor din
`docs/06_UDAL/fixtures/faza1_5/`, cu DOAR extraction map-ul schimbat per
sursă — nicio ramură de cod per site.

Produce datele brute pentru cele 5 livrabile cerute (Compatibility Matrix,
Selector Complexity, HTML Stability, Generic Adapter Score, Recommendation)
— scrise integral în `UDAL_FAZA1_5_GENERIC_VALIDATION_REPORT.md`, nu
inventate separat.

Nicio scriere Supabase, niciun acces live, niciun flag activat.
================================================================================
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

root = Path(__file__).parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

FIXTURES = root / "docs" / "06_UDAL" / "fixtures" / "faza1_5"
CONFIGS = root / "docs" / "06_UDAL" / "site_configs"

CANONICAL_CATEGORIES = (
    "match", "teams", "score", "statistics", "advanced_statistics",
    "lineups", "player_statistics", "injuries", "odds",
)

_SITES = {
    "worldfootball": {"kind": "css_tier1", "fixture": "worldfootball_match.html"},
    "soccerway": {"kind": "css_tier1", "fixture": "soccerway_match.html"},
    "footystats": {"kind": "css_tier1", "fixture": "footystats_match.html"},
    "sofascore": {"kind": "json_tier1", "fixture": "sofascore_match.json"},
    "flashscore": {"kind": "css_tier2", "fixture": "flashscore_match_rendered.html"},
    "aiscore": {"kind": "css_tier2", "fixture": "aiscore_match_rendered.html"},
}


def _category_populated(record: dict, category: str) -> bool:
    node = record.get(category)
    if node is None:
        return False
    if isinstance(node, dict):
        return any(v not in (None, [], "") for v in node.values())
    if isinstance(node, list):
        return len(node) > 0
    return bool(node)


def main() -> dict:
    from generic_rich_match_scraper_adapter import (
        GenericRichMatchScraperAdapter, GenericJsonMatchScraperAdapter,
        GenericPlaywrightMatchScraperAdapter, PlaywrightNotImplementedError,
    )

    report: dict = {"sites": {}}
    same_class_used: set[str] = set()
    normalize_method_identity: dict[str, int] = {}

    for site_id, meta in _SITES.items():
        config_path = CONFIGS / f"{site_id}_extraction_map.json"
        extraction_map = json.loads(config_path.read_text(encoding="utf-8"))
        extraction_map.pop("extraction_type", None)
        extraction_map.pop("_comment", None)
        fixture_path = FIXTURES / meta["fixture"]

        if meta["kind"] == "css_tier1":
            adapter = GenericRichMatchScraperAdapter(site_id, extraction_map)
            same_class_used.add(type(adapter).__name__)
            raw = adapter.fetch({"mode": "fixture", "fixture_path": str(fixture_path)})
        elif meta["kind"] == "json_tier1":
            adapter = GenericJsonMatchScraperAdapter(site_id, extraction_map)
            raw = adapter.fetch({"mode": "fixture", "fixture_path": str(fixture_path)})
        else:  # css_tier2
            adapter = GenericPlaywrightMatchScraperAdapter(site_id, extraction_map)
            try:
                adapter.fetch({"mode": "fixture", "fixture_path": str(fixture_path)})
                fetch_blocked = False
            except PlaywrightNotImplementedError:
                fetch_blocked = True
            # normalize() ramane apelabil direct - reprezinta DOM post-randare
            # deja disponibil (simuleaza ce ar preda un fetch() Playwright real).
            raw = fixture_path.read_text(encoding="utf-8")
            report["sites"].setdefault(site_id, {})["fetch_correctly_blocked"] = fetch_blocked

        normalize_method_identity[site_id] = id(type(adapter).normalize)

        records = adapter.normalize(raw)
        validation = adapter.validate(records)
        record = validation.valid[0] if validation.valid else (records[0] if records else {})

        coverage = {cat: _category_populated(record, cat) for cat in CANONICAL_CATEGORIES}

        report["sites"].setdefault(site_id, {}).update({
            "tier": adapter.tier.value,
            "extraction_kind": meta["kind"],
            "valid": len(validation.valid),
            "rejected": len(validation.rejected),
            "coverage": coverage,
            "categories_covered": sum(coverage.values()),
        })

    # Proba de reutilizare: aceeasi clasa (GenericRichMatchScraperAdapter)
    # a rulat pentru 3 surse diferite (worldfootball/soccerway/footystats).
    report["tier1_css_shared_class"] = sorted(same_class_used)
    # Proba ca normalize() e IDENTIC (acelasi obiect metoda in memorie)
    # intre Tier 1 (worldfootball) si Tier 2 (flashscore) - mostenit din
    # acelasi mixin, nu redefinit.
    report["normalize_shared_between_tier1_and_tier2"] = (
        normalize_method_identity["worldfootball"] == normalize_method_identity["flashscore"]
    )

    return report


if __name__ == "__main__":
    result = main()
    print(json.dumps(result, indent=2, ensure_ascii=False))
