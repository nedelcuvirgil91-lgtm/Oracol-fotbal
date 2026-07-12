"""Teste pentru diagnostics_api_football.py — sondaj discovery pentru
/fixtures/statistics, fără rețea reală (mock pe requests.get), fără
Supabase (cache fals, în memorie). Verifică: parsare fericită, degradare
grațioasă la fiecare pas (fără cheie, eșec HTTP la fiecare etapă, structură
neașteptată), oprire onestă fără pași inventați, ȘI optimizarea de quota —
cache pentru team_id/fixture_id/verdict 403-404, astfel încât o verificare
repetată să coste 1 apel sau 0, nu 3."""
from __future__ import annotations

import json

import diagnostics_api_football as daf


class _FakeResp:
    def __init__(self, status_code=200, json_body=None, text=None):
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self._json_body = json_body
        self.text = text if text is not None else (json.dumps(json_body) if json_body is not None else "")

    def json(self):
        if self._json_body is None:
            raise ValueError("no json body")
        return self._json_body


class _FakeKeyManager:
    def __init__(self, available=True):
        self._available = available
        self.recorded = 0

    def is_available(self, provider):
        return self._available

    def get_headers(self, provider):
        return {"x-apisports-key": "fake"}

    def record_request(self, provider):
        self.recorded += 1


class _FakeCache:
    """Cache în memorie, izolat per test — nu atinge disc sau Supabase."""
    def __init__(self, seed: dict | None = None):
        self._store: dict[tuple[str, str], object] = dict(seed or {})
        self.set_calls: list[tuple[str, str, object]] = []

    def get_raw(self, category, key):
        return self._store.get((category, key))

    def set(self, category, key, data, provider="unknown"):
        self._store[(category, key)] = data
        self.set_calls.append((category, key, data))
        return True


TEAMS_OK = {"response": [{"team": {"id": 42, "name": "Arsenal"}}]}
FIXTURES_OK = {"response": [{
    "fixture": {"id": 999, "date": "2026-07-01T18:00:00+00:00"},
    "teams": {"home": {"name": "Arsenal"}, "away": {"name": "Chelsea"}},
}]}
STATS_FULL = {"response": [
    {"team": {"id": 42}, "statistics": [
        {"type": "Ball Possession", "value": "55%"},
        {"type": "Total Shots", "value": 14},
        {"type": "Shots on Goal", "value": 6},
        {"type": "Corner Kicks", "value": 5},
        {"type": "Yellow Cards", "value": 2},
        {"type": "Red Cards", "value": 0},
        {"type": "Fouls", "value": 10},
        {"type": "Something Unrecognized", "value": 1},
    ]},
    {"team": {"id": 49}, "statistics": [
        {"type": "Ball Possession", "value": "45%"},
    ]},
]}
STATS_MISSING_SOME = {"response": [
    {"team": {"id": 42}, "statistics": [
        {"type": "Ball Possession", "value": "55%"},
        {"type": "Total Shots", "value": 14},
    ]},
]}


def _fake_get(responses: dict[str, _FakeResp], calls: list):
    def fake_get(url, headers=None, params=None, timeout=12):
        calls.append(url)
        for suffix, resp in responses.items():
            if url == f"{daf.BASE_URL}/{suffix}":
                return resp
        raise AssertionError(f"apel HTTP neașteptat, nemockuit: {url}")
    return fake_get


def test_probe_league_happy_path_all_fields_found(monkeypatch):
    calls: list = []
    monkeypatch.setattr(daf.requests, "get", _fake_get({
        "teams": _FakeResp(200, TEAMS_OK),
        "fixtures": _FakeResp(200, FIXTURES_OK),
        "fixtures/statistics": _FakeResp(200, STATS_FULL),
    }, calls))

    km = _FakeKeyManager()
    result = daf.probe_league("Premier League", "Arsenal", key_manager=km, cache=_FakeCache())

    assert result.verdict == "ok"
    assert result.team_id == 42
    assert result.fixture_id == 999
    assert result.home_team == "Arsenal" and result.away_team == "Chelsea"
    found = {fc.label: fc.found for fc in result.field_checks}
    assert found["possession"] and found["shots"] and found["shots_on_target"]
    assert found["corners"] and found["yellow_cards"] and found["fouls"]
    assert found["red_cards"]  # value 0, dar tipul EXISTĂ -> found trebuie True
    assert found["xG"] is False  # nu apare deloc în răspuns
    assert "Something Unrecognized" in result.all_raw_types_found  # transparență totală
    assert km.recorded == 3
    assert len(calls) == 3


def test_probe_league_missing_some_fields_reported_honestly(monkeypatch):
    calls: list = []
    monkeypatch.setattr(daf.requests, "get", _fake_get({
        "teams": _FakeResp(200, TEAMS_OK),
        "fixtures": _FakeResp(200, FIXTURES_OK),
        "fixtures/statistics": _FakeResp(200, STATS_MISSING_SOME),
    }, calls))

    result = daf.probe_league("Premier League", "Arsenal", key_manager=_FakeKeyManager(), cache=_FakeCache())

    assert result.verdict == "ok"
    found = {fc.label: fc.found for fc in result.field_checks}
    assert found["possession"] and found["shots"]
    assert found["corners"] is False and found["xG"] is False and found["fouls"] is False


def test_probe_league_no_key_configured_makes_zero_http_calls(monkeypatch):
    def fail_get(*a, **kw):
        raise AssertionError("nu ar trebui făcut niciun apel HTTP fără cheie")
    monkeypatch.setattr(daf.requests, "get", fail_get)

    result = daf.probe_league("Premier League", "Arsenal",
                               key_manager=_FakeKeyManager(available=False), cache=_FakeCache())

    assert result.verdict == "fara_cheie"
    assert result.resolve_team_probe is None


def test_probe_league_statistics_403_reports_plan_message(monkeypatch):
    calls: list = []
    monkeypatch.setattr(daf.requests, "get", _fake_get({
        "teams": _FakeResp(200, TEAMS_OK),
        "fixtures": _FakeResp(200, FIXTURES_OK),
        "fixtures/statistics": _FakeResp(403, {"errors": {"plan": "Your plan does not include fixture statistics."}}),
    }, calls))

    result = daf.probe_league("Premier League", "Arsenal", key_manager=_FakeKeyManager(), cache=_FakeCache())

    assert result.verdict == "statistics_http_error"
    assert result.statistics_probe.http_status == 403
    assert "plan" in result.verdict_detail.lower() or "does not include" in result.verdict_detail


def test_probe_league_statistics_404_no_error_body(monkeypatch):
    calls: list = []
    monkeypatch.setattr(daf.requests, "get", _fake_get({
        "teams": _FakeResp(200, TEAMS_OK),
        "fixtures": _FakeResp(200, FIXTURES_OK),
        "fixtures/statistics": _FakeResp(404, text=""),
    }, calls))

    result = daf.probe_league("Premier League", "Arsenal", key_manager=_FakeKeyManager(), cache=_FakeCache())

    assert result.verdict == "statistics_http_error"
    assert result.statistics_probe.http_status == 404


def test_probe_league_unexpected_structure_does_not_crash(monkeypatch):
    calls: list = []
    monkeypatch.setattr(daf.requests, "get", _fake_get({
        "teams": _FakeResp(200, TEAMS_OK),
        "fixtures": _FakeResp(200, FIXTURES_OK),
        "fixtures/statistics": _FakeResp(200, {"response": [{"team": {"id": 42}, "totally_different_shape": True}]}),
    }, calls))

    result = daf.probe_league("Premier League", "Arsenal", key_manager=_FakeKeyManager(), cache=_FakeCache())

    assert result.verdict == "structura_neasteptata"
    assert result.all_raw_types_found == []


def test_probe_league_stops_after_resolve_team_failure_no_further_calls(monkeypatch):
    calls: list = []
    monkeypatch.setattr(daf.requests, "get", _fake_get({
        "teams": _FakeResp(500, text="internal error"),
    }, calls))

    result = daf.probe_league("Premier League", "Arsenal", key_manager=_FakeKeyManager(), cache=_FakeCache())

    assert result.verdict == "resolve_team_esuat"
    assert result.fixture_lookup_probe is None
    assert result.statistics_probe is None
    assert len(calls) == 1  # niciun apel suplimentar, nu inventează pași


# ── Optimizare de quota — cache team_id / fixture_id / verdict 403-404 ──────

def test_probe_league_reuses_cached_team_id_skips_teams_call(monkeypatch):
    """team_id deja în cache (aceeași cheie ca ApiFootballProvider.resolve_team_id)
    -> /teams NU se mai apelează."""
    calls: list = []
    monkeypatch.setattr(daf.requests, "get", _fake_get({
        "fixtures": _FakeResp(200, FIXTURES_OK),
        "fixtures/statistics": _FakeResp(200, STATS_FULL),
    }, calls))
    cache = _FakeCache(seed={("teams", "team_id:arsenal"): TEAMS_OK})

    km = _FakeKeyManager()
    result = daf.probe_league("Premier League", "Arsenal", key_manager=km, cache=cache)

    assert result.verdict == "ok"
    assert result.team_id == 42
    assert result.team_id_from_cache is True
    assert result.resolve_team_probe is None
    assert "teams" not in [c.split("/")[-1] for c in calls if c.endswith("/teams")]
    assert km.recorded == 2  # doar fixtures + statistics, nu teams


def test_probe_league_reuses_cached_team_and_fixture_id_costs_one_call(monkeypatch):
    """team_id ȘI fixture_id deja în cache -> un singur apel real, la
    /fixtures/statistics. Exact optimizarea cerută: 3 apeluri -> 1."""
    calls: list = []
    monkeypatch.setattr(daf.requests, "get", _fake_get({
        "fixtures/statistics": _FakeResp(200, STATS_FULL),
    }, calls))
    cache = _FakeCache(seed={
        ("teams", "team_id:arsenal"): TEAMS_OK,
        ("api_football_probe", "last_fixture:42"): {
            "fixture_id": 999, "home_team": "Arsenal", "away_team": "Chelsea",
            "fixture_date": "2026-07-01T18:00:00+00:00",
        },
    })

    km = _FakeKeyManager()
    result = daf.probe_league("Premier League", "Arsenal", key_manager=km, cache=cache)

    assert result.verdict == "ok"
    assert result.team_id_from_cache is True
    assert result.fixture_id_from_cache is True
    assert result.fixture_id == 999
    assert len(calls) == 1
    assert km.recorded == 1


def test_probe_league_writes_team_id_and_fixture_id_to_cache_after_fresh_calls(monkeypatch):
    calls: list = []
    monkeypatch.setattr(daf.requests, "get", _fake_get({
        "teams": _FakeResp(200, TEAMS_OK),
        "fixtures": _FakeResp(200, FIXTURES_OK),
        "fixtures/statistics": _FakeResp(200, STATS_FULL),
    }, calls))
    cache = _FakeCache()

    daf.probe_league("Premier League", "Arsenal", key_manager=_FakeKeyManager(), cache=cache)

    assert cache.get_raw("teams", "team_id:arsenal") == TEAMS_OK
    fx = cache.get_raw("api_football_probe", "last_fixture:42")
    assert fx["fixture_id"] == 999 and fx["home_team"] == "Arsenal"


def test_probe_league_caches_403_verdict_and_next_call_makes_zero_http_calls(monkeypatch):
    """Primul apel: 403, se cache-uiește verdictul. Al doilea apel (aceeași
    echipă, cache 'cald'): 0 apeluri HTTP la /fixtures/statistics."""
    calls: list = []
    monkeypatch.setattr(daf.requests, "get", _fake_get({
        "teams": _FakeResp(200, TEAMS_OK),
        "fixtures": _FakeResp(200, FIXTURES_OK),
        "fixtures/statistics": _FakeResp(403, {"errors": {"plan": "not included"}}),
    }, calls))
    cache = _FakeCache()

    r1 = daf.probe_league("Premier League", "Arsenal", key_manager=_FakeKeyManager(), cache=cache)
    assert r1.verdict == "statistics_http_error"
    assert len(calls) == 3  # prima dată: toate cele 3

    calls.clear()
    r2 = daf.probe_league("Premier League", "Arsenal", key_manager=_FakeKeyManager(), cache=cache)

    assert r2.verdict == "statistics_http_error"
    assert r2.statistics_result_from_cache is True
    assert len(calls) == 0  # a doua oară: ZERO apeluri — team_id + fixture_id + verdict, toate din cache
    assert "[rezultat din cache" in r2.verdict_detail


def test_probe_league_does_not_cache_non_403_404_statistics_errors(monkeypatch):
    """Un 500 (eroare tranzitorie) NU trebuie cache-uit — merită reîncercat,
    spre deosebire de 403/404 (structural, nu se schimbă de pe-o zi pe alta)."""
    calls: list = []
    monkeypatch.setattr(daf.requests, "get", _fake_get({
        "teams": _FakeResp(200, TEAMS_OK),
        "fixtures": _FakeResp(200, FIXTURES_OK),
        "fixtures/statistics": _FakeResp(500, text="server error"),
    }, calls))
    cache = _FakeCache()

    daf.probe_league("Premier League", "Arsenal", key_manager=_FakeKeyManager(), cache=cache)

    assert cache.get_raw("api_football_probe", "statistics_verdict:999") is None


def test_run_probe_calls_probe_league_once_per_configured_league(monkeypatch):
    seen: list[tuple[str, str]] = []

    def fake_probe_league(league, team, key_manager=None, cache=None):
        seen.append((league, team))
        return daf.LeagueProbeResult(league=league, team_name=team, verdict="ok")

    monkeypatch.setattr(daf, "probe_league", fake_probe_league)
    report = daf.run_probe(leagues=["Premier League", "La Liga"], delay_seconds=0)

    assert seen == [("Premier League", "Arsenal"), ("La Liga", "Real Madrid")]
    assert len(report.leagues) == 2


def test_format_report_text_readable_for_ok_and_failed_verdicts():
    ok = daf.LeagueProbeResult(
        league="Premier League", team_name="Arsenal", fixture_id=1,
        home_team="Arsenal", away_team="Chelsea", fixture_date="2026-07-01",
        statistics_probe=daf.HttpProbe(url="x", http_status=200, ok=True, latency_ms=120.0),
        field_checks=[daf.FieldCheck(label="possession", found=True, matched_raw_type="Ball Possession"),
                      daf.FieldCheck(label="xG", found=False)],
        all_raw_types_found=["Ball Possession"], verdict="ok",
    )
    failed = daf.LeagueProbeResult(
        league="La Liga", team_name="Real Madrid", verdict="statistics_http_error",
        verdict_detail="HTTP 403. plan: not included",
        statistics_probe=daf.HttpProbe(url="x", http_status=403, ok=False, latency_ms=80.0),
    )
    text = daf.format_report_text(daf.ProbeReport(generated_at="now", quota_note="q", leagues=[ok, failed]))

    assert "Premier League" in text and "✓ possession" in text and "✗ xG" in text
    assert "La Liga" in text and "statistics_http_error" in text and "403" in text
