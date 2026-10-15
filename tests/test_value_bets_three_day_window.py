"""
Teste pentru fereastra de 3 zile a ecranului Top Value Bets (2026-10-15).

Trei clase de gărzi, cu scopuri diferite:

1. **`zile_radar()`** — funcția pură care produce fereastra. Testată inclusiv
   pe granițe de lună și de an, fiindcă acolo o implementare naivă (adunare pe
   numărul zilei) se rupe.

2. **Structura ecranului din `app.py`**, citită prin AST, nu prin text. Două
   lucruri se pot strica tăcut și NU se văd în niciun test unitar:
   - cheile de widget ale celor trei tab-uri trebuie să difere, altfel
     Streamlit aruncă `DuplicateWidgetID` și pagina cade la prima randare;
   - calculul live automat trebuie să rămână legat de ziua curentă. `st.tabs`
     randează conținutul TUTUROR tab-urilor, deci un `auto_live=True` ar
     declanșa zeci de evaluări complete pentru zile pe care utilizatorul nici
     nu le-a deschis.
   Se citește codul, nu comentariile: un `ast.parse` ignoră din construcție
   comentariile, deci garda nu-și poate găsi propria explicație — eroarea
   comisă deja de trei ori în proiect (`pipefail`, numele de secrete,
   docstring-ul din ADR-073).

3. **Workflow-ul colectorului.** Capcana reală nu e valoarea implicită a
   intrării manuale, ci expresia `||` din linia de comandă: la rulările `cron`,
   `github.event.inputs` e GOL, deci fereastra programată vine EXCLUSIV din
   fallback. Cineva care schimbă doar `default:` crede că a mărit fereastra, și
   n-a mărit-o pentru nicio rulare automată.

Zero rețea, zero Supabase, zero import de `app.py` (importul l-ar executa).
"""
from __future__ import annotations

import ast
import re
from datetime import date
from pathlib import Path

import pytest

from value_dashboard import ETICHETE_ZILE, zile_radar

RADACINA = Path(__file__).resolve().parents[1]
APP = RADACINA / "app.py"
WORKFLOW = RADACINA / ".github" / "workflows" / "value_selector_shadow.yml"


# ── 1. Funcția pură ──────────────────────────────────────────────────────────

def test_fereastra_implicita_are_trei_zile_consecutive():
    assert zile_radar(date(2026, 10, 15)) == [
        ("2026-10-15", "Azi"),
        ("2026-10-16", "Mâine"),
        ("2026-10-17", "Poimâine"),
    ]


def test_etichetele_sunt_cele_cerute_de_produs():
    assert ETICHETE_ZILE == ("Azi", "Mâine", "Poimâine")
    assert [e for _, e in zile_radar(date(2026, 1, 1))] == list(ETICHETE_ZILE)


def test_granita_de_luna():
    """O implementare care adună pe numărul zilei ar produce „2026-10-32"."""
    assert zile_radar(date(2026, 10, 30)) == [
        ("2026-10-30", "Azi"),
        ("2026-10-31", "Mâine"),
        ("2026-11-01", "Poimâine"),
    ]


def test_granita_de_an():
    assert [z for z, _ in zile_radar(date(2026, 12, 31))] == [
        "2026-12-31", "2027-01-01", "2027-01-02",
    ]


def test_granita_de_an_bisect():
    """2028 e bisect: 28 feb → 29 feb → 1 mar, nu 28 → 1 → 2."""
    assert [z for z, _ in zile_radar(date(2028, 2, 28))] == [
        "2028-02-28", "2028-02-29", "2028-03-01",
    ]


def test_o_singura_zi_ramane_posibila():
    assert zile_radar(date(2026, 10, 15), zile=1) == [("2026-10-15", "Azi")]


def test_dincolo_de_trei_zile_eticheta_e_data_nu_un_nume_inventat():
    """„Răspoimâine" e ambiguu; o etichetă seacă e preferabilă uneia inventate
    (Regula #8 — o stare fără nume nu se aproximează)."""
    iesire = zile_radar(date(2026, 10, 15), zile=5)
    assert len(iesire) == 5
    assert [e for _, e in iesire[:3]] == list(ETICHETE_ZILE)
    for _zi, eticheta in iesire[3:]:
        assert eticheta not in ETICHETE_ZILE
        assert re.fullmatch(r"\w{3} \d{2}/\d{2}", eticheta), eticheta


def test_zero_zile_intoarce_totusi_una():
    """Contrapondere: o fereastră goală ar lăsa ecranul fără niciun tab, adică
    o pagină albă fără nicio explicație."""
    assert len(zile_radar(date(2026, 10, 15), zile=0)) == 1


def test_functia_e_pura_nu_citeste_ceasul():
    """Ziua se injectează. Dacă funcția ar chema `date.today()` pe undeva,
    rezultatul ar depinde de ceasul mașinii, iar testele de graniță de mai sus
    ar trece sau nu după calendar."""
    sursa = ast.parse(Path(RADACINA / "value_dashboard.py").read_text(encoding="utf-8"))
    functie = next(n for n in ast.walk(sursa)
                   if isinstance(n, ast.FunctionDef) and n.name == "zile_radar")
    apeluri = {ast.unparse(n.func) for n in ast.walk(functie) if isinstance(n, ast.Call)}
    assert not {a for a in apeluri if "today" in a or "now" in a}, apeluri


# ── 2. Structura ecranului ───────────────────────────────────────────────────

def _functia_de_zi() -> ast.FunctionDef:
    arbore = ast.parse(APP.read_text(encoding="utf-8"))
    for nod in ast.walk(arbore):
        if isinstance(nod, ast.FunctionDef) and nod.name == "_randeaza_ziua":
            return nod
    pytest.fail("`_randeaza_ziua` nu mai există în app.py — ecranul a fost "
                "rescris; gărzile de mai jos trebuie reevaluate, nu șterse.")


def _siruri(nod: ast.AST) -> set[str]:
    """Toate constantele-șir din cod, inclusiv bucățile fixe ale f-string-urilor.
    Docstring-urile intră și ele, deci verificările de mai jos se scriu ca
    egalitate exactă sau prefix, niciodată ca „apare pe undeva în fișier"."""
    return {n.value for n in ast.walk(nod)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)}


def test_app_foloseste_fereastra_de_zile():
    arbore = ast.parse(APP.read_text(encoding="utf-8"))
    apeluri = {ast.unparse(n.func) for n in ast.walk(arbore) if isinstance(n, ast.Call)}
    assert "zile_radar" in apeluri, (
        "ecranul nu mai construiește fereastra prin `zile_radar()` — dacă a "
        "revenit la o singură zi, asta e regresia")


def test_paginarea_e_per_zi_nu_globala():
    """Cheia globală `radar_pagina` însemna o singură paginare pentru toate
    tab-urile: „Încă 5" la Azi ar fi mutat și Mâine, și Poimâine."""
    functie = _functia_de_zi()
    siruri = _siruri(functie)
    assert "radar_pagina" not in siruri, (
        "cheie de paginare GLOBALĂ în ecranul per zi")
    assert any(s.startswith("radar_pagina_") for s in siruri), siruri


def test_fiecare_widget_are_cheie_per_zi():
    """Fără chei distincte, cele trei tab-uri declară același widget și
    Streamlit aruncă `DuplicateWidgetID` — pagina cade la prima randare, deci
    un defect pe care niciun test de logică nu l-ar prinde."""
    functie = _functia_de_zi()
    butoane = [n for n in ast.walk(functie)
               if isinstance(n, ast.Call) and ast.unparse(n.func) == "st.button"]
    assert butoane, "niciun buton în ecranul per zi — structura s-a schimbat"
    for buton in butoane:
        chei = [kw.value for kw in buton.keywords if kw.arg == "key"]
        assert chei, f"buton fără `key` în `_randeaza_ziua`: {ast.unparse(buton)[:80]}"
        assert isinstance(chei[0], ast.JoinedStr), (
            "cheie CONSTANTĂ de widget într-un ecran randat de trei ori: "
            f"{ast.unparse(buton)[:80]}")


def test_calculul_live_automat_ramane_legat_de_ziua_curenta():
    """`st.tabs` randează TOATE tab-urile, nu doar cel vizibil. `auto_live=True`
    ar porni calculul live pentru toate cele trei zile, inclusiv pentru tab-uri
    nedeschise — zeci de evaluări complete într-o sesiune Streamlit."""
    arbore = ast.parse(APP.read_text(encoding="utf-8"))
    apeluri = [n for n in ast.walk(arbore)
               if isinstance(n, ast.Call) and ast.unparse(n.func) == "_randeaza_ziua"]
    assert apeluri, "`_randeaza_ziua` nu mai e apelată nicăieri"
    for apel in apeluri:
        valori = [kw.value for kw in apel.keywords if kw.arg == "auto_live"]
        assert valori, f"apel fără `auto_live`: {ast.unparse(apel)}"
        assert not isinstance(valori[0], ast.Constant), (
            "`auto_live` constant — calculul live nu mai e legat de ziua "
            f"curentă: {ast.unparse(apel)}")
        assert isinstance(valori[0], ast.Compare), ast.unparse(apel)


# ── 3. Workflow-ul colectorului ──────────────────────────────────────────────

FEREASTRA_MINIMA = 3


def _doar_cod(text: str) -> list[str]:
    """Liniile fără comentarii YAML. Fără asta, o gardă care caută `--days-ahead`
    s-ar putea mulțumi cu propria explicație din antetul fișierului."""
    return [l for l in text.splitlines() if not l.lstrip().startswith("#")]


def test_fereastra_colectorului_acopera_trei_zile():
    linii = _doar_cod(WORKFLOW.read_text(encoding="utf-8"))
    cod = "\n".join(linii)

    fallback = re.search(r"--days-ahead\s+\"\$\{\{[^}]*?\|\|\s*'(\d+)'\s*\}\}\"", cod)
    assert fallback, ("linia `--days-ahead` nu mai are fallback literal — "
                      "rulările `cron` ar primi un argument gol")
    assert int(fallback.group(1)) >= FEREASTRA_MINIMA, (
        f"fallback-ul e {fallback.group(1)} zile; rulările programate nu "
        f"primesc niciodată `github.event.inputs`, deci ASTA e fereastra reală")

    implicit = re.search(r"days_ahead:.*?default:\s*\"(\d+)\"", cod, re.S)
    assert implicit, "intrarea manuală `days_ahead` nu mai are `default`"
    assert implicit.group(1) == fallback.group(1), (
        f"implicitul manual ({implicit.group(1)}) diferă de cel al rulărilor "
        f"programate ({fallback.group(1)}) — o rulare manuală pornită pe "
        f"implicite ar măsura altă fereastră decât cea de noapte")
