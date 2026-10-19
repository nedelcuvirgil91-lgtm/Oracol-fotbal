"""
Faza 0 din ADR-078 — captarea identitatii de echipa a lui Flashscore.

Ce apara testele de aici, in ordinea importantei:

  1. **Orientarea gazda/oaspete nu se slabeste.** Identitatea se citeste din
     ACELEASI containere semantice ca numele (`duelParticipant__home/away`).
     Un link luat de oriunde din pagina ar putea aparea de partea greselita si
     ar reintroduce inversarea de teren reparata pe 2026-08-23.
  2. **Faza 0 nu poate strica Flashscore ca prima linie.** Captarea sta in
     AFARA lui `steps`, deci in afara lui `ok` — fiindca
     `run_foundation_data_layer.py` intoarce exit code 1 la orice esec partial.
  3. **Eticheta se scrie BRUTA.** Normalizata, cele doua forme ale aceluiasi
     club ar colapsa in una si tabela ar ascunde exact fenomenul pentru care
     exista.
  4. **Flagul porneste oprit** (North Star #3).

Zero retea, zero Supabase: HTML construit local, plus HTML-ul REAL salvat in
`docs/06_UDAL/poc_evidence/` (citit de pe disc, niciodata descarcat).
"""
from __future__ import annotations

import ast
import glob
import inspect
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

import database.queries as q
from providers.flashscore.normalizer import (
    _extract_team_identities,
    _extract_team_names,
    normalize_team_identities,
)

REPO = Path(__file__).resolve().parent.parent


def pagina(*, gazda="Gazda FC", oaspete="Oaspete FC",
           href_gazda="/team/gazda-fc/AAAA1111/",
           href_oaspete="/team/oaspete-fc/BBBB2222/",
           mid="MID12345") -> str:
    def latura(cls, nume, href):
        link = f'<a href="{href}">x</a>' if href else ""
        nume_el = (f'<div class="participant__participantName '
                   f'participant__overflow">{nume}</div>') if nume is not None else ""
        return f'<div class="{cls}">{link}{nume_el}</div>'
    # Formatul REAL al `og:url`, copiat din dovada salvata — contine `?mid=`.
    # Observatie care conteaza: URL-ul acela poarta si id-urile echipelor
    # (`fc-botosani-GjY1JjUS/rapid-bucuresti-YFCpigVG`), deci ar fi o a doua
    # sursa posibila. NU se foloseste: atribuirea pe laturi ar veni din ORDINEA
    # din URL, exact mecanismul inversarii de teren reparate pe 2026-08-23.
    og = (f'<meta property="og:url" content="https://www.flashscore.com/match/'
          f'football/gazda-fc-AAAA1111/oaspete-fc-BBBB2222/?mid={mid}">') if mid else ""
    return ("<html><head>" + og + "</head><body>"
            + latura("duelParticipant__home", gazda, href_gazda)
            + latura("duelParticipant__away", oaspete, href_oaspete)
            + "</body></html>")


# ── Extragerea ───────────────────────────────────────────────────────────────

def test_extrage_id_slug_si_eticheta_pe_fiecare_latura():
    g, o = _extract_team_identities(BeautifulSoup(pagina(), "html.parser"))
    assert g == {"flashscore_team_id": "AAAA1111", "team_slug": "gazda-fc",
                 "display_name": "Gazda FC"}
    assert o == {"flashscore_team_id": "BBBB2222", "team_slug": "oaspete-fc",
                 "display_name": "Oaspete FC"}


def test_eticheta_cu_sufix_de_tara_se_pastreaza_BRUTA():
    """Nucleul Fazei 0: `Levski Sofia (BUL)` se scrie exact asa. Normalizata,
    ar deveni `Levski Sofia` si tabela ar raporta mereu „un id, un nume"."""
    g, _ = _extract_team_identities(BeautifulSoup(
        pagina(gazda="Levski Sofia (BUL)", href_gazda="/team/levski-sofia/ABC12345/"),
        "html.parser"))
    assert g["display_name"] == "Levski Sofia (BUL)"
    assert g["flashscore_team_id"] == "ABC12345"


def test_container_absent_da_None_nu_ghicit():
    html = pagina().replace('class="duelParticipant__away"', 'class="altceva"')
    g, o = _extract_team_identities(BeautifulSoup(html, "html.parser"))
    assert g is not None and o is None


def test_link_absent_da_None_nu_ghicit():
    g, o = _extract_team_identities(BeautifulSoup(
        pagina(href_oaspete=None), "html.parser"))
    assert g is not None and o is None


def test_nume_gol_in_container_prezent_da_None():
    """Structura inteleasa dar numele lipsa: randul n-ar spune nimic despre
    maparea id -> nume, deci nu se scrie (Regula #8)."""
    g, _ = _extract_team_identities(BeautifulSoup(
        pagina(gazda=""), "html.parser"))
    assert g is None


def test_link_care_nu_e_de_echipa_e_ignorat():
    html = pagina(href_gazda="/news/some-article/XYZ/")
    g, _ = _extract_team_identities(BeautifulSoup(html, "html.parser"))
    assert g is None


def test_identitatea_nu_se_ia_din_afara_containerului_semantic():
    """GARDA DE ORIENTARE. Un link de echipa plantat in afara containerelor
    nu are voie sa devina identitate — altfel s-ar putea atribui laturii
    greselite, exact clasa inversarii de teren din 23 august."""
    html = pagina(href_gazda=None, href_oaspete=None).replace(
        "</body>", '<a href="/team/strain/ZZZZ9999/">x</a></body>')
    g, o = _extract_team_identities(BeautifulSoup(html, "html.parser"))
    assert g is None and o is None


def test_extragerea_numelor_ramane_neatinsa_de_identitate():
    """`_extract_team_names()` nu depinde in niciun fel de functia noua:
    fara niciun link, numele si orientarea ies identic."""
    html = pagina(href_gazda=None, href_oaspete=None)
    assert _extract_team_names(BeautifulSoup(html, "html.parser")) == ("Gazda FC", "Oaspete FC")


# ── normalize_team_identities ────────────────────────────────────────────────

def test_randurile_poarta_latura_si_fixture_id():
    randuri = normalize_team_identities({"summary": pagina()})
    assert [r["side"] for r in randuri] == ["home", "away"]
    assert {r["observed_fixture_id"] for r in randuri} == {"flashscore_MID12345"}


def test_fara_pagini_nu_arunca_si_nu_inventeaza():
    assert normalize_team_identities({}) == []
    assert normalize_team_identities({"odds": "<html></html>"}) == []


def test_fara_mid_fixture_id_ramane_None_nu_fabricat():
    randuri = normalize_team_identities({"summary": pagina(mid=None)})
    assert randuri and all(r["observed_fixture_id"] is None for r in randuri)


def test_pe_HTML_REAL_salvat_din_repo():
    """Pe dovada reala: pagini domestice (fara sufix) si o calificare UCL (cu
    sufix). Citit de pe disc, niciodata descarcat."""
    fisiere = sorted(glob.glob(str(REPO / "docs/06_UDAL/poc_evidence/"
                                   "flashscore_10matches/*__summary.html")))
    assert fisiere, "dovada HTML lipseste din repo"
    vazute: dict[str, set[str]] = {}
    for f in fisiere:
        randuri = normalize_team_identities(
            {"summary": Path(f).read_text(encoding="utf-8", errors="replace")})
        assert len(randuri) == 2, f"{Path(f).name}: {len(randuri)} randuri"
        for r in randuri:
            assert r["flashscore_team_id"] and r["team_slug"] and r["display_name"]
            vazute.setdefault(r["flashscore_team_id"], set()).add(r["display_name"])
    # Cel putin un nume cu sufix de tara (paginile de calificare) si cel putin
    # unul fara (paginile domestice) — altfel testul n-ar acoperi ambele cazuri.
    toate = {n for nume in vazute.values() for n in nume}
    assert any(n.endswith(")") for n in toate), toate
    assert any(not n.endswith(")") for n in toate), toate


# ── Scrierea ─────────────────────────────────────────────────────────────────

class _Tabela:
    def __init__(self, jurnal): self.jurnal = jurnal
    def upsert(self, payload, on_conflict=None):
        self.jurnal.append(("upsert", payload, on_conflict)); return self
    def execute(self): return type("R", (), {"data": []})()


class _Client:
    def __init__(self): self.jurnal = []
    def table(self, nume):
        self.jurnal.append(("table", nume)); return _Tabela(self.jurnal)


@pytest.fixture
def client_fals(monkeypatch):
    c = _Client()
    monkeypatch.setattr(q, "get_client", lambda: c)
    return c


def test_scrierea_pune_mereu_last_seen_at_si_niciodata_first_seen_at(client_fals):
    """Capcana timestamp-ului inghetat, in ambele direcții: `last_seen_at`
    TREBUIE scris (altfel ingheata pe `DO UPDATE`), `first_seen_at` NU are voie
    sa fie scris (altfel „prima observare" se rescrie la fiecare revedere)."""
    assert q.upsert_team_identity([
        {"flashscore_team_id": "A1", "display_name": "X (BUL)",
         "team_slug": "x", "observed_fixture_id": "flashscore_m1", "side": "home"},
    ]) is True
    (_, payload, on_conflict), = [j for j in client_fals.jurnal if j[0] == "upsert"]
    assert on_conflict == "flashscore_team_id,display_name"
    assert payload[0]["last_seen_at"]
    assert "first_seen_at" not in payload[0]


def test_scrierea_nu_normalizeaza_eticheta(client_fals):
    q.upsert_team_identity([{"flashscore_team_id": "A1",
                             "display_name": "Din. Zagreb (CRO)"}])
    (_, payload, _), = [j for j in client_fals.jurnal if j[0] == "upsert"]
    assert payload[0]["display_name"] == "Din. Zagreb (CRO)", (
        "eticheta trebuie sa rămână BRUTA — normalizata, cele doua forme ale "
        "aceluiasi club ar colapsa si tabela ar ascunde driftul")


def test_randurile_incomplete_sunt_sarite_nu_completate(client_fals):
    assert q.upsert_team_identity([
        {"flashscore_team_id": "A1", "display_name": "Bun"},
        {"flashscore_team_id": None, "display_name": "Fara id"},
        {"flashscore_team_id": "A2", "display_name": None},
    ]) is True
    (_, payload, _), = [j for j in client_fals.jurnal if j[0] == "upsert"]
    assert [p["display_name"] for p in payload] == ["Bun"]


def test_fara_randuri_sau_fara_client_nu_arunca(monkeypatch):
    assert q.upsert_team_identity([]) is True
    monkeypatch.setattr(q, "get_client", lambda: None)
    assert q.upsert_team_identity([{"flashscore_team_id": "A", "display_name": "B"}]) is False


# ── Detectia driftului ───────────────────────────────────────────────────────

class _Citire:
    def __init__(self, randuri): self.randuri = randuri; self._cursor = 0
    def select(self, *a, **k): return self
    def gt(self, col, val): self._cursor = val; return self
    def order(self, *a, **k): return self
    def limit(self, n): self._n = n; return self
    def execute(self):
        rest = [r for r in self.randuri if r["id"] > self._cursor][:getattr(self, "_n", 1000)]
        return type("R", (), {"data": rest})()


def _instaleaza_citire(monkeypatch, randuri):
    client = type("C", (), {"table": lambda self, n: _Citire(randuri)})()
    monkeypatch.setattr(q, "get_client", lambda: client)


def test_driftul_raporteaza_doar_id_urile_cu_mai_multe_nume(monkeypatch):
    _instaleaza_citire(monkeypatch, [
        {"id": 1, "flashscore_team_id": "A1", "display_name": "Levski Sofia",
         "team_slug": "levski-sofia", "last_seen_at": "x"},
        {"id": 2, "flashscore_team_id": "A1", "display_name": "Levski Sofia (BUL)",
         "team_slug": "levski-sofia", "last_seen_at": "x"},
        {"id": 3, "flashscore_team_id": "B2", "display_name": "FCSB",
         "team_slug": "fcsb", "last_seen_at": "x"},
    ])
    drift = q.get_team_identity_drift()
    assert [d["flashscore_team_id"] for d in drift] == ["A1"]
    assert drift[0]["nume"] == ["Levski Sofia", "Levski Sofia (BUL)"]


def test_un_id_cu_un_singur_nume_nu_e_drift(monkeypatch):
    _instaleaza_citire(monkeypatch, [
        {"id": 1, "flashscore_team_id": "B2", "display_name": "FCSB",
         "team_slug": "fcsb", "last_seen_at": "x"},
    ])
    assert q.get_team_identity_drift() == []


def test_citirea_e_paginata_si_nu_taie_la_1000(monkeypatch):
    """A sasea instanta a plafonului PostgREST ar fi aratat „niciun drift"."""
    randuri = [{"id": i, "flashscore_team_id": f"T{i}", "display_name": f"N{i}",
                "team_slug": None, "last_seen_at": "x"} for i in range(1, 2501)]
    randuri.append({"id": 2501, "flashscore_team_id": "T2500",
                    "display_name": "ALT NUME", "team_slug": None, "last_seen_at": "x"})
    _instaleaza_citire(monkeypatch, randuri)
    drift = q.get_team_identity_drift()
    assert [d["flashscore_team_id"] for d in drift] == ["T2500"], (
        "driftul de pe pagina a treia a fost ratat — plafonul PostgREST")


def test_eroarea_de_citire_da_lista_goala_nu_partial(monkeypatch):
    class _Boom:
        def table(self, n):
            class T:
                def select(s, *a, **k): return s
                def gt(s, *a): return s
                def order(s, *a, **k): return s
                def limit(s, *a): return s
                def execute(s): raise RuntimeError("boom")
            return T()
    monkeypatch.setattr(q, "get_client", lambda: _Boom())
    assert q.get_team_identity_drift() == []


# ── Garzi structurale ────────────────────────────────────────────────────────

def test_flagul_porneste_OPRIT():
    import flashscore_team_identity_config as cfg
    assert cfg._DEFAULT_CONFIG == {"flashscore_team_identity_capture_enabled": False}


def test_captarea_e_in_AFARA_lui_steps_deci_nu_poate_inrosi_rularea():
    """GARDA CARE PROTEJEAZA PRIMA LINIE. `ok = all(steps.values())`, iar
    `run_foundation_data_layer.py` intoarce exit code 1 la orice esec parțial.
    O observatie care nu schimba nicio predictie nu are voie sa inroseasca
    rularea care aduce datele reale.

    Verificat pe AST, nu pe text: un comentariu care explica regula ar face
    garda sa-si citeasca propria explicatie (clasa deja intalnita de patru ori
    in acest proiect)."""
    import providers.flashscore.persistence as pers

    arbore = ast.parse(inspect.getsource(pers.persist_match_foundation_data))
    atribuiri_steps: list[str] = []
    for nod in ast.walk(arbore):
        if isinstance(nod, ast.Subscript) and isinstance(nod.value, ast.Name) \
                and nod.value.id == "steps" and isinstance(nod.ctx, ast.Store):
            if isinstance(nod.slice, ast.Constant):
                atribuiri_steps.append(str(nod.slice.value))
    assert atribuiri_steps, "garda ar trece vida — nu s-a gasit nicio cheie `steps`"
    assert not [k for k in atribuiri_steps if "identity" in k], (
        f"captarea identitatii a intrat in `steps` ({atribuiri_steps}) — "
        "un esec al ei ar inrosi toata rularea Flashscore")


def test_captarea_e_gatata_de_flag_in_persistenta():
    """Fara poarta, codul ar scrie de la primul merge, inainte de orice
    decizie (North Star #3)."""
    sursa = inspect.getsource(
        __import__("providers.flashscore.persistence", fromlist=["x"])
        .persist_match_foundation_data)
    arbore = ast.parse(sursa)
    nume = {n.id for n in ast.walk(arbore) if isinstance(n, ast.Name)}
    assert "_identitate_pornita" in nume or "is_enabled" in nume, (
        "captarea nu citeste niciun flag — ar porni implicit activa")


def test_identitatea_nu_intra_in_payload_canonic():
    """`normalize_match_statistics()` nu are voie sa capete chei de identitate:
    payload-ul care scrie in `match_history` rămâne neatins in Faza 0."""
    from providers.flashscore.normalizer import normalize_match_statistics

    base = normalize_match_statistics({"summary": pagina(), "stats": pagina()})
    assert not [k for k in base if "flashscore_team_id" in k or "team_slug" in k], (
        f"chei de identitate in payload-ul canonic: {sorted(base)}")
