# FEATURE_ENGINEERING_ROADMAP.md — Football Oracle

## Scop

Analiză a feature-urilor candidate pentru îmbunătățirea acurateței modelului, **înainte** de a îngheța `BENCHMARK_V4.md`. Fără cod. Pentru fiecare candidat: sursă, disponibilitate, cost, impact, automatizare GitHub Actions, risc de scurgere de date, prioritate ROI.

Context verificat, nu presupus: modelul actual e dominat aproape exclusiv de ELO (permutation importance ~0.123 vs. <0.004 pentru restul), confirmat prin audit anterior pe 53.409 meciuri reale.

---

## Nivel 1 — ROI foarte mare, cost foarte mic (cod deja scris, doar neconectat)

### 1.1 Rest days (zile de odihnă)

- **Sursă**: `match_history.kickoff_date`, per echipă — **date deja existente**, zero colectare nouă.
- **Stare reală, verificată**: funcția `rest_days_modifier()` **există deja, completă**, în `feature_engine.py:99` — dar **nu e apelată nicăieri** în `oracle_engine.py`. Cod mort, gata de folosit.
- **Cost implementare**: **mic** — calculul `rest_days` (diferența în zile față de ultimul meci cunoscut al echipei, din `match_history`) + un apel de funcție deja scrisă.
- **Impact estimat**: literatura de sport-analytics (fotbal/fixture congestion) documentează consistent un efect mic-spre-moderat al odihnei reduse (tipic sub 4 zile) asupra performanței — funcția existentă implementează deja o penalizare fixă de -5% xG pentru acest caz, o alegere rezonabilă, nu una exagerată.
- **GitHub Actions**: complet automatizabil — calculul se face din date deja sincronizate zilnic.
- **Risc de scurgere**: **zero** — `rest_days` al unui meci depinde strict de meciuri anterioare aceluiași, niciodată de viitor.
- **Prioritate ROI**: **#1 — cel mai bun raport din tot roadmap-ul.**

### 1.2 Congestionarea calendarului (fixture congestion)

- **Sursă**: aceleași date (`kickoff_date` per echipă) — extensie naturală a 1.1 (numărul de meciuri în ultimele N zile, nu doar distanța până la ultimul).
- **Cost implementare**: **mic** — aceeași sursă de date, o funcție de agregare în plus.
- **Impact estimat**: complementar cu rest days, dar captează un efect diferit (oboseală cumulată pe o perioadă, nu doar ultimul meci) — relevant mai ales pentru echipele cu cupe europene/naționale.
- **GitHub Actions**: da, automat.
- **Risc de scurgere**: zero (strict istoric).
- **Prioritate ROI**: **#2.**

---

## Nivel 2 — ROI mare, cost mic-mediu (date deja colectate, dar neintegrate în ML)

### 2.1 Accidentări (injuries) — integrare live, nu doar shadow

- **Sursă**: API-Football, deja integrat (`football_providers.py`, `ApiFootballProvider.get_injuries()`), confirmat funcțional din audituri anterioare.
- **Stare reală**: colectat, logat ca experiment shadow (`apifootball_injuries_coaches`) — dar **`shadow_mode_enabled=False`**, deci **zero evaluare reală acumulată** până acum.
- **Cost implementare**: **mic-mediu** — nu necesită date noi, necesită doar (a) activarea shadow mode, (b) acumularea a suficiente meciuri evaluate, (c) abia apoi, dacă experimentul demonstrează statistic o îmbunătățire, promovare la blend live.
- **Impact estimat**: literatura pe absențe-cheie (jucători titulari indisponibili) arată efecte reale, dar foarte variabile ca mărime — depinde enorm de calitatea datelor de "importanță a jucătorului", pe care proiectul nu o are încă (doar prezență/absență, nu impact estimat per jucător).
- **GitHub Actions**: da — shadow logging deja rulează prin `run_daily.py`.
- **Risc de scurgere**: **zero**, dacă rămâne strict "echipă probabilă la momentul T-1" — risc real dacă se folosește accidental compoziția FINALĂ a echipei (cunoscută abia aproape de kickoff, uneori după).
- **Prioritate ROI**: **#3** — dar necesită întâi activarea shadow mode + timp de acumulare, nu implementare imediată de cod nou.

### 2.2 Antrenor nou / schimbare de antrenor

- **Sursă**: API-Football, deja integrat (`get_coaches()`), aceeași stare ca 2.1 (colectat, shadow, neactivat).
- **Cost implementare**: **mic** — infrastructura există; adaugă doar un semnal derivat ("antrenor nou de X zile") peste datele deja colectate.
- **Impact estimat**: efectul de "noul antrenor" e documentat în literatură ca real, dar de scurtă durată (primele 3-6 meciuri) și eterogen — nu toate schimbările de antrenor au aceeași direcție de efect.
- **GitHub Actions**: da.
- **Risc de scurgere**: zero, dacă data schimbării de antrenor e cunoscută înainte de meci (tipic e publică imediat).
- **Prioritate ROI**: **#4.**

---

## Nivel 3 — ROI moderat, cost mediu (calcul nou, dar din date deja existente)

### 3.1 ELO ofensiv/defensiv separat (în loc de un singur scor combinat)

- **Sursă**: istoricul deja folosit pentru ELO curent — **nicio dată nouă**, doar restructurarea calculului.
- **Cost implementare**: **mediu** — necesită rescrierea logicii de actualizare ELO (două scoruri per echipă în loc de unul, actualizate diferit pe baza golurilor marcate vs. primite), plus recalcularea istorică pentru consistență.
- **Impact estimat**: teoretic promițător (permite modelului să distingă "echipă puternică ofensiv, slabă defensiv" de "echilibrată mediu") — dar ELO combinat deja domină ca importanță (confirmat), deci câștigul marginal e incert fără testare.
- **GitHub Actions**: da, parte din recalcularea zilnică deja existentă.
- **Risc de scurgere**: zero, dacă recalcularea istorică respectă aceeași disciplină cronologică deja aplicată la ELO curent.
- **Prioritate ROI**: **#5** — promițător, dar necesită validare explicită (shadow/backtest) înainte de a-i acorda prioritate mai mare, exact pentru că "pare util teoretic" nu e dovadă.

### 3.2 Puterea adversarilor întâlniți recent (strength of schedule)

- **Sursă**: ELO-ul adversarilor din meciurile recente — derivabil complet din date deja existente.
- **Cost implementare**: **mediu** — agregare pe fereastră glisantă a ELO-ului adversarilor, nu doar rezultatul brut.
- **Impact estimat**: rafinează `form_score`-ul existent (o victorie contra unui adversar puternic ar trebui să conteze mai mult) — direcție rezonabilă, dar `form_score` are deja importanță mică azi (0.0015/0.0005), deci rafinarea lui are plafon limitat de câștig.
- **GitHub Actions**: da.
- **Risc de scurgere**: zero.
- **Prioritate ROI**: **#6.**

---

## Nivel 4 — ROI incert sau cost mare (date noi de colectat, dependință externă)

### 4.1 xG real din surse externe (ex. Understat, FBref, Opta)

- **Sursă**: **nu există în proiect** — ar necesita un provider nou, complet neintegrat azi.
- **Cost implementare**: **mare** — provider nou (rate limits, normalizare nume echipe — aceeași disciplină deja aplicată la celelalte provideri), fără istoric acumulat (xG real ar trebui colectat de acum înainte, nu poate fi reconstruit retroactiv pentru meciuri vechi fără acces la un furnizor cu istoric complet, adesea plătit).
- **Impact estimat**: literatura de betting-analytics tratează xG real ca pe unul din cele mai puternice predictoare cunoscute, superior xG-ului estimat intern (Poisson-baseline) — dar tocmai de asta costul de achiziție (mulți furnizori serioși sunt plătiți) trebuie cântărit explicit.
- **GitHub Actions**: parțial — colectarea zilnică da, dar acumularea unui istoric util ar dura luni.
- **Risc de scurgere**: **risc real, de verificat explicit** — xG "post-meci" (statistici finale) nu trebuie folosit ca feature de PRE-meci; doar xG-ul acumulat din meciuri ANTERIOARE ar fi valid ca input.
- **Prioritate ROI**: **#7** — impact potențial mare, dar cost/timp de acumulare mare, nesigur fără o decizie explicită de buget/furnizor.

### 4.2 Valoarea lotului (squad value)

- **Sursă**: **nu există în proiect** — ar necesita scraping/API extern (ex. Transfermarkt, fără API oficial documentat public).
- **Cost implementare**: **mare** — fără API oficial, orice integrare ar fi fragilă (scraping), risc de întrerupere.
- **Impact estimat**: corelează cu puterea reală a lotului, dar parțial redundant cu ELO (echipele valoroase au deja ELO mare, de regulă) — câștigul marginal peste ELO existent e incert.
- **GitHub Actions**: dificil de automatizat robust, dat fiind lipsa unui API oficial.
- **Risc de scurgere**: zero (valoarea lotului la un moment dat e strict istorică).
- **Prioritate ROI**: **#8** — cost mare, beneficiu marginal incert peste ce ELO deja acoperă.

### 4.3 Deplasări lungi (distanță de călătorie)

- **Sursă**: **nu există în proiect** — ar necesita coordonatele stadioanelor (geocodare, o singură dată per echipă — cost inițial mic, dar tot nou).
- **Cost implementare**: **mediu** — geocodarea în sine e simplă (o singură dată, echipe fixe), dar integrarea (calcul de distanță + prag de "deplasare lungă") e muncă nouă.
- **Impact estimat**: literatura pe acest subiect specific în fotbal e mai puțin robustă decât pe rest days/congestie — efectul distanței, izolat de oboseală (deja acoperită de 1.1/1.2), e greu de separat statistic.
- **GitHub Actions**: da, o dată geocodat.
- **Risc de scurgere**: zero.
- **Prioritate ROI**: **#9** — cel mai slab raport din listă, se suprapune parțial cu 1.1/1.2 fără o dovadă clară de valoare incrementală.

---

## Rezumat — ordine finală după ROI/complexitate

| # | Feature | Sursă | Cost | Risc scurgere | GH Actions |
|---|---|---|---|---|---|
| 1 | Rest days | existentă, cod deja scris | mic | zero | da |
| 2 | Fixture congestion | existentă | mic | zero | da |
| 3 | Injuries (activare shadow → live) | existentă, colectată | mic-mediu | zero (dacă echipă probabilă, nu finală) | da |
| 4 | Schimbare antrenor | existentă, colectată | mic | zero | da |
| 5 | ELO ofensiv/defensiv separat | existentă, recalcul | mediu | zero | da |
| 6 | Strength of schedule | existentă | mediu | zero | da |
| 7 | xG real extern | **nouă**, provider nou | mare | risc real, de gestionat | parțial |
| 8 | Squad value | **nouă**, scraping fragil | mare | zero | dificil |
| 9 | Distanță deplasare | **nouă**, geocodare | mediu | zero | da |

## Recomandare

Implementăm **1-4 mai întâi** (cost mic/mediu, zero risc de scurgere, folosesc exclusiv date deja existente) — fiecare cu propriul mini-benchmark, cum ai cerut. Abia după acestea, reevaluăm dacă 5-6 merită efortul, și decidem separat, cu buget/decizie explicită, dacă 7-9 (date noi, cost mare) intră în scop.

Aștept aprobarea ta pentru a începe cu **#1, Rest days** — implementare mică, risc zero, cod deja pe jumătate scris.
