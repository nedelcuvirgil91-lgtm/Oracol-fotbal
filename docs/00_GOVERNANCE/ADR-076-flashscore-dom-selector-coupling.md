# ADR-076 — Cuplajul extragerii Flashscore la `data-testid` și absența unui semnal de rupere

**Status**: PROPUNERE (2026-10-17) — cere aprobare explicită înainte de implementare
**Autor**: sesiune Claude Code, la cererea proprietarului produsului
**Înlocuiește / modifică**: nimic. Atinge `providers/flashscore/normalizer.py` (extragere), nu contracte de date.
**Legături**: ADR-045 (Single Owner), ADR-036 (Canonical Feature Ownership), ADR-072 (clasa „indicator înghețat"), migrațiile 008/026/032/035/037

---

## 1. Context — ce s-a rupt, și de când (măsurat, nu deduse)

Extragerea statisticilor de meci din Flashscore a încetat să producă date. Nu
printr-o eroare, nu printr-un eșec de rețea, nu printr-un eșec de scriere: prin
**tăcere**. Funcțiile de extragere întorc dicționare goale, iar `COALESCE`-ul
din RPC-ul canonic tratează un `None` ca „n-am nimic de adăugat". Rezultatul e
indistinct, pentru orice consumator, de „meciul n-are încă statistici".

Nu e un eveniment, sunt **două**, la 13 zile distanță, pe două familii diferite
de selectori. Seria zilnică de scrieri (read-only pe producție, 2026-10-17):

| Zi | `match_statistics_extended` | `player_match_stats` | `player_match_stats_extended` | `flashscore_match_context` (H2H) |
|---|---:|---:|---:|---:|
| 6 sep | 1497 | 2449 | 12922 | 869 |
| 7 sep | 487 | 783 | 4179 | 506 |
| **8 sep** | **377** | 309 | 1505 | 100 |
| **9 sep** | **0** | 312 | 1554 | 95 |
| 13 sep | 0 | 2340 | 12369 | 846 |
| **21 sep** | 0 | **545** | **2415** | 1721 |
| **23 sep** | 0 | **0** | **441** | 0 |
| 24 sep → 17 oct | 0 | 0 | 0 | 90 … 2717 |

**Evenimentul 1, 8→9 septembrie.** `match_statistics_extended` cade de la 377 la
zero și nu mai revine. Tabelele de jucători scriu normal încă două săptămâni.

**Evenimentul 2, 21→23 septembrie.** Cad tabelele de jucători. H2H-ul continuă
neatins până azi (2717 rânduri scrise pe 17 octombrie).

Faptul că H2H-ul și `match_events` scriu normal tot intervalul **exclude**
rețeaua, autentificarea, GDPR-ul, scrierea în bază și descoperirea meciurilor.
Ce rămâne e extragerea.

### 1.1 Cauza, determinată prin măsurătoare pe pagina reală

POC izolat, 6 iterații, ultima în jobul `117434543468` (dispatch manual, zero
credențiale de bază de date, zero scriere). A făcut un recensământ al tuturor
selectorilor pe care `normalizer.py` se sprijină, fiecare pe tabul pe care e
folosit efectiv. **Șase sunt morți pe pagina de azi:**

| Tab | Selector | Rol | Victima |
|---|---|---|---|
| stats | `wcl-statistics-category` | eticheta statisticii | toate cele 45 de categorii |
| stats | `wcl-statistics-value` | valorile home/away | idem |
| lineups | `wcl-scores-simple-text-01` | număr + nume jucător | roster + (prin join) statistici avansate |
| summary | `wcl-scores-overline-02` | scorul la pauză | `home_ht_goals`/`away_ht_goals` |
| standings | `wcl-tableBodyRow` | — | **niciuna** (vezi §1.3) |
| standings | `wcl-tableBodyCell` | — | **niciuna** (vezi §1.3) |

Containerul `wcl-statistics` **trăiește** — 45 de rânduri pe tabul de
statistici. Deci nu s-a mutat nimic și nu s-a schimbat nicio adresă: s-au
redenumit **copiii**. Structura reală de azi, citită din HTML-ul paginii (nu
reconstruită):

```html
<div data-testid="wcl-statistics" class="wcl-statistics_vZTGP …">
  <div class="wcl-labelRow_42JBQ">
    <div><div class="wcl-value_Ywp3J wcl-small_B9bSY">0.45</div></div>
    <div class="wcl-label_sO4bA">
      <span data-testid="wcl-simple-text-01" class="… wcl-name_2lXWg">Expected goals (xG)</span>
      <svg data-testid="wcl-icon-settings-info-rounded" …></svg>
    </div>
    <div class="wcl-awayValue_smmfR"><div class="wcl-value_Ywp3J …">1.54</div></div>
  </div>
```

Două tipare distincte, amândouă măsurate:

- **Redenumire de familie**: segmentul `scores` a căzut din valorile
  `data-testid`. `wcl-scores-simple-text-01` → `wcl-simple-text-01` (100 de
  apariții pe tabul lineups), `wcl-scores-overline-02` → `wcl-overline-02`.
  Asta explică, cu o singură cauză, evenimentul 2 în întregime: roster-ul ȘI
  scorul la pauză. Datarea independentă confirmă: ultimul meci cu scor la pauză
  e **21 septembrie** (2 din 2), primul fără e **24 septembrie** (0 din 1) —
  aceeași fereastră ca prăbușirea roster-ului.
- **Dispariție cu mutare în clase**: `wcl-statistics-category` și
  `wcl-statistics-value` nu s-au redenumit, au dispărut. Eticheta trăiește
  acum într-un `div.wcl-label_*`, valorile în `div.wcl-value_*`, cea a
  oaspetelui învelită în `div.wcl-awayValue_*`. Asta e evenimentul 1.

### 1.2 Victima de ordinul doi, `player_match_stats_extended`

N-are selector rupt: tabelul de pe tabul „Player stats" se citește corect azi
(30 de rânduri, 270 de celule, exact cele 9 coloane așteptate). A murit prin
**dependență**. `persistence._join_player_stats_with_roster()` rezolvă echipa
fiecărui jucător prin potrivire de nume cu roster-ul din Lineups, iar un rând
fără potrivire e **exclus explicit, niciodată ghicit** (comportamentul corect,
North Star #8). Roster-ul fiind gol, toate rândurile se exclud.

Un defect cu patru victime, din două cauze. Nu patru defecte.

### 1.3 Cele două rânduri de clasament sunt un fals pozitiv al măsurătorii mele

`wcl-tableBodyRow`/`wcl-tableBodyCell` ies morți **pe tabul standings al unui
meci**, dar acolo producția nu-i folosește. `normalize_standings()` citește
`.tableCellParticipant__name` (20 de potriviri, viu) și
`[data-testid^='wcl-badgeForm-']` (120, viu). Selectorii `wcl-tableBody*`
aparțin lui `normalize_player_match_stats_table()`, care îi folosește pe tabul
**player_stats**, unde sunt vii.

Verificat în date, nu doar în cod: `flashscore_standings_snapshot` are ultima
scriere **17 octombrie** — sănătos. Consemnez falsul pozitiv în loc să-l
ascund: un recensământ care rulează fiecare selector pe fiecare tab ar fi dat
șase „morți" fără sens. Perechea (selector, tab) trebuie să fie cea din cod.

---

## 2. Paguba, cuantificată

**2.1 Statistici de meci, direct.** Acoperirea xG real pe meciuri terminate,
per lună: iulie **54,8%** → august **76,4%** → septembrie **26,4%** →
octombrie **0,4%** (1 meci din 232). `home_shots` urmează exact aceeași serie
(141 în septembrie, 1 în octombrie) — aceeași sursă.

**693 de meciuri terminate** de la 9 septembrie n-au xG real.

**2.2 Trei dintre cele 14 feature-uri ML sunt înghețate în timp — și nimic nu
o spune.** `corner_dominance`, `foul_diff`, `shot_dominance` sunt în
`FEATURE_COLUMNS` (promovate prin ablație: `SHOT_DOMINANCE_ABLATION_2026-07-15`,
ADR-012/013/021). Verificat: **nu sunt NULL** — 216 din 232 de meciuri de
octombrie le au populate. Ar fi fost mai bine dacă erau.

`supabase_client.get_team_recent_match_events()` filtrează
`home_corners IS NOT NULL` și ia ultimele 5 meciuri **care au** statistici.
Deci feature-ul se calculează, dar din meciuri tot mai vechi. Măsurat pe 10
echipe care joacă în următoarele 7 zile:

| Echipă | Ultimul meci CU statistici | Ultimul meci jucat | Decalaj |
|---|---|---|---:|
| Ararat-Armenia | 27 aug | 15 oct | 49 zile |
| AFC Bournemouth | 5 sep | 10 oct | 35 zile |
| AS Roma | 5 sep | 11 oct | 36 zile |
| AC Milan | 6 sep | 11 oct | 35 zile |
| Aston Villa | 8 sep | 14 oct | 36 zile |

Niciuna n-are nimic mai nou de **8 septembrie**. Fereastra de 5 meciuri e
întreagă din august–septembrie, pentru toate echipele, și se învechește cu o
zi în fiecare zi. **E exact clasa ADR-072** (un indicator înghețat citit ca
proaspăt) și clasa „forma 2" din defectul filtrului de competiție: date reale,
vechi, fără niciun câmp care să răspundă la „cât de vechi".

**2.3 Providerii de rezervă n-au fost întrebați niciodată.** Din cele 693 de
meciuri fără statistici, **691 sunt marcate `has_stats = true`** în
`flashscore_data_completeness`. Rutarea Single Owner (ADR-045) folosește exact
acel câmp ca să NU interogheze Soccer Football Info/FreeLF pentru un meci pe
care Flashscore l-a acoperit. Deci pentru 691 de meciuri calea de rezervă a
fost sărită — corect după regulă, pe baza unui semnal fals.

**2.4 Scorul la pauză**: zero din 232 de meciuri de octombrie, 456 din 534 în
septembrie. Nu alimentează nicio predicție (verificat: `home_ht_goals` nu e în
`FEATURE_COLUMNS`), e informativ în Team Profile.

---

## 3. De ce a fost tăcut 39 de zile — și de ce nu e „n-am fost atent"

Trei mecanisme independente au trebuit să fie aliniate, și au fost:

**(a) Indicatorul de acoperire măsoară prezența paginii, nu succesul
extragerii — prin decizie documentată.** `persistence.compute_data_completeness()`
e `{tab: bool(pages.get(tab))}`, iar docstring-ul propriu o spune explicit:
*„prezenta paginii FETCH-uite (nu succesul extractiei ulterioare — definitie
simpla, robusta, verificabila direct din `pages`, fara ambiguitatea «cat de
bine s-a extras»)"*. Decizia e defensabilă în sine. Consecința ei nu fusese
niciodată pusă alături de ea: **același câmp rutează providerii de rezervă.**
Un indicator proiectat ca să nu judece calitatea a devenit poarta care decide
dacă mai încercăm altă sursă.

Agravant, deja scris în proiect și necitit: `FUNCTIONAL_COMPLETION_REPORT.md`
consemna pe **3 august** că `coverage_percent = 100%` pe 328 din 328 de rânduri,
`count(DISTINCT coverage_percent) = 1`, **zero variație, niciodată**. Un
indicator cu o singură valoare posibilă nu e un indicator. Măsurat azi, pe
rândurile de octombrie: `has_stats = true` și `coverage 100%` pe **toate** zilele,
inclusiv pe fixture-uri **viitoare** (31 octombrie, 50 de rânduri) unde
statisticile nu pot exista prin construcție.

**(b) Semnalul care exista era la nivelul greșit.** `_join_player_stats_with_roster`
loghează un `WARNING` **per jucător** neîmperecheat — adică ~30 de linii pe meci,
îngropate într-un log de peste 100.000 de linii pe rulare. Niciun semnal la
nivelul care contează: „meciul ăsta a produs zero rânduri".

**(c) Extragerea eșuată și absența datelor sunt indistincte în aval.** RPC-ul
canonic e `COALESCE(m.existent, p->nou)`. Un `None` dintr-o extragere ruptă și
un `None` dintr-un meci care încă n-a fost jucat produc exact aceeași scriere:
niciuna.

---

## 4. Decizie

### 4.1 Se repară extragerea, în trei pași, fără nicio schimbare de contract

**P1 — selectorii de statistici.** `_extract_labeled_stat_pairs()` citește
eticheta și valorile prin cascadă: `data-testid` vechi dacă mai există, altfel
**token de clasă CSS-module**. Niciodată clasa întreagă: `wcl-value_Ywp3J`
conține hash de build, iar a lega selectorul de el ar reintroduce exact
defectul de reparat, în formă nouă, la următorul deploy Flashscore.

Potrivirea se face pe **token**, nu pe prefix de șir. Diferența nu e teoretică:
prima versiune a candidatului folosea `startswith("wcl-label")`, care prinde și
`wcl-labelRow_*` — părintele care conține valoare + etichetă + valoarea
oaspetelui. Rezultatul erau etichete poluate (`"0.45Expected goals (xG)1.54"`),
iar cele 10 etichete din `STAT_LABEL_TO_FIELDS` ieșeau toate „absente". Un
token e `c == "wcl-label"` sau `c.startswith("wcl-label_")` — `wcl-labelRow_`
nu se potrivește.

Partea oaspetelui se determină **semantic**, prin strămoșul `wcl-awayValue*`,
cu ordinea DOM ca rezervă logată — exact tiparul deja impus în proiect de
incidentul de orientare gazdă/oaspete (`duelParticipant__home/away` peste
`seen[0]`/`seen[1]`). Cele două semnale au fost verificate independent pe
pagina reală și sunt concordante (`valoare[0]` nu are strămoș `awayValue`,
`valoare[1]` are).

**P2 — familia `wcl-scores-*` → `wcl-*`.** Cascadă de `data-testid` în
`_extract_roster_rows()` și `_extract_half_time_score()`: se încearcă forma
veche, apoi cea nouă. Cascadă, nu înlocuire oarbă — forma veche rămâne
funcțională pentru orice HTML salvat anterior, iar o eventuală lansare
etapizată a Flashscore nu produce o fereastră în care nici una, nici alta nu
merge.

**P3 — ca a treia redenumire să NU mai fie tăcută.** Două semnale, niciunul
dintre ele o schimbare de contract:

1. **La locul extragerii**: când containerul există și din el se extrage ZERO
   (`N` rânduri `wcl-statistics` → 0 etichete; rânduri de aliniament → 0
   jucători), se loghează `ERROR` cu un marcaj distinct. „Containerul e acolo,
   copiii nu se potrivesc" e exact semnătura acestei clase de defect și nu se
   poate confunda cu un meci fără date.
2. **La nivel zilnic**, în `scripts/check_data_health.py`: o clasă nouă care
   raportează **zero absolut** — niciun rând nou în `match_statistics_extended`
   în ultimele 3 zile, deși au existat meciuri terminate procesate. Pragul e
   zero, nu un procent: acoperirea xG variază legitim între ligi (54-76%
   istoric), deci orice prag procentual ar fi inventat de mine. Un zero absolut
   nu e ambiguu, și ar fi declanșat pe **11 septembrie**.

**Limita lui P3, scrisă explicit ca să nu fie descoperită mai târziu**:
semnalul de zero absolut prinde o rupere **totală**. O ruptură **parțială** —
Flashscore redenumește doar 3 din 45 de categorii — ar trece neobservată de
ambele semnale. Instrumentul pentru asta e altul (o linie de bază per categorie,
cu alarmă la cădere relativă) și **nu e în scopul acestui ADR**.

### 4.2 Ce NU face acest ADR

- **Nu schimbă `compute_data_completeness()`.** Că `has_stats` măsoară prezența
  paginii și rutează în același timp providerii de rezervă (§3a) e un **gol de
  contract real**, descoperit în timpul acestei investigații. Schimbarea lui
  atinge ADR-045 → **decizie separată, cerută explicit mai jos** (Discovery
  Rule). Până la ea, cele 691 de meciuri rămân marcate acoperit.
- **Nu recuperează cele 693 de meciuri.** Recuperarea e blocată de Delta Sync
  (`is_flashscore_match_already_collected()` sare peste un meci deja în
  `match_history`), deci cere o cale de re-colectare deliberată — altă decizie,
  §6.
- **Nu atinge formula niciunui motor.** Zero modificări în `oracle_engine.py`,
  `feature_engine.py`, `ml_predictor.py`, `recalibration.py`. Reparația
  restaurează alimentarea unor coloane cu owner deja stabilit (ADR-036), nu
  schimbă niciun parametru matematic. Dar atenție, consemnat: la prima rulare
  reparată, cele trei feature-uri ML din §2.2 se vor împrospăti brusc, după
  5-6 săptămâni de îngheț. **Nu e o regresie, e sfârșitul unei regresii** —
  aceeași formă de discontinuitate acceptată deliberat la ADR-072 §D5.
- **Nu rescrie retroactiv nimic.** Rândurile existente rămân cum sunt; dovada
  că defectul a existat nu se șterge.

---

## 5. Verificare cerută

**Înainte de merge** (offline, în `pytest tests/`):

1. Teste pe HTML **real**, copiat din pagina de azi (rândul `wcl-statistics`
   din §1.1), nu reconstruit — cele 10 etichete din `STAT_LABEL_TO_FIELDS`
   extrase corect, cu valorile home/away pe partea corectă.
2. Test că forma **veche** de HTML continuă să se extragă identic (cascada nu
   e o înlocuire).
3. Test pe eticheta poluată: structura cu `wcl-labelRow_*` NU trebuie să
   producă cheia `"0.45Expected goals (xG)1.54"`. Garda pentru exact eroarea
   comisă în candidat.
4. Semnalul de zero: container prezent + copii nepotriviți → se loghează
   `ERROR`, verificat prin contor, nu prin `AssertionError` (lecția M4 din
   ADR-073: plasa de siguranță a codului poate anula garda testului).
5. Mutații: fiecare selector nou scos pe rând, token înlocuit cu prefix de șir,
   strămoșul `awayValue` ignorat, cascada inversată. Toate trebuie prinse.

**După merge, pe date reale** (semnalul care închide ADR-ul):

6. O rulare `flashscore_foundation_data_layer` → `match_statistics_extended`
   primește rânduri noi, `home_xg_actual` se populează pentru meciuri recente,
   `player_match_stats` revine, `home_ht_goals` revine. Măsurat în Supabase,
   nu presupus din verdele testelor.
7. Starea „ÎNAINTE", înregistrată azi pentru comparație: `match_statistics_extended`
   **19320** rânduri, ultima scriere **2026-09-08**; `player_match_stats`
   **51091**, ultima **2026-09-21**; `player_match_stats_extended` **230153**,
   ultima **2026-09-23**; xG octombrie **1 din 232**.

---

## 6. Decizii cerute proprietarului produsului (Discovery Rule)

Trei descoperiri care NU erau în scopul investigației și pe care nu le extind
tacit:

**D-A. `has_stats` rutează providerii de rezervă pe baza unui semnal care, prin
construcție, nu poate ști dacă extragerea a reușit** (§3a). Variante: (i) un
câmp nou care măsoară extragerea, lăsând `has_stats` neatins; (ii) rutarea
Single Owner se sprijină pe existența rândurilor în `match_statistics_extended`,
nu pe flag; (iii) se lasă, documentat. Oricare dintre (i)/(ii) atinge ADR-045 →
ADR propriu.

**D-B. Recuperarea celor 693 de meciuri.** Flashscore păstrează statisticile pe
paginile de meciuri încheiate, deci datele sunt accesibile. Dar Delta Sync le
sare deliberat. Nu e scurgere temporală (sunt rezultate, nu feature-uri
pre-meci — North Star #7 neatins), dar e o cale de re-colectare nouă, cu cost
de rulare real. **Recomandarea mea**: după ce P1-P3 sunt dovedite pe meciuri
noi, nu înainte — altfel am re-colecta cu un extractor neverificat în producție.

**D-C. Ruptura parțială rămâne nedetectabilă** (§4.1, limita lui P3). De decis
dacă merită instrumentul per-categorie, sau dacă zero-absolut e suficient.

---

## 7. Consecințe

**Pozitive**: cele patru fluxuri de date revin; cele trei feature-uri ML
redevin proaspete; scorul la pauză revine; a treia redenumire Flashscore
produce un semnal în ziua 1, nu în ziua 39.

**Negative, acceptate conștient**: potrivirea pe token de clasă e mai fragilă
decât un `data-testid` — dacă Flashscore redenumește și clasele CSS-module
(nu doar hash-ul lor), P1 cade din nou. Nu există alternativă: atributele
dedicate testării au fost tocmai eliminate de pe acele elemente. De aceea P3
nu e opțional — el e partea care face reparația durabilă, nu selectorii.

**Cost de disciplină**: un extractor cuplat la DOM-ul unui furnizor terț e o
datorie permanentă, nu o reparație unică. Acest ADR nu o elimină; o face
**zgomotoasă** când se activează.

---

## 8. Dovezi

- POC izolat, 6 iterații, ultima jobul `117434543468` (dispatch manual, zero
  credențiale, `tests/test_poc_isolation.py` verde). Se șterge la închiderea
  investigației; dovada rămâne în istoricul GitHub Actions.
- Interogări read-only pe `Prediction` (2026-10-17): seriile zilnice din §1,
  acoperirea din §2.1, vechimea ferestrei din §2.2, cele 691 din §2.3.
- Cod citit, nu amintit: `providers/flashscore/normalizer.py:263-276, 295-310,
  472-512, 671-705`, `providers/flashscore/persistence.py:68-87, 141-152,
  222-231`, `supabase_client.py:419-457`, `ml_predictor.FEATURE_COLUMNS`.

### Lecții de metodă din această investigație

1. **Un POC care nu reproduce exact calea producției măsoară propria lui
   diferență.** S-a întâmplat de cinci ori aici: navigare prin hash în loc de
   cale, `?mid=` lipsă, GDPR nerespins, o formă de URL inventată de mine
   (`/match/football/<mid>/…`) pe care producția nu o folosește niciodată, și
   în fine o listă de etichete („Goal attempts", „Shots on goal") pe care le-am
   verificat deși `STAT_LABEL_TO_FIELDS` nu le conține — toate au dat răspunsuri
   coerente și false. Reparația trebuie validată contra **codului**, citit, nu
   contra amintirii mele despre el.
2. **Validarea candidatului ÎNAINTE de a-l scrie a prins un defect real în el**
   (`wcl-label` vs `wcl-labelRow`). Dacă aș fi scris direct în producție,
   testele scrise de mine ar fi folosit aceeași presupunere greșită și ar fi
   trecut.
3. **Un indicator cu o singură valoare posibilă e un indicator mort**, iar
   faptul că e la 100% arată exact ca sănătate. Era scris în repo din 3 august.
