# ADR-037 — Learning Core: Rollback Engine & Champion Guardian

**Status**: Accepted (arhitectură) — pre-implementare. Ratificat ca versiune de referință a arhitecturii; implementarea urmează în etape dedicate (R1–R4), fiecare cu propriul review, per disciplina ADR-035.

**Data**: 2026-07-21

**Relații**:
- **Extinde**: ADR-015 (training-run history & champion comparison), ADR-016 (challenger FSM), ADR-017 (challenger shadow logging), ADR-018 (challenger shadow evaluation), ADR-019 (promotion architecture), ADR-030 (continuous learning), ADR-031 (n-way serving).
- **Nu modifică niciun contract Frozen**: `PROMOTION_CONTRACT.md` rezervă explicit Rollback ca „mecanism simetric, dar SEPARAT, viitor, cu propriul contract". Acest ADR este acel contract. `RUNTIME_CONTRACT.md`, `ATOMICITY_CONTRACT.md`, `PROMOTION_SERVICE_CONTRACT.md` rămân neatinse.
- **Guvernanță**: activarea promovării/rollback-ului automat (fără om în buclă) rămâne în afara scopului — contrazice ADR-002 și cere un ADR dedicat separat.

**Notă de stil (normativă pentru acest document)**: ADR-037 e un document de arhitectură — responsabilități, contracte, invariante, decizii. Detaliile de implementare (algoritmi, praguri numerice exacte, SQL, clase, funcții) NU intră aici; ele aparțin unui document de implementare ulterior (`docs/04_LEARNING_CORE/CHAMPION_GUARDIAN_IMPLEMENTATION.md`, nescris încă) și PR-urilor R1–R4. Astfel ADR-ul rămâne stabil chiar dacă implementarea evoluează (per `FROZEN_REGISTRY.md`, Change Policy — detaliile de implementare nu necesită ADR).

---

## 1. Context

Ciclul de viață al campionului e azi deschis pe jumătate. Promovarea e implementată, contractată și — verificat — **activă în servire fără flag**: `oracle_engine._initialize_ml()` seedează campionul ori de câte ori un rând activ din `model_champions` e utilizabil (cele 6 condiții din `RUNTIME_CONTRACT.md`), fără un `champion_serving_enabled`. În consecință, prima promovare devine live imediat și, azi, **ireversibilă prin orice mijloc automat**: `rollback_plan` din decizia T3a de promovare e un simplu șir descriptiv, nu o cale executabilă.

Acest ADR închide ciclul: face un campion promovat **reversibil** (Rollback Engine) și face degradarea lui **observabilă și clasificabilă** fără a consuma slotul de challenger și fără a re-rula vreun model (Champion Guardian).

## 2. Fundament conceptual — Rollback NU este opusul Promotion

Aceasta e cea mai importantă distincție a documentului, cu efect pe termen lung:

> **Promotion** schimbă campionul pentru că există **dovadă că un alt model e mai bun**.
> **Rollback** schimbă campionul pentru că **modelul curent nu mai e de încredere**.

Sunt două decizii de domeniu distincte, cu întrebări, dovezi și declanșatoare diferite — nu două direcții ale aceleiași operații.

| | Promotion | Rollback |
|---|---|---|
| Întrebarea | „Există un model *mai bun*?" | „Modelul curent mai e *de încredere*?" |
| Dovada | verdict comparativ challenger vs. campion (Pasul 4, imuabil) | sănătatea campionului activ (structurală sau statistică) |
| Sursa de date | predicții shadow (treatment vs. control) | predicții *servite* + rezultate reale |
| Declanșator | Challenger Evaluation | Champion Guardian |
| Motivul | superioritate demonstrată | pierdere de încredere (regresie / eroare / date / decizie umană) |

Un sistem care ar trata Rollback ca „un-promote" ar cupla accidental cele două lanțuri de decizie. Ele rămân separate: componente separate, evenimente separate, contracte separate. (Simetria e strict la nivel de *mecanism de scriere* — vezi §3 — nu la nivel de decizie.)

## 3. Decizie D1 — Rollback Engine (append-only re-promovare a predecesorului)

Rollback e un **eveniment de domeniu propriu**, cu un singur efect logic: campionul activ curent (degradat) e retras, iar predecesorul lui redevine campion activ. Mecanic, e exprimat **append-only**, respectând integral triggerul de imuabilitate `model_champions` (migrarea 005, Frozen prin ADR-019):

- Rândul activ curent primește singura mutație pe care triggerul o permite (activ → istoric).
- Predecesorul redevine activ printr-un **rând nou** (nu prin reactivarea rândului istoric, pe care triggerul o interzice).

**Invariante**:
- Rollback atinge **exclusiv** `model_champions`. NU atinge `challengers` (ambele rânduri FSM implicate sunt deja terminale `PROMOTED`) — deci NU redeschide FSM-ul Challenger, spre deosebire de Promotion.
- Cele două scrieri sunt **o singură unitate atomică** (aceeași proprietate observabilă cerută de `ATOMICITY_CONTRACT.md` pentru Promotion — fie ambele efecte, fie niciunul). Mecanismul concret (o funcție Postgres) urmează precedentul deja existent, dar rămâne detaliu de implementare.
- **Single owner**: un serviciu nou, cu un singur use-case și un singur punct de intrare public, e proprietarul exclusiv al evenimentului Rollback — exact disciplina din `PROMOTION_SERVICE_CONTRACT.md` (Promotion Service e singurul care emite Promote; Rollback Service e singurul care emite Rollback).
- **Ținta de reversie** e predecesorul imediat al campionului activ (rândul pe care campionul curent l-a supersedat). Dacă nu există predecesor (campionul degradat a fost primul), Rollback refuză explicit — nicio aproximare (Regula #8).
- Rollback în lanț (revenirea repetată, mai mult de un pas) e **în afara scopului** acestui ADR — semantică rezervată unei revizuiri separate.

## 4. Decizie D2 — Șase motive de rollback (set închis)

Rollback e parametrizat de un **motiv**, dintr-un set închis, constrâns la nivel de contract (tipar deja folosit de `VALID_REJECTION_REASONS` în Challenger FSM). Fiecare motiv are o sursă de declanșare și o cale de guvernanță distincte:

| Motiv | Sursă de declanșare | Cale de guvernanță |
|---|---|---|
| `regression` | degradare statistică (deviație de la baseline **sau** trend) | **guvernat** — recomandare T3a, aprobată de om |
| `artifact_missing` | artefactul campionului nu poate fi obținut (absent / necitibil / nedeserializabil) | guvernat T3a sau operator |
| `model_error` | obiect obținut dar nefuncțional (`predict_proba` invalid, sau `algorithm_version` incompatibil) | guvernat T3a sau operator |
| `data_error` | corupție amonte care invalidează intrările | operator |
| `operator` | decizie umană, fără semnal automat | direct, uman |
| `emergency` | override uman cu efect imediat | ocolește fereastra T3a; rămâne complet logat |

**Clarificare load-bearing** pentru cele două motive structurale (`artifact_missing`, `model_error`): servirea e deja protejată — dacă un campion e neutilizabil, `oracle_engine._resolve_champion()` întoarce `None` și cade pe antrenarea locală (`RUNTIME_CONTRACT.md`). Deci un rollback structural **nu salvează servirea** (aceea e deja în siguranță) — el **restabilește un campion declarat sănătos**, ca pornirile viitoare de proces să nu mai cadă repetat pe modelul local, iar pointerul activ să reflecte un model utilizabil. `algorithm_version` incompatibil se subsumează lui `model_error` (consemnat în evidence).

`operator` denumește **motivul** („un operator a decis"), nu modul de execuție — de aceea nu se numește `manual`.

## 5. Decizie D3 — Champion Guardian: responsabilitate și ownership

Componentul care evaluează sănătatea campionului activ se numește **Champion Guardian** (nu „Monitor" — un monitor doar observă; acest component **clasifică, propune și generează recomandări**).

### 5.1 Ownership: Learning Core, nu Monitoring Layer

Champion Guardian aparține **Learning Core**. Argumentare:

1. **Emite recomandări de control, nu doar observă.** În momentul în care un component evaluează sănătatea față de praguri și emite o recomandare de rollback în decision feed, el face parte din **bucla de control** a ciclului de viață al modelului. Observabilitatea *privește*; nu *conduce* acțiuni care schimbă ce model servește.
2. **Depinde de primitive Learning Core**: biblioteca de metrici din `shadow_testing`, baseline-ul din `challenger_evaluations`, sonda de utilizabilitate a artefactului, și scrie pe aceeași cale de guvernanță (`automation_runs`, tier T3a) ca Promotion.
3. **Simetrie cu Challenger Evaluation.** Challenger Evaluation (pre-promovare) e neechivoc Learning Core; Champion Guardian e oglinda lui post-promovare — aceleași metrici, aceeași guvernanță, același decision feed. A le împărți pe două straturi ar fragmenta o singură responsabilitate (gating de calitate a modelului).
4. **North Star #10** (nicio dependință „în sus"; servirea nu depinde de infra de învățare). Ținând Guardian-ul în Learning Core, bucla de control rămâne într-un singur strat.

### 5.2 Granița corectă — observare vs. recomandare

- **Evaluarea sănătății + emiterea recomandării = Learning Core** (planul de control). Produce faptele imuabile de sănătate și propunerile T3a.
- **Vizualizarea sănătății (dashboard read-only) = Monitoring / Observability Layer** (UI viitor), care *consumă* faptele de sănătate fără să dețină evaluarea.

Exact ca `challenger_evaluations` (Learning Core produce faptele) urmând să fie *afișate* de un UI viitor fără ca UI-ul să dețină evaluarea. Respectă „funcții pure separate de I/O" și responsabilitate unică.

### 5.3 Ce NU face Champion Guardian

Nu scrie niciodată `model_champions` (nu execută rollback — doar recomandă). Nu re-rulează modele. Nu consumă slotul de challenger (invariant central — de aceea *nu* e abordarea „guardian challenger" respinsă la design). Nu atinge `oracle_engine.py` / calea de servire.

## 6. Decizie D4 — Modelul de sănătate al campionului

### 6.1 Health States — o scară, cu un singur punct de decizie

Sănătatea e o clasificare unică derivată din semnalele subiacente — un singur punct de decizie, niciodată `if/elif` împrăștiat (tipar deja validat de `_classify_data_quality()`, ADR-035 D4):

| Stare | Semnificație | Acțiune de principiu |
|---|---|---|
| 🟢 **Healthy** | toate semnalele în limite | doar înregistrare |
| 🟡 **Watch** | un singur semnal statistic degradat, ori deviație ușoară, ori flag de instabilitate | doar log — avertizare timpurie, nicio recomandare |
| 🟠 **Degrading** | degradare statistică **susținută** (ferestre degradate consecutive) | propune rollback `regression` (T3a) |
| 🔴 **Critical** | eșec structural, ori colaps statistic sever | recomandare imediată (structural poate justifica `emergency`) |

### 6.2 Health vs. Confidence — două axe separate

Sănătatea (starea modelului) e distinctă de **încrederea în verdict** (cât de puternic e semnalul). Ele se raportează **împreună**, dar nu se contopesc:

- `Health = Degrading, Confidence = Low` (eșantion mic) — semnal fragil, de urmărit.
- `Health = Degrading, Confidence = High` (eșantion mare) — semnal puternic, de acționat.

Confidence e o axă **prevăzută arhitectural**, derivabilă ulterior din: numărul de meciuri, consistența ferestrelor, stabilitatea metricilor. **Nu se implementează în Stage 1** — ADR-ul rezervă axa, iar ieșirea Guardian-ului o transportă (chiar dacă inițial necomputată). Operatorul trebuie să poată distinge un semnal fragil de unul robust.

### 6.3 Cele patru dimensiuni de evaluare

Guardian-ul evaluează, independent:

1. **Baseline deviation** (statistic) — metricile live ale campionului vs. baseline-ul de promovare. Detectează căderi *abrupte*.
2. **Trend degradation** (statistic) — degradare *în timp* pe propria performanță live a campionului, comparând o sub-fereastră recentă cu una anterioară a aceluiași campion. Detectează *drift* gradual chiar când nivelul absolut încă pare acceptabil.
3. **Structural health** — o sondă de utilizabilitate care clasifică *de ce* un campion e neutilizabil (`artifact_missing` vs. `model_error`), fără a modifica `champion_loader` sau `RUNTIME_CONTRACT.md`.
4. **Prediction Stability** (informațional, non-blocant) — o măsură de dispersie a probabilităților servite recent. Un model „nervos" (probabilități care oscilează haotic, nejustificate de rezultate) e semnalat ca `instability_detected`. **Nu produce niciodată rollback**, nu are motiv propriu, nu poate ridica starea peste **Watch**.

### 6.4 Reguli de emitere a recomandării — structural vs. statistic

- **Semnalele structurale** (`artifact_missing`, `model_error`) → **recomandare imediată**. Un artefact rupt nu se repară singur; a mai aștepta nu adaugă informație. → **Critical**.
- **Semnalele statistice** (baseline / trend) → **necesită ferestre degradate consecutive** înainte de orice recomandare. Prima fereastră degradată → **Watch** (doar log). Susținerea peste ferestre consecutive → **Degrading** (T3a). Reduce drastic zgomotul dintr-un singur spike.

O „fereastră nouă" reflectă dovezi noi (meciuri noi acumulate), nu re-evaluarea acelorași meciuri — exact semantica de imuabilitate „fereastră nouă = mai multe meciuri" din `challenger_evaluations`. Numărul exact de ferestre consecutive, dimensiunea ferestrei și pragurile = **parametri de implementare**, nu decizii de arhitectură.

## 7. Decizie D5 — `champion_health_evaluations` (contract de date)

„Ferestre consecutive" și „urmărirea sănătății în timp" cer istoric persistat — nederivabil din memorie tranzitorie. Se introduce o tabelă **nouă, aditivă, append-only, imuabilă**, urmând exact precedentul `challenger_evaluations` (RLS activ, scriere doar prin `service_role`, imuabilitate impusă la nivel de bază de date). Reutilizarea lui `automation_runs` a fost considerată și respinsă: acela e registru de guvernanță, nu magazin de serii temporale.

**Ce trebuie să înregistreze contractul** (nu DDL — forma exactă e implementare):
- **identitate**: `training_run_id` al campionului, `algorithm_family`, `league_scope`;
- **fereastră**: marcaj de sfârșit de fereastră + numărul de meciuri evaluate (cheia de imuabilitate: un rând per campion + fereastră, niciodată rescris);
- **metrici** de sănătate (metricile de scoring reutilizate + indicatorul de stabilitate);
- **`health_state`** (starea derivată);
- **`baseline_source`** — provenind din setul: `promotion_evaluation` (baseline live din `challenger_evaluations`), `trend_only` (fără baseline — primul campion, doar trend), `manual_override`. Valoare load-bearing pentru audit: peste ani, o analiză de rollback știe imediat pe ce bază a fost calculată sănătatea;
- **rezultatele per-semnal** (care dimensiune a declanșat) + timestamp UTC.

Aditivă — zero `ALTER` pe tabele existente, zero atingere a contractelor Frozen. E singura adăugire de schemă a acestui ADR peste mecanismul de rollback, și decurge direct din regula ferestrelor consecutive (§6.4), nu din scope nou.

## 8. Politica de promovare — neschimbată

P4 rămâne integral: `candidate_for_promotion` doar dacă Brier ∧ Log-loss ∧ Accuracy sunt *toate* semnificativ mai bune, peste pragul de eșantion. Nimic din acest ADR nu atinge promovarea.

## 9. Politica de rollback

- **Baseline** = rândul de verdict de promovare din `challenger_evaluations` (măsurat *live*, deci comparabil like-for-like cu performanța live ulterioară). **Regula „fără baseline → doar trend"**: un campion fără verdict de promovare (ex. primul campion, bootstrapat) nu primește un baseline inventat — se folosește exclusiv monitorizarea de trend (`baseline_source = trend_only`). Respectă „Never approximate".
- **Atribuire temporală (acceptată pentru Stage 1)**: predicțiile servite se atribuie campionului prin fereastra `kickoff_date` raportată la `promoted_at`, fiindcă `match_history.prob_*_pred` nu poartă azi identitatea modelului servitor. Atribuirea precisă (marcarea unui `training_run_id` pe predicție) e o îmbunătățire viitoare, potențial ADR separat — **nu** se introduce acum.
- **`regression`** cere semnal statistic *susținut* (ferestre consecutive); **structural** → imediat; **`operator`/`emergency`** → autoritate umană directă.
- **Cel mult un rollback per fereastră de promovare** (cooldown) — previne oscilația.
- **Fără rollback automat** (fără om în buclă) — același teritoriu de risc ca promovarea automată, rezervat unui ADR dedicat.

## 10. Ciclul de viață al modelului

```
… → PROMOTED (campion activ) → [Champion Guardian observă] → rollback → predecesor reactivat
                                                                (rând nou în model_champions,
                                                                 promoted_by = rollback:<motiv>:<by>)
```

Istoricul nu se pierde niciodată (append-only + trigger de imuabilitate). Campionul degradat păstrează intact `training_run`-ul și artefactul — complet reproductibil (Regula #9: orice rezultat trasabil complet).

## 11. Strategia de evaluare — doi evaluatori distincți, deliberat nefuzionați

| | Challenger Evaluation | Champion Guardian |
|---|---|---|
| Întrebarea | „e candidatul mai bun ca campionul?" | „mai e campionul de încredere?" |
| Momentul | pre-promovare | post-promovare |
| Datele | predicții shadow (paired) | predicții servite + rezultate |
| Slot challenger | ocupă slotul | **nu** ocupă slotul |
| Rezultat | verdict de promovare | stare de sănătate + recomandare |

Aceeași bibliotecă de metrici, întrebări diferite, date diferite, zero contenție pe slotul de challenger.

## 12. Strategia de eșec

- Fără predecesor → refuz explicit (`no_predecessor`).
- Fereastră insuficientă → nicio recomandare (Regula #8, niciodată aproximare).
- Artefact mort → `RUNTIME_CONTRACT.md` cade deja pe modelul local; rollback-ul `model_error`/`artifact_missing` dezactivează campionul mort.
- Fără baseline → doar trend (`trend_only`).
- Rollback concurent → protecție la nivel de RPC (idempotent) — al doilea apel nu produce a doua scriere.
- Guardian în eroare → best-effort, nicio recomandare, niciodată excepție propagată.
- Indisponibilitate bază de date → best-effort peste tot.

## 13. Compatibilitate înapoi / zero regresie

- **Oracle Engine**: zero schimbare — citește rândul activ exact ca azi; un rând reactivat prin rollback e indistinct ca formă de unul promovat.
- **Promotion Engine**: zero schimbare — serviciu și mecanism separate.
- **Contracte Frozen / trigger / tabele existente**: zero schimbare — doar adăugiri aditive (mecanismul de rollback + tabela de sănătate).
- **Flag-uri**: Guardian-ul și rollback-ul guvernat rulează sub `learning_core_enabled` (implicit `False`); nimic nou nu pornește implicit activ (P1).
- **Pipeline-ul de challenger**: neatins — slotul nu e niciodată consumat.

## 14. Scope / non-goals

Explicit **în afara** acestui ADR: rollback automat (fără om); marcarea `training_run_id` pe predicții (îmbunătățire viitoare, potențial ADR separat); rollback în lanț; corecția comparațiilor multiple (R5); praguri numerice exacte, algoritmi, SQL, semnături (document de implementare + PR-uri R1–R4).

## 15. Etape de implementare (rezumat — detaliul, în documentul de implementare)

- **R1** — Rollback Engine (mecanism atomic + serviciu single-owner + citire predecesor + set de motive), declanșare manuală.
- **R2** — Champion Guardian (evaluare read-only, cele patru dimensiuni, health states, `champion_health_evaluations`).
- **R3** — cablare Guardian → propunere T3a + execuție a rollback-urilor aprobate în bucla de Continuous Learning; motivele `regression` (guvernat), `operator`/`emergency` (direct).
- **R4** (separat) — activarea `learning_core_enabled` în producție, după R1–R3 verificate live pe o ligă.

Fiecare etapă: independent revizuibilă, cu teste fail-before/pass-after, gărzi AST de unicitate a scriitorului/apelantului, plan de revenire, și verificare live — exact disciplina ADR-035.

## 16. Extensii viitoare

Computarea axei Confidence; atribuire precisă per-model a predicțiilor; rollback automat (sub ADR-ul dedicat de risc R1); semantică de rollback în lanț; corecția comparațiilor multiple; un dashboard read-only în Monitoring Layer care consumă `champion_health_evaluations`.

---

## Consecințe

**Pozitive**: ciclul de viață al campionului devine închis și reversibil; drift-ul și eșecurile structurale capătă un răspuns clasificat, guvernat; imuabilitatea strictă e păstrată (append-only); zero atingere a Prediction Engine, API, contractelor Frozen; distincția conceptuală Promotion vs. Rollback previne cuplarea accidentală a celor două lanțuri de decizie.

**Costuri (acceptate conștient)**: un mecanism nou de rollback + un serviciu + un Guardian + o tabelă nouă aditivă + o fază nouă de orchestrare; riscul de oscilație mitigat prin cooldown; atribuirea temporală (nu per-model) acceptată explicit pentru Stage 1; corecția comparațiilor multiple rămâne amânată.

**Deschis, prin proiectare**: axa Confidence și atribuirea precisă sunt prevăzute, nu implementate — rezervate fără a bloca R1–R3.
