# STRUCTURAL_MATCH_STATISTICS_ROADMAP.md — Football Oracle

**Status**: Audit + design review — zero cod scris, zero cod modificat, zero schemă Supabase atinsă, zero ADR, zero workflow, zero serviciu. Fiecare afirmație despre stare curentă e verificată direct (interogare SQL live pe `Prediction`, citire directă de cod), nu presupusă.
**Context**: P1/P2/P3 (Etapa 1-2 din `ML_EVOLUTION_ROADMAP.md`) au epuizat câștigul disponibil din reglaje (hiperparametri, calibrare, formula ELO) — concluzie arhitecturală explicită: următorul salt vine din date, nu din algoritm. Acest document e Etapa 3 („Structural Match Statistics"), pentru cele 4 statistici prioritizate: Shots, Shots on Target, Big Chances, Possession.
**Precedent direct, obligatoriu de citit împreună cu acest document**: `docs/05_DATA_AUDIT/DATASET_CAPABILITY_AUDIT_2026-07-13.md` (completitudine pe sursă, per ligă) și `docs/03_ENGINE/KNOWLEDGE_ENGINE_SOURCES_AUDIT_2026-07-13.md` (surse externe, ToS, risc juridic) — ambele deja există, ambele re-verificate aici contra stării LIVE de azi (2026-07-15), nu doar citate.

---

## Rezumat — răspunsul scurt la toate cele 9 întrebări

1. **Shots/Shots on Target/Fouls/Corners/Cards sunt deja parțial populate în producție** (66,7% pentru Premier League/La Liga/Serie A, 66,6% Bundesliga/Ligue 1) — nu 0%, cum arăta auditul din urmă cu 2 zile. Backfill-ul deja s-a rulat între timp. **Possession e 0% peste tot, fără nicio excepție.** **Big Chances nu are nicio coloană în schemă — nu există deloc azi.**
2. **Infrastructura de backfill/tracking există deja și e explicit proiectată pentru extindere fără cod nou** (`STAT_GROUPS`, `MatchStatsBackfillService`, `ShotsTracker`/`FoulsTracker`/`CornerCardTracker`) — Shots on Target e deja PARȚIAL conectată la ML (prin `compute_team_offdef_rating`, indirect, nu ca feature propriu), dar Possession, deși are aceeași infrastructură de blend pregătită, primește azi mereu o valoare constantă (50,0) fiindcă nu există date reale — 25% din ponderea formulei de rating e efectiv irosită pe o constantă.
3. **Shots/SOT au sursă gratuită, deja descărcată, zero risc legal nou. Possession nu poate fi retro-populată din nicio sursă gratuită curată — doar live, incremental, prin API-Football. Big Chances nu are nicio sursă gratuită conformă ToS pentru niciuna din cele 11 competiții urmărite** — descoperire deja documentată, reconfirmată aici.
4. Vezi §4 — tabel complet, per statistică.
5. Vezi §5 — peste 15 feature-uri derivate propuse, nu doar exemplele din cerere.
6. Vezi §6 — pentru fiecare, rațional + calcul + risc de scurgere + validare.
7. Vezi §7 — ordinea NU urmează prioritatea cerută (Shots → SOT → Big Chances → Possession) — fezabilitatea reală diverge sever de acea ordine, semnalat explicit, nu ascuns.
8. Vezi §8 — 9 categorii de risc identificate, inclusiv una nouă, descoperită în timpul acestui audit (duplicare de reprezentare a ligii, nu doar a echipei).
9. Vezi §9 — roadmap recomandat, 4 etape, cu justificare.

---

## 1. Ce statistici există deja în baza de date — verificat, nu presupus

Interogare SQL directă (`match_history`, 53.430 rânduri, toate ligile), `COUNT(coloană) / COUNT(*)` per ligă:

| Ligă | Total rânduri | Shots | Shots on Target | Fouls | Corners | Yellow Cards | HT Score | Possession | xG real | `stats_source` |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Premier League | 1.140 | 760 (66,7%) | 760 (66,7%) | 760 | 760 | 760 | 760 | **0** | **0** | **0** |
| La Liga | 1.140 | 760 (66,7%) | 760 (66,7%) | 760 | 760 | 760 | 760 | **0** | **0** | **0** |
| Serie A | 1.140 | 760 (66,7%) | 760 (66,7%) | 760 | 760 | 760 | 760 | **0** | **0** | **0** |
| Bundesliga | 917 | 611 (66,6%) | 611 (66,6%) | 611 | 611 | 611 | 611 | **0** | **0** | **0** |
| Ligue 1 | 916 | 610 (66,6%) | 610 (66,6%) | 610 | 610 | 610 | 610 | **0** | **0** | **0** |
| Romania SuperLiga | 1.975 | **0** | **0** | **0** | **0** | **0** | **0** | **0** | **0** | **0** |
| Champions League | 628 | **0** | **0** | **0** | **0** | **0** | **0** | **0** | **0** | **0** |
| Europa League | 139 | **0** | **0** | **0** | **0** | **0** | **0** | **0** | **0** | **0** |
| World Cup 2026 | 21 | **0** | **0** | **0** | **0** | **0** | **0** | **0** | **0** | **0** |
| „E0"/„E1"/„SP1"/... (coduri brute, rânduri separate) | ~35.000 | **0** | **0** | **0** | **0** | **0** | **0** | **0** | **0** | **0** |

**Coloana `big_chances` (sau echivalent) nu există deloc în schema `match_history`** — verificat direct (`information_schema` via `list_tables`), nu doar 0% populată, ci absentă structural.

**Descoperire nouă, nu era în auditul din 07-13**: backfill-ul de Shots/SOT/Fouls/Corners/Cards/HT **s-a executat între timp** (probabil ca urmare a ADR-011, aprobat 07-13/07-14) — starea reală de azi e mult mai bună decât „0% peste tot" documentat acum 2 zile. Dar plafonul de **66,6-66,7%, identic pe toate cele 5 ligi**, nu e întâmplător — vezi §8.1 pentru cauza cea mai probabilă (nu confirmată 100%, dar susținută consistent de dovezi).

**Clasificare, reconfirmată din `DATASET_CAPABILITY_AUDIT`**:
- **Populate parțial**: `home_shots`/`away_shots`, `home_shots_on_target`/`away_shots_on_target`, `home_fouls`/`away_fouls`, `home_corners`/`away_corners`, `home_yellow_cards`/`away_yellow_cards`, `home_red_cards`/`away_red_cards`, `home_ht_goals`/`away_ht_goals` — toate la 66,6-66,7% pe cele 5 ligi mari, 0% peste tot altundeva.
- **Complet nefolosite (coloane există, 0% populate, peste tot)**: `home_possession`/`away_possession`, `home_xg_actual`/`away_xg_actual`, `stats_source`.
- **Inexistente structural**: orice coloană de Big Chances.

---

## 2. Ce infrastructură există deja — nu reinventăm

Verificat direct în cod, nu presupus. Fiecare piesă de mai jos e deja scrisă, deja rulează, sau e deja pregătită pentru extindere fără cod nou:

### 2.1 Backfill istoric (sursă statică, deja descărcată)

- **`sync/sources/football_data_co_uk.py`** — `fetch_football_data_co_uk_match_stats()` + `_MATCH_STATS_FIELDS` (dict sursă→coloană, un singur loc de adăugat o statistică nouă). Extrage azi: Shots, Shots on Target, Fouls, Corners, Yellow/Red Cards, HT Score. **Nu conține și nu poate extrage Possession sau Big Chances — sursa CSV nu are aceste coloane** (confirmat direct în fișier, consistent cu `KNOWLEDGE_ENGINE_SOURCES_AUDIT`).
- **`services/match_stats_backfill_service.py`** — `MatchStatsBackfillService`, generic, parametrizat prin `columns` (lista de coloane de completat) — zero cod nou între „Task 1: shots" și „Task 2: corners/fouls/cartonașe/HT", conform propriului comentariu din cod. Matching fail-closed (dată + `normalize_team_name()` pe ambele echipe + verificare obligatorie de scor), scriere non-destructivă (gating strict per-coloană NULL, Regula #13).
- **`sync/backfill_match_stats.py`** — CLI + `STAT_GROUPS` (registru declarativ: `"shots"` → 4 coloane, `"match_events"` → 10 coloane). **O statistică nouă = o intrare nouă în `STAT_GROUPS`, zero cod nou** — exact mecanismul pe care orice extensie viitoare (dacă apare o sursă pentru Possession/Big Chances) l-ar folosi.
- **`LEAGUE_DIVISION_CODES`** (în `sync/backfill_match_stats.py`) acoperă azi doar 5 ligi (Premier League, La Liga, Serie A, Bundesliga, Ligue 1) — Romania SuperLiga exclusă explicit (sursă 0% acolo, demonstrat), Championship exclusă (motiv diferit, vezi §8.1).

### 2.2 Feature engineering / trackere (calcul din date deja scrise)

- **`sync/backfill_features.py`**: `ShotsTracker`, `FoulsTracker`, `CornerCardTracker` — toate trei aceeași disciplină (medie glisantă pe fereastră `FORM_WINDOW`, întoarce media DINAINTE de meci, `None` dacă nu există date reale, niciodată aproximat). `FoulsTracker`/`CornerCardTracker` alimentează deja `foul_diff`/`corner_dominance`/`card_diff` — deja în `ml_predictor.FEATURE_COLUMNS`, promovate prin ablație (ADR-012/013). **`ShotsTracker` există, dar NU alimentează un feature propriu** — folosit doar ca input pentru `compute_team_offdef_rating()` (vezi 2.3).
- **Tipar exact reutilizabil pentru orice statistică nouă**: o clasă „Tracker" nouă (sau extinderea uneia existente), aceeași semnătură (`process_match`, `get_avg_*`), conectată în bucla principală din `run_backfill()`.

### 2.3 Blend-ul de rating ofensiv/defensiv (deja consumă Shots on Target + Possession — parțial)

- **`feature_engine.compute_team_offdef_rating()`** — formula deja combină `avg_goals_for`, `avg_shots_on_target`, `avg_possession`, ponderate (`goals_weight`, `shots_ot_weight`, `possession_weight` — 0,45/0,30/0,25 implicit, per-ligă în `oracle_engine.LEAGUE_WEIGHTS`). **Rezultatul alimentează direct `home_offensive_rating`/`home_defensive_rating`/`away_offensive_rating`/`away_defensive_rating`** — deja în `FEATURE_COLUMNS`.
- **Descoperire directă, cu impact concret**: fiindcă `home_possession`/`away_possession` sunt 0% populate peste tot, `avg_possession` folosit în formulă e mereu fallback-ul hardcodat **50,0** (`oracle_engine.py:707`, `pos: 50.0`), identic pentru toate echipele — `pos_norm` rezultat e o CONSTANTĂ (0,25), nu diferențiază nicio echipă de alta. **25% din ponderea formulei de rating ofensiv/defensiv (posession_weight) e azi complet irosită** — nu contribuie cu niciun semnal real, doar cu un offset identic pentru toți. Popularea reală a posesiei ar activa acea pondere, nu ar adăuga un feature nou de la zero.
- Pentru Shots on Target, situația e mai bună dar tot parțială: `oracle_engine._real_avg_shots_on_target()` (linia 536) încearcă să obțină SOT real din `match_history` prin `supabase_client.get_team_recent_shots()` — **cale LIVE separată**, duplicată funcțional față de `ShotsTracker` (folosit în replay-ul offline din `backfill_features.py`). Ambele fac același lucru (medie glisantă SOT real), pe două căi de cod diferite — nu e o problemă azi (nu diverg, ambele citesc aceleași date), dar e o duplicare de menținut sincronizată, nu consolidată.

### 2.4 Statistici pur informative, deja calculate, neconectate la formula de rating

- **`oracle_engine._real_match_events()`** (linia 568) — cornere/faulturi/cartonașe/HT reale, medie glisantă, **explicit „NU alimentează formula de rating"** (comentariu din cod) — pur pentru afișare/explainability. Corner/card/foul AJUNG totuși la model prin altă cale (`CornerCardTracker`/`FoulsTracker` din `backfill_features.py`, separat de această funcție live).

### 2.5 Ce NU există deja (verificat, nu presupus)

- **Niciun provider de Possession sau Big Chances** — `football_providers.ApiFootballProvider` are `get_injuries()`/`get_coaches()` complet implementate, dar `get_player_stats()`/`get_team_stats()` sunt **stub-uri abstracte, neimplementate**. Orice integrare API-Football pentru statistici de meci ar fi cod nou, nu conectarea unuia existent.
- **Nicio coloană, niciun tracker, niciun serviciu pentru Big Chances** — zero infrastructură de reutilizat, în orice strat (schemă, sursă, cod).

---

## 3. Ce surse reale pot popula aceste statistici

Reconfirmă și extinde `KNOWLEDGE_ENGINE_SOURCES_AUDIT_2026-07-13.md`, aplicat specific celor 4 statistici cerute.

| Sursă | Shots | Shots on Target | Big Chances | Possession | Acoperire competiții | Dificultate | Risc |
|---|---|---|---|---|---|---|---|
| **football-data.co.uk (mirror deja descărcat)** | ✅ da, deja parțial populat | ✅ da, deja parțial populat | ❌ nu are coloană | ❌ nu are coloană | 5 mari ligi (nu Romania, nu Championship ca nume, nu cupe europene, nu World Cup) | **Foarte mică** — infrastructură completă, doar de rulat/extins | Zero — sursă deja folosită, zero expunere ToS nouă |
| **API-Football (nivel gratuit)** | ✅ da, endpoint documentat | ✅ da | ❌ nu apare în lista de câmpuri documentată | ✅ da | Revendică 1.200+ competiții, dar **completitudinea reală pentru Romania/Conference League neverificată** — necesită test cu cheie live | **Medie** — API curat, dar cod nou (provider stub neimplementat azi), și doar incremental (100 req/zi, backfill istoric impracticabil) | Scăzut (ToS oficial, clar) — dar cost dacă se depășește nivelul gratuit (19 USD/lună de la 7.500 req/zi) |
| **Understat** | ❌ nu | ❌ nu | ❌ nu | ❌ nu | 6 ligi, doar xG/xA/PPDA — nu are deloc șuturi brute, posesie, big chances | — | Zonă gri legală (fără ToS public găsit pentru acces automatizat) |
| **StatsBomb Open Data** | Parțial (derivabil din date la nivel de eveniment) | Parțial (derivabil) | Parțial (derivabil) | Parțial (derivabil) | Fragmentat — World Cup/turnee, sezoane selectate Champions League; **zero sezoane complete pentru cele 6 ligi domestice mari** | **Mare** — necesită procesare de la nivel de eveniment, nu date preagregate | Licență comercială neconfirmată (`LICENSE.pdf` neextras) |
| **SofaScore / FotMob / WhoScored** | ✅ (cea mai bogată acoperire, inclusiv Romania) | ✅ | ✅ (singurele cu Big Chances) | ✅ | Cea mai largă din toate sursele analizate | Mică tehnic, dar **interzis explicit de ToS** | **Ridicat — ToS interzice explicit scraping și uz comercial fără licență; WhoScored numește explicit platformele de pariuri. Nerecomandat, consistent cu decizia deja luată în `KNOWLEDGE_ENGINE_SOURCES_AUDIT`.** |
| **Kaggle (dump-uri de la sursele de mai sus)** | Variabil | Variabil | Rar | Variabil | Moștenește limitele sursei originale | Mică tehnic | Moștenește riscul legal/prospețimea sursei originale |
| **Wyscout / Opta** | ✅ | ✅ | ✅ | ✅ | Cea mai completă, comercial | Mică tehnic (API documentat) | **Cost** — sute-mii USD/an, preț la cerere, decizie de buget separată |

**Concluzie directă, per statistică**:
- **Shots + Shots on Target**: sursă gratuită, curată, deja parțial exploatată. Nicio decizie nouă de risc necesară.
- **Possession**: **imposibil de retro-populat** din nicio sursă gratuită curată identificată — football-data.co.uk nu o are, singura cale gratuită conformă ToS e API-Football, dar doar LIVE/incremental (nu backfill istoric). Orice istoric de possession ar începe să se acumuleze abia de la data activării, nu retroactiv.
- **Big Chances**: **nicio sursă gratuită conformă ToS** identificată pentru niciuna din cele 11 competiții urmărite. Singurele surse care au deloc acest câmp (SofaScore, FotMob, WhoScored) sunt explicit nerecomandate. Rămâne fie plătit (Opta/Wyscout), fie stare permanent „necunoscută" (consistent cu ADR-001).

---

## 4. Prioritate / Impact ML / Complexitate / Calitate / Acoperire / Cost — per statistică

| Statistică | Prioritate cerută | Impact ML estimat | Complexitate | Calitate estimată | Acoperire estimată | Cost implementare |
|---|---:|---|---|---|---|---|
| **Shots** | 1 | **Necunoscut, netestat** — dar înlocuiește un proxy deja documentat ca sintetic/fals (`gf_avg*0,45`), similar cazului Shots on Target de mai jos | **Foarte mică** — coloană existentă, sursă existentă, tracker de scris după tiparul `FoulsTracker`/`CornerCardTracker` | Bună pentru 5 ligi mari (66,7% și crescând, plafon de investigat — §8.1), zero pentru Romania/cupe | 5/11 competiții urmărite, ~67% din meciurile acelor 5 | Foarte mic — extensie directă a infrastructurii §2.2 |
| **Shots on Target** | 2 | **Parțial deja „ars" prin blend** (`compute_team_offdef_rating`) — un feature RAW separat ar testa dacă semnalul brut aduce ceva peste ce ratingul deja capturează, risc real de redundanță (§8.5) | **Foarte mică** — date deja disponibile, doar promovare la feature propriu (ablație) | Idem Shots | Idem Shots | Foarte mic |
| **Big Chances** | 3 | **Teoretic mare** (literatura de betting-analytics tratează big chances ca semnal de calitate a atacului, complementar șuturilor brute) — dar **nedemonstrabil azi, nicio sursă** | **Blocată** — nu e o problemă de cod, e o problemă de sursă inexistentă | N/A — nu există date de evaluat | **0/11 competiții**, din nicio sursă conformă ToS | **Nu poate fi estimat onest** — depinde de o decizie de buget (Opta/Wyscout) sau de acceptarea riscului ToS (nerecomandat), nu de efort de inginerie |
| **Possession** | 4 | **Potențial real** — completează exact ponderea „irosită" de 25% din blend-ul de rating deja existent (§2.3) | **Mică pentru infrastructura de scriere** (coloane există), **mare pentru sursa de date** — necesită provider nou (API-Football, cod neimplementat azi) și e strict incrementală (nicio cale de backfill istoric) | Bună doar pentru meciuri viitoare, de la data activării — **zero istoric retroactiv posibil** | Nesigur — „nominal" 1.200+ competiții per documentație API-Football, **neverificat independent** pentru Romania/Conference League | Mediu — provider nou de scris + lună(i) de acumulare înainte de a avea suficient istoric pentru feature-uri utile |

**Observație centrală, care contrazice ordinea cerută**: **Shots și Shots on Target sunt, de departe, cele mai ieftine și mai sigure — exact opusul poziției 1-2 fiind „ușor de amânat"**. Possession (poziția 4, cea mai joasă prioritate cerută) e de fapt a doua ca fezabilitate, dar structural diferită (doar incrementală). Big Chances (poziția 3) e practic blocată azi, indiferent de cât de mult ar conta pentru model — nu e o chestiune de prioritizare, e o chestiune de sursă inexistentă.

---

## 5. Feature-uri derivate propuse

Nu doar exemplele din cerere — toate candidatele identificate, grupate pe sursă.

### 5.1 Din Shots / Shots on Target (fezabile azi, date deja parțial disponibile)

1. **`shot_dominance`** — `home_shots_avg_recent − away_shots_avg_recent` (medie glisantă, aceeași fereastră ca `corner_dominance`).
2. **`sot_dominance`** — echivalentul pentru șuturi pe poartă.
3. **`shot_accuracy`** — `shots_on_target / shots` (per echipă, medie glisantă) — proxy pentru calitatea tehnică a șuturilor, nu doar volumul.
4. **`shot_accuracy_diff`** — diferența home−away a lui #3.
5. **`finishing_efficiency`** — `goals_scored / shots_on_target` (medie glisantă) — proxy pentru „claritate în fața porții", distinct de volumul de șuturi.
6. **`defensive_efficiency`** — `goals_conceded / opponent_shots_on_target_faced` (medie glisantă) — proxy pentru calitatea apărării/portarului, complementar lui `home_defensive_rating` existent (care e derivat din goluri, nu din șuturi primite).
7. **`shots_per_goal`** — inversul lui #5 — **redundant cu #5, nu se propun ambele simultan** (risc de coliniaritate, semnalat explicit, nu ignorat).
8. **`opponent_shot_pressure`** — media șuturilor PERMISE de adversarii recenți ai unei echipe (nu ai echipei înseși) — extensie directă a conceptului „Strength of Schedule" deja în roadmap (P5, `ML_EVOLUTION_ROADMAP.md`), aplicată la șuturi în loc de ELO.
9. **`shot_volume_home_away_split`** — medie separată pe context acasă/deplasare, nu blendată — **îmbunătățire reală față de tiparul actual** (`ShotsTracker`/`FoulsTracker`/`CornerCardTracker` combină azi meciurile acasă+deplasare într-un singur istoric per echipă, fără distincție de context) — candidat de etapă ulterioară, nu inițială (complexitate suplimentară, valoare nedemonstrată încă pentru varianta simplă).

### 5.2 Din Possession (fezabile doar după activarea sursei live)

10. **`possession_differential`** — `home_possession_avg − away_possession_avg`.
11. **`possession_efficiency`** — șuturi (sau șuturi pe poartă) per unitate de posesie — „cât de eficient transformă o echipă controlul mingii în ocazii", distinge stilurile „posesie sterilă" de „posesie productivă".
12. **`possession_vs_elo_gap`** — diferența dintre posesia reală a unei echipe și posesia „așteptată" dat fiind ELO-ul ei relativ — semnal de „joacă sub/peste nivelul ratingului azi".

### 5.3 Din Big Chances (blocate — propuse condiționat, doar dacă sursa apare vreodată)

13. **`big_chances_created_diff`** — home−away, medie glisantă.
14. **`big_chances_conversion`** — `goals / big_chances` — proxy de „luck vs. skill" în finalizare, mai curat decât `finishing_efficiency` (#5) fiindcă separă explicit ocaziile clare de șuturile de la distanță/fără șansă reală.
15. **`big_chances_missed_diff`** — ocazii mari ratate — semnal de instabilitate/formă proastă independent de rezultat.

### 5.4 Combinate (necesită ≥2 din cele 4 statistici simultan)

16. **`shot_quality_index`** — combinație ponderată de `shot_accuracy` + `big_chances_conversion` (dacă disponibil) — un singur scor de „cât de periculos atacă o echipă", nu doar cât de mult atacă.
17. **`control_vs_output_gap`** — `possession_differential` vs. `shot_dominance` — echipe cu posesie mare dar șuturi puține (posesie sterilă) vs. echipe eficiente cu posesie mică (contraatac).

---

## 6. Pentru fiecare feature derivat — rațional, calcul, risc de scurgere, validare

Toate feature-urile de mai jos urmează **exact** disciplina deja stabilită și validată pentru `corner_dominance`/`card_diff`/`foul_diff` (ADR-012/013) — nu se propune o disciplină nouă.

| Feature | De ce ajută predictorul | Calcul | Risc de scurgere | Validare |
|---|---|---|---|---|
| `shot_dominance`, `sot_dominance` | ELO domină modelul (15-20×), dar e un rating pe termen lung — șuturile recente captează forma imediată, complementar formei bazate pe rezultate (`home_form_score`, deja slab, 0,0015 importanță) | Diferență de medii glisante (fereastră `FORM_WINDOW`), identic cu `corner_dominance` | Zero, dacă tracker-ul urmează disciplina „returnează media DINAINTE de meci" (deja implementată de `ShotsTracker`, doar neconectată la un feature propriu) | Test de ablație walk-forward, exact metodologia `CORNER_CARD_DOMINANCE_ABLATION_2026-07-13.md` — comparat cu benchmark-ul oficial ADR-020 |
| `shot_accuracy`, `shot_accuracy_diff` | Distinge „echipă care șutează mult, dar prost" de „echipă eficientă" — informație absentă azi din `home_offensive_rating` (bazat pe goluri+SOT+posesie, nu pe rata de conversie șut→șut pe poartă) | Raport de medii glisante (nu raport per-meci, pentru stabilitate pe eșantioane mici) | Zero — strict din meciuri trecute | Ablație, plus verificare explicită de coliniaritate cu `home_offensive_rating`/`home_defensive_rating` existente (risc de redundanță, §8.5) |
| `finishing_efficiency`, `defensive_efficiency` | Separă „calitatea atacului" (câte ocazii bune) de „calitatea finalizării" (cât de bine le transformă) — distincție absentă azi | Raport goluri/SOT, medii glisante | Zero | Ablație — atenție la eșantioane mici (echipe nou-promovate, puține meciuri reale în fereastră — reutilizează gardă deja existentă „`None` dacă fereastra e goală") |
| `opponent_shot_pressure` | Extensie directă a P5 (Strength of Schedule, deja în `ML_EVOLUTION_ROADMAP.md`) aplicată la volum de joc, nu doar rating | Media șuturilor permise de adversarii din ultimele N meciuri ale unei echipe | Zero, dacă folosește strict adversari din meciuri TRECUTE | Ablație, testat separat de P5 (nu presupune că beneficiul se adună liniar) |
| `shot_volume_home_away_split` | Multe echipe joacă structural diferit acasă vs. deplasare (deja reflectat parțial în `HOME_ADVANTAGE`, dar global, nu per-echipă) | Două medii glisante separate per echipă, în loc de una blendată | Zero | Ablație — comparat explicit cu varianta blendată (#1), nu doar cu absența featureului, ca să demonstreze că split-ul chiar aduce ceva peste varianta simplă |
| `possession_differential`, `possession_efficiency`, `possession_vs_elo_gap` | Completează ponderea „irosită" de 25% din `compute_team_offdef_rating` (§2.3) — singurul feature din toată lista cu o legătură DEMONSTRATĂ (nu doar teoretică) la o parte deja existentă, dar inactivă, a modelului | Diferențe/rapoarte de medii glisante, identic ca disciplină | Zero, dar **atenție operațională**: fereastra de date va fi mică multă vreme (doar meciuri de la data activării sursei live înainte) — validarea trebuie explicit să raporteze `n` (mărimea eșantionului), nu doar rezultatul agregat | Ablație, dar amânată până la acumularea unui istoric minim (`MIN_SAMPLES_TO_TRAIN`-style prag, de definit explicit înainte de testare, nu ad-hoc) |
| `big_chances_*` (toate) | Teoretic cel mai curat semnal de „calitate a atacului" din toată lista — separă explicit ocaziile clare de zgomotul șuturilor fără șansă reală | Diferențe/rapoarte, identic | N/A — condiționat de existența sursei | N/A — nu poate fi validat fără date; rămâne „necunoscut", consistent cu ADR-001, nu aproximat din alte statistici |
| `shot_quality_index`, `control_vs_output_gap` | Combină semnale din mai multe statistici într-un singur scor — reduce dimensionalitatea, dar crește riscul de a ascunde care componentă contribuie real | Combinație ponderată (ponderi de calibrat, nu presupuse) | Zero, dacă componentele de bază sunt deja curate | Ablație pe scorul combinat, ȘI pe fiecare componentă separat — dacă scorul combinat nu bate suma componentelor individuale, nu se promovează (regulă adăugată explicit aici, consistentă cu ADR-020: nu se adaugă complexitate fără câștig demonstrat peste alternativa mai simplă) |

---

## 7. Ordinea exactă de implementare — NU urmează prioritatea 1-2-3-4 cerută

Ordinea de mai jos e organizată după **fezabilitate + cost + risc**, nu după ordinea Shots→SOT→Big Chances→Possession din cerere — divergența e semnalată explicit mai sus (§4), nu ascunsă, și fiecare etapă rămâne mapată clar la statisticile cerute.

### Etapa A — Închiderea buclei pe Shots/SOT (infrastructură deja 90% gata)

1. Investighează plafonul de 66,6-66,7% (§8.1) — determină dacă merită efort de creștere a acoperirii înainte de a promova orice feature nou peste date parțiale.
2. Scrie tracker-ul lipsă pentru Shots brut (identic ca tipar cu `FoulsTracker`) — `ShotsTracker` există deja pentru SOT, dar nu pentru șuturile totale.
3. Calculează toate feature-urile din §5.1 (1-8, exclus #9 — home/away split, amânat la o etapă ulterioară).
4. Ablație walk-forward, exact metodologia deja validată — comparat cu benchmark-ul oficial ADR-020.
5. Promovare condiționată de dovadă (consistent cu ADR-020: nu se adaugă fără câștig demonstrat).

### Etapa B — Decizie explicită de Possession (nu implementare implicită)

6. Decizie separată, explicită: se acceptă costul unei surse noi (implementare `ApiFootballProvider.get_team_stats()`, azi stub) pentru un beneficiu doar incremental (fără istoric retroactiv)?
7. Dacă da: implementare provider + activare sincronizare zilnică + perioadă de acumulare (luni, nu zile) înainte de orice test de ablație semnificativ statistic.
8. Feature-urile din §5.2, testate abia după acumularea unui eșantion minim explicit definit.

### Etapa C — Home/away split + feature-uri combinate (rafinare, nu extindere de sursă)

9. `shot_volume_home_away_split` (#9) — doar dacă Etapa A demonstrează valoare pentru varianta simplă întâi.
10. `shot_quality_index`, `control_vs_output_gap` — doar după ce componentele individuale sunt deja promovate sau clar respinse.

### Etapa D — Big Chances (blocată, nu programabilă azi)

11. Rămâne explicit „necunoscut"/„blocat" până una din: (a) apare o sursă nouă conformă ToS, (b) se ia o decizie de buget pentru Opta/Wyscout, (c) se acceptă explicit riscul ToS al SofaScore/FotMob (nerecomandat). **Nu se programează pe o axă de timp** — depinde de o decizie externă acestui document.

**De ce această ordine, nu cea cerută**: Etapa A costă aproape nimic (infrastructură + sursă deja existente, doar de conectat), riscul e zero, iar rezultatul (pozitiv sau negativ) informează direct dacă merită investit în Etapa B (mai costisitoare, cu lead-time lung). Inversarea ordinii — a începe cu Possession sau a aștepta Big Chances — ar bloca inutil un câștig ieftin și rapid testabil, exact tiparul deja stabilit de P1-P3 („epuizăm ce e ieftin de testat înainte de a investi în ce e scump").

---

## 8. Riscuri tehnice identificate

### 8.1 Plafonul de 66,6-67% — cauză probabilă, neconfirmată 100%

Toate cele 5 ligi mari plafonează la exact acest interval, pentru TOATE coloanele deodată (nu doar unele) — tipar prea uniform pentru a fi întâmplător. Ipoteza cea mai susținută de dovezi (nu confirmată direct în acest audit, necesită verificare separată): mirror-ul CSV (`Club-Football-Match-Data-2000-2025`) se oprește la finalul sezonului 2024/25 (confirmat în `DATASET_CAPABILITY_AUDIT`), în timp ce `match_history` conține și sezonul 2025/26 în desfășurare — rândurile din sezonul curent n-ar avea nicio potrivire în sursa statică, indiferent de acuratețea matching-ului. Dacă adevărat: **acoperirea nu va crește niciodată peste acest plafon fără o sursă live/incrementală suplimentară** — o limitare structurală a sursei alese pentru Etapa A, nu un bug de cod.

### 8.2 Duplicare de reprezentare a ligii — descoperire nouă, paralelă cu P3.5

`match_history` conține rânduri sub numele canonic („Premier League", 1.140 rânduri) ȘI, separat, sub codul brut de divizie („E0", 1.559 rânduri) — seturi disjuncte, backfill-ul rulează azi doar pe numele canonic (`LEAGUE_DIVISION_CODES`). Dacă rândurile „E0" reprezintă (parțial sau total) aceleași meciuri reale sub o etichetă de ligă neconsolidată, e exact același tip de problemă găsit în `TEAM_IDENTITY_AUDIT.md`, dar la nivel de LIGĂ, nu de echipă — nesemnalat până acum, nu investigat aici (în afara scopului acestui document), dar semnalat explicit ca risc real de urmărit separat.

### 8.3 Surse incomplete / inconsistente între ligi

Romania SuperLiga are 0% acoperire pentru orice statistică de meci din sursa curentă — un model antrenat global ar putea învăța tipare spurii legate de „ce ligă are date reale vs. proxy", nu de fotbal propriu-zis, dacă feature-urile noi nu gestionează explicit lipsa lor (deja acoperit de disciplina „`None`, niciodată aproximat", dar de reverificat specific pentru fiecare feature nou din §5).

### 8.4 Cost de backfill pentru surse viitoare

API-Football gratuit (100 req/zi) face backfill istoric impracticabil pentru Possession — orice decizie de a merge pe această sursă acceptă implicit „fără istoric retroactiv", nu doar „cost mic de request-uri".

### 8.5 Risc de redundanță/coliniaritate — nou, specific acestui set de feature-uri

Spre deosebire de corner/card/foul (feature-uri complet noi la momentul promovării lor), Shots on Target **contribuie deja, indirect**, la `home_offensive_rating`/`home_defensive_rating` (existente în `FEATURE_COLUMNS`) prin `compute_team_offdef_rating()`. Adăugarea unui feature RAW de SOT separat riscă să dubleze un semnal deja parțial prezent — testul de ablație trebuie să verifice explicit câștigul MARGINAL peste ratingurile existente, nu doar față de un model fără SOT deloc.

### 8.6 Normalizare — echipă (rezolvată), ligă (nerezolvată, vezi 8.2)

Normalizarea de nume de echipă e deja rezolvată la scriere (P3.5, Faza 1) — `MatchStatsBackfillService` folosește deja `normalize_team_name()` la matching, deci beneficiază automat de fix-ul deja aplicat. Normalizarea de nume de ligă nu are un mecanism echivalent demonstrat aici.

### 8.7 Probleme juridice — doar pentru Big Chances/Possession via surse nerecomandate

Shots/SOT via football-data.co.uk: zero risc nou. Possession via API-Football: risc scăzut (ToS oficial). Orice cale spre Big Chances prin SofaScore/FotMob/WhoScored: risc ridicat, deja documentat, deja nerecomandat — reconfirmat aici, nu redeschis.

### 8.8 Prospețime — sursă statică vs. nevoia de sincronizare continuă

Mirror-ul CSV nu se actualizează automat cu sezoane noi (§8.1) — o dependință pe termen lung de această sursă unică ar îngheța acoperirea la sezonul 2024/25 pentru totdeauna, fără o decizie separată de a adăuga o sursă incrementală (posibil chiar football-data.co.uk în format live, dacă există, neverificat aici).

### 8.9 Cost de menținere a duplicării de cod (§2.3)

`ShotsTracker` (offline) și `oracle_engine._real_avg_shots_on_target()` (live) fac calcule echivalente pe căi separate — nu diverg azi, dar orice modificare viitoare a logicii de calcul trebuie aplicată în ambele locuri, altfel modelul de antrenare și motorul live ar folosi definiții diferite de „SOT recent" fără să fie detectat automat.

---

## 9. Roadmap recomandat

### Etapa 1 — Shots + Shots on Target (Etapa A din §7)

Cost minim, risc zero, infrastructură 90% deja existentă. Livrabil: `ShotsTracker` extins pentru șuturi totale, 8 feature-uri derivate calculate, ablație walk-forward completă, decizie explicită Accepted/Rejected per feature, investigarea plafonului de 66,7% (§8.1) ca precondiție de raportare onestă a acoperirii reale.

### Etapa 2 — Decizie de Possession (Etapa B din §7)

Nu implementare implicită — o decizie explicită, separată, de arhitect: costul (provider nou de scris, lead-time de luni pentru istoric util) justifică beneficiul (completarea ponderii de 25% azi irosite în blend-ul de rating)? Dacă da, implementare + acumulare + ablație abia după prag minim de eșantion.

### Etapa 3 — Rafinare (Etapa C din §7)

Home/away split și feature-uri combinate — doar dacă Etapa 1 demonstrează valoare pentru versiunile simple. Nu se investește în rafinare peste un feature încă nedemonstrat.

### Etapa 4 — Big Chances (Etapa D din §7)

Rămâne explicit blocată, fără axă de timp, până la o decizie externă (sursă nouă / buget / acceptare de risc ToS, nerecomandată). Nu intră în programarea activă a proiectului.

**Justificarea ordinii, pe scurt**: costul crește monoton de la Etapa 1 la Etapa 4 (infrastructură deja gata → decizie de sursă nouă cu lead-time → rafinare condiționată de succes anterior → sursă inexistentă), iar valoarea fiecărei etape ulterioare depinde parțial de rezultatul celei anterioare (Etapa 3 depinde de Etapa 1; Etapa 2 e independentă, dar structural mai costisitoare decât Etapa 1). Aceasta e exact disciplina deja aplicată cu succes la P1→P2→P3→P3.5: se epuizează întâi ce e ieftin și rapid de testat, înainte de a investi în ce necesită decizii de buget sau timp de acumulare.

---

## Ce NU tratează acest document

Nu implementează niciun tracker, serviciu, provider sau feature. Nu modifică schema Supabase. Nu creează ADR (orice extindere de schemă viitoare — coloane noi pentru Possession dacă nu există deja, eventual Big Chances — va necesita un ADR separat, conform disciplinei deja stabilite, ADR-011 ca precedent direct). Nu investighează §8.2 (duplicarea de ligă) în profunzime — doar o semnalează. Nu decide dacă merită bugetul pentru Opta/Wyscout — rămâne o decizie explicită separată, a arhitectului.
