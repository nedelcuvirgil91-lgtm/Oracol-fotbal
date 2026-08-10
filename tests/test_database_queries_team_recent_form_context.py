"""Teste pentru database.queries.get_team_recent_form_context() — sursă
NOUĂ de formă reală per echipă, adăugată 2026-08-10 după ce s-a confirmat
că flashscore_match_context (recent_form_home/away, normalize_match_
context(), deja parte din pipeline-ul standard H2H) conține deja date
reale, nefolosite de cascada de profil — funcționează pentru orice
echipă/țară/competiție, spre deosebire de Level FS (clasament domestic),
care nu acoperă niciodată fazele eliminatorii ale cupelor europene sau
echipele străine (caz real confirmat live: Univ. Craiova vs KuPS,
Europa League calificări, 2026-08-10).

Selecție prin `subject_team` (migrația 046) — NU prin poziția home/away a
rândului, care variază real per meci (verificat live: Univ. Craiova
apare pe ambele părți în rânduri diferite ale propriei secțiuni).

Fake client care filtrează un set de rânduri în memorie după eq/in_/
order/limit, mai fidel comportamentului real Supabase decât un fake care
ignoră filtrele."""
from __future__ import annotations

import database.queries as q


class _FakeResult:
    def __init__(self, data):
        self.data = data


class _FakeQuery:
    def __init__(self, rows):
        self._rows = list(rows)

    def select(self, *a, **kw):
        return self

    def eq(self, field, value):
        self._rows = [r for r in self._rows if r.get(field) == value]
        return self

    def in_(self, field, values):
        self._rows = [r for r in self._rows if r.get(field) in values]
        return self

    def order(self, field, desc=False):
        self._rows = sorted(self._rows, key=lambda r: r.get(field, 0), reverse=desc)
        return self

    def limit(self, n):
        self._rows = self._rows[:n]
        return self

    def execute(self):
        return _FakeResult(self._rows)


class _FakeClient:
    def __init__(self, rows):
        self._rows = rows

    def table(self, name):
        return _FakeQuery(self._rows)


def _client(rows, monkeypatch) -> None:
    monkeypatch.setattr(q, "get_client", lambda: _FakeClient(rows))


def _row(context_match_id, category, subject_team, meeting_order, meeting_date,
         home_team, away_team, home_score, away_score):
    return {
        "context_match_id": context_match_id, "category": category, "subject_team": subject_team,
        "meeting_order": meeting_order, "meeting_date": meeting_date,
        "home_team": home_team, "away_team": away_team,
        "home_score": home_score, "away_score": away_score,
    }


def test_returns_empty_when_client_unavailable(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: None)
    assert q.get_team_recent_form_context("Univ. Craiova") == []


def test_degrades_gracefully_on_exception(monkeypatch):
    class _RaisingClient:
        def table(self, name):
            raise RuntimeError("boom")
    monkeypatch.setattr(q, "get_client", lambda: _RaisingClient())
    assert q.get_team_recent_form_context("Univ. Craiova") == []


def test_derives_win_loss_draw_from_correct_side(monkeypatch):
    """Craiova apare pe ambele părți în rânduri diferite ale ACELEIAȘI
    secțiuni — W/D/L trebuie derivat per rând, nu presupus mereu home.
    Selecția rândurilor e prin subject_team (nu prin poziția rândului)."""
    rows = [
        _row(131273, "recent_form_away", "Univ. Craiova", 0, "2026-08-09", "Univ. Craiova", "FC Arges", 0, 1),
        _row(131273, "recent_form_away", "Univ. Craiova", 1, "2026-08-06", "KuPS", "Univ. Craiova", 1, 1),
        _row(131273, "recent_form_away", "Univ. Craiova", 2, "2026-08-01", "Univ. Craiova", "Petrolul", 4, 0),
    ]
    _client(rows, monkeypatch)
    results = q.get_team_recent_form_context("Univ. Craiova", n=5)
    # cronologic: cel mai vechi primul (order=2) -> cel mai recent ultimul (order=0)
    assert [r["result"] for r in results] == ["W", "D", "L"]
    assert [r["goals_for"] for r in results] == [4, 1, 0]
    assert [r["goals_against"] for r in results] == [0, 1, 1]


def test_ignores_rows_with_different_subject_team_same_context(monkeypatch):
    """recent_form_home (adversarul) NU trebuie amestecat cu
    recent_form_away (Craiova) doar pentru că au același context_match_id."""
    rows = [
        _row(131273, "recent_form_away", "Univ. Craiova", 0, "2026-08-09", "Univ. Craiova", "FC Arges", 0, 1),
        _row(131273, "recent_form_home", "FC Rapid Bucuresti", 0, "2026-08-07", "UTA Arad", "FC Rapid Bucuresti", 0, 0),
    ]
    _client(rows, monkeypatch)
    results = q.get_team_recent_form_context("Univ. Craiova")
    assert len(results) == 1
    assert results[0]["result"] == "L"


def test_ignores_h2h_overall_category_even_with_matching_teams(monkeypatch):
    rows = [
        _row(1, "h2h_overall", None, 0, "2026-07-01", "Univ. Craiova", "FC Rapid Bucuresti", 1, 0),
    ]
    _client(rows, monkeypatch)
    assert q.get_team_recent_form_context("Univ. Craiova") == []


def test_rows_without_subject_team_not_visible_pre_migration(monkeypatch):
    """Rânduri vechi (persistate înainte de migrația 046, subject_team
    NULL) nu apar — se completează natural la următoarea resincronizare,
    fără backfill forțat."""
    rows = [
        _row(1, "recent_form_home", None, 0, "2026-07-01", "Univ. Craiova", "Team B", 1, 0),
    ]
    _client(rows, monkeypatch)
    assert q.get_team_recent_form_context("Univ. Craiova") == []


def test_picks_most_recent_context_only_not_mixed_snapshots(monkeypatch):
    """Nu amestecă rânduri din snapshot-uri (context_match_id) diferite —
    doar cel mai recent, coerent."""
    rows = [
        _row(100, "recent_form_home", "Univ. Craiova", 0, "2026-07-01", "Univ. Craiova", "Old Opponent", 1, 0),
        _row(200, "recent_form_home", "Univ. Craiova", 0, "2026-08-05", "Univ. Craiova", "New Opponent", 2, 2),
    ]
    _client(rows, monkeypatch)
    results = q.get_team_recent_form_context("Univ. Craiova")
    assert len(results) == 1
    assert results[0]["result"] == "D"


def test_tolerates_advancing_note_suffix_on_opponent_name(monkeypatch):
    """Rândurile deja persistate cu glitch-ul de scraping pe numele
    ADVERSARULUI ("...Advancing to next round: ...") nu trebuie să
    blocheze derivarea rezultatului echipei-subiect."""
    rows = [
        _row(131057, "recent_form_home", "Univ. Craiova", 0, "2026-08-01",
             "Univ. Craiova", "Levski SofiaAdvancing to next round: Levski Sofia", 4, 0),
    ]
    _client(rows, monkeypatch)
    results = q.get_team_recent_form_context("Univ. Craiova")
    assert len(results) == 1
    assert results[0]["result"] == "W"


def test_works_for_team_never_in_any_tracked_domestic_league(monkeypatch):
    """Cazul real care a motivat feature-ul: KuPS (Finlanda) nu are
    clasament (Level FS) în nicio ligă urmărită, dar are formă reală în
    flashscore_match_context — cu condiția să existe un rând acolo."""
    rows = [
        _row(131273, "recent_form_home", "KuPS", 0, "2026-08-06", "KuPS", "Univ. Craiova", 1, 1),
    ]
    _client(rows, monkeypatch)
    results = q.get_team_recent_form_context("KuPS")
    assert len(results) == 1
    assert results[0]["result"] == "D"


def test_returns_empty_when_team_never_appears(monkeypatch):
    rows = [_row(1, "recent_form_home", "Team A", 0, "2026-08-01", "Team A", "Team B", 1, 0)]
    _client(rows, monkeypatch)
    assert q.get_team_recent_form_context("Nonexistent Team") == []


def test_rows_with_missing_score_are_skipped(monkeypatch):
    rows = [
        _row(1, "recent_form_home", "Univ. Craiova", 0, "2026-08-01", "Univ. Craiova", "Team B", None, None),
        _row(1, "recent_form_home", "Univ. Craiova", 1, "2026-07-25", "Univ. Craiova", "Team C", 2, 0),
    ]
    _client(rows, monkeypatch)
    results = q.get_team_recent_form_context("Univ. Craiova")
    assert len(results) == 1
    assert results[0]["result"] == "W"


def test_respects_n_limit_after_selecting_latest_context(monkeypatch):
    rows = [
        _row(1, "recent_form_home", "Univ. Craiova", i, f"2026-07-{20-i:02d}", "Univ. Craiova", f"Opp{i}", 1, 0)
        for i in range(5)
    ]
    _client(rows, monkeypatch)
    results = q.get_team_recent_form_context("Univ. Craiova", n=3)
    assert len(results) == 3
