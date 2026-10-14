"""Gardă: fiecare workflow din `.github/workflows/` trebuie să fie YAML valid.

DE CE EXISTĂ — un eșec real, 2026-10-14
`sensitivity_injury_penalty.yml` a fost scris cu numele neghilimelat:

    name: Football Oracle — Calea 0: plafonul penalizării de accidentări

Cele două puncte urmate de spațiu, într-un scalar neghilimelat, fac YAML-ul
invalid (`mapping values are not allowed here`, linia 1, coloana 32). Fișierul
a trecut `pytest tests/` — 3382 passed — a fost commis, împins, și abia GitHub
l-a respins: două rulări „failure" în 0 s, declanșate de `push`, plus
`workflow_dispatch` refuzat cu „Workflow does not have 'workflow_dispatch'
trigger" (GitHub nu putea citi declanșatorii dintr-un fișier pe care nu-l putea
parsa).

CE NU A PRINS GARDA EXISTENTĂ, ȘI DE CE
`tests/test_workflow_log_artifacts.py` citește workflow-urile ca **text** și
caută șiruri (`pipefail`, `mkdir -p`, `logs/`). Toate erau prezente, deci a
trecut — pe un fișier care nu era YAML. O gardă textuală nu poate decide dacă
fișierul e măcar parsabil; verifică conținutul presupunând structura.

Aceeași clasă de eroare ca garda care își găsea propriul comentariu
(`_doar_cod()`, 2026-08-27): verificarea se uita la ce scrie, nu la ce e.

CE APĂRĂ
  1. Fiecare `.yml`/`.yaml` din `.github/workflows/` se parsează.
  2. Fiecare are `on:` (declanșatori) și `jobs:` — un workflow fără ele e
     sintactic valid dar inert, iar GitHub nu-l semnalează ca eroare.
  3. Contrapondere: dacă folderul s-ar goli sau redenumi, garda ar trece VIDĂ
     fără să apere nimic.

Fără rețea, fără Supabase.
"""
from __future__ import annotations

import pathlib

import pytest

yaml = pytest.importorskip("yaml")

WORKFLOWS = pathlib.Path(__file__).resolve().parent.parent / ".github" / "workflows"


def _fisiere() -> list[pathlib.Path]:
    return sorted([*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml")])


def test_toate_workflow_urile_sunt_yaml_valid():
    """GARDA CENTRALĂ. Un workflow neparsabil e invizibil pentru orice gardă
    textuală și e respins abia de GitHub, după push."""
    rele = []
    for p in _fisiere():
        try:
            yaml.safe_load(p.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            prima = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
            rele.append(f"{p.name}: {prima}")
    assert not rele, (
        "Workflow-uri care NU se parsează ca YAML (GitHub le respinge, nu le "
        "rulează). Cauza tipică: două puncte urmate de spațiu într-un scalar "
        "neghilimelat, de ex. `name: Ceva: altceva` — se ghilimelează:\n  "
        + "\n  ".join(rele))


def test_fiecare_workflow_are_declansator_si_joburi():
    """Un workflow valid sintactic dar fără `on:` sau `jobs:` nu rulează
    niciodată, iar GitHub nu-l raportează ca eroare — tace."""
    incomplete = []
    for p in _fisiere():
        try:
            d = yaml.safe_load(p.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue   # raportat de testul de mai sus, nu de două ori
        if not isinstance(d, dict):
            incomplete.append(f"{p.name}: rădăcina nu e o mapare")
            continue
        # PyYAML normalizează `on:` la boolean True (YAML 1.1), deci se
        # acceptă ambele chei — altfel garda ar raporta fals TOATE fișierele.
        if "on" not in d and True not in d:
            incomplete.append(f"{p.name}: lipsește `on:`")
        if not d.get("jobs"):
            incomplete.append(f"{p.name}: lipsește `jobs:`")
    assert not incomplete, "Workflow-uri inerte:\n  " + "\n  ".join(incomplete)


def test_detectorul_chiar_prinde_yaml_invalid(tmp_path):
    """CONTRAPONDERE — construiește exact defectul din 14 octombrie și verifică
    faptul că e detectat. Fără asta, garda de mai sus ar putea trece fiindcă
    `yaml.safe_load` e mai permisiv decât cred, nu fiindcă totul e corect."""
    rupt = tmp_path / "rupt.yml"
    rupt.write_text(
        "name: Football Oracle — Calea 0: plafonul penalizarii\n"
        "on:\n  workflow_dispatch:\n"
        "jobs:\n  x:\n    runs-on: ubuntu-latest\n", encoding="utf-8")
    with pytest.raises(yaml.YAMLError):
        yaml.safe_load(rupt.read_text(encoding="utf-8"))

    reparat = tmp_path / "reparat.yml"
    reparat.write_text(
        'name: "Football Oracle — Calea 0: plafonul penalizarii"\n'
        "on:\n  workflow_dispatch:\n"
        "jobs:\n  x:\n    runs-on: ubuntu-latest\n", encoding="utf-8")
    d = yaml.safe_load(reparat.read_text(encoding="utf-8"))
    assert d["name"].startswith("Football Oracle"), "ghilimelarea trebuie să rezolve"
    assert d.get("jobs"), "fișierul reparat trebuie să aibă joburi"


def test_exista_workflow_uri_de_verificat():
    """Dacă folderul s-ar goli sau redenumi, gărzile de mai sus ar trece VIDE
    și nimeni n-ar observa că nu mai apără nimic."""
    n = len(_fisiere())
    assert n >= 30, f"doar {n} workflow-uri găsite în {WORKFLOWS} — garda pare oarbă"
