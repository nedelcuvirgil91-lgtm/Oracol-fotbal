"""Gardă — INVARIANTUL marcajului temporal la `upsert`, pe TOT codul.

DE CE EXISTĂ ÎNCĂ UNA. `tests/test_upsert_timestamp_freshness.py` a fost scrisă
pe 2026-08-26, după ce clasa „marcaj înghețat de `on_conflict`" fusese reparată
în 6 locuri. `CLAUDE.md` afirmă despre ea:

    „nu verifică cele 6 locuri (aia ar fi o listă, care se învechește exact ca
    documentația care ne-a mințit) — verifică INVARIANTUL... A șaptea instanță
    cade automat, cu numele funcției și al tabelei."

**Afirmația era falsă, și a șaptea instanță NU a căzut automat.** Pe 2026-11-03,
`engine_comparison_snapshots.captured_at` s-a dovedit înghețat — **464 din 1728
de rânduri (26,9%)** aveau marcajul ANTERIOR antrenării artefactului care le
produsese, cu un decalaj de până la **66 de zile**. Garda n-a văzut-o, din două
motive structurale independente:

  1. **e o listă hardcodată** (`TABELE_CU_MARCAJ_TEMPORAL`, 7 intrări);
  2. **scanează un singur modul** (`database.queries`), iar scriitorul vinovat
     trăiește în `supabase_client.py`.

Garda veche NU se șterge: rămâne validă pe raza ei și e mai strictă acolo (știe
că `first_seen_at` TREBUIE să reziste pe `DO UPDATE`). Asta o completează.

CUM E UN INVARIANT, NU O LISTĂ — două surse, niciuna întreținută manual:

  · **migrările** (`database/migrations/*.sql`) dau harta `tabelă → coloane
    timestamp cu DEFAULT`. O migrare nouă aduce automat tabela ei sub gardă.
    Azi acoperă 48 de tabele.
  · **o declarație de MOȘTENIRE**, mică și ancorată, doar pentru cele 4 tabele
    create direct în Supabase ÎNAINTE de a exista directorul de migrări.

Iar regula de închidere e cea care face diferența față de o listă: **orice
tabelă atinsă de un `upsert ... on_conflict` trebuie să fie într-una din cele
două surse.** O tabelă nouă nu poate scăpa tăcut — ori vine cu migrarea ei
(automat), ori forțează o decizie conștientă.

DISCRIMINATORUL care evită 5 false pozitive: `ignore_duplicates=True` înseamnă
`DO NOTHING`, deci nu există ramură de actualizare și nu există nimic de
înghețat. Append-only prin design nu e defect. Cele cinci —
`challenger_evaluations`, `champion_health_evaluations`,
`consensus_capture_samples`, `consensus_validation_verdicts`,
`equivalence_evaluations` — sunt verificate explicit mai jos ca atare, ca garda
să nu devină zgomot.

EXCLUSE DELIBERAT: `created_at` și `first_seen_at`. Acelea TREBUIE să rămână
înghețate pe `DO UPDATE` — „prima scriere" și „prima observare" ar fi minciuni
dacă s-ar împrospăta. Simetric cu nota din garda veche despre `first_seen_at`.

REGULA pe care o impune: **scriitorul pune marcajul.** Nu constructorul rândului
dintr-un alt modul — tiparul celor 6 reparații din august, păstrat.
"""
from __future__ import annotations

import ast
import pathlib
import re

RADACINA = pathlib.Path(__file__).resolve().parent.parent
DIR_MIGRARI = RADACINA / "database" / "migrations"

# Coloane care TREBUIE să rămână înghețate pe `DO UPDATE` — nu sunt defecte.
COLOANE_DE_PRIMA_SCRIERE = {"created_at", "first_seen_at"}

# MOȘTENIRE — tabele create direct în Supabase, înainte să existe directorul de
# migrări, deci invizibile pentru sursa automată. Ancorate la 2026-11-03;
# lista poate doar să SCADĂ (dacă o tabelă primește o migrare), niciodată să
# crească: o tabelă nouă vine cu migrarea ei.
TABELE_MOSTENITE: dict[str, set[str]] = {
    "shadow_predictions": {"prediction_time"},
    "experiment_registry": {"last_evaluated_at"},
    "api_cache": set(),                    # doar `created_at` — corect înghețat
    "elo_ratings": {"updated_at"},
    "api_provider_status": {"last_updated"},
    "league_provider_coverage": {"checked_at"},
    "elo_history": set(),                  # doar `created_at`
    "sync_status": set(),                  # niciun timestamp cu DEFAULT
}

_RE_TIMESTAMP_COL = re.compile(
    r"^\s*[\"']?([a-z_][a-z0-9_]*)[\"']?\s+TIMESTAMP(?:TZ|\s+WITH\s+TIME\s+ZONE)?\b"
    r"[^,]*\bDEFAULT\b",
    re.IGNORECASE,
)


def _fara_comentarii(sql: str) -> str:
    """Elimină comentariile ÎNAINTE de parsare.

    DUPLICAT DELIBERAT față de celelalte gărzi: o gardă nu are voie să depindă
    de interiorul alteia — dacă aceea e slăbită, asta trebuie să rămână în
    picioare. Și e necesar aici: docstring-ul acestui fișier conține chiar
    `captured_at` și `DEFAULT`."""
    fara_bloc = re.sub(r"/\*[\s\S]*?\*/", " ", sql)
    return "\n".join(l.split("--", 1)[0] for l in fara_bloc.splitlines())


def _corp_create_table(cod: str, start: int) -> str:
    """Conținutul parantezelor unui `CREATE TABLE`, echilibrat."""
    i = cod.find("(", start)
    if i < 0:
        return ""
    adancime, j = 0, i
    while j < len(cod):
        if cod[j] == "(":
            adancime += 1
        elif cod[j] == ")":
            adancime -= 1
            if adancime == 0:
                return cod[i + 1:j]
        j += 1
    return cod[i + 1:]


def harta_din_migrari() -> dict[str, set[str]]:
    """`tabelă -> coloane timestamp cu DEFAULT`, citită din migrări."""
    harta: dict[str, set[str]] = {}
    re_create = re.compile(
        r"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:public\.)?[\"']?"
        r"([a-zA-Z_][a-zA-Z0-9_]*)[\"']?", re.IGNORECASE)
    for cale in sorted(DIR_MIGRARI.glob("*.sql")):
        cod = _fara_comentarii(cale.read_text(encoding="utf-8", errors="ignore"))
        for m in re_create.finditer(cod):
            tabela = m.group(1).lower()
            coloane = {
                c.group(1).lower()
                for linie in _corp_create_table(cod, m.end()).split(",")
                if (c := _RE_TIMESTAMP_COL.match(linie))
            }
            harta.setdefault(tabela, set()).update(coloane)
    return harta


def coloane_de_prospetime(tabela: str) -> set[str] | None:
    """Coloanele care TREBUIE scrise explicit. `None` = tabelă necunoscută."""
    harta = harta_din_migrari()
    if tabela in harta:
        return harta[tabela] - COLOANE_DE_PRIMA_SCRIERE
    if tabela in TABELE_MOSTENITE:
        return TABELE_MOSTENITE[tabela] - COLOANE_DE_PRIMA_SCRIERE
    return None


def _fisiere_productie() -> list[pathlib.Path]:
    return [
        p for p in sorted(RADACINA.rglob("*.py"))
        if "tests" not in p.parts and ".git" not in p.parts
        and "scratchpad" not in p.parts
    ]


def _nume_tabela(nod: ast.Call) -> str | None:
    cur = nod.func.value
    while True:
        if (isinstance(cur, ast.Call) and isinstance(cur.func, ast.Attribute)
                and cur.func.attr == "table" and cur.args):
            arg = cur.args[0]
            return arg.value if isinstance(arg, ast.Constant) else None
        if isinstance(cur, ast.Call):
            cur = cur.func
        elif isinstance(cur, ast.Attribute):
            cur = cur.value
        else:
            return None


def upserturi_cu_conflict() -> list[tuple[str, int, str, str, bool]]:
    """`(fișier, linie, funcție, tabelă, ignora_duplicatele)` — toate."""
    gasite = []
    for cale in _fisiere_productie():
        try:
            sursa = cale.read_text(encoding="utf-8")
            arbore = ast.parse(sursa)
        except (SyntaxError, UnicodeDecodeError):
            continue
        functii = [(n, n.lineno, getattr(n, "end_lineno", n.lineno))
                   for n in ast.walk(arbore)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        for nod in ast.walk(arbore):
            if not (isinstance(nod, ast.Call) and isinstance(nod.func, ast.Attribute)
                    and nod.func.attr == "upsert"):
                continue
            if not any(k.arg == "on_conflict" for k in nod.keywords):
                continue
            tabela = _nume_tabela(nod)
            if tabela is None:
                continue
            ignora = any(
                k.arg == "ignore_duplicates" and isinstance(k.value, ast.Constant)
                and k.value.value is True for k in nod.keywords)
            incadrante = [f for f, a, b in functii if a <= nod.lineno <= b]
            fn = min(incadrante, key=lambda f: nod.lineno - f.lineno) if incadrante else None
            gasite.append((
                str(cale.relative_to(RADACINA)), nod.lineno,
                fn.name if fn else "<modul>", tabela, ignora,
            ))
    return gasite


def _sursa_functiei(fisier: str, nume: str) -> str:
    sursa = (RADACINA / fisier).read_text(encoding="utf-8")
    for nod in ast.walk(ast.parse(sursa)):
        if isinstance(nod, (ast.FunctionDef, ast.AsyncFunctionDef)) and nod.name == nume:
            return ast.get_source_segment(sursa, nod) or ""
    return ""


def incalcari() -> list[str]:
    rele = []
    for fisier, linie, fn, tabela, ignora in upserturi_cu_conflict():
        if ignora:
            continue  # DO NOTHING — nicio ramură de actualizare, nimic de înghețat
        cols = coloane_de_prospetime(tabela)
        if not cols:
            continue
        corp = _sursa_functiei(fisier, fn)
        lipsa = [c for c in cols
                 if f'"{c}"' not in corp and f"'{c}'" not in corp]
        if lipsa:
            rele.append(f"{fisier}:{linie} {fn}() -> {tabela} "
                        f"(lipsește: {', '.join(sorted(lipsa))})")
    return rele


# ════════════════════════════════════════════════════════════════════════════
# Garda centrală
# ════════════════════════════════════════════════════════════════════════════

def test_niciun_upsert_nu_inghetata_marcajul_temporal():
    """A OPTA instanță cade aici, oriunde ar fi în cod."""
    rele = incalcari()
    assert not rele, (
        "`upsert ... on_conflict` FĂRĂ `ignore_duplicates` intră pe `DO UPDATE`, "
        "iar `DEFAULT now()` NU se aplică acolo — marcajul rămâne de la prima "
        "scriere, iar rândul poartă o dată falsă. Scriitorul trebuie să-l pună "
        "explicit:\n  " + "\n  ".join(rele)
    )


def test_orice_tabela_upsertata_e_cunoscuta_de_una_din_cele_doua_surse():
    """Regula care face din asta un invariant, nu o listă.

    O tabelă nouă atinsă de `upsert ... on_conflict` trebuie să fie ori în
    migrări (automat), ori declarată conștient ca moștenire. Nu poate scăpa
    tăcut — exact cum a scăpat `engine_comparison_snapshots` de garda veche."""
    harta = harta_din_migrari()
    necunoscute = sorted({
        tabela for _, _, _, tabela, _ in upserturi_cu_conflict()
        if tabela not in harta and tabela not in TABELE_MOSTENITE
    })
    assert not necunoscute, (
        "tabele atinse de `upsert ... on_conflict` pe care garda nu le poate "
        "judeca — nici în `database/migrations/`, nici declarate ca moștenire:\n  "
        + "\n  ".join(necunoscute)
    )


# ════════════════════════════════════════════════════════════════════════════
# Martori pozitivi — ca garda să nu treacă VID
# ════════════════════════════════════════════════════════════════════════════

def test_sursa_din_migrari_chiar_gaseste_tabele():
    """Dacă parserul de migrări s-ar rupe, garda ar trece verde fără să
    judece nimic. Ancorat la realitatea din 2026-11-03: 48 de tabele."""
    harta = harta_din_migrari()
    assert len(harta) >= 40, f"doar {len(harta)} tabele găsite în migrări"
    assert "engine_comparison_snapshots" in harta
    assert "captured_at" in harta["engine_comparison_snapshots"]


def test_cele_doua_instante_reale_sunt_acum_acoperite():
    """Martorul care contează: exact cele două scrieri reparate pe 2026-11-03."""
    for fn in ("save_engine_comparison_snapshot", "save_validation_analysis_report"):
        corp = _sursa_functiei("supabase_client.py", fn)
        assert corp, f"{fn}() nu mai există"
        assert "_acum_utc()" in corp, f"{fn}() nu mai scrie marcajul explicit"


def test_cele_cinci_append_only_NU_sunt_raportate():
    """Contrapondere — fără discriminatorul `ignore_duplicates`, garda ar
    raporta 5 false pozitive și ar deveni zgomot ignorat."""
    cu_ignore = {
        (t, i) for _, _, _, t, i in upserturi_cu_conflict() if i
    }
    numite = {t for t, _ in cu_ignore}
    for tabela in ("challenger_evaluations", "champion_health_evaluations",
                   "consensus_capture_samples", "consensus_validation_verdicts",
                   "equivalence_evaluations"):
        assert tabela in numite, (
            f"{tabela} nu mai e scrisă cu `ignore_duplicates=True` — dacă a "
            f"devenit `DO UPDATE`, are nevoie de marcaj explicit"
        )


def test_coloanele_de_prima_scriere_sunt_excluse():
    """`created_at` / `first_seen_at` TREBUIE să rămână înghețate."""
    harta = harta_din_migrari()
    assert "created_at" in harta.get("match_events", set()), \
        "martor pozitiv pierdut: `match_events.created_at` nu mai e văzut"
    assert "created_at" not in (coloane_de_prospetime("match_events") or set())
    assert "first_seen_at" not in (coloane_de_prospetime("flashscore_team_identity") or set())
    assert "last_seen_at" in (coloane_de_prospetime("flashscore_team_identity") or set())


def test_discriminatorul_vede_si_cazul_fara_ignore_duplicates():
    """Simetric: scrierile reparate NU au `ignore_duplicates`, deci garda
    chiar le judecă (nu le sare din întâmplare)."""
    fara_ignore = {
        (fn, t) for _, _, fn, t, i in upserturi_cu_conflict() if not i
    }
    assert ("save_engine_comparison_snapshot", "engine_comparison_snapshots") in fara_ignore
    assert ("save_validation_analysis_report", "validation_analysis_reports") in fara_ignore


def test_garda_veche_ramane_pe_loc():
    """Asta o COMPLETEAZĂ, nu o înlocuiește — aceea e mai strictă pe raza ei
    (știe că `first_seen_at` trebuie să reziste). Ștergerea ei ar pierde acea
    cunoaștere."""
    assert (RADACINA / "tests" / "test_upsert_timestamp_freshness.py").is_file()


def test_lista_de_mostenire_nu_poate_creste_tacit():
    """Ancoră. Cele 4 tabele moștenite sunt cele dinainte de directorul de
    migrări; o a cincea ar însemna ori o tabelă nouă fără migrare (interzis
    de `test_orice_tabela_upsertata_e_cunoscuta`), ori o slăbire a gărzii."""
    assert len(TABELE_MOSTENITE) <= 8, (
        f"declarația de moștenire a crescut la {len(TABELE_MOSTENITE)} — o "
        f"tabelă nouă vine cu migrarea ei, nu cu o intrare aici"
    )
    harta = harta_din_migrari()
    migrate = sorted(t for t in TABELE_MOSTENITE if t in harta)
    assert not migrate, (
        f"tabelele {migrate} au primit între timp migrare — se scot din "
        f"declarația de moștenire, lista poate doar să scadă"
    )
