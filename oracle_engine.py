"""
================================================================================
FOOTBALL ORACLE — Core Engine (Hybrid Edition)
================================================================================
Module  : oracle_engine.py
Depends : oracle_api.py (FootballOracleAPI - Hybrid)
          pip install numpy scipy pandas
Changes : Real weather xG penalty, hybrid team stats, standings form fallback,
          self-learning recalibration, prediction cache, portfolio logger.
================================================================================
"""

from __future__ import annotations

import csv
import json
import logging
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import poisson

try:
    from oracle_api import FootballOracleAPI
except ModuleNotFoundError:
    print("[FATAL] oracle_api.py not found.")
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
# PATHS
# ─────────────────────────────────────────────────────────────────────────────
BASE_DIR          = Path(__file__).parent
CONFIG_PATH       = BASE_DIR / "config.json"
WEIGHTS_PATH      = BASE_DIR / "weights.json"
PORTFOLIO_PATH    = BASE_DIR / "portfolio.csv"
PREDICTIONS_DIR   = BASE_DIR / "predictions"
RECAL_LOG_PATH    = BASE_DIR / "recalibration_log.csv"
PREDICTIONS_DIR.mkdir(exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# DEFAULTS
# ─────────────────────────────────────────────────────────────────────────────
DEFAULT_CONFIG: dict[str, Any] = {
    "value_bet_threshold_pct":      5.0,
    "max_goals_poisson":            8,
    "last_n_fixtures":              5,
    "stake_default":                10.0,
    "kelly_fraction":               0.25,
    "recalibration_learning_rate":  0.05,
    "recalibration_max_delta":      0.15,
}

DEFAULT_WEIGHTS: dict[str, Any] = {
    # Offensive rating components
    "goals_weight":      0.45,
    "shots_ot_weight":   0.30,
    "possession_weight": 0.25,
    # xG calibration
    "form_weight":       0.60,
    "dna_weight":        0.40,
    # Home / Away adjustment
    "home_advantage":    1.07,
    "away_penalty":      0.95,
    # League baselines (avg xG per team per game)
    "league_baselines": {
        "Premier League":    1.35,
        "La Liga":           1.20,
        "Serie A":           1.25,
        "Bundesliga":        1.40,
        "Ligue 1":           1.30,
        "Champions League":  1.20,
        "Europa League":     1.15,
        "Romania SuperLiga": 1.15,
        "World Cup 2026":    1.30,
        "default":           1.25,
    },
    # Caps
    "offensive_cap": 3.5,
    "defensive_cap": 2.5,
    # Per-league weights — each league calibrates independently
    # sample_count tracks how many results have been fed for this league
    "league_weights": {
        "Premier League":    {"form_weight":0.60,"dna_weight":0.40,"goals_weight":0.45,"shots_ot_weight":0.30,"possession_weight":0.25,"home_advantage":1.07,"away_penalty":0.95,"sample_count":0},
        "La Liga":           {"form_weight":0.60,"dna_weight":0.40,"goals_weight":0.45,"shots_ot_weight":0.30,"possession_weight":0.25,"home_advantage":1.06,"away_penalty":0.95,"sample_count":0},
        "Serie A":           {"form_weight":0.60,"dna_weight":0.40,"goals_weight":0.45,"shots_ot_weight":0.30,"possession_weight":0.25,"home_advantage":1.06,"away_penalty":0.95,"sample_count":0},
        "Bundesliga":        {"form_weight":0.65,"dna_weight":0.35,"goals_weight":0.50,"shots_ot_weight":0.28,"possession_weight":0.22,"home_advantage":1.08,"away_penalty":0.94,"sample_count":0},
        "Ligue 1":           {"form_weight":0.60,"dna_weight":0.40,"goals_weight":0.45,"shots_ot_weight":0.30,"possession_weight":0.25,"home_advantage":1.07,"away_penalty":0.95,"sample_count":0},
        "Champions League":  {"form_weight":0.55,"dna_weight":0.45,"goals_weight":0.42,"shots_ot_weight":0.32,"possession_weight":0.26,"home_advantage":1.05,"away_penalty":0.96,"sample_count":0},
        "Europa League":     {"form_weight":0.58,"dna_weight":0.42,"goals_weight":0.43,"shots_ot_weight":0.31,"possession_weight":0.26,"home_advantage":1.06,"away_penalty":0.95,"sample_count":0},
        "Romania SuperLiga": {"form_weight":0.65,"dna_weight":0.35,"goals_weight":0.48,"shots_ot_weight":0.28,"possession_weight":0.24,"home_advantage":1.09,"away_penalty":0.93,"sample_count":0},
        "World Cup 2026":    {"form_weight":0.55,"dna_weight":0.45,"goals_weight":0.44,"shots_ot_weight":0.30,"possession_weight":0.26,"home_advantage":1.03,"away_penalty":0.97,"sample_count":0},
        "default":           {"form_weight":0.60,"dna_weight":0.40,"goals_weight":0.45,"shots_ot_weight":0.30,"possession_weight":0.25,"home_advantage":1.07,"away_penalty":0.95,"sample_count":0}
    },
}


def _load_json(path: Path, default: dict) -> dict:
    if not path.exists():
        path.write_text(json.dumps(default, indent=4), encoding="utf-8")
        return dict(default)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return dict(default)


def _save_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=4), encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# DATA CLASSES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TeamProfile:
    team_id:           str
    team_name:         str
    matches_analysed:  int
    avg_goals_for:     float
    avg_goals_against: float
    avg_shots_ot:      float
    avg_possession:    float
    offensive_rating:  float
    defensive_rating:  float
    form_results:      list[str]   # ["W","D","L","W","W"]
    form_score:        float       # 0-1 weighted
    standings_form:    str         # "W,D,W,L,W" from API
    data_source:       str

    def __str__(self) -> str:
        return (
            f"OFF={self.offensive_rating:.3f}  DEF={self.defensive_rating:.3f}"
            f"  Form={''.join(self.form_results)}  Score={self.form_score:.2f}"
            f"  [{self.data_source}]"
        )


@dataclass
class MatchPrediction:
    fixture_id:       str
    home_team:        str
    away_team:        str
    league:           str
    kickoff_utc:      str
    kickoff_date:     str
    season:           int
    home_xg:          float
    away_xg:          float
    prob_home_win:    float
    prob_draw:        float
    prob_away_win:    float
    top_scores:       list[tuple[int, int, float]]
    bk_home_odds:     float
    bk_draw_odds:     float
    bk_away_odds:     float
    bookmaker_name:   str
    impl_home_pct:    float
    impl_draw_pct:    float
    impl_away_pct:    float
    edge_home_pct:    float
    edge_draw_pct:    float
    edge_away_pct:    float
    value_bets:       list[dict]
    weather_note:     str
    weather_penalty:  float
    kelly_stakes:     dict[str, float]
    home_profile:     TeamProfile | None
    away_profile:     TeamProfile | None


# ─────────────────────────────────────────────────────────────────────────────
# ENGINE
# ─────────────────────────────────────────────────════════════════════════════

class FootballOracleEngine:
    """
    Core engine — Hybrid Edition.
    Combines multi-source API data with Poisson modelling, value-bet
    detection, self-learning recalibration, and portfolio logging.
    """

    def __init__(self) -> None:
        self.api     = FootballOracleAPI()
        self.config  = _load_json(CONFIG_PATH,  DEFAULT_CONFIG)
        self.weights = _load_json(WEIGHTS_PATH, DEFAULT_WEIGHTS)
        logger.info("FootballOracleEngine (Hybrid) ready.")

    # ══════════════════════════════════════════════════════════════════════
    # TEAM PROFILE BUILDER
    # ══════════════════════════════════════════════════════════════════════

    def _build_profile(
        self,
        team_id:   str,
        team_name: str,
        league:    str,
    ) -> TeamProfile:
        """
        Build TeamProfile using cascading data sources:
        1. API-Football historical stats (detailed)
        2. football-data.org standings form (fallback)
        3. Neutral defaults (last resort)
        """
        w        = self.weights
        o_cap    = float(w.get("offensive_cap", 3.5))
        d_cap    = float(w.get("defensive_cap", 2.5))
        last_n   = int(self.config.get("last_n_fixtures", 5))

        # ── Source 1: API-Football detailed stats ─────────────────────────
        stats = self.api.get_team_stats(team_id, league)
        data_source = "api-football-hist"

        if stats:
            n   = len(stats)
            gf  = sum(s["goals_for"]     for s in stats) / n
            ga  = sum(s["goals_against"] for s in stats) / n
            sot = sum(s["shots_on_goal"] for s in stats) / n
            pos = sum(s["possession"]    for s in stats) / n
            results = [s["result"] for s in stats]

        else:
            # ── Source 2: standings form ──────────────────────────────────
            standings = self.api.get_standings_form(team_id, league)
            data_source = "standings-form"

            if standings:
                played = standings.get("played") or 1
                gf  = (standings.get("goals_for",     0) or 0) / played
                ga  = (standings.get("goals_against", 0) or 0) / played
                sot = gf * 0.45           # estimate: ~45% of goals from shots on target
                pos = 50.0                # neutral possession
                form_str = standings.get("form", "") or ""
                results  = [r.strip() for r in form_str.split(",") if r.strip()][:last_n]
                n = max(len(results), 1)
            else:
                # ── Source 3: neutral defaults ────────────────────────────
                logger.warning(
                    "No stats for team '%s' — using league neutral defaults.", team_name
                )
                baseline = float(
                    w.get("league_baselines", {}).get(league,
                    w.get("league_baselines", {}).get("default", 1.25))
                )
                gf  = baseline
                ga  = baseline
                sot = baseline * 0.45
                pos = 50.0
                results = ["D", "D", "D"]
                n = 3
                data_source = "neutral-defaults"

        # ── Ratings ───────────────────────────────────────────────────────
        g_w   = float(w.get("goals_weight",      0.45))
        sot_w = float(w.get("shots_ot_weight",   0.30))
        pos_w = float(w.get("possession_weight", 0.25))

        g_norm   = min(gf  / 2.0, 1.0) * 1.5
        sot_norm = min(sot / 6.0, 1.0) * 1.5
        pos_norm = max(0.0, min(((pos - 30.0) / 40.0) * 0.5, 0.5))

        off_rating = min(
            g_norm * g_w + sot_norm * sot_w + pos_norm * pos_w + gf * 0.2,
            o_cap,
        )
        def_rating = min(ga, d_cap)

        # ── Form score (exponential recency weight) ───────────────────────
        rv = {"W": 1.0, "D": 0.4, "L": 0.0}
        wts = [2 ** i for i in range(len(results))]
        tw  = sum(wts) or 1
        form_score = sum(rv.get(r, 0.4) * wts[i] for i, r in enumerate(results)) / tw

        return TeamProfile(
            team_id          = team_id,
            team_name        = team_name,
            matches_analysed = n,
            avg_goals_for    = round(gf,  3),
            avg_goals_against= round(ga,  3),
            avg_shots_ot     = round(sot, 3),
            avg_possession   = round(pos, 1),
            offensive_rating = round(off_rating, 4),
            defensive_rating = round(def_rating, 4),
            form_results     = results[-last_n:] if results else [],
            form_score       = round(form_score, 4),
            standings_form   = ",".join(results),
            data_source      = data_source,
        )

    # ══════════════════════════════════════════════════════════════════════
    # xG CALIBRATION
    # ══════════════════════════════════════════════════════════════════════

    def _get_league_weights(self, league: str) -> dict:
        """
        Return per-league weights, falling back to global weights then defaults.
        Per-league weights take priority once sample_count > 0.
        """
        lw_all  = self.weights.get("league_weights", {})
        lw      = lw_all.get(league, lw_all.get("default", {}))
        # Blend: if sample_count < 5, mix with global weights (cold-start protection)
        sc = int(lw.get("sample_count", 0))
        if sc < 5:
            alpha = sc / 5.0   # 0.0 → pure global, 1.0 → pure league
        else:
            alpha = 1.0
        gw = self.weights   # global fallback
        def _blend(key, default):
            league_val = float(lw.get(key, gw.get(key, default)))
            global_val = float(gw.get(key, default))
            return alpha * league_val + (1 - alpha) * global_val
        return {
            "form_weight":       _blend("form_weight",       0.60),
            "dna_weight":        _blend("dna_weight",        0.40),
            "goals_weight":      _blend("goals_weight",      0.45),
            "shots_ot_weight":   _blend("shots_ot_weight",   0.30),
            "possession_weight": _blend("possession_weight", 0.25),
            "home_advantage":    _blend("home_advantage",    1.07),
            "away_penalty":      _blend("away_penalty",      0.95),
            "sample_count":      sc,
        }

    def _calibrate_xg(
        self,
        home_p:  TeamProfile,
        away_p:  TeamProfile,
        league:  str,
        weather_penalty: float = 0.0,
    ) -> tuple[float, float]:
        """
        Compute calibrated xG for home and away teams.
        Uses per-league weights (blended with global during cold-start).
        """
        w        = self.weights
        baselines= w.get("league_baselines", {})
        baseline = float(baselines.get(league, baselines.get("default", 1.25)))
        lw       = self._get_league_weights(league)
        fw       = lw["form_weight"]
        dw       = lw["dna_weight"]
        d_cap    = float(w.get("defensive_cap",  2.5))
        home_adv = lw["home_advantage"]
        away_pen = lw["away_penalty"]

        # Defensive vulnerability: 0=iron defence, d_cap=very leaky
        away_def_mod = 0.60 + (away_p.defensive_rating / d_cap) * 0.80
        home_def_mod = 0.60 + (home_p.defensive_rating / d_cap) * 0.80

        # Form modifier: 1.0 form → +20%, 0 form → -20%
        home_form_mod = 0.80 + home_p.form_score * 0.40
        away_form_mod = 0.80 + away_p.form_score * 0.40

        home_xg = (
            home_p.offensive_rating
            * away_def_mod
            * baseline
            * (fw * home_form_mod + dw)
            * home_adv
        )
        away_xg = (
            away_p.offensive_rating
            * home_def_mod
            * baseline
            * (fw * away_form_mod + dw)
            * away_pen
        )

        # Apply weather penalty (both teams equally affected)
        if weather_penalty > 0:
            home_xg *= (1 - weather_penalty)
            away_xg *= (1 - weather_penalty)

        home_xg = round(max(home_xg, 0.20), 4)
        away_xg = round(max(away_xg, 0.20), 4)

        logger.info("xG → home=%.3f  away=%.3f  (weather_penalty=%.3f)", home_xg, away_xg, weather_penalty)
        return home_xg, away_xg

    # ══════════════════════════════════════════════════════════════════════
    # POISSON MODEL
    # ══════════════════════════════════════════════════════════════════════

    def _poisson_model(
        self, home_xg: float, away_xg: float
    ) -> tuple[float, float, float, list[tuple[int, int, float]]]:
        max_g  = int(self.config.get("max_goals_poisson", 8))
        matrix = np.zeros((max_g + 1, max_g + 1))

        for hg in range(max_g + 1):
            for ag in range(max_g + 1):
                matrix[hg, ag] = poisson.pmf(hg, home_xg) * poisson.pmf(ag, away_xg)

        ph = float(np.sum(np.tril(matrix, -1)))
        pd = float(np.sum(np.diag(matrix)))
        pa = float(np.sum(np.triu(matrix, 1)))

        scores = sorted(
            [(hg, ag, round(matrix[hg, ag] * 100, 2))
             for hg in range(max_g + 1)
             for ag in range(max_g + 1)],
            key=lambda x: x[2], reverse=True,
        )
        return ph, pd, pa, scores[:6]

    # ══════════════════════════════════════════════════════════════════════
    # VALUE BET LOGIC
    # ══════════════════════════════════════════════════════════════════════

    @staticmethod
    def _implied(odds: float) -> float:
        return 0.0 if odds <= 1.0 else 1.0 / odds

    @staticmethod
    def _edge(model_p: float, impl_p: float) -> float:
        if impl_p <= 0: return 0.0
        return round((model_p - impl_p) / impl_p * 100, 2)

    @staticmethod
    def _rating(edge: float) -> str:
        if edge >= 25: return "⚡ ELITE"
        if edge >= 15: return "🔥 HIGH"
        if edge >= 8:  return "✅ MEDIUM"
        return "📌 LOW"

    def _kelly(self, prob: float, odds: float) -> float:
        if odds <= 1.0 or prob <= 0: return 0.0
        b  = odds - 1.0
        kf = max((b * prob - (1 - prob)) / b, 0.0)
        return round(
            float(self.config.get("stake_default", 10.0))
            * kf
            * float(self.config.get("kelly_fraction", 0.25)),
            2,
        )

    # ══════════════════════════════════════════════════════════════════════
    # MASTER EVALUATE
    # ══════════════════════════════════════════════════════════════════════

    def evaluate_match(self, match: dict) -> MatchPrediction | None:
        """
        Full analysis pipeline for one normalised match dict.

        match dict (from FootballOracleAPI.get_matches_for_week):
        {
            fixture_id, home_team, away_team, home_team_id, away_team_id,
            league, kickoff_utc, kickoff_date, season, venue_city,
            home_odds, draw_odds, away_odds, odds_source, source
        }
        """
        home_name = match["home_team"]
        away_name = match["away_team"]
        league    = match.get("league", "Unknown")
        fid       = match.get("fixture_id", "?")

        logger.info("━━━ evaluate %s vs %s [%s] ━━━", home_name, away_name, league)

        # ── Team profiles ─────────────────────────────────────────────────
        home_p = self._build_profile(
            match.get("home_team_id", ""),
            home_name, league,
        )
        away_p = self._build_profile(
            match.get("away_team_id", ""),
            away_name, league,
        )
        logger.info("Home: %s", home_p)
        logger.info("Away: %s", away_p)

        # ── Weather ───────────────────────────────────────────────────────
        city    = match.get("venue_city", "") or league
        weather = self.api.get_weather(city, match.get("kickoff_date"))
        w_pen   = float(weather.get("xg_penalty", 0.0))
        w_note  = weather.get("description", "")

        # ── xG ────────────────────────────────────────────────────────────
        home_xg, away_xg = self._calibrate_xg(home_p, away_p, league, w_pen)

        # ── Poisson ───────────────────────────────────────────────────────
        ph, pd, pa, top_scores = self._poisson_model(home_xg, away_xg)

        # ── Odds ──────────────────────────────────────────────────────────
        bk_h = float(match.get("home_odds") or 0.0)
        bk_d = float(match.get("draw_odds") or 0.0)
        bk_a = float(match.get("away_odds") or 0.0)
        bk_n = match.get("odds_source") or "N/A"

        # ── Implied probs & Edge ──────────────────────────────────────────
        impl_h = self._implied(bk_h)
        impl_d = self._implied(bk_d)
        impl_a = self._implied(bk_a)

        edge_h = self._edge(ph, impl_h) if bk_h > 1 else 0.0
        edge_d = self._edge(pd, impl_d) if bk_d > 1 else 0.0
        edge_a = self._edge(pa, impl_a) if bk_a > 1 else 0.0

        threshold  = float(self.config.get("value_bet_threshold_pct", 5.0))
        value_bets: list[dict] = []

        for sel, ep, mp, odds in [
            ("Home Win", edge_h, ph, bk_h),
            ("Draw",     edge_d, pd, bk_d),
            ("Away Win", edge_a, pa, bk_a),
        ]:
            if ep >= threshold:
                value_bets.append({
                    "market":         "1X2",
                    "selection":      sel,
                    "edge_pct":       ep,
                    "rating":         self._rating(ep),
                    "model_prob_pct": round(mp * 100, 2),
                    "bk_odds":        odds,
                })

        # ── Kelly stakes ──────────────────────────────────────────────────
        kelly: dict[str, float] = {}
        for sel, prob, odds in [("Home Win", ph, bk_h), ("Draw", pd, bk_d), ("Away Win", pa, bk_a)]:
            if odds > 1.0:
                kelly[sel] = self._kelly(prob, odds)

        pred = MatchPrediction(
            fixture_id     = str(fid),
            home_team      = home_name,
            away_team      = away_name,
            league         = league,
            kickoff_utc    = match.get("kickoff_utc",  ""),
            kickoff_date   = match.get("kickoff_date", ""),
            season         = match.get("season", 2026),
            home_xg        = home_xg,
            away_xg        = away_xg,
            prob_home_win  = round(ph, 4),
            prob_draw      = round(pd, 4),
            prob_away_win  = round(pa, 4),
            top_scores     = top_scores,
            bk_home_odds   = bk_h,
            bk_draw_odds   = bk_d,
            bk_away_odds   = bk_a,
            bookmaker_name = bk_n,
            impl_home_pct  = round(impl_h * 100, 2),
            impl_draw_pct  = round(impl_d * 100, 2),
            impl_away_pct  = round(impl_a * 100, 2),
            edge_home_pct  = edge_h,
            edge_draw_pct  = edge_d,
            edge_away_pct  = edge_a,
            value_bets     = value_bets,
            weather_note   = w_note,
            weather_penalty= w_pen,
            kelly_stakes   = kelly,
            home_profile   = home_p,
            away_profile   = away_p,
        )

        # Cache for recalibration
        self._cache_prediction(pred)
        return pred

    # ══════════════════════════════════════════════════════════════════════
    # WEEKLY SCAN
    # ══════════════════════════════════════════════════════════════════════

    def get_week_matches(
        self,
        days_ahead:   int = 7,
        competitions: list[str] | None = None,
    ) -> list[dict]:
        """
        Return normalised match list for next N days (enriched with odds).
        Sorted by kickoff. No analysis yet — just data.
        """
        return self.api.get_matches_for_week(days_ahead=days_ahead, competitions=competitions)

    def get_matches_by_date(self, target_date: str) -> list[dict]:
        return self.api.get_matches_for_date(target_date)

    # ══════════════════════════════════════════════════════════════════════
    # PREDICTION CACHE
    # ══════════════════════════════════════════════════════════════════════

    def _cache_prediction(self, pred: MatchPrediction) -> None:
        data = {
            "fixture_id":   pred.fixture_id,
            "home_team":    pred.home_team,
            "away_team":    pred.away_team,
            "league":       pred.league,
            "kickoff_date": pred.kickoff_date,
            "home_xg":      pred.home_xg,
            "away_xg":      pred.away_xg,
            "prob_home":    pred.prob_home_win,
            "prob_draw":    pred.prob_draw,
            "prob_away":    pred.prob_away_win,
            "saved_at":     datetime.now(timezone.utc).isoformat(),
        }
        safe_id = str(pred.fixture_id).replace("/", "_")
        _save_json(PREDICTIONS_DIR / f"{safe_id}.json", data)

    def _load_prediction(self, fixture_id: str) -> dict | None:
        safe_id = str(fixture_id).replace("/", "_")
        p = PREDICTIONS_DIR / f"{safe_id}.json"
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None

    # ══════════════════════════════════════════════════════════════════════
    # SELF-LEARNING RECALIBRATION
    # ══════════════════════════════════════════════════════════════════════

    def update_weights_from_result(
        self,
        fixture_id:        str,
        actual_home_goals: int,
        actual_away_goals: int,
    ) -> dict:
        """
        Self-learning recalibration — updates BOTH global weights AND
        the per-league weight block in weights.json.

        Algorithm
        ---------
        1. Load cached prediction → get league name + predicted xG
        2. Compute errors (home + away)
        3. If error < 0.30 → stable, no changes
        4. Otherwise → shift weights in the direction that reduces future error
        5. Update BOTH:
           a) global weights (slow drift — all leagues)
           b) league_weights[league] (fast drift — this league only)
        6. Increment league sample_count
        7. Save weights.json + log to recalibration_log.csv
        """
        cache = self._load_prediction(fixture_id)
        if cache is None:
            return {"status": "error", "message": f"No cached prediction for {fixture_id}."}

        pred_h = float(cache.get("home_xg", 1.25))
        pred_a = float(cache.get("away_xg", 1.00))
        league = cache.get("league", "default")

        home_err = actual_home_goals - pred_h
        away_err = actual_away_goals - pred_a
        combined = (abs(home_err) + abs(away_err)) / 2.0
        avg_err  = (home_err + away_err) / 2.0

        lr    = float(self.config.get("recalibration_learning_rate", 0.05))
        max_d = float(self.config.get("recalibration_max_delta",     0.15))

        if combined < 0.30:
            return {
                "status": "stable",
                "league": league,
                "combined_error": round(combined, 4),
                "message": "Model accurate — no adjustments.",
                "adjustments": {},
            }

        scale = min(combined / 3.0, 1.0) * lr
        adjustments: dict = {}
        reasons:     list = []

        def _shift(name, cur, delta, lo=0.05, hi=0.95):
            delta   = max(-max_d, min(max_d, delta))
            new_val = max(lo, min(hi, cur + delta))
            adjustments[name] = {"old": round(cur,4), "delta": round(delta,4), "new": round(new_val,4)}
            return new_val

        # ── Read current per-league weights ───────────────────────────────
        lw_all = self.weights.setdefault("league_weights", {})
        if league not in lw_all:
            # Initialise from global weights
            lw_all[league] = {
                "form_weight":       float(self.weights.get("form_weight",      0.60)),
                "dna_weight":        float(self.weights.get("dna_weight",       0.40)),
                "goals_weight":      float(self.weights.get("goals_weight",     0.45)),
                "shots_ot_weight":   float(self.weights.get("shots_ot_weight",  0.30)),
                "possession_weight": float(self.weights.get("possession_weight",0.25)),
                "home_advantage":    float(self.weights.get("home_advantage",   1.07)),
                "away_penalty":      float(self.weights.get("away_penalty",     0.95)),
                "sample_count":      0,
            }

        lw = lw_all[league]
        # League-specific learning rate: faster when few samples
        sc       = int(lw.get("sample_count", 0))
        # Adaptive LR: higher at start, decays as data accumulates
        lr_league = lr * max(1.0, 3.0 / (sc + 1))
        lr_league = min(lr_league, lr * 3)   # cap at 3× base LR
        scale_l   = min(combined / 3.0, 1.0) * lr_league

        # Current values — league-specific
        fw  = float(lw.get("form_weight",       0.60))
        dw  = float(lw.get("dna_weight",        0.40))
        gw  = float(lw.get("goals_weight",      0.45))
        sow = float(lw.get("shots_ot_weight",   0.30))
        pw  = float(lw.get("possession_weight", 0.25))
        ha  = float(lw.get("home_advantage",    1.07))
        ap  = float(lw.get("away_penalty",      0.95))

        # ── Apply adjustments ─────────────────────────────────────────────
        if combined >= 0.50:
            fw  = _shift("form_weight", fw,  -scale_l * 0.6, lo=0.10, hi=0.90)
            dw  = _shift("dna_weight",  dw,  +scale_l * 0.6, lo=0.10, hi=0.90)
            reasons.append(f"[{league}] Large error ({combined:.2f}) → shifted to DNA.")

        if avg_err > 0.50:
            gw  = _shift("goals_weight",    gw,  +scale_l * 0.5, lo=0.10, hi=0.80)
            sow = _shift("shots_ot_weight", sow, +scale_l * 0.3, lo=0.05, hi=0.60)
            # Home advantage boost if home team consistently scores more
            if home_err > 0.5:
                ha  = _shift("home_advantage", ha, +scale_l * 0.2, lo=1.00, hi=1.20)
            reasons.append(f"[{league}] Under-estimated (+{avg_err:.2f}) → boosted offensive.")
        elif avg_err < -0.50:
            gw  = _shift("goals_weight",      gw, -scale_l * 0.4, lo=0.10, hi=0.80)
            pw  = _shift("possession_weight", pw, +scale_l * 0.3, lo=0.05, hi=0.50)
            # Reduce home advantage if home team consistently under-delivers
            if home_err < -0.5:
                ha  = _shift("home_advantage", ha, -scale_l * 0.15, lo=1.00, hi=1.20)
            reasons.append(f"[{league}] Over-estimated ({avg_err:.2f}) → reduced offensive.")

        # ── Normalise ─────────────────────────────────────────────────────
        t_comp = gw + sow + pw
        if t_comp > 0:
            gw  = round(gw  / t_comp, 4)
            sow = round(sow / t_comp, 4)
            pw  = round(pw  / t_comp, 4)
        t_fd = fw + dw
        if t_fd > 0:
            fw = round(fw / t_fd, 4)
            dw = round(dw / t_fd, 4)

        # ── Save per-league weights ───────────────────────────────────────
        lw_all[league].update({
            "form_weight":       fw,
            "dna_weight":        dw,
            "goals_weight":      gw,
            "shots_ot_weight":   sow,
            "possession_weight": pw,
            "home_advantage":    ha,
            "away_penalty":      ap,
            "sample_count":      sc + 1,
        })

        # ── Also nudge global weights slowly (1/4 speed) ──────────────────
        gfw  = float(self.weights.get("form_weight",      0.60))
        gdw  = float(self.weights.get("dna_weight",       0.40))
        ggw  = float(self.weights.get("goals_weight",     0.45))
        gsow = float(self.weights.get("shots_ot_weight",  0.30))
        gpw  = float(self.weights.get("possession_weight",0.25))

        self.weights.update({
            "form_weight":       round(max(0.10, min(0.90, gfw  + (fw  - gfw)  * 0.25)), 4),
            "dna_weight":        round(max(0.10, min(0.90, gdw  + (dw  - gdw)  * 0.25)), 4),
            "goals_weight":      round(max(0.10, min(0.80, ggw  + (gw  - ggw)  * 0.25)), 4),
            "shots_ot_weight":   round(max(0.05, min(0.60, gsow + (sow - gsow) * 0.25)), 4),
            "possession_weight": round(max(0.05, min(0.50, gpw  + (pw  - gpw)  * 0.25)), 4),
            "league_weights":    lw_all,
        })
        _save_json(WEIGHTS_PATH, self.weights)

        reason = "  |  ".join(reasons) or "Minor adjustment."
        logger.info(
            "Recalibrated [%s] (sample #%d) — %s", league, sc + 1, reason
        )

        # ── Log ───────────────────────────────────────────────────────────
        log_row = {
            "timestamp":      datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "fixture_id":     fixture_id,
            "league":         league,
            "sample_count":   sc + 1,
            "home":           f"{cache.get('home_team','')} ({pred_h:.2f} xG)",
            "away":           f"{cache.get('away_team','')} ({pred_a:.2f} xG)",
            "actual":         f"{actual_home_goals}-{actual_away_goals}",
            "combined_error": round(combined, 3),
            "new_form_w":     fw,
            "new_dna_w":      dw,
            "home_advantage": ha,
            "reason":         reason,
        }
        exists = RECAL_LOG_PATH.exists()
        with RECAL_LOG_PATH.open("a", newline="", encoding="utf-8") as f:
            w_ = csv.DictWriter(f, fieldnames=list(log_row.keys()))
            if not exists:
                w_.writeheader()
            w_.writerow(log_row)

        return {
            "status": "recalibrated",
            "fixture_id": fixture_id,
            "pred_home_xg": round(pred_h, 3),
            "pred_away_xg": round(pred_a, 3),
            "actual_home":  actual_home_goals,
            "actual_away":  actual_away_goals,
            "home_error":   round(home_err, 3),
            "away_error":   round(away_err, 3),
            "combined_error": round(combined, 3),
            "adjustments":  adjustments,
            "reason":       reason,
        }

    # ══════════════════════════════════════════════════════════════════════
    # PORTFOLIO
    # ══════════════════════════════════════════════════════════════════════

    HEADERS = ["Date","FixtureID","Match","Market","Selection","Odds","Stake","Result","PnL"]

    def log_bet(
        self,
        fixture_id: str,
        match_name: str,
        market:     str,
        selection:  str,
        odds:       float,
        stake:      float,
        result:     str = "",
    ) -> dict:
        result = result.upper().strip()
        pnl = (
            round(stake * (odds - 1), 2) if result == "W"
            else (-round(stake, 2)       if result == "L"
            else 0.0)
        )
        row = {
            "Date":      datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "FixtureID": str(fixture_id),
            "Match":     match_name,
            "Market":    market,
            "Selection": selection,
            "Odds":      odds,
            "Stake":     stake,
            "Result":    result or "PENDING",
            "PnL":       pnl,
        }
        exists = PORTFOLIO_PATH.exists()
        with PORTFOLIO_PATH.open("a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=self.HEADERS)
            if not exists:
                w.writeheader()
            w.writerow(row)
        logger.info("Portfolio → %s | %s @ %.2f | %s | PnL=%.2f", match_name, selection, odds, result or "PENDING", pnl)
        return row

    def get_league_learning_stats(self) -> pd.DataFrame:
        """
        Returns a DataFrame showing how each league's weights have evolved
        vs the global defaults — useful for the Calibration UI.
        """
        global_defaults = {
            "form_weight": 0.60, "dna_weight": 0.40,
            "goals_weight": 0.45, "shots_ot_weight": 0.30,
            "possession_weight": 0.25, "home_advantage": 1.07,
            "away_penalty": 0.95,
        }
        lw_all = self.weights.get("league_weights", {})
        rows = []
        for league, lw in lw_all.items():
            if league == "default":
                continue
            sc = int(lw.get("sample_count", 0))
            row = {
                "League":       league,
                "Samples":      sc,
                "Confidence":   f"{min(sc/5*100, 100):.0f}%",
                "form_w":       round(float(lw.get("form_weight",      0.60)), 4),
                "dna_w":        round(float(lw.get("dna_weight",       0.40)), 4),
                "goals_w":      round(float(lw.get("goals_weight",     0.45)), 4),
                "home_adv":     round(float(lw.get("home_advantage",   1.07)), 4),
                "Δ form_w":     round(float(lw.get("form_weight", 0.60)) - global_defaults["form_weight"],      4),
                "Δ goals_w":    round(float(lw.get("goals_weight",0.45)) - global_defaults["goals_weight"],     4),
                "Δ home_adv":   round(float(lw.get("home_advantage",1.07)) - global_defaults["home_advantage"], 4),
            }
            rows.append(row)

        if not rows:
            return pd.DataFrame(columns=["League","Samples","Confidence","form_w","dna_w","goals_w","home_adv","Δ form_w","Δ goals_w","Δ home_adv"])
        return pd.DataFrame(rows).sort_values("Samples", ascending=False).reset_index(drop=True)

    def portfolio_summary(self) -> pd.DataFrame | None:
        if not PORTFOLIO_PATH.exists():
            return None
        df = pd.read_csv(PORTFOLIO_PATH)
        return df if not df.empty else None
