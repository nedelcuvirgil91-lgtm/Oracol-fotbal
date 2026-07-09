"""
================================================================================
FOOTBALL ORACLE — Bootstrap League Learning
================================================================================
Module: sync/bootstrap_league_learning.py

Reface `model_weights` de la zero, printr-un replay cronologic peste TOT
istoricul din match_history — ca și cum sistemul ar fi rulat live încă din
primul meci din dataset.

IMPORTANT — acest script e complet AUTONOM față de backfill_features.py:
  - NU citește coloanele-cache (home_elo, home_form_score, home_offensive_rating,
    h2h_modifier, backfill_done, ...) din match_history. Acelea sunt doar un
    cache pentru aplicație, nu sursa de adevăr pentru bootstrap.
  - Reconstruiește singur ELO / formă / H2H din (home_team, away_team, league,
    kickoff_date, actual_home_goals, actual_away_goals, actual_result) — adică
    exact coloanele "brute" ale unui rezultat real, nimic altceva.
  - De aceea NU depinde de câte meciuri are backfill_done=true: învață din
    toate cele ~50.000 de meciuri cu rezultat real, nu doar din subsetul deja
    cache-uit.

Ce NU face acest script (intenționat):
  - NU scrie niciodată în match_history (nu marchează backfill_done, nu
    modifică nicio coloană de-acolo). Singurele scrieri sunt:
      1. model_weights — UN SINGUR save_weights() la finalul întregului replay
      2. recalibration_log — în batch-uri, nu un request per meci
  - NU pornește de la model_weights curent din Supabase (care reflectă doar
    cele ~16 predicții live existente). Pornește de la DEFAULT_WEIGHTS —
    acele ~16 predicții live sunt "înghițite" natural în replay, pentru că
    meciurile lor există și ele în match_history.
  - NU inventează statistici lipsă (shots, shots_on_target, possession —
    absente 100% din dataset-ul Kaggle). Folosește EXACT aceleași fallback-uri
    ca motorul live atunci când aceste statistici lipsesc:
      sot = avg_goals_for * 0.45   (proxy, identic cu _build_profile)
      pos = 50.0                    (neutru, identic cu _build_profile)
    și, dacă o echipă nu are încă niciun meci în istoric (primul ei meci din
    dataset), folosește cascada live Level 5 "ELO only" (fără formă, fără
    blend din statistici) — nu Level 6 "neutral defaults", pentru că ELO-ul
    (via ELOTracker) există întotdeauna, chiar dacă valoarea inițială e 1500.

Matematica (form score, H2H modifier, transformări ELO→multiplicator,
calibrare xG, model Poisson, blend de ponderi per-ligă, rating ofensiv/defensiv)
vine EXCLUSIV din feature_engine.py — exact aceeași matematică pe care o
folosește motorul live. Reconstrucția stării (ELO/formă/H2H de-a lungul
timpului) vine din clasele deja existente în sync/backfill_features.py
(ELOTracker, FormTracker, H2HTracker) — nu sunt reimplementate aici.

Rulare:
  python sync/bootstrap_league_learning.py                 # rulare completă
  python sync/bootstrap_league_learning.py --dry-run        # fără scriere în Supabase
  python sync/bootstrap_league_learning.py --limit 5000     # test pe primele N meciuri
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
    compute_form_score,
    calibrate_xg,
    poisson_model,               # noqa: F401  (importat pentru simetrie/uz viitor — vezi nota din run())
    elo_to_offensive_multiplier,
    elo_to_defensive_multiplier,
    resolve_league_weights,
    compute_team_offdef_rating,
)
from recalibration import recalibrate_weights, compute_recency_weight
from sync.backfill_features import ELOTracker, FormTracker, H2HTracker, fetch_all_matches
from oracle_engine import DEFAULT_CONFIG, DEFAULT_WEIGHTS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(levelname)s]  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("FootballOracle.Bootstrap")


def get_client():
    from supabase_client import get_client as _gc
    return _gc()


# ════════════════════════════════════════════════════════════════════════════
# NORMALIZARE + DEDUPLICARE ÎN MEMORIE
# ════════════════════════════════════════════════════════════════════════════

def normalize_and_dedupe(raw_matches: list[dict]) -> list[dict]:
    """
    Normalizează home_team/away_team/league și elimină duplicatele — același
    meci real apărut de mai multe ori în match_history (de ex. o dată din
    sincronizarea live "fd_...", o dată din importul bulk "kaggle_...").

    `raw_matches` trebuie să fie deja sortat cronologic (kickoff_date, id
    ascendent) — fetch_all_matches() face deja asta. Cheia de deduplicare e
    (home_normalizat, away_normalizat, league_normalizat, kickoff_date); se
    păstrează PRIMA apariție întâlnită (adică cea cu id-ul cel mai mic —
    de obicei sursa live-sincronizată, inserată înaintea bulk-import-ului).
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

    logger.info(
        "[Bootstrap] Normalizare + deduplicare: %d meciuri unice (%d duplicate eliminate)",
        len(out), duplicates,
    )
    return out


# ════════════════════════════════════════════════════════════════════════════
# FEATURE-URI PRE-MECI (identic cu cascada live, fără statistici lipsă)
# ════════════════════════════════════════════════════════════════════════════

def _team_pre_match_rating(
    team: str,
    league: str,
    elo_tracker: ELOTracker,
    form_tracker: FormTracker,
    weights: dict,
    config: dict,
) -> tuple[float, float, float, int]:
    """
    Calculează (offensive_rating, defensive_rating, form_score, elo_before)
    pentru o echipă, ÎNAINTE de meciul curent — folosind exact aceeași
    matematică din feature_engine.py ca și motorul live.

    Fallback identic cu cascada _build_profile() din oracle_engine.py:
      - dacă echipa are istoric de formă  → ratinguri din stats (gf/ga reale,
        sot = gf*0.45, pos = 50.0 — singurele statistici disponibile în
        dataset-ul istoric), blendate cu ELO (Level "stats + elo blend").
      - dacă echipa NU are încă niciun meci în istoric → Level 5 "ELO only"
        (fără formă, fără blend din statistici — ELO-ul există mereu, chiar
        dacă e valoarea inițială 1500).
    """
    elo_before = round(elo_tracker.get_elo(team))
    elo_off = elo_to_offensive_multiplier(
        elo_before, config["elo_reference"], config["elo_sigmoid_scale"]
    )
    elo_def = elo_to_defensive_multiplier(
        elo_before, config["elo_reference"], config["elo_sigmoid_scale"]
    )

    form = form_tracker.get_form(team)  # [(result, gf, ga), ...] înainte de acest meci
    lw = resolve_league_weights(weights, league)
    baselines = weights.get("league_baselines", {})
    baseline = float(baselines.get(league, baselines.get("default", 1.25)))

    if form:
        avg_gf = sum(gf for _, gf, _ in form) / len(form)
        avg_ga = sum(ga for _, _, ga in form) / len(form)
        avg_sot = avg_gf * 0.45   # fallback identic cu live: shots_on_goal lipsă
        avg_pos = 50.0            # fallback identic cu live: possession lipsă

        off_rating, def_rating = compute_team_offdef_rating(
            avg_goals_for=avg_gf,
            avg_goals_against=avg_ga,
            avg_shots_on_target=avg_sot,
            avg_possession=avg_pos,
            goals_weight=lw["goals_weight"],
            shots_ot_weight=lw["shots_ot_weight"],
            possession_weight=lw["possession_weight"],
            offensive_cap=float(weights.get("offensive_cap", 3.5)),
            defensive_cap=float(weights.get("defensive_cap", 2.5)),
            elo_offensive_multiplier=elo_off,
            elo_defensive_multiplier=elo_def,
            elo_blend_weight=float(config.get("elo_blend_weight", 0.35)),
        )
        form_score = compute_form_score([r for r, _, _ in form])
    else:
        # Level 5 "ELO only" — identic cu _build_profile() când nu există stats
        off_rating = round(elo_off * baseline, 4)
        def_rating = round(elo_def, 4)
        form_score = 0.0

    return off_rating, def_rating, form_score, elo_before


# ════════════════════════════════════════════════════════════════════════════
# ORCHESTRATORUL PRINCIPAL
# ════════════════════════════════════════════════════════════════════════════

def run_bootstrap(limit: int | None = None, dry_run: bool = False) -> dict:
    start_time = time.time()
    logger.info("═" * 60)
    logger.info("  FOOTBALL ORACLE — Bootstrap League Learning")
    logger.info("  Dry run: %s | Limit: %s", dry_run, limit or "toate meciurile")
    logger.info("═" * 60)

    raw_matches = fetch_all_matches()  # deja sortate cronologic (kickoff_date, id)
    if not raw_matches:
        logger.error("[Bootstrap] Niciun meci găsit în match_history. Opresc.")
        return {"processed": 0, "error": "no_matches"}

    matches = normalize_and_dedupe(raw_matches)
    if limit:
        matches = matches[:limit]

    # ── Stare inițială: pornim de la DEFAULT_WEIGHTS, NU de la model_weights curent ──
    weights = copy.deepcopy(DEFAULT_WEIGHTS)
    config = DEFAULT_CONFIG

    elo_tracker = ELOTracker()
    form_tracker = FormTracker()
    h2h_tracker = H2HTracker()

    log_rows: list[dict] = []
    stable_count = 0
    recalibrated_count = 0
    processed = 0

    half_life = float(config.get("recency_half_life_days", 365))
    learning_rate = float(config.get("recalibration_learning_rate", 0.05))
    max_delta = float(config.get("recalibration_max_delta", 0.15))

    total = len(matches)
    for i, m in enumerate(matches, start=1):
        home = m["home_team"]
        away = m["away_team"]
        league = m["league"]
        kickoff_date = m["kickoff_date"]
        home_goals = m.get("actual_home_goals")
        away_goals = m.get("actual_away_goals")
        result_code = m.get("actual_result")  # "H" / "D" / "A"
        fixture_id = str(m.get("fixture_id") or m.get("id") or "")

        if home_goals is None or away_goals is None or result_code not in ("H", "D", "A"):
            continue  # rând incomplet — sărit, nu presupunem un rezultat

        # ── 1. Citim feature-urile ÎNAINTE de acest meci ──────────────────
        home_off, home_def, home_form_score, home_elo = _team_pre_match_rating(
            home, league, elo_tracker, form_tracker, weights, config
        )
        away_off, away_def, away_form_score, away_elo = _team_pre_match_rating(
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

        # ── 2. Recalibrare (un singur pas, exact ca live) ─────────────────
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
                "[Bootstrap] %d/%d meciuri (%.1f%%) — %d recalibrări, %d stabile — %.1fs",
                processed, total, 100 * processed / total, recalibrated_count, stable_count, elapsed,
            )

    elapsed = time.time() - start_time
    logger.info("═" * 60)
    logger.info(
        "[Bootstrap] Replay complet: %d meciuri procesate (%d recalibrări, %d stabile) în %.1fs",
        processed, recalibrated_count, stable_count, elapsed,
    )

    # ── 4. UN SINGUR save_weights() la final ──────────────────────────────
    if dry_run:
        logger.info("[Bootstrap] --dry-run: nu scriu în Supabase (model_weights, recalibration_log).")
    else:
        from supabase_client import save_weights, append_recalibration_log_batch

        ok = save_weights(weights)
        logger.info("[Bootstrap] save_weights() → %s", "OK" if ok else "EȘUAT")

        log_ok, log_err = append_recalibration_log_batch(log_rows)
        logger.info(
            "[Bootstrap] recalibration_log: %d rânduri scrise, %d erori (batch-uri de 500)",
            log_ok, log_err,
        )

    # ── Rezumat per-ligă ───────────────────────────────────────────────────
    league_weights = weights.get("league_weights", {})
    logger.info("[Bootstrap] Ligi învățate: %d", len(league_weights))
    for lg, lw in sorted(league_weights.items(), key=lambda kv: -int(kv[1].get("sample_count", 0)))[:15]:
        logger.info(
            "   %-25s sample_count=%-5d form_w=%.3f dna_w=%.3f home_adv=%.3f",
            lg, lw.get("sample_count", 0), lw.get("form_weight", 0), lw.get("dna_weight", 0),
            lw.get("home_advantage", 0),
        )

    return {
        "processed": processed,
        "recalibrated": recalibrated_count,
        "stable": stable_count,
        "leagues": len(league_weights),
        "elapsed_seconds": round(elapsed, 1),
        "weights": weights,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bootstrap League Learning — replay cronologic complet")
    parser.add_argument("--dry-run", action="store_true", help="Nu scrie în Supabase, doar rulează replay-ul")
    parser.add_argument("--limit", type=int, default=None, help="Procesează doar primele N meciuri (test)")
    args = parser.parse_args()

    run_bootstrap(limit=args.limit, dry_run=args.dry_run)
