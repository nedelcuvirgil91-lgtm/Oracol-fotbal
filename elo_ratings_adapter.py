"""
================================================================================
FOOTBALL ORACLE — National Team ELO Adapter (R-Sync-4, ADR-039)
================================================================================
A treia implementare reală a `SyncAdapter` (sync_adapter.py, R-Sync-1) —
ELO pentru echipele NAȚIONALE, sursa eloratings.net. Servirea live nu mai
apelează niciodată acest adapter direct — citește exclusiv din
`national_team_elo_snapshot` (Database-First, `database.queries.
get_national_team_elo()`), populată separat de Sync Layer.

Corecție de scope (audit §6c): NU e TheSportsDB — eloratings.net e un
provider distinct (scrape), confundat inițial cu TheSportsDB în auditul
original. TheSportsDB team stats rămâne, deliberat, neatins aici —
R-Sync-8, după Universal Match Discovery Layer.

[CORECTAT — audit infrastructură, 2026-08-10] Implementarea inițială
(`fetch()` delegat la `oracle_api.get_national_elo_ratings_raw()`, care la
rândul ei făcea `requests.get()` + BeautifulSoup pe HTML BRUT) nu a
funcționat NICIODATĂ real — confirmat live (POC izolat, două etape):
eloratings.net randază tabelul de ratinguri 100% client-side prin
SlickGrid (`slick.grid.js`), răspunsul HTTP brut are ~1.8KB, zero
`<table>`, zero date. Fiecare rulare săptămânală cădea tăcut pe
`ELO_RATINGS_FALLBACK` (mappings.py) — aceleași 47 de valori statice, de
la crearea sincronizării. Fix: randare reală (Playwright, Chromium
headless — deja dependință activă a proiectului, folosită pentru
Flashscore) — vezi `_fetch_rendered_html()`/`parse_elo_ratings_html()`
mai jos. Confirmat live (a doua etapă a POC-ului): 244 echipe naționale
reale, cu ratinguri curente (ex. Spain 2259, Argentina 2173, England
2125 — diferite de valorile statice vechi, care erau aproximări).
================================================================================
"""
from __future__ import annotations

import logging

from sync_adapter import SyncAdapter

logger = logging.getLogger("FootballOracle.SyncAdapters.EloRatings")

ELO_URL = "https://www.eloratings.net"


def parse_elo_ratings_html(html: str) -> dict[str, int]:
    """Funcție PURĂ — separată explicit de randarea Playwright
    (`_fetch_rendered_html()`), ca parsarea să rămână testabilă offline,
    fără browser (tipar identic `providers/flashscore/discovery.py`:
    `page.content()` -> funcție pură de parsare).

    Parsează HTML-ul RANDAT (după execuție JS, nu răspunsul HTTP brut).
    Grid-ul SlickGrid produce un `<div class="slick-row">` per echipă,
    fiecare cu `<div class="slick-cell">` per coloană, în ordine: rang,
    nume echipă, rating ELO, ... (restul coloanelor — meciuri jucate,
    victorii/egaluri/înfrângeri, goluri — nu sunt folosite azi de proiect,
    ignorate deliberat). Confirmat live, structură reală (POC izolat,
    2026-08-10): 244 rânduri, coloana 1 = nume, coloana 2 = ELO."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    ratings: dict[str, int] = {}
    for row in soup.select(".slick-row"):
        cells = row.select(".slick-cell")
        if len(cells) < 3:
            continue
        name = cells[1].get_text(strip=True)
        elo_text = cells[2].get_text(strip=True).replace(",", "")
        try:
            elo_val = int(elo_text)
        except ValueError:
            continue
        if name and elo_val > 0:
            ratings[name] = elo_val
    return ratings


def _fetch_rendered_html() -> str | None:
    """Randare reală — SINGURUL mod verificat care poate obține datele
    (vezi docstring modul). Izolată explicit de `parse_elo_ratings_html()`
    de mai sus. `None` la orice eșec (Playwright indisponibil, navigare
    eșuată, grid-ul nu apare în 15s) — niciodată excepție propagată către
    apelant (Regula #8)."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        logger.error("[EloRatingsAdapter] Playwright indisponibil: %s", exc)
        return None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            try:
                page.goto(ELO_URL, wait_until="networkidle", timeout=30000)
                page.wait_for_selector(".slick-row", timeout=15000)
                return page.content()
            finally:
                browser.close()
    except Exception as exc:
        logger.error("[EloRatingsAdapter] randare eșuată: %s", exc)
        return None


class EloRatingsAdapter(SyncAdapter):
    provider_id = "eloratings"

    def fetch(self, params: dict) -> dict | None:
        """`params` neutilizat — o singură randare produce ratinguri
        pentru TOATE echipele naționale cunoscute deodată, nu există un
        parametru de filtrare (spre deosebire de football-data.org, care
        cere `comp_code` per ligă)."""
        html = _fetch_rendered_html()
        if html is None:
            return None
        return parse_elo_ratings_html(html)

    def normalize(self, raw_payload: dict | None) -> list[dict]:
        """Iterează TOATE echipele din dicționarul `{nume: elo}` —
        `fetch()` produce mai multe înregistrări, la fel ca
        `footballdata_form_adapter.normalize()` (R-Sync-3).

        `team_name` e trecut EXPLICIT prin `normalize_team_name()`
        (mappings.py — TEAM_ALIASES, ADR-039 Principiul 7) — numele de pe
        eloratings.net nu sunt garantat canonice."""
        if not raw_payload:
            return []
        from mappings import normalize_team_name

        records: list[dict] = []
        for raw_name, elo_value in raw_payload.items():
            if not raw_name:
                continue
            canonical_name = normalize_team_name(raw_name)
            records.append({"team_name": canonical_name, "elo_rating": elo_value})
        return records

    def validate(self, records: list[dict]) -> list[dict]:
        """Exclude, nu aruncă excepție — un rând fără `team_name` valid sau
        cu un ELO nepozitiv nu poate fi persistat (Regula #8: mai bine
        lipsă decât greșit)."""
        valid: list[dict] = []
        for r in records:
            if not r.get("team_name"):
                logger.warning("[EloRatingsAdapter] rând fără team_name, exclus: %r", r)
                continue
            elo = r.get("elo_rating")
            if not isinstance(elo, (int, float)) or elo <= 0:
                continue
            valid.append(r)
        return valid

    def persist(self, records: list[dict]) -> bool:
        from database.queries import upsert_national_team_elo

        ok = True
        for r in records:
            success = upsert_national_team_elo(r["team_name"], int(r["elo_rating"]))
            ok = ok and success
        return ok

    def coverage_check(self, context: dict) -> bool:
        """[DELIBERAT, nu omisiune] Fără concept de coverage — eloratings.net
        e un provider public, un singur tabel global, fără restricții de
        plan/ligă/sezon (spre deosebire de API-Football/football-data.org).
        Suprascrierea de mai jos (True, identică cu default-ul din
        SyncAdapter) există explicit, nu implicit, ca următorul
        dezvoltator să nu creadă că lipsește dintr-o scăpare — exact
        tiparul din `footballdata_form_adapter.coverage_check()`
        (R-Sync-3)."""
        return True
