"""Doua defecte de parsare in randurile H2H, gasite 2026-08-25.

DEFECTUL A — fereastra de secol lipsa la anul din doua cifre.
`_parse_h2h_date` facea `datetime(2000 + int(yy), ...)` neconditionat, deci
meciurile vechi ajungeau exact 100 de ani in VIITOR. Masurat: 35 de randuri.

    Coventry–Fulham    stocat 2067-11-10  (real 1967 — Coventry era in prima liga)
    Nice–Paris FC      stocat 2074-02-23  (real 1974 — Paris FC juca in Ligue 1)
    Dyn. Kyiv–PAOK     stocat 2076-10-20  (real 1976, Cupa Campionilor)

DEFECTUL B — al doilea tipar de tooltip, netratat si INCA ACTIV.
Fixul din 2026-08-10 taia „Advancing to next round" dar nu si „Winner:".
Masurat: 256 de randuri cu primul tipar, 201 cu al doilea. Numele corupt nu se
potriveste niciodata cu forma canonica la H2H — „FCSBWinner: FCSB" != „FCSB".

Fara retea, fara Supabase — functii pure.
"""
from __future__ import annotations

from datetime import datetime

from providers.flashscore.normalizer import _parse_h2h_date, _strip_advancing_note


# ── A. fereastra de secol ────────────────────────────────────────────────────

def test_meci_recent_ramane_in_secolul_curent():
    assert _parse_h2h_date("24.08.26") == "2026-08-24"
    assert _parse_h2h_date("15.03.25") == "2025-03-15"


def test_meci_vechi_cade_in_secolul_trecut():
    """CAZURILE REALE din productie."""
    assert _parse_h2h_date("10.11.67") == "1967-11-10"   # Coventry–Fulham
    assert _parse_h2h_date("23.02.74") == "1974-02-23"   # Nice–Paris FC
    assert _parse_h2h_date("20.10.76") == "1976-10-20"   # Dyn. Kyiv–PAOK


def test_anul_curent_e_pastrat_la_limita():
    """GARDA de frontiera: anul curent NU trebuie impins in trecut."""
    yy = f"{datetime.now().year % 100:02d}"
    assert _parse_h2h_date(f"01.01.{yy}") == f"{datetime.now().year}-01-01"


def test_pragul_e_relativ_la_anul_curent_nu_fix():
    """GARDA: fixul nu are voie sa expire. Anul urmator, un meci din anul
    urmator trebuie sa ramana in viitor apropiat, nu sa sara cu 100 de ani —
    deci regula se raporteaza la `datetime.now().year`, nu la o constanta."""
    import inspect
    sursa = inspect.getsource(_parse_h2h_date)
    assert "datetime.now().year" in sursa, (
        "fereastra de secol trebuie calculata fata de anul CURENT, nu fata de "
        "un prag hardcodat care ar deveni gresit peste ani"
    )


def test_data_invalida_ramane_none():
    assert _parse_h2h_date("32.13.26") is None
    assert _parse_h2h_date(None) is None
    assert _parse_h2h_date("") is None
    assert _parse_h2h_date("text fara data") is None


# ── B. tooltipurile concatenate ─────────────────────────────────────────────

def test_taie_advancing_to_next_round():
    assert _strip_advancing_note(
        "Univ. CraiovaAdvancing to next round: Univ. Craiova") == "Univ. Craiova"


def test_taie_si_winner(   ):
    """AL DOILEA TIPAR, gasit 2026-08-25 — era INCA ACTIV, nu doar istoric."""
    assert _strip_advancing_note("FCSBWinner: FCSB") == "FCSB"
    assert _strip_advancing_note("PSGWinner: PSG") == "PSG"
    assert _strip_advancing_note("Manchester CityWinner: Manchester City") == "Manchester City"


def test_numele_curate_raman_neatinse():
    """Contrapondere: fixul nu are voie sa ciupeasca nume legitime."""
    for nume in ("FCSB", "Paris Saint-Germain", "Dinamo Zagreb",
                 "Universitatea Cluj", "Sheffield Wednesday"):
        assert _strip_advancing_note(nume) == nume


def test_ambele_tipare_in_acelasi_sir():
    assert _strip_advancing_note("AjaxWinner: AjaxAdvancing to next round: Ajax") == "Ajax"


def test_spatiile_sunt_taiate():
    assert _strip_advancing_note("  Inter  ") == "Inter"
