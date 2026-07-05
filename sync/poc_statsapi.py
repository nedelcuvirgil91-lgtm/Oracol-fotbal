"""
================================================================================
FOOTBALL ORACLE v4.0 — Sprint 0: Stats API Proof of Concept
================================================================================
Module: sync/poc_statsapi.py

Testează The Stats API și generează un raport de acoperire complet.

Ce testează:
  1. Health check + validare API key
  2. Descoperire competition IDs pentru 6 ligi
  3. Rate limit — câte req/min înainte de 429
  4. Paginare — per_page maxim efectiv
  5. Per 100+ meciuri din ligi diferite:
     - xG disponibil
     - Posesie
     - Șuturi + șuturi pe poartă
     - Cornere, cartonașe
     - Odds opening + closing
     - Lineups confirmate
     - Market value jucători
  6. Generează raport final în format tabel

Rulare:
  python sync/poc_statsapi.py
  python sync/poc_statsapi.py --quick   # doar 20 meciuri, test rapid
================================================================================
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import requests

root = Path(__file__).parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

logging.basicConfig(
    level=logging.WARNING,  # Supress info în PoC — vrem output curat
    format="%(asctime)s  [%(levelname)s]  %(name)s — %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("FootballOracle.PoC")

BASE_URL = "https://api.thestatsapi.com/api"

# Ligi de testat — mix de top5 + ligi mici
LEAGUES_TO_TEST = [
    {"name": "Premier League",   "search": "Premier League",        "country": "England"},
    {"name": "La Liga",          "search": "La Liga",               "country": "Spain"},
    {"name": "Serie A",          "search": "Serie A",               "country": "Italy"},
    {"name": "Bundesliga",       "search": "Bundesliga",            "country": "Germany"},
    {"name": "Ligue 1",          "search": "Ligue 1",               "country": "France"},
    {"name": "Romania SuperLiga","search": "Romania",               "country": "Romania"},
]

MATCHES_PER_LEAGUE = 18  # ~18 * 6 ligi = ~108 meciuri total


def _get_api_key() -> str | None:
    try:
        import streamlit as st
        key = st.secrets.get("STATS_API_KEY")
        if key:
            return key
    except Exception:
        pass
    return os.environ.get("STATS_API_KEY")


# ════════════════════════════════════════════════════════════════════════════
# HTTP CLIENT SIMPLU
# ════════════════════════════════════════════════════════════════════════════

@dataclass
class RequestStats:
    total:      int = 0
    successful: int = 0
    rate_limit_hit: bool = False
    min_interval_used: float = 0.0
    max_per_page_tested: int = 0
    per_page_limit: int = 0


_req_stats = RequestStats()
_last_req_time: float = 0.0
_req_interval: float = 1.2  # start conservator


def _get(path: str, params: dict | None = None,
         timeout: int = 15) -> dict | None:
    global _last_req_time, _req_stats

    api_key = _get_api_key()
    if not api_key:
        print("❌ STATS_API_KEY lipsă din secrets/env")
        sys.exit(1)

    elapsed = time.time() - _last_req_time
    if elapsed < _req_interval:
        time.sleep(_req_interval - elapsed)

    _req_stats.total += 1

    try:
        resp = requests.get(
    f"{BASE_URL}/{path.lstrip('/')}",
    headers={
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    },
    params=params or {},
    timeout=timeout,
)
_last_req_time = time.time()

# DEBUG TEMPORAR
if resp.status_code != 200:
    print(f"\n===== DEBUG {path} =====")
    print("STATUS:", resp.status_code)
    print("BODY:", resp.text)
    print("========================\n")

if resp.status_code == 200:
    _req_stats.successful += 1
    return resp.json()
        if resp.status_code == 429:
            _req_stats.rate_limit_hit = True
            logger.warning("Rate limit 429 la %s", path)
            time.sleep(10)
            return None
        if resp.status_code in (401, 403):
            print(f"❌ Auth error {resp.status_code} — verifică STATS_API_KEY")
            return None
        if resp.status_code == 404:
            return None

        logger.debug("HTTP %d pentru %s", resp.status_code, path)
        return None

    except Exception as exc:
        logger.warning("Eroare fetch %s: %s", path, exc)
        _last_req_time = time.time()
        return None


# ════════════════════════════════════════════════════════════════════════════
# STRUCTURI PENTRU RAPORT
# ════════════════════════════════════════════════════════════════════════════

@dataclass
class LeagueResult:
    league:          str
    comp_id:         str | None  = None
    season_id:       str | None  = None
    season_name:     str | None  = None
    matches_tested:  int         = 0
    xg_available:    int         = 0
    possession:      int         = 0
    shots:           int         = 0
    shots_on_target: int         = 0
    corners:         int         = 0
    cards:           int         = 0
    odds_opening:    int         = 0
    odds_closing:    int         = 0
    lineups:         int         = 0
    market_value:    int         = 0
    stats_endpoint_ok: int       = 0
    odds_endpoint_ok:  int       = 0
    errors:          int         = 0
    sample_match_id: str | None  = None


@dataclass
class PoCReport:
    timestamp:      str
    api_healthy:    bool         = False
    rate_limit_hit: bool         = False
    req_interval:   float        = 1.2
    per_page_limit: int          = 0
    leagues:        list[LeagueResult] = field(default_factory=list)
    total_matches:  int          = 0
    total_requests: int          = 0
    success_rate:   float        = 0.0


# ════════════════════════════════════════════════════════════════════════════
# TEST 1: HEALTH + API KEY
# ════════════════════════════════════════════════════════════════════════════

def test_health(report: PoCReport) -> bool:
    print("  Verificare API key...", end=" ", flush=True)
    data = _get("health")
    if data and data.get("status") == "healthy":
        report.api_healthy = True
        print("✅ healthy")
        return True
    print("❌ eșuat")
    return False


# ════════════════════════════════════════════════════════════════════════════
# TEST 2: RATE LIMIT
# ════════════════════════════════════════════════════════════════════════════

def test_rate_limit(report: PoCReport) -> None:
    """
    Testează rate limit-ul trimițând cereri rapide și văzând când apare 429.
    Testăm cu intervale: 0.3s, 0.5s, 0.8s, 1.0s
    """
    print("  Test rate limit...", end=" ", flush=True)
    global _req_interval

    intervals_to_test = [0.3, 0.5, 0.8, 1.0]
    safe_interval = 1.2

    for interval in intervals_to_test:
        hit_limit = False
        for _ in range(5):
            time.sleep(interval)
            api_key = _get_api_key()
            try:
                resp = requests.get(
                    f"{BASE_URL}/health",
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=5,
                )
                if resp.status_code == 429:
                    hit_limit = True
                    break
            except Exception:
                break

        if not hit_limit:
            safe_interval = interval + 0.1
            break

    _req_interval = safe_interval
    report.req_interval = safe_interval

    if safe_interval <= 0.5:
        limit_str = f"≥120 req/min (interval sigur: {safe_interval}s)"
    elif safe_interval <= 1.0:
        limit_str = f"~60-120 req/min (interval sigur: {safe_interval}s)"
    else:
        limit_str = f"~60 req/min sau mai puțin (interval sigur: {safe_interval}s)"

    print(f"✅ {limit_str}")


# ════════════════════════════════════════════════════════════════════════════
# TEST 3: PAGINARE
# ════════════════════════════════════════════════════════════════════════════

def test_pagination(report: PoCReport) -> None:
    """Testează per_page maxim efectiv."""
    print("  Test paginare...", end=" ", flush=True)

    # Încearcă per_page=100
    data = _get("football/competitions", {"per_page": 100, "page": 1})
    if data and isinstance(data, dict):
        meta = data.get("meta", {})
        actual_per_page = meta.get("per_page", 0)
        total = meta.get("total", 0)
        report.per_page_limit = actual_per_page
        print(f"✅ per_page={actual_per_page}, total competiții={total}")
    else:
        print("⚠️  Nu am putut testa paginarea")


# ════════════════════════════════════════════════════════════════════════════
# TEST 4: DESCOPERIRE COMPETIȚII
# ════════════════════════════════════════════════════════════════════════════

def discover_competition(league_info: dict) -> tuple[str | None, str | None, str | None]:
    """
    Returnează (comp_id, season_id, season_name) pentru o ligă.
    Ia cel mai recent sezon complet (nu cel curent dacă e în desfășurare).
    """
    search = league_info["search"]
    country = league_info.get("country", "")

    data = _get("football/competitions", {
        "search": search, "per_page": 20
    })
    if not data:
        return None, None, None

    comps = data.get("data", [])
    if not comps:
        return None, None, None

    # Filtrare: preferăm competiția din țara corectă
    comp = None
    for c in comps:
        c_country = c.get("country", "") or ""
        c_name    = c.get("name", "").lower()
        if country.lower() in c_country.lower() or search.lower() in c_name:
            comp = c
            break
    if not comp:
        comp = comps[0]

    comp_id = comp.get("id")
    if not comp_id:
        return None, None, None

    # Ia sezoanele
    seasons_data = _get(f"football/competitions/{comp_id}/seasons")
    if not seasons_data:
        return comp_id, None, None

    seasons = seasons_data.get("data", [])
    if not seasons:
        return comp_id, None, None

    # Preferăm penultimul sezon (cel mai recent complet)
    # Sezonul curent poate fi incomplet
    finished_seasons = [s for s in seasons if not s.get("is_current", False)]
    target_season = finished_seasons[0] if finished_seasons else seasons[0]

    return comp_id, target_season.get("id"), target_season.get("year", target_season.get("name"))


# ════════════════════════════════════════════════════════════════════════════
# TEST 5: MECIURI + STATISTICI
# ════════════════════════════════════════════════════════════════════════════

def test_league(
    league_info: dict,
    comp_id: str,
    season_id: str,
    season_name: str,
    matches_to_test: int,
) -> LeagueResult:
    """
    Testează N meciuri dintr-o ligă și verifică disponibilitatea fiecărui
    câmp important.
    """
    result = LeagueResult(
        league=league_info["name"],
        comp_id=comp_id,
        season_id=season_id,
        season_name=season_name,
    )

    # Descarcă o pagină de meciuri finite
    data = _get("football/matches", {
        "competition_id": comp_id,
        "season_id":      season_id,
        "status":         "finished",
        "per_page":       matches_to_test,
        "page":           1,
    })

    if not data:
        result.errors += 1
        return result

    matches = data.get("data", [])
    if not matches:
        return result

    # Ia primele N meciuri
    matches = matches[:matches_to_test]
    result.matches_tested = len(matches)

    if matches:
        result.sample_match_id = matches[0].get("id")

    for match in matches:
        match_id = match.get("id")
        if not match_id:
            continue

        # ── Test /stats endpoint ──────────────────────────────────────────
        stats_data = _get(f"football/matches/{match_id}/stats")
        if stats_data and isinstance(stats_data, dict):
            result.stats_endpoint_ok += 1
            stats = stats_data.get("data", {})
            overview = stats.get("overview", {})

            def _has(section: str, key: str) -> bool:
                try:
                    val = stats.get(section, {}).get(key, {}).get("all", {})
                    return val.get("home") is not None or val.get("away") is not None
                except Exception:
                    return False

            def _has_ov(key: str) -> bool:
                try:
                    val = overview.get(key, {}).get("all", {})
                    return val.get("home") is not None
                except Exception:
                    return False

            # xG
            if _has_ov("expected_goals") or stats.get("np_expected_goals"):
                result.xg_available += 1

            # Posesie
            if _has_ov("ball_possession"):
                result.possession += 1

            # Șuturi
            if _has_ov("total_shots"):
                result.shots += 1

            # Șuturi pe poartă
            if _has_ov("shots_on_target"):
                result.shots_on_target += 1

            # Cornere
            if _has_ov("corner_kicks"):
                result.corners += 1

            # Cartonașe
            if _has_ov("yellow_cards"):
                result.cards += 1

        # ── Test /odds endpoint ───────────────────────────────────────────
        odds_data = _get(f"football/matches/{match_id}/odds")
        if odds_data and isinstance(odds_data, dict):
            result.odds_endpoint_ok += 1
            bookmakers = odds_data.get("data", {}).get("bookmakers", [])
            for bk in bookmakers:
                markets = bk.get("markets", {})
                match_odds = markets.get("match_odds", {})
                home_odds  = match_odds.get("home", {})
                if home_odds.get("opening"):
                    result.odds_opening += 1
                if home_odds.get("last_seen"):
                    result.odds_closing += 1
                break  # primul bookmaker e suficient pentru test

        # ── Test /lineups endpoint ────────────────────────────────────────
        lineup_data = _get(f"football/matches/{match_id}/lineups")
        if lineup_data and isinstance(lineup_data, dict):
            lineups = lineup_data.get("data", {})
            if lineups.get("home", {}).get("starting_xi"):
                result.lineups += 1

    # ── Test market value (un singur match pentru a obține team_id) ───────
    if matches:
        home_team_id = (matches[0].get("home_team") or {}).get("id")
        if home_team_id:
            squad_data = _get(f"football/teams/{home_team_id}/players")
            if squad_data and isinstance(squad_data, dict):
                players = squad_data.get("data", [])
                # Verificăm dacă cel puțin 50% din jucători au market_value
                with_value = sum(
                    1 for p in players
                    if p.get("market_value") is not None
                )
                if players and with_value / len(players) >= 0.5:
                    result.market_value = result.matches_tested  # disponibil

    return result


# ════════════════════════════════════════════════════════════════════════════
# RAPORT FINAL
# ════════════════════════════════════════════════════════════════════════════

def _pct(value: int, total: int) -> str:
    if total == 0:
        return "N/A"
    return f"{value/total*100:.0f}%"


def print_report(report: PoCReport) -> None:
    print()
    print("═" * 70)
    print("  FOOTBALL ORACLE — Stats API PoC Report")
    print(f"  {report.timestamp}")
    print("═" * 70)

    print(f"\n  API Health    : {'✅ healthy' if report.api_healthy else '❌ unhealthy'}")
    print(f"  Rate limit    : interval sigur = {report.req_interval}s "
          f"({'429 detectat' if report.rate_limit_hit else 'fără 429'})")
    print(f"  Per page max  : {report.per_page_limit}")
    print(f"  Total requests: {report.total_requests}")
    print(f"  Success rate  : {report.success_rate:.1f}%")

    print()
    print("  ACOPERIRE PE LIGI:")
    print("  " + "─" * 66)

    # Header tabel
    header = f"  {'Ligă':<20} {'Meciuri':>7} {'xG':>5} {'Pos':>5} {'Shots':>6} {'Odds':>5} {'Lineup':>7} {'MktVal':>7}"
    print(header)
    print("  " + "─" * 66)

    for lr in report.leagues:
        n = lr.matches_tested
        if n == 0:
            print(f"  {lr.league:<20} {'N/A':>7}")
            continue

        print(
            f"  {lr.league:<20}"
            f" {n:>7}"
            f" {_pct(lr.xg_available, n):>5}"
            f" {_pct(lr.possession, n):>5}"
            f" {_pct(lr.shots, n):>6}"
            f" {_pct(lr.odds_opening, n):>5}"
            f" {_pct(lr.lineups, n):>7}"
            f" {_pct(lr.market_value, n):>7}"
        )

    print("  " + "─" * 66)

    # Medie globală
    total = sum(lr.matches_tested for lr in report.leagues)
    if total > 0:
        print(
            f"  {'TOTAL/MEDIE':<20}"
            f" {total:>7}"
            f" {_pct(sum(lr.xg_available for lr in report.leagues), total):>5}"
            f" {_pct(sum(lr.possession for lr in report.leagues), total):>5}"
            f" {_pct(sum(lr.shots for lr in report.leagues), total):>6}"
            f" {_pct(sum(lr.odds_opening for lr in report.leagues), total):>5}"
            f" {_pct(sum(lr.lineups for lr in report.leagues), total):>7}"
            f" {_pct(sum(lr.market_value for lr in report.leagues), total):>7}"
        )

    print()
    print("  DETALII ENDPOINTS:")
    print("  " + "─" * 66)
    for lr in report.leagues:
        if lr.matches_tested == 0:
            continue
        n = lr.matches_tested
        print(
            f"  {lr.league:<20}"
            f"  /stats: {_pct(lr.stats_endpoint_ok, n)}"
            f"  /odds: {_pct(lr.odds_endpoint_ok, n)}"
            f"  odds_open: {_pct(lr.odds_opening, n)}"
            f"  odds_close: {_pct(lr.odds_closing, n)}"
            f"  corners: {_pct(lr.corners, n)}"
            f"  cards: {_pct(lr.cards, n)}"
        )

    print()
    print("  RECOMANDĂRI PENTRU SPRINT 1:")
    print("  " + "─" * 66)

    # Analiza automată
    all_leagues = [lr for lr in report.leagues if lr.matches_tested > 0]
    if not all_leagues:
        print("  ⚠️  Nicio ligă testată cu succes.")
        return

    avg_xg    = sum(lr.xg_available for lr in all_leagues) / sum(lr.matches_tested for lr in all_leagues)
    avg_odds  = sum(lr.odds_opening for lr in all_leagues) / sum(lr.matches_tested for lr in all_leagues)
    avg_lineup = sum(lr.lineups for lr in all_leagues) / sum(lr.matches_tested for lr in all_leagues)
    avg_mv    = sum(lr.market_value for lr in all_leagues) / sum(lr.matches_tested for lr in all_leagues)

    if avg_xg >= 0.8:
        print(f"  ✅ xG disponibil la {avg_xg*100:.0f}% din meciuri — INCLUDE în schema ML")
    elif avg_xg >= 0.5:
        print(f"  🟡 xG disponibil la {avg_xg*100:.0f}% — include cu NULL fallback")
    else:
        print(f"  ❌ xG disponibil la {avg_xg*100:.0f}% — NU include ca feature obligatoriu ML")

    if avg_odds >= 0.8:
        print(f"  ✅ Odds disponibile la {avg_odds*100:.0f}% — CREEAZĂ tabel odds_history")
    else:
        print(f"  🟡 Odds disponibile la {avg_odds*100:.0f}% — include cu atenție")

    if avg_lineup >= 0.7:
        print(f"  ✅ Lineups la {avg_lineup*100:.0f}% — IMPORTĂ în sprint dedicat")
    else:
        print(f"  🟡 Lineups la {avg_lineup*100:.0f}% — folosește doar pentru live, nu ML istoric")

    if avg_mv >= 0.7:
        print(f"  ✅ Market value la {avg_mv*100:.0f}% — IMPORTĂ în team_strength_history")
    else:
        print(f"  🟡 Market value la {avg_mv*100:.0f}% — verifică manual disponibilitatea")

    if report.req_interval <= 0.5:
        print(f"  ✅ Rate limit generos — import masiv posibil rapid")
    elif report.req_interval <= 1.0:
        print(f"  🟡 Rate limit moderat — import masiv: ~{3600/report.req_interval:.0f} req/oră")
    else:
        print(f"  ⚠️  Rate limit restrictiv — import masiv va dura mai mult")

    print()
    print("═" * 70)


# ════════════════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════════════════

def run_poc(quick: bool = False) -> PoCReport:
    matches_per_league = 5 if quick else MATCHES_PER_LEAGUE

    report = PoCReport(
        timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    )

    print()
    print("═" * 70)
    print("  ⚽  FOOTBALL ORACLE — Sprint 0: Stats API PoC")
    print(f"  Mod: {'QUICK (5 meciuri/ligă)' if quick else f'FULL ({matches_per_league} meciuri/ligă)'}")
    print("═" * 70)
    print()

    # Test 1: Health
    print("── Test 1/5: Health Check")
    if not test_health(report):
        return report
    print()

    # Test 2: Rate limit
    print("── Test 2/5: Rate Limit")
    test_rate_limit(report)
    print()

    # Test 3: Paginare
    print("── Test 3/5: Paginare")
    test_pagination(report)
    print()

    # Test 4: Descoperire competiții
    print("── Test 4/5: Descoperire Competiții")
    comp_map: dict[str, tuple[str, str, str]] = {}
    for lg in LEAGUES_TO_TEST:
        name = lg["name"]
        print(f"  {name}...", end=" ", flush=True)
        comp_id, season_id, season_name = discover_competition(lg)
        if comp_id and season_id:
            comp_map[name] = (comp_id, season_id, season_name or "")
            print(f"✅ {comp_id} / {season_name}")
        else:
            print(f"❌ negăsit")
    print()

    # Test 5: Meciuri + statistici
    print(f"── Test 5/5: Meciuri + Statistici ({matches_per_league} meciuri/ligă)")
    for lg in LEAGUES_TO_TEST:
        name = lg["name"]
        if name not in comp_map:
            result = LeagueResult(league=name)
            report.leagues.append(result)
            continue

        comp_id, season_id, season_name = comp_map[name]
        print(f"\n  {name} ({season_name}):")
        print(f"    Descarcă meciuri...", end=" ", flush=True)

        result = test_league(
            league_info    = lg,
            comp_id        = comp_id,
            season_id      = season_id,
            season_name    = season_name,
            matches_to_test = matches_per_league,
        )
        report.leagues.append(result)

        n = result.matches_tested
        if n > 0:
            print(f"✅ {n} meciuri")
            print(f"    xG={_pct(result.xg_available,n)} "
                  f"Pos={_pct(result.possession,n)} "
                  f"Shots={_pct(result.shots,n)} "
                  f"Odds={_pct(result.odds_opening,n)} "
                  f"Lineup={_pct(result.lineups,n)} "
                  f"MktVal={_pct(result.market_value,n)}")
        else:
            print("❌ niciun meci")

    # Statistici finale
    report.total_matches  = sum(lr.matches_tested for lr in report.leagues)
    report.total_requests = _req_stats.total
    report.rate_limit_hit = _req_stats.rate_limit_hit
    if _req_stats.total > 0:
        report.success_rate = _req_stats.successful / _req_stats.total * 100

    # Raport final
    print_report(report)
    return report


def main():
    parser = argparse.ArgumentParser(
        description="Football Oracle — Sprint 0: Stats API PoC"
    )
    parser.add_argument("--quick", action="store_true",
                        help="Test rapid: 5 meciuri per ligă în loc de 18")
    args = parser.parse_args()

    run_poc(quick=args.quick)


if __name__ == "__main__":
    main()
