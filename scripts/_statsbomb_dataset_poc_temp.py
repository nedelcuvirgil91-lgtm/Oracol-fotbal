"""
POC izolat, temporar — inspectează live structura dataset-ului Kaggle
"saurabhshahane/statsbomb-football-data" (propus de proprietarul produsului
ca sursa suplimentara pentru date istorice, in special cornere/cartonase/
faulturi, care lipsesc aproape complet pentru majoritatea ligilor).

Nu importă niciun modul de producție care ar scrie in Supabase. Refoloseste
STRICT sync/sources/kaggle.py (inspect_dataset), fara sa modifice acel
modul. Se șterge din cod după închiderea investigației.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

root = Path(__file__).parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))


DATASET_SLUG = "saurabhshahane/statsbomb-football-data"


if __name__ == "__main__":
    from sync.sources.kaggle import inspect_dataset, KaggleSourceError

    try:
        inspection = inspect_dataset(DATASET_SLUG)
    except KaggleSourceError as exc:
        print(f"EROARE: {exc}")
        sys.exit(1)

    print(f"=== {inspection.dataset_slug} ===")
    print(f"Cale locala: {inspection.local_path}")
    print(f"Numar fisiere CSV: {len(inspection.csv_files)}\n")

    for csv in inspection.csv_files:
        print(f"--- {csv.filename} ---")
        print(f"  randuri={csv.rows}  dimensiune={csv.file_size_bytes / (1024*1024):.1f} MB")
        print(f"  coloane ({len(csv.columns)}): {csv.columns}")
        print(f"  campuri obligatorii lipsa: {csv.missing_required_fields}")
        print(f"  campuri optionale cunoscute gasite: {csv.known_optional_fields}")
        print()
