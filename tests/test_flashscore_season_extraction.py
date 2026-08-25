"""Teste pentru extragerea sezonului din hub-ul Flashscore (ADR-066).

CONTEXT: `match_history.season` era NULL pentru TOATE cele 1.058 de rânduri
Flashscore (757 doar în august). `CLAUDE.md` (2026-08-03) documenta golul cu
concluzia că sezonul e „genuin necolectat de pe pagină, ar cere investigație
live nouă".

Concluzia era GREȘITĂ, iar dovada exista deja în repo: HTML-ul de hub salvat ca
evidență POC — adică exact pagina pe care Discovery o descarcă la fiecare
rulare — conține și eticheta sezonului, și intervalul. Costul de rețea al
extragerii e zero.

Testele rulează pe HTML-ul REAL din repo, nu pe fixture-uri inventate.

Fără rețea, fără Supabase.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from providers.flashscore.discovery import parse_season_from_hub

EVIDENCE = Path(__file__).parent.parent / "docs" / "06_UDAL" / "poc_evidence" / "flashscore_10matches"


def _hub(nume: str) -> str:
    f = EVIDENCE / nume
    if not f.exists():
        pytest.skip(f"evidență POC indisponibilă: {f}")
    return f.read_text(encoding="utf-8", errors="replace")


# ── HTML real ────────────────────────────────────────────────────────────────

def test_superliga_din_html_real():
    assert parse_season_from_hub(_hub("superliga_results_hub_raw.html")) == {
        "season": "2026-2027", "start_date": "2026-07-17", "end_date": "2027-05-30",
    }


def test_champions_league_din_html_real():
    """A doua competiție, cu calendar diferit — confirmă că nu e o potrivire
    întâmplătoare pe un singur fișier."""
    assert parse_season_from_hub(_hub("ucl_results_hub_raw.html")) == {
        "season": "2026-2027", "start_date": "2026-07-07", "end_date": "2027-06-05",
    }


# ── cazurile din capturile proprietarului produsului ─────────────────────────

def _fals(eticheta: str, start: str, final: str) -> str:
    return (f'<div class="heading__info">{eticheta}</div>'
            f'<div class="wcl-progressBarContainer_qiOjQ">'
            f'<span class="wcl-progressLabel_J wcl-start_TGQDT">{start}</span>'
            f'<span class="wcl-progressLabel_J wcl-end_OQo3-">{final}</span></div>')


def test_ligue1_traverseaza_anul():
    assert parse_season_from_hub(_fals("2026/2027", "21.08.", "06.06.")) == {
        "season": "2026-2027", "start_date": "2026-08-21", "end_date": "2027-06-06",
    }


def test_mls_sezon_intr_un_singur_an():
    """CAZUL CARE CONTEAZĂ. MLS joacă februarie–decembrie, în același an
    calendaristic. Pragul fix de 1 iulie din `_current_season_start_date()`
    taie exact prin mijlocul lui — cu sezonul real, tăietura dispare."""
    assert parse_season_from_hub(_fals("2026", "21.02.", "18.12.")) == {
        "season": "2026-2026", "start_date": "2026-02-21", "end_date": "2026-12-18",
    }


def test_sezon_de_primavara_ia_al_doilea_an():
    """Sezon care NU traversează anul deși eticheta are doi ani: luna de start
    e mai mică decât cea de sfârșit, deci ambele margini cad în al doilea an.
    Anul vine din etichetă, niciodată din calendarul de azi."""
    out = parse_season_from_hub(_fals("2026/2027", "03.03.", "28.11."))
    assert out["start_date"] == "2027-03-03"
    assert out["end_date"] == "2027-11-28"


# ── degradare: necunoscut rămâne necunoscut ──────────────────────────────────

def test_fara_eticheta_intoarce_none():
    """Regula #8: fără etichetă nu se ghicește anul din calendar.
    `season_cleanup.py` interzice deja explicit aproximarea calendaristică."""
    assert parse_season_from_hub(_fals("", "17.07.", "30.05.").replace(
        '<div class="heading__info"></div>', "")) is None


def test_eticheta_nerecunoscuta_intoarce_none():
    assert parse_season_from_hub(_fals("sezonul viitor", "17.07.", "30.05.")) is None


def test_bara_absenta_pastreaza_sezonul_fara_interval(caplog):
    """Clasele barei sunt hash-uite si se pot schimba la orice redeploy.
    Atunci se pastreaza ce se stie (eticheta) si se LOGHEAZA lipsa — nu se
    inventeaza un interval."""
    html = '<div class="heading__info">2026/2027</div>'
    with caplog.at_level("WARNING"):
        out = parse_season_from_hub(html)
    assert out == {"season": "2026-2027", "start_date": None, "end_date": None}
    assert "bara de sezon absent" in caplog.text


def test_ancorare_pe_prefix_nu_pe_hash():
    """GARDĂ: sufixul clasei e un hash volatil. Un hash DIFERIT trebuie să
    funcționeze la fel — altfel primul redeploy Flashscore rupe extragerea
    tăcut."""
    html = ('<div class="heading__info">2026/2027</div>'
            '<div class="wcl-progressBarContainer_ALTUL">'
            '<span class="wcl-start_XXXXX">17.07.</span>'
            '<span class="wcl-end_YYYYY">30.05.</span></div>')
    assert parse_season_from_hub(html)["start_date"] == "2026-07-17"


def test_html_gol_nu_arunca():
    assert parse_season_from_hub("") is None
    assert parse_season_from_hub("<html><body>nimic</body></html>") is None


def test_formatul_e_cel_canonic():
    """ADR-066 §4: scrierile NOI folosesc `YYYY-YYYY`, formatul majoritar
    (7.591 rânduri) și neambiguu. Coloana e azi fragmentată (5.245 de rânduri
    `YYYY-YY`), dar normalizarea lor e o decizie separată."""
    out = parse_season_from_hub(_fals("2026/2027", "17.07.", "30.05."))
    assert out["season"] == "2026-2027"
    assert "/" not in out["season"]
