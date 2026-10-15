# ADR-074 — Istoric de cote din Flashscore (capturi multiple în `odds_fallback_flashscore`)

**Status**: PROPOSED — 2026-10-15. Nicio linie de cod scrisă. Cere aprobare explicită înainte de implementare.

**Declanșator**: întrebarea proprietarului produsului, 2026-10-15 — *„de ce depindem atât de Odds API? Dacă cotele le luăm din Flashscore, nu înțeleg de ce mai depindem de Odds API? Că așa vom avea probleme și cu noile campionate când vom dori să le adăugăm."*

Întrebarea e corectă, iar măsurătoarea îi dă dreptate pe aproape toate axele. Acest ADR tratează singura axă pe care nu i-o dă.

---

## 1. Context — ce am măsurat, nu ce presupunem

Două surse de cote coexistă azi:

| | `odds_history` (Odds API) | `odds_fallback_flashscore` (ADR-043) |
|---|---:|---:|
| Meciuri acoperite, cumulat | 2003 | 1341 *(pornit 4 aug)* |
| **Case de pariuri per meci** | **1,57** | **5,53** |
| Case distincte | 26 | 16 |
| Deschidere + închidere | **da** (3136 + 3136) | **nu** |
| Capturi per (meci, casă) | multiple | **exact 1** (7416 din 7416) |
| Conference League / HNL | **nu le acoperă** | **le acoperă** (123/147, 44/51) |
| Cost | cotă zilnică, cronic epuizată | zero |

**Flashscore e deja sursa mai bună pentru value betting**: de 3,5× mai multe case per meci — deci preț mai bun găsit — plus două competiții pe care Odds API nu le are deloc.

**Singurul lucru pe care Odds API îl oferă și Flashscore nu: mișcarea cotei** (deschidere → închidere). Și aceea **nu e o limită a providerului**, ci a modului în care stocăm: `upsert_odds_fallback_flashscore()` scrie pe cheia `(fixture_id, bookmaker)`, deci fiecare captură o suprascrie pe precedenta. Verificat: 7416 de perechi, 7416 de capturi — exact una fiecare, fără excepție.

Fluxul care alimentează tabela (`sync_pre_match_odds.yml`) rulează **de două ori pe zi**. Deci datele pentru o serie temporală trec deja prin noi, de două ori pe zi, și le aruncăm.

### Ce NU rezolvă acest ADR

Defectul descoperit în aceeași zi — batch-ul de noapte vedea 16 din 18 competiții, fiindcă `get_matches_for_week()` cădea pe `ODDS_SPORT_KEYS` — **nu are legătură cu sursa de cote** și se repară separat (vezi `mappings.TRACKED_COMPETITIONS`). Acela era un accident de denumire, nu o dependență de provider. Se menționează aici fiindcă a fost găsit căutând răspunsul la aceeași întrebare, și pentru că împreună dau impresia falsă că „Odds API e problema".

---

## 2. Decizia propusă

`odds_fallback_flashscore` păstrează **capturi multiple** per `(fixture_id, bookmaker)`, în loc să le suprascrie.

Consumatorii aleg explicit captura:

- **cea mai veche** → echivalentul funcțional al `opening_*`;
- **cea mai recentă dinainte de lovitura de start** → echivalentul lui `closing_*`.

Niciun consumator nu primește „ultima scrisă", semantica de azi, care nu e nici una, nici alta.

## 3. Consecințe

### Ce se schimbă

1. **Schema**: constrângerea de unicitate trece de la `(fixture_id, bookmaker)` la `(fixture_id, bookmaker, captured_at)`. Migrare idempotentă, RLS activ, scriere doar prin `service_role` — ca orice tabelă nouă.
2. **`get_odds_fallback_for_missing_fixtures()`** trebuie să aleagă captura, nu să presupună că există una singură. Azi presupune.
3. **`value_selector_shadow._completeaza_din_fallback()`** moștenește alegerea. Documentația lui spune deja „`opening_*` preferat, capturat cel mai devreme, deci cel mai sigur anterior startului" pentru sursa primară — cu acest ADR, afirmația devine adevărată și pentru rezervă.
4. **Volum**: două capturi/zi × ~5,5 case × meciurile ferestrei. Pe acoperirea actuală, estimativ 10-15× volumul de azi al tabelei. **De măsurat înainte, nu de estimat** — aceeași disciplină care a corectat de două ori cifrele ferestrei radarului în ziua redactării.

### Ce NU se schimbă

- `odds_history` și `services/odds_persistence_service.py` rămân **neatinse**. `ODDS_PERSISTENCE_DESIGN.md` e Frozen (ADR-005/006/010) și acoperă exclusiv acel flux; `odds_fallback_flashscore` e ADR-043 și **nu figurează în `FROZEN_REGISTRY.md`** — verificat, nu presupus.
- Nicio predicție, nicio formulă, niciun prag.
- Odds API **nu se oprește**. Regula proiectului pentru provideri e explicită: sistemul existent rămâne activ până când cel nou dovedește că îl poate înlocui fără regresii. Acest ADR creează condiția tehnică pentru acea dovadă; nu o declară obținută.

### Riscul principal, numit explicit

Schimbarea sursei de cote a radarului **schimbă experimentul F2 în curs** — a treia oară după lărgirea universului de competiții. De aceea:

- se implementează **după** ce F2 atinge pragul de eșantion (proiectat 26-29 octombrie, `DE_URMARIT.md` §3ter);
- primește **propriul marcaj de perioadă**, pe modelul `detecteaza_cutoff()` din `value_selector_evaluation.py`;
- nu se bundle-uiește cu nicio altă schimbare.

## 4. Alternative respinse

**(a) Să renunțăm la Odds API acum.** Respinsă: am pierde mișcarea cotei fără să fi demonstrat că o putem reconstrui din Flashscore. Întâi se construiește înlocuitorul, se compară, abia apoi se discută eliminarea — niciodată invers.

**(b) Să lăsăm lucrurile așa.** Respinsă prin măsurătoare: fluxul colectează deja datele de două ori pe zi și le aruncă. Costul de a le păstra e spațiu; costul de a nu le păstra e că nu se mai pot recupera niciodată retroactiv.

**(c) O tabelă nouă, separată, pentru serie.** Respinsă: ar fi a doua sursă de adevăr pentru aceeași informație, exact tiparul pe care proiectul l-a respins deja la `scheduled_fixtures` vs. `match_history` (ADR-070, varianta (b)).

## 5. Verificare cerută înainte de implementare

1. Volumul real măsurat, nu estimat: câte rânduri/zi produc efectiv cele două rulări.
2. Politica de retenție decisă **în același timp**, nu ulterior — tabela nu are una azi, la fel ca `shadow_predictions` și `value_selector_shadow`. Un istoric care crește fără limită e felul în care golul se mută, nu se rezolvă.
3. F2 trecut de prag, cu verdictul consemnat.
