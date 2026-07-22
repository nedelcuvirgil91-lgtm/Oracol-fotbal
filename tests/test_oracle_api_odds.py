"""Teste pentru extinderea _fetch_odds()/_attach_odds() (oracle_api.py) la
piețele Over/Under (totals) și BTTS, pe lângă h2h existent — fără rețea
reală, mock direct pe self._s.get(), urmând tiparul din
test_football_providers.py (FootballOracleAPI.__new__, ocolind
_validate_api_keys())."""
from __future__ import annotations

import oracle_api


class _FakeResp:
    def __init__(self, payload, ok=True, status_code=200):
        self._payload = payload
        self.ok = ok
        self.status_code = status_code

    def json(self):
        return self._payload


class _FakeSession:
    """Rutează după parametrul `markets` din query, ca să simuleze mai multe
    apeluri distincte (h2h+totals, apoi btts separat) în aceeași secvență."""
    def __init__(self, responses_by_markets: dict[str, _FakeResp]):
        self._responses = responses_by_markets
        self.calls: list[str] = []

    def get(self, url, headers=None, params=None, timeout=12):
        markets = (params or {}).get("markets", "")
        self.calls.append(markets)
        return self._responses.get(markets, _FakeResp(None, ok=False, status_code=404))


def _api(session: _FakeSession) -> oracle_api.FootballOracleAPI:
    api = oracle_api.FootballOracleAPI.__new__(oracle_api.FootballOracleAPI)
    api._s = session
    api._mem = {}
    api._ttl = 30
    api._cache_mgr = None
    api._dead_keys = set()
    # [ADAUGAT R4.1] _fetch_market() citește acum cheia Odds API prin
    # self._key_manager (nu mai există constanta hardcodată ODDS_API_KEY,
    # migrată la key_manager.py — vezi audit §13, Step 1).
    from key_manager import get_key_manager
    api._key_manager = get_key_manager()
    return api


_EVENT_H2H_TOTALS = [{
    "id": "ev1", "home_team": "Arsenal", "away_team": "Chelsea",
    "bookmakers": [{
        "title": "Bet365",
        "markets": [
            {"key": "h2h", "outcomes": [
                {"name": "Arsenal", "price": 2.1}, {"name": "Draw", "price": 3.4},
                {"name": "Chelsea", "price": 3.8},
            ]},
            {"key": "totals", "outcomes": [
                {"name": "Over", "point": 2.5, "price": 1.9},
                {"name": "Under", "point": 2.5, "price": 1.95},
                {"name": "Over", "point": 3.5, "price": 3.2},   # linie diferită — trebuie ignorată
            ]},
        ],
    }],
}]

_EVENT_H2H_ONLY = [{
    "id": "ev1", "home_team": "Arsenal", "away_team": "Chelsea",
    "bookmakers": [{
        "title": "Bet365",
        "markets": [
            {"key": "h2h", "outcomes": [
                {"name": "Arsenal", "price": 2.1}, {"name": "Draw", "price": 3.4},
                {"name": "Chelsea", "price": 3.8},
            ]},
        ],
    }],
}]

_EVENT_BTTS = [{
    "id": "ev1", "home_team": "Arsenal", "away_team": "Chelsea",
    "bookmakers": [{
        "title": "Bet365",
        "markets": [{"key": "btts", "outcomes": [
            {"name": "Yes", "price": 1.75}, {"name": "No", "price": 2.05},
        ]}],
    }],
}]


def test_fetch_odds_parses_totals_and_btts_when_available():
    session = _FakeSession({
        "h2h,totals": _FakeResp(_EVENT_H2H_TOTALS),
        "btts":       _FakeResp(_EVENT_BTTS),
    })
    api = _api(session)
    result = api._fetch_odds("soccer_epl")

    entry = result["ev1"]
    assert entry["home"] == 2.1 and entry["draw"] == 3.4 and entry["away"] == 3.8
    assert entry["over25"] == 1.9 and entry["under25"] == 1.95  # doar linia 2.5
    assert entry["btts_yes"] == 1.75 and entry["btts_no"] == 2.05


def test_fetch_odds_falls_back_to_h2h_only_when_expanded_markets_fail():
    """Regresie critică: dacă 'totals' nu e disponibil pe plan, h2h — care
    funcționa deja înainte de acest sprint — NU trebuie să se strice."""
    session = _FakeSession({
        "h2h": _FakeResp(_EVENT_H2H_ONLY),  # doar h2h singur reușește
    })
    api = _api(session)
    result = api._fetch_odds("soccer_epl")

    entry = result["ev1"]
    assert entry["home"] == 2.1 and entry["draw"] == 3.4 and entry["away"] == 3.8
    assert entry["over25"] == 0.0 and entry["under25"] == 0.0
    assert entry["btts_yes"] == 0.0 and entry["btts_no"] == 0.0
    assert "h2h,totals" in session.calls  # a încercat întâi extins
    assert "h2h" in session.calls          # apoi a căzut înapoi pe h2h singur


def test_fetch_odds_btts_failure_does_not_affect_h2h_totals():
    session = _FakeSession({
        "h2h,totals": _FakeResp(_EVENT_H2H_TOTALS),
        # "btts" absent din răspunsuri -> _FakeSession întoarce 404/ok=False
    })
    api = _api(session)
    result = api._fetch_odds("soccer_epl")

    entry = result["ev1"]
    assert entry["home"] == 2.1
    assert entry["over25"] == 1.9
    assert entry["btts_yes"] == 0.0 and entry["btts_no"] == 0.0


def test_fetch_odds_dead_key_shortcircuits_no_http_call():
    session = _FakeSession({})
    api = _api(session)
    api._dead_keys = {"soccer_epl"}
    result = api._fetch_odds("soccer_epl")
    assert result == {}
    assert session.calls == []


def test_attach_odds_populates_extra_fields_only_when_found():
    api = oracle_api.FootballOracleAPI.__new__(oracle_api.FootballOracleAPI)
    api._dead_keys = set()

    def fake_fetch_odds(sport_key):
        return {
            "ev1": {"home": 2.1, "draw": 3.4, "away": 3.8, "bookmaker": "Bet365",
                     "ev_id": "ev1", "over25": 1.9, "under25": 1.95,
                     "btts_yes": 0.0, "btts_no": 0.0},
        }
    api._fetch_odds = fake_fetch_odds

    matches = [{"fixture_id": "fx1", "home_team": "Arsenal", "away_team": "Chelsea",
                "league": "Premier League", "_odds_api_id": "ev1"}]
    result = oracle_api.FootballOracleAPI._attach_odds(api, matches)

    m = result[0]
    assert m["over25_odds"] == 1.9 and m["under25_odds"] == 1.95
    # btts a fost 0.0 (indisponibil) -> nicio valoare inventată, cheia nu apare deloc
    assert "btts_yes_odds" not in m and "btts_no_odds" not in m
