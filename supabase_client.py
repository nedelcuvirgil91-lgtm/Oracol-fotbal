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
    """Inserează sau actualizează un meci în dataset-ul de antrenare ML."""
    client = get_client()
    if client is None:
        return False
    try:
        client.table("match_history").upsert(row, on_conflict="fixture_id").execute()
        return True
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
    cu cornere/faulturi/cartonașe reale populate (Task 2, ADR-011) — sursă
    pentru statistici reale afișate în TeamProfile, fără a atinge formula
    de rating (corners/fouls/cards nu sunt încă parametri ai
    compute_team_offdef_rating — rămân informativ, până la o decizie
    separată de ablație).

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
                    "home_red_cards,away_red_cards,kickoff_date")
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
