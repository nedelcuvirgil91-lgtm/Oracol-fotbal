"""Gărzi pentru relurea campionului (`scripts/replay_champion_on_persisted_inputs.py`).

DE CE EXISTĂ, și de ce aici și nu în `test_poc_isolation.py`
Scriptul a fost scris întâi ca `_poc_replay_champion_temp.py`, iar garda 4 din
`tests/test_poc_isolation.py` a căzut — corect. În proiect `_poc_*` denumește o
clasă precisă: validarea unei surse sau chei EXTERNE noi, căreia niciun workflow
nu-i dă credențiale Supabase. Scriptul de aici e opusul — o analiză a datelor
NOASTRE, care fără credențiale nu are ce măsura. Numele afirma o categorie din
care nu face parte; garda a prins o eroare de încadrare, nu un fals pozitiv.

Mutat în clasa corectă (`scripts/ablation_form_weighting.py`,
`scripts/sensitivity_injury_penalty.py` — scripturi de măsurare care STAU pe
`main`), îi revine obligația acelei clase: read-only IMPUS, nu promis.

CE APĂRĂ
  1. Read-only — un script care scrie ar putea schimba exact ce pretinde că
     doar măsoară, iar cifra produsă ar decide o promovare.
  2. Nu importă module care știu să scrie, și NU importă `oracle_engine`
     (construcția lui rezolvă campioni, încarcă artefacte și loghează).
  3. Nu citește `*` și nu atinge decât cele două tabele declarate.
  4. Faza 1 rămâne o POARTĂ: dacă martorul de control nu trece, Faza 2 nu are
     voie să ruleze. O relure nevalidată care raportează cifre despre campion
     e exact defectul pe care martorul există ca să-l prevină.
  5. Statistica e corectă pe cazuri construite — inclusiv semnul, care diferă
     per metrică (acuratețea vrea mai mare, Brier/log-loss vor mai mic).

Fără rețea, fără Supabase.
"""
from __future__ import annotations

import ast
import pathlib

from scripts.replay_champion_on_persisted_inputs import (
    CAMPION, MARTOR, TOLERANTA, _brier, _corect, _logloss, _metrici,
    _t_pereche, _verdict,
)

SCRIPT = (pathlib.Path(__file__).resolve().parent.parent
          / "scripts" / "replay_champion_on_persisted_inputs.py")
SURSA = SCRIPT.read_text(encoding="utf-8")
ARBORE = ast.parse(SURSA)

_SCRIERE_NEAMBIGUA = {"upsert", "rpc", "execute_sql", "save_config",
                      "save_weights", "log_shadow_prediction", "write_run",
                      "fail_run", "propose_decision", "commit_decision",
                      "promote_challenger", "promote_experiment",
                      "deprecate_experiment", "record_champion_health_evaluation",
                      "set_cached_response", "upload", "remove"}
_SCRIERE_AMBIGUA = {"insert", "update", "delete"}

_MODULE_INTERZISE = {
    "oracle_engine", "cache_manager", "app", "promotion_service",
    "rollback_service", "continuous_learning", "automation_runs",
    "champion_manager", "challenger_manager",
}


def _apeluri() -> set[str]:
    return {n.func.attr for n in ast.walk(ARBORE)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}


def _importuri() -> set[str]:
    gasite: set[str] = set()
    for n in ast.walk(ARBORE):
        if isinstance(n, ast.Import):
            gasite.update(a.name.split(".")[0] for a in n.names)
        elif isinstance(n, ast.ImportFrom) and n.module:
            gasite.add(n.module.split(".")[0])
            if n.module.startswith("learning_core."):
                gasite.add(n.module.split(".")[1])
    return gasite


# ════════════════════════════════════════════════════════════════════════
# 1. Read-only
# ════════════════════════════════════════════════════════════════════════

def test_nu_contine_apeluri_de_scriere_neambigue():
    assert not (_apeluri() & _SCRIERE_NEAMBIGUA)


def test_nu_scrie_prin_insert_update_delete_pe_un_query():
    """AST, nu text: o căutare după `.insert(` ar raporta `sys.path.insert`,
    exact falsul pozitiv care a făcut prima versiune a gărzii de izolare să
    raporteze 23 de fișiere pe nedrept."""
    gasite = []
    for nod in ast.walk(ARBORE):
        if not (isinstance(nod, ast.Call) and isinstance(nod.func, ast.Attribute)):
            continue
        if nod.func.attr not in _SCRIERE_AMBIGUA:
            continue
        cur = nod.func.value
        while isinstance(cur, (ast.Call, ast.Attribute)):
            if (isinstance(cur, ast.Call) and isinstance(cur.func, ast.Attribute)
                    and cur.func.attr == "table"):
                gasite.append(f"{nod.func.attr}() la linia {nod.lineno}")
                break
            cur = cur.func if isinstance(cur, ast.Call) else cur.value
    assert gasite == []


def test_nu_importa_module_care_scriu_sau_construiesc_motorul():
    """`oracle_engine` e interzis separat de restul: nu e doar un modul care
    scrie, construcția lui rezolvă campioni, încarcă artefacte din cache și
    loghează — adică are efecte secundare la simplul import plus instanțiere."""
    assert not (_importuri() & _MODULE_INTERZISE)


def test_nu_scrie_pe_disc_si_nu_citeste_steluta():
    """[CORECTAT 2026-10-27] Prima versiune interzicea și `Path(` și `open(`,
    ca proxy pentru „scrie pe disc". Era PREA LARG, și a costat: `Path(` e pur
    manipulare de cale, iar `sys.path.insert(0, str(Path(__file__)...))` e
    idiomul folosit de toate celelalte scripturi din folder. Garda ar fi
    blocat exact reparația corectă a primei rulări eșuate — iar o gardă care
    interzice singura soluție validă se ocolește prin excepție, nu se respectă.

    Proprietatea reală e „nu SCRIE", nu „nu atinge căi". Verificată acum pe
    operații de scriere, plus `open()` doar în mod de scriere (prin AST, ca să
    nu fie confundat un `open()` de citire)."""
    for interzis in ('select("*")', "write_text", "write_bytes", "to_csv",
                     "mkdir", "makedirs", "unlink", "rmtree", "shutil"):
        assert interzis not in SURSA, f"scriptul nu are voie să folosească {interzis}"

    scrieri_open = []
    for nod in ast.walk(ARBORE):
        if not (isinstance(nod, ast.Call) and isinstance(nod.func, ast.Name)
                and nod.func.id == "open"):
            continue
        moduri = [a.value for a in nod.args[1:2] if isinstance(a, ast.Constant)]
        moduri += [k.value.value for k in nod.keywords
                   if k.arg == "mode" and isinstance(k.value, ast.Constant)]
        if any(c in m for m in moduri for c in "wax+") or not moduri:
            scrieri_open.append(f"open() la linia {nod.lineno}")
    assert scrieri_open == [], scrieri_open


def test_scriptul_RULEAZA_ca_in_workflow_fara_sa_cada_pe_import():
    """GARDA CARE LIPSEA, și care a costat o rulare.

    Rularea 40517516913 a eșuat în 0 secunde cu `ModuleNotFoundError: No module
    named 'supabase_client'`: pornit ca `python scripts/<fisier>.py`,
    `sys.path[0]` e `scripts/`, nu rădăcina. Toate testele de mai sus treceau,
    fiindcă ele IMPORTĂ modulul din rădăcină — exercitau cele două capete și nu
    firul dintre ele, aceeași clasă ca mutația M5 de la `night_sync`.

    Aici scriptul se pornește EXACT ca în workflow, ca subproces, fără
    credențiale. Trebuie să iasă cu codul 1 și mesajul de indisponibilitate —
    NU cu un traceback. Un `ModuleNotFoundError` reapărut cade aici, nu în
    producție."""
    import subprocess
    import os

    mediu = {k: v for k, v in os.environ.items()
             if k not in ("SUPABASE_URL", "SUPABASE_SECRET_KEY")}
    # `cwd` = rădăcina, ca în workflow (`python scripts/...`), fără PYTHONPATH:
    # bootstrap-ul din script e singurul lucru care face importul să reușească.
    mediu.pop("PYTHONPATH", None)
    r = subprocess.run([__import__("sys").executable, "scripts/" + SCRIPT.name],
                       cwd=str(SCRIPT.parent.parent), env=mediu,
                       capture_output=True, text=True, timeout=120)
    assert "ModuleNotFoundError" not in r.stderr, r.stderr[-800:]
    assert "Traceback" not in r.stderr, r.stderr[-800:]
    assert "Supabase indisponibil" in r.stdout, (r.stdout[-400:], r.stderr[-400:])
    assert r.returncode == 1


def test_atinge_doar_cele_doua_tabele_declarate():
    """Numele tabelelor ajung prin variabilă la `.table(...)`, deci se citesc
    din literalele pasate lui `_citeste_tot` — altfel verificarea ar raporta
    „nicio tabelă", un fals negativ care arată liniștitor."""
    tabele = {n.args[1].value for n in ast.walk(ARBORE)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
              and n.func.id == "_citeste_tot" and len(n.args) >= 2
              and isinstance(n.args[1], ast.Constant)}
    assert tabele == {"shadow_predictions", "match_history"}


def test_citirile_sunt_paginate():
    """A cincea instanță a plafonului PostgREST a fost reparată chiar azi; cod
    nou nu mai are voie să calce pe ea."""
    assert "_PAGINA" in SURSA and '.gt("id", cursor)' in SURSA
    assert ".limit(_PAGINA)" in SURSA and '.order("id")' in SURSA


# ════════════════════════════════════════════════════════════════════════
# 2. Faza 1 rămâne o poartă
# ════════════════════════════════════════════════════════════════════════

def test_faza_2_e_dupa_poarta_fazei_1_in_ordinea_codului():
    """Nu verifică doar că poarta EXISTĂ, ci că Faza 2 vine DUPĂ ea. O poartă
    mutată după calculul pe care o păzește ar lăsa mesajele identice și ar
    trece o verificare făcută doar pe conținut — aceeași lecție ca la
    instrumentarea `sync_pre_match_odds`, unde ordinea era proprietatea care
    conta, iar prima gardă o rata."""
    poarta = SURSA.index("POARTA NU TRECE")
    faza2 = SURSA.index("### FAZA 2")
    assert poarta < faza2, "poarta Fazei 1 trebuie să precede Faza 2"
    # și trebuie să fie un `return`, nu doar un mesaj tipărit
    dupa = SURSA[poarta:faza2]
    assert "return 2" in dupa, "poarta tipărește dar nu oprește execuția"


def test_martorul_si_campionul_sunt_modele_DIFERITE():
    """Un martor identic cu subiectul ar face Faza 1 o tautologie."""
    assert MARTOR != CAMPION


def test_toleranta_e_stransa():
    """Generoasă pentru drumul float→JSON→numeric→float, dar nu atât încât să
    înghită o divergență reală de model."""
    assert 0 < TOLERANTA <= 1e-5


# ════════════════════════════════════════════════════════════════════════
# 3. Statistica
# ════════════════════════════════════════════════════════════════════════

def test_brier_pe_predictie_perfecta_si_pe_una_maxim_greita():
    assert _brier(1.0, 0.0, 0.0, "H") == 0.0
    assert _brier(0.0, 0.0, 1.0, "H") == 2.0


def test_logloss_creste_cand_probabilitatea_rezultatului_scade():
    assert _logloss(0.9, 0.05, 0.05, "H") < _logloss(0.5, 0.25, 0.25, "H")


def test_logloss_nu_arunca_pe_probabilitate_zero():
    assert _logloss(0.0, 0.5, 0.5, "H") > 0


def test_corect_foloseste_argmax_nu_pragul():
    assert _corect(0.4, 0.35, 0.25, "H") == 1.0
    assert _corect(0.4, 0.35, 0.25, "D") == 0.0


def test_t_pereche_e_None_pe_eșantion_insuficient_sau_fara_dispersie():
    """A prins un defect REAL înainte de prima rulare: `var <= 0` nu se
    declanșează pe diferențe identice, fiindcă float dă ~1e-33 în loc de 0 —
    iar `t` ieșea 1,02e16, adică certitudine absolută dintr-un eșantion fără
    nicio dispersie. Pragul e acum relativ la scara diferențelor."""
    assert _t_pereche([0.1]) is None
    assert _t_pereche([0.2, 0.2, 0.2]) is None
    assert _t_pereche([0.0, 0.0, 0.0, 0.0]) is None
    assert _t_pereche([1e-9, 1e-9, 1e-9]) is None


def test_t_pereche_NU_respinge_diferente_mici_dar_reale():
    """Contrapondere la testul de mai sus: un prag ABSOLUT ar fi respins un
    eșantion legitim cu diferențe mici — exact cazul Brier, unde deltele reale
    sunt de ordinul 0,01."""
    t = _t_pereche([0.010, 0.012, 0.008, 0.011, 0.009])
    assert t is not None and t > 1.96


def test_t_pereche_semnul_urmeaza_diferenta():
    assert _t_pereche([0.1, 0.2, 0.15, 0.12]) > 0
    assert _t_pereche([-0.1, -0.2, -0.15, -0.12]) < 0


def test_verdictul_are_TREI_stari_nu_doua():
    """Lecția panoului de verdict (P2): „mai bun" și „dovedit mai bun" sunt
    două afirmații diferite, iar un ecran cu două stări le confundă."""
    assert "incert" in _verdict(True, 1.0)
    assert "mai bun" in _verdict(True, 3.0)
    assert "mai slab" in _verdict(False, 3.0)
    assert _verdict(True, None).startswith("—")


def test_verdictul_respecta_semnul_PER_metrica():
    """Brier mai mic = mai bun, acuratețe mai mare = mai bun. Apelantul decide
    ce e „favorabil"; funcția nu are voie să presupună o direcție."""
    m = _metrici([((0.5, 0.3, 0.2), (0.8, 0.1, 0.1), "H")] * 4)
    # modelul e mai încrezător și are dreptate → Brier mai mic, acuratețe egală
    assert m["brier_model"] < m["brier_oracle"]
    assert _verdict(m["brier_model"] < m["brier_oracle"], 3.0).startswith("✅")
    assert _verdict(m["brier_model"] > m["brier_oracle"], 3.0).startswith("❌")


def test_metricile_numara_toate_meciurile_primite():
    pereche = [((0.5, 0.3, 0.2), (0.6, 0.2, 0.2), "H"),
               ((0.4, 0.3, 0.3), (0.3, 0.3, 0.4), "A"),
               ((0.3, 0.4, 0.3), (0.2, 0.6, 0.2), "D")]
    assert _metrici(pereche)["n"] == 3
