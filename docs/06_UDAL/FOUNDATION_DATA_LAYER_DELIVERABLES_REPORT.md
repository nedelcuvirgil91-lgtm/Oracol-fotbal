# Flashscore Foundation Data Layer — Raport final de livrabile

**Status**: implementare completă (schemă + normalizare + persist() idempotent + Data Trust Layer + Data Completeness Score + model de sezon + Season Cleanup dry-run), testată (pytest, fără rețea, contra fixture-ului real `docs/06_UDAL/poc_evidence/flashscore_full_tabs_poc/`). **Scriere live neactivată** — `tos_reviewed=False`, `providers/flashscore/adapter.py.fetch()` rămâne `NotImplementedError`. Acest raport răspunde celor 5 livrabile cerute în „TASK APROBAT — Foundation Data Layer (Flashscore) + Data Trust Layer” **și** extensiei ulterioare „TASK APROBAT — Flashscore Foundation Data Layer (M1)” + „Răspuns oficial — clarificări finale” (secțiunea 6 de mai jos).

**Cod**: `providers/flashscore/normalizer.py` (parsare pură), `providers/flashscore/persistence.py` (I/O), `providers/flashscore/season_cleanup.py` (dry-run), `database/queries.py`, `udal_validation.py`, migrațiile `035`-`038`.

**Teste**: 1769 pytest verzi (cele 3 eșecuri sunt preexistente, neafectate — `tests/test_oracle_api_tsdb_per_league_gate.py`, documentat de mult, fără legătură cu acest task).

---

## 1. Schema Supabase completă (actualizată)

### Coloane noi pe `match_history` (owner: `upsert_match_canonical`, COALESCE-only)

| Coloană | Tip | Migrația |
|---|---|---|
| `attendance` | INTEGER | 035 |
| `capacity` | INTEGER | 035 |

(`home/away_goalkeeper_saves` existau deja din migrația 032, dar RPC-ul canonic nu le scria — **gol închis de migrația 036**, vezi §3.)

### 4 tabele noi

```sql
-- match_statistics_extended (EAV) — UNIQUE (match_id, stat_key)
id, match_id, stat_key, stat_label, home_value_raw, away_value_raw,
home_value_numeric, away_value_numeric, source, captured_at

-- player_match_stats_extended (EAV per jucător) — UNIQUE (player_match_stats_id, stat_key)
id, player_match_stats_id, stat_key, stat_label, value_raw, value_numeric,
source, captured_at

-- flashscore_match_context (H2H + formă recentă) — UNIQUE (context_match_id, category, meeting_order)
id, context_match_id, category, meeting_order, meeting_date, competition_code,
home_team, away_team, home_score, away_score, source, captured_at

-- flashscore_standings_snapshot (clasament curent) — UNIQUE (competition, team)
id, competition, team, rank, played, won, drawn, lost, goals_for, goals_against,
goal_diff, points, source, captured_at

-- flashscore_raw_extraction (stratul RAW, Data Trust Layer) — UNIQUE (match_ref, tab_name)
id, match_ref, tab_name, raw_extracted (jsonb), validation_status, validation_errors,
canonical_written, source, captured_at
```

Toate: `CREATE TABLE IF NOT EXISTS`, RLS activ, scriere `service_role` (via client-ul Python), idempotent (`ON CONFLICT DO UPDATE`).

### Fix RPC (migrația 036)

`_upsert_match_canonical_locked` (RPC-ul canonic, singurul owner de scriere pe `match_history`) a fost extins să scrie și `home/away_goalkeeper_saves`, `attendance`, `capacity` — coloane care existau în schemă de la migrațiile 032/035, dar erau imposibil de persistat prin owner-ul unic, indiferent de payload (gol găsit prin citire de cod, nu presupus).

---

## 2. Lista completă a statisticilor salvate

### `match_history` (coloane dedicate, prin `normalize_match_statistics`)

`home/away_xg_actual`, `home/away_possession`, `home/away_shots`, `home/away_shots_on_target`, `home/away_corners`, `home/away_fouls`, `home/away_yellow_cards`, `home/away_red_cards`, `home/away_offsides`, `home/away_goalkeeper_saves`, `referee`, `stadium`, `attendance`, `capacity`, `home/away_lineup` (jsonb, nume+număr).

### `match_statistics_extended` (EAV — 26 categorii fără coloană dedicată, `normalize_match_statistics_extended`)

`big_chances`, `passes`, `xg_on_target_xgot`, `shots_off_target`, `blocked_shots`, `shots_inside_the_box`, `shots_outside_the_box`, `hit_the_woodwork`, `headed_goals`, `touches_in_opposition_box`, `accurate_through_passes`, `free_kicks`, `long_passes`, `passes_in_final_third`, `crosses`, `expected_assists_xa`, `throw_ins`, `tackles`, `duels_won`, `clearances`, `interceptions`, `errors_leading_to_shot`, `errors_leading_to_goal`, `xgot_faced`, `goals_prevented`, `goal_kicks`.

### `player_match_stats` (roster + îmbogățire, `normalize_player_match_stats` + `normalize_player_match_stats_table`)

`team`, `player_name`, `shirt_number`, `position`, `rating`.

### `player_match_stats_extended` (EAV per jucător — 7 statistici, `PLAYER_TABLE_EXTENDED_COLUMNS`)

`total_shots`, `xg`, `accurate_passes`, `touches`, `touches_in_opposition_box`, `successful_dribbles`, `duels`.

### `flashscore_match_context` (`normalize_match_context`)

`category` (`h2h_overall`/`recent_form_home`/`recent_form_away`), `meeting_date`, `competition_code` (populat — vezi corectura de mai jos), `home_team`, `away_team`, `home_score`, `away_score`.

### `flashscore_standings_snapshot` (`normalize_standings`)

`rank`, `played`, `won`, `drawn`, `lost`, `goals_for`, `goals_against`, `goal_diff`, `points`.

### Odds (`normalize_odds`, RAW-only — vezi §6.1)

`bookmaker`, `home`, `draw`, `away` — extras din tab-ul dedicat, scris în stratul RAW (`flashscore_raw_extraction`). **NU** scris încă în tabela canonică `odds_fallback_flashscore` (ADR-043) — vezi §6.1 pentru motiv.

### Corectură față de raportul inițial: goluri închise

- **`flashscore_match_context.competition_code`** — ERA gol de populare (raportat explicit mai sus în versiunea inițială a acestui document) — **închis**: elementul real `.h2h__event` (text scurt, ex. „SL”) e extras acum, verificat pe fixture.

### Gol cunoscut, activ, rămas neschimbat (onest raportat, nu ascuns)

- **`player_match_stats.goals/assists/yellow_cards/red_cards`** — coloane existente din migrația 032 (`NOT NULL DEFAULT 0`), dar Flashscore Foundation Data Layer nu le scrie încă (nicio sursă curată identificată pentru ele în tab-urile vizitate până acum) — rămân `0` implicit (valoare de schemă, NU un fapt confirmat „zero evenimente”) pentru orice rând scris de acest flux. Nu se confundă cu absența unui eveniment real — consecvent cu North Star #8, rândurile nu inventează o valoare, dar cititorul trebuie să știe explicit că acest câmp nu e încă sursă de adevăr.

---

## 3. Fluxul RAW → VALIDATED → CANONICAL (documentat)

```
pages (HTML per tab, deja citit)
        │
        ▼
normalize_*()  [providers/flashscore/normalizer.py — PUR, fără I/O]
        │
        ▼
┌───────────────────────────────────────────────────────────┐
│ RAW  — flashscore_raw_extraction(match_ref, tab_name)      │
│ Scris ÎNTOTDEAUNA, indiferent de rezultatul validării.     │
└───────────────────────────────────────────────────────────┘
        │
        ▼
VALIDATED — udal_validation.validate_flat_identity()
  verifică home_team/away_team/kickoff_date (cheia naturală)
        │
   ┌────┴────┐
   │ valid   │ invalid
   ▼         ▼
CANONICAL   (oprire — canonical_written=False,
persist_match_   validation_status='rejected',
foundation_data()  validation_errors=[...])
   │
   ▼
match_history + match_statistics_extended + player_match_stats(+extended)
+ flashscore_match_context + flashscore_standings_snapshot
   │
   ▼
flashscore_raw_extraction.validation_status='valid', canonical_written=True
```

**„Nu există bypass”**: `persist_match_with_data_trust_layer()` (punctul de intrare oficial, `providers/flashscore/persistence.py`) e singura cale de scriere prevăzută pentru Foundation Data Layer — scrierea CANONICAL rulează DOAR condiționat de rezultatul validării, niciodată necondiționat. Testat explicit: un meci fără cheie naturală scrie RAW (dovadă păstrată) dar NU atinge nicio tabelă canonică (`test_data_trust_layer_invalid_record_skips_canonical_but_writes_raw`).

**Idempotență** (verificată explicit, nu presupusă): `persist_match_foundation_data()` rulat de 1, 2 și 10 ori contra aceluiași fixture produce exact același număr de rânduri per tabelă și ACELEAȘI id-uri rezolvate — `tests/test_providers_flashscore_persistence_idempotency.py`, parametrizat.

---

## 4. ADR-044, finalizat

`docs/00_GOVERNANCE/ADR-044-flashscore-foundation-data-layer.md` — Status: ACCEPTAT. Acoperă: rolul complementar al Flashscore (nu înlocuiește providerii API), Data Trust Layer, schema completă, garanțiile obligatorii înainte de integrare Predictor/ML, alternativele respinse. Referențiat din `docs/00_GOVERNANCE/ARCHITECTURE_STATE.md` §0.1.

---

## 5. Câmpuri noi disponibile pentru Predictor/ML viitor (fără nicio integrare încă)

**Toate câmpurile de mai jos există în Supabase azi, populate (cu excepția celor 2 goluri din §2), dar NICIUN cod Oracle Engine/ML nu le citește** — orice folosire viitoare rămâne un task separat, condiționat de „Garanțiile obligatorii” din ADR-044 (§ dedicată) și de disciplina de ablație (CLAUDE.md, „Regulile ML” — niciun feature nou fără test de ablație măsurat).

**Prioritate mare pentru testare de ablație** (deja pe coloane `match_history`, azi goale pentru meciurile Flashscore): `home/away_fouls`, `home/away_offsides`, `home/away_goalkeeper_saves`, `attendance`.

**Prioritate medie** (necesită prima dată populare la scară + decizie explicită de includere în `FEATURE_COLUMNS`): `xG on target (xGOT)`, `Expected assists (xA)`, `Big chances`, `Touches in opposition box`, `Duels won`, statisticile per jucător (`rating`, `xg`, `accurate_passes`).

**Prioritate mică / neclar** (fără ipoteză formulată): restul EAV-ului (`tackles`, `clearances`, `interceptions`, `blocked_shots`, etc.), `flashscore_match_context` (Oracle Engine are deja H2H Database-First din `match_history`, ADR-035 D3 — valoare marginală), `flashscore_standings_snapshot` (niciun consumator clar identificat azi).

**Explicit exclus din orice integrare viitoare fără ADR nou**: nimic din acest raport autorizează o schimbare de `oracle_engine.py`/`ml_predictor.py`/`config.json` — rămâne blocat de ML Activation Gate (`docs/00_GOVERNANCE/ML_ACTIVATION_GATE.md`) până la finalul Critical Path (M4) sau aprobare explicită separată.

---

## 6. Extensie M1 — „TASK APROBAT — Flashscore Foundation Data Layer (M1)” + „Răspuns oficial — clarificări finale”

Detalii complete: ADR-044, Addendum (2026-07-29). Rezumat verificabil direct în cod:

### 6.1 Odds — gol închis, cu o limitare explicită

`normalize_odds()` extrage cota curentă 1X2 per bookmaker (structură verificată pe fixture: `.oddsCell__bookmakerPart`/`.oddsCell__odd`, ordine confirmată prin `data-analytics-label`). Scris în stratul RAW. **Scrierea canonică în `odds_fallback_flashscore` (ADR-043) rămâne deliberat neimplementată** — necesită rezolvarea identității `fixture_id` cross-provider (aceeași valoare folosită de The Odds API), un task separat, documentat deja de ADR-043; scrierea cu o cheie greșită ar rupe silențios regula de fallback a Predictorului.

### 6.2 Data Completeness Score — persistat, neconsumat

`flashscore_data_completeness` (migrația 037) — 7 flag-uri (Summary/Statistics/Lineups/PlayerStats/Odds/H2H/Standings, prezența FETCH, nu succesul extracției) + `coverage_percent`. Scris indiferent de rezultatul validării. Verificat pe fixture: coverage 100% (toate cele 7 tab-uri prezente). **Nu e citit de Oracle Engine azi.**

### 6.3 Model de sezon — schemă pregătită, populare condiționată de provider

Coloană `season` (migrația 038) pe `match_history` + toate cele 7 tabele Foundation Data Layer. **Regulă strictă**: scrisă DOAR dacă providerul o oferă explicit — niciodată dedusă din reguli calendaristice proprii. Verificat direct pe fixture: **Flashscore nu expune azi un sezon robust** în niciunul din cele 7 tab-uri confirmate — toate rândurile scrise de acest flux au `season = NULL` până la o sursă reală (provider care oferă sezonul, sau o viitoare tabelă de configurare per competiție, neimplementată). Parametrul `season` există în semnătura `persist_match_foundation_data()`/`persist_match_with_data_trust_layer()`, propagat uniform, gata de folosire imediat ce o sursă reală apare.

### 6.4 Season Cleanup — Discovery + Cleanup Report, fără nicio ștergere

`providers/flashscore/season_cleanup.py` — implementează DOAR primii 2 pași din fluxul oficial (`Discovery → Validation → Cleanup Report → Backup → Delete → Integrity Check → Final Report`). Politică: 6 sezoane (curent + 5 istorice). **Scope explicit restrâns** la cele 6 tabele Foundation Data Layer — exclude explicit `match_history`/`match_events`/`player_match_stats` de bază (ar afecta istoricul ML) și `odds_history` (Frozen). **Verificabil direct în cod**: modulul nu conține nicio operație `DELETE`; `discover_seasons()`/`build_cleanup_dry_run_report()` returnează mereu `delete_executed: False`. Rulat azi contra Supabase-ului real (0 rânduri cu `season` populat, din cauza §6.3) ar raporta onest „niciun sezon cunoscut găsit” — nu o concluzie fabricată.

### 6.5 Ce rămâne, explicit, pentru o etapă viitoare (neimplementat, nu omis din neglijență)

- Rezolvarea `fixture_id` cross-provider pentru scrierea canonică a cotelor Flashscore (§6.1).
- O sursă reală de `season` (provider care îl oferă, sau tabelă de configurare per competiție) — fără ea, ponderarea Oracle/ML pe sezon (motivația explicită a acestei extensii) nu poate începe.
- Activarea reală a Season Cleanup (Backup → Delete → Integrity Check → Final Report) — necesită propriul flag dedicat și propria aprobare explicită, separată de acest task.
