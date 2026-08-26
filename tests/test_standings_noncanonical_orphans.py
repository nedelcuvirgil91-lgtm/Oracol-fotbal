"""Clasa 6 din `check_data_health`: rânduri de clasament sub formă NEcanonică.

CONTEXT. Găsită pe date reale (2026-08-26), ca efect secundar al reîmprospătării
`captured_at`: 19 rânduri orfane în `flashscore_standings_snapshot`, aceeași
echipă sub două nume — „Heerenveen" lângă „SC Heerenveen", „Atl. Madrid" lângă
„Atletico Madrid", „Nottingham" lângă „Nottingham Forest".

Scrise ÎNAINTE de fixul de normalizare din 2026-08-15. `UNIQUE(competition,
team)` le ține ca echipe diferite, deci rândul vechi nu se rescrie niciodată în
loc — rămâne fantomă, cu cifre înghețate în trecut. După curățare, numărătorile
au confirmat mărimile reale ale ligilor (Serie A 20, Ligue 1 18, SuperLiga 16).

DE CE MONITORIZARE, NU DOAR CURĂȚARE: clasa se poate reactiva oricând se ADAUGĂ
un alias nou — o formă azi canonică devine mâine alias, iar rândul ei existent
devine instant orfan. Curățarea rezolvă instanțele; detectorul rezolvă clasa.

Fără rețea, fără Supabase — invariant pur.
"""
from __future__ import annotations

from mappings import normalize_team_name


def _orfane(randuri: list[dict]) -> list[dict]:
    """Replica exactă a invariantului din `check_data_health`, clasa 6."""
    return [
        r for r in randuri
        if r.get("team") and normalize_team_name(r["team"]) != r["team"]
    ]


def _r(team, comp="Eredivisie", rid=1):
    return {"id": rid, "competition": comp, "team": team}


# ── invariantul de bază ──────────────────────────────────────────────────────

def test_forma_canonica_nu_e_semnalata():
    """Contrapondere: formele corecte nu au voie să producă zgomot."""
    for nume in ("SC Heerenveen", "Atletico Madrid", "Nottingham Forest",
                 "FC Barcelona", "Real Madrid", "FCSB"):
        assert _orfane([_r(nume)]) == [], f"{nume!r} e canonic, nu orfan"


def test_formele_reale_gasite_in_productie_sunt_prinse():
    """CAZURILE REALE, toate cele 19 verificate pe producție 2026-08-26."""
    vechi = ["Groningen", "Utrecht", "Sittard", "Zwolle", "Excelsior",
             "Heerenveen", "Telstar", "Leuven", "Atl. Madrid", "Nottingham",
             "Nacional", "Santa Clara", "Estrela", "Casa Pia", "Arouca",
             "Famalicao", "Moreirense", "Rio Ave", "Goztepe"]
    prinse = _orfane([_r(n, rid=i) for i, n in enumerate(vechi)])
    assert len(prinse) == len(vechi), (
        f"nu toate formele necanonice reale sunt prinse: "
        f"{set(vechi) - {p['team'] for p in prinse}}"
    )


def test_fiecare_orfan_converge_la_o_forma_canonica_diferita():
    """Garanția că semnalul e acționabil: orfanul are unde să fie unificat."""
    for nume in ("Heerenveen", "Atl. Madrid", "Nottingham"):
        canonic = normalize_team_name(nume)
        assert canonic != nume
        assert normalize_team_name(canonic) == canonic, (
            f"{canonic!r} trebuie sa fie punct fix — altfel harta e inconsistenta"
        )


# ── degradare ────────────────────────────────────────────────────────────────

def test_lista_goala():
    assert _orfane([]) == []


def test_rand_fara_nume_nu_arunca():
    assert _orfane([{"id": 1, "competition": "X", "team": None}]) == []
    assert _orfane([{"id": 1, "competition": "X", "team": ""}]) == []
    assert _orfane([{"id": 1, "competition": "X"}]) == []


# ── garda de cablare ─────────────────────────────────────────────────────────

def _arbore_main():
    import ast
    import inspect

    from scripts import check_data_health

    return ast.parse(inspect.getsource(check_data_health.main).strip())


def test_clasa_6_compara_efectiv_cu_forma_canonica():
    """GARDĂ, adăugată după ce o mutație a arătat că lipsea: testele de mai sus
    verifică o REPLICĂ a invariantului, deci rămân verzi chiar dacă filtrul din
    codul real devine `if False`. Aici se verifică expresia reală."""
    import ast

    arbore = _arbore_main()
    comparatii = [
        n for n in ast.walk(arbore)
        if isinstance(n, ast.Compare)
        and isinstance(n.ops[0], ast.NotEq)
        and any(
            isinstance(c, ast.Call) and getattr(c.func, "id", None) == "normalize_team_name"
            for c in ast.walk(n)
        )
    ]
    assert comparatii, (
        "clasa 6 trebuie sa compare `team` cu `normalize_team_name(team)` — "
        "fara comparatia reala, filtrul nu detecteaza nimic"
    )


def test_clasa_6_chiar_ridica_alarma():
    """A doua mutație neprinsă: `if orfane: findings += 1` poate fi neutralizat
    fără ca vreun test să cadă. Detectorul care nu alarmează nu e detector."""
    import ast

    arbore = _arbore_main()
    gardat = any(
        isinstance(n, ast.If)
        and getattr(n.test, "id", None) == "orfane"
        and any(
            isinstance(x, ast.AugAssign) and getattr(x.target, "id", None) == "findings"
            for x in ast.walk(n)
        )
        for n in ast.walk(arbore)
    )
    assert gardat, (
        "constatarile clasei 6 trebuie sa incrementeze `findings` sub `if orfane:`"
    )


def test_clasa_6_e_chiar_cablata_in_raport():
    """Fără asta, invariantul poate fi corect și totuși niciodată rulat —
    exact clasa de defect de la ADR-066 (extragere bună, fir netăiat)."""
    import inspect

    from scripts import check_data_health

    sursa = inspect.getsource(check_data_health.main)
    assert "flashscore_standings_snapshot" in sursa, "clasa 6 nu citeste tabela"
    assert "findings}/6" in sursa, "sumarul inca raporteaza 5 clase, nu 6"
