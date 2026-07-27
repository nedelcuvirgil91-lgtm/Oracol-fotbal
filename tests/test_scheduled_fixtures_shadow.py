"""Teste pentru scheduled_fixtures_shadow.py (R-Sync-7b, ADR-039/ADR-040, G2)
— evaluator PUR: fără Supabase, fără logging (mutat în alte module la G2).
scheduled_rows injectat direct, ca listă — simulează
database.queries.list_scheduled_fixtures()."""
from __future__ import annotations

import equivalence_root_cause as root_cause
import scheduled_fixtures_shadow as mod

_KO_DATE = "2026-08-01"


def _live_match(**overrides) -> dict:
    base = {
        "home_team": "Arsenal", "away_team": "Chelsea",
        "kickoff_date": _KO_DATE, "kickoff_utc": f"{_KO_DATE}T15:00:00Z",
        "league": "Premier League", "venue_city": "London",
        "source": "freelivefootball",
        "home_team_id": "freelf_1", "away_team_id": "freelf_2",
        "_freelf_event_id": "999",
    }
    base.update(overrides)
    return base


def _scheduled_row(**overrides) -> dict:
    base = {
        "home_team_canonical": "arsenal", "away_team_canonical": "chelsea",
        "kickoff_date": _KO_DATE,
        "league": "Premier League", "kickoff_utc": f"{_KO_DATE}T15:00:00Z",
        "venue_city": "London",
        "freelf_event_id": "999", "freelf_home_team_id": "freelf_1",
        "freelf_away_team_id": "freelf_2",
    }
    base.update(overrides)
    return base


def test_evaluator_has_no_io_or_logging_dependencies():
    """Regula de Aur #2 -- dovadă structurală: evaluatorul pur nu importă
    nimic din database.queries, supabase_client sau logging (ADR-040, G2,
    principiul 1)."""
    import ast
    import inspect

    src = inspect.getsource(mod)
    tree = ast.parse(src)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    assert "logging" not in imported
    assert "database.queries" not in imported
    assert "supabase_client" not in imported
    assert not hasattr(mod, "log_report"), "log_report a fost eliminat la G2 -- persistenta traieste in alt modul"


def test_perfect_match_is_clean_and_has_zero_diffs():
    report = mod.evaluate([_live_match()], [_scheduled_row()])

    assert report.live_count == 1
    assert report.scheduled_count == 1
    assert report.matched == 1
    assert report.missing_scheduled_count == 0
    assert report.missing_live_count == 0
    assert report.field_difference_count == 0
    assert report.provider_id_difference_count == 0
    assert report.accepted_exception_count == 0
    assert report.is_clean is True
    assert report.provider_breakdown == {"freelivefootball": {"matched": 1, "field_diff": 0, "id_diff": 0, "missing_scheduled": 0}}
    assert report.root_cause_summary == {}


def test_missing_scheduled_when_row_absent():
    report = mod.evaluate([_live_match()], [])

    assert report.live_count == 1
    assert report.scheduled_count == 0
    assert report.matched == 0
    assert report.missing_scheduled_count == 1
    assert report.missing_live_count == 0
    assert report.is_clean is False
    assert report.provider_breakdown["freelivefootball"]["missing_scheduled"] == 1
    assert report.root_cause_summary == {root_cause.PROVIDER_TIMEOUT: 1}


def test_missing_live_detects_phantom_scheduled_row():
    phantom_row = _scheduled_row(
        home_team_canonical="realmadrid", away_team_canonical="barcelona",
    )
    report = mod.evaluate([_live_match()], [_scheduled_row(), phantom_row])

    assert report.live_count == 1
    assert report.scheduled_count == 2
    assert report.matched == 1
    assert report.missing_live_count == 1
    assert report.missing_scheduled_count == 0
    assert report.is_clean is False
    assert report.root_cause_summary == {root_cause.UNKNOWN: 1}


def test_zero_matches_and_zero_rows_is_clean():
    report = mod.evaluate([], [])
    assert report.live_count == 0
    assert report.scheduled_count == 0
    assert report.is_clean is True
    assert report.provider_breakdown == {}


def test_field_difference_detected_for_venue_city_unknown_provider_stays_unaccepted():
    """venue_city la un provider FĂRĂ excepție cunoscută (freelf) rămâne
    NEacceptată -- doar football-data.org are gap documentat (R-Sync-7a)."""
    report = mod.evaluate(
        [_live_match(venue_city="London")],
        [_scheduled_row(venue_city="Manchester")],
    )

    assert report.field_difference_count == 1
    diff = report.field_differences[0]
    assert diff["field"] == "venue_city"
    assert diff["live"] == "London"
    assert diff["scheduled"] == "Manchester"
    assert diff["exception_policy"] is None
    assert report.accepted_exception_count == 0
    assert report.is_clean is False
    assert report.provider_breakdown["freelivefootball"]["field_diff"] == 1
    assert report.root_cause_summary == {root_cause.VENUE_PRIORITY: 1}


def test_known_exception_footballdata_venue_city_is_accepted():
    report = mod.evaluate(
        [_live_match(source="football-data.org", venue_city="London",
                     home_team_id="fd_1", away_team_id="fd_2", _freelf_event_id=None)],
        [_scheduled_row(venue_city="Manchester",
                         fd_home_team_id="fd_1", fd_away_team_id="fd_2",
                         freelf_event_id=None, freelf_home_team_id=None, freelf_away_team_id=None)],
    )

    assert report.field_difference_count == 1
    assert report.accepted_exception_count == 1
    diff = report.field_differences[0]
    assert diff["exception_policy"] == "SAFE"
    # excepție acceptată -> NU se numără la field_diff-ul din breakdown
    assert report.provider_breakdown["football-data.org"]["field_diff"] == 0


def test_known_exception_kickoff_utc_expected_for_any_provider():
    report = mod.evaluate(
        [_live_match(kickoff_utc=f"{_KO_DATE}T16:00:00Z")],
        [_scheduled_row(kickoff_utc=f"{_KO_DATE}T15:00:00Z")],
    )
    assert report.field_difference_count == 1
    assert report.accepted_exception_count == 1
    assert report.field_differences[0]["exception_policy"] == "EXPECTED"


def test_field_difference_ignores_empty_vs_none_equivalence():
    report = mod.evaluate(
        [_live_match(venue_city="")],
        [_scheduled_row(venue_city=None)],
    )
    assert report.field_difference_count == 0


def test_provider_id_difference_detected_for_freelf_event_id():
    report = mod.evaluate(
        [_live_match(_freelf_event_id="999")],
        [_scheduled_row(freelf_event_id="111")],
    )

    assert report.provider_id_difference_count == 1
    diff = report.provider_id_differences[0]
    assert diff["provider"] == "freelf"
    assert diff["field"] == "freelf_event_id"
    assert diff["live"] == "999"
    assert diff["scheduled"] == "111"
    assert report.root_cause_summary == {root_cause.UNKNOWN: 1}
    assert report.provider_breakdown["freelivefootball"]["id_diff"] == 1


def test_provider_id_difference_when_scheduled_missing_the_id_entirely():
    report = mod.evaluate([_live_match()], [_scheduled_row(freelf_event_id=None)])
    assert report.provider_id_difference_count == 1
    assert report.provider_id_differences[0]["scheduled"] is None
    assert report.root_cause_summary == {root_cause.MISSING_PROVIDER_ID: 1}


def test_provider_id_differences_never_appear_in_known_exceptions():
    """Regulă structurală ADR-040 principiul 5: provider_id_differences nu
    intră NICIODATĂ în mecanismul exception_policy -- verificat prin
    inspecția directă a KNOWN_EXCEPTIONS."""
    for (field, _provider) in mod.KNOWN_EXCEPTIONS:
        assert field in mod._GOVERNED_FIELDS, (
            f"{field} nu e un câmp guvernat -- provider_id_differences nu ar trebui "
            "să poată fi vreodată în KNOWN_EXCEPTIONS"
        )


def test_odds_api_source_checks_event_id_and_sport_key():
    matches = [_live_match(
        source="the-odds-api", home_team_id=None, away_team_id=None,
        _freelf_event_id=None, _odds_api_id=42, _sport_key="soccer_epl",
    )]
    rows = [_scheduled_row(
        odds_api_event_id="42", odds_api_sport_key="soccer_epl",
        freelf_event_id=None, freelf_home_team_id=None, freelf_away_team_id=None,
    )]
    report = mod.evaluate(matches, rows)
    assert report.provider_id_difference_count == 0


def test_apifootball_source_checks_fixture_id_and_team_ids():
    matches = [_live_match(
        source="apifootball", home_team_id="apifootball_1", away_team_id="apifootball_2",
        fixture_id="apifootball_777", _freelf_event_id=None,
    )]
    rows = [_scheduled_row(
        apifootball_fixture_id="apifootball_777",
        apifootball_home_team_id="apifootball_1",
        apifootball_away_team_id="apifootball_2",
        freelf_event_id=None, freelf_home_team_id=None, freelf_away_team_id=None,
    )]
    report = mod.evaluate(matches, rows)
    assert report.provider_id_difference_count == 0


def test_provider_breakdown_derived_from_data_not_hardcoded_list():
    """ADR-040 principiul 3: providerii raportați sunt exact cei întâlniți în
    date -- niciun provider absent din matches nu apare în provider_breakdown."""
    report = mod.evaluate([_live_match(source="thesportsdb", home_team_id="tsdb_1", away_team_id="tsdb_2",
                                        _freelf_event_id=None)],
                           [_scheduled_row(tsdb_home_team_id="tsdb_1", tsdb_away_team_id="tsdb_2",
                                            freelf_event_id=None, freelf_home_team_id=None, freelf_away_team_id=None)])
    assert set(report.provider_breakdown.keys()) == {"thesportsdb"}


def test_demo_matches_excluded_from_comparison_entirely():
    report = mod.evaluate([_live_match(source="demo-premier-league")], [_scheduled_row()])

    assert report.live_count == 0
    assert report.scheduled_count == 1
    assert report.missing_live_count == 1
    assert report.provider_breakdown == {}


def test_match_missing_identity_fields_skipped_not_crashed():
    report = mod.evaluate([_live_match(home_team="")], [])
    assert report.live_count == 0


def test_scheduled_row_missing_identity_fields_skipped_not_crashed():
    report = mod.evaluate([], [_scheduled_row(home_team_canonical="")])
    assert report.scheduled_count == 0


def test_examples_capped_but_counts_stay_exact_beyond_cap():
    """Bug găsit la G2 auto-audit: len() pe listele plafonate ar subnumăra
    dacă diferențele reale depășesc MAX_EXAMPLES -- count-urile trebuie să
    rămână exacte, doar eșantioanele se plafonează."""
    matches = [
        _live_match(home_team=f"Team{i}", away_team=f"Rival{i}")
        for i in range(mod.MAX_EXAMPLES + 5)
    ]
    report = mod.evaluate(matches, [])
    assert report.live_count == mod.MAX_EXAMPLES + 5
    assert report.missing_scheduled_count == mod.MAX_EXAMPLES + 5
    assert len(report.missing_scheduled) == mod.MAX_EXAMPLES
