# ADR-080 — Stări terminale în `experiment_registry`

**Status**: **ACCEPTED** (aprobat explicit de proprietarul produsului, 2026-10-21)
**Implementat**: `main` @ `141f373` · backfill §5 **EXECUTAT** 2026-10-21
**Data**: 2026-10-21
**Autor**: sesiune Claude Code, la cererea proprietarului produsului
**Înlocuiește / amendează**: nimic. Completează ADR-018 (verdicte imuabile) și
ADR-002 (promovarea e exclusiv umană).

---

## 0. De ce acest ADR arată altfel decât cel anunțat

Propusesem, în `DE_URMARIT.md` §11, un ADR care să **lege
`experiment_registry` de `model_champions`** — statusul n-ar mai putea fi
`candidate_for_promotion` pentru un model deja activ.

**Analiza cerută înainte de scriere a infirmat acea propunere.** Ar fi
introdus o dependență nouă (evaluarea generică → registrul de campioni) ca să
repare un simptom, când cauza e alta și e mai simplă. Ce urmează descrie cauza
măsurată, nu cea presupusă.

---

## 1. Context — ce s-a măsurat, element cu element

Punctul de plecare: `experiment_registry` spune că `blend_v1/8ac89c70` e
`candidate_for_promotion`, iar `model_champions` îl arată **campion ACTIV** din
23 august. Sistemul afirmă că **campionul activ e un candidat de promovat**.

Formularea din `CLAUDE.md` D-10 atribuia asta baseline-ului înghețat
(ADR-072): cifra ar fi fost produsă pe 12 septembrie, pe un reper care
flatează. **Fals** — rândul a fost reevaluat pe 21 octombrie, pe
`baseline_source = 'shadow_control'`, și a rămas `candidate_for_promotion`.
Explicația comodă e eliminată prin măsurare.

### 1.1 Riscul operațional e ZERO — verificat pe trei căi independente

| Verificare | Rezultat |
|---|---|
| Cine citește `experiment_registry.status` în producție? | **Nimeni.** `get_experiment_registry()` are zero apelanți în afara propriului modul; `app.py`, `value_dashboard.py` și `oracle_engine.py` nu ating tabela. |
| Poate contradicția produce o promovare greșită? | **Nu.** `promotion_service` cere starea FSM `SUCCEEDED` (`8ac89c70` e `PROMOTED`) **și** citește verdictul imuabil din `challenger_evaluations`, nu din registru. Două porți, ambele independente de registru. |
| Poate `continuous_learning` propune repromovarea? | **Nu.** `_process_pair()` ia verdictul din `challenger_evaluation.evaluate_active_challenger()`, iar ținta din `challenger_manager.get_active_challenger()` — un model `PROMOTED` nu mai e activ, deci calea nici nu-l atinge. |

**Deci nu reparăm un risc, reparăm o afirmație falsă.** Asta e o distincție pe
care acest ADR o face explicit, ca să nu fie citit ca o urgență.

### 1.2 Cauza reală: registrul are stări terminale pe care nimeni nu le scrie

`shadow_testing` definește `promote_experiment()` (scrie `status="promoted"`)
și `deprecate_experiment()` (scrie `status="deprecated"`).

**Ambele au ZERO apelanți de producție** — singura apariție în afara
definiției e un test care le enumeră numele. Măsurat în producție: **zero
rânduri au purtat vreodată `promoted` sau `deprecated`**; cele 7 rânduri
existente sunt `monitoring` (4), `candidate_for_promotion` (1), `rejected` (1),
`insufficient_data` (1).

Calea de promovare (`promotion_service` → `model_champions` + FSM
`challengers`) **nu anunță niciodată registrul**. Deci un model promovat
rămâne, pe vecie, la ultimul lui verdict statistic.

### 1.3 Agravant: verdictul se recalculează la nesfârșit pe date înghețate

`blend_v1/8ac89c70` are **ultima scriere în `shadow_predictions` pe 23 august,
09:23:17** — cu **13 minute** înainte de promovarea lui (`promoted_at`
09:36:27). 394 de rânduri, neschimbate de atunci.

`evaluate_all_active_experiments()` nu are **niciun filtru de viață**: iterează
peste `get_distinct_experiments()`, adică peste orice experiment care a scris
vreodată un rând. Deci recalculează în fiecare noapte același verdict, pe
același set, și obține același rezultat — prin construcție.

Iar `_update_registry()` scrie `last_evaluated_at = now()` **necondiționat**.
Rândul **arată proaspăt** (evaluat azi) în timp ce măsurătoarea din spate e de
acum două luni. E forma **inversată** a capcanei marcajului înghețat reparate
pe 26 august: acolo conținutul se împrospăta și marcajul mințea că e vechi;
aici marcajul minte că e proaspăt.

### 1.4 O citire alternativă, testată și RESPINSĂ

Înainte de a scrie, am considerat că verdictul ar putea fi o măsurătoare
**curentă și legitimă** — campionul `blend_v1` comparat permanent cu Oracle,
exact ce cere ADR-051 („trei motoare permanent comparabile"). În acea citire,
`candidate_for_promotion` ar însemna „bate Oracle pe toate trei metricile",
ceea ce pentru un campion e **veste bună**, nu contradicție.

**Infirmată de §1.3**: setul lui e înghețat din august, deci nu măsoară nimic
curent. Citirea alternativă ar fi fost corectă dacă rândurile ar fi continuat
să curgă; nu curg.

---

## 2. Decizie

**`experiment_registry.status` capătă stări TERMINALE, iar evaluarea
statistică nu le mai poate suprascrie.**

1. **`promoted` și `deprecated` sunt stări terminale.** Ele descriu ce s-a
   decis despre un experiment, nu ce măsoară el. Un verdict statistic
   (`candidate_for_promotion` / `monitoring` / `rejected` /
   `insufficient_data`) descrie măsurătoarea. **Cele două nu mai trăiesc în
   același spațiu fără ordine de precedență.**

2. **Scriitor unic pentru `promoted`**: **orchestratorul**
   (`continuous_learning._phase_c_execute_approved`), imediat după o promovare
   reușită. **NU** `promotion_service` — vezi §7, o gardă existentă interzice
   asta, și are dreptate.

3. **Evaluarea generică nu atinge rândurile terminale.**
   `evaluate_all_active_experiments()` le sare, deci nici statusul, nici
   `last_evaluated_at` nu se mai rescriu. Rândul rămâne la data promovării —
   adevărul lui.

4. **Eșecul scrierii în registru NU oprește promovarea.** Registrul e
   evidență, nu poartă. Aceeași regulă ca la rândul de audit `night_sync`
   (21 oct): *observabilitatea nu are voie să rupă lucrul pe care îl observă*.

---

## 3. Ce NU face acest ADR, și de ce — fiecare punct măsurat

### 3.1 NU leagă registrul de `model_champions`

Era propunerea inițială. Ar fi însemnat ca evaluarea statistică să citească
registrul de campioni ca să-și decidă verdictul — o dependență nouă, către un
strat superior, pentru a corecta un simptom. Cu §2 pct. 2-3, legătura nu e
necesară: rândul devine terminal **în momentul promovării**, din interiorul
căii care promovează.

### 3.2 NU adaugă un filtru „sare experimentele fără date noi"

**Era planul meu, și e GREȘIT.** Un set de rânduri shadow înghețat poate
produce în continuare un verdict care se schimbă, fiindcă **rezultatele se
rezolvă mai târziu**: `actual_result` se completează după ce meciul se joacă,
iar `n_matches_evaluated` crește pe măsură ce meciurile din set capătă
rezultat. Deci „niciun rând nou" **nu** înseamnă „verdictul nu se poate
schimba", iar un filtru pe acel criteriu ar îngheța verdicte încă vii.

Consecința acceptată conștient: `blend_v1/4e17c737` (ultima scriere 19
septembrie, status `monitoring`) va continua să primească `last_evaluated_at`
proaspăt. **Falsa prospețime rămâne pentru rândurile NEterminale** — e
documentată aici, nu reparată, fiindcă reparația sigură cere un semnal pe care
nu-l avem azi.

### 3.3 NU cablează `deprecated`

Rollback Engine (ADR-037) e implementat dar **neactivat în producție** (R4). A
scrie `deprecated` din el ar fi cod pe o cale care nu rulează. Rămâne definit
în registru, cu zero scriitori, **declarat ca atare** — nu pretindem că e
cablat.

### 3.4 NU rescrie retroactiv istoricul

Cele 394 de rânduri `shadow_predictions` ale lui `8ac89c70` și verdictele din
`challenger_evaluations` rămân neatinse. Singura corecție retroactivă propusă
e **un rând**, cu SQL arătat și confirmare explicită (North Star #6) — vezi §5.

---

## 4. Consecințe

**Pozitive**

- Registrul nu mai poate afirma că un campion activ e un candidat de promovat.
- `last_evaluated_at` nu mai minte pentru rândurile terminale.
- `promote_experiment()` încetează să fie cod mort — devine calea declarată.
- Munca nocturnă scade marginal (un experiment sărit azi, mai multe în timp).

**Negative, acceptate**

- Un al doilea scriitor pe `experiment_registry.status`. Mitigat prin
  precedență explicită (terminal > statistic) și prin gardă de test.
- Falsa prospețime rămâne pe rândurile neterminale (§3.2).
- Dacă un model promovat e vreodată retras fără Rollback Engine, rândul lui
  rămâne `promoted` — stare terminală, prin definiție. Corectarea ar fi o
  scriere manuală, cu aceleași reguli ca orice scriere pe producție.

**Neutre**

- Zero schimbare de comportament în servire, predicție sau poarta de
  promovare. Calea de predicție nu e atinsă.
- Zero schemă nouă, zero migrare. `status` e deja text liber în tabelă, iar
  `promoted_at`/`promoted_by` există deja (scrise de `promote_experiment()`).

---

## 5. Corecția retroactivă a rândului existent — cere confirmare separată

`blend_v1/8ac89c70` e promovat din 23 august, dar registrul nu știe. După
implementare, rândul **nu se corectează singur** (promovarea lui s-a întâmplat
înainte de cablare).

```sql
-- De arătat și confirmat ÎNAINTE de rulare (North Star #6).
-- Gardă triplă: cheia completă + statusul curent, ca o schimbare intermediară
-- să facă instrucțiunea inofensivă în loc de greșită.
UPDATE experiment_registry
SET status = 'promoted',
    promoted_at = '2026-08-23 09:36:27.787184+00',
    promoted_by = 'ADR-080-backfill'
WHERE experiment_name = 'blend_v1'
  AND experiment_version = '8ac89c70-8727-459f-aa42-08a2edd16431'
  AND league_scope = 'all'
  AND status = 'candidate_for_promotion';
```

`promoted_at` e copiat din `model_champions` id=5, nu inventat.

### ✅ EXECUTAT — 2026-10-21, cu aprobare explicită

**Precondițiile au fost recitite ÎNAINTE de scriere, nu presupuse din ADR:**

| Verificare | Rezultat |
|---|---|
| Cheia completă există | `blend_v1` / `8ac89c70-8727-459f-aa42-08a2edd16431` / `all` ✅ |
| Statusul din gardă | `candidate_for_promotion` ✅ |
| `promoted_at`/`promoted_by` în registru | **NULL** — nimic de suprascris ✅ |
| `model_champions.promoted_at` | `2026-08-23 09:36:27.787184+00` — identic cu cifra din ADR ✅ |
| Celelalte 2 rânduri `blend_v1` | `monitoring`, fără campion — negarantate de gardă, deci neatinse ✅ |

**Rezultat**: exact **un rând** actualizat (`RETURNING` l-a confirmat).
Starea registrului după: `monitoring` 4 · **`promoted` 1** · `rejected` 1 ·
`insufficient_data` 1 — **zero `candidate_for_promotion`**. Contradicția
„campionul activ e un candidat de promovat" nu mai există, iar acesta e
**primul rând `promoted` din istoricul tabelei**.

**Ordinea a contat, și e aceeași lecție ca la Clasa B din D-13**: codul a ajuns
pe `main` **înainte** de backfill. Invers, evaluarea nocturnă n-ar fi avut încă
garda terminală și ar fi suprascris `promoted` înapoi la verdictul statistic,
la prima rulare.

**`promoted_by = 'ADR-080-backfill'`, nu `'ADR-030-continuous-learning'`** —
deliberat. A doua variantă ar fi făcut rândul să arate ca scris de calea
normală, ceea ce e fals: promovarea reală a avut loc pe 23 august, marcajul e
o corecție retroactivă de azi. Trasabilitatea cere să se vadă diferența (#9).

---

## 6. Verificare cerută după implementare

1. `pytest tests/` verde, cu aritmetica testelor închisă exact.
2. Calea de predicție neatinsă: `git diff` gol pe `oracle_engine.py`,
   `feature_engine.py`, `ml_predictor.py`, `recalibration.py`, `app.py`,
   `oracle_api.py`.
3. La prima rulare de noapte după merge: `last_evaluated_at` al rândului
   terminal **nu** avansează, iar celelalte 6 rânduri se evaluează normal.
4. Mutații verificate (minim): garda terminală ștearsă · apelul din Faza C
   eliminat · eșecul scrierii în registru propagat ca excepție · `deprecated`
   omis din mulțimea terminală.

---

## 7. Discovery Rule — un invariant pe care acest ADR nu-l identificase

**Prima implementare a pus apelul în `promotion_service.promote_challenger()`
și a căzut pe o gardă EXISTENTĂ**, la rularea suitei:

```
tests/test_promotion_service.py::test_module_does_not_import_shadow_testing
  „promotion_service.py nu are voie sa importe shadow_testing —
   Promotion executa, nu decide"
```

Garda vine din ADR-019 și **are dreptate**: `shadow_testing` e stratul care
**decide** (calculează verdicte); Promotion doar **execută** o decizie deja
luată de om. Un import acolo ar fi legat executantul de decident.

**Nu am șters garda.** Am mutat cablarea în orchestrator
(`continuous_learning`), care:

- cunoaște deja ambele straturi — importă `promote_challenger` de la ADR-030;
- e **singurul apelant legitim** al promovării (whitelist explicit în
  `test_module_has_only_known_importers`);
- nu are nicio gardă care să-i interzică `shadow_testing` (verificat).

**Consecință asupra §2 pct. 2**: scriitorul declarat al stării `promoted` e
orchestratorul, nu serviciul de promovare. Pentru registru, efectul e identic;
pentru arhitectură, diferența e tot.

**Gardă nouă, permanentă**: `test_promotion_service_ramane_CURAT_de_shadow_testing`
în fișierul de teste al ADR-080, ca mutarea asta să nu fie anulată din
neatenție la o refactorizare viitoare. Verificată prin mutație (M7: reimport
în `promotion_service` → **2 teste cad**).

**De reținut ca metodă**: invariantul n-a fost găsit citind documentele, ci de
suita de teste, la prima rulare completă. Un ADR scris cu grijă poate rata un
contract pe care codul îl apără deja — motiv pentru care suita se rulează
**înainte** de a declara o implementare terminată, nu ca formalitate la final.
