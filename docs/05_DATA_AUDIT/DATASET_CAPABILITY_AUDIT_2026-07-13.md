# DATASET_CAPABILITY_AUDIT_2026-07-13.md — Football Oracle

**Status**: Audit tehnic pur — zero cod scris, zero migrare, zero ADR, zero implementare. Fiecare cifră din acest document a fost obținută prin analiză directă (pandas) a fișierului sursă (`Matches.csv`, mirror-ul `xgabora/Club-Football-Match-Data-2000-2025`, deja descărcat și folosit de proiect pentru backfill-ul de cote) și prin interogare SQL directă a `match_history` din Supabase (proiect `Prediction`). **Nu s-a folosit documentația sursei** — orice coloană a cărei semnificație nu a putut fi determinată empiric e marcată explicit „necunoscut", nu presupusă.

**Metodologie**: `pandas.read_csv` pe cele 230.557 rânduri ale fișierului sursă, filtrat pe `Division` pentru fiecare din cele 7 competiții cerute + toate celelalte 30 de coduri prezente. Completitudinea = `count(non-null) / count(total)` per coloană per ligă. Interogări SQL directe (`information_schema.columns`, `count()`) pe `match_history` pentru starea reală de producție.

---

## 0. Ce este de fapt acest fișier sursă

Fișierul (`Matches.csv`) **nu e identic cu fișierele brute per-sezon de pe football-data.co.uk** (care au ~133 coloane, inclusiv `Referee`, `Attendance`, cote de la 15+ case individuale, closing odds separate — vezi `FOOTBALL_DATA_CO_UK_AUDIT_2026-07-13.md` pentru acel audit anterior, bazat pe o oglindă diferită). Acesta e un mirror **curat/derivat**, cu doar **48 de coloane**, care include câteva câmpuri suplimentare pre-calculate (Elo, formă) dar **nu conține deloc `Referee` sau `Attendance`** — confirmat prin absența lor din header, nu presupus.

**Nu se inventează** de ce sursele diferă — doar se raportează ce există, efectiv, în fișierul pe care proiectul îl folosește azi.

---

## 1. Inventar complet de coloane (48 total, grupate empiric)

| Grup | Coloane |
|---|---|
| **Identificare/metadata** | `Division`, `MatchDate`, `MatchTime`, `HomeTeam`, `AwayTeam` |
| **Rating pre-calculat** | `HomeElo`, `AwayElo` |
| **Formă pre-calculată** | `Form3Home`, `Form5Home`, `Form3Away`, `Form5Away` |
| **Rezultat** | `FTHome`, `FTAway`, `FTResult`, `HTHome`, `HTAway`, `HTResult` |
| **Statistici de meci** | `HomeShots`, `AwayShots`, `HomeTarget`, `AwayTarget`, `HomeFouls`, `AwayFouls`, `HomeCorners`, `AwayCorners`, `HomeYellow`, `AwayYellow`, `HomeRed`, `AwayRed` |
| **Cote 1X2** | `OddHome`, `OddDraw`, `OddAway`, `MaxHome`, `MaxDraw`, `MaxAway` |
| **Cote Over/Under 2.5** | `Over25`, `Under25`, `MaxOver25`, `MaxUnder25` |
| **Cote Handicap Asiatic** | `HandiSize`, `HandiHome`, `HandiAway` |
| **Necunoscut (nedocumentat, semnificație nedeterminată empiric)** | `C_LTH`, `C_LTA`, `C_VHD`, `C_VAD`, `C_HTB`, `C_PHB` |

**Absente din acest fișier, deloc**: `Referee`, `Attendance` — nu există nicio coloană cu aceste informații în acest mirror specific. Nu se presupune existența lor.

**Nota despre grupul „Necunoscut"**: cele 6 coloane `C_*` conțin valori numerice în intervalul [0,1], populate consistent doar începând cu un anumit punct în timp per ligă (vezi §3). Fără documentația sursei (interzisă explicit de sarcină) nu pot determina empiric semnificația exactă — ar putea fi probabilități implicite de-vig, un scor de piață, sau altceva. **Le raportez ca atare, neclasificate, nu ghicesc.**

---

## 2. Acoperire temporală per competiție

| Competiție | Cod | Prima dată | Ultima dată | Prim sezon | Ultim sezon | Nr. sezoane | Nr. meciuri |
|---|---|---|---|---|---|---|---|
| Premier League | E0 | 2000-08-19 | 2025-05-25 | 2000/2001 | 2024/2025 | 25 | **9.410** |
| Championship | E1 | 2000-08-12 | 2025-05-03 | 2000/2001 | 2024/2025 | 25 | **13.606** |
| La Liga | SP1 | 2000-09-09 | 2025-05-25 | 2000/2001 | 2024/2025 | 24 | **9.008** |
| Serie A | I1 | 2000-09-30 | 2025-05-25 | 2000/2001 | 2024/2025 | 25 | **9.012** |
| Bundesliga | D1 | 2000-08-11 | 2025-05-17 | 2000/2001 | 2024/2025 | 25 | **7.522** |
| Ligue 1 | F1 | 2000-07-28 | 2025-05-17 | 2000/2001 | 2024/2025 | 25 | **8.756** |
| Romania SuperLiga | ROM | 2012-01-09 | 2024-12-08 | 2011/2012 | 2024/2025 | 14 | **3.640** |

**Observație directă, nu presupusă**: fișierul se oprește la sfârșitul sezonului 2024/25 pentru toate cele 7 competiții (deja documentat în auditul anterior de cote) — nu conține sezonul 2025/26, aflat în desfășurare azi (2026-07-13).

### Alte competiții prezente în dataset (30 coduri, listate separat)

| Cod | Nr. meciuri | Prima dată | Ultima dată | Sezoane |
|---|---|---|---|---|
| B1 (Belgia) | 6.559 | 2000-08-12 | 2025-05-25 | 25 |
| D2 (Germania div. 2) | 7.161 | 2000-08-11 | 2025-05-18 | 25 |
| E2 (Anglia div. 3) | 13.220 | 2000-08-12 | 2025-05-03 | 25 |
| E3 (Anglia div. 4) | 12.777 | 2001-04-16 | 2025-05-03 | 25 |
| EC (Anglia Conference) | 7.134 | 2011-08-12 | 2024-10-23 | 14 |
| F2 (Franța div. 2) | 8.677 | 2000-07-28 | 2025-05-10 | 25 |
| G1 (Grecia) | 4.128 | 2005-08-27 | 2025-05-18 | 17 |
| I2 (Italia div. 2) | 9.921 | 2000-09-01 | 2025-05-13 | 25 |
| N1 (Olanda) | 7.288 | 2000-08-18 | 2025-05-18 | 25 |
| P1 (Portugalia) | 6.626 | 2000-08-18 | 2025-05-17 | 24 |
| SC0-SC3 (Scoția, 4 divizii) | 5.124+4.094+4.092+4.010 | 2001-07-28 | 2025-05-18 | 24 |
| SP2 (Spania div. 2) | 10.497 | 2000-09-02 | 2025-06-01 | 24 |
| T1 (Turcia) | 7.458 | 2000-08-11 | 2025-06-01 | 24 |
| ARG, AUT, BRA, CHN, DEN, FIN, IRL, JAP, MEX, NOR, POL, RUS, SUI, SWE, USA (ligi „extra") | 2.273–5.330 fiecare | 2011/2012 sau 2013/2014 | 2024-12 | 12-14 |

Niciuna dintre acestea nu e în cele 9 din `BOOTSTRAP_LEAGUES`, cu excepția faptului că E2/E3/EC/D2/F2/I2/SP2 sunt diviziile inferioare ale țărilor deja urmărite (nu urmărite azi ca ligi separate de proiect).

---

## 3. Completitudine pe coloane, per competiție

### Premier League (E0) — 9.410 meciuri
| Coloană | Completitudine |
|---|---|
| Elo, Formă, Rezultat FT/HT | 99.99–100% |
| Shots/Target/Fouls/Corners/Cartonașe | **100%** |
| Cote 1X2 (Odd*) | 99.12% |
| Cote Max/O-U 2.5 | 80.77% |
| Handicap | 87.67–87.77% |
| C_* (necunoscut) | 100% |

### Championship (E1) — 13.606 meciuri
| Coloană | Completitudine |
|---|---|
| Elo | 99.00–99.04% |
| Shots/Target/Fouls/Corners/Cartonașe | **99.99%** |
| Cote 1X2 | 98.77% |
| Cote Max/O-U 2.5 | 81.12–81.13% |
| Handicap | 87.87–87.95% |
| C_* | 99.99% |

### La Liga (SP1) — 9.008 meciuri
| Coloană | Completitudine |
|---|---|
| Elo, Formă, Rezultat FT/HT | 100% |
| Shots/Target/Fouls/Corners/Cartonașe | **80.15%** |
| Cote 1X2 | 99.00% |
| Cote Max/O-U 2.5 | 80.14–80.15% |
| Handicap | 86.89–87.01% |
| C_* | 80.14% |

### Serie A (I1) — 9.012 meciuri
| Coloană | Completitudine |
|---|---|
| Elo, Formă, Rezultat FT | 100% |
| Shots/Target | 84.17% |
| Fouls/Corners/Cartonașe | 84.21–84.32% |
| Cote 1X2 | 98.68% |
| Cote Max/O-U 2.5 | 84.29–84.31% |
| Handicap | 89.16% |
| C_* | 84.15% |

### Bundesliga (D1) — 7.522 meciuri
| Coloană | Completitudine |
|---|---|
| Elo, Formă, Rezultat FT/HT | 100% |
| Shots/Fouls/Corners/Cartonașe | **96.14%** |
| Target (șuturi pe poartă) | **85.43%** ← gap distinct față de Shots |
| Cote 1X2 | 99.00% |
| Cote Max/O-U 2.5 | 81.36% |
| Handicap | 87.65–87.66% |
| C_* | 85.40% |

### Ligue 1 (F1) — 8.756 meciuri
| Coloană | Completitudine |
|---|---|
| Elo | 99.78% |
| Shots/Target/Cartonașe | 83.92–83.94% |
| **Fouls** | **75.23%** ← cel mai slab din grup |
| **Corners** | **79.59%** |
| Cote 1X2 | 99.01% |
| Cote Max/O-U 2.5 | 83.94% |
| Handicap | 90.58–90.60% |
| C_* | 75.23% |

### Romania SuperLiga (ROM) — 3.640 meciuri
| Coloană | Completitudine |
|---|---|
| Elo | **22.23–22.39%** ← foarte slab |
| Formă, Rezultat FT | 100% |
| **HT (scor la pauză)** | **0%** |
| **Shots/Target/Fouls/Corners/Cartonașe** | **0%** — zero, deloc |
| Cote 1X2, Max | **100%** |
| **Over/Under 2.5, Handicap, C_*** | **0%** — zero, deloc |

---

## 4. Comparație directă între competiții

| Statistică | PL | Championship | La Liga | Serie A | Bundesliga | Ligue 1 | Romania |
|---|---|---|---|---|---|---|---|
| Shots | 100% | 99.99% | 80.15% | 84.17% | 96.14% | 83.92% | **0%** |
| Shots on Target | 100% | 99.99% | 80.15% | 84.17% | 85.43% | 83.92% | **0%** |
| Corners | 100% | 99.99% | 80.15% | 84.21% | 96.14% | 79.59% | **0%** |
| Fouls | 100% | 99.99% | 80.15% | 84.21% | 96.14% | 75.23% | **0%** |
| Cartonașe galbene/roșii | 100% | 99.99% | 80.15% | 84.31% | 96.14% | 83.93% | **0%** |
| Scor la pauză (HT) | 100% | 99.99% | 100% | 99.98% | 100% | 99.99% | **0%** |
| Elo (din sursă) | 99.99% | 99.02% | 100% | 100% | 100% | 99.78% | **22.3%** |
| Formă precalculată | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| Cote 1X2 | 99.12% | 98.77% | 99.00% | 98.68% | 99.00% | 99.01% | 100% |
| Over/Under 2.5 | 80.77% | 81.12% | 80.14% | 84.29% | 81.36% | 83.94% | **0%** |
| Handicap asiatic | 87.7% | 87.9% | 86.9% | 89.16% | 87.66% | 90.6% | **0%** |

**Diferența cea mai clară**: Romania SuperLiga e complet lipsită de orice statistică de meci în acest mirror (0% pe 5 din 6 categorii de statistici + Over/Under + Handicap), are doar rezultat, formă precalculată și cote 1X2/Max — restul e gol structural, nu incomplet. Toate celelalte 6 competiții au acoperire de statistici de meci între 75% și 100%, cu Premier League/Championship aproape complete și Ligue 1 cea mai slabă dintre cele 5 mari ligi (75-84%).

---

## 5. „Active ascunse" — date existente, nefolosite de Football Oracle

Verificat direct în `match_history` (schema completă via `information_schema.columns` + `count()` per coloană, pentru toate cele 6 competiții cu rânduri „named" în producție): **`home_shots`, `away_shots`, `home_shots_on_target`, `away_shots_on_target`, `home_possession`, `away_possession`, `home_xg_actual`, `away_xg_actual` sunt 0% completate (NULL) pentru toate cele 6 ligi**, deși coloanele există în schemă din alt sprint. **Verificat și pe rândurile brute deja importate (`E0`,`E1`,`SP1`,`I1`,`D1`,`F1` ca coduri) — la fel, 0% — doar `home_elo`/`away_elo` a fost vreodată populat din importul Kaggle inițial.**

Concluzie directă: **absolut toate cele 12 coloane de statistici de meci din sursă (shots/target/fouls/corners/cartonașe) sunt azi complet nefolosite în producție, pentru toate ligile, indiferent de completitudinea lor în sursă.**

| Activ ascuns | Unde există | Din ce sezon | Completitudine (per ligă, vezi §3) | Merită integrat? |
|---|---|---|---|---|
| `HomeShots`/`AwayShots` | Sursă (mirror deja descărcat) | 2000/01 | 80-100% (6 ligi), 0% Romania | **Da** — coloane deja existente în `match_history`, azi goale |
| `HomeTarget`/`AwayTarget` | Sursă | 2000/01 | 80-100% (6 ligi), 0% Romania | **Da** — idem |
| `HomeFouls`/`AwayFouls` | Sursă | 2000/01 | 75-100% (6 ligi), 0% Romania | Da, dar necesită coloane noi (nu există în `match_history`) |
| `HomeCorners`/`AwayCorners` | Sursă | 2000/01 | 79-100% (6 ligi), 0% Romania | Da, coloane noi |
| `HomeYellow`/`AwayYellow`, `HomeRed`/`AwayRed` | Sursă | 2000/01 | 83-100% (6 ligi), 0% Romania | Da, coloane noi |
| `HTHome`/`HTAway`/`HTResult` (scor la pauză) | Sursă | 2000/01 | 99.98-100% (6 ligi), 0% Romania | Da, coloane noi — permite feature-uri „revenire", „performanță repriza 2" |
| `Form3Home`/`Form5Home`/`Form3Away`/`Form5Away` | Sursă | 2000/01 | 100% (toate 7) | Probabil — format exact necunoscut, necesită verificare directă a formulei înainte de folosire ca feature (ar putea fi redundant sau contradictoriu cu `home_form_score` deja calculat de `feature_engine.py`) |
| `HomeElo`/`AwayElo` (din acest mirror) | Sursă | 2000/01 | 99.99-100% (6 ligi), **22.3% Romania** | **Nu imediat** — sursă de Elo diferită de cea deja folosită de ELO Infrastructure v1.0 (componentă închisă, Regula #17: read-only, redeschisă doar pentru bug demonstrat); ar necesita reconciliere explicită, nu integrare tăcută |
| `Over25`/`Under25`/`MaxOver25`/`MaxUnder25` | Sursă | 2000/01 | 80-84% (6 ligi), 0% Romania | Piață nouă (Totals) — `odds_history` nu are coloane pentru asta azi |
| `HandiSize`/`HandiHome`/`HandiAway` | Sursă | 2000/01 | 86.9-90.6% (6 ligi), 0% Romania | Piață nouă (Handicap asiatic) — idem, `odds_history` nu are slot pentru asta |
| `C_LTH`/`C_LTA`/`C_VHD`/`C_VAD`/`C_HTB`/`C_PHB` | Sursă | variabil per ligă | 75-100% (6 ligi), 0% Romania | **Necunoscut** — nu poate fi evaluat pentru integrare fără a-i determina mai întâi semnificația |

---

## 6. Clasificare (A/B/C/D)

| Statistică | Clasă | Motivare |
|---|---|---|
| Shots, Shots on Target | **A** | Coloane deja existente în `match_history` (`home_shots`, `home_shots_on_target` etc.), azi 100% NULL. Zero schimbare de schemă — doar populare, prin serviciu de backfill după tiparul deja validat (`BackfillOddsService`). |
| Fouls, Corners, Cartonașe galbene/roșii | **B** | Necesită coloane noi în `match_history` (nu există azi) — migrare mică, tipar deja precedent (adăugarea `source_hash`/`source_url` la `odds_history`), dar tot necesită ADR conform regulii „schimbare de model de date". |
| Scor la pauză (HT) | **B** | Idem — coloane noi, tipar simplu, dar schimbare de model de date → ADR. |
| Formă precalculată (Form3/Form5) | **B** | Necesită mai întâi determinarea empirică a formulei exacte (ce reprezintă valorile) înainte de a decide dacă se stochează ca feature nou sau doar se validează contra `home_form_score` existent. |
| Piețe Over/Under 2.5, Handicap asiatic | **C** | `odds_history` nu are deloc slot pentru alt tip de piață în afară de 1X2 — necesită extindere reală de schemă/eventual tabelă nouă, decizie arhitecturală separată de scope-ul Odds Infrastructure Etapa 1-4 deja aprobat (care a fost explicit doar 1X2). |
| Elo din acest mirror (al doilea Elo) | **C** | Nu e o simplă populare de coloană — necesită o decizie explicită de reconciliere cu ELO Infrastructure v1.0, componentă deja închisă (Regula #17). Orice atingere fără bug demonstrat contrazice disciplina stabilită. |
| Coloanele `C_LTH/LTA/VHD/VAD/HTB/PHB` | **Neclasificabil azi** | Nu se încadrează onest în A-D fără a le determina mai întâi semnificația — a le clasifica acum ar însemna să presupun, exact ce sarcina interzice explicit. |
| Statistici de meci pentru Romania SuperLiga (shots/corners/cartonașe/fouls/HT/Over-Under/Handicap) | **D** | Sursa curentă (acest mirror) are 0% completitudine pentru toate acestea la Romania — imposibil de obținut din sursa actuală, indiferent de clasa aplicabilă celorlalte 6 ligi. |
| Referee, Attendance | **D** | Nu există deloc în acest fișier sursă, pentru nicio competiție — imposibil de obținut din sursa actuală (ar necesita altă sursă, posibil oglinda cu 133 de coloane identificată în auditul anterior, neconfirmată accesibilă din acest mediu). |

---

## 7. Impact ML (fără implementare, doar justificare)

| Statistică | Poate deveni feature ML? | Tip de feature | Valoare probabilă |
|---|---|---|---|
| Shots, Shots on Target | Da | Numeric, mediat pe fereastră glisantă (ex. medie ultimele 5 meciuri per echipă) | Probabil moderată — `PREDICTOR_ROADMAP_V4.md` a documentat deja că feature-urile sintetice actuale de șuturi/posesie sunt formule, nu date reale; date reale ar înlocui o aproximare cunoscută ca falsă, dar impactul pe acuratețe nu e demonstrat fără test de ablație. |
| Fouls, Corners, Cartonașe | Da | Numeric/count, mediat pe fereastră | Necunoscut — complet neexplorat azi în proiect; ar necesita ablație dedicată, conform disciplinei „verificat, nu presupus". |
| Scor la pauză (HT) | Da, indirect | Nu ca predictor direct al meciului curent (data leakage evident — HT-ul meciului de prezis nu există încă la momentul predicției) — **dar valoros ca sursă istorică** pentru feature-uri de tip „tendință de a întoarce scorul", „echipă puternică în repriza a doua" | Potențial interesant — feature nou, complet neexplorat, dar necesită atenție explicită la scurgere temporală (Regula #7 din CLAUDE.md) — HT-ul se folosește doar din meciuri TRECUTE ale echipei, niciodată din meciul curent. |
| Formă precalculată (Form3/Form5) | Posibil, ca validare | Comparație/cross-check | Valoare ca instrument de validare a `home_form_score` propriu, nu neapărat ca feature nou — riscă redundanță dacă reprezintă același concept. |
| Over/Under 2.5, Handicap | Nu direct ca feature de predicție rezultat | Ar alimenta un tip diferit de model (predicție total goluri / linie de handicap), separat de 1X2 | Relevant doar dacă proiectul extinde scope-ul de predicție dincolo de 1X2 — azi nu e cazul documentat. |
| Al doilea Elo (din mirror) | Nu recomandat fără decizie explicită | — | Risc de a contrazice/duplica silențios ELO Infrastructure v1.0 deja închisă — orice test de ablație ar trebui să compare explicit cele două surse, nu să le amestece. |
| C_* necunoscute | Nu, până nu se determină semnificația | — | Imposibil de evaluat valoarea fără a ști ce reprezintă. |

---

## 8. Impact utilizator (Streamlit, fără implementare)

| Statistică | Ce ar vedea utilizatorul |
|---|---|
| Shots, Shots on Target, Corners, Fouls, Cartonașe | Grafice de formă istorică per echipă (ex. „medie șuturi pe poartă, ultimele 10 meciuri"), comparație radar între cele două echipe ale unui meci, filtrare/sortare ligi după stil de joc (agresivitate, disciplină) |
| Scor la pauză (istoric) | Indicator „tendință de revenire" per echipă (ex. „X a întors scorul de la pauză în Y% din meciuri") — vizibil ca badge sau statistică în pagina de predicție |
| Formă precalculată | Comparație directă cu propriul `home_form_score` — util pentru explainability („de ce a prezis motorul asta") dacă cele două diverg vizibil |
| Over/Under 2.5, Handicap | Filtru/tab nou complet separat de predicția 1X2 actuală — relevant doar dacă se decide extinderea scope-ului de produs |
| Al doilea Elo | Explainability — afișare comparativă „Elo sursă A vs Elo sursă B" ar crește încrederea utilizatorului DACĂ sunt consistente; ar semnala o problemă DACĂ diverg — valoare de audit vizibil, nu doar de model |

---

## 9. Roadmap (valoare maximă / efort minim, nu spectaculos)

1. **Backfill Shots + Shots on Target** pentru cele 6 ligi (Premier League, Championship, La Liga, Serie A, Bundesliga, Ligue 1) — Clasă A, coloane deja existente, tipar de serviciu deja validat prin `BackfillOddsService`. Cel mai mic efort, cea mai mare valoare imediată (umple un gol deja documentat ca sintetic/fals în `PREDICTOR_ROADMAP_V4.md`).
2. **Determinarea semnificației coloanelor Form3/Form5** — efort minim (o singură analiză statistică, comparație cu `home_form_score` existent), valoare de validare/explainability.
3. **Fouls + Corners + Cartonașe** — Clasă B, necesită ADR + migrare mică (coloane noi în `match_history`), dar tipar deja precedent din extinderea `odds_history`. Efort mediu-mic, valoare potențială pentru feature engineering (neexplorat, necesită ablație).
4. **Scor la pauză (HT)** — Clasă B, coloane noi, atenție explicită la scurgere temporală. Valoare de explainability/produs mai clară decât de ML imediat.
5. **Piețe Over/Under + Handicap** — Clasă C, extindere reală de schemă pentru `odds_history` sau tabelă nouă. Efort mai mare, valoare condiționată de o decizie separată de extindere a scope-ului de produs dincolo de 1X2.
6. **Al doilea Elo (din mirror)** — Clasă C, blocat de disciplina Regulii #17 (componentă închisă). Nu recomand pornirea fără o decizie explicită de arhitect că merită redeschiderea ELO Infrastructure.
7. **C_* necunoscute** — nu poate intra în roadmap până nu i se determină semnificația; recomand asta ca prim pas dacă se dorește vreodată evaluarea lor, nu integrarea directă.
8. **Referee, Attendance, statistici Romania SuperLiga** — Clasă D din sursa actuală. Orice progres aici necesită o sursă nouă, explicit din afara acestui audit.

---

## Răspunsuri obligatorii

**1. Ce valoare ascunsă există deja în datele Football Oracle?**
Statistici reale de meci (șuturi, șuturi pe poartă, șuturi pe poartă, cornere, faulturi, cartonașe, scor la pauză) pentru 6 din cele 7 competiții cerute, cu completitudine între 75% și 100%, deja descărcate pe disc (fișierul sursă folosit pentru backfill-ul de cote), complet nefolosite azi — confirmat direct, nu presupus: toate coloanele corespunzătoare din `match_history` sunt 0% populate, inclusiv pe rândurile deja importate din Kaggle.

**2. Ce putem integra în următorul sprint fără nicio sursă nouă?**
Shots + Shots on Target pentru Premier League, Championship, La Liga, Serie A, Bundesliga, Ligue 1 — coloanele există deja în `match_history`, sursa există deja pe disc, tiparul de serviciu de backfill există deja și e validat în producție (Odds Infrastructure, Premier League ACCEPTATĂ). Zero sursă nouă, zero migrare pentru acest pas specific.

**3. Ce aduce cel mai mare câștig pentru ML?**
Neclar/nedemonstrat fără test de ablație — asta rămâne valabil indiferent de ce spune acest audit. Ce pot spune cu certitudine: Shots/Target înlocuiesc o aproximare deja documentată ca sintetică/falsă (`PREDICTOR_ROADMAP_V4.md`), deci sunt cel mai probabil candidat de testat primul, dar „probabil" nu înseamnă „demonstrat".

**4. Ce aduce cel mai mare câștig pentru utilizator?**
Statisticile de meci reale (șuturi, cornere, cartonașe) ca grafice de formă/comparație radar — vizibil imediat, independent de dacă modelul ML le folosește sau nu (consistent cu directiva „fiecare componentă finalizată trebuie să aibă și reprezentare în produs").

**5. Ce lipsește cu adevărat și justifică adăugarea unei surse externe?**
Trei goluri reale, confirmate: (a) orice statistică de meci pentru Romania SuperLiga — 0% în sursa actuală; (b) `Referee`/`Attendance` — absente complet din acest fișier, pentru orice ligă; (c) xG/xA/posesie/Big Chances/PPDA — deja documentat separat în `KNOWLEDGE_ENGINE_SOURCES_AUDIT_2026-07-13.md`, niciuna prezentă în acest mirror. Aceste trei goluri, și doar ele, justifică o sursă nouă — restul poate fi exploatat din infrastructura deja existentă.

---

*Acest document nu propune și nu autorizează nicio implementare. Orice pas din §9 necesită aprobare explicită separată, conform disciplinei proiectului.*
