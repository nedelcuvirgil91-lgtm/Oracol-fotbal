# Promotion Contract — evenimentul de domeniu „Promote Challenger"

**Status**: FROZEN (via ADR-019)
**Scope**: Contract normativ pentru Pasul 5 (Promotion), rezultat al Architecture Gate Review

---

## Decizia centrală: Promotion nu e un table writer, e un eveniment de domeniu

Architecture Gate Review (înainte de Pasul 5) a demonstrat o contradicție reală: cerința inițială „Promotion scrie exclusiv `model_champions`" intră în conflict direct cu FSM-ul deja înghețat al Challenger-ului (`challenger_manager.py`) — `PROMOTED` e starea terminală a Challenger-ului, atinsă EXACT prin acest eveniment, iar fără ea, slotul „un singur Challenger activ" per `(algorithm_family, league_scope)` nu s-ar elibera niciodată.

Rezoluția: **„Promote Challenger" e UN eveniment de domeniu, cu DOUĂ efecte cuplate, aplicate atomic**:

1. Un rând nou, activ, în `model_champions` (Champion nou).
2. Tranziția Challenger-ului sursă: `SUCCEEDED → PROMOTED` (`challengers.state`, `terminal_at`).

Aceste două efecte nu sunt „responsabilități separate care se ating accidental" — sunt fațete ale ACELUIAȘI fapt istoric. Un Promotion Service care ar scrie doar unul dintre ele ar produce o stare inconsistentă (Champion nou fără Challenger închis, sau invers) — niciodată acceptabil.

**Nu se construiește un Learning Orchestrator general pentru asta** (decizie explicită Chief Architect, YAGNI) — Promotion Service e proprietarul acestui UNIC eveniment, cu ambele efecte incluse în propriul lui scop, nu al unei componente de coordonare mai largi.

## Agregatele modificate

| Agregat | Efect | Cine scrie |
|---|---|---|
| `challengers` | `SUCCEEDED → PROMOTED`, `terminal_at = now()` | Promotion Service (prin `promote_challenger` RPC — vezi `ATOMICITY_CONTRACT.md`) |
| `model_champions` | Campionul activ curent (dacă există) → `superseded_at = now()`, `superseded_by = training_run_id` nou; INSERT rând nou, activ | Promotion Service (același RPC) |

Nicio altă tabelă/agregat nu e atins — `challenger_evaluations` (verdictul, deja imuabil, doar CITIT ca precondiție), `shadow_predictions`, artefactul din Storage (doar CITIT, pentru validare) rămân neschimbate.

## Invariant — Promotion execută, nu decide

Adăugat explicit la aprobarea Pasului 4.5 (Chief Architect), înainte de înghețarea completă.

```
Comparison → Shadow Evaluation → verdict candidate_for_promotion → Promotion Service
```

Lanțul de decizie (comparare metrici, semnificație statistică, praguri, eligibilitate) e complet ÎNCHEIAT înainte ca Promotion Service să fie invocat — verdictul `candidate_for_promotion` din `challenger_evaluations` (Pasul 4, imuabil) e rezultatul final al acelui lanț, nu o sugestie. **Promotion Service nu recalculează nimic din asta** — nu re-rulează teste statistice, nu re-evaluează praguri, nu re-decide dacă modelul e „suficient de bun". Cele trei precondiții de mai jos sunt verificări **structurale** (există / nu există, valid / invalid), niciodată o a doua opinie asupra calității modelului.

Dacă Promotion Service ar începe vreodată să evalueze din nou eligibilitatea (nu doar s-o citească), logica de decizie ar deveni duplicată — cu risc real ca cele două căi de decizie (Shadow Evaluation vs. re-verificarea din Promotion) să diveargă în timp. Orice extindere viitoare a precondițiilor Promotion Service trebuie să rămână strict structurală (ex. „rândul există și are forma așteptată"), niciodată statistică/de prag.

## Precondiții (verificate ÎNAINTE de orice scriere — fail fast, zero scriere parțială)

Promotion Service refuză să acționeze dacă **oricare** din următoarele e falsă. Toate trei sunt verificări STRUCTURALE, nu decizionale (vezi invariantul de mai sus):

1. **Challenger există** pentru `training_run_id` dat, și `challengers.state == 'SUCCEEDED'` — o citire de stare, nu o re-evaluare a motivului pentru care e `SUCCEEDED`.
2. **Verdict pozitiv, imuabil, deja înregistrat** — cel mai recent rând din `challenger_evaluations` pentru acest `training_run_id` are `verdict = 'candidate_for_promotion'`. Această verificare e independentă de (1) — nu se are încredere doar în `challengers.state` (apărare în adâncime, consistent cu „verificat, nu presupus"). Închide, totodată, legătura dintre Pasul 4 (verdict) și Pasul 5 (acțiune) — un verdict `candidate_for_promotion` calculat de Shadow Evaluation e literalmente precondiția obligatorie a promovării, nu doar informație pasivă. **Promotion Service citește acest câmp — nu recalculează `delta_brier`/`delta_logloss`/`delta_accuracy` sau semnificația lor statistică.**
3. **Artefactul e re-validat la momentul promovării** — `model_artifact_storage.load_model_artifact(training_run_id)` reușește ȘI produce un obiect funcțional (`predict_proba` apelabil pe un rând de test), nu doar „fișierul există". Validarea se întâmplă **înainte** de orice scriere în bază de date (vezi `ATOMICITY_CONTRACT.md`). Aceasta e o verificare de integritate tehnică (bytes deserializabili), nu de calitate a modelului.

Dacă oricare eșuează, Promotion Service întoarce un rezultat explicit de eșec, cu motivul — **zero scriere** are loc.

## Idempotență

Dacă `training_run_id` cerut e **deja** campionul activ pentru `(algorithm_family, league_scope)` (rulare dublă a aceleiași promovări), operația e un no-op: întoarce succes, fără o a doua scriere, fără al doilea rând `model_champions`, fără o a doua tranziție de stare (Challenger e deja `PROMOTED`, tranziția `PROMOTED → PROMOTED` nu există în `ALLOWED_TRANSITIONS` — detectată explicit ÎNAINTE de a încerca tranziția, nu lăsată să eșueze ca eroare).

## Cine invocă Promotion

**Exclusiv manual** — un om, explicit, printr-un apel direct (CLI/UI viitor) cu `promoted_by` obligatoriu (identitatea celui care a decis). Niciun proces automat nu invocă Promotion azi — `auto_promotion_enabled` rămâne `False`/neimplementat, exact cum CLAUDE.md și ADR-002 impun deja („promovare automată necesită ADR dedicat, niciodată implicit pornită").

## Ce NU face Promotion Service

- Nu calculează verdictul (deja calculat, imuabil, Pasul 4) — doar îl CITEȘTE ca precondiție.
- Nu antrenează, nu re-evaluează, nu re-rulează Shadow Evaluation.
- Nu atinge Runtime, `oracle_engine.py`, sau fluxul de predicție — Runtime nu citește `model_champions` încă (vezi `RUNTIME_CONTRACT.md`); Promotion rămâne complet invizibil pentru el.
- Nu implementează Rollback — mecanism simetric, dar SEPARAT, viitor, cu propriul contract (nemenționat aici, explicit în afara scopului Pasului 5).
- Nu scrie/citește `shadow_predictions` sau artefacte noi (doar re-validare read-only a celui existent).

## Imuabilitatea `model_champions` — decizie explicită, nu implicită

Până la primul writer (Pasul 5), `model_champions` era un jurnal fără scriitor — întrebarea „append-only sau mutable" nu avea încă un răspuns necesar. Din momentul în care apare Promotion Service, răspunsul devine obligatoriu:

**Decizie: hibrid, nu pur append-only.** Un rând `model_champions` permite EXACT o singură mutație în viața lui — tranziția de la activ (`superseded_at IS NULL`) la istoric (`superseded_at`/`superseded_by` completate), executată o singură dată, ca parte a promovării campionului URMĂTOR. După acel moment, rândul devine **permanent imuabil** — niciun UPDATE, niciun DELETE, niciodată, indiferent de rol (inclusiv `service_role`).

Impunere: un trigger de imuabilitate la nivel de bază de date, simetric cu `odds_history_immutability_guard` (ADR-005/006, singurul precedent real din proiect) — blochează orice UPDATE/DELETE pe un rând unde `superseded_at IS NOT NULL`, și blochează orice UPDATE pe un rând activ care ar atinge altă coloană decât `superseded_at`/`superseded_by` (exact mutația permisă). Trigger-ul e parte a migrării Pasului 5 (nescris încă — Pasul 4.5 doar decide, nu implementează).

Această decizie închide golul semnalat explicit chiar în comentariul din `database/migrations/002_learning_core.sql` (liniile 90-104): „revizuit ca decizie separată, explicită, când Promotion Engine ... chiar scrie în aceste tabele" — acest document e acea decizie.
