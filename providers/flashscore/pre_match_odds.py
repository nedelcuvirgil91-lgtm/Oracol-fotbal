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

Scriere: `odds_fallback_flashscore` (ADR-043) — niciodată `odds_history`
(Frozen). Citirea de fallback în Predictor (regula ADR-043 §Decizie pct. 3)
rămâne, deliberat, un pas separat, ulterior — acest modul doar populează
tabela.

[ADAUGAT ADR-070, 2026-08-30] `persist_week_odds()` mai corectează, gatat de
`flashscore_kickoff_correction_config.is_enabled()` (implicit False), un
`match_history.kickoff_date` deja scris, dar greșit — cazul unei etape
anunțate cu ~3 săptămâni înainte, cu oră placeholder identică pentru toate
meciurile, orele reale confirmându-se abia cu câteva zile înainte de fluier.
NU e o cale nouă de scriere — refolosește RPC-ul canonic deja existent
(migrarea 048, `database.queries.correct_flashscore_kickoff_if_mismatched()`
→ `upsert_match()`), niciodată un meci cu `actual_result` deja scris. Vezi
ADR-070 pentru justificarea completă (de ce Flashscore rămâne singura sursă,
de ce TSDB a fost respins explicit).
================================================================================
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Any

from mappings import match_key

from .discovery import (
    FLASHSCORE_TRACKED_COMPETITIONS,
    _CHROMIUM_EXECUTABLE_PATH,
    _check_protection,
    _dismiss_gdpr_if_present,
    parse_match_links,
    polite_delay,
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


# [ADAUGAT — review, al 2-lea pas] Flashscore afișează ora de start FĂRĂ
# fus explicit extras (`_extract_kickoff_iso()`, normalizer.py — datetime
# naiv). Fusul real afișat (probabil CET, neverificat live) poate diverge
# de UTC-ul rulării automate (GitHub Actions) cu câteva ore — marja de mai
# jos absoarbe acel decalaj la marginea ferestrei, fără să pretindă că se
# cunoaște exact fusul (asta ar cere o verificare live separată, nu o
# presupunere). Lărgește fereastra simetric, niciodată nu o îngustează —
# nu poate exclude un meci care era deja valid.
_TIMEZONE_SAFETY_MARGIN = timedelta(hours=6)


def _within_window(kickoff_iso: str | None, days_ahead: int, now: datetime | None = None) -> bool:
    """Pură — True doar dacă `kickoff_iso` cade în [acum, acum+days_ahead
    zile], lărgit cu `_TIMEZONE_SAFETY_MARGIN` la ambele capete. Fără dată
    extrasă => False, niciodată aproximat ca fiind în fereastră (North
    Star #8)."""
    if not kickoff_iso:
        return False
    try:
        kickoff = datetime.fromisoformat(kickoff_iso)
    except ValueError:
        return False
    reference = now or datetime.now()
    window_start = reference - _TIMEZONE_SAFETY_MARGIN
    window_end = reference + timedelta(days=days_ahead) + _TIMEZONE_SAFETY_MARGIN
    return window_start <= kickoff <= window_end


def _kickoff_confirmed_beyond_window(kickoff_iso: str | None, days_ahead: int, now: datetime | None = None) -> bool:
    """Pură — True DOAR dacă `kickoff_iso` e parsabil ȘI confirmat dincolo
    de fereastră (+ aceeași marjă). Folosită exclusiv pentru oprire
    timpurie pe `/fixtures/` (hub cronologic, documentat în
    discovery.py — odată confirmat un meci prea departe, toate
    următoarele de pe hub sunt și ele mai departe). Niciodată True pentru
    dată lipsă/neparsabilă — acelea rămân ambigue, gestionate separat
    (sărite, nu opresc bucla — ar putea fi un glitch izolat de pagină,
    nu un semnal real că am trecut de fereastră)."""
    if not kickoff_iso:
        return False
    try:
        kickoff = datetime.fromisoformat(kickoff_iso)
    except ValueError:
        return False
    reference = now or datetime.now()
    return kickoff > reference + timedelta(days=days_ahead) + _TIMEZONE_SAFETY_MARGIN


def _discover_league_fixtures_with_odds(
    page, league: str, days_ahead: int, limit_per_league: int | None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """O singură ligă — hub `/fixtures/` + fetch ușor per meci. Extrasă
    separat (pattern identic `discovery._discover_for_hub()`) ca să poată
    fi testată direct, fără Playwright real, ȘI izolată per-ligă de
    apelant (`discover_week_fixtures_with_odds()`) — o ligă eșuată nu
    trebuie să oprească restul. `now` — injectabil DOAR pentru teste
    deterministe (vezi `_within_window`); implicit `None` => ceasul real,
    comportament de producție neschimbat."""
    country, competition = FLASHSCORE_TRACKED_COMPETITIONS[league]
    hub_url = f"https://www.flashscore.com/football/{country}/{competition}/fixtures/"
    resp = page.goto(hub_url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
    http_status = resp.status if resp else None
    _dismiss_gdpr_if_present(page)
    page.wait_for_timeout(POST_LOAD_WAIT_MS)
    _check_protection(page, http_status, tag=f"{league}-fixtures-hub")
    pairs = parse_match_links(page.content())
    if limit_per_league is not None:
        pairs = pairs[:limit_per_league]

    # [INSTRUMENTAT 2026-08-30] Contoare per liga. Motivul: rularea din
    # 2026-08-29 13:45 a fost TAIATA de `timeout-minutes: 45` la 45m21s, iar
    # log-ul Python tacea 43 de minute — ultima linie utila era "181 meciuri
    # din sursa primara" la 13:47:36, apoi nimic pana la taiere. Nu se putea
    # spune cate ligi apucase, cate meciuri descarcase, unde s-a dus timpul.
    # Aceeasi disciplina ca la `run_daily.step_durations_s`: se masoara
    # INAINTE de a decide intre marirea timeout-ului si optimizare — un
    # timeout marit orbeste exact semnalul de care avem nevoie.
    t_start = time.monotonic()
    descarcate = 0      # meciuri pentru care s-a facut fetch real (2 pagini)
    pastrate = 0        # au intrat in fereastra -> record produs
    sarite = 0          # descarcate, dar in afara ferestrei -> aruncate
    oprire_devreme = False

    records: list[dict[str, Any]] = []
    for base_url, mid in pairs:
        polite_delay()
        pages = _fetch_summary_and_odds(page, base_url, mid)
        descarcate += 1
        identity = normalize_upcoming_match(pages)
        kickoff = identity.get("kickoff_date")
        if _kickoff_confirmed_beyond_window(kickoff, days_ahead, now=now):
            # cronologic (hub /fixtures/) - restul sunt si mai departe,
            # oprire aici economiseste fetch-uri inutile (politete Flashscore).
            oprire_devreme = True
            break
        if not _within_window(kickoff, days_ahead, now=now):
            sarite += 1
            continue
        pastrate += 1
        records.append({
            "league": league,
            "home_team": identity.get("home_team"),
            "away_team": identity.get("away_team"),
            "kickoff_date": kickoff,
            "mid": identity.get("mid"),
            "odds": normalize_odds(pages),
        })

    durata = time.monotonic() - t_start
    # `sarite` e cifra de interes: fetch-uri platite (delay + 2 pagini
    # Playwright) si apoi ARUNCATE. Daca e mare, exista risipa reala de
    # optimizat — daca e ~0, durata e munca genuina si atunci raspunsul
    # corect e marirea timeout-ului, nu o "optimizare" inventata.
    logger.info(
        "[PreMatchOdds] %s: %d pe hub, %d descarcate, %d pastrate, %d sarite "
        "(in afara ferestrei), oprire_devreme=%s, %.1fs (%.1fs/meci)",
        league, len(pairs), descarcate, pastrate, sarite, oprire_devreme,
        durata, durata / descarcate if descarcate else 0.0,
    )
    return records


def discover_week_fixtures_with_odds(
    leagues: list[str] | None = None, days_ahead: int = 7, limit_per_league: int | None = None,
) -> list[dict[str, Any]]:
    """Punct de intrare — vizitează `/fixtures/` (meciuri viitoare) pentru
    fiecare ligă urmărită, extrage identitate + cote pentru meciurile din
    fereastra `days_ahead`. `FlashscoreProtectionDetected` (din
    discovery.py) sau orice altă eroare pe o ligă e logată și acea ligă e
    sărită — restul continuă, izolare per-ligă (identic principiul deja
    aplicat în `continuous_learning.py`: o ligă eșuată nu trebuie să
    piardă rezultatele deja strânse de la celelalte). Niciodată bypass la
    protecție — oprirea per-ligă rămâne imediată, doar nu se propagă la
    ligile încă neîncercate."""
    targets = leagues if leagues is not None else list(FLASHSCORE_TRACKED_COMPETITIONS.keys())
    unknown = [lg for lg in targets if lg not in FLASHSCORE_TRACKED_COMPETITIONS]
    if unknown:
        raise ValueError(
            f"discover_week_fixtures_with_odds(): liga(e) fara slug Flashscore verificat live -> {unknown} "
            "(vezi FLASHSCORE_TRACKED_COMPETITIONS, providers/flashscore/discovery.py)."
        )

    from playwright.sync_api import sync_playwright

    records: list[dict[str, Any]] = []
    # [INSTRUMENTAT 2026-08-30] Vezi motivul complet in
    # `_discover_league_fixtures_with_odds`. Aici se cronometreaza fiecare
    # liga si se tipareste un raport final ordonat descrescator — asa incat,
    # daca rularea e taiata din nou de timeout, log-ul sa arate exact PANA
    # UNDE a ajuns si CARE ligi consuma timpul, nu sa taca 43 de minute.
    t_total = time.monotonic()
    per_liga: list[tuple[str, float, int]] = []
    esuate: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=_CHROMIUM_EXECUTABLE_PATH)
        page = browser.new_page()
        try:
            for i, league in enumerate(targets):
                if i > 0:
                    polite_delay()
                # Progresul se logheaza INAINTE de a incepe liga: daca jobul e
                # omorat la mijloc, ultima linie spune la ce liga era, nu la
                # care terminase. Diferenta conteaza exact cand se taie.
                logger.info("[PreMatchOdds] ▶ liga %d/%d: %s", i + 1, len(targets), league)
                t_liga = time.monotonic()
                try:
                    noi = _discover_league_fixtures_with_odds(page, league, days_ahead, limit_per_league)
                    records.extend(noi)
                    per_liga.append((league, time.monotonic() - t_liga, len(noi)))
                except Exception as exc:
                    logger.warning("[PreMatchOdds] liga '%s' eșuată, sar la următoarea: %s", league, exc)
                    esuate.append(league)
                    per_liga.append((league, time.monotonic() - t_liga, 0))
                    continue
        finally:
            browser.close()

    total = time.monotonic() - t_total
    logger.info(
        "[PreMatchOdds] RAPORT: %d ligi in %.1f min, %d inregistrari, %d ligi esuate%s",
        len(per_liga), total / 60.0, len(records), len(esuate),
        f" ({', '.join(esuate)})" if esuate else "",
    )
    for liga, secunde, n in sorted(per_liga, key=lambda x: x[1], reverse=True):
        logger.info("[PreMatchOdds]     %6.1fs  %-26s %d înregistrări", secunde, liga, n)
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
    """Scrie cotele în `odds_fallback_flashscore` (ADR-043) — niciodată
    `odds_history`. Meciuri fără nicio cotă găsită (piață încă
    nepublicată) nu scriu nimic la cote — numărate, nu aproximate.

    [ADR-070] Rulează, gatat de `flashscore_kickoff_correction_config.
    is_enabled()`, corectarea de `kickoff_date` pentru FIECARE meci
    descoperit — indiferent dacă are cotă găsită sau nu. Corectarea
    identității (dată greșită) e independentă de disponibilitatea cotelor:
    un meci fără cotă publicată încă tot poate avea o dată placeholder,
    deja scrisă în `match_history`, de corectat."""
    from database.queries import correct_flashscore_kickoff_if_mismatched, upsert_odds_fallback_flashscore
    import flashscore_kickoff_correction_config

    kickoff_correction_enabled = flashscore_kickoff_correction_config.is_enabled()

    report = {
        "matches_seen": len(records), "odds_rows_written": 0,
        "odds_rows_failed": 0, "matches_without_odds": 0,
        "kickoff_corrections": 0,
    }
    for record in records:
        fixture_id = resolve_fixture_id(record, live_matches)

        if kickoff_correction_enabled:
            corrected = correct_flashscore_kickoff_if_mismatched(
                fixture_id=fixture_id,
                home_team=record.get("home_team", "") or "",
                away_team=record.get("away_team", "") or "",
                league=record.get("league", "") or "",
                scraped_kickoff_date=record.get("kickoff_date") or "",
            )
            if corrected:
                report["kickoff_corrections"] += 1

        odds_rows = record.get("odds") or []
        if not odds_rows:
            report["matches_without_odds"] += 1
            continue
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
