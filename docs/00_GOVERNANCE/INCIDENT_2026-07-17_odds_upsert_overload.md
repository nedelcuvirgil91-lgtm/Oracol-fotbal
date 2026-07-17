# INCIDENT 2026-07-17 — `upsert_odds_snapshot` function overload (PGRST203)

**Status**: Documentat. **Producție NEMODIFICATĂ** — soluția necesită autorizare
explicită (mandat: documentezi → cauză → soluție → nu modifici producția fără
autorizare).
**Severitate**: Medie — capturarea cotelor (odds_history) e nefuncțională; fără
corupție de date; **independent de ADR-025**.

## Fapte

- La rularea `daily.yml` #29 (2026-07-17 08:55 UTC, `workflow_dispatch` pe `main`
  merge-uit), pasul „Persistare cote de piață (odds_history)" a produs **19 erori
  din 26 fixture-uri verificate**; `sync_status.odds_persistence = partial`,
  „0 scrise / 26 verificate".
- Eroare exactă (repetată identic pe fiecare fixture):
  ```
  code PGRST203 — Could not choose the best candidate function between:
    public.upsert_odds_snapshot(p_fixture_id, p_bookmaker, p_home, p_draw, p_away, p_now)
    public.upsert_odds_snapshot(p_fixture_id, p_bookmaker, p_home, p_draw, p_away, p_now,
                                p_provider, p_import_type, p_import_version, p_source_hash, p_source_url)
  ```
- `OddsPersistenceService` face fără-retry (ADR-006 §4) — fixture-ul rămâne
  neactualizat, reevaluat la rularea următoare. Nicio scriere parțială/coruptă.
- **Pre-existent**: același simptom pe 2026-07-16 (`odds_persistence partial`,
  „0 scrise / 31 verificate"), ÎNAINTE de merge-ul ADR-025.

## Cauză

Există **două funcții `upsert_odds_snapshot` supraîncărcate** în producție
(confirmat: `pg_proc` → 2 intrări):
1. **6 argumente** — creată de `database/migrations/001_odds_history.sql` (în repo,
   apelată de `services/odds_persistence_service.py._upsert()`).
2. **11 argumente** — cu provenance (`p_provider`, `p_import_type`,
   `p_import_version`, `p_source_hash`, `p_source_url`) — **NU există în nicio
   migrare din repo**; a fost aplicată ad-hoc pe producție (probabil în timpul
   lucrului de backfill odds cu provenance, ADR-010), fără migrare versionată.

PostgREST rezolvă apelul RPC după numele funcției; cu două supraîncărcări cu
aceleași prime 6 tipuri de parametri, nu poate alege candidatul → `PGRST203`.

Verificat: merge-ul ADR-025 **nu a atins nicio definiție `upsert_odds_snapshot`**
(diff `eac45d9`→`main` pe migrări/odds = gol). Defectul e ortogonal ADR-025.

## Impact

- `odds_history` nu primește scrieri noi (opening/closing) → Value Betting și
  orice consumator de cote istorice lucrează pe date stagnante.
- Zero impact asupra `match_history`, ELO, ML sau ADR-025.

## Soluție propusă (NEAPLICATĂ — necesită autorizare)

Investigație necesară întâi: **ce apelant folosește fiecare semnătură** (serviciul
zilnic apelează 6-arg; `BackfillOddsService` — de verificat dacă folosește 11-arg
sau altă cale). Apoi, una dintre:

- **(A) Recomandat** — regularizare prin migrare versionată: consolidează într-o
  singură funcție `upsert_odds_snapshot` (semnătura 11-arg cu parametrii de
  provenance `DEFAULT NULL`), și **DROP** semnătura 6-arg redundantă. Astfel
  ambii apelanți (6-arg și 11-arg) se rezolvă la o singură funcție, iar starea
  producției devine reproductibilă dintr-o migrare (elimină și datoria „funcție
  ad-hoc fără migrare"). Necesită confirmarea că apelul 6-arg e compatibil cu
  noua semnătură (e — parametrii noi au default).
- **(B)** Redenumire: păstrează ambele, redenumește una (ex. `upsert_odds_snapshot_v2`)
  și aliniază apelantul respectiv. Mai puțin curat (proliferare de nume).
- **(C)** Calificare la apelant: forțează semnătura prin numărul exact de parametri
  — fragil, nu elimină ambiguitatea la nivel de schemă.

Oricare variantă e o **scriere pe producție** (DDL pe funcții) → conform
`supabase-safety` + mandat, se execută doar cu SQL-ul exact arătat și autorizare
explicită.

## Recomandare de proces

Acest defect e o **datorie separată** (odds subsystem), nu parte din ADR-025.
Propunere: îl tratez ca element propriu în auditul de branch-uri / Release Roadmap
(TASK 2/3), cu verdict și plan de integrare, **după** închiderea ADR-025 și cu
autorizarea ta pentru orice scriere pe producție.

## Nemodificat

Nicio funcție, nicio schemă, niciun rând de producție nu a fost atins de acest
raport. Doar documentare.
