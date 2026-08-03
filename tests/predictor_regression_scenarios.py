"""Predictor Regression Suite — dataset golden + harness (EPIC "Functional
Completion", Punctul 2, aprobat explicit de proprietarul produsului,
2026-08-03).

Scop: 20 de meciuri reprezentative, cu input COMPLET determinist (formă
recentă, ELO, H2H — toate mock-uite, zero rețea/Supabase reală), astfel
încât orice schimbare viitoare la `oracle_engine.py`, `feature_engine.py`
sau la structura bazei de date poate fi verificată automat contra unui
snapshot „golden" (home_xg, away_xg, ph, pd, pa) — vezi
`tests/predictor_regression_golden.json` (snapshot-ul înghețat) și
`tests/test_predictor_regression_suite.py` (testul care compară).

Design:
  - Punctul de intrare exercitat e `FootballOracleEngine.evaluate_match()`
    — API-ul REAL de producție, nu un helper intern — exact ce ar rula
    `app.py` pentru un meci.
  - Cascada Database-First (ADR-035) rămâne ACTIVĂ (`DB_QUERIES_MODULE_
    AVAILABLE`/`SUPABASE_MODULE_AVAILABLE` neschimbate) — doar funcțiile
    individuale de citire (`get_latest_team_elo`, `sb.get_team_recent_
    results`, `get_h2h_from_history`, etc.) sunt înlocuite cu date fixe,
    pe numele modulului `oracle_engine` (exact tiparul deja folosit în
    `test_oracle_engine_db_first_elo.py`/`_h2h.py`/`_profile.py`) — nu un
    tipar nou inventat.
  - Monte Carlo (`_monte_carlo`) folosește deja un seed fix (`np.random.
    default_rng(seed=42)`, hardcodat în `oracle_engine.py`) — ieșirea e
    determinist-identică între rulări pentru input identic, verificat
    direct în cod, nu presupus.
  - `_save_json()` (scriere locală `predictions/<fixture_id>.json`) e
    dezactivat pentru fiecare scenariu — testul rămâne complet fără efecte
    secundare pe disc.
  - Injurii/vreme/ML/Team DNA Flashscore sunt dezactivate uniform (nu
    influențează scopul acestei suite — precizia predicției de bază
    Poisson/ELO/formă) — omise deliberat din scenarii, nu ascunse.

Reglementare 20 meciuri, acoperire deliberată:
  - Ligi diferite (baseline-uri de gol diferite): Premier League, La Liga,
    Serie A, Bundesliga, Ligue 1, Champions League, Europa League, Romania
    SuperLiga, MLS, World Cup 2026.
  - Nivele de calitate a datelor (ADR-035 D4): LIVE (formă recentă reală,
    ≥3 meciuri DB), ELO-only (fără formă, doar ELO), NEUTRAL (fără formă,
    fără ELO — echipă complet necunoscută).
  - Dinamici de meci: favorit clar acasă/deplasare, echipe apropiate,
    ambele echipe ofensive/defensive, semnale contradictorii (ELO mare,
    formă slabă), meci cu istoric H2H real, meci fără H2H.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from unittest import mock
import contextlib

from mappings import normalize_team_name


# ── Helpers de construcție a rândurilor brute (formă match_history-style) ──

def _form_row(team_canonical: str, is_home: bool, gf: int, ga: int) -> dict:
    """Un rând brut `match_history`, din perspectiva `team_canonical`
    (gf=goluri marcate, ga=goluri primite) — opusul e mereu un adversar
    fictiv, numele lui nu contează pentru profilul PROPRIU al echipei
    (doar `is_home`/`gf`/`ga`/`actual_result` sunt citite, vezi
    oracle_engine.py:917-936)."""
    if is_home:
        home_team, away_team, hg, ag = team_canonical, "Opponent FC", gf, ga
    else:
        home_team, away_team, hg, ag = "Opponent FC", team_canonical, ga, gf
    result = "H" if hg > ag else ("A" if hg < ag else "D")
    return {"home_team": home_team, "away_team": away_team,
            "actual_home_goals": hg, "actual_away_goals": ag, "actual_result": result}


def _h2h_row(home_c: str, away_c: str, this_side_was_home: bool, gf: int, ga: int) -> dict:
    """Un rând brut de confruntare directă DINTRE cele două echipe ale
    scenariului — `gf`/`ga` din perspectiva echipei `home_c` (gazda
    curentă a scenariului), indiferent cine a fost gazdă la acea
    confruntare istorică."""
    if this_side_was_home:
        h, a, hg, ag = home_c, away_c, gf, ga
    else:
        h, a, hg, ag = away_c, home_c, ga, gf
    result = "H" if hg > ag else ("A" if hg < ag else "D")
    return {"home_team": h, "away_team": a, "actual_home_goals": hg, "actual_away_goals": ag, "actual_result": result}


@dataclass
class Scenario:
    key: str
    home_team: str
    away_team: str
    league: str
    home_form: list[tuple[bool, int, int]] = field(default_factory=list)
    away_form: list[tuple[bool, int, int]] = field(default_factory=list)
    home_elo: int | None = None
    away_elo: int | None = None
    h2h: list[tuple[bool, int, int]] = field(default_factory=list)  # din perspectiva home_team
    home_odds: float | None = None
    draw_odds: float | None = None
    away_odds: float | None = None
    kickoff_date: str = "2026-08-10"

    @property
    def home_canonical(self) -> str:
        return normalize_team_name(self.home_team)

    @property
    def away_canonical(self) -> str:
        return normalize_team_name(self.away_team)


# ── Cele 20 de scenarii golden ──────────────────────────────────────────────
SCENARIOS: list[Scenario] = [
    Scenario(
        key="pl_favorite_home_strong_form",
        home_team="Manchester City", away_team="Nottingham Forest", league="Premier League",
        home_form=[(True, 3, 0), (False, 2, 1), (True, 4, 1), (True, 2, 0), (False, 3, 1)],
        away_form=[(True, 1, 2), (False, 0, 3), (True, 0, 0), (False, 1, 2), (True, 1, 1)],
        home_elo=1980, away_elo=1520,
        home_odds=1.25, draw_odds=6.5, away_odds=11.0,
    ),
    Scenario(
        key="pl_close_match",
        home_team="Arsenal", away_team="Chelsea", league="Premier League",
        home_form=[(True, 2, 1), (False, 1, 1), (True, 2, 0), (False, 2, 2), (True, 1, 0)],
        away_form=[(True, 2, 0), (False, 1, 1), (True, 1, 1), (False, 2, 1), (True, 0, 0)],
        home_elo=1870, away_elo=1830,
        home_odds=2.3, draw_odds=3.4, away_odds=3.1,
    ),
    Scenario(
        key="laliga_away_favorite",
        home_team="Getafe", away_team="Real Madrid", league="La Liga",
        home_form=[(True, 0, 1), (False, 1, 2), (True, 1, 1), (False, 0, 2), (True, 1, 0)],
        away_form=[(True, 3, 1), (False, 2, 0), (True, 4, 0), (False, 2, 1), (True, 3, 0)],
        home_elo=1560, away_elo=2010,
    ),
    Scenario(
        key="laliga_h2h_history",
        home_team="Barcelona", away_team="Atletico Madrid", league="La Liga",
        home_form=[(True, 3, 1), (False, 2, 1), (True, 2, 0), (False, 1, 1), (True, 3, 2)],
        away_form=[(True, 1, 0), (False, 1, 1), (True, 2, 0), (False, 0, 1), (True, 1, 0)],
        home_elo=1920, away_elo=1860,
        h2h=[(True, 2, 1), (False, 0, 0), (True, 3, 1), (False, 1, 2)],
    ),
    Scenario(
        key="seriea_defensive_battle",
        home_team="Juventus", away_team="Inter Milan", league="Serie A",
        home_form=[(True, 1, 0), (False, 0, 0), (True, 1, 1), (False, 1, 0), (True, 0, 0)],
        away_form=[(True, 1, 0), (False, 0, 0), (True, 2, 1), (False, 1, 1), (True, 1, 0)],
        home_elo=1880, away_elo=1900,
    ),
    Scenario(
        key="seriea_high_scoring",
        home_team="Atalanta", away_team="Napoli", league="Serie A",
        home_form=[(True, 3, 2), (False, 2, 2), (True, 4, 1), (False, 3, 3), (True, 2, 1)],
        away_form=[(True, 2, 1), (False, 3, 2), (True, 3, 0), (False, 1, 2), (True, 4, 2)],
        home_elo=1830, away_elo=1870,
    ),
    Scenario(
        key="bundesliga_favorite_home",
        home_team="Bayern Munich", away_team="Union Berlin", league="Bundesliga",
        home_form=[(True, 4, 0), (False, 3, 1), (True, 3, 0), (True, 5, 1), (False, 2, 0)],
        away_form=[(True, 1, 1), (False, 0, 2), (True, 1, 0), (False, 0, 1), (True, 2, 2)],
        home_elo=2020, away_elo=1580,
    ),
    Scenario(
        key="bundesliga_conflicting_signals",
        home_team="Bayer Leverkusen", away_team="VfL Wolfsburg", league="Bundesliga",
        home_form=[(True, 0, 1), (False, 1, 2), (True, 1, 1), (False, 0, 2), (True, 1, 1)],
        away_form=[(True, 2, 0), (False, 1, 0), (True, 3, 1), (False, 2, 1), (True, 1, 0)],
        home_elo=1900, away_elo=1620,  # ELO mare, forma slaba - semnale contradictorii
    ),
    Scenario(
        key="ligue1_close_match",
        home_team="Marseille", away_team="Lyon", league="Ligue 1",
        home_form=[(True, 1, 1), (False, 2, 1), (True, 2, 2), (False, 1, 0), (True, 1, 1)],
        away_form=[(True, 2, 1), (False, 1, 1), (True, 1, 0), (False, 2, 2), (True, 0, 0)],
        home_elo=1780, away_elo=1770,
    ),
    Scenario(
        key="ligue1_away_favorite",
        home_team="Le Havre", away_team="Paris Saint-Germain", league="Ligue 1",
        home_form=[(True, 0, 2), (False, 1, 3), (True, 1, 1), (False, 0, 2), (True, 0, 1)],
        away_form=[(True, 4, 0), (False, 3, 1), (True, 5, 0), (False, 2, 0), (True, 3, 1)],
        home_elo=1500, away_elo=2050,
    ),
    Scenario(
        key="ucl_giant_vs_underdog",
        home_team="Real Madrid", away_team="Sheriff Tiraspol", league="Champions League",
        home_form=[(True, 4, 1), (False, 3, 0), (True, 5, 1), (False, 2, 1), (True, 3, 0)],
        away_form=[(True, 1, 2), (False, 0, 3), (True, 1, 1), (False, 0, 4), (True, 2, 2)],
        home_elo=2010, away_elo=1400,
        home_odds=1.10, draw_odds=9.0, away_odds=17.0,
    ),
    Scenario(
        key="ucl_evenly_matched",
        home_team="Manchester City", away_team="Bayern Munich", league="Champions League",
        home_form=[(True, 3, 1), (False, 2, 1), (True, 2, 0), (False, 1, 1), (True, 3, 2)],
        away_form=[(True, 3, 0), (False, 2, 1), (True, 4, 1), (False, 1, 1), (True, 2, 0)],
        home_elo=1980, away_elo=2020,
        home_odds=2.1, draw_odds=3.6, away_odds=3.3,
    ),
    Scenario(
        key="europa_league_mid_table",
        home_team="Villarreal", away_team="Rangers", league="Europa League",
        home_form=[(True, 2, 1), (False, 1, 1), (True, 1, 0), (False, 2, 2), (True, 1, 1)],
        away_form=[(True, 1, 1), (False, 0, 1), (True, 2, 1), (False, 1, 2), (True, 1, 0)],
        home_elo=1750, away_elo=1690,
    ),
    Scenario(
        key="superliga_home_favorite",
        home_team="CFR Cluj", away_team="Petrolul Ploiești", league="Romania SuperLiga",
        home_form=[(True, 2, 0), (False, 1, 1), (True, 3, 1), (False, 2, 1), (True, 1, 0)],
        away_form=[(True, 1, 1), (False, 0, 2), (True, 1, 2), (False, 0, 1), (True, 2, 2)],
        home_elo=1650, away_elo=1500,
    ),
    Scenario(
        key="superliga_h2h_history",
        home_team="FCSB", away_team="Universitatea Craiova", league="Romania SuperLiga",
        home_form=[(True, 2, 1), (False, 1, 1), (True, 1, 0), (False, 2, 1), (True, 1, 1)],
        away_form=[(True, 1, 0), (False, 1, 2), (True, 2, 1), (False, 0, 0), (True, 1, 1)],
        home_elo=1620, away_elo=1590,
        h2h=[(True, 1, 1), (False, 0, 1), (True, 2, 0)],
    ),
    Scenario(
        key="mls_close_match",
        home_team="LA Galaxy", away_team="Seattle Sounders", league="MLS",
        home_form=[(True, 2, 1), (False, 1, 2), (True, 1, 1), (False, 2, 1), (True, 1, 0)],
        away_form=[(True, 1, 1), (False, 2, 2), (True, 2, 1), (False, 1, 1), (True, 1, 2)],
        home_elo=1600, away_elo=1610,
    ),
    Scenario(
        key="worldcup_neutral_venue",
        home_team="France", away_team="Brazil", league="World Cup 2026",
        home_form=[(True, 2, 0), (False, 1, 1), (True, 2, 1), (False, 3, 1), (True, 1, 0)],
        away_form=[(True, 2, 1), (False, 2, 0), (True, 1, 1), (False, 3, 2), (True, 2, 0)],
        home_elo=2050, away_elo=2080,
    ),
    Scenario(
        key="elo_only_no_recent_form",
        home_team="Sporting CP", away_team="Benfica", league="Ligue 1",
        home_form=[], away_form=[],
        home_elo=1780, away_elo=1810,  # doar ELO — fara meciuri recente in DB
    ),
    Scenario(
        key="neutral_defaults_unknown_teams",
        home_team="Zorya Luhansk", away_team="Vorskla Poltava", league="Ligue 1",
        home_form=[], away_form=[],
        home_elo=None, away_elo=None,  # complet necunoscute — nici formă, nici ELO
    ),
    Scenario(
        key="mixed_one_team_elo_only",
        home_team="Slavia Prague", away_team="Fenerbahce", league="Europa League",
        home_form=[(True, 2, 1), (False, 1, 0), (True, 3, 1), (False, 1, 1), (True, 2, 0)],
        away_form=[],  # doar ELO pentru echipa oaspete
        home_elo=1700, away_elo=1820,
    ),
]

assert len(SCENARIOS) == 20, f"Golden dataset trebuie sa aiba exact 20 de meciuri, are {len(SCENARIOS)}"
assert len({s.key for s in SCENARIOS}) == 20, "Chei de scenariu duplicate"


# ── Harness — ruleaza evaluate_match() REAL, complet mock-uit, fara retea ──

def _mocked_engine_context(scenario: Scenario):
    """Context manager care patch-uieste TOATE dependintele externe ale
    evaluate_match() direct pe namespace-ul modulului `oracle_engine`
    (exact tiparul din test_oracle_engine_db_first_*.py) si intoarce o
    instanta gata de folosit, construita prin __new__ (ocoleste __init__,
    care ar declansa un apel de retea real prin FootballOracleAPI())."""
    import oracle_engine as oe

    home_c, away_c = scenario.home_canonical, scenario.away_canonical

    home_rows = [_form_row(home_c, is_home, gf, ga) for is_home, gf, ga in scenario.home_form]
    away_rows = [_form_row(away_c, is_home, gf, ga) for is_home, gf, ga in scenario.away_form]
    h2h_rows = [_h2h_row(home_c, away_c, was_home, gf, ga) for was_home, gf, ga in scenario.h2h]

    def _recent_results(canonical, league, last_n):
        if canonical == home_c:
            return home_rows
        if canonical == away_c:
            return away_rows
        return []

    def _elo(canonical):
        if canonical == home_c:
            return scenario.home_elo
        if canonical == away_c:
            return scenario.away_elo
        return None

    fake_sb = mock.Mock()
    fake_sb.get_team_recent_results.side_effect = _recent_results
    fake_sb.get_team_recent_shots.return_value = []
    fake_sb.get_team_recent_match_events.return_value = []

    stack = contextlib.ExitStack()
    stack.enter_context(mock.patch.object(oe, "sb", fake_sb))
    stack.enter_context(mock.patch.object(oe, "DB_QUERIES_MODULE_AVAILABLE", True))
    stack.enter_context(mock.patch.object(oe, "SUPABASE_MODULE_AVAILABLE", True))
    stack.enter_context(mock.patch.object(oe, "FLASHSCORE_TEAM_DNA_AVAILABLE", False))
    stack.enter_context(mock.patch.object(oe, "get_latest_team_elo", side_effect=_elo))
    stack.enter_context(mock.patch.object(oe, "get_national_team_elo", return_value=None))
    stack.enter_context(mock.patch.object(oe, "get_h2h_from_history", return_value=h2h_rows))
    stack.enter_context(mock.patch.object(oe, "get_freelf_h2h_snapshot", return_value=None))
    stack.enter_context(mock.patch.object(oe, "get_h2h_from_odds_recent", return_value=[]))
    stack.enter_context(mock.patch.object(oe, "get_team_form_freelf_snapshot", return_value=None))
    stack.enter_context(mock.patch.object(oe, "get_team_recent_form_oddsapi", return_value=[]))
    stack.enter_context(mock.patch.object(oe, "get_team_form_footballdata", return_value=None))
    stack.enter_context(mock.patch.object(oe, "get_team_stats_tsdb", return_value=[]))
    stack.enter_context(mock.patch.object(oe, "get_team_health", return_value=None))
    stack.enter_context(mock.patch.object(oe, "get_weather_forecast", return_value=None))
    stack.enter_context(mock.patch.object(oe, "_save_json"))  # nu scrie predictions/*.json
    return stack, oe


def build_engine(scenario: Scenario):
    """Instanta FootballOracleEngine gata pentru evaluate_match(), ocolind
    __init__ (evita orice apel de retea real)."""
    import oracle_engine as oe
    import copy

    eng = oe.FootballOracleEngine.__new__(oe.FootballOracleEngine)
    eng.weights = copy.deepcopy(oe.DEFAULT_WEIGHTS)
    eng.config = copy.deepcopy(oe.DEFAULT_CONFIG)
    eng.api = None
    eng.ml = None
    eng.injury_manager = None
    eng.use_supabase = False
    eng.cache = None
    return eng


def match_dict(scenario: Scenario) -> dict:
    d = {
        "fixture_id": scenario.key, "home_team": scenario.home_team, "away_team": scenario.away_team,
        "league": scenario.league, "kickoff_date": scenario.kickoff_date,
        "kickoff_utc": f"{scenario.kickoff_date}T18:00:00Z", "season": 2026,
    }
    if scenario.home_odds is not None:
        d["home_odds"] = scenario.home_odds
        d["draw_odds"] = scenario.draw_odds
        d["away_odds"] = scenario.away_odds
        d["odds_source"] = "golden-fixture"
    return d


def run_scenario(scenario: Scenario):
    """Ruleaza evaluate_match() real pentru un scenariu, complet mock-uit.
    Intoarce obiectul MatchPrediction complet."""
    stack, oe = _mocked_engine_context(scenario)
    with stack:
        eng = build_engine(scenario)
        pred = eng.evaluate_match(match_dict(scenario))
    assert pred is not None, f"evaluate_match() a intors None pentru scenariul {scenario.key!r}"
    return pred


def snapshot_fields(pred) -> dict:
    """Cele 5 campuri cerute explicit pentru snapshot-ul golden — home_xg,
    away_xg, ph, pd, pa (Punctul 2 al EPIC-ului, 2026-08-03)."""
    return {
        "home_xg": pred.home_xg,
        "away_xg": pred.away_xg,
        "ph": pred.prob_home_win,
        "pd": pred.prob_draw,
        "pa": pred.prob_away_win,
    }
