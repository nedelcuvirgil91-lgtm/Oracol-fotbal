# Football Data Harvester — Architecture Audit (DRAFT, pre-implementare)

**Status**: DRAFT — propunere de arhitectură + analiză critică, **fără nicio linie de cod scrisă**. Nu e Frozen, nu e ADR — precedent direct: Pasul 4.5 din Learning Core ("Promotion Architecture"), unde arhitectura a fost dezbătută complet înainte de prima linie de cod de producție.

**Scop**: un serviciu separat, cu un singur mandat — completează statistici de meci lipsă (shots, shots on target, posesie, xG unde există o sursă curată, big chances) în `match_history`, din surse externe, fără să atingă niciodată logica de predicție a Football Oracle.

---

## 0. Premisă — de ce un serviciu separat, nu o extensie a `sync/`

`sync/sources/` conține deja un pattern de plugin (`football_data.py`, `openfootball.py`, `football_data_co_uk.py`, `kaggle.py`) — fiecare sursă cu propriul parser, normalizat prin `mappings.py`. Aparent, Harvester-ul ar putea fi doar o extensie a acestui pattern.

**De ce NU**: `sync/` e azi cuplat direct de `oracle_engine.py`/`run_daily.py` — orice bug într-un provider nou riscă să afecteze pipeline-ul zilnic de producție (deja s-a întâmplat: incidentul "writer destructiv" din 2026-07-13, 1.059 rânduri ELO re-anulate de un upsert cu chei `None`, vezi §4). Cerința explicită "poate fi șters complet fără să afecteze Football Oracle" nu poate fi garantată dacă Harvester-ul trăiește în același proces/deploy ca motorul de predicție.

**Decizie propusă**: Harvester = serviciu/repo separat, care scrie DOAR în coloane specifice, deja NULL în `match_history`, niciodată citite de cod critic înainte ca Harvester să le fi populat vreodată (regulă verificabilă: azi, cu Harvester inexistent, acele coloane sunt 100% NULL și codul funcționează — starea trebuie să rămână identică dacă Harvester e oprit permanent).

---

## 1. Structura repo-ului

Propunere: repo GitHub separat (`football-data-harvester`), NU un director în `Oracol-fotbal`. Motive:

- Eliminabilitate totală literală — ștergerea unui repo nu poate atinge accidental fișiere din alt repo, spre deosebire de un director dintr-un monorepo (unde un `rm -rf` greșit sau un import relativ scăpat ar putea traversa granița).
- Deploy/CI independent — Harvester poate rula pe alt orar, cu alte secrete, fără să partajeze `requirements.txt`/dependențe cu Football Oracle (risc redus de coliziune de versiuni, ex. o versiune de `pandas` care ar sparge `ml_predictor.py`).
- Graniță de review clară — orice PR pe Harvester nu poate, prin construcție, atinge `oracle_engine.py`/`ml_predictor.py`.

**Punct critic, nerezolvat încă**: Harvester TOT trebuie să scrie în `match_history` din Supabase-ul de producție al Football Oracle — deci partajează baza de date, chiar dacă nu partajează codul. Izolarea de cod nu e izolare de date. Acest lucru trebuie tratat explicit la §4 (nu poate corupe istoricul) — separarea de repo reduce riscul de cod, dar nu-l elimină la nivel de scriere în DB.

## 2. Plugin architecture

Reutilizează conceptul din `sync/sources/` (fiecare provider = un modul cu interfață comună), dar NU codul — Harvester nu importă `sync/sources/*.py` din Football Oracle (ar reintroduce cuplarea pe care §0/§1 o resping).

Interfață minimă propusă per plugin:
```
class HarvesterSource(Protocol):
    name: str                     # identitate stabilă, ex. "football_data_co_uk"
    def fetch(self, fixture_ids: list[str]) -> list[HarvestedRow]: ...
```
`HarvestedRow` = date brute + `source_name` + `fetched_at` (UTC) — niciodată scris direct în `match_history`, ci printr-un strat de normalizare/conflict-resolution (§4-5) înainte de orice scriere.

**Întrebare deschisă, nerezolvată**: câte surse independente pentru ACELAȘI tip de statistică sunt realist necesare la lansare? Dacă răspunsul e "una singură" (ex. doar football-data.co.uk pentru shots), atunci stratul de detectare a conflictelor (§5) e supra-inginerie pentru v1 — merită decis explicit înainte de design, nu presupus.

## 3. Normalizare

`mappings.py` (Football Oracle) e sursa canonică de nume echipe/ligi — ADR-001, deja Frozen. Harvester NU poate reimplementa propria normalizare independentă (ar produce exact disjuncția deja documentată în proiect între surse — vezi `DATA_PIPELINE_INVESTIGATION_2026-07-12.md`, unde o secvențiere greșită de doi scriitori a produs rânduri cu ELO și rating din surse diferite, niciodată reconciliate).

Propunere: Harvester consumă `mappings.py` ca dependință read-only (fie prin API expus de Football Oracle, fie printr-un pachet publicat separat cu maparea canonică — de decis, dar NU prin duplicare manuală, care ar dezincroniza cele două repo-uri în timp).

## 4. Cum nu poate corupe istoricul — precedent obligatoriu

Acesta e cel mai important punct al documentului, pentru că proiectul are deja un incident real, documentat, cu exact acest tip de defect: `database/queries.py:57-67`, `_strip_none_values()` — fix aplicat 2026-07-13 după ce doi scriitori (`sync/sources/football_data.py`, `sync/sources/openfootball.py`) trimiteau explicit `home_elo=None`/`away_elo=None` în payload de upsert, rescriind cu NULL 1.059 rânduri de ELO deja calculat corect. Testul de regresie (`tests/test_sync_writer_protection.py`) confirmă mecanismul exact.

**Regula obligatorie pentru Harvester, fără excepție**: aceeași disciplină ca `sync/backfill_features.py` — payload de UPDATE conține DOAR coloanele curent NULL pentru acel rând (pattern `_missing_feature_columns()`, `sync/backfill_features.py:105-108`), niciodată o cheie cu valoare `None`/lipsă pentru o coloană deja populată. Verificabil mecanic: un test de gardă care confirmă că niciun payload emis de Harvester nu conține chei absente din setul „coloane curent NULL" pentru rândul țintă.

**Al doilea nivel de protecție, obligatoriu**: scriere ATOMICĂ per coloană/rând (`INSERT ... ON CONFLICT DO UPDATE SET col = COALESCE(match_history.col, EXCLUDED.col)` — pattern SQL, nu doar disciplină Python) — chiar dacă Harvester ar avea un bug care trimite o valoare greșită pentru o coloană deja populată, baza de date însăși refuză suprascrierea, nu doar codul aplicației. Acesta e un nivel de apărare pe care fix-ul din 2026-07-13 NU l-a avut la momentul incidentului (garda era doar în Python, la stratul aplicație) — Harvester ar trebui să înceapă direct cu garda la nivel de bază de date, nu s-o adauge după un incident.

**Întrebare deschisă**: cine deține scrierea efectivă în `match_history` — Harvester scrie direct (necesită credențiale `service_role` pe proiectul de producție al Football Oracle, risc de blast radius mare), sau Harvester produce un fișier/payload intermediar, iar Football Oracle importă printr-un proces separat, controlat, auditat? A doua variantă reduce suprafața de atac (Harvester nu are niciodată acces de scriere direct la producție), dar adaugă o etapă manuală/semi-automată. De decis explicit — nu implicit prin cea mai simplă implementare.

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

**Detectarea conflictelor între provideri**: relevantă DOAR dacă există ≥2 surse pentru aceeași statistică pe același meci (vezi întrebarea deschisă §2). Dacă da: regulă propusă — prima scriere câștigă (coloana devine non-NULL, gating-ul de la §4 blochează orice suprascriere ulterioară), nu o reconciliere activă. Simplu, dar înseamnă că ordinea de rulare a surselor contează — trebuie documentată explicit, nu implicită.

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

Condiție de proiectare, nu doar de operare — trebuie verificabilă înainte de prima linie de cod:

1. **Football Oracle nu importă niciodată cod din Harvester** — garantat prin §1 (repo separat).
2. **Coloanele pe care Harvester le scrie trebuie să fie deja tolerante la NULL în tot codul de producție azi** — verificabil: fiecare coloană țintă (shots, shots_on_target, possession, big_chance) e deja 0% populată în producție ȘI codul funcționează corect cu ele NULL (confirmat de auditul tehnic din 2026-07-14 — `home_offensive_rating`/etc. folosesc azi proxy-uri sintetice tocmai pentru că aceste coloane sunt goale). Deci oprirea Harvester-ului = revenire la starea actuală, nu o stare nouă, nedefinită.
3. **Niciun cod de producție nu trebuie să presupună CĂ Harvester a rulat** — nicio ramură `if home_shots is not None` care ar deveni cale moartă dacă Harvester nu mai scrie niciodată nu trebuie să fie singura cale funcțională; fallback-ul sintetic actual trebuie să rămână calea implicită, nu una „temporară".
4. **Ștergerea coloanelor scrise de Harvester** (dacă s-ar decide vreodată) trebuie să fie o migrare aditivă inversă simplă (`ALTER TABLE ... DROP COLUMN`), fără dependințe încrucișate — verificabil dacă schema respectă disciplina deja stabilită (`CREATE TABLE IF NOT EXISTS`, coloane aditive, niciodată o coloană obligatorie/`NOT NULL` nouă pe un tabel existent).

**Verdict**: eliminabilitatea totală e realizabilă, DAR nu automat — cere disciplina explicită de la punctul 3 (nicio cale de cod care presupune Harvester ca sursă unică/obligatorie) menținută activ în `ml_predictor.py`/`feature_engine.py` pe toată durata cât Harvester există. Nu e o proprietate câștigată o singură dată la design, ci una de verificat la fiecare PR viitor care atinge aceste coloane.

---

## Întrebări deschise, nerezolvate — de decis înainte de prima linie de cod

1. Harvester scrie direct în producție (`service_role`, risc de blast radius) sau produce un payload intermediar importat controlat de Football Oracle? (§4)
2. Există realist ≥2 surse independente pentru aceeași statistică la lansare, sau design-ul de conflict-resolution (§5) e supra-inginerie pentru v1? (§2)
3. Cum se distribuie/sincronizează `mappings.py` între cele două repo-uri fără duplicare manuală care să dezincronizeze în timp? (§3)
4. Frecvența reală de rulare — o dată, periodic, sau doar la cerere? (§7)

## Ce NU tratează acest document

Nu propune un design de bază de date complet (schema exactă a coloanelor noi rămâne de stabilit la implementare, cu aceeași disciplină `CREATE TABLE IF NOT EXISTS`/RLS/`service_role` din `supabase-safety`). Nu decide dacă xG (Understat) intră vreodată în scopul Harvester-ului — riscul legal de scraping deja semnalat în `KNOWLEDGE_ENGINE_SOURCES_AUDIT_2026-07-13.md` rămâne nerezolvat, independent de arhitectura Harvester-ului însuși. Nu conține cod.
