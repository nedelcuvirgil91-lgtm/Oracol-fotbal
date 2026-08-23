"""Teste pentru scripts/check_data_health.py — detectia formelor abreviate
(ADR-063). `find_abbreviation_pairs()` e PURA, testata direct, fara Supabase.

Capcana centrala, gasita empiric: o scanare naiva care imperecheaza pe
sufixul comun produce "Din. Zagreb" ↔ "Lok. Zagreb" — doua cluburi DIFERITE
din acelasi oras. Interogarea SQL exploratorie din 2026-08-23 a facut exact
aceasta greseala; functia de aici o evita cerand si potrivirea pe initiala.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from check_data_health import find_abbreviation_pairs  # noqa: E402


def test_lista_goala():
    assert find_abbreviation_pairs([]) == []


def test_perechea_reala_din_zagreb():
    pairs = find_abbreviation_pairs(["Din. Zagreb", "Dinamo Zagreb", "Rijeka"])
    assert pairs == [("Din. Zagreb", "Dinamo Zagreb")]


def test_nu_imperecheaza_cluburi_diferite_din_acelasi_oras():
    """Capcana centrala: 'Din. Zagreb' si 'Lok. Zagreb' se termina ambele cu
    'Zagreb', dar sunt Dinamo si Lokomotiva — cluburi diferite."""
    pairs = find_abbreviation_pairs(["Din. Zagreb", "Lok. Zagreb"])
    assert pairs == [], f"nu trebuie imperecheate intre ele, dar s-a produs: {pairs}"


def test_garda_pe_initiala_separa_cluburi_diferite_cu_sufix_comun():
    """[ADAUGAT dupa un test de mutatie esuat] Testul de mai sus trecea din
    ALT motiv decat cel intentionat: 'Lok. Zagreb' e sarit fiindca e el
    insusi o abreviere, nu datorita potrivirii pe initiala. Eliminand
    `o.startswith(prefix)` din cod, testul ramanea verde — garda era
    NETESTATA.

    Cazul care o testeaza cu adevarat: forma lunga concurenta NU e o
    abreviere, dar are acelasi sufix si alta initiala. Fara garda,
    'Din. Zagreb' s-ar imperechea gresit cu 'Lokomotiva Zagreb'."""
    pairs = find_abbreviation_pairs(["Din. Zagreb", "Lokomotiva Zagreb", "Dinamo Zagreb"])
    assert ("Din. Zagreb", "Dinamo Zagreb") in pairs
    assert ("Din. Zagreb", "Lokomotiva Zagreb") not in pairs, (
        "garda pe initiala lipseste — 'Din.' nu are voie sa se lege de 'Lokomotiva'"
    )


def test_nu_imperecheaza_abreviere_cu_abreviere():
    """Doua forme abreviate nu se unifica una cu alta — ambele ar trebui sa
    trimita catre o forma lunga, nu una catre cealalta."""
    pairs = find_abbreviation_pairs(["Din. Zagreb", "Lok. Zagreb", "Dinamo Zagreb", "Lokomotiva Zagreb"])
    for short, long in pairs:
        assert not long.startswith(("Din. ", "Lok. ")), f"{long!r} e tot o abreviere"
    assert ("Din. Zagreb", "Dinamo Zagreb") in pairs
    assert ("Lok. Zagreb", "Lokomotiva Zagreb") in pairs


def test_diferenta_doar_de_punct():
    """'St. Mirren' vs 'St Mirren' — cazul cel mai evident, gasit real."""
    assert find_abbreviation_pairs(["St. Mirren", "St Mirren"]) == [("St. Mirren", "St Mirren")]


def test_nu_raporteaza_nimic_cand_nu_exista_forma_lunga():
    """'A. Klagenfurt' n-are corespondent in baza — nu se inventeaza unul."""
    assert find_abbreviation_pairs(["A. Klagenfurt", "Rapid Wien", "Sturm Graz"]) == []


def test_ignora_nume_fara_tipar_de_abreviere():
    assert find_abbreviation_pairs(["Dinamo Zagreb", "Rijeka", "Hajduk Split"]) == []


def test_rezultatul_e_determinist_indiferent_de_ordine():
    a = find_abbreviation_pairs(["Din. Zagreb", "Dinamo Zagreb", "St. Mirren", "St Mirren"])
    b = find_abbreviation_pairs(["St Mirren", "Dinamo Zagreb", "St. Mirren", "Din. Zagreb"])
    assert a == b


def test_nu_arunca_pe_valori_lipsa():
    assert find_abbreviation_pairs(["", "Din. Zagreb", "Dinamo Zagreb"]) == [
        ("Din. Zagreb", "Dinamo Zagreb")
    ]


def test_ignora_abrevierea_fara_rest():
    """'X. ' fara nimic dupa punct nu produce nicio pereche."""
    assert find_abbreviation_pairs(["A. ", "Ceva"]) == []
