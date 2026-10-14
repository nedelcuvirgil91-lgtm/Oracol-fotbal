"""Gărzi pentru ADR-073 — persistarea intrărilor de la servire.

CE APĂRĂ, în ordinea importanței

  1. REPRODUCEREA. `feature_engine.calibrate_xg()`, alimentat EXCLUSIV din
     `oracle_inputs`, trebuie să întoarcă exact `oracle_outputs[*_xg_pre_injury]`.
     Fără asta, înregistrarea ar *arăta* auditabilă fără să fie — exact
     capcana pe care ADR-073 §Decizia 4 o numește.
  2. PUNCTUL UNIC. `_calibrate_xg()` (care servește) și `_build_serving_record()`
     (care înregistrează) citesc ambele din `_resolve_xg_params()`. Dacă
     rezolvarea s-ar duplica, înregistrarea ar putea raporta alte valori decât
     cele folosite — opusul scopului ei (North Star #9).
  3. FLAGUL OPRIT = ZERO COST. Nu doar „întoarce None": `_build_serving_record`
     nu trebuie nici atins.
  4. DOAR PE `control`. Rândul `treatment` descrie Challenger-ul; intrările
     Oracle pe el ar fi o afirmație falsă despre cine a produs ce.
  5. NEDEGRADARE. O excepție în construcția înregistrării nu are voie să
     anuleze logarea shadow, care funcționează deja.

DE CE REPRODUCEREA SE OPREȘTE LA xG-ul PRE-ACCIDENTĂRI, și nu merge până la
probabilitatea servită (ADR-073 §D2): penalizarea de accidentări se aplică
ÎNTRE `calibrate_xg()` și Poisson. Azi pre și post coincid
(`freelf_lineup_snapshot` are 0 rânduri), deci o gardă care ar verifica până
la capăt ar trece — și ar cădea exact în ziua în care accidentările se
cablează, iar partea greșită ar fi garda. Se verifică etapa pe care
înregistrarea PRETINDE că o acoperă, nu una pe care n-o acoperă.

Fără rețea, fără Supabase.
"""
from __future__ import annotations

import ast
import inspect
import pathlib

import pytest

import oracle_engine
from feature_engine import calibrate_xg
from oracle_engine import H2HRecord, MatchPrediction, TeamProfile

_WEIGHTS = {
    "league_baselines": {"Test League": 1.31, "default": 1.25},
    "defensive_cap": 2.4,
    "form_weight": 0.58, "base_weight": 0.42,
    "home_advantage": 1.09, "away_penalty": 0.94,
    "league_weights": {},
}


def _siruri_din_cod(modul) -> set[str]:
    """Șirurile din COD, cu docstring-urile EXCLUSE.

    DE CE PRIN AST, nu prin `in sursa`: prima versiune a gărzii de mai jos
    căuta numele flagului ca text și a căzut pe propriul meu docstring, cel
    care explica tocmai faptul că adaptorul NU citește flagul. Garda își
    găsea propria explicație — cu cât comentariul era mai bine scris, cu atât
    verificarea era mai oarbă.

    A TREIA instanță a aceleiași clase în proiect, după garda `pipefail` din
    `test_workflow_log_artifacts.py` (2026-08-27, reparată prin `_doar_cod()`)
    și garda de nume de secrete din `test_poc_isolation.py` (2026-10-14).
    Reparată prin structură, nu prin excepție de interpretat.
    """
    arbore = ast.parse(pathlib.Path(modul.__file__).read_text(encoding="utf-8"))
    docstringuri = set()
    for nod in ast.walk(arbore):
        if isinstance(nod, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            corp = getattr(nod, "body", None) or []
            if corp and isinstance(corp[0], ast.Expr) and isinstance(corp[0].value, ast.Constant) \
                    and isinstance(corp[0].value.value, str):
                docstringuri.add(id(corp[0].value))
    return {
        n.value for n in ast.walk(arbore)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
        and id(n) not in docstringuri
    }


def _profile(name: str, *, off: float, dfn: float, form: float, dq: str = "live") -> TeamProfile:
    return TeamProfile(
        team_id="t", team_name=name, matches_analysed=10,
        avg_goals_for=1.5, avg_goals_against=1.0, avg_shots_ot=4.0,
        avg_possession=50.0, offensive_rating=off, defensive_rating=dfn,
        form_results=["W", "D", "L"], form_score=form, standings_form="",
        elo_rating=1550, data_source="test", data_quality=dq, data_quality_note="",
    )


def _pred(**over) -> MatchPrediction:
    base = dict(
        fixture_id="fx-1", home_team="Home FC", away_team="Away FC",
        league="Test League", kickoff_utc="2026-10-20T18:00:00Z",
        kickoff_date="2026-10-20", season=2026,
        home_xg=1.4, away_xg=1.1,
        prob_home_win=0.45, prob_draw=0.28, prob_away_win=0.27,
        top_scores=[], bk_home_odds=2.1, bk_draw_odds=3.3, bk_away_odds=3.6,
        bookmaker_name="test-bk",
        impl_home_pct=45.0, impl_draw_pct=28.0, impl_away_pct=27.0,
        edge_home_pct=0.0, edge_draw_pct=0.0, edge_away_pct=0.0,
        value_bets=[], weather_note="", weather_penalty=0.0,
        kelly_stakes={}, home_profile=None, away_profile=None, h2h=None,
        data_quality_home="live", data_quality_away="live",
        home_injury_report=None, away_injury_report=None, injury_note="",
        home_xg_pre_injury=1.4, away_xg_pre_injury=1.1,
    )
    base.update(over)
    return MatchPrediction(**base)


class _Engine:
    """Instanță minimală, fără Supabase/API — același tipar ca `_FakeEngine`
    din tests/test_challenger_shadow_logging.py."""
    _resolve_xg_params = oracle_engine.FootballOracleEngine._resolve_xg_params
    _get_league_weights = oracle_engine.FootballOracleEngine._get_league_weights
    _calibrate_xg = oracle_engine.FootballOracleEngine._calibrate_xg
    _build_ml_features = oracle_engine.FootballOracleEngine._build_ml_features
    _build_serving_record = oracle_engine.FootballOracleEngine._build_serving_record
    _serving_record_if_enabled = oracle_engine.FootballOracleEngine._serving_record_if_enabled
    _log_challenger_shadow = oracle_engine.FootballOracleEngine._log_challenger_shadow
    SERVING_RECORD_SCHEMA_VERSION = \
        oracle_engine.FootballOracleEngine.SERVING_RECORD_SCHEMA_VERSION

    def __init__(self, config: dict | None = None):
        self.config = config if config is not None else {}
        self.weights = dict(_WEIGHTS)


def _h2h(*, meetings: int, modifier: float) -> H2HRecord:
    return H2HRecord(
        home_team="Home FC", away_team="Away FC", meetings=meetings,
        home_wins=2, draws=1, away_wins=1,
        home_goals_avg=1.75, away_goals_avg=1.25, last_5=["H", "D", "A"],
        h2h_modifier=modifier, summary="test",
    )


def _scenarii():
    """Cazuri cu valori DISTINCTE pe fiecare parametru.

    Deliberat NU se folosesc valori implicite rotunde: dacă `oracle_inputs`
    ar lua din greșeală un default (1.25 / 2.5 / 0.60) în loc de valoarea
    reală, un scenariu cu valori implicite ar reproduce oricum corect și
    garda ar trece degeaba.
    """
    return [
        ("fără h2h, fără vreme", 0.0, None),
        ("h2h activ (meetings >= 2)", 0.0, _h2h(meetings=4, modifier=0.08)),
        ("penalizare de vreme", 0.17, None),
        ("h2h sub prag — modifier IGNORAT de calibrate_xg", 0.0,
         _h2h(meetings=1, modifier=0.08)),
        ("h2h + vreme simultan", 0.11, _h2h(meetings=3, modifier=-0.06)),
    ]


def _record(engine, home_p, away_p, h2h, w_pen):
    home_xg, away_xg = engine._calibrate_xg(home_p, away_p, "Test League", w_pen, h2h)
    mc = {"mc_prob_home": 0.44, "mc_prob_draw": 0.29, "mc_prob_away": 0.27}
    mlf = engine._build_ml_features(
        home_p, away_p, h2h, home_xg, away_xg, 0.45, 0.28, 0.27, mc, w_pen)
    rec = engine._build_serving_record(
        home_p=home_p, away_p=away_p, h2h=h2h, league="Test League",
        weather_penalty=w_pen, ml_features=mlf,
        home_xg_pre_injury=home_xg, away_xg_pre_injury=away_xg,
        home_xg=home_xg, away_xg=away_xg,
    )
    return rec, home_xg, away_xg


# ── 1. REPRODUCEREA ────────────────────────────────────────────────────────

@pytest.mark.parametrize("eticheta,w_pen,h2h", _scenarii())
def test_predictia_se_reproduce_din_inregistrare(eticheta, w_pen, h2h):
    """GARDA CENTRALĂ a ADR-073. `calibrate_xg()` alimentat EXCLUSIV din
    `oracle_inputs` reproduce xG-ul pre-accidentări stocat."""
    engine = _Engine()
    home_p = _profile("Home FC", off=1.18, dfn=0.87, form=0.63)
    away_p = _profile("Away FC", off=0.94, dfn=1.12, form=0.41)

    rec, home_xg, away_xg = _record(engine, home_p, away_p, h2h, w_pen)

    # Reconstrucția folosește DOAR `oracle_inputs` — niciun profil, nicio
    # pondere din afara înregistrării. Dacă ar lipsi un parametru, apelul ar
    # cădea cu TypeError, nu ar trece cu o valoare implicită.
    reprodus_home, reprodus_away = calibrate_xg(**rec["oracle_inputs"])

    assert reprodus_home == pytest.approx(
        rec["oracle_outputs"]["home_xg_pre_injury"], abs=1e-9), eticheta
    assert reprodus_away == pytest.approx(
        rec["oracle_outputs"]["away_xg_pre_injury"], abs=1e-9), eticheta
    # ...și aceleași cifre cu cele produse efectiv de calea de servire.
    assert reprodus_home == pytest.approx(home_xg, abs=1e-9), eticheta
    assert reprodus_away == pytest.approx(away_xg, abs=1e-9), eticheta


def test_oracle_inputs_acopera_exact_semnatura_lui_calibrate_xg():
    """`oracle_inputs` trebuie să fie exact setul de parametri al lui
    `calibrate_xg()`, fără lipsuri și fără surplus.

    Un parametru LIPSĂ ar fi completat tăcut de valoarea implicită din
    semnătură (`h2h_modifier=0.0`, `weather_penalty=0.0`) — reproducerea ar
    trece, pe alt calcul decât cel servit. Un parametru în SURPLUS ar face
    apelul să cadă. Deci egalitatea, nu incluziunea."""
    engine = _Engine()
    home_p = _profile("Home FC", off=1.18, dfn=0.87, form=0.63)
    away_p = _profile("Away FC", off=0.94, dfn=1.12, form=0.41)
    rec, _, _ = _record(engine, home_p, away_p, None, 0.0)

    asteptat = set(inspect.signature(calibrate_xg).parameters)
    assert set(rec["oracle_inputs"]) == asteptat, (
        "oracle_inputs diferă de semnătura calibrate_xg(); lipsesc "
        f"{sorted(asteptat - set(rec['oracle_inputs']))}, în plus "
        f"{sorted(set(rec['oracle_inputs']) - asteptat)}")


@pytest.mark.parametrize("cheie", [
    "baseline", "form_weight", "base_weight", "home_advantage",
    "away_penalty", "defensive_cap", "h2h_modifier", "weather_penalty",
    "home_offensive_rating", "home_defensive_rating",
    "away_offensive_rating", "away_defensive_rating",
    "home_form_score", "away_form_score",
])
def test_contrapondere_o_valoare_falsificata_face_garda_sa_cada(cheie):
    """CONTRAPONDERE, obligatorie prin ADR-073 §Decizia 4.

    Fără ea, garda de mai sus ar putea trece fiindcă reproduce o tautologie,
    nu fiindcă înregistrarea e completă. Se falsifică FIECARE valoare, una
    câte una, și se cere ca reproducerea să se rupă — altfel acea valoare nu
    contează pentru rezultat și n-ar avea ce căuta în înregistrare."""
    engine = _Engine()
    home_p = _profile("Home FC", off=1.18, dfn=0.87, form=0.63)
    away_p = _profile("Away FC", off=0.94, dfn=1.12, form=0.41)
    rec, _, _ = _record(engine, home_p, away_p, _h2h(meetings=4, modifier=0.08), 0.13)

    mutat = dict(rec["oracle_inputs"])
    mutat[cheie] = float(mutat[cheie]) + 0.37

    m_home, m_away = calibrate_xg(**mutat)
    original_home = rec["oracle_outputs"]["home_xg_pre_injury"]
    original_away = rec["oracle_outputs"]["away_xg_pre_injury"]
    assert (m_home, m_away) != (original_home, original_away), (
        f"falsificarea lui `{cheie}` nu schimbă xG-ul reprodus — deci ori "
        "valoarea e inertă, ori nu e citită efectiv de calibrate_xg()")


# ── 2. PUNCTUL UNIC ────────────────────────────────────────────────────────

def test_rezolvarea_parametrilor_e_un_singur_punct_in_cod():
    """Structural, nu doar prin efect: `_calibrate_xg` și
    `_build_serving_record` trebuie să cheme AMBELE `_resolve_xg_params`.

    O rescriere viitoare care reintroduce rezolvarea inline într-una din ele
    ar putea trece testele numerice din întâmplare (azi valorile coincid),
    lăsând înregistrarea liberă să mintă mai târziu."""
    sursa = inspect.getsource(oracle_engine.FootballOracleEngine)
    assert sursa.count("def _resolve_xg_params(") == 1
    for metoda in ("_calibrate_xg", "_build_serving_record"):
        corp = inspect.getsource(getattr(oracle_engine.FootballOracleEngine, metoda))
        assert "_resolve_xg_params(" in corp, (
            f"{metoda} nu trece prin _resolve_xg_params — rezolvarea s-a duplicat")


def test_defensive_cap_vine_din_ponderile_globale_nu_per_liga():
    """[ADR-073 D1] `defensive_cap` NU trece prin `resolve_league_weights()`.
    Planul preliminar îl numărase greșit printre „cele 5 ponderi" per ligă.

    Verificat prin efect: o pondere per ligă pentru `defensive_cap` nu are
    voie să schimbe valoarea rezolvată."""
    engine = _Engine()
    base = engine._resolve_xg_params("Test League")
    assert base["defensive_cap"] == pytest.approx(2.4)

    engine.weights = dict(_WEIGHTS)
    engine.weights["league_weights"] = {
        "Test League": {"defensive_cap": 9.9, "sample_count": 99}}
    assert engine._resolve_xg_params("Test League")["defensive_cap"] == pytest.approx(2.4)


def test_baseline_cade_pe_default_pentru_liga_necunoscuta():
    engine = _Engine()
    assert engine._resolve_xg_params("Ligă Inexistentă")["baseline"] == pytest.approx(1.25)
    assert engine._resolve_xg_params("Test League")["baseline"] == pytest.approx(1.31)


# ── 3. FLAGUL ──────────────────────────────────────────────────────────────

def test_flagul_e_oprit_implicit():
    assert oracle_engine.DEFAULT_CONFIG["serving_inputs_persistence_enabled"] is False


def test_flagul_e_distinct_de_celelalte_flaguri_de_shadow():
    """North Star #3 — fiecare decizie are flagul ei. O reutilizare ar lega
    înregistrarea intrărilor de activarea logării shadow."""
    for alt in ("challenger_shadow_logging_enabled",
                "blend_challenger_shadow_logging_enabled",
                "shadow_mode_enabled", "flashscore_shadow_logging_enabled"):
        assert alt in oracle_engine.DEFAULT_CONFIG
        assert alt != "serving_inputs_persistence_enabled"


def test_flag_oprit_nu_atinge_deloc_constructia_inregistrarii(monkeypatch):
    """GARDA 3 — zero cost, nu doar None. Dacă `_build_serving_record` ar fi
    apelat și rezultatul aruncat, costul ar exista pe fiecare meci.

    GARDA SE VERIFICĂ PRIN NUMĂRĂTOARE, NU PRIN EXCEPȚIE — și motivul e o
    gaură reală, găsită prin mutație (M4, 2026-10-14). Prima versiune patcha
    `_build_serving_record` cu o funcție care ridica `AssertionError`. Dar
    `_serving_record_if_enabled` are un `except Exception` deliberat (vezi
    GARDA 5 mai jos), iar `AssertionError` ESTE o `Exception` — deci era
    prinsă, funcția întorcea `None`, exact valoarea așteptată, și testul
    trecea. Am șters complet poarta flagului și toate cele 35 de teste au
    trecut: **plasa de siguranță a codului anula garda testului.**

    Un contor nu poate fi înghițit de niciun `except`.
    """
    apeluri = {"n": 0}

    def _numara(self, **kw):
        apeluri["n"] += 1
        return {"schema_version": 1}

    # Patch pe `_Engine`, NU pe `FootballOracleEngine`: `_Engine` copiază
    # funcțiile la definirea clasei, deci un patch pe clasa reală nu l-ar
    # atinge — iar testul ar trece VID. Prima versiune făcea și asta.
    monkeypatch.setattr(_Engine, "_build_serving_record", _numara, raising=True)

    home_p = _profile("Home FC", off=1.18, dfn=0.87, form=0.63)
    away_p = _profile("Away FC", off=0.94, dfn=1.12, form=0.41)

    oprit = _Engine(config={"serving_inputs_persistence_enabled": False})
    assert oprit._serving_record_if_enabled(
        home_p, away_p, None, _pred(), 1.4, 1.1, 0.0, {}) is None
    assert apeluri["n"] == 0, "_build_serving_record atins cu flagul OPRIT"

    # Contrapondere: cu flagul PORNIT, contorul TREBUIE să crească. Fără ea,
    # testul de mai sus ar trece și dacă patch-ul n-ar fi pe calea de
    # execuție deloc.
    pornit = _Engine(config={"serving_inputs_persistence_enabled": True})
    assert pornit._serving_record_if_enabled(
        home_p, away_p, None, _pred(), 1.4, 1.1, 0.0, {}) is not None
    assert apeluri["n"] == 1, "patch-ul nu e pe calea de execuție — garda e oarbă"


def test_flag_pornit_produce_inregistrare_cu_schema_version():
    engine = _Engine(config={"serving_inputs_persistence_enabled": True})
    home_p = _profile("Home FC", off=1.18, dfn=0.87, form=0.63)
    away_p = _profile("Away FC", off=0.94, dfn=1.12, form=0.41)
    rec = engine._serving_record_if_enabled(
        home_p, away_p, None, _pred(), 1.4, 1.1, 0.0, {"home_xg_pred": 1.4})
    assert rec is not None
    assert rec["schema_version"] == 1
    assert set(rec) == {
        "schema_version", "ml_features", "oracle_inputs",
        "oracle_outputs", "data_quality", "captured_at"}


# ── 4. DOAR PE RÂNDUL `control` ────────────────────────────────────────────

@pytest.mark.parametrize("modul,functie,extra", [
    ("learning_core.challenger_shadow", "log_shadow_for_active_challenger",
     dict(algorithm_family="xgboost_v1", league_scope="all",
          control_prob_home=0.45, control_prob_draw=0.28, control_prob_away=0.27)),
    ("learning_core.blend_challenger_shadow", "log_shadow_for_active_blend_challenger",
     dict(oracle_probs=(0.45, 0.28, 0.27), league_scope="all")),
])
def test_inregistrarea_ajunge_doar_pe_randul_control(monkeypatch, modul, functie, extra):
    """Rândul `treatment` descrie Challenger-ul. Intrările Oracle pe el ar fi
    o afirmație falsă despre cine a produs ce (ADR-073 §Decizia 2)."""
    import importlib

    mod = importlib.import_module(modul)
    apeluri: list[dict] = []
    import shadow_testing

    monkeypatch.setattr(
        "learning_core.challenger_manager.get_active_challenger",
        lambda *a, **kw: {"training_run_id": "run-x"}, raising=True)
    monkeypatch.setattr(
        shadow_testing, "log_shadow_prediction",
        lambda **kw: apeluri.append(kw) or True, raising=True)
    # Inferența Challenger-ului nu e subiectul testului — se scurtcircuitează.
    for nume in ("predict_with_challenger", "predict_with_blend_challenger"):
        if hasattr(mod, nume):
            monkeypatch.setattr(mod, nume, lambda *a, **kw: (0.4, 0.3, 0.3), raising=True)

    inregistrare = {"schema_version": 1, "marcaj": "doar-control"}
    ok = getattr(mod, functie)(
        features={"home_xg_pred": 1.4},
        control_feature_metadata=inregistrare,
        fixture_id="fx-1", home_xg=1.4, away_xg=1.1,
        league="Test League", home_team="Home FC", away_team="Away FC",
        kickoff_date="2026-10-20", **extra)

    assert ok is True
    grupuri = {a["experiment_group"]: a for a in apeluri}
    assert set(grupuri) == {"treatment", "control"}
    assert grupuri["control"].get("feature_metadata") == inregistrare
    assert not grupuri["treatment"].get("feature_metadata"), (
        "înregistrarea Oracle a ajuns pe rândul `treatment`")


@pytest.mark.parametrize("modul,functie", [
    ("learning_core.challenger_shadow", "log_shadow_for_active_challenger"),
    ("learning_core.blend_challenger_shadow", "log_shadow_for_active_blend_challenger"),
])
def test_parametrul_e_opțional_si_adaptoarele_nu_citesc_niciun_flag(modul, functie):
    """Compatibilitate: apelanții existenți nu pasează parametrul nou.
    Și adaptoarele nu au voie să citească configurație — poarta trăiește în
    Oracle Engine (ADR-073 §Decizia 3)."""
    import importlib

    mod = importlib.import_module(modul)
    sig = inspect.signature(getattr(mod, functie))
    p = sig.parameters["control_feature_metadata"]
    assert p.default is None, "parametrul nou trebuie să fie opțional"

    assert "serving_inputs_persistence_enabled" not in _siruri_din_cod(mod), (
        f"{modul} citește flagul — poarta trebuie să rămână în Oracle Engine")


# ── 5. NEDEGRADARE ─────────────────────────────────────────────────────────

def test_o_eroare_in_inregistrare_nu_opreste_logarea_shadow(monkeypatch):
    """GARDA 5. Înregistrarea e observațională. O excepție în construcția ei
    nu are voie să anuleze logarea shadow, care funcționează deja — altfel o
    îmbunătățire de trasabilitate distruge un flux existent (North Star #1)."""
    def _boom(*a, **kw):
        raise RuntimeError("profil corupt")

    # Patch pe `_Engine` — vezi explicația din testul de zero cost.
    monkeypatch.setattr(_Engine, "_build_serving_record", _boom, raising=True)

    engine = _Engine(config={"serving_inputs_persistence_enabled": True})
    home_p = _profile("Home FC", off=1.18, dfn=0.87, form=0.63)
    away_p = _profile("Away FC", off=0.94, dfn=1.12, form=0.41)
    assert engine._serving_record_if_enabled(
        home_p, away_p, None, _pred(), 1.4, 1.1, 0.0, {}) is None


# ── 6. ETAPA ACCIDENTĂRILOR, raportată nu presupusă (ADR-073 §D2) ─────────

def test_xg_changed_after_injury_step_raporteaza_strict_pre_vs_post():
    """Câmpul spune STRICT că pre != post. NU pretinde că a existat un
    aliniament — informația aceea nu ajunge până aici (Regula #8)."""
    engine = _Engine(config={"serving_inputs_persistence_enabled": True})
    home_p = _profile("Home FC", off=1.18, dfn=0.87, form=0.63)
    away_p = _profile("Away FC", off=0.94, dfn=1.12, form=0.41)

    neatins = engine._build_serving_record(
        home_p=home_p, away_p=away_p, h2h=None, league="Test League",
        weather_penalty=0.0, ml_features={},
        home_xg_pre_injury=1.40, away_xg_pre_injury=1.10,
        home_xg=1.40, away_xg=1.10)
    assert neatins["oracle_outputs"]["xg_changed_after_injury_step"] is False

    penalizat = engine._build_serving_record(
        home_p=home_p, away_p=away_p, h2h=None, league="Test League",
        weather_penalty=0.0, ml_features={},
        home_xg_pre_injury=1.40, away_xg_pre_injury=1.10,
        home_xg=1.12, away_xg=1.10)
    assert penalizat["oracle_outputs"]["xg_changed_after_injury_step"] is True
    # Ambele xG rămân disponibile — reproducerea nu depinde de egalitatea lor.
    assert penalizat["oracle_outputs"]["home_xg_pre_injury"] == pytest.approx(1.40)
    assert penalizat["oracle_outputs"]["home_xg"] == pytest.approx(1.12)


def test_data_quality_e_pe_acelasi_rand_cu_predictia():
    """Motivul concret, plătit pe 2026-10-14: o partiție pe
    `match_history.home_data_quality` (ÎNGHEȚAT prin COALESCE) contra
    predicției SERVITE a produs „59-76%" când cifra corectă e 34%."""
    engine = _Engine(config={"serving_inputs_persistence_enabled": True})
    rec = engine._build_serving_record(
        home_p=_profile("Home FC", off=1.1, dfn=0.9, form=0.5, dq="neutral"),
        away_p=_profile("Away FC", off=1.0, dfn=1.0, form=0.4, dq="live"),
        h2h=None, league="Test League", weather_penalty=0.0, ml_features={},
        home_xg_pre_injury=1.4, away_xg_pre_injury=1.1, home_xg=1.4, away_xg=1.1)
    assert rec["data_quality"] == {"home": "neutral", "away": "live"}


def test_inregistrarea_nu_aliaseaza_dictul_de_ml_features():
    """`ml_features` e refolosit de apelant după construcția înregistrării.
    O referință partajată ar lega cele două, iar o mutație ulterioară ar
    rescrie tăcut ce s-a înregistrat."""
    engine = _Engine(config={"serving_inputs_persistence_enabled": True})
    mlf = {"home_xg_pred": 1.4}
    rec = engine._build_serving_record(
        home_p=_profile("Home FC", off=1.1, dfn=0.9, form=0.5),
        away_p=_profile("Away FC", off=1.0, dfn=1.0, form=0.4),
        h2h=None, league="Test League", weather_penalty=0.0, ml_features=mlf,
        home_xg_pre_injury=1.4, away_xg_pre_injury=1.1, home_xg=1.4, away_xg=1.1)
    mlf["home_xg_pred"] = 99.0
    assert rec["ml_features"]["home_xg_pred"] == pytest.approx(1.4)
