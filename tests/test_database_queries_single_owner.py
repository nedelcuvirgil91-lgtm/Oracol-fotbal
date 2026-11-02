"""Teste pentru functiile Single Owner adaugate in database.queries.py
(Pasul 1 Master Repair Plan, ADR-045): get_match_ids_with_complete_
flashscore_stats, get_flashscore_covered_standings_leagues,
has_flashscore_h2h_context, plus regresia pentru
get_finished_matches_missing_stats(include_id=...). Fara retea."""
from __future__ import annotations

import database.queries as q


class _FakeResult:
    def __init__(self, data):
        self.data = data


class _FakeQuery:
    def __init__(self, rows, calls, table_name):
        self._rows = rows
        self._calls = calls
        self._table_name = table_name

    def select(self, *a, **kw):
        self._calls.append((self._table_name, "select", a, kw)); return self

    def eq(self, *a, **kw):
        self._calls.append((self._table_name, "eq", a, kw)); return self

    def or_(self, *a, **kw):
        self._calls.append((self._table_name, "or_", a, kw)); return self

    def in_(self, *a, **kw):
        self._calls.append((self._table_name, "in_", a, kw)); return self

    def gte(self, *a, **kw):
        self._calls.append((self._table_name, "gte", a, kw)); return self

    @property
    def not_(self):
        return self

    def is_(self, *a, **kw):
        self._calls.append((self._table_name, "is_", a, kw)); return self

    def limit(self, *a, **kw):
        self._calls.append((self._table_name, "limit", a, kw)); return self

    def order(self, *a, **kw):
        self._calls.append((self._table_name, "order", a, kw)); return self

    def execute(self):
        return _FakeResult(self._rows)


class _FakeClient:
    def __init__(self, rows_by_table: dict[str, list[dict]]):
        self._rows_by_table = rows_by_table
        self.calls: list = []

    def table(self, name):
        return _FakeQuery(self._rows_by_table.get(name, []), self.calls, name)


class _BoomClient:
    def table(self, name):
        raise RuntimeError("simulated network failure")


# ════════════════════════════════════════════════════════════════════════
# get_match_ids_with_complete_flashscore_stats
# ════════════════════════════════════════════════════════════════════════

def test_get_match_ids_with_complete_flashscore_stats_returns_matching_ids(monkeypatch):
    """[ACTUALIZAT ADR-085 §4.2] Citea `flashscore_data_completeness.has_stats`;
    citește acum `match_history.home_shots IS NOT NULL`. Testul vechi afirma
    contractul VECHI, deci a trebuit schimbat — nu e o adaptare cosmetică."""
    fake = _FakeClient({"match_history": [{"id": 1}, {"id": 3}]})
    monkeypatch.setattr(q, "get_client", lambda: fake)
    result = q.get_match_ids_with_complete_flashscore_stats([1, 2, 3])
    assert result == {1, 3}


def test_poarta_single_owner_NU_mai_citeste_completeness(monkeypatch):
    """[ADR-085 §4.2] Garda centrală: un rând `flashscore_data_completeness`
    scris ÎNAINTE de meci (has_stats=true, coverage=100%) nu mai are voie să
    declare meciul acoperit. Toate cele 23 de meciuri din golul măsurat aveau
    exact un asemenea rând — unul scris pe 30 iulie pentru un meci din 31
    octombrie."""
    fake = _FakeClient({
        # completitudinea MINTE (rând de dinainte de meci), match_history e gol
        "flashscore_data_completeness": [{"match_id": 7}],
        "match_history": [],
    })
    monkeypatch.setattr(q, "get_client", lambda: fake)
    assert q.get_match_ids_with_complete_flashscore_stats([7]) == set()
    tabele = {c[0] for c in fake.calls}
    assert "flashscore_data_completeness" not in tabele, (
        f"poarta citește încă tabela de completitudine: {fake.calls}")
    assert "match_history" in tabele


def test_poarta_single_owner_filtreaza_pe_home_shots_nenul(monkeypatch):
    """Contrapondere la testul de mai sus: nu e suficient să NU citească
    tabela greșită — trebuie să aplice efectiv filtrul corect. Fără asta,
    o implementare care citește `match_history` fără niciun filtru ar trece."""
    fake = _FakeClient({"match_history": [{"id": 1}]})
    monkeypatch.setattr(q, "get_client", lambda: fake)
    q.get_match_ids_with_complete_flashscore_stats([1])
    assert ("match_history", "is_", ("home_shots", "null"), {}) in fake.calls, (
        f"filtrul pe coloana-țintă lipsește: {fake.calls}")


def test_poarta_single_owner_pastreaza_chunk_uirea_la_500(monkeypatch):
    """[ADR-077 §2.2] Chunk-uirea nu are voie să se piardă la schimbarea de
    tabelă — `.in_()` pe `match_history.id` are exact același plafon PostgREST
    de 1000. A cincea instanță a clasei, reparată preventiv acolo; aici se
    păzește să nu fie anulată din neatenție."""
    fake = _FakeClient({"match_history": []})
    monkeypatch.setattr(q, "get_client", lambda: fake)
    q.get_match_ids_with_complete_flashscore_stats(list(range(1, 1201)))
    bucati = [c[2][1] for c in fake.calls if c[1] == "in_"]
    assert [len(b) for b in bucati] == [500, 500, 200], (
        f"chunk-uirea s-a pierdut: {[len(b) for b in bucati]}")


def test_get_match_ids_with_complete_flashscore_stats_empty_input_no_query(monkeypatch):
    fake = _FakeClient({})
    monkeypatch.setattr(q, "get_client", lambda: fake)
    assert q.get_match_ids_with_complete_flashscore_stats([]) == set()
    assert fake.calls == []


def test_get_match_ids_with_complete_flashscore_stats_no_client(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: None)
    assert q.get_match_ids_with_complete_flashscore_stats([1, 2]) == set()


def test_get_match_ids_with_complete_flashscore_stats_network_error_returns_empty(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: _BoomClient())
    assert q.get_match_ids_with_complete_flashscore_stats([1]) == set()


# ════════════════════════════════════════════════════════════════════════
# get_flashscore_covered_standings_leagues
# ════════════════════════════════════════════════════════════════════════

def test_get_flashscore_covered_standings_leagues_returns_distinct_names(monkeypatch):
    fake = _FakeClient({"flashscore_standings_snapshot": [
        {"competition": "Premier League"}, {"competition": "Premier League"},
        {"competition": "Romania SuperLiga"},
    ]})
    monkeypatch.setattr(q, "get_client", lambda: fake)
    result = q.get_flashscore_covered_standings_leagues()
    assert result == {"Premier League", "Romania SuperLiga"}


def test_get_flashscore_covered_standings_leagues_no_client(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: None)
    assert q.get_flashscore_covered_standings_leagues() == set()


def test_get_flashscore_covered_standings_leagues_network_error_returns_empty(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: _BoomClient())
    assert q.get_flashscore_covered_standings_leagues() == set()


# ════════════════════════════════════════════════════════════════════════
# has_flashscore_h2h_context
# ════════════════════════════════════════════════════════════════════════

def test_has_flashscore_h2h_context_true_when_context_exists(monkeypatch):
    fake = _FakeClient({
        "match_history": [{"id": 42}],
        "flashscore_match_context": [{"id": 7}],
    })
    monkeypatch.setattr(q, "get_client", lambda: fake)
    assert q.has_flashscore_h2h_context("Team A", "Team B") is True


def test_has_flashscore_h2h_context_false_when_no_matching_pair(monkeypatch):
    fake = _FakeClient({"match_history": [], "flashscore_match_context": []})
    monkeypatch.setattr(q, "get_client", lambda: fake)
    assert q.has_flashscore_h2h_context("Team A", "Team B") is False


def test_has_flashscore_h2h_context_false_when_pair_exists_but_no_context(monkeypatch):
    fake = _FakeClient({
        "match_history": [{"id": 42}],
        "flashscore_match_context": [],
    })
    monkeypatch.setattr(q, "get_client", lambda: fake)
    assert q.has_flashscore_h2h_context("Team A", "Team B") is False


def test_has_flashscore_h2h_context_no_client(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: None)
    assert q.has_flashscore_h2h_context("Team A", "Team B") is False


def test_has_flashscore_h2h_context_network_error_returns_false(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: _BoomClient())
    assert q.has_flashscore_h2h_context("Team A", "Team B") is False


# ════════════════════════════════════════════════════════════════════════
# get_finished_matches_missing_stats(include_id=...) — regresie
# ════════════════════════════════════════════════════════════════════════

def test_get_finished_matches_missing_stats_default_excludes_id(monkeypatch):
    fake = _FakeClient({"match_history": [{"home_team": "A", "away_team": "B"}]})
    monkeypatch.setattr(q, "get_client", lambda: fake)
    q.get_finished_matches_missing_stats(days_back=2)
    select_calls = [c for c in fake.calls if c[1] == "select"]
    assert select_calls[0][2] == ("home_team,away_team,kickoff_date,league",)


def test_get_finished_matches_missing_stats_include_id_adds_id_column(monkeypatch):
    fake = _FakeClient({"match_history": [{"id": 1, "home_team": "A", "away_team": "B"}]})
    monkeypatch.setattr(q, "get_client", lambda: fake)
    q.get_finished_matches_missing_stats(days_back=2, include_id=True)
    select_calls = [c for c in fake.calls if c[1] == "select"]
    assert select_calls[0][2] == ("id,home_team,away_team,kickoff_date,league",)
