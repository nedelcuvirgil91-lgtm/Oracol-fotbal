"""Teste pentru poarta de pregătire Team Profile corectată (ADR-062):
database.queries.count_matches_with_sufficient_history() + constanta
TEAM_PROFILE_WINDOW.

Funcția e PURĂ — testată direct, fără Supabase, fără rețea.

Invariantul central: poarta numără meciurile în care AMBELE echipe au deja
cel puțin `window` meciuri ANTERIOARE cu xG real — NU meciurile jucate în
sezon (cantitatea greșită pe care o măsura versiunea anterioară: la 298 de
meciuri „terminate" existau doar 15 evaluabile, 5,0%).
"""
from __future__ import annotations

import inspect

import database.queries as q


def _m(home, away, day, home_xg=1.0, away_xg=1.0, mid=None):
    return {
        "id": mid, "home_team": home, "away_team": away, "kickoff_date": day,
        "home_xg_actual": home_xg, "away_xg_actual": away_xg,
    }


def _chain(team_a: str, team_b: str, n: int, start_day: int = 1) -> list[dict]:
    """n meciuri, fiecare in alta zi, intre aceleasi doua echipe — creste
    istoricul ambelor cu exact n."""
    return [_m(team_a, team_b, f"2026-07-{start_day + i:02d}") for i in range(n)]


# ── Cazuri de bază ────────────────────────────────────────────────────────

def test_lista_goala_da_zero():
    assert q.count_matches_with_sufficient_history([], 5) == 0


def test_sub_prag_nimic_nu_e_evaluabil():
    """4 meciuri de istoric < window=5 -> niciun meci evaluabil."""
    rows = _chain("A", "B", 4)
    assert q.count_matches_with_sufficient_history(rows, 5) == 0


def test_exact_la_prag_urmatorul_meci_e_evaluabil():
    """Dupa exact 5 meciuri de istoric, al 6-lea devine evaluabil."""
    rows = _chain("A", "B", 5) + [_m("A", "B", "2026-07-20")]
    assert q.count_matches_with_sufficient_history(rows, 5) == 1


def test_pragul_e_inclusiv_pe_window():
    """>= window, nu > window — al 6-lea meci se numara cu exact 5 anterioare."""
    rows = _chain("A", "B", 5) + [_m("A", "B", "2026-07-20")]
    assert q.count_matches_with_sufficient_history(rows, 5) == 1
    # cu window=6, acelasi set nu mai produce niciun meci evaluabil
    assert q.count_matches_with_sufficient_history(rows, 6) == 0


# ── Invariantul „AMBELE echipe", nu doar una ──────────────────────────────

def test_o_singura_echipa_cu_istoric_nu_e_suficient():
    """A acumuleaza 5 meciuri (cu B), apoi joaca cu C, care n-are niciunul.
    Meciul A-C NU e evaluabil — formula are nevoie de ambele parti."""
    rows = _chain("A", "B", 5) + [_m("A", "C", "2026-07-20")]
    assert q.count_matches_with_sufficient_history(rows, 5) == 0


def test_ambele_echipe_cu_istoric_e_suficient():
    rows = _chain("A", "B", 5) + _chain("C", "D", 5, start_day=1) + [_m("A", "C", "2026-07-20")]
    assert q.count_matches_with_sufficient_history(rows, 5) == 1


# ── Semantica STRICTA a lui „anterior" (aceeasi zi nu conteaza) ───────────

def test_meciurile_din_aceeasi_zi_nu_se_numara_unele_pentru_altele():
    """Garda centrala impotriva scurgerii temporale: doua meciuri in ACEEASI
    zi nu-si construiesc istoric unul altuia. Cu 4 meciuri anterioare + 2 in
    aceeasi zi, niciunul din cele 2 nu devine evaluabil (ar avea nevoie de 5
    STRICT anterioare, iar celalalt meci al zilei nu se pune la socoteala)."""
    rows = _chain("A", "B", 4) + [
        _m("A", "B", "2026-07-20"),
        _m("A", "B", "2026-07-20"),
    ]
    assert q.count_matches_with_sufficient_history(rows, 5) == 0


def test_ziua_urmatoare_include_toate_meciurile_zilei_precedente():
    """Complementul testului de mai sus: contributiile unei zile intra in
    istoric incepand cu ziua URMATOARE, toate deodata."""
    rows = _chain("A", "B", 4) + [
        _m("A", "B", "2026-07-20"),
        _m("A", "B", "2026-07-21"),
    ]
    assert q.count_matches_with_sufficient_history(rows, 5) == 1


def test_ordinea_de_intrare_nu_schimba_rezultatul():
    """Rezultatul depinde de kickoff_date, nu de ordinea in lista primita —
    altfel numaratoarea ar fi nedeterminista fata de ordinea din DB."""
    rows = _chain("A", "B", 5) + [_m("A", "B", "2026-07-20")]
    assert (
        q.count_matches_with_sufficient_history(rows, 5)
        == q.count_matches_with_sufficient_history(list(reversed(rows)), 5)
    )


# ── xG lipsa nu contribuie la istoric (Regula #8) ────────────────────────

def test_meciurile_fara_xg_nu_construiesc_istoric():
    """Un meci fara xG real nu ajuta formula de finalizare, deci nu se
    numara ca istoric — nu se aproximeaza o valoare lipsa."""
    rows = [_m("A", "B", f"2026-07-{i:02d}", home_xg=None, away_xg=None) for i in range(1, 6)]
    rows.append(_m("A", "B", "2026-07-20"))
    assert q.count_matches_with_sufficient_history(rows, 5) == 0


def test_xg_partial_contribuie_doar_partii_care_il_are():
    """Daca doar gazda are xG, doar gazda isi creste istoricul."""
    rows = [_m("A", "B", f"2026-07-{i:02d}", home_xg=1.0, away_xg=None) for i in range(1, 6)]
    rows.append(_m("A", "B", "2026-07-20"))
    # A are 5, B are 0 -> nu e evaluabil (regula "ambele")
    assert q.count_matches_with_sufficient_history(rows, 5) == 0


# ── Robustete la date incomplete ─────────────────────────────────────────

def test_randuri_fara_kickoff_date_sunt_ignorate_nu_arunca():
    rows = _chain("A", "B", 5) + [{"home_team": "A", "away_team": "B", "kickoff_date": None}]
    assert q.count_matches_with_sufficient_history(rows, 5) == 0


def test_randuri_fara_echipa_sunt_ignorate_nu_arunca():
    rows = _chain("A", "B", 5) + [_m(None, "B", "2026-07-20")]
    assert q.count_matches_with_sufficient_history(rows, 5) == 0


def test_window_zero_sau_negativ_nu_filtreaza():
    rows = _chain("A", "B", 3)
    assert q.count_matches_with_sufficient_history(rows, 0) == len(rows)


# ── Garda de consecventa: fereastra portii == fereastra productiei ───────

def test_window_constant_matches_production_last_n():
    """TEAM_PROFILE_WINDOW trebuie sa fie identic cu `last_n` implicit din
    oracle_engine._build_flashscore_dna() — altfel poarta ar valida o
    fereastra, iar productia ar afisa alta (inconsistenta tacuta, exact
    tipul de divergenta pe care ADR-062 o previne)."""
    import oracle_engine

    sig = inspect.signature(oracle_engine.FootballOracleEngine._build_flashscore_dna)
    production_last_n = sig.parameters["last_n"].default
    assert production_last_n == q.TEAM_PROFILE_WINDOW, (
        f"_build_flashscore_dna(last_n={production_last_n}) difera de "
        f"TEAM_PROFILE_WINDOW={q.TEAM_PROFILE_WINDOW}"
    )
