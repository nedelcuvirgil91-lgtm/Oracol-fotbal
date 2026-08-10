"""
================================================================================
FOOTBALL ORACLE — Validare xG Oracle (predicted) vs. xG real (actual)
================================================================================
Module: scripts/xg_pred_vs_actual_validation.py

Tooling de analiză (nu cod de producție — niciun modul din app.py/
oracle_engine.py/sync/*/learning_core/* îl importă). Read-only: nicio
scriere în Supabase, niciun flag de producție atins, nicio decizie luată
automat — doar raport descriptiv, exact tiparul deja stabilit de
validation_analysis.py (ADR-052 §2.3: "Claude analizează și recomandă,
decizia rămâne a proprietarului produsului").

Compară DOUĂ semnale deja existente în `match_history`, niciodată puse
față în față până acum:
  - home_xg_pred/away_xg_pred — xG-ul PROPRIU al Oracle Engine, o proxy
    matematică derivată din rating ofensiv/defensiv/formă/ELO
    (feature_engine.calibrate_xg()), NU un model bazat pe hărți de șuturi.
    Scris de oracle_engine.py la momentul predicției (înainte de meci).
  - home_xg_actual/away_xg_actual — xG REAL, stil Opta (bazat pe calitatea
    șuturilor), colectat de Foundation Data Layer din tab-ul Summary al
    Flashscore ȘI din soccerfootballinfo (două surse independente) —
    scris DUPĂ meci, când statisticile reale există.

Întrebarea la care răspunde: cât de bine aproximează formula proprie a
Oracle xG-ul real bazat pe șuturi? Bias sistematic (supra/subestimare) ar
fi un semnal pentru un experiment de recalibrare — dar NICIODATĂ decis
aici; per regula explicită din CLAUDE.md, orice schimbare a parametrilor
matematici ai Oracle e un experiment de calibrare separat, cu aprobare
proprie, niciodată bundle-uit tacit într-o analiză.

Eșantion mic azi (xG real hidden există doar pentru meciuri deja trecute
prin Foundation Data Layer, ADR-044) — crește zilnic prin night_sync.yml/
live_sync.yml, fără cost suplimentar de colectare.

Utilizare:
    python scripts/xg_pred_vs_actual_validation.py
    python scripts/xg_pred_vs_actual_validation.py --min-league-n 5
================================================================================
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd


def fetch_rows() -> pd.DataFrame:
    """Read-only — SELECT direct, nicio scriere. Filtrează pe rânduri unde
    AMBELE semnale (pred ȘI actual) există pentru același meci — altfel nu
    există nimic de comparat."""
    import supabase_client as sb

    client = sb.get_client()
    cols = ("league,home_xg_pred,away_xg_pred,home_xg_actual,away_xg_actual,"
            "actual_home_goals,actual_away_goals")
    all_rows: list[dict] = []
    offset = 0
    page_size = 1000
    while True:
        res = (
            client.table("match_history")
            .select(cols)
            .not_.is_("home_xg_pred", "null")
            .not_.is_("away_xg_pred", "null")
            .not_.is_("home_xg_actual", "null")
            .not_.is_("away_xg_actual", "null")
            .not_.is_("actual_result", "null")
            .range(offset, offset + page_size - 1)
            .execute()
        )
        rows = res.data or []
        all_rows.extend(rows)
        if len(rows) < page_size:
            break
        offset += page_size
    return pd.DataFrame(all_rows)


def _side_errors(pred: pd.Series, actual: pd.Series) -> dict:
    pred = pred.astype(float)
    actual = actual.astype(float)
    err = pred - actual
    mae = err.abs().mean()
    bias = err.mean()
    rmse = np.sqrt((err ** 2).mean())
    corr = pred.corr(actual) if len(pred) >= 3 else None
    return {"n": len(pred), "mae": mae, "bias": bias, "rmse": rmse, "corr": corr}


def _fmt(v) -> str:
    return "—" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{v:.3f}"


def _print_block(title: str, stats: dict) -> None:
    print(f"  {title:<10} n={stats['n']:<4} MAE={_fmt(stats['mae'])}  "
          f"bias={_fmt(stats['bias'])} (pred-actual)  RMSE={_fmt(stats['rmse'])}  "
          f"corr={_fmt(stats['corr'])}")


def run(min_league_n: int) -> None:
    df = fetch_rows()
    print()
    print("=" * 88)
    print("  Football Oracle — xG Oracle (predicted) vs. xG real (actual), validare")
    print("=" * 88)
    print(f"  Eșantion total: {len(df)} meciuri (au AMBELE semnale — predicted ȘI actual)")
    print("=" * 88)

    if df.empty:
        print("\nNiciun meci cu ambele semnale disponibile — nimic de analizat azi.")
        return

    print("\n── Agregat (toate ligile, home+away combinate) ──")
    combined_pred = pd.concat([df["home_xg_pred"], df["away_xg_pred"]], ignore_index=True)
    combined_actual = pd.concat([df["home_xg_actual"], df["away_xg_actual"]], ignore_index=True)
    _print_block("Combinat", _side_errors(combined_pred, combined_actual))
    _print_block("Home", _side_errors(df["home_xg_pred"], df["home_xg_actual"]))
    _print_block("Away", _side_errors(df["away_xg_pred"], df["away_xg_actual"]))

    print(f"\n── Per ligă (doar cu n >= {min_league_n} meciuri) ──")
    for league, g in df.groupby("league"):
        if len(g) < min_league_n:
            continue
        pred = pd.concat([g["home_xg_pred"], g["away_xg_pred"]], ignore_index=True)
        actual = pd.concat([g["home_xg_actual"], g["away_xg_actual"]], ignore_index=True)
        _print_block(league, _side_errors(pred, actual))

    skipped = [lg for lg, g in df.groupby("league") if len(g) < min_league_n]
    if skipped:
        print(f"\n  (sărite, sub prag: {', '.join(skipped)})")

    print("\n── Context: xG real vs. goluri reale marcate (variație/\"noroc\", nu eroare Oracle) ──")
    combined_goals = pd.concat([df["actual_home_goals"], df["actual_away_goals"]], ignore_index=True)
    _print_block("xG_real vs goluri", _side_errors(combined_actual, combined_goals))
    print()
    print("=" * 88)
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validare xG Oracle (predicted) vs. xG real (actual, Flashscore/soccerfootballinfo)"
    )
    parser.add_argument("--min-league-n", type=int, default=3,
                         help="Prag minim de meciuri per ligă pentru a fi raportată individual (implicit 3)")
    args = parser.parse_args()
    run(args.min_league_n)


if __name__ == "__main__":
    main()
