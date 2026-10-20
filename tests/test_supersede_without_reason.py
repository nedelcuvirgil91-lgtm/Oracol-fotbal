"""Teste pentru `get_supersede_without_reason()` — clasa 9, ADR-075 §8.

Fara retea, fara Supabase live. Clientul fals APLICA efectiv filtrele si
`count="exact"`, fiindcă un fals care le ignora ar face testele sa treaca fara
sa dovedeasca nimic — lecția platita pe 14 octombrie, cand un fals care tai la
`limit` doar la apel explicit a lasat defectul original sa treaca garda.
"""
from __future__ import annotations

import database.queries as q


class _Rezultat:
    def __init__(self, data, count):
        self.data = data
        self.count = count


class _Interogare:
    """Aplica filtrele CHIAR, in ordinea in care sunt chemate."""

    def __init__(self, randuri: list[dict], arunca: bool = False):
        self._randuri = list(randuri)
        self._arunca = arunca
        self._coloane: list[str] = []
        self._count_cerut = False
        self._limita: int | None = None
        self.ordonat = False

    def select(self, coloane, count=None):
        self._coloane = [c.strip() for c in coloane.split(",")]
        self._count_cerut = (count == "exact")
        return self

    def not_(self):  # pragma: no cover — inlocuit de proprietatea de mai jos
        raise AssertionError("nefolosit")

    @property
    def not_(self):  # type: ignore[no-redef]
        return _Negat(self)

    def is_(self, coloana, valoare):
        assert valoare == "null"
        self._randuri = [r for r in self._randuri if r.get(coloana) is None]
        return self

    def order(self, coloana):
        self._randuri.sort(key=lambda r: r[coloana])
        self.ordonat = True
        return self

    def limit(self, n):
        self._limita = n
        return self

    def execute(self):
        if self._arunca:
            raise RuntimeError("PostgREST indisponibil")
        total = len(self._randuri)
        pagina = self._randuri[: self._limita] if self._limita else self._randuri
        # Proiectie pe coloanele cerute — ca un `select` real sa nu intoarca
        # mai mult decat s-a cerut, si ca testele sa nu se sprijine pe coloane
        # pe care productia nu le citeste.
        proiectat = [{c: r.get(c) for c in self._coloane} for r in pagina]
        return _Rezultat(proiectat, total if self._count_cerut else None)


class _Negat:
    def __init__(self, interogare: _Interogare):
        self._i = interogare

    def is_(self, coloana, valoare):
        assert valoare == "null"
        self._i._randuri = [r for r in self._i._randuri
                            if r.get(coloana) is not None]
        return self._i


class _Client:
    def __init__(self, randuri, arunca=False):
        self._randuri = randuri
        self._arunca = arunca
        self.ultima: _Interogare | None = None

    def table(self, nume):
        assert nume == "match_history"
        self.ultima = _Interogare(self._randuri, arunca=self._arunca)
        return self.ultima


def _rand(id_, superseded_by=None, superseded_reason=None, superseded_at=None):
    return {"id": id_, "fixture_id": f"fx_{id_}", "home_team": "A",
            "away_team": "B", "kickoff_date": "2026-10-09",
            "superseded_by": superseded_by, "superseded_reason": superseded_reason,
            "superseded_at": superseded_at}


def _cu_client(monkeypatch, client):
    monkeypatch.setattr(q, "get_client", lambda: client)


def test_randul_fara_motiv_e_gasit(monkeypatch):
    """Cazul real ADR-075: superseded_by setat, motiv si marcaj NULL."""
    client = _Client([_rand(1, superseded_by=99)])
    _cu_client(monkeypatch, client)
    total, exemple = q.get_supersede_without_reason()
    assert total == 1
    assert exemple[0]["id"] == 1
    assert exemple[0]["superseded_by"] == 99


def test_randul_cu_motiv_NU_e_raportat(monkeypatch):
    """Cele 6738 de randuri supersedate corect nu trebuie sa apara."""
    client = _Client([_rand(1, superseded_by=99, superseded_reason="reschedule",
                            superseded_at="2026-08-23T00:00:00Z")])
    _cu_client(monkeypatch, client)
    assert q.get_supersede_without_reason() == (0, [])


def test_randul_live_NU_e_raportat(monkeypatch):
    """Un rand care nu e supersedat deloc nu are ce motiv sa dea."""
    client = _Client([_rand(1)])
    _cu_client(monkeypatch, client)
    assert q.get_supersede_without_reason() == (0, [])


def test_amesteca_corect(monkeypatch):
    """Garda centrala: separa cele trei stari pe un set mixt."""
    client = _Client([
        _rand(1, superseded_by=10),                                    # fara motiv
        _rand(2, superseded_by=11, superseded_reason="reschedule"),     # corect
        _rand(3),                                                      # live
        _rand(4, superseded_by=12),                                    # fara motiv
    ])
    _cu_client(monkeypatch, client)
    total, exemple = q.get_supersede_without_reason()
    assert total == 2
    assert [e["id"] for e in exemple] == [1, 4]


def test_totalul_vine_din_count_nu_din_lungimea_paginii(monkeypatch):
    """Esențial: cu 50 de randuri si 15 exemple, totalul trebuie sa fie 50.

    Daca totalul s-ar lua din `len(data)`, raportul ar spune „15" la orice
    amploare — exact clasa de plafon implicit reparata de cinci ori in proiect."""
    client = _Client([_rand(i, superseded_by=1000 + i) for i in range(1, 51)])
    _cu_client(monkeypatch, client)
    total, exemple = q.get_supersede_without_reason(limit_examples=15)
    assert total == 50
    assert len(exemple) == 15


def test_eroarea_intoarce_NECUNOSCUT_nu_zero(monkeypatch):
    """Regula #8. Un `(0, [])` pe eroare ar arata identic cu starea sanatoasa,
    iar monitorul ar raporta verde exact cand nu stie nimic."""
    client = _Client([_rand(1, superseded_by=10)], arunca=True)
    _cu_client(monkeypatch, client)
    assert q.get_supersede_without_reason() == (None, [])


def test_lipsa_clientului_intoarce_NECUNOSCUT(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: None)
    assert q.get_supersede_without_reason() == (None, [])


def test_ordonare_explicita_cerut(monkeypatch):
    """Fara `ORDER BY`, ce exemple se vad se poate schimba singur de la o zi la
    alta — tiparul deja documentat la `get_shadow_predictions()`."""
    client = _Client([_rand(5, superseded_by=1), _rand(2, superseded_by=1)])
    _cu_client(monkeypatch, client)
    total, exemple = q.get_supersede_without_reason()
    assert client.ultima is not None and client.ultima.ordonat
    assert [e["id"] for e in exemple] == [2, 5]


def test_limita_minima_de_un_exemplu(monkeypatch):
    """`limit(0)` e invalid in PostgREST; functia il ridica la 1."""
    client = _Client([_rand(1, superseded_by=10)])
    _cu_client(monkeypatch, client)
    total, exemple = q.get_supersede_without_reason(limit_examples=0)
    assert total == 1 and len(exemple) == 1
