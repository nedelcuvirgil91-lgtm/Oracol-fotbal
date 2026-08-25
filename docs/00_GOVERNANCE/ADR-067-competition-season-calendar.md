# ADR-067 — Calendarul sezonului devine fapt stocat, nu dedus

**Status**: Proposed (2026-08-25)
**Atinge contractul**: tabelă nouă `competition_season`, `providers/flashscore/discovery.py`,
`oracle_engine._current_season_start_date()`
**Nu atinge**: `match_history.season` (ADR-066 rămâne neschimbat), criteriile de promovare, RLS existent

---

## Context

ADR-066 a rezolvat *eticheta* sezonului (`match_history.season`). Ce n-a rezolvat
e **calendarul**: când începe și când se termină sezonul unei competiții.

Datele există deja. `parse_season_from_hub()` le extrage, la fiecare rulare de
Discovery, din pagina care oricum e descărcată:

```
div.heading__info                       -> "2026/2027"
.wcl-progressBarContainer_ .wcl-start_  -> "21.08."
.wcl-progressBarContainer_ .wcl-end_    -> "06.06."
```

Verificat pe Ligue 1 (captură a proprietarului produsului, 2026-08-25):
`{"season": "2026-2027", "start_date": "2026-08-21", "end_date": "2027-06-06"}`.

**Și apoi se aruncă.** Intervalul trăiește doar cât ține bucla de persistare,
ca gardă în `season_for_kickoff()`. Nu-l stochează nimic.

### De ce a devenit asta o problemă concretă, nu teoretică

ADR-066 P3 a înlocuit pragul fix de 1 iulie cu startul real, derivat din
`match_history` (sezonul celui mai recent meci al ligii → prima zi a acelui
sezon). Alternativa „tabelă nouă" a fost lăsată deoparte ca fiind contract nou.

**Derivarea a cedat în aceeași zi.** Verificată pe date reale, pentru Premier
League întorcea `2025-08-15` — startul sezonului **trecut**. Cauza: cel mai
recent meci PL *cu etichetă* e din 2026-05-24, fiindcă football_data nu mai
scrie nimic din 2026-08-04, iar meciurile noi n-au încă sezon. Aceeași
situație la La Liga, Serie A, Bundesliga, Ligue 1. Fixul aplicat (`max()` cu
pragul) o face inofensivă, dar cu prețul de a o face și inutilă pentru exact
ligile unde ar fi contat.

Concluzia: alegerea reală nu e „tabelă nouă vs. nimic". E **fapt stocat de la
provider vs. inferență fragilă din acoperirea propriei baze de date.**

### Ce nu există azi

Nicio tabelă nu ține calendarul unei competiții. Verificat:
`api_football_league_coverage` și `league_provider_coverage` descriu acoperirea
providerilor; `flashscore_standings_snapshot` ține clasamente per echipă.

---

## Decizie

**1. Tabelă nouă `competition_season`**, cheie `(competition, season)`:

| Coloană | Rol |
|---|---|
| `competition` | numele canonic al ligii (`mappings.normalize_league_name`) |
| `season` | eticheta canonică, `YYYY-YYYY` (ADR-066 §4) |
| `start_date`, `end_date` | calendarul real, de la provider |
| `source` | `flashscore_hub` — de unde vine faptul |
| `observed_at` | când a fost văzut ultima oară; face vizibilă învechirea |

**2. Scriitor unic: Discovery.** Nimeni altcineva. ADR-036 (Canonical Feature
Ownership) se aplică identic: o coloană are un singur owner.

**3. „Sezonul curent" al unei ligi = rândul al cărui interval conține ziua de
azi.** Nu „eticheta cea mai recentă", nu „cea mai mare lexicografic" — exact
inferențele care au cedat. Dacă nicio linie nu conține ziua de azi (pauză
între sezoane, competiție neurmărită, calendar neactualizat), nu se ghicește.

**4. Cascada din `_current_season_start_date()`**, în ordine:

1. `competition_season.start_date` — faptul de la provider
2. derivarea din `match_history` (ADR-066 P3), cu garda `max()` — acoperă
   ligile fără hub Flashscore
3. pragul de 1 iulie — plasa de siguranță

Fiecare treaptă e strict mai slabă decât cea de deasupra. Nicio treaptă nu
poate lărgi fereastra peste ce dă pragul.

**5. RLS activ, scriere doar prin `service_role`**, `CREATE TABLE IF NOT
EXISTS` — aceeași disciplină ca `001_odds_history.sql`.

---

## Argumente PRO

- **Sursa e autoritară.** Providerul *declară* calendarul; noi nu-l mai
  deducem. Exact „verificat, nu presupus".
- **Cost de rețea zero.** Pagina de hub e deja descărcată la fiecare rulare.
  Nu se adaugă nicio cerere.
- **Închide clasa de defect care s-a manifestat deja azi.** Un fapt stocat nu
  poate întoarce startul sezonului trecut din cauza acoperirii inegale a
  propriei baze de date.
- **Rezolvă calendarele non-europene fără să aștepte date.** MLS
  (februarie–decembrie) e corect din prima zi, nu după ce se acumulează meciuri.
- **Deblochează munca despre „amânat".** Cu `end_date` cunoscut, un meci în
  afara intervalului devine distinct de un meci al cărui rezultat lipsește —
  azi arată identic.
- **Mic și izolat.** O tabelă, cinci coloane, un scriitor, nicio dependință
  „în sus" (North Star #10).

## Argumente CONTRA, asumate

- **E contract nou.** Tabelă nouă înseamnă scriitor nou, RLS, reguli de
  ownership și încă un lucru care poate rămâne în urmă. Nu e gratis.
- **Dependență de HTML pentru un fapt STOCAT, nu doar tranzitoriu.** Clasele
  barei sunt hash-uite (`wcl-start_TGQDT`) și se pot schimba la orice redeploy
  Flashscore. Dacă se schimbă, tabela încetează tăcut să se actualizeze și am
  servi un calendar învechit. *Mitigat, nu eliminat*: ancorare pe prefix (deja
  implementată), `observed_at` care face învechirea vizibilă, și degradare pe
  treapta 2 a cascadei.
- **Acoperire parțială.** Doar cele 17 competiții urmărite. Pragul de iulie nu
  dispare — se micșorează.
- **Hub-ul `/fixtures/` nu afișează bara** (verificat live). Doar rulările pe
  `/results/` populează intervalul, deci o competitie aflată în pauză poate
  rămâne fără calendar o vreme.
- **Beneficiu marginal ASTĂZI.** Verificat: zero meciuri înainte de 1 iulie
  2026 în oricare din cele 17 ligi, deci pragul nu taie nimic acum. Valoarea e
  în februarie 2027 și în eliminarea inferenței fragile — nu într-o pagubă
  măsurabilă azi.

## Verdict

**Pro cântărește mai greu**, dintr-un motiv concret, nu principial: alternativa
nu e „nimic", e o inferență care a cedat în ziua în care a fost scrisă.
Contraargumentul serios rămâne fragilitatea HTML — dar el se aplică la fel și
extragerii etichetei, pe care o facem deja și care e mitigată la fel.

---

## Consecințe

**Pozitive**
- Calendarul devine fapt trasabil, cu sursă și dată (North Star #9).
- Cascada are trei trepte, fiecare strict mai slabă — degradare explicită.
- Munca despre starea „amânat" capătă fundația de care are nevoie.

**Negative, acceptate**
- O tabelă în plus de întreținut și de monitorizat.
- Calendarul poate rămâne în urmă dacă Flashscore își schimbă structura;
  vizibil prin `observed_at`, nu tăcut.

**Ce NU face acest ADR**
- Nu schimbă `match_history.season` și nu atinge ADR-066.
- Nu normalizează cele 5.471 de rânduri `YYYY-YY`.
- Nu introduce starea „amânat" — rămâne ADR separat.
- Nu elimină pragul de 1 iulie; îl retrogradează la a treia treaptă.
