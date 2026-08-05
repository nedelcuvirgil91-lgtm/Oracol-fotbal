# Machine Learning Engine — Viziune World-Class (v2, Deep Research)

**Status**: DRAFT — document de cercetare și arhitectură. NU e un ADR, NU autorizează implementare, NU modifică `FEATURE_COLUMNS`, cod sau configurare. Nicio propoziție de mai jos nu e o instrucțiune de execuție — e o hartă de opțiuni, evaluate.

**Relația cu documentele existente**: acest document nu înlocuiește `ML_ENGINE_ARCHITECTURE_DESIGN.md` (v1) — v1 descrie ce există azi și cum se conectează, pragmatic, la infrastructura curentă (Model Registry, Challenger FSM, `ml_engine.py` propus). Acest document (v2) e un strat separat, orientat spre orizont de ani, nu spre următorul sprint: ce ar însemna, realist, ca ML Engine să devină un sistem de nivel world-class, informat de literatura modernă, cercetare academică, sisteme comerciale și practică Kaggle/open-source — nu de imaginație liberă.

**Precondiție supremă, necontestată aici**: ADR-051 (Three Independent Engines Vision, ACCEPTED). ML Engine e al doilea expert independent — nu copie Oracle, nu modul atașat Oracle, nu înlocuitor Oracle. Nicio propunere din acest document nu folosește ieșirea Oracle ca feature de intrare pentru ML; regula deja aplicată azi (excludere `home_xg_pred`/`prob_*_pred`/`mc_prob_*` din `FEATURE_COLUMNS`, prin ablație reală, importanță 0.0000) rămâne principiul permanent, nu doar o observație istorică. Independența descrisă aici e despre CONTRACTUL extern al ML Engine (ce consumă, ce expune) — structura internă a ML Engine (ansamblu de mai multe modele, §4) e o decizie separată, care nu contrazice ADR-051 în niciun fel.

**Metodologie**: sinteză de cercetare (WebSearch, deep research pe ~12 arii tematice: state-of-the-art în predicția fotbalistică, DeepMind TacticAI, abordări Kaggle, StatsBomb/Opta xG/xT/VAEP, conformal prediction, monitorizare drift la nivel enterprise (Evidently AI), continual/online learning, sisteme Bayesian de rating (Glicko-2/TrueSkill), ansambluri stacking pentru sport, eficiența piețelor de pariuri, graph neural networks pentru fotbal, SHAP pentru gradient boosting) + citire integrală a `ADR-051` și `ML_ENGINE_ARCHITECTURE_DESIGN.md` (v1), pentru a garanta consistență și a evita duplicare. Fiecare secțiune distinge explicit între ce e susținut de cercetare/practică reală și ce e judecată arhitecturală proprie aplicată la contextul specific Football Oracle.

---

## 1. Data Layer

### Ce folosesc cele mai bune sisteme moderne

Sistemele de vârf (cluburi profesioniste, DeepMind TacticAI, StatsBomb/Opta-based research) se bazează, în ordine de valoare informațională:

1. **Date de eveniment** (event data) — fiecare atingere de minge, pasă, șut, tackle, cu coordonate (x,y) și timestamp, per jucător. Stă la baza xG modern, xT (expected threat — StatsBomb), VAEP (Valuing Actions by Estimating Probabilities, biblioteca `socceraction`, ML-KULeuven).
2. **Date de tracking** (poziții optice/GPS, 25fps, jucător + minge) — baza TacticAI (DeepMind, parteneriate Liverpool FC/Palmeiras): geometrie de presiune, linie defensivă, culoare de pasă, hărți de xT continue în spațiu.
3. **Date de piață pe traiectorie** (nu doar cota de închidere) — mișcarea cotei în timp, dispersia între case, viteza mișcării — semnal de "bani inteligenți".
4. **Date de echipă/context** — aliniere confirmată vs. probabilă, accidentări, suspendări, aglomerare de calendar, distanță de deplasare, arbitru desemnat.
5. **Date de piață a jucătorilor** — valoare de transfer (Transfermarkt-style), variație de valoare între sezoane — proxy pentru schimbare de calitate mai rapidă decât ELO (care se mișcă lent, doar din rezultate).

### Ce lipsește complet din Football Oracle

Football Oracle are azi **zero date de eveniment și zero date de tracking** — doar statistici agregate per meci (șuturi, cornere, cartonașe, posesie), și acelea cu acoperire reală de doar 17,1% (verificat live, `ML_ENGINE_ARCHITECTURE_DESIGN.md` §0). Nu există niciun acces, azi, la un provider de event/tracking data (StatsBomb, Opta, Second Spectrum, Skillcorner sunt toate produse comerciale, cu costuri incompatibile cu un proiect personal, sau acces restricționat la cluburi).

### Esențial vs. nice-to-have, ROI mare vs. ROI mic

| Categorie | Cost realist | ROI | Verdict |
|---|---|---|---|
| Populare consecventă `odds_history` (multi-snapshot, nu doar closing) | Zero — infrastructura există deja (ADR-005/006), doar trebuie să ruleze constant | Mare | **Prioritate imediată** — cel mai ieftin gol de închis, deja identificat în v1 §0 pct. 5 |
| Date arbitru (tendințe cartonașe/penalty) | Mic — API-Football are deja acces la arbitri | Mediu-mare | Adoptare realistă, termen scurt |
| Aliniere confirmată (nu doar probabilă) + timing | Mic-mediu | Mediu | Adoptare realistă, termen scurt |
| Valoare de piață jucători/echipă (proxy calitate) | Mic (surse publice, ex. Transfermarkt scraping — verifică termenii de utilizare) | Mediu-mare | Candidat solid, necesită validare de sursă |
| Date de eveniment (StatsBomb-style) | Foarte mare (comercial) sau inaccesibil live | Foarte mare, dar neatins azi | **Nu azi** — orizont 5 ani (§10), doar dacă apare un parteneriat sau un dataset public suficient de mare |
| Date de tracking (poziții optice) | Practic inaccesibil pentru un proiect personal | Foarte mare, dar irelevant fără acces | Exclus din orice roadmap realist pe termen mediu |
| Sentiment social/volum de pariuri alternativ | Mic-mediu | Mic, zgomotos | Nu recomandat — raport cost/beneficiu slab, greu de validat cauzal |

**Concluzie Data Layer**: cel mai mare decalaj față de sistemele world-class nu e algoritmic — e de ACCES la date. Orice discuție despre algoritmi mai buni (§3-§9) e limitată de acest plafon. Recunoașterea explicită a acestui plafon e ea însăși parte din viziune, nu un eșec de ambiție (vezi capitolul de închidere).

---

## 2. Feature Engineering — clasificare completă

Feature-urile moderne nu sunt doar "mai multe statistici" — sunt categorii structural diferite de reprezentare a aceleiași informații brute:

**a. Snapshot la un moment dat** — starea curentă (ELO acum, formă acum). Deja dominant în Oracle/ML azi.

**b. Ferestre glisante (rolling windows)** — formă pe ultimele N meciuri. Azi: un singur N (5), tăiere bruscă. Upgrade simplu: mai multe ferestre simultan (3/5/10/20), lăsând modelul să învețe care fereastră contează în ce context — mult mai ieftin decât pare, calculabil din `match_history` existent.

**c. Ferestre ponderate exponențial (EWMA)** — meciurile recente cântăresc mai mult, fără prag dur, fără saltul brusc de valoare când un meci "cade" din fereastră la trecerea unei zile. Standard în finanțe cuantitative, direct transferabil, ieftin de calculat.

**d. Feature-uri de trend/momentum** — nu nivelul, ci derivata: forma crește sau scade (panta unei regresii liniare pe fereastră, sau diferența EWMA-scurt minus EWMA-lung, analog MACD din analiza tehnică financiară).

**e. Feature-uri de interacțiune** — XGBoost captează implicit interacțiuni prin splituri de arbore, dar interacțiuni explicite, cunoscute a priori (ex. "avantaj gazdă condiționat de forma-deplasare a oaspetelui", sau "diferență ELO × dominanță H2H") pot ajuta când modelul e sărac în date pe acea combinație specifică.

**f. Feature-uri contextuale** — miza meciului (baraj retrogradare, derby, cursă de calificare europeană), aglomerare de calendar (zile de la ultimul meci, meciuri în ultimele 14 zile), probabilitate de rotație a lotului, etapa competiției (grupe vs. eliminatorii).

**g. Feature-uri latente/embeddings** — saltul real modern: în loc de statistici alese manual, o reprezentare vectorială densă a "stilului de joc" al unei echipe, învățată din date (analog word2vec, dar antrenat pe secvențe de rezultate/adversari, nu pe text). Fără date de eveniment, o variantă fezabilă azi: un embedding prin factorizare matriceală a matricei istorice echipă×echipă de rezultate (analog sistemelor de recomandare) — captează afinități stilistice de meci-up dincolo de scalarul unic al ELO.

**h. Feature-uri de graf/rețea** — graful "cine a bătut pe cine" tranzitiv — un rating stil PageRank ca semnal complementar/cross-check la ELO, ieftin de adăugat din `match_history` existent, fără nicio sursă nouă de date.

**i. Feature-uri derivate din piață** — probabilitate implicită din cotă (deja parțial folosit pentru de-vig), dar specific FORMA distribuției cotelor între case (dispersie) ca semnal de incertitudine a pieței, nu doar valoarea de-vig-uită.

**Disciplina de ablație (regulă CLAUDE.md, neschimbată)**: toate cele de mai sus sunt propuneri, nu instrucțiuni — niciuna nu intră în `FEATURE_COLUMNS` fără test de ablație măsurat, exact ca precedentul celor 6 feature-uri deja eliminate prin permutation importance.

---

## 3. Learning — paradigme comparate

| Paradigmă | Ce înseamnă | Potrivire cu Football Oracle | Verdict |
|---|---|---|---|
| **Batch learning** | Reantrenare completă, de la zero, la fiecare ciclu | Starea de azi — simplu, sigur, compatibil walk-forward | **Păstrat ca ancoră** — nu se elimină, e baza de siguranță |
| **Incremental learning** | Continuare a antrenării existente (`xgb_model=` warm-start) doar pe date noi | Reduce compute, permite actualizare mai frecventă fără retrain integral | Adoptare realistă, 1-2 ani, cu retrain complet periodic ca "ancoră" împotriva acumulării de drift |
| **Online learning** | Actualizare per-eșantion, după fiecare rezultat nou | Nepotrivit — rata de evenimente (câteva sute de meciuri/zi pe TOATE ligile urmărite, mult mai puțin per ligă) e mult prea mică pentru a justifica varianța și riscul suplimentar | **Respins** — fără caz de utilizare real |
| **Active learning** | Selectarea inteligentă a ce merită etichetat/colectat | Reformulare utilă: nu "ce meci merită etichetă" (rezultatele sunt gratuite, din sync), ci "ce feature auxiliar merită efort de colectare, pentru ce meciuri" — se mapează direct pe golul deja documentat (17,1% acoperire stats derivate) | **Adoptare, în forma reformulată** — prioritizare a efortului de colectare Flashscore, nu a etichetelor |
| **Continual learning** | Prevenirea "uitării catastrofale" la actualizare online a unei rețele neuronale | Irelevant azi (familia de model e bazată pe arbori, care nu "uită" în sensul rețelelor neuronale) | Devine relevant DOAR dacă/când apare o componentă neuronală (embeddings, §2g/§5) — semnalat ca tehnică de rezervă (replay buffer, EWC, izolare arhitecturală), nu ca nevoie azi |
| **Transfer learning** | Pre-antrenare pe ligi bogate în date, adaptare/fine-tuning pe ligi sărace | Se mapează direct pe cea mai reală durere a proiectului azi: fragmentarea pe ligi și "cold start"-ul ligilor noi (Croatia HNL, Romania SuperLiga, orice ligă viitoare) | **Cea mai mare pârghie pe termen scurt** — orice feature de tip embedding (§2g) trebuie antrenat pooled, pe toate ligile, exact pentru ca ligile noi/mici să beneficieze imediat de transfer, nu să aștepte ani de istorie locală |

---

## 4. Ensemble — în interiorul ML Engine

**Precizare de contract, obligatorie**: discuția de mai jos e despre structura INTERNĂ a ML Engine — câte modele conține, cum le combină. Independența ADR-051 (Oracle/ML/Blend ca motoare separate, niciunul nu consumă ieșirea celuilalt ca intrare) e despre CONTRACTUL EXTERN al ML Engine, nu despre câte modele are înăuntru. Un ML Engine intern-ansamblist rămâne, extern, o singură voce independentă — exact cum Blend Engine e deja, azi, o combinație de Oracle+ML intern la propriul strat, fără să înceteze să fie un motor propriu (ADR-050).

**Recomandare**: da, mai multe modele, combinate printr-un strat meta principial — nu unul singur.

- **Bagging** — prioritate mică; XGBoost include deja regularizare stil-bagging (subsample/colsample) intern.
- **Boosting** — deja algoritmul de bază; poate extinde la un "portofoliu" de configurații boosted (hiperparametri diferiți / subseturi de feature-uri diferite) combinate ulterior.
- **Modele specialist / experți pe ligă** — modele separate per cluster de ligi (ex. "model big-5" vs. "model ligi mici"), cu fallback pe modelul general/transfer (§3) pentru ligile sărace în date — adresează direct fragmentarea deja documentată.
- **Stacking** — un meta-model (tipic regresie logistică sau un model mic) antrenat pe predicțiile out-of-fold ale mai multor modele de bază (specialiști + model general + baseline din probabilitatea implicită de piață) — abordarea standard de top din practica Kaggle documentată în cercetare.
- **Blending** — variantă mai simplă a stacking-ului, pe un set de validare temporal ținut deoparte, fără riscul de scurgere de informație între folduri — dat fiind disciplina walk-forward strictă a proiectului (CLAUDE.md, regulă #7), blending pe un holdout temporal e mai sigur decât stacking pe k-fold și ar trebui preferat practic, chiar dacă stacking-ul e mai eficient pe eșantion.
- **Voting** — prea grosier (ignoră diferențele de calitate de calibrare între modelele de bază) — **respins** ca mecanism final de combinare; util doar ca verificare rapidă de sanitate în dezvoltare.
- **Strat de calibrare** — indiferent de combinarea aleasă, un pas final de calibrare (Temperature Scaling — deja decis prin ADR-049, neimplementat încă; izotonic regression ca alternativă la volum mare de date) trebuie să stea DUPĂ ansamblu, nu doar după modelul de bază — decizia ADR-049 existentă se generalizează natural la scorul combinat.

**Arhitectură internă recomandată (descriptivă, nu implementare)**: 2-3 modele specialist/general care alimentează un meta-combinator blended (holdout temporal), urmat de un strat final de calibrare — totul învelit de fațada unică `ml_engine.py` deja propusă în v1, fără nicio schimbare a contractului extern.

---

## 5. Temporal Intelligence

**Limitele "formei pe ultimele 5 meciuri"**: prag dur, ponderare uniformă, fără ajustare pentru puterea adversarului, fără structură de decădere, fără distincție între schimbare de lot și schimbare de formă reală.

**Alternative moderne**:

- **EWMA / formă ponderată exponențial** (§2c) — upgrade imediat, ieftin.
- **Sisteme de rating cu dinamică temporală încorporată** — **Glicko-2** adaugă un termen de "deviație a ratingului" care se LĂRGEȘTE în perioade de inactivitate și se ÎNGUSTEAZĂ cu mai multe meciuri jucate — dă structural un semnal de incertitudine temporală pe care ELO nu-l are. **TrueSkill** (Bayesian, gestionează dinamici multi-competitor) converge mai rapid după pauze lungi. Cercetare recentă (rating-uri fotbalistice bazate pe Glicko-2) arată performanță competitivă sau superioară ELO la scară mică-medie de date — exact regimul Football Oracle pentru ligile noi/mici. Concret: deviația de rating Glicko-2 e ea însăși un feature de "încredere temporală" utilizabil, complementar cu §6.
- **Modele de secvență peste istoricul de meciuri** — tratarea secvenței de meciuri a unei echipe ca serie temporală, cu un model ușor (convoluție temporală sau atenție mică peste ultimele N meciuri, cu ponderare ÎNVĂȚATĂ, nu aleasă manual) — alternativa modernă la ingineria manuală a "formei", cu costul unei lungimi de secvență suficiente per echipă; realist doar după ce infrastructura de embeddings (§2g) există.
- **Propagare pe graf, sensibilă la recență** — un semnal de "formă" derivat dintr-o versiune decăzută temporal a grafului de echipe (§2h) — PageRank recalculat pe o fereastră glisantă, decăzută, nu pe tot istoricul — captează momentum tranzitiv ("a bătut o echipă care tocmai a bătut o echipă în formă") pe care un scalar de formă nu-l poate.
- **Efecte de sezonalitate/calendar** — aglomerare de calendar, parte din sezon (zgomot de început de sezon vs. stabilitate de final) — mai bine ca feature-uri contextuale explicite (§2f) decât împachetate în "formă".

---

## 6. Confidence — un model care știe când nu știe

Diferența de reținut: **calibrarea** (corectitudinea medie a încrederii declarate, peste multe predicții) e diferită de **incertitudinea per-meci** (acest meci specific merită încredere mare sau mică?).

- **Conformal prediction** — fără presupuneri de distribuție, agnostic de model, produce SETURI de predicție cu acoperire garantată (ex. "90% din timp rezultatul real e în acest set") în loc de un singur triplet de probabilități — dă direct o cale principială de a spune "încredere insuficientă pentru un singur rezultat" pentru meciurile unde setul conformal include 2+ rezultate cu masă semnificativă. Inferența conformală adaptivă (cercetare recentă, "conformal prediction by betting") gestionează explicit deriva de distribuție în timp — relevant pentru un sport live, în evoluție. Valoare mare, risc arhitectural mic — se înfășoară în JURUL oricărui model existent (nu cere înlocuirea XGBoost), unul dintre cele mai bune raporturi valoare/risc disponibile.
- **Dezacord de ansamblu** — spread-ul între modelele specialist interne (§4) ca semnal nativ de incertitudine — gratuit, dacă ansamblul propus e deja construit.
- **Entropie/varianță predictivă** — simplu, deja calculabil din output-ul curent tip softmax, azi nefolosit ca semnal.
- **Detecție de noutate/out-of-distribution** — semnalarea meciurilor "fără precedent" (echipă nou-promovată, gol mare de date, meci între regimuri de rating radical diferite) prin distanța față de distribuția de antrenare (scor k-NN sau bazat pe densitate în spațiul de feature-uri) — operaționalizează direct principiul CLAUDE.md de a nu aproxima niciodată o stare necunoscută — e implementarea pe partea ML a aceluiași principiu deja aplicat lui `supported: "necunoscut"` din ADR-001.
- **Bayesian last-layer / ansambluri de rețele adânci** — semnalat ca tehnică de orizont lung, doar dacă apare o componentă neuronală.

**Țintă recomandată, termen scurt**: înfășurare conformal prediction + flag de noutate/OOD — ambele adaosuri externe, care nu ating modelul de bază, ambele servind direct scopul "modelul își recunoaște limitele" fără să schimbe `FEATURE_COLUMNS` sau disciplina de antrenare.

---

## 7. Explainability

- **SHAP (TreeSHAP specific)** — calcul EXACT în timp polinomial pentru ansambluri de arbori (nu o aproximare, spre deosebire de SHAP agnostic de model) — alegerea corectă implicită pentru un motor bazat pe XGBoost, deja standardul în literatura de sport-analytics revizuită. **Recomandat ca instrument principal.**
- **LIME** — agnostic de model, local, aproximativ (bazat pe perturbare) — inferior TreeSHAP specific pentru modele de arbori (mai lent, mai puțin exact) — nerecomandat ca instrument principal dat fiind familia de model; rămâne o verificare încrucișată dacă ansamblul crește cu componente non-arbore.
- **Atribuire de feature-uri (globală)** — deja parțial prezentă în spirit prin analiza permutation-importance existentă (`PREDICTOR_ROADMAP_V4.md` §2.3) — upgrade recomandat de la permutation importance la SHAP, care dă și atribuiri LOCALE (per predicție), nu doar clasament global.
- **Explicații counterfactuale** ("ce ar trebui să se schimbe ca predicția să se inverseze") — valoros pentru un caz concret de produs: explicarea utilizatorului final de ce ML nu e de acord cu Oracle pe un meci ("dacă forma-deplasare a oaspetelui ar fi cu o treaptă mai bună, ML ar comuta spre Egal") — cost de inginerie mai mare, poziționat ca element de roadmap pe termen mai lung (§10).

**Ce merită implementat curând vs. nu**: TreeSHAP (global + local) = valoare mare, cost mic, implementare timpurie. LIME = omis. Counterfactuale = amânat spre anul 2, odată ce cazul de utilizare UI/produs e concret definit (decizie de produs la fel de mult ca una ML, în afara scopului unui document pur arhitectural).

---

## 8. Monitoring — nivel enterprise

Taxonomie explicită a modurilor de eșec (cadru din industrie, ex. Evidently AI):

| Tip de derivă | Ce înseamnă | Detectabil prin |
|---|---|---|
| **Data drift** | Distribuția feature-urilor de INTRARE se schimbă (ex. după o ligă nouă, sau un provider care schimbă modul de raportare) | Population Stability Index / test KS per feature, față de distribuția de la antrenare |
| **Concept drift** | Relația dintre feature-uri și rezultatul real se schimbă (ex. schimbare de regulament, schimbare de arbitraj) | Indirect — degradarea metricilor live pe o fereastră glisantă, relația reală nefiind observabilă direct |
| **Feature drift** | Sub-caz specific, scopat la un singur feature ingineresc (ex. chiar creșterea organică a acoperirii statisticilor derivate schimbă tiparul de lipsă — risc de monitorizat explicit, dat fiind golul deja documentat) | Monitorizare per-feature dedicată |
| **Prediction drift** | Distribuția OUTPUT-ului probabilistic al modelului se schimbă, independent de acuratețe | Ieftin — nu necesită rezultate de meci, doar predicțiile în sine — semnal de avertizare timpurie |
| **Calibration drift** | Brier/Log-loss/reliability-diagram se degradează pe o fereastră glisantă chiar dacă acuratețea brută pare stabilă | Cea mai relevantă metrică pentru filosofia anti-"doar-acuratețe" a proiectului |
| **Confidence drift** | Modelul devine sistematic supra- sau subîncrezător în timp | Distinctă de calibration drift — se uită specific la spread/entropie, nu la corectitudine |

**Practică din industrie**: platforme dedicate de observabilitate ML există (Evidently AI, open-source, adoptare largă, nativ Python) — teste statistice (PSI, KS, distanță Wasserstein) per feature, dashboard-uri, praguri de alertare automate.

**Recomandare pentru Football Oracle**: un strat NOU, read-only, de observabilitate, care oglindește conceptual taxonomia de mai sus (dacă biblioteca Evidently însăși e adoptată e o decizie de implementare, în afara scopului aici), explicit DOWNSTREAM de Champion Guardian (deja construit, ADR-037 R2) — Champion Guardian și acest strat sunt complementare, nu duplicate: Champion Guardian răspunde "e campionul suficient de sănătos ca să continue să servească", acest strat răspunde "de ce, pe care din cele 6 axe de derivă, dacă nu". Păstrează North Star #10 (nicio dependință în sus): stratul de monitorizare citește aceleași semnale pe care Champion Guardian le citește deja, nu adaugă nicio cale nouă de scriere.

---

## 9. Self-Improvement — fără uman în buclă, dar fără auto-promovare

Distincție explicită, cerută direct: "self-improvement" ≠ cadență de reantrenare. Mecanisme reale, din cercetare/industrie:

- **Re-evaluare automată a relevanței feature-urilor** — rulare periodică programată a procesului de ablație/permutation-importance ÎN SINE (nu doar reantrenarea ponderilor), pentru a prinde feature-uri utile la lansare dar decăzute în relevanță (sau invers, un feature deja respins — ex. `rest_days_modifier` — devenind relevant după o schimbare de regim de date) — un proces de RE-VALIDARE programat, nu un retrain.
- **Re-căutare automată de hiperparametri declanșată de semnale de derivă (§8)**, nu pe calendar fix — ex. rulare Optuna nouă doar când calibration drift trece un prag, nu "la fiecare N zile" — leagă direct self-improvement de stratul de monitorizare, alternativa concretă la "retrain zilnic".
- **Căutare de arhitectură condusă de Challenger** — FSM-ul Challenger existent (deja construit, ADR-016) e el însuși un mecanism de self-improvement dacă scopul i se extinde dincolo de schimbări de parametri, la variante STRUCTURALE (subseturi de feature-uri diferite, configurații de ansamblu diferite din §4) care concurează ca challengeri — reutilizează infrastructură existentă în loc să propună ceva nou; "self-improvement"-ul vine din a face generarea de Challenger mai sistematică (ex. o căutare programată peste spațiul subset-feature-uri/configurație-ansamblu), nu doar challengeri autorați de om.
- **Meta-learning peste experimentele trecute** — Experiment Registry (deja înregistrează fiecare decizie de Challenger/promovare) e el însuși un set de date — idee de orizont lung (2+ ani, §10): antrenarea unui meta-model ușor pe ISTORICUL experimentelor trecute, pentru a prezice care configurații viitoare au șanse mai mari de succes, reducând ciclurile de Challenger irosite — analog direct cercetării de learning-to-learn/meta-learning pentru căutare de hiperparametri, poziționat realist ca element de roadmap de cercetare, nu construcție pe termen scurt.
- **Bucle de feedback pentru calitatea datelor** — semnalarea automată a regresiilor de calitate a datelor (ex. un provider care schimbă tacit formatul de raportare, exact ce s-a întâmplat deja istoric) ca declanșator de re-validare, în loc să aștepte ca un om să observe o scădere de performanță.

**Non-obiectiv explicit, respectând ADR-002**: nimic din acest paragraf implică auto-promovare fără om în buclă. "Self-improvement" înseamnă aici CANDIDAȚI mai buni și DIAGNOSTIC mai bun ajungând la om mai rapid și mai sistematic, niciodată eliminarea deciziei umane de promovare.

---

## 10. Research Roadmap

**Principiu de ordonare, explicit**: se închid golurile structurale/de guvernanță ÎNAINTE de orice extindere de capacitate (regula Discovery + disciplina ADR deja existente în proiect), apoi se prioritizează după (ROI/cost), nu după noutate — conformal prediction și SHAP se clasează deasupra embeddings și GNN-urilor tocmai PENTRU CĂ sunt adaosuri aditive peste modelul existent, nu cer date noi sau algoritmi noi.

- **6 luni**: închiderea celor 2-3 goluri structurale deja identificate în v1 (ADR pentru `RUNTIME_CONTRACT.md`, bug-ul de cuplare la 2 motoare din `consensus_validation.compute_metrics()`, fațada `ml_engine.py`) — APOI cele mai ieftine, mai valoroase elemente din acest document: upgrade feature-uri EWMA/ferestre glisante (§2), explicabilitate TreeSHAP (§7), înfășurare conformal prediction (§6), taxonomie de monitorizare stil Evidently (§8) — toate aditive, toate reversibile, niciuna atingând `FEATURE_COLUMNS` fără ablație.
- **1 an**: transfer learning peste ligi (§3) pentru problema de fragmentare/cold-start a ligilor noi, Glicko-2/TrueSkill ca semnal de rating complementar ELO (§5), modele specialist/experți pe ligă + ansamblu stacking/blending (§4) odată ce există suficient istoric shadow-testat pentru a valida corect pasul de combinare, feature-uri de piață derivate din `odds_history` devenind semnal real pe măsură ce stratul de persistare acumulează mai mult istoric (§1).
- **2 ani**: feature-uri de graf/rețea (§2h, §5) complet productizate, active-learning-ca-prioritizare-de-colectare (§3) formalizat pentru a ghida unde merge următorul efort de acoperire Flashscore/statistici, scopul Challenger extins la căutare structurală/de arhitectură (§9), explicații counterfactuale (§7) dacă cazul de utilizare de produs s-a maturizat.
- **5 ani**: reevaluarea achiziției de date de eveniment/tracking (§1) — până atunci, fie devine viabil un parteneriat de date plătit pentru un proiect matur, fie seturile de date publice/de cercetare (StatsBomb open data s-a extins istoric) pot închide parțial golul — feature-uri latente/embeddings (§2g) și modele de secvență (§5) devin viabile în acest punct, dat fiind suficient istoric propriu acumulat pentru a le antrena bine; acesta e și punctul la care o primă evaluare reală a componentelor de arhitectură neuronală (cu tehnicile de continual learning semnalate în §3) merită revizitată, nu mai devreme.

---

## Capitol de închidere: "Dacă Football Oracle ar fi construit azi de DeepMind, OpenAI sau Google Research"

**Ce ar face diferit**: ar porni de la date de eveniment/tracking ca cetățean de prim rang (întreaga propunere de valoare a TacticAI se bazează pe date poziționale pe care Football Oracle nu le are și probabil nu le va avea) — ar trata problema ca deep learning geometric (rețele neuronale de graf peste poziții de jucători/minge, arhitecturi stil HIGFormer/TacticAI) mai degrabă decât ca gradient boosting tabular.

**Tehnologii**: GNN-uri peste date de tracking jucător/minge, modele de secvență tip transformer peste fluxuri de evenimente/meciuri, pre-antrenare auto-supervizată la scară mare pe tot filmul/log-urile de evenimente disponibile (analog modului în care modelele fundamentale de viziune/limbaj sunt pre-antrenate apoi fine-tunate) — cadrul "model fundamental pentru fotbal", care învață reprezentări generale ale jocului, apoi se adaptează la sarcini specifice, predicția rezultatului fiind doar una dintre ele.

**Ce NU ar face**: nu s-ar obseda cu "formă pe ultimele 5 meciuri" inginerite manual sau delta-uri ELO — acestea sunt proxy-uri limitate de plafon, utile specific PENTRU CĂ date mai bune nu sunt disponibile; un laborator cu acces la date de tracking tratează statisticile de tip box-score ca semnal legacy/de fidelitate joasă, nu ca țintă de rafinare nesfârșită.

**Compromisuri care ar rămâne, chiar și pentru ei**: latență/cost de date în timp real, stocasticitatea fundamentală a fotbalului (sport cu scor mic, varianță mare — punct de consens în cercetare, inclusiv literatura de eficiență a piețelor de pariuri, că există un plafon de Brier/Log-loss atins indiferent de sofisticarea modelului, pentru că cea mai mare parte a varianței rezultatului e zgomot ireductibil genuin, nu semnal nemodelat) — chiar propriul paper TacticAI al DeepMind e validat prin PREFERINȚA EXPERTULUI UMAN (90% din timp un expert uman nu a putut distinge/a preferat sugestia tactică TacticAI), nu prin bătutul caselor de pariuri direct — un punct de referință care umple de smerenie, real.

**Ce poate adopta realist Football Oracle în anii următori, fără bugetul unui laborator**: tot ce e în roadmap-ul 6luni-2ani de mai sus (conformal prediction, SHAP, transfer learning peste ligi, Glicko-2, ansambluri stacking, rating-uri bazate pe graf de echipe din `match_history` existent) — toate acestea sunt exact ideile "GNN/transformer de laborator" SCALATE la ce e atins fără date de tracking: un graf de echipe e un graf (crud, fără detaliu de jucător); un feature EWMA/trend e un model de secvență (crud, fără reprezentare învățată); conformal prediction e literalmente același instrument pe care l-ar folosi și un laborator bine finanțat, doar aplicat unui model de bază mai simplu. Decalajul spre "world-class" e real și e mai ales despre ACCESUL LA DATE, nu despre sofisticare algoritmică pe care Football Oracle n-o poate atinge — asta reformulează onest ambiția: închiderea golului de date (date de eveniment/tracking, §1, orizont 5 ani) e blocajul real, nu arhitectura modelului.

---

## Notă finală

Acest document nu autorizează nimic. Fiecare element menționat rămâne, până la un ADR dedicat sau o decizie explicită a proprietarului produsului, doar o opțiune evaluată — exact regula "Discovery" și disciplina ADR deja stabilite în `CLAUDE.md`. Niciun element de mai sus nu propune folosirea ieșirii Oracle ca intrare pentru ML, nu transformă ML într-o copie/modul atașat Oracle, și nu contrazice ADR-051 în vreun punct.
