"""
================================================================================
FOOTBALL ORACLE — Bootstrap League Learning
================================================================================
Module: sync/bootstrap_league_learning.py

Reface `league_weights` per ligă, printr-un replay cronologic INDEPENDENT
pentru fiecare competiție suportată — ca și cum sistemul ar fi rulat live,
separat, câte un canal per ligă, încă din primul meci al acelei ligi.

CHANGES v2 (strategie bootstrap — NU se modifică recalibrate_weights()):
  - [SCOPE] Procesează DOAR cele 9 competiții din BOOTSTRAP_LEAGUES, nu tot
    ce apare normalizat în match_history (înainte: tot istoricul, toate
    ligile amestecate într-o singură buclă cronologică).
  - [FEREASTRĂ] Limitat la ultimele HISTORICAL_SEASONS_BACK sezoane (implicit
    5), folosind EXACT aceeași definiție de "sezon" (1 iulie) ca la import —
    vezi _compute_season_cutoff_date() în sync/import_historical.py. Nu s-a
    inventat o a doua definiție de "sezon" în proiect.
  - [IZOLARE COMPLETĂ] Fiecare ligă are propriul replay independent:
    ELOTracker, FormTracker și H2HTracker proaspete per ligă (nu global) —
    o echipă care joacă și în campionatul intern și în cupele europene NU
    își împrumută starea ELO/formă/H2H între cele două replay-uri. La fel,
    fiecare ligă pornește din DEFAULT_WEIGHTS (nu din rezultatul altei
    ligi) — niciun semnal de eroare dintr-o ligă nu se scurge în alta.
  - [SALVARE] Se scrie DOAR league_weights[liga] pentru fiecare din cele 9
    ligi procesate (câte o intrare, rezultatul exclusiv al replay-ului ei).
    Câmpurile globale de top-level (form_weight, dna_weight, goals_weight,
    shots_ot_weight, possession_weight, home_advantage, away_penalty,
    league_baselines, offensive_cap, defensive_cap) NU mai sunt suprascrise
    de bootstrap — rămân la valorile din DEFAULT_WEIGHTS, ca fallback pur
    (folosit de resolve_league_weights() pentru orice ligă cu sample_count
    mic, sau pentru ligi neprocesate aici, ex. MLS). Notă tehnică: acest
    "îngheț" e aplicat la nivel de orchestrator (run_bootstrap), NU în
    recalibrate_weights() — acea funcție tot mută intern câmpurile globale
    la fiecare pas (neschimbat, v1.1), dar rezultatul ei global e aruncat la
    finalul fiecărui replay de ligă; se păstrează doar league_weights[liga].
  - [--limit] Semantică schimbată: acum se aplică PER LIGĂ (primele N
    meciuri din fiecare ligă, după filtrarea pe sezon), nu global pe un
    singur flux amestecat de meciuri — replay-ul nemaifiind un singur flux.

IMPORTANT — acest script rămâne complet AUTONOM față de backfill_features.py:
  - NU citește coloanele-cache (home_elo, home_form_score, home_offensive_rating,
    h2h_modifier, backfill_done, ...) din match_history. Acelea sunt doar un
    cache pentru aplicație, nu sursa de adevăr pentru bootstrap.
  - Reconstruiește singur ELO / formă / H2H din (home_team, away_team, league,
    kickoff_date, actual_home_goals, actual_away_goals, actual_result) — adică
    exact coloanele "brute" ale unui rezultat real, nimic altceva.

Ce NU face acest script (intenționat):
  - NU scrie niciodată în match_history (nu marchează backfill_done, nu
    modifică nicio coloană de-acolo). Singurele scrieri sunt:
      1. model_weights — UN SINGUR save_weights() la finalul TUTUROR
         replay-urilor (nu unul per ligă — vezi run_bootstrap()).
      2. recalibration_log — în batch-uri, nu un request per meci.
  - NU pornește de la model_weights curent din Supabase (care reflectă doar
    predicțiile live existente). Fiecare ligă pornește de la DEFAULT_WEIGHTS.
  - NU inventează statistici lipsă (shots, shots_on_target, possession —
    absente 100% din dataset-ul Kaggle). Folosește EXACT aceleași fallback-uri
    ca motorul live atunci când aceste statistici lipsesc:
      sot = avg_goals_for * 0.45   (proxy, identic cu _build_profile)
      pos = 50.0                    (neutru, identic cu _build_profile)
    și, dacă o echipă nu are încă niciun meci în istoricul LIGII CURENTE
    (primul ei meci din replay-ul acelei ligi), folosește cascada live
    Level 5 "ELO only" (fără formă, fără blend din statistici) — nu
    Level 6 "neutral defaults", pentru că ELO-ul (via ELOTracker) există
    întotdeauna, chiar dacă valoarea inițială e 1500.

Matematica (form score, H2H modifier, transformări ELO→multiplicator,
calibrare xG, model Poisson, blend de ponderi per-ligă, rating ofensiv/defensiv)
vine EXCLUSIV din feature_engine.py — exact aceeași matematică pe care o
folosește motorul live. Reconstrucția stării (ELO/formă/H2H de-a lungul
timpului) vine din clasele deja existente în sync/backfill_features.py
(ELOTracker, FormTracker, H2HTracker) — nu sunt reimplementate aici.

Algoritmul de recalibrare (recalibrate_weights în recalibration.py) NU a
fost modificat în această etapă — doar strategia de la nivelul bootstrap-ului
(ce meciuri intră în replay, cum sunt grupate, ce se salvează).

Rulare:
  python sync/bootstrap_league_learning.py                 # toate cele 9 ligi, ultimele 5 sezoane
  python sync/bootstrap_league_learning.py --dry-run        # fără scriere în Supabase
  python sync/bootstrap_league_learning.py --limit 2000     # primele 2000 de meciuri DIN FIECARE ligă (test)
  python sync/bootstrap_league_learning.py --seasons-back 3 # suprascrie fereastra implicită de 5 sezoane
================================================================================
"""
from __future__ import annotations

import argparse
import copy
import logging
import sys
import time
from pathlib import Path

root = Path(__file__).parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from mappings import normalize_team_name, normalize_league_name
from feature_engine import (
    calibrate_xg,
    poisson_model,               # noqa: F401  (importat pentru simetrie/uz viitor — vezi nota din run())
    resolve_league_weights,
)
from recalibration import recalibrate_weights, compute_recency_weight
from sync.backfill_features import (
    ELOTracker, FormTracker, H2HTracker, fetch_all_matches, team_pre_match_rating,
)
from sync.import_historical import HISTORICAL_SEASONS_BACK, _compute_season_cutoff_date
from oracle_engine import DEFAULT_CONFIG, DEFAULT_WEIGHTS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(levelname)s]  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("FootballOracle.Bootstrap")

# ════════════════════════════════════════════════════════════════════════════
# CONFIGURARE — competițiile procesate de bootstrap
# ════════════════════════════════════════════════════════════════════════════
# [v2] Listă explicită, confirmată — NU se deduce din FREE_LF_LEAGUE_IDS,
# ODDS_SPORT_KEYS sau alt dicționar din mappings.py, care au acoperiri
# diferite (surse API vs ligi învățate). Ligile din DEFAULT_WEIGHTS care nu
# apar aici (ex. "MLS") NU sunt procesate de bootstrap — intrarea lor din
# DEFAULT_WEIGHTS rămâne neschimbată, ca fallback.
#
# "World Cup 2026" e inclus explicit; dacă match_history nu are (încă)
# meciuri reale pentru el, replay-ul acelei "ligi" procesează 0 meciuri —
# sample_count rămâne 0, iar resolve_league_weights() cade natural pe
# fallback-ul global (comportament existent, nemodificat).
BOOTSTRAP_LEAGUES: list[str] = [
    "Premier League",
    "La Liga",
    "Serie A",
    "Bundesliga",
    "Ligue 1",
    "Champions League",
    "Europa League",
    "Romania SuperLiga",
    "World Cup 2026",
]


def get_client():
    from supabase_client import get_client as _gc
    return _gc()


# ════════════════════════════════════════════════════════════════════════════
# NORMALIZARE + DEDUPLICARE ÎN MEMORIE (per ligă)
# ════════════════════════════════════════════════════════════════════════════

def normalize_and_dedupe(raw_matches: list[dict], league_label: str = "") -> list[dict]:
    """
    Normalizează home_team/away_team/league și elimină duplicatele — același
    meci real apărut de mai multe ori în match_history (de ex. o dată din
    sincronizarea live "fd_...", o dată din importul bulk "kaggle_...").

    `raw_matches` trebuie să fie deja sortat cronologic (kickoff_date, id
    ascendent) — fetch_all_matches() face deja asta. Cheia de deduplicare e
    (home_normalizat, away_normalizat, league_normalizat, kickoff_date); se
    păstrează PRIMA apariție întâlnită (adică cea cu id-ul cel mai mic —
    de obicei sursa live-sincronizată, inserată înaintea bulk-import-ului).

    `league_label` e doar pentru claritatea log-ului (numele ligii al cărei
    replay independent apelează această funcție) — nu afectează logica.
    """
    seen: set[tuple] = set()
    out: list[dict] = []
    duplicates = 0

    for m in raw_matches:
        home = normalize_team_name(m.get("home_team", ""))
        away = normalize_team_name(m.get("away_team", ""))
        league = normalize_league_name(m.get("league", ""))
        date = str(m.get("kickoff_date", ""))[:10]

        key = (home, away, league, date)
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)

        out.append({
            **m,
            "home_team": home,
            "away_team": away,
            "league": league,
            "kickoff_date": date,
        })

    label = f"[{league_label}] " if league_label else ""
    logger.info(
        "[Bootstrap] %sNormalizare + deduplicare: %d meciuri unice (%d duplicate eliminate)",
        label, len(out), duplicates,
    )
    return out


# ════════════════════════════════════════════════════════════════════════════
# FEREASTRA DE SEZOANE
# ════════════════════════════════════════════════════════════════════════════

def _filter_by_season_window(matches: list[dict], cutoff_iso: str) -> list[dict]:
    """
    Păstrează doar meciurile cu kickoff_date >= cutoff_iso (string ISO
    "YYYY-MM-DD", comparabil lexicografic). Meciurile fără kickoff_date
    valid (string gol) sunt excluse — nu presupunem că aparțin ferestrei.

    `matches` trebuie să aibă deja `kickoff_date` normalizat la primele 10
    caractere (normalize_and_dedupe() face asta).
    """
    return [m for m in matches if str(m.get("kickoff_date", "")) >= cutoff_iso]


# ════════════════════════════════════════════════════════════════════════════
# FEATURE-URI PRE-MECI (identic cu cascada live, fără statistici lipsă)
# ════════════════════════════════════════════════════════════════════════════

# ════════════════════════════════════════════════════════════════════════════
# [UNIFICAT — v3] _team_pre_match_rating() a fost mutată în
# sync/backfill_features.py ca team_pre_match_rating() — SINGURA
# implementare, folosită acum identic de backfill (run_backfill) și de
# bootstrap (mai jos, importată direct, nu redefinită). Elimină divergența
# de model documentată anterior în feature_engine.py.
# ════════════════════════════════════════════════════════════════════════════


# ════════════════════════════════════════════════════════════════════════════
# REPLAY INDEPENDENT — O SINGURĂ LIGĂ
# ════════════════════════════════════════════════════════════════════════════

def _bootstrap_one_league(
    league: str,
    cutoff_iso: str,
    limit: int | None,
    config: dict,
) -> dict:
    """
    Rulează replay-ul cronologic + recalibrarea PENTRU O SINGURĂ LIGĂ, complet
    izolat: trackere (ELO/Formă/H2H) proaspete, `weights` propriu pornind de
    la DEFAULT_WEIGHTS, fără nicio informație împrumutată din alte ligi.

    Returnează un dict cu:
      - "league_weights_entry": dict | None — league_weights[league] rezultat
        din acest replay, sau None dacă liga nu a avut niciun meci valid
        (caz în care apelantul păstrează fallback-ul din DEFAULT_WEIGHTS).
      - "log_rows": list[dict] — rândurile de recalibration_log ale acestei ligi.
      - "processed" / "recalibrated" / "stable": contoare pentru rezumat.
    """
    logger.info("─" * 60)
    logger.info("[Bootstrap] Ligă: %s — încep replay independent", league)

    raw_matches = fetch_all_matches(league=league)  # filtrare server-side, deja cronologic
    if not raw_matches:
        logger.warning("[Bootstrap] [%s] Niciun meci găsit în match_history. Sar peste.", league)
        return {"league_weights_entry": None, "log_rows": [], "processed": 0,
                "recalibrated": 0, "stable": 0}

    matches = normalize_and_dedupe(raw_matches, league_label=league)
    matches = _filter_by_season_window(matches, cutoff_iso)
    logger.info(
        "[Bootstrap] [%s] %d meciuri în fereastra ultimelor sezoane (cutoff %s)",
        league, len(matches), cutoff_iso,
    )
    if limit:
        matches = matches[:limit]

    if not matches:
        logger.warning(
            "[Bootstrap] [%s] Niciun meci în fereastra de sezoane selectată. Sar peste.", league
        )
        return {"league_weights_entry": None, "log_rows": [], "processed": 0,
                "recalibrated": 0, "stable": 0}

    # ── Stare izolată: propriile trackere + propriile ponderi, pornind de la DEFAULT_WEIGHTS ──
    weights = copy.deepcopy(DEFAULT_WEIGHTS)
    elo_tracker = ELOTracker()
    form_tracker = FormTracker()
    h2h_tracker = H2HTracker()

    half_life = float(config.get("recency_half_life_days", 365))
    learning_rate = float(config.get("recalibration_learning_rate", 0.05))
    max_delta = float(config.get("recalibration_max_delta", 0.15))

    log_rows: list[dict] = []
    stable_count = 0
    recalibrated_count = 0
    processed = 0
    total = len(matches)
    start_time = time.time()

    for i, m in enumerate(matches, start=1):
        home = m["home_team"]
        away = m["away_team"]
        kickoff_date = m["kickoff_date"]
        home_goals = m.get("actual_home_goals")
        away_goals = m.get("actual_away_goals")
        result_code = m.get("actual_result")  # "H" / "D" / "A"
        fixture_id = str(m.get("fixture_id") or m.get("id") or "")

        if home_goals is None or away_goals is None or result_code not in ("H", "D", "A"):
            continue  # rând incomplet — sărit, nu presupunem un rezultat

        # ── 1. Citim feature-urile ÎNAINTE de acest meci (doar din istoricul acestei ligi) ──
        home_off, home_def, home_form_score, home_elo = team_pre_match_rating(
            home, league, elo_tracker, form_tracker, weights, config
        )
        away_off, away_def, away_form_score, away_elo = team_pre_match_rating(
            away, league, elo_tracker, form_tracker, weights, config
        )
        h2h_modifier, h2h_meetings = h2h_tracker.get_h2h_before(home, away)

        baselines = weights.get("league_baselines", {})
        baseline = float(baselines.get(league, baselines.get("default", 1.25)))
        lw = resolve_league_weights(weights, league)

        pred_home_xg, pred_away_xg = calibrate_xg(
            home_offensive_rating=home_off,
            home_defensive_rating=home_def,
            away_offensive_rating=away_off,
            away_defensive_rating=away_def,
            home_form_score=home_form_score,
            away_form_score=away_form_score,
            baseline=baseline,
            form_weight=lw["form_weight"],
            dna_weight=lw["dna_weight"],
            home_advantage=lw["home_advantage"],
            away_penalty=lw["away_penalty"],
            defensive_cap=float(weights.get("defensive_cap", 2.5)),
            h2h_modifier=h2h_modifier,
            h2h_meetings=h2h_meetings,
            weather_penalty=0.0,   # nu inventăm date meteo istorice
        )

        # ── 2. Recalibrare (un singur pas, exact ca live — funcție NEMODIFICATĂ) ──
        recency_weight = compute_recency_weight(kickoff_date, half_life)

        weights, result = recalibrate_weights(
            weights,
            league=league,
            pred_home_xg=pred_home_xg,
            pred_away_xg=pred_away_xg,
            actual_home_goals=home_goals,
            actual_away_goals=away_goals,
            fixture_id=fixture_id,
            home_team=home,
            away_team=away,
            learning_rate=learning_rate,
            max_delta=max_delta,
            recency_weight=recency_weight,
        )
        log_rows.append(result.log_row)
        if result.status == "stable":
            stable_count += 1
        else:
            recalibrated_count += 1

        # ── 3. Actualizăm trackerele DUPĂ ce am folosit starea "înainte" ──
        elo_tracker.process_match(home, away, result_code)
        form_tracker.process_match(home, away, home_goals, away_goals, result_code)
        h2h_tracker.process_match(home, away, result_code, home_goals, away_goals)

        processed += 1
        if processed % 5000 == 0:
            elapsed = time.time() - start_time
            logger.info(
                "[Bootstrap] [%s] %d/%d meciuri (%.1f%%) — %d recalibrări, %d stabile — %.1fs",
                league, processed, total, 100 * processed / total,
                recalibrated_count, stable_count, elapsed,
            )

    elapsed = time.time() - start_time
    league_weights_entry = weights.get("league_weights", {}).get(league)
    logger.info(
        "[Bootstrap] [%s] Replay complet: %d meciuri (%d recalibrări, %d stabile) în %.1fs",
        league, processed, recalibrated_count, stable_count, elapsed,
    )
    if league_weights_entry:
        logger.info(
            "[Bootstrap] [%s] sample_count=%d form_w=%.3f dna_w=%.3f home_adv=%.3f",
            league, league_weights_entry.get("sample_count", 0),
            league_weights_entry.get("form_weight", 0),
            league_weights_entry.get("dna_weight", 0),
            league_weights_entry.get("home_advantage", 0),
        )

    return {
        "league_weights_entry": league_weights_entry,
        "log_rows": log_rows,
        "processed": processed,
        "recalibrated": recalibrated_count,
        "stable": stable_count,
    }


# ════════════════════════════════════════════════════════════════════════════
# ORCHESTRATORUL PRINCIPAL
# ════════════════════════════════════════════════════════════════════════════

def run_bootstrap(
    limit: int | None = None,
    dry_run: bool = False,
    seasons_back: int = HISTORICAL_SEASONS_BACK,
) -> dict:
    start_time = time.time()
    cutoff_date = _compute_season_cutoff_date(seasons_back)
    cutoff_iso = cutoff_date.isoformat()

    logger.info("═" * 60)
    logger.info("  FOOTBALL ORACLE — Bootstrap League Learning (per-ligă, izolat)")
    logger.info("  Dry run: %s | Limit per ligă: %s", dry_run, limit or "toate meciurile")
    logger.info("  Sezoane: ultimele %d (cutoff %s) | Ligi: %d",
                 seasons_back, cutoff_iso, len(BOOTSTRAP_LEAGUES))
    logger.info("═" * 60)

    config = DEFAULT_CONFIG

    # ── Pornim de la DEFAULT_WEIGHTS "curat" — acesta rămâne baza pentru
    #    câmpurile globale (fallback) și pentru ligile neprocesate (ex. MLS) ──
    combined_weights = copy.deepcopy(DEFAULT_WEIGHTS)
    all_log_rows: list[dict] = []

    total_processed = 0
    total_recalibrated = 0
    total_stable = 0
    leagues_with_data = 0

    for league in BOOTSTRAP_LEAGUES:
        result = _bootstrap_one_league(league, cutoff_iso, limit, config)

        if result["league_weights_entry"] is not None:
            combined_weights.setdefault("league_weights", {})[league] = result["league_weights_entry"]
            leagues_with_data += 1
        else:
            logger.info(
                "[Bootstrap] [%s] Fără meciuri procesate — păstrez fallback-ul din DEFAULT_WEIGHTS.",
                league,
            )

        all_log_rows.extend(result["log_rows"])
        total_processed += result["processed"]
        total_recalibrated += result["recalibrated"]
        total_stable += result["stable"]

    elapsed = time.time() - start_time
    logger.info("═" * 60)
    logger.info(
        "[Bootstrap] Toate ligile procesate: %d/%d cu date — %d meciuri (%d recalibrări, %d stabile) în %.1fs",
        leagues_with_data, len(BOOTSTRAP_LEAGUES), total_processed,
        total_recalibrated, total_stable, elapsed,
    )

    # ── UN SINGUR save_weights() la finalul TUTUROR replay-urilor ─────────
    if dry_run:
        logger.info("[Bootstrap] --dry-run: nu scriu în Supabase (model_weights, recalibration_log).")
    else:
        from supabase_client import save_weights, append_recalibration_log_batch

        ok = save_weights(combined_weights)
        logger.info("[Bootstrap] save_weights() → %s", "OK" if ok else "EȘUAT")

        log_ok, log_err = append_recalibration_log_batch(all_log_rows)
        logger.info(
            "[Bootstrap] recalibration_log: %d rânduri scrise, %d erori (batch-uri de 500)",
            log_ok, log_err,
        )

    # ── Rezumat per-ligă ───────────────────────────────────────────────────
    league_weights = combined_weights.get("league_weights", {})
    logger.info("[Bootstrap] Rezumat league_weights (doar ligile din BOOTSTRAP_LEAGUES):")
    for lg in BOOTSTRAP_LEAGUES:
        lw = league_weights.get(lg, {})
        logger.info(
            "   %-25s sample_count=%-5d form_w=%.3f dna_w=%.3f home_adv=%.3f",
            lg, lw.get("sample_count", 0), lw.get("form_weight", 0), lw.get("dna_weight", 0),
            lw.get("home_advantage", 0),
        )

    return {
        "processed": total_processed,
        "recalibrated": total_recalibrated,
        "stable": total_stable,
        "leagues_with_data": leagues_with_data,
        "leagues_total": len(BOOTSTRAP_LEAGUES),
        "elapsed_seconds": round(elapsed, 1),
        "cutoff_date": cutoff_iso,
        "weights": combined_weights,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Bootstrap League Learning — replay cronologic independent, per ligă"
    )
    parser.add_argument("--dry-run", action="store_true", help="Nu scrie în Supabase, doar rulează replay-ul")
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Procesează doar primele N meciuri DIN FIECARE ligă (test) — nu mai e o limită globală",
    )
    parser.add_argument(
        "--seasons-back", type=int, default=HISTORICAL_SEASONS_BACK,
        help=f"Câte sezoane în urmă (implicit {HISTORICAL_SEASONS_BACK}, aceeași definiție ca la import)",
    )
    args = parser.parse_args()

    run_bootstrap(limit=args.limit, dry_run=args.dry_run, seasons_back=args.seasons_back)
