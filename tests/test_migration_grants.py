"""Gardă — orice tabelă nouă primește `GRANT ... TO service_role`.

DE CE EXISTĂ, cu dată. Supabase oprește pe **2026-10-30** acordarea AUTOMATĂ de
acces Data API pentru tabelele noi din `public`. Tabelele existente nu sunt
afectate. Măsurat pe 20 octombrie, înainte de a scrie garda: **zero din cele 60
de migrări** conțineau vreun `GRANT` — toate se bazau pe acordarea automată,
inclusiv 057, creată cu o zi înainte.

CE SE RUPE FĂRĂ EA. Aplicația vorbește prin PostgREST ca `service_role`
(`SUPABASE_SECRET_KEY`), iar anunțul cere `GRANT` explicit INCLUSIV pentru
`service_role`. O tabelă creată după 30 oct fără grant nu eșuează la creare —
eșuează la prima SCRIERE din `night_sync`, cu `permission denied`. Nu avem
staging, deci nu există unde să se vadă mai devreme. Exact genul de defect pe
care o gardă de cod îl prinde cu săptămâni înainte.

RLS NU E UN GRANT — două straturi diferite. Migrările noastre scriu
`ENABLE ROW LEVEL SECURITY` + `CREATE POLICY ... TO service_role` și se opresc
acolo; politica spune ce RÂNDURI vede un rol care deja are voie la tabelă.

DE CE UN PRAG, NU O LISTĂ. Cele 57 de migrări existente nu pot fi reparate
retroactiv — sunt evidența a ce s-a RULAT, nu documente vii, iar tabelele lor au
deja grant-urile de la Supabase. Garda se aplică de la `PRAG_GRANT_OBLIGATORIU`
în sus. O listă de excepții s-ar învechi; un prag nu, iar
`test_pragul_nu_poate_fi_ridicat_ca_sa_taca` îl ancorează de realitate.

NEVACUITATE. Azi nu există nicio migrare peste prag, deci verificarea principală
n-ar demonstra nimic singură — capcana trecerii VIDE, plătită deja de două ori
în proiect (clientul fals fără plafon implicit, 14 oct; cele două gărzi șterse
tăcut prin reutilizare de nume, tot 14 oct). De aceea logica e exercitată aici
pe un caz SINTETIC și pe ȘABLONUL real, nu doar pe fișierele existente.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

RADACINA = Path(__file__).resolve().parent.parent
DIR_MIGRARI = RADACINA / "database" / "migrations"
SABLON = DIR_MIGRARI / "_SABLON_tabela_noua.sql"

# Prima migrare care trebuie să conțină GRANT. Cele de sub prag au fost create
# cât acordarea automată încă exista; tabelele lor au deja privilegiile pe
# producție (verificat 20 oct: `odds_history`, `match_history` și
# `flashscore_team_identity` au toate SELECT/INSERT/UPDATE/DELETE pentru
# `service_role`).
PRAG_GRANT_OBLIGATORIU = 58

ROL_OBLIGATORIU = "service_role"

_RE_NUMAR = re.compile(r"^(\d{3})_")
# `CREATE TABLE [IF NOT EXISTS] nume` și `CREATE TABLE nume AS ...` (tiparul de
# backup, care a produs singura tabelă fără RLS din proiect).
_RE_CREATE_TABLE = re.compile(
    r"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    r"(?:public\.)?[\"']?([A-Za-z_][A-Za-z0-9_]*)[\"']?",
    re.IGNORECASE,
)
_RE_GRANT = re.compile(
    r"\bGRANT\b[\s\S]{0,400}?\bON\b[\s\S]{0,200}?\bTO\b([^;]*)", re.IGNORECASE
)


def doar_cod(sql: str) -> str:
    """Elimină comentariile ÎNAINTE de orice verificare.

    Fără asta, garda s-ar găsi pe sine: șablonul explică în comentarii, pe
    larg, de ce e nevoie de `GRANT`, deci o căutare pe text brut ar trece chiar
    după ștergerea instrucțiunii reale. A treia instanță a clasei în proiect,
    după `pipefail` (27 aug) și docstring-ul care-și satisfăcea propria gardă
    (14 oct). Verificată prin mutație, nu presupusă."""
    fara_bloc = re.sub(r"/\*[\s\S]*?\*/", " ", sql)
    return "\n".join(
        linie.split("--", 1)[0] for linie in fara_bloc.splitlines()
    )


def tabele_create(sql: str) -> list[str]:
    return _RE_CREATE_TABLE.findall(doar_cod(sql))


def roluri_cu_grant(sql: str) -> set[str]:
    roluri: set[str] = set()
    for tinta in _RE_GRANT.findall(doar_cod(sql)):
        for bucata in tinta.split(","):
            nume = bucata.strip().strip('"').strip()
            if nume:
                roluri.add(nume.lower())
    return roluri


def incalca_regula(sql: str) -> bool:
    """True dacă migrarea creează o tabelă dar nu acordă rolului de serviciu."""
    return bool(tabele_create(sql)) and ROL_OBLIGATORIU not in roluri_cu_grant(sql)


def _migrari_numerotate() -> list[tuple[int, Path]]:
    gasite: list[tuple[int, Path]] = []
    for cale in sorted(DIR_MIGRARI.glob("*.sql")):
        potrivire = _RE_NUMAR.match(cale.name)
        if potrivire:
            gasite.append((int(potrivire.group(1)), cale))
    return gasite


# ════════════════════════════════════════════════════════════════════════════
# Verificarea principală — azi nu are ce să prindă, și e în regulă
# ════════════════════════════════════════════════════════════════════════════

def test_migrarile_de_la_prag_in_sus_acorda_service_role():
    """Garda centrală. Cade cu numele fișierului și al tabelei."""
    lipsa = []
    for numar, cale in _migrari_numerotate():
        if numar < PRAG_GRANT_OBLIGATORIU:
            continue
        sql = cale.read_text(encoding="utf-8")
        if incalca_regula(sql):
            lipsa.append(f"{cale.name} — creează {tabele_create(sql)}, "
                         f"dar nu acordă nimic lui `{ROL_OBLIGATORIU}`")
    assert not lipsa, (
        "Tabelă nouă fără `GRANT`. De la 2026-10-30, Supabase nu mai acordă "
        "automat acces Data API, iar prima scriere din night_sync va întoarce "
        "`permission denied`. Vezi `database/migrations/_SABLON_tabela_noua.sql`:\n  "
        + "\n  ".join(lipsa)
    )


# ════════════════════════════════════════════════════════════════════════════
# Nevacuitate — logica se exercită chiar dacă niciun fișier real n-o atinge
# ════════════════════════════════════════════════════════════════════════════

def test_sablonul_exista():
    """Dacă șablonul dispare, regula rămâne fără formă de copiat."""
    assert SABLON.is_file(), f"lipsește {SABLON.name}"


def test_sablonul_TRECE_propria_regula():
    """Șablonul e singurul artefact REAL care exercită regula azi.

    Dacă cineva îl rescrie și scoate `GRANT`-ul, testul cade — deci forma de
    copiat nu poate diverge tăcut de gardă."""
    sql = SABLON.read_text(encoding="utf-8")
    assert tabele_create(sql), "șablonul nu mai creează nicio tabelă"
    assert not incalca_regula(sql), "șablonul însuși încalcă regula pe care o predă"


def test_o_migrare_sintetica_FARA_grant_e_prinsa():
    """Cazul pe care garda îl există să-l prindă, scris explicit.

    Fără testul ăsta, `test_migrarile_de_la_prag_in_sus` ar trece azi pe un set
    GOL și n-ar dovedi nimic despre logică."""
    sql = """
        CREATE TABLE IF NOT EXISTS ceva_nou (id BIGINT PRIMARY KEY);
        ALTER TABLE ceva_nou ENABLE ROW LEVEL SECURITY;
        CREATE POLICY p ON ceva_nou FOR ALL TO service_role USING (true);
    """
    assert tabele_create(sql) == ["ceva_nou"]
    assert incalca_regula(sql), "politica RLS a fost confundată cu un GRANT"


def test_o_migrare_sintetica_CU_grant_trece():
    sql = """
        CREATE TABLE IF NOT EXISTS ceva_nou (id BIGINT PRIMARY KEY);
        GRANT SELECT, INSERT, UPDATE, DELETE ON ceva_nou TO service_role;
    """
    assert not incalca_regula(sql)


def test_grant_catre_alt_rol_NU_satisface_regula():
    """`anon` nu ține locul lui `service_role` — aplicația scrie prin al doilea."""
    sql = """
        CREATE TABLE IF NOT EXISTS ceva_nou (id BIGINT PRIMARY KEY);
        GRANT SELECT ON ceva_nou TO anon;
    """
    assert incalca_regula(sql)


def test_grantul_din_COMENTARIU_nu_pacaleste_garda():
    """Contraponderea care contează cel mai mult.

    Șablonul explică `GRANT` pe larg în comentarii. O gardă care caută text
    brut ar trece chiar după ștergerea instrucțiunii reale — exact cum garda
    `pipefail` își găsea propriul comentariu pe 27 august."""
    sql = """
        -- GRANT SELECT ON ceva_nou TO service_role;  <- doar explicație
        /* GRANT ALL ON ceva_nou TO service_role; */
        CREATE TABLE IF NOT EXISTS ceva_nou (id BIGINT PRIMARY KEY);
    """
    assert incalca_regula(sql), "garda s-a lăsat păcălită de un comentariu"


def test_create_table_din_COMENTARIU_nu_declanseaza_fals():
    """Simetric: un `CREATE TABLE` comentat nu e o tabelă nouă."""
    sql = "-- CREATE TABLE IF NOT EXISTS exemplu_din_documentatie (id INT);"
    assert tabele_create(sql) == []
    assert not incalca_regula(sql)


def test_prinde_si_tiparul_CREATE_TABLE_AS():
    """Tiparul de backup. Tocmai el a produs singura tabelă fără RLS din
    proiect (`flashscore_match_context_retention_backup_20260826`), fiindcă
    `CREATE TABLE AS` nu moștenește nimic de la sursă."""
    sql = "CREATE TABLE backup_ceva AS SELECT * FROM ceva;"
    assert tabele_create(sql) == ["backup_ceva"]
    assert incalca_regula(sql)


# ════════════════════════════════════════════════════════════════════════════
# Ancore — ca garda să nu poată fi redusă la tăcere fără să cadă
# ════════════════════════════════════════════════════════════════════════════

# Ultima migrare existentă în ziua în care s-a scris garda (2026-10-20), deci
# ultima creată cât acordarea automată încă funcționa. Pragul e ANCORAT
# ISTORIC de ea și nu are voie să urce peste.
ULTIMA_MIGRARE_INAINTE_DE_REGULA = 57


def test_pragul_nu_poate_fi_ridicat_ca_sa_taca():
    """Pragul poate COBORÎ (mai strict), niciodată urca.

    PRIMA VERSIUNE A ACESTUI TEST ERA GREȘITĂ, și a căzut la propria mutație:
    cerea `PRAG == max(migrări) + 1`, ceea ce e exact invers. Cu regula aia,
    adăugarea unei migrări 058 — chiar perfect conformă — făcea testul să
    pice, iar „reparația" evidentă (ridică pragul la 59) ar fi scos tocmai
    migrarea nouă de sub verificare. Garda s-ar fi auto-dezactivat la fiecare
    folosire, trecând mereu pe un set gol.

    Forma corectă e o ancoră ISTORICĂ: cutoff-ul e ziua în care Supabase a
    schimbat implicitul, nu „ultimul fișier din director"."""
    assert PRAG_GRANT_OBLIGATORIU <= ULTIMA_MIGRARE_INAINTE_DE_REGULA + 1, (
        f"pragul a fost ridicat la {PRAG_GRANT_OBLIGATORIU}. Migrările "
        f"{ULTIMA_MIGRARE_INAINTE_DE_REGULA + 1:03d}+ sunt create DUPĂ "
        f"2026-10-30 și trebuie verificate. Pragul se coboară dacă se vrea "
        f"mai strict — nu se urcă pentru a reduce garda la tăcere."
    )


def test_ancora_istorica_corespunde_unui_fisier_real():
    """Dacă migrările se renumerotează, ancora devine o cifră fără acoperire
    și ar trebui rescrisă conștient, nu lăsată să alunece."""
    numere = [n for n, _ in _migrari_numerotate()]
    assert numere, "niciun fișier de migrare numerotat găsit"
    assert ULTIMA_MIGRARE_INAINTE_DE_REGULA in numere, (
        f"migrarea {ULTIMA_MIGRARE_INAINTE_DE_REGULA:03d} nu mai există — "
        f"ancora istorică a pragului nu mai corespunde realității"
    )


def test_parserul_vede_tabele_in_migrarile_REALE():
    """Contrapondere de orbire: dacă regexul se strică, totul ar trece vid.

    Verifică pe fișiere reale, de sub prag, că detectarea de `CREATE TABLE`
    chiar funcționează — nu doar pe SQL-ul sintetic scris de mine."""
    cu_tabele = [cale.name for _, cale in _migrari_numerotate()
                 if tabele_create(cale.read_text(encoding="utf-8"))]
    assert len(cu_tabele) >= 10, (
        f"parserul găsește tabele în doar {len(cu_tabele)} migrări reale — "
        f"probabil s-a rupt regexul, iar garda ar trece vid"
    )


@pytest.mark.parametrize("fisier", ["001_odds_history.sql"])
def test_precedentul_de_stil_e_sub_prag_si_ramane_neatins(fisier):
    """`001` e citat ca precedent de toate migrările. NU se editează retroactiv
    ca să adauge GRANT: e evidența a ce s-a rulat, iar tabela lui are deja
    privilegiile pe producție. Forma de copiat e șablonul, nu el."""
    cale = DIR_MIGRARI / fisier
    assert cale.is_file()
    numar = int(_RE_NUMAR.match(cale.name).group(1))
    assert numar < PRAG_GRANT_OBLIGATORIU
