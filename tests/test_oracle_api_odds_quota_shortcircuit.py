"""Scurt-circuit la nivel de etapă pentru `_attach_odds()` (oracle_api.py) —
golul notat explicit în CLAUDE.md: „RequestManager.should_request() e
verificat și loghează un WARNING separat la FIECARE tentativă individuală
(per ligă/zi/fixture), fără niciun scurt-circuit la nivel de etapă care să
sară peste tot restul lucrului legat de cote odds odată ce se confirmă
epuizarea zilei."

DE CE CONTEAZĂ. `get_matches_for_week()` — și odată cu el, `_attach_odds()`
— e apelat independent de mai multe etape în aceeași rulare de noapte
(odds_persistence, weather_forecast, team_health, Challenger Shadow
Batch), fiecare cu propria instanță `FootballOracleAPI()`. Fără acest
control, fiecare din cele 4 apeluri re-iterează de la zero fiecare ligă
distinctă din meciurile primite, chiar și când cota e deja epuizată pentru
toată ziua — mii de iterații Python + I/O de logging identice.

`should_request("oddsapi")` însuși rămâne NESCHIMBAT — fail-safe-ul care
blochează orice cerere HTTP reală era deja corect (confirmat în cod:
`rate_limit_manager.can_request()`). Acest fișier verifică doar noul strat
de deasupra: verificarea O SINGURĂ dată, înainte de buclă, nu per-ligă.

Fără rețea, fără Supabase.
"""
from __future__ import annotations

import oracle_api


def _api_with_request_manager(should_request_result: bool):
    api = oracle_api.FootballOracleAPI.__new__(oracle_api.FootballOracleAPI)
    api._dead_keys = set()

    class _FakeRM:
        def __init__(self):
            self.calls: list[str] = []

        def should_request(self, provider: str) -> bool:
            self.calls.append(provider)
            return should_request_result

    api._request_manager = _FakeRM()
    return api


def _matches(n: int = 3):
    return [
        {"fixture_id": f"fx{i}", "home_team": "A", "away_team": "B",
         "league": "Premier League", "_odds_api_id": f"ev{i}"}
        for i in range(n)
    ]


# ── _oddsapi_quota_exhausted() ────────────────────────────────────────────

def test_cota_disponibila_intoarce_false():
    api = _api_with_request_manager(should_request_result=True)
    assert api._oddsapi_quota_exhausted() is False


def test_cota_epuizata_intoarce_true():
    api = _api_with_request_manager(should_request_result=False)
    assert api._oddsapi_quota_exhausted() is True


def test_verifica_exact_providerul_oddsapi():
    api = _api_with_request_manager(should_request_result=True)
    api._oddsapi_quota_exhausted()
    assert api._request_manager.calls == ["oddsapi"]


def test_fara_request_manager_esueaza_deschis_spre_disponibil(caplog):
    """Consecvent cu restul fișierului (getattr defensiv, teste vechi care
    construiesc obiectul prin __new__ fără toate atributele) — o eroare de
    citire NU blochează tacit cote care ar fi fost disponibile."""
    api = oracle_api.FootballOracleAPI.__new__(oracle_api.FootballOracleAPI)
    assert api._oddsapi_quota_exhausted() is False


# ── cablare în _attach_odds() ────────────────────────────────────────────

def test_cota_epuizata_sare_toata_bucla_nu_doar_un_meci():
    """GARDA CENTRALĂ. Fără verificarea O SINGURĂ dată, `_fetch_odds` ar fi
    apelat per ligă distinctă — aici testăm că NU e apelat deloc."""
    api = _api_with_request_manager(should_request_result=False)
    apeluri_fetch: list[str] = []
    api._fetch_odds = lambda sk: apeluri_fetch.append(sk) or {}

    rezultat = api._attach_odds(_matches(5))

    assert apeluri_fetch == [], "cu cota epuizata, _fetch_odds nu are voie sa fie apelat deloc"
    assert len(rezultat) == 5, "meciurile raman neschimbate, nu se pierd"


def test_cota_disponibila_ataseaza_normal_cotele():
    """Contrapondere: fixul nu are voie să strice calea normală."""
    api = _api_with_request_manager(should_request_result=True)
    api._fetch_odds = lambda sk: {
        "ev0": {"home": 2.1, "draw": 3.4, "away": 3.8, "bookmaker": "Bet365",
                "ev_id": "ev0", "over25": 0.0, "under25": 0.0,
                "btts_yes": 0.0, "btts_no": 0.0},
    }
    rezultat = api._attach_odds(_matches(1))
    assert rezultat[0]["home_odds"] == 2.1


def test_verificarea_se_face_o_singura_data_nu_per_liga():
    """Cu 5 meciuri din 3 ligi distincte, cota trebuie verificată o singură
    dată — nu de 3 ori (per ligă) și nu de 5 ori (per meci)."""
    api = _api_with_request_manager(should_request_result=True)
    api._fetch_odds = lambda sk: {}
    matches = [
        {"fixture_id": "a", "home_team": "X", "away_team": "Y", "league": "Premier League", "_odds_api_id": "e1"},
        {"fixture_id": "b", "home_team": "X", "away_team": "Y", "league": "La Liga", "_odds_api_id": "e2"},
        {"fixture_id": "c", "home_team": "X", "away_team": "Y", "league": "Serie A", "_odds_api_id": "e3"},
        {"fixture_id": "d", "home_team": "X", "away_team": "Y", "league": "Premier League", "_odds_api_id": "e4"},
        {"fixture_id": "e", "home_team": "X", "away_team": "Y", "league": "La Liga", "_odds_api_id": "e5"},
    ]
    api._attach_odds(matches)
    assert len(api._request_manager.calls) == 1


def test_lista_goala_de_meciuri_nu_verifica_deloc_cota():
    """O listă goală nu are ce ligă să itereze — verificarea gating-ului
    ar fi lucru degeaba, chiar dacă ieftin."""
    api = _api_with_request_manager(should_request_result=True)
    api._attach_odds([])
    assert api._request_manager.calls == []


def test_cota_epuizata_pe_lista_goala_nu_arunca():
    api = _api_with_request_manager(should_request_result=False)
    assert api._attach_odds([]) == []
