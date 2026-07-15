"""
================================================================================
FOOTBALL ORACLE v4.0 — Database Queries
================================================================================
Module: database/queries.py

Centralizează toate operațiunile de citire/scriere în Supabase.
Folosit de sync/ și de oracle_engine.py.
================================================================================
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Any

from mappings import normalize_team_name

logger = logging.getLogger("FootballOracle.Queries")


def get_client():
    """Importă și returnează clientul Supabase."""
    try:
        import sys
        from pathlib import Path
        # Suportă rulare atât din root cât și din subdirectoare
        root = Path(__file__).parent.parent
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from supabase_client import get_client as _get_client
        return _get_client()
    except Exception as exc:
        logger.error("[Queries] Nu pot obține clientul Supabase: %s", exc)
        return None


# ════════════════════════════════════════════════════════════════════════════
# MATCH HISTORY
# ════════════════════════════════════════════════════════════════════════════

def _normalize_team_fields(row: dict) -> dict:
    """
    [ADAUGAT — P3.5 Team Identity Audit, fix de wiring] Punct unic de
    normalizare a home_team/away_team, aplicat la FIECARE scriere in
    match_history, indiferent de sursa. `normalize_team_name()`
    (mappings.py) exista de mult si e deja aplicata de sync/import_
    historical.py, dar niciun writer al sincronizarii zilnice (sync/
    sources/football_data.py, openfootball.py) nu o apela — cauza
    radacina demonstrata in TEAM_IDENTITY_AUDIT.md (137 echipe
    fragmentate, 10,1% din match_history). Aplicata aici, la cele doua
    functii de upsert (nu in fiecare sursa individual), ca nicio sursa
    viitoare sa nu poata reintroduce defectul — acelasi principiu ca
    _strip_none_values() de mai jos (Protectia Writer-ilor, 2026-07-13).
    """
    out = dict(row)
    if out.get("home_team"):
        out["home_team"] = normalize_team_name(out["home_team"])
    if out.get("away_team"):
        out["away_team"] = normalize_team_name(out["away_team"])
    return out


def upsert_match(row: dict) -> bool:
    """
    Inserează sau actualizează un meci în match_history.
    fixture_id e cheia unică — dacă există, actualizează.
    """
    client = get_client()
    if client is None:
        return False
    try:
        client.table("match_history").upsert(
            _normalize_team_fields(row), on_conflict="fixture_id"
        ).execute()
        return True
    except Exception as exc:
        logger.error("[Queries] upsert_match failed: %s", exc)
        return False


def _strip_none_values(row: dict) -> dict:
    """
    [FIX 2026-07-13 — Protecția Writer-ilor] Elimină cheile cu valoare None
    din payload-ul de upsert. La un upsert pe fixture_id existent, o cheie
    explicit None RESCRIE coloana cu NULL — exact mecanismul care a distrus
    ELO-ul calculat de backfill (1.059 rânduri re-anulate, demonstrat).
    O cheie absentă e echivalentă la INSERT (coloana primește default NULL
    oricum) și inofensivă la UPDATE (coloana rămâne neatinsă). Regula de
    arhitectură: niciun writer de sync nu are voie să transforme o valoare
    validată în NULL — garda e aplicată aici, la punctul unic de trecere,
    ca nicio sursă viitoare cu chei None să nu poată reintroduce defectul.
    """
    return {k: v for k, v in row.items() if v is not None}


def upsert_matches_bulk(rows: list[dict]) -> tuple[int, int]:
    """
    Inserează o listă de meciuri în bulk.
    Returnează (inserted_count, error_count).
    """
    client = get_client()
    if client is None:
        return 0, len(rows)

    ok = 0
    errors = 0
    # Batch de 250 (marit de la 50) — reduce ~5x request-urile HTTP catre
    # Supabase la importuri de volum mare (ex. import_historical.py, 230k+
    # randuri). Payload-ul ramane mic (zeci de KB), sub limitele PostgREST.
    batch_size = 250
    for i in range(0, len(rows), batch_size):
        batch = [_strip_none_values(_normalize_team_fields(r)) for r in rows[i:i + batch_size]]
        try:
            client.table("match_history").upsert(
                batch, on_conflict="fixture_id"
            ).execute()
            ok += len(batch)
        except Exception as exc:
            logger.error("[Queries] bulk upsert batch %d failed: %s", i, exc)
            errors += len(batch)
    return ok, errors


def get_existing_fixture_ids(fixture_ids: list[str]) -> set[str]:
    """
    Returnează set-ul de fixture_id-uri care există deja în Supabase.
    Folosit pentru deduplicare înainte de inserare.

    [FIX 2026-07-13 — eliminat fail-open] Înainte, ORICE excepție întorcea
    set() gol — deduplicarea murea silențios și TOT setul preluat era
    re-upsert-at peste rândurile existente (demonstrat: sync_status
    fetched=5756, skipped=0, zi după zi — cauza directă a interogării cu
    5.756 de id-uri într-un singur .in_(), peste limita de URL). Acum:
    (1) interogarea e împărțită în chunk-uri, ca să nu mai atingă limita;
    (2) la eroare NU se mai întoarce set gol — se propagă excepția
    (fail-closed): apelanții din sync_matches.sync_all() o prind per-sursă
    și abandonează sincronizarea acelei surse FĂRĂ nicio scriere, în loc
    să scrie totul orbește.
    """
    client = get_client()
    if client is None:
        # Fără client nu e posibilă nicio scriere ulterioară (upsert-ul
        # no-op-uiește la rândul lui), deci nu există risc de re-upsert orb.
        return set()

    existing: set[str] = set()
    # 200 id-uri per cerere — id-urile intră în query string (.in_), iar
    # limita practică de URL la PostgREST e ~16KB; 200 × ~30 caractere ≈ 6KB.
    chunk_size = 200
    for i in range(0, len(fixture_ids), chunk_size):
        chunk = fixture_ids[i:i + chunk_size]
        res = (
            client.table("match_history")
            .select("fixture_id")
            .in_("fixture_id", chunk)
            .execute()
        )
        existing.update(row["fixture_id"] for row in (res.data or []))
    return existing


def count_matches_without_result() -> int:
    """Câte meciuri din match_history nu au rezultat real încă."""
    client = get_client()
    if client is None:
        return 0
    try:
        res = (
            client.table("match_history")
            .select("id", count="exact")
            .is_("actual_result", "null")
            .execute()
        )
        return res.count or 0
    except Exception as exc:
        logger.error("[Queries] count_matches_without_result failed: %s", exc)
        return 0


def count_matches_with_result() -> int:
    """Câte meciuri din match_history au rezultat real (pentru ML)."""
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
        logger.error("[Queries] count_matches_with_result failed: %s", exc)
        return 0


def get_matches_by_league(league: str, limit: int = 100) -> list[dict]:
    """Returnează meciurile dintr-o ligă, ordonate descrescător după dată."""
    client = get_client()
    if client is None:
        return []
    try:
        res = (
            client.table("match_history")
            .select("*")
            .eq("league", league)
            .not_.is_("actual_result", "null")
            .order("kickoff_date", desc=True)
            .limit(limit)
            .execute()
        )
        return res.data or []
    except Exception as exc:
        logger.error("[Queries] get_matches_by_league failed: %s", exc)
        return []


# ════════════════════════════════════════════════════════════════════════════
# SYNC STATUS
# ════════════════════════════════════════════════════════════════════════════

def get_sync_status(source: str) -> dict | None:
    """
    Citește statusul ultimei sincronizări pentru o sursă dată.
    source: ex. 'openfootball', 'football_data', 'sportradar'
    """
    client = get_client()
    if client is None:
        return None
    try:
        res = (
            client.table("sync_status")
            .select("*")
            .eq("source", source)
            .single()
            .execute()
        )
        return res.data
    except Exception:
        return None


def upsert_sync_status(source: str, last_sync: str,
                        matches_added: int, matches_updated: int,
                        status: str = "ok", notes: str = "") -> bool:
    """Actualizează statusul sincronizării pentru o sursă."""
    client = get_client()
    if client is None:
        return False
    try:
        client.table("sync_status").upsert({
            "source":          source,
            "last_sync":       last_sync,
            "matches_added":   matches_added,
            "matches_updated": matches_updated,
            "status":          status,
            "notes":           notes,
        }, on_conflict="source").execute()
        return True
    except Exception as exc:
        logger.error("[Queries] upsert_sync_status failed: %s", exc)
        return False


# ════════════════════════════════════════════════════════════════════════════
# ELO RATINGS
# ════════════════════════════════════════════════════════════════════════════

def upsert_elo_ratings(ratings: list[dict]) -> tuple[int, int]:
    """
    Inserează/actualizează ratinguri ELO.
    Format: [{"team": "...", "league": "...", "elo": 1850, "updated_at": "..."}]
    """
    client = get_client()
    if client is None:
        return 0, len(ratings)
    ok = 0
    errors = 0
    batch_size = 50
    for i in range(0, len(ratings), batch_size):
        batch = ratings[i:i + batch_size]
        try:
            client.table("elo_ratings").upsert(
                batch, on_conflict="team,league"
            ).execute()
            ok += len(batch)
        except Exception as exc:
            logger.error("[Queries] upsert_elo_ratings batch %d failed: %s", i, exc)
            errors += len(batch)
    return ok, errors


def get_elo_ratings(league: str | None = None) -> dict[str, int]:
    """
    Returnează ratingurile ELO ca dict {team_name: elo_value}.
    Opțional filtrat per ligă.
    """
    client = get_client()
    if client is None:
        return {}
    try:
        q = client.table("elo_ratings").select("team,elo")
        if league:
            q = q.eq("league", league)
        res = q.execute()
        return {row["team"]: row["elo"] for row in (res.data or [])}
    except Exception as exc:
        logger.error("[Queries] get_elo_ratings failed: %s", exc)
        return {}


# ════════════════════════════════════════════════════════════════════════════
# ELO HISTORY (snapshot-uri temporale, separat de elo_ratings care e curent)
# ════════════════════════════════════════════════════════════════════════════

def upsert_elo_history_bulk(rows: list[dict]) -> tuple[int, int]:
    """
    Inserează/actualizează snapshot-uri ELO istorice în elo_history.
    Format rând: {"team": "...", "league": "...", "elo": 1850,
                  "snapshot_date": "YYYY-MM-DD", "source": "kaggle"}
    Cheia unică e (team, snapshot_date) — conform schemei create anterior.
    """
    client = get_client()
    if client is None:
        return 0, len(rows)
    ok = 0
    errors = 0
    # Batch de 250 (marit de la 50) — reduce ~5x request-urile HTTP catre
    # Supabase la importuri de volum mare (ex. import_historical.py, 245k+
    # randuri). Payload-ul ramane mic (zeci de KB), sub limitele PostgREST.
    batch_size = 250
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        try:
            client.table("elo_history").upsert(
                batch, on_conflict="team,snapshot_date"
            ).execute()
            ok += len(batch)
        except Exception as exc:
            logger.error("[Queries] upsert_elo_history_bulk batch %d failed: %s", i, exc)
            errors += len(batch)
    return ok, errors


# ════════════════════════════════════════════════════════════════════════════
# ML STATUS
# ════════════════════════════════════════════════════════════════════════════

def get_ml_sample_count() -> int:
    """Returnează numărul de meciuri disponibile pentru antrenare ML."""
    return count_matches_with_result()


def should_retrain_ml(min_new_matches: int = 20) -> bool:
    """
    Verifică dacă trebuie reantrenat modelul ML.
    Reantrenează dacă s-au adăugat min_new_matches de la ultimul training.
    """
    client = get_client()
    if client is None:
        return False
    try:
        # Citim samples_used din ultimul training
        ml_res = (
            client.table("ml_model_status")
            .select("samples_used")
            .eq("id", 1)
            .single()
            .execute()
        )
        last_samples = (ml_res.data or {}).get("samples_used") or 0
        current_samples = count_matches_with_result()
        return (current_samples - last_samples) >= min_new_matches
    except Exception as exc:
        logger.error("[Queries] should_retrain_ml failed: %s", exc)
        return False
