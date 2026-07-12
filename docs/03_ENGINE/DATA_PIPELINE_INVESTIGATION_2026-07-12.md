# DATA_PIPELINE_INVESTIGATION_2026-07-12.md — Football Oracle

**Status**: Investigație tehnică — cauza unei contradicții cod/date semnalate în `PREDICTOR_ROADMAP_V4.md` §2.2. Zero cod modificat, zero migrare, zero rulare de backfill. Nu e Frozen, nu necesită ADR.
**Metodă**: fiecare afirmație de mai jos e demonstrată prin cod citit direct, query SQL rulat pe Supabase (proiect `Prediction`) sau istoric real GitHub Actions — nu presupunere.

---

## Rezumat — cauza exactă

**Cauza e o secvențiere greșită în timp, nu un bug de cod curent și nu o migrare care a stricat date.**

1. `sync/backfill_features.py` (`run_backfill()`) a rulat **o singură dată, vreodată** — 2026-07-03, 05:52 UTC, cu succes (verificat direct în istoricul GitHub Actions al `.github/workflows/backfill.yml` — 1 rulare totală).
2. Importul istoric masiv din Kaggle (45.972 meciuri, cu `home_elo`/`away_elo` direct din CSV) a rulat **4 zile mai târziu** — 2026-07-07, 22:48 UTC (`sync_status`, sursa `kaggle_historical`).
3. Backfill **nu a mai rulat niciodată după import** — deci cele 45.972+ rânduri aduse de Kaggle nu au fost niciodată procesate de `run_backfill()`, rămânând fără `offensive_rating`/`defensive_rating`/`form_score`/`h2h_modifier`.
4. Cele 3.816 rânduri care AU `offensive_rating` etc. sunt cele procesate în singura rulare din 2026-07-03 — înainte ca Kaggle să existe în `match_history`. Sunt un set complet diferit de rânduri.

**Nivel de încredere**:
- **Ridicat** pentru secvențierea celor două evenimente (2026-07-03 vs. 2026-07-07) și pentru faptul că backfill n-a mai rulat de atunci — verificat direct din istoricul real GitHub Actions, nu presupus.
- **Ridicat** pentru mecanismul prin care Kaggle-importul populează `home_elo`/`away_elo` condiționat (doar dacă CSV are valoare) și NU atinge `offensive_rating`/etc. — verificat direct în cod (`sync/import_historical.py:434-448`).
- **Mediu** pentru motivul exact pentru care rularea din 2026-07-03 a scris `offensive_rating`/etc. dar NU și `home_elo`/`away_elo`, deși codul ACTUAL din `sync/backfill_features.py` scrie ambele în același dict. Motivul cel mai probabil: codul care a rulat efectiv pe 2026-07-03 era o versiune diferită de cea din repo azi — istoricul git vizibil pentru acest fișier începe abia pe 2026-07-10 (un singur commit, `0bfd517`, conține tot fișierul dintr-o dată), deci nu pot verifica direct conținutul exact de pe 2026-07-03. Semnalez explicit: **nu pot demonstra 100% conținutul exact al codului care a rulat atunci** — doar coincidența temporală (rulare înainte de commit-ul cel mai vechi vizibil) și rezultatul din date.

---

## Traseul complet al datelor — toate punctele care scriu în `match_history`

Verificat exhaustiv prin `grep` pe tot repo-ul pentru `.table("match_history")` — 4 scriitori reali identificați (restul apelurilor găsite sunt SELECT/count, read-only):

| # | Cod | Ce scrie | Când rulează | Dovadă |
|---|---|---|---|---|
| 1 | `sync/import_historical.py` → `database.queries.upsert_matches_bulk()` | identitate meci, rezultat, **`home_elo`/`away_elo` condiționat** (doar dacă CSV are valoare), `used_for_training=True` — **NU** scrie `offensive_rating`/`form_score`/`h2h_modifier` deloc | Manual (`workflow_dispatch`, `.github/workflows/import_kaggle.yml`) — confirmat rulat 2026-07-07 22:48 (`sync_status`) | `sync/import_historical.py:424-448` |
| 2 | `sync/backfill_features.py` → `update_match_features()` | toate cele 8 non-ELO + `home_elo`/`away_elo` împreună, `backfill_done=True` | Manual (`workflow_dispatch`, `.github/workflows/backfill.yml`) — **1 rulare totală, 2026-07-03 05:52 UTC** | `sync/backfill_features.py:670-683`; GitHub Actions run `28641391820` |
| 3 | `sync/sync_results.py` → `update_results_in_supabase()` | `actual_home_goals`, `actual_away_goals`, `actual_result`, **`backfill_done=False`** (resetare explicită) | Zilnic, automat (`daily.yml`, verificat rulează cu succes zilnic) | `sync/sync_results.py:350-356` |
| 4 | `oracle_engine.py` → `_cache_prediction()` → `supabase_client.upsert_match_history()` | toate cele 10 + `home_xg_pred`/`weather_penalty`/`mc_prob_*` | La fiecare predicție live în aplicație | `oracle_engine.py:1110-1139`; doar 21/53.409 rânduri ating vreodată acest cod (verificat: `count(home_xg_pred)=21`) |

`shadow_testing.py:262` și `supabase_client.py:314` ating `match_history` doar prin `SELECT` — verificat, nu scriu nimic.

**Ipoteze verificate explicit, per cerința ta:**

| Ipoteză | Verdict | Dovadă |
|---|---|---|
| Există mai multe pipeline-uri de scriere | **DA, confirmat** | 4 scriitori distincți, tabelul de mai sus |
| Există importuri istorice diferite | **DA, confirmat** | Kaggle (`import_historical.py`, 45.972 rânduri, 2026-07-07) e distinct de orice a existat în `match_history` înainte de 2026-07-03 (procesat de singura rulare de backfill) |
| Există UPDATE-uri parțiale | **DA, confirmat** | `sync_results.py` scrie doar 4 coloane per update (`:351-356`) — parțial, dar NU nulește alte coloane (PostgREST `.update()` cu dict parțial nu atinge coloanele neincluse — comportament standard, nu bug) |
| Există migrații vechi care au lăsat baza inconsistentă | **Neconfirmat, dar plauzibil parțial** — nu există fișiere de migrare pentru `match_history` în `database/migrations/` (doar `001_odds_history.sql` există acolo); inconsistența vine din **secvențiere operațională** (ordinea greșită a două rulări manuale), nu dintr-o migrare de schemă | Absența oricărui alt fișier de migrare relevant, verificată prin listare directă |
| `sync_bootstrap_league_learning.py` scrie în `match_history` | **ELIMINAT explicit** | Comentariu propriu în cod: „NU scrie niciodată în match_history" (`sync/bootstrap_league_learning.py:50`) |

---

## Impactul asupra modelului

Deja cuantificat în `PREDICTOR_ROADMAP_V4.md` §2.3, reconfirmat aici cu cauza clarificată: modelul ML se antrenează cu **0% din rânduri având toate cele 10 feature-uri reale**, ~46% complet imputate cu mediana. Acuratețea reală (46,71%, walk-forward complet) depășește baseline-ul naiv ("mereu Home", 44,0%) cu doar ~3 puncte procentuale — consecință directă, măsurată, a acestei acoperiri.

---

## Data Lineage — toate cele 10 FEATURE_COLUMNS

| Feature | Calculat | Persistat | Citit de ML | % real | % imputat | Cauza lipsei |
|---|---|---|---|---|---|---|
| `home_offensive_rating` | `feature_engine.compute_team_offdef_rating()` — live (`oracle_engine._build_profile`) sau replay istoric (`backfill_features.team_pre_match_rating`) | `_cache_prediction()` (live) SAU `update_match_features()` (backfill, o singură rulare) | `ml_predictor.py:210`, `fillna(median)` | 7,14% (3.816) | 92,86% | Backfill rulat o singură dată (2026-07-03), înainte de importul Kaggle (2026-07-07); niciodată re-rulat |
| `home_defensive_rating` | idem | idem | idem | 7,14% | 92,86% | idem |
| `away_offensive_rating` | idem | idem | idem | 7,14% | 92,86% | idem |
| `away_defensive_rating` | idem | idem | idem | 7,14% | 92,86% | idem |
| `home_form_score` | `feature_engine.compute_form_score()` | idem | idem | 7,14% | 92,86% | idem |
| `away_form_score` | idem | idem | idem | 7,14% | 92,86% | idem |
| `home_elo` | Live: `oracle_api.get_elo_rating()` (scraping extern). Backfill: `ELOTracker` (replay intern, pornește de la 1500). Import: direct din CSV Kaggle | Kaggle import (condiționat pe CSV) SAU backfill SAU `_cache_prediction()` | idem | 47,00% (25.104) | 53,00% | Populat doar pentru rândurile Kaggle cu `HomeElo` valid în CSV-ul sursă; restul (pre-Kaggle, procesat de backfill) au fost suprascrise/nescrise cu ELO în rularea din 2026-07-03 — mecanism exact nedemonstrat 100% (vezi „Nivel de încredere") |
| `away_elo` | idem | idem | idem | 46,98% (25.095) | 53,02% | idem (diferență de 9 rânduri față de `home_elo` — nereconciliată exact, marginal) |
| `h2h_modifier` | `feature_engine.compute_h2h_modifier()` | `_cache_prediction()` SAU backfill | idem | 7,14% | 92,86% | Ca la ratinguri — doar rândurile procesate de backfill (2026-07-03) |
| `h2h_meetings` | idem | idem | idem | 7,14% | 92,86% | idem |

**Unde poate deveni NULL**: la creare, dacă `import_historical.py` nu găsește valoare CSV (pentru elo) sau pur și simplu nu scrie coloana (pentru celelalte 8) — nu există niciun cod care ar seta explicit NULL peste o valoare existentă (verificat: niciun writer nu include chei cu valoare `None` intenționat pentru aceste coloane).
**Unde poate fi suprascris**: `sync_results.py` NU suprascrie aceste 10 coloane (doar 4 coloane de rezultat) — dar resetează `backfill_done=False`, ceea ce (dacă backfill ar rula din nou) ar declanșa o rescriere a tuturor celor 10, inclusiv pentru rânduri care poate au deja valori reale de la o rulare anterioară (comportament intenționat — rezultat nou = feature-urile pre-meci merită recalculate cu istoricul cel mai recent).
**Unde e imputat**: exclusiv în `ml_predictor.py:210`, la antrenare — niciodată persistat înapoi în `match_history` (imputarea e efemeră, doar în memorie, per rulare de antrenare).

---

## Cea mai sigură metodă de remediere (NEIMPLEMENTATĂ — doar propunere, în așteptarea aprobării)

Nu implementez nimic din ce urmează. Enumăr opțiunile, cu risc:

1. **Re-rulare completă `run_backfill()` pe tot `match_history`** (fără filtrul `backfill_done`, sau după resetarea lui la `False` peste tot) — ar completa cele 8 feature-uri non-ELO pentru toate cele 53.409 rânduri. Risc: suprascrie `home_elo`/`away_elo` existent (cel din Kaggle, real) cu valori calculate de `ELOTracker` (replay intern, pornind de la 1500) — care ar putea fi MAI PUȚIN corecte decât ELO-ul real din Kaggle pentru rândurile care îl au deja. **Necesită o decizie explicită**: păstrăm ELO-ul Kaggle acolo unde există (modificare de cod — `update_match_features` să nu suprascrie `home_elo`/`away_elo` dacă rândul are deja o valoare non-null) sau acceptăm suprascrierea cu ELO replay-uit (posibil mai puțin precis, dar cel puțin intern consistent).
2. **Rulare parțială, doar pe rândurile Kaggle** (`elo_only` + `neither`, ~49.593 rânduri) — mai sigură, nu atinge cele 3.816 deja procesate.
3. **Nu se remediază încă** — se documentează limitarea și se ia decizia abia după acest audit.

**Da, e nevoie de o rerulare (parțială sau completă) a backfill-ului** ca să existe vreun rând cu toate cele 10 feature-uri reale simultan — asta e demonstrat, nu opțional, dacă scopul e un model antrenat pe date reale. Alegerea între opțiunile 1/2/3 de mai sus, și tratamentul exact al ELO-ului existent, rămâne decizia ta.
