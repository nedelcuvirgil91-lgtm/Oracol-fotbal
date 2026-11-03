# ADR-086 — Guvernarea artefactului ML servit: eticheta familiei solicitante și garda `REJECTED`

*(Titlul spunea inițial „garda de stare terminală". Corectat deliberat: vezi
§4.0 — `TERMINAL_STATES` include `PROMOTED`, adică exact campionul, iar un
titlu care sugerează „terminal" ar fi dus la implementarea greșită.)*

**Status: ACCEPTED** (aprobat explicit de proprietarul produsului, 2026-11-03,
împreună cu aprobarea separată pentru atingerea fișierului protejat
`ml_predictor.py`)
**Data: 2026-11-03**
**Scop aprobat: A + B** (proprietarul produsului, 2026-11-03)
**Derivat din**: D-15 (un motor dovedit mai bun nu are cale să ajungă la servire), D-17 (cele trei motoare nu sunt independente), Pasul 2 al planului de guvernare a artefactului
**Clasa de defect**: aceeași ca **ADR-082**, cu un nivel mai sus — *ceea ce se evaluează nu e ceea ce se servește*

---

## §0. Trei afirmații ale mele, dintre care DOUĂ s-au dovedit FALSE

Secțiunea asta deschide documentul deliberat, după tiparul lui
`PLAN_DECIZII_DESCHISE_2026-10-20.md` §0. Golurile de mai jos au fost
enunțate proprietarului produsului pe 2026-11-02, **înainte** de a fi
măsurate. Remăsurate pe 3 noiembrie:

| # | ce am afirmat | verdict | ce arată măsurătoarea |
|---|---|:-:|---|
| 1 | „ce artefact servește nu se înregistrează durabil" | **FALS** | se înregistrează: `engine_comparison_snapshots.ml_training_run_id`, 5 artefacte, ferestre fără suprapunere, concordante **exact** cu `training_runs` |
| 2 | „nimic nu împiedică un artefact `REJECTED` să servească — s-a întâmplat 3 din 5" | **FALS ca fapt** | **zero** zile servite în stare terminală, pe toate cinci; fiecare respingere e **12,6–23,5 zile DUPĂ** înlocuire |
| 3 | „`xgboost_v1` n-a avut niciodată campion" | **ADEVĂRAT** | `model_champions`: un singur activ, `blend_v1/8ac89c70` |

**Afirmația 1 era falsă fiindcă n-am citit lanțul până la capăt.**
`seed_from_cache()` chiar setează `last_training_run_id` (`ml_predictor.py:289`),
iar `_resolve_ml_traceability()` (`oracle_engine.py:2578`) îl folosește ca
sursă reală, nu aproximată. Trasabilitatea cerută de North Star #9 **există**
pe calea ADR-052.

**Afirmația 2 e mai instructivă, fiindcă prima mea interogare a nimerit
concluzia corectă din GREȘEALĂ.** Calculasem momentul înlocuirii pe **toate**
cele 64 de rulări `trained`, nu pe cele **cu artefact persistat**. `e638c1dc`
nu a fost înlocuit pe 7 august — rularea următoare (`1455d6c0`) n-are artefact,
deci cache-ul o sare, iar `e638c1dc` a servit până pe 24 august. Refăcută pe
mulțimea corectă, concluzia e aceeași — dar acum **prin construcție**, nu din
noroc. Aceeași clasă ca măsurătoarea pe `id` din ADR-069 §Amendamentul 1: *o
interogare pe cheia greșită nu poate vedea, prin construcție, lucrul căutat.*

**O a patra afirmație, pe care era ușor s-o fac și care e tot falsă**: „59 de
artefacte neguvernate au servit". Imposibil: din 64 de rulări `trained`, doar
**5** au artefact persistat în bucket-ul `model-artifacts`, iar acelea cinci
sunt **exact** cele cinci care au devenit Challenger. Fără artefact, o rulare
nu poate servi — `local_model_cache` o sare.

---

## §1. Starea măsurată (2026-11-03, read-only)

### §1.1 Cine poate servi

```
rulari_trained (xgboost_v1/all) : 64
obiecte in bucket model-artifacts: 18   (6 = suita gate_validation_test, 14 iulie;
                                         12 = 6 perechi model+calibrare)
rulari CU artefact               :  5
rulari FARA artefact             : 59
```

Cele 59 fără artefact sunt antrenări din dezvoltarea din iulie și retrain-uri
manuale prin `oracle_engine.retrain_ml_model()` — care scrie necondiționat un
rând `training_runs` cu `status='trained'`, dar **nu** persistă artefact.
Docstring-ul acelei funcții promite „fără niciun efect asupra modelului activ";
promisiunea se ține, și prin **al doilea** mecanism, independent: fără artefact,
cache-ul nu o poate selecta.

### §1.2 Ce a servit efectiv, și ce familie l-a evaluat

| artefact | a servit | zile | familia Challengerului | stare FSM | terminal la |
|---|---|---:|---|---|---|
| `e638c1dc` | 5 aug – 24 aug | 18,3 | `xgboost_v1` | REJECTED/expired | 6 sep (+13,5z după înlocuire) |
| `4e17c737` | 24 aug – 6 sep | 13,5 | **`blend_v1`** | REJECTED/expired | 19 sep (+12,6z) |
| `6e7265c5` | 6 sep – 20 sep | 13,6 | `xgboost_v1` | REJECTED/expired | 13 oct (+23,5z) |
| `174e7e17` | 20 sep – 14 oct | 23,9 | **`blend_v1`** | SUCCEEDED | — |
| `dda4f7f3` | 14 oct – azi | 20,4 | `xgboost_v1` | SUCCEEDED | — |

Fiecare artefact are **exact un** rând în `challengers` (verificat). Ferestrele
concordă cu `engine_comparison_snapshots` din două surse independente (18,3 zile
↔ kickoff 7–24 aug; 13,5 ↔ 24 aug – 6 sep).

### §1.3 Afirmația centrală: artefactul evaluat NU era artefactul care servea

Suprapunând fereastra de servire cu fereastra Challengerului **activ pe familia
`xgboost_v1`** — familia pe care calea de servire citește:

| perioadă | servea | challenger `xgboost_v1` activ | coincid? |
|---|---|---|:-:|
| 5 aug – 24 aug (18,3z) | `e638c1dc` | `e638c1dc` | ✅ |
| 24 aug – 6 sep (13,5z) | `4e17c737` | `e638c1dc` | ❌ |
| 6 sep – 20 sep (13,6z) | `6e7265c5` | `6e7265c5` | ✅ |
| 20 sep – 13 oct (23,5z) | `174e7e17` | `6e7265c5` | ❌ |
| 13 oct – 14 oct (8,4h) | `174e7e17` | **niciunul** | ❌ |
| 14 oct – azi (20,4z) | `dda4f7f3` | `dda4f7f3` | ✅ |

> **37,4 din 89,9 zile — 41,6% din perioada măsurată — artefactul evaluat în
> shadow pe calea `xgboost_v1` nu era artefactul care servea ieșirea ML.**

Iar în cele două ferestre de nepotrivire, artefactul care servea fusese evaluat
**numai ca `blend_v1`** — adică rândurile shadow au comparat ieșirea
**0,65·Oracle + 0,35·ML** contra Oracle, nu ieșirea ML brută, care e ce
contribuie efectiv artefactul pe calea de servire.

**E exact clasa ADR-082, cu un nivel mai sus.** Acolo Guardianul evalua
campionul pe predicția *Oracle*, nu pe a campionului. Aici poarta evaluează un
*amestec* pe un artefact care servește nemijlocit.

---

## §2. Cauza, citită în cod — eticheta corectă e calculată și ARUNCATĂ

Lanțul, verigă cu verigă:

1. `ml_predictor._ALGORITHM_FAMILY = "xgboost_v1"` — **hardcodat**, linia 45.
2. `_record_training_run()` (linia 50) apelează `storage.save_training_run(...,
   algorithm_name=_ALGORITHM_FAMILY, ...)` — linia 73. Apelat **necondiționat**,
   pe orice status, din `MLPredictorEngine.train()`.
3. `BlendV1Algorithm.fit()` apelează **același** `self._engine.train()`
   (`learning_core/algorithms/blend_v1.py:62`) și refolosește
   `self._engine.last_record_run_id`.
4. Faza B apelează `run_training(algorithm.name, version)`
   (`continuous_learning.py:620`) → `training_runner.run_training()` apelează
   `storage.save_training_run(..., algorithm_name=algorithm.name, ...)`
   (`training_runner.py:50,55`) — adică **`blend_v1`, eticheta CORECTĂ**.
5. Dar `storage.save_training_run()` e **idempotent pe `training_run_id`**:
   fișierul local a fost deja scris la pasul 2, deci funcția **iese devreme
   (`if path.exists(): return path`) și nu scrie niciodată rândul remote**.

> **Eticheta corectă e calculată la pasul 4 și aruncată de garda pusă la pasul
> 5.** Garda aceea e corectă și a fost adăugată deliberat (audit ADR-051/052),
> ca `run_training()` să nu producă un al doilea `INSERT` pe același
> `training_run_id` (constrângere UNIQUE, migrarea 002). Repararea unui gol a
> importat alt gol.

**Aceeași formă ca D-2** („datele nu trebuie construite — se aruncă la ultima
linie: `log_shadow_prediction()` nu mai pasează `features`") **și ca
`error_body` din ADR-081** („pasat dintr-un singur loc"). A treia instanță a
clasei **„valoarea corectă există în proces și nu ajunge la scriere"**.

### §2.1 Consecința colaterală, consemnată

`_record_training_run()` apelează și
`champion_comparison.compare_to_champion(algorithm_family=_ALGORITHM_FAMILY, ...)`
— deci o antrenare cerută de `blend_v1` e comparată informativ cu campionul
**`xgboost_v1`**, care nu a existat niciodată. Comparația e pur informativă
(loghează, nu decide), deci **paguba e zero**; se corectează gratuit de același
fix.

### §2.2 Un comentariu de cod învechit, găsit cu aceeași ocazie

`ml_predictor.py:40-44` justifică eticheta hardcodată cu: *„`train()` e apelat
direct de fluxul de producție (`run_daily.py`, `oracle_engine.py`)"*. **Fals azi
pentru `run_daily.py`**: pasul `ml_retrain` a fost **ELIMINAT de ADR-054**
(`sync/run_daily.py:139`, comentariu explicit). Singurul apelant direct rămas e
`oracle_engine.retrain_ml_model()` (linia 2794), un „ce-ar-fi-dacă" manual care
nu atinge modelul activ. Motivația rămâne valabilă pentru **un** apelant, nu
pentru două — deci implicitul de la §3 e în continuare necesar.

---

## §3. Decizia A — eticheta familiei care a cerut antrenarea

**`_record_training_run()` primește familia solicitantă ca parametru, cu
implicit `xgboost_v1`.** Cei doi adaptori Learning Core își pasează propriul
`name`. Punctul unic de scriere a rândului rămâne exact unde e.

```python
def _record_training_run(status, samples_used, walk_forward_metrics, message,
                         *, algorithm_family: str = _ALGORITHM_FAMILY) -> str:
```

**De ce NU varianta pe care o recomandasem inițial** („adaptorul blend scrie
propriul rând"): ar reintroduce **exact** defectul reparat la auditul
ADR-051/052 — două rânduri `training_runs` pentru o singură tentativă reală de
antrenare. Descoperire făcută în timpul scrierii acestui ADR, consemnată aici,
nu strecurată (Discovery Rule).

**De ce NU varianta „calea de servire selectează prin `challengers`"**: ar fi
mai ieftină (nu atinge niciun fișier protejat), dar lasă `training_runs` să
mintă în continuare, iar `training_runs` e sursa durabilă, cross-run, pe care
se sprijină `get_latest_training_run()` și comparația cu campionul. Se repară
înregistrarea, nu se ocolește.

**Implicitul `xgboost_v1` nu e comoditate, e corectitudine**: singurul apelant
direct rămas (`retrain_ml_model()`) chiar antrenează motorul ML generic, fără
context de familie — iar comportamentul lui nu se schimbă cu nimic.

### §3.1 Ce schimbă A în producție — și e o SCHIMBARE, nu o corecție neutră

După A, `list_recent_training_runs('xgboost_v1','all')` **nu mai vede rulările
cerute de blend**. Consecințele, în ordinea importanței:

**(a) Nepotrivirea de 41,6% din §1.3 devine ZERO prin construcție.** Faza B pe
familia `xgboost_v1` produce o rulare etichetată `xgboost_v1`, înregistrată ca
Challenger `xgboost_v1`, cu artefact persistat — deci **cea mai recentă rulare
`xgboost_v1` cu artefact ESTE artefactul Challengerului `xgboost_v1` activ**.
Poarta și servirea se aliniază fără să atingem deloc jurnalizarea shadow. Asta
e valoarea reală a lui A; eticheta în sine ar fi fost igienă.

**(b) Artefactul servit poate fi mai VECHI.** Familiile alternează, deci
rulările `xgboost_v1` apar la ~34–38 de zile (5 aug → 6 sep → 14 oct), nu la
~13. Azi nu se schimbă nimic (`dda4f7f3` e `xgboost_v1`), dar în viitor
artefactul servit poate fi cu o alternanță mai vechi.

**Trocul, spus explicit**: un artefact ușor mai vechi care **E** evaluat, contra
unuia mai proaspăt care **NU E**. Răspunsul proiectului e neechivoc (North Star
#1, #2, ADR-002): **evaluat bate proaspăt.** Iar costul e măsurat, nu presupus —
D-17 a arătat că două artefacte consecutive ale aceluiași motor diferă cu
**0,0117 Brier** (campion vs challenger blend), adică puțin.

**(c) Nu schimbă nicio formulă, niciun feature, nicio pondere.** Artefactul e
produs de același `MLPredictorEngine`, pe aceleași date, cu aceleași
`FEATURE_COLUMNS`. Se schimbă *care* artefact e selectat, niciodată *cum* e
antrenat.

### §3.2 Raza de acțiune e EXACT un cititor — măsurată, nu estimată

`training_runs.algorithm_name` are doi cititori declarați în `supabase_client`:
`get_latest_training_run()` (linia 619) și `list_recent_training_runs()`
(linia 650). Măsurat prin `grep` pe tot codul de producție:

**`get_latest_training_run()` nu are NICIUN apelant de producție.** Ancora
Fazei B a fost mutată deliberat pe `get_latest_challenger()`, cu motivul scris
în `continuous_learning.py:587-598`: `training_runs` conține și antrenări din
afara Challenger Framework, fiecare resetând ceasul „meciuri noi de la ultima
antrenare", astfel încât pragul **nu era atins niciodată** — 17 zile de
`threshold_check` „skipped" pentru `xgboost_v1`, cu 50.000+ meciuri eligibile.

Deci singurul consumator real al etichetei e **`list_recent_training_runs()`,
adică exact calea de servire**. Nicio altă decizie din proiect nu se mișcă.

**Observație care întărește decizia**: auditul acela a ocolit `training_runs`
fiindcă eticheta ei nu era de încredere. ADR-086 o face de încredere — deci
ocolirea rămâne corectă din alt motiv (imunitate la antrenările din afara
fluxului), nu din cauza etichetei.

---

## §4. Decizia B — garda `REJECTED` pe Local Model Cache

**`local_model_cache.load_latest_trained_model_or_none()` sare artefactele al
căror Challenger e `REJECTED`**, gatată de flagul `local_cache_fsm_guard_enabled`,
**implicit oprit** (North Star #3).

### §4.0 🔴 Garda e pe `REJECTED`, NU pe `TERMINAL_STATES` — capcană prinsă înainte de implementare

Prima formulare a acestui paragraf spunea „stare terminală (`REJECTED`, și orice
stare terminală viitoare)". **Ar fi fost un defect grav**, fiindcă
`challenger_manager.TERMINAL_STATES = {"PROMOTED", "REJECTED"}` (linia 53): un
implementator care ar fi citit §4 și ar fi reutilizat constanta ar fi **exclus
campionul de la servire** — exact inversul scopului.

Garda se scrie pe o mulțime **proprie**, cu motivul alături în cod:
`_STARI_CARE_NU_SERVESC = {"REJECTED"}`. `PROMOTED` nu se exclude **niciodată**,
și o gardă dedicată cade dacă cineva reintroduce `TERMINAL_STATES` acolo.

**Clasa**: *o constantă corectă pentru întrebarea ei („s-a terminat ciclul?")
devine greșită pentru altă întrebare („mai are voie să servească?")*. Ruda lui
`has_stats` („pagina descărcată" citit ca „extragere reușită") și a lui
`referee` ca martor.

Azi funcția filtrează pe `status=='trained'` + `algorithm_version` compatibil +
artefact încărcabil + probă de inferență reală — și **nicio verificare a stării
FSM**.

### §4.1 B e PREVENȚIE, nu reparație — măsurat

**Zero zile** au fost servite în stare terminală, pe toate cele cinci artefacte
(§1.2). Siguranța de până acum vine din **ordine, nu din gardă**: propunerea de
expirare se naște la `n ≥ 300`, ceea ce ia săptămâni, iar până atunci Faza B a
antrenat deja înlocuitorul. Cele trei respingeri au venit cu 12,6 / 12,6 / 23,5
zile **după** înlocuire.

**Riscul viu, pe care ordinea nu-l acoperă**: dacă o expirare se comite și Faza
B **nu** apucă să antreneze înlocuitorul (rulare de noapte eșuată, defectul de
idempotență al candidaturii din ADR-084 Etapa 0, slot ocupat), artefactul
respins rămâne singurul cu artefact și **servește nelimitat**. Nimic în cod nu
se opune.

### §4.2 Consecința operațională a lui A+B împreună, spusă explicit

După A+B, dacă cel mai recent Challenger `xgboost_v1` e terminal și nu există
înlocuitor, cache-ul cade pe rulări `xgboost_v1` mai vechi — ale căror
Challengeri sunt și ei terminali — deci **ML se oprește complet, se servește
Oracle-only**.

Măsurat pe istoric: pe **13–14 octombrie** a existat o fereastră de **8,4 ore**
fără niciun Challenger `xgboost_v1`. Sub A+B, ML ar fi fost oprit în acele 8,4
ore.

**Acesta e comportamentul CORECT** — nimic negatat nu servește — dar e o
consecință reală, nu una teoretică, și e motivul pentru care B e gatat și pentru
care cele două se activează împreună, cu măsurătoare.

---

### §4.3 Dependența NOUĂ pe care B o introduce, și de ce nu încalcă North Star #10

B face calea de servire să citească tabela **`challengers`** — registrul FSM,
scris exclusiv de Challenger Framework. Asta e o lărgire reală a suprafeței de
care depinde servirea și merită spusă, nu trecută cu vederea.

**Nu e o dependință „în sus"**, și argumentul e de direcție, nu de convenție:
servirea citea deja registre din Learning Core — `champion_loader` citește
`model_champions`, iar `local_model_cache` citea deja `training_runs`. Direcția
proiectată (ADR-019, straturile L0-L6) e **L6 Serving consumă ieșirea
registrelor**, niciodată invers: servirea nu antrenează, nu promovează, nu
scrie în niciun registru. B adaugă o a treia citire de același fel.

Ce ar FI fost o încălcare: ca servirea să *declanșeze* o tranziție FSM, sau să
ceară antrenare la pornire — lucru eliminat deliberat în trecut
(`oracle_engine._initialize_ml()` reantrena sincron, 3-5 minute de blocaj).
Nimic din B nu se apropie de asta: o singură citire, fail-open, care în cel mai
rău caz servește ca azi.

**Costul operațional**: o interogare `challengers` per candidat, doar cât
flagul e activ, și doar până la primul candidat acceptabil — tipic **una** per
pornire de motor. Plasată înaintea descărcării artefactului, deci în cazul
respins **economisește** un download din Storage.

---

## §5. Ce NU decide acest ADR

1. **Nu cere `PROMOTED` pentru servire.** Ar însemna Oracle-only azi (niciunul
   din cele 5 artefacte n-a fost vreodată campion) și ar contrazice ADR-051
   („niciun motor nu e primar prin construcție"). Regula adoptată e **negativă**:
   *un artefact respins nu servește*. Niciodată *doar un campion servește*.
2. **Nu atinge jurnalizarea shadow.** Alinierea dintre poartă și servire se
   obține din §3.1(a), prin etichetă — nu prin a face `challenger_shadow.py` să
   țintească artefactul care servește. Varianta aceea era pe masă și **nu se
   face**: ar fi o schimbare de semantică FSM pentru un rezultat pe care A îl
   produce gratuit.
3. **Nu schimbă `ml_weight`** și nu atinge calea de blend la servire (D-17,
   Pasul 3, ADR separat).
4. **Nu promovează nimic.** ADR-002 neatins: promovarea rămâne act uman.
5. **Nu rescrie retroactiv** etichetele celor 5 rânduri existente. Un rând de
   evidență care spune ce s-a scris atunci rămâne dovada stării de atunci
   (North Star #9). Nepotrivirea de 41,6% din §1.3 rămâne **măsurabilă în date**
   exact fiindcă nu rescriem.

---

## §6. Măsurătoarea „înainte / după", obligatorie

Linia de bază, măsurată **înainte** de orice schimbare (3 noiembrie, cifrele din
§1), față de care se compară:

| ce se măsoară | înainte |
|---|---|
| rulări `trained` (xgboost_v1/all) | 64 |
| rulări cu artefact | 5 |
| artefact servit azi | `dda4f7f3` |
| familia Challengerului lui | `xgboost_v1` / SUCCEEDED |
| rulări etichetate `blend_v1` în `training_runs` | **1** — vezi §6.1: scrisesem „0", și era o DEDUCȚIE prezentată ca măsurătoare |
| nepotrivire servit ↔ evaluat | **37,4 / 89,9 zile = 41,6%** |

**După A, la prima antrenare cerută de `blend_v1`**: apare un rând
`training_runs` cu `algorithm_name='blend_v1'` **și `created_at` ulterior
livrării ADR-086** — nu „primul rând", fiindcă unul există deja din 4 august —
iar `list_recent_training_runs('xgboost_v1','all')` **nu** îl vede. Acela e
testul decisiv — nu „suita e verde".

### §6.1 🔴 O cifră a mea din tabelul de mai sus era FALSĂ — deducție prezentată ca măsurătoare

Prima versiune scria: *rulări etichetate `blend_v1` în `training_runs` = **0**
(zero, din totdeauna)*. **Nu am numărat niciodată.** Am dedus-o din mecanismul
din §2 (eticheta hardcodată) și am scris deducția cu aparența unei cifre
măsurate — exact clasa de eroare pe care §0 al acestui ADR o reproșează altor
trei afirmații de-ale mele. Găsită la verificarea de după push, nu de un test.

**Măsurat: 1 rând** — și e `8ac89c70`, **campionul `blend_v1` activ**, etichetat
**corect**, din 4 august, cu artefact, `PROMOTED`.

**Nu infirmă nimic din §2 — îl confirmă cu martor pozitiv**, iar perechea e
vizibilă în date:

| `training_run_id` | `algorithm_name` | `created_at` | scris de |
|---|---|---|---|
| `d784f19f` | `xgboost_v1` | 2026-08-04 **14:46:35.541** | `_record_training_run()` |
| `8ac89c70` | **`blend_v1`** | 2026-08-04 **14:46:35.811** | `training_runner.run_training()` |

**270 de milisecunde** între ele, același `samples_used = 49983`, același mesaj.
Pe 4 august adaptorul blend încă genera un `uuid` **propriu**, deci
`storage.save_training_run()` nu avea ce să sară — și scria al doilea rând, **cu
eticheta corectă**. Avem, așadar, toate trei regimurile atestate în producție:

| regim | rânduri per antrenare | eticheta |
|---|---:|---|
| înainte de auditul ADR-051/052 | **2** | corectă (pe al doilea rând) |
| după audit, până la ADR-086 | **1** | **greșită** |
| **de la ADR-086 A** | **1** | **corectă** |

Reparația de atunci a schimbat „două rânduri, etichetă corectă" în „un rând,
etichetă greșită". A fost alegerea bună — un rând per tentativă e corect — dar
a plătit cu eticheta, și nimeni n-a observat fiindcă singurul ei cititor e
calea de servire (§3.2), unde consecința a fost tăcută.

**O consecință care se închide curat**: campionul activ `8ac89c70` e etichetat
`blend_v1`, deci `list_recent_training_runs('xgboost_v1','all')` **nu l-a văzut
niciodată** — consecvent cu §1.2, unde cele 5 artefacte servite nu îl includ.
Verificarea mea era corectă; afirmația despre cauză era nemăsurată.

**Contrapondere obligatorie**: numărul total de rânduri `training_runs` per
tentativă de antrenare trebuie să rămână **1**. Dacă devine 2, defectul
ADR-051/052 a fost reintrodus și reparația se retrage.

**După B**: artefactul servit rămâne `dda4f7f3` (Challengerul lui nu e
terminal), deci activarea lui B **nu trebuie să schimbe nimic azi**. O schimbare
la activare înseamnă că garda prinde altceva decât ce credem.

---

## §7. Consecințe

- **Pozitive**: nepotrivirea servit↔evaluat devine 0 prin construcție;
  `training_runs` încetează să mintă despre familia solicitantă;
  `compare_to_champion` compară cu campionul familiei corecte; un artefact
  respins nu mai poate servi, nici în scenariul în care ordinea nu ne mai
  protejează.
- **Negative, acceptate conștient**: artefactul servit poate fi cu o alternanță
  mai vechi (§3.1b, cost măsurat ~0,0117 Brier); ML se poate opri complet dacă
  familia `xgboost_v1` n-are niciun Challenger în stare neterminală (§4.2 —
  8,4 ore pe istoric).
- **Fișier protejat atins**: `ml_predictor.py` (semnătura lui
  `_record_training_run` + cele două apeluri interne). Cere **aprobare
  separată**, distinctă de aprobarea acestui ADR.
- **Zero migrări, zero coloane noi, zero tabele noi.** Un flag nou
  (`local_cache_fsm_guard_enabled`), implicit absent din `model_config`.
- **Calea de predicție** (`oracle_engine.py`, `feature_engine.py`,
  `recalibration.py`, `app.py`, `oracle_api.py`) rămâne **neatinsă** — se
  verifică prin `git diff` gol înainte de push.

---

## §8. Verificare cerută ÎNAINTE de activarea flagului B

1. `pytest tests/` verde pe `main` înainte de push, cu aritmetica testelor
   închisă exact.
2. Mutații rulate și prinse, minimum: eticheta hardcodată reintrodusă · garda
   de idempotență ocolită (al doilea rând) · garda FSM inversată (sare doar
   artefactele NEterminale) · flagul citit implicit `True` · starea terminală
   citită din `training_runs` în loc de `challengers`.
3. O rulare de noapte cu flagul **oprit**, care confirmă comportament identic —
   cerința standard a proiectului înaintea oricărei activări.
4. Măsurătoarea din §6, înregistrată, cu amprenta `model_config` (chei +
   `md5(data − cheia_nouă)` + `updated_at`, per remediul D-14).

---

## §9. Jurnal

- **2026-11-03, dimineață** — PROPUNERE scrisă. Scopul A+B aprobat de
  proprietarul produsului. Cifrele din §1 măsurate read-only în aceeași zi.
- **2026-11-03** — **ACCEPTED**, cu aprobare separată pentru fișierul protejat
  `ml_predictor.py`. **A și B implementate, flagul B NEACTIVAT.**

### §9.1 Ce s-a scris

| fișier | ce |
|---|---|
| `ml_predictor.py` | `_record_training_run(..., *, algorithm_family=_ALGORITHM_FAMILY)`; `train(*, requested_by=None)` propagă pe **toate cele patru** puncte de apel; eticheta ajunge și la `compare_to_champion()` (§2.1); comentariul învechit despre `run_daily.py` corectat (§2.2) |
| `learning_core/algorithms/blend_v1.py` | `train(requested_by=self.name)` |
| `learning_core/algorithms/xgboost_v1.py` | `train(requested_by=self.name)` — **explicit**, deși coincide cu implicitul |
| `learning_core/local_model_cache.py` | `_STARI_CARE_NU_SERVESC`, `is_fsm_guard_enabled()`, `_artefact_descalificat_de_fsm()`, garda în buclă **înaintea** descărcării |
| `tests/test_adr086_artifact_governance.py` | 31 de teste noi |
| `tests/test_local_model_cache.py` | fixtură `autouse` care oprește garda (vezi §9.3) + garda de importatori refactorizată din listă în invariant + contrapondere |

### §9.2 Capcana prinsă ÎNAINTE de implementare — §4.0

Prima formulare a lui §4 vorbea despre „stare terminală". Reutilizarea lui
`challenger_manager.TERMINAL_STATES` (`{"PROMOTED", "REJECTED"}`) ar fi **oprit
campionul de la servire**. Garda e scrisă pe mulțime proprie, iar
`test_TERMINAL_STATES_nu_apare_in_modul` cade dacă cineva o reintroduce.
Mutația M6 (PROMOTED adăugat la stările care nu servesc) e prinsă.

### §9.3 Defect găsit în propriile mele teste, înainte de commit

Garda B adaugă o citire `sb.load_config()` în calea pe care cele ~18 teste
existente din `tests/test_local_model_cache.py` o exercită. Într-un container
fără credențiale, `get_client()` întoarce `None` și `load_config` dă implicitul
— deci testele ar fi trecut. **Pe o mașină care are credențiale ar fi atins
rețeaua.** A doua instanță a lecției plătite pe 21 octombrie: *un test care
trece fiindcă mediul e sărac nu e un test fără rețea, e unul norocos.*
Închis cu o fixtură `autouse` care patch-ează explicit `load_config`.

### §9.4 Garda de izolare a modulului era o LISTĂ, și a căzut la adăugarea unui test

`test_module_has_single_known_importer` exempta nume de teste dintr-o listă
(`{"test_local_model_cache.py", "test_champion_diagnostic_probe.py"}`) —
**deja amendată o dată**. Noul fișier de teste a doborât-o, deși un test care
importă modulul e exact comportamentul declarat de propriul ei docstring.

Refactorizată în invariant: tot ce e sub `tests/` e exceptat **prin
construcție**, lista de producție (`oracle_engine.py`) rămâne. Nu slăbește ce
contează — M12 (un importator nou de **producție**, adăugat în
`training_runner.py`) e prins. Și i s-a adăugat **contraponderea care
lipsea**: fără ea, garda ar fi trecut liniștită și dacă scanarea s-ar fi rupt,
fiindcă `offenders == []` arată identic pentru „nimeni nu importă" și pentru
„n-am căutat" — M13 (rădăcină greșită) o doboară.

Aceeași clasă corectată în aceeași zi la `tests/test_upsert_timestamp_freshness.py`
(Pasul 2b): **o gardă scrisă ca listă se învechește exact ca documentația pe
care proiectul o reproșează altora.**

### §9.5 Mutații — 13, toate prinse

| # | mutația | teste căzute |
|---|---|---:|
| M1 | eticheta hardcodată reintrodusă în scriere | 2 |
| M2 | `requested_by` ignorat în `train()` | 2 |
| M3 | comparația cu campionul revine la constantă | 1 |
| M4 | adaptorul `xgboost_v1` nu mai pasează `requested_by` | 1 |
| M5 | garda FSM **inversată** (sare artefactele neterminale) | 9 |
| M6 | `PROMOTED` adăugat la stările care nu servesc | 2 |
| M7 | flagul implicit `True` | 2 |
| M8 | garda FSM mutată **după** descărcarea artefactului | 2 |
| M9 | absența Challengerului **descalifică** (regula devine pozitivă) | 1 |
| M10 | varianta RESPINSĂ pentru A — adaptorul scrie și propriul rând | 2 |
| M11 | flagul citit **per candidat**, în buclă | 1 |
| M12 | importator nou de **producție** al modulului | 1 |
| M13 | scanarea gărzii ruptă — contraponderea trebuie să cadă | 1 |

Fișierele au fost restaurate din instantanee și verificate cu `md5sum -c`
(niciodată `git checkout`).

### §9.6 Raza de acțiune, verificată

`git diff` pe **celelalte cinci** fișiere protejate (`oracle_engine.py`,
`feature_engine.py`, `recalibration.py`, `app.py`, `oracle_api.py`) e **GOL**.
Zero migrări, zero tabele, zero coloane. Singurul consumator real al etichetei
e calea de servire (§3.2).

### §9.6bis Corecție de după push, în aceeași zi — §6.1

Linia de bază din §6 conținea o cifră pe care o **dedusesem** și o scrisesem ca
măsurată („0 rânduri `blend_v1`"). Măsurat: **1**, campionul `8ac89c70`.
Corectată, cu perechea de 270 ms care confirmă mecanismul. Testul decisiv din
§6 a fost și el rescris — „primul rând" devenise un criteriu care s-ar fi
îndeplinit din istoric, nu din reparație.

**Lecția, în propriile condiții ale acestui ADR**: §0 enumeră trei afirmații
false de-ale mele, iar §6 conținea o a patra, de aceeași clasă, scrisă în
același document. **O deducție corectă despre mecanism nu devine o măsurătoare
fiindcă mecanismul e corect.**

### §9.7 Ce rămâne de făcut

1. **Activarea flagului** `local_cache_fsm_guard_enabled` — decizie separată,
   după verificările din §8. Până atunci, B e cod inert, iar A e în efect de
   la prima antrenare cerută de `blend_v1`.
2. Măsurătoarea „după" din §6, la prima antrenare blend: trebuie să apară
   primul rând `training_runs` cu `algorithm_name='blend_v1'`, **unul singur**,
   iar `list_recent_training_runs('xgboost_v1','all')` să nu-l vadă.
