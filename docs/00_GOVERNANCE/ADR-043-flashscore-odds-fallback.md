# ADR-043 — Flashscore ca sursă de fallback temporar pentru cote (Predictor)

**Status**: **ACCEPTAT** (2026-07-29) — aprobat explicit de proprietarul produsului ("Sunt conștient că există ADR-urile privind odds_history. Sunt de acord cu soluția ta"). Schema propusă (`odds_fallback_flashscore`) aplicată live (migrația 032, Stage 1 din implementarea etapizată) — `odds_history` rămâne complet neatins, confirmat. **Implementare completă (2026-08-04)**: scrierea reală (`providers/flashscore/pre_match_odds.py`, `sync/sync_pre_match_odds.py`, discovery săptămânală + fallback de cote, izolat de `discovery.py`/`adapter.py`/`persistence.py`) și regula de citire pentru Predictor (§Decizie, pct. 3 — `database.queries.get_odds_fallback_for_missing_fixtures()`, cablată în `oracle_api.get_matches_for_week()` prin `_attach_flashscore_odds_fallback()`, funcție nouă separată, imediat după `_attach_odds()`) sunt ambele funcționale, gatate de flag-uri dedicate implicit OPRITE (North Star #3): `flashscore_odds_fallback_enabled` (`flashscore_odds_fallback_config.py`) pentru citire, workflow manual `sync_pre_match_odds.yml` pentru scriere (necablat încă în orchestrarea automată zilnică, deliberat, cât timp rămâne în etapa de verificare la scară).

**Autor**: Claude, la cererea proprietarului produsului.

**Data**: 2026-07-29.

**Companion**: `docs/03_ENGINE/ODDS_PERSISTENCE_DESIGN.md` (Frozen, ADR-005/ADR-006/ADR-010 — **neatins de acest ADR**, vezi Decizie), `docs/06_UDAL/R-SYNC-FLASH-01_DESIGN.md` §10.7 (context complet), `docs/06_UDAL/UDAL_FLASHSCORE_POC_10MATCHES_REPORT.md` (dovada tehnică — cote reale confirmate extractibile).

---

## Context

`R-SYNC-FLASH-01_DESIGN.md` (versiunea inițială) exclusese deliberat cotele din scope-ul Flashscore, motivând că `ODDS_PERSISTENCE_DESIGN.md` e Frozen și orice atingere a modelului de date de cote necesită ADR dedicat, nu un side-effect al unui provider auxiliar nou.

Proprietarul produsului a cerut explicit o excepție: aplicația nu are azi cote funcționale pentru Predictor, iar Flashscore a confirmat (POC, 10 meciuri) date reale de cotă, de la bookmaker-i reali (bet365, Unibet). Cerința explicită: Flashscore poate completa acest gol, dar **strict ca fallback temporar**, fără să devină provider principal de cote, fără să schimbe filosofia proiectului.

Verificare directă a schemei live (`database/migrations/001_odds_history.sql`) confirmă riscul tehnic concret al unei implementări naive: `odds_history` are cheia `UNIQUE(fixture_id, bookmaker)` — **fără nicio coloană de sursă/provider**. Dacă Flashscore ar scrie direct în `odds_history` folosind același nume de bookmaker ca sursa oficială (The Odds API), cele două surse s-ar putea amesteca pe același rând, fără nicio urmă a cărei valoare provine de unde — încălcare directă a North Star #9 ("orice rezultat trasabil complet până la sursă").

## Decizie

1. **`odds_history` (Frozen) rămâne complet neatins** — nicio coloană nouă, niciun writer nou, niciun trigger modificat. Acest ADR **nu redeschide** `ODDS_PERSISTENCE_DESIGN.md`.
2. Se introduce o tabelă **nouă, separată**: `odds_fallback_flashscore` — `(fixture_id, bookmaker, home, draw, away, captured_at)`, `UNIQUE(fixture_id, bookmaker)`, RLS activ, scriere exclusivă Flashscore Night/Pre-Match Sync.
3. **Regula de citire pentru Predictor** (implementată într-un singur punct, `database/queries.py`, nu dispersat): citește întâi `odds_history`; **doar dacă** acel `fixture_id` nu are niciun rând acolo, citește `odds_fallback_flashscore`. Niciodată amestecate pe același fixture; `odds_history`, când există, are prioritate necondiționată.
4. **Etichetare la nivel de nume de tabelă**, nu doar de convenție de cod — orice interogare viitoare care citește `odds_fallback_flashscore` e auto-documentată ca sursă secundară.
5. **Reversibilitate explicită**: în momentul în care providerul oficial de cote redevine funcțional pentru o ligă/competiție, `odds_history` capătă rânduri reale pentru acele fixture-uri, iar regula de citire (pct. 3) trece automat înapoi pe sursa primară — fără nicio migrare sau schimbare de cod necesară la acel moment. `odds_fallback_flashscore` nu se șterge automat (istoric păstrat, North Star #9), dar încetează să fie citit pentru fixture-urile care au acum acoperire primară.
6. Flashscore rămâne, la nivel de capability matrix (`FLASH_PROVIDER_CAPABILITIES`), un provider **auxiliar** — acest ADR nu îi schimbă statutul, nu îl promovează la "principal" pe nicio dimensiune, inclusiv cote.

## Consecințe

**Pozitive**:
- Predictorul capătă o cale de a avea cote acolo unde azi nu are, fără a compromite integritatea/imutabilitatea deja testată exhaustiv a `odds_history`.
- Trasabilitatea sursei rămâne completă — un cititor viitor al schemei vede imediat, din numele tabelei, că nu e sursa oficială.
- Reversibil fără migrare — revenirea providerului oficial "dezactivează" automat fallback-ul, la nivel de query, nu de schemă.

**Negative / riscuri acceptate**:
- Două tabele de cote în paralel = complexitate suplimentară de întreținere (un singur punct de citire, per pct. 3, limitează acest risc, dar nu-l elimină).
- `odds_fallback_flashscore` nu beneficiază de trigger-ul de imutabilitate opening/closing testat exhaustiv pentru `odds_history` (§7, `ODDS_PERSISTENCE_DESIGN.md`) — dacă acest ADR e aprobat, va necesita propriul contract de scriere (simplu, propunere: `INSERT ... ON CONFLICT (fixture_id, bookmaker) DO UPDATE`, fără distincție opening/closing — cotele Flashscore sunt fallback, nu sursa de CLV/market-drift, deci nuanța opening/closing nu e critică aici, doar valoarea cea mai recentă contează).
- Volumul real de cote recuperabile din Flashscore la scară (nu doar 10 meciuri, cum a confirmat POC-ul) rămâne neverificat — acest ADR autorizează arhitectura, nu garantează acoperirea.

## Alternative respinse

- **Scriere directă în `odds_history` cu un discriminator nou de sursă** (ex. extinde cheia unică la `(fixture_id, bookmaker, source)`) — respinsă: ar redeschide un document Frozen deja verdict "FROZEN" (§13, `ODDS_PERSISTENCE_DESIGN.md`), cu trigger de imutabilitate deja testat exhaustiv — risc mai mare decât beneficiul, pentru o nevoie explicit temporară.
- **Namespacing bookmaker prin nume** (ex. `"bet365 (flashscore)"`) — respinsă: ar corupe semantic coloana `bookmaker`, ar sparge orice cod existent care compară nume de bookmaker, fără avantaj real față de o tabelă separată.

---

## Addendum — corectare implementare §Decizie pct. 3 (2026-08-10)

**Nu e o schimbare de decizie** — implementarea nu respecta complet regula deja acceptată la §Decizie pct. 3 ("citește întâi `odds_history`... `odds_history`, când există, are prioritate necondiționată"). Cod real, până acum: `get_odds_fallback_for_missing_fixtures()` verifica doar EXISTENȚA unui rând în `odds_history`, ca să blocheze fallback-ul Flashscore — nicio funcție nu citea vreodată VALOAREA acelui rând. Rezultat, confirmat live prin audit de infrastructură (2026-08-10, la cererea proprietarului produsului, care raporta "eu nu am cote în aplicație, decât maxim 5% din meciuri"): meciuri cu un rând în `odds_history` (persistat de un job de sincronizare separat, de multe ori cu ore/o zi înainte de cererea curentă) rămâneau fără NICIO cotă afișată — nici cea persistată (niciodată citită), nici fallback-ul Flashscore (blocat de regula §3), de fiecare dată când fetch-ul live curent (`_attach_odds()`) nu găsea date proaspete pentru acel meci — situație frecventă în practică (0/113 meciuri verificate live aveau cote de la fetch-ul live curent, în instantaneul auditat).

**Corectare**: pas nou, `oracle_api._attach_primary_odds_from_history()` / `database.queries.get_primary_odds_from_history()`, rulat imediat după `_attach_odds()` și imediat înainte de fallback-ul Flashscore. Citește `closing_home/draw/away` din `odds_history` (cu fallback la `opening_*` dacă piața nu s-a închis încă), pentru fixture-urile încă fără cote după fetch-ul live. Necondiționat de niciun flag — `odds_history` e sursa primară/Frozen, nu un experiment (spre deosebire de fallback-ul Flashscore, care rămâne gatat de `flashscore_odds_fallback_enabled`). `get_odds_fallback_for_missing_fixtures()` (Flashscore) nu mai verifică ea însăși `odds_history` — primește deja doar fixture-urile rămase fără cote după ambii pași anteriori.

Ordinea de prioritate din §Decizie pct. 3 (primar necondiționat > Flashscore doar pentru gol real) rămâne exact aceeași — se schimbă doar faptul că „primar" înseamnă acum și „citit", nu doar „verificat ca existent". Impact măsurat pe instantaneul auditat: 31 din 113 meciuri (verificate) recuperează cote reale, deja persistate, fără nicio scriere nouă de date.
