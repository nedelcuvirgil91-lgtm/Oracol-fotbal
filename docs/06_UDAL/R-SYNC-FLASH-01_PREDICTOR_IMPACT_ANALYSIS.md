# R-Sync-FLASH-01 — Analiză de Impact asupra Predictorului și ML

**Status**: document de analiză, nu implementare. **Predictor-ul (`oracle_engine.py`) NU a fost modificat** ca urmare a acestui document, cf. cerință explicită ("Nu modifica încă Predictorul").
**Cerut**: "Înainte să conectezi Predictorul la tabelele noi, vreau un document separat care explică: ce câmpuri noi vor fi folosite; cum cresc feature-urile ML; ce impact estimezi asupra acurateții; ce impact asupra timpului de inferență."

---

## 1. Ce câmpuri noi vor fi folosite

Important de separat corect — **niciun feature nou** nu se introduce în `FEATURE_COLUMNS` (`ml_predictor.py`) ca urmare a R-Sync-FLASH-01. Flashscore completează **datele brute din spatele unor feature-uri deja acceptate prin ablație**, nu adaugă coloane noi la modelul ML. Distincție importantă față de regula CLAUDE.md ("Feature nou în FEATURE_COLUMNS doar cu dovadă de ablație") — aici nu e vorba de feature nou, e vorba de **completare de gol de date pentru un feature deja aprobat**.

| Tabelă/coloană | Folosită de | Cum |
|---|---|---|
| `match_history.home/away_corners`, `home/away_fouls`, `home/away_shots`, `home/away_yellow_cards` (deja existente, migrația 026, acum și gap-fill Flashscore) | `sync/backfill_features.py` (antrenare) + `oracle_engine.py::_build_ml_features()` (predicție live) | Sursă brută pentru `corner_dominance`, `card_diff`, `foul_diff`, `shot_dominance` — deja în `FEATURE_COLUMNS`, promovate prin ablație (ADR-012, ADR-013, ADR-021). |
| `match_history.home/away_goalkeeper_saves` (coloană nouă, migrația 032) | Niciunul azi | Nu e folosită de niciun feature existent — pur informativă/viitoare, fără promovare prin ablație. |
| `player_match_stats`, `match_events` | Niciunul azi | Genuin noi, fără consumator ML — populare fără consum, decizie conștientă (documentată deja în design). |
| `odds_fallback_flashscore` | Predictor (value betting/de-vig), NU ML training | Fallback la calculul de cotă, nu la niciun `FEATURE_COLUMNS`. |
| `upcoming_matches`/`upcoming_lineups`/`upcoming_match_features` | Niciunul azi | Predictor nu citește încă din ele (neschimbat de acest document). |

## 2. Cum cresc feature-urile ML — mecanismul exact, verificat în cod

Dovada, nu presupunerea (citire directă de cod, nu documentație):

- **Antrenare**: `sync/backfill_features.py` — `FoulsTracker`, `ShotsTracker`, un tracker analog pentru cornere/cartonașe — citesc direct `match.get("home_corners")`, `match.get("home_fouls")`, `match.get("home_shots")` etc. (liniile 947-951) din `match_history` și calculează mediile mobile `home/away_corner_avg_recent`, `home/away_card_avg_recent`, `home/away_foul_avg_recent`, `home/away_shot_avg_recent`. `ml_predictor.py` (liniile 198-215) transformă aceste medii în `corner_dominance`/`card_diff`/`foul_diff`/`shot_dominance` — **dacă oricare din coloanele brute lipsește, feature-ul respectiv devine `np.nan`** (liniile 201/205/210/215), nu zero, nu o valoare presupusă — XGBoost tratează nativ `NaN` ca "informație lipsă" la split, nu ca zero.
- **Predicție live**: `oracle_engine.py::_build_ml_features()` (liniile 1289-1324) calculează **aceleași 4 feature-uri**, dar din `home_p.avg_corners`/`away_p.avg_corners` etc. — proprietăți ale profilului de echipă construit din meciurile recente reale, aceeași sursă brută (`match_history`), cale de cod diferită (live, nu batch), aceeași dependență de completitudine.

**Verificare reală, nu presupusă** (interogare directă, read-only, pe schema live — 1487 meciuri SuperLiga cu rezultat cunoscut, toate sezoanele istorice, filtrate după nume de echipă): **1485/1487 (99,87%) au `home_corners`/`home_fouls`/`home_shots`/`home_yellow_cards`/`referee` = `NULL`**; **1487/1487 (100%) au `home_goalkeeper_saves` = `NULL`** (coloană nou-creată, așteptat). Consecință directă: pentru aproape orice meci SuperLiga, azi, cele 4 feature-uri `corner_dominance`/`card_diff`/`foul_diff`/`shot_dominance` sunt `NaN` — atât la antrenare, cât și la predicție live — indiferent cât de bune sunt ELO/formă/H2H pentru acele rânduri.

**Consecință a bootstrap-ului**: completarea acestor coloane brute pentru SuperLiga (bootstrap, apoi Night Sync) transformă acele 4 feature-uri din `NaN` sistematic în valori reale, pentru **atât** antrenare **cât și** predicție live — nu doar unul din cele două fluxuri.

## 3. Impact estimat asupra acurateției

**Onest, nu presupus** — conform filosofiei proiectului ("Verificat, nu presupus"), acest document **nu afirmă** un procent de îmbunătățire. Ce se poate spune, cu dovadă:

- Cele 4 feature-uri (`corner_dominance`, `card_diff`, `foul_diff`, `shot_dominance`) au fost deja promovate prin teste de ablație walk-forward reale, separate, fiecare cu magnitudine mică dar pozitivă și raportată onest (`shot_dominance`: Δacc +0,0046, Δlog-loss -0,0062, Δbrier -0,0047, măsurat pe 5.253 meciuri, `docs/03_ENGINE/SHOT_DOMINANCE_ABLATION_2026-07-15.md`). Aceste cifre sunt însă măsurate pe **populația generală** de meciuri (multi-ligă), nu specific pe SuperLiga.
- Pentru SuperLiga specific, azi, aceste 4 feature-uri sunt aproape 100% `NaN` — deci **contribuția lor reală la predicțiile SuperLiga de azi e efectiv zero**, indiferent de câștigul mediu măsurat cross-ligă. Umplerea golului nu poate face predicțiile SuperLiga mai rele pe aceste 4 dimensiuni (nu existau înainte), dar **magnitudinea exactă a îmbunătățirii pentru SuperLiga specific rămâne necunoscută** până la măsurare reală.
- **Recomandare, consistentă cu disciplina ADR-012/013/021**: după ce bootstrap-ul SuperLiga se finalizează (ultimul sezon complet), rulează un test de ablație/re-evaluare walk-forward dedicat, **doar pe subsetul SuperLiga**, comparând acuratețe/log-loss/Brier înainte/după completare — nu se presupune un rezultat, se măsoară. Acest pas **nu face parte** din scope-ul actual (design + Stage 1 schema) — e recomandarea pentru momentul în care bootstrap-ul chiar rulează.

## 4. Impact estimat asupra timpului de inferență

- **Azi (acest document, Stage 1 aplicat)**: **zero** — `oracle_engine.py` nu a fost modificat, nu există nicio interogare nouă adăugată la calea de predicție live.
- **După o eventuală conectare viitoare** (task separat, neînceput):
  - Feature-urile de mai sus (corner/card/foul/shot dominance) **nu adaugă nicio interogare nouă** — `_build_ml_features()` deja citește profilul de echipă (`home_p`/`away_p`) din surse existente; completarea datelor brute nu schimbă numărul de query-uri, doar conținutul lor (mai puține `NULL`).
  - **Odds fallback** (`odds_fallback_flashscore`): ar necesita o interogare Supabase suplimentară, **doar quando** `odds_history` nu are niciun rând pentru fixture-ul respectiv (cale rară, nu comună) — o singură interogare indexată pe cheie unică `(fixture_id, bookmaker)`, cost tipic sub-100ms pe o tabelă mică, neglijabil față de restul căii de predicție (Poisson/Monte Carlo, deja mai costisitoare). Nu se activează implicit — cerut explicit ca task separat de acest document.
  - `upcoming_matches`/`upcoming_lineups`/`upcoming_match_features` — nefolosite încă de Predictor; impactul de timp e strict `0` până la conectare, ne-estimabil precis înainte (depinde de designul concret al interogării, neproiectat încă).

## 5. Ce NU s-a schimbat ca urmare a acestui document

- Niciun rând de cod în `oracle_engine.py`, `ml_predictor.py`, `feature_engine.py`.
- Niciun test de ablație nou rulat (recomandat, nu executat — vezi §3).
- Nicio migrare Supabase nouă.
- `FEATURE_COLUMNS` neschimbat.
