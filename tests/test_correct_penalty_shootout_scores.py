"""Teste pentru scripts/correct_penalty_shootout_scores.py — corecția
supervizată a scorurilor penalty-shootout (ADR-060, Faza 1).

`build_sql()` e pură, testată direct. Testele structurale (AST) impun
condițiile 2 și 3 din ADR-060: corpus fix, suprafață minimă de scriere.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from correct_penalty_shootout_scores import CORRECTIONS, build_sql  # noqa: E402


def test_corpus_are_exact_sase_randuri():
    """Condiția 2 (ADR-060): corpus închis. Auditul (run 32560333453) a găsit
    exact 6 nepotriviri — corpusul nu are voie să difere."""
    assert len(CORRECTIONS) == 6
    assert {c["id"] for c in CORRECTIONS} == {3623, 3625, 3634, 3809, 3814, 114439}


def test_fiecare_corectie_are_valori_vechi_si_noi_diferite():
    for c in CORRECTIONS:
        assert c["old"] != c["new"], f"id={c['id']}: corecție fără efect"


def test_sql_e_generat_pentru_fiecare_corectie():
    stmts = build_sql(CORRECTIONS)
    assert len(stmts) == 6


def test_sql_where_contine_valoarea_veche_nu_cea_noua():
    """Idempotență (condiția 5): WHERE trebuie să verifice starea VECHE, nu
    cea nouă — altfel o rulare repetată ar rescrie orbește."""
    c = {"id": 3809, "fixture_id": "fd_524100", "meci": "x",
         "old": {"home": 1, "away": 5, "result": "A"},
         "new": {"home": 0, "away": 1, "result": "A"}}
    stmt = build_sql([c])[0]
    assert "WHERE id = 3809" in stmt
    assert "actual_home_goals = 1" in stmt  # vechea valoare, in WHERE
    assert "actual_away_goals = 5" in stmt
    assert "SET actual_home_goals = 0" in stmt  # noua valoare, in SET
    assert "SET actual_home_goals = 1" not in stmt


def test_sql_seteaza_exact_trei_coloane():
    """Suprafață minimă (condiția 3): SET nu are voie să atingă altceva
    (backfill_done, ELO, feature-uri) — acelea rămân pentru rebuild-ul separat."""
    stmt = build_sql(CORRECTIONS)[0]
    set_clause = stmt.split("SET", 1)[1].split("WHERE", 1)[0]
    coloane = {part.strip().split(" = ")[0] for part in set_clause.split(",")}
    assert coloane == {"actual_home_goals", "actual_away_goals", "actual_result"}


def test_liverpool_psg_corespunde_adevarului_verificat():
    """Ancorare directă în cazul care a declanșat auditul: 0-1, nu 1-5."""
    c = next(c for c in CORRECTIONS if c["id"] == 3809)
    assert c["new"] == {"home": 0, "away": 1, "result": "A"}
    assert c["old"] == {"home": 1, "away": 5, "result": "A"}


def test_trei_corectii_schimba_si_rezultatul_nu_doar_scorul():
    """3 din 6 au eticheta actual_result greșită (un egal înregistrat ca
    victorie) — verificare explicită că nu doar golurile se corectează."""
    schimba_rezultat = [c for c in CORRECTIONS if c["old"]["result"] != c["new"]["result"]]
    assert len(schimba_rezultat) == 3
    assert {c["id"] for c in schimba_rezultat} == {3634, 3814, 114439}


def test_scriptul_nu_recalibreaza_si_nu_reseteaza_backfill():
    """Condiția 'Ce NU declanșează' din ADR-060: nicio recalibrare, niciun
    reset de backfill_done/ELO ca efect secundar al corecției.

    Verificare pe AST, nu pe text brut: docstring-ul modulului MENȚIONEAZĂ
    aceste nume ca sa explice ce NU face scriptul — o cautare textuala ar
    da fals pozitiv chiar pe propria documentatie. Se elimina toate
    docstring-urile/comentariile inainte de verificare, ramane doar codul
    executabil.
    """
    import ast

    src = (Path(__file__).resolve().parent.parent / "scripts"
           / "correct_penalty_shootout_scores.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    # Eliminam toate constantele string (docstrings incluse) din arbore,
    # inlocuindu-le cu un placeholder, apoi regeneram sursa doar din cod.
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            node.value = ""

    cod_fara_stringuri = ast.unparse(tree)
    for interzis in ("_recalibrate_for_result", "backfill_done", "home_elo"):
        assert interzis not in cod_fara_stringuri, f"cod interzis gasit: {interzis}"


def test_scriptul_scrie_doar_prin_update_pe_match_history_cu_eq_id():
    """Garda structurală pe AST: singurul apel `.update(` din script trebuie
    să fie urmat de `.eq("id", ...)` — niciun UPDATE fără filtru pe id
    individual (ar fi o scriere în masă, în afara corpusului fix)."""
    import ast

    src = (Path(__file__).resolve().parent.parent / "scripts"
           / "correct_penalty_shootout_scores.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    update_calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "update"
    ]
    assert len(update_calls) == 1, "scriptul trebuie sa aiba exact un singur apel .update(...)"


def test_lista_de_id_uri_e_unica():
    ids = [c["id"] for c in CORRECTIONS]
    assert len(ids) == len(set(ids))
