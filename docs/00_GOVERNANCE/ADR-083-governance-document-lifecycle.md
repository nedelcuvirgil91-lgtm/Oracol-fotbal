# ADR-083 — Un document de guvernanță care nu mai e întreținut se retrage formal, nu se lasă să putrezească

**Status**: **ACCEPTED** (aprobat explicit de proprietarul produsului, 2026-10-27)
**Data**: 2026-10-27
**Autor**: sesiune Claude Code, la cererea proprietarului produsului
**Legat de**: ADR-005 (precedentul că atingerea unui document de guvernanță cere
ADR), `FROZEN_REGISTRY.md` §Change Policy („responsabilitățile componentelor" =
motivație validă), North Star #4 și #5

---

## 1. Context — măsurat, nu presupus

`ARCHITECTURE_STATE.md` își declară în antet propria regulă de întreținere:

> „orice sesiune care merge-uiește cod, schimbă un flag de producție, sau închide
> un ADR **actualizează acest document în același commit** (sau imediat
> următor) … dacă acest document e stale, se corectează întâi el, nu se
> lucrează pe baza memoriei conversației."

Iar `CLAUDE.md` trimitea la el ca la „**sursa de adevăr actualizată** … ce
rulează live, ce e activat prin flag-uri".

Starea reală, interogată pe 27 octombrie 2026:

| Ce | Cifra |
|---|---:|
| Ultima atingere a `ARCHITECTURE_STATE.md` | **2026-09-06** (51 de zile) |
| Commit-uri pe `main` de atunci | **143** |
| ADR-uri necunoscute documentului | **25** (058 → 082) |
| Migrări neconsemnate | **3** (056, 057, 058) |
| Activări de flag neconsemnate | **4** |
| `main` HEAD afirmat la §1 | `fb188a7` (4 aug), commit care nici nu mai există local |
| Ultima intrare din `CHANGELOG.md` | **2026-08-29** (~2 luni) |

**Cele 4 activări lipsă sunt exact cele cu cea mai mare consecință**, fiecare cu
amprentă `md5` documentată în `CLAUDE.md`: ADR-072 (baseline proaspăt la
promovare) · ADR-073 (persistarea intrărilor de servire) · ADR-078 (captarea
identității Flashscore) · ADR-082 (banda campionului).

**Două afirmații FALSE** au fost găsite cu aceeași ocazie, ambele verificate în
cod, nu în documente:

1. `CLAUDE.md` scria despre ADR-037 R3 „cod complet, testat, **NEMERGE-UIT pe
   `main`**" — de ~3 luni. `git show origin/main:learning_core/continuous_learning.py`
   conține `_phase_d_champion_health` și `is_champion_guardian_enabled`;
   `champion_guardian.py` și `rollback_service.py` sunt amândouă pe `main`.
   Agravant: `ADR037_DEPLOYMENT_PLAN.md` îl contrazicea **din 28 iulie**, în
   chiar documentul citat ca referință în același rând.
2. `CHANGELOG.md` purta același titlu „NEMERGE-UIT", plus eticheta `[Nelansat]`
   pe patru secțiuni aflate în producție de luni.

### 1.1 Diagnosticul care contează: regula scrisă a eșuat, nu oamenii

Regula de întreținere **exista, era scrisă în capul documentului, și era
explicită**. A fost încălcată de **25 de ADR-uri la rând**, inclusiv de sesiuni
care citaseră acel document în aceeași zi. Deci problema nu e că regula lipsea
sau că nu era cunoscută — e că **o regulă de proces fără mecanism nu se aplică
singură**, indiferent cât de bine e scrisă și cât de vizibil.

Asta e aceeași clasă pentru care proiectul plătește deja repetat:
`flashscore_data_completeness.coverage_percent` fix la 100% (un indicator cu o
singură valoare posibilă nu e un indicator), `night_sync` verde prin construcție
(un job care nu poate fi roșu nu e un semnal), ADR-057 necitat de nimeni timp de
14 zile. **Un document care trebuie întreținut prin disciplină e un indicator
care nu poate fi roșu.**

### 1.2 De ce nu se reconstituie istoria

Varianta „se reînvie documentul" a fost analizată și respinsă (vezi §4). Dar
chiar și în ea, reconstituirea celor 51 de zile ar fi însemnat să rescriem 143 de
commit-uri **din memoria conversațiilor** — exact ce propria regulă a documentului
interzice („nu se lucrează pe baza memoriei conversației"). Un document care
*pare* actual dar e reconstituit din amintiri e mai periculos decât unul care își
declară vechimea, fiindcă e citit tocmai pentru precizia lui.

---

## 2. Decizie

### 2.1 Regula generală (partea normativă)

**Un document de guvernanță care nu mai e întreținut se retrage formal, printr-un
ADR, cu starea lui declarată în antet. Nu se lasă stale, și nu se șterge.**

Trei stări posibile, declarate explicit în antetul fiecărui document de
guvernanță:

| Stare | Ce înseamnă | Cine o poate cita |
|---|---|---|
| **VIU** | se actualizează; răspunde la „ce e azi" | oricine, ca stare curentă |
| **ISTORIC** | instantaneu al unei date, exact la acea dată | doar ca dovadă a trecutului, niciodată ca stare curentă |
| **FROZEN** | imuabil fără ADR dedicat (regimul existent, `FROZEN_REGISTRY.md`) | ca specificație |

**Trecerea VIU → ISTORIC cere un ADR** — fiindcă mută o responsabilitate (cine
răspunde la „ce rulează azi"), iar Change Policy numește explicit
„responsabilitățile componentelor" ca motivație validă. Trecerea nu se face prin
editare tăcută (North Star #5).

**Un document ISTORIC nu se șterge.** Ștergerea ar distruge dovada stării de la
acea dată, ceea ce contrazice North Star #9 (trasabilitate completă). Rămâne în
repo, cu antetul lui.

**Niciun document nu se declară VIU fără un mecanism care îl ține viu.** O regulă
de proces scrisă în antet **nu** e un mecanism — asta e lecția măsurată din §1.1.
Mecanism acceptabil: o gardă automată, sau faptul că documentul e atins în mod
natural de munca însăși (cazul `BACKLOG.md`, actualizat fiindcă e lista de lucru,
nu dintr-o obligație separată).

### 2.2 Aplicarea imediată

**`ARCHITECTURE_STATE.md` → ISTORIC**, instantaneu al stării din **6 septembrie
2026**, cu excepția §4bis (remăsurată pe producție, 27 oct) care rămâne datată
explicit.

**`CHANGELOG.md` → ISTORIC**, jurnal al perioadei până la **29 august 2026**.

**Sursele VII declarate ale proiectului devin, în ordinea de citire:**

1. **`CLAUDE.md`** — starea pe componente, regulile, golurile cunoscute.
2. **`docs/00_GOVERNANCE/BACKLOG.md`** — ce e de făcut și ce decizii așteaptă.
3. **`docs/00_GOVERNANCE/DE_URMARIT.md`** — ce așteptăm, când, și ce înseamnă
   dacă nu vine.

Toate trei satisfac §2.1 pct. 4: se actualizează **fiindcă sunt instrumentele de
lucru**, nu dintr-o obligație de întreținere separată. Dovada e empirică, nu
argumentată: în intervalul în care `ARCHITECTURE_STATE.md` a stat neatins 51 de
zile, `BACKLOG.md` și `DE_URMARIT.md` au fost actualizate de zeci de ori.

**Jurnalul declarat al schimbărilor devine seria de ADR-uri** (`ADR-0NN-*.md`,
fiecare cu `Status` și dată) plus `git log`. Un jurnal paralel, întreținut manual,
e tocmai ce a cedat.

### 2.3 Ce NU decide acest ADR

- **Nu** șterge, nu rescrie și nu reconstituie niciun conținut istoric.
- **Nu** atinge regimul FROZEN existent și nu modifică `FROZEN_REGISTRY.md`.
- **Nu** schimbă nicio linie de cod. Zero impact pe calea de predicție.
- **Nu** rezolvă golul celor **6 numere de ADR fără fișier** (007, 008, 009, 027,
  029, 032 — măsurat 27 oct, 76 de fișiere din 82). Rămâne consemnat ca gol
  propriu de trasabilitate, din aceeași clasă cu documentele declarate Frozen
  care nu există fizic în repo. **Nu se deduce** dacă acele decizii n-au fost
  scrise niciodată sau trăiesc doar în istoricul conversațiilor de proiect.

---

## 3. Consecințe

**Pozitive:**

- Dispare a doua sursă de adevăr declarată. **Două surse declarate, una moartă,
  e mai rău decât una** — e aceeași lecție pentru care `BACKLOG.md` nu are dată
  în nume.
- Distincția dintre „abandonat" și „retras deliberat" devine citibilă. Fără ADR,
  cineva care găsește `ARCHITECTURE_STATE.md` în trei luni nu poate ști care din
  două e cazul — iar a presupune e exact cum s-a ajuns aici.
- Costul de întreținere scade la zero pentru două documente, fără pierdere de
  informație.

**Negative, acceptate conștient:**

- **Nu mai există un instantaneu complet al arhitecturii, actualizat.** Dacă apare
  nevoia reală (onboarding, audit extern), el se **generează atunci**, din cod și
  din bază — nu se ține în viață prin disciplină. Asumarea e că un instantaneu
  generat la cerere e mai de încredere decât unul întreținut manual, și cele 51
  de zile o susțin.
- Răspunsul la „ce e activat prin flag-uri" cere acum o interogare, nu o citire.
  Mitigare: interogarea e în `ARCHITECTURE_STATE.md` §4bis și e read-only.

**Neutre:**

- Dacă vreodată apare un al doilea consumator declarat al documentului,
  decizia se poate inversa — dar atunci varianta „reînviere" trebuie să vină cu
  mecanismul din §2.1 pct. 4, nu cu o regulă rescrisă. Un document cu cititori
  merită un mecanism; unul fără, nu.

---

## 4. Alternativa respinsă

**Reînvierea cu mecanism** — o gardă care cade dacă un fișier `ADR-0NN-*.md` nou
apare în `docs/00_GOVERNANCE/` fără ca `ARCHITECTURE_STATE.md` să fie atins în
același commit. E tehnic ieftină (o comparație de liste de fișiere în `git diff`;
nici AST nu e necesar).

**Respinsă** pentru că rezolvă problema greșită. Garda ar impune ca documentul să
fie *atins*, nu ca el să fie *corect* — iar o atingere obligatorie produce
exact genul de actualizare formală care arată ca întreținere fără să fie. Și ar
adăuga un al treilea artefact de întreținut (garda însăși) pentru un document cu
un singur cititor declarat: `CLAUDE.md`, care tocmai a fost corectat să nu-l mai
citeze.

Argumentul decisiv e empiric: munca reală a migrat deja, singură, în
`BACKLOG.md` + `DE_URMARIT.md`, timp de 51 de zile. Decizia asta descrie ce se
întâmplă deja, în loc să lupte împotrivă.

---

## 5. Verificare cerută

1. `ARCHITECTURE_STATE.md` și `CHANGELOG.md` au fiecare, în antet, starea
   **ISTORIC** cu data instantaneului și trimitere la acest ADR. ✅
2. `CLAUDE.md` nu mai citează niciun document ISTORIC ca sursă de stare curentă.
   ✅
3. Niciun document ISTORIC nu e șters sau rescris retroactiv. ✅
4. **Nicio trimitere VIE** nu mai prezintă un document ISTORIC ca sursă de stare
   curentă. ✅ — trei găsite și reparate pe 27 oct, toate prin verificarea asta,
   nu prin noroc: `CHAMPION_GUARDIAN_IMPLEMENTATION.md:372`
   („pentru starea curentă, sursa de adevăr actualizată"),
   `ADR037_DEPLOYMENT_PLAN.md:7` („Stare curentă completă: … §3") și
   `R3_IMPLEMENTATION_CHECKLIST.md:108` („sursă unică de adevăr, actualizată
   permanent").

   > **Criteriul a fost CORECTAT în aceeași zi, și motivul merită consemnat.**
   > Formularea inițială era „`grep -rn \"sursa de adevăr actualizată\"` nu mai
   > întoarce nicio trimitere". Rulată, **nu trecea** — dar nu din cauza unui
   > defect: rândul din `R3_IMPLEMENTATION_CHECKLIST.md` e **evidența a ce s-a
   > livrat la R3.8** și păstrează deliberat textul original, cu nota de
   > corecție imediat dedesubt. Ca să treacă grep-ul, ar fi trebuit **rescris
   > retroactiv** — ceea ce North Star #9 interzice și ceea ce acest ADR însuși
   > interzice la §2.1.
   >
   > Deci criteriul, nu documentul, era greșit: cerea o proprietate
   > (**absența textului**) în locul celei care contează (**absența unei
   > trimiteri pe care un cititor ar urma-o fără să vadă corecția**). Un rând
   > istoric adnotat satisface a doua și o va încălca mereu pe prima.
   >
   > **Nu e o slăbire a verificării ca să devină verde** — e înlocuirea unei
   > măsurători care intra în conflict cu o regulă de rang superior. Distincția
   > contează: dacă aș fi șters textul vechi, grep-ul ar fi trecut și aș fi
   > distrus dovada; dacă aș fi lăsat criteriul neschimbat, ADR-ul ar fi purtat
   > o verificare permanent roșie, adică un indicator pe care nimeni nu-l mai
   > citește — exact patologia pe care §1.1 o descrie.
5. `pytest tests/` verde — ADR-ul nu atinge cod. ✅
