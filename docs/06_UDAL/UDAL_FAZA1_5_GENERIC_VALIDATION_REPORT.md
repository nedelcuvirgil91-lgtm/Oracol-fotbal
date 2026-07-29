# UDAL Faza 1.5 — Generic Scraper Validation (ADR-042)

**Obiectiv**: demonstrăm că arhitectura UDAL e genuin generică — poate
funcționa pe mai multe surse diferite schimbând DOAR configurația
(hartă de extracție), NU codul. **Nu validăm un site — validăm
arhitectura.** Toate cifrele de mai jos vin dintr-o rulare reală
(`scripts/udal_faza1_5_validation_run.py`), nu simulate.

**Constrângeri respectate, verificate direct**: niciun scraping live
(`fetch()` acceptă strict `mode="fixture"`; Tier 2 nu are deloc `fetch()`
funcțional — ridică `NotImplementedError`), niciun flag activat, Oracle
Engine/ML neatinse, nicio scriere canonică (nici măcar în tabelele UDAL
din Faza 0 — acest sprint a rămas 100% local, zero interacțiune Supabase),
fără merge în `main`.

**Metodă și limitare declarată explicit**: fixture-urile pentru cele 6
surse sunt **reprezentative, NU capturate live** — `WebFetch` a rămas
blocat în această sesiune (confirmat din nou, ca în Faza 1). Structura
fiecărui fixture reflectă cercetare reală via `WebSearch` (citată per
secțiune), inclusiv proiecte open-source de scraping ale comunității
pentru fiecare site — dar nu e o copie a unei pagini reale. Datele din
fixture-uri sunt placeholder (echipe/jucători inventați), niciodată
prezentate ca reale.

---

## Descoperire arhitecturală centrală, înainte de tabele

Cercetarea (WebSearch) a arătat că cele 4 surse Tier A **nu sunt
tehnic omogene** — fapt onest, nu ascuns pentru simetria tabelelor:

- **worldfootball.net, Soccerway** — HTML static/server-rendered
  clasic, confirmat de multiple proiecte comunitate care le extrag cu
  BeautifulSoup. **Tier 1 (HTTP Scraper), extracție CSS.**
- **SofaScore** — front-end JS, DAR cu o API JSON neoficială,
  descoperibilă (`sofascore.com/api/v1/...`), folosită direct de
  scraperele comunității (nu HTML parsat). **Tot Tier 1 (acces HTTP
  simplu, fără browser), dar extracție JSON path, nu CSS** — o axă nouă,
  ORTOGONALĂ față de tier, nu un tier nou.
- **Flashscore** — SPA JS fără API oficială, confirmat de comunitate
  (`gustavofariaa/FlashscoreScraping`) ca necesitând automatizare de
  browser (Puppeteer). **Tier 2 (Playwright) — obligatoriu**, nu opțiune.

Asta înseamnă: o cerere de „selector map identic pentru toate" ar fi fost
tehnic incorectă pentru SofaScore/Flashscore — nu din limitare de
implementare, ci din natura reală a surselor. Am construit în schimb
**două axe independente** (`tier` pentru `fetch()`, `extraction_type`
pentru `normalize()`), verificate separat mai jos.

## Proba de reutilizare (verificată programatic, nu declarată)

```json
"tier1_css_shared_class": ["GenericRichMatchScraperAdapter"],
"normalize_shared_between_tier1_and_tier2": true
```

- **O singură clasă** (`GenericRichMatchScraperAdapter`) a rulat, neschimbată,
  pentru worldfootball.net, Soccerway și FootyStats — doar harta de
  extracție a diferit.
- `type(html_adapter).normalize is type(playwright_adapter).normalize` →
  **`True`**, verificat direct (nu doar rezultat echivalent — ACELAȘI
  obiect metodă în memorie, moștenit dintr-un mixin comun,
  `_CssExtractionNormalizeMixin`). Parsarea e 100% comună între Tier 1 și
  Tier 2 — doar `fetch()` diferă, exact cum impune designul din Faza 0
  (`AcquisitionTier` ca axă strictă).

---

## 1. Compatibility Matrix

| Site | Match | Teams | Score | Statistics | Advanced (xG) | Lineups | Player Stats | Injuries | Odds |
|---|---|---|---|---|---|---|---|---|---|
| worldfootball.net | ✓ | ✓ | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Soccerway | ✓ | ✓ | ✓ | ✗ | ✗ | ✗ | ~ (doar evenimente de gol) | ✗ | ✗ |
| FootyStats | ✓ | ✓ | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ | ✓ |
| SofaScore | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ | ✗ |
| Flashscore | ✓ | ✓ | ✓ | ✓ | ✗ | ✓ | ✗ | ✗ | ✓ |
| AiScore | ✓ | ✓ | ✓ | ~ (light) | ✗ | ✗ | ✗ | ✗ | ✓ |

**Constatare onestă, nu ascunsă**: **niciuna** din cele 6 surse cercetate
n-a confirmat date de **accidentări per meci** structurate — categoria
rămâne un gol real, neînchis de niciun candidat din acest lot (accidentările
apar de obicei ca secțiuni separate de „echipă/știri", nu atașate unui
raport de meci). Rămâne o investigație separată, viitoare.

## 2. Selector Complexity

| Site | Complexitate | Motiv |
|---|---|---|
| worldfootball.net | **Ușor** | Tabele HTML clasice, plate, clase simple — confirmat de simplitatea reală a hărții de extracție folosite. |
| Soccerway | **Ușor-mediu** | Structură clasică, dar cu o listă repetată (evenimente de gol) — puțin nesting. |
| FootyStats | **Mediu** | Site „modern" (per descriere publică), posibil parțial dinamic — neconfirmat direct în această sesiune. |
| SofaScore | **Mediu** | Extragerea propriu-zisă (JSON path) e simplă odată găsită structura — dificultatea reală e în DESCOPERIREA endpoint-urilor neoficiale (necesită inspecție manuală network, per proiectele comunității), nu în parsare. |
| Flashscore | **Dificil** | SPA, clase deseori generate/obfuscate dinamic (cunoaștere comunitate) — randare JS obligatorie înainte de orice extracție. |
| AiScore | **Dificil (probabil)** | Profil tehnic neconfirmat direct — tratat conservator, similar Flashscore, dat fiind produsul de tip live-score modern. |

## 3. HTML Stability

| Site | Stabilitate | Risc de rupere |
|---|---|---|
| worldfootball.net | **Ridicată** | Design vechi, schimbat rar (inferență din vechimea/stilul site-ului — nemăsurată direct). |
| Soccerway | **Moderat-ridicată** | Similar — site clasic, structură URL/HTML consistentă confirmată de comunitate. |
| FootyStats | **Moderată** | Site activ, posibile redesign-uri periodice. |
| SofaScore | **Moderată** | API-ul neoficial poate migra la orice rescriere de front-end (fără preaviz — nu e un contract public), dar structura JSON tinde să fie mai stabilă decât CSS-ul unei pagini randate, odată descoperită. |
| Flashscore | **Scăzută** | SPA modern, actualizat frecvent, structură DOM volatilă (cunoaștere generală despre site-uri de acest tip). |
| AiScore | **Scăzută (probabil)** | Neconfirmat direct — tratat conservator. |

## 4. Generic Adapter Score

| Site | Scor | Verificat |
|---|---|---|
| worldfootball.net | **Merge doar cu selector map** | ✓ rulare reală, `GenericRichMatchScraperAdapter` neschimbat |
| Soccerway | **Merge doar cu selector map** | ✓ rulare reală, aceeași clasă |
| FootyStats | **Merge doar cu selector map** | ✓ rulare reală, aceeași clasă |
| SofaScore | **Necesită adaptor nou (minimal)** | `GenericJsonMatchScraperAdapter` — diferă DOAR `extraction_type` (JSON path vs. CSS); `validate()`/`persist()` rămân identice (moștenite din aceleași mixin-uri) |
| Flashscore | **Necesită adaptor nou pentru `fetch()`** (Tier 2/Playwright, infra inexistentă azi) — dar `normalize()` moștenit NESCHIMBAT | ✓ verificat: `is` identity check pe metodă |
| AiScore | La fel ca Flashscore | Structural identic, neconfirmat empiric (fără fixture rulat separat de Flashscore la acest nivel de detaliu) |

## 5. Recommendation

**[NOTĂ 2026-07-28]** Clasificarea de mai jos e păstrată neschimbată ca
înregistrare istorică a analizei tehnice din Faza 1.5. Clasificarea
FINALĂ, aprobată de proprietarul produsului (Primary/Secondary/**Premium**
— FlashScore NU mai e „Emergency"), trăiește exclusiv în
`docs/06_UDAL/UDAL_SOURCE_CLASSIFICATION.md`.


**Primary Scraper** (cele mai stabile, gata de `POC_SCRAPER_SOURCE_01`
fără cod nou, doar selector map):
- **worldfootball.net** — cel mai simplu, cel mai stabil, acoperă exact
  golul deja documentat (statistici Romania SuperLiga).
- **FootyStats** — acoperire mai largă (inclusiv odds), complexitate
  puțin mai mare, tot Tier 1 fără cod nou.

**Secondary Scraper** (fallback, valoare mare dar risc/efort mai mare):
- **Soccerway** — acoperire mai îngustă (fără statistici agregate
  confirmate), dar util pentru evenimente de gol.
- **SofaScore** — cea mai bogată sursă din tot lotul (7/9 categorii,
  inclusiv xG și lineups) — dar cere un adaptor nou (mic) și poartă risc
  mai mare: API neoficial, fără contract public, plus aceeași întrebare
  legală/ToS nerezolvată ca orice altă sursă (§16.1, neschimbată de acest
  sprint).

**Emergency Only** (doar dacă celelalte nu acoperă golul):
- **Flashscore** — cea mai bogată acoperire structurală (6/9) dintre
  sursele Tier 2, dar cost/risc/instabilitate cele mai mari — cere
  infrastructură Playwright inexistentă azi (Faza 4) și e cunoscută
  pentru protecție anti-bot activă.
- **AiScore** — profil tehnic neconfirmat, acoperire mai săracă — cea mai
  slabă recomandare din lot, nu justifică investiția înaintea celorlalte.

---

## Ce NU s-a schimbat (verificat, nu declarat)

- Niciun flag UDAL nu a fost activat (`udal_config.py` neatins).
- Niciun `tos_reviewed` nu a fost marcat `True` — `scraper_registry.py`
  rămâne cu O SINGURĂ intrare (pilotul din Faza 1), acest sprint n-a
  adăugat intrări noi în registry-ul „de producție" — cele 6 configurări
  de extracție trăiesc separat, în `docs/06_UDAL/site_configs/`, ca
  artefacte de analiză, nu ca surse înregistrate pentru rulare.
- Zero apeluri Supabase în acest sprint — pur local.
- `pytest tests/`: 1660 passed (+23 față de Faza 1), 2 skipped, aceleași
  3 eșecuri pre-existente, nelegate.

## Fișiere adăugate

`udal_extraction.py` (extractor generic, CSS + JSON path),
`generic_rich_match_scraper_adapter.py` (3 adaptoare, 2 mixin-uri comune),
`scripts/udal_faza1_5_validation_run.py`, `docs/06_UDAL/fixtures/faza1_5/`
(6 fixture-uri), `docs/06_UDAL/site_configs/` (6 hărți de extracție),
teste noi: `test_udal_extraction.py`, `test_generic_rich_match_scraper_adapter.py`,
extensie `test_udal_validation.py` (`validate_identity_only`).

## Recomandare pentru pasul următor

Rămâne, per decizia ta explicită din Faza 1, exclusiv a ta: dacă acest
sprint validează arhitectura suficient, următorul pas rămâne
`POC_SCRAPER_SOURCE_01` — pe **o singură sursă**, aleasă de tine (probabil
`worldfootball.net`, per scorul cel mai bun din acest raport, dar decizia
rămâne integral a ta), izolat pe GitHub Actions, cu aprobare explicită
`tos_reviewed=True` abia după acel POC.
