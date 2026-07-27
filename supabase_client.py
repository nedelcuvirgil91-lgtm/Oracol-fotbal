"""
================================================================================
FOOTBALL ORACLE — Supabase Client Layer
================================================================================
Module: supabase_client.py

Înlocuiește persistența pe fișiere locale (portfolio.csv, weights.json,
recalibration_log.csv) cu Supabase Postgres, ca să supraviețuiască
redeploy-urilor pe Streamlit Community Cloud (care resetează filesystem-ul
efemer la fiecare push).

Citește credențialele din st.secrets (Streamlit Cloud → Settings → Secrets)
sau din variabile de mediu ca fallback pentru rulare locală.

Necesită în requirements.txt:  supabase>=2.0.0
================================================================================
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from mappings import normalize_team_name

logger = logging.getLogger("FootballOracle.Supabase")

_client = None
_client_error: str | None = None


def _get_credentials() -> tuple[str | None, str | None]:
    """Citește URL + secret key din st.secrets (Streamlit Cloud) sau env vars."""
    url = None
    key = None
    try:
        import streamlit as st
        url = st.secrets.get("SUPABASE_URL")
        key = st.secrets.get("SUPABASE_SECRET_KEY")
    except Exception:
        pass
    url = url or os.environ.get("SUPABASE_URL")
    key = key or os.environ.get("SUPABASE_SECRET_KEY")
    return url, key


def get_client():
    """Returnează un client Supabase singleton, sau None dacă lipsesc credențialele."""
    global _client, _client_error
    if _client is not None:
        return _client
    if _client_error is not None:
        return None

    url, key = _get_credentials()
    if not url or not key:
        _client_error = "SUPABASE_URL / SUPABASE_SECRET_KEY lipsesc din st.secrets."
        logger.warning("[Supabase] %s", _client_error)
        return None

    try:
        from supabase import create_client
        _client = create_client(url, key)
        logger.info("[Supabase] Client conectat la %s", url)
        return _client
    except Exception as exc:
        _client_error = f"Conectare eșuată: {exc}"
        logger.error("[Supabase] %s", _client_error)
        return None


def is_available() -> bool:
    return get_client() is not None


def last_error() -> str | None:
    return _client_error


# ════════════════════════════════════════════════════════════════════════════
# WEIGHTS / CONFIG  (tabele singleton, id=1)
# ════════════════════════════════════════════════════════════════════════════

def load_weights(default: dict) -> dict:
    client = get_client()
    if client is None:
        return dict(default)
    try:
        res = client.table("model_weights").select("data").eq("id", 1).single().execute()
        data = (res.data or {}).get("data") or {}
        return data if data else dict(default)
    except Exception as exc:
        logger.warning("[Supabase] load_weights failed: %s", exc)
        return dict(default)


def save_weights(data: dict) -> bool:
    client = get_client()
    if client is None:
        return False
    try:
        client.table("model_weights").update({
            "data": data, "updated_at": datetime.now(timezone.utc).isoformat()
        }).eq("id", 1).execute()
        return True
    except Exception as exc:
        logger.error("[Supabase] save_weights failed: %s", exc)
        return False


def load_config(default: dict) -> dict:
    client = get_client()
    if client is None:
        return dict(default)
    try:
        res = client.table("model_config").select("data").eq("id", 1).single().execute()
        data = (res.data or {}).get("data") or {}
        return data if data else dict(default)
    except Exception as exc:
        logger.warning("[Supabase] load_config failed: %s", exc)
        return dict(default)


def save_config(data: dict) -> bool:
    client = get_client()
    if client is None:
        return False
    try:
        client.table("model_config").update({
            "data": data, "updated_at": datetime.now(timezone.utc).isoformat()
        }).eq("id", 1).execute()
        return True
    except Exception as exc:
        logger.error("[Supabase] save_config failed: %s", exc)
        return False


# ════════════════════════════════════════════════════════════════════════════
# PORTFOLIO
# ════════════════════════════════════════════════════════════════════════════

def log_bet(fixture_id: str, match_name: str, market: str, selection: str,
            odds: float, stake: float, result: str = "") -> dict | None:
    client = get_client()
    result = (result or "").upper().strip()
    pnl = round(stake * (odds - 1), 2) if result == "W" else (-round(stake, 2) if result == "L" else 0.0)
    row = {
        "fixture_id": str(fixture_id), "match_name": match_name, "market": market,
        "selection": selection, "odds": odds, "stake": stake,
        "result": result or "PENDING", "pnl": pnl,
    }
    if client is None:
        return row
    try:
        client.table("portfolio").insert(row).execute()
        return row
    except Exception as exc:
        logger.error("[Supabase] log_bet failed: %s", exc)
        return row


def update_bet_result(bet_id: int, result: str, pnl: float) -> bool:
    client = get_client()
    if client is None:
        return False
    try:
        client.table("portfolio").update({"result": result, "pnl": pnl}).eq("id", bet_id).execute()
        return True
    except Exception as exc:
        logger.error("[Supabase] update_bet_result failed: %s", exc)
        return False


def get_portfolio() -> list[dict]:
    client = get_client()
    if client is None:
        return []
    try:
        res = client.table("portfolio").select("*").order("id", desc=True).execute()
        return res.data or []
    except Exception as exc:
        logger.error("[Supabase] get_portfolio failed: %s", exc)
        return []


# ════════════════════════════════════════════════════════════════════════════
# RECALIBRATION LOG
# ════════════════════════════════════════════════════════════════════════════

def append_recalibration_log(row: dict) -> bool:
    client = get_client()
    if client is None:
        return False
    try:
        client.table("recalibration_log").insert({
            "fixture_id":     row.get("fixture_id"),
            "league":         row.get("league"),
            "sample_count":   row.get("sample_count"),
            "home_team_info": row.get("home"),
            "away_team_info": row.get("away"),
            "actual_score":   row.get("actual"),
            "combined_error": row.get("combined_error"),
            "new_form_w":     row.get("new_form_w"),
            "new_dna_w":      row.get("new_dna_w"),
            "home_advantage": row.get("home_advantage"),
            "reason":         row.get("reason"),
        }).execute()
        return True
    except Exception as exc:
        logger.error("[Supabase] append_recalibration_log failed: %s", exc)
        return False


def append_recalibration_log_batch(rows: list[dict]) -> tuple[int, int]:
    """
    Insereaza in Supabase mai multe randuri de recalibration_log intr-un
    singur request (sau in cateva request-uri, daca `rows` e foarte mare).
    Folosit de sync/bootstrap_league_learning.py, care ruleaza recalibrare
    peste zeci de mii de meciuri si nu isi permite un round-trip HTTP per meci.

    Returneaza (nr_randuri_inserate, nr_erori). Trimite in chunk-uri de 500
    ca sa ramana sub limitele obisnuite de payload ale PostgREST.
    """
    client = get_client()
    if client is None:
        return 0, 0

    mapped = [{
        "fixture_id":     r.get("fixture_id"),
        "league":         r.get("league"),
        "sample_count":   r.get("sample_count"),
        "home_team_info": r.get("home"),
        "away_team_info": r.get("away"),
        "actual_score":   r.get("actual"),
        "combined_error": r.get("combined_error"),
        "new_form_w":     r.get("new_form_w"),
        "new_dna_w":      r.get("new_dna_w"),
        "home_advantage": r.get("home_advantage"),
        "reason":         r.get("reason"),
    } for r in rows]

    ok, errors = 0, 0
    chunk_size = 500
    for i in range(0, len(mapped), chunk_size):
        chunk = mapped[i:i + chunk_size]
        try:
            client.table("recalibration_log").insert(chunk).execute()
            ok += len(chunk)
        except Exception as exc:
            logger.error("[Supabase] append_recalibration_log_batch chunk %d failed: %s", i, exc)
            errors += len(chunk)
    return ok, errors


# ════════════════════════════════════════════════════════════════════════════
# MATCH HISTORY (dataset ML)
# ════════════════════════════════════════════════════════════════════════════

def upsert_match_history(row: dict) -> bool:
    """Inserează sau actualizează un meci în dataset-ul de antrenare ML.

    [MIGRAT — ID-025-03 Writer Migration] Al doilea funnel de scriere in
    match_history (celalalt e database/queries.py, folosit de sync/). Ruteaza
    prin RPC-ul canonic (`upsert_match_canonical`): lookup pe cheia naturala
    normalizata + decizie UPDATE/INSERT sub pg_advisory_xact_lock, in loc de
    upsert direct pe fixture_id. Un meci deja existent devine UPDATE
    non-destructiv pe randul canonic — zero duplicate noi (mecanismul D, ADR-025).
    Normalizarea home/away se face aici, in Python (nu in SQL), inainte de apel
    (P3.5 Team Identity Audit + ID-025-03). Apelantii (oracle_engine.py) trebuie
    sa furnizeze cheia naturala completa (home_team/away_team/kickoff_date).
    """
    client = get_client()
    if client is None:
        return False
    try:
        payload = dict(row)
        if payload.get("home_team"):
            payload["home_team"] = normalize_team_name(payload["home_team"])
        if payload.get("away_team"):
            payload["away_team"] = normalize_team_name(payload["away_team"])
        payload = {k: v for k, v in payload.items() if v is not None}
        res = client.rpc("upsert_match_canonical", {"p_payload": payload}).execute()
        data = getattr(res, "data", None) or {}
        action = data.get("action") if isinstance(data, dict) else None
        if action == "hard_conflict":
            logger.warning(
                "[Supabase] upsert_match_history HARD CONFLICT (nescris): %s vs %s @ %s",
                payload.get("home_team"), payload.get("away_team"), payload.get("kickoff_date"),
            )
            return False
        return action in ("insert", "update")
    except Exception as exc:
        logger.error("[Supabase] upsert_match_history failed: %s", exc)
        return False


def get_training_data(only_with_results: bool = True) -> list[dict]:
    """
    Returnează TOATE meciurile din istoric care au rezultat real cunoscut.

    [REPARAT] Inainte facea un singur select("*") fara paginare - Supabase/
    PostgREST limiteaza implicit orice astfel de cerere la 1000 randuri
    (confirmat oficial: https://supabase.com/docs, "Max Rows" - implicit
    1000, configurabil doar din Dashboard). Asta insemna ca modelul ML se
    antrena mereu pe doar 1000 din cele 50000+ meciuri eligibile reale -
    gasit prin audit direct (count real vs samples_used din ml_model_status).

    Acum pagineaza explicit cu .range(), in bucla, pana cand o pagina
    intoarce mai putin decat page_size (semn ca s-a ajuns la ultima pagina).
    """
    client = get_client()
    if client is None:
        return []
    page_size = 1000
    all_rows: list[dict] = []
    start = 0
    try:
        while True:
            q = client.table("match_history").select("*")
            if only_with_results:
                q = q.not_.is_("actual_result", "null")
            q = q.order("fixture_id").range(start, start + page_size - 1)
            res = q.execute()
            page = res.data or []
            all_rows.extend(page)
            if len(page) < page_size:
                break
            start += page_size
        return all_rows
    except Exception as exc:
        logger.error("[Supabase] get_training_data failed (după %d rânduri): %s", len(all_rows), exc)
        return all_rows


def get_team_recent_results(team: str, league: str, last_n: int = 5,
                             lookback_days: int = 365) -> list[dict]:
    """
    ADR-035 / D1 — sursa canonică pentru forma și golurile echipei în
    _build_profile(): ultimele `last_n` meciuri TERMINATE ale echipei
    `team` în liga `league`, din match_history, limitate la ultimele
    `lookback_days` zile (forma veche de ani nu e „formă").

    Zero scurgere temporală: doar meciuri cu actual_result populat —
    pentru un meci viitor de prezis, toate rândurile întoarse sunt
    garantat din trecut. O echipă fără istoric suficient primește listă
    goală/scurtă — apelantul decide pragul minim și cade pe cascada de
    provideri existentă, nu se aproximează aici (Regula #8).
    """
    client = get_client()
    if client is None:
        return []
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).date().isoformat()
        res = (
            client.table("match_history")
            .select("home_team,away_team,actual_home_goals,actual_away_goals,"
                    "actual_result,kickoff_date")
            .eq("league", league)
            .or_(f"home_team.eq.{team},away_team.eq.{team}")
            .not_.is_("actual_result", "null")
            .gte("kickoff_date", cutoff)
            .order("kickoff_date", desc=True)
            .limit(last_n)
            .execute()
        )
        return res.data or []
    except Exception as exc:
        logger.warning("[Supabase] get_team_recent_results failed pentru %s/%s: %s", team, league, exc)
        return []


def get_team_recent_shots(team: str, league: str, last_n: int = 5) -> list[dict]:
    """
    Ultimele `last_n` meciuri TERMINATE ale echipei `team` în liga `league`,
    cu date reale de șuturi (home_shots/away_shots/*_on_target populate) —
    sursă pentru avg_shots_ot real în TeamProfile (oracle_engine._build_profile),
    înlocuind proxy-ul sintetic (avg_gf*0.45) cu date reale, unde există.

    Zero scurgere temporală: doar meciuri cu actual_result populat (deci deja
    terminate) — pentru un meci viitor de prezis, toate rândurile întoarse
    sunt garantat din trecut. O echipă fără istoric relevant primește listă
    goală — apelantul păstrează fallback-ul existent, nu se aproximează aici.
    """
    client = get_client()
    if client is None:
        return []
    try:
        res = (
            client.table("match_history")
            .select("home_team,away_team,home_shots,away_shots,"
                    "home_shots_on_target,away_shots_on_target,kickoff_date")
            .eq("league", league)
            .or_(f"home_team.eq.{team},away_team.eq.{team}")
            .not_.is_("actual_result", "null")
            .not_.is_("home_shots", "null")
            .order("kickoff_date", desc=True)
            .limit(last_n)
            .execute()
        )
        return res.data or []
    except Exception as exc:
        logger.warning("[Supabase] get_team_recent_shots failed pentru %s/%s: %s", team, league, exc)
        return []


def get_team_recent_match_events(team: str, league: str, last_n: int = 5) -> list[dict]:
    """
    Ultimele `last_n` meciuri TERMINATE ale echipei `team` în liga `league`,
    cu cornere/faulturi/cartonașe/gol la pauză/șuturi totale reale populate
    (Task 2/3 ADR-011, șuturi totale ADR-021/P7.1) — sursă pentru statistici
    reale afișate în TeamProfile, fără a atinge formula de rating
    (corners/fouls/cards/HT nu sunt încă parametri ai
    compute_team_offdef_rating — rămân informativ). `home_shots`/`away_shots`
    alimentează `shot_dominance` (FEATURE_COLUMNS, promovat prin ablație —
    docs/03_ENGINE/SHOT_DOMINANCE_ABLATION_2026-07-15.md).

    Notă cunoscută: filtrul de rând rămâne `home_corners IS NOT NULL`
    (neschimbat, ca să nu se atingă comportamentul deja validat prin
    ablație al corner_dominance/foul_diff) — deci `avg_shots` se calculează
    doar din rândurile care AU și cornere populate, nu din toate rândurile
    cu șuturi reale. Cuplaj pre-existent, nu unul introdus de P7.1.

    Zero scurgere temporală: doar meciuri cu actual_result populat.
    """
    client = get_client()
    if client is None:
        return []
    try:
        res = (
            client.table("match_history")
            .select("home_team,away_team,home_fouls,away_fouls,"
                    "home_corners,away_corners,home_yellow_cards,away_yellow_cards,"
                    "home_red_cards,away_red_cards,home_ht_goals,away_ht_goals,"
                    "home_shots,away_shots,kickoff_date")
            .eq("league", league)
            .or_(f"home_team.eq.{team},away_team.eq.{team}")
            .not_.is_("actual_result", "null")
            .not_.is_("home_corners", "null")
            .order("kickoff_date", desc=True)
            .limit(last_n)
            .execute()
        )
        return res.data or []
    except Exception as exc:
        logger.warning("[Supabase] get_team_recent_match_events failed pentru %s/%s: %s", team, league, exc)
        return []


def count_training_samples() -> int:
    client = get_client()
    if client is None:
        return 0
    try:
        res = (
            client.table("match_history")
            .select("id", count="exact")
            .not_.is_("actual_result", "null")
            .execute()
        )
        return res.count or 0
    except Exception as exc:
        logger.error("[Supabase] count_training_samples failed: %s", exc)
        return 0


# ════════════════════════════════════════════════════════════════════════════
# ML MODEL STATUS
# ════════════════════════════════════════════════════════════════════════════

def get_ml_status() -> dict:
    client = get_client()
    if client is None:
        return {}
    try:
        res = client.table("ml_model_status").select("*").eq("id", 1).single().execute()
        return res.data or {}
    except Exception as exc:
        logger.error("[Supabase] get_ml_status failed: %s", exc)
        return {}


def save_ml_status(trained_at: str, samples_used: int, accuracy: float | None,
                    log_loss: float | None, feature_names: list[str], model_version: int,
                    notes: str = "") -> bool:
    client = get_client()
    if client is None:
        return False
    try:
        client.table("ml_model_status").update({
            "trained_at": trained_at, "samples_used": samples_used,
            "accuracy": accuracy, "log_loss": log_loss,
            "feature_names": feature_names, "model_version": model_version,
            "notes": notes,
        }).eq("id", 1).execute()
        return True
    except Exception as exc:
        logger.error("[Supabase] save_ml_status failed: %s", exc)
        return False


# ════════════════════════════════════════════════════════════════════════════
# LEARNING CORE — training_runs / model_champions (ADR-015)
# ════════════════════════════════════════════════════════════════════════════
# Istoric append-only de rulări de antrenare + pointer de campion activ per
# (algorithm_family, league_scope). Nu suprascrie niciodată un rând existent
# (spre deosebire de ml_model_status, care rămâne "status curent" pentru
# afișare live — neschimbat, consumatorii lui existenți nu sunt atinși).

def save_training_run(training_run_id: str, algorithm_name: str, algorithm_version: str,
                       league_scope: str, status: str, samples_used: int,
                       walk_forward_metrics: dict, message: str = "") -> bool:
    client = get_client()
    if client is None:
        return False
    try:
        client.table("training_runs").insert({
            "training_run_id": training_run_id,
            "algorithm_name": algorithm_name,
            "algorithm_version": algorithm_version,
            "league_scope": league_scope,
            "status": status,
            "samples_used": samples_used,
            "walk_forward_metrics": walk_forward_metrics,
            "message": message,
        }).execute()
        return True
    except Exception as exc:
        logger.error("[Supabase] save_training_run failed: %s", exc)
        return False


def get_training_run(training_run_id: str) -> dict | None:
    client = get_client()
    if client is None:
        return None
    try:
        res = (
            client.table("training_runs")
            .select("*")
            .eq("training_run_id", training_run_id)
            .single()
            .execute()
        )
        return res.data or None
    except Exception as exc:
        logger.warning("[Supabase] get_training_run failed pentru %s: %s", training_run_id, exc)
        return None


def get_latest_training_run(algorithm_name: str, league_scope: str) -> dict | None:
    """[ADR-030] Cea mai recentă rulare de antrenare persistată în Supabase
    pentru (algorithm_name, league_scope) — sursa durabilă, cross-run, spre
    deosebire de learning_core.storage.list_training_runs() (local, per
    runner, nu supraviețuiește între rulările efemere GitHub Actions).
    None dacă nu s-a antrenat niciodată — stare legitimă, nu eroare."""
    client = get_client()
    if client is None:
        return None
    try:
        res = (
            client.table("training_runs")
            .select("*")
            .eq("algorithm_name", algorithm_name)
            .eq("league_scope", league_scope)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return rows[0] if rows else None
    except Exception as exc:
        logger.warning("[Supabase] get_latest_training_run failed pentru %s/%s: %s",
                        algorithm_name, league_scope, exc)
        return None


def get_active_champion(algorithm_family: str, league_scope: str) -> dict | None:
    """Campionul activ curent pentru (algorithm_family, league_scope) —
    rândul cu superseded_at IS NULL, per invariantul din migrare (cel mult
    unul). None dacă nu există niciun campion promovat încă — stare
    legitimă, nu eroare (Regula #8, nu se aproximează)."""
    client = get_client()
    if client is None:
        return None
    try:
        res = (
            client.table("model_champions")
            .select("*")
            .eq("algorithm_family", algorithm_family)
            .eq("league_scope", league_scope)
            .is_("superseded_at", "null")
            .execute()
        )
        rows = res.data or []
        return rows[0] if rows else None
    except Exception as exc:
        logger.warning("[Supabase] get_active_champion failed pentru %s/%s: %s",
                        algorithm_family, league_scope, exc)
        return None


def get_champion_predecessor(algorithm_family: str, league_scope: str) -> str | None:
    """training_run_id-ul predecesorului campionului activ pentru
    (algorithm_family, league_scope) — rândul pe care campionul activ l-a
    supersedat (superseded_by = training_run-ul campionului activ). None dacă
    nu există campion activ, sau dacă acesta nu are predecesor (a fost primul
    campion) — stare legitimă, nu eroare (Regula #8, nu se aproximează).

    Folosit de learning_core/rollback_service.py DOAR ca precondiție Python
    (fail-fast + validarea artefactului predecesorului + sămânța
    compare-and-swap). Sursa autoritară de derivare rămâne funcția Postgres
    rollback_champion (migrarea 014), care re-derivă predecesorul server-side
    sub lock; de aceea această citire nu trebuie să fie fără-cursă — CAS-ul din
    RPC prinde orice stare învechită. Derivarea de aici oglindește exact
    ORDER BY superseded_at DESC LIMIT 1 din RPC (predecesorul IMEDIAT), ca
    valoarea trimisă ca expected_predecessor să coincidă cu ce verifică RPC-ul."""
    client = get_client()
    if client is None:
        return None
    try:
        active_res = (
            client.table("model_champions")
            .select("training_run_id")
            .eq("algorithm_family", algorithm_family)
            .eq("league_scope", league_scope)
            .is_("superseded_at", "null")
            .execute()
        )
        active_rows = active_res.data or []
        if not active_rows:
            return None
        active_training_run_id = active_rows[0]["training_run_id"]

        pred_res = (
            client.table("model_champions")
            .select("training_run_id")
            .eq("algorithm_family", algorithm_family)
            .eq("league_scope", league_scope)
            .eq("superseded_by", active_training_run_id)
            .order("superseded_at", desc=True)
            .limit(1)
            .execute()
        )
        pred_rows = pred_res.data or []
        return pred_rows[0]["training_run_id"] if pred_rows else None
    except Exception as exc:
        logger.warning("[Supabase] get_champion_predecessor failed pentru %s/%s: %s",
                        algorithm_family, league_scope, exc)
        return None


def create_challenger(training_run_id: str, algorithm_family: str, league_scope: str) -> dict | None:
    """Creează un Challenger nou, în starea CREATED. None la orice eșec —
    fie Supabase indisponibil, fie constrângerea de invariant (cel mult un
    Challenger activ per algorithm_family/league_scope, ADR-016) a respins
    scrierea. Apelantul (learning_core.challenger_manager) e responsabil să
    trateze None ca eșec explicit, nu ca succes tacit (Regula #8)."""
    client = get_client()
    if client is None:
        return None
    try:
        res = client.table("challengers").insert({
            "training_run_id": training_run_id,
            "algorithm_family": algorithm_family,
            "league_scope": league_scope,
            "state": "CREATED",
        }).execute()
        rows = res.data or []
        return rows[0] if rows else None
    except Exception as exc:
        logger.warning("[Supabase] create_challenger failed pentru %s: %s", training_run_id, exc)
        return None


def get_challenger(training_run_id: str) -> dict | None:
    client = get_client()
    if client is None:
        return None
    try:
        res = (
            client.table("challengers")
            .select("*")
            .eq("training_run_id", training_run_id)
            .execute()
        )
        rows = res.data or []
        return rows[0] if rows else None
    except Exception as exc:
        logger.warning("[Supabase] get_challenger failed pentru %s: %s", training_run_id, exc)
        return None


def get_active_challenger(algorithm_family: str, league_scope: str) -> dict | None:
    """Challenger-ul activ curent (stare non-terminală) pentru
    (algorithm_family, league_scope). None dacă nu există niciunul —
    stare legitimă, nu eroare (Regula #8)."""
    client = get_client()
    if client is None:
        return None
    try:
        res = (
            client.table("challengers")
            .select("*")
            .eq("algorithm_family", algorithm_family)
            .eq("league_scope", league_scope)
            .not_.in_("state", ["PROMOTED", "REJECTED"])
            .execute()
        )
        rows = res.data or []
        return rows[0] if rows else None
    except Exception as exc:
        logger.warning("[Supabase] get_active_challenger failed pentru %s/%s: %s",
                        algorithm_family, league_scope, exc)
        return None


def count_active_challengers(algorithm_family: str, league_scope: str) -> int:
    """[ADR-030] Numără independent Challengerii activi (stare non-terminală)
    pentru (algorithm_family, league_scope) — NU reutilizează
    get_active_challenger() (care ia tăcut rows[0] dacă ar exista mai
    multe). Gardă de siguranță: ADR-030 trebuie să detecteze explicit orice
    încălcare a invariantului "cel mult un Challenger activ" (index unic
    parțial idx_challengers_active_unique) — intervenție manuală, migrare
    defectă, bug anterior — nu s-o ascundă alegând orbește primul rând."""
    client = get_client()
    if client is None:
        return -1  # necunoscut != zero — apelantul nu trebuie sa presupuna "sigur"
    try:
        res = (
            client.table("challengers")
            .select("training_run_id")
            .eq("algorithm_family", algorithm_family)
            .eq("league_scope", league_scope)
            .not_.in_("state", ["PROMOTED", "REJECTED"])
            .execute()
        )
        return len(res.data or [])
    except Exception as exc:
        logger.warning("[Supabase] count_active_challengers failed pentru %s/%s: %s",
                        algorithm_family, league_scope, exc)
        return -1


def update_challenger_state(training_run_id: str, expected_current_state: str, new_state: str,
                             rejection_reason: str | None, terminal: bool) -> bool:
    """Tranziție atomică compare-and-swap: scrie DOAR dacă rândul e încă în
    expected_current_state la momentul UPDATE-ului — niciodată check-then-act
    (Regula bazelor de date). False dacă starea s-a schimbat concurent între
    citire și scriere, sau la orice alt eșec."""
    client = get_client()
    if client is None:
        return False
    try:
        now_iso = datetime.now(timezone.utc).isoformat()
        payload = {"state": new_state, "updated_at": now_iso, "rejection_reason": rejection_reason}
        if terminal:
            payload["terminal_at"] = now_iso
        res = (
            client.table("challengers")
            .update(payload)
            .eq("training_run_id", training_run_id)
            .eq("state", expected_current_state)
            .execute()
        )
        return bool(res.data)
    except Exception as exc:
        logger.warning("[Supabase] update_challenger_state failed pentru %s (%s -> %s): %s",
                        training_run_id, expected_current_state, new_state, exc)
        return False


def record_challenger_evaluation(
    training_run_id: str, algorithm_family: str, league_scope: str,
    n_matches_evaluated: int, evaluation_window_start: str | None, evaluation_window_end: str | None,
    verdict: str, statistical_method: str,
    brier_baseline: float | None, brier_experiment: float | None,
    delta_brier: float | None, brier_significant: bool | None,
    logloss_baseline: float | None, logloss_experiment: float | None,
    delta_logloss: float | None, logloss_significant: bool | None,
    accuracy_baseline: float | None, accuracy_experiment: float | None,
    delta_accuracy: float | None, accuracy_significant: bool | None,
) -> bool:
    """Persistă un verdict de Shadow Evaluation ca fapt istoric IMUABIL —
    ADR-018. `INSERT ... ignore_duplicates=True` => ON CONFLICT DO NOTHING
    la nivel Postgres, pe UNIQUE (training_run_id, n_matches_evaluated): o
    rulare ulterioară cu ACEEAȘI fereastră de evaluare nu poate scrie un
    rând nou și nu poate modifica rândul deja existent — niciodată UPDATE,
    niciodată check-then-act. True dacă rândul a fost scris SAU exista deja
    (ambele sunt „faptul e înregistrat", nu eșec)."""
    client = get_client()
    if client is None:
        return False
    try:
        client.table("challenger_evaluations").upsert({
            "training_run_id": training_run_id,
            "algorithm_family": algorithm_family, "league_scope": league_scope,
            "n_matches_evaluated": n_matches_evaluated,
            "evaluation_window_start": evaluation_window_start,
            "evaluation_window_end": evaluation_window_end,
            "verdict": verdict, "statistical_method": statistical_method,
            "brier_baseline": brier_baseline, "brier_experiment": brier_experiment,
            "delta_brier": delta_brier, "brier_significant": brier_significant,
            "logloss_baseline": logloss_baseline, "logloss_experiment": logloss_experiment,
            "delta_logloss": delta_logloss, "logloss_significant": logloss_significant,
            "accuracy_baseline": accuracy_baseline, "accuracy_experiment": accuracy_experiment,
            "delta_accuracy": delta_accuracy, "accuracy_significant": accuracy_significant,
        }, on_conflict="training_run_id,n_matches_evaluated", ignore_duplicates=True).execute()
        return True
    except Exception as exc:
        logger.warning("[Supabase] record_challenger_evaluation failed pentru %s (n=%s): %s",
                        training_run_id, n_matches_evaluated, exc)
        return False


def get_latest_challenger_evaluation(training_run_id: str) -> dict | None:
    """Cel mai recent verdict imuabil (ADR-018) pentru un training_run_id —
    ordonat după `evaluated_at`. None dacă nu există niciunul încă (stare
    legitimă, nu eroare — Regula #8)."""
    client = get_client()
    if client is None:
        return None
    try:
        res = (
            client.table("challenger_evaluations")
            .select("*")
            .eq("training_run_id", training_run_id)
            .order("evaluated_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return rows[0] if rows else None
    except Exception as exc:
        logger.warning("[Supabase] get_latest_challenger_evaluation failed pentru %s: %s",
                        training_run_id, exc)
        return None


# ════════════════════════════════════════════════════════════════════════════
# CHAMPION HEALTH (ADR-037, R2) — citire predicții servite scorabile + scriere/
# citire evaluări de sănătate. Champion Guardian (R2.4) e SINGURUL scriitor al
# champion_health_evaluations; e READ-ONLY față de model_champions.
# ════════════════════════════════════════════════════════════════════════════

def get_champion_served_outcomes(
    algorithm_family: str, league_scope: str, since_date: str | None = None,
) -> list[dict]:
    """Predicțiile SERVITE ale campionului, deja rezolvate (scorabile) — rânduri
    din match_history cu prob_*_pred ȘI actual_result prezente, ordonate
    cronologic DETERMINIST după (kickoff_date, fixture_id). Substratul evaluării
    de sănătate (R2.4).

    Adaptor NEUTRU (F-A/F-B audit): filtrează + sortează determinist + întoarce
    TOATE rezultatele. Dimensionarea ferestrei (ex. „ultimele 200") aparține
    Champion Guardian (R2.4), nu acestui strat de date — aceeași separare de
    responsabilități ca în R1. Ordine TOTALĂ prin cheia secundară fixture_id:
    kickoff_date e TEXT dată-only → mai multe meciuri/zi; fără cheie secundară
    ordinea n-ar fi reproductibilă la trend.

    Atribuire temporală (ADR-037 §9, acceptată Stage 1): `since_date` =
    promoted_at-ul campionului ca dată-only `YYYY-MM-DD` (kickoff_date >=
    since_date), fiindcă prob_*_pred nu poartă identitatea modelului servitor.
    `league_scope="all"` e SENTINEL (nu filtrează liga, ca în
    continuous_learning._count_finished_matches); altfel filtrează
    match_history.league. Listă goală = stare legitimă (ex. 0 scorabile,
    ADR-037 Risk R-A), nu eroare (Regula #8). READ-ONLY."""
    client = get_client()
    if client is None:
        return []
    try:
        q = (
            client.table("match_history")
            .select("fixture_id,home_team,away_team,league,kickoff_date,"
                    "prob_home_pred,prob_draw_pred,prob_away_pred,actual_result")
            .not_.is_("prob_home_pred", "null")
            .not_.is_("actual_result", "null")
        )
        if league_scope != "all":
            q = q.eq("league", league_scope)
        if since_date:
            q = q.gte("kickoff_date", since_date)
        res = q.order("kickoff_date", desc=False).order("fixture_id", desc=False).execute()
        return res.data or []
    except Exception as exc:
        logger.warning("[Supabase] get_champion_served_outcomes failed pentru %s/%s: %s",
                        algorithm_family, league_scope, exc)
        return []


def record_champion_health_evaluation(
    training_run_id: str, algorithm_family: str, league_scope: str,
    window_end: str, n_matches_evaluated: int,
    health_state: str, baseline_source: str,
    brier_live: float | None = None, logloss_live: float | None = None,
    accuracy_live: float | None = None,
    brier_baseline: float | None = None, logloss_baseline: float | None = None,
    accuracy_baseline: float | None = None,
    stability_indicator: float | None = None,
    baseline_deviation_flag: bool | None = None, trend_flag: bool | None = None,
    structural_flag: bool | None = None, stability_flag: bool | None = None,
) -> bool:
    """Persistă o evaluare de sănătate ca fapt IMUABIL (ADR-037/R2). `upsert`
    cu on_conflict pe UNIQUE (training_run_id, n_matches_evaluated) +
    ignore_duplicates=True => ON CONFLICT DO NOTHING: aceeași fereastră (același
    n_matches_evaluated) nu poate scrie un rând nou sau modifica unul existent —
    niciodată UPDATE, niciodată check-then-act. Tipar identic cu
    record_challenger_evaluation. True dacă rândul e scris SAU exista deja."""
    client = get_client()
    if client is None:
        return False
    try:
        client.table("champion_health_evaluations").upsert({
            "training_run_id": training_run_id,
            "algorithm_family": algorithm_family, "league_scope": league_scope,
            "window_end": window_end, "n_matches_evaluated": n_matches_evaluated,
            "health_state": health_state, "baseline_source": baseline_source,
            "brier_live": brier_live, "logloss_live": logloss_live, "accuracy_live": accuracy_live,
            "brier_baseline": brier_baseline, "logloss_baseline": logloss_baseline,
            "accuracy_baseline": accuracy_baseline,
            "stability_indicator": stability_indicator,
            "baseline_deviation_flag": baseline_deviation_flag, "trend_flag": trend_flag,
            "structural_flag": structural_flag, "stability_flag": stability_flag,
        }, on_conflict="training_run_id,n_matches_evaluated", ignore_duplicates=True).execute()
        return True
    except Exception as exc:
        logger.warning("[Supabase] record_champion_health_evaluation failed pentru %s (n=%s): %s",
                        training_run_id, n_matches_evaluated, exc)
        return False


def get_recent_champion_health_evaluations(training_run_id: str, limit: int = 5) -> list[dict]:
    """Cele mai recente evaluări de sănătate pentru un training_run_id, ordonate
    descrescător după n_matches_evaluated (ferestre tot mai mari = tot mai
    recente). Folosit de Champion Guardian pentru regula ferestrelor
    consecutive. Listă goală = fără istoric încă (legitim, Regula #8)."""
    client = get_client()
    if client is None:
        return []
    try:
        res = (
            client.table("champion_health_evaluations")
            .select("*")
            .eq("training_run_id", training_run_id)
            .order("n_matches_evaluated", desc=True)
            .limit(limit)
            .execute()
        )
        return res.data or []
    except Exception as exc:
        logger.warning("[Supabase] get_recent_champion_health_evaluations failed pentru %s: %s",
                        training_run_id, exc)
        return []


# ════════════════════════════════════════════════════════════════════════════
# CONSENSUS VALIDATION (ADR-033) — strict append-only, independent de
# shadow_predictions/challenger_evaluations (infrastructură proprie, per
# decizia explicită din ADR-033).
# ════════════════════════════════════════════════════════════════════════════

def save_consensus_capture_sample(
    fixture_id: str, league: str, home_team: str, away_team: str,
    kickoff_date: str | None, raw_predictions: list,
) -> bool:
    """Persistă o pereche de ieșiri brute (ADR-031) — Faza 1, captură la
    serving-time. `UNIQUE(fixture_id)` + `ignore_duplicates=True` => ON
    CONFLICT DO NOTHING la nivel Postgres: o a doua captură pentru același
    fixture (rerulare Streamlit, retry) nu modifică rândul deja existent.
    True dacă rândul a fost scris SAU exista deja — ambele sunt „fapt
    înregistrat", nu eșec."""
    client = get_client()
    if client is None:
        return False
    try:
        client.table("consensus_capture_samples").upsert({
            "fixture_id": fixture_id, "league": league,
            "home_team": home_team, "away_team": away_team,
            "kickoff_date": kickoff_date, "raw_predictions": raw_predictions,
        }, on_conflict="fixture_id", ignore_duplicates=True).execute()
        return True
    except Exception as exc:
        logger.debug("[Supabase] save_consensus_capture_sample failed pentru %s: %s",
                      fixture_id, exc)
        return False


def get_unevaluated_consensus_samples(limit: int = 5000) -> list[dict]:
    """Perechi capturate (Faza 1) care au acum un rezultat real cunoscut în
    `match_history`, pentru a fi consumate de studiul T1 (Faza 2). Read-only
    pe ambele tabele — nu scrie nimic. Join în Python (nu SQL brut), pe
    `fixture_id`, exact tiparul deja folosit de
    `shadow_testing.evaluate_experiment()`."""
    client = get_client()
    if client is None:
        return []
    try:
        samples_res = (
            client.table("consensus_capture_samples")
            .select("fixture_id,raw_predictions,kickoff_date")
            .order("captured_at")
            .limit(limit)
            .execute()
        )
        samples = samples_res.data or []
        if not samples:
            return []

        fixture_ids = [s["fixture_id"] for s in samples]
        mh_res = (
            client.table("match_history")
            .select("fixture_id,actual_result")
            .in_("fixture_id", fixture_ids)
            .not_.is_("actual_result", "null")
            .execute()
        )
        mh_by_fixture = {r["fixture_id"]: r["actual_result"] for r in (mh_res.data or [])}

        return [
            {**s, "actual_result": mh_by_fixture[s["fixture_id"]]}
            for s in samples if s["fixture_id"] in mh_by_fixture
        ]
    except Exception as exc:
        logger.warning("[Supabase] get_unevaluated_consensus_samples failed: %s", exc)
        return []


def save_consensus_validation_verdict(
    metric_name: str, is_primary_metric: bool, n_samples_evaluated: int,
    evaluation_window_start: str | None, evaluation_window_end: str | None,
    verdict: str, statistical_method: str, metrics: dict,
) -> bool:
    """Persistă verdictul unui studiu ADR-033 ca fapt istoric IMUABIL.
    `UNIQUE(metric_name, n_samples_evaluated)` + `ignore_duplicates=True` =>
    ON CONFLICT DO NOTHING — o rerulare cu ACEEAȘI fereastră nu poate
    schimba verdictul deja scris, identic ca disciplină cu
    `record_challenger_evaluation()` (ADR-018)."""
    client = get_client()
    if client is None:
        return False
    try:
        client.table("consensus_validation_verdicts").upsert({
            "metric_name": metric_name, "is_primary_metric": is_primary_metric,
            "n_samples_evaluated": n_samples_evaluated,
            "evaluation_window_start": evaluation_window_start,
            "evaluation_window_end": evaluation_window_end,
            "verdict": verdict, "statistical_method": statistical_method,
            "metrics": metrics,
        }, on_conflict="metric_name,n_samples_evaluated", ignore_duplicates=True).execute()
        return True
    except Exception as exc:
        logger.warning("[Supabase] save_consensus_validation_verdict failed pentru %s (n=%s): %s",
                        metric_name, n_samples_evaluated, exc)
        return False


def rpc_promote_challenger(training_run_id: str, promoted_by: str) -> str:
    """Apelează funcția Postgres `promote_challenger` (migration 005) —
    ADR-019/Contract de Atomicitate: o singură tranzacție, ambele efecte
    (model_champions + challengers) aplicate atomic sau deloc. Întoarce
    'promoted' | 'already_active'.

    EXCEPȚIE deliberată de la convenția restului fișierului (return None/
    False la eșec): aici excepția e lăsată să urce necontrolat — mesajul
    exact al unui RAISE EXCEPTION server-side (precondiție structurală
    nesatisfăcută, ex. „Challenger nu e SUCCEEDED") e informație pe care
    apelantul (un om care declanșează o promovare manuală) trebuie s-o
    vadă exact, nu doar „a eșuat". `learning_core/promotion_service.py`
    prinde această excepție la propriul nivel și o mapează la
    `PromotionResult(status="rejected", reason=str(exc))` — el rămâne
    punctul unde nicio excepție nu mai scapă necontrolat mai departe."""
    client = get_client()
    if client is None:
        raise RuntimeError("Supabase indisponibil — imposibil de apelat promote_challenger")
    res = client.rpc("promote_challenger", {
        "p_training_run_id": training_run_id,
        "p_promoted_by": promoted_by,
    }).execute()
    return res.data


def rpc_rollback_champion(
    algorithm_family: str, league_scope: str,
    expected_predecessor_training_run_id: str, reason: str, rolled_back_by: str,
) -> str:
    """Apelează funcția Postgres `rollback_champion` (migrarea 014) —
    ADR-037/Contract de Atomicitate: o singură tranzacție, ambele efecte pe
    model_champions (supersedare campion activ + reactivare predecesor prin
    rând nou) aplicate atomic sau deloc. Întoarce 'rolled_back' | 'already_active'.

    EXCEPȚIE deliberată de la convenția restului fișierului (return None/False
    la eșec), simetrică cu `rpc_promote_challenger`: aici excepția e lăsată să
    urce necontrolat — mesajul exact al unui RAISE EXCEPTION server-side
    (precondiție structurală nesatisfăcută, `no_predecessor`,
    `predecessor_mismatch` de la garda compare-and-swap, sau cursă concurentă)
    e informație pe care apelantul trebuie s-o vadă exact. `learning_core/
    rollback_service.py` prinde această excepție la propriul nivel și o mapează
    la `RollbackResult(status="rejected", reason=str(exc))` — el rămâne punctul
    unde nicio excepție nu mai scapă necontrolat mai departe."""
    client = get_client()
    if client is None:
        raise RuntimeError("Supabase indisponibil — imposibil de apelat rollback_champion")
    res = client.rpc("rollback_champion", {
        "p_algorithm_family": algorithm_family,
        "p_league_scope": league_scope,
        "p_expected_predecessor_training_run_id": expected_predecessor_training_run_id,
        "p_reason": reason,
        "p_rolled_back_by": rolled_back_by,
    }).execute()
    return res.data


# ════════════════════════════════════════════════════════════════════════════
# [ADAUGAT] CACHE PERSISTENT (Nivel 2) — vezi architecture/ADR-003-cache.md
# ════════════════════════════════════════════════════════════════════════════
# Sursă comună între toate instanțele (telefon, PC, GitHub Actions, Streamlit
# Cloud). Cheia de CITIRE ignoră deliberat `provider` — dacă există ORICE
# răspuns valid pentru (category, cache_key), indiferent cine l-a produs,
# nu se mai face un request nou. `provider` se păstrează la SCRIERE, doar
# ca metadată de trasabilitate/audit, nu ca parte a deciziei de reutilizare.

def get_cached_response(category: str, cache_key: str) -> dict | None:
    """Citire agnostică de provider — vezi nota de mai sus. Returnează
    payload_json (dict) dacă există un răspuns încă valid, altfel None."""
    client = get_client()
    if client is None:
        return None
    try:
        res = (
            client.table("api_cache")
            .select("payload_json,expires_at,provider")
            .eq("category", category)
            .eq("cache_key", cache_key)
            .gt("expires_at", datetime.now(timezone.utc).isoformat())
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return rows[0]["payload_json"] if rows else None
    except Exception as exc:
        logger.debug("[Supabase] get_cached_response failed: %s", exc)
        return None


def set_cached_response(
    provider: str, category: str, cache_key: str, payload: dict,
    ttl_hours: float, etag: str | None = None,
    source_latency_ms: float | None = None, http_status: int | None = None,
) -> bool:
    """Scrie/actualizează un răspuns în cache-ul persistent. `provider` e
    salvat doar ca metadată — nu afectează cheia de citire (vezi mai sus)."""
    client = get_client()
    if client is None:
        return False
    try:
        now = datetime.now(timezone.utc)
        expires_iso = (now + timedelta(hours=ttl_hours)).isoformat()
        client.table("api_cache").upsert({
            "provider": provider, "category": category, "cache_key": cache_key,
            "payload_json": payload, "etag": etag,
            "source_latency_ms": source_latency_ms, "http_status": http_status,
            "created_at": now.isoformat(), "expires_at": expires_iso,
        }, on_conflict="provider,category,cache_key").execute()
        return True
    except Exception as exc:
        logger.warning("[Supabase] set_cached_response failed: %s", exc)
        return False


# ════════════════════════════════════════════════════════════════════════════
# [ADAUGAT] ACOPERIRE PROVIDERI PER LIGĂ — league_provider_coverage
# ════════════════════════════════════════════════════════════════════════════
# Stare runtime, actualizată periodic — complementară cu LEAGUE_PROVIDERS din
# mappings.py (cunoștința statică, confirmată manual din documentație).

def get_league_provider_coverage(league: str | None = None) -> list[dict]:
    client = get_client()
    if client is None:
        return []
    try:
        q = client.table("league_provider_coverage").select("*")
        if league is not None:
            q = q.eq("league", league)
        res = q.execute()
        return res.data or []
    except Exception as exc:
        logger.error("[Supabase] get_league_provider_coverage failed: %s", exc)
        return []


def set_league_provider_coverage(
    league: str, provider: str, covered: bool | None, category: str = "general",
) -> bool:
    """`covered=None` înseamnă explicit „necunoscut" — distinct de False."""
    client = get_client()
    if client is None:
        return False
    try:
        client.table("league_provider_coverage").upsert({
            "league": league, "provider": provider, "category": category,
            "covered": covered, "checked_at": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="league,provider,category").execute()
        return True
    except Exception as exc:
        logger.error("[Supabase] set_league_provider_coverage failed: %s", exc)
        return False


# ════════════════════════════════════════════════════════════════════════════
# [ADAUGAT R4.1] COVERAGE CACHE API-FOOTBALL — api_football_league_coverage
# ════════════════════════════════════════════════════════════════════════════
# Design aprobat si inghetat: docs/03_ENGINE/API_FOOTBALL_SYNC_V2_AUDIT_2026-07-22.md §2,
# citat explicit de ADR-038 ("Coverage Cache (audit §2)"). Distinct de
# `league_provider_coverage` de mai sus (generic, fara sezon, neapelat azi) —
# vezi nota din database/migrations/016_api_football_league_coverage.sql.
# Tabela poate sa nu existe inca in proiectul conectat (migrare 016,
# proiectata dar neaplicata pana la confirmare explicita — Supabase-safety) —
# degradare gratioasa identica cu restul modulului: `client is None` sau
# orice eroare -> None/False, niciodata exceptie propagata catre apelant.

def get_league_coverage(league_id_canonical: str, api_football_league_id: int, season: int) -> dict | None:
    """Ultima confirmare cunoscuta de coverage pentru (liga, sezon) — sau
    None daca nu exista inca nicio confirmare (tratat ca "necunoscut",
    Regula #8, nu aproximat)."""
    client = get_client()
    if client is None:
        return None
    try:
        res = (
            client.table("api_football_league_coverage")
            .select("*")
            .eq("league_id_canonical", league_id_canonical)
            .eq("api_football_league_id", api_football_league_id)
            .eq("season", season)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return rows[0] if rows else None
    except Exception as exc:
        logger.debug("[Supabase] get_league_coverage failed: %s", exc)
        return None


def set_league_coverage(
    league_id_canonical: str, api_football_league_id: int, season: int,
    fixtures_supported: str, coverage_raw: dict | None = None,
    season_restriction: str | None = None, verified_via: str = "live_call",
    raw_error_payload: dict | None = None,
) -> bool:
    """`fixtures_supported` una din cele 4 stari deja folosite in
    mappings.LEAGUE_PROVIDERS ('True'/'False'/'necunoscut'/'plan_restricted') —
    niciodata NULL, exact disciplina deja aplicata acolo."""
    client = get_client()
    if client is None:
        return False
    try:
        client.table("api_football_league_coverage").upsert({
            "league_id_canonical": league_id_canonical,
            "api_football_league_id": api_football_league_id,
            "season": season,
            "fixtures_supported": fixtures_supported,
            "coverage_raw": coverage_raw,
            "season_restriction": season_restriction,
            "verified_via": verified_via,
            "raw_error_payload": raw_error_payload,
            "verified_at": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="league_id_canonical,api_football_league_id,season").execute()
        return True
    except Exception as exc:
        logger.warning("[Supabase] set_league_coverage failed: %s", exc)
        return False


# ════════════════════════════════════════════════════════════════════════════
# [ADAUGAT] QUOTA PROVIDERI — api_provider_status (vezi ADR-003)
# ════════════════════════════════════════════════════════════════════════════
# Extinde key_manager.py, care azi ține quota DOAR local (key_usage.json) —
# risc de depășire reală a cotei dacă rulează din mai multe instanțe/
# dispozitive (telefon/PC/GitHub Actions) fără sincronizare. Ciclul e LUNAR
# (nu zilnic), identic cu key_manager._reset_if_new_month().

def get_all_provider_usage(month: str) -> dict[str, dict[str, int]]:
    """Returnează {provider: {key_label: used}} pt luna data."""
    client = get_client()
    if client is None:
        return {}
    try:
        res = (
            client.table("api_provider_status")
            .select("provider,api_key_label,used")
            .eq("month", month)
            .execute()
        )
        result: dict[str, dict[str, int]] = {}
        for row in res.data or []:
            result.setdefault(row["provider"], {})[row["api_key_label"]] = row["used"]
        return result
    except Exception as exc:
        logger.warning("[Supabase] get_all_provider_usage failed: %s", exc)
        return {}


def set_provider_usage(provider: str, api_key_label: str, month: str, used: int, quota_limit: int) -> bool:
    client = get_client()
    if client is None:
        return False
    try:
        client.table("api_provider_status").upsert({
            "provider": provider, "api_key_label": api_key_label, "month": month,
            "used": used, "quota_limit": quota_limit,
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="provider,api_key_label,month").execute()
        return True
    except Exception as exc:
        logger.warning("[Supabase] set_provider_usage failed: %s", exc)
        return False


# ════════════════════════════════════════════════════════════════════════════
# [ADAUGAT] OBSERVABILITATE PROVIDERI — provider_metrics (vezi ADR-003)
# ════════════════════════════════════════════════════════════════════════════
# NOTĂ DE SCOP: `cache_hits`/`cache_misses` sunt in schema, dar NU sunt încă
# populate de acest apel — instrumentat doar la nivelul _get() din
# oracle_api.py (un singur punct de trecere pt toate request-urile HTTP
# reale), care nu vede deloc cache-ul (cache-ul e verificat ÎNAINTE, la
# nivelul metodelor de nivel inalt din oracle_api.py). Popularea reala a
# cache_hits/cache_misses ar necesita instrumentarea separata a
# cache_manager.py (CacheManager.get/.set) - ramane follow-up, nu ascuns.

def record_provider_call(provider: str, endpoint: str, success: bool, latency_ms: float) -> bool:
    """Read-then-write (2 round-trip-uri) - acceptabil la volumul actual de
    request-uri (zeci-sute, nu mii/secunda), consistent cu restul proiectului
    (fara coada/async, vezi ADR-003)."""
    client = get_client()
    if client is None:
        return False
    try:
        res = (
            client.table("provider_metrics").select("*")
            .eq("provider", provider).eq("endpoint", endpoint)
            .limit(1).execute()
        )
        rows = res.data or []
        now = datetime.now(timezone.utc).isoformat()

        if rows:
            row = rows[0]
            calls = row["calls"] + 1
            errors = row["errors"] + (0 if success else 1)
            prev_avg = row.get("avg_latency_ms") or 0.0
            new_avg = (prev_avg * row["calls"] + latency_ms) / calls
            consecutive_failures = 0 if success else row.get("consecutive_failures", 0) + 1
            update = {
                "calls": calls, "errors": errors, "avg_latency_ms": new_avg,
                "consecutive_failures": consecutive_failures, "last_call": now,
            }
            update["last_success" if success else "last_failure"] = now
            client.table("provider_metrics").update(update).eq("provider", provider).eq("endpoint", endpoint).execute()
        else:
            client.table("provider_metrics").insert({
                "provider": provider, "endpoint": endpoint,
                "calls": 1, "cache_hits": 0, "cache_misses": 0,
                "errors": 0 if success else 1, "avg_latency_ms": latency_ms,
                "consecutive_failures": 0 if success else 1,
                "last_call": now,
                "last_success": now if success else None,
                "last_failure": None if success else now,
            }).execute()
        return True
    except Exception as exc:
        logger.debug("[Supabase] record_provider_call failed: %s", exc)
        return False


def get_provider_metrics() -> list[dict]:
    """[ADAUGAT] Citește provider_metrics (calls/errors/consecutive_failures/
    avg_latency_ms/last_success/last_failure) — scris deja de
    record_provider_call() din oracle_api.py/football_providers.py, dar
    niciodată citit înainte de acest apel (gol găsit la audit — infrastructura
    ADR-003 de observabilitate exista pe jumătate, doar scriere, fără citire).
    Read-only, aditiv."""
    client = get_client()
    if client is None:
        return []
    try:
        res = client.table("provider_metrics").select("*").execute()
        return res.data or []
    except Exception as exc:
        logger.warning("[Supabase] get_provider_metrics failed: %s", exc)
        return []
