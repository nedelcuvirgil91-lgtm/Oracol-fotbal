"""
================================================================================
FOOTBALL ORACLE — Raport Shadow Mode: Selection Engine (ADR-034, PR5)
================================================================================
Module: shadow_selection_report.py

NU e cod de producție — script de raportare/analiză, rulat manual, citește
`shadow_provider_recommendations` (read-only, prin shadow_recorder.py, unde
rămâne izolată toată cunoașterea de Supabase). Nu apelează niciodată
provider_selector.py, nu influențează Selection Engine sau Prediction
Engine în niciun fel.

`build_report(rows)` e o funcție pură — primește rânduri deja citite,
produce text. Testabilă direct cu fixture-uri, fără rețea.

Notă onestă despre schema disponibilă: `shadow_provider_recommendations`
stochează scorurile TOTALE (current_score/recommended_score) și DELTAS
ponderate per componentă (component_deltas, JSONB) — NU scorurile brute pe
componentă ale fiecărui provider individual. "Delta mediu per componentă"
de mai jos e media diferenței (recommended - current), nu o medie absolută
a componentei — schema nu permite mai mult fără o modificare separată,
neefectuată aici.

Rulare:
    python shadow_selection_report.py [--since YYYY-MM-DD]
================================================================================
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date

import shadow_recorder

MIN_DAYS_FOR_EXIT_CRITERION = 7
MIN_SAMPLES_FOR_EXIT_CRITERION = 50
MATCH_RATE_THRESHOLD = 0.95

_COMPONENT_ORDER = ("availability", "coverage", "reliability", "quota", "latency", "priority")


def _fmt_pct(n: int, total: int) -> str:
    return f"{(100 * n / total):.1f}%" if total else "n/a"


def build_report(rows: list[dict]) -> str:
    lines: list[str] = []
    total = len(rows)
    lines.append("=" * 78)
    lines.append("Selection Engine — Raport Shadow Mode (ADR-034 PR5)")
    lines.append("=" * 78)

    if total == 0:
        lines.append("\nNicio observație înregistrată încă.")
        return "\n".join(lines)

    identical = [r for r in rows if not r.get("decision_changed") and r.get("recommended_provider")]
    different = [r for r in rows if r.get("decision_changed")]
    unavailable = [r for r in rows if not r.get("recommended_provider")]

    observed_dates = sorted({(r.get("observed_at") or "")[:10] for r in rows if r.get("observed_at")})
    n_days = len(observed_dates)

    lines.append(f"\nTotal recomandări: {total}")
    if observed_dates:
        lines.append(f"Perioadă acoperită: {observed_dates[0]} → {observed_dates[-1]} ({n_days} zile distincte)")
    lines.append(f"Identice cu providerul curent: {len(identical)} ({_fmt_pct(len(identical), total)})")
    lines.append(f"Diferite față de providerul curent: {len(different)} ({_fmt_pct(len(different), total)})")
    lines.append(f"Niciun candidat eligibil (provider_unavailable): {len(unavailable)} "
                 f"({_fmt_pct(len(unavailable), total)})")

    lines.append("\n--- Distribuție recomandări pe provider ---")
    dist = Counter(r["recommended_provider"] for r in rows if r.get("recommended_provider"))
    if not dist:
        lines.append("  (nicio recomandare cu provider eligibil)")
    for provider_id, count in dist.most_common():
        lines.append(f"  {provider_id:<20} {count:>4}  ({_fmt_pct(count, total)})")

    lines.append("\n--- Delta mediu per componentă (recommended - current, doar cazuri diferite) ---")
    lines.append("    (schema stochează doar deltas ponderate, nu componentele brute per provider)")
    component_sums: dict[str, float] = defaultdict(float)
    component_counts: dict[str, int] = defaultdict(int)
    for r in different:
        for name, value in (r.get("component_deltas") or {}).items():
            component_sums[name] += value
            component_counts[name] += 1
    any_component = False
    for name in _COMPONENT_ORDER:
        if component_counts[name] > 0:
            any_component = True
            avg = component_sums[name] / component_counts[name]
            lines.append(f"  {name:<14} {avg:+.3f}")
    if not any_component:
        lines.append("  (niciun caz cu recomandare diferită încă)")

    lines.append("\n--- Evoluție zilnică ---")
    by_day: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "identical": 0, "different": 0})
    for r in rows:
        day = (r.get("observed_at") or "")[:10]
        by_day[day]["total"] += 1
        if r.get("decision_changed"):
            by_day[day]["different"] += 1
        elif r.get("recommended_provider"):
            by_day[day]["identical"] += 1
    for day in sorted(by_day):
        d = by_day[day]
        lines.append(f"  {day}   total={d['total']:<4} identice={d['identical']:<4} diferite={d['different']:<4}")

    lines.append("\n--- Cazuri cu recomandare diferită față de providerul curent ---")
    if not different:
        lines.append("  (niciunul)")
    for r in different:
        lines.append(
            f"  [{(r.get('observed_at') or '')[:19]}] {r.get('league')}: "
            f"{r.get('current_provider')} (scor {r.get('current_score')}) -> "
            f"{r.get('recommended_provider')} (scor {r.get('recommended_score')})"
        )

    lines.append("\n" + "=" * 78)
    lines.append("Criteriul de ieșire din Shadow Mode (ADR-034, PR5→PR6)")
    lines.append("=" * 78)
    match_rate = len(identical) / total if total else 0.0
    enough_sample = n_days >= MIN_DAYS_FOR_EXIT_CRITERION and total >= MIN_SAMPLES_FOR_EXIT_CRITERION
    lines.append(
        f"  Eșantion minim (≥{MIN_DAYS_FOR_EXIT_CRITERION} zile ȘI ≥{MIN_SAMPLES_FOR_EXIT_CRITERION} recomandări): "
        f"{'DA' if enough_sample else 'NU'} ({n_days} zile, {total} recomandări)"
    )
    lines.append(
        f"  Criteriul 1 (rata de coincidență ≥{MATCH_RATE_THRESHOLD * 100:.0f}%): "
        f"{'DA' if match_rate >= MATCH_RATE_THRESHOLD else 'NU'} ({match_rate * 100:.1f}%)"
    )
    lines.append("  Criteriul 2 (zero regresii funcționale): necesită corelare manuală cu fetch-uri "
                  "reale — nu calculabil automat din această tabelă.")
    lines.append("  Criteriul 3 (rata de erori de fetch neschimbată): necesită comparație cu "
                  "provider_metrics — raport separat.")
    lines.append("  Criteriul 4 (consum de cereri în limitele estimate): necesită comparație cu "
                  "key_manager/provider_metrics — raport separat.")

    return "\n".join(lines)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Raport Shadow Mode — Selection Engine (ADR-034 PR5)")
    parser.add_argument("--since", type=str, default=None,
                         help="Doar observații de la această dată (YYYY-MM-DD)")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    since = date.fromisoformat(args.since) if args.since else None
    rows = shadow_recorder.get_shadow_rows(since=since)
    print(build_report(rows))


if __name__ == "__main__":
    main()
