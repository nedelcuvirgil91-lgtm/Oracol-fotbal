"""Teste pentru invalidarea predicțiilor shadow (ADR-064).

CONTEXT: `shadow_predictions` nu avea NICIUN mecanism prin care un rând să fie
scos din evaluare — `evaluate_experiment()` filtra doar pe `processing_stage`
și `experiment_group`, iar `error_message` nu era citită niciodată.

Cazul care a expus golul (2026-08-23): o inversare de teren în extragerea
Flashscore a produs 5 rânduri cu `prob_home` atribuit echipei greșite.
Contaminarea nu e zgomot, ci semnal fals SISTEMATIC — evaluarea punctează
`predicted_outcome` contra `actual_result`, unde "H" înseamnă victoria gazdei
din `match_history`.

Fără rețea, fără Supabase — clientul e injectat.
"""
from __future__ import annotations

import pytest

import shadow_testing as st


class _Query:
    """Client Supabase fals, minimal: reține filtrele aplicate."""

    def __init__(self, sink: dict, rows: list | None = None):
        self.sink = sink
        self.rows = rows if rows is not None else []

    def select(self, *_a, **_k):
        return self

    def update(self, payload):
        self.sink["update_payload"] = payload
        return self

    def eq(self, col, val):
        self.sink.setdefault("eq", []).append((col, val))
        return self

    def is_(self, col, val):
        self.sink.setdefault("is_", []).append((col, val))
        return self

    def execute(self):
        return type("R", (), {"data": self.rows})()


class _Client:
    def __init__(self, sink: dict, rows: list | None = None):
        self.sink = sink
        self.rows = rows

    def table(self, name):
        self.sink["table"] = name
        return _Query(self.sink, self.rows)


# ── citire: excluderea implicită ─────────────────────────────────────────────

def test_citirea_exclude_implicit_randurile_invalidate(monkeypatch):
    """GARDA CENTRALĂ a ADR-064: fără acest filtru, o predicție inversată
    revine în evaluare la primul backfill al coloanelor de predicție."""
    sink: dict = {}
    monkeypatch.setattr(st.sb, "get_client", lambda: _Client(sink))

    st.get_shadow_predictions("blend_v1")

    assert ("invalidated_at", "null") in sink.get("is_", []), (
        "get_shadow_predictions() trebuie sa filtreze invalidated_at IS NULL"
    )


def test_include_invalidated_dezactiveaza_filtrul(monkeypatch):
    """Portiță explicită pentru audit — niciodată pentru evaluare."""
    sink: dict = {}
    monkeypatch.setattr(st.sb, "get_client", lambda: _Client(sink))

    st.get_shadow_predictions("blend_v1", include_invalidated=True)

    assert ("invalidated_at", "null") not in sink.get("is_", [])


def test_evaluarea_foloseste_calea_care_filtreaza(monkeypatch):
    """Cablare: `evaluate_experiment` trebuie să citească prin
    `get_shadow_predictions`, nu printr-o interogare proprie care ar ocoli
    filtrul. Verificat la nivel de sursă — calea completă cere Supabase."""
    import ast
    import inspect

    sursa = inspect.getsource(st.evaluate_experiment)
    arbore = ast.parse(sursa)
    apeluri = {
        getattr(n.func, "id", None)
        for n in ast.walk(arbore) if isinstance(n, ast.Call)
    }
    assert "get_shadow_predictions" in apeluri
    assert 'client.table("shadow_predictions")' not in sursa, (
        "evaluate_experiment() nu are voie sa interogheze direct tabela — "
        "ar ocoli filtrul de invalidare"
    )


# ── scriere: funcția de invalidare ───────────────────────────────────────────

def test_invalidarea_scrie_motivul_si_momentul(monkeypatch):
    sink: dict = {}
    monkeypatch.setattr(st.sb, "get_client", lambda: _Client(sink, rows=[{"id": 1}, {"id": 2}]))

    n = st.invalidate_shadow_predictions("flashscore_p2AX2W4D", "orientare inversata")

    assert n == 2
    payload = sink["update_payload"]
    assert payload["invalidation_reason"] == "orientare inversata"
    assert payload["invalidated_at"]
    assert ("fixture_id", "flashscore_p2AX2W4D") in sink["eq"]


def test_nu_re_marcheaza_randurile_deja_invalidate(monkeypatch):
    """Prima decizie ramane cea trasabila — motivul original nu se suprascrie."""
    sink: dict = {}
    monkeypatch.setattr(st.sb, "get_client", lambda: _Client(sink, rows=[]))

    st.invalidate_shadow_predictions("x", "motiv")

    assert ("invalidated_at", "null") in sink.get("is_", [])


def test_motiv_gol_e_refuzat(monkeypatch):
    """O invalidare fara motiv nu e trasabila (#9). Refuzata in cod, nu doar
    de constrangerea din baza de date — apelantul afla imediat."""
    monkeypatch.setattr(st.sb, "get_client", lambda: _Client({}))

    for motiv in ("", "   ", None):
        with pytest.raises(ValueError):
            st.invalidate_shadow_predictions("x", motiv)  # type: ignore[arg-type]


def test_fixture_id_gol_e_refuzat(monkeypatch):
    """Fara aceasta garda, `.eq("fixture_id", "")` ar putea invalida altceva
    decat s-a intentionat."""
    monkeypatch.setattr(st.sb, "get_client", lambda: _Client({}))

    with pytest.raises(ValueError):
        st.invalidate_shadow_predictions("", "motiv")


def test_supabase_indisponibil_nu_arunca(monkeypatch):
    """Degradare gratioasa, consecvent cu restul modulului."""
    monkeypatch.setattr(st.sb, "get_client", lambda: None)
    assert st.invalidate_shadow_predictions("x", "motiv") == 0


def test_eroare_de_scriere_nu_arunca(monkeypatch):
    class _Boom:
        def table(self, _n):
            raise RuntimeError("retea cazuta")

    monkeypatch.setattr(st.sb, "get_client", lambda: _Boom())
    assert st.invalidate_shadow_predictions("x", "motiv") == 0
