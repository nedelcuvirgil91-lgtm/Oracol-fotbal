# ADR-019 — Promotion Architecture (Pasul 4.5, pre-implementare)

**Status**: Decis — documentele normative devin Frozen prin acest ADR
**Affects**: `docs/04_LEARNING_CORE/RUNTIME_CONTRACT.md`, `PROMOTION_CONTRACT.md`, `ATOMICITY_CONTRACT.md`, `PROMOTION_SERVICE_CONTRACT.md`
**Authority**: Principal Software Architect, aprobat explicit de proprietarul produsului

---

## Context

Înainte de Pasul 5 (First Promotion — prima scriere reală în `model_champions`), un Architecture Gate Review adversarial a fost cerut explicit, cu obiectivul declarat „demonstrează activ că Pasul 5 e prematur, nu confirma". Reviewul a găsit două contradicții reale:

1. **Cerința inițială „Promotion scrie exclusiv `model_champions`" intră în conflict cu FSM-ul Challenger** (`challenger_manager.py`, ADR-016) — `PROMOTED` e starea terminală a Challenger-ului, atinsă exact prin evenimentul de promovare; fără acea tranziție, invariantul „un singur Challenger activ per (algorithm_family, league_scope)" ar rămâne blocat permanent după prima promovare reală.
2. **Mecanismul de atomicitate cerut de „Contract #5"** (stabilit înainte de Pasul 1, niciodată transcris într-un document — el însuși un gol de trasabilitate identificat la acest review) **nu e realizabil** cu tiparele de scriere Supabase folosite peste tot altundeva în proiect (apeluri PostgREST single-table, fără tranzacții multi-statement).

Verdictul reviewului a fost „Architecture Gate NOT PASSED AS SUBMITTED" — nu o respingere a conceptului de Promotion, ci o amânare până la rezolvarea explicită a patru decizii arhitecturale.

## Decision

Chief Architect a acceptat ambele obiecții ca valide, a respins concluzia „NOT PASSED" ca fiind prea tare, și a cerut un pas intermediar — **Pasul 4.5, „Promotion Architecture"** — care nu scrie niciun cod și nicio migrare, ci produce exclusiv decizii/documente normative. Acest ADR consemnează acele decizii:

1. **Promotion nu e un table writer — e evenimentul de domeniu „Promote Challenger"**, cu două efecte cuplate, aplicate atomic: `model_champions` (Champion nou) + `challengers` (`SUCCEEDED → PROMOTED`). Vezi `PROMOTION_CONTRACT.md`.

2. **Nu se construiește Learning Orchestrator acum** — decizie explicită YAGNI a Chief Architect. Se construiește exact UN serviciu nou, cu UN use-case: `promotion_service.py`, owner al evenimentului „Promote Challenger", nimic mai mult. Vezi `PROMOTION_SERVICE_CONTRACT.md`.

3. **Atomicitatea reală cere o funcție Postgres (RPC)** — declarată explicit parte a arhitecturii Learning Core, nu „infrastructură în plus": mecanismul minim necesar pentru a respecta un invariant deja acceptat. Promotion Service face precondițiile (citire Challenger, citire verdict, validare artefact) în Python, ÎNAINTE de orice scriere; UN singur apel RPC face cele trei scrieri cuplate într-o singură tranzacție Postgres. Vezi `ATOMICITY_CONTRACT.md`.

4. **Runtime Contract și Promotion Contract devin documente normative**, nu doar proză în ADR-uri — transcrise complet, pentru prima dată, în `docs/04_LEARNING_CORE/`. Închide golul de trasabilitate identificat la review (invariantul de 5 condiții de utilizabilitate Runtime, fallback-ul permanent, Contract #5).

5. **`model_champions` e hibrid, nu pur append-only** — decizie explicită, nu implicită: fiecare rând permite EXACT o mutație (tranziția activ → istoric, la promovarea campionului următor), apoi devine permanent imuabil (niciun UPDATE/DELETE, impus printr-un trigger simetric cu `odds_history_immutability_guard`, ADR-005/006). Vezi `PROMOTION_CONTRACT.md`, secțiunea „Imuabilitatea model_champions".

6. **Promotion execută, nu decide** — adăugat de Chief Architect la aprobarea Pasului 4.5, ca ultimă condiție înainte de înghețarea completă. Lanțul de decizie (Comparison → Shadow Evaluation → verdict `candidate_for_promotion`) e complet încheiat înainte ca Promotion Service să fie invocat. Cele trei precondiții din `PROMOTION_CONTRACT.md` sunt verificări STRUCTURALE (există/valid), niciodată o a doua opinie statistică asupra calității modelului — Promotion Service nu importă `shadow_testing`, nu recalculează deltas/semnificație. Previne duplicarea logicii de decizie între Shadow Evaluation și Promotion, care ar putea diverge în timp. Vezi `PROMOTION_CONTRACT.md` și `PROMOTION_SERVICE_CONTRACT.md`, secțiunile actualizate.

## Addendum — aprobarea Pasului 5 (implementare)

După implementarea mecanică a contractelor de mai sus (migration 005, `learning_core/promotion_service.py`), Chief Architect a aprobat Pasul 5 și a consemnat două invarianți suplimentari, direct legați de ce s-a descoperit/clarificat în implementare:

7. **Promotion Service e singura cale legitimă către starea `PROMOTED`** — ca răspuns direct la riscul semnalat în timpul implementării (`challenger_manager.transition(tid, "PROMOTED")` rămâne valid la nivel de FSM, dar nu e o cale de producție). FSM-ul descrie stările posibile; Promotion Service descrie singura cale legală prin care sistemul ajunge efectiv acolo. Vezi `PROMOTION_CONTRACT.md`, secțiunea nouă.

8. **RPC-ul e mecanismul, nu invariantul** — atomicitatea „Promote Challenger" (ambele efecte împreună, sau niciunul) e proprietatea permanentă de păstrat; funcția Postgres `promote_challenger` e implementarea aleasă azi, înlocuibilă în viitor (printr-un ADR nou) dacă infrastructura permite altceva echivalent, fără ca invariantul însuși să se schimbe. Vezi `ATOMICITY_CONTRACT.md`, secțiunea nouă.

## Addendum — Validare E2E finală (identitate izolată de test, infrastructură reală)

După implementarea Pasului 5-7B, un audit final end-to-end a rulat toate scenariile critice (promovare, superseding, imuabilitate, refuzul unui rollback nepermis, idempotență, incompatibilitate de `algorithm_version`, artefact corupt) contra infrastructurii reale (Supabase `Prediction`), sub o identitate de test complet izolată (`gate_validation_test`), fără să atingă identitatea reală de guvernanță (`xgboost_v1`/`all`). Toate scenariile au confirmat integritatea datelor și atomicitatea — singura observație a fost una de contract/documentație, nu de cod:

9. **Idempotența „Promote Challenger" are două niveluri distincte, ambele corecte, care nu trebuie confundate**:
   - **Apel secvențial** (re-promovare a unui `training_run_id` deja `PROMOTED`, după ce prima promovare s-a încheiat): Promotion Service (Python) respinge la precondiția FSM (`state != 'SUCCEEDED'`) — `PromotionResult(status="rejected", reason=...)`. Corect: din perspectiva FSM-ului Challenger-ului, precondiția operației nu mai e îndeplinită — nu (mai) e aceeași operație.
   - **Apel concurent** (două promovări simultane pentru același `training_run_id`, ambele citind `state == 'SUCCEEDED'` înainte ca vreuna să comită): RPC-ul (`promote_challenger`, migration 005) rezolvă cursa prin `FOR UPDATE` — al doilea apel, deblocat după commit-ul primului, vede `state = 'PROMOTED'` și întoarce `'already_active'` (succes, nu eroare). Aici, la nivelul bazei de date, e locul corect pentru protecția anti-cursă.

   **Decizie explicită**: codul rămâne neschimbat — cele două niveluri de responsabilitate (Promotion Service verifică precondiția de business; RPC-ul garantează integritatea tranzacțională/anti-cursă) sunt deja corect separate. Nu se introduce o excepție în `promotion_service.py` doar pentru a uniformiza mesajul de răspuns al unui apel secvențial cu cel al unui apel concurent — ar câștiga o etichetă identică, fără niciun câștig real de siguranță sau consistență. Se corectează exclusiv textul din `PROMOTION_CONTRACT.md` (secțiunea „Idempotență") și `ATOMICITY_CONTRACT.md`, care descriau anterior idempotența ca un singur caz nediferențiat.

## Rationale

Un gate arhitectural găsește o contradicție reală — răspunsul corect nu e nici „ignoră și continuă", nici „respinge tot conceptul", ci „rezolvă exact contradicția găsită, cu cea mai mică extensie de scop posibilă" (Promotion Service, nu Orchestrator; RPC justificat de un invariant concret, nu de o preferință de stil).

## Consequences

- **Pasul 5 devine, per verdictul Chief Architect, „aproape mecanic"** — cele patru decizii structurale sunt deja luate; implementarea propriu-zisă (migrare cu trigger de imuabilitate + funcție `promote_challenger` + `learning_core/promotion_service.py` + teste) urmează exact contractele din acest ADR, fără decizii noi de arhitectură.
- `FROZEN_REGISTRY.md` actualizat cu cele patru documente noi.
- Niciun cod nou, nicio migrare, zero impact asupra producției — acest ADR e pur decizional.
- Rollback (mecanism simetric cu Promotion) rămâne explicit în afara scopului — un contract separat, viitor, nu implicit inclus aici.
