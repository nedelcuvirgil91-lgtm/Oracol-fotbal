# ADR-006 — Odds Persistence: Operational Clarifications

**Status**: Accepted
**Affects**: `docs/03_ENGINE/ODDS_PERSISTENCE_DESIGN.md` (clarificare, fără modificarea textului)
**Authority**: Principal Software Architect

---

## Context

Un review de arhitectură ulterior declarării `ODDS_PERSISTENCE_DESIGN.md` ca `FROZEN` (via ADR-005) a identificat patru puncte care nu contrazic contractul tehnic deja stabilit, dar merită precizie explicită înainte de implementare, pentru a elimina orice interpretare ambiguă la nivel de cod.

## Decision

Următoarele patru clarificări se aplică, ca precizări operaționale, fără să modifice nicio regulă din `ODDS_PERSISTENCE_DESIGN.md`:

### 1. Definiția precisă a "date invalide sau incomplete"

Un set de cote e considerat invalid dacă **oricare** din componentele lui (`home`, `draw`, `away`) satisface una din următoarele:
- `NULL` (lipsă completă a valorii);
- `NaN` (rezultat numeric nedefinit);
- valoare `<= 1` (o cotă zecimală validă e mereu strict mai mare decât 1 — o valoare `<= 1` nu poate reprezenta o cotă reală);
- valoare negativă;
- tip de date invalid (orice valoare care nu poate fi interpretată ca număr — string, obiect malformat etc.).

Regula de respingere integrală din `ODDS_PERSISTENCE_DESIGN.md §7` se aplică identic pentru oricare din aceste cinci cazuri, fără distincție de tratament.

### 2. Fusul orar pentru determinarea kickoff-ului

Comparația `VALIDATED.fixtures.event_date > now()` (§9) se execută **exclusiv în UTC** — consistent cu restul platformei, care operează integral în UTC (confirmat: toate coloanele `timestamptz` din `DATABASE_SPEC.md`, inclusiv `opening_fetched_at`/`closing_fetched_at`, sunt stocate și comparate în UTC). Nu există conversie de fus orar local la niciun pas al acestei comparații.

### 3. Scope explicit — piața 1X2

`OddsPersistenceService` persistă **exclusiv** piața 1X2 (Home/Draw/Away). Orice altă piață (Over/Under, Both Teams to Score, Asian Handicap, sau altele) e explicit **în afara scope-ului** acestui document și al schemei `odds_history` curente. Extinderea la alte piețe ar necesita o schimbare de schemă și un ADR dedicat, nu o presupunere implicită.

### 4. Absența retry-ului în cadrul aceleiași rulări

Dacă un set de cote e respins ca invalid (per punctul 1) sau dacă apare o eroare tranzitorie (ex. timeout la fetch) pentru un anumit `(fixture_id, bookmaker)`, Serviciul **nu reîncearcă** în cadrul aceleiași execuții. Fixture-ul/bookmaker-ul respectiv rămâne, pur și simplu, neactualizat pentru acea rulare — va fi reevaluat natural la următoarea execuție programată (§9). Acest comportament era deja deductibil din descrierea izolării per-fixture (`PIPELINE_SPEC.md`, aplicată prin analogie), dar nu era afirmat explicit.

## Rationale

Niciunul din cele patru puncte nu introduce o decizie de arhitectură nouă — toate sunt precizări ale unor comportamente deja implicite în contractul existent, formulate acum explicit pentru a elimina orice ambiguitate de implementare. Tratarea lor ca ADR, nu ca editare a documentului Frozen, menține disciplina de guvernanță stabilită prin ADR-005.

## Consequences

- `ODDS_PERSISTENCE_DESIGN.md` rămâne neschimbat.
- Implementarea `OddsPersistenceService` trebuie să respecte explicit cele 4 clarificări de mai sus, ca parte a contractului complet (document + ADR-005 + ADR-006).
- Orice extindere viitoare la alte piețe de pariuri (dincolo de 1X2) necesită un ADR separat, nu o adăugare tacită.
