---
name: architecture-review
description: Verifică orice dependență nouă introdusă între module (import nou între fișiere din arii funcționale diferite) față de regulile de layering și disciplina ADR documentate în CLAUDE.md. Se invocă automat la orice diff care introduce o dependență nouă între module.
---

# architecture-review

## Scop

Prinde greșeli structurale — o dependință nouă care contrazice un contract deja documentat — înainte ca ele să ajungă în cod, nu după. E gardul cu cea mai mare acoperire per efort din nucleul de skill-uri, pentru că se aplică oricărei schimbări de structură, nu doar celor din Learning Core.

## Când se declanșează

Automat, la orice diff care adaugă un `import` nou între fișiere aparținând unor arii funcționale diferite (ex. un modul de date brute care importă direct din motorul de predicție, sau invers).

## Verificare obligatorie înainte de orice modificare structurală

1. **Direcția dependinței respectă separarea deja existentă** (vezi `CLAUDE.md`, Knowledge Map): module de acces la date (`oracle_api.py`, `supabase_client.py`, `database/queries.py`) nu importă niciodată din motorul de predicție (`oracle_engine.py`) sau din ML (`ml_predictor.py`) — dependența merge într-un singur sens, dinspre motor spre date, niciodată invers.
2. **`recalibration.py` și `shadow_testing.py` rămân fără dependințe circulare** — `shadow_testing.py` nu importă `oracle_engine.py` (documentat explicit chiar în header-ul `shadow_testing.py`); `recalibration.py` rămâne funcție pură, fără I/O.
3. **`mappings.py` (`LEAGUE_PROVIDERS`) rămâne sursă canonică unică** — nicio copie manuală nouă a unei mapări ligă→provider (exact greșeala descrisă și reparată în ADR-001).
4. **Schimbarea atinge un contract deja documentat** (model de date, responsabilitate de componentă, flux) în vreun ADR existent? Dacă da → oprire, cere ADR nou înainte de a continua.

## Reguli de respectat

- North Star #5: orice schimbare de contract trece prin ADR, nu prin editare tăcută.
- North Star #10: nicio dependință „în sus" între straturile arhitecturale — regulă generală de layering, aplicabilă chiar și fără ca Learning Core (L0-L6) să fie încă implementat ca atare.
- ADR-001 (sursă canonică unică pentru mapări).

## Fișiere de cunoscut

`CLAUDE.md` (Knowledge Map — sursa curentă, în repo, pentru rolul fiecărui modul), toate ADR-urile din `architecture/` și `docs/00_GOVERNANCE/`.

**Notă importantă**: acest skill nu se bazează pe documentele detaliate de arhitectură Learning Core (straturile L0-L6, cele 18 componente, dependency graph) discutate în proiectare — acelea nu sunt încă persistate ca fișiere în acest repo. Până când vor fi transcrise în `docs/`, singura sursă de adevăr verificabilă în repo pentru regulile de layering e secțiunea „Regulile pentru Learning Core" din `CLAUDE.md` și ADR-urile existente. Acest skill nu presupune și nu inventează conținut din afara repo-ului.

## Dacă declanșează un conflict de arhitectură

Oprește modificarea structurală respectivă, explică exact ce regulă de layering ar fi încălcată și ce ADR ar fi necesar — nu proceda unilateral.

## Obligatoriu / Opțional

**Obligatoriu**, la orice dependență nouă între module.
