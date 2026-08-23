"""Teste pentru unificarea formelor abreviate cu cele lungi (2026-08-23).

CONTEXT: trei cluburi trăiau în `match_history` sub două nume în paralel — forma
abreviată (Flashscore) și forma lungă (surse istorice) — ca și cum ar fi fost
cluburi diferite: două lanțuri ELO, două istorii H2H. Perechile nu se
întâlniseră niciodată într-un meci, deci detecția D2/D3 de până atunci nu le
putea vedea.

| abreviat (Flashscore) | lung (istoric) | motiv |
|---|---|---|
| `Din. Zagreb` (14)  | `Dinamo Zagreb` (19) | ambele erau CANONICE în hartă |
| `St. Mirren` (7)    | `St Mirren` (147)    | niciuna nu era în hartă |
| `St. Truiden` (8)   | `St Truiden` (149)   | doar abrevierea era canonică |

DECIZIA (proprietarul produsului): canonic = forma LUNGĂ, abrevierea devine
alias. Stratul de alias există tocmai ca forma unui provider să nu dicteze
vocabularul stocat (ADR-058) — precedent identic, deja funcțional de mult:
`PSG` → `Paris Saint-Germain`, 244 de rânduri.

CAPCANA DE ÎNTREȚINERE pe care o păzesc testele de aici: `Din. Zagreb` și
`St. Truiden` erau EMISE ca baze canonice de `scripts/identity_f3_emit_aliases.py`.
Auditul F0 le văzuse doar cu sufix de țară și nu avea cum să știe că există o
formă lungă în istoric. O regenerare oarbă a blocului le-ar reintroduce ca al
doilea canonic — tăcut, pentru că `ALIAS_TO_CANONICAL` se construiește
necondiționat și ultima scriere ar câștiga, în funcție de ordinea de iterație.

Fără rețea, fără Supabase.
"""
from __future__ import annotations

import pytest

from mappings import TEAM_ALIASES, normalize_team_name

PERECHI = [
    ("Din. Zagreb", "Dinamo Zagreb"),
    ("St. Mirren", "St Mirren"),
    ("St. Truiden", "St Truiden"),
]


@pytest.mark.parametrize("abreviat,lung", PERECHI)
def test_forma_abreviata_se_rezolva_la_cea_lunga(abreviat, lung):
    assert normalize_team_name(abreviat) == lung


@pytest.mark.parametrize("abreviat,lung", PERECHI)
def test_forma_lunga_e_stabila(abreviat, lung):
    """Canonicul trebuie să se mapeze la el însuși — altfel am muta doar
    fragmentarea în altă parte."""
    assert normalize_team_name(lung) == lung


@pytest.mark.parametrize("abreviat,lung", PERECHI)
def test_abrevierea_nu_mai_e_cheie_canonica(abreviat, lung):
    """GARDA CENTRALĂ contra regenerării blocului F3.

    Dacă un viitor `identity_f3_emit_aliases.py` reintroduce `Din. Zagreb` sau
    `St. Truiden` ca bază canonică, `ALIAS_TO_CANONICAL` va avea aceeași cheie
    scrisă de două ori și rezultatul devine dependent de ordinea de iterație —
    o regresie tăcută, exact clasa de defect pe care unificarea o repară."""
    assert abreviat not in TEAM_ALIASES, (
        f"{abreviat!r} a redevenit cheie canonică — probabil printr-o "
        f"regenerare a blocului F3. Trebuie să rămână alias al lui {lung!r}."
    )
    assert lung in TEAM_ALIASES
    assert abreviat in TEAM_ALIASES[lung]


@pytest.mark.parametrize("abreviat,lung,tara", [
    ("Din. Zagreb", "Dinamo Zagreb", "CRO"),
    ("St. Truiden", "St Truiden", "BEL"),
])
def test_sufixul_de_tara_ajunge_tot_la_forma_lunga(abreviat, lung, tara):
    """Formele cu sufix erau chiar motivul pentru care abrevierile intraseră în
    hartă (auditul F0). Regula structurală de sufix caută forma dezbrăcată în
    `ALIAS_TO_CANONICAL`, deci trebuie să treacă acum prin alias, nu să se
    oprească la abreviere."""
    assert normalize_team_name(f"{abreviat} ({tara})") == lung


def test_cluburile_vecine_nu_sunt_afectate():
    """Fără această verificare, o unificare prea lacomă ar putea absorbi un club
    diferit cu nume asemănător. `St. Gallen` rămâne canonic propriu (nu are
    formă lungă concurentă), iar `Paris FC` nu are voie să devină PSG —
    coliziune reală, documentată în mappings.py."""
    assert normalize_team_name("St. Gallen") == "St. Gallen"
    assert normalize_team_name("Paris FC") == "Paris FC"
    assert normalize_team_name("PSG") == "Paris Saint-Germain"


def test_lok_zagreb_nu_devine_dinamo_zagreb():
    """Două cluburi DIFERITE din același oraș. Scanarea naivă de abrevieri le
    confundă (ambele se termină în „Zagreb"); normalizarea nu are voie."""
    assert normalize_team_name("Lok. Zagreb") != "Dinamo Zagreb"
