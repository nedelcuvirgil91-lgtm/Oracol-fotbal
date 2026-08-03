# Oracle Engine Audit

**Status**: AUDIT — nicio modificare de cod. Etapa 1 din EPIC „ML Activation & Oracle Evolution".

**Data**: 2026-08-03.

**Autor**: Claude, la cererea proprietarului produsului.

**Scop**: inventar complet, verificat din cod și din date live (Supabase `Prediction`), al tuturor feature-urilor, ponderilor, regulilor hardcodate și cascadelor de penalizare din calea reală de predicție (`oracle_engine.py::evaluate_match()` → `feature_engine.py` → `injury_manager.py`). Bază pentru Etapa 4 (roadmap) — acest document NU propune nicio schimbare, doar constată.

**Metodologie**: citire directă de cod (`oracle_engine.py`, `feature_engine.py`, `injury_manager.py`, `oracle_api.py`), verificare live a valorilor curente din `model_weights`/`model_config` (Supabase, proiect `Prediction`), grep exhaustiv pentru confirmarea căilor de apel (cine cheamă efectiv ce, nu presupunere din docstring).

---

## 1. Fluxul complet — de la input la `home_xg`/`away_xg`/`ph`/`pd`/`pa`

```
_build_profile(home) ─┐
_build_profile(away) ─┤
                       ├─→ _calibrate_xg() ─→ [H2H modifier] ─→ [weather penalty] ─→ home_xg/away_xg (calibrate_xg-final)
_build_h2h() ──────────┘                                                                  │
                                                                                            ▼
                                                                          [injury penalty — pass SEPARAT, DUPĂ]
                                                                                            │
                                                                                            ▼
                                                                              _poisson_model(home_xg, away_xg) → ph, pd, pa
                                                                                            │
                                                                                            ▼
                                                                          _monte_carlo(home_xg, away_xg) → mc_ph/pd/pa (verificare, nu suprascrie)
                                                                                            │
                                                                                            ▼
                                                                    [ML blend — DOAR dacă ml_blending_enabled=True, azi FALSE implicit]
```

`_build_flashscore_dna()`, `get_team_health()` (apifootball_metadata) rulează **în paralel**, nu ating deloc acest flux — confirmate explicit prin comentarii în cod („NU intră în TeamProfile, NU atinge compute_team_offdef_rating()/blend_predictions") și prin faptul că singurul lor consum e shadow logging condiționat de flag-uri implicit oprite.

---

## 2. Toate feature-urile folosite — inventar complet

### 2.1 — Feature-uri care intră DIRECT în calculul `home_xg`/`away_xg`

| # | Feature | Sursă | Unde intră | Contribuție |
|---|---|---|---|---|
| 1 | `offensive_rating` (home/away) | `_build_profile()` → `compute_team_offdef_rating()` | `calibrate_xg()`, multiplicator direct | Componenta principală a xG propriu |
| 2 | `defensive_rating` (home/away) | `_build_profile()` → `compute_team_offdef_rating()` | `calibrate_xg()`, modulează xG-ul ADVERSARULUI | Componenta principală a xG advers |
| 3 | `form_score` (home/away) | `_build_profile()` → `compute_form_score()`, ponderare exponențială pe ultimele `last_n_fixtures` (implicit 5) rezultate | `calibrate_xg()`, `home_form_mod = 0.80 + form_score*0.40` | Modulează multiplicativ, range [0.80, 1.20] |
| 4 | ELO (club, primar) | `database.queries.get_latest_team_elo()` (Database-First, ADR-023/035 D2) | Blend în `compute_team_offdef_rating()` (`elo_blend_weight=0.35`) — NU intră separat în `calibrate_xg()` | 35% din off/def rating dacă ELO disponibil |
| 5 | ELO (național, fallback) | `database.queries.get_national_team_elo()` — DOAR dacă echipa n-are meciuri de club sincronizate | Identic cu #4 | Identic cu #4 |
| 6 | `h2h_modifier` | `_build_h2h()` → cascadă DB/FreeLF/Odds API → `compute_h2h_modifier()` | `calibrate_xg()`, DOAR dacă `h2h_meetings >= 2` | ±`h2h_weight` (implicit 0.15) aplicat opus pe cele 2 echipe |
| 7 | `league_baseline` | `weights["league_baselines"][league]` (static, per ligă) | `calibrate_xg()`, multiplicator `baseline` | Scală absolută goluri/meci per ligă |
| 8 | `home_advantage` / `away_penalty` | `weights` (global sau per-ligă, vezi §4) | `calibrate_xg()`, multiplicator final | ~±5-9% în funcție de ligă |
| 9 | `weather_penalty` | `database.queries.get_weather_forecast()` (Database-First, ADR-039 R-Sync-5) — populat de `oracle_api.get_weather()` în Sync Layer | `calibrate_xg()`, discount multiplicativ egal pe ambele echipe | 0-15%, vezi §5.3 |
| 10 | Injury penalty | `injury_manager.build_injury_report_from_raw_lineup()` + `apply_injury_penalty()` | **DUPĂ** `calibrate_xg()`, pass separat | -0% până la -30% per echipă, vezi §5.4 |

### 2.2 — Feature-uri de context, NU intră în calculul xG (informativ/shadow)

| Feature | Sursă | Rol real |
|---|---|---|
| Team DNA Flashscore (`home_flashscore_dna`/`away_flashscore_dna`) | `_build_flashscore_dna()` (Faza 2, ADR-044 §5) | Pur informativ — afișat în UI, shadow-logat dacă `flashscore_shadow_logging_enabled=True` (**confirmat live: TRUE azi**, dar shadow logging nu influențează `ph`/`pd`/`pa` servite) |
| `apifootball_metadata` (health/injuries API-Football) | `database.queries.get_team_health()` | Pur informativ — shadow-logat dacă `shadow_mode_enabled=True` (implicit False) |
| `avg_corners`/`avg_fouls`/`avg_yellow_cards`/`avg_ht_goals`/`avg_shots` | `_real_match_events()` | Afișate în UI („Team DNA" card), NU intră în `compute_team_offdef_rating()` — pur descriptive |
| Odds bookmaker (`home_odds`/`draw_odds`/`away_odds`) | `match.get("home_odds", ...)` | Folosite DOAR pentru value bets/edge/Kelly, NU influențează `home_xg`/`away_xg`/`ph`/`pd`/`pa` |

### 2.3 — Feature-uri calculate dar NEAPELATE deloc în calea live

| Feature | Sursă | Status |
|---|---|---|
| `rest_days_modifier()` | `feature_engine.py:108-127` | **Complet neapelat** — respins explicit prin test de ablație pe 53.409 meciuri reale (`docs/03_ENGINE/REST_DAYS_VALIDATION.md`, precedent citat în CLAUDE.md), păstrat în cod ca funcție pură documentată, nu ca „dead code" ascuns — decizie deliberată, nu omisiune |

---

## 3. Contribuția fiecărui feature — analiză formulă (`calibrate_xg`)

```python
home_xg = home_offensive_rating * away_def_mod * baseline * (form_weight * home_form_mod + dna_weight) * home_advantage
away_xg = away_offensive_rating * home_def_mod * baseline * (form_weight * away_form_mod + dna_weight) * away_penalty
```

Observație structurală importantă: **`dna_weight` NU corespunde niciunui semnal real de „Team DNA"** — e o constantă adunată necondiționat la `form_weight * form_mod`, nemodulată de nicio valoare dinamică a echipei. Numele e moștenit dintr-un design mai vechi; azi „Team DNA" (UI) și „Team DNA Flashscore" (§2.2, pur informativ) sunt concepte COMPLET SEPARATE de acest `dna_weight`. Trei lucruri diferite poartă azi numele „Team DNA" în proiect — risc real de confuzie pentru orice cititor viitor (vezi §6.2).

`away_def_mod`/`home_def_mod` (modulează xG-ul PROPRIU pe baza defensivei ADVERSARULUI):
```python
away_def_mod = 0.60 + (away_defensive_rating / defensive_cap) * 0.80   # range [0.60, 1.40]
home_def_mod = 0.60 + (home_defensive_rating / defensive_cap) * 0.80
```
Verificat: direcția e corectă — `defensive_rating` mai mare = apărare mai slabă (concede mai multe goluri, vezi §3.1) = modulator mai mare = xG-ul adversarului crește. Nu e o inversare de semn, cum ar părea la prima citire.

### 3.1 — `compute_team_offdef_rating()` — de unde vin `offensive_rating`/`defensive_rating`

```python
g_norm   = min(avg_goals_for / 2.0, 1.0) * 1.5      # cap la 2.0 goluri/meci
sot_norm = min(avg_shots_on_target / 6.0, 1.0) * 1.5 # cap la 6 șuturi pe poartă/meci
pos_norm = max(0.0, min(((avg_possession - 30.0) / 40.0) * 0.5, 0.5))  # 30%→0, 70%+→0.5

off_stat = min(g_norm*goals_weight + sot_norm*shots_ot_weight + pos_norm*possession_weight + avg_goals_for*0.2, offensive_cap)
def_stat = min(avg_goals_against, defensive_cap)
```

**Vezi §6.1 — `avg_goals_for` intră de DOUĂ ORI în `off_stat`** (o dată prin `g_norm*goals_weight`, o dată prin `+ avg_goals_for*0.2` necondiționat, cu o pondere hardcodată separată de sistemul de `weights` configurabil).

`defensive_rating` = literal `avg_goals_against` (capat) — nu e o „formulă", e media brută a golurilor primite.

Dacă ELO disponibil, ambele rating-uri sunt blendate 65%/35% (`elo_blend_weight`) cu multiplicatorul ELO sigmoid — vezi §4.4.

---

## 4. Ponderi fixe — inventar complet, cu valorile curente verificate live

### 4.1 — `DEFAULT_CONFIG` (`oracle_engine.py:127-172`)

| Cheie | Valoare | Rol |
|---|---|---|
| `elo_blend_weight` | 0.35 | Cât cântărește ELO-ul vs. statisticile brute în off/def rating |
| `elo_sigmoid_scale` | 400.0 | Panta sigmoidei ELO→multiplicator |
| `elo_reference` | 1500.0 | ELO „neutru" (multiplicator = mijlocul intervalului) |
| `h2h_weight` | 0.15 | Amplitudinea maximă a modificatorului H2H |
| `h2h_lookback_days` | 1095 (3 ani) | Fereastra de căutare H2H (nefolosită direct în cascada DB, doar în fallback-uri vechi) |
| `last_n_fixtures` | 5 | Câte meciuri recente intră în form/rating |
| `max_goals_poisson` | 8 | Trunchierea matricei Poisson (vezi P2, risc deja documentat: pierdere de masă de probabilitate la xG mare) |
| `monte_carlo_simulations` | 10.000 | Fixat, cu seed fix (`seed=42`) — determinist |
| `ml_blending_enabled` | **False** | Confirmat live: cheia lipsește din `model_config` (NULL în Supabase) → codul cade pe default `False` |

### 4.2 — `DEFAULT_WEIGHTS` — globale (`oracle_engine.py:174-193`)

`goals_weight=0.45, shots_ot_weight=0.30, possession_weight=0.25, form_weight=0.60, dna_weight=0.40, home_advantage=1.07, away_penalty=0.95, offensive_cap=3.5, defensive_cap=2.5`.

### 4.3 — Ponderi per-ligă — **VERIFICATE LIVE, CONSTATARE MAJORĂ**

`weights["league_weights"]` conține valori DIFERITE per ligă (ex. Bundesliga: `dna_weight=0.35, form_weight=0.65, home_advantage=1.08` vs. default `0.40/0.60/1.07`). Mecanismul de blend (`resolve_league_weights()`, `feature_engine.py:176-205`) le combină cu globalul proporțional cu `sample_count`, saturând la `sample_count=5`.

**Verificat live** (`model_weights`, Supabase, `updated_at: 2026-07-08`): **`sample_count = 0` pentru TOATE cele 11 ligi, fără excepție.** `alpha = min(0/5, 1) = 0` → `resolve_league_weights()` returnează azi **100% ponderile GLOBALE, 0% cele per-ligă**, indiferent de valorile diferite prezente în date.

**Cauza, confirmată**: `sample_count` se incrementează DOAR prin `recalibration.py`, apelat din `sync/sync_results.py`, gatat de `auto_recalibration_enabled` — **confirmat live: cheia lipsește din `model_config` (NULL) → cade pe default `False`** (`sync/sync_results.py:125`).

**Concluzie**: ponderile per-ligă, deși prezente și aparent calibrate diferit per competiție, sunt azi **complet inerte în formula servită** — nu o eroare (flag oprit implicit, conform Regulii North Star #3), dar un fapt pe care Etapa 4 trebuie să-l ia în calcul explicit: activarea `auto_recalibration_enabled` ar schimba comportamentul predicției pe măsură ce `sample_count` crește, fără nicio altă schimbare de cod.

### 4.4 — Transformări ELO (`feature_engine.py:93-100`)

```python
elo_to_offensive_multiplier: 0.55 + sigmoid((elo-1500)/400) * 1.10   # range [0.55, 1.65]
elo_to_defensive_multiplier: 1.80 - sigmoid((elo-1500)/400) * 1.20   # range [0.60, 1.80]
```
Complet hardcodate (referință 1500, scală 400, intervalele 0.55-1.65 / 0.60-1.80) — nicio validare de ablație citată pentru aceste constante specifice (spre deosebire de `corner_dominance`/`shot_dominance`/etc., care AU documente de ablație dedicate).

### 4.5 — Constante injurii (`injury_manager.py:31-58`)

`POSITION_WEIGHTS` (GK=1.5, DEF=1.0, MID=0.8, FWD=1.2), `MAX_SINGLE_PLAYER_IMPACT=0.18`, `MAX_TOTAL_TEAM_IMPACT=0.30`, `MARKET_VALUE_KEY_PLAYER=20M€`, `MARKET_VALUE_STARTER=5M€`, `max_expected=150M€` (Mbappé-level, hardcodat inline în `_calc_impact_from_market_value`) — toate hardcodate, nicio sursă de calibrare/ablație citată.

**Discrepanță găsită** (`injury_manager.py:104` vs. `114`): docstring-ul funcției spune `penalty = min(mv_share * pos_w * certainty * 0.20, MAX_SINGLE)`, dar codul efectiv folosește **`0.25`**, nu `0.20`. Comentariu neactualizat față de cod — minor, dar exact genul de discrepanță pe care „Verificat, nu presupus" trebuie s-o prindă.

---

## 5. Reguli hardcodate — cascade complete

### 5.1 — Cascada de calibrare xG (`calibrate_xg`, ordinea EXACTĂ)

1. `home_xg`/`away_xg` de bază: `offensive_rating * def_mod_advers * baseline * (form_weight*form_mod + dna_weight) * home_advantage/away_penalty`
2. **DACĂ** `h2h_meetings >= 2`: `home_xg *= (1+h2h_modifier)`, `away_xg *= (1-h2h_modifier)` (opus, simetric)
3. **DACĂ** `weather_penalty > 0`: ambele xG `*= (1-weather_penalty)` — **egal pe ambele echipe**, nu diferențiat (decizie de design, nu bug — vremea afectează terenul, nu o echipă anume)
4. Podea: `max(xg, 0.20)` pe ambele

### 5.2 — Injury penalty — pass SEPARAT, DUPĂ pasul de mai sus

```python
home_xg_new = max(home_xg * (1 + home_penalty), 0.20) if home_penalty < 0 else home_xg
```
Aplicat INDEPENDENT, per echipă (nu simetric ca H2H/weather) — logic corect (absențele unei echipe n-au legătură cu ale celeilalte), dar înseamnă că podeaua de 0.20 e aplicată de DOUĂ ORI în lanț (o dată în `calibrate_xg`, o dată aici) — inofensiv (max cu aceeași valoare), dar redundant.

### 5.3 — Regulă de vreme (`oracle_api.py:1471-1484`) — set complet de praguri hardcodate

| Condiție | Penalizare |
|---|---|
| ploaie/ninsoare severă (heavy rain/torrential/blizzard/thunderstorm/sleet/freezing) | +8% |
| ploaie ușoară/burniță | +4% |
| ninsoare | +6% |
| precipitații >15mm | +4% |
| precipitații 5-15mm | +2% |
| vânt >70km/h | +4% |
| vânt 50-70km/h | +2% |
| temp <0°C | +3% |
| temp >38°C | +2% |
| **Plafon total** | **15%** |

Aditiv (mai multe condiții se pot cumula, ex. ploaie + vânt), plafonat la final. Nicio sursă de ablație/calibrare citată pentru aceste praguri specifice.

### 5.4 — Regulă de impact per jucător absent (`injury_manager.py:94-115`)

```python
mv_norm = log10(max(market_value, 100_000) + 1) / log10(150_000_000 + 1)
penalty = min(mv_norm * POSITION_WEIGHTS[pos] * certainty * 0.25, 0.18)   # cap per jucător
total   = max(sum(penalties), -0.30)                                       # cap per echipă
```
`certainty` vine din text liber parsat (`_EXPECTED_RETURN_CERTAINTY`, 13 pattern-uri hardcodate: „doubtful"→0.50, „a week"→0.95, „suspended"→1.0, etc.) — fragil la variații de formulare din sursa de date (FreeLF), fără fallback structurat dincolo de default 0.80.

---

## 6. Reguli duplicate / locuri unde aceeași informație e penalizată (sau bonusată) de două ori

### 6.1 — `avg_goals_for` intră de două ori în `off_stat` (CONFIRMAT, cel mai clar caz)

```python
off_stat = min(g_norm*goals_weight + sot_norm*shots_ot_weight + pos_norm*possession_weight + avg_goals_for*0.2, offensive_cap)
```
`g_norm` derivă DEJA din `avg_goals_for` (capat la 2.0/meci, ponderat cu `goals_weight`, implicit 0.45). Termenul final, `+ avg_goals_for*0.2`, adaugă din nou aceeași valoare brută, NECAPATĂ, cu o pondere `0.2` complet separată de sistemul configurabil `weights` (nu există `goals_bonus_weight` sau echivalent în `DEFAULT_WEIGHTS`). Efect practic: o echipă cu `avg_goals_for` mare (ex. 3.0/meci) primește un bonus semnificativ prin al doilea termen, necontrolat de `goals_weight` și necapat de aceeași logică ca primul termen — la meciuri cu marcaj foarte ridicat, contribuția goluri-per-meci la `off_stat` poate depăși intenția aparentă a `goals_weight=0.45`.

### 6.2 — Trei concepte diferite, același nume „Team DNA" (confuzie, nu duplicare funcțională)

1. **UI „Team DNA"** (`app.py`, cardul OFF/DEF/Formă/ELO) — afișează `TeamProfile` (off/def rating, form_score, elo_rating) — ACESTEA intră în predicție.
2. **`dna_weight`** (`weights.json`) — constantă în formula `calibrate_xg`, NU corespunde niciunui semnal „DNA" real (§3).
3. **„Team DNA Flashscore"** (`home_flashscore_dna`) — xG real/posesie reală/etc., PUR informativ, NU intră în predicție (§2.2).

Nu e o dublă penalizare a datelor — e un risc real de confuzie terminologică pentru orice dezvoltator/audit viitor care presupune că cele trei sunt legate.

### 6.3 — Formă (rezultate W/D/L) vs. rating ofensiv/defensiv (goluri) — NU e duplicare, dar aceeași fereastră de date

`form_score` (din `results`, ultimele `last_n_fixtures`) și `avg_goals_for/against` (din `stats`, aceleași `last_n_fixtures`) provin din ACELEAȘI meciuri recente, dar reprezintă aspecte diferite (rezultat W/D/L vs. scor brut) — nu e o duplicare literală a informației (o echipă poate marca mult și totuși pierde), dar ambele semnale sunt derivate din aceeași fereastră temporală mică (5 meciuri), ceea ce limitează diversitatea reală a semnalului de intrare — relevant pentru Etapa 4, nu o „eroare" de raportat aici.

### 6.4 — Podea (`max(xg, 0.20)`) aplicată de două ori în lanț (§5.2)

Inofensiv funcțional (idempotent), dar semnalează că injury penalty a fost adăugat ca pass separat, ulterior, fără să refactorizeze cascada originală — consistent cu disciplina „no defect, no rewrite" a proiectului, dar merită menționat ca artefact de evoluție incrementală.

---

## 7. Reguli istorice care pot fi eliminate (cod mort confirmat, nu presupus)

| Element | Fișier | Dovadă | Recomandare |
|---|---|---|---|
| `get_injury_report_from_cache()` | `injury_manager.py:267-296` | Zero apelanți găsiți în tot repo-ul (grep exhaustiv) | Candidat clar pentru eliminare — nicio cale de producție sau test nu-l atinge |
| `ABSENCE_CERTAINTY` (dict) | `injury_manager.py:36-39` | Folosit DOAR în `get_injury_report_from_cache()` (mort) | Elimină odată cu funcția de mai sus |
| `_impact_label()` (bazat pe minute) | `injury_manager.py:134-137` | Zero apelanți — calea live folosește `_impact_label_from_market_value()` | Candidat pentru eliminare |
| `MIN_STARTER_MINUTES`/`MIN_KEY_PLAYER_MINUTES` | `injury_manager.py:51-52` | Folosite DOAR de `_impact_label()` (mort) | Elimină odată cu funcția de mai sus |
| `get_lineup_absences()` | `injury_manager.py:140-188` | NU e apelată de `oracle_engine.py` (migrat la Database-First, R-Sync-10, confirmat prin comentariu explicit + test dedicat `test_oracle_engine_single_profile_construction_point.py`) — DAR încă folosită de teste de paritate (`test_injury_manager_db_first.py`) | **NU e cod mort** — păstrează, dar documentează explicit rolul (parity-testing, nu cale live) |
| `rest_days_modifier()` | `feature_engine.py:108-127` | Neapelat, respins explicit prin ablație (§2.3) | **NU recomand ștergere** — păstrat deliberat ca funcție pură documentată, precedent util pentru viitoare teste de ablație similare |
| `h2h_lookback_days` (config) | `DEFAULT_CONFIG` | **Confirmat cod mort și ELIMINAT, 2026-08-03** (EPIC ML Activation, Pasul 4) — grep exhaustiv pe tot repo (`.py`, inclusiv `sync/`): singurele apariții erau definiția din `DEFAULT_CONFIG` și `tests/test_oracle_engine_compat.py:18` (test de regresie pe forma dict-ului, nu citire funcțională). Verificat integral `_build_h2h()`/`_h2h_record_from_history_rows()` (toate cele 3 cascade — DB, FreeLF, Odds API): niciuna nu citea `h2h_lookback_days`, doar `h2h_weight` | **Eliminat** — cheia scoasă din `DEFAULT_CONFIG` (`oracle_engine.py`) și din testul de regresie asociat, regresie completă verde |

---

## 8. Ce NU a fost găsit (verificat, nu ignorat)

- Nicio altă dublă-penalizare clară dincolo de §6.1 (goluri marcate) — verificat sistematic fiecare intrare în `calibrate_xg`/`compute_team_offdef_rating`.
- Home advantage aplicat o singură dată, coerent (nu există un al doilea bonus „acasă" ascuns altundeva în ELO sau Poisson).
- Weather penalty aplicat o singură dată, simetric, corect.

---

## 9. Rezumat pentru Etapa 4 (roadmap) — puncte de decizie identificate aici

1. `avg_goals_for` dublu-contorizat în `off_stat` (§6.1) — **investigat complet 2026-08-03** (EPIC ML Activation, Pasul 8), **cod NEATINS, decizie deliberată**: bugul rămâne confirmat și nerezolvat în cod. Eliminarea simplă degradează Oracle (backtest, 4849 meciuri); compensarea validată (recalibrare `goals_weight` 0.45→0.75) există și e documentată ca „Oracle Insight" (`docs/03_ENGINE/ORACLE_INSIGHT_GOALS_WEIGHT.md`), dar **nu a fost aplicată** — orice modificare a parametrilor matematici Oracle e tratată ca experiment de calibrare separat, cu propria aprobare, niciodată bundle-uit în task-ul de fix. Follow-up: **FOLLOW-UP-P8-01 — Oracle Calibration (`goals_weight`)**, task separat, neînceput.
2. Ponderile per-ligă sunt complet inerte azi (`sample_count=0` peste tot, `auto_recalibration_enabled` implicit oprit) — necesită decizie: activare (cu monitorizare), sau eliminare a diferențierii per-ligă dacă nu se dorește activarea.
3. `dna_weight` — nume derutant, fără semnal real de „DNA" în spate — necesită decizie: redenumire (schimbare de contract, ADR necesar) sau documentare clară.
4. 5 elemente de cod confirmat mort în `injury_manager.py` (§7) — candidați pentru curățare, risc zero (zero apelanți).
5. Discrepanță docstring/cod (0.20 vs. 0.25, §4.5) — corecție minoră de documentație.

Niciuna din aceste decizii nu e luată aici — acest document doar constată, cu dovadă.
