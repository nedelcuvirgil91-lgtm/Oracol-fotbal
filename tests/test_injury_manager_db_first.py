"""Teste pentru R-Sync-10 (ADR-039) — injury_manager.build_injury_report_from_raw_lineup()
extrasă din fostul get_lineup_absences(), funcție pură, fără I/O.

Demonstrează explicit paritatea comportamentală cerută: aceeași logică de
calcul a penalizării, indiferent dacă `lineup_data` vine dintr-un apel live
(get_lineup_absences(), Sync Layer) sau dintr-un rând Supabase
(oracle_engine.py, Database-First) — funcția de calcul e IDENTICĂ, doar
sursa lui `lineup_data` diferă."""
from __future__ import annotations

from types import SimpleNamespace

from injury_manager import InjuryManager, TeamInjuryReport


_LINEUP_WITH_KEY_ABSENCE = {
    "confirmed": True, "formation": "4-3-3",
    "unavailable": [{
        "id": 7, "name": "Star Forward", "market_value": 80_000_000, "position": "F",
        "unavailability": {"type": "injured", "expectedReturn": "a week"},
    }],
}

_LINEUP_NO_ABSENCES = {"confirmed": True, "formation": "4-4-2", "unavailable": []}


def _manager() -> InjuryManager:
    return InjuryManager()


# ── build_injury_report_from_raw_lineup() — funcție pură ─────────────────

def test_build_report_produces_key_absence_penalty():
    im = _manager()
    report = im.build_injury_report_from_raw_lineup(_LINEUP_WITH_KEY_ABSENCE, team_id=1, team_name="Arsenal")

    assert report.data_quality == "confirmed"
    assert report.has_key_absences is True
    assert report.total_xg_penalty < 0
    assert len(report.absences) == 1
    assert report.absences[0].name == "Star Forward"


def test_build_report_confirmed_no_absences():
    im = _manager()
    report = im.build_injury_report_from_raw_lineup(_LINEUP_NO_ABSENCES, team_id=1, team_name="Arsenal")

    assert report.data_quality == "confirmed"
    assert report.has_key_absences is False
    assert report.total_xg_penalty == 0.0
    assert report.absences == []


def test_build_report_unavailable_when_lineup_data_is_none():
    im = _manager()
    report = im.build_injury_report_from_raw_lineup(None, team_id=1, team_name="Arsenal")

    assert report.data_quality == "unavailable"
    assert report.total_xg_penalty == 0.0


def test_build_report_unavailable_when_lineup_data_empty_dict():
    im = _manager()
    report = im.build_injury_report_from_raw_lineup({}, team_id=1, team_name="Arsenal")

    assert report.data_quality == "unavailable"


def test_build_report_is_pure_zero_io_zero_api_dependency():
    """Regresie directă: funcția nu are nevoie de self._api/self._cache —
    poate fi apelată pe o instanță InjuryManager() fără provider injectat,
    exact cazul din oracle_engine.py (Database-First, fără FootballOracleAPI
    pentru acest calcul)."""
    im = InjuryManager(api=None, cache=None)
    report = im.build_injury_report_from_raw_lineup(_LINEUP_WITH_KEY_ABSENCE, team_id=1, team_name="Arsenal")
    assert report.total_xg_penalty < 0


def test_build_report_parity_with_live_fetch_path():
    """Paritate explicită: get_lineup_absences() (calea live, Sync Layer)
    trebuie să producă EXACT același TeamInjuryReport ca apelul direct la
    build_injury_report_from_raw_lineup() cu același payload — dovedește că
    refactorizarea (R-Sync-10) e o extragere, nu o reimplementare."""
    fake_api = SimpleNamespace(get_lineup=lambda event_id, is_home: _LINEUP_WITH_KEY_ABSENCE)
    im_live = InjuryManager(api=fake_api, cache=None)
    live_report = im_live.get_lineup_absences(
        event_id=123, team_id=1, team_name="Arsenal", is_home=True,
    )

    im_pure = InjuryManager()
    pure_report = im_pure.build_injury_report_from_raw_lineup(
        _LINEUP_WITH_KEY_ABSENCE, team_id=1, team_name="Arsenal",
    )

    assert live_report.total_xg_penalty == pure_report.total_xg_penalty
    assert live_report.has_key_absences == pure_report.has_key_absences
    assert live_report.data_quality == pure_report.data_quality
    assert len(live_report.absences) == len(pure_report.absences)
    assert live_report.absences[0].xg_impact == pure_report.absences[0].xg_impact


# ── apply_injury_penalty() — neschimbată, verificare de regresie ─────────

def test_apply_injury_penalty_uses_db_first_report_identically():
    im = _manager()
    home_report = im.build_injury_report_from_raw_lineup(_LINEUP_WITH_KEY_ABSENCE, 1, "Arsenal")
    away_report = TeamInjuryReport(team_name="Chelsea", team_id=2)  # fără absențe

    home_xg_new, away_xg_new, note = im.apply_injury_penalty(2.0, 1.5, home_report, away_report)

    assert home_xg_new < 2.0
    assert away_xg_new == 1.5
    assert "Arsenal" in note
