"""
================================================================================
FOOTBALL ORACLE — Flashscore Match Discovery (Foundation Data Layer, ADR-044)
================================================================================
Module: providers/flashscore/discovery.py

M1 — transformă "competiție urmărită" în listă de meciuri reale
(`match_base_url` + `mid`), pe baza structurii reale a paginii de
rezultate Flashscore, verificată live (nu presupusă). Structura de mai
jos a fost confirmată direct, printr-o navigare Playwright reală, fără
niciun semn de protecție întâlnit (evidența brută rămâne salvată în
`docs/06_UDAL/poc_evidence/flashscore_10matches/`:
`superliga_results_hub_raw.html`, `ucl_results_hub_raw.html`) — același
tipar de HTML e citit aici, niciun selector nou ghicit.

Structură confirmată (per rând de meci, `.event__match`):
- `a.eventRowLink[href*="/match/football/"]` → URL complet, cu `?mid=...`.
- Rândurile de pe `/results/` sunt DOAR meciuri încheiate — Flashscore
  separă `/results/` de `/fixtures/` la nivel de hub, deci discovery NU
  are nevoie să parseze un status per rând, sursa hub-ului îl garantează
  implicit (fallback pe `/fixtures/` există doar dacă `/results/` nu
  întoarce niciun link, identic tiparului deja verificat în POC-ul
  `scripts/_poc_flashscore_10matches_temp.py`).
- Data/ora afișată per rând (ex. "27.07. 18:30") NU are an — NU se
  folosește aici. Data completă (cu an), autoritativă, se extrage deja
  de `normalizer._extract_kickoff_iso()` direct de pe pagina meciului
  (`.duelParticipant__startTime`, are anul) — discovery nu duplică acea
  responsabilitate.
- "Show more matches" (paginare) există ca mecanism în aplicație
  (confirmat în bundle-ul JS — cheia de traducere
  `TRANS_SHOW_MORE_MATCHES`), dar NU a apărut ca buton vizibil în
  randarea capturată (16 meciuri unice SuperLiga / 28 unice UCL, fără
  element `event__more` în DOM). Paginarea dincolo de randarea inițială
  rămâne NEIMPLEMENTATĂ — documentat explicit, nu ghicită.

FLASHSCORE_TRACKED_COMPETITIONS conține DOAR competiții cu slug
Flashscore verificat — DOUĂ nivele de verificare, distincte, marcate
explicit mai jos, niciodată amestecate:

- **Nivel A (Romania SuperLiga, UEFA Champions League)** — verificare
  live COMPLETĂ: navigare Playwright reală, HTML brut salvat ca dovadă
  (`docs/06_UDAL/poc_evidence/flashscore_10matches/`), structura DOM
  (`.event__match`, `a.eventRowLink`) confirmată direct pe pagină.
- **Nivel B (Premier League, La Liga, Serie A, Bundesliga, Ligue 1,
  Europa League, MLS — adăugate Faza 2, extindere Discovery; Primeira
  Liga, Eredivisie, Super Lig, HNL — adăugate 2026-08-04; Conference
  League — adăugată 2026-08-05, cerere explicită proprietar produs)** —
  verificare prin căutare web (titlul REAL, generat de Flashscore, indexat
  de motorul de căutare, confirmă că URL-ul exact există și corespunde
  ligii — nu un slug ghicit din convenție), NU prin navigare Playwright
  live (sandbox-ul de dezvoltare nu are acces direct la flashscore.com).
  `parse_match_links()` (parserul, generic, PROBAT deja pe 2 hub-uri
  reale diferite) rămâne neschimbat — riscul rezidual e STRICT la
  nivelul slug-ului URL, nu al parserului. Recomandat: o rulare
  `--dry-run` reală per ligă nouă înainte de prima rulare live completă,
  ca ultimă confirmare (owner-ul produsului are acces live, sesiunea de
  dezvoltare nu).
- **World Cup 2026 — EXCLUS deliberat**, NU adăugat: căutarea a întors
  MULTIPLE URL-uri Flashscore reale, conflictuale, pentru "World Cup
  2026" (`world/world-championship`, `world/world-cup-2026`,
  `world/world-cup`, `south-america/world-cup` — acesta din urmă pare
  calificări, o competiție diferită) — nicio confirmare fără ambiguitate,
  deci niciun slug ales (Regula #8 — nicio stare necunoscută nu se
  aproximează).

Pacing: `FLASHSCORE_MIN_DELAY_SECONDS` — unica disciplină de
politețe/rată implementată azi (`politeness_policy_ref` din
`scraper_registry.py` rămâne altfel un string neresolvat, fără mecanism).
================================================================================
"""
from __future__ import annotations

import logging
import os
import random
import re
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("FootballOracle.Flashscore.Discovery")

NAV_TIMEOUT_MS = 30000
POST_LOAD_WAIT_MS = 3500

# Vezi adapter.py - acelasi mecanism opțional de executable_path explicit.
_CHROMIUM_EXECUTABLE_PATH = os.environ.get("FLASHSCORE_CHROMIUM_EXECUTABLE") or None

# Disciplina de politete/rata intre doua navigari succesive (hub->hub, sau
# meci->meci in orchestrare). [EXTINS 2026-08-05, cerere explicita
# proprietar produs — "sa nu il blocheze"] Un delay FIX (2.0s constant) e
# exact tiparul pe care detectia anti-bot il cauta — research (BrowserStack
# "Web Scraping with Playwright", ScrapingAnt "Avoid Getting Blocked", 2026):
# 1-3s cu jitter (randomizare) e considerat trafic uman, un interval identic
# repetat de fiecare data nu e. FLASHSCORE_MIN/MAX_DELAY_SECONDS definesc
# plaja, polite_delay() alege uniform in ea de fiecare data — nu schimba
# comportamentul la protectie detectata (FlashscoreProtectionDetected tot
# opreste imediat, niciun retry-prin-blocaj, niciodata bypass/proxy/stealth).
FLASHSCORE_MIN_DELAY_SECONDS = 2.0
FLASHSCORE_MAX_DELAY_SECONDS = 4.0


def polite_delay() -> None:
    """Delay cu jitter intre doua navigari succesive — vezi comentariul
    de la FLASHSCORE_MIN/MAX_DELAY_SECONDS pentru motiv. Sursa unica,
    reutilizata si de pre_match_odds.py."""
    time.sleep(random.uniform(FLASHSCORE_MIN_DELAY_SECONDS, FLASHSCORE_MAX_DELAY_SECONDS))


_PROTECTION_MARKERS = (
    "checking your browser", "cf-browser-verification", "attention required",
    "captcha-delivery", "access denied", "ray id",
    "sorry, you have been blocked", "just a moment...",
    "verify you are human", "unusual traffic from your computer",
    "please verify you are a human", "detected unusual activity",
)

# [ADAUGAT Pasul 1 Master Repair Plan, rafinat dupa feedback] Plafon pentru
# rularile AUTOMATE (night_sync.yml/live_sync.yml) - se aplica DOAR hub-ului
# `/results/` (meciuri deja TERMINATE, singurele cu valoare reala pentru
# Flashscore - vezi ADR-045, Owner matrix: Results/Statistics/Standings/H2H/
# Player Ratings/Events cer toate un meci deja jucat). Nu mai e folosit
# pentru `/fixtures/` (meciuri VIITOARE) - vezi `include_future_fixtures`
# mai jos, care elimina complet acea cale la rularile automate, nu doar o
# plafoneaza.
#
# Configurabil, NU hardcodat - citit din `model_config.data` (Supabase,
# rand unic id=1, acelasi tipar deja folosit de `blend_engine_display_enabled`/
# `flashscore_shadow_logging_enabled`/etc.), cheia
# `FLASHSCORE_LIMIT_PER_LEAGUE_CONFIG_KEY`. Valoarea de mai jos e DOAR
# fallback-ul folosit cand cheia lipseste din config (implicit azi, nicio
# scriere facuta) - vezi `get_limit_per_league_automated()`.
#
# Justificare pentru valoarea de fallback (20): dimensiunea reala a
# hub-ului `/results/`, verificata live pe doua competitii diferite (POC
# 10-matches, docstring modul, liniile 16-34) - 16 meciuri unice SuperLiga,
# 28 unice UCL, fara paginare dincolo de randarea initiala. 20 acopera
# confortabil o runda/fereastra recenta reala per competitie, fara sa
# proceseze un arhiva istorica intreaga la fiecare rulare (Delta Sync face
# reprocesarea sigura, dar nu gratuita - fiecare meci inca cere o rulare
# de pagina). Rularile manuale (CLI, `--limit-per-league`) raman complet
# neafectate de acest plafon si de config-ul Supabase - doar apelurile
# implicite din run_night.py/run_live.py il folosesc.
FLASHSCORE_LIMIT_PER_LEAGUE_CONFIG_KEY = "flashscore_limit_per_league_automated"
DEFAULT_LIMIT_PER_LEAGUE_AUTOMATED = 20


def get_limit_per_league_automated() -> int:
    """Plafonul REAL folosit de rularile automate — citit din
    `model_config.data` (Supabase), cu fallback la
    `DEFAULT_LIMIT_PER_LEAGUE_AUTOMATED` daca cheia lipseste sau clientul
    Supabase nu e disponibil (degradare identica restului proiectului —
    niciodata excepție, niciodata blocaj). Configurabil fără deploy de
    cod: `UPDATE model_config SET data = jsonb_set(data,
    '{flashscore_limit_per_league_automated}', '30') WHERE id = 1;` (SQL
    exemplu — orice scriere reală trece prin disciplina supabase-safety,
    SQL arătat explicit înainte de rulare)."""
    try:
        from supabase_client import load_config
        cfg = load_config(default={})
        value = cfg.get(FLASHSCORE_LIMIT_PER_LEAGUE_CONFIG_KEY)
        if isinstance(value, int) and value > 0:
            return value
    except Exception as exc:
        logger.warning("[Discovery] get_limit_per_league_automated failed, fallback la implicit: %s", exc)
    return DEFAULT_LIMIT_PER_LEAGUE_AUTOMATED

# [ADR-044] Doar competitii cu slug Flashscore VERIFICAT LIVE (nu ghicit) -
# vezi docstring modul. (country, competition) - exact segmentele folosite
# de target_url_template din scraper_registry.py.
FLASHSCORE_TRACKED_COMPETITIONS: dict[str, tuple[str, str]] = {
    # Nivel A — verificare live completă (Playwright + fixture HTML salvat).
    "Romania SuperLiga": ("romania", "superliga"),
    # [FIX — audit Canonical Integration, Faza 2] cheia era "UEFA Champions
    # League" - listată explicit ca ALIAS (nu formă canonică) în
    # mappings.LEAGUE_ALIASES["Champions League"]. Redenumit la forma
    # canonică exactă, altfel meciurile UCL colectate de Flashscore nu ar
    # fi găsite NICIODATĂ de Oracle Engine (care interoghează cu
    # "Champions League", din LEAGUE_WEIGHTS) - persist_match_foundation_
    # data() aplică acum oricum normalize_league_name() ca plasă de
    # siguranță suplimentară, dar cheia de aici trebuie să fie deja corectă.
    "Champions League": ("europe", "champions-league"),
    # Nivel B — verificare prin căutare web (Faza 2, vezi docstring modul).
    "Premier League": ("england", "premier-league"),
    "La Liga": ("spain", "laliga"),
    "Serie A": ("italy", "serie-a"),
    "Bundesliga": ("germany", "bundesliga"),
    "Ligue 1": ("france", "ligue-1"),
    "Europa League": ("europe", "europa-league"),
    "MLS": ("usa", "mls"),
    # [ADAUGAT 2026-08-04] Nivel B — verificare prin căutare web (mai multe
    # rezultate independente per ligă, titlu Flashscore real, URL exact
    # confirmat). Portugalia: slug curent "liga-portugal" (rebranding
    # sponsorizat 2026/2027, NU "primeira-liga" — acela e un URL vechi/
    # arhivat, riscă redirect sau pagină stale).
    "Primeira Liga": ("portugal", "liga-portugal"),
    "Eredivisie": ("netherlands", "eredivisie"),
    "Super Lig": ("turkey", "super-lig"),
    "HNL": ("croatia", "hnl"),
    # [ADAUGAT 2026-08-05] Nivel B — verificare prin căutare web (WebSearch,
    # rezultate multiple independente, titlu Flashscore real: "Conference
    # League 2026/2027 live scores, results, Football Europe", "Conference
    # League Fixtures - Football/Europe" — URL exact confirmat, nu ghicit
    # din convenție). Cerere explicită proprietar produs — Conference League
    # lipsea complet din discovery Flashscore, deși e deja tracked în
    # mappings.LEAGUE_PROVIDERS (espn/tsdb/soccerfootballinfo).
    "Conference League": ("europe", "conference-league"),
    # [ADAUGAT 2026-08-10] Nivel B — verificare prin căutare web (WebSearch,
    # rezultate multiple independente per ligă, titlu Flashscore real, URL
    # exact confirmat, nu ghicit din convenție). Cerere explicită proprietar
    # produs — extindere etapizată (3 din 6 propuse, cele cu sezonul deja
    # început): "Jupiler Pro League 2026/2027 live scores... Football
    # Belgium", "Ekstraklasa 2026/2027 live scores... Football Poland",
    # "Scottish Premiership live scores... Football Scotland" (Hearts,
    # Rangers, Celtic confirmate în conținut).
    "Jupiler Pro League":   ("belgium", "jupiler-pro-league"),
    "Ekstraklasa":          ("poland", "ekstraklasa"),
    "Scottish Premiership": ("scotland", "premiership"),
}


class FlashscoreProtectionDetected(Exception):
    """Identic cu adapter.py - oprire imediata la orice semn de protectie,
    niciodata bypass/stealth/proxy."""


@dataclass(frozen=True)
class DiscoveredMatch:
    league: str
    match_base_url: str
    mid: str
    source: str  # "results" sau "fixtures"
    # [ADR-066 P2b] Sezonul competitiei, citit din ACELASI HTML de hub din care
    # se extrag si linkurile — zero cereri suplimentare. Implicit None, deci
    # niciun apelant existent nu se rupe. `season_start`/`season_end` NU sunt
    # scrise nicaieri: servesc exclusiv ca garda in `season_for_kickoff()`.
    season: str | None = None
    season_start: str | None = None
    season_end: str | None = None


def _dismiss_gdpr_if_present(page) -> None:
    for selector in (
        "#onetrust-accept-btn-handler",
        "button:has-text('Accept & continue')",
        "button:has-text('Accept all')",
        "button:has-text('I Accept')",
    ):
        try:
            btn = page.locator(selector).first
            if btn.is_visible(timeout=1500):
                btn.click(timeout=2000)
                page.wait_for_timeout(500)
                return
        except Exception:
            continue


def _check_protection(page, http_status: int | None, tag: str) -> None:
    if http_status is not None and http_status in (403, 429, 503):
        raise FlashscoreProtectionDetected(f"{tag}: HTTP {http_status}")
    lower = page.content().lower()
    hit = next((m for m in _PROTECTION_MARKERS if m in lower), None)
    if hit:
        raise FlashscoreProtectionDetected(f"{tag}: marker gasit -> '{hit}'")


def parse_match_links(html: str) -> list[tuple[str, str]]:
    """Functie PURA - din HTML brut al hub-ului -> [(match_base_url, mid),
    ...], ordinea paginii, fara duplicate. `match_base_url` fara slash
    final, fara query string (contract identic cu parametrii cerut de
    `FlashscoreAdapter.fetch()`). Testata direct contra evidentei reale
    capturate live (`docs/06_UDAL/poc_evidence/flashscore_10matches/`),
    nu contra unui fixture inventat."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    seen: dict[str, str] = {}
    for a in soup.select("a[href*='/match/football/']"):
        href = a.get("href")
        if not href:
            continue
        full = href if href.startswith("http") else f"https://www.flashscore.com{href}"
        base, _, query = full.partition("?")
        base = base.rstrip("/")
        mid = None
        for part in query.split("&"):
            if part.startswith("mid="):
                mid = part[len("mid="):]
                break
        if not mid or base in seen:
            continue
        seen[base] = mid
    return list(seen.items())


def _discover_for_hub(
    page, hub_url: str, league: str, limit: int | None,
    include_future_fixtures: bool = True, future_fixtures_only: bool = False,
) -> list[DiscoveredMatch]:
    """`hub_url` fara `/results/`/`/fixtures/` - ambele incercate,
    `/results/` intai (identic POC-ului 10-matches, deja verificat live);
    `/fixtures/` folosit doar daca `/results/` nu intoarce niciun link.

    `include_future_fixtures` [ADAUGAT Pasul 1 Master Repair Plan, rafinat
    dupa feedback] — implicit True (comportament NESCHIMBAT pentru orice
    apelant existent/CLI manual). Cand False, `/fixtures/` (meciuri
    VIITOARE) nu mai e incercat deloc — daca `/results/` nu intoarce
    niciun link (competitie in pauza competitionala, confirmat live pentru
    Premier League/La Liga/Serie A/Bundesliga/Ligue 1 in Coverage Audit
    2026-08-03), liga e sarita curat pentru acea rulare, fara sa persiste
    fixture-uri fara nicio statistica posibila inca. Solutia reala pentru
    "Discovery Flashscore nu mai cauta meciuri deja descoperite de Sync
    Layer" (ADR-045): Flashscore nu are NICIODATA valoare pe un meci
    nejucat (Owner matrix — Results/Statistics/Standings/H2H/Player
    Ratings/Events cer toate un meci deja jucat), deci rularile automate
    nu mai incearca deloc acea treaba, indiferent daca Sync Layer a
    descoperit deja fixture-ul sau nu — nu mai era nevoie de o
    cross-referentiere fragila (slug URL -> nume canonic) cu
    `scheduled_fixtures`, care ar fi cerut fie o schimbare de schema, fie
    o potrivire de nume nesigura.

    `future_fixtures_only` [ADAUGAT 2026-08-05, fix descoperit in timpul
    implementarii flashscore_weekly_fixtures.yml] — cand True, `/results/`
    NU mai e incercat deloc, DOAR `/fixtures/`. Motiv: pentru orice liga
    activa, `/results/` are aproape mereu meciuri (night_sync.yml/
    live_sync.yml le acopera deja la cadenta lor) — cu `include_future_
    fixtures=True` obisnuit, `/fixtures/` e doar FALLBACK, deci NU e
    incercat niciodata cand `/results/` are continut, exact opusul a ceea
    ce are nevoie un workflow dedicat descoperirii de meciuri viitoare.
    `future_fixtures_only=True` ignora complet `include_future_fixtures`
    (cere `/fixtures/` necondiționat) — folosit DOAR de flashscore_weekly_
    fixtures.yml, restul apelantilor (CLI manual, flashscore_foundation_
    data_layer.yml) raman pe implicit False, comportament neschimbat."""
    if future_fixtures_only:
        sources = ("fixtures",)
    elif include_future_fixtures:
        sources = ("results", "fixtures")
    else:
        sources = ("results",)
    for source in sources:
        url = f"{hub_url.rstrip('/')}/{source}/"
        resp = page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        http_status = resp.status if resp else None
        _dismiss_gdpr_if_present(page)
        page.wait_for_timeout(POST_LOAD_WAIT_MS)
        _check_protection(page, http_status, tag=f"{league}-{source}-hub")
        # [ADR-066 P2b] UN SINGUR `page.content()` pentru ambele extrageri —
        # linkurile si sezonul vin din exact acelasi HTML, deci sezonul nu poate
        # descrie alta pagina decat cea din care s-au luat meciurile.
        html = page.content()
        pairs = parse_match_links(html)
        if pairs:
            if limit is not None:
                pairs = pairs[:limit]
            sezon = parse_season_from_hub(html) or {}
            if not sezon:
                logger.warning(
                    "[Flashscore.Discovery] sezon negasit pe hub-ul %s (%s) — "
                    "meciurile raman fara sezon (Regula #8: necunoscut ramane "
                    "necunoscut, nu se deduce din calendar).", league, source,
                )
            return [
                DiscoveredMatch(
                    league=league, match_base_url=base, mid=mid, source=source,
                    season=sezon.get("season"),
                    season_start=sezon.get("start_date"),
                    season_end=sezon.get("end_date"),
                )
                for base, mid in pairs
            ]
        polite_delay()
    return []


def discover_matches(
    leagues: list[str] | None = None, limit_per_league: int | None = None,
    include_future_fixtures: bool = True, future_fixtures_only: bool = False,
    persist_calendar: bool = True,
) -> list[DiscoveredMatch]:
    """Punct de intrare M1 - o singura sesiune Playwright, un singur
    browser, pacing explicit intre hub-uri succesive
    (`FLASHSCORE_MIN_DELAY_SECONDS`). `leagues=None` -> toate din
    `FLASHSCORE_TRACKED_COMPETITIONS`. Ridica `FlashscoreProtectionDetected`
    si se opreste imediat la orice semn de protectie, nu incearca sa
    ocoleasca - identic restul acestui provider.

    `include_future_fixtures`/`future_fixtures_only` — vezi docstring
    `_discover_for_hub()`. Implicit True/False (comportament CLI/manual
    neschimbat)."""
    targets = leagues if leagues is not None else list(FLASHSCORE_TRACKED_COMPETITIONS.keys())
    unknown = [lg for lg in targets if lg not in FLASHSCORE_TRACKED_COMPETITIONS]
    if unknown:
        raise ValueError(
            f"discover_matches(): liga(e) fara slug Flashscore verificat live -> {unknown} "
            "(vezi FLASHSCORE_TRACKED_COMPETITIONS, providers/flashscore/discovery.py)."
        )

    from playwright.sync_api import sync_playwright

    results: list[DiscoveredMatch] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=_CHROMIUM_EXECUTABLE_PATH)
        page = browser.new_page()
        try:
            for i, league in enumerate(targets):
                country, competition = FLASHSCORE_TRACKED_COMPETITIONS[league]
                hub_url = f"https://www.flashscore.com/football/{country}/{competition}"
                if i > 0:
                    polite_delay()
                results.extend(_discover_for_hub(page, hub_url, league, limit_per_league,
                                                  include_future_fixtures, future_fixtures_only))
        finally:
            browser.close()
    rezultate = dedupe_by_mid(results)
    # [ADR-067] Calendarul se scrie AICI, la nivel de orchestrare, nu in
    # `_discover_for_hub()`: acea functie ramane fara I/O catre Supabase in
    # mijlocul buclei Playwright, iar scrierea se face o singura data, dupa ce
    # browserul e deja inchis.
    #
    # `persist_calendar=False` exista pentru dry-run. Fara el, `run(dry_run=
    # True)` ar fi scris in `competition_season` si ar fi tiparit apoi „Dry
    # run — nicio scriere" — o afirmatie FALSA in propriul output. Un dry-run
    # care scrie ceva nu mai e dry-run; defectul a fost introdus si prins in
    # aceeasi zi, inainte de prima rulare.
    if persist_calendar:
        persist_season_calendars(rezultate)
    return rezultate


_SEASON_LABEL_RE = re.compile(r"^\s*(20\d{2})\s*(?:/\s*(20\d{2}))?\s*$")
_SEASON_DAY_RE = re.compile(r"^\s*(\d{2})\.(\d{2})\.\s*$")


def parse_season_from_hub(html: str) -> dict | None:
    """Sezonul competiției din pagina de hub — FUNCȚIE PURĂ, fără I/O.

    [ADR-066] Datele erau pe pagină de la bun început. `CLAUDE.md` (2026-08-03)
    concluziona că sezonul e „genuin necolectat de pe pagină, ar cere
    investigație live nouă" — greșit: dovada era deja în repo, în HTML-ul de
    hub salvat ca evidență POC, adică exact pagina pe care Discovery o descarcă
    la fiecare rulare. Costul de rețea al extragerii e ZERO.

    Trei elemente, verificate pe două competiții cu calendare diferite:

        div.heading__info                       -> "2026/2027"  (sau "2026")
        .wcl-progressBarContainer_ .wcl-start_  -> "17.07."
        .wcl-progressBarContainer_ .wcl-end_    -> "30.05."

    Anul se derivă DETERMINIST din etichetă, niciodată din calendar: pentru
    „2026/2027", luna de start (07) o plasează în 2026, cea de sfârșit (05) în
    2027. Pentru un sezon într-un singur an („2026", ex. MLS) ambele cad în
    același an. Dacă eticheta lipsește sau nu se potrivește, se întoarce None —
    `season_cleanup.py` interzice deja aproximarea calendaristică, iar regula
    nu se slăbește aici (Regula #8).

    Ancorare pe PREFIXUL clasei (`wcl-start_`), nu pe numele complet: sufixul
    e un hash care se schimbă la orice redeploy Flashscore. Absența e logată,
    nu ghicită — aceeași lecție ca la inversarea de teren din 2026-08-23.

    Întoarce `{"season", "start_date", "end_date"}` sau None."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html or "", "html.parser")

    eticheta_el = soup.select_one("div.heading__info")
    if eticheta_el is None:
        return None
    m = _SEASON_LABEL_RE.match(eticheta_el.get_text(strip=True))
    if not m:
        return None
    an_start = int(m.group(1))
    an_final = int(m.group(2)) if m.group(2) else an_start
    eticheta = f"{an_start}-{an_final}"  # format canonic YYYY-YYYY (ADR-066 §4)

    def _zi(prefix: str) -> tuple[int, int] | None:
        for el in soup.find_all("span"):
            clase = el.get("class") or []
            if not any(c.startswith(prefix) for c in clase):
                continue
            z = _SEASON_DAY_RE.match(el.get_text(strip=True))
            if z:
                return int(z.group(1)), int(z.group(2))
        return None

    start = _zi("wcl-start_")
    final = _zi("wcl-end_")
    if start is None or final is None:
        logger.warning(
            "[Flashscore.Discovery] bara de sezon absentă sau cu altă structură "
            "(prefixe wcl-start_/wcl-end_) — eticheta %r găsită, dar fără date. "
            "Sezonul rămâne fără interval.", eticheta,
        )
        return {"season": eticheta, "start_date": None, "end_date": None}

    # Anul fiecărei margini vine din etichetă, nu din calendar. Pentru un sezon
    # care traversează anul, marginea de start ia primul an DOAR dacă luna ei e
    # >= luna de sfârșit; altfel ambele cad în al doilea an (sezon scurt, de
    # primăvară). Pentru un sezon într-un singur an, ambele iau acel an.
    zi_s, luna_s = start
    zi_f, luna_f = final
    if an_final == an_start:
        an_pentru_start, an_pentru_final = an_start, an_start
    elif luna_s > luna_f:
        an_pentru_start, an_pentru_final = an_start, an_final
    else:
        an_pentru_start, an_pentru_final = an_final, an_final

    return {
        "season": eticheta,
        "start_date": f"{an_pentru_start:04d}-{luna_s:02d}-{zi_s:02d}",
        "end_date": f"{an_pentru_final:04d}-{luna_f:02d}-{zi_f:02d}",
    }


def season_calendar_rows(matches: list) -> list[dict]:
    """Calendarele DISTINCTE de sezon, din meciurile descoperite — FUNCTIE
    PURA, fara I/O.

    [ADR-067] Separata deliberat de scriere: partea care decide CE se scrie
    ramane testabila fara baza de date, iar `_discover_for_hub()` ramane fara
    I/O de retea catre Supabase in mijlocul buclei Playwright.

    Un calendar fara interval complet e inutil pentru intrebarea „ce sezon
    contine ziua de azi", dar eticheta tot merita pastrata — de aceea randul
    e emis si atunci, cu interval None (cazul hub-ului `/fixtures/`, verificat
    live: poarta eticheta, nu si bara de progres)."""
    vazute: dict[tuple, dict] = {}
    for m in matches:
        liga = getattr(m, "league", None)
        sezon = getattr(m, "season", None)
        if not liga or not sezon:
            continue
        cheie = (liga, sezon)
        rand = {
            "competition": liga, "season": sezon,
            "start_date": getattr(m, "season_start", None),
            "end_date": getattr(m, "season_end", None),
        }
        # Prima aparitie CU interval castiga; altfel prima aparitie, oricare.
        veche = vazute.get(cheie)
        if veche is None or (veche["start_date"] is None and rand["start_date"]):
            vazute[cheie] = rand
    return list(vazute.values())


def persist_season_calendars(matches: list) -> int:
    """Scrie calendarele in `competition_season`. Intoarce cate au fost scrise.

    [ADR-067] Esecul aici NU opreste Discovery: calendarul e un fapt auxiliar,
    iar descoperirea meciurilor e treaba principala. Se logheaza, nu se ridica."""
    randuri = season_calendar_rows(matches)
    if not randuri:
        return 0
    try:
        from database.queries import upsert_competition_season
    except ModuleNotFoundError:
        return 0
    scrise = 0
    for r in randuri:
        if upsert_competition_season(r["competition"], r["season"],
                                     r["start_date"], r["end_date"]):
            scrise += 1
        else:
            logger.warning("[Flashscore.Discovery] calendar nescris pentru %s/%s",
                           r["competition"], r["season"])
    return scrise


def season_for_kickoff(
    season: str | None, season_start: str | None, season_end: str | None,
    kickoff_date: str | None,
) -> str | None:
    """Sezonul care se SCRIE efectiv pentru un meci — FUNCTIE PURA, fara I/O.

    [ADR-066 P2b] Eticheta de pe hub descrie sezonul afisat de Flashscore, iar
    meciurile listate acolo apartin, prin constructie, acelui sezon. Garda de
    aici e o centura in plus, nu o neincredere in provider: daca hub-ul ofera
    si intervalul, un meci cu data IN AFARA lui nu primeste sezon deloc.

    Motivul e cel invatat pe 2026-08-23, la inversarea de teren: o eticheta
    aplicata gresit e mai rea decat o eticheta lipsa, pentru ca nu produce
    niciun semnal. Un `season` gresit ar contamina tacit walk-forward-ul si
    `season_cleanup.py` (care sterge pe baza sezonului).

    Fara interval (cazul hub-ului `/fixtures/`, unde bara de progres nu apare)
    eticheta ramane singurul semnal si se foloseste ca atare — nu se inventeaza
    un interval ca sa avem ce verifica.

    Fara eticheta -> None (Regula #8, necunoscut ramane necunoscut)."""
    if not season:
        return None
    if not season_start or not season_end or not kickoff_date:
        return season
    zi = kickoff_date[:10]
    if season_start <= zi <= season_end:
        return season
    logger.warning(
        "[Flashscore.Discovery] meci pe %s in afara intervalului sezonului %s "
        "(%s .. %s) — sezonul NU se scrie pentru acest meci.",
        zi, season, season_start, season_end,
    )
    return None


def dedupe_by_mid(matches: list) -> list:
    """Elimina meciurile descoperite de mai multe ori, dupa `mid` — FUNCTIE
    PURA, pastreaza ordinea si prima aparitie.

    [R5, 2026-08-23] Rularea din 23 august a descoperit 4 mid-uri de doua ori
    (4xKntFxe, zkSijgL7, nqbcPVHG, EJFII9Il): hub-urile /fixtures/ si
    /results/ pot lista acelasi meci, iar un meci in desfasurare apare in
    ambele. Trei au fost sarite la a doua trecere prin Delta Sync (munca
    irosita: 7 tab-uri Playwright degeaba), dar al patrulea a picat pe
    validare de identitate si a facut workflow-ul ROSU — un meci care fusese
    deja colectat cu succes la prima trecere.

    Explica si observatia nelamurita din CLAUDE.md ("3 intrari MLS cu acelasi
    mid aparand de doua ori, o data OK apoi ESUAT") — nu era un duplicat in
    baza de date, ci in lista de descoperire.

    Cazurile eliminate se logheaza: daca acelasi meci ajunge sa fie listat sub
    DOUA ligi diferite, asta e o informatie despre acoperire, nu zgomot."""
    vazute: dict = {}
    pastrate: list = []
    for m in matches:
        mid = getattr(m, "mid", None)
        if mid is None:
            pastrate.append(m)  # fara mid nu putem deduplica; nu aruncam nimic
            continue
        anterior = vazute.get(mid)
        if anterior is None:
            vazute[mid] = m
            pastrate.append(m)
            continue
        liga_ant = getattr(anterior, "league", None)
        liga_now = getattr(m, "league", None)
        if liga_ant != liga_now:
            logger.warning(
                "[Flashscore.Discovery] mid=%s descoperit sub DOUA ligi diferite "
                "(%r pastrata, %r eliminata) — verifica maparea competitiilor",
                mid, liga_ant, liga_now,
            )
        else:
            logger.info(
                "[Flashscore.Discovery] mid=%s descoperit de mai multe ori in %r "
                "(sursa %r vs %r) — pastrat o singura data",
                mid, liga_now, getattr(anterior, "source", None), getattr(m, "source", None),
            )
    return pastrate


_IDENTITY_FIELDS = ("home_team", "away_team", "kickoff_date")


def _describe_identity_gaps(rejected: list) -> str:
    """Care campuri din cheia naturala lipseau, pentru fiecare rand respins —
    FUNCTIE PURA, fara I/O.

    Nu se includ VALORILE campurilor prezente: numele echipelor pot fi lungi
    si nu ajuta la diagnostic. Conteaza ce LIPSESTE. Daca nu lipseste nimic
    din cheia naturala, motivul respingerii e altul decat cel asteptat si se
    raporteaza ca atare — nu se presupune (Regula #8)."""
    if not rejected:
        return "niciun rand respins raportat"
    parti: list[str] = []
    for r in rejected:
        record = getattr(r, "record", None) or {}
        lipsa = [c for c in _IDENTITY_FIELDS if not record.get(c)]
        motiv = getattr(r, "reason", None) or "motiv necunoscut"
        parti.append(f"{motiv}: lipsesc {lipsa}" if lipsa
                     else f"{motiv}: cheia naturala e completa (motiv neasteptat)")
    return "; ".join(parti)


def run_foundation_data_layer_for_discovered_matches(
    matches: list[DiscoveredMatch],
) -> list[dict[str, Any]]:
    """Ruleaza fetch()/normalize()/validate() (FlashscoreAdapter,
    adapter.py) + `persist_match_with_data_trust_layer()` direct (nu
    `adapter.persist()`, care intoarce doar bool - contractul
    `SyncAdapter`) pentru fiecare meci descoperit, secvential, cu pacing
    explicit intre CERERILE REALE catre Flashscore
    (`FLASHSCORE_MIN_DELAY_SECONDS`; un meci sarit prin Delta Sync nu
    contacteaza providerul, deci nu se distanteaza - vezi bucla) -
    "Foundation Data Layer va rula apoi peste fiecare meci descoperit"
    (aprobare explicita, 2026-07-29). `preflight()` verificat o singura data, inainte
    de bucla - `tos_reviewed` nu se schimba intre meciuri in aceeasi
    rulare. Fiecare rezultat e raportul complet intors de
    `persist_match_with_data_trust_layer()` (niciodata doar True/False -
    esecul partial ramane vizibil, North Star #9)."""
    from .adapter import FlashscoreAdapter, _build_match_ref
    from .persistence import persist_match_with_data_trust_layer

    try:
        from database.queries import is_flashscore_match_already_collected
    except ModuleNotFoundError:
        is_flashscore_match_already_collected = None

    adapter = FlashscoreAdapter()
    adapter.preflight()

    reports: list[dict[str, Any]] = []
    # [REPARAT 2026-08-30] Numara CERERILE REALE catre Flashscore, nu iteratiile.
    # Vezi blocul de mai jos pentru masuratoare — asta e pivotul fixului.
    cereri_reale = 0
    for match in matches:
        # [Delta Sync — Faza 2] `mid` e cunoscut ÎNAINTE de fetch (Discovery
        # îl extrage din URL-ul hub-ului) — dacă acest meci a fost deja
        # persistat canonic (fixture_id="flashscore_{mid}" pe match_history),
        # sărim fetch-ul complet (7 tab-uri Playwright), nu doar persist().
        #
        # [ORDINE REPARATA 2026-08-30] Verificarea Delta Sync e ACUM prima, iar
        # `polite_delay()` s-a mutat DUPA ea. Inainte, delay-ul rula
        # neconditionat la inceputul fiecarei iteratii (`if i > 0`), deci si
        # pentru meciurile sarite — care nu fac NICIUN apel catre Flashscore
        # (verificarea Delta Sync e o interogare Supabase). Politetea aparea
        # pe un canal pe care nu se cerea nimic.
        #
        # MASURAT pe doua rulari live_sync reale din 2026-08-29:
        #   14:10 (reusita, 44m44s): 457 descoperite, 438 sarite, 19 procesate
        #     -> ~22 min din 44 (JUMATATE din rulare) au fost somn pur.
        #   19:36 (TAIATA de timeout la 50m18s): 487 descoperite, doar 327
        #     atinse (67%), 289 sarite, 38 procesate -> ~14,5 min irositi;
        #     160 de meciuri nu au mai fost atinse deloc.
        # A doua taiere in 3 zile (si 2026-08-27, la 50m19s). Setul descoperit
        # creste pe masura ce sezoanele avanseaza (457 -> 487 in 5 ore), deci
        # timpul irosit creste liniar cu el — s-ar fi agravat de la sine.
        if is_flashscore_match_already_collected is not None and is_flashscore_match_already_collected(match.mid):
            reports.append({
                "match_id": None, "ok": True, "skipped": True,
                "reason": "already_collected", "match": match,
            })
            continue
        # Politete DOAR intre cereri reale: nu inaintea primeia (nimic de
        # distantat inca), niciodata inaintea unei sariri. `cereri_reale` se
        # incrementeaza chiar daca `fetch()` arunca — cererea a plecat
        # oricum spre Flashscore, deci urmatoarea trebuie distantata de ea.
        if cereri_reale > 0:
            polite_delay()
        cereri_reale += 1
        try:
            pages = adapter.fetch({"match_base_url": match.match_base_url, "mid": match.mid})
        except Exception as exc:
            logger.error(
                "[Flashscore.Discovery] fetch esuat pentru %s (mid=%s): %s",
                match.match_base_url, match.mid, exc,
            )
            reports.append({"match_id": None, "ok": False, "error": str(exc), "match": match})
            continue
        records = adapter.normalize(pages)
        validation = adapter.validate_detailed(records)
        if not validation.valid:
            # [R3, 2026-08-23] Motivul CONCRET, nu sirul generic de dinainte.
            # `validate_flat_identity` respinge pentru un singur motiv
            # (`missing_natural_key`), deci ce conteaza e CARE camp lipsea —
            # altfel esecul e nediagnosticabil: la validare esuata nu se
            # scrie nici macar RAW, deci nu ramane nicio urma forensica.
            detalii = _describe_identity_gaps(validation.rejected)
            logger.error(
                "[Flashscore.Discovery] validare identitate esuata pentru %s "
                "(mid=%s, liga=%s): %s", match.match_base_url, match.mid, match.league, detalii,
            )
            reports.append({
                "match_id": None, "ok": False,
                "error": f"validare identitate esuata ({detalii})",
                "match": match,
            })
            continue
        record = validation.valid[0]
        match_ref = _build_match_ref(record.get("home_team"), record.get("away_team"), record.get("kickoff_date"))
        # [FIX live] match_history.league e NOT NULL - Discovery deja
        # cunoaste liga (a ales-o explicit ca sa construiasca URL-ul hub-ului,
        # FLASHSCORE_TRACKED_COMPETITIONS), o furnizeaza direct in loc sa
        # ceara normalizer-ului sa o extraga din pagina (gol real, documentat
        # in FLASHSCORE_FIELD_MAPPING_MATRIX.md - "Cross-provider dependency").
        # [ADR-066 P2b] `season` provine din hub-ul din care a fost descoperit
        # meciul, filtrat prin `season_for_kickoff()`. Plumbing-ul exista de la
        # migratia 038 (`persist_match_foundation_data(..., season=...)`), dar
        # nimeni nu i-a dat vreodata o valoare — de aceea toate cele 1.058 de
        # randuri Flashscore aveau season NULL, alaturi de celelalte trei tabele
        # FDL care primesc acelasi parametru.
        report = persist_match_with_data_trust_layer(
            record["_pages"], match_ref=match_ref, league=match.league, competition=match.league,
            season=season_for_kickoff(
                match.season, match.season_start, match.season_end,
                record.get("kickoff_date"),
            ),
        )
        reports.append({**report, "match": match})
    return reports
