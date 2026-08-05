# Design Review — Principal/Staff+ — ML Platform Architecture (v4)

**Subiect**: `docs/04_LEARNING_CORE/ML_PLATFORM_ARCHITECTURE_V4.md` (v4, straturile de platformă), cu referințe inevitabile la `ML_ENGINE_SYSTEM_ARCHITECTURE_V3.md` (v3) unde v4 moștenește direct afirmații de acolo (Serving Wrapper, regula celor 2 canale de comunicare, "evoluează fără refactorizări majore").

**Postură**: acest review NU presupune că v3/v4 sunt corecte doar pentru că au fost verificate contra codului real la momentul scrierii — verificarea faptelor citate (nume de funcții, linii de cod) nu e aceeași proprietate cu corectitudinea RAȚIONAMENTULUI arhitectural construit pe ele. Cele două se evaluează separat mai jos.

**Verdict, pe scurt, înaintea detaliilor**: documentul e neobișnuit de bine ancorat factual (citate verificate, nu presupuse) — asta e o calitate reală, rară. Dar taxonomia de "8 straturi" are o slăbiciune conceptuală reală (amestecă straturi secvențiale cu preocupări transversale sub aceeași etichetă), documentul alunecă între nivel de arhitectură și nivel de audit-de-cod fără s-o recunoască explicit, și nu discută deloc riscul cel mai probabil de rupere pe termen mediu (orchestratorul unic, `oracle_engine.py`, ca punct de coupling liniar-în-număr-de-motoare). Detaliile, mai jos.

---

## 1. Arhitectura generală

### 1.1 Modelul mental — "8 straturi" ca metaforă

**⚠️ Parțial corect.** Documentul alege explicit să numească straturile după RESPONSABILITATE ("Feature Layer răspunde la...") nu după strat de implementare — alegere corectă, declarată onest (§1 din v4). Problema nu e alegerea inițială, e execuția ei inconsistentă: nu toate cele 8 "straturi" sunt de fapt același TIP de lucru.

- **Feature/Dataset/Experimentation/Training/Promotion/Serving** — acestea SUNT, defensibil, faze într-un flux (chiar dacă nu strict secvențial, vezi 1.2) — au sens ca "straturi" în sensul clasic (fiecare consumă ieșirea celui anterior).
- **Monitoring** — NU e o fază secvențială după Serving. Monitoring observă TOATE celelalte straturi (drift de date = Dataset Layer, drift de feature = Feature Layer, drift de predicție = Serving Layer). Documentul însuși recunoaște asta implicit când spune, la §8, că lipsește "monitorizare... distinctă de sănătatea unui singur Champion" — dar nu trage concluzia arhitecturală corectă: Monitoring nu aparține unei poziții fixe în diagramă, e transversal, exact ca Governance.
- **Governance** — documentul ÎL desenează deja transversal (§10, banda orizontală "traversează toate straturile") — corect, dar atunci de ce Monitoring nu primește același tratament? Inconsecvență directă în propriul document: două concepte cu aceeași natură (transversal, nu secvențial) sunt tratate diferit în diagramă, unul ca bandă orizontală, celălalt ca ultima cutie dintr-un lanț vertical.

**Concluzie**: nu 8 straturi omogene — cel puțin 6 straturi secvențiale + 2 preocupări transversale (Governance, Monitoring), care ar fi trebuit modelate diferit, nu înșirate în același tabel de la §1.

### 1.2 Layering — direcția de dependență e reală, dar diagrama de flux nu

**❌ Greșit** (aspect specific, nu tot documentul): diagrama din §10 desenează `Experimentation Layer` ÎNTRE `Dataset Layer` și `Training Layer` — implicând că experimentarea se întâmplă ÎNAINTE de/independent de antrenare. Asta contrazice direct ce descriu v1 §7 și v3 §3.4-3.5 (deja citate ca sursă în v4 însuși): Challenger FSM evaluează un candidat DUPĂ ce a fost antrenat, prin shadow testing pe meciuri reale, în PARALEL cu Serving-ul curent — nu ca o fază premergătoare Training-ului. Fluxul real e Training → (candidat antrenat) → Experimentation (shadow, concurent cu Serving) → Promotion, nu Feature→Dataset→Experimentation→Training liniar cum arată diagrama.

Aceasta nu e o nuanță minoră — pentru un document care pretinde explicit "arhitectură de sistem, nu design de implementare", ordinea corectă a fluxului de control E arhitectură, nu detaliu.

### 1.3 Bounded contexts

**⚠️ Parțial corect, cu o gaură reală.** Secțiunea 4 din v4 identifică ea însăși, explicit, DOUĂ bounded context-uri diferite în ce numește "Experimentation Layer" — traseul Challenger-vs-Champion (decizie de promovare) și Consensus Validation (cercetare de ipoteză, ADR-033) — și chiar spune "notă structurală importantă, negăsită explicit numită în v1/v2/v3". Corect identificat. Dar apoi **nu trage consecința**: dacă sunt cu adevărat două bounded context-uri diferite (scop diferit, ciclu de viață diferit, un traseu gatează producția, celălalt doar propune cercetare), de ce sunt prezentate sub UN SINGUR nume de strat în taxonomia de 8? Fie taxonomia ar trebui să aibă 9 intrări, fie documentul ar trebui să explice explicit de ce le tratează ca un singur bounded context cu două implementări — nu face niciuna din cele două, doar le enumeră consecutiv sub același titlu.

**✅ Confirmat**, în schimb, separarea Promotion/Serving: verificat independent (champion_loader.py nu scrie, promotion_service.py nu servește) — aici bounded context-ul e real și respectat corect, cu graniță de scriere/citire clară.

### 1.4 Separarea responsabilităților

**✅ Confirmat** pentru Training/Promotion (Model Registry nu decide promovare, Promotion Engine nu antrenează) — verificat direct, genuin bine separat.

**⚠️ Parțial corect** pentru Serving: v3/v4 propun ca `oracle_engine.py` să rămână "orchestratorul unic" care cunoaște toate motoarele. Asta E o separare de responsabilități la nivel de COMPONENTE (Blend nu cunoaște Oracle, ML nu cunoaște Blend) — dar concentrează o responsabilitate diferită, de ORCHESTRARE, într-un singur fișier care crește liniar cu numărul de motoare (vezi §6 mai jos). Separarea "orizontală" (între motoare) e reală; separarea "verticală" (orchestratorul însuși nu are o responsabilitate unică, ci acumulează una nouă per motor adăugat) nu e discutată deloc.

---

## 2. Consistența internă

### 2.1 Contradicție de ton — §11 vs. restul documentului

**⚠️ Parțial corect / retoric, nu factual.** §11 din v4 ("Observație centrală de platformă") afirmă cu încredere că platforma e deja generică, validată empiric de 2-3 clienți — adevărat, verificat. Dar formularea ("platforma nu a fost construită pentru ML — a fost construită generic") sună ca o concluzie de închidere, imediat urmată de §12, un tabel care listează 4 lipsuri REALE (Dataset Registry, Feature Store, traseu de experimentare pentru feature-uri, monitorizare de drift) plus, din v3, un blocaj de guvernanță neînchis. Nu e o contradicție factuală — dar e o inconsecvență de ton: documentul sună mai încheiat decât e, imediat înainte de propriul tabel de lipsuri. Un cititor care se oprește la §11 pleacă cu impresia greșită.

### 2.2 Concepte care se suprapun — Champion Comparison vs. Shadow Testing

**❌ Găsit, netratat de document.** `champion_comparison.py` (§6 din v4) compară metrici walk-forward ale unei antrenări noi cu Champion-ul activ — pur informativ. `shadow_testing.evaluate_experiment()` (§4/§6, Challenger FSM) compară un Challenger cu Champion-ul, pe date LIVE, cu criteriu de promovare. Ambele răspund la întrebări adiacente: "e candidatul mai bun?" Documentul citează ambele componente ca reutilizabile, fără să pună întrebarea evidentă: **e `champion_comparison.py` cod încă folosit activ, sau infrastructură rămasă dintr-o fază anterioară (ADR-015) suprapusă/înlocuită de Challenger FSM (ADR-016+), mai riguros?** Dacă răspunsul e "suprapusă", asta e datorie tehnică reală (două căi care răspund la aceeași întrebare, cu rigoare diferită) pe care documentul o clasifică drept "matur, reutilizabil" fără să investigheze suprapunerea. Nu am verificare directă în această sesiune dacă e cod mort sau activ — semnalez întrebarea, nu răspunsul, exact genul de lucru pe care un document care pretinde "verificat, nu presupus" ar fi trebuit să-l verifice înainte de a clasifica componenta drept sănătoasă.

### 2.3 Afirmații incompatibile — niciuna găsită la nivel factual

Nu am găsit nicio pereche de afirmații factuale direct contradictorii (ex. un tabel spune X e generic, altul spune X e hardcodat pe un algoritm) — spre deosebire de secțiunea 2.1/2.2, care sunt probleme de framing/completitudine, nu de fapte contrazise.

---

## 3. Nivelul de abstractizare

**⚠️ Parțial corect — amestec nedeclarat.** Documentul pretinde explicit "arhitectură de sistem, nu design de implementare" (header, ambele v3 și v4). Dar citează, direct: semnătura exactă `get_training_data(only_with_results: bool = True)`, linia de cod `a, b = engines[0], engines[1]`, numele exacte ale celor 8 funcții din `feature_engine.py`. Acestea sunt citate de audit de cod, nu de arhitectură — o diagramă de arhitectură reală ar descrie "un modul de transformare feature, pur, fără I/O" fără să enumere cele 8 nume de funcție.

**Nu e neapărat o greșeală** — pentru un proiect cu istoricul ăsta specific (regula explicită "verificat, nu presupus" din CLAUDE.md), ancorarea în citate de cod concrete e ce dă documentului credibilitate față de v1/v2 (care au fost, corect, criticate în v3 pentru o diagramă care nu funcționa cum era desenată). Dar **documentul nu recunoaște explicit acest compromis** — pretinde nivel de arhitectură pură, în timp ce practică un hibrid arhitectură+audit. Un cititor care ia titlul literal ("nu design de implementare") și găsește linii de cod citate la fiecare pas primește un semnal mixt despre ce fel de document citește.

**💡 Bună idee dar incompletă**: soluția corectă nu e eliminarea citatelor de cod (ar reintroduce exact problema pe care v3 a criticat-o la v1 — afirmații nesusținute) — e etichetarea explicită a fiecărei afirmații ca "verificat prin citire de cod" vs. "concluzie arhitecturală derivată" — o distincție pe care documentul o face IMPLICIT (prin ton), nu STRUCTURAL (prin marcaj).

---

## 4. Ce lipsește — structural, nu detalii

### 4.1 Train/serve skew — absent complet

**❌ Lipsă reală, negăsită nicăieri în v3/v4.** Niciuna din cele 8 secțiuni de strat nu discută dacă ACELAȘI cod de calcul al feature-urilor rulează garantat identic la antrenare și la servire live. Acesta e, empiric, una dintre cele mai frecvente cauze de eșec în producție pentru orice platformă ML din industrie — și nu apare nici măcar ca întrebare în §2 (Feature Layer) sau §7 (Serving Layer). Dataset Registry (§3) rezolvă o problemă adiacentă (ce date exact a văzut antrenarea) dar NU rezolvă dacă transformarea feature aplicată la servire e garantat aceeași funcție/versiune cu cea aplicată la antrenare. Gaură structurală reală, nu detaliu.

### 4.2 `league_scope` ca dimensiune transversală, tratat inconsistent

**⚠️ Parțial corect, tratament incomplet.** `league_scope` apare ca gap doar la §7 (Serving Layer — "niciun mecanism de servire pentru mai mult de un league_scope simultan cu strategii diferite"). Dar Dataset Layer, Feature Layer, și Monitoring Layer au, verificat în alte documente ale acestui proiect (fragmentarea identității de ligă, acoperire foarte inegală între ligi mari/mici), exact aceeași problemă structurală — nu doar Serving. Documentul tratează `league_scope` ca pe o problemă locală unui singur strat, când e, evident din propriul context al proiectului, o dimensiune care traversează tot.

### 4.3 Guvernanță de resurse/cost — complet absentă

**❌ Lipsă reală.** Governance Layer (§9) discută exclusiv guvernanța de DECIZIE (cine aprobă ce) — zero mențiune despre guvernanța de RESURSĂ: cost de antrenare (crește cu volumul de date, cu numărul de `algorithm_family`), cost de stocare artefacte model (crește cu `algorithm_family × league_scope × versiuni`), buget de compute pentru shadow testing paralel pe mai mulți candidați simultan. Pentru o întrebare care include explicit "ce se întâmplă cu 5 algoritmi/10 ligi/20M meciuri în plus" (§6 al acestui review), lipsa asta devine relevantă direct, nu doar teoretic.

### 4.4 Schema evolution pentru `FEATURE_COLUMNS` peste snapshot-uri de dataset

**💡 Bună idee dar incompletă** — al doilea-ordin, dar real: dacă Dataset Registry (propunerea proprie a documentului, §3) ajunge construit, apare imediat întrebarea "ce se întâmplă când `FEATURE_COLUMNS` se schimbă între două snapshot-uri de date antrenate anterior" — RUNTIME_CONTRACT.md rezolvă asta doar la ÎNCĂRCARE (condiția 6, versiune incompatibilă = indisponibil), nu la nivelul "putem re-antrena pe un dataset vechi cu un set de feature-uri nou". Nu e o lipsă critică azi (Dataset Registry însuși nu există încă), dar e o consecință directă a propriei recomandări a documentului, netratată.

---

## 5. Ce e supra-proiectat

### 5.1 Taxonomia de 8 straturi, ca atare — candidat real de supra-proiectare conceptuală

**⚠️ Parțial corect, merită spus direct.** Sistemul descris are azi, verificat, **doi clienți reali** ai platformei generice (`xgboost_v1` servit, `blend_v1` în shadow) — nu cinci, nu zece. A numi și fixa 8 "Straturi de Platformă", cu majusculă, ca și cum ar fi o arhitectură enterprise permanentă, pentru un sistem la această scară, riscă exact genul de ceremonie prematură pe care CLAUDE.md însuși îl interzice explicit în altă parte a proiectului ("nu introduce funcționalități speculative", "nu proiecta pentru cerințe ipotetice viitoare"). Documentul nu construiește cod pentru aceste straturi (corect, disciplinat, secțiunile "ce nu trebuie construit" din v3 sunt un exemplu bun de reținere) — dar FIXEAZĂ o taxonomie conceptuală de 8 nume oficiale, care va influența orice discuție viitoare, pentru o complexitate care azi justifică poate 4-5 concepte reale, nu 8 etichete separate (vezi 1.1: Governance și Monitoring nu sunt straturi de același fel).

### 5.2 Menținerea a două trasee de experimentare paralele (Challenger vs. Consensus Validation) — investiție neproporțională cu dovada de valoare

**💡 Bună idee dar incompletă.** Traseul Consensus Validation (ADR-033) e infrastructură reală, funcțională, testată — dar, din tot ce a fost citit în această sesiune și în cele anterioare, nu există nicio dovadă că a produs vreodată un verdict `surface_worthy` care să fi schimbat ceva în producție. Documentul îl clasifică drept infrastructură matură de reutilizat, fără să pună întrebarea: merită menținerea a două trasee de experimentare distincte, cu propriile flag-uri, propriile tabele, propria cadență, pentru o ipoteză de cercetare care încă n-a plătit nimic măsurabil? Nu recomand eliminarea (nu e scopul acestui review), dar semnalez explicit: e complexitate reală, cu valoare încă nedemonstrată, tratată de document ca "matur" fără nuanța asta.

### 5.3 Ce NU e supra-proiectat, spus explicit ca să nu se piardă în restul criticilor

**✅ Confirmat**: disciplina "ce nu trebuie construit" din v3 (niciun `ml_engine.py` prematur, niciun Feature Pipeline separat prematur, niciun wiring nou în `raw_predictions`) e exact opusul supra-proiectării — un exemplu real de reținere arhitecturală corectă, de menținut ca precedent pentru orice extensie viitoare a acestei taxonomii de 8 straturi.

---

## 6. Evoluție — 5 algoritmi, 10 ligi, 20M meciuri — unde crapă prima?

### 6.1 Primul punct de rupere real: orchestratorul unic (`oracle_engine.py`)

**❌ Risc real, nediscutat de v3/v4.** Regula de comunicare din v3 §4 ("compunere de funcții Python, sincronă, ÎNTR-UN SINGUR proces de servire, `oracle_engine.py` ca orchestrator unic") și tiparul propus pentru vocea ML (v3 §3.1: o metodă nouă, `_get_ml_engine_prediction()`, adăugată LÂNGĂ `_get_blend_engine_prediction()`, ambele în `oracle_engine.py`) sunt un pattern care **nu scalează liniar fără cost** la 5 algoritmi în plus: fiecare motor nou = o nouă metodă `_get_X_engine_prediction()`, un nou flag, o nouă linie de wiring, TOATE în același fișier, care e deja mare (2000+ linii, confirmat din citirile de cod ale acestei sesiuni). La 7-8 motoare simultane (3 azi + 5 ipotetice), `oracle_engine.py` devine, prin propriul design recomandat, un god-object de orchestrare — exact contrariul afirmației din v3 §6 ("evoluează fără refactorizări majore"). Aceasta e cea mai importantă descoperire a acestui review: **afirmația explicită "fără refactorizări majore" din documentul anterior nu rezistă la scenariul de scalare pe care review-ul de față îl cere să fie testat.**

### 6.2 Al doilea punct de rupere: Dataset Layer, la 10 ligi în plus

**✅ Confirmat, deja identificat corect de document.** Lipsa Dataset Registry (§3, deja semnalată de v4 însuși) devine acută, nu doar incomodă, la 10 ligi noi — fragmentarea identității de ligă (deja documentată în alte părți ale proiectului) s-ar multiplica, iar reproductibilitatea "ce a văzut fiecare model, per ligă, la ce moment" devine esențială pentru orice audit de calitate pe ligile noi/mici. Acesta e exact tipul de gap pe care documentul îl prezice corect, fără să spună explicit "aici se rupe primul la scalare".

### 6.3 Al treilea punct de rupere: costul de antrenare walk-forward, la 20M meciuri

**💡 Bună idee dar incompletă, absentă din discuție.** v1 §7 (citat de v3) justifică explicit "nu migrăm la incremental learning" pe motivul "antrenare completă <1s la ~50K rânduri, fără presiune reală de cost". La 20M rânduri (≈400×), acest argument nu mai rezistă automat — nu doar costul de compute, ci și fereastra de validare walk-forward (expanding window, obligatorie per regulă permanentă) ar deveni operațional costisitoare, potențial ore, nu secunde. Niciun document din serie (v1-v4) nu numește explicit acest punct de rupere — toate presupun implicit că argumentul "ieftin azi" rămâne valabil la scară, fără să recalculeze.

### 6.4 Ce NU crapă, cu încredere rezonabilă

Model Registry, Promotion Engine, Champion Manager, `automation_runs.py` — toate patru deja demonstrate generice la un al doilea client real (`blend_v1`), fără nicio presupunere de scală în design (chei compuse, dict-uri, fără limite hardcodate găsite). Riscul de rupere la scară e concentrat, cu încredere rezonabilă, în cele trei puncte de mai sus, nu distribuit uniform pe toată platforma.

---

## 7. Verdict

### Scor: **7/10**

**De ce nu mai jos**: documentul e neobișnuit de riguros pentru un artefact de arhitectură — fiecare componentă citată e verificată contra codului real, nu presupusă; identifică singur o contradicție reală și importantă (`dataset_id` declarat în guvernanță, absent din schemă); recunoaște explicit ce NU trebuie construit, o disciplină rară; separarea Training/Promotion e genuin curată și verificată independent aici.

**De ce nu mai sus**: taxonomia centrală a documentului (8 straturi) amestecă concepte de natură diferită (secvențial vs. transversal) sub aceeași formă de prezentare, fără să recunoască asta (§1.1); un bounded context important, identificat CHIAR DE DOCUMENT (Experimentation Layer = 2 trasee diferite), nu primește consecința structurală corectă (§1.3, §2.2); afirmația moștenită din v3 ("evoluează fără refactorizări majore") nu rezistă la exact testul de scalare pe care acest review l-a cerut — orchestratorul unic e un risc real, netratat (§6.1); lipsesc două preocupări structurale standard în orice platformă ML matură — train/serve skew și guvernanță de resurse — complet absente, nu doar sub-tratate (§4.1, §4.3); nivelul de abstractizare declarat ("arhitectură, nu implementare") nu corespunde practicii reale a documentului (citate de cod la fiecare pas), fără ca discrepanța să fie recunoscută explicit (§3).

Niciuna dintre aceste probleme nu invalidează documentul — toate sunt corectabile fără să repornească munca deja făcută. Dar un review Staff+ onest nu poate acorda un scor de "aproape ireproșabil" unui document a cărui taxonomie centrală are o inconsecvență de categorie nerezolvată și a cărui singură afirmație explicită despre scalabilitate ("fără refactorizări majore") nu supraviețuiește primului test de scalare cerut chiar de acest review.
