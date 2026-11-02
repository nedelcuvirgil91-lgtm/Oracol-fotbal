# ADR-081 — Corpul răspunsului eșuat se persistă în `provider_call_log`

**Status**: **ACCEPTED** (aprobat explicit de proprietarul produsului, 2026-10-22)
**Data**: 2026-10-22
**Autor**: sesiune Claude Code, la cererea proprietarului produsului
**Legat de**: ADR-041 (Provider Call Log), ADR-077 (ruta SFI — deschis, blocat
exact de absența acestui câmp)

---

## 1. Context — trei căi încercate azi, toate închise

`soccerfootballinfo` răspunde **HTTP 400 pe 100% din apeluri** din 11 octombrie:
72 de apeluri, zero reușite, ultimul azi la 07:25. ADR-077 nu poate fi decis
fără **motivul** refuzului, iar RapidAPI îl pune în corpul răspunsului.

Corpul **se calculează deja** — `soccerfootballinfo_client._corp_diagnostic()`,
instrumentare adăugată pe 20 oct — și se scrie într-un `logger.warning`.
Problema nu e că lipsește: e că **nu poate fi citit**.

| Calea încercată | Rezultat măsurat, azi |
|---|---|
| Artefactul `logs/` al rulării (315 KB, există) | **Blocat** — redirect către `productionresultssa3.blob.core.windows.net`, refuzat de politica de rețea a containerului |
| Coada log-ului `night_sync` prin API GitHub | **400 de linii acoperă 58 de secunde** (08:37:23→08:38:21). Apelurile SFI sunt la **07:25:25**, cu 73 de minute mai devreme |
| `daily.yml` rulat manual | `results` e **PRIMUL** pas din `PIPELINE_STEPS` — liniile ar fi iar la capătul opus cozii |

**Clasa de defect e deja documentată de trei ori în acest proiect**: o valoare
calculată corect, cablată corect, și niciodată ajunsă la cineva —
`step_durations_s` (calculat, aruncat la ultima linie), raportul pe etape al
lui `night_sync` (tipărit, nepersistat), artefactul `logs/` promis din iulie și
produs abia în august.

---

## 2. Decizie

**`provider_call_log` capătă o coloană `error_body text`, nullable, scrisă
EXCLUSIV pe eșec.**

1. **Un singur punct de scriere**, cel existent:
   `supabase_client.record_provider_call()`. Parametrul e opțional, deci cei
   doi apelanți actuali rămân valizi fără nicio schimbare.
2. **Pasat prin `RequestManager.record_result()`**, deci **orice adaptor nou de
   Sync Layer îl capătă gratuit**, fără să reimplementeze nimic — exact
   contractul ADR-041 Faza 1 („punct unic de scriere pentru cod NOU").
3. **Garda de succes e în calea de scriere, nu în apelant**: dacă
   `success = True`, `error_body` se forțează la `NULL` indiferent ce pasează
   apelantul. Un apelant neatent nu poate umple tabela cu corpuri de răspunsuri
   reușite.
4. **Plafon la scriere, nu doar la sursă**: `_corp_diagnostic()` trunchiază deja
   la 400 de caractere, dar `record_provider_call()` nu are voie să aibă
   încredere în apelant. Al doilea plafon, independent.
5. **Se cablează azi DOAR la `soccerfootballinfo`** — providerul cu defectul
   real. Restul capătă capacitatea, nu valoarea.

---

## 3. De ce asta și nu un POC — argumentul tehnic, nu cel economic

Alternativa evaluată: un workflow temporar care face un singur apel SFI și
tipărește corpul (tiparul folosit pentru API-Football, SofaScore, Transfermarkt).

**Respinsă, și motivul principal nu e costul**: un POC construiește o
**replică** a cererii de producție. Cererea reală se compune în
`SoccerFootballInfoClient._get()` din cale, parametri și header-e proprii; dacă
replica diferă într-un detaliu, poate să nu mai primească 400 deloc — și atunci
n-am aflat nimic, doar am cheltuit o rundă. **Varianta aleasă captează corpul
de pe calea reală, prin construcție.**

Argumentele secundare, în ordine:

- **Costul e mărginit de mecanisme care există deja**: `_corp_diagnostic()`
  trunchiază la 400 de caractere, iar `provider_call_log` are **retenție de 9
  zile** (`cleanup_provider_call_log(retention_days=9)`, rulată nocturn). La
  ritmul actual al SFI: 9 × 400 B × 9 zile ≈ **32 kB**.
- **Nicio scurgere de secret**: cheia RapidAPI circulă exclusiv în header-ul de
  **cerere**. Corpul răspunsului nu o conține — proprietate deja documentată în
  comentariul de lângă `_corp_diagnostic()`, nu o presupunere nouă.
  > **⚠️ [AMENDAMENT 1, 2026-11-02 — argumentul ăsta e SPECIFIC PROVIDERULUI,
  > nu general. Vezi §8.]** Rândul de mai sus rămâne **neatins**, fiindcă era
  > adevărat la data lui și pentru providerul la care se referea (North Star
  > #9 — un document nu se rescrie retroactiv). Dar nu se mai poate cita ca
  > proprietate a coloanei: Odds API trimite cheia ca **parametru de query**.
- **Întârzierea nu costă nimic**: SFI eșuează de ~9 ori pe noapte, deci corpul
  intră singur în tabelă la prima rulare. ADR-077 e deschis din 17 oct,
  providerul mort din 11 oct — o zi în plus pe o cale care produce deja zero nu
  schimbă nimic.
- **Un POC răspunde o dată și se șterge.** Proiectul a avut **cinci** rupturi de
  provider în trei luni (cotă FreeLF, plan API-Football, Akamai SofaScore, WAF
  Transfermarkt, selectorii Flashscore). Fiecare a cerut o investigație proprie.
  Asta transformă clasa într-un `SELECT`.

---

## 4. Ce NU face

- **Nu scrie corpul pe succes** (§2 pct. 3) — nici dacă apelantul îl pasează.
- **Nu ridică plafonul de 400 de caractere.**
- **Nu rescrie retroactiv** cele 72 de rânduri existente: corpurile lor nu mai
  există nicăieri. Rămân cu `error_body = NULL`, corect — necunoscut, nu
  aproximat (Regula #8).
- **Nu cablează `football_providers.py`** (API-Football), deși trece prin
  `record_provider_call()` direct. Ar cere propriul echivalent de
  `_corp_diagnostic()`; capacitatea există de acum, valoarea se adaugă când
  apare nevoia.
- **Nu atinge calea de predicție.**

---

## 5. Ordinea de execuție — INVERSĂ celei de ieri, și motivul e altul

**Migrarea rulează ÎNAINTE de merge-ul codului.**

Dacă ar fi invers, `record_provider_call()` ar trimite un `INSERT` cu o coloană
inexistentă; PostgREST ar respinge **tot rândul**, iar eșecul e înghițit de
`except Exception: logger.debug(...)` — deci **scrierea în `provider_call_log`
s-ar opri tăcut**, pentru toți providerii, până la aplicarea migrării. Exact
clasa de defect pe care acest ADR o repară.

La Clasa B din D-13 (19 oct) ordinea era inversă — merge întâi — fiindcă acolo
producția ar fi recreat rânduri orfane peste un backfill proaspăt. **Regula nu e
„întâi codul" sau „întâi baza", e „întâi precondiția".**

### Migrarea (de arătat și confirmat înainte de rulare, North Star #6)

```sql
-- 058_provider_call_log_error_body.sql
ALTER TABLE provider_call_log
    ADD COLUMN IF NOT EXISTS error_body text;

COMMENT ON COLUMN provider_call_log.error_body IS
    'ADR-081: corpul raspunsului, DOAR pe esec, trunchiat la 400 de caractere. '
    'NULL pe succes, prin garda din record_provider_call(). Cheia API nu poate '
    'ajunge aici: circula exclusiv in header-ul de CERERE.';
```

**Nu creează nicio tabelă**, deci garda `tests/test_migration_grants.py`
(pragul 058) nu i se aplică — verificat explicit:
`_RE_CREATE_TABLE.search("ALTER TABLE …")` → `False`. Tabela existentă își
păstrează grant-urile, deci nici regula Supabase de la 30 octombrie nu se
aplică.

---

## 6. Consecințe

**Pozitive**
- Motivul oricărui eșec de provider devine interogabil, nu doar logat.
- ADR-077 se poate decide la prima rulare de după, cu dovada, nu cu o ipoteză.
- Orice adaptor nou prin `RequestManager` capătă capacitatea gratuit.

**Negative, acceptate**
- Un câmp în plus pe calea de scriere a fiecărui apel de provider. Mitigat: e
  `None` pe succes, deci costul real apare doar la eșecuri.
- Corpurile celor 72 de apeluri deja eșuate sunt pierdute definitiv.

**Neutre**
- Zero schimbare de comportament în servire, predicție sau poarta de promovare.
- Zero tabelă nouă, zero RLS, zero `GRANT`.

---

## 7. Verificare — EXECUTATĂ (2026-10-22)

1. **`pytest tests/`: 3855 passed, 2 skipped.** Aritmetica se închide exact:
   baseline măsurat pe arborele curat **3828**, fișierul nou colectează **27**
   de teste, 3828 + 27 = 3855. Deci niciun test umbrit (clasa prinsă pe 21 oct
   prin `tests/test_no_shadowed_tests.py`).
2. **Calea de predicție neatinsă**, verificat: `git diff --stat` pe
   `oracle_engine.py`/`feature_engine.py`/`ml_predictor.py`/`recalibration.py`/
   `app.py`/`oracle_api.py` e **GOL**.
3. **7 mutații, toate prinse:**

   | Mutație | Teste căzute |
   |---|---:|
   | garda de succes ștearsă | 3 |
   | plafonul de scriere scos | 3 |
   | parametrul brut în `INSERT` (garda ocolită) | 3 |
   | parametrul nepasat prin `RequestManager` | 3 |
   | corpul necalculat la SFI (`error_body=None`) | 2 |
   | corpul calculat de DOUĂ ori (log și coloană pot divergea) | 1 |
   | trunchiere de la coadă, nu de la început | 1 |

4. **Starea măsurată înainte de migrare** (read-only, 2026-10-22):
   `provider_call_log` are **9 coloane**, `error_body` **absentă**;
   `soccerfootballinfo` — **72 de apeluri, 0 reușite**, primul 13 oct 09:12,
   ultimul **22 oct 07:25**.
5. **La prima rulare de noapte după merge**: `error_body` populat pe rândurile
   `soccerfootballinfo` cu `success = false`, și **NULL** pe orice rând cu
   `success = true`.

### Descoperire în timpul verificării — gărzile existente au funcționat

Lărgirea semnăturii a **rupt 8 teste existente**, în trei fișiere, și fiecare
eșec era comportamentul corect:

- `tests/test_supabase_client.py` — o asserțiune de **egalitate exactă** pe
  payload-ul `INSERT` a prins lărgirea contractului. Exact rolul ei. Actualizată
  ca să afirme acum și garda de succes: un apel **reușit** scrie `NULL`.
- `tests/test_request_manager.py` (2 fals-uri) și
  `tests/test_soccerfootballinfo_client.py` (1 fals, 7 teste) — fals-uri cu
  semnătură **strictă**, care au aruncat `TypeError` la parametrul nou.

**Reparate adăugând `error_body=None` EXPLICIT, nu `**kw`** — și motivul e
tehnic, nu stilistic: `RequestManager.record_result()` înghite orice excepție
prin `except Exception: pass`. Un fals cu `**kw` ar fi rămas verde la o
divergență viitoare de semnătură, în timp ce în producție scrierea în
`provider_call_log` s-ar fi oprit **tăcut**. Fals-ul strict transformă acea
clasă de defect într-un eșec zgomotos de test. Aceeași lecție ca la clientul
fals din reparația D-10, care nu emula plafonul implicit PostgREST.

---

## 8. Amendament 1 (2026-11-02) — „nicio scurgere de secret" era o proprietate a providerului, nu a coloanei

**Status**: ACCEPTED (aprobat explicit de proprietarul produsului, 2026-11-02,
varianta (a) din trei prezentate). **Cod deja pe `main`**: `1cb1e77` (garda),
`356ef79` (cablarea), `8bf3385` (gărzile).

### 8.1 Ce s-a dovedit fals

§3 susține, ca argument secundar al deciziei de a stoca deloc corpul:

> *„Nicio scurgere de secret: cheia RapidAPI circulă exclusiv în header-ul de
> **cerere**. Corpul răspunsului nu o conține."*

Afirmația e **adevărată pentru SoccerFootballInfo** — RapidAPI autentifică prin
header — și **falsă pentru The Odds API**, unde cheia e **parametru de query**
(`?apiKey=…`). Un provider care își reflectă cererea în corpul erorii ar fi
scris cheia în `provider_call_log.error_body`.

ADR-ul nu a greșit: la 22 octombrie exista **un singur** apelant, iar pentru el
argumentul era verificat. Greșeala ar fi fost să-l citim ca proprietate a
coloanei atunci când al doilea apelant a apărut.

### 8.2 Clasa, care e mai importantă decât cazul

**Un ADR nou invalidează tacit precondiția altuia.** Exact clasa documentată de
**ADR-077**, unde ADR-044/045 a adus Flashscore ca al doilea scriitor al lui
`referee` și a transformat criteriul de rutare al ADR-041 în unul care întorcea
0 pe orice fereastră — nedetectat **39 de zile**.

Diferența, și singurul motiv pentru care costul e zero aici: acolo s-a
descoperit *după*, aici *înainte de cablare*. Nu din noroc — din regula că o
extindere se verifică față de argumentele scrise ale ADR-ului pe care îl
extinde, nu doar față de cod.

**Rămâne adevărat golul mai larg, deja consemnat în `CLAUDE.md` D-12**: nimic
nu detectează azi când un ADR nou adaugă al doilea scriitor — sau al doilea
apelant — pe ceva ce altul folosește ca premisă. Garda ADR-036 acoperă strict
`FEATURE_COLUMNS`.

### 8.3 Ce se schimbă

**§2 (Decizie) rămâne neatinsă.** Coloana, plafonul de 400 de caractere,
retenția de 9 zile și garda „pe succes se scrie NULL" sunt toate neschimbate.

Se adaugă **a treia gardă în calea de scriere**, lângă celelalte două, exact
unde §2 pct. 3 spune că trebuie să stea („gărzile nu stau în apelant"):

- `supabase_client._redacteaza_secrete()` — funcție **pură**, aplicată de
  `_error_body_de_scris()` **înaintea** trunchierii. Ordinea e load-bearing:
  trunchierea întâi ar tăia secretul la jumătate, iar jumătatea rămasă e tot o
  scurgere. Test dedicat.
- Două plase, una pe **nume de parametru** (`apiKey`, `token`, `secret`,
  `password`, `auth`, …) și una pe **valoare** (șiruri de ≥32 hexazecimale —
  cheia Odds API are exact 32).
- `key` **simplu** e deliberat **în afara** listei: răspunsurile Odds API conțin
  legitim `{"key": "soccer_epl"}`, iar redactarea lui ar distruge exact
  diagnosticul pentru care coloana există. Contrapondere dedicată în teste.

### 8.4 Limita, declarată ca test

Redactarea e pe **tipar**, nu pe valoare — `supabase_client` nu importă
`key_manager` și nici nu trebuie. O cheie care ar apărea fără nume de parametru
și fără formă hexazecimală ar trece. **E a doua linie de apărare, nu prima**;
prima rămâne ca providerii să nu reflecte cererea.

Limita e scrisă ca test (`test_LIMITA_DECLARATA_…`), nu ca notă, tocmai ca
nimeni să nu presupună mai multă protecție decât există — aceeași regulă ca
North Star #8.

### 8.5 Costul se mută, și cu cât exact

§3 mărginea costul la **~32 kB** (9 eșecuri SFI/noapte × 400 B × 9 zile).
Odată ce `oracle_api` cablează `error_body`, intră și ceilalți provideri.
Măsurat pe 2 noiembrie, eșecuri în ultimele 9 zile:

| Provider | Eșecuri / 9 zile | Cost maxim |
|---|---:|---:|
| `oddsapi` | 365 | 143 kB |
| `freelivefootball` | 157 | 61 kB |
| `footballdata` | 48 | 19 kB |
| `soccerfootballinfo` | 13 | 5 kB |

**Total ~228 kB** în loc de 32 kB — de șapte ori mai mult decât bugetul scris,
și tot neglijabil în absolut. Plafonul și retenția rămân neschimbate, deci
cifra nu poate crește nemărginit. TheSportsDB nu mai apare deloc (0 eșecuri) —
întrerupătorul de provider își face treaba.

### 8.6 Ce NU face acest amendament

- **Nu rescrie §3.** Rândul original rămâne, cu un marcaj care trimite aici.
- **Nu ridică plafonul de 400 de caractere** și nu atinge retenția.
- **Nu rescrie retroactiv** rândurile existente — cele 90 de rânduri `oddsapi`
  rămân cu `error_body = NULL`. Corpurile lor nu mai există nicăieri.
- **Nu decide nimic despre `btts`.** Amendamentul face întrebarea *observabilă*;
  răspunsul vine de la prima rulare de noapte care scrie un 422 cu corp.
