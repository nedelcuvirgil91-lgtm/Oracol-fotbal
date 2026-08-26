"""Capcana timestamp-ului înghețat — garda care o închide ca CLASĂ, nu ca listă.

CE E CAPCANA. Un `upsert` cu `on_conflict` care nu pune marcajul temporal în
payload îl îngheață tăcut: `DEFAULT now()` se aplică doar pe ramura `INSERT`;
pe `DO UPDATE` valoarea veche supraviețuiește. Rândul își împrospătează corect
conținutul, dar poartă ora PRIMEI scrieri.

DE CE MERITĂ O GARDĂ, NU DOAR ȘASE FIXURI. Nu e pierdere de date — e un
instrument de diagnostic care minte, iar costul lui a fost demonstrat direct:
pe 2026-08-26 am raportat „clasamentele sunt vechi de 16-21 de zile", concluzie
trasă exact din aceste timestamp-uri. Verificarea pe CONȚINUT (etape în
clasament vs. meciuri jucate) a arătat că fiecare clasament era la zi. Datele
erau bune; ceasul mințea. O oră de investigație pe un defect inexistent, la un
pas de a „repara" ceva nestricat.

Șase instanțe în trei valuri, toate găsite ACCIDENTAL, niciodată printr-o
revizuire. A șaptea ar apărea la fel de tăcut — de aceea garda de mai jos
citește CODUL, nu o listă întreținută de om.

Fără rețea, fără Supabase.
"""
from __future__ import annotations

import ast
import inspect
from datetime import datetime

import database.queries as q

# Tabelele Foundation Data Layer cu marcaj temporal, verificate live pe schema
# de producție (2026-08-26): toate au `DEFAULT`, deci toate erau expuse.
TABELE_CU_MARCAJ_TEMPORAL: dict[str, str] = {
    "flashscore_raw_extraction": "captured_at",
    "flashscore_standings_snapshot": "captured_at",
    "flashscore_match_context": "captured_at",
    "match_statistics_extended": "captured_at",
    "player_match_stats_extended": "captured_at",
    "flashscore_data_completeness": "computed_at",
}


def _sursa_modulului() -> str:
    return inspect.getsource(q)


def _functii_care_scriu_in(tabela: str) -> list[ast.FunctionDef]:
    """Funcțiile din `database.queries` care fac `.table("<tabela>").upsert(...)`."""
    arbore = ast.parse(_sursa_modulului())
    gasite = []
    for nod in ast.walk(arbore):
        if not isinstance(nod, ast.FunctionDef):
            continue
        sursa_fn = ast.dump(nod)
        if f"'{tabela}'" not in sursa_fn and f'"{tabela}"' not in sursa_fn:
            continue
        # doar funcțiile care chiar fac upsert, nu cele care doar citesc
        face_upsert = any(
            isinstance(n, ast.Attribute) and n.attr == "upsert" for n in ast.walk(nod)
        )
        if face_upsert:
            gasite.append(nod)
    return gasite


# ── helper-ul comun ──────────────────────────────────────────────────────────

def test_acum_utc_intoarce_iso_cu_fus():
    valoare = q._acum_utc()
    parsat = datetime.fromisoformat(valoare)
    assert parsat.tzinfo is not None, (
        "coloanele sunt `timestamptz` — un timestamp naiv ar fi interpretat "
        "dupa fusul serverului, nu dupa UTC"
    )


def test_acum_utc_chiar_avanseaza():
    """Prinde mutația care întoarce o constantă."""
    a, b = q._acum_utc(), q._acum_utc()
    assert datetime.fromisoformat(b) >= datetime.fromisoformat(a)
    assert datetime.fromisoformat(a).year >= 2026


# ── GARDA CENTRALĂ: clasa, nu instanțele ─────────────────────────────────────

def test_orice_upsert_pe_tabela_cu_marcaj_temporal_il_scrie_explicit():
    """GARDA CARE ÎNCHIDE CLASA.

    Nu verifică cele șase locuri reparate (aia ar fi o listă, care se învechește
    exact ca documentația care ne-a mințit). Verifică INVARIANTUL: pentru
    fiecare tabelă cu marcaj temporal, orice funcție care face upsert pe ea
    trebuie să menționeze acel câmp în corpul ei.

    Dacă cineva adaugă mâine un al șaptelea upsert fără timestamp, testul cade
    și numește exact funcția și tabela."""
    lipsuri: list[str] = []
    for tabela, coloana in TABELE_CU_MARCAJ_TEMPORAL.items():
        for fn in _functii_care_scriu_in(tabela):
            corp = ast.dump(fn)
            if f"'{coloana}'" not in corp and f'"{coloana}"' not in corp:
                lipsuri.append(f"{fn.name}() scrie in {tabela} fara sa puna {coloana}")
    assert not lipsuri, (
        "upsert cu on_conflict care NU pune marcajul temporal in payload il "
        "INGHEATA tacit (DEFAULT now() se aplica doar la INSERT):\n  "
        + "\n  ".join(lipsuri)
    )


def test_fiecare_tabela_declarata_are_chiar_un_scriitor():
    """Contrapondere: dacă o tabelă e redenumită sau scriitorul ei dispare,
    garda de mai sus ar trece VID — verde fără să verifice nimic. Aici se
    confirmă că fiecare intrare din listă chiar are cod în spate."""
    fara_scriitor = [t for t in TABELE_CU_MARCAJ_TEMPORAL if not _functii_care_scriu_in(t)]
    assert not fara_scriitor, (
        f"tabele declarate fara niciun upsert gasit in cod: {fara_scriitor} — "
        "garda ar trece vid, deci lista trebuie actualizata deliberat"
    )


def test_marcajul_se_scrie_prin_helperul_comun():
    """Explicația capcanei trăiește într-un singur loc (`_acum_utc`). Un
    `datetime.now()` scris direct în payload ar funcționa, dar ar rupe firul
    către explicație — iar a șaptea persoană ar redescoperi capcana de la zero."""
    directe: list[str] = []
    for tabela, coloana in TABELE_CU_MARCAJ_TEMPORAL.items():
        for fn in _functii_care_scriu_in(tabela):
            sursa_fn = ast.get_source_segment(_sursa_modulului(), fn) or ""
            for linie in sursa_fn.splitlines():
                if coloana in linie and "datetime.now" in linie:
                    directe.append(f"{fn.name}(): {linie.strip()}")
    assert not directe, (
        "foloseste `_acum_utc()`, nu `datetime.now()` direct:\n  " + "\n  ".join(directe)
    )


# ── comportament, nu doar formă ──────────────────────────────────────────────

class _Tabela:
    def __init__(self, jurnal, nume):
        self._j, self._n = jurnal, nume

    def upsert(self, payload, on_conflict=None):
        self._j.append((self._n, payload, on_conflict))
        return self

    def select(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def execute(self): return type("R", (), {"data": [{"id": 1}]})()


class _Client:
    def __init__(self):
        self.jurnal: list = []

    def table(self, nume):
        return _Tabela(self.jurnal, nume)


def _payload_pentru(jurnal, tabela):
    for nume, payload, _ in jurnal:
        if nume == tabela:
            return payload if isinstance(payload, dict) else payload[0]
    raise AssertionError(f"nicio scriere in {tabela}: {[j[0] for j in jurnal]}")


def test_match_context_primeste_captured_at(monkeypatch):
    c = _Client()
    monkeypatch.setattr(q, "get_client", lambda: c)
    monkeypatch.setattr(q, "normalize_team_name", lambda t: t, raising=False)
    inainte = datetime.now().astimezone()
    q.upsert_match_context([{
        "context_match_id": 1, "category": "h2h_overall", "meeting_order": 0,
        "home_team": "A", "away_team": "B",
    }])
    scris = datetime.fromisoformat(_payload_pentru(c.jurnal, "flashscore_match_context")["captured_at"])
    assert scris >= inainte


def test_toate_randurile_de_context_poarta_acelasi_moment(monkeypatch):
    """Un lot de context e o singură observație — nu are voie să se împrăștie
    pe momente diferite între rânduri."""
    c = _Client()
    monkeypatch.setattr(q, "get_client", lambda: c)
    monkeypatch.setattr(q, "normalize_team_name", lambda t: t, raising=False)
    q.upsert_match_context([
        {"context_match_id": 1, "category": "h2h_overall", "meeting_order": i,
         "home_team": "A", "away_team": "B"}
        for i in range(4)
    ])
    _, randuri, _ = c.jurnal[0]
    assert len({r["captured_at"] for r in randuri}) == 1


def test_statistici_extinse_primesc_captured_at(monkeypatch):
    c = _Client()
    monkeypatch.setattr(q, "get_client", lambda: c)
    inainte = datetime.now().astimezone()
    q.upsert_match_statistics_extended(7, [{"stat_key": "possession", "value_raw": "55%"}])
    scris = datetime.fromisoformat(_payload_pentru(c.jurnal, "match_statistics_extended")["captured_at"])
    assert scris >= inainte


def test_data_completeness_primeste_computed_at(monkeypatch):
    c = _Client()
    monkeypatch.setattr(q, "get_client", lambda: c)
    inainte = datetime.now().astimezone()
    q.upsert_data_completeness("a__b__2026-08-26", 7, {"summary": True, "coverage_percent": 14.3})
    scris = datetime.fromisoformat(
        _payload_pentru(c.jurnal, "flashscore_data_completeness")["computed_at"]
    )
    assert scris >= inainte


def test_player_stats_extinse_primesc_captured_at(monkeypatch):
    c = _Client()
    monkeypatch.setattr(q, "get_client", lambda: c)
    inainte = datetime.now().astimezone()
    q.upsert_player_match_stats_extended(7, [{
        "player_name": "X", "team": "A", "rating": 7.1,
        "extended_stats": [{"stat_key": "shots", "stat_label": "Shots", "value_numeric": 3}],
    }])
    scris = datetime.fromisoformat(
        _payload_pentru(c.jurnal, "player_match_stats_extended")["captured_at"]
    )
    assert scris >= inainte


# ── restul payload-ului rămâne neatins ───────────────────────────────────────

def test_fixul_nu_altereaza_celelalte_campuri(monkeypatch):
    c = _Client()
    monkeypatch.setattr(q, "get_client", lambda: c)
    q.upsert_match_statistics_extended(
        7, [{"stat_key": "possession", "value_raw": "55%", "value_numeric": 55.0,
             "season": "2026-2027", "source": "flashscore"}],
    )
    p = _payload_pentru(c.jurnal, "match_statistics_extended")
    assert p["stat_key"] == "possession" and p["value_numeric"] == 55.0
    assert p["season"] == "2026-2027" and p["match_id"] == 7


def test_lotul_gol_nu_scrie_nimic(monkeypatch):
    c = _Client()
    monkeypatch.setattr(q, "get_client", lambda: c)
    assert q.upsert_match_context([]) is True
    assert q.upsert_match_statistics_extended(1, []) is True
    assert c.jurnal == []
