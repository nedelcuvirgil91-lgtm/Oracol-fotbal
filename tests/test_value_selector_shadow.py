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
