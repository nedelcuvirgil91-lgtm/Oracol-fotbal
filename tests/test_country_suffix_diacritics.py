"""Dezbrăcarea sufixului de țară era oarbă la diacritice (reparat 2026-10-21).

DEFECTUL. `normalize_team_name` caută forma dezbrăcată de sufix în
`ALIAS_TO_CANONICAL`, dar o caută **unicode-normalizată** (diacriticele
eliminate) — în timp ce alias-urile sunt înregistrate **cu** diacritic, 52 din
977. Deci:

    'fc bayern münchen'  în ALIAS_TO_CANONICAL -> True
    'fc bayern munchen'  în ALIAS_TO_CANONICAL -> False   (ce căuta codul)

`normalize_team_name("FC Bayern München")` funcționa, prin lookup-ul direct.
`normalize_team_name("FC Bayern München (GER)")` se întorcea NESCHIMBAT, deci
clubul trăia ca a doua identitate.

AMPLOAREA, măsurată pe producție — nu estimată: exact **3 cluburi** afectate
(toate cu diacritic), **30 de rânduri** `match_history` duplicate, toate
Champions League. E cauza rădăcină a clasei pe care D-13 o descria drept
„invizibilă indexului unic PRIN CONSTRUCȚIE, fiindcă etichetele diferă". Nu era
prin construcție.

CE A PRINS MĂSURAREA, ȘI RECITIREA NU AR FI PRINS. Prima versiune a reparației
renormaliza forma dezbrăcată și o întorcea ca IEȘIRE. Schimba **toate 53** de
etichete cu sufix, nu 3: `TNS (WAL)` -> `TNS`. Asta încalcă ADR-058 §2.3 —
*„sufixul de tara e strict CHEIE DE CAUTARE, niciodata iesire"* — adică exact
regula scrisă în comentariul de deasupra codului reparat. Ar fi redenumit tăcut
50 de cluburi. De aceea jumătate din testele de aici sunt CONTRAPONDERI: nu
verifică doar că cele 3 se repară, ci că celelalte 50 **NU** se ating.
"""
from __future__ import annotations

import unicodedata

import pytest

import mappings as m


# Cele trei cluburi reale afectate, cu eticheta EXACTĂ din `match_history`
# (2026-10-21) și forma canonică spre care trebuie să se rezolve.
AFECTATE = [
    ("FC Bayern München (GER)", "Bayern Munich"),
    ("Club Atlético de Madrid (ESP)", "Atletico Madrid"),
    ("ŠK Slovan Bratislava (SVK)", "Slovan Bratislava"),
]

# Etichete cu sufix ale unor cluburi care NU au formă canonică cunoscută. Se
# întorc NESCHIMBATE — sufixul e cheie de căutare, nu ieșire.
FARA_GEAMAN = [
    "TNS (WAL)", "Klaksvik (FAI)", "Din. Minsk (BLR)", "Tre Fiori (SAN)",
    "Zalgiris (LTU)", "Vestri (ICE)", "Paks (HUN)", "UNA Strassen (LUX)",
    "Zeleznicar Pancevo (SRB)", "LNZ Cherkasy (UKR)",
]


# ════════════════════════════════════════════════════════════════════════════
# Reparația
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("eticheta,canonic", AFECTATE)
def test_sufixul_se_dezbraca_si_pentru_nume_cu_diacritice(eticheta, canonic):
    """Garda centrală. Fiecare dintre cele trei producea 10-14 rânduri
    duplicate în `match_history`."""
    assert m.normalize_team_name(eticheta) == canonic


@pytest.mark.parametrize("eticheta,canonic", AFECTATE)
def test_forma_fara_sufix_functiona_deja(eticheta, canonic):
    """Contraponderea care localizează defectul: forma NEsufixată se rezolva
    corect și înainte. Deci problema era strict în calea de dezbrăcare, nu în
    dicționarul de alias-uri."""
    fara_sufix = m._COUNTRY_SUFFIX_RE.sub("", eticheta).strip()
    assert fara_sufix != eticheta, "fixtura e greșită — eticheta n-are sufix"
    assert m.normalize_team_name(fara_sufix) == canonic


def test_aliasul_e_inregistrat_CU_diacritic_asta_e_mecanismul():
    """Documentează cauza exactă, nu doar simptomul. Dacă vreodată cineva
    normalizează cheile dicționarului, testul ăsta cade și arată că reparația
    de aici a devenit inutilă (nu greșită — inutilă)."""
    assert "fc bayern münchen" in m.ALIAS_TO_CANONICAL
    assert "fc bayern munchen" not in m.ALIAS_TO_CANONICAL, (
        "cheia fără diacritice a apărut în dicționar — mecanismul descris de "
        "acest fișier s-a schimbat, reparația trebuie reevaluată")


# ════════════════════════════════════════════════════════════════════════════
# CONTRAPONDERI — ADR-058 §2.3: sufixul nu devine niciodată ieșire
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("eticheta", FARA_GEAMAN)
def test_sufixul_NU_devine_iesire_cand_baza_e_necunoscuta(eticheta):
    """Exact ce greșea prima versiune a reparației. `TNS (WAL)` NU devine
    `TNS`: o formă dezbrăcată necunoscută nu e un nume canonic, iar a o
    întoarce ar inventa o identitate."""
    assert m.normalize_team_name(eticheta) == eticheta


def test_raza_de_actiune_e_EXACT_trei_pe_toate_etichetele_reale():
    """Măsurătoarea de pe producție, înghețată ca test.

    Toate cele 53 de etichete cu sufix de țară active în `match_history` la
    2026-10-21. Reparația trebuie să schimbe EXACT trei. Dacă o versiune
    viitoare schimbă mai multe, raza de acțiune a crescut tăcut — iar asta e
    defectul primei mele variante."""
    toate = [e for e, _ in AFECTATE] + FARA_GEAMAN + [
        "Larne (NIR)", "Vikingur Reykjavik (ICE)", "Dinamo City (ALB)",
        "Drita (KOS)", "Hapoel Tel Aviv (ISR)", "Hradec Kralove (CZE)",
        "Partizan (SRB)", "ML Vitebsk (BLR)", "Beitar Jerusalem (ISR)",
        "Flora (EST)", "Gyor (HUN)", "NSI Runavik (FAI)", "RFS (LAT)",
        "Shkendija (MKD)", "Valur (ICE)", "Aluminij (SLO)", "Auda (LAT)",
        "CSKA 1948 Sofia (BUL)", "Debrecen (HUN)", "Dun. Streda (SVK)",
        "Noah (ARM)", "Paide (EST)", "Sutjeska (MNE)", "Tobol (KAZ)",
        "Vojvodina (SRB)", "Zilina (SVK)", "AEK Larnaca (CYP)",
        "Alashkert (ARM)", "BATE (BLR)", "Bissen (LUX)", "Bravo (SLO)",
        "Coleraine (NIR)", "FC Ballkani (KOS)", "FK Liepaja (LAT)",
        "Floriana (MLT)", "Koper (SLO)", "Malisheva (KOS)", "Petrocub (MDA)",
        "Vardar (MKD)", "Zrinjski (BIH)",
    ]
    assert len(toate) == 53, f"fixtura s-a schimbat: {len(toate)} etichete"
    schimbate = [e for e in toate if m.normalize_team_name(e) != e]
    assert sorted(schimbate) == sorted(e for e, _ in AFECTATE), (
        "raza de acțiune nu mai e cea măsurată — schimbate: " + repr(schimbate))


@pytest.mark.parametrize("nume", [
    "Bayern Munich", "Inter Milan", "Celtic", "Paris FC", "Dinamo Zagreb",
    "Salzburg", "Red Bull Salzburg", "Levski Sofia", "Zalgiris",
    "Kauno Zalgiris", "Atletico Madrid", "Slovan Bratislava",
])
def test_niciun_nume_NESUFIXAT_nu_e_atins(nume):
    """Reparația stă într-o ramură gardată de „are sufix de țară", deci nu
    poate atinge un nume nesufixat. Verificat, nu presupus."""
    inainte = m.normalize_team_name(nume)
    assert m.normalize_team_name(nume) == inainte
    assert "(" not in inainte, "un nume canonic nu conține sufix de țară"


def test_Zalgiris_si_Kauno_Zalgiris_ramAn_cluburi_DIFERITE():
    """Gardă explicită din D-13: `Zalgiris` (Vilnius) și `Kauno Zalgiris`
    (Kaunas) sunt cluburi diferite. Reparația nu are voie să le apropie."""
    assert m.normalize_team_name("Zalgiris") != m.normalize_team_name("Kauno Zalgiris")
    assert m.normalize_team_name("Zalgiris (LTU)") == "Zalgiris (LTU)"


def test_nu_arunca_pe_intrari_degenerate():
    for intrare in ("", "   ", "(GER)", "FC (GER)", "München"):
        m.normalize_team_name(intrare)  # nu trebuie să ridice


# ════════════════════════════════════════════════════════════════════════════
# Expunerea clasei — cât de larg e riscul, ca să nu fie reestimat din memorie
# ════════════════════════════════════════════════════════════════════════════

def test_cate_aliasuri_au_diacritice_marimea_clasei():
    """52 din 977 la reparare. Nu e o aserțiune de egalitate (dicționarul
    crește legitim), ci o gardă că clasa NU e vidă — altfel testele de mai sus
    ar putea trece fără să existe niciun nume cu diacritic de protejat."""
    def are_diacritic(s: str) -> bool:
        return any(unicodedata.category(c) == "Mn"
                   for c in unicodedata.normalize("NFD", s))

    cu_diacritic = [k for k in m.ALIAS_TO_CANONICAL if are_diacritic(k)]
    assert len(cu_diacritic) >= 40, (
        f"doar {len(cu_diacritic)} alias-uri cu diacritice — clasa s-a "
        "schimbat substanțial, reparația trebuie reevaluată")


def test_fixtura_fara_geaman_are_baza_GENUIN_necunoscuta():
    """Garda care previne repetarea erorii din `test_team_identity_invariants`.

    Acolo, `FC Bayern München (GER)` fusese pus în lista „fără bază cunoscută"
    pentru că resolverul îl întorcea neschimbat — dar motivul era defectul
    reparat aici, nu absența bazei. **O verificare făcută pe ieșirea codului
    defect a transformat bug-ul în specificație.**

    Testul ăsta cere dovada în DICȚIONAR, nu în ieșire: pentru fiecare nume din
    `FARA_GEAMAN`, baza dezbrăcată trebuie să fie genuin absentă din
    `ALIAS_TO_CANONICAL`. Dacă cineva adaugă mâine un alias pentru una din ele,
    testul cade și spune că fixtura trebuie mutată — nu că resolverul e stricat."""
    greșite = []
    for eticheta in FARA_GEAMAN:
        baza = m._COUNTRY_SUFFIX_RE.sub("", eticheta).strip().lower()
        if baza in m.ALIAS_TO_CANONICAL:
            greșite.append(f"{eticheta!r} (baza {baza!r} E un alias cunoscut)")
    assert not greșite, (
        "nume clasificate ca fiind fara geaman, dar care AU baza cunoscuta: "
        "fixtura e greșita, nu resolverul:\n  " + "\n  ".join(greșite))


@pytest.mark.parametrize("eticheta,canonic", AFECTATE)
def test_cele_afectate_au_baza_CUNOSCUTA_asta_le_distinge(eticheta, canonic):
    """Contraponderea celui de mai sus, pe cealaltă parte a graniței: cele trei
    reparate se distingeau de restul prin exact o proprietate verificabilă —
    baza lor ERA în dicționar tot timpul."""
    baza = m._COUNTRY_SUFFIX_RE.sub("", eticheta).strip().lower()
    assert baza in m.ALIAS_TO_CANONICAL, (
        f"baza {baza!r} nu e alias — atunci rezolvarea ar fi ghicire, iar "
        "reparația ar fi greșită")
