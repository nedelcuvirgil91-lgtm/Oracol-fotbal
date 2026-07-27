"""
================================================================================
FOOTBALL ORACLE — Migration Gate (ADR-040, G3)
================================================================================
Module: migration_gate.py

Instrumentul oficial de guvernanță al proiectului (decizie explicită
proprietar produs, G3: „nu îl gândim în termeni de R-Sync-7, ci de
mecanism general") — generic prin construcție, parametrizat pe `gate_key`
+ `entity`, nu legat de `scheduled_fixtures`. Aceeași infrastructură
validează orice tabelă critică viitoare (`equivalence_evaluations`,
`migration_gate_status` — ADR-040, principiul 2/7).

Patru comenzi (ADR-040, principiul 7):

    migration_gate status  <gate_key>   # PASS/FAIL/GRAY, exit 0/1/2
    migration_gate explain <gate_key>   # + cauză dominantă + acțiune recomandată
    migration_gate attest  <gate_key>   # scrie docs/00_GOVERNANCE/gates/<gate_key>.attestation.json
    migration_gate verify  <gate_key>   # re-derivă din DB, detectează atestare stale/falsificată

`history`/`providers`/`dashboard` — extensii viitoare (ADR-040, secțiunea
Future Extensions), NEimplementate aici, deliberat.

VETO ≠ AUTORIZARE (ADR-040, principiul 1): acest modul poate produce
FAIL/GRAY (blocare), niciodată nu „autorizează" nimic automat — verdictul
PASS e o CONSTATARE persistentă, verificabilă, nu o acțiune. Decizia de a
continua etapa următoare rămâne întotdeauna a proprietarului produsului.

Nivel A (validitatea unui rând, `insufficient_data`) trăiește în
`equivalence_governance.classify_evaluation()`, aplicat la scriere.
Nivel B (maturitatea porții — acest modul) combină `historical_confidence`
(volum cumulat, MIN între volum total și cel mai slab provider) cu
`current_health` (starea celei mai recente evaluări eligibile) — ambele
citite din view-ul `migration_gate_status` (migrările 024/025), niciodată
recalculate aici din rânduri brute.
================================================================================
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import equivalence_root_cause as root_cause

DEFAULT_MIN_MATCHED_TOTAL = 500
DEFAULT_MIN_MATCHED_PER_PROVIDER = 50
STALE_AFTER_DAYS = 30

ATTESTATION_DIR = Path(__file__).parent / "docs" / "00_GOVERNANCE" / "gates"

_RECOMMENDED_ACTION: dict[str, str] = {
    root_cause.MISSING_PROVIDER_ID: "Rulează din nou sync_scheduled_fixtures.py (sau echivalentul pentru entitate) pentru providerul afectat.",
    root_cause.VENUE_PRIORITY: "Verifică SourcePriority pentru câmpul afectat (migrarea 023).",
    root_cause.LEAGUE_MAPPING: "Verifică SourcePriority pentru câmpul afectat (migrarea 023).",
    root_cause.KICKOFF_CONFLICT: "Verifică SourcePriority pentru câmpul afectat (migrarea 023).",
    root_cause.PROVIDER_TIMEOUT: "Verifică Request Manager/Rate Limit Manager pentru providerul afectat.",
    root_cause.TEAM_NORMALIZATION: "Categorie rezervată, neatribuită automat azi — investigație manuală.",
    root_cause.UNKNOWN: "Investigație manuală — cauza nu a putut fi clasificată automat.",
}


@dataclass
class GateVerdict:
    gate_key: str
    entity: str
    verdict: str  # "PASS" | "FAIL" | "GRAY"
    historical_confidence: float
    current_health: str | None
    total_matched_eligible: int
    eligible_row_count: int
    min_provider_matched: int | None
    reasons: list[str] = field(default_factory=list)


@dataclass
class ExplainReport:
    verdict: GateVerdict
    dominant_root_cause: str | None
    recommended_action: str


@dataclass
class VerifyResult:
    valid: bool
    reasons: list[str] = field(default_factory=list)


def load_thresholds(gate_key: str) -> dict:
    """Praguri configurabile per `gate_key` (ADR-040, principiul 6, Nivel B),
    din `model_config` (Supabase, cheie `migration_gate_thresholds`) — implicit
    500 total / 50 per provider dacă nu există override."""
    import supabase_client as sb

    cfg = sb.load_config({"migration_gate_thresholds": {}})
    per_gate = (cfg.get("migration_gate_thresholds") or {}).get(gate_key, {})
    return {
        "min_matched_total": per_gate.get("min_matched_total", DEFAULT_MIN_MATCHED_TOTAL),
        "min_matched_per_provider": per_gate.get("min_matched_per_provider", DEFAULT_MIN_MATCHED_PER_PROVIDER),
    }


def compute_verdict(gate_key: str, entity: str, view_row: dict | None, thresholds: dict) -> GateVerdict:
    """
    Funcție PURĂ — primește `view_row` deja citit din `migration_gate_status`
    (sau None dacă nu există niciun rând), decide verdictul. Testabilă fără
    Supabase.

    Regulă (ADR-040, principiul 6): PASS doar dacă volumul istoric e
    suficient ȘI ultima evaluare eligibilă e GREEN/YELLOW. O regresie
    recentă (RED/broken) blochează imediat, indiferent de volumul cumulat
    — istoricul construiește încrederea, ultima rulare o confirmă.
    """
    min_total = thresholds.get("min_matched_total", DEFAULT_MIN_MATCHED_TOTAL)
    min_per_provider = thresholds.get("min_matched_per_provider", DEFAULT_MIN_MATCHED_PER_PROVIDER)

    if view_row is None or view_row.get("current_health") is None:
        return GateVerdict(
            gate_key=gate_key, entity=entity, verdict="GRAY",
            historical_confidence=0.0, current_health=None,
            total_matched_eligible=0, eligible_row_count=0, min_provider_matched=None,
            reasons=["Nicio evaluare eligibilă încă — sistem în acumulare de dovezi (GRAY, nu eroare)."],
        )

    current_health = view_row["current_health"]
    total_matched = view_row.get("total_matched_eligible") or 0
    eligible_row_count = view_row.get("eligible_row_count") or 0
    min_provider_matched = view_row.get("min_provider_matched")

    volume_confidence = min(total_matched / min_total, 1.0) if min_total > 0 else 1.0
    provider_confidence = (
        min(min_provider_matched / min_per_provider, 1.0)
        if min_provider_matched is not None and min_per_provider > 0
        else 0.0
    )
    historical_confidence = min(volume_confidence, provider_confidence)

    common = dict(
        gate_key=gate_key, entity=entity, historical_confidence=historical_confidence,
        current_health=current_health, total_matched_eligible=total_matched,
        eligible_row_count=eligible_row_count, min_provider_matched=min_provider_matched,
    )

    if current_health in ("red", "broken"):
        return GateVerdict(verdict="FAIL", reasons=[
            f"Ultima evaluare eligibilă e {current_health.upper()} — blocare imediată, "
            "indiferent de volumul istoric acumulat.",
        ], **common)

    if historical_confidence >= 1.0:
        return GateVerdict(verdict="PASS", reasons=[
            "Volum istoric suficient (total și per provider) ȘI ultima evaluare eligibilă "
            f"e {current_health.upper()}.",
        ], **common)

    return GateVerdict(verdict="GRAY", reasons=[
        f"Sănătate curentă OK ({current_health}), dar volum istoric insuficient "
        f"({historical_confidence:.1%} din prag — total={total_matched}/{min_total}, "
        f"min_provider={min_provider_matched}/{min_per_provider}).",
    ], **common)


def get_status(gate_key: str, entity: str = "scheduled_fixtures") -> GateVerdict:
    from database.queries import get_migration_gate_status_row

    thresholds = load_thresholds(gate_key)
    view_row = get_migration_gate_status_row(gate_key, entity)
    return compute_verdict(gate_key, entity, view_row, thresholds)


def dominant_root_cause(rows: list[dict]) -> str | None:
    """Funcție PURĂ — agregă `root_cause_summary` peste o listă de rânduri
    deja citite, întoarce categoria cu cel mai mare total (None dacă nu
    există nicio diferență în istoricul dat)."""
    totals: dict[str, int] = {}
    for row in rows:
        for category, count in (row.get("root_cause_summary") or {}).items():
            totals[category] = totals.get(category, 0) + count
    if not totals:
        return None
    return max(totals.items(), key=lambda kv: kv[1])[0]


def recommended_action(category: str | None) -> str:
    if category is None:
        return "Nicio diferență găsită în istoricul recent — nimic de investigat."
    return _RECOMMENDED_ACTION.get(category, "Categorie necunoscută — investigație manuală.")


def explain(gate_key: str, entity: str = "scheduled_fixtures", recent_limit: int = 50) -> ExplainReport:
    from database.queries import list_recent_equivalence_evaluations

    verdict = get_status(gate_key, entity)
    recent_rows = list_recent_equivalence_evaluations(gate_key, entity, limit=recent_limit)
    category = dominant_root_cause(recent_rows)
    return ExplainReport(
        verdict=verdict, dominant_root_cause=category,
        recommended_action=recommended_action(category),
    )


def build_attestation_payload(verdict: GateVerdict, generated_at: str | None = None) -> dict:
    """Funcție PURĂ — construiește payload-ul de atestare + digest-ul de
    evidență dintr-un `GateVerdict` deja calculat. Testabilă fără I/O."""
    payload = {
        "gate_key": verdict.gate_key, "entity": verdict.entity,
        "verdict": verdict.verdict,
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "historical_confidence": verdict.historical_confidence,
        "current_health": verdict.current_health,
        "total_matched_eligible": verdict.total_matched_eligible,
        "eligible_row_count": verdict.eligible_row_count,
        "min_provider_matched": verdict.min_provider_matched,
        "reasons": verdict.reasons,
    }
    digest_source = json.dumps({
        k: payload[k] for k in (
            "gate_key", "entity", "verdict", "historical_confidence", "current_health",
            "total_matched_eligible", "eligible_row_count", "min_provider_matched",
        )
    }, sort_keys=True)
    payload["evidence_digest"] = "sha256:" + hashlib.sha256(digest_source.encode("utf-8")).hexdigest()
    return payload


def attestation_path(gate_key: str) -> Path:
    return ATTESTATION_DIR / f"{gate_key}.attestation.json"


def attest(gate_key: str, entity: str = "scheduled_fixtures", path: Path | None = None) -> dict:
    """
    Scrie o „chitanță" locală, offline-verificabilă (ADR-040, principiul 8)
    — NU e autoritatea (asta rămâne Supabase, `equivalence_evaluations` +
    view), doar o dovadă verificabilă fără rețea. Scrie verdictul curent
    ORICARE ar fi el (PASS/FAIL/GRAY) — o atestare FAIL/GRAY e la fel de
    informativă ca una PASS, nu se ascunde.
    """
    verdict = get_status(gate_key, entity)
    payload = build_attestation_payload(verdict)

    target = path or attestation_path(gate_key)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return payload


def verify(gate_key: str, entity: str = "scheduled_fixtures", path: Path | None = None) -> VerifyResult:
    """
    Citește atestarea locală, re-derivă starea curentă din DB, compară.
    Limită declarată onest (ADR-040, principiul 8): fișierul poate fi editat
    manual — asta NU poate fi împiedicat criptografic aici, doar detectat
    prin discrepanță față de starea reală.
    """
    target = path or attestation_path(gate_key)
    if not target.exists():
        return VerifyResult(valid=False, reasons=[f"Nicio atestare găsită la {target}."])

    try:
        stored = json.loads(target.read_text(encoding="utf-8"))
    except Exception as exc:
        return VerifyResult(valid=False, reasons=[f"Atestare ilizibilă/coruptă: {exc}"])

    reasons: list[str] = []

    generated_at = stored.get("generated_at")
    try:
        ts = datetime.fromisoformat(generated_at)
    except (TypeError, ValueError):
        return VerifyResult(valid=False, reasons=["Atestare fără `generated_at` valid (ISO 8601)."])

    age_days = (datetime.now(timezone.utc) - ts).days
    if age_days > STALE_AFTER_DAYS:
        reasons.append(f"Atestare veche de {age_days} zile (prag {STALE_AFTER_DAYS}).")

    fresh_verdict = get_status(gate_key, entity)
    if stored.get("verdict") != fresh_verdict.verdict:
        reasons.append(
            f"Atestare spune {stored.get('verdict')}, starea curentă (re-derivată din DB) e "
            f"{fresh_verdict.verdict} — atestare stale sau modificată manual.",
        )

    if reasons:
        return VerifyResult(valid=False, reasons=reasons)
    return VerifyResult(valid=True, reasons=["Atestare validă, proaspătă, consistentă cu starea curentă."])


_EXIT_CODES = {"PASS": 0, "FAIL": 1, "GRAY": 2}


def _cli() -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="migration_gate")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "explain", "attest", "verify"):
        p = sub.add_parser(name)
        p.add_argument("gate_key")
        p.add_argument("--entity", default="scheduled_fixtures")
    args = parser.parse_args()

    if args.command == "status":
        v = get_status(args.gate_key, args.entity)
        print(f"{v.verdict}  gate_key={v.gate_key} entity={v.entity} "
              f"historical_confidence={v.historical_confidence:.1%} current_health={v.current_health}")
        for r in v.reasons:
            print(f"  - {r}")
        return _EXIT_CODES[v.verdict]

    if args.command == "explain":
        rep = explain(args.gate_key, args.entity)
        v = rep.verdict
        print(f"{v.verdict}  gate_key={v.gate_key} entity={v.entity}")
        for r in v.reasons:
            print(f"  - {r}")
        print(f"Cauză dominantă (istoric recent): {rep.dominant_root_cause or '(nicio diferență)'}")
        print(f"Acțiune recomandată: {rep.recommended_action}")
        return _EXIT_CODES[v.verdict]

    if args.command == "attest":
        payload = attest(args.gate_key, args.entity)
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    if args.command == "verify":
        result = verify(args.gate_key, args.entity)
        for r in result.reasons:
            print(f"  - {r}")
        return 0 if result.valid else 1

    return 2  # pragma: no cover -- argparse cu subparsers required=True nu permite ajungerea aici


if __name__ == "__main__":
    import sys
    sys.exit(_cli())
