# ODDS_INFRASTRUCTURE_DESIGN_2026-07-13.md — Football Oracle

**Status**: Arhitectură aprobată — zero cod încă. Companion la `ODDS_PERSISTENCE_DESIGN.md` (Frozen, ADR-005/006), nu îl înlocuiește și nu-l modifică. Acela guvernează captura **live** (The Odds API, deja activă — 8 rânduri azi). Acest document guvernează backfill-ul **istoric** (football-data.co.uk), ca extensie compatibilă, nu ca sistem paralel. Extinderea de schemă (Provenance, §3.1) și regimul temporal dual sunt formalizate în **ADR-010** — obligatoriu, nu opțional, conform deciziei arhitectului.

**Odds Infrastructure e primul modul al Knowledge Engine** — nu doar infrastructură pentru Value Betting. Cotele devin parte din memoria permanentă a Football Oracle. Analitice viitoare (Closing Line Value, Market Drift, Market Efficiency, Calibration vs Market, Market Surprise, Betting Bias, evoluția pieței înaintea meciului) **nu se implementează acum**, dar schema (§3.1, Provenance) e proiectată explicit ca ele să fie posibile mai târziu fără nicio modificare suplimentară de tabelă — doar interogări/view-uri noi peste date deja existente.

---

## 1. Sursele

- **football-data.co.uk**, ultimii 5 ani, acces prin Exa (web_fetch) pentru pagini text + oglindă GitHub pentru CSV brut — singura cale verificată funcțională în acest mediu (site-ul direct e blocat de politica de rețea a sesiunii, demonstrat în `FOOTBALL_DATA_CO_UK_AUDIT_2026-07-13.md`).
- **Competiții acoperite**: doar cele deja urmărite ȘI acoperite de sursă — Premier League, La Liga, Serie A, Bundesliga, Ligue 1, Romania SuperLiga (6/9 din `BOOTSTRAP_LEAGUES`). Champions League, Europa League, World Cup 2026 **rămân neacoperite** — sursa nu le oferă, nu e o limitare a acestui design.
- **Câmpuri folosite**: strict piața 1X2, pre-closing și closing, de la un set minim de surse — `B365H/D/A` + `B365CH/CD/CA` (Bet365, cea mai consistentă în timp) și `MaxH/D/A`+`MaxCH/CD/CA`, `AvgH/D/A`+`AvgCH/CD/CA` (consensul de piață, deja folosit conceptual de de-vig). **Pinnacle exclus explicit** — football-data.co.uk însuși a semnalat că din 23/07/2025 API-ul Pinnacle e nesigur, exclus din calculul de piață (deja documentat în audit).
- **Câmpuri ignorate**: toate statisticile de meci (șuturi/cornere/faulturi/cartonașe/arbitru — Knowledge Engine, P1/P3, gated separat, task #19); toate celelalte case de pariuri (acoperire inconsistentă); Over/Under, BTTS, Handicap Asiatic — **în afara scopului 1X2 deja înghețat prin ADR-006 §3**, nu se ating fără ADR nou dedicat; `Div/Date/Time/HomeTeam/AwayTeam/FTHG/FTAG/FTR` — redundante (deja avem rezultatul, mai proaspăt, în `match_history`), dar `FTHG/FTAG` se **citesc** intern ca semnal de verificare (§2), fără să se scrie nicăieri.

## 2. Schema de matching

- **Cheia de identificare**: `(kickoff_date, home_team normalizat, away_team normalizat, league canonic)` — folosind **exact** `mappings.normalize_team_name()`/`normalize_league_name()`, nicio a doua funcție de normalizare (regula deja scrisă în §5 din designul Frozen: „o singură funcție de rezoluție a identității, reutilizată, nu paralelizată").
- **Ținta matching-ului**: exclusiv rândurile `match_history` cu **numele complet de ligă** (`Premier League`, `La Liga`, ...) — niciodată codurile brute de Division (`E0`, `SP1`, ...). Acelea sunt artefacte Kaggle deja documentate ca duplicate; atașarea de cote pe ambele ar dubla stocarea fără motiv.
- **Verificare de încredere suplimentară, obligatorie**: scorul din CSV (`FTHG`/`FTAG`) trebuie să coincidă exact cu `match_history.actual_home_goals`/`actual_away_goals` al rândului candidat. Nume+dată+ligă potrivite dar scor diferit → **nepotrivire**, nu se scrie nimic.
- **Regula fail-closed**: zero potriviri, sau mai mult de o potrivire, sau scor neconcordant → rândul e **sărit complet**, logat cu motivul exact, niciodată forțat prin cea mai apropiată aproximare. Fixture_id-ul folosit la scriere e **întotdeauna** cel deja canonic din `match_history` — acest proces nu inventează niciun fixture_id nou și nu creează rânduri noi în `match_history`.

## 3. Writer-ul

Nu se construiește un mecanism nou de scriere — se **reutilizează** primitiva deja Frozen și testată live: `OddsPersistenceService._upsert()` → RPC `upsert_odds_snapshot` → `INSERT ... ON CONFLICT (fixture_id, bookmaker) DO UPDATE SET closing_*` (opening_* nu apare niciodată în clauza SET, prin construcție).

Pentru date istorice (opening și closing deja cunoscute, nu capturate în timp), secvența e **două apeluri** ale aceleiași primitive existente: (1) apel cu prețul de opening → INSERT, opening=closing=opening; (2) apel cu prețul de closing → UPDATE, doar `closing_*` se schimbă. Rezultat final identic cu ce ar produce fluxul live, fără nicio schimbare de schemă sau RPC.

Verificat împotriva celor 5 cerințe, prin moștenire directă de la contractul Frozen, nu prin cod nou:
- **Niciodată None explicit** — RPC-ul primește doar valori numerice validate (§2 din designul Frozen, deja aplicat).
- **Actualizare doar pe coloane lipsă** — `opening_*` scris o singură dată; imposibil de suprascris, la nivel de trigger SQL, nu doar disciplină de aplicație.
- **Idempotent** — a doua rulare pe aceleași date nu scrie nimic (deja garantat de `_upsert`, testat live).
- **Restart-safe** — fiecare `(fixture_id, bookmaker)` e o operațiune atomică independentă; o întrerupere lasă restul intact, reluarea reia exact de unde a rămas.
- **Nu poate suprascrie accidental** — protecție **dublă**: gardă la nivel de aplicație (validare înainte de apel) ȘI trigger `odds_history_immutability_guard` la nivel de bază de date, care blochează necondiționat orice `UPDATE` pe `opening_*` sau orice `DELETE`, indiferent de client. Mai puternic decât ce am construit pentru `match_history` (acolo protecția era doar la nivel de aplicație).

**Extensibilitate prin provider**: satisfăcută de schema existentă — `bookmaker` e discriminatorul, `UNIQUE(fixture_id, bookmaker)` există deja. O sursă viitoare (The Odds API pentru alt tip de cote, Pinnacle direct, orice altceva) intră ca rânduri noi cu alt `bookmaker`, fără nicio modificare structurală suplimentară a tabelei — dincolo de coloanele de proveniență din §3.1, care sunt deja parte a acestui design, nu o extindere ulterioară.

### 3.1 Provenance (obligatoriu, ADR-010)

Fiecare rând trebuie să răspundă nu doar „ce cotă e", ci „de unde provine". Patru coloane noi, aditive, imuabile după prima scriere (protejate de același trigger ca `opening_*`):

| Coloană | Exemplu (backfill istoric) | Exemplu (live, retroactiv) |
|---|---|---|
| `provider` | `football-data.co.uk` | `the-odds-api` |
| `import_type` | `historical_backfill` | `live_capture` |
| `import_version` | `OddsBackfill_v1` | `OddsPersistenceService_v1` |
| `imported_at` | momentul rulării backfill-ului | `opening_fetched_at` (aproximare, la completarea retroactivă) |

`provider` ≠ `bookmaker`: primul e sursa de date (de unde am citit NOI cota), al doilea e casa de pariuri reală (a cui e cota). Cele 8 rânduri live deja scrise se completează retroactiv, NULL-only, fără nicio suprascriere — detaliile complete în ADR-010.

**Notă de guvernanță**: acest writer operează sub un regim temporal diferit de §9 din designul Frozen (eligibilitate = kickoff viitor, gândită pentru fluxul live). Backfill-ul istoric scrie valori finale, cunoscute, o singură dată — nu „captează" o piață activă. Nu contrazice regula §9 (n-o modifică, n-o ocolește pentru fixture-uri viitoare). Formalizat prin **ADR-010** — obligatoriu, acoperă atât regimul temporal dual cât și extinderea de schemă din §3.1.

## 4. Integritatea

- **Import corect**: raport final cu `attempted/written/skipped_no_match/skipped_score_mismatch/errors` — exact pattern-ul deja folosit de `PersistenceResult` din serviciul live, reutilizat, nu reinventat.
- **Fără duplicate**: imposibil structural, nu doar testat — `UNIQUE(fixture_id, bookmaker)` există deja în schemă.
- **Fără meciuri asociate greșit**: verificare de scor (§2) aplicată la 100% din rândurile scrise; rata de nepotrivire (`skipped_no_match` + `skipped_score_mismatch`) raportată explicit, nu ascunsă într-un total agregat.
- **Writer-ul nu poate deteriora date existente**: demonstrat prin natura constrângerii — trigger-ul SQL deja Frozen, deja testat live (INSERT unic, opening imuabil, DELETE blocat) protejează indiferent de care client scrie. Nu necesită un test nou dedicat pentru asta — testul deja există și acoperă orice apelant.

## 5. Închiderea componentei — condiții exacte pentru „Odds Infrastructure v1.0 — CLOSED"

1. Toate fixture-urile eligibile (6 ligi acoperite × ultimii 5 ani, din `match_history`, nume canonic) au fost procesate — fiecare rezultă în `written`, `skipped_no_match` sau `skipped_score_mismatch`, nimic „netratat".
2. Zero duplicate (verificare SQL directă pe `odds_history`, deja imposibil structural, dar confirmat).
3. Rata de nepotrivire raportată explicit și explicabilă (nu doar un număr — motivele).
4. Idempotență și restart-safety demonstrate prin rulare dublă (același pattern folosit la ELO — a doua rulare nu scrie nimic).
5. Serviciul live (`odds_persistence_service.py`) confirmat neafectat — suita lui de teste rămâne verde, fără nicio modificare a codului lui.
6. Confirmat că `odds_history` continuă să primească meciuri noi prin fluxul live existent (Obiectivul 4 din Sprint) — nu doar din backfill.
7. Cele 4 coloane de proveniență (§3.1) populate 100% pe rândurile noi, plus completarea retroactivă a celor 8 rânduri live existente (ADR-010) — nicio scriere fără proveniență, de la primul rând.

---

**Nu conține cod încă.** Arhitectură aprobată de Arhitectul Principal, condiționată de integrarea Provenance (§3.1) și ADR-010 — ambele integrate. Implementarea poate începe.
