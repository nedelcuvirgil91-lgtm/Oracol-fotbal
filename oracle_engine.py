"""
================================================================================
FOOTBALL ORACLE — Core Execution Engine
================================================================================
Module  : oracle_engine.py
Purpose : Mathematical heart of the platform.  Combines API data with
          Poisson-based match modelling, xG calibration, value-bet detection,
          and portfolio logging.  Zero external database — Pandas + JSON/CSV.
Depends : oracle_api.py  (FootballOracleAPI)
          numpy, scipy, pandas  (pip install numpy scipy pandas)
Author  : Football Oracle — Private Single-User Build
================================================================================
"""

from __future__ import annotations

import csv
import json
import logging
import math
import os
import sys
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import poisson

# ── Local module ──────────────────────────────────────────────────────────────
# oracle_api.py must be in the same directory (or on PYTHONPATH)
try:
    from oracle_api import FootballOracleAPI
except ModuleNotFoundError:
    print("[FATAL] oracle_api.py not found. Place it in the same directory.")
    sys.exit(1)

# ─────────────────────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(levelname)s]  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("FootballOracle.Engine")

# ─────────────────────────────────────────────────────────────────────────────
# FILE PATHS  (relative to oracle_engine.py location)
# ─────────────────────────────────────────────────────────────────────────────
BASE_DIR       = Path(__file__).parent
CONFIG_PATH    = BASE_DIR / "config.json"
WEIGHTS_PATH   = BASE_DIR / "weights.json"
PORTFOLIO_PATH = BASE_DIR / "portfolio.csv"
CACHE_DIR      = BASE_DIR / "cache"
CACHE_DIR.mkdir(exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# DEFAULT CONFIG & WEIGHTS  (written to disk if files don't exist)
# ─────────────────────────────────────────────────────────────────────────────
DEFAULT_CONFIG: dict[str, Any] = {
    "value_bet_threshold_pct": 5.0,       # minimum edge % to flag as value
    "max_goals_poisson":       8,          # Poisson matrix dimension (0-N goals)
    "last_n_fixtures":         5,          # how many recent matches to analyse
    "stake_default":           10.0,       # default stake in portfolio logger (€)
    "kelly_fraction":          0.25,       # fractional Kelly for stake sizing
    "weather_xg_penalty":      0.08,       # xG reduction per team in bad weather
    "bad_weather_keywords": [
        "heavy rain", "torrential", "blizzard", "heavy snow",
        "thunderstorm", "sleet", "freezing"
    ],
}

DEFAULT_WEIGHTS: dict[str, Any] = {
    # --- Form/DNA rating building blocks ---
    "goals_weight":      0.45,   # weight of goals scored in offensive rating
    "shots_ot_weight":   0.30,   # weight of shots on target
    "possession_weight": 0.25,   # weight of possession %

    # --- xG calibration multipliers ---
    "form_weight":       0.60,   # how much recent form influences final xG
    "dna_weight":        0.40,   # how much season-long DNA influences final xG

    # --- League baseline xG (average goals/game in various leagues) ---
    "league_baselines": {
        "39":  1.35,    # Premier League
        "140": 1.20,    # La Liga
        "135": 1.25,    # Serie A
        "78":  1.40,    # Bundesliga
        "61":  1.30,    # Ligue 1
        "283": 1.15,    # Romania SuperLiga
        "default": 1.25
    },

    # --- Defensive rating normalisation cap ---
    "defensive_cap":     2.5,    # max defensive rating before capping
    "offensive_cap":     3.5,    # max offensive rating
}


def _load_json(path: Path, default: dict) -> dict:
    """Load a JSON file; write and return the default if it doesn't exist."""
    if not path.exists():
        logger.warning("'%s' not found — creating with defaults.", path.name)
        path.write_text(json.dumps(default, indent=4), encoding="utf-8")
        return default
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        logger.info("Loaded '%s'.", path.name)
        return data
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Failed to read '%s': %s — using defaults.", path.name, exc)
        return default


# ─────────────────────────────────────────────────────────────────────────────
# DATA CLASSES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TeamProfile:
    """Computed offensive/defensive DNA for one team."""
    team_id:           int
    matches_analysed:  int
    avg_goals_for:     float
    avg_goals_against: float
    avg_shots_ot:      float
    avg_possession:    float
    offensive_rating:  float          # composite 0-3.5
    defensive_rating:  float          # composite 0-2.5  (lower = better defence)
    form_results:      list[str]      # ["W","D","L","W","W"]
    form_score:        float          # 0-1  (1 = perfect form)

    def __str__(self) -> str:
        form_str = " ".join(self.form_results) or "N/A"
        return (
            f"OFF={self.offensive_rating:.3f}  DEF={self.defensive_rating:.3f}  "
            f"Form={form_str}  FormScore={self.form_score:.2f}  "
            f"AvgGF={self.avg_goals_for:.2f}  AvgGA={self.avg_goals_against:.2f}"
        )


@dataclass
class MatchPrediction:
    """Full probabilistic output for one fixture."""
    fixture_id:       int
    home_team_id:     int
    away_team_id:     int
    league_id:        int
    home_xg:          float
    away_xg:          float

    # Poisson probabilities
    prob_home_win:    float
    prob_draw:        float
    prob_away_win:    float

    # Score matrix top picks
    top_scores:       list[tuple[int, int, float]]   # [(hg, ag, prob%), …]

    # Bookmaker odds
    bk_home_odds:     float
    bk_draw_odds:     float
    bk_away_odds:     float
    bookmaker_name:   str

    # Implied probabilities from odds
    impl_home_pct:    float
    impl_draw_pct:    float
    impl_away_pct:    float

    # Edge analysis
    edge_home_pct:    float
    edge_draw_pct:    float
    edge_away_pct:    float

    # Value bets flagged
    value_bets:       list[dict]     # [{market, selection, edge_pct, rating}]

    # Weather info
    weather_applied:  bool
    weather_note:     str

    # Kelly stake suggestions (based on config default stake)
    kelly_stakes:     dict[str, float]


@dataclass
class BetLogEntry:
    date:       str
    fixture_id: int
    match:      str
    market:     str
    selection:  str
    odds:       float
    stake:      float
    result:     str    # "W", "L", "V" (void), "" (pending)
    pnl:        float


# ─────────────────────────────────────────────────────────────────────────────
# ENGINE
# ─────────────────────────────────────────────────────────────────────────────

class FootballOracleEngine:
    """
    Core execution engine for Football Oracle.

    Workflow per match:
        api data → Team DNA profiles → xG calibration →
        Poisson model → value-bet detection → portfolio logging
    """

    def __init__(self) -> None:
        self.api     = FootballOracleAPI()
        self.config  = _load_json(CONFIG_PATH,  DEFAULT_CONFIG)
        self.weights = _load_json(WEIGHTS_PATH, DEFAULT_WEIGHTS)
        logger.info("FootballOracleEngine ready.")

    # ══════════════════════════════════════════════════════════════════════
    # 1. TEAM DNA & FORM ANALYSER
    # ══════════════════════════════════════════════════════════════════════

    def _build_team_profile(
        self, team_id: int, last_n: int = 5
    ) -> TeamProfile | None:
        """
        Fetch the last *last_n* fixtures for a team and compute
        offensive rating, defensive rating, and form score.
        """
        raw = self.api.get_last_fixtures_stats(team_id=team_id, last_n=last_n)
        if not raw:
            logger.warning("team_id=%d — no stat data, cannot build profile.", team_id)
            return None

        w = self.weights
        g_w   = w["goals_weight"]
        sot_w = w["shots_ot_weight"]
        pos_w = w["possession_weight"]
        o_cap = w["offensive_cap"]
        d_cap = w["defensive_cap"]

        goals_for_list:     list[float] = []
        goals_against_list: list[float] = []
        shots_ot_list:      list[float] = []
        possession_list:    list[float] = []
        results:            list[str]   = []

        for item in raw:
            meta  = item["fixture_meta"]
            stats = item["team_stats"]

            goals_for_list.append(float(meta["goals_for"]))
            goals_against_list.append(float(meta["goals_against"]))
            shots_ot_list.append(stats["shots_on_goal"])
            possession_list.append(stats["possession_pct"])
            results.append(meta["result"])

        n = len(raw)

        avg_gf  = sum(goals_for_list)     / n
        avg_ga  = sum(goals_against_list) / n
        avg_sot = sum(shots_ot_list)      / n
        avg_pos = sum(possession_list)    / n

        # ── Offensive rating: weighted composite, normalised ──────────────
        # Goals component: goals/game normalised to a 0-1.5 scale (cap 3)
        g_norm  = min(avg_gf / 2.0, 1.0) * 1.5
        # Shots on target: normalised (avg ~4-5 in top leagues)
        sot_norm = min(avg_sot / 6.0, 1.0) * 1.5
        # Possession: 50% = neutral, >60% positive, <40% negative
        pos_norm = ((avg_pos - 30.0) / 40.0) * 0.5   # maps [30,70]% → [0,0.5]
        pos_norm = max(0.0, min(pos_norm, 0.5))

        offensive_rating = min(
            g_norm * g_w + sot_norm * sot_w + pos_norm * pos_w + avg_gf * 0.2,
            o_cap,
        )

        # ── Defensive rating: lower is better ────────────────────────────
        # Scale: 0 = conceding nothing, 2.5 = conceding 2.5+/game
        defensive_rating = min(avg_ga * 1.0, d_cap)

        # ── Form score: W=1, D=0.4, L=0  weighted (recent = higher weight) ──
        result_vals = {"W": 1.0, "D": 0.4, "L": 0.0}
        weights_recent = [2 ** i for i in range(n)]   # [1,2,4,8,16] for n=5
        total_weight   = sum(weights_recent)
        form_score = sum(
            result_vals.get(r, 0.0) * weights_recent[i]
            for i, r in enumerate(results)
        ) / total_weight

        profile = TeamProfile(
            team_id=team_id,
            matches_analysed=n,
            avg_goals_for=round(avg_gf, 3),
            avg_goals_against=round(avg_ga, 3),
            avg_shots_ot=round(avg_sot, 3),
            avg_possession=round(avg_pos, 3),
            offensive_rating=round(offensive_rating, 4),
            defensive_rating=round(defensive_rating, 4),
            form_results=results,
            form_score=round(form_score, 4),
        )
        logger.info("team_id=%d profile built → %s", team_id, profile)
        return profile

    def analyze_teams(
        self,
        home_team_id: int,
        away_team_id: int,
        league_id: int,
    ) -> tuple[TeamProfile | None, TeamProfile | None, float, float]:
        """
        Build profiles for both teams and compute calibrated xG values.

        xG calibration formula
        ----------------------
        raw_xg  = (offensive_attack × opponent_defensive_vulnerability) × league_baseline
        final_xg = raw_xg × (form_weight × form_score_modifier + dna_weight)

        Returns
        -------
        (home_profile, away_profile, home_xg, away_xg)
        """
        logger.info(
            "=== Analysing teams: home=%d | away=%d | league=%d ===",
            home_team_id, away_team_id, league_id,
        )
        last_n = int(self.config.get("last_n_fixtures", 5))

        home_profile = self._build_team_profile(home_team_id, last_n)
        away_profile = self._build_team_profile(away_team_id, last_n)

        if home_profile is None or away_profile is None:
            logger.error("Cannot compute xG — one or both team profiles missing.")
            return home_profile, away_profile, 1.25, 1.00   # neutral fallback

        # League baseline xG
        baselines: dict = self.weights.get("league_baselines", {})
        baseline = float(
            baselines.get(str(league_id), baselines.get("default", 1.25))
        )
        logger.info("League %d baseline xG/team = %.2f", league_id, baseline)

        fw = float(self.weights["form_weight"])
        dw = float(self.weights["dna_weight"])

        # ── Home xG ──────────────────────────────────────────────────────
        # Attacking strength vs opponent's defensive vulnerability
        home_attack     = home_profile.offensive_rating
        away_def_vuln   = away_profile.defensive_rating   # higher = weaker defence

        # Defensive vulnerability modifier: 0 defence → multiplier 0.6, cap 2.5 → 1.4
        away_def_mod    = 0.6 + (away_def_vuln / DEFAULT_WEIGHTS["defensive_cap"]) * 0.8

        home_raw_xg     = home_attack * away_def_mod * baseline

        # Form modifier: form_score 1.0 → +20%, 0.0 → -20%
        home_form_mod   = 0.80 + home_profile.form_score * 0.40
        home_xg         = home_raw_xg * (fw * home_form_mod + dw)

        # Home advantage boost (+7%)
        home_xg        *= 1.07

        # ── Away xG ──────────────────────────────────────────────────────
        away_attack     = away_profile.offensive_rating
        home_def_vuln   = home_profile.defensive_rating
        home_def_mod    = 0.6 + (home_def_vuln / DEFAULT_WEIGHTS["defensive_cap"]) * 0.8

        away_raw_xg     = away_attack * home_def_mod * baseline
        away_form_mod   = 0.80 + away_profile.form_score * 0.40
        away_xg         = away_raw_xg * (fw * away_form_mod + dw)

        # Away penalty (-5%)
        away_xg        *= 0.95

        # Hard floor — avoid Poisson collapse near zero
        home_xg = max(home_xg, 0.20)
        away_xg = max(away_xg, 0.20)

        home_xg = round(home_xg, 4)
        away_xg = round(away_xg, 4)

        logger.info(
            "Calibrated xG → Home xG=%.3f | Away xG=%.3f", home_xg, away_xg
        )
        return home_profile, away_profile, home_xg, away_xg

    # ══════════════════════════════════════════════════════════════════════
    # 2. POISSON DISTRIBUTION ENGINE
    # ══════════════════════════════════════════════════════════════════════

    def _poisson_matrix(
        self, home_xg: float, away_xg: float
    ) -> tuple[float, float, float, list[tuple[int, int, float]]]:
        """
        Build a goals probability matrix using independent Poisson distributions.

        Returns
        -------
        (prob_home_win, prob_draw, prob_away_win, top_scores)
        top_scores: list of (home_goals, away_goals, probability%) sorted desc
        """
        max_g = int(self.config.get("max_goals_poisson", 8))
        matrix = np.zeros((max_g + 1, max_g + 1))

        for hg in range(max_g + 1):
            for ag in range(max_g + 1):
                matrix[hg, ag] = (
                    poisson.pmf(hg, home_xg) * poisson.pmf(ag, away_xg)
                )

        prob_home = float(np.sum(np.tril(matrix, -1)))   # hg > ag
        prob_draw = float(np.sum(np.diag(matrix)))
        prob_away = float(np.sum(np.triu(matrix,  1)))   # ag > hg

        # Top 6 most probable exact scores
        scores: list[tuple[int, int, float]] = []
        for hg in range(max_g + 1):
            for ag in range(max_g + 1):
                scores.append((hg, ag, round(matrix[hg, ag] * 100, 2)))
        scores.sort(key=lambda x: x[2], reverse=True)
        top_scores = scores[:6]

        logger.info(
            "Poisson → H=%.1f%%  D=%.1f%%  A=%.1f%%",
            prob_home * 100, prob_draw * 100, prob_away * 100,
        )
        return prob_home, prob_draw, prob_away, top_scores

    # ══════════════════════════════════════════════════════════════════════
    # 3. VALUE BET DETECTOR
    # ══════════════════════════════════════════════════════════════════════

    @staticmethod
    def _implied_prob(odds: float) -> float:
        """Convert decimal odds to raw implied probability (no margin removed)."""
        if odds <= 1.0:
            return 0.0
        return 1.0 / odds

    @staticmethod
    def _edge(model_prob: float, implied_prob: float) -> float:
        """Edge % = (model_prob - implied_prob) / implied_prob × 100."""
        if implied_prob <= 0:
            return 0.0
        return round((model_prob - implied_prob) / implied_prob * 100, 2)

    @staticmethod
    def _value_rating(edge_pct: float) -> str:
        """Classify edge magnitude into a qualitative tier."""
        if edge_pct >= 25:
            return "⚡ ELITE"
        if edge_pct >= 15:
            return "🔥 HIGH"
        if edge_pct >= 8:
            return "✅ MEDIUM"
        return "📌 LOW"

    def _kelly_stake(
        self, prob: float, odds: float, bankroll: float
    ) -> float:
        """
        Fractional Kelly criterion stake.
        kelly_f = fraction from config (default 0.25 = quarter-Kelly)
        """
        if odds <= 1.0 or prob <= 0:
            return 0.0
        b   = odds - 1.0          # net odds
        q   = 1.0 - prob
        kf  = (b * prob - q) / b  # full Kelly fraction
        kf  = max(kf, 0.0)
        fraction = float(self.config.get("kelly_fraction", 0.25))
        return round(bankroll * kf * fraction, 2)

    # ══════════════════════════════════════════════════════════════════════
    # 4. MASTER EVALUATE METHOD
    # ══════════════════════════════════════════════════════════════════════

        def evaluate_match(
        self,
        fixture_id:   int,
        home_team_id: int,
        away_team_id: int,
        league_id:    int,
        city:         str,
        match_name:   str = "",
        season:       int = 2026,
    ):

    ) -> MatchPrediction | None:
        """
        Full pre-match analysis pipeline for a single fixture.

        Steps
        -----
        1. Build team DNA + form profiles → calibrated xG
        2. Weather penalty (optional)
        3. Poisson distribution → H/D/A probabilities + score matrix
        4. Fetch bookmaker odds → implied probs
        5. Edge calculation → value bet detection
        6. Kelly stake sizing
        7. Return MatchPrediction dataclass

        Parameters
        ----------
        fixture_id   : API-Football fixture ID
        home_team_id : API-Football team ID
        away_team_id : API-Football team ID
        league_id    : API-Football league ID
        city         : Venue city name (for weather)
        match_name   : Human-readable "Home vs Away" string for reports
        """
        logger.info(
            "━━━ evaluate_match: fixture=%d | %s ━━━", fixture_id, match_name
        )

        # ── Step 1: Team DNA + xG ─────────────────────────────────────────
        home_profile, away_profile, home_xg, away_xg = self.analyze_teams(
            home_team_id, away_team_id, league_id
        )

        # ── Step 2: Weather penalty ───────────────────────────────────────
        weather_applied = False
        weather_note    = "No significant weather impact."
        penalty         = float(self.config.get("weather_xg_penalty", 0.08))
        bad_keywords    = [
            kw.lower()
            for kw in self.config.get("bad_weather_keywords", [])
        ]

        weather = self.api.get_weather_for_venue(city=city)
        if weather:
            condition = weather.get("condition", "").lower()
            precip_mm = float(weather.get("precip_mm", 0))
            wind_kph  = float(weather.get("wind_kph", 0))

            is_bad = (
                any(kw in condition for kw in bad_keywords)
                or precip_mm > 10
                or wind_kph > 60
            )
            if is_bad:
                home_xg         = round(home_xg * (1 - penalty), 4)
                away_xg         = round(away_xg * (1 - penalty), 4)
                weather_applied = True
                weather_note = (
                    f"⚠️  Severe weather detected: '{weather['condition']}' | "
                    f"Rain={precip_mm}mm | Wind={wind_kph}km/h — "
                    f"xG reduced by {penalty*100:.0f}% per team."
                )
                logger.warning("Weather penalty applied → %s", weather_note)
            else:
                weather_note = (
                    f"☀️  Conditions: '{weather.get('condition','N/A')}' | "
                    f"Temp={weather.get('temp_c','?')}°C | "
                    f"Rain={precip_mm}mm — No penalty."
                )
                logger.info("Weather OK — %s", weather_note)
        else:
            logger.warning(
                "Weather data unavailable for '%s'. Proceeding without penalty.", city
            )
            weather_note = "Weather data unavailable — no penalty applied."

        # ── Step 3: Poisson ───────────────────────────────────────────────
        prob_home, prob_draw, prob_away, top_scores = self._poisson_matrix(
            home_xg, away_xg
        )

        # ── Step 4: Bookmaker odds ────────────────────────────────────────
        odds_data = self.api.get_prematch_odds(fixture_id=fixture_id)

        if odds_data:
            bk_home  = float(odds_data.get("home", 0.0))
            bk_draw  = float(odds_data.get("draw", 0.0))
            bk_away  = float(odds_data.get("away", 0.0))
            bk_name  = odds_data.get("bookmaker", "Unknown")
        else:
            logger.warning(
                "No bookmaker odds for fixture %d — using neutral placeholders.",
                fixture_id,
            )
            bk_home, bk_draw, bk_away = 0.0, 0.0, 0.0
            bk_name = "N/A"

        # ── Step 5: Implied probs & Edge ─────────────────────────────────
        impl_home = self._implied_prob(bk_home)
        impl_draw = self._implied_prob(bk_draw)
        impl_away = self._implied_prob(bk_away)

        edge_home = self._edge(prob_home, impl_home) if bk_home > 1.0 else 0.0
        edge_draw = self._edge(prob_draw, impl_draw) if bk_draw > 1.0 else 0.0
        edge_away = self._edge(prob_away, impl_away) if bk_away > 1.0 else 0.0

        threshold = float(self.config.get("value_bet_threshold_pct", 5.0))
        value_bets: list[dict] = []

        candidates = [
            ("1X2", "Home Win",  edge_home, prob_home, bk_home),
            ("1X2", "Draw",      edge_draw, prob_draw, bk_draw),
            ("1X2", "Away Win",  edge_away, prob_away, bk_away),
        ]
        for market, selection, edge_pct, model_prob, bk_odds in candidates:
            if edge_pct >= threshold:
                value_bets.append({
                    "market":    market,
                    "selection": selection,
                    "edge_pct":  edge_pct,
                    "rating":    self._value_rating(edge_pct),
                    "model_prob_pct": round(model_prob * 100, 2),
                    "bk_odds":   bk_odds,
                })
                logger.info(
                    "VALUE BET FOUND → %s | %s | Edge=%.1f%% | Rating=%s",
                    selection, market, edge_pct, self._value_rating(edge_pct),
                )

        if not value_bets:
            logger.info(
                "No value bets detected above %.1f%% threshold.", threshold
            )

        # ── Step 6: Kelly stakes ──────────────────────────────────────────
        bankroll = float(self.config.get("stake_default", 10.0))
        kelly_stakes: dict[str, float] = {}
        if bk_home > 1.0:
            kelly_stakes["Home Win"] = self._kelly_stake(prob_home, bk_home, bankroll)
        if bk_draw > 1.0:
            kelly_stakes["Draw"]     = self._kelly_stake(prob_draw, bk_draw, bankroll)
        if bk_away > 1.0:
            kelly_stakes["Away Win"] = self._kelly_stake(prob_away, bk_away, bankroll)

        # ── Assemble prediction ───────────────────────────────────────────
        prediction = MatchPrediction(
            fixture_id      = fixture_id,
            home_team_id    = home_team_id,
            away_team_id    = away_team_id,
            league_id       = league_id,
            home_xg         = home_xg,
            away_xg         = away_xg,
            prob_home_win   = round(prob_home, 4),
            prob_draw       = round(prob_draw, 4),
            prob_away_win   = round(prob_away, 4),
            top_scores      = top_scores,
            bk_home_odds    = bk_home,
            bk_draw_odds    = bk_draw,
            bk_away_odds    = bk_away,
            bookmaker_name  = bk_name,
            impl_home_pct   = round(impl_home * 100, 2),
            impl_draw_pct   = round(impl_draw * 100, 2),
            impl_away_pct   = round(impl_away * 100, 2),
            edge_home_pct   = edge_home,
            edge_draw_pct   = edge_draw,
            edge_away_pct   = edge_away,
            value_bets      = value_bets,
            weather_applied = weather_applied,
            weather_note    = weather_note,
            kelly_stakes    = kelly_stakes,
        )
        logger.info("MatchPrediction assembled for fixture_id=%d.", fixture_id)
        return prediction

    # ══════════════════════════════════════════════════════════════════════
    # 5. PORTFOLIO LOGGER
    # ══════════════════════════════════════════════════════════════════════

    PORTFOLIO_HEADERS = [
        "Date", "FixtureID", "Match", "Market",
        "Selection", "Odds", "Stake", "Result", "PnL",
    ]

    def log_bet(
        self,
        fixture_id: int,
        match_name:  str,
        market:      str,
        selection:   str,
        odds:        float,
        stake:       float,
        result:      str = "",   # "W", "L", "V" (void), "" (pending)
    ) -> BetLogEntry:
        """
        Append one bet record to portfolio.csv.

        PnL calculation
        ---------------
        W  → stake × (odds - 1)
        L  → -stake
        V  → 0.0  (void/refund)
        "" → 0.0  (pending — will be updated later)

        Returns the BetLogEntry that was written.
        """
        result = result.upper().strip()
        if result == "W":
            pnl = round(stake * (odds - 1), 2)
        elif result == "L":
            pnl = round(-stake, 2)
        else:
            pnl = 0.0

        entry = BetLogEntry(
            date       = datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
            fixture_id = fixture_id,
            match      = match_name,
            market     = market,
            selection  = selection,
            odds       = odds,
            stake      = stake,
            result     = result if result else "PENDING",
            pnl        = pnl,
        )

        file_exists = PORTFOLIO_PATH.exists()
        with PORTFOLIO_PATH.open("a", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=self.PORTFOLIO_HEADERS)
            if not file_exists:
                writer.writeheader()
                logger.info("Created portfolio.csv with headers.")
            writer.writerow(
                {
                    "Date":      entry.date,
                    "FixtureID": entry.fixture_id,
                    "Match":     entry.match,
                    "Market":    entry.market,
                    "Selection": entry.selection,
                    "Odds":      entry.odds,
                    "Stake":     entry.stake,
                    "Result":    entry.result,
                    "PnL":       entry.pnl,
                }
            )
        logger.info(
            "Portfolio logged → %s | %s @ %.2f | Stake=%.2f | Result=%s | PnL=%.2f",
            match_name, selection, odds, stake, entry.result, pnl,
        )
        return entry

    # ══════════════════════════════════════════════════════════════════════
    # 6. PORTFOLIO SUMMARY (bonus utility)
    # ══════════════════════════════════════════════════════════════════════

    def portfolio_summary(self) -> pd.DataFrame | None:
        """
        Load portfolio.csv into a Pandas DataFrame and print a P&L summary.
        Returns the DataFrame for further processing.
        """
        if not PORTFOLIO_PATH.exists():
            logger.warning("portfolio.csv does not exist yet.")
            return None

        df = pd.read_csv(PORTFOLIO_PATH)
        settled = df[df["Result"].isin(["W", "L"])]

        total_bets   = len(settled)
        total_stake  = settled["Stake"].sum()
        total_pnl    = settled["PnL"].sum()
        roi          = (total_pnl / total_stake * 100) if total_stake > 0 else 0.0
        wins         = len(settled[settled["Result"] == "W"])
        win_rate     = (wins / total_bets * 100) if total_bets > 0 else 0.0

        print("\n" + "─" * 50)
        print("  📊  PORTFOLIO SUMMARY")
        print("─" * 50)
        print(f"  Settled Bets : {total_bets}")
        print(f"  Win Rate     : {win_rate:.1f}%")
        print(f"  Total Staked : €{total_stake:.2f}")
        print(f"  Net P&L      : €{total_pnl:+.2f}")
        print(f"  ROI          : {roi:+.1f}%")
        print("─" * 50 + "\n")

        return df


# ─────────────────────────────────────────────────────────────────────────────
# REPORT PRINTER
# ─────────────────────────────────────────────────────────────────────────────

def _print_prediction_report(
    pred: MatchPrediction,
    match_name: str,
    home_profile: TeamProfile | None,
    away_profile: TeamProfile | None,
) -> None:
    """Render a beautiful terminal prediction report."""

    W = 68   # total report width

    def _bar(prob: float, width: int = 20) -> str:
        filled = int(round(prob * width))
        return "█" * filled + "░" * (width - filled)

    def _odds_display(odds: float) -> str:
        return f"{odds:.2f}" if odds > 1.0 else "N/A "

    home_name, away_name = (
        (match_name.split(" vs ") + ["HOME", "AWAY"])[:2]
        if " vs " in match_name
        else ("HOME", "AWAY")
    )

    print()
    print("╔" + "═" * (W - 2) + "╗")
    print("║" + "  ⚽  FOOTBALL ORACLE — MATCH PREDICTION REPORT  ".center(W - 2) + "║")
    print("╠" + "═" * (W - 2) + "╣")

    # Match title
    title = f"  {match_name}"
    print("║" + title.ljust(W - 2) + "║")
    print("║" + f"  Fixture ID: {pred.fixture_id}   League ID: {pred.league_id}".ljust(W - 2) + "║")
    print("╠" + "═" * (W - 2) + "╣")

    # xG
    print("║" + "  EXPECTED GOALS (xG)".ljust(W - 2) + "║")
    print("║" + f"  {home_name:<20}  xG = {pred.home_xg:.3f}".ljust(W - 2) + "║")
    print("║" + f"  {away_name:<20}  xG = {pred.away_xg:.3f}".ljust(W - 2) + "║")
    print("╠" + "═" * (W - 2) + "╣")

    # Team DNA
    if home_profile:
        print("║" + "  HOME TEAM DNA".ljust(W - 2) + "║")
        print(
            "║"
            + f"  Form: {' '.join(home_profile.form_results):<12} "
              f"FormScore: {home_profile.form_score:.2f}  "
              f"OFF: {home_profile.offensive_rating:.3f}  "
              f"DEF: {home_profile.defensive_rating:.3f}".ljust(W - 3)
            + "║"
        )
        print(
            "║"
            + f"  Avg Goals: GF={home_profile.avg_goals_for:.2f}  "
              f"GA={home_profile.avg_goals_against:.2f}  "
              f"SoT={home_profile.avg_shots_ot:.1f}  "
              f"Poss={home_profile.avg_possession:.1f}%".ljust(W - 3)
            + "║"
        )
    if away_profile:
        print("║" + "  AWAY TEAM DNA".ljust(W - 2) + "║")
        print(
            "║"
            + f"  Form: {' '.join(away_profile.form_results):<12} "
              f"FormScore: {away_profile.form_score:.2f}  "
              f"OFF: {away_profile.offensive_rating:.3f}  "
              f"DEF: {away_profile.defensive_rating:.3f}".ljust(W - 3)
            + "║"
        )
        print(
            "║"
            + f"  Avg Goals: GF={away_profile.avg_goals_for:.2f}  "
              f"GA={away_profile.avg_goals_against:.2f}  "
              f"SoT={away_profile.avg_shots_ot:.1f}  "
              f"Poss={away_profile.avg_possession:.1f}%".ljust(W - 3)
            + "║"
        )
    print("╠" + "═" * (W - 2) + "╣")

    # Poisson probabilities
    print("║" + "  POISSON PROBABILITY MODEL".ljust(W - 2) + "║")
    h_pct = pred.prob_home_win * 100
    d_pct = pred.prob_draw     * 100
    a_pct = pred.prob_away_win * 100
    print("║" + f"  Home Win  {_bar(pred.prob_home_win)}  {h_pct:5.1f}%".ljust(W - 2) + "║")
    print("║" + f"  Draw      {_bar(pred.prob_draw)}     {d_pct:5.1f}%".ljust(W - 2) + "║")
    print("║" + f"  Away Win  {_bar(pred.prob_away_win)}  {a_pct:5.1f}%".ljust(W - 2) + "║")

    # Top scores
    print("║" + "".ljust(W - 2) + "║")
    print("║" + "  TOP PREDICTED SCORES:".ljust(W - 2) + "║")
    score_line = "  "
    for hg, ag, prob in pred.top_scores[:6]:
        score_line += f"{hg}-{ag} ({prob:.1f}%)   "
    print("║" + score_line.ljust(W - 2) + "║")
    print("╠" + "═" * (W - 2) + "╣")

    # Bookmaker odds
    print("║" + f"  BOOKMAKER ODDS  ({pred.bookmaker_name})".ljust(W - 2) + "║")
    print(
        "║"
        + f"  Home: {_odds_display(pred.bk_home_odds)}  "
          f"Draw: {_odds_display(pred.bk_draw_odds)}  "
          f"Away: {_odds_display(pred.bk_away_odds)}".ljust(W - 2)
        + "║"
    )
    print("║" + "  Implied Probs:".ljust(W - 2) + "║")
    print(
        "║"
        + f"  Home: {pred.impl_home_pct:5.1f}%  "
          f"Draw: {pred.impl_draw_pct:5.1f}%  "
          f"Away: {pred.impl_away_pct:5.1f}%".ljust(W - 2)
        + "║"
    )
    print("╠" + "═" * (W - 2) + "╣")

    # Edge analysis
    print("║" + "  EDGE ANALYSIS (Model vs Market)".ljust(W - 2) + "║")

    def _edge_line(label: str, model_pct: float, impl_pct: float, edge: float) -> str:
        sign = "+" if edge >= 0 else ""
        return (
            f"  {label:<10} Model={model_pct:5.1f}%  "
            f"Market={impl_pct:5.1f}%  "
            f"Edge={sign}{edge:+.1f}%"
        )

    print("║" + _edge_line("Home Win", h_pct, pred.impl_home_pct, pred.edge_home_pct).ljust(W - 2) + "║")
    print("║" + _edge_line("Draw",     d_pct, pred.impl_draw_pct, pred.edge_draw_pct).ljust(W - 2) + "║")
    print("║" + _edge_line("Away Win", a_pct, pred.impl_away_pct, pred.edge_away_pct).ljust(W - 2) + "║")
    print("╠" + "═" * (W - 2) + "╣")

    # Value bets
    if pred.value_bets:
        print("║" + "  🎯  VALUE BETS DETECTED".ljust(W - 2) + "║")
        for vb in pred.value_bets:
            line = (
                f"  {vb['rating']}  {vb['selection']:<12}  "
                f"Odds={vb['bk_odds']:.2f}  "
                f"Edge={vb['edge_pct']:+.1f}%  "
                f"Model={vb['model_prob_pct']:.1f}%"
            )
            print("║" + line.ljust(W - 2) + "║")
        # Kelly stakes
        if pred.kelly_stakes:
            print("║" + "  Kelly Stake Suggestions (fractional):".ljust(W - 2) + "║")
            for sel, stk in pred.kelly_stakes.items():
                print("║" + f"    {sel:<14}  €{stk:.2f}".ljust(W - 2) + "║")
    else:
        print("║" + "  ⚪  No value bets above threshold — skip this match.".ljust(W - 2) + "║")
    print("╠" + "═" * (W - 2) + "╣")

    # Weather
    print("║" + "  WEATHER ASSESSMENT".ljust(W - 2) + "║")
    for chunk in [pred.weather_note[i:i+W-4] for i in range(0, len(pred.weather_note), W-4)]:
        print("║" + f"  {chunk}".ljust(W - 2) + "║")

    print("╚" + "═" * (W - 2) + "╝")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# MOCK DATA HELPER  (for offline / quota-free testing)
# ─────────────────────────────────────────────────────────────────────────────

def _build_mock_prediction() -> tuple[MatchPrediction, TeamProfile, TeamProfile]:
    """
    Return a fully populated MatchPrediction and two TeamProfiles using
    realistic mock data — no API call required.
    Used in the __main__ demo block.
    """
    home_profile = TeamProfile(
        team_id=496,
        matches_analysed=5,
        avg_goals_for=1.80,
        avg_goals_against=0.80,
        avg_shots_ot=5.2,
        avg_possession=58.4,
        offensive_rating=2.341,
        defensive_rating=0.800,
        form_results=["W", "W", "D", "W", "L"],
        form_score=0.742,
    )
    away_profile = TeamProfile(
        team_id=489,
        matches_analysed=5,
        avg_goals_for=1.20,
        avg_goals_against=1.40,
        avg_shots_ot=3.8,
        avg_possession=47.1,
        offensive_rating=1.612,
        defensive_rating=1.400,
        form_results=["L", "D", "W", "L", "D"],
        form_score=0.323,
    )

    home_xg = 1.74
    away_xg = 1.02

    # Compute Poisson locally
    max_g = 8
    matrix = np.zeros((max_g + 1, max_g + 1))
    for hg in range(max_g + 1):
        for ag in range(max_g + 1):
            matrix[hg, ag] = poisson.pmf(hg, home_xg) * poisson.pmf(ag, away_xg)

    prob_home = float(np.sum(np.tril(matrix, -1)))
    prob_draw = float(np.sum(np.diag(matrix)))
    prob_away = float(np.sum(np.triu(matrix, 1)))

    scores = [
        (hg, ag, round(matrix[hg, ag] * 100, 2))
        for hg in range(max_g + 1)
        for ag in range(max_g + 1)
    ]
    scores.sort(key=lambda x: x[2], reverse=True)

    bk_home, bk_draw, bk_away = 2.10, 3.40, 3.70
    impl_home = 1 / bk_home
    impl_draw = 1 / bk_draw
    impl_away = 1 / bk_away

    def edge(mp, ip): return round((mp - ip) / ip * 100, 2)

    edge_h = edge(prob_home, impl_home)
    edge_d = edge(prob_draw, impl_draw)
    edge_a = edge(prob_away, impl_away)

    threshold = 5.0
    value_bets = []
    for sel, ep, mp, odds in [
        ("Home Win", edge_h, prob_home, bk_home),
        ("Draw",     edge_d, prob_draw, bk_draw),
        ("Away Win", edge_a, prob_away, bk_away),
    ]:
        if ep >= threshold:
            rating = "⚡ ELITE" if ep >= 25 else "🔥 HIGH" if ep >= 15 else "✅ MEDIUM" if ep >= 8 else "📌 LOW"
            value_bets.append(
                {"market": "1X2", "selection": sel, "edge_pct": ep,
                 "rating": rating, "model_prob_pct": round(mp * 100, 2),
                 "bk_odds": odds}
            )

    pred = MatchPrediction(
        fixture_id=1035042,
        home_team_id=496,
        away_team_id=489,
        league_id=135,
        home_xg=home_xg,
        away_xg=away_xg,
        prob_home_win=round(prob_home, 4),
        prob_draw=round(prob_draw, 4),
        prob_away_win=round(prob_away, 4),
        top_scores=scores[:6],
        bk_home_odds=bk_home,
        bk_draw_odds=bk_draw,
        bk_away_odds=bk_away,
        bookmaker_name="Bet365 (mock)",
        impl_home_pct=round(impl_home * 100, 2),
        impl_draw_pct=round(impl_draw * 100, 2),
        impl_away_pct=round(impl_away * 100, 2),
        edge_home_pct=edge_h,
        edge_draw_pct=edge_d,
        edge_away_pct=edge_a,
        value_bets=value_bets,
        weather_applied=False,
        weather_note="☀️  Conditions: 'Partly cloudy' | Temp=18°C | Rain=0.0mm — No penalty.",
        kelly_stakes={
            "Home Win": round(10.0 * max((bk_home - 1) * prob_home - (1 - prob_home), 0) / (bk_home - 1) * 0.25, 2),
        },
    )
    return pred, home_profile, away_profile


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":

    print("\n" + "=" * 68)
    print("  FOOTBALL ORACLE — Engine Smoke Test")
    print("=" * 68)

    engine = FootballOracleEngine()

    # ── LIVE mode (comment out if API quota is exhausted) ─────────────────
    LIVE_MODE = False   # ← set True to hit real API endpoints

    MATCH_NAME    = "Juventus vs Inter Milan"
    FIXTURE_ID    = 1035042   # Replace with a real upcoming fixture ID
    HOME_TEAM_ID  = 496       # Juventus
    AWAY_TEAM_ID  = 489       # Inter Milan
    LEAGUE_ID     = 135       # Serie A
    CITY          = "Turin"

    if LIVE_MODE:
        print("\n[MODE] LIVE — calling real API endpoints …\n")
        prediction = engine.evaluate_match(
            fixture_id   = FIXTURE_ID,
            home_team_id = HOME_TEAM_ID,
            away_team_id = AWAY_TEAM_ID,
            league_id    = LEAGUE_ID,
            city         = CITY,
            match_name   = MATCH_NAME,
        )
        # Rebuild profiles for report (already computed inside evaluate_match)
        home_p, away_p, _, _ = engine.analyze_teams(
            HOME_TEAM_ID, AWAY_TEAM_ID, LEAGUE_ID
        )
    else:
        print("\n[MODE] OFFLINE MOCK — using realistic pre-built data …\n")
        prediction, home_p, away_p = _build_mock_prediction()

    if prediction:
        _print_prediction_report(prediction, MATCH_NAME, home_p, away_p)

    # ── Portfolio logger demo ─────────────────────────────────────────────
    print("\n[DEMO] Logging a sample bet to portfolio.csv …")
    engine.log_bet(
        fixture_id = FIXTURE_ID,
        match_name  = MATCH_NAME,
        market     = "1X2",
        selection  = "Home Win",
        odds       = 2.10,
        stake      = 15.00,
        result     = "W",
    )
    engine.log_bet(
        fixture_id = FIXTURE_ID,
        match_name  = MATCH_NAME,
        market     = "1X2",
        selection  = "Away Win",
        odds       = 3.70,
        stake      = 5.00,
        result     = "L",
    )

    # ── Portfolio summary ─────────────────────────────────────────────────
    engine.portfolio_summary()

    print("=" * 68)
    print("  Engine smoke test complete.")
    print("=" * 68 + "\n")
