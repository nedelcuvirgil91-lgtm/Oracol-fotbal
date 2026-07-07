"""
================================================================================
FOOTBALL ORACLE — sync/import_historical.py (v1.3)
Importa date istorice din Kaggle (adamgbor/club-football-match-data-2000-2025)
in Supabase: fisierul de meciuri -> match_history, fisierul de ELO -> elo_history.

NU implementeaza inca integrarea Understat / xG (scop viitor, separat).
NU modifica mappings.py — foloseste doar normalize_team_name() existent.
NU ghiceste structura: clasifica fisierele CSV pe baza metadatelor produse
de sync.sources.kaggle.inspect_dataset(), nu pe nume de fisier hardcodat.

GARANTIE dry-run: toate scrierile in Supabase trec exclusiv prin _safe_upsert().
In dry-run, aceasta functie returneaza (0, 0) fara sa apeleze niciodata
upsert_matches_bulk() / upsert_elo_history_bulk() — deci zero scrieri reale,
garantat la nivel de cod, nu doar prin conventie.

CHANGES v1.3:
  - [CUTOFF] Pragul de relevanta istorica nu mai e calendaristic
    ("azi minus N ani"), ci bazat pe SEZON fotbalistic (inceput la 1 iulie).
    HISTORICAL_YEARS_BACK -> redenumit HISTORICAL_SEASONS_BACK (semantica
    s-a schimbat: nu mai sunt "ani calendaristici", ci "sezoane complete").
    Sezonul curent e determinat dupa data de azi (UTC): daca azi >= 1 iulie
    an X, sezonul curent e X; altfel X-1. Cutoff = inceputul sezonului
    (sezon_curent - HISTORICAL_SEASONS_BACK), adica 1 iulie al acelui an.
    Motivatie: nu vrem sa taiem un sezon la jumatate doar pentru ziua din
    an in care ruleaza workflow-ul — pastram intotdeauna sezoane complete.
    Vezi _compute_season_cutoff_date(). Vechiul tratament special pentru
    29 februarie (an bisect) a disparut — nu mai are sens, cutoff-ul e
    intotdeauna 1 iulie.
  - [PERFORMANCE] Early-stop pentru fisiere ordonate cronologic DESCRESCATOR
    (cele mai recente randuri primele). Ordinea e detectata AUTOMAT si
    CONTINUU, chunk cu chunk (nu presupusa dinainte) — vezi _SortOrderTracker.
    Odata ce ordinea descrescatoare e confirmata si un chunk intreg are toate
    datele < cutoff, restul fisierului e garantat in afara intervalului si
    citirea se opreste (break). Daca ordinea presupusa e violata la orice
    moment, tracker-ul se dezactiveaza definitiv si tot fisierul e procesat
    normal — siguranta > viteza, in nicio situatie nu se omit randuri valide
    silentios.
    NOTA: pentru fisiere ordonate CRESCATOR (cele mai vechi randuri primele),
    randurile valide (ultimii N ani) sunt la finalul fisierului, deci nu
    exista shortcut fara seek/binary-search pe fisier — decizie explicita,
    neimplementata in acest pas (complexitate/risc suplimentar, discutat
    si respins pentru moment).
  - [RAPORT] report() afiseaza acum explicit: cutoff season, rows imported,
    rows skipped (before cutoff) separat de celelalte motive de respingere,
    si, daca s-a activat early-stop, la ce rand s-a oprit citirea.
  - Pragul se aplica identic pentru ambele fisiere (meciuri si ELO
    snapshots), pentru consistenta.
================================================================================
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable

import pandas as pd

root = Path(__file__).parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from mappings import normalize_team_name, match_key
from database.queries import upsert_matches_bulk, upsert_elo_history_bulk, upsert_sync_status
from sync.sources.kaggle import (
    MAIN_DATASET,
    CsvSummary,
    KaggleSourceError,
    inspect_dataset,
)

logger = logging.getLogger("football_oracle.sync.import_historical")

CHUNK_SIZE = 5000
MAX_DUPLICATE_EXAMPLES = 5
PROGRESS_LOG_INTERVAL = 20000

# [v1.3] Numarul de sezoane complete pastrate. Fix, nu configurabil din CLI,
# prin decizie explicita: simplitate peste flexibilitate aici. Un sezon
# fotbalistic incepe la 1 iulie — vezi _compute_season_cutoff_date().
HISTORICAL_SEASONS_BACK = 5


def _compute_season_cutoff_date(seasons_back: int = HISTORICAL_SEASONS_BACK) -> date:
    """
    Calculeaza cutoff-ul ca INCEPUT DE SEZON (1 iulie), nu calendaristic.

    Sezonul fotbalistic e considerat a incepe la 1 iulie. Sezonul curent e
    identificat dupa data de azi (UTC): daca azi >= 1 iulie al anului X,
    sezonul curent e X; altfel sezonul curent e X-1. Cutoff-ul e inceputul
    sezonului (sezon_curent - seasons_back), adica 1 iulie al acelui an.

    Exemplu: azi = 8 iulie 2026 -> sezon curent = 2026 -> cu seasons_back=5
    -> cutoff = 2021-07-01.

    Motivatie: pastram intotdeauna sezoane complete, nu taiem un sezon la
    jumatate doar in functie de ziua din an in care ruleaza workflow-ul.
    """
    today = datetime.now(timezone.utc).date()
    current_season_start_year = today.year if today >= date(today.year, 7, 1) else today.year - 1
    cutoff_season_start_year = current_season_start_year - seasons_back
    return date(cutoff_season_start_year, 7, 1)


class _SortOrderTracker:
    """
    Detecteaza si urmareste, AUTOMAT si CONTINUU (chunk cu chunk), daca un
    fisier CSV e ordonat cronologic descrescator (cele mai recente randuri
    primele). Nu presupune ordinea dinainte — o verifica la fiecare chunk
    nou, inclusiv continuitatea la granita dintre chunk-uri consecutive.

    Daca ordinea presupusa e violata la orice moment, se dezactiveaza
    DEFINITIV (stare "unsorted") si ramane asa pentru tot restul rularii —
    e o decizie deliberata pentru siguranta: mai bine procesam tot fisierul
    (mai lent) decat sa riscam sa omitem randuri valide pe baza unei
    presupuneri de ordine care s-a dovedit gresita.

    Doar starea "descending" permite early-stop. Un fisier "ascending"
    (cele mai vechi randuri primele) e detectat si raportat, dar NU aduce
    niciun beneficiu de early-stop cu aceasta implementare — randurile
    valide (ultimii N ani) sunt la finalul fisierului, deci tot trebuie
    citite secvential toate randurile dinaintea lor.
    """

    def __init__(self, label: str) -> None:
        self.label = label
        self.state = "unknown"  # unknown | descending | ascending | unsorted
        self._last_date: date | None = None

    def observe_chunk(self, dates_in_order: list[date]) -> None:
        if self.state == "unsorted" or not dates_in_order:
            return

        is_non_increasing = all(a >= b for a, b in zip(dates_in_order, dates_in_order[1:]))
        is_non_decreasing = all(a <= b for a, b in zip(dates_in_order, dates_in_order[1:]))
        boundary_ok_desc = self._last_date is None or dates_in_order[0] <= self._last_date
        boundary_ok_asc = self._last_date is None or dates_in_order[0] >= self._last_date

        if self.state == "unknown":
            if is_non_increasing:
                self.state = "descending"
                logger.info("[%s] Ordine cronologica DESCRESCATOARE detectata -> early-stop activ.", self.label)
            elif is_non_decreasing:
                self.state = "ascending"
                logger.info(
                    "[%s] Ordine cronologica CRESCATOARE detectata -> early-stop NU se aplica "
                    "(randurile valide sunt la finalul fisierului).", self.label,
                )
            else:
                self.state = "unsorted"
                logger.info("[%s] Fisier NEordonat cronologic -> early-stop dezactivat, se citeste tot.", self.label)
        elif self.state == "descending":
            if not (is_non_increasing and boundary_ok_desc):
                self.state = "unsorted"
                logger.warning(
                    "[%s] Ordinea descrescatoare asumata a fost VIOLATA -> early-stop dezactivat, "
                    "se proceseaza tot fisierul de aici incolo (siguranta > viteza).", self.label,
                )
        elif self.state == "ascending":
            if not (is_non_decreasing and boundary_ok_asc):
                self.state = "unsorted"
                logger.info(
                    "[%s] Ordinea crescatoare asumata a fost violata (fara impact functional, "
                    "early-stop nu se aplica oricum pentru ascendent).", self.label,
                )

        self._last_date = dates_in_order[-1]

    @property
    def can_early_stop(self) -> bool:
        return self.state == "descending"


class ImportStats:
    """Contor pentru raportul final: detectate / valide / respinse (cu motiv) / scrise."""

    def __init__(self, label: str) -> None:
        self.label = label
        self.rows_seen = 0
        self.rows_valid = 0
        self.rows_written = 0
        self.upsert_errors = 0
        self.rejection_reasons: dict[str, int] = {}
        self.invalid_date_examples: list[str] = []
        self.duplicate_keys_count = 0
        self.duplicate_key_examples: list[str] = []
        self.distinct_teams: set[str] = set()
        self.distinct_leagues: set[str] = set()
        self.dates: list[str] = []
        # [v1.3] Metadate pentru raportul de cutoff / early-stop.
        self.cutoff_date: date | None = None
        self.total_rows_in_file: int = 0
        self.stopped_early: bool = False
        self.rows_at_stop: int = 0
        # [v1.3.1] Necesar ca report() sa poata explica de ce rows_written
        # e 0 in dry-run, in loc sa lase impresia falsa ca nu exista randuri
        # valide de importat.
        self.dry_run: bool = False

    def reject(self, reason: str) -> None:
        self.rejection_reasons[reason] = self.rejection_reasons.get(reason, 0) + 1

    def note_invalid_date_example(self, raw_value: str) -> None:
        if len(self.invalid_date_examples) < MAX_DUPLICATE_EXAMPLES:
            self.invalid_date_examples.append(repr(raw_value))

    def note_duplicate(self, key: str) -> None:
        self.duplicate_keys_count += 1
        if len(self.duplicate_key_examples) < MAX_DUPLICATE_EXAMPLES:
            self.duplicate_key_examples.append(key)

    def report(self) -> None:
        total_rejected = sum(self.rejection_reasons.values())
        before_cutoff_count = self.rejection_reasons.get("before_cutoff", 0)
        other_rejected_count = total_rejected - before_cutoff_count

        logger.info("=== Raport import: %s ===", self.label)
        if self.cutoff_date is not None:
            logger.info("  Cutoff season             : %s", self.cutoff_date.isoformat())
        if self.total_rows_in_file:
            logger.info("  Randuri in fisier (total) : %d", self.total_rows_in_file)
        logger.info("  Randuri citite             : %d%s", self.rows_seen,
                     " (oprit devreme)" if self.stopped_early else "")
        logger.info("  Rows valid                 : %d", self.rows_valid)
        if self.dry_run:
            logger.info("  Rows written               : %d (DRY RUN)", self.rows_written)
        else:
            logger.info("  Rows written               : %d", self.rows_written)
        logger.info("  Rows skipped (before cutoff): %d", before_cutoff_count)
        logger.info("  Rows skipped (alte motive) : %d", other_rejected_count)
        for reason, count in sorted(self.rejection_reasons.items()):
            if reason == "before_cutoff":
                continue
            logger.info("      - %-22s: %d", reason, count)
        if self.invalid_date_examples:
            logger.info("      Exemple date nevalide: %s", self.invalid_date_examples)
        logger.info("  Erori la UPSERT            : %d", self.upsert_errors)
        if self.stopped_early:
            logger.info(
                "  Import oprit prematur la randul %d/%d — fisier detectat ordonat cronologic "
                "descrescator, restul e considerat inainte de cutoff.",
                self.rows_at_stop, self.total_rows_in_file,
            )
        if self.duplicate_keys_count:
            logger.warning(
                "  Chei duplicate (fixture_id / team+data) detectate: %d (exemple: %s)",
                self.duplicate_keys_count, self.duplicate_key_examples,
            )
        logger.info("  Echipe distincte           : %d", len(self.distinct_teams))
        if self.distinct_leagues:
            logger.info("  Competitii/coduri distincte: %d (%s)",
                        len(self.distinct_leagues), sorted(self.distinct_leagues))
        if self.dates:
            logger.info("  Interval date              : %s -> %s",
                        min(self.dates), max(self.dates))


def _classify_csv(summary: CsvSummary) -> str:
    """
    Clasifica un CsvSummary fara sa presupuna numele fisierului.
    Returneaza: "matches", "elo_snapshot", sau "unknown".
    """
    if not summary.missing_required_fields:
        return "matches"

    lower_cols = {c.lower() for c in summary.columns}
    has_elo = "elo" in lower_cols
    has_team_like = bool(lower_cols & {"club", "team"})
    has_date_like = bool(lower_cols & {"date", "snapshot_date"})
    if has_elo and has_team_like and has_date_like:
        return "elo_snapshot"

    return "unknown"


def _generate_fixture_id(home_team: str, away_team: str, kickoff_date: str) -> str:
    """
    Genereaza un fixture_id sintetic, determinist, pentru meciuri fara
    fixture_id nativ (sursa Kaggle, spre deosebire de API-Football).
    Foloseste match_key() existent din mappings.py ca baza.
    """
    key = match_key(home_team, away_team, kickoff_date)
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    return f"kaggle_{digest}"


def _safe_int(value) -> int | None:
    """
    Converteste o valoare (citita ca str din CSV) la int, sau None daca
    lipseste. IMPORTANT: cu dtype=str la citire, valorile lipsa din pandas
    raman float('nan') (nu devin literal stringul "nan"), deci o comparatie
    directa cu "nan" NU le prinde. pd.isna() e singura verificare corecta.
    Nu arunca niciodata exceptie — un camp numeric lipsa nu trebuie sa
    compromita restul randului (teams/data/rezultat raman valide).
    """
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value).strip().lower()
    if text in ("", "nan", "none"):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _safe_str(value) -> str:
    """
    Converteste o valoare la str curat, tratand corect NaN. Aceeasi clasa
    de bug ca la _safe_int(): expresia `nan or ""` evalueaza la `nan` (nu
    la ""), pentru ca un float NaN e "truthy" in Python — deci un simplu
    `(value or "").strip()` arunca AttributeError pe randuri cu date lipsa.
    Returneaza "" pentru orice valoare lipsa/invalida, niciodata exceptie.
    """
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def import_matches(
    summary: CsvSummary,
    dry_run: bool = False,
    limit: int | None = None,
    cutoff_date: date | None = None,
) -> ImportStats:
    """
    Importa fisierul de meciuri (detectat automat) in match_history.
    Coloane asteptate (Kaggle adamgbor): Division, MatchDate, HomeTeam,
    AwayTeam, HomeElo, AwayElo, FTHome, FTAway, FTResult (restul, ignorate
    la acest pas — odds/xG raman pentru un pas viitor, cu aprobare separata).

    Daca `cutoff_date` este furnizat, randurile cu MatchDate < cutoff_date
    sunt respinse (motiv "before_cutoff") si NU ajung in Supabase — vezi
    HISTORICAL_SEASONS_BACK / _compute_season_cutoff_date().

    [v1.3] Daca fisierul e detectat AUTOMAT ca ordonat cronologic
    descrescator (cele mai recente randuri primele), citirea se opreste
    imediat ce un chunk intreg cade sub cutoff_date — vezi _SortOrderTracker.
    """
    stats = ImportStats("Matches -> match_history")
    stats.cutoff_date = cutoff_date
    stats.total_rows_in_file = summary.rows
    stats.dry_run = dry_run

    usecols = [c for c in [
        "Division", "MatchDate", "HomeTeam", "AwayTeam",
        "HomeElo", "AwayElo", "FTHome", "FTAway", "FTResult",
    ] if c in summary.columns]

    missing_cols = {"MatchDate", "HomeTeam", "AwayTeam"} - set(usecols)
    if missing_cols:
        raise KaggleSourceError(
            f"Fisierul de meciuri nu are coloanele obligatorii: {missing_cols}. "
            f"Coloane disponibile: {summary.columns}"
        )

    seen_fixture_ids: set[str] = set()
    rows_processed_total = 0
    order_tracker = _SortOrderTracker("Matches")

    for chunk in pd.read_csv(summary.path, usecols=usecols, dtype=str, chunksize=CHUNK_SIZE):
        if limit is not None and rows_processed_total >= limit:
            break

        chunk["_parsed_date"] = pd.to_datetime(chunk["MatchDate"], errors="coerce")

        # [v1.3] Datele valide, in ordinea din fisier, pentru detectia de sortare.
        valid_dates_in_order = [d.date() for d in chunk["_parsed_date"] if pd.notna(d)]
        order_tracker.observe_chunk(valid_dates_in_order)

        batch_rows: list[dict] = []
        for _, r in chunk.iterrows():
            stats.rows_seen += 1
            rows_processed_total += 1
            if limit is not None and rows_processed_total > limit:
                break

            if stats.rows_seen % PROGRESS_LOG_INTERVAL == 0:
                logger.info(
                    "Progres Matches: %d/%d randuri procesate (%.1f%%)",
                    stats.rows_seen, summary.rows,
                    100 * stats.rows_seen / summary.rows,
                )

            if pd.isna(r["_parsed_date"]):
                stats.reject("invalid_date")
                stats.note_invalid_date_example(r.get("MatchDate"))
                continue

            parsed_date_obj = r["_parsed_date"].date()
            if cutoff_date is not None and parsed_date_obj < cutoff_date:
                stats.reject("before_cutoff")
                continue

            try:
                kickoff_date = r["_parsed_date"].strftime("%Y-%m-%d")
                home_team = normalize_team_name(_safe_str(r["HomeTeam"]))
                away_team = normalize_team_name(_safe_str(r["AwayTeam"]))

                if not home_team or not away_team:
                    stats.reject("missing_team_name")
                    continue

                league_code = _safe_str(r.get("Division")) or None
                fixture_id = _generate_fixture_id(home_team, away_team, kickoff_date)

                if fixture_id in seen_fixture_ids:
                    stats.note_duplicate(fixture_id)
                else:
                    seen_fixture_ids.add(fixture_id)

                row: dict = {
                    "fixture_id": fixture_id,
                    "home_team": home_team,
                    "away_team": away_team,
                    "league": league_code,
                    "kickoff_date": kickoff_date,
                    "actual_result": _safe_str(r.get("FTResult")) or None,
                    "used_for_training": True,
                }

                home_goals = _safe_int(r.get("FTHome"))
                away_goals = _safe_int(r.get("FTAway"))
                home_elo_val = _safe_int(r.get("HomeElo"))
                away_elo_val = _safe_int(r.get("AwayElo"))
                if home_goals is not None:
                    row["actual_home_goals"] = home_goals
                if away_goals is not None:
                    row["actual_away_goals"] = away_goals
                if home_elo_val is not None:
                    row["home_elo"] = home_elo_val
                if away_elo_val is not None:
                    row["away_elo"] = away_elo_val

                batch_rows.append(row)
                stats.rows_valid += 1
                stats.distinct_teams.add(home_team)
                stats.distinct_teams.add(away_team)
                if league_code:
                    stats.distinct_leagues.add(league_code)
                stats.dates.append(kickoff_date)

            except Exception as exc:
                stats.reject("processing_error")
                logger.warning("Rand ignorat (eroare procesare): %s", exc)

        if batch_rows:
            written, errors = _safe_upsert(dry_run, upsert_matches_bulk, batch_rows)
            stats.rows_written += written
            stats.upsert_errors += errors

        # [v1.3] Early-stop: doar daca ordinea descrescatoare e confirmata SI
        # tot chunk-ul curent cade sub cutoff -> restul fisierului e garantat
        # in afara intervalului (fisier descrescator = valorile scad mereu).
        if (
            cutoff_date is not None
            and order_tracker.can_early_stop
            and valid_dates_in_order
            and max(valid_dates_in_order) < cutoff_date
        ):
            stats.stopped_early = True
            stats.rows_at_stop = stats.rows_seen
            logger.info(
                "[Matches] Chunk curent integral inainte de cutoff (%s), ordine descrescatoare "
                "confirmata -> opresc citirea la randul %d/%d.",
                cutoff_date.isoformat(), stats.rows_seen, summary.rows,
            )
            break

    return stats


def import_elo_history(
    summary: CsvSummary,
    dry_run: bool = False,
    limit: int | None = None,
    cutoff_date: date | None = None,
) -> ImportStats:
    """
    Importa fisierul de snapshot-uri ELO (detectat automat) in elo_history.
    Coloana 'country' din Kaggle e salvata TEMPORAR in 'league' (ex. "England",
    "Spain") — nu e o competitie reala, ci o tara. Va fi normalizata corect
    cand se implementeaza normalize_league_name() si o structura de competitii.

    Acelasi `cutoff_date` ca la import_matches() este aplicat aici, pentru
    consistenta (vezi HISTORICAL_SEASONS_BACK). Aceeasi logica de early-stop
    pentru fisiere descrescatoare se aplica independent, pe acest fisier.
    """
    stats = ImportStats("EloRatings -> elo_history")
    stats.cutoff_date = cutoff_date
    stats.total_rows_in_file = summary.rows
    stats.dry_run = dry_run

    lower_to_original = {c.lower(): c for c in summary.columns}
    date_col = lower_to_original.get("date") or lower_to_original.get("snapshot_date")
    team_col = lower_to_original.get("club") or lower_to_original.get("team")
    elo_col = lower_to_original.get("elo")
    country_col = lower_to_original.get("country")

    if not (date_col and team_col and elo_col):
        raise KaggleSourceError(
            f"Fisierul de ELO nu are coloanele necesare (date/club/elo). "
            f"Coloane disponibile: {summary.columns}"
        )

    usecols = [c for c in [date_col, team_col, elo_col, country_col] if c]
    seen_team_dates: dict[str, str] = {}
    rows_processed_total = 0
    order_tracker = _SortOrderTracker("EloRatings")

    for chunk in pd.read_csv(summary.path, usecols=usecols, dtype=str, chunksize=CHUNK_SIZE):
        if limit is not None and rows_processed_total >= limit:
            break

        chunk["_parsed_date"] = pd.to_datetime(chunk[date_col], errors="coerce")

        valid_dates_in_order = [d.date() for d in chunk["_parsed_date"] if pd.notna(d)]
        order_tracker.observe_chunk(valid_dates_in_order)

        batch_rows: list[dict] = []
        for _, r in chunk.iterrows():
            stats.rows_seen += 1
            rows_processed_total += 1
            if limit is not None and rows_processed_total > limit:
                break

            if stats.rows_seen % PROGRESS_LOG_INTERVAL == 0:
                logger.info(
                    "Progres EloRatings: %d/%d randuri procesate (%.1f%%)",
                    stats.rows_seen, summary.rows,
                    100 * stats.rows_seen / summary.rows,
                )

            if pd.isna(r["_parsed_date"]):
                stats.reject("invalid_date")
                stats.note_invalid_date_example(r.get(date_col))
                continue

            parsed_date_obj = r["_parsed_date"].date()
            if cutoff_date is not None and parsed_date_obj < cutoff_date:
                stats.reject("before_cutoff")
                continue

            try:
                snapshot_date = r["_parsed_date"].strftime("%Y-%m-%d")
                team = normalize_team_name(_safe_str(r[team_col]))

                if not team:
                    stats.reject("missing_team_name")
                    continue

                elo_value = _safe_int(r.get(elo_col))
                if elo_value is None:
                    stats.reject("missing_elo_value")
                    continue
                country_value = _safe_str(r.get(country_col)) if country_col else ""

                dedup_key = f"{team}||{snapshot_date}"
                current_raw = _safe_str(r[team_col])
                if dedup_key in seen_team_dates:
                    first_raw = seen_team_dates[dedup_key]
                    if first_raw == current_raw:
                        stats.note_duplicate(f"{dedup_key} [duplicat real, raw identic: '{current_raw}']")
                    else:
                        stats.note_duplicate(
                            f"{dedup_key} [COLIZIUNE normalizare: '{first_raw}' vs '{current_raw}']"
                        )
                else:
                    seen_team_dates[dedup_key] = current_raw

                row = {
                    "team": team,
                    "elo": elo_value,
                    "snapshot_date": snapshot_date,
                    "source": "kaggle",
                }
                if country_value:
                    # Temporar: 'country' (ex. "England") stocat direct in 'league'.
                    # NU e o competitie reala — va fi normalizat ulterior.
                    row["league"] = country_value
                    stats.distinct_leagues.add(country_value)

                batch_rows.append(row)
                stats.rows_valid += 1
                stats.distinct_teams.add(team)
                stats.dates.append(snapshot_date)

            except Exception as exc:
                stats.reject("processing_error")
                logger.warning("Rand ELO ignorat (eroare procesare): %s", exc)

        if batch_rows:
            written, errors = _safe_upsert(dry_run, upsert_elo_history_bulk, batch_rows)
            stats.rows_written += written
            stats.upsert_errors += errors

        if (
            cutoff_date is not None
            and order_tracker.can_early_stop
            and valid_dates_in_order
            and max(valid_dates_in_order) < cutoff_date
        ):
            stats.stopped_early = True
            stats.rows_at_stop = stats.rows_seen
            logger.info(
                "[EloRatings] Chunk curent integral inainte de cutoff (%s), ordine descrescatoare "
                "confirmata -> opresc citirea la randul %d/%d.",
                cutoff_date.isoformat(), stats.rows_seen, summary.rows,
            )
            break

    return stats


def _safe_upsert(dry_run: bool, upsert_fn: Callable[[list[dict]], tuple[int, int]],
                  rows: list[dict]) -> tuple[int, int]:
    """
    Singurul punct din tot fisierul prin care se scrie in Supabase.
    Daca dry_run e True, NU apeleaza niciodata upsert_fn — returneaza (0, 0)
    necondiționat. Aceasta e garantia ca dry-run nu produce nicio scriere reala.
    """
    if dry_run:
        return 0, 0
    return upsert_fn(rows)


def run(dry_run: bool = False, limit: int | None = None) -> None:
    cutoff_date = _compute_season_cutoff_date(HISTORICAL_SEASONS_BACK)
    logger.info(
        "Import istoric limitat la ultimele %d sezoane — cutoff season: %s "
        "(randuri cu data < cutoff sunt respinse).",
        HISTORICAL_SEASONS_BACK, cutoff_date.isoformat(),
    )

    logger.info("Inspectez dataset-ul principal Kaggle inainte de import...")
    inspection = inspect_dataset(MAIN_DATASET)

    matches_summary: CsvSummary | None = None
    elo_summary: CsvSummary | None = None

    for summary in inspection.csv_files:
        kind = _classify_csv(summary)
        logger.info("Fisier '%s' clasificat ca: %s", summary.filename, kind)
        if kind == "matches" and matches_summary is None:
            matches_summary = summary
        elif kind == "elo_snapshot" and elo_summary is None:
            elo_summary = summary
        elif kind == "unknown":
            logger.warning(
                "Fisierul '%s' nu a putut fi clasificat automat — este SARIT. "
                "Coloane: %s", summary.filename, summary.columns,
            )

    if matches_summary is None:
        raise KaggleSourceError(
            "Niciun fisier de meciuri identificat in dataset-ul principal. "
            "Verifica daca structura Kaggle s-a schimbat."
        )
    if elo_summary is None:
        logger.warning(
            "Niciun fisier de snapshot ELO identificat — se importa doar meciurile."
        )

    if dry_run:
        logger.info("=== DRY RUN — validare completa, ZERO scrieri in Supabase ===")

    match_stats = import_matches(matches_summary, dry_run=dry_run, limit=limit, cutoff_date=cutoff_date)
    match_stats.report()

    elo_stats: ImportStats | None = None
    if elo_summary is not None:
        elo_stats = import_elo_history(elo_summary, dry_run=dry_run, limit=limit, cutoff_date=cutoff_date)
        elo_stats.report()

    # Inregistrare auditabila a rularii, refolosind functia deja existenta
    # upsert_sync_status(). Respecta ACEEASI garantie de zero-scriere in
    # dry-run — nu se apeleaza deloc daca dry_run e True.
    if not dry_run:
        total_written = match_stats.rows_written + (elo_stats.rows_written if elo_stats else 0)
        total_errors = match_stats.upsert_errors + (elo_stats.upsert_errors if elo_stats else 0)
        status = "ok" if total_errors == 0 else "partial_errors"
        notes = (
            f"matches_valid={match_stats.rows_valid}, matches_written={match_stats.rows_written}, "
            f"matches_skipped_before_cutoff={match_stats.rejection_reasons.get('before_cutoff', 0)}, "
            f"matches_stopped_early={match_stats.stopped_early}, "
            f"elo_valid={elo_stats.rows_valid if elo_stats else 0}, "
            f"elo_written={elo_stats.rows_written if elo_stats else 0}, "
            f"elo_skipped_before_cutoff={elo_stats.rejection_reasons.get('before_cutoff', 0) if elo_stats else 0}, "
            f"elo_stopped_early={elo_stats.stopped_early if elo_stats else False}, "
            f"limit={limit or 'none'}, cutoff_season={cutoff_date.isoformat()}, "
            f"seasons_back={HISTORICAL_SEASONS_BACK}"
        )
        ok = upsert_sync_status(
            source="kaggle_historical",
            last_sync=datetime.now(timezone.utc).isoformat(),
            matches_added=total_written,
            matches_updated=0,
            status=status,
            notes=notes,
        )
        if not ok:
            logger.warning("Nu s-a putut scrie in sync_status (import-ul in sine a mers OK).")
    else:
        logger.info("DRY RUN — sync_status NU este atins (garantie zero-scriere).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import istoric Kaggle -> Supabase")
    parser.add_argument("--dry-run", action="store_true", help="Validare completa, ZERO scrieri in Supabase.")
    parser.add_argument("--limit", type=int, default=None, help="Limiteaza numarul de randuri procesate per fisier (util pentru testare). Omis = import complet.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    try:
        run(dry_run=args.dry_run, limit=args.limit)
    except KaggleSourceError as exc:
        logger.error("Import esuat: %s", exc)
        raise SystemExit(1) from exc
