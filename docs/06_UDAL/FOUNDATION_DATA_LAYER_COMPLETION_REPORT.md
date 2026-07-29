# Foundation Data Layer — Raport de închidere oficială

**Status**: Punct oficial de închidere pentru ADR-044 (Flashscore Foundation Data Layer + Data Trust Layer). După acest raport, ADR-044 e considerat închis; etapa următoare a proiectului poate începe.

**Scriere live**: NEACTIVATĂ. `tos_reviewed=False` (`scraper_registry.py`), neatins pe tot parcursul acestei lucrări. Toate tabelele Foundation Data Layer există live în Supabase (`Prediction`, `gtlpyxzocacaqyompkwe`), cu RLS activ, dar cu **0 rânduri** — nicio scriere reală nu a avut loc încă, doar schema + codul + testele (contra fixture-urilor capturate în POC-uri anterioare) sunt gata.

**Documente companion**: `docs/00_GOVERNANCE/ADR-044-flashscore-foundation-data-layer.md` (decizia arhitecturală + 3 addendumuri), `docs/06_UDAL/FLASHSCORE_FIELD_MAPPING_MATRIX.md` (matricea completă câmp-cu-câmp), `docs/06_UDAL/FOUNDATION_DATA_LAYER_DELIVERABLES_REPORT.md` (raportul de livrabile intermediar).

---

## 1. Ce există acum în Supabase

### Schema (migrațiile 032, 035-039, toate aplicate live)

**Coloane noi pe `match_history`** (owner: `upsert_match_canonical`, COALESCE-only):
`attendance`, `capacity`, `home/away_goalkeeper_saves`, `actual_home_goals`, `actual_away_goals`, `home/away_ht_goals`, `season`.

**8 tabele noi**, toate cu RLS activ, verificate live (`list_tables`):

| Tabelă | Rol |
|---|---|
| `player_match_stats` | Roster + rating + poziție per jucător per meci |
| `match_events` | Timeline complet: goluri, penalty, cartonașe, schimbări (intrare+ieșire), VAR |
| `match_statistics_extended` | EAV — 26 categorii de statistici de meci fără coloană dedicată |
| `player_match_stats_extended` | EAV — 7 statistici avansate per jucător |
| `flashscore_match_context` | H2H + formă recentă, segmentate (3 categorii) |
| `flashscore_standings_snapshot` | Clasament curent per competiție |
| `flashscore_raw_extraction` | Stratul RAW al Data Trust Layer-ului — output brut, indiferent de validare |
| `flashscore_data_completeness` | Scor de completitudine per meci (7 flag-uri de tab + procent) |

**Coloană `season`** (TEXT, nullable) — pe `match_history` + toate cele 8 tabele de mai sus, populată STRICT dacă providerul o oferă explicit, niciodată dedusă calendaristic.

### Fluxul de scriere (Data Trust Layer, „nu există bypass")

```
Flashscore (HTML) → normalize_*() [pur] → RAW (întotdeauna) → VALIDATED → CANONICAL (doar dacă valid)
```

`persist_match_with_data_trust_layer()` e punctul de intrare oficial. Validare minimală pe cheia naturală (`udal_validation.validate_flat_identity`) — dacă eșuează, scrierea canonică e sărită explicit, dar RAW tot se scrie (dovadă completă, chiar și pentru meciuri respinse).

### Idempotență — verificată, nu presupusă

Testată explicit, parametrizat, 1/2/10 rulări succesive pe același fixture real: **0 duplicate**, id-uri stabile între rulări, pentru toate cele 8 tabele noi + `match_events` (21 evenimente reale, stabile).

---

## 2. Ce aduce Flashscore peste providerii API existenți

Provideriii API (API-Football, Soccer Football Info, ESPN, TheSportsDB, football-data.org) **rămân** responsabili pentru fixtures/rezultate/scoruri/status/sincronizare curentă — Flashscore nu-i înlocuiește (ADR-044, Decizie §1).

Ce adaugă Flashscore, azi neacoperit de niciun alt provider activ:

- **36 de categorii de statistici de meci** (10 cu coloană dedicată + 26 EAV) — xG, xGOT, posesie, șuturi, cornere, cartonașe, fouluri, duels, tackles, clearances, etc.
- **Timeline complet de evenimente cu minut** — goluri (cu assist), penalty, cartonașe (cu motiv), schimbări (intrare ȘI ieșire), VAR (cu textul deciziei) — 6 tipuri confirmate pe date reale.
- **Scor final și scor la pauză** — extrase direct, verificat pe 2 fixture-uri independente.
- **Rating și statistici avansate per jucător** (9 câmpuri) — sursă nouă, curată, care a deblocat exact ce fusese amânat în faza M0 (rating de jucător, fără disambiguare fiabilă în sursa veche).
- **Context H2H + formă recentă** — 15 întâlniri istorice per meci, segmentate corect (H2H general / formă acasă / formă oaspete).
- **Clasament curent per competiție** — snapshot, 10 coloane.
- **Cote 1X2 curente** (RAW) — fallback potențial pentru Predictor, cu limitările documentate explicit (§3).
- **Referee, stadion, capacitate, spectatori** — câmpuri care completează date lipsă la providerii existenți.
- **Data Completeness Score per meci** — infrastructură de observabilitate, nouă, nu exista înainte la niciun provider.

---

## 3. Ce rămâne pentru fazele viitoare

Nimic din secțiunea asta nu e ascuns sau neclasificat — vezi `FLASHSCORE_FIELD_MAPPING_MATRIX.md` pentru detaliul complet, câmp cu câmp (32 identificate, 21 implementate, 11 rămase, fiecare cu motiv exact).

### Parser limitation (3 câmpuri) — mecanism gata, așteaptă date reale
`own_goal`, `penalty_missed`, `second_yellow_card` — schema (migrația 039) le permite deja, mecanismul de clasificare e identic cu al celor 6 tipuri confirmate, dar niciunul nu a apărut încă în fixture-urile capturate. **Nu se ghicește selectorul** — se implementează la primul fixture real care conține unul din aceste evenimente.

### Schema gap (5 câmpuri) — decizie de produs, neluată încă
Scor doar-a-doua-repriză, breadcrumb țară, breadcrumb rundă, marcaje rol jucător (G/C), insigne de formă recentă la clasament. Toate necesită o coloană nouă — nu au fost adăugate unilateral, rămân la latitudinea proprietarului produsului.

### Cross-provider dependency (2 câmpuri) — necesită rezoluție de identitate
Liga canonică (breadcrumb → reconciliere cu `mappings.py`, ADR-001) și scrierea canonică a cotei (`odds_fallback_flashscore`, necesită `fixture_id` identic cu The Odds API — ADR-043 documentează asta ca task separat).

### Decizie ADR (1 câmp)
Mișcarea cotei (opening → curent) — ADR-043 a decis explicit că nu contează pentru un fallback, doar valoarea curentă.

### TODO documentat, nedecis — ownership `actual_home_goals`/`actual_away_goals`
ADR-044 Addendum 3: implementarea scrie scorul prin RPC-ul COALESCE-safe existent, dar întrebarea de ownership (Flashscore ca writer secundar autorizat vs. owner unic `sync_results.py`) rămâne deschisă explicit — **nu s-a schimbat nimic acum**, se decide împreună la începutul integrării Oracle.

### Season Cleanup — infrastructură DOAR, activare amânată explicit
`providers/flashscore/season_cleanup.py` implementează DOAR Discovery + Cleanup Report (dry-run) — `discover_seasons()` (pur) și `build_cleanup_dry_run_report()` (interoghează Supabase, raportează, nu șterge). **NU există Backup, Delete, Integrity Check, Final Report, cron** — confirmat direct în cod: `delete_executed` e mereu `False`, niciun modul de ștergere nu există. Activarea reală rămâne pentru momentul în care baza de date are suficiente sezoane reale — decizie viitoare, nu acum.

### Integrare Oracle/Predictor/ML — neînceput, deliberat
Toate tabelele de mai sus există, dar **niciun cod Oracle Engine/Predictor/ML nu citește din ele azi**. Orice integrare viitoare rămâne condiționată de:
- „Garanțiile obligatorii" din ADR-044 (date brute salvate ✅, validare funcțională ✅, tabele canonice populate corect ✅ pe fixture, rerun-uri fără duplicate ✅, niciun provider extern nu poate afecta direct modelele ✅ prin construcție);
- disciplina de ablație (CLAUDE.md, „Regulile ML" — niciun feature nou fără test măsurat);
- ML Activation Gate (`docs/00_GOVERNANCE/ML_ACTIVATION_GATE.md`) — blocat până la finalul Critical Path (M4) sau aprobare explicită separată.

---

## 4. Confirmare explicită: Oracle, Predictor și ML NU au fost modificate

Verificat, nu presupus:

- **`oracle_engine.py`** — netins pe tot parcursul acestei lucrări. `ml_blending_enabled=False` rămâne neschimbat (R-ARCH-REVIEW-01, din faza anterioară Critical Path).
- **`ml_predictor.py`** — netins.
- **`config.json`** — netins (dincolo de `ml_blending_enabled`, deja setat înainte de acest task).
- **Nicio coloană nouă a Foundation Data Layer nu e citită** de niciun modul de predicție/antrenare — verificabil prin grep: niciun `import` din `oracle_engine.py`/`ml_predictor.py` către `providers/flashscore/*`.
- **`tests/test_canonical_feature_ownership.py`** (garda AST pentru ADR-036) rămâne verde, neschimbată — singura zonă de atenție semnalată explicit e TODO-ul documentat din Addendum 3 (ownership `actual_*`), nedecis, nemodificat.

`pytest tests/` — 1779 teste verzi, aceleași 3 eșecuri preexistente, fără legătură cu acest task (`test_oracle_api_tsdb_per_league_gate.py`, documentat de mult).

---

## 5. Închidere

Toate cele 6 cerințe ale ultimei runde de corecții sunt îndeplinite:
1. Matricea de câmpuri conține o concluzie clară, cu numere exacte și clasificare strictă în 4 categorii.
2. ADR-044 declară explicit completitudinea — nimic nu lasă impresia unui parser incomplet.
3. Ownership-ul `actual_*` NU a fost schimbat — doar documentat ca TODO deschis.
4. Niciun selector de eveniment nu a fost inventat — `own_goal`/`penalty_missed`/`second_yellow_card` rămân documentate, nu ghicite.
5. Season Cleanup rămâne infrastructură pură — fără Backup/Delete/Cron.
6. Acest raport.

**ADR-044 e considerat închis odată cu acest document.**
