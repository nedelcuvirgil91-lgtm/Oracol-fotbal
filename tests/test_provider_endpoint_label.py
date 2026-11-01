"""Eticheta `provider_call_log.endpoint` / `provider_metrics.endpoint`.

Fără rețea, fără Supabase: `_eticheta_endpoint` e o funcție PURĂ și statică,
iar `_detect_provider_endpoint` folosește doar atribute de clasă, deci se
exercitează pe o instanță construită cu `__new__` (fără `__init__`, deci fără
nicio inițializare de client HTTP).

DE CE EXISTĂ: regula veche lua PRIMUL segment de cale, iar măsurătoarea de pe
2026-11-01 a arătat două defecte în direcții OPUSE —
  · colapsa cele patru endpoint-uri Odds API într-unul singur (`sports`), ceea
    ce a produs o concluzie falsă („zero apeluri la /odds în octombrie");
  · băga identificatorul de ligă ESPN în etichetă (14 din 31 de rânduri din
    `provider_metrics` erau slug-uri, nu endpoint-uri).
Ambele sunt acoperite aici ca regresii, cu forma reală de cale, nu inventată.
"""
from __future__ import annotations

import pytest

from oracle_api import (
    ESPN_API_URL,
    FOOTBALL_DATA_URL,
    ODDS_API_URL,
    THESPORTSDB_URL,
    WEATHER_URL,
    FootballOracleAPI,
)

_eticheta = FootballOracleAPI._eticheta_endpoint


def _api() -> FootballOracleAPI:
    """Instanță fără `__init__` — nimic de inițializat pentru calea asta."""
    return FootballOracleAPI.__new__(FootballOracleAPI)


# ── Formele REALE de cale, enumerate din construcțiile f-string din
# `oracle_api.py` (verificate, nu presupuse) ──────────────────────────────────

@pytest.mark.parametrize("cale, asteptat", [
    # Odds API — cele patru care se colapsau în `sports`
    ("sports", "sports"),
    ("sports/soccer_epl/odds", "sports/odds"),
    ("sports/soccer_epl/events", "sports/events"),
    ("sports/soccer_epl/scores", "sports/scores"),
    # ESPN — primul segment e VARIABIL (slug de ligă)
    ("eng.1/scoreboard", "scoreboard"),
    ("uefa.champions/scoreboard", "scoreboard"),
    # football-data.org
    ("competitions/PL/standings", "competitions/standings"),
    ("matches", "matches"),
    # TheSportsDB
    ("eventslast.php", "eventslast.php"),
    ("eventsnextleague.php", "eventsnextleague.php"),
    # WeatherAPI
    ("current.json", "current.json"),
    ("forecast.json", "forecast.json"),
    # FreeLF — valorile reale măsurate sunt literale, un singur segment
    ("football-get-matches-by-date", "football-get-matches-by-date"),
])
def test_formele_reale_de_cale(cale, asteptat):
    assert _eticheta(cale) == asteptat


# ── Cele două defecte, ca regresii explicite ────────────────────────────────

def test_REGRESIE_cele_patru_endpointuri_odds_api_sunt_DISTINCTE():
    """Defectul 1. Dacă astea trei redevin egale, `provider_call_log` nu mai
    poate spune dacă o eroare e la validare sau la cote — exact starea care a
    produs afirmația falsă „zero apeluri la /odds"."""
    etichete = {
        _eticheta("sports"),
        _eticheta("sports/soccer_epl/odds"),
        _eticheta("sports/soccer_epl/events"),
        _eticheta("sports/soccer_epl/scores"),
    }
    assert len(etichete) == 4, f"endpoint-uri colapsate: {sorted(etichete)}"


def test_REGRESIE_slugul_de_liga_NU_ajunge_in_eticheta():
    """Defectul 2. Un segment variabil în etichetă înseamnă un rând nou în
    `provider_metrics` per ligă — măsurat: 14 rânduri de slug-uri."""
    sluguri = ("eng.1", "ger.1", "fifa.world", "uefa.champions", "uefa.europa.conf")
    for slug in sluguri:
        eticheta = _eticheta(f"{slug}/scoreboard")
        assert slug not in eticheta, (
            f"slugul {slug!r} a ajuns în eticheta {eticheta!r} — un identificator "
            f"variabil fragmentează provider_metrics per ligă"
        )


def test_cheia_de_sport_NU_ajunge_in_eticheta():
    """Simetricul: nici cheia de sport din Odds API nu are ce căuta acolo."""
    eticheta = _eticheta("sports/soccer_romania_1_liga/odds")
    assert "soccer_romania_1_liga" not in eticheta
    assert eticheta == "sports/odds"


# ── Margini ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("cale, asteptat", [
    ("", "root"),
    ("/", "root"),
    ("///", "root"),
    ("sports/", "sports"),                       # slash final ignorat
    ("sports/soccer_epl/odds/", "sports/odds"),  # idem, nu produce segment gol
    ("sports?apiKey=x&all=true", "sports"),      # query string tăiat
    ("sports/soccer_epl/odds?regions=eu", "sports/odds"),
    ("a/b", "b"),                                # două segmente → ultimul
    ("a/b/c/d", "a/d"),                          # patru → primul + ultimul
])
def test_margini(cale, asteptat):
    assert _eticheta(cale) == asteptat


def test_eticheta_nu_e_niciodata_goala():
    for cale in ("", "/", "sports", "a/b/c", "x?y=1", "//a//"):
        assert _eticheta(cale), f"etichetă goală pentru {cale!r}"


# ── Integrarea cu detecția de provider ──────────────────────────────────────

@pytest.mark.parametrize("url, provider, endpoint", [
    (f"{ODDS_API_URL}/sports/soccer_epl/odds?apiKey=REDACTAT", "oddsapi", "sports/odds"),
    (f"{ODDS_API_URL}/sports?apiKey=REDACTAT&all=true", "oddsapi", "sports"),
    (f"{ESPN_API_URL}/eng.1/scoreboard", "espn", "scoreboard"),
    (f"{FOOTBALL_DATA_URL}/competitions/PL/standings", "footballdata", "competitions/standings"),
    (f"{THESPORTSDB_URL}/eventslast.php?id=1", "thesportsdb", "eventslast.php"),
    (f"{WEATHER_URL}/forecast.json?q=Bucharest", "weatherapi", "forecast.json"),
])
def test_detect_provider_endpoint_pe_url_complet(url, provider, endpoint):
    assert _api()._detect_provider_endpoint(url) == (provider, endpoint)


def test_gazda_necunoscuta_ramane_unknown():
    assert _api()._detect_provider_endpoint("https://exemplu.invalid/x/y") == ("unknown", "unknown")


def test_eticheta_nu_contine_niciodata_cheia_din_query():
    """Garda de secrete: cheia e un parametru de query la Odds API, iar
    eticheta se persistă. Query string-ul se taie ÎNAINTE de etichetare, deci
    nu are cum să ajungă în `provider_metrics`."""
    url = f"{ODDS_API_URL}/sports/soccer_epl/odds?apiKey=secret-de-test-123&regions=eu"
    provider, endpoint = _api()._detect_provider_endpoint(url)
    assert provider == "oddsapi"
    assert "secret-de-test-123" not in endpoint
    assert "apiKey" not in endpoint
    assert endpoint == "sports/odds"
