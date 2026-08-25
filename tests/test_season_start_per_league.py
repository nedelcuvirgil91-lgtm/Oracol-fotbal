"""Startul real al sezonului, per ligă (ADR-066 P3).

CE INLOCUIESTE. `_current_season_start_date()` folosea un prag calendaristic
fix — 1 iulie. Corect pentru ligile europene, gresit pentru cele care joaca
intr-un singur an calendaristic. MLS joaca februarie–decembrie: din februarie
2027, pragul „1 iulie 2026" ar amesteca sezonul 2026 cu 2027 in acelasi profil
de echipa — exact ce marginirea trebuia sa previna („loturile se schimba intre
sezoane", cerinta proprietarului produsului, 2026-08-15).

DE CE NU E O SCHIMBARE RISCANTA AZI. Verificat 2026-08-25: zero meciuri
Flashscore inainte de 1 iulie 2026, in oricare din cele 17 ligi cu date; si
zero randuri cu `season` populat. Deci AZI comportamentul e identic cu cel
vechi, pentru toate ligile. Fixul se activeaza singur, pe masura ce cablarea
P2b scrie sezoane.

Fara retea, fara Supabase.
"""
from __future__ import annotations

from datetime import date

import oracle_engine
from oracle_engine import FootballOracleEngine as Motor


# ── plasa de siguranta: pragul vechi, neschimbat ─────────────────────────────

def test_pragul_de_iulie_ramane_identic():
    assert Motor._season_start_fallback(date(2026, 8, 15)) == "2026-07-01"
    assert Motor._season_start_fallback(date(2027, 3, 1)) == "2026-07-01"
    assert Motor._season_start_fallback(date(2026, 7, 1)) == "2026-07-01"


def test_fara_liga_comportamentul_e_cel_dinainte():
    """Compatibilitate: `check_team_profile_readiness.py`, `app.py` si sonda de
    ablatie apeleaza fara liga — nu au voie sa-si schimbe raspunsul."""
    assert Motor._current_season_start_date(date(2026, 8, 15)) == "2026-07-01"
    assert Motor._current_season_start_date(date(2027, 3, 1)) == "2026-07-01"


# ── startul real, cand e cunoscut ────────────────────────────────────────────

def test_startul_real_are_prioritate_asupra_pragului(monkeypatch):
    """CAZUL CARE CONTEAZA. MLS, februarie 2027: pragul ar da 2026-07-01 si ar
    amesteca doua sezoane. Cu startul real, marginirea cade unde trebuie."""
    monkeypatch.setattr(oracle_engine, "DB_QUERIES_MODULE_AVAILABLE", True, raising=False)
    monkeypatch.setattr(oracle_engine, "get_current_season_start",
                        lambda liga: "2027-02-20", raising=False)
    assert Motor._current_season_start_date(date(2027, 3, 1), league="MLS") == "2027-02-20"


def test_eticheta_de_sezon_INCHEIAT_nu_largeste_fereastra(monkeypatch):
    """GARDA CENTRALA, gasita pe date REALE (2026-08-25), nu prin mock-uri.

    Pentru Premier League, `get_current_season_start` intorcea `2025-08-15` —
    startul sezonului TRECUT: cel mai recent meci PL cu eticheta e din
    2026-05-24 (football_data s-a oprit pe 2026-08-04), iar meciurile noi n-au
    inca sezon scris. Folosind-o direct, fereastra Team DNA s-ar fi LARGIT
    peste tot sezonul 2025-26 — exact amestecul pe care marginirea il previne.

    Regula: se ia data cea mai tarzie. `max()` nu poate largi niciodata
    fereastra peste prag, deci nu poate introduce un amestec de sezoane."""
    monkeypatch.setattr(oracle_engine, "DB_QUERIES_MODULE_AVAILABLE", True, raising=False)
    monkeypatch.setattr(oracle_engine, "get_current_season_start",
                        lambda liga: "2025-08-15", raising=False)
    out = Motor._current_season_start_date(date(2026, 8, 25), league="Premier League")
    assert out == "2026-07-01", f"eticheta unui sezon incheiat a largit fereastra: {out}"


def test_start_derivat_egal_cu_pragul_nu_schimba_nimic(monkeypatch):
    monkeypatch.setattr(oracle_engine, "DB_QUERIES_MODULE_AVAILABLE", True, raising=False)
    monkeypatch.setattr(oracle_engine, "get_current_season_start",
                        lambda liga: "2026-07-01", raising=False)
    assert Motor._current_season_start_date(date(2026, 8, 25), league="X") == "2026-07-01"


def test_liga_fara_sezon_cunoscut_cade_pe_prag(monkeypatch):
    """Situatia REALA de azi: nicio linie Flashscore nu are inca sezon."""
    monkeypatch.setattr(oracle_engine, "DB_QUERIES_MODULE_AVAILABLE", True, raising=False)
    monkeypatch.setattr(oracle_engine, "get_current_season_start",
                        lambda liga: None, raising=False)
    assert Motor._current_season_start_date(date(2026, 8, 15), league="MLS") == "2026-07-01"


def test_eroare_la_interogare_nu_rupe_servirea(monkeypatch, caplog):
    """Degradare, nu prabusire: servirea live nu are voie sa cada pentru ca o
    interogare auxiliara a esuat. Esecul se LOGHEAZA, nu se inghite tacut."""
    def _explodeaza(liga):
        raise RuntimeError("conexiune pierduta")

    monkeypatch.setattr(oracle_engine, "DB_QUERIES_MODULE_AVAILABLE", True, raising=False)
    monkeypatch.setattr(oracle_engine, "get_current_season_start", _explodeaza, raising=False)
    with caplog.at_level("WARNING"):
        out = Motor._current_season_start_date(date(2026, 8, 15), league="MLS")
    assert out == "2026-07-01"
    assert "start de sezon indisponibil" in caplog.text


def test_fara_modulul_de_interogari_cade_pe_prag(monkeypatch):
    monkeypatch.setattr(oracle_engine, "DB_QUERIES_MODULE_AVAILABLE", False, raising=False)
    assert Motor._current_season_start_date(date(2026, 8, 15), league="MLS") == "2026-07-01"


# ── liga chiar ajunge la interogare ──────────────────────────────────────────

def test_team_dna_transmite_liga(monkeypatch):
    """Capatul firului: fara transmiterea ligii, tot restul e cod mort."""
    primite: dict = {}

    monkeypatch.setattr(oracle_engine, "DB_QUERIES_MODULE_AVAILABLE", True, raising=False)
    monkeypatch.setattr(oracle_engine, "FLASHSCORE_TEAM_DNA_AVAILABLE", True, raising=False)
    monkeypatch.setattr(oracle_engine, "get_current_season_start",
                        lambda liga: primite.setdefault("liga", liga) and None, raising=False)
    for nume in ("get_team_recent_advanced_stats", "get_team_recent_statistics_extended",
                 "get_team_recent_player_ratings"):
        monkeypatch.setattr(oracle_engine, nume,
                            lambda *a, **k: [], raising=False)
    monkeypatch.setattr(oracle_engine, "get_team_standings_row",
                        lambda t, l: None, raising=False)
    monkeypatch.setattr(oracle_engine, "build_team_dna",
                        lambda *a, **k: {"ok": True}, raising=False)

    Motor._build_flashscore_dna("FCSB", "Romania SuperLiga")
    assert primite.get("liga") == "Romania SuperLiga"


def test_startul_real_ajunge_la_cele_trei_interogari(monkeypatch):
    apeluri: dict[str, str | None] = {}

    monkeypatch.setattr(oracle_engine, "DB_QUERIES_MODULE_AVAILABLE", True, raising=False)
    monkeypatch.setattr(oracle_engine, "FLASHSCORE_TEAM_DNA_AVAILABLE", True, raising=False)
    monkeypatch.setattr(oracle_engine, "get_current_season_start",
                        lambda liga: "2027-02-20", raising=False)

    def _fals(cheie):
        def _f(team, league, last_n=5, since_date=None):
            apeluri[cheie] = since_date
            return []
        return _f

    monkeypatch.setattr(oracle_engine, "get_team_recent_advanced_stats", _fals("advanced"), raising=False)
    monkeypatch.setattr(oracle_engine, "get_team_recent_statistics_extended", _fals("extended"), raising=False)
    monkeypatch.setattr(oracle_engine, "get_team_recent_player_ratings", _fals("ratings"), raising=False)
    monkeypatch.setattr(oracle_engine, "get_team_standings_row", lambda t, l: None, raising=False)
    monkeypatch.setattr(oracle_engine, "build_team_dna", lambda *a, **k: {}, raising=False)

    Motor._build_flashscore_dna("Inter Miami", "MLS")
    assert apeluri == {"advanced": "2027-02-20", "extended": "2027-02-20", "ratings": "2027-02-20"}
