# ADR-077 — Semnalul care decide dacă providerii de rezervă mai sunt întrebați

**Status**: **ACCEPTED** (aprobat explicit de proprietarul produsului, 2026-10-27) — **IMPLEMENTAT în aceeași zi**

> ## 🔴 CIFRELE DE LA §1 ȘI §2.1 SUNT DIN 19 OCTOMBRIE ȘI NU MAI DESCRIU PREZENTUL
>
> Remăsurat pe producție, **27 octombrie**, exact același tabel:
>
> | Fereastră | `referee IS NULL` (criteriul vechi) | `home_shots IS NULL` (lipsesc real) | total terminate |
> |---|---:|---:|---:|
> | 7 zile | **2** *(era 0)* | **2** *(era 95)* | 199 |
> | 14 zile | **2** *(era 0)* | **2** *(era 229)* | 390 |
> | 60 zile | **2** *(era 0)* | **8** *(era 653)* | 1218 |
>
> **Golul s-a prăbușit, 653 → 8.** Cauza nu e acest ADR: e reparația ADR-076 (extragerea statisticilor Flashscore) plus recuperarea restanței D-B. Acoperirea curentă e **197/199 = 99,0%**.
>
> **Cele 8 se despart curat**, și distincția contează:
> - **2 de pe 26 oct** (PSG–Lyon, Sevilla–Osasuna), fără arbitru încă — simplă **latență**, pe care criteriul VECHI le prinde corect;
> - **6 MLS din 9-13 septembrie**, toate **cu** arbitru scris și statistici lipsă — reziduul penei de 39 de zile, exact clasa pe care criteriul vechi nu o poate vedea niciodată.
>
> **§2.1 e INVALIDAT ca argument de volum.** Spunea „după schimbare SFI ar primi ~95 de meciuri pe săptămână" — acela era costul care făcea din asta o decizie grea. Cifra reală azi, pe fereastra de 2 zile a sincronizării zilnice, e de ordinul **2**, iar reziduul total e **8**. Consecință: **recomandarea de etapizare cu `limit=20` devine inutilă** — volumul natural *este* deja eșantionul mic pe care §2.1 îl cerea. Nu s-a aplicat niciun plafon artificial, deliberat.
>
> **Argumentul care rămâne, și care a justificat implementarea**: proxy-ul nu e *corect*, e doar **din nou aliniat prin accident**. Funcționează azi fiindcă Flashscore scrie arbitrul și statisticile împreună. Când extragerea lui se rupe — s-a rupt de două ori — scrie arbitrul și ratează statisticile, criteriul redevine 0, și mergem orbi. Deci lărgirea nu e despre volum, e un **detector**: la următoarea rupere, meciurile sunt rutate imediat către SFI (degradat, dar nenul) în loc să nu colecteze nimic în tăcere.
>
> **Și costul care bloca decizia s-a prăbușit cu el**: „SFI trece de la 0 la ~95/săptămână, cu rată de succes nemăsurată" devine „de la 0 la ~2/săptămână". Pe un asemenea volum, rata reală de succes a SFI — nemăsurată din august — devine ceva ce se poate **observa în siguranță**, nu un risc de asumat. Rămâne de citit la prima rulare de după (§3 pct. 4).
>
> **Cum a ieșit la iveală**: din întrebarea proprietarului produsului „nu îmi amintesc problema, trebuie făcut acum?". Răspunsesem cu o oră înainte că ADR-ul „are acum dovada care îi lipsea" — dovada aceea era doar că SFI întoarce HTTP 200 după reparația parametrului de dată. **Nu remăsurasem golul**, deci purtasem cifrele din 19 oct ca fiind curente. A doua instanță în aceeași zi a clasei „o intrare de listă e o ipoteză, nu un fapt".
**Derivat din**: ADR-076 §2.3 și §6 D-A (descoperire în timpul investigației, Discovery Rule)
**Atinge**: contractul de rutare din ADR-045 (Single Owner) și criteriul din ADR-041
**Nu atinge**: nicio formulă, niciun motor de predicție, nicio coloană nouă

---

## 1. Context — calea Soccer Football Info e moartă, și nu de ieri

`sync/sync_match_statistics.py:119` e **singurul** apelant (verificat prin
grep) al lui `get_finished_matches_missing_stats()`, și o cere cu
`require_referee=True`. Criteriul acelui mod e `referee IS NULL`.

Măsurat read-only pe producție, 2026-10-19:

| Fereastră | `referee IS NULL` (criteriul de azi) | `home_shots IS NULL` | `home_possession IS NULL` | `home_xg_actual IS NULL` | total terminate |
|---|---:|---:|---:|---:|---:|
| 7 zile | **0** | 95 | 95 | 95 | 185 |
| 14 zile | **0** | 229 | 229 | 229 | 322 |
| 60 zile | **0** | 653 | 653 | 675 | 1208 |

**Zero pe fiecare fereastră.** Soccer Football Info nu primește niciun meci de
procesat, niciodată. Nu e o degradare recentă: `referee` e populat pe **100%**
din meciurile terminate (679/679 august, 534/534 septembrie, 232/232
octombrie), deci criteriul întoarce zero de când Flashscore a devenit al doilea
scriitor al câmpului.

### 1.1 De ce proxy-ul a fost corect, și când a încetat să fie

Docstring-ul funcției o spune explicit, și era adevărat când a fost scris:

> `require_referee` [ADAUGAT Sprint 1 Faza 1, ADR-041] — … `referee` e populat
> STRICT de acest adaptor, deci e semnalul corect de „lipsesc datele bogate"

La ADR-041, Soccer Football Info era singurul scriitor al lui `referee`, deci
`referee IS NULL` ⇔ „SFI n-a atins încă meciul" ⇔ „lipsesc datele bogate".
Echivalența era reală.

**ADR-044/045 au adus Flashscore ca al doilea scriitor al aceluiași câmp**
(`providers/flashscore/normalizer.py:533`, `"referee": info.get("Referee:")`),
iar nimeni — eu inclusiv, până la investigația ADR-076 — nu a revizitat
proxy-ul. De atunci, prima parte a echivalenței s-a rupt: `referee` scris
înseamnă „un provider a atins meciul", nu „datele bogate există".

**Un ADR a invalidat precondiția unui alt ADR, tăcut.** Asta e clasa de defect,
nu cifra. Nici ADR-041, nici ADR-044/045 nu greșesc în sine; ce lipsea e o
verificare care să prindă momentul în care un câmp-martor capătă al doilea
scriitor.

### 1.2 Cum s-a văzut

Deloc, 39 de zile. În septembrie-octombrie, extragerea statisticilor
Flashscore a fost moartă (ADR-076), dar extragerea arbitrului a continuat
impecabil — deci fiecare meci primea `referee`, dispărea din lista
providerilor de rezervă, și rămânea fără statistici. Plasa de siguranță
exista, era cablată, și nu putea să se declanșeze niciodată.

---

## 2. Decizie propusă

### Varianta recomandată: (ii) criteriul citește coloanele ȚINTĂ

`get_finished_matches_missing_stats()` primește un mod nou în care „lipsesc
datele" se citește din coloanele pe care sincronizarea chiar vrea să le
completeze — `home_shots IS NULL` (sau o combinație explicită) — în loc de un
câmp-martor.

**De ce (ii) și nu mutarea proxy-ului pe alt câmp**: un martor poate oricând să
capete al doilea scriitor, exact ce s-a întâmplat aici. O coloană-țintă nu
poate minți despre propria absență. Varianta (i) — „găsim un câmp pe care doar
SFI îl scrie" — ar reface același aranjament fragil și ar cere, la fiecare ADR
viitor care adaugă un scriitor, ca cineva să-și amintească de acest ADR.

Măsurat ca `home_shots` și `home_possession` dau cifre **identice** pe toate
cele trei ferestre (95/229/653), deci alegerea între ele nu schimbă nimic azi;
`home_xg_actual` diferă (675 vs 653 la 60 de zile) — cele 22 de meciuri în plus
sunt cazuri cu șuturi dar fără xG, tipic calificări de cupă unde Flashscore nu
publică xG. **Recomand `home_shots`**: e cel mai larg câmp comun celor doi
provideri, și nu cere SFI pentru meciuri la care golul e structural la sursă.

### 2.1 Consecința de volum, care face din asta o decizie și nu un fix

Azi SFI procesează **0** meciuri. După schimbare ar primi **~95 pe săptămână**.

Asta nu e un detaliu de implementare:

- e consum real de cotă la un provider extern, nemăsurat în regimul nou;
- e timp real adăugat într-un pas de pipeline care azi se termină instant
  (lista goală);
- **și o parte din cele 95 nu sunt recuperabile de nimeni** — meciuri din
  competiții pe care SFI nu le acoperă. Câte, **nu se știe**: nu există
  măsurătoare, pentru că nu s-a mai făcut niciun apel. Nu o estimez.

**Recomandare de etapizare**: prima rulare după schimbare cu un `limit` mic
(ex. 20) și raport, ca rata reală de succes a SFI să fie **măsurată** înainte de
a-i da 95 de meciuri pe săptămână. „Verificat, nu presupus" se aplică și
beneficiului, nu doar riscului.

### 2.2 Ce rămâne neatins, deliberat

- **`flashscore_data_completeness.has_stats` NU se schimbă.** Rămâne ce e
  documentat să fie: prezența paginii descărcate. Filtrul Single Owner care îl
  citește (`get_match_ids_with_complete_flashscore_stats`) devine însă
  redundant sub criteriul (ii): un meci care are `home_shots` scris nu mai
  intră în listă, indiferent de flag. **Propun să rămână pe loc**, ca a doua
  plasă, nu să fie șters în același pas — ștergerea unui filtru și schimbarea
  criteriului în același commit ar face imposibil de atribuit orice efect.
- Plafonul PostgREST: `get_match_ids_with_complete_flashscore_stats` folosește
  un singur `.in_(…)`, iar plafonul de 1000 a fost deja reparat de patru ori în
  proiect. Sub criteriul nou lista de intrare crește de la 0 la ~95-653, deci
  **intră în zona de risc**. De chunk-uit la 500 în același pas, cu test.

---

## 3. Verificare cerută

1. Test că modul nou citește coloana-țintă, nu martorul; și că modul vechi
   rămâne neschimbat pentru orice alt apelant (azi nu există, dar contractul e
   public).
2. Test de chunk-uire peste 500 de id-uri (clasa deja reparată de patru ori).
3. Mutații: criteriul inversat, chunk-ul scos, filtrul Single Owner lăsat să
   primească o listă mare.
4. **Pe date reale**: o rulare cu `limit=20`, cu raport pe rata de succes SFI
   per competiție. Starea „înainte": 0 meciuri procesate, de la cel puțin
   2026-08-01 (prima dată măsurabilă).

---

## 4. Consecințe

**Pozitive**: plasa de siguranță pentru statistici redevine funcțională după ce
a fost inertă de la activarea Flashscore FDL; clasa „câmp-martor cu al doilea
scriitor" dispare în locul ăsta, în loc să fie mutată.

**Negative, de acceptat conștient**: consum nou la un provider extern, cu rată
de succes necunoscută; și un pas de pipeline care azi costă zero va costa ceva.

**Ce NU rezolvă**: restanța istorică (ADR-076 D-B, decizie separată). Criteriul
nou privește fereastra de sincronizare zilnică, nu recuperarea retroactivă.

**Gol rămas deschis, mai larg decât acest ADR**: nimic nu detectează, azi, când
un ADR nou adaugă un al doilea scriitor pe un câmp folosit de altul ca martor.
`tests/test_canonical_feature_ownership.py` (ADR-036) impune owner unic pentru
`FEATURE_COLUMNS`, dar `referee` nu e în acel set.

### 4.1 Garda statică evidentă e OARBĂ — măsurat, nu presupus (2026-10-19)

Reparația de clasă părea să fie o gardă AST în idiomul deja folosit de proiect:
„orice coloană folosită ca martor într-o interogare de rutare trebuie să aibă
exact un scriitor". Am scris scanarea înainte de gardă, exact ca să nu livrez
un instrument nedovedit. Rezultatul, pe codul de azi:

| Coloană | Scriitori găsiți de scanare |
|---|---|
| **`referee`** | **1** — `soccerfootballinfo_match_statistics_adapter.py` |
| `home_shots` | 1 — același |
| `home_possession` | 2 |
| `home_xg_actual` | 2 |

**Garda ar fi declarat `referee` sănătos** — adică ar fi trecut verde pe exact
defectul care a produs acest ADR. Cauza: criteriul „dicționar cu cheia X **și**
apel de scriere, în ACELAȘI modul" nu urmărește calea Flashscore, unde
înregistrarea se construiește în `providers/flashscore/normalizer.py:533` și se
scrie din `providers/flashscore/persistence.py`. Două module, deci invizibilă.

A urmări fluxul între module ar fi analiză statică reală (fragilă, și cu
propriile puncte orbe). **Deci reparația de clasă NU e o gardă statică** —
instrumentul corect e de tip *date*, în idiomul clasei 7 din
`check_data_health`: **o interogare de rutare care întoarce ZERO candidați în
timp ce datele pe care le gardează lipsesc pe ≥N meciuri** e, prin construcție,
un proxy rupt. Nu poate fi păcălită de structura codului, și ar fi declanșat
aici.

**Nefăcut în acest ADR**, dar scris ca să nu se construiască varianta oarbă:
cine reia subiectul pornește de la instrumentul pe date, nu de la gardă AST.
A patra instanță în proiect a lecției „o gardă care își citește propriul
comentariu / propria structură nu dovedește nimic" (după `pipefail`, numele de
secrete, docstring-ul ADR-073).

---

## 5. Implementare (2026-10-27)

**Varianta (ii), exact cum a fost propusă.** Trei schimbări, toate în stratul
de date și la apelant — **zero atingere a vreunei formule sau a vreunui motor**
(verificat: `git diff` pe `oracle_engine.py`, `feature_engine.py`,
`ml_predictor.py`, `recalibration.py`, `app.py` e GOL).

1. **`database/queries.get_finished_matches_missing_stats()`** — parametru nou
   `target_missing: bool = False`. Când e `True`, filtrul e `home_shots IS
   NULL`. **Modul vechi rămâne neschimbat** (`require_referee` → `referee IS
   NULL`; implicit → `home_possession IS NULL`): contractul funcției e public,
   iar „n-are alt apelant azi" nu e un motiv să-l rupi tăcut.
   **Precedență explicită și testată**: `target_missing` câștigă peste
   `require_referee`. Nu se aruncă excepție — funcția nu aruncă niciodată, prin
   contract.
2. **`sync/sync_match_statistics.py`** — singurul apelant de producție trece pe
   `target_missing=True`.
3. **`get_match_ids_with_complete_flashscore_stats()`** — chunk-uire la 500
   (§2.2). Sub criteriul vechi lista de intrare era mereu **goală**, deci un
   singur `.in_(…)` nu putea atinge plafonul PostgREST de 1000; sub criteriul
   nou devine nevidă și poate crește. **A cincea instanță a unei clase deja
   reparată de patru ori**, reparată preventiv. La eroare se întoarce setul
   **GOL, nu parțialul** — un parțial ar trimite la providerii de rezervă
   meciuri pe care Flashscore le-a acoperit deja, adică exact risipa pe care
   Single Owner (ADR-045) previne.

**§2.2 respectat**: `flashscore_data_completeness.has_stats` **nu** s-a atins,
iar filtrul Single Owner **rămâne pe loc** ca a doua plasă — ștergerea unui
filtru și schimbarea criteriului în același commit ar face imposibil de
atribuit orice efect.

**13 teste** (`tests/test_adr077_fallback_routing_signal.py`), **6 mutații,
toate prinse**: criteriul căzut înapoi pe martor · precedență inversată ·
apelantul revenit la `require_referee` · chunk-ul scos · plafonul urcat peste
1000 · parțialul întors la eroare. Garda pe apelant folosește **AST**, nu text,
fiindcă comentariul care explică reparația conține chiar șirul
`require_referee` — a șasea instanță a clasei `pipefail`, unde o verificare
textuală ar da fals pozitiv pe codul CORECT. Plus o gardă pe tot codul de
producție: dacă apare vreodată un apelant nou cu `require_referee=True`, cade.

### 5.1 Un defect găsit în propriile teste, prin mutație

Mutația „la eroare întoarce parțialul în loc de setul gol" **a trecut** la
prima rulare. Cauza nu era în cod: falsul meu întorcea `data: []` pe toate
bucățile, deci `gasite` rămânea gol oricum — **parțialul era indistinct de
setul gol**, iar testul nu putea separa cele două ramuri, deși era verde.
Reparat făcând prima bucată să întoarcă date reale. **Un test care nu poate
distinge ramurile pe care le judecă nu testează nimic**, și singurul lucru care
a arătat-o a fost mutația.

### 5.2 Două teste existente actualizate, nu șterse

`tests/test_sync_match_statistics.py` avea două stub-uri cu semnătura fixă
`(days_back, require_referee, include_id)`, iar unul codifica
`calls == [(3, True, True)]`. Nu afirmau o proprietate greșită — erau stub-uri
cu semnătură învechită. Motivul original al lui `require_referee=True`
(Sprint 3: „fără el, un meci completat de FreeLF cu possession+xG dispărea
permanent din rezultat") a fost **păstrat în docstring ca istoric**, cu
explicația de ce nu mai e suficient. Preocuparea aceea rămâne acoperită:
`home_shots` e disjunct de `home_possession`, deci un meci completat de FreeLF
rămâne în listă pentru Soccer Football Info.

### 5.3 Ce rămâne de citit la prima rulare de după (§3 pct. 4)

- Cele **2** meciuri recente intră în listă și SFI e apelat efectiv pentru ele
  (`provider_call_log`, `soccerfootballinfo`, HTTP 200 — reparat pe 26 oct).
- **Rata reală de succes a SFI**, nemăsurată din august fiindcă nu s-a mai
  făcut niciun apel. Starea „înainte": **0 meciuri procesate**, de la cel puțin
  2026-08-01.
- Cele **6 MLS din septembrie** apar în fereastra de 60 de zile, dar
  sincronizarea zilnică rulează cu `days_back=2`, deci **nu** le va atinge
  singură. Recuperarea lor e o decizie separată, nu un efect al acestui ADR.
