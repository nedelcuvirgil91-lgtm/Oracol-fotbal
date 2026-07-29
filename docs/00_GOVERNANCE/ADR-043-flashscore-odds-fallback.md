# ADR-043 — Flashscore ca sursă de fallback temporar pentru cote (Predictor)

**Status**: **PROPUS** — neaprobat, neimplementat, nicio migrare aplicată. Redactat ca parte a `R-SYNC-FLASH-01_DESIGN.md` §10 ("Direction Update"), la cererea explicită a proprietarului produsului: "verifică dacă noua direcție nu intră în conflict cu ADR-urile existente... propune cea mai bună arhitectură posibilă." Nu intră în vigoare până la aprobare separată, explicită.

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
