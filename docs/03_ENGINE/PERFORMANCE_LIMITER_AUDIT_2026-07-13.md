# PERFORMANCE_LIMITER_AUDIT_2026-07-13.md — Football Oracle

**Status**: Audit inginerească de performanță — zero cod scris, zero fișier de producție modificat, zero soluție propusă, zero brainstorming. Sintetizează dovezile deja obținute (`ELO_*`, `PREDICTOR_ROADMAP_V4`, `DATA_PIPELINE_INVESTIGATION`, `REST_DAYS_VALIDATION`) **fără să le reanalizeze** și adaugă măsurători noi, punctuale, pentru componentele neacoperite încă: distribuția ligilor, arhitectura XGBoost, procesul de antrenare, metodologia walk-forward.
**Scop**: identificarea limitatorului principal de performanță și un plafon realist de acuratețe, ca bază de decizie — nu ca plan de acțiune.

---

## Metodologie

Pentru componentele deja investigate (ELO, imputare, dezechilibru de clase, calitate date istorice, rest_days), citez direct rezultatele deja măsurate, cu sursa exactă. Pentru componentele neacoperite, am rulat trei experimente noi, azi, pe același set de 53.409 meciuri, cu aceeași metodologie walk-forward (5 folduri, expanding window):

1. **Distribuția ligilor** — acuratețea modelului, spartă pe ligă (folosind predicțiile deja calculate din `ELO_PERFORMANCE_EXPERIMENT`, variantele A și D).
2. **Sensibilitate la capacitatea modelului** — XGBoost cu 4 configurații de complexitate diferită + o regresie logistică (cel mai simplu model posibil), pe feature-setul D (cel mai performant din experimentul anterior).
3. **Walk-forward vs. random split** — aceleași feature-uri (D), comparate cu o împărțire aleatorie 80/20 (cu scurgere temporală intenționată, ca reper).

---

## Analiza componentă cu componentă

### 1. ELO
**Contribuție**: cel mai mare feature individual — importanță de permutare 0,048-0,071 (de 6-15× mai mare decât următorul feature), eliminarea lui scade acuratețea de la 46,65% la 43,98% (semnificativ, p=4×10⁻¹⁶⁹). Acoperire completă (nu doar 47%) crește acuratețea la 48,64% (semnificativ, p=4×10⁻⁴³).
**Limitator**: **Major** — dar prin acoperire incompletă, nu prin conceptul în sine.
**Dovezi**: experimentale, directe (`ELO_PERFORMANCE_EXPERIMENT_2026-07-13.md`).
**Încredere**: Ridicată.

### 2. `offensive_rating`
**Contribuție**: importanță de permutare 0,0046-0,0071 — cu un ordin de mărime sub ELO.
**Limitator**: **Minor-mediu** — contribuie, dar e departe de al doilea factor real de impact. Notă din audituri anterioare (`PREDICTOR_ROADMAP_V4`): componenta de bază (șuturi pe poartă, posesie) e sintetică pentru echipele de club — deci acest număr măsoară valoarea unui rating parțial informat, nu plafonul teoretic al unui rating complet informat.
**Dovezi**: experimentale directe (permutation importance, acest audit + cel anterior).
**Încredere**: Ridicată pentru contribuția măsurată azi; joasă pentru „cât ar contribui cu date reale de șuturi/posesie" — nedemonstrat.

### 3. `defensive_rating`
**Contribuție**: importanță de permutare între −0,0006 și +0,0007 — **practic zero, în unele folduri ușor negativă** (adăugare de zgomot, nu semnal).
**Limitator**: **Minor** — cel mai slab feature din tot setul testat.
**Dovezi**: experimentale directe.
**Încredere**: Ridicată.

### 4. `form_score`
**Contribuție**: importanță de permutare între −0,0007 și +0,0017 pentru ambele variante (home/away) — marginal, unele valori negative.
**Limitator**: **Minor**.
**Dovezi**: experimentale directe.
**Încredere**: Ridicată.

### 5. `h2h_modifier`
**Contribuție**: 0,0004-0,0011 — marginal, printre cele mai slabe.
**Limitator**: **Minor**.
**Dovezi**: experimentale directe.
**Încredere**: Ridicată.

### 6. `home_advantage`
**Contribuție**: nu e feature ML — e un multiplicator fix în motorul Poisson, niciodată expus modelului XGBoost, deci nu are o „importanță de permutare" proprie. Dovadă indirectă: clasa „Home" reprezintă 44,0% din rezultate (dezechilibru de bază), iar toate modelele testate ating doar 46,7-48,9% acuratețe — cu 3-5 puncte procentuale peste un predictor trivial „mereu Home". Avantajul de teren e deja larg absorbit în priorul de clasă, nu într-un feature separat.
**Limitator**: **Nedemonstrat ca limitator separat** — parte structurală a problemei (dezechilibrul de clase), nu o componentă izolabilă cu testele rulate.
**Dovezi**: indirecte (distribuția claselor).
**Încredere**: Joasă — n-am rulat un test dedicat care izolează exact acest multiplicator (ar necesita rularea motorului Poisson, în afara scopului „doar măsurători pe feature-urile ML").

### 7. `league_strength` (distribuția ligilor)
**Descoperire nouă, măsurată azi**: `match_history` conține meciuri din **40 de ligi/coduri distincte**, dintre care doar **11 sunt urmărite efectiv de Football Oracle**. **Doar 33,6% din meciurile evaluate (14.962 din 44.508) aparțin celor 11 ligi urmărite** — restul de 66,4% sunt din ligi complet irelevante pentru produs (Scoția, Japonia, China, Polonia, Austria, Irlanda, Finlanda, diviziile inferioare engleze/italiene/franceze/germane, Argentina, Brazilia, Mexic etc.).
**Acuratețea diferă real între cele două grupuri**:
- Varianta A (actuală): 48,22% pe ligile urmărite vs. 45,86% pe restul.
- Varianta D (ELOTracker complet): **50,86%** pe ligile urmărite vs. 47,52% pe restul.
**Limitator**: **Major, dar în sens de raportare, nu de model** — cifrele de acuratețe raportate în tot acest fir de audit (46,65%/48,64%) sunt medii diluate cu 2/3 date irelevante pentru produs. Performanța reală pe ce contează azi e cu 2-2,5pp mai bună decât cifrele „headline".
**Dovezi**: experimentale directe, măsurate azi.
**Încredere**: Ridicată.

### 8. `rest_days`
**Contribuție**: testat deja, exhaustiv, într-un audit dedicat anterior (`REST_DAYS_VALIDATION.md`) — ablație reală pe 50.402 meciuri: baseline ELO+form acc=0,4667, cu rest_days=0,4658 (mai slab), cu prag binar=0,4660 (mai slab). **Zero câștig măsurabil, posibilă regresie mică**.
**Limitator**: **Non-limitator, deja demonstrat respins** — nu se reanalizează, cităm rezultatul existent.
**Dovezi**: experimentale directe, deja existente.
**Încredere**: Ridicată.

### 9. Feature engineering (calitatea formulelor de calcul)
**Contribuție**: deja demonstrat (`PREDICTOR_ROADMAP_V4.md`) — `avg_shots_on_target`/`avg_possession`, intrări în formula `offensive_rating`, sunt sintetice (derivate din goluri sau constanta 50,0) pentru toate echipele de club, în toate sursele live. Feature-ul conceptual „rating ofensiv/defensiv" nu e testat izolat de calitatea intrărilor lui.
**Limitator**: **Major, dar nedemonstrat cât anume** — știm că intrările sunt slabe calitativ, nu știm cât ar câștiga modelul cu intrări reale (nicio sursă de date confirmată, per `DATA_AUDIT`/Discovery Probe).
**Dovezi**: parțiale — demonstrat că intrările sunt sintetice, nedemonstrat impactul asupra acurateței cu intrări reale.
**Încredere**: Ridicată pe diagnostic, joasă pe magnitudine.

### 10. Imputarea valorilor lipsă
**Contribuție**: deja demonstrat exhaustiv (`PREDICTOR_ROADMAP_V4.md` + `ELO_PERFORMANCE_EXPERIMENT`) — 0% din rânduri au toate cele 10 `FEATURE_COLUMNS` reale simultan; 46% au toate imputate. Testul direct (variantele A vs. D) arată că **acoperirea completă (chiar cu o sursă imperfect calibrată) bate acoperirea parțială cu +4,3pp accuracy**.
**Limitator**: **Major, deja demonstrat cu cea mai solidă dovadă din tot acest fir de audit.**
**Dovezi**: experimentale directe, testate cu semnificație statistică (p=4×10⁻⁴³).
**Încredere**: Ridicată.

### 11. Dezechilibrul claselor (Home/Draw/Away)
**Contribuție**: distribuție reală H=44,0% / A=29,9% / D=26,0%. **Toate cele 4 variante testate (A/B/C/D) prezic egalul aproape deloc**: acuratețe D între 0,7% și 1,3% — inclusiv varianta E (subset curat), unde acuratețea D urcă la 14,45%, dar pe un eșantion mult mai mic și cu acuratețe generală mai slabă. Modelul „câștigă" aproape exclusiv din H/A, niciodată din D.
**Limitator**: **Major, transversal la toate variantele testate** — nu e cauzat de ELO, persistă indiferent de sursa de ELO folosită.
**Dovezi**: experimentale directe, măsurate în acest audit și în cel anterior.
**Încredere**: Ridicată pe existența problemei; joasă pe soluție/magnitudine de câștig posibil (nu am testat o abordare dedicată egalurilor).

### 12. Calitatea datelor istorice
**Contribuție**: deja demonstrat (`DATA_PIPELINE_INVESTIGATION_2026-07-13.md`) — disjuncție completă între rândurile cu ELO (Kaggle) și cele cu rating/formă (backfill), cauzată de secvențiere operațională greșită (backfill rulat o singură dată, înainte de import). Plus, descoperit în `ELO_ROOT_CAUSE_ANALYSIS`: 646 meciuri duplicate (2,4% din date) și un bug de normalizare specific („Club Atlético de Madrid").
**Limitator**: **Major** — cauza rădăcină a problemei de imputare de la §10.
**Dovezi**: experimentale directe, deja existente.
**Încredere**: Ridicată.

### 13. Arhitectura XGBoost
**Test nou, rulat azi** — sensibilitate la capacitatea modelului, feature-set D, walk-forward identic:

| Configurație | Accuracy | Log Loss | Brier |
|---|---:|---:|---:|
| Actuală (n_est=150, depth=4) | 0,4864 | 1,0305 | 0,6172 |
| Mult mai simplă (n_est=50, depth=2) | **0,4882** | **1,0241** | **0,6138** |
| Mult mai complexă (n_est=400, depth=6) | 0,4735 | 1,0558 | 0,6307 |
| Foarte complexă (n_est=800, depth=8) | 0,4601 | 1,0889 | 0,6478 |
| Regresie logistică (liniară, cel mai simplu model posibil) | **0,4892** | **1,0212** | **0,6121** |

**Descoperire clară**: creșterea complexității modelului **înrăutățește** performanța (supra-antrenare pe feature-uri sărace), iar un model **mai simplu** — inclusiv o regresie logistică pur liniară — obține rezultate egale sau ușor mai bune decât XGBoost-ul actual.
**Limitator**: **Non-limitator, demonstrat direct** — arhitectura nu limitează performanța; dacă ceva, complexitatea actuală e deja la limita utilă. Plafonul e dat de conținutul de informație al feature-urilor, nu de puterea modelului.
**Dovezi**: experimentale directe, noi, testate azi.
**Încredere**: Ridicată.

### 14. Procesul de antrenare
**Contribuție**: acoperit indirect de §13 (hiperparametri nu limitează) și de varianta E din experimentul anterior (volumul de date contează mai mult decât puritatea lor — subsetul mic dar „curat" a performat mai slab decât setul mare cu imputare).
**Limitator**: **Minor-mediu** — nu identificat ca limitator separat de cele deja acoperite (date, feature-uri).
**Dovezi**: experimentale indirecte.
**Încredere**: Medie.

### 15. Metodologia walk-forward
**Test nou, rulat azi** — feature-set D, walk-forward (5 folduri) vs. random split 80/20 (cu scurgere temporală intenționată, ca reper de „cât de mult ar câștiga modelul dacă am trișa"):

| Metodă | Accuracy | Log Loss | Brier |
|---|---:|---:|---:|
| Walk-forward (disciplinat, fără scurgere) | 0,4864 | 1,0305 | 0,6172 |
| Random split 80/20 (cu scurgere temporală) | 0,4859 | 1,0279 | 0,6165 |

**Descoperire clară**: diferența e **neglijabilă** (0,05pp accuracy) — disciplina walk-forward **nu costă performanță măsurabilă** față de o validare „trișată". Plafonul de azi nu e un artefact al rigorii metodologice.
**Limitator**: **Non-limitator, demonstrat direct**.
**Dovezi**: experimentale directe, noi, testate azi.
**Încredere**: Ridicată.

---

## Tabelul final

| Componentă | Impact estimat asupra accuracy | Nivel de încredere | Dovezi existente | Prioritate |
|---|---|---|---|---|
| Imputarea valorilor lipsă (acoperire ELO/rating) | **+4,3pp** (demonstrat, A→D) | Ridicată | Experimentale, semnificative statistic | **Critică** |
| Distribuția ligilor (diluare cu ligi irelevante) | **+2-2,5pp** pe cifrele raportate (efect de măsurare, nu de model) | Ridicată | Experimentale, măsurate azi | **Critică** (pt. interpretare corectă a rezultatelor) |
| Calitatea datelor istorice (secvențiere, duplicate, normalizare) | Cauza rădăcină a rândului de mai sus — nu izolabilă separat numeric | Ridicată | Experimentale, deja existente | **Critică** |
| Dezechilibrul claselor (predicție egal ≈0%) | Necuantificat izolat — problemă transversală, prezentă în toate variantele | Ridicată (pe existență) / Joasă (pe magnitudine) | Experimentale directe | **Majoră** |
| ELO (conceptul, cu acoperire completă) | Feature dominant, de 6-15× peste următorul | Ridicată | Experimentale | Deja acoperit — nu prioritate nouă |
| Feature engineering (intrări sintetice în rating) | Nedemonstrat numeric — doar diagnostic calitativ | Ridicată (diagnostic) / Joasă (magnitudine) | Parțiale | **Majoră**, condiționată de sursă de date |
| `offensive_rating` | Marginal (0,005-0,007) | Ridicată | Experimentale | Minoră |
| `defensive_rating` | ≈0, uneori negativ | Ridicată | Experimentale | Minoră |
| `form_score` | Marginal, uneori negativ | Ridicată | Experimentale | Minoră |
| `h2h_modifier` | Marginal (0,0004-0,0011) | Ridicată | Experimentale | Minoră |
| `home_advantage` | Nedemonstrat separat (absorbit în priorul de clasă) | Joasă | Indirecte | Neclasificabilă cu datele curente |
| `rest_days` | ≈0, deja testat și respins | Ridicată | Experimentale, existente | Închis, non-prioritate |
| Arhitectura XGBoost | **0 sau ușor negativ** — model mai simplu = la fel de bun/mai bun | Ridicată | Experimentale, noi | Non-limitator |
| Procesul de antrenare (hiperparametri, volum) | Volumul contează, hiperparametrii nu | Medie | Indirecte + noi | Non-limitator (pe partea de hiperparametri) |
| Metodologia walk-forward | ≈0 (−0,05pp față de random split) | Ridicată | Experimentale, noi | Non-limitator |

---

## Plafonul realist de acuratețe

**Sinteză a tuturor experimentelor**: pe ligile urmărite efectiv de produs, cu acoperire completă de ELO (singura variabilă cu impact major demonstrat) și fără nicio altă schimbare, acuratețea măsurată azi e **50,86%** (varianta D, restrânsă la cele 11 ligi). Modelul liniar cel mai simplu, pe tot setul (toate ligile), atinge 48,92% — la limita de sus a ce oferă acest set de 10 feature-uri, indiferent de arhitectură.

**Estimare inginerească a plafonului, dacă toate problemele deja demonstrate ar fi rezolvate** (acoperire completă + date istorice consistente + raportare corectă pe ligile relevante, **fără** feature-uri noi nedemonstrate — șuturi/posesie reale rămân nedemonstrate ca sursă, deci nu intră în acest plafon):

**~51-53% acuratețe generală, pe ligile urmărite de produs.**

Motivare, strict pe dovezi: (a) modelul liniar arată deja plafonul de informație al feature-urilor curente, ~48,9% pe tot setul; (b) restrângerea la ligile relevante adaugă +2-2,5pp, măsurat; (c) arhitectura și metodologia nu lasă marjă suplimentară (ambele testate, ambele la plafon); (d) problema egalurilor (≈26% din meciuri, ≈0% acuratețe) rămâne complet nerezolvată de orice combinație testată azi — un câștig aici e teoretic posibil, dar complet nedemonstrat, deci nu-l includ în estimare.

**Acest plafon nu e cu mult peste ce se măsoară deja azi cu varianta D pe ligile relevante (50,86%)** — nu există, în dovezile adunate până acum, un semnal că zeci sau sute de ore suplimentare de lucru pe arhitectură, hiperparametri sau metodologie ar muta acest plafon semnificativ. Singurele pârghii cu impact demonstrat rămân: acoperirea de date (deja cuantificată, +4,3pp) și, nedemonstrat încă, date noi de calitate (șuturi/posesie reale, dacă s-ar găsi o sursă — condiționat, nu garantat).
