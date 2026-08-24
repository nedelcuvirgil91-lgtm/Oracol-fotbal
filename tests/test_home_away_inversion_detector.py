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


def test_gazda_fara_teren_cunoscut_nu_poate_fi_acuzata():
    """GARDA CENTRALĂ, semnalată de proprietarul produsului (2026-08-24).

    Varianta anterioară cerea teren cunoscut doar pentru OASPETE. Dacă gazda
    lipsea din hartă, `acasa.get(gazda)` întorcea None ≠ stadion și rândul era
    SEMNALAT — se concluziona din stadion tocmai când lipsea dovada de teren
    pentru gazdă.

    Aici `NouPromovata` nu are meciuri acasă în corpus, deci nu poate fi
    judecată. Fără fix, meciul ei pe Pittodrie ar fi raportat ca inversare."""
    rows = [
        _r(1, "Aberdeen", "X", "Pittodrie"), _r(2, "Aberdeen", "Y", "Pittodrie"),
        _r(9, "NouPromovata", "Aberdeen", "Pittodrie"),
    ]
    candidati, judecabile = find_home_away_inversions(rows)
    assert candidati == [], f"gazda fara teren cunoscut nu are voie sa fie acuzata: {candidati}"
    assert judecabile == 0, "un meci pe care nu-l putem judeca nu intra in acoperire"


def test_echipa_cu_doua_terenuri_nu_capata_teren_propriu():
    """Cazul real semnalat: FCSB (Arena Națională / Stadionul Steaua), Paris FC,
    Kairat Almaty. La 3 vs 2 meciuri, „cel mai frecvent" e o coincidență
    statistică, nu identitate — echipa rămâne în afara hărții."""
    rows = [
        _r(1, "FCSB", "A", "Arena Nationala"), _r(2, "FCSB", "B", "Arena Nationala"),
        _r(3, "FCSB", "C", "Arena Nationala"),
        _r(4, "FCSB", "D", "Stadionul Steaua"), _r(5, "FCSB", "E", "Stadionul Steaua"),
    ]
    assert "FCSB" not in build_home_stadiums(rows), (
        "3 din 5 meciuri (60%) nu e dovada de teren propriu"
    )


def test_teren_dominant_ramane_acceptat():
    """Pragul nu are voie să elimine cazurile normale: o echipă cu un teren
    propriu clar, plus o excepție izolată (finală pe teren neutru), rămâne
    judecabilă."""
    rows = [_r(i, "Liverpool", f"Adv{i}", "Anfield") for i in range(1, 8)]
    rows.append(_r(99, "Liverpool", "Final", "Teren Neutru"))
    assert build_home_stadiums(rows).get("Liverpool") == "Anfield", (
        "7 din 8 meciuri (87,5%) e teren propriu clar"
    )


def test_teren_neutru_partajat_nu_produce_acuzatie():
    """Verificat în date: H. Beer Sheva a jucat „acasă" pe Giulești, terenul
    lui Rapid. Dacă niciunul nu are teren dominant, nu se judecă nimic."""
    rows = [
        _r(1, "Rapid", "A", "Giulesti"), _r(2, "Rapid", "B", "Giulesti"),
        _r(3, "Rapid", "C", "Giulesti"), _r(4, "Rapid", "D", "Giulesti"),
        _r(5, "Beer Sheva", "E", "Giulesti"), _r(6, "Beer Sheva", "F", "Giulesti"),
        _r(9, "Rapid", "Beer Sheva", "Giulesti"),
    ]
    candidati, _ = find_home_away_inversions(rows)
    assert candidati == [], "stadion partajat nu e dovada de inversare"


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
