"""ADR-085 — „colectat" se citește pe coloana-țintă, nu pe un câmp-martor.

CE PĂZEȘTE, și de ce fiecare gardă există:

`is_flashscore_match_already_collected` întreba *„are acest meci un rezultat?"*
ca proxy pentru *„a colectat Flashscore statisticile?"*. `actual_result` are
patru scriitori, deci proxy-ul e fals ori de câte ori un provider API scrie
rezultatul primul — ce se întâmplă sistematic pentru meciurile de seară,
fiindcă pasul `results` rulează cu patru etape înaintea etapei Flashscore în
aceeași rulare de noapte.

Costul măsurat: 23 de meciuri din 166 (26 oct – 1 nov 2026), printre ele
AC Milan – Inter, Juventus – Napoli, PSG – Lyon, rămase PERMANENT fără
statistici și fără xG. Declanșatorul a fost o reparație a noastră (`9202d82`,
parametrul `d` al SFI) — defectul era latent exact fiindcă un scriitor
concurent era stricat.

NU se testează aici poarta Single Owner (§4.2) — ea stă în
`tests/test_database_queries_single_owner.py`, lângă celelalte teste ale
funcției, ca să nu se despartă de contextul ei.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

import database.queries as q


# ════════════════════════════════════════════════════════════════════════
# Etapa 1 — Delta Sync pe coloana-țintă
# ════════════════════════════════════════════════════════════════════════

class _Rez:
    def __init__(self, data):
        self.data = data


class _Interogare:
    def __init__(self, rows, calls):
        self._rows, self._calls = rows, calls

    def select(self, *a, **kw):
        self._calls.append(("select", a)); return self

    def eq(self, *a, **kw):
        self._calls.append(("eq", a)); return self

    def limit(self, *a, **kw):
        return self

    def execute(self):
        return _Rez(self._rows)


class _Client:
    def __init__(self, rows):
        self._rows, self.calls = rows, []

    def table(self, name):
        self._calls_table = name
        return _Interogare(self._rows, self.calls)


def _rand(**kw):
    """Un rând `match_history` minimal. Implicit: meci TERMINAT, de ieri,
    FĂRĂ statistici — adică exact cazul celor 23."""
    baza = {
        "id": 1,
        "kickoff_date": (datetime.now(timezone.utc) - timedelta(days=1))
                        .replace(microsecond=0).isoformat(),
        "actual_result": "H",
        "home_shots": None,
    }
    baza.update(kw)
    return baza


def _colectat(monkeypatch, rows):
    monkeypatch.setattr(q, "get_client", lambda: _Client(rows))
    return q.is_flashscore_match_already_collected("abc123")


def test_DEFECTUL_REPARAT_rezultat_prezent_dar_fara_statistici_se_RECOLECTEAZA(monkeypatch):
    """Cazul celor 23. Înainte: `True` (sărit permanent). Acum: `False`."""
    assert _colectat(monkeypatch, [_rand()]) is False


def test_cu_statistici_se_sare(monkeypatch):
    """Cazul normal, 1608 meciuri — comportament identic cu înainte, zero cost
    în plus."""
    assert _colectat(monkeypatch, [_rand(home_shots=12)]) is True


def test_statistici_prezente_dar_rezultat_absent_se_sare_TOT(monkeypatch):
    """Contrapondere care prinde o implementare care ar fi păstrat tăcut
    condiția pe `actual_result` alături de cea nouă (un `and` în loc de
    înlocuire). Statisticile există — nu mai avem ce colecta, indiferent de
    rezultat."""
    assert _colectat(monkeypatch, [_rand(actual_result=None, home_shots=5)]) is True


def test_rand_inexistent_se_colecteaza(monkeypatch):
    assert _colectat(monkeypatch, []) is False


def test_fara_client_se_colecteaza(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: None)
    assert q.is_flashscore_match_already_collected("x") is False


def test_eroare_de_retea_se_colecteaza(monkeypatch):
    class _Boom:
        def table(self, name):
            raise RuntimeError("retea picata")
    monkeypatch.setattr(q, "get_client", lambda: _Boom())
    assert q.is_flashscore_match_already_collected("x") is False


# ── Pașii NEATINȘI din 5 august: trebuie să rămână identici ────────────────

def test_meci_in_VIITOR_se_sare_chiar_fara_statistici(monkeypatch):
    """Pasul 3, neatins. CRITIC: fără el, fiecare fixture viitor descoperit de
    Discovery (7 zile înainte, schelet fără statistici) ar fi re-descărcat la
    FIECARE rulare — exact risipa reparată la `live_sync` în august."""
    viitor = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    assert _colectat(monkeypatch, [_rand(kickoff_date=viitor, actual_result=None)]) is True


def test_kickoff_lipsa_se_sare(monkeypatch):
    """Pasul 2, neatins — nu putem decide, deci nu ghicim (Regula #8)."""
    assert _colectat(monkeypatch, [_rand(kickoff_date=None)]) is True


def test_kickoff_neparsabil_se_sare(monkeypatch):
    assert _colectat(monkeypatch, [_rand(kickoff_date="nu-e-o-data")]) is True


def test_marja_de_fus_orar_de_6h_e_pastrata(monkeypatch):
    """Un meci care începe în 3 ore (deci în fereastra de ambiguitate de 6h)
    se RECOLECTEAZĂ — a reîncerca puțin prea devreme e ieftin, a nu reîncerca
    niciodată e defectul reparat în august. Garda există fiindcă varianta
    inițială de atunci adunase marja în direcția greșită."""
    curand = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
    assert _colectat(monkeypatch, [_rand(kickoff_date=curand, actual_result=None)]) is False


# ── Pasul NOU: marginea de renunțare ──────────────────────────────────────

def test_dincolo_de_fereastra_se_RENUNTA(monkeypatch):
    """Pasul 4, nou. Fără el, un meci pe care Flashscore genuin nu-l servește
    ar fi recerut la nesfârșit."""
    vechi = (datetime.now(timezone.utc)
             - timedelta(days=q.FLASHSCORE_RECOLLECT_WINDOW_DAYS + 5)).isoformat()
    assert _colectat(monkeypatch, [_rand(kickoff_date=vechi)]) is True


def test_in_interiorul_ferestrei_se_recolecteaza(monkeypatch):
    """Contrapondere: marginea nu are voie să înghită fereastra utilă."""
    recent = (datetime.now(timezone.utc)
              - timedelta(days=q.FLASHSCORE_RECOLLECT_WINDOW_DAYS - 5)).isoformat()
    assert _colectat(monkeypatch, [_rand(kickoff_date=recent)]) is False


def test_fereastra_e_ACEEASI_cu_implicitul_recuperarii():
    """O singură definiție, nu două care pot deriva. `FLASHSCORE_RECOLLECT_
    WINDOW_DAYS` trebuie să fie egal cu implicitul lui
    `get_flashscore_mids_missing_statistics(days_back=…)` — altfel Delta Sync
    ar renunța la meciuri pe care recuperarea încă le caută, sau invers."""
    import inspect
    implicit = inspect.signature(
        q.get_flashscore_mids_missing_statistics).parameters["days_back"].default
    assert q.FLASHSCORE_RECOLLECT_WINDOW_DAYS == implicit


def test_coloana_tinta_e_CERUTA_in_select(monkeypatch):
    """Garda care prinde o implementare care verifică `home_shots` fără să-l
    ceară — ar primi mereu `None` din dicționar și ar recolecta totul, la
    nesfârșit, arătând „corect" pe testele de mai sus care pasează câmpul."""
    client = _Client([_rand()])
    monkeypatch.setattr(q, "get_client", lambda: client)
    q.is_flashscore_match_already_collected("abc")
    coloane = [a[0] for nume, a in client.calls if nume == "select"]
    assert coloane and "home_shots" in coloane[0], (
        f"`home_shots` nu e cerut în select: {coloane}")


# ════════════════════════════════════════════════════════════════════════
# Etapa 3 — `stats_source` doar când s-a extras efectiv ceva
# ════════════════════════════════════════════════════════════════════════

from providers.flashscore import normalizer as nz  # noqa: E402


_SUMMARY_MINIM = """
<html><body>
  <div class="duelParticipant__home"><div class="participant__participantName">Arsenal</div></div>
  <div class="duelParticipant__away"><div class="participant__participantName">Chelsea</div></div>
</body></html>
"""


def test_fara_nicio_statistica_extrasa_stats_source_LIPSESTE(monkeypatch):
    """Cazul celor 29 de rânduri care mint: o vizită de dinainte de meci
    extrage stadionul și clasamentul, dar zero statistici — și revendica
    totuși Flashscore ca sursă a statisticilor."""
    monkeypatch.setattr(nz, "_extract_labeled_stat_pairs", lambda *a, **kw: {})
    rezultat = nz.normalize_match_statistics({"summary": _SUMMARY_MINIM})
    assert "stats_source" not in rezultat, (
        "`stats_source` revendicat fără nicio statistică extrasă")


def test_cu_statistici_extrase_stats_source_E_SCRIS(monkeypatch):
    """Contrapondere obligatorie: fără ea, o implementare care nu scrie
    NICIODATĂ `stats_source` ar trece testul de mai sus. Un „lipsește" nu se
    raportează fără martorul pozitiv."""
    monkeypatch.setattr(nz, "_extract_labeled_stat_pairs",
                        lambda *a, **kw: {"Total shots": ("12", "7")})
    rezultat = nz.normalize_match_statistics({"summary": _SUMMARY_MINIM})
    assert rezultat.get("stats_source") == "flashscore"


def test_eticheta_prezenta_dar_NEPARSABILA_nu_revendica(monkeypatch):
    """Întrebarea corectă e „a ajuns vreo valoare în payload?", nu „a existat
    vreo etichetă pe pagină?". O etichetă cu „-" sau text gol lasă coloana
    NULL, deci nu e o extragere."""
    monkeypatch.setattr(nz, "_extract_labeled_stat_pairs",
                        lambda *a, **kw: {"Total shots": ("-", "")})
    rezultat = nz.normalize_match_statistics({"summary": _SUMMARY_MINIM})
    assert "stats_source" not in rezultat


def test_revendicarea_se_face_pe_campuri_de_STATISTICI_nu_pe_arbitru(monkeypatch):
    """`referee`/`stadium`/scorul vin din tabul summary, nu din cel de
    statistici. Un rând cu arbitru și fără statistici e exact semnătura celor
    23 de meciuri — nu are voie să revendice."""
    monkeypatch.setattr(nz, "_extract_labeled_stat_pairs", lambda *a, **kw: {})
    monkeypatch.setattr(nz, "_extract_labeled_info_pairs",
                        lambda *a, **kw: {"Referee:": "Oliver M.",
                                          "Venue:": "Emirates"})
    rezultat = nz.normalize_match_statistics({"summary": _SUMMARY_MINIM})
    assert rezultat.get("referee") == "Oliver M."
    assert "stats_source" not in rezultat


# ════════════════════════════════════════════════════════════════════════
# Etapa 4 — clasa 11 din `check_data_health` (funcție PURĂ)
# ════════════════════════════════════════════════════════════════════════

from scripts.check_data_health import (  # noqa: E402
    _PRAG_ZILE_FARA_STATISTICI,
    meciuri_fara_statistici,
)

_AZI = date(2026, 11, 2)


def _m(zile_in_urma: int, **kw):
    baza = {
        "league": "Serie A",
        "kickoff_date": (_AZI - timedelta(days=zile_in_urma)).isoformat(),
        "home_team": "AC Milan", "away_team": "Inter Milan",
        "home_shots": None, "referee": None,
    }
    baza.update(kw)
    return baza


def test_clasa11_prinde_golul_delta_sync():
    gol = meciuri_fara_statistici([_m(5)], _AZI)
    assert gol["total"] == 1
    assert len(gol["delta_sync"]) == 1 and not gol["extragere"]


def test_clasa11_separa_clasa_ADR076_prin_arbitru():
    """Cele două clase au remedii OPUSE: recolectarea rezolvă prima și nu face
    nimic pentru a doua. A le raporta împreună ar trimite pe pistă greșită
    exact persoana care citește raportul."""
    gol = meciuri_fara_statistici([_m(5), _m(60, referee="Oliver M.")], _AZI)
    assert len(gol["delta_sync"]) == 1
    assert len(gol["extragere"]) == 1
    assert gol["total"] == 2


def test_clasa11_nu_raporteaza_meciuri_prea_recente():
    """Latența normală e sub 2 zile — un meci de ieri fără statistici e
    așteptat, nu un defect. Fără pragul asta clasa ar fi roșie în fiecare
    dimineață, adică exact boala documentată a lui `check_data_health`."""
    gol = meciuri_fara_statistici([_m(_PRAG_ZILE_FARA_STATISTICI - 1)], _AZI)
    assert gol["total"] == 0


def test_clasa11_la_prag_EXACT_raporteaza():
    """Graniță explicită, ca pragul să nu alunece tăcut cu o zi."""
    assert meciuri_fara_statistici([_m(_PRAG_ZILE_FARA_STATISTICI)], _AZI)["total"] == 1


def test_clasa11_ignora_meciurile_CU_statistici():
    assert meciuri_fara_statistici([_m(5, home_shots=14)], _AZI)["total"] == 0


def test_clasa11_zero_cand_totul_e_curat():
    """Starea sănătoasă trebuie să fie ATINGIBILĂ — un indicator care nu poate
    fi verde nu e un indicator (lecția `coverage_percent` fix la 100%)."""
    randuri = [_m(5, home_shots=10), _m(20, home_shots=3), _m(1)]
    assert meciuri_fara_statistici(randuri, _AZI)["total"] == 0


def test_clasa11_tolereaza_forma_lunga_de_data():
    """`match_history.kickoff_date` e `text` și ține DOUĂ forme — 57.366
    rânduri `YYYY-MM-DD` și 2.390 `YYYY-MM-DDTHH:MM:SS`. Exact ambiguitatea
    care a produs defectul parametrului `d` (`9202d82`), adică declanșatorul
    întregului ADR-085. Nu se repetă aici."""
    gol = meciuri_fara_statistici(
        [_m(5) | {"kickoff_date": "2026-10-28T20:45:00"}], _AZI)
    assert gol["total"] == 1


def test_clasa11_sare_randurile_cu_data_invalida_fara_sa_arunce():
    """Degradare grațioasă (Regula #8) — un rând nedecidabil nu oprește
    raportul și nu e numărat ca defect."""
    gol = meciuri_fara_statistici([_m(5) | {"kickoff_date": "15/10/2026"},
                                   _m(5) | {"kickoff_date": None},
                                   _m(7)], _AZI)
    assert gol["total"] == 1


def test_clasa11_e_functie_PURA():
    """Nicio citire din bază — testabilă fără Supabase și fără o rulare de
    noapte, aceeași convenție ca `serie_3_din_3`. Garda e pe semnătură: dacă
    cineva îi adaugă un client, parametrii se schimbă și testul cade."""
    import inspect
    params = list(inspect.signature(meciuri_fara_statistici).parameters)
    assert params == ["randuri", "azi", "prag_zile"], params


def test_clasa11_ordoneaza_dupa_data():
    """Raportul se citește de om; o listă neordonată face greu de văzut dacă
    golul e vechi sau de ieri."""
    gol = meciuri_fara_statistici([_m(4), _m(30), _m(10)], _AZI)
    date_ = [m["kickoff_date"] for m in gol["delta_sync"]]
    assert date_ == sorted(date_)
