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


def _rpc_write_ok(res, payload: dict, ctx: str) -> bool:
    """Interpreteaza rezultatul unui RPC canonic (upsert_match_canonical).
    True daca s-a scris (insert/update); False + warning la HARD CONFLICT
    (rand nescris — niciodata pierdut tacit, ID-025-01/03)."""
    data = getattr(res, "data", None) or {}
    action = data.get("action") if isinstance(data, dict) else None
    if action == "hard_conflict":
        logger.warning(
            "[Queries] %s HARD CONFLICT (nescris): %s vs %s @ %s",
            ctx, payload.get("home_team"), payload.get("away_team"), payload.get("kickoff_date"),
        )
        return False
    return action in ("insert", "update")


def upsert_match(row: dict) -> bool:
    """
    [MIGRAT — ID-025-03 Writer Migration] Ruteaza prin RPC-ul canonic
    (`upsert_match_canonical`): lookup pe cheia naturala normalizata (home/away
    deja normalizate in Python) + decizie UPDATE/INSERT sub pg_advisory_xact_lock,
    in loc de upsert direct pe fixture_id. Un meci deja existent devine UPDATE
    non-destructiv pe randul canonic — zero duplicate noi (mecanismul D, ADR-025).
    """
    client = get_client()
    if client is None:
        return False
    payload = _strip_none_values(_normalize_team_fields(row))
    try:
        res = client.rpc("upsert_match_canonical", {"p_payload": payload}).execute()
        return _rpc_write_ok(res, payload, "upsert_match")
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
    # [MIGRAT — ID-025-03 Writer Migration] Fiecare lot trece prin RPC-ul canonic
    # `upsert_matches_canonical` (o singura tranzactie per lot, lock-uri advisory
    # per cheie naturala, achizitionate in ordine crescatoare -> deadlock-free
    # intre loturi concurente). Un meci deja existent devine UPDATE non-destructiv
    # pe randul canonic, niciodata un al doilea INSERT — zero duplicate noi.
    # Batch de 250 (marit de la 50) — reduce ~5x request-urile HTTP catre Supabase.
    batch_size = 250
    for i in range(0, len(rows), batch_size):
        batch = [_strip_none_values(_normalize_team_fields(r)) for r in rows[i:i + batch_size]]
        try:
            res = client.rpc("upsert_matches_canonical", {"p_payloads": batch}).execute()
            data = getattr(res, "data", None) or {}
            ok += int(data.get("inserted", 0)) + int(data.get("updated", 0))
            hc = int(data.get("hard_conflict", 0))
            if hc:
                errors += hc
                logger.warning("[Queries] bulk upsert batch %d: %d HARD CONFLICT nescrise", i, hc)
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
            .is_("superseded_by", "null")
            .execute()
        )
        return res.count or 0
    except Exception as exc:
        logger.error("[Queries] count_matches_with_result failed: %s", exc)
        return 0


def get_finished_matches_missing_stats(
    days_back: int = 2, limit: int = 200,
    date_from: str | None = None, date_to: str | None = None,
    league: str | None = None,
    require_referee: bool = False,
) -> list[dict]:
    """
    [ADAUGAT Sprint 1 — Match Statistics] Meciuri deja ÎNCHEIATE
    (`actual_home_goals` populat de `sync_results`, owner exclusiv, ADR-036)
    care încă NU au datele de statistici.

    Mod implicit (`date_from`/`date_to` neprecizate) — fereastră scurtă,
    `days_back` zile de la azi, ținta reală a `sync/sync_match_statistics.py`
    (sincronizare ZILNICĂ — vezi `DATA_WAREHOUSE_ARCHITECTURE_ETAPA_B_
    2026-07-27.md §1`). Fereastră scurtă deliberată: FreeLF nu garantează
    retenție istorică lungă.

    Mod explicit (`date_from`/`date_to` precizate) — reutilizat de
    `sync/backfill_match_statistics_freelf.py` (backfill istoric, separat
    deliberat de sincronizarea zilnică, aceeași funcție/adaptor, doar
    fereastra de date diferă).

    `require_referee` [ADAUGAT Sprint 1 Faza 1, ADR-041] — implicit `False`,
    comportament NESCHIMBAT pentru apelanții existenți (`home_possession IS
    NULL`, scope-ul îngust FreeLF: doar possession+xG). Soccer Football
    Info (owner nou, set de câmpuri mult mai larg — shots/corners/fouls/
    lineup/manageri/arbitru/stadion) trebuie să folosească `True`: `referee`
    e populat STRICT de acest adaptor, deci e semnalul corect de "lipsesc
    datele bogate" — un meci la care `home_possession` a fost deja completat
    de FreeLF (owner diferit, COALESCE-only, ADR-036) tot trebuie procesat
    de Soccer Football Info dacă `referee` încă lipsește.
    """
    client = get_client()
    if client is None:
        return []
    from datetime import date, timedelta
    if date_from is None:
        date_from = (date.today() - timedelta(days=days_back)).isoformat()
    try:
        query = (
            client.table("match_history")
            .select("home_team,away_team,kickoff_date,league")
            .not_.is_("actual_home_goals", "null")
            .is_("superseded_by", "null")
            .gte("kickoff_date", date_from)
        )
        query = query.is_("referee", "null") if require_referee else query.is_("home_possession", "null")
        if date_to is not None:
            query = query.lte("kickoff_date", date_to)
        if league is not None:
            query = query.eq("league", league)
        res = (
            query
            .order("kickoff_date", desc=True)
            .limit(limit)
            .execute()
        )
        return res.data or []
    except Exception as exc:
        logger.error("[Queries] get_finished_matches_missing_stats failed: %s", exc)
        return []


def get_matches_missing_results(days_back: int = 60, limit: int = 200) -> list[dict]:
    """
    [ADAUGAT Sprint 3, Pasul 1 — închidere retroactivă Feedback Loop]
    Meciuri din trecut (kickoff_date < azi) fără NICIUN rezultat real încă
    (`actual_result IS NULL`) — indiferent dacă au sau nu predicție salvată
    (`prob_home_pred`), fiindcă orice rând fără rezultat blochează
    permanent bucla Prediction → Result → Evaluation pentru acel meci.
    Ținta reală a `sync/sync_results.py:fetch_results_from_
    soccerfootballinfo()` — a treia sursă de rezultate reale, după
    football-data.org și odds_api_recent_results, pentru ligile acoperite
    de League Mapping v2 Soccer Football Info (Sprint 3, Prioritatea 1).
    """
    client = get_client()
    if client is None:
        return []
    try:
        from datetime import date, timedelta
        today = date.today()
        date_from = (today - timedelta(days=days_back)).isoformat()
        date_to = today.isoformat()
        res = (
            client.table("match_history")
            .select("id,home_team,away_team,league,kickoff_date")
            .is_("actual_result", "null")
            .is_("superseded_by", "null")
            .gte("kickoff_date", date_from)
            .lt("kickoff_date", date_to)
            .order("kickoff_date", desc=True)
            .limit(limit)
            .execute()
        )
        return res.data or []
    except Exception as exc:
        logger.error("[Queries] get_matches_missing_results failed: %s", exc)
        return []


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
# ELO CANONIC — Canonical Live ELO Snapshot (ADR-023 Variant C, executat de
# ADR-035 D2 pe calea de servire)
# ════════════════════════════════════════════════════════════════════════════

_team_elo_cache: dict[str, int | None] = {}


def get_latest_team_elo(team: str, lookback: int = 5) -> int | None:
    """
    Sursa canonică pentru ELO-ul de club folosit de servirea live
    (oracle_engine._build_profile()) — ADR-023 (Variant C) / ADR-035 (D2).

    Returnează home_elo_after/away_elo_after (din perspectiva echipei
    `team`) al celui mai recent meci TERMINAT al ei, căutat GLOBAL — fără
    filtru de ligă. ELO e urmărit per club, nu per competiție (ELOTracker,
    sync/backfill_features.py, cheie doar pe numele echipei, populat de
    run_backfill() fără filtru de ligă în ambii apelanți de producție,
    sync/run_daily.py și sync/sync_results.py) — un club care joacă în mai
    multe competiții sincronizate are un singur traseu ELO continuu.

    Caută în ultimele `lookback` meciuri terminate, nu doar cel mai recent:
    home_elo_after/away_elo_after pot rămâne temporar NULL pe rânduri deja
    scrise dacă backfill-ul de features n-a ajuns încă la ele (risc
    rezidual documentat, ADR-023 Consecința #4 — inserție istorică
    întârziată). Dacă niciun rând din fereastră nu are valoare, se
    întoarce None — nu se aproximează (Regula #8) — iar apelantul cade pe
    fallback-ul de provider existent (oracle_api.get_elo_rating()).

    Cache in-memory, per proces (nu per-cerere HTTP): evită interogări
    Supabase repetate pentru aceeași echipă în cadrul aceleiași rulări
    (ex. o echipă apare ca oponent în mai multe meciuri prezise în același
    batch). Fără TTL/staleness detection — explicit Phase 7 (ADR-023), nu
    responsabilitatea acestei funcții.
    """
    if team in _team_elo_cache:
        return _team_elo_cache[team]

    client = get_client()
    if client is None:
        return None
    try:
        res = (
            client.table("match_history")
            .select("home_team,away_team,home_elo_after,away_elo_after,kickoff_date")
            .or_(f"home_team.eq.{team},away_team.eq.{team}")
            .not_.is_("actual_result", "null")
            .is_("superseded_by", "null")
            .order("kickoff_date", desc=True)
            .order("id", desc=True)
            .limit(lookback)
            .execute()
        )
        rows = res.data or []
    except Exception as exc:
        logger.warning("[Queries] get_latest_team_elo failed pentru %s: %s", team, exc)
        return None

    elo: int | None = None
    for row in rows:
        is_home = row.get("home_team") == team
        is_away = row.get("away_team") == team
        if not (is_home or is_away):
            continue
        val = row.get("home_elo_after") if is_home else row.get("away_elo_after")
        if val is not None:
            elo = int(round(val))
            break

    _team_elo_cache[team] = elo
    return elo


# ════════════════════════════════════════════════════════════════════════════
# H2H CANONIC — Head-to-Head Database-First (ADR-035 D3)
# ════════════════════════════════════════════════════════════════════════════

def get_h2h_from_history(home: str, away: str, last_n: int = 10) -> list[dict]:
    """
    Sursa canonică pentru H2H folosită de servirea live
    (oracle_engine._build_h2h()) — ADR-035 (D3).

    Returnează ultimele `last_n` confruntări directe TERMINATE dintre cele
    două cluburi (ambele orientări gazdă/oaspete), ca RÂNDURI BRUTE — apelantul
    recalculează bilanțul din `actual_result`/`actual_home_goals`/
    `actual_away_goals`, exact cum D1 recalculează forma din rezultate brute.
    NU se folosesc niciodată coloanele precalculate `h2h_modifier`/
    `h2h_meetings` (Decizia 2, D3): sunt scrise concurent de două căi și pot
    fi contaminate — vezi D3.5 (Feature Canonicalization).

    Căutare GLOBALĂ — fără filtru de ligă (Decizia 1, D3): H2H reprezintă
    istoricul confruntărilor dintre două cluburi indiferent de competiție,
    consecvent cu ELO-ul global per club (D2). Cheia naturală a perechii e
    simetrică: (home vs away) SAU (away vs home).

    Zero scurgere temporală: doar meciuri cu `actual_result` populat — un meci
    viitor de prezis nu are încă rezultat, deci nu poate apărea aici, pentru
    niciuna dintre cele două echipe. Apelantul aplică pragul minim de
    confruntări (Decizia 3, D3) și, sub prag, cade pe cascada de provideri
    existentă — nu se aproximează aici (Regula #8).
    """
    client = get_client()
    if client is None:
        return []
    try:
        res = (
            client.table("match_history")
            .select("home_team,away_team,actual_home_goals,actual_away_goals,"
                    "actual_result,kickoff_date,league")
            .or_(f"and(home_team.eq.{home},away_team.eq.{away}),"
                 f"and(home_team.eq.{away},away_team.eq.{home})")
            .not_.is_("actual_result", "null")
            .is_("superseded_by", "null")
            .order("kickoff_date", desc=True)
            .order("id", desc=True)
            .limit(last_n)
            .execute()
        )
        return res.data or []
    except Exception as exc:
        logger.warning("[Queries] get_h2h_from_history failed pentru %s vs %s: %s", home, away, exc)
        return []


# ════════════════════════════════════════════════════════════════════════════
# TEAM HEALTH — Injuries + Coaches Database-First (ADR-039, R-Sync-2)
# ════════════════════════════════════════════════════════════════════════════

def get_team_health(team: str) -> dict | None:
    """
    Sursa canonică pentru starea de sănătate a unei echipe (injuries+coaches)
    folosită de servirea live (oracle_engine.evaluate_match()) — ADR-039,
    R-Sync-2. Înlocuiește apelul live către ApiFootballProvider din Oracle
    Engine — citire STRICT din Supabase, populată separat de Sync Layer
    (sync/sync_team_health.py), niciodată direct de aici.

    Identitate canonică prin nume normalizat (ADR-039 Principiul 7) — NU
    prin ID-ul numeric de provider; `team` trebuie să fie deja trecut prin
    `normalize_team_name()` de apelant, exact ca la `get_latest_team_elo()`/
    `get_h2h_from_history()`.

    Întoarce None dacă echipa nu a fost încă sincronizată — Regula #8,
    tratat de apelant ca „necunoscut", NICIODATĂ ca motiv de fallback live
    către provider (spre deosebire de `get_latest_team_elo()`/
    `get_h2h_from_history()`, care au voie să cadă pe cascada de provideri
    sub ADR-035 — ADR-039 elimină explicit acea excepție pentru providerii
    deja migrați la Sync Layer).
    """
    client = get_client()
    if client is None:
        return None
    try:
        res = (
            client.table("team_health_snapshot")
            .select("*")
            .eq("team_name_canonical", team)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return rows[0] if rows else None
    except Exception as exc:
        logger.warning("[Queries] get_team_health failed pentru %s: %s", team, exc)
        return None


def upsert_team_health(
    team: str, injuries: list[dict], coaches: list[dict],
    source_provider: str = "apifootball",
) -> bool:
    """
    Owner unic de scriere pentru `team_health_snapshot` (disciplina
    ADR-036) — exclusiv Sync Layer (`sync/sync_team_health.py`), niciodată
    Oracle Engine.
    """
    client = get_client()
    if client is None:
        return False
    try:
        client.table("team_health_snapshot").upsert({
            "team_name_canonical": team,
            "injuries": injuries,
            "coaches": coaches,
            "source_provider": source_provider,
            "synced_at": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="team_name_canonical").execute()
        return True
    except Exception as exc:
        logger.warning("[Queries] upsert_team_health failed pentru %s: %s", team, exc)
        return False


def get_team_form_footballdata(team: str) -> dict | None:
    """
    Sursa canonică pentru forma/standings unei echipe (football-data.org)
    folosită de servirea live (oracle_engine._build_profile(), Level 3) —
    ADR-039, R-Sync-3. Înlocuiește apelul live către
    `oracle_api.get_standings_form()` din Oracle Engine — citire STRICT
    din Supabase, populată separat de Sync Layer
    (sync/sync_team_form_footballdata.py), niciodată direct de aici.

    Identitate canonică prin nume normalizat (ADR-039 Principiul 7) — NU
    prin ID-ul numeric de provider; `team` trebuie să fie deja trecut prin
    `normalize_team_name()` de apelant, exact ca la `get_team_health()`.

    Întoarce None dacă echipa nu a fost încă sincronizată — Regula #8,
    tratat de apelant ca „necunoscut", niciodată motiv de fallback live
    către provider.
    """
    client = get_client()
    if client is None:
        return None
    try:
        res = (
            client.table("footballdata_team_form_snapshot")
            .select("*")
            .eq("team_name_canonical", team)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return rows[0] if rows else None
    except Exception as exc:
        logger.warning("[Queries] get_team_form_footballdata failed pentru %s: %s", team, exc)
        return None


def upsert_team_form_footballdata(
    team: str, played: int, goals_for: int, goals_against: int, form: str,
) -> bool:
    """
    Owner unic de scriere pentru `footballdata_team_form_snapshot`
    (disciplina ADR-036) — exclusiv Sync Layer
    (`sync/sync_team_form_footballdata.py`), niciodată Oracle Engine.
    """
    client = get_client()
    if client is None:
        return False
    try:
        client.table("footballdata_team_form_snapshot").upsert({
            "team_name_canonical": team,
            "played": played,
            "goals_for": goals_for,
            "goals_against": goals_against,
            "form": form,
            "source_provider": "footballdata",
            "synced_at": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="team_name_canonical").execute()
        return True
    except Exception as exc:
        logger.warning("[Queries] upsert_team_form_footballdata failed pentru %s: %s", team, exc)
        return False


def get_national_team_elo(team: str) -> dict | None:
    """
    Sursa canonică pentru ELO-ul echipelor NAȚIONALE (eloratings.net) —
    folosită de servirea live (oracle_engine._build_profile(), fallback
    ELO după Level DB) — ADR-039, R-Sync-4. Înlocuiește apelul live către
    `oracle_api.get_elo_rating()` — citire STRICT din Supabase, populată
    separat de Sync Layer (sync/sync_national_team_elo.py), niciodată
    direct de aici.

    NU se confundă cu `get_latest_team_elo()` (ELO de club, match_history,
    ADR-023/D2) — acela rămâne sursa primară, neatinsă, pentru orice
    echipă cu meciuri de club sincronizate. Funcția de față e strict
    fallback-ul pentru naționale.

    Identitate canonică prin nume normalizat (ADR-039 Principiul 7) — NU
    prin ID numeric de provider; `team` trebuie să fie deja trecut prin
    `normalize_team_name()` de apelant, exact ca la `get_team_health()`/
    `get_team_form_footballdata()`.

    Întoarce None dacă echipa nu a fost încă sincronizată — Regula #8,
    tratat de apelant ca „necunoscut", niciodată motiv de fallback live
    către provider.
    """
    client = get_client()
    if client is None:
        return None
    try:
        res = (
            client.table("national_team_elo_snapshot")
            .select("*")
            .eq("team_name_canonical", team)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return rows[0] if rows else None
    except Exception as exc:
        logger.warning("[Queries] get_national_team_elo failed pentru %s: %s", team, exc)
        return None


def upsert_national_team_elo(team: str, elo_rating: int) -> bool:
    """
    Owner unic de scriere pentru `national_team_elo_snapshot` (disciplina
    ADR-036) — exclusiv Sync Layer (`sync/sync_national_team_elo.py`),
    niciodată Oracle Engine.
    """
    client = get_client()
    if client is None:
        return False
    try:
        client.table("national_team_elo_snapshot").upsert({
            "team_name_canonical": team,
            "elo_rating": elo_rating,
            "source_provider": "eloratings",
            "synced_at": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="team_name_canonical").execute()
        return True
    except Exception as exc:
        logger.warning("[Queries] upsert_national_team_elo failed pentru %s: %s", team, exc)
        return False


def get_weather_forecast(city: str, kickoff_date: str) -> dict | None:
    """
    Sursa canonică pentru condițiile meteo la o pereche (oraș, dată) —
    folosită de servirea live (oracle_engine.evaluate_match(), penalizare
    xG) — ADR-039, R-Sync-5. Înlocuiește apelul live către
    `oracle_api.get_weather()` — citire STRICT din Supabase, populată
    separat de Sync Layer (sync/sync_weather_forecast.py), niciodată
    direct de aici.

    Cheie: (city, kickoff_date) — NU per meci, NU per echipă. `city`
    trebuie să fie EXACT stringul folosit la sincronizare (fără
    normalizare — nu există încă un mecanism de identitate canonică
    pentru orașe, decizie explicită, proprietar produs, R-Sync-5).

    Întoarce None dacă perechea nu a fost încă sincronizată — Regula #8,
    tratat de apelant ca „necunoscut", niciodată motiv de fallback live
    către provider.
    """
    client = get_client()
    if client is None:
        return None
    try:
        res = (
            client.table("weather_forecast_cache")
            .select("*")
            .eq("city", city)
            .eq("kickoff_date", kickoff_date)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return rows[0] if rows else None
    except Exception as exc:
        logger.warning("[Queries] get_weather_forecast failed pentru %s/%s: %s", city, kickoff_date, exc)
        return None


def upsert_weather_forecast(
    city: str, kickoff_date: str,
    temp_c: float | None, condition: str | None, wind_kph: float | None,
    precip_mm: float | None, humidity: int | None, xg_penalty: float, description: str | None,
) -> bool:
    """
    Owner unic de scriere pentru `weather_forecast_cache` (disciplina
    ADR-036) — exclusiv Sync Layer (`sync/sync_weather_forecast.py`),
    niciodată Oracle Engine. `xg_penalty`/`description` sunt persistate
    EXACT cum le calculează `oracle_api.get_weather()` — nu recalculate
    aici (logica de penalizare rămâne definită într-un singur loc).
    """
    client = get_client()
    if client is None:
        return False
    try:
        client.table("weather_forecast_cache").upsert({
            "city": city,
            "kickoff_date": kickoff_date,
            "temp_c": temp_c,
            "condition": condition,
            "wind_kph": wind_kph,
            "precip_mm": precip_mm,
            "humidity": humidity,
            "xg_penalty": xg_penalty,
            "description": description,
            "source_provider": "weatherapi",
            "synced_at": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="city,kickoff_date").execute()
        return True
    except Exception as exc:
        logger.warning("[Queries] upsert_weather_forecast failed pentru %s/%s: %s", city, kickoff_date, exc)
        return False


def get_team_form_freelf_snapshot(team: str) -> dict | None:
    """
    Sursa canonică pentru standings/forma unei echipe (Free Live Football)
    folosită de servirea live (oracle_engine._build_profile(), Level 0+1
    fuzionate) — ADR-039, R-Sync-6. Înlocuiește apelurile live către
    `oracle_api.get_freelf_standings()`/`get_team_form_freelf()` —
    citire STRICT din Supabase, populată separat de Sync Layer
    (sync/sync_team_form_freelf.py), niciodată direct de aici.

    Identitate canonică prin nume normalizat (ADR-039 Principiul 7) — NU
    prin ID-ul numeric de provider FreeLF; `team` trebuie să fie deja
    trecut prin `normalize_team_name()` de apelant.

    [NOTĂ, R-Sync-6] Coloana `form` va fi aproape mereu goală în practică
    — reproduce fidel un bug preexistent în calea live
    (`get_team_form_freelf()` returna deja mereu `[]` în producție, vezi
    migrarea 021) — NU e o regresie introdusă aici.

    Întoarce None dacă echipa nu a fost încă sincronizată — Regula #8.
    """
    client = get_client()
    if client is None:
        return None
    try:
        res = (
            client.table("freelf_team_form_snapshot")
            .select("*")
            .eq("team_name_canonical", team)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return rows[0] if rows else None
    except Exception as exc:
        logger.warning("[Queries] get_team_form_freelf_snapshot failed pentru %s: %s", team, exc)
        return None


def upsert_team_form_freelf(
    team: str, played: int, wins: int, draws: int, losses: int,
    goals_for: int, goals_against: int, points: int, position: int | None, form: str,
) -> bool:
    """
    Owner unic de scriere pentru `freelf_team_form_snapshot` (disciplina
    ADR-036) — exclusiv Sync Layer (`sync/sync_team_form_freelf.py`),
    niciodată Oracle Engine.
    """
    client = get_client()
    if client is None:
        return False
    try:
        client.table("freelf_team_form_snapshot").upsert({
            "team_name_canonical": team,
            "played": played, "wins": wins, "draws": draws, "losses": losses,
            "goals_for": goals_for, "goals_against": goals_against,
            "points": points, "position": position, "form": form,
            "source_provider": "freelivefootball",
            "synced_at": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="team_name_canonical").execute()
        return True
    except Exception as exc:
        logger.warning("[Queries] upsert_team_form_freelf failed pentru %s: %s", team, exc)
        return False


def get_team_recent_form_oddsapi(team: str, limit: int = 5) -> list[dict]:
    """
    Sursa canonică pentru formă (fallback tertiar, Level 2 în
    `_build_profile()`) — Odds API meciuri terminate recente, sursă
    UNICĂ, partajată cu `get_h2h_from_odds_recent()` (ADR-039, R-Sync-6,
    audit opțiunea A). Citire STRICT din Supabase
    (`odds_api_recent_results`), populată de Sync Layer
    (sync/sync_odds_recent_results.py), niciodată apel live.

    Căutare GLOBALĂ pe echipă (ambele orientări gazdă/oaspete), la fel ca
    `get_latest_team_elo()`/`get_h2h_from_history()`.
    """
    client = get_client()
    if client is None:
        return []
    try:
        res = (
            client.table("odds_api_recent_results")
            .select("*")
            .or_(f"home_team_canonical.eq.{team},away_team_canonical.eq.{team}")
            .order("kickoff_date", desc=True)
            .limit(limit)
            .execute()
        )
        return res.data or []
    except Exception as exc:
        logger.warning("[Queries] get_team_recent_form_oddsapi failed pentru %s: %s", team, exc)
        return []


def get_h2h_from_odds_recent(home: str, away: str, last_n: int = 5) -> list[dict]:
    """
    Sursa canonică pentru H2H (fallback tertiar, în `_build_h2h()`) —
    ACELAȘI tabel `odds_api_recent_results` folosit de
    `get_team_recent_form_oddsapi()` (ADR-039, R-Sync-6, audit opțiunea
    A) — un singur adaptor/tabel, două citiri diferite ale aceleiași date
    canonice, nu două implementări separate.

    Cheie naturală simetrică (home vs away) SAU (away vs home) — exact
    tiparul deja folosit de `get_h2h_from_history()` (ADR-035 D3).
    """
    client = get_client()
    if client is None:
        return []
    try:
        res = (
            client.table("odds_api_recent_results")
            .select("*")
            .or_(f"and(home_team_canonical.eq.{home},away_team_canonical.eq.{away}),"
                 f"and(home_team_canonical.eq.{away},away_team_canonical.eq.{home})")
            .order("kickoff_date", desc=True)
            .limit(last_n)
            .execute()
        )
        return res.data or []
    except Exception as exc:
        logger.warning("[Queries] get_h2h_from_odds_recent failed pentru %s vs %s: %s", home, away, exc)
        return []


def upsert_odds_recent_result(
    home_team: str, away_team: str, kickoff_date: str, league: str,
    home_score: int | None, away_score: int | None,
) -> bool:
    """
    Owner unic de scriere pentru `odds_api_recent_results` (disciplina
    ADR-036) — exclusiv Sync Layer (`sync/sync_odds_recent_results.py`),
    niciodată Oracle Engine.
    """
    client = get_client()
    if client is None:
        return False
    try:
        client.table("odds_api_recent_results").upsert({
            "home_team_canonical": home_team,
            "away_team_canonical": away_team,
            "kickoff_date": kickoff_date,
            "league": league,
            "home_score": home_score,
            "away_score": away_score,
            "source_provider": "oddsapi",
            "synced_at": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="home_team_canonical,away_team_canonical,kickoff_date").execute()
        return True
    except Exception as exc:
        logger.warning(
            "[Queries] upsert_odds_recent_result failed pentru %s vs %s (%s): %s",
            home_team, away_team, kickoff_date, exc,
        )
        return False


def get_recent_odds_results(days_back: int = 14) -> list[dict]:
    """
    [ADAUGAT Sprint 0 — Stabilizare, Etapa 2] Citire READ-ONLY din
    `odds_api_recent_results` — a doua sursă de rezultate reale pentru
    `sync/sync_results.py` (owner canonic al `match_history.actual_*`,
    ADR-036). Completează football-data.org (care nu acoperă Romania
    SuperLiga/MLS/Conference League — vezi `mappings.FD_COMPETITIONS`) cu
    ce a sincronizat deja Sync Layer în `odds_api_recent_results`
    (`sync/sync_odds_recent_results.py`, R-Sync-6).

    Nu scrie nimic — owner-ul de scriere al acestui tabel rămâne exclusiv
    `sync_odds_recent_results.py` (upsert_odds_recent_result, de mai sus).
    Doar rânduri cu scor complet (home_score/away_score ambele non-null) —
    un rând incomplet nu poate produce un `actual_result` valid.
    """
    client = get_client()
    if client is None:
        return []
    from datetime import date, timedelta
    date_from = (date.today() - timedelta(days=days_back)).isoformat()
    try:
        res = (
            client.table("odds_api_recent_results")
            .select("home_team_canonical,away_team_canonical,kickoff_date,league,home_score,away_score")
            .not_.is_("home_score", "null")
            .not_.is_("away_score", "null")
            .gte("kickoff_date", date_from)
            .execute()
        )
        return res.data or []
    except Exception as exc:
        logger.warning("[Queries] get_recent_odds_results failed: %s", exc)
        return []


def upsert_scheduled_fixture(
    home_team: str, away_team: str, kickoff_date: str, provider_id: str,
    league: str | None = None, kickoff_utc: str | None = None, venue_city: str | None = None,
    status: str | None = None,
    freelf_event_id: str | None = None, freelf_home_team_id: str | None = None,
    freelf_away_team_id: str | None = None, freelf_coverage_level: str | None = None,
    odds_api_event_id: str | None = None, odds_api_sport_key: str | None = None,
    apifootball_fixture_id: str | None = None, apifootball_home_team_id: str | None = None,
    apifootball_away_team_id: str | None = None,
    tsdb_home_team_id: str | None = None, tsdb_away_team_id: str | None = None,
    fd_home_team_id: str | None = None, fd_away_team_id: str | None = None,
    espn_home_team_id: str | None = None, espn_away_team_id: str | None = None,
) -> bool:
    """
    Owner unic de scriere pentru `scheduled_fixtures` (disciplina ADR-036)
    — exclusiv Sync Layer, prin cei 6 adaptori de descoperire
    (freelf/odds_api/footballdata/espn/tsdb/apifootball_fixture_adapter.py).
    Oracle Engine NU scrie niciodată aici.

    ÎNTREAGA logică FixtureMergePolicy trăiește în RPC-ul
    `upsert_scheduled_fixture_merge` (migrare 023) — funcția de față e un
    wrapper subțire, NU decide nimic: trimite doar câmpurile pe care
    adaptorul le are (restul rămân `None` → `NULL` în SQL, ignorate de
    RPC), la fel pentru orice provider. Decizie explicită, proprietar
    produs: „adaptorul trimite doar câmpurile lui, RPC decide" — nicio
    logică de merge duplicată aici sau în Python.

    `provider_id`: `'freelf' | 'oddsapi' | 'apifootball' | 'tsdb' | 'fd' | 'espn'`
    — cod scurt, intern RPC-ului, distinct de `SyncAdapter.provider_id`
    folosit în restul Sync Layer (`'freelivefootball'`, `'footballdata'`
    etc.) — documentat explicit aici ca să nu fie confundat.
    """
    client = get_client()
    if client is None:
        return False
    try:
        client.rpc("upsert_scheduled_fixture_merge", {
            "p_home_team_canonical": home_team,
            "p_away_team_canonical": away_team,
            "p_kickoff_date": kickoff_date,
            "p_provider_id": provider_id,
            "p_league": league,
            "p_kickoff_utc": kickoff_utc,
            "p_venue_city": venue_city,
            "p_status": status,
            "p_freelf_event_id": freelf_event_id,
            "p_freelf_home_team_id": freelf_home_team_id,
            "p_freelf_away_team_id": freelf_away_team_id,
            "p_freelf_coverage_level": freelf_coverage_level,
            "p_odds_api_event_id": odds_api_event_id,
            "p_odds_api_sport_key": odds_api_sport_key,
            "p_apifootball_fixture_id": apifootball_fixture_id,
            "p_apifootball_home_team_id": apifootball_home_team_id,
            "p_apifootball_away_team_id": apifootball_away_team_id,
            "p_tsdb_home_team_id": tsdb_home_team_id,
            "p_tsdb_away_team_id": tsdb_away_team_id,
            "p_fd_home_team_id": fd_home_team_id,
            "p_fd_away_team_id": fd_away_team_id,
            "p_espn_home_team_id": espn_home_team_id,
            "p_espn_away_team_id": espn_away_team_id,
        }).execute()
        return True
    except Exception as exc:
        logger.warning(
            "[Queries] upsert_scheduled_fixture failed pentru %s vs %s @ %s (provider=%s): %s",
            home_team, away_team, kickoff_date, provider_id, exc,
        )
        return False


def get_scheduled_fixture(home_team: str, away_team: str, kickoff_date: str) -> dict | None:
    """
    Citire a unui meci descoperit, prin identitatea canonică
    (ADR-024/025). NU folosită încă de Oracle Engine în R-Sync-7a
    (rămâne pe cascada live veche, `get_matches_for_week()`) — pregătită
    pentru R-Sync-7b, citire directă din tabelă.
    """
    client = get_client()
    if client is None:
        return None
    try:
        res = (
            client.table("scheduled_fixtures")
            .select("*")
            .eq("home_team_canonical", home_team)
            .eq("away_team_canonical", away_team)
            .eq("kickoff_date", kickoff_date)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return rows[0] if rows else None
    except Exception as exc:
        logger.warning(
            "[Queries] get_scheduled_fixture failed pentru %s vs %s @ %s: %s",
            home_team, away_team, kickoff_date, exc,
        )
        return None


def list_scheduled_fixtures(kickoff_date_from: str, kickoff_date_to: str) -> list[dict]:
    """
    Toate rândurile din `scheduled_fixtures` pentru o fereastră de date —
    folosită EXCLUSIV de shadow-ul de comparație (R-Sync-7b,
    `scheduled_fixtures_shadow.py`), pentru cardinalitate completă și
    detectarea meciurilor „fantomă" (rânduri persistate fără corespondent
    în calea live curentă) — imposibil de detectat prin lookup-uri punctuale
    (`get_scheduled_fixture`, per meci live). Oracle Engine nu apelează
    această funcție pentru servire (rămâne pe `get_matches_for_week()`
    până la R-Sync-7c).
    """
    client = get_client()
    if client is None:
        return []
    try:
        res = (
            client.table("scheduled_fixtures")
            .select("*")
            .gte("kickoff_date", kickoff_date_from)
            .lte("kickoff_date", kickoff_date_to)
            .execute()
        )
        return res.data or []
    except Exception as exc:
        logger.warning(
            "[Queries] list_scheduled_fixtures failed pentru %s..%s: %s",
            kickoff_date_from, kickoff_date_to, exc,
        )
        return []


def get_teams_with_tsdb_id(days_ahead: int = 14) -> list[dict]:
    """
    [ADAUGAT Sprint 3, R-Sync-8] Echipe cu meci programat în următoarele
    `days_ahead` zile care AU un `tsdb_*_team_id` cunoscut — sursa unică
    pentru Sync Layer (`sync/sync_team_stats_tsdb.py`), citită din
    `scheduled_fixtures` (populată de `TsdbFixtureAdapter`, R-Sync-7a; vezi
    comentariul din `tsdb_fixture_adapter.py`: "Singurul adaptor care
    furnizează tsdb_home_team_id/tsdb_away_team_id — cheia care deblochează
    TheSportsDB team stats la R-Sync-8"). NU se mai caută team_id prin
    apel live de căutare — vine deja din discovery, deja persistat.

    Distinct pe `team_name_canonical` — o echipă poate apărea de mai multe
    ori (acasă/oaspete, meciuri multiple) în fereastră; se ia primul
    tsdb_team_id găsit.
    """
    client = get_client()
    if client is None:
        return []
    try:
        from datetime import date, timedelta
        today = date.today()
        date_to = (today + timedelta(days=days_ahead)).isoformat()
        res = (
            client.table("scheduled_fixtures")
            .select("home_team_canonical,away_team_canonical,tsdb_home_team_id,tsdb_away_team_id")
            .gte("kickoff_date", today.isoformat())
            .lte("kickoff_date", date_to)
            .or_("tsdb_home_team_id.not.is.null,tsdb_away_team_id.not.is.null")
            .execute()
        )
        rows = res.data or []
    except Exception as exc:
        logger.error("[Queries] get_teams_with_tsdb_id failed: %s", exc)
        return []

    teams: dict[str, str] = {}
    for row in rows:
        home = row.get("home_team_canonical")
        away = row.get("away_team_canonical")
        home_id = row.get("tsdb_home_team_id")
        away_id = row.get("tsdb_away_team_id")
        if home and home_id and home not in teams:
            teams[home] = home_id
        if away and away_id and away not in teams:
            teams[away] = away_id
    return [{"team_name": name, "tsdb_team_id": tid} for name, tid in teams.items()]


def get_team_stats_tsdb(team: str) -> list[dict]:
    """
    Sursa canonică pentru ultimele evenimente TheSportsDB ale unei echipe
    (`oracle_engine._build_profile()`, Level 4) — ADR-039, R-Sync-8.
    Înlocuiește apelul live `oracle_api.get_team_stats(team_id, league)` —
    citire STRICT din Supabase, populată separat de Sync Layer
    (`sync/sync_team_stats_tsdb.py`), niciodată direct de aici.

    Identitate canonică prin nume normalizat (ADR-039 Principiul 7) — `team`
    trebuie deja trecut prin `normalize_team_name()` de apelant, exact ca la
    `get_team_form_footballdata()`.

    Întoarce listă goală dacă echipa nu a fost încă sincronizată — Regula
    #8, tratat de apelant ca „necunoscut" (cade pe nivelul următor din
    cascadă), niciodată motiv de fallback live către provider.
    """
    client = get_client()
    if client is None:
        return []
    try:
        res = (
            client.table("tsdb_team_stats_snapshot")
            .select("events")
            .eq("team_name_canonical", team)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            return []
        return rows[0].get("events") or []
    except Exception as exc:
        logger.warning("[Queries] get_team_stats_tsdb failed pentru %s: %s", team, exc)
        return []


def upsert_team_stats_tsdb(team: str, tsdb_team_id: str, events: list[dict]) -> bool:
    """
    Owner unic de scriere pentru `tsdb_team_stats_snapshot` (disciplina
    ADR-036) — exclusiv Sync Layer (`sync/sync_team_stats_tsdb.py`),
    niciodată Oracle Engine.
    """
    client = get_client()
    if client is None:
        return False
    try:
        client.table("tsdb_team_stats_snapshot").upsert({
            "team_name_canonical": team,
            "tsdb_team_id": tsdb_team_id,
            "events": events,
            "source_provider": "thesportsdb",
            "synced_at": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="team_name_canonical").execute()
        return True
    except Exception as exc:
        logger.warning("[Queries] upsert_team_stats_tsdb failed pentru %s: %s", team, exc)
        return False


def get_freelf_fixtures_needing_h2h(days_ahead: int = 14) -> list[dict]:
    """
    [ADAUGAT Sprint 3, R-Sync-9] Meciuri viitoare descoperite de FreeLF
    (`scheduled_fixtures.freelf_event_id` populat, R-Sync-7a) — sursa unică
    pentru Sync Layer (`sync/sync_h2h_freelf.py`). NU se mai caută
    `event_id` live — vine deja din discovery, deja persistat.
    """
    client = get_client()
    if client is None:
        return []
    try:
        from datetime import date, timedelta
        today = date.today()
        date_to = (today + timedelta(days=days_ahead)).isoformat()
        res = (
            client.table("scheduled_fixtures")
            .select("home_team_canonical,away_team_canonical,freelf_event_id")
            .gte("kickoff_date", today.isoformat())
            .lte("kickoff_date", date_to)
            .not_.is_("freelf_event_id", "null")
            .execute()
        )
        return res.data or []
    except Exception as exc:
        logger.error("[Queries] get_freelf_fixtures_needing_h2h failed: %s", exc)
        return []


def get_freelf_h2h_snapshot(home_team: str, away_team: str) -> dict | None:
    """
    Sursa canonică pentru H2H Free Live Football (`oracle_engine._build_h2h()`,
    fallback după Level DB) — ADR-039, R-Sync-9. Înlocuiește apelul live
    `oracle_api.get_h2h(event_id, home_name, away_name)` — citire STRICT
    din Supabase, populată separat de Sync Layer
    (`sync/sync_h2h_freelf.py`), niciodată direct de aici.

    Identitate ORIENTATĂ (home/away, nu simetrică) prin nume normalizate —
    `home_team`/`away_team` trebuie deja trecute prin
    `normalize_team_name()` de apelant.

    Întoarce None dacă perechea nu a fost încă sincronizată — Regula #8,
    tratat de apelant ca „necunoscut" (cade pe nivelul următor din
    cascadă), niciodată motiv de fallback live către provider.
    """
    client = get_client()
    if client is None:
        return None
    try:
        res = (
            client.table("freelf_h2h_snapshot")
            .select("*")
            .eq("home_team_canonical", home_team)
            .eq("away_team_canonical", away_team)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return rows[0] if rows else None
    except Exception as exc:
        logger.warning(
            "[Queries] get_freelf_h2h_snapshot failed pentru %s vs %s: %s",
            home_team, away_team, exc,
        )
        return None


def upsert_freelf_h2h_snapshot(
    home_team: str, away_team: str, freelf_event_id: str,
    meetings: int, home_wins: int, draws: int, away_wins: int,
    home_goals_avg: float, away_goals_avg: float, last_5: list[str],
    h2h_modifier: float, summary: str,
) -> bool:
    """
    Owner unic de scriere pentru `freelf_h2h_snapshot` (disciplina ADR-036)
    — exclusiv Sync Layer (`sync/sync_h2h_freelf.py`), niciodată Oracle
    Engine.
    """
    client = get_client()
    if client is None:
        return False
    try:
        client.table("freelf_h2h_snapshot").upsert({
            "home_team_canonical": home_team,
            "away_team_canonical": away_team,
            "freelf_event_id": freelf_event_id,
            "meetings": meetings,
            "home_wins": home_wins,
            "draws": draws,
            "away_wins": away_wins,
            "home_goals_avg": home_goals_avg,
            "away_goals_avg": away_goals_avg,
            "last_5": last_5,
            "h2h_modifier": h2h_modifier,
            "summary": summary,
            "source_provider": "freelivefootball",
            "synced_at": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="home_team_canonical,away_team_canonical").execute()
        return True
    except Exception as exc:
        logger.warning(
            "[Queries] upsert_freelf_h2h_snapshot failed pentru %s vs %s: %s",
            home_team, away_team, exc,
        )
        return False


def get_upcoming_freelf_fixtures_for_lineup(window_minutes_ahead: int = 240) -> list[dict]:
    """
    [ADAUGAT Sprint 3, R-Sync-10] Meciuri cu `freelf_event_id` cunoscut
    (`scheduled_fixtures`, R-Sync-7a) al căror kickoff cade într-o fereastră
    generoasă în jurul „acum" — sursa unică pentru Sync Layer
    (`sync/sync_lineup_freelf.py`). Fereastra e DELIBERAT largă (implicit
    240 minute înainte de kickoff, plus 15 minute după) — momentul real de
    publicare a aliniamentelor FreeLF nu e cunoscut empiric încă (cota
    cronic epuizată blochează verificarea live, Sprint 3 audit) — o
    fereastră îngustă ar risca să rateze publicarea reală. Instrumentarea
    `*_first_available_at` (migrare 030) acumulează dovada reală în timp;
    fereastra se poate îngusta ulterior, pe bază de date, nu presupunere.
    """
    client = get_client()
    if client is None:
        return []
    try:
        from datetime import datetime, timedelta, timezone as _tz
        now = datetime.now(_tz.utc)
        window_from = (now - timedelta(minutes=15)).isoformat()
        window_to = (now + timedelta(minutes=window_minutes_ahead)).isoformat()
        res = (
            client.table("scheduled_fixtures")
            .select("home_team_canonical,away_team_canonical,kickoff_date,kickoff_utc,freelf_event_id")
            .gte("kickoff_utc", window_from)
            .lte("kickoff_utc", window_to)
            .not_.is_("freelf_event_id", "null")
            .execute()
        )
        return res.data or []
    except Exception as exc:
        logger.error("[Queries] get_upcoming_freelf_fixtures_for_lineup failed: %s", exc)
        return []


def get_freelf_lineup_snapshot(home_team: str, away_team: str, kickoff_date: str) -> dict | None:
    """
    Sursa canonică pentru aliniamente + absențe confirmate Free Live
    Football (`oracle_engine.evaluate_match()`, Database-First, R-Sync-10)
    — ADR-039. Înlocuiește apelul live
    `injury_manager.get_lineup_absences()` → `oracle_api.get_lineup()` —
    citire STRICT din Supabase, populată separat de Sync Layer
    (`sync/sync_lineup_freelf.py`), niciodată direct de aici.

    Un singur rând per meci (ambele părți, home+away) — identitate prin
    (home_team_canonical, away_team_canonical, kickoff_date), la fel ca
    `scheduled_fixtures`/`odds_api_recent_results`.

    Întoarce None dacă meciul nu a fost încă sincronizat — Regula #8,
    tratat de apelant ca „necunoscut", niciodată motiv de fallback live
    către provider.
    """
    client = get_client()
    if client is None:
        return None
    try:
        res = (
            client.table("freelf_lineup_snapshot")
            .select("*")
            .eq("home_team_canonical", home_team)
            .eq("away_team_canonical", away_team)
            .eq("kickoff_date", kickoff_date)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return rows[0] if rows else None
    except Exception as exc:
        logger.warning(
            "[Queries] get_freelf_lineup_snapshot failed pentru %s vs %s: %s",
            home_team, away_team, exc,
        )
        return None


def upsert_freelf_lineup_snapshot(
    home_team: str, away_team: str, kickoff_date: str, freelf_event_id: str,
    home_confirmed: bool, home_formation: str, home_unavailable: list[dict],
    away_confirmed: bool, away_formation: str, away_unavailable: list[dict],
) -> bool:
    """
    Owner unic de scriere pentru `freelf_lineup_snapshot` (disciplina
    ADR-036) — exclusiv Sync Layer (`sync/sync_lineup_freelf.py`),
    niciodată Oracle Engine. Întreaga logică de merge (COALESCE pe
    `*_first_available_at`, niciodată suprascris) trăiește în RPC-ul
    `upsert_freelf_lineup_snapshot_merge` (migrare 030) — funcția de față
    e un wrapper subțire.
    """
    client = get_client()
    if client is None:
        return False
    try:
        client.rpc("upsert_freelf_lineup_snapshot_merge", {
            "p_home_team_canonical": home_team,
            "p_away_team_canonical": away_team,
            "p_kickoff_date": kickoff_date,
            "p_freelf_event_id": freelf_event_id,
            "p_home_confirmed": home_confirmed,
            "p_home_formation": home_formation,
            "p_home_unavailable": home_unavailable,
            "p_away_confirmed": away_confirmed,
            "p_away_formation": away_formation,
            "p_away_unavailable": away_unavailable,
        }).execute()
        return True
    except Exception as exc:
        logger.warning(
            "[Queries] upsert_freelf_lineup_snapshot failed pentru %s vs %s: %s",
            home_team, away_team, exc,
        )
        return False


def upsert_equivalence_evaluation(
    gate_key: str, entity: str, window_from: str, window_to: str,
    live_count: int, scheduled_count: int, matched_count: int,
    missing_scheduled_count: int, missing_live_count: int,
    field_difference_count: int, provider_id_difference_count: int,
    equivalence_state: str,
    duplicate_key_count: int = 0, accepted_exception_count: int = 0,
    equivalence_score: float | None = None,
    provider_breakdown: dict | None = None, root_cause_summary: dict | None = None,
    sample_missing_scheduled: list | None = None, sample_missing_live: list | None = None,
    sample_field_differences: list | None = None, sample_provider_id_diffs: list | None = None,
    run_id: int | None = None,
) -> bool:
    """
    Owner unic de scriere pentru `equivalence_evaluations` (ADR-040) —
    apelată EXCLUSIV prin `equivalence_governance.persist_equivalence_
    evaluation()`, niciodată direct dintr-un hook de provider. Wrapper
    subțire, zero logică de clasificare aici — scorul/starea sunt deja
    calculate de apelant.

    Istoric IMUABIL, append-only — `upsert` cu `on_conflict` pe UNIQUE
    (gate_key, entity, window_to, matched_count) + `ignore_duplicates=True`
    => ON CONFLICT DO NOTHING (migrarea 024), tipar identic cu
    `record_champion_health_evaluation` (`supabase_client.py`).
    """
    client = get_client()
    if client is None:
        return False
    try:
        client.table("equivalence_evaluations").upsert({
            "gate_key": gate_key, "entity": entity,
            "window_from": window_from, "window_to": window_to,
            "live_count": live_count, "scheduled_count": scheduled_count,
            "matched_count": matched_count,
            "missing_scheduled_count": missing_scheduled_count,
            "missing_live_count": missing_live_count,
            "duplicate_key_count": duplicate_key_count,
            "field_difference_count": field_difference_count,
            "provider_id_difference_count": provider_id_difference_count,
            "accepted_exception_count": accepted_exception_count,
            "equivalence_score": equivalence_score,
            "equivalence_state": equivalence_state,
            "provider_breakdown": provider_breakdown or {},
            "root_cause_summary": root_cause_summary or {},
            "sample_missing_scheduled": sample_missing_scheduled or [],
            "sample_missing_live": sample_missing_live or [],
            "sample_field_differences": sample_field_differences or [],
            "sample_provider_id_diffs": sample_provider_id_diffs or [],
            "run_id": run_id,
        }, on_conflict="gate_key,entity,window_to,matched_count", ignore_duplicates=True).execute()
        return True
    except Exception as exc:
        logger.warning(
            "[Queries] upsert_equivalence_evaluation failed pentru %s/%s @ %s: %s",
            gate_key, entity, window_to, exc,
        )
        return False


def get_migration_gate_status_row(gate_key: str, entity: str) -> dict | None:
    """
    Citește agregatele brute pentru un `(gate_key, entity)` din view-ul
    `migration_gate_status` (migrarea 024/025) — folosit EXCLUSIV de
    `migration_gate.py` (ADR-040, G3). View-ul nu decide PASS/FAIL/GRAY —
    doar pregătește ingredientele (Nivel B); decizia rămâne în Python.
    """
    client = get_client()
    if client is None:
        return None
    try:
        res = (
            client.table("migration_gate_status")
            .select("*")
            .eq("gate_key", gate_key)
            .eq("entity", entity)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return rows[0] if rows else None
    except Exception as exc:
        logger.warning(
            "[Queries] get_migration_gate_status_row failed pentru %s/%s: %s",
            gate_key, entity, exc,
        )
        return None


def list_recent_equivalence_evaluations(gate_key: str, entity: str, limit: int = 50) -> list[dict]:
    """
    Ultimele `limit` evaluări (orice stare, inclusiv insufficient_data/broken)
    pentru un `(gate_key, entity)`, ordonate descrescător după `evaluated_at`
    — folosit de `migration_gate.py` (`explain`) pentru agregarea
    `root_cause_summary` peste istoricul recent. NU e sursa pentru Nivel B
    (asta rămâne view-ul `migration_gate_status`).
    """
    client = get_client()
    if client is None:
        return []
    try:
        res = (
            client.table("equivalence_evaluations")
            .select("*")
            .eq("gate_key", gate_key)
            .eq("entity", entity)
            .order("evaluated_at", desc=True)
            .limit(limit)
            .execute()
        )
        return res.data or []
    except Exception as exc:
        logger.warning(
            "[Queries] list_recent_equivalence_evaluations failed pentru %s/%s: %s",
            gate_key, entity, exc,
        )
        return []


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


# ════════════════════════════════════════════════════════════════════════════
# PREDICTION EVALUATION (Sprint 0 — Stabilizare, Etapa 3)
# ════════════════════════════════════════════════════════════════════════════

def upsert_raw_extraction(
    match_ref: str, tab_name: str, raw_extracted: Any,
    validation_status: str = "pending", validation_errors: list | None = None,
    canonical_written: bool = False,
) -> bool:
    """`flashscore_raw_extraction` - stratul RAW al Data Trust Layer-ului
    (RAW -> VALIDATED -> CANONICAL, ADR-044). Scrie output-ul `normalize_
    *()` INDIFERENT de rezultatul validarii (dovada de audit completa,
    North Star #9) - apelantul (`providers/flashscore/persistence.py`)
    decide `validation_status`/`canonical_written` DUPA ce a rulat
    validarea, dar randul RAW exista chiar si pentru meciuri respinse.
    `on_conflict="match_ref,tab_name"` - snapshot curent, nu istoric
    acumulat (schema, migratia 035)."""
    if not raw_extracted:
        return True
    client = get_client()
    if client is None:
        return False
    payload = {
        "match_ref": match_ref, "tab_name": tab_name, "raw_extracted": raw_extracted,
        "validation_status": validation_status, "validation_errors": validation_errors,
        "canonical_written": canonical_written,
    }
    try:
        client.table("flashscore_raw_extraction").upsert(
            payload, on_conflict="match_ref,tab_name",
        ).execute()
        return True
    except Exception as exc:
        logger.error("[Queries] upsert_raw_extraction failed (%s/%s): %s", match_ref, tab_name, exc)
        return False


def upsert_data_completeness(match_ref: str, match_id: int | None, completeness: dict) -> bool:
    """`flashscore_data_completeness` (migratia 037, regula 7 - TASK
    APROBAT M1) - scor persistat, NEconsumat de Oracle Engine/ML azi.
    `completeness`: dict cu cele 7 chei de tab (`summary`/`stats`/
    `lineups`/`player_stats`/`odds`/`h2h`/`standings`, boolean) +
    `coverage_percent` - vezi `providers.flashscore.persistence.
    compute_data_completeness()`. `on_conflict="match_ref"` -
    idempotent, snapshot curent per meci."""
    client = get_client()
    if client is None:
        return False
    payload = {
        "match_ref": match_ref, "match_id": match_id,
        "has_summary": completeness.get("summary", False),
        "has_stats": completeness.get("stats", False),
        "has_lineups": completeness.get("lineups", False),
        "has_player_stats": completeness.get("player_stats", False),
        "has_odds": completeness.get("odds", False),
        "has_h2h": completeness.get("h2h", False),
        "has_standings": completeness.get("standings", False),
        "coverage_percent": completeness.get("coverage_percent", 0.0),
    }
    try:
        client.table("flashscore_data_completeness").upsert(
            payload, on_conflict="match_ref",
        ).execute()
        return True
    except Exception as exc:
        logger.error("[Queries] upsert_data_completeness failed (%s): %s", match_ref, exc)
        return False


def upsert_match_and_get_id(row: dict) -> int | None:
    """Ca `upsert_match()`, dar returneaza id-ul canonic rezolvat (insert
    SAU update) - necesar pentru scrierile FK-dependente ale Foundation
    Data Layer (`match_statistics_extended`, `player_match_stats`,
    `flashscore_match_context`), care au nevoie de `match_history.id`
    pentru a-l lega, nu doar de confirmarea ca s-a scris."""
    client = get_client()
    if client is None:
        return None
    payload = _strip_none_values(_normalize_team_fields(row))
    try:
        res = client.rpc("upsert_match_canonical", {"p_payload": payload}).execute()
        if not _rpc_write_ok(res, payload, "upsert_match_and_get_id"):
            return None
        data = getattr(res, "data", None) or {}
        return data.get("id") if isinstance(data, dict) else None
    except Exception as exc:
        logger.error("[Queries] upsert_match_and_get_id failed: %s", exc)
        return None


# ════════════════════════════════════════════════════════════════════════════
# FLASHSCORE FOUNDATION DATA LAYER (migratia 035/036)
# ════════════════════════════════════════════════════════════════════════════
# Owner de scriere: exclusiv Flashscore (Night Sync) - vezi providers/
# flashscore/persistence.py pentru orchestrarea completa per meci.
# Idempotenta garantata la nivel Postgres prin ON CONFLICT DO UPDATE pe
# exact constrangerea UNIQUE din migratia 035 - rerun-uri repetate produc
# acelasi rand, niciodata un duplicat nou.

def upsert_match_statistics_extended(match_id: int, rows: list[dict]) -> bool:
    """`match_statistics_extended` (EAV) - `on_conflict="match_id,stat_key"`,
    exact cheia UNIQUE a tabelei (migratia 035)."""
    if not rows:
        return True
    client = get_client()
    if client is None:
        return False
    payload = [{**r, "match_id": match_id} for r in rows]
    try:
        client.table("match_statistics_extended").upsert(
            payload, on_conflict="match_id,stat_key",
        ).execute()
        return True
    except Exception as exc:
        logger.error("[Queries] upsert_match_statistics_extended failed: %s", exc)
        return False


def upsert_player_roster(match_id: int, roster_rows: list[dict]) -> bool:
    """`player_match_stats` - randurile BRUTE de roster (nume/numar/echipa,
    din tab-ul Lineups), FARA rating/pozitie (scrise separat, vezi
    `upsert_player_match_stats_extended` mai jos) - `on_conflict=
    "match_id,team,player_name"`, cheia UNIQUE existenta (migratia 032).
    Payload-ul include DOAR coloanele cunoscute aici - un upsert ulterior
    de imbogatire (rating/pozitie) nu le suprascrie cu NULL (PostgREST
    genereaza SET doar pentru coloanele prezente in cerere)."""
    if not roster_rows:
        return True
    client = get_client()
    if client is None:
        return False
    payload = [
        {
            "match_id": match_id, "team": r["team"], "player_name": r["player_name"],
            "shirt_number": r.get("shirt_number"), "source": r.get("source", "flashscore"),
        }
        for r in roster_rows
    ]
    try:
        client.table("player_match_stats").upsert(
            payload, on_conflict="match_id,team,player_name",
        ).execute()
        return True
    except Exception as exc:
        logger.error("[Queries] upsert_player_roster failed: %s", exc)
        return False


def upsert_player_match_stats_extended(match_id: int, stats_rows: list[dict]) -> bool:
    """`player_match_stats_extended` (EAV per jucator) - `stats_rows`:
    randuri din `normalize_player_match_stats_table()`, deja imbinate cu
    roster-ul (team rezolvat) de apelant (`providers/flashscore/
    persistence.py`) - nu se rezolva echipa aici. Fiecare rand scrie
    intai imbogatirea `player_match_stats` (position/rating), citeste
    id-ul rezultat, apoi scrie cele 7 statistici avansate EAV cu acel FK.
    Randuri fara `team` rezolvat sunt EXCLUSE (nu se ghiceste echipa)."""
    if not stats_rows:
        return True
    client = get_client()
    if client is None:
        return False
    ok = True
    for row in stats_rows:
        team = row.get("team")
        if not team:
            logger.warning(
                "[Queries] player_match_stats_extended: '%s' fara echipa rezolvata, exclus",
                row.get("player_name"),
            )
            ok = False
            continue
        enrich_payload = {
            "match_id": match_id, "team": team, "player_name": row["player_name"],
            "position": row.get("position"), "rating": row.get("rating"),
            "source": "flashscore",
        }
        try:
            res = client.table("player_match_stats").upsert(
                enrich_payload, on_conflict="match_id,team,player_name",
            ).execute()
            data = getattr(res, "data", None) or []
            pms_id = data[0]["id"] if data else None
        except Exception as exc:
            logger.error("[Queries] player_match_stats enrichment failed pentru %s: %s",
                         row.get("player_name"), exc)
            ok = False
            continue
        if pms_id is None:
            logger.warning("[Queries] player_match_stats enrichment fara id rezolvat pentru %s",
                           row.get("player_name"))
            ok = False
            continue
        extended = row.get("extended_stats") or []
        if not extended:
            continue
        ext_payload = [
            {
                "player_match_stats_id": pms_id, "stat_key": e["stat_key"],
                "stat_label": e["stat_label"], "value_raw": e.get("value_raw"),
                "value_numeric": e.get("value_numeric"), "source": "flashscore",
            }
            for e in extended
        ]
        try:
            client.table("player_match_stats_extended").upsert(
                ext_payload, on_conflict="player_match_stats_id,stat_key",
            ).execute()
        except Exception as exc:
            logger.error("[Queries] player_match_stats_extended failed pentru %s: %s",
                         row.get("player_name"), exc)
            ok = False
    return ok


def upsert_match_context(rows: list[dict]) -> bool:
    """`flashscore_match_context` (H2H + forma recenta, segmentate) -
    `on_conflict="context_match_id,category,meeting_order"`, cheia
    UNIQUE existenta (migratia 035)."""
    if not rows:
        return True
    client = get_client()
    if client is None:
        return False
    try:
        client.table("flashscore_match_context").upsert(
            rows, on_conflict="context_match_id,category,meeting_order",
        ).execute()
        return True
    except Exception as exc:
        logger.error("[Queries] upsert_match_context failed: %s", exc)
        return False


def upsert_standings_snapshot(rows: list[dict]) -> bool:
    """`flashscore_standings_snapshot` (clasament curent) -
    `on_conflict="competition,team"`, cheia UNIQUE existenta
    (migratia 035) - rerun ACTUALIZEAZA snapshot-ul (rand curent), nu
    acumuleaza istoric."""
    if not rows:
        return True
    client = get_client()
    if client is None:
        return False
    try:
        client.table("flashscore_standings_snapshot").upsert(
            rows, on_conflict="competition,team",
        ).execute()
        return True
    except Exception as exc:
        logger.error("[Queries] upsert_standings_snapshot failed: %s", exc)
        return False


def get_predictions_with_results(days_back: int | None = None) -> list[dict]:
    """
    [ADAUGAT Sprint 0 — Stabilizare, Etapa 3] Citire READ-ONLY — rânduri din
    `match_history` cu ATÂT predicție (prob_home_pred/prob_draw_pred/
    prob_away_pred) CÂT ȘI rezultat real (actual_result). Identitatea
    canonică e deja garantată de owner-ul unic per coloană (ADR-036) —
    aceste două grupuri de coloane sunt scrise de procese diferite
    (`_cache_prediction`/oracle_engine pentru predicții, `sync_results`
    pentru `actual_*`), dar pe ACELAȘI rând, deci join-ul e implicit prin
    identitatea rândului, nu prin vreo cheie separată.

    Sursa exclusivă de citire pentru `prediction_evaluation.py` (raportul
    de acuratețe/log-loss/Brier/calibrare) — nicio scriere aici.
    """
    client = get_client()
    if client is None:
        return []
    try:
        query = (
            client.table("match_history")
            .select("league,kickoff_date,home_team,away_team,fixture_id,"
                    "prob_home_pred,prob_draw_pred,prob_away_pred,actual_result")
            .not_.is_("prob_home_pred", "null")
            .not_.is_("actual_result", "null")
            .is_("superseded_by", "null")
        )
        if days_back is not None:
            from datetime import date, timedelta
            date_from = (date.today() - timedelta(days=days_back)).isoformat()
            query = query.gte("kickoff_date", date_from)
        res = query.execute()
        return res.data or []
    except Exception as exc:
        logger.warning("[Queries] get_predictions_with_results failed: %s", exc)
        return []
