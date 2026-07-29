"""
================================================================================
FOOTBALL ORACLE — UDAL Validation Layer (Faza 1, ADR-042)
================================================================================
Module: udal_validation.py

Generalizarea contractului deja existent `SyncAdapter.validate()` (nu
aruncă niciodată pentru un rând individual invalid — îl exclude) într-un
modul comun, aplicat DUPĂ `normalize()`, indiferent de tier — un rând
produs de Playwright (Faza 4, viitor) trece prin exact aceeași validare
ca unul produs de HTTP Scraper (Faza 1) sau de API (existent).

Trei clase de verificare (UDAL_ARCHITECTURE_SPEC v1.0 §9):
  1. Schemă — câmpuri obligatorii prezente, tip corect.
  2. Consistență inter-câmp — non-negativ, plajă plauzibilă.
  3. Coliziune de cheie naturală — DOAR în interiorul lotului curent în
     Faza 1 (fără scriere/interogare pe `match_history`, per constrângerea
     explicită a Fazei 1: "fără scriere în tabele canonice" — o verificare
     de conflict CONTRA `match_history` rămâne o funcție separată,
     read-only, explicit denumită, NU parte din `validate_records()`).

Fiecare rând VALID capătă proveniență obligatorie (`source_tier`,
`source_id`, `fetched_at`, `confidence`) — un rând fără proveniență
completă nu poate ieși din acest modul ca "valid".
================================================================================
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

REQUIRED_FIELDS: tuple[str, ...] = (
    "home_team", "away_team", "kickoff_date",
    "home_corners", "away_corners",
    "home_cards", "away_cards",
    "home_fouls", "away_fouls",
)

_NUMERIC_FIELDS: tuple[str, ...] = (
    "home_corners", "away_corners", "home_cards", "away_cards",
    "home_fouls", "away_fouls",
)


@dataclass(frozen=True)
class RejectedRecord:
    record: dict
    reason: str


@dataclass
class ValidationResult:
    valid: list[dict] = field(default_factory=list)
    rejected: list[RejectedRecord] = field(default_factory=list)

    @property
    def validation_rate(self) -> float:
        total = len(self.valid) + len(self.rejected)
        return (len(self.valid) / total) if total else 0.0


def _natural_key(record: dict) -> tuple:
    return (record.get("home_team"), record.get("away_team"), record.get("kickoff_date"))


def validate_records(
    records: list[dict], source_tier: str, source_id: str,
    confidence: str = "SCRAPED_UNVERIFIED",
) -> ValidationResult:
    """Validare pură, fără I/O — respectă exact tiparul
    `SyncAdapter.validate()` (niciodată aruncă pentru un rând individual).
    `confidence` urmează vocabularul cu 3 stări din spec (§9):
    `CONFIRMED_API | SCRAPED_VERIFIED | SCRAPED_UNVERIFIED` — implicit
    `SCRAPED_UNVERIFIED`, corect pentru orice sursă cu `tos_reviewed=False`
    (Faza 1 pilot, nicio sursă aprobată încă)."""
    result = ValidationResult()
    seen_keys: set[tuple] = set()

    for record in records:
        missing = [f for f in REQUIRED_FIELDS if record.get(f) in (None, "")]
        if missing:
            result.rejected.append(RejectedRecord(
                record, f"missing_required_fields:{','.join(missing)}",
            ))
            continue

        numeric_values: dict[str, int] = {}
        bad_numeric = False
        for f_name in _NUMERIC_FIELDS:
            try:
                numeric_values[f_name] = int(record[f_name])
            except (TypeError, ValueError):
                result.rejected.append(RejectedRecord(record, f"non_numeric_field:{f_name}"))
                bad_numeric = True
                break
        if bad_numeric:
            continue

        negative = [f_name for f_name, v in numeric_values.items() if v < 0]
        if negative:
            result.rejected.append(RejectedRecord(
                record, f"negative_value:{','.join(negative)}",
            ))
            continue

        key = _natural_key(record)
        if key in seen_keys:
            result.rejected.append(RejectedRecord(record, "duplicate_natural_key_in_batch"))
            continue
        seen_keys.add(key)

        provenanced = dict(record)
        provenanced.update(numeric_values)
        provenanced["_provenance"] = {
            "source_tier": source_tier,
            "source_id": source_id,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "confidence": confidence,
        }
        result.valid.append(provenanced)

    return result


def validate_identity_only(
    records: list[dict], source_tier: str, source_id: str,
    confidence: str = "SCRAPED_UNVERIFIED",
) -> ValidationResult:
    """[UDAL Faza 1.5] Validare MINIMALĂ pentru recorduri IERARHICE, bogate
    (`udal_extraction.extract()` — grupuri `match`/`teams`/`score`/
    `statistics`/`lineups`/etc., nu forma plată din Faza 1). Verifică DOAR
    identitatea (`teams.home_team`/`teams.away_team` prezente) — NU
    reimplementă regulile de schemă/plajă din `validate_records()` (acelea
    rămân specifice formei plate de statistici de meci, Faza 1). Scopul
    Fazei 1.5 e completitudinea pe categorii (Compatibility Matrix), nu
    respingerea strictă de rânduri — calculul de completitudine se face
    separat, în raport, nu aici."""
    result = ValidationResult()
    for record in records:
        teams = record.get("teams") or {}
        if not teams.get("home_team") or not teams.get("away_team"):
            result.rejected.append(RejectedRecord(record, "missing_team_identity"))
            continue
        provenanced = dict(record)
        provenanced["_provenance"] = {
            "source_tier": source_tier,
            "source_id": source_id,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "confidence": confidence,
        }
        result.valid.append(provenanced)
    return result


def validate_flat_identity(
    records: list[dict], source_tier: str, source_id: str,
    confidence: str = "SCRAPED_UNVERIFIED",
) -> ValidationResult:
    """[Foundation Data Layer, Flashscore] Validare MINIMALĂ pentru forme
    PLATE bogate (`normalize_match_statistics()` - 20+ câmpuri variabile,
    nu doar cele 9 fixe din `REQUIRED_FIELDS`) - verifică DOAR cheia
    naturală (home_team/away_team/kickoff_date). `validate_records()` NU
    se potrivește aici: schema lui fixă (`home_cards`/`away_cards`
    combinate) aparține unui pilot Fază 1 anterior, diferit de forma
    reală Flashscore (`home_yellow_cards`/`home_red_cards` separate) -
    aplicarea ei ar respinge orice rând valid, fals-negativ. Analog cu
    `validate_identity_only()` (Faza 1.5, forme ierarhice), dar pentru
    forme PLATE - același contract de ieșire (`ValidationResult`,
    proveniență obligatorie)."""
    result = ValidationResult()
    for record in records:
        if not record.get("home_team") or not record.get("away_team") or not record.get("kickoff_date"):
            result.rejected.append(RejectedRecord(record, "missing_natural_key"))
            continue
        provenanced = dict(record)
        provenanced["_provenance"] = {
            "source_tier": source_tier,
            "source_id": source_id,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "confidence": confidence,
        }
        result.valid.append(provenanced)
    return result


def check_conflicts_with_match_history(records: list[dict]) -> list[dict]:
    """[Faza 1, read-only, NU parte din validate_records()] Verifică dacă
    cheia naturală (home_team, away_team, kickoff_date) a unui rând VALID
    există deja în `match_history` — informativ (Conflict Rate), NU
    blochează validarea și NU scrie nimic. Degradare grațioasă dacă
    Supabase nu e disponibil (listă goală, nu excepție) — consecvent cu
    restul proiectului."""
    if not records:
        return []
    try:
        import supabase_client as sb
        client = sb.get_client()
        if client is None:
            return []
        conflicts = []
        for record in records:
            res = (
                client.table("match_history")
                .select("id")
                .eq("home_team", record.get("home_team"))
                .eq("away_team", record.get("away_team"))
                .eq("kickoff_date", record.get("kickoff_date"))
                .limit(1)
                .execute()
            )
            if res.data:
                conflicts.append(record)
        return conflicts
    except Exception:
        return []
