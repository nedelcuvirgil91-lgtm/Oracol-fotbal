# BACKLOG_ARHITECTURAL_AUTOMATIZARE_2026-07-14.md — Football Oracle

**Status**: Backlog clasificat. Ținta declarată: zero intervenții manuale pentru funcționarea normală a aplicației — butoanele/workflow-urile manuale rămân doar pentru debugging, administrare și excepții.

**[ACTUALIZAT 2026-07-28]** Itemul 1.1 e implementat — verificat direct în cod:
`sync/run_daily.py` apelează `backfill_features.run_backfill(dry_run=False)`
ca parte a pipeline-ului zilnic (`PipelineStep("feature_update",
depends_on="history_sync")`, linia ~493), exact planul descris mai jos.
Restul itemilor din document rămân neimplementate — corectat aici doar
itemul verificat fals, nu tot documentul.

Fiecare proces manual identificat (Task 5, `docs/03_ENGINE/...` — sesiunea de audit din 2026-07-14) e clasificat aici cu întrebarea standard: **De ce e manual? Poate fi automatizat? Risc? Cost? Ce schimbări arhitecturale? În ce sprint?**

---

## Nivel 1 (critic) — sincronizare date, baze istorice, pipeline ML, shadow testing, promotion, deploy

### 1.1 Actualizare feature-uri/dataset după meci terminat (`sync/backfill_features.py`) — **[IMPLEMENTAT, vezi nota din Status]**
- **De ce era manual** (istoric, la data redactării): `backfill.yml` e exclusiv `workflow_dispatch`, fără `cron`. `backfill.yml` rămâne el însuși manual (canal de backfill ad-hoc pe tot dataset-ul), dar `run_backfill()` rulează acum și automat, zilnic, din `sync/run_daily.py`.
- **Poate fi automatizat**: Da — funcția `run_backfill()` e deja idempotentă, non-destructivă (gating per-coloană), sigură de rulat zilnic pe tot dataset-ul fără cost de corectitudine.
- **Risc**: Scăzut — comportament deja testat (252+ teste), pattern-ul non-destructiv elimină riscul de suprascriere.
- **Cost**: Scăzut — reutilizare 100% cod existent, doar un apel nou în `run_daily.py`.
- **Schimbări arhitecturale**: Niciuna — extinde orchestratorul zilnic existent (guvernat de ADR-004), nu creează unul nou.
- **Sprint**: **Sprintul curent** — e exact obiectivul „închiderea fluxului post-match → feature update → dataset update".

### 1.2 Actualizare statistici brute (`sync/backfill_match_stats.py` — shots/corners/cards/fouls/HT)
- **De ce e manual**: `backfill_match_stats.yml`, exclusiv `workflow_dispatch`.
- **Poate fi automatizat**: Da — `MatchStatsBackfillService` are aceeași disciplină non-destructivă.
- **Risc**: Scăzut, dar sursa (football-data.co.uk) publică date cu întârziere (nu sunt disponibile imediat post-meci) — trebuie verificată frecvența reală de actualizare a sursei înainte de a promite „automat imediat".
- **Cost**: Scăzut — reutilizare cod existent.
- **Schimbări arhitecturale**: Niciuna.
- **Sprint**: **Sprintul curent**, condiționat de verificarea prealabilă a latenței sursei.

### 1.3 Promotion Engine (Learning Core)
- **De ce e manual**: Nu există încă — infrastructura de promovare (`promote_experiment()`) există în `shadow_testing.py`, dar nimic n-o apelează automat, per design ADR-002 (promovare doar manuală, dovadă statistică simultană).
- **Poate fi automatizat**: Da, dar explicit interzis până la un ADR dedicat (ADR-002: „Promovarea automată... necesită un ADR nou dedicat înainte de activare").
- **Risc**: Ridicat dacă automatizat prematur — exact motivul pentru care ADR-002 cere gate explicit.
- **Cost**: Ridicat — necesită Promotion Engine, Champion Manager complete (Not Implemented azi).
- **Schimbări arhitecturale**: Majore — Learning Core complet.
- **Sprint**: **Epic separat**, explicit amânat („după finalizarea acestui sprint" per directivele anterioare).

### 1.4 Deploy (model nou devine live)
- **De ce e manual**: Nu există separare Champion/Challenger azi — modelul se antrenează în memorie, per proces, fără persistare/versionare reală.
- **Poate fi automatizat**: Da, dar depinde de 1.3 (Promotion Engine) — nu poate fi rezolvat izolat.
- **Risc**: Ridicat — fără gate de validare, „deploy automat" azi ar însemna literalmente orice antrenare reușită devine live, fără control.
- **Cost**: Ridicat — necesită persistare model + Champion Manager.
- **Schimbări arhitecturale**: Majore.
- **Sprint**: **Epic separat** (Learning Core).

---

## Nivel 2 — Workflow-uri GitHub Actions `workflow_dispatch`-only

### 2.1 Backfill-uri istorice (`backfill.yml`, `backfill_odds.yml`, `backfill_match_stats.yml`)
- **De ce e manual**: Concepute inițial ca instrumente de recuperare/populare inițială, nu ca parte a fluxului zilnic.
- **Poate fi automatizat**: Parțial — `backfill.yml`/`backfill_match_stats.yml` da (vezi 1.1/1.2, devin parte din `daily.yml`). `backfill_odds.yml` (istoric 5 ani, cost mare per rulare) rămâne candidat mai slab pentru automatizare zilnică — cost/beneficiu diferit (rulare grea, date deja capturate zilnic prin `OddsPersistenceService`).
- **Risc**: Scăzut pentru primele două; necunoscut pentru `backfill_odds.yml` fără o analiză separată de cost.
- **Cost**: Scăzut-mediu.
- **Schimbări arhitecturale**: Niciuna pentru primele două (absorbite în `daily.yml`); posibil un cron separat, mai rar, pentru `backfill_odds.yml`.
- **Sprint**: Primele două — **sprintul curent** (parte din 1.1/1.2). `backfill_odds.yml` — **sprint separat**, neprioritizat încă.

### 2.2 Import istoric (`import_kaggle.yml`, `inspect_kaggle.yml`, `verify_freshness.yml`)
- **De ce e manual**: Import one-shot de dataset extern static (Kaggle) — nu are o cadență naturală „zilnică", sursa însăși nu se actualizează des.
- **Poate fi automatizat**: Nu are sens ca frecvență zilnică — candidat pentru control automat rar (lunar?) sau rămâne manual prin design (nu orice proces manual e „datorie tehnică" dacă frecvența reală a sursei nu justifică automatizare).
- **Risc**: N/A.
- **Cost**: N/A.
- **Schimbări arhitecturale**: Niciuna propusă.
- **Sprint**: **Neprioritizat** — candidat pentru re-evaluare, nu pentru eliminare automată forțată.

### 2.3 PoC-uri (`poc_statsapi.yml`, `poc_api_football_statistics.yml`, `bootstrap_league_learning.yml`)
- **De ce e manual**: Explicit instrumente de explorare/discovery, nu fluxuri de producție.
- **Poate fi automatizat**: Nu ar trebui — sunt unelte de debugging prin design.
- **Sprint**: **Nu se automatizează** — rămân manuale prin definiție (Nivel 3 de facto, nu Nivel 2).

---

## Nivel 3 — Operațiuni Streamlit (rămân pentru debugging/administrare)

### 3.1 „🔄 Reîncarcă meciuri" / „🔄 Reîncarcă" / „🗑️ Clear cache complet"
- **De ce e manual**: Fallback de prospețime când TTL-ul de cache nu e suficient de agresiv pentru un caz specific.
- **Poate fi automatizat**: Parțial — TTL-urile deja există; problema reală (semnalată în Task 2) e lipsa verificării de TTL pe `st.session_state["all_matches"]`. Fix-ul corect nu e „elimină butonul", ci „adaugă verificare automată de prospețime", păstrând butonul ca override manual.
- **Risc**: Scăzut.
- **Cost**: Scăzut.
- **Schimbări arhitecturale**: Minime — un check de vârstă pe `session_state`.
- **Sprint**: **Neprioritizat pentru sprintul curent** — nu blochează închiderea fluxului live; candidat pentru un sprint de „simplificare cache" (Defect Arhitectural #4, deja notat).

### 3.2 „🎓 Antrenează ML acum"
- **De ce e manual**: Suprapunere cu antrenarea automată deja existentă (la fiecare instanțiere `FootballOracleEngine`, plus `daily.yml`/`weekly.yml`).
- **Poate fi automatizat**: Deja parțial automat (vezi 1.1 context) — butonul rămâne util strict ca declanșator manual de test/debugging, nu ca mecanism principal.
- **Risc**: Scăzut.
- **Cost**: Zero — comportamentul dorit (retrain automat) există deja.
- **Schimbări arhitecturale**: Niciuna.
- **Sprint**: **Rămâne cum e** — clasificat corect deja ca Nivel 3 (debugging), nu necesită eliminare.

### 3.3 „🔬 Rulează sondajul acum" (probă API-Football)
- **De ce e manual**: Explicit un instrument de discovery/diagnostic (nu scrie în `match_history`).
- **Poate fi automatizat**: Nu ar trebui.
- **Sprint**: **Nu se automatizează** — corect clasificat ca administrare.

---

## Nivel 4 — Portofoliu

### 4.1 Introducere manuală rezultat pariu (W/L)
- **De ce e manual**: Formularul din Portfolio nu a fost niciodată conectat la `match_history.actual_result`, deși acesta se sincronizează automat zilnic.
- **Poate fi automatizat**: Da — la actualizarea unui rezultat în `match_history` (deja automată, `sync_results.py`), s-ar putea determina automat W/L pentru orice pariu `PENDING` cu `fixture_id` care se potrivește (comparând `Selection`/`Market` cu `actual_result`).
- **Risc**: Mediu — necesită mapare corectă piață→rezultat (1X2 e direct, dar BTTS/Over-Under/Handicap necesită logică de evaluare per piață, nu doar `actual_result`). Pariu introdus cu `Fixture ID="manual"` (permis azi) nu are cum fi automatizat — rămâne un caz de excepție.
- **Cost**: Mediu — logică de evaluare per tip de piață, nu doar 1X2.
- **Schimbări arhitecturale**: O funcție nouă de reconciliere Portfolio↔match_history (fără impact asupra Predictorului/ML).
- **Sprint**: **Candidat puternic pentru sprintul următor după închiderea fluxului live** — impact vizibil pentru utilizator, cost moderat, zero risc pentru motorul de predicție.

---

## Rezumat prioritizare

| Item | Nivel | Sprint |
|---|---|---|
| Feature/dataset update automat post-match | 1 | **Curent** |
| Statistici brute (shots/corners/cards/fouls/HT) automat post-match | 1 | **Curent** (condiționat de latența sursei) |
| Promotion Engine / Deploy | 1 | Epic separat (Learning Core) |
| `backfill.yml`/`backfill_match_stats.yml` → absorbite în `daily.yml` | 2 | **Curent** (= aceleași item-uri ca 1.1/1.2) |
| `backfill_odds.yml` automat | 2 | Sprint separat, neprioritizat |
| Import Kaggle / PoC-uri | 2-3 | Nu se automatizează |
| Cache session_state — verificare TTL automată | 3 | Sprint „simplificare cache" |
| Buton retrain ML manual | 3 | Rămâne (deja redundant cu automatul) |
| Reconciliere automată Portfolio↔match_history | 4 | Sprint următor (după flux live) |
