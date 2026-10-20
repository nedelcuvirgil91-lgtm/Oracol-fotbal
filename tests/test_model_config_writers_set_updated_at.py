"""Gardă AST — orice scriitor de `model_config` din COD scrie și `updated_at`.

De ce exista (D-14, gasit 2026-10-20). `model_config.updated_at` e inghetat la
2026-09-06 11:29:08 in productie, desi au urmat cel putin trei scrieri de flag
(ADR-072, ADR-073, ADR-078). Cauza: `DEFAULT now()` se aplica doar pe `INSERT`,
nu pe `UPDATE`. Consecinta: lantul de amprente al flag-urilor nu mai poate fi
ancorat in timp — singura coloana care ar fi datat scrierile e cea sarita.

A patra instanta a clasei marcajului inghetat, cu mecanism NOU: nu `on_conflict`
care omite coloana (cele 6 reparate pe 26 august, acoperite de
`test_upsert_timestamp_freshness.py`), ci un `UPDATE` scris de mana care o
omite.

LIMITA DE ACOPERIRE, declarata explicit ca sa nu fie confundata cu o garantie:
garda asta citeste COD. Scrierile de flag din productie se fac azi prin MCP
(`execute_sql`), ad-hoc, si **nu trec prin niciun fisier .py** — deci garda nu
le poate vedea, prin construcție. Suprafata aceea e acoperita de skill-ul
`supabase-safety`, punctul 5. Garda asta acopera doar viitorul scriitor din cod:
azi `supabase_client.save_config()` e singurul si e corect, iar un al doilea
care ar uita coloana cade aici, cu numele functiei si al fisierului.

Verificata prin mutatie: scoaterea lui `updated_at` din `save_config()` face
testul central sa cada.
"""
from __future__ import annotations

import ast
from pathlib import Path

RADACINA = Path(__file__).resolve().parent.parent
# Tabele de configurare cu marcaj temporal. `model_weights` intra aici fiindcă e
# EXACT aceeasi clasa: un singur rand, `UPDATE` prin `save_weights()`, aceeasi
# forma de payload — a si fost nimerita din greseala de prima mutatie incercata
# pe garda asta, ceea ce a dovedit ca sunt indistingibile textual. Scriitorul ei
# e corect azi; garda il tine corect.
TABELE = ("model_config", "model_weights")
COLOANA_MARCAJ = "updated_at"
METODE_DE_SCRIERE = {"update", "upsert", "insert"}

# Directoare excluse: testele si fisierele de suport nu sunt cod de productie.
EXCLUSE = {"tests", ".git", "cache", "predictions", "node_modules", ".venv"}


def _fisiere_de_productie() -> list[Path]:
    fisiere: list[Path] = []
    for cale in RADACINA.rglob("*.py"):
        if any(parte in EXCLUSE for parte in cale.relative_to(RADACINA).parts):
            continue
        fisiere.append(cale)
    return sorted(fisiere)


def _lanț_atinge_tabela(nod: ast.AST) -> bool:
    """True daca lanțul de apeluri conține `.table(T)` cu T din `TABELE`.

    Coboara prin `func`/`value`, deci prinde si `client.table(T).update(...)`
    si forme mai lungi, `client.table(T).update(...).eq(...).execute()`."""
    curent: ast.AST | None = nod
    while curent is not None:
        if isinstance(curent, ast.Call):
            f = curent.func
            if (isinstance(f, ast.Attribute) and f.attr == "table"
                    and curent.args
                    and isinstance(curent.args[0], ast.Constant)
                    and curent.args[0].value in TABELE):
                return True
            curent = f
        elif isinstance(curent, ast.Attribute):
            curent = curent.value
        else:
            return False
    return False


def _chei_din_payload(apel: ast.Call) -> set[str] | None:
    """Cheile dict-ului pasat ca prim argument. `None` daca nu e un dict
    literal — caz in care nu putem decide si NU pretindem c-am verificat."""
    if not apel.args:
        return None
    primul = apel.args[0]
    if not isinstance(primul, ast.Dict):
        return None
    chei: set[str] = set()
    for k in primul.keys:
        if isinstance(k, ast.Constant) and isinstance(k.value, str):
            chei.add(k.value)
    return chei


def _scriitori() -> list[tuple[Path, int, set[str] | None]]:
    """(fișier, linie, chei) pentru fiecare scriere pe o tabelă din `TABELE`."""
    gasiti: list[tuple[Path, int, set[str] | None]] = []
    for cale in _fisiere_de_productie():
        try:
            arbore = ast.parse(cale.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):  # pragma: no cover
            continue
        for nod in ast.walk(arbore):
            if not isinstance(nod, ast.Call):
                continue
            f = nod.func
            if not (isinstance(f, ast.Attribute) and f.attr in METODE_DE_SCRIERE):
                continue
            if not _lanț_atinge_tabela(f.value):
                continue
            gasiti.append((cale, nod.lineno, _chei_din_payload(nod)))
    return gasiti


def test_exista_cel_putin_un_scriitor_de_configurare():
    """CONTRAPONDERE — fără ea, garda ar trece VID.

    Dacă tabela se redenumește sau `save_config()` dispare, testul central ar
    trece fiindcă nu mai găsește nimic de verificat — exact tiparul care a
    lăsat două gărzi șterse tăcut pe 14 octombrie. Aici cade explicit."""
    scriitori = _scriitori()
    assert scriitori, (
        f"Niciun scriitor găsit în cod pentru {TABELE}. Fie o tabelă a fost "
        f"redenumită, fie garda a devenit oarbă — în ambele cazuri trebuie "
        f"actualizată, nu lăsată să treacă vid."
    )


def test_fiecare_scriitor_de_configurare_scrie_updated_at():
    """Garda centrală."""
    lipsa: list[str] = []
    for cale, linie, chei in _scriitori():
        if chei is None:
            # Payload necunoscut la analiza statica — se raporteaza ca atare,
            # nu se declara verificat (Regula #8).
            continue
        if COLOANA_MARCAJ not in chei:
            rel = cale.relative_to(RADACINA)
            lipsa.append(f"{rel}:{linie} — chei scrise: {sorted(chei)}")
    assert not lipsa, (
        f"Scriere pe o tabelă de configurare fără `{COLOANA_MARCAJ}`. `DEFAULT now()` se "
        f"aplică doar pe INSERT, deci marcajul se îngheață tăcut:\n  "
        + "\n  ".join(lipsa)
    )


def test_payload_neanalizabil_e_raportat_nu_ascuns():
    """O scriere cu payload construit dinamic nu poate fi verificată statistic.

    Garda o lasă să treacă — dar testul ăsta documentează că trecerea e o
    LIMITĂ, nu o confirmare, și cade dacă apare una, ca să fie decisă
    conștient."""
    neanalizabili = [f"{c.relative_to(RADACINA)}:{l}"
                     for c, l, chei in _scriitori() if chei is None]
    assert not neanalizabili, (
        "Scriere pe `model_config` cu payload care nu e dict literal, deci "
        "neverificabilă static. De verificat manual și de adăugat o excepție "
        "explicită aici, cu motiv scris:\n  " + "\n  ".join(neanalizabili)
    )
