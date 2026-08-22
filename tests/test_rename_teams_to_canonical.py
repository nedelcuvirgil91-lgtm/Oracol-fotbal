"""Teste pentru scripts/rename_teams_to_canonical.py — redenumirea supervizată
la forma canonică (ADR-060, Faza 2b).

`plan_renames()` e pură, reutilizează `classify()` din analiza D2 (nu o
reimplementare paralelă) și e testată pe un vocabular mic, sintetic.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rename_teams_to_canonical import plan_renames  # noqa: E402

_VOCAB = {
    "Liverpool FC (ENG)": "Liverpool",
    "AC Milan (ITA)": "AC Milan",
    "Almere City FC": "Almere City FC",  # deja canonic (alias -> el insusi)
    "Almere City": "Almere City FC",
}


def _norm(name: str) -> str:
    return _VOCAB.get(name, name)


def _row(rid, home, away, kd="2026-01-01"):
    return {"id": rid, "home_team": home, "away_team": away, "kickoff_date": kd}


def test_rand_fara_nume_fragmentat_nu_e_in_plan():
    rows = [_row(1, "Liverpool", "Arsenal")]
    plan = plan_renames(rows, _norm)
    assert plan["updates"] == []


def test_rand_cu_nume_fragmentat_e_in_plan():
    rows = [_row(1, "Liverpool FC (ENG)", "Arsenal")]
    plan = plan_renames(rows, _norm)
    assert len(plan["updates"]) == 1
    rid, oh, oa, nh, na = plan["updates"][0]
    assert (rid, oh, oa, nh, na) == (1, "Liverpool FC (ENG)", "Arsenal", "Liverpool", "Arsenal")


def test_ambele_parti_fragmentate_produc_un_singur_update():
    rows = [_row(1, "Liverpool FC (ENG)", "AC Milan (ITA)")]
    plan = plan_renames(rows, _norm)
    assert len(plan["updates"]) == 1
    _, _, _, nh, na = plan["updates"][0]
    assert nh == "Liverpool" and na == "AC Milan"


def test_coliziune_exclude_ambele_randuri_din_plan():
    """Daca redenumirea a doua randuri diferite ar produce aceeasi cheie,
    NICIUNUL nu se redenumeste — decizie de reconciliere, nu de redenumire."""
    rows = [
        _row(1, "Liverpool FC (ENG)", "Arsenal"),
        _row(2, "Liverpool", "Arsenal"),
    ]
    plan = plan_renames(rows, _norm)
    assert plan["updates"] == []
    assert set(plan["excluded_ids"]) == {1, 2}


def test_randuri_fara_coliziune_raman_in_plan_chiar_daca_altele_sunt_excluse():
    rows = [
        _row(1, "Liverpool FC (ENG)", "Arsenal"),
        _row(2, "Liverpool", "Arsenal"),
        _row(3, "AC Milan (ITA)", "Chelsea"),
    ]
    plan = plan_renames(rows, _norm)
    ids_in_plan = {u[0] for u in plan["updates"]}
    assert ids_in_plan == {3}
    assert set(plan["excluded_ids"]) == {1, 2}


def test_plan_e_gol_pentru_lista_goala():
    plan = plan_renames([], _norm)
    assert plan["updates"] == []
    assert plan["excluded_ids"] == []


def test_nume_deja_canonic_nu_produce_update_fals():
    """'Almere City FC' normalizeaza la el insusi — nu trebuie sa apara in
    plan doar fiindca e cheie in vocabular."""
    rows = [_row(1, "Almere City FC", "Arsenal")]
    plan = plan_renames(rows, _norm)
    assert plan["updates"] == []


def test_scriptul_scrie_doar_prin_update_cu_eq_id_si_valori_vechi():
    """Garda structurala: singurul apel .update( PE TABELA DIN SUPABASE
    (nu `set.update(...)`, folosit in altă parte pentru `excluded_ids`)
    trebuie sa existe o singura data."""
    import ast

    src = (Path(__file__).resolve().parent.parent / "scripts"
           / "rename_teams_to_canonical.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    def chain_has_table_call(node: ast.AST) -> bool:
        """True daca lantul de apeluri (node.func.value.func.value...)
        contine undeva un apel `.table(...)` — semnul unei scrieri Supabase,
        nu al unei operatii pe o structura Python locala."""
        cur = node
        for _ in range(10):
            if isinstance(cur, ast.Call) and isinstance(cur.func, ast.Attribute):
                if cur.func.attr == "table":
                    return True
                cur = cur.func.value
            elif isinstance(cur, ast.Attribute):
                cur = cur.value
            else:
                return False
        return False

    update_calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "update"
        and chain_has_table_call(node.func.value)
    ]
    assert len(update_calls) == 1
