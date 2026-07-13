"""
================================================================================
FOOTBALL ORACLE — Backfill Odds Service (istoric)
================================================================================
Module: services/odds_backfill_service.py

Companion la OddsPersistenceService (live) — vezi
docs/03_ENGINE/ODDS_PERSISTENCE_DESIGN.md (Frozen) și
docs/03_ENGINE/ODDS_INFRASTRUCTURE_DESIGN_2026-07-13.md + ADR-010.

Serviciu generic — NU conține nicio ramură de cod specifică unei ligi.
Singurul loc unde apare o valoare specifică unei ligi e la instanțiere
(parametrul `league`, folosit doar pentru interogarea match_history).

Reutilizează exact primitiva de scriere deja Frozen (RPC
`upsert_odds_snapshot`, generalizat pentru proveniență prin ADR-010) —
niciun mecanism nou de scriere, niciun trigger nou.

Matching fail-closed (nu best-effort): cheie (dată, echipe normalizate),
plus verificare obligatorie de scor. Zero potriviri, potriviri ambigue,
sau scor neconcordant -> rândul e sărit, motivul înregistrat explicit.
================================================================================
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from mappings import normalize_team_name

logger = logging.getLogger("FootballOracle.BackfillOddsService")


@dataclass
class BackfillMetrics:
    """Indicatori standard — devin formatul de raportare pentru orice import viitor."""
    source_matches_found: int = 0        # meciuri unice găsite în sursă (nu rânduri per bookmaker)
    source_rows_found: int = 0           # rânduri (meci, bookmaker) găsite în sursă
    matched: int = 0
    rejected_no_match: int = 0
    rejected_ambiguous_match: int = 0
    rejected_score_mismatch: int = 0
    written_ok: int = 0
    write_errors: int = 0
    rejection_details: list[str] = field(default_factory=list)

    @property
    def match_rate_pct(self) -> float:
        if self.source_rows_found == 0:
            return 0.0
        return round(100.0 * self.matched / self.source_rows_found, 2)


class BackfillOddsService:
    """
    Interfață generică de backfill istoric de cote.

    provider: numele sursei (ex. "football-data.co.uk")
    division: codul competiției în sursă (ex. "E0") — opac pentru serviciu
    season:   rezervat pentru importere viitoare bazate pe fișiere per-sezon
    importer: callable(division, season, min_date) -> list[dict], vezi
              sync/sources/football_data_co_uk.py pentru contractul exact
    league:   numele canonic Football Oracle (ex. "Premier League") — singurul
              loc unde apare o valoare specifică unei ligi, mereu din configurație
    """

    IMPORT_VERSION = "OddsBackfill_v1"

    def __init__(
        self,
        provider: str,
        division: str,
        season: str | None,
        importer: Callable[[str, str | None, str], list[dict]],
        league: str,
        years_back: int = 5,
        supabase_client=None,
    ):
        self.provider = provider
        self.division = division
        self.season = season
        self.importer = importer
        self.league = league
        self.years_back = years_back
        if supabase_client is None:
            import supabase_client as sb
            supabase_client = sb
        self._sb = supabase_client

    def _min_date(self) -> str:
        today = datetime.now(timezone.utc).date()
        return today.replace(year=today.year - self.years_back).isoformat()

    def _fetch_match_history_candidates(self, min_date: str) -> list[dict]:
        client = self._sb.get_client()
        rows: list[dict] = []
        offset, page_size = 0, 1000
        while True:
            res = (
                client.table("match_history")
                .select("id,fixture_id,home_team,away_team,kickoff_date,"
                        "actual_home_goals,actual_away_goals")
                .eq("league", self.league)
                .gte("kickoff_date", min_date)
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

    def run(self, dry_run: bool = False) -> BackfillMetrics:
        metrics = BackfillMetrics()
        min_date = self._min_date()

        source_rows = self.importer(self.division, self.season, min_date)
        metrics.source_rows_found = len(source_rows)

        candidates = self._fetch_match_history_candidates(min_date)

        # Index pe (dată, echipă acasă normalizată, echipă deplasare normalizată).
        # Nume canonic de ligă -> deja garantat de filtrul .eq("league", ...).
        index: dict[tuple, list[dict]] = {}
        for c in candidates:
            key = (
                str(c["kickoff_date"])[:10],
                normalize_team_name(c["home_team"]),
                normalize_team_name(c["away_team"]),
            )
            index.setdefault(key, []).append(c)

        seen_matches: set[tuple] = set()
        for row in source_rows:
            match_id_key = (row["match_date"], row["home_team_raw"], row["away_team_raw"])
            if match_id_key not in seen_matches:
                seen_matches.add(match_id_key)
                metrics.source_matches_found += 1

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
            if dry_run:
                metrics.written_ok += 1
                continue
            try:
                wrote = self._write(candidate["fixture_id"], row)
                if wrote:
                    metrics.written_ok += 1
            except Exception as exc:
                metrics.write_errors += 1
                metrics.rejection_details.append(
                    f"write_error: {candidate['fixture_id']}/{row['bookmaker']}: {exc}"
                )
                logger.error(
                    "[BackfillOdds] scriere esuata %s/%s: %s",
                    candidate["fixture_id"], row["bookmaker"], exc,
                )

        logger.info(
            "[BackfillOdds] provider=%s division=%s league=%s dry_run=%s: "
            "meciuri_sursa=%d randuri_sursa=%d potrivite=%d (%.2f%%) "
            "fara_potrivire=%d ambigue=%d scor_diferit=%d scrise=%d erori=%d",
            self.provider, self.division, self.league, dry_run,
            metrics.source_matches_found, metrics.source_rows_found,
            metrics.matched, metrics.match_rate_pct,
            metrics.rejected_no_match, metrics.rejected_ambiguous_match,
            metrics.rejected_score_mismatch, metrics.written_ok, metrics.write_errors,
        )
        return metrics

    def _write(self, fixture_id: str, row: dict) -> bool:
        client = self._sb.get_client()
        now_iso = datetime.now(timezone.utc).isoformat()
        res = client.rpc("upsert_odds_snapshot", {
            "p_fixture_id": fixture_id,
            "p_bookmaker": row["bookmaker"],
            "p_home": row["price_home"],
            "p_draw": row["price_draw"],
            "p_away": row["price_away"],
            "p_now": now_iso,
            "p_provider": self.provider,
            "p_import_type": "historical_backfill",
            "p_import_version": self.IMPORT_VERSION,
            "p_source_hash": row["source_hash"],
            "p_source_url": row.get("source_url"),
        }).execute()
        return bool(res.data)
