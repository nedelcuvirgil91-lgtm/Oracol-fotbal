"""Teste de regresie pentru reconcilierea TSDB (Fir B, aprobat explicit de
utilizator, independent de ADR-034 Selection Engine — vezi discuția
"provider fetch strategy" vs. "provider selection").

Motivație: investigația Etapa 1 SuperLiga a demonstrat că
eventsnextleague.php (calea veche, folosită azi pentru toate ligile TSDB)
are doar 12.5% completitudine față de calendarul oficial LPF, iar
eventsseason.php/eventsround.php doar 62.5% — 3 meciuri
(Petrolul-Dinamo, Corvinul-Csíkszereda, Rapid-Sepsi) există în TSDB STRICT
la nivel de echipă (eventsnext.php), absente din orice endpoint de ligă.

Fix: `_fetch_matches_tsdb()` folosește calea nouă (eventsseason.php +
supliment per echipă, deduplicat prin match_key()) DOAR pentru ligile cu
`TSDB_TEAM_IDS` populat (azi: doar Romania SuperLiga) — toate celelalte
ligi rămân pe calea veche, neschimbată, verificată ani de zile.

Testele mock-uiesc `_get()` direct (nu `_fetch_matches_tsdb`), pentru a
verifica exact CE endpoint-uri sunt apelate și cu ce parametri — asta e
comportamentul intern testat aici, nu gate-ul din get_matches_for_week()
(deja acoperit de test_oracle_api_tsdb_per_league_gate.py)."""
from __future__ import annotations

from datetime import date, timedelta

import oracle_api


def _api_no_network() -> oracle_api.FootballOracleAPI:
    api = oracle_api.FootballOracleAPI.__new__(oracle_api.FootballOracleAPI)
    api._mem = {}
    api._ttl = 30
    api._cache_mgr = None
    api._dead_keys = set()
    api._freelf_exhausted = False
    api._active_sport_keys = set()
    api._api_football = None
    api._key_manager = None
    return api


FUTURE = (date.today() + timedelta(days=3)).isoformat()
PAST = (date.today() - timedelta(days=3)).isoformat()


def _event(home: str, away: str, ev_date: str, event_id: str = "1") -> dict:
    return {
        "idEvent": event_id, "strHomeTeam": home, "strAwayTeam": away,
        "dateEvent": ev_date, "strTime": "15:30:00",
    }


def test_league_without_team_ids_uses_only_eventsnextleague():
    """Premier League nu are TSDB_TEAM_IDS populat — calea veche,
    neschimbată. eventsseason.php/eventsnext.php NU trebuie atinse."""
    api = _api_no_network()
    calls: list[str] = []

    def _fake_get(url: str, headers=None, params=None, timeout: int = 12):
        calls.append(url.rsplit("/", 1)[-1])
        if url.endswith("eventsnextleague.php"):
            return {"events": [_event("Arsenal", "Chelsea", FUTURE)]}
        return None

    api._get = _fake_get

    results = api._fetch_matches_tsdb("4328", "Premier League")

    assert calls == ["eventsnextleague.php"], f"apeluri neasteptate: {calls}"
    assert len(results) == 1
    assert results[0]["home_team"] == "Arsenal"
    assert results[0]["source"] == "thesportsdb"


def test_romania_superliga_uses_eventsseason_and_team_supplement_not_eventsnextleague():
    """Romania SuperLiga are TSDB_TEAM_IDS populat (5 echipe) — trebuie să
    apeleze eventsseason.php O SINGURĂ DATĂ + eventsnext.php o dată per
    echipă (5 apeluri), NICIODATĂ eventsnextleague.php."""
    api = _api_no_network()
    calls: list[tuple[str, dict]] = []

    def _fake_get(url: str, headers=None, params=None, timeout: int = 12):
        endpoint = url.rsplit("/", 1)[-1]
        calls.append((endpoint, dict(params or {})))
        if endpoint == "eventsseason.php":
            return {"events": [_event("FCSB", "FC Argeș", FUTURE, "s1")]}
        if endpoint == "eventsnext.php":
            return {"events": []}
        return None

    api._get = _fake_get

    results = api._fetch_matches_tsdb("4691", "Romania SuperLiga")

    endpoints_called = [c[0] for c in calls]
    assert "eventsnextleague.php" not in endpoints_called, (
        f"eventsnextleague.php NU trebuie apelat pentru Romania SuperLiga — apeluri: {endpoints_called}"
    )
    assert endpoints_called.count("eventsseason.php") == 1
    assert endpoints_called.count("eventsnext.php") == 5, (
        f"asteptat exact 5 apeluri eventsnext.php (cate echipe in TSDB_TEAM_IDS), gasit {endpoints_called.count('eventsnext.php')}"
    )
    # eventsseason.php trebuie apelat cu un sezon calculat, nu hardcodat.
    season_call = next(c for c in calls if c[0] == "eventsseason.php")
    assert season_call[1].get("id") == "4691"
    assert "s" in season_call[1] and "-" in season_call[1]["s"]

    assert len(results) == 1
    assert results[0]["home_team"] == "FCSB"


def test_dedup_across_season_and_team_supplement():
    """Un meci intors atat de eventsseason.php CAT SI de eventsnext.php
    (id-uri de eveniment diferite, dar acelasi meci real) nu trebuie sa
    apara de doua ori in rezultatul final — match_key() e sursa de adevar
    pentru deduplicare, nu idEvent."""
    api = _api_no_network()

    def _fake_get(url: str, headers=None, params=None, timeout: int = 12):
        endpoint = url.rsplit("/", 1)[-1]
        if endpoint == "eventsseason.php":
            return {"events": [_event("Petrolul Ploiești", "Dinamo", FUTURE, "season_id_1")]}
        if endpoint == "eventsnext.php":
            # Acelasi meci, alt idEvent — asa arata dublura reala in TSDB.
            return {"events": [_event("Petrolul Ploiești", "Dinamo", FUTURE, "team_id_9")]}
        return None

    api._get = _fake_get

    results = api._fetch_matches_tsdb("4691", "Romania SuperLiga")

    petrolul_dinamo = [r for r in results if r["home_team"] == "Petrolul Ploiești" and r["away_team"] == "Dinamo"]
    assert len(petrolul_dinamo) == 1, (
        f"meciul Petrolul-Dinamo a aparut de {len(petrolul_dinamo)} ori — dedup esuat"
    )


def test_past_events_filtered_out_in_reconciled_path():
    """Evenimentele cu data in trecut trebuie eliminate, exact ca pe calea
    veche — atat din eventsseason.php cat si din supliment per echipa."""
    api = _api_no_network()

    def _fake_get(url: str, headers=None, params=None, timeout: int = 12):
        endpoint = url.rsplit("/", 1)[-1]
        if endpoint == "eventsseason.php":
            return {"events": [
                _event("FCSB", "FC Argeș", PAST, "past_1"),
                _event("Oțelul Galați", "CFR 1907 Cluj", FUTURE, "future_1"),
            ]}
        if endpoint == "eventsnext.php":
            return {"events": [_event("Dinamo", "Petrolul Ploiești", PAST, "past_2")]}
        return None

    api._get = _fake_get

    results = api._fetch_matches_tsdb("4691", "Romania SuperLiga")

    dates = {r["kickoff_date"] for r in results}
    assert PAST not in dates, f"un eveniment din trecut ({PAST}) nu a fost filtrat: {results}"
    assert FUTURE in dates


def test_dynamic_season_string_calculated_not_hardcoded():
    """Sezonul se calculeaza din data data ca parametru, nu e niciodata un
    string fix — verifica exact granita de iulie (start sezon fotbal)."""
    api = _api_no_network()

    assert api._tsdb_season_string(date(2026, 6, 30)) == "2025-2026"
    assert api._tsdb_season_string(date(2026, 7, 1)) == "2026-2027"
    assert api._tsdb_season_string(date(2027, 1, 15)) == "2026-2027"
    assert api._tsdb_season_string(date(2026, 12, 31)) == "2026-2027"
