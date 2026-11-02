"""Redactarea de secrete din `provider_call_log.error_body` + cablarea Odds API.

Fără rețea, fără Supabase: `_error_body_de_scris` și `_redacteaza_secrete` sunt
funcții PURE, iar `_corp_eroare` e statică.

DE CE EXISTĂ. ADR-081 §3 a justificat persistarea corpului de eroare cu
argumentul: *„cheia RapidAPI circulă exclusiv în header-ul de cerere. Corpul
răspunsului nu o conține."* Adevărat pentru SoccerFootballInfo, singurul
apelant de atunci — **fals pentru Odds API, unde cheia e parametru de query**.
Un provider care își reflectă cererea în corpul erorii ar fi scris cheia în
tabelă. Aceeași clasă ca ADR-077: un ADR invalidează tacit precondiția altuia.
Reparat ÎNAINTE de a produce pagubă, nu după.

CONTRAPONDERI: o redactare prea lată ar distruge exact diagnosticul pentru care
coloana există. Fiecare test de redactare are un geamăn care cere ca textul util
să RĂMÂNĂ.
"""
from __future__ import annotations

import oracle_api
import supabase_client as sb

_CHEIE = "b0e2ab9bcda1d9f4c5ddfe1063a1b2c3"  # 32 hex, inventată, forma reală


# ── Redactare — funcție pură ────────────────────────────────────────────────

def test_apiKey_din_query_e_redactat():
    rezultat = sb._error_body_de_scris(False, f"Invalid: apiKey={_CHEIE}&regions=eu")
    assert _CHEIE not in rezultat
    assert "«REDACTAT»" in rezultat


def test_CONTRAPONDERE_diagnosticul_util_RAMANE_intact():
    """Motivul pentru care coloana există. O redactare care ar șterge asta ar
    face reparația mai rea decât defectul."""
    corp = '{"message":"Unknown market btts","error_code":"INVALID_MARKET"}'
    assert sb._error_body_de_scris(False, corp) == corp


def test_apiKey_in_forma_JSON_e_redactat():
    """Forma în care un API își reflectă cererea într-un corp de eroare.
    O versiune anterioară a regexului o rata complet — între nume și `:` stă
    un ghilimel. Găsit printr-o mutație care a TRECUT.

    VALOAREA E DELIBERAT NE-HEXAZECIMALĂ: cu o cheie hex, testul ar trece prin
    a doua plasă (`_SIR_HEX_LUNG`) chiar și cu regexul vechi, deci ar trece din
    alt motiv decât cel pe care îl declară — exact clasa „un test care nu poate
    distinge ramurile pe care le judecă". Prima versiune a acestui test chiar
    avea defectul; l-a scos la iveală mutația M8."""
    cheie_nehex = "zzzz-cheie-care-nu-e-hexazecimala-9999"
    rezultat = sb._error_body_de_scris(False, f'{{"apiKey": "{cheie_nehex}", "ok": false}}')
    assert cheie_nehex not in rezultat
    assert "«REDACTAT»" in rezultat


def test_apiKey_in_forma_JSON_cu_cheie_hex_e_redactat_de_AMBELE_plase():
    """Cazul real, prins de oricare dintre cele două — păstrat separat, ca
    acoperirea reală să fie vizibilă, nu dedusă."""
    rezultat = sb._error_body_de_scris(False, f'{{"apiKey": "{_CHEIE}"}}')
    assert _CHEIE not in rezultat


def test_CONTRAPONDERE_cheia_de_sport_NU_e_redactata():
    """`key` SIMPLU e deliberat în afara listei: răspunsurile Odds API conțin
    legitim `{"key": "soccer_epl"}`. Testul folosește forma JSON **pe care
    regexul chiar o poate potrivi** — altfel ar trece din construcție, nu din
    corectitudine, și n-ar apăra nimic."""
    corp = '{"key": "soccer_epl", "title": "EPL"}'
    assert sb._error_body_de_scris(False, corp) == corp


def test_sir_hexazecimal_lung_e_redactat_chiar_fara_nume_de_parametru():
    """A doua plasă, pe VALOARE nu pe nume."""
    rezultat = sb._error_body_de_scris(False, f"eroare la {_CHEIE} in cerere")
    assert _CHEIE not in rezultat


def test_CONTRAPONDERE_un_hex_scurt_NU_e_redactat():
    """Un id scurt rămâne — altfel am pierde referințe utile."""
    corp = "fixture deadbeef nu a fost gasit"
    assert sb._error_body_de_scris(False, corp) == corp


def test_token_si_secret_sunt_redactate():
    for nume in ("token", "secret", "password", "access_token", "api_key"):
        rezultat = sb._error_body_de_scris(False, f"{nume}=valoare-sensibila-123")
        assert "valoare-sensibila-123" not in rezultat, f"{nume} nu a fost redactat"


def test_pe_SUCCES_nu_se_scrie_nimic_nici_cu_secret():
    """Garda 1 din ADR-081, neatinsă."""
    assert sb._error_body_de_scris(True, f"apiKey={_CHEIE}") is None


def test_ORDINEA_redactare_INAINTE_de_trunchiere():
    """Load-bearing: trunchierea înaintea redactării ar tăia secretul la
    jumătate, iar jumătatea rămasă tot e o scurgere."""
    umplutura = "x" * (sb._LUNGIME_MAXIMA_ERROR_BODY - 15)
    rezultat = sb._error_body_de_scris(False, f"{umplutura}apiKey={_CHEIE}")
    assert _CHEIE[:8] not in rezultat, "un prefix al cheii a supraviețuit trunchierii"


def test_plafonul_de_lungime_ramane_in_efect():
    """Garda 3 din ADR-081, neatinsă."""
    rezultat = sb._error_body_de_scris(False, "y" * 5000)
    assert len(rezultat) == sb._LUNGIME_MAXIMA_ERROR_BODY


def test_LIMITA_DECLARATA_o_cheie_fara_nume_si_fara_forma_hex_trece():
    """Scris ca test, nu ca notă, ca nimeni să nu presupună mai multă
    protecție decât există. Redactarea e pe TIPAR, nu pe valoare — nu are
    acces la valorile reale ale cheilor. E a DOUA linie de apărare."""
    corp = "eroare: zzzz-nu-arata-a-secret-dar-ar-putea-fi"
    assert sb._error_body_de_scris(False, corp) == corp


# ── `_corp_eroare` — extragerea din răspuns ─────────────────────────────────

class _RespFaraText:
    ok = False
    status_code = 422


class _RespCuText:
    ok = False
    status_code = 422
    text = "  linia 1\n  linia 2  "


class _RespCareArunca:
    ok = False
    status_code = 500

    @property
    def text(self):
        raise RuntimeError("conexiune rupta")


def test_corp_eroare_pe_dublura_fara_text_intoarce_None():
    """Zeci de fișiere de test folosesc `_FakeResp` fără atribut `text`."""
    assert oracle_api.FootballOracleAPI._corp_eroare(_RespFaraText()) is None


def test_corp_eroare_NU_arunca_niciodata():
    """E chemată pe calea de eroare: o excepție aici ar masca defectul pe care
    tocmai încearcă să-l explice."""
    assert oracle_api.FootballOracleAPI._corp_eroare(_RespCareArunca()) is None


def test_corp_eroare_normalizeaza_spatiul_alb():
    assert oracle_api.FootballOracleAPI._corp_eroare(_RespCuText()) == "linia 1 linia 2"


def test_corp_eroare_pe_corp_gol_intoarce_None():
    class _Gol:
        text = "   "
    assert oracle_api.FootballOracleAPI._corp_eroare(_Gol()) is None


# ── Cablarea în `_get` — toate cele patru ramuri de eșec ────────────────────

class _Resp:
    def __init__(self, status_code, text):
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self.text = text
        self.headers = {}

    def json(self):
        return []


def _api_cu(resp):
    api = oracle_api.FootballOracleAPI.__new__(oracle_api.FootballOracleAPI)

    class _S:
        def get(self, url, headers=None, params=None, timeout=12):
            return resp

    api._s = _S()
    api._mem = {}
    api._ttl = 30
    api._cache_mgr = None
    inregistrari: list[dict] = []
    api._record_metric = lambda url, success, latency_ms, status_code=None, exc=None, error_body=None: \
        inregistrari.append({"success": success, "status": status_code, "body": error_body})
    return api, inregistrari


def test_toate_cele_patru_ramuri_de_esec_paseaza_corpul():
    """O ramură uitată ar fi exact tiparul „verifici cele două capete și nu
    firul dintre ele" — garda ar exista, dar nu pe calea care contează."""
    for status in (404, 403, 429, 422):
        api, inreg = _api_cu(_Resp(status, f"corp pentru {status}"))
        api._get("https://api.the-odds-api.com/v4/sports/soccer_epl/odds")
        assert len(inreg) == 1, f"status {status}: {len(inreg)} înregistrări"
        assert inreg[0]["success"] is False
        assert inreg[0]["body"] == f"corp pentru {status}", (
            f"ramura {status} nu pasează corpul: {inreg[0]['body']!r}")


def test_CONTRAPONDERE_pe_succes_nu_se_paseaza_corp():
    api, inreg = _api_cu(_Resp(200, "corp de succes"))
    api._get("https://api.the-odds-api.com/v4/sports")
    assert len(inreg) == 1
    assert inreg[0]["success"] is True
    assert inreg[0]["body"] is None


def test_FIRUL_record_metric_chiar_transmite_corpul_mai_departe(monkeypatch):
    """Mutația M5 (`error_body=None` în `_record_metric`) a TRECUT prima dată:
    toate testele de cablare înlocuiau `_record_metric` cu o dublură, deci
    verificau că `_get` îl cheamă, dar niciodată că el transmite mai departe.
    „Verifici cele două capete și nu firul dintre ele." Aici se exercită firul:
    `_record_metric` e cel REAL, iar `record_provider_call` e interceptat."""
    primite: list[dict] = []

    def _fals(provider, endpoint, success, latency_ms, **kw):
        primite.append({"provider": provider, "endpoint": endpoint, **kw})
        return True

    monkeypatch.setattr(sb, "record_provider_call", _fals)

    api = oracle_api.FootballOracleAPI.__new__(oracle_api.FootballOracleAPI)
    api._record_metric(
        "https://api.the-odds-api.com/v4/sports/soccer_epl/odds",
        False, 12.0, status_code=422, error_body="Unknown market btts")

    assert len(primite) == 1
    assert primite[0]["provider"] == "oddsapi"
    assert primite[0]["endpoint"] == "sports/odds"
    assert primite[0]["error_body"] == "Unknown market btts", (
        "corpul s-a pierdut între `_record_metric` și `record_provider_call`")


def test_cheia_din_corp_nu_ajunge_in_tabela_pe_lantul_INTREG():
    """Testul care contează cel mai mult: de la răspunsul providerului până la
    valoarea care s-ar scrie efectiv, nu doar pe funcția pură."""
    api, inreg = _api_cu(_Resp(401, f'{{"message":"Invalid apiKey={_CHEIE}"}}'))
    api._get("https://api.the-odds-api.com/v4/sports/soccer_epl/odds")
    de_scris = sb._error_body_de_scris(False, inreg[0]["body"])
    assert _CHEIE not in de_scris
    assert "Invalid" in de_scris, "diagnosticul s-a pierdut odată cu secretul"
