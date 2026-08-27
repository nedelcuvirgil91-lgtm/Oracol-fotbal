"""Un workflow care ÎNCARCĂ `logs/` trebuie și să SCRIE acolo.

DEFECTUL, găsit 2026-08-27. Trei workflow-uri (`daily`, `night_sync`,
`sync_pre_match_odds`) aveau un pas `actions/upload-artifact` cu `path: logs/`
încă de la crearea lor (commit 3532e6b) — dar NIMIC nu scria vreodată acolo:
tot logging-ul mergea în `StreamHandler(sys.stdout)`, iar directorul `logs/`
nici nu exista. Cu `if-no-files-found: ignore`, eșecul era complet tăcut.
Intenția existase (`logs/` e în `.gitignore`); scrierea n-a fost implementată.

COSTUL, măsurat de două ori în aceeași zi: API-ul de log-uri GitHub întoarce
doar ultimele ~5.000 de linii, iar `night_sync` produce peste 100.000. Raportul
cu `step_durations_s` era la ~06:45, fereastra citibilă începea la 07:28 —
măsurătoarea exista și era inaccesibilă. Un artefact conține log-ul complet.

DE CE GARDA E PE INVARIANT, NU PE LISTĂ: cele trei nu au fost stricate de
cineva, ci s-au născut așa. Al patrulea workflow care adaugă un upload de
`logs/` fără `tee` ar reintroduce golul la fel de tăcut. Testul citește
workflow-urile de pe disc și verifică perechea, nu numele.

Fără rețea, fără Supabase.
"""
from __future__ import annotations

import re
from pathlib import Path

WORKFLOWS = Path(__file__).parent.parent / ".github" / "workflows"


def _fisiere():
    return sorted(WORKFLOWS.glob("*.yml"))


def _incarca_logs(text: str) -> bool:
    """Are un pas `upload-artifact` cu `path: logs/`?"""
    return "upload-artifact" in text and re.search(r"path:\s*logs/", text) is not None


def _scrie_in_logs(text: str) -> bool:
    """Redirectează ieșirea către un fișier din `logs/`?"""
    return re.search(r"tee\s+\"?logs/", text) is not None


def _doar_cod(text: str) -> str:
    """Textul fără liniile de comentariu YAML.

    [ADĂUGAT după o mutație NEPRINSĂ, 2026-08-27] Verificarea `"set -o pipefail"
    in text` trecea chiar după ce linia REALĂ era ștearsă din `night_sync.yml`
    — fiindcă explicația pe care o scrisesem deasupra conține exact acea frază
    („`set -o pipefail` NU e optional"). Garda își găsea propriul comentariu și
    se declara mulțumită.

    E aceeași clasă de eroare pe care o repar în alte părți: o verificare care
    pare să confirme ceva, dar confirmă altceva. Aici, cu cât comentariul e mai
    bine scris, cu atât garda e mai oarbă."""
    return "\n".join(
        linie for linie in text.splitlines() if not linie.lstrip().startswith("#")
    )


def test_exista_workflow_uri_care_incarca_logs():
    """Contrapondere: dacă redenumirea unui director face ca niciun workflow să
    nu mai potrivească, gărzile de mai jos ar trece VID — verzi fără să
    verifice nimic. Aici se confirmă că mai există ce verifica."""
    cu_upload = [f.name for f in _fisiere() if _incarca_logs(f.read_text(encoding="utf-8"))]
    assert cu_upload, (
        "niciun workflow nu mai incarca `logs/` — daca e deliberat, sterge si "
        "acest fisier de test; altfel garda de mai jos trece degeaba"
    )


def test_orice_workflow_care_incarca_logs_chiar_scrie_acolo():
    """GARDA CENTRALĂ. Un artefact promis și niciodată produs e mai rău decât
    unul absent: pare că ai datele până în ziua în care ai nevoie de ele."""
    lipsuri = []
    for f in _fisiere():
        text = f.read_text(encoding="utf-8")
        if _incarca_logs(text) and not _scrie_in_logs(text):
            lipsuri.append(f.name)
    assert not lipsuri, (
        "workflow-uri care incarca `logs/` dar nu scriu nimic acolo "
        f"(artefact mereu gol): {lipsuri}"
    )


def test_orice_redirectare_spre_logs_are_pipefail():
    """GARDA DE SIGURANȚĂ, la fel de importantă ca prima.

    Shell-ul implicit GitHub e `bash -e`, FĂRĂ pipefail (verificat: niciun
    workflow din repo nu declară `shell:`). Într-un pipeline `python ... | tee`,
    codul de ieșire e al ULTIMEI comenzi — adică al lui `tee`, care reușește
    aproape întotdeauna. Fără `set -o pipefail`, o rulare EȘUATĂ ar fi raportată
    ca reușită: am transforma o îmbunătățire de observabilitate într-o pierdere
    de semnal, exact opusul scopului."""
    fara_garda = []
    for f in _fisiere():
        text = f.read_text(encoding="utf-8")
        if _scrie_in_logs(text) and "set -o pipefail" not in _doar_cod(text):
            fara_garda.append(f.name)
    assert not fara_garda, (
        "`tee` fara `set -o pipefail` masheaza codul de iesire — o rulare "
        f"esuata ar fi raportata ca reusita: {fara_garda}"
    )


def test_directorul_e_creat_inainte_de_scriere():
    """`logs/` e în `.gitignore` și nu există în repo — `tee` ar eșua fără
    `mkdir -p`. Detaliu mic, dar exact genul care face fixul să nu funcționeze
    la prima rulare reală."""
    fara_mkdir = []
    for f in _fisiere():
        text = f.read_text(encoding="utf-8")
        if _scrie_in_logs(text) and not re.search(r"mkdir\s+-p\s+logs", _doar_cod(text)):
            fara_mkdir.append(f.name)
    assert not fara_mkdir, f"`tee logs/...` fara `mkdir -p logs`: {fara_mkdir}"


def test_numele_fisierului_contine_marcaj_temporal():
    """Fără timestamp, două rulări în aceeași zi s-ar suprascrie — și tocmai
    rularea pe care vrei s-o compari cu cea anterioară ar dispărea."""
    fara_timestamp = []
    for f in _fisiere():
        text = f.read_text(encoding="utf-8")
        if not _scrie_in_logs(text):
            continue
        for linie in text.splitlines():
            if "tee" in linie and "logs/" in linie and "date -u" not in linie:
                fara_timestamp.append(f"{f.name}: {linie.strip()}")
    assert not fara_timestamp, (
        f"nume de fisier fara marcaj temporal (suprascriere intre rulari): {fara_timestamp}"
    )


def test_cele_trei_workflow_uri_reparate_azi_sunt_acoperite():
    """Cazurile REALE care au motivat fixul. Dacă vreunul pierde `tee` la o
    editare viitoare, testul îl numește direct."""
    for nume in ("night_sync.yml", "daily.yml", "sync_pre_match_odds.yml"):
        text = (WORKFLOWS / nume).read_text(encoding="utf-8")
        assert _incarca_logs(text), f"{nume}: nu mai incarca `logs/`"
        assert _scrie_in_logs(text), f"{nume}: nu mai scrie in `logs/`"
        assert "set -o pipefail" in _doar_cod(text), f"{nume}: fara pipefail"
