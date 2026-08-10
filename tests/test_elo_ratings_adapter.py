"""Teste pentru elo_ratings_adapter.py (R-Sync-4, ADR-039).

[ACTUALIZAT — corectare 2026-08-10] `fetch()` nu mai delegă la
`oracle_api.get_national_elo_ratings_raw()` (care nu a funcționat
niciodată real — eloratings.net randază tabelul 100% client-side,
BeautifulSoup pe HTML brut nu găsea niciodată date, confirmat prin POC
izolat live). Acum randează pagina (Playwright, izolat prin
`_fetch_rendered_html()`) și parsează HTML-ul randat printr-o funcție
PURĂ (`parse_elo_ratings_html()`), testabilă offline, fără browser."""
from __future__ import annotations

from elo_ratings_adapter import EloRatingsAdapter, parse_elo_ratings_html


# ── parse_elo_ratings_html() — funcție pură, fixture bazat pe structura
# reală confirmată live (POC izolat, 2026-08-10): .slick-row > .slick-cell,
# coloana 1 = nume, coloana 2 = ELO. Valorile de mai jos sunt cele reale,
# capturate live (rândurile 0-3 din rularea reușită).
_REAL_STRUCTURE_HTML = """
<html><body><div class="grid-canvas">
  <div class="slick-row">
    <div class="slick-cell">1</div><div class="slick-cell">Spain</div><div class="slick-cell">2259</div>
  </div>
  <div class="slick-row">
    <div class="slick-cell">2</div><div class="slick-cell">Argentina</div><div class="slick-cell">2173</div>
  </div>
  <div class="slick-row">
    <div class="slick-cell">3</div><div class="slick-cell">England</div><div class="slick-cell">2125</div>
  </div>
  <div class="slick-row">
    <div class="slick-cell">4</div><div class="slick-cell">France</div><div class="slick-cell">2070</div>
  </div>
</div></body></html>
"""


def test_parse_elo_ratings_html_extracts_name_and_elo_from_real_structure():
    ratings = parse_elo_ratings_html(_REAL_STRUCTURE_HTML)
    assert ratings == {"Spain": 2259, "Argentina": 2173, "England": 2125, "France": 2070}


def test_parse_elo_ratings_html_empty_when_no_slick_rows():
    """Randare brută (fără JS executat) — exact ce întorcea site-ul înainte
    de fix: 0 rânduri .slick-row, 0 date."""
    assert parse_elo_ratings_html("<html><body>no grid here</body></html>") == {}


def test_parse_elo_ratings_html_skips_row_with_too_few_cells():
    html = """<div class="slick-row"><div class="slick-cell">1</div></div>"""
    assert parse_elo_ratings_html(html) == {}


def test_parse_elo_ratings_html_skips_row_with_non_numeric_elo():
    html = """<div class="slick-row">
      <div class="slick-cell">1</div><div class="slick-cell">Ghost FC</div><div class="slick-cell">N/A</div>
    </div>"""
    assert parse_elo_ratings_html(html) == {}


def test_parse_elo_ratings_html_handles_comma_thousands_separator():
    html = """<div class="slick-row">
      <div class="slick-cell">1</div><div class="slick-cell">Spain</div><div class="slick-cell">2,259</div>
    </div>"""
    assert parse_elo_ratings_html(html) == {"Spain": 2259}


# ── fetch() — izolat de randarea Playwright prin monkeypatch la
# _fetch_rendered_html() (tiparul deja folosit pentru _discover_for_hub în
# providers/flashscore/discovery.py: page.content() -> funcție pură) ───────

def test_fetch_returns_none_when_render_fails(monkeypatch):
    import elo_ratings_adapter as mod
    monkeypatch.setattr(mod, "_fetch_rendered_html", lambda: None)
    adapter = EloRatingsAdapter()
    assert adapter.fetch({}) is None


def test_fetch_parses_rendered_html(monkeypatch):
    import elo_ratings_adapter as mod
    monkeypatch.setattr(mod, "_fetch_rendered_html", lambda: _REAL_STRUCTURE_HTML)
    adapter = EloRatingsAdapter()
    raw = adapter.fetch({})
    assert raw == {"Spain": 2259, "Argentina": 2173, "England": 2125, "France": 2070}


# ── normalize/validate/persist/coverage_check — neschimbate ────────────────

_RAW_RATINGS = {
    "France": 2085,
    "Brazil": 2050,
    "Unranked FC": 0,   # invalid — exclus de validate()
}


def test_normalize_handles_none_payload():
    adapter = EloRatingsAdapter()
    assert adapter.normalize(None) == []


def test_normalize_handles_empty_payload():
    adapter = EloRatingsAdapter()
    assert adapter.normalize({}) == []


def test_normalize_produces_multiple_records_per_call():
    adapter = EloRatingsAdapter()
    records = adapter.normalize(_RAW_RATINGS)
    assert len(records) == 3
    by_name = {r["team_name"]: r["elo_rating"] for r in records}
    assert by_name["France"] == 2085
    assert by_name["Brazil"] == 2050


def test_normalize_calls_canonical_normalize_team_name_explicitly(monkeypatch):
    """Regresie directă, oglindă a verificării cerute la R-Sync-2/R-Sync-3:
    normalize() apelează EXPLICIT mecanismul canonic existent
    (mappings.normalize_team_name), chiar dacă sursa (eloratings.net)
    nu garantează nume deja canonice."""
    import mappings

    calls = []

    def _fake_normalize(name):
        calls.append(name)
        return f"CANONICAL[{name}]"

    monkeypatch.setattr(mappings, "normalize_team_name", _fake_normalize)
    adapter = EloRatingsAdapter()
    records = adapter.normalize({"France": 2085})

    assert calls == ["France"]
    assert records[0]["team_name"] == "CANONICAL[France]"


def test_validate_excludes_records_without_team_name():
    adapter = EloRatingsAdapter()
    records = [{"team_name": "France", "elo_rating": 2085}, {"elo_rating": 2050}]
    out = adapter.validate(records)
    assert out == [{"team_name": "France", "elo_rating": 2085}]


def test_validate_excludes_records_with_non_positive_elo():
    adapter = EloRatingsAdapter()
    records = [
        {"team_name": "France", "elo_rating": 2085},
        {"team_name": "Unranked FC", "elo_rating": 0},
        {"team_name": "Negative FC", "elo_rating": -5},
    ]
    out = adapter.validate(records)
    assert len(out) == 1
    assert out[0]["team_name"] == "France"


def test_persist_calls_upsert_national_team_elo_per_record(monkeypatch):
    calls = []

    def _fake_upsert(team, elo_rating):
        calls.append((team, elo_rating))
        return True

    monkeypatch.setattr("database.queries.upsert_national_team_elo", _fake_upsert)
    adapter = EloRatingsAdapter()
    ok = adapter.persist([{"team_name": "France", "elo_rating": 2085}])
    assert ok is True
    assert calls == [("France", 2085)]


def test_persist_returns_false_if_any_write_fails(monkeypatch):
    def _fake_upsert(team, elo_rating):
        return team == "France"

    monkeypatch.setattr("database.queries.upsert_national_team_elo", _fake_upsert)
    adapter = EloRatingsAdapter()
    ok = adapter.persist([
        {"team_name": "France", "elo_rating": 2085},
        {"team_name": "Brazil", "elo_rating": 2050},
    ])
    assert ok is False


def test_full_pipeline_fetch_normalize_validate_persist(monkeypatch):
    """End-to-end pe adaptorul complet, fara randare reala si fara Supabase real."""
    import elo_ratings_adapter as mod
    monkeypatch.setattr(mod, "_fetch_rendered_html", lambda: _REAL_STRUCTURE_HTML)

    calls = []

    def _fake_upsert(team, elo_rating):
        calls.append(team)
        return True

    monkeypatch.setattr("database.queries.upsert_national_team_elo", _fake_upsert)
    adapter = EloRatingsAdapter()

    raw = adapter.fetch({})
    records = adapter.normalize(raw)
    records = adapter.validate(records)
    ok = adapter.persist(records)

    assert ok is True
    assert sorted(calls) == ["Argentina", "England", "France", "Spain"]


def test_coverage_check_returns_true_deliberately():
    """Documentează comportamentul cerut explicit, oglindă a
    footballdata_form_adapter.coverage_check(): suprascris EXPLICIT (nu
    moștenit implicit din SyncAdapter), True fix, deliberat — fără concept
    de coverage pentru eloratings.net."""
    adapter = EloRatingsAdapter()
    assert adapter.coverage_check({"league": "orice"}) is True
    assert "coverage_check" in EloRatingsAdapter.__dict__
