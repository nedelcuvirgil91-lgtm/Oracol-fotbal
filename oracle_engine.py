"""
================================================================================
FOOTBALL ORACLE — Core Execution Engine
================================================================================
Module  : oracle_engine.py
Season  : 2026  (World Cup 2026 compatible)
Purpose : Mathematical heart of the platform.  Combines API data with
          Poisson-based match modelling, xG calibration, value-bet detection,
          portfolio logging, and AUTO-RECALIBRATION (self-learning).
Depends : oracle_api.py  (FootballOracleAPI)
          pip install numpy scipy pandas
================================================================================
"""

from __future__ import annotations

import csv
import json
import logging
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import poisson

try:
    from oracle_api import FootballOracleAPI, DEFAULT_SEASON
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
# FILE PATHS
# ─────────────────────────────────────────────────────────────────────────────
BASE_DIR            = Path(__file__).parent
CONFIG_PATH         = BASE_DIR / "config.json"
WEIGHTS_PATH        = BASE_DIR / "weights.json"
PORTFOLIO_PATH      = BASE_DIR / "portfolio.csv"
PREDICTIONS_DIR     = BASE_DIR / "predictions"   # prediction cache (one JSON per fixture)
RECALIBRATION_LOG   = BASE_DIR / "recalibration_log.csv"

PREDICTIONS_DIR.mkdir(exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# DEFAULTS
# ─────────────────────────────────────────────────────────────────────────────
DEFAULT_CONFIG: dict[str, Any] = {
    "value_bet_threshold_pct": 5.0,
    "max_goals_poisson":       8,
    "last_n_fixtures":         5,
    "stake_default":           10.0,
    "kelly_fraction":          0.25,
    "weather_xg_penalty":      0.08,
    "default_season":          2026,
    "recalibration_learning_rate": 0.05,   # how aggressively weights shift per result
    "recalibration_max_delta":     0.15,   # maximum shift per update (safety cap)
    "bad_weather_keywords": [
        "heavy rain", "torrential", "blizzard", "heavy snow",
        "thunderstorm", "sleet", "freezing",
    ],
}

DEFAULT_WEIGHTS: dict[str, Any] = {
    # Form/DNA
    "goals_weight":      0.45,
    "shots_ot_weight":   0.30,
    "possession_weight": 0.25,
    "form_weight":       0.60,
    "dna_weight":        0.40,

    # League baselines — avg expected goals per team per game
    "league_baselines": {
        "1":   1.30,    # FIFA World Cup 2026
        "39":  1.35,    # Premier League
        "140": 1.20,    # La Liga
        "135": 1.25,    # Serie A
        "78":  1.40,    # Bundesliga
        "61":  1.30,    # Ligue 1
        "283": 1.15,    # Romania SuperLiga
        "88":  1.30,    # Eredivisie
        "94":  1.20,    # Primeira Liga
        "default": 1.25,
    },

    # Caps
    "defensive_cap": 2.5,
    "offensive_cap": 3.5,
}


def _load_json(path: Path, default: dict) -> dict:
    if not path.exists():
        logger.warning("'%s' not found — creating with defaults.", path.name)
        path.write_text(json.dumps(default, indent=4), encoding="utf-8")
        return dict(default)
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        logger.info("Loaded '%s'.", path.name)
        return data
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Failed to read '%s': %s — using defaults.", path.name, exc)
        return dict(default)


def _save_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=4), encoding="utf-8")
    logger.info("Saved '%s'.", path.name)


# ─────────────────────────────────────────────────────────────────────────────
# DATA CLASSES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TeamProfile:
    team_id:           int
    matches_analysed:  int
    avg_goals_for:     float
    avg_goals_against: float
    avg_shots_ot:      float
    avg_possession:    float
    offensive_rating:  float
    defensive_rating:  float
    form_results:      list[str]
    form_score:        float

    def __str__(self) -> str:
        return (
            f"OFF={self.offensive_rating:.3f}  DEF={self.defensive_rating:.3f}  "
            f"Form={' '.join(self.form_results)}  Score={self.form_score:.2f}"
        )


@dataclass
class MatchPrediction:
    fixture_id:      int
    home_team_id:    int
    away_team_id:    int
    league_id:       int
    season:          int
    home_xg:         float
    away_xg:         float
    prob_home_win:   float
    prob_draw:       float
    prob_away_win:   float
    top_scores:      list[tuple[int, int, float]]
    bk_home_odds:    float
    bk_draw_odds:    float
    bk_away_odds:    float
    bookmaker_name:  str
    impl_home_pct:   float
    impl_draw_pct:   float
    impl_away_pct:   float
    edge_home_pct:   float
    edge_draw_pct:   float
    edge_away_pct:   float
    value_bets:      list[dict]
    weather_applied: bool
    weather_note:    str
    kelly_stakes:    dict[str, float]


@dataclass
class BetLogEntry:
    date:       str
    fixture_id: int
    match:      str
    market:     str
    selection:  str
    odds:       float
    stake:      float
    result:     str
    pnl:        float


# ─────────────────────────────────────────────────────────────────────────────
# ENGINE
# ─────────────────────────────────────────────────────────────────────────────

class FootballOracleEngine:
    """
    Core execution engine — Football Oracle 2026.

    New in this version
    -------------------
    - season parameter throughout (default 2026)
    - World Cup 2026 league baselines
    - Prediction cache (predictions/<fixture_id>.json)
    - update_weights_from_result() — self-learning recalibration
    """

    def __init__(self) -> None:
        self.api     = FootballOracleAPI()
        self.config  = _load_json(CONFIG_PATH,  DEFAULT_CONFIG)
        self.weights = _load_json(WEIGHTS_PATH, DEFAULT_WEIGHTS)
        logger.info(
            "FootballOracleEngine ready — default season %d",
            self.config.get("default_season", 2026),
        )

    # ══════════════════════════════════════════════════════════════════════
    # INTERNAL UTILITIES
    # ══════════════════════════════════════════════════════════════════════

    def _current_season(self) -> int:
        return int(self.config.get("default_season", 2026))

    def _prediction_path(self, fixture_id: int) -> Path:
        return PREDICTIONS_DIR / f"{fixture_id}.json"

    def _save_prediction(self, pred: MatchPrediction) -> None:
        """Cache a prediction to disk for later recalibration lookup."""
        data = {
            "fixture_id":    pred.fixture_id,
            "home_team_id":  pred.home_team_id,
            "away_team_id":  pred.away_team_id,
            "league_id":     pred.league_id,
            "season":        pred.season,
            "home_xg":       pred.home_xg,
            "away_xg":       pred.away_xg,
            "prob_home_win": pred.prob_home_win,
            "prob_draw":     pred.prob_draw,
            "prob_away_win": pred.prob_away_win,
            "bookmaker":     pred.bookmaker_name,
            "bk_home":       pred.bk_home_odds,
            "bk_draw":       pred.bk_draw_odds,
            "bk_away":       pred.bk_away_odds,
            "saved_at":      datetime.utcnow().isoformat(),
        }
        _save_json(self._prediction_path(pred.fixture_id), data)
        logger.info("Prediction cached → predictions/%d.json", pred.fixture_id)

    def _load_prediction_cache(self, fixture_id: int) -> dict | None:
        path = self._prediction_path(fixture_id)
        if not path.exists():
            logger.warning("No cached prediction for fixture=%d.", fixture_id)
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Cannot load prediction cache for %d: %s", fixture_id, exc)
            return None

    # ══════════════════════════════════════════════════════════════════════
    # 1. TEAM DNA & FORM ANALYSER
    # ══════════════════════════════════════════════════════════════════════

    def _build_team_profile(
        self, team_id: int, last_n: int = 5, season: int | None = None
    ) -> TeamProfile | None:
        if season is None:
            season = self._current_season()

        raw = self.api.get_last_fixtures_stats(
            team_id=team_id, last_n=last_n, season=season
        )
        if not raw:
            logger.warning("team=%d — no data for season %d.", team_id, season)
            return None

        w     = self.weights
        o_cap = float(w.get("offensive_cap", 3.5))
        d_cap = float(w.get("defensive_cap", 2.5))

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

        n       = len(raw)
        avg_gf  = sum(goals_for_list)     / n
        avg_ga  = sum(goals_against_list) / n
        avg_sot = sum(shots_ot_list)      / n
        avg_pos = sum(possession_list)    / n

        g_norm   = min(avg_gf / 2.0, 1.0) * 1.5
        sot_norm = min(avg_sot / 6.0, 1.0) * 1.5
        pos_norm = max(0.0, min(((avg_pos - 30.0) / 40.0) * 0.5, 0.5))

        g_w   = float(w.get("goals_weight",      0.45))
        sot_w = float(w.get("shots_ot_weight",   0.30))
        pos_w = float(w.get("possession_weight", 0.25))

        offensive_rating = min(
            g_norm * g_w + sot_norm * sot_w + pos_norm * pos_w + avg_gf * 0.2,
            o_cap,
        )
        defensive_rating = min(avg_ga * 1.0, d_cap)

        result_vals     = {"W": 1.0, "D": 0.4, "L": 0.0}
        weights_recent  = [2 ** i for i in range(n)]
        total_weight    = sum(weights_recent)
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
        logger.info("team=%d profile → %s", team_id, profile)
        return profile

    def analyze_teams(
        self,
        home_team_id: int,
        away_team_id: int,
        league_id:    int,
        season:       int | None = None,
    ) -> tuple[TeamProfile | None, TeamProfile | None, float, float]:
        """
        Build DNA profiles for both teams and return calibrated xG values.
        """
        if season is None:
            season = self._current_season()

        logger.info(
            "=== analyze_teams home=%d away=%d league=%d season=%d ===",
            home_team_id, away_team_id, league_id, season,
        )
        last_n = int(self.config.get("last_n_fixtures", 5))

        home_p = self._build_team_profile(home_team_id, last_n, season)
        away_p = self._build_team_profile(away_team_id, last_n, season)

        if home_p is None or away_p is None:
            logger.error("Missing profile — using neutral xG fallback.")
            return home_p, away_p, 1.25, 1.00

        baselines = self.weights.get("league_baselines", {})
        baseline  = float(
            baselines.get(str(league_id), baselines.get("default", 1.25))
        )
        logger.info("league=%d baseline=%.2f", league_id, baseline)

        fw = float(self.weights.get("form_weight", 0.60))
        dw = float(self.weights.get("dna_weight",  0.40))
        d_cap = float(self.weights.get("defensive_cap", 2.5))

        # ── Home xG
        away_def_mod = 0.6 + (away_p.defensive_rating / d_cap) * 0.8
        home_raw_xg  = home_p.offensive_rating * away_def_mod * baseline
        home_form_mod = 0.80 + home_p.form_score * 0.40
        home_xg = home_raw_xg * (fw * home_form_mod + dw) * 1.07   # +7% home boost

        # ── Away xG
        home_def_mod = 0.6 + (home_p.defensive_rating / d_cap) * 0.8
        away_raw_xg  = away_p.offensive_rating * home_def_mod * baseline
        away_form_mod = 0.80 + away_p.form_score * 0.40
        away_xg = away_raw_xg * (fw * away_form_mod + dw) * 0.95   # -5% away penalty

        home_xg = round(max(home_xg, 0.20), 4)
        away_xg = round(max(away_xg, 0.20), 4)

        logger.info("xG → home=%.3f  away=%.3f", home_xg, away_xg)
        return home_p, away_p, home_xg, away_xg

    # ══════════════════════════════════════════════════════════════════════
    # 2. POISSON ENGINE
    # ══════════════════════════════════════════════════════════════════════

    def _poisson_matrix(
        self, home_xg: float, away_xg: float
    ) -> tuple[float, float, float, list[tuple[int, int, float]]]:
        max_g  = int(self.config.get("max_goals_poisson", 8))
        matrix = np.zeros((max_g + 1, max_g + 1))

        for hg in range(max_g + 1):
            for ag in range(max_g + 1):
                matrix[hg, ag] = poisson.pmf(hg, home_xg) * poisson.pmf(ag, away_xg)

        prob_home = float(np.sum(np.tril(matrix, -1)))
        prob_draw = float(np.sum(np.diag(matrix)))
        prob_away = float(np.sum(np.triu(matrix,  1)))

        scores = [
            (hg, ag, round(matrix[hg, ag] * 100, 2))
            for hg in range(max_g + 1)
            for ag in range(max_g + 1)
        ]
        scores.sort(key=lambda x: x[2], reverse=True)

        logger.info(
            "Poisson H=%.1f%%  D=%.1f%%  A=%.1f%%",
            prob_home * 100, prob_draw * 100, prob_away * 100,
        )
        return prob_home, prob_draw, prob_away, scores[:6]

    # ══════════════════════════════════════════════════════════════════════
    # 3. VALUE BET DETECTOR
    # ══════════════════════════════════════════════════════════════════════

    @staticmethod
    def _implied_prob(odds: float) -> float:
        return 0.0 if odds <= 1.0 else 1.0 / odds

    @staticmethod
    def _edge(model_prob: float, implied_prob: float) -> float:
        if implied_prob <= 0:
            return 0.0
        return round((model_prob - implied_prob) / implied_prob * 100, 2)

    @staticmethod
    def _value_rating(edge_pct: float) -> str:
        if edge_pct >= 25: return "⚡ ELITE"
        if edge_pct >= 15: return "🔥 HIGH"
        if edge_pct >= 8:  return "✅ MEDIUM"
        return "📌 LOW"

    def _kelly_stake(self, prob: float, odds: float, bankroll: float) -> float:
        if odds <= 1.0 or prob <= 0:
            return 0.0
        b  = odds - 1.0
        q  = 1.0 - prob
        kf = max((b * prob - q) / b, 0.0)
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
    ) -> MatchPrediction | None:
        """
        Full pre-match analysis pipeline.

        Parameters
        ----------
        fixture_id   : API-Football fixture ID
        home_team_id : API-Football team ID
        away_team_id : API-Football team ID
        league_id    : API-Football league ID (1 = World Cup 2026)
        city         : Venue city for weather
        match_name   : "Home vs Away" string
        season       : Season year (default 2026)
        """
        logger.info("━━━ evaluate_match fixture=%d '%s' season=%d ━━━",
                    fixture_id, match_name, season)

        # Step 1 — Team DNA + xG
        home_p, away_p, home_xg, away_xg = self.analyze_teams(
            home_team_id, away_team_id, league_id, season=season
        )

        # Step 2 — Weather penalty
        weather_applied = False
        weather_note    = "No significant weather impact."
        penalty         = float(self.config.get("weather_xg_penalty", 0.08))
        bad_kw          = [k.lower() for k in self.config.get("bad_weather_keywords", [])]

        weather = self.api.get_weather_for_venue(city=city)
        if weather:
            cond      = weather.get("condition", "").lower()
            precip_mm = float(weather.get("precip_mm", 0))
            wind_kph  = float(weather.get("wind_kph",  0))
            is_bad    = any(kw in cond for kw in bad_kw) or precip_mm > 10 or wind_kph > 60

            if is_bad:
                home_xg        *= (1 - penalty)
                away_xg        *= (1 - penalty)
                home_xg         = round(home_xg, 4)
                away_xg         = round(away_xg, 4)
                weather_applied = True
                weather_note    = (
                    f"⚠️  Severe weather: '{weather['condition']}' | "
                    f"Rain={precip_mm}mm | Wind={wind_kph}km/h — "
                    f"xG reduced {penalty*100:.0f}%."
                )
                logger.warning(weather_note)
            else:
                weather_note = (
                    f"☀️  {weather.get('condition','N/A')} | "
                    f"{weather.get('temp_c','?')}°C | "
                    f"Rain={precip_mm}mm — No penalty."
                )
        else:
            weather_note = "Weather data unavailable — no penalty applied."

        # Step 3 — Poisson
        prob_home, prob_draw, prob_away, top_scores = self._poisson_matrix(
            home_xg, away_xg
        )

        # Step 4 — Bookmaker odds
        odds_data = self.api.get_prematch_odds(fixture_id=fixture_id)
        if odds_data:
            bk_home = float(odds_data.get("home", 0.0))
            bk_draw = float(odds_data.get("draw", 0.0))
            bk_away = float(odds_data.get("away", 0.0))
            bk_name = odds_data.get("bookmaker", "Unknown")
        else:
            bk_home, bk_draw, bk_away = 0.0, 0.0, 0.0
            bk_name = "N/A"

        # Step 5 — Edge
        impl_home = self._implied_prob(bk_home)
        impl_draw = self._implied_prob(bk_draw)
        impl_away = self._implied_prob(bk_away)

        edge_home = self._edge(prob_home, impl_home) if bk_home > 1 else 0.0
        edge_draw = self._edge(prob_draw, impl_draw) if bk_draw > 1 else 0.0
        edge_away = self._edge(prob_away, impl_away) if bk_away > 1 else 0.0

        threshold = float(self.config.get("value_bet_threshold_pct", 5.0))
        value_bets: list[dict] = []
        for sel, ep, mp, odds in [
            ("Home Win", edge_home, prob_home, bk_home),
            ("Draw",     edge_draw, prob_draw, bk_draw),
            ("Away Win", edge_away, prob_away, bk_away),
        ]:
            if ep >= threshold:
                value_bets.append({
                    "market":         "1X2",
                    "selection":      sel,
                    "edge_pct":       ep,
                    "rating":         self._value_rating(ep),
                    "model_prob_pct": round(mp * 100, 2),
                    "bk_odds":        odds,
                })
                logger.info(
                    "VALUE BET → %s @ %.2f | Edge=%.1f%% | %s",
                    sel, odds, ep, self._value_rating(ep),
                )

        # Step 6 — Kelly stakes
        bankroll = float(self.config.get("stake_default", 10.0))
        kelly_stakes: dict[str, float] = {}
        for sel, prob, odds in [
            ("Home Win", prob_home, bk_home),
            ("Draw",     prob_draw, bk_draw),
            ("Away Win", prob_away, bk_away),
        ]:
            if odds > 1.0:
                kelly_stakes[sel] = self._kelly_stake(prob, odds, bankroll)

        # Build prediction
        pred = MatchPrediction(
            fixture_id     = fixture_id,
            home_team_id   = home_team_id,
            away_team_id   = away_team_id,
            league_id      = league_id,
            season         = season,
            home_xg        = home_xg,
            away_xg        = away_xg,
            prob_home_win  = round(prob_home, 4),
            prob_draw      = round(prob_draw, 4),
            prob_away_win  = round(prob_away, 4),
            top_scores     = top_scores,
            bk_home_odds   = bk_home,
            bk_draw_odds   = bk_draw,
            bk_away_odds   = bk_away,
            bookmaker_name = bk_name,
            impl_home_pct  = round(impl_home * 100, 2),
            impl_draw_pct  = round(impl_draw * 100, 2),
            impl_away_pct  = round(impl_away * 100, 2),
            edge_home_pct  = edge_home,
            edge_draw_pct  = edge_draw,
            edge_away_pct  = edge_away,
            value_bets     = value_bets,
            weather_applied= weather_applied,
            weather_note   = weather_note,
            kelly_stakes   = kelly_stakes,
        )

        # Cache prediction for later recalibration
        self._save_prediction(pred)

        logger.info("MatchPrediction complete — fixture=%d", fixture_id)
        return pred

    # ══════════════════════════════════════════════════════════════════════
    # 5. AUTO-RECALIBRATION (SELF-LEARNING)
    # ══════════════════════════════════════════════════════════════════════

    def update_weights_from_result(
        self,
        fixture_id:        int,
        actual_home_goals: int,
        actual_away_goals: int,
    ) -> dict[str, Any]:
        """
        Self-learning recalibration — adjusts weights.json based on the
        delta between the model's xG prediction and the actual result.

        Algorithm
        ---------
        1. Load cached prediction for fixture_id.
        2. Compute xG error:
             home_error = actual_home_goals - predicted_home_xg
             away_error = actual_away_goals - predicted_away_xg
             combined_error = (|home_error| + |away_error|) / 2
        3. If combined_error > 0.5 (model was off):
             - large error → form_weight was over-trusted → decrease it,
               increase dna_weight (DNA/stats more stable than form).
             - Check direction: if actual > predicted, model under-estimated
               → offensive factors need slight boost (goals_weight up).
        4. Apply learning_rate-scaled adjustments with max_delta cap.
        5. Save updated weights.json.
        6. Log the event to recalibration_log.csv.

        Returns dict summarising the adjustments made.
        """
        logger.info(
            "update_weights_from_result: fixture=%d actual=%d-%d",
            fixture_id, actual_home_goals, actual_away_goals,
        )

        cache = self._load_prediction_cache(fixture_id)
        if cache is None:
            return {
                "status": "error",
                "message": f"No cached prediction found for fixture_id={fixture_id}.",
            }

        pred_home_xg = float(cache.get("home_xg", 1.25))
        pred_away_xg = float(cache.get("away_xg", 1.00))

        home_error     = actual_home_goals - pred_home_xg
        away_error     = actual_away_goals - pred_away_xg
        combined_error = (abs(home_error) + abs(away_error)) / 2.0
        avg_error      = (home_error + away_error) / 2.0   # signed: + = under-estimated

        lr      = float(self.config.get("recalibration_learning_rate", 0.05))
        max_d   = float(self.config.get("recalibration_max_delta",     0.15))

        # ── Current weight values ────────────────────────────────────────
        fw  = float(self.weights.get("form_weight",      0.60))
        dw  = float(self.weights.get("dna_weight",       0.40))
        gw  = float(self.weights.get("goals_weight",     0.45))
        sow = float(self.weights.get("shots_ot_weight",  0.30))
        pw  = float(self.weights.get("possession_weight",0.25))

        adjustments: dict[str, dict] = {}
        reason_parts: list[str] = []

        def _clamp(val: float, lo: float, hi: float) -> float:
            return max(lo, min(hi, val))

        def _shift(name: str, current: float, delta: float,
                   lo: float = 0.05, hi: float = 0.95) -> float:
            """Apply delta with cap and record adjustment."""
            delta = max(-max_d, min(max_d, delta))
            new_val = _clamp(current + delta, lo, hi)
            adjustments[name] = {
                "old": round(current, 4),
                "delta": round(delta, 4),
                "new": round(new_val, 4),
            }
            return new_val

        # ── Decision logic ───────────────────────────────────────────────
        if combined_error < 0.30:
            # Model was accurate — no adjustment needed
            logger.info(
                "Combined xG error=%.3f < 0.30 — weights stable, no adjustment.",
                combined_error,
            )
            return {
                "status":          "stable",
                "combined_error":  round(combined_error, 4),
                "home_error":      round(home_error, 4),
                "away_error":      round(away_error, 4),
                "adjustments":     {},
                "message":         "Model accurate — no weight changes.",
            }

        # ── Large error: form was over-trusted ──────────────────────────
        # Scale adjustment magnitude with error size
        scale = min(combined_error / 3.0, 1.0) * lr

        if combined_error >= 0.50:
            # Shift trust from form → DNA
            fw  = _shift("form_weight", fw,  -scale * 0.6, lo=0.10, hi=0.90)
            dw  = _shift("dna_weight",  dw,  +scale * 0.6, lo=0.10, hi=0.90)
            reason_parts.append(
                f"Large xG error ({combined_error:.2f}) → reduced form_weight, increased dna_weight."
            )

        if avg_error > 0.50:
            # Model under-estimated goals → boost offensive indicators
            gw  = _shift("goals_weight",     gw,  +scale * 0.5, lo=0.10, hi=0.80)
            sow = _shift("shots_ot_weight",  sow, +scale * 0.3, lo=0.05, hi=0.60)
            reason_parts.append(
                f"Model under-estimated (avg_error=+{avg_error:.2f}) → boosted goals/shots weights."
            )
        elif avg_error < -0.50:
            # Model over-estimated goals → reduce offensive weight, boost possession
            gw  = _shift("goals_weight",     gw,  -scale * 0.4, lo=0.10, hi=0.80)
            pw  = _shift("possession_weight",pw,  +scale * 0.3, lo=0.05, hi=0.50)
            reason_parts.append(
                f"Model over-estimated (avg_error={avg_error:.2f}) → reduced goals_weight, boosted possession."
            )

        # ── Normalise component weights so they sum to 1.0 ──────────────
        total_comp = gw + sow + pw
        if total_comp > 0:
            gw  = round(gw  / total_comp, 4)
            sow = round(sow / total_comp, 4)
            pw  = round(pw  / total_comp, 4)

        # ── Normalise form/dna weights ───────────────────────────────────
        total_fd = fw + dw
        if total_fd > 0:
            fw = round(fw / total_fd, 4)
            dw = round(dw / total_fd, 4)

        # ── Update and persist ───────────────────────────────────────────
        self.weights["form_weight"]       = fw
        self.weights["dna_weight"]        = dw
        self.weights["goals_weight"]      = gw
        self.weights["shots_ot_weight"]   = sow
        self.weights["possession_weight"] = pw

        _save_json(WEIGHTS_PATH, self.weights)

        reason = "  |  ".join(reason_parts) if reason_parts else "Minor adjustment."
        logger.info("Weights recalibrated: %s", reason)
        logger.info(
            "New weights → form=%.4f  dna=%.4f  goals=%.4f  shots=%.4f  poss=%.4f",
            fw, dw, gw, sow, pw,
        )

        # ── Log to recalibration_log.csv ─────────────────────────────────
        log_row = {
            "timestamp":       datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
            "fixture_id":      fixture_id,
            "pred_home_xg":    round(pred_home_xg, 3),
            "pred_away_xg":    round(pred_away_xg, 3),
            "actual_home":     actual_home_goals,
            "actual_away":     actual_away_goals,
            "home_error":      round(home_error, 3),
            "away_error":      round(away_error, 3),
            "combined_error":  round(combined_error, 3),
            "new_form_weight": fw,
            "new_dna_weight":  dw,
            "new_goals_weight":gw,
            "reason":          reason,
        }
        log_headers = list(log_row.keys())
        log_exists  = RECALIBRATION_LOG.exists()

        with RECALIBRATION_LOG.open("a", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=log_headers)
            if not log_exists:
                writer.writeheader()
            writer.writerow(log_row)

        logger.info("Recalibration logged → recalibration_log.csv")

        return {
            "status":         "recalibrated",
            "fixture_id":     fixture_id,
            "pred_home_xg":   round(pred_home_xg, 3),
            "pred_away_xg":   round(pred_away_xg, 3),
            "actual_home":    actual_home_goals,
            "actual_away":    actual_away_goals,
            "home_error":     round(home_error, 3),
            "away_error":     round(away_error, 3),
            "combined_error": round(combined_error, 3),
            "adjustments":    adjustments,
            "reason":         reason,
        }

    # ══════════════════════════════════════════════════════════════════════
    # 6. PORTFOLIO LOGGER
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
        result:      str = "",
    ) -> BetLogEntry:
        """
        Append one bet to portfolio.csv.
        result: "W", "L", "V" (void), "" (pending)
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
            writer.writerow({
                "Date":      entry.date,
                "FixtureID": entry.fixture_id,
                "Match":     entry.match,
                "Market":    entry.market,
                "Selection": entry.selection,
                "Odds":      entry.odds,
                "Stake":     entry.stake,
                "Result":    entry.result,
                "PnL":       entry.pnl,
            })

        logger.info(
            "Portfolio → %s | %s @ %.2f | Stake=%.2f | Result=%s | PnL=%.2f",
            match_name, selection, odds, stake, entry.result, pnl,
        )
        return entry

    # ══════════════════════════════════════════════════════════════════════
    # 7. PORTFOLIO SUMMARY
    # ══════════════════════════════════════════════════════════════════════

    def portfolio_summary(self) -> pd.DataFrame | None:
        if not PORTFOLIO_PATH.exists():
            logger.warning("portfolio.csv does not exist yet.")
            return None
        df = pd.read_csv(PORTFOLIO_PATH)
        if df.empty:
            return None

        settled     = df[df["Result"].isin(["W", "L"])]
        total_bets  = len(settled)
        total_stake = settled["Stake"].sum()
        total_pnl   = settled["PnL"].sum()
        roi         = total_pnl / total_stake * 100 if total_stake > 0 else 0.0
        wins        = len(settled[settled["Result"] == "W"])
        win_rate    = wins / total_bets * 100 if total_bets > 0 else 0.0

        print(f"\n{'─'*50}")
        print("  📊  PORTFOLIO SUMMARY")
        print(f"{'─'*50}")
        print(f"  Settled Bets : {total_bets}")
        print(f"  Win Rate     : {win_rate:.1f}%")
        print(f"  Total Staked : €{total_stake:.2f}")
        print(f"  Net P&L      : €{total_pnl:+.2f}")
        print(f"  ROI          : {roi:+.1f}%")
        print(f"{'─'*50}\n")
        return df


# ─────────────────────────────────────────────────────────────────────────────
# SMOKE TEST
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "=" * 68)
    print("  FOOTBALL ORACLE ENGINE — Smoke Test (Season 2026)")
    print("=" * 68 + "\n")

    engine = FootballOracleEngine()

    # Mock recalibration test (no API call needed)
    print("[TEST] Simulating recalibration for fixture 9999999 …")

    # Create a fake cache entry
    import json
    fake_cache = {
        "fixture_id": 9999999, "home_team_id": 496,
        "away_team_id": 489, "league_id": 135, "season": 2026,
        "home_xg": 1.74, "away_xg": 1.02,
        "prob_home_win": 0.52, "prob_draw": 0.26, "prob_away_win": 0.22,
        "saved_at": datetime.utcnow().isoformat(),
    }
    cache_file = PREDICTIONS_DIR / "9999999.json"
    cache_file.write_text(json.dumps(fake_cache, indent=4), encoding="utf-8")

    result = engine.update_weights_from_result(
        fixture_id=9999999,
        actual_home_goals=3,
        actual_away_goals=1,
    )
    print(f"\n  Status         : {result['status']}")
    print(f"  Combined Error : {result.get('combined_error', 'N/A')}")
    print(f"  Reason         : {result.get('reason', '')}")
    if result.get("adjustments"):
        print("  Weight changes :")
        for k, v in result["adjustments"].items():
            print(f"    {k}: {v['old']} → {v['new']}  (Δ{v['delta']:+.4f})")

    print("\n" + "=" * 68 + "\n")
