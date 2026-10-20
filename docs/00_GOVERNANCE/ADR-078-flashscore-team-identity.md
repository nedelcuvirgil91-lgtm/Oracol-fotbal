# ADR-078 — Identitatea de echipă a lui Flashscore: Faza 0, observare fără consum

**Status**: ACCEPTED (2026-10-19) — Faza 0 aprobată explicit de proprietarul produsului („Fa faza 0"). Faza 1 (unificarea) **NEAUTORIZATĂ**, decizie separată.
**Atinge**: `providers/flashscore/normalizer.py` (extracție nouă, funcție separată), `providers/flashscore/persistence.py` (cablare ne-blocantă), `database/queries.py` (scriitor + cititor), migrarea 057 (tabelă nouă), `scripts/check_data_health.py` (clasa 8).
**Nu atinge**: nicio formulă, nicio predicție, `match_history`, `normalize_team_name()`, cascada de profil, `_extract_team_names()`.

---

## 1. Context — avem cluburi cu două identități, dar nu colectăm nimic de două ori

Întrebarea proprietarului produsului: „avem cluburi cu 2 profiluri? Colectăm de 2 ori date. Asta nu se poate."

Prima parte e adevărată, a doua nu. Măsurat read-only pe producție:

| Test | Rezultat |
|---|---:|
| Chei naturale duplicate **după normalizarea sufixului** (gazdă, oaspete, zi) | **0** |
| `mid`-uri Flashscore scrise de două ori | **0** din 2196 |

Verificarea anterioară de duplicate folosea numele **exacte**, deci prin construcție nu putea vedea perechea `Levski Sofia` / `Levski Sofia (BUL)`. Refăcută pe cheia normalizată: zero.

Cele două etichete țin **seturi disjuncte de meciuri**:

| Formă | Meciuri | Cu rezultat | Cu statistici | Cu xG real | Perioadă |
|---|---:|---:|---:|---:|---|
| cu sufix | 142 | 142 | 141 | 49 | 14 iul – 27 aug (**calificări**) |
| scurtă | 367 | 286 | 208 | 165 | 20 ian – prezent (**faza ligii**) |

**Deci: două profiluri de identitate, zero date duplicate.** Un club are două „dosare", fiecare cu alte meciuri în el.

### 1.1 Consecința: nu există nimic de șters

Ștergerea formei cu sufix ar distruge 142 de meciuri reale cu rezultat, 141 cu statistici și 49 cu xG real colectat. Ștergerea formei scurte ar distruge faza ligii și ar rupe radarul. **Operația corectă nu e `DELETE`, e redenumire** — Faza 1, decizie separată, nu subiectul acestui ADR.

---

## 2. Cauza — ancorăm identitatea pe eticheta afișată, nu pe identitatea providerului

Flashscore are **un singur** identificator stabil per club, în URL-ul paginii lui. Verificat direct pe HTML-ul salvat în repo (`docs/06_UDAL/poc_evidence/`, 55 de fișiere, **zero apeluri de rețea**):

```
nume afișat: 'Egnatia (ALB)'        →  /team/kf-egnatia/CjYs7BO9/
nume afișat: 'Din. Zagreb (CRO)'    →  /team/din-zagreb/8G5ufQTg/
nume afișat: 'Hearts (SCO)'         →  /team/hearts/0rGrwwNc/
```

`_extract_team_names()` citește textul din `.participant__participantName` — **din interiorul aceluiași container** `duelParticipant__home/away` care conține și `href`-ul. Luăm eticheta și aruncăm identificatorul.

Codul de țară e o **decorație de pagină**, nu identitate. Dovada din propria bază: widget-ul de formă recentă al lui Flashscore scrie `Levski Sofia` simplu, **inclusiv pentru meciurile lui de Europa League** (`flashscore_match_context`, `competition_code = 'EL'`, 17 sep și 15 oct), în timp ce header-ul paginii de calificare scrisese `Levski Sofia (BUL)`. Același provider, același club, două suprafețe, două etichete.

**Flashscore nu are două profiluri. Noi am creat al doilea.**

### 2.1 Mecanismul de unificare existent nu e defect — e incomplet

`_COUNTRY_SUFFIX_RE` (ADR-058 §2.3) dezbracă sufixul, dar **strict ca cheie de căutare**: rezolvă doar dacă forma dezbrăcată e deja un alias cunoscut. Verificat rulând codul real pe 26 de nume: **4 rezolvate, 22 nu**. Nu e un bug — e regula „niciodată ghicit" aplicată corect peste un dicționar incomplet. Altfel un ipotetic `Nacional (POR)` și `Nacional (URU)` ar fi unite tăcut.

### 2.2 Golul de arhitectură, măsurat

`scheduled_fixtures` stochează id-ul de echipă pentru **cinci** provideri: `apifootball_`, `espn_`, `fd_`, `freelf_`, `tsdb_`. Pentru Flashscore — **niciunul**. Tiparul exista deja; providerul devenit primă linie nu a fost adăugat la el.

Contrastul care arată că tiparul funcționează: **identitatea MECIULUI e deja ancorată pe id-ul Flashscore** (`fixture_id = flashscore_<mid>`) — exact de aceea am găsit zero duplicate de meciuri. Identitatea **clubului** e singurul loc rămas pe un șir de caractere. Faza 0 nu introduce un principiu nou; îl extinde pe cel deja dovedit.

---

## 3. Costul real, măsurat cap-coadă — mai mic decât pare

Rulat prin formulele adevărate (`elo_to_offensive_multiplier` → `compute_team_offdef_rating` cu `elo_blend_weight` din `weights.json` → `calibrate_xg` → Poisson), cu profilul statistic identic în ambele scenarii:

| Canal | Efect măsurat |
|---|---|
| **ELO** | mediana celor 13 echipe: **−0,43 pp** pe P(1); cazul cel mai rău **−0,72 pp** |
| **H2H** | **exact zero** — poarta cere ≥3 întâlniri; 120 de perechi au întâlniri ascunse, dar maximul pe orice pereche după unificare e **2**, deci nicio pereche nu ar trece pragul |
| **Forma** | `MIN_DB_MATCHES = 3`, iar cele 13 au 1-2 meciuri sub numele scurt → Level DB eșuează. **Dar nu cad pe constante**: `flashscore_match_context` are 10-20 de rânduri sub numele scurt pentru toate 13, deci Level FS2 le prinde, cu meciuri reale |

**Deci cele „−67 de puncte ELO" devin 0,7 puncte procentuale în predicția servită.** ELO intră cu pondere 0,35 într-un rating care trece apoi prin saturări și prin Poisson.

**Încadrarea corectă**: nu sunt predicții greșite, sunt două istorii pentru un singur club. Problema e **North Star #9** (trasabilitate completă până la sursă), nu calitatea predicției.

**Lecție de metodă, consemnată**: am raportat prima dată „−67 ELO", cifra spectaculoasă, în loc de cifra relevantă (predicția). Un delta pe o mărime intermediară nu e un delta pe rezultat — iar ordinea de prioritate pe care o propusesem se sprijinea pe cifra greșită.

---

## 4. Decizie — Faza 0: se captează, nu se consumă

Se adaugă o tabelă de **observație**, `flashscore_team_identity` (migrarea 057), care înregistrează ce etichete apar pentru fiecare `flashscore_team_id`. Nimic nu o citește ca sursă de identitate.

**De ce o fază care nu repară nimic:** harta `id → nume` nu există azi, deci unificarea s-ar sprijini pe deducția mea din 55 de fișiere salvate. Faza 0 o produce din date vii, în câteva zile, și — mai important — face următoarea apariție **detectabilă automat**. Fenomenul a început pe 29 iulie și a fost găsit pe 19 octombrie, din întrebarea proprietarului produsului despre ELO-ul Borussiei, nu din vreun monitor. **Clasa 8 ar fi declanșat pe 29 iulie.**

### 4.1 Ce s-a construit

- **`_extract_team_identities()`** — citește `href`-ul **din același container semantic** ca numele. Container absent, link absent, nume gol ⇒ `None`, niciodată ghicit (Regula #8).
- **`normalize_team_identities()`** — funcție **separată** de `normalize_match_statistics()`. RPC-ul canonic ignoră cheile necunoscute, deci o cheie în plus ar fi fost inofensivă — dar „inofensiv" nu e un motiv să modifici contractul care scrie în `match_history`.
- **`upsert_team_identity()`** — `on_conflict="flashscore_team_id,display_name"`, deci „un id cu două nume" devine **două rânduri**, nu o suprascriere.
- **`get_team_identity_drift()`** — paginat keyset (a șasea apariție a plafonului PostgREST de 1000 în acest proiect), lista **goală** la eroare, nu setul parțial.
- **Clasa 8 în `check_data_health`** — prag **zero absolut**. Tabelă goală ⇒ „insuficiente date", niciodată „sănătos" (Regula #8).
- **Flag `flashscore_team_identity_capture_enabled`, implicit `False`** (North Star #3).

### 4.2 Trei decizii de proiectare care protejează prima linie

1. **Captarea stă în AFARA lui `steps`, deci în afara lui `ok`.** `run_foundation_data_layer.py` întoarce exit code 1 la orice eșec parțial (389/393 = 99% a fost tot roșu pe 20 august). O observație care nu schimbă nicio predicție nu are voie să înroșească rularea care aduce datele reale. Plus `try/except` din care nicio excepție nu scapă. **Gardă AST dedicată**, care cade dacă cineva mută captarea în `steps`.
2. **Identitatea se citește din containerul semantic, nu din pagină.** `og:url` poartă și id-urile echipelor (`.../fc-botosani-GjY1JjUS/rapid-bucuresti-YFCpigVG/?mid=...`) și ar fi fost o a doua sursă — **respinsă**: atribuirea pe laturi ar veni din **ordinea** din URL, exact mecanismul inversării de teren reparate pe 2026-08-23. Gardă dedicată: un link de echipă plantat în afara containerelor nu devine identitate.
3. **Eticheta se scrie BRUTĂ.** Inversare deliberată a precedentului din `upsert_standings_snapshot()`, care normalizează tocmai ca potrivirea exactă să funcționeze. Aici scopul e opus: normalizată, ambele forme ale aceluiași club ar colapsa în una și tabela ar raporta mereu „un id, un nume" — adică ar ascunde exact fenomenul pentru care există.

### 4.3 Ce NU face Faza 0

Nicio predicție schimbată. Niciun rând șters. Nicio redenumire. Niciun ELO recalculat. `match_history` neatins. `normalize_team_name()` neatins. `_extract_team_names()` neatins, deci orientarea gazdă/oaspete nu depinde în niciun fel de codul nou.

---

## 5. Verificare

- **24 de teste noi** (`tests/test_flashscore_team_identity.py`), inclusiv pe **HTML-ul REAL salvat în repo** — pagini domestice (fără sufix) și o calificare UCL (cu sufix), cu aserțiune că ambele cazuri sunt acoperite.
- **7 mutații, toate prinse**: linkul căutat în toată pagina · eticheta normalizată la scriere · `last_seen_at` scos · captarea mutată în `steps` · poarta flagului ștearsă · paginarea scoasă · `first_seen_at` pus în payload.
- `last_seen_at` scos a fost prins **și** de garda centrală de clasă (`tests/test_upsert_timestamp_freshness.py`), la care tabela a fost adăugată **odată cu scriitorul**, nu după ce ar fi înghețat tăcut. `first_seen_at` NU e în acea listă, deliberat: el trebuie să reziste pe ramura `DO UPDATE`.
- **Două gărzi existente au căzut la adăugarea clasei 8** (`findings}/7` → `/8`) — exact cum au fost proiectate: „fragilitatea e scopul gărzii". Actualizate, nu slăbite.
- `pytest tests/`: **3589 passed, 2 skipped** (3565 + 24, aritmetica se închide; zero teste umbrite).

---

## 6. Consecințe

**Pozitive**: încetăm să pierdem o informație pe care Flashscore o dă gratis, în același element din care citim deja. Următoarea apariție — iulie 2027, la calificări — devine detectabilă în ziua în care apare. Harta pe care Faza 1 are nevoie se construiește din date vii, nu din deducția mea.

**Negative, acceptate conștient**: o tabelă în plus și o scriere în plus per meci (două rânduri, `upsert`), pentru o informație pe care azi nimeni nu o consumă. Costul e real și mic; alternativa e să decidem Faza 1 fără hartă.

**Ce NU rezolvă**: cele 330 de rânduri existente rămân sub forma cu sufix, iar cele 13 cluburi rămân cu lanțuri ELO despicate. Faza 0 nu repară nimic — face reparația decidabilă.

---

## 7. FAZA 1 — EXECUTATĂ 2026-10-19, dar pe un scop mai mic decât cel estimat

**Aprobată explicit** de proprietarul produsului. **Harta din Faza 0 NU a fost necesară**, și motivul e verificabil, nu o scurtătură: proprietatea de care aveam nevoie — că dezbrăcarea sufixului nu poate uni cluburi distincte — e deja auditată (ADR-058 §2.3, pe 58.299 de rânduri), iar am **reverificat-o pe datele de azi**: zero baze produse de două coduri de țară diferite, zero meciuri între cele două forme ale aceluiași club.

### 7.1 Măsurătoarea care a redus scopul de la 103 la 13

Rulând codul real pe toate cele 100 de nume cu sufix:

| Clasă | Câte | Ce s-a făcut |
|---|---:|---|
| **Se rezolvau DEJA** prin stratul de alias | **33** | nimic — `Arsenal FC (ENG)`→`Arsenal`, `FC Internazionale Milano (ITA)`→`Inter Milan`, `FC Red Bull Salzburg (AUT)`→`Salzburg` |
| **Grupul A** — bază cu geamăn REAL în bază | **13** | **reparate** (vezi mai jos) |
| Văzute DOAR cu sufix, fără geamăn | **~49** | **neatinse** — vocabular, nu reparație |
| Nume oficiale lungi ale unor cluburi existente sub alt nume | **~5** | **neatinse, deliberat** |

**Doar Grupul A era „un club cu două profiluri"** — restul au un singur profil care se întâmplă să poarte un sufix. Estimarea mea anterioară („632 de rânduri, 3 tabele") descria dezbrăcarea TUTUROR celor 330 de rânduri; reparația reală a cerut **57 + 99 = 156**.

### 7.2 Reparația e o REGULĂ, nu 13 perechi

`ALIAS_TO_CANONICAL[_canonical.lower()] = _canonical` (`mappings.py:629`) — numele canonic e el însuși cheie de căutare. Deci adăugarea bazei ca **intrare canonică** face ca forma cu sufix să se rezolve **singură**, prin `_COUNTRY_SUFFIX_RE` (ADR-058 §2.3). 13 intrări, nu 13 mapări explicite — și orice club viitor cu același tipar se rezolvă fără cod nou, odată ce numele lui simplu e cunoscut.

`TEAM_ALIASES`: **388 → 401 chei, toate unice** (verificat prin AST — capcana Salzburg, unde o cheie duplicată a fost înghițită tăcut de Python și suita a rămas verde).

### 7.3 Backfill-ul

`UPDATE` atomic, idempotent, într-o singură instrucțiune cu `RETURNING`: **57 de rânduri în `match_history`, 99 în `shadow_predictions`** — exact cifrele prezise înainte de rulare.

Constrângerea reală verificată înainte: indexul unic pe cheia naturală e **parțial** (`WHERE superseded_by IS NULL`) — exact setul pe care am măsurat **0 coliziuni**. La `shadow_predictions` cheia unică nu conține numele echipelor, deci nu putea fi violată.

**După**: 0 rânduri Grupul A rămase cu sufix în ambele tabele; 0 duplicate pe cheia naturală; **293** de rânduri rămase cu sufix (alte cluburi). Aritmetica se închide exact: 330 − 57 + **20** = 293, cele 20 fiind rânduri unde adversarul a rămas sufixat fiindcă nu e în Grupul A.

`consensus_capture_samples`: **19 rânduri rămân sub forma cu sufix** — tabela e strict append-only prin trigger. Nu e un rest de curățat, e o regulă respectată; orice monitorizare trebuie să le **excludă**.

### 7.4 Ce s-a schimbat efectiv în predicție

**Lanțul de meciuri e unificat**: Levski Sofia 2 → **9** meciuri terminate, Omonia 2 → 8, Egnatia 1 → 7. Deci H2H și forma văd acum toate meciurile clubului.

**ELO-ul NU a fost recalculat retroactiv** — precedentul Salzburg (17 oct). Valorile `*_elo_after` din rândurile istorice rămân cele calculate pe lanțurile separate; ce s-a schimbat e că de acum există **un singur lanț** pe care căutarea îl găsește.

**Consecința (c) din decizie e acum ÎN EFECT**: cu 4-9 meciuri terminate per club, `MIN_DB_MATCHES = 3` e satisfăcut, deci cele 13 trec de la **Level FS2** (formă pe toate competițiile, 10-20 de meciuri) la **Level DB** (formă în competiție, 4-9). Troc acceptat conștient: semnal mai potrivit pentru cupe (dispersie 2,0 ppm, `DE_URMARIT` §2c), eșantion mai subțire.

### 7.5 Ce rămâne, și de ce nu l-am făcut

**~5 nume oficiale lungi** ale unor cluburi care există deja sub alt nume canonic — `FC Bayern München`, `Club Atlético de Madrid`, `ŠK Slovan Bratislava`, `Dyn. Kyiv`, `Din. Minsk`. A le „rezolva" prin dezbrăcare ar crea o **a doua identitate permanentă** (`FC Bayern München` lângă `Bayern Munich`), adică ar înlocui un orfan cu alt orfan — zero câștig, plus agitație. A le mapa corect cere cunoaștere de domeniu, exact unde proiectul interzice ghicitul. **Decizie separată, necerută.**

**~49 de cluburi văzute doar cu sufix** — adăugarea bazelor lor ar fi igienă de vocabular, nu reparație: nu există niciun al doilea profil cu care să se unească.

**Caz special de reținut**: `Kauno Zalgiris` (Kaunas) și `Zalgiris` (Vilnius) sunt cluburi **DIFERITE**. Dezbrăcarea le păstrează distincte, iar `Zalgiris` **nu** a fost adăugat ca nume canonic tocmai ca să nu existe tentația unei uniri. Gardă dedicată.

### 7.6 Verificare

- **30 de teste noi** în `tests/test_team_identity_invariants.py`: cele 13 se rezolvă, forma scurtă e canonicul (nu alias al altcuiva), cele două Zalgiris rămân distincte, idempotență.
- **O gardă existentă a căzut, corect**: `test_f3_suffixed_without_known_base_stays_unchanged` avea `Inter Escaldes (AND)` în parametri — premisa „fără geamăn în `match_history`" era adevărată în august și nu mai e. Scos, cu notă datată, și **înlocuit cu cazurile riscante** (`FC Bayern München (GER)`, `Club Atlético de Madrid (ESP)`, `Larne (NIR)`) — deci garda a devenit mai strictă, nu mai slabă.
- **4 mutații, toate prinse**: o intrare din Grupul A ștearsă · `Zalgiris` adăugat ca nume canonic · o bază redirectată ca alias al altui club · regula `_COUNTRY_SUFFIX_RE` dezactivată (21 de teste căzute).
- `pytest tests/`: **3619 passed, 2 skipped** (3589 + 30, aritmetica se închide).

### 6.1 Faza 1 — estimarea INIȚIALĂ, păstrată ca istoric

Scopul unei unificări, măsurat pe fiecare tabelă:

| Tabelă | Rânduri cu sufix |
|---|---:|
| `match_history` | 330 |
| `shadow_predictions` | 252 |
| `consensus_capture_samples` | **50 — APPEND-ONLY, intangibile** (trigger la nivel de bază) |
| `elo_ratings`, `elo_history`, `flashscore_match_context`, `scheduled_fixtures`, `flashscore_standings_snapshot`, `match_events`, `player_match_stats`, `upcoming_matches`, `value_selector_shadow` | **0** |

**632 de rânduri, 3 tabele** — rază de acțiune mai mică decât la Salzburg (256 de rânduri pe 7 tabele). Verificarea care a cerut grijă în august (coliziunea Rijeka–Dinamo Zagreb) e deja făcută: **zero chei duplicate după normalizare**, deci o redenumire spre forma scurtă nu produce nicio coliziune.

Decizia are trei părți, care nu se separă: (a) forma canonică — sufixul devine alias sistematic, sau club cu club; (b) ce se face cu cele 330 de rânduri istorice; (c) dacă se acceptă mutarea celor 13 din FS2 în Level DB — **un troc, nu un câștig curat**: forma europeană e semnalul mai potrivit pentru un meci de cupă (dispersia măsurată campionat→UCL e 2,0 ppm, `DE_URMARIT` §2c), dar e mai subțire (3-9 meciuri în loc de 10-20).

**ELO-ul nu se recalculează retroactiv la unificare** — precedentul Salzburg (17 oct) a stabilit asta explicit.

### 6.2 Activare

Două lucruri, în ordine, fiecare cu confirmare explicită:

1. **Migrarea 057** — SQL arătat integral înainte de rulare (North Star #6). Până atunci codul e inert: flagul e oprit, deci nimic nu scrie.
2. **`UPDATE model_config`** pentru `flashscore_team_identity_capture_enabled = true`, cu amprentă `md5` înainte/după, ca la ADR-072 și ADR-073.

**[VERIFICAT PE PRODUCȚIE — 2026-10-19, rularea FDL `39322557559`, `success`]** 28 de rânduri, 28 de id-uri distincte, 28 de nume distincte, 0 fără `team_slug`, pe 14 meciuri din 8 competiții.

**Două rezultate care corectează așteptările scrise mai sus:**

1. **Sufixul de țară apare și în sezonul în curs**, nu doar la calificări. `Iberia 1999 (GEO)` și `Jagiellonia (POL)` au fost captate cu eticheta intactă pe 19 octombrie. Prognoza mea („driftul va fi zero până în iulie") era prea pesimistă. Confirmă totodată decizia de a scrie eticheta **brută**: normalizată, ambele ar fi colapsat și tabela n-ar fi arătat nimic.
2. **Comparația `last_seen_at` vs `first_seen_at` NU e fiabilă la nivel de secundă.** Pe 4 din 28 de rânduri, `last_seen_at` e cu o secundă *înaintea* lui `first_seen_at` — fiindcă primul vine din `DEFAULT now()` (serverul Postgres) și al doilea din `_acum_utc()` (runnerul GitHub, calculat înainte de `INSERT`). **Două ceasuri, nu un defect de scriere.** Verificarea „egale la prima vedere" din §6.2 e deci greșită ca test și se scrie cu toleranță. Detecția de îngheț rămâne validă: o a doua vedere mută marcajul cu minute sau ore.

   Clasa e mai largă decât tabela asta — toate cele 6 instanțe reparate pe 2026-08-26 scriu marcajul din client; acolo e invizibil fiindcă au o singură coloană de timp. **Nereparat**: a scrie `last_seen_at` server-side ar contrazice garda care impune `_acum_utc()` (`tests/test_upsert_timestamp_freshness.py`).

**Rămâne NEexercitat**: cele 28 de rânduri sunt 28 de cluburi distincte, fiecare văzut o singură dată, deci „`last_seen_at` avansează la a doua vedere" se testează abia la prima rulare care reprocesează un club deja văzut.
