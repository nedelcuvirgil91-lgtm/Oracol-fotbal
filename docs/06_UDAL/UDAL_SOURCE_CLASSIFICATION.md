# UDAL — Clasificarea surselor (canonic, înlocuiește §5 din raportul Faza 1.5)

**Status**: document viu, actualizat de proprietarul produsului. Raportul
`UDAL_FAZA1_5_GENERIC_VALIDATION_REPORT.md` §5 („Recommendation") rămâne
neschimbat ca înregistrare istorică a analizei tehnice — clasificarea
FINALĂ, aprobată, trăiește exclusiv aici de acum înainte.

**Data actualizării**: 2026-07-28, per decizie explicită a proprietarului
produsului („Architecture Corrections", după aprobarea Fazei 1.5).

---

## Primary Sources

Surse de primă intenție — orice țintă nouă de achiziție le verifică
întâi.

- **WorldFootball.net** — Tier 1 (HTTP Scraper, CSS). Cel mai stabil,
  cel mai simplu tehnic (§2/§3 din raportul Faza 1.5).
- **SofaScore** — Tier 1 (HTTP, API JSON neoficială). Cea mai bogată
  acoperire de categorii (7/9, per Compatibility Matrix, Faza 1.5).

## Secondary Sources

Surse complementare — folosite pentru acoperire suplimentară sau ca
fallback pe categorii pe care Primary nu le acoperă complet.

- **Soccerway** — Tier 1 (HTTP, CSS). Acoperire mai îngustă (evenimente
  de gol, nu statistici agregate confirmate).
- **FootyStats** — Tier 1 (HTTP, CSS). Acoperă odds, complexitate ușor
  mai mare decât WorldFootball.

## Premium Sources

**[SCHIMBAT — decizie explicită a proprietarului produsului]** FlashScore
**NU** mai e clasificat „Emergency" (ultimă soluție, degradat). E
**Premium** — folosit deliberat, ca alegere de calitate, DOAR atunci
când informația cerută nu poate fi obținută din Primary/Secondary.
Distincția nu e doar de vocabular: „Emergency" implica un fallback
degradat, forțat de eșecul celorlalte; „Premium" recunoaște că FlashScore
oferă acoperire reală (6/9 categorii, inclusiv lineups, per Faza 1.5) pe
care alte surse n-o au — costul (Tier 2/Playwright, infrastructură
inexistentă azi, risc de instabilitate mai mare) e motivul pentru care
nu e Primary, nu o judecată de calitate a datelor.

- **FlashScore** — Tier 2 (Playwright, infrastructură rezervată Fazei 4).

*(AiScore rămâne neclasificat formal — acoperire mai slabă, profil tehnic
neconfirmat direct, per Faza 1.5 — nu a fost menționat explicit în
decizia de reorganizare.)*

---

## Future Providers

**[ADAUGAT — decizie explicită a proprietarului produsului]** Surse
identificate ca relevante STRATEGIC pentru viitorul Football Oracle
(în special pentru Learning Core/ML) — **NU fac parte din sprintul
curent**. Niciun cod, niciun adaptor, niciun scraping, nicio verificare
ToS pentru acestea — strict poziționare arhitecturală, per cerință
explicită.

### Transfermarkt

**Categorie de date viitoare**: Squad, Market Value, Injuries,
Suspensions, Contracts, Transfers, Player Profile.

**Loc în arhitectură (proiectat, nu implementat)**: ar extinde
`DataType` (`provider_capabilities.py`) cu valori noi (`SQUAD`,
`MARKET_VALUE`, `SUSPENSIONS`, `CONTRACTS`, `TRANSFERS`, `PLAYER_PROFILE`
— niciuna dintre acestea nu există azi în enum). Categoria `INJURIES`
există deja în `DataType` — Transfermarkt ar fi primul candidat real
care s-o populeze prin UDAL (gol deja identificat, niciodată închis, nici
măcar în Faza 1.5 — vezi Compatibility Matrix). Tehnic, Transfermarkt e
cunoscut ca HTML server-rendered relativ clasic — plasare probabilă
**Tier 1**, neconfirmat.

### FBref

**Categorie de date viitoare**: xG, xA, PPDA, Progressive Passes,
Advanced Statistics.

**Loc în arhitectură (proiectat, nu implementat)**: ar alimenta
`DataType.XG` (deja existent) + extensii noi (`XA`, `PPDA`,
`PROGRESSIVE_PASSES`) — categoria `advanced_statistics` din harta de
extracție generică (`udal_extraction.py`, Faza 1.5) e deja proiectată
să acopere exact acest gen de câmpuri, fără nicio schimbare de schemă
necesară când FBref intră efectiv în scope. FBref e cunoscut ca sursă
academică/analitică, tabele HTML dense (Sports Reference network) —
plasare probabilă **Tier 1**, neconfirmată.

**Notă explicită**: ambele surse devin importante pentru Machine
Learning (nu pentru serving live) — asta le poziționează probabil pe
calea `Mode=HISTORICAL` (cadență noapte, §10 UDAL_ARCHITECTURE_SPEC),
nu `Mode=LIVE`, când vor intra efectiv în scope. Decizie de confirmat
la momentul respectiv, nu presupusă acum.

---

## Vision — actualizare

**[ADAUGAT — decizie explicită a proprietarului produsului]**

> UDAL nu mai este doar un scraper. UDAL devine: **Universal Football
> Knowledge Acquisition Layer.** Scopul este să poată integra orice
> sursă relevantă pentru Football Oracle.

Acronimul rămâne **UDAL** — numele complet se extinde conceptual de la
„Universal Data Acquisition Layer" la „Universal **Football Knowledge**
Acquisition Layer", reflectând scopul pe termen lung (zeci de surse,
inclusiv cele „Future Providers" de mai sus) fără să implice o
redenumire de cod/module — niciun fișier, clasă sau flag nu se
redenumește ca urmare a acestei actualizări ([]„Nu implementa cod",
cerință explicită). Referință normativă adăugată în
`ADR-042-universal-data-acquisition-layer.md` (notă de actualizare, nu
rescriere) și `UDAL_ARCHITECTURE_SPEC_v1.0.md` §0.
