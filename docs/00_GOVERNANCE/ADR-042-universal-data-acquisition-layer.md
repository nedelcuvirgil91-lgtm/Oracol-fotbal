# ADR-042 — Universal Data Acquisition Layer (UDAL)

**[ACTUALIZAT 2026-07-28, după Faza 1.5]** Proprietarul produsului a
extins conceptual viziunea UDAL: „UDAL nu mai este doar un scraper. UDAL
devine: **Universal Football Knowledge Acquisition Layer**." Acronimul
(UDAL) și codul rămân neschimbate — actualizarea e de scop pe termen
lung (integrare a zeci de surse viitoare), nu o redenumire de contract.
Detalii, clasificare de surse (Primary/Secondary/Premium) și „Future
Providers" (Transfermarkt, FBref — proiectate, neimplementate) în
`docs/06_UDAL/UDAL_SOURCE_CLASSIFICATION.md`. Restul acestui document
rămâne normativ, neschimbat.

**Status**: PROPUS — document de arhitectură, redactat la cerere explicită
("Rolul tău: Principal Software Architect... Misiunea ta este EXCLUSIV
proiectarea noului subsistem"). **Nu implementat, nu aprobat pentru
implementare.** Devine normativ abia după aprobarea explicită a
proprietarului produsului, per disciplina aplicată ADR-034…041. Niciun cod,
nicio migrare, niciun tabel nu a fost creat odată cu acest document — vezi
`docs/06_UDAL/UDAL_ARCHITECTURE_SPEC_v1.0.md` pentru planul de migrare pe
faze, care rămâne neînceput.

**Autor**: Claude, în rolul de Principal Software Architect / Enterprise
System Designer, la cererea explicită a proprietarului produsului — rol
exclusiv de proiectare, fără implementare, fără scraperi, fără migrări,
fără commit/push (constrângeri explicite ale cererii, respectate integral).

**Data**: 2026-07-28.

**Companion**: `docs/06_UDAL/UDAL_ARCHITECTURE_SPEC_v1.0.md` (specificația
completă — diagrame, design per componentă, plan de migrare). Se bazează
explicit pe și nu duplică: `ADR-001-league-providers.md` (sursa canonică
liga→provider), `ADR-034-provider-capability-selection-architecture.md`
(Selection Engine), `ADR-036-canonical-feature-ownership.md` (un singur
scriitor per coloană), `ADR-038-api-football-synchronization-architecture-v2.md`
(SyncOrchestrator, priorități P1-P5), `ADR-039-universal-synchronization-architecture-supabase-first.md`
(Sync Layer, Supabase-First), `ADR-040-automated-migration-gate-and-equivalence-governance.md`
(shadow evaluation + migration gate — precedentul direct pentru cum UDAL
introduce surse noi fără risc), `ADR-041-sync-layer-selection-engine-extension.md`
(extinderea Selection Engine-ului ca al doilea consumator, nu un al doilea
motor).

---

## Context

Football Oracle a ajuns, prin șase luni de extindere incrementală a Sync
Layer-ului (R-Sync-1…10, ADR-034…041), la un ansamblu solid dar **limitat
structural la un singur nivel de achiziție: API-uri REST/JSON**. Auditul
direct al `provider_call_log` (2026-07-28, aceeași sesiune) confirmă
concret limitele acestui nivel unic:

- `freelivefootball` (RapidAPI) — 0% fiabilitate în ultima săptămână (96/96
  apeluri eșuate), cotă epuizată cronic — gol deja documentat în CLAUDE.md.
- `oddsapi` — 44% fiabilitate, tipar de epuizare progresivă a creditelor pe
  parcursul zilei.
- `footballdata` — acces interzis (403) pe endpoint-uri de clasament pentru
  competiții neacoperite de planul gratuit.

Independent de fiabilitatea operațională, **auditul de completitudine a
datelor** (`docs/05_DATA_AUDIT/DATASET_CAPABILITY_AUDIT_2026-07-13.md`,
reconfirmat de `FIELD_CAPABILITY_MATRIX.md`) arată goluri structurale pe
care niciun API disponibil azi nu le acoperă: **orice statistică de meci
pentru Romania SuperLiga (0%)**, **Referee/Attendance (absente complet, în
orice ligă)**, **xG/xA/posesie/Big Chances/PPDA pentru ligile neacoperite
de Soccer Football Info**. Un singur nivel de achiziție (API) nu mai poate
închide aceste goluri — următorul nivel realist e HTML/date publice
structurate, iar pentru unele surse, randare JavaScript (Playwright).

Proprietarul produsului a cerut explicit o schimbare de scop, nu un patch:
un subsistem nou, de rang egal cu Oracle Engine/Learning Core/Supabase
Knowledge Base, care **generalizează achiziția de date pe mai multe
niveluri (tier-uri)**, cu un ordin fix de preferință (API → HTTP Scraper →
Playwright → Validare → Supabase, niciodată inversat), capabil de backfill
istoric pe 5 sezoane și de cadență zi/noapte diferențiată, scalabil la
ligi noi fără cod hardcodat, și pregătit arhitectural (nu implementat) pentru
diagnostic automat și detectare de drift al selectorilor.

## Decizie

### 1. UDAL e ridicarea formală a Sync Layer-ului la rang de subsistem major — nu un sistem paralel

Verificarea directă a infrastructurii existente (`provider_registry.py`,
`provider_capabilities.py`, `provider_selector.py`, `sync_adapter.py`,
`equivalence_governance.py`, `migration_gate.py`) confirmă exact ce s-a
confirmat deja o dată la ADR-041: infrastructura e deja generică, pură,
fără dependințe circulare — construită corect pentru extindere. A construi
un al doilea sistem de achiziție, paralel, ar încălca direct North Star #10
(nicio dependință „în sus" între straturi) și disciplina anti-duplicare
explicită din ADR-041 („exact duplicarea de cod pe care ADR-041 o interzice
explicit"). **Decizie**: UDAL nu înlocuiește Sync Layer-ul — îl
generalizează, adăugând două tier-uri noi de achiziție SUB tier-ul API
existent, un motor formal de backfill istoric, și o politică de
scheduling zi/noapte. Toate componentele Sync Layer existente
(Provider Registry, Capability Registry, Selection Engine, Rate Limit
Manager, Request Manager, Cache Manager, `SyncAdapter`, mecanismul
shadow/gate ADR-040) rămân neatinse structural și devin fundația UDAL.

### 2. Ordinul de achiziție e o axă STRICTĂ, nu un scor ponderat

API (Tier 0) → HTTP Scraper (Tier 1) → Playwright (Tier 2) → Validare →
Supabase. Tier-ul e o **partiție strictă**, evaluată înaintea oricărui scor
de calitate (Selection Engine-ul ADR-034 continuă să aleagă între
candidați ÎN INTERIORUL aceluiași tier — el nu decide niciodată să prefere
un scraper unui API doar pentru un scor mai bun). Un tier inferior devine
candidat DOAR dacă niciun candidat din tier-ul superior nu e disponibil sau
nu acoperă acel (tip de date × ligă). Această regulă e neinversabilă prin
configurare — impusă structural, nu doar prin convenție (detaliu în spec,
§Provider/Scraper Registry).

### 3. Supabase rămâne unica sursă de adevăr — niciun consumator nu citește direct din internet

Oracle Engine, ML, Learning Core nu au voie, azi sau după UDAL, să facă
vreun apel de rețea către un provider/scraper — regulă deja impusă
arhitectural (Oracle Engine nu antrenează, nu scrie în Experiment
Registry) și extinsă acum explicit: **Oracle Engine nu are voie să citească
direct din internet, sub nicio formă, prin niciun tier.** UDAL scrie
exclusiv în Supabase; toți consumatorii citesc exclusiv din Supabase.

### 4. Scalabilitate: zero cod hardcodat pe competiție

Orice țintă de achiziție nouă (ligă, sezon, tip de date) se adaugă prin
date de configurare (extensie a `LEAGUE_PROVIDERS` din `mappings.py`,
per ADR-001 — sursă canonică unică), niciodată prin ramuri noi de cod
per ligă. Un scraper nou respectă contractul `SyncAdapter` existent
(`fetch/normalize/validate/persist/coverage_check`) — parametrizat prin
URL template + hartă de selectori externalizată, nu prin funcții Python
dedicate per site.

### 5. AI-readiness: puncte de conectare proiectate, nimic implementat

Diagnostic automat, detectare de drift al selectorilor, capturi de
screenshot/HTML, rapoarte de reparare — toate rămân **puncte de extensie
proiectate explicit** (registru de selectori versionat, jurnal de rulare
per target, locație dedicată pentru diagnostice), nu componente
funcționale. Orice reparare automată a unui selector, dacă va exista
vreodată, cere un ADR dedicat de risc, exact ca auto-promovarea/
auto-rollback-ul (ADR-002) — niciun cod nu modifică singur o sursă de
adevăr fără om în buclă.

### 6. Migrare pe faze, gated de mecanismul ADR-040, reversibilă la fiecare pas

Nicio sursă nouă (scraper sau Playwright) nu scrie live în `match_history`
fără să treacă întâi prin shadow evaluation + migration gate (mecanismul
deja verificat funcțional end-to-end, `RSYNC7B_EVIDENCE_REPORT_2026-07-28.md`).
Fiecare fază din planul de migrare (`docs/06_UDAL/UDAL_ARCHITECTURE_SPEC_v1.0.md`,
§Migration Plan) e blocată explicit de un test dedicat până la verdict
PASS, exact tiparul `test_migration_gate_blocks_r_sync_7c.py`.

## Consecințe

**Ce permite:**
- Închiderea celor trei goluri de date deja documentate și recunoscute ca
  justificând o sursă nouă (statistici Romania SuperLiga, Referee/
  Attendance, xG/xA/posesie pentru ligile neacoperite).
- Reziliență reală față de epuizarea de cotă API (problema care a
  declanșat această discuție) — un tier de rezervă structurat, nu doar un
  fallback ad-hoc.
- Extindere la ligi noi fără rescriere de cod — cost marginal real, nu
  doar declarat.

**Ce costă / ce rămâne deschis, documentat explicit (nu ascuns):**
- Risc legal/ToS per țintă de scraping — nerezolvabil prin arhitectură,
  cere aprobare explicită per sursă înainte de activare (§Probleme
  arhitecturale din spec).
- Playwright e infrastructură complet nouă în acest repo (zero precedent)
  — cost de implementare și risc mai mare decât Tier 1, programat ultimul
  în plan, nu în paralel.
- Asimetrie de încredere între date API și date scraped — cere decizie
  explicită (ADR separat, la momentul Fazei 1) despre cum intră un câmp
  scraped în `FEATURE_COLUMNS` (disciplina de ablație rămâne neschimbată,
  fără excepție).
- `sync/sources/` (football-data.co.uk, openfootball, Kaggle) e azi un al
  treilea tipar de achiziție, disconectat de Provider Registry/SyncAdapter
  — UDAL trebuie să-l absoarbă formal (Fază 0/1), altfel rămân trei tipare
  paralele, nu unul.

## Referințe

`docs/06_UDAL/UDAL_ARCHITECTURE_SPEC_v1.0.md` (specificația completă),
`docs/00_GOVERNANCE/ADR-001…041` (vezi Companion), `docs/05_DATA_AUDIT/DATASET_CAPABILITY_AUDIT_2026-07-13.md`,
`docs/00_GOVERNANCE/FIELD_CAPABILITY_MATRIX.md`,
`docs/00_GOVERNANCE/RSYNC7B_EVIDENCE_REPORT_2026-07-28.md`.
