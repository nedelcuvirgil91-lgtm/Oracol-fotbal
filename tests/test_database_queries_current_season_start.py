"""Teste pentru `database.queries.get_current_season_start()` (ADR-066 P3).

Partea subtila a functiei e ORDINEA celor doi pasi:

  1. sezonul CELUI MAI RECENT MECI al ligii — nu eticheta maxima lexicografic
  2. prima zi a acelui sezon

Pasul 1 exista pentru ca `match_history.season` e fragmentat in doua formate
(`YYYY-YYYY`, 7.592 randuri, si `YYYY-YY`, 5.471 — ADR-066 §4). O comparatie
lexicografica intre formate diferite nu are sens garantat; „sezonul celui mai
recent meci" nu depinde de format deloc.

Fara retea, fara Supabase.
"""
from __future__ import annotations

import database.queries as q


class _Rezultat:
    def __init__(self, data):
        self.data = data


class _Interogare:
    """Retine filtrele si intoarce randul dictat de scenariu."""

    def __init__(self, scenariu: dict, jurnal: list):
        self._s = scenariu
        self._j = jurnal
        self._filtre: dict = {}

    def select(self, *a, **kw):
        self._j.append(("select", a[0] if a else None)); return self

    def eq(self, camp, valoare):
        self._filtre[camp] = valoare
        self._j.append(("eq", camp, valoare)); return self

    @property
    def not_(self):
        return self

    def is_(self, *a, **kw):
        self._j.append(("is_", a)); return self

    def order(self, camp, desc=False):
        self._j.append(("order", camp, desc))
        self._desc = desc
        return self

    def limit(self, n):
        self._j.append(("limit", n)); return self

    def execute(self):
        # Pasul 1 cere cel mai recent meci (desc=True); pasul 2 cere primul
        # meci al unui sezon deja ales (desc=False, cu `season` in filtre).
        if "season" in self._filtre:
            return _Rezultat(self._s.get("prima_zi", []))
        return _Rezultat(self._s.get("cel_mai_recent", []))


class _Client:
    def __init__(self, scenariu: dict):
        self._s = scenariu
        self.jurnal: list = []

    def table(self, nume):
        return _Interogare(self._s, self.jurnal)


def _pregateste(monkeypatch, scenariu: dict) -> _Client:
    c = _Client(scenariu)
    monkeypatch.setattr(q, "get_client", lambda: c)
    return c


# ── comportamentul de baza ───────────────────────────────────────────────────

def test_intoarce_prima_zi_a_sezonului_celui_mai_recent_meci(monkeypatch):
    _pregateste(monkeypatch, {
        "cel_mai_recent": [{"season": "2026-2026"}],
        "prima_zi": [{"kickoff_date": "2026-02-21T20:30:00"}],
    })
    assert q.get_current_season_start("MLS") == "2026-02-21"


def test_al_doilea_pas_filtreaza_pe_sezonul_gasit_la_primul(monkeypatch):
    """GARDA: fara acest filtru, pasul 2 ar intoarce prima zi din TOT
    istoricul ligii, nu din sezonul curent."""
    c = _pregateste(monkeypatch, {
        "cel_mai_recent": [{"season": "2026-2027"}],
        "prima_zi": [{"kickoff_date": "2026-07-17"}],
    })
    q.get_current_season_start("Romania SuperLiga")
    assert ("eq", "season", "2026-2027") in c.jurnal


def test_primul_pas_cere_cel_mai_recent_nu_eticheta_maxima(monkeypatch):
    """GARDA CENTRALA. Cu doua formate in coloana, `max(season)` lexicografic
    nu e sigur. Functia trebuie sa ordoneze dupa DATA, descrescator."""
    c = _pregateste(monkeypatch, {
        "cel_mai_recent": [{"season": "2025-26"}],
        "prima_zi": [{"kickoff_date": "2025-08-01"}],
    })
    q.get_current_season_start("Premier League")
    assert ("order", "kickoff_date", True) in c.jurnal, (
        "pasul 1 trebuie sa ordoneze dupa kickoff_date descrescator"
    )
    assert not any(j[0] == "order" and j[1] == "season" for j in c.jurnal), (
        "sezonul nu se alege prin ordonare lexicografica pe eticheta"
    )


def test_primul_pas_exclude_randurile_fara_sezon(monkeypatch):
    c = _pregateste(monkeypatch, {
        "cel_mai_recent": [{"season": "2026-2027"}],
        "prima_zi": [{"kickoff_date": "2026-07-17"}],
    })
    q.get_current_season_start("HNL")
    assert any(j[0] == "is_" for j in c.jurnal), "trebuie filtrate randurile cu season NULL"


# ── necunoscut ramane necunoscut ─────────────────────────────────────────────

def test_liga_fara_niciun_sezon_cunoscut_intoarce_none(monkeypatch):
    """Situatia REALA de azi: toate cele 1.058 de randuri Flashscore au
    season NULL. Apelantul cade pe pragul vechi, explicit (Regula #8)."""
    _pregateste(monkeypatch, {"cel_mai_recent": [], "prima_zi": []})
    assert q.get_current_season_start("MLS") is None


def test_sezon_gol_e_tratat_ca_necunoscut(monkeypatch):
    _pregateste(monkeypatch, {"cel_mai_recent": [{"season": None}], "prima_zi": []})
    assert q.get_current_season_start("MLS") is None


def test_sezon_gasit_dar_fara_prima_zi_intoarce_none(monkeypatch):
    _pregateste(monkeypatch, {"cel_mai_recent": [{"season": "2026-2027"}], "prima_zi": []})
    assert q.get_current_season_start("MLS") is None


# ── degradare ────────────────────────────────────────────────────────────────

def test_fara_client_intoarce_none(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: None)
    assert q.get_current_season_start("MLS") is None


def test_eroare_de_retea_nu_arunca(monkeypatch, caplog):
    class _Explodeaza:
        def table(self, nume):
            raise RuntimeError("conexiune pierduta")

    monkeypatch.setattr(q, "get_client", lambda: _Explodeaza())
    with caplog.at_level("WARNING"):
        assert q.get_current_season_start("MLS") is None
    assert "get_current_season_start" in caplog.text
