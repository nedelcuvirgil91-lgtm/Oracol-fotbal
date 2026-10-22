"""[2026-10-22] `Sabah FC` si `Sabah Baku` sunt acelasi club.

Flashscore a REDENUMIT clubul: acelasi id stabil `fNGcxbyr`, dar slug-ul s-a
schimbat (`sabah-baku` -> `sabah-fc`). Deci NU e decoratie de sufix de tara —
e o redenumire reala la provider, prinsa PROSPECTIV de detectorul ADR-078 cu
13 zile inainte de meciul Viking - Sabah (UCL, 4 nov 2026).

DE CE E GRAV FARA ALIAS, masurat pe productie inainte de reparatie:
  - `Sabah Baku`: 9 meciuri, lant ELO pana la 1579
  - `Sabah FC`:   1 rand — exact meciul VIITOR din 4 noiembrie
`get_latest_team_elo("Sabah FC")` nu gasea nimic, deci ELO-ul real era
INVIZIBIL la predictie, iar forma Level DB (3 meciuri sub acel nume) esua.

Garzile de aici acopera trei lucruri diferite:
  1. aliasul rezolva, in ambele sensuri utile;
  2. `Sabah Baku` ramane canonicul (NU forma noua a providerului) — acolo e
     lantul ELO;
  3. omonimul malaezian e consemnat explicit, ca sa nu fie unit din greseala
     la o extindere viitoare (tiparul `Zalgiris` / `Kauno Zalgiris`).
"""
from __future__ import annotations

import ast
from pathlib import Path

import mappings as m

RADACINA = Path(__file__).resolve().parent.parent


# ──────────────────────────────────────────────────────────────────────
# 1. Aliasul rezolva
# ──────────────────────────────────────────────────────────────────────

def test_sabah_fc_se_rezolva_la_canonicul_cu_lantul_ELO():
    """Defectul original: `Sabah FC` trecea neschimbat, deci clubul traia ca
    a doua identitate, cu ELO invizibil pe meciul din 4 noiembrie."""
    assert m.normalize_team_name("Sabah FC") == "Sabah Baku"


def test_canonicul_ramane_stabil():
    assert m.normalize_team_name("Sabah Baku") == "Sabah Baku"


def test_rezolvarea_e_insensibila_la_majuscule():
    """`ALIAS_TO_CANONICAL` e cheiat pe `.lower()` — un provider care scrie
    altfel nu trebuie sa recreeze a doua identitate."""
    for varianta in ("sabah fc", "SABAH FC", "Sabah fc"):
        assert m.normalize_team_name(varianta) == "Sabah Baku"


def test_canonicul_NU_e_forma_noua_a_providerului():
    """Decizie explicita, nu intamplare: Flashscore scrie azi `Sabah FC`, dar
    canonicul ramane `Sabah Baku`, fiindca acolo sunt cele 9 meciuri si lantul
    ELO. Stratul de alias exista exact ca forma unui provider sa nu dicteze
    vocabularul stocat (ADR-058). O inversare ar cere rescrierea a 9 randuri
    plus lantul ELO, care oricum nu se recalculeaza retroactiv (Salzburg)."""
    assert "Sabah Baku" in m.TEAM_ALIASES
    assert "Sabah FC" not in m.TEAM_ALIASES
    assert "Sabah FC" in m.TEAM_ALIASES["Sabah Baku"]


def test_ambele_etichete_duc_la_ACELASI_canonic():
    """Proprietatea care conteaza de fapt — nu ca fiecare se rezolva, ci ca
    se rezolva la acelasi lucru. Un lant ELO despicat e exact esecul ei."""
    assert m.normalize_team_name("Sabah FC") == m.normalize_team_name("Sabah Baku")


# ──────────────────────────────────────────────────────────────────────
# 2. Omonimul malaezian — consemnat, nu reparat (nu e nimic de reparat azi)
# ──────────────────────────────────────────────────────────────────────

def test_omonimul_malaezian_e_documentat_langa_alias():
    """⚠️ Exista si un `Sabah FC` in MALAYSIA, club complet DIFERIT. Malaysia
    Super League nu e urmarita azi, deci riscul e zero — dar daca se adauga
    vreodata, aliasul asta ar rezolva TACIT clubul malaezian la cel azer.

    Garda nu poate impiedica asta (nu exista azi niciun semnal de tara in
    `normalize_team_name`). Ce poate face: sa garanteze ca avertismentul
    exista langa alias, ca cine adauga liga sa-l vada. Acelasi tipar ca
    `Zalgiris` (Vilnius) / `Kauno Zalgiris` (Kaunas).

    GARDA SLABA PRIN NATURA, si o spun aici ca sa nu fie citita ca mai mult
    decat e: verifica un COMENTARIU. Garda care chiar tine e cea de mai jos,
    comportamentala (`test_malaysia_nu_e_urmarita_deci_riscul_e_zero_AZI`).

    [INTARITA dupa o mutatie care A TRECUT] Prima versiune cauta doar cuvantul
    `MALAYSIA` — si a trecut cand am sters avertismentul, fiindca cuvantul
    supravietuia in fraza urmatoare („Malaysia Super League NU e urmarita").
    Avertismentul era eviscerat, cuvantul ramasese. Aceeasi clasa ca garda
    `pipefail` care isi gasea propriul comentariu. Acum cer titlul
    avertismentului SI cuvantul — stergerea oricaruia o doboara."""
    sursa = (RADACINA / "mappings.py").read_text(encoding="utf-8")
    i = sursa.index('"Sabah Baku"')
    context = sursa[max(0, i - 1400):i].upper()
    for marcaj in ("OMONIM REAL", "MALAYSIA"):
        assert marcaj in context, (
            f"{marcaj!r} a disparut din avertismentul de langa aliasul `Sabah FC` "
            "— cine adauga Malaysia Super League nu mai are cum sa-l vada"
        )


def test_malaysia_nu_e_urmarita_deci_riscul_e_zero_AZI():
    """Contrapondere la testul de mai sus: daca Malaysia intra vreodata in
    competitiile urmarite, acest test cade si forteaza redeschiderea
    discutiei, in loc ca aliasul sa uneasca tacit doua cluburi."""
    competitii = " ".join(m.LEAGUE_PROVIDERS.keys()).lower()
    assert "malaysia" not in competitii, (
        "Malaysia e acum urmarita — `Sabah FC` devine ambiguu intre clubul "
        "azer si cel malaezian. Vezi comentariul de langa alias in mappings.py"
    )


# ──────────────────────────────────────────────────────────────────────
# 3. Garzi structurale pe dictionarul de alias (capcana Salzburg)
# ──────────────────────────────────────────────────────────────────────

def test_Sabah_Baku_apare_o_SINGURA_data_ca_cheie():
    """Capcana Salzburg: Python pastreaza ULTIMA definitie a unei chei
    duplicate, deci o a doua `"Sabah Baku": []` ar sterge TACIT aliasul, fara
    nicio eroare si fara ca vreun test de rezolvare sa cada neaparat.
    Verificat prin AST, pe sursa — `dict`-ul incarcat nu mai contine dovada."""
    arbore = ast.parse((RADACINA / "mappings.py").read_text(encoding="utf-8"))
    aparitii = 0
    for nod in ast.walk(arbore):
        if isinstance(nod, ast.Dict):
            for cheie in nod.keys:
                if isinstance(cheie, ast.Constant) and cheie.value == "Sabah Baku":
                    aparitii += 1
    assert aparitii == 1, f"`Sabah Baku` apare de {aparitii} ori ca cheie, nu o data"


def test_aliasul_nu_se_ciocneste_cu_alt_canonic():
    """`Sabah FC` nu are voie sa fie deja alias al altui club, sau canonic el
    insusi — ambele ar face rezolvarea sa depinda de ordinea de constructie a
    lui `ALIAS_TO_CANONICAL`, adica de un detaliu de implementare."""
    proprietari = [canonic for canonic, aliasuri in m.TEAM_ALIASES.items()
                   if "Sabah FC" in aliasuri or canonic == "Sabah FC"]
    assert proprietari == ["Sabah Baku"], f"`Sabah FC` revendicat de {proprietari}"
