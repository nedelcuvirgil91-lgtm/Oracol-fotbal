"""Gardă — orice migrare care redefinește o funcție îi păstrează `search_path`.

DE CE EXISTĂ, cu dată și cu instanța care a produs-o. Migrarea **042**
(„SECURITY DEFINER view fix + explicit search_path pentru 15 functii", Master
Repair Plan, Pasul 3, P1) a aplicat hardening pe toate cele 15 funcții din
`public`, printre care, pe linia 35:

    ALTER FUNCTION public._upsert_match_canonical_locked(jsonb)
      SET search_path = public, pg_temp;

Apoi migrările **048, 049, 052 și 053** au redefinit funcția — și EXCLUSIV pe
ea — prin `CREATE OR REPLACE FUNCTION`, fără nicio clauză `SET`. În PostgreSQL,
`CREATE OR REPLACE FUNCTION` **înlocuiește atributele funcției**, inclusiv
`proconfig`. Fiecare dintre cele patru a ȘTERS TĂCUT setarea pusă de 042: fără
eroare, fără avertisment, fără nimic în jurnal.

Rezultatul măsurat pe 2026-11-03, înainte de reparație: **1 funcție din 15**
fără `search_path`. Și exact aceea e `_upsert_match_canonical_locked` — RPC-ul
canonic de scriere, cel care serializează fiecare scriere în `match_history`
prin `pg_advisory_xact_lock`. Celelalte 14 își păstraseră setarea dintr-un
motiv pasiv: nimeni nu le-a mai redefinit după 042.

CLASA, mai largă decât instanța: **un hardening aplicat prin `ALTER` e anulat de
orice `CREATE OR REPLACE` ulterior.** E ruda mecanismului deja numit în
`CLAUDE.md` — „un ADR a invalidat tacit precondiția altui ADR" (ADR-077,
`referee`) — dar cu alt mecanism: nu un al doilea scriitor pe un câmp-martor, ci
o instrucțiune care resetează atribute pe care nu le menționează.

CE **NU** ERA GRAV, și se scrie aici ca să nu fie citit mai alarmant decât e:
niciuna dintre cele 15 funcții nu e `SECURITY DEFINER` (verificat în
`pg_proc.prosecdef`, și afirmat deja de antetul lui 042), deci nu există vector
de escaladare; calea de producție trece prin `upsert_match_canonical` și
`upsert_matches_canonical`, care AU `search_path` setat și îl transmit apelului
imbricat; iar `match_history` are RLS activ cu zero politici, deci un apel
direct prin PostgREST n-ar putea scrie oricum. Riscul practic era ~0 — exact
concluzia la care ajunsese 042 despre el însuși („hardening standard împotriva
unui atac teoretic"). **Garda asta nu păzește o breșă, păzește un mecanism de
regresie tăcută.**

DE CE O GARDĂ ÎN REPO ȘI NU DOAR ADVISOR-UL. Lint-ul Supabase
`function_search_path_mutable` chiar a prins-o — dar e de nivel **WARN**, iar
mecanismul declarat pentru advisor (D-6, varianta 3d) raportează doar **ERROR**,
tocmai ca să nu devină zgomot. Garda asta prinde instanța următoare la commit,
nu la trei luni după.

DE CE UN PRAG, NU O LISTĂ. Migrările existente sunt evidența a ce s-a RULAT, nu
documente vii — nu se repară retroactiv. Pragul e ancorat ISTORIC de **053**,
ultima migrare care a pierdut setarea, și poate doar să COBOARE.

NEVACUITATE. Azi nicio migrare peste prag nu definește vreo funcție, deci
verificarea principală ar trece pe un set GOL și n-ar dovedi nimic singură —
capcana plătită deja de trei ori în proiect. De aceea logica e exercitată pe
cazuri sintetice ȘI pe **fișierele reale 053 și 042**, ca martori pozitivi:
unul trebuie PRINS, celălalt trebuie recunoscut ca acoperitor.
"""
from __future__ import annotations

import re
from pathlib import Path

RADACINA = Path(__file__).resolve().parent.parent
DIR_MIGRARI = RADACINA / "database" / "migrations"

# Prima migrare care trebuie să păstreze `search_path`. Cele de sub prag au
# rulat deja; reparația lor e migrarea 060, nu o rescriere retroactivă.
PRAG_SEARCH_PATH_OBLIGATORIU = 54

# Ultima migrare care a ȘTERS setarea pusă de 042. Ancoră ISTORICĂ a pragului.
ULTIMA_MIGRARE_CARE_A_PIERDUT_SETAREA = 53

_RE_NUMAR = re.compile(r"^(\d{3})_")

_RE_CREATE_FUNC = re.compile(
    r"\bCREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+"
    r"(?:public\.)?[\"']?([A-Za-z_][A-Za-z0-9_]*)[\"']?",
    re.IGNORECASE,
)
_RE_ALTER_FUNC = re.compile(
    r"\bALTER\s+FUNCTION\s+(?:public\.)?[\"']?([A-Za-z_][A-Za-z0-9_]*)[\"']?",
    re.IGNORECASE,
)
# Începutul corpului unei funcții: `AS $...$` sau `AS '...'`.
_RE_INCEPUT_CORP = re.compile(r"\bAS\s*(?:\$|')", re.IGNORECASE)
_RE_SET_SEARCH_PATH = re.compile(r"\bSET\s+search_path\b", re.IGNORECASE)


def doar_cod(sql: str) -> str:
    """Elimină comentariile ÎNAINTE de orice verificare.

    DUPLICAT DELIBERAT față de `test_migration_grants.doar_cod`. O gardă nu are
    voie să depindă de interiorul altei gărzi: dacă aceea e slăbită sau
    rescrisă, asta trebuie să rămână în picioare. Independența costă zece linii
    și e singurul lucru care face două gărzi să fie două.

    Fără eliminarea comentariilor, garda s-ar găsi pe sine: docstring-ul de mai
    sus conține chiar `SET search_path`, de mai multe ori. A noua instanță a
    clasei `pipefail` (27 aug), și de data asta prevenită, nu descoperită."""
    fara_bloc = re.sub(r"/\*[\s\S]*?\*/", " ", sql)
    return "\n".join(linie.split("--", 1)[0] for linie in fara_bloc.splitlines())


def _antet_definitie(cod: str, de_la: int) -> str:
    """Textul dintre numele funcției și începutul corpului.

    Se oprește la `AS $` / `AS '` DELIBERAT: un `SET search_path` aflat în
    CORPUL altei funcții nu trebuie să acopere definiția asta. Fără tăietura
    aceasta, o migrare care definește două funcții și setează calea doar pentru
    a doua ar trece — iar prima ar rămâne exact defectul pe care îl păzim."""
    potrivire = _RE_INCEPUT_CORP.search(cod, de_la)
    sfarsit = potrivire.start() if potrivire else len(cod)
    return cod[de_la:sfarsit]


def functii_redefinite(sql: str) -> list[str]:
    """Funcțiile create sau înlocuite de migrare, în ordinea apariției."""
    return [m.group(1) for m in _RE_CREATE_FUNC.finditer(doar_cod(sql))]


def functii_neacoperite(sql: str) -> list[str]:
    """Funcții redefinite fără ca `search_path` să le fie (re)setat.

    ORDINEA CONTEAZĂ, și e tot defectul în miniatură: un `ALTER ... SET
    search_path` care precede un `CREATE OR REPLACE` al aceleiași funcții NU o
    acoperă — exact ce s-a întâmplat între 042 și 048. Deci `ALTER`-ul e
    acceptat numai dacă apare DUPĂ definiția pe care o repară."""
    cod = doar_cod(sql)
    alter_dupa: dict[str, list[int]] = {}
    for m in _RE_ALTER_FUNC.finditer(cod):
        nume = m.group(1).lower()
        if _RE_SET_SEARCH_PATH.search(_antet_definitie(cod, m.end())):
            alter_dupa.setdefault(nume, []).append(m.start())

    neacoperite: list[str] = []
    for m in _RE_CREATE_FUNC.finditer(cod):
        nume = m.group(1)
        if _RE_SET_SEARCH_PATH.search(_antet_definitie(cod, m.end())):
            continue  # clauza e în chiar definiția funcției
        if any(poz > m.start() for poz in alter_dupa.get(nume.lower(), [])):
            continue  # reparată printr-un ALTER care vine DUPĂ
        neacoperite.append(nume)
    return neacoperite


def incalca_regula(sql: str) -> bool:
    return bool(functii_neacoperite(sql))


def _migrari_numerotate() -> list[tuple[int, Path]]:
    gasite: list[tuple[int, Path]] = []
    for cale in sorted(DIR_MIGRARI.glob("*.sql")):
        potrivire = _RE_NUMAR.match(cale.name)
        if potrivire:
            gasite.append((int(potrivire.group(1)), cale))
    return gasite


def _citeste(numar: int) -> str:
    for n, cale in _migrari_numerotate():
        if n == numar:
            return cale.read_text(encoding="utf-8")
    raise AssertionError(f"migrarea {numar:03d} nu există")


# ════════════════════════════════════════════════════════════════════════════
# Verificarea principală — azi nu are ce să prindă, și e în regulă
# ════════════════════════════════════════════════════════════════════════════

def test_migrarile_de_la_prag_in_sus_pastreaza_search_path():
    """Garda centrală. Cade cu numele fișierului și al funcției."""
    lipsa = []
    for numar, cale in _migrari_numerotate():
        if numar < PRAG_SEARCH_PATH_OBLIGATORIU:
            continue
        neacoperite = functii_neacoperite(cale.read_text(encoding="utf-8"))
        if neacoperite:
            lipsa.append(f"{cale.name} — redefinește {neacoperite} fără "
                         f"`SET search_path`")
    assert not lipsa, (
        "`CREATE OR REPLACE FUNCTION` ȘTERGE atributele funcției, inclusiv "
        "`search_path`. Exact așa au anulat migrările 048/049/052/053 "
        "hardening-ul pus de 042, tăcut, de patru ori la rând. Adaugă "
        "`SET search_path = public, pg_temp` în definiție, sau un "
        "`ALTER FUNCTION ... SET search_path` DUPĂ ea:\n  "
        + "\n  ".join(lipsa)
    )


# ════════════════════════════════════════════════════════════════════════════
# Martori pozitivi pe fișiere REALE — ca garda să nu treacă vid
# ════════════════════════════════════════════════════════════════════════════

def test_migrarea_053_REALA_e_prinsa_de_garda():
    """Martorul pozitiv care contează cel mai mult.

    053 e ultima migrare care a șters setarea. Dacă garda n-o prinde, garda nu
    funcționează — oricât de verzi ar fi cazurile sintetice. Un „0" nu se
    raportează fără martor pozitiv."""
    neacoperite = functii_neacoperite(_citeste(53))
    assert "_upsert_match_canonical_locked" in neacoperite, (
        "garda NU prinde instanța reală care a produs-o — e oarbă"
    )


def test_toate_cele_patru_migrari_vinovate_sunt_prinse():
    """048, 049, 052, 053 — toate au făcut aceeași greșeală."""
    for numar in (48, 49, 52, 53):
        assert "_upsert_match_canonical_locked" in functii_neacoperite(
            _citeste(numar)
        ), f"migrarea {numar:03d} nu e prinsă"


def test_migrarea_042_REALA_nu_redefineste_nimic_dar_repara_15_functii():
    """Simetricul: 042 e forma CORECTĂ, iar parserul de `ALTER` trebuie s-o
    vadă pe un fișier real, nu doar pe unul inventat.

    042 nu conține niciun `CREATE OR REPLACE FUNCTION` — doar `ALTER`-uri. (O
    măsurătoare anterioară a spus greșit că „redefinește", fiindcă tiparul de
    căutare potrivea chiar linia `ALTER`. Corectat prin citirea fișierului.)"""
    sql = _citeste(42)
    assert functii_redefinite(sql) == [], "042 nu ar trebui să definească funcții"
    cod = doar_cod(sql)
    reparate = {
        m.group(1).lower()
        for m in _RE_ALTER_FUNC.finditer(cod)
        if _RE_SET_SEARCH_PATH.search(_antet_definitie(cod, m.end()))
    }
    assert len(reparate) == 15, f"așteptam 15 funcții reparate, am găsit {len(reparate)}"
    assert "_upsert_match_canonical_locked" in reparate


def test_migrarea_060_REALA_repara_functia_si_trece_garda():
    """Reparația însăși nu are voie să încalce regula pe care o restabilește."""
    sql = _citeste(60)
    assert not incalca_regula(sql)
    cod = doar_cod(sql)
    assert _RE_SET_SEARCH_PATH.search(cod), "060 nu mai setează `search_path`"
    assert "_upsert_match_canonical_locked" in cod


# ════════════════════════════════════════════════════════════════════════════
# Cazuri sintetice — logica, exercitată independent de fișierele reale
# ════════════════════════════════════════════════════════════════════════════

def test_create_fara_search_path_e_prins():
    sql = """
        CREATE OR REPLACE FUNCTION ceva(p jsonb) RETURNS jsonb
        LANGUAGE plpgsql
        AS $function$ BEGIN RETURN p; END; $function$;
    """
    assert functii_neacoperite(sql) == ["ceva"]


def test_search_path_IN_DEFINITIE_trece():
    sql = """
        CREATE OR REPLACE FUNCTION ceva(p jsonb) RETURNS jsonb
        LANGUAGE plpgsql
        SET search_path = public, pg_temp
        AS $function$ BEGIN RETURN p; END; $function$;
    """
    assert not incalca_regula(sql)


def test_ALTER_DUPA_definitie_trece():
    sql = """
        CREATE OR REPLACE FUNCTION ceva(p jsonb) RETURNS jsonb
        LANGUAGE plpgsql AS $function$ BEGIN RETURN p; END; $function$;
        ALTER FUNCTION public.ceva(jsonb) SET search_path = public, pg_temp;
    """
    assert not incalca_regula(sql)


def test_ALTER_INAINTE_de_definitie_NU_acopera():
    """Defectul real, în miniatură: exact ordinea 042 -> 048.

    Un `ALTER` care precede `CREATE OR REPLACE` e șters de el. O gardă care ar
    verifica doar PREZENȚA, nu ordinea, ar declara conformă chiar migrarea care
    reintroduce defectul."""
    sql = """
        ALTER FUNCTION public.ceva(jsonb) SET search_path = public, pg_temp;
        CREATE OR REPLACE FUNCTION ceva(p jsonb) RETURNS jsonb
        LANGUAGE plpgsql AS $function$ BEGIN RETURN p; END; $function$;
    """
    assert functii_neacoperite(sql) == ["ceva"], (
        "garda acceptă un ALTER anulat de CREATE-ul care îl urmează"
    )


def test_search_path_din_CORPUL_altei_functii_nu_acopera():
    """A doua funcție își setează calea; prima nu. Tăietura la `AS $` e tot ce
    împiedică garda să creadă că una o acoperă pe cealaltă."""
    sql = """
        CREATE OR REPLACE FUNCTION prima(p jsonb) RETURNS jsonb
        LANGUAGE plpgsql AS $function$ BEGIN RETURN p; END; $function$;
        CREATE OR REPLACE FUNCTION a_doua(p jsonb) RETURNS jsonb
        LANGUAGE plpgsql
        SET search_path = public, pg_temp
        AS $function$ BEGIN RETURN p; END; $function$;
    """
    assert functii_neacoperite(sql) == ["prima"]


def test_search_path_din_COMENTARIU_nu_pacaleste_garda():
    """Contraponderea obligatorie. Docstring-ul acestui fișier conține de mai
    multe ori `SET search_path`; o gardă pe text brut ar trece după ștergerea
    instrucțiunii reale."""
    sql = """
        -- SET search_path = public, pg_temp;   <- doar explicație
        /* ALTER FUNCTION ceva(jsonb) SET search_path = public, pg_temp; */
        CREATE OR REPLACE FUNCTION ceva(p jsonb) RETURNS jsonb
        LANGUAGE plpgsql AS $function$ BEGIN RETURN p; END; $function$;
    """
    assert functii_neacoperite(sql) == ["ceva"], (
        "garda s-a lăsat păcălită de un comentariu"
    )


def test_create_function_din_COMENTARIU_nu_declanseaza_fals():
    """Simetric: o definiție comentată nu e o redefinire."""
    sql = "-- CREATE OR REPLACE FUNCTION exemplu_din_documentatie() ...;"
    assert functii_redefinite(sql) == []
    assert not incalca_regula(sql)


def test_o_migrare_fara_nicio_functie_trece():
    """Majoritatea migrărilor. Garda nu are voie să le coloreze roșu."""
    sql = "CREATE TABLE IF NOT EXISTS ceva (id BIGINT PRIMARY KEY);"
    assert functii_redefinite(sql) == []
    assert not incalca_regula(sql)


def test_mai_multe_functii_neacoperite_sunt_raportate_TOATE():
    """Raportul trebuie să le numească pe toate, nu doar pe prima — altfel
    repararea devine iterativă și una poate rămâne în urmă."""
    sql = """
        CREATE OR REPLACE FUNCTION una(p jsonb) RETURNS jsonb
        LANGUAGE plpgsql AS $function$ BEGIN RETURN p; END; $function$;
        CREATE OR REPLACE FUNCTION alta(p jsonb) RETURNS jsonb
        LANGUAGE plpgsql AS $function$ BEGIN RETURN p; END; $function$;
    """
    assert functii_neacoperite(sql) == ["una", "alta"]


# ════════════════════════════════════════════════════════════════════════════
# Ancore — ca garda să nu poată fi redusă la tăcere fără să cadă
# ════════════════════════════════════════════════════════════════════════════

def test_pragul_nu_poate_fi_ridicat_ca_sa_taca():
    """Pragul poate COBORÎ (mai strict), niciodată urca.

    Lecția e împrumutată, nu redescoperită: prima versiune a gărzii de `GRANT`
    cerea `PRAG == max(migrări) + 1`, ceea ce ar fi scos fiecare migrare nouă
    de sub verificare chiar în clipa adăugării ei. Ancora corectă e un FAPT
    ISTORIC — aici, ultima migrare care a șters setarea."""
    assert PRAG_SEARCH_PATH_OBLIGATORIU <= ULTIMA_MIGRARE_CARE_A_PIERDUT_SETAREA + 1, (
        f"pragul a fost ridicat la {PRAG_SEARCH_PATH_OBLIGATORIU}. Migrările "
        f"{ULTIMA_MIGRARE_CARE_A_PIERDUT_SETAREA + 1:03d}+ trebuie verificate. "
        f"Pragul se coboară dacă se vrea mai strict — nu se urcă pentru a "
        f"reduce garda la tăcere."
    )


def test_ancora_istorica_corespunde_unui_fisier_real():
    numere = [n for n, _ in _migrari_numerotate()]
    assert numere, "niciun fișier de migrare numerotat găsit"
    assert ULTIMA_MIGRARE_CARE_A_PIERDUT_SETAREA in numere, (
        f"migrarea {ULTIMA_MIGRARE_CARE_A_PIERDUT_SETAREA:03d} nu mai există — "
        f"ancora istorică a pragului nu mai corespunde realității"
    )
