"""
Gărzi pentru raportarea pe perioade a evaluării F2 (ADR-071 §16, extins 2026-10-15).

**De ce există.** Pe 15 octombrie, batch-ul de noapte a fost reparat să vadă
toate cele 18 competiții urmărite, nu 16. Experimentul F2 era deja în curs, cu
~40 de zile acumulate. Universul de meciuri se lărgește, deci:

- comparația ÎNTRE politici rămâne validă (toate cele 12 văd aceleași meciuri);
- dar ROI-ul ABSOLUT al unei politici devine calculat peste două universuri
  lipite, ceea ce nu e greșit, e doar greu de interpretat.

Soluția aleasă în locul unei resetări (care ar fi aruncat 40 de zile și ar fi
amânat primul verdict cu eșantion suficient de la 26-29 octombrie la finalul
lui noiembrie): nu se șterge nimic (§15), iar raportul arată cumulatul ȘI cele
două jumătăți.

**Capcana pe care o previn testele de aici:** un cutoff scris ca dată fixă ar
fi trebuit completat manual exact în momentul merge-ului — adică modul clasic
în care o măsurătoare rămâne tăcut greșită. Cutoff-ul se DEDUCE din date.

Zero rețea, zero Supabase.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

import value_selector_evaluation as ev

MODUL = Path(ev.__file__)


def _rand(run_id: str, liga: str, fid: str = "f1") -> dict:
    return {"run_id": run_id, "league": liga, "fixture_id": fid,
            "policy_id": "p@v1:abc", "selection_code": "1"}


# ── Detectarea cutoff-ului ───────────────────────────────────────────────────

def test_fara_competitii_noi_nu_exista_cutoff():
    """Starea de dinainte de merge: raportul trebuie să rămână exact cel vechi,
    fără secțiune de perioade. Un flag nou nu schimbă comportamentul implicit."""
    randuri = [_rand("2026-10-10T09:40Z", "Premier League"),
               _rand("2026-10-11T09:40Z", "La Liga")]
    assert ev.detecteaza_cutoff(randuri) is None


def test_cutoff_ul_e_PRIMA_aparitie_nu_ultima():
    """Mutația evidentă e `min` → `max`: ar muta granița la cea mai recentă
    rulare, deci aproape tot ar cădea în „înainte" și jumătatea „după" ar fi
    mereu aproape goală — exact opusul măsurătorii cerute."""
    randuri = [
        _rand("2026-10-20T09:40Z", "Conference League"),
        _rand("2026-10-16T14:00Z", "HNL"),
        _rand("2026-10-25T09:40Z", "Conference League"),
        _rand("2026-10-01T09:40Z", "Premier League"),
    ]
    assert ev.detecteaza_cutoff(randuri) == "2026-10-16T14:00Z"


def test_cutoff_ul_ignora_ligile_vechi():
    """O ligă veche într-o rulare timpurie nu are voie să coboare granița."""
    randuri = [_rand("2026-09-01T09:40Z", "Serie A"),
               _rand("2026-10-16T09:40Z", "HNL")]
    assert ev.detecteaza_cutoff(randuri) == "2026-10-16T09:40Z"


def test_rand_fara_liga_nu_doboara_detectia():
    randuri = [_rand("2026-10-16T09:40Z", "HNL"), {"run_id": "2026-10-17T09:40Z"}]
    assert ev.detecteaza_cutoff(randuri) == "2026-10-16T09:40Z"


def test_lista_goala_nu_produce_cutoff():
    assert ev.detecteaza_cutoff([]) is None


# ── Împărțirea pe perioade ───────────────────────────────────────────────────

def test_fara_cutoff_totul_e_inainte():
    randuri = [_rand("2026-10-01T09:40Z", "Serie A"),
               _rand("2026-10-02T09:40Z", "La Liga")]
    parti = ev.imparte_pe_perioade(randuri, None)
    assert len(parti["inainte"]) == 2 and parti["dupa"] == []


def test_rularea_de_granita_intra_in_DUPA():
    """Granița e inclusivă la dreapta: rularea care a introdus competițiile noi
    aparține universului nou, nu celui vechi. Mutația `>=` → `>` ar pune-o în
    partea greșită, iar prima rulare de după reparație ar fi numărată ca
    „înainte" — tăcut, și exact pe rândurile care contează cel mai mult."""
    cutoff = "2026-10-16T09:40Z"
    randuri = [_rand("2026-10-15T09:40Z", "Serie A"),
               _rand(cutoff, "Conference League"),
               _rand("2026-10-17T09:40Z", "La Liga")]
    parti = ev.imparte_pe_perioade(randuri, cutoff)
    assert [r["run_id"] for r in parti["inainte"]] == ["2026-10-15T09:40Z"]
    assert [r["run_id"] for r in parti["dupa"]] == [cutoff, "2026-10-17T09:40Z"]


def test_nicio_selectie_nu_se_pierde_la_impartire():
    """ADR-071 §15: nimic nu se șterge. Suma celor două jumătăți trebuie să fie
    exact întregul, altfel raportul pe perioade ar ascunde rânduri."""
    randuri = [_rand(f"2026-10-{zi:02d}T09:40Z", "Serie A", f"f{zi}")
               for zi in range(10, 25)]
    randuri.append(_rand("2026-10-18T09:40Z", "HNL", "fx"))
    cutoff = ev.detecteaza_cutoff(randuri)
    parti = ev.imparte_pe_perioade(randuri, cutoff)
    assert len(parti["inainte"]) + len(parti["dupa"]) == len(randuri)


# ── Constanta istorică ───────────────────────────────────────────────────────

def test_competitiile_intrate_sunt_un_fapt_istoric_nu_o_derivare():
    """Cutoff-ul NU are voie să fie dedus din `TRACKED_COMPETITIONS -
    ODDS_SPORT_KEYS`.

    Diferența aceea pare echivalentă azi, dar s-ar muta la PRIMA ligă nouă
    neacoperită de The Odds API — exact ligile pe care le avem pe listă de
    adăugat (Austria, Danemarca, Norvegia). Cutoff-ul ar aluneca atunci tăcut
    spre o dată mai târzie, iar cele două perioade ar fi greșite fără niciun
    semnal. Mulțimea e un fapt despre 15 octombrie 2026 și rămâne așa pe veci."""
    arbore = ast.parse(MODUL.read_text(encoding="utf-8"))
    atribuiri = [n for n in ast.walk(arbore)
                 if isinstance(n, ast.AnnAssign)
                 and isinstance(n.target, ast.Name)
                 and n.target.id == "COMPETITII_INTRATE_2026_10_15"]
    assert atribuiri, "constanta istorică a dispărut"
    sursa = ast.unparse(atribuiri[0].value)
    for interzis in ("TRACKED_COMPETITIONS", "ODDS_SPORT_KEYS", "LEAGUE_PROVIDERS"):
        assert interzis not in sursa, (
            f"cutoff derivat din `{interzis}` — alunecă la prima ligă nouă: {sursa}")
    assert ev.COMPETITII_INTRATE_2026_10_15 == frozenset({"Conference League", "HNL"})


def test_evaluatorul_ramane_strict_read_only():
    """Contrapondere la tot ce s-a adăugat: raportarea pe perioade nu are voie
    să introducă nicio scriere. Aceeași regulă pe care o impune garda AST
    existentă a modulului, reverificată aici pe codul nou."""
    arbore = ast.parse(MODUL.read_text(encoding="utf-8"))
    apeluri = {ast.unparse(n.func) for n in ast.walk(arbore) if isinstance(n, ast.Call)}
    for scriere in ("insert", "upsert", "update", "delete", "rpc", "execute_sql"):
        assert not [a for a in apeluri if a.endswith(f".{scriere}")], scriere
