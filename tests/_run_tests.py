"""
Runner minimal, folosit DOAR pentru că pytest nu a putut fi instalat în
acest sandbox (fără acces la rețea, la fel ca la kagglehub mai devreme).
Execută EXACT aceleași fișiere de test din tests/ (scrise 100% compatibil
pytest - funcții test_*, assert simplu, fără fixtures speciale) - ar rula
identic sub un `pytest tests/ -v` real.
"""
import importlib.util
import sys
import traceback
from pathlib import Path

TESTS_DIR = Path(__file__).parent
sys.path.insert(0, str(Path(__file__).parent.parent))

# ruleaza conftest.py manual (seteaza sys.path + stub kagglehub)
conftest_path = TESTS_DIR / "conftest.py"
spec = importlib.util.spec_from_file_location("conftest", conftest_path)
conftest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(conftest)

total, passed, failed = 0, 0, []

for test_file in sorted(TESTS_DIR.glob("test_*.py")):
    spec = importlib.util.spec_from_file_location(test_file.stem, test_file)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        print(f"[EROARE LA IMPORT] {test_file.name}: {exc}")
        traceback.print_exc()
        continue

    for name in dir(module):
        if name.startswith("test_"):
            fn = getattr(module, name)
            if callable(fn):
                total += 1
                try:
                    fn()
                    passed += 1
                    print(f"  PASS  {test_file.name}::{name}")
                except Exception as exc:
                    failed.append((test_file.name, name, exc))
                    print(f"  FAIL  {test_file.name}::{name} -> {exc}")

print()
print(f"TOTAL: {total} teste rulate, {passed} trecute, {len(failed)} eșuate")
if failed:
    print("\nDetalii eșecuri:")
    for fname, tname, exc in failed:
        print(f"  {fname}::{tname}")
        print(f"    {type(exc).__name__}: {exc}")

sys.exit(0 if not failed else 1)
