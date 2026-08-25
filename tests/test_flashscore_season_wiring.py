"""Cablarea sezonului: hub -> DiscoveredMatch -> scrierea canonica (ADR-066 P2b).

CONTEXT: `parse_season_from_hub()` (P1) extrage sezonul corect, iar migrarea 052
(P2) a facut coloana scriibila pe calea canonica. Intre ele lipsea firul: nimeni
nu dadea vreodata o valoare parametrului `season`, desi plumbing-ul exista de la
migratia 038. De aceea toate cele 1.058 de randuri Flashscore aveau season NULL,
impreuna cu celelalte trei tabele FDL care primesc acelasi parametru.

Testele acopera cele trei imbinari, separat:
  1. `season_for_kickoff()` — functie pura, garda de interval
  2. `_discover_for_hub()` — sezonul ajunge pe fiecare DiscoveredMatch
  3. `run_foundation_data_layer_for_discovered_matches()` — ajunge la persistare

Fara retea, fara Supabase, fara Playwright real.
"""
from __future__ import annotations

from providers.flashscore import discovery
from providers.flashscore.discovery import DiscoveredMatch, season_for_kickoff


# ── 1. season_for_kickoff — functie pura ─────────────────────────────────────

def test_meci_in_interval_primeste_sezonul():
    assert season_for_kickoff("2026-2027", "2026-07-17", "2027-05-30", "2026-08-25") == "2026-2027"


def test_marginile_intervalului_sunt_incluse():
    assert season_for_kickoff("2026-2027", "2026-07-17", "2027-05-30", "2026-07-17") == "2026-2027"
    assert season_for_kickoff("2026-2027", "2026-07-17", "2027-05-30", "2027-05-30") == "2026-2027"


def test_meci_in_afara_intervalului_nu_primeste_sezon(caplog):
    """GARDA CENTRALA. O eticheta aplicata gresit e mai rea decat una lipsa:
    nu produce niciun semnal, dar contamineaza walk-forward-ul si
    `season_cleanup.py` (care sterge pe baza sezonului)."""
    with caplog.at_level("WARNING"):
        out = season_for_kickoff("2026-2027", "2026-07-17", "2027-05-30", "2026-06-30")
    assert out is None
    assert "in afara intervalului" in caplog.text


def test_fara_interval_eticheta_ramane_singurul_semnal():
    """Cazul hub-ului `/fixtures/`: verificat live 2026-08-25 ca poarta eticheta
    („Superliga 2026/2027") dar nu si bara de progres. Nu se inventeaza un
    interval doar ca sa avem ce verifica."""
    assert season_for_kickoff("2026-2027", None, None, "2026-08-25") == "2026-2027"


def test_fara_eticheta_intoarce_none():
    """Regula #8 — necunoscutul nu se deduce din calendar."""
    assert season_for_kickoff(None, "2026-07-17", "2027-05-30", "2026-08-25") is None
    assert season_for_kickoff("", None, None, "2026-08-25") is None


def test_fara_data_meciului_eticheta_se_pastreaza():
    assert season_for_kickoff("2026-2027", "2026-07-17", "2027-05-30", None) == "2026-2027"


def test_kickoff_cu_ora_se_compara_doar_pe_zi():
    assert season_for_kickoff(
        "2026-2027", "2026-07-17", "2027-05-30", "2026-08-25T18:00:00Z") == "2026-2027"


# ── 2. _discover_for_hub — sezonul ajunge pe fiecare meci ────────────────────

_HUB = (
    '<div class="heading__info">2026/2027</div>'
    '<div class="wcl-progressBarContainer_qiOjQ">'
    '<span class="wcl-start_TGQDT">17.07.</span>'
    '<span class="wcl-end_OQo3-">30.05.</span></div>'
    '<a href="/match/football/rapid-x-YFCpigVG/?mid=EeqI7WJc"></a>'
)


class _PaginaFalsa:
    """Minimul din API-ul Playwright folosit de `_discover_for_hub`."""

    def __init__(self, html: str):
        self._html = html
        self.content_calls = 0

    def goto(self, *a, **k):
        return type("R", (), {"status": 200})()

    def wait_for_timeout(self, *a, **k):
        pass

    def content(self):
        self.content_calls += 1
        return self._html

    def locator(self, *a, **k):
        raise RuntimeError("fara GDPR in fixture")


def _fara_efecte(monkeypatch):
    monkeypatch.setattr(discovery, "_dismiss_gdpr_if_present", lambda page: None)
    monkeypatch.setattr(discovery, "_check_protection", lambda *a, **k: None)
    monkeypatch.setattr(discovery, "polite_delay", lambda *a, **k: None)


def test_sezonul_ajunge_pe_fiecare_meci_descoperit(monkeypatch):
    _fara_efecte(monkeypatch)
    page = _PaginaFalsa(_HUB)
    out = discovery._discover_for_hub(page, "https://x/y", "Romania SuperLiga", None)
    assert out and all(m.season == "2026-2027" for m in out)
    assert out[0].season_start == "2026-07-17"
    assert out[0].season_end == "2027-05-30"


def test_un_singur_content_pentru_linkuri_si_sezon(monkeypatch):
    """GARDA: sezonul si linkurile trebuie sa vina din ACELASI HTML. Cu doua
    apeluri `page.content()` separate, hub-ul s-ar putea schimba intre ele si
    sezonul ar descrie alta pagina decat meciurile."""
    _fara_efecte(monkeypatch)
    page = _PaginaFalsa(_HUB)
    discovery._discover_for_hub(page, "https://x/y", "Romania SuperLiga", None)
    assert page.content_calls == 1, f"{page.content_calls} apeluri content() pe acelasi hub"


def test_hub_fara_sezon_nu_blocheaza_descoperirea(monkeypatch, caplog):
    """Degradare corecta: meciurile se descopera oricum, doar fara sezon."""
    _fara_efecte(monkeypatch)
    fara = '<a href="/match/football/rapid-x-YFCpigVG/?mid=EeqI7WJc"></a>'
    page = _PaginaFalsa(fara)
    with caplog.at_level("WARNING"):
        out = discovery._discover_for_hub(page, "https://x/y", "Romania SuperLiga", None)
    assert out and out[0].season is None
    assert "sezon negasit" in caplog.text


def test_campurile_de_sezon_sunt_optionale():
    """Niciun apelant existent nu se rupe: implicit None peste tot."""
    m = DiscoveredMatch(league="L", match_base_url="u", mid="m", source="results")
    assert (m.season, m.season_start, m.season_end) == (None, None, None)


# ── 3. ajunge efectiv la persistare ─────────────────────────────────────────

def _cale_de_persistare(monkeypatch, kickoff: str) -> dict:
    """Izoleaza `run_foundation_data_layer_for_discovered_matches()` de retea,
    Playwright si Supabase, si intoarce ce a primit persistarea."""
    primite: dict = {}

    def _persist_fals(pages, match_ref, competition=None, season=None, league=None):
        primite["season"] = season
        return {"match_id": 1, "ok": True, "steps": {}}

    class _Validare:
        valid = [{"home_team": "A", "away_team": "B", "kickoff_date": kickoff, "_pages": {}}]
        rejected: list = []

    class _AdaptorFals:
        def preflight(self):
            pass

        def fetch(self, params):
            return {"summary": "<html></html>"}

        def normalize(self, pages):
            return [{}]

        def validate_detailed(self, records):
            return _Validare()

    import database.queries as queries
    import providers.flashscore.adapter as adapter_mod
    import providers.flashscore.persistence as persistence

    monkeypatch.setattr(persistence, "persist_match_with_data_trust_layer", _persist_fals)
    monkeypatch.setattr(adapter_mod, "FlashscoreAdapter", _AdaptorFals)
    monkeypatch.setattr(queries, "is_flashscore_match_already_collected", lambda mid: False)
    monkeypatch.setattr(discovery, "polite_delay", lambda *a, **k: None)

    discovery.run_foundation_data_layer_for_discovered_matches([
        DiscoveredMatch(league="Romania SuperLiga", match_base_url="u", mid="m",
                        source="results", season="2026-2027",
                        season_start="2026-07-17", season_end="2027-05-30"),
    ])
    return primite


def test_sezonul_ajunge_la_scrierea_canonica(monkeypatch):
    """Capatul firului. Fara acest test, P1+P2 pot fi ambele corecte si coloana
    tot ramane NULL — exact situatia dinainte de ADR-066."""
    assert _cale_de_persistare(monkeypatch, "2026-08-25")["season"] == "2026-2027"


def test_meci_in_afara_sezonului_nu_scrie_sezon(monkeypatch):
    """Aceeasi cale, cu garda activa: meci din iunie sub eticheta 2026/2027."""
    assert _cale_de_persistare(monkeypatch, "2026-06-30")["season"] is None
