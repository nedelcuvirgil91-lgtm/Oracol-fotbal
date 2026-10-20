# Plan pe deciziile deschise — 2026-10-20

**Scop**: să nu mai reluăm de la zero analiza celor cinci decizii deschise. Documentul ține
măsurătorile, **ce schimbă ele față de ce scria înainte**, pașii în ordine, și — pentru fiecare
punct — **ce ar trebui să se întâmple ca să ne schimbăm părerea**.

**Nimic din document nu e definitiv.** Un plan e o ipoteză despre ordinea costurilor, nu o
promisiune. Fiecare punct are mai jos o secțiune „Ce ar schimba decizia" tocmai ca
reevaluarea să fie ieftină, nu o rediscuție completă.

**Toate cifrele de mai jos sunt măsurate read-only pe producție pe 2026-10-20.** Nicio scriere
nu a fost făcută în timpul analizei.

---

## 0. Trei afirmații din documentele proiectului s-au dovedit FALSE

Le consemnez primele, fiindcă fiecare dintre ele a fost cauza unei încadrări greșite. Clasa e
aceeași de fiecare dată: **un document descrie o stare care nu mai e verificată.**

| Unde | Ce spunea | Ce e în realitate |
|---|---|---|
| `CLAUDE.md` D-13, reziduul | „dezbrăcarea lor ar **înlocui un orfan cu alt orfan**, iar maparea corectă cere cunoaștere de domeniu" | Fals pentru toate trei clasele. 30 din 36 de rânduri sunt **duplicate cu geamăn canonic**, nu orfane. Vezi §1. |
| `ADR-077` §cost | „SFI ar trece de la 0 la ~95 de meciuri/săptămână, cu rată de succes **nemăsurată**" | Precondiția obligatorie a căii e măsurată: **0 reușite din 75 de apeluri**, HTTP 400 uniform. Vezi §2. |
| `ADR-075` §8 | „mecanismul exact nu a fost stabilit… de investigat înainte de a implementa" | Întrebarea s-a stins singură (latență, nu regulă de sărire), dar a lăsat în loc o scriere **din afara sistemului**, nedatabilă. Vezi §3. |

**Lecția de metodă, a patra instanță în proiect**: o cifră citată dintr-un document e o
măsurătoare cu dată, nu un fapt. Înainte de a decide pe baza ei, se remăsoară. Costul
nemăsurării: aici, o recomandare inversată (ADR-077) și o încadrare greșită a unui reziduu.

---

## 1. Reziduul de „~5 nume oficiale lungi" — trei clase, trei operații diferite

### Ce e măsurat

**36 de rânduri active distincte**, nu 38. Cifra 38 număra pe echipă, iar 2 rânduri au ambele
părți sufixate. Aritmetica se închide din două direcții: 14+10+8+4+2 = 38 sloturi de echipă,
minus 2 dubluri = **36 de rânduri**; separat, 14+10+8 = 32 sloturi − 2 = **30 de rânduri** pentru
primele trei cluburi, cifră care coincide exact cu numărul de rânduri `openfootball` active cu
etichetă sufixată.

| Clasă | Rânduri | Ce sunt | Sursa | Operația corectă |
|---|---:|---|---|---|
| **A** — `FC Bayern München (GER)`, `Club Atlético de Madrid (ESP)`, `ŠK Slovan Bratislava (SVK)` | **30** | **DUPLICATE** (geamăn canonic la aceeași cheie naturală) | `openfootball%`, 100% | **supersedare** |
| **B** — `Dyn. Kyiv (UKR)` | **4** | orfane reale, cu geamăn sub alt nume | `flashscore_%` | **redenumire** (tiparul Fazei 1) |
| **C** — `Din. Minsk (BLR)` | **2** | profil unic, fără geamăn | `flashscore_%` | igienă de vocabular |

Alte tabele: **zero** rânduri în `shadow_predictions`, `flashscore_match_context`,
`consensus_capture_samples`, `elo_ratings` pentru toate cele 5 etichete. Deci complicația
append-only **nu se aplică deloc** aici.

### Clasa A — dovada că sunt duplicate, nu orfane

Toate 30 au `coliziuni = 1` la proiecția pe numele canonic, toate sunt `openfootball%`, o
singură competiție (**Champions League**), fereastra 2024-09 → 2025-04. Perechea verificată
individual:

| id | `fixture_id` | gazdă | oaspete | rezultat | `away_elo_after` | creat |
|---:|---|---|---|---|---:|---|
| 3823 | `fd_524115` | Inter Milan | **Bayern Munich** | D 2-2 | 1854 | 2 iul |
| 130925 | `openfootball_champions_league_202425_…` | Inter Milan | **FC Bayern München (GER)** | D 2-2 | **1685** | 5 aug |

Același meci, același rezultat, două rânduri live. ELO-ul diferă fiindcă lanțul fantomă nu a
acumulat niciodată.

**Redenumirea e imposibilă structural**: ar viola
`idx_match_history_natural_key_canonical ON (home_team, away_team, kickoff_date) WHERE superseded_by IS NULL`.
Operația corectă e **supersedarea** — precedentul deja aplicat de două ori (Rijeka–Dinamo Zagreb,
8 aug; rândul TSDB supersedat de cel Flashscore).

**De ce Faza 0/1 nu le-a văzut**: detectorul Fazei 1 normaliza **doar sufixul de țară**, iar
`FC Bayern München` ≠ `Bayern Munich` și după dezbrăcare. **A treia instanță a aceleiași clase de
punct orb** — o verificare care, prin construcție, nu poate vedea lucrul pe care îl caută
(primele două: verificarea pe nume EXACTE care nu putea vedea perechea `Levski Sofia` /
`Levski Sofia (BUL)`; și `flashscore_data_completeness.has_stats`, care măsura prezența paginii,
nu succesul extragerii).

### Impactul real — prospectiv ZERO

Meciurile viitoare sunt **deja** sub numele canonic scurt: `Atletico Madrid` 3 nov,
`Slovan Bratislava` 3 nov, `Bayern Munich` 7 nov. Cele 30 de rânduri sunt exclusiv istorice.
Deci paguba e la **adâncimea H2H** și la **setul de antrenare**, nu la predicția servită. Iar
ELO-ul **nu se recalculează retroactiv** (precedentul Salzburg, 17 oct), deci nici după reparație
nu se schimbă.

Asta coboară urgența și ridică, în schimb, corectitudinea de a o face cândva: e ieftină și
neambiguă, dar nu schimbă nimic ce se servește azi.

### Golul mai mare, pe care reziduul doar îl semnalează (Discovery Rule)

Clasa de duplicate `openfootball` e **invizibilă indexului unic prin construcție**, fiindcă
etichetele diferă. Am măsurat **doar subsetul sufixat** (30 de rânduri). Setul total:

- `fixture_id LIKE 'openfootball%'`: **2119 rânduri**, din care **1893 active**, 226 deja
  superseded, 7 competiții, 2021-08 → 2025-05.
- Dacă rândurile openfootball **nesufixate** duplică și ele rânduri canonice: **NEMĂSURAT.**

**Asta e elementul real, nu cele 5 nume.** Tratat separat ca punctul 5 al planului.

### Propunere

- **Clasa B (4 rânduri)** — se face: o intrare de alias `Dyn. Kyiv` → `Dynamo Kyiv` + backfill de
  4 rânduri. Exact tiparul Fazei 1, cost minim, zero ambiguitate.
- **Clasa C (2 rânduri)** — se lasă. Nu există al doilea profil cu care să se unească; e igienă de
  vocabular, nu reparație.
- **Clasa A (30 de rânduri)** — **NU** se atinge ca „redenumire". Intră în investigația clasei
  openfootball (punctul 5), cu ADR propriu: supersedarea a 30+ rânduri schimbă setul de antrenare.

### Ce ar schimba decizia

- Dacă un club din Clasa A apare **din nou** cu etichetă sufixată pentru un meci **viitor** —
  atunci impactul nu mai e doar istoric și Clasa A urcă în prioritate.
- Dacă măsurătoarea de la punctul 5 arată că duplicatele openfootball nesufixate sunt multe,
  Clasa A devine un subset al unei reparații mai mari și nu se mai tratează separat.

---

## 2. ADR-077 — decizia se reordonează; criteriul de rutare e irelevant până la o întrebare anterioară

### Ce e măsurat

`provider_call_log`, fereastra de retenție (9 zile, 11–19 oct):

| provider | apeluri | reușite | % | latență medie |
|---|---:|---:|---:|---:|
| `soccerfootballinfo` | **75** | **0** | **0,0** | 437 ms |

Defalcarea: **100% HTTP 400**, un singur endpoint — `matches/day/full/`,
`failure_reason = other_error` (**nu** `quota`, deci nu e limitare de ritm). Latența de 437 ms
arată un răspuns prompt de respingere, nu un timeout.

### Lanțul de dependență, verificat în cod

```
sync_match_statistics
  └─ soccerfootballinfo_event_resolver.resolve()        (linia 56)
       └─ client.get_matches_for_day()                  (linia 75)
            └─ GET matches/day/full/  ?d=YYYYMMDD       (soccerfootballinfo_client.py:145)  ← HTTP 400, 75/75
```

Endpoint-ul bogat `matches/view/full/` (`soccerfootballinfo_client.py:150`) cere un **`match_id`
SFI**, pe care **numai resolverul îl poate produce**.

### Ce schimbă asta

Varianta (ii) recomandată de ADR-077 — criteriul să citească `home_shots IS NULL` în loc de
`referee IS NULL` — **ar produce ZERO statistici prin construcție**: ar ruta ~95 de meciuri pe
săptămână într-o cale al cărei prim pas e rupt, cu costul a ~95 de apeluri eșuate pe săptămână.

Rata endpoint-ului bogat rămâne nemăsurată. Dar **precondiția lui obligatorie e la 0%**, iar
asta e suficient pentru decizie.

Observația care merită reținută: **un criteriu inert pe o cale moartă nu costă nimic; un criteriu
funcțional pe o cale moartă costă 95 de apeluri pe săptămână.** Defectul descris de ADR-077
(`referee IS NULL` întoarce 0 pe orice fereastră) ne-a protejat accidental.

### Propunere

ADR-077 rămâne `Proposed`, dar **decizia lui e blocată de o întrebare anterioară, nu de criteriul
de rutare**: mai trăiește SFI? O sondă read-only o închide.

| Ieșirea sondei | Ce înseamnă | Ce urmează |
|---|---|---|
| **400 și pe `matches/view/full/`** | calea e moartă cap-coadă | SFI se marchează ca provider mort — **cu audit scris + aprobare explicită**, conform regulilor de chei API; nicio „curățenie preventivă". Criteriul de rutare devine irelevant. |
| **200 pe `matches/view/full/`, 400 doar pe resolver** | doar resolverul e rupt | se repară resolverul (parametru/format), **apoi** se decide rutarea, cu o rată reală măsurată |
| **401/403** | perete de autentificare/plan | ca prima variantă, dar auditul se concentrează pe cheie |

### Ce ar schimba decizia

- Un singur apel reușit pe `matches/day/full/` → providerul nu e mort, iar 400-urile sunt
  intermitente; atunci se măsoară rata pe o fereastră mai lungă înainte de orice decizie.
- Dacă Flashscore ar începe vreodată să rateze statistici pe scară largă, SFI redevine relevant
  chiar și cu o rată mică de succes — azi nu e, fiindcă ADR-076 a reparat extragerea
  (`match_statistics_extended` 19320 → 22490).

---

## 3. ADR-075 §8 — întrebarea s-a stins; în locul ei rămâne o scriere nedatabilă

### Întrebarea din §8, închisă empiric

§8 întreba de ce colectarea Flashscore a ajuns la meciul Dortmund și nu la celelalte două.
**Răspuns: latență, nu o regulă de sărire.** Toate trei rândurile `odds_` au acum rezultat ȘI xG:

| meci | rezultat | xG (gazdă/oaspete) | potrivește H2H-ul Flashscore (dovada #1 din ADR)? |
|---|---|---|---|
| Borussia Dortmund – SV Werder Bremen | D 2-2 | 2,42 / 1,10 | ✅ 2-2 |
| PSV – SC Heerenveen | H 2-0 | 2,34 / 1,55 | ✅ 2-0 |
| Galatasaray – Kasimpasa | H 3-1 | 2,52 / 0,49 | ✅ 3-1 |

Exact cele trei scoruri pe care ADR-075 le anticipa. Dortmund a fost doar primul. Ipotezele
„fereastra de descoperire" și „Delta Sync" **nu erau necesare** — nu exista nicio regulă de
sărire, doar ordine de sosire.

### Ce a rămas în loc, și e mai rău

Cele trei rânduri placeholder Flashscore sunt acum `superseded_by` (132416, 132415, 132414) —
**cu `superseded_reason` ȘI `superseded_at` NULL pe toate trei**. Combinația e unică:

```
superseded_by IS NOT NULL                                     →  6742 rânduri
  … din care superseded_reason IS NULL                        →     4
  … din care superseded_at IS NULL                            →     3
  … din care AMBELE NULL                                      →     3   ← exact cele trei
```

**Nimic din sistem nu poate produce asta** — verificat, nu presupus:

- `services/match_identity_reconciliation_service._mark_superseded()` scrie **mereu** toate trei
  coloanele (`superseded_by`, `superseded_at`, `superseded_reason`), filtrat idempotent pe
  `superseded_by is null`.
- RPC-ul canonic `_upsert_match_canonical_locked` **doar citește** `superseded_by`
  (`WHERE superseded_by IS NULL`) — nicio atribuire, fără SQL dinamic, fără
  `jsonb_populate_record`, listă de coloane explicită. *(Prima mea citire a fost greșită:
  `position('superseded_by' in src) > 0` prinsese liniile de **citire**. Corectat prin regex pe
  atribuire.)*
- Singurele funcții din bază care scriu un `superseded_by` sunt `promote_challenger` și
  `rollback_champion` — pe `model_champions`, **altă tabelă**.
- ADR-075 e `Proposed`, nimic implementat; niciun commit din 15–20 oct îl implementează.

**Concluzie: o scriere din afara sistemului, iar singurul câmp care ar fi putut-o data e exact cel
care e NULL.** Nu pot spune cine sau când. **Nu deduc** (Regula #8 — o stare necunoscută rămâne
necunoscută).

### Propunere

1. **§8 se închide ca răspuns** (latență), cu notă că ipotezele din el erau inutile.
2. **Element nou, mic**: o gardă care cade când `superseded_by` e setat fără `superseded_reason`
   și fără `superseded_at` — fie `CHECK` în Postgres, fie o clasă nouă în `check_data_health` cu
   prag **zero absolut**. Face următoarea supersedare din afara sistemului **vizibilă**, în loc de
   tăcută. E direct North Star #9 (trasabilitate completă).
3. **ADR-075 (opțiunile A/B/C)** se decide pe meritele detectorului, știind că **cazul live s-a
   stins singur** și că `check_data_health` prinde deja clasa la ~6 zile după meci. Deci A ar fi o
   îmbunătățire de viteză, nu închiderea unui gol — exact cum nota deja `DE_URMARIT` §640-679.

### Ce ar schimba decizia

- Dacă apare o **a doua** apariție a clasei (`superseded_by` fără motiv) → nu mai e un incident,
  e un mecanism, și trebuie găsit scriitorul înainte de orice altceva.
- Dacă clasa reapare cu geamăn care **nu** are rezultat → atunci latența nu mai e explicația și
  §8 se redeschide.

---

## 4. D-14 — cauza rădăcină găsită; ancora exista și era aruncată tăcut

### Ruta deducției, închisă onest

- **39 de chei** în `model_config` azi. Lanțul documentat: 35 → 36 (ADR-072, 14 oct) → 37
  (ADR-073, 15 oct) → măsurat 38 pe 19 oct → 39 după ADR-078. Se confirmă.
- **Toate 39 sunt citite de cel puțin un fișier de producție** (verificat prin numărătoare de
  referințe, excluzând `tests/`). **Nicio cheie orfană**, deci nu există nimic anormal din care să
  numesc cheia neconsemnată. Deducția e imposibilă, nu doar grea.

### Cauza rădăcină

`model_config.updated_at` **există**, iar `supabase_client.save_config()` (linia 129) îl scrie
corect. Valoarea stocată în producție:

```
updated_at = 2026-09-06 11:29:08.321687+00     ← ÎNGHEȚAT
```

Între timp au fost cel puțin **trei** scrieri: ADR-072 (14 oct), ADR-073 (15 oct), ADR-078
(19 oct). Toate au fost `UPDATE model_config SET data = data || '…'::jsonb WHERE id = 1`.
**Niciuna n-a atins `updated_at`.** Data de 6 septembrie corespunde ultimei scrieri prin calea
aplicației (activarea ADR-071 §18).

Două concluzii, amândouă verificabile:

1. **Câmpul care ar fi ancorat lanțul exista tot timpul** și a fost ignorat de fiecare activare,
   inclusiv de ale mele.
2. **Cheia neconsemnată a fost și ea o scriere SQL brută, între 15 și 19 octombrie** — altfel
   `updated_at` s-ar fi mișcat. D-14 trece din „nedeterminabil" în „o scriere din sesiune,
   nedatată fiindcă scriitorul a sărit singura coloană care datează".

**E a patra instanță a clasei marcajului înghețat, cu mecanism NOU**: nu `on_conflict` care omite
coloana (cele 6 instanțe reparate pe 26 august), ci un `UPDATE` scris de mână care o omite. Garda
AST `tests/test_upsert_timestamp_freshness.py` citește **cod** — prin construcție nu poate vedea
SQL ad-hoc rulat prin MCP. **Golul gărzii nu e un defect al ei; e limita suprafeței pe care o
acoperă.**

### Propunere, în ordinea costului

| # | Ce | Cost | ADR? |
|---|---|---|---|
| **1** | Orice scriere viitoare de config include `updated_at = now()` | o clauză | nu |
| **2** | Nota fiecărei activări consemnează, ca acum, numărul de chei + `md5(data − cheia_nouă)`, **plus** `updated_at` → devine autodatată | zero | nu |
| 3 | Tabelă de audit append-only (`model_config_audit`) alimentată de trigger | tabelă nouă | **da** |

**Recomandare: 1 + 2, NU 3 — încă.** Variantele 1+2 recuperează exact proprietatea pe care D-14 a
pierdut-o (o ancoră fiabilă) la cost zero de schemă. Un audit cu trigger răspunde la o întrebare
diferită — „ce s-a schimbat între două date" — care a apărut **o singură dată** în proiect.

**Se acceptă explicit**: nu vom ști niciodată care a fost cheia a 38-a. Lanțul se **re-ancorează**
de la următoarea scriere, nu se reconstituie retroactiv.

### Ce ar schimba decizia

- A doua oară când întrebarea „ce s-a schimbat între două date" chiar blochează ceva → varianta 3
  devine justificată.
- Dacă `updated_at` se dovedește, după varianta 1, insuficient (de exemplu două activări în aceeași
  zi, și contează ordinea) → varianta 3.

---

## 5. F3 — proiecția documentată se reproduce exact; o singură observație structurală

### Corecția propriei mele măsurători

Prima măsurătoare arăta `market_floor_040` cu **1342 de pariuri decise** și părea că F3 e demult
complet. **Eroare de numitor, a mea.** Poarta evaluatorului numără, după dedup-ul §16 pe
`(policy_id, fixture_id)`, **fixture-uri distincte per categorie**, iar cifrele documentate sunt pe
setul **Top**. `PRAG_ESANTION_MINIM = 150` se aplică **per categorie**
(`value_selector_evaluation.py:223`), nu pe total.

Aceeași clasă de eroare ca „comparația cu reperul greșit" (14 oct). Prinsă prin verificare înainte
de a raporta, nu după.

### Pe numitorul corect

| profil | Top total | Top decise | ritm, 14 zile |
|---|---:|---:|---:|
| `market_floor_040` | **103** | 100 | **3,07/zi** |
| `market_floor_035` | 135 | 131 | 4,00/zi |
| `market_floor_030` | 156 | 151 | 4,79/zi |

Reproduce **exact** `103/99` și `3,07` din ADR-071 §F3 (diferența de 1 = o zi de creștere).

**150 − 103 = 47 la 3,07/zi ≈ 15 zile → ~4 noiembrie.** Cele 8 săptămâni se împlinesc ~31
octombrie. **Proiecția documentată stă; nicio corecție.** A patra recalculare și prima care nu
schimbă nimic.

### Observația structurală — singura noutate

- `market_floor_040` e brațul cel mai lent **prin construcție**: pragul lui de plauzibilitate de
  0,40 taie cel mai mult, deci brațul care guvernează pornirea experimentului e cel care va avea
  **mereu** cele mai puține date.
- `legacy` are **1642 Top și 0 Longshot** — nu are categoria, prin construcție. Deci o poartă
  globală „toate brațele × toate categoriile ≥ 150" **nu poate fi îndeplinită niciodată.**

Ambele împing spre citirea per braț, nu spre o poartă globală.

### Opțiuni

| | Ce | Verdict |
|---|---|---|
| **(a)** | Se așteaptă ~4 noiembrie | **recomandat.** Risc zero, cost două săptămâni, colectarea continuă, cele două constrângeri se închid împreună. |
| (b) | Citire per braț, acum. Evaluatorul marchează **deja** `esantion_insuficient` per categorie, deci un raport de azi ar semnala onest `market_floor_040`/Top ca sub-puternic și ar da verdicte pe brațele care au trecut. Zero cod nou, zero prag schimbat. | legitimă **ca citire, nu ca pornire a lui F3** |
| (c) | Coborârea pragului de 150 | **de respins.** §F3 interzice explicit ajustarea pragurilor pe parcurs; e singurul lucru care ar face rezultatul neauditabil. |

**Recomandare: (a).** Câștigul lui (b) e doar să vezi cu două săptămâni mai devreme verdicte care
nu se vor schimba. Dacă se dorește totuși o citire timpurie, (b) se rulează ca **probă**, iar F3
pornește formal când `_040` trece pragul — textul §F3 rămâne intact.

**Nimic nu se declanșează automat pe 4 noiembrie.** F3 pornește doar prin decizie umană explicită
(ADR-002). Rutina zilnică de la 07:47 UTC e ce duce asta mai departe.

### Ce ar schimba decizia

- Dacă ritmul lui `market_floor_040` scade sub ~2/zi, data se mută și se recalculează (a cincea
  oară) — nu se extrapolează.
- Dacă `policy_id` se schimbă din orice motiv, numărătoarea **se resetează** (ADR-071 §10) și
  planul se rescrie de la zero.

---

## 6. Pașii, în ordine — cu precondiții și condiții de oprire

Ordinea e dată de **informație per cost**, nu de cronologie sau de mărimea elementului.

| # | Pasul | De ce aici | Oprire / precondiție |
|---|---|---|---|
| **1** | **ADR-077** — sondă read-only pe `matches/view/full/` | cea mai mare informație pe cel mai mic cost; deblochează sau închide definitiv o decizie care stă | sonda e **read-only**, un apel; dacă cere cheie nouă sau atinge un secret → se oprește și se cere audit |
| **2** | **D-14 varianta 1** — `updated_at = now()` în orice scriere de config | o clauză, zero risc, reancorează lanțul pentru activarea următoare | nicio scriere de config **fără** SQL arătat și confirmat (North Star #6) |
| **3** | **ADR-075** — §8 se închide ca răspuns; se propune garda pe `superseded_by` fără motiv | închide o întrebare deschisă și acoperă un gol de trasabilitate real | garda e **propunere**; un `CHECK` nou pe o tabelă existentă atinge un contract → ADR |
| **4** | **Reziduul, Clasa B** — 4 rânduri `Dyn. Kyiv` → `Dynamo Kyiv` | ieftin, neambiguu, tiparul deja dovedit al Fazei 1 | backfill arătat înainte; coliziuni reverificate la momentul scrierii, nu presupuse din această analiză |
| **—** | **reevaluare** | ce s-a făcut, ce s-a schimbat, ce a apărut pe parcurs | — |
| **5** | **Clasa openfootball** — 1893 de rânduri active, duplicate posibile nemăsurate | **nu se începe înainte de reevaluare.** Supersedarea schimbă setul de antrenare → ADR propriu | se **măsoară** întâi; nicio supersedare înainte de ADR aprobat |

**Regula care guvernează toți pașii**: niciun pas nu se bundle-uiește cu altul, iar fiecare
măsurătoare „înainte/după" se consemnează. Dacă un pas descoperă un contract nou, o migrare nouă
sau o dependență neidentificată → **Discovery Rule**: implementarea se oprește, descoperirea se
prezintă explicit, proprietarul produsului decide (a) în afara scopului, (b) amendament, (c) ADR nou.

---

## 7. Ce NU e în acest plan, deliberat

- **Accidentările** (penalizarea de 30% xG, moartă) — rămân deprioritizate prin decizie explicită
  a proprietarului produsului, pe argumentul reperului extern: Oracle e la **−1,98 pp de piață pe
  97,5% din meciuri, statistic nesemnificativ** (z = 1,35), deci nu se vede headroom exact acolo
  unde accidentările ar acționa.
- **D-5** (`sweep_stale_decisions()` necablată) și **D-8** (`consensus_validation` fără fază de
  execuție) — ambele cer ADR și schimbă contracte; nu intră într-un plan de execuție până nu sunt
  decise ca decizii.
- **D-6** (backup-uri cu revizuire restantă) — cere doar un „se păstrează / se șterg", nu o
  analiză.
- **D-11** (Decision Feed nu numește acțiunea) — rămâne deschis; atinge calea de aprobare umană.
- **D-12 punctul D-C** (detectorul de rupere parțială) — are nevoie de o linie de bază; de reluat
  în jurul **2 noiembrie**, cum e deja notat.

---

## 8. Trimiteri

- `CLAUDE.md` §DECIZII ÎN AȘTEPTARE — D-13 (identități), D-14 (lanțul de amprente)
- `docs/00_GOVERNANCE/ADR-071-value-selection-policy.md` §F3, §10, §16, §19
- `docs/00_GOVERNANCE/ADR-075-cross-provider-duplicate-identity.md` §8
- `docs/00_GOVERNANCE/ADR-077-*` (propunere, criteriul de rutare SFI)
- `docs/00_GOVERNANCE/ADR-078-flashscore-team-identity.md` §7 (Faza 1)
- `docs/00_GOVERNANCE/DE_URMARIT.md` §640-679 (clasa ADR-075, acoperirea monitorului)
