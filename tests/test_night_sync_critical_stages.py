"""`night_sync` ieșea cu 0 oricâte etape eșuau (reparat 2026-10-21).

DEFECTUL, și de ce a costat patru nopți. `run_night.run()` calcula corect
raportul pe etape, îl tipărea corect, și îl **arunca**: `__main__` apela
`run()` fără să citească valoarea întoarsă. Deci jobul GitHub era verde chiar
cu „1 eșuate din 9" scris în propriul raport.

Consecința reală: etapa „Challenger Shadow Batch" a murit la 2,3 s în rulările
din 18-21 octombrie (nume de fișier de cache peste 255 de octeți) și nimeni
n-a observat — fiindcă nimic nu putea fi roșu. Un indicator care nu poate fi
roșu nu e un indicator, exact ca `coverage_percent` fix la 100%.

REPARAȚIA, și de ce NU e un `exit 1` global. Un job care devine roșu la orice
eșec reproduce problema `check_data_health` (roșu zilnic prin design, deci
antrenează ignorarea). Aici: `critic=False` IMPLICIT, deci nicio etapă nu
colorează jobul decât dacă e marcată **explicit**. Lista crește prin decizie.

CE NU VERIFICĂ FIȘIERUL ĂSTA. Nu verifică „etapele X, Y, Z sunt critice" —
aia ar fi o listă, care se învechește la prima marcare nouă. Verifică
invariantul (marcat → roșu; nemarcat → verde) plus faptul că batch-ul ESTE
marcat, fiindcă aia e chiar schimbarea de comportament cerută.
"""
from __future__ import annotations

import ast
import inspect

import pytest

import sync.run_night as rn


# ════════════════════════════════════════════════════════════════════════════
# Invariantul: doar o etapă CRITICĂ eșuată face jobul roșu
# ════════════════════════════════════════════════════════════════════════════

def test_raport_curat_nu_produce_nicio_etapa_critica_esuata():
    raport = [
        {"stage": "A", "ok": True, "critic": True},
        {"stage": "B", "ok": True, "critic": False},
    ]
    assert rn.etape_critice_esuate(raport) == []


def test_etapa_CRITICA_esuata_e_raportata():
    raport = [
        {"stage": "A", "ok": True, "critic": False},
        {"stage": "Batch", "ok": False, "critic": True},
    ]
    assert rn.etape_critice_esuate(raport) == ["Batch"]


def test_CONTRAPONDERE_etapa_NEcritica_esuata_NU_inroseste_jobul():
    """Partea care previne reproducerea problemei `check_data_health`. Dacă
    testul ăsta cade, înseamnă că schimbarea a devenit un `exit 1` global, iar
    rulările cu eșecuri benigne vor fi roșii — adică exact mecanismul care
    antrenează ignorarea alertelor."""
    raport = [
        {"stage": "Vreme", "ok": False, "critic": False},
        {"stage": "Cleanup", "ok": False, "critic": False},
    ]
    assert rn.etape_critice_esuate(raport) == []


def test_mai_multe_etape_critice_esuate_sunt_TOATE_numite():
    """Mesajul de ieșire trebuie să le conțină pe toate: dacă două etape
    critice cad, raportarea doar a primeia ar ascunde a doua cauză."""
    raport = [
        {"stage": "Unu", "ok": False, "critic": True},
        {"stage": "Doi", "ok": True, "critic": True},
        {"stage": "Trei", "ok": False, "critic": True},
    ]
    assert rn.etape_critice_esuate(raport) == ["Unu", "Trei"]


@pytest.mark.parametrize("rand", [
    {"stage": "fara_critic", "ok": False},                 # câmp absent
    {"stage": "fara_ok", "critic": True},                  # `ok` absent
])
def test_raport_incomplet_nu_arunca(rand):
    """Un raport scris de cod mai vechi (fără `critic`) nu trebuie să ridice și
    nu trebuie să devină retroactiv critic. Al doilea caz e mai subtil: `ok`
    absent se citește ca eșec (implicit `False`), ceea ce e alegerea prudentă —
    o etapă despre care nu știm că a reușit nu se declară reușită."""
    rezultat = rn.etape_critice_esuate([rand])
    assert isinstance(rezultat, list)


def test_functia_e_PURA_nu_citeste_si_nu_scrie_nimic():
    """Dacă ar atinge baza sau discul, decizia „roșu/verde" n-ar mai putea fi
    testată fără o rulare reală — exact motivul pentru care a fost scoasă într-o
    funcție separată."""
    sursa = inspect.getsource(rn.etape_critice_esuate)
    for interzis in ("supabase", "client", "open(", "requests", "Path(",
                     "execute(", "print("):
        assert interzis not in sursa, f"funcția nu mai e pură: conține {interzis!r}"


def test_raportul_NU_e_mutat_de_functie():
    """Contrapondere la o implementare care ar „normaliza" raportul pe loc."""
    raport = [{"stage": "A", "ok": False, "critic": True}]
    copie = [dict(r) for r in raport]
    rn.etape_critice_esuate(raport)
    assert raport == copie


# ════════════════════════════════════════════════════════════════════════════
# FIRUL dintre cele două capete — găsit lipsă printr-o mutație, nu prin recitire
#
# Mutația care a trecut: `"critic": critic` șters din ramura de EȘEC a lui
# `_run_stage`. Apelurile pasau în continuare `critic=True` (gărzile AST
# treceau), funcția pură funcționa în continuare pe dicționare scrise de mână
# (invarianții treceau) — dar între ele marcajul se pierdea, deci un batch
# picat redevenea verde. Exact clasa „extragere bună, fir netăiat" deja
# documentată la `step_durations_s`: calculat corect, cablat corect, niciodată
# afișat. Testele de mai jos exercită mecanismul REAL, fără dicționare
# inventate: `_run_stage` primește o funcție care chiar aruncă.
# ════════════════════════════════════════════════════════════════════════════

def test_FIR_etapa_critica_care_arunca_ajunge_pana_la_codul_de_ieSire():
    """Singurul test care traversează tot lanțul: funcție care aruncă →
    `_run_stage` → rândul din raport → `etape_critice_esuate`."""
    def explodeaza():
        raise RuntimeError("[Errno 36] File name too long")

    raport: list[dict] = []
    rn._run_stage("Batch de probă", explodeaza, raport, critic=True)

    assert len(raport) == 1 and raport[0]["ok"] is False
    assert raport[0].get("critic") is True, (
        "`_run_stage` nu a pus `critic` în rândul de EȘEC — marcajul se pierde "
        "între apel și decizie, deci jobul ar rămâne verde")
    assert rn.etape_critice_esuate(raport) == ["Batch de probă"]


def test_FIR_etapa_critica_care_REUSESTE_nu_inroseste():
    raport: list[dict] = []
    rn._run_stage("Batch de probă", lambda: {"ok": 1}, raport, critic=True)
    assert raport[0]["ok"] is True
    assert raport[0].get("critic") is True, (
        "`critic` lipsește din rândul de SUCCES — raportul devine asimetric, "
        "iar orice cititor care îl grupează pe `critic` vede altceva")
    assert rn.etape_critice_esuate(raport) == []


def test_FIR_etapa_NEmarcata_care_arunca_lasa_jobul_verde():
    """Contraponderea firului: aceeași cale, fără marcaj, trebuie să rămână
    inofensivă — altfel am făcut un `exit 1` global pe ascuns."""
    def explodeaza():
        raise RuntimeError("eșec benign")

    raport: list[dict] = []
    rn._run_stage("Etapă minoră", explodeaza, raport)
    assert raport[0]["ok"] is False
    assert raport[0].get("critic") is False
    assert rn.etape_critice_esuate(raport) == []


def test_FIR_o_etapa_care_arunca_NU_opreste_rularea():
    """Comportamentul care trebuie păstrat neschimbat: eșecul unei etape nu
    propagă excepția, ca etapele următoare să ruleze. Jobul devine roșu la
    FINAL, nu se oprește la mijloc — altfel reparația ar transforma un eșec
    parțial în rulare trunchiată, adică ar pierde date."""
    raport: list[dict] = []
    rn._run_stage("Cade", lambda: (_ for _ in ()).throw(RuntimeError("x")),
                  raport, critic=True)
    rn._run_stage("Merge după ea", lambda: "ok", raport)
    assert [r["ok"] for r in raport] == [False, True]


# ════════════════════════════════════════════════════════════════════════════
# Cablarea — invariantul de mai sus nu valorează nimic dacă nimic nu e marcat
# ════════════════════════════════════════════════════════════════════════════

def _apeluri_run_stage() -> list[dict]:
    """Fiecare apel `_run_stage(...)` din `run()`, citit prin AST.

    AST, nu text: comentariul de deasupra apelului marcat conține chiar
    `critic=True` ca explicație, deci o gardă textuală ar trece și pe un cod
    din care marcajul real a fost șters. A șasea instanță a clasei, după
    `pipefail`, numele de secrete, docstring-ul ADR-073, titlul Decision
    Feed-ului și cheia de cache.
    """
    arbore = ast.parse(inspect.getsource(rn))
    apeluri = []
    for n in ast.walk(arbore):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == "_run_stage"):
            continue
        nume = n.args[0].value if (n.args and isinstance(n.args[0], ast.Constant)) else "?"
        critic = False
        for kw in n.keywords:
            if kw.arg == "critic" and isinstance(kw.value, ast.Constant):
                critic = bool(kw.value.value)
        apeluri.append({"stage": nume, "critic": critic})
    return apeluri


def test_CONTRAPONDERE_garda_AST_chiar_vede_apelurile():
    """Previne trecerea VIDĂ: dacă `_run_stage` ar fi redenumit sau apelat
    altfel, testele de cablare de mai jos ar trece fără să verifice nimic."""
    apeluri = _apeluri_run_stage()
    assert len(apeluri) >= 9, f"garda vede doar {len(apeluri)} apeluri"
    assert all(a["stage"] != "?" for a in apeluri), "numele etapelor nu se citesc"


def test_challenger_shadow_batch_E_marcat_critic():
    """Chiar schimbarea de comportament cerută. Dacă pică, jobul redevine verde
    când batch-ul moare — adică defectul reparat s-a întors."""
    marcate = [a["stage"] for a in _apeluri_run_stage() if a["critic"]]
    assert any("Challenger Shadow Batch" in s for s in marcate), (
        f"batch-ul nu e marcat critic; marcate: {marcate}")


def test_cel_putin_o_etapa_e_marcata_altfel_reparatia_e_inerta():
    assert [a for a in _apeluri_run_stage() if a["critic"]], (
        "nicio etapă marcată critică — `etape_critice_esuate()` nu poate "
        "întoarce niciodată nimic, deci reparația e cod mort")


def test_majoritatea_etapelor_rAmân_NEmarcate_deliberat():
    """Nu e o listă, e o proporție: marcarea e excepția, nu regula. Dacă
    vreodată majoritatea etapelor devin critice, jobul se apropie de un
    `exit 1` global și decizia trebuie reluată explicit, nu strecurată."""
    apeluri = _apeluri_run_stage()
    marcate = [a for a in apeluri if a["critic"]]
    assert len(marcate) * 2 <= len(apeluri), (
        f"{len(marcate)} din {len(apeluri)} etape sunt critice — prea multe "
        "pentru un mecanism gândit ca excepție")


def test_implicitul_parametrului_critic_e_False():
    """North Star #3 aplicat aici: nimic nu pornește activ. O etapă nouă,
    adăugată fără să se gândească la asta, NU colorează jobul."""
    semnatura = inspect.signature(rn._run_stage)
    assert semnatura.parameters["critic"].default is False


def test_main_citeste_raportul_si_iese_cu_cod(tmp_path):
    """Defectul original era exact aici: `__main__` apela `run()` și arunca
    valoarea. Verificat prin AST pe blocul `if __name__ == '__main__'`."""
    arbore = ast.parse(inspect.getsource(rn))
    bloc = [n for n in arbore.body if isinstance(n, ast.If)]
    assert bloc, "nu există bloc `if __name__ == ...`"
    text_bloc = "\n".join(ast.dump(n) for b in bloc for n in ast.walk(b))
    assert "etape_critice_esuate" in text_bloc, (
        "`__main__` nu consultă etapele critice — raportul e aruncat, ca în "
        "defectul reparat")
    assert "SystemExit" in text_bloc, "`__main__` nu poate ieși cu cod nenul"


def test_run_intoarce_in_continuare_raportul():
    """`run()` e apelată și din alte locuri ca funcție; semnătura nu are voie
    să se schimbe într-una care iese din proces."""
    sursa = inspect.getsource(rn.run)
    assert "return report" in sursa
    assert "SystemExit" not in sursa, (
        "`run()` nu are voie să iasă din proces — doar `__main__` decide codul "
        "de ieșire, altfel orice apelant programatic ar fi omorât")
