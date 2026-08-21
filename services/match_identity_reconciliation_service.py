"""
================================================================================
FOOTBALL ORACLE — Match Identity Reconciliation Service
================================================================================
Implementeaza algoritmul din ID-025-01 (Canonical Row Selection) si motorul
de descoperire/raportare din ID-025-02 (Historical Reconciliation Engine),
consumate de strategia de migrare ADR-025.

[ADR-059, 2026-08-21] RECONCILIEREA MARCHEAZA, NU CONTOPESTE. Pasul de merge
non-destructiv (ID-025-01, Pasul 3) a fost ELIMINAT: reconcilierea nu scrie
nicio coloana de date, pe niciun rand. Singurele coloane pe care le scrie sunt
`superseded_by`/`superseded_at`/`superseded_reason`, exclusiv pe randul
NECANONIC — randul canonic nu e atins de niciun octet.

De ce: toate cele 52 de coloane candidate au un owner unic de scriere
(ADR-036) — verificat mecanic din cod, multimea coloanelor fara owner e vida,
deci nu exista subset sigur. Si, dincolo de guvernanta: orice valoare de pe un
rand necanonic a fost calculata sub identitatea FRAGMENTATA, iar RPC-ul si
`run_backfill` fiind NULL-only, copierea ei ar BLOCA definitiv recalculul
corect al owner-ului legitim. Diferenta de date se RAPORTEAZA (cu owner-ul care
o poate regenera), nu se scrie.

Modul EXECUTE e autorizat de ADR-059 si implementat aici (`run(dry_run=False)`).
Executia in sine ramane gatata per Phase Gate (ADR-025): pilot pe subset
(`limit_groups`) inainte de rulare completa. Codul de decizie e comun celor
doua moduri prin constructie — DRY-RUN foloseste exact acelasi cod, doar nu
scrie (ID-025-02, garantie explicita).

Fluxul (per grup de duplicate, ID-025-01, amendat de ADR-059):
  1. Clasificare HARD CONFLICT (actual_result/actual_home_goals/actual_away_goals)
     — o discrepanta reala exclude tot grupul, fara efect lateral.
  2. Rezolvarea sursei fiecarui rand (`resolve_source`, din prefixul fixture_id)
     — sursa necunoscuta exclude tot grupul (Regula #8 North Star).
  3. Selectia randului canonic — rang minim (SourceTrustProvider), tiebreak id minim.
  4. [ADR-059] Observarea golurilor de date (ce are necanonicul si nu are
     canonicul) + owner-ul fiecaruia — raportat, niciodata scris.
  5. Marcare trasabila a randurilor necanonice (superseded_by/at/reason) — DOAR
     in modul EXECUTE.
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
#
# [EXTINS — F4.3, 2026-08-21] Adaugate flashscore/tsdb/openfootball. Fara ele,
# `resolve_source()` intoarce None pentru orice rand din aceste surse, iar
# regula "sursa necunoscuta exclude tot grupul" (Regula #8 North Star) ar fi
# exclus 403/403 grupurile descoperite dupa extinderea de vocabular F3
# (ADR-058). Rangurile corespunzatoare si justificarea lor empirica sunt in
# `source_trust_policy.py` — acest dict rezolva DOAR numele sursei din prefix,
# nu incredere (separatie explicita ID-025-01).
#
# Prefixele sunt verificate contra celor scrise efectiv in `match_history`
# (interogare live pe `fixture_id`, 2026-08-21), nu deduse din numele
# modulelor. Garda automata: `tests/test_match_identity_reconciliation_service.py
# ::test_every_live_fixture_prefix_resolves_to_a_ranked_source`.
FIXTURE_ID_PREFIX_TO_SOURCE: dict[str, str] = {
    "fd_": "football_data",
    "espn_": "espn",
    "odds_": "odds_api",
    "kaggle_": "kaggle_historical",
    "flashscore_": "flashscore",
    "tsdb_": "tsdb",
    "openfootball_": "openfootball",
}

# Camp care definesc identitatea rezultatului unui meci — discrepanta aici
# opreste reconcilierea automata a intregului grup (ID-025-01, HARD CONFLICT).
HARD_CONFLICT_COLUMNS: list[str] = [
    "actual_result", "actual_home_goals", "actual_away_goals",
]

# [ADR-059, 2026-08-21] Aceste coloane NU MAI SUNT CONTOPITE. Reconcilierea
# marcheaza, nu contopeste — vezi `process_group()`. Lista ramane, cu semantica
# schimbata: coloanele sunt INSPECTATE, ca raportul sa poata arata ce are randul
# necanonic si nu are cel canonic, si CINE detine fiecare gol.
#
# De ce s-a eliminat contopirea: fiecare din cele 52 are un owner unic de
# scriere (ADR-036) — verificat mecanic din cod, multimea coloanelor fara owner
# e vida, deci nu exista subset sigur. Si, mai important decat guvernanta:
# orice valoare de pe un rand necanonic a fost calculata sub identitatea
# FRAGMENTATA (tracker-ele ELO/forma/H2H sunt cheiate pe numele echipei), iar
# RPC-ul si `run_backfill` fiind NULL-only, o valoare gresita copiata acolo ar
# BLOCA definitiv recalculul corect al owner-ului.
#
# Alias pastrat mai jos pentru compatibilitate cu apelanti externi.
OBSERVED_DATA_COLUMNS: list[str] = [
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

# Alias de compatibilitate. Numele vechi trimite acum la aceeasi lista, dar
# semantica e cea din ADR-059: coloane observate, NU contopite.
MERGE_COLUMNS = OBSERVED_DATA_COLUMNS

# [ADR-059] Coloanele pe care reconcilierea are voie sa le scrie — singurele,
# si exclusiv pe randul NECANONIC. Randul canonic nu e atins de niciun octet.
# Reconcilierea e owner unic al acestora (adaugire la modelul ADR-036, nu
# exceptie de la el).
RECONCILIATION_OWNED_COLUMNS: tuple[str, ...] = (
    "superseded_by", "superseded_at", "superseded_reason",
)

# [ADR-059] Cine poate REGENERA fiecare coloana observata. Raportul transforma
# astfel "6 randuri au goluri" in "6 randuri asteapta ca _cache_prediction sa
# ruleze" — reconcilierea observa, owner-ul actioneaza.
# Derivat mecanic din cod, nu din memorie: `BACKFILL_COLUMNS` +
# `backfill_done` (sync/backfill_features.py:197) pentru run_backfill;
# `used_for_training` din scriitorii de import (sync/sources/openfootball.py:193,
# football_data.py:242); iesirile de predictie per ADR-036 Stage 1.
# Garda automata: tests/test_adr059_reconciliation_is_identity.py.
_PREDICTION_OUTPUT_COLUMNS = frozenset({
    "home_xg_pred", "away_xg_pred",
    "prob_home_pred", "prob_draw_pred", "prob_away_pred",
    "mc_prob_home", "mc_prob_draw", "mc_prob_away",
    "weather_penalty", "home_data_quality", "away_data_quality",
})
_BACKFILL_OWNED_COLUMNS = frozenset({
    "home_offensive_rating", "home_defensive_rating",
    "away_offensive_rating", "away_defensive_rating",
    "home_form_score", "away_form_score",
    "home_elo", "away_elo",
    "h2h_modifier", "h2h_meetings",
    "home_corner_avg_recent", "away_corner_avg_recent",
    "home_card_avg_recent", "away_card_avg_recent",
    "home_foul_avg_recent", "away_foul_avg_recent",
    "home_shot_avg_recent", "away_shot_avg_recent",
    "home_elo_after", "away_elo_after",
    "backfill_done",
})
_IMPORT_OWNED_COLUMNS = frozenset({"used_for_training"})


def column_owner(column: str) -> str:
    """Cine poate regenera aceasta coloana (ADR-036 + ADR-059). Restul
    coloanelor observate sunt statistici de meci, scrise de sincronizarea de
    statistici."""
    if column in _PREDICTION_OUTPUT_COLUMNS:
        return "_cache_prediction"
    if column in _BACKFILL_OWNED_COLUMNS:
        return "run_backfill"
    if column in _IMPORT_OWNED_COLUMNS:
        return "import_sources"
    return "stats_sync"


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
    # [ADR-059] Ce lipseste de pe randul canonic si exista pe cel necanonic:
    # {coloana -> owner care o poate regenera}. Se RAPORTEAZA, nu se scrie —
    # reconcilierea nu atinge randul canonic. Inlocuieste `merge_updates`.
    data_gaps: dict[str, str] = field(default_factory=dict)


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

    # Pasul 3 — [ADR-059] OBSERVARE, nu contopire. Se identifica ce coloane are
    # randul necanonic si nu are cel canonic, si CINE le detine — dar nu se
    # scrie nimic pe randul canonic. Vezi ADR-059 pentru rationament: toate cele
    # 52 de coloane au owner unic (ADR-036), iar valorile de pe randul necanonic
    # au fost calculate sub identitatea fragmentata, deci copierea lor ar
    # cimenta date gresite prin semantica NULL-only a RPC-ului si a backfill-ului.
    for col in OBSERVED_DATA_COLUMNS:
        if canonical.get(col) is not None:
            continue
        if any(row.get(col) is not None for row, _, _ in noncanonical_ranked):
            decision.data_gaps[col] = column_owner(col)

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
    # [ADR-059] Semantica schimbata: nu "ce s-ar scrie", ci "ce lipseste si cine
    # o poate regenera". Reconcilierea nu scrie niciuna dintre aceste coloane.
    columns_with_data_gap: dict[str, int] = field(default_factory=dict)
    gaps_by_owner: dict[str, int] = field(default_factory=dict)
    canonical_rows_with_data_gap: int = 0
    # [ADR-059] Randurile atinse sunt EXCLUSIV cele necanonice (marcaj de audit).
    # `rows_to_mark` se numara in ambele moduri (in DRY-RUN e planul), pe cand
    # `rows_marked_superseded` numara doar scrierile chiar efectuate. Diferenta
    # dintre ele, dupa un EXECUTE, e exact numarul de esecuri de scriere.
    rows_to_mark: int = 0
    rows_marked_superseded: int = 0

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

    def _mark_superseded(self, row_id: Any, canonical_id: Any, reason: str) -> None:
        """[ADR-059] Singura scriere pe care o face reconcilierea. Atinge EXCLUSIV
        randul necanonic, si doar cele 3 coloane de audit din
        `RECONCILIATION_OWNED_COLUMNS`. Randul canonic nu e atins niciodata.

        Idempotent prin filtrul `superseded_by is null`: un rand deja marcat nu
        e re-marcat, deci o reluare dupa esec partial nu suprascrie un marcaj
        anterior (si nu-i schimba `superseded_at`)."""
        from datetime import datetime, timezone

        client = self._sb.get_client()
        (
            client.table("match_history")
            .update({
                "superseded_by": canonical_id,
                "superseded_at": datetime.now(timezone.utc).isoformat(),
                "superseded_reason": reason,
            })
            .eq("id", row_id)
            .is_("superseded_by", "null")
            .execute()
        )

    def run(self, dry_run: bool = True, limit_groups: int | None = None) -> ReconciliationReport:
        """DRY-RUN implicit. `dry_run=False` scrie — vezi `_mark_superseded`
        pentru suprafata exacta (3 coloane de audit, doar pe randul necanonic).

        [ADR-059] Modul EXECUTE e autorizat de ADR-059, care a redus radical
        riscul: reconcilierea nu mai contopeste date, deci nu mai exista
        "valoare completata care trebuie reconstituita" la rollback — anularea
        e stergerea marcajului. Execuția in sine ramane gatata per Phase Gate
        (ADR-025): pilot pe subset inainte de rulare completa.

        `limit_groups` — plafon de siguranta pentru pilot (ADR-025 Faza 3).
        Grupurile se proceseaza in ordine sortata a cheii naturale, deci un
        pilot e reproductibil: aceleasi N grupuri la fiecare rulare.
        """
        report = ReconciliationReport()
        key_index = self._fetch_key_index()
        duplicate_groups = {k: v for k, v in key_index.items() if len(v) > 1}
        report.total_groups = len(duplicate_groups)

        all_ids = [row["id"] for rows in duplicate_groups.values() for row in rows]
        full_rows_by_id = self._fetch_full_rows(all_ids)

        processed = 0
        for key in sorted(duplicate_groups):
            stub_rows = duplicate_groups[key]
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

            if limit_groups is not None and processed >= limit_groups:
                continue
            processed += 1

            report.reconciled_groups += 1
            if decision.data_gaps:
                report.canonical_rows_with_data_gap += 1
            for col, owner in decision.data_gaps.items():
                report.columns_with_data_gap[col] = report.columns_with_data_gap.get(col, 0) + 1
                report.gaps_by_owner[owner] = report.gaps_by_owner.get(owner, 0) + 1

            report.rows_to_mark += len(decision.noncanonical)

            if not dry_run:
                for nc in decision.noncanonical:
                    try:
                        self._mark_superseded(nc["id"], decision.canonical_id, nc["reason"])
                        report.rows_marked_superseded += 1
                    except Exception as exc:
                        # Un esec pe un grup nu opreste restul: marcajul e
                        # idempotent si per-rand, deci reluarea e sigura.
                        report.write_errors.append(f"id={nc['id']}: {exc}")
                        logger.error("[MatchIdentityReconciliation] Esec marcaj id=%s: %s", nc["id"], exc)

        logger.info(
            "[MatchIdentityReconciliation] %s: %d grupuri, %d reconciliate, "
            "%d hard_conflict, %d sursa_necunoscuta, %d randuri_canonice_cu_gol, "
            "%d randuri_marcate, %d erori_scriere",
            "DRY-RUN" if dry_run else "EXECUTE",
            report.total_groups, report.reconciled_groups,
            report.excluded_hard_conflict_count, report.excluded_unknown_source_count,
            report.canonical_rows_with_data_gap, report.rows_marked_superseded,
            len(report.write_errors),
        )
        return report
