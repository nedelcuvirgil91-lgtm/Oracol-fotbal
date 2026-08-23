"""Teste pentru `_extract_team_names` — orientarea gazda/oaspete.

CONTEXT (bug real de productie, 2026-08-23): orientarea se stabilea din
ORDINEA elementelor in DOM (`seen[0]` = gazda, `seen[1]` = oaspete), printr-un
selector generic. Cand Flashscore a randat pagina altfel in ziua meciului,
orientarea s-a inversat tacit: acelasi meci (mid=p2AX2W4D, Ligue 1) a fost
extras ca `psg__rennes` pe 31 iulie si ca `rennes__psg` pe 23 august.

Verificat extern: meciul se juca la Roazhon Park, deci Rennes era gazda —
extragerea din iulie era gresita, dar fusese deja scrisa canonic in
match_history, cu predictii calculate pe orientarea inversata (inclusiv 5
randuri in shadow_predictions).

O inversare de teren contamineaza ELO, forma, H2H, atribuirea xG pe parti si
avantajul terenului propriu. A iesit la iveala DOAR din intamplare, printr-o
coliziune de fixture_id.

Testul central e `test_orientarea_rezista_la_inversarea_ordinii_din_dom`: el
reproduce exact modul de esec, pe HTML real, si pica daca cineva reintroduce
dependenta de ordinea DOM.

Fara retea, fara Supabase — doar fixture-ul HTML real din repo.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from providers.flashscore.normalizer import _extract_team_names

FIXTURE = (
    Path(__file__).parent.parent
    / "docs" / "06_UDAL" / "poc_evidence" / "flashscore_full_tabs_poc" / "stats.html"
)

# Valorile reale din fixture, citite din containerele semantice ale paginii.
GAZDA = "Dinamo Bucuresti"
OASPETE = "Univ. Craiova"


def _soup() -> BeautifulSoup:
    if not FIXTURE.exists():
        pytest.skip(f"fixture HTML real indisponibil: {FIXTURE}")
    return BeautifulSoup(FIXTURE.read_text(encoding="utf-8", errors="replace"), "html.parser")


def test_html_real_da_orientarea_corecta():
    assert _extract_team_names(_soup()) == (GAZDA, OASPETE)


def test_orientarea_rezista_la_inversarea_ordinii_din_dom():
    """GARDA CENTRALA — reproduce bug-ul de productie.

    Blocul `away` e mutat INAINTEA blocului `home`, exact ca in randarea care
    a inversat meciul Rennes-PSG. Containerele semantice raman intacte, deci
    orientarea trebuie sa ramana corecta. Cu vechea implementare (ordine DOM)
    acest test intoarce perechea inversata si pica."""
    soup = _soup()
    home_container = soup.select_one(".duelParticipant__home")
    away_container = soup.select_one(".duelParticipant__away")
    assert home_container is not None and away_container is not None
    home_container.insert_before(away_container.extract())

    assert _extract_team_names(soup) == (GAZDA, OASPETE)


def test_fara_containere_semantice_se_cade_pe_ordinea_dom_cu_avertisment(caplog):
    """Fallback-ul ramane disponibil (nu pierdem extragerea daca Flashscore
    schimba structura), dar NU redevine tacit sursa de adevar."""
    soup = _soup()
    for container in soup.select(".duelParticipant__home, .duelParticipant__away"):
        container["class"] = ["altceva"]

    with caplog.at_level("WARNING"):
        assert _extract_team_names(soup) == (GAZDA, OASPETE)

    assert "containere semantice absente" in caplog.text, \
        "fallback-ul pe ordinea DOM trebuie sa fie vizibil in log, niciodata tacit"


def test_un_singur_container_prezent_nu_e_suficient():
    """Daca doar unul dintre containere exista, orientarea NU e confirmata —
    nu se deduce celalalt din ordinea DOM ca si cum ar fi verificat."""
    soup = _soup()
    away_container = soup.select_one(".duelParticipant__away")
    away_container["class"] = ["altceva"]

    # Cade pe fallback (ambele nume, din ordinea DOM), nu pe o combinatie
    # hibrida "home semantic + away ghicit".
    assert _extract_team_names(soup) == (GAZDA, OASPETE)


def test_pagina_fara_participanti_nu_arunca():
    """Regula #8: o stare necunoscuta ramane necunoscuta, nu devine exceptie
    si nici un nume inventat."""
    soup = BeautifulSoup("<html><body><p>nimic</p></body></html>", "html.parser")
    assert _extract_team_names(soup) == (None, None)


def test_nume_gol_in_container_nu_se_completeaza_cu_echipa_cealalta():
    """GARDA — gasita prin test, nu prin inspectie.

    Prima versiune a fix-ului cadea pe ordinea DOM ori de cate ori un nume
    lipsea. Cu numele gazdei golit, fallback-ul intorcea `('Univ. Craiova',
    None)` — adica OASPETELE drept GAZDA, exact inversarea pe care functia o
    repara, reintrodusa pe alta cale.

    Comportamentul corect: containerul e prezent, deci structura e inteleasa;
    un nume lipsa ramane lipsa si randul e respins de validarea de identitate
    (`missing_natural_key`), niciodata completat prin ghicire."""
    soup = _soup()
    el = soup.select_one(".duelParticipant__home .participant__participantName")
    el.string = ""

    home, away = _extract_team_names(soup)
    assert home is None, "un nume lipsa nu se inlocuieste cu nimic"
    assert away == OASPETE
    assert home != OASPETE, "gazda nu devine NICIODATA echipa oaspete"
