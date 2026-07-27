# Football Oracle Data Warehouse — Current State & Execution Roadmap (2026-07-27)

**Status**: document de stare arhitecturală, NU un al cincilea audit. Nu repetă concluziile celor 4 audituri existente (§2) — le referențiază, le marchează cu status curent, și adaugă strict ce e nou din 27 iulie: delta față de ele (§3), sinteza lor într-un singur gap analysis (§4), ownership (§5) și sync coverage (§6) — niciunul dintre acestea nu exista consolidat înainte —, și un roadmap executabil pe valoare ML, nu pe ușurință (§7). Zero cod scris, zero migrare, zero ADR — document, per cerință explicită.

**Metodologie**: interogări SQL directe pe producție (`Prediction`), grep/citire directă de cod, citire completă a celor 4 audituri existente. Orice afirmație neverificabilă direct e marcată explicit ca atare.

---

## 1. Executive Summary

| | |
|---|---|
| ✅ **Complet implementat, în producție** | ELO club (pre+post meci, ~100%), ELO național (eloratings.net), H2H, form_score, offensive/defensive ratings — toate în `FEATURE_COLUMNS`, toate ~100% populate. Cote 1X2 open+close (ADR-005/006, Frozen, 1.650 rânduri, ultimele 2 săptămâni). `scheduled_fixtures` + FixtureMergePolicy (singurul merge policy complet documentat din tot proiectul). Migration Gate (ADR-040) — infrastructură de guvernanță, testată, neactivată deliberat. |
| 🟡 **Parțial implementat** | Statistici de meci (șuturi/cornere/cartonașe/faulturi/scor pauză) — 6,5% din `match_history`, doar 5 ligi, oprite la 2025-05-25. Sync Layer R-Sync-3→7a — cod complet, testat, **0 rânduri în producție** (neorchestrat, nu neconstruit). Lineup FreeLF — parsat, doar `unavailable[]` folosit. |
| ⚪ **Doar cercetat/proiectat, zero decizie de implementare** | xG/xA/PPDA prin surse externe noi (Understat/StatsBomb/API-Football) — cercetare completă există (`KNOWLEDGE_ENGINE_SOURCES_AUDIT`), nicio sursă curată pentru toate cele 11 competiții, zero cod. Extindere schemă pentru cornere/faulturi/cartonașe ca și coloane noi (Clasă B) — aprobat conceptual în auditul din 12 iulie, neexecutat. |
| ❌ **Complet lipsă** | Referee (o singură mențiune TODO în tot codul), Attendance, PPDA/pressing, formații ca feature, statistici la nivel de jucător, piețe de pariuri dincolo de 1X2 persistate, market movement granular (doar 2 puncte: opening/closing). |

**Observația centrală a acestui document** (confirmată, nu presupusă): **problema nu mai e „nu avem infrastructură" — e „infrastructura există și nu e orchestrată."** 6 componente Sync Layer complete (R-Sync-3→7a) + o funcție FreeLF completă (`get_match_statistics()`, xG/posesie/big chances reale) există în cod, testate, funcționale — și au zero rânduri/zero apelanți în producție pentru că nimic nu le apelează din `sync/run_daily.py` sau din calea de predicție.

---

## 2. Consolidarea celor 4 audituri existente (referențiate, nu rescrise)

| Document | Concluzia principală | Status azi |
|---|---|---|
| `docs/05_DATA_AUDIT/DATA_AUDIT_2026-07-12.md` | `get_match_statistics()` (FreeLF) — funcție completă, zero apelanți, „descoperirea centrală" a auditului. Roadmap Sprint 1/2/3 aprobat. | 🟡 Sprint 1 parțial (backfill șuturi executat manual o dată, pe altă cale decât cea recomandată în audit) — `get_match_statistics()` însuși **tot neconectat**, reconfirmat identic azi. |
| `docs/05_DATA_AUDIT/DATASET_CAPABILITY_AUDIT_2026-07-13.md` | Analiză empirică pandas a mirror-ului `Club-Football-Match-Data-2000-2025` (48 coloane) — completitudine 75-100% pentru 6 ligi, 0% Romania SuperLiga, sursă oprită la sezonul 2024/25. | ✅ Concluziile rămân valide — confirmat live: backfill-ul „Clasă A" din roadmap (șuturi) a fost executat manual, o dată, exact pe fereastra de date descrisă acolo. |
| `docs/03_ENGINE/KNOWLEDGE_ENGINE_SOURCES_AUDIT_2026-07-13.md` | Cercetare web a surselor externe pentru xG/xA/PPDA — nicio sursă gratuită, curată ToS, pentru toate cele 11 competiții. FBref și-a pierdut fluxul Opta ianuarie 2026. WhoScored/SofaScore/FotMob explicit interzise pentru platforme de pariuri. | ✅ Valid, nicio acțiune întreprinsă de atunci — nicio sursă nouă adăugată. |
| `docs/03_ENGINE/FOOTBALL_DATA_CO_UK_AUDIT_2026-07-13.md` | Verificare directă a sursei folosite deja pentru cote — 6/9 ligi urmărite acoperite, risc de duplicare (646 meciuri deja duplicate), risc de prospețime inversată. Notă de securitate separată: 8 tabele fără RLS. | 🟡 Parțial — backfill de statistici executat parțial (vezi §3); ❌ RLS-ul celor 8 tabele **încă nerezolvat**; ❌ cotele istorice extinse din această sursă **neexecutat**. |

---

## 3. Ce s-a schimbat efectiv față de 12-13 iulie (delta, nu re-audit)

| Domeniu | Stare la audit (12-13 iulie) | Stare azi (27 iulie) |
|---|---|---|
| Statistici de meci (`match_history`) | 0% populate | 6,5% (3.501/53.443), doar 5 ligi (Serie A/La Liga/PL/Bundesliga/Ligue 1), oprite la 2025-05-25 — sursă reală: `sync/sources/football_data_co_uk.py` (mirror GitHub separat de `MAIN_DATASET` Kaggle), rulat manual o dată |
| `odds_history` | 0 rânduri | 1.650 rânduri, 815 fixtures distincte, 13 case de pariuri, ultimele 2 săptămâni — opening ȘI closing 100% populate |
| Sync Layer (R-Sync-3→7a: formă fd.org, ELO național, vreme, formă FreeLF, Odds API recent results, `scheduled_fixtures`) | Nu exista | Cod complet, testat (sute de teste), aplicat pe Supabase — **0 rânduri**, `sync/run_daily.py` nu apelează niciunul din cele 6 scripturi |
| Migration Gate (ADR-040) | Nu exista | Funcțional, testat, `equivalence_evaluations`/`migration_gate_status`/`migration_gate.py` — stare GRAY, neactivat deliberat |
| `equivalence_evaluations` / guvernanță automată | Nu exista conceptul | Infrastructură generică, reutilizabilă pentru orice entitate viitoare din acest document |

---

## 4. Gap Analysis (valoare pentru ML, nu ordine alfabetică)

| Domeniu | Status | Prioritate | Impact ML plauzibil |
|---|---|---|---|
| Cornere/cartonașe/faulturi (`corner_dominance`/`card_diff`/`foul_diff`) | 🟡 6,5%, 5 ligi, oprit 2025-05 — **dar deja ÎN PRODUCȚIE ca feature ML** (ADR-012/013, promovate prin ablație) | **Critică** — model live rulează azi pe bază sparsă/veche pentru aceste feature-uri | Confirmat pozitiv la ablație, dar pe eșantion îngust — risc de calitate silențios pentru meciurile din afara celor 5 ligi/2025 |
| Șuturi/șuturi pe poartă real | 🟡 6,5%, 5 ligi | Înaltă | Necunoscut, netestat — Clasă A (deja populabil, deja parțial populat) |
| xG (predicted + actual), posesie, big chances | ❌ 0% — sursă reală există (`get_match_statistics()`, FreeLF), zero apelanți | Înaltă | Necunoscut — ar înlocui o aproximare deja documentată ca sintetică/falsă (`PREDICTOR_ROADMAP_V4.md`) |
| Scor la pauză (HT) | 🟡 6,5% (aceeași sursă) | Medie | Neexplorat — atenție explicită la scurgere temporală dacă devine feature |
| PPDA/pressing | ❌ zero sursă curată pentru toate ligile urmărite | Scăzută (blocată structural de sursă) | Necunoscut |
| Lineup/formații ca feature | 🟡 parsat (FreeLF `get_lineup()`), aruncat imediat | Mică-medie | Marginal, per audit vechi |
| Injuries | ✅ folosit (API-Football R-Sync-2 + FreeLF `unavailable[]`) | — | Deja în producție, dar fără politică de merge documentată între cele 2 surse |
| Weather (prospectiv) | 🟡 infrastructură nouă completă (R-Sync-5, `weather_forecast_cache`), 0 rânduri (neorchestrat); istoric doar 0,06% (34/53.443) | Medie | Valabil doar prospectiv, nu retroactiv fără backfill separat |
| Referee | ❌ o singură mențiune TODO în tot codul, nicio sursă confirmată | Scăzută (blocată de sursă — nici football-data.org, nici mirror-ul de 48 coloane nu au acest câmp) | Necunoscut |
| Attendance | ❌ absent din toate sursele auditate | Scăzută | Necunoscut |
| Odds 1X2 (open+close) | ✅ Frozen, funcțional, complet populat | — | Deja disponibil (de-vig, value betting) |
| Odds O/U + BTTS | 🟡 fetch-uite, folosite live pentru value bets, **nepersistate** (ADR-006, decizie de scop explicită) | Medie — decizie de produs, nu gol tehnic | Nu e feature ML, activează funcționalitate UI existentă |
| Odds Handicap Asiatic | ❌ nefetch-uit deloc de la Odds API azi | Scăzută | Doar dacă se extinde scope-ul de predicție dincolo de 1X2 |
| Market movement (instantanee multiple) | ❌ doar 2 puncte (opening/closing) | Scăzută-medie | Semnal posibil, complet netestat |
| Team-level statistics (agregat sezon) | 🟡 cod gata (`freelf_team_form_snapshot`/`footballdata_team_form_snapshot`, R-Sync-3/6), 0 rânduri (neorchestrat) | Medie | Neconectat la orchestrare, altfel gata |
| Player-level statistics | ❌ nicio infrastructură | Scăzută (posibil în afara scope-ului de produs — echipă, nu jucător) | Necunoscut |

---

## 5. Data Ownership (lipsea complet până acum — practic ADR-ul câmpurilor)

| Câmp/domeniu | Provider principal | Fallback | Politică de merge |
|---|---|---|---|
| ELO club (pre-meci) | `match_history.home_elo` (import istoric) / ELOTracker live | — | Scriere unică, ADR-023 (Canonical Live ELO) |
| ELO național | eloratings.net (R-Sync-4) | `ELO_RATINGS_FALLBACK` (**temporar**, de eliminat explicit, ADR-039) | Live câștigă, merge simplu |
| H2H | `match_history` (recalculat din `actual_result`) | FreeLF `get_h2h` (event_id-based, blocat până la R-Sync-8) | DB-first (ADR-035 D3) |
| Formă echipă | football-data.org (R-Sync-3) **și** FreeLF (R-Sync-6) | — | **Gol**: două surse independente, fără prioritate documentată între ele |
| Șuturi/cornere/cartonașe/faulturi/HT | `football_data_co_uk.py` mirror (backfill manual) | FreeLF `get_match_statistics()` (neconectat) | **Gol**: un singur writer activ, al doilea complet neconectat, zero politică |
| xG/posesie/big chances | FreeLF `get_match_statistics()` (neconectat, zero apelanți) | — | **Gol total** — nicio sursă activă |
| Vreme (prospectivă) | **WeatherAPI.com** (`api.weatherapi.com/v1`, R-Sync-5) | — | Validate-only — oraș invalid → „necunoscut", niciodată ghicit (deja documentat R-Sync-5) |
| Cote 1X2 | Odds API | — | Opening/closing, scriitor unic, Frozen (ADR-005/006) |
| Cote O/U/BTTS | Odds API (fetch-uit, nepersistat) | — | N/A — decizie de scop, nu owner tehnic |
| `scheduled_fixtures` (identitate meci) | 6 provideri, FixtureMergePolicy | — | SourcePriority explicit per câmp (migrarea 023) — **singurul exemplu complet din tot proiectul** |
| Injuries | API-Football (R-Sync-2) **și** FreeLF `unavailable[]` | — | **Gol**: două surse independente, fără politică de merge documentată |
| Referee | — | — | **Gol total**, nicio sursă |

---

## 6. Sync Coverage — provider → endpoint folosit/nefolosit/de ce

| Provider | Folosit | Nefolosit | Motiv |
|---|---|---|---|
| **FreeLF** | fixtures ✅, standings/formă ✅ (R-Sync-6), H2H event-based ✅ (cuplat la discovery), injuries via `unavailable[]` ✅ | `statistics/{id}` (xG/posesie/big chances) ❌, `lineup.formation`/`confirmed` ⚠ (parsate, aruncate) | Zero apelanți la `get_match_statistics()` — funcție completă, niciodată conectată |
| **Odds API** | events ✅, scores/recent results ✅ (R-Sync-6), odds `h2h` (1X2) ✅ persistat | odds `totals`(O/U) ⚠ fetch/nepersistat, `btts` ⚠ fetch/nepersistat, `spreads`(handicap) ❌ nefetch-uit | O/U+BTTS: decizie de scop ADR-006 (1X2 only). Handicap: nici măcar cerut de la API |
| **API-Football** | fixtures ✅, injuries ✅ (R-Sync-2), coaches ✅ (R-Sync-2) | `/fixtures/statistics` ❌, `/fixtures/lineups` ❌, `/odds` ❌, `/predictions` ❌ | Niciodată implementate — `get_player_stats`/`get_team_stats` explicit `NotImplementedError` |
| **football-data.org** | matches ✅ (discovery, fallback), standings ✅ (R-Sync-3, formă) | referee ❌, scorers ❌ | Referee absent din payload-ul citit; scorers niciodată cerut |
| **TheSportsDB** | events (discovery) ✅, team stats istoric ✅ (blocat de discovery, R-Sync-8) | venue/formation ❌ | `strVenue` deliberat lăsat gol (reparat la sursă, R-Sync-5) — nicio dată de formație citită |
| **ESPN** | scoreboard (discovery) ✅ | `summary` (posesie/șuturi/cartonașe) ❌ | Endpoint nedocumentat oficial, risc de instabilitate — decizie explicită de a nu-l folosi |
| **WeatherAPI.com** | `current`/`forecast` ✅ (R-Sync-5) | `history.json` (vreme istorică retroactivă) ❌ | Niciodată folosit pentru completarea retroactivă a golului istoric de 99,94% |
| **Kaggle** | `MAIN_DATASET` (rezultate 2000-2026) ✅ (import inițial) | `XG_DATASET` (understat) ❌ | Definit în `kaggle.py`, niciodată importat de niciun script |
| **football_data_co_uk mirror** (GitHub, separat de Kaggle) | rezultate/cote istorice ✅ (backfill cote) | match stats ⚠ (backfill manual o dată, neactualizat din 2025-05), Over/Under+Handicap (din acest mirror) ❌ | Backfill manual-only, fără trigger programat |

---

## 7. Prioritizare execuție (valoare ML, nu ușurință de implementare)

**Sprint 1 — orchestrare, zero date noi, zero cod nou de fetch (cel mai mare raport valoare/risc din tot documentul):**
1. Conectează `sync/run_daily.py` la cele 6 scripturi R-Sync-3→7a deja construite, testate, aplicate pe Supabase — pur wiring.
2. Conectează `get_match_statistics()` (FreeLF) în pipeline-ul de backfill/live → populează xG/posesie/big chances/șuturi pe poartă reale, prima dată vreodată.
3. Programează (sau reamintește periodic) `backfill_match_stats.yml` — extinde acoperirea celor 5 ligi dincolo de 2025-05-25 (limita reală a sursei fiind sezonul 2024/25 — verifică dacă a apărut o versiune mai nouă a mirror-ului).

**Sprint 2 — extindere schemă, ADR necesar:**
4. Cornere/faulturi/cartonașe/HT ca și coloane noi (Clasă B, audit 12 iulie) — condiționat de ablație.
5. Politică de merge documentată explicit pentru formă (football-data.org vs. FreeLF) și injuries (API-Football vs. FreeLF) — după modelul FixtureMergePolicy (migrarea 023).

**Sprint 3 — decizie de scop, nu doar tehnică:**
6. O/U + BTTS persistate — revizitare explicită a ADR-006, doar dacă produsul chiar vrea piețe suplimentare.
7. Vreme istorică retroactivă (`/history.json`) — testată prin ablație, nu presupusă utilă.

**Sprint 4 — surse noi, risc mai mare, decizie de arhitect separată:**
8. xG/xA prin Understat sau echivalent — decizie explicită de risc legal (zonă gri ToS, per `KNOWLEDGE_ENGINE_SOURCES_AUDIT`).
9. Referee/Attendance — necesită sursă complet nouă, neconfirmată accesibilă din acest mediu.

---

## 8. Technical Debt

| Element | Descriere |
|---|---|
| **Sync Layer neorchestrat** | Cel mai mare gol din tot documentul — `sync/run_daily.py` nu apelează niciunul din cele 6 scripturi R-Sync-3→7a. Zero cod nou necesar pentru fix, doar wiring. |
| `get_match_statistics()` (FreeLF) | Funcție completă, zero apelanți — găsită de două ori, la 2 săptămâni distanță, de două cercetări independente, fără nicio schimbare între ele. |
| `get_lineup()` (FreeLF) | `formation`/`confirmed` parsate din răspuns, aruncate — doar `unavailable[]` folosit. |
| O/U + BTTS | Fetch-uite, folosite live pentru value bets, nepersistate — decizie explicită (ADR-006), dar merită revizitată acum că scope-ul e Data Warehouse complet. |
| `backfill_match_stats.yml` | Doar `workflow_dispatch` (manual) — s-a oprit acum ~14 luni, nimeni nu l-a mai rulat. |
| **8 tabele fără RLS** | `sync_status`, `elo_ratings`, `api_cache`, `league_provider_coverage`, `api_provider_status`, `provider_metrics`, `shadow_predictions`, `experiment_registry` — semnalat explicit în auditul din 13 iulie, confirmat identic azi, **nu apare în „Goluri cunoscute" din `CLAUDE.md`**. |
| 3 chei API hardcodate (`oracle_api.py`) | Cunoscut, documentat, tratat ca risc real dar neurgent (deja în `CLAUDE.md`). |
| `XG_DATASET` (Kaggle Understat) | Definit în `kaggle.py`, niciodată consumat de niciun script de import. |
| Politici de merge nedocumentate | Formă (2 surse), injuries (2 surse) — spre deosebire de `scheduled_fixtures`, singurul domeniu cu FixtureMergePolicy complet documentată. |
| 4 tabele de backup `match_history_*` fără RLS | Rămase din migrări anterioare (Faza 3, ADR-025 Faza 4, MOV activation, gate07 renorm) — curățare/arhivare neclarificată, în afara scope-ului acestui document. |

---

## Referințe

- `docs/05_DATA_AUDIT/DATA_AUDIT_2026-07-12.md`
- `docs/05_DATA_AUDIT/DATASET_CAPABILITY_AUDIT_2026-07-13.md`
- `docs/03_ENGINE/KNOWLEDGE_ENGINE_SOURCES_AUDIT_2026-07-13.md`
- `docs/03_ENGINE/FOOTBALL_DATA_CO_UK_AUDIT_2026-07-13.md`
- `docs/00_GOVERNANCE/ADR-040-automated-migration-gate-and-equivalence-governance.md` (infrastructura de guvernanță care va valida orice extindere viitoare a acestui Data Warehouse)
- `docs/03_ENGINE/UNIVERSAL_SYNC_ARCHITECTURE_AUDIT_2026-07-22.md` (R-Sync-3→7a, sursa tehnologică a Sprint 1, punctul 1)

*Acest document nu propune și nu autorizează nicio implementare. Fiecare sprint din §7 necesită aprobare explicită separată, conform disciplinei proiectului.*
