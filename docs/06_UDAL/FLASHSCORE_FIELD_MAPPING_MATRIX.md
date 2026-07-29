# Flashscore Field Mapping Matrix — Flashscore field → Supabase table → Supabase column

**Versiune**: 2 (revizuire completă, TASK APROBAT — corecție oversight-uri + reclasificare pe 4 categorii stricte, fără categorie generică „nu există sursă curată").

**Scop**: matrice completă, verificată direct în cod (`providers/flashscore/normalizer.py`) și în fixture-ul real (`docs/06_UDAL/poc_evidence/flashscore_full_tabs_poc/` + `flashscore_10matches/`), pentru fiecare informație documentată în `UDAL_FLASHSCORE_FULL_TABS_POC_REPORT.md`. Fiecare câmp NEIMPLEMENTAT e clasificat în una din **exact 4 categorii, fără altele**:

| Categorie | Înseamnă |
|---|---|
| **1. Parser limitation** | Mecanismul de extracție există și e gata (identic cu al câmpurilor deja confirmate din aceeași familie) — dar niciun fixture real capturat nu conține o apariție a acestei informații, deci selectorul exact nu poate fi confirmat pe date reale. Limitare a EȘANTIONULUI disponibil azi, nu a codului. |
| **2. Schema gap** | Extracția e posibilă, dar nu există coloană/tabelă în Supabase pentru ea |
| **3. Cross-provider dependency** | Scrierea corectă necesită o identitate/reconciliere cu alt provider (fixture_id, taxonomie de ligă) — nu o simplă extracție |
| **4. Decizie arhitecturală explicită (ADR)** | S-a decis deliberat, printr-un ADR, să nu se scrie (nu lipsă tehnică) |

---

## 0. Ce s-a corectat în această revizuire (Parser oversight închise)

Aprobat explicit („Corectează imediat toate 'pure oversight gaps'"), implementat, testat, aplicat live:

1. **Scor final** (`.detailScore__wrapper`) → `match_history.actual_home_goals`/`actual_away_goals` — coloane deja existente (migrația 008).
2. **Scor la pauză** (pereche etichetă/valoare „1st Half") → `match_history.home_ht_goals`/`away_ht_goals` — coloane deja existente (migrația 008).
3. **Timeline complet de evenimente** (`.smv__participantRow`, tab Summary) → `match_events` — **corectează direct o afirmație falsă** din docstring-ul vechi al `normalizer.py` („goluri/cartonașe NU au minut vizibil în structura verificată"). Migrația 039 a extins vocabularul `event_type` la 9 valori (`goal`, `own_goal`, `penalty_goal`, `penalty_missed`, `yellow_card`, `red_card`, `second_yellow_card`, `substitution`, `var`) + coloană `detail` (motiv cartonaș / text decizie VAR) + `player_name` cu sentinel `''` pentru evenimente fără jucător (VAR). **Verificat pe 21 evenimente reale**: 5 goluri, 1 penalty, 3 galbene, 1 roșu, 10 schimbări (intrare+ieșire), 1 VAR — consistență internă confirmată (numărul de goluri din timeline == scorul final extras separat, 5-1).

Toate 3 sunt scrise acum prin `persist_match_foundation_data()`, verificate idempotent (1/2/10 rulări, 0 duplicate).

---

## 1. Matricea completă

### Tab „Sumar" (summary)

| Câmp Flashscore | Tabelă Supabase | Coloană | Status |
|---|---|---|---|
| Referee | `match_history` | `referee` | ✅ MAPAT |
| Venue | `match_history` | `stadium` | ✅ MAPAT |
| Capacity | `match_history` | `capacity` | ✅ MAPAT |
| Attendance | `match_history` | `attendance` | ✅ MAPAT |
| Nume echipe | `match_history` | `home_team`/`away_team` | ✅ MAPAT |
| Data/ora meciului | `match_history` | `kickoff_date` | ✅ MAPAT |
| **Scor final** | `match_history` | `actual_home_goals`/`actual_away_goals` | ✅ **MAPAT (corectat acum)** |
| **Scor la pauză** | `match_history` | `home_ht_goals`/`away_ht_goals` | ✅ **MAPAT (corectat acum)** |
| **Gol** (event) | `match_events` | `event_type='goal'` | ✅ **MAPAT (corectat acum)** |
| **Penalty gol** | `match_events` | `event_type='penalty_goal'` | ✅ **MAPAT (corectat acum)** |
| **Cartonaș galben** | `match_events` | `event_type='yellow_card'`, `detail`=motiv | ✅ **MAPAT (corectat acum)** |
| **Cartonaș roșu** | `match_events` | `event_type='red_card'`, `detail`=motiv | ✅ **MAPAT (corectat acum)** |
| **Schimbare** (intrare+ieșire) | `match_events` | `event_type='substitution'`, `player_name`=intră, `related_player_name`=iese | ✅ **MAPAT (corectat acum)** |
| **VAR** | `match_events` | `event_type='var'`, `detail`=decizie | ✅ **MAPAT (corectat acum)** |
| **Autogol** | `match_events` | `event_type='own_goal'` (schema pregătită) | ❌ **Categoria 1 (Parser limitation)**: mecanismul de clasificare (dispatch pe `data-testid`/clasă SVG) e complet și identic cu cel al celorlalte 6 tipuri deja confirmate — DAR niciun autogol nu a apărut în cele 11 fixture-uri capturate până acum, deci selectorul exact (testid/clasă SVG) nu a putut fi verificat direct. Cod pregătit să-l accepte (`event_type` permis în schemă) — activare imediată la primul fixture real cu un autogol, nu ghicit acum. |
| **Penalty ratat** | `match_events` | `event_type='penalty_missed'` (schema pregătită) | ❌ **Categoria 1 (Parser limitation), același caz** — nicio apariție reală capturată încă. |
| **Al doilea galben** | `match_events` | `event_type='second_yellow_card'` (schema pregătită) | ❌ **Categoria 1 (Parser limitation), același caz** — nicio apariție reală capturată încă. |
| Scor doar a doua repriză (nu cumulativ) | — | — | ❌ **Categoria 2 (Schema gap)** — element real, extractibil (aceeași pereche etichetă/valoare ca scorul la pauză), dar nicio coloană dedicată în `match_history` pentru „scor doar repriza 2" (diferit de scorul final). Valoare marginală — derivabil din final − pauză. |
| Breadcrumb țară („Romania") | — | — | ❌ **Categoria 2 (Schema gap)** — nicio coloană dedicată; redundant cu liga. |
| Breadcrumb competiție („Superliga") | `match_history` | `league` (coloană există) | ❌ **Categoria 3 (Cross-provider dependency)** — coloana EXISTĂ, dar valoarea brută Flashscore trebuie reconciliată cu taxonomia canonică de ligi (`mappings.py`, ADR-001 „sursă canonică unică pentru ligi") înainte de scriere — scriere directă ar putea crea o valoare de ligă duplicată/necanonică, exact problema pe care ADR-001 o previne. |
| Breadcrumb rundă („Round 2") | — | — | ❌ **Categoria 2 (Schema gap)** — nicio coloană `round`/`matchday` în `match_history` azi. |

### Tab „Statistici" (stats)

| Câmp Flashscore | Tabelă Supabase | Coloană | Status |
|---|---|---|---|
| 10 categorii de bază (xG, possession, shots, shots_on_target, corners, fouls, yellow/red cards, offsides, goalkeeper saves) | `match_history` | coloane dedicate | ✅ MAPAT (toate 10) |
| 26 categorii extinse (xGOT, Big chances, Passes, etc.) | `match_statistics_extended` (EAV) | `stat_key`/`stat_label`/valori | ✅ MAPAT (toate 26) |

### Tab „Formații" (lineups)

| Câmp Flashscore | Tabelă Supabase | Coloană | Status |
|---|---|---|---|
| Nume jucător, număr tricou, echipă | `player_match_stats` | `player_name`/`shirt_number`/`team` | ✅ MAPAT |
| Marcaje de rol „(G)"/„(C)" | — | — | ❌ **Categoria 2 (Schema gap)** — niciun câmp `is_captain`/flag dedicat; poziția „Goalkeeper" e deja acoperită separat prin tab-ul Player Stats (`position`). |

### Tab „Statistici jucători" (player_stats)

| Câmp Flashscore | Tabelă Supabase | Coloană | Status |
|---|---|---|---|
| Rating, poziție + 7 statistici avansate | `player_match_stats` / `player_match_stats_extended` | `rating`/`position`/EAV | ✅ MAPAT (toate 9) |

### Tab „Cote" (odds)

| Câmp Flashscore | Tabelă Supabase | Coloană | Status |
|---|---|---|---|
| Bookmaker + cotă curentă (home/draw/away) — strat RAW | `flashscore_raw_extraction` | `raw_extracted` (jsonb) | ✅ MAPAT (RAW) |
| Aceleași date — scriere CANONICĂ | `odds_fallback_flashscore` | `fixture_id`/`bookmaker`/`home`/`draw`/`away` | ❌ **Categoria 3 (Cross-provider dependency)** — tabela cere `fixture_id` IDENTIC cu cel folosit de The Odds API; Flashscore nu-l oferă. Scrierea cu o cheie inventată ar rupe silențios regula de fallback a Predictorului (ADR-043). Rezoluția identității cross-provider rămâne task separat, documentat deja de ADR-043. |
| Mișcare cotă (opening → curent, atribut `title`) | — | — | ❌ **Categoria 4 (Decizie ADR)** — ADR-043: „cotele Flashscore sunt fallback, nu sursa de CLV/market-drift, doar valoarea cea mai recentă contează". Element real, extractibil — neextras prin decizie, nu gol tehnic. |

### Tab „H2H"

| Câmp Flashscore | Tabelă Supabase | Coloană | Status |
|---|---|---|---|
| Categorie, dată, cod competiție, echipe, scor, ordine | `flashscore_match_context` | toate coloanele | ✅ MAPAT (toate 6) |

### Tab „Clasamente" (standings)

| Câmp Flashscore | Tabelă Supabase | Coloană | Status |
|---|---|---|---|
| Rang, echipă, J/C/E/P, goluri, diferență, puncte | `flashscore_standings_snapshot` | toate coloanele | ✅ MAPAT (toate 10) |
| Insigne de formă recentă (48 pe fixture, W/D/L per echipă) | — | — | ❌ **Categoria 2 (Schema gap)** — element real, extractibil (clasă CSS determinist per rezultat), dar `flashscore_standings_snapshot` nu are nicio coloană pentru el (ex. `recent_form JSONB`). |

---

## 2. Concluzie finală

**Convenție de numărare, explicită** (ca să poată fi verificată direct, rând cu rând): fiecare RÂND din tabelele secțiunii 1 = un câmp/grup de informație distinct, exact așa cum e enumerat acolo. Categoriile de statistici (36) și coloanele de clasament (10) sunt numărate ca UN rând fiecare (un grup coerent, extras/scris printr-un singur mecanism), nu desfășurate individual. Numărătoarea a fost recalculată direct din tabelele secțiunii 1, nu estimată.

| | Număr |
|---|---|
| **Total câmpuri identificate** (toate cele 7 tab-uri, confirmate în POC) | **32** |
| **Total câmpuri implementate** (extrase + scrise în Supabase) | **21** |
| **Total câmpuri rămase** (neimplementate) | **11** |

### Cele 11 câmpuri rămase — motivul fiecăruia, clasificat exact în una din cele 4 categorii (fără altele)

| # | Câmp | Categorie | Motiv exact |
|---|---|---|---|
| 1 | Autogol (`own_goal`) | **Parser limitation** | Mecanism de clasificare identic cu celelalte 6 tipuri confirmate, dar nicio apariție reală în 11 fixture-uri capturate — selector neconfirmat pe date reale |
| 2 | Penalty ratat (`penalty_missed`) | **Parser limitation** | Idem #1 |
| 3 | Al doilea galben (`second_yellow_card`) | **Parser limitation** | Idem #1 |
| 4 | Scor doar repriza a doua | **Schema gap** | Nicio coloană dedicată; derivabil din final−pauză, valoare marginală |
| 5 | Breadcrumb țară | **Schema gap** | Nicio coloană dedicată; redundant cu liga |
| 6 | Breadcrumb rundă | **Schema gap** | Nicio coloană `round`/`matchday` |
| 7 | Marcaje rol jucător (G/C) | **Schema gap** | Niciun flag dedicat; „Goalkeeper" deja acoperit via `position` |
| 8 | Insigne formă recentă standings | **Schema gap** | Nicio coloană `recent_form` |
| 9 | Breadcrumb competiție (liga canonică) | **Cross-provider dependency** | Coloana `league` există, dar necesită reconciliere cu taxonomia canonică (`mappings.py`, ADR-001) înainte de scriere |
| 10 | Cotă canonică (`odds_fallback_flashscore`) | **Cross-provider dependency** | Necesită `fixture_id` identic cu The Odds API — nedisponibil în Flashscore |
| 11 | Mișcare cotă (opening/curent) | **ADR decision** | ADR-043 — decizie explicită de scop, nu gol tehnic |

**Distribuție**: 3 Parser limitation · 5 Schema gap · 2 Cross-provider dependency · 1 ADR decision. Nicio altă categorie folosită.

### Concluzia propriu-zisă

**Toate cele 21 de câmpuri robuste, disponibile, confirmate pe date reale sunt implementate în Supabase azi.** Niciunul din cele 11 rămase nu e „disponibil și ignorat" — fiecare are exact unul din cele 4 motive de mai sus, verificabil direct în cod sau în schemă:

- **3 sunt limitări reale ale eșantionului** (Parser limitation) — mecanismul există, așteaptă un fixture real cu acel eveniment pentru confirmare, nu se ghicește selectorul.
- **5 sunt goluri de schemă** (Schema gap) — decizie de extindere a schemei, rămasă la latitudinea proprietarului produsului (nu implementate unilateral, nu cerute explicit în acest task).
- **2 sunt dependențe cross-provider** (Cross-provider dependency) — necesită rezoluție de identitate cu alt provider, nu o simplă extracție.
- **1 e o decizie ADR explicită** (ADR-043) — scop, nu gol tehnic.

Foundation Data Layer extrage azi tot ce e disponibil robust în Flashscore, confirmat pe date reale — vezi și `docs/00_GOVERNANCE/ADR-044-flashscore-foundation-data-layer.md`, Addendum 2.
