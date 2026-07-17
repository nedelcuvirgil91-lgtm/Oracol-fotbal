# ADR-010 — Odds Historical Backfill & Provenance

**Status**: Accepted
**Affects**: `docs/03_ENGINE/ODDS_PERSISTENCE_DESIGN.md` (extindere, fără modificarea textului existent), schema `odds_history` (extindere aditivă de coloane)
**Authority**: Principal Software Architect

---

## Context

`ODDS_PERSISTENCE_DESIGN.md` (Frozen, ADR-005/006) a fost proiectat exclusiv pentru captura **live** — eligibilitatea din §9 presupune explicit un kickoff viitor. Sprint-ul Odds Infrastructure introduce un backfill **istoric** (football-data.co.uk, ultimii 5 ani) care scrie în aceeași tabelă, dar sub un regim temporal diferit: valori finale, deja cunoscute, scrise o singură dată — nu o piață activă, capturată progresiv în timp. Documentul Frozen nu tratează explicit acest caz.

În plus, odată ce `odds_history` primește date din mai mult de o sursă (live: The Odds API; istoric: football-data.co.uk; potențial viitor: alte surse din Knowledge Engine, Prioritatea 5), tabela nu mai poate răspunde singură la întrebarea "de unde provine acest rând?" — informație esențială pentru trasabilitate pe termen lung, deja regulă de bază a proiectului (North Star #9: „Orice rezultat trebuie trasabil complet până la sursă").

## Decision

1. **Regim temporal dual, fără modificarea regulii §9.** Backfill-ul istoric e o utilizare validă a primitivei de scriere deja existente (`upsert_odds_snapshot` / `OddsPersistenceService._upsert`), aplicată de două ori per `(fixture_id, bookmaker)` — o dată cu prețul de opening, o dată cu cel de closing — **fără** verificarea de eligibilitate din §9, care nu se aplică conceptual unor meciuri deja jucate. Regula §9 rămâne neschimbată, în vigoare identic pentru fluxul live.

2. **Schema `odds_history` se extinde aditiv, cu 4 coloane noi**, fără să atingă nicio coloană existentă:
   - `provider` (text, obligatoriu) — sursa de date externă (ex. `the-odds-api`, `football-data.co.uk`), distinctă de `bookmaker` (casa de pariuri reală ale cărei cote sunt raportate).
   - `import_type` (text, obligatoriu) — `live_capture` sau `historical_backfill`.
   - `import_version` (text, obligatoriu) — identificatorul versiunii de cod care a scris rândul (ex. `OddsPersistenceService_v1`, `OddsBackfill_v1`).
   - `imported_at` (timestamptz, obligatoriu, default `now()`) — momentul în care rândul a fost scris în baza noastră de date; distinct semantic de `opening_fetched_at`/`closing_fetched_at`, care marchează momentul observării prețului pe piață, nu momentul importului.

3. **Cele 4 coloane noi devin imuabile după prima scriere** — se adaugă la lista de coloane protejate de `odds_history_immutability_guard`, alături de `opening_*`/`opening_fetched_at`/`id`/`fixture_id`/`bookmaker`. Proveniența, la fel ca `opening_*`, e un fapt istoric — nu o stare curentă, nu se rescrie.

4. **Completare retroactivă, NULL-only, non-destructivă**: cele 8 rânduri deja scrise de fluxul live înainte de acest ADR primesc `provider='the-odds-api'`, `import_type='live_capture'`, `import_version='OddsPersistenceService_v1'`, `imported_at=opening_fetched_at` (singura aproximare rezonabilă disponibilă a momentului real de import). Aceeași disciplină aplicată la backfill-ul ELO — se completează doar ce e NULL, nimic nu se suprascrie.

## Rationale

Separă explicit **ce reprezintă o cotă** (bookmaker, valorile 1X2, opening/closing) de **cum a ajuns acea cotă în sistemul nostru** (provider, tip de import, versiune, moment) — distincție care nu exista înainte și devine esențială din momentul în care există mai mult de o sursă de adevăr pentru aceeași tabelă. Fără proveniență, o interogare peste doi ani nu ar putea răspunde „de ce `odds_history` conține date istorice, deși infrastructura a fost proiectată inițial pentru live" — exact întrebarea pe care acest ADR o rezolvă permanent, prin date, nu doar prin discuție arhivată.

## Consequences

- `ODDS_PERSISTENCE_DESIGN.md` rămâne neschimbat ca text — extins prin acest ADR, nu editat direct (consistent cu `FROZEN_REGISTRY.md`).
- Orice writer viitor pe `odds_history` (surse noi din Knowledge Engine — alte piețe, alți provideri) **trebuie** să populeze cele 4 coloane de proveniență — nu opțional, aplicat de la primul rând.
- Trigger-ul de imutabilitate trebuie actualizat, la implementare, pentru a include coloanele noi în lista protejată — parte obligatorie a implementării acestui ADR, nu o decizie separată.
- Analitice viitoare bazate pe piață (Closing Line Value, Market Drift, Market Efficiency, Calibration vs Market, Market Surprise, Betting Bias, evoluția pieței înaintea meciului) devin calculabile direct din coloanele deja existente (`opening_*`/`closing_*`) plus proveniență, ca interogări/view-uri — **fără nicio schimbare suplimentară de schemă**.
