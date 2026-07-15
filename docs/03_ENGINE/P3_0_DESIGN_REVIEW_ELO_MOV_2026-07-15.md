# P3.0 — Design Review: ELO Margin of Victory (MOV)

**Status**: Document de proiectare — zero cod scris, zero fișier de producție atins, zero implementare. Precondiție explicită pentru P3 (`ML_EVOLUTION_ROADMAP.md`), cerută de Chief Architect: P3 nu se implementează până acest document nu produce o formulă definitivă, aleasă și argumentată.
**De ce un document separat, nu direct un workflow ca la P1/P2**: P1/P2 optimizau modelul peste o informație deja fixată. P3 schimbă informația însăși pe care modelul o învață — `home_elo`/`away_elo` domină importanța feature-urilor de 15-20× (`PREDICTOR_ROADMAP_V4.md`, confirmat cantitativ în `ELO_PERFORMANCE_EXPERIMENT_2026-07-13.md`, §4). O greșeală de proiectare aici nu se corectează cu un alt experiment — se propagă în predictor, Learning Core, Confidence Engine (backlog), Value Betting.
**Bază de plecare**: implementarea actuală (`sync/backfill_features.py`, `ELOTracker`, linii 201-253) și seria de audituri ELO deja existente — `ELO_CANONICAL_SOURCE_AUDIT_2026-07-13.md`, `ELO_ROOT_CAUSE_ANALYSIS_2026-07-13.md`, `ELO_FIDELITY_AUDIT_2026-07-13.md`, `ELO_PERFORMANCE_EXPERIMENT_2026-07-13.md`. Nu repet ce e deja demonstrat acolo — îl citez și îl folosesc.

---

## 0. Ce face ELOTracker azi (linia de bază, exactă)

```python
HOME_ADVANTAGE = 50
K_FACTOR_BASE  = 32
K_FACTOR_NEW   = 40   # primele 10 meciuri ale unei echipe

def process_match(self, home, away, result):   # result: "H" | "D" | "A" — DOAR categorial
    r_home = self.get_elo(home) + HOME_ADVANTAGE
    r_away = self.get_elo(away)
    exp_home = 1 / (1 + 10**((r_away - r_home) / 400))
    score_home = 1.0 if result=="H" else (0.0 if result=="A" else 0.5)
    self.ratings[home] += k_home * (score_home - exp_home)
    self.ratings[away] += k_away * (score_away - exp_away)
```

`process_match()` **nu primește goluri** — doar `result`. Un 5-0 și un 1-0 produc exact aceeași actualizare. Asta e exact ce P3 propune să schimbe. Observație de implementare (nu decizie, doar constatare): `FormTracker.process_match()`, apelat din același loc, **primește deja** `home_goals`/`away_goals` — datele sunt disponibile la punctul de apel, doar neconectate azi la `ELOTracker`.

---

## 1. Ce formulă MOV folosim

### 1.1 Cele trei candidate

**A — FiveThirtyEight-style** (formula lor publică pentru NFL/NBA Elo, adaptată — nu au o versiune „oficială" de fotbal identică, folosesc SPI pentru cluburi, un model diferit, nu Elo clasic cu MOV; forma de mai jos e adaptarea standard, larg folosită de implementări hobbyist de Elo fotbalistic):

```
multiplier(gd, elo_diff) = ln(gd + 1) × [2.2 / (0.001 × elo_diff + 2.2)]
```

unde `gd` = diferența de goluri (≥1), `elo_diff` = `elo_câștigător − elo_învins` **semnat** (nu absolut) — dacă favoritul câștigă (elo_diff pozitiv), multiplicatorul scade (era oricum așteptat); dacă apare o surpriză (elo_diff negativ — câștigătorul avea rating mai mic), multiplicatorul crește (semnal mai puternic).

**B — ClubElo/eloratings.net-style** (funcție treaptă folosită documentat de World Football Elo Ratings pentru echipe naționale, și descrisă similar de ClubElo în FAQ-ul lor public):

```
G(gd) = 1               dacă gd ∈ {0, 1}
G(gd) = 1.5              dacă gd = 2
G(gd) = (11 + gd) / 8    dacă gd ≥ 3
```

Nu depinde de diferența de rating — doar de scor.

**C — Pi Ratings** (Constantinou & Fenton, 2013): **nu e o formulă MOV pentru Elo — e alt sistem de rating**. Fiecare echipă are DOUĂ ratinguri separate (home/away), actualizate printr-o regresie asupra diferenței de goluri (nu asupra rezultatului categorial W/D/L), cu o funcție de eroare logaritmică (`ψ(e) = c·log(1+|e|)`) și un factor de „scurgere" între ratingul de acasă și cel de deplasare al aceleiași echipe. Arhitectural, ar înlocui `ELOTracker` complet — schimbă și `HOME_ADVANTAGE` (constantă fixă azi, devine parte din model), și structura `elo_history`, și tot ce depinde de „un singur număr per echipă".

### 1.2 Comparație numerică — „nu vreau ca un 8-0 să explodeze"

Verificat direct (nu presupus), multiplicator relativ la o victorie 1-0, echipe de forță egală (`elo_diff=0`):

| Diferență de goluri | A (538-style, log) | B (ClubElo/eloratings, treaptă) |
|---:|---:|---:|
| 1 | 0,693 | 1,000 |
| 2 | 1,099 | 1,500 |
| 3 | 1,386 | 1,750 |
| 5 | 1,792 | 2,000 |
| 8 | 2,197 | 2,375 |
| **Raport 8-0 / 1-0** | **3,17×** | **2,375×** |

Ambele saturează (nu exploadează liniar — un 8-0 nu produce de 8 ori actualizarea unui 1-0 la niciuna din formule). A crește mai abrupt în intervalul mic (1→3 goluri) apoi se aplatizează logaritmic; B e mai liniară pe tot intervalul, cu pantă mai mică. A e **strict logaritmică** (cerința ta explicită); B e liniară-amortizată, nu logaritmică — o distincție reală, nu doar terminologică.

**A conține informație suplimentară pe care B nu o are** — reacția la surpriză vs. rezultat așteptat:

| Scenariu (gd=3) | Multiplicator A |
|---|---:|
| Forțe egale | 1,386 |
| Favoritul câștigă (elo_diff=+200, „așteptat") | 1,271 (redus) |
| Surpriză (elo_diff=−200, câștigătorul era outsider) | 1,525 (amplificat) |
| Surpriză extremă, gd=8, elo_diff=−400 | 2,685 (tot saturat, nu exploadează) |

### 1.3 Recomandare

**A (FiveThirtyEight-style, logaritmic + corecție elo_diff)**, cu o rezervă explicită: constantele `2,2` și `0,001` sunt derivate din NFL (distribuție de puncte total diferită de fotbal — mult mai puține goluri, mai multe rezultate 0-0/1-0/1-1). Nu le tratez ca adevăr importat — propun să rămână **candidatul funcțional** (formă logaritmică + corecție de surpriză), dar constantele să fie tratate ca parametri de validat empiric în faza de replay (§3), nu ca valori fixe garantate corecte pentru fotbal. Dacă replay-ul arată comportament degenerat (ex. multiplicator prea agresiv/prea slab pe distribuția reală de scoruri din `match_history`), se ajustează înainte de comparația finală, nu după.

**B (ClubElo/eloratings-style)** rămâne alternativa de rezervă — mai simplă, zero constante de tuning, precedent de zeci de ani (eloratings.net), dar ignoră complet contextul „era de așteptat sau nu" și nu e strict logaritmică.

**C (Pi Ratings) — scot din scopul P3.** Nu e o îmbunătățire incrementală a `ELOTracker` — e un sistem de rating diferit, care ar necesita propriul proiect de arhitectură (schimbă `HOME_ADVANTAGE`, structura de rating per echipă, tot ce citește `home_elo`/`away_elo` ca număr unic). Recomand să rămână o idee separată, viitoare, posibil un candidat pentru „Idei explicit amânate" din roadmap — nu P3.

**Decizie necesară de la tine**: A sau B. Eu recomand A, cu constantele supuse validării empirice descrise la §3.

---

## 2. Funcția de amortizare — răspuns inclus în §1.2

Confirmat numeric mai sus: ambele candidate A/B saturează, niciuna nu produce creștere liniară/explozivă. A e strict logaritmică (cerința ta), B e liniar-amortizată.

---

## 3. Cum verificăm fidelitatea noului ELO

**Constatare obligatorie, înainte de metodologie**: nu avem acces azi la date reale ClubElo (clubelo.com). Singura referință externă existentă în proiect e `ELO_RATINGS_FALLBACK` (`mappings.py`) — un tabel hardcodat, stil **eloratings.net** (World Football Elo Ratings, orientat pe echipe naționale, scală proprie, NU ClubElo), deja folosit și auditat integral în `ELO_FIDELITY_AUDIT_2026-07-13.md`. Acel audit a demonstrat, cu dovezi:

- Doar **16/64 intrări** (25%) sunt comparabile cu `ELOTracker` — restul de 48 sunt echipe naționale, complet absente din `match_history` (acoperire zero, nu imprecizie).
- Cele 16 comparabile sunt exclusiv cluburi de elită (Premier League/La Liga/Serie A/Bundesliga/Ligue 1) — nimic din Romania SuperLiga sau ligi secundare.
- Eroare sistematică deja demonstrată: **medie 9,4%, 100% în aceeași direcție** (subestimare) — cauzată de „cold start" (toate echipele pornesc la 1.500, fereastră de replay efectiv de ~5 ani densă, gol de date 2001-2020) — **o problemă de inițializare/acoperire, independentă de formula de actualizare** (categorială vs. MOV). Orice variantă de Elo pornită la 1.500 pe aceeași fereastră de date va avea probabil o eroare sistematică similară.

**Consecință directă pentru metodologie**: a compara Replay B direct cu acest fallback, ca măsură absolută de „adevăr", ar repeta o eroare deja documentată — am măsura în mare parte cold-start, nu calitatea formulei MOV. Propun trei verificări, nu una, ordonate după cât de mult ne putem încrede în ele:

**3.1 — Comparație RELATIVĂ (nu absolută), pe cele 16 echipe deja folosite în `ELO_FIDELITY_AUDIT`**
Ambele replay-uri (A și B) rulează pe exact aceeași fereastră de date, deci cold-start-ul e (aproximativ) identic pentru amândouă — comparăm dacă **eroarea vs. fallback SCADE sau CREȘTE** de la Replay A la Replay B, pe aceleași 16 echipe, pereche cu pereche. Nu pretind că asta măsoară „fidelitate absolută față de ClubElo" (nu avem acele date) — măsor doar dacă MOV apropie sau depărtează ratingul de singura referință externă pe care o avem, relativ la ce aveam deja.

**3.2 — Stabilitate sezon-cu-sezon (100% internă, nu are nevoie de nicio referință externă — cea mai de încredere dintre cele trei)**
Pentru fiecare echipă cu istoric suficient, calculăm ratingul de sfârșit de sezon, an cu an, pentru Replay A și Replay B separat. Comparăm: (a) volatilitatea (deviația standard a variației sezon-la-sezon), (b) corelația de rang (Spearman) între clasamentele consecutive. Ipoteză de verificat, nu presupusă: MOV ar trebui să facă ratingul mai discriminant (diferențiază mai clar echipele de formă bună/proastă) fără să devină instabil/zgomotos de la un sezon la altul.

**3.3 — Distribuția diferențelor (cerința ta explicită, aplicată în două locuri)**
- Intern: pentru fiecare echipă, `rating_B − rating_A` la finalul replay-ului — histogramă, nu doar medie. Verifică dacă MOV mută toate echipele în aceeași direcție (semnal sistematic, posibil bug) sau diferențiază (unele sus, unele jos, în funcție de cât de des au câștigat/pierdut la scor mare).
- Extern (aceeași rezervă ca la 3.1): reia exact formatul deja stabilit în `ELO_FIDELITY_AUDIT` (medie/mediană diferență absolută %, percentila 95, verificare „100% aceeași direcție sau mixt") — comparabil direct cu cifrele deja publicate acolo (9,40% medie, 8,58% mediană pentru Replay A/D).

**Ce NU face acest document**: nu propune achiziția de date reale ClubElo (clubelo.com) — ar fi o sursă nouă de date externe, cu propriile întrebări de licențiere/scraping/fiabilitate, candidat plauzibil pentru „Football Data Harvester" pe termen lung, dar explicit în afara scopului P3.0.

---

## 4. Replay-ul — design

Exact cum ai cerut, formalizat:

- **Replay A** = `ELOTracker` exact cum e azi (categorial, `HOME_ADVANTAGE=50`, `K_FACTOR_BASE=32`/`K_FACTOR_NEW=40`), rulat cronologic peste tot `match_history` — de fapt identic cu varianta **D** din `ELO_PERFORMANCE_EXPERIMENT_2026-07-13.md` (deja rulată, deja are cifre de referință: Accuracy 0,4864, Log Loss 1,0305 — notă: valori dinainte de fix-ul de leakage la imputare, nu identice cu benchmark-ul oficial ADR-020, dar aceeași metodologie de replay).
- **Replay B** = aceeași infrastructură (aceeași ordine cronologică, aceiași `INITIAL_ELO`/`HOME_ADVANTAGE`/K-factori), dar `process_match()` primește și golurile, aplică multiplicatorul MOV ales la §1 peste termenul de actualizare (`k × multiplier × (score − expected)`).
- **Rulează complet independent, 100% local sau într-un workflow temporar read-only** (exact pattern-ul deja stabilit la P1/P1.1/P2 — `workflow_dispatch`, zero scriere Supabase, zero atingere `match_history`/`elo_history`/`ELOTracker`-ul de producție din `sync/backfill_features.py`). Niciuna din cele două nu scrie nicăieri — ambele produc, în memorie, o serie completă de ELO pre-meci pentru toate cele 53.409 rânduri, folosită direct ca input pentru §5B.
- **Zero suprascriere** — literal, cerința ta. `ELOTracker`-ul de producție rămâne neatins până (și dacă) urmează o decizie separată de promovare, cu propriul proces (nu implicit, nu automat).

---

## 5. Ce comparăm

**A — Calitatea ELO în sine** (§3 de mai sus): comparație relativă vs. `ELO_RATINGS_FALLBACK` (16 echipe), stabilitate sezon-cu-sezon, distribuția diferențelor A-vs-B.

**B — Calitatea predictorului**: reantrenare XGBoost walk-forward, exact metodologia oficială (5 folduri, `random_state=42`, hiperparametrii de producție — neschimbați, P1/P1.1 închise), `home_elo`/`away_elo` înlocuite cu Replay B în loc de Replay A. Comparație directă cu benchmark-ul oficial (ADR-020: Accuracy 0,4868 / Log Loss 1,0253 / Brier 0,6145) — exact ca la P1/P1.1/P2.

---

## 6. Criteriul de succes — formalizat, neschimbat față de ce ai cerut

Nu e suficient un câștig marginal de predictor izolat. Promovare (spre implementare reală, nu doar „experiment reușit") doar dacă:

```
(fidelitatea ELO crește la §3 — eroare relativă vs. referință scade ȘI/SAU stabilitate sezon-cu-sezon se îmbunătățește)
                              SAU
(predictorul crește clar — Accuracy ≥+0,3pp FĂRĂ regres simultan pe Log Loss ȘI Brier,
 pragul deja stabilit în ML_EVOLUTION_ROADMAP.md P3)
```

Respins dacă fidelitatea ELO scade ȘI câștigul de predictor e doar marginal (sub pragul de mai sus). Nu se promovează un ELO „mai puțin fidel" doar pentru un câștig mic de predictor — exact cerința ta.

Propun ca acest criteriu compus să înlocuiască/completeze explicit criteriul de succes actual al P3 din roadmap (care azi menționează doar Accuracy/Log Loss/Brier, nu și fidelitatea) — de actualizat în roadmap odată ce alegi formula.

---

## 7. Decizii rămase, de la tine

1. **A sau B** — formula MOV (recomand A, cu constantele supuse validării empirice la replay, nu fixate a priori).
2. Confirmare că **C (Pi Ratings) rămâne în afara scopului P3**, tratat separat, viitor.
3. Confirmare metodologie de fidelitate (§3) — în special acceptarea explicită că nu comparăm cu ClubElo real (nu avem acele date), ci cu referința deja existentă și deja auditată (`ELO_RATINGS_FALLBACK`), interpretată relativ, nu absolut.

După aceste trei confirmări, implementarea P3 (Replay A/B, workflow temporar, aceeași disciplină read-only ca P1/P1.1/P2) poate începe.
