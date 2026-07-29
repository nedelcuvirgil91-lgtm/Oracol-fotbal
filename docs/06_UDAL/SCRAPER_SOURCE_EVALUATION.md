# Evaluare surse candidate pentru scraper pilot — UDAL Faza 1

**Scop**: comparație informativă a 5 surse publice candidate pentru statistici
de meci (cornere/cartonașe/faulturi) Romania SuperLiga — golul deja documentat
(`DATASET_CAPABILITY_AUDIT_2026-07-13.md`, `FIELD_CAPABILITY_MATRIX.md`).
**Acest document NU aprobă nicio sursă pentru scraping** — per decizia
explicită a proprietarului produsului, toate rămân `tos_reviewed=False` în
`scraper_registry.py` până la un POC izolat dedicat + aprobare separată,
per sursă (§4 din decizia de arhitectură care a cerut acest document).

**Metodă și limitări, declarate explicit**: cercetarea de mai jos s-a făcut
exclusiv prin `WebSearch` (rezultate citate per rând). `WebFetch` direct
(pentru `robots.txt`/pagini de Termeni) a fost **blocat integral** în
această sesiune — confirmat inclusiv pe `example.com` (HTTP 403), nu doar
pe site-urile candidate — deci nu e o restricție per-site, e o limitare a
mediului curent de execuție. Coloanele `robots.txt` și `ToS` de mai jos NU
sunt afirmații verificate live — sunt marcate explicit „neverificat" peste
tot, per disciplina „Verificat, nu presupus". Verificarea reală rămâne
exclusiv sarcina POC-ului izolat pe GitHub Actions (§4, planul aprobat),
care rulează pe un runner cu acces real la internet.

**Observație laterală, nu candidat de scraping**: `footystats.org` oferă
și o **API JSON oficială, plătită** (de la ~$36/lună, per pagina lor de
pricing) — nu doar un site scrapeable. Per North Star-ul proiectului
(preferință structurală API > Scraper), dacă acoperă Romania SuperLiga,
ar fi o alternativă de Tier 0 mai sigură decât scraping-ul site-ului lor —
rămâne o decizie separată, a proprietarului produsului, dacă merită
costul; nu face parte din compararea de scraping de mai jos.

---

## Tabel comparativ

| | worldfootball.net | corner-stats.com | windrawwin.com | footystats.org (site, nu API) | flashscore.com |
|---|---|---|---|---|---|
| **URL** | `worldfootball.net/competition/co66/romania-liga-1/` | `corner-stats.com/liga-i/romania/tournament/27` | `windrawwin.com/statistics/corners/romania-liga-i/` | `footystats.org/romania/liga-i` | `flashscore.com` (Liga I) |
| **Tip date disponibile** | Rezultate, clasament, marcatori, **statistici pagini dedicate**: cornere, faulturi, cartonașe (confirmat via WebSearch — pagini `team-statistics-fouls-committed`, etc.) | Goluri, cornere, cartonașe, **arbitri** — poziționat explicit ca „advanced stats" | Cornere, posesie, șuturi, faulturi — poziționat ca statistici agregate per echipă/rezultat | Over/Under, BTTS, cornere, cartonașe, goluri — foarte larg (200 ligi declarate) | Scor live, statistici live per meci (posesie/șuturi/cornere/cartonașe), lineup — cel mai bogat set, dar predominant randat JS |
| **Acoperire competiții** | 300+ ligi declarate, inclusiv Romania Liga 1 confirmat live (pagină dedicată găsită) | Romania Liga I confirmat (`tournament/27`) | Romania Liga I confirmat, pagină dedicată | 200 ligi declarate; **acoperirea exactă a Romania Liga 1 neconfirmată** în rezultatele de căutare | Acoperire foarte largă, cvasi-globală (cunoaștere generală despre Flashscore, nu verificat per-ligă aici) |
| **Acoperire istorică** | Nu s-a confirmat adâncimea exactă în sezoane — site vechi, cunoscut cu arhive multi-sezon (cunoaștere generală, neconfirmat live) | **Neconfirmat** — rezultatele de căutare nu specifică | **Neconfirmat** — rezultatele de căutare nu specifică | Neconfirmat | Istoric live/recent bun, arhivă profundă multi-sezon incertă |
| **Statistici disponibile relevante golului** | Cornere ✓, Faulturi ✓, Cartonașe ✓ (confirmat) | Cornere ✓, Cartonașe ✓, **Arbitru** ✓ (relevant — al doilea gol documentat, Referee/Attendance) | Cornere ✓, Posesie ✓, Șuturi ✓ — **fauluri/cartonașe neconfirmate explicit** | Cornere ✓, Cartonașe ✓ (declarat generic „Corners, Cards" în descrierea API/site) | Toate — cel mai complet set, dar acces predominant live, nu neapărat istoric per-meci ușor de extras |
| **`robots.txt`** | **NEVERIFICAT** — WebFetch blocat în sesiune | **NEVERIFICAT** | **NEVERIFICAT** | **NEVERIFICAT** | **NEVERIFICAT** |
| **ToS** | **NEVERIFICAT** | **NEVERIFICAT** | **NEVERIFICAT** | Are pagină dedicată `footystats.org/terms-and-conditions`, conținut exact **neconfirmat** aici | **NEVERIFICAT** (cunoaștere generală: majoritatea site-urilor sportive mari interzic explicit scraping-ul automat în ToS) |
| **Dificultate tehnică** | Scăzută — site clasic, structură HTML simplă, tabele (cunoaștere generală despre worldfootball.net, familie de site-uri „simple tables" folosită frecvent ca exemplu didactic de scraping ușor) | Probabil scăzută-medie — site de nișă, structură necunoscută exact | Probabil scăzută-medie | Probabil medie — site modern, posibil parțial dinamic | **Ridicată** — SPA JS-heavy, protecție Cloudflare cunoscută (confirmat via WebSearch: „Cloudflare... blochează orice bot necunoscut") |
| **Necesită HTTP sau Playwright** | HTTP Scraper (Tier 1) — probabil | HTTP Scraper (Tier 1) — probabil, neconfirmat | HTTP Scraper (Tier 1) — probabil, neconfirmat | Incert — posibil HTTP, posibil necesită randare parțială | **Playwright (Tier 2)** — aproape sigur, dat fiind SPA + anti-bot |
| **Stabilitatea structurii HTML** | Probabil ridicată — design vechi, schimbat rar (inferență din vechimea/simplitatea site-ului, nu măsurată) | Necunoscută | Necunoscută | Necunoscută | Scăzută — SPA modern, actualizat frecvent, structură volatilă (cunoaștere generală) |
| **Riscul de blocare** | Scăzut-mediu (site simplu, dar tot neverificat dacă are protecție anti-bot) | Necunoscut | Necunoscut | Necunoscut | **Ridicat** — Cloudflare + fingerprinting comportamental confirmat |
| **Scor final (calitativ, NU o aprobare)** | **Cel mai promițător candidat pentru un POC Tier 1** — acoperire confirmată a exact statisticilor căutate (cornere/faulturi/cartonașe), complexitate tehnică probabil scăzută | Candidat secundar — acoperă și Referee (al 2-lea gol documentat), dar mai puțin cunoscut structural | Candidat secundar — acoperire parțială neconfirmată pe fauluri/cartonașe | Neclar — API-ul plătit ar putea fi opțiunea mai bună decât scraping-ul site-ului | **Nerecomandat pentru Faza 1** — potrivit conceptual pentru Faza 4 (Playwright), nu pentru pilotul HTTP Scraper de acum |

---

## Concluzie, per cerința explicită a documentului

Acest tabel **nu selectează o sursă** — rămâne, per decizia ta, o comparație
informativă. Pilotul Fazei 1 (`SCRAPER_ADAPTER`, `Validation Layer`, Shadow
Mode) se construiește independent de orice sursă anume, contra unui
fixture HTML static, exact cum ai cerut (§3).

Dacă/când alegi o sursă pentru `POC_SCRAPER_SOURCE_01` (§4, pas separat,
după pilot): `worldfootball.net` e candidatul cu cele mai multe confirmări
directe (acoperire Romania Liga 1 + cornere/faulturi/cartonașe, toate
confirmate via WebSearch) și cu cel mai probabil profil tehnic simplu
(HTTP Scraper, nu Playwright) — dar rămâne o recomandare informativă, nu o
aprobare; `robots.txt`/ToS-ul lui rămân la fel de neverificate ca ale
celorlalte, exact cum precizează planul tău.

## Surse citate (WebSearch, 2026-07-28)

- [Corners stats Liga I Romania — fctables.com](https://www.fctables.com/romania/liga-i/corners/)
- [Liga I Corners Statistics — WinDrawWin.com](https://www.windrawwin.com/statistics/corners/romania-liga-i/)
- [Liga I Romania stats — Corner-stats.com](https://corner-stats.com/liga-i/romania/tournament/27)
- [Romania Liga I 2026/27 Stats — FootyStats](https://footystats.org/romania/liga-i)
- [Liga 1: Table, Fixtures & Top Scorers — worldfootball.net](https://www.worldfootball.net/competition/co66/romania-liga-1/)
- [Bundesliga » Statistics — worldfootball.net](https://www.worldfootball.net/competition/co12/germany-bundesliga/statistics-overview/)
- [World Cup 2026 » Team-Statistics: Fouls committed — worldfootball.net](https://www.worldfootball.net/competition/co139/fifa-world-cup/team-statistics-fouls-committed/)
- [FootyStats API — Football Stats JSON API](https://footystats.org/api)
- [Terms and Conditions — FootyStats](https://footystats.org/terms-and-conditions)
- [How to Bypass Cloudflare Bot Protection — gologin.com](https://gologin.com/blog/web-scraping-service-cloudflare-bypass/)
