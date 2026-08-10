# Football Oracle

Platformă personală de predicție și analiză a pariurilor pe fotbal, combinând modelare statistică (ELO, distribuție Poisson, simulare Monte Carlo), machine learning (XGBoost) și analiză de piață (value betting, de-vig) pentru identificarea oportunităților de pariere cu valoare reală.

> **Disclaimer**: acest proiect e un instrument personal de analiză statistică, nu un serviciu de consultanță financiară sau de pariuri. Niciun rezultat generat de acest sistem nu constituie o garanție de câștig. Pariurile sportive implică risc financiar real — folosește acest instrument pe propria răspundere.

---

## Cuprins

- [Arhitectură](#arhitectură)
- [Stack tehnologic](#stack-tehnologic)
- [Structură foldere](#structură-foldere)
- [Instalare](#instalare)
- [Configurare Supabase](#configurare-supabase)
- [Configurare API Keys](#configurare-api-keys)
- [GitHub Actions](#github-actions)
- [Rulare locală](#rulare-locală)
- [Troubleshooting](#troubleshooting)
- [Roadmap](#roadmap)
- [Guvernanță și documentație tehnică](#guvernanță-și-documentație-tehnică)

---

## Arhitectură

Fluxul de date urmează un lanț determinist:

```
Provideri externi (odds, meciuri, vreme, ELO)
        │
        ▼
Ingestie + normalizare (cache L1 disc + L2 Supabase)
        │
        ▼
Feature engineering (ELO, formă, H2H, rating ofensiv/defensiv)
        │
        ▼
Poisson model → Monte Carlo (10k simulări) → blend ML (XGBoost)
        │
        ▼
Calibrare cote (de-vig) → Value Betting Engine
        │
        ▼
Prediction (Streamlit UI) + Persistare (Supabase)
```

Componente principale:
- **`oracle_api.py`** — strat unificat de acces la toate sursele externe de date (meciuri, cote, vreme, ELO), cu cache pe două niveluri și fallback automat între provideri.
- **`oracle_engine.py`** — motorul de predicție propriu-zis: Poisson, Monte Carlo, blend ML, de-vig, value betting, Kelly staking.
- **`ml_predictor.py`** — model XGBoost, antrenat cu validare temporală (walk-forward, expanding window) pe istoricul de meciuri.
- **`services/odds_persistence_service.py`** — persistare istorică a cotelor de piață (opening/closing), guvernată de un contract de arhitectură dedicat (vezi `docs/03_ENGINE/ODDS_PERSISTENCE_DESIGN.md`).
- **`sync/`** — job-uri de sincronizare (meciuri, rezultate, ELO, cote), orchestrate zilnic/săptămânal prin GitHub Actions.
- **`shadow_testing.py`** — infrastructură de experimentare offline (A/B testing de feature-uri noi, fără impact asupra producției, până la validare statistică).

## Stack tehnologic

| Componentă | Tehnologie |
|---|---|
| UI | Streamlit |
| Bază de date | Supabase (PostgreSQL) |
| ML | XGBoost, scikit-learn |
| Date numerice | pandas, numpy, scipy |
| HTTP/scraping | requests, BeautifulSoup4 |
| Import istoric | kagglehub |
| Orchestrare | GitHub Actions |
| Limbaj | Python 3.11 |

**Provideri de date externi**: The Odds API (cote), football-data.org, Free Live Football (RapidAPI), ESPN, TheSportsDB, eloratings.net (ELO național), WeatherAPI, API-Football (accidentări/antrenori).

## Structură foldere

```
Oracol-fotbal-main/
├── app.py                       # Interfața Streamlit
├── oracle_api.py                 # Strat unificat de acces la surse externe
├── oracle_engine.py               # Motor de predicție (Poisson/MC/ML/value betting)
├── ml_predictor.py                # Model XGBoost + walk-forward validation
├── mappings.py                    # Normalizare nume echipe/ligi, alias-uri
├── cache_manager.py               # Cache L1 (disc) + L2 (Supabase)
├── key_manager.py                 # Gestiune chei API + cote de utilizare
├── feature_engine.py              # Calcul formă, H2H, rest days
├── football_providers.py         # Provider API-Football (injuries/coaches)
├── injury_manager.py              # Gestiune rapoarte de accidentări
├── recalibration.py                # Recalibrare ponderi per ligă (legacy)
├── shadow_testing.py              # Infrastructură de experimentare offline
├── supabase_client.py              # Client Supabase + query-uri de nivel înalt
├── services/
│   └── odds_persistence_service.py # Persistare istorică cote (opening/closing)
├── sync/                          # Job-uri de sincronizare (meciuri, rezultate, ELO)
│   └── sources/                   # Adaptoare per provider (football-data, kaggle, openfootball)
├── database/
│   ├── queries.py                 # Interogări structurate Supabase
│   └── migrations/                # Migrări SQL (schema, trigger-e, funcții RPC)
├── docs/
│   ├── 00_GOVERNANCE/              # ADR-uri, registru de documente Frozen
│   └── 03_ENGINE/                  # Specificații tehnice de design (Frozen)
├── architecture/                  # ADR-uri istorice (V3)
├── tests/                         # Suită de teste (fără dependință de rețea)
└── .github/workflows/             # Automatizare GitHub Actions
```

## Instalare

```bash
git clone <repo-url>
cd Oracol-fotbal-main
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Configurare Supabase

1. Creează un proiect nou pe [supabase.com](https://supabase.com).
2. Rulează toate migrările din `database/migrations/`, în ordine numerică, în SQL Editor-ul din dashboard-ul Supabase.
   > **Notă**: la momentul acestui README, doar `001_odds_history.sql` există ca migrare versionată. Restul schemei (celelalte tabele) există deja în proiectul de producție, dar nu are încă migrări `.sql` corespunzătoare în repo — o bază de date nouă, creată de la zero, nu va avea automat toate tabelele. Vezi `docs/00_GOVERNANCE/` pentru context.
3. Obține din dashboard: **Project URL** și **Secret API Key** (format `sb_secret_...` — cheile noi Supabase au `BYPASSRLS` prin design, necesar pentru scrierile din job-urile de sincronizare).
4. Adaugă-le ca variabile de mediu (vezi secțiunea următoare).

## Configurare API Keys

Proiectul folosește mai multe chei API externe. Recomandat: variabile de mediu / `st.secrets` (Streamlit), nu hardcodare în cod.

| Serviciu | Variabilă | Obligatoriu |
|---|---|---|
| Supabase URL | `SUPABASE_URL` | Da |
| Supabase Secret Key | `SUPABASE_SECRET_KEY` | Da |
| The Odds API | `ODDS_API_KEY` | Da (cote) |
| WeatherAPI | `WEATHER_API_KEY` | Opțional (penalizare xG meteo) |
| RapidAPI (Free Live Football) | `RAPIDAPI_KEY` | Opțional (sursă primară meciuri) |
| API-Football | prin `key_manager.py` | Opțional (injuries/coaches) |
| football-data.org | prin `key_manager.py` | Opțional (fallback meciuri) |

> **Notă de securitate**: la momentul acestui README, câteva chei sunt încă hardcodate direct în `oracle_api.py` (moștenite dintr-o etapă anterioară a proiectului). Migrarea completă în `key_manager.py`/variabile de mediu e recomandată, dar nu blocantă pentru un repo privat.

## GitHub Actions

| Workflow | Declanșare | Scop |
|---|---|---|
| `daily.yml` | cron zilnic (03:00 UTC) + manual | Sincronizare meciuri/rezultate, recalculare ELO, evaluare experimente shadow, persistare cote, verificare/reantrenare ML |
| `weekly.yml` | cron săptămânal (Duminică 04:00 UTC) + manual | Sincronizare ELO echipe naționale (eloratings.net) |
| `backfill.yml` | manual | Recalculare istorică de feature-uri |
| `import_kaggle.yml` | manual | Import istoric inițial (Kaggle) |
| `bootstrap_league_learning.yml` | manual | Inițializare ponderi per ligă |
| `verify_freshness.yml` | manual/cron | Verificare prospețime dataset |
| `poc_statsapi.yml` | manual | Proof-of-concept (Sprint 0) |

Toate necesită secretele `SUPABASE_URL`/`SUPABASE_SECRET_KEY` configurate în **Settings → Secrets and variables → Actions** ale repo-ului.

## Rulare locală

```bash
streamlit run app.py
```

Rulare manuală a sincronizării zilnice (fără GitHub Actions):
```bash
python -m sync.run_daily
```

Rulare teste (nu necesită rețea sau credențiale reale):
```bash
python tests/_run_tests.py
```

## Troubleshooting

- **`ModuleNotFoundError` la `xgboost`/`sklearn`** — verifică `pip install -r requirements.txt` a rulat complet.
- **Streamlit arată "Supabase indisponibil"** — verifică `SUPABASE_URL`/`SUPABASE_SECRET_KEY` în `st.secrets` sau variabile de mediu.
- **Antrenarea ML pare lentă la fiecare pornire** — comportament cunoscut, actual (modelul se reantrenează la fiecare boot al procesului, nu e persistat ca artefact separat încă).
- **`odds_history` rămâne goală** — verifică dacă `shadow_mode`/persistarea de cote rulează efectiv în `run_daily.py` (Pasul 4/5) și dacă RLS/cheia service-role sunt configurate corect.
- **Segfault ocazional pe Streamlit Cloud** — problemă cunoscută, investigată extensiv, cauza nativă exactă neconfirmată (posibil presiune de memorie); fără soluție definitivă la acest moment.

## Roadmap

- Feature engineering: rest days *(evaluat, respins pe date — vezi `docs/03_ENGINE/REST_DAYS_VALIDATION.md`)*, injuries/coaching changes (colectate, în așteptare activare shadow testing).
- Migrarea completă a schemei Supabase în fișiere `.sql` versionate.
- Pensionarea completă a mecanismului legacy `recalibrate_weights()`, înlocuit cu un sistem de învățare guvernat prin shadow testing + backtest.
- Backtest complet + Benchmark V4.0 înghețat (Accuracy, Brier, Log-Loss, ROI, Yield, CLV) ca punct de referință oficial.

## Guvernanță și documentație tehnică

Documentele de arhitectură "Frozen" (contracte tehnice care nu se modifică decât prin ADR nou) se află în `docs/00_GOVERNANCE/` și `docs/03_ENGINE/`. Orice modificare a unui document Frozen necesită un ADR dedicat, nu editare directă.
