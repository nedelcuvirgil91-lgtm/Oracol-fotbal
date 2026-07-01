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
from datetime import datetime, timezone
from typing import Any

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
    """Returnează toate meciurile din istoric care au rezultat real cunoscut."""
    client = get_client()
    if client is None:
        return []
    try:
        q = client.table("match_history").select("*")
        if only_with_results:
            q = q.not_.is_("actual_result", "null")
        res = q.execute()
        return res.data or []
    except Exception as exc:
        logger.error("[Supabase] get_training_data failed: %s", exc)
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
