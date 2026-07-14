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

## Rationale

Un gate arhitectural găsește o contradicție reală — răspunsul corect nu e nici „ignoră și continuă", nici „respinge tot conceptul", ci „rezolvă exact contradicția găsită, cu cea mai mică extensie de scop posibilă" (Promotion Service, nu Orchestrator; RPC justificat de un invariant concret, nu de o preferință de stil).

## Consequences

- **Pasul 5 devine, per verdictul Chief Architect, „aproape mecanic"** — cele patru decizii structurale sunt deja luate; implementarea propriu-zisă (migrare cu trigger de imuabilitate + funcție `promote_challenger` + `learning_core/promotion_service.py` + teste) urmează exact contractele din acest ADR, fără decizii noi de arhitectură.
- `FROZEN_REGISTRY.md` actualizat cu cele patru documente noi.
- Niciun cod nou, nicio migrare, zero impact asupra producției — acest ADR e pur decizional.
- Rollback (mecanism simetric cu Promotion) rămâne explicit în afara scopului — un contract separat, viitor, nu implicit inclus aici.
