# Football Data Harvester — Architecture Audit (DRAFT, pre-implementare)

**Status**: DRAFT — propunere de arhitectură + analiză critică, **fără nicio linie de cod scrisă**. Nu e Frozen, nu e ADR — precedent direct: Pasul 4.5 din Learning Core ("Promotion Architecture"), unde arhitectura a fost dezbătută complet înainte de prima linie de cod de producție.

**Scop**: un serviciu separat, cu un singur mandat — completează statistici de meci lipsă (shots, shots on target, posesie, xG unde există o sursă curată, big chances) în `match_history`, din surse externe, fără să atingă niciodată logica de predicție a Football Oracle.

**Reframing (Chief Architect)**: nu doar un "scraper" — un **Data Acquisition Engine**, cu o interfață unică peste orice tip de sursă (API, CSV, Kaggle, scraping, import manual). Vezi §2.

**Invariant central, repetat explicit pentru că e cel mai important din tot documentul**: *„dacă mâine ștergem Harvester, Football Oracle continuă să funcționeze."* Football Oracle nu trebuie să știe că Harvester există — nu doar la nivel de cod, ci la nivel de dependință. Nicio ramură `if harvester...` sau echivalent nu are voie să existe vreodată în codul Football Oracle. Vezi §11.

---

## 0. Premisă — de ce un serviciu separat, nu o extensie a `sync/`

`sync/sources/` conține deja un pattern de plugin (`football_data.py`, `openfootball.py`, `football_data_co_uk.py`, `kaggle.py`) — fiecare sursă cu propriul parser, normalizat prin `mappings.py`. Aparent, Harvester-ul ar putea fi doar o extensie a acestui pattern.

**De ce NU**: `sync/` e azi cuplat direct de `oracle_engine.py`/`run_daily.py` — orice bug într-un provider nou riscă să afecteze pipeline-ul zilnic de producție (deja s-a întâmplat: incidentul "writer destructiv" din 2026-07-13, 1.059 rânduri ELO re-anulate de un upsert cu chei `None`, vezi §4). Cerința explicită "poate fi șters complet fără să afecteze Football Oracle" nu poate fi garantată dacă Harvester-ul trăiește în același proces/deploy ca motorul de predicție.

**Decizie propusă**: Harvester = serviciu/repo separat, care scrie DOAR în coloane specifice, deja NULL în `match_history`, niciodată citite de cod critic înainte ca Harvester să le fi populat vreodată (regulă verificabilă: azi, cu Harvester inexistent, acele coloane sunt 100% NULL și codul funcționează — starea trebuie să rămână identică dacă Harvester e oprit permanent).

---

## 1. Structura repo-ului

Propunere inițială: repo GitHub separat (`football-data-harvester`), NU un director în `Oracol-fotbal`. **Revizuit (Chief Architect) — trei componente, nu două**, ca niciunul din cele două servicii de business să nu depindă direct de celălalt:

```
football-common   (repo minimal, shared)
  - mappings.py (echipe/ligi canonice, ADR-001)
  - league ids / team ids / competition ids
       ↑                              ↑
       |                              |
  Football Oracle              Football Data Harvester
  (produsul, predicții)        (Data Acquisition Engine)
```

Football Oracle și Harvester depind AMBELE de `football-common`, NICIODATĂ unul de celălalt — nici măcar pentru `mappings.py`. Asta rezolvă complet întrebarea deschisă inițială despre sincronizarea normalizării (vezi fostul §3, acum decis).

Motive pentru separarea în 3 componente, nu 2:

- Eliminabilitate totală literală — ștergerea repo-ului Harvester nu poate atinge accidental fișiere din Football Oracle sau din `football-common`.
- Deploy/CI independent — Harvester rulează pe alt orar, cu alte secrete, fără să partajeze `requirements.txt` cu Football Oracle.
- Graniță de review clară — un PR pe Harvester nu poate, prin construcție, atinge `oracle_engine.py`/`ml_predictor.py`.
- **`football-common` rămâne suficient de mic încât să nu devină el însuși un punct de cuplare ascunsă** — conține EXCLUSIV date de mapare/identitate (nume canonice, ID-uri), niciodată logică de business, niciodată cod de scriere/citire Supabase. Dacă `football-common` ar crește să conțină logică, ar reintroduce exact cuplarea pe care separarea o respinge.

**Punct critic, rămâne valabil**: Harvester TOT trebuie să scrie în `match_history` din Supabase-ul de producție al Football Oracle — deci partajează baza de date, chiar dacă nu partajează codul (nici măcar prin `football-common`). Izolarea de cod nu e izolare de date. Tratat explicit la §4.

## 2. Data Acquisition Engine — interfață unică peste orice tip de sursă

**Extindere de scop (Chief Architect)**: nu un plugin architecture limitat la "surse web", ci un Data Acquisition Engine — aceeași interfață pentru API, CSV, Kaggle, scraping, import manual. Obiectiv explicit: o sursă nouă se adaugă în ~30 minute, indiferent de tipul ei de acces.

Reutilizează conceptul din `sync/sources/` (fiecare provider = un modul cu interfață comună), dar NU codul — Harvester nu importă `sync/sources/*.py` din Football Oracle (ar reintroduce cuplarea pe care §0/§1 o resping).

Interfață minimă propusă, generică pe tipul de acces:
```
class HarvesterSource(Protocol):
    name: str                     # identitate stabilă, ex. "football_data_co_uk"
    kind: Literal["api", "csv", "kaggle", "scrape", "manual"]
    def fetch(self, fixture_ids: list[str]) -> list[HarvestedRow]: ...
```
`HarvestedRow` = date brute + `source_name` + `fetched_at` (UTC) — niciodată scris direct în `match_history`, ci printr-un strat de normalizare/conflict-resolution (§4-5) înainte de orice scriere. Diferența dintre `kind`-uri e izolată complet în implementarea `fetch()` a fiecărui plugin (un CSV local, un apel HTTP, un dataset Kaggle, o pagină scrapuită, un fișier introdus manual — toate produc identic `list[HarvestedRow]`, restul motorului nu știe și nu-i pasă de sursă).

**Întrebare deschisă, parțial redusă de reframing**: câte surse independente pentru ACELAȘI tip de statistică sunt realist necesare la lansare? Interfața generică de mai sus suportă ușor multi-sursă prin design, dar asta NU înseamnă că stratul de detectare a conflictelor (§5) trebuie construit din prima zi — la lansare, probabil o singură sursă activă per statistică (ex. football-data.co.uk pentru shots) e suficientă; conflict-resolution rămâne document, nu implementat, până apare o a doua sursă reală.

## 3. Normalizare — rezolvat prin `football-common`

`mappings.py` (echipe/ligi canonice, ADR-001, deja Frozen în Football Oracle) mută în `football-common` (§1). Harvester și Football Oracle consumă AMBELE aceeași sursă, fără ca vreunul să depindă de celălalt — elimină riscul deja materializat o dată în proiect (`DATA_PIPELINE_INVESTIGATION_2026-07-12.md`: o secvențiere greșită de doi scriitori a produs rânduri cu ELO și rating din surse diferite, niciodată reconciliate, din exact acest tip de normalizare dezincronizată).

**Notă de migrare, pentru Football Oracle**: mutarea `mappings.py` în `football-common` e o schimbare de contract (ADR-001 e deja Frozen) — necesită un ADR nou în Football Oracle dacă/când se decide implementarea efectivă. Acest document nu decide ADR-ul, doar arhitectura țintă.

## 4. Cum nu poate corupe istoricul — precedent obligatoriu

Acesta e cel mai important punct al documentului, pentru că proiectul are deja un incident real, documentat, cu exact acest tip de defect: `database/queries.py:57-67`, `_strip_none_values()` — fix aplicat 2026-07-13 după ce doi scriitori (`sync/sources/football_data.py`, `sync/sources/openfootball.py`) trimiteau explicit `home_elo=None`/`away_elo=None` în payload de upsert, rescriind cu NULL 1.059 rânduri de ELO deja calculat corect. Testul de regresie (`tests/test_sync_writer_protection.py`) confirmă mecanismul exact.

**Regula obligatorie pentru Harvester, fără excepție**: aceeași disciplină ca `sync/backfill_features.py` — payload de UPDATE conține DOAR coloanele curent NULL pentru acel rând (pattern `_missing_feature_columns()`, `sync/backfill_features.py:105-108`), niciodată o cheie cu valoare `None`/lipsă pentru o coloană deja populată. Verificabil mecanic: un test de gardă care confirmă că niciun payload emis de Harvester nu conține chei absente din setul „coloane curent NULL" pentru rândul țintă.

**Al doilea nivel de protecție, obligatoriu**: scriere ATOMICĂ per coloană/rând (`INSERT ... ON CONFLICT DO UPDATE SET col = COALESCE(match_history.col, EXCLUDED.col)` — pattern SQL, nu doar disciplină Python) — chiar dacă Harvester ar avea un bug care trimite o valoare greșită pentru o coloană deja populată, baza de date însăși refuză suprascrierea, nu doar codul aplicației. Acesta e un nivel de apărare pe care fix-ul din 2026-07-13 NU l-a avut la momentul incidentului (garda era doar în Python, la stratul aplicație) — Harvester ar trebui să înceapă direct cu garda la nivel de bază de date, nu s-o adauge după un incident.

**Decis (Chief Architect) — nu mai e întrebare deschisă**: **scriere directă**, nu payload intermediar, nu fișiere, nu import manual. Motivul explicit: „Vreau scriere directă. Dar: doar pe coloane permise; doar NULL → valoare; niciodată overwrite; cu COALESCE în SQL; cu verificări înainte de commit." Adică Harvester scrie direct în producție, dar arhitectura face **imposibil tehnic** să distrugă ceva — nu prin evitarea scrierii directe, ci prin garda la 3 niveluri, obligatorii TOATE simultan, nu alternative:
1. **Whitelist de coloane** — Harvester are voie să scrie EXCLUSIV în coloanele explicit definite pentru el (shots, shots_on_target, possession, big_chance, etc.) — orice altă coloană, inclusiv orice coloană din `FEATURE_COLUMNS`, e respinsă la nivel de cod înainte de orice apel către Supabase.
2. **NULL → valoare, niciodată overwrite** — payload conține doar chei pentru coloane curent NULL (§ regula obligatorie de mai sus), verificat mecanic printr-un test de gardă.
3. **`COALESCE` în SQL** — a doua linie de apărare, la nivelul bazei de date, independentă de disciplina din Python (§ al doilea nivel de protecție de mai sus) — chiar dacă (1) și (2) ar eșua printr-un bug, baza de date refuză oricum suprascrierea.

Credențialele folosite de Harvester pentru scriere directă rămân `service_role`, dar restricționate — fie prin RLS pe exact coloanele din whitelist (dacă Supabase permite RLS la nivel de coloană pentru `UPDATE`, de verificat la implementare), fie prin funcția RPC dedicată (`harvest_upsert_stats(...)`, pattern deja precedent în proiect — `promote_challenger`, `upsert_odds_snapshot`) care aplică toate cele 3 garanții server-side, nu doar client-side.

## 5. Proveniența fiecărei statistici + Quality Score

Precedent direct în proiect: `services/odds_persistence_service.py` (ADR-005/006, Frozen) — persistă opening/closing odds cu provenance explicit (sursă, timestamp). Harvester ar trebui să urmeze exact acest tipar, nu unul nou.

Propunere de schemă minimă per statistică scrisă:
```
{stat_name}         -- valoarea propriu-zisă (ex. home_shots)
{stat_name}_source   -- identitatea plugin-ului care a produs-o
{stat_name}_fetched_at  -- UTC, momentul colectării
```
(nu o tabelă `provenance` separată, generică — coloane explicite per statistică, consistent cu stilul deja folosit în `match_history` pentru alte feature-uri derivate, ex. `home_corner_avg_recent`).

**Quality Score**: propus ca un scor per (sursă, tip de statistică), NU per rând individual — ex. „football-data.co.uk are completitudine 96,14% pe Bundesliga, 75,23% pe Ligue 1" (cifre deja măsurate, `DATASET_CAPABILITY_AUDIT_2026-07-13.md`). Actualizat periodic (nu la fiecare scriere), folosit pentru a decide ORDINEA de încercare a surselor la §2, nu pentru a filtra rânduri individuale (ar introduce complexitate fără beneficiu clar la o singură sursă per statistică, conform întrebării deschise de la §2).

**Detectarea conflictelor între provideri**: relevantă DOAR dacă/când apare o a doua sursă reală pentru aceeași statistică (vezi §2 — la lansare, o singură sursă activă per statistică e suficientă, conflict-resolution rămâne document, nu cod). Dacă/când apare: regulă propusă — prima scriere câștigă (coloana devine non-NULL, gating-ul de la §4 blochează orice suprascriere ulterioară), nu o reconciliere activă. Simplu, dar înseamnă că ordinea de rulare a surselor contează — trebuie documentată explicit, nu implicită.

## 6. Versionarea datelor

Nu necesită un mecanism nou — Learning Core are deja conceptul de identitate unică prin `(algorithm_family, algorithm_version, training_run_id, dataset_id)` (CLAUDE.md, „Regulile pentru Learning Core"). Harvester nu antrenează nimic, deci nu are nevoie de `dataset_id` — dar `{stat_name}_fetched_at` de la §5 joacă exact rolul de versionare la nivel de rând: orice re-antrenare poate documenta exact "la ce dată erau populate aceste coloane".

## 7. Scheduler

`sync/run_daily.py` există deja ca orchestrator zilnic al Football Oracle (03:00 UTC, conform ADR-014). Harvester NU ar trebui să se conecteze la acest orchestrator (ar reintroduce cuplarea respinsă la §0) — rulează pe propriul orar, independent, prin GitHub Actions `workflow_dispatch`/`schedule` în propriul repo.

**Frecvență propusă**: mult mai rară decât sync-ul zilnic al Football Oracle — Harvester completează un backlog istoric finit (meciuri deja jucate, cu statistici deja publicate de sursă), nu urmărește meciuri live. O rulare săptămânală (sau chiar manuală, `workflow_dispatch` only, la cerere) e probabil suficientă pentru v1 — de validat cu volumul real de rânduri rămase de completat.

## 8. Retry

`sync/run_daily.py` izolează fiecare pas cu propriul `try/except` (un pas eșuat nu oprește restul pipeline-ului), dar nu are un mecanism explicit de retry-cu-backoff pentru apeluri API individuale — pattern-ul curent e "eșuează, loghează, continuă la următorul rând", nu "reîncearcă".

Propunere pentru Harvester: retry cu backoff exponențial DOAR la nivelul unei singure cereri HTTP (2-3 încercări, pentru erori tranzitorii de rețea/rate-limit) — niciodată retry la nivel de „rând întreg" dacă sursa a răspuns explicit cu date invalide/lipsă (ar fi echivalentul unei bucle infinite fără progres). Fiecare eșec definitiv se loghează cu identitatea exactă a rândului (fixture_id) și motivul, niciodată silențios (precedent negativ direct: incidentul (b) din `tests/test_sync_writer_protection.py` — o excepție care întorcea `set()` gol silențios a dus la re-upsert zilnic al 5.756 meciuri, nedetectat).

## 9. Logging

Fără mecanism nou — pattern-ul deja existent în proiect (`logger = logging.getLogger("FootballOracle.X")`, mesaje structurate cu numărul de rânduri afectate) e suficient și consistent cu restul codebase-ului. Harvester ar trebui să producă un raport de rulare (rânduri procesate, rânduri completate cu succes per coloană, rânduri eșuate cu motiv) — nu doar log de linie, un sumar final, exact ca `run_backfill()` din `sync/backfill_features.py`.

## 10. Cum completează doar coloanele lipsă

Deja acoperit mecanic la §4 — reutilizează identic pattern-ul `_missing_feature_columns()`/gating NULL-only din `sync/backfill_features.py`, deja dovedit pe producție (rulează zilnic prin ADR-014, zero incidente de la fix-ul din 2026-07-13). Nu se inventează un mecanism nou — se reutilizează unul deja verificat.

## 11. Cum poate fi șters complet fără să afecteze Football Oracle

Condiție de proiectare, nu doar de operare — trebuie verificabilă înainte de prima linie de cod. **Invariant central (Chief Architect), repetat aici ca regulă hard, nu doar recomandare**: dacă mâine ștergem Harvester, Football Oracle continuă să funcționeze — fără dependințe ascunse, fără nicio ramură `if harvester...` (sau echivalent semantic) nicăieri în codul Football Oracle.

1. **Football Oracle nu importă niciodată cod din Harvester** — garantat prin §1 (repo separat, trei componente).
2. **Football Oracle nu depinde de Harvester nici măcar indirect, prin `football-common`** — dependința e `Oracle → football-common` și `Harvester → football-common`, niciodată `Oracle → Harvester`. Ștergerea Harvester-ului nu atinge `football-common`, deci nu atinge Football Oracle.
3. **Coloanele pe care Harvester le scrie trebuie să fie deja tolerante la NULL în tot codul de producție azi** — verificabil: fiecare coloană țintă (shots, shots_on_target, possession, big_chance) e deja 0% populată în producție ȘI codul funcționează corect cu ele NULL (confirmat de auditul tehnic din 2026-07-14 — `home_offensive_rating`/etc. folosesc azi proxy-uri sintetice tocmai pentru că aceste coloane sunt goale). Deci oprirea Harvester-ului = revenire la starea actuală, nu o stare nouă, nedefinită.
4. **Niciun cod de producție nu trebuie să presupună CĂ Harvester a rulat** — nicio ramură `if home_shots is not None` care ar deveni cale moartă dacă Harvester nu mai scrie niciodată nu trebuie să fie singura cale funcțională; fallback-ul sintetic actual trebuie să rămână calea implicită, nu una „temporară". Literal: niciun `if harvester_available` / `if home_shots is not None: ... else: raise` — doar fallback tăcut, mereu funcțional.
5. **Ștergerea coloanelor scrise de Harvester** (dacă s-ar decide vreodată) trebuie să fie o migrare aditivă inversă simplă (`ALTER TABLE ... DROP COLUMN`), fără dependințe încrucișate — verificabil dacă schema respectă disciplina deja stabilită (`CREATE TABLE IF NOT EXISTS`, coloane aditive, niciodată o coloană obligatorie/`NOT NULL` nouă pe un tabel existent).

**Verdict**: eliminabilitatea totală e realizabilă, DAR nu automat — cere disciplina explicită de la punctul 4 (nicio cale de cod care presupune Harvester ca sursă unică/obligatorie) menținută activ în `ml_predictor.py`/`feature_engine.py` pe toată durata cât Harvester există. Nu e o proprietate câștigată o singură dată la design, ci una de verificat la fiecare PR viitor care atinge aceste coloane — candidat pentru un test de gardă dedicat (similar cu garda AST deja folosită în Learning Core pentru „zero importatori neașteptați").

---

## Decizii confirmate (Chief Architect) — nu mai sunt întrebări deschise

1. **Scriere directă** în producție, nu payload intermediar, nu import manual — protejată prin whitelist de coloane + NULL-only + `COALESCE` SQL, toate 3 obligatorii simultan (§4).
2. **`football-common`** — repo minimal separat pentru `mappings.py`/ID-uri canonice, consumat identic de Football Oracle și Harvester, niciun import încrucișat între cele două (§1, §3).
3. **Data Acquisition Engine** — interfață unică peste API/CSV/Kaggle/scraping/manual, nu doar "surse web" (§2).

## Întrebări deschise, rămase — de decis înainte de prima linie de cod

1. Există realist ≥2 surse independente pentru aceeași statistică la lansare, sau conflict-resolution (§5) rămâne document neimplementat pentru v1? (§2)
2. Frecvența reală de rulare — o dată, periodic, sau doar la cerere? (§7)
3. RLS pe coloană vs. funcție RPC dedicată pentru aplicarea celor 3 garanții de scriere server-side (§4) — de decis la implementare, în funcție de ce permite Supabase.

## Ce NU tratează acest document

Nu propune un design de bază de date complet (schema exactă a coloanelor noi rămâne de stabilit la implementare, cu aceeași disciplină `CREATE TABLE IF NOT EXISTS`/RLS/`service_role` din `supabase-safety`). Nu decide dacă xG (Understat) intră vreodată în scopul Harvester-ului — riscul legal de scraping deja semnalat în `KNOWLEDGE_ENGINE_SOURCES_AUDIT_2026-07-13.md` rămâne nerezolvat, independent de arhitectura Harvester-ului însuși. Nu conține cod.
