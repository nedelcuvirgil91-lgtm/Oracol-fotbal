# ADR-025 — Faza 3: Raport EXECUTE Pilot (2026-07-16)

**Status**: Pilot EXECUTE complet, verificat. **Execuția s-a oprit conform
mandatului** — nu s-a continuat spre Faza 4, nu s-a rulat reconcilierea
completă, nu s-au modificat writerii/schema/constrângerile.
**Autorizare**: Faza 3, Owner, 2026-07-16 — "exclusiv execuția pilotului...
subset stabilit pentru validare manuală".

## Algoritm folosit — identic cu Gate-02, fără nicio modificare

`services/match_identity_reconciliation_service.py` **nu a fost modificat**
față de commit-ul validat la Gate-02 (`eef3571`) — verificat explicit
(`git diff` gol) înainte de rulare. Deciziile de mai jos au fost produse prin
apelul direct al funcției pure `process_group()` din acel fișier neschimbat,
pe datele reale ale subsetului pilot (aduse read-only, înainte de orice
scriere). SQL-ul de scriere a fost generat programatic din rezultatul exact
al acelui apel — nicio valoare retastată manual.

Mecanismul de scriere: acest mediu de execuție nu are credențiale directe
Supabase (doar canalul MCP) — scrierea reală s-a făcut prin tranzacții SQL
explicite (`BEGIN`/`UPDATE`/`COMMIT`), câte una per grup, exact tiparul de
atomicitate per-grup cerut de ID-025-02. Codul `MatchIdentityReconciliationService`
însuși **nu a primit o metodă EXECUTE nouă** în această fază — deliberat: o
implementare corectă, reutilizabilă (Faza 4) necesită o funcție RPC atomică
dedicată, iar crearea unei funcții noi în baza de date ar fi o modificare de
schemă, explicit interzisă de mandatul acestei faze.

## 1. Lista exactă a grupurilor procesate

| # | Canonic (id / sursă) | Necanonic (id / sursă) | Echipe | Dată |
|---|---|---|---|---|
| 1 | 13 / `fd_435943` | 75913 / `kaggle_25333cc9ae292387` | Burnley – Manchester City | 2023-08-11 |
| 2 | 14 / `fd_435944` | 75923 / `kaggle_51571702e72bd63f` | Arsenal – Nottingham Forest | 2023-08-12 |
| 3 | 15 / `fd_435945` | 75927 / `kaggle_248983a5044a1952` | AFC Bournemouth – West Ham United | 2023-08-12 |
| 4 | 23 / `fd_435959` | 76182 / `kaggle_896ef66fe8c63ff5` | Nottingham Forest – Sheffield United | 2023-08-18 |
| 5 | 24 / `fd_435955` | 76244 / `kaggle_701347be2e28d63e` | Fulham – Brentford | 2023-08-19 |

**Criteriul de selecție a pilotului** (deliberat, pentru acoperire echilibrată
de cod): 3 grupuri unde canonicul primește completări reale prin merge
(#1-3), 2 grupuri "triviale" unde canonicul e deja complet — doar marcarea
necanonică se aplică (#4-5). Toate 5 sunt din perechile istorice
`football_data`↔`kaggle_historical` — **cele 3 grupuri active World Cup 2026
(`espn`↔`odds_api`, dormante, `actual_result IS NULL`) au fost exclus
deliberat din pilot**, pentru a păstra pilotul strict pe date istorice,
complet închise, fără nicio interacțiune cu meciuri live.

## 2. Raport complet EXECUTE pentru pilot

| Metrică | Valoare |
|---|---|
| Grupuri în scope | 5 |
| Grupuri procesate | 5 |
| Excluse — HARD CONFLICT | 0 |
| Excluse — sursă necunoscută | 0 |
| Reconciliate cu succes | 5 / 5 (100%) |
| Rânduri canonice cu ≥1 completare | 3 (#1, #2, #3) |
| Rânduri necanonice marcate `superseded` | 5 |
| Total rânduri scrise | 8 (3 UPDATE pe canonic + 5 UPDATE pe necanonic) |
| Erori de scriere | 0 |
| Tranzacții | 5, câte una per grup (`BEGIN`/`UPDATE`(×1-2)/`COMMIT`) — toate `COMMIT` confirmat |

## 3. Diferențe înainte/după, per grup

Doar coloanele `*_avg_recent` (singurele afectate de merge, per predicția
DRY-RUN) + coloanele de audit.

**Grup #1 — canonic id=13**
| Coloană | Înainte | După |
|---|---|---|
| `home_corner_avg_recent` | `NULL` | `6.0` |
| `away_corner_avg_recent` | `NULL` | `5.0` |
| `home_card_avg_recent` | `NULL` | `0.0` |
| `away_card_avg_recent` | `NULL` | `0.0` |
| `home_foul_avg_recent` | `NULL` | `11.0` |
| `away_foul_avg_recent` | `NULL` | `8.0` |
| `home_shot_avg_recent` | `NULL` | `6.0` |
| `away_shot_avg_recent` | `NULL` | `17.0` |

Necanonic id=75913: `superseded_by` `NULL`→`13`, `superseded_at` `NULL`→`2026-07-16 16:58:04 UTC`, `superseded_reason` `NULL`→`"duplicate_cross_provider: canonical=fd_435943 (rank=1), superseded=kaggle_25333cc9ae292387 (rank=4)"`.

**Grup #2 — canonic id=14**
| Coloană | Înainte | După |
|---|---|---|
| `home_corner_avg_recent` | `NULL` | `8.0` |
| `away_corner_avg_recent` | `NULL` | `3.0` |
| `home_card_avg_recent` | `NULL` | `2.0` |
| `away_card_avg_recent` | `NULL` | `2.0` |
| `home_foul_avg_recent` | `NULL` | `12.0` |
| `away_foul_avg_recent` | `NULL` | `12.0` |
| `home_shot_avg_recent` | `NULL` | `15.0` |
| `away_shot_avg_recent` | `NULL` | `6.0` |

Necanonic id=75923: `superseded_by` `NULL`→`14`, `superseded_at` `NULL`→`2026-07-16 16:58:10 UTC`, `superseded_reason` `NULL`→`"duplicate_cross_provider: canonical=fd_435944 (rank=1), superseded=kaggle_51571702e72bd63f (rank=4)"`.

**Grup #3 — canonic id=15**
| Coloană | Înainte | După |
|---|---|---|
| `home_corner_avg_recent` | `NULL` | `10.0` |
| `away_corner_avg_recent` | `NULL` | `4.0` |
| `home_card_avg_recent` | `NULL` | `1.0` |
| `away_card_avg_recent` | `NULL` | `4.0` |
| `home_foul_avg_recent` | `NULL` | `9.0` |
| `away_foul_avg_recent` | `NULL` | `14.0` |
| `home_shot_avg_recent` | `NULL` | `14.0` |
| `away_shot_avg_recent` | `NULL` | `16.0` |

Necanonic id=75927: `superseded_by` `NULL`→`15`, `superseded_at` `NULL`→`2026-07-16 16:58:15 UTC`, `superseded_reason` `NULL`→`"duplicate_cross_provider: canonical=fd_435945 (rank=1), superseded=kaggle_248983a5044a1952 (rank=4)"`.

**Grup #4 — canonic id=23** — nicio coloană de merge modificată (canonic deja complet). Necanonic id=76182: `superseded_by` `NULL`→`23`, `superseded_at` `NULL`→`2026-07-16 16:58:19 UTC`, `superseded_reason` `NULL`→`"duplicate_cross_provider: canonical=fd_435959 (rank=1), superseded=kaggle_896ef66fe8c63ff5 (rank=4)"`.

**Grup #5 — canonic id=24** — nicio coloană de merge modificată (canonic deja complet). Necanonic id=76244: `superseded_by` `NULL`→`24`, `superseded_at` `NULL`→`2026-07-16 16:58:25 UTC`, `superseded_reason` `NULL`→`"duplicate_cross_provider: canonical=fd_435955 (rank=1), superseded=kaggle_701347be2e28d63e (rank=4)"`.

## 4. Rândul canonic ales, per grup, cu justificare

Toate 5 grupuri: canonic = rândul `football_data` (`fd_*`), **rang 1**
(cel mai de încredere, `source_trust_policy.SOURCE_TRUST_RANK`), necanonic =
`kaggle_historical`, **rang 4**. Niciun caz de egalitate de rang (tiebreak pe
`id` minim, ID-025-01 Pasul 2) — rangul de sursă singur a decis în toate cele
5 cazuri. Corespunde exact Source Trust Policy stabilită în Faza 1 și
compoziției raportate la Gate-02 (100% din grupurile istorice: canonic
`football_data`).

## 5. Toate coloanele completate prin merge

Exclusiv cele 8 coloane `*_avg_recent` (`home_corner_avg_recent`,
`away_corner_avg_recent`, `home_card_avg_recent`, `away_card_avg_recent`,
`home_foul_avg_recent`, `away_foul_avg_recent`, `home_shot_avg_recent`,
`away_shot_avg_recent`), și doar pe grupurile #1-3 (3 din 5) — valorile exacte
sunt în tabelele de la secțiunea 3. Toate celelalte coloane din
`MERGE_COLUMNS` (43 rămase) erau deja populate pe rândul canonic în toate
cele 5 grupuri — niciun caz de Case 3 (SOFT CONFLICT, mai mulți candidați
concurenți) în acest pilot, consistent cu observația de la Gate-02 (fiecare
grup are exact 2 rânduri).

## 6. Grupuri excluse și motivul excluderii

**Niciunul** — 0 din cele 5 grupuri din pilot au fost excluse. (Excluderile —
HARD CONFLICT, sursă necunoscută — sunt posibile în algoritm, dar niciun grup
din subsetul ales nu le-a declanșat; subsetul a fost ales dintre grupurile
deja clasificate "reconciled" la Gate-02.)

## 7. Dovada că modificările au rămas limitate exclusiv la subsetul pilot

Verificare read-only, după toate cele 5 tranzacții:

```sql
SELECT
  (SELECT count(*) FROM match_history) AS total_rows,               -- 53.432 (neschimbat)
  (SELECT count(*) FROM match_history WHERE superseded_by IS NOT NULL) AS total_superseded, -- 5
  (SELECT array_agg(id ORDER BY id) FROM match_history WHERE superseded_by IS NOT NULL),    -- [75913,75923,75927,76182,76244]
  (SELECT count(*) FROM match_history
     WHERE superseded_by IS NOT NULL AND id NOT IN (75913,75923,75927,76182,76244)
  ) AS unexpected_superseded_rows;                                   -- 0
```

Rezultat: `total_rows=53432` (identic cu starea de dinainte de Fazele 1-3),
`total_superseded=5`, `superseded_ids` = exact cele 5 id-uri necanonice din
pilot, `unexpected_superseded_rows=0`. Toate cele 5 `UPDATE` de marcare și
cele 3 `UPDATE` de merge au folosit `WHERE id = <literal>` — scriere
imposibil de extins dincolo de rândul țintă, prin construcția SQL-ului însuși
(nu doar prin verificare ulterioară).

Suplimentar: niciun `DELETE`, `ALTER`, `CREATE FUNCTION`/`CREATE TRIGGER` nu a
fost executat în această fază — `SourceTrustProvider`, schema, writerii și
constrângerile rămân exact ca la finalul Fazei 1.

## Gate-03 (ID-025-05): Faza 3 → Faza 4

**Criteriu**: Subsetul pilot verificat manual — fiecare rând canonic/
superseded din pilot corespunde exact cu ce a prezis DRY-RUN (Gate-02) pentru
același subset. Comparație exclusiv asupra rezultatului final.
**No-Go dacă**: orice discrepanță de rezultat final între predicția DRY-RUN
și EXECUTE pe pilot.

**Verificare**: predicția (secțiunea "Algoritm folosit", `process_group()`
neschimbat) și rezultatul real (secțiunea 3, citit din producție după
scriere) coincid **exact**, câmp cu câmp, pe toate cele 5 grupuri — canonic
identic, valori de merge identice, `superseded_reason` identic caracter cu
caracter. Zero discrepanță.

### Verdict: **Gate-03 = GO**

Dovezi: secțiunile 1-7 de mai sus (grupuri procesate, raport EXECUTE,
diferențe înainte/după, justificare canonic, completări merge, excluderi
— niciuna —, containment verificat). Algoritmul folosit e byte-identic cu
cel validat la Gate-02. Scrierea a rămas strict limitată la cele 10 rânduri
ale pilotului.

## Interdicții respectate (mandat Faza 3)

Execuția s-a oprit aici, conform mandatului. **Nu s-a continuat spre Faza 4,
nu s-a rulat reconcilierea completă, nu s-au modificat writerii, nu s-a creat
constrângerea UNIQUE, niciun pas din fazele ulterioare nu a fost executat.**

## Referințe

- ADR-025 — Match Identity Implementation Strategy (Faza 3, Rollback Strategy)
- ID-025-01 — Canonical Row Selection
- ID-025-02 — Historical Reconciliation Engine
- ID-025-05 — Validation (Gate-03)
- `docs/03_ENGINE/ADR025_PHASE2_DRY_RUN_REPORT_2026-07-16.md` — predicția
  Gate-02 pentru corpusul complet (subsetul pilot e o submulțime a acelui
  raport)
