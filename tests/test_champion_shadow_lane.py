"""Gărzi pentru banda de predicții a campionului promovat (ADR-082).

CE APĂRĂ, pe scurt — detaliile fiecărei proprietăți sunt în testul ei:
  1. Banda NU atinge probabilitatea servită. `prob_home_win` are exact un
     scriitor (`oracle_engine.py:2095`); un al doilea ar fi cea mai gravă
     regresie posibilă din acest ADR.
  2. Scrierea trece prin ADAPTOR, niciodată direct din Oracle Engine la
     `shadow_testing` — frontiera ADR-033/ADR-056.
  3. Predicția NU se recalculează: se refolosește
     `pred.blend_v1_champion_prediction`. Un al doilea apel la predictor ar
     putea divergea tăcut de ce s-a afișat, iar o bandă care nu corespunde
     afișării e mai rea decât niciuna.
  4. `feature_metadata` NU ajunge pe banda `'champion'` — ar fi o afirmație
     falsă despre cine a produs intrările (regula ADR-073).
  5. Gardianul NU mai poate citi `prob_*_pred` din `match_history`. Fără flag
     (ADR-082 §2.4), singura protecție e structura.
  6. `baseline_source` rămâne în mulțimea permisă de `CHECK`-ul migrării 015 —
     altfel defectul s-ar manifesta abia la prima activare, în producție.
  7. Flagul e implicit OPRIT (North Star #3) și poarta lui chiar oprește.

Fără rețea, fără Supabase.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

import learning_core.champion_shadow as cs
import oracle_engine as oe
import supabase_client as sb

RADACINA = pathlib.Path(__file__).resolve().parent.parent
SRC_ENGINE = (RADACINA / "oracle_engine.py").read_text(encoding="utf-8")
SRC_ADAPTOR = (RADACINA / "learning_core" / "champion_shadow.py").read_text(encoding="utf-8")
SRC_GUARDIAN = (RADACINA / "learning_core" / "champion_guardian.py").read_text(encoding="utf-8")
SRC_MIGRARE = (RADACINA / "database" / "migrations" / "015_champion_health.sql").read_text(
    encoding="utf-8")


def _functie(sursa: str, nume: str) -> ast.FunctionDef:
    for n in ast.walk(ast.parse(sursa)):
        if isinstance(n, ast.FunctionDef) and n.name == nume:
            return n
    raise AssertionError(f"funcția {nume} nu există — garda ar trece vid")


def _corp_fara_docstring(f: ast.FunctionDef) -> str:
    """`ast.dump()` include docstring-ul, iar docstring-urile de aici EXPLICĂ
    ce nu face funcția — deci citează chiar numele interzise.

    A CINCEA INSTANȚĂ a clasei, după `pipefail` (27 aug), numele de secrete
    (14 oct), docstring-ul ADR-073 și comentariul D-11: o gardă care caută un
    nume în text găsește propria explicație. Prinsă aici de ea însăși, înainte
    de commit — `test_hook_ul_REFOLOSESTE…` a căzut pe fraza „hook-ul apelează
    `_get_blend_v1_champion_prediction`", scrisă ca să spună că NU o apelează.

    Cu cât comentariul e mai bine scris, cu atât garda textuală e mai oarbă."""
    corp = list(f.body)
    if (corp and isinstance(corp[0], ast.Expr)
            and isinstance(corp[0].value, ast.Constant)
            and isinstance(corp[0].value.value, str)):
        corp = corp[1:]
    return "\n".join(ast.dump(n) for n in corp)


def _sursa_fara_docstringuri_si_comentarii(sursa: str) -> str:
    """Varianta la nivel de fișier: se re-emite codul din AST, care prin
    construcție nu conține comentarii, apoi se scot docstring-urile."""
    arbore = ast.parse(sursa)
    for n in ast.walk(arbore):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            corp = getattr(n, "body", [])
            if (corp and isinstance(corp[0], ast.Expr)
                    and isinstance(corp[0].value, ast.Constant)
                    and isinstance(corp[0].value.value, str)):
                n.body = corp[1:] or [ast.Pass()]
    return ast.unparse(ast.fix_missing_locations(arbore))


# ════════════════════════════════════════════════════════════════════════
# 1. Banda nu atinge probabilitatea servită
# ════════════════════════════════════════════════════════════════════════

def test_prob_home_win_are_tot_EXACT_un_scriitor():
    """Invariantul central al lui P6. `prob_home_win` se atribuie o singură
    dată în tot `oracle_engine.py`, din `ph` (ieșirea Poisson). Banda
    campionului nu are voie să devină un al doilea scriitor — aia ar fi
    cablarea căii de servire, pe care ADR-082 §3 o lasă explicit nedecisă."""
    atribuiri = []
    for n in ast.walk(ast.parse(SRC_ENGINE)):
        if isinstance(n, ast.keyword) and n.arg == "prob_home_win":
            atribuiri.append(n.lineno)
        if isinstance(n, (ast.Assign, ast.AugAssign)):
            ținte = n.targets if isinstance(n, ast.Assign) else [n.target]
            for t in ținte:
                if isinstance(t, ast.Attribute) and t.attr == "prob_home_win":
                    atribuiri.append(n.lineno)
    assert len(atribuiri) == 1, (
        f"prob_home_win are {len(atribuiri)} scriitori, la liniile {atribuiri} "
        "— ADR-082 nu are voie să cableze calea de servire"
    )


def test_adaptorul_nu_primeste_si_nu_atinge_obiectul_de_predictie():
    """Formularea anterioară căuta șirurile `prob_home_win`/`prob_draw` în
    fișier și cădea pe propriile nume de parametri (`control_prob_draw`) — un
    fals pozitiv produs de o verificare prea grosieră.

    Proprietatea reală: adaptorul primește NUMERE, nu obiectul `pred`, deci
    nu poate atinge probabilitatea servită nici dacă ar vrea."""
    f = _functie(SRC_ADAPTOR, "log_shadow_for_active_champion")
    parametri = {a.arg for a in f.args.args + f.args.kwonlyargs}
    assert "pred" not in parametri, "adaptorul primește obiectul de predicție"
    corp = _corp_fara_docstring(f)
    for interzis in ("prob_home_win", "prob_away_win", "blend_v1_champion_prediction"):
        assert interzis not in corp, f"adaptorul atinge `{interzis}`"


# ════════════════════════════════════════════════════════════════════════
# 2. Frontiera Oracle Engine → Adaptor → persistență
# ════════════════════════════════════════════════════════════════════════

def test_oracle_engine_nu_importa_shadow_testing_in_hook():
    """ADR-033/ADR-056: Oracle Engine vorbește cu persistența EXCLUSIV prin
    adaptor. Verificat pe corpul funcției, nu pe fișier — `oracle_engine`
    importă legitim `shadow_testing` în altă parte."""
    f = _functie(SRC_ENGINE, "_log_champion_shadow")
    corp = ast.dump(f)
    assert "shadow_testing" not in corp, (
        "`_log_champion_shadow` atinge direct `shadow_testing` — frontiera cade"
    )
    assert "champion_shadow" in corp, "hook-ul nu trece prin adaptor"


def test_adaptorul_scrie_exact_DOUA_randuri():
    """Banda + rândul `control` pereche. Un singur rând ar face banda
    neevaluabilă (`shadow_testing` împerechează pe control); trei ar scrie
    ceva nedeclarat."""
    f = _functie(SRC_ADAPTOR, "log_shadow_for_active_champion")
    apeluri = [n for n in ast.walk(f)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr == "log_shadow_prediction"]
    assert len(apeluri) == 2, f"{len(apeluri)} apeluri de scriere, se așteptau 2"

    # Grupul benzii e pasat prin CONSTANTA importată, nu ca literal — deci nu
    # e un `ast.Constant`. Prima versiune a gărzii citea doar literalele, găsea
    # un singur grup (`"control"`) și ar fi raportat eșec pe cod corect.
    def _grup(apel):
        for k in apel.keywords:
            if k.arg != "experiment_group":
                continue
            if isinstance(k.value, ast.Constant):
                return k.value.value
            if isinstance(k.value, ast.Name):
                return getattr(cs, k.value.id)
        raise AssertionError("un apel de scriere nu declară `experiment_group`")

    assert sorted(_grup(a) for a in apeluri) == ["champion", "control"]


def test_grupul_benzii_vine_din_constanta_nu_dintr_un_sir_scris_de_mana():
    """Scriitorul și cititorul trebuie să împartă o singură definiție —
    două șiruri scrise de mână pot divergea (clasa `_PAGE_SIZE`)."""
    assert cs.EXPERIMENT_GROUP_CHAMPION is sb.EXPERIMENT_GROUP_CHAMPION
    assert sb.EXPERIMENT_GROUP_CHAMPION == "champion"


def test_stratul_de_date_nu_importa_din_learning_core():
    """North Star #10, dependințe „în sus". Prima versiune a implementării
    avea `supabase_client` importând constanta din `learning_core` — exact
    inversul direcției permise. Prins înainte de commit."""
    for n in ast.walk(ast.parse((RADACINA / "supabase_client.py").read_text(encoding="utf-8"))):
        module = None
        if isinstance(n, ast.ImportFrom) and n.module:
            module = n.module
        elif isinstance(n, ast.Import):
            module = n.names[0].name
        if module and module.split(".")[0] == "learning_core":
            raise AssertionError(
                f"supabase_client importă `{module}` la linia {n.lineno} "
                "— dependință in SUS, contra North Star #10"
            )


# ════════════════════════════════════════════════════════════════════════
# 3. Predicția nu se recalculează
# ════════════════════════════════════════════════════════════════════════

def test_hook_ul_REFOLOSESTE_predictia_afisata_si_nu_apeleaza_predictorul():
    corp = _corp_fara_docstring(_functie(SRC_ENGINE, "_log_champion_shadow"))
    assert "blend_v1_champion_prediction" in corp, (
        "hook-ul nu citește predicția deja calculată"
    )
    for interzis in ("predict_with_blend_challenger", "_build_ml_features",
                     "_get_blend_v1_champion_prediction"):
        assert interzis not in corp, (
            f"hook-ul apelează `{interzis}` — ar putea divergea de ce s-a afișat"
        )


def test_adaptorul_nu_calculeaza_nicio_predictie():
    corp = _sursa_fara_docstringuri_si_comentarii(SRC_ADAPTOR)
    for interzis in ("predict_with_blend_challenger", "load_model_artifact",
                     "load_calibration_artifact", "blend_predictions"):
        assert interzis not in corp, (
            f"adaptorul calculează prin `{interzis}` — primește probabilitățile, nu le produce"
        )


def test_hook_ul_e_apelat_DUPA_ce_predictia_e_populata():
    """Ordinea, nu doar prezența: apelat înainte, câmpul ar fi `None` și banda
    n-ar fi scrisă niciodată — un defect tăcut, care arată exact ca „flagul e
    oprit". Aceeași clasă ca instrumentarea `sync_pre_match_odds`."""
    populare = SRC_ENGINE.index("pred.blend_v1_champion_prediction = self._get_blend_v1_champion_prediction")
    apel = SRC_ENGINE.index("self._log_champion_shadow(")
    assert populare < apel


# ════════════════════════════════════════════════════════════════════════
# 4. `feature_metadata` nu ajunge pe bandă
# ════════════════════════════════════════════════════════════════════════

def test_feature_metadata_nu_e_pasat_NICIUNUI_apel_din_adaptor():
    """Regula ADR-073: înregistrarea intrărilor descrie ce a folosit ORACLE.
    Pe banda campionului ar fi o afirmație falsă despre cine a produs ce; pe
    rândul `control` al benzii ar fi a treia copie identică (măsurat: identic
    bit cu bit pe 512 meciuri)."""
    assert "feature_metadata" not in SRC_ADAPTOR.replace(
        "`feature_metadata`", "")  # mențiunile din docstring nu contează
    f = _functie(SRC_ADAPTOR, "log_shadow_for_active_champion")
    for n in ast.walk(f):
        if isinstance(n, ast.keyword) and n.arg == "feature_metadata":
            raise AssertionError(f"`feature_metadata` pasat la linia {n.lineno}")


# ════════════════════════════════════════════════════════════════════════
# 5. Gardianul nu mai poate citi sursa veche
# ════════════════════════════════════════════════════════════════════════

def test_gardianul_citeste_banda_si_NU_mai_citeste_prob_pred_din_match_history():
    f = _functie(SRC_GUARDIAN, "evaluate_champion_health")
    corp = ast.dump(f)
    assert "get_champion_lane_outcomes" in corp, "gardianul nu citește banda"
    assert "get_champion_served_outcomes" not in corp, (
        "gardianul citește încă sursa veche — ar raporta sănătatea lui Oracle "
        "sub numele campionului (ADR-082 §1.1)"
    )


def test_sursa_gardianului_identifica_modelul_nu_perioada():
    """Miezul reparației: fereastra nu se mai delimitează temporal, prin
    `promoted_at`, ci prin identitatea modelului. Un `since_date` reapărut ar
    însemna că proteza s-a întors."""
    import inspect
    parametri = list(inspect.signature(sb.get_champion_lane_outcomes).parameters)
    assert "training_run_id" in parametri
    assert "since_date" not in parametri


def test_sursa_noua_e_paginata_si_nu_intoarce_parcursul_partial():
    sursa = (RADACINA / "supabase_client.py").read_text(encoding="utf-8")
    corp = sursa[sursa.index("def get_champion_lane_outcomes"):]
    corp = corp[:corp.index("\ndef ")]
    assert ".limit(_PAGE_SIZE)" in corp and '.gt("fixture_id", cursor)' in corp
    assert "return []" in corp, "la eroare trebuie lista goală, nu parțialul"
    assert 'select("*")' not in corp


# ════════════════════════════════════════════════════════════════════════
# 6. `baseline_source` rămâne în mulțimea permisă de CHECK
# ════════════════════════════════════════════════════════════════════════

def test_baseline_source_scris_de_gardian_e_permis_de_CHECK_ul_din_schema():
    """Prima versiune a ADR-082 propunea o valoare nouă, `'champion_lane'`.
    Ar fi fost respinsă de bază la prima activare — adică un defect care apare
    în producție, nu la test. Garda citește mulțimea direct din migrare."""
    import re
    linie = next(l for l in SRC_MIGRARE.splitlines() if "baseline_source IN" in l)
    # Parsarea anterioară folosea `rindex(")")` și includea o paranteză în
    # ultima valoare (`"manual_override')"`). Acum se extrag literalele cu
    # ghilimele simple, deci parantezele nu mai contează.
    permise = set(re.findall(r"'([^']+)'", linie))
    assert permise == {"promotion_evaluation", "trend_only", "manual_override"}, permise

    candidate = permise | {"champion_lane", "champion_lane_outcomes"}
    scrise = {n.value for n in ast.walk(ast.parse(SRC_GUARDIAN))
              if isinstance(n, ast.Constant) and isinstance(n.value, str)
              and n.value in candidate}
    assert scrise <= permise, f"gardianul scrie valori respinse de CHECK: {scrise - permise}"


# ════════════════════════════════════════════════════════════════════════
# 7. Flagul — implicit oprit, și poarta chiar oprește
# ════════════════════════════════════════════════════════════════════════

def test_flagul_e_implicit_OPRIT():
    assert oe.DEFAULT_CONFIG["champion_shadow_logging_enabled"] is False


class _Engine:
    """Fixtură minimă: copiază metoda reală la definirea clasei. Patch-area
    clasei `FootballOracleEngine` n-ar avea efect aici — lecția din ADR-073,
    unde un test trecea fără să exercite calea."""
    _log_champion_shadow = oe.FootballOracleEngine._log_champion_shadow

    def __init__(self, config):
        self.config = config


class _Pred:
    fixture_id = "fx-1"
    league = "Premier League"
    home_team = "A"
    away_team = "B"
    kickoff_date = "2026-10-28"
    prob_home_win = 0.5
    prob_draw = 0.3
    prob_away_win = 0.2
    blend_v1_champion_prediction = {"available": True, "prob_home": 0.55,
                                     "prob_draw": 0.28, "prob_away": 0.17}


def test_poarta_flagului_oprit_nu_scrie_si_nu_importa(monkeypatch):
    contor = []
    monkeypatch.setattr(cs, "log_shadow_for_active_champion",
                        lambda **k: contor.append(k) or True)
    assert _Engine({"champion_shadow_logging_enabled": False})._log_champion_shadow(
        _Pred(), 1.5, 1.1) is False
    assert contor == []


def test_flag_pornit_apeleaza_adaptorul_cu_predictia_afisata(monkeypatch):
    primite = {}
    monkeypatch.setattr(cs, "log_shadow_for_active_champion",
                        lambda **k: primite.update(k) or True)
    assert _Engine({"champion_shadow_logging_enabled": True})._log_champion_shadow(
        _Pred(), 1.5, 1.1) is True
    assert primite["champion_prob_home"] == 0.55
    assert primite["control_prob_home"] == 0.5
    assert primite["algorithm_family"] == "blend_v1"
    assert primite["home_xg"] == 1.5 and primite["away_xg"] == 1.1


@pytest.mark.parametrize("bp", [None, {"available": False, "reason": "x"}, {}])
def test_predictie_indisponibila_nu_scrie_nimic(monkeypatch, bp):
    """Trei stări distincte, niciuna aproximată (Regula #8). Dacă
    `blend_v1_champion_display_enabled` e oprit, câmpul e `None` — banda nu se
    scrie, și asta e documentat, nu accidental."""
    contor = []
    monkeypatch.setattr(cs, "log_shadow_for_active_champion",
                        lambda **k: contor.append(k) or True)
    p = _Pred()
    p.blend_v1_champion_prediction = bp
    assert _Engine({"champion_shadow_logging_enabled": True})._log_champion_shadow(
        p, 1.5, 1.1) is False
    assert contor == []


def test_eroarea_adaptorului_nu_se_propaga_in_evaluate_match(monkeypatch):
    def _boom(**k):
        raise RuntimeError("Supabase picat")
    monkeypatch.setattr(cs, "log_shadow_for_active_champion", _boom)
    assert _Engine({"champion_shadow_logging_enabled": True})._log_champion_shadow(
        _Pred(), 1.5, 1.1) is False


# ════════════════════════════════════════════════════════════════════════
# 8. Adaptorul — campion absent / incomplet
# ════════════════════════════════════════════════════════════════════════

def test_campion_absent_nu_scrie_nimic(monkeypatch):
    """`xgboost_v1` n-a avut niciodată campion — stare legitimă, nu eroare."""
    monkeypatch.setattr(sb, "get_active_champion", lambda f, l: None)
    scrieri = []
    import shadow_testing
    monkeypatch.setattr(shadow_testing, "log_shadow_prediction",
                        lambda **k: scrieri.append(k))
    assert cs.log_shadow_for_active_champion(
        algorithm_family="xgboost_v1", league_scope="all", fixture_id="fx-1",
        champion_prob_home=0.5, champion_prob_draw=0.3, champion_prob_away=0.2,
        control_prob_home=0.5, control_prob_draw=0.3, control_prob_away=0.2,
        home_xg=1.0, away_xg=1.0, league="L", home_team="A", away_team="B",
        kickoff_date="2026-10-28") is False
    assert scrieri == []


def test_campion_fara_training_run_id_nu_scrie_un_rand_neidentificabil(monkeypatch):
    """Un rând fără identitatea modelului e mai rău decât niciun rând
    (North Star #9) — și nu se aproximează (Regula #8)."""
    monkeypatch.setattr(sb, "get_active_champion", lambda f, l: {"training_run_id": None})
    scrieri = []
    import shadow_testing
    monkeypatch.setattr(shadow_testing, "log_shadow_prediction",
                        lambda **k: scrieri.append(k))
    assert cs.log_shadow_for_active_champion(
        algorithm_family="blend_v1", league_scope="all", fixture_id="fx-1",
        champion_prob_home=0.5, champion_prob_draw=0.3, champion_prob_away=0.2,
        control_prob_home=0.5, control_prob_draw=0.3, control_prob_away=0.2,
        home_xg=1.0, away_xg=1.0, league="L", home_team="A", away_team="B",
        kickoff_date="2026-10-28") is False
    assert scrieri == []


def test_ambele_randuri_poarta_training_run_id_ul_campionului(monkeypatch):
    monkeypatch.setattr(sb, "get_active_champion",
                        lambda f, l: {"training_run_id": "run-campion"})
    scrieri = []
    import shadow_testing
    monkeypatch.setattr(shadow_testing, "log_shadow_prediction",
                        lambda **k: scrieri.append(k))
    assert cs.log_shadow_for_active_champion(
        algorithm_family="blend_v1", league_scope="all", fixture_id="fx-1",
        champion_prob_home=0.55, champion_prob_draw=0.28, champion_prob_away=0.17,
        control_prob_home=0.5, control_prob_draw=0.3, control_prob_away=0.2,
        home_xg=1.5, away_xg=1.1, league="L", home_team="A", away_team="B",
        kickoff_date="2026-10-28") is True
    assert len(scrieri) == 2
    assert {s["experiment_version"] for s in scrieri} == {"run-campion"}
    banda = next(s for s in scrieri if s["experiment_group"] == "champion")
    control = next(s for s in scrieri if s["experiment_group"] == "control")
    assert banda["prob_home"] == 0.55, "banda trebuie să poarte predicția campionului"
    assert control["prob_home"] == 0.5, "controlul trebuie să poarte Oracle-ul servit"
    assert "feature_metadata" not in banda and "feature_metadata" not in control


# ════════════════════════════════════════════════════════════════════════
# 9. Perechea control–champion e COMPLETĂ și CORECT ASOCIATĂ
#    (verificare cerută explicit de proprietarul produsului, 2026-10-27:
#     „documentul explică de ce e necesar rândul control, dar implementarea
#     trebuie să demonstreze că fiecare pereche e completă și corect
#     asociată")
# ════════════════════════════════════════════════════════════════════════

def _scrie(monkeypatch, trid="run-campion", **suprascrieri):
    monkeypatch.setattr(sb, "get_active_champion", lambda f, l: {"training_run_id": trid})
    scrieri = []
    import shadow_testing
    monkeypatch.setattr(shadow_testing, "log_shadow_prediction",
                        lambda **k: scrieri.append(k))
    argumente = dict(
        algorithm_family="blend_v1", league_scope="all", fixture_id="fx-7",
        champion_prob_home=0.55, champion_prob_draw=0.28, champion_prob_away=0.17,
        control_prob_home=0.50, control_prob_draw=0.30, control_prob_away=0.20,
        home_xg=1.5, away_xg=1.1, league="Premier League",
        home_team="A", away_team="B", kickoff_date="2026-10-28T19:00:00",
    )
    argumente.update(suprascrieri)
    rezultat = cs.log_shadow_for_active_champion(**argumente)
    return rezultat, scrieri


def test_perechea_e_completa_EXACT_un_champion_si_EXACT_un_control(monkeypatch):
    _, scrieri = _scrie(monkeypatch)
    grupuri = [s["experiment_group"] for s in scrieri]
    assert grupuri.count("champion") == 1, grupuri
    assert grupuri.count("control") == 1, grupuri
    assert len(grupuri) == 2, "nicio scriere în plus, nedeclarată"


def test_perechea_e_CORECT_ASOCIATA_pe_toata_cheia_de_impereche(monkeypatch):
    """Cele două rânduri trebuie să împartă EXACT cheia pe care
    `shadow_testing` împerechează — `fixture_id` + `experiment_name` +
    `experiment_version` + `processing_stage`. O singură componentă diferită
    face perechea invizibilă evaluării, iar banda ar părea nepereche fără
    nicio eroare."""
    _, scrieri = _scrie(monkeypatch)
    cheie = lambda s: (s["fixture_id"], s["experiment_name"],
                       s["experiment_version"], s["processing_stage"])
    assert cheie(scrieri[0]) == cheie(scrieri[1]), (
        f"perechea nu se asociază: {cheie(scrieri[0])} vs {cheie(scrieri[1])}"
    )
    assert cheie(scrieri[0]) == ("fx-7", "blend_v1", "run-campion", "final")


def test_perechea_difera_DOAR_prin_grup_si_probabilitati(monkeypatch):
    """Tot restul metadatelor (ligă, echipe, kickoff, xG) trebuie identic —
    altfel cele două rânduri ar descrie meciuri subtil diferite."""
    _, scrieri = _scrie(monkeypatch)
    a, b = scrieri
    diferite = {k for k in set(a) | set(b) if a.get(k) != b.get(k)}
    assert diferite == {"experiment_group", "prob_home", "prob_draw", "prob_away"}, diferite


def test_probabilitatile_nu_se_INVERSEAZA_intre_cele_doua_randuri(monkeypatch):
    """Cea mai periculoasă greșeală posibilă aici: campionul scris pe rândul
    `control` și invers. Ar trece orice test de numărare, ar produce o pereche
    completă și corect asociată — și ar inversa verdictul de sănătate.
    Verificat pe valori distincte, deliberat alese să nu se poată confunda."""
    _, scrieri = _scrie(monkeypatch)
    banda = next(s for s in scrieri if s["experiment_group"] == "champion")
    control = next(s for s in scrieri if s["experiment_group"] == "control")
    assert (banda["prob_home"], banda["prob_draw"], banda["prob_away"]) == (0.55, 0.28, 0.17)
    assert (control["prob_home"], control["prob_draw"], control["prob_away"]) == (0.50, 0.30, 0.20)


def test_perechea_e_ATOMICA_logic_ambele_sau_niciunul(monkeypatch):
    """Dacă prima scriere reușește și a doua aruncă, adaptorul întoarce False.
    Nu putem face scrierea atomică în bază (două `upsert`-uri), dar apelantul
    nu are voie să primească `True` pe o pereche incompletă — altfel un rând
    orfan ar fi raportat ca succes."""
    monkeypatch.setattr(sb, "get_active_champion", lambda f, l: {"training_run_id": "r"})
    apeluri = []
    import shadow_testing

    def _a_doua_arunca(**k):
        apeluri.append(k)
        if len(apeluri) == 2:
            raise RuntimeError("Supabase picat la al doilea rând")

    monkeypatch.setattr(shadow_testing, "log_shadow_prediction", _a_doua_arunca)
    rezultat = cs.log_shadow_for_active_champion(
        algorithm_family="blend_v1", league_scope="all", fixture_id="fx-7",
        champion_prob_home=0.55, champion_prob_draw=0.28, champion_prob_away=0.17,
        control_prob_home=0.50, control_prob_draw=0.30, control_prob_away=0.20,
        home_xg=1.5, away_xg=1.1, league="L", home_team="A", away_team="B",
        kickoff_date="2026-10-28")
    assert rezultat is False, "o pereche incompletă nu are voie să raporteze succes"
    assert len(apeluri) == 2, "a doua scriere trebuie încercată, nu sărită"


def test_banda_se_scrie_PRIMA_ca_un_orfan_sa_fie_detectabil(monkeypatch):
    """Ordinea nu e indiferentă. Dacă `control` s-ar scrie primul și banda ar
    eșua, rămâne un rând `control` orfan — indistingibil de cele scrise
    legitim de Challenger pentru aceeași versiune. Invers, un rând `champion`
    orfan e imediat detectabil: grupul există doar aici."""
    _, scrieri = _scrie(monkeypatch)
    assert scrieri[0]["experiment_group"] == "champion"


# ════════════════════════════════════════════════════════════════════════
# 10. Ordinea de activare: gardianul nu poate raporta pe o bandă subțire
#     (verificare cerută explicit: „nicio activare a Guardianului înainte ca
#      banda să aibă suficiente rezultate reale și verificabile")
# ════════════════════════════════════════════════════════════════════════

def test_banda_goala_da_insufficient_data_si_NU_persista(monkeypatch):
    """Starea de dinainte de activarea benzii, și singura în care gardianul
    poate fi pornit fără risc: fereastra e goală, deci `n == 0`, deci
    `evaluate_champion_health` întoarce starea FĂRĂ să persiste."""
    import learning_core.champion_guardian as g

    monkeypatch.setattr("supabase_client.get_active_champion",
                        lambda f, l: {"training_run_id": "run-1",
                                      "algorithm_version": "1",
                                      "promoted_at": "2026-01-01T00:00:00+00:00"})
    monkeypatch.setattr(g, "_structural_probe", lambda t, v: None)
    monkeypatch.setattr("supabase_client.get_champion_lane_outcomes", lambda f, l, t: [])
    persistate = []
    monkeypatch.setattr("supabase_client.record_champion_health_evaluation",
                        lambda **k: persistate.append(k) or True)

    r = g.evaluate_champion_health("blend_v1", "all")
    assert r is not None
    assert r.n_matches_evaluated == 0
    assert r.health_state == "insufficient_data"
    assert r.recommends_rollback is False, "o bandă goală nu poate recomanda rollback"
    assert persistate == [], "n == 0 nu are voie să persiste un fapt"


def test_banda_sub_prag_nu_recomanda_rollback(monkeypatch):
    """Între 1 și 29 de rânduri: se persistă (fapt real), dar nicio dimensiune
    statistică nu se calculează și nimic nu poate declanșa rollback."""
    import learning_core.champion_guardian as g

    monkeypatch.setattr("supabase_client.get_active_champion",
                        lambda f, l: {"training_run_id": "run-1",
                                      "algorithm_version": "1",
                                      "promoted_at": "2026-01-01T00:00:00+00:00"})
    monkeypatch.setattr(g, "_structural_probe", lambda t, v: None)
    randuri = [{"fixture_id": f"fx-{i}", "kickoff_date": f"2026-10-{i + 1:02d}",
                "prob_home_pred": 0.5, "prob_draw_pred": 0.3, "prob_away_pred": 0.2,
                "actual_result": "H"} for i in range(g.MIN_MATCHES_FOR_HEALTH - 1)]
    monkeypatch.setattr("supabase_client.get_champion_lane_outcomes",
                        lambda f, l, t: randuri)
    monkeypatch.setattr("supabase_client.record_champion_health_evaluation",
                        lambda **k: True)

    r = g.evaluate_champion_health("blend_v1", "all")
    assert r.health_state == "insufficient_data"
    assert r.recommends_rollback is False
    assert r.brier_live is None, "nicio metrică nu se calculează sub prag"
