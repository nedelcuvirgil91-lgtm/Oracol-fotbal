"""Calendarul sezonului ca fapt STOCAT, nu dedus (ADR-067).

DE CE EXISTA. ADR-066 P3 derivase startul sezonului din `match_history`
(sezonul celui mai recent meci -> prima lui zi). Verificata pe date REALE in
aceeasi zi, derivarea intorcea pentru Premier League `2025-08-15` — startul
sezonului TRECUT: football_data nu mai scrie din 2026-08-04, iar meciurile noi
n-au inca eticheta. Idem La Liga, Serie A, Bundesliga, Ligue 1.

Alegerea reala nu era „tabela noua vs nimic", ci „fapt declarat de provider vs
inferenta fragila din acoperirea propriei baze de date".

CASCADA IN TREI TREPTE, fiecare cu semantica proprie:
  1. calendarul din `competition_season` — DIRECT, fara garda
  2. derivarea din `match_history`      — cu garda `max()`
  3. pragul de 1 iulie                  — plasa de siguranta

Diferenta dintre 1 si 2 e miezul acestui fisier si e testata explicit.

Fara retea, fara Supabase.
"""
from __future__ import annotations

from datetime import date

import oracle_engine
from oracle_engine import FootballOracleEngine as Motor
from providers.flashscore.discovery import DiscoveredMatch, season_calendar_rows


# ── season_calendar_rows — functie pura ─────────────────────────────────────

def _m(liga, sezon=None, start=None, final=None, mid="m"):
    return DiscoveredMatch(league=liga, match_base_url="u", mid=mid, source="results",
                           season=sezon, season_start=start, season_end=final)


def test_un_calendar_per_liga_si_sezon():
    randuri = season_calendar_rows([
        _m("Ligue 1", "2026-2027", "2026-08-21", "2027-06-06", mid="a"),
        _m("Ligue 1", "2026-2027", "2026-08-21", "2027-06-06", mid="b"),
        _m("Serie A", "2026-2027", "2026-08-22", "2027-05-30", mid="c"),
    ])
    assert len(randuri) == 2
    assert {r["competition"] for r in randuri} == {"Ligue 1", "Serie A"}


def test_meciurile_fara_sezon_nu_produc_calendar():
    assert season_calendar_rows([_m("Ligue 1"), _m("Serie A", None)]) == []


def test_o_vedere_CU_interval_o_bate_pe_una_fara():
    """GARDA. Hub-ul `/fixtures/` poarta eticheta dar NU si bara de progres
    (verificat live). Daca acea vedere ajunge prima, nu are voie sa fixeze un
    calendar gol cand exista si una completa in acelasi lot."""
    randuri = season_calendar_rows([
        _m("Ligue 1", "2026-2027", None, None, mid="a"),
        _m("Ligue 1", "2026-2027", "2026-08-21", "2027-06-06", mid="b"),
    ])
    assert randuri == [{"competition": "Ligue 1", "season": "2026-2027",
                        "start_date": "2026-08-21", "end_date": "2027-06-06"}]


def test_eticheta_fara_interval_se_pastreaza_totusi():
    """Necunoscutul ramane necunoscut (interval None), dar ce se stie nu se
    arunca — eticheta tot merita scrisa."""
    randuri = season_calendar_rows([_m("MLS", "2026-2026", None, None)])
    assert randuri == [{"competition": "MLS", "season": "2026-2026",
                        "start_date": None, "end_date": None}]


def test_lista_goala():
    assert season_calendar_rows([]) == []


# ── cascada: treapta 1 vs treapta 2 ─────────────────────────────────────────

def _fara_db(monkeypatch):
    monkeypatch.setattr(oracle_engine, "DB_QUERIES_MODULE_AVAILABLE", True, raising=False)
    monkeypatch.setattr(oracle_engine, "get_season_calendar",
                        lambda liga, zi: None, raising=False)
    monkeypatch.setattr(oracle_engine, "get_current_season_start",
                        lambda liga: None, raising=False)


def test_calendarul_are_prioritate_asupra_derivarii(monkeypatch):
    _fara_db(monkeypatch)
    monkeypatch.setattr(oracle_engine, "get_season_calendar",
                        lambda liga, zi: {"start_date": "2026-08-21"}, raising=False)
    monkeypatch.setattr(oracle_engine, "get_current_season_start",
                        lambda liga: "2025-08-15", raising=False)
    assert Motor._current_season_start_date(date(2026, 8, 25), league="Ligue 1") == "2026-08-21"


def test_calendarul_POATE_largi_fereastra_derivarea_NU(monkeypatch):
    """MIEZUL ADR-067. MLS, noiembrie 2026: sezonul real e februarie–decembrie
    2026, deci calendarul spune 2026-02-21, iar pragul ar spune 2026-07-01.

    Raspunsul CORECT e al calendarului — un interval care CONTINE ziua de azi
    defineste sezonul curent prin constructie, deci nu poate amesteca doua
    sezoane nici cand largeste fereastra. Garda `max()` de la treapta 2 l-ar
    respinge si ar taia jumatate din sezonul in curs."""
    _fara_db(monkeypatch)
    monkeypatch.setattr(oracle_engine, "get_season_calendar",
                        lambda liga, zi: {"start_date": "2026-02-21"}, raising=False)
    out = Motor._current_season_start_date(date(2026, 11, 15), league="MLS")
    assert out == "2026-02-21", f"calendarul autoritar a fost respins de garda: {out}"


def test_derivarea_ramane_cu_garda(monkeypatch):
    """Aceeasi data mai devreme decat pragul, dar venita din DERIVARE, trebuie
    respinsa — acolo nu avem garantia ca eticheta descrie sezonul curent."""
    _fara_db(monkeypatch)
    monkeypatch.setattr(oracle_engine, "get_current_season_start",
                        lambda liga: "2026-02-21", raising=False)
    assert Motor._current_season_start_date(date(2026, 11, 15), league="MLS") == "2026-07-01"


def test_calendar_fara_start_cade_pe_treapta_urmatoare(monkeypatch):
    _fara_db(monkeypatch)
    monkeypatch.setattr(oracle_engine, "get_season_calendar",
                        lambda liga, zi: {"start_date": None}, raising=False)
    monkeypatch.setattr(oracle_engine, "get_current_season_start",
                        lambda liga: "2027-02-20", raising=False)
    assert Motor._current_season_start_date(date(2027, 3, 1), league="MLS") == "2027-02-20"


def test_toate_trei_treptele_goale_dau_pragul(monkeypatch):
    _fara_db(monkeypatch)
    assert Motor._current_season_start_date(date(2026, 8, 25), league="X") == "2026-07-01"


def test_eroare_la_calendar_nu_rupe_servirea(monkeypatch, caplog):
    _fara_db(monkeypatch)

    def _explodeaza(liga, zi):
        raise RuntimeError("conexiune pierduta")

    monkeypatch.setattr(oracle_engine, "get_season_calendar", _explodeaza, raising=False)
    with caplog.at_level("WARNING"):
        out = Motor._current_season_start_date(date(2026, 8, 25), league="MLS")
    assert out == "2026-07-01"
    assert "calendar de sezon indisponibil" in caplog.text


def test_discover_matches_chiar_scrie_calendarul():
    """GARDA DE CABLARE, adaugata dupa ce o mutatie a aratat ca lipsea:
    stergerea apelului din `discover_matches()` nu era prinsa de niciun test.

    Exact clasa de defect de la ADR-066 — extragerea corecta, scrierea corecta,
    dar firul dintre ele netaiat, iar coloana ramane goala la nesfarsit.
    `discover_matches()` ruleaza sub Playwright si nu poate fi apelata fara
    retea, deci verificarea e la nivel de AST."""
    import ast
    import inspect

    from providers.flashscore import discovery

    arbore = ast.parse(inspect.getsource(discovery.discover_matches))
    apeluri = {
        getattr(n.func, "id", None)
        for n in ast.walk(arbore) if isinstance(n, ast.Call)
    }
    assert "persist_season_calendars" in apeluri, (
        "discover_matches() trebuie sa scrie calendarul sezonului — altfel "
        "`competition_season` ramane goala si cascada cade mereu pe treapta 2"
    )


def test_ziua_interogata_e_cea_ceruta_nu_azi(monkeypatch):
    """GARDA: `as_of` trebuie sa ajunga la interogare, altfel orice evaluare
    retroactiva ar primi calendarul de AZI — scurgere temporala."""
    primite: dict = {}
    _fara_db(monkeypatch)
    monkeypatch.setattr(oracle_engine, "get_season_calendar",
                        lambda liga, zi: primite.setdefault("zi", zi) and None, raising=False)
    Motor._current_season_start_date(date(2027, 3, 1), league="MLS")
    assert primite["zi"] == "2027-03-01"
