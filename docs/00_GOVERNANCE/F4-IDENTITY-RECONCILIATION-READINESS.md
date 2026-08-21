# F4 — Reconcilierea identității canonice: decizii și stare

**Status**: implementat la nivel de cod, **zero scriere în producție**. Reconcilierea propriu-zisă rămâne neautorizată.
**Data**: 2026-08-21
**Relație cu ADR-uri**: consumă ADR-025 (Approved / Architecture Frozen) și ADR-058 (F3). **Nu modifică niciunul.**

---

## 1. De ce nu e nevoie de un ADR nou

Extinderea Source Trust Policy și a regulii de selecție a rândului canonic e sancționată explicit, în două locuri independente — verificat prin citire directă, nu presupus:

- `source_trust_policy.py` (antet): *„politică operațională, evolutivă, SEPARATĂ de contractul de identitate stabilit de ADR-025. Poate fi schimbată în timp (ex. la adăugarea unui provider nou) fără a redeschide ADR-025 sau ID-025-01."*
- ADR-025 §Consecințe: *„Source Trust Policy și regula exactă de selecție a rândului canonic rămân externalizate din acest ADR — pot evolua fără un ADR nou, atât timp cât invariantul («exact un rând canonic per meci») nu e încălcat."*

Invariantul nu e atins: rămâne exact un rând canonic per meci.

## 2. Constatarea care încadrează totul

Raportul Faza 2 al ADR-025 (`docs/03_ENGINE/ADR025_PHASE2_DRY_RUN_REPORT_2026-07-16.md:29-37`) conține propria condiție de expirare:

> „normalizarea completă (`match_key()`, folosită de codul real) nu produce niciun grup suplimentar față de gruparea brută, **pentru datele curente**."

Adevărat pe 2026-07-16. F3 (ADR-058) a extins vocabularul cu 130 de rezoluții pe 2026-08-21; același `match_key()` produce acum 404 grupuri suplimentare.

**F4 nu e o politică concurentă — e aceeași descoperire ID-025-01, re-rulată după ce vocabularul s-a schimbat.** Motorul e neatins.

**Consecință structurală, rămasă deschisă**: `idx_match_history_natural_key_canonical` e pe `(home_team, away_team, kickoff_date)` **brut**. Writerii normalizează la scriere, deci intrările noi converg; rândurile istorice scrise sub un vocabular mai vechi rămân literal diferite, iar indexul nu le poate vedea ca echivalente. **Orice extindere viitoare de vocabular reproduce acest efect** — nu e specific F3. De tratat separat.

## 3. Registrul de surse — extindere calibrată empiric

Metoda e cea din ADR-024: completitudine **măsurată**, nu opinie. Măsurătoare pe meciuri terminate (`actual_result IS NOT NULL` — includerea fixture-urilor viitoare ar dilua artificial sursele care descoperă meciuri în avans), Supabase `Prediction`, 2026-08-21:

| sursă | n terminate | shots | corners | posesie | xG real | season | medie coloane non-NULL |
|---|---|---|---|---|---|---|---|
| tsdb | 13 | 100% | 100% | 100% | 100% | 0% | **69,1** |
| flashscore | 444 | 99,8% | 99,8% | 99,8% | 71,2% | 0% | **59,0** |
| football_data | 7.534 | 48,4% | 48,4% | 1,9% | 1,9% | 100% | **38,4** |
| openfootball | 2.119 | 0% | 0% | 0% | 0% | 100% | **25,0** |
| kaggle_historical | 44.152 | 0% | 0% | 0% | 0% | 7,7% | **24,1** |

`odds_api` (n=2) și `espn` (n=1) sunt sub pragul oricărei recalibrări — rang neschimbat.

**Rangurile rezultate**: `flashscore` 1, `football_data` 2, `tsdb` 3, `espn` 4, `odds_api` 5, `openfootball` 6, `kaggle_historical` 7.

- **flashscore → 1**: Foundation Data Layer (ADR-044), singura sursă cu xG real, posesie, evenimente și statistici de jucători; singura cu copii FK în cele 5 tabele derivate. Corpusul e mai mic azi fiindcă sursa e recentă — dar rangul măsoară completitudinea **per rând**, nu volumul acumulat. Direcție confirmată explicit de proprietarul produsului ca sursă primară de viitor.
- **tsdb → 3, sub football_data**: profilul per rând e cel mai bun din corpus, **dar pe n=13**. Plasarea peste football_data (n=7.534) ar fi inferență din eșantion mic — exact ce interzice regula „Verificat, nu presupus". Peste espn/odds_api, unde măsurătoarea e clară.
- **openfootball → 6**: practic identic cu kaggle (0% pe toate statisticile); diferența e exclusiv `season`.

**Ordinea relativă a celor 4 surse preexistente e neschimbată** — calibrarea ADR-024 nu e redeschisă. Verificat: nicio decizie istorică nu se inversează (cele 3.501 grupuri `fd > kaggle` și cele 3 World Cup `espn > odds_api` dau același câștigător). Gardat de `test_preexisting_relative_order_is_preserved`.

## 4. Politica de survivor — chestiunea se închide fără a alege

Verificat mecanic pe toate cele 403 grupuri automatizabile, înainte de a scrie codul: sub rangurile de mai sus, selecția „rang minim" a ID-025-01 produce **același câștigător** ca o ipotetică politică „completitudine → FK → rang → id" pe **403 din 403 grupuri, zero divergențe**.

Nu există deci niciun motiv pentru o a doua politică. **ID-025-01 rămâne neatins.**

Cele 403 grupuri au exact patru compoziții de surse:

| Compoziție | Grupuri | Canonic |
|---|---|---|
| `kaggle + openfootball` | 162 | openfootball |
| `football_data + openfootball` | 157 | football_data |
| `football_data + kaggle` | 78 | football_data |
| `flashscore + tsdb` | 6 | flashscore |

Alte proprietăți verificate: toate grupurile au exact 2 rânduri; **0 non-survivori au copii FK** → zero re-parentare; toate cele 6 FK-uri către `match_history` sunt `ON DELETE NO ACTION` (zero `CASCADE`).

## 5. Liverpool–PSG și bugul de departajare

Grupul cu scoruri contradictorii (openfootball 0–1 vs football_data 1–5) e exclus automat de `_classify_hard_conflict()`. **Alegerea survivorului nu poate ascunde problema**: merge-ul e NULL-only prin construcție, deci un scor greșit non-NULL nu poate fi corectat de nicio politică de selecție.

**Cauza, reparată la sursă (F4.5)**: `sync/sources/football_data.py` citea `score.fullTime` necondiționat și nu consulta niciodată `score.duration`. Pentru tușele decise la penalty-uri, football-data.org include departajarea în `fullTime`. Verificat aritmetic pe cazul real `fd_524100`: Liverpool 0–1 PSG, PSG 4–1 la penalty-uri → `0+1=1`, `1+4=5`.

Impact dincolo de scorul afișat: `actual_result` rămâne corect, dar diferența de goluri intră distorsionat în multiplicatorul MOV al ELO (`_mov_multiplier`) — goal_diff 4 în loc de 1 — deci eroarea se propagă în starea derivată.

Fix: se preferă `score.regularTime` când `duration == "PENALTY_SHOOTOUT"`; dacă lipsește, meciul e **sărit**, nu aproximat prin scăderea `penalties` din `fullTime` (ipoteză neverificată pe payload-uri reale; North Star #8).

**Rămâne de făcut, neautorizat**: corectarea în bază a rândului `fd_524100` (corecție factuală, în afara politicii NULL-only) și auditul celor **503 rânduri `fd_` din Champions League** pentru alte meciuri decise la penalty-uri. Câte sunt afectate nu se poate determina fără reapel API — nu s-a extrapolat.

## 6. Goluri de vocabular apărute după F3

Night_sync-ul din 21 august a adus rânduri TSDB cu nume noi. Detecție mecanică, nu ad-hoc:

- Scanare „nume = canonic_cunoscut + cuvinte suplimentare" pe cele 1.254 de nume live → **76 candidați, majoritatea falși pozitivi evidenți**: `Forest Green`→`Nottingham Forest`, `Arsenal Sarandi`/`Arsenal Tula`→`Arsenal`, `Inter Miami`/`Inter Turku`→`Inter Milan`, `Den Haag`→`Denmark`, `U Craiova 1948`→`Universitatea Craiova` (cluburi rivale distincte), `Villarreal B`/`Sociedad B` (echipe secunde), `Oxford City`→`Oxford United`. **Regula de prefix pe cuvinte NU a fost adoptată** — e exact clasa de eroare care a produs 141+ coliziuni în v1.2. Cele 10 perechi de mai sus sunt acum fixate ca teste permanente.
- Re-rulare a detecției F0 (pereche sufixată cu bază existentă literal) → **exact 1 pereche nouă**: `Iberia 1999 (GEO)` ↔ `Iberia 1999`.

Aplicate, fiecare verificat individual în date:
- `"Jagiellonia": ["Jagiellonia Białystok"]` — un singur club Jagiellonia în tot corpusul (verificat live).
- `"Iberia 1999": []` — cheie canonică goală, activează regula structurală de sufix deja aprobată la F3.

Ambele **previn** un duplicat viitor, nu creează unul: returul din 27 august există doar ca rând TSDB, iar Flashscore îl va descoperi sub formele sufixate.

## 7. Starea derivată — mecanism nou, necesar, neconstruit

`run_backfill()` **nu poate fi folosit pentru rebuild**, verificat în cod: gating v4.1 per-coloană (*„o coloană deja populată nu e niciodată suprascrisă"*), fără parametru `force`, iar `grep` pentru orice cale de reset al `BACKFILL_COLUMNS` returnează zero rezultate.

**Dovadă că problema e reală**: ADR-025 Faza 2 a raportat **0 completări pentru `home_elo`** — rândurile canonice aveau deja valori, calculate în era în care replay-ul număra fiecare meci de două ori. Contaminarea ELO din acea eră e încă în bază.

Cauza mecanică unică: `ELOTracker.ratings`, `FormTracker.history` și `H2HTracker.history` sunt dicționare cheiate pe **șirul cu numele echipei**. Două grafii = două intrări independente. Confirmat empiric: `"Zwolle"` vs `"PEC Zwolle"` au rulat lanțuri ELO paralele 2021→2025; `"Liverpool"` = 1960 vs `"Liverpool FC (ENG)"` = 1615 în același meci.

Cerințe pentru mecanismul nou (proiectate, neimplementate): reset explicit înainte de replay; replay **global** (ELO e cuplat temporal — un rebuild „doar pentru cele ~130 de identități" e matematic imposibil); ordine ELO → rating-uri → restul; snapshot înainte de reset; idempotență; ordinea reconciliere → reset → replay.

Contaminare ML: `home_elo`/`away_elo` (pre-meci) **sunt** în `ml_predictor.FEATURE_COLUMNS`, alături de rating-uri, formă și H2H. `home_elo_after`/`away_elo_after` sunt structural excluse din ML (gardă: `test_backfill_columns_naming.py`). Magnitudinea rămâne nedemonstrabilă fără rebuild.

## 8. Ce rămâne neautorizat

Nicio scriere în producție nu a fost efectuată. Necesită aprobare separată, în această ordine:

1. Rularea DRY-RUN pe date reale (`identity_reconciliation_dryrun.yml`, `workflow_dispatch`) — read-only, dar prima verificare end-to-end a registrului extins.
2. Reimplementarea căii EXECUTE în `match_identity_reconciliation_service` (azi: `NotImplementedError`).
3. Pilot pe subset izolat — propuse cele 6 grupuri `flashscore + tsdb` (semnal cel mai clar, Δ 30–39 coloane, blast radius minim).
4. Reconciliere completă (403 grupuri) + redenumire D2 (493 rânduri) + D3 (44 rânduri).
5. Snapshot + reset + replay global al stării derivate.
6. Corectarea factuală `fd_524100` + auditul celor 503 rânduri `fd_` din Champions League.
7. Închiderea structurală a indexului orb la schimbări de vocabular (§2).
