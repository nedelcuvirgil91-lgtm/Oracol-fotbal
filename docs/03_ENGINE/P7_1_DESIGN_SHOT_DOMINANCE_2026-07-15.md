# P7.1 — Design Review: `shot_dominance`

**Status**: Document de proiectare — zero cod scris, zero fișier de producție atins, zero implementare, zero migrare. Precondiție explicită pentru P7.1 (`ML_EVOLUTION_ROADMAP.md`), cerută de Chief Architect: P7.1 e primul (și singurul, în această rundă) feature nou din familia „Structural Match Statistics", implementat izolat, cu ablație completă, înainte de a discuta P7.2 sau oricare din restul de 17 feature-uri propuse în `STRUCTURAL_MATCH_STATISTICS_ROADMAP.md`.

**De ce un document separat, nu direct implementare ca la corner/card/foul**: acele trei au fost implementate direct pentru că infrastructura de calcul (`CornerCardTracker`, coloanele brute deja backfill-uite) era deja identică, unu-la-unu, cu un tracker existent (`FoulsTracker`). Pentru `shot_dominance` NU există azi un tracker pentru șuturi TOTALE — `ShotsTracker` (`sync/backfill_features.py:326`) există, dar calculează media glisantă de **șuturi PE POARTĂ** (`shots_on_target`), nu șuturi totale, în ciuda numelui generic. Un document scurt de proiectare evită o confuzie de nomenclatură la implementare și fixează exact ce se calculează înainte de a scrie cod.

---

## 1. Definiția exactă a feature-ului

```
shot_dominance = home_shot_avg_recent − away_shot_avg_recent
```

unde `home_shot_avg_recent` / `away_shot_avg_recent` = media glisantă a șuturilor TOTALE (`home_shots`/`away_shots`, coloane deja existente în `match_history`, backfill ADR-011, 66,7% populate pe cele 5 ligi mari — verificat acum, nu presupus, vezi §4) din ultimele `FORM_WINDOW` meciuri ale fiecărei echipe, calculată STRICT înainte de meciul curent (aceeași disciplină ca `corner_dominance`/`card_diff`/`foul_diff`).

Nu e un procent, nu e normalizat la posesie — e diferența brută de volum de șuturi, exact ca `corner_dominance` (diferență brută de cornere), nu un raport. Semnul: pozitiv → gazdele au tras mai mult recent decât oaspeții.

**De ce diferență și nu raport**: precedent direct — toate cele trei feature-uri deja promovate (`corner_dominance`, `card_diff`, `foul_diff`) folosesc diferența brută, nu raportul. Un raport ar introduce instabilitate la numitor mic (o echipă cu 2 șuturi/meci recent ar produce rapoarte extreme) — problemă pe care diferența brută n-o are. Consistență de metodologie cu precedentul existent, nu presupunere nouă.

---

## 2. Metodologia de calcul

### 2.1 Tracker nou, NU reutilizarea `ShotsTracker`

`ShotsTracker` (existent) rămâne neatins — servește azi `compute_team_offdef_rating()` cu media de șuturi pe poartă, folosită la blend-ul ELO/ofensiv-defensiv (`feature_engine.py`). Nu trebuie reconfigurat pentru altă coloană, ar risca să-i schimbe comportamentul pentru consumatorul existent.

Propun un tracker nou, `ShotCountTracker` (nume distinct, deliberat, ca să nu se confunde cu `ShotsTracker`/SOT) — identic ca disciplină cu `CornerCardTracker`/`FoulsTracker`:

- Procesează meciurile în ordine cronologică (aceeași buclă din `sync/backfill_features.py` care alimentează și `ShotsTracker`/`FoulsTracker`/`CornerCardTracker` azi, la fiecare meci).
- La fiecare meci, întoarce media DINAINTE de acel meci, din ultimele `FORM_WINDOW` meciuri cu valoare reală cunoscută (azi `FORM_WINDOW = 10`).
- O echipă fără niciun meci cu șuturi reale în istoric întoarce `None` — niciodată aproximat (Regula #8, CLAUDE.md: „nicio stare necunoscută nu se aproximează").
- Consumă `home_shots`/`away_shots` (coloane deja existente, nu necesită migrare nouă pentru datele brute — doar pentru coloanele de medie glisantă, vezi §2.2).

### 2.2 Coloane noi (dacă P7.1 e Accepted — nu se creează înainte de verdict)

Exact precedentul `home_corner_avg_recent`/`away_corner_avg_recent` (ADR-012) și `home_foul_avg_recent`/`away_foul_avg_recent` (ADR-013): două coloane noi pe `match_history`, `home_shot_avg_recent`/`away_shot_avg_recent`, populate de `ShotCountTracker` la backfill, consumate de `ml_predictor._fetch_training_dataframe()` pentru a deriva `shot_dominance` la momentul antrenării (nu stocat redundant ca atare, exact ca la `corner_dominance`). Migrarea propriu-zisă (dacă se ajunge acolo) necesită propriul ADR, per regula existentă — nu se creează azi, doar se anticipează structura.

### 2.3 Calea live (predicție)

`oracle_engine._build_ml_features()` ar calcula `shot_dominance` identic, din aceleași două coloane, la momentul predicției — simetric cu tratamentul `corner_dominance`/`foul_diff` deja existent acolo. Nu se schimbă azi — doar se documentează ce ar urma, dacă P7.1 e Accepted.

---

## 3. Evitarea leakage-ului

- **Point-in-time strict**: `ShotCountTracker.process_match()` actualizează istoricul unei echipe DUPĂ ce a fost citită media pentru meciul curent — exact ordinea de operații deja verificată la `CornerCardTracker`/`FoulsTracker` (citește media, apoi procesează rezultatul, nu invers).
- **Walk-forward, nu split aleator**: ablația rulează cu exact `ml_predictor.MLPredictorEngine._walk_forward_validate()` — expanding window, 5 folduri cronologice, aceiași hiperparametri XGBoost de producție, `random_state=42` fixat. Niciun rând din fold-ul de validare nu contribuie la media glisantă folosită pentru propriile lui predicții (media e deja „înghețată" în coloana `home_shot_avg_recent`/`away_shot_avg_recent` la backfill, calculată o singură dată, cronologic).
- **NaN, nu imputare aproximativă la nivel de rând**: rândurile fără istoric suficient (fereastră neînceputa încă pentru o echipă, sau meci fără `home_shots`/`away_shots` real) primesc `NaN` pentru `shot_dominance`, umplut cu mediana globală DOAR ca tratament de preprocesare pentru XGBoost, identic cu tratamentul de producție pentru `corner_dominance`/`foul_diff` azi — nu o valoare inventată per rând.
- **Sursa datelor brute e deja verificată non-leaking**: `home_shots`/`away_shots` sunt statistici POST-meci (numărul final de șuturi din tot meciul), niciodată disponibile înainte de kickoff pentru meciul curent — de asta feature-ul se calculează din ISTORICUL recent al echipei, nu din meciul curent însuși. Exact analogia cu `corner_dominance`/`foul_diff`, niciun risc nou introdus.

---

## 4. Datele — verificat acum, nu presupus

```sql
SELECT league, COUNT(*) AS total_meciuri,
       COUNT(*) FILTER (WHERE actual_result IS NOT NULL) AS cu_rezultat,
       COUNT(*) FILTER (WHERE actual_result IS NOT NULL
                         AND home_shots IS NOT NULL AND away_shots IS NOT NULL) AS cu_rezultat_si_shots
FROM match_history
WHERE league IN ('Premier League','La Liga','Serie A','Bundesliga','Ligue 1')
GROUP BY league;
```

| Ligă | Meciuri cu rezultat | Din care cu `shots` populat |
|---|---:|---:|
| Premier League | 1.140 | 760 |
| La Liga | 1.140 | 760 |
| Serie A | 1.140 | 760 |
| Bundesliga | 917 | 611 |
| Ligue 1 | 916 | 610 |
| **Total** | **5.253** | **3.501 (66,6%)** |

Total identic (5.253) cu setul folosit la `CORNER_CARD_DOMINANCE_ABLATION_2026-07-13.md`/`FOULS_DOMINANCE_ABLATION_2026-07-14.md` — aceleași 5 ligi, aceeași definiție de „meci cu rezultat cunoscut". Acoperirea brută de `shots` (66,6%) e sub cea de `fouls`/`corners`/`cards` din ablațiile anterioare (92,7% la faulturi) — de anticipat, dat fiind că sursa (`football-data.co.uk`) are coloane de șuturi disponibile pe o fereastră temporală mai scurtă decât fouls/cards pentru unele ligi (confirmat în `DATASET_CAPABILITY_AUDIT_2026-07-13.md`). Acoperirea REALĂ pentru `shot_dominance` (rânduri cu ISTORIC de `FORM_WINDOW` meciuri anterioare, nu doar rândul curent) va fi mai mică decât 66,6% — de măsurat exact la rularea ablației, nu presupusă azi.

---

## 5. Planul de ablație — metodologie identică cu precedentul, nu una nouă

- **Baseline**: `FEATURE_COLUMNS` de producție curent (13 intrări — include deja `corner_dominance`, `card_diff`, `foul_diff`, promovate anterior).
- **Extins**: baseline + `shot_dominance` (14 intrări).
- **Metodologie**: `_walk_forward_validate`, expanding window, 5 folduri, aceiași hiperparametri XGBoost, `random_state=42`, umplere NaN cu mediana globală înainte de split (identic cu tratamentul de producție), pe cele 5.253 meciuri.
- **Workflow temporar, read-only** — exact pattern-ul P1-P3 (`workflow_dispatch`, zero scriere Supabase, șters imediat după raportarea rezultatului).
- **Raportare onestă**: acuratețe/log-loss/Brier per fold + medie, magnitudine raportată exact, fără rotunjire optimistă — precedentul `foul_diff` (câștig mic, dar simultan pe toate 3) arată că magnitudinea mică nu invalidează un Accepted, dacă simultaneitatea e reală.

---

## 6. Criteriul de succes — explicit, neschimbat față de regula deja stabilită

Conform `CLAUDE.md` („Promovarea unui model cere dovadă statistică simultană pe metrici multiple — niciodată o singură metrică, niciodată intuiție") și precedentul direct `ADR-020`/`CORNER_CARD_DOMINANCE_ABLATION`/`FOULS_DOMINANCE_ABLATION`:

```
ACCEPTED   dacă Accuracy, Log Loss ȘI Brier se îmbunătățesc SIMULTAN
           (fără prag minim de magnitudine — precedentul foul_diff arată
           că un câștig mic dar simultan pe toate 3 e suficient)

REJECTED   dacă cel puțin o metrică regresează
           (precedent: HT_SCORE_ABLATION_2026-07-14 — accuracy câștigă,
           dar log-loss/Brier regresează → respins)

INCONCLUSIVE / Needs refinement   dacă rezultatele sunt mixte fără o
           regresie clară (ex. o metrică neschimbată în limita zgomotului,
           celelalte două ambigue) — se aplică distincția deja stabilită
           în legenda roadmap-ului (poate rămâne stare finală permanentă
           dacă efectul e real dar prea mic pentru cost)
```

**Condiție suplimentară, specifică acestei runde**: dacă acoperirea reală de date (rânduri cu istoric complet de `FORM_WINDOW` meciuri) se dovedește prea mică pentru un test statistic relevant (sub, aproximativ, 50% din cele 5.253 rânduri — prag calitativ, nu o cifră magică, de judecat la momentul rulării față de precedentele de 66,6-92,7%), rezultatul se raportează ca **Inconclusive** din cauza datelor, nu Rejected — nu se confundă „feature-ul nu ajută" cu „nu am avut destule date să testăm".

---

## 7. Ce NU face acest document

Nu implementează `ShotCountTracker`, nu creează coloane noi, nu modifică `FEATURE_COLUMNS`, nu creează ADR sau migrare. Nu proiectează P7.2 (`sot_dominance`) — acela primește propriul document scurt, DOAR dacă P7.1 e Accepted, reutilizând `ShotsTracker` deja existent (implementare mai ieftină, dar decizia de succes/abandon rămâne separată, proprie). Nu decide dacă restul familiei de 17 feature-uri din `STRUCTURAL_MATCH_STATISTICS_ROADMAP.md` merită implementate — rămân backlog, neprogramate, per decizia explicită a Chief Architect de a nu bundui feature-uri noi într-un singur test.

**Gata de implementare** — după acest document, P7.1 poate trece direct la workflow temporar de ablație (fără altă rundă de proiectare), exact ca P1/P2/P3.1.
