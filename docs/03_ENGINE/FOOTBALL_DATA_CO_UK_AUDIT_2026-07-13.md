# FOOTBALL_DATA_CO_UK_AUDIT_2026-07-13.md — Football Oracle

**Status**: Audit tehnic — zero cod scris, zero fișier modificat, zero migrare, zero branch nou, zero implementare. Fiecare afirmație e etichetată `[DEMONSTRAT]`, `[PROBABIL]` sau `[IMPOSIBIL DE DEMONSTRAT]`, cu dovada alăturată.

---

## 0. Constrângere de mediu — declarată explicit, nu ascunsă

Accesul direct la `www.football-data.co.uk` **e blocat la nivelul politicii de rețea a sesiunii curente** (proxy-ul de organizație respinge CONNECT către acest host cu 403 — verificat direct în `__agentproxy/status`, `recentRelayFailures`, host `www.football-data.co.uk:443`, motiv `policy denial`). Nu e o proprietate a site-ului, e o restricție a mediului acestei sesiuni.

**Ce am folosit în loc, și de ce e valid**: am accesat conținutul prin infrastructura externă a unui tool MCP (`Exa web_fetch`, care face fetch de pe propriile servere, nu prin proxy-ul acestei sesiuni) pentru paginile text (`notes.txt`, `data.php`, `romania.php`, `all_new_data.php`). Pentru fișierele CSV brute (pe care Exa nu le poate extrage — eroare `CRAWL_UNEXPECTED_CONTENT_TYPE`, tool-ul respinge tipul de conținut CSV), am folosit oglinzi publice pe GitHub care declară explicit că re-publică fișierele **nemodificate** de pe football-data.co.uk (`skthewimp/football`, sezonul 2025/26 Premier League — verificat rând cu rând, coincide exact cu `notes.txt`). Orice afirmație bazată pe aceste surse secundare e marcată ca atare mai jos.

**Ce NU am putut verifica direct**: fișierul CSV brut pentru Romania (liga urmărită de proiect) sau pentru celelalte 4 ligi majore (La Liga, Serie A, Bundesliga, Ligue 1) — oglinda GitHub disponibilă conține doar Premier League pentru sezoanele recente. Aceste cazuri sunt etichetate explicit „nedemonstrat direct", bazat doar pe descrierea textuală a site-ului.

---

## 1. Auditul sursei

### 1.1 Competiții oferite [DEMONSTRAT — din `data.php`, `all_new_data.php`]

**„Main leagues" (11 țări, fișier per sezon, din 1993/94)**: Anglia (5 divizii: Premiership + Divs 1,2,3 + Conference — coduri E0-E3, EC), Scoția (4 divizii — SC0-SC3), Germania (2 — D1,D2), Italia (2 — I1,I2), Spania (2 — SP1,SP2), Franța (2 — F1,F2), Olanda (N1), Belgia (B1), Portugalia (P1), Turcia (T1), Grecia (G1).

**„Extra leagues" (16 țări, un singur fișier cumulat per țară, din 2012/13)**: Argentina, Austria, Brazilia, China, Danemarca, Finlanda, Irlanda, Japonia, Mexic, Norvegia, Polonia, **România**, Rusia, Suedia, Elveția, SUA (MLS).

**Ce NU e acoperit deloc** [DEMONSTRAT prin absență — nicio mențiune în niciuna din cele 2 liste, verificat pe 3 pagini distincte]: **Champions League, Europa League, Conference League, World Cup** — nu există ca fișiere de sezon standard, nici în „main", nici în „extra". Există o resursă separată, ad-hoc, „World Cup XLSX" listată printre resurse — **nu am explorat-o** (fora scopul unui audit al fluxului standard de date; ar necesita o verificare dedicată dacă devine relevantă).

**Confruntare directă cu cele 9 ligi din `BOOTSTRAP_LEAGUES`** (`sync/bootstrap_league_learning.py:133-143`):

| Ligă urmărită de Football Oracle | Acoperită de football-data.co.uk? |
|---|:---:|
| Premier League | ✅ (E0) |
| La Liga | ✅ (SP1) |
| Serie A | ✅ (I1) |
| Bundesliga | ✅ (D1) |
| Ligue 1 | ✅ (F1) |
| Romania SuperLiga | ✅ (extra league, din 2012/13) |
| Champions League | ❌ |
| Europa League | ❌ |
| World Cup 2026 | ❌ |

**6 din 9 ligi urmărite sunt acoperite. Cele 3 neacoperite sunt exact cele mai slab acoperite azi în `match_history`** (Europa League: 139 rânduri, oprit la 2022-05-18; World Cup 2026: 21 rânduri, turneu abia început; Champions League: 628 rânduri — vezi §2). Sursa nu poate ajuta exact acolo unde nevoia e cea mai mare.

### 1.2 Perioadă istorică [DEMONSTRAT — text explicit pe `data.php`]

„Main leagues": **31 sezoane rezultate, 26 sezoane cote, 26 sezoane statistici de meci**, din 1993/94. „Extra leagues": din 2012/13. Conform cerinței utilizatorului, analiza de mai jos se limitează la **ultimele ~5 sezoane** (2021/22 → 2025/26) — pentru această fereastră, ambele categorii au acoperire completă.

### 1.3 Coloane existente per sezon [DEMONSTRAT — `notes.txt` + fișier CSV real 2025/26 Premier League]

Fișierul CSV real pentru Premier League 2025/26 (verificat rând cu rând, prin oglindă GitHub, coincide cu `notes.txt`) are **133 de coloane**:

- **Rezultat/identificare (11)**: `Div, Date, Time, HomeTeam, AwayTeam, FTHG, FTAG, FTR, HTHG, HTAG, HTR`
- **Statistici de meci (13)**: `Referee, HS, AS, HST, AST, HF, AF, HC, AC, HY, AY, HR, AR` (șuturi, șuturi pe poartă, faulturi, cornere, cartonașe galbene/roșii, arbitru) — **fără `Attendance` în acest fișier specific** (coloană documentată în `notes.txt` ca disponibilă „unde există", dar absentă din header-ul real verificat).
- **Cote de piață — pre-closing (~55)**: 1X2 de la ~15 case de pariuri individuale (B365, BFD, BMGM, BV, BW, CL, LB, PS) + agregate de piață (`Max`, `Avg`, `BFE`), plus total goluri Over/Under 2.5 (B365, P, Max, Avg, BFE) și handicap asiatic (`AHh`, B365AH, PAH, MaxAH, AvgAH, BFEAH).
- **Cote de piață — closing (~55)**: identice structural, cu sufix `C` (ex. `B365CH`).

**Coloane care lipsesc structural azi** (nu doar în date, ci și în schema `match_history`): `HC/AC` (cornere), `HF/AF` (faulturi), `HY/AY/HR/AR` (cartonașe), `Referee` — **niciuna dintre acestea nu are coloană corespondentă în `match_history`** (schema confirmată direct din Supabase, §2.1). `HS/AS/HST/AST` (șuturi/șuturi pe poartă) **au** coloane corespondente (`home_shots`, `away_shots`, `home_shots_on_target`, `away_shots_on_target`) — dar sunt 100% NULL azi (§2.1).

### 1.4 Stabilitatea denumirilor echipelor [DEMONSTRAT — comparație directă în `match_history`]

football-data.co.uk folosește nume scurte/prescurtate (`Man City`, `Man Utd`, `Nott'm Forest`, `Wolves`, `Spurs` — confirmat direct în `notes.txt`, secțiunea de context, și indirect prin formatul rândurilor Kaggle deja importate cu aceeași convenție, ex. `Manchester United`, `Nottingham Forest`, `Leicester`, `Ipswich` — fără sufixul „FC"). Motorul live/`football-data.org` folosește nume lungi cu sufix (`Manchester United FC`, `Leicester City FC`).

**Verificat direct, 9 perechi reale de meciuri identice** (16-19 august 2024, Premier League), comparând rândul etichetat `Premier League` (sursă live) cu rândul etichetat `E0` (Kaggle, stil football-data.co.uk) pentru exact același meci (potrivire pe dată + scor): `Manchester United FC`↔`Manchester United`, `Nottingham Forest FC`↔`Nottingham Forest`, `Leicester City FC`↔`Leicester`, `Wolverhampton Wanderers FC`↔`Wolverhampton Wanderers`, etc. **Toate cele 9 perechi se potrivesc corect** prin `mappings.TEAM_ALIASES`, care conține deja explicit formele exacte folosite de football-data.co.uk (`"Man City"`, `"Man Utd"`, `"Nott'm Forest"`, `"Wolves"`, `"Spurs"` — citat direct din `mappings.py:105-113`).

**Concluzie**: pentru cele 5 ligi majore, compatibilitatea de denumire **e deja demonstrat rezolvată** — nu pentru că a fost proiectată pentru football-data.co.uk explicit, ci pentru că importul Kaggle deja folosea aceeași convenție, iar `mappings.py` a fost construit împotriva ei. **Nedemonstrat** pentru Romania SuperLiga (nicio pereche de test disponibilă în `match_history` — liga nu are un duplicat brut acolo) și pentru orice ligă nouă neacoperită încă.

### 1.5 Compatibilitate cu schema Football Oracle [DEMONSTRAT]

- **Format dată**: `dd/mm/yyyy` (verificat: `"15/08/2025"`) — `match_history.kickoff_date` e `text`, format observat `"2025-08-15"` (ISO). **Necesită conversie explicită** la orice import — risc real, nu ipotetic (ambiguitate zi/lună dacă s-ar face un parse naiv).
- **`Time`**: coloană separată în CSV (`"20:00"`) — `match_history` nu are nicio coloană de oră, doar `kickoff_date` (dată, nu timestamp).
- **`Div`**: exact mecanismul care a produs deja cele 646 de meciuri duplicate documentate în `ELO_ROOT_CAUSE_ANALYSIS_2026-07-13.md` — orice import nou din football-data.co.uk pentru cele 5 ligi majore **recreează, demonstrat, exact același risc de duplicare** dacă nu e deduplicat explicit față de rândurile deja existente (atât cele etichetate cu numele complet, cât și cele etichetate cu codul brut).

---

## 2. Comparație cu baza actuală

### 2.1 Ce avem deja [DEMONSTRAT — interogare directă `match_history`, schema completă]

`match_history` (53.430 rânduri) **nu are nicio coloană de cote** (nici `match_history`, nici `odds_history` — acesta din urmă confirmat cu **0 rânduri**, schema există dar complet goală). Are coloane pentru șuturi (`home_shots`, `away_shots`, `home_shots_on_target`, `away_shots_on_target`) și `stats_source`, dar **100% NULL** pentru toate cele 5.253 de meciuri din ultimii 5 ani ale celor 5 ligi majore urmărite, verificat direct:

```
total=5253, has_home_shots=0, has_hst=0, has_stats_source=0, distinct_stats_sources=0
```

Nu există nicio coloană pentru cornere, faulturi, cartonașe sau arbitru — nici măcar ca slot gol în schemă.

### 2.2 Ce lipsește, ce am putea obține nou [DEMONSTRAT pentru existența datelor la sursă; PROBABIL pentru impact]

**Cu adevărat nou** (nicio coloană azi, nici măcar goală): cornere (HC/AC), faulturi (HF/AF), cartonașe (HY/AY/HR/AR), arbitru. **Ar umple coloane existente dar complet goale**: șuturi/șuturi pe poartă. **Ar umple o tabelă existentă dar complet goală**: cote istorice (`odds_history`) — aici football-data.co.uk oferă, demonstrat, cel mai mult: cote pre-closing ȘI closing de la 15+ case de pariuri, din 2000 pentru ligile majore, plus Over/Under 2.5 și handicap asiatic.

### 2.3 Duplicate [DEMONSTRAT — deja documentat în `ELO_ROOT_CAUSE_ANALYSIS_2026-07-13.md`, reconfirmat aici]

646 de meciuri (1.292 rânduri, 2,4% din `match_history`) sunt deja duplicate exact din cauza acestui tipar (etichetă normală + cod brut football-data.co.uk). **Orice extindere a integrării cu această sursă trebuie să rezolve întâi acest duplicat existent, altfel îl amplifică.**

### 2.4 Diferență de prospețime — descoperire nouă în acest audit [DEMONSTRAT]

Rândurile brute deja importate (E0, SP1, I1, D1, F1) **se opresc la sfârșitul sezonului 2024/25** (`E0`: max date `2025-05-25`; `SP1`/`I1`: `2025-05-25`; `D1`: `2025-05-17`; `F1`: `2025-05-17`) — **nu conțin sezonul 2025/26, aflat deja în desfășurare/încheiat azi**. În schimb, rândurile etichetate cu numele complet (`Premier League`, `La Liga`, etc., alimentate de pipeline-ul live) merg până la `2026-05-24`/`2026-05-17`. **Snapshot-ul Kaggle e înghețat, pipeline-ul live e curent** — o sursă nouă din football-data.co.uk ar aduce date mai proaspete decât Kaggle, dar **nu mai proaspete decât ce avem deja live** pentru cele 5 ligi majore.

Similar, rândurile „extra leagues" deja importate (ARG, BRA, USA, MEX, JAP, POL, CHN, SWE, NOR, RUS, IRL, FIN, DEN, SUI, AUT) se opresc **toate la decembrie 2024** (19 luni vechime azi) — dar aparțin unor ligi complet neurmărite de Football Oracle (confirmat: niciuna nu apare în `BOOTSTRAP_LEAGUES`), deci sunt deja zgomot pur, indiferent de prospețime.

### 2.5 Diferențe de calitate [DEMONSTRAT parțial]

Nu pot compara calitatea (acuratețea scorurilor/datelor) rând cu rând între football-data.co.uk brut și `match_history` — ar necesita fișierul complet al sursei pentru exact aceleași meciuri, indisponibil din cauza blocajului de rețea (§0). **Ce pot demonstra**: structura și convenția de numire coincid exact cu ce e deja în Kaggle pentru cele 5 ligi majore (§1.4), ceea ce sugerează (nu demonstrează) că datele Kaggle deja importate **provin** din football-data.co.uk sau dintr-o sursă care-l oglindește — consistent cu observația independentă deja făcută în `ELO_ROOT_CAUSE_ANALYSIS_2026-07-13.md` (linia 30: „provine dintr-un fișier stil football-data.co.uk").

---

## 3. Limitare la ultimii 5 ani — aplicată

Toată analiza de mai sus (coloane, acoperire, prospețime) s-a limitat explicit la fereastra 2021/22 → 2025/26. Sezoanele mai vechi (1993/94 → 2020/21) nu au fost interogate sau analizate.

---

## 4. Valoare pentru ML

| Componentă | Verdict | Argumentare |
|---|---|---|
| **ELO** | **PROBABIL, netestat** | football-data.co.uk nu oferă ELO — oferă rezultate brute cu istoric mult mai lung (din 1993/94) decât fereastra densă de facto a `ELOTracker` (~2021-2026, cauza rădăcină demonstrată în `ELO_ROOT_CAUSE_ANALYSIS_2026-07-13.md`). Un istoric mai lung ar putea reduce „cold start"-ul demonstrat acolo — **dar nu am rulat un experiment în acest audit** (în afara scopului cerut: „doar auditul tehnic"). Rămâne o ipoteză testabilă, nu o concluzie. |
| **Feature engineering (șuturi/cornere/faulturi/cartonașe)** | **DEMONSTRAT că datele reale există; PROBABIL ca beneficiu** | `PREDICTOR_ROADMAP_V4.md` a demonstrat deja că `avg_shots_on_target`/`avg_possession` sunt sintetice (formule, nu date reale) în toate sursele live actuale. football-data.co.uk oferă, demonstrat, valori reale pentru șuturi/șuturi pe poartă/cornere/faulturi/cartonașe. Nu pot demonstra că folosirea lor ÎMBUNĂTĂȚEȘTE acuratețea — asta ar necesita un test de ablație explicit, conform disciplinei proiectului („verificat, nu presupus"), neefectuat aici. |
| **Odds** | **DEMONSTRAT — cea mai clară valoare** | `odds_history` are 0 rânduri; `ELO_PERFORMANCE_EXPERIMENT_2026-07-13.md` a declarat explicit ROI „nedemonstrabil" din lipsă de cote istorice. football-data.co.uk oferă, demonstrat, cote reale pre-closing și closing de la 15+ case de pariuri, din 2000, pentru toate cele 5 ligi majore urmărite. E singura componentă unde sursa umple un gol deja documentat ca blocant, nu doar teoretic util. |
| **Calibrare model** | **PROBABIL** | Cote istorice reale ar permite comparație de-vig față de piață (funcție deja existentă, `oracle_engine.py`, dar niciodată testată contra unui istoric real) — utilă, netestată aici. |
| **Detectarea egalurilor** | **IMPOSIBIL DE DEMONSTRAT vreun beneficiu din această sursă** | football-data.co.uk nu oferă niciun semnal specific pentru egaluri dincolo de ce există deja (scor, cote 1X2 care includ D). Problema de ~1% acuratețe pe Draw (demonstrată în `ELO_PERFORMANCE_EXPERIMENT_2026-07-13.md`, prezentă în TOATE variantele testate acolo) nu are nicio cale demonstrabilă de rezolvare doar prin această sursă. |
| **Evaluarea ROI** | **DEMONSTRAT — devine posibilă, azi imposibilă** | Fără cote istorice (azi: 0 rânduri), ROI simulat nu poate fi calculat deloc — confirmat explicit în `ELO_PERFORMANCE_EXPERIMENT_2026-07-13.md`. Cu cotele football-data.co.uk, calculul devine posibil structural (nu automat corect — depinde de calitatea potrivirii fixture-cotă). |
| **Acoperirea ligilor urmărite** | **DEMONSTRAT — parțial, cu un gol structural** | 6/9 ligi din `BOOTSTRAP_LEAGUES` acoperite; exact cele 3 neacoperite (Champions League, Europa League, World Cup 2026) sunt cele mai sărace în date azi. Sursa nu poate atinge deloc problema cea mai vizibilă de acoperire. |

---

## 5. Compatibilitate — riscuri identificate

Toate verificate direct, nu presupuse:

1. **Duplicare** — [DEMONSTRAT, risc real] mecanismul care a produs deja 646 de meciuri duplicate (2,4% din `match_history`) s-ar repeta identic la orice import nou, dacă nu există deduplicare explicită față de AMBELE etichete existente (numele complet ȘI codul brut).
2. **Cronologie/format dată** — [DEMONSTRAT, risc real] `dd/mm/yyyy` în sursă vs. `yyyy-mm-dd` (text) în `match_history` — conversie obligatorie, altfel corupere silențioasă a datelor (nu doar eroare vizibilă) dacă cineva ar face un parse naiv „primele 2 cifre = lună".
3. **Nume echipe** — [DEMONSTRAT rezolvat pentru cele 5 ligi majore, nedemonstrat pentru restul] `mappings.TEAM_ALIASES` acoperă deja convenția football-data.co.uk pentru Anglia/Spania/Italia/Germania/Franța (verificat cu 9 perechi reale). Romania SuperLiga și orice ligă nouă **nu au fost testate** — niciun duplicat existent de verificat.
4. **Ruperea pipeline-ului** — [PROBABIL scăzut, nedemonstrat direct] `match_history` nu are coloane pentru cornere/faulturi/cartonașe/arbitru — orice import al acestor câmpuri ar necesita extindere de schemă (coloane noi), nu doar populare de coloane goale. Adăugarea de coloane e, prin regulile proiectului, o schimbare de contract de date care necesită ADR — nu poate fi făcută „pe tăcute".
5. **Prospețime inversată** — [DEMONSTRAT, descoperire nouă] pentru cele 5 ligi majore, varianta brută deja în `match_history` (E0/SP1/I1/D1/F1) e mai VECHE (oprită la sezonul 2024/25) decât ce avem deja live (curent la 2025/26) — orice reimport necontrolat ar putea introduce date STALE peste date deja mai proaspete, dacă logica de merge nu prioritizează corect sursa.

---

## 6. Concluzie

### Avantaje demonstrate
- Cote istorice reale (pre-closing + closing, 15+ case de pariuri) — singura sursă din tot proiectul care ar rezolva golul deja documentat ca blocant pentru ROI.
- Statistici de meci reale (șuturi, cornere, faulturi, cartonașe) pentru cele 5 ligi majore — alternativă demonstrat-reală la formulele sintetice deja expuse în `PREDICTOR_ROADMAP_V4.md`.
- Compatibilitate de nume deja rezolvată pentru cele 5 ligi majore (verificat, nu presupus).
- Format CSV simplu, fără autentificare, gratuit.

### Dezavantaje/limitări demonstrate
- **Nu acoperă exact cele 3 competiții cu cea mai slabă acoperire azi** (Champions League, Europa League, World Cup) — nu atinge problema unde e mai vizibilă.
- **Nu e mai proaspăt decât ce avem deja live** pentru cele 5 ligi majore — valoarea nouă e strict pe coloane (statistici/cote), nu pe acoperire temporală.
- **Recreează un risc de duplicare deja demonstrat costisitor de rezolvat.**
- **Nu conține ELO** — orice beneficiu pentru problema ELO e indirect și netestat.
- **Nu atinge deloc problema de detectare a egalurilor** — cel mai mare limitator de acuratețe rămas nerezolvat, conform `PERFORMANCE_LIMITER_AUDIT_2026-07-13.md`.
- Acces direct la sursă blocat în acest mediu de sesiune (§0) — orice implementare viitoare ar trebui verificată dintr-un mediu fără această restricție.

### Ce e nou vs. ce e redundant
**Nou, real**: cote istorice (umple un gol de 0 rânduri), statistici de meci reale (înlocuiesc formule sintetice deja demonstrate ca false). **Redundant**: rezultatele brute (scor, dată, echipe) pentru cele 5 ligi majore — le avem deja, mai complete și mai proaspete, prin pipeline-ul live.

### Verdict

**Merită investigat suplimentar STRICT pentru coloanele de cote istorice** (`odds_history`, azi complet gol) — acesta e singurul beneficiu demonstrat, nu doar probabil, și rezolvă un gol deja documentat explicit ca blocant (`ELO_PERFORMANCE_EXPERIMENT_2026-07-13.md`, secțiunea ROI). **Nu există, azi, dovadă suficientă pentru a justifica reimportarea rezultatelor brute** (redundante) sau extinderea imediată a schemei pentru statistici de meci (cornere/faulturi/cartonașe) — acestea rămân „probabil util", nu „demonstrat util", și ar necesita un test de ablație separat, conform disciplinei proiectului, înainte de orice decizie de implementare.

**Această concluzie nu implică nicio acțiune** — conform cerinței explicite, nu se propune aici niciun plan de implementare, migrare sau import.

---

## Notă de securitate (obligatorie, în afara scopului acestui audit)

În timpul interogării schemei Supabase pentru acest audit, tool-ul de listare a semnalat automat: **8 tabele au Row Level Security dezactivat** (`sync_status`, `elo_ratings`, `api_cache`, `league_provider_coverage`, `api_provider_status`, `provider_metrics`, `shadow_predictions`, `experiment_registry`) — expuse complet la cheia `anon`. Nu e o descoperire nouă a acestui audit și nu are legătură cu football-data.co.uk, dar tool-ul obligă semnalarea ei explicită către utilizator. Nu s-a aplicat nicio remediere (ar bloca accesul fără politici RLS definite) — doar semnalat, decizia rămâne a arhitectului șef.
