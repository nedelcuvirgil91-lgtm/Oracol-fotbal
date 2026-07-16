# ID-025-01 — Canonical Row Selection

## Ce este acest document

**Implementation Design, nu ADR.** ADR-025 a stabilit invariantul („pentru fiecare
meci real trebuie să existe exact un rând canonic") și a lăsat deliberat deschisă
regula de selecție, deferată către implementare. Acest document fixează exact acea
regulă — determinist, fără ambiguitate, verificabil.

**Scop strict**: doar algoritmul de selecție a rândului canonic dintr-un grup de
rânduri duplicate + regula de merge non-destructiv al câmpurilor + regula de marcare
trasabilă. Nu descrie motorul de execuție (ID-025-02), migrarea writerilor
(ID-025-03), constrângerea de bază de date (ID-025-04), validarea (ID-025-05), sau
playbook-ul de rollback (ID-025-06) — acelea sunt documente separate.

## Intrare: ce este un „grup de duplicate"

Un grup = toate rândurile din `match_history` cu aceeași cheie naturală normalizată
`(home_normalizat, away_normalizat, kickoff_date)`, conform ADR-025. Pe corpusul
cunoscut azi (ADR-024): 3.501 grupuri istorice + 3 grupuri active (World Cup 2026),
toate cu exact 2 rânduri; algoritmul de mai jos e proiectat să funcționeze corect și
pentru N ≥ 2 rânduri per grup, nu doar pentru cazul observat de 2.

## Terminologie

- **Grup**: toate rândurile din `match_history` cu aceeași cheie naturală
  normalizată — vezi „Intrare" de mai sus.
- **Canonical Candidate**: orice rând dintr-un grup, înainte de aplicarea
  algoritmului de selecție — un candidat la a deveni rândul canonic.
- **Canonical Row**: candidatul ales de algoritm (Pașii 1-2) — rândul „viu" al
  meciului.
- **Superseded Row**: orice candidat necanonic, după marcare (Pasul 4) — rămâne
  fizic în `match_history`, marcat `superseded_by`, niciodată șters.

## Clasificarea conflictelor: HARD vs. SOFT

Nu toate discrepanțele dintre rândurile unui grup sunt același tip de problemă —
tratarea lor identică ar fi greșită. Acest document distinge explicit două categorii:

**HARD CONFLICT** — câmpuri care definesc identitatea rezultatului unui meci:
`actual_result`, `actual_home_goals`, `actual_away_goals`. (`kickoff_date` nu poate
fi, prin construcție, în conflict în interiorul unui grup — face parte din cheia
naturală care definește grupul, deci e garantat identică pe toate rândurile lui.)
O discrepanță pe `actual_result`/goluri **oprește reconcilierea automată a întregului
grup** — nu se rezolvă prin Source Trust, nu se aproximează, nu se alege un
„câștigător". Motiv: o valoare diferită aici înseamnă fie o eroare reală de date,
fie un semn că cheia naturală nu identifică unic meciul în acel caz — ambele cazuri
necesită decizie umană, nu presupunere automată (Regula #8 North Star). Un grup cu
HARD CONFLICT se exclude din procesarea automată și se raportează separat.
Excluderea **nu produce niciun efect lateral**: nu marchează niciun rând ca
`superseded`, nu mută nimic, nu completează niciun câmp — grupul rămâne exact în
starea găsită; singurul efect e apariția lui în raportul de excludere.

**SOFT CONFLICT** — orice altă coloană (feature-uri statistice: shots, corners,
posesie, ELO, ratings etc.). O discrepanță aici **nu oprește nimic** — nu e o
problemă de identitate, e o divergență normală între măsurători ale acelorași fapte
de la surse diferite (ex. FD raportează 15 șuturi, ESPN raportează 14 — ambele
plauzibile). Se rezolvă determinist prin Source Trust Registry — vezi Pasul 3,
cazul 3.

Pe corpusul cunoscut azi (ADR-024): zero grupuri cu HARD CONFLICT (100% scoruri
identice, verificat direct); frecvența SOFT CONFLICT nu a fost cuantificată
exhaustiv per coloană în auditul inițial, dar e tratată oricum determinist de
algoritm, indiferent de cât de des apare în practică.

## Algoritm de selecție (determinist)

Algoritmul de mai jos operează **exclusiv asupra rândurilor deja validate** de
motorul de reconciliere (ID-025-02) — adică rânduri care au trecut verificarea HARD
CONFLICT de mai sus și orice altă validare de integritate (ex. un rând corupt/
incomplet dincolo de simplu NULL, dacă o astfel de validare se dovedește necesară).
`canonical = rangul cel mai mic **dintre candidații validați ai grupului**`, nu
dintre toate rândurile brute — dacă motorul de reconciliere exclude un candidat
înainte de Pasul 1 (ex. `fd_` corupt), acel candidat nu participă deloc la selecție,
indiferent de rangul lui de sursă.

### Pasul 1 — Rangul de încredere per rând

**Algoritmul de selecție nu cunoaște formatul `fixture_id` al niciunui provider.**
Depinde exclusiv de o abstracție:

> `SourceTrustProvider.get_rank(source: str) -> int | None`

care întoarce rangul de încredere al unei surse (mai mic = mai de încredere), sau
`None` dacă sursa e necunoscută (→ grupul e exclus din procesarea automată,
raportat separat — Regula #8: o sursă necunoscută nu se presupune, nu se clasează
arbitrar).

Acest lucru face algoritmul independent de convenția de denumire a oricărui
provider — un provider nou (`opta_`, `sofascore_`, `flashscore_`, `manual_`, sau
orice altul) nu atinge niciodată acest document sau algoritmul, doar registrul.

**Rezolvarea sursei unui rând** (`source`, argumentul funcției de mai sus) e o
componentă separată, explicit înlocuibilă — `resolve_source(row) -> str`.
Implementarea curentă (interimară, nu fixată de acest document, doar singurul
semnal disponibil azi în schemă) derivă sursa din prefixul `fixture_id`:

| Prefix `fixture_id` | `source` rezolvat |
|---|---|
| `fd_` | `football_data` |
| `espn_` | `espn` |
| `odds_` | `odds_api` |
| `kaggle_` | `kaggle_historical` |
| altul | necunoscut — grup exclus |

Registrul `SourceTrustProvider` conține azi, ca referință (Source Trust Policy,
ADR-025):

| `source` | Rang |
|---|---|
| `football_data` | 1 |
| `espn` | 2 |
| `odds_api` | 3 |
| `kaggle_historical` | 4 |

Motiv pentru rangul de sursă ca și criteriu **principal** (nu „id minim", nu „cel
mai complet"): e singurul criteriu dintre cele trei candidate din ADR-025 stabil în
timp (nu se schimbă când sosesc date noi prin backfill) și nesupus unui artefact de
ordine de inserare arbitrară. E de asemenea singurul deja evidențiat empiric în
ADR-024 (100% din rândurile `fd_` au shots/corners populate vs. 0% din `kaggle_`).

Notă de implementare (nu decizie a acestui document): dacă `match_history` capătă
vreodată o coloană explicită `source` (populată direct de fiecare writer, nu
dedusă din `fixture_id`), `resolve_source()` se înlocuiește cu o simplă citire de
coloană, fără nicio schimbare la `SourceTrustProvider` sau la restul algoritmului —
exact beneficiul separării.

`SourceTrustProvider` e **infrastructură** (o sursă de configurare care furnizează
un fapt extern — rangul unei surse), nu logică de business. Logica de business
(cum se folosește acel rang pentru a decide) trăiește exclusiv în algoritmul de
selecție de mai jos, nu în registru.

### Pasul 2 — Desemnarea rândului canonic

Rândul cu rangul numeric cel mai mic (cea mai mare încredere) devine **canonic**.

**Egalitate de rang** (posibil doar teoretic azi — niciun grup cunoscut nu are doi
rânduri cu același prefix; păstrat pentru robustețe viitoare): rândul cu `id` mai
mic devine canonic. Acesta e folosit **doar** ca tiebreaker de ultimă instanță, nu
ca regulă principală — diferența e intenționată, per observația Owner-ului la
ADR-025.

Toate celelalte rânduri din grup devin **necanonice**.

### Pasul 3 — Merge non-destructiv (câmp cu câmp)

Pentru fiecare coloană din `FEATURE_COLUMNS` + coloanele de rezultat/statistici:

1. Dacă rândul canonic are deja o valoare non-null pe acea coloană → **nu se
   atinge niciodată** (Writer Protection, necondiționat).
2. Dacă rândul canonic are null pe acea coloană și **exact un** rând necanonic are
   o valoare non-null → valoarea se copiază în rândul canonic.
3. Dacă rândul canonic are null și **mai multe** rânduri necanonice au valori
   non-null diferite pentru aceeași coloană — acesta e un **SOFT CONFLICT** (vezi
   clasificarea de mai sus), nu un motiv de oprire → câștigă valoarea de la rândul
   necanonic cu rangul de încredere cel mai mic dintre cele aflate în conflict,
   determinat via `SourceTrustProvider.get_rank()` (Pasul 1), aplicat acum la nivel
   de câmp, nu doar de rând întreg. **Doar rândurile cu valoare non-null pe acea
   coloană specifică participă la comparație** — un rând cu null pe acea coloană nu
   influențează decizia, indiferent de rangul lui de sursă (ex. `fd_`=null,
   `espn_`=14, `odds_`=13 pe `shots` → câștigă `espn_`, fiindcă `fd_` nu participă
   deloc la această comparație, deși are rangul cel mai mic per Pasul 1).
4. Dacă niciun rând (canonic sau necanonic) nu are valoare pe acea coloană →
   rămâne null. Nu se aproximează (Regula #8).

**Merge-ul e monoton**: singura tranziție permisă e `NULL → valoare`. Tranziția
`valoare → altă valoare` nu se întâmplă niciodată, în niciun caz de mai sus — exact
Writer Protection exprimată ca proprietate matematică a operației de merge.

### Pasul 4 — Marcarea trasabilă

Fiecare rând necanonic primește (coloane de audit, adăugate în Faza 1 din
strategia de migrare ADR-025 — schema exactă e responsabilitatea ID-025-04):

- `superseded_by` = `id`-ul rândului canonic.
- `superseded_at` = timestamp UTC al reconcilierii.
- `superseded_reason` = șir determinist, generat automat, ex.:
  `"duplicate_cross_provider: canonical=fd_497780 (rank=1), superseded=kaggle_04f4107f71d47331 (rank=4)"`.

Rândul canonic **nu primește niciun marcaj special** — rămâne rândul „viu" al
meciului, identificabil prin absența lui `superseded_by`.

Rândul necanonic **nu se șterge niciodată** — rămâne în `match_history`, doar
marcat, recuperabil integral (Regula #9 North Star, trasabilitate completă).

## Proprietăți garantate de acest algoritm

- **Determinism**: aceleași rânduri de intrare produc întotdeauna aceeași alegere
  de rând canonic și același rezultat de merge — nicio componentă aleatorie, niciun
  ordine-de-procesare-dependent (regulile de la Pasul 3 sunt simetrice față de
  ordinea în care sunt vizitate rândurile necanonice).
- **Idempotență**: rularea algoritmului a doua oară pe un grup deja reconciliat nu
  produce nicio schimbare — rândurile necanonice deja marcate `superseded_by` sunt
  excluse din procesarea ulterioară (motor de execuție, ID-025-02).
- **Stabilitate**: alegerea rândului canonic nu depinde de completitudinea datelor
  la momentul reconcilierii — deci nu se poate „schimba" retroactiv dacă sosesc mai
  multe date pe rândul necanonic ulterior (compatibil cu cerința de Stabilitate din
  Canonical Row Definition, ADR-025).
- **Fail-closed pe HARD CONFLICT**: un grup cu scoruri contradictorii nu e niciodată
  reconciliat automat — nu există o cale silențioasă spre o alegere greșită.
- **Referential Stability**: `id`-ul unui rând canonic nu se schimbă niciodată după
  ce a fost desemnat — nu doar alegerea în sine, ci TOATE referințele externe către
  el (predicții cache-uite, `fixture_id`-uri necanonice cu `superseded_by`, orice
  consumator viitor) rămân valide pe termen nelimitat. Mecanismul care garantează
  asta, structural: (a) reconcilierea reutilizează `id`-ul unui rând deja existent
  ca și canonic — nu creează niciodată un `id` nou pentru „vederea combinată"; (b)
  rândurile necanonice nu se șterg niciodată, deci orice referință externă la un
  `fixture_id` necanonic rămâne rezolvabilă (nu devine invalidă), doar trebuie
  urmărit `superseded_by` pentru a ajunge la starea „vie"; (c) după Faza 6 din
  ADR-025 (constrângerea UNIQUE), nu mai poate apărea fizic un al doilea rând pentru
  aceeași cheie naturală — deci nu mai există niciodată o „re-canonicalizare" de
  făcut ulterior. Procesul de selecție descris în acest document se aplică o
  singură dată, exclusiv istoricului deja existent la momentul reconcilierii.
  Explicit: dacă un candidat e deja desemnat canonic al unui grup (are cel puțin un
  `Superseded Row` care îl referă via `superseded_by`), rulările ulterioare ale
  algoritmului **nu îl re-evaluează** — nu se recalculează canonicul unui grup deja
  procesat, indiferent de ce date noi sosesc ulterior pe candidații necanonici.

## Ce NU acoperă acest document

- Cum se execută algoritmul pe scară (batching, paginare, reluare după eroare) —
  ID-025-02 (Historical Reconciliation Engine).
- Cum se actualizează writerii pentru scriere continuă pe cheia naturală — ID-025-03
  (Writer Migration).
- Schema exactă a coloanelor de audit (`superseded_by` etc.) — ID-025-04 (Database
  Constraint).
- Cum se verifică rezultatul final (criteriul de acceptanță) — ID-025-05
  (Validation).
- Ce se întâmplă dacă acest algoritm produce un rezultat greșit după ce a rulat pe
  producție — ID-025-06 (Rollback Playbook), deja schițat parțial în ADR-025.

## Referințe

- ADR-024 — Canonical Match Identity & Data Contract
- ADR-025 — Match Identity Implementation Strategy (Canonical Row Definition, Source
  Trust Policy, Rollback Strategy)
- Regula #13 (Writer Protection) — `sync/backfill_features.py::_missing_feature_columns()`
