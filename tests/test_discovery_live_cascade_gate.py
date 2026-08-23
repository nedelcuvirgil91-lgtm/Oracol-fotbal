"""Teste pentru gate-ul cascadei live de descoperire (ADR-063).

Invariantul CENTRAL, si motivul pentru care implicitul e `True`, nu `False`:
oprirea descoperirii trebuie sa fie intotdeauna o DECIZIE EXPLICITA scrisa in
config — niciodata efectul secundar al unei erori. Un fallback la `False` ar
insemna ca o indisponibilitate Supabase degradeaza tacit sistemul spre MAI
PUTINE meciuri descoperite, exact opusul a ce trebuie sa faca o plasa de
siguranta.

Fara retea, fara Supabase real — `load_config` e monkeypatch-uit.
"""
from __future__ import annotations

import inspect

import oracle_api
from oracle_api import FootballOracleAPI


# ── Implicitul: activ (comportamentul de dinainte de ADR-063) ─────────────

def test_implicit_activ_cand_cheia_lipseste(monkeypatch):
    monkeypatch.setattr("supabase_client.load_config", lambda default=None: {})
    assert FootballOracleAPI._live_cascade_enabled() is True


def test_implicit_activ_cand_supabase_arunca(monkeypatch):
    """Degradarea NU are voie sa opreasca descoperirea — vezi antetul."""
    def _boom(default=None):
        raise RuntimeError("Supabase indisponibil")

    monkeypatch.setattr("supabase_client.load_config", _boom)
    assert FootballOracleAPI._live_cascade_enabled() is True


def test_implicit_activ_cand_valoarea_nu_e_booleana(monkeypatch):
    """O valoare corupta in config (string, numar) nu opreste descoperirea —
    doar un `false` boolean explicit o face."""
    for bad in ("false", 0, None, "no", []):
        monkeypatch.setattr(
            "supabase_client.load_config", lambda default=None, b=bad: {"discovery_live_cascade_enabled": b},
        )
        assert FootballOracleAPI._live_cascade_enabled() is True, f"valoarea {bad!r} nu trebuie sa dezactiveze"


# ── Oprirea: doar `false` boolean explicit ────────────────────────────────

def test_dezactivat_doar_la_false_boolean_explicit(monkeypatch):
    monkeypatch.setattr(
        "supabase_client.load_config", lambda default=None: {"discovery_live_cascade_enabled": False},
    )
    assert FootballOracleAPI._live_cascade_enabled() is False


def test_activ_la_true_explicit(monkeypatch):
    monkeypatch.setattr(
        "supabase_client.load_config", lambda default=None: {"discovery_live_cascade_enabled": True},
    )
    assert FootballOracleAPI._live_cascade_enabled() is True


# ── Cascada chiar e ocolita cand flag-ul e oprit ──────────────────────────

def test_cascada_intoarce_lista_goala_si_nu_apeleaza_niciun_provider(monkeypatch):
    """Gate-ul trebuie sa iasa INAINTE de orice apel de provider — nu doar sa
    arunce rezultatul. Verificat cu numaratoare reala de apeluri (nu cu un
    mock care arunca, fiindca o exceptie ar putea fi inghitita de o garda
    interna si testul ar trece din motivul gresit)."""
    calls: list[str] = []

    monkeypatch.setattr(
        "supabase_client.load_config", lambda default=None: {"discovery_live_cascade_enabled": False},
    )
    for name in ("_fetch_events_odds_api", "_fetch_freelf_matches",
                 "_fetch_matches_fd", "_fetch_matches_espn", "_fetch_matches_tsdb"):
        if hasattr(FootballOracleAPI, name):
            monkeypatch.setattr(
                FootballOracleAPI, name,
                lambda self, *a, _n=name, **kw: (calls.append(_n), [])[1],
            )

    api = FootballOracleAPI.__new__(FootballOracleAPI)  # fara __init__ (zero I/O)
    out = FootballOracleAPI._fetch_live_week_matches(api, days_ahead=7, competitions=["Premier League"])

    assert out == []
    assert calls == [], f"niciun provider nu trebuie apelat cand cascada e oprita, dar s-au apelat: {calls}"


# ── Garda structurala: gate-ul e prima instructiune executabila ──────────

def test_gate_ul_e_verificat_inaintea_oricarui_provider():
    """Structural: `_live_cascade_enabled()` apare in sursa metodei INAINTEA
    primului apel de provider — altfel un provider ar putea fi contactat
    (cost real de cota API) chiar cu cascada oprita."""
    src = inspect.getsource(FootballOracleAPI._fetch_live_week_matches)
    idx_gate = src.find("_live_cascade_enabled()")
    assert idx_gate != -1, "gate-ul lipseste din _fetch_live_week_matches"

    for provider_call in ("_fetch_events_odds_api(", "_fetch_freelf_matches(",
                          "_fetch_matches_fd(", "_fetch_matches_espn(", "_fetch_matches_tsdb("):
        idx = src.find(provider_call)
        if idx != -1:
            assert idx_gate < idx, f"{provider_call} apare inaintea gate-ului"


def test_flag_ul_nu_e_in_default_config_al_engine_ului():
    """Flag-ul apartine oracle_api (descoperire), nu oracle_engine
    (predictie) — nu trebuie sa se strecoare in DEFAULT_CONFIG-ul motorului,
    unde ar sugera un implicit `False` (tiparul celorlalte flag-uri de acolo)
    si ar contrazice implicitul `True` cerut aici."""
    import oracle_engine

    assert "discovery_live_cascade_enabled" not in oracle_engine.DEFAULT_CONFIG
