# ADR-040 — Automated Migration Gate & Equivalence Governance

**Status**: PROPOSED — scris la cererea explicită a proprietarului produsului, ca fundație de guvernanță automată reutilizabilă (nu doar poartă pentru R-Sync-7b). Devine FROZEN după prima aplicare reală (G1-G6, `scheduled_fixtures`) confirmă designul pe date live, per aceeași disciplină aplicată ADR-037/039.

**Autor**: Claude, audit + design, la cererea proprietarului produsului (review arhitectural declanșat de defectul descris în Context).

**Data**: 2026-07-27.

**Companion**: `docs/03_ENGINE/UNIVERSAL_SYNC_ARCHITECTURE_AUDIT_2026-07-22.md` §6f/§6g (originea R-Sync-7b), plan de implementare G0-G6 (secțiunea Plan de mai jos).

---

## Context

R-Sync-7b (ADR-039) a introdus un mecanism shadow — comparație observațională între calea live de discovery și `scheduled_fixtures` — implementat, testat local (21 teste), dar necommis. Auditul de închidere a descoperit un defect structural, nu cosmetic: `logging.basicConfig(handlers=[StreamHandler(sys.stdout)])` e singurul handler activ în tot proiectul (confirmat prin grep, zero `FileHandler`), iar rezultatul „echivalent" se loghează la `DEBUG` — filtrat de `level=INFO`. **Consecința**: succesul nu produce nicio dovadă persistentă; eșecul produce o linie de log perisabilă, într-un istoric de Actions care expiră. Nu se poate răspunde, nici manual, la „a rulat validarea ieri și a trecut?".

Extins de proprietarul produsului dincolo de simpla reparație: dacă Supabase devine Single Source of Truth pentru tot proiectul, procesul care *decide dacă o etapă de migrare poate continua* trebuie să respecte aceeași regulă — dovadă persistentă, verificabilă, nu memorie umană. Auditul (cerut explicit) a găsit alte șase locuri cu aceeași boală structurală, de severitate diferită (§Audit mai jos) — cel mai grav fiind validarea live a migrării 023 (R-Sync-7a), care există azi DOAR în istoricul conversației curente.

## Audit — validări dependente de om, pe tot proiectul

Distincție obligatorie înainte de listă, pentru că proiectul are deja gate-uri umane *deliberate*, Frozen, care NU sunt defecte:

| Categorie | Exemple | Statut |
|---|---|---|
| **Gate deliberat** (ADR-002) | `auto_promotion_enabled=False`; trigger SQL `decision_feed` interzice `proposed→approved`; Champion Guardian propune, nu execută; DoD Nivel 2 („ultima căsuță aparține utilizatorului") | Neatins de acest ADR — vezi Principiul 1 |
| **Defect** (monitorizare accidentală, nu autorizare) | Cele 7 din tabelul de mai jos | Obiectul acestui ADR |

| # | Loc | Ce depinde de om azi | Gravitate |
|---|---|---|---|
| A1 | Shadow R-Sync-7b (§6g) | Log invizibil (DEBUG filtrat) sau perisabil (Actions) | Critic |
| A2 | Validarea live migrare 023 (R-Sync-7a) | 100% ad-hoc, există doar în chat, nereproductibil, nu detectează regresie viitoare a RPC-ului | Critic |
| A3 | `shadow_selection_report.py` (ADR-034 PR5) | Dovezile SUNT persistate (`shadow_provider_recommendations`); verdictul cere rulare manuală a scriptului | Mediu |
| A4 | R-Sync-6a (task #18) | Există doar ca linie într-o listă de task-uri | Mediu |
| A5 | DoD Nivel 1, „verificare live end-to-end" | Rulată manual, fără artefact | Mediu |
| A6 | `sync/poc_*.py` (6 scripturi) | Rezultat pe stdout, rulare manuală | Mic |
| A7 | Tabelul cumulat de dependențe live (audit §8) | Întreținut manual la fiecare închidere de etapă | Mic |

## Decizie

### Principiul 1 — VETO ≠ AUTORIZARE (regulă de proiect, nu doar pentru acest ADR)

> Un mecanism automat de guvernanță poate **bloca** singur o acțiune, fără intervenție umană. **Nu poate niciodată autoriza** singur o acțiune ireversibilă sau cu efect asupra producției.

Rezolvă tensiunea explicită dintre „Zero Human Monitoring" (cerut) și „Zero Manual Gates" (cerut, dar imposibil de aplicat literal fără a contrazice ADR-002, care rămâne neatins). Absența dovezii = blocare implicită (fail-closed), niciodată permisiune implicită.

**Pregătit explicit pentru North Star #11 în `CLAUDE.md` — proprietar produs insistă, decizie confirmată, dar NU în acest commit**: formularea propusă, verbatim, de proprietarul produsului —

> „The system may automatically block unsafe changes, but it may never automatically authorize irreversible ones."

`CLAUDE.md` nu e Frozen (document viu), dar are greutatea unui contract de sesiune — introducerea efectivă a North Star #11 rămâne un commit separat, ulterior, dedicat exclusiv acelei modificări (inclusiv decizia de traducere/păstrare a formulării în engleză, față de restul listei de 10, în română — decizie de rezolvat la acel commit, nu aici).

### Principiul 2 — Infrastructură generică, nu per-etapă

Tabelă unică `equivalence_evaluations`, cu `gate_key` (etapa care a produs evaluarea, ex. `R-Sync-7b`) și `entity` (ce se compară, ex. `scheduled_fixtures`) — nu `shadow_equivalence_evaluations` legată doar de fixtures. Aceeași infrastructură validează orice tabelă critică viitoare (`team_form`, `odds_recent`, `injuries`, etc.) fără schemă nouă.

### Principiul 3 — Scor: MIN, niciodată medie

```
coverage      = matched_count / max(live_count, scheduled_count)
field_purity  = 1 − (field_difference_count − accepted_exception_count) / max(matched_count, 1)
id_purity     = 1 − provider_id_difference_count / max(matched_count, 1)

equivalence_score = MIN(coverage, field_purity, id_purity)
```

O medie ar permite unui defect catastrofal (ex. pierderea completă a `freelf_event_id`) să se ascundă într-un scor „acceptabil". MIN e deja principiul Frozen la promovare (North Star #2: Brier ȘI Log-loss ȘI Accuracy simultan) — extins aici, nu inventat.

### Principiul 4 — Verdict pe patru stări, nu trei — GRAY (Learning) e distinct de culori

| Stare | Condiție | E o culoare? |
|---|---|---|
| `insufficient_data` (**GRAY — Learning**) | volum sub prag (Principiul 6) | **Nu** — Regula #8 (CLAUDE.md): o stare necunoscută nu se aproximează. A colora „necunoscut" ca galben sau roșu ar însemna exact aproximarea interzisă. |
| `broken` | evaluarea shadow a crăpat structural, sau `scheduled_count=0` cu `live_count>0` | **RED** (fail-closed: o observație stricată e tratată ca dovadă de problemă, nu ca „fără date") |
| `RED` | `equivalence_score < 1.0` (există ≥1 diferență NEacceptată — vezi `exception_policy`, Principiul 5) | Da |
| `YELLOW` | `equivalence_score == 1.0` ȘI `accepted_exception_count > 0` (doar diferențe cu politică SAFE/EXPECTED/WARNING) | Da |
| `GREEN` | `equivalence_score == 1.0` ȘI `accepted_exception_count == 0` | Da |

**Numele stării GRAY, deliberat, nu e „unknown" sau „error" — decizie explicită proprietar produs**: în Football Oracle, GRAY (Learning) NU înseamnă „sistemul nu știe ce se întâmplă" — înseamnă „sistemul acumulează încă dovezi, ca proces normal, nu ca eroare". Documentat explicit în `migration_gate status`/`explain` cu acest text, nu doar ca etichetă de cod — contează cum se citește operațional, nu doar ce reprezintă tehnic.

**Notă tehnică importantă**: formula de scor de la Principiul 3 exclude deja excepțiile acceptate din numărătoare — deci GREEN și YELLOW ar avea, altfel, scor identic (1.0). Distincția dintre ele se face separat, prin `accepted_exception_count`, nu prin scor. Scorul decide doar RED vs. non-RED.

### Principiul 5 — Provider breakdown + politică de excepții + root cause (best-effort, etichetat ca atare)

`provider_breakdown` (JSONB): per provider (`freelf`/`oddsapi`/`fd`/`espn`/`tsdb`/`apifootball`), `{matched, field_diff, id_diff, missing_scheduled}` — derivat din câmpul `source` deja folosit de `scheduled_fixtures_shadow.evaluate()` pentru alegerea coloanelor de comparat (extensie directă, nicio sursă nouă de date).

**`exception_policy` — extinde `accepted_exception_count` de la simplu „acceptat/neacceptat" la o clasificare de severitate, cerută explicit de proprietarul produsului**: „două `venue_city` lipsă ≠ două `provider_id` lipsă." Fiecare tip CUNOSCUT de divergență (identificat prin semnătură `(field, provider)` sau `(categorie)`) primește o etichetă din patru:

| Politică | Sens | Efect asupra verdictului |
|---|---|---|
| `SAFE` | gap documentat, fără risc funcțional (ex. `fd.venue_city`, `fd.league` — R-Sync-7a, football-data.org nu normalizează liga/nu are oraș) | intră în `accepted_exception_count` → cel mult YELLOW |
| `EXPECTED` | diferență inerentă designului (ex. `kickoff_utc` fără ierarhie de calitate, R-Sync-7a — „niciun provider nu are defect demonstrat") | intră în `accepted_exception_count` → cel mult YELLOW |
| `WARNING` | tolerat azi, dar merită atenție operațională (rezervat, gol la lansare — populat doar când auditul găsește un caz concret, nu presupus) | intră în `accepted_exception_count` → cel mult YELLOW, dar semnalat distinct în `migration_gate explain` |
| `CRITICAL` | problemă de integritate a datelor — **structural NU poate fi acceptată, indiferent cine ar vrea s-o adauge pe listă** | exclusă din `accepted_exception_count` prin construcție → contribuie mereu la RED |

**Regulă structurală, nu doar convenție**: `provider_id_differences` (identificatori de provider pierduți/inconsistenți) **nu intră niciodată** în mecanismul `exception_policy` — sunt tratate ca `CRITICAL` prin construcția codului, nu printr-o etichetă care ar putea fi schimbată accidental. Motivul: ar viola invariantul COALESCE-only al FixtureMergePolicy (migrarea 023) — dacă un identificator de provider diferă, e un bug de RPC, nu o divergență tolerabilă. Doar `field_differences` (câmpurile guvernate: `league`/`venue_city`/`kickoff_utc`) pot avea o politică diferită de `CRITICAL`.

`KNOWN_EXCEPTIONS` — registru static, în cod (nu în `model_config`, deliberat): adăugarea unei noi excepții e o constatare de audit (ca `fd.venue_city`, găsită la R-Sync-7a), care merită revizuire la commit, nu un toggle runtime schimbabil fără urmă. Orice semnătură `(field, provider)` absentă din registru rămâne, implicit, NEacceptată — fail-closed, consistent cu Principiul 8.

`root_cause_category` — clasificare **euristică, deterministă, dar NU o dovadă de cauzalitate** (onestitate explicită, „Verificat, nu presupus"):

| Diferență observată | Categorie | Certitudine |
|---|---|---|
| `field_differences[field=venue_city]` | `VENUE_PRIORITY` | Ridicată — mapare directă pe câmp |
| `field_differences[field=league]` | `LEAGUE_MAPPING` | Ridicată |
| `field_differences[field=kickoff_utc]` | `KICKOFF_CONFLICT` | Ridicată |
| `provider_id_differences[scheduled IS NULL]` | `MISSING_PROVIDER_ID` | Ridicată |
| `missing_scheduled` (există live, lipsă din DB) | `PROVIDER_TIMEOUT` | **Presupunere etichetată** — poate fi și sync neexecutat, nu doar timeout |
| `missing_live` (rând „fantomă") | `UNKNOWN` | **Deliberat neclasificat** — a distinge „reprogramare reală" de „eroare de normalizare a numelui" ar cere o euristică de similaritate de nume pe care n-o propun speculativ aici (`TEAM_NORMALIZATION` rămâne o categorie definită în schemă, dar NEATRIBUITĂ automat până există un semnal determinist) |
| `provider_id_differences` cu ambele valori non-null, diferite | `UNKNOWN`, prioritate de investigare maximă | Ar viola invariantul COALESCE-only al FixtureMergePolicy (migrarea 023) — dacă apare, e bug de RPC, nu divergență normală |

`UNKNOWN` e un rezultat acceptat, nu un eșec al clasificării — a forța o categorie fără semnal determinist ar fi exact genul de aproximare interzisă de Regula #8.

### Principiul 6 — Praguri pe volum, configurabile, nu pe timp

Renunțat explicit la N=5 rulări/7 zile (versiunea anterioară a acestui design). Prag nou:

- `min_matched_total` (implicit **500**) — `matched_count` cumulat pe fereastra evaluată.
- `min_matched_per_provider` (implicit **50**) — pentru FIECARE provider relevant `entity`-ului (pentru `scheduled_fixtures`: toți cei 6).

Stocate în `model_config` (Supabase, deja existent — cheie nouă `migration_gate_thresholds`, JSONB `{"R-Sync-7b": {"min_matched_total": 500, "min_matched_per_provider": 50}}`), nu tabelă nouă — reutilizează substratul deja folosit de `scheduled_fixtures_shadow_config.py`/`shadow_config.py`.

**Risc numit, nu ascuns**: dacă un provider e structural minoritar (ex. TSDB, aproape mereu în urma altor 5 la discovery), pragul per-provider ar putea să nu fie atins niciodată în practică — poarta rămâne GRAY indefinit pentru acea dimensiune. Nu e un defect de design, e o proprietate corectă (Regula #8: dacă nu există dovadă, rămâne „necunoscut", nu „presupus ok") — dar trebuie observată operațional, nu ignorată. Prag configurabil explicit pentru acest motiv.

### Principiul 7 — `migration_gate` CLI, patru comenzi

```
migration_gate status <gate_key>    # GREEN/YELLOW/RED/GRAY, exit code 0/1/2
migration_gate explain <gate_key>   # verdict + condiții eșuate + root cause dominant + acțiune recomandată
migration_gate attest <gate_key>    # scrie docs/00_GOVERNANCE/gates/<gate_key>.attestation.json
migration_gate verify <gate_key>    # re-derivă din DB, detectează atestare stale/falsificată
```

`explain` — acțiune recomandată per categorie dominantă (lookup static, nu inteligență nouă):

| Categorie dominantă | Acțiune recomandată |
|---|---|
| `MISSING_PROVIDER_ID` | Rulează din nou `sync_scheduled_fixtures.py` pentru providerul afectat |
| `VENUE_PRIORITY` / `LEAGUE_MAPPING` / `KICKOFF_CONFLICT` | Verifică SourcePriority pentru câmpul afectat (migrarea 023) |
| `PROVIDER_TIMEOUT` | Verifică Request Manager/Rate Limit Manager pentru provider |
| `UNKNOWN` | Investigație manuală — cauza nu a putut fi clasificată automat |

### Principiul 8 — Blocare reală: DB autoritar + chitanță offline verificabilă

`test-coverage-guard` interzice testelor accesul la Supabase live — dar testul care blochează *trebuie* să blocheze offline. Rezolvare pe două straturi:

1. **Autoritatea**: `equivalence_evaluations` + view derivat (Supabase) — singura sursă de adevăr, niciodată duplicată.
2. **Chitanța**: `migration_gate attest` scrie un fișier JSON local (`docs/00_GOVERNANCE/gates/<gate_key>.attestation.json`, cu `evidence_digest` sha256 peste rândurile sursă). Un test AST (`tests/test_migration_gate.py`, precedent direct: `test_canonical_feature_ownership.py`) detectează dacă structura care marchează R-Sync-7c (eliminarea unui apel `_fetch_*` din `get_matches_for_week()`) a fost introdusă, și cere atestare `PASS`, nu mai veche de 30 de zile.

**Limită declarată onest**: fișierul de atestare poate fi editat manual de cineva cu acces la repo — nu există semnare criptografică într-un repo controlat de un singur dezvoltator. Ce garantează designul: bypass-ul nu poate fi accidental, și e vizibil în diff (`migration_gate verify` re-derivă din DB și demască o atestare falsificată sau învechită).

## Scope

**În scope**: schema generalizată (`equivalence_evaluations`), regula de scor/verdict, `migration_gate` CLI, aplicarea completă la `entity='scheduled_fixtures'` / `gate_key='R-Sync-7b'`, poarta pentru R-Sync-7c.

**Explicit NEIMPLEMENTAT în acest ADR, dar proiectat ca direcție arhitecturală** — decizie explicită proprietar produs: „ADR-ul trebuie să spună unde merge sistemul, nu doar ce implementează mâine." Diferența dintre „implementat" și „proiectat" e păstrată strict — nimic din secțiunea de mai jos are cod, migrare, sau plan de fază asociat în acest document.

#### Future Extensions (Out of Current Scope)

Infrastructure already supports validation for future entities — schema generalizată (`equivalence_evaluations`, `gate_key` + `entity`, Principiul 2) validează orice tabelă critică nouă fără schemă nouă, doar prin adăugarea unei valori `entity`:

- `scheduled_fixtures` (R-Sync-7b, singura implementată azi)
- `match_stats`
- `team_stats`
- `lineups`
- `injuries`
- `weather`
- `referee_stats`
- `betting_odds`
- `xG`/`xA`
- ML feature tables

Acestea corespund direct viziunii de „Football Data Warehouse complet" (xG, xA, posesie, șuturi, cornere, faulturi, pressing, formații, lineups, accidentări, suspendări, arbitri, stadion, mișcare cote istorică) — investiția pe care proprietarul produsului o consideră, explicit, cu cel mai mare impact asupra predictorului și motorului ML, odată ce Supabase devine complet sursa unică de adevăr. **No implementation in ADR-040. Only architecture direction.** Fiecare intrare nouă necesită propriul audit de provideri/scheme, per disciplina deja aplicată la fiecare R-Sync anterior — nu se adaugă tacit.

#### Future UI Consumers

Consumatori naturali ai `equivalence_evaluations`/`migration_gate`, neproiectați aici, cu propriul ciclu design→aprobare când încep efectiv (posibil **G7**, plan de mai jos):

- **System Health Dashboard** — stare per `entity`, agregat.
- **Migration Gates Dashboard** — stare per `gate_key`, verdict curent + istoric.
- **Provider Quality Dashboard** — `provider_breakdown` agregat pe termen lung, per provider.
- **Data Warehouse Quality Dashboard** — acoperire per tip de dată din secțiunea anterioară.

Scop explicit al acestei liste: peste șase luni, nimeni să nu întrebe „de ce am construit toate astea?" — infrastructura generică (Principiul 2) există special ca să le servească pe toate, nu doar `scheduled_fixtures`.

## Consecințe

- **Pozitive**: R-Sync-7c devine imposibil de început fără dovadă automată, persistentă, re-verificabilă. A2 (cea mai gravă găsire a auditului) se repară prin propria primă utilizare a mecanismului (G1). Infrastructura servește orice etapă viitoare fără schemă nouă.
- **Neutru**: `automation_runs`/`decision_feed` (ADR-026) rămân neatinse — acest ADR adaugă un tip nou de `process_type`, nu schimbă state machine-urile existente.
- **Risc acceptat, numit**: pragul per-provider (Principiul 6) poate să nu fie atins niciodată pentru un provider structural minoritar — poarta rămâne GRAY, nu se relaxează tacit pragul ca să „treacă".
- **Limită acceptată, numită**: atestarea offline (Principiul 8) nu e criptografic inviolabilă — vizibilă în diff, nu imposibil de ocolit.
- **Nu suprascrie ADR-002**: promovarea/rollback-ul automat rămân sub interdicția existentă; acest ADR guvernează procesul de dezvoltare (poate migrarea continua?), nu decizii de producție (poate modelul X deveni campion?) — categorii diferite de risc, tratate diferit deliberat.

## Referințe

- `docs/00_GOVERNANCE/ADR-039-universal-synchronization-architecture-supabase-first.md` — R-Sync-7b, originea acestui ADR.
- `docs/00_GOVERNANCE/ADR-026-automation-decision-governance.md` — `automation_runs`/`decision_feed`, substrat reutilizat.
- `docs/00_GOVERNANCE/ADR-037-learning-core-rollback-and-champion-guardian.md` — precedent direct pentru `health_state` cu stare `insufficient_data` distinctă, MIN/reguli de derivare, imuabilitate append-only (`champion_health_evaluations`, migrarea 015).
- `docs/00_GOVERNANCE/ADR-002-shadow-testing.md` — limita pe care acest ADR nu o traversează (auto-promovare/rollback rămân umane).
