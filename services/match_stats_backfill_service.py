"""
================================================================================
FOOTBALL ORACLE — Backfill Match Stats Service (istoric)
================================================================================
Module: services/match_stats_backfill_service.py

Companion la BackfillOddsService (services/odds_backfill_service.py) —
reutilizează exact același matching fail-closed (dată + echipe normalizate +
verificare obligatorie de scor), dar scrie direct pe `match_history`, prin
gating strict per-coloană NULL (tiparul din sync/backfill_features.py), nu
printr-un RPC separat — coloanele țintă (home_shots, home_fouls etc.) trăiesc
deja pe `match_history`, nu într-un tabel dedicat.

Serviciu generic — `columns` (lista de coloane match_history de completat) e
singurul parametru care variază între Task 1 (shots) și Task 2 (corners/
fouls/cartonașe/HT) — zero cod nou între etape.

Scriere non-destructivă (Regula #13 — Protecția Writer-ilor): pentru fiecare
meci potrivit, se scrie STRICT intersecția dintre (a) coloanele urmărite care
sunt azi NULL în match_history și (b) coloanele pentru care sursa are o
valoare reală. O coloană deja populată nu e niciodată atinsă.
================================================================================
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

from mappings import normalize_team_name

logger = logging.getLogger("FootballOracle.MatchStatsBackfillService")


@dataclass
class MatchStatsBackfillMetrics:
    """Aceiași indicatori standard folosiți la BackfillOddsService, plus
    `already_complete` (meci potrivit dar fără nicio coloană de completat)
    și `columns_populated` (câte valori s-au scris per coloană)."""
    source_matches_found: int = 0
    matched: int = 0
    rejected_no_match: int = 0
    rejected_ambiguous_match: int = 0
    rejected_score_mismatch: int = 0
    already_complete: int = 0
    written_ok: int = 0
    write_errors: int = 0
    columns_populated: dict[str, int] = field(default_factory=dict)
    rejection_details: list[str] = field(default_factory=list)

    @property
    def match_rate_pct(self) -> float:
        if self.source_matches_found == 0:
            return 0.0
        return round(100.0 * self.matched / self.source_matches_found, 2)


class MatchStatsBackfillService:
    """
    provider:  numele sursei (ex. "football-data.co.uk")
    division:  codul competiției în sursă (ex. "E0") — opac pentru serviciu
    importer:  callable(division, season, min_date) -> list[dict], vezi
               sync/sources/football_data_co_uk.py:fetch_football_data_co_uk_match_stats
    league:    numele canonic Football Oracle — singurul loc specific unei ligi
    columns:   coloanele match_history de completat în această rulare
               (ex. ["home_shots","away_shots","home_shots_on_target","away_shots_on_target"])
    """

    IMPORT_VERSION = "MatchStatsBackfill_v1"

    def __init__(
        self,
        provider: str,
        division: str,
        season: str | None,
        importer: Callable[[str, str | None, str], list[dict]],
        league: str,
        columns: list[str],
        min_date: str = "2000-01-01",
        supabase_client=None,
    ):
        self.provider = provider
        self.division = division
        self.season = season
        self.importer = importer
        self.league = league
        self.columns = columns
        self.min_date = min_date
        if supabase_client is None:
            import supabase_client as sb
            supabase_client = sb
        self._sb = supabase_client

    def _fetch_match_history_candidates(self) -> list[dict]:
        client = self._sb.get_client()
        select_cols = (
            "id,fixture_id,home_team,away_team,kickoff_date,"
            "actual_home_goals,actual_away_goals,stats_source," + ",".join(self.columns)
        )
        rows: list[dict] = []
        offset, page_size = 0, 1000
        while True:
            res = (
                client.table("match_history")
                .select(select_cols)
                .eq("league", self.league)
                .gte("kickoff_date", self.min_date)
                .not_.is_("actual_result", "null")
                .range(offset, offset + page_size - 1)
                .execute()
            )
            batch = res.data or []
            rows.extend(batch)
            if len(batch) < page_size:
                break
            offset += page_size
        return rows

    def run(self, dry_run: bool = False) -> MatchStatsBackfillMetrics:
        metrics = MatchStatsBackfillMetrics()

        source_rows = self.importer(self.division, self.season, self.min_date)
        metrics.source_matches_found = len(source_rows)

        candidates = self._fetch_match_history_candidates()
        index: dict[tuple, list[dict]] = {}
        for c in candidates:
            key = (
                str(c["kickoff_date"])[:10],
                normalize_team_name(c["home_team"]),
                normalize_team_name(c["away_team"]),
            )
            index.setdefault(key, []).append(c)

        for row in source_rows:
            lookup_key = (
                row["match_date"],
                normalize_team_name(row["home_team_raw"]),
                normalize_team_name(row["away_team_raw"]),
            )
            found = index.get(lookup_key, [])

            if len(found) == 0:
                metrics.rejected_no_match += 1
                metrics.rejection_details.append(
                    f"no_match: {row['match_date']} {row['home_team_raw']} vs {row['away_team_raw']}"
                )
                continue
            if len(found) > 1:
                metrics.rejected_ambiguous_match += 1
                metrics.rejection_details.append(
                    f"ambiguous: {row['match_date']} {row['home_team_raw']} vs {row['away_team_raw']} "
                    f"({len(found)} candidati in match_history)"
                )
                continue

            candidate = found[0]
            if (candidate["actual_home_goals"], candidate["actual_away_goals"]) != (
                row["home_goals"], row["away_goals"]
            ):
                metrics.rejected_score_mismatch += 1
                metrics.rejection_details.append(
                    f"score_mismatch: {row['match_date']} {row['home_team_raw']} vs {row['away_team_raw']} "
                    f"sursa={row['home_goals']}-{row['away_goals']} "
                    f"match_history={candidate['actual_home_goals']}-{candidate['actual_away_goals']}"
                )
                continue

            metrics.matched += 1

            missing_in_db = {c for c in self.columns if candidate.get(c) is None}
            to_write = {c: row[c] for c in self.columns if c in missing_in_db and c in row}

            if not to_write:
                metrics.already_complete += 1
                continue

            # [FIX Pasul 3, Master Repair Plan] Cei 3 ceilalți writer de
            # statistici (freelivefootball, soccerfootballinfo, flashscore)
            # scriu `stats_source` odată cu valorile — acest writer nu o
            # făcea, deși e singurul care completează coloane pe rânduri
            # deja existente (de la football-data.org). Aceeași gardă
            # non-destructivă: scris DOAR dacă e azi NULL, DOAR când chiar
            # se scrie o valoare noua (to_write non-gol).
            if candidate.get("stats_source") is None:
                to_write["stats_source"] = self.provider

            if dry_run:
                metrics.written_ok += 1
                for c in to_write:
                    metrics.columns_populated[c] = metrics.columns_populated.get(c, 0) + 1
                continue

            try:
                wrote = self._write(candidate["id"], to_write)
                if wrote:
                    metrics.written_ok += 1
                    for c in to_write:
                        metrics.columns_populated[c] = metrics.columns_populated.get(c, 0) + 1
            except Exception as exc:
                metrics.write_errors += 1
                metrics.rejection_details.append(f"write_error: id={candidate['id']}: {exc}")
                logger.error("[MatchStatsBackfill] scriere esuata id=%s: %s", candidate["id"], exc)

        logger.info(
            "[MatchStatsBackfill] provider=%s division=%s league=%s columns=%s dry_run=%s: "
            "meciuri_sursa=%d potrivite=%d (%.2f%%) deja_complete=%d fara_potrivire=%d "
            "ambigue=%d scor_diferit=%d scrise=%d erori=%d",
            self.provider, self.division, self.league, self.columns, dry_run,
            metrics.source_matches_found, metrics.matched, metrics.match_rate_pct,
            metrics.already_complete, metrics.rejected_no_match, metrics.rejected_ambiguous_match,
            metrics.rejected_score_mismatch, metrics.written_ok, metrics.write_errors,
        )
        return metrics

    def _write(self, match_id: int, values: dict) -> bool:
        client = self._sb.get_client()
        res = client.table("match_history").update(values).eq("id", match_id).execute()
        return bool(res.data)
