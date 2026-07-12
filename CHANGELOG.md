# Changelog

Toate schimbările notabile ale proiectului sunt documentate aici.

## [4.0.0] — 2026-07-12

### Adăugat
- **Odds Persistence Service** (`services/odds_persistence_service.py`) — persistare istorică a cotelor de piață (opening/closing), cu contract de arhitectură dedicat (`docs/03_ENGINE/ODDS_PERSISTENCE_DESIGN.md`, ADR-005, ADR-006).
- Migrare SQL versionată pentru `odds_history` (`database/migrations/001_odds_history.sql`) — schemă, trigger de imutabilitate structurală, funcție RPC de persistare atomică.
- Walk-forward validation (expanding window) pentru antrenarea ML, înlocuind `train_test_split` aleator — elimină scurgerea temporală.
- De-vig pentru probabilitățile implicite ale bookmaker-ilor (`_devig_probabilities()`) — Value Betting Engine folosește acum probabilități "fair", fără marja bookmaker-ului.
- Audit de feature importance (permutation importance, ablație) pe 53.409 meciuri reale — 6 feature-uri ML cu importanță zero eliminate din antrenare.
- `docs/03_ENGINE/FEATURE_ENGINEERING_ROADMAP.md` — analiză completă a candidaților de feature engineering, ordonați după ROI/complexitate.
- `docs/03_ENGINE/REST_DAYS_VALIDATION.md` — validare empirică (nu doar teoretică) a ipotezei "rest days" — verdict: neintegrat, fără câștig măsurabil.
- Consolidare alias echipă (`Dinamo Bucuresti`/`Dinamo București`/`Din. Bucuresti` → o singură identitate canonică) în `mappings.py`.

### Corectat
- Import Romania SuperLiga extins (2021-2026, 917 meciuri noi), cu deduplicare corectă prin normalizare de nume.
- Câmp `bookmaker` curat, expus explicit pe obiectele `match` (anterior doar încapsulat în șirul de afișare `odds_source`).

### Guvernanță
- `docs/00_GOVERNANCE/FROZEN_REGISTRY.md` — registru oficial al documentelor de arhitectură Frozen.
- ADR-005, ADR-006 — clarificări de guvernanță și operaționale pentru `ODDS_PERSISTENCE_DESIGN.md`.

### Cunoscut, neschimbat în această versiune
- `recalibrate_weights()` — mecanism legacy, păstrat activ pentru continuitatea unui viitor benchmark comparativ; nu mai primește dezvoltare nouă.
- Schema completă Supabase (15 din 16 tabele) nu are încă migrări `.sql` versionate — doar `odds_history` e acoperit complet.
- Chei API (`ODDS_API_KEY`, `WEATHER_API_KEY`, `RAPIDAPI_KEY`) rămân hardcodate în `oracle_api.py` — migrare planificată, neurgentă (repo privat).

---

*Versiunile anterioare nu au fost documentate retroactiv în acest changelog — istoricul complet de dezvoltare există în conversațiile de proiect asociate.*
