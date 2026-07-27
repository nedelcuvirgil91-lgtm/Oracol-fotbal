# ADR-039 — Universal Synchronization Architecture & Supabase First

**Status**: FROZEN — arhitectură aprobată oficial de proprietarul produsului, 2026-07-22. Devine baza oficială pentru implementarea Universal Synchronization Architecture. Tratat de acum ca contract normativ — nicio modificare arhitecturală ulterioară decât printr-un ADR nou, dedicat, sau o problemă demonstrată în implementare (nu o preferință), per aceeași disciplină aplicată ADR-030…038.

**Autor**: Claude, audit + design, la cererea explicită a proprietarului produsului. Companion: `docs/03_ENGINE/UNIVERSAL_SYNC_ARCHITECTURE_AUDIT_2026-07-22.md` (evidența completă, per provider).

**Data**: 2026-07-22.

---

## Context

ADR-038 a rezolvat sincronizarea pentru un singur provider (API-Football), stabilind explicit o excepție rămasă deschisă: Oracle Engine continua să apeleze providerul direct (prin Request Manager, dar tot direct), iar politica generală a proiectului (ADR-035) permitea explicit „apel direct la provider, excepție, nu regulă" atunci când Supabase nu are date suficiente.

Discuția ulterioară (proprietar produs, sesiunea curentă) a stabilit o decizie fundamentală: **excepția se elimină, pentru toți providerii, nu doar pentru API-Football.** Regula devine universală:

> Orice provider extern există EXCLUSIV pentru sincronizarea și îmbogățirea bazei de date Supabase. Oracle Engine, Prediction Engine, ML și Feature Engineering nu mai au voie să cunoască existența niciunui provider extern — citesc exclusiv din Supabase.

Auditul companion (§1) a demonstrat că 7 provideri reali (API-Football, Odds API, Weather API, football-data.org, FreeLF, ESPN, TheSportsDB) plus unul deja conform (Kaggle) sunt afectați, cu roluri și riscuri diferite — nu toți sunt „fallback-uri" (FreeLF și Odds API sunt surse PRIMARE de descoperire a meciurilor).

## Decizie

### North Star (extins, nu contrazis)

Regula ADR-035 („Niciun provider extern nu poate avea prioritate asupra unei informații deja sincronizate și validate în baza canonică Supabase") devine literă de lege, fără excepție de tip „date insuficiente → apel live". Dacă Supabase nu are încă o informație, răspunsul e „necunoscut" (Regula #8, CLAUDE.md), niciodată un apel live de completare.

### Principii arhitecturale

1. **Un singur strat poate vorbi cu providerii externi: Universal Sync Layer.** Niciun alt modul (Oracle Engine, ML, Feature Engineering, Prediction Engine) nu importă, nu instanțiază, nu apelează direct sau indirect vreun adaptor de provider.
2. **Sync Layer e generic, nu per-provider.** Scheduler (Sync Orchestrator), Request Manager, Rate Limit Manager sunt deja construite generic (R4.1) — rămân neschimbate, reutilizate de orice adaptor nou.
3. **Fiecare provider capătă un adaptor formal** (`SyncAdapter`: fetch/normalize/validate/persist/coverage_check opțional) — extensie directă a tiparului deja dovedit (`FootballDataProvider`, `football_providers.py`), nu un concept nou.
4. **Niciun cod deja funcțional nu se rescrie fără migrare testată per pas.** Odds persistence (Frozen, ADR-005/006) și `match_history` Database-First (ADR-035 D1-D3) rămân neatinse — ele deja satisfac regula, nu sunt obiectul acestui ADR.
5. **Migrare provider-cu-provider, niciodată big-bang.** Secvențiere pe risc (audit §6, **corectată post-R-Sync-2** — audit §6b — **și din nou post-R-Sync-3** — audit §6c, pentru dovada/justificarea fiecărei corecții): API-Football injuries/coaches (**finalizat, R-Sync-2**) → football-data.org formă/standings, **exclus explicit fixtures** (**finalizat, R-Sync-3**) → **eloratings.net, ELO național** (R-Sync-4 — **corectat, audit §6c: NU e TheSportsDB, provider distinct — eroare de clasificare demonstrată și corectată prin cod, nu presupusă**) → Weather (R-Sync-5) → FreeLF formă/standings + Odds API fallback H2H/formă, exclus explicit orice rol de descoperire (R-Sync-6) → **Universal Match Discovery Layer** (R-Sync-7, TOȚI providerii de fixtures într-un singur pas: FreeLF, Odds API, football-data.org, ESPN, TheSportsDB, **și API-Football** — niciun provider de fixtures nu rămâne tratat separat sau privilegiat) → **TheSportsDB team stats** (R-Sync-8 — **mutat aici, audit §6c: cuplat structural la `team_id` `tsdb_`-prefixat, produs DOAR de Match Discovery; migrare curată abia posibilă după R-Sync-7, fără introducerea unei rezoluții de identitate noi și neaprobate**) → eliminarea finală a `self.api` din Oracle Engine (R-Sync-9).
6. **Supabase e Football Data Warehouse-ul proiectului** — denumire formală a ceea ce principiile 1-2 și fluxul din audit §3 deja stabilesc: singurul depozit canonic pe care Oracle Engine/ML/Feature Engineering/Prediction Engine îl citesc, alimentat exclusiv prin fluxul `Provider → Sync Adapter → Normalize → Validate → Persist → Supabase`. Nu e un concept nou — e numele conceptului deja definit.
7. **Identitatea canonică a entităților (Team/Match/Competition) e deja rezolvată, prin nume normalizat, nu prin ID numeric de provider.** Sync Adapters (principiul 3) nu inventează identificatori noi — folosesc exclusiv mecanismele deja existente: `ADR-024`/`ADR-025` (Match, Frozen — cheie `(echipe normalizate, dată)`, fără ligă în cheie, crosswalk-ul de ID-uri explicit respins acolo), `mappings.TEAM_ALIASES`/`normalize_team_name()` (Team), `mappings.LEAGUE_PROVIDERS` (Competition, cheie = nume canonic, `provider_ids` per provider dedesubt — exact tiparul deja folosit de Coverage Cache, ADR-038). Niciun adaptor nou nu are voie să introducă o a doua sursă de identitate paralelă.

### Scope-ul acestui ADR

**În scope**: definirea Universal Sync Layer, interfața `SyncAdapter`, modelul de persistare Supabase per tip nou de date (`team_health_snapshot`, `scheduled_fixtures`, `weather_forecast_cache`), politica de sincronizare per provider, strategia de migrare secvențială.

**În afara scope-ului, explicit**:
- Nu redeschide ADR-034 (Provider Capability Selection) — Sync Layer consumă providerii, nu decide între ei; Selection Engine rămâne subiectul lui ADR-034, neatins.
- Nu redeschide ADR-005/006 (Odds Persistence, Frozen) — cotele pre-meci rămân pe calea existentă.
- Nu implementează încă niciun adaptor — acest ADR e contract, nu cod.
- Nu elimină încă `self.api`/`self.apifootball` din `oracle_engine.py` — asta e ultimul pas al roadmap-ului (audit §8), condiționat de finalizarea migrării tuturor providerilor.

## Consecințe

- **Pozitive**: Oracle Engine devine, odată finalizată migrarea, complet independent de disponibilitatea oricărui provider extern — North Star-ul „oprești un provider o săptămână, Oracle continuă din Supabase" devine adevărat universal, nu doar pentru API-Football.
- **Neutre**: infrastructura deja construită în R4.1 (Scheduler, Request Manager, Rate Limit Manager) rămâne complet reutilizabilă — zero regresie de arhitectură deja funcțională.
- **Risc acceptat, documentat**: descoperirea meciurilor (FreeLF/Odds/football-data/ESPN) e o migrare structural mai mare decât oricare fallback individual — afectează calea prin care se află *ce meciuri există*, nu doar *ce date are un meci deja cunoscut*. Tratată explicit ca etapă proprie, ultima, nu subestimată prin includere tacită în pașii anteriori.
- **Cost real, numit**: cadența de sincronizare diferă masiv per provider (Kaggle: o dată; injuries: ore; descoperire meciuri: posibil ore; vreme: de câteva ori/zi) — nu există o cadență universală unică, fiecare adaptor își declară propria politică.

## Referințe

- `docs/03_ENGINE/UNIVERSAL_SYNC_ARCHITECTURE_AUDIT_2026-07-22.md` — evidența completă.
- `docs/00_GOVERNANCE/ADR-038-api-football-synchronization-architecture-v2.md` — primul pas, API-Football, neatins, extins acum.
- `docs/00_GOVERNANCE/ADR-035-database-first-prediction-engine.md` — principiul de bază pe care acest ADR îl extinde, eliminând excepția de fallback live.
- `docs/00_GOVERNANCE/ADR-034-provider-capability-selection-architecture.md` — strat de abstractizare peste care Sync Layer se construiește, neatins.
- `docs/00_GOVERNANCE/ADR-036-canonical-feature-ownership.md` — precedentul de ownership unic de scriere, reaplicat la fiecare tabelă nouă.
- `docs/00_GOVERNANCE/ADR-024-canonical-match-identity-data-contract.md` + `docs/00_GOVERNANCE/ADR-025-match-identity-implementation-strategy.md` (Frozen) — identitatea canonică a unui meci, deja decisă; sursa pentru principiul 7.
- `docs/03_ENGINE/TEAM_IDENTITY_AUDIT.md` — identitatea canonică a unei echipe, `TEAM_ALIASES`/`normalize_team_name()`; documentează și un gol de wiring cunoscut (nu toți writerii aplică normalizarea la scriere), în afara scope-ului acestui ADR.

---

**FREEZE CONFIRMAT.** Nicio linie de cod scrisă sub acest ADR. Arhitectura de mai sus (Universal Sync Layer, `SyncAdapter`, modelul de persistare, politica de migrare provider-cu-provider, identitatea canonică prin nume normalizat) devine contractul normativ pentru orice sincronizare externă a proiectului. Implementarea urmează roadmap-ul din audit companion (§8), incremental, pas cu pas, fiecare cu aprobare explicită separată — fără extindere de scope, fără redesign suplimentar decât la o problemă demonstrată în implementare.
