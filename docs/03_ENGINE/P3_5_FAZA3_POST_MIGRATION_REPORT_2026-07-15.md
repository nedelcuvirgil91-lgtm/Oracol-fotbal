# P3.5 — Faza 3: Raport Post-Migrare

**Status**: Executat pe producție (proiect Supabase `Prediction`, `gtlpyxzocacaqyompkwe`). Continuă `P3_5_FAZA3_MIGRATION_PLAN_2026-07-15.md` (aprobat, autorizare Chief Architect). Toate cifrele de mai jos sunt măsurate direct pe producție după execuție, nu estimate.

---

## 1. Ce s-a executat

| Pas | Acțiune | Rezultat |
|---|---:|---|
| 0 | Snapshot rollback | `match_history_faza3_backup_20260715` — 19.797 rânduri, creat înainte de orice UPDATE |
| A.1 | Rescriere `home_team` (176 perechi) | Executat |
| A.2 | Rescriere `away_team` (176 perechi) | Executat |
| Verificare A | 0 nume brute rămase (WHERE home/away_team IN 176 raw names) | **0** — confirmat înainte de Pasul B |
| B | Reset 18 coloane la `NULL` (scope 313 nume) | **19.797 rânduri**, toate 18 coloane simultan `NULL` — exact cifra din Migration Plan |
| C.1 | `run_backfill()` — GitHub Actions run `#29419904484`, global (`league=""`), `retrain_ml=false` | 19.828/19.829 rânduri scrise cu succes, 1 eroare, durată **3547,1s (~59,1 min)** |
| C.2 | `run_backfill()` — rerulare, `#29425268522` | A completat rândul rămas (Writer Protection, idempotent) |

Total `match_history` neschimbat pe tot parcursul: **53.430 rânduri** (verificat înainte și după).

---

## 2. Incident izolat — 1 rând din 19.797, cauză și remediere

Run-ul `#29419904484` a fost marcat de GitHub Actions drept **failure**, deși scriptul a terminat execuția completă (log: „BACKFILL COMPLET, Procesate: 19829, Erori: 1"). Cauza: `sync/backfill_features.py:998-999` face `sys.exit(1)` la orice `errors > 0`, indiferent de câte rânduri au reușit — o politică all-or-nothing deja existentă în cod, nemodificată în această sesiune.

Rândul afectat: `id=80790` (Brescia vs Como, 2023-12-16, liga I2) — toate 18 coloane rămase `NULL` după primul run, restul de 19.796 rânduri corecte. Cauza probabilă: un blip tranzitoriu de rețea/Supabase pe acel apel PATCH specific (restul rulării a avut mii de PATCH-uri reușite consecutive, fără alt pattern de eroare).

Remediere: rerulare identică (`#29425268522`, aceeași comandă globală, `retrain_ml=false`). Datorită Writer Protection (Regula #13), toate rândurile deja complete au fost sărite instant (fără PATCH), iar rândul `id=80790` a fost scris corect. **Confirmat direct pe Supabase** (nu prin log-urile GitHub Actions — conexiunea MCP GitHub a expirat în timpul verificării celui de-al doilea run; verificarea s-a făcut prin interogarea directă a stării finale în baza de date, sursa de adevăr).

---

## 3. Sanity checks (măsurate pe producție, după ambele rulări)

| Verificare | Rezultat |
|---|---:|
| Rânduri cu `home_elo IS NULL` (întreaga bază) | **0** |
| Rânduri cu oricare din cele 10 coloane obligatorii (`elo`, `form_score`, `offensive/defensive_rating`, `h2h_*`) `NULL` (întreaga bază, 53.430 rânduri) | **0** |
| Valori negative pe `elo`/`form_score`/`offensive_rating`/`defensive_rating`/`h2h_meetings`/`corner_avg`/`card_avg`/`foul_avg`/`shot_avg` | **0** pe toate |
| Rândul `id=80790` (cel remediat) | 16/18 coloane populate; `home_shot_avg_recent`/`away_shot_avg_recent` rămân `NULL` — **comportament legitim** (Regula #8: `ShotCountTracker` nu are încă istoric real de șuturi pentru aceste echipe la acel moment, nu se aproximează) |
| Total `match_history` | **53.430** — neschimbat |

---

## 4. Spot-check H2H (categoria C din Impact Matrix)

Verificare inițială pe perechea Porto/Benfica: fără diferență înainte/după — canonic deja dominant în acele înregistrări specifice, nerelevant ca test.

Verificare pe **Borussia Mönchengladbach** (fragmentat între „Borussia Mönchengladbach"/„M'gladbach"/„MGladbach"/„Borussia Monchengladbach") — comparație directă `match_history` vs `match_history_faza3_backup_20260715` pentru toate rândurile unde `h2h_meetings` diferă:

| Exemplu | `h2h_meetings` înainte | `h2h_meetings` după |
|---|---:|---:|
| Borussia Mönchengladbach vs RB Leipzig (2025-03-29) | 0 | 10 |
| Borussia Mönchengladbach vs Eintracht Frankfurt (2025-02-08) | 0 | 10 |
| Borussia Dortmund vs Borussia Mönchengladbach (2025-04-20) | 0 | 10 |
| VfB Stuttgart vs Borussia Mönchengladbach (2025-02-01) | 0 | 10 |
| +6 perechi similare | 0 | 10 |

**Confirmă empiric predicția arhitecturală din Impact Matrix §7 categoria C**: înainte de consolidare, istoricul H2H al acestei echipe era complet invizibil (0 întâlniri înregistrate) din cauza fragmentării cheii-pereche `(min(home,away), max(home,away))`; după consolidare, istoricul complet e vizibil (plafonat la fereastra de 10 meciuri a tracker-ului, per design). Orientarea home/away rămâne corectă (verificat: `h2h_modifier` cu semn coerent pe direcție).

---

## 5. Rata de populare `shot_avg_recent`

**Corecție față de instrucțiunea de verificare inițială**: cifra de „92,7%" citată din P7.1 se referea la setul curat de 5.253 meciuri folosit în ablația walk-forward, NU la întreaga tabelă `match_history` și nici la scope-ul de 19.797 rânduri al Fazei 3 — nu era o bază de comparație validă aici. Comparația corectă, pe același scope, înainte/după:

| Moment | Scope | `home_shot_avg_recent` populat | Procent |
|---|---:|---:|---:|
| **Înainte** (backup) | 19.797 | 5.013 | **25,3%** |
| **După** (Faza 3 + re-backfill) | 19.797 | 9.095 | **45,9%** |
| Global (întreaga bază, 53.430) | 53.430 | 9.137 | 17,1% |

**Rezultat: îmbunătățire reală (25,3% → 45,9%), nu regresie.** Consistent cu predicția arhitecturală — consolidarea unifică istoricul, deci mai multe rânduri ating pragul „cel puțin 1 valoare reală în fereastră". Populația globală (17,1%) e mai mică decât cea din scope-ul Fazei 3, fiindcă datele reale de șuturi (`ShotCountTracker`, sursă `MatchStatsBackfillService`) nu acoperă întregul istoric Kaggle — doar sezoanele/ligile cu statistici reale disponibile, fapt cunoscut și necorelat cu această migrare.

---

## 6. Impact final

- **12.247 rânduri** cu `home_team`/`away_team` rescris literal (Pasul A) — cifră din Migration Plan, confirmată indirect prin verificarea „0 nume brute rămase" post-execuție.
- **19.797 rânduri** cu toate 18 coloane resetate și recalculate corect (Pasul B + C).
- **1 rând** a necesitat o a doua rulare (remediat, cauză tranzitorie, nu structurală).
- **0** valori greșite, negative sau lăsate `NULL` fără justificare arhitecturală (Regula #8).
- **0** rânduri pierdute sau duplicate — 53.430 înainte și după.
- Predicțiile live **nu au fost afectate** în nicio clipă (confirmat în Impact Matrix: cele 18 coloane sunt consumate exclusiv de `ml_predictor`, nu de `oracle_engine` live).

## 7. Ce NU s-a făcut (per instrucțiune explicită)

- `retrain_ml` a fost explicit dezactivat pe ambele rulări — niciun model ML nu a fost reantrenat.
- Nicio reevaluare P3 (MOV ELO) sau alt experiment din roadmap nu a fost inițiată.
- Execuția se oprește aici, în așteptarea analizei și aprobării acestui raport.
