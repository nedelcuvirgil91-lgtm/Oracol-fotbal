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

from udal_validation import ValidationResult

EVIDENCE_DIR = Path(__file__).parent.parent / "docs" / "06_UDAL" / "poc_evidence" / "flashscore_10matches"


def _valid_result(records):
    """[R3, 2026-08-23] Discovery apeleaza acum `validate_detailed()`, care
    intoarce `ValidationResult` intreg (are nevoie de `rejected` ca sa poata
    raporta CARE camp din cheia naturala lipsea). `validate()` ramane metoda
    de contract SyncAdapter, dar nu mai e pe calea de executie a Discovery."""
    return ValidationResult(valid=[{
        "home_team": "A", "away_team": "B", "kickoff_date": "2026-08-01T18:00:00",
        "_pages": records[0],
    }])


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
        "Conference League": ("europe", "conference-league"),
        "Jupiler Pro League": ("belgium", "jupiler-pro-league"),
        "Ekstraklasa": ("poland", "ekstraklasa"),
        "Scottish Premiership": ("scotland", "premiership"),
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
        FlashscoreAdapter, "validate_detailed", lambda self, records: _valid_result(records),
    )
    calls = []
    monkeypatch.setattr(
        "providers.flashscore.persistence.persist_match_with_data_trust_layer",
        lambda pages, match_ref, **kw: calls.append(kw) or {"ok": True},
    )

    match = DiscoveredMatch(league="Romania SuperLiga", match_base_url="https://x", mid="abc", source="results")
    reports = run_foundation_data_layer_for_discovered_matches([match])

    assert reports == [{"ok": True, "match": match}]
    # [ADR-066 P2b] `season` face acum parte din contractul de persistare.
    # Aici meciul e construit FARA sezon (hub fara eticheta), deci trebuie sa
    # ajunga `None` — niciodata o valoare inventata (Regula #8). Asertiunea
    # ramane pe dict-ul COMPLET, deliberat: orice kwarg nou trebuie sa treaca
    # printr-o decizie explicita, nu sa se strecoare tacit.
    assert calls == [{
        "league": "Romania SuperLiga", "competition": "Romania SuperLiga", "season": None,
    }]


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
        FlashscoreAdapter, "validate_detailed", lambda self, records: _valid_result(records),
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
# polite_delay() se cheltuie DOAR pe cereri reale (reparat 2026-08-30)
#
# DEFECTUL: `polite_delay()` (2-4s) rula neconditionat la inceputul fiecarei
# iteratii (`if i > 0`), INAINTE de verificarea Delta Sync — deci si pentru
# meciurile sarite, care nu contacteaza deloc Flashscore.
#
# COSTUL, masurat pe rulari live_sync reale (2026-08-29): in rularea reusita
# de la 14:10 (457 descoperite, 438 sarite) ~22 din 44 de minute au fost somn
# pur; rularea de la 19:36 a fost TAIATA de timeout-ul de 50 min dupa ce
# atinsese doar 327 din 487 de meciuri. A doua taiere in 3 zile.
# ════════════════════════════════════════════════════════════════════════

def _pregateste_fdl(monkeypatch, deja_colectate: set[str], fetch_arunca: set[str] = frozenset()):
    """Monteaza un Foundation Data Layer complet fals si intoarce
    `(delay_calls, fetch_calls)` — liste care se umplu in timpul rularii."""
    delay_calls: list[str] = []
    fetch_calls: list[str] = []

    monkeypatch.setattr(FlashscoreAdapter, "preflight", lambda self: None)
    monkeypatch.setattr("providers.flashscore.discovery.polite_delay",
                        lambda: delay_calls.append("delay"))
    monkeypatch.setattr("database.queries.is_flashscore_match_already_collected",
                        lambda mid: mid in deja_colectate)

    def _fetch(self, params):
        fetch_calls.append(params["mid"])
        if params["mid"] in fetch_arunca:
            raise RuntimeError("fetch esuat (simulat)")
        return {"summary": "<html></html>"}

    monkeypatch.setattr(FlashscoreAdapter, "fetch", _fetch)
    monkeypatch.setattr(FlashscoreAdapter, "normalize", lambda self, raw: [raw])
    monkeypatch.setattr(FlashscoreAdapter, "validate_detailed",
                        lambda self, records: _valid_result(records))
    monkeypatch.setattr("providers.flashscore.persistence.persist_match_with_data_trust_layer",
                        lambda pages, match_ref, **kw: {"ok": True})
    return delay_calls, fetch_calls


def _meci(mid: str) -> DiscoveredMatch:
    return DiscoveredMatch(league="Romania SuperLiga", match_base_url=f"https://x/{mid}",
                           mid=mid, source="results")


def test_toate_sarite_zero_delay(monkeypatch):
    """GARDA CENTRALA a fixului. 100 de meciuri deja colectate = 0 apeluri
    `polite_delay()`. Inainte ar fi fost 99 — ~5 minute de somn pur pentru
    zero cereri catre Flashscore."""
    mids = [f"m{i}" for i in range(100)]
    delay_calls, fetch_calls = _pregateste_fdl(monkeypatch, deja_colectate=set(mids))

    rapoarte = run_foundation_data_layer_for_discovered_matches([_meci(m) for m in mids])

    assert len(delay_calls) == 0, (
        f"{len(delay_calls)} apeluri polite_delay() pentru meciuri SARITE — "
        "acestea nu contacteaza deloc Flashscore, deci nu au ce distanta"
    )
    assert fetch_calls == []
    assert all(r["skipped"] for r in rapoarte)


def test_delay_doar_INTRE_cereri_reale(monkeypatch):
    """3 cereri reale -> 2 delay-uri (nu 3): niciodata inaintea primeia."""
    delay_calls, fetch_calls = _pregateste_fdl(monkeypatch, deja_colectate=set())

    run_foundation_data_layer_for_discovered_matches([_meci(m) for m in ("a", "b", "c")])

    assert fetch_calls == ["a", "b", "c"]
    assert len(delay_calls) == 2


def test_sariturile_dintre_cereri_nu_umfla_numarul_de_delay_uri(monkeypatch):
    """Cazul REAL de productie: putine fetch-uri, multe sarituri intercalate.
    2 cereri reale printre 8 sarituri -> exact 1 delay."""
    mids = ["s1", "s2", "REAL1", "s3", "s4", "s5", "REAL2", "s6", "s7", "s8"]
    sarite = {m for m in mids if m.startswith("s")}
    delay_calls, fetch_calls = _pregateste_fdl(monkeypatch, deja_colectate=sarite)

    run_foundation_data_layer_for_discovered_matches([_meci(m) for m in mids])

    assert fetch_calls == ["REAL1", "REAL2"]
    assert len(delay_calls) == 1, (
        "delay-ul trebuie sa distanteze DOAR cele doua cereri reale, "
        "indiferent cate sarituri sunt intre ele"
    )


def test_un_fetch_care_arunca_ramane_o_cerere_reala(monkeypatch):
    """Contrapondere impotriva unei 'optimizari' gresite: daca `fetch()`
    arunca, cererea a plecat oricum spre Flashscore — deci urmatoarea TREBUIE
    distantata de ea. A nu numara esecul ar face ca doua cereri consecutive
    sa plece fara pauza exact cand providerul da semne de problema."""
    delay_calls, fetch_calls = _pregateste_fdl(
        monkeypatch, deja_colectate=set(), fetch_arunca={"a"},
    )

    rapoarte = run_foundation_data_layer_for_discovered_matches([_meci("a"), _meci("b")])

    assert fetch_calls == ["a", "b"]
    assert len(delay_calls) == 1, "esecul lui 'a' tot a contactat Flashscore"
    assert rapoarte[0]["ok"] is False


def test_ordinea_in_cod_delta_sync_INAINTEA_delay_ului():
    """GARDA STRUCTURALA, citita din sursa. Testele de mai sus verifica efectul;
    asta verifica *ordinea*, ca o rescriere viitoare sa nu reintroduca defectul
    intr-o forma care intamplator trece testele de numarare."""
    import inspect
    from providers.flashscore import discovery as d

    sursa = inspect.getsource(d.run_foundation_data_layer_for_discovered_matches)
    doar_cod = "\n".join(l for l in sursa.splitlines() if not l.strip().startswith("#"))

    poz_delta = doar_cod.find("is_flashscore_match_already_collected(match.mid)")
    poz_delay = doar_cod.find("polite_delay()")
    assert poz_delta != -1 and poz_delay != -1
    assert poz_delta < poz_delay, (
        "polite_delay() a ajuns din nou INAINTEA verificarii Delta Sync — "
        "asta reintroduce ~22 min de somn pur per rulare (masurat 2026-08-29)"
    )


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
    monkeypatch.setattr("providers.flashscore.discovery.polite_delay", lambda: None)
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
    monkeypatch.setattr("providers.flashscore.discovery.polite_delay", lambda: None)
    page = _FakePage({"results": _EMPTY_HTML, "fixtures": _MATCH_HTML})
    matches = _discover_for_hub(page, "https://www.flashscore.com/football/x/y", "Premier League",
                                 limit=None, include_future_fixtures=False)
    assert matches == []
    assert not any(u.endswith("/fixtures/") for u in page.urls_visited)
    assert any(u.endswith("/results/") for u in page.urls_visited)


def test_discover_for_hub_still_returns_results_when_future_fixtures_disabled(monkeypatch):
    """Excluderea /fixtures/ nu atinge deloc /results/ — meciurile deja
    terminate raman complet neafectate."""
    monkeypatch.setattr("providers.flashscore.discovery.polite_delay", lambda: None)
    page = _FakePage({"results": _MATCH_HTML, "fixtures": _EMPTY_HTML})
    matches = _discover_for_hub(page, "https://www.flashscore.com/football/x/y", "Champions League",
                                 limit=None, include_future_fixtures=False)
    assert len(matches) == 1
    assert matches[0].source == "results"


def test_discover_for_hub_future_fixtures_only_ignores_nonempty_results(monkeypatch):
    """[FIX 2026-08-05, gasit in timpul implementarii flashscore_weekly_
    fixtures.yml] future_fixtures_only=True cere /fixtures/ NECONDITIONAT
    - /results/ nu trebuie nici macar incercat, chiar daca are continut
    (comportamentul normal, include_future_fixtures=True, l-ar fi luat pe
    acela si s-ar fi oprit acolo, fara sa mai ajunga la /fixtures/)."""
    monkeypatch.setattr("providers.flashscore.discovery.polite_delay", lambda: None)
    page = _FakePage({"results": _MATCH_HTML, "fixtures": _MATCH_HTML})
    matches = _discover_for_hub(page, "https://www.flashscore.com/football/x/y", "Premier League",
                                 limit=None, include_future_fixtures=True, future_fixtures_only=True)
    assert len(matches) == 1
    assert matches[0].source == "fixtures"
    assert not any(u.endswith("/results/") for u in page.urls_visited)
    assert any(u.endswith("/fixtures/") for u in page.urls_visited)


def test_discover_for_hub_future_fixtures_only_empty_when_no_fixtures(monkeypatch):
    monkeypatch.setattr("providers.flashscore.discovery.polite_delay", lambda: None)
    page = _FakePage({"results": _MATCH_HTML, "fixtures": _EMPTY_HTML})
    matches = _discover_for_hub(page, "https://www.flashscore.com/football/x/y", "Premier League",
                                 limit=None, include_future_fixtures=True, future_fixtures_only=True)
    assert matches == []
    assert not any(u.endswith("/results/") for u in page.urls_visited)


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
