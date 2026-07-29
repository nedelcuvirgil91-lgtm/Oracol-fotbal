# UDAL — Cercetare surse cu acces legitim și stabil (sprint de cercetare, fără cod)

**Decizie de context**: proprietarul produsului a concluzionat, după
`UDAL_POC_SCRAPER_SOURCE_01_REPORT.md`, că problema nu e arhitectura
UDAL — e alegerea surselor (WorldFootball/SofaScore, ambele blocate 403
la primul contact real). Noua strategie: surse cu acces oficial sau
foarte stabil, fără protecție anti-bot agresivă, fără ocolire de
protecții (interzis explicit — fără proxy, spoofing, browser
fingerprinting). **Acest document e strict cercetare — zero cod, zero
adaptor nou, zero schimbare de arhitectură.**

**Metodă**: cercetare via `WebSearch` (citată per secțiune) + auditul
DEJA EXISTENT al fiabilității reale, măsurate, din `provider_call_log`
(citat din verificarea acestei sesiuni, nu re-executat acum). Deliberat
**n-am reîncercat niciun fetch live** pentru sursele noi din acest
raport — exact lecția din POC_SCRAPER_SOURCE_01: nu se testează live o
sursă înainte de o evaluare de bază a tipului de acces (API oficial vs.
HTML scraping) și fără aprobare separată, per sursă.

---

## 0. Precedent intern, deja măsurat (nu presupus)

Proiectul are DEJA 5 surse active, verificate reale, prin
`provider_call_log` (interogare directă Supabase, în aceeași sesiune,
fereastra 7 zile): `espn` (492 apeluri, **100% fiabilitate**), `thesportsdb`
(325 apeluri, **100%**), `soccerfootballinfo` (183 apeluri, **100%**),
`apifootball` (12 apeluri, **100%**), `footballdata` (37 apeluri, 75,7%,
403 doar pe competiții neacoperite de plan, nu blocare generală). Acestea
sunt dovada directă că **nu orice sursă „găsită"/neoficială e blocată**
(ESPN e API neoficial, dar 100% fiabil) — diferența reală e între surse
protejate agresiv anti-bot (Cloudflare modern, cazul WorldFootball/SofaScore)
și surse care nu au un asemenea strat de protecție, indiferent dacă sunt
„oficiale" în sensul de documentate public.

---

## 1. Top 10 surse recomandate

| # | Sursă | Tip acces | ToS | robots.txt | Stabilitate | Acoperire competiții | Acoperire statistici | Latență estimată | Limitări | Risc întrerupere | Mentenanță | Compatibil UDAL |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | **API-Football (api-sports.io)** | API oficială, cheie REST | Documentată, comercială | N/A (API, nu HTML) | **Foarte ridicată** — deja integrat, 100% fiabil (12/12 apeluri, măsurat) | Romania Liga I confirmată ca existentă în catalog, dar **plan_restricted** pe planul gratuit (deja confirmat prin test, `test_romania_superliga_api_football_plan_restricted`) | Foarte largă pe planurile plătite (fixtures/statistics/lineups/odds) | Mică (API REST simplu) | Cota (100-1500 req/zi în funcție de plan) | Foarte scăzut | Foarte ușoară — deja integrat, doar upgrade de plan | **Totală** — deja Tier 0, deja în `key_manager.py` |
| 2 | **Soccer Football Info (RapidAPI)** | API oficială (marketplace RapidAPI), cheie | Documentată, prin RapidAPI (contract de platformă) | N/A | **Foarte ridicată** — 100% fiabil (183/183 apeluri, măsurat) | **Romania SuperLiga CONFIRMATĂ live** (ADR-041, verificat 2026-07-27, meci verificat câmp cu câmp) | Statistics/xG/lineups/managers/standings — deja confirmat | Mică-medie | 200 req/zi (plan curent) | Scăzut | Ușoară — deja integrat complet | **Totală** — deja Tier 0, deja producție |
| 3 | **football-data.org** | API oficială, cheie (header) | Documentată, gratuită cu limite | N/A | **Foarte ridicată** — deja integrat, măsurat (75,7%, singurele eșecuri fiind 403 pe competiții neacoperite de plan, nu blocare) | **Romania SuperLiga confirmată NEACOPERITĂ** (documentat deja) | Standings/fixtures pe ligile acoperite | Medie (~1,3s măsurat) | 10 req/minut (plan gratuit) | Scăzut | Foarte ușoară — deja integrat | **Totală** — deja Tier 0 |
| 4 | **ESPN (API neoficială, hidden)** | JSON neoficial, fără cheie | Nedocumentată explicit, dar folosită public pe scară largă | Neverificat direct | **Foarte ridicată — măsurat 100% (492/492 apeluri)** | Fixtures multi-ligă, acoperire generală bună | Limitată la fixtures/scoruri, nu statistici detaliate | Mică (11-89ms, măsurat) | Necunoscute (fără contract) | **Necunoscut, dar 0% eșec măsurat pe 7 zile** | Foarte ușoară — deja integrat | **Totală** — deja Tier 0 |
| 5 | **TheSportsDB** | API oficială (free tier), cheie generică | Documentată | N/A | **Foarte ridicată — măsurat 100% (325/325 apeluri)** | Multi-ligă, inclusiv Romania (confirmat existent în catalogul lor, per pagina publică găsită) | Fixtures + unele statistici de echipă | Mică (94-105ms, măsurat) | Rate-limit generos pe tier gratuit | Scăzut | Foarte ușoară — deja integrat | **Totală** — deja Tier 0 |
| 6 | **FootyStats API** | API oficială, plătită, cheie | Documentată (`footystats.org/terms-and-conditions`) | N/A | Neconfirmată direct (nouă pentru proiect), dar e API oficială, nu scraping | 200+ ligi declarate; **acoperire exactă Romania Liga 1 neconfirmată** | Explicit: Over/Under, BTTS, **Corners, Cards** — exact golul căutat | Necunoscută, dar API REST simplu (nu scraping) | Cost: de la ~$36/lună | Scăzut (API comercială, contract clar) | Ușoară — tipar identic key_manager.py existent | **Foarte ridicată** — o cheie nouă, zero cod nou de scraping |
| 7 | **Sportmonks** | API oficială, plătită, cheie | Documentată, comercială | N/A | Neconfirmată direct, dar API oficială matură (categorie „enterprise") | 2.500+ ligi declarate, pagină dedicată „Liga 1 API Romania" găsită explicit | Foarte largă — referee stats, coach stats, lineups, H2H, odds | Necunoscută, dar API REST | Cost: de la €29/lună (tier minim acoperă doar 2 ligi — Romania ar necesita tier mai mare) | Scăzut | Ușoară — tipar identic | **Ridicată** — dar cost mai mare decât FootyStats pentru aceeași nevoie |
| 8 | **football-data.co.uk** | Fișiere CSV statice, fără autentificare | Permisivă (folosit deja de acest proiect, ani de zile, fără incident) | N/A (fișiere statice) | **Foarte ridicată** — deja folosit cu succes în proiect | Cele 6 ligi majore acoperite; **Romania SuperLiga confirmată 0%** (documentat deja) | Foarte bogată pentru ligile acoperite (shots/corners/cards/fouls) | Mică (download simplu) | Fără cornere/carduri pentru Romania — nu închide golul curent | Foarte scăzut | Foarte ușoară — deja integrat | **Totală** — deja folosit (`sync/sources/football_data_co_uk.py`) |
| 9 | **StatsBomb Open Data (GitHub)** | Date statice, JSON, git/raw fetch de pe GitHub | Necesită atribuire (StatsBomb User Agreement) — permisivă pentru cercetare | N/A (GitHub, nu scraping) | **Foarte ridicată** — servit de GitHub însuși, aceeași platformă ca runner-ul CI | Doar competiții/turnee SELECTATE, lansate periodic de StatsBomb — **improbabil să acopere Romania SuperLiga curent** | Foarte bogată (event-level) DOAR pentru ce e acoperit | Mică (fetch de pe GitHub) | Acoperire imprevizibilă/limitată la ce a fost publicat | Foarte scăzut (fișiere statice, versionate) | Ușoară — fără scraping deloc | **Medie** — util pentru cercetare ML avansată, nu pentru golul curent |
| 10 | **OpenLigaDB** | API oficială, REST, **fără autentificare** | Permisivă, publică prin design | N/A | Ridicată (design public, fără cheie de gestionat) | **Focalizat pe ligile germane** — Romania SuperLiga improbabil acoperită | Fixtures/rezultate/clasamente — nu statistici detaliate | Mică | Acoperire geografică îngustă | Scăzut | Foarte ușoară | **Scăzută** pentru golul curent, utilă doar pentru extindere viitoare Germania |

---

## 2. Clasament argumentat

**Nivel 1 — deja active, deja dovedite (risc zero de integrare, pentru
că nu e integrare, e extindere)**: API-Football, Soccer Football Info,
football-data.org, ESPN, TheSportsDB, football-data.co.uk. Toate 6 au
fiabilitate MĂSURATĂ, nu presupusă — niciuna n-a fost blocată vreodată.
**Observație centrală, care schimbă cadrul discuției**: Soccer Football
Info **acoperă deja** statistici de meci pentru Romania SuperLiga, live,
confirmat — golul care a motivat UDAL ar putea fi deja parțial închis de
infrastructura existentă, nu de o sursă nouă.

**Nivel 2 — candidați noi, oficiali, cu cost real dar risc de acces
scăzut**: FootyStats API (cel mai bun raport acoperire-relevanță/cost
pentru golul curent — Corners/Cards explicit menționate), Sportmonks
(cel mai bogat, dar cost mai mare pentru tier-ul necesar Romaniei).

**Nivel 3 — utile pentru extindere viitoare, nu pentru golul curent**:
StatsBomb Open Data (cercetare ML avansată, acoperire imprevizibilă),
OpenLigaDB (doar ligi germane).

## 3. Recomandare Primary/Secondary/Premium

**Primary Sources** (folosite curent, dovedite, prima linie de apărare):
- API-Football, Soccer Football Info, football-data.org, TheSportsDB, ESPN
  — deja Tier 0, deja producție, zero risc suplimentar.

**Secondary Sources** (candidați noi, oficiali, integrare cu risc scăzut):
- **FootyStats API** — cel mai aliniat cu golul documentat (Corners/Cards
  explicit).
- football-data.co.uk — deja folosit, dar plafonat la ce acoperă deja
  (nu Romania).

**Premium Sources** (cost mai mare, valoare mai mare, pentru extindere
serioasă, nu pentru primul pas):
- **Sportmonks** — cea mai largă acoperire (referee/coach/H2H), cost
  proporțional mai mare.
- StatsBomb Open Data — „premium" în sensul de calitate a datelor
  (event-level), nu de cost, dar acoperire imprevizibilă.

## 4. Plan de integrare în UDAL

**Observație arhitecturală importantă**: toate sursele din Nivelul 1 și
2 (API-Football, Soccer Football Info, football-data.org, TheSportsDB,
ESPN, FootyStats, Sportmonks) sunt **Tier 0 (API)**, NU Tier 1/2
(scraper) — asta înseamnă că, per axa strictă de precedență din
ADR-042, ele n-ar trece deloc prin `scraper_registry.py`/
`ScraperAdapterBase`/`tos_reviewed` — ar intra prin `provider_registry.py`/
`provider_capabilities.py`, exact calea deja folosită pentru cei 9
provideri existenți. **UDAL, ca strat de tier-uri, rămâne relevant mai
ales pentru Tier 1/2** — dacă strategia se mută integral spre API-uri
oficiale, componentele Tier 1/2 construite în Faza 0/1/1.5
(`scraper_registry.py`, `generic_rich_match_scraper_adapter.py`,
`udal_extraction.py`) rămân neutilizate pentru moment, nu inutile — ele
rămân disponibile pentru orice sursă viitoare fără API oficial (poziția
lor arhitecturală, per ADR-042, nu se schimbă).

Pași (fără cod, doar plan):
1. **Verifică întâi cât de mult din gol e deja acoperit** de Soccer
   Football Info (deja live) — un audit de completitudine, nu o
   integrare nouă.
2. **Dacă rămâne gol real** (probabil pe Referee/Attendance, pe care
   niciuna din sursele active nu pare să le acopere explicit): evaluează
   FootyStats API ca cea mai apropiată sursă nouă, prin exact tiparul
   deja folosit (`key_manager.py` → provider nou, `provider_capabilities.py`
   → capabilități, `provider_registry.py` → înregistrare) — Tier 0, NU
   trece prin infrastructura de scraping.
3. **Sportmonks rămâne opțiune de rezervă**, pentru extindere serioasă
   ulterioară, dacă bugetul o justifică.
4. **Componentele UDAL Tier 1/2 rămân „on hold"**, nu abandonate — utile
   pentru o sursă viitoare fără API oficial, dar NU pentru pasul imediat
   următor.

## 5. Recomandarea finală — ce sursă se implementează prima

**Nu o sursă nouă — o verificare.** Recomandarea mea: înainte de orice
integrare nouă, un audit rapid (Supabase, read-only, deja posibil cu
infrastructura existentă) al COMPLETITUDINII reale a datelor Soccer
Football Info pentru Romania SuperLiga (câte meciuri, ce câmpuri
populate) — pentru că e deja Tier 0, deja live, deja dovedit. Dacă acel
audit arată un gol real rămas (cel mai probabil pe Referee/Attendance),
**FootyStats API** e recomandarea mea pentru prima sursă NOUĂ de
implementat — API oficială, cost moderat, acoperire explicită pe
Corners/Cards, risc de acces practic zero (nu e scraping), integrare
prin tiparul deja dovedit de 9 ori în acest proiect.
