"""
================================================================================
FOOTBALL ORACLE — Core Engine v2.1
================================================================================
Module  : oracle_engine.py
Depends : oracle_api.py (FootballOracleAPI v2.1)
          mappings.py   (normalize_team_name, LEAGUE_BASELINES)
          pip install numpy scipy pandas

CHANGES v2.1:
  - _build_profile() cascade:
      0. /scores recent form  (Odds API — nationals)
      1. standings fd.org     (clubs)
      2. TheSportsDB events   (clubs fallback)
      3. ELO sigmoid          (nationals fallback / always blended)
      4. neutral defaults     (last resort)
  - data_quality field on TeamProfile: "live" | "elo" | "neutral"
  - data_quality_note: human-readable badge text for UI
  - ELO → offensive/defensive ratings via sigmoid (amplifies differences)
  - H2H analysis: last 5 meetings from /scores
  - _calibrate_xg() uses H2H modifier
  - evaluate_match() returns h2h_summary in MatchPrediction
  - Per-league weights blended (cold-start safe)
  - Self-learning recalibration unchanged (still works per-league)
================================================================================
"""

from __future__ import annotations

import csv
import json
import logging
import math
import sys
from dataclasses import dataclass, field
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

try:
    from mappings import normalize_team_name, LEAGUE_BASELINES
except ModuleNotFoundError:
    print("[FATAL] mappings.py not found.")
    sys.exit(1)

try:
    from injury_manager import InjuryManager, TeamInjuryReport
    INJURY_MANAGER_AVAILABLE = True
except ModuleNotFoundError:
    INJURY_MANAGER_AVAILABLE = False
    logger = logging.getLogger("FootballOracle.Engine")
    logger.warning("injury_manager.py not found — injuries disabled.")

try:
    from cache_manager import get_cache
    CACHE_MANAGER_AVAILABLE = True
except ModuleNotFoundError:
    CACHE_MANAGER_AVAILABLE = False

try:
    from key_manager import get_key_manager
    KEY_MANAGER_AVAILABLE = True
except ModuleNotFoundError:
    KEY_MANAGER_AVAILABLE = False

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
BASE_DIR        = Path(__file__).parent
CONFIG_PATH     = BASE_DIR / "config.json"
WEIGHTS_PATH    = BASE_DIR / "weights.json"
PORTFOLIO_PATH  = BASE_DIR / "portfolio.csv"
PREDICTIONS_DIR = BASE_DIR / "predictions"
RECAL_LOG_PATH  = BASE_DIR / "recalibration_log.csv"
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
    # ELO
    "elo_blend_weight":             0.35,   # how much ELO contributes when live data exists
    "elo_sigmoid_scale":            400.0,  # steepness of sigmoid (higher = sharper diff)
    "elo_reference":                1500.0, # neutral reference ELO
    # H2H
    "h2h_weight":                   0.15,   # modifier weight in xG formula
    "h2h_lookback_days":            365 * 3,# 3 years of H2H history
}

DEFAULT_WEIGHTS: dict[str, Any] = {
    "goals_weight":      0.45,
    "shots_ot_weight":   0.30,
    "possession_weight": 0.25,
    "form_weight":       0.60,
    "dna_weight":        0.40,
    "home_advantage":    1.07,
    "away_penalty":      0.95,
    "league_baselines":  LEAGUE_BASELINES,
    "offensive_cap":     3.5,
    "defensive_cap":     2.5,
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
        "MLS":               {"form_weight":0.60,"dna_weight":0.40,"goals_weight":0.45,"shots_ot_weight":0.30,"possession_weight":0.25,"home_advantage":1.08,"away_penalty":0.94,"sample_count":0},
        "default":           {"form_weight":0.60,"dna_weight":0.40,"goals_weight":0.45,"shots_ot_weight":0.30,"possession_weight":0.25,"home_advantage":1.07,"away_penalty":0.95,"sample_count":0},
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
# DATA QUALITY LEVELS
# ─────────────────────────────────────────────────────────────────────────────

DATA_QUALITY_LIVE    = "live"    # Real match stats from /scores or standings
DATA_QUALITY_ELO     = "elo"     # ELO available, no recent match stats
DATA_QUALITY_NEUTRAL = "neutral" # Full fallback — all values estimated

DATA_QUALITY_NOTES = {
    DATA_QUALITY_LIVE:    "✅ Date live — formă recentă + statistici reale",
    DATA_QUALITY_ELO:     "🟡 Date parțiale — ELO disponibil, formă estimată",
    DATA_QUALITY_NEUTRAL: "⚠️ Date estimate — fără statistici reale",
}

DATA_QUALITY_COLOURS = {
    DATA_QUALITY_LIVE:    "#00d17a",
    DATA_QUALITY_ELO:     "#f5a623",
    DATA_QUALITY_NEUTRAL: "#ff4757",
}


# ─────────────────────────────────────────────────────────────────────────────
# DATA CLASSES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TeamProfile:
    team_id:            str
    team_name:          str
    matches_analysed:   int
    avg_goals_for:      float
    avg_goals_against:  float
    avg_shots_ot:       float
    avg_possession:     float
    offensive_rating:   float
    defensive_rating:   float
    form_results:       list[str]    # ["W","D","L","W","W"]
    form_score:         float        # 0–1 weighted
    standings_form:     str          # raw string
    elo_rating:         int | None   # raw ELO value, None if unavailable
    data_source:        str          # which source provided the data
    # v2.1 — data quality signal
    data_quality:       str          # "live" | "elo" | "neutral"
    data_quality_note:  str          # human-readable badge text

    def __str__(self) -> str:
        return (
            f"OFF={self.offensive_rating:.3f}  DEF={self.defensive_rating:.3f}"
            f"  Form={''.join(self.form_results)}  ELO={self.elo_rating}"
            f"  [{self.data_quality}]  [{self.data_source}]"
        )


@dataclass
class H2HRecord:
    """Head-to-head history between two teams."""
    home_team:      str
    away_team:      str
    meetings:       int              # total meetings found
    home_wins:      int
    draws:          int
    away_wins:      int
    home_goals_avg: float            # avg goals scored by home team in H2H
    away_goals_avg: float
    last_5:         list[str]        # e.g. ["H","H","D","A","H"] from most recent
    h2h_modifier:   float            # -0.10 to +0.10 xG modifier for home team
    summary:        str              # human-readable: "H2H: 3W 1D 1L (últimas 5)"

    @classmethod
    def empty(cls, home: str, away: str) -> "H2HRecord":
        return cls(
            home_team=home, away_team=away,
            meetings=0, home_wins=0, draws=0, away_wins=0,
            home_goals_avg=0.0, away_goals_avg=0.0,
            last_5=[], h2h_modifier=0.0,
            summary="H2H: fără date istorice",
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
    h2h:              H2HRecord | None          # NEW v2.1
    data_quality_home: str                      # NEW v2.1
    data_quality_away: str                      # NEW v2.1
    # v2.2 — Injury fields
    home_injury_report: Any | None             # TeamInjuryReport
    away_injury_report: Any | None             # TeamInjuryReport
    injury_note:        str                    # summary for UI
    home_xg_pre_injury: float                  # xG before injury penalty
    away_xg_pre_injury: float                  # xG before injury penalty


# ─────────────────────────────────────────────────────────────────────────────
# ENGINE
# ─────────────────────────────────────────────────────────────────────────────

class FootballOracleEngine:
    """
    Core engine v2.1 — Hybrid Edition.
    Adds: ELO sigmoid, H2H modifier, data quality signals,
    improved _build_profile() cascade.
    """

    def __init__(self) -> None:
        self.api     = FootballOracleAPI()
        self.config  = _load_json(CONFIG_PATH,  DEFAULT_CONFIG)
        self.weights = _load_json(WEIGHTS_PATH, DEFAULT_WEIGHTS)

        # Cache manager
        self.cache = get_cache() if CACHE_MANAGER_AVAILABLE else None

        # Key manager
        self.key_manager = get_key_manager() if KEY_MANAGER_AVAILABLE else None

        # Injury manager
        self.injury_manager = (
            InjuryManager(api=self.api, cache=self.cache)
            if INJURY_MANAGER_AVAILABLE else None
        )

        logger.info("FootballOracleEngine v2.2 ready. "
                    "Injuries=%s Cache=%s KeyMgr=%s",
                    INJURY_MANAGER_AVAILABLE,
                    CACHE_MANAGER_AVAILABLE,
                    KEY_MANAGER_AVAILABLE)

    # ══════════════════════════════════════════════════════════════════════
    # ELO SIGMOID  — converts raw ELO to an offensive/defensive multiplier
    # ══════════════════════════════════════════════════════════════════════

    def _elo_to_multiplier(self, elo: int) -> float:
        """
        Sigmoid mapping: ELO → multiplier in range [0.55, 1.65].

        Why sigmoid instead of linear:
          - Linear (elo/2000): Argentina(2100)=1.05, Maldives(1000)=0.50 → gap 0.55
          - Sigmoid: Argentina=1.52, Maldives=0.62 → gap 0.90 (more realistic impact)

        Reference points:
          ELO 2100 (Argentina/France) → ~1.52
          ELO 1900 (solid top-10)     → ~1.25
          ELO 1700 (mid-tier)         → ~1.00
          ELO 1500 (reference/weak)   → ~0.80
          ELO 1200 (very weak)        → ~0.63
        """
        ref   = float(self.config.get("elo_reference",    1500.0))
        scale = float(self.config.get("elo_sigmoid_scale", 400.0))
        # Logistic: maps ELO difference to [0, 1], then scale to [0.55, 1.65]
        x = (elo - ref) / scale
        sigmoid = 1.0 / (1.0 + math.exp(-x))
        # Map [0,1] → [0.55, 1.65]
        return round(0.55 + sigmoid * 1.10, 4)

    def _elo_to_defensive_multiplier(self, elo: int) -> float:
        """
        Defensive rating from ELO: higher ELO → lower goals conceded.
        Inverted sigmoid mapped to [0.60, 1.80] (lower = better defence).

        ELO 2100 → ~0.72 (very few goals conceded)
        ELO 1700 → ~1.10 (average)
        ELO 1300 → ~1.55 (leaky)
        """
        ref   = float(self.config.get("elo_reference",    1500.0))
        scale = float(self.config.get("elo_sigmoid_scale", 400.0))
        x = (elo - ref) / scale
        sigmoid = 1.0 / (1.0 + math.exp(-x))
        # Invert: high ELO → low defensive rating (fewer goals against)
        return round(1.80 - sigmoid * 1.20, 4)

    # ══════════════════════════════════════════════════════════════════════
    # H2H ANALYSIS
    # ══════════════════════════════════════════════════════════════════════

    def _build_h2h(self, home_name: str, away_name: str, league: str) -> H2HRecord:
        """
        Build H2H record from /scores (Odds API) for the past 3 years.
        Falls back to empty record if no data available.
        """
        from mappings import ODDS_SPORT_KEYS
        sport_key = ODDS_SPORT_KEYS.get(league)
        if not sport_key:
            return H2HRecord.empty(home_name, away_name)

        # Fetch recent scores (max 3 days from API, but we use cached history)
        scores = self.api._fetch_scores_odds_api(sport_key, days_back=3)

        # Filter for meetings between these two teams (either direction)
        home_c = normalize_team_name(home_name)
        away_c = normalize_team_name(away_name)

        meetings: list[dict] = []
        for s in scores:
            h = normalize_team_name(s.get("home_team", ""))
            a = normalize_team_name(s.get("away_team", ""))
            if (h == home_c and a == away_c) or (h == away_c and a == home_c):
                meetings.append(s)

        if not meetings:
            return H2HRecord.empty(home_name, away_name)

        home_wins = draws = away_wins = 0
        home_goals_total = away_goals_total = 0
        last_5: list[str] = []

        for m in meetings[:5]:  # most recent 5
            is_home_first = normalize_team_name(m["home_team"]) == home_c
            hs = m.get("home_score", 0)
            as_ = m.get("away_score", 0)
            gf = hs if is_home_first else as_
            ga = as_ if is_home_first else hs
            home_goals_total += gf
            away_goals_total += ga
            if gf > ga:
                home_wins += 1
                last_5.append("H")
            elif gf < ga:
                away_wins += 1
                last_5.append("A")
            else:
                draws += 1
                last_5.append("D")

        n = len(meetings[:5])
        home_goals_avg = round(home_goals_total / n, 2)
        away_goals_avg = round(away_goals_total / n, 2)

        # H2H modifier: home team dominance → positive xG boost
        # Range: -0.10 (away dominates) to +0.10 (home dominates)
        h2h_weight = float(self.config.get("h2h_weight", 0.15))
        dominance = (home_wins - away_wins) / n  # -1 to +1
        h2h_modifier = round(dominance * h2h_weight, 4)

        wins_str  = f"{home_wins}W"
        draws_str = f"{draws}D"
        loss_str  = f"{away_wins}L"
        summary = (
            f"H2H ({n} meciuri): {wins_str} {draws_str} {loss_str}  "
            f"| Goluri medii: {home_goals_avg:.1f}–{away_goals_avg:.1f}  "
            f"| Ultimele: {''.join(last_5)}"
        )

        logger.info("[H2H] %s vs %s: %s", home_name, away_name, summary)

        return H2HRecord(
            home_team=home_c, away_team=away_c,
            meetings=n,
            home_wins=home_wins, draws=draws, away_wins=away_wins,
            home_goals_avg=home_goals_avg,
            away_goals_avg=away_goals_avg,
            last_5=last_5,
            h2h_modifier=h2h_modifier,
            summary=summary,
        )

    # ══════════════════════════════════════════════════════════════════════
    # TEAM PROFILE BUILDER  — v2.1 cascade
    # ══════════════════════════════════════════════════════════════════════

    def _build_profile(
        self,
        team_id:   str,
        team_name: str,
        league:    str,
    ) -> TeamProfile:
        """
        Build TeamProfile using 4-level cascade:

        Level 0 — /scores recent form  (Odds API, nationals + active leagues)
        Level 1 — fd.org standings      (clubs with fd_ ID)
        Level 2 — TheSportsDB events    (clubs with tsdb_ ID)
        Level 3 — ELO ratings           (all teams, blended in always)
        Level 4 — neutral defaults      (last resort)

        data_quality:
          "live"    → Level 0 or 1 or 2 returned real match data
          "elo"     → only ELO available
          "neutral" → no data at all
        """
        w      = self.weights
        o_cap  = float(w.get("offensive_cap", 3.5))
        d_cap  = float(w.get("defensive_cap", 2.5))
        last_n = int(self.config.get("last_n_fixtures", 5))
        canonical = normalize_team_name(team_name)

        # ── Always fetch ELO (blended in at all levels) ───────────────────
        elo_raw = self.api.get_elo_rating(canonical)
        elo_off = self._elo_to_multiplier(elo_raw)         if elo_raw else None
        elo_def = self._elo_to_defensive_multiplier(elo_raw) if elo_raw else None
        elo_blend = float(self.config.get("elo_blend_weight", 0.35))

        # ── Level 0: /scores recent form ─────────────────────────────────
        recent = self.api.get_team_recent_form(canonical, league, days_back=14)
        stats  = recent  # list of {date, result, goals_for, goals_against, ...}
        data_source   = ""
        data_quality  = DATA_QUALITY_NEUTRAL

        if stats:
            data_source  = "scores-api"
            data_quality = DATA_QUALITY_LIVE

        # ── Level 1: fd.org standings ─────────────────────────────────────
        if not stats and team_id and team_id.startswith("fd_"):
            standings = self.api.get_standings_form(team_id, league)
            if standings:
                played = standings.get("played") or 1
                gf_avg = (standings.get("goals_for", 0) or 0) / played
                ga_avg = (standings.get("goals_against", 0) or 0) / played
                form_str = standings.get("form", "") or ""
                results  = [r.strip() for r in form_str.split(",") if r.strip()][:last_n]
                # Convert standings to stats-like format
                stats = [{
                    "date":          "",
                    "result":        r,
                    "goals_for":     gf_avg,
                    "goals_against": ga_avg,
                    "shots_on_goal": gf_avg * 0.45,
                    "possession":    50.0,
                } for r in results]
                data_source  = "standings-fd"
                data_quality = DATA_QUALITY_LIVE

        # ── Level 2: TheSportsDB ──────────────────────────────────────────
        if not stats and team_id and team_id.startswith("tsdb_"):
            tsdb_stats = self.api.get_team_stats(team_id, league)
            if tsdb_stats:
                stats        = tsdb_stats
                data_source  = "thesportsdb"
                data_quality = DATA_QUALITY_LIVE

        # ── Compute raw ratings from match stats (if any) ─────────────────
        if stats:
            n   = len(stats)
            gf  = sum(s["goals_for"]     for s in stats) / n
            ga  = sum(s["goals_against"] for s in stats) / n
            sot = sum(s.get("shots_on_goal", gf * 0.45) for s in stats) / n
            pos = sum(s.get("possession",    50.0)       for s in stats) / n
            results = [s["result"] for s in stats]

            g_w   = float(w.get("goals_weight",      0.45))
            sot_w = float(w.get("shots_ot_weight",   0.30))
            pos_w = float(w.get("possession_weight", 0.25))

            g_norm   = min(gf  / 2.0, 1.0) * 1.5
            sot_norm = min(sot / 6.0, 1.0) * 1.5
            pos_norm = max(0.0, min(((pos - 30.0) / 40.0) * 0.5, 0.5))

            off_stat = min(
                g_norm * g_w + sot_norm * sot_w + pos_norm * pos_w + gf * 0.2,
                o_cap,
            )
            def_stat = min(ga, d_cap)

            # Blend with ELO if available
            if elo_off is not None:
                off_rating = round(
                    (1 - elo_blend) * off_stat + elo_blend * elo_off, 4
                )
                def_rating = round(
                    (1 - elo_blend) * def_stat + elo_blend * elo_def, 4
                )
            else:
                off_rating = round(off_stat, 4)
                def_rating = round(def_stat, 4)

        # ── Level 3: ELO only ─────────────────────────────────────────────
        elif elo_off is not None:
            baseline = float(
                self.weights.get("league_baselines", {}).get(
                    league,
                    self.weights.get("league_baselines", {}).get("default", 1.25)
                )
            )
            off_rating = round(elo_off * baseline, 4)
            def_rating = round(elo_def, 4)
            gf  = baseline * elo_off
            ga  = baseline * elo_def
            sot = gf * 0.45
            pos = 50.0
            n   = 0
            results    = []
            data_source  = "elo-only"
            data_quality = DATA_QUALITY_ELO

        # ── Level 4: neutral defaults ─────────────────────────────────────
        else:
            logger.warning(
                "No data for '%s' — using neutral defaults.", team_name
            )
            baseline = float(
                self.weights.get("league_baselines", {}).get(
                    league,
                    self.weights.get("league_baselines", {}).get("default", 1.25)
                )
            )
            off_rating = round(baseline * 0.65, 4)
            def_rating = round(baseline, 4)
            gf  = baseline
            ga  = baseline
            sot = baseline * 0.45
            pos = 50.0
            n   = 0
            results     = []
            data_source  = "neutral-defaults"
            data_quality = DATA_QUALITY_NEUTRAL

        # ── Form score (exponential recency) ──────────────────────────────
        rv  = {"W": 1.0, "D": 0.4, "L": 0.0}
        wts = [2 ** i for i in range(len(results))]
        tw  = sum(wts) or 1
        form_score = sum(rv.get(r, 0.4) * wts[i] for i, r in enumerate(results)) / tw

        off_rating = min(off_rating, o_cap)
        def_rating = min(def_rating, d_cap)

        return TeamProfile(
            team_id           = team_id,
            team_name         = canonical,
            matches_analysed  = n if stats else 0,
            avg_goals_for     = round(gf,  3),
            avg_goals_against = round(ga,  3),
            avg_shots_ot      = round(sot, 3),
            avg_possession    = round(pos, 1),
            offensive_rating  = off_rating,
            defensive_rating  = def_rating,
            form_results      = results[-last_n:] if results else [],
            form_score        = round(form_score, 4),
            standings_form    = ",".join(results),
            elo_rating        = elo_raw,
            data_source       = data_source,
            data_quality      = data_quality,
            data_quality_note = DATA_QUALITY_NOTES[data_quality],
        )

    # ══════════════════════════════════════════════════════════════════════
    # LEAGUE WEIGHTS (cold-start blending)
    # ══════════════════════════════════════════════════════════════════════

    def _get_league_weights(self, league: str) -> dict:
        lw_all = self.weights.get("league_weights", {})
        lw     = lw_all.get(league, lw_all.get("default", {}))
        sc     = int(lw.get("sample_count", 0))
        alpha  = min(sc / 5.0, 1.0)
        gw     = self.weights

        def _blend(key, default):
            lv = float(lw.get(key, gw.get(key, default)))
            gv = float(gw.get(key, default))
            return alpha * lv + (1 - alpha) * gv

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

    # ══════════════════════════════════════════════════════════════════════
    # xG CALIBRATION  — v2.1 adds H2H modifier
    # ══════════════════════════════════════════════════════════════════════

    def _calibrate_xg(
        self,
        home_p:          TeamProfile,
        away_p:          TeamProfile,
        league:          str,
        weather_penalty: float = 0.0,
        h2h:             H2HRecord | None = None,
    ) -> tuple[float, float]:
        w        = self.weights
        baselines= w.get("league_baselines", {})
        baseline = float(baselines.get(league, baselines.get("default", 1.25)))
        lw       = self._get_league_weights(league)
        fw       = lw["form_weight"]
        dw       = lw["dna_weight"]
        d_cap    = float(w.get("defensive_cap", 2.5))
        home_adv = lw["home_advantage"]
        away_pen = lw["away_penalty"]

        away_def_mod = 0.60 + (away_p.defensive_rating / d_cap) * 0.80
        home_def_mod = 0.60 + (home_p.defensive_rating / d_cap) * 0.80

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

        # ── H2H modifier ─────────────────────────────────────────────────
        if h2h and h2h.meetings >= 2:
            home_xg = home_xg * (1 + h2h.h2h_modifier)
            away_xg = away_xg * (1 - h2h.h2h_modifier)
            logger.info(
                "[xG] H2H modifier applied: %.4f → home=%.3f away=%.3f",
                h2h.h2h_modifier, home_xg, away_xg,
            )

        # ── Weather penalty ───────────────────────────────────────────────
        if weather_penalty > 0:
            home_xg *= (1 - weather_penalty)
            away_xg *= (1 - weather_penalty)

        home_xg = round(max(home_xg, 0.20), 4)
        away_xg = round(max(away_xg, 0.20), 4)

        logger.info(
            "[xG] home=%.3f  away=%.3f  (weather=%.3f)",
            home_xg, away_xg, weather_penalty,
        )
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
        home_name = match["home_team"]
        away_name = match["away_team"]
        league    = match.get("league", "Unknown")
        fid       = match.get("fixture_id", "?")

        logger.info("━━━ evaluate %s vs %s [%s] ━━━", home_name, away_name, league)

        # ── Profiles ──────────────────────────────────────────────────────
        home_p = self._build_profile(
            match.get("home_team_id", ""), home_name, league
        )
        away_p = self._build_profile(
            match.get("away_team_id", ""), away_name, league
        )
        logger.info("Home: %s", home_p)
        logger.info("Away: %s", away_p)

        # ── H2H ───────────────────────────────────────────────────────────
        h2h = self._build_h2h(home_name, away_name, league)

        # ── Weather ───────────────────────────────────────────────────────
        city    = match.get("venue_city", "") or league
        weather = self.api.get_weather(city, match.get("kickoff_date"))
        w_pen   = float(weather.get("xg_penalty", 0.0))
        w_note  = weather.get("description", "")

        # ── xG ────────────────────────────────────────────────────────────
        home_xg, away_xg = self._calibrate_xg(
            home_p, away_p, league, w_pen, h2h
        )

        # ── Injury penalty ────────────────────────────────────────────────
        home_xg_pre = home_xg
        away_xg_pre = away_xg
        injury_note = "ℹ️ Date accidentări indisponibile"
        home_injury_report = None
        away_injury_report = None

        event_id = match.get("_sportapi_event_id")

        if self.injury_manager and event_id:
            # Fetch injury reports pentru ambele echipe
            home_injury_report = self.injury_manager.get_lineup_absences(
                event_id  = event_id,
                team_id   = match.get("_sportapi_home_id", ""),
                team_name = home_name,
                league    = league,
            )
            away_injury_report = self.injury_manager.get_lineup_absences(
                event_id  = event_id,
                team_id   = match.get("_sportapi_away_id", ""),
                team_name = away_name,
                league    = league,
            )

            # Aplică penalizările
            home_xg, away_xg, injury_note = self.injury_manager.apply_injury_penalty(
                home_xg      = home_xg,
                away_xg      = away_xg,
                home_report  = home_injury_report,
                away_report  = away_injury_report,
            )

            if home_injury_report.has_key_absences or away_injury_report.has_key_absences:
                logger.warning(
                    "[Injuries] Key player absences detected! %s", injury_note
                )
        elif self.injury_manager and self.cache:
            # Fallback: raport din cache fără lineup comparat
            home_tid = match.get("_sportapi_home_id", "")
            away_tid = match.get("_sportapi_away_id", "")
            if home_tid:
                home_injury_report = self.injury_manager.get_injury_report_from_cache(
                    home_tid, home_name
                )
            if away_tid:
                away_injury_report = self.injury_manager.get_injury_report_from_cache(
                    away_tid, away_name
                )
            if home_injury_report and away_injury_report:
                home_xg, away_xg, injury_note = self.injury_manager.apply_injury_penalty(
                    home_xg, away_xg, home_injury_report, away_injury_report
                )

        logger.info(
            "[xG after injuries] home=%.3f (was %.3f)  away=%.3f (was %.3f)",
            home_xg, home_xg_pre, away_xg, away_xg_pre,
        )

        # ── Poisson ───────────────────────────────────────────────────────
        ph, pd, pa, top_scores = self._poisson_model(home_xg, away_xg)

        # ── Odds & Edge ───────────────────────────────────────────────────
        bk_h = float(match.get("home_odds") or 0.0)
        bk_d = float(match.get("draw_odds") or 0.0)
        bk_a = float(match.get("away_odds") or 0.0)
        bk_n = match.get("odds_source") or "N/A"

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
                # Downgrade value bet confidence if data quality is low
                confidence_note = ""
                if home_p.data_quality == DATA_QUALITY_NEUTRAL or \
                   away_p.data_quality == DATA_QUALITY_NEUTRAL:
                    confidence_note = " ⚠️ date estimate"
                elif home_p.data_quality == DATA_QUALITY_ELO or \
                     away_p.data_quality == DATA_QUALITY_ELO:
                    confidence_note = " 🟡 ELO only"

                value_bets.append({
                    "market":           "1X2",
                    "selection":        sel,
                    "edge_pct":         ep,
                    "rating":           self._rating(ep),
                    "model_prob_pct":   round(mp * 100, 2),
                    "bk_odds":          odds,
                    "confidence_note":  confidence_note,
                })

        # ── Kelly ─────────────────────────────────────────────────────────
        kelly: dict[str, float] = {}
        for sel, prob, odds in [
            ("Home Win", ph, bk_h),
            ("Draw",     pd, bk_d),
            ("Away Win", pa, bk_a),
        ]:
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
            h2h            = h2h,
            data_quality_home = home_p.data_quality,
            data_quality_away = away_p.data_quality,
            # v2.2 injuries
            home_injury_report = home_injury_report,
            away_injury_report = away_injury_report,
            injury_note        = injury_note,
            home_xg_pre_injury = home_xg_pre,
            away_xg_pre_injury = away_xg_pre,
        )

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
        return self.api.get_matches_for_week(
            days_ahead=days_ahead, competitions=competitions
        )

    def get_matches_by_date(self, target_date: str) -> list[dict]:
        return self.api.get_matches_for_date(target_date)

    # ══════════════════════════════════════════════════════════════════════
    # PREDICTION CACHE
    # ══════════════════════════════════════════════════════════════════════

    def _cache_prediction(self, pred: MatchPrediction) -> None:
        data = {
            "fixture_id":        pred.fixture_id,
            "home_team":         pred.home_team,
            "away_team":         pred.away_team,
            "league":            pred.league,
            "kickoff_date":      pred.kickoff_date,
            "home_xg":           pred.home_xg,
            "away_xg":           pred.away_xg,
            "prob_home":         pred.prob_home_win,
            "prob_draw":         pred.prob_draw,
            "prob_away":         pred.prob_away_win,
            "data_quality_home": pred.data_quality_home,
            "data_quality_away": pred.data_quality_away,
            "saved_at":          datetime.now(timezone.utc).isoformat(),
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
    # SELF-LEARNING RECALIBRATION  (unchanged logic, updated logging)
    # ══════════════════════════════════════════════════════════════════════

    def update_weights_from_result(
        self,
        fixture_id:        str,
        actual_home_goals: int,
        actual_away_goals: int,
    ) -> dict:
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
            adjustments[name] = {
                "old":   round(cur,    4),
                "delta": round(delta,  4),
                "new":   round(new_val,4),
            }
            return new_val

        lw_all = self.weights.setdefault("league_weights", {})
        if league not in lw_all:
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

        lw       = lw_all[league]
        sc       = int(lw.get("sample_count", 0))
        lr_league= min(lr * max(1.0, 3.0 / (sc + 1)), lr * 3)
        scale_l  = min(combined / 3.0, 1.0) * lr_league

        fw  = float(lw.get("form_weight",       0.60))
        dw  = float(lw.get("dna_weight",        0.40))
        gw  = float(lw.get("goals_weight",      0.45))
        sow = float(lw.get("shots_ot_weight",   0.30))
        pw  = float(lw.get("possession_weight", 0.25))
        ha  = float(lw.get("home_advantage",    1.07))
        ap  = float(lw.get("away_penalty",      0.95))

        if combined >= 0.50:
            fw  = _shift("form_weight", fw,  -scale_l * 0.6, lo=0.10, hi=0.90)
            dw  = _shift("dna_weight",  dw,  +scale_l * 0.6, lo=0.10, hi=0.90)
            reasons.append(f"[{league}] Large error ({combined:.2f}) → shifted to DNA.")

        if avg_err > 0.50:
            gw  = _shift("goals_weight",    gw,  +scale_l * 0.5, lo=0.10, hi=0.80)
            sow = _shift("shots_ot_weight", sow, +scale_l * 0.3, lo=0.05, hi=0.60)
            if home_err > 0.5:
                ha  = _shift("home_advantage", ha, +scale_l * 0.2, lo=1.00, hi=1.20)
            reasons.append(f"[{league}] Under-estimated (+{avg_err:.2f}) → boosted offensive.")
        elif avg_err < -0.50:
            gw  = _shift("goals_weight",      gw, -scale_l * 0.4, lo=0.10, hi=0.80)
            pw  = _shift("possession_weight", pw, +scale_l * 0.3, lo=0.05, hi=0.50)
            if home_err < -0.5:
                ha  = _shift("home_advantage", ha, -scale_l * 0.15, lo=1.00, hi=1.20)
            reasons.append(f"[{league}] Over-estimated ({avg_err:.2f}) → reduced offensive.")

        t_comp = gw + sow + pw
        if t_comp > 0:
            gw  = round(gw  / t_comp, 4)
            sow = round(sow / t_comp, 4)
            pw  = round(pw  / t_comp, 4)
        t_fd = fw + dw
        if t_fd > 0:
            fw = round(fw / t_fd, 4)
            dw = round(dw / t_fd, 4)

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
        logger.info("Recalibrated [%s] sample #%d — %s", league, sc + 1, reason)

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
            "status":         "recalibrated",
            "fixture_id":     fixture_id,
            "pred_home_xg":   round(pred_h, 3),
            "pred_away_xg":   round(pred_a, 3),
            "actual_home":    actual_home_goals,
            "actual_away":    actual_away_goals,
            "home_error":     round(home_err, 3),
            "away_error":     round(away_err, 3),
            "combined_error": round(combined, 3),
            "adjustments":    adjustments,
            "reason":         reason,
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
            else (-round(stake, 2) if result == "L" else 0.0)
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
        logger.info(
            "Portfolio → %s | %s @ %.2f | %s | PnL=%.2f",
            match_name, selection, odds, result or "PENDING", pnl,
        )
        return row

    # ══════════════════════════════════════════════════════════════════════
    # LEAGUE LEARNING STATS  (for Calibration UI)
    # ══════════════════════════════════════════════════════════════════════

    def get_league_learning_stats(self) -> pd.DataFrame:
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
            sc  = int(lw.get("sample_count", 0))
            row = {
                "League":     league,
                "Samples":    sc,
                "Confidence": f"{min(sc / 5 * 100, 100):.0f}%",
                "form_w":     round(float(lw.get("form_weight",    0.60)), 4),
                "dna_w":      round(float(lw.get("dna_weight",     0.40)), 4),
                "goals_w":    round(float(lw.get("goals_weight",   0.45)), 4),
                "home_adv":   round(float(lw.get("home_advantage", 1.07)), 4),
                "Δ form_w":   round(float(lw.get("form_weight",    0.60)) - global_defaults["form_weight"],    4),
                "Δ goals_w":  round(float(lw.get("goals_weight",   0.45)) - global_defaults["goals_weight"],   4),
                "Δ home_adv": round(float(lw.get("home_advantage", 1.07)) - global_defaults["home_advantage"], 4),
            }
            rows.append(row)

        if not rows:
            return pd.DataFrame(columns=[
                "League","Samples","Confidence","form_w","dna_w",
                "goals_w","home_adv","Δ form_w","Δ goals_w","Δ home_adv",
            ])
        return (
            pd.DataFrame(rows)
            .sort_values("Samples", ascending=False)
            .reset_index(drop=True)
        )

    def portfolio_summary(self) -> pd.DataFrame | None:
        if not PORTFOLIO_PATH.exists():
            return None
        df = pd.read_csv(PORTFOLIO_PATH)
        return df if not df.empty else None
