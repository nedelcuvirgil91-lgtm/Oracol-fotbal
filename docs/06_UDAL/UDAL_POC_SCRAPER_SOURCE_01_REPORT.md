# UDAL — POC_SCRAPER_SOURCE_01 — Raport (WorldFootball + SofaScore)

**Rulare reală, live**, prima din istoria UDAL — `scripts/_poc_scraper_source_01_temp.py`,
GitHub Actions run `30400824519` (`push`, branch `claude/sprint0-stabilizare-feedback-loop`,
succes la nivel de job — dar rezultatul FUNCȚIONAL e negativ, raportat
onest mai jos, nu ascuns). Dovadă: `docs/06_UDAL/poc_evidence/poc_scraper_source_01_result.json`
(comisă automat de workflow). Workflow-ul temporar a fost șters după
rulare (tipar stabilit); scriptul rămâne, ca artefact permanent, alături
de dovadă.

**Rezultat central, pe scurt**: **ambele surse au respins TOATE cererile
cu HTTP 403**, imediat — 1/1 pentru WorldFootball, 14/14 pentru SofaScore
(pe 14 date diferite, endpoint-uri diferite). Nicio pagină/răspuns n-a
fost obținut cu succes. **N-am încercat să ocolesc protecția anti-bot**
(fără spoofing de headere/fingerprint de browser, fără rotație de
identitate) — asta ar fi evaziune de detecție, nu validare de
arhitectură. Raportul reflectă exact ce s-a întâmplat.

---

## 1. Coverage

**0%.** Fetch-ul a eșuat la ambele surse, înainte de orice parsare —
`normalize()`/`validate()` nu au fost apelate deloc (nu există conținut
de parsat). Niciun câmp cerut (Match/Teams/Score/Referee/Attendance
pentru WorldFootball; Match/Teams/Score/Statistics/Lineups/Player
Statistics/xG pentru SofaScore) n-a putut fi extras din date reale.

## 2. Latency

Măsurată real, dar reprezintă **timp până la respingere**, nu până la
conținut util:

| Sursă | Apeluri | Latență (min–max) | Pattern |
|---|---|---|---|
| WorldFootball | 1 | 99,1 ms | Un singur punct de date — respingere rapidă, tipică unei blocări la marginea rețelei (edge/WAF), nu procesare de backend. |
| SofaScore | 14 | 44,5–212,0 ms (majoritatea ~45 ms, un outlier 212 ms la primul apel) | Foarte consistent — 13 din 14 apeluri sub 50ms, semnal puternic de respingere automată, sistematică, nu variație de procesare reală. |

## 3. Validation Rate

**N/A — 0 înregistrări procesate.** Fără conținut fetch-uit, Validation
Layer n-a avut ce evalua. Nu se poate raporta o rată calculată din zero
împărțit la zero fără să inducă în eroare — rămâne explicit „necunoscut",
nu aproximat (ADR-001).

## 4. Conflict Rate

**N/A**, din același motiv — `check_conflicts_with_match_history()` n-a
fost apelat, nimic de comparat cu `match_history`.

## 5. Comparație WorldFootball vs. SofaScore

| | WorldFootball | SofaScore |
|---|---|---|
| **Avantaje** | Tier 1 simplu (HTTP+CSS), fără nevoie de descoperire de endpoint — un singur URL de bază, cunoscut. | Extracție JSON e mai simplă odată obținut accesul (fără fragilitate CSS); acoperire de date mult mai bogată (confirmat conceptual, Faza 1.5). |
| **Dezavantaje** | Testat cu un SINGUR apel — dovadă mai slabă decât SofaScore (n=1 vs. n=14); rezultatul „blocat" e plauzibil dar mai puțin robust statistic. | API neoficială — fără contract public, structura poate schimba oricând; blocarea confirmată robust (14/14, pe 14 zile diferite — sistematică, nu accidentală). |
| **Cost** | Necunoscut încă — blocarea de azi nu permite nicio estimare de cost operațional real. | Idem. |
| **Mentenanță** | Presupusă scăzută (site vechi, stabil) — DAR ipoteza „ușor de întreținut" devine irelevantă dacă accesul de bază e blocat. | Presupusă mai mare (API neoficială, fără versionare) — aceeași observație. |
| **Stabilitate** | Necunoscută sub blocare — nu s-a putut testa nimic dincolo de primul request. | La fel. |
| **Complexitate** | Complexitatea REALĂ a crescut față de Faza 1.5: nu mai e „doar CSS selectors" — acum include (posibil) ocolirea unei blocări la nivel de infrastructură, o problemă calitativ diferită și mai grea. | Idem — complexitatea reală s-a dovedit mai mare decât complexitatea de extracție JSON estimată în Faza 1.5. |

**Observație onestă**: comparația de mai sus e parțial goală de conținut
— ambele surse au eșuat la primul obstacol (acces), înainte ca vreo
diferență de extracție să conteze practic. Diferența reală demonstrată
azi e doar în ROBUSTEȚEA DOVEZII de blocare (SofaScore: 14 puncte de
date; WorldFootball: 1).

## 6. Architecture Review

**Ce funcționează:**
- Pipeline-ul UDAL (Registry → Adaptor → `udal_extraction` → Validation →
  observabilitate) — verificat funcțional end-to-end pe date FIXTURE
  (Faza 1/1.5), rămâne intact, netestat de acest eșec (blocarea e la
  fetch, în afara pipeline-ului UDAL propriu-zis).
- Gate-urile de siguranță (`ScraperPreflightError`, `LiveFetchNotAllowedError`)
  au continuat să funcționeze corect — POC-ul a fost izolat, nu a trecut
  prin registry-ul de producție, exact cum era proiectat.
- Tiparul „POC izolat pe GitHub Actions, evidență comisă înapoi" a
  funcționat tehnic perfect — job-ul a rulat, a scris rezultatul, l-am
  putut citi. Infrastructura de investigare e solidă.

**Ce NU funcționează:**
- **Accesul de bază, de la runner-ul GitHub Actions, către ambele surse
  candidate „Primary"** — blocat complet, HTTP 403, fără excepție.
  Aceasta e o descoperire arhitecturală NOUĂ, nedocumentată în ADR-042
  §16 (problemele identificate acolo erau despre ToS/legal, nu despre
  blocare tehnică la nivel de IP/rețea).

**Ce trebuie îmbunătățit:**
- **Mediul de execuție pentru fetch real** — runner-ul standard GitHub
  Actions (IP-uri „datacenter" cunoscute, frecvent pe liste de blocare
  Cloudflare/WAF) s-ar putea să nu fie o platformă viabilă pentru Tier 1
  HTTP scraping împotriva surselor moderne, protejate. Alternative de
  luat în calcul (decizie a proprietarului produsului, nu a mea):
  runner self-hosted cu IP rezidențial/necunoscut ca „datacenter",
  servicii de proxy dedicate (cost + complexitate suplimentară,
  discutabil dacă merită), sau reevaluarea surselor „Primary" către
  altele mai permisive.
- **Un singur test pentru WorldFootball** — dovadă insuficientă pentru o
  concluzie fermă; ar merita un al doilea test izolat, separat, înainte
  de a-l elimina definitiv din „Primary".

## 7. Scalability Review

Întrebare: poate UDAL scala fără modificări majore pentru SuperLiga,
Premier League, La Liga, Serie A, Bundesliga, Ligue 1, Champions League,
Europa League, Conference League?

**Răspuns cu două niveluri, distincte, nu confundate:**

- **Modelul de date/cod — DA, fără modificări.** Verificat direct în
  Faza 1.5: extractorul (`udal_extraction.py`), adaptoarele
  (`generic_rich_match_scraper_adapter.py`) și schema de validare nu
  conțin nicio referință hardcodată la ligă — extinderea la oricare din
  cele 9 competiții cerute ar însemna DOAR o hartă de extracție nouă
  (URL template + selectori), zero cod.
- **Accesul real la sursă — NECONFIRMAT, posibil NU, per descoperirea
  de azi.** Dacă blocarea 403 e la nivel de IP (cel mai probabil,
  per pattern-ul observat), ea s-ar aplica IDENTIC pentru toate cele 9
  competiții — nu e o problemă per-ligă, e o problemă per-infrastructură.
  Asta înseamnă: scalarea la 9 competiții NU multiplică riscul (nu e „de
  9 ori mai greu"), dar NICI nu-l reduce — o singură rezolvare
  (schimbare de mediu de execuție sau de sursă) ar debloca toate cele 9
  deodată, la fel cum o blocare nerezolvată le-ar bloca pe toate deodată.

**Concluzie**: arhitectura UDAL e pregătită structural pentru scalare la
toate cele 9 competiții — dar afirmația depinde de o presupunere
netestată încă („sursa e accesibilă din mediul de execuție ales") care
s-a dovedit FALSĂ azi, pentru exact aceste 2 surse, din exact acest
mediu. Nu e o problemă de arhitectură UDAL — e o problemă de
infrastructură de acces, separată.

## 8. Recommendations pentru Faza 2

1. **Nu extinde încă la alte ligi/surse** — rezolvă întâi întrebarea de
   acces (blocare 403), altfel orice extindere moștenește aceeași
   problemă nedemonstrat-rezolvată.
2. **Decizie explicită a proprietarului produsului** despre cum se
   abordează blocarea: (a) accept costul/complexitatea unui mediu de
   execuție diferit (self-hosted runner, IP nedatacenter), (b) reevaluează
   sursele „Primary" către altele mai permisive (posibil unele din
   „Secondary"/Tier B testate mai puțin agresiv), sau (c) pune pauză pe
   scraping activ și rămâi pe API-uri existente + surse deja funcționale
   (Soccer Football Info, etc.) până la o resursă/decizie nouă.
3. **Un al doilea test, izolat, pentru WorldFootball specific** — un
   singur punct de date (403) nu e o dovadă la fel de robustă ca cele 14
   pentru SofaScore; merită o confirmare separată înainte de a-l elimina
   din „Primary".
4. **NU încerca ocolirea protecției anti-bot** — rămâne o linie clară,
   indiferent de presiune de livrare; dacă produsul decide să continue cu
   aceste surse, calea corectă e un parteneriat/acces autorizat explicit
   cu sursa, nu evaziune tehnică.
5. **Reconsideră clasificarea „Primary"** stabilită cu câteva ore în urmă
   (`UDAL_SOURCE_CLASSIFICATION.md`) — a fost făcută înainte de acest
   test empiric; azi arată că „Primary" teoretic (stabilitate/simplitate
   selectori) nu implică „Primary" practic (acces reușit). Rămâne decizia
   proprietarului produsului dacă/cum se ajustează.

---

## Fișiere

`scripts/_poc_scraper_source_01_temp.py` (păstrat, artefact permanent),
`docs/06_UDAL/poc_evidence/poc_scraper_source_01_result.json` (dovadă
reală). Workflow-ul temporar (`poc_scraper_source_01_temp.yml`) a fost
șters după rulare, per tiparul stabilit — evidența rămâne, nu depinde de
el.
