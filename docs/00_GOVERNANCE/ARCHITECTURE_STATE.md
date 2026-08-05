# ARCHITECTURE_STATE.md — Sursa unică de adevăr a stării proiectului

**Tip**: document viu, actualizat la fiecare etapă majoră (merge, activare de flag, închidere de ADR) — NU un ADR, NU o specificație înghețată. Scopul lui: să răspundă instant, fără să refacem o analiză, la întrebările „ce e implementat, ce e pe `main`, ce e doar pe branch, ce rulează live, ce e activat prin flag-uri, ce mai lipsește înainte de merge".

**Regulă de întreținere**: orice sesiune care merge-uiește cod, schimbă un flag de producție, sau închide un ADR **actualizează acest document în același commit** (sau imediat următor). Un „Architecture State Report" (verificat, la începutul fiecărei etape noi — vezi convenția de mai jos) citește de aici; dacă acest document e stale, se corectează întâi el, nu se lucrează pe baza memoriei conversației.

**Ultima verificare completă**: 2026-07-28, prin inspecție directă `git`/Supabase (nu presupusă) — vezi metodologia §5. **Corecție majoră față de versiunea anterioară (verificată 2026-07-22)**: acel document afirma că tot lanțul ADR-037 R1-R3 era „doar pe branch, nemerge-uit" — verificat direct azi (`git show origin/main:learning_core/champion_guardian.py` etc.), **merge-ul s-a produs între timp**. Secțiunile 1-5 de mai jos sunt rescrise complet pe baza stării reale de azi, nu corectate punctual.

**Actualizare punctuală, 2026-08-03**: `main` HEAD = `30c20da` (§1) — fast-forward al `claude/continua-faza-1-adr5-o52jat` după aprobarea Pasului 1 din EPIC „ML Activation & Oracle Evolution" (`docs/00_GOVERNANCE/ML_ACTIVATION_IMPLEMENTATION_PLAN.md`). De acum, fiecare pas aprobat din acel plan merge-uiește imediat pe `main` (vezi nota din §1) — acest document se actualizează la fiecare astfel de merge, nu doar la etapele majore ADR-037/Flashscore de mai jos.

**Actualizare punctuală, 2026-08-04**: `main` HEAD = `cd5d45e` (§1) — Pasul 10a EPIC „ML Activation & Oracle Evolution" ÎNCHIS: ADR-049 (calibrare post-hoc ML, Temperature Scaling) implementat parțial — antrenare, persistare artefact de calibrare, aplicare la predicția Challenger shadow. Vezi §3.1 pentru detalii și pentru ce rămâne (Pasul 10b, Champion serving live).

**Actualizare punctuală, 2026-08-04 (2)**: `main` HEAD = `e5d5606` (§1) — Pasul 10b EPIC „ML Activation & Oracle Evolution" ÎNCHIS: ADR-049 complet implementat — wiring de servire live prin `champion_loader.py`/`oracle_engine.py`. Champion-ul live servește azi probabilități calibrate ori de câte ori artefactul de calibrare există pentru `training_run_id`-ul activ. Vezi §3.1 (actualizat) pentru detalii.

**Actualizare punctuală, 2026-08-04 (3)**: Pasul 11 EPIC „ML Activation & Oracle Evolution" ÎNCHIS — validare experimentală (nu arhitectură): re-rulare a benchmark-ului Etapa 3 pe date live curente (1500 meciuri, 2025-08-23→2026-08-03), comparație perechi ML necalibrat vs. calibrat pe aceleași fold-uri/margini. Toate cele 5 criterii de succes prestabilite TREC — accuracy identică (invariant `argmax` confirmat empiric), log-loss/Brier/ECE îmbunătățite substanțial, overhead runtime +1.81% (neglijabil). Raport complet: `docs/00_GOVERNANCE/ETAPA3_RERUN_AFTER_ADR049.md`. Tooling committed, reutilizabil: `scripts/rerun_etapa3_benchmark.py`. `docs/00_GOVERNANCE/ORACLE_VS_ML_REPORT.md` (Etapa 3 originală) rămâne complet neatins — document istoric, imuabil; trimiterea către raportul nou se face exclusiv de aici, niciodată din interiorul raportului original.

**Actualizare punctuală, 2026-08-04 (4)**: ADR-043 (fallback Flashscore de cote) — corectează golul din §0.1 de mai jos, deja depășit înainte de această sesiune ("scrierea canonică... rămâne deliberat neimplementată"). Stare reală, verificată direct: scrierea (`providers/flashscore/pre_match_odds.py`, `sync/sync_pre_match_odds.py`, `.github/workflows/sync_pre_match_odds.yml`, rezolvare `fixture_id` cross-provider prin `mappings.match_key()`) e pe `main` din `0a44af0`. Pe `claude/continua-faza-1-adr5-o52jat`, NEMERGE-UITE încă pe `main`: (a) commit `714a0bb` — robustizarea scrierii (izolare per-ligă la eroare, oprire timpurie pe hub-ul cronologic, marjă de siguranță de fus orar); (b) regula de citire pentru Predictor (ADR-043 §Decizie pct. 3) — funcție nouă `database.queries.get_odds_fallback_for_missing_fixtures()` (întâi `odds_history`, fallback DOAR pe fixture-uri complet absente din primar), cablată printr-o funcție nouă separată `oracle_api.FootballOracleAPI._attach_flashscore_odds_fallback()`, apelată printr-o singură linie adăugată în `get_matches_for_week()` imediat după `_attach_odds()` (neatinsă). Ambele căi (scriere manuală prin workflow, citire prin flag) rămân implicit OPRITE (North Star #3): scrierea e `workflow_dispatch` manual, necablată în orchestrarea automată zilnică; citirea e gatată de `flashscore_odds_fallback_enabled` (`flashscore_odds_fallback_config.py`), niciodată activat implicit.

---

## 0. Critical Path oficial curent (2026-07-29)

Prioritatea de dezvoltare a întregului proiect, declarată oficial: `M0 → M1 → M2 → M3 → M4` — provider Flashscore funcțional, până la primul Night Sync complet. Detalii, analiza de dependențe, ce s-a amânat (nu abandonat): `docs/06_UDAL/R-SYNC-FLASH-01_DESIGN.md` (secțiunea "CRITICAL PATH OFICIAL" + §15). Consecință directă: niciun task nou privind Predictor/ML/Blending/Confidence nu începe înainte de M4 fără aprobare explicită separată — `docs/00_GOVERNANCE/ML_ACTIVATION_GATE.md`.

### 0.1 Foundation Data Layer + Data Trust Layer (ADR-044, 2026-07-29)

Scope-ul M0 s-a extins oficial (decizie Product Owner) de la statistici de bază la un **Foundation Data Layer** complet — vezi `docs/00_GOVERNANCE/ADR-044-flashscore-foundation-data-layer.md`. **Implementat, testat, NEMERGE-UIT pe `main`** (pe branch, cod complet + teste, `tos_reviewed=False` neatins, nicio scriere live):

- Schema: migrațiile 035 (5 tabele noi + `attendance`/`capacity`), 036 (fix gol RPC — `goalkeeper_saves`/`attendance`/`capacity` nu erau scrise de `upsert_match_canonical`), 037 (`flashscore_data_completeness`), 038 (coloana `season` pe `match_history` + toate cele 7 tabele FDL) — toate aplicate live, `Prediction`.
- Persist layer complet, idempotent (verificat 1/2/10 rulări): `providers/flashscore/persistence.py`, extensii `database/queries.py`.
- Data Trust Layer (RAW → VALIDATED → CANONICAL) funcțional: `persist_match_with_data_trust_layer()`, `udal_validation.validate_flat_identity()`.
- **Odds** (`normalize_odds()`) — gol închis, tab confirmat în POC, extras în stratul RAW. Scrierea canonică în `odds_fallback_flashscore` (ADR-043) — **implementată** (vezi nota punctuală 2026-08-04 (4) de mai sus pentru starea exactă branch vs. `main`), inclusiv rezolvarea `fixture_id` cross-provider prin `mappings.match_key()`.
- **Data Completeness Score** (`flashscore_data_completeness`, migrația 037) — calculat și scris per meci, **neconsumat de Oracle Engine azi** (regulă 7, TASK APROBAT M1).
- **Model de sezon** (`season`, migrația 038) — DOAR dacă providerul îl oferă explicit, niciodată dedus din reguli calendaristice; Flashscore nu îl expune robust azi (verificat pe fixture) — coloana există, pregătită pentru ponderare Oracle/ML pe sezon (neimplementată).
- **Season Cleanup** (`providers/flashscore/season_cleanup.py`) — DOAR Discovery + Cleanup Report (dry-run), `delete_executed` mereu `False`. Scope explicit restrâns la tabelele Foundation Data Layer — NU `match_history`/`match_events`/`player_match_stats` de bază, NU `odds_history` (Frozen). Ștergerea reală rămâne neimplementată, viitoare, cu propriul flag/aprobare.
- Oracle Engine/ML rămân neatinse — niciun consumator nu citește încă din tabelele noi (secțiunea 5, ADR-044).
- Următorul pas pe Critical Path rămâne M1 (primul meci descoperit live) — Foundation Data Layer pregătește DESTINAȚIA scrierii, nu înlocuiește pașii M1-M4.

---

## 1. Topologia branch-urilor (verificat direct, `git`, 2026-08-03)

| | |
|---|---|
| Branch default (GitHub Actions rulează pe el) | `main` (verificat: `git remote show origin` → `HEAD branch: main`) |
| `main` HEAD | `fb188a7` — fast-forward de pe `claude/continua-faza-1-adr5-o52jat`, 2026-08-04. Lanț de 6 commit-uri de la `e5d5606`: (1) `0a44af0`/`714a0bb` — ADR-043 scriere (Flashscore pre-match odds, discovery săptămânal + fallback cote, robustizare izolare per-ligă/oprire timpurie/marjă fus orar); (2) `5b4cd09` — ADR-043 citire (regulă `odds_history`-întâi cablată în `get_matches_for_week()` prin funcție nouă separată, flag `flashscore_odds_fallback_enabled`); (3) `4a7c989` — automatizare cron propriu (2x/zi, separat deliberat de night_sync/live_sync) + flag activat live; (4) `a040c52`/`fb188a7` — 4 ligi noi (Primeira Liga, Eredivisie, Super Lig, HNL) înregistrate cu paritate completă (provider_ids verificați live, `LEAGUE_BASELINES` din date reale sezon 2024-25, `league_weights` explicit, `FLASHSCORE_TRACKED_COMPETITIONS`, UI, **`model_weights` live în Supabase actualizat aditiv** — fără asta codul ar fi fost inert, `load_weights()` citește rândul Supabase integral, nu-l combină cu `DEFAULT_WEIGHTS`). `pytest tests/` — 2118 passed, 2 skipped. Rămas deliberat neatins: `BOOTSTRAP_LEAGUES` (replay de calibrare din istoric real — cele 4 ligi noi nu au încă niciun meci în `match_history`, adăugarea ar fi un no-op fără sens azi, nu o omisiune).

| `main` HEAD (istoric) | `e5d5606` — fast-forward de pe `claude/continua-faza-1-adr5-o52jat`, `git push origin main`, 2026-08-04 (**Pasul 10b EPIC ML Activation, ÎNCHIS** — ADR-049 complet implementat: wiring pur de servire live, fără nicio schimbare de algoritm/storage/politică de promovare. `ChampionLoadResult` capătă câmpul `temperature`; `champion_loader.load_champion_or_none()` încarcă calibrarea prin `calibration_artifact_storage.load_calibration_artifact()` DUPĂ ce Champion-ul e deja confirmat utilizabil (după proba `predict_proba`, deci după toate cele 6 condiții din `RUNTIME_CONTRACT.md`, neatins) — calibrarea nu participă la decizia de utilizabilitate, degradare grațioasă la `None` dacă lipsește. `oracle_engine._resolve_champion()`: o singură linie nouă, `temperature=result.temperature` propagat la `seed_from_champion(...)` — parametru existent din Pasul 10a, acum apelat prima dată cu valoare reală. Niciun cod nou în `ml_predictor.py` (calea calibrată era deja implementată, doar neapelată live). Blast radius exact cum era în Implementation Plan 10b: `ml_predictor.py`, `calibration_artifact_storage.py`, `model_artifact_storage.py`, `continuous_learning.py`, `challenger_shadow.py`, `challenger_manager.py`, `training_runner.py`, `promotion_service.py` — neatinse. Vezi §3.1 (actualizat) pentru detalii complete. `pytest tests/` — 2014 passed, 2 skipped (aceleași 3 eșecuri preexistente în `test_oracle_api_tsdb_per_league_gate.py`, neatinse) |
| Branch de lucru curent | `claude/continua-faza-1-adr5-o52jat` |
| Commit-uri branch înaintea lui `main` | 0 (fast-forward complet — branch și `main` identice după merge) |
| Commit-uri `main` înaintea branch-ului | 0 |
| Ultima migrare pe `main` | `029_freelf_h2h_snapshot` (include 014/015, verificat `git show origin/main:database/migrations/01{4,5}_*.sql`) — neatinsă de commit-urile EPIC „ML Activation & Oracle Evolution" (doar documentație + comentariu, zero schimbare de schemă) |

**Strategie de merge (EPIC „ML Activation & Oracle Evolution", din Pasul 2 încolo)**: după fiecare pas aprobat individual, merge fast-forward imediat pe `main` (nu se acumulează mai multe pași pe branch înainte de merge) + actualizare acestui document cu noul SHA. Scop: `main` reflectă mereu exact ce a fost aprobat, fără fereastră în care branch-ul de lucru divergă vizibil de starea aprobată.

## 2. Ce e pe `main` azi (implementat, live, nu doar cod) — ADR-037 MERGE-UIT

Tot lanțul R1 (Rollback Engine) + R2 (Champion Guardian) + R3 (Orchestrare, Faza D + Faza C extinsă) e confirmat pe `main` (`git show origin/main:<fișier>`, nu presupus):

| Componentă | Fișiere | Pe `main`? |
|---|---|---|
| Rollback Engine (R1) | `learning_core/rollback_service.py`, `database/migrations/014_rollback.sql` | ✅ DA |
| Champion Guardian (R2) | `learning_core/champion_guardian.py`, `database/migrations/015_champion_health.sql` | ✅ DA |
| Orchestrare (R3, Faza D + Faza C extinsă) | `learning_core/continuous_learning.py` (4 faze — `_phase_d_champion_health` prezentă, `is_champion_guardian_enabled()` prezentă) | ✅ DA |
| Flag-uri dedicate (R3.7) | `champion_guardian_enabled`, `champion_guardian_proposals_enabled` (cod care le citește) | ✅ DA (codul citește; valorile în `model_config` rămân `False`, vezi §4) |

Migrările 014/015 sunt aplicate pe Supabase live de mult (`champion_health_evaluations` există, schema verificată coloană-cu-coloană împotriva `record_champion_health_evaluation()` de pe `main`, 2026-07-28).

## 3. Learning Core — flag-uri, două familii independente

**ADR-030 (Fazele A/B/C — training, monitorizare challenger, promovare)**:
- `learning_core_enabled = true` — pre-existent, activ.

**ADR-037 (Faza D — Champion Guardian)**, independent de `learning_core_enabled`:
- `champion_guardian_enabled` = **`False`** (cheie absentă din `model_config`, verificat live 2026-07-28) — Faza D nu rulează încă, deși codul e pe `main`. Etapa 2 din `ADR037_DEPLOYMENT_PLAN.md` (activare monitorizare read-only) rămâne o decizie deliberată, neexecutată — nu un blocaj de cod.
- `champion_guardian_proposals_enabled` = **`False`** — neatins, Etapa 4.

**ADR-017 (Challenger Shadow Logging)**, independent de ambele de mai sus:
- `challenger_shadow_logging_enabled` = **`True`** — **activat 2026-07-28** (Sprint 3, audit complet). Verificat live: `oracle_engine._log_challenger_shadow()` scrie exclusiv în `shadow_predictions`, nu modifică predicția servită, nu atinge `model_champions`/`weights.json` (before/after Supabase confirmat: `model_champions`/`challengers`/`model_weights` neschimbate). Suita `test_challenger_shadow_logging.py` + `test_challenger_shadow_adapter.py` (15/15 verde) confirmă comportamentul.

**ADR-050 (Pasul 13/14 — extensia Challenger Framework pentru algoritmi compuși, ex. Blend)**, independent de flag-ul de mai sus:
- `blend_challenger_shadow_logging_enabled` = **`True`** — **activat 2026-08-04** (Pasul 14, `docs/00_GOVERNANCE/PASUL14_ACTIVATION_REPORT.md`). Primul Challenger `blend_v1` antrenat și creat (`training_run_id=8ac89c70-8727-459f-aa42-08a2edd16431`, `samples_used=49983`, stare `EVALUATING`) prin `continuous_learning.yml` (pipeline-ul generic ADR-030, zero cod nou). Shadow logging verificat cu date reale, nu doar structural: 3 meciuri reale probate prin `scripts/shadow_probe.py` (utilitar operațional permanent, `docs/00_GOVERNANCE/SHADOW_PROBE_OPERATIONAL_GUIDE.md`) au produs 6 rânduri confirmate în `shadow_predictions` (`blend_v1`, treatment+control). Invariant Champion live neschimbat confirmat live, de două ori (log-ul probei + query SQL independent): `model_champions` pentru `xgboost_v1/all` rămâne `0` rânduri, identic înainte/după. `challenger_shadow_logging_enabled` (xgboost_v1) rămâne complet neatins — verificat prin gardă structurală AST (`tests/test_blend_challenger_shadow_logging.py`). Flag-ul rămâne activ permanent (decizie explicită a proprietarului produsului) — shadow-ul acumulează acum date organice din trafic real, pregătind evaluarea statistică (Pasul 14 viitor — „Evaluare shadow → decizie de promovare", încă neînceput).

### 3.1 Calibrare post-hoc ML (ADR-049) — Pasul 10a/10b

**ADR-049 (ACCEPTED)**: decizia de a corecta supraîncrederea sistematică a modelului ML (diagnosticată empiric, `ORACLE_VS_ML_REPORT.md` §3.2 — gap de 24.3pp între încredere raportată și acuratețe reală, binul `[0.70, 1.01)`) prin Temperature Scaling, ales față de Platt Scaling/Isotonic Regression pe baza tiparului diagnosticat, cerinței minime de date și proprietății de a păstra `argmax` neschimbat.

Scope-ul complet a fost împărțit deliberat în două sub-pași, cu granițe de responsabilitate distincte (decizie confirmată explicit de Product Owner înainte de Implementation Plan):

- **Step 10a: ✅ COMPLETED** (`main` @ `cd5d45e`, 2026-08-04) — antrenare (`ml_predictor._fit_temperature()`), persistare (`learning_core/calibration_artifact_storage.py`, artefact separat de model), integrare în fluxul Challenger: persistarea calibrării e gating la crearea Challenger-ului (`continuous_learning.py`, extensie INV-1/ADR-048), aplicarea ei la predicția shadow e degradare grațioasă (`challenger_shadow.py`). Temperature Scaling e disponibil azi pentru orice Challenger nou creat.
- **Step 10b: ✅ COMPLETED** (`main` @ `e5d5606`, 2026-08-04) — wiring-ul de servire live: `champion_loader.py` (`ChampionLoadResult.temperature`, încărcat DUPĂ confirmarea utilizabilității Champion-ului) + `oracle_engine.py` (`_resolve_champion()` propagă `temperature` la `seed_from_champion(...)`). **Champion-ul live servește azi probabilități calibrate** ori de câte ori artefactul de calibrare există pentru `training_run_id`-ul activ — degradare grațioasă (probabilități brute) dacă lipsește, exact ca înainte de acest pas. `docs/04_LEARNING_CORE/RUNTIME_CONTRACT.md` (Frozen) confirmat neatins — calibrarea nu a devenit o a 7-a condiție de utilizabilitate, exact cum s-a decis înainte de Pasul 10a.

ADR-049 e acum **complet implementat**, de la antrenare până la servire live. Fișiere confirmate neatinse pe tot parcursul 10a+10b (`git diff --stat`, gol): `promotion_service.py`, `training_runner.py`, `challenger_manager.py`, `model_artifact_storage.py`, `RUNTIME_CONTRACT.md`.

### 3.2 Blend Engine (`blend_engine.py`) — stare tehnică curentă (ACTUALIZAT — „dualitatea Blend" închisă)

**[ACTUALIZAT]** ADR-051 §6 identifica, la momentul acceptării, o „dualitate Blend" ca întrebare deschisă. Proprietarul produsului a închis explicit acea întrebare (decizie arhitecturală finală, nu mai e subiect de ADR viitor — vezi istoricul deciziei): rămân azi **două** mecanisme, cu roluri distincte, fără suprapunere:

1. **`blend_v1` Challenger** (ADR-050, Pasul 13/14, `learning_core/blend_challenger_shadow.py`) — shadow-only, parte din Learning Core, cu propriul ciclu de antrenare/evaluare/promovare prin Challenger Framework. Aparține ciclului de antrenare/evaluare, nu trebuie confundat cu motorul Blend servit în producție.
2. **`blend_engine.py`** (ADR-051 §2.3) — **singurul Blend din runtime, motorul Blend oficial**. Modul pur, fără I/O, fără antrenare (`BlendEngine`/`BlendConfig`/`EngineOutput`), instanțiat în `oracle_engine.py` (`self.blend`), afișare UI gatată de `blend_engine_display_enabled` (implicit `False`), populează `MatchPrediction.blend_engine_prediction`, izolat de `raw_predictions`/ADR-031 și de `shadow_predictions`/ADR-033. **De la ADR-052**: consumă Oracle ȘI ML (al doilea `EngineOutput`, adăugat în `_get_blend_engine_prediction()` dacă `pred.ml_engine_prediction` e disponibil) — nu mai e o medie cu un singur termen. Zero coupling verificat static (`tests/test_blend_engine.py`) cu `learning_core.*`/`oracle_engine`-ul intern/mecanismul de mai sus.

**Blend legacy inline** (fostul mecanism #1, gatat de `ml_blending_enabled`) a fost **eliminat complet** — nu mai există în cod (`oracle_engine.py`), nu mai există în `model_config` live (`ml_blending_enabled`/`ml_blend_weight`, șterse). `blend_predictions()` (funcția partajată, `ml_predictor.py`) rămâne — folosită azi exclusiv de `blend_v1` Challenger de mai sus; call site-ul ei din `explainability.py` (treapta „Model ML" a cascadei de explicații) a fost eliminat la același pas — cascada explică azi exclusiv Oracle, care rămâne mereu pur (nu mai există blend legacy in-place care să-i dilueze probabilitatea).

## 4. Ce rulează efectiv în producție azi (verificat live)

| Workflow | Cron | Cod executat (de pe `main`) | Gated de |
|---|---|---|---|
| `daily.yml` | zilnic 03:00 UTC | `sync/run_daily.py` — neatins de ADR-037 | — |
| `continuous_learning.yml` | **`workflow_dispatch` only** (corectat 2026-08-03, EPIC ML Activation Pasul 5 — secțiunea anterioară afirma `0 6 * * *`, depășită; cron-ul propriu a fost eliminat, consolidat în `night_sync.yml`, vezi rândul de mai jos) | `continuous_learning.run_cycle()` — 4 faze (A/B/D/C), Faza D gatată separat | `learning_core_enabled` (A/B/C), `champion_guardian_enabled` (D) |
| `night_sync.yml` | zilnic 03:00 UTC | Etapa 8 („ML Refresh") apelează `continuous_learning.run_cycle()` — cadența reală de producție pentru Learning Core | Aceleași flag-uri ca rândul de mai sus |
| `consensus_validation.yml` | `0 9 * * *` | `run_consensus_validation.py` | `consensus_validation_enabled` |
| `validation_analysis.yml` (ADR-052 §2.4) | zilnic `0 10 * * *` + săptămânal (luni) `15 10 * * 1` | `run_validation_analysis.py --cadence daily\|weekly` | `validation_analysis_enabled` (implicit `False`) |

**Stare canonică relevantă** (verificat live, 2026-07-28): `model_champions` — 4 rânduri, toate `gate_validation_test` (fixturi R1.8, niciun campion real `production_champion`/`xgboost_v1`); `challengers` — 5 rânduri, toate `gate_validation_test`, toate în stare terminală/test, zero challenger real activ; `decision_feed` = 0; `champion_health_evaluations` = 0; `shadow_predictions` = 0 (infrastructură activată azi, în așteptare de trafic real + un challenger real activ — vezi §3); `recalibration_log` = 0 (`auto_recalibration_enabled=False`, deliberat, neatins azi).

## 5. Ce mai rămâne (nu „înainte de merge" — merge-ul s-a închis; rămâne activarea graduală)

1. ~~Merge R1-R3 pe `main`~~ — **DONE**, confirmat 2026-07-28.
2. **Activare `champion_guardian_enabled` (Etapa 2, monitorizare read-only)** — decizie deliberată, neexecutată; cod verificat safe/reversibil, în așteptarea unui Champion real de evaluat.
3. **Feedback Loop end-to-end cu date reale** (predicție → rezultat real → shadow → evaluare → promovare) — blocat azi de lipsa traficului real de utilizator (`total_predictions=37`, `closed_loop_rows=0`), nu de vreun cod nescris.
4. **Verificare proaspătă a `model_champions`/`challengers`** înainte de orice activare suplimentară de flag — Fazele A/B rulează zilnic, starea se poate schimba.

## 6. Metodologia de verificare (ce înseamnă „verificat", nu „presupus", aici)

- **Topologie branch**: `git remote show origin`, `git log --oneline branch..main` / `main..branch`, `git cat-file -e <branch>:<fișier>`.
- **Producție live**: `mcp__Supabase__execute_sql` cu `SELECT`, strict read-only, pe proiectul `Prediction` (`gtlpyxzocacaqyompkwe`).
- **Cod pe `main` vs. branch**: `git show <branch>:<fișier>`, niciodată presupus din memoria conversației.
- **Când se re-verifică**: la orice merge, la orice schimbare de flag în producție, la orice închidere de etapă/ADR, sau când a trecut suficient timp încât starea live s-ar putea fi schimbat (Fazele A/B rulează zilnic).

---

## 7. Oracle Engine — ponderi per-ligă inerte (EPIC „ML Activation & Oracle Evolution", verificat 2026-08-03)

`feature_engine.resolve_league_weights()` face blend între ponderile globale și cele per-ligă din `model_weights`, ponderat de `sample_count` (saturează la `sample_count=5`). **Verificat live, 2026-08-03**: `sample_count = 0` pentru toate cele 11 ligi, fără excepție → `alpha = 0` mereu → funcția întoarce azi **100% ponderile globale**, niciodată cele per-ligă, indiferent de valorile diferite prezente în `league_weights` (ex. Bundesliga are `base_weight`/`form_weight`/`home_advantage` proprii, dar neaplicate). **Notă (Pasul 7, ADR-047)**: cheia era `dna_weight` la verificarea inițială de mai sus — redenumită `base_weight` ulterior, în aceeași sesiune, aceleași valori.

**Cauza**: `sample_count` se incrementează doar prin `recalibration.py`, apelat din `sync/sync_results.py`, gatat de `auto_recalibration_enabled` — cheie absentă din `model_config` azi, deci cade pe default `False` (consistent cu `recalibration_log = 0`, §4 de mai sus).

**Nu e un bug** — flag oprit implicit, conform North Star #3 — dar un mecanism prezent în cod și în date, complet inert în formula servită. Documentat integral în `docs/00_GOVERNANCE/ORACLE_ENGINE_AUDIT.md` §4.3 și tratat explicit în `docs/00_GOVERNANCE/ML_ACTIVATION_IMPLEMENTATION_PLAN.md` §2.4/§6.2 (pasul 1: documentare, fără activare — decizia de a activa `auto_recalibration_enabled` rămâne separată, neluată în acest EPIC).

## 8. Oracle Engine — suprapunere fereastră formă/goluri (EPIC „ML Activation & Oracle Evolution", verificat 2026-08-03)

`oracle_engine._build_profile()`: `form_score` (rezultate W/D/L) și `off_rating`/`def_rating` (derivate din `avg_goals_for`/`avg_goals_against`) provin din **ACEEAȘI fereastră** `last_n_fixtures` (implicit 5 meciuri) — nu e o duplicare de informație (rezultat W/D/L vs. scor brut sunt aspecte diferite ale aceluiași set de meciuri), dar ambele semnale sunt derivate din aceeași fereastră temporală mică, ceea ce limitează diversitatea reală a semnalului de intrare în `calibrate_xg()`.

**Nu e un bug** — observație de proiectare, documentată explicit (comentariu în cod, `oracle_engine.py`, secțiunea „Form score") ca să nu fie redescoperită ca „gol" într-o sesiune viitoare. Documentat integral în `docs/00_GOVERNANCE/ORACLE_ENGINE_AUDIT.md` §6.3 și tratat explicit în `docs/00_GOVERNANCE/ML_ACTIVATION_IMPLEMENTATION_PLAN.md` §2.7/§6.2 (pasul 6: documentare, fără acțiune de cod — o eventuală extindere a `last_n_fixtures` sau diversificare a surselor de semnal ar necesita propriul test de ablație, neinclusă în acest EPIC).

---

## Architecture State Report — convenția de raportare la începutul fiecărei etape

De la ADR-037/R3.5 încolo, orice etapă nouă începe cu acest raport minimal (patru linii, citite din acest document + `git`/Supabase, nu din memorie):

```
- Commit curent: <SHA>
- Ultimul punct de restaurare confirmat: <SHA> pe <branch>, HEAD local == HEAD remote
- Etapa ADR curentă: <ADR-XXX, sub-etapă>
- Etapa precedentă închisă oficial: DA/NU
```
