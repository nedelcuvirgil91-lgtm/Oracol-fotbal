# BASELINE FAZA 1 — Football Oracle (2026-07-19)

> **Snapshot istoric înghețat.** Acest document este fotografia exactă a
> proiectului la închiderea Fazei 1. Nu se modifică în practică. Dacă, în
> mod absolut excepțional, se descoperă că baseline-ul conține o eroare
> factuală (nu o evoluție a proiectului), orice modificare necesită un ADR
> explicit care documentează eroarea și păstrează trasabilitatea. O fază
> nouă primește un baseline nou — acesta nu se actualizează niciodată.

**Scope-ul Fazei 1**: pipeline-ul de fixtures și integrarea surselor de
date. Închisă de utilizator la 2026-07-19, pe scope-ul declarat.

## Commit de referință

- Cod: `main` @ `8a68a20` — „Fix TSDB fixture completeness for Romania
  SuperLiga via multi-endpoint reconciliation (#28)"
- Momentul citirilor live din acest document: **2026-07-19** (toate valorile
  de mai jos sunt citite din sursele vii la semnare, nu copiate din alte
  documente)

## Provideri activi per ligă (din `mappings.LEAGUE_PROVIDERS`, la semnare)

| Ligă | Provideri declarați suportați (True) |
|---|---|
| Premier League | football_data, espn, tsdb, odds, freelf |
| La Liga | football_data, espn, tsdb, odds, freelf |
| Serie A | football_data, espn, tsdb, odds, freelf |
| Bundesliga | football_data, espn, tsdb, odds, freelf |
| Ligue 1 | football_data, espn, tsdb, odds, freelf |
| Champions League | football_data, espn, tsdb, odds, freelf |
| Europa League | espn, tsdb, odds, freelf |
| Romania SuperLiga | espn, tsdb, odds¹ |
| World Cup 2026 | football_data, espn, tsdb, odds, freelf |
| MLS | espn, tsdb, odds |
| Conference League | espn, tsdb |

¹ Declarația `odds: True` pentru Romania SuperLiga este **contrazisă de
dovezi live** (2026-07-18: `soccer_romania_1_liga` nu există la Odds API —
HTTP 404 „Unknown sport", zero chei `romania` în catalogul de 170 intrări).
Consemnat ca inexactitate cunoscută de mapare — vezi Known Limitations.
Pentru Romania SuperLiga, fixtures se obțin real prin reconcilierea TSDB
în 3 endpointuri (PR #28); ESPN întoarce 0 evenimente pentru această ligă
la data semnării.

## Metrici Champion (citite LIVE din `ml_model_status`, id=1)

- `trained_at`: **2026-07-19 11:04:06 UTC** (reantrenat chiar în ziua semnării)
- `samples_used`: **53.409** meciuri
- `accuracy`: **0.4984**
- `log_loss`: **1.0122**
- Brier mediu (walk-forward): **0.6052**
- `model_version`: 1; validare walk-forward 5 folds, expanding window
  (fold1 acc=0.4763/brier=0.6267 → fold5 acc=0.5319/brier=0.5811)

**Avertisment de onestitate (moștenit din
`ML_RETRAIN_BENCHMARK_POST_MOV_ACTIVATION_2026-07-15.md`)**: cifrele
Champion-ului actual NU izolează efectul vreunei schimbări individuale —
între măsurătorile istorice s-au schimbat simultan mai multe componente.
Exact de aceea există acest baseline: de la punctul zero încolo, disciplina
Champion vs. Challenger elimină acest tip de ambiguitate.

## Metrici-adevăr (definiția oficială)

- **Metrici de promovare** (toate trei, simultan semnificativ mai bune —
  `shadow_testing.evaluate_experiment()`): **Accuracy, Log Loss, Brier Score**.
- **ROI: metrică OBSERVATĂ, nu de promovare.** Motivare: ROI depinde de
  bookmaker, marjele caselor, stake management și pragul de value bet — un
  model statistic mai bun poate avea temporar ROI mai slab. ROI se
  monitorizează separat până când sistemul de betting este complet stabil.

## Known Limitations (stări cunoscute la punctul zero — NU regresii ale Fazei 1)

1. **Prediction Engine nu este încă Database-First** — limitare
   arhitecturală PRE-EXISTENTĂ Fazei 1, demonstrată de auditul
   Petrolul–Dinamo (2026-07-19): motorul construiește profiluri din
   fallback-uri de provider (inclusiv eșantioane de 1 meci TSDB cu șuturi
   sintetice = goluri × 3.5), deși `match_history` conține 1.977 meciuri
   SuperLiga, ELO de club actualizat și 38–40 meciuri de formă per echipă.
   Documentată și tratată prin **ADR-035** (Faza 2, D1–D4). Nimeni nu
   trebuie să creadă, peste șase luni, că această problemă a apărut după
   închiderea Fazei 1 — ea exista dinainte și era nevăzută.
2. **Statisticile de meci pentru România nu sunt importate** — cornere/
   șuturi/faulturi/cartonașe/goluri la pauză: 0/1.977 rânduri populate în
   `match_history` (comparativ: La Liga 760/1.140). Gol de pipeline de
   import, task separat de ADR-035 (P1).
3. **3 teste fragile la dată** în `test_oracle_api_tsdb_per_league_gate.py`
   (hardcodează `"2026-07-18"`) — pică de la 19.07 încolo; pre-existente,
   fix programat ca PR separat, fără atingere de cod de producție.
4. **`odds: True` pentru Romania în mapări** — contrazis de dovezi live
   (nota ¹); corectura ține de întreținerea mapărilor, nu de Faza 1.
5. **Branch remote rămas necurățat** — `claude/continua-faza-1-adr5-o52jat`
   nu a putut fi șters automat (HTTP 403, limitare de mediu). Acțiune
   manuală rămasă.

## Definition of Done — instanța Fazei 1 (bifele reale, la închidere)

### Nivel 1 — Engineering DoD (verificat 2026-07-19)

```
☑ pytest tests/: 675 passed, 2 skipped — zero eșecuri NOI
    (3 eșecuri pre-existente fragile la dată — Known Limitations #3)
☑ Verificare live end-to-end pe main (GH Actions run 29684418450):
    Romania SuperLiga 4/4 meciuri, celelalte ligi fără regresii
☑ security-review: PR #26/#28 fără secrete noi introduse
☑ architecture-review: zero dependențe noi între module
☐ sync/run_daily.py --dry-run
```
> Excepție (☐ dry-run): nerulabil din mediul sesiunii (rețea blocată către
> provideri, HTTP 000 demonstrat). Dovadă compensatorie: sync-ul real
> zilnic a rulat azi cu succes (`ml_model_status.trained_at` = 2026-07-19
> 11:04 UTC, `elo_ratings.updated_at` = 2026-07-17). Rămâne nebifat, nu
> „aproape bifat".

### Nivel 2 — Product DoD (bifat de utilizator, 2026-07-19)

```
☑ Aplicația pornește și dashboard-ul se încarcă
☑ Cele 4 meciuri SuperLiga afișate (echipe, date, fără duplicate)
☑ Predicțiile sunt generate
☑ „Reîncarcă meciuri" funcționează
☑ Fără regresii vizibile pe celelalte ligi
☑ Utilizatorul confirmă funcționalitatea (mesaj explicit, 2026-07-19)
```
Notă: cotele pentru SuperLiga nu sunt afișate — providerul de cote nu
acoperă liga (Known Limitations #4), stare cunoscută, nu regresie.

### Nivel 3 — Governance DoD

```
☑ Baseline creat (acest document)
☑ Frozen Registry actualizat
☑ ADR-uri închise (ADR-035 aprobat rev.3; niciun ADR în lucru pentru Faza 1)
☐ Branch-uri curățate
☑ Monitorizări oprite (subscripția PR #28 închisă la merge)
☑ Faza declarată oficial închisă (utilizator, 2026-07-19)
```
> Excepție (☐ branch-uri): branch-ul `claude/continua-faza-1-adr5-o52jat`
> nu a putut fi șters automat (HTTP 403 — limitare a mediului). Acțiune
> manuală rămasă.

## De aici încolo

Faza 2 = **Database-First Prediction Engine** (ADR-035, D1–D4, în ordinea
de execuție obligatorie din ADR), urmată abia apoi de Learning Core. Orice
progres viitor se măsoară față de acest punct zero.
