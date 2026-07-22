import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# [ADAUGAT — eliminare completă a cheilor hardcodate, R4.1] key_manager.py nu
# mai are niciun literal hardcodat — toate cele 6 chei se încarcă exclusiv
# din variabile de mediu. Testele au nevoie ca `is_available()` să întoarcă
# True (calea normală de gating, nu starea "neconfigurat"), NU de chei
# funcționale — niciun test din suită face vreun apel HTTP real (politica de
# proiect: fără dependință de rețea). `setdefault` — dacă o variabilă reală e
# deja setată (CI cu secrete adevărate), nu o suprascrie. Setate la nivel de
# modul, înainte de orice colectare de teste, ca să fie garantat active
# înaintea primei instanțieri a singleton-ului APIKeyManager (altfel un test
# care apelează get_key_manager() înaintea acestui fișier ar bloca override-ul
# — singleton-ul e cache-uit global, per proces).
for _env_var in (
    "API_FOOTBALL_KEY", "ODDS_API_KEY", "WEATHER_API_KEY",
    "RAPIDAPI_KEY_SPORTAPI", "RAPIDAPI_KEY_FREELIVEFOOTBALL", "FOOTBALL_DATA_KEY",
):
    os.environ.setdefault(_env_var, f"test-{_env_var.lower()}-not-a-real-secret")

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
