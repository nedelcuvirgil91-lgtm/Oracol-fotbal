# KNOWLEDGE_ENGINE_SOURCES_AUDIT_2026-07-13.md — Football Oracle

**Status**: Audit de cercetare — zero cod scris, zero implementare, zero migrare. Cerut explicit ca livrabil separat de rollout-ul Odds Infrastructure, în paralel, fără să-l blocheze. Fiecare afirmație de mai jos a fost verificată prin căutare web directă (iulie 2026), nu doar din cunoștințe de antrenament — orice element neverificabil e marcat explicit ca atare, conform disciplinei „verificat, nu presupus".

**Scop**: surse gratuite pentru xG, xA, Shots/Shots on Target, Cornere, Cartonașe, Posesie, Faulturi, Big Chances, Pass Accuracy, Goalkeeper Saves, PPDA — pentru cele 11 competiții urmărite (Premier League, Championship, La Liga, Serie A, Bundesliga, Ligue 1, Romania SuperLiga, Champions League, Europa League, Conference League, World Cup).

---

## 1. Sursele gratuite disponibile

### Understat.com
xG, xGA, xPts, hartă de șuturi (x/y + xG per șut), PPDA per echipă, deep completions. **Nu are** posesie%, faulturi, cartonașe, șuturi pe poartă ca număr brut, big chances.
**Acoperire**: doar 6 ligi (Premier League, La Liga, Ligue 1, Serie A, Bundesliga, Rusia), din 2014/15. Zero Championship, zero Romania SuperLiga, zero Champions/Europa/Conference League, zero World Cup.
**Acces**: fără API oficial — JSON extras din `<script>` tags în HTML, singura cale fiind scraping neoficial (`understatapi`, Apify, `worldfootballR`). **Nu s-a găsit niciun Terms of Service public care să adreseze explicit accesul automatizat** — zonă gri legală reală, nu „liber de facto".
**Prospețime**: aproape live pe site; dump-urile Kaggle sunt statice, defazate.
**Fiabilitate**: considerat cel mai de încredere xG gratuit de comunitate, dar modelul xG e proprietar/nedocumentat — nereproductibil independent.

### FBref / Sports-Reference (Stathead)
**Descoperire critică, foarte recentă**: partenerul de date avansate al FBref (Opta/Stats Perform) **a întrerupt fluxul de date în ianuarie 2026** și a cerut ștergerea datelor subiacente. FBref s-a conformat. **Azi, xG/xA/progressive passes/shot-creating actions sunt indisponibile pe FBref, indiferent de ligă.**
**Acoperire (statistici de bază, dacă rămân)**: anterior Premier League, Championship, La Liga, Serie A, Bundesliga, Ligue 1, Champions League, Europa League — dar exact stratul avansat de care are nevoie proiectul (xG/xA) e azi indisponibil.
**Acces**: doar scraping HTML, rate-limiting agresiv (429), termenii de utilizare împing spre abonamentul plătit Stathead.
**Verdict**: **inutilizabil azi pentru xG** — situație vie, nu stabilă; de reverificat periodic, nu de construit pe el acum.

### StatsBomb Open Data (GitHub `statsbomb/open-data`)
**Oferă**: date complete la nivel de eveniment (fiecare pasă, șut cu xG, presiune, cărat de minge, duel) — din care se pot *deriva* șuturi, xG, posesie%, PPDA (nu preagregat, dar calculabil).
**Acoperire**: gratuit dar fragmentat — World Cup (mai multe ediții), Euro/Women's Euro, Copa América, AFCON, Champions League (doar sezoane selectate, ex. 2003/04, 2017/18, 2018/19 + unele finale), FA WSL, NWSL, Liga F, ISL, MLS, meciurile lui Messi la Barcelona (subset La Liga, nu sezoane complete). **Zero sezoane complete Premier League/Bundesliga/Serie A/Ligue 1, zero Championship, zero Romania SuperLiga.** Confirmat direct din `competitions.json` al repo-ului.
**Acces**: JSON versionat, curat, într-un repo GitHub public (`statsbombpy`) — singura sursă din listă cu acces demonstrabil curat, nu scraping.
**Licență**: cere atribuire; termenii compleți sunt într-un `LICENSE.pdf` **care nu a putut fi extras ca text în această cercetare** — granița comercial/necomercial exactă rămâne neconfirmată și trebuie citită direct înainte de orice folosire.
**Prospețime**: dump-uri statice, actualizate neregulat.
**Cea mai bună utilizare**: analiză World Cup/turnee europene, nu cele 11 competiții urmărite ca ansamblu.

### API-Football (api-football.com / RapidAPI, API-Sports)
**Oferă**: endpoint documentat de statistici per meci — Shots on/off Goal, Shots Inside/Outside Box, Total Shots, Fouls, Corner Kicks, Offsides, Ball Possession, Yellow/Red Cards, **Goalkeeper Saves**, Total Passes, Passes Accurate, Pass % — acoperă majoritatea categoriilor cerute printr-un singur API REST curat. **xG NU e câmp standard garantat** — descris ca „inconsistent" în funcție de ligă/sezon/plan. **Big Chances și xA nu apar deloc în lista de câmpuri documentată.**
**Acoperire**: revendică 1.200+ competiții; teoretic acoperă Romania SuperLiga, Championship, Conference League — dar **completitudinea reală a endpoint-ului de statistici pentru competiții de profil mai mic nu a putut fi verificată independent, necesită test direct cu cheie API live.**
**Acces**: API REST oficial, documentat — singura sursă din listă cu acces fără ambiguitate ToS.
**Prospețime**: live (~15s în timpul meciului).
**Limite gratuite**: 100 request/zi (~10/min) — suficient pentru **sincronizare zilnică incrementală înainte**, dar **impractic pentru backfill istoric** (mii de meciuri × 1 request ar dura ani pe planul gratuit).
**Cost peste gratuit**: plan Pro de la 19 USD/lună pentru 7.500 request/zi.

### WhoScored — **ToS interzice explicit**
Termenii de utilizare interzic explicit copierea/reproducerea/republicarea conținutului fără licență oficială și **numesc explicit platformele de pariuri** ca necesitând licență pentru a folosi datele/ratingurile WhoScored. Acest proiect e exact asta. **Nerecomandat.**

### SofaScore — **ToS interzice explicit**
Cea mai largă acoperire găsită (confirmă Romania SuperLiga, Conference League), dar termenii interzic explicit „data mining, roboți sau metode similare de extragere" și uzul comercial fără licență; suportul propriu declară că nu pot oferi API „din cauza acordurilor cu furnizorii de date". **Nerecomandat pentru ingestie automatizată.**

### FotMob — **ToS interzice explicit**
xG, xA, big chances, posesie, pass accuracy pentru ligile majore (derivate Opta). Termenii interzic explicit „acces neautorizat, scraping sau afectarea performanței sistemului". **Nerecomandat.**

### football-data.co.uk (sursa deja parțial integrată prin oglinda GitHub folosită pentru cote)
**Descoperire directă, relevantă imediat**: oglinda deja folosită de proiect pentru istoricul de cote (`xgabora/Club-Football-Match-Data-2000-2025`) **conține deja coloane `HomeShots/AwayShots`, `HomeTarget/AwayTarget`, `HomeCorners/AwayCorners`, `HomeFouls/AwayFouls`, `HomeYellow/AwayYellow`, `HomeRed/AwayRed`** — confirmat direct din repo. Șuturi/șuturi pe poartă/cornere/faulturi/cartonașe ar putea fi deja prezente, nefolosite, în date pe care pipeline-ul le descarcă deja pentru cote.
**Acoperire**: mirror-ul acoperă „27 țări, 42 ligi"; **nu s-a putut confirma dacă Romania are aceste coloane populate** (spre deosebire de cote, care sunt confirmate) — necesită inspecție directă a rândurilor CSV pentru Romania, nu presupunere. Confirmat istoric pentru Anglia (toate diviziile), Spania, Italia, Germania, Franța (primele 2 divizii). **Zero acoperire Champions/Europa/Conference League/World Cup** — sursă strict de ligi domestice.
**Acces/ToS**: relație deja existentă și presupusă acceptabilă (deja folosită pentru cote) — zero expunere legală nouă.
**Prospețime**: CSV pe sezon, nu live.

### Dataset-uri Kaggle (scraping-uri Understat, conversii StatsBomb etc.)
Utile pentru experimente punctuale de backfill/modelare, nu pentru sincronizare continuă (prospețimea depinde de ultima actualizare a autorului). Moștenesc aceleași limite de acoperire și aceeași zonă gri legală ca sursa originală.

### Wyscout (Hudl) / Opta (Stats Perform)
Comerciale, enterprise. Wyscout „Personal" ~299-325 EUR/an (orientat spre scouting video, nu acces API în masă); API complet — preț la cerere. Opta — fără preț public deloc, doar la cerere. **Nu „suficient pe nivel gratuit"** pentru acest proiect — potențial mii de USD/an. Doar de urmărit dacă economia proiectului se schimbă.

### PPDA — caz special
Nu există un dataset gratuit dedicat, curat, de prim rang. PPDA se **derivă** normal din date poziționale la nivel de eveniment, deci accesibil gratuit doar din **numerele PPDA afișate de Understat** (limitat la cele 6 ligi) sau **derivabil din fluxurile de evenimente StatsBomb Open Data** (limitat la setul fragmentat de mai sus). Sursele de tip box-score (football-data.co.uk, endpoint-ul de statistici API-Football) **nu** au PPDA sau datele poziționale necesare pentru a-l calcula.

---

## 2. Calitatea datelor

- **Dezacord de model xG**: Understat, Opta (FBref/FotMob/WhoScored/SofaScore) și StatsBomb folosesc modele xG proprietare diferite — același șut poate primi valori xG diferite între furnizori. Nu există un „adevăr universal" xG. Amestecarea xG din surse diferite (ex. Understat istoric + un viitor API-Football) ar introduce o discontinuitate care arată ca semnal real, dar e artefact de schimbare de sursă — relevant direct pentru disciplina „verificat, nu presupus" a proiectului: un test de ablație pe un feature xG mixat ar putea arăta „îmbunătățire"/„degradare" falsă, doar din schimbarea sursei.
- **Fragilitate scraping**: Understat, FBref, WhoScored, SofaScore, FotMob nu au API oficial; toate wrapper-ele neoficiale găsite sunt întreținute de hobbyiști, cunoscute că se strică la orice redesign de site — risc operațional, nu doar legal.
- **Pierderea fluxului Opta de la FBref (ianuarie 2026)** e ea însăși un eveniment de calitate a datelor: orice scraping istoric dinainte de ianuarie 2026 reflectă modelul Opta; nimic nou nu mai vine de acolo, deci nu poate fi extins înainte chiar dacă s-ar construi un scraper.
- **football-data.co.uk / Club Football Match Data**: sursă cu istoric lung de încredere pentru statistici de bază (aceeași bază de încredere pe care proiectul se bazează deja pentru cote); consistența înregistrării datelor pentru sezoanele mai vechi (anii 2000) e mai slabă decât post-2010.
- **StatsBomb**: date de eveniment de cea mai înaltă fidelitate gratuită (adnotate manual), dar golurile de acoperire îl exclud ca sursă primară pentru cele 11 competiții urmărite — doar supliment pentru turneele acoperite.

---

## 3. Acoperirea competițiilor

| Competiție | Understat | FBref (post-ian-2026) | StatsBomb Open Data | API-Football (gratuit) | football-data.co.uk / Club-Football mirror | WhoScored/SofaScore/FotMob |
|---|---|---|---|---|---|---|
| Premier League | Da (doar xG) | Doar stats de bază, fără xG | Nu | Da (nominal) | Da (complet) | Da — blocat de ToS |
| Championship | Nu | Neconfirmat | Nu | Da (nominal) | Da (complet) | Da — blocat de ToS |
| La Liga | Da (doar xG) | Doar stats de bază | Parțial (doar meciurile lui Messi la Barça) | Da (nominal) | Da (complet) | Da — blocat de ToS |
| Serie A | Da (doar xG) | Doar stats de bază | Nu | Da (nominal) | Da (complet) | Da — blocat de ToS |
| Bundesliga | Da (doar xG) | Doar stats de bază | Nu | Da (nominal) | Da (complet) | Da — blocat de ToS |
| Ligue 1 | Da (doar xG) | Doar stats de bază | Nu | Da (nominal) | Da (complet) | Da — blocat de ToS |
| Romania SuperLiga | Nu | Nu | Nu | Da (nominal, neverificat) | **Neverificat** (cote prezente; coloane shots/cards neconfirmate) | Da (confirmat pe SofaScore) — blocat de ToS |
| Champions League | Nu | Doar stats de bază, fără xG | Parțial (sezoane selectate) | Da (nominal) | Nu | Probabil — blocat de ToS |
| Europa League | Nu | Doar stats de bază, fără xG | Neconfirmat | Da (nominal) | Nu | Probabil — blocat de ToS |
| Conference League | Nu | Nu | Nu | Da (nominal, neverificat) | Nu | Probabil — blocat de ToS |
| World Cup | Nu | Neconfirmat | Da (mai multe ediții, nivel de eveniment) | Da (nominal) | Nu | Da — blocat de ToS |

„Da (nominal)" = revendicat în documentația furnizorului, dar completitudinea reală a câmpurilor pentru acea competiție nu a fost verificată independent — necesită test direct.

---

## 4. Recomandarea de integrare

**Faza 1 — zero risc legal nou, infrastructură aproape zero (de făcut prima).** Inspectare directă a coloanelor deja prezente în `Club-Football-Match-Data-2000-2025` (mirror-ul deja folosit pentru cote): `HomeShots/AwayShots`, `HomeTarget/AwayTarget`, `HomeCorners/AwayCorners`, `HomeFouls/AwayFouls`, `HomeYellow/AwayYellow`, `HomeRed/AwayRed`. Ar putea fi deja populate pentru cele 5 ligi majore + diviziile inferioare engleze, ceea ce ar însemna că `shots`, `shots_on_target`, `corners`, `fouls`, `cards` din `match_history` (coloane existente, azi 100% NULL pentru șuturi) ar putea fi umplute din date pe care pipeline-ul le are deja pe disc — zero sursă nouă, zero expunere ToS nouă, zero problemă de rate-limit la backfill. Nu acoperă Champions/Europa/Conference League/World Cup; acoperirea pentru Romania la aceste coloane specifice rămâne neconfirmată.

**Faza 2 — sincronizare incrementală înainte, prin API-Football (nivel gratuit).** API REST curat, ToS clar, pentru șuturi, cornere, cartonașe, posesie, faulturi, GK saves — pentru meciuri viitoare (nu backfill istoric — 100 req/zi face backfill-ul impractic fără upgrade la planul Pro, 19 USD/lună). Înainte de a te baza pe el: test direct dacă endpoint-ul de statistici întoarce date complete pentru Romania SuperLiga și Conference League, și dacă `xg` există pentru oricare din cele 11 competiții — ambele sunt azi afirmații nedemonstrate din documentație, nu comportament confirmat.

**Faza 3 — xG/xA, doar pentru ligile unde există o cale legitimă, decizie separată de go/no-go.** Understat e singura sursă cu istoric stabil de xG de încredere pentru 5 din 11 competiții (nu Championship, nu Romania, nu vreo cupă europeană, nu World Cup) — dar nu are niciun Terms of Service public descoperit care să guverneze accesul automatizat, ceea ce e un semnal în sine: absența unui ToS public nu înseamnă permisiune, și ar trebui să primească o evaluare directă de risc/juridic (consistent cu disciplina ADR a proiectului) înainte de a construi infrastructură de scraping, nu tratată tacit ca „fără ToS = fără restricție". StatsBomb Open Data e o alternativă cu acces curat pentru analiză World Cup/Euro și sezoane parțiale Champions League, cu date reale la nivel de eveniment din care se poate deriva PPDA — dar termenii exacți de licență comercială nu au putut fi extrași din `LICENSE.pdf` în această cercetare și trebuie citiți direct înainte de folosire. FBref **nu e utilizabil azi** pentru xG, în urma întreruperii fluxului Opta din ianuarie 2026 — de reverificat periodic, nu țintă de construcție acum.

**Explicit nerecomandate**: WhoScored, SofaScore, FotMob — deși au cea mai largă acoperire brută (inclusiv Romania SuperLiga și Conference League confirmate pe SofaScore) și cel mai bogat set de câmpuri (big chances, xA, xG live). Toate trei au Termeni de Utilizare care interzic explicit scraping/data-mining și uz comercial fără licență, iar WhoScored numește explicit platformele de pariuri ca necesitând licență plătită — exact ce e acest proiect. Construirea de infrastructură de scraping împotriva oricăreia dintre acestea ar fi o încălcare directă, identificabilă a ToS, nu o zonă gri, și ar contrazice disciplina proprie a proiectului privind trasabilitatea și riscul.

**Gol onest de semnalat arhitectului**: nu există azi nicio sursă gratuită, curată din punct de vedere ToS, care să livreze fiabil Big Chances, xA sau PPDA pe toate cele 11 competiții urmărite — în special Romania SuperLiga și Conference League. A închide cu adevărat acest gol ar însemna fie (a) acceptarea riscului legal nerezolvat al scraping-ului pe surse de tip Understat/FBref/SofaScore, (b) păstrarea permanentă a stării „necunoscut" pentru acele combinații statistică/competiție (consistent cu filozofia ADR-001 de a nu aproxima starea necunoscută), fie (c) bugetarea unui contract plătit Opta/Wyscout — ordin de mărime de cost complet diferit, imposibil de precizat exact aici (ambele sunt doar „la cerere").

**Elemente care necesită test direct/evaluare juridică înainte de implementare, nu presupuse din această cercetare**:
1. Dacă mirror-ul `Club-Football-Match-Data-2000-2025` are coloanele de șuturi/cornere/cartonașe populate (non-NULL) pentru rândurile Romania SuperLiga.
2. Completitudinea reală a câmpurilor API-Football (mai ales `xg`) pentru Romania SuperLiga și Conference League — testat cu o cheie API live, nu din documentație.
3. Clauza exactă de uz comercial din `LICENSE.pdf` al StatsBomb Open Data (nu a putut fi extrasă ca text în această trecere).
4. Termenii scriși (dacă există) ai Understat pentru acces automatizat — niciunul găsit public, ceea ce necesită o decizie deliberată de risc, nu o presupunere tăcută de permisiune.

---

## Concluzie

**Zero implementare în acest document, conform cerinței explicite.** Recomandarea imediată, cu cel mai mic risc și cel mai mic efort, e Faza 1 (inspecție a coloanelor deja descărcate) — dar rămâne doar recomandare, nu acțiune, până la aprobare explicită.
