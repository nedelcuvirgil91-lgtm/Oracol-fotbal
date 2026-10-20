# ADR-079 — Ciclul de viață al unei decizii T3a

**Status**: PROPUNERE (2026-10-20) — cere aprobare explicită înainte de implementare
**Decizie de proiectare delegată și luată de mine** (2026-10-20, la cererea
explicită a proprietarului produsului): §4.2, plafonul regulii de trend. Prima
mea recomandare (fără plafon) s-a dovedit **greșită la măsurare** — vezi
§4.2.1. Rămâne de aprobat ADR-ul ca întreg, nu acest punct.
**Derivat din**: D-5, D-8 și D-11 (`CLAUDE.md` §DECIZII) + o a treia față descoperită
pe 20 octombrie, în timpul analizei deciziei #8 (Discovery Rule)
**Atinge**: contractul ADR-026 (Decision Feed, mașina de stări + politica de
staleness), ADR-057 (regula de expirare a unui Challenger), ADR-033
(§Decision — limita normativă a studiului de consens)
**Nu atinge**: nicio formulă, niciun motor de predicție, nicio coloană nouă,
nicio migrare. Calea de servire rămâne neatinsă.

---

## 0. De ce un singur ADR pentru trei lucruri

Cele trei fețe arată ca defecte independente și sunt tratate separat în
`CLAUDE.md`. **Nu sunt separabile**, și asta e demonstrabil, nu stilistic:

- Cablarea sweep-ului (F2) ar trece decizia #8 din `pending` în `expired`
  după 27 octombrie. `expired` **nu** e în `_OPEN_DECISION_STATUSES`
  (`automation_runs.py:39`), deci rularea următoare ar propune #9, apoi #10 —
  exact fluxul zilnic de propuneri identice pe care F3 trebuie să-l închidă.
  **F2 rezolvat singur produce F3.**
- Pragul de expirare (F3b) decide dacă #8 ar fi trebuit să existe. Dacă nu ar
  fi trebuit, întrebarea „ce facem cu o decizie uitată" (F2) se pune pe un
  caz fabricat.
- Suprascrierea tăcută a felului (F3a) face ca o decizie aprobată pentru X să
  fie executată ca Y — adică face ca *execuția* (F1) să nu mai corespundă
  aprobării. **Nu are sens să cablăm execuții înainte să fie garantat că
  execută ce s-a aprobat.**

Un ADR per față ar cere ca fiecare să presupună ce decid celelalte două.

---

## 1. Context — ce s-a măsurat, read-only, pe 2026-10-20

### 1.1 Starea reală a feed-ului

```sql
SELECT d.id, d.status, d.ttl_at::date, r.target_key, r.producer,
       d.evidence->>'decision_kind' AS fel
FROM decision_feed d JOIN automation_runs r ON r.id = d.run_id;
```

| # | status | TTL | target_key | producer | `decision_kind` |
|---|---|---|---|---|---|
| 8 | `pending` | 2026-10-27 | `blend_v1\|all` | ADR-030 | `expiry` |
| 7 | `committed` | 2026-09-28 | `xgboost_v1\|all` | ADR-030 | `expiry` |
| 6 | **`approved`** | **2026-09-21 (depășit)** | `agreement_score` | ADR-033 | **NULL** |
| 5 | `committed` | 2026-09-17 | `blend_v1\|all` | ADR-030 | `expiry` |
| 4 | `committed` | 2026-09-13 | `xgboost_v1\|all` | ADR-030 | `expiry` |
| 3 | `committed` | 2026-08-30 | `blend_v1\|all` | ADR-030 | **NULL** |

Două spații de nume distincte de `target_key`: `familie|ligă` (ADR-030) și
`metric_name` (ADR-033). Ele **nu se pot ciocni** — fapt relevant la §3.

### 1.2 Ținta deciziei #8 nu e înțepenită, e în urcare

`blend_v1/174e7e17`, din `challenger_evaluations`:

| n | Δ acuratețe | sig. | Δ Brier | sig. | Δ log-loss | sig. |
|---:|---:|:--:|---:|:--:|---:|:--:|
| 204 (17 oct) | +0,98pp | nu | −0,00845 | nu | −0,01603 | nu |
| 206 (17 oct) | +0,97pp | nu | −0,00819 | nu | −0,01553 | nu |
| 255 (18 oct) | +1,57pp | nu | −0,00869 | nu | −0,01578 | **DA** |
| 290 (19 oct) | +2,07pp | nu | −0,00886 | **DA** | −0,01516 | **DA** |
| **301 (20 oct)** | **+2,33pp** | nu | −0,00890 | **DA** | −0,01498 | **DA** |

Trei zile consecutive, câte o metrică trece pragul, în ordine. Toate pe
`baseline_source = 'shadow_control'`, deci pe baseline-ul corect (ADR-072).
Fratele lui, `blend_v1/8ac89c70`, a devenit `candidate_for_promotion` la
n=383 cu +3,66pp și toate trei semnificative. Ritmul măsurat în ultimele 4
zile e ~27 meciuri/zi.

**Pragul care a produs #8 e `MIN_MATCHES_FOR_EXPIRY = 300`**
(`continuous_learning.py:78`), fără nicio altă condiție. ADR-057 l-a scris
pentru cazul real din august: un Challenger **blocat** în `monitoring` care
oprea antrenarea întregii familii timp de 14 zile. Acesta nu e blocat.

---

## 2. Fața 1 — decizii care nu pot fi executate (D-8)

`learning_core/consensus_validation.py:191`, `_propose_surfacing_decision()`
produce o decizie T3a. `commit_decision()` e apelat exclusiv din
`continuous_learning.py` (liniile 821, 866, 876, 903), iar acela iterează
prin `list_approved_decisions_for_target(target_key)` cu `target_key =
familie|ligă` — **niciodată `agreement_score`**. Deci decizia #6, aprobată pe
19 septembrie, nu poate fi comisă de nicio linie de cod existentă.

**Dar încadrarea „lipsește codul de execuție" e greșită**, și asta schimbă
decizia. Docstring-ul modulului (liniile 9-13) și ADR-033 §Decision spun
explicit: *„rezultatele acestui modul produc exclusiv evidență, nu execută
nicio schimbare de serving"* și *„Nu atinge niciodată `oracle_engine.py`,
Model Registry, Challenger FSM sau Promotion Service"*.

O fază de execuție **în** `consensus_validation` ar încălca regula normativă
centrală a propriului ei ADR. Deci D-8 nu e un gol de implementare, e o
**contradicție internă a ADR-033**: produce o decizie T3a — care prin ADR-026
înseamnă „cineva o execută după aprobare" — interzicându-și simultan orice
execuție.

Ce ar trebui să se întâmple e scris în chiar decizia #6, în `rollback_plan`:
*„revenire la politica de serving implicită ADR-031 (flag de configurare, zero
risc de date)"*. Adică acțiunea e **comutarea unui flag de configurare** — exact
operația pe care în acest proiect o face omul, cu SQL arătat și confirmat, de
fiecare dată (ADR-072 pe 14 oct, ADR-073 pe 15 oct, ADR-078 pe 19 oct).

### 2.1 Decizie propusă — varianta (i), recomandată

**Execuția unei decizii de surfacing e operațională, nu de cod**, iar
Decision Feed-ul primește o singură afordanță nouă: pentru o decizie
`approved` pe care nicio fază de cod nu o revendică, un control explicit
„marchează ca executată" care apelează `commit_decision()`.

- Respectă limita ADR-033 fără amendament: niciun cod de consens nu atinge
  servirea.
- Nu construiește un mecanism pentru o acțiune care e, la propriu, un `UPDATE`
  de o linie pe `model_config`.
- Închide #6 onest: fie o marchezi executată după ce comuți flagul, fie o
  respingi.

**Capcană de tratat explicit în implementare**: „marchează ca executată" e un
buton prin care omul afirmă un fapt despre lumea exterioară. Trebuie să fie
vizibil DIFERIT de „Aprobă" (text, nu culoare — vezi D-11), și textul trebuie
să spună ce anume se afirmă, nu „gata".

### 2.2 Variantele respinse, cu motivul

- **(ii) se oprește producerea de propuneri de surfacing.** Verdictul se scrie
  oricum imutabil în tabela proprie, deci informația nu se pierde. Respinsă:
  ar însemna că un studiu cu verdict `surface_worthy` nu ajunge niciodată în
  fața nimănui — adică exact clasa de eroare ADR-057 (o condiție împlinită pe
  care nimic nu o semnalează, descoperită după 14 zile).
- **(iii) faza de execuție se implementează în alt modul** (`continuous_learning`
  sau unul dedicat), ca limita ADR-033 să țină. Respinsă azi: ar lega un modul
  deliberat decuplat (flag propriu, cadență proprie, „un eșec aici nu poate
  bloca ciclul Continuous Learning") de orchestratorul principal. Costul
  arhitectural depășește cu mult o acțiune care e o comutare de flag. Rămâne
  varianta corectă **dacă** vreodată surfacing-ul ajunge să cuprindă mai mult
  decât un flag.

---

## 3. Fața 2 — nimic nu semnalează o decizie uitată (D-5)

`automation_runs.sweep_stale_decisions()` (linia 349) implementează politica
ADR-026: `pending` + TTL depășit → `expired`; `approved` + TTL depășit →
`orphaned`. Verificat prin `grep -rn` pe `*.py` și `*.yml`: **singurii
apelanți sunt două teste** (`tests/test_automation_runs.py:265, 286`). Niciun
workflow, niciun orchestrator.

Consecința e ambivalentă, și **ambele jumătăți sunt măsurabile azi**:

- Ne-a **ajutat**: decizia #7 a rămas aprobabilă 15 zile după TTL, și a fost
  aprobată pe 13 octombrie. Cu sweep-ul cablat, ar fi devenit `expired` și ar
  fi trebuit reemisă.
- Ne-a **costat**: #7 a stat 22 de zile fără niciun semnal, iar #6 e blocată
  de o lună. §8 din ADR-057 prevestea exact asta: *„nu există azi nicio
  alertă care să semnaleze acea stare"*.

### 3.1 De ce cablarea simplă e GREȘITĂ — verificat, nu presupus

Dacă sweep-ul ar rula mâine, #8 ar deveni `expired` pe 27 octombrie.
`expired` nu e în `_OPEN_DECISION_STATUSES = ("proposed", "pending",
"approved")`, deci garda de idempotență din `propose_decision()` nu îl mai
vede — iar rularea următoare ar crea #9, identică. Și în fiecare noapte după,
cât timp `n ≥ 300`.

**Același efect îl are și „Respinge"**: `rejected` nu e nici el o stare
deschisă.

Deci, azi, din cele trei acțiuni posibile pe #8, **singura care nu produce
zgomot zilnic e să nu faci nimic** — `pending` *este* o stare deschisă, deci
`propose_decision()` returnează #8 existentă, iar `surface_decision()` refuză
s-o reîmpingă (tranziție condiționată, reparată pe 6 septembrie). Asta nu e o
proprietate proiectată, e un accident fericit.

### 3.2 Decizie propusă

Sweep-ul se cablează, **împreună cu o perioadă de răcire**, nu înaintea ei:

1. **Cablare**: `sweep_stale_decisions()` se apelează o dată pe rulare, din
   `continuous_learning.run_cycle()`, înaintea Fazei A — deci în același loc
   care și produce deciziile, cu același flag, fără workflow nou.
2. **Răcire (nouă)**: nu se propune o decizie de același **fel** pe același
   `target_key` dacă există una `rejected` sau `expired` de acel fel,
   rezolvată în ultimele **168 de ore** (identic cu `_T3A_DECISION_TTL_HOURS`,
   ca să nu introducem o a doua constantă de timp). Folosește `resolved_at`,
   care există deja — **zero schemă nouă**.
3. **Raportare**: numărul de decizii expirate/orfanizate intră în `summary`-ul
   rulării, ca o expirare să nu treacă neobservată. O decizie `orphaned` e un
   eșec de producător (ADR-026), nu o curățenie.

Efectul pe cazurile reale: #6 ar deveni `orphaned` și ar fi raportată — ceea
ce e corect, e exact semnalul care a lipsit o lună. #8 nu ar mai genera flux
zilnic după rezolvare, indiferent cum o rezolvi.

---

## 4. Fața 3 — o decizie deschisă își poate schimba tăcut felul

Trei sub-defecte, toate în aceeași funcție de propunere.

### 4.1 F3a — `propose_decision()` suprascrie `evidence`-ul unei decizii de ALT fel

`automation_runs.py:184-215`: când există o decizie **deschisă** pe același
`target_key`, funcția îi **suprascrie `evidence`** și îi returnează id-ul, în
loc să creeze una nouă. Comportamentul e intenționat (idempotență), și e
corect **cât timp felul e același**.

**Clasa e deja cunoscută și numită în cod** — garda `R3-Risk-1`,
`continuous_learning.py:682-689`:

> *„`propose_decision()` reutilizează ȘI suprascrie `evidence`-ul oricărei
> decizii deschise pe același `target_key` […] — o propunere de rollback peste
> o decizie de alt fel (ex. o promovare `pending`) i-ar corupe `evidence`-ul.
> Nu se stivuiește niciodată."*

Garda e aplicată pe **calea de rollback**. Verificat pe celelalte două:

| Cale | Gardă | Ce verifică |
|---|---|---|
| rollback (`_phase_d`, l. 687) | `_has_open_decision_for_target()` | orice decizie deschisă → nu propune |
| expirare (`_handle_monitoring_verdict`, l. 337) | `list_approved_decisions_for_target()` | **doar** `approved` — nu `pending`, nu `proposed` |
| **promovare** (`_handle_candidate_for_promotion`, l. 273-282) | **niciuna** | — |

**Scenariul concret, cu fereastră datată.** Fazele rulează A → … → C în
**aceeași trecere** (`continuous_learning.py:215` și `226`). Dacă decizia #8
e `approved` și, în aceeași rulare, `174e7e17` e evaluat
`candidate_for_promotion`:

1. Faza A → `_handle_candidate_for_promotion` → `propose_decision()` găsește
   #8 (`approved` **este** stare deschisă) și **îi suprascrie `evidence`** cu
   unul de promovare; `surface_decision(#8)` refuză (nu e `proposed`), deci
   #8 rămâne `approved`.
2. Faza C → `list_approved_decisions_for_target()` găsește #8, citește
   `decision_kind` (acum absent → **implicit `"promotion"`**, l. 800) și
   apelează `promote_challenger()`.

**Rezultat: ai aprobat o expirare, sistemul execută o promovare de campion.**
Fără ca nimeni să fi aprobat vreodată o promovare. Contrazice direct ADR-002.

Fereastra nu e teoretică: `174e7e17` e la 2 din 3 metrici semnificative, iar
a treia e, pe ritmul măsurat, la ~3 zile.

**Decizie propusă — reparație la nivelul INVARIANTULUI, nu al apelantului.**
Precedentul e în acest proiect, în aceeași familie de funcții:
`surface_decision()` a fost reparat pe 6 septembrie exact așa, iar docstring-ul
ei spune de ce — *„Fix la nivelul invariantului, nu al unui apelant"*. Garda
per-apelant a fost scrisă o dată și aplicată la una din trei căi; asta e
dovada empirică că nu scalează.

În `propose_decision()`, când există o decizie deschisă pe `target_key`:

- `status = 'approved'` → **nu se atinge nimic**, se întoarce `None`. Ce a
  aprobat omul e înghețat. (Comentariul de la linia 330 formulează deja
  regula: *„omul a aprobat un conținut anume, nu «ce se va nimeri la
  execuție»"* — doar că o impune pe o singură cale.)
- `status ∈ {'proposed','pending'}` și felul **diferă** → nu se atinge nimic,
  se întoarce `None`, se loghează explicit.
- felul e **același** → se actualizează `evidence` (comportamentul de azi,
  legitim: împrospătează cifrele aceleiași propuneri).

Garda `R3-Risk-1` din calea de rollback rămâne — devine redundantă, nu
greșită, și e a doua plasă.

### 4.2 F3b — pragul de expirare nu distinge „înțepenit" de „în urcare"

Măsurătoarea din §1.2. Pragul e `n ≥ 300`, singura condiție. Un Challenger cu
**2 din 3 metrici semnificativ mai bune** e, prin definiția porții de
promovare (`shadow_testing.evaluate_experiment()`, North Star #2), la o
singură metrică de `candidate_for_promotion`. A-l expira înseamnă a arunca
exact produsul pentru care politica există — iar `REJECTED(expired)` e stare
**terminală**: reluarea se face antrenând altul de la zero (n=0), nu revenind
la el. La ritmul măsurat, un înlocuitor ar reface drumul până la n≈380 în
~2 săptămâni.

**Decizie — varianta (ii), cu plafon `n ≥ 450`.** Nu se propune expirare cât
timp Challenger-ul are **≥2 din 3** metrici semnificativ mai bune decât
baseline-ul **ȘI `n < MAX_MATCHES_FOR_TREND_HOLD = 450`**. Peste plafon,
propunerea se emite oricum, cu trendul consemnat în `evidence`
(`trend_significant_metrics: 2`), ca omul să vadă că expiră ceva care arăta
bine pe două metrici din trei. Suprimarea se consemnează explicit în `summary`
(`expiry_skipped_trending: true`) — niciodată tăcut, fiindcă tăcerea e exact
defectul ADR-057.

### 4.2.1 Prima versiune a acestei decizii era GREȘITĂ, și datele au arătat-o

Recomandasem varianta (i), **fără plafon**, numind regula „autolimitată": ori
Challenger-ul trece a treia metrică, ori trendul se degradează. Declarasem
onest că n-am măsurat dacă poate sta la 2/3 la nesfârșit.

**Măsurat. Se întâmplă, și s-a întâmplat deja** — `challenger_evaluations`,
seria completă a lui `blend_v1/4e17c737`:

| n | 230 | 248 | 269 | 281 | 289 | 311 | 320 | **329** | 385 | 422 | 436 | 441 | 457 | 468 | 479 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| metrici sig. | 2 | 2 | 2 | 2 | 2 | 2 | 2 | **3** | 2 | 2 | 2 | 2 | 2 | 2 | 2 |

**13 din 15 evaluări la exact 2/3, pe 14 zile.** A atins 3/3 o singură dată
(n=329), a recăzut imediat și a rămas la 2/3 până a fost expirat prin decizia
#5 (aprobată 19 septembrie).

**Deci varianta (i) ar fi suprimat exact propunerea care a produs decizia #5**,
iar `4e17c737` ar ocupa și azi slotul `blend_v1`. Challenger-ul de acum,
`174e7e17` — cel pe care §1.2 îl arată în urcare — **n-ar exista.** Regula
„autolimitată" ar fi blocat familia pe care pretindea că o protejează.

**De ce m-am înșelat, formulat precis**: presupusesem două ieșiri din 2/3 (a
treia metrică vine, sau trendul se degradează). Există o a treia, care e de
fapt cea tipică: **staționarea**. Brier și log-loss sunt corelate puternic
între ele, iar acuratețea e metrica cu cel mai mult zgomot — plafonată
structural la ~76% de cele 23,9% remize (§Reperul extern din `CLAUDE.md`).
**2/3 nu înseamnă „aproape promovabil"; e starea de echilibru a unui
Challenger mediocru.**

### 4.2.2 De unde vine 450 — back-test pe toate seriile reale

Plafonul **nu** e un număr rotund ales din gust. E derivat din cele patru
serii existente și verificat contra fiecăreia:

| Challenger | A atins 3/3 la | Expirat la (decizia) | Plafonul 450 l-ar fi tăiat prematur? |
|---|---:|---:|---|
| `blend_v1/8ac89c70` (campion activ) | **207** | — | nu |
| `blend_v1/4e17c737` | **329** | 468 (#5) | **nu** — trece la 329, devine expirabil de la 450, #5 a venit la 468 |
| `xgboost_v1/6e7265c5` | niciodată | 458 (#7) | nu — la 458 era la **0/3**, regula de trend nici nu se aplică |
| `xgboost_v1/e638c1dc` | niciodată | 506 (#4) | nu — 0/3 pe toată seria |

**Plafonul de 450 reproduce exact toate cele trei expirări istorice** și nu
taie niciun Challenger înaintea punctului lui de trecere observat. Cel mai
târziu crossing măsurat e **329**; 450 e cu ~37% peste el, iar cele trei
expirări reale s-au produs la 458, 468 și 506 — toate peste plafon.

**Ce ar schimba decizia**: un Challenger care atinge 3/3 pentru prima dată la
`n > 450`. Nu există azi niciunul, pe nicio familie. Dacă apare, plafonul se
ridică la noul maxim observat × ~1,4, cu aceeași aritmetică — nu se elimină.

### 4.3 F3c — calea de promovare nu scrie niciodată `decision_kind`

`_handle_candidate_for_promotion` (l. 279-280) construiește `evidence` fără
`decision_kind`. Faza C compensează cu un **implicit**: `evidence.get(
"decision_kind", "promotion")` (l. 800). Confirmat în date: decizia #3
(promovarea lui `8ac89c70`, 23 august, `committed`) are `decision_kind` NULL.

Deci absența câmpului înseamnă **două lucruri diferite, după cine citește**:

| Cititor | Ce înțelege din absență |
|---|---|
| Faza C, `target_key = familie\|ligă` | promovare (implicit codat) |
| Faza C, `target_key = metric_name` | nu ajunge niciodată acolo (§2) |
| Ecranul, după D-11 | `FEL NECUNOSCUT` |

**Asta e un gol în reparația D-11 de pe 20 octombrie**, găsit la o zi de la
livrare și consemnat ca atare: o propunere de **promovare** — felul cu
consecința cea mai mare — s-ar afișa azi ca `FEL NECUNOSCUT`, nu ca
„PROMOVARE Champion". Nu e o eroare de randare: ecranul raportează fidel ce
scrie în `evidence`. Divergența e între ce scrie și ce va executa codul.

**Decizie propusă**: `_handle_candidate_for_promotion` scrie explicit
`evidence["decision_kind"] = "promotion"`, simetric cu calea de expirare
(l. 353). Implicitul din Faza C **rămâne** ca retrocompatibilitate pentru
rândurile istorice, dar nu mai are de deservit nicio propunere nouă.

Rândurile vechi nu se rescriu (ar șterge dovada). Sunt oricum toate
`committed`, deci nu apar niciodată în feed-ul `pending`.

---

## 5. Ce NU face acest ADR

- Nu promovează, nu expiră și nu respinge nimic. Nu atinge decizia #8 —
  aceea rămâne a proprietarului produsului, ADR-002.
- Nu introduce nicio tabelă, coloană sau migrare. Toate cele patru reparații
  folosesc câmpuri existente (`status`, `resolved_at`, `evidence`).
- Nu atinge calea de servire, nicio formulă, niciun motor.
- Nu activează niciun flag. Dacă implementarea cere unul, pornește oprit
  (North Star #3).
- Nu atinge `consensus_capture_samples` (append-only prin trigger).

---

## 6. Verificare cerută înainte de a declara implementarea încheiată

1. `pytest tests/` verde, cu teste noi pentru fiecare dintre cele patru
   reguli (F1 afordanța, F2 răcirea, F3a invariantul, F3b trendul, F3c felul
   explicit).
2. **Mutații obligatorii, fiecare trebuie să doboare un test anume**:
   - garda „`approved` nu se suprascrie" scoasă → scenariul §4.1 reprodus
     end-to-end, nu doar funcția izolată;
   - comparația de fel înlocuită cu „orice deschisă trece";
   - răcirea scoasă → propunere repetată imediat după `rejected`;
   - condiția de trend inversată (`≤2` în loc de `≥2`);
   - **plafonul `MAX_MATCHES_FOR_TREND_HOLD` scos** → `4e17c737` nu mai e
     expirabil niciodată (vezi 4.2.3);
   - `decision_kind="promotion"` șters din calea de promovare.

### 6.1 Back-test obligatoriu pe seriile REALE, nu doar teste sintetice

Regula de trend se validează rulând-o peste cele patru serii măsurate din
§4.2.2, ca date de test fixate în cod (nu citite din bază — testele rămân fără
rețea). Cerințele, fiecare un test separat:

| Serie | Ce trebuie să rezulte |
|---|---|
| `8ac89c70` (3/3 la n=207) | propunerea de expirare nu se emite niciodată |
| `4e17c737` | suprimată la n=230…320; **emisă de la n≥450**; la n=468 emisă — exact decizia #5 reală |
| `6e7265c5` | emisă la n=458 (0/3, trendul nu se aplică) — exact decizia #7 reală |
| `e638c1dc` | emisă (0/3 pe toată seria) — exact decizia #4 reală |
| `174e7e17` | suprimată la n=290 și 301 (2/3, sub plafon) |

Ultima linie e **contraponderea care contează**: dacă regula ar emite
propunerea la n=301, ar reproduce exact greșeala pe care ADR-ul o repară.
3. **Testul §4.1 se scrie pe LANȚUL A→C, nu pe `propose_decision` singură.**
   Defectul nu e vizibil în funcție; e vizibil în ordinea fazelor. Un test pe
   funcție ar trece și cu defectul prezent.
4. Zero atingere a căii de predicție, dovedit cu `git diff --stat` pe
   `oracle_engine.py`, `feature_engine.py`, `ml_predictor.py`,
   `recalibration.py`, `oracle_api.py` — gol.
5. După implementare, o rulare `night_sync` care confirmă: nicio propunere
   nouă pe `blend_v1|all` (trendul e ≥2/3), `summary` cu
   `expiry_skipped_trending: true`, sweep raportat.

---

## 7. Consecințe

**Pozitive**

- Dispare calea prin care o aprobare de expirare se poate executa ca
  promovare. E singurul element cu consecință ireversibilă din tot ADR-ul.
- O decizie aprobată devine imuabilă în conținut — ce a citit omul e ce se
  execută. Asta e, în fond, singura formă în care ADR-002 chiar înseamnă ceva.
- TTL-ul redevine real fără să producă flux zilnic de propuneri.
- Un Challenger în urcare nu mai e expirat la n=300.
- Decizia #6 iese din limb, într-un fel sau altul.

**Negative, acceptate conștient**

- Răcirea de 168 h înseamnă că o decizie respinsă din greșeală nu se repropune
  o săptămână. Mitigare: `fire_trigger` manual rămâne disponibil; o propunere
  pierdută o săptămână e mai ieftină decât una repetată 7 ori.
- Regula de trend ține un slot ocupat mai mult decât azi: până la **450** de
  meciuri în loc de 300, adică ~5 zile în plus la ritmul măsurat (~27/zi). Cost
  acceptat explicit, cu back-test care arată că nu schimbă niciuna din cele
  trei expirări istorice (§4.2.2).
- Plafonul e **empiric, nu teoretic** — derivat din patru serii. Se ridică doar
  cu aceeași aritmetică (max observat × ~1,4), niciodată „pentru siguranță".
- „Marchează ca executată" e o afirmație umană despre lumea exterioară, deci
  poate fi greșită. E totuși mai onest decât o decizie `approved` pe veci.

**Ce rămâne în afara scopului (Discovery Rule, de decis separat)**

- Contradicția internă a ADR-033 (produce T3a, interzice execuția) e
  **ocolită**, nu rezolvată, de varianta (i). Dacă surfacing-ul ajunge vreodată
  să însemne mai mult decât o comutare de flag, ADR-033 trebuie amendat
  explicit.
- Nimic nu verifică azi că fiecare `decision_kind` produs are un executant.
  Un fel nou adăugat mâine ar reintra exact în clasa F1. O gardă AST ar fi
  ieftină — nepropusă aici ca să nu umflu scopul.
