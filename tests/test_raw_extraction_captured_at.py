"""A treia instanta a capcanei cu timestamp inghetat, in `flashscore_raw_extraction`.

CUM A IESIT LA IVEALA. Nu printr-un test si nu printr-o revizuire de cod, ci
incercand sa RASPUND la o intrebare: au fost cele 4 fixture-uri-fantoma
reincercate dupa amanare, sau au fost atinse o singura data, cand erau inca
meciuri viitoare? `captured_at` arata 5-10 august pentru toate — dar acel
raspuns nu insemna nimic, fiindca `upsert_raw_extraction()` nu punea niciodata
`captured_at` in payload. `DEFAULT now()` se aplica DOAR pe ramura INSERT; pe
`DO UPDATE` valoarea veche supravietuia. Tabela nu putea spune cand a fost
vazuta ultima oara pagina.

CE NU E. Nu e pierdere de date — `raw_extracted` se improspata corect de
fiecare data. E o problema de INTERPRETARE: un marcaj temporal care minte e
mai rau decat unul absent, fiindca invita exact rationamentul gresit pe care
l-am facut.

TIPARUL, a treia oara: `flashscore_raw_extraction` (alt camp), apoi
`flashscore_standings_snapshot`, acum aceasta. Un `on_conflict` care nu include
timestamp-ul in payload il INGHEATA tacit. Regula generala: orice upsert pe o
tabela cu marcaj temporal trebuie sa-l scrie EXPLICIT.

Fara retea, fara Supabase.
"""
from __future__ import annotations

from datetime import datetime, timezone

import database.queries as q


class _Rezultat:
    data: list = []


class _Tabela:
    def __init__(self, jurnal, nume):
        self._j, self._nume = jurnal, nume

    def upsert(self, payload, on_conflict=None):
        self._j.append((self._nume, payload, on_conflict))
        return self

    def execute(self):
        return _Rezultat()


class _Client:
    def __init__(self):
        self.jurnal: list = []

    def table(self, nume):
        return _Tabela(self.jurnal, nume)


def _scrie(monkeypatch, **kw):
    c = _Client()
    monkeypatch.setattr(q, "get_client", lambda: c)
    ok = q.upsert_raw_extraction(
        kw.pop("match_ref", "rijeka__din-zagreb__2026-08-08"),
        kw.pop("tab_name", "stats"),
        kw.pop("raw_extracted", {"home_team": "Rijeka", "away_team": "Dinamo Zagreb"}),
        **kw,
    )
    return c, ok


# ── garda centrala ───────────────────────────────────────────────────────────

def test_captured_at_ajunge_in_payload(monkeypatch):
    """Fara asta, ramane ora primei capturi pentru totdeauna."""
    c, ok = _scrie(monkeypatch)
    assert ok is True
    tabela, payload, conflict = c.jurnal[0]
    assert tabela == "flashscore_raw_extraction"
    assert conflict == "match_ref,tab_name"
    assert "captured_at" in payload, (
        "fara `captured_at` explicit, ramura DO UPDATE pastreaza ora veche"
    )


def test_captured_at_e_momentul_scrierii_nu_o_constanta(monkeypatch):
    """Prinde mutatia care pune o valoare fixa in loc de `now()` — o constanta
    ar trece testul de mai sus si ar minti la fel de tare."""
    inainte = datetime.now(timezone.utc)
    c, _ = _scrie(monkeypatch)
    _, payload, _ = c.jurnal[0]
    scris = datetime.fromisoformat(payload["captured_at"])
    dupa = datetime.now(timezone.utc)
    assert inainte <= scris <= dupa, f"captured_at in afara ferestrei apelului: {scris}"


def test_captured_at_are_fus_orar(monkeypatch):
    """Coloana e `timestamptz`. Un timestamp naiv ar fi interpretat dupa fusul
    serverului, nu dupa UTC — aceeasi clasa de eroare tacuta, alt mecanism."""
    c, _ = _scrie(monkeypatch)
    _, payload, _ = c.jurnal[0]
    assert datetime.fromisoformat(payload["captured_at"]).tzinfo is not None


def test_doua_scrieri_succesive_dau_momente_diferite(monkeypatch):
    """Contraproba directa a defectului: aceeasi cheie naturala, scrisa de doua
    ori, trebuie sa poarte doua momente — altfel nu se poate raspunde niciodata
    la 'cand a fost vazuta ultima oara pagina asta?'."""
    c = _Client()
    monkeypatch.setattr(q, "get_client", lambda: c)
    for _ in range(2):
        q.upsert_raw_extraction("acelasi__meci__2026-08-08", "stats", {"x": 1})
    momente = [datetime.fromisoformat(p["captured_at"]) for _, p, _ in c.jurnal]
    assert len(c.jurnal) == 2
    assert momente[1] >= momente[0]
    assert momente[0].tzinfo and momente[1].tzinfo


# ── contrapondere: fixul nu are voie sa strice restul ────────────────────────

def test_restul_campurilor_raman_neatinse(monkeypatch):
    brut = {"home_team": "Rijeka", "flashscore_status_raw": "Postponed"}
    c, _ = _scrie(
        monkeypatch, raw_extracted=brut, validation_status="rejected",
        validation_errors=["motiv"], canonical_written=False, season="2026-2027",
    )
    _, payload, _ = c.jurnal[0]
    assert payload["raw_extracted"] == brut
    assert payload["validation_status"] == "rejected"
    assert payload["validation_errors"] == ["motiv"]
    assert payload["canonical_written"] is False
    assert payload["season"] == "2026-2027"
    assert payload["match_ref"] == "rijeka__din-zagreb__2026-08-08"
    assert payload["tab_name"] == "stats"


def test_raw_gol_nu_scrie_nimic(monkeypatch):
    """Comportament preexistent, pastrat: un tab fara continut nu produce rand
    — deci nici nu-i reimprospateaza timestamp-ul degeaba."""
    c, ok = _scrie(monkeypatch, raw_extracted={})
    assert ok is True
    assert c.jurnal == []


def test_fara_client_nu_arunca(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: None)
    assert q.upsert_raw_extraction("m", "stats", {"x": 1}) is False


def test_esecul_scrierii_e_raportat_nu_ascuns(monkeypatch):
    class _TabelaCareCade(_Tabela):
        def execute(self):
            raise RuntimeError("retea cazuta")

    class _ClientCareCade(_Client):
        def table(self, nume):
            return _TabelaCareCade(self.jurnal, nume)

    monkeypatch.setattr(q, "get_client", lambda: _ClientCareCade())
    assert q.upsert_raw_extraction("m", "stats", {"x": 1}) is False
