"""ADR-068 Faza A — colectarea literei brute a stării meciului.

DE CE FAZA A EXISTĂ SEPARAT. ADR-068 propune o coloană `match_status` care să
distingă un meci AMÂNAT de unul al cărui rezultat n-a fost colectat — azi arată
identic (dată în trecut, `actual_result` NULL), iar trei cazuri reale au fost
confirmate extern în trei săptămâni.

Dar ADR-ul cerea explicit o verificare înainte de orice cod: că marcajul există
în HTML-ul pe care îl descărcăm deja. Verificarea a dat un răspuns PARȚIAL:

  CONFIRMAT, pe HTML real din repo (55 fișiere): câmpul există, e în pagina
  `summary` (cost de rețea zero), clasele sunt SEMANTICE — fără hash, deci mai
  robuste decât bara de sezon din ADR-067 — și normalizatorul nu îl extrăgea.
      <span class="detailStatus">Finished</span>            88 apariții
      „After Extra Time"                                    12 apariții

  NEconfirmat: litera pentru un meci AMÂNAT. Niciun fișier salvat nu conține
  unul, sandbox-ul nu ajunge la flashscore.com (403 la proxy), iar pagina
  randată prin JS nu se poate citi din afară.

De aceea Faza A colectează verbatim și NU interpretează. Vocabularul real
devine observabil în `flashscore_raw_extraction` după o rulare de noapte; abia
atunci Faza B mapează literalele OBSERVATE într-o coloană canonică.

Fără rețea, fără Supabase.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from providers.flashscore.normalizer import extract_detail_status, normalize_match_statistics

EVIDENCE = Path(__file__).parent.parent / "docs" / "06_UDAL" / "poc_evidence" / "flashscore_10matches"


def _soup(html: str):
    return BeautifulSoup(html, "html.parser")


# ── pe HTML REAL din repo ────────────────────────────────────────────────────

def test_pe_html_real_salvat():
    """Nu fixture inventat: exact pagina pe care pipeline-ul o descarcă."""
    f = EVIDENCE / "superliga_1_rapid-bucuresti-YFCpigVG_mid=EeqI7WJc__summary.html"
    if not f.exists():
        pytest.skip(f"evidență POC indisponibilă: {f}")
    assert extract_detail_status(_soup(f.read_text(encoding="utf-8", errors="replace"))) == "Finished"


# ── extragere verbatim, fără interpretare ────────────────────────────────────

def test_valoarea_e_intoarsa_verbatim():
    """GARDA CENTRALĂ a Fazei A: nicio traducere, nicio normalizare, niciun
    lowercase. Litera brută e chiar scopul — dacă o transformăm, pierdem exact
    informația pentru care colectăm."""
    for litera in ("Finished", "After Extra Time", "Postponed", "Cancelled",
                   "Abandoned", "Scheduled", "Ceva Necunoscut"):
        html = f'<span class="detailStatus">{litera}</span>'
        assert extract_detail_status(_soup(html)) == litera


def test_al_doilea_selector_e_folosit_ca_rezerva():
    """Ambele locuri confirmate în HTML real; dacă primul lipsește, al doilea
    trebuie încercat — altfel o schimbare de layout taie extragerea tăcut."""
    html = '<div class="fixedHeaderDuel__detailStatus">After Extra Time</div>'
    assert extract_detail_status(_soup(html)) == "After Extra Time"


def test_primul_selector_are_prioritate():
    html = ('<span class="detailStatus">Finished</span>'
            '<div class="fixedHeaderDuel__detailStatus">Altceva</div>')
    assert extract_detail_status(_soup(html)) == "Finished"


# ── degradare: absența nu e defect ───────────────────────────────────────────

def test_lipsa_starii_nu_e_eroare():
    """Un meci fără element de stare e un caz NORMAL (ex. fixture viitor), nu
    un defect — deci None, fără excepție și fără log de eroare."""
    assert extract_detail_status(_soup("<html><body>nimic</body></html>")) is None
    assert extract_detail_status(_soup("")) is None
    assert extract_detail_status(None) is None


def test_element_gol_e_tratat_ca_absent():
    assert extract_detail_status(_soup('<span class="detailStatus"></span>')) is None
    assert extract_detail_status(_soup('<span class="detailStatus">   </span>')) is None


def test_element_gol_cade_pe_al_doilea_selector():
    html = ('<span class="detailStatus">  </span>'
            '<div class="fixedHeaderDuel__detailStatus">Postponed</div>')
    assert extract_detail_status(_soup(html)) == "Postponed"


# ── cablare: valoarea ajunge în output-ul normalizatorului ───────────────────

def test_campul_ajunge_in_rezultatul_normalizatorului():
    """Capătul firului. Fără asta, extragerea poate fi corectă și totuși
    valoarea să nu ajungă niciodată în stratul RAW — exact clasa de defect de
    la ADR-066 (extragere bună, fir netăiat)."""
    f = EVIDENCE / "superliga_1_rapid-bucuresti-YFCpigVG_mid=EeqI7WJc__summary.html"
    if not f.exists():
        pytest.skip(f"evidență POC indisponibilă: {f}")
    out = normalize_match_statistics({"summary": f.read_text(encoding="utf-8", errors="replace")})
    assert out.get("flashscore_status_raw") == "Finished"


def test_numele_campului_semnaleaza_ca_e_neinterpretat():
    """`_raw` în nume nu e cosmetic: previne ca cineva să citească valoarea ca
    stare canonică a meciului înainte de Faza B."""
    f = EVIDENCE / "superliga_1_rapid-bucuresti-YFCpigVG_mid=EeqI7WJc__summary.html"
    if not f.exists():
        pytest.skip(f"evidență POC indisponibilă: {f}")
    out = normalize_match_statistics({"summary": f.read_text(encoding="utf-8", errors="replace")})
    assert "flashscore_status_raw" in out
    assert "match_status" not in out, (
        "Faza A nu are voie să producă o coloană canonică — vocabularul nu e "
        "încă verificat pe date reale"
    )


def test_fara_pagina_summary_campul_ramane_none():
    out = normalize_match_statistics({"stats": "<html><body>fara stare</body></html>"})
    assert out.get("flashscore_status_raw") is None
