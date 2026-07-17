# ADR-030 — Continuous Learning ca Funcție Decuplată

**Status**: FROZEN. Al treilea ADR din drumul critic de execuție Football
Oracle vNext, succesor direct al ADR-026 și ADR-028 (ambele frozen). Drum
critic: ADR-026 (Frozen) → ADR-028 (Frozen) → **ADR-030 (Frozen)** →
ADR-031 (Frozen) → ADR-033 (Frozen).

**Implementat**: PR #5, merge-uit în `main`, inactiv implicit prin
`learning_core_enabled=False`; activat controlat în producție ulterior
(SQL exact confirmat), verificat end-to-end (`automation_runs` T2 real,
antrenare `production_champion` declanșată corect, `xgboost_v1` sărit
corect sub prag, `league_weights_adaptive` exclus corect din Challenger
Framework, zero efecte secundare pe `challengers`/`decision_feed`). Acest
fișier reprezintă contractul normativ corespunzător implementării deja
existente în `main` — nu o propunere, un document retroactiv al deciziei
deja aplicate.

**Reconstrucție**: Document nescris pe disc în timp real — Frozen exclusiv în
istoricul conversației, reconstruit aici din conținutul furnizat explicit de
proprietarul produsului, fără completare sau presupunere de conținut lipsă.
**Data reconstrucției**: 2026-07-17.

**Notă de trasabilitate**: fragmentul „ADR Final" furnizat de proprietarul
produsului se încheia cu „pregătit pentru Etapa 4/4 (Freeze)", fără ca
textul propriu-zis al Freeze Declaration să fi fost retrimis (spre
deosebire de ADR-028/031, unde fragmentul de Freeze a fost furnizat
explicit). Freeze Declaration de mai jos e construită acum, nu recuperată
verbatim — formalizează o decizie deja aplicată integral în cod și
producție, fără nicio schimbare de conținut arhitectural față de ADR Final.

---

## Context

Learning Core (Model Registry, `LearningAlgorithm`, Challenger FSM, Promotion
Service + RPC, toate ADR-015…019, deja închise și verificate în producție)
există și funcționează, dar exclusiv manual — antrenarea, evaluarea și
promovarea sunt declanșate prin CLI, de un om, la momentul ales de el.
ADR-028 a închis contradicția de la nivelul căii de scriere (o singură cale
de învățare coerentă). Rămâne deschisă contradicția de la nivelul
declanșării: Regula de Aur #2 cere ca sistemul să observe și să decidă singur
când merită reantrenarea, nu să aștepte inițiativa umană.

Corecția deja stabilită în Independent Architecture Assessment §6 respinge
explicit ideea unui „Continuous Learning Orchestrator" ca subsistem nou,
prim-clasă, construit preventiv — recomandă o funcție mică, decuplată de
`run_daily.py`, formalizată ca subsistem abia dacă/când complexitatea reală o
cere. ADR-030 implementează exact această funcție, nimic mai mult.

## Problem Statement

Fără o decizie autonomă de declanșare, „Continuous Learning" rămâne, în fapt,
„Learning la cerere" — contrazice direct Regula de Aur #2 și lasă precondiția
pentru ADR-031 (N-way Serving) nesatisfăcută: nu are sens să servești
transparent ieșirile mai multor motoare dacă acele motoare rămân, în
continuare, statice între intervențiile manuale ocazionale ale unui om.

## Decision

ADR-030 nu construiește un orchestrator nou. Introduce o singură funcție
mică, decuplată de `run_daily.py`, care decide când Training Runner-ul deja
existent trebuie invocat — nimic din mecanica de antrenare, evaluare sau
promovare nu se schimbă.

Funcția verifică, programat, independent de cadența de sincronizare zilnică,
pentru fiecare intrare din Model Registry și fiecare `league_scope` relevant,
dacă un prag de volum e atins; dacă da, invocă `algorithm.fit()` (neschimbat);
dacă evaluarea rezultată (`shadow_testing.evaluate_experiment()`, neschimbat)
produce `candidate_for_promotion`, creează decizia T3a corespunzătoare în
Decision Feed, conform contractului deja înghețat la ADR-026 (partajat,
rezervat pentru acest ADR).

## Scope

**Intră**: funcția de verificare prag + invocare Training Runner, generică
peste toate intrările din Model Registry; prima implementare reală a
legăturii T3a rezervate la ADR-026; raportare T2 în `automation_runs`;
configurare aditivă a pragurilor în `model_config`; flag
`learning_core_enabled` (nume păstrat, sens redefinit — vezi §Backward
Compatibility).

**NU intră**: metodologia de calcul a drift-ului (consumată dacă există, nu
inventată aici); corecția de comparații multiple (ADR-034); declanșarea
reconcilierii de dataset istoric (ADR-032 — vezi delimitarea explicită mai
jos); N-way serving (ADR-031); orice modificare a `LearningAlgorithm`, Model
Registry, Challenger FSM, Promotion Service, `shadow_testing`, sau logica
internă de walk-forward din `ml_predictor.py`.

## Trigger Logic Contract

- Declanșator primar: prag de volum per `(algorithm_family, league_scope)`,
  construit peste porțile deja existente (`MIN_SAMPLES_TO_TRAIN`,
  `min_matches=200`) — nu le duplică, nu le contrazice.
- Declanșator secundar, opțional: semnal de drift, consumat dacă există din
  monitorizarea deja atribuită L1/L2 — nu calculat de acest ADR.
- Generic, peste toate intrările din Registry — adăugarea unui algoritm nou
  nu cere nicio schimbare aici.
- Limită KISS: verificare booleană simplă — fără motor de reguli, fără
  combinații ponderate de semnale.

Delimitare explicită față de ADR-032: „reantrenare" (acest ADR) reacționează
exclusiv la volumul de date deja existent și validat în `match_history` — nu
inspectează niciodată surse externe și nu inițiază verificări de prospețime a
dataset-urilor istorice. „Reconciliere" (ADR-032) reacționează la apariția
datelor noi la sursă, complet independent de orice prag de antrenare. Singura
interacțiune e indirectă: datele aduse de ADR-032 contribuie ulterior la
volumul verificat aici, fără nicio dependință operațională directă.

## Ownership

| Operație | Cine are voie |
|---|---|
| Declararea pragului de volum per (algoritm, ligă) | Configurare aditivă în `model_config` |
| Verificarea pragului și decizia de declanșare | Exclusiv funcția ADR-030, programată, independentă de `run_daily.py` |
| Antrenarea efectivă | Exclusiv Training Runner-ul existent, prin `algorithm.fit()`, neschimbat |
| Evaluarea statistică | Exclusiv `shadow_testing.evaluate_experiment()`, neschimbată |
| Crearea deciziei T3a la `candidate_for_promotion` | Funcția ADR-030 — primul proprietar real al acestei legături |
| Promovarea efectivă | Exclusiv Promotion Service + `promote_challenger`, neschimbate |

## Integrare cu ADR-026

- T2: verificarea pragului + invocarea Training Runner.
- T3a: implementare reală a contractului deja rezervat, partajat cu ADR-028.
  Dovada atașată reutilizează exact câmpurile deja produse de
  `evaluate_experiment()`/`experiment_registry` — niciun format nou. Planul de
  rollback reutilizează mecanismul deja existent de „supersede" din
  `model_champions`.
- Niciun state machine nou — reutilizare integrală a celor deja înghețate la
  ADR-026.

## Garanții de integritate statistică

- Walk-forward: neatins structural — invocă exclusiv `algorithm.fit()`
  existent, care îl aplică intern.
- Fereastra pre-ADR-034: orice decizie T3a produsă înaintea livrării ADR-034
  populează câmpul obligatoriu de metodă de corecție statistică (deja impus
  generic de ADR-026) cu valoarea explicită `"none — pre-ADR-034"`, niciodată
  gol sau omis — limitarea devine auditabilă la nivelul fiecărei decizii, nu
  doar în text. Recomandare operațională, nu obligație de secvențiere:
  ADR-034 ar trebui prioritizat curând după livrarea operațională a ADR-030.

## Backward Compatibility & Rollback

`LEARNING_CORE_ARCHITECTURE.md` (Not Yet Frozen, superseded unde există
conflict) folosea `learning_core_enabled` cu sensul „pas opțional în
`run_daily.py`". Acest ADR păstrează numele, dar îi redefinește complet
sensul: activează exclusiv verificarea de prag decuplată — vechiul sens nu
mai există și nu trebuie presupus valabil. Implicit `False`.

Rollback: dezactivare prin flag / oprirea declanșatorului programat — zero
risc de date, funcția nu execută niciodată o scriere pe stare canonică fără
aprobare umană (produce exclusiv propuneri T3a).

## Non-Goals

Nu calculează metodologia de drift · nu aplică corecție de comparații
multiple · nu declanșează reconcilierea de dataset istoric · nu modifică
N-way serving · nu atinge `LearningAlgorithm`, Model Registry, Challenger
FSM, Promotion Service, `shadow_testing`, sau walk-forward intern · nu
introduce un motor de reguli de declanșare.

## Dependencies

ADR-026 (frozen) — contractul `automation_runs` + T2/T3a. ADR-028 (frozen) —
precondiția „o singură cale de învățare coerentă", plus faptul că
recalibrarea participă acum ca oricare alt algoritm din Registry.
Infrastructura Learning Core pre-existentă (ADR-015…019, neschimbată).

## Consequences

- ADR-031 (N-way Serving) capătă precondiția satisfăcută: modelele afișate
  nu mai sunt statice, se întrețin singure.
- Regula de Aur #2 devine îndeplinită pentru bucla de reantrenare —
  operatorul nu mai trebuie să-și amintească să declanșeze manual.
- Se deschide, cunoscut și acceptat, riscul statistic al ferestrei
  pre-ADR-034 — vizibil explicit în fiecare decizie afectată, nu ascuns.
- Documentul de proiectare vechi (`LEARNING_CORE_ARCHITECTURE.md`) e formal
  suprascris pe punctul specific al integrării în `run_daily.py`.

## References

ADR-004 · `LEARNING_CORE_ARCHITECTURE.md` (superseded parțial) · ADR-026
(frozen) · ADR-028 (frozen) · ADR-015…019 (Learning Core pre-existent) ·
Final Strategic Blueprint · Execution Roadmap · Independent Architecture
Assessment §6 · ADR-030 Planning Draft · ADR-030 Clarification Pass.

## Open Questions

1. TTL propriu pentru deciziile T3a ale ADR-030 — ADR-026 cere ca fiecare
   producător să declare propriul TTL pentru deciziile de tip T3; acest ADR
   nu a declarat încă o valoare (nici în Planning Draft, nici în
   Clarification Pass). Prins abia acum, la sinteza finală — nu blochează
   Freeze-ul (analog cu Open Question #1 de la ADR-026, tratat identic:
   necesită o valoare la implementare, nu o decizie arhitecturală nouă), dar
   trebuie semnalat explicit, nu inventat tacit aici.
   **Rezolvat la implementare** (nu prin acest ADR): `_PROMOTION_DECISION_TTL_HOURS
   = 168.0` (7 zile) în `learning_core/continuous_learning.py`, comentat
   explicit ca „valoare de implementare, nu decizie de arhitectură".
2. Cele două întrebări deschise moștenite de la ADR-026 (fallback TTL
   generic; definiția „aprobator") rămân deschise, neatinse de acest ADR.

---

## Freeze Declaration (Etapa 4/4 — construită acum, vezi notă de trasabilitate din header)

**ADR-030 — FROZEN.**

Status actualizat: Decis → Frozen. Tratat de acum ca contract normativ, nu
document de lucru — nicio modificare arhitecturală ulterioară decât
printr-un ADR nou, dedicat, per aceeași regulă aplicată ADR-026/028.

### Ce rămâne blocat, permanent, prin acest freeze:

- Funcția de Continuous Learning rămâne decuplată de `sync/run_daily.py` —
  nu devine niciodată un pas al lui.
- Generic peste tot Model Registry-ul — niciun if/elif pe nume de algoritm
  în bucla de orchestrare (confirmat în cod, `run_cycle()`).
- Garda de consistență („cel mult un Challenger activ") rămâne obligatorie,
  independentă de `get_active_challenger()` — o anomalie oprește procesarea,
  nu alege arbitrar.
- `learning_core_enabled` păstrează sensul redefinit prin acest ADR — nu
  cel vechi, din `LEARNING_CORE_ARCHITECTURE.md`.
- Fereastra pre-ADR-034 rămâne explicit auditabilă
  (`correction_method="none — pre-ADR-034"`), nu ascunsă.

### Drumul critic, poziție confirmată:

`ADR-026 (Frozen) → ADR-028 (Frozen) → ADR-030 (Frozen) → ADR-031 → ADR-033`

### Următorul pas

La momentul acestui Freeze (reconstrucție), ADR-031 și ADR-033 erau deja
decise separat — vezi fișierele lor proprii pentru continuarea drumului
critic.
