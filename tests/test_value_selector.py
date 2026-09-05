"""
Teste pentru Value Selector V1 (ADR-071) — T1..T10, T14, T15 din lista
aprobata de proprietarul produsului, plus invarianti de echivalenta si
determinism.

Cifrele folosite in fixture-uri NU sunt inventate: provin din masuratori reale
pe setul curat de 364 de meciuri (predictie dovedit anterioara loviturii de
start + cote de deschidere capturate inainte de start). Fiecare fixture care
reproduce un caz din productie e adnotat cu sursa lui.

Fara retea, fara Supabase, fara ceas de sistem.
"""
from __future__ import annotations

import pytest

from value_selector import (
    Category,
    GateId,
    LEGACY_POLICY,
    RANKERS,
    RejectionReason,
    SelectionCandidate,
    SelectorPolicy,
    Verdict,
    classify,
    compute_metrics,
    explain,
    select,
    select_by_day,
    shrink_probability,
    to_shadow_rows,
)


# ── Fabrici de fixture-uri ───────────────────────────────────────────────────

def make_candidate(
    *,
    fixture_id: str = "fx-1",
    selection_code: str = "1",
    model_p: float = 0.50,
    fair_p: float = 0.40,
    bk_odds: float = 2.50,
    kickoff_utc: str = "2026-09-04T19:00:00Z",
    data_quality: str | None = "live/live",
    data_quality_is_sufficient: bool | None = True,
    matches_analysed: int | None = 5,
    prediction_age_s: float | None = 3600.0,
    odds_age_s: float | None = None,
    seconds_to_kickoff: float | None = 7200.0,
    match_label: str = "Echipa A - Echipa B",
    league: str = "Test League",
) -> SelectionCandidate:
    return SelectionCandidate(
        fixture_id=fixture_id,
        match_label=match_label,
        league=league,
        kickoff_utc=kickoff_utc,
        market="1X2",
        selection_code=selection_code,
        selection_label=f"selectie-{selection_code}",
        model_p=model_p,
        fair_p=fair_p,
        bk_odds=bk_odds,
        bookmaker="test-bk",
        data_quality=data_quality,
        data_quality_is_sufficient=data_quality_is_sufficient,
        matches_analysed=matches_analysed,
        prediction_age_s=prediction_age_s,
        odds_age_s=odds_age_s,
        seconds_to_kickoff=seconds_to_kickoff,
    )


def make_match(fixture_id: str, outcomes: list[tuple[str, float, float, float]],
               **kwargs) -> list[SelectionCandidate]:
    """`outcomes`: [(cod, model_p, fair_p, cota), ...] — toate cele trei
    rezultate ale unui meci, ca rangul in meci sa fie calculabil."""
    return [
        make_candidate(fixture_id=fixture_id, selection_code=code, model_p=p,
                       fair_p=f, bk_odds=o, **kwargs)
        for code, p, f, o in outcomes
    ]


# Politica de radar folosita in majoritatea testelor. Pragurile sunt
# EXPERIMENTALE (ADR-071 §15), aici doar ca sa exercite portile.
RADAR = SelectorPolicy(
    profile="test_radar",
    ranker_id="probability_first",
    shrinkage_w=0.5,
    require_rank_one=True,
    market_plausibility_floor=0.25,
    min_abs_edge_pp=3.0,
    require_sufficient_data_quality=True,
    require_positive_value=True,
    legacy_relative_edge_floor_pct=None,
    top_n_matches=5,
    one_selection_per_match=True,
)


# ── T1 — simetrie H/X/A ──────────────────────────────────────────────────────

def test_T1_selectiile_identice_ca_numere_sunt_tratate_identic_indiferent_de_tip():
    """Trei selectii cu aceleasi numere, diferind DOAR prin codul de selectie,
    trebuie sa primeasca aceleasi verdicte de poarta si aceeasi categorie."""
    candidates = [
        make_candidate(fixture_id=f"fx-{code}", selection_code=code,
                       model_p=0.55, fair_p=0.42, bk_odds=2.30)
        for code in ("1", "X", "2")
    ]
    result = select(candidates, RADAR)

    assert len(result.top) == 3
    categories = {c.candidate.selection_code: c.category for c in result.top}
    assert categories == {"1": Category.TOP, "X": Category.TOP, "2": Category.TOP}

    scores = {c.candidate.selection_code: c.score for c in result.top}
    assert scores["1"] == scores["X"] == scores["2"]


def test_T1b_un_egal_cu_probabilitate_mai_mare_bate_o_gazda_cu_probabilitate_mai_mica():
    """Simetria nu inseamna cota egala de rezultate, inseamna aceeasi regula.
    Un X la 37% cu valoare buna trebuie sa treaca inaintea unui 1 la 33%."""
    egal = make_match("fx-egal", [("1", 0.31, 0.30, 3.20), ("X", 0.37, 0.28, 3.40),
                                  ("2", 0.32, 0.42, 2.30)])
    gazda = make_match("fx-gazda", [("1", 0.33, 0.29, 3.30), ("X", 0.30, 0.30, 3.20),
                                    ("2", 0.31, 0.41, 2.35)])
    result = select(egal + gazda, RADAR)

    assert [c.candidate.selection_code for c in result.top] == ["X", "1"]
    assert result.top[0].candidate.fixture_id == "fx-egal"


def test_T13_niciun_verdict_nu_depinde_de_codul_selectiei():
    """Acelasi candidat, rebotezat pe rand 1/X/2 — verdictele portilor trebuie
    sa fie identice, poarta cu poarta."""
    verdicts = []
    for code in ("1", "X", "2"):
        candidate = make_candidate(selection_code=code, model_p=0.20, fair_p=0.30,
                                   bk_odds=3.00)
        result = select([candidate], RADAR)
        item = (result.top + result.longshot + result.rejected)[0]
        verdicts.append(tuple((g.gate_id, g.verdict) for g in item.gates))
    assert verdicts[0] == verdicts[1] == verdicts[2]


# ── T2 — permutare gazda ↔ oaspete ───────────────────────────────────────────

def test_T2_permutarea_gazda_oaspete_permuta_identic_iesirea():
    original = make_match("fx-1", [("1", 0.58, 0.44, 2.20), ("X", 0.22, 0.26, 3.60),
                                   ("2", 0.20, 0.30, 3.10)])
    oglindit = make_match("fx-1", [("2", 0.58, 0.44, 2.20), ("X", 0.22, 0.26, 3.60),
                                   ("1", 0.20, 0.30, 3.10)])

    r1 = select(original, RADAR)
    r2 = select(oglindit, RADAR)

    assert len(r1.top) == len(r2.top) == 1
    assert r1.top[0].candidate.selection_code == "1"
    assert r2.top[0].candidate.selection_code == "2"
    assert r1.top[0].score == pytest.approx(r2.top[0].score)
    assert r1.top[0].metrics.e_abs_pp == pytest.approx(r2.top[0].metrics.e_abs_pp)


# ── T3 / T4 / T5 — o selectie per meci, plafon de meciuri, fara completare ───

def test_T3_maximum_o_selectie_per_meci_in_top():
    """Deduplicarea pe meci se testeaza cu poarta de rang OPRITA — altfel n-ar
    fi exercitata niciodata: cu rangul cerut, un singur rezultat per meci poate
    trece oricum. Regula trebuie sa tina si fara acea plasa de siguranta."""
    fara_rang = SelectorPolicy(
        profile="fara_rang", ranker_id="probability_first", shrinkage_w=0.5,
        require_rank_one=False, market_plausibility_floor=0.25, min_abs_edge_pp=3.0,
        require_sufficient_data_quality=True, require_positive_value=True,
        legacy_relative_edge_floor_pct=None, top_n_matches=5,
        one_selection_per_match=True,
    )
    candidates = make_match("fx-1", [("1", 0.46, 0.34, 2.90), ("X", 0.44, 0.33, 3.00),
                                     ("2", 0.10, 0.33, 3.00)])
    result = select(candidates, fara_rang)

    assert len(result.top) == 1
    assert result.top[0].candidate.selection_code == "1"
    demoted = [r for r in result.rejected
               if RejectionReason.OUTRANKED_SAME_MATCH in r.rejection_reasons]
    assert len(demoted) == 1
    assert demoted[0].candidate.selection_code == "X"


def test_T3b_poarta_de_rang_garanteaza_singura_o_selectie_per_meci():
    """Sub politica radarului, deduplicarea e redundanta — dar invariantul
    trebuie sa tina, ca o schimbare viitoare de politica sa nu-l rupa tacit."""
    candidates = make_match("fx-1", [("1", 0.46, 0.34, 2.90), ("X", 0.44, 0.33, 3.00),
                                     ("2", 0.10, 0.33, 3.00)])
    result = select(candidates, RADAR)
    assert len(result.top) == 1
    assert len({c.candidate.fixture_id for c in result.top}) == len(result.top)


def test_T4_maximum_cinci_meciuri_pe_zi():
    candidates: list[SelectionCandidate] = []
    for i in range(8):
        candidates += make_match(f"fx-{i}", [("1", 0.60 - i * 0.01, 0.40, 2.40),
                                             ("X", 0.20, 0.28, 3.40),
                                             ("2", 0.20, 0.32, 3.10)])
    result = select(candidates, RADAR)

    assert len(result.top) == 5
    assert len({c.candidate.fixture_id for c in result.top}) == 5
    assert sum(1 for r in result.rejected
               if RejectionReason.OUTRANKED_TOP_N in r.rejection_reasons) == 3


def test_T5_fara_completare_artificiala_cand_sunt_mai_putine_de_cinci():
    bune = make_match("fx-bun", [("1", 0.58, 0.44, 2.20), ("X", 0.21, 0.26, 3.60),
                                 ("2", 0.21, 0.30, 3.10)])
    slabe = make_match("fx-slab", [("1", 0.20, 0.34, 2.90), ("X", 0.30, 0.33, 3.00),
                                   ("2", 0.50, 0.33, 3.00)],
                       data_quality="neutral/neutral", data_quality_is_sufficient=False)
    result = select(bune + slabe, RADAR)

    assert len(result.top) == 1
    assert result.top[0].candidate.fixture_id == "fx-bun"


def test_T5b_zero_selectii_bune_produce_top_gol_fara_exceptie():
    slabe = make_match("fx-slab", [("1", 0.20, 0.34, 2.90), ("X", 0.30, 0.33, 3.00),
                                   ("2", 0.50, 0.33, 3.00)],
                       data_quality="neutral/neutral", data_quality_is_sufficient=False)
    result = select(slabe, RADAR)
    assert result.top == ()
    assert result.stats.n_top == 0


def test_lista_goala_de_intrare_nu_arunca():
    result = select([], RADAR)
    assert result.top == () and result.longshot == () and result.rejected == ()
    assert result.stats.n_input == 0


# ── T6 / T14 — date neutre: respinse, niciodata Longshot ─────────────────────

def test_T6_datele_neutre_nu_pot_intra_in_top():
    """Reproduce constanta de fallback masurata in productie: 34.1 / 37.0 / 28.9,
    identica pentru 25 de meciuri diferite de Europa League."""
    candidates = make_match("fx-el", [("1", 0.341, 0.28, 3.30), ("X", 0.370, 0.21, 4.40),
                                      ("2", 0.289, 0.48, 2.05)],
                            data_quality="neutral/neutral", data_quality_is_sufficient=False)
    result = select(candidates, RADAR)

    assert result.top == ()
    assert all(c.category is not Category.TOP for c in result.longshot + result.rejected)


def test_T14_fallback_neutral_ajunge_in_respinse_nu_in_longshot():
    """Chiar si atunci cand candidatul cade SI pe o poarta de tip longshot
    (rang in meci), calitatea insuficienta il trimite la Respinse."""
    candidates = make_match("fx-el", [("1", 0.341, 0.28, 3.30), ("X", 0.370, 0.21, 4.40),
                                      ("2", 0.289, 0.48, 2.05)],
                            data_quality="neutral/neutral", data_quality_is_sufficient=False)
    result = select(candidates, RADAR)

    assert result.longshot == ()
    reasons = {r for c in result.rejected for r in c.rejection_reasons}
    assert RejectionReason.DATA_QUALITY_INSUFFICIENT in reasons


def test_longshot_inseamna_valoare_reala_cu_probabilitate_mica_nu_date_proaste():
    """Date bune + valoare reala + rang 2 => LONGSHOT, nu REJECTED."""
    candidates = make_match("fx-1", [("1", 0.30, 0.18, 5.20), ("X", 0.25, 0.26, 3.60),
                                     ("2", 0.45, 0.56, 1.75)])
    result = select(candidates, RADAR)

    longshot_codes = {c.candidate.selection_code for c in result.longshot}
    assert "1" in longshot_codes
    item = next(c for c in result.longshot if c.candidate.selection_code == "1")
    assert set(item.rejection_reasons) <= {
        RejectionReason.NOT_MODEL_LEADER,
        RejectionReason.MARKET_IMPLAUSIBLE,
        RejectionReason.BELOW_PROBABILITY_FLOOR,
        RejectionReason.ABOVE_ODDS_CEILING,
    }


# ── T7 — rangul in meci elimina cazurile reale din captura ───────────────────

@pytest.mark.parametrize("nume, outcomes, cod_problema", [
    # Lommel SK - Club Brugge, 2026-09-04. Recomandat "1" cu edge relativ +166%.
    ("Lommel SK - Club Brugge",
     [("1", 0.2416, 0.091, 10.67), ("X", 0.2440, 0.150, 6.44), ("2", 0.5144, 0.758, 1.28)],
     "1"),
    # Paris Saint-Germain - Monaco, 2026-09-04. Recomandat "2" cu +136%.
    ("Paris Saint-Germain - Monaco",
     [("1", 0.4992, 0.700, 1.36), ("X", 0.2109, 0.176, 5.56), ("2", 0.2895, 0.123, 7.97)],
     "2"),
    # Lyon - AJ Auxerre, 2026-09-04. Recomandat "2" cu +95%. Real: a castigat gazda.
    ("Lyon - AJ Auxerre",
     [("1", 0.5245, 0.640, 1.49), ("X", 0.1903, 0.213, 4.47), ("2", 0.2840, 0.145, 6.77)],
     "2"),
])
def test_T7_rangul_in_meci_elimina_selectiile_gresite_din_captura(nume, outcomes, cod_problema):
    result = select(make_match("fx", outcomes, match_label=nume), RADAR)
    assert cod_problema not in {c.candidate.selection_code for c in result.top}

    item = next(c for c in result.longshot + result.rejected
                if c.candidate.selection_code == cod_problema)
    assert RejectionReason.NOT_MODEL_LEADER in item.rejection_reasons


def test_T7b_rangul_in_meci_NU_e_suficient_singur():
    """Ipswich Town - Liverpool, 2026-09-04: modelul da 59,2% gazdei, piata
    16,8%. Trece rangul in meci — deci plauzibilitatea de piata e necesara."""
    outcomes = [("1", 0.5916, 0.168, 5.89), ("X", 0.1880, 0.222, 4.46),
                ("2", 0.2194, 0.610, 1.62)]
    doar_rang = SelectorPolicy(profile="doar_rang", ranker_id="probability_first",
                               require_rank_one=True, require_positive_value=True,
                               legacy_relative_edge_floor_pct=None)
    result = select(make_match("fx-ips", outcomes), doar_rang)
    assert {c.candidate.selection_code for c in result.top} == {"1"}


# ── T8 — plauzibilitatea de piata ────────────────────────────────────────────

@pytest.mark.parametrize("nume, outcomes", [
    # Frosinone - Juventus, 2026-08-23: model 61,9% vs piata 12,5%, cota 7,50.
    ("Frosinone - Juventus",
     [("1", 0.619, 0.125, 7.50), ("X", 0.201, 0.215, 4.35), ("2", 0.180, 0.660, 1.42)]),
    # Telstar 1963 - Ajax, 2026-08-30: model 44,1% vs piata 21,0%, cota 4,50.
    ("Telstar 1963 - Ajax",
     [("1", 0.441, 0.210, 4.50), ("X", 0.280, 0.240, 3.95), ("2", 0.279, 0.550, 1.72)]),
])
def test_T8_plauzibilitatea_de_piata_respinge_divergentele_extreme(nume, outcomes):
    result = select(make_match("fx", outcomes, match_label=nume), RADAR)
    assert result.top == ()
    item = next(c for c in result.longshot + result.rejected
                if c.candidate.selection_code == "1")
    assert RejectionReason.MARKET_IMPLAUSIBLE in item.rejection_reasons


def test_T8b_divergenta_moderata_ramane_admisa():
    """Genoa - Como, 2026-09-04: model 59,9% vs piata 53,5% — exact tipul de
    meci pe care radarul TREBUIE sa-l scoata."""
    outcomes = [("1", 0.144, 0.230, 4.20), ("X", 0.257, 0.235, 4.10),
                ("2", 0.599, 0.535, 1.84)]
    result = select(make_match("fx-gen", outcomes), RADAR)
    assert {c.candidate.selection_code for c in result.top} == {"2"}


def test_poarta_de_piata_e_simetrica_pe_tipuri_de_selectie():
    """Un X cu prob de piata 28% trece; un 1 cu prob de piata 12% cade.
    Diferenta vine din numar, nu din tipul selectiei."""
    egal_ok = make_match("fx-a", [("1", 0.30, 0.36, 2.70), ("X", 0.40, 0.28, 3.40),
                                  ("2", 0.30, 0.36, 2.70)])
    gazda_nu = make_match("fx-b", [("1", 0.55, 0.12, 7.80), ("X", 0.25, 0.24, 3.90),
                                   ("2", 0.20, 0.64, 1.46)])
    result = select(egal_ok + gazda_nu, RADAR)

    assert {(c.candidate.fixture_id, c.candidate.selection_code) for c in result.top} \
        == {("fx-a", "X")}


# ── T9 / T10 — edge relativ si EV nu pot domina ──────────────────────────────

def test_T9_edge_relativ_urias_nu_domina_ordonarea():
    """Un outsider cu edge relativ +214% nu poate sta peste o selectie
    plauzibila cu edge relativ mult mai mic."""
    outsider = make_match("fx-out", [("1", 0.308, 0.098, 9.90), ("X", 0.292, 0.252, 3.85),
                                     ("2", 0.400, 0.650, 1.50)])
    plauzibil = make_match("fx-ok", [("1", 0.560, 0.480, 2.05), ("X", 0.240, 0.260, 3.75),
                                     ("2", 0.200, 0.260, 3.70)])
    result = select(outsider + plauzibil, RADAR)

    assert [c.candidate.fixture_id for c in result.top] == ["fx-ok"]
    outsider_metrics = compute_metrics(outsider[0], w=1.0, rank_in_match=2)
    assert outsider_metrics.e_rel_pct > 200.0  # edge-ul relativ chiar e urias


def test_T10_EV_mare_nu_promoveaza_automat_un_outsider_extrem():
    """Frosinone-Juventus are EV brut foarte mare (0,619 × 7,50 − 1 = +3,64) si
    totusi nu are voie in Top sub politica radarului."""
    outcomes = [("1", 0.619, 0.125, 7.50), ("X", 0.201, 0.215, 4.35),
                ("2", 0.180, 0.660, 1.42)]
    candidates = make_match("fx-fro", outcomes)
    metrics = compute_metrics(candidates[0], w=1.0, rank_in_match=1)
    assert metrics.ev_raw > 3.0

    result = select(candidates, RADAR)
    assert result.top == ()


def test_T10b_rankerul_pe_EV_ramane_disponibil_ca_experiment():
    """Ranker-ul pe EV exista pentru F2 — dar portile raman cele care decid."""
    assert "shrunk_ev" in RANKERS
    politica_ev = SelectorPolicy(profile="ev", ranker_id="shrunk_ev", shrinkage_w=0.5,
                                 require_rank_one=True, market_plausibility_floor=0.25,
                                 require_positive_value=True,
                                 legacy_relative_edge_floor_pct=None)
    outcomes = [("1", 0.619, 0.125, 7.50), ("X", 0.201, 0.215, 4.35),
                ("2", 0.180, 0.660, 1.42)]
    assert select(make_match("fx-fro", outcomes), politica_ev).top == ()


# ── T15 — orice decizie e explicabila ────────────────────────────────────────

def test_T15_orice_candidat_are_categorie_unica_si_motive_daca_nu_e_top():
    candidates = (
        make_match("fx-1", [("1", 0.58, 0.44, 2.20), ("X", 0.21, 0.26, 3.60),
                            ("2", 0.21, 0.30, 3.10)])
        + make_match("fx-2", [("1", 0.30, 0.18, 5.20), ("X", 0.25, 0.26, 3.60),
                              ("2", 0.45, 0.56, 1.75)])
        + make_match("fx-3", [("1", 0.341, 0.28, 3.30), ("X", 0.370, 0.21, 4.40),
                              ("2", 0.289, 0.48, 2.05)],
                     data_quality="neutral/neutral", data_quality_is_sufficient=False)
    )
    result = select(candidates, RADAR)
    toate = list(result.top) + list(result.longshot) + list(result.rejected)

    assert len(toate) == len(candidates)
    for item in toate:
        assert {g.gate_id for g in item.gates} == set(GateId)
        if item.category is Category.TOP:
            assert item.rejection_reasons == ()
            assert item.rank_in_day is not None
        else:
            assert item.rejection_reasons, f"{item.candidate.selection_code} fara motiv"
        assert explain(item)


def test_portile_se_evalueaza_toate_fara_scurtcircuit():
    """Un candidat care cade la prima poarta trebuie sa aiba totusi verdicte
    pentru toate portile — altfel diagnosticul din F2 ar fi incomplet."""
    candidate = make_candidate(bk_odds=1.0, model_p=0.10, fair_p=0.60)
    item = select([candidate], RADAR).rejected[0]
    assert len(item.gates) == len(GateId)
    assert {g.gate_id for g in item.gates if g.verdict is Verdict.FAIL} >= {GateId.ODDS_PRESENT}


# ── Necunoscut ramane necunoscut ─────────────────────────────────────────────

def test_o_poarta_fara_informatie_da_UNKNOWN_si_nu_respinge():
    """Prospetimea cotei e necunoscuta in V1 (timestamp nepropagat).
    Candidatul NU trebuie respins din acest motiv, dar trebuie contorizat."""
    politica = SelectorPolicy(profile="t", ranker_id="probability_first",
                              max_odds_age_s=3600.0, legacy_relative_edge_floor_pct=None)
    result = select([make_candidate(odds_age_s=None)], politica)

    assert len(result.top) == 1
    gate = next(g for g in result.top[0].gates if g.gate_id is GateId.ODDS_FRESH)
    assert gate.verdict is Verdict.UNKNOWN
    assert result.stats.gates_unknown[GateId.ODDS_FRESH.value] == 1


def test_o_poarta_neconfigurata_da_NOT_APPLICABLE_nu_PASS():
    result = select([make_candidate()], SelectorPolicy(ranker_id="probability_first",
                                                       legacy_relative_edge_floor_pct=None))
    verdicts = {g.gate_id: g.verdict for g in result.top[0].gates}
    assert verdicts[GateId.MARKET_PLAUSIBILITY] is Verdict.NOT_APPLICABLE
    assert verdicts[GateId.PROBABILITY_FLOOR] is Verdict.NOT_APPLICABLE


# ── Shrinkage ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("w", [1.00, 0.75, 0.50, 0.25, 0.00])
def test_familia_de_shrinkage_e_o_interpolare_liniara(w):
    p, f = 0.60, 0.40
    assert shrink_probability(p, f, w) == pytest.approx(w * p + (1 - w) * f)


def test_w_unu_inseamna_modelul_iar_w_zero_inseamna_piata():
    assert shrink_probability(0.62, 0.31, 1.0) == pytest.approx(0.62)
    assert shrink_probability(0.62, 0.31, 0.0) == pytest.approx(0.31)


def test_w_in_afara_intervalului_e_respins():
    with pytest.raises(ValueError):
        shrink_probability(0.5, 0.4, 1.5)


def test_la_w_zero_EV_contractat_e_mereu_negativ_pe_o_piata_cu_marja():
    """Proprietate algebrica documentata deliberat: un control market-only NU
    poate folosi o poarta pe EV pozitiv — ar da mereu multimea vida."""
    odds = (2.10, 3.40, 3.60)
    implied = [1 / o for o in odds]
    total = sum(implied)
    assert total > 1.0
    for o, impl in zip(odds, implied):
        fair = impl / total
        assert fair * o - 1.0 < 0.0


# ── Versionarea politicii ────────────────────────────────────────────────────

def test_policy_id_se_schimba_la_orice_schimbare_de_prag():
    baza = RADAR.policy_id
    assert SelectorPolicy(**{**RADAR.__dict__, "market_plausibility_floor": 0.30}).policy_id != baza
    assert SelectorPolicy(**{**RADAR.__dict__, "shrinkage_w": 0.25}).policy_id != baza
    assert SelectorPolicy(**{**RADAR.__dict__, "top_n_matches": 3}).policy_id != baza
    assert SelectorPolicy(**{**RADAR.__dict__, "ranker_id": "shrunk_ev"}).policy_id != baza


def test_policy_id_e_stabil_pentru_aceeasi_politica():
    assert SelectorPolicy(**RADAR.__dict__).policy_id == RADAR.policy_id


def test_policy_id_contine_profilul_si_versiunea():
    assert RADAR.policy_id.startswith("test_radar@v1:")


# ── Determinism ──────────────────────────────────────────────────────────────

def test_doua_rulari_pe_aceleasi_intrari_dau_exact_aceeasi_lista():
    candidates = (make_match("fx-1", [("1", 0.55, 0.42, 2.30), ("X", 0.25, 0.28, 3.40),
                                      ("2", 0.20, 0.30, 3.20)])
                  + make_match("fx-2", [("1", 0.55, 0.42, 2.30), ("X", 0.25, 0.28, 3.40),
                                        ("2", 0.20, 0.30, 3.20)]))
    r1 = select(candidates, RADAR)
    r2 = select(candidates, RADAR)
    key = lambda r: [(c.candidate.fixture_id, c.candidate.selection_code, c.rank_in_day)
                     for c in r.top]
    assert key(r1) == key(r2)


def test_scoruri_egale_se_departajeaza_stabil():
    candidates = (make_match("fx-b", [("1", 0.55, 0.42, 2.30), ("X", 0.25, 0.28, 3.40),
                                      ("2", 0.20, 0.30, 3.20)])
                  + make_match("fx-a", [("1", 0.55, 0.42, 2.30), ("X", 0.25, 0.28, 3.40),
                                        ("2", 0.20, 0.30, 3.20)]))
    result = select(candidates, RADAR)
    assert [c.candidate.fixture_id for c in result.top] == ["fx-a", "fx-b"]


# ── Echivalenta cu comportamentul actual ─────────────────────────────────────

def test_politica_implicita_reproduce_regula_actuala_de_prag_si_ordonare():
    """Legacy: prag pe edge relativ >= 5%, ordonare descrescatoare dupa el,
    fara nicio alta poarta, fara deduplicare pe meci."""
    candidates = make_match("fx-1", [("1", 0.308, 0.098, 9.90), ("X", 0.292, 0.252, 3.85),
                                     ("2", 0.400, 0.650, 1.50)])
    result = select(candidates, LEGACY_POLICY)

    assert [c.candidate.selection_code for c in result.top] == ["1", "X"]
    assert result.top[0].metrics.e_rel_pct > result.top[1].metrics.e_rel_pct
    respins = next(c for c in result.rejected if c.candidate.selection_code == "2")
    assert RejectionReason.BELOW_LEGACY_RELATIVE_EDGE in respins.rejection_reasons


def test_politica_implicita_nu_deduplica_pe_meci():
    candidates = make_match("fx-1", [("1", 0.308, 0.098, 9.90), ("X", 0.292, 0.252, 3.85),
                                     ("2", 0.400, 0.650, 1.50)])
    assert len({c.candidate.fixture_id for c in select(candidates, LEGACY_POLICY).top}) == 1
    assert len(select(candidates, LEGACY_POLICY).top) == 2


# ── Grupare pe zi ────────────────────────────────────────────────────────────

def test_plafonul_de_meciuri_se_aplica_per_zi_nu_pe_tot_setul():
    candidates: list[SelectionCandidate] = []
    for zi in ("2026-09-04T19:00:00Z", "2026-09-05T19:00:00Z"):
        for i in range(7):
            candidates += make_match(f"fx-{zi[:10]}-{i}",
                                     [("1", 0.60 - i * 0.01, 0.40, 2.40),
                                      ("X", 0.20, 0.28, 3.40), ("2", 0.20, 0.32, 3.10)],
                                     kickoff_utc=zi)
    pe_zile = select_by_day(candidates, RADAR)

    assert set(pe_zile) == {"2026-09-04", "2026-09-05"}
    assert all(len(r.top) == 5 for r in pe_zile.values())


# ── Contract de shadow ───────────────────────────────────────────────────────

def test_payloadul_de_shadow_contine_toate_deciziile_si_campurile_cerute():
    candidates = (make_match("fx-1", [("1", 0.58, 0.44, 2.20), ("X", 0.21, 0.26, 3.60),
                                      ("2", 0.21, 0.30, 3.10)])
                  + make_match("fx-2", [("1", 0.30, 0.18, 5.20), ("X", 0.25, 0.26, 3.60),
                                        ("2", 0.45, 0.56, 1.75)]))
    result = select(candidates, RADAR)
    rows = to_shadow_rows(result, run_id="run-1", evaluated_at="2026-09-04T08:15:00Z",
                          policy=RADAR)

    assert len(rows) == len(candidates)
    obligatorii = {
        "run_id", "evaluated_at", "policy_id", "policy_profile", "ranker_id",
        "shrinkage_w", "fixture_id", "league", "kickoff_utc", "market",
        "selection_code", "model_p", "fair_p", "bk_odds", "e_abs_pp", "e_rel_pct",
        "p_shr", "ev_raw", "ev_shr", "rank_in_match", "actionability_score",
        "rank_in_day", "category", "rejection_reasons", "gate_results",
        "data_quality", "matches_analysed", "prediction_age_s", "odds_age_s",
        "leakage_suspect",
    }
    assert obligatorii <= set(rows[0])
    assert {r["category"] for r in rows} <= {"top", "longshot", "rejected"}
    assert all(set(r["gate_results"]) == {g.value for g in GateId} for r in rows)


def test_payloadul_marcheaza_scurgerea_temporala():
    dupa_start = make_candidate(seconds_to_kickoff=-60.0)
    rows = to_shadow_rows(select([dupa_start], RADAR), run_id="r", evaluated_at="t",
                          policy=RADAR)
    assert rows[0]["leakage_suspect"] is True

    necunoscut = make_candidate(seconds_to_kickoff=None)
    rows = to_shadow_rows(select([necunoscut], RADAR), run_id="r", evaluated_at="t",
                          policy=RADAR)
    assert rows[0]["leakage_suspect"] is None


def test_model_p_nu_e_modificat_de_selector():
    candidate = make_candidate(model_p=0.5916)
    result = select([candidate], RADAR)
    item = (result.top + result.longshot + result.rejected)[0]
    assert item.candidate.model_p == 0.5916
    assert item.metrics.p_shr != item.candidate.model_p  # contractia e separata


# ── Clasificare ──────────────────────────────────────────────────────────────

def test_clasificarea_e_top_doar_cand_nicio_poarta_nu_cade():
    from value_selector import GateResult
    gates = tuple(GateResult(g, Verdict.PASS) for g in GateId)
    assert classify(gates)[0] is Category.TOP


def test_o_singura_poarta_de_validitate_cazuta_trimite_la_respinse():
    from value_selector import GateResult
    gates = tuple(
        GateResult(g, Verdict.FAIL if g is GateId.ODDS_PRESENT else Verdict.PASS)
        for g in GateId
    )
    category, reasons = classify(gates)
    assert category is Category.REJECTED
    assert RejectionReason.ODDS_INVALID in reasons


# ── Adaptor MatchPrediction -> candidaturi ───────────────────────────────────

class _Profil:
    def __init__(self, data_quality: str | None, matches_analysed: int | None):
        self.data_quality = data_quality
        self.matches_analysed = matches_analysed


class _Predictie:
    """Dublura minimala de `MatchPrediction` — adaptorul citeste prin getattr,
    deci nu are nevoie de clasa reala (si nu are voie s-o importe)."""

    def __init__(self, **kwargs):
        self.fixture_id = "fx-1"
        self.home_team = "Echipa A"
        self.away_team = "Echipa B"
        self.league = "Test League"
        self.kickoff_utc = "2026-09-04T19:00:00Z"
        self.bookmaker_name = "test-bk"
        self.prob_home_win = 0.55
        self.prob_draw = 0.25
        self.prob_away_win = 0.20
        self.bk_home_odds = 2.10
        self.bk_draw_odds = 3.40
        self.bk_away_odds = 3.60
        self.fair_home_pct = 44.0
        self.fair_draw_pct = 27.0
        self.fair_away_pct = 29.0
        self.home_profile = _Profil("live", 5)
        self.away_profile = _Profil("live", 5)
        for cheie, valoare in kwargs.items():
            setattr(self, cheie, valoare)


def test_adaptorul_produce_exact_trei_candidaturi_pentru_1X2():
    from value_selector_adapter import candidates_from_prediction

    candidaturi = candidates_from_prediction(_Predictie(), prediction_age_s=120.0)
    assert [c.selection_code for c in candidaturi] == ["1", "X", "2"]
    assert all(c.market == "1X2" for c in candidaturi)
    assert candidaturi[0].model_p == 0.55
    assert candidaturi[0].fair_p == pytest.approx(0.44)
    assert all(c.prediction_age_s == 120.0 for c in candidaturi)


def test_adaptorul_nu_produce_candidaturi_partiale_cand_lipseste_o_cota():
    """Cu o cota lipsa, de-vig-ul celorlalte rezultate ar fi calculat pe o piata
    incompleta — deci gresit. Mai bine zero candidaturi decat trei gresite."""
    from value_selector_adapter import candidates_from_prediction

    assert candidates_from_prediction(_Predictie(bk_draw_odds=None)) == []
    assert candidates_from_prediction(_Predictie(fair_away_pct=None)) == []
    assert candidates_from_prediction(None) == []


def test_adaptorul_ia_cea_mai_slaba_calitate_dintre_cele_doua_echipe():
    from value_selector_adapter import candidates_from_prediction

    predictie = _Predictie(home_profile=_Profil("live", 6), away_profile=_Profil("neutral", 0))
    candidaturi = candidates_from_prediction(predictie)
    assert candidaturi[0].data_quality_is_sufficient is False
    assert candidaturi[0].matches_analysed == 0


def test_adaptorul_lasa_calitatea_necunoscuta_cand_lipseste_un_profil():
    from value_selector_adapter import candidates_from_prediction

    predictie = _Predictie(away_profile=None)
    candidaturi = candidates_from_prediction(predictie)
    assert candidaturi[0].data_quality_is_sufficient is None
    assert candidaturi[0].matches_analysed is None


def test_adaptorul_lasa_varsta_cotei_necunoscuta_in_V1():
    """Gol documentat (ADR-071 §16): timestamp-ul capturii cotei nu e propagat
    pana aici. Ramane `None` — necunoscut, niciodata aproximat."""
    from value_selector_adapter import candidates_from_prediction

    assert all(c.odds_age_s is None for c in candidates_from_prediction(_Predictie()))


# ── Porti configurabile, testate comportamental ──────────────────────────────
# (lacuna descoperita prin mutatie: portile de mai jos existau, dar niciun test
# nu verifica faptul ca RESPING efectiv ceva — o mutatie care le facea sa treaca
# mereu era prinsa doar de un test colateral.)

def test_pragul_de_probabilitate_respinge_efectiv_sub_prag():
    politica = SelectorPolicy(profile="t", ranker_id="probability_first",
                              probability_floor=0.50, legacy_relative_edge_floor_pct=None)
    sub = select([make_candidate(model_p=0.49, fair_p=0.40)], politica)
    peste = select([make_candidate(model_p=0.51, fair_p=0.40)], politica)

    assert sub.top == ()
    assert RejectionReason.BELOW_PROBABILITY_FLOOR in sub.longshot[0].rejection_reasons
    assert len(peste.top) == 1


def test_pragul_de_probabilitate_e_simetric_pe_tipuri_de_selectie():
    politica = SelectorPolicy(profile="t", ranker_id="probability_first",
                              probability_floor=0.40, legacy_relative_edge_floor_pct=None)
    for code in ("1", "X", "2"):
        sub = select([make_candidate(selection_code=code, model_p=0.39)], politica)
        peste = select([make_candidate(selection_code=code, model_p=0.41)], politica)
        assert sub.top == () and len(peste.top) == 1


def test_plafonul_de_cota_respinge_efectiv_peste_prag():
    politica = SelectorPolicy(profile="t", ranker_id="probability_first",
                              odds_ceiling=4.0, legacy_relative_edge_floor_pct=None)
    peste = select([make_candidate(bk_odds=4.50)], politica)
    sub = select([make_candidate(bk_odds=3.50)], politica)

    assert peste.top == ()
    assert RejectionReason.ABOVE_ODDS_CEILING in peste.longshot[0].rejection_reasons
    assert len(sub.top) == 1


def test_pragul_de_istoric_respinge_efectiv_si_trimite_la_respinse_nu_la_longshot():
    """Istoricul insuficient e o problema de informatie, nu de risc — deci
    REJECTED, exact ca `neutral` (ADR-071 §13)."""
    politica = SelectorPolicy(profile="t", ranker_id="probability_first",
                              min_matches_analysed=3, legacy_relative_edge_floor_pct=None)
    putin = select([make_candidate(matches_analysed=2)], politica)
    destul = select([make_candidate(matches_analysed=3)], politica)

    assert putin.top == () and putin.longshot == ()
    assert RejectionReason.INSUFFICIENT_HISTORY in putin.rejected[0].rejection_reasons
    assert len(destul.top) == 1


def test_pragul_de_valoare_absoluta_respinge_efectiv_sub_prag():
    politica = SelectorPolicy(profile="t", ranker_id="probability_first",
                              min_abs_edge_pp=5.0, legacy_relative_edge_floor_pct=None)
    sub = select([make_candidate(model_p=0.44, fair_p=0.40)], politica)
    peste = select([make_candidate(model_p=0.46, fair_p=0.40)], politica)

    assert sub.top == ()
    assert RejectionReason.BELOW_ABS_EDGE in sub.rejected[0].rejection_reasons
    assert len(peste.top) == 1


def test_valoarea_nepozitiva_e_respinsa_nu_tratata_ca_longshot():
    politica = SelectorPolicy(profile="t", ranker_id="probability_first",
                              require_positive_value=True,
                              legacy_relative_edge_floor_pct=None)
    result = select([make_candidate(model_p=0.30, fair_p=0.40)], politica)

    assert result.top == () and result.longshot == ()
    assert RejectionReason.NON_POSITIVE_VALUE in result.rejected[0].rejection_reasons


def test_piata_inchisa_respinge_candidatul():
    politica = SelectorPolicy(profile="t", ranker_id="probability_first",
                              legacy_relative_edge_floor_pct=None)
    result = select([make_candidate(seconds_to_kickoff=-1.0)], politica)

    assert result.top == ()
    assert RejectionReason.MARKET_CLOSED in result.rejected[0].rejection_reasons


def test_predictia_prea_veche_e_respinsa():
    politica = SelectorPolicy(profile="t", ranker_id="probability_first",
                              max_prediction_age_s=1800.0,
                              legacy_relative_edge_floor_pct=None)
    veche = select([make_candidate(prediction_age_s=3600.0)], politica)
    proaspata = select([make_candidate(prediction_age_s=600.0)], politica)

    assert veche.top == ()
    assert RejectionReason.PREDICTION_STALE in veche.rejected[0].rejection_reasons
    assert len(proaspata.top) == 1
