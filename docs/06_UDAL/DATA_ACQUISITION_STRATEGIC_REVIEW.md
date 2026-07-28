# Football Oracle — Cum arătăm datele peste 5 ani (document strategic)

**Nu e document tehnic.** Răspunde la o singură întrebare: cum construim
achiziția de date a Football Oracle astfel încât peste 5 ani să fie
stabilă, legală, ușor de întreținut, cu cele mai bune date disponibile
realist — nu ideal.

**Metodă**: cercetare `WebSearch` (citată), plus inspecție directă de
cod pentru 2 biblioteci reprezentative (`soccerdata`, `fotmob-api`, clonate
și citite direct), plus tot ce e deja MĂSURAT, real, din producția
Football Oracle (`provider_call_log`). Nicio presupunere prezentată ca
fapt.

---

## Concluzia, direct, înainte de detalii

**Combinația de API-uri oficiale (unele deja active, altele noi de
adăugat) + surse open-data punctuale e strategia corectă pentru
următorii 5 ani — nu scraping-ul, indiferent de unealtă.** Nu pentru că
UDAL ca arhitectură ar fi greșit — Faza 0/1/1.5 au demonstrat un design
solid, generic, corect — ci pentru că **realitatea externă s-a schimbat
sub noi, măsurabil, în timpul acestei cercetări**: fiecare sursă modernă
de calitate (SofaScore, WorldFootball, FotMob, WhoScored, FBref) fie
blochează activ accesul necostumat (403, confirmat live pe 2 din ele),
fie cere tehnici pe care le-am exclus explicit azi (spoofing, browser
nedetectabil, proxy, solver CAPTCHA — confirmat prin citirea directă a
codului sursă `soccerdata`). **Asta nu e o presupunere — e ce s-a
întâmplat, de două ori, în ultimele 24 de ore de lucru.**

Nu recomand abandonarea UDAL — recomand **reorientarea lui**: stratul
Tier 0 (Registry/Capability/Selection Engine) rămâne exact strategia
corectă, extins cu API-uri noi; stratul Tier 1/2 (scraper/browser) rămâne
arhitectural corect, dar **fără nicio sursă reală de pus în el azi**,
per cercetarea de mai jos — nu din lipsă de efort, ci din lipsă de surse
care să respecte simultan „date bune" ȘI „acces legitim, stabil".

---

## 1. Ce există azi, pe categorii

### API-uri oficiale

| Sursă | Status la Football Oracle | Observație cheie |
|---|---|---|
| API-Football | **Activ, 100% fiabil măsurat** | Romania SuperLiga „plan_restricted" pe planul gratuit — upgrade posibil, nu sursă nouă |
| Soccer Football Info | **Activ, 100% fiabil măsurat** | Deja acoperă statistici Romania SuperLiga live, confirmat |
| football-data.org | **Activ, 75,7% măsurat** (eșecurile = plan, nu blocare) | Nu acoperă Romania |
| ESPN (neoficial, dar stabil) | **Activ, 100% fiabil măsurat** | Fără protecție anti-bot — dovadă că „neoficial" ≠ „instabil" |
| TheSportsDB | **Activ, 100% fiabil măsurat** | |
| FootyStats API | Neintegrat | Oficial, plătit (~$36/lună+), Corners/Cards explicit — cel mai aliniat cu golul curent |
| Sportmonks | Neintegrat | Oficial, plătit (€29-99+/lună), referee/coach stats — cel mai bogat, cost proporțional |
| StatsBomb Open Data | Neintegrat | Gratuit, GitHub-hosted (zero risc de acces), dar acoperire SELECTATĂ (turnee specifice), improbabil Romania |
| Opta (Stats Perform) | Exclus | **Enterprise-only** — fără portal public de self-service, doar contact comercial |
| Wyscout | Exclus | **Enterprise-only** — confirmat ~£5.000/ligă/an (citat, utilizator real) — imposibil pentru un proiect personal |
| FotMob (API neoficială) | Exclus | **Blocat activ din oct. 2024** — header semnat `x-fm-req`, ToS interzice explicit scraping-ul; chiar și `worldfootballR` (bibliotecă matură) a renunțat la FotMob din exact acest motiv |

### Open Data

| Sursă | Status | Observație |
|---|---|---|
| Kaggle (import istoric) | **Deja folosit** | Date/ELO istorice, fără cornere/cartonașe pentru Romania |
| football-data.co.uk | **Deja folosit** | 0% Romania confirmat, dar zero risc, bogat pentru 6 ligi mari |
| openfootball (GitHub) | **Deja folosit parțial** | Zero risc (GitHub-hosted), acoperă și Champions League (calificări incluse) |
| ClubElo | Neintegrat | CSV simplu, zero risc, DOAR rating Elo — nimic altceva |
| StatsBomb Open Data | Neintegrat | Vezi mai sus |
| FiveThirtyEight (SPI) | **Mort** | Oprit definitiv 2023 (ABC News a închis FiveThirtyEight) — doar arhivă istorică 2016-2019, fără actualizări |
| FIFA („Give Voice to Football") | Nou descoperit | API public real, dar scop îngust (competiții FIFA/echipe naționale), nu ligi de club |
| UEFA | **Nu există API public oficial** | Confirmat — orice acces azi ar fi neoficial/scraping |

### Biblioteci Open Source (analizate direct, nu din memorie)

- **`soccerdata`** — vezi review-ul separat (`docs/06_UDAL/` — trimis anterior). Verdict: NU, dependent structural de spoofing/undetected-browser/proxy.
- **`worldfootballR`** (R) — aceeași familie de surse (FBref/Transfermarkt/Understat), **a renunțat oficial la FotMob** din cauza ToS — confirmă independent aceeași concluzie.
- **`fotmob-api`** (Python, citit direct din cod) — wrapper simplu, `requests` fără spoofing — DAR construit pe o API care între timp a adăugat protecție activă (`x-fm-req`); orice wrapper simplu de genul ăsta e azi, cel mai probabil, nefuncțional.
- **`pyfootball`** — wrapper abandonat (ultima versiune 2016) peste football-data.org, pe care Football Oracle îl are deja integrat NATIV, mai complet — zero valoare adăugată.

### Feed-uri oficiale (RSS/CSV/JSON/XML)

Niciun feed RSS/XML relevant găsit pentru statistici de meci granulare
(cornere/cartonașe/xG) — formatul dominant real e JSON via API sau CSV
via open-data, exact categoriile deja acoperite mai sus. Nu exagerez o
categorie care, în practică, nu există separat pentru acest domeniu.

---

## 2. Matricea pe câmpuri de date — ce se poate obține FĂRĂ scraping

| Câmp | API oficial? | Open Data? | Feed public? | Doar scraping? |
|---|---|---|---|---|
| Rezultate | **Da** (API-Football, football-data.org, ESPN, TheSportsDB) | Da (football-data.co.uk, openfootball) | — | — |
| Cornere/Cartonașe/Fauluri | **Da** (Soccer Football Info — confirmat Romania; FootyStats — Corners/Cards explicit) | Parțial (football-data.co.uk, doar 6 ligi mari) | — | — |
| xG | **Parțial** (Soccer Football Info) | Da, granular (StatsBomb Open Data, doar competiții selectate) | — | Understat (fără API oficială — doar scraping/soccerdata) |
| xA | Parțial (surse premium, neconfirmat exact) | Limitat | — | Da, majoritatea surselor bogate |
| PPDA | **Nu, nicăieri ca și câmp gata calculat** | Nu | — | Calculabil manual din date de evenimente (StatsBomb Open Data, unde există) |
| Posesie | **Da** (Soccer Football Info, FootyStats parțial) | Limitat | — | — |
| Șuturi | **Da** (Soccer Football Info) | Da (StatsBomb Open Data, selectiv) | — | — |
| Lineups | **Da** (Soccer Football Info, API-Football) | Limitat | — | — |
| Referee | **Nu confirmat la nicio sursă activă azi** | Nu confirmat | — | Da (WorldFootball, dar acces blocat azi) |
| Attendance | **Nu confirmat la nicio sursă activă azi** | Nu confirmat | — | Da (WorldFootball, dar acces blocat azi) |
| Elo | **Da** (deja sursă proprie, eloratings.net) | Da (ClubElo, neintegrat) | — | — |
| Market Value | **Nu există API oficial identificat** | Nu | — | **Doar Transfermarkt, doar scraping** — gol real, nerezolvat azi |
| Transfers | **Nu există API oficial identificat** | Nu | — | **Doar Transfermarkt, doar scraping** — gol real, nerezolvat azi |
| Injuries | **Da — deja integrat** (API-Football, migrat R-Sync-2) | — | — | — |
| Suspensions | Parțial (API-Football, neconfirmat separat de injuries) | — | — | WhoScored (`read_missing_players`, dar acces blocat/evaziv) |

**Onest**: Referee/Attendance rămân goluri reale fără sursă API/open-data
identificată azi — singura cale găsită trece prin surse blocate
(WorldFootball) sau neconfirmate. Market Value/Transfers — gol la fel de
real, aceeași concluzie (Transfermarkt, fără alternativă oficială
găsită). Nu inventez o soluție care nu există.

---

## 3. Tabel comparativ — candidați reali pentru pasul următor

| Sursă | Legalitate | Cost | Rate limit | Stabilitate | Calitate | Frecvență update | SuperLiga | Big5 | Europene | Dificultate integrare | Risc termen lung |
|---|---|---|---|---|---|---|---|---|---|---|---|
| FootyStats API | Curată (API oficială, ToS clar) | ~$36+/lună | Neconfirmat exact | Neconfirmată direct, dar API contractuală | Bună (Corners/Cards/BTTS/O-U confirmate) | Zilnic-săptămânal (declarat) | Neconfirmată explicit | Da | Neconfirmată | **Mică** — tipar identic key_manager.py existent | **Scăzut** — contract comercial, nu adversarial |
| Sportmonks | Curată | €29-99+/lună (tier-ul necesar Romaniei, neconfirmat exact) | Documentat, per plan | Ridicată (API matură, enterprise-grade) | Foarte bună (referee/coach/H2H) | Live (declarat) | Confirmată explicit (pagină dedicată găsită) | Da | Da (declarat) | **Mică** | **Scăzut** |
| Upgrade plan API-Football | Curată (deja contract existent) | Necunoscut, dar incremental | Deja cunoscut (100-1500 req/zi) | **Deja dovedită** | Deja dovedită | Deja dovedită | Deblocabilă (azi „plan_restricted", nu absentă) | Deja da | Deja da | **Minimă — zero cod nou, doar decizie de cost** | **Cel mai scăzut posibil** |
| StatsBomb Open Data | Curată (atribuire necesară) | Gratuit | N/A (fișiere statice) | Foarte ridicată (GitHub) | Foarte bună, dar acoperire imprevizibilă | Rar (periodic, pe turnee) | Improbabilă | Selectiv | Selectiv (turnee majore) | Mică | Scăzut, dar valoare limitată pentru nevoia curentă |
| ClubElo | Curată | Gratuit | Nedocumentat, dar simplu | Ridicată | Doar Elo | Zilnic (declarat) | Neconfirmată | Da | Da | Mică | Scăzut |

---

## 4. Ce înseamnă asta pentru UDAL — adevărul, nu eleganța

**UDAL Tier 0 (Provider/Capability Registry, Selection Engine) — continuă,
neschimbat.** E exact mecanismul prin care FootyStats/Sportmonks/upgrade-ul
API-Football ar intra, dacă produsul decide asta — zero rescriere.

**UDAL Tier 1/2 (Scraper/Playwright, `scraper_registry.py`,
`generic_rich_match_scraper_adapter.py`, `udal_extraction.py`) — rămân
arhitectural corecte, dar fără nicio sursă reală de folosit azi.** Nu e
un eșec de design — extractorul generic, contractul `ScraperAdapterBase`,
gate-ul `tos_reviewed` au funcționat exact cum trebuiau: au permis
verificarea rapidă, ieftină (câteva ore, nu luni) că drumul de scraping
e închis pentru sursele de calitate disponibile azi, ÎNAINTE de o
investiție mare. Componentele rămân în cod, nefolosite, pentru o sursă
viitoare care s-ar putea deschide (ex. un site mai vechi, necunoscut încă,
sau o schimbare de politică a unei surse existente) — nu se șterg, nu se
regretă construirea lor.

**Golurile reale, nerezolvate**: Referee/Attendance, Market Value/Transfers
— rămân goluri, onest raportate, fără soluție API/open-data găsită azi.
Nu le for țez cu o soluție de scraping doar ca să „le închid" — rămân
explicit „necunoscut/fără sursă legitimă identificată", per disciplina
proiectului (ADR-001).

## 5. Recomandare finală, pe 5 ani

1. **Anul 1 (acum)**: verifică upgrade de plan API-Football pentru Romania
   SuperLiga (cost marginal, zero cod nou) + evaluează FootyStats API ca
   primă sursă nouă reală (Corners/Cards, cost moderat, risc de acces
   practic zero).
2. **An 1-2**: dacă bugetul permite, Sportmonks pentru acoperire mai largă
   (inclusiv o eventuală cale spre Referee, neconfirmată încă — de
   verificat explicit înainte de a cumpăra).
3. **Permanent**: componentele UDAL Tier 1/2 rămân „gata de activare",
   nu se dezvoltă activ mai departe fără o sursă nouă, concretă, care să
   fi trecut de o verificare de acces (exact disciplina `tos_reviewed`
   deja construită) — nu se scriu adaptoare „ca să existe".
4. **Market Value/Transfers**: rămâne o decizie separată, viitoare — fie
   se acceptă golul (nu orice funcție ML are nevoie de el imediat), fie
   se redeschide, separat, o discuție dedicată despre Transfermarkt,
   cu toate riscurile puse pe masă explicit, nu presupuse azi.

**Răspunsul, direct, la întrebarea din titlu**: Football Oracle rămâne
stabil pe 5 ani construind pe contracte (API-uri, chiar plătite), nu pe
adversitate tehnică (scraping împotriva unor site-uri care își schimbă
activ apărarea — FotMob a dovedit-o în octombrie 2024, SofaScore/WorldFootball
au dovedit-o ieri). E un adevăr mai puțin „elegant" decât o arhitectură
de scraping universală — dar e cel care nu se rupe la următoarea
actualizare de Cloudflare a cuiva.
