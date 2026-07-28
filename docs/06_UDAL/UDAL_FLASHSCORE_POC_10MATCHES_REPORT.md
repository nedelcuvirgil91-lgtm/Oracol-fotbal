# UDAL — Flashscore POC (Phase 0): 10 meciuri reale (5 SuperLiga + 5 UEFA Champions League)

**Status**: POC informativ, închis. Nu implementează adaptorul UDAL Flashscore.
**Dată**: 2026-07-28
**Cerut**: "Architecture Validation – Flashscore POC (Phase 0)"

## Metodologie

- Playwright Chromium **standard**, headless, fără patchright/stealth/proxy/fingerprint spoofing/TLS spoofing/bypass Cloudflare/CAPTCHA solver — profilul confirmat anterior în `gustavofariaa/FlashscoreScraping`.
- Rulat izolat pe GitHub Actions (singura cale cu acces real la internet în acest mediu de dezvoltare): `scripts/_poc_flashscore_10matches_temp.py` + workflow temporar (șters după rulare, evidența rămâne).
- Descoperire **reală** de meciuri: navigare pe hub-ul `/results/` al fiecărei competiții (SuperLiga: 43 link-uri de meci găsite; UCL: 75, din faza preliminară de calificare aflată în desfășurare) → primele 5 link-uri reale per competiție, fără URL-uri ghicite sau hardcodate.
- Pentru fiecare meci: navigare pe pagina de bază ("Match"/Summary) + click pe taburile vizibile text (Statistics/Lineups/H2H/Odds/Standings) + salvare HTML brut + screenshot per meci.
- Detectare protecție: HTTP 403/429/503 + fraze specifice de pagină de blocare reală ("verify you are human", "unusual traffic", "just a moment...", etc.). **Oprire imediată** configurată dacă apare.

### Corecție aplicată în timpul testului (transparent, nu evaziune)

Prima rulare s-a oprit după 1 meci cu "protecție detectată": string-ul `recaptcha/api` găsit în pagină la tab-ul Lineups. Verificare manuală (grep pe evidența brută): string-ul provine din `google.com/recaptcha/api2/aframe`, un iframe invizibil încărcat async de infrastructura anti-fraudă a Google Ads (`adtrafficquality.google/sodar`) — prezent identic pe hub-urile `/results/` (care trecuseră testul curat), fără nicio legătură cu Lineups sau cu vreun challenge real. Am strâns lista de markeri la fraze specifice de blocare reală și am rerulat o singură dată. A doua rulare a parcurs toate cele 10 meciuri fără nicio oprire.

## 1. Coverage (%)

- Competiții descoperite cu succes: **2/2 (100%)** — SuperLiga și UEFA Champions League, ambele via `/results/` direct (fără a fi nevoie de fallback pe `/fixtures/`).
- Meciuri reale identificate și testate: **10/10 (100%)** din ținta cerută (5 SuperLiga + 5 UCL).
- Meciuri reale, finalizate, cu scor final (nu programări): **10/10 (100%)**.

## 2. Success Rate

- Navigare inițială reușită (HTTP 200, conținut real): **10/10 (100%)**.
- Cel puțin un tab suplimentar (Lineups/H2H/Odds) navigat cu succes după Summary: **10/10 (100%)**.
- Nicio oprire din motive de protecție reală în rularea finală: **0/10**.

## 3. Average Latency

Timp de încărcare inițială (`domcontentloaded`, per meci, măsurat real):

| Meci | ms |
|---|---|
| SuperLiga 1 (FC Botoșani – Rapid) | 1156.7 |
| SuperLiga 2 (CFR Cluj – Voluntari) | 747.7 |
| SuperLiga 3 (M. Ciuc – FCSB) | 880.4 |
| SuperLiga 4 (Sepsi – U. Cluj) | 906.7 |
| SuperLiga 5 (Dinamo – Univ. Craiova) | 1107.7 |
| UCL 6 (Shamrock Rovers – Ararat-Armenia) | 706.7 |
| UCL 7 (Hearts – Sturm Graz) | 571.6 |
| UCL 8 (Celje – Egnatia) | 816.5 |
| UCL 9 (Dinamo Zagreb – Thun) | 564.7 |
| UCL 10 (Lincoln Red Imps – Mjallby) | 834.2 |

**Medie: ~829 ms** (min 564.7 ms, max 1156.7 ms) — rapid, consecvent, fără semne de rate-limiting progresiv.

## 4. Failure Rate

**0%.** Zero erori de navigare Playwright, zero HTTP 403/429/503, zero opriri din protecție în rularea finală, zero GDPR/CAPTCHA/Cloudflare semnalate pe niciunul din cele 10 meciuri.

## 5. Ce e accesibil (verificat direct pe evidența brută, nu doar presupus)

Verificare structurală (`data-testid` real în markup) + verificare de conținut (valori reale, nu doar etichete de traducere) pe un eșantion (SuperLiga meci 1 integral, UCL meci 6 pentru câmpurile sensibile la nivel de competiție) — structura HTML e identică (același template Flashscore) pe toate cele 10, deci concluziile generalizează:

| Categorie | Câmp | Status | Dovadă |
|---|---|---|---|
| **MATCH** | Match ID | ✅ | parametru `mid=` în URL, stabil |
| | Competiție | ✅ | breadcrumb + titlu pagină ("Superliga - Round 2") |
| | Sezon | ⚠️ | derivabil din context (hub-ul competiției), nu e un câmp direct pe pagina meciului |
| | Rundă | ✅ | text real găsit: "Round 2" |
| | Dată | ✅ | "27.07.2026" |
| | Ora meciului | ✅ | datetime complet real găsit: "27.07.2026 18:30" |
| | Echipa gazdă/oaspete | ✅ | nume reale, confirmate în titlu + breadcrumb |
| | Scor final | ✅ | real în titlul paginii (ex. "CFR 5-0 VOL") |
| **MATCH STATISTICS** | Posesie | ✅ | valori reale (58% / 42%), `data-testid="wcl-statistics-value"` |
| | Șuturi (total) | ✅ | valori reale (12 / 13) |
| | Șuturi pe poartă | ✅ | etichetă + structură confirmată identic |
| | Cornere | ✅ | valori reale (2 / 3) |
| | Faulturi | ✅ | valori reale (28 / 31) |
| | Cartonașe galbene/roșii | ✅ | structură identică confirmată |
| | Ofsaiduri | ✅ | structură identică confirmată |
| | Intervenții portar | ✅ | structură identică confirmată |
| **LINEUPS** | Starting XI | ✅ | nume reale + numere reale de tricou (ex. "Anestis" #99), poziționare pe teren (`wcl-participantPitch`) |
| | Rating jucători | ✅ | `wcl-badgeRating` cu valoare reală per jucător |
| | Substituții (evenimente) | ✅ | `wcl-lineupsParticipantsSubstitution-left/right` real |
| | Bancă (rezerve nefolosite, listă completă) | ⚠️ | eticheta de traducere există ("Substitutes"), dar niciun `data-testid` dedicat de listă statică găsit în eșantion — necesită verificare suplimentară (posibil necesită scroll/interacțiune diferită de click-text) |
| | Antrenor (nume) | ⚠️ | doar eticheta de traducere găsită ("Coach"/"Coaches"), niciun nume real de antrenor confirmat structural în eșantion |
| **PLAYER DATA** | Goluri/Assist-uri (evenimente) | ✅ | iconițe reale de eveniment (`wcl-icon-incidents-goal-soccer`) |
| | Cartonașe (per jucător) | ✅ | iconițe reale (`wcl-icon-incidents-yellow-card`/`red-card`) |
| | Minute jucate | ⚠️ | nu a fost verificat direct ca valoare explicită per jucător în eșantion |
| | Rating (dacă există) | ✅ | vezi Lineups → `wcl-badgeRating` |
| **EXTRA** | Arbitru | ✅ | nume real confirmat: "Barbu M. (Rou)" |
| | Stadion | ✅ | nume real confirmat: "Stadionul Municipal (Botoșani)" |
| | Spectatori (attendance) | ✅ | valoare reală confirmată: "6 113" |
| | Vreme | ❌ | niciun semn — Flashscore nu afișează date meteo pentru fotbal |
| | xG (Expected Goals) | ❌ | **corectare față de detecția automată inițială**: string-ul "xG" apărea doar în dicționarul de traduceri bundle-uit în JS (`TRANS_EXPECTED_GOALS`), NU ca widget real cu valoare pe pagina meciului — verificat pe SuperLiga #1 și UCL #6, niciun `data-testid` cu xG real găsit în niciunul din cele două |
| | H2H (istoric confruntări) | ⚠️ | tab-ul navighează cu succes (titlu real "Head-to-head matches" prezent), dar rândurile efective de meciuri istorice NU au fost confirmate structural în eșantionul verificat — posibil necesită timp de așteptare mai mare sau selector mai precis |
| | Cote (odds) | ✅ | valori reale de cotă găsite (ex. 2.80 / 3.10 / 2.30), mai mulți bookmakeri reali identificați (bet365, Unibet etc.) — nu sub selectorul presupus inițial, dar confirmate direct în conținutul brut |

**Notă de corectitudine**: tab-ul "Statistics" (etichetat real "Stats", nu "Statistics" — eroare de potrivire text exactă în scriptul POC) nu a fost vizitat separat ca pagină dedicată la niciunul din cele 10 meciuri. Nu contează ca gol real: valorile de statistici de meci erau deja prezente, reale și complete direct pe pagina "Match" (Summary), deci concluzia de extractibilitate (✅) e susținută independent de acest bug minor de etichetă.

## 6. Ce NU e accesibil (sau neconfirmat)

- **Vreme**: confirmat absent — Flashscore nu oferă acest câmp pentru fotbal.
- **xG per meci**: confirmat absent ca widget real (doar text de traducere generic bundle-uit, fals-pozitiv al detecției automate inițiale, corectat prin verificare manuală).
- **Lista completă a rezervelor nefolosite + numele antrenorului**: neconfirmate structural în eșantionul testat — necesită un test dedicat mai profund (timp de așteptare mai mare, selectori mai preciși) înainte de a le considera disponibile.
- **Rândurile reale de istoric H2H**: tab-ul se deschide, dar conținutul de rânduri (meciuri anterioare + scoruri) nu a fost confirmat — la fel, necesită investigație suplimentară dedicată.
- **Minute jucate per jucător** ca valoare explicită: neconfirmat direct (dar plauzibil disponibil, dat fiind că toate celelalte date per-jucător sunt prezente).

## 7. Ce se poate folosi pentru Football Oracle

- **Match Statistics complet** (posesie, șuturi, cornere, faulturi, cartonașe, ofsaiduri, intervenții) — date reale, structurate, cu `data-testid` stabile — acesta e exact tipul de date pe care Sprint 1 (Soccer Football Info) l-a introdus deja în `match_history`; Flashscore ar fi o a doua sursă independentă pentru cross-validare/completare de goluri (gap-uri).
- **Lineups + rating jucători + evenimente de substituție** — date reale, cu nume și numere de tricou.
- **Arbitru, stadion, spectatori** — câmpuri complet reale, utile pentru feature engineering (ex. impact arbitru, capacitate stadion vs. afluență).
- **Cote reale, multi-bookmaker** — relevant pentru value betting / de-vig, deși Football Oracle are deja Odds API ca sursă principală pentru cote; Flashscore ar fi redundant aici decât dacă Odds API are un gol de acoperire specific (ex. SuperLiga, unde Odds API e deja documentat ca "dead" pentru piețe per-meci — vezi golul cunoscut din CLAUDE.md).

## 8. Ce NU merită implementat (acum)

- **xG, vreme**: confirmat inexistente pe Flashscore — nu proiecta câmpuri pentru ele în adaptorul UDAL Flashscore.
- **H2H din Flashscore**: Oracle Engine are deja H2H Database-First (ADR-035 D3) din `match_history` — duplicarea prin Flashscore n-ar aduce valoare fără dovadă că rezolvă un gol real de acoperire.
- **Bancă completă + antrenor**: neconfirmate — nu le include în scope-ul unui viitor adaptor până nu sunt verificate separat, dedicat.

## 9. Complexitate estimată pentru un adaptor UDAL Flashscore (dacă s-ar construi vreodată)

- **Tier**: Playwright (Tier 2) — obligatoriu, site JS SPA fără API public, fără fallback HTTP simplu (WorldFootball/SofaScore au fost blocate; Flashscore răspunde doar la randare completă JS).
- **Discovery**: necesită navigare pe hub `/results/` per competiție + parsare link-uri reale (nu URL-uri fixe) — mecanism deja demonstrat funcțional în acest POC, reutilizabil ca bază.
- **Extracție**: markup bazat pe `data-testid` stabile (`wcl-*`) — un avantaj real față de scraping bazat pe clase CSS volatile (WorldFootball/SofaScore CSS clasic ar fi fost mult mai fragil). Totuși, navigarea pe taburi (Lineups/H2H/Odds) necesită click real + așteptare JS (nu simplă cerere HTTP), deci **fiecare meci = minim 4-6 navigări Playwright** (cost timp/resurse GitHub Actions non-trivial la scară — corelat cu riscul deja documentat în ADR-042 §16, "GitHub Actions resource ceiling").
- **Fragilitate selectori**: risc mediu — `data-testid`-urile par relativ stabile (convenție `wcl-*` consistentă pe tot site-ul), dar etichetele text vizibile (ca "Stats" vs. "Statistics" descoperit în acest test) pot varia și necesită mentenanță.
- **Politeness/rate**: neconfirmat la scară — 10 meciuri secvențiale, cu pauză de 2s între ele, n-au declanșat nicio protecție; comportamentul la sute/mii de meciuri (scenariul real de backfill istoric) e necunoscut și trebuie testat separat, gradual, dacă se decide continuarea.
- **Estimare**: complexitate **medie-mare** — nu trivială (multi-tab, JS SPA, discovery dinamic), dar semnificativ mai tratabilă decât WorldFootball/SofaScore (care au fost blocate complet, deci complexitate infinită/irelevantă).

## 10. Recomandare finală

**B. Flashscore poate fi doar sursă auxiliară.**

Motivare:
- Acces real, stabil, fără nicio protecție declanșată pe 10 meciuri reale din 2 competiții diferite (ligă internă + cupă europeană) — merită să rămână în discuție, spre deosebire de WorldFootball/SofaScore (blocate definitiv).
- Date de calitate reală și substanțiale (statistici complete, lineups cu rating, arbitru/stadion/spectatori, cote multi-bookmaker) — nu un site "gol".
- **Dar** nu calitate de "Provider Premium" (opțiunea A) încă: (1) nu există dovadă de stabilitate la scară (10 meciuri secvențiale ≠ sute/mii, ceea ce ar fi cazul real de backfill istoric pentru 9 competiții); (2) câteva câmpuri importante (H2H, bancă completă, antrenor) nu au fost confirmate ca extractibile în acest test — necesită o rundă dedicată de verificare înainte de orice angajament de arhitectură; (3) costul per-meci e mai mare decât o sursă API/HTTP simplu (multi-tab Playwright = mai multe navigări/meci), ceea ce contrazice principiul de ordine a achiziției din ADR-042 (API → HTTP → Playwright, Playwright fiind ultima opțiune, nu implicită); (4) niciun test de ToS/legalitate n-a fost făcut încă (`tos_reviewed` rămâne `False`, neschimbat de acest POC, conform regulii stabilite).
- Opțiunea C (nu merită integrat) ar fi nedreaptă față de dovezile concrete de acces stabil și date reale — Flashscore nu se comportă ca WorldFootball/SofaScore.

**Concluzie**: Flashscore rămâne un candidat legitim pentru rolul "Premium" din `UDAL_SOURCE_CLASSIFICATION.md`, dar nu e încă demonstrat ca atare. Înainte de orice implementare de adaptor: (a) test de stabilitate la scară mai mare (zeci de meciuri, nu 10), (b) verificare dedicată H2H/bancă/antrenor, (c) review explicit de ToS per regula stabilită pentru surse de scraping. Niciunul din acești pași nu a fost făcut aici — acest POC răspunde doar la întrebarea "merită să continuăm discuția?", și răspunsul e da, condiționat.

## Evidență

Toată evidența brută (JSON, HTML per meci/tab, screenshot-uri) e salvată în `docs/06_UDAL/poc_evidence/flashscore_10matches/`. Nu s-a scris nimic în Supabase, nu s-a atins `scraper_registry.py`/`tos_reviewed`, nu s-a implementat niciun adaptor UDAL.
