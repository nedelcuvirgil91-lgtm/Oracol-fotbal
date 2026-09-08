# Team Profile — Eficiență finalizare + volum faze fixe

**Status**: implementat, ADITIV, izolat de Oracle/ML/Blend — **NEPROMOVAT încă**.
Nicio predicție, nicio pondere, niciun feature ML nu depinde azi de acest
modul. Testul de ablație care ar decide o eventuală promovare nu a fost
încă rulat (necesită pragul de mai jos atins + aprobare separată,
proprietarul produsului — regula „niciun backtest favorabil nu e, singur,
suficient" din CLAUDE.md, secțiunea Filosofia proiectului).

**Cod**: `flashscore_team_dna.py` (`rolling_finishing_and_setpieces()`,
`rolling_advanced_stats()`, `build_team_dna()`) · `database/queries.py`
(`get_team_recent_advanced_stats`, `_recent_match_side_map`,
`get_team_recent_statistics_extended`, `get_team_recent_player_ratings`,
`get_finishing_data_readiness`, `TEAM_PROFILE_TEST_THRESHOLD`,
`TEAM_PROFILE_EXCLUDED_LEAGUES`) · `oracle_engine.py`
(`_build_flashscore_dna`, `_current_season_start_date`) · `app.py`
(panourile „⚽ Eficiență finalizare", „💪 Profil fizic/dueluri", „🎯 Profil
de construcție", bara de progres „🧪 Profil de echipă").

## Ce calculează

Pentru fiecare echipă, pe meciurile TERMINATE ale sezonului curent
(kickoff_date >= 1 iulie, convenția deja folosită de `oracle_api.
_tsdb_season_string()`):

- `goals_per_xg` — goluri reale / xG real, pe SUME aliniate per meci (nu
  media rapoartelor — evită divizarea la 0 și amestecarea golurilor unui
  meci cu xG-ul altuia dacă unul din cele două lipsește).
- `goals_per_shot_on_target` — aceeași metodă, pe șuturi pe poartă.
- `avg_corners` — volum, fără conversie (eficiența la faze fixe nu e
  calculabilă azi — `match_events.detail` nu conține tipul de asistență).
- Profil fizic/dueluri, profil de construcție a jocului — din
  `match_statistics_extended` (EAV), aceleași meciuri.

## Istoricul deciziilor de prag (cronologic, toate ale proprietarului produsului)

1. **Propunere inițială respinsă**: prag pe tot istoricul (precedentul
   5.253 meciuri, ADR-012/013/021) — respins explicit, 2026-08-15:
   „loturile se schimbă între sezoane, acest prag nu poate fi atins anul
   asta" — contradicție reală, prinsă de proprietarul produsului, nu de
   Claude.
2. **400, sezon curent, agregat pe toate ligile** — decis 2026-08-15,
   simetric cu `MIN_MATCHES_FOR_EVALUATION=200` al Challenger-ului ML
   (dublu, pentru că fiecare meci contribuie o singură observație per
   echipă vs. Challenger-ul care evaluează pe meci, nu pe echipă). Bară
   vizuală identică cu bara Challenger-ului ML din Setări Model.
3. **Pragul 400 atins, 2026-08-18** — înainte de a rula testul de
   ablație, proprietarul produsului a ridicat o îngrijorare: cele 3 cupe
   europene UEFA (Champions/Europa/Conference League) sunt ~42.5% din
   eșantion (170/400) și, în august, majoritar tururi de calificare cu
   adversari nepotriviți ca forță.
4. **Verificare live (nu presupunere)** — interogare directă Supabase +
   verificare manuală pe Flashscore (screenshot-uri furnizate de
   proprietarul produsului, meciul Dinamo City (ALB) – Auda (LAT),
   Conference League, calificări): confirmat că Flashscore însuși NU
   publică rândul „Expected goals (xG)" pentru multe meciuri din aceste
   competiții — nu e o eroare de citire a noastră. Verificat și codul
   (`providers/flashscore/normalizer.py`, `STAT_LABEL_TO_FIELDS`):
   parserul citește orice etichetă găsește pe pagină, fără filtrare pe
   competiție — dacă eticheta lipsește din HTML, câmpul rămâne `NULL`,
   corect (Regula #8).

   Rezultat măsurat (pooled, home+away, sezon 2026-07-01+):

   | | meciuri | acoperire xG | goluri/xG | goluri/SOT |
   |---|---|---|---|---|
   | Toate ligile domestice urmărite | 460 obs | 99-100% | 0.958 | 0.322 |
   | Champions/Europa/Conference League | 340 obs | ~33.5% (CL: 30%) | 1.005 | 0.311 |
   | World Cup 2026 | 4 obs | 0% | — | — |

   Rata de finalizare în sine NU diferă mult (~4-5%, plauzibil zgomot) —
   problema reală e acoperirea de date, nu o distorsiune a formulei.
5. **Decizie finală, 2026-08-18**: `TEAM_PROFILE_EXCLUDED_LEAGUES =
   ("Champions League", "Europa League", "Conference League",
   "World Cup 2026")` — World Cup 2026 inclus deliberat (2 meciuri, dar
   același profil: turneu, adversari nepotriviți, 0% acoperire xG).
   Prag redus **400 → 300**, acum strict pe ligile domestice. Verificat
   live la momentul deciziei: 228/300 meciuri domestice, ritm de
   acumulare ~50-70/săptămână (ligile domestice tocmai și-au început
   sezonul) → prag estimat atins în ~1-1.5 săptămâni.

## Excluderea e aplicată CONSECVENT, nu doar la bară

Decizie explicită: dacă am fi exclus cupele europene doar din
`get_finishing_data_readiness()` (contorul pragului), dar formula reală
(`get_team_recent_advanced_stats`/`_recent_match_side_map`, care
alimentează panourile afișate ȘI orice promovare viitoare) ar fi rămas
calculată pe toate competițiile per echipă — am fi validat pe o
populație curată dar am fi afișat/promovat una diferită, contaminată.
Excluderea e deci aplicată identic în ambele locuri.

## Ce NU s-a schimbat

- Formula (`rolling_finishing_and_setpieces`, `_sum_ratio`) — neatinsă.
- `FEATURE_COLUMNS` (ML) — neatins.
- Nicio scriere în Supabase — doar filtre de citire (`SELECT ... WHERE
  league NOT IN (...)`).
- Istoricul „global per echipă, fără filtru de ligă" (fix 2026-08-10,
  care combină corect campionat + cupă pentru ELO/formă) — rămâne
  valabil pentru restul competițiilor; doar cele 4 din
  `TEAM_PROFILE_EXCLUDED_LEAGUES` sunt scoase, țintit.

## Tooling de verificare

`scripts/team_profile_ablation_probe.py` — read-only, nu e importat de
niciun cod de producție, compară formula cu/fără competițiile excluse
(folosește `TEAM_PROFILE_EXCLUDED_LEAGUES` direct din `database.queries`,
nu o copie locală — evită divergența). Necesită `SUPABASE_URL`/
`SUPABASE_SECRET_KEY` în mediu (nu rulează în orice sandbox).

6. **Poarta corectată — ADR-062, 2026-08-23**: pragul 300 rămâne, dar
   numără acum altceva. Verificat live înainte de a începe ablația:
   numărătoarea veche ajunsese la 298/300 (deschidere în ore), dar dintre
   cele 298 de meciuri doar **15 (5,0%)** aveau ambele echipe cu ≥5 meciuri
   anterioare cu xG — fereastra reală a formulei. Numărătoarea veche
   măsura meciurile jucate în sezon; ablația walk-forward are nevoie de
   meciuri cu istoric suficient **per ambele echipe**, o cantitate diferită.
   Poarta urmărește acum `evaluable_matches` (vezi
   `database.queries.count_matches_with_sufficient_history`), cu cifra
   veche păstrată ca context. Detalii complete, inclusiv măsurătorile de
   stabilitate și analiza 3-vs-5, în
   `docs/00_GOVERNANCE/ADR-062-team-profile-readiness-gate-correction.md`.

## Ce știm despre zgomotul metricii (măsurat 2026-08-23, nu presupus)

Corelație split-half pe datele curente: `goals_per_xg` ≈ **−0,10** (două
metode independente, 32 respectiv 61 de echipe). DAR și martorii presupuși
stabili ies ≈ 0 (xG mediu 0,076, cornere 0,054, șuturi pe poartă −0,056) —
deci măsurătoarea **nu distinge** „metrica e zgomot" de „eșantion prea mic".
Istoric mai adânc nu există (xG real începe 2026-05-02, 531 rânduri, maxim
7 meciuri/echipă), deci nu se poate măsura mai bine azi.

Ce se poate afirma riguros: eroarea relativă a raportului scade cu
√(xG acumulat) — **±46% la 3 meciuri, ±36% la 5, ±20% abia la ~16**.
Dispersia observată între echipe (0,413) e integral explicată de zgomotul
de eșantionare.

Varianta de a reduce fereastra 5→3 (ar fi dat 68 meciuri evaluabile în loc
de 15, ≈2,7× mai multă putere netă) a fost evaluată explicit și **respinsă
de proprietarul produsului, 2026-08-23** — se rămâne la 5, planul inițial.

## Pasul următor (neînceput, în așteptarea pragului + aprobării)

Testul de ablație propriu-zis: măsoară dacă adăugarea acestor semnale ca
feature-uri ML (sau ca ajustare Oracle) îmbunătățește predicțiile
măsurabil — nu doar dacă formula „arată bine" pe eșantionul curent. Va
fi propus separat, cu aprobare separată, când pragul de 300 **meciuri
evaluabile** e atins (ADR-062).

**La atingerea pragului NU se întâmplă nimic automat** — singurul efect e
că textul barei din UI trece din `insufficient_data` în „prag atins — test
de ablație în așteptare" (`app.py`). E o etichetă, nu un declanșator.
Feature-ul rămâne NEPROMOVAT până când ablația îl justifică.

### Estimarea de timp — CORECTATĂ 2026-09-08, cu ritm măsurat

> **Estimarea inițială (2026-08-23) era: „~5-6 săptămâni (finalul lui
> septembrie)". E prea optimistă — realist e mijlocul spre finalul lui
> OCTOMBRIE.** Nu era greșită ca metodă: a fost făcută când contorul era la
> **15**, imediat după redefinirea lui prin ADR-062, deci fără nicio
> observație despre ritmul real. Acum există patru săptămâni de măsurători.

Ritmul real de acumulare a meciurilor evaluabile (măsurat live 2026-09-08;
replicarea în SQL a `count_matches_with_sufficient_history` întoarce exact
**82**, aceeași cifră ca UI-ul — deci metoda de proiecție e validată contra
funcției de producție, nu presupusă):

| Săptămâna | Evaluabile noi | Meciuri terminate | Cumulat |
|---|---:|---:|---:|
| S29–S33 (20 iul – 23 aug) | **0** | 221 | 0 |
| S34 (24–30 aug) | 20 | 117 | 20 |
| S35 (31 aug – 6 sep) | 27 | 128 | 47 |
| S36 | 31 | 139 | 78 |
| S37 (parțială) | 4 | 11 | **82** |

Două lucruri se citesc de-aici, și amândouă explică de ce estimarea din
august nu putea fi corectă:

1. **Primele cinci săptămâni au dat ZERO**, deși s-au jucat 221 de meciuri
   — nicio echipă nu avea încă 5 meciuri anterioare cu xG real. Acumularea
   nu începe odată cu sezonul, ci după ce echipele traversează fereastra.
   O estimare liniară făcută la contor=15 extrapola dintr-un punct aflat
   chiar la începutul pantei.
2. **Ritmul accelerează**: 20 → 27 → 31 pe săptămână, iar proporția
   meciurilor terminate care devin evaluabile crește (17% → 21% → 22%).

**Proiecție**: mai sunt 218 de acumulat. La 31/săptămână, chiar cu
accelerarea, ies **5-7 săptămâni → mijlocul spre finalul lui octombrie**.
Pentru finalul lui septembrie (3 săptămâni) ar fi nevoie de ~73/săptămână,
mai mult decât dublu față de ritmul măsurat.

**De ce e notată corectura, nu doar înlocuită cifra**: estimarea veche
circula deja ca „e pentru finalul lui septembrie", iar la momentul acela
întrebarea „de ce nu s-a atins pragul?" ar fi părut un defect, nu o
estimare depășită. Ritmul de mai sus e verificabil oricând cu aceeași
interogare.

### Precondiție deja rezolvată (2026-08-23)

`get_team_recent_advanced_stats()`/`_recent_match_side_map()` au primit
parametrul opțional `as_of_date` — limită SUPERIOARĂ STRICTĂ
(`kickoff_date <`), fără de care o ablație walk-forward ar fi dat unui meci
din septembrie, în propriul istoric „recent", meciuri din decembrie
(scurgere temporală reală, interzisă de `CLAUDE.md`). Servirea live nu îl
folosește — acolo „recent" chiar înseamnă „față de acum".
