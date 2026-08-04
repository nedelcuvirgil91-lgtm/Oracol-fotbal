"""
================================================================================
FOOTBALL ORACLE — Flashscore Pre-Match Odds Sync (flux nou, separat)
================================================================================
Module: providers/flashscore/pre_match_odds.py

Flux DEDICAT, izolat de restul providerului Flashscore — nu modifică
`discovery.py`/`adapter.py`/`persistence.py` (rularea automată existentă,
`night_sync.yml`/`live_sync.yml`, care procesează exclusiv meciuri
FINALIZATE, rămâne complet neatinsă). Motivul separării: acele module
exclud deliberat `/fixtures/` (meciuri viitoare) la rulările automate —
"Flashscore nu are niciodată valoare pe un meci nejucat" (Owner matrix,
ADR-045) — corect pentru statistici/H2H/lineups, dar NU pentru cote, care
sunt confirmat disponibile pre-meci (verificat direct pe Flashscore live,
meciuri „PREVIEW", cote reale afișate). Acest modul cere DOAR tab-urile
"summary" (identitate) și "odds" (cote) — niciodată "stats"/"lineups"/"h2h"/
"standings"/"player_stats" pentru un meci nejucat, exact regula deja
respectată.

Acoperă fereastra "azi + următoarele `days_ahead` zile" (implicit 7 —
aceeași convenție deja folosită peste tot în proiect pentru "o săptămână",
`oracle_api.get_matches_for_week(days_ahead=7)` — nu un model nou de
"săptămână calendaristică luni-duminică", care ar exclude nejustificat
meciurile din restul săptămânii curente dacă rulează, de ex., miercuri).

Rezolvarea `fixture_id` cross-provider (blocajul explicit lăsat deschis de
ADR-043): dacă meciul descoperit de Flashscore se potrivește (prin
`mappings.match_key()`, aceeași cheie de deduplicare deja folosită în toată
cascada `oracle_api.get_matches_for_week()`) cu un meci deja găsit de
sursa primară, se refolosește `fixture_id`-ul EI — `odds_history` și
`odds_fallback_flashscore` vorbesc despre același meci sub aceeași cheie.
Dacă Flashscore a găsit un meci pe care nicio altă sursă nu l-a găsit încă
(cazul real, documentat, al calificărilor europene), se minte un
`fixture_id` propriu, cu EXACT același prefix deja folosit în
`match_history` pentru meciuri descoperite întâi de Flashscore
(`normalizer.normalize_match_statistics()`), niciodată un format nou.

Scriere: DOAR `odds_fallback_flashscore` (ADR-043) — niciodată
`odds_history` (Frozen). Citirea de fallback în Predictor (regula ADR-043
§Decizie pct. 3) rămâne, deliberat, un pas separat, ulterior — acest modul
doar populează tabela.
================================================================================
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Any

from mappings import match_key

from .discovery import (
    FLASHSCORE_MIN_DELAY_SECONDS,
    FLASHSCORE_TRACKED_COMPETITIONS,
    _CHROMIUM_EXECUTABLE_PATH,
    _check_protection,
    _dismiss_gdpr_if_present,
    parse_match_links,
)
from .normalizer import normalize_odds, normalize_upcoming_match

logger = logging.getLogger("FootballOracle.Flashscore.PreMatchOdds")

NAV_TIMEOUT_MS = 30000
POST_LOAD_WAIT_MS = 3500

# DOAR cele 2 tab-uri necesare unui meci nejucat — subset deliberat al
# celor 7 din adapter.py (_MATCH_TAB_SUFFIXES), niciodată extins aici.
_LIGHT_TAB_SUFFIXES: dict[str, str] = {"summary": "", "odds": "odds/"}


def _fetch_summary_and_odds(page, match_base_url: str, mid: str) -> dict[str, str]:
    """Fetch UȘOR — 2 navigări, nu 7. Reutilizează exact disciplina de
    protecție/GDPR/pacing din discovery.py (importată, nu duplicată)."""
    pages: dict[str, str] = {}
    for tab_name, suffix in _LIGHT_TAB_SUFFIXES.items():
        url = f"{match_base_url}/{suffix}?mid={mid}"
        resp = page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        http_status = resp.status if resp else None
        if tab_name == "summary":
            _dismiss_gdpr_if_present(page)
        page.wait_for_timeout(POST_LOAD_WAIT_MS)
        _check_protection(page, http_status, tag=f"pre-match-odds-{tab_name}")
        pages[tab_name] = page.content()
    return pages


def _within_window(kickoff_iso: str | None, days_ahead: int, now: datetime | None = None) -> bool:
    """Pură — True doar dacă `kickoff_iso` cade în [acum, acum+days_ahead
    zile]. Fără dată extrasă => False, niciodată aproximat ca fiind în
    fereastră (North Star #8)."""
    if not kickoff_iso:
        return False
    try:
        kickoff = datetime.fromisoformat(kickoff_iso)
    except ValueError:
        return False
    reference = now or datetime.now()
    return reference <= kickoff <= reference + timedelta(days=days_ahead)


def discover_week_fixtures_with_odds(
    leagues: list[str] | None = None, days_ahead: int = 7, limit_per_league: int | None = None,
) -> list[dict[str, Any]]:
    """Punct de intrare — vizitează `/fixtures/` (meciuri viitoare) pentru
    fiecare ligă urmărită, extrage identitate + cote pentru meciurile din
    fereastra `days_ahead`. Ridică `FlashscoreProtectionDetected` (din
    `discovery.py`) și se oprește imediat la orice semn de protecție —
    identic restul providerului, niciodată bypass."""
    targets = leagues if leagues is not None else list(FLASHSCORE_TRACKED_COMPETITIONS.keys())
    unknown = [lg for lg in targets if lg not in FLASHSCORE_TRACKED_COMPETITIONS]
    if unknown:
        raise ValueError(
            f"discover_week_fixtures_with_odds(): liga(e) fara slug Flashscore verificat live -> {unknown} "
            "(vezi FLASHSCORE_TRACKED_COMPETITIONS, providers/flashscore/discovery.py)."
        )

    from playwright.sync_api import sync_playwright

    records: list[dict[str, Any]] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=_CHROMIUM_EXECUTABLE_PATH)
        page = browser.new_page()
        try:
            for i, league in enumerate(targets):
                country, competition = FLASHSCORE_TRACKED_COMPETITIONS[league]
                hub_url = f"https://www.flashscore.com/football/{country}/{competition}/fixtures/"
                if i > 0:
                    time.sleep(FLASHSCORE_MIN_DELAY_SECONDS)
                resp = page.goto(hub_url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
                http_status = resp.status if resp else None
                _dismiss_gdpr_if_present(page)
                page.wait_for_timeout(POST_LOAD_WAIT_MS)
                _check_protection(page, http_status, tag=f"{league}-fixtures-hub")
                pairs = parse_match_links(page.content())
                if limit_per_league is not None:
                    pairs = pairs[:limit_per_league]
                for base_url, mid in pairs:
                    time.sleep(FLASHSCORE_MIN_DELAY_SECONDS)
                    pages = _fetch_summary_and_odds(page, base_url, mid)
                    identity = normalize_upcoming_match(pages)
                    if not identity.get("kickoff_date"):
                        continue
                    if not _within_window(identity["kickoff_date"], days_ahead):
                        continue
                    records.append({
                        "league": league,
                        "home_team": identity.get("home_team"),
                        "away_team": identity.get("away_team"),
                        "kickoff_date": identity.get("kickoff_date"),
                        "mid": identity.get("mid"),
                        "odds": normalize_odds(pages),
                    })
        finally:
            browser.close()
    return records


def resolve_fixture_id(record: dict[str, Any], live_matches: list[dict[str, Any]] | None) -> str:
    """Pură. Vezi docstring modul pentru justificare completă — potrivire
    prin `match_key()` cu sursa primară dacă există, altfel `fixture_id`
    propriu, prefix identic celui deja folosit în `match_history`."""
    key = match_key(record.get("home_team", ""), record.get("away_team", ""), record.get("kickoff_date", ""))
    for m in (live_matches or []):
        m_key = match_key(m.get("home_team", ""), m.get("away_team", ""), m.get("kickoff_date", ""))
        if m_key == key and m.get("fixture_id"):
            return m["fixture_id"]
    return f"flashscore_{record.get('mid')}"


def persist_week_odds(
    records: list[dict[str, Any]], live_matches: list[dict[str, Any]] | None = None,
) -> dict[str, int]:
    """Scrie DOAR `odds_fallback_flashscore` (ADR-043) — niciodată
    `odds_history`. Meciuri fără nicio cotă găsită (piață încă
    nepublicată) nu scriu nimic — numărate, nu aproximate."""
    from database.queries import upsert_odds_fallback_flashscore

    report = {
        "matches_seen": len(records), "odds_rows_written": 0,
        "odds_rows_failed": 0, "matches_without_odds": 0,
    }
    for record in records:
        odds_rows = record.get("odds") or []
        if not odds_rows:
            report["matches_without_odds"] += 1
            continue
        fixture_id = resolve_fixture_id(record, live_matches)
        for row in odds_rows:
            ok = upsert_odds_fallback_flashscore(
                fixture_id=fixture_id, bookmaker=row["bookmaker"],
                home=row.get("home"), draw=row.get("draw"), away=row.get("away"),
            )
            report["odds_rows_written" if ok else "odds_rows_failed"] += 1
    return report


def sync_week_odds_from_flashscore(
    leagues: list[str] | None = None, days_ahead: int = 7,
    limit_per_league: int | None = None, live_matches: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Orchestrare completă (discover → persist), simetrică cu
    `discovery.run_foundation_data_layer_for_discovered_matches()`, dar
    pentru fluxul separat de mai sus. `live_matches`: rezultatul deja
    obținut al `oracle_api.get_matches_for_week()` în aceeași rulare —
    opțional, folosit doar pentru rezolvarea `fixture_id` (§`resolve_
    fixture_id`); fără el, fiecare meci capătă un `fixture_id` propriu."""
    records = discover_week_fixtures_with_odds(leagues, days_ahead, limit_per_league)
    report = persist_week_odds(records, live_matches)
    report["leagues"] = leagues or list(FLASHSCORE_TRACKED_COMPETITIONS.keys())
    report["days_ahead"] = days_ahead
    return report
