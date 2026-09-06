"""
Teste pentru calea de RADAR din value_dashboard.py (ADR-071 §17).

Testul care contează cel mai mult nu e niciunul dintre cele despre radar, ci
`test_cu_flagul_stins_rezultatul_e_identic_cu_inainte`: cu flagul stins,
ecranul trebuie să arate exact ce arăta înainte de ADR-071, câmp cu câmp.
Restul verifică invariantul de produs — radar, nu robot de pariere.

Zero rețea, zero Supabase: flagul e injectat prin monkeypatch, politica e
injectată direct în `collect_radar_bets`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

import value_dashboard as vd
from value_dashboard import ValueBetRow, collect_radar_bets, collect_value_bets
from value_selector import LEGACY_POLICY
from value_selector_config import F2_PROFILES

RADAR = F2_PROFILES["shrunk_050"]


@dataclass
class _Profil:
    data_quality: str = "partial/live"
    matches_analysed: int = 10


@dataclass
class _Pred:
    """Câmpurile citite fie de calea moștenită, fie de adaptor."""
    fixture_id: str
    home_team: str
    away_team: str
    league: str = "Premier League"
    kickoff_utc: str = "2026-09-06T15:00:00"
    # 1X2 pentru adaptor
    prob_home_win: float | None = 0.60
    prob_draw: float | None = 0.22
    prob_away_win: float | None = 0.18
    bk_home_odds: float | None = 2.00
    bk_draw_odds: float | None = 3.60
    bk_away_odds: float | None = 4.50
    fair_home_pct: float | None = 48.0
    fair_draw_pct: float | None = 26.7
    fair_away_pct: float | None = 25.3
    bookmaker_name: str | None = "TestBook"
    home_profile: object = field(default_factory=_Profil)
    away_profile: object = field(default_factory=_Profil)
    # calea mostenita
    value_bets: list = field(default_factory=list)
    special_value_bets: list = field(default_factory=list)
    kelly_stakes: dict = field(default_factory=dict)


def _pred_castigator(fid: str, *, model_home=0.60, fair_home=48.0, cota=2.00,
                     zi="2026-09-06") -> _Pred:
    """Un meci în care gazda e clar liderul modelului și trece porțile."""
    return _Pred(
        fixture_id=fid, home_team=f"H{fid}", away_team=f"A{fid}",
        kickoff_utc=f"{zi}T15:00:00",
        prob_home_win=model_home, prob_draw=(1 - model_home) * 0.55,
        prob_away_win=(1 - model_home) * 0.45,
        bk_home_odds=cota, bk_draw_odds=3.60, bk_away_odds=4.50,
        fair_home_pct=fair_home, fair_draw_pct=(100 - fair_home) * 0.53,
        fair_away_pct=(100 - fair_home) * 0.47,
        value_bets=[{"market": "1X2", "selection": "Home Win", "edge_pct": 25.0,
                     "model_prob_pct": model_home * 100, "bk_odds": cota,
                     "rating": "🔥 HIGH"}],
        special_value_bets=[{"market": "Over 2.5", "edge_pct": 9.0,
                             "model_prob_pct": 61.0, "bk_odds": 1.8,
                             "rating": "✅ MEDIUM"}],
        kelly_stakes={"Home Win": 11.0},
    )


@pytest.fixture
def flag(monkeypatch):
    """Controlează `_radar_activ()` fără să atingă Supabase."""
    def seteaza(pornit: bool):
        monkeypatch.setattr(vd, "_radar_activ", lambda: pornit)
    return seteaza


# ── Invariantul cel mai important: flagul stins nu schimbă nimic ─────────────

def test_cu_flagul_stins_rezultatul_e_identic_cu_inainte(flag):
    """Comportamentul de dinaintea ADR-071, câmp cu câmp — nu doar „aceeași
    lungime". Dacă cineva strecoară radarul pe calea implicită, cade aici."""
    flag(False)
    predictii = [_pred_castigator("fx1"), _pred_castigator("fx2", model_home=0.70)]

    randuri = collect_value_bets(predictii)
    asteptat = vd._collect_legacy(predictii)

    assert randuri == asteptat
    # Piețele speciale sunt prezente, Kelly e completat — exact ca înainte.
    assert any(r.market == "Over 2.5" for r in randuri)
    assert any(r.kelly_stake == 11.0 for r in randuri)


def test_flagul_necitit_inseamna_stins(monkeypatch):
    """Un flag care nu poate fi citit NU activează niciodată nimic."""
    import value_selector_config as vsc

    def explodeaza():
        raise RuntimeError("Supabase indisponibil")

    monkeypatch.setattr(vsc, "is_enabled", explodeaza)
    assert vd._radar_activ() is False


# ── Radarul: cel mult 5 meciuri, unul per meci ───────────────────────────────

def test_radarul_limiteaza_la_cinci_meciuri_pe_zi():
    predictii = [_pred_castigator(f"fx{i}", model_home=0.55 + i * 0.02)
                 for i in range(12)]
    randuri = collect_radar_bets(predictii, RADAR)
    assert len(randuri) == 5


def test_radarul_da_o_singura_selectie_per_meci():
    predictii = [_pred_castigator(f"fx{i}") for i in range(3)]
    randuri = collect_radar_bets(predictii, RADAR)
    assert len({r.fixture_id for r in randuri}) == len(randuri)


def test_plafonul_e_pe_zi_nu_pe_tot_setul():
    azi = [_pred_castigator(f"a{i}", model_home=0.55 + i * 0.02, zi="2026-09-06")
           for i in range(8)]
    maine = [_pred_castigator(f"b{i}", model_home=0.55 + i * 0.02, zi="2026-09-07")
             for i in range(8)]
    randuri = collect_radar_bets(azi + maine, RADAR)
    assert len(randuri) == 10
    pe_zi = {}
    for r in randuri:
        pe_zi[r.kickoff_utc[:10]] = pe_zi.get(r.kickoff_utc[:10], 0) + 1
    assert pe_zi == {"2026-09-06": 5, "2026-09-07": 5}


def test_lista_goala_e_un_rezultat_valid_nu_completare_artificiala():
    """Zero meciuri care trec porțile => zero sugestii. Radarul nu umple
    lista ca să pară util (ADR-071 §9). Aici modelul e de acord cu piața pe
    toate cele trei rezultate, deci nu există nicio valoare de semnalat."""
    de_acord = _Pred(
        fixture_id="fx1", home_team="H", away_team="A",
        prob_home_win=0.480, prob_draw=0.267, prob_away_win=0.253,
        fair_home_pct=48.0, fair_draw_pct=26.7, fair_away_pct=25.3,
    )
    assert collect_radar_bets([de_acord], RADAR) == []


def test_egalul_poate_intra_in_radar_exact_ca_o_gazda():
    """Simetria H/X/A nu e declarativă: dacă egalul e rezultatul cel mai
    probabil al modelului și trece aceleași porți, intră ca oricare altul.
    Testul ăsta s-a născut dintr-o fixtură greșită care a selectat un egal
    fără să vreau — dovadă că simetria chiar funcționează."""
    egal_lider = _Pred(
        fixture_id="fx1", home_team="H", away_team="A",
        prob_home_win=0.28, prob_draw=0.42, prob_away_win=0.30,
        bk_home_odds=2.90, bk_draw_odds=3.00, bk_away_odds=2.90,
        fair_home_pct=32.0, fair_draw_pct=35.0, fair_away_pct=33.0,
    )
    (rand,) = collect_radar_bets([egal_lider], RADAR)
    assert rand.selection == "Draw"
    assert rand.rating == "+7.0 pp vs piață"


# ── Invariantul de produs: radar, nu robot de pariere ────────────────────────

def test_radarul_nu_produce_niciodata_marime_de_miza():
    """ADR-071 §17. Kelly e `None` chiar dacă predicția îl are calculat."""
    pred = _pred_castigator("fx1")
    assert pred.kelly_stakes["Home Win"] == 11.0
    (rand,) = collect_radar_bets([pred], RADAR)
    assert rand.kelly_stake is None


def test_radarul_nu_include_piete_speciale():
    """ADR-071 §12: în afara scopului V1. Cinci meciuri nu se diluează cu
    rânduri de Over/Under."""
    pred = _pred_castigator("fx1")
    assert pred.special_value_bets  # există în predicție
    randuri = collect_radar_bets([pred], RADAR)
    assert all(r.market == "1X2" for r in randuri)


def test_ordinea_e_cea_a_selectorului_nu_dupa_edge_relativ():
    """Mecanismul care scotea outsiderii deasupra nu se reintroduce prin
    sortarea finală (ADR-071 §2)."""
    # Outsider cu edge relativ urias, dar probabilitate mica; favorit cu edge
    # relativ mic, dar probabilitate mare.
    favorit = _pred_castigator("favorit", model_home=0.72, fair_home=60.0, cota=1.60)
    randuri = collect_radar_bets([favorit, _pred_castigator("normal")], RADAR)
    assert randuri[0].fixture_id == "favorit"
    assert randuri[0].edge_pct < randuri[1].edge_pct  # ordinea NU e dupa edge


def test_ratingul_arata_diferenta_absoluta_fata_de_piata():
    (rand,) = collect_radar_bets([_pred_castigator("fx1")], RADAR)
    assert rand.rating == "+12.0 pp vs piață"  # 60.0% model - 48.0% piata


def test_campurile_de_baza_vin_din_predictie_si_din_candidatura():
    (rand,) = collect_radar_bets([_pred_castigator("fx1")], RADAR)
    assert isinstance(rand, ValueBetRow)
    assert rand.fixture_id == "fx1"
    assert rand.home_team == "Hfx1" and rand.away_team == "Afx1"
    assert rand.league == "Premier League"
    assert rand.selection == "Home Win"
    assert rand.model_prob_pct == pytest.approx(60.0)
    assert rand.bk_odds == pytest.approx(2.00)


# ── Robustețe ────────────────────────────────────────────────────────────────

def test_predictiile_none_sunt_ignorate():
    randuri = collect_radar_bets([None, _pred_castigator("fx1"), None], RADAR)
    assert len(randuri) == 1


def test_meciul_cu_cote_incomplete_nu_produce_candidaturi_partiale():
    incomplet = _pred_castigator("fx1")
    incomplet.bk_draw_odds = None
    assert collect_radar_bets([incomplet], RADAR) == []


def test_intrare_goala():
    assert collect_radar_bets([], RADAR) == []


def test_radarul_cazut_revine_la_lista_clasica_nu_lasa_ecranul_gol(flag, monkeypatch):
    """Un radar care crapă nu are voie să golească ecranul."""
    flag(True)

    def explodeaza(*a, **k):
        raise RuntimeError("selector stricat")

    monkeypatch.setattr(vd, "collect_radar_bets", explodeaza)
    predictii = [_pred_castigator("fx1")]
    assert collect_value_bets(predictii) == vd._collect_legacy(predictii)


def test_cu_flagul_pornit_se_foloseste_radarul(flag, monkeypatch):
    flag(True)
    monkeypatch.setattr("value_selector_config.build_policy", lambda: RADAR)
    predictii = [_pred_castigator(f"fx{i}") for i in range(9)]
    randuri = collect_value_bets(predictii)
    assert len(randuri) == 5
    assert all(r.kelly_stake is None for r in randuri)
    assert all(r.market == "1X2" for r in randuri)


# ── Puritate: calculul nu citește configurația ───────────────────────────────

def test_collect_radar_bets_nu_citeste_configuratia(monkeypatch):
    """Politica e injectată. Dacă cineva o citește înăuntru, testul cade —
    funcția nu ar mai fi testabilă fără Supabase."""
    import value_selector_config as vsc

    def interzis(*a, **k):
        raise AssertionError("collect_radar_bets nu are voie sa citeasca configul")

    monkeypatch.setattr(vsc, "build_policy", interzis)
    monkeypatch.setattr(vsc, "is_enabled", interzis)
    monkeypatch.setattr(vsc, "is_shadow_logging_enabled", interzis)
    assert len(collect_radar_bets([_pred_castigator("fx1")], RADAR)) == 1


def test_politica_moștenită_prin_radar_reproduce_lipsa_plafonului():
    """Garda de injecție: cu `LEGACY_POLICY`, calea de radar nu mai plafonează
    la 5 — dovadă că plafonul vine din politică, nu e codat în modul."""
    predictii = [_pred_castigator(f"fx{i}", model_home=0.55 + i * 0.02)
                 for i in range(8)]
    assert len(collect_radar_bets(predictii, LEGACY_POLICY)) > 5


# ── radar_din_shadow: calea rapidă (ADR-071 §18) ─────────────────────────────

class _Q:
    def __init__(self, randuri, jurnal):
        self._r = list(randuri)
        self._j = jurnal

    def select(self, *a, **k): return self
    def eq(self, c, v):
        self._j.append(("eq", c, v)); self._r = [x for x in self._r if x.get(c) == v]; return self
    def gte(self, c, v):
        self._r = [x for x in self._r if str(x.get(c, "")) >= v]; return self
    def lt(self, c, v):
        self._r = [x for x in self._r if str(x.get(c, "")) < v]; return self
    def in_(self, c, vals):
        self._r = [x for x in self._r if x.get(c) in set(vals)]; return self
    def execute(self):
        return type("R", (), {"data": self._r})()


class _Cl:
    def __init__(self, tabele):
        self.tabele = tabele
        self.jurnal = []

    def table(self, nume):
        self.jurnal.append(("table", nume))
        return _Q(self.tabele.get(nume, []), self.jurnal)


def _rand_shadow(**kw):
    baza = {
        "run_id": "2026-09-06T09:40Z", "fixture_id": "fx1", "league": "Premier League",
        "kickoff_utc": "2026-09-06T15:00:00+00:00", "market": "1X2",
        "selection_code": "1", "model_probability": 0.65, "fair_probability": 0.55,
        "bk_odds": 1.71, "relative_edge_pct": 18.2, "absolute_edge_pp": 10.0,
        "actionability_score": 0.5, "policy_id": "shrunk_050@v1:32ccbf4a",
        "selected_top": True, "rejection_reasons": [],
    }
    baza.update(kw)
    return baza


@pytest.fixture
def shadow(monkeypatch):
    def instaleaza(randuri_shadow, meciuri=None, radar=True):
        client = _Cl({
            "value_selector_shadow": randuri_shadow,
            "match_history": meciuri if meciuri is not None else [
                {"fixture_id": "fx1", "home_team": "Arsenal", "away_team": "Chelsea"},
                {"fixture_id": "fx2", "home_team": "Beveren",
                 "away_team": "Oud-Heverlee Leuven"},
            ],
        })
        import database.queries as dq
        monkeypatch.setattr(dq, "get_client", lambda: client)
        monkeypatch.setattr(vd, "_radar_activ", lambda: radar)
        monkeypatch.setattr("value_selector_config.build_policy", lambda: RADAR)
        return client
    return instaleaza


def test_radarul_din_shadow_intoarce_randuri_si_ora_rularii(shadow):
    shadow([_rand_shadow()])
    radar = vd.radar_din_shadow("2026-09-06")
    assert radar.calculat_la == "2026-09-06T09:40Z"
    assert radar.total_meciuri == 1 and radar.pagina == 0 and radar.pagini == 1
    (r,) = radar.randuri
    assert r.home_team == "Arsenal" and r.away_team == "Chelsea"
    assert r.selection == "Home Win"
    assert r.bk_odds == 1.71
    assert r.rating == "+10.0 pp vs piață"
    assert r.kelly_stake is None


def test_echipele_vin_din_match_history_nu_din_despicarea_etichetei(shadow):
    """`match_label` nu se poate sparge: „Beveren - Oud-Heverlee Leuven" e un
    caz real din date, cu liniuță în numele echipei."""
    shadow([_rand_shadow(fixture_id="fx2")])
    radar = vd.radar_din_shadow("2026-09-06")
    assert radar.randuri[0].home_team == "Beveren"
    assert radar.randuri[0].away_team == "Oud-Heverlee Leuven"


def test_se_serveste_rularea_cea_mai_recenta(shadow):
    shadow([
        _rand_shadow(run_id="2026-09-05T15:52Z", bk_odds=9.99, rank_in_day=1),
        _rand_shadow(run_id="2026-09-06T09:40Z", bk_odds=1.71, rank_in_day=1),
    ])
    radar = vd.radar_din_shadow("2026-09-06")
    assert radar.calculat_la == "2026-09-06T09:40Z"
    assert len(radar.randuri) == 1 and radar.randuri[0].bk_odds == 1.71


def test_ordinea_reproduce_sortarea_selectorului(shadow):
    """Scor descrescator, apoi valoare absoluta, apoi identitate stabila —
    identic cu `value_selector._sort_key`. De aia pagina 2 inseamna cu adevarat
    „locurile 6-10", nu un alt set arbitrar."""
    shadow([
        _rand_shadow(fixture_id="fx2", actionability_score=0.10),
        _rand_shadow(fixture_id="fx1", actionability_score=0.90),
    ])
    radar = vd.radar_din_shadow("2026-09-06")
    assert [r.fixture_id for r in radar.randuri] == ["fx1", "fx2"]


def test_filtreaza_pe_politica_activa_si_pe_selectiile_de_top(shadow):
    client = shadow([_rand_shadow()])
    vd.radar_din_shadow("2026-09-06")
    assert ("eq", "policy_id", RADAR.policy_id) in client.jurnal


def test_alta_zi_nu_intoarce_nimic(shadow):
    shadow([_rand_shadow()])
    assert vd.radar_din_shadow("2026-09-07") is None


def test_radar_inactiv_nu_citeste_nimic(shadow):
    client = shadow([_rand_shadow()], radar=False)
    assert vd.radar_din_shadow("2026-09-06") is None
    assert client.jurnal == []


def test_fara_randuri_cade_pe_calculul_live(shadow):
    shadow([])
    assert vd.radar_din_shadow("2026-09-06") is None


def test_fara_client_supabase_cade_pe_calculul_live(monkeypatch):
    import database.queries as dq
    monkeypatch.setattr(dq, "get_client", lambda: None)
    monkeypatch.setattr(vd, "_radar_activ", lambda: True)
    assert vd.radar_din_shadow("2026-09-06") is None


def test_o_eroare_de_citire_nu_arunca_ci_cade_pe_calculul_live(monkeypatch):
    """Un ecran lent e mai bun decât un ecran căzut."""
    import database.queries as dq

    def explodeaza():
        raise RuntimeError("Supabase indisponibil")

    monkeypatch.setattr(dq, "get_client", explodeaza)
    monkeypatch.setattr(vd, "_radar_activ", lambda: True)
    assert vd.radar_din_shadow("2026-09-06") is None


def test_meciul_fara_rand_in_match_history_ramane_fara_echipe_nu_arunca(shadow):
    shadow([_rand_shadow(fixture_id="necunoscut")], meciuri=[])
    radar = vd.radar_din_shadow("2026-09-06")
    assert len(radar.randuri) == 1
    assert radar.randuri[0].home_team == "" and radar.randuri[0].away_team == ""


def test_radar_din_shadow_nu_scrie_nimic():
    """Garda: doar SELECT-uri, niciun insert/upsert/update/delete."""
    import ast
    from pathlib import Path

    sursa = (Path(__file__).resolve().parent.parent / "value_dashboard.py")
    arbore = ast.parse(sursa.read_text(encoding="utf-8"))
    for nod in ast.walk(arbore):
        if isinstance(nod, (ast.Module, ast.ClassDef, ast.FunctionDef)):
            if (nod.body and isinstance(nod.body[0], ast.Expr)
                    and isinstance(nod.body[0].value, ast.Constant)
                    and isinstance(nod.body[0].value.value, str)):
                nod.body.pop(0)
    cod = ast.unparse(arbore)
    for metoda in ("insert", "upsert", "update", "delete", "rpc"):
        assert f".{metoda}(" not in cod


# ── Ora afișată (raportat ca „oră de începere greșită") ──────────────────────

def test_ora_se_converteste_in_fusul_romaniei():
    """Cazul real raportat: Telstar - Cambuur, 12:30 UTC = 15:30 ora României,
    exact ce arată și Flashscore. Datele erau corecte, afișarea nu."""
    assert vd.ora_locala("2026-09-06T12:30:00") == "15:30"
    assert vd.ora_locala("2026-09-06T15:30:00") == "18:30"   # Arsenal - Chelsea
    assert vd.ora_locala("2026-09-06T14:00:00") == "17:00"   # Kortrijk - Waregem


def test_marcajul_cu_fus_explicit_e_respectat_nu_reinterpretat():
    assert vd.ora_locala("2026-09-06T12:30:00+00:00") == "15:30"
    assert vd.ora_locala("2026-09-06T12:30:00Z") == "15:30"
    # Deja în ora României: nu se mai adaugă încă trei ore.
    assert vd.ora_locala("2026-09-06T15:30:00+03:00") == "15:30"


def test_ora_de_iarna_foloseste_decalajul_corect():
    """România e UTC+3 vara și UTC+2 iarna. Un decalaj fix ar greși jumătate
    de an — de aceea conversia e pe fus, nu pe o constantă."""
    assert vd.ora_locala("2026-01-15T12:30:00") == "14:30"
    assert vd.ora_locala("2026-07-15T12:30:00") == "15:30"


@pytest.mark.parametrize("intrare", ["", "   ", "TBA", "abc", "2026-09-06", None])
def test_ce_nu_se_poate_interpreta_ramane_TBA(intrare):
    """Regula #8: mai bine „nu știu" decât o oră inventată."""
    assert vd.ora_locala(intrare) == "TBA"


def test_fus_indisponibil_cade_pe_UTC_nu_pe_eroare():
    """Dacă baza de fusuri lipsește din imagine, ecranul arată ora UTC —
    corectă, doar altfel etichetată — în loc să cadă."""
    assert vd.ora_locala("2026-09-06T12:30:00", fus="Fus/Inexistent") == "12:30"


def test_fusul_de_afisare_e_declarat_explicit():
    assert vd.FUS_ORAR_AFISARE == "Europe/Bucharest"


def test_marcajul_naiv_e_tratat_ca_UTC_indiferent_de_fusul_masinii():
    """Gaură prinsă prin mutație: containerul rulează pe UTC, deci un test
    naiv nu distinge „naiv = UTC" de „naiv = ora sistemului". Aici fusul
    mașinii e forțat pe altceva, ca diferența să devină vizibilă."""
    import os
    import time as _time

    vechi = os.environ.get("TZ")
    try:
        os.environ["TZ"] = "America/New_York"   # UTC-4 vara
        _time.tzset()
        # Dacă marcajul naiv ar fi citit ca oră de New York, 12:30 ar deveni
        # 19:30 la București, nu 15:30.
        assert vd.ora_locala("2026-09-06T12:30:00") == "15:30"
    finally:
        if vechi is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = vechi
        _time.tzset()


@pytest.mark.parametrize("intrare", [
    "2026-13-45T99:99:99",     # dată imposibilă, lungime suficientă
    "nu-e-o-data-dar-e-lung",  # text lung, neinterpretabil
    "2026-09-06T12:30:0X",
])
def test_marcaj_lung_dar_invalid_ramane_TBA(intrare):
    """Ramura `except ValueError` — pe care testele anterioare nu o atingeau
    deloc, pentru că intrările lor scurte erau respinse mai devreme."""
    assert vd.ora_locala(intrare) == "TBA"


# ── Paginarea: „Încă 5 sugestii" ─────────────────────────────────────────────

def _pool(n: int, *, top: int = 5):
    """`n` meciuri calificate: primele `top` marcate `selected_top`, restul
    tăiate DOAR de plafon (`outranked_top_n`) — exact ce produce selectorul."""
    randuri = []
    for i in range(n):
        randuri.append(_rand_shadow(
            fixture_id=f"fx{i:02d}",
            actionability_score=1.0 - i * 0.01,
            selected_top=i < top,
            rejection_reasons=[] if i < top else ["outranked_top_n"],
        ))
    return randuri


def _echipe(n: int):
    return [{"fixture_id": f"fx{i:02d}", "home_team": f"H{i}", "away_team": f"A{i}"}
            for i in range(n)]


def test_pagina_0_da_primele_cinci(shadow):
    shadow(_pool(24), meciuri=_echipe(24))
    radar = vd.radar_din_shadow("2026-09-06", pagina=0)
    assert [r.fixture_id for r in radar.randuri] == ["fx00", "fx01", "fx02", "fx03", "fx04"]
    assert radar.total_meciuri == 24 and radar.pagini == 5 and radar.pagina == 0


def test_pagina_1_da_exact_locurile_6_10(shadow):
    shadow(_pool(24), meciuri=_echipe(24))
    radar = vd.radar_din_shadow("2026-09-06", pagina=1)
    assert [r.fixture_id for r in radar.randuri] == ["fx05", "fx06", "fx07", "fx08", "fx09"]
    assert radar.pagina == 1


def test_ultima_pagina_poate_fi_incompleta_nu_se_umple_artificial(shadow):
    shadow(_pool(24), meciuri=_echipe(24))
    radar = vd.radar_din_shadow("2026-09-06", pagina=4)
    assert len(radar.randuri) == 4          # 24 = 5+5+5+5+4
    assert [r.fixture_id for r in radar.randuri] == ["fx20", "fx21", "fx22", "fx23"]


def test_dupa_ultima_pagina_se_reia_de_la_capat(shadow):
    """Butonul nu se blochează: apăsat la nesfârșit, ciclează."""
    shadow(_pool(24), meciuri=_echipe(24))
    prima = vd.radar_din_shadow("2026-09-06", pagina=0)
    reluata = vd.radar_din_shadow("2026-09-06", pagina=5)
    assert reluata.pagina == 0
    assert [r.fixture_id for r in reluata.randuri] == [r.fixture_id for r in prima.randuri]


def test_paginarea_NU_coboara_stacheta(shadow):
    """Invariantul care contează. Meciurile respinse de porți NU apar pe
    nicio pagină, oricât ai apăsa — doar cele care au trecut tot și au fost
    tăiate de plafon."""
    calificate = _pool(7)
    respins = _rand_shadow(fixture_id="respins", actionability_score=99.0,
                           selected_top=False,
                           rejection_reasons=["not_model_leader", "market_implausible"])
    shadow(calificate + [respins],
           meciuri=_echipe(7) + [{"fixture_id": "respins", "home_team": "R",
                                  "away_team": "R2"}])
    vazute = set()
    for pagina in range(6):                      # mai multe cicluri complete
        radar = vd.radar_din_shadow("2026-09-06", pagina=pagina)
        vazute |= {r.fixture_id for r in radar.randuri}
    assert "respins" not in vazute
    assert radar.total_meciuri == 7


def test_un_meci_apare_o_singura_data_chiar_cu_doua_selectii_calificate(shadow):
    """Invariantul „o selecție per meci" (ADR-071 §9) se păstrează și la
    paginare: un meci cu două selecții calificate nu ocupă două locuri."""
    randuri = [
        _rand_shadow(fixture_id="fx00", selection_code="1", actionability_score=0.9,
                     selected_top=True, rejection_reasons=[]),
        _rand_shadow(fixture_id="fx00", selection_code="X", actionability_score=0.8,
                     selected_top=False, rejection_reasons=["outranked_top_n"]),
        _rand_shadow(fixture_id="fx01", selection_code="1", actionability_score=0.7,
                     selected_top=True, rejection_reasons=[]),
    ]
    shadow(randuri, meciuri=_echipe(2))
    radar = vd.radar_din_shadow("2026-09-06", pagina=0)
    assert radar.total_meciuri == 2
    assert [r.fixture_id for r in radar.randuri] == ["fx00", "fx01"]


def test_o_singura_pagina_cand_sunt_cel_mult_cinci_calificate(shadow):
    shadow(_pool(3, top=3), meciuri=_echipe(3))
    radar = vd.radar_din_shadow("2026-09-06", pagina=0)
    assert radar.pagini == 1 and radar.total_meciuri == 3
    assert vd.radar_din_shadow("2026-09-06", pagina=7).pagina == 0


def test_zi_fara_niciun_meci_calificat_cade_pe_calculul_live(shadow):
    """Rânduri există, dar toate respinse de porți: nu e nimic de semnalat,
    deci se cade pe calea veche în loc să se afișeze un tabel gol."""
    shadow([_rand_shadow(fixture_id="fx00", selected_top=False,
                         rejection_reasons=["not_model_leader"])])
    assert vd.radar_din_shadow("2026-09-06") is None


def test_marimea_paginii_e_parametru_nu_constanta(shadow):
    shadow(_pool(24), meciuri=_echipe(24))
    radar = vd.radar_din_shadow("2026-09-06", pagina=1, marime=3)
    assert len(radar.randuri) == 3
    assert [r.fixture_id for r in radar.randuri] == ["fx03", "fx04", "fx05"]
