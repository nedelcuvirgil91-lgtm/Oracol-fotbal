"""
================================================================================
FOOTBALL ORACLE — sync/verify_dataset_freshness.py (v1.0)
Script de verificare INDEPENDENT, separat complet de import_historical.py.

Nu foloseste nicio logica din pipeline-ul de import (cutoff, clasificare,
normalizare). Scaneaza EXPLICIT si COMPLET coloana de data din Matches.csv
si EloRatings.csv si raporteaza:
  - data minima si maxima REALA gasita in fisier (peste tot fisierul, fara
    nicio filtrare de cutoff sau alta logica de business)
  - numarul de randuri cu data neparsabila
  - numarul de randuri cu data mai noua decat un prag de referinta (implicit
    2025-06-01, valoarea raportata anterior de import_historical.py, pentru
    comparatie directa)

Read-only. Nu scrie nimic, nici in Supabase, nici local (in afara de output
in consola). Motivatie: raportul din import_historical.py deduce intervalul
de date din randurile deja filtrate de cutoff — o inferenta, nu o verificare
directa. Acest script raspunde direct, din continutul brut al fisierului,
la intrebarea "exista randuri mai noi care nu au fost procesate?".
================================================================================
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import pandas as pd

root = Path(__file__).parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from sync.sources.kaggle import MAIN_DATASET, inspect_dataset

CHUNK_SIZE = 20000
DEFAULT_REFERENCE_DATE = date(2025, 6, 1)


def _scan_date_column(csv_path: str, date_col: str, label: str, reference_date: date) -> None:
    min_date: date | None = None
    max_date: date | None = None
    total_rows = 0
    invalid_rows = 0
    rows_after_reference = 0
    newest_examples: list[str] = []

    for chunk in pd.read_csv(csv_path, usecols=[date_col], dtype=str, chunksize=CHUNK_SIZE):
        parsed = pd.to_datetime(chunk[date_col], errors="coerce")
        total_rows += len(chunk)
        invalid_rows += int(parsed.isna().sum())

        valid = parsed.dropna()
        if valid.empty:
            continue

        chunk_min = valid.min().date()
        chunk_max = valid.max().date()
        if min_date is None or chunk_min < min_date:
            min_date = chunk_min
        if max_date is None or chunk_max > max_date:
            max_date = chunk_max

        after_ref_mask = valid.dt.date > reference_date
        rows_after_reference += int(after_ref_mask.sum())
        if after_ref_mask.any() and len(newest_examples) < 5:
            for d in sorted(valid[after_ref_mask].dt.date.unique(), reverse=True):
                if len(newest_examples) >= 5:
                    break
                newest_examples.append(d.isoformat())

    print(f"=== {label} (coloana: {date_col}) ===")
    print(f"  Randuri totale in fisier         : {total_rows}")
    print(f"  Randuri cu data neparsabila       : {invalid_rows}")
    print(f"  Data minima gasita (REALA)        : {min_date}")
    print(f"  Data maxima gasita (REALA)        : {max_date}")
    print(f"  Randuri cu data > {reference_date.isoformat()}      : {rows_after_reference}")
    if newest_examples:
        print(f"  Exemple de date mai noi gasite    : {newest_examples}")
    print()


def run(reference_date: date = DEFAULT_REFERENCE_DATE) -> None:
    print("Descarc / folosesc din cache dataset-ul Kaggle pentru verificare independenta...")
    inspection = inspect_dataset(MAIN_DATASET)

    for summary in inspection.csv_files:
        lower_to_original = {c.lower(): c for c in summary.columns}
        date_col = lower_to_original.get("matchdate") or lower_to_original.get("date")

        if date_col is None:
            print(f"[SKIP] '{summary.filename}' — nicio coloana de data recunoscuta ({summary.columns})")
            continue

        _scan_date_column(summary.path, date_col, summary.filename, reference_date)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Verificare independenta a datei minime/maxime reale din CSV-urile Kaggle."
    )
    parser.add_argument(
        "--reference-date", type=str, default=DEFAULT_REFERENCE_DATE.isoformat(),
        help="Data de referinta (YYYY-MM-DD) fata de care se numara randurile mai noi. "
             "Implicit: 2025-06-01 (valoarea raportata anterior de import_historical.py).",
    )
    args = parser.parse_args()
    ref = date.fromisoformat(args.reference_date)

    run(reference_date=ref)

