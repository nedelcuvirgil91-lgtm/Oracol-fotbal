# ADR-025 — Gate-07: Re-normalizare rânduri canonice (2026-07-16)

**Status**: Re-normalizare executată pe producție, verificată. **Execuția s-a
oprit** — nu s-a creat indexul UNIQUE (Gate-08), niciun pas ulterior.
**Autorizare**: Gate-07, Owner, 2026-07-16 — "exclusiv executarea Gate-07,
conform ID-025-04 și ID-025-05".

## Context (ID-025-04, precondiție înainte de constrângerea UNIQUE)

`normalize_team_name()` (mappings.py) e aplicată la scriere de writerii migrați
(Gate-06), dar rânduri istorice scrise sub versiuni mai vechi ale tabelului de
aliasuri pot avea forme stocate diferite de ce produce normalizarea **curentă**
(drift, nu eroare de scriere). ID-025-04 cere o trecere unică de re-normalizare a
rândurilor canonice înainte de constrângerea UNIQUE, **cu ordinea strictă**:
(1) re-normalizare întâi; (2) verificare zero duplicate **după**; (3) reconciliere
oricărei coliziuni noi produse.

## Ce s-a executat

Trecere unică de re-normalizare pe rândurile **canonice** (`superseded_by IS NULL`).
Normalizarea s-a calculat în Python (`normalize_team_name`) pe numele distincte
stocate; s-au rescris exclusiv coloanele `home_team`/`away_team`, doar unde forma
stocată diferă de forma canonică. Rândurile `superseded` **nu au fost atinse**
(WHERE `superseded_by IS NULL`).

- **58 nume distincte** (din 960 live) diferă de forma canonică → **53 forme
  canonice** distincte (6 perechi de alias se contopesc la același canonic).
- **5.403 rânduri canonice** afectate (backup țintit înainte de scriere:
  `match_history_gate07_renorm_backup_20260716`, 5.403 rânduri — id + home + away).
- Scriere printr-un **singur UPDATE atomic** (mapare `CASE`, scopat pe rândurile
  live care conțin un nume schimbat).

Cele mai multe schimbări sunt echipe engleze de ligă inferioară stocate în formă
scurtă (`Stoke`→`Stoke City`, `QPR`→`Queens Park Rangers`), plus corecții Unicode
(`Farul Constanta`→`Farul Constanța`, `Rapid București`) și cele 6 grupuri de alias
europene (`SPARTA PRAHA`→`AC Sparta Praha` etc.).

## Ordinea respectată (ID-025-04)

1. **DRY-RUN colision, ÎNAINTE de scriere**: simulare server-side (mapare `CASE`
   peste toate cele 49.928 rânduri live) → **0 grupuri de coliziune** pe cheia
   naturală. Deci re-normalizarea nu introduce coliziuni.
2. **Re-normalizare** (UPDATE atomic).
3. **Verificare zero duplicate, DUPĂ re-normalizare**: grupare `lower(trim())` pe
   rândurile live (echivalentă cu cheia normalizată, fiindcă numele stocate sunt
   acum forme canonice) → **0 grupuri duplicate**.

Nicio coliziune nouă produsă → nu a fost nevoie de reconciliere suplimentară
(ID-025-02) — pasul (3) din ID-025-04 confirmat gol, nu sărit.

## Verificări Gate-07 (ID-025-05)

### 1. Re-normalizarea s-a rulat, confirmată idempotentă (V-02)

Demonstrație directă a idempotenței operației: `normalize_team_name(normalize_team_name(x))
== normalize_team_name(x)` pentru **toate** cele 960 nume originale (zero excepții).
Consecință: după prima trecere, `stocat = normalize(x)`; a doua trecere ar calcula
`normalize(normalize(x)) = normalize(x) = stocat` → **0 rânduri modificate**.

Toate cele 53 forme canonice țintă sunt puncte fixe (`normalize(canon)=canon`), și
toate cele **954** nume live post-re-normalizare sunt puncte fixe. Cross-check pe
producție: numărul de nume distincte live = **954** (exact cât a prezis
reconstrucția: 960 − 6 contopiri). A doua trecere = zero schimbări.

### 2. Nu introduce coliziuni noi pe cheia naturală

DRY-RUN (înainte): 0 grupuri de coliziune. Verificare reală (după): **0 grupuri
duplicate** pe cheia naturală printre rândurile live. Confirmat pe ambele direcții.

### 3. Verificările Gate-07 + containment

| Verificare | Rezultat |
|---|---|
| Total rânduri tabelă | 53.432 (neschimbat) |
| Superseded | 3.504 (neschimbat) |
| Live | 49.928 (neschimbat) |
| Grupuri duplicate live după re-normalizare | **0** |
| Rânduri re-normalizate (home/away diferă de backup) | **5.403** = dimensiunea backup-ului țintit |
| Rânduri live care mai păstrează un nume vechi | **0** (re-normalizare completă) |
| Rânduri superseded atinse | **0** (excluse structural prin WHERE) |
| Coloane modificate | exclusiv `home_team`/`away_team` (singurele din `SET`) |
| Nume distincte live | **954** (= predicția Python) |

## Maparea completă (58 → 53), cu numărul de rânduri afectate

| Nume stocat (vechi) | Formă canonică | rânduri ca home | rânduri ca away |
|---|---|---|---|
| `Birmingham` | `Birmingham City` | 93 | 94 |
| `Blackburn` | `Blackburn Rovers` | 94 | 94 |
| `Bolton` | `Bolton Wanderers` | 94 | 94 |
| `Bradford` | `Bradford City` | 94 | 93 |
| `Burton` | `Burton Albion` | 92 | 92 |
| `CRVENA ZVEZDA` | `Crvena Zvezda` | 4 | 4 |
| `Cardiff` | `Cardiff City` | 91 | 92 |
| `Charlton` | `Charlton Athletic` | 94 | 94 |
| `Colchester` | `Colchester United` | 95 | 94 |
| `Coventry` | `Coventry City` | 94 | 94 |
| `Crewe` | `Crewe Alexandra` | 94 | 94 |
| `DINAMO ZAGREB` | `Dinamo Zagreb` | 4 | 4 |
| `DYNAMO KYIV` | `Dynamo Kyiv` | 3 | 3 |
| `Derby` | `Derby County` | 94 | 94 |
| `Doncaster` | `Doncaster Rovers` | 92 | 92 |
| `FC Rapid Bucuresti` | `Rapid București` | 121 | 125 |
| `FC Red Bull Salzburg` | `Red Bull Salzburg` | 7 | 7 |
| `FERENCVAROSI TC` | `Ferencvaros` | 3 | 3 |
| `FK Crvena Zvezda` | `Crvena Zvezda` | 7 | 7 |
| `FK Kairat` | `Kairat Almaty` | 4 | 4 |
| `FK Shakhtar Donetsk` | `Shakhtar Donetsk` | 7 | 7 |
| `Farul Constanta` | `Farul Constanța` | 123 | 119 |
| `GNK Dinamo Zagreb` | `Dinamo Zagreb` | 4 | 4 |
| `Grimsby` | `Grimsby Town` | 93 | 93 |
| `Huddersfield` | `Huddersfield Town` | 94 | 93 |
| `Hull` | `Hull City` | 92 | 91 |
| `LEGIA WARSZAWA` | `Legia Warszawa` | 3 | 3 |
| `LUDOGORETS` | `Ludogorets` | 3 | 3 |
| `Norwich` | `Norwich City` | 90 | 90 |
| `Oxford` | `Oxford United` | 95 | 95 |
| `Peterboro` | `Peterborough United` | 95 | 94 |
| `Plymouth` | `Plymouth Argyle` | 92 | 92 |
| `Preston` | `Preston North End` | 95 | 94 |
| `QPR` | `Queens Park Rangers` | 94 | 94 |
| `Qarabağ Ağdam FK` | `Qarabag` | 5 | 5 |
| `RAPID VIENNA` | `Rapid Vienna` | 3 | 3 |
| `RED BULL SALZBURG` | `Red Bull Salzburg` | 4 | 4 |
| `Rotherham` | `Rotherham United` | 95 | 94 |
| `Royale Union Saint-Gilloise` | `Union Saint-Gilloise` | 4 | 4 |
| `SHAKHTAR DONETSK` | `Shakhtar Donetsk` | 3 | 3 |
| `SHERIFF TIRASPOL` | `Sheriff Tiraspol` | 4 | 4 |
| `SK Slavia Praha` | `Slavia Praha` | 4 | 4 |
| `SPARTA PRAHA` | `AC Sparta Praha` | 3 | 3 |
| `SPORTING CP` | `Sporting CP` | 4 | 4 |
| `Scunthorpe` | `Scunthorpe United` | 46 | 46 |
| `Sheffield Weds` | `Sheffield Wednesday` | 94 | 94 |
| `Southend` | `Southend United` | 75 | 76 |
| `Sporting Clube de Portugal` | `Sporting CP` | 11 | 11 |
| `Stockport` | `Stockport County` | 93 | 94 |
| `Stoke` | `Stoke City` | 93 | 94 |
| `Swansea` | `Swansea City` | 94 | 94 |
| `Tranmere` | `Tranmere Rovers` | 94 | 94 |
| `West Brom` | `West Bromwich Albion` | 95 | 94 |
| `Wigan` | `Wigan Athletic` | 92 | 95 |
| `Wycombe` | `Wycombe Wanderers` | 95 | 95 |
| `Yeovil` | `Yeovil Town` | 52 | 53 |
| `ZENIT SAINT PETERSBURG` | `Zenit Saint Petersburg` | 4 | 4 |
| `ŠK Slovan Bratislava` | `Slovan Bratislava` | 4 | 4 |

## Gate-07 (ID-025-05)

**Criteriu**: (1) re-normalizarea rulată, idempotentă la a doua trecere (zero
rânduri modificate); (2) verificare zero duplicate rulată **după** re-normalizare;
(3) orice coliziune nouă reconciliată.
**No-Go dacă**: verificarea zero-duplicate rulată înainte de re-normalizare;
orice coliziune nouă nereconciliată.

**Verificare**: idempotență demonstrată (`normalize∘normalize = normalize` pe toate
numele; 954 nume live post, toate puncte fixe, cross-checked pe producție);
verificarea zero-duplicate rulată **după** re-normalizare = 0; zero coliziuni noi
(dry-run înainte = 0, real după = 0) → pasul de reconciliere confirmat gol.

### Verdict: **Gate-07 = GO**

## Interdicții respectate (mandat Gate-07)

Nu s-a creat indexul UNIQUE (Gate-08), niciun pas ulterior (Gate-09+). Doar
re-normalizarea + verificările.

## Artefacte de rollback (pe producție)

- `match_history_gate07_renorm_backup_20260716` (5.403 rânduri: id, home_team,
  away_team pre-re-normalizare) — rollback exact al acestei operații.
- `match_history_adr025_faza4_backup_20260716` (snapshot complet, păstrat conform
  recomandării Owner-ului până după Gate-08).

## Notă de metodă

Re-normalizarea e o operație de date unică (nu schemă), executată prin SQL via MCP
(mediul nu are credențiale directe Supabase). Maparea 58→53 de mai sus e artefactul
canonic, reproductibil: forma stocată nouă = `normalize_team_name(forma veche)`,
pentru fiecare nume. Zero cod de producție schimbat în această fază.

## Referințe

- ID-025-04 — Database Constraint (precondiția de re-normalizare + ordinea strictă)
- ID-025-05 — Validation (Gate-07, V-02)
- ADR-025 — Match Identity Implementation Strategy
- `docs/03_ENGINE/ADR025_GATE05_VERIFICATION_2026-07-16.md` (predicția că cele 6
  grupuri de alias nu produc coliziuni de dată — confirmată aici post-execuție)
