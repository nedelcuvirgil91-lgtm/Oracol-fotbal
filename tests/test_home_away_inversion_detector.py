"""Teste pentru detectorul de inversări de teren (clasa 5, check_data_health).

CONTEXT: inversarea Rennes-PSG (2026-08-23) a ieșit la iveală DIN ÎNTÂMPLARE,
printr-o coliziune de `fixture_id`. O inversare la prima și singura extragere
nu declanșează nimic — și contaminează ELO, formă, H2H și atribuirea xG pe
părți. Detectorul folosește un semnal independent de numele echipelor:
stadionul.

Validat pe date reale înainte de a fi scris ca test: prinde 5 din 5 inversări
sintetice construite din rânduri reale, iar pe corpusul Flashscore de azi
(915 din 1.032 rânduri judecabile, 88,7%) găsește zero.

Fără rețea, fără Supabase — funcții pure.
"""
from __future__ import annotations

from scripts.check_data_health import build_home_stadiums, find_home_away_inversions


def _r(id_, home, away, stadium, league="L", zi="2026-08-01"):
    return {"id": id_, "home_team": home, "away_team": away, "stadium": stadium,
            "league": league, "kickoff_date": zi}


# ── build_home_stadiums ──────────────────────────────────────────────────────

def test_stadionul_de_acasa_e_cel_mai_frecvent():
    rows = [_r(1, "A", "X", "Arena A"), _r(2, "A", "Y", "Arena A"), _r(3, "A", "Z", "Neutru")]
    assert build_home_stadiums(rows)["A"] == "Arena A"


def test_o_singura_aparitie_nu_e_suficienta():
    """Pragul exista tocmai pentru ca o singura aparitie ar putea fi CHIAR
    randul inversat pe care incercam sa-l detectam."""
    assert build_home_stadiums([_r(1, "A", "X", "Arena A")]) == {}


# ── find_home_away_inversions ────────────────────────────────────────────────

def test_prinde_inversarea():
    rows = [
        _r(1, "Aberdeen", "X", "Pittodrie"), _r(2, "Aberdeen", "Y", "Pittodrie"),
        _r(3, "Rangers", "P", "Ibrox"), _r(4, "Rangers", "Q", "Ibrox"),
        _r(9, "Rangers", "Aberdeen", "Pittodrie"),  # inversat
    ]
    candidati, judecabile = find_home_away_inversions(rows)
    assert [c["id"] for c in candidati] == [9]
    assert judecabile > 0


def test_randurile_corecte_nu_sunt_semnalate():
    rows = [
        _r(1, "Aberdeen", "X", "Pittodrie"), _r(2, "Aberdeen", "Y", "Pittodrie"),
        _r(3, "Rangers", "P", "Ibrox"), _r(4, "Rangers", "Q", "Ibrox"),
        _r(9, "Aberdeen", "Rangers", "Pittodrie"),  # corect
    ]
    candidati, _ = find_home_away_inversions(rows)
    assert candidati == []


def test_stadion_partajat_nu_produce_fals_pozitiv():
    """GARDA CENTRALĂ. San Siro e „acasă" și pentru Milan, și pentru Inter.
    Fără această gardă, FIECARE derby ar fi raportat ca inversare."""
    rows = [
        _r(1, "Milan", "X", "San Siro"), _r(2, "Milan", "Y", "San Siro"),
        _r(3, "Inter", "P", "San Siro"), _r(4, "Inter", "Q", "San Siro"),
        _r(9, "Milan", "Inter", "San Siro"),
        _r(10, "Inter", "Milan", "San Siro"),
    ]
    candidati, _ = find_home_away_inversions(rows)
    assert candidati == [], f"derby raportat gresit ca inversare: {candidati}"


def test_oaspete_fara_stadion_cunoscut_nu_e_judecat():
    """Onestitate a acoperirii: un meci pe care nu-l putem judeca NU se declara
    curat — nici nu intra in numaratoarea de verificabile (Regula #8)."""
    rows = [
        _r(1, "A", "X", "Arena A"), _r(2, "A", "Y", "Arena A"),
        _r(9, "A", "NecunoscutFC", "Arena A"),
    ]
    candidati, judecabile = find_home_away_inversions(rows)
    assert candidati == []
    assert judecabile == 0, "randul cu oaspete necunoscut nu e verificabil"


def test_numarul_de_judecabile_e_raportat_corect():
    rows = [
        _r(1, "A", "B", "Arena A"), _r(2, "A", "B", "Arena A"),
        _r(3, "B", "A", "Arena B"), _r(4, "B", "A", "Arena B"),
    ]
    _, judecabile = find_home_away_inversions(rows)
    assert judecabile == 4, "toate patru au oaspete cu stadion cunoscut"


def test_rand_fara_stadion_e_ignorat_nu_semnalat():
    rows = [
        _r(1, "A", "X", "Arena A"), _r(2, "A", "Y", "Arena A"),
        _r(9, "Z", "A", None),
    ]
    candidati, judecabile = find_home_away_inversions(rows)
    assert candidati == []
    assert judecabile == 0


def test_lista_goala_nu_arunca():
    assert find_home_away_inversions([]) == ([], 0)


def test_candidatul_arata_stadionul_asteptat_al_gazdei():
    """Raportul trebuie sa spuna si CE se astepta, nu doar ca ceva e in neregula
    — altfel verificarea umana (regula D3) porneste de la zero."""
    rows = [
        _r(1, "Aberdeen", "X", "Pittodrie"), _r(2, "Aberdeen", "Y", "Pittodrie"),
        _r(3, "Rangers", "P", "Ibrox"), _r(4, "Rangers", "Q", "Ibrox"),
        _r(9, "Rangers", "Aberdeen", "Pittodrie"),
    ]
    candidati, _ = find_home_away_inversions(rows)
    assert candidati[0]["stadion_asteptat_gazda"] == "Ibrox"
