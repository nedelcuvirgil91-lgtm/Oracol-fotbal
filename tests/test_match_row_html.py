"""Regresie UI — `_match_row_html` (app.py) randează HTML pe o singură linie.

Bug reprodus în producție: pentru meciuri FĂRĂ cote afișate (`odds_html == ""`),
f-string-ul multi-linie din `_render_match_card` lăsa o linie goală în interiorul
blocului HTML. Per CommonMark, o linie goală termină un bloc HTML, iar
`<div class="match-src">` indentat imediat după era randat ca bloc de cod
monospace — exact textul brut `<div class="match-src">thesp...` văzut în UI.

Fix: HTML construit prin concatenare pe O SINGURĂ linie (fără newline, fără
indentare), indiferent de care segmente sunt goale.

`app.py` NU poate fi importat (rulează întreg scriptul Streamlit la import și
se blochează), deci `_match_row_html` e extrasă prin AST și executată izolat."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).parent.parent


def _load_match_row_html():
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_match_row_html":
            ns: dict = {}
            exec(ast.get_source_segment(src, node), ns)
            return ns["_match_row_html"]
    raise AssertionError("_match_row_html() nu a fost găsită în app.py")


def test_no_odds_produces_single_line_no_indented_block():
    """Cazul bug-ului: fără cote, HTML-ul nu conține newline și nicio linie
    indentată cu 4 spații (care ar deveni bloc de cod în Markdown)."""
    html = _load_match_row_html()(
        "20:00", "Mjällby", "Lincoln Red Imps", "", "", "thesportsdb")
    assert "\n" not in html, f"HTML conține newline: {html!r}"
    assert "    " not in html, f"HTML conține indentare de 4 spații: {html!r}"
    assert '<div class="match-src">thesportsdb</div>' in html
    # match-src urmează direct după </div>-ul echipelor, fără linie goală
    assert 'match-src' in html and html.endswith('</div>')


def test_with_odds_still_single_line():
    """Regresia nu trebuie să afecteze meciurile CU cote."""
    odds = ('<div class="match-odds"><div class="odd-pill home">1.80</div>'
            '<div class="odd-pill draw">3.50</div>'
            '<div class="odd-pill away">4.20</div></div>')
    html = _load_match_row_html()(
        "18:30", "Team A", "Team B", "", odds, "odds-api")
    assert "\n" not in html
    assert "    " not in html
    assert odds in html


def test_demo_badge_and_all_segments_render():
    html = _load_match_row_html()(
        "15:00", "Home", "Away", " <span>DEMO</span>", "", "demo-src")
    assert "\n" not in html
    assert '<div class="match-time">15:00</div>' in html
    assert '<div class="match-home">Home <span>DEMO</span></div>' in html
    assert '<div class="match-away">Away</div>' in html
    assert '<div class="match-src">demo-src</div>' in html
