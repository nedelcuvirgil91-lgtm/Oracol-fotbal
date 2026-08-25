"""Doua defecte gasite DUPA cablarea ADR-066 P2b, pe date reale de productie.

DEFECTUL 1 — sezonul meciului-SUBIECT scris pe randuri care descriu ALTE meciuri.
`persistence.py` punea `row["season"] = season` pe randurile de context (H2H +
forma recenta). Acele randuri descriu confruntari directe, adesea din alte
competitii SI din alte sezoane. Bugul exista de la migratia 038, dar era
INVIZIBIL cat timp `season` era mereu None — cablarea i-a dat prima data o
valoare si l-a activat.

Masurat live: din 210 randuri etichetate, 55 descriau confruntari din alte
sezoane, cea mai veche din 2022-07-02, etichetata „2026-2027".

Conteaza fiindca `season_cleanup.py` foloseste `season` ca sa decida ce s-ar
sterge la retentie (azi strict dry-run — deci nicio paguba, dar eticheta
gresita ar taia randurile gresite daca stergerea s-ar activa).

DEFECTUL 2 — `captured_at` inghetat la prima inserare.
Randul de clasament e un snapshot CURENT, actualizat in loc, dar `captured_at`
ramanea la data primei inserari A ACELEI ECHIPE. Rezultat masurat: sezonul
fragmentat in interiorul aceleiasi competitii (Serie A 1 rand din 20 cu sezon,
Premier League 9 din 21) — un clasament are un singur sezon.

Fara retea, fara Supabase.
"""
from __future__ import annotations

import ast
import inspect
from datetime import datetime, timezone

import database.queries as q


# ── Defectul 1: contextul nu mai mosteneste sezonul subiectului ─────────────

def test_contextul_nu_mai_primeste_sezonul_meciului_subiect():
    """GARDA. Verificare la nivel de AST fiindca `persist_match_foundation_data`
    cere pagini HTML reale si Supabase. Ce conteaza e ca bucla de atribuire sa
    NU existe intre `normalize_match_context()` si `upsert_match_context()`."""
    from providers.flashscore import persistence

    sursa = inspect.getsource(persistence.persist_match_foundation_data)
    arbore = ast.parse(sursa.strip())

    atribuiri_de_sezon = [
        n for n in ast.walk(arbore)
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Subscript)
                and isinstance(t.slice, ast.Constant) and t.slice.value == "season"
                for t in n.targets)
    ]
    # Ramane exact UNA: cea pentru `base` (match_history), care e corecta —
    # acolo sezonul chiar descrie meciul. Plus cele pentru standings/statistici.
    tinte = {
        t.value.id for n in atribuiri_de_sezon for t in n.targets
        if isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name)
    }
    assert "base" in tinte, "sezonul TREBUIE sa ajunga pe match_history"

    # `context_rows` nu are voie sa fie printre tinte — nici direct, nici prin
    # variabila de bucla `row` intr-un `for row in context_rows`.
    for bucla in [n for n in ast.walk(arbore) if isinstance(n, ast.For)]:
        iterabil = getattr(bucla.iter, "id", None)
        if iterabil != "context_rows":
            continue
        scrie_sezon = any(
            isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant)
                    and t.slice.value == "season" for t in n.targets)
            for n in ast.walk(bucla)
        )
        assert not scrie_sezon, (
            "randurile de context descriu ALTE meciuri — sezonul meciului-subiect "
            "nu le descrie (55 din 210 erau provabil gresite, pana in 2022)"
        )


def test_standings_pastreaza_sezonul():
    """Contrapondere: fixul nu are voie sa taie si scrierea CORECTA. Clasamentul
    apartine chiar competitiei si sezonului meciului curent."""
    from providers.flashscore import persistence

    sursa = inspect.getsource(persistence.persist_match_foundation_data)
    arbore = ast.parse(sursa.strip())
    bucle_standings = [
        n for n in ast.walk(arbore)
        if isinstance(n, ast.For) and getattr(n.iter, "id", None) == "standings_rows"
    ]
    assert bucle_standings, "bucla peste standings_rows a disparut"
    assert any(
        isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant)
                and t.slice.value == "season" for t in n.targets)
        for b in bucle_standings for n in ast.walk(b)
    ), "clasamentul trebuie sa pastreze sezonul"


# ── Defectul 2: captured_at reimprospatat ───────────────────────────────────

class _Rezultat:
    data: list = []


class _Tabela:
    def __init__(self, jurnal): self._j = jurnal
    def upsert(self, rows, on_conflict=None):
        self._j.append((rows, on_conflict)); return self
    def execute(self): return _Rezultat()


class _Client:
    def __init__(self): self.jurnal: list = []
    def table(self, nume): return _Tabela(self.jurnal)


def test_captured_at_e_rescris_la_fiecare_upsert(monkeypatch):
    """GARDA CENTRALA. Fara asta, `captured_at` spune cand a fost vazuta prima
    oara echipa, nu ce descriu cifrele — iar cifrele sunt mereu de acum."""
    c = _Client()
    monkeypatch.setattr(q, "get_client", lambda: c)
    monkeypatch.setattr(q, "normalize_team_name", lambda t: t, raising=False)

    inainte = datetime.now(timezone.utc)
    q.upsert_standings_snapshot([
        {"competition": "Serie A", "team": "Inter", "played": 1,
         "captured_at": "2026-07-31T00:00:00+00:00"},
    ])
    randuri, conflict = c.jurnal[0]
    assert conflict == "competition,team"
    scris = datetime.fromisoformat(randuri[0]["captured_at"])
    assert scris >= inainte, (
        f"captured_at nu a fost reimprospatat: {randuri[0]['captured_at']}"
    )


def test_restul_campurilor_raman_neatinse(monkeypatch):
    c = _Client()
    monkeypatch.setattr(q, "get_client", lambda: c)
    monkeypatch.setattr(q, "normalize_team_name", lambda t: t, raising=False)

    q.upsert_standings_snapshot([
        {"competition": "Serie A", "team": "Inter", "played": 1,
         "points": 3, "season": "2026-2027"},
    ])
    randuri, _ = c.jurnal[0]
    assert randuri[0]["played"] == 1
    assert randuri[0]["points"] == 3
    assert randuri[0]["season"] == "2026-2027"
    assert randuri[0]["competition"] == "Serie A"


def test_toate_randurile_primesc_acelasi_moment(monkeypatch):
    """Un clasament e o singura observatie — nu are voie sa se imprastie pe
    momente diferite intre echipe, exact fragmentarea care a cauzat problema."""
    c = _Client()
    monkeypatch.setattr(q, "get_client", lambda: c)
    monkeypatch.setattr(q, "normalize_team_name", lambda t: t, raising=False)

    q.upsert_standings_snapshot([
        {"competition": "Serie A", "team": t, "played": 1} for t in ("Inter", "Milan", "Roma")
    ])
    randuri, _ = c.jurnal[0]
    assert len({r["captured_at"] for r in randuri}) == 1


def test_lista_goala_nu_scrie_nimic(monkeypatch):
    c = _Client()
    monkeypatch.setattr(q, "get_client", lambda: c)
    assert q.upsert_standings_snapshot([]) is True
    assert c.jurnal == []
