# ELO_CANONICAL_SOURCE_AUDIT_2026-07-13.md — Football Oracle

**Status**: Audit de arhitectură — zero cod scris, zero fișier modificat, zero patch propus. Continuă `DATA_PIPELINE_INVESTIGATION_2026-07-12.md` și `BACKFILL_NON_DESTRUCTIVE_STRATEGY_2026-07-12.md`.
**Scop**: determină sursa canonică a ELO-ului, argumentat exclusiv pe cod și date reale, nu pe ce e mai ușor de implementat.

---

## 1. Toate sursele de ELO din proiect — descoperire completă

Investigația inițială (documentele anterioare) menționa doar două surse (Kaggle vs. `ELOTracker`). O căutare exhaustivă în tot repo-ul arată **cinci** mecanisme distincte legate de ELO, nu două:

| # | Sursă | Tip | Scriere | Citire |
|---|---|---|---|---|
| A | **Scraping live — eloratings.net** | externă, live | doar cache (nu Supabase) | **motorul live de predicție** |
| B | **Kaggle — coloană per-meci `HomeElo`/`AwayElo`** | externă, istorică, statică | `match_history.home_elo/away_elo` | doar `FEATURE_COLUMNS` la antrenare |
| C | **Kaggle — fișier separat `EloRatings.csv`** | externă, istorică, statică | tabela `elo_history` | **nimic — orfan, confirmat** |
| D | **`ELOTracker` — replay intern** (`sync/backfill_features.py`) | internă, calculată | `match_history.home_elo/away_elo` (parțial) + intern la `offensive_rating`/`defensive_rating` | `FEATURE_COLUMNS` la antrenare (indirect, via rating) |
| E | **`sync/calculate_elo.py` — replay intern DUPLICAT** | internă, calculată | tabela `elo_ratings` | **nimic — orfan, confirmat, deși rulează zilnic în producție** |

---

## 2. Traseul complet al fiecărei surse

### A. Scraping live (eloratings.net)
**Calcul**: `oracle_api._fetch_elo_ratings()` (`oracle_api.py:855-888`) — scraping HTML (BeautifulSoup) al tabelului eloratings.net. Fallback: `ELO_RATINGS_FALLBACK` (`mappings.py`, ~65 echipe/țări hardcodate).
**Persistare**: doar `CacheManager`, categoria `"elo"`, cheia de cache `"elo_ratings"` (TTL 24h) — **NU tabela Supabase `elo_ratings`**, deși numele coincide. Coincidență de denumire între o cheie de cache și un nume de tabelă complet separat — confirmat prin citirea directă a `_category_for_key()`/`_cget`/`_cset` din `oracle_api.py:168-203`.
**Consum**: `oracle_engine._build_profile()` (`oracle_engine.py:461-464`) — **aceasta e singura sursă de ELO folosită efectiv de motorul live** pentru orice predicție reală, azi.

### B. Kaggle, coloană per-meci
**Calcul**: extern, metodologie nedocumentată în acest repo — provine dintr-un fișier stil football-data.co.uk. **Nu pot demonstra K-factor/home advantage/inițializare exacte ale acestei surse** — CSV-ul nu documentează metodologia, doar valorile.
**Persistare**: `sync/import_historical.py:434-448` → `match_history.home_elo`/`away_elo`, condiționat (doar dacă valoarea CSV există). 25.104/25.095 rânduri (47,0%/47,0%).
**Consum**: doar ca parte a `FEATURE_COLUMNS` citite de `ml_predictor.py` la antrenare — **niciodată citit înapoi de `team_pre_match_rating()`** (deja demonstrat în documentul anterior), niciodată folosit de motorul live.

### C. Kaggle, `EloRatings.csv` separat
**Calcul**: extern, alt fișier decât B — confirmat separat prin cod: `sync/import_historical.py:619-...`, `import_elo_history()`, citește un fișier detectat automat ca `"elo_snapshot"` (coloane date/echipă/elo, nu meciuri). Conține 667 echipe (mult peste cele ~211 echipe naționale FIFA — include probabil și cluburi), interval 2000-07-01 → 2025-06-01.
**Persistare**: tabela `elo_history`, 39.575 rânduri, `source="kaggle"` (verificat direct în date).
**Consum**: **nicăieri** — verificat prin căutare completă `SELECT` pe `elo_history` în tot codul: zero rezultate. Scriere pură, fără niciun consumator.
**Observație cantitativă**: distribuția (min 1069, max 2087, medie 1494, deviație 164) e remarcabil de apropiată de distribuția sursei B din `match_history` (min 1103, max 2141, medie 1524, deviație 161) — **indiciu**, nu dovadă, că ambele fișiere Kaggle provin dintr-o metodologie înrudită.

### D. `ELOTracker` (replay intern, backfill)
**Calcul**: `sync/backfill_features.py:161-205` — replay cronologic determinist. `INITIAL_ELO=1500`, `HOME_ADVANTAGE=50`, `K_FACTOR_BASE=32`, `K_FACTOR_NEW=40` (prag 10 meciuri), formulă logistică standard (`_expected_score`).
**Persistare**: `match_history.home_elo`/`away_elo`, dar **doar pentru cele 3.816 rânduri procesate în singura rulare din 2026-07-03** (deja documentat). În plus, `team_pre_match_rating()` (`:503-568`) folosește ELO-ul din acest tracker **intern**, ca parte a calculului `offensive_rating`/`defensive_rating` — persistat separat, pentru orice rând procesat de backfill SAU de `bootstrap_league_learning.py` (care reutilizează corect `ELOTracker`/`team_pre_match_rating`, import direct, fără duplicare — verificat `sync/bootstrap_league_learning.py:106-107`).
**Consum**: `FEATURE_COLUMNS` la antrenare (`home_elo`/`away_elo` direct, plus indirect prin `offensive_rating`/`defensive_rating`).

### E. `sync/calculate_elo.py` (replay intern, DUPLICAT independent)
**Calcul**: `sync/calculate_elo.py:53-127` — **aceeași formulă, aceiași parametri exacți** ca D (`INITIAL_ELO=1500`, `HOME_ADVANTAGE=50`, `K_FACTOR_BASE=32`, `K_FACTOR_NEW=40`, aceeași `_expected_score`) — dar cod separat, nereutilizat, nu importă din `feature_engine.py` sau `backfill_features.py`. Scop: doar 7 ligi hardcodate în `LEAGUES` (`:42-50`) — lipsesc explicit Conference League, Europa League, MLS, World Cup 2026 față de cele 11 urmărite azi de proiect. Limitat la ultimele 2000 meciuri per ligă (`get_matches_by_league(league, limit=2000)`).
**Persistare**: tabela `elo_ratings`, 239 rânduri.
**Consum**: **nicăieri** — `database.queries.get_elo_ratings()` (funcția de citire) are **zero apeluri** în tot codul, verificat prin căutare completă.
**Rulare**: automată, **zilnic**, prin `sync/run_daily.py:180-181` — confirmat parte din pipeline-ul de producție. Rulează de fiecare dată, degeaba, fără niciun consumator.

---

## 3. Diferențe matematice între sursele externe și cele calculate — ce pot și ce nu pot demonstra

| Comparație | Verificabil? | Rezultat |
|---|---|---|
| B vs. D (K-factor, home advantage, inițializare) | **Parțial** | D are parametri expliciți în cod (32/40, +50, 1500). B (Kaggle) nu documentează nicăieri metodologia — CSV-ul are doar valori, nu formula. **Nu pot demonstra** dacă B folosește aceiași parametri. |
| B vs. D (compatibilitate de scală) | **Da, din date** | Distribuții similare ca ordin de mărime (B: medie 1524/std 161; D: nu există încă date reale de comparat, fiindcă D nu s-a scris niciodată pentru rânduri care au și B — vezi documentul anterior, `both_backfill_and_elo=0`). Nu există NICIUN rând cu ambele valori, deci **nu pot compara direct, cap la cap, pe aceleași meciuri** — doar distribuții agregate separate. |
| C vs. B (aceeași sursă Kaggle?) | **Indiciu, nu dovadă** | Distribuții foarte apropiate (medie 1494 vs. 1524, std 164 vs. 161) — sugestiv, dar nu identic, și „source" în `elo_history` spune doar `"kaggle"`, fără alt detaliu de proveniență. |
| D vs. E (aceeași formulă?) | **Da, demonstrat exact** | Cod citit direct: constante identice, formulă `_expected_score` identică caracter cu caracter. Singura diferență reală: scope (D = tot istoricul, toate ligile; E = 7 ligi hardcodate, ultimele 2000 meciuri/ligă) — deci **chiar și D și E, cu aceeași formulă, ar produce valori diferite** din cauza scope-ului diferit de replay. |
| A (scraping live) vs. oricare altă sursă | **Nu pot verifica** | Metodologia eloratings.net nu e documentată în acest repo — e un site extern. Nu pot compara matematic. |

---

## 4. Scenarii — Kaggle canonic vs. ELOTracker (replay) canonic

### Scenariul 1: Kaggle (sursele B/C) devine canonic

**Avantaje**: valori externe, potențial mai calibrate/reputate decât un replay intern; acoperă deja 47% din istoric fără niciun calcul suplimentar; cost zero de calcul.

**Dezavantaje, unul dintre ele fatal**:
- **Kaggle e un fișier istoric, static, cu o dată limită demonstrată (`elo_history`: ultimul snapshot 2025-06-01)**. Nu există, structural, niciun mecanism prin care Kaggle ar putea oferi un ELO pentru un meci de mâine. **Motorul live n-ar avea niciodată o sursă canonică validă** — Kaggle poate răspunde doar la întrebări despre trecut, niciodată despre viitor. Asta descalifică Kaggle ca sursă canonică pentru un sistem al cărui scop e să prezică meciuri viitoare, indiferent de calitatea valorilor istorice.
- Metodologia exactă nedemonstrabilă (vezi §3) — o sursă canonică al cărei calcul nu poate fi inspectat/verificat contravine direct filosofiei „verificat, nu presupus" a proiectului.
- Nicio cale de testare prin Champion/Challenger — nu poți experimenta cu parametrii unei coloane CSV externe, înghețate.

**Componente care ar deveni inconsistente**: `oracle_engine._build_profile()` (sursa A, live) ar rămâne singura sursă reală pentru predicții — Kaggle n-ar putea-o înlocui niciodată, deci ar coexista permanent DOUĂ „canonice" (unul pentru trecut, altul pentru prezent), exact tipul de inconsistență pe care o căutăm să eliminăm. `team_pre_match_rating()` ar trebui rescris să prefere Kaggle când există — dar tot ar avea nevoie de un fallback la replay pentru cele 53% din rânduri fără Kaggle ELO și pentru 100% din predicțiile live — deci ELOTracker n-ar putea fi eliminat oricum. `sync/calculate_elo.py` ar rămâne orfan, la fel ca azi.

### Scenariul 2: `ELOTracker` (replay intern) devine canonic

**Avantaje**:
- Singura sursă capabilă, structural, să acopere **atât trecutul cât și viitorul** — aceeași formulă poate calcula ELO pentru un meci din 2022 sau pentru unul de mâine, fiindcă e o funcție pură de rezultate + cronologie, nu un fișier static.
- Parametri expliciți, inspectabili, testabili — coerent cu „verificat, nu presupus".
- Testabil prin Champion/Challenger (Learning Core deja există) — orice rafinament (alt K-factor, decay temporal etc.) poate fi validat statistic înainte de promovare, exact fluxul deja proiectat.
- O singură formulă, în principiu, ar putea unifica atât backfill-ul (D) cât și — dacă s-ar decide separat — chiar sursa live (A, azi eloratings.net), eliminând definitiv discrepanța dintre „ELO-ul din antrenare" și „ELO-ul din producție".

**Dezavantaje**:
- Pornește „rece" (1500) la începutul ferestrei de date disponibile (cutoff istoric ~2021), fără context real anterior — un ELO extern, cu istoric de zeci de ani, ar avea teoretic mai multă „memorie" încorporată de la început.
- Implementarea de azi e deja duplicată (D vs. E) și inconsistentă ca scope — necesită consolidare (neimplementată aici, doar semnalată).
- Nu e ce folosește azi motorul live (sursa A) — a declara D canonic nu rezolvă automat coerența cu A; ar rămâne o decizie separată, ulterioară.

**Componente care ar deveni inconsistente**: `import_historical.py` ar continua să scrie Kaggle ELO în `match_history` (B) — ar deveni „date brute importate, nu canonice" — fie ignorate de pipeline-ul de feature-uri, fie păstrate doar ca semnal de audit/comparație. `elo_history` (C) și `sync/calculate_elo.py`/`elo_ratings` (E) rămân orfane oricum — dar cel puțin **nu mai rulează degeaba zilnic în producție** dacă sunt eliminate ca parte a consolidării (decizie separată, neimplementată aici). Sursa A (live) rămâne o inconsistență REZIDUALĂ, nerezolvată de această decizie — trebuie tratată explicit, separat.

---

## 5. Care variantă păstrează coerența pe termen lung — pentru Poisson, ML, Learning Core, Shadow Testing, experimente

Argument central, nu de implementare: **un sistem de predicție al cărui scop e viitorul nu poate avea drept canonic o sursă care structural nu poate produce valori pentru viitor.** Kaggle e descalificat pe acest singur criteriu, independent de orice altă calitate a datelor lui.

`ELOTracker` (replay intern) e singura sursă dintre cele cinci care poate, în principiu, servi identic toate componentele enumerate:
- **Poisson** (motorul live) — poate consuma direct valori replay, dacă sursa A e vreodată aliniată la aceeași formulă.
- **ML** (`FEATURE_COLUMNS`) — deja parțial consumă D azi (indirect, prin `offensive_rating`).
- **Learning Core / Shadow Testing** — orice variație a formulei (K-factor, fereastră de decay) devine un experiment testabil, nu o presupunere.
- **Experimente viitoare** — o singură sursă de adevăr, versionabilă, nu un amestec de fișiere externe înghețate + cod intern.

---

## 6. Verdict

**Canonical ELO = `ELOTracker` (metodologia de replay intern, calculată — sursele D/E consolidate, nu sursele externe Kaggle B/C).**

**Justificare, strict pe dovezi**:
1. Kaggle (B, C) e demonstrat static — cutoff real, verificat în date (`elo_history`, ultimul snapshot 2025-06-01) — nu poate produce niciodată o valoare pentru un meci viitor. Orice sistem care ar declara Kaggle canonic ar avea nevoie, obligatoriu, de o a doua sursă pentru producție — adică n-ar rezolva problema de coerență, ar muta-o.
2. Replay-ul intern (D/E) e singura sursă, dintre toate cele cinci, matematic capabilă să acopere atât istoricul cât și viitorul, sub aceeași formulă — proprietate structurală, nu de preferință.
3. E singura sursă compatibilă nativ cu disciplina proiectului (walk-forward, Champion/Challenger, „verificat nu presupus") — parametrii sunt cod propriu, inspectabil și testabil, nu un CSV extern cu metodologie nedocumentată.

**Rămâne explicit nerezolvat de acest verdict** (nu presupun o soluție): reconcilierea sursei A (scraping live eloratings.net, ce folosește azi efectiv motorul live) cu metodologia de replay D — a declara D canonic pentru antrenare nu elimină automat discrepanța față de A pentru producție. E o decizie separată, ulterioară, neacoperită de întrebarea pusă aici. La fel, consolidarea D/E (eliminarea duplicării) și tratamentul exact al datelor B/C existente (păstrate ca audit vs. eliminate) rămân decizii de implementare, explicit neabordate — cerința ta a fost strict verdictul de arhitectură, nu planul de execuție.
