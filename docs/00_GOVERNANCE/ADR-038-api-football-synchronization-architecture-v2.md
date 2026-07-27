# ADR-038 — API-Football Synchronization Architecture V2

**Status**: FROZEN — arhitectură aprobată oficial de proprietarul produsului, 2026-07-22. Tratat de acum ca contract normativ, nu document de lucru — nicio modificare arhitecturală ulterioară decât printr-un ADR nou, dedicat, per aceeași disciplină aplicată ADR-030…037.

**Autor**: Claude, audit + design, la cererea explicită a proprietarului produsului. Companion: `docs/03_ENGINE/API_FOOTBALL_SYNC_V2_AUDIT_2026-07-22.md` (evidența completă, per-endpoint).

**Data**: 2026-07-22.

---

## Context

Football Oracle depinde azi de API-Football pentru **date de sănătate a echipei** (accidentări, antrenori) și, marginal, rezolvare de ID de echipă — nu pentru fixtures (fallback-ul e inert azi, blocat de restricția de plan Free pe Romania SuperLiga, verificat live) și deloc pentru odds/predicții/statistici avansate.

Auditul (companion doc) a găsit că apelul către API-Football e **necondiționat, per meci evaluat**, în calea principală `oracle_engine.evaluate_match()` — nu doar un fallback rar. Cu un plan Free (100 cereri/zi, cheie confirmată în audit) și un sistem de urmărire a cotei care aproximează greșit limita reală (lunar, nu zilnic), acesta e riscul operațional central pe care această arhitectură trebuie să-l rezolve.

În paralel, ADR-034 (Frozen) a construit deja un strat de abstractizare de provider (registry, capabilities, health, selector) — **neimplicat încă în calea de producție** (Selection Engine rămâne Shadow Mode, PR6/PR7 din ADR-034 neexecutate). Acest ADR **nu redeschide** ADR-034 — se construiește deasupra lui, ca un al doilea strat, specific API-Football.

## Decizie

### North Star (neschimbat, reafirmat)
Dacă API-Football dispare complet 24-48h, Oracle continuă să producă predicții. Doar sincronizarea e afectată. Degradare grațioasă (feature „necunoscut", Regula #8 deja respectată în tot proiectul), niciodată catastrofică.

### Principii arhitecturale
1. **Prediction Engine, Learning Core, Champion Guardian, Rollback Engine nu depind niciodată de API-Football** — adevărat deja azi (verificat: niciuna din aceste componente nu importă `football_providers`/`oracle_api` direct pentru date live de decizie), reafirmat explicit ca invariant permanent.
2. **Doar Synchronization Layer poate apela API-Football** — azi parțial adevărat (`ApiFootballProvider` e singurul punct de apel), de întărit printr-un Request Manager (audit §4) care devine **singurul** punct de trecere.
3. **Niciun cod deja funcțional nu se rescrie fără un defect demonstrat** — respectat: cache-ul disk+Supabase (L1/L2), retry-ul HTTP, coverage gate-ul pe `/injuries`/`/fixtures` rămân neatinse. Singurele corecții propuse au defect concret citat (audit §16).
4. **Nicio capacitate nouă fără valoare măsurabilă demonstrată** (Regula „Data Value Review", audit §16) — domeniul Live, fixture-centric sync, historical odds pe API-Football sunt **deferate explicit**, nu construite preventiv.

### Scope-ul acestui ADR
**În scope**: Request Manager (buget zilnic real, RAM L0, dedup, coverage cache), corectarea celor 2 defecte reale găsite (gardă lipsă pe `/coachs`, declarație `ODDS` neimplementată), centralizarea cheilor API-Football-adiacente (audit §13).

**În afara scope-ului, deferat**: domeniul Live, sincronizare fixture-centric, odds istoric pe API-Football (sursa existentă, Odds API, Frozen, acoperă deja nevoia), orice extindere de endpoint fără justificare de valoare.

## Consecințe

- **Pozitive**: reducere de risc operațional real (buget zilnic corect urmărit vs. aproximare lunară greșită azi); un defect real de cotă corectat (`get_coaches` fără coverage gate); igienă de chei îmbunătățită.
- **Neutre**: cache-ul existent (L1/L2), retry-ul HTTP, `provider_capabilities`/`registry`/`selector` (ADR-034) rămân neatinse — zero regresie de arhitectură deja funcțională.
- **Risc acceptat, documentat**: coverage-ul per-ligă rămâne „necunoscut" pentru ~10 din 11 ligi monitorizate până la o verificare live explicită (blocată azi de politica de rețea a acestui mediu de audit — nu de arhitectură) — Coverage Cache (audit §2) e proiectat să capteze rezultatul quando devine posibil, nu presupune valori.

## Referințe
- `docs/03_ENGINE/API_FOOTBALL_SYNC_V2_AUDIT_2026-07-22.md` — evidența completă.
- `docs/00_GOVERNANCE/ADR-034-provider-capability-selection-architecture.md` — stratul de abstractizare peste care se construiește, neatins.
- `docs/00_GOVERNANCE/FROZEN_REGISTRY.md` — niciun document Frozen atins de acest ADR.

---

**FREEZE CONFIRMAT.** Nicio linie de cod de producție, test, SQL sau workflow scrisă sub acest ADR. Arhitectura de mai sus (Request Manager, Coverage Cache, cele 2 defecte reale corectate, centralizarea cheilor API-Football-adiacente) devine contractul normativ pentru Synchronization Layer API-Football. Implementarea propriu-zisă (Implementation Roadmap, audit companion) e faza următoare, separată de acest freeze, cu aprobare explicită per pas — urmând exact disciplina deja aplicată la ADR-037.
