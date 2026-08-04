"""Teste pentru providers/flashscore/discovery.py (Foundation Data Layer,
ADR-044, M1) — fara retea.

`parse_match_links()` e testata direct contra evidentei brute REALE,
capturate live in aceasta sesiune (docs/06_UDAL/poc_evidence/
flashscore_10matches/*_hub_raw.html) - nu contra unui fixture inventat."""
from __future__ import annotations

from pathlib import Path

import pytest

from providers.flashscore.adapter import FlashscoreAdapter
from providers.flashscore.discovery import (
    DEFAULT_LIMIT_PER_LEAGUE_AUTOMATED,
    FLASHSCORE_LIMIT_PER_LEAGUE_CONFIG_KEY,
    FLASHSCORE_TRACKED_COMPETITIONS,
    DiscoveredMatch,
    _discover_for_hub,
    discover_matches,
    get_limit_per_league_automated,
    parse_match_links,
    run_foundation_data_layer_for_discovered_matches,
)

EVIDENCE_DIR = Path(__file__).parent.parent / "docs" / "06_UDAL" / "poc_evidence" / "flashscore_10matches"


def test_tracked_competitions_only_contains_verified_slugs():
    """Regresie - orice liga noua adaugata aici fara verificare (live sau
    prin cautare web, vezi docstring modul) ar trebui sa fie o schimbare
    deliberata, vizibila la code review, nu tacita."""
    assert FLASHSCORE_TRACKED_COMPETITIONS == {
        "Romania SuperLiga": ("romania", "superliga"),
        "Champions League": ("europe", "champions-league"),
        "Premier League": ("england", "premier-league"),
        "La Liga": ("spain", "laliga"),
        "Serie A": ("italy", "serie-a"),
        "Bundesliga": ("germany", "bundesliga"),
        "Ligue 1": ("france", "ligue-1"),
        "Europa League": ("europe", "europa-league"),
        "MLS": ("usa", "mls"),
        "Primeira Liga": ("portugal", "liga-portugal"),
        "Eredivisie": ("netherlands", "eredivisie"),
        "Super Lig": ("turkey", "super-lig"),
        "HNL": ("croatia", "hnl"),
    }


def test_tracked_competition_keys_are_all_canonical_league_names():
    """Gardă directă contra regresiei găsite în audit (Faza 2): o cheie
    FLASHSCORE_TRACKED_COMPETITIONS care e doar un ALIAS (nu forma
    canonică din mappings.LEAGUE_ALIASES) ar face ca meciurile colectate
    să nu fie găsite NICIODATĂ de Oracle Engine la interogare pe `league`."""
    from mappings import normalize_league_name

    for league_key in FLASHSCORE_TRACKED_COMPETITIONS:
        assert normalize_league_name(league_key) == league_key, (
            f"'{league_key}' nu e forma canonică — normalize_league_name() "
            f"întoarce '{normalize_league_name(league_key)}'. Folosește "
            f"forma canonică direct ca cheie."
        )


def test_parse_match_links_on_real_superliga_hub_evidence():
    html = (EVIDENCE_DIR / "superliga_results_hub_raw.html").read_text(encoding="utf-8")
    pairs = parse_match_links(html)
    assert len(pairs) == 16
    base, mid = pairs[0]
    assert base == "https://www.flashscore.com/match/football/fc-botosani-GjY1JjUS/rapid-bucuresti-YFCpigVG"
    assert mid == "EeqI7WJc"
    assert all(not b.endswith("/") and "?" not in b for b, _ in pairs)
    assert len({b for b, _ in pairs}) == len(pairs)


def test_parse_match_links_on_real_ucl_hub_evidence():
    html = (EVIDENCE_DIR / "ucl_results_hub_raw.html").read_text(encoding="utf-8")
    pairs = parse_match_links(html)
    assert len(pairs) == 28


def test_parse_match_links_empty_html():
    assert parse_match_links("<html><body>no matches</body></html>") == []


def test_parse_match_links_ignores_links_without_mid():
    html = '<a href="https://www.flashscore.com/match/football/a-1/b-2/">no mid param</a>'
    assert parse_match_links(html) == []


def test_discover_matches_rejects_unknown_league():
    with pytest.raises(ValueError):
        discover_matches(leagues=["Not A Tracked League"])


def test_discovered_match_is_frozen_dataclass():
    m = DiscoveredMatch(league="Romania SuperLiga", match_base_url="https://x", mid="abc", source="results")
    with pytest.raises(Exception):
        m.mid = "changed"  # type: ignore[misc]


def test_run_foundation_data_layer_passes_league_to_persist(monkeypatch):
    """[FIX live, gasit la al treilea run live real] match_history.league
    e NOT NULL - Discovery deja cunoaste liga (a ales-o explicit ca sa
    construiasca URL-ul), trebuie sa o transmita mai departe la persist(),
    nu doar la fetch()."""
    monkeypatch.setattr(FlashscoreAdapter, "preflight", lambda self: None)
    monkeypatch.setattr(FlashscoreAdapter, "fetch", lambda self, params: {"summary": "<html></html>"})
    monkeypatch.setattr(FlashscoreAdapter, "normalize", lambda self, raw: [raw])
    monkeypatch.setattr(
        FlashscoreAdapter, "validate",
        lambda self, records: [{
            "home_team": "A", "away_team": "B", "kickoff_date": "2026-08-01T18:00:00",
            "_pages": records[0],
        }],
    )
    calls = []
    monkeypatch.setattr(
        "providers.flashscore.persistence.persist_match_with_data_trust_layer",
        lambda pages, match_ref, **kw: calls.append(kw) or {"ok": True},
    )

    match = DiscoveredMatch(league="Romania SuperLiga", match_base_url="https://x", mid="abc", source="results")
    reports = run_foundation_data_layer_for_discovered_matches([match])

    assert reports == [{"ok": True, "match": match}]
    assert calls == [{"league": "Romania SuperLiga", "competition": "Romania SuperLiga"}]


def test_run_foundation_data_layer_skips_already_collected_match_delta_sync(monkeypatch):
    """Delta Sync (Faza 2) — dacă mid-ul e deja canonic persistat
    (is_flashscore_match_already_collected == True), fetch()/persist() NU
    se apelează deloc pentru acel meci."""
    monkeypatch.setattr(FlashscoreAdapter, "preflight", lambda self: None)
    fetch_calls = []
    monkeypatch.setattr(
        FlashscoreAdapter, "fetch",
        lambda self, params: fetch_calls.append(params) or {"summary": "<html></html>"},
    )
    monkeypatch.setattr(
        "database.queries.is_flashscore_match_already_collected",
        lambda mid: mid == "already-seen",
    )

    seen = DiscoveredMatch(league="Romania SuperLiga", match_base_url="https://x", mid="already-seen", source="results")
    new = DiscoveredMatch(league="Romania SuperLiga", match_base_url="https://y", mid="new-mid", source="results")
    monkeypatch.setattr(FlashscoreAdapter, "normalize", lambda self, raw: [raw])
    monkeypatch.setattr(
        FlashscoreAdapter, "validate",
        lambda self, records: [{
            "home_team": "A", "away_team": "B", "kickoff_date": "2026-08-01T18:00:00",
            "_pages": records[0],
        }],
    )
    monkeypatch.setattr(
        "providers.flashscore.persistence.persist_match_with_data_trust_layer",
        lambda pages, match_ref, **kw: {"ok": True},
    )

    reports = run_foundation_data_layer_for_discovered_matches([seen, new])

    assert reports[0] == {"match_id": None, "ok": True, "skipped": True, "reason": "already_collected", "match": seen}
    assert reports[1]["ok"] is True and not reports[1].get("skipped")
    assert fetch_calls == [{"match_base_url": "https://y", "mid": "new-mid"}]


# ════════════════════════════════════════════════════════════════════════
# _discover_for_hub — include_future_fixtures (Pasul 1 Master Repair Plan,
# rafinat dupa feedback) — vezi docstring _discover_for_hub() pentru
# justificarea completa: rularile automate NU mai incearca /fixtures/
# deloc, in loc sa incerce o cross-referentiere fragila cu
# scheduled_fixtures.
# ════════════════════════════════════════════════════════════════════════

_MATCH_HTML = '<a href="/match/football/team-a-AAAAAAAA/team-b-BBBBBBBB?mid=XYZ123"></a>'
_EMPTY_HTML = "<html><body>no matches</body></html>"


class _FakeResponse:
    def __init__(self, status=200):
        self.status = status


class _FakePage:
    """Fake Playwright page — `content_by_source` mapeaza `"results"`/
    `"fixtures"` la HTML-ul intors dupa navigare la acel hub. Inregistreaza
    fiecare `goto()` ca sa se poata verifica exact ce hub-uri au fost
    incercate."""
    def __init__(self, content_by_source: dict[str, str]):
        self._content_by_source = content_by_source
        self._current = ""
        self.urls_visited: list[str] = []

    def goto(self, url, wait_until=None, timeout=None):
        self.urls_visited.append(url)
        source = "results" if url.rstrip("/").endswith("/results") else "fixtures"
        self._current = self._content_by_source.get(source, _EMPTY_HTML)
        return _FakeResponse()

    def wait_for_timeout(self, ms):
        pass

    def content(self):
        return self._current


def test_discover_for_hub_tries_fixtures_when_results_empty_and_future_allowed(monkeypatch):
    monkeypatch.setattr("providers.flashscore.discovery.FLASHSCORE_MIN_DELAY_SECONDS", 0)
    page = _FakePage({"results": _EMPTY_HTML, "fixtures": _MATCH_HTML})
    matches = _discover_for_hub(page, "https://www.flashscore.com/football/x/y", "Premier League",
                                 limit=None, include_future_fixtures=True)
    assert len(matches) == 1
    assert matches[0].source == "fixtures"
    assert any(u.endswith("/fixtures/") for u in page.urls_visited)


def test_discover_for_hub_skips_fixtures_when_future_fixtures_disabled(monkeypatch):
    """[ADAUGAT Pasul 1 Master Repair Plan] Cauza radacina a celor 240 de
    fixture-uri viitoare (audit 2026-08-03): cu include_future_fixtures=
    False, /fixtures/ nu mai e incercat NICIODATA — liga cu /results/ gol
    (in pauza competitionala) e sarita curat, 0 meciuri, nu 100+."""
    monkeypatch.setattr("providers.flashscore.discovery.FLASHSCORE_MIN_DELAY_SECONDS", 0)
    page = _FakePage({"results": _EMPTY_HTML, "fixtures": _MATCH_HTML})
    matches = _discover_for_hub(page, "https://www.flashscore.com/football/x/y", "Premier League",
                                 limit=None, include_future_fixtures=False)
    assert matches == []
    assert not any(u.endswith("/fixtures/") for u in page.urls_visited)
    assert any(u.endswith("/results/") for u in page.urls_visited)


def test_discover_for_hub_still_returns_results_when_future_fixtures_disabled(monkeypatch):
    """Excluderea /fixtures/ nu atinge deloc /results/ — meciurile deja
    terminate raman complet neafectate."""
    monkeypatch.setattr("providers.flashscore.discovery.FLASHSCORE_MIN_DELAY_SECONDS", 0)
    page = _FakePage({"results": _MATCH_HTML, "fixtures": _EMPTY_HTML})
    matches = _discover_for_hub(page, "https://www.flashscore.com/football/x/y", "Champions League",
                                 limit=None, include_future_fixtures=False)
    assert len(matches) == 1
    assert matches[0].source == "results"


# ════════════════════════════════════════════════════════════════════════
# get_limit_per_league_automated() — plafon configurabil (nu hardcodat),
# Pasul 1 Master Repair Plan, rafinat dupa feedback.
# ════════════════════════════════════════════════════════════════════════

def test_get_limit_per_league_automated_uses_supabase_config_when_present(monkeypatch):
    monkeypatch.setattr("supabase_client.load_config", lambda default: {FLASHSCORE_LIMIT_PER_LEAGUE_CONFIG_KEY: 45})
    assert get_limit_per_league_automated() == 45


def test_get_limit_per_league_automated_falls_back_to_default_when_key_missing(monkeypatch):
    monkeypatch.setattr("supabase_client.load_config", lambda default: {})
    assert get_limit_per_league_automated() == DEFAULT_LIMIT_PER_LEAGUE_AUTOMATED


def test_get_limit_per_league_automated_falls_back_when_value_invalid(monkeypatch):
    """Valoare configurata gresit (negativa/zero/nenumerica) -> fallback la
    implicit, niciodata o eroare care blocheaza rularea automata."""
    monkeypatch.setattr("supabase_client.load_config",
                         lambda default: {FLASHSCORE_LIMIT_PER_LEAGUE_CONFIG_KEY: -5})
    assert get_limit_per_league_automated() == DEFAULT_LIMIT_PER_LEAGUE_AUTOMATED


def test_get_limit_per_league_automated_falls_back_on_exception(monkeypatch):
    def _boom(default):
        raise RuntimeError("simulated failure")
    monkeypatch.setattr("supabase_client.load_config", _boom)
    assert get_limit_per_league_automated() == DEFAULT_LIMIT_PER_LEAGUE_AUTOMATED


def test_discover_matches_default_preserves_manual_cli_behavior(monkeypatch):
    """include_future_fixtures implicit True — comportamentul CLI/manual
    existent ramane identic, neafectat de acest task."""
    import inspect
    sig = inspect.signature(discover_matches)
    assert sig.parameters["include_future_fixtures"].default is True
