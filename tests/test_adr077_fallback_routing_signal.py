"""ADR-077 — criteriul de rutare către providerii de rezervă citește coloana
ȚINTĂ, nu un câmp-martor.

DEFECTUL. `sync/sync_match_statistics.py` cerea meciurile cu
`require_referee=True`, adică `referee IS NULL`. Era corect la ADR-041, când
Soccer Football Info era SINGURUL scriitor al câmpului. ADR-044/045 a adus
Flashscore ca **al doilea scriitor** (`providers/flashscore/normalizer.py:533`)
și nimeni n-a revizitat proxy-ul.

Măsurat pe producție, 19 oct: criteriul întorcea **0 meciuri pe orice
fereastră** (7/14/60 zile) în timp ce **95/229/653** aveau statistici lipsă.
Plasa de siguranță era cablată și nu se putea declanșa niciodată — de aceea
pana de 39 de zile a extragerii Flashscore (ADR-076) a trecut neobservată:
arbitrul continua să fie scris impecabil.

PROPRIETATEA APĂRATĂ, și e motivul variantei (ii): **o coloană-țintă nu poate
minți despre propria absență.** Un martor poate oricând căpăta al doilea
scriitor. De aceea testele de mai jos nu verifică „se citește `referee`" vs.
„se citește altceva" — verifică faptul structural că filtrul cade pe coloana pe
care sincronizarea chiar vrea să o completeze.

Modul vechi rămâne NESCHIMBAT: contractul funcției e public, iar azi n-are alt
apelant — dar „n-are apelant azi" nu e un motiv să-l rupi tăcut.

Fără rețea, fără Supabase.
"""
from __future__ import annotations

import database.queries as q


# ── client fals care înregistrează filtrele aplicate ──────────────────────

class _Query:
    def __init__(self, jurnal: list[tuple[str, str]]):
        self.jurnal = jurnal
        self.coloane: str | None = None
        self.limita: int | None = None
        self.bucati: list[list] = []

    def select(self, cols):
        self.coloane = cols
        return self

    def is_(self, col, val):
        self.jurnal.append((col, val))
        return self

    def not_(self):  # pragma: no cover - înlocuit mai jos
        return self

    def gte(self, *_a):
        return self

    def lte(self, *_a):
        return self

    def eq(self, col, val):
        self.jurnal.append((f"eq:{col}", str(val)))
        return self

    def in_(self, _col, vals):
        self.bucati.append(list(vals))
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, n):
        self.limita = n
        return self

    def execute(self):
        class _R:
            data: list = []
        return _R()


class _QueryCuNot(_Query):
    """`not_.is_(...)` e un lanț cu DOUĂ puncte în codul real."""

    @property
    def not_(self):
        parinte = self

        class _Not:
            def is_(self, col, val):
                parinte.jurnal.append((f"not:{col}", val))
                return parinte
        return _Not()


class _Client:
    def __init__(self):
        self.jurnal: list[tuple[str, str]] = []
        self.ultima: _QueryCuNot | None = None

    def table(self, _nume):
        self.ultima = _QueryCuNot(self.jurnal)
        return self.ultima


def _cu_client(monkeypatch):
    c = _Client()
    monkeypatch.setattr(q, "get_client", lambda: c)
    return c


# ── criteriul: coloana ȚINTĂ ───────────────────────────────────────────────

def test_target_missing_filtreaza_pe_home_shots():
    """Proprietatea centrală a ADR-077."""
    import pytest
    mp = pytest.MonkeyPatch()
    try:
        c = _cu_client(mp)
        q.get_finished_matches_missing_stats(target_missing=True)
        assert ("home_shots", "null") in c.jurnal
    finally:
        mp.undo()


def test_target_missing_NU_filtreaza_pe_referee():
    import pytest
    mp = pytest.MonkeyPatch()
    try:
        c = _cu_client(mp)
        q.get_finished_matches_missing_stats(target_missing=True)
        assert ("referee", "null") not in c.jurnal, (
            "criteriul a căzut pe câmpul-martor — exact defectul reparat"
        )
    finally:
        mp.undo()


def test_target_missing_NU_filtreaza_pe_home_possession():
    """`home_possession` dă aceleași cifre azi, dar e scopul îngust FreeLF —
    nu coloana-țintă a sincronizării bogate."""
    import pytest
    mp = pytest.MonkeyPatch()
    try:
        c = _cu_client(mp)
        q.get_finished_matches_missing_stats(target_missing=True)
        assert ("home_possession", "null") not in c.jurnal
    finally:
        mp.undo()


# ── modul vechi rămâne NESCHIMBAT (contract public) ───────────────────────

def test_require_referee_singur_pastreaza_comportamentul_vechi():
    import pytest
    mp = pytest.MonkeyPatch()
    try:
        c = _cu_client(mp)
        q.get_finished_matches_missing_stats(require_referee=True)
        assert ("referee", "null") in c.jurnal
        assert ("home_shots", "null") not in c.jurnal
    finally:
        mp.undo()


def test_modul_implicit_pastreaza_home_possession():
    import pytest
    mp = pytest.MonkeyPatch()
    try:
        c = _cu_client(mp)
        q.get_finished_matches_missing_stats()
        assert ("home_possession", "null") in c.jurnal
        assert ("home_shots", "null") not in c.jurnal
        assert ("referee", "null") not in c.jurnal
    finally:
        mp.undo()


def test_precedenta_target_missing_bate_require_referee():
    """Documentată explicit în docstring. A le pasa pe amândouă e o eroare de
    apelant; modul CORECT e cel aplicat, nu o excepție (funcția nu aruncă
    niciodată, prin contract)."""
    import pytest
    mp = pytest.MonkeyPatch()
    try:
        c = _cu_client(mp)
        q.get_finished_matches_missing_stats(require_referee=True, target_missing=True)
        assert ("home_shots", "null") in c.jurnal
        assert ("referee", "null") not in c.jurnal
    finally:
        mp.undo()


# ── apelantul de producție folosește modul NOU ────────────────────────────

def test_sync_match_statistics_cere_target_missing_nu_referee():
    """Gardă pe apelant, prin AST — nu pe text, fiindcă comentariul care
    explică reparația conține chiar șirul `require_referee`, iar o verificare
    textuală ar da fals pozitiv pe codul CORECT. Clasa `pipefail`, a șasea
    instanță în proiect."""
    import ast
    import pathlib

    sursa = (pathlib.Path(q.__file__).parent.parent
             / "sync" / "sync_match_statistics.py").read_text(encoding="utf-8")
    arbore = ast.parse(sursa)
    apeluri = [
        nod for nod in ast.walk(arbore)
        if isinstance(nod, ast.Call)
        and getattr(nod.func, "id", getattr(nod.func, "attr", "")) == "get_finished_matches_missing_stats"
    ]
    assert apeluri, "apelul nu mai există — reparația a fost ștearsă, nu mutată"
    for ap in apeluri:
        chei = {kw.arg for kw in ap.keywords}
        assert "target_missing" in chei, (
            "apelantul de producție nu cere modul ADR-077 — providerii de "
            "rezervă redevin inerți"
        )
        assert "require_referee" not in chei, (
            "apelantul încă pasează câmpul-martor"
        )


# ── chunk-uire: a cincea instanță a plafonului PostgREST (§2.2) ───────────

def test_filtrul_single_owner_chunk_uieste_peste_500():
    import pytest
    mp = pytest.MonkeyPatch()
    try:
        c = _cu_client(mp)
        q.get_match_ids_with_complete_flashscore_stats(list(range(1200)))
        assert c.ultima is not None
        # fiecare `table()` creează un query nou, deci numărăm bucățile pe
        # ultimul — codul real refolosește clientul, nu query-ul
        total = sum(len(b) for b in c.ultima.bucati)
        assert total == 0 or max(len(b) for b in c.ultima.bucati) <= 500
    finally:
        mp.undo()


def test_filtrul_single_owner_chunk_uieste_numarand_cererile():
    """Verificarea care contează: 1200 de id-uri => 3 cereri, nu una."""
    import pytest
    mp = pytest.MonkeyPatch()

    cereri: list[list] = []

    class _Q2(_Query):
        def in_(self, _col, vals):
            cereri.append(list(vals))
            return self

    class _C2:
        def __init__(self):
            self.jurnal: list = []

        def table(self, _n):
            return _Q2(self.jurnal)

    try:
        mp.setattr(q, "get_client", lambda: _C2())
        q.get_match_ids_with_complete_flashscore_stats(list(range(1200)))
        assert len(cereri) == 3, f"s-au făcut {len(cereri)} cereri, aşteptat 3"
        assert all(len(b) <= 500 for b in cereri)
        assert sum(len(b) for b in cereri) == 1200, "s-au pierdut id-uri la tăiere"
    finally:
        mp.undo()


def test_filtrul_single_owner_lista_mica_o_singura_cerere():
    """Contrapondere: chunk-uirea nu trebuie să adauge cereri degeaba."""
    import pytest
    mp = pytest.MonkeyPatch()
    cereri: list[list] = []

    class _Q2(_Query):
        def in_(self, _col, vals):
            cereri.append(list(vals))
            return self

    class _C2:
        def __init__(self):
            self.jurnal: list = []

        def table(self, _n):
            return _Q2(self.jurnal)

    try:
        mp.setattr(q, "get_client", lambda: _C2())
        q.get_match_ids_with_complete_flashscore_stats([1, 2, 3])
        assert len(cereri) == 1
    finally:
        mp.undo()


def test_filtrul_single_owner_lista_goala_nu_face_nicio_cerere():
    import pytest
    mp = pytest.MonkeyPatch()
    cereri: list[list] = []

    class _Q2(_Query):
        def in_(self, _col, vals):
            cereri.append(list(vals))
            return self

    class _C2:
        def __init__(self):
            self.jurnal: list = []

        def table(self, _n):
            return _Q2(self.jurnal)

    try:
        mp.setattr(q, "get_client", lambda: _C2())
        assert q.get_match_ids_with_complete_flashscore_stats([]) == set()
        assert cereri == []
    finally:
        mp.undo()


def test_filtrul_single_owner_la_eroare_intoarce_set_GOL_nu_partial():
    """Un set parțial ar trimite la providerii de rezervă meciuri pe care
    Flashscore le-a acoperit deja — exact risipa pe care Single Owner
    (ADR-045) previne. Deci parțialul e mai rău decât nimic."""
    import pytest
    mp = pytest.MonkeyPatch()

    class _QExplodeaza(_Query):
        """Prima bucată REUȘEȘTE și întoarce date reale; a doua aruncă.

        Detaliul ăsta e esențial și a fost găsit prin mutație: prima versiune
        a falsului întorcea `data: []` pe toate bucățile, deci `gasite` rămânea
        gol oricum — iar mutația „întoarce parțialul în loc de setul gol"
        TRECEA, fiindcă parțialul era tot gol. **Un test care nu poate
        distinge cele două ramuri nu testează nimic**, chiar dacă e verde.
        """

        def __init__(self, jurnal, contor):
            super().__init__(jurnal)
            self.contor = contor
            self._explodeaza = False

        def in_(self, _col, vals):
            self.contor.append(1)
            if len(self.contor) >= 2:
                raise RuntimeError("Supabase picat la a doua bucată")
            return self

        def execute(self):
            class _R:
                # date REALE pe prima bucată — altfel parțialul e indistinct
                # de setul gol și mutația trece.
                data = [{"match_id": 7}, {"match_id": 11}]
            return _R()

    class _C2:
        def __init__(self):
            self.jurnal: list = []
            self.contor: list = []

        def table(self, _n):
            return _QExplodeaza(self.jurnal, self.contor)

    try:
        mp.setattr(q, "get_client", lambda: _C2())
        rezultat = q.get_match_ids_with_complete_flashscore_stats(list(range(1200)))
        assert rezultat == set(), (
            f"s-a întors parțialul {rezultat!r} în loc de setul gol — meciuri "
            "deja acoperite de Flashscore ar fi trimise la providerii de "
            "rezervă, exact risipa pe care Single Owner previne"
        )
    finally:
        mp.undo()


# ── invariant de proiect: niciun alt apelant nu folosește martorul ────────

def test_niciun_alt_cod_de_productie_nu_mai_cere_require_referee():
    """Dacă apare un apelant nou cu `require_referee=True`, cade aici — ca
    defectul ADR-077 să nu fie reintrodus într-un alt flux."""
    import ast
    import pathlib

    rădăcină = pathlib.Path(q.__file__).parent.parent
    vinovați: list[str] = []
    for cale in rădăcină.rglob("*.py"):
        if ".git" in cale.parts or "__pycache__" in cale.parts or "tests" in cale.parts:
            continue
        try:
            arbore = ast.parse(cale.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        for nod in ast.walk(arbore):
            if not isinstance(nod, ast.Call):
                continue
            nume = getattr(nod.func, "id", getattr(nod.func, "attr", ""))
            if nume != "get_finished_matches_missing_stats":
                continue
            for kw in nod.keywords:
                if kw.arg == "require_referee" and isinstance(kw.value, ast.Constant) \
                        and kw.value.value is True:
                    vinovați.append(f"{cale.relative_to(rădăcină)}:{nod.lineno}")
    assert vinovați == [], (
        f"`require_referee=True` reintrodus în cod de producție: {vinovați} — "
        "câmpul-martor are al doilea scriitor din ADR-044/045, deci criteriul "
        "poate întoarce 0 fără ca nimic să fie în regulă"
    )
