# ADR-024 — Canonical Match Identity & Data Contract (cross-provider)

## Status

**Accepted** — 2026-07-16. Documentează contractul de identitate și problema demonstrată;
**nu alege și nu autorizează** o soluție tehnică de remediere. Alegerea soluției și
autorizarea implementării rămân o decizie ulterioară, separată, a Owner-ului
(„Architecture Review" după acest ADR).

## Context

### Descoperire

Problema a fost descoperită nu printr-un bug, crash sau test picat, ci prin verificarea
unui Acceptance Criterion semantic impus explicit de Owner pentru Phase 3 din Execution
Plan-ul ADR-023 („Canonical Live ELO Snapshot"): *pentru fiecare echipă distinctă din
`match_history`, trebuie să existe exact o valoare Current ELO rezolvabilă, fără
ambiguitate*. Verificarea acestui criteriu a arătat că 14 echipe aveau două valori
diferite de ELO la cea mai recentă dată — investigația ulterioară a demonstrat că
sursa e sistemică, nu punctuală.

### Amploarea demonstrată

- **3.501 grupuri de meciuri duplicate / 7.002 rânduri** (~13,1% din cele 53.409 rânduri
  cu `actual_result` din `match_history`), interval 2023-08-11 → 2025-05-25, **110 echipe
  distincte**, exact 5 ligi: Premier League↔E0, La Liga↔SP1, Serie A↔I1, Bundesliga↔D1,
  Ligue 1↔F1.
- **100% (3.501/3.501)** din perechi au `actual_home_goals`/`actual_away_goals`/
  `actual_result` identice — dovadă directă că fiecare pereche e **același meci real**,
  scris de două ori.
- Verificare de exhaustivitate independentă: `distinct_matches` (grupare pe cheie
  naturală, tot setul de 53.409 rânduri) = 49.908; `53.409 − 49.908 = 3.501` — coincide
  exact, confirmă că nu există alte grupuri duplicate nedescoperite în universul
  meciurilor rezolvate.
- **Origine root-cause identificată exact**: rularea GitHub Actions `28903982046`
  (workflow `import_kaggle.yml`), pasul „Run historical import", 2026-07-07T22:47:33Z
  → 22:48:54Z (fereastră care încadrează exact `created_at` al rândurilor `kaggle_`
  afectate). La commit-ul exact al acelei rulări (`4573a012849a3eda739edeb3fb7b5c32338943a3`),
  `sync/import_historical.py` scria `league_code = _safe_str(r.get("Division")) or None`
  — codul brut din CSV, fără normalizare — iar `mappings.py` nu conținea încă
  `normalize_league_name()`/`LEAGUE_ALIASES`. Bug-ul de cod a fost reparat ulterior în
  cod (funcția există azi), dar cele 3.501 grupuri deja scrise nu au fost niciodată
  remediate retroactiv.
- **Recurență live, confirmată, nu doar istorică**: aceeași clasă de defect a fost
  găsită activă azi, la World Cup 2026 — 3 perechi de meciuri (Belgium-Senegal 07-01,
  Australia-Egypt 07-03, England-Argentina 07-15), scrise de doi writeri suplimentari
  (`odds_<hash>` — fetch de cote, scriere directă în `match_history`; `espn_<id>` —
  sync ESPN), ambii localizați exact în `oracle_api.py` (liniile 591, 754). Momentan
  dormante (`actual_result IS NULL` pe toate rândurile implicate), dar demonstrat
  (`sync/sync_results.py:339-346`, comentariu explicit dintr-o sesiune anterioară) că
  mecanismul de atașare a rezultatelor scrie pe **toate** rândurile găsite pentru
  același (home, away, league, date) — deci aceste perechi **vor** deveni active de
  îndată ce rezultatele reale sosesc.

### Cauza structurală (nu doar cea punctuală)

`match_history` are un singur mecanism de unicitate real: `idx_match_history_fixture`
(UNIQUE INDEX pe `fixture_id`). Există **minimum 4 scheme distincte de generare a
`fixture_id`**, fiecare per-provider (`kaggle_<hash>` — 47.653 rânduri, `fd_<id>` —
5.756 rânduri, `odds_<hash>` — 19, `espn_<id>` — 4), niciodată reconciliate între ele.
Codul propriu conține afirmații explicite, dar false, ale acestei garanții — de ex.
`sync/sync_matches.py`, docstring: „Elimină duplicatele automat prin fixture_id unic."
Indexul unic previne un duplicat DOAR în interiorul aceleiași scheme (același
provider); nu oferă nicio protecție cross-provider.

Investigația a găsit **minimum 6 definiții concurente, parțial suprapuse, ale
identității unui meci**, construite izolat, fiecare pentru nevoia locală a unui singur
consumator, niciodată unificate:

1. `mappings.match_key()` — `(home, away, kickoff_date)`, **fără ligă**.
2. `sync/bootstrap_league_learning.normalize_and_dedupe()` — `(home, away, league
   normalizat, kickoff_date)`.
3. `sync/sync_results.update_results_in_supabase()` — `(home, away, league EXACT,
   nenormalizat, kickoff_date)` + fallback pe `fixture_id=fd_{id}` — singurul loc care
   admite explicit posibilitatea de duplicate, dar doar pentru cazul unde liga
   coincide exact.
4. `services/match_stats_backfill_service.py` / `services/odds_backfill_service.py` —
   `(kickoff_date, home normalizat, away normalizat)` + filtru extern de ligă + scor
   identic obligatoriu (fail-closed).
5. `idx_match_history_fixture` — `fixture_id` opac, per-provider, impus de schemă.
6. `ELOTracker`/`fetch_all_matches()` (ADR-022/023) și `ml_predictor.get_training_data()`
   — **nicio noțiune de identitate** — fiecare rând procesat/antrenat independent.

### Impact demonstrat (nu ipotetic)

- **ADR-022 (ELOTracker MOV V2_damped)**: divergență măsurată 98,9%/98,86% pe cele
  7.002 valori comparate; medie 10,27 puncte ELO, mediană 9, maxim 43 (0 cazuri peste
  50). Replay-ul cronologic tratează fiecare duplicat ca eveniment real separat.
- **ADR-023 (`home_elo_after`/`away_elo_after`)**: moștenește identic corupția — construit
  pe același replay.
- **`home_offensive_rating`/`home_defensive_rating`**: demonstrat regenerate în aceeași
  buclă, din aceeași stare `elo_tracker`, prin lanțul `elo_to_offensive_multiplier()`
  → `compute_team_offdef_rating()` (`sync/backfill_features.py`, liniile 736-803,
  910-966).
- **ML**: modelul activ în producție azi (`ml_model_status`, `trained_at=2026-07-16
  08:45:52`, `samples_used=53409`) a fost antrenat **după** introducerea duplicatelor
  (2026-07-07), pe tot dataset-ul, fără nicio excludere. `used_for_training` există în
  schemă (chiar cu index dedicat, `idx_match_history_training`) dar nu e filtrat
  nicăieri în `get_training_data()` — flag mort.
- **Prediction Engine live, Dashboard, League Learning, `sync_results` recalibration**:
  demonstrat neafectate azi — `oracle_engine.py` citește ELO din `oracle_api` extern,
  nu din `match_history`; `_recalibrate_for_result()` folosește doar xG prezis vs.
  goluri reale; League Learning exclude complet acest corpus prin filtrul exact de
  ligă.

## Decizie

Acest ADR **stabilește contractul formal de identitate**, nu mecanismul tehnic de
aplicare a lui. Contractul, derivat direct din dovezile de mai sus:

### Contract formal de identitate a unui meci

1. **Un meci real trebuie să aibă exact o identitate canonică, unică la nivelul
   întregului sistem** — nu una per provider, nu una per consumator.
2. **Identitatea canonică nu poate depinde de eticheta brută de ligă** a niciunei
   surse — cazul demonstrat (Premier League vs. E0) arată că liga poate varia
   sintactic între provideri pentru același meci real.
3. **Identitatea canonică trebuie derivată din câmpuri deja normalizate** (echipe,
   dată) — nu din valori brute, nenormalizate, așa cum face azi
   `update_results_in_supabase()`.
4. **Identitatea canonică trebuie să fie independentă de orice schemă de `fixture_id`
   a unui provider individual** — niciuna dintre cele 4 scheme găsite (`fd_`,
   `kaggle_`, `odds_`, `espn_`) nu se poate reconcilia cu altele prin ea însăși.
5. **Identitatea canonică trebuie să fie vizibilă/aplicabilă exact la punctele unde
   corupția demonstrată s-a produs** — `ELOTracker`/`fetch_all_matches()` și
   `ml_predictor.get_training_data()`, ambele fără nicio noțiune de identitate azi.
6. **Contractul trebuie să fie o singură sursă de adevăr**, consumată identic de toți
   cei minimum 6 consumatori identificați — nu re-implementată independent per modul,
   așa cum e cazul azi.
7. Pe baza datelor curente (verificat empiric, nu doar presupus): cheia (echipe
   normalizate + dată) explică 100% din cele 3.504 grupuri de duplicate găsite
   (3.501 istorice + 3 World Cup 2026) — nu s-a găsit niciun caz de rematch legitim
   (același cuplu de echipe, aceeași dată, evenimente reale diferite) care ar necesita
   granularitate suplimentară. Această observație e asupra datelor actuale, nu o
   garanție universală pentru orice date viitoare.

### Ce NU decide acest ADR

- Nu alege mecanismul tehnic (constrângere UNIQUE pe cheie naturală, tabelă de
  crosswalk/identitate, regulă de precedență de provider, upsert idempotent pe cheie
  naturală, sau altă variantă) — toate au fost doar **comparate**, nu selectate, în
  cercetarea premergătoare acestui ADR.
- Nu decide dacă/cum se deduplichează cele 3.501 grupuri deja existente în producție.
- Nu decide dacă/cum se reconstruiește ELO (ADR-022), Feature Engineering, sau se
  reantrenează ML.
- Nu decide dacă/când se reia Phase 4 din ADR-023.

Toate acestea rămân decizii ulterioare, separate, condiționate de o revizuire
arhitecturală explicită a Owner-ului asupra unei propuneri tehnice viitoare.

## Consecințe

- **Architecture Freeze rămâne activ** pe Phase 4+ din ADR-023 până la satisfacerea
  acestui contract — validarea (Phase 5) și servirea live (Phase 6) ar rula altfel pe
  date demonstrat corupte.
- **ADR-022 și ADR-023 rămân valide ca decizii de design** — problema nu e de
  formulă/arhitectură a replay-ului, ci de contractul de date pe care acesta îl
  presupune implicit și pe care intrarea curentă îl încalcă. Nicio modificare asupra
  acestor documente Frozen nu e necesară sau propusă aici.
- Orice propunere tehnică viitoare pentru acest contract va necesita, minim: o decizie
  asupra celor 3.501+ grupuri deja existente, un rebuild ELO/Feature Engineering
  (playbook operațional deja exersat de 3-4 ori în acest proiect, „Varianta A"), o
  reantrenare ML, și o metodologie de validare (reutilizabilă din criteriul deja
  folosit la Phase 3 — „exact o valoare Current ELO per echipă").
- Riscul de recurență e activ, nu doar istoric — perechile `odds_`/`espn_` de la World
  Cup 2026 vor deveni corupătoare de îndată ce rezultatele reale sosesc prin
  `update_results_in_supabase()`, dacă acest contract nu e aplicat înainte de acel
  moment.

## Referințe

- ADR-022 — Elo Margin of Victory V2 Damped (`docs/00_GOVERNANCE/ADR-022-elo-margin-of-victory-v2-damped.md`)
- ADR-023 — Canonical Live ELO Source (`docs/00_GOVERNANCE/ADR-023-canonical-live-elo-source.md`)
- `docs/03_ENGINE/TEAM_IDENTITY_AUDIT.md` — audit anterior, normalizare nume echipe la
  scriere (context adiacent, nu identic — acela tratează identitatea unei ECHIPE, nu a
  unui MECI).
- Seria de rapoarte de cercetare din această sesiune (Architecture Gate Audit,
  Follow-up Impact Audit, Architecture Review Board Verdict v2.0, Research Task —
  Canonical Match Identity, Research Task — Complete Match Lifecycle) — conversaționale,
  nu persistate separat ca documente, la fel ca precedentul notat în ADR-023.
