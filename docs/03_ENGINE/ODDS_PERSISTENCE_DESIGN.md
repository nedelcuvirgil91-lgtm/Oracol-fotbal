# docs/03_ENGINE/ODDS_PERSISTENCE_DESIGN.md

## 1. Scop

Acest document proiectează, la nivel de arhitectură, pasul lipsă identificat în auditul read-only: persistarea cotelor de piață (`odds_history`), care astăzi există doar ca date tranzitorii în memorie (`_fetch_odds()`, `_attach_odds()`, `oracle_api.py`). Nu conține cod, SQL sau migrații — doar decizii de design și argumentarea lor.

`odds_history` reprezintă **sursa oficială** pentru orice feature ML viitor bazat pe Closing Line Value (CLV), drift de piață sau mișcarea cotelor. Orice dezvoltare ulterioară (Modulul Machine Learning) trebuie să citească din această tabelă, niciodată direct de la provider — exact principiul deja aplicat pentru `fixture_id` canonic (§5), extins acum și la datele de piață.

---

## 2. Punctul optim din pipeline

Cotele de piață **nu fac parte din lanțul analitic determinist** (`RAW → VALIDATED → BASELINE → EWMA → ... → PREDICTION → SNAPSHOT`, `ARCHITECTURE.md §3`). Sunt date externe, cu ciclu de viață propriu (se schimbă continuu până la kickoff, independent de orice recalculare de indici sau predicție).

**Poziția corectă**: un flux **paralel, independent** de state machine-ul principal, care depinde doar de existența unui `fixture_id` canonic în `VALIDATED` (nu de nicio stare ulterioară — `BASELINE`, `INDEX`, `PREDICTION` etc. sunt irelevante pentru cote). Persistarea nu trebuie să blocheze, nici să fie blocată de, execuția Engine-urilor analitice.

Concret, în codul existent: imediat după `_attach_odds()` (unde `fixture_id` canonic e deja disponibil pe obiectul `match`), dar **în afara** buclei de predicție live — ca pas separat în orchestrarea zilnică (`run_daily.py`), nu în calea de request a aplicației.

---

## 3. Responsabilitatea exactă a noului pas

**Strict trei lucruri, nimic mai mult**:
1. Citește cotele deja obținute (din cache-ul existent, categoria `"odds"`).
2. Mapează fiecare intrare la `fixture_id`-ul canonic deja rezolvat.
3. Scrie/actualizează rândul corespunzător în `odds_history`, respectând regula opening/closing (§5).

**Nu face**: nu calculează probabilități, nu ajustează xG, nu ia decizii de predicție, nu re-fetch-uiește de la provider dacă datele există deja în cache.

---

## 4. Tip de componentă: **Service**

Argumentare, prin eliminare, față de cele patru alternative:

- **Engine nou** — respins. Engine-urile din `ARCHITECTURE.md §4` sunt legate strict de state machine-ul `VALIDATED→...→PREDICTION`, cu determinism definit ca `f(Input, Model Version, Config)`. Cotele nu au `model_version` și nu participă la nicio transformare matematică a predicției.
- **Sub-engine** — respins. Un sub-engine ar presupune o dependență ierarhică de un Engine existent (ex. parte din Baseline). Cotele nu derivă din niciun Engine analitic — sunt captură directă de piață.
- **Pipeline stage** — respins. O "etapă de pipeline" implică o poziție fixă în secvența `RAW→SNAPSHOT`, cu o singură trecere per Execution Unit. Cotele necesită **mai multe capturi în timp** pentru același fixture (opening, apoi actualizări succesive de closing) — incompatibil cu semantica de "etapă unică, o singură trecere".
- **Helper** — parțial corect, dar insuficient ca etichetă principală. Maparea la `fixture_id` (§4 mai jos) e, ea însăși, un helper reutilizat — dar componenta ca întreg, cu propriul program de rulare și propriul ciclu de viață al datelor, depășește sfera unui helper simplu.

**Concluzie**: **Service** — un proces independent, programat, cu propriul ciclu temporal (nu declanșat de o execuție de predicție), analog conceptual cu "market data service". Folosește un helper intern pentru maparea `fixture_id` (§4).

---

## 5. Obținerea `fixture_id` canonic — fără duplicare de logică

Maparea `home_team||away_team → fixture_id` **există deja**, în `_attach_odds()` (`oracle_api.py`), folosind `normalize_team_name()`. Serviciul nou **nu reimplementează** această logică — o consumă direct din rezultatul deja produs de `_attach_odds()` (obiectele `match` care ies din acel pas au deja `fixture_id` atașat).

Riscul de duplicare ar apărea dacă serviciul nou ar re-deriva independent identitatea meciului (ex. un al doilea algoritm de potrivire nume-echipă) — exact tipul de "dublă sursă de adevăr" semnalat deja ca MAJOR în auditul `DATABASE_SPEC.md` (Revizia 3). Regula: **o singură funcție de normalizare, un singur punct de rezoluție a identității**, reutilizate, nu paralelizate.

---

## 6. Tratarea opening / closing / bookmaker / timestamp

Schema existentă (`odds_history`) are **un singur rând per `(fixture_id, bookmaker)`** — nu un rând per captură temporală. Asta impune următoarea semantică:

- **Opening**: valorile `opening_home/draw/away` se scriu **o singură dată**, la prima captură reușită pentru acel `(fixture_id, bookmaker)`. După acest moment, **niciodată** nu se mai ating — imuabile, analog principiului `Raw Data is Immutable`.
- **Closing**: `closing_home/draw/away` se actualizează la **fiecare** captură ulterioară, până la kickoff — reprezintă mereu "ultima valoare cunoscută", nu un istoric complet al mișcării de piață.
- **Bookmaker**: rămâne discriminator în cheia de unicitate (`UNIQUE(fixture_id, bookmaker)`, deja confirmată existentă) — fiecare casă de pariuri are propriul rând.
- **Timestamp**: **REZOLVAT** — schema a fost extinsă (decizie luată explicit, cost minim cât tabela era goală): `fetched_at` (unic) a fost înlocuit cu **`opening_fetched_at`** și **`closing_fetched_at`**, câte unul pentru fiecare moment de captură. Motivul: opening și closing sunt observații distincte în timp — un singur timestamp ar fi făcut imposibilă demonstrarea ulterioară a intervalului real dintre ele, esențial pentru analiza Closing Line Value (CLV), backtesting și modele ML bazate pe mișcarea cotelor.

---

## 7. Modul de persistare — insert / upsert / update / append-only

Ținând cont de principiul de imutabilitate din `DATABASE_SPEC.md §4`, dar aplicat **la nivel de coloană**, nu de rând întreg (o nuanță nouă, nu identică cu regula deja scrisă pentru `analytical`/`predictive`):

1. **Prima captură** pentru `(fixture_id, bookmaker)` → `INSERT`, cu `opening_* = closing_*` (la momentul zero, cele două coincid).
2. **Capturi ulterioare, înainte de kickoff** → `UPDATE`, dar **strict limitat** la `closing_*` și `closing_fetched_at` — `opening_*` (inclusiv `opening_fetched_at`) rămâne intangibil.
3. **După kickoff** → nicio scriere, indiferent de sursă.

Acesta **nu e append-only pur** (care ar însemna un rând nou per captură) — schema actuală (un rând per pereche) face imposibil append-only fără o schimbare de schemă. E, mai degrabă, un **"insert-then-column-scoped-update"** — o formă restrânsă de mutabilitate, aplicată doar acolo unde natura datelor o cere (closing se mișcă până la kickoff, prin definiție).

**Regulă implementată** (`odds_history_guard`, funcție `odds_history_immutability_guard()`, `BEFORE UPDATE OR DELETE`):
1. `INSERT` — permis o singură dată per `(fixture_id, bookmaker)`, deja aplicat via `UNIQUE` existent.
2. `opening_*` (inclusiv `opening_fetched_at`) — completabile doar cât sunt `NULL`; odată setate, orice `UPDATE` care le schimbă e respins.
3. `closing_*` (inclusiv `closing_fetched_at`) — **rămân mutabile**, fără nicio restricție la nivel de trigger — se pot actualiza de oricâte ori, reprezentând mereu "ultima valoare cunoscută" (§6). **Corectare făcută**: o versiune anterioară a acestui trigger bloca greșit rescrierea `closing_*` după prima setare, contrazicând direct §6 — defect real, confirmat live (nu doar teoretic) și corectat.
4. `id`, `fixture_id`, `bookmaker` — niciodată modificabile.
5. `DELETE` — respins necondiționat; mentenanță administrativă posibilă doar prin dezactivare explicită și temporară a trigger-ului (`ALTER TABLE ... DISABLE/ENABLE TRIGGER`).
6. Orice încălcare (regulile 2/4/5) → `RAISE EXCEPTION`, tranzacție anulată complet.

**Separarea explicită de responsabilități** (bază de date vs. Serviciu):
> Enforcement of kickoff eligibility belongs to the Odds Persistence Service. The database trigger enforces only structural immutability (opening values, key columns, delete prevention) — it has no access to `event_date` and cannot, by itself, know whether kickoff has passed. The decision to stop writing `closing_*` for a given fixture is made entirely by the Service, per the eligibility rule in §9.

**Testat exhaustiv, live** — inclusiv re-testare completă după corectarea defectului de mai sus: INSERT inițial, **trei rescrieri succesive ale `closing_home`** (confirmate reușite, valoare finală corect actualizată), rescriere `opening_home` (confirmat blocată), `DELETE` (confirmat blocat), escape hatch de mentenanță (confirmat funcțional).

**Comportamentul la date invalide sau incomplete** (ex. `home=NULL, draw=3.30, away=2.10`; sau cote `≤ 1`, negative, `NaN`): un set incomplet sau invalid de cote e **respins integral** pentru acel `(fixture_id, bookmaker)` — nu se scrie nimic, nici parțial. Motivul: o cotă lipsă sau invalidă indică o problemă de calitate a datelor la sursă (provider), nu o stare de piață reală — scrierea parțială ar produce un rând `odds_history` care arată fals complet, imposibil de distins ulterior de o captură reală, incompletă legitim. Nici `opening_*`, nici `closing_*` nu se ating în acest caz. Serviciul continuă neîntrerupt procesarea celorlalte bookmaker-e și fixture-uri din aceeași rulare — un set invalid izolat nu oprește restul lotului (consistent cu izolarea per-fixture deja stabilită în `PIPELINE_SPEC.md`).

**Validarea este responsabilitatea exclusivă a Serviciului**, executată **înainte** de orice tentativă de `UPSERT` — nu a trigger-ului SQL. Trigger-ul din §7 nu verifică și nu poate verifica validitatea unei cote (nu are nicio noțiune de "cotă ≤ 1" sau `NaN`) — el impune strict imutabilitate structurală (§7, regulile 2/4/5), nimic altceva. Un set de cote invalid nu ajunge niciodată până la trigger, pentru că Serviciul nu emite deloc instrucțiunea SQL în acel caz.

---

## 8. Evitarea duplicatelor, apelurilor și scrierilor inutile

- **Duplicate**: prevenite la nivel de schemă, deja existent (`UNIQUE(fixture_id, bookmaker)`) — orice scriere folosește această cheie pentru conflict-resolution.
- **Apeluri API inutile**: serviciul **nu inițiază fetch-uri proprii** — citește exclusiv din rezultatul deja cache-uit al `_fetch_odds()` (TTL 4h, categoria `"odds"`, deja funcțional). Zero cereri HTTP suplimentare introduse de acest design.
- **Scrieri inutile**: înainte de orice `UPDATE`, se compară valorile noi de `closing_*` cu cele deja stocate — dacă sunt identice, nu se scrie nimic (evită zgomot în `fetched_at` și trafic Supabase fără informație nouă).

---

## 9. Contractul de Scheduler

**Mecanism de declanșare**: reutilizează exact orchestrarea zilnică existentă (`daily.yml` → `run_daily.py`, cron deja funcțional) — niciun workflow nou, niciun proces separat de pornit/monitorizat.

**Regula de eligibilitate per fixture** (rezolvă riscul §12.4, dependența cross-table):
Un fixture e eligibil pentru o tentativă de scriere **doar dacă** `VALIDATED.fixtures.event_date > now()` la momentul rulării. Această verificare aparține exclusiv Serviciului — nu Engine-urilor, nu Pipeline Orchestrator-ului — și e singura dependință de citire în afara `odds_history` însuși.

`validated.fixtures.event_date` este **singura sursă de adevăr** pentru determinarea kickoff-ului. Niciun provider extern (The Odds API sau altul) nu poate influența această decizie în timpul persistării cotelor — data/ora unui eveniment așa cum o raportează un bookmaker e irelevantă pentru eligibilitate.

**Comportamentul când un bookmaker nu mai apare într-o rulare ulterioară** (ex. era prezent ziua 1, absent ziua 2): rândul respectiv **rămâne neschimbat** în `odds_history` — nu se șterge, nu se marchează invalid. Ultima valoare `closing_*` scrisă pentru acel `(fixture_id, bookmaker)` rămâne valoarea finală cunoscută, exact ca și cum acel bookmaker ar fi încetat să actualizeze prețul (interpretare validă din perspectiva CLV — piața "înghețată" la ultima cotă observată). Serviciul nu inițiază nicio acțiune de curățare sau reconciliere pentru bookmaker-i dispăruți.

**Determinarea opening vs. closing, la nivel de scheduler** (nu de schemă — schema/trigger-ul din §7 rămâne neschimbată):
- **Prima rulare eligibilă** pentru un `(fixture_id, bookmaker)` → scrie atât `opening_*` cât și `closing_*` (identice, la momentul zero).
- **Orice rulare eligibilă ulterioară**, până când fixture-ul iese din eligibilitate (kickoff trecut) → scrie doar `closing_*`.
- **Nicio noțiune specială de "closing final"** e necesară: ultima rulare eligibilă înainte de kickoff produce, prin simpla trecere a timpului, valoarea `closing_*` definitivă — cadența zilnică existentă e suficientă, fără mecanism separat de "ultimă șansă".

**Frecvență**: designul nu impune o cadență anume — contractul Serviciului (§4, §7, §9-§10) rămâne valabil indiferent de cât de des rulează. Implementarea actuală reutilizează cadența deja existentă (orchestrarea zilnică, `daily.yml`/`run_daily.py`, o rulare/zi) — o alegere de implementare, nu o cerință de arhitectură. Frecvența poate fi crescută ulterior (relevant mai ales pentru CLV/market drift/steam moves, unde o singură captură/zi oferă vizibilitate limitată asupra mișcării reale a pieței) fără nicio schimbare a semanticii de persistare, a schemei, sau a trigger-ului deja definit.

---

## 10. Contractul de Concurență Atomică

Rezolvă riscul §12.5 (concurență la scriere) printr-un singur mecanism, nu printr-un pattern nou:

**Operațiune unică, atomică**: fiecare scriere e un singur `INSERT ... ON CONFLICT (fixture_id, bookmaker) DO UPDATE SET closing_home = EXCLUDED.closing_home, closing_draw = ..., closing_away = ..., closing_fetched_at = ...` — **fără** un pas separat de verificare-apoi-scriere (`check-then-act`). Elimină complet fereastra de cursă, nu doar o reduce — exact defectul deja identificat și evitat separat, la designul reconcilierii `raw.external_mappings`↔`validated.fixtures`.

**Coloanele `opening_*` nu apar niciodată în clauza `SET`** a acestei operațiuni — nu prin convenție de disciplină în cod, ci prin construcția însăși a instrucțiunii. Trigger-ul din §7 rămâne ca plasă de siguranță (apără împotriva oricărui alt client — SQL manual, dashboard, Edge Function viitoare), dar fluxul normal al Serviciului nu ajunge niciodată să-l testeze, pentru că nu încearcă niciodată operațiunea interzisă.

**Garanție sub concurență reală**: dacă două rulări ating simultan același `(fixture_id, bookmaker)` (retry + rulare programată suprapusă), constrângerea `UNIQUE` existentă face ca operațiunea `ON CONFLICT` să fie serializată la nivel de rând de către Postgres însuși — o singură tranzacție reușește să scrie, cealaltă fie așteaptă, fie aplică propriul `DO UPDATE` pe rândul deja existent, fără duplicare și fără corupere de date, indiferent de ordinea reală de sosire.

**Serviciul este idempotent**: două rulări consecutive pe același set de date (aceleași cote, nemodificate între timp de piață) produc aceeași stare finală în `odds_history`. Consistent cu regula deja stabilită în §8 ("scrieri inutile evitate"): dacă valorile `closing_*` nu s-au schimbat față de rândul existent, a doua rulare nu emite deloc `UPDATE` — nici măcar `closing_fetched_at` nu se atinge. Rezultatul, indiferent de câte ori rulează serviciul pe date neschimbate, e identic: aceeași stare, cu același timestamp al ultimei capturi reale. Consistent cu principiul `Idempotency` din `ARCHITECTURE.md §7`.

---

## 11. Impact asupra documentelor Frozen — necesită ADR nou

| Document | Modificare necesară |
|---|---|
| `DATABASE_SPEC.md` | Adăugare notă explicită: `odds_history` are o excepție de imutabilitate **la nivel de coloană** (`closing_*`, `fetched_at` rămân mutabile până la kickoff; `opening_*` imuabil din prima scriere). Aceasta e o nuanță nouă față de regula "all-or-nothing" deja documentată pentru `analytical`/`predictive` — trigger-ul existent (blocare totală după `SUCCESS`) **nu poate fi reutilizat identic** aici, necesită variantă proprie, scoped pe coloane. Recomand și adăugarea unei a doua coloane de timestamp (`opening_fetched_at`) — gap găsit la §6. |
| `ENGINE_SPEC.md` | Adăugare intrare nouă, categorisită explicit **Service** (nu Engine) — cu graniță de acces: citire `VALIDATED.fixtures` (doar `fixture_id`, `event_date`), scriere exclusiv `odds_history`. |
| `PIPELINE_SPEC.md` | Notă explicită: acest Service rulează **în afara** semantică `Execution Unit`/`pipeline_runs` (nu participă la STARTED/SUCCESS/FAILED/PARTIAL) — are propriul ciclu, declanșat temporal, nu per-fixture. |

**ADR nou necesar**: da — atinge un principiu deja înghețat (imutabilitatea) cu o excepție nedocumentată până acum. Conform `FROZEN_REGISTRY.md`, aceasta e exact motivația validă pentru redeschidere ("contradicție tehnică demonstrabilă... imposibil de reconciliat cu specificația deja înghețată" — aici, nu o contradicție, ci o extindere necesară, dar tot sub controlul unui ADR).

---

## 12. Riscuri tehnice identificate

1. **🟢 REZOLVAT — RLS** — confirmat oficial (documentație Supabase: cheile `sb_secret_...` au atributul `BYPASSRLS`, prin design) și verificat practic (test real INSERT+DELETE, reușit, fără eroare de permisiune). Nu mai e un risc deschis.
2. **🟢 REZOLVAT — Trigger de imutabilitate** — proiectat, implementat și testat exhaustiv live (6/6 reguli confirmate: INSERT unic, opening/closing imuabile independent, coloane-cheie protejate, DELETE blocat, escape hatch de mentenanță funcțional).
3. **🟢 REZOLVAT — Granularitate de timestamp** — schema a fost extinsă cu `opening_fetched_at`/`closing_fetched_at` (aplicat direct, cost zero — tabela era goală). Nu mai e un risc deschis.
4. **🟢 REZOLVAT — Dependență cross-table** — regula de eligibilitate din §9 (`event_date > now()`) o face explicită, nu doar o semnalează.
5. **🟢 REZOLVAT — Concurență la scriere** — contractul din §10 (`ON CONFLICT`, o singură operațiune atomică) elimină complet fereastra de cursă.

---

## 13. Verdict

**☑ FROZEN**

Toate riscurile identificate sunt rezolvate; contradicția §6/§7 (closing mutabil) corectată și re-testată live; regulile pentru bookmaker dispărut, date invalide/incomplete și idempotență sunt explicite. Documentul nu mai are precondiții, ambiguități sau contradicții deschise.

Din acest moment, orice modificare ulterioară a acestui document necesită un **ADR nou** (conform `FROZEN_REGISTRY.md`) — nu editare directă. Poate fi adăugat la registru alături de `ARCHITECTURE.md`, `DATABASE_SPEC.md`, `PIPELINE_SPEC.md`, `ENGINE_SPEC.md`, `CONFIG_SPEC.md`.
