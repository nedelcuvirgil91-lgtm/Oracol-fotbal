"""Gardă — o dată trimisă unui provider se taie la 10 caractere ÎNAINTE de a i
se scoate cratimele.

════════════════════════════════════════════════════════════════════════════
DE CE EXISTĂ (2026-10-26)
════════════════════════════════════════════════════════════════════════════
`match_history.kickoff_date` e `text` și ține DOUĂ forme: `YYYY-MM-DD`
(57.366 rânduri) și `YYYY-MM-DDTHH:MM:SS` (2.390). Un apelant care face
`kickoff_date.replace("-", "")` pe forma lungă trimite `20260714T15:00:00`.

Soccer Football Info a răspuns la asta `{"code":8,"message":"Wrong d param"}`
pe **100% din apeluri timp de 15 zile**, iar defectul s-a activat **fără niciun
commit**: pe 9 oct mai existau 3 rânduri cu forma scurtă în fereastra de 2 zile
a resolverului, pe 10 oct zero. Ultimul succes 10 oct 08:20:04, primul 400 pe
11 oct 08:37:03. Declanșatorul a fost o proprietate a DATELOR.

A doua instanță (`oracle_api.get_freelf_finished_match_id`) era LATENTĂ —
mascată de faptul că FreeLF răspunde oricum 401/429 — și s-ar fi manifestat
exact în ziua în care cota se reface, arătând ca un defect nou.

════════════════════════════════════════════════════════════════════════════
DE CE AST, NU TEXT — și o afirmație a mea, VERIFICATĂ și găsită FALSĂ
════════════════════════════════════════════════════════════════════════════
Scrisesem întâi că o gardă textuală ar cădea pe propriile comentarii de
reparație, ca la `pipefail` (27 aug), numele de secrete (14 oct) și `decizie #`
din `app.py` (20 oct). **Am verificat: nu e adevărat aici.**
`grep 'replace("-", "")'` pe cele două fișiere reparate întoarce exact 4 linii,
toate de COD, niciuna de comentariu. Scrisesem concluzia din tipar, nu din
măsurătoare — exact eroarea pe care acest proiect o reproșează altora.

Motivul real pentru AST e altul, și e mai simplu: garda trebuie să distingă
RECEPTORUL. `target_date.replace(...)` e legitim, `kickoff_date.replace(...)`
e defectul, iar `rand["kickoff_date"][:10].replace(...)` e corect deși numele
nu e la vedere. Un text-match ar trebui să reimplementeze parsarea ca să le
separe. AST-ul dă receptorul structural, gratuit.

════════════════════════════════════════════════════════════════════════════
CE IMPUNE, ȘI CE NU
════════════════════════════════════════════════════════════════════════════
Implicitul e INVERS celui intuitiv: orice `.replace("-", "")` din cod de
producție trebuie să aibă receptorul tăiat cu `[:10]`, SAU să fie trecut
explicit în `_PERMISE`, cu motiv scris. Lista crește prin decizie, nu prin
construcție — cod nou trebuie să se justifice, nu să fie prins.

NU impune nimic despre `datetime`, parsare sau fusuri orare. Nu e o gardă de
corectitudine a datelor; e o gardă contra UNEI expresii cu o victimă dovedită.
"""
from __future__ import annotations

import ast
import pathlib

RADACINA = pathlib.Path(__file__).resolve().parent.parent

# Excluse: testele însele, și POC-urile (temporare prin definiție, șterse după
# închiderea investigației — vezi regula din CLAUDE.md §chei API).
_DIRECTOARE_EXCLUSE = {"tests", ".git", "__pycache__", "cache", "predictions"}


def _este_poc(cale: pathlib.Path) -> bool:
    return cale.name.startswith("_poc_") or cale.name.startswith("poc_")


def _fisiere_productie() -> list[pathlib.Path]:
    fisiere = []
    for cale in RADACINA.rglob("*.py"):
        parti = set(cale.relative_to(RADACINA).parts)
        if parti & _DIRECTOARE_EXCLUSE or _este_poc(cale):
            continue
        fisiere.append(cale)
    return sorted(fisiere)


# ── Excepții, fiecare cu motiv VERIFICAT, nu presupus ───────────────────────
# Cheia e (numele fișierului, numele variabilei) — stabilă la mutarea liniilor,
# spre deosebire de un număr de linie.
_PERMISE: dict[tuple[str, str], str] = {
    ("oracle_api.py", "target_date"): (
        "dată generată INTERN, niciodată citită din match_history: apelanții "
        "sunt `(today + timedelta(days=i)).isoformat()` (oracle_api.py, bucla "
        "WeekLoop) — verificat la apelant, nu presupus. Mereu 10 caractere."
    ),
}


def _este_replace_de_cratime(nod: ast.AST) -> bool:
    """`<ceva>.replace("-", "")` — exact două argumente constante."""
    if not isinstance(nod, ast.Call):
        return False
    if not isinstance(nod.func, ast.Attribute) or nod.func.attr != "replace":
        return False
    if len(nod.args) != 2 or nod.keywords:
        return False
    a, b = nod.args
    return (isinstance(a, ast.Constant) and a.value == "-"
            and isinstance(b, ast.Constant) and b.value == "")


def _taiat_la_zece(receptor: ast.AST) -> bool:
    """Receptorul e `X[:10]` — felie fără capăt de jos, cu 10 sus."""
    if not isinstance(receptor, ast.Subscript):
        return False
    felie = receptor.slice
    if not isinstance(felie, ast.Slice):
        return False
    if felie.lower is not None or felie.step is not None:
        return False
    return isinstance(felie.upper, ast.Constant) and felie.upper.value == 10


def _nume_de_baza(nod: ast.AST) -> str | None:
    """Numele variabilei din care pleacă expresia, oricât de împachetată."""
    while True:
        if isinstance(nod, ast.Name):
            return nod.id
        if isinstance(nod, ast.Subscript):
            nod = nod.value
        elif isinstance(nod, ast.Attribute):
            nod = nod.value
        elif isinstance(nod, ast.Call):
            nod = nod.func
        else:
            return None


def _incalcari() -> list[tuple[str, int, str]]:
    gasite = []
    for cale in _fisiere_productie():
        try:
            arbore = ast.parse(cale.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        for nod in ast.walk(arbore):
            if not _este_replace_de_cratime(nod):
                continue
            receptor = nod.func.value
            if _taiat_la_zece(receptor):
                continue
            nume = _nume_de_baza(receptor) or "<expresie>"
            if (cale.name, nume) in _PERMISE:
                continue
            gasite.append((cale.name, nod.lineno, nume))
    return gasite


# ════════════════════════════════════════════════════════════════════════════
# GARDA CENTRALĂ
# ════════════════════════════════════════════════════════════════════════════

def test_orice_replace_de_cratime_are_receptorul_taiat_la_zece():
    incalcari = _incalcari()
    assert not incalcari, (
        "`.replace(\"-\", \"\")` pe o dată NEtăiată la 10 caractere — exact "
        "defectul care a omorât Soccer Football Info 15 zile "
        "(`Wrong d param`):\n"
        + "\n".join(f"  · {f}:{l} — variabila {v!r}" for f, l, v in incalcari)
        + "\n\nFie adaugi `[:10]` înaintea lui `.replace`, fie treci perechea "
          "(fișier, variabilă) în `_PERMISE` cu motivul VERIFICAT pentru care "
          "acea dată nu poate veni niciodată din `match_history`."
    )


# ════════════════════════════════════════════════════════════════════════════
# CONTRAPONDERI — o gardă care nu găsește nimic nu dovedește nimic
# ════════════════════════════════════════════════════════════════════════════

def test_garda_chiar_scaneaza_fisiere_reale():
    """Dacă `_fisiere_productie()` ar întoarce lista goală (excludere prea
    largă, redenumire de director), garda centrală ar trece VID."""
    fisiere = _fisiere_productie()
    assert len(fisiere) > 50, f"doar {len(fisiere)} fișiere scanate — excludere prea largă?"
    nume = {f.name for f in fisiere}
    assert "soccerfootballinfo_client.py" in nume
    assert "oracle_api.py" in nume


def test_cele_doua_locuri_reparate_sunt_chiar_gasite_de_detector():
    """Contrapondere directă: detectorul trebuie să VADĂ cele două apeluri
    reparate — altfel ar putea trece fiindcă nu le găsește, nu fiindcă sunt
    corecte. Verificat pe sursa REALĂ, nu pe un fixture inventat."""
    asteptate = {
        ("soccerfootballinfo_client.py", "date_iso"),
        ("oracle_api.py", "kickoff_date"),
    }
    gasite = set()
    for cale in _fisiere_productie():
        if cale.name not in {"soccerfootballinfo_client.py", "oracle_api.py"}:
            continue
        arbore = ast.parse(cale.read_text(encoding="utf-8"))
        for nod in ast.walk(arbore):
            if _este_replace_de_cratime(nod) and _taiat_la_zece(nod.func.value):
                nume = _nume_de_baza(nod.func.value)
                if nume:
                    gasite.add((cale.name, nume))
    lipsa = asteptate - gasite
    assert not lipsa, (
        f"apelurile reparate nu mai sunt găsite de detector: {lipsa}. "
        "Ori s-au mutat/redenumit, ori detectorul s-a rupt — în ambele cazuri "
        "garda centrală a devenit oarbă pe exact locurile pentru care există."
    )


# ════════════════════════════════════════════════════════════════════════════
# PREDICATELE, pe cazuri sintetice
# ════════════════════════════════════════════════════════════════════════════

def _expr(sursa: str) -> ast.AST:
    return ast.parse(sursa, mode="eval").body


def test_detecteaza_defectul_original():
    nod = _expr('kickoff_date.replace("-", "")')
    assert _este_replace_de_cratime(nod)
    assert not _taiat_la_zece(nod.func.value)


def test_accepta_forma_reparata():
    nod = _expr('kickoff_date[:10].replace("-", "")')
    assert _este_replace_de_cratime(nod)
    assert _taiat_la_zece(nod.func.value)


def test_o_felie_cu_ALT_capat_nu_trece():
    """`[:19]` ar păstra ora — e tocmai defectul, scris altfel."""
    assert not _taiat_la_zece(_expr('k[:19].replace("-", "")').func.value)


def test_o_felie_cu_capat_de_jos_nu_trece():
    """`[0:10]` e echivalent semantic, dar `[2:10]` nu — garda cere forma
    canonică, fiindcă nu poate ști care dintre ele a fost intenția."""
    assert not _taiat_la_zece(_expr('k[2:10].replace("-", "")').func.value)


def test_replace_de_altceva_nu_e_vizat():
    assert not _este_replace_de_cratime(_expr('s.replace("_", "")'))
    assert not _este_replace_de_cratime(_expr('s.replace("-", "/")'))


def test_replace_cu_trei_argumente_nu_e_vizat():
    """`.replace("-", "", 1)` schimbă semantica — altă expresie, nu clasa asta."""
    assert not _este_replace_de_cratime(_expr('s.replace("-", "", 1)'))


def test_numele_de_baza_strabate_impachetarea():
    assert _nume_de_baza(_expr("kickoff_date")) == "kickoff_date"
    assert _nume_de_baza(_expr("rand['kickoff_date'][:10]")) == "rand"
    assert _nume_de_baza(_expr("obiect.kickoff_date")) == "obiect"
    assert _nume_de_baza(_expr('"2026-01-01"')) is None


def test_fiecare_permis_acopera_un_apel_care_CHIAR_exista():
    """O excepție care nu mai acoperă nimic e datorie, nu siguranță: rămâne în
    listă, pare să justifice ceva, și maschează ziua în care un apel real
    reapare sub acel nume.

    Testul ăsta există fiindcă prima versiune a gărzii avea o a doua intrare
    (`oracle_api.py`, `d`) pe care am scris-o din presupunere — apelul ESPN
    folosește de fapt `target_date`. N-o acoperea nimic și nimic n-ar fi
    semnalat asta."""
    folosite = set()
    for cale in _fisiere_productie():
        arbore = ast.parse(cale.read_text(encoding="utf-8"))
        for nod in ast.walk(arbore):
            if not _este_replace_de_cratime(nod) or _taiat_la_zece(nod.func.value):
                continue
            nume = _nume_de_baza(nod.func.value)
            if nume:
                folosite.add((cale.name, nume))
    nefolosite = set(_PERMISE) - folosite
    assert not nefolosite, (
        f"excepții care nu acoperă niciun apel real: {nefolosite}. "
        "Scoate-le — altfel justifică ceva ce nu mai există."
    )


def test_permise_au_toate_motiv_scris():
    """O excepție fără motiv e o excepție care se uită de ce există."""
    for cheie, motiv in _PERMISE.items():
        assert isinstance(motiv, str) and len(motiv) > 40, (
            f"excepția {cheie} n-are motiv scris — o listă de permise fără "
            "motive devine, în câteva luni, o listă pe care nimeni n-o mai "
            "poate audita."
        )
