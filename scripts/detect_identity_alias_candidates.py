"""
================================================================================
FOOTBALL ORACLE — Detector de candidati pentru vocabular (categoria D3)
================================================================================
Module: scripts/detect_identity_alias_candidates.py

STRICT read-only. Nu scrie in Supabase. **Nu modifica NICIODATA `mappings.py`** —
propune candidati pentru review uman, atat. Vezi "De ce nu aplica automat".

--------------------------------------------------------------------------------
PROBLEMA (categoria D3)
--------------------------------------------------------------------------------
Reconcilierea (ADR-025 Faza 3+4) uneste doua randuri doar cand `match_key()` —
deci `normalize_team_name()` — le da aceeasi cheie. Exista insa perechi de nume
care desemneaza acelasi club dar pe care vocabularul actual NU le uneste:
'Almere City' (kaggle) si 'Almere City FC' (football-data). Pentru ele
`match_key()` difera, deci reconcilierea nu le-a putut vedea niciodata.

Consecinta, verificata live (2026-08-22): toate cele 68 de meciuri ale lui
Almere City exista de DOUA ori in setul live — aceeasi zi, acelasi scor, sub
doua nume. Nu e doar fragmentare de lant ELO: sunt meciuri DUPLICATE ramase in
setul de antrenare ML si in replay-ul ELO.

--------------------------------------------------------------------------------
DOVADA FOLOSITA (zero potrivire fuzzy)
--------------------------------------------------------------------------------
Istoria proiectului interzice potrivirea aproximativa: v1.2 a eliminat
prefix-matching-ul dupa 141 de fuziuni false ('Paris FC' -> 'Paris
Saint-Germain'). Detectorul NU compara siruri. Foloseste doua semnale factuale:

  POZITIV — doua randuri live, aceeasi (zi, liga, scor), in care exact O parte
    difera ca nume iar cealalta e identica la caracter. Acelasi meci, notat sub
    doua nume. Cu cat mai multe astfel de perechi, cu atat mai puternica dovada.

  VETO — daca cele doua nume apar vreodata ca ADVERSARI in acelasi meci, sunt
    cluburi DIFERITE: o echipa nu joaca niciodata cu ea insasi. Veto absolut,
    indiferent cate coincidente pozitive exista.

Vetoul nu e teoretic. Pe datele reale a eliminat exact cele 3 false pozitive
produse de semnalul pozitiv singur — 'FCSB'/'Sepsi OSK' (9+9 meciuri directe),
'CFR Cluj'/'Chindia Targoviste' (3+3), 'Din. Bucuresti'/'Farul Constanța'
(4+6) — pastrand toate perechile reale, care au zero meciuri directe.

--------------------------------------------------------------------------------
DE CE NU APLICA AUTOMAT
--------------------------------------------------------------------------------
Un alias nou schimba retroactiv identitatea unor randuri deja scrise. Acelasi
motiv pentru care bump-ul baseline-ului de drift e neautomat: dovada mecanica
spune "aceste doua nume se comporta ca acelasi club", nu "sunt acelasi club".
Ultima verificare — un club redenumit? doua echipe ale aceluiasi oras? o
eroare de date upstream? — ramane a omului. Iesirea e formatata ca sa fie
citita si aprobata, nu executata.

Utilizare:
    python scripts/detect_identity_alias_candidates.py
================================================================================
"""
from __future__ import annotations

import logging
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

BAR = "=" * 78


def find_candidates(rows: list[dict]) -> list[dict]:
    """Detectia completa, ca functie PURA peste randuri deja aduse.

    Testabila pe randuri sintetice, fara Supabase (`tests/
    test_detect_identity_alias_candidates.py`).

    Returneaza o lista de dict-uri, ordonata descrescator dupa taria dovezii.
    """
    # --- VETO: perechile care s-au infruntat vreodata ---------------------
    # Construit din TOATE randurile, nu doar cele cu rezultat: un meci viitor
    # deja programat intre A si B e la fel de concludent ca unul jucat.
    adversari: set[frozenset] = set()
    for r in rows:
        h, a = r.get("home_team"), r.get("away_team")
        if h and a and h != a:
            adversari.add(frozenset((h, a)))

    # --- POZITIV: acelasi meci sub doua nume ------------------------------
    # Grupare pe (zi, liga, scor) ca sa nu se compare tot cu tot. Cosurile
    # sunt mici, deci compararea in interiorul unui cos e ieftina.
    cosuri: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        if r.get("actual_result") is None:
            continue
        cheie = (r.get("kickoff_date"), r.get("league"),
                 r.get("actual_home_goals"), r.get("actual_away_goals"))
        cosuri[cheie].append(r)

    dovezi: dict[frozenset, list[tuple]] = defaultdict(list)
    for randuri in cosuri.values():
        if len(randuri) < 2:
            continue
        for i in range(len(randuri)):
            for j in range(i + 1, len(randuri)):
                a, b = randuri[i], randuri[j]
                ah, aa = a.get("home_team"), a.get("away_team")
                bh, ba = b.get("home_team"), b.get("away_team")
                if not all((ah, aa, bh, ba)):
                    continue
                if ah != bh and aa == ba:
                    nume_a, nume_b = ah, bh
                elif aa != ba and ah == bh:
                    nume_a, nume_b = aa, ba
                else:
                    continue
                dovezi[frozenset((nume_a, nume_b))].append((a.get("id"), b.get("id")))

    rezultat: list[dict] = []
    for pereche, perechi_randuri in dovezi.items():
        nume_a, nume_b = sorted(pereche)
        if pereche in adversari:
            rezultat.append({
                "nume_a": nume_a, "nume_b": nume_b,
                "perechi": len(perechi_randuri),
                "respins_veto": True,
                "exemple": perechi_randuri[:3],
            })
            continue
        rezultat.append({
            "nume_a": nume_a, "nume_b": nume_b,
            "perechi": len(perechi_randuri),
            "respins_veto": False,
            "exemple": perechi_randuri[:3],
        })

    rezultat.sort(key=lambda c: (c["respins_veto"], -c["perechi"], c["nume_a"]))
    return rezultat


def _fetch_rows(client) -> list[dict]:
    rows: list[dict] = []
    offset, page_size = 0, 1000
    while True:
        batch = (
            client.table("match_history")
            .select("id,home_team,away_team,kickoff_date,league,"
                    "actual_home_goals,actual_away_goals,actual_result")
            .is_("superseded_by", "null")
            .range(offset, offset + page_size - 1)
            .execute().data
        ) or []
        rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size
    return rows


def main() -> int:
    import supabase_client as sb

    if not sb.is_available():
        print("EROARE: Supabase indisponibil (SUPABASE_URL / SUPABASE_SECRET_KEY).")
        return 1

    from mappings import ALIAS_TO_CANONICAL, normalize_team_name

    print(BAR)
    print("  CANDIDATI DE VOCABULAR (D3) — propunere pentru review uman")
    print("  STRICT read-only. NU modifica mappings.py.")
    print(BAR)

    rows = _fetch_rows(sb.get_client())
    print(f"  Randuri live analizate : {len(rows)}")

    candidati = find_candidates(rows)
    acceptati = [c for c in candidati if not c["respins_veto"]]
    respinsi = [c for c in candidati if c["respins_veto"]]

    print(f"  Perechi cu dovada pozitiva : {len(candidati)}")
    print(f"  Respinse de veto (s-au infruntat) : {len(respinsi)}")
    print(f"  CANDIDATI DE APROBAT : {len(acceptati)}")
    print(BAR)

    canonice = set(ALIAS_TO_CANONICAL.values())
    total_randuri_duble = 0

    for c in acceptati:
        a, b = c["nume_a"], c["nume_b"]
        total_randuri_duble += c["perechi"]
        # Sugestie de canonic: daca EXACT unul din nume e deja o valoare
        # canonica in vocabular, el e alegerea evidenta. Daca ambele sau
        # niciunul, alegerea ramane explicit a omului — nu se ghiceste.
        a_can, b_can = a in canonice, b in canonice
        if a_can and not b_can:
            sugestie = f'"{a}": [..., "{b}"]'
        elif b_can and not a_can:
            sugestie = f'"{b}": [..., "{a}"]'
        else:
            sugestie = "AMBIGUU — alege canonicul manual"
        deja = "DEJA UNITE" if normalize_team_name(a) == normalize_team_name(b) else ""
        print(f"  [{c['perechi']:>3} perechi] {a!r}  <->  {b!r}   {deja}")
        print(f"       sugestie: {sugestie}")

    print(BAR)
    print(f"  Perechi de randuri duplicate implicate : {total_randuri_duble}")
    print(BAR)

    if respinsi:
        print("  RESPINSE DE VETO (s-au infruntat direct — cluburi diferite):")
        for c in respinsi:
            print(f"    [{c['perechi']:>3}] {c['nume_a']!r} vs {c['nume_b']!r}")
        print(BAR)

    print("  Nicio modificare efectuata. Aprobarea fiecarui alias e a omului.")
    print(BAR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
