"""
================================================================================
FOOTBALL ORACLE — Core Engine v3.0 (Supabase + ML edition)
================================================================================
Module  : oracle_engine.py
CHANGES v3.0 (față de v2.3):
  - Persistență migrată din fișiere locale (weights.json, portfolio.csv,
    recalibration_log.csv) în Supabase Postgres — supraviețuiește redeploy-
    urilor pe Streamlit Community Cloud.
  - Strat ML nou (ml_predictor.py, XGBoost) — învață tipare din meciuri
    istorice salvate automat în Supabase (match_history) de fiecare dată
    când utilizatorul confirmă rezultatul real al unui meci.
  - evaluate_match() combină (blend) predicția Poisson/Monte Carlo cu
    predicția ML, dacă există suficiente date de antrenare (≥30 meciuri).
  - update_weights_from_result() salvează acum și un rând în match_history
    pentru fiecare meci confirmat, pe lângă recalibrarea euristică existentă.
  - Fallback automat pe fișiere locale dacă Supabase nu e configurat
    (SUPABASE_URL / SUPABASE_SECRET_KEY lipsesc din st.secrets) — aplicația
    tot funcționează, doar nu persistă între redeploy-uri.
================================================================================
"""
from __future__ import annotations

import csv, json, logging, sys, time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

try:
    from oracle_api import FootballOracleAPI
except ModuleNotFoundError:
    print("[FATAL] oracle_api.py not found."); sys.exit(1)

try:
    from mappings import normalize_team_name, LEAGUE_BASELINES
except ModuleNotFoundError:
    print("[FATAL] mappings.py not found."); sys.exit(1)

try:
    from recalibration import recalibrate_weights, compute_recency_weight
except ModuleNotFoundError:
    print("[FATAL] recalibration.py not found."); sys.exit(1)

try:
    from feature_engine import (
        compute_form_score,
        compute_h2h_modifier,
        elo_to_offensive_multiplier,
        elo_to_defensive_multiplier,
        calibrate_xg,
        poisson_model,
        resolve_league_weights,
        compute_team_offdef_rating,
    )
except ModuleNotFoundError:
    print("[FATAL] feature_engine.py not found."); sys.exit(1)

try:
    from injury_manager import InjuryManager
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

try:
    import supabase_client as sb
    SUPABASE_MODULE_AVAILABLE = True
except ModuleNotFoundError:
    SUPABASE_MODULE_AVAILABLE = False

try:
    from database.queries import (
        get_latest_team_elo, get_h2h_from_history, get_team_health,
        get_team_form_footballdata, get_national_team_elo, get_weather_forecast,
        get_team_form_freelf_snapshot, get_team_recent_form_oddsapi, get_h2h_from_odds_recent,
        get_team_stats_tsdb, get_freelf_h2h_snapshot, get_freelf_lineup_snapshot,
        get_team_recent_advanced_stats, get_team_recent_statistics_extended,
        get_team_recent_player_ratings, get_team_standings_row,
        get_team_recent_form_context,
    )
    DB_QUERIES_MODULE_AVAILABLE = True
except ModuleNotFoundError:
    DB_QUERIES_MODULE_AVAILABLE = False

try:
    from flashscore_team_dna import build_team_dna
    FLASHSCORE_TEAM_DNA_AVAILABLE = True
except ModuleNotFoundError:
    FLASHSCORE_TEAM_DNA_AVAILABLE = False

try:
    from ml_predictor import MLPredictorEngine
    ML_MODULE_AVAILABLE = True
except ModuleNotFoundError:
    ML_MODULE_AVAILABLE = False

try:
    from blend_engine import BlendConfig, BlendEngine, EngineOutput
    BLEND_ENGINE_MODULE_AVAILABLE = True
except ModuleNotFoundError:
    BLEND_ENGINE_MODULE_AVAILABLE = False

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
    "recency_half_life_days":      365,
    "elo_blend_weight":            0.35,
    "elo_sigmoid_scale":           400.0,
    "elo_reference":               1500.0,
    "h2h_weight":                  0.15,
    "monte_carlo_simulations":     10000,
    # [ADAUGAT] Shadow testing - vezi architecture/ADR-002-shadow-testing.md.
    # Implicit OPRIT - nicio schimbare de comportament fara activare explicita.
    "shadow_mode_enabled":         False,
    # [ADAUGAT — Pasul 3, Implementation Contract Learning Core] Shadow
    # logging pt Challenger activ — vezi ADR-016. Flag DEDICAT, separat de
    # shadow_mode_enabled (acela ramane legat exclusiv de experimentul
    # apifootball_injuries_coaches). Implicit OPRIT.
    "challenger_shadow_logging_enabled": False,
    # [ADAUGAT — ADR-033] Captura Faza 1 (Consensus Validation) — flag
    # DEDICAT, explicit independent de challenger_shadow_logging_enabled si
    # de learning_core_enabled (ADR-030, citit separat din model_config, nu
    # din acest dict). Implicit OPRIT.
    "consensus_capture_enabled": False,
    # [ADAUGAT — Faza 3, exceptie explicita M4 aprobata de proprietarul
    # produsului 2026-07-29, ML_ACTIVATION_GATE.md] Shadow logging pentru
    # experimentul "flashscore_team_dna" — flag DEDICAT, separat de
    # shadow_mode_enabled (legat exclusiv de apifootball_injuries_coaches)
    # si de challenger_shadow_logging_enabled. Acelasi tipar exact ca
    # apifootball_injuries_coaches: foloseste probabilitatile FINALE
    # (productia), doar captureaza Team DNA ca feature_metadata pt analiza
    # viitoare - nu propune inca o varianta alternativa de xG. Implicit
    # OPRIT.
    "flashscore_shadow_logging_enabled": False,
    # Shadow logging pt Challenger-ul Blend (ADR-050/Pasul 13) — flag
    # dedicat, separat de challenger_shadow_logging_enabled. Implicit OPRIT.
    "blend_challenger_shadow_logging_enabled": False,
    # Afișare UI a predicției Blend Engine (ADR-051/ADR-052) — flag dedicat,
    # neînrudit cu cel de mai sus (acela ramane strict shadow logging pt
    # Challenger-ul blend_v1). Populeaza doar pred.blend_engine_prediction.
    # Implicit OPRIT.
    "blend_engine_display_enabled": False,
    # Config public al BlendEngine (ADR-052) — strategie + ponderi per
    # motor, citit de orchestrator si pasat ca BlendConfig. Implicit:
    # strategia V1 (medie ponderata), nicio pondere explicita (=> 1.0,
    # neutru, pt orice motor).
    "blend_engine_config": {"strategy": "weighted_average", "weights": {}},
    # Afișare UI a predicției ML Engine (ADR-051, Phase 1) — flag dedicat,
    # singura cale prin care ML influențează ce se afișează (motorul Oracle
    # servit prin prob_home_win/prob_draw/prob_away_win rămâne mereu pur —
    # nu mai există blend legacy in-place, eliminat ADR-051/052). Populează
    # doar pred.ml_engine_prediction. Implicit OPRIT.
    "ml_engine_display_enabled": False,
    # [ADAUGAT — ADR-061] Afișare UI a predicției Campionului blend_v1
    # PROMOVAT (Model Registry, learning_core/blend_v1_champion_loader.py) —
    # flag DEDICAT, distinct de blend_engine_display_enabled de mai sus
    # (acela e motorul static blend_engine.py, algoritm neschimbat, zero
    # legătură cu Model Registry). Populează doar
    # pred.blend_v1_champion_prediction. Implicit OPRIT (North Star #3).
    "blend_v1_champion_display_enabled": False,
    # Validation Framework (ADR-052) — colectare automată, per meci, a
    # ieșirilor Oracle/ML/Blend în engine_comparison_snapshots, pentru
    # analize periodice ulterioare. Flag dedicat, neînrudit cu flag-urile
    # de afișare de mai sus. Nu ia decizii, nu optimizează, nu promovează.
    # Implicit OPRIT.
    "validation_framework_enabled": False,
}

DEFAULT_WEIGHTS: dict[str, Any] = {
    "goals_weight": 0.45, "shots_ot_weight": 0.30, "possession_weight": 0.25,
    "form_weight": 0.60, "base_weight": 0.40,
    "home_advantage": 1.07, "away_penalty": 0.95,
    "offensive_cap": 3.5, "defensive_cap": 2.5,
    "league_baselines": LEAGUE_BASELINES,
    "league_weights": {
        "Premier League":    {"form_weight":0.60,"base_weight":0.40,"goals_weight":0.45,"shots_ot_weight":0.30,"possession_weight":0.25,"home_advantage":1.07,"away_penalty":0.95,"sample_count":0},
        "La Liga":           {"form_weight":0.60,"base_weight":0.40,"goals_weight":0.45,"shots_ot_weight":0.30,"possession_weight":0.25,"home_advantage":1.06,"away_penalty":0.95,"sample_count":0},
        "Serie A":           {"form_weight":0.60,"base_weight":0.40,"goals_weight":0.45,"shots_ot_weight":0.30,"possession_weight":0.25,"home_advantage":1.06,"away_penalty":0.95,"sample_count":0},
        "Bundesliga":        {"form_weight":0.65,"base_weight":0.35,"goals_weight":0.50,"shots_ot_weight":0.28,"possession_weight":0.22,"home_advantage":1.08,"away_penalty":0.94,"sample_count":0},
        "Ligue 1":           {"form_weight":0.60,"base_weight":0.40,"goals_weight":0.45,"shots_ot_weight":0.30,"possession_weight":0.25,"home_advantage":1.07,"away_penalty":0.95,"sample_count":0},
        "Champions League":  {"form_weight":0.55,"base_weight":0.45,"goals_weight":0.42,"shots_ot_weight":0.32,"possession_weight":0.26,"home_advantage":1.05,"away_penalty":0.96,"sample_count":0},
        "Europa League":     {"form_weight":0.58,"base_weight":0.42,"goals_weight":0.43,"shots_ot_weight":0.31,"possession_weight":0.26,"home_advantage":1.06,"away_penalty":0.95,"sample_count":0},
        "Romania SuperLiga": {"form_weight":0.65,"base_weight":0.35,"goals_weight":0.48,"shots_ot_weight":0.28,"possession_weight":0.24,"home_advantage":1.09,"away_penalty":0.93,"sample_count":0},
        "World Cup 2026":    {"form_weight":0.55,"base_weight":0.45,"goals_weight":0.44,"shots_ot_weight":0.30,"possession_weight":0.26,"home_advantage":1.03,"away_penalty":0.97,"sample_count":0},
        "MLS":               {"form_weight":0.60,"base_weight":0.40,"goals_weight":0.45,"shots_ot_weight":0.30,"possession_weight":0.25,"home_advantage":1.08,"away_penalty":0.94,"sample_count":0},
        # [ADAUGAT 2026-08-04] 4 ligi noi — valori IDENTICE cu "default" de
        # mai jos (deliberat, nu o omisiune): nicio calibrare per-ligă reală
        # nu există încă (sample_count=0 peste tot, oricum inert azi — vezi
        # docstring resolve_league_weights(), feature_engine.py). Prezența
        # explicită aici e doar structurală (paritate vizibilă cu restul
        # ligilor înregistrate), NU o schimbare de parametru matematic —
        # regula "orice recalibrare = experiment separat, aprobare
        # explicită" (CLAUDE.md) rămâne respectată: nimic nu e recalibrat.
        "Primeira Liga":     {"form_weight":0.60,"base_weight":0.40,"goals_weight":0.45,"shots_ot_weight":0.30,"possession_weight":0.25,"home_advantage":1.07,"away_penalty":0.95,"sample_count":0},
        "Eredivisie":        {"form_weight":0.60,"base_weight":0.40,"goals_weight":0.45,"shots_ot_weight":0.30,"possession_weight":0.25,"home_advantage":1.07,"away_penalty":0.95,"sample_count":0},
        "Super Lig":         {"form_weight":0.60,"base_weight":0.40,"goals_weight":0.45,"shots_ot_weight":0.30,"possession_weight":0.25,"home_advantage":1.07,"away_penalty":0.95,"sample_count":0},
        "HNL":               {"form_weight":0.60,"base_weight":0.40,"goals_weight":0.45,"shots_ot_weight":0.30,"possession_weight":0.25,"home_advantage":1.07,"away_penalty":0.95,"sample_count":0},
        "default":           {"form_weight":0.60,"base_weight":0.40,"goals_weight":0.45,"shots_ot_weight":0.30,"possession_weight":0.25,"home_advantage":1.07,"away_penalty":0.95,"sample_count":0},
    },
}

DATA_QUALITY_LIVE    = "live"
DATA_QUALITY_PARTIAL = "partial"
DATA_QUALITY_ELO     = "elo"
DATA_QUALITY_NEUTRAL = "neutral"

DATA_QUALITY_NOTES = {
    DATA_QUALITY_LIVE:    "Date reale — meciuri terminate",
    DATA_QUALITY_PARTIAL: "Date parțiale — estimate din agregate/proxy",
    DATA_QUALITY_ELO:     "Date parțiale — ELO disponibil",
    DATA_QUALITY_NEUTRAL: "Date estimate — fără statistici reale",
}


# ── Clasificarea data_quality (ADR-035 D4) — PUNCT UNIC de decizie ──────────
# LIVE reprezintă date provenite din meciuri REALE (chiar dacă unele câmpuri —
# posesie, șuturi — folosesc fallback), adică `supabase-history` cu eșantion
# suficient. Sursa e deja gate-uită la MIN_DB_MATCHES=3 în _build_profile, deci
# pragul n>=3 de aici e o plasă de siguranță aliniată D1, NU un prag numeric
# nou. Sursele agregat/hardcodat/proxy/sintetice (national, freelf, scores-api,
# fd, thesportsdb) → PARTIAL, onest (nu „statistici reale"). elo-only → ELO;
# fără date → NEUTRAL. Nicio altă locație nu atribuie DATA_QUALITY_LIVE — garda
# AST tests/test_data_quality_classification.py impune asta.
_DATA_QUALITY_LIVE_MIN_MATCHES = 3


def _classify_data_quality(data_source: str, matches_analysed: int) -> str:
    """Singurul punct de decizie pentru data_quality (ADR-035 D4)."""
    if data_source == "supabase-history" and matches_analysed >= _DATA_QUALITY_LIVE_MIN_MATCHES:
        return DATA_QUALITY_LIVE
    if data_source == "elo-only":
        return DATA_QUALITY_ELO
    if data_source in ("", "neutral-defaults"):
        return DATA_QUALITY_NEUTRAL
    return DATA_QUALITY_PARTIAL


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
    # Statistici reale, informative (Task 2, ADR-011) — NU sunt încă
    # parametri ai compute_team_offdef_rating(), doar afișate. None dacă
    # nu există date reale (nu se aproximează).
    avg_corners:       float | None = None
    avg_fouls:         float | None = None
    avg_yellow_cards:  float | None = None
    avg_ht_goals:      float | None = None
    # [ADAUGAT — ADR-021/P7.1] Șuturi TOTALE reale (nu pe poartă — vezi
    # avg_shots_ot mai sus, deja existent). Sursă pentru shot_dominance
    # (FEATURE_COLUMNS), promovat prin ablație — vezi
    # docs/03_ENGINE/SHOT_DOMINANCE_ABLATION_2026-07-15.md.
    avg_shots:         float | None = None


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
        return cls(
            home_team=home, away_team=away, meetings=0, home_wins=0,
            draws=0, away_wins=0, home_goals_avg=0.0, away_goals_avg=0.0,
            last_5=[], h2h_modifier=0.0, summary="H2H: fără date istorice",
        )


@dataclass
class MatchPrediction:
    # ── Identificare meci ─────────────────────────────────────────────────
    fixture_id:        str
    home_team:         str
    away_team:         str
    league:            str
    kickoff_utc:       str
    kickoff_date:      str
    season:            int
    # ── xG & probabilități Poisson ────────────────────────────────────────
    home_xg:           float
    away_xg:           float
    prob_home_win:     float
    prob_draw:         float
    prob_away_win:     float
    top_scores:        list[tuple[int, int, float]]
    # ── Cote bookmaker ────────────────────────────────────────────────────
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
    # ── Vreme ─────────────────────────────────────────────────────────────
    weather_note:      str
    weather_penalty:   float
    # ── Kelly & profiluri ─────────────────────────────────────────────────
    kelly_stakes:      dict[str, float]
    home_profile:      TeamProfile | None
    away_profile:      TeamProfile | None
    h2h:               H2HRecord | None
    data_quality_home: str
    data_quality_away: str
    # ── Accidentări ───────────────────────────────────────────────────────
    home_injury_report: Any | None
    away_injury_report: Any | None
    injury_note:        str
    home_xg_pre_injury: float
    away_xg_pre_injury: float
    # ── Monte Carlo & Confidence (câmpuri cu default) ─────────────────────
    mc_prob_home:             float = 0.0
    mc_prob_draw:             float = 0.0
    mc_prob_away:             float = 0.0
    confidence_score:         float = 0.0
    confidence_label:         str   = ""
    mc_simulations:           int   = 0
    # ── Piețe speciale ────────────────────────────────────────────────────
    prob_over25:              float = 0.0
    prob_over15:              float = 0.0
    prob_under25:             float = 0.0
    prob_btts:                float = 0.0
    prob_clean_sheet_home:    float = 0.0
    prob_clean_sheet_away:    float = 0.0
    prob_double_chance_home:  float = 0.0
    prob_double_chance_away:  float = 0.0
    special_value_bets:       list  = field(default_factory=list)
    # ── De-vig (Prioritatea #2 — Value Betting Engine) ────────────────────
    # Probabilitatea "fair" (fara marja bookmaker-ului), separata explicit
    # de impl_*_pct (bruta, 1/cota) - vezi _devig_probabilities(). Suma
    # celor trei e normalizata la 1.0. edge_*_pct/value_bets/EV o folosesc
    # pe aceasta, NU pe impl_*_pct.
    fair_home_pct:            float = 0.0
    fair_draw_pct:            float = 0.0
    fair_away_pct:            float = 0.0
    # ── N-way Serving (ADR-031) ────────────────────────────────────────────
    # Aditiv, byte-for-byte compatibil cu tot ce e mai sus — prob_home_win/
    # prob_draw/prob_away_win (compus, existent) rămân neschimbate. Listă,
    # nu câmpuri fixe — N-way-ready fără hardcodare la exact 2 motoare.
    # Ordine deterministă: sortată (familie, nume), niciodată ordine de
    # calcul/iterare internă. Fiecare view compus e derivat PUR din aceste
    # ieșiri brute — nu execută niciun motor suplimentar.
    raw_predictions:          list  = field(default_factory=list)
    # ── Flashscore Team DNA (Faza 2, ADR-044 §5) ──────────────────────────
    # Context SUPLIMENTAR, aditiv — xG real/posesie reală/pase/dueluri/
    # tackle-uri/apărări/rating jucători/clasament, din Foundation Data
    # Layer. NU alimentează home_profile/away_profile/predicția Oracle -
    # doar informativ, ca H2H/injury_report de mai sus. None dacă
    # Flashscore n-a colectat încă date pentru acea echipă (nu se
    # aproximează).
    home_flashscore_dna:      dict | None = None
    away_flashscore_dna:      dict | None = None
    # ── Blend Engine (ADR-051/ADR-052) ──────────────────────────────────────
    # Câmp SEPARAT, dedicat, izolat de `raw_predictions` (ADR-031) în mod
    # deliberat — consensus_validation.compute_metrics() presupune azi
    # exact 2 motoare în raw_predictions (`a, b = engines[0], engines[1]`);
    # o a treia intrare acolo ar rupe acel cod. Populat de BlendEngine
    # (blend_engine.py, motor independent, algoritm neschimbat, zero
    # coupling cu Champion/Shadow/Promotion/ADR-031/ADR-033). De la
    # ADR-052: combină Oracle + ML (dacă ml_engine_prediction e disponibil
    # la momentul calculului — vezi _get_blend_engine_prediction()),
    # altfel doar Oracle, exact comportamentul dinainte de ADR-052. None
    # dacă flag-ul de afișare e oprit — nu se aproximează.
    blend_engine_prediction:  dict | None = None
    # ── ML Engine (ADR-051, Phase 1) ───────────────────────────────────────
    # Câmp SEPARAT, izolat, mirror exact al blend_engine_prediction de mai
    # sus — NU raw_predictions (ADR-031), NU shadow_predictions. Populat de
    # self.ml (deja Champion-aware prin _resolve_champion()) via
    # _get_ml_engine_prediction(), doar dacă ml_engine_display_enabled=True.
    # Trei stări, niciodată aproximate: None (flag oprit sau eroare
    # neprevăzută), {"available": False, "reason": ...} (ML indisponibil
    # sau predicție eșuată pentru acest meci), {"available": True,
    # "prob_home"/"prob_draw"/"prob_away": ...} (succes).
    ml_engine_prediction:     dict | None = None
    # ── Blend v1 Champion (ADR-061) ────────────────────────────────────────
    # Câmp SEPARAT, izolat — NU blend_engine_prediction de mai sus (acela e
    # motorul static blend_engine.py, algoritm neschimbat, fără legătură cu
    # Model Registry — cele două ar produce numere diferite sub o etichetă
    # similară dacă s-ar confunda). Populat de
    # _get_blend_v1_champion_prediction() DOAR dacă
    # blend_v1_champion_display_enabled=True, din Campionul PROMOVAT al
    # familiei blend_v1 (learning_core/blend_v1_champion_loader.py) — nu din
    # Challenger-ul activ (acela rămâne exclusiv shadow,
    # blend_challenger_shadow.py, neschimbat). Trei stări, niciodată
    # aproximate: None (flag oprit sau eroare neprevăzută),
    # {"available": False, "reason": ...} (niciun Campion promovat/utilizabil
    # pentru această familie), {"available": True, "prob_home"/"prob_draw"/
    # "prob_away": ...} (succes). Fără fallback pe "antrenare locală" — nu
    # există un blend_v1 local cu sens (vezi ADR-061).
    blend_v1_champion_prediction: dict | None = None


def build_raw_predictions(
    rb_prob_home: float, rb_prob_draw: float, rb_prob_away: float,
    ml_active: bool, ml_prob_home: float, ml_prob_draw: float, ml_prob_away: float,
) -> list[dict]:
    """[ADR-031] Construiește lista N-way de ieșiri brute, separate, pentru
    Serving Contract — funcție pură (fără efecte laterale, fără atingerea
    niciunui motor), separată explicit de evaluate_match() pentru
    testabilitate directă. Ordine deterministă: sortată (familie, nume),
    niciodată ordinea de calcul internă."""
    predictions = [{
        "engine": "oracle_protocol", "family": "rule_based", "version": "1",
        "prob_home": round(rb_prob_home, 4), "prob_draw": round(rb_prob_draw, 4),
        "prob_away": round(rb_prob_away, 4),
    }]
    if ml_active:
        predictions.append({
            "engine": "xgboost_v1", "family": "ml", "version": "1",
            "prob_home": round(ml_prob_home, 4), "prob_draw": round(ml_prob_draw, 4),
            "prob_away": round(ml_prob_away, 4),
        })
    predictions.sort(key=lambda e: (e["family"], e["engine"]))
    return predictions


class FootballOracleEngine:

    def __init__(self) -> None:
        self.api         = FootballOracleAPI()
        self.use_supabase = SUPABASE_MODULE_AVAILABLE and sb.is_available()

        if self.use_supabase:
            self.config  = sb.load_config(DEFAULT_CONFIG)
            self.weights = sb.load_weights(DEFAULT_WEIGHTS)
            if not self.config:
                self.config = dict(DEFAULT_CONFIG)
            if not self.weights:
                self.weights = dict(DEFAULT_WEIGHTS)
            logger.info("[Persistence] Supabase activ — config/weights încărcate din cloud.")
        else:
            self.config  = _load_json(CONFIG_PATH,  DEFAULT_CONFIG)
            self.weights = _load_json(WEIGHTS_PATH, DEFAULT_WEIGHTS)
            reason = sb.last_error() if SUPABASE_MODULE_AVAILABLE else "modul supabase_client lipsă"
            logger.warning("[Persistence] Supabase indisponibil (%s) — fallback pe fișiere locale (NU persistă la redeploy).", reason)

        self.cache       = get_cache()       if CACHE_MANAGER_AVAILABLE else None
        self.key_manager = get_key_manager() if KEY_MANAGER_AVAILABLE   else None
        self.injury_manager = (
            InjuryManager(api=self.api, cache=self.cache)
            if INJURY_MANAGER_AVAILABLE else None
        )
        # [ELIMINAT R-Sync-2, ADR-039] self.apifootball (ApiFootballProvider)
        # eliminat — Oracle Engine nu mai apeleaza niciun provider extern
        # pentru injuries/coaches, citeste exclusiv Supabase (team_health_snapshot,
        # database.queries.get_team_health()). Sincronizarea reala ruleaza acum
        # separat, in Sync Layer (sync/sync_team_health.py, apifootball_health_adapter.py).

        self._initialize_ml()

        # [ADAUGAT — ADR-051] BlendEngine — motor independent
        # (blend_engine.py), instanțiat o dată, reutilizat per predicție,
        # exact tiparul lui self.ml de mai sus. Zero coupling: blend_engine.py
        # nu importă acest fișier. Config public, tipizat (BlendConfig),
        # citit din model_config (self.config) — modulul însuși rămâne fără
        # I/O.
        self.blend = (
            BlendEngine(BlendConfig.from_dict(self.config.get("blend_engine_config")))
            if BLEND_ENGINE_MODULE_AVAILABLE else None
        )

        logger.info(
            "FootballOracleEngine v3.0 ready. Supabase=%s Injuries=%s Cache=%s KeyMgr=%s ML=%s ml_source=%s champion_status=%s",
            self.use_supabase, INJURY_MANAGER_AVAILABLE, CACHE_MANAGER_AVAILABLE,
            KEY_MANAGER_AVAILABLE, ML_MODULE_AVAILABLE, self.ml_source,
            self.champion_diagnostic.get("status"),
        )

    # [ADAUGAT — Pasul 7B, Implementation Contract Learning Core] Decizie
    # UNICĂ Champion vs Local vs None — vezi RUNTIME_CONTRACT.md și
    # ADR-019/Architecture Gate 7B. Extrasă din __init__ într-o metodă
    # separată exact ca să fie testabilă direct (garda "Champion wins over
    # Local" cere să poată mock-ui MLPredictorEngine.train() ca să ridice
    # excepție dacă e apelat, fără să construiască un engine complet).
    #
    # UN singur apel către champion_loader (`_resolve_champion()`) —
    # rezultatul lui alimentează SIMULTAN decizia de servire,
    # `champion_diagnostic` și seeding-ul lui `self.ml` — zero al doilea
    # apel, zero cursă posibilă între diagnostic și ce chiar servește.
    #
    # Invariant (Architecture Gate 7B): `train()` NU e apelat NICIODATĂ
    # când Champion reușește — nu doar rezultatul ignorat, apelul însuși
    # lipsește. Motiv: `train()` are efect secundar Supabase
    # (`sb.save_ml_status`) care ar corupe `ml_model_status` cu
    # statisticile antrenării locale, chiar dacă Champion e cel care
    # servește efectiv (Defectul A, găsit la audit).
    def _initialize_ml(self) -> None:
        # [CORECTAT — fix „aplicația pornește foarte greu"] Antrenarea
        # sincronă (self.ml.train()) a fost ELIMINATĂ complet din calea de
        # servire. Înainte, absența unui Champion promovat însemna un
        # antrenament XGBoost complet (6 fit-uri — 5 fold-uri walk-forward +
        # final, pe 50.000+ meciuri, cu paginare Supabase completă) la
        # FIECARE construcție de motor (fiecare restart de container, fiecare
        # „Clear cache" din Streamlit) — 3-5 minute de blocaj confirmat live.
        # Acum: Champion (nivel 1) -> Local Model Cache (nivel 2, încarcă
        # ultimul artefact antrenat cu succes, fără nicio antrenare) -> fără
        # ML (Oracle-only), niciodată blocare. Antrenarea reală rămâne
        # exclusiv responsabilitatea learning_core/continuous_learning.py
        # (Faza B, ADR-030), decuplată, în fundal (cron GitHub Actions),
        # NICIODATĂ în calea de servire — vezi local_model_cache.py.
        #
        # [ADAUGAT — audit ADR-051/052, instrumentare de startup] Doar
        # MĂSURARE: `time.perf_counter()` + `logger.info` în jurul celor două
        # etape care pot domina timpul de pornire (rezolvare Champion,
        # respectiv încărcare artefact din Local Model Cache — ambele fac
        # I/O Supabase + Storage). Zero schimbare de comportament: nicio
        # ramură nouă, nicio decizie schimbată, niciun apel suplimentar de
        # rețea. Costul e un apel `perf_counter()` per etapă (nanosecunde),
        # deci sub orice prag de impact asupra servirii. Scop: să putem citi
        # din logurile Streamlit Cloud unde se duc efectiv secundele, fără
        # să presupunem.
        _t_engine_start = time.perf_counter()
        self.ml = MLPredictorEngine() if ML_MODULE_AVAILABLE else None

        champion_result = None
        _t_champion_ms = None
        if self.ml and self.use_supabase:
            _t0 = time.perf_counter()
            champion_result = self._resolve_champion()
            _t_champion_ms = (time.perf_counter() - _t0) * 1000

        if champion_result is not None:
            self.ml_source = "champion"
            self.champion_diagnostic = self._champion_diagnostic_from_result(champion_result)
            logger.info(
                "[Startup] ML=champion (training_run_id=%s) · rezolvare Champion %.0f ms · total %.0f ms",
                champion_result.training_run_id, _t_champion_ms or 0.0,
                (time.perf_counter() - _t_engine_start) * 1000,
            )
        elif self.ml and self.use_supabase:
            _t1 = time.perf_counter()
            cache_result = self._resolve_local_cache()
            _t_cache_ms = (time.perf_counter() - _t1) * 1000
            logger.info(
                "[ML] Inițializare: %s",
                f"cache încărcat (training_run_id={cache_result.training_run_id})"
                if cache_result is not None else "niciun artefact servabil în cache — Oracle-only",
            )
            self.ml_source = "local" if self.ml.is_trained else "none"
            self.champion_diagnostic = self._champion_diagnostic_unavailable("no_valid_champion")
            logger.info(
                "[Startup] ML=%s · Champion absent (%.0f ms) · încărcare cache %.0f ms · total %.0f ms",
                self.ml_source, _t_champion_ms or 0.0, _t_cache_ms,
                (time.perf_counter() - _t_engine_start) * 1000,
            )
        else:
            self.ml_source = "none"
            reason = "no_supabase" if not self.use_supabase else "ml_module_unavailable"
            self.champion_diagnostic = self._champion_diagnostic_unavailable(reason)
            logger.info(
                "[Startup] ML=none (motiv: %s) · total %.0f ms",
                reason, (time.perf_counter() - _t_engine_start) * 1000,
            )

    @staticmethod
    def _champion_diagnostic_unavailable(reason: str) -> dict:
        return {
            "status": "unavailable", "reason": reason,
            "training_run_id": None, "algorithm_version": None,
            "validated_at": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def _champion_diagnostic_from_result(result) -> dict:
        return {
            "status": "validated", "reason": None,
            "training_run_id": result.training_run_id,
            "algorithm_version": result.algorithm_version,
            "validated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _resolve_champion(self):
        """UN singur apel către `champion_loader.load_champion_or_none()`
        per construcție — dacă reușește, seedează `self.ml` DIRECT (Golul A,
        Pasul 6) și întoarce rezultatul (folosit apoi pentru
        `champion_diagnostic`, fără al doilea apel). None dacă Champion nu
        e disponibil — `self.ml` rămâne neatins, apelantul cade pe
        `train()`. `load_champion_or_none()` însuși nu ridică niciodată
        excepție (contract propriu, testat) — try/except-ul de aici e
        plasă de siguranță suplimentară pe cel mai sensibil punct din tot
        Learning Core (primul care schimbă efectiv ce se servește)."""
        try:
            from learning_core.champion_loader import load_champion_or_none
            from ml_predictor import _ALGORITHM_FAMILY, _LEAGUE_SCOPE

            result = load_champion_or_none(_ALGORITHM_FAMILY, _LEAGUE_SCOPE)
            if result is None:
                return None

            self.ml.seed_from_champion(
                result.model, result.samples_used,
                accuracy=result.accuracy, log_loss=result.log_loss, trained_at=result.trained_at,
                temperature=result.temperature,  # [ADAUGAT — ADR-049, Pasul 10b]
            )
            return result
        except Exception as exc:
            logger.warning("[Champion] Rezolvare eșuată neașteptat — fallback pe antrenare locală: %s", exc)
            return None

    # [ADAUGAT — fix „aplicația pornește foarte greu"] Al doilea nivel de
    # rezolvare ML, sub Champion — oglindește exact _resolve_champion() de
    # mai sus (un singur apel per construcție, seedează self.ml DIRECT, None
    # dacă indisponibil, apelantul cade mai departe). Diferența: sursa e
    # local_model_cache.load_latest_trained_model_or_none() (ultimul artefact
    # antrenat cu succes, INDIFERENT dacă a devenit vreodată Champion), nu
    # get_active_champion(). NICIODATĂ nu antrenează — doar încarcă un
    # artefact deja persistat. Dacă și cache-ul e indisponibil (bootstrap,
    # niciun training_run reușit încă), apelantul servește Oracle-only,
    # NICIODATĂ nu antrenează sincron în calea de servire (eliminat complet
    # — antrenarea rămâne exclusiv learning_core/continuous_learning.py,
    # decuplată, în fundal).
    def _resolve_local_cache(self):
        try:
            from learning_core.local_model_cache import load_latest_trained_model_or_none
            from ml_predictor import _ALGORITHM_FAMILY, _LEAGUE_SCOPE

            result = load_latest_trained_model_or_none(_ALGORITHM_FAMILY, _LEAGUE_SCOPE)
            if result is None:
                return None

            self.ml.seed_from_cache(
                result.model, result.samples_used, result.training_run_id,
                accuracy=result.accuracy, log_loss=result.log_loss, trained_at=result.trained_at,
                temperature=result.temperature,
            )
            return result
        except Exception as exc:
            logger.warning("[LocalModelCache] Rezolvare eșuată neașteptat — servire fără ML: %s", exc)
            return None

    def _persist_weights(self) -> None:
        if self.use_supabase:
            sb.save_weights(self.weights)
        else:
            _save_json(WEIGHTS_PATH, self.weights)

    def _persist_config(self) -> None:
        if self.use_supabase:
            sb.save_config(self.config)
        else:
            _save_json(CONFIG_PATH, self.config)

    # ── ELO sigmoid ───────────────────────────────────────────────────────
    def _elo_to_multiplier(self, elo: int) -> float:
        ref   = float(self.config.get("elo_reference",    1500.0))
        scale = float(self.config.get("elo_sigmoid_scale", 400.0))
        return elo_to_offensive_multiplier(elo, ref, scale)

    def _elo_to_defensive_multiplier(self, elo: int) -> float:
        ref   = float(self.config.get("elo_reference",    1500.0))
        scale = float(self.config.get("elo_sigmoid_scale", 400.0))
        return elo_to_defensive_multiplier(elo, ref, scale)

    # ── H2H ───────────────────────────────────────────────────────────────
    # Prag minim de confruntări sub care H2H din DB e considerat insuficient
    # (Decizia 3, ADR-035 D3) — sub el, se cade pe cascada de provideri
    # existentă, exact ca la Level DB din _build_profile (D1, MIN_DB_MATCHES=3).
    MIN_H2H_MEETINGS = 3

    @staticmethod
    def _h2h_record_from_history_rows(
        home_c: str, away_c: str, rows: list[dict], weight: float
    ) -> H2HRecord | None:
        """Recalculează H2H din rânduri BRUTE match_history (ADR-035 D3,
        Decizia 2) — din perspectiva echipei gazdă curente (`home_c`).
        Nicio coloană precalculată (`h2h_modifier`/`h2h_meetings`) nu e
        atinsă. Rândurile incomplete nu se aproximează (Regula #8) — se
        ignoră. Returnează None dacă niciun rând valid (apelantul cade pe
        cascada veche)."""
        home_wins = draws = away_wins = 0
        home_g = away_g = 0.0
        last_5: list[str] = []
        n = 0
        for r in rows:
            r_home = r.get("home_team")
            r_away = r.get("away_team")
            if {r_home, r_away} != {home_c, away_c}:
                continue
            hg, ag = r.get("actual_home_goals"), r.get("actual_away_goals")
            res    = r.get("actual_result")
            if hg is None or ag is None or res not in ("H", "D", "A"):
                continue
            home_was_host = (r_home == home_c)
            gf = float(hg if home_was_host else ag)
            ga = float(ag if home_was_host else hg)
            home_g += gf
            away_g += ga
            if res == "D":
                draws += 1
                letter = "D"
            elif (res == "H") == home_was_host:
                home_wins += 1
                letter = "H"
            else:
                away_wins += 1
                letter = "A"
            if len(last_5) < 5:
                last_5.append(letter)
            n += 1

        if n == 0:
            return None

        h2h_modifier = compute_h2h_modifier(home_wins, away_wins, n, weight=weight)
        summary = (
            f"H2H ({n} meciuri): {home_wins}W {draws}D {away_wins}L | "
            f"Goluri: {round(home_g/n, 1)}–{round(away_g/n, 1)} | "
            f"Ultimele: {''.join(last_5)}"
        )
        return H2HRecord(
            home_team=home_c, away_team=away_c, meetings=n,
            home_wins=home_wins, draws=draws, away_wins=away_wins,
            home_goals_avg=round(home_g/n, 2), away_goals_avg=round(away_g/n, 2),
            last_5=last_5, h2h_modifier=h2h_modifier, summary=summary,
        )

    def _build_h2h(self, home_name: str, away_name: str, match: dict) -> H2HRecord:
        # ── Level DB (ADR-035 / D3): match_history global, recalc din brute ──
        # PRIMAR. Principiul de proiectare (ADR-035): niciun provider extern
        # nu poate avea prioritate asupra unei informații deja sincronizate în
        # baza canonică. Sub MIN_H2H_MEETINGS confruntări, DB e insuficient —
        # se cade pe cascada de provideri existentă, neschimbată (fluxul
        # normal, nu excepția), exact ca Level DB din _build_profile (D1).
        if DB_QUERIES_MODULE_AVAILABLE:
            home_c = normalize_team_name(home_name)
            away_c = normalize_team_name(away_name)
            try:
                db_rows = get_h2h_from_history(home_c, away_c)
            except Exception as exc:
                db_rows = []
                logger.warning("[H2H] DB-first read failed for %s vs %s: %s", home_c, away_c, exc)
            db_h2h = self._h2h_record_from_history_rows(
                home_c, away_c, db_rows, float(self.config.get("h2h_weight", 0.15))
            )
            if db_h2h is not None and db_h2h.meetings >= self.MIN_H2H_MEETINGS:
                logger.info("[H2H] %s vs %s — supabase-history (%d confruntări)",
                            home_c, away_c, db_h2h.meetings)
                return db_h2h

        # ── FreeLF H2H (ADR-039, R-Sync-9) ──────────────────────────────────
        # Sync Layer only — citire STRICT din Supabase (freelf_h2h_snapshot,
        # populată de sync/sync_h2h_freelf.py), niciodată apel live către
        # provider. Identitate ORIENTATĂ prin nume canonice normalizate — nu
        # mai necesită `_freelf_event_id` la citire (gate-ul vechi, eliminat
        # — depindea de identificatorul de provider al meciului curent;
        # sincronizarea folosește azi event_id-urile deja descoperite în
        # scheduled_fixtures, R-Sync-7a).
        if DB_QUERIES_MODULE_AVAILABLE:
            home_c = normalize_team_name(home_name)
            away_c = normalize_team_name(away_name)
            try:
                freelf_h2h = get_freelf_h2h_snapshot(home_c, away_c)
                if freelf_h2h and freelf_h2h.get("meetings", 0) >= 1:
                    return H2HRecord(
                        home_team      = home_c,
                        away_team      = away_c,
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
                logger.warning("[H2H] FreeLF Supabase read failed for %s vs %s: %s", home_c, away_c, exc)

        # ── Odds API meciuri recente (ADR-039, R-Sync-6) ───────────────────
        # Sync Layer only — citire STRICT din Supabase
        # (odds_api_recent_results, populată de
        # sync/sync_odds_recent_results.py), niciodată apel live. Aceeași
        # tabelă citită și de _build_profile() Level 2 (formă) — o singură
        # sursă canonică, două derivări la citire (audit R-Sync-6,
        # opțiunea A). Nu mai are nevoie de `sport_key`/`ODDS_SPORT_KEYS`
        # la citire — cheia e direct perechea de nume canonice, valabilă
        # indiferent de ligă (simplificare permisă de migrare, la fel ca
        # eliminarea gate-ului `team_id.startswith("fd_")` la R-Sync-3).
        if not DB_QUERIES_MODULE_AVAILABLE:
            return H2HRecord.empty(home_name, away_name)

        home_c = normalize_team_name(home_name)
        away_c = normalize_team_name(away_name)
        try:
            odds_rows = get_h2h_from_odds_recent(home_c, away_c)
        except Exception as exc:
            odds_rows = []
            logger.warning("[H2H] Odds API Supabase read failed for %s vs %s: %s", home_c, away_c, exc)

        if not odds_rows:
            return H2HRecord.empty(home_name, away_name)

        home_wins = draws = away_wins = 0
        home_g = away_g = 0
        last_5: list[str] = []
        for row in odds_rows[:5]:
            is_home_first = row.get("home_team_canonical") == home_c
            hs  = row.get("home_score", 0) or 0
            as_ = row.get("away_score", 0) or 0
            gf  = hs if is_home_first else as_
            ga  = as_ if is_home_first else hs
            home_g += gf; away_g += ga
            if gf > ga:
                home_wins += 1; last_5.append("H")
            elif gf < ga:
                away_wins += 1; last_5.append("A")
            else:
                draws += 1; last_5.append("D")

        n = len(odds_rows[:5])
        h2h_modifier = compute_h2h_modifier(
            home_wins, away_wins, n, weight=float(self.config.get("h2h_weight", 0.15))
        )
        summary = (
            f"H2H ({n} meciuri): {home_wins}W {draws}D {away_wins}L | "
            f"Goluri: {round(home_g/n,1)}–{round(away_g/n,1)} | Ultimele: {''.join(last_5)}"
        )
        return H2HRecord(
            home_team=home_c, away_team=away_c, meetings=n,
            home_wins=home_wins, draws=draws, away_wins=away_wins,
            home_goals_avg=round(home_g/n, 2), away_goals_avg=round(away_g/n, 2),
            last_5=last_5, h2h_modifier=h2h_modifier, summary=summary,
        )

    # ── _build_profile — v2.3 cascade cu Free Live Football primar ────────
    @staticmethod
    def _real_avg_shots_on_target(canonical: str, league: str, last_n: int = 5) -> float | None:
        """
        Șuturi pe poartă REALE (nu proxy sintetic gf*0.45), din ultimele
        `last_n` meciuri terminate ale echipei în match_history — populate
        prin MatchStatsBackfillService (Premier League/La Liga/Serie A/
        Bundesliga/Ligue 1). Întoarce None dacă nu există date reale — NU
        se aproximează aici, apelantul păstrează fallback-ul sintetic
        existent (Regula #8 — nicio stare necunoscută nu se aproximează).
        """
        if not SUPABASE_MODULE_AVAILABLE:
            return None
        try:
            rows = sb.get_team_recent_shots(canonical, league, last_n=last_n)
        except Exception:
            return None
        if not rows:
            return None
        values = []
        for r in rows:
            if r.get("home_team") == canonical:
                v = r.get("home_shots_on_target")
            elif r.get("away_team") == canonical:
                v = r.get("away_shots_on_target")
            else:
                continue
            if v is not None:
                values.append(float(v))
        if not values:
            return None
        return sum(values) / len(values)

    @staticmethod
    def _real_match_events(canonical: str, league: str, last_n: int = 5) -> dict:
        """
        Cornere/faulturi/cartonașe galbene/gol la pauză/șuturi totale REALE,
        medie pe ultimele `last_n` meciuri terminate — pur informativ
        (Task 2/3 ADR-011, șuturi ADR-021/P7.1), NU alimentează formula de
        rating. Valorile lipsă rămân None — nu se aproximează.
        """
        empty = {"avg_corners": None, "avg_fouls": None, "avg_yellow_cards": None,
                  "avg_ht_goals": None, "avg_shots": None}
        if not SUPABASE_MODULE_AVAILABLE:
            return empty
        try:
            rows = sb.get_team_recent_match_events(canonical, league, last_n=last_n)
        except Exception:
            return empty
        if not rows:
            return empty
        corners, fouls, yellows, ht_goals, shots = [], [], [], [], []
        for r in rows:
            is_home = r.get("home_team") == canonical
            is_away = r.get("away_team") == canonical
            if not (is_home or is_away):
                continue
            c  = r.get("home_corners") if is_home else r.get("away_corners")
            f  = r.get("home_fouls") if is_home else r.get("away_fouls")
            y  = r.get("home_yellow_cards") if is_home else r.get("away_yellow_cards")
            ht = r.get("home_ht_goals") if is_home else r.get("away_ht_goals")
            s  = r.get("home_shots") if is_home else r.get("away_shots")
            if c is not None: corners.append(float(c))
            if f is not None: fouls.append(float(f))
            if y is not None: yellows.append(float(y))
            if ht is not None: ht_goals.append(float(ht))
            if s is not None: shots.append(float(s))
        return {
            "avg_shots": sum(shots) / len(shots) if shots else None,
            "avg_corners": sum(corners) / len(corners) if corners else None,
            "avg_fouls": sum(fouls) / len(fouls) if fouls else None,
            "avg_yellow_cards": sum(yellows) / len(yellows) if yellows else None,
            "avg_ht_goals": sum(ht_goals) / len(ht_goals) if ht_goals else None,
        }

    @staticmethod
    def _current_season_start_date(as_of: date | None = None) -> str:
        """Data de start a sezonului curent de fotbal european (convenția
        deja folosită de oracle_api._tsdb_season_string() — sezonul începe
        în iulie, calculat dinamic din data curentă, niciodată hardcodat).
        Reimplementată local (nu importată din oracle_api) ca să evite o
        dependință nouă între module pentru un calcul de o linie — vezi
        architecture-review."""
        d = as_of or date.today()
        start_year = d.year if d.month >= 7 else d.year - 1
        return date(start_year, 7, 1).isoformat()

    @staticmethod
    def _build_flashscore_dna(canonical: str, league: str, last_n: int = 5) -> dict | None:
        """
        Team DNA Flashscore (Faza 2, ADR-044 §5) — xG real, posesie reală,
        offside, apărări portar, cartonașe roșii, eficiență finalizare,
        volum faze fixe, statistici EAV (pase/dueluri/tackle-uri), rating
        mediu jucători, clasament curent. Context SUPLIMENTAR, pur
        informativ — NU intră în TeamProfile, NU atinge
        compute_team_offdef_rating()/FEATURE_COLUMNS/predicția Oracle servită.

        [ADAUGAT — mărginire la sezonul curent] Toate cele 3 interogări
        sunt mărginite la kickoff_date >= începutul sezonului curent
        (convenția iulie). La cerere explicită a proprietarului produsului:
        loturile se schimbă între sezoane, un profil bazat pe date din
        sezonul trecut nu descrie corect echipa de azi. Verificat live
        (2026-08-15): 100% din datele Flashscore existente sunt oricum din
        sezonul curent (colectarea a pornit 2026-07-14) — mărginirea nu
        pierde nimic azi, protejează doar viitorul, când istoricul cross-
        sezon se va acumula.

        Returnează None dacă modulele necesare lipsesc (degradare identică
        cu restul cascadei _build_profile) — apelantul afișează "—",
        niciodată nu aproximează.
        """
        if not (DB_QUERIES_MODULE_AVAILABLE and FLASHSCORE_TEAM_DNA_AVAILABLE):
            return None
        try:
            since = FootballOracleEngine._current_season_start_date()
            advanced_rows = get_team_recent_advanced_stats(canonical, league, last_n=last_n, since_date=since)
            extended_rows = get_team_recent_statistics_extended(canonical, league, last_n=last_n, since_date=since)
            player_rows = get_team_recent_player_ratings(canonical, league, last_n=last_n, since_date=since)
            standings_row = get_team_standings_row(canonical, league)
            return build_team_dna(advanced_rows, extended_rows, player_rows, standings_row, canonical)
        except Exception as exc:
            logger.warning("[OracleEngine] _build_flashscore_dna failed pentru %s/%s: %s", canonical, league, exc)
            return None

    def _build_profile(self, team_id: str, team_name: str, league: str) -> TeamProfile:
        """
        Cascade:
           DB. Supabase match_history (get_team_recent_results)      ← PRIMAR, ADR-035/D1
          -1. Date naționale hardcodate (World Cup + naționale)      — fallback, doar dacă Level DB nu are date
           FS. Flashscore standings+formă reală (Supabase) (get_team_standings_row) — fallback, ADR-045 (Owner Standings, 14 ligi FLASHSCORE_TRACKED_COMPETITIONS)
           FS2. Flashscore recent match-context form (Supabase) (get_team_recent_form_context) — fallback, adăugat 2026-08-10 (orice echipă/țară/competiție — acoperă cupele europene fără clasament + echipele străine, ex. KuPS)
           0+1. FreeLF standings+formă (Supabase) (get_team_form_freelf_snapshot) — fallback, ADR-039 R-Sync-6
           2. Odds API meciuri recente (Supabase) (get_team_recent_form_oddsapi) — fallback, ADR-039 R-Sync-6
           3. fd.org standings (Supabase)  (get_team_form_footballdata) — fallback, ADR-039 R-Sync-3
           4. TheSportsDB events (Supabase) (get_team_stats_tsdb)     — fallback, ADR-039 R-Sync-8
           5. ELO sigmoid                  (întotdeauna blended)
           6. Neutral defaults

        ELO de club (separat de cascada de mai sus, rulează în paralel):
        match_history.home_elo_after/away_elo_after (get_latest_team_elo,
        ADR-023/ADR-035 D2) — PRIMAR, global per club, indiferent de ligă;
        fallback pe get_national_team_elo() (Supabase, national_team_elo_
        snapshot, ADR-039 R-Sync-4 — populat de Sync Layer din
        eloratings.net, niciodată citit live) doar dacă echipa n-are
        meciuri de club sincronizate (tipic: naționale).

        Principiul de proiectare (ADR-035): niciun provider extern nu poate
        avea prioritate asupra unei informații deja sincronizate și
        validate în baza canonică Supabase — Level DB rulează primul, iar
        toate nivelurile de mai jos sunt gate-uite `if not stats`.
        """
        w         = self.weights
        o_cap     = float(w.get("offensive_cap",  3.5))
        d_cap     = float(w.get("defensive_cap",  2.5))
        last_n    = int(self.config.get("last_n_fixtures", 5))
        canonical = normalize_team_name(team_name)
        real_sot  = self._real_avg_shots_on_target(canonical, league, last_n)

        # ── ELO (ADR-023 Variant C / ADR-035 D2): match_history canonic,
        # PRIMUL ──────────────────────────────────────────────────────────
        # Principiul de proiectare (ADR-035): niciun provider extern nu
        # poate avea prioritate asupra unei informații deja sincronizate în
        # baza canonică. Fallback pentru echipele naționale (fără meciuri
        # de club în match_history) — ADR-039, R-Sync-4: citire STRICT din
        # Supabase (national_team_elo_snapshot, populată de Sync Layer,
        # sync/sync_national_team_elo.py), niciodată apel live către
        # eloratings.net (self.api.get_elo_rating(), eliminat de aici).
        elo_raw = None
        if DB_QUERIES_MODULE_AVAILABLE:
            try:
                elo_raw = get_latest_team_elo(canonical)
            except Exception as exc:
                elo_raw = None
                logger.warning("[Profile] DB-first ELO read failed for %s: %s", canonical, exc)
            if elo_raw is None:
                try:
                    national_elo = get_national_team_elo(canonical)
                    if national_elo:
                        elo_raw = national_elo.get("elo_rating")
                except Exception as exc:
                    logger.warning("[Profile] national ELO Supabase read failed for %s: %s", canonical, exc)
        elo_off   = self._elo_to_multiplier(elo_raw)           if elo_raw else None
        elo_def   = self._elo_to_defensive_multiplier(elo_raw) if elo_raw else None
        elo_blend = float(self.config.get("elo_blend_weight", 0.35))

        stats: list[dict]     = []
        season_entry: dict | None = None
        data_source  = ""

        # ── Level DB (ADR-035 / D1): Supabase match_history — PRIMUL ─────
        # Sursa canonică internă. Principiul de proiectare (ADR-035):
        # niciun provider extern nu poate avea prioritate asupra unei
        # informații deja sincronizate și validate în baza canonică.
        # Sub MIN_DB_MATCHES meciuri terminate recente, se cade pe cascada
        # de provideri existentă, neschimbată — fluxul normal, nu excepția.
        MIN_DB_MATCHES = 3
        if SUPABASE_MODULE_AVAILABLE:
            try:
                db_rows = sb.get_team_recent_results(canonical, league, last_n)
            except Exception as exc:
                db_rows = []
                logger.warning("[Profile] DB-first read failed for %s: %s", canonical, exc)
            db_stats: list[dict] = []
            for r in db_rows:
                is_home = r.get("home_team") == canonical
                is_away = r.get("away_team") == canonical
                if not (is_home or is_away):
                    continue
                hg, ag = r.get("actual_home_goals"), r.get("actual_away_goals")
                res    = r.get("actual_result")
                if hg is None or ag is None or res not in ("H", "D", "A"):
                    continue
                gf_i = float(hg if is_home else ag)
                ga_i = float(ag if is_home else hg)
                if res == "D":
                    letter = "D"
                else:
                    letter = "W" if (res == "H") == is_home else "L"
                db_stats.append({
                    "result": letter, "goals_for": gf_i, "goals_against": ga_i,
                    "shots_on_goal": real_sot if real_sot is not None else gf_i * 0.45,
                    "possession": 50.0,
                })
            if len(db_stats) >= MIN_DB_MATCHES:
                stats        = db_stats
                data_source  = "supabase-history"
                logger.info("[Profile] %s — supabase-history (%d meciuri terminate)",
                            canonical, len(db_stats))

        # ── Level -1: Date naționale hardcodate ───────────────────────────
        from mappings import NATIONAL_TEAM_STATS
        nat = NATIONAL_TEAM_STATS.get(canonical)
        if nat and not stats:
            gf      = float(nat["avg_gf"])
            ga      = float(nat["avg_ga"])
            sot     = float(nat.get("avg_sot", gf * 0.45))
            pos     = float(nat.get("avg_possession", 50.0))
            n       = int(nat.get("matches", 10))
            results = list(nat.get("form", []))
            stats   = [
                {"result": r, "goals_for": gf, "goals_against": ga,
                 "shots_on_goal": sot, "possession": pos}
                for r in (results or ["W"] * 5)
            ]
            data_source  = "national-stats-hardcoded"
            logger.info("[Profile] %s — national stats hardcoded (gf=%.2f ga=%.2f)", canonical, gf, ga)

        # ── Level FS: Flashscore standings (ADR-045, Owner Standings —
        # adăugat 2026-08-10) ──────────────────────────────────────────────
        # Sync Layer only — citire STRICT din Supabase
        # (flashscore_standings_snapshot, populată de persist_match_
        # foundation_data() → upsert_standings_snapshot()), niciodată apel
        # live. Owner declarat explicit pentru Standings (ADR-045 §Matrice,
        # rândul 3) — acoperă azi cele 14 competiții din FLASHSCORE_TRACKED_
        # COMPETITIONS (providers/flashscore/discovery.py). NU înlocuiește
        # Level 0+1 (FreeLF)/Level 3 (football-data.org) de mai jos — rămân
        # fallback neatins pentru ligile în afara acoperirii Flashscore
        # (ex. World Cup, exclus deliberat din FLASHSCORE_TRACKED_
        # COMPETITIONS — identitate URL ambiguă).
        #
        # `form` (migrația 045) — secvență cronologică REALĂ W/D/L, extrasă
        # din badge-urile paginii de clasament (`data-testid="wcl-badgeForm-
        # {win,draw,lose}"`, confirmat live, POC izolat 2026-08-10), cel mai
        # vechi primul, cel mai recent ULTIMUL — exact ordinea cerută de
        # `compute_form_score()`. Nivelul NU se activează dacă `form` e
        # goală (echipă fără niciun rezultat real capturat încă) — mai bine
        # cascada continuă la FreeLF/football-data decât un `results=[]`
        # care ar produce form_score=0.0 (worst-case, nu neutru — Regula #8).
        if not stats and DB_QUERIES_MODULE_AVAILABLE:
            try:
                fs_row = get_team_standings_row(canonical, league)
            except Exception as exc:
                fs_row = None
                logger.warning("[Profile] Flashscore standings read failed for %s: %s", canonical, exc)
            if fs_row:
                form_list = fs_row.get("form") or []
                if form_list:
                    played = fs_row.get("played") or 1
                    gf_avg = (fs_row.get("goals_for", 0) or 0) / played
                    ga_avg = (fs_row.get("goals_against", 0) or 0) / played
                    sot    = real_sot if real_sot is not None else gf_avg * 0.45
                    pos    = 50.0
                    stats  = [
                        {"result": r, "goals_for": gf_avg, "goals_against": ga_avg,
                         "shots_on_goal": sot, "possession": pos}
                        for r in form_list[-last_n:]
                    ]
                    data_source  = "flashscore-standings"
                    logger.info("[Profile] %s — flashscore-standings (%d rezultate reale)",
                                canonical, len(stats))

        # ── Level FS2: Flashscore recent match-context form (adăugat
        # 2026-08-10, caz real confirmat: Univ. Craiova vs KuPS, Europa
        # League calificări) ────────────────────────────────────────────
        # Sync Layer only — citire STRICT din Supabase
        # (flashscore_match_context, populată de normalize_match_context()
        # — H2H e unul din cele 7 tab-uri fetch-uite standard pentru
        # FIECARE meci procesat, deja existent, doar necitit până acum de
        # cascada de profil), niciodată apel live.
        #
        # Level FS (mai sus) acoperă doar clasamentele ligilor domestice
        # urmărite — fazele eliminatorii ale cupelor europene (Champions/
        # Europa/Conference League) NU au niciodată clasament (verificat
        # live: `flashscore_standings_snapshot`, zero rânduri pentru
        # aceste 3 competiții), iar echipele străine din ligi neurmărite
        # (ex. KuPS, Finlanda) nu apar în niciun clasament domestic urmărit
        # de aici. Level FS2 completează exact acest gol — funcționează
        # pentru orice echipă, orice țară, orice competiție, folosind
        # ultimele meciuri REALE ale echipei (nu clasament), cu scor exact
        # per meci (mai precis decât media de sezon folosită la Level FS).
        if not stats and DB_QUERIES_MODULE_AVAILABLE:
            try:
                context_form = get_team_recent_form_context(canonical, n=last_n)
            except Exception as exc:
                context_form = []
                logger.warning("[Profile] Flashscore match-context form read failed for %s: %s", canonical, exc)
            if context_form:
                sot = real_sot if real_sot is not None else (
                    sum(r["goals_for"] for r in context_form) / len(context_form) * 0.45
                )
                pos = 50.0
                stats = [
                    {"result": r["result"], "goals_for": r["goals_for"], "goals_against": r["goals_against"],
                     "shots_on_goal": sot, "possession": pos}
                    for r in context_form
                ]
                data_source = "flashscore-match-context"
                logger.info("[Profile] %s — flashscore-match-context (%d rezultate reale)",
                            canonical, len(stats))

        # ── Level 0+1: Free Live Football standings + formă (ADR-039, R-Sync-6) ─
        # Sync Layer only — citire STRICT din Supabase
        # (freelf_team_form_snapshot, populată de
        # sync/sync_team_form_freelf.py), niciodată apel live. Fuzionează
        # foștii Level 0 (standings) + Level 1 (formă) — ambii citeau
        # ACELAȘI răspuns FreeLF standings (team_id-ul folosit de fostul
        # Level 1 venea din fostul Level 0, nicio dependență de discovery,
        # verificat la audit) — un singur rând persistat servește ambele
        # semnale acum.
        #
        # [GĂSIT LA AUDIT, nu ascuns] `form` va fi aproape mereu goală —
        # reproduce fidel un bug preexistent din calea live (vezi migrarea
        # 021, freelf_form_adapter.py) — NU e o regresie introdusă aici.
        recent_form: list[dict] = []
        if not stats and DB_QUERIES_MODULE_AVAILABLE:
            try:
                freelf_row = get_team_form_freelf_snapshot(canonical)
            except Exception as exc:
                freelf_row = None
                logger.warning("[Profile] FreeLF Supabase read failed for %s: %s", canonical, exc)
            if freelf_row:
                played = freelf_row.get("played") or 5
                gf     = (freelf_row.get("goals_for", 0) or 0) / max(played, 1)
                ga     = (freelf_row.get("goals_against", 0) or 0) / max(played, 1)
                sot    = real_sot if real_sot is not None else gf * 0.45
                pos    = 50.0
                stats  = [
                    {"result": "W", "goals_for": gf, "goals_against": ga,
                     "shots_on_goal": sot, "possession": pos}
                ] * min(played, 5)
                data_source  = "freelf-standings"
                season_entry = {"avg_gf": gf, "avg_ga": ga}
                form_str = freelf_row.get("form", "") or ""
                recent_form = [
                    {"result": ch.upper(), "goals_for": 0, "goals_against": 0, "date": ""}
                    for ch in form_str[-last_n:]
                ]

        # ── Level 2: Odds API meciuri recente (ADR-039, R-Sync-6) ─────────
        # Sync Layer only — citire STRICT din Supabase
        # (odds_api_recent_results, populată de
        # sync/sync_odds_recent_results.py), niciodată apel live. Aceeași
        # tabelă e citită și de _build_h2h() (fallback H2H) — o singură
        # sursă canonică, două derivări la citire (audit R-Sync-6,
        # opțiunea A).
        if not stats and DB_QUERIES_MODULE_AVAILABLE:
            try:
                odds_rows = get_team_recent_form_oddsapi(canonical)
                scores_form: list[dict] = []
                for row in odds_rows:
                    is_home = row.get("home_team_canonical") == canonical
                    gf = row.get("home_score") if is_home else row.get("away_score")
                    ga = row.get("away_score") if is_home else row.get("home_score")
                    if gf is None or ga is None:
                        continue
                    result = "W" if gf > ga else ("L" if gf < ga else "D")
                    scores_form.append({
                        "date": row.get("kickoff_date", ""), "result": result,
                        "goals_for": gf, "goals_against": ga,
                        "shots_on_goal": round(gf * 3.5, 1), "possession": 50.0,
                    })
                if scores_form:
                    stats        = scores_form
                    data_source  = "scores-api"
            except Exception as exc:
                logger.warning("[Profile] Odds API Supabase read failed for %s: %s", canonical, exc)

        # ── Level 3: football-data.org standings (ADR-039, R-Sync-3) ───────
        # Sync Layer only, dupa migrare — citire STRICT din Supabase
        # (footballdata_team_form_snapshot, populata de
        # sync/sync_team_form_footballdata.py), niciodata apel live catre
        # provider. Identitate prin nume canonic normalizat, nu prin
        # team_id prefixat "fd_" (gate-ul vechi, eliminat — depindea de
        # machinery de descoperire a meciurilor, in afara scope-ului
        # acestei migrari).
        if not stats and DB_QUERIES_MODULE_AVAILABLE:
            try:
                fd_standings = get_team_form_footballdata(canonical)
                if fd_standings:
                    played   = fd_standings.get("played") or 1
                    gf_avg   = (fd_standings.get("goals_for",     0) or 0) / played
                    ga_avg   = (fd_standings.get("goals_against", 0) or 0) / played
                    form_str = fd_standings.get("form", "") or ""
                    results  = [r.strip() for r in form_str.split(",") if r.strip()][:last_n]
                    stats    = [
                        {"result": r, "goals_for": gf_avg, "goals_against": ga_avg,
                         "shots_on_goal": gf_avg * 0.45, "possession": 50.0}
                        for r in results
                    ]
                    data_source  = "standings-fd"
            except Exception as exc:
                logger.warning("[Profile] footballdata form read failed for %s: %s", canonical, exc)

        # ── Level 4: TheSportsDB (ADR-039, R-Sync-8) ────────────────────────
        # Sync Layer only — citire STRICT din Supabase
        # (tsdb_team_stats_snapshot, populată de
        # sync/sync_team_stats_tsdb.py), niciodată apel live către provider.
        # Identitate prin nume canonic normalizat (ADR-039 Principiul 7) —
        # NU mai necesită team_id prefixat "tsdb_" la citire (gate-ul vechi,
        # eliminat — depindea de identificatorul de provider al meciului
        # curent; sincronizarea folosește azi tsdb_team_id-urile deja
        # descoperite în scheduled_fixtures, R-Sync-7a).
        if not stats and DB_QUERIES_MODULE_AVAILABLE:
            try:
                tsdb_stats = get_team_stats_tsdb(canonical)
                if tsdb_stats:
                    stats        = tsdb_stats
                    data_source  = "thesportsdb"
            except Exception as exc:
                logger.warning("[Profile] TheSportsDB Supabase read failed for %s: %s", canonical, exc)

        # ── Compute ratings din stats ─────────────────────────────────────
        if stats:
            n = len(stats)
            if season_entry:
                gf  = season_entry.get("avg_gf", sum(s["goals_for"]     for s in stats) / n)
                ga  = season_entry.get("avg_ga", sum(s["goals_against"] for s in stats) / n)
                sot = real_sot if real_sot is not None else gf * 0.45
                pos = 50.0
            else:
                gf  = sum(s["goals_for"]                       for s in stats) / n
                ga  = sum(s["goals_against"]                   for s in stats) / n
                sot = real_sot if real_sot is not None else sum(s.get("shots_on_goal", gf * 0.45) for s in stats) / n
                pos = sum(s.get("possession",    50.0)         for s in stats) / n

            form_source = recent_form if recent_form else stats
            results     = [s["result"] for s in form_source]

            g_w   = float(w.get("goals_weight",      0.45))
            sot_w = float(w.get("shots_ot_weight",   0.30))
            pos_w = float(w.get("possession_weight", 0.25))

            off_rating, def_rating = compute_team_offdef_rating(
                avg_goals_for=gf,
                avg_goals_against=ga,
                avg_shots_on_target=sot,
                avg_possession=pos,
                goals_weight=g_w,
                shots_ot_weight=sot_w,
                possession_weight=pos_w,
                offensive_cap=o_cap,
                defensive_cap=d_cap,
                elo_offensive_multiplier=elo_off,
                elo_defensive_multiplier=elo_def,
                elo_blend_weight=elo_blend,
            )

        # ── Level 5: ELO only ─────────────────────────────────────────────
        elif elo_off is not None:
            baseline   = float(w.get("league_baselines", {}).get(league, w.get("league_baselines", {}).get("default", 1.25)))
            off_rating = round(elo_off * baseline, 4)
            def_rating = round(elo_def, 4)
            gf         = baseline * elo_off
            ga         = baseline * elo_def
            sot        = real_sot if real_sot is not None else gf * 0.45
            pos        = 50.0
            n          = 0
            results    = []
            data_source  = "elo-only"

        # ── Level 6: Neutral defaults ─────────────────────────────────────
        else:
            baseline   = float(w.get("league_baselines", {}).get(league, w.get("league_baselines", {}).get("default", 1.25)))
            logger.warning("No data for '%s' — neutral defaults.", team_name)
            off_rating = round(baseline * 0.65, 4)
            def_rating = round(baseline, 4)
            gf         = baseline
            ga         = baseline
            sot        = real_sot if real_sot is not None else gf * 0.45
            pos        = 50.0
            n          = 0
            results    = []
            data_source  = "neutral-defaults"

        # ── Form score ────────────────────────────────────────────────────
        # Notă (documentat 2026-08-03, EPIC ML Activation & Oracle Evolution,
        # Pasul 6, ORACLE_ENGINE_AUDIT.md §6.3): `results` (formă W/D/L, de
        # mai jos) și `gf`/`ga` (goluri, folosite mai sus pentru off/def
        # rating) provin din ACEEAȘI fereastră `last_n_fixtures` (implicit 5,
        # vezi `last_n` mai sus) — nu e o duplicare de informație (rezultat
        # W/D/L vs. scor brut sunt aspecte diferite), dar ambele semnale sunt
        # derivate din aceeași fereastră temporală mică, ceea ce limitează
        # diversitatea reală a semnalului de intrare. Observație cunoscută,
        # fără acțiune de cod în acest EPIC — o eventuală extindere a
        # `last_n_fixtures` sau diversificare a surselor ar necesita propriul
        # test de ablație, nu o decizie tacită aici.
        form_score = compute_form_score(results)

        off_rating = min(off_rating, o_cap)
        def_rating = min(def_rating, d_cap)

        events = self._real_match_events(canonical, league, last_n)

        # [ADR-035 D4] data_quality derivat într-un PUNCT UNIC, din data_source
        # final + numărul de meciuri — nu mai e atribuit inline per nivel.
        matches_analysed = n if stats else 0
        data_quality = _classify_data_quality(data_source, matches_analysed)

        return TeamProfile(
            team_id=team_id, team_name=canonical,
            matches_analysed=matches_analysed,
            avg_goals_for=round(gf, 3), avg_goals_against=round(ga, 3),
            avg_shots_ot=round(sot, 3), avg_possession=round(pos, 1),
            offensive_rating=off_rating, defensive_rating=def_rating,
            form_results=results[-last_n:] if results else [],
            form_score=round(form_score, 4),
            standings_form=",".join(results),
            elo_rating=elo_raw, data_source=data_source,
            data_quality=data_quality,
            data_quality_note=DATA_QUALITY_NOTES[data_quality],
            avg_corners=round(events["avg_corners"], 2) if events["avg_corners"] is not None else None,
            avg_fouls=round(events["avg_fouls"], 2) if events["avg_fouls"] is not None else None,
            avg_yellow_cards=round(events["avg_yellow_cards"], 2) if events["avg_yellow_cards"] is not None else None,
            avg_ht_goals=round(events["avg_ht_goals"], 2) if events["avg_ht_goals"] is not None else None,
            avg_shots=round(events["avg_shots"], 2) if events["avg_shots"] is not None else None,
        )

    # ── League weights (cold-start blending) ──────────────────────────────
    def _get_league_weights(self, league: str) -> dict:
        return resolve_league_weights(self.weights, league)

    # ── xG calibration ────────────────────────────────────────────────────
    def _calibrate_xg(
        self,
        home_p: TeamProfile,
        away_p: TeamProfile,
        league: str,
        weather_penalty: float = 0.0,
        h2h: H2HRecord | None = None,
    ) -> tuple[float, float]:
        w         = self.weights
        baselines = w.get("league_baselines", {})
        baseline  = float(baselines.get(league, baselines.get("default", 1.25)))
        lw        = self._get_league_weights(league)
        d_cap     = float(w.get("defensive_cap", 2.5))

        home_xg, away_xg = calibrate_xg(
            home_offensive_rating=home_p.offensive_rating,
            home_defensive_rating=home_p.defensive_rating,
            away_offensive_rating=away_p.offensive_rating,
            away_defensive_rating=away_p.defensive_rating,
            home_form_score=home_p.form_score,
            away_form_score=away_p.form_score,
            baseline=baseline,
            form_weight=lw["form_weight"],
            base_weight=lw["base_weight"],
            home_advantage=lw["home_advantage"],
            away_penalty=lw["away_penalty"],
            defensive_cap=d_cap,
            h2h_modifier=(h2h.h2h_modifier if h2h else 0.0),
            h2h_meetings=(h2h.meetings if h2h else 0),
            weather_penalty=weather_penalty,
        )
        logger.info("[xG] home=%.3f  away=%.3f  (weather=%.3f)", home_xg, away_xg, weather_penalty)
        return home_xg, away_xg

    # ── Poisson model ─────────────────────────────────────────────────────
    def _poisson_model(self, home_xg: float, away_xg: float) -> tuple[float, float, float, list]:
        max_g = int(self.config.get("max_goals_poisson", 8))
        return poisson_model(home_xg, away_xg, max_g)

    # ── Value bet helpers ─────────────────────────────────────────────────
    @staticmethod
    def _implied(odds: float) -> float:
        return 0.0 if odds <= 1.0 else 1.0 / odds

    @staticmethod
    def _devig_probabilities(impl_h: float, impl_d: float, impl_a: float) -> tuple[float, float, float]:
        """
        Normalizează probabilitățile implicite BRUTE (1/cotă) astfel încât
        suma lor să fie exact 1.0 — elimină marja bookmaker-ului
        (overround/vig). La orice bookmaker real, suma celor trei
        probabilități brute depășește mereu 100% (tipic 105-108%) — fără
        această normalizare, motorul de Value Betting compară modelul
        propriu cu o probabilitate artificial umflată de marjă, nu cu
        piața reală ("fair"), ceea ce subestimează sistematic edge-ul real.

        Caz limită: dacă suma e 0 (toate cele trei cote lipsă/invalide),
        returnează (0.0, 0.0, 0.0) — fără împărțire la zero, fără valori
        inventate.
        """
        total = impl_h + impl_d + impl_a
        if total <= 0:
            return 0.0, 0.0, 0.0
        return impl_h / total, impl_d / total, impl_a / total

    @staticmethod
    def _edge(model_p: float, impl_p: float) -> float:
        if impl_p <= 0:
            return 0.0
        return round((model_p - impl_p) / impl_p * 100, 2)

    @staticmethod
    def _rating(edge: float) -> str:
        if edge >= 25: return "⚡ ELITE"
        if edge >= 15: return "🔥 HIGH"
        if edge >= 8:  return "✅ MEDIUM"
        return "📌 LOW"

    def _kelly(self, prob: float, odds: float) -> float:
        if odds <= 1.0 or prob <= 0:
            return 0.0
        b  = odds - 1.0
        kf = max((b * prob - (1 - prob)) / b, 0.0)
        return round(
            float(self.config.get("stake_default", 10.0)) *
            kf *
            float(self.config.get("kelly_fraction", 0.25)),
            2,
        )

    # ── Monte Carlo Simulator ─────────────────────────────────────────────
    def _monte_carlo(self, home_xg: float, away_xg: float, n_sim: int = 10_000) -> dict:
        rng        = np.random.default_rng(seed=42)
        home_goals = rng.poisson(home_xg, n_sim)
        away_goals = rng.poisson(away_xg, n_sim)

        ph = float(np.mean(home_goals > away_goals))
        pd = float(np.mean(home_goals == away_goals))
        pa = float(np.mean(home_goals < away_goals))

        over25  = float(np.mean((home_goals + away_goals) > 2.5))
        over15  = float(np.mean((home_goals + away_goals) > 1.5))
        under25 = float(np.mean((home_goals + away_goals) < 2.5))
        btts    = float(np.mean((home_goals > 0) & (away_goals > 0)))
        cs_h    = float(np.mean(away_goals == 0))
        cs_a    = float(np.mean(home_goals == 0))
        dc_h    = float(np.mean(home_goals >= away_goals))
        dc_a    = float(np.mean(home_goals <= away_goals))

        poisson_ph, poisson_pd, poisson_pa, _ = self._poisson_model(home_xg, away_xg)
        divergence   = (abs(ph - poisson_ph) + abs(pd - poisson_pd) + abs(pa - poisson_pa)) / 3.0
        consistency  = max(0.0, 1.0 - divergence * 10.0)
        max_p        = max(ph, pd, pa)
        concentration = (max_p - 0.333) / 0.667

        confidence_raw   = (consistency * 0.4 + concentration * 0.6) * 100.0
        confidence_score = round(min(max(confidence_raw, 5.0), 99.0), 1)

        if confidence_score >= 70:
            confidence_label = "🟢 Ridicat"
        elif confidence_score >= 45:
            confidence_label = "🟡 Mediu"
        else:
            confidence_label = "🔴 Scăzut"

        logger.info("[MC] ph=%.3f pd=%.3f pa=%.3f confidence=%.1f%%", ph, pd, pa, confidence_score)

        return {
            "mc_prob_home":            round(ph,     4),
            "mc_prob_draw":            round(pd,     4),
            "mc_prob_away":            round(pa,     4),
            "confidence_score":        confidence_score,
            "confidence_label":        confidence_label,
            "mc_simulations":          n_sim,
            "prob_over25":             round(over25,  4),
            "prob_over15":             round(over15,  4),
            "prob_under25":            round(under25, 4),
            "prob_btts":               round(btts,    4),
            "prob_clean_sheet_home":   round(cs_h,    4),
            "prob_clean_sheet_away":   round(cs_a,    4),
            "prob_double_chance_home": round(dc_h,    4),
            "prob_double_chance_away": round(dc_a,    4),
        }

    # ── Value bets piețe speciale ─────────────────────────────────────────
    def _special_value_bets(self, mc: dict, match: dict) -> list[dict]:
        results   = []
        threshold = float(self.config.get("value_bet_threshold_pct", 5.0))

        markets = [
            ("Over 2.5",         mc["prob_over25"],             "over25_odds"),
            ("Under 2.5",        mc["prob_under25"],            "under25_odds"),
            ("BTTS Da",          mc["prob_btts"],               "btts_yes_odds"),
            ("BTTS Nu",          1 - mc["prob_btts"],           "btts_no_odds"),
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
                    "market":         market_name,
                    "model_prob_pct": round(model_prob * 100, 1),
                    "bk_odds":        bk_odds,
                    "edge_pct":       round(edge, 2),
                    "rating":         self._rating(edge),
                })

        return sorted(results, key=lambda x: x["edge_pct"], reverse=True)

    # ── ML feature builder (v3.0) ───────────────────────────────────────
    def _build_ml_features(
        self, home_p: TeamProfile, away_p: TeamProfile, h2h: H2HRecord,
        home_xg: float, away_xg: float, ph: float, pd_: float, pa: float,
        mc: dict, weather_penalty: float,
    ) -> dict:
        return {
            "home_xg_pred":            home_xg,
            "away_xg_pred":            away_xg,
            "home_offensive_rating":   home_p.offensive_rating,
            "home_defensive_rating":   home_p.defensive_rating,
            "away_offensive_rating":   away_p.offensive_rating,
            "away_defensive_rating":   away_p.defensive_rating,
            "home_form_score":         home_p.form_score,
            "away_form_score":         away_p.form_score,
            "home_elo":                home_p.elo_rating or 1500,
            "away_elo":                away_p.elo_rating or 1500,
            "h2h_modifier":            h2h.h2h_modifier if h2h else 0.0,
            "h2h_meetings":            h2h.meetings if h2h else 0,
            # [ADAUGAT — ADR-012] Aceeași derivare ca în ml_predictor.
            # _fetch_training_dataframe(): diferență, nu medii brute
            # stocate redundant. None dacă istoricul real lipsește pentru
            # oricare echipă — XGBoost gestionează nativ (missing-value
            # split), niciodată aproximat.
            "corner_dominance":        (home_p.avg_corners - away_p.avg_corners)
                                        if home_p.avg_corners is not None and away_p.avg_corners is not None
                                        else None,
            "card_diff":               (away_p.avg_yellow_cards - home_p.avg_yellow_cards)
                                        if home_p.avg_yellow_cards is not None and away_p.avg_yellow_cards is not None
                                        else None,
            # [ADAUGAT — ADR-013] Aceeași disciplină ca mai sus.
            "foul_diff":               (away_p.avg_fouls - home_p.avg_fouls)
                                        if home_p.avg_fouls is not None and away_p.avg_fouls is not None
                                        else None,
            # [ADAUGAT — ADR-021/P7.1] Aceeași disciplină, promovat prin
            # ablație (docs/03_ENGINE/SHOT_DOMINANCE_ABLATION_2026-07-15.md).
            "shot_dominance":          (home_p.avg_shots - away_p.avg_shots)
                                        if home_p.avg_shots is not None and away_p.avg_shots is not None
                                        else None,
            "weather_penalty":         weather_penalty,
            "mc_prob_home":            mc["mc_prob_home"],
            "mc_prob_draw":            mc["mc_prob_draw"],
            "mc_prob_away":            mc["mc_prob_away"],
        }

    # ── evaluate_match ────────────────────────────────────────────────────
    def evaluate_match(self, match: dict) -> MatchPrediction | None:
        home_name = match["home_team"]
        away_name = match["away_team"]
        league    = match.get("league", "Unknown")
        fid       = match.get("fixture_id", "?")
        logger.info("━━━ evaluate %s vs %s [%s] ━━━", home_name, away_name, league)

        home_p = self._build_profile(match.get("home_team_id", ""), home_name, league)
        away_p = self._build_profile(match.get("away_team_id", ""), away_name, league)
        logger.info("Home: OFF=%.3f DEF=%.3f [%s]", home_p.offensive_rating, home_p.defensive_rating, home_p.data_quality)
        logger.info("Away: OFF=%.3f DEF=%.3f [%s]", away_p.offensive_rating, away_p.defensive_rating, away_p.data_quality)

        h2h = self._build_h2h(home_name, away_name, match)

        # [Faza 2, ADR-044 §5] Context suplimentar, pur informativ — NU
        # intră în home_p/away_p/h2h de mai sus, deci nu poate atinge
        # predicția Oracle servită/confidence.
        home_flashscore_dna = self._build_flashscore_dna(home_name, league)
        away_flashscore_dna = self._build_flashscore_dna(away_name, league)

        # [ADR-039, R-Sync-5] Citire STRICT din Supabase
        # (weather_forecast_cache, populată de Sync Layer,
        # sync/sync_weather_forecast.py) — niciodată apel live către
        # WeatherAPI din Oracle Engine (self.api.get_weather(), eliminat
        # de aici). Cheia (city, kickoff_date) trebuie să fie IDENTICĂ cu
        # cea folosită la sincronizare — `venue_city` brut, FĂRĂ fallback
        # pe numele ligii (fallback-ul vechi era chiar bug-ul demonstrat
        # în audit: trimitea "Premier League" ca oraș). Dacă orașul
        # lipsește sau perechea nu a fost încă sincronizată, penalizarea
        # rămâne 0.0 — neutru, nu aproximat (Regula #8).
        city    = match.get("venue_city", "")
        weather = None
        if DB_QUERIES_MODULE_AVAILABLE and city:
            try:
                weather = get_weather_forecast(city, match.get("kickoff_date", ""))
            except Exception as exc:
                logger.warning("[Weather] Supabase read failed for %s: %s", city, exc)
        w_pen   = float(weather.get("xg_penalty", 0.0)) if weather else 0.0
        w_note  = weather.get("description", "") if weather else ""

        home_xg, away_xg = self._calibrate_xg(home_p, away_p, league, w_pen, h2h)

        # ── Injury penalty — Database-First (R-Sync-10, ADR-039) ────────────
        # [ACTUALIZAT Sprint 3, audit complet] Fostul apel live
        # (injury_manager.get_lineup_absences() -> oracle_api.get_lineup())
        # era ULTIMUL loc din oracle_engine.py care modifica efectiv
        # predicția servită pe baza unui apel live la provider — găsit la
        # audit, nu ascuns. Citește azi STRICT din Supabase
        # (freelf_lineup_snapshot, populată de sync/sync_lineup_freelf.py,
        # cadență dedicată 15 min — vezi .github/workflows/lineup_sync.yml),
        # niciodată apel live. Logica de calcul a penalizării e IDENTICĂ,
        # neschimbată — extrasă din injury_manager.get_lineup_absences() în
        # injury_manager.build_injury_report_from_raw_lineup() (funcție
        # pură), doar sursa datelor brute s-a mutat.
        home_xg_pre        = home_xg
        away_xg_pre        = away_xg
        injury_note        = "ℹ️ Date accidentări indisponibile"
        home_injury_report = None
        away_injury_report = None

        if self.injury_manager and DB_QUERIES_MODULE_AVAILABLE:
            try:
                lineup_snapshot = get_freelf_lineup_snapshot(
                    normalize_team_name(home_name), normalize_team_name(away_name),
                    match.get("kickoff_date", ""),
                )
                if lineup_snapshot:
                    home_lineup_raw = {
                        "confirmed":   lineup_snapshot.get("home_confirmed", False),
                        "formation":   lineup_snapshot.get("home_formation", ""),
                        "unavailable": lineup_snapshot.get("home_unavailable") or [],
                    }
                    away_lineup_raw = {
                        "confirmed":   lineup_snapshot.get("away_confirmed", False),
                        "formation":   lineup_snapshot.get("away_formation", ""),
                        "unavailable": lineup_snapshot.get("away_unavailable") or [],
                    }
                    home_injury_report = self.injury_manager.build_injury_report_from_raw_lineup(
                        home_lineup_raw, match.get("_freelf_home_id", ""), home_name,
                    )
                    away_injury_report = self.injury_manager.build_injury_report_from_raw_lineup(
                        away_lineup_raw, match.get("_freelf_away_id", ""), away_name,
                    )
                    home_xg, away_xg, injury_note = self.injury_manager.apply_injury_penalty(
                        home_xg, away_xg, home_injury_report, away_injury_report,
                    )
                    if (home_injury_report and home_injury_report.has_key_absences) or \
                       (away_injury_report and away_injury_report.has_key_absences):
                        logger.warning("[Injuries] Key absences! %s", injury_note)
            except Exception as exc:
                logger.warning("[Injuries] Supabase read failed for %s vs %s: %s", home_name, away_name, exc)

        logger.info(
            "[xG after injuries] home=%.3f (was %.3f)  away=%.3f (was %.3f)",
            home_xg, home_xg_pre, away_xg, away_xg_pre,
        )

        # ── Team Health (injuries + coaches) — Database-First (R-Sync-2, ADR-039) ──
        # [ACTUALIZAT R-Sync-2] Nu mai apeleaza niciun provider extern — citeste
        # exclusiv Supabase (team_health_snapshot), populata separat de Sync Layer
        # (sync/sync_team_health.py, apifootball_health_adapter.py), niciodata aici.
        # Lipsa unei intrari (echipa inca nesincronizata) inseamna "necunoscut"
        # (Regula #8) — NICIODATA fallback live catre provider (ADR-039 elimina
        # explicit acea exceptie, spre deosebire de ELO/H2H sub ADR-035).
        # NU modifica home_xg/away_xg (productia ramane neschimbata) - datele merg
        # doar in shadow log (gated de shadow_mode_enabled), consistent cu ADR-002.
        apifootball_metadata: dict = {}
        if DB_QUERIES_MODULE_AVAILABLE:
            try:
                home_health = get_team_health(normalize_team_name(home_name))
                away_health = get_team_health(normalize_team_name(away_name))
                if home_health or away_health:
                    apifootball_metadata = {
                        "home_injuries": (home_health or {}).get("injuries", []),
                        "away_injuries": (away_health or {}).get("injuries", []),
                        "home_coaches":  (home_health or {}).get("coaches", []),
                        "away_coaches":  (away_health or {}).get("coaches", []),
                    }
            except Exception as exc:
                logger.warning("[TeamHealth] Citire eșuată pentru %s vs %s: %s", home_name, away_name, exc)

        ph, pd, pa, top_scores = self._poisson_model(home_xg, away_xg)
        # [ADAUGAT — ADR-031] Instantaneu al ieșirii brute a motorului
        # rule-based (Poisson + Monte Carlo + ELO, deja blendat intern la
        # acest punct) — Oracle rămâne mereu pur de aici încolo (niciun
        # blend legacy in-place, eliminat ADR-051/052), deci rb_ph/rb_pd/rb_pa
        # sunt identice cu ph/pd/pa finale. Păstrat explicit, separat, ca
        # sursă dedicată pentru raw_predictions (ADR-031) — nu implicit.
        rb_ph, rb_pd, rb_pa = ph, pd, pa

        # ── Monte Carlo ───────────────────────────────────────────────────
        n_sim         = int(self.config.get("monte_carlo_simulations", 10000))
        mc            = self._monte_carlo(home_xg, away_xg, n_sim)
        special_vbets = self._special_value_bets(mc, match)

        # [ADAUGAT — ADR-051/052] ML Engine — a treia voce independentă,
        # calculată aici (nu doar mai jos, la finalul funcției) ca să poată
        # alimenta atât raw_predictions (ADR-031) cât și pred.ml_engine_prediction
        # direct la construcție. Oracle (ph/pd/pa) rămâne mereu pur — niciun
        # blend legacy in-place aici; singurul Blend din arhitectura finală
        # e blend_engine.py, motor separat (vezi _get_blend_engine_prediction()
        # mai jos, apelat după construcția pred).
        ml_engine_prediction = self._get_ml_engine_prediction(
            home_p, away_p, h2h, home_xg, away_xg, ph, pd, pa, mc, w_pen,
        )
        ml_active    = bool(ml_engine_prediction and ml_engine_prediction.get("available"))
        ml_prob_home = ml_engine_prediction["prob_home"] if ml_active else 0.0
        ml_prob_draw = ml_engine_prediction["prob_draw"] if ml_active else 0.0
        ml_prob_away = ml_engine_prediction["prob_away"] if ml_active else 0.0

        bk_h = float(match.get("home_odds") or 0.0)
        bk_d = float(match.get("draw_odds") or 0.0)
        bk_a = float(match.get("away_odds") or 0.0)
        bk_n = match.get("odds_source") or "N/A"

        impl_h = self._implied(bk_h); impl_d = self._implied(bk_d); impl_a = self._implied(bk_a)
        # [MODIFICAT] de-vig — vezi Prioritatea #2. impl_* rămân brute (afișate
        # ca atare în UI, neschimbate — fără regresie). fair_* sunt folosite
        # de acum pentru TOATE calculele de edge/EV/value bets/Kelly.
        fair_h, fair_d, fair_a = self._devig_probabilities(impl_h, impl_d, impl_a)
        edge_h = self._edge(ph, fair_h) if bk_h > 1 else 0.0
        edge_d = self._edge(pd, fair_d) if bk_d > 1 else 0.0
        edge_a = self._edge(pa, fair_a) if bk_a > 1 else 0.0

        threshold  = float(self.config.get("value_bet_threshold_pct", 5.0))
        value_bets: list[dict] = []
        for sel, ep, mp, odds in [
            ("Home Win", edge_h, ph, bk_h),
            ("Draw",     edge_d, pd, bk_d),
            ("Away Win", edge_a, pa, bk_a),
        ]:
            if ep >= threshold:
                conf = ""
                if home_p.data_quality == DATA_QUALITY_NEUTRAL or away_p.data_quality == DATA_QUALITY_NEUTRAL:
                    conf = " ⚠️ date estimate"
                elif home_p.data_quality == DATA_QUALITY_ELO or away_p.data_quality == DATA_QUALITY_ELO:
                    conf = " 🟡 ELO only"
                value_bets.append({
                    "market": "1X2", "selection": sel, "edge_pct": ep,
                    "rating": self._rating(ep), "model_prob_pct": round(mp * 100, 2),
                    "bk_odds": odds, "confidence_note": conf,
                })

        kelly: dict[str, float] = {}
        for sel, prob, odds in [("Home Win", ph, bk_h), ("Draw", pd, bk_d), ("Away Win", pa, bk_a)]:
            if odds > 1.0:
                kelly[sel] = self._kelly(prob, odds)

        # [ADAUGAT — ADR-031] N-way Serving Policy — vezi build_raw_predictions().
        raw_predictions = build_raw_predictions(
            rb_ph, rb_pd, rb_pa, ml_active, ml_prob_home, ml_prob_draw, ml_prob_away,
        )

        pred = MatchPrediction(
            fixture_id=str(fid), home_team=home_name, away_team=away_name, league=league,
            kickoff_utc=match.get("kickoff_utc", ""), kickoff_date=match.get("kickoff_date", ""),
            season=match.get("season", 2026),
            home_xg=home_xg, away_xg=away_xg,
            prob_home_win=round(ph, 4), prob_draw=round(pd, 4), prob_away_win=round(pa, 4),
            top_scores=top_scores,
            bk_home_odds=bk_h, bk_draw_odds=bk_d, bk_away_odds=bk_a, bookmaker_name=bk_n,
            impl_home_pct=round(impl_h * 100, 2), impl_draw_pct=round(impl_d * 100, 2),
            impl_away_pct=round(impl_a * 100, 2),
            fair_home_pct=round(fair_h * 100, 2), fair_draw_pct=round(fair_d * 100, 2),
            fair_away_pct=round(fair_a * 100, 2),
            edge_home_pct=edge_h, edge_draw_pct=edge_d, edge_away_pct=edge_a,
            value_bets=value_bets, weather_note=w_note, weather_penalty=w_pen,
            kelly_stakes=kelly,
            home_profile=home_p, away_profile=away_p, h2h=h2h,
            data_quality_home=home_p.data_quality, data_quality_away=away_p.data_quality,
            home_injury_report=home_injury_report, away_injury_report=away_injury_report,
            injury_note=injury_note, home_xg_pre_injury=home_xg_pre,
            away_xg_pre_injury=away_xg_pre,
            # Monte Carlo
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
            raw_predictions=raw_predictions,
            ml_engine_prediction=ml_engine_prediction,
            home_flashscore_dna=home_flashscore_dna, away_flashscore_dna=away_flashscore_dna,
        )
        self._cache_prediction(pred, home_p, away_p, h2h, w_pen, mc)

        # [ADAUGAT] Shadow log pt datele API-Football colectate mai sus -
        # nu face nimic daca shadow_mode_enabled=False (implicit), deci
        # productia ramane 100% neschimbata. Foloseste predictia FINALA
        # (ph/pd/pa) - acest experiment inca nu propune o varianta
        # alternativa de xG, doar capteaza contextul pt analiza viitoare.
        if apifootball_metadata:
            self.log_shadow_experiment(
                pred=pred, experiment_name="apifootball_injuries_coaches", experiment_version="v1",
                home_xg=home_xg, away_xg=away_xg, prob_home=ph, prob_draw=pd, prob_away=pa,
                feature_metadata=apifootball_metadata, processing_stage="final",
            )

        # [ADAUGAT — Faza 3, exceptie M4 aprobata explicit 2026-07-29] Shadow
        # log pt Team DNA Flashscore (home/away_flashscore_dna, deja
        # construite mai sus, Faza 2) - flag DEDICAT
        # (flashscore_shadow_logging_enabled, implicit OPRIT), acelasi tipar
        # exact ca apifootball_injuries_coaches: foloseste predictia FINALA
        # (ph/pd/pa) - acest experiment inca nu propune o varianta
        # alternativa de xG, doar captureaza contextul pt analiza viitoare
        # (ablatie reala, cand exista volum suficient de meciuri reale
        # colectate - vezi R-SYNC-FLASH-01_PREDICTOR_IMPACT_ANALYSIS.md §3).
        if home_flashscore_dna or away_flashscore_dna:
            self.log_shadow_experiment(
                pred=pred, experiment_name="flashscore_team_dna", experiment_version="v1",
                home_xg=home_xg, away_xg=away_xg, prob_home=ph, prob_draw=pd, prob_away=pa,
                feature_metadata={"home_flashscore_dna": home_flashscore_dna, "away_flashscore_dna": away_flashscore_dna},
                processing_stage="final", enabled_flag="flashscore_shadow_logging_enabled",
            )

        # [ADAUGAT — Pasul 3, Implementation Contract Learning Core] Shadow
        # logging pt Challenger activ (daca exista) — flag DEDICAT
        # (challenger_shadow_logging_enabled, implicit False), separat de
        # shadow_mode_enabled. Zero impact asupra productiei: ruleaza dupa
        # ce `pred` a fost deja construita complet mai sus, nu o modifica
        # niciodata, iar rezultatul acestei metode e ignorat de apelant.
        self._log_challenger_shadow(
            pred, home_p, away_p, h2h, home_xg, away_xg, ph, pd, pa, mc, w_pen,
        )

        # Shadow logging pt Challenger-ul Blend (ADR-050/Pasul 13) — flag
        # dedicat, separat de cel de mai sus. Nu modifica `pred`.
        self._log_blend_challenger_shadow(
            pred, home_p, away_p, h2h, home_xg, away_xg, ph, pd, pa, mc, w_pen,
        )

        # [ADAUGAT — ADR-033, Faza 1] Captură observațională a ieșirilor
        # brute (raw_predictions, ADR-031) — flag DEDICAT
        # (consensus_capture_enabled, implicit False), separat de
        # challenger_shadow_logging_enabled și de learning_core_enabled.
        # Zero impact asupra producției: rulează după ce `pred` a fost deja
        # construită complet, nu o modifică niciodată, rezultatul acestei
        # metode e ignorat de apelant.
        self._log_consensus_capture(pred)

        # [ADAUGAT — ADR-051/ADR-052] BlendEngine — motor independent
        # (blend_engine.py, algoritm neschimbat), afișat simultan cu
        # Oracle/ML, fără niciun selector/fallback. Flag dedicat
        # (blend_engine_display_enabled). Singura mutație:
        # pred.blend_engine_prediction (câmp izolat, fără alt cititor) —
        # nu atinge raw_predictions/prob_home_win/shadow_predictions.
        # De la ADR-052: consumă și pred.ml_engine_prediction (deja calculat
        # mai sus), dacă disponibil — vezi _get_blend_engine_prediction().
        pred.blend_engine_prediction = self._get_blend_engine_prediction(pred)

        # [ADAUGAT — ADR-061] Campion PROMOVAT al familiei blend_v1 (Model
        # Registry) — a patra voce independentă, afișată simultan cu
        # Oracle/ML/Blend static de mai sus. Flag dedicat
        # (blend_v1_champion_display_enabled). Singura mutație:
        # pred.blend_v1_champion_prediction (câmp izolat) — nu atinge
        # raw_predictions/prob_home_win/shadow_predictions.
        pred.blend_v1_champion_prediction = self._get_blend_v1_champion_prediction(
            pred, home_p, away_p, h2h, home_xg, away_xg, ph, pd, pa, mc, w_pen,
        )

        # [ADAUGAT — ADR-052] Validation Framework — colectare automată,
        # per meci, a ieșirilor disponibile Oracle/ML/Blend, pentru analize
        # periodice ulterioare. Flag DEDICAT (validation_framework_enabled,
        # implicit OPRIT), separat de toate celelalte. Rulează DUPĂ ce toate
        # cele trei predicții sunt deja calculate — nu modifică pred, nu
        # influențează nimic din ce se servește. Rezultatul acestei metode e
        # ignorat de apelant (exact tiparul shadow logging de mai sus).
        self._log_validation_snapshot(pred)

        return pred

    # ── Utility methods ───────────────────────────────────────────────────
    def get_week_matches(self, days_ahead: int = 7, competitions: list[str] | None = None) -> list[dict]:
        return self.api.get_matches_for_week(days_ahead=days_ahead, competitions=competitions)

    def get_matches_by_date(self, target_date: str) -> list[dict]:
        return self.api.get_matches_for_date(target_date)

    def _cache_prediction(
        self, pred: MatchPrediction, home_p: TeamProfile, away_p: TeamProfile,
        h2h: H2HRecord, weather_penalty: float, mc: dict,
    ) -> None:
        """Salvează predicția — local (pentru recalibrare rapidă) ȘI, dacă
        Supabase e activ, un rând complet de feature-uri în match_history
        (fără rezultat încă — se completează la update_weights_from_result)."""
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
            # feature-uri ML — reținute ca să nu trebuiască reconstruite
            # la momentul update_weights_from_result()
            "ml_features": self._build_ml_features(
                home_p, away_p, h2h, pred.home_xg_pre_injury, pred.away_xg_pre_injury,
                pred.prob_home_win, pred.prob_draw, pred.prob_away_win, mc, weather_penalty,
            ),
        }
        safe_id = str(pred.fixture_id).replace("/", "_")
        _save_json(PREDICTIONS_DIR / f"{safe_id}.json", data)

        if self.use_supabase:
            mlf = data["ml_features"]
            # [ADR-036 / D3.5 Stage 1] Prediction Engine scrie DOAR ieșirile
            # proprii de predicție. Cele 10 FEATURE_COLUMNS owner-ate de
            # backfill (home/away_offensive_rating, home/away_defensive_rating,
            # home/away_form_score, home/away_elo, h2h_modifier, h2h_meetings)
            # NU se mai trimit de aici — rămân NULL până le completează
            # sync/backfill_features.run_backfill() cu recalculul walk-forward,
            # sursa canonică unică. Astfel `first-writer-wins` (COALESCE) nu mai
            # îngheață valori din cascada live peste recalculul corect. RPC-ul
            # (upsert_match_canonical) rămâne neschimbat — coloanele absente din
            # payload nu sunt atinse (COALESCE(existing, NULL) = existing).
            sb.upsert_match_history({
                "fixture_id":   pred.fixture_id,
                "home_team":    pred.home_team,
                "away_team":    pred.away_team,
                "league":       pred.league,
                "kickoff_date": pred.kickoff_date,
                "home_xg_pred": mlf["home_xg_pred"],
                "away_xg_pred": mlf["away_xg_pred"],
                "weather_penalty": mlf["weather_penalty"],
                "home_data_quality": pred.data_quality_home,
                "away_data_quality": pred.data_quality_away,
                "prob_home_pred": pred.prob_home_win,
                "prob_draw_pred": pred.prob_draw,
                "prob_away_pred": pred.prob_away_win,
                "mc_prob_home": mlf["mc_prob_home"],
                "mc_prob_draw": mlf["mc_prob_draw"],
                "mc_prob_away": mlf["mc_prob_away"],
            })

    # [ADAUGAT] Hook generic de shadow testing — vezi shadow_testing.py /
    # architecture/ADR-002-shadow-testing.md. NU e apelat încă de nimic în
    # fluxul curent (niciun experiment activ până la integrarea reală a
    # unui feature nou — Etapa 6) — există aici, gata de folosit, ca orice
    # experiment viitor (injuries, coaches, player stats, SofaScore etc.)
    # să nu reinventeze gating-ul pe `shadow_mode_enabled` sau construcția
    # câmpurilor standard (fixture_id, ligă, echipe, dată).
    def log_shadow_experiment(
        self, pred: MatchPrediction, experiment_name: str, experiment_version: str,
        home_xg: float, away_xg: float, prob_home: float, prob_draw: float, prob_away: float,
        feature_metadata: dict | None = None, processing_stage: str = "final",
        experiment_group: str = "treatment", enabled_flag: str = "shadow_mode_enabled",
    ) -> bool:
        """Nu face nimic dacă flag-ul din `enabled_flag` e False (implicit)
        — zero impact asupra producției. `enabled_flag` (implicit
        `shadow_mode_enabled`, comportament neschimbat pentru apelul
        existent `apifootball_injuries_coaches`) — parametrizat explicit
        [ADAUGAT Faza 3] ca fiecare experiment nou să aibă propriul flag
        DEDICAT (la fel ca `challenger_shadow_logging_enabled`/
        `consensus_capture_enabled`), fără să reutilizeze/conflice cu
        flag-ul altui experiment — exact intenția documentată în docstring-ul
        modulului acestei metode ("orice experiment viitor... să nu
        reinventeze gating-ul"). `baseline_model_version` se calculează
        automat din predicția de producție curentă (pred), nu trebuie dat
        explicit de apelant."""
        if not self.config.get(enabled_flag, False):
            return False
        try:
            import shadow_testing
            return shadow_testing.log_shadow_prediction(
                fixture_id=pred.fixture_id,
                experiment_name=experiment_name, experiment_version=experiment_version,
                home_xg=home_xg, away_xg=away_xg,
                prob_home=prob_home, prob_draw=prob_draw, prob_away=prob_away,
                feature_metadata=feature_metadata, experiment_group=experiment_group,
                processing_stage=processing_stage,
                league=pred.league, home_team=pred.home_team, away_team=pred.away_team,
                kickoff_date=pred.kickoff_date,
            )
        except Exception as exc:
            logger.debug("[ShadowTesting] log_shadow_experiment failed: %s", exc)
            return False

    # [ADAUGAT — Pasul 3, Implementation Contract Learning Core] Shadow
    # logging pt Challenger activ — vezi ADR-016 (Challenger FSM, Pasul 2) și
    # docs/00_GOVERNANCE/ADR-017-challenger-shadow-logging.md (+ addendum
    # Chief Architect Review: Shadow e un SIDE EFFECT, nu parte din
    # Prediction Pipeline). Flag DEDICAT (`challenger_shadow_logging_enabled`,
    # implicit False) — NU reutilizează `shadow_mode_enabled`, care rămâne
    # legat exclusiv de experimentul apifootball_injuries_coaches.
    #
    # REGULĂ ARHITECTURALĂ: OracleEngine → Shadow Adapter → ChallengerManager.
    # Această metodă NU importă niciodată learning_core.challenger_manager
    # direct — trece exclusiv prin learning_core.challenger_shadow (adapter),
    # singura frontieră permisă. Verificat prin gardă arhitecturală
    # (tests/test_challenger_shadow_logging.py).
    def _log_challenger_shadow(
        self, pred: MatchPrediction, home_p: TeamProfile, away_p: TeamProfile,
        h2h: H2HRecord, home_xg: float, away_xg: float,
        ph: float, pd_: float, pa: float, mc: dict, weather_penalty: float,
    ) -> bool:
        """Nu face nimic dacă challenger_shadow_logging_enabled=False
        (implicit) — return imediat, zero import, zero apel Supabase, zero
        cost. Nu modifică NICIODATĂ `pred` — parametrii sunt folosiți doar
        pentru a reconstrui feature-urile ML deja calculate mai sus
        (_build_ml_features e pură, fără efecte secundare), nu pentru a
        recalcula predicția servită. Orice eșec e prins aici — niciodată
        propagat către evaluate_match()."""
        if not self.config.get("challenger_shadow_logging_enabled", False):
            return False
        try:
            from ml_predictor import _ALGORITHM_FAMILY, _LEAGUE_SCOPE
            from learning_core.challenger_shadow import log_shadow_for_active_challenger

            ml_features = self._build_ml_features(
                home_p, away_p, h2h, home_xg, away_xg, ph, pd_, pa, mc, weather_penalty,
            )
            return log_shadow_for_active_challenger(
                algorithm_family=_ALGORITHM_FAMILY, league_scope=_LEAGUE_SCOPE,
                features=ml_features,
                fixture_id=pred.fixture_id, home_xg=home_xg, away_xg=away_xg,
                control_prob_home=pred.prob_home_win, control_prob_draw=pred.prob_draw,
                control_prob_away=pred.prob_away_win,
                league=pred.league, home_team=pred.home_team, away_team=pred.away_team,
                kickoff_date=pred.kickoff_date,
            )
        except Exception as exc:
            logger.debug("[ChallengerShadow] _log_challenger_shadow failed: %s", exc)
            return False

    def _log_blend_challenger_shadow(
        self, pred: MatchPrediction, home_p: TeamProfile, away_p: TeamProfile,
        h2h: H2HRecord, home_xg: float, away_xg: float,
        ph: float, pd_: float, pa: float, mc: dict, weather_penalty: float,
    ) -> bool:
        """Simetric cu _log_challenger_shadow(), dar pentru Challenger-ul
        Blend (algorithm_family="blend_v1"); flag propriu, neschimbat de
        challenger_shadow_logging_enabled (vezi ADR-050). Flag oprit = zero
        cost. Nu modifică NICIODATĂ `pred`. Orice eșec e prins aici,
        niciodată propagat mai departe."""
        if not self.config.get("blend_challenger_shadow_logging_enabled", False):
            return False
        try:
            from ml_predictor import _LEAGUE_SCOPE
            from learning_core.blend_challenger_shadow import log_shadow_for_active_blend_challenger

            ml_features = self._build_ml_features(
                home_p, away_p, h2h, home_xg, away_xg, ph, pd_, pa, mc, weather_penalty,
            )
            return log_shadow_for_active_blend_challenger(
                league_scope=_LEAGUE_SCOPE,
                oracle_probs=(pred.prob_home_win, pred.prob_draw, pred.prob_away_win),
                features=ml_features,
                fixture_id=pred.fixture_id, home_xg=home_xg, away_xg=away_xg,
                league=pred.league, home_team=pred.home_team, away_team=pred.away_team,
                kickoff_date=pred.kickoff_date,
            )
        except Exception as exc:
            logger.debug("[BlendChallengerShadow] _log_blend_challenger_shadow failed: %s", exc)
            return False

    def _get_blend_engine_prediction(self, pred: MatchPrediction) -> dict | None:
        """[ADAUGAT — ADR-051/ADR-052] Predicția BlendEngine (blend_engine.py,
        motor independent, ALGORITM NESCHIMBAT — WeightedAverageStrategy)
        pentru AFIȘARE în UI — read-only, nu scrie NIMIC în
        shadow_predictions/raw_predictions. Flag propriu
        (blend_engine_display_enabled). Flag oprit sau self.blend
        indisponibil = zero cost, None.

        [ADR-052] Construiește al doilea EngineOutput (ML) DOAR dacă
        pred.ml_engine_prediction e deja disponibil (calculat mai devreme
        în evaluate_match(), înainte de acest apel — vezi ordinea acolo) —
        altfel rămâne exact comportamentul dinainte de ADR-052, un singur
        EngineOutput (Oracle). Zero schimbare în blend_engine.py — era deja
        generic pe listă, nu pe număr fix de motoare. Orice eșec e prins
        aici, niciodată propagat mai departe."""
        if not self.config.get("blend_engine_display_enabled", False):
            return None
        if self.blend is None:
            return None
        try:
            outputs = [EngineOutput(
                engine="oracle",
                prob_home=pred.prob_home_win, prob_draw=pred.prob_draw, prob_away=pred.prob_away_win,
            )]
            mp = pred.ml_engine_prediction
            if mp and mp.get("available"):
                outputs.append(EngineOutput(
                    engine="ml",
                    prob_home=mp["prob_home"], prob_draw=mp["prob_draw"], prob_away=mp["prob_away"],
                ))
            return self.blend.predict(outputs)
        except Exception as exc:
            logger.debug("[BlendEngine] _get_blend_engine_prediction failed: %s", exc)
            return None

    def _get_blend_v1_champion_prediction(
        self, pred: MatchPrediction, home_p: TeamProfile, away_p: TeamProfile,
        h2h: H2HRecord, home_xg: float, away_xg: float,
        ph: float, pd_: float, pa: float, mc: dict, weather_penalty: float,
    ) -> dict | None:
        """[ADR-061] Predicția Campionului PROMOVAT al familiei blend_v1
        (Model Registry) — read-only, NU modifică ph/pd_/pa, NU scrie nimic
        în shadow_predictions (asta rămâne exclusiv
        blend_challenger_shadow.py, pt Challenger-ul activ, neschimbat).
        Flag propriu (blend_v1_champion_display_enabled). Distinct de
        _get_blend_engine_prediction() de mai sus (motor static, algoritm
        neschimbat, fără Model Registry) — cele două NU trebuie confundate,
        nici în cod, nici în UI (vezi ADR-061).

        Reutilizează integral learning_core.blend_challenger_shadow.
        predict_with_blend_challenger() — aceeași funcție deja testată prin
        shadow logging, apelată acum cu training_run_id-ul Campionului
        PROMOVAT (blend_v1_champion_loader.py), nu al Challenger-ului activ.

        Trei stări distincte, niciodată aproximate: flag oprit sau eroare
        neprevăzută -> None; Campion indisponibil (nicio promovare încă,
        superseded, artefact invalid) -> dict cu motiv explicit; succes ->
        dict cu probabilități."""
        if not self.config.get("blend_v1_champion_display_enabled", False):
            return None
        try:
            from learning_core.blend_v1_champion_loader import load_blend_v1_champion_or_none
            from learning_core.blend_challenger_shadow import predict_with_blend_challenger
            from ml_predictor import _LEAGUE_SCOPE

            champion = load_blend_v1_champion_or_none(_LEAGUE_SCOPE)
            if champion is None:
                return {"available": False, "reason": "champion_indisponibil"}

            ml_features = self._build_ml_features(
                home_p, away_p, h2h, home_xg, away_xg, ph, pd_, pa, mc, weather_penalty,
            )
            blend_probs = predict_with_blend_challenger(
                oracle_probs=(pred.prob_home_win, pred.prob_draw, pred.prob_away_win),
                features=ml_features, training_run_id=champion.training_run_id,
            )
            if blend_probs is None:
                return {"available": False, "reason": "predictie_esuata"}
            b_ph, b_pd, b_pa = blend_probs
            return {"available": True, "prob_home": b_ph, "prob_draw": b_pd, "prob_away": b_pa}
        except Exception as exc:
            logger.debug("[BlendV1Champion] _get_blend_v1_champion_prediction failed: %s", exc)
            return None

    def _resolve_ml_traceability(self) -> dict:
        """[ADAUGAT — trasabilitate ML Engine, ADR-052/North Star #9]
        training_run_id/algorithm_version pentru rândul Validation
        Framework. Sursa PREFERATĂ e Champion-ul rezolvat
        (self.champion_diagnostic — completă, include validated_at). Dacă
        acela nu are training_run_id (niciun Champion real promovat încă —
        stare curentă în producție azi, self.ml_source=="local") ȘI modelul
        local chiar a antrenat cu succes în acest proces
        (self.ml.last_training_run_id), se folosește acela ca fallback —
        sursă reală (identifică exact rularea de antrenare care a produs
        modelul curent), nu aproximată. Fără fallback, rândul rămâne
        onest: training_run_id=None (Regula #8, nu se aproximează)."""
        if self.champion_diagnostic.get("training_run_id"):
            return self.champion_diagnostic
        if self.ml_source == "local" and self.ml is not None:
            local_run_id = getattr(self.ml, "last_training_run_id", None)
            if local_run_id:
                from ml_predictor import _ALGORITHM_VERSION
                return {"training_run_id": local_run_id, "algorithm_version": _ALGORITHM_VERSION}
        return self.champion_diagnostic

    def _log_validation_snapshot(self, pred: MatchPrediction) -> bool:
        """[ADAUGAT — ADR-052] Validation Framework — colectare automată,
        per meci, a ieșirilor disponibile Oracle/ML/Blend, pentru analize
        periodice (zilnice/săptămânale/lunare) ulterioare. Flag DEDICAT
        (validation_framework_enabled, implicit OPRIT), separat de toate
        celelalte. NU ia decizii, NU optimizează, NU promovează — pur
        observațional (ADR-052 §2.3). Nu modifică pred. Transmite
        _resolve_ml_traceability() (Champion dacă disponibil, altfel
        fallback pe antrenarea locală curentă) — trasabilitate ML completă
        (training_run_id/algorithm_version, migrația 007) pe rândul
        persistat, indiferent dacă ML-ul activ vine dintr-un Champion
        promovat sau dintr-o antrenare locală. Orice eșec (modul
        indisponibil, Supabase indisponibil, eroare neprevăzută) e prins
        aici, niciodată propagat către evaluate_match()."""
        if not self.config.get("validation_framework_enabled", False):
            return False
        try:
            import validation_framework
            return validation_framework.save_snapshot(pred, self._resolve_ml_traceability())
        except Exception as exc:
            # [CORECTAT — audit "erori silențioase în loguri"] warning, nu
            # debug — root logger e INFO, la debug eșecul n-ar apărea deloc.
            logger.warning("[ValidationFramework] _log_validation_snapshot failed: %s", exc)
            return False

    def _get_ml_engine_prediction(
        self, home_p: TeamProfile, away_p: TeamProfile, h2h: H2HRecord,
        home_xg: float, away_xg: float, ph: float, pd_: float, pa: float, mc: dict, w_pen: float,
    ) -> dict | None:
        """[ADR-051/052] Predicția ML Engine (self.ml, deja Champion-aware
        prin _resolve_champion()) — sursa canonică unică a ieșirii ML în
        arhitectura finală: alimentează atât pred.ml_engine_prediction
        (afișare UI) cât și raw_predictions (ADR-031) și Blend
        (_get_blend_engine_prediction()). Read-only — nu modifică ph/pd_/pa
        primite, nu scrie nimic în shadow_predictions. Flag propriu
        (ml_engine_display_enabled) — niciun mecanism paralel de blend
        in-place mai există în oracle_engine.py.

        Apel propriu la self.ml.predict(), cu exact aceleași feature-uri
        (_build_ml_features(), neschimbată). Zero al doilea apel către
        champion_loader — self.ml e deja rezolvat o singură dată, la
        construcția procesului (_resolve_champion()).

        Trei stări distincte, niciodată aproximate: flag oprit sau eroare
        neprevăzută -> None; ML activ dar indisponibil/predicție eșuată ->
        dict cu motiv explicit; succes -> dict cu probabilități."""
        if not self.config.get("ml_engine_display_enabled", False):
            return None
        if self.ml is None or not self.ml.is_trained:
            return {"available": False, "reason": "model_indisponibil"}
        try:
            ml_features = self._build_ml_features(
                home_p, away_p, h2h, home_xg, away_xg, ph, pd_, pa, mc, w_pen,
            )
            ml_pred = self.ml.predict(ml_features)
            if ml_pred is None:
                return {"available": False, "reason": "predictie_esuata"}
            return {
                "available": True,
                "prob_home": ml_pred.prob_home, "prob_draw": ml_pred.prob_draw, "prob_away": ml_pred.prob_away,
            }
        except Exception as exc:
            logger.debug("[MLEngine] _get_ml_engine_prediction failed: %s", exc)
            return None

    # [ADAUGAT — ADR-033, Faza 1] Singura frontieră spre infrastructura
    # proprie de eșantionare Consensus Validation — trece exclusiv prin
    # learning_core.consensus_capture (adapter), simetric cu granița deja
    # impusă pentru Shadow (OracleEngine -> Adapter, niciodată direct la
    # persistență/decizie). oracle_engine.py nu importă niciodată
    # learning_core.consensus_validation (Faza 2, T1) — cele două faze
    # comunică exclusiv prin tabela persistată, niciodată prin apel direct.
    def _log_consensus_capture(self, pred: MatchPrediction) -> bool:
        """Nu face nimic dacă consensus_capture_enabled=False (implicit) —
        return imediat, zero import, zero apel Supabase, zero cost. Nu
        modifică NICIODATĂ `pred`. Orice eșec e prins aici, niciodată
        propagat către evaluate_match()."""
        if not self.config.get("consensus_capture_enabled", False):
            return False
        try:
            from learning_core.consensus_capture import capture_raw_predictions

            return capture_raw_predictions(
                fixture_id=pred.fixture_id, raw_predictions=pred.raw_predictions,
                league=pred.league, home_team=pred.home_team, away_team=pred.away_team,
                kickoff_date=pred.kickoff_date,
            )
        except Exception as exc:
            logger.debug("[ConsensusCapture] _log_consensus_capture failed: %s", exc)
            return False

    def _load_prediction(self, fixture_id: str) -> dict | None:
        safe_id = str(fixture_id).replace("/", "_")
        p = PREDICTIONS_DIR / f"{safe_id}.json"
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None

    # ── Self-learning recalibration ───────────────────────────────────────
    def update_weights_from_result(
        self, fixture_id: str, actual_home_goals: int, actual_away_goals: int
    ) -> dict:
        """
        [FIX v1.1] Wrapper subtire peste recalibration.recalibrate_weights() —
        NU mai duplica logica de recalibrare inline (era o a doua
        implementare separata de cea din recalibration.py, desi docstring-ul
        modulului pretindea ca acesta e "wrapper subtire" — nu era). Acum
        chiar este.

        Ramane utilizabila manual (ex. pentru testare sau recalibrare
        retroactiva punctuala), dar NU mai e parte din fluxul automat de
        League Learning — acela ruleaza prin sync/sync_results.py, care
        recalibreaza direct din match_history in Supabase, fara sa treaca
        pe aici si fara sa depinda de cache-ul local de predictii.
        """
        cache = self._load_prediction(fixture_id)
        if cache is None:
            return {"status": "error", "message": f"No cached prediction for {fixture_id}."}

        # [ADR-036 / D3.5 Stage 3] Scrierea legacy a rezultatului real
        # (actual_home_goals/actual_away_goals/actual_result) în match_history
        # a fost ELIMINATĂ de aici. Owner-ul canonic al coloanelor `actual_*`
        # este `sync/sync_results.py` (overwrite permis, pentru corecție de
        # scor). Această funcție e o cale manuală/legacy, neapelată în niciun
        # flux automat (verificat AST: zero apeluri reale), iar scrierea ei era
        # `COALESCE` fill-once — strict mai slabă decât `sync_results`. Rămâne
        # exclusiv recalibrarea (scopul ei real), fără efect asupra contractului
        # de scriere al `actual_*`.
        pred_h = float(cache.get("home_xg", 1.25))
        pred_a = float(cache.get("away_xg", 1.00))
        league = cache.get("league", "default")
        lr     = float(self.config.get("recalibration_learning_rate", 0.05))
        max_d  = float(self.config.get("recalibration_max_delta",     0.15))

        half_life = float(self.config.get("recency_half_life_days", 365))
        recency   = compute_recency_weight(cache.get("kickoff_date"), half_life)

        new_weights, result = recalibrate_weights(
            self.weights,
            league=league, pred_home_xg=pred_h, pred_away_xg=pred_a,
            actual_home_goals=actual_home_goals, actual_away_goals=actual_away_goals,
            fixture_id=fixture_id,
            home_team=cache.get("home_team", ""), away_team=cache.get("away_team", ""),
            learning_rate=lr, max_delta=max_d, recency_weight=recency,
        )
        self.weights = new_weights
        self._persist_weights()

        if result.log_row is not None:
            if self.use_supabase:
                sb.append_recalibration_log(result.log_row)
            else:
                log_row_csv = {"timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"), **result.log_row}
                exists = RECAL_LOG_PATH.exists()
                with RECAL_LOG_PATH.open("a", newline="", encoding="utf-8") as f:
                    wr = csv.DictWriter(f, fieldnames=list(log_row_csv.keys()))
                    if not exists:
                        wr.writeheader()
                    wr.writerow(log_row_csv)

        return {
            "status":         result.status,
            "fixture_id":     fixture_id,
            "league":         league,
            "pred_home_xg":   result.pred_home_xg,
            "pred_away_xg":   result.pred_away_xg,
            "actual_home":    actual_home_goals,
            "actual_away":    actual_away_goals,
            "home_error":     result.home_error,
            "away_error":     result.away_error,
            "combined_error": result.combined_error,
            "adjustments":    result.adjustments,
            "reason":         result.reason,
            "recency_weight": round(recency, 4),
        }

    # ── ML training trigger (v3.0) ────────────────────────────────────────
    def retrain_ml_model(self):
        """[MODIFICAT — ADR-055] Strict diagnostic — antrenează o instanță
        NOUĂ, aruncată, de MLPredictorEngine, niciodată self.ml (obiectul
        folosit de _get_ml_engine_prediction() pentru servire live, deja
        populat prin _resolve_champion()/seed_from_champion() cu Campionul
        real, promovat). engine e @st.cache_resource — partajat între toți
        utilizatorii aplicației — deci antrenarea directă pe self.ml ar
        suprascrie, live, modelul care servește predicții tuturor, ocolind
        complet Challenger Framework/Promotion Engine/ADR-002. Rezultatul
        (accuracy/log-loss/samples) rămâne util ca răspuns la "dacă aș
        antrena acum, ce aș obține?", fără niciun efect asupra modelului
        activ. Antrenarea reală, guvernată, rămâne exclusiv Learning Core
        (continuous_learning.py, ADR-030)."""
        if not ML_MODULE_AVAILABLE:
            return {"status": "unavailable", "message": "Modulul ml_predictor.py lipsește."}
        result = MLPredictorEngine().train()
        return {
            "status": result.status, "samples_used": result.samples_used,
            "accuracy": result.accuracy, "log_loss": result.log_loss,
            "message": result.message,
        }

    def log_challenger_shadow_for_week(self, days_ahead: int = 7) -> dict:
        """[ADAUGAT — ADR-056] Evaluează TOATE meciurile descoperite pentru
        fereastra curentă (self.api.get_matches_for_week(), Database-First,
        ADR-053), indiferent dacă userul le vizionează în aplicație —
        accelerează acumularea de predicții shadow pentru Challenger-ul
        activ (MIN_MATCHES_FOR_EVALUATION, tot 200 — pragul NU se schimbă,
        doar viteza de acumulare). evaluate_match() rămâne complet
        neschimbat — shadow logging-ul rulează pe același traseu ca la o
        vizionare manuală (_log_challenger_shadow(), gatat de
        challenger_shadow_logging_enabled). Idempotent — vezi
        shadow_testing.log_shadow_prediction() (upsert pe fixture_id/
        experiment_name/experiment_version/experiment_group/
        processing_stage) — sigur de rulat zilnic pentru aceleași meciuri
        încă nejucate, doar reîmprospătează predicția. Orice eșec per meci
        e izolat, nu oprește restul batch-ului (Regula #8)."""
        matches = self.api.get_matches_for_week(days_ahead=days_ahead)
        evaluated = 0
        for m in matches:
            try:
                if self.evaluate_match(m) is not None:
                    evaluated += 1
            except Exception as exc:
                logger.warning(
                    "[ChallengerShadowBatch] evaluate_match a eșuat pentru %s vs %s: %s",
                    m.get("home_team"), m.get("away_team"), exc,
                )
        return {"matches_checked": len(matches), "evaluated": evaluated}

    def get_ml_status(self) -> dict:
        if not self.ml:
            return {"available": False}
        status = self.ml.status_summary()
        status["available"] = True
        status["supabase_connected"] = self.use_supabase
        return status

    # ── Portfolio ─────────────────────────────────────────────────────────
    HEADERS = ["Date", "FixtureID", "Match", "Market", "Selection", "Odds", "Stake", "Result", "PnL"]

    def log_bet(self, fixture_id, match_name, market, selection, odds, stake, result="") -> dict:
        if self.use_supabase:
            return sb.log_bet(fixture_id, match_name, market, selection, odds, stake, result)

        result = result.upper().strip()
        pnl    = round(stake * (odds - 1), 2) if result == "W" else (-round(stake, 2) if result == "L" else 0.0)
        row    = {
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
        return row

    def get_league_learning_stats(self) -> pd.DataFrame:
        global_defaults = {
            "form_weight": 0.60, "base_weight": 0.40, "goals_weight": 0.45,
            "shots_ot_weight": 0.30, "possession_weight": 0.25,
            "home_advantage": 1.07, "away_penalty": 0.95,
        }
        lw_all = self.weights.get("league_weights", {})
        rows   = []
        for league, lw in lw_all.items():
            if league == "default":
                continue
            sc = int(lw.get("sample_count", 0))
            rows.append({
                "League":     league,
                "Samples":    sc,
                "Confidence": f"{min(sc / 5 * 100, 100):.0f}%",
                "form_w":     round(float(lw.get("form_weight",    0.60)), 4),
                "base_w":      round(float(lw.get("base_weight",     0.40)), 4),
                "goals_w":    round(float(lw.get("goals_weight",   0.45)), 4),
                "home_adv":   round(float(lw.get("home_advantage", 1.07)), 4),
                "Δ form_w":   round(float(lw.get("form_weight",    0.60)) - global_defaults["form_weight"],    4),
                "Δ goals_w":  round(float(lw.get("goals_weight",   0.45)) - global_defaults["goals_weight"],   4),
                "Δ home_adv": round(float(lw.get("home_advantage", 1.07)) - global_defaults["home_advantage"], 4),
            })
        if not rows:
            return pd.DataFrame(columns=[
                "League", "Samples", "Confidence", "form_w", "base_w",
                "goals_w", "home_adv", "Δ form_w", "Δ goals_w", "Δ home_adv",
            ])
        return pd.DataFrame(rows).sort_values("Samples", ascending=False).reset_index(drop=True)

    def portfolio_summary(self) -> pd.DataFrame | None:
        if self.use_supabase:
            rows = sb.get_portfolio()
            if not rows:
                return None
            df = pd.DataFrame(rows)
            # Normalizează numele coloanelor la formatul vechi (Date, FixtureID, ...)
            # ca app.py să continue să funcționeze fără modificări suplimentare
            rename_map = {
                "bet_date": "Date", "fixture_id": "FixtureID", "match_name": "Match",
                "market": "Market", "selection": "Selection", "odds": "Odds",
                "stake": "Stake", "result": "Result", "pnl": "PnL",
            }
            df = df.rename(columns=rename_map)
            cols = [c for c in self.HEADERS if c in df.columns]
            return df[cols] if not df.empty else None

        if not PORTFOLIO_PATH.exists():
            return None
        df = pd.read_csv(PORTFOLIO_PATH)
        return df if not df.empty else None
