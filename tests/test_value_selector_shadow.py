"""
Teste pentru Value Selector Shadow Runner (ADR-071, faza F2).

Acopera cerintele explicite ale Gate Review-ului F2:
  - toate cele 13 profile ruleaza pe aceleasi intrari;
  - profilele semantic identice sunt marcate ca o singura familie;
  - `odds_freshness` ramane UNKNOWN, niciodata PASS;
  - verdictele si motivele fiecarei porti se persista;
  - candidatii RESPINSI se persista, nu doar Top 5;
  - `leakage_suspect` se persista per candidat;
  - determinism, max 1 selectie/meci, max 5 meciuri/zi, fara completare;
  - simetrie H/X/A;
  - fallback/neutral nu ajunge in Longshot;
  - izolarea motorului: runner-ul nu invoca Oracle Engine si nu scrie in nicio
    tabela existenta.

Fara retea, fara Supabase, fara ceas de sistem (momentul e mereu injectat).
"""
from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from value_selector import SelectorPolicy
from value_selector_config import F2_PROFILES
from value_selector_shadow import (
    SHADOW_TABLE,
    build_rows_for_all_profiles,
    candidates_from_rows,
    policy_families,
    prediction_view_from_row,
    semantic_duplicates,
    to_db_rows,
    _devig,
)

RUNNER = Path(__file__).resolve().parent.parent / "value_selector_shadow.py"

MOMENT = datetime(2026, 9, 4, 8, 15, tzinfo=timezone.utc)
KICKOFF = "2026-09-04T19:00:00+00:00"


def make_row(fixture_id: str = "fx-1", *, prob=(0.58, 0.22, 0.20),
             odds=(2.20, 3.60, 3.10), quality=("live", "live"),
             kickoff: str = KICKOFF, prediction_time: str | None = None) -> dict:
    return {
        "fixture_id": fixture_id,
        "home_team": "Echipa A", "away_team": "Echipa B",
        "league": "Test League", "kickoff_utc": kickoff,
        "home_data_quality": quality[0], "away_data_quality": quality[1],
        "prediction_time": prediction_time or "2026-09-02T03:00:00+00:00",
        "prob_home": prob[0], "prob_draw": prob[1], "prob_away": prob[2],
        "odds_home": odds[0], "odds_draw": odds[1], "odds_away": odds[2],
        "bookmaker": "test-bk",
    }


# ── Cele 13 profile ──────────────────────────────────────────────────────────

def test_exista_exact_13_profile_aprobate():
    assert len(F2_PROFILES) == 13


def test_toate_cele_13_profile_ruleaza_pe_aceleasi_intrari():
    candidaturi = candidates_from_rows([make_row()], evaluated_at=MOMENT)
    rows = build_rows_for_all_profiles(candidaturi, run_id="r1", evaluated_at=MOMENT)

    profile_rulate = {r["policy_profile"] for r in rows}
    assert profile_rulate == set(F2_PROFILES)
    # fiecare profil evalueaza fiecare selectie exact o data
    for profil in F2_PROFILES:
        ale_lui = [r for r in rows if r["policy_profile"] == profil]
        assert len(ale_lui) == len(candidaturi) == 3


def test_fiecare_profil_are_policy_id_propriu_in_randurile_persistate():
    candidaturi = candidates_from_rows([make_row()], evaluated_at=MOMENT)
    rows = build_rows_for_all_profiles(candidaturi, run_id="r1", evaluated_at=MOMENT)

    per_profil = {r["policy_profile"]: r["policy_id"] for r in rows}
    assert len(set(per_profil.values())) == len(F2_PROFILES)
    for profil, policy_id in per_profil.items():
        assert policy_id.startswith(f"{profil}@v1:")


# ── Deduplicarea analitica ───────────────────────────────────────────────────

def test_profilele_semantic_identice_sunt_marcate_ca_o_singura_familie():
    """`shrunk_050` si `market_floor_025` sunt aceeasi politica sub doua nume —
    centrul comun al celor doua grile. `policy_id` ramane distinct pentru
    trasabilitate, dar familia trebuie sa fie una singura, ca la analiza F3 sa
    nu cantareasca dublu."""
    duplicate = semantic_duplicates(F2_PROFILES)
    assert duplicate, "se astepta cel putin o pereche semantic identica"

    familii = policy_families(F2_PROFILES)
    for membri in duplicate.values():
        assert len({familii[m] for m in membri}) == 1

    assert familii["shrunk_050"] == familii["market_floor_025"]


def test_numarul_de_familii_e_mai_mic_decat_numarul_de_profile():
    familii = set(policy_families(F2_PROFILES).values())
    assert len(familii) < len(F2_PROFILES)


def test_familia_e_stabila_indiferent_de_ordinea_dictionarului():
    inversat = dict(reversed(list(F2_PROFILES.items())))
    assert policy_families(F2_PROFILES) == policy_families(inversat)


def test_familia_se_persista_pe_fiecare_rand():
    candidaturi = candidates_from_rows([make_row()], evaluated_at=MOMENT)
    rows = build_rows_for_all_profiles(candidaturi, run_id="r1", evaluated_at=MOMENT)
    assert all(r["policy_family"] for r in rows)
    assert all(r["policy_fingerprint"] for r in rows)

    familii_pe_profil = {r["policy_profile"]: r["policy_family"] for r in rows}
    assert familii_pe_profil["shrunk_050"] == familii_pe_profil["market_floor_025"]


# ── Prospetimea cotei ramane necunoscuta ─────────────────────────────────────

def test_prospetimea_cotei_ramane_UNKNOWN_niciodata_PASS():
    politica = SelectorPolicy(profile="t", ranker_id="probability_first",
                              max_odds_age_s=3600.0, legacy_relative_edge_floor_pct=None)
    candidaturi = candidates_from_rows([make_row()], evaluated_at=MOMENT)
    rows = build_rows_for_all_profiles(candidaturi, run_id="r1", evaluated_at=MOMENT,
                                       profiles={"t": politica})

    for row in rows:
        assert row["odds_freshness_s"] is None
        assert row["gate_verdicts"]["odds_fresh"] == "unknown"


def test_prospetimea_predictiei_e_calculata_si_persistata():
    rand = make_row(prediction_time="2026-09-02T03:00:00+00:00")
    candidaturi = candidates_from_rows([rand], evaluated_at=MOMENT)
    asteptat = (MOMENT - datetime(2026, 9, 2, 3, 0, tzinfo=timezone.utc)).total_seconds()
    assert all(c.prediction_age_s == pytest.approx(asteptat) for c in candidaturi)


# ── Persistenta completa a deciziilor ────────────────────────────────────────

def test_se_persista_si_candidatii_respinsi_nu_doar_top_5():
    randuri = [make_row(f"fx-{i}", prob=(0.60 - i * 0.02, 0.22, 0.18)) for i in range(8)]
    candidaturi = candidates_from_rows(randuri, evaluated_at=MOMENT)
    rows = build_rows_for_all_profiles(candidaturi, run_id="r1", evaluated_at=MOMENT)

    ale_unui_profil = [r for r in rows if r["policy_profile"] == "shrunk_050"]
    assert len(ale_unui_profil) == 24                     # 8 meciuri × 3 selectii
    assert sum(1 for r in ale_unui_profil if r["selected_top"]) <= 5
    assert sum(1 for r in ale_unui_profil if r["rejected"]) > 0


def test_verdictele_si_motivele_fiecarei_porti_se_persista():
    candidaturi = candidates_from_rows(
        [make_row(quality=("neutral", "neutral"))], evaluated_at=MOMENT)
    rows = build_rows_for_all_profiles(candidaturi, run_id="r1", evaluated_at=MOMENT)

    for row in rows:
        assert len(row["gate_verdicts"]) == 13
        assert set(row["gate_verdicts"].values()) <= {
            "pass", "fail", "unknown", "not_applicable"}
        assert isinstance(row["rejection_reasons"], list)
        assert isinstance(row["gate_details"], dict)

    respinse = [r for r in rows if r["rejected"]]
    assert respinse
    assert any(r["rejection_reasons"] for r in respinse)


def test_categoria_si_cele_trei_stegulete_sunt_consecvente():
    randuri = [make_row("fx-1"), make_row("fx-2", prob=(0.30, 0.25, 0.45))]
    candidaturi = candidates_from_rows(randuri, evaluated_at=MOMENT)
    rows = build_rows_for_all_profiles(candidaturi, run_id="r1", evaluated_at=MOMENT)

    for row in rows:
        stegulete = [row["selected_top"], row["selected_longshot"], row["rejected"]]
        assert sum(bool(s) for s in stegulete) == 1
        asteptat = {"top": 0, "longshot": 1, "rejected": 2}[row["category"]]
        assert stegulete[asteptat] is True


def test_toate_campurile_cerute_de_gate_review_sunt_prezente():
    candidaturi = candidates_from_rows([make_row()], evaluated_at=MOMENT)
    rows = build_rows_for_all_profiles(candidaturi, run_id="r1", evaluated_at=MOMENT)

    cerute = {
        "fixture_id", "selection_code", "model_probability", "fair_probability",
        "absolute_edge_pp", "relative_edge_pct", "p_shr", "ev_raw", "ev_shr",
        "rank_in_match", "policy_id", "ranker_id", "shrinkage_w", "gate_verdicts",
        "rejection_reasons", "data_quality", "prediction_freshness_s",
        "odds_freshness_s", "matches_analysed", "selected_top", "selected_longshot",
        "rejected", "leakage_suspect",
    }
    assert cerute <= set(rows[0])


# ── Scurgere temporala ───────────────────────────────────────────────────────

def test_leakage_suspect_se_persista_per_candidat():
    viitor = candidates_from_rows([make_row()], evaluated_at=MOMENT)
    trecut = candidates_from_rows(
        [make_row(kickoff="2026-09-04T07:00:00+00:00")], evaluated_at=MOMENT)

    rows_viitor = build_rows_for_all_profiles(viitor, run_id="r", evaluated_at=MOMENT)
    rows_trecut = build_rows_for_all_profiles(trecut, run_id="r", evaluated_at=MOMENT)

    assert all(r["leakage_suspect"] is False for r in rows_viitor)
    assert all(r["leakage_suspect"] is True for r in rows_trecut)


def test_un_meci_deja_inceput_e_respins_cu_motiv_de_piata_inchisa():
    candidaturi = candidates_from_rows(
        [make_row(kickoff="2026-09-04T07:00:00+00:00")], evaluated_at=MOMENT)
    rows = build_rows_for_all_profiles(candidaturi, run_id="r", evaluated_at=MOMENT)
    assert all(not r["selected_top"] for r in rows)
    assert all("market_closed" in r["rejection_reasons"] for r in rows)


# ── Determinism si invarianti de selectie ────────────────────────────────────

def test_doua_rulari_pe_aceleasi_intrari_produc_randuri_identice():
    candidaturi = candidates_from_rows(
        [make_row("fx-1"), make_row("fx-2", prob=(0.52, 0.24, 0.24))], evaluated_at=MOMENT)
    r1 = build_rows_for_all_profiles(candidaturi, run_id="r", evaluated_at=MOMENT)
    r2 = build_rows_for_all_profiles(candidaturi, run_id="r", evaluated_at=MOMENT)
    assert r1 == r2


def test_maxim_o_selectie_per_meci_si_cinci_meciuri_pe_zi_in_toate_profilele_de_radar():
    randuri = [make_row(f"fx-{i}", prob=(0.60 - i * 0.01, 0.22, 0.18)) for i in range(9)]
    candidaturi = candidates_from_rows(randuri, evaluated_at=MOMENT)
    rows = build_rows_for_all_profiles(candidaturi, run_id="r", evaluated_at=MOMENT)

    for profil, politica in F2_PROFILES.items():
        if not politica.one_selection_per_match:
            continue
        top = [r for r in rows if r["policy_profile"] == profil and r["selected_top"]]
        assert len(top) <= 5, profil
        assert len({r["fixture_id"] for r in top}) == len(top), profil


def test_fara_completare_artificiala_cand_exista_o_singura_selectie_buna():
    randuri = [make_row("fx-bun")] + [
        make_row(f"fx-slab-{i}", quality=("neutral", "neutral")) for i in range(6)]
    candidaturi = candidates_from_rows(randuri, evaluated_at=MOMENT)
    rows = build_rows_for_all_profiles(candidaturi, run_id="r", evaluated_at=MOMENT)

    top = [r for r in rows if r["policy_profile"] == "shrunk_050" and r["selected_top"]]
    assert len(top) == 1
    assert top[0]["fixture_id"] == "fx-bun"


def test_simetria_HXA_se_pastreaza_prin_tot_lantul_de_persistenta():
    """Acelasi meci, cu gazda si oaspetele permutati — randurile persistate
    trebuie sa se permute identic, cu aceleasi numere."""
    direct = candidates_from_rows(
        [make_row("fx", prob=(0.58, 0.22, 0.20), odds=(2.20, 3.60, 3.10))],
        evaluated_at=MOMENT)
    invers = candidates_from_rows(
        [make_row("fx", prob=(0.20, 0.22, 0.58), odds=(3.10, 3.60, 2.20))],
        evaluated_at=MOMENT)

    r1 = build_rows_for_all_profiles(direct, run_id="r", evaluated_at=MOMENT)
    r2 = build_rows_for_all_profiles(invers, run_id="r", evaluated_at=MOMENT)

    top1 = [r for r in r1 if r["policy_profile"] == "shrunk_050" and r["selected_top"]]
    top2 = [r for r in r2 if r["policy_profile"] == "shrunk_050" and r["selected_top"]]
    assert [r["selection_code"] for r in top1] == ["1"]
    assert [r["selection_code"] for r in top2] == ["2"]
    assert top1[0]["actionability_score"] == pytest.approx(top2[0]["actionability_score"])
    assert top1[0]["absolute_edge_pp"] == pytest.approx(top2[0]["absolute_edge_pp"])


def test_fallback_neutral_nu_ajunge_niciodata_in_longshot():
    """Constanta reala de fallback masurata in productie: 34,1 / 37,0 / 28,9."""
    rand = make_row("fx-el", prob=(0.341, 0.370, 0.289), odds=(3.30, 4.40, 2.05),
                    quality=("neutral", "neutral"))
    candidaturi = candidates_from_rows([rand], evaluated_at=MOMENT)
    rows = build_rows_for_all_profiles(candidaturi, run_id="r", evaluated_at=MOMENT)

    for profil, politica in F2_PROFILES.items():
        if not politica.require_sufficient_data_quality:
            continue
        ale_lui = [r for r in rows if r["policy_profile"] == profil]
        assert not any(r["selected_longshot"] for r in ale_lui), profil
        assert not any(r["selected_top"] for r in ale_lui), profil
        assert all("data_quality_insufficient" in r["rejection_reasons"] for r in ale_lui)


# ── De-vig ───────────────────────────────────────────────────────────────────

def test_devigul_local_e_identic_cu_cel_al_motorului():
    """Runner-ul nu importa motorul, deci reimplementeaza de-vig-ul. Echivalenta
    se fixeaza aici — testele au voie sa importe motorul, codul de productie nu."""
    import oracle_engine

    for odds in [(2.10, 3.40, 3.60), (1.36, 5.56, 7.97), (10.67, 6.44, 1.28)]:
        implicite = [1.0 / o for o in odds]
        asteptat = oracle_engine.FootballOracleEngine._devig_probabilities(*implicite)
        assert _devig(*odds) == pytest.approx(asteptat)


def test_suma_probabilitatilor_fair_e_unu():
    fh, fd, fa = _devig(2.10, 3.40, 3.60)
    assert fh + fd + fa == pytest.approx(1.0)


# ── Constructia vederii din randuri ──────────────────────────────────────────

def test_un_rand_fara_cote_valide_nu_produce_candidaturi():
    assert prediction_view_from_row(make_row(odds=(1.0, 3.4, 3.6))) is None
    assert prediction_view_from_row({"fixture_id": "x"}) is None
    assert candidates_from_rows([{"fixture_id": "x"}], evaluated_at=MOMENT) == []


def test_matches_analysed_ramane_necunoscut_in_V1():
    candidaturi = candidates_from_rows([make_row()], evaluated_at=MOMENT)
    assert all(c.matches_analysed is None for c in candidaturi)


# ── Izolarea motorului si a bazei de date ────────────────────────────────────

def _tabele_scrise(sursa: str) -> set[str]:
    """Numele tabelelor care apar intr-un lant care contine o metoda de scriere.
    Verifica invariantul, nu o lista de nume — un `insert` nou intr-o alta
    tabela cade automat."""
    scrieri = {"upsert", "insert", "update", "delete", "rpc"}
    gasite: set[str] = set()
    for nod in ast.walk(ast.parse(sursa)):
        if not (isinstance(nod, ast.Call) and isinstance(nod.func, ast.Attribute)):
            continue
        if nod.func.attr not in scrieri:
            continue
        curent: ast.AST = nod.func.value
        while isinstance(curent, ast.Call):
            if isinstance(curent.func, ast.Attribute) and curent.func.attr == "table" \
                    and curent.args and isinstance(curent.args[0], ast.Constant):
                gasite.add(str(curent.args[0].value))
                break
            curent = curent.func.value if isinstance(curent.func, ast.Attribute) else curent
            if not isinstance(curent, (ast.Call, ast.Attribute)):
                break
        else:
            if isinstance(curent, ast.Name):
                gasite.add(f"<variabila:{curent.id}>")
    return gasite


def test_runnerul_scrie_exclusiv_in_tabela_proprie():
    scrise = _tabele_scrise(RUNNER.read_text(encoding="utf-8"))
    assert scrise <= {SHADOW_TABLE, "<variabila:client>"}, (
        f"runner-ul scrie in tabele care nu-i apartin: {sorted(scrise)}")


def test_garda_de_scriere_chiar_prinde_o_incalcare():
    """CONTRA-TEST: fara el, garda ar putea intoarce mereu multimea vida."""
    mutant = 'client.table("match_history").upsert({"a": 1}).execute()\n'
    assert _tabele_scrise(mutant) == {"match_history"}


def test_runnerul_nu_importa_oracle_engine():
    arbore = ast.parse(RUNNER.read_text(encoding="utf-8"))
    module: set[str] = set()
    for nod in ast.walk(arbore):
        if isinstance(nod, ast.Import):
            module.update(a.name.split(".")[0] for a in nod.names)
        elif isinstance(nod, ast.ImportFrom) and nod.module:
            module.add(nod.module.split(".")[0])
    interzise = {"oracle_engine", "oracle_api", "feature_engine", "ml_predictor",
                 "recalibration", "shadow_testing", "supabase_client", "app"}
    assert not (module & interzise), f"runner-ul importa: {sorted(module & interzise)}"


APELURI_DE_PRODUCTIE_INTERZISE = {
    "evaluate_match", "_cache_prediction", "retrain_ml_model", "retrain",
    "promote", "rollback", "recalibrate_weights", "recalibrate",
    "save_weights", "upsert_match", "upsert_match_canonical",
}


def _nume_apelate(sursa: str) -> set[str]:
    """Numele efectiv APELATE in cod. Analiza pe AST — un docstring care explica
    de ce un apel e interzis nu declanseaza garda.

    Aceasta e a treia oara in acest proiect cand o garda pe text se declanseaza
    pe propria documentatie (precedente: `pipefail`, `_doar_cod()`). Prima
    versiune a acestui test cauta subsiruri si a cazut pe propriul docstring."""
    gasite: set[str] = set()
    for nod in ast.walk(ast.parse(sursa)):
        if isinstance(nod, ast.Call):
            if isinstance(nod.func, ast.Name):
                gasite.add(nod.func.id)
            elif isinstance(nod.func, ast.Attribute):
                gasite.add(nod.func.attr)
    return gasite


def test_runnerul_nu_declanseaza_nicio_predictie():
    apelate = _nume_apelate(RUNNER.read_text(encoding="utf-8"))
    interzise = apelate & APELURI_DE_PRODUCTIE_INTERZISE
    assert not interzise, f"runner-ul apeleaza cod de productie interzis: {sorted(interzise)}"


def test_garda_de_apeluri_chiar_prinde_o_incalcare_dar_nu_si_documentatia():
    """CONTRA-TEST dublu: prinde apelul real, ignora mentiunea din docstring."""
    mutant = "def f(engine, m):\n    return engine.evaluate_match(m)\n"
    assert _nume_apelate(mutant) & APELURI_DE_PRODUCTIE_INTERZISE == {"evaluate_match"}

    doar_documentatie = (
        '"""Nu apelam niciodata evaluate_match() si nici _cache_prediction()."""\n'
        "def f():\n"
        '    """Nici aici: recalibrate_weights ramane interzis."""\n'
        "    return 1\n"
    )
    assert not (_nume_apelate(doar_documentatie) & APELURI_DE_PRODUCTIE_INTERZISE)


def test_flagul_de_colectare_e_implicit_oprit():
    from value_selector_config import _DEFAULT_CONFIG

    assert _DEFAULT_CONFIG["value_selector_shadow_logging_enabled"] is False
    assert _DEFAULT_CONFIG["value_selector_v1_enabled"] is False


def test_rularea_cu_flagul_oprit_nu_face_nimic(monkeypatch):
    import value_selector_shadow as vss

    monkeypatch.setattr(vss, "is_shadow_logging_enabled", lambda: False)
    raport = vss.run()
    assert raport == {"enabled": False, "candidates": 0, "rows": 0, "persisted": 0}


# ── Concordanta cod <-> schema migrarii (post-migration guard) ───────────────

MIGRARE = (Path(__file__).resolve().parent.parent / "database" / "migrations"
           / "055_value_selector_shadow.sql")


def _coloane_din_migrare(sql: str) -> set[str]:
    """Numele coloanelor declarate in CREATE TABLE. Parsare a corpului dintre
    prima paranteza si `UNIQUE (`, ignorand liniile de comentariu — o coloana
    mentionata doar intr-un comentariu nu conteaza ca declarata."""
    corp = sql.split("CREATE TABLE IF NOT EXISTS value_selector_shadow (", 1)[1]
    corp = corp.split("UNIQUE (", 1)[0]
    coloane: set[str] = set()
    for linie in corp.splitlines():
        linie = linie.strip()
        if not linie or linie.startswith("--"):
            continue
        primul = linie.split()[0]
        if primul.isidentifier():
            coloane.add(primul)
    return coloane


def test_toate_cheile_scrise_de_runner_exista_ca_coloane_in_migrare():
    """Fara aceasta garda, o cheie in plus ar face `upsert` sa esueze in
    productie — iar esecul e doar logat ca avertisment, deci ar trece
    neobservat pana la evaluarea F3, cu date lipsa."""
    candidaturi = candidates_from_rows([make_row()], evaluated_at=MOMENT)
    rows = build_rows_for_all_profiles(candidaturi, run_id="r", evaluated_at=MOMENT)

    scrise = set(rows[0])
    declarate = _coloane_din_migrare(MIGRARE.read_text(encoding="utf-8"))
    lipsa = scrise - declarate
    assert not lipsa, f"runner-ul scrie chei fara coloana in migrare: {sorted(lipsa)}"


def test_migrarea_declara_coloanele_generate_de_baza_de_date():
    declarate = _coloane_din_migrare(MIGRARE.read_text(encoding="utf-8"))
    assert {"id", "created_at"} <= declarate
    assert len(declarate) == 41


def test_garda_de_schema_chiar_prinde_o_coloana_lipsa():
    """CONTRA-TEST: garda trebuie sa vada absenta reala, nu sa treaca vida."""
    fals = ("CREATE TABLE IF NOT EXISTS value_selector_shadow (\n"
            "    id BIGINT PRIMARY KEY,\n"
            "    -- policy_family TEXT,   (doar comentariu, nu declaratie)\n"
            "    run_id TEXT NOT NULL,\n"
            "    UNIQUE (run_id)\n);")
    coloane = _coloane_din_migrare(fals)
    assert coloane == {"id", "run_id"}
    assert "policy_family" not in coloane


def test_migrarea_are_RLS_si_nicio_policy_publica():
    sql = MIGRARE.read_text(encoding="utf-8")
    doar_cod = "\n".join(l for l in sql.splitlines() if not l.strip().startswith("--"))
    assert "ENABLE ROW LEVEL SECURITY" in doar_cod
    assert "CREATE POLICY" not in doar_cod
    for periculos in ("DROP ", "DELETE ", "TRUNCATE", "ALTER TABLE match_history",
                      "ALTER TABLE odds_history", "ALTER TABLE shadow_predictions"):
        assert periculos not in doar_cod, f"migrarea contine operatie interzisa: {periculos}"


# ── Rulare manuala fortata: doar gate-ul de flag, nimic altceva ──────────────

def test_forta_ocoleste_doar_verificarea_flagului(monkeypatch):
    """`force=True` nu activeaza niciun flag si nu atinge configuratia — doar
    permite unei rulari manuale autorizate sa treaca de gate."""
    import value_selector_shadow as vss

    monkeypatch.setattr(vss, "is_shadow_logging_enabled", lambda: False)
    monkeypatch.setattr(vss, "load_inputs", lambda **kw: ([], {"gasite": 0, "retinute": 0}))

    fara = vss.run()
    assert fara["enabled"] is False

    cu = vss.run(force=True, dry_run=True)
    assert cu["enabled"] is True and cu["forced"] is True and cu["persisted"] == 0


def test_calea_programata_nu_poate_forta_niciodata():
    """Invariant de workflow: `--force` apare doar sub o expresie legata de
    `github.event.inputs`, care e goala la rularile de cron. O rulare automata
    nu poate ocoli gate-ul din greseala."""
    wf = (Path(__file__).resolve().parent.parent / ".github" / "workflows"
          / "value_selector_shadow.yml").read_text(encoding="utf-8")
    doar_cod = "\n".join(l for l in wf.splitlines() if not l.strip().startswith("#"))

    linii_cu_force = [l for l in doar_cod.splitlines() if "--force" in l]
    assert linii_cu_force, "workflow-ul nu mai expune deloc --force"
    for linie in linii_cu_force:
        assert "github.event.inputs.force == 'true'" in linie, (
            f"--force apare neconditionat de input manual: {linie.strip()}")


def test_flagul_de_colectare_ramane_oprit_indiferent_de_forta():
    """Forta nu scrie nimic in configuratie — verificat pe cod, nu presupus."""
    sursa = RUNNER.read_text(encoding="utf-8")
    apelate = _nume_apelate(sursa)
    assert "save_config" not in apelate and "update_config" not in apelate
    assert "set_config" not in apelate


# ── Garzi de scurgere temporala la incarcare ─────────────────────────────────

def test_load_inputs_intoarce_si_contoare_de_excludere():
    """Diferenta dintre meciurile gasite si cele evaluate nu are voie sa fie o
    cifra neexplicata — fiecare excludere are contorul ei."""
    import inspect
    import value_selector_shadow as vss

    sursa = inspect.getsource(vss.load_inputs)
    for contor in ("deja_incepute", "fara_predictie", "fara_cote",
                   "predictie_dupa_kickoff", "retinute", "gasite"):
        assert contor in sursa, f"contor lipsa la incarcare: {contor}"
    assert 'kickoff <= moment' in sursa, "lipseste garda pe momentul exact"


# ── Determinism la alegerea sursei (citire) ──────────────────────────────────

class _TabelaFalsa:
    """Client Supabase minimal, care intoarce randurile in ordinea data — ca sa
    putem demonstra ca alegerea NU depinde de ordinea de sosire."""

    def __init__(self, rows):
        self._rows = rows

    def table(self, _name):
        return self

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def in_(self, *_a, **_k):
        return self

    def is_(self, *_a, **_k):
        return self

    def execute(self):
        return type("R", (), {"data": list(self._rows)})()


def test_alegerea_casei_de_pariuri_nu_depinde_de_ordinea_randurilor():
    """Un meci cu doua case de pariuri trebuie sa produca aceeasi cota
    indiferent de ordinea in care Supabase intoarce randurile."""
    from value_selector_shadow import _load_odds

    a = {"id": 10, "fixture_id": "fx", "bookmaker": "Alfa",
         "opening_home": 2.0, "opening_draw": 3.4, "opening_away": 3.9,
         "closing_home": None, "closing_draw": None, "closing_away": None}
    b = {"id": 20, "fixture_id": "fx", "bookmaker": "Beta",
         "opening_home": 2.2, "opening_draw": 3.2, "opening_away": 3.7,
         "closing_home": None, "closing_draw": None, "closing_away": None}

    intr_un_sens = _load_odds(_TabelaFalsa([a, b]), ["fx"])
    in_celalalt = _load_odds(_TabelaFalsa([b, a]), ["fx"])

    assert intr_un_sens == in_celalalt
    assert intr_un_sens["fx"]["bookmaker"] == "Alfa"     # id-ul mai mic castiga


def test_alegerea_predictiei_nu_depinde_de_ordinea_randurilor():
    """La egalitate de `prediction_time`, alegerea trebuie sa fie tot stabila."""
    from value_selector_shadow import _load_predictions

    a = {"id": 10, "fixture_id": "fx", "prediction_time": "2026-09-02T03:00:00+00:00",
         "prob_home": 0.5, "prob_draw": 0.25, "prob_away": 0.25}
    b = {"id": 20, "fixture_id": "fx", "prediction_time": "2026-09-02T03:00:00+00:00",
         "prob_home": 0.4, "prob_draw": 0.30, "prob_away": 0.30}

    assert _load_predictions(_TabelaFalsa([a, b]), ["fx"]) == \
           _load_predictions(_TabelaFalsa([b, a]), ["fx"])


def test_predictia_cea_mai_veche_ramane_cea_aleasa():
    from value_selector_shadow import _load_predictions

    veche = {"id": 99, "fixture_id": "fx", "prediction_time": "2026-09-01T03:00:00+00:00",
             "prob_home": 0.5, "prob_draw": 0.25, "prob_away": 0.25}
    noua = {"id": 1, "fixture_id": "fx", "prediction_time": "2026-09-03T03:00:00+00:00",
            "prob_home": 0.4, "prob_draw": 0.30, "prob_away": 0.30}

    ales = _load_predictions(_TabelaFalsa([noua, veche]), ["fx"])
    assert ales["fx"]["prediction_time"] == "2026-09-01T03:00:00+00:00"


# ── FAIL-LOUD la persistare (T1-T10) ─────────────────────────────────────────
# Esecul se simuleaza cu un client fals. NU se produce niciodata o scriere
# reala, partiala sau nu — scopul e verificarea fluxului de control.

class _ClientFals:
    """Client Supabase minimal care numara loturile si poate esua la unul anume."""

    def __init__(self, esueaza_la: int | None = None):
        self.esueaza_la = esueaza_la
        self.loturi: list[list[dict]] = []
        self.on_conflict: list[str] = []
        self.tabele: list[str] = []
        self.operatii: list[str] = []
        self._lot_curent: list[dict] = []

    def table(self, nume):
        self.tabele.append(nume)
        return self

    def upsert(self, lot, on_conflict=None):
        self.operatii.append("upsert")
        self._lot_curent = list(lot)
        self.on_conflict.append(on_conflict)
        return self

    def delete(self, *_a, **_k):        # nu trebuie apelat niciodata
        self.operatii.append("delete")
        return self

    def update(self, *_a, **_k):
        self.operatii.append("update")
        return self

    def execute(self):
        if self.esueaza_la is not None and len(self.loturi) + 1 == self.esueaza_la:
            raise RuntimeError("esec simulat de retea")
        self.loturi.append(self._lot_curent)
        return type("R", (), {"data": self._lot_curent})()


def _randuri_de_test(n: int) -> list[dict]:
    return [{"run_id": "r", "policy_id": "p@v1:abc", "fixture_id": f"fx-{i}",
             "selection_code": "1", "model_probability": 0.5} for i in range(n)]


def _cu_client(monkeypatch, client):
    import database.queries as dq
    monkeypatch.setattr(dq, "get_client", lambda: client)


def test_T1_toate_loturile_reusesc_returneaza_totalul(monkeypatch):
    from value_selector_shadow import persist_rows

    client = _ClientFals()
    _cu_client(monkeypatch, client)
    assert persist_rows(_randuri_de_test(1250)) == 1250
    assert [len(l) for l in client.loturi] == [500, 500, 250]


@pytest.mark.parametrize("lot_care_cade, eticheta", [(1, "primul"), (2, "din mijloc"), (3, "ultimul")])
def test_T2_T3_T4_orice_lot_esuat_propaga_exceptia(monkeypatch, lot_care_cade, eticheta):
    from value_selector_shadow import ShadowPersistError, persist_rows

    client = _ClientFals(esueaza_la=lot_care_cade)
    _cu_client(monkeypatch, client)
    with pytest.raises(ShadowPersistError) as exc:
        persist_rows(_randuri_de_test(1250))

    assert "INCOMPLETA" in str(exc.value)
    assert exc.value.__cause__ is not None          # cauza originala se pastreaza
    # fail-fast: nu se mai incearca loturile de dupa cel esuat
    assert len(client.loturi) == lot_care_cade - 1


def test_T5_rularea_nu_poate_raporta_succes_dupa_o_exceptie_de_persistare(monkeypatch):
    """`run()` nu prinde exceptia, deci procesul iese cu cod != 0 si workflow-ul
    devine ROSU — nu verde cu date partiale."""
    import value_selector_shadow as vss

    monkeypatch.setattr(vss, "is_shadow_logging_enabled", lambda: True)
    monkeypatch.setattr(vss, "load_inputs", lambda **kw: ([make_row()], {"retinute": 1}))
    _cu_client(monkeypatch, _ClientFals(esueaza_la=1))

    with pytest.raises(vss.ShadowPersistError):
        vss.run(now=MOMENT)


def test_T5b_fara_client_dar_cu_randuri_de_scris_se_arunca(monkeypatch):
    """Altfel rularea ar iesi verde fara sa fi scris nimic."""
    from value_selector_shadow import ShadowPersistError, persist_rows

    _cu_client(monkeypatch, None)
    with pytest.raises(ShadowPersistError):
        persist_rows(_randuri_de_test(10))


def test_T5c_lista_goala_ramane_un_zero_legitim(monkeypatch):
    from value_selector_shadow import persist_rows

    _cu_client(monkeypatch, _ClientFals())
    assert persist_rows([]) == 0


def test_T6_dimensiunea_lotului_ramane_500():
    from value_selector_shadow import DIMENSIUNE_LOT

    assert DIMENSIUNE_LOT == 500


def test_T7_cheia_naturala_ramane_neschimbata(monkeypatch):
    from value_selector_shadow import CHEIE_NATURALA, persist_rows

    assert CHEIE_NATURALA == "run_id,policy_id,fixture_id,selection_code"
    client = _ClientFals()
    _cu_client(monkeypatch, client)
    persist_rows(_randuri_de_test(600))
    assert set(client.on_conflict) == {"run_id,policy_id,fixture_id,selection_code"}


def test_T8_nicio_operatie_distructiva_pentru_recuperare(monkeypatch):
    """Nici la succes, nici la esec nu se apeleaza delete/update, si nu exista
    DELETE/TRUNCATE in codul runner-ului."""
    from value_selector_shadow import ShadowPersistError, persist_rows

    client = _ClientFals()
    _cu_client(monkeypatch, client)
    persist_rows(_randuri_de_test(600))
    assert set(client.operatii) == {"upsert"}
    assert set(client.tabele) == {SHADOW_TABLE}

    client_esec = _ClientFals(esueaza_la=1)
    _cu_client(monkeypatch, client_esec)
    with pytest.raises(ShadowPersistError):
        persist_rows(_randuri_de_test(600))
    assert set(client_esec.operatii) == {"upsert"}

    apelate = _nume_apelate(RUNNER.read_text(encoding="utf-8"))
    assert not (apelate & {"delete", "truncate", "drop"})


def test_T9_rerularea_aceluiasi_run_id_ramane_idempotenta(monkeypatch):
    """Aceleasi randuri, scrise de doua ori: acelasi upsert, aceeasi cheie,
    nicio operatie de stergere intre ele."""
    from value_selector_shadow import persist_rows

    randuri = _randuri_de_test(300)
    client = _ClientFals()
    _cu_client(monkeypatch, client)
    assert persist_rows(randuri) == 300
    assert persist_rows(randuri) == 300
    assert client.loturi[0] == client.loturi[1]
    assert set(client.operatii) == {"upsert"}


def test_T10_runnerul_nu_atinge_niciun_modul_upstream():
    """Aceeasi garda ca la F1, reverificata dupa corectie."""
    arbore = ast.parse(RUNNER.read_text(encoding="utf-8"))
    module: set[str] = set()
    for nod in ast.walk(arbore):
        if isinstance(nod, ast.Import):
            module.update(a.name.split(".")[0] for a in nod.names)
        elif isinstance(nod, ast.ImportFrom) and nod.module:
            module.add(nod.module.split(".")[0])
    interzise = {"oracle_engine", "oracle_api", "feature_engine", "ml_predictor",
                 "recalibration", "shadow_testing", "supabase_client", "app"}
    assert not (module & interzise)


def test_docstringul_nu_mai_pretinde_atomicitate_la_nivel_de_rulare():
    """Formularea veche, `Upsert atomic pe cheia naturala`, putea fi citita ca
    atomicitate globala. Garda verifica textul, pentru ca aici exact textul e
    contractul care se comunica mai departe."""
    import inspect
    import value_selector_shadow as vss

    doc = inspect.getdoc(vss.persist_rows) or ""
    assert "Upsert atomic pe cheia naturala" not in doc
    assert "atomicitatea la nivel de RULARE nu e garantata" in doc.replace("\n", " ")
    assert "FAIL-FAST" in doc.upper()


# ── Fallback de cote (ADR-043) — 24 de meciuri recuperate ────────────────────

def _client_cu_fallback(monkeypatch, *, istoric, fallback, flag=True):
    """Client fals + flagul de fallback, fără rețea."""
    class _Q:
        def __init__(self, randuri): self._r = list(randuri)
        def select(self, *a, **k): return self
        def eq(self, c, v): self._r = [x for x in self._r if x.get(c) == v]; return self
        def in_(self, c, vals): self._r = [x for x in self._r if x.get(c) in set(vals)]; return self
        def order(self, *a, **k): return self
        def execute(self): return type("R", (), {"data": self._r})()

    class _C:
        def table(self, nume):
            return _Q(istoric if nume == "odds_history" else [])

    import database.queries as dq
    import flashscore_odds_fallback_config as cfg
    monkeypatch.setattr(dq, "get_client", lambda: _C())
    monkeypatch.setattr(cfg, "is_enabled", lambda: flag)
    monkeypatch.setattr(dq, "get_odds_fallback_for_missing_fixtures",
                        lambda ids: {k: v for k, v in fallback.items() if k in set(ids)})
    return _C()


def _rand_istoric(fid, **kw):
    baza = {"id": 1, "fixture_id": fid, "bookmaker": "Primar",
            "opening_home": 2.0, "opening_draw": 3.4, "opening_away": 3.8,
            "closing_home": None, "closing_draw": None, "closing_away": None}
    baza.update(kw)
    return baza


def test_meciul_fara_cote_primare_le_ia_din_fallback(monkeypatch):
    """Cazul HNL: 11 din 11 meciuri jucate aveau cote DOAR in fallback."""
    from value_selector_shadow import SURSA_FALLBACK, _load_odds

    c = _client_cu_fallback(
        monkeypatch, istoric=[],
        fallback={"hnl1": {"home": 1.8, "draw": 3.5, "away": 4.2, "bookmaker": "Flashscore"}})
    cote = _load_odds(c, ["hnl1"])
    assert cote["hnl1"]["home"] == 1.8
    assert cote["hnl1"]["bookmaker"] == "Flashscore"
    assert cote["hnl1"]["sursa"] == SURSA_FALLBACK


def test_sursa_primara_castiga_intotdeauna(monkeypatch):
    """Oglindeste productia: fallback-ul umple goluri, nu inlocuieste."""
    from value_selector_shadow import SURSA_PRIMARA, _load_odds

    c = _client_cu_fallback(
        monkeypatch, istoric=[_rand_istoric("fx1")],
        fallback={"fx1": {"home": 9.9, "draw": 9.9, "away": 9.9, "bookmaker": "Flashscore"}})
    cote = _load_odds(c, ["fx1"])
    assert cote["fx1"]["home"] == 2.0
    assert cote["fx1"]["sursa"] == SURSA_PRIMARA


def test_flagul_stins_inseamna_fara_fallback(monkeypatch):
    """Acelasi flag guverneaza productia si experimentul — daca productia il
    stinge, experimentul se stinge odata cu ea, nu diverg tacit."""
    from value_selector_shadow import _load_odds

    c = _client_cu_fallback(
        monkeypatch, istoric=[], flag=False,
        fallback={"hnl1": {"home": 1.8, "draw": 3.5, "away": 4.2, "bookmaker": "F"}})
    assert _load_odds(c, ["hnl1"]) == {}


def test_fallback_incomplet_nu_produce_cote_partiale(monkeypatch):
    from value_selector_shadow import _load_odds

    c = _client_cu_fallback(
        monkeypatch, istoric=[],
        fallback={"x": {"home": 1.8, "draw": None, "away": 4.2, "bookmaker": "F"}})
    assert _load_odds(c, ["x"]) == {}


def test_fallback_interogat_DOAR_pentru_meciurile_lipsa(monkeypatch):
    """Nu se cere din fallback ce avem deja — cerere inutilă la baza de date."""
    from value_selector_shadow import _load_odds

    cerute: list[list[str]] = []

    class _Q:
        def __init__(self, r): self._r = list(r)
        def select(self, *a, **k): return self
        def eq(self, c, v): return self
        def in_(self, c, vals): self._r = [x for x in self._r if x.get(c) in set(vals)]; return self
        def order(self, *a, **k): return self
        def execute(self): return type("R", (), {"data": self._r})()

    class _C:
        def table(self, nume):
            return _Q([_rand_istoric("are")] if nume == "odds_history" else [])

    import database.queries as dq
    import flashscore_odds_fallback_config as cfg
    monkeypatch.setattr(dq, "get_client", lambda: _C())
    monkeypatch.setattr(cfg, "is_enabled", lambda: True)

    def spion(ids):
        cerute.append(list(ids))
        return {}

    monkeypatch.setattr(dq, "get_odds_fallback_for_missing_fixtures", spion)
    _load_odds(_C(), ["are", "nu_are"])
    assert cerute == [["nu_are"]]


def test_eroarea_de_fallback_nu_arunca(monkeypatch):
    from value_selector_shadow import _load_odds

    class _C:
        def table(self, nume):
            class _Q:
                def select(s, *a, **k): return s
                def eq(s, *a, **k): return s
                def in_(s, *a, **k): return s
                def order(s, *a, **k): return s
                def execute(s): return type("R", (), {"data": []})()
            return _Q()

    import database.queries as dq
    import flashscore_odds_fallback_config as cfg
    monkeypatch.setattr(dq, "get_client", lambda: _C())
    monkeypatch.setattr(cfg, "is_enabled", lambda: True)

    def explodeaza(ids):
        raise RuntimeError("Supabase indisponibil")

    monkeypatch.setattr(dq, "get_odds_fallback_for_missing_fixtures", explodeaza)
    assert _load_odds(_C(), ["x"]) == {}
