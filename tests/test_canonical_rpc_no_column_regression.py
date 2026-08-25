"""Garda contra pierderii tacite de coloane din RPC-ul canonic.

CE S-A INTAMPLAT (2026-08-23 -> 2026-08-25). Migrarea 048 a fost generata
dintr-o baza VECHE a functiei `_upsert_match_canonical_locked`, nu din corpul
live. A rescris-o cu 75 de coloane in loc de 80, pierzand tacit cinci:

    attendance, capacity, home_goalkeeper_saves, away_goalkeeper_saves  (036)
    season                                                              (038)

Niciun test nu a cazut. Nicio eroare la rulare. Normalizatorul a continuat sa
extraga toate cinci, `database/queries.py` a continuat sa le citeasca pentru
Team DNA, iar RPC-ul le arunca in tacere. Defectul a iesit la iveala din
intamplare, doua zile mai tarziu, in timp ce se investiga altceva.

INVARIANTUL IMPUS AICI: cea mai noua definitie a RPC-ului trebuie sa contina
TOT ce a scris vreodata o definitie anterioara. O coloana intra in contractul
canonic si nu mai iese — daca vreodata trebuie scoasa cu adevarat, testul
cade si obliga la o decizie explicita, documentata, in loc sa dispara tacit.

Testul e PUR pe fisierele din `database/migrations/` — fara retea, fara
Supabase. Asta conteaza: garda trebuie sa functioneze inainte de a atinge
productia, nu dupa.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

MIGRATIONS = Path(__file__).parent.parent / "database" / "migrations"
ANCORA = "CREATE OR REPLACE FUNCTION _upsert_match_canonical_locked"

# Cheia naturala + fixture_id: se scriu la INSERT, dar NU se rescriu la UPDATE.
# Identitatea unui rand nu se schimba printr-un upsert obisnuit (reprogramarea
# are propriul bloc dedicat, migrarea 048).
NEACTUALIZABILE = {"fixture_id", "home_team", "away_team", "kickoff_date"}


def _definitii() -> list[Path]:
    fisiere = sorted(p for p in MIGRATIONS.glob("*.sql")
                     if ANCORA in p.read_text(encoding="utf-8"))
    assert fisiere, "nicio migrare nu defineste RPC-ul canonic — ancora s-a schimbat?"
    return fisiere


def _coloane_insert(p: Path) -> list[str]:
    s = p.read_text(encoding="utf-8")
    m = re.search(r"INSERT INTO match_history \((.*?)\)\n", s, re.S)
    assert m, f"{p.name}: lista de coloane a INSERT-ului nu a putut fi parsata"
    return [c.strip() for c in m.group(1).split(",")]


def _valori_insert(p: Path) -> list[str]:
    """Expresiile de nivel 0 din VALUES — parantezele imbricate nu se numara."""
    s = p.read_text(encoding="utf-8")
    val = s[s.index("    VALUES (\n"):s.index("    RETURNING id")]
    interior = val[val.index("(") + 1:val.rindex(")")]
    adancime, bucati, curent = 0, [], ""
    for ch in interior:
        if ch == "(":
            adancime += 1
        elif ch == ")":
            adancime -= 1
        if ch == "," and adancime == 0:
            bucati.append(curent)
            curent = ""
        else:
            curent += ch
    bucati.append(curent)
    return [b for b in bucati if b.strip()]


def _coloane_update(p: Path) -> set[str]:
    s = p.read_text(encoding="utf-8")
    bloc = s[s.index("UPDATE match_history m SET"):s.index("WHERE m.id = v_existing.id")]
    return set(re.findall(r"^\s{4}(\w+) = COALESCE", bloc, re.M))


# ── invariantul central ──────────────────────────────────────────────────────

def test_ultima_definitie_contine_tot_ce_s_a_scris_vreodata():
    """GARDA CENTRALA. Exact regresia din 048: o definitie noua, generata dintr-o
    baza veche, care pierde coloane fara ca nimic sa semnaleze."""
    fisiere = _definitii()
    reuniune: set[str] = set()
    for p in fisiere[:-1]:
        reuniune |= set(_coloane_insert(p))
    ultima = set(_coloane_insert(fisiere[-1]))
    pierdute = sorted(reuniune - ultima)
    assert not pierdute, (
        f"{fisiere[-1].name} pierde coloane scrise de o migrare anterioara: {pierdute}. "
        "O coloana intra in contractul canonic si nu mai iese. Daca eliminarea e "
        "intentionata, trebuie decisa explicit si documentata — nu strecurata "
        "printr-o regenerare din baza gresita."
    )


def test_ramura_update_acopera_tot_ce_scrie_insert_ul():
    """A doua fata a aceleiasi regresii: o coloana poate fi prezenta la INSERT si
    lipsa la UPDATE, iar atunci meciurile descoperite ca fixture VIITOR (INSERT
    intai, UPDATE dupa ce se joaca) n-ar primi-o niciodata."""
    ultima = _definitii()[-1]
    insert = set(_coloane_insert(ultima))
    update = _coloane_update(ultima)
    lipsa = sorted(insert - update - NEACTUALIZABILE)
    assert not lipsa, f"{ultima.name}: scrise la INSERT dar niciodata la UPDATE: {lipsa}"


@pytest.mark.parametrize("fisier", _definitii(), ids=lambda p: p.name)
def test_paritate_coloane_valori(fisier: Path):
    """Postgres prinde asta la CREATE (check_function_bodies=on), dar abia DUPA
    ce migrarea a ajuns pe productie. Aici cade inainte."""
    n_col, n_val = len(_coloane_insert(fisier)), len(_valori_insert(fisier))
    assert n_col == n_val, f"{fisier.name}: {n_col} coloane vs {n_val} valori"


def test_nicio_coloana_duplicata_in_insert():
    for p in _definitii():
        coloane = _coloane_insert(p)
        duplicate = sorted({c for c in coloane if coloane.count(c) > 1})
        assert not duplicate, f"{p.name}: coloane repetate in INSERT: {duplicate}"


# ── istoricul ramane vizibil ─────────────────────────────────────────────────

def test_regresia_din_048_ramane_documentata():
    """North Star #9. Migrarile sunt append-only: 048/049/052 raman in repo cu
    defectul lor, ca dovada. Testul verifica atat ca istoricul e intact, cat si
    ca reparatia a avut loc — daca cineva ar 'curata' retroactiv fisierele, ar
    disparea si dovada, si motivul acestei garzi."""
    dupa_nume = {p.name: set(_coloane_insert(p)) for p in _definitii()}
    pierdute_de_048 = {
        "attendance", "capacity", "home_goalkeeper_saves", "away_goalkeeper_saves", "season",
    }
    v048 = next(v for k, v in dupa_nume.items() if k.startswith("048"))
    v038 = next(v for k, v in dupa_nume.items() if k.startswith("038"))
    v053 = next(v for k, v in dupa_nume.items() if k.startswith("053"))

    assert v038 - v048 == pierdute_de_048, "istoricul regresiei 048 s-a schimbat"
    assert pierdute_de_048 <= v053, "migrarea 053 nu mai restaureaza tot ce s-a pierdut"
