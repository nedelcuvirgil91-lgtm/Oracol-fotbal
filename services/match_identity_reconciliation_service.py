"""
================================================================================
FOOTBALL ORACLE — Match Identity Reconciliation Service
================================================================================
Implementeaza algoritmul din ID-025-01 (Canonical Row Selection) si motorul
de descoperire/raportare din ID-025-02 (Historical Reconciliation Engine),
consumate de strategia de migrare ADR-025.

Scop STRICT in aceasta faza (Faza 2, ADR-025): DRY-RUN. Modul EXECUTE (scriere
efectiva pe match_history — Faza 3/4 din ADR-025) NU e implementat aici — vezi
`run()`. Adaugarea lui necesita autorizare separata, explicita, per Phase Gate
(ADR-025, "Strategie de migrare"). Codul de decizie (discover/clasificare/
selectie/merge) e comun celor doua moduri prin constructie — DRY-RUN foloseste
exact acelasi cod, doar nu scrie (ID-025-02, garantie explicita).

Fluxul (per grup de duplicate, ID-025-01):
  1. Clasificare HARD CONFLICT (actual_result/actual_home_goals/actual_away_goals)
     — o discrepanta reala exclude tot grupul, fara efect lateral.
  2. Rezolvarea sursei fiecarui rand (`resolve_source`, din prefixul fixture_id)
     — sursa necunoscuta exclude tot grupul (Regula #8 North Star).
  3. Selectia randului canonic — rang minim (SourceTrustProvider), tiebreak id minim.
  4. Merge non-destructiv camp cu camp (monoton, NULL -> valoare, niciodata invers).
  5. Marcare trasabila a randurilor necanonice (superseded_by/at/reason) — DOAR
     in modul EXECUTE, neimplementat inca.
================================================================================
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from mappings import match_key
from source_trust_policy import SourceTrustProvider

logger = logging.getLogger("FootballOracle.MatchIdentityReconciliationService")

# Rezolvarea sursei unui rand — componenta separata, inlocuibila (ID-025-01,
# Pasul 1). NU face parte din Source Trust Policy (source_trust_policy.py).
FIXTURE_ID_PREFIX_TO_SOURCE: dict[str, str] = {
    "fd_": "football_data",
    "espn_": "espn",
    "odds_": "odds_api",
    "kaggle_": "kaggle_historical",
}

# Camp care definesc identitatea rezultatului unui meci — discrepanta aici
# opreste reconcilierea automata a intregului grup (ID-025-01, HARD CONFLICT).
HARD_CONFLICT_COLUMNS: list[str] = [
    "actual_result", "actual_home_goals", "actual_away_goals",
]

# Toate coloanele eligibile pentru merge non-destructiv (ID-025-01, Pasul 3) —
# FEATURE_COLUMNS (ml_predictor.py) + coloanele brute de rezultat/statistici.
# Exclude: cheia naturala (home_team/away_team/kickoff_date), identitate opaca
# (id/fixture_id/league), audit (created_at/superseded_*), HARD_CONFLICT_COLUMNS.
MERGE_COLUMNS: list[str] = [
    "home_xg_pred", "away_xg_pred",
    "home_offensive_rating", "home_defensive_rating",
    "away_offensive_rating", "away_defensive_rating",
    "home_form_score", "away_form_score",
    "home_elo", "away_elo",
    "h2h_modifier", "h2h_meetings",
    "weather_penalty",
    "home_data_quality", "away_data_quality",
    "prob_home_pred", "prob_draw_pred", "prob_away_pred",
    "mc_prob_home", "mc_prob_draw", "mc_prob_away",
    "used_for_training", "backfill_done",
    "home_xg_actual", "away_xg_actual",
    "home_possession", "away_possession",
    "home_shots", "away_shots",
    "home_shots_on_target", "away_shots_on_target",
    "stats_source",
    "home_fouls", "away_fouls",
    "home_corners", "away_corners",
    "home_yellow_cards", "away_yellow_cards",
    "home_red_cards", "away_red_cards",
    "home_ht_goals", "away_ht_goals",
    "home_corner_avg_recent", "away_corner_avg_recent",
    "home_card_avg_recent", "away_card_avg_recent",
    "home_foul_avg_recent", "away_foul_avg_recent",
    "home_shot_avg_recent", "away_shot_avg_recent",
    "home_elo_after", "away_elo_after",
]


def resolve_source(fixture_id: str | None) -> str | None:
    """Sursa unui rand, derivata din prefixul fixture_id (ID-025-01, Pasul 1).
    None daca prefixul nu e recunoscut — grupul e exclus (sursa necunoscuta)."""
    if not fixture_id:
        return None
    for prefix, source in FIXTURE_ID_PREFIX_TO_SOURCE.items():
        if fixture_id.startswith(prefix):
            return source
    return None


@dataclass
class GroupDecision:
    """Rezultatul determinist al algoritmului (ID-025-01) pentru UN grup."""
    group_key: str
    excluded_reason: str | None = None  # "hard_conflict" | "unknown_source" | None
    canonical_id: Any = None
    canonical_source: str | None = None
    noncanonical: list[dict] = field(default_factory=list)  # [{"id","source","rank","reason"}]
    merge_updates: dict[str, Any] = field(default_factory=dict)  # camp -> valoare noua (canonical)


def _classify_hard_conflict(rows: list[dict]) -> bool:
    for col in HARD_CONFLICT_COLUMNS:
        values = {r[col] for r in rows if r.get(col) is not None}
        if len(values) > 1:
            return True
    return False


def process_group(rows: list[dict]) -> GroupDecision:
    """
    Algoritmul determinist ID-025-01 (Pasii 1-4), aplicat unui singur grup de
    randuri duplicate (aceeasi cheie naturala). Pura — fara I/O, identica in
    DRY-RUN si EXECUTE (garantia din ID-025-02).

    `rows`: fiecare dict trebuie sa contina minim "id", "fixture_id", si toate
    HARD_CONFLICT_COLUMNS + MERGE_COLUMNS relevante.
    """
    group_key = match_key(
        rows[0].get("home_team", ""), rows[0].get("away_team", ""),
        rows[0].get("kickoff_date", ""),
    )
    decision = GroupDecision(group_key=group_key)

    if _classify_hard_conflict(rows):
        decision.excluded_reason = "hard_conflict"
        return decision

    resolved = [(r, resolve_source(r.get("fixture_id"))) for r in rows]
    if any(source is None for _, source in resolved):
        decision.excluded_reason = "unknown_source"
        return decision

    ranked = sorted(
        ((r, source, SourceTrustProvider.get_rank(source)) for r, source in resolved),
        key=lambda t: (t[2], r_id(t[0])),
    )
    canonical, canonical_source, canonical_rank = ranked[0]
    noncanonical_ranked = ranked[1:]

    decision.canonical_id = canonical.get("id")
    decision.canonical_source = canonical_source

    # Pasul 3 — merge non-destructiv, camp cu camp (monoton, NULL -> valoare).
    for col in MERGE_COLUMNS:
        if canonical.get(col) is not None:
            continue  # Case 1 — Writer Protection, niciodata atins.
        candidates = [
            (row, rank) for row, _, rank in noncanonical_ranked
            if row.get(col) is not None
        ]
        if not candidates:
            continue  # Case 4 — nimeni nu are valoare, ramane NULL.
        # Case 2 (un singur candidat) si Case 3 (SOFT CONFLICT — mai multi
        # candidati, castiga rangul de incredere cel mai mic) — aceeasi regula.
        winner_row, _ = min(candidates, key=lambda c: c[1])
        decision.merge_updates[col] = winner_row[col]

    # Pasul 4 — marcare trasabila (doar calculata aici; scrisa doar in EXECUTE).
    for row, source, rank in noncanonical_ranked:
        decision.noncanonical.append({
            "id": row.get("id"),
            "source": source,
            "reason": (
                f"duplicate_cross_provider: "
                f"canonical={canonical.get('fixture_id')} (rank={canonical_rank}), "
                f"superseded={row.get('fixture_id')} (rank={rank})"
            ),
        })

    return decision


def r_id(row: dict) -> Any:
    """Tiebreak de ultima instanta la egalitate de rang (ID-025-01, Pasul 2)."""
    return row.get("id")


@dataclass
class ReconciliationReport:
    """Raportul unei rulari (DRY-RUN sau EXECUTE) — campurile minime cerute
    de ID-025-02, sectiunea "Raportare"."""
    total_groups: int = 0
    excluded_hard_conflict: list[str] = field(default_factory=list)
    excluded_unknown_source: list[str] = field(default_factory=list)
    reconciled_groups: int = 0
    write_errors: list[str] = field(default_factory=list)  # doar EXECUTE
    columns_populated: dict[str, int] = field(default_factory=dict)
    canonical_rows_with_any_fill: int = 0
    total_rows_affected: int = 0  # canonice completate + necanonice marcate

    @property
    def excluded_hard_conflict_count(self) -> int:
        return len(self.excluded_hard_conflict)

    @property
    def excluded_unknown_source_count(self) -> int:
        return len(self.excluded_unknown_source)


class MatchIdentityReconciliationService:
    """
    Motorul de descoperire (ID-025-02). Discovery + orchestrare per-grup;
    decizia in sine (`process_group`) e delegata functiei pure de mai sus.
    """

    def __init__(self, supabase_client=None):
        if supabase_client is None:
            import supabase_client as sb
            supabase_client = sb
        self._sb = supabase_client

    def _fetch_key_index(self) -> dict[str, list[dict]]:
        """Descoperirea grupurilor (ID-025-02) — id/fixture_id/home_team/
        away_team/kickoff_date pentru tot corpusul, grupat pe match_key()
        (aceeasi functie folosita de restul aplicatiei — nu se reimplementeaza
        normalizarea). Exclude randurile deja reconciliate (superseded_by IS
        NOT NULL) — un grup deja marcat nu se reevalueaza (ID-025-01)."""
        client = self._sb.get_client()
        index: dict[str, list[dict]] = {}
        offset, page_size = 0, 1000
        while True:
            res = (
                client.table("match_history")
                .select("id,fixture_id,home_team,away_team,kickoff_date")
                .is_("superseded_by", "null")
                .range(offset, offset + page_size - 1)
                .execute()
            )
            batch = res.data or []
            for row in batch:
                key = match_key(row.get("home_team", ""), row.get("away_team", ""), row.get("kickoff_date", ""))
                index.setdefault(key, []).append(row)
            if len(batch) < page_size:
                break
            offset += page_size
        return index

    def _fetch_full_rows(self, ids: list[Any]) -> dict[Any, dict]:
        """A doua trecere — doar pentru randurile din grupuri cu duplicate,
        aduce toate coloanele necesare deciziei (HARD_CONFLICT_COLUMNS +
        MERGE_COLUMNS)."""
        client = self._sb.get_client()
        select_cols = ",".join(
            ["id", "fixture_id", "home_team", "away_team", "kickoff_date"]
            + HARD_CONFLICT_COLUMNS + MERGE_COLUMNS
        )
        rows: dict[Any, dict] = {}
        batch_size = 200
        for i in range(0, len(ids), batch_size):
            batch_ids = ids[i:i + batch_size]
            res = (
                client.table("match_history")
                .select(select_cols)
                .in_("id", batch_ids)
                .execute()
            )
            for row in (res.data or []):
                rows[row["id"]] = row
        return rows

    def run(self, dry_run: bool = True) -> ReconciliationReport:
        if not dry_run:
            raise NotImplementedError(
                "Modul EXECUTE nu e autorizat/implementat in Faza 2 (ADR-025) — "
                "necesita aprobare explicita separata pentru Faza 3 (pilot) sau "
                "Faza 4 (completa), conform Phase Gate din ADR-025."
            )

        report = ReconciliationReport()
        key_index = self._fetch_key_index()
        duplicate_groups = {k: v for k, v in key_index.items() if len(v) > 1}
        report.total_groups = len(duplicate_groups)

        all_ids = [row["id"] for rows in duplicate_groups.values() for row in rows]
        full_rows_by_id = self._fetch_full_rows(all_ids)

        for key, stub_rows in duplicate_groups.items():
            full_rows = [full_rows_by_id[r["id"]] for r in stub_rows if r["id"] in full_rows_by_id]
            if len(full_rows) < 2:
                continue
            decision = process_group(full_rows)

            if decision.excluded_reason == "hard_conflict":
                report.excluded_hard_conflict.append(key)
                continue
            if decision.excluded_reason == "unknown_source":
                report.excluded_unknown_source.append(key)
                continue

            report.reconciled_groups += 1
            if decision.merge_updates:
                report.canonical_rows_with_any_fill += 1
            for col in decision.merge_updates:
                report.columns_populated[col] = report.columns_populated.get(col, 0) + 1

        report.total_rows_affected = report.reconciled_groups + report.canonical_rows_with_any_fill

        logger.info(
            "[MatchIdentityReconciliation] DRY-RUN: %d grupuri, %d reconciliate, "
            "%d hard_conflict, %d sursa_necunoscuta, %d randuri_canonice_cu_completare",
            report.total_groups, report.reconciled_groups,
            report.excluded_hard_conflict_count, report.excluded_unknown_source_count,
            report.canonical_rows_with_any_fill,
        )
        return report
