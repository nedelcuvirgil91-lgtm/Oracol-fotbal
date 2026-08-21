"""F2.5 (ADR-058) — invariantul de deduplicare al listei Level-DB din
`oracle_api.get_matches_for_week()`.

CONTRACT TESTAT AICI, ȘI NIMIC ALTCEVA: lista venită din
`get_matches_for_week_from_history()` trece prin ACELAȘI `_add()` /
`match_key()` / `seen_keys` ca orice sursă ulterioară (cascadă live,
scheduled_fixtures). Înainte de F2.5 era singura sursă din funcție care
ocolea dedup-ul — `matches` era chiar lista brută, iar `seen_keys` se
construia din ea.

Acest fișier NU demonstrează că F3 (extinderea vocabularului) e sigur.
F2.5 e un invariant de deduplicare, valid și dovedit independent de F3:
ar fi fost justificat și dacă problema de identitate n-ar fi existat
niciodată, fiindcă două rânduri `match_history` pentru același meci
ajungeau deja necondiționat la consumatori.

Datele de test sunt calculate DINAMIC din `date.today()` — un test cu
date fixe iese din fereastra de 7 zile a funcției pe măsură ce trece
timpul și începe să treacă/pice din motive care n-au legătură cu
contractul.

Fără rețea, fără Supabase.
"""
from __future__ import annotations

from datetime import date, timedelta

import oracle_api
from mappings import match_key


def _api_no_network() -> oracle_api.FootballOracleAPI:
    """Aceeași construcție ca tests/test_oracle_api_scheduled_fixtures_
    last_resort_fallback.py — instanță fără rețea, toate fetch-erele
    neutralizate."""
    api = oracle_api.FootballOracleAPI.__new__(oracle_api.FootballOracleAPI)
    api._mem = {}
    api._ttl = 30
    api._cache_mgr = None
    api._dead_keys = set()
    api._freelf_exhausted = False
    api._active_sport_keys = set()
    api._api_football = None
    api._key_manager = None

    api._fetch_events_odds_api = lambda sport_key, days_ahead=7: []
    api._fetch_freelf_matches = lambda target, league: []
    api._fetch_matches_fd = lambda date_from, date_to, comp_codes=None: []
    api._fetch_matches_espn = lambda league, target_date: []
    api._fetch_matches_tsdb = lambda league_id, league_name: []
    api._fetch_matches_api_football = lambda league, date_from, date_to: []
    api._fetch_live_week_matches = lambda days_ahead, competitions: []
    api._generate_demo_matches = lambda competitions: []
    api._attach_odds = lambda matches: matches
    api._attach_primary_odds_from_history = lambda matches: matches
    api._attach_flashscore_odds_fallback = lambda matches: matches
    api._shadow_evaluate_selection_engine = lambda comps, matches: None
    api._shadow_evaluate_scheduled_fixtures = lambda matches, d_from, d_to: None
    return api


def _stub_history(monkeypatch, rows: list[dict], covered: set[str]):
    import database.queries as queries
    monkeypatch.setattr(
        queries, "get_matches_for_week_from_history",
        lambda comps, d_from, d_to: (list(rows), set(covered)),
    )


def _stub_scheduled_empty(monkeypatch):
    import database.queries as queries
    monkeypatch.setattr(
        queries, "get_matches_for_week_from_scheduled_fixtures",
        lambda leagues, d_from, d_to: ([], set()),
    )


def _day(offset: int) -> str:
    """Dată în interiorul ferestrei de 7 zile a funcției."""
    return (date.today() + timedelta(days=offset)).isoformat()


def _row(home: str, away: str, when: str, fixture_id: str, league: str = "Premier League") -> dict:
    return {
        "fixture_id": fixture_id, "home_team": home, "away_team": away,
        "league": league, "kickoff_date": when, "kickoff_utc": f"{when}T15:00:00Z",
        "season": None, "status": "scheduled",
        "home_odds": None, "draw_odds": None, "away_odds": None, "odds_source": None,
    }


# ════════════════════════════════════════════════════════════════════════
# 1. NO-OP în baseline-ul curent
# ════════════════════════════════════════════════════════════════════════

def test_no_op_when_level_db_has_no_duplicate_keys(monkeypatch):
    """Cerința centrală de siguranță a F2.5: în baseline-ul real (B3 = 0
    chei naturale duplicate în match_history, verificat live), schimbarea
    NU are niciun efect — aceleași meciuri, aceeași ordine, același număr.

    Dacă acest test pică, F2.5 nu mai e un no-op și nu are voie să intre.
    """
    rows = [
        _row("Arsenal", "Chelsea", _day(1), "fd_1"),
        _row("Liverpool", "Everton", _day(2), "fd_2"),
        _row("Manchester United", "Leeds United", _day(3), "fd_3"),
    ]
    _stub_history(monkeypatch, rows, {"Premier League"})
    _stub_scheduled_empty(monkeypatch)

    api = _api_no_network()
    out = api.get_matches_for_week(days_ahead=7, competitions=["Premier League"])

    assert len(out) == len(rows), "F2.5 a schimbat numărul de meciuri într-un baseline fără duplicate"
    assert [m["fixture_id"] for m in out] == ["fd_1", "fd_2", "fd_3"], (
        "F2.5 a schimbat ordinea meciurilor — ordinea Level-DB trebuie păstrată"
    )
    assert out == rows, "conținutul rândurilor a fost modificat"


# ════════════════════════════════════════════════════════════════════════
# 2. Invariantul propriu-zis — deduplicarea
# ════════════════════════════════════════════════════════════════════════

def test_two_name_variants_of_same_match_collapse_to_one(monkeypatch):
    """INVARIANTUL F2.5. Două rânduri `match_history` pentru ACELAȘI meci
    (aceeași pereche de echipe + aceeași dată), scrise sub variante de nume
    diferite, trebuie să producă O SINGURĂ apariție la consumator.

    Se folosesc `Man Utd` / `Manchester United` — alias care există DEJA azi
    în `mappings.ALIAS_TO_CANONICAL`, deci testul e valid independent de F3.
    """
    when = _day(2)
    rows = [
        _row("Man Utd", "Leeds United", when, "kaggle_aaa"),
        _row("Manchester United", "Leeds United", when, "fd_bbb"),
    ]
    _stub_history(monkeypatch, rows, {"Premier League"})
    _stub_scheduled_empty(monkeypatch)

    api = _api_no_network()
    out = api.get_matches_for_week(days_ahead=7, competitions=["Premier League"])

    assert len(out) == 1, (
        f"același meci sub două variante de nume a produs {len(out)} apariții — "
        f"exact defectul pe care F2.5 îl elimină"
    )
    assert out[0]["fixture_id"] == "kaggle_aaa", "dedup-ul trebuie să păstreze PRIMA apariție (first-wins)"


def test_match_key_normalizes_aliases():
    """Dovada că mecanismul de dedup chiar unifică variantele: cheia se
    calculează pe numele NORMALIZAT, nu pe cel brut. Fără asta, `_add()` ar
    trata cele două rânduri ca meciuri diferite."""
    when = _day(2)
    assert match_key("Man Utd", "Leeds United", when) == match_key("Manchester United", "Leeds United", when)
    # Contra-proba: cluburi genuin diferite NU au voie să coincidă.
    assert match_key("Arsenal", "Leeds United", when) != match_key("Chelsea", "Leeds United", when)


def test_distinct_matches_are_never_collapsed(monkeypatch):
    """Contra-proba invariantului: dedup-ul nu are voie să piardă meciuri
    reale — echipe diferite, sau aceleași echipe la date diferite."""
    rows = [
        _row("Arsenal", "Chelsea", _day(1), "fd_1"),
        _row("Arsenal", "Chelsea", _day(4), "fd_2"),   # tur/retur, date diferite
        _row("Chelsea", "Arsenal", _day(1), "fd_3"),   # inversat: alt meci
    ]
    _stub_history(monkeypatch, rows, {"Premier League"})
    _stub_scheduled_empty(monkeypatch)

    api = _api_no_network()
    out = api.get_matches_for_week(days_ahead=7, competitions=["Premier League"])

    assert len(out) == 3, "dedup-ul a colapsat meciuri genuin diferite"


# ════════════════════════════════════════════════════════════════════════
# 3. Comportamentul surselor ulterioare rămâne neschimbat
# ════════════════════════════════════════════════════════════════════════

def test_level_db_still_wins_over_later_sources(monkeypatch):
    """Regresie pe prioritatea ADR-053: Level DB se adaugă PRIMUL, deci un
    meci deja prezent în match_history nu poate fi înlocuit de o sursă
    ulterioară (cascadă live) pentru aceeași cheie."""
    when = _day(2)
    _stub_history(monkeypatch, [_row("Arsenal", "Chelsea", when, "fd_db")], {"Premier League"})
    _stub_scheduled_empty(monkeypatch)

    api = _api_no_network()
    # Ligă neacoperită => cascada live rulează și întoarce ACELAȘI meci.
    api._fetch_live_week_matches = lambda days_ahead, competitions: [
        _row("Arsenal", "Chelsea", when, "live_dupe", league="MLS")
    ]
    out = api.get_matches_for_week(days_ahead=7, competitions=["Premier League", "MLS"])

    ids = [m["fixture_id"] for m in out]
    assert "fd_db" in ids, "rândul din Level DB a fost pierdut"
    assert "live_dupe" not in ids, "sursa live a suprascris un meci deja acoperit de Level DB"


def test_live_source_still_fills_genuine_gap(monkeypatch):
    """Cascada live trebuie să funcționeze exact ca înainte pentru ligile
    fără acoperire în match_history."""
    _stub_history(monkeypatch, [], set())
    _stub_scheduled_empty(monkeypatch)

    api = _api_no_network()
    api._fetch_live_week_matches = lambda days_ahead, competitions: [
        _row("LA Galaxy", "LAFC", _day(2), "live_1", league="MLS")
    ]
    out = api.get_matches_for_week(days_ahead=7, competitions=["MLS"])

    assert [m["fixture_id"] for m in out] == ["live_1"]
