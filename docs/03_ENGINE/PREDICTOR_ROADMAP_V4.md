# PREDICTOR_ROADMAP_V4.md — Football Oracle

**Status**: Analiză tehnică + roadmap argumentat — nu e document de arhitectură (nu modifică modelul de date/contracte), nu necesită ADR, nu e Frozen. Zero cod scris, zero fișier de producție modificat, zero migrare, zero schimbare de pipeline.
**Scop**: pregătirea etapei următoare de evoluție a predictorului (v4). Fiecare afirmație de mai jos e demonstrată direct din cod, din schema Supabase sau din date reale interogate live — unde nu s-a putut demonstra, se spune explicit.
**Precede**: `docs/03_ENGINE/FEATURE_ENGINEERING_ROADMAP.md` (analiză anterioară, parțial suprapusă — reconciliată la §5) și `docs/05_DATA_AUDIT/DATA_AUDIT_2026-07-12.md` (audit de date, sursele API).

---

## 0. Notă metodologică

Am citit efectiv codul relevant (`feature_engine.py`, `oracle_engine.py`, `oracle_api.py`, `ml_predictor.py`, `sync/backfill_features.py`), am interogat direct Supabase (proiect `Prediction`) pentru numere reale pe `match_history` (53.409 rânduri), și am **rulat local un antrenament XGBoost + permutation importance** pe un eșantion real de 12.000 rânduri, cu exact preprocesarea din `ml_predictor.py` (fillna cu mediana pe `FEATURE_COLUMNS`), ca să reverific — nu doar să citez — afirmațiile despre importanța feature-urilor. Rezultatele acelei rulări sunt raportate la §2.

Documentele Frozen declarate în `FROZEN_REGISTRY.md` (`ARCHITECTURE.md`, `DATABASE_SPEC.md`, `PIPELINE_SPEC.md`, `ENGINE_SPEC.md`, `CONFIG_SPEC.md`) **nu există fizic în repo** — gol deja cunoscut, documentat în `CLAUDE.md`. Nu pot verifica acest roadmap față de ele; nu pretind conformitate cu ceva ce nu pot citi.

---

## 1. Feature pipeline-ul actual — ce intră azi în predictor

Predicția finală (`oracle_engine.evaluate_match()`) combină patru componente independente:

### 1.1 Motorul Poisson (xG calibrat) — `feature_engine.calibrate_xg()`
Intrări: `home/away_offensive_rating`, `home/away_defensive_rating`, `home/away_form_score`, `baseline` (per ligă), `form_weight`, `dna_weight`, `home_advantage`, `away_penalty`, `defensive_cap`, `h2h_modifier`, `h2h_meetings`, `weather_penalty`. La rândul lor, `offensive_rating`/`defensive_rating` vin din `feature_engine.compute_team_offdef_rating()` (`oracle_engine.py:442-650`, `_build_profile()`), care combină:
- `avg_goals_for`, `avg_goals_against` — reale, din cascada de surse live (FreeLF/Odds API/football-data.org/TSDB/date naționale hardcodate).
- `avg_shots_on_target`, `avg_possession` — **vezi §2.1, sunt sintetice, nu reale, pentru echipele de club.**
- multiplicator ELO (blend 35% implicit, `elo_blend_weight`).

### 1.2 Blend ML — `ml_predictor.py`, `FEATURE_COLUMNS` (10 coloane)
```
home_offensive_rating, home_defensive_rating, away_offensive_rating, away_defensive_rating,
home_form_score, away_form_score, home_elo, away_elo, h2h_modifier, h2h_meetings
```
Antrenat pe `match_history`, blend cu Poisson prin `ml_blend_weight` (0.35 implicit) — **vezi §2, sunt aproape complet imputate în datele reale de antrenare.**

### 1.3 Penalizare accidentări — `injury_manager.py`, aplicată multiplicativ pe xG (înainte de blend ML), sursă: lineup FreeLF (`get_lineup_absences`). Funcțională, dar aplicată doar dacă `match["_freelf_event_id"]` există (nu garantat pentru toate meciurile — vezi §3).

### 1.4 Penalizare vreme — `oracle_api.get_weather()`, aplicată multiplicativ pe xG. Funcțională azi (Sprint 1A a reparat gaura de instrumentare provider_metrics), dar **fără cache** (fiecare evaluare = apel live nou — semnalat deja în auditul de cod anterior).

### 1.5 Monte Carlo — 10.000 simulări Poisson, produce piețele speciale (Over/Under, BTTS, Double Chance — activate Sprint 1A) și un scor de consistență față de modelul Poisson analitic. Nu alimentează ML-ul, doar output-ul de value betting.

**Ce NU intră deloc azi**: șuturi (nu doar pe poartă), cornere, cartonașe, faulturi, formație/lineup confirmat (fetch-uit de FreeLF dar aruncat — audit anterior), xG real măsurat, tendință ELO (`elo_history`, 39.575 rânduri, write-only), rest days (funcție scrisă, niciodată apelată — deja documentat, deja testat și respins prin ablație reală, vezi `REST_DAYS_VALIDATION.md`).

---

## 2. Descoperirea centrală: cele 10 FEATURE_COLUMNS sunt, în datele reale de antrenare, aproape complet imputate — nu reale

Aceasta e cea mai importantă descoperire a acestui audit și schimbă fundamental răspunsul la întrebarea "sunt cele 10 feature-uri alegerea corectă".

### 2.1 `avg_shots_on_target` / `avg_possession` sunt sintetice pentru toate echipele de club (nu doar parțial — verificat în FIECARE sursă live)

| Sursă | Cod | Șuturi pe poartă | Posesie |
|---|---|---|---|
| FreeLF standings (**sursa PRIMARĂ**, v2.3) | `oracle_engine.py:500` | `sot = gf * 0.45` | `pos = 50.0` |
| Odds API `/scores` | `oracle_api.py:656` | `shots_on_goal: round(gf * 3.5, 1)` | `possession: 50.0` |
| football-data.org standings | `oracle_engine.py:544` | `gf_avg * 0.45` | `50.0` |
| TheSportsDB | `oracle_api.py:812` | `round(gf * 3.5, 1)` | `50.0` |
| Backfill istoric (`team_pre_match_rating`) | `sync/backfill_features.py:549-550` | `avg_gf * 0.45`, comentariu explicit în cod: `# proxy — șuturi pe poartă absente 100% din Kaggle` | `50.0`, comentariu: `# neutru — posesie absentă 100% din Kaggle` |
| Date naționale hardcodate (`NATIONAL_TEAM_STATS`) | `mappings.py` | **reale, curate manual** (~50 echipe naționale) | **reale** |

Consecință matematică demonstrabilă: în `compute_team_offdef_rating()`, `pos_norm = ((avg_possession-30)/40)*0.5` — dacă `avg_possession` e mereu 50.0, `pos_norm` e o **constantă** (0.25) pentru orice echipă de club, adăugată identic la toată lumea. `possession_weight` (25% din formula ponderată) nu diferențiază nicio echipă de nicio altă echipă azi — contribuie doar un offset fix. `shots_ot_weight` (30%) operează pe o valoare direct proporțională cu `avg_goals_for` (doar rescalată cu alt plafon), deci nu adaugă o dimensiune de informație independentă de golurile deja contorizate separat prin `goals_weight`.

**Concluzie verificată**: recalibrarea per-ligă tunează azi `shots_ot_weight`/`possession_weight` pe date care nu poartă informație reală despre șuturi/posesie — doar o transformare redundantă/constantă a golurilor deja folosite.

### 2.2 Cele 10 FEATURE_COLUMNS din `match_history` — populare reală, verificată direct în Supabase

```sql
-- rulat direct pe proiectul Prediction, 53.409 rânduri cu rezultat cunoscut
both_backfill_and_elo: 0        -- 0%
backfill_only (fără ELO):  3.816    -- 7,1%
elo_only (fără restul):   25.104    -- 47,0%
neither (toate 10 NULL): 24.489    -- 45,9%
```

**Zero rânduri au toate cele 10 FEATURE_COLUMNS reale simultan.** ~46% din setul de antrenare are un vector de feature-uri complet imputat (constantă, aceeași pentru toate aceste rânduri — zero informație discriminativă). Alte 47% au ELO real dar restul imputat. Doar 7,1% au ratingul ofensiv/defensiv/formă/H2H reale, dar ELO imputat.

`ml_predictor.py:210`: `X = df[FEATURE_COLUMNS].astype(float).fillna(df[FEATURE_COLUMNS].astype(float).median())` — confirmat direct din cod, fără ambiguitate.

**Nu pot demonstra** de ce cele două subseturi (backfill_only, elo_only) sunt perfect disjuncte — `run_backfill()` (`sync/backfill_features.py:670-683`) scrie `home_elo`/`away_elo` în ACELAȘI dict cu restul, deci teoretic ar trebui completate împreună. Contradicția aparentă dintre cod și date rămâne nedemonstrată — necesită o investigație separată, dedicată (posibil: un import istoric anterior a populat ELO direct din CSV Kaggle pe un subset de rânduri niciodată atinse de `run_backfill()`, sau invers). Semnalez explicit, nu presupun o cauză.

### 2.3 Reverificare independentă a importanței feature-urilor (rulare reală, azi, nu doar citare)

Antrenament XGBoost (aceiași hiperparametri ca producție) + `sklearn.inspection.permutation_importance`, pe eșantion real de 12.000 rânduri (75/25 split), preprocesare identică cu `ml_predictor.py`:

```
away_elo                  0.04880  (+/- 0.00443)
home_elo                  0.03587  (+/- 0.00297)
h2h_modifier               0.00264
away_defensive_rating      0.00260
h2h_meetings                0.00211
away_form_score              0.00176
home_form_score               0.00151
away_offensive_rating           0.00122
home_offensive_rating             0.00062
home_defensive_rating              0.00027
```
ELO domină ceilalți 8 feature de **15-20×**. Consistent direcțional cu claim-ul anterior din `FEATURE_ENGINEERING_ROADMAP.md` ("~0.123 vs. <0.004") — magnitudinea exactă diferă (metodologie diferită: eșantion aleator de 12k vs. walk-forward complet pe 53k), dar concluzia calitativă e identică și acum reverificată independent, azi.

**Baseline vs. model real**: distribuția claselor în eșantion — Home 44,0%, Away 29,9%, Draw 26,0%. Un predictor trivial ("mereu Home") ar obține 44,0% acuratețe. Modelul XGBoost antrenat obține 47,3% (rulare locală) / 46,71% (`ml_model_status`, walk-forward complet, azi). **Modelul actual bate baseline-ul naiv cu doar ~3 puncte procentuale.** Asta e o consecință directă, cuantificată, a faptului că 93% din rânduri au cel puțin o parte semnificativă din feature-uri imputate (median), nu reale.

**Concluzie centrală, cu impact direct asupra §6**: problema principală a predictorului azi nu e "lipsesc feature-uri noi" — e că **feature-urile deja alese sunt corecte conceptual, dar aproape nepopulate cu date reale**. Orice feature nou (șuturi, posesie reale, cornere) ar suferi exact aceeași soartă (imputare majoritară) dacă nu rezolvăm mai întâi acoperirea backfill-ului.

---

## 3. Date deja în baza de date, nefolosite (reconciliat cu `DATA_AUDIT_2026-07-12.md`)

| Dată | Tabelă | Populare | Folosită? |
|---|---|---|---|
| `home/away_shots`, `shots_on_target`, `possession`, `xg_actual`, `stats_source` | `match_history` | 0/53.409 | Nu — vezi `get_match_statistics()` deja scrisă, niciodată apelată (audit anterior; Discovery Probe API-Football înlocuiește ipoteza FreeLF, oprit fără rezultat concludent — vezi Sprint 1B/decizia din 2026-07-12) |
| Tendință ELO (istoric complet) | `elo_history` | 39.575 rânduri, write-only | Nu — nicio interogare `SELECT` nicăieri în cod |
| `home_xg_pred`, `weather_penalty`, `mc_prob_home/draw/away` | `match_history` | 21/53.409 (0,04%) | Nu — deja eliminate din `FEATURE_COLUMNS` prin ablație reală (comentariu în `ml_predictor.py:39-46`) |
| `formation`, `confirmed` din lineup FreeLF | — (doar în memorie) | fetch-uit, aruncat | Nu — `injury_manager.py` citește doar `unavailable` |
| `shadow_predictions`, `experiment_registry` | Supabase | 0 rânduri | Infrastructură completă (Learning Core, Champion/Challenger), niciodată exercitată cu un experiment real |

---

## 4. Date calculate în runtime, pierdute — cu precizarea EXACTĂ a mecanismului

Nu e o problemă de cod care aruncă date — `_cache_prediction()` (`oracle_engine.py:1079-1139`) scrie explicit, într-un singur upsert, TOATE cele 10 `FEATURE_COLUMNS` + `home_xg_pred`/`away_xg_pred`/`weather_penalty`/`mc_prob_home/draw/away` simultan, când `evaluate_match()` rulează live prin aplicație.

**Problema reală, demonstrată**: doar 21 din 53.409 rânduri au vreodată trecut prin acest cod (`weather_penalty` populat 0,04%). Marea majoritate a `match_history` (53.388 rânduri) vine din **import bulk istoric** (Kaggle/openfootball/football-data.org), nu din predicții live ale aplicației — deci semnalele calculate live (vreme, accidentări la momentul predicției, MC) nu sunt "pierdute" printr-un bug, ele **pur și simplu nu există pentru meciuri jucate înainte ca aplicația să le fi evaluat vreodată live**. E o limitare de fond, nu de implementare: vremea/accidentările istorice pentru un meci din 2022 nu pot fi reconstruite retroactiv fără o sursă externă dedicată (WeatherAPI `/history.json`, neconfirmat — vezi audit anterior).

Pentru meciurile evaluate live DE ACUM ÎNAINTE, mecanismul de captură deja funcționează corect — problema e volumul (0,04% din istoric), nu lipsa infrastructurii.

---

## 5. Evaluare feature-uri candidate

| Candidat | Cost implementare | Cost întreținere | Impact probabil | Testabil Champion/Challenger azi? |
|---|---|---|---|---|
| **Completare backfill (rezolvă disjuncția §2.2)** | Mediu — investigație + eventual re-rulare `run_backfill()` pe tot istoricul | Mic (o singură rulare + monitorizare) | **Mare** — condiție necesară pentru ca ORICE altceva de mai jos să conteze | Nu se aplică (nu e feature nou, e reparație de acoperire a celor existente) |
| **ELO Trend** (formă ELO ultimele 5 meciuri) | Mic — date deja în `elo_history`, o funcție de agregare nouă | Mic | Necunoscut, dar plauzibil — singurul candidat cu date reale deja 100% disponibile | **Da** — `ChallengerRunner` + `shadow_testing.evaluate_experiment()` există și rulează deja zilnic (`experiment_registry`, 0 experimente înregistrate până acum) |
| **Rest days** | Mic — funcție deja scrisă (`feature_engine.rest_days_modifier`) | Zero | **Deja testat și respins** prin ablație reală (`REST_DAYS_VALIDATION.md`) — nu se reintroduce fără date noi |  N/A |
| Șuturi pe poartă / posesie REALE | Mediu-Mare — sursă de date nedemonstrată (FreeLF respins Sprint 1B; API-Football respins pentru backfill din motive de quota, discovery probe încă neconcludent) | Mediu | Necunoscut — condiționat de #1 (backfill) ca să nu repete aceeași soartă de imputare | Da, IPOTETIC — dar fără sursă de date confirmată, nu se poate proiecta un experiment real azi |
| Lineup confirmat / formație | Mic — deja fetch-uit, doar aruncat | Zero | Marginal — mai degrabă crește certitudinea penalizării de accidentări existente decât feature nou | Da, dacă se conectează |
| Statistici API-Football (cornere/cartonașe/faulturi) | Mediu-Mare — acoperire pe planul gratuit neconfirmată (Discovery Probe pregătit, fără rezultate reale încă) | Mediu | Necunoscut | Da, condiționat de rezultatul probei |
| xG real extern (Understat/Opta) | Mare — provider nou, cost posibil | Mare | Teoretic cel mai puternic predictor cunoscut (literatură), dar cost/acces neclar | Da, dacă se achiziționează |

---

## 6. Sunt cele 10 FEATURE_COLUMNS cea mai bună alegere?

**Răspuns demonstrat, nu presupus**: setul conceptual (ELO, rating ofensiv/defensiv, formă, H2H) e rezonabil — nu găsesc dovezi că ar trebui înlocuit cu altceva. Problema verificată nu e alegerea feature-urilor, e **acoperirea lor reală în datele de antrenare** (§2.2: 0% rânduri complete, 46% complet imputate). Orice discuție despre "ce feature nou să adăugăm" e prematură dacă feature-urile deja alese sunt majoritar imputate — un feature nou ar avea aceeași soartă, dacă nu mai rea (populare și mai rară inițial).

Nu există în proiect niciun feature deja calculat, cu acoperire reală bună, care merită "promovat" și nu e deja în `FEATURE_COLUMNS` — cu o singură excepție parțială: **tendința ELO** (din `elo_history`, teoretic 100% derivabilă din date deja complete acolo unde ELO există), care nu concurează cu problema de acoperire a celorlalte 8 feature-uri, fiindcă folosește exclusiv date deja populate.

---

## 7. Roadmap tehnic prioritizat

Ordonat după principiul cerut explicit: infrastructură deja existentă, complexitate minimă, testabil prin experiment, nimic fără dovadă.

**Pasul 1 — Investighează și repară acoperirea backfill-ului** (§2.2). Fără asta, orice altceva de mai jos e construit pe aceeași fundație imputată. Nu e un feature nou — e o reparație de date, cu cel mai mare impact posibil asupra a tot ce urmează.

**Pasul 2 — ELO Trend, ca shadow feature/experiment real** prin Learning Core existent (`ModelRegistry` → algoritm nou înregistrat → `ChallengerRunner` → `shadow_testing.evaluate_experiment()`, deja scris, deja rulează zilnic, niciodată exercitat). Primul experiment real care ar popula efectiv `experiment_registry` — validează întregul flux Champion/Challenger cu un caz simplu, cu risc minim, înainte de a-l folosi pe ceva mai complex.

**Pasul 3 — Feature Pipeline generic** (deja cerut de utilizator într-un sprint anterior: Provider → Normalizare → Persistare → Backfill → Learning Core → Shadow Testing → Promotion Gate) — construit O SINGURĂ DATĂ, folosind ELO Trend (Pasul 2) ca prim caz real de validare a pipeline-ului, nu ca proiect teoretic separat.

**Amânat, explicit, până la dovezi de acoperire**: șuturi/posesie reale, statistici API-Football detaliate, xG extern — toate condiționate de o sursă de date confirmată (niciuna confirmată azi) și de rezolvarea Pasului 1, altfel repetă aceeași problemă.

**Promotion Engine / Champion Manager / promovare automată** — rămân neimplementate (`CLAUDE.md`, status curent) — necesare înainte ca orice experiment din Pasul 2+ să poată ajunge vreodată în producție fără intervenție manuală. Nu fac parte din scope-ul acestui roadmap de feature-uri, dar sunt o dependință structurală pentru ca "nimic nu intră în producție fără dovezi" să fie complet automatizabil, nu doar posibil manual.

---

## 8. Limite explicite ale acestui audit

- Cauza exactă a disjuncției `backfill_only`/`elo_only` (§2.2) — nedemonstrată, semnalată explicit.
- Acoperirea reală API-Football pentru `/fixtures/statistics` — necunoscută, Discovery Probe pregătit dar fără rulare reală încă (rețea indisponibilă în acest mediu).
- Impactul real al ELO Trend, al șuturilor/posesiei reale (dacă ar exista) — necunoscut până la un experiment real; orice cifră de impact "estimat" ar fi presupunere, nu dovadă — de-asta nu apare în tabelul de la §5.
