"""
================================================================================
FOOTBALL ORACLE — Core Engine v2.3 (reconciliat Free Live Football)
================================================================================
Module  : oracle_engine.py
CHANGES v2.3:
  - _build_profile() folosește Free Live Football (get_freelf_standings +
    get_team_form_freelf) ca sursă primară, cu cascade spre Odds API /
    fd.org / TSDB / ELO / neutral
  - _build_h2h() folosește get_h2h() (Free Live Football, _freelf_event_id)
  - injury_manager.get_lineup_absences() cu is_home: bool (semnătură v2.0)
  - ELO sigmoid blending, per-league weights, self-learning — neschimbate
================================================================================
"""
from __future__ import annotations

import csv, json, logging, math, sys
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
    print("[FATAL] oracle_api.py not found."); sys.exit(1)

try:
    from mappings import normalize_team_name, LEAGUE_BASELINES
except ModuleNotFoundError:
    print("[FATAL] mappings.py not found."); sys.exit(1)

try:
    from injury_manager import InjuryManager, TeamInjuryReport
    INJURY_MANAGER_AVAILABLE = True
except ModuleNotFoundError:
    INJURY_MANAGER_AVAILABLE = False

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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(levelname)s]  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("FootballOracle.Engine")

BASE_DIR        = Path(__file__).parent
CONFIG_PATH     = BASE_DIR / "config.json"
WEIGHTS_PATH    = BASE_DIR / "weights.json"
PORTFOLIO_PATH  = BASE_DIR / "portfolio.csv"
PREDICTIONS_DIR = BASE_DIR / "predictions"
RECAL_LOG_PATH  = BASE_DIR / "recalibration_log.csv"
PREDICTIONS_DIR.mkdir(exist_ok=True)

DEFAULT_CONFIG: dict[str, Any] = {
    "value_bet_threshold_pct":     5.0,
    "max_goals_poisson":           8,
    "last_n_fixtures":             5,
    "stake_default":               10.0,
    "kelly_fraction":              0.25,
    "recalibration_learning_rate": 0.05,
    "recalibration_max_delta":     0.15,
    "elo_blend_weight":            0.35,
    "elo_sigmoid_scale":           400.0,
    "elo_reference":               1500.0,
    "h2h_weight":                  0.15,
    "h2h_lookback_days":           1095,
    "monte_carlo_simulations":     10000,
}

DEFAULT_WEIGHTS: dict[str, Any] = {
    "goals_weight": 0.45, "shots_ot_weight": 0.30, "possession_weight": 0.25,
    "form_weight": 0.60, "dna_weight": 0.40,
    "home_advantage": 1.07, "away_penalty": 0.95,
    "offensive_cap": 3.5, "defensive_cap": 2.5,
    "league_baselines": LEAGUE_BASELINES,
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

DATA_QUALITY_LIVE    = "live"
DATA_QUALITY_ELO     = "elo"
DATA_QUALITY_NEUTRAL = "neutral"

DATA_QUALITY_NOTES = {
    DATA_QUALITY_LIVE:    "✅ Date live — statistici reale",
    DATA_QUALITY_ELO:     "🟡 Date parțiale — ELO disponibil",
    DATA_QUALITY_NEUTRAL: "⚠️ Date estimate — fără statistici reale",
}

def _load_json(path: Path, default: dict) -> dict:
    if not path.exists():
        path.write_text(json.dumps(default, indent=4), encoding="utf-8")
        return dict(default)
    try: return json.loads(path.read_text(encoding="utf-8"))
    except Exception: return dict(default)

def _save_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=4), encoding="utf-8")

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
    form_results:      list[str]
    form_score:        float
    standings_form:    str
    elo_rating:        int | None
    data_source:       str
    data_quality:      str
    data_quality_note: str

@dataclass
class H2HRecord:
    home_team:      str
    away_team:      str
    meetings:       int
    home_wins:      int
    draws:          int
    away_wins:      int
    home_goals_avg: float
    away_goals_avg: float
    last_5:         list[str]
    h2h_modifier:   float
    summary:        str

    @classmethod
    def empty(cls, home: str, away: str) -> "H2HRecord":
        return cls(home_team=home, away_team=away, meetings=0, home_wins=0,
                   draws=0, away_wins=0, home_goals_avg=0.0, away_goals_avg=0.0,
                   last_5=[], h2h_modifier=0.0, summary="H2H: fără date istorice")

@dataclass
class MatchPrediction:
    fixture_id:        str
    home_team:         str
    away_team:         str
    league:            str
    kickoff_utc:       str
    kickoff_date:      str
    season:            int
    home_xg:           float
    away_xg:           float
    prob_home_win:     float
    prob_draw:         float
    prob_away_win:     float
    top_scores:        list[tuple[int, int, float]]
    bk_home_odds:      float
    bk_draw_odds:      float
    bk_away_odds:      float
    bookmaker_name:    str
    impl_home_pct:     float
    impl_draw_pct:     float
    impl_away_pct:     float
    edge_home_pct:     float
    edge_draw_pct:     float
    edge_away_pct:     float
    value_bets:        list[dict]
    weather_note:      str
    weather_penalty:   float
    kelly_stakes:      dict[str, float]
    home_profile:      TeamProfile | None
    away_profile:      TeamProfile | None
    h2h:               H2HRecord | None
    data_quality_home: str
    data_quality_away: str
    home_injury_report: Any | None
    away_injury_report: Any | None
    injury_note:        str
    home_xg_pre_injury: float
    away_xg_pre_injury: float


class FootballOracleEngine:

    def __init__(self) -> None:
        self.api     = FootballOracleAPI()
        self.config  = _load_json(CONFIG_PATH,  DEFAULT_CONFIG)
        self.weights = _load_json(WEIGHTS_PATH, DEFAULT_WEIGHTS)
        self.cache       = get_cache()       if CACHE_MANAGER_AVAILABLE  else None
        self.key_manager = get_key_manager() if KEY_MANAGER_AVAILABLE    else None
        self.injury_manager = (
            InjuryManager(api=self.api, cache=self.cache)
            if INJURY_MANAGER_AVAILABLE else None
        )
        logger.info("FootballOracleEngine v2.2 ready. Injuries=%s Cache=%s KeyMgr=%s",
                    INJURY_MANAGER_AVAILABLE, CACHE_MANAGER_AVAILABLE, KEY_MANAGER_AVAILABLE)

    # ── ELO sigmoid ───────────────────────────────────────────────────────
    def _elo_to_multiplier(self, elo: int) -> float:
        ref   = float(self.config.get("elo_reference",    1500.0))
        scale = float(self.config.get("elo_sigmoid_scale", 400.0))
        sigmoid = 1.0 / (1.0 + math.exp(-((elo - ref) / scale)))
        return round(0.55 + sigmoid * 1.10, 4)

    def _elo_to_defensive_multiplier(self, elo: int) -> float:
        ref   = float(self.config.get("elo_reference",    1500.0))
        scale = float(self.config.get("elo_sigmoid_scale", 400.0))
        sigmoid = 1.0 / (1.0 + math.exp(-((elo - ref) / scale)))
        return round(1.80 - sigmoid * 1.20, 4)

    # ── H2H — v2.3 folosește Free Live Football ───────────────────────────
    def _build_h2h(self, home_name: str, away_name: str, match: dict) -> H2HRecord:
        event_id = match.get("_freelf_event_id")

        # ── Încearcă Free Live Football H2H ──────────────────────────────
        if event_id:
            try:
                freelf_h2h = self.api.get_h2h(int(event_id), home_name, away_name)
                if freelf_h2h and freelf_h2h.get("meetings", 0) >= 1:
                    return H2HRecord(
                        home_team      = normalize_team_name(home_name),
                        away_team      = normalize_team_name(away_name),
                        meetings       = freelf_h2h["meetings"],
                        home_wins      = freelf_h2h["home_wins"],
                        draws          = freelf_h2h["draws"],
                        away_wins      = freelf_h2h["away_wins"],
                        home_goals_avg = freelf_h2h["home_goals_avg"],
                        away_goals_avg = freelf_h2h["away_goals_avg"],
                        last_5         = freelf_h2h["last_5"],
                        h2h_modifier   = freelf_h2h["h2h_modifier"],
                        summary        = freelf_h2h["summary"],
                    )
            except Exception as exc:
                logger.warning("[H2H] FreeLF failed for event %s: %s", event_id, exc)

        # ── Fallback: Odds API /scores ────────────────────────────────────
        league    = match.get("league", "")
        from mappings import ODDS_SPORT_KEYS
        sport_key = ODDS_SPORT_KEYS.get(league)
        if not sport_key:
            return H2HRecord.empty(home_name, away_name)

        scores = self.api._fetch_scores_odds_api(sport_key, days_back=3)
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
        home_g = away_g = 0
        last_5: list[str] = []
        for m in meetings[:5]:
            is_home_first = normalize_team_name(m["home_team"]) == home_c
            hs = m.get("home_score", 0); as_ = m.get("away_score", 0)
            gf = hs if is_home_first else as_; ga = as_ if is_home_first else hs
            home_g += gf; away_g += ga
            if gf > ga:   home_wins += 1; last_5.append("H")
            elif gf < ga: away_wins += 1; last_5.append("A")
            else:         draws += 1;     last_5.append("D")

        n = len(meetings[:5])
        dominance    = (home_wins - away_wins) / n
        h2h_modifier = round(dominance * float(self.config.get("h2h_weight", 0.15)), 4)
        summary = (f"H2H ({n} meciuri): {home_wins}W {draws}D {away_wins}L | "
                   f"Goluri: {round(home_g/n,1)}–{round(away_g/n,1)} | Ultimele: {''.join(last_5)}")
        return H2HRecord(
            home_team=home_c, away_team=away_c, meetings=n,
            home_wins=home_wins, draws=draws, away_wins=away_wins,
            home_goals_avg=round(home_g/n,2), away_goals_avg=round(away_g/n,2),
            last_5=last_5, h2h_modifier=h2h_modifier, summary=summary,
        )

    # ── _build_profile — v2.3 cascade cu Free Live Football primar ────────
    def _build_profile(self, team_id: str, team_name: str, league: str) -> TeamProfile:
        """
        Cascade:
          0. Free Live Football standings (get_freelf_standings)   ← PRIMAR v2.3
          1. Free Live Football form      (get_team_form_freelf)   ← NOU v2.3
          2. Odds API /scores             (get_team_recent_form)
          3. fd.org standings             (get_standings_form)
          4. TheSportsDB events           (get_team_stats)
          5. ELO sigmoid                  (întotdeauna blended)
          6. Neutral defaults
        """
        w        = self.weights
        o_cap    = float(w.get("offensive_cap",  3.5))
        d_cap    = float(w.get("defensive_cap",  2.5))
        last_n   = int(self.config.get("last_n_fixtures", 5))
        canonical = normalize_team_name(team_name)

        # ELO — întotdeauna fetch (blended la toate nivelele)
        elo_raw   = self.api.get_elo_rating(canonical)
        elo_off   = self._elo_to_multiplier(elo_raw)           if elo_raw else None
        elo_def   = self._elo_to_defensive_multiplier(elo_raw) if elo_raw else None
        elo_blend = float(self.config.get("elo_blend_weight", 0.35))

        stats: list[dict] = []
        season_entry: dict | None = None
        data_source  = ""
        data_quality = DATA_QUALITY_NEUTRAL

        # ── Level -1: Date naționale hardcodate (World Cup + naționale) ───
        from mappings import NATIONAL_TEAM_STATS
        nat = NATIONAL_TEAM_STATS.get(canonical)
        if nat:
            gf  = float(nat["avg_gf"])
            ga  = float(nat["avg_ga"])
            sot = float(nat.get("avg_sot", gf * 0.45))
            pos = float(nat.get("avg_possession", 50.0))
            n   = int(nat.get("matches", 10))
            results = list(nat.get("form", []))
            stats = [{"result": r, "goals_for": gf, "goals_against": ga,
                      "shots_on_goal": sot, "possession": pos}
                     for r in (results or ["W"] * 5)]
            data_source  = "national-stats-hardcoded"
            data_quality = DATA_QUALITY_LIVE
            logger.info("[Profile] %s — national stats hardcoded (gf=%.2f ga=%.2f)", canonical, gf, ga)

        # ── Level 0: Free Live Football standings ─────────────────────────
        try:
            standings_list = self.api.get_freelf_standings(league)
            for entry in standings_list:
                if entry.get("team","").lower() == canonical.lower():
                    season_entry = entry
                    break
            if season_entry:
                gf  = season_entry.get("avg_gf", 1.25)
                ga  = season_entry.get("avg_ga", 1.25)
                sot = gf * 0.45
                pos = 50.0
                played = season_entry.get("played", 5)
                stats = [{"result": "W", "goals_for": gf, "goals_against": ga,
                          "shots_on_goal": sot, "possession": pos}] * min(played, 5)
                data_source  = "freelf-standings"
                data_quality = DATA_QUALITY_LIVE
        except Exception as exc:
            logger.warning("[Profile] FreeLF standings error for %s: %s", team_name, exc)

        # ── Level 1: Free Live Football form ──────────────────────────────
        recent_form: list[dict] = []
        try:
            freelf_id = season_entry.get("team_id") if season_entry else None
            if freelf_id:
                recent_form = self.api.get_team_form_freelf(int(freelf_id), league, last_n)
        except Exception as exc:
            logger.warning("[Profile] FreeLF form error for %s: %s", team_name, exc)

        # ── Level 2: Odds API /scores ─────────────────────────────────────
        if not stats:
            try:
                scores_form = self.api.get_team_recent_form(canonical, league, days_back=14)
                if scores_form:
                    stats        = scores_form
                    data_source  = "scores-api"
                    data_quality = DATA_QUALITY_LIVE
            except Exception:
                pass

        # ── Level 3: fd.org standings ─────────────────────────────────────
        if not stats and team_id and team_id.startswith("fd_"):
            try:
                fd_standings = self.api.get_standings_form(team_id, league)
                if fd_standings:
                    played   = fd_standings.get("played") or 1
                    gf_avg   = (fd_standings.get("goals_for", 0) or 0) / played
                    ga_avg   = (fd_standings.get("goals_against", 0) or 0) / played
                    form_str = fd_standings.get("form", "") or ""
                    results  = [r.strip() for r in form_str.split(",") if r.strip()][:last_n]
                    stats = [{"result": r, "goals_for": gf_avg, "goals_against": ga_avg,
                              "shots_on_goal": gf_avg*0.45, "possession": 50.0} for r in results]
                    data_source  = "standings-fd"
                    data_quality = DATA_QUALITY_LIVE
            except Exception:
                pass

        # ── Level 4: TheSportsDB ──────────────────────────────────────────
        if not stats and team_id and team_id.startswith("tsdb_"):
            try:
                tsdb_stats = self.api.get_team_stats(team_id, league)
                if tsdb_stats:
                    stats        = tsdb_stats
                    data_source  = "thesportsdb"
                    data_quality = DATA_QUALITY_LIVE
            except Exception:
                pass

        # ── Compute ratings din stats ─────────────────────────────────────
        if stats:
            n = len(stats)
            if season_entry:
                gf  = season_entry.get("avg_gf", sum(s["goals_for"]     for s in stats)/n)
                ga  = season_entry.get("avg_ga", sum(s["goals_against"] for s in stats)/n)
                sot = gf * 0.45
                pos = 50.0
            else:
                gf  = sum(s["goals_for"]     for s in stats) / n
                ga  = sum(s["goals_against"] for s in stats) / n
                sot = sum(s.get("shots_on_goal", gf*0.45) for s in stats) / n
                pos = sum(s.get("possession",    50.0)     for s in stats) / n

            # Form results — preferăm recent_form FreeLF dacă există
            form_source = recent_form if recent_form else stats
            results = [s["result"] for s in form_source]

            g_w   = float(w.get("goals_weight",      0.45))
            sot_w = float(w.get("shots_ot_weight",   0.30))
            pos_w = float(w.get("possession_weight", 0.25))

            g_norm   = min(gf  / 2.0, 1.0) * 1.5
            sot_norm = min(sot / 6.0, 1.0) * 1.5
            pos_norm = max(0.0, min(((pos - 30.0) / 40.0) * 0.5, 0.5))

            off_stat = min(g_norm*g_w + sot_norm*sot_w + pos_norm*pos_w + gf*0.2, o_cap)
            def_stat = min(ga, d_cap)

            if elo_off is not None:
                off_rating = round((1-elo_blend)*off_stat + elo_blend*elo_off, 4)
                def_rating = round((1-elo_blend)*def_stat + elo_blend*elo_def, 4)
            else:
                off_rating = round(off_stat, 4)
                def_rating = round(def_stat, 4)

        # ── Level 5: ELO only ─────────────────────────────────────────────
        elif elo_off is not None:
            baseline   = float(w.get("league_baselines",{}).get(league, w.get("league_baselines",{}).get("default",1.25)))
            off_rating = round(elo_off * baseline, 4)
            def_rating = round(elo_def, 4)
            gf  = baseline * elo_off; ga = baseline * elo_def
            sot = gf * 0.45; pos = 50.0; n = 0; results = []
            data_source  = "elo-only"
            data_quality = DATA_QUALITY_ELO

        # ── Level 6: Neutral defaults ─────────────────────────────────────
        else:
            baseline   = float(w.get("league_baselines",{}).get(league, w.get("league_baselines",{}).get("default",1.25)))
            logger.warning("No data for '%s' — neutral defaults.", team_name)
            off_rating = round(baseline * 0.65, 4)
            def_rating = round(baseline, 4)
            gf  = baseline; ga = baseline; sot = gf*0.45; pos = 50.0
            n = 0; results = []
            data_source  = "neutral-defaults"
            data_quality = DATA_QUALITY_NEUTRAL

        # ── Form score ────────────────────────────────────────────────────
        rv  = {"W": 1.0, "D": 0.4, "L": 0.0}
        wts = [2**i for i in range(len(results))]
        tw  = sum(wts) or 1
        form_score = sum(rv.get(r, 0.4)*wts[i] for i, r in enumerate(results)) / tw

        off_rating = min(off_rating, o_cap)
        def_rating = min(def_rating, d_cap)

        return TeamProfile(
            team_id=team_id, team_name=canonical,
            matches_analysed=n if stats else 0,
            avg_goals_for=round(gf,3), avg_goals_against=round(ga,3),
            avg_shots_ot=round(sot,3), avg_possession=round(pos,1),
            offensive_rating=off_rating, defensive_rating=def_rating,
            form_results=results[-last_n:] if results else [],
            form_score=round(form_score,4),
            standings_form=",".join(results),
            elo_rating=elo_raw, data_source=data_source,
            data_quality=data_quality,
            data_quality_note=DATA_QUALITY_NOTES[data_quality],
        )

    # ── League weights (cold-start blending) ──────────────────────────────
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

    # ── xG calibration ────────────────────────────────────────────────────
    def _calibrate_xg(self, home_p: TeamProfile, away_p: TeamProfile,
                      league: str, weather_penalty: float = 0.0,
                      h2h: H2HRecord | None = None) -> tuple[float, float]:
        w        = self.weights
        baselines= w.get("league_baselines", {})
        baseline = float(baselines.get(league, baselines.get("default", 1.25)))
        lw       = self._get_league_weights(league)
        fw       = lw["form_weight"]; dw = lw["dna_weight"]
        d_cap    = float(w.get("defensive_cap", 2.5))
        home_adv = lw["home_advantage"]; away_pen = lw["away_penalty"]

        away_def_mod  = 0.60 + (away_p.defensive_rating / d_cap) * 0.80
        home_def_mod  = 0.60 + (home_p.defensive_rating / d_cap) * 0.80
        home_form_mod = 0.80 + home_p.form_score * 0.40
        away_form_mod = 0.80 + away_p.form_score * 0.40

        home_xg = home_p.offensive_rating * away_def_mod * baseline * (fw*home_form_mod + dw) * home_adv
        away_xg = away_p.offensive_rating * home_def_mod * baseline * (fw*away_form_mod + dw) * away_pen

        if h2h and h2h.meetings >= 2:
            home_xg = home_xg * (1 + h2h.h2h_modifier)
            away_xg = away_xg * (1 - h2h.h2h_modifier)

        if weather_penalty > 0:
            home_xg *= (1 - weather_penalty); away_xg *= (1 - weather_penalty)

        home_xg = round(max(home_xg, 0.20), 4)
        away_xg = round(max(away_xg, 0.20), 4)
        logger.info("[xG] home=%.3f  away=%.3f  (weather=%.3f)", home_xg, away_xg, weather_penalty)
        return home_xg, away_xg

    # ── Poisson model ─────────────────────────────────────────────────────
    def _poisson_model(self, home_xg: float, away_xg: float) -> tuple[float, float, float, list]:
        max_g  = int(self.config.get("max_goals_poisson", 8))
        matrix = np.zeros((max_g+1, max_g+1))
        for hg in range(max_g+1):
            for ag in range(max_g+1):
                matrix[hg,ag] = poisson.pmf(hg, home_xg) * poisson.pmf(ag, away_xg)
        ph = float(np.sum(np.tril(matrix, -1)))
        pd = float(np.sum(np.diag(matrix)))
        pa = float(np.sum(np.triu(matrix,  1)))
        scores = sorted(
            [(hg, ag, round(matrix[hg,ag]*100, 2))
             for hg in range(max_g+1) for ag in range(max_g+1)],
            key=lambda x: x[2], reverse=True,
        )
        return ph, pd, pa, scores[:6]

    # ── Value bet helpers ─────────────────────────────────────────────────
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
        return round(float(self.config.get("stake_default",10.0)) *
                     kf * float(self.config.get("kelly_fraction",0.25)), 2)


    # ── Monte Carlo Simulator ─────────────────────────────────────────────
    def _monte_carlo(self, home_xg: float, away_xg: float,
                     n_sim: int = 10_000) -> dict:
        """
        Simulează n_sim meciuri independente cu distribuție Poisson.
        Returnează probabilități MC + confidence score.
        """
        rng = np.random.default_rng(seed=42)
        home_goals = rng.poisson(home_xg, n_sim)
        away_goals = rng.poisson(away_xg, n_sim)

        ph = float(np.mean(home_goals > away_goals))
        pd = float(np.mean(home_goals == away_goals))
        pa = float(np.mean(home_goals < away_goals))

        # ── Piețe speciale din simulare ───────────────────────────────────
        over25  = float(np.mean((home_goals + away_goals) > 2.5))
        over15  = float(np.mean((home_goals + away_goals) > 1.5))
        under25 = float(np.mean((home_goals + away_goals) < 2.5))
        btts    = float(np.mean((home_goals > 0) & (away_goals > 0)))
        cs_h    = float(np.mean(away_goals == 0))
        cs_a    = float(np.mean(home_goals == 0))
        dc_h    = float(np.mean(home_goals >= away_goals))   # 1X
        dc_a    = float(np.mean(home_goals <= away_goals))   # X2

        # ── Confidence Score ─────────────────────────────────────────────
        # Bazat pe: varianța probabilităților MC vs Poisson analitic,
        # calitatea datelor (live > elo > neutral), și concentrarea distribuției
        poisson_ph, poisson_pd, poisson_pa, _ = self._poisson_model(home_xg, away_xg)
        divergence = (abs(ph - poisson_ph) + abs(pd - poisson_pd) + abs(pa - poisson_pa)) / 3.0
        # Cu cât MC și Poisson analitic sunt mai aproape, cu atât modelul e mai consistent
        consistency = max(0.0, 1.0 - divergence * 10.0)

        # Concentrarea: dacă o echipă domină clar → confidence ridicat
        max_p = max(ph, pd, pa)
        concentration = (max_p - 0.333) / 0.667  # 0 = uniform, 1 = certitudine

        confidence_raw = (consistency * 0.4 + concentration * 0.6) * 100.0
        confidence_score = round(min(max(confidence_raw, 5.0), 99.0), 1)

        if confidence_score >= 70:
            confidence_label = "🟢 Ridicat"
        elif confidence_score >= 45:
            confidence_label = "🟡 Mediu"
        else:
            confidence_label = "🔴 Scăzut"

        logger.info("[MC] ph=%.3f pd=%.3f pa=%.3f confidence=%.1f%%",
                    ph, pd, pa, confidence_score)

        return {
            "mc_prob_home":           round(ph, 4),
            "mc_prob_draw":           round(pd, 4),
            "mc_prob_away":           round(pa, 4),
            "confidence_score":       confidence_score,
            "confidence_label":       confidence_label,
            "mc_simulations":         n_sim,
            "prob_over25":            round(over25, 4),
            "prob_over15":            round(over15, 4),
            "prob_under25":           round(under25, 4),
            "prob_btts":              round(btts, 4),
            "prob_clean_sheet_home":  round(cs_h, 4),
            "prob_clean_sheet_away":  round(cs_a, 4),
            "prob_double_chance_home": round(dc_h, 4),
            "prob_double_chance_away": round(dc_a, 4),
        }

    # ── Value bets piețe speciale ─────────────────────────────────────────
    def _special_value_bets(self, mc: dict, match: dict) -> list[dict]:
        """Caută value bets în piețele Over/Under, BTTS, Double Chance."""
        results: list[dict] = []
        threshold = float(self.config.get("value_bet_threshold_pct", 5.0))

        # Mapare piață → probabilitate model → cheie odds în match
        markets = [
            ("Over 2.5",      mc["prob_over25"],            "over25_odds"),
            ("Under 2.5",     mc["prob_under25"],           "under25_odds"),
            ("BTTS Da",       mc["prob_btts"],              "btts_yes_odds"),
            ("BTTS Nu",       1 - mc["prob_btts"],          "btts_no_odds"),
            ("Double Chance 1X", mc["prob_double_chance_home"], "dc_home_odds"),
            ("Double Chance X2", mc["prob_double_chance_away"], "dc_away_odds"),
        ]

        for market_name, model_prob, odds_key in markets:
            bk_odds = float(match.get(odds_key) or 0.0)
            if bk_odds <= 1.0:
                continue
            impl_p = 1.0 / bk_odds
            edge   = (model_prob - impl_p) / impl_p * 100.0
            if edge >= threshold:
                results.append({
                    "market":        market_name,
                    "model_prob_pct": round(model_prob * 100, 1),
                    "bk_odds":       bk_odds,
                    "edge_pct":      round(edge, 2),
                    "rating":        self._rating(edge),
                })

        return sorted(results, key=lambda x: x["edge_pct"], reverse=True)

    # ── evaluate_match ────────────────────────────────────────────────────
    def evaluate_match(self, match: dict) -> MatchPrediction | None:
        home_name = match["home_team"]; away_name = match["away_team"]
        league    = match.get("league","Unknown"); fid = match.get("fixture_id","?")
        logger.info("━━━ evaluate %s vs %s [%s] ━━━", home_name, away_name, league)

        home_p = self._build_profile(match.get("home_team_id",""), home_name, league)
        away_p = self._build_profile(match.get("away_team_id",""), away_name, league)
        logger.info("Home: OFF=%.3f DEF=%.3f [%s]", home_p.offensive_rating, home_p.defensive_rating, home_p.data_quality)
        logger.info("Away: OFF=%.3f DEF=%.3f [%s]", away_p.offensive_rating, away_p.defensive_rating, away_p.data_quality)

        h2h = self._build_h2h(home_name, away_name, match)

        city    = match.get("venue_city","") or league
        weather = self.api.get_weather(city, match.get("kickoff_date"))
        w_pen   = float(weather.get("xg_penalty", 0.0))
        w_note  = weather.get("description","")

        home_xg, away_xg = self._calibrate_xg(home_p, away_p, league, w_pen, h2h)

        # ── Injury penalty ────────────────────────────────────────────────
        home_xg_pre = home_xg; away_xg_pre = away_xg
        injury_note = "ℹ️ Date accidentări indisponibile"
        home_injury_report = None; away_injury_report = None
        event_id = match.get("_freelf_event_id")

        if self.injury_manager and event_id:
            try:
                home_injury_report = self.injury_manager.get_lineup_absences(
                    event_id  = event_id,
                    team_id   = match.get("_freelf_home_id",""),
                    team_name = home_name,
                    is_home   = True,
                )
                away_injury_report = self.injury_manager.get_lineup_absences(
                    event_id  = event_id,
                    team_id   = match.get("_freelf_away_id",""),
                    team_name = away_name,
                    is_home   = False,
                )
                home_xg, away_xg, injury_note = self.injury_manager.apply_injury_penalty(
                    home_xg, away_xg, home_injury_report, away_injury_report
                )
                if (home_injury_report and home_injury_report.has_key_absences) or \
                   (away_injury_report and away_injury_report.has_key_absences):
                    logger.warning("[Injuries] Key absences! %s", injury_note)
            except Exception as exc:
                logger.warning("[Injuries] Failed for event %s: %s", event_id, exc)

        logger.info("[xG after injuries] home=%.3f (was %.3f)  away=%.3f (was %.3f)",
                    home_xg, home_xg_pre, away_xg, away_xg_pre)

        ph, pd, pa, top_scores = self._poisson_model(home_xg, away_xg)

        # ── Monte Carlo + Confidence + Piețe speciale ─────────────────────
        n_sim = int(self.config.get("monte_carlo_simulations", 10000))
        mc    = self._monte_carlo(home_xg, away_xg, n_sim)
        special_vbets = self._special_value_bets(mc, match)

        bk_h = float(match.get("home_odds") or 0.0)
        bk_d = float(match.get("draw_odds") or 0.0)
        bk_a = float(match.get("away_odds") or 0.0)
        bk_n = match.get("odds_source") or "N/A"

        impl_h = self._implied(bk_h); impl_d = self._implied(bk_d); impl_a = self._implied(bk_a)
        edge_h = self._edge(ph, impl_h) if bk_h > 1 else 0.0
        edge_d = self._edge(pd, impl_d) if bk_d > 1 else 0.0
        edge_a = self._edge(pa, impl_a) if bk_a > 1 else 0.0

        threshold  = float(self.config.get("value_bet_threshold_pct", 5.0))
        value_bets: list[dict] = []
        for sel, ep, mp, odds in [("Home Win",edge_h,ph,bk_h),("Draw",edge_d,pd,bk_d),("Away Win",edge_a,pa,bk_a)]:
            if ep >= threshold:
                conf = ""
                if home_p.data_quality == DATA_QUALITY_NEUTRAL or away_p.data_quality == DATA_QUALITY_NEUTRAL:
                    conf = " ⚠️ date estimate"
                elif home_p.data_quality == DATA_QUALITY_ELO or away_p.data_quality == DATA_QUALITY_ELO:
                    conf = " 🟡 ELO only"
                value_bets.append({"market":"1X2","selection":sel,"edge_pct":ep,
                                   "rating":self._rating(ep),"model_prob_pct":round(mp*100,2),
                                   "bk_odds":odds,"confidence_note":conf})

        kelly: dict[str,float] = {}
        for sel, prob, odds in [("Home Win",ph,bk_h),("Draw",pd,bk_d),("Away Win",pa,bk_a)]:
            if odds > 1.0: kelly[sel] = self._kelly(prob, odds)

        pred = MatchPrediction(
            fixture_id=str(fid), home_team=home_name, away_team=away_name, league=league,
            kickoff_utc=match.get("kickoff_utc",""), kickoff_date=match.get("kickoff_date",""),
            season=match.get("season",2026),
            home_xg=home_xg, away_xg=away_xg,
            prob_home_win=round(ph,4), prob_draw=round(pd,4), prob_away_win=round(pa,4),
            top_scores=top_scores,
            bk_home_odds=bk_h, bk_draw_odds=bk_d, bk_away_odds=bk_a, bookmaker_name=bk_n,
            impl_home_pct=round(impl_h*100,2), impl_draw_pct=round(impl_d*100,2),
            impl_away_pct=round(impl_a*100,2),
            edge_home_pct=edge_h, edge_draw_pct=edge_d, edge_away_pct=edge_a,
            value_bets=value_bets, weather_note=w_note, weather_penalty=w_pen,
            kelly_stakes=kelly,
            home_profile=home_p, away_profile=away_p, h2h=h2h,
            data_quality_home=home_p.data_quality, data_quality_away=away_p.data_quality,
            home_injury_report=home_injury_report, away_injury_report=away_injury_report,
            injury_note=injury_note, home_xg_pre_injury=home_xg_pre,
            away_xg_pre_injury=away_xg_pre,
            # Monte Carlo & Confidence
            mc_prob_home=mc["mc_prob_home"],
            mc_prob_draw=mc["mc_prob_draw"],
            mc_prob_away=mc["mc_prob_away"],
            confidence_score=mc["confidence_score"],
            confidence_label=mc["confidence_label"],
            mc_simulations=mc["mc_simulations"],
            # Piețe speciale
            prob_over25=mc["prob_over25"],
            prob_over15=mc["prob_over15"],
            prob_under25=mc["prob_under25"],
            prob_btts=mc["prob_btts"],
            prob_clean_sheet_home=mc["prob_clean_sheet_home"],
            prob_clean_sheet_away=mc["prob_clean_sheet_away"],
            prob_double_chance_home=mc["prob_double_chance_home"],
            prob_double_chance_away=mc["prob_double_chance_away"],
            special_value_bets=special_vbets,
        )
        self._cache_prediction(pred)
        return pred

    # ── Utility methods ───────────────────────────────────────────────────
    def get_week_matches(self, days_ahead: int = 7, competitions: list[str] | None = None) -> list[dict]:
        return self.api.get_matches_for_week(days_ahead=days_ahead, competitions=competitions)

    def get_matches_by_date(self, target_date: str) -> list[dict]:
        return self.api.get_matches_for_date(target_date)

    def _cache_prediction(self, pred: MatchPrediction) -> None:
        data = {"fixture_id": pred.fixture_id, "home_team": pred.home_team,
                "away_team": pred.away_team, "league": pred.league,
                "kickoff_date": pred.kickoff_date,
                "home_xg": pred.home_xg, "away_xg": pred.away_xg,
                "prob_home": pred.prob_home_win, "prob_draw": pred.prob_draw,
                "prob_away": pred.prob_away_win,
                "data_quality_home": pred.data_quality_home,
                "data_quality_away": pred.data_quality_away,
                "saved_at": datetime.now(timezone.utc).isoformat()}
        safe_id = str(pred.fixture_id).replace("/","_")
        _save_json(PREDICTIONS_DIR / f"{safe_id}.json", data)

    def _load_prediction(self, fixture_id: str) -> dict | None:
        safe_id = str(fixture_id).replace("/","_")
        p = PREDICTIONS_DIR / f"{safe_id}.json"
        if not p.exists(): return None
        try: return json.loads(p.read_text(encoding="utf-8"))
        except Exception: return None

    # ── Self-learning recalibration ───────────────────────────────────────
    def update_weights_from_result(self, fixture_id: str, actual_home_goals: int, actual_away_goals: int) -> dict:
        cache = self._load_prediction(fixture_id)
        if cache is None:
            return {"status":"error","message":f"No cached prediction for {fixture_id}."}
        pred_h = float(cache.get("home_xg",1.25)); pred_a = float(cache.get("away_xg",1.00))
        league = cache.get("league","default")
        home_err = actual_home_goals - pred_h; away_err = actual_away_goals - pred_a
        combined = (abs(home_err) + abs(away_err)) / 2.0; avg_err = (home_err + away_err) / 2.0
        lr = float(self.config.get("recalibration_learning_rate",0.05))
        max_d = float(self.config.get("recalibration_max_delta",0.15))
        if combined < 0.30:
            return {"status":"stable","league":league,"combined_error":round(combined,4),
                    "message":"Model accurate.","adjustments":{}}
        adjustments: dict = {}; reasons: list = []
        def _shift(name, cur, delta, lo=0.05, hi=0.95):
            delta = max(-max_d, min(max_d, delta))
            new_val = max(lo, min(hi, cur+delta))
            adjustments[name] = {"old":round(cur,4),"delta":round(delta,4),"new":round(new_val,4)}
            return new_val
        lw_all = self.weights.setdefault("league_weights",{})
        if league not in lw_all:
            lw_all[league] = {"form_weight":float(self.weights.get("form_weight",0.60)),"dna_weight":float(self.weights.get("dna_weight",0.40)),"goals_weight":float(self.weights.get("goals_weight",0.45)),"shots_ot_weight":float(self.weights.get("shots_ot_weight",0.30)),"possession_weight":float(self.weights.get("possession_weight",0.25)),"home_advantage":float(self.weights.get("home_advantage",1.07)),"away_penalty":float(self.weights.get("away_penalty",0.95)),"sample_count":0}
        lw = lw_all[league]; sc = int(lw.get("sample_count",0))
        lr_league = min(lr * max(1.0, 3.0/(sc+1)), lr*3); scale_l = min(combined/3.0,1.0) * lr_league
        fw=float(lw.get("form_weight",0.60)); dw=float(lw.get("dna_weight",0.40))
        gw=float(lw.get("goals_weight",0.45)); sow=float(lw.get("shots_ot_weight",0.30))
        pw=float(lw.get("possession_weight",0.25)); ha=float(lw.get("home_advantage",1.07))
        ap=float(lw.get("away_penalty",0.95))
        if combined >= 0.50:
            fw=_shift("form_weight",fw,-scale_l*0.6,lo=0.10,hi=0.90)
            dw=_shift("dna_weight",dw,+scale_l*0.6,lo=0.10,hi=0.90)
            reasons.append(f"[{league}] Large error ({combined:.2f}) → DNA shift.")
        if avg_err > 0.50:
            gw=_shift("goals_weight",gw,+scale_l*0.5,lo=0.10,hi=0.80)
            sow=_shift("shots_ot_weight",sow,+scale_l*0.3,lo=0.05,hi=0.60)
            if home_err>0.5: ha=_shift("home_advantage",ha,+scale_l*0.2,lo=1.00,hi=1.20)
            reasons.append(f"[{league}] Under-estimated.")
        elif avg_err < -0.50:
            gw=_shift("goals_weight",gw,-scale_l*0.4,lo=0.10,hi=0.80)
            pw=_shift("possession_weight",pw,+scale_l*0.3,lo=0.05,hi=0.50)
            if home_err<-0.5: ha=_shift("home_advantage",ha,-scale_l*0.15,lo=1.00,hi=1.20)
            reasons.append(f"[{league}] Over-estimated.")
        t_comp = gw+sow+pw
        if t_comp > 0: gw=round(gw/t_comp,4); sow=round(sow/t_comp,4); pw=round(pw/t_comp,4)
        t_fd = fw+dw
        if t_fd > 0: fw=round(fw/t_fd,4); dw=round(dw/t_fd,4)
        lw_all[league].update({"form_weight":fw,"dna_weight":dw,"goals_weight":gw,
                                "shots_ot_weight":sow,"possession_weight":pw,
                                "home_advantage":ha,"away_penalty":ap,"sample_count":sc+1})
        gfw=float(self.weights.get("form_weight",0.60)); gdw=float(self.weights.get("dna_weight",0.40))
        ggw=float(self.weights.get("goals_weight",0.45)); gsow=float(self.weights.get("shots_ot_weight",0.30))
        gpw=float(self.weights.get("possession_weight",0.25))
        self.weights.update({"form_weight":round(max(0.10,min(0.90,gfw+(fw-gfw)*0.25)),4),
                              "dna_weight":round(max(0.10,min(0.90,gdw+(dw-gdw)*0.25)),4),
                              "goals_weight":round(max(0.10,min(0.80,ggw+(gw-ggw)*0.25)),4),
                              "shots_ot_weight":round(max(0.05,min(0.60,gsow+(sow-gsow)*0.25)),4),
                              "possession_weight":round(max(0.05,min(0.50,gpw+(pw-gpw)*0.25)),4),
                              "league_weights":lw_all})
        _save_json(WEIGHTS_PATH, self.weights)
        reason = "  |  ".join(reasons) or "Minor adjustment."
        log_row = {"timestamp":datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
                   "fixture_id":fixture_id,"league":league,"sample_count":sc+1,
                   "home":f"{cache.get('home_team','')} ({pred_h:.2f} xG)",
                   "away":f"{cache.get('away_team','')} ({pred_a:.2f} xG)",
                   "actual":f"{actual_home_goals}-{actual_away_goals}",
                   "combined_error":round(combined,3),"new_form_w":fw,"new_dna_w":dw,
                   "home_advantage":ha,"reason":reason}
        exists = RECAL_LOG_PATH.exists()
        with RECAL_LOG_PATH.open("a", newline="", encoding="utf-8") as f:
            wr = csv.DictWriter(f, fieldnames=list(log_row.keys()))
            if not exists: wr.writeheader()
            wr.writerow(log_row)
        return {"status":"recalibrated","fixture_id":fixture_id,
                "pred_home_xg":round(pred_h,3),"pred_away_xg":round(pred_a,3),
                "actual_home":actual_home_goals,"actual_away":actual_away_goals,
                "home_error":round(home_err,3),"away_error":round(away_err,3),
                "combined_error":round(combined,3),"adjustments":adjustments,"reason":reason}

    # ── Portfolio ─────────────────────────────────────────────────────────
    HEADERS = ["Date","FixtureID","Match","Market","Selection","Odds","Stake","Result","PnL"]

    def log_bet(self, fixture_id, match_name, market, selection, odds, stake, result="") -> dict:
        result = result.upper().strip()
        pnl = round(stake*(odds-1),2) if result=="W" else (-round(stake,2) if result=="L" else 0.0)
        row = {"Date":datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
               "FixtureID":str(fixture_id),"Match":match_name,"Market":market,
               "Selection":selection,"Odds":odds,"Stake":stake,
               "Result":result or "PENDING","PnL":pnl}
        exists = PORTFOLIO_PATH.exists()
        with PORTFOLIO_PATH.open("a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=self.HEADERS)
            if not exists: w.writeheader()
            w.writerow(row)
        return row

    def get_league_learning_stats(self) -> pd.DataFrame:
        global_defaults = {"form_weight":0.60,"dna_weight":0.40,"goals_weight":0.45,
                           "shots_ot_weight":0.30,"possession_weight":0.25,
                           "home_advantage":1.07,"away_penalty":0.95}
        lw_all = self.weights.get("league_weights",{}); rows = []
        for league, lw in lw_all.items():
            if league == "default": continue
            sc = int(lw.get("sample_count",0))
            rows.append({"League":league,"Samples":sc,
                         "Confidence":f"{min(sc/5*100,100):.0f}%",
                         "form_w":round(float(lw.get("form_weight",0.60)),4),
                         "dna_w":round(float(lw.get("dna_weight",0.40)),4),
                         "goals_w":round(float(lw.get("goals_weight",0.45)),4),
                         "home_adv":round(float(lw.get("home_advantage",1.07)),4),
                         "Δ form_w":round(float(lw.get("form_weight",0.60))-global_defaults["form_weight"],4),
                         "Δ goals_w":round(float(lw.get("goals_weight",0.45))-global_defaults["goals_weight"],4),
                         "Δ home_adv":round(float(lw.get("home_advantage",1.07))-global_defaults["home_advantage"],4)})
        if not rows:
            return pd.DataFrame(columns=["League","Samples","Confidence","form_w","dna_w",
                                         "goals_w","home_adv","Δ form_w","Δ goals_w","Δ home_adv"])
        return pd.DataFrame(rows).sort_values("Samples",ascending=False).reset_index(drop=True)

    def portfolio_summary(self) -> pd.DataFrame | None:
        if not PORTFOLIO_PATH.exists(): return None
        df = pd.read_csv(PORTFOLIO_PATH)
        return df if not df.empty else None
