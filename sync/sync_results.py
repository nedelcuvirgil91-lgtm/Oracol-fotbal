"""
================================================================================
FOOTBALL ORACLE v4.0 — Sync Results (zilnic automat)
================================================================================
Module: sync/sync_results.py

Descarcă rezultatele meciurilor terminate ieri din football-data.org și
actualizează match_history în Supabase cu scorurile reale.

Rulat zilnic de run_daily.py la 03:00 UTC — meciurile de ieri sunt deja
terminate și scorurile finale sunt disponibile.

Flux:
  1. Descarcă meciurile terminate ieri din football-data.org
  2. Caută în match_history meciurile fără scor (actual_result IS NULL)
     care se potrivesc cu home_team + away_team + kickoff_date
  3. Actualizează scorurile + marchează pentru backfill
  4. Calculează feature-urile ML pentru meciurile nou-completate
================================================================================
"""
from __future__ import annotations

import logging
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

root = Path(__file__).parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

import requests

from key_manager import get_key_manager

logger = logging.getLogger("FootballOracle.Sync.Results")

FD_BASE_URL = "https://api.football-data.org/v4"
# [ELIMINAT] FD_API_KEY hardcodat - migrat in key_manager.py (provider "footballdata")

# Rate limit: 10 req/min
REQUEST_INTERVAL = 6.1
_last_request_time: float = 0.0


def _rate_limited_get(url: str, params: dict | None = None) -> dict | None:
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < REQUEST_INTERVAL:
        time.sleep(REQUEST_INTERVAL - elapsed)
    try:
        resp = requests.get(
            url,
            headers=get_key_manager().get_headers("footballdata") or {},
            params=params or {},
            timeout=15,
        )
        _last_request_time = time.time()
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 429:
            logger.warning("[SyncResults] Rate limit — aștept 60s")
            time.sleep(60)
            return None
        logger.warning("[SyncResults] HTTP %d pentru %s", resp.status_code, url)
        return None
    except Exception as exc:
        logger.error("[SyncResults] Eroare fetch: %s", exc)
        _last_request_time = time.time()
        return None


# [FIX] COMPETITION_TO_LEAGUE nu mai e o copie manuală, independentă — era
# exact cauza descoperită prin audit: lipseau "EL"->Europa League și
# "WC"->World Cup 2026 pentru că această copie nu fusese actualizată quando
# FD_COMPETITIONS (mappings.py) a fost extins ulterior. Acum se derivă direct
# din sursa canonică — imposibil să se mai desincronizeze. Vezi
# architecture/ADR-001-league-providers.md.
from mappings import FD_COMPETITIONS
COMPETITION_TO_LEAGUE = {v: k for k, v in FD_COMPETITIONS.items()}

# [ADAUGAT v1.1] Fallback minim daca model_config nu exista inca in Supabase
# / config.json — identic ca valori cu DEFAULT_CONFIG din oracle_engine.py,
# doar cele 3 chei de care are nevoie recalibrarea (nu duplica intreg
# DEFAULT_CONFIG, ca sa nu existe doua liste complete de config care se pot
# dezalinia in timp — ambele citesc oricum aceeasi sursa reala, model_config).
_RECAL_CONFIG_DEFAULTS = {
    "recalibration_learning_rate": 0.05,
    "recalibration_max_delta":     0.15,
    "recency_half_life_days":      365,
}


def _recalibrate_for_result(match_row: dict, r: dict) -> None:
    """
    [ADAUGAT v1.1] Recalibreaza automat league_weights pentru meciul
    tocmai completat cu rezultatul real — fara nicio interventie manuala,
    fara Portfolio. Foloseste EXACT aceeasi functie pura (recalibrate_weights,
    din recalibration.py) ca fluxul live din oracle_engine.py — o singura
    sursa de adevar pentru algoritmul de invatare.

    match_row: randul din match_history gasit de update_results_in_supabase()
               (contine home_xg_pred / away_xg_pred — predictia salvata la
               momentul evaluate_match()).
    r:         rezultatul real descarcat de fetch_yesterday_results()
               (contine home_goals / away_goals / league / kickoff_date).

    Nu arunca exceptii in afara — un esec de recalibrare (ex. Supabase
    indisponibil temporar) nu trebuie sa opreasca restul jobului zilnic de
    sincronizare a rezultatelor.
    """
    pred_h = match_row.get("home_xg_pred")
    pred_a = match_row.get("away_xg_pred")
    if pred_h is None or pred_a is None:
        # Meciul nu a fost niciodata predictionat live (nu exista xG salvat) —
        # nimic de recalibrat pentru el.
        logger.debug(
            "[SyncResults] Fara home_xg_pred/away_xg_pred pentru %s vs %s — sar peste recalibrare.",
            r.get("home_team"), r.get("away_team"),
        )
        return

    try:
        from supabase_client import load_weights, save_weights, load_config, append_recalibration_log
        from recalibration import recalibrate_weights, compute_recency_weight

        cfg = load_config(_RECAL_CONFIG_DEFAULTS)
        lr        = float(cfg.get("recalibration_learning_rate", 0.05))
        max_d     = float(cfg.get("recalibration_max_delta",     0.15))
        half_life = float(cfg.get("recency_half_life_days",      365))

        weights = load_weights({"league_weights": {}})
        recency = compute_recency_weight(r.get("kickoff_date"), half_life)

        new_weights, result = recalibrate_weights(
            weights,
            league=r["league"], pred_home_xg=float(pred_h), pred_away_xg=float(pred_a),
            actual_home_goals=r["home_goals"], actual_away_goals=r["away_goals"],
            fixture_id=str(match_row.get("fixture_id", "")),
            home_team=r.get("home_team", ""), away_team=r.get("away_team", ""),
            learning_rate=lr, max_delta=max_d, recency_weight=recency,
        )

        if not save_weights(new_weights):
            logger.warning(
                "[SyncResults] save_weights a esuat pentru %s vs %s — recalibrarea NU a fost persistata.",
                r.get("home_team"), r.get("away_team"),
            )
            return

        if result.log_row is not None:
            append_recalibration_log(result.log_row)

        logger.info(
            "[SyncResults] League Learning: %s vs %s [%s] → %s (sample #%d, eroare=%.3f, recency=%.3f)",
            r.get("home_team"), r.get("away_team"), r["league"],
            result.status, new_weights["league_weights"][r["league"]]["sample_count"],
            result.combined_error, recency,
        )
    except Exception as exc:
        logger.error(
            "[SyncResults] Recalibrare automata esuata pentru %s vs %s: %s",
            r.get("home_team"), r.get("away_team"), exc,
        )


def fetch_yesterday_results(target_date: str | None = None, days_back: int = 7) -> list[dict]:
    """
    Descarcă rezultatele meciurilor terminate într-o FEREASTRĂ de zile, nu
    doar o singură zi fixă.

    [REPARAT] Inainte verifica STRICT "ieri" (o singura zi) - daca job-ul
    zilnic esua sau ligile lipseau din COMPETITION_TO_LEAGUE (bug deja
    reparat separat), acele zile erau pierdute definitiv, fara nicio
    recuperare posibila. Confirmat cu date reale: 16 meciuri World Cup 2026
    ramasesera blocate fara actual_result din exact acest motiv.

    Acum verifică ultimele `days_back` zile (implicit 7) la fiecare rulare -
    sigur si idempotent, fiindca update_results_in_supabase() ignora deja
    meciurile care au deja actual_result (.is_("actual_result","null")) -
    re-verificarea zilelor deja rezolvate nu duplica nimic, doar recupereaza
    ce a fost ratat.

    target_date: daca dat explicit, verifica DOAR acea zi (comportament
    vechi, pastrat pt teste/debugging punctual). Altfel, fereastra glisanta.
    """
    if target_date is not None:
        date_from = date_to = target_date
    else:
        today = datetime.now(timezone.utc).date()
        date_to = (today - timedelta(days=1)).isoformat()
        date_from = (today - timedelta(days=days_back)).isoformat()

    logger.info("[SyncResults] Descarcă rezultate din intervalul %s → %s", date_from, date_to)

    data = _rate_limited_get(
        f"{FD_BASE_URL}/matches",
        params={
            "dateFrom": date_from,
            "dateTo":   date_to,
            "status":   "FINISHED",
        }
    )

    if not data:
        return []

    results = []
    for match in data.get("matches", []):
        try:
            comp_code = (match.get("competition") or {}).get("tla", "")
            league    = COMPETITION_TO_LEAGUE.get(comp_code)
            if not league:
                continue

            home_team  = (match.get("homeTeam") or {}).get("name", "")
            away_team  = (match.get("awayTeam") or {}).get("name", "")
            score      = match.get("score", {})
            ft         = score.get("fullTime", {})
            home_goals = ft.get("home")
            away_goals = ft.get("away")

            if not home_team or not away_team:
                continue
            if home_goals is None or away_goals is None:
                continue

            home_goals = int(home_goals)
            away_goals = int(away_goals)

            actual_result = (
                "H" if home_goals > away_goals
                else "A" if home_goals < away_goals
                else "D"
            )

            utc_date    = match.get("utcDate", "")
            kickoff_date = utc_date[:10] if utc_date else date_to

            results.append({
                "fd_id":           match.get("id"),
                "home_team":       home_team,
                "away_team":       away_team,
                "league":          league,
                "kickoff_date":    kickoff_date,
                "home_goals":      home_goals,
                "away_goals":      away_goals,
                "actual_result":   actual_result,
            })
        except Exception as exc:
            logger.debug("[SyncResults] Parse error: %s", exc)
            continue

    logger.info("[SyncResults] %d meciuri terminate găsite în intervalul %s → %s",
                len(results), date_from, date_to)
    return results


def update_results_in_supabase(results: list[dict]) -> tuple[int, int]:
    """
    Actualizează scorurile în match_history pentru meciurile terminate.
    Caută potriviri după home_team + away_team + kickoff_date.
    Returnează (updated_count, not_found_count).
    """
    from supabase_client import get_client
    client = get_client()
    if client is None:
        return 0, len(results)

    updated    = 0
    not_found  = 0

    for r in results:
        try:
            # Căutăm meciul în match_history fără scor
            res = (
                client.table("match_history")
                .select("id,fixture_id,home_xg_pred,away_xg_pred")
                .eq("home_team",    r["home_team"])
                .eq("away_team",    r["away_team"])
                .eq("league",       r["league"])
                .eq("kickoff_date", r["kickoff_date"])
                .is_("actual_result", "null")
                .execute()
            )

            rows = res.data or []

            if not rows:
                # Încearcă și cu fixture_id fd_
                fd_fixture_id = f"fd_{r['fd_id']}" if r.get("fd_id") else None
                if fd_fixture_id:
                    res2 = (
                        client.table("match_history")
                        .select("id,fixture_id,home_xg_pred,away_xg_pred")
                        .eq("fixture_id", fd_fixture_id)
                        .is_("actual_result", "null")
                        .execute()
                    )
                    rows = res2.data or []

            if not rows:
                logger.debug(
                    "[SyncResults] Nu am găsit: %s vs %s (%s)",
                    r["home_team"], r["away_team"], r["kickoff_date"]
                )
                not_found += 1
                continue

            # [FIX v1.1] Pot exista MAI MULTE randuri pentru acelasi meci real
            # (predictionat separat de surse diferite — ex. ESPN si Odds API,
            # fiecare cu propriul fixture_id). Scriem rezultatul real pe TOATE
            # (niciun rand nu ramane orfan, cu actual_result null la nesfarsit),
            # dar recalibram League Learning O SINGURA DATA, dintr-un singur
            # rand ales determinist (cel cu id-ul cel mai mic — prima predictie
            # facuta pentru acel meci) — ca sa nu invatam de doua ori din
            # acelasi rezultat real.
            rows_sorted   = sorted(rows, key=lambda x: x["id"])
            canonical_row = rows_sorted[0]

            if len(rows_sorted) > 1:
                logger.info(
                    "[SyncResults] %d predictii duplicate gasite pentru %s vs %s (%s) — "
                    "actualizez scorul pe toate, recalibrez o singura data din id=%s.",
                    len(rows_sorted), r["home_team"], r["away_team"], r["kickoff_date"],
                    canonical_row["id"],
                )

            for row in rows_sorted:
                client.table("match_history").update({
                    "actual_home_goals": r["home_goals"],
                    "actual_away_goals": r["away_goals"],
                    "actual_result":     r["actual_result"],
                    "backfill_done":     False,  # va fi procesat de backfill
                }).eq("id", row["id"]).execute()

            updated += 1
            logger.debug(
                "[SyncResults] Actualizat: %s vs %s → %d-%d (%s)",
                r["home_team"], r["away_team"],
                r["home_goals"], r["away_goals"], r["actual_result"]
            )

            # [ADAUGAT v1.1] Recalibrare AUTOMATA — League Learning nu mai
            # depinde de Portfolio sau de vreo confirmare manuala. Daca acest
            # meci a fost predictionat live (home_xg_pred/away_xg_pred exista),
            # recalibram ponderile chiar aici, fara nicio interventie umana.
            # Doar din randul canonic — vezi nota de mai sus despre duplicate.
            _recalibrate_for_result(canonical_row, r)

        except Exception as exc:
            logger.error("[SyncResults] Update failed pentru %s vs %s: %s",
                         r.get("home_team"), r.get("away_team"), exc)
            not_found += 1

    logger.info("[SyncResults] Actualizate: %d | Negăsite: %d", updated, not_found)
    return updated, not_found


def sync_yesterday_results() -> dict:
    """
    Funcția principală — descarcă și salvează rezultatele din ultimele zile
    (fereastră glisantă, implicit 7 zile — vezi fetch_yesterday_results()).
    Numele funcției a rămas neschimbat (run_daily.py o importă exact așa),
    deși acum acoperă mai mult decât "ieri" — vezi ADR-004.
    Apelată din run_daily.py.
    """
    results = fetch_yesterday_results()
    if not results:
        return {"status": "ok", "updated": 0, "not_found": 0, "message": "Niciun meci ieri"}

    updated, not_found = update_results_in_supabase(results)

    # Dacă s-au actualizat meciuri, rulăm backfill pentru ele
    if updated > 0:
        logger.info("[SyncResults] Rulăm backfill pentru %d meciuri noi...", updated)
        try:
            from sync.backfill_features import run_backfill
            # Backfill doar pentru meciurile recent actualizate (backfill_done=False)
            run_backfill(batch_size=50)
        except Exception as exc:
            logger.warning("[SyncResults] Backfill după sync eșuat: %s", exc)

    return {
        "status":    "ok",
        "updated":   updated,
        "not_found": not_found,
    }
