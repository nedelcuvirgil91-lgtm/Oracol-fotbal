# ADR-051 — Trei motoare independente de predicție (Vision Shift)

**Status**: ACCEPTED
**Tip**: ADR de viziune arhitecturală (nu o decizie tehnică punctuală) — stabilește un principiu permanent, nu o implementare. Nu conține și nu autorizează cod.
**Precedent direct**: secțiunea „Viziune pe termen lung — Oracle și ML" din `CLAUDE.md` (adăugată 2026-08-03) — acest ADR o extinde și o înlocuiește parțial (vezi §4).
**Fundament tehnic deja existent**: ADR-050 (Challenger Framework generalizat pentru algoritmi compuși) și Pasul 13/14 (Blend Challenger operațional, shadow logging activ) — acest ADR formalizează la nivel de viziune ce era deja adevărat structural în cod de la ADR-050 încoace.

---

## 1. Contextul schimbării

Proiectul a fost construit, implicit, în jurul unei ierarhii: **Oracle e motorul principal; ML e un supliment care ar putea, într-o zi, să-l depășească.** Această ierarhie era deja parțial atenuată de viziunea din `CLAUDE.md` (2026-08-03): ML nu e „experiment abandonat", trebuie să-și genereze propriile predicții independente, afișate permanent în UI, comparabile cu Oracle. Dar formularea rămânea binară — „Oracle vs. ML" — și Blend nu avea statut propriu: era tratat ca mecanism de combinare, nu ca a treia voce a sistemului.

Proprietarul produsului decide explicit schimbarea acestei perspective:

> Oracle, ML și Blend sunt trei motoare independente de inteligență. Niciunul nu este „mai important" prin definiție. Ele concurează permanent.

Aceasta nu e o continuare a viziunii existente — e o schimbare de statut. Diferența exactă:

| | Viziunea veche (`CLAUDE.md`, 2026-08-03) | Viziunea nouă (acest ADR) |
|---|---|---|
| Ierarhie implicită | Oracle primar azi; ML poate deveni primar „într-o zi" | Niciun motor nu e primar prin construcție — poziția de lider e mereu doar un fapt empiric curent |
| Blend | Mecanism de combinare Oracle+ML | Al treilea motor independent, cu identitate proprie |
| ML | Legat de un singur algoritm implicit (XGBoost) | Entitate care învață continuu; XGBoost e primul membru, nu definiția ei |
| Servire live | O singură predicție finală servită | (Viziune, nu implementare încă) trei ieșiri distincte, afișate simultan |

## 2. Decizia

**De acum, Football Oracle nu mai e construit în jurul Oracle Engine. Devine o platformă cu trei motoare independente de predicție, permanent comparabile, dintre care niciunul nu are prioritate structurală.**

### 2.1 Oracle Engine

Expert determinist, bazat pe modele matematice (Poisson, xG, ajustări, reguli, experiență fotbalistică codificată). Produce propria predicție. **Nu este „adevărul"** — e doar una dintre vocile sistemului.

### 2.2 Machine Learning Engine

Nu mai e „XGBoost" — XGBoost e primul algoritm folosit, nu definiția motorului. Machine Learning Engine e o entitate care învață continuu, cu obiectiv distinct de a reproduce Oracle: descoperă tipare noi, observă relații pe care Oracle nu le vede, identifică contexte speciale, estimează risc. Consumă (deja, azi, prin `match_history` și infrastructura Learning Core existentă) toate meciurile istorice, toate feature-urile, toate rezultatele Oracle/Blend/ML/reale. Algoritmul concret (XGBoost azi; CatBoost, LightGBM, rețele neuronale, Transformer, Reinforcement Learning, orice viitor) e un detaliu de implementare per membru — contractul `learning_core.model_registry.LearningAlgorithm` (deja existent, deja generic) e exact abstracția care face asta posibil fără o decizie arhitecturală nouă per algoritm.

### 2.3 Blend Engine

Nu e un compromis provizoriu — e un motor propriu, cu propria identitate. Rolul lui e să combine informația produsă de Oracle și Machine Learning Engine în mod inteligent; poate deveni adaptiv în viitor (pondere de blend învățată, nu fixă). Fundamentul tehnic pentru statutul de „motor independent" există deja: `blend_v1` (ADR-050, Pasul 13/14) e un `algorithm_family` propriu în Model Registry, cu propriul ciclu de viață Challenger, propria antrenare, propriul shadow logging — nu un ramificaj de cod în interiorul Oracle Engine.

### 2.4 Interfața utilizator (viziune, NU implementare autorizată aici)

UI trebuie să afișeze separat, simultan: predicția Oracle, predicția Machine Learning, predicția Blend. Niciun motor nu e ascuns. Operatorul poate compara permanent performanța lor. **Acest ADR nu autorizează nicio modificare de cod pentru asta** — vezi §5.

### 2.5 Învățare continuă

Machine Learning Engine trebuie să învețe continuu, consumând permanent rezultate reale, predicții Oracle, predicții Blend, propriile predicții anterioare, feature-uri istorice și curente — obiectiv deja parțial acoperit de infrastructura Learning Core existentă (ADR-030, Continuous Learning), reafirmat aici ca țintă explicită, nu doar mecanism tehnic.

## 3. Regula obligatorie

Aceasta devine viziunea oficială a proiectului. **Toate deciziile arhitecturale viitoare trebuie să fie compatibile cu ea.** Un document existent care presupune că Oracle e motorul unic sau implicit primar nu se editează tacit — se identifică (§6) și se actualizează printr-un ADR dedicat, la momentul relevant, niciodată „din mers".

## 4. Relația cu viziunea existentă din `CLAUDE.md`

Secțiunea „Viziune pe termen lung — Oracle și ML" din `CLAUDE.md` (2026-08-03) nu e greșită — e incompletă față de decizia de azi. Rămâne valabil, neschimbat: disciplina de a nu trata ML ca experiment abandonat, obligația de învățare continuă, cerința de comparație explicită. Ce se schimbă: (a) Blend capătă statut de motor propriu, nu doar de mecanism; (b) „Oracle rămâne motorul principal" încetează să fie o afirmație de statut implicit — devine strict o observație empirică curentă, valabilă azi, niciodată garantată structural. `CLAUDE.md` se actualizează ca parte a acestui ADR (document viu, neînghețat — vezi `FROZEN_REGISTRY.md`), nu separat, ca să nu rămână contradictoriu față de sursa de adevăr chiar din momentul acceptării.

## 5. Ce NU decide/autorizează acest ADR

Consecvent cu instrucțiunea explicită a proprietarului produsului („următorul pas nu este să scriem cod"):

- **Nicio modificare de cod.** Nu modifică `oracle_engine.py`, `app.py`, `MatchPrediction`, `RUNTIME_CONTRACT.md`, `ML_ACTIVATION_GATE.md`.
- **Nu decide forma tehnică** prin care UI va expune cele trei predicții separat (contract de date nou pe `MatchPrediction`? endpoint separat? Structura exactă rămâne a unui Implementation Plan viitor, dedicat.
- **Nu decide soarta `ml_blending_enabled`** (mecanismul legacy din `oracle_engine.evaluate_match()`, gatat de `ML_ACTIVATION_GATE.md`) — dacă devine parte a noii arhitecturi cu trei motoare, e înlocuit de ea, sau rămâne un mecanism separat — vezi §6, gol identificat, nu rezolvat aici.
- **Nu modifică `RUNTIME_CONTRACT.md`** (Frozen, ADR-019) — orice extindere a servirii live pentru a expune ML/Blend ca ieșiri proprii, separate de Champion-ul `xgboost_v1`, cere un ADR dedicat, separat, care redeschide acel document explicit.
- **Nu schimbă nimic din ce rulează azi în producție** — Oracle rămâne singurul motor care servește predicția live (verificat, Pasul 14: zero Champion promovat, zero blending activ). Acest ADR e o declarație de direcție, nu o activare.

## 6. Goluri identificate — documente/mecanisme care presupun Oracle primar (de actualizat prin ADR-uri viitoare dedicate, NU acum)

Investigație directă în cod/documentație (grep + citire, nu presupunere), per cerința explicită a proprietarului produsului de a identifica, nu neapărat rezolva acum:

| Document/mecanism | Ce presupune azi | Acțiune viitoare necesară |
|---|---|---|
| `CLAUDE.md` §„Viziune pe termen lung — Oracle și ML" | Ierarhie Oracle-primar/ML-succesor, Blend fără statut propriu | **Actualizat ca parte a acestui ADR** (§4) — singurul din tabel rezolvat azi. |
| `docs/00_GOVERNANCE/ML_ACTIVATION_GATE.md` | „Predictorul (Poisson/ELO/formă) rămâne sistemul principal de decizie" (§„Starea curentă") — gatează un mecanism de blend LEGACY (`ml_blending_enabled`, `oracle_engine.py:1553`), distinct de `blend_v1`/Challenger Framework | ADR dedicat: decide dacă acest gate devine gate-ul de activare al noii arhitecturi cu trei motoare, sau rămâne un mecanism separat, învechit. |
| `docs/04_LEARNING_CORE/RUNTIME_CONTRACT.md` (**Frozen**, ADR-019) | Cele 6 condiții de utilizabilitate sunt scrise exclusiv pentru un Champion `xgboost_v1` care alimentează un SINGUR set de probabilități servite | ADR dedicat, obligatoriu (document Frozen) — pentru orice servire live care expune ML/Blend ca ieșiri proprii, separate. |
| `oracle_engine.MatchPrediction` (contract de date) | Un singur set de câmpuri `prob_home_win`/`prob_draw`/`prob_away_win` — nu distinge Oracle/ML/Blend ca ieșiri separate | Implementation Plan viitor, dedicat — extensie de contract, nu decisă aici. |
| `app.py` (UI) | Afișează o singură predicție finală (blend intern, azi neactivat) | Task UI viitor, explicit în afara scopului acestui ADR (§5). |
| **Dualitatea Blend** — descoperire directă, nesemnalată explicit înainte de acest ADR | Există DOUĂ mecanisme de blend distincte azi: (a) blend legacy inline în `evaluate_match()`, gatat de `ml_blending_enabled`, ar influența predicția LIVE dacă activat; (b) `blend_v1` (ADR-050), Challenger independent, strict shadow, nu atinge niciodată predicția live | **Întrebare deschisă, nerezolvată aici**: rămân două mecanisme distincte, sau (a) se retrage în favoarea lui (b) ca unic „Blend Engine"? Decizie pentru un ADR viitor dedicat, NU implicită. |

Acest tabel e rezultatul unei investigații directe (grep pe „motorul principal"/„sistemul principal", citire `oracle_engine.py` liniile 1540-1570, `ML_ACTIVATION_GATE.md` integral) — nu o listă presupusă.

## 7. Consecințe

- **Pozitive**: elimină ambiguitatea despre rolul fiecărui motor pentru orice decizie arhitecturală viitoare; validează retroactiv designul deja ales la ADR-050 (Blend ca `algorithm_family` propriu, nu ramură de cod) ca fiind exact direcția corectă; oferă un criteriu clar pentru a respinge orice propunere viitoare de a simplifica proiectul prin eliminarea ML sau Blend.
- **Negative/costuri acceptate**: creează o listă de documente/mecanisme (§6) care rămân temporar inconsistente cu noua viziune, până la ADR-urile dedicate corespunzătoare — acceptat explicit, nu ascuns.
- **Amânate, deliberat**: toată implementarea tehnică (UI cu trei ieșiri separate, soarta `ml_blending_enabled`, extinderea `RUNTIME_CONTRACT.md`) — subiectul unor ADR-uri/Implementation Plan-uri viitoare, dedicate, separate.

---

**Status**: **ACCEPTED** — 2026-08-04, de proprietarul produsului. Document-only, per instrucțiune explicită („următorul pas nu este să scriem cod") — nicio modificare de cod în acest pas, cu excepția actualizării `CLAUDE.md` §„Viziune pe termen lung" (§4, parte integrantă a acestui ADR, document neînghețat).
