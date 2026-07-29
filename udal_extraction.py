"""
================================================================================
FOOTBALL ORACLE — UDAL Generic Extraction (Faza 1.5, ADR-042)
================================================================================
Module: udal_extraction.py

Generalizează harta de selectori „plată" din Faza 1
(`generic_html_stats_scraper_adapter.py`, `row_selector` + `fields`) la o
hartă IERARHICĂ, capabilă să acopere aproape orice câmp al unui meci
(Match/Teams/Score/Statistics/Advanced Statistics/Lineups/Player
Statistics/Injuries/Odds) — grupuri simple (scalare) ȘI liste repetate
(11 jucători, bancă, accidentări), fără cod nou per grup.

Un SINGUR walker recursiv (`extract()`) funcționează IDENTIC indiferent
de mecanismul de extragere de dedesubt — CSS (HTML) sau JSON path (API
neoficial, ex. SofaScore) — prin injectarea unui `Resolver` (pereche de
funcții `scalar`/`list_items`), nu prin cod duplicat per tip de sursă.
Asta e proba arhitecturală cerută explicit: „aceeași logică, doar
config/resolver diferă".

Formatul hărții (recursiv, per nod):
  - string  → selector/path scalar (extrage o valoare text).
  - dict cu chei "list"+"item" → grup REPETAT (extrage o listă de
    sub-recorduri, fiecare conform sub-hărții "item").
  - dict fără "list"/"item"    → grup NEREPETAT (recurge, produce un
    sub-dict cu aceeași structură).

Câmp lipsă din sursă (selector/path fără corespondent) → `None`, NICIODATĂ
aproximat (ADR-001) — Compatibility Matrix-ul (Faza 1.5) se bazează exact
pe această distincție.
================================================================================
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class Resolver:
    """Pereche de funcții — TOATĂ diferența dintre a extrage din HTML
    (BeautifulSoup) sau dintr-un payload JSON e concentrată aici, nicăieri
    altundeva. `scalar(container, path) -> str | None`.
    `list_items(container, path) -> list[Any]` (containere pentru fiecare
    element, gata de pasat recursiv la `extract()`)."""
    scalar: Callable[[Any, str], str | None]
    list_items: Callable[[Any, str], list[Any]]


def extract(container: Any, extraction_map: dict, resolver: Resolver) -> dict:
    result: dict = {}
    for key, node in extraction_map.items():
        if isinstance(node, str):
            result[key] = resolver.scalar(container, node)
        elif isinstance(node, dict) and "list" in node and "item" in node:
            items = resolver.list_items(container, node["list"])
            result[key] = [extract(item, node["item"], resolver) for item in items]
        elif isinstance(node, dict):
            result[key] = extract(container, node, resolver)
        else:
            raise ValueError(f"Nod invalid in extraction_map la cheia {key!r}: {node!r}")
    return result


# ── Resolver CSS (BeautifulSoup) — folosit de Tier 1 (HTTP) și Tier 2
#    (Playwright, DOAR pentru normalize() — fetch()-ul Tier 2 ramane
#    neimplementat in aceasta faza, vezi generic_playwright_stats_scraper_adapter.py) ──

def _css_scalar(container, selector: str) -> str | None:
    el = container.select_one(selector)
    return el.get_text(strip=True) if el else None


def _css_list_items(container, selector: str) -> list[Any]:
    return list(container.select(selector))


CSS_RESOLVER = Resolver(scalar=_css_scalar, list_items=_css_list_items)


# ── Resolver JSON path (SofaScore-style, API neoficiala) ──
# Path simplu, punctat, cu index optional intre paranteze patrate:
# "statistics.home.possession" sau "lineups.home.players[0].name".

def _walk_json_path(container: Any, path: str) -> Any:
    current = container
    for segment in path.split("."):
        if current is None:
            return None
        key = segment
        index: int | None = None
        if "[" in segment and segment.endswith("]"):
            key, idx_str = segment[:-1].split("[")
            index = int(idx_str)
        if key:
            if not isinstance(current, dict) or key not in current:
                return None
            current = current[key]
        if index is not None:
            if not isinstance(current, list) or index >= len(current):
                return None
            current = current[index]
    return current


def _json_scalar(container, path: str) -> str | None:
    value = _walk_json_path(container, path)
    if value is None:
        return None
    return str(value)


def _json_list_items(container, path: str) -> list[Any]:
    value = _walk_json_path(container, path)
    return value if isinstance(value, list) else []


JSON_RESOLVER = Resolver(scalar=_json_scalar, list_items=_json_list_items)
