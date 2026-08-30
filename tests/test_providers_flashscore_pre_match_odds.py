"""Teste pentru providers/flashscore/pre_match_odds.py — flux NOU, separat,
fara retea. Verifica exact frontiera cu discovery.py/normalizer.py
(reutilizare, nu duplicare) si garda critica: fetch-ul unui meci nejucat
atinge DOAR 2 taburi (summary + odds), niciodata cele 7 din adapter.py."""
from __future__ import annotations

import logging
import time
from datetime import datetime

import pytest

from providers.flashscore.pre_match_odds import (
    _discover_league_fixtures_with_odds,
    _fetch_summary_and_odds,
    _kickoff_confirmed_beyond_window,
    _within_window,
    discover_week_fixtures_with_odds,
    persist_week_odds,
    resolve_fixture_id,
    sync_week_odds_from_flashscore,
)

# ── fake-uri comune, reutilizate de mai multe secțiuni de mai jos ──────────

class _FakeResponse:
    def __init__(self, status=200):
        self.status = status


class _FakeLightPage:
    """Fake Playwright page — inregistreaza fiecare URL vizitat, ca sa se
    poata verifica exact ce taburi au fost cerute."""
    def __init__(self):
        self.urls_visited: list[str] = []

    def goto(self, url, wait_until=None, timeout=None):
        self.urls_visited.append(url)
        return _FakeResponse()

    def wait_for_timeout(self, ms):
        pass

    def content(self):
        return "<html><body>fake</body></html>"


# ── _within_window — pura ───────────────────────────────────────────────────

def test_within_window_true_for_kickoff_in_range():
    now = datetime(2026, 8, 4, 12, 0, 0)
    assert _within_window("2026-08-06T18:00:00", days_ahead=7, now=now) is True


def test_within_window_false_for_kickoff_beyond_days_ahead():
    now = datetime(2026, 8, 4, 12, 0, 0)
    assert _within_window("2026-08-20T18:00:00", days_ahead=7, now=now) is False


def test_within_window_false_for_kickoff_in_the_past():
    now = datetime(2026, 8, 4, 12, 0, 0)
    assert _within_window("2026-08-01T18:00:00", days_ahead=7, now=now) is False


def test_within_window_false_for_missing_kickoff():
    assert _within_window(None, days_ahead=7) is False


def test_within_window_false_for_unparseable_kickoff():
    assert _within_window("not-a-date", days_ahead=7) is False


def test_within_window_true_at_exact_boundaries():
    now = datetime(2026, 8, 4, 12, 0, 0)
    assert _within_window("2026-08-04T12:00:00", days_ahead=7, now=now) is True
    assert _within_window("2026-08-11T12:00:00", days_ahead=7, now=now) is True


def test_within_window_margin_absorbs_a_few_hours_of_timezone_drift():
    """Marja de siguranta (_TIMEZONE_SAFETY_MARGIN) trebuie sa accepte un
    kickoff cu cateva ore inainte de 'acum' sau dupa capatul ferestrei —
    fara ea, testul de mai jos ar fi False."""
    now = datetime(2026, 8, 4, 12, 0, 0)
    assert _within_window("2026-08-04T08:00:00", days_ahead=7, now=now) is True   # 4h inainte de "acum"
    assert _within_window("2026-08-11T15:00:00", days_ahead=7, now=now) is True   # 3h dupa capatul ferestrei


def test_within_window_still_false_well_outside_margin():
    now = datetime(2026, 8, 4, 12, 0, 0)
    assert _within_window("2026-08-04T00:00:00", days_ahead=7, now=now) is False  # 12h inainte, dincolo de marja
    assert _within_window("2026-08-12T12:00:00", days_ahead=7, now=now) is False  # 1 zi dupa capatul ferestrei


# ── _kickoff_confirmed_beyond_window — garda de oprire timpurie ───────────

def test_kickoff_confirmed_beyond_window_true_well_past_window():
    now = datetime(2026, 8, 4, 12, 0, 0)
    assert _kickoff_confirmed_beyond_window("2026-08-20T12:00:00", days_ahead=7, now=now) is True


def test_kickoff_confirmed_beyond_window_false_inside_window():
    now = datetime(2026, 8, 4, 12, 0, 0)
    assert _kickoff_confirmed_beyond_window("2026-08-06T12:00:00", days_ahead=7, now=now) is False


def test_kickoff_confirmed_beyond_window_false_inside_margin():
    """Chiar imediat dupa capatul ferestrei, dar inca in marja — nu se
    confirma 'dincolo de fereastra' (ar opri bucla prea devreme)."""
    now = datetime(2026, 8, 4, 12, 0, 0)
    assert _kickoff_confirmed_beyond_window("2026-08-11T15:00:00", days_ahead=7, now=now) is False


def test_kickoff_confirmed_beyond_window_false_for_missing_or_unparseable():
    assert _kickoff_confirmed_beyond_window(None, days_ahead=7) is False
    assert _kickoff_confirmed_beyond_window("not-a-date", days_ahead=7) is False


# ── resolve_fixture_id — pura ───────────────────────────────────────────────

def test_resolve_fixture_id_reuses_primary_source_fixture_id_on_match():
    record = {"home_team": "FC Botosani", "away_team": "Universitatea Cluj", "kickoff_date": "2026-08-10", "mid": "abc123"}
    live_matches = [
        {"home_team": "FC Botosani", "away_team": "Universitatea Cluj", "kickoff_date": "2026-08-10", "fixture_id": "odds_api_999"},
    ]
    assert resolve_fixture_id(record, live_matches) == "odds_api_999"


def test_resolve_fixture_id_mints_flashscore_id_when_no_primary_match():
    record = {"home_team": "Shamrock Rovers", "away_team": "Egnatia", "kickoff_date": "2026-08-10", "mid": "abc123"}
    assert resolve_fixture_id(record, live_matches=[]) == "flashscore_abc123"
    assert resolve_fixture_id(record, live_matches=None) == "flashscore_abc123"


def test_resolve_fixture_id_no_false_positive_on_different_date():
    record = {"home_team": "FC Botosani", "away_team": "Universitatea Cluj", "kickoff_date": "2026-08-10", "mid": "abc123"}
    live_matches = [
        {"home_team": "FC Botosani", "away_team": "Universitatea Cluj", "kickoff_date": "2026-08-11", "fixture_id": "odds_api_999"},
    ]
    assert resolve_fixture_id(record, live_matches) == "flashscore_abc123"


# ── persist_week_odds — I/O mockuit ─────────────────────────────────────────

def test_persist_week_odds_writes_one_row_per_bookmaker(monkeypatch):
    written = []

    def _fake_upsert(fixture_id, bookmaker, home, draw, away):
        written.append((fixture_id, bookmaker, home, draw, away))
        return True

    monkeypatch.setattr("database.queries.upsert_odds_fallback_flashscore", _fake_upsert)

    records = [{
        "home_team": "A", "away_team": "B", "kickoff_date": "2026-08-10", "mid": "m1",
        "odds": [
            {"bookmaker": "bet365", "home": 1.5, "draw": 3.5, "away": 6.0, "source": "flashscore"},
            {"bookmaker": "Unibet", "home": 1.55, "draw": 3.4, "away": 5.8, "source": "flashscore"},
        ],
    }]
    report = persist_week_odds(records)

    assert report == {"matches_seen": 1, "odds_rows_written": 2, "odds_rows_failed": 0, "matches_without_odds": 0}
    assert written == [
        ("flashscore_m1", "bet365", 1.5, 3.5, 6.0),
        ("flashscore_m1", "Unibet", 1.55, 3.4, 5.8),
    ]


def test_persist_week_odds_counts_matches_without_any_odds_row():
    records = [{"home_team": "A", "away_team": "B", "kickoff_date": "2026-08-10", "mid": "m1", "odds": []}]
    report = persist_week_odds(records)
    assert report == {"matches_seen": 1, "odds_rows_written": 0, "odds_rows_failed": 0, "matches_without_odds": 1}


def test_persist_week_odds_counts_write_failures_separately(monkeypatch):
    monkeypatch.setattr("database.queries.upsert_odds_fallback_flashscore", lambda **kw: False)
    records = [{
        "home_team": "A", "away_team": "B", "kickoff_date": "2026-08-10", "mid": "m1",
        "odds": [{"bookmaker": "bet365", "home": 1.5, "draw": 3.5, "away": 6.0, "source": "flashscore"}],
    }]
    report = persist_week_odds(records)
    assert report["odds_rows_written"] == 0
    assert report["odds_rows_failed"] == 1


def test_persist_week_odds_uses_resolved_fixture_id_from_live_matches(monkeypatch):
    seen_fixture_ids = []
    monkeypatch.setattr(
        "database.queries.upsert_odds_fallback_flashscore",
        lambda fixture_id, bookmaker, home, draw, away: seen_fixture_ids.append(fixture_id) or True,
    )
    records = [{
        "home_team": "FC Botosani", "away_team": "Universitatea Cluj", "kickoff_date": "2026-08-10", "mid": "m1",
        "odds": [{"bookmaker": "bet365", "home": 1.5, "draw": 3.5, "away": 6.0, "source": "flashscore"}],
    }]
    live_matches = [{"home_team": "FC Botosani", "away_team": "Universitatea Cluj", "kickoff_date": "2026-08-10", "fixture_id": "odds_api_999"}]
    persist_week_odds(records, live_matches=live_matches)
    assert seen_fixture_ids == ["odds_api_999"]


# ── discover_week_fixtures_with_odds — validare fara retea ────────────────

def test_discover_week_fixtures_rejects_unknown_league():
    with pytest.raises(ValueError, match="fara slug Flashscore verificat live"):
        discover_week_fixtures_with_odds(leagues=["Liga Necunoscuta"])


class _FakeBrowser:
    """Inregistreaza daca a fost inchis (finally), indiferent de succes/esec."""
    def __init__(self):
        self.closed = False

    def new_page(self):
        return _FakeLightPage()

    def close(self):
        self.closed = True


class _FakeChromium:
    def __init__(self, browser):
        self._browser = browser

    def launch(self, headless=True, executable_path=None):
        return self._browser


class _FakePlaywright:
    def __init__(self, browser):
        self.chromium = _FakeChromium(browser)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_discover_week_fixtures_isolates_one_failing_league(monkeypatch):
    """O liga esuata nu trebuie sa piarda rezultatele deja stranse de la
    celelalte — regresie directa pentru fix-ul de izolare per-liga."""
    calls: list[str] = []

    def _fake_discover_league(page, league, days_ahead, limit_per_league):
        calls.append(league)
        if league == "Champions League":
            raise RuntimeError("protectie Flashscore simulata")
        return [{"league": league, "mid": f"{league}-m1"}]

    fake_browser = _FakeBrowser()
    monkeypatch.setattr(
        "providers.flashscore.pre_match_odds._discover_league_fixtures_with_odds", _fake_discover_league,
    )
    monkeypatch.setattr("playwright.sync_api.sync_playwright", lambda: _FakePlaywright(fake_browser))
    monkeypatch.setattr("providers.flashscore.pre_match_odds.polite_delay", lambda: None)

    records = discover_week_fixtures_with_odds(
        leagues=["Europa League", "Champions League", "Premier League"], days_ahead=7,
    )

    assert calls == ["Europa League", "Champions League", "Premier League"]
    assert [r["mid"] for r in records] == ["Europa League-m1", "Premier League-m1"]
    assert fake_browser.closed is True


# ── _discover_league_fixtures_with_odds — o singura liga, control flow ────

def _patch_discovery_internals(monkeypatch, pairs, identities, odds_by_mid=None):
    """Monkeypatch-uri comune — izoleaza controlul de flux (break/continue/
    collect) de parsarea HTML reala (deja acoperita separat, in normalizer
    si discovery)."""
    fetched_mids: list[str] = []

    def _fake_fetch(page, base_url, mid):
        fetched_mids.append(mid)
        return {"summary": mid, "odds": mid}

    monkeypatch.setattr("providers.flashscore.pre_match_odds._fetch_summary_and_odds", _fake_fetch)
    monkeypatch.setattr(
        "providers.flashscore.pre_match_odds.normalize_upcoming_match", lambda pages: identities[pages["summary"]],
    )
    monkeypatch.setattr(
        "providers.flashscore.pre_match_odds.normalize_odds",
        lambda pages: (odds_by_mid or {}).get(pages["odds"], []),
    )
    monkeypatch.setattr("providers.flashscore.pre_match_odds.parse_match_links", lambda html: pairs)
    monkeypatch.setattr("providers.flashscore.pre_match_odds._dismiss_gdpr_if_present", lambda page: None)
    monkeypatch.setattr("providers.flashscore.pre_match_odds._check_protection", lambda *a, **kw: None)
    monkeypatch.setattr("providers.flashscore.pre_match_odds.polite_delay", lambda: None)
    return fetched_mids


def test_discover_league_fixtures_stops_early_when_kickoff_confirmed_beyond_window(monkeypatch):
    now = datetime(2026, 8, 4, 12, 0, 0)
    pairs = [
        ("https://www.flashscore.com/match/football/a", "m1"),
        ("https://www.flashscore.com/match/football/b", "m2"),  # confirmat dincolo de fereastra -> break
        ("https://www.flashscore.com/match/football/c", "m3"),  # nu trebuie niciodata fetch-uit
    ]
    identities = {
        "m1": {"home_team": "A1", "away_team": "A2", "kickoff_date": "2026-08-05T12:00:00", "mid": "m1"},
        "m2": {"home_team": "B1", "away_team": "B2", "kickoff_date": "2026-09-01T12:00:00", "mid": "m2"},
        "m3": {"home_team": "C1", "away_team": "C2", "kickoff_date": "2026-08-06T12:00:00", "mid": "m3"},
    }
    fetched_mids = _patch_discovery_internals(monkeypatch, pairs, identities)

    records = _discover_league_fixtures_with_odds(
        _FakeLightPage(), "Europa League", days_ahead=7, limit_per_league=None, now=now,
    )

    assert fetched_mids == ["m1", "m2"]
    assert [r["mid"] for r in records] == ["m1"]


def test_discover_league_fixtures_collects_all_within_window(monkeypatch):
    now = datetime(2026, 8, 4, 12, 0, 0)
    pairs = [
        ("https://www.flashscore.com/match/football/a", "m1"),
        ("https://www.flashscore.com/match/football/b", "m2"),
    ]
    identities = {
        "m1": {"home_team": "A1", "away_team": "A2", "kickoff_date": "2026-08-05T12:00:00", "mid": "m1"},
        "m2": {"home_team": "B1", "away_team": "B2", "kickoff_date": "2026-08-06T12:00:00", "mid": "m2"},
    }
    odds_by_mid = {"m1": [{"bookmaker": "bet365", "home": 1.5, "draw": 3.5, "away": 6.0, "source": "flashscore"}]}
    _patch_discovery_internals(monkeypatch, pairs, identities, odds_by_mid)

    records = _discover_league_fixtures_with_odds(
        _FakeLightPage(), "Europa League", days_ahead=7, limit_per_league=None, now=now,
    )

    assert [r["mid"] for r in records] == ["m1", "m2"]
    assert records[0]["odds"] == odds_by_mid["m1"]
    assert records[1]["odds"] == []


def test_discover_league_fixtures_skips_unparseable_date_without_stopping(monkeypatch):
    now = datetime(2026, 8, 4, 12, 0, 0)
    pairs = [
        ("https://www.flashscore.com/match/football/a", "m1"),  # data lipsa -> sarit, bucla continua
        ("https://www.flashscore.com/match/football/b", "m2"),  # valid -> colectat
    ]
    identities = {
        "m1": {"home_team": "A1", "away_team": "A2", "kickoff_date": None, "mid": "m1"},
        "m2": {"home_team": "B1", "away_team": "B2", "kickoff_date": "2026-08-06T12:00:00", "mid": "m2"},
    }
    fetched_mids = _patch_discovery_internals(monkeypatch, pairs, identities)

    records = _discover_league_fixtures_with_odds(
        _FakeLightPage(), "Europa League", days_ahead=7, limit_per_league=None, now=now,
    )

    assert fetched_mids == ["m1", "m2"]
    assert [r["mid"] for r in records] == ["m2"]


def test_discover_league_fixtures_respects_limit_per_league(monkeypatch):
    now = datetime(2026, 8, 4, 12, 0, 0)
    pairs = [
        ("https://www.flashscore.com/match/football/a", "m1"),
        ("https://www.flashscore.com/match/football/b", "m2"),
        ("https://www.flashscore.com/match/football/c", "m3"),
    ]
    identities = {
        mid: {"home_team": f"{mid}-H", "away_team": f"{mid}-A", "kickoff_date": "2026-08-05T12:00:00", "mid": mid}
        for mid, _ in [("m1", None), ("m2", None), ("m3", None)]
    }
    fetched_mids = _patch_discovery_internals(monkeypatch, pairs, identities)

    records = _discover_league_fixtures_with_odds(
        _FakeLightPage(), "Europa League", days_ahead=7, limit_per_league=2, now=now,
    )

    assert fetched_mids == ["m1", "m2"]
    assert [r["mid"] for r in records] == ["m1", "m2"]


# ── _fetch_summary_and_odds — garda critica: DOAR 2 taburi, nu 7 ───────────

def test_fetch_summary_and_odds_visits_exactly_two_tabs_not_seven():
    page = _FakeLightPage()
    pages = _fetch_summary_and_odds(page, "https://www.flashscore.com/match/football/x", "mid123")

    assert set(pages.keys()) == {"summary", "odds"}
    assert len(page.urls_visited) == 2
    assert page.urls_visited[0] == "https://www.flashscore.com/match/football/x/?mid=mid123"
    assert page.urls_visited[1] == "https://www.flashscore.com/match/football/x/odds/?mid=mid123"
    # nu apar niciodata taburile "grele" (stats/lineups/player-stats/h2h/standings)
    for forbidden in ("stats", "lineups", "player-stats", "h2h", "standings"):
        assert not any(forbidden in u for u in page.urls_visited)


# ── sync_week_odds_from_flashscore — orchestrare ───────────────────────────

def test_sync_week_odds_from_flashscore_wires_discover_and_persist(monkeypatch):
    fake_records = [{
        "league": "Europa League", "home_team": "A", "away_team": "B",
        "kickoff_date": "2026-08-10", "mid": "m1", "odds": [],
    }]
    monkeypatch.setattr(
        "providers.flashscore.pre_match_odds.discover_week_fixtures_with_odds",
        lambda leagues, days_ahead, limit_per_league: fake_records,
    )
    report = sync_week_odds_from_flashscore(leagues=["Europa League"], days_ahead=7)
    assert report["matches_seen"] == 1
    assert report["leagues"] == ["Europa League"]
    assert report["days_ahead"] == 7


# ════════════════════════════════════════════════════════════════════════
# Instrumentare (adaugata 2026-08-30)
#
# MOTIVUL: rularea sync_pre_match_odds din 2026-08-29 13:45 a fost TAIATA de
# `timeout-minutes: 45` la 45m21s, iar log-ul Python tacea 43 de minute —
# ultima linie utila era "181 meciuri din sursa primara" la 13:47:36, apoi
# nimic pana la taiere. Nu se putea spune cate ligi apucase, cate meciuri
# descarcase, unde s-a dus timpul. Durata crescuse constant: 36m -> 37m ->
# 45m (taiat).
#
# Se masoara INAINTE de a decide intre marirea timeout-ului si optimizare —
# un timeout marit orbeste exact semnalul de care avem nevoie (aceeasi
# disciplina ca la run_daily.step_durations_s).
# ════════════════════════════════════════════════════════════════════════

def _monteaza_playwright_fals(monkeypatch):
    """Playwright + polite_delay neutralizate — reutilizeaza fake-urile deja
    definite mai sus (_FakeBrowser/_FakePlaywright), nu creeaza altele noi."""
    monkeypatch.setattr("playwright.sync_api.sync_playwright", lambda: _FakePlaywright(_FakeBrowser()))
    monkeypatch.setattr("providers.flashscore.pre_match_odds.polite_delay", lambda: None)


def test_raportul_per_liga_numara_descarcate_pastrate_sarite(monkeypatch, caplog):
    """GARDA CENTRALA. `sarite` e cifra de interes: fetch-uri PLATITE (delay +
    2 pagini Playwright) si apoi ARUNCATE. Daca e mare, exista risipa reala
    de optimizat; daca e ~0, durata e munca genuina si raspunsul corect e
    marirea timeout-ului, nu o 'optimizare' inventata."""
    now = datetime(2026, 8, 4, 12, 0, 0)
    pairs = [
        ("https://x/a", "m1"),   # in fereastra  -> pastrat
        ("https://x/b", "m2"),   # data lipsa    -> descarcat si ARUNCAT
        ("https://x/c", "m3"),   # in fereastra  -> pastrat
    ]
    identities = {
        "m1": {"home_team": "A1", "away_team": "A2", "kickoff_date": "2026-08-05T12:00:00", "mid": "m1"},
        "m2": {"home_team": "B1", "away_team": "B2", "kickoff_date": None, "mid": "m2"},
        "m3": {"home_team": "C1", "away_team": "C2", "kickoff_date": "2026-08-06T12:00:00", "mid": "m3"},
    }
    _patch_discovery_internals(monkeypatch, pairs, identities)

    with caplog.at_level(logging.INFO, logger="FootballOracle.Flashscore.PreMatchOdds"):
        _discover_league_fixtures_with_odds(
            _FakeLightPage(), "Europa League", days_ahead=7, limit_per_league=None, now=now,
        )

    linie = next(l for l in caplog.messages if "Europa League" in l and "descarcate" in l)
    assert "3 pe hub" in linie
    assert "3 descarcate" in linie
    assert "2 pastrate" in linie
    assert "1 sarite" in linie
    assert "oprire_devreme=False" in linie


def test_raportul_marcheaza_oprirea_devreme(monkeypatch, caplog):
    """`oprire_devreme=True` distinge 'am terminat hub-ul' de 'am iesit
    din fereastra' — fara asta, un numar mic de descarcari arata identic
    in ambele cazuri, desi inseamna lucruri opuse."""
    now = datetime(2026, 8, 4, 12, 0, 0)
    pairs = [("https://x/a", "m1"), ("https://x/b", "m2"), ("https://x/c", "m3")]
    identities = {
        "m1": {"home_team": "A1", "away_team": "A2", "kickoff_date": "2026-08-05T12:00:00", "mid": "m1"},
        "m2": {"home_team": "B1", "away_team": "B2", "kickoff_date": "2026-09-01T12:00:00", "mid": "m2"},
        "m3": {"home_team": "C1", "away_team": "C2", "kickoff_date": "2026-08-06T12:00:00", "mid": "m3"},
    }
    _patch_discovery_internals(monkeypatch, pairs, identities)

    with caplog.at_level(logging.INFO, logger="FootballOracle.Flashscore.PreMatchOdds"):
        _discover_league_fixtures_with_odds(
            _FakeLightPage(), "Europa League", days_ahead=7, limit_per_league=None, now=now,
        )

    linie = next(l for l in caplog.messages if "Europa League" in l and "descarcate" in l)
    assert "oprire_devreme=True" in linie
    assert "2 descarcate" in linie, "m3 nu trebuie atins dupa break"


def test_progresul_se_logheaza_INAINTE_de_fiecare_liga(monkeypatch, caplog):
    """Daca jobul e omorat la mijloc, ultima linie trebuie sa spuna la ce liga
    ERA, nu la care terminase. Diferenta conteaza exact cand se taie — a fost
    singura informatie care ne-a lipsit pe 29 august.

    [INTARIT dupa o mutatie NEPRINSA] Prima versiune verifica doar CONTINUTUL
    mesajelor. Mutand logul de dinainte de liga la dupa ea, mesajele ramaneau
    identice si testul trecea — desi tocmai proprietatea care conteaza
    (ordinea) disparuse. Acum liga falsa isi logheaza propriul marcaj de
    lucru, iar testul verifica INTRETESEREA: anunt-1, lucru-1, anunt-2,
    lucru-2. Aceeasi clasa de eroare ca la garda `_doar_cod()`: o verificare
    care pare sa confirme ceva, dar confirma altceva."""
    import providers.flashscore.pre_match_odds as m

    def _fals(page, league, days_ahead, limit):
        logger_modul = logging.getLogger("FootballOracle.Flashscore.PreMatchOdds")
        logger_modul.info("[PreMatchOdds] LUCRU efectiv: %s", league)
        return []

    monkeypatch.setattr(m, "_discover_league_fixtures_with_odds", _fals)
    _monteaza_playwright_fals(monkeypatch)

    with caplog.at_level(logging.INFO, logger="FootballOracle.Flashscore.PreMatchOdds"):
        discover_week_fixtures_with_odds(leagues=["Europa League", "Premier League"], days_ahead=7)

    secventa = [l for l in caplog.messages if "▶ liga" in l or "LUCRU efectiv" in l]
    assert secventa == [
        "[PreMatchOdds] ▶ liga 1/2: Europa League",
        "[PreMatchOdds] LUCRU efectiv: Europa League",
        "[PreMatchOdds] ▶ liga 2/2: Premier League",
        "[PreMatchOdds] LUCRU efectiv: Premier League",
    ], f"anuntul trebuie sa PRECEADA lucrul, nu sa-l urmeze: {secventa}"


def test_liga_esuata_e_totusi_anuntata_inainte(monkeypatch, caplog):
    """Cazul in care anuntul conteaza cel mai mult: liga care ARUNCA. Daca
    anuntul s-ar face doar pe calea de succes, exact liga problematica ar
    ramane nenumita in log."""
    import providers.flashscore.pre_match_odds as m

    def _fals(page, league, days_ahead, limit):
        raise RuntimeError("protectie Flashscore (simulat)")

    monkeypatch.setattr(m, "_discover_league_fixtures_with_odds", _fals)
    _monteaza_playwright_fals(monkeypatch)

    with caplog.at_level(logging.INFO, logger="FootballOracle.Flashscore.PreMatchOdds"):
        discover_week_fixtures_with_odds(leagues=["La Liga"], days_ahead=7)

    assert "[PreMatchOdds] ▶ liga 1/1: La Liga" in caplog.messages


def test_raportul_final_ordoneaza_ligile_descrescator_dupa_durata(monkeypatch, caplog):
    """Un raport care listeaza 17 ligi in ordine arbitrara nu raspunde la
    intrebarea pentru care a fost construit ('unde se duce timpul?')."""
    import providers.flashscore.pre_match_odds as m

    durate = {"Europa League": 0.05, "Premier League": 0.0, "La Liga": 0.02}

    def _fals(page, league, days_ahead, limit):
        time.sleep(durate[league])
        return [{"mid": league}]

    monkeypatch.setattr(m, "_discover_league_fixtures_with_odds", _fals)
    _monteaza_playwright_fals(monkeypatch)

    with caplog.at_level(logging.INFO, logger="FootballOracle.Flashscore.PreMatchOdds"):
        discover_week_fixtures_with_odds(
            leagues=["Premier League", "Europa League", "La Liga"], days_ahead=7,
        )

    linii = [l for l in caplog.messages if "înregistrări" in l]
    assert len(linii) == 3
    # cea mai LENTA prima, cea mai rapida ultima
    assert "Europa League" in linii[0], f"cea mai lenta nu e prima: {linii}"
    assert "La Liga" in linii[1], f"ordine gresita la mijloc: {linii}"
    assert "Premier League" in linii[2], f"cea mai rapida nu e ultima: {linii}"


def test_o_liga_esuata_apare_in_raport_si_nu_opreste_restul(monkeypatch, caplog):
    """Izolarea per-liga exista deja; aici se verifica doar ca raportul o
    NUMESTE — altfel un esec tacut ar arata ca o liga pur si simplu lenta."""
    import providers.flashscore.pre_match_odds as m

    def _fals(page, league, days_ahead, limit):
        if league == "La Liga":
            raise RuntimeError("protectie Flashscore (simulat)")
        return [{"mid": league}]

    monkeypatch.setattr(m, "_discover_league_fixtures_with_odds", _fals)
    _monteaza_playwright_fals(monkeypatch)

    with caplog.at_level(logging.INFO, logger="FootballOracle.Flashscore.PreMatchOdds"):
        records = discover_week_fixtures_with_odds(
            leagues=["Europa League", "La Liga", "Premier League"], days_ahead=7,
        )

    assert len(records) == 2, "ligile sanatoase trebuie sa continue"
    raport = next(l for l in caplog.messages if "RAPORT:" in l)
    assert "1 ligi esuate (La Liga)" in raport
