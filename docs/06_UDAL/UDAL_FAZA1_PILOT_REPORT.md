# UDAL Faza 1 — Raport Pilot (ADR-042)

**Scop**: validarea arhitecturii UDAL printr-un pilot controlat — NU
validarea unui site, NU dezvoltarea completă a sistemului (obiectivul
explicit al Fazei 1). Toate cifrele de mai jos vin dintr-o rulare reală
(`scripts/udal_pilot_run.py`, local + verificare directă Supabase), nu
simulate.

**Constrângeri respectate, verificate direct, nu doar declarate**:
- Un singur scraper pilot (`udal_pilot_generic_html_stats`), o singură
  ligă (Romania SuperLiga), un singur tip de date (Match Statistics).
- Rulare exclusiv Shadow Mode — `persist()` e no-op explicit, verificat:
  `records_persisted=0` în `acquisition_run_log`.
- **Zero scriere în tabele canonice** — verificat direct: `SELECT count(*)
  FROM match_history WHERE home_team LIKE 'FC Pilot%' OR away_team LIKE
  'FC Pilot%'` → **0**.
- Oracle Engine — neatins, niciun fișier din calea lui de execuție (`oracle_engine.py`,
  `oracle_api.py`, `feature_engine.py`) nu apare în diff.
- Fără merge în `main` — commit doar pe branch (confirmat mai jos).
- Sursă **necunoscută/nealeasă** — `tos_reviewed=False`, `target_url_template`
  e un placeholder needereferențiat, niciun fetch live n-a avut loc (blocat
  structural, verificat — vezi §Shadow Results).

---

## Coverage

Două interpretări distincte, ambele raportate onest (nicio confuzie
între ele):

- **Coverage structural (extragere din fixture)**: 6/6 rânduri brute din
  fixture-ul HTML au fost extrase de `normalize()` — 100% din rândurile
  prezente în sursă au fost parsate în structuri de date (indiferent dacă
  ulterior au trecut validarea).
- **Coverage de câmpuri (completitudine per rând valid)**: toate cele 9
  câmpuri (`home_team`/`away_team`/`kickoff_date`/`home_corners`/
  `away_corners`/`home_cards`/`away_cards`/`home_fouls`/`away_fouls`) au
  fost populate pentru cele 3 rânduri valide — 100%.
- **Coverage reală de ligă (câte meciuri Romania SuperLiga acoperă o
  sursă reală, per sezon)** — **nemăsurabilă în Faza 1**, prin construcție:
  fixture-ul e sintetic (echipe placeholder, nu date reale), nicio sursă
  reală n-a fost aprobată/accesată. Rămâne exclusiv obiectivul
  `POC_SCRAPER_SOURCE_01` (pas separat, viitor).

## Latency

`fetch_latency_ms = 0.066 ms` — **citire de fișier local**, NU latență de
rețea reală. Raportată onest ca atare: nu spune nimic despre cât ar dura
un fetch HTTP real către o sursă live. Rămâne nemăsurată până la
`POC_SCRAPER_SOURCE_01` (rulează pe un runner GitHub Actions cu acces
real la internet, per decizia anterioară privind limitările de rețea ale
acestei sesiuni).

## Validation Rate

**50,0%** (3 valide / 6 procesate). Nu e un semnal de calitate a unei
surse reale — fixture-ul a fost construit deliberat cu jumătate din
rânduri invalide, ca să testeze mecanismul de respingere, nu o sursă
reală. Motive de respingere confirmate, toate distincte (Validation Layer
distinge corect tipurile de eroare):

| Motiv | Rânduri |
|---|---|
| `negative_value:home_corners` | 1 |
| `missing_required_fields:away_corners` | 1 |
| `duplicate_natural_key_in_batch` | 1 |

## Conflict Rate

**0,0%** (0 din 3 rânduri valide coincid cu o cheie naturală deja
existentă în `match_history`, verificat prin interogare read-only
directă). **Limitare structurală, documentată explicit**: echipele din
fixture sunt placeholder (`FC Pilot Nord`, etc.) — nu pot coincide
niciodată cu rânduri reale din `match_history`. Cifra confirmă doar că
*mecanismul* (`check_conflicts_with_match_history()`) rulează corect și
nu scrie nimic — NU e o măsurătoare reală a ratei de conflict pe care o
sursă reală ar produce-o.

## Shadow Results

Rulare reală confirmată, în 2 părți distincte:

1. **Gate-ul ToS blochează corect** — `adapter.preflight()` a ridicat
   `ScraperPreflightError` (`tos_reviewed=False`), confirmat programatic.
   `adapter.fetch({"mode": "live", ...})` a ridicat separat
   `LiveFetchNotAllowedError` — a doua barieră structurală, independentă
   de prima (chiar dacă cineva ar uita să apeleze `preflight()`, `fetch()`
   însuși refuză live în Faza 1).
2. **Pipeline-ul de shadow a rulat integral pe fixture** — `fetch(mode="fixture")
   → normalize() → validate() → check_conflicts_with_match_history() →
   persist() [no-op]` — toate etapele confirmate funcționale, cu rezultate
   scrise REAL în Supabase, dar exclusiv în cele 2 tabele UDAL (nu
   canonice), verificat direct:
   - `scraper_selector_registry`: 1 rând (`udal_pilot_generic_html_stats`,
     `version=1`).
   - `acquisition_run_log`: 1 rând (`records_fetched=6, records_validated=3,
     records_persisted=0, records_rejected=3`).

## Architecture Review

- **Registry → Selector Map → Adaptor → Validation → Observabilitate**:
  lanțul complet a funcționat end-to-end, fără nicio componentă lipsă sau
  ocolită.
- **Interschimbabilitate confirmată parțial**: adaptorul
  (`GenericHtmlStatsScraperAdapter`) e condus integral de `selector_map`
  (dict extern, nu cod hardcodat) — schimbarea sursei ar însemna
  schimbarea `SELECTOR_MAP`/`target_url_template` din registry, nu
  rescrierea clasei. **Neconfirmat încă**: interschimbabilitatea reală
  cere un AL DOILEA site testat cu aceeași clasă — Faza 1 a testat un
  singur fixture, deci ipoteza de generalitate rămâne teoretică, nu
  dovedită empiric.
- **Contractul `SyncAdapter` respectat**, cu o singură deviere documentată
  (nu ascunsă): `validate()` întoarce `ValidationResult` (rânduri valide +
  respinse + motive), nu doar `list[Any]` cum cere semnătura strict —
  decizie deliberată pentru observabilitatea cerută de pilot; un adaptor
  de producție ar putea alege să respecte semnătura strict.
- **Zero cod hardcodat pe ligă/competiție** — confirmat: nimic din
  `generic_html_stats_scraper_adapter.py` sau `udal_validation.py`
  menționează "Romania SuperLiga" literal.

## Riscuri identificate

1. **O singură sursă de fixture testată** — nu dovedește generalitatea
   reală a adaptorului generic pe un al doilea format HTML diferit
   structural. Risc: designul „interschimbabil" să se dovedească
   insuficient de flexibil la a doua sursă reală.
2. **Latența/coverage-ul reale rămân complet necunoscute** — orice
   estimare de cost/beneficiu pentru Faza 3 (extindere multi-țintă) ar fi
   presupunere, nu date, până la `POC_SCRAPER_SOURCE_01`.
3. **`check_conflicts_with_match_history()` face 1 query per rând** (nu
   batched) — acceptabil la volumul pilotului (3 rânduri), dar ar deveni
   un cost real la scară (sute de meciuri/sezon) — de optimizat înainte de
   Faza 3, nu în Faza 1.
4. **Nicio sursă reală n-a fost identificată/aprobată încă** —
   `SCRAPER_SOURCE_EVALUATION.md` oferă candidați informativi
   (`worldfootball.net` cel mai promițător pe hârtie), dar `robots.txt`/ToS
   rămân neverificate — riscul legal identificat în ADR-042 §16.1 rămâne
   integral deschis.
5. **Mediul de execuție curent nu are acces general la internet** (confirmat:
   chiar `example.com` blocat) — orice POC live viitor trebuie să ruleze pe
   GitHub Actions (runner cu acces real), nu în sesiuni ca aceasta.

## Recomandări pentru Faza 2

Per decizia ta explicită, Faza 2 (dacă pilotul e validat) NU înseamnă
încă alte ligi/tipuri de date — înseamnă `POC_SCRAPER_SOURCE_01`, pas
separat, pe o singură sursă aleasă de tine, cu aprobare explicită
`tos_reviewed=True` abia după acel POC. Recomandările mele, în ordine:

1. **Alege sursa** din `SCRAPER_SOURCE_EVALUATION.md` (sau alta, dacă ai
   deja una în minte) — decizie exclusiv a ta.
2. **`POC_SCRAPER_SOURCE_01`, izolat pe GitHub Actions** — verifică live
   `robots.txt` + structura reală HTML a UNUI meci real, contra formei pe
   care `GenericHtmlStatsScraperAdapter` o așteaptă (`row_selector`/`fields`)
   — dacă selector map-ul actual nu se potrivește, ajustează-l DOAR în
   `scraper_selector_registry` (nu în cod), test direct al
   interschimbabilității pe care Faza 1 n-a putut s-o dovedească.
3. **Abia după POC + aprobarea ta explicită**: `tos_reviewed=True` pentru
   acea sursă specifică, apoi o primă rulare shadow REALĂ (nu fixture) —
   tot fără scriere canonică, gate-ul de migrare ADR-040 rămâne activ până
   la prag de volum + sănătate (exact tiparul deja dovedit la R-Sync-7b).
4. **Batching pentru `check_conflicts_with_match_history()`** înainte de
   orice volum real — 1-query-per-rând nu scalează.
5. **Nu extinde la a doua ligă/tip de date** până când o sursă reală
   trece prin ciclul complet (POC → aprobare → shadow → gate PASS) — exact
   restricția ta explicită, reafirmată aici ca reminder pentru sesiunea
   viitoare.

---

## Fișiere adăugate/modificate (Faza 1)

`docs/06_UDAL/SCRAPER_SOURCE_EVALUATION.md`, `docs/06_UDAL/fixtures/pilot_match_statistics.html`
(sintetic), `udal_validation.py`, `generic_html_stats_scraper_adapter.py`,
`scripts/udal_pilot_run.py`, `scraper_registry.py` (1 intrare pilot,
`tos_reviewed=False`), teste noi: `test_udal_validation.py`,
`test_generic_html_stats_scraper_adapter.py`, `test_scraper_registry.py`
(actualizat). `pytest tests/`: 1637 passed (+21 față de Faza 0), 2 skipped,
aceleași 3 eșecuri pre-existente, nelegate.
