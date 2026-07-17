# ADR-025 — Gate-09 (Release Integration) + Închidere Oficială (2026-07-17)

**Status**: **ADR-025 ÎNCHIS**. Integrat în `main`, validat pe producție.
**Autorizare**: Mandat Release Strategy, Owner, 2026-07-17 (Gate-09 = Release
Integration Gate).

## Rezumat

ADR-025 (Canonical Match Identity) e implementat, validat gate-cu-gate (01…08)
și acum **integrat în `main`** printr-un Release Integration Gate disciplinat.
`main` reprezintă din nou adevărul proiectului.

## Gate-09 — pașii executați (în ordinea impusă)

1. **Push release branch** — `release/adr-025-integration` (creat din `origin/main`).
2. **PR** — [#1](https://github.com/nedelcuvirgil91-lgtm/Oracol-fotbal/pull/1), `mergeable_state: clean`.
3. **Verificare PR** — clean, fără CI checks configurate pe PR (validare făcută local: 416/427 teste + dry-run + end-to-end).
4. **Merge în `main`** — PR #1 merge-uit, `main` la `d6bcdaa`.
5. **`workflow_dispatch`** — rularea `daily.yml` #29 (`29567779677`) pe `main` merge-uit.
6. **Verificare** (mai jos).
7. **Monitorizare** — vezi „Monitorizare".
8. **Închidere oficială** — acest document.

## Analiza conflictelor & rezolvare (main păstrat integral)

Divergență: branch 133 commituri înainte, `main` 23 înapoi (nu fast-forward).
Două conflicte, ambele pe fișiere unde `main` avea fix-ul „destructive writer"
(`25b9166`): `database/queries.py`, `tests/test_sync_writer_protection.py`.

Verificat că branch-ul e **superset** al fix-ului din `main` — toate fix-urile
din `main` păstrate în rezultat:
- `_strip_none_values` (garda anti-None) — păstrat + combinat cu `_normalize_team_fields` + RPC.
- `get_existing_fixture_ids` chunking (200) + fail-closed — prezent.
- Eliminarea cheilor `home_elo/away_elo` din `football_data.py`/`openfootball.py` — prezent.
- Workflow-urile `backfill_match_stats.yml`/`backfill_odds.yml` — prezente.
- Cele 7 teste de regresie writer-protection — nume identice `main`↔branch, adaptate la RPC.

## Verificare (step 6) — criteriile mandatului

| Criteriu | Rezultat |
|---|---|
| Rularea `workflow_dispatch` | **success** (conclusion=success, 303s, toate 6 pașii) |
| RPC (`upsert_match_canonical`) prezent pe producție | ✅ da |
| UNIQUE INDEX `idx_match_history_natural_key_canonical` | ✅ prezent, `indisvalid=true` |
| 0 duplicate live | ✅ `live_dup_groups = 0` |
| 0 erori `23505` | ✅ zero în log-ul rulării; `+0 meciuri noi` → 0 INSERT-uri, deci nicio violare posibilă |
| `sync_status` | `football_data` **ok** (fetched=5756 skipped=5756), `openfootball` **ok**, `experiment_evaluation` **ok** |
| Total/superseded/live | 53.432 / 3.504 / 49.928 — neschimbat |

Calea de scriere `match_history` (writeri migrați → RPC) a rulat curat în
producție: sursele au dedus toate meciurile (0 noi), zero `23505`, invarianții
ADR-025 intacți.

## Incident SEPARAT, pre-existent (NU ADR-025) — vezi raport dedicat

Rularea a expus un defect **independent de ADR-025**: `OddsPersistenceService`
eșuează cu `PGRST203` (ambiguitate de supraîncărcare pe `upsert_odds_snapshot`,
2 semnături în producție), 19/26 scrieri de cote eșuate. **Pre-existent**
(prezent și pe 07-16, înainte de merge); merge-ul ADR-025 nu a atins nicio
funcție de odds. Subsistem diferit (`odds_history` / `upsert_odds_snapshot`),
NU calea de identitate a meciului. **Nu blochează închiderea ADR-025.**
Documentat, cu cauză și soluție propusă, în
`docs/00_GOVERNANCE/INCIDENT_2026-07-17_odds_upsert_overload.md` — **nemodificat
pe producție fără autorizare explicită**.

## Monitorizare (step 7)

Rularea imediată post-merge (`workflow_dispatch`) e validată curat pentru calea
ADR-025. Următoarele rulări cron (`0 3 * * *`) trebuie verificate pentru:
0×`23505`, RPC fără erori, 0 duplicate live. (Nicio automatizare de check-in nu
e armată — verificare la cerere sau la următoarea rulare, conform preferinței
Owner-ului.)

## Backup-uri (păstrate, NEȘTERSE)

- `match_history_adr025_faza4_backup_20260716` — 53.432 rânduri.
- `match_history_gate07_renorm_backup_20260716` — 5.403 rânduri.

Rămân disponibile pentru rollback în fereastra de stabilizare.

## Criterii de rollback (dacă apare o regresie ADR-025 ulterioară)

Revert al merge-ului pe `main` (codul revine la writeri vechi) **cuplat cu**
`DROP INDEX idx_match_history_natural_key_canonical` (altfel writerii vechi ar
putea lovi indexul). Datele reconciliate + RPC rămân; backup-urile sunt plasa de
date. Indexul NU se scoate izolat (protejează integritatea).

## Verdict: **ADR-025 = CLOSED**

Toate cele 9 gate-uri (01…08 + 09 Release Integration) executate, validate,
integrate în `main`. Verificarea de producție e curată pentru calea de identitate
a meciului. Singurul defect rămas e pre-existent, independent, documentat separat.

## Referințe

- ADR-025 + ID-025-01…06; rapoartele Gate-01…08 (`docs/03_ENGINE/ADR025_*`).
- PR #1 (Release Integration).
- `docs/00_GOVERNANCE/INCIDENT_2026-07-17_odds_upsert_overload.md`.
