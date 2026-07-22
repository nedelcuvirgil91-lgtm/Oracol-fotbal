# R1_IMPLEMENTATION_CHECKLIST.md — Rollback Engine (Stage R1)

**Tip**: checklist de execuție. NU e ADR, NU e document de arhitectură. Autoritatea de design rămâne `ADR-037` + `CHAMPION_GUARDIAN_IMPLEMENTATION.md` (neatinse de acest document).

**Scop R1**: mecanismul atomic de rollback (append-only, re-promovare a predecesorului) + serviciul single-owner + integrarea de acces la date, cu declanșare exclusiv manuală. Fără Champion Guardian (R2), fără orchestrare (R3), fără activare (R4).

**Reguli**: Verificat, nu presupus · fără redesign · fără cod · fără SQL · ADR-037 și doc-ul Guardian neatinse. Acest checklist descrie CE se construiește și cum se verifică, nu conținutul cod/SQL.

**Ancore verificate în repo** (nu presupuse): `rpc_promote_challenger` (`supabase_client.py`) — pattern `client.rpc("promote_challenger", {p_...}).execute()`, excepția lăsată să urce; `promote_challenger` RPC (`005_promotion.sql`) — precedentul atomic; triggerul `model_champions_guard` (005) — permite exact mutația activ→istoric + INSERT; teste AST de ownership (`test_promotion_service.py::test_module_has_only_known_importers`, `test_challenger_manager.py::test_module_has_single_known_importer`); zero cod „rollback" existent; ultima migrare = `013` → următoarea `014`.

---

## Ajustare față de împărțirea sugerată (cu explicație)

Sugestia inițială avea `R1.1 Migration 014` și `R1.2 rollback_champion RPC` ca task-uri separate. **Ajustare**: RPC-ul *este* conținutul migrării 014 — o singură funcție Postgres, care nu poate fi împărțită în două task-uri fără a lăsa o funcție pe jumătate definită (stare inconsistentă, contrazice criteriul „oprire după orice task fără inconsistență"). Am re-împărțit pe granița reală și mai valoroasă:
- **R1.1 = autorarea migrării 014** (funcția completă, în repo, neaplicată);
- **R1.2 = aplicarea migrării 014 pe Supabase** (acțiune de scriere live, guvernată obligatoriu de skill-ul `supabase-safety` — SQL-ul exact arătat înainte).

A doua ajustare: `supabase_client integration` trebuie să preceadă `rollback_service.py` (serviciul importă funcțiile de acces). Am ordonat data-access înainte de serviciu, pentru dependențe strict aciclice. Granularitatea totală rămâne 9 pași (R1.1–R1.9), ca în sugestie.

---

## Modificări aplicate din Auditul de arhitectură (pre-R1)

Trei modificări minore aprobate, aplicate ÎNAINTE de orice cod. Niciun redesign, niciun ADR-037 atins, niciun fișier interzis (Oracle Engine, Promotion Service, Champion Loader, RUNTIME_CONTRACT, triggerul `model_champions`, migrarea 005) modificat.

1. **Compare-and-Swap Guard (obligatoriu)** — RPC-ul `rollback_champion` primește `expected_predecessor_training_run_id`, derivă predecesorul server-side sub lock, îl compară, și refuză (`predecessor_mismatch`, zero scriere) la neconcordanță. Elimină complet TOCTOU-ul validare-Python → execuție-RPC. Impus exact ca `update_challenger_state(expected_current_state=...)`. Reflectat în R1.1, R1.3, R1.4, R1.6, R1.8.
2. **Ownership explicit** — `model_champions` e agregarea Champion Lifecycle, cu **doi scriitori autorizați** (Promotion Service + Rollback Service), coordonați NU prin owner unic, ci prin: tranzacție atomică + index parțial unic + trigger de imuabilitate (Frozen, neatins) + row locking. Consemnat în `CHAMPION_GUARDIAN_IMPLEMENTATION.md` §13 și impus de gărzile AST din R1.7. Fără schimbare de design/trigger/migrarea 005.
3. **Invariant pentru R3** — un `training_run` deja retras prin rollback NU trebuie niciodată re-promovat (rândul lui din `challengers` rămâne `PROMOTED`; `promote_challenger` are deja garda). Documentat în `CHAMPION_GUARDIAN_IMPLEMENTATION.md` §14 (R3); nu se atinge FSM-ul sau `promote_challenger`. În afara scope-ului execuției R1 (R1 e manual), consemnat pentru R3.

---

## Task-uri

### R1.1 — Autorează migrarea 014 (`rollback_champion` RPC)
- **Descriere**: fișier de migrare nou care definește funcția Postgres `rollback_champion(algorithm_family, league_scope, expected_predecessor_training_run_id, reason, by)` — o singură tranzacție: lock pe campionul activ; **idempotență (stare-țintă)** — dacă campionul activ e deja `expected_predecessor_training_run_id`, întoarce `already_active` fără scriere; derivarea server-side, sub lock, a predecesorului (rândul cu `superseded_by` = training_run-ul campionului activ); **gardă compare-and-swap** — dacă predecesorul derivat ≠ `expected_predecessor_training_run_id` (schimbare concurentă) → refuz (`predecessor_mismatch`), zero scriere, exact ca pattern-ul `update_challenger_state(expected_current_state=...)`; supersedarea campionului activ (mutația unică permisă de triggerul 005); INSERT rând nou activ pentru `expected_predecessor_training_run_id` cu `promoted_by = rollback:<motiv>:<by>`; refuz explicit dacă nu există predecesor (`no_predecessor`). NU atinge `challengers`. Idempotent la re-rulare (`CREATE OR REPLACE FUNCTION`). NU adaugă/modifică vreun trigger.
- **[Audit — modificarea 1, CAS guard]** `expected_predecessor_training_run_id` e obligatoriu, elimină TOCTOU-ul dintre validarea artefactului în Python (R1.4) și execuția RPC — artefactul validat e EXACT cel activat, sau operația e respinsă.
- **Fișiere**: `database/migrations/014_rollback.sql` (nou).
- **Dependențe**: niciuna.
- **DONE**: fișierul există, revizuit; funcția respectă diviziunea din `ATOMICITY_CONTRACT` (writes atomice server-side), append-only, zero atingere a triggerului.
- **Fail-before**: nu există `database/migrations/014_*`; grep „rollback_champion" → 0 rezultate.
- **Pass-after**: fișierul prezent; conține definiția completă a funcției (un singur artefact coerent); review confirmă simetria cu `promote_challenger` și lipsa oricărei scrieri pe `challengers`/tabele Frozen.
- **Rollback plan**: se șterge fișierul. Nicio urmă (neaplicat pe DB încă).

### R1.2 — Aplică migrarea 014 pe Supabase (proiect `Prediction`)
- **Descriere**: aplicarea funcției `rollback_champion` pe baza live. **Gate obligatoriu**: skill-ul `supabase-safety` — SQL-ul exact al migrării 014 e arătat utilizatorului ÎNAINTE de aplicare; nicio aplicare fără confirmare vizibilă.
- **Fișiere**: niciun fișier de repo modificat (acțiune pe DB). Referință: `014_rollback.sql`.
- **Dependențe**: R1.1.
- **DONE**: funcția `rollback_champion` există în DB; re-aplicarea (idempotent) nu produce eroare.
- **Fail-before**: apelul RPC `rollback_champion` întoarce eroare „function does not exist".
- **Pass-after**: un apel-sondă al RPC pe o combinație inexistentă întoarce comportamentul de refuz definit (nu eroare de funcție inexistentă), confirmând că funcția e prezentă și rulează.
- **Rollback plan**: `DROP FUNCTION rollback_champion` (arătat prin `supabase-safety` înainte de execuție). Aditiv — nicio tabelă/date atinse.

### R1.3 — Integrare `supabase_client` (acces la date)
- **Descriere**: două funcții noi de acces: (a) citirea predecesorului campionului activ pentru `(algorithm_family, league_scope)` — precondiție Python înainte de RPC, a cărei valoare devine `expected_predecessor_training_run_id`; (b) un wrapper `rpc_rollback_champion(algorithm_family, league_scope, expected_predecessor_training_run_id, reason, by)` care apelează RPC-ul, oglindind exact `rpc_promote_challenger` (același pattern `client.rpc(...).execute()`, aceeași convenție de a lăsa excepția server-side să urce, prinsă mai sus în serviciu). **[Audit — modificarea 1]** wrapper-ul transmite obligatoriu `expected_predecessor_training_run_id` (gardă CAS).
- **Fișiere**: `supabase_client.py` (adăugiri; niciun cod existent modificat).
- **Dependențe**: R1.1 (contractul RPC). Verificarea funcțională completă necesită R1.2.
- **DONE**: ambele funcții prezente, cu docstring-uri consecvente cu vecinele; wrapper-ul identic ca formă cu `rpc_promote_challenger`.
- **Fail-before**: grep pentru numele noilor funcții → 0; testele R1.5 care le importă eșuează la colectare (ImportError).
- **Pass-after**: funcțiile importabile; wrapper-ul construiește apelul RPC corect (verificat prin test cu client fabricat, R1.6).
- **Rollback plan**: se revine diff-ul din `supabase_client.py` (adăugiri izolate, ușor de eliminat).

### R1.4 — `learning_core/rollback_service.py` (serviciu single-owner)
- **Descriere**: serviciul care deține evenimentul „Rollback Challenger". Un singur punct de intrare public. Precondiții structurale ÎNAINTE de orice scriere (campion activ există; predecesor există; artefactul predecesorului se re-validează funcțional; motivul ∈ setul închis de șase), fail-fast, zero apel RPC la primul eșec. **[Audit — modificarea 1]** predecesorul validat aici e transmis ca `expected_predecessor_training_run_id` la RPC (CAS) — garanția că artefactul validat = artefactul activat. Un singur apel `rpc_rollback_champion`. Niciodată excepție necontrolată către apelant — rezultat structurat `RollbackResult(status ∈ {rolled_back, already_active, rejected}, reason)`; mapează inclusiv `predecessor_mismatch` la `rejected` (operatorul reia cu starea actuală). Oglindește `promotion_service.py`.
- **Fișiere**: `learning_core/rollback_service.py` (nou).
- **Dependențe**: R1.3.
- **DONE**: serviciu complet, izolat (zero apelanți reali în producție — ca `promotion_service.py` la creare); mapează excepția RPC la `rejected`.
- **Fail-before**: fișierul nu există; testele R1.5 eșuează la import.
- **Pass-after**: testele R1.5 trec; modulul e importabil și execută lanțul precondiții→RPC pe căi mockuite.
- **Rollback plan**: se șterge fișierul. Fiind izolat (fără apelanți), ștergerea nu afectează nimic (verificabil prin grep, ca la celelalte module Learning Core).

### R1.5 — Teste `rollback_service` (fără rețea)
- **Descriere**: teste unitare cu RPC/Supabase mockuit: fiecare precondiție eșuată → `rejected`, zero scriere; `no_predecessor` → refuz; artefact invalid → `rejected`; răspuns RPC `already_active` → mapat la succes, nu eroare; motiv în afara setului → refuz. Fără dependență de rețea/DB live (regula testelor).
- **Fișiere**: `tests/test_rollback_service.py` (nou).
- **Dependențe**: R1.4.
- **DONE**: toate cazurile verzi; `pytest tests/test_rollback_service.py` fără rețea.
- **Fail-before**: fișierul absent → 0 teste; sau, scris înaintea R1.4, eșuează la import (fail-before valid, ca la ADR-035 D4).
- **Pass-after**: suita nouă verde; `pytest tests/` global rămâne verde.
- **Rollback plan**: se șterge fișierul de test.

### R1.6 — Teste RPC / atomicitate
- **Descriere**: verificarea comportamentului `rollback_champion`: supersede+insert atomic (ambele sau niciunul); idempotență stare-țintă (`already_active` când campionul activ e deja `expected_predecessor`); **gardă CAS — `predecessor_mismatch` când predecesorul derivat ≠ `expected_predecessor_training_run_id`, zero scriere**; refuz fără predecesor (`no_predecessor`); respectarea triggerului de imuabilitate (niciun rând istoric mutat). Preferabil la nivel de logică cu DB fabricat/mock; verificarea reală de atomicitate/concurență se confirmă la R1.8 pe DB live.
- **Fișiere**: `tests/test_supabase_client_rollback.py` (nou) și/sau extindere test dedicată RPC.
- **Dependențe**: R1.3 (wrapper); R1.2 pentru orice verificare pe DB live.
- **DONE**: cazurile de contract ale RPC verzi (fără rețea unde e posibil).
- **Fail-before**: testele absente / eșuează la import.
- **Pass-after**: verzi; `pytest tests/` global verde.
- **Rollback plan**: se șterge fișierul de test.

### R1.7 — Teste AST de ownership
- **Descriere**: gărzi statice, oglindind `test_promotion_service.py` / `test_challenger_manager.py`: (a) `rpc_rollback_champion` are un singur apelant real = `rollback_service.py`; (b) `rollback_service.py` are doar importatori cunoscuți; (c) niciun cod de producție nu scrie `model_champions` pe cale de rollback în afara RPC-ului. Impune invariantul „single owner al evenimentului Rollback".
- **Fișiere**: `tests/test_rollback_ownership.py` (nou) sau secțiune AST în R1.5.
- **Dependențe**: R1.3, R1.4.
- **DONE**: gărzile AST trec; orice al doilea apelant viitor ar fi detectat imediat.
- **Fail-before**: fără gardă → un apelant neautorizat ar trece neobservat (test absent).
- **Pass-after**: gărzile verzi pe arborele curent.
- **Rollback plan**: se șterge fișierul/secțiunea de test.

### R1.8 — Verificare de integrare (end-to-end, manual/fixture)
- **Descriere**: pe date reale/fixture controlate: predecesor găsit → swap atomic (activul devine istoric, predecesorul devine activ, un singur activ per `(family, league)` — invariantul indexului parțial); fără predecesor → refuz curat (`no_predecessor`); dublu rollback (ținta deja atinsă) → `already_active`, nicio a doua scriere; **[Audit — modificarea 1] CAS**: dacă campionul activ s-a schimbat concurent, predecesorul derivat ≠ `expected_predecessor` → `predecessor_mismatch`, zero scriere; confirmarea conceptuală că `champion_loader` ar citi noul rând activ la următoarea construcție de proces (fără a modifica `oracle_engine`). Read-only asupra oricărei stări pe care nu o mutăm deliberat.
- **Fișiere**: niciun fișier de producție nou; opțional un script de verificare de tip `sync/poc_*` (neintegrat), consecvent cu precedentele `poc_*`.
- **Dependențe**: R1.2, R1.4 (tot lanțul cablat).
- **DONE**: toate scenariile de mai sus confirmate pe rulare reală; raport scris.
- **Fail-before**: fără verificare, comportamentul real (atomicitate/concurență/idempotență pe DB live) e nedemonstrat.
- **Pass-after**: raport care arată swap corect + refuz + idempotență, pe DB live.
- **Rollback plan**: verificare read-mostly; orice rând `model_champions` creat în test se tratează prin procedura administrativă documentată (dezactivare temporară trigger), nu prin cod nou. (Se preferă un `(family, league)` de test, nu unul de producție.)

### R1.9 — Actualizare documentație (condițional)
- **Descriere**: dacă R1 schimbă starea raportată a proiectului: notă în `CHANGELOG.md` (Rollback Engine — mecanism, manual, izolat) și corectarea secțiunii stale din `CLAUDE.md` („Current Implementation Status") care încă listează greșit componente Learning Core drept neimplementate. NU se ating ADR-037, doc-ul Guardian, sau documente Frozen.
- **Fișiere**: `CHANGELOG.md`, `CLAUDE.md` (dacă e necesar).
- **Dependențe**: R1.8.
- **DONE**: changelog reflectă R1; statusul din CLAUDE.md nu mai contrazice repo-ul.
- **Fail-before**: `CLAUDE.md` afirmă stare neconformă cu codul livrat.
- **Pass-after**: documentația consecventă cu starea reală.
- **Rollback plan**: se revine diff-ul de documentație.

---

## Graful de dependențe (aciclic)

```
R1.1 ─▶ R1.2 ─────────────▶ R1.8 ─▶ R1.9
  └────▶ R1.3 ─▶ R1.4 ─┬─▶ R1.5
                        ├─▶ R1.7
                        └─▶ R1.8
         R1.2/R1.3 ────▶ R1.6
```
Toate muchiile merg „înainte"; niciun ciclu.

---

## Self-review

- **Fără dependențe circulare**: graful de mai sus e strict aciclic — R1.1 e rădăcina; fiecare task depinde doar de task-uri cu index mai mic sau de R1.2 (aplicarea), niciodată invers. ✔
- **Fiecare task e implementabil și verificabil independent**: fiecare are un artefact propriu (fișier de migrare / funcții de acces / serviciu / fișier de test / raport) și un criteriu de verificare izolat (review, sondă RPC, pytest fără rețea, verificare live). ✔
- **Criterii de acceptare clare**: fiecare task are DONE + Fail-before + Pass-after explicite și măsurabile (existență fișier, comportament RPC, suită verde, raport). ✔
- **Oprire după orice task fără inconsistență**: după R1.1 migrarea e un fișier inert (neaplicat, ca orice migrare pe disc); după R1.2 RPC-ul există dar nimeni nu-l apelează (aditiv, inofensiv); după R1.3 funcțiile de acces sunt neapelate; după R1.4 serviciul e izolat, zero apelanți (exact starea în care au fost livrate `promotion_service.py`, `challenger_manager.py` etc.); testele (R1.5–R1.7) sunt pur aditive; R1.8 e verificare; R1.9 e documentație. În niciun punct nu rămâne un artefact pe jumătate scris — motivul pentru care RPC-ul (o funcție indivizibilă) e un singur task (R1.1), nu două. ✔
- **Consecvență cu ADR-037 / doc-ul Guardian**: R1 acoperă exact „R1 — Rollback Engine (declanșare manuală)" din `CHAMPION_GUARDIAN_IMPLEMENTATION.md` §14; zero introducere de Guardian/orchestrare/activare (acelea sunt R2–R4); append-only și zero atingere a contractelor Frozen păstrate. ✔
- **Verificat, nu presupus**: toate ancorele (RPC pattern, teste AST, trigger 005, plafon migrare 013) au fost citite direct din repo înainte de redactare. ✔
