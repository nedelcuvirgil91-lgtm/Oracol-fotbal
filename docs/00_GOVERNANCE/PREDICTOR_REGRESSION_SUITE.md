# Predictor Regression Suite

**Status**: ACTIV, obligatoriu la merge (CI, `.github/workflows/predictor_regression_suite.yml`).

**Aprobat de**: proprietarul produsului, 2026-08-03 (EPIC „Functional Completion", Punctul 2).

**Fișiere**:
- `tests/predictor_regression_scenarios.py` — cele 20 de scenarii golden + harness-ul care rulează `FootballOracleEngine.evaluate_match()` real, complet mock-uit.
- `tests/predictor_regression_golden.json` — snapshot-ul înghețat (`home_xg`, `away_xg`, `ph`, `pd`, `pa` pentru fiecare din cele 20 de meciuri).
- `tests/test_predictor_regression_suite.py` — testul care rulează cele 20 de scenarii și compară cu snapshot-ul.
- `scripts/generate_predictor_regression_golden.py` — singurul mod acceptat de a regenera `predictor_regression_golden.json`.

---

## De ce există

Până la acest EPIC, nicio schimbare la `oracle_engine.py`, `feature_engine.py` sau la structura bazei de date (`match_history`, cascadele Database-First ADR-035) nu putea fi verificată automat pentru drift — testele existente acopereau bucăți interne (`_build_profile`, `_build_h2h`, cascade individuale), niciunul nu rula punctul de intrare real de producție (`evaluate_match()`) capăt-la-capăt și nu compara ieșirea numerică finală cu o bază de referință.

Suita asta închide exact acel gol: **orice modificare viitoare la calea de predicție trebuie să producă exact aceleași `home_xg`/`away_xg`/`ph`/`pd`/`pa`** pentru cele 20 de meciuri golden, sau testul eșuează explicit — silențios nu mai e o opțiune.

Cele 20 de meciuri (`tests/predictor_regression_scenarios.py`) acoperă deliberat:
- 10 ligi diferite (baseline-uri de gol diferite, `league_baselines`);
- cele 3 nivele de calitate a datelor din ADR-035 D4: **LIVE** (formă recentă reală, ≥3 meciuri DB), **ELO-only** (fără formă, doar ELO), **NEUTRAL** (echipă complet necunoscută);
- dinamici variate: favorit clar acasă/deplasare, meciuri strânse, semnale contradictorii (ELO mare + formă slabă), istoric H2H real vs. inexistent.

## Cum se rulează

```bash
pytest tests/test_predictor_regression_suite.py -v
```

Rulează automat la fiecare `push`/`pull_request` către `main` (`.github/workflows/predictor_regression_suite.yml`) — **obligatoriu**, nu opțional. Scopul CI e deliberat îngust — doar acest fișier de test, NU `pytest tests/` complet (vezi nota din workflow: suita completă are azi 3 eșecuri preexistente, necorelate, în `tests/test_oracle_api_tsdb_per_league_gate.py`; un gate pe toată suita ar fi permanent roșu din motive din afara acestui EPIC).

## Cum se regenerează snapshot-ul — și, mai important, când NU se regenerează

```bash
python scripts/generate_predictor_regression_golden.py
```

**Regula, fără excepție**: snapshot-ul (`tests/predictor_regression_golden.json`) se regenerează **DOAR** atunci când o schimbare la algoritmul Predictorului (Oracle Engine/feature_engine.py) e **intenționată și aprobată explicit** de proprietarul produsului — exact ca orice altă schimbare de comportament în calea de predicție (vezi CLAUDE.md, „Regulile ADR" și „Nu modifica Oracle Engine fără aprobare").

**Un test picat NU justifică regenerarea.** Dacă `test_prediction_matches_golden_snapshot` eșuează:
1. Diferența trebuie înțeleasă întâi — ce schimbare de cod a produs-o, e intenționată?
2. Dacă schimbarea NU era intenționată (regresie reală) → se repară codul, nu snapshot-ul.
3. Dacă schimbarea ERA intenționată și aprobată → **abia atunci** se rulează scriptul de regenerare, iar noul `predictor_regression_golden.json` intră în același commit/PR care conține schimbarea de algoritm aprobată (niciodată separat, niciodată „în tăcere").

Cine are voie să regenereze: oricine implementează o schimbare aprobată explicit a algoritmului Predictorului, ca parte a acelei schimbări — niciodată ca reacție automată la un test roșu, niciodată ca „curățenie" separată.

## Ce NU acoperă (deliberat, nu ascuns)

- Injurii, vreme, Team DNA Flashscore, blend ML — dezactivate uniform în toate cele 20 de scenarii (`injury_manager=None`, `venue_city` omis, `FLASHSCORE_TEAM_DNA_AVAILABLE=False`, `ml=None`). Scopul suitei e precizia predicției de bază Poisson/ELO/formă, nu fiecare ramură secundară — o extindere separată, dacă devine necesară, ar adăuga scenarii dedicate, nu ar redefini scopul acestei suite.
- Value bets/Kelly/edge — nu fac parte din snapshot (doar `home_xg`/`away_xg`/`ph`/`pd`/`pa`, exact cerința explicită a EPIC-ului).
