# Shadow Probe — ghid operațional

**Status**: utilitar **permanent**, operațional. NU e un POC, NU e un
script one-shot — rămâne în repo la nesfârșit, disponibil pentru orice
verificare viitoare. Nu se șterge după prima rulare.

**Fișiere**: `scripts/shadow_probe.py` (cod), `.github/workflows/shadow_probe.yml`
(rulare prin GitHub Actions, `workflow_dispatch`).

**Origine**: Pasul 14 (derivat din ADR-050) — vezi
`docs/00_GOVERNANCE/PASUL14_ACTIVATION_REPORT.md` pentru prima lui
utilizare reală, la activarea shadow logging-ului pentru Challenger-ul
Blend.

## Scopul utilitarului

`oracle_engine.evaluate_match()` — singurul punct care declanșează orice
shadow logging (`_log_challenger_shadow()`, `_log_blend_challenger_shadow()`,
și orice mecanism similar viitor) — rulează azi DOAR din UI-ul Streamlit,
la interacțiune reală de utilizator. Nu există niciun job programat
(`daily.yml`, `night_sync.yml`) care să-l apeleze. Fără acest tool,
confirmarea că un shadow logging nou activat chiar produce date ar depinde
exclusiv de trafic organic imprevizibil.

Shadow Probe injectează, controlat, un număr mic de meciuri prin calea
REALĂ de producție (`FootballOracleEngine.evaluate_match()`), folosind
echipe/ligă reale (dintr-un meci deja terminat, ales aleator din
`match_history`), dar cu `fixture_id`/`kickoff_date` sintetice, izolate.
Raportează, per meci probat: predicția Oracle produsă și exact ce rânduri
au apărut în `shadow_predictions` pentru acel `fixture_id`.

**Generic** — nu e specific niciunei familii de algoritm. Nu citește, nu
scrie niciun flag `*_shadow_logging_enabled`. Orice shadow logging deja
activ în `model_config` (xgboost_v1, blend_v1, sau o familie viitoare) se
declanșează singur, exact ca la trafic real.

## Când se folosește

- Imediat după activarea unui flag nou de shadow logging (ca la Pasul 14),
  pentru dovadă reală, nu doar structurală, că mecanismul chiar scrie date.
- Oricând există suspiciunea că un shadow logging activ a încetat să
  funcționeze (de ex. după o refactorizare a `oracle_engine.py` sau a
  modulelor `learning_core.*_shadow`).
- Pentru diagnostic operațional rapid, fără a aștepta trafic real de
  utilizator sau următorul cron.

## Când NU se folosește

- Nu e un instrument de evaluare statistică — `shadow_testing.evaluate_experiment()`
  rămâne singura sursă pentru verdicte de tip `candidate_for_promotion`.
  Rândurile produse de Shadow Probe sunt meciuri fictive (fără rezultat
  real posibil) — vezi mai jos de ce sunt structural invizibile pentru
  orice evaluare.
- Nu e un mecanism de creare de Challenger — nu importă
  `learning_core.challenger_manager`/`learning_core.promotion_service`.
- Nu se folosește pentru a genera volum artificial de "date de antrenare"
  — rândurile create nu au niciodată `actual_result`, deci sunt excluse
  structural din orice pipeline de antrenare (vezi Invariant 2 mai jos).

## Invariant 1 — Idempotență la rulări repetate

Fiecare probă primește un `fixture_id` nou (`shadow-probe-<uuid8>`, generat
la fiecare apel al `build_probe_match()`) — **niciodată același ID de două
ori**, chiar dacă se aleg din nou aceleași echipe sursă. Consecință
directă:

- **Nicio suprascriere**: rularea de 10 ori a tool-ului NU produce 10
  actualizări ale aceluiași rând — fiecare rulare scrie rânduri complet
  noi, distincte.
- **Nicio ambiguitate**: fiecare rând (`match_history` + `shadow_predictions`)
  e atribuibil fără dubiu unei singure execuții, prin `fixture_id`-ul unic.
- **Acumulare intenționată, nu bug**: rulările repetate ACUMULEAZĂ rânduri
  noi, cu prefixul `shadow-probe-`, nelimitat în timp. Asta e comportamentul
  AȘTEPTAT al unui instrument de diagnostic — fiecare rulare lasă o urmă
  verificabilă. Volumul e mic și predictibil (limitat de `--limit`,
  implicit 3, folosit manual/rar), nu un risc de creștere necontrolată.
  Auditarea acestei acumulări e disponibilă oricând prin `--list-probes`
  (vezi Invariant 3).

## Invariant 2 — Izolare totală față de producție (verificat prin cod)

Niciun dashboard, raport sau proces de învățare nu poate consuma rândurile
produse de Shadow Probe ca date reale — verificat direct în cod, nu
presupus:

1. **`upsert_match_history()` nu cheie pe `fixture_id`** — rutează prin
   RPC-ul `upsert_match_canonical`, care face lookup pe CHEIA NATURALĂ
   normalizată `(home_team, away_team, kickoff_date)`. De aceea
   `kickoff_date` e o constantă sentinelă fixă (`2099-01-01`, viitor
   îndepărtat, niciodată o dată reală) — garantează că orice probă produce
   întotdeauna un rând NOU în `match_history`, niciodată o suprascriere
   peste un meci real.
2. **Rândurile create nu au NICIODATĂ `actual_result`** — sunt meciuri
   fictive; nimeni nu va raporta vreodată un scor real pentru
   `shadow-probe-xxx`. Verificat direct: fiecare consumator relevant din
   cod filtrează explicit `actual_result IS NOT NULL` (14+ locuri
   confirmate prin grep în `supabase_client.py`/`database/queries.py`,
   inclusiv `get_training_data()` — sursa antrenării ML,
   `get_team_recent_results()` — sursa formei echipei folosită de
   `_build_profile()`, `get_matches_by_league()`, și raportul de evaluare
   `prediction_evaluation.build_evaluation_report()`, citit din
   `app.py`). Un rând fără `actual_result` e structural invizibil pentru
   toate aceste căi — nu doar convențional, ci prin filtrul SQL însuși.
3. **`kickoff_date` sentinelă (2099) exclude proba din sincronizarea de
   rezultate** — `get_matches_missing_results()` (ținta reală a
   `sync/sync_results.py`) filtrează explicit `kickoff_date < azi` — o
   dată din 2099 e mereu în afara ferestrei, deci `sync_results.py` nu va
   încerca niciodată să "rezolve" o probă ca pe un meci real.
4. **Forma echipei nu e afectată** — `get_team_recent_results()` (sursa
   canonică pentru `_build_profile()`) filtrează pe ceasul real
   (`datetime.now()`), nu pe `kickoff_date`-ul meciului de prezis, ȘI
   cere `actual_result IS NOT NULL` — o probă nu poate deveni niciodată
   "formă recentă" pentru nicio echipă, reală sau fictivă.

## Invariant 3 — Curățenie operațională (decizie explicită)

**Decizie**: rândurile create de Shadow Probe **rămân intenționat în baza
de date** — tool-ul NU șterge niciodată nimic, nu există cleanup automat.
Motivare: (a) izolarea de mai sus le face inerte pentru orice consumator
real, deci absența unui cleanup nu are cost funcțional; (b) ștergerea din
date live e o operație distructivă care, per regulile Supabase din
`CLAUDE.md`, necesită oricum confirmare explicită separată de fiecare
dată — nu se automatizează "din oficiu".

Auditarea rândurilor acumulate e disponibilă oricând, read-only, prin:
```bash
python scripts/shadow_probe.py --list-probes
```
(sau workflow-ul GitHub Actions, input `list_probes="yes"`) — listează
toate rândurile din `match_history` și `shadow_predictions` cu prefixul
`shadow-probe-`, cu `created_at`, pentru revizuire umană oricând. O
ștergere efectivă, dacă e dorită vreodată, rămâne o decizie separată,
explicită, executată manual (SQL arătat înainte de rulare, per
supabase-safety), nu o funcție a acestui tool.

## Invariant 4 — Nu e un test temporar

Acest document + cele două fișiere de cod sunt parte permanentă a
infrastructurii operaționale a proiectului, la fel ca
`scripts/rerun_etapa3_benchmark.py` sau `learning_core/run_continuous_learning.py`.
Nu se șterg după prima rulare. Orice extindere viitoare (alți parametri,
alte moduri de audit) se face prin editarea acestor fișiere, nu prin
crearea unui nou script paralel.

## Garanții de izolare — rezumat rapid

1. `fixture_id` are întotdeauna prefixul `shadow-probe-`.
2. `kickoff_date` = constanta sentinelă `2099-01-01`.
3. Echipe/ligă reale (profil realist), dar niciodată `actual_result`.
4. Nu importă `learning_core.challenger_manager`/`promotion_service`.
5. `--confirm` (CLI) / input `confirm="yes"` (GitHub Actions) obligatoriu
   pentru orice scriere reală — implicit: doar afișează planul, iese.

## Cum se rulează

**GitHub Actions (recomandat — secretele reale de producție)**:
Actions → "Football Oracle — Shadow Probe" → Run workflow →
- `limit` (implicit 3), `confirm="yes"` pentru execuție reală (orice altă
  valoare = dry-run, doar plan).
- `list_probes="yes"` pentru audit read-only al rândurilor acumulate până
  acum (ignoră `limit`/`confirm`).

**Local** (necesită `SUPABASE_URL`/`SUPABASE_SECRET_KEY` în mediu):
```bash
python scripts/shadow_probe.py --limit 3              # dry-run, doar plan
python scripts/shadow_probe.py --limit 3 --confirm    # execuție reală
python scripts/shadow_probe.py --list-probes          # audit read-only
```

## Ce NU face

- Nu activează/dezactivează niciun flag de configurare.
- Nu creează/antrenează niciun Challenger.
- Nu promovează, nu execută rollback.
- Nu șterge nimic — vezi Invariant 3.
