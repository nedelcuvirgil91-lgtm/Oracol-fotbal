# P3 — Activarea V2_damped în producție: Design Review, Impact Analysis, Migration Plan

**Status**: Document de proiectare + plan de migrare — zero cod scris (deja scris și comis în `631b0a4`), zero migrare rulată, zero rând din `match_history` atins. Continuă `ADR-022-elo-margin-of-victory-v2-damped.md` (Accepted). Execuția rămâne condiționată de aprobarea explicită a acestui document, ca precedentul `P3_5_FAZA3_MIGRATION_PLAN_2026-07-15.md`.

**Context**: cod deja implementat și testat (`sync/backfill_features.py`, `sync/bootstrap_league_learning.py`, `tests/test_elo_mov.py`, 394/394 verzi) — `ELOTracker` calculează acum formula MOV (V2_damped, c=4,4/d=0,0005) când e apelat. **Producția nu e afectată** de acest cod până nu se resetează explicit coloanele deja populate (Writer Protection, Regula #13) — exact motivul acestui document.

---

## 1. Design Review

### 1.1 Ce se schimbă, exact — analiză de dependență de cod (nu presupunere)

`ELOTracker.process_match()` e singura sursă a valorii `home_elo`/`away_elo`. Verificat direct în cod, `sync/backfill_features.py`, cine consumă `elo_tracker.get_elo(team)`:

| Consumator | Linie | Afectat? |
|---|---|---|
| `elo_tracker.get_elos_before_match()` → `home_elo`/`away_elo` (coloană directă) | :234-236 | **DA** — direct |
| `team_pre_match_rating()` → `elo_off`/`elo_def` (linia :726-732) → blend cu goluri/SOT → `home/away_offensive_rating`/`defensive_rating` | :726-755 | **DA** — indirect, prin blend (`elo_blend_weight`) |
| `team_pre_match_rating()` → `form_score` (linia :756, :760) | :734, :756 | **NU** — calculat exclusiv din `form_tracker.calculate_form_score(team)`, fără referință la `elo_tracker` |
| `H2HTracker`, `CornerCardTracker`, `FoulsTracker`, `ShotCountTracker` | (clase separate) | **NU** — cheiate independent, zero referință la `ELOTracker` |

**Concluzie, corectând o formulare imprecisă din mesajul anterior** („propagă modificările către feature-urile dependente" — prea vag): sunt exact **6 coloane** afectate, nu 18 ca la P3.5:

```
home_elo, away_elo,
home_offensive_rating, home_defensive_rating,
away_offensive_rating, away_defensive_rating
```

`home_form_score`/`away_form_score`, `h2h_modifier`/`h2h_meetings`, cornere/cartonașe/faulturi/șuturi — **neatinse**, nu se resetează, nu se ating.

### 1.2 Mecanism de activare — identic cu P3.5, infrastructură reutilizată

Writer Protection (`_missing_feature_columns()`, `sync/backfill_features.py:110-113`) scrie DOAR coloanele curent `NULL`. Cele 6 coloane de mai sus sunt azi 100% populate (verificat, §2) — codul nou, deja comis, NU le va recalcula până nu sunt resetate explicit. Strategia: **reset controlat → `run_backfill()` neschimbat** — exact pattern-ul dovedit la P3.5 Faza 3, zero cod nou.

### 1.3 De ce NU e nevoie de o etapă „Pasul A" (consolidare nume)

Spre deosebire de P3.5, nu există nicio problemă de identitate a echipelor de rezolvat aici — consolidarea din P3.5 e deja completă și verificată (0 nume brute rămase). `ELOTracker.ratings` e cheiat pe nume de echipă deja canonic. Singura schimbare e formula de actualizare, nu cheia de identitate.

### 1.4 Live serving — reconfirmat neatins

`oracle_engine.py._build_profile()` (linia :633) obține ELO prin `self.api.get_elo_rating(canonical)` — sursă externă (`oracle_api.py`, cache eloratings.net + `ELO_RATINGS_FALLBACK`), nicio citire din `ELOTracker` sau `match_history.home_elo`. Confirmat identic cu Impact Matrix din P3.5 (`P3_5_FAZA3_MIGRATION_PLAN_2026-07-15.md` §7): cele 6 coloane sunt consumate exclusiv de `ml_predictor.py` (antrenare), niciodată de fluxul de predicție live.

### 1.5 Descoperire operațională nouă — timpul de execuție depășește un singur run GitHub Actions

Spre deosebire de P3.5 (19.797 rânduri de rescris), această migrare afectează **toate cele 53.409 rânduri** — ELO se schimbă la fiecare meci din replay, nu doar la echipele fost-fragmentate. Pe baza throughput-ului real măsurat la P3.5 (run `#29419904484`: 19.829 rânduri scrise în 3547,1s ≈ 5,59 rânduri/sec), estimare: **53.409 / 5,59 ≈ 9.556s ≈ ~159 minute (~2h39min)**. `backfill.yml` are `timeout-minutes: 60` — **acest run NU se termină într-o singură execuție**. Vezi §3.4 pentru cele 2 variante de tratare.

---

## 2. Impact Analysis (măsurat pe producție, read-only, 2026-07-15)

| Metrică | Valoare |
|---|---:|
| Total rânduri `match_history` | 53.430 |
| Rânduri cu `actual_result` (procesate de `run_backfill()`) | **53.409** |
| Rânduri cu `actual_result` dar fără goluri (ar produce `gd=0` implicit, fallback sigur deja în cod) | 0 |
| Rânduri afectate (= rânduri de resetat) | **53.409** (100% din rândurile cu rezultat) |
| Coloane de resetat per rând | **6** (nu 18) |
| Total celule resetate | 53.409 × 6 = **320.454** |
| Coloane populate azi (verificat pe toate 6) | 53.409/53.409 (100%) — nimic e deja `NULL` |
| Estimare timp re-backfill | **~159 minute (~2h39min)**, pe baza throughput real P3.5 |
| Runs GitHub Actions necesare (la timeout actual 60 min) | **~3 rulări secvențiale** (vezi §3.4) |

---

## 3. Migration Plan

### 3.1 SQL complet — snapshot rollback (înainte de orice UPDATE)

```sql
CREATE TABLE IF NOT EXISTS match_history_mov_activation_backup_20260715 AS
SELECT id, home_elo, away_elo,
       home_offensive_rating, home_defensive_rating,
       away_offensive_rating, away_defensive_rating
FROM match_history
WHERE actual_result IS NOT NULL;
```

Doar cele 6 coloane + `id` — nu tot rândul (spre deosebire de P3.5, nimic altceva nu se schimbă aici, deci nu e nevoie de backup complet de rând).

### 3.2 SQL complet — reset controlat (6 coloane, toate rândurile cu rezultat)

```sql
UPDATE match_history
SET home_elo = NULL, away_elo = NULL,
    home_offensive_rating = NULL, home_defensive_rating = NULL,
    away_offensive_rating = NULL, away_defensive_rating = NULL
WHERE actual_result IS NOT NULL;
```

Fără listă de nume, fără CTE — scope-ul e simplu (toate rândurile cu rezultat), nu necesită lista de 313 nume ca la P3.5.

### 3.3 Ordinea operațiilor

1. Snapshot rollback (§3.1) — confirmă 53.409 rânduri salvate.
2. Reset (§3.2) — confirmă exact 53.409 rânduri cu toate 6 coloane simultan `NULL` după execuție.
3. `run_backfill()` — declanșare `backfill.yml` (`league=""`, global, `retrain_ml=false` — consistent cu P3.5, reantrenarea rămâne o decizie separată, ulterioară).
4. Verificare completitudine — dacă run-ul se oprește la timeout (60 min, vezi §3.4), rulează din nou identic — Writer Protection garantează reluare sigură, fără duplicare, fără rescriere.
5. Repetă pasul 4 până `SELECT COUNT(*) WHERE actual_result IS NOT NULL AND home_elo IS NULL` = 0.

### 3.4 Tratarea timpului de execuție — 2 variante, alegere explicită necesară

**Varianta A — rulări multiple manuale, fără nicio schimbare de configurare** (recomandat, risc minim): se declanșează `backfill.yml` de ~3 ori consecutiv, la timeout-ul actual de 60 min. Fiecare rulare scrie ce apucă, se oprește la timeout (proces oprit de GitHub Actions, nu de eroare de cod), rândurile deja scrise rămân corecte (Writer Protection). Nicio schimbare de fișier `.yml`, nicio decizie suplimentară de guvernanță.

**Varianta B — crește `timeout-minutes` în `backfill.yml`** (ex. la 180) pentru un singur run complet: schimbare minoră de configurare operațională (nu necesită ADR — CLAUDE.md: „detaliile de implementare... NU necesită ADR"), dar atinge un fișier de infrastructură comun (folosit și de sincronizări viitoare), nu izolat unei singure migrări. Recomand Varianta A dacă nu ceri explicit altfel.

### 3.5 Verificări post-execuție

1. `SELECT COUNT(*) WHERE actual_result IS NOT NULL AND home_elo IS NULL` — trebuie 0.
2. Zero valori negative pe cele 6 coloane (extensia sanity-check-ului deja folosită la P3.5).
3. **Verificare de convergență cu P3 Revalidation** (test nou, specific acestei migrări): rulează un walk-forward de verificare (read-only, fără scriere) pe `match_history` proaspăt actualizat — cifrele de Accuracy/Log Loss/Brier trebuie să se apropie de cele deja publicate în `P3_REVALIDATION_POST_P3_5_2026-07-15.md` pentru V2_damped (Accuracy 0,4992, Log Loss 1,0121, Brier 0,6051) — o discrepanță mare ar semnala o eroare de execuție, nu doar zgomot de reproductibilitate.
4. Total `match_history` neschimbat: 53.430 (invariant, ca la P3.5).

### 3.6 Plan de rollback complet

1. **Raport „înainte"**: snapshot-ul din §3.1, deja salvat ca tabelă separată înainte de orice UPDATE.
2. **Migrare aditivă-reversibilă**: reset (`UPDATE ... = NULL`) și re-backfill sunt ambele `UPDATE`-uri simple — numărul de rânduri rămâne 53.430 pe tot parcursul.
3. **Restaurare, dacă e necesară**: `UPDATE match_history m SET home_elo = b.home_elo, away_elo = b.away_elo, home_offensive_rating = b.home_offensive_rating, home_defensive_rating = b.home_defensive_rating, away_offensive_rating = b.away_offensive_rating, away_defensive_rating = b.away_defensive_rating FROM match_history_mov_activation_backup_20260715 b WHERE m.id = b.id;` — restaurează exact starea pre-migrare, rând cu rând.
4. **Reluare sigură după eșec/timeout**: idempotent prin design (Regula #13) — nicio acțiune specială necesară, doar rerulare.
5. **Criteriu de stop**: dacă verificarea de convergență (§3.5.3) arată o discrepanță majoră față de cifrele deja publicate, execuția se oprește înainte de a considera migrarea „finalizată" — raportul „înainte" rămâne disponibil pentru restaurare completă.

---

## 4. Ce NU decide acest document

- **Execuția propriu-zisă** — SQL-ul e arătat, nu rulat.
- **Varianta A vs. B din §3.4** — rămâne alegerea ta explicită.
- **Reantrenarea ML** (`retrain_ml`) — rămâne `false`, decizie separată, ulterioară, condiționată de verificarea de convergență din §3.5.3.
- **P4 (ELO Trend)** sau orice alt experiment din roadmap — nu se deschide automat după această migrare.

**Aștept aprobarea explicită a acestui Migration Plan înainte de orice execuție**, exact protocolul folosit la P3.5.
