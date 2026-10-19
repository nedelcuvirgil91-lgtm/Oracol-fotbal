"""Gardă ADR-076 D-B: recuperarea restanței de statistici, fără să devină
un buton care dezactivează Delta Sync.

DE CE EXISTĂ
Reparația selectorilor (ADR-076) repară meciurile NOI. Restanța lăsată de cele
39 de zile de tăcere — 653 de meciuri terminate fără `home_shots`, toate cu
`mid` Flashscore, în 20 de competiții — nu se repară singură: Delta Sync sare
peste orice meci deja persistat canonic, corect în regim normal, fatal aici.

CE APĂRĂ
  1. Bypass-ul se aplică DOAR `mid`-urilor cerute explicit. Un meci care nu e
     în setul-țintă rămâne sărit — altfel „recuperarea" ar fi, de fapt,
     dezactivarea Delta Sync pentru toată rularea, cu re-fetch inutil pe tot
     sezonul.
  2. Lista se calculează din bază pe o coloană-ȚINTĂ (`home_shots IS NULL`),
     nu pe un câmp-martor. Lecția ADR-077: `referee` părea semnalul corect
     pentru „lipsesc datele" până a căpătat al doilea scriitor.
  3. Selectorul pagineză keyset și întoarce setul GOL la eroare, niciodată
     unul parțial — un parțial ar produce o recuperare care pare completă.
  4. Plafonul pe tranșă e respectat: fără el, 653 de meciuri × 7 taburi ar
     depăși `timeout-minutes: 90`, exact tiparul plătit deja de `live_sync` și
     `sync_pre_match_odds`.

Fără rețea, fără Supabase.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import database.queries as q
from providers.flashscore import discovery as disc
from providers.flashscore import run_foundation_data_layer as cli


# ════════════════════════════════════════════════════════════════════════
# Client fals care APLICĂ filtrele care contează
# ════════════════════════════════════════════════════════════════════════
class _Query:
    def __init__(self, rows: list[dict], store: dict) -> None:
        self._rows = rows
        self._store = store
        self._gt_id = 0
        self._limit: int | None = None
        self._ordered = False

    # filtre care doar se înregistrează (verificate în teste)
    def select(self, cols):  # noqa: D102
        self._store.setdefault("select", []).append(cols)
        return self

    # `.not_.is_(...)` — interfața reală a clientului Supabase. O singură
    # definiție, deliberat: o primă versiune avea și o metodă `not_`, iar
    # Python păstrează doar ultima definiție. Exact clasa de defect pentru
    # care există `tests/test_no_shadowed_tests.py`, comisă în propria gardă.
    @property
    def not_(self):
        parent = self

        class _Not:
            def is_(self, col, val):
                parent._store.setdefault("not_is", []).append((col, val))
                return parent
        return _Not()

    def is_(self, col, val):
        self._store.setdefault("is", []).append((col, val))
        return self

    def gte(self, col, val):
        self._store.setdefault("gte", []).append((col, val))
        return self

    def like(self, col, val):
        self._store.setdefault("like", []).append((col, val))
        return self

    def in_(self, col, vals):
        self._store.setdefault("in", []).append((col, list(vals)))
        return self

    # filtrele care CHIAR se aplică — fără ele, testul de paginare nu dovedește nimic
    def gt(self, col, val):
        assert col == "id"
        self._gt_id = val
        return self

    def order(self, col):
        assert col == "id", "paginarea keyset cere ORDER BY id EXPLICIT"
        self._ordered = True
        return self

    def limit(self, n):
        self._limit = n
        return self

    def execute(self):
        assert self._ordered, "fără `order('id')`, ordinea între pagini nu e garantată"
        vizibile = [r for r in self._rows if r["id"] > self._gt_id]
        vizibile.sort(key=lambda r: r["id"])
        # Plafonul PostgREST se aplică MEREU, nu doar când cerem `.limit()` —
        # un fals care l-ar ignora ar face testele să treacă degeaba (lecția
        # deja plătită la `tests/test_shadow_pagination.py`).
        plafon = min(self._limit or q._PAGE_SIZE, q._PAGE_SIZE)
        return SimpleNamespace(data=vizibile[:plafon])


class _Client:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.store: dict = {}

    def table(self, name):
        self.store.setdefault("tables", []).append(name)
        return _Query(self.rows, self.store)


class _BoomClient:
    def table(self, name):
        raise RuntimeError("cădere simulată de rețea")


class _BoomLaPaginaADoua:
    """Cade DUPĂ ce prima pagină a reușit.

    [GARDĂ REPARATĂ — defect găsit prin mutație, nu prin noroc] Prima
    versiune folosea doar `_BoomClient`, care cade la prima cerere: acolo
    `mids` e gol oricum, deci „întoarce set gol" și „întoarce parțialul"
    produc exact același rezultat. Mutația care înlocuia `return set()` cu
    `return mids` a trecut neprinsă. Un parțial e periculos tocmai când o
    parte a reușit — adică exact cazul pe care garda nu-l construia."""

    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.apeluri = 0
        self.store: dict = {}

    def table(self, name):
        self.apeluri += 1
        if self.apeluri > 1:
            raise RuntimeError("cădere simulată la pagina a doua")
        return _Query(self.rows, self.store)


def _rand(i: int, mid: str) -> dict:
    return {"id": i, "fixture_id": f"flashscore_{mid}"}


# ════════════════════════════════════════════════════════════════════════
# 2 + 3. Selectorul
# ════════════════════════════════════════════════════════════════════════

def test_intoarce_mid_urile_din_fixture_id(monkeypatch):
    client = _Client([_rand(1, "aaa"), _rand(2, "bbb")])
    monkeypatch.setattr(q, "get_client", lambda: client)
    assert q.get_flashscore_mids_missing_statistics() == {"aaa", "bbb"}


def test_criteriul_e_coloana_tinta_nu_un_camp_martor(monkeypatch):
    """ADR-077: `referee` a încetat să fie un semnal valid în momentul în care
    a căpătat al doilea scriitor. Garda fixează că nu ne sprijinim pe el."""
    client = _Client([_rand(1, "aaa")])
    monkeypatch.setattr(q, "get_client", lambda: client)
    q.get_flashscore_mids_missing_statistics()
    coloane_is_null = [col for col, _ in client.store.get("is", [])]
    assert "home_shots" in coloane_is_null
    assert "referee" not in coloane_is_null
    assert ("fixture_id", "flashscore_%") in client.store.get("like", [])


def test_pagineaza_peste_plafonul_postgrest(monkeypatch):
    """A cincea instanță a clasei în proiect — reparată din start, nu după."""
    rows = [_rand(i, f"m{i}") for i in range(1, q._PAGE_SIZE + 251)]
    client = _Client(rows)
    monkeypatch.setattr(q, "get_client", lambda: client)
    rezultat = q.get_flashscore_mids_missing_statistics(limit=10_000)
    assert len(rezultat) == q._PAGE_SIZE + 250


def test_eroarea_la_prima_cerere_intoarce_set_gol(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: _BoomClient())
    assert q.get_flashscore_mids_missing_statistics() == set()


def test_eroarea_DUPA_o_pagina_reusita_intoarce_GOL_nu_partialul(monkeypatch):
    """Cazul care contează: 1000 de `mid`-uri citite, apoi cădere. Un parțial
    ar arăta ca o recuperare completă și ar lăsa restul restanței nerecuperat,
    tăcut — a doua oară în proiect când un parțial ar fi mai rău decât nimic
    (prima: `get_shadow_predictions`, ADR-076-era, unde un parțial dădea un
    verdict fals)."""
    rows = [_rand(i, f"m{i}") for i in range(1, q._PAGE_SIZE + 51)]
    client = _BoomLaPaginaADoua(rows)
    monkeypatch.setattr(q, "get_client", lambda: client)
    assert q.get_flashscore_mids_missing_statistics(limit=10_000) == set()
    assert client.apeluri == 2, "prima pagină trebuie să fi reușit, altfel testul nu dovedește nimic"


def test_cursorul_care_nu_avanseaza_opreste_bucla(monkeypatch):
    """Garda împotriva buclei infinite, adăugată după ce o mutație („cursorul
    ia primul rând, nu ultimul") a BLOCAT suita în loc să o facă să eșueze.
    Un defect care consumă tot bugetul de rulare în tăcere e mai rău decât
    unul care aruncă."""
    rows = [_rand(i, f"m{i}") for i in range(1, q._PAGE_SIZE + 51)]

    class _CursorBlocat(_Client):
        def table(self, name):
            qq = _Query(self.rows, self.store)
            qq.gt = lambda col, val: qq  # ignoră cursorul: mereu prima pagină
            return qq

    client = _CursorBlocat(rows)
    monkeypatch.setattr(q, "get_client", lambda: client)
    rezultat = q.get_flashscore_mids_missing_statistics(limit=10_000)
    # Se oprește după prima pagină, în loc să ceară aceeași pagină la infinit.
    assert len(rezultat) == q._PAGE_SIZE


def test_fara_client_nu_crapa(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: None)
    assert q.get_flashscore_mids_missing_statistics() == set()


def test_citeste_doar_coloanele_necesare(monkeypatch):
    client = _Client([_rand(1, "aaa")])
    monkeypatch.setattr(q, "get_client", lambda: client)
    q.get_flashscore_mids_missing_statistics()
    assert all(c == "id,fixture_id" for c in client.store["select"]), \
        "un `select('*')` ar aduce zeci de coloane degeaba"


# ════════════════════════════════════════════════════════════════════════
# 1. Bypass-ul se aplică DOAR țintelor
# ════════════════════════════════════════════════════════════════════════
def _meci(mid: str, liga: str = "La Liga"):
    return SimpleNamespace(mid=mid, league=liga,
                           match_base_url=f"https://x/{mid}", source="results",
                           season=None, season_start=None, season_end=None)


@pytest.fixture()
def fara_retea(monkeypatch):
    """Oprește lanțul înainte de orice cerere reală: `fetch` aruncă, deci se
    vede CARE meciuri au ajuns la el — exact ce vrem să măsurăm."""
    atinse: list[str] = []

    class _Adapter:
        def preflight(self):
            return None

        def fetch(self, params):
            atinse.append(params["mid"])
            raise RuntimeError("fetch oprit deliberat în test")

    monkeypatch.setattr(disc, "polite_delay", lambda: None)
    import providers.flashscore.adapter as ad
    monkeypatch.setattr(ad, "FlashscoreAdapter", lambda *a, **k: _Adapter())
    return atinse


def test_bypass_doar_pentru_mid_urile_cerute(monkeypatch, fara_retea):
    monkeypatch.setattr(q, "is_flashscore_match_already_collected", lambda mid: True)
    rapoarte = disc.run_foundation_data_layer_for_discovered_matches(
        [_meci("tinta"), _meci("necerut")], force_mids={"tinta"},
    )
    assert fara_retea == ["tinta"], "doar ținta trebuie să ajungă la fetch"
    sarite = [r for r in rapoarte if r.get("skipped")]
    assert [r["match"].mid for r in sarite] == ["necerut"]


def test_fara_force_mids_comportamentul_e_neschimbat(monkeypatch, fara_retea):
    """Contraponderea: Delta Sync rămâne regula, recuperarea e excepția."""
    monkeypatch.setattr(q, "is_flashscore_match_already_collected", lambda mid: True)
    rapoarte = disc.run_foundation_data_layer_for_discovered_matches(
        [_meci("a"), _meci("b")],
    )
    assert fara_retea == []
    assert all(r.get("skipped") for r in rapoarte)


def test_force_mids_nu_ocoleste_delta_sync_pentru_restul(monkeypatch, fara_retea):
    """Un meci NEcolectat trece oricum (Delta Sync întoarce False), deci
    prezența lui la fetch nu dovedește nimic despre bypass — testul fixează
    că setul nu se extinde tacit."""
    monkeypatch.setattr(q, "is_flashscore_match_already_collected",
                        lambda mid: mid != "nou")
    disc.run_foundation_data_layer_for_discovered_matches(
        [_meci("tinta"), _meci("nou"), _meci("vechi")], force_mids={"tinta"},
    )
    assert set(fara_retea) == {"tinta", "nou"}
    assert "vechi" not in fara_retea


# ════════════════════════════════════════════════════════════════════════
# 4. Planul de recuperare și plafonul pe tranșă
# ════════════════════════════════════════════════════════════════════════

def test_planul_restrange_lista_la_tinte_si_respecta_plafonul(monkeypatch):
    monkeypatch.setattr(
        "database.queries.get_flashscore_mids_missing_statistics",
        lambda days_back: {"a", "b", "c"},
    )
    meciuri = [_meci(m) for m in ("a", "x", "b", "y", "c")]
    force, restranse, plan = cli._plan_recuperare(meciuri, max_recover=2, days_back=60)
    assert [m.mid for m in restranse] == ["a", "b"], "ordinea hub-ului se păstrează"
    assert force == {"a", "b"}
    assert plan == {"in_restanta": 3, "gasite_pe_hub": 3, "de_recuperat_acum": 2}


def test_plafon_zero_inseamna_fara_plafon(monkeypatch):
    monkeypatch.setattr(
        "database.queries.get_flashscore_mids_missing_statistics",
        lambda days_back: {"a", "b"},
    )
    force, restranse, _ = cli._plan_recuperare([_meci("a"), _meci("b")],
                                               max_recover=0, days_back=60)
    assert force == {"a", "b"} and len(restranse) == 2


def test_restanta_negasita_pe_hub_nu_produce_nicio_cerere(monkeypatch):
    monkeypatch.setattr(
        "database.queries.get_flashscore_mids_missing_statistics",
        lambda days_back: {"lipsa"},
    )
    force, restranse, plan = cli._plan_recuperare([_meci("altul")], 50, 60)
    assert restranse == [] and force == set()
    assert plan["in_restanta"] == 1 and plan["gasite_pe_hub"] == 0


def test_cli_refuza_combinatia_contradictorie():
    """`--recover-missing-stats` lucrează pe meciuri TERMINATE;
    `--future-fixtures-only` cere doar viitoare. Fără gardă, prima ar fi
    silențios inutilă."""
    import subprocess
    import sys

    r = subprocess.run(
        [sys.executable, "-m", "providers.flashscore.run_foundation_data_layer",
         "--recover-missing-stats", "--future-fixtures-only"],
        capture_output=True, text=True,
    )
    assert r.returncode != 0
    assert "exclud reciproc" in (r.stderr + r.stdout)


def test_workflow_expune_recuperarea():
    """Fără cablarea în workflow, modul ar exista doar în CLI — adică
    inaccesibil în practică (clasa de defect ADR-066: cod bun, fir netăiat)."""
    import pathlib

    text = pathlib.Path(".github/workflows/flashscore_foundation_data_layer.yml").read_text()
    assert "recover_missing_stats" in text
    assert "--recover-missing-stats" in text
    assert "--max-recover" in text
    # [ADĂUGAT 2026-10-19] `--recover-days-back` exista în CLI de la început,
    # dar NU era expus în workflow — deci fereastra de recuperare era blocată
    # la 60 de zile și meciurile din iulie/prima parte a lui august nu intrau
    # NICIODATĂ în listă. Ieșit la iveală dintr-o obiecție a proprietarului
    # produsului („100% nu sunt"), nu dintr-un test: ligi cu fereastra de 5
    # meciuri plină aveau totuși zeci de meciuri de sezon fără statistici.
    # Un parametru care există în cod dar nu poate fi cerut e cod mort.
    assert "recover_days_back" in text, "intrarea de workflow lipsește"
    assert "--recover-days-back" in text, "parametrul nu e pasat CLI-ului"
