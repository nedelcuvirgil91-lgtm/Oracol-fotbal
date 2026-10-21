"""Raportul pe etape al lui `night_sync` se persistă (adăugat 2026-10-21).

GOLUL. `run()` calcula raportul pe cele 10 etape — nume, reușită, durată — îl
tipărea, și îl **arunca**. Deci la întrebarea „ce etape au eșuat săptămâna
trecută?" nu exista niciun răspuns: singura sursă era log-ul fiecărei rulări,
iar API-ul GitHub întoarce doar ultimele ~5000 de linii dintr-o rulare care
produce peste 100.000. Limita a fost lovită de două ori în aceeași zi (corpul
răspunsului SFI, și rapoartele etapelor din rulările mai vechi).

Consecința practică, nu teoretică: lista etapelor „critice" din pasul anterior
a trebuit lăsată la UNA singură, fiindcă nu există istoric de eșecuri pe care
s-o întemeiezi. Orice altă alegere ar fi fost ghicită.

DE CE `automation_runs` ȘI NU O TABELĂ NOUĂ. Tabela are deja fix câmpurile
necesare, și are deja producători din afara Learning Core (`ADR-040`,
`ADR-052`) — deci „e doar pentru Learning Core" era fals. Zero schemă nouă.

DE CE UN SINGUR RÂND PE RULARE, nu unul pe etapă — măsurat:
`list_recent_runs(limit=50)` nu filtrează pe `producer` și alimentează ecranul
„Activity Log". La ~13 rânduri/zi, 50 de rânduri ≈ 4 zile; 10 rânduri/noapte
ar fi redus istoricul vizibil la ~2 zile, cu ~43% succese de rutină. Aș fi
reparat un punct orb creând altul.
"""
from __future__ import annotations

import json

import pytest

import automation_runs as ar
import sync.run_night as rn


# ════════════════════════════════════════════════════════════════════════════
# Rezumatul — funcție pură, deci testabilă fără bază și fără o rulare reală
# ════════════════════════════════════════════════════════════════════════════

RAPORT = [
    {"stage": "1-4. Discovery", "ok": True, "critic": False, "duration_s": 1159.3,
     "detail": {"step_durations_s": {"history_sync": 587.4, "results": 9.2}}},
    {"stage": "Batch", "ok": False, "critic": True, "duration_s": 2.3,
     "error": "[Errno 36] File name too long"},
    {"stage": "Backup", "ok": True, "critic": False, "duration_s": 4.7},
]


def test_rezumatul_numara_corect_etapele():
    r = rn.rezumat_pentru_audit(RAPORT, "2026-10-21T10:29:56", "2026-10-21T11:37:02")
    assert r["etape_total"] == 3
    assert r["etape_reusite"] == 2
    assert r["etape_esuate"] == 1
    assert r["critice_esuate"] == ["Batch"]


def test_rezumatul_pastreaza_defalcarea_pe_pasi():
    """`step_durations_s` se calcula corect și se arunca la ultima linie —
    exact clasa de defect deja documentată. Aici devine interogabil."""
    r = rn.rezumat_pentru_audit(RAPORT, "a", "b")
    assert r["etape"][0]["pasi_s"] == {"history_sync": 587.4, "results": 9.2}


def test_rezumatul_pastreaza_eroarea_etapei_esuate():
    r = rn.rezumat_pentru_audit(RAPORT, "a", "b")
    assert "File name too long" in r["etape"][1]["eroare"]


def test_rezumatul_NU_copiaza_detail_intreg():
    """Contraponderea care ține rândul de audit un rând de audit, nu un
    depozit: `detail` e arbitrar ca mărime."""
    raport = [{"stage": "X", "ok": True, "duration_s": 1.0,
               "detail": {"balast": "y" * 100_000, "step_durations_s": {"p": 1}}}]
    r = rn.rezumat_pentru_audit(raport, "a", "b")
    text = json.dumps(r)
    assert "balast" not in text
    assert len(text) < 2000, f"rezumatul a crescut la {len(text)} octeți"


def test_rezumatul_e_serializabil_ca_jsonb():
    """Dacă nu e serializabil, scrierea ar eșua abia în producție."""
    json.dumps(rn.rezumat_pentru_audit(RAPORT, "a", "b"))


def test_rezumatul_citeste_github_run_id_din_mediu(monkeypatch):
    """Legătura cu log-ul complet: rândul trebuie să poată trimite la rularea
    exactă, fiindcă API-ul de log-uri se taie la ~5000 de linii."""
    monkeypatch.setenv("GITHUB_RUN_ID", "39584871018")
    assert rn.rezumat_pentru_audit(RAPORT, "a", "b")["github_run_id"] == "39584871018"


def test_rezumatul_fara_GITHUB_RUN_ID_nu_arunca(monkeypatch):
    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
    assert rn.rezumat_pentru_audit(RAPORT, "a", "b")["github_run_id"] is None


def test_rezumatul_NU_muta_raportul():
    copie = [dict(r) for r in RAPORT]
    rn.rezumat_pentru_audit(RAPORT, "a", "b")
    assert RAPORT == copie


# ════════════════════════════════════════════════════════════════════════════
# REGULA CENTRALĂ: observabilitatea nu are voie să rupă lucrul pe care îl observă
#
# Exact lecția reparației de cache din aceeași zi: o funcție auxiliară care
# aruncă în apelant a omorât o etapă întreagă patru nopți la rând. Un rând de
# evidență care nu se poate scrie e o pierdere de informație; o rulare de
# noapte oprită din cauza lui ar fi o pierdere de DATE.
# ════════════════════════════════════════════════════════════════════════════

class _ArExploziv:
    def write_run(self, *a, **k): raise RuntimeError("Supabase picat")
    def start_run(self, *a, **k): raise RuntimeError("Supabase picat")
    def complete_run(self, *a, **k): raise RuntimeError("Supabase picat")
    def fail_run(self, *a, **k): raise RuntimeError("Supabase picat")


@pytest.fixture
def ar_exploziv(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "automation_runs", _ArExploziv())


def test_deschiderea_nu_arunca_daca_baza_e_picata(ar_exploziv):
    assert rn._deschide_rand_audit("2026-10-21T10:00:00") is None


def test_inchiderea_nu_arunca_daca_baza_e_picata(ar_exploziv):
    rn._inchide_rand_audit(123, {"x": 1}, [])  # nu trebuie să ridice


def test_inchiderea_cu_run_id_None_nu_apeleaza_nimic(monkeypatch):
    """Dacă deschiderea a eșuat, închiderea nu are ce închide — și nu trebuie
    să încerce, altfel ar produce o a doua eroare pentru aceeași cauză."""
    apeluri = []

    class _Spion:
        def complete_run(self, *a, **k): apeluri.append("complete")
        def fail_run(self, *a, **k): apeluri.append("fail")

    import sys
    monkeypatch.setitem(sys.modules, "automation_runs", _Spion())
    rn._inchide_rand_audit(None, {"x": 1}, [])
    assert apeluri == []


# ════════════════════════════════════════════════════════════════════════════
# Starea finală: `failed` DOAR pentru etape critice — aceeași regulă ca
# la codul de ieșire, ca baza și culoarea jobului să nu se contrazică
# ════════════════════════════════════════════════════════════════════════════

class _ArSpion:
    def __init__(self): self.apeluri = []
    def write_run(self, *a, **k):
        self.apeluri.append(("write_run", a, k)); return 777
    def start_run(self, run_id): self.apeluri.append(("start_run", run_id)); return True
    def complete_run(self, run_id, summary=None):
        self.apeluri.append(("complete_run", run_id, summary)); return True
    def fail_run(self, run_id, error_detail, summary=None):
        self.apeluri.append(("fail_run", run_id, error_detail, summary)); return True


@pytest.fixture
def ar_spion(monkeypatch):
    spion = _ArSpion()
    import sys
    monkeypatch.setitem(sys.modules, "automation_runs", spion)
    return spion


def test_fara_etape_critice_esuate_randul_se_inchide_COMPLETED(ar_spion):
    rn._inchide_rand_audit(777, {"etape": []}, [])
    assert [a[0] for a in ar_spion.apeluri] == ["complete_run"]


def test_cu_etapa_critica_esuata_randul_se_inchide_FAILED(ar_spion):
    rn._inchide_rand_audit(777, {"etape": []}, ["Batch"])
    tip, run_id, detaliu, rezumat = ar_spion.apeluri[0]
    assert tip == "fail_run" and run_id == 777
    assert "Batch" in detaliu


def test_randul_FAILED_pastreaza_TOTUSI_rezumatul(ar_spion):
    """Partea pentru care `fail_run` a primit parametrul opțional: defalcarea
    se pierdea exact pe rulările unde contează cel mai mult."""
    rezumat = {"etape": [{"etapa": "Batch", "ok": False}]}
    rn._inchide_rand_audit(777, rezumat, ["Batch"])
    assert ar_spion.apeluri[0][3] == rezumat


def test_deschiderea_foloseste_DATA_UTC_drept_cheie_de_identitate(ar_spion):
    """Cheia cerută de ADR-026 §2. Cu ea, o a doua rulare pornită cât prima e
    încă `running` o refolosește; una de a doua zi creează un rând nou."""
    rn._deschide_rand_audit("2026-10-21T10:29:56.123+00:00")
    tip, args, kwargs = ar_spion.apeluri[0]
    assert tip == "write_run"
    assert kwargs.get("target_key") == "2026-10-21"
    assert args[0] == "night_sync" and args[2] == "T1"


def test_tier_ul_e_T1_observational_fara_decizie(ar_spion):
    """T1 = evidență, nu decizie. Un tier care cere aprobare umană ar face
    rândul ăsta să apară în Decision Feed — ar fi zgomot, zilnic."""
    rn._deschide_rand_audit("2026-10-21T00:00:00")
    assert ar_spion.apeluri[0][1][2] == "T1"


def test_randul_se_si_PORNESTE_nu_rAmane_queued(ar_spion):
    rn._deschide_rand_audit("2026-10-21T00:00:00")
    assert [a[0] for a in ar_spion.apeluri] == ["write_run", "start_run"]


# ════════════════════════════════════════════════════════════════════════════
# `fail_run` cu `summary` — apelanții existenți rămân neatinși
# ════════════════════════════════════════════════════════════════════════════

def test_fail_run_ramane_compatibil_cu_apelantii_existenti():
    """Parametrul e opțional. Dacă ar deveni obligatoriu, cele ~12 apeluri din
    `learning_core/` ar cădea abia în producție."""
    import inspect
    p = inspect.signature(ar.fail_run).parameters["summary"]
    assert p.default is None


def test_fail_run_fara_summary_NU_trimite_cheia(monkeypatch):
    """Contraponderea: un `summary: None` trimis explicit ar ȘTERGE un rezumat
    scris anterior de altcineva."""
    trimis = {}

    class _Q:
        def update(self, payload): trimis.update(payload); return self
        def eq(self, *a): return self
        def execute(self): return type("R", (), {"data": [{"id": 1}]})()

    class _C:
        def table(self, _): return _Q()

    monkeypatch.setattr(ar, "get_client", lambda: _C())
    ar.fail_run(1, "eroare")
    assert "summary" not in trimis
    assert trimis["status"] == "failed"
