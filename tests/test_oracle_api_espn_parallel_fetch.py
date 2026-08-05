"""
Teste pentru paralelizarea buclei ESPN din get_matches_for_week() — fix
"aplicația pornește foarte greu, partea 2" (confirmat live: până la ~98
cereri secvențiale zi×ligă către ESPN, singura cauză reală rămasă a
pornirii lente după eliminarea reantrenării ML sincrone, fix separat).

Verifică exclusiv proprietățile care contează după paralelizare — rezultatul
final trebuie să rămână identic cu varianta secvențială (toate meciurile
adunate, indiferent de ordinea de finalizare a thread-urilor), iar o eroare
neașteptată într-un singur task nu trebuie să oprească restul.
"""
from __future__ import annotations

import threading

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
    api._fetch_matches_api_football = lambda league, date_from, date_to: []
    api._generate_demo_matches = lambda competitions: []
    api._attach_odds = lambda matches: matches
    api._fetch_events_odds_api = lambda sport_key, days_ahead=7: []
    api._fetch_freelf_matches = lambda target, league: []
    api._fetch_matches_fd = lambda date_from, date_to, comp_codes=None: []
    api._fetch_matches_tsdb = lambda league_id, league_name: []
    return api


def test_espn_results_from_all_day_league_combinations_are_merged(monkeypatch):
    """Toate combinatiile zi x liga care au raspuns trebuie sa apara in
    rezultatul final, indiferent de ordinea de finalizare a thread-urilor."""
    api = _api_no_network()

    def _fake_espn(league: str, target_date: str):
        return [{
            "fixture_id": f"espn_{league}_{target_date}",
            "home_team": f"{league}-Home", "away_team": f"{league}-Away",
            "kickoff_date": target_date, "kickoff_utc": f"{target_date}T18:00:00Z",
            "league": league, "source": "espn",
        }]

    api._fetch_matches_espn = _fake_espn

    matches = api.get_matches_for_week(days_ahead=3, competitions=["Premier League", "La Liga"])

    espn_matches = [m for m in matches if m.get("source") == "espn"]
    leagues_seen = {m["league"] for m in espn_matches}
    assert leagues_seen == {"Premier League", "La Liga"}
    # 3 zile x 2 ligi = 6 combinatii, toate trebuie sa fi produs un meci
    assert len(espn_matches) == 6


def test_espn_exception_in_one_task_does_not_block_the_rest(monkeypatch):
    """O eroare neasteptata intr-un singur task (thread) nu trebuie sa
    opreasca colectarea rezultatelor celorlalte — tipar identic degradarii
    gratioase existente deja in tot proiectul."""
    api = _api_no_network()

    def _flaky_espn(league: str, target_date: str):
        if league == "La Liga":
            raise RuntimeError("eroare neasteptata simulata")
        return [{
            "fixture_id": f"espn_{league}_{target_date}",
            "home_team": f"{league}-Home", "away_team": f"{league}-Away",
            "kickoff_date": target_date, "kickoff_utc": f"{target_date}T18:00:00Z",
            "league": league, "source": "espn",
        }]

    api._fetch_matches_espn = _flaky_espn

    matches = api.get_matches_for_week(days_ahead=2, competitions=["Premier League", "La Liga"])

    espn_matches = [m for m in matches if m.get("source") == "espn"]
    assert all(m["league"] == "Premier League" for m in espn_matches)
    assert len(espn_matches) == 2  # 2 zile, doar Premier League a reusit


def test_espn_calls_actually_run_concurrently(monkeypatch):
    """Regresie centrala a fix-ului: dovada directa ca apelurile NU mai
    ruleaza secvential — cel putin doua thread-uri trebuie sa fie active
    SIMULTAN in interiorul _fetch_matches_espn."""
    api = _api_no_network()

    max_concurrent = 0
    current = 0
    lock = threading.Lock()
    barrier_reached = threading.Event()

    def _slow_espn(league: str, target_date: str):
        nonlocal max_concurrent, current
        with lock:
            current += 1
            max_concurrent = max(max_concurrent, current)
            if max_concurrent >= 2:
                barrier_reached.set()
        barrier_reached.wait(timeout=2.0)
        with lock:
            current -= 1
        return []

    api._fetch_matches_espn = _slow_espn

    api.get_matches_for_week(days_ahead=3, competitions=["Premier League", "La Liga", "Serie A"])

    assert max_concurrent >= 2, "apelurile ESPN trebuie sa ruleze concurent, nu secvential"


def test_espn_merge_is_never_touched_from_worker_threads(monkeypatch):
    """_add()/seen_keys raman single-threaded — apelate DOAR dupa
    future.result(), niciodata direct din worker thread-uri. Verificat
    indirect: niciun meci duplicat in rezultat, chiar daca mai multe
    thread-uri intorc chei de deduplicare identice concurent."""
    api = _api_no_network()

    def _duplicate_key_espn(league: str, target_date: str):
        return [{
            "fixture_id": f"espn_dup_{target_date}",
            "home_team": "Same Home", "away_team": "Same Away",
            "kickoff_date": target_date, "kickoff_utc": f"{target_date}T18:00:00Z",
            "league": league, "source": "espn",
        }]

    api._fetch_matches_espn = _duplicate_key_espn

    matches = api.get_matches_for_week(days_ahead=3, competitions=["Premier League", "La Liga"])

    espn_matches = [m for m in matches if m.get("source") == "espn"]
    # (Same Home, Same Away, aceeasi data) e aceeasi cheie de deduplicare
    # indiferent de liga -> exact un meci per zi, nu 2 (cate o liga).
    assert len(espn_matches) == 3
