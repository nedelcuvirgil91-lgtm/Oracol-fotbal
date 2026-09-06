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
