import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Stub minimal pt kagglehub - doar pt satisfacerea importului la nivel de
# modul in sync/import_historical.py; nu descarca nimic, nu e folosit real
# in aceste teste. NU face parte din dependintele reale ale proiectului.
STUBS_DIR = ROOT / "tests" / "_stubs"
STUBS_DIR.mkdir(exist_ok=True)
kagglehub_stub = STUBS_DIR / "kagglehub.py"
if not kagglehub_stub.exists():
    kagglehub_stub.write_text(
        "def dataset_download(slug):\n"
        "    raise RuntimeError('kagglehub stub - doar pt teste, nu descarca nimic')\n"
    )
sys.path.insert(0, str(STUBS_DIR))
