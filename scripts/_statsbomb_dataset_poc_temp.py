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

import sys
import traceback
from pathlib import Path

root = Path(__file__).parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))


DATASET_SLUG = "saurabhshahane/statsbomb-football-data"
OUTPUT_FILE = root / "scripts" / "_statsbomb_poc_output_temp.txt"


if __name__ == "__main__":
    from sync.sources.kaggle import inspect_dataset, KaggleSourceError

    lines: list[str] = []

    try:
        inspection = inspect_dataset(DATASET_SLUG)

        lines.append(f"=== {inspection.dataset_slug} ===")
        lines.append(f"Cale locala: {inspection.local_path}")
        lines.append(f"Numar fisiere CSV: {len(inspection.csv_files)}\n")

        for csv in inspection.csv_files:
            lines.append(f"--- {csv.filename} ---")
            lines.append(f"  randuri={csv.rows}  dimensiune={csv.file_size_bytes / (1024*1024):.1f} MB")
            lines.append(f"  coloane ({len(csv.columns)}): {csv.columns}")
            lines.append(f"  campuri obligatorii lipsa: {csv.missing_required_fields}")
            lines.append(f"  campuri optionale cunoscute gasite: {csv.known_optional_fields}")
            lines.append("")

        OUTPUT_FILE.write_text("\n".join(lines), encoding="utf-8")
        print("\n".join(lines))
    except KaggleSourceError as exc:
        OUTPUT_FILE.write_text(f"EROARE (KaggleSourceError): {exc}", encoding="utf-8")
        print(f"EROARE: {exc}")
        sys.exit(1)
    except Exception as exc:
        tb = traceback.format_exc()
        OUTPUT_FILE.write_text(f"EROARE ({type(exc).__name__}): {exc}\n\n{tb}", encoding="utf-8")
        print(f"EROARE ({type(exc).__name__}): {exc}")
        print(tb)
        sys.exit(1)
