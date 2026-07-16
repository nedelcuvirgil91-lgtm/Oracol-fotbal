# ADR-023 — Canonical Live ELO Source (Variant C: post-match snapshot în `match_history`)

**Status**: Accepted
**Data**: 2026-07-16

## Context

Eliminarea `sync/calculate_elo.py` (audit code-first, `docs/03_ENGINE/ARCHITECTURE_AUDIT_2026-07-15.md`) a expus o discrepanță preexistentă, independentă de acea eliminare: antrenarea ML (`ml_predictor.py`, `MLPredictorEngine.train()`) folosește exclusiv `match_history.home_elo`/`away_elo`, scrise de `ELOTracker` (`sync/backfill_features.py`, formula MOV V2_damped, ADR-022) — dar servirea live (`oracle_engine._build_profile()`) obține ELO printr-o cale complet diferită, `oracle_api.get_elo_rating()` → scraping `eloratings.net` + `ELO_RATINGS_FALLBACK` (`mappings.py`), o sursă externă, categorială, fără MOV, calibrată pe echipe naționale.

Verificare cantitativă directă, pe producție: din 939 echipe distincte cu meciuri cu rezultat în `match_history`, doar **16** (1,7%) apar în `ELO_RATINGS_FALLBACK` — pentru restul de 98,3%, `elo_raw` e `None` la orice predicție live, indiferent dacă scraping-ul reușește sau nu. Formula de transformare (`compute_team_offdef_rating`, `feature_engine.py`) e deja identică pe ambele căi — singura diferență reală e sursa valorii ELO brute.

Analiza completă — comparație a patru variante de arhitectură (A: tabel separat, persistare la final; A′: tabel separat, persistare incrementală; C: coloane noi în `match_history`; D: derivare la citire, fără persistare nouă), șase runde de review adversarial (fiecare variantă atacată activ, inclusiv cea aleasă), un test de scară („100 milioane de meciuri"), un test „noul inginer senior", și un Execution Plan pe 9 faze — a fost condusă conversațional, cu Chief Architect. Nu a fost persistată ca documente separate; acest ADR e sinteza oficială, singura formă scrisă a deciziei.

## Decizie

**Se adoptă Variant C.** `match_history` primește două coloane noi, `home_elo_after`/`away_elo_after` — ratingul ELO al fiecărei echipe imediat după meciul respectiv, calculat de `ELOTracker.process_match()` (deja disponibil în memorie, neschimbat ca formulă) și scris în **același payload** deja folosit pentru `home_elo`/`away_elo`/restul feature-urilor derivate, prin mecanismul deja existent (`bulk_update_features()`, gating per-coloană, Regula #13). Servirea live citește aceste coloane printr-o funcție nouă de tip bulk-fetch + cache (`database/queries.py`), înlocuind `oracle_api.get_elo_rating()` în `oracle_engine._build_profile()`.

**Variante respinse, explicit, cu motiv**:
- **A** (tabel separat, persistare doar la finalul rulării) — dominată strict de A′; eșuează sub timeout GitHub Actions, scenariu demonstrat operațional, repetat, în acest proiect (3-4 rulări necesare la activarea MOV).
- **A′** (tabel separat, persistare incrementală) — validă tehnic, dar cost de scriere mai mare (mai multe apeluri Supabase, agravând exact riscul de timeout deja documentat) și o fereastră reală de neatomicitate între două tabele, fără beneficiu care să justifice costul la scara reală a proiectului azi.
- **D** (derivare la citire, zero coloană nouă) — respinsă cu dovadă din cod, nu din preferință: reconstrucția corectă necesită K-factor, care depinde de numărul de meciuri jucate de fiecare echipă înainte de meciul curent — informație **niciodată persistată** nicăieri în schema actuală (verificat exhaustiv, `FEATURE_COLUMNS`, `sync/backfill_features.py:88-108`). Singura reparație (persistarea acestei informații) anulează exact avantajul revendicat de D.

**Explicit out of scope, nu implementat preventiv** (consistent cu filosofia proiectului): Champion/Challenger pe formula ELO, tracking concurent multi-algoritm, formulă Glicko, formulă SPI, etichetă `algorithm_version` pe schema nouă. Niciuna dintre acestea nu are o nevoie activă azi (Promotion Engine „Not Implemented" — vezi „Current Implementation Status — Learning Core" mai sus în acest document) — se adaugă printr-un ADR nou, dedicat, dacă/când devine necesar.

## Guvernanța de execuție (specifică acestui ADR)

Implementarea urmează un Execution Plan pe 9 faze (Phase 0 — ADR → Phase 8 — Legacy Cleanup), sub următoarele reguli permanente, stabilite explicit pentru acest ADR:

- **Architecture Freeze** — nicio schimbare de arhitectură în timpul implementării; doar bugfix/clarificări/optimizări locale/refactorizări fără schimbare de arhitectură. Orice schimbare arhitecturală reală necesită ADR nou.
- **Phase Gates** — fiecare fază se oprește explicit („STOP") și așteaptă aprobarea proprietarului înainte de faza următoare.
- **One Phase per Instruction** — o singură fază implementată per instrucțiune explicită, niciodată „Phase 0 → Phase 8" într-un singur pas.
- **Owner Approval Gates** — rezultatul fiecărei faze (fișiere atinse, diff real, verificări) e prezentat înainte de a cere semnalul pentru faza următoare.
- **No Hidden Refactors** — se modifică exclusiv fișierele declarate în planul fazei curente; orice fișier neprevăzut necesar → implementarea se oprește, se raportează, se cere aprobare.
- **ADR Supremacy** — orice contradicție descoperită între cod/documentație veche/presupuneri anterioare și acest ADR se rezolvă în favoarea ADR-ului aprobat; nu se adaptează implementarea la sursa veche fără aprobare explicită.

## Consecințe

1. **Schimbare de contract de date** — `match_history` capătă 2 coloane noi, nullable, aditive (Phase 1). `home_elo`/`away_elo` (pre-meci) rămân complet neschimbate, sursă exclusivă pentru antrenarea ML.
2. **Producție NU e atinsă automat de acest ADR** — identic disciplinei ADR-022: activarea reală (Phase 6, comutarea `oracle_engine.py`) e o decizie separată, ulterioară, cu aprobare proprie, nu implicită prin acceptarea acestui document.
3. **Live serving neafectat până la Phase 6** — până atunci, `oracle_engine._build_profile()` continuă să citească ELO din `oracle_api.get_elo_rating()`, neschimbat. `CLAUDE.md` (Knowledge Map) primește o notă de tranziție, nu o rescriere a dependenței curente (care rămâne factual corectă până la Phase 6). Similar, nota din `feature_engine.py` (linia care descrie separarea de responsabilități live/backfill) rămâne adevărată azi — se adnotează cu referință la acest ADR, nu se declară falsă înainte de a fi efectiv schimbată.
4. **Riscuri reziduale, acceptate explicit, netratate ca blocante**: inserție istorică întârziată (rânduri deja scrise rămân „înghețate" — rezolvat prin procedură operațională Reset+Replay, Phase 7, nu prin arhitectură); zero observabilitate/staleness detection (propusă, Phase 7); lipsă `concurrency:` guard pe `daily.yml`/`backfill.yml` (Phase 7); al treilea context ELO, separat, per-ligă, în `sync/bootstrap_league_learning.py` — neatins de acest ADR, rămâne inconsistență reziduală documentată, nu rezolvată.
5. **Cleanup-ul sursei vechi** (`oracle_api._fetch_elo_ratings()`/`get_elo_rating()`, `ELO_RATINGS_FALLBACK` dacă rămâne neapelat, funcțiile deja moarte din `database/queries.py`) se face abia în Phase 8, după Operational Hardening (Phase 7) — ordine explicit stabilită, nu implicită.

## Referințe

- ADR-022 — ELO Margin of Victory (MOV), V2_damped — formula de bază pentru `ELOTracker`, neschimbată de acest ADR.
- `docs/03_ENGINE/ARCHITECTURE_AUDIT_2026-07-15.md` — descoperirea inițială a discrepanței train/inference, post-eliminare `calculate_elo.py`.
- Execution Plan (9 faze, Phase 0 — ADR → Phase 8 — Legacy Cleanup) — document de execuție aprobat, conversațional, referință operațională pentru fiecare fază ulterioară.
