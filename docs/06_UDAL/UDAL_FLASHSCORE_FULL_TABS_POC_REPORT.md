# Flashscore — POC Live, toate tab-urile, 1 meci (raport complet)

**Status**: POC live aprobat explicit ("TASK APROBAT – POC LIVE (1 singur meci)"), executat, analizat. **M0 rămâne în pauză** — următorul pas e decizia comună asupra acestui raport, nu continuarea implementării.
**Meci**: Dinamo Bucuresti 5-1 Univ. Craiova, SuperLiga, 25.07.2026 (același meci din captura trimisă).
**Metodă**: Playwright standard, fără evaziune, toate cele 7 URL-uri reale extrase direct din HTML deja salvat (nicio presupunere de URL). Rulare izolată, `tos_reviewed` neatins. Zero semne de protecție pe toate cele 7 navigări (`stopped_due_to_protection: null`).
**Evidență brută**: `docs/06_UDAL/poc_evidence/flashscore_full_tabs_poc/` (HTML + screenshot per tab + `poc_full_tabs_result.json`). Persistat și în Supabase, tabelă de test: `flashscore_poc_full_tabs_test` (migrația 034 — TEST ONLY, neatinsă de UDAL/Night Sync/Predictor).

---

## 0. Corectură importantă față de concluzia POC-ului anterior (cu 10 meciuri)

Cornere/Pase/Cartonașe/Șuturi pe poartă **există real**, exact cum ai arătat în captură — dar pe tab-ul dedicat **"Statistici"** (`/summary/stats/`), nu pe pagina "Sumar" (unde am căutat inițial). Explicația din turul anterior a fost corectă (bug de etichetă "Stats" vs "Statistics"), iar acum, cu tab-ul vizitat direct, confirm cu dovadă: **36 de categorii de statistici reale**, nu 5.

## 1. Ce câmpuri există în fiecare tab (dovadă directă)

### Tab „Sumar" (`match-summary`)
- `wcl-summaryMatchInformation`: **Referee** ("Kovacs I. (Rou)"), **Venue** ("Stadionul Arcul de Triumf (Bucharest)"), **Capacity** ("8 207" — câmp nou, nedescoperit anterior), **Attendance** ("7 128").
- Widget restrâns „Top Stats" — 5 categorii (xG, posesie, șuturi totale, ocazii mari, atingeri în careu).
- Scor final, echipe, dată/oră — deja confirmate.

### Tab „Statistici" (`match-statistics`, `/summary/stats/`) — **NOU, niciodată capturat înainte**
**36 categorii reale**, valori home/away confirmate identic cu captura ta:

| Categorie | Home | Away |
|---|---|---|
| Expected goals (xG) | 3.41 | 0.88 |
| Ball possession | 47% | 53% |
| Total shots | 18 | 9 |
| Shots on target | 7 | 5 |
| Big chances | 6 | 2 |
| **Corner kicks** | **8** | **1** |
| **Passes** | **85% (314/371)** | **87% (366/423)** |
| **Yellow cards** | **2** | **1** |
| **Red cards** | **0** | **1** |

Plus 27 categorii suplimentare, nemenționate în captură dar la fel de reale: xGOT, shots off/inside/outside box, hit woodwork, headed goals, touches in box, accurate through passes, offsides, free kicks, long passes, passes in final third, crosses, xA, throw ins, fouls, tackles, duels won, clearances, interceptions, errors leading to shot/goal, **goalkeeper saves**, xGOT faced, goals prevented, goal kicks — listă completă în evidență.

### Tab „Formații" (`lineups`, `/summary/lineups/`)
46 jucători (23 home + 23 away — XI + rezerve), nume + număr tricou, confirmat identic cu prima rundă de POC.

### Tab „Statistici jucători" (`player-match-statistics`, `/summary/player-stats/`) — **NOU**
Tabel structurat, **32 rânduri** (ambele echipe combinate, sortate descrescător după rating), coloane: **Rating**, Total shots, xG, Accurate passes, Touches, Touches in opposition box, Successful dribbles, Duels. Exemplu real: "Pop A., Striker, rating 8.7, 4 șuturi, 0.85 xG, 12/17 (71%) pase reușite".

### Tab „Cote" (`odds-comparison`)
9 valori zecimale reale confirmate, 8+ case de pariuri reale (bet365, Unibet, William Hill, 1xBet, BetMGM, Betfred, Midnite, Betway) — consistent cu runda anterioară.

### Tab „H2H"
**Corectură față de raportul POC inițial** (care marcase H2H ca „⚠️ neconfirmat"): de fapt conține **30 de rânduri reale** de participanți + scoruri (15 meciuri istorice), confirmate acum cu `wcl-matchRow-participant`/`wcl-tableScore`. Runda anterioară a ratat asta — fie timp de așteptare insuficient, fie click pe sub-secțiune greșită.

### Tab „Clasamente" (`standings`)
16 echipe, ordine reală de clasament (FCSB, FC Rapid Bucuresti, Otelul, CFR Cluj, Dinamo Bucuresti...) + 48 insigne de formă recentă. Structură DIFERITĂ (clase CSS, nu `data-testid` standard `wcl-table`) — notă de robustețe mai jos.

---

## 2. Ce poate fi extras 100% robust (etichetă-ca-cheie, verificat, nu ghicit)

- **Toate cele 36 statistici de meci** — mecanismul deja construit (`_extract_labeled_stat_pairs`, bazat pe `wcl-statistics`/`wcl-statistics-category`) funcționează **neschimbat** pe noul tab, fără nicio modificare de cod — confirmă justificarea tehnică din turul anterior.
- **Referee/Venue/Capacity/Attendance** — pattern etichetă/valoare deja construit, doar extins cu o etichetă nouă ("Capacity:").
- **Lineups (nume + număr)** — deja robust, confirmat pe 10+1 meciuri.
- **Player stats (tabel)** — structură `wcl-table`/`wcl-tableBodyRow`/`wcl-tableBodyCell`, foarte curată, poziție fixă de coloană (verificat pe un singur meci — recomand verificare pe încă 2-3 înainte de a declara "100%").
- **Odds** — valori zecimale + nume bookmaker, pattern regex simplu, deja funcțional.
- **H2H participanți/scoruri** — `wcl-matchRow-participant`/`wcl-tableScore`, aceeași familie de testid ca discovery-ul de meciuri (deja folosit cu succes în tot POC-ul).

## 3. Ce e instabil / necesită atenție

- **Player stats — fără coloană de echipă în tabel.** Cele 32 rânduri sunt combinate, sortate după rating, fără etichetă home/away directă — necesită **join după nume de jucător** cu roster-ul din tab-ul Lineups (care ARE echipa). Risc: nume ușor diferit formatate între cele două tab-uri (neverificat încă pe acest eșantion — trebuie testat explicit înainte de a-l considera robust).
- **Standings — structură non-standard.** Nu folosește `data-testid="wcl-table"` ca restul site-ului, ci clase CSS (`tableCellParticipant__name`) — posibil mai fragil la schimbări viitoare de build (hash-uri de clasă), spre deosebire de `data-testid`-uri care par stabile pe tot restul site-ului.
- **H2H — corectat acum, dar runda anterioară a ratat-o complet** — semnal că extracția H2H are o dependență de timing/randare mai sensibilă decât restul; recomand un test suplimentar (2-3 meciuri) înainte de a o declara robustă.
- **"Passes" ca procent compus** (`"85% (314/371)"`) — necesită parsare suplimentară (procent + fracție), nu doar `float()` direct ca restul statisticilor numerice.

## 4. Ce merită salvat în Supabase, pentru Predictor și ML

**Prioritate mare** (extinde direct capabilitatea deja proiectată, coloane deja existente sau ușor de adăugat):
- Toate cele 9 statistici din captura ta: possession, shots, shots_on_target, corners, passes(%), yellow_cards, red_cards — plus **goalkeeper_saves** (coloană deja creată, migrația 032, azi goală) și **fouls**, **offsides** (coloane deja existente din migrația 026, azi goale pentru Flashscore).
- **Player stats cu rating** — deblochează exact ce fusese deferred în M0 (rating de jucător), acum cu sursă curată (tabelul dedicat, nu view-ul pitch fără disambiguare).
- **Attendance** — real, gol de coloană deja identificat.

**Prioritate medie** (valoare reală pentru ML, dar necesită coloane noi):
- xG/xGOT, xA, big chances, touches in opposition box — feature-uri avansate, ar necesita mai întâi un test de ablație (per regula CLAUDE.md de ML) înainte de a intra în `FEATURE_COLUMNS` — dar **datele brute** merită salvate acum, indiferent de decizia de feature ulterioară.
- H2H (30 rânduri/meci) — util pentru completarea `match_events`-style istoric, dar Oracle Engine are deja H2H Database-First (ADR-035 D3) din `match_history` — valoare marginală, nu prioritate.

**Prioritate mică / neclar**:
- Duels/tackles/interceptions/clearances (statistici defensive avansate) — fără precedent de feature testat, fără ipoteză formulată încă.
- Standings — Oracle Engine nu are azi un consumator clar pentru clasament în timp real per meci (posibil relevant pentru context, neexplorat).

## 5. Ce modificări de schemă ar trebui făcute (propunere, neaplicate)

- `match_history`: adaugă `home/away_offsides` (**deja există**, migrația 026 — doar gol de date, nu de schemă), `home/away_goalkeeper_saves` (**deja există**, migrația 032), `home/away_fouls` (**deja există**) — deci NICIO coloană nouă necesară pentru cele 9 statistici din captură + saves + fouls + offsides.
- **`attendance`** — coloană nouă, lipsă azi (confirmat în turul anterior, reconfirmat acum).
- **`capacity`** — coloană nouă, câmp nedescoperit anterior, real.
- **`player_match_stats.rating`** — verificat direct în schema live (`information_schema.columns`): coloana **există deja** (migrația 032) — nicio schimbare de schemă necesară, doar activarea extragerii ei (deferred în M0 din lipsă de sursă curată; acum sursa curată există — tabelul dedicat de statistici jucători).
- Câmpuri avansate (xG/xGOT/xA/duels/tackles) — ar necesita coloane noi dedicate, DOAR după decizie explicită (ablație/prioritate ML), nu doar pentru că sunt disponibile.

## Recomandare, fără decizie unilaterală

Datele sunt semnificativ mai bogate decât scope-ul M0 restrâns anterior. Asta schimbă calculul: merită extinderea scope-ului M0 să includă tab-ul "Statistici" (cost mic — mecanismul de extracție deja funcționează neschimbat) și tab-ul "Statistici jucători" (cost mediu — necesită join nume↔echipă, de validat). Rămân la decizia comună, cum ai cerut — nu reiau M0 până nu stabilim împreună ce intră în scope-ul final.
