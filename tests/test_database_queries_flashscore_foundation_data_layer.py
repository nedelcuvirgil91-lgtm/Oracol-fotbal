"""Teste pentru database.queries — persist() layer Foundation Data Layer
Flashscore (migratia 035/036): upsert_match_and_get_id, upsert_match_
statistics_extended, upsert_player_roster, upsert_player_match_stats_
extended, upsert_match_context, upsert_standings_snapshot.

Verifică proprietățile cerute explicit (M0 + Foundation Data Layer):
(1) fiecare upsert scrie prin `on_conflict` EXACT cheia UNIQUE reală a
    tabelei (migratia 035) — idempotența e garantată la nivel Postgres,
    testul verifică doar că se folosește cheia corectă;
(2) `upsert_match_and_get_id` returnează id-ul rezolvat (insert/update),
    None la hard_conflict sau client absent;
(3) `upsert_player_match_stats_extended` exclude explicit rândurile fără
    echipă rezolvată (nu ghicește);
(4) degradare fără excepție la client absent / eroare de rețea.

Fără rețea live."""
from __future__ import annotations

import database.queries as q


class _FakeRpcResult:
    def __init__(self, data):
        self.data = data


class _FakeRpc:
    def __init__(self, fn, params, sink, response_data):
        self.fn = fn
        self.params = params
        self.sink = sink
        self.response_data = response_data

    def execute(self):
        self.sink.append(("rpc", self.fn, self.params))
        return _FakeRpcResult(self.response_data)


class _FakeUpsertQuery:
    def __init__(self, table_name, calls, id_seq):
        self.table_name = table_name
        self.calls = calls
        self.id_seq = id_seq
        self._payload = None
        self._on_conflict = None

    def upsert(self, payload, on_conflict=None):
        self.calls.append((self.table_name, "upsert", payload, on_conflict))
        self._payload = payload
        self._on_conflict = on_conflict
        return self

    def execute(self):
        if isinstance(self._payload, list):
            rows = [{**r, "id": next(self.id_seq)} for r in self._payload]
        else:
            rows = [{**self._payload, "id": next(self.id_seq)}]
        return _FakeRpcResult(rows)


class _FakeClient:
    def __init__(self, rpc_response=None):
        self.calls: list = []
        self._rpc_response = rpc_response if rpc_response is not None else {"action": "insert", "id": 999}
        self._id_seq = iter(range(1, 100000))

    def rpc(self, fn, params):
        return _FakeRpc(fn, params, self.calls, self._rpc_response)

    def table(self, name):
        return _FakeUpsertQuery(name, self.calls, self._id_seq)


class _BoomClient:
    def rpc(self, fn, params):
        raise RuntimeError("simulated network failure")

    def table(self, name):
        raise RuntimeError("simulated network failure")


# ════════════════════════════════════════════════════════════════════════
# upsert_match_and_get_id
# ════════════════════════════════════════════════════════════════════════

def test_upsert_match_and_get_id_returns_id_on_insert(monkeypatch):
    fake = _FakeClient(rpc_response={"action": "insert", "id": 42})
    monkeypatch.setattr(q, "get_client", lambda: fake)
    row = {"home_team": "A", "away_team": "B", "kickoff_date": "2026-07-25T18:00:00"}
    assert q.upsert_match_and_get_id(row) == 42


def test_upsert_match_and_get_id_returns_none_on_hard_conflict(monkeypatch):
    fake = _FakeClient(rpc_response={"action": "hard_conflict", "id": 42})
    monkeypatch.setattr(q, "get_client", lambda: fake)
    row = {"home_team": "A", "away_team": "B", "kickoff_date": "2026-07-25T18:00:00"}
    assert q.upsert_match_and_get_id(row) is None


def test_upsert_match_and_get_id_returns_none_when_client_unavailable(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: None)
    row = {"home_team": "A", "away_team": "B", "kickoff_date": "2026-07-25T18:00:00"}
    assert q.upsert_match_and_get_id(row) is None


def test_upsert_match_and_get_id_degrades_gracefully_on_exception(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: _BoomClient())
    row = {"home_team": "A", "away_team": "B", "kickoff_date": "2026-07-25T18:00:00"}
    assert q.upsert_match_and_get_id(row) is None


# ════════════════════════════════════════════════════════════════════════
# upsert_match_statistics_extended
# ════════════════════════════════════════════════════════════════════════

def test_upsert_match_statistics_extended_correct_conflict_key(monkeypatch):
    fake = _FakeClient()
    monkeypatch.setattr(q, "get_client", lambda: fake)
    rows = [{"stat_key": "big_chances", "stat_label": "Big chances",
             "home_value_raw": "6", "away_value_raw": "2",
             "home_value_numeric": 6.0, "away_value_numeric": 2.0, "source": "flashscore"}]
    assert q.upsert_match_statistics_extended(999, rows) is True
    call = next(c for c in fake.calls if c[0] == "match_statistics_extended")
    assert call[3] == "match_id,stat_key"
    assert call[2][0]["match_id"] == 999


def test_upsert_match_statistics_extended_empty_rows_no_call(monkeypatch):
    fake = _FakeClient()
    monkeypatch.setattr(q, "get_client", lambda: fake)
    assert q.upsert_match_statistics_extended(999, []) is True
    assert fake.calls == []


def test_upsert_match_statistics_extended_degrades_gracefully(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: _BoomClient())
    assert q.upsert_match_statistics_extended(999, [{"stat_key": "x"}]) is False


# ════════════════════════════════════════════════════════════════════════
# upsert_player_roster
# ════════════════════════════════════════════════════════════════════════

def test_upsert_player_roster_correct_conflict_key_and_payload_shape(monkeypatch):
    fake = _FakeClient()
    monkeypatch.setattr(q, "get_client", lambda: fake)
    roster = [{"team": "home", "player_name": "Pop A.", "shirt_number": 7, "source": "flashscore"}]
    assert q.upsert_player_roster(999, roster) is True
    call = next(c for c in fake.calls if c[0] == "player_match_stats")
    assert call[3] == "match_id,team,player_name"
    payload = call[2][0]
    assert payload["match_id"] == 999
    assert payload["team"] == "home"
    assert "position" not in payload
    assert "rating" not in payload


def test_upsert_player_roster_empty_no_call(monkeypatch):
    fake = _FakeClient()
    monkeypatch.setattr(q, "get_client", lambda: fake)
    assert q.upsert_player_roster(999, []) is True
    assert fake.calls == []


# ════════════════════════════════════════════════════════════════════════
# upsert_player_match_stats_extended
# ════════════════════════════════════════════════════════════════════════

def _stat_row(team="home"):
    return {
        "player_name": "Pop A.", "position": "Striker", "rating": 8.7, "team": team,
        "extended_stats": [
            {"stat_key": "total_shots", "stat_label": "Total shots", "value_raw": "4", "value_numeric": 4.0},
        ],
    }


def test_upsert_player_match_stats_extended_writes_enrichment_then_eav(monkeypatch):
    fake = _FakeClient()
    monkeypatch.setattr(q, "get_client", lambda: fake)
    ok = q.upsert_player_match_stats_extended(999, [_stat_row()])
    assert ok is True
    enrich_call = next(c for c in fake.calls if c[0] == "player_match_stats")
    assert enrich_call[3] == "match_id,team,player_name"
    assert enrich_call[2]["position"] == "Striker"
    assert enrich_call[2]["rating"] == 8.7
    eav_call = next(c for c in fake.calls if c[0] == "player_match_stats_extended")
    assert eav_call[3] == "player_match_stats_id,stat_key"
    assert eav_call[2][0]["stat_key"] == "total_shots"
    assert eav_call[2][0]["player_match_stats_id"] is not None


def test_upsert_player_match_stats_extended_excludes_rows_without_team(monkeypatch):
    fake = _FakeClient()
    monkeypatch.setattr(q, "get_client", lambda: fake)
    row_no_team = _stat_row(team=None)
    ok = q.upsert_player_match_stats_extended(999, [row_no_team])
    assert ok is False
    assert fake.calls == []


def test_upsert_player_match_stats_extended_empty_no_call(monkeypatch):
    fake = _FakeClient()
    monkeypatch.setattr(q, "get_client", lambda: fake)
    assert q.upsert_player_match_stats_extended(999, []) is True
    assert fake.calls == []


# ════════════════════════════════════════════════════════════════════════
# upsert_match_context / upsert_standings_snapshot
# ════════════════════════════════════════════════════════════════════════

def test_upsert_match_context_correct_conflict_key(monkeypatch):
    fake = _FakeClient()
    monkeypatch.setattr(q, "get_client", lambda: fake)
    rows = [{"context_match_id": 999, "category": "h2h_overall", "meeting_order": 0,
             "home_team": "A", "away_team": "B"}]
    assert q.upsert_match_context(rows) is True
    call = next(c for c in fake.calls if c[0] == "flashscore_match_context")
    assert call[3] == "context_match_id,category,meeting_order"


def test_upsert_standings_snapshot_correct_conflict_key(monkeypatch):
    fake = _FakeClient()
    monkeypatch.setattr(q, "get_client", lambda: fake)
    rows = [{"competition": "SuperLiga", "team": "FCSB", "rank": 1}]
    assert q.upsert_standings_snapshot(rows) is True
    call = next(c for c in fake.calls if c[0] == "flashscore_standings_snapshot")
    assert call[3] == "competition,team"


def test_upsert_match_context_degrades_gracefully(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: _BoomClient())
    assert q.upsert_match_context([{"context_match_id": 1}]) is False


def test_upsert_standings_snapshot_degrades_gracefully(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: _BoomClient())
    assert q.upsert_standings_snapshot([{"competition": "X", "team": "Y"}]) is False


# ════════════════════════════════════════════════════════════════════════
# upsert_raw_extraction — stratul RAW al Data Trust Layer (migratia 035)
# ════════════════════════════════════════════════════════════════════════

def test_upsert_raw_extraction_correct_conflict_key_and_payload(monkeypatch):
    fake = _FakeClient()
    monkeypatch.setattr(q, "get_client", lambda: fake)
    ok = q.upsert_raw_extraction(
        "dinamo_univ_craiova_2026-07-25", "stats", {"home_team": "Dinamo Bucuresti"},
        validation_status="valid", canonical_written=True,
    )
    assert ok is True
    call = next(c for c in fake.calls if c[0] == "flashscore_raw_extraction")
    assert call[3] == "match_ref,tab_name"
    payload = call[2]
    assert payload["match_ref"] == "dinamo_univ_craiova_2026-07-25"
    assert payload["tab_name"] == "stats"
    assert payload["validation_status"] == "valid"
    assert payload["canonical_written"] is True


def test_upsert_raw_extraction_empty_raw_no_call(monkeypatch):
    fake = _FakeClient()
    monkeypatch.setattr(q, "get_client", lambda: fake)
    assert q.upsert_raw_extraction("ref", "stats", {}) is True
    assert fake.calls == []


def test_upsert_raw_extraction_degrades_gracefully(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: _BoomClient())
    assert q.upsert_raw_extraction("ref", "stats", {"x": 1}) is False


# ════════════════════════════════════════════════════════════════════════
# upsert_data_completeness — Data Completeness Score (migratia 037)
# ════════════════════════════════════════════════════════════════════════

def test_upsert_data_completeness_correct_conflict_key_and_payload(monkeypatch):
    fake = _FakeClient()
    monkeypatch.setattr(q, "get_client", lambda: fake)
    completeness = {
        "summary": True, "stats": True, "lineups": True, "player_stats": True,
        "odds": True, "h2h": True, "standings": True, "coverage_percent": 100.0,
    }
    ok = q.upsert_data_completeness("dinamo_craiova_2026-07-25", 123, completeness)
    assert ok is True
    call = next(c for c in fake.calls if c[0] == "flashscore_data_completeness")
    assert call[3] == "match_ref"
    payload = call[2]
    assert payload["match_ref"] == "dinamo_craiova_2026-07-25"
    assert payload["match_id"] == 123
    assert payload["has_summary"] is True
    assert payload["has_odds"] is True
    assert payload["coverage_percent"] == 100.0


def test_upsert_data_completeness_handles_none_match_id(monkeypatch):
    fake = _FakeClient()
    monkeypatch.setattr(q, "get_client", lambda: fake)
    ok = q.upsert_data_completeness("ref-invalid", None, {"coverage_percent": 0.0})
    assert ok is True
    call = next(c for c in fake.calls if c[0] == "flashscore_data_completeness")
    assert call[2]["match_id"] is None
    assert call[2]["has_summary"] is False


def test_upsert_data_completeness_degrades_gracefully(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: _BoomClient())
    assert q.upsert_data_completeness("ref", 1, {"coverage_percent": 0.0}) is False


# ════════════════════════════════════════════════════════════════════════
# season (migratia 038) - propagat DOAR daca e furnizat explicit, niciodata
# dedus - "Raspuns oficial - Foundation Data Layer (clarificari finale)"
# ════════════════════════════════════════════════════════════════════════

def test_upsert_player_roster_includes_season_when_given(monkeypatch):
    fake = _FakeClient()
    monkeypatch.setattr(q, "get_client", lambda: fake)
    roster = [{"team": "home", "player_name": "Pop A.", "shirt_number": 7}]
    q.upsert_player_roster(999, roster, season="2026-2027")
    call = next(c for c in fake.calls if c[0] == "player_match_stats")
    assert call[2][0]["season"] == "2026-2027"


def test_upsert_player_roster_season_defaults_to_none(monkeypatch):
    fake = _FakeClient()
    monkeypatch.setattr(q, "get_client", lambda: fake)
    roster = [{"team": "home", "player_name": "Pop A.", "shirt_number": 7}]
    q.upsert_player_roster(999, roster)
    call = next(c for c in fake.calls if c[0] == "player_match_stats")
    assert call[2][0]["season"] is None


def test_upsert_player_match_stats_extended_includes_season_when_given(monkeypatch):
    fake = _FakeClient()
    monkeypatch.setattr(q, "get_client", lambda: fake)
    q.upsert_player_match_stats_extended(999, [_stat_row()], season="2026-2027")
    enrich_call = next(c for c in fake.calls if c[0] == "player_match_stats")
    assert enrich_call[2]["season"] == "2026-2027"
    eav_call = next(c for c in fake.calls if c[0] == "player_match_stats_extended")
    assert eav_call[2][0]["season"] == "2026-2027"


def test_upsert_raw_extraction_includes_season_when_given(monkeypatch):
    fake = _FakeClient()
    monkeypatch.setattr(q, "get_client", lambda: fake)
    q.upsert_raw_extraction("ref", "stats", {"home_team": "A"}, season="2026-2027")
    call = next(c for c in fake.calls if c[0] == "flashscore_raw_extraction")
    assert call[2]["season"] == "2026-2027"


def test_upsert_data_completeness_includes_season_when_given(monkeypatch):
    fake = _FakeClient()
    monkeypatch.setattr(q, "get_client", lambda: fake)
    q.upsert_data_completeness("ref", 1, {"coverage_percent": 100.0}, season="2026-2027")
    call = next(c for c in fake.calls if c[0] == "flashscore_data_completeness")
    assert call[2]["season"] == "2026-2027"
