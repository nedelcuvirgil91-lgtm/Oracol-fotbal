"""
================================================================================
FOOTBALL ORACLE — Categoria D2: nume fragmentate care NU colizioneaza
================================================================================
Module: scripts/analyze_d2_vocabulary_drift.py

STRICT read-only. Zero scrieri, nicaieri. Nu atinge `mappings.py`, nu atinge
Supabase decat prin SELECT-uri paginate, nu emite niciun baseline.

--------------------------------------------------------------------------------
DE CE EXISTA
--------------------------------------------------------------------------------
Reconcilierea identitatii (ADR-025 Faza 3+4, ADR-059) a rezolvat categoria
"acelasi meci, doua randuri" — 404 grupuri duplicate reduse la 0. Dar a rezolvat
DOAR cazul in care fragmentarea producea o COLIZIUNE de `match_key()`.

Ramane o categorie complet diferita, pe care reconcilierea nu o putea atinge
prin constructie: randuri live al caror `home_team`/`away_team` e un nume pe
care `normalize_team_name()` l-ar traduce in altceva, DAR care nu are un rand
geaman in baza. Nu exista grup duplicat, deci reconcilierea nu le vede.

Efectul lor nu e duplicarea unui meci, ci FRAGMENTAREA unui lant: `ELOTracker`,
`FormTracker` si `H2HTracker` sunt toate indexate pe SIRUL de nume brut
(`dict[str, float]`). Doua nume care desemneaza acelasi club produc doua serii
ELO paralele, fiecare vazand doar jumatate din meciuri.

Masuratoarea de divergenta ELO (Actions run 32558948226) a aratat ca primele
25 de divergente sunt dominate de nume cu sufix de tara — `Liverpool FC (ENG)`,
`Real Madrid CF (ESP)`, `FC Internazionale Milano (ITA)`. Adica exact aceasta
categorie. Reconstructia ELO nu are sens inainte ca D2 sa fie rezolvata: ar
recalcula corect pe serii care raman fragmentate.

--------------------------------------------------------------------------------
CE MASOARA (si ce NU)
--------------------------------------------------------------------------------
Foloseste `mappings.normalize_team_name()` de productie, nemodificat — nu
reimplementeaza normalizarea si nu presupune ce ar face (regula "Verificat, nu
presupus"). Un nume e D2 daca si numai daca `normalize_team_name(n) != n`.

Raporteaza patru lucruri distincte, deliberat neamestecate:

  1. AMPLOAREA   — cate randuri live, cate nume distincte, cate identitati.
  2. LANTURI RUPTE — subsetul in care doua sau mai multe nume vii desemneaza
     ACEEASI identitate canonica. Doar acestea produc serii ELO paralele azi;
     restul sunt inconsecvente de vocabular fara efect de dubla numarare.
  3. COLIZIUNI   — daca redenumirea ar incalca
     `idx_match_history_natural_key_canonical` (UNIQUE pe home_team, away_team,
     kickoff_date WHERE superseded_by IS NULL). Se calculeaza CHEIA EXACTA a
     indexului dupa redenumire si se cauta duplicate. Nu se presupune ca
     reconcilierea le-a eliminat deja — se verifica.
  4. RANDURI SUPERSEDED — cate randuri deja marcate ar ramane cu nume vechi.
     Informativ: ele nu sunt in niciun index si in niciun replay.

NU decide nimic si NU propune o migrare. Produce cifrele pe care un ADR
dedicat (redenumirea scrie in `home_team`/`away_team` — suprafata complet
diferita de cea autorizata de ADR-059) trebuie sa le aiba inainte de a exista.

Utilizare:
    python scripts/analyze_d2_vocabulary_drift.py
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


def classify(rows: list[dict], normalize) -> dict:
    """Toata analiza D2, ca functie PURA peste randuri deja aduse.

    Separata de I/O exact ca `compute_drift()` in check_identity_drift.py, ca
    sa fie testabila pe randuri sintetice, fara Supabase si fara mock-uri
    (`tests/test_analyze_d2_vocabulary_drift.py`).

    `normalize` e injectat (nu importat aici) ca testele sa poata folosi un
    vocabular mic si explicit in loc de cele 854 de alias-uri reale.
    """
    # --- 1. Amploare -----------------------------------------------------
    # rename_map: nume brut -> canonic, doar pentru cele care se schimba.
    rename_map: dict[str, str] = {}
    # aparitii per nume brut (o aparitie = o parte a unui meci, home sau away)
    raw_occurrences: dict[str, int] = defaultdict(int)
    live_raw_names: set[str] = set()
    affected_row_ids: set = set()

    for row in rows:
        rid = row.get("id")
        for side in ("home_team", "away_team"):
            raw = row.get(side)
            if not raw:
                continue
            live_raw_names.add(raw)
            raw_occurrences[raw] += 1
            canon = normalize(raw)
            if canon != raw:
                rename_map[raw] = canon
                affected_row_ids.add(rid)

    # --- 2. Lanturi rupte -------------------------------------------------
    # Identitatea canonica a fiecarui nume viu (inclusiv a celor care nu se
    # schimba — un nume deja canonic e propria identitate). Un lant e rupt
    # cand >= 2 nume VII cad pe aceeasi identitate.
    identity_to_names: dict[str, set[str]] = defaultdict(set)
    for raw in live_raw_names:
        identity_to_names[normalize(raw)].add(raw)

    broken_chains = {
        identity: sorted(names)
        for identity, names in identity_to_names.items()
        if len(names) > 1
    }

    # --- 3. Coliziuni la redenumire --------------------------------------
    # Cheia EXACTA a indexului unic, calculata dupa redenumire. `kickoff_date`
    # e `text` in schema, deci se compara ca atare — nu se normalizeaza si nu
    # se trunchiaza la 10 caractere (asta ar fi `match_key()`, o cheie DIFERITA,
    # mai grosiera; a le confunda ar rata exact coliziunile pe care indexul
    # le-ar respinge).
    post_rename_key: dict[tuple, list] = defaultdict(list)
    for row in rows:
        h = row.get("home_team") or ""
        a = row.get("away_team") or ""
        key = (rename_map.get(h, h), rename_map.get(a, a), row.get("kickoff_date"))
        post_rename_key[key].append(row.get("id"))

    collisions = {k: v for k, v in post_rename_key.items() if len(v) > 1}

    return {
        "live_rows": len(rows),
        "live_distinct_names": len(live_raw_names),
        "d2_distinct_names": len(rename_map),
        "d2_affected_rows": len(affected_row_ids),
        "d2_occurrences": sum(raw_occurrences[r] for r in rename_map),
        "rename_map": rename_map,
        "raw_occurrences": dict(raw_occurrences),
        "identities_total": len(identity_to_names),
        "broken_chains": broken_chains,
        "collisions": collisions,
    }


def _fetch_rows(client, superseded: bool) -> list[dict]:
    """Paginare identica cu `_fetch_key_index()` din serviciul de reconciliere
    — acelasi contract, aceeasi dimensiune de pagina.

    [FIX — descoperit 2026-08-22] `.range()` FARA `.order()` explicit nu are
    ordine garantata intre pagini succesive sub scriere concurenta — poate
    intoarce acelasi rand de doua ori. `id` e imutabil si monoton, deci
    ordonarea pe el face paginarea provabil stabila (acelasi fix ca in
    `services/match_identity_reconciliation_service.py`)."""
    rows: list[dict] = []
    seen_ids: set = set()
    offset, page_size = 0, 1000
    while True:
        q = client.table("match_history").select("id,home_team,away_team,kickoff_date")
        q = q.not_.is_("superseded_by", "null") if superseded else q.is_("superseded_by", "null")
        batch = (q.order("id").range(offset, offset + page_size - 1).execute().data) or []
        for row in batch:
            rid = row.get("id")
            if rid in seen_ids:
                continue  # aparare in adancime, vezi nota de mai sus
            seen_ids.add(rid)
            rows.append(row)
        if len(batch) < page_size:
            break
        offset += page_size
    return rows


def main() -> int:
    import supabase_client as sb

    if not sb.is_available():
        print("EROARE: Supabase indisponibil (SUPABASE_URL / SUPABASE_SECRET_KEY).")
        return 1

    from mappings import normalize_team_name

    client = sb.get_client()

    print(BAR)
    print("  CATEGORIA D2 — nume fragmentate care NU colizioneaza")
    print("  STRICT read-only. Zero scrieri.")
    print(BAR)

    live = _fetch_rows(client, superseded=False)
    if not live:
        print("EROARE: niciun rand live returnat.")
        return 1

    res = classify(live, normalize_team_name)

    print(f"  Randuri live                        : {res['live_rows']}")
    print(f"  Nume distincte in uz                : {res['live_distinct_names']}")
    print(f"  Identitati canonice distincte       : {res['identities_total']}")
    print(BAR)
    print("  1. AMPLOAREA D2")
    print(f"    Nume distincte care s-ar schimba  : {res['d2_distinct_names']}")
    print(f"    Randuri live afectate             : {res['d2_affected_rows']}")
    print(f"    Aparitii (home+away) de rescris   : {res['d2_occurrences']}")
    print(BAR)

    print("  2. LANTURI ELO RUPTE AZI (>=2 nume vii pe aceeasi identitate)")
    chains = res["broken_chains"]
    occ = res["raw_occurrences"]
    print(f"    Identitati cu lant rupt           : {len(chains)}")
    rows_in_chains = sum(occ.get(n, 0) for names in chains.values() for n in names)
    print(f"    Aparitii implicate                : {rows_in_chains}")
    print(BAR)
    print("    Detaliu (ordonat dupa aparitiile din ramura minoritara —")
    print("    adica exact cat de mult 'lipseste' din lantul principal):")
    def minority(names: list[str]) -> int:
        counts = sorted((occ.get(n, 0) for n in names), reverse=True)
        return sum(counts[1:])
    for identity, names in sorted(chains.items(), key=lambda kv: -minority(kv[1])):
        parts = ", ".join(f"{n!r}={occ.get(n, 0)}" for n in sorted(names, key=lambda n: -occ.get(n, 0)))
        print(f"      [{minority(names):>4}] {identity}  <-  {parts}")
    print(BAR)

    print("  3. COLIZIUNI PE INDEXUL UNIC, DUPA REDENUMIRE")
    print("     (cheia exacta a idx_match_history_natural_key_canonical)")
    coll = res["collisions"]
    if not coll:
        print("    0 coliziuni — redenumirea nu ar incalca indexul unic.")
    else:
        print(f"    \U0001f534 {len(coll)} coliziuni. Redenumirea ar esua pe acestea:")
        for (h, a, kd), ids in sorted(coll.items(), key=lambda kv: str(kv[0]))[:50]:
            print(f"      {h} vs {a} @ {kd}  -> id-uri {ids}")
        if len(coll) > 50:
            print(f"      ... si inca {len(coll) - 50}")
    print(BAR)

    superseded = _fetch_rows(client, superseded=True)
    res_sup = classify(superseded, normalize_team_name) if superseded else None
    print("  4. RANDURI DEJA SUPERSEDED (informativ — in afara indexului si a replay-ului)")
    if res_sup:
        print(f"    Randuri superseded                : {res_sup['live_rows']}")
        print(f"    dintre care cu nume fragmentat    : {res_sup['d2_affected_rows']}")
    else:
        print("    (niciun rand superseded)")
    print(BAR)
    print("  Analiza incheiata. ZERO scriere efectuata.")
    print(BAR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
