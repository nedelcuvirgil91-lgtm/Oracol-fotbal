# BACKLOG — singura listă

**Fără dată în nume, deliberat.** Fiecare „BACKLOG_2026-10-13", „PLAN_POST_…",
„STARE_…_SEARA" a fost scris ca să fie *cel actual* și a devenit în câteva zile
încă un loc în care să cauți. Documentul ăsta se **actualizează**, nu se
dublează. Dacă apare un al doilea backlog cu dată în nume, e un simptom.

**Ultima măsurare completă: 2026-10-20**, cu **§1.6bis, §1.8 și §1.9 remăsurate
pe 2026-10-21**. Totul de mai jos e verificat atunci, read-only, nu reluat din
memorie. Unde o cifră e veche, scrie cât e de veche.

**Cum se folosește**: §1 e ce te așteaptă pe TINE (se citește prima, e singurul
loc unde se pierd lucrurile). §2-§5 e munca, ordonată după valoare reală. §6 e
ce NU facem și de ce — ca să nu se redeschidă. §7 sunt documentele de detaliu;
ele rămân valabile ca dovadă, dar **ordinea de lucru e aici, nu acolo**.

---

## 1. ⚠️ DECIZII CARE TE AȘTEAPTĂ

Nimic din lista asta nu avansează fără tine. Ordinea e după cât costă amânarea.

| # | Ce | Stare | Costul amânării |
|---|---|---|---|
| **1.0** | 🔴 **`Sabah FC` vs `Sabah Baku`** — același club Flashscore (`fNGcxbyr`), două identități | **TERMEN FERM: înainte de 4 noiembrie** | **Singura intrare din listă cu dată de meci.** `Sabah Baku` are 9 meciuri și lanț ELO până la **1579**; `Sabah FC` are **1 rând, meciul VIITOR Viking – Sabah FC (UCL, 4 nov)**. `normalize_team_name('Sabah FC')` nu se rezolvă → la predicție ELO-ul real e **invizibil**, forma Level DB eșuează. Reparația e tiparul deja executat de două ori (D-13 Faza 1 și Clasa B): alias + backfill pe **1 rând**. Prins **prospectiv** de detectorul ADR-078, la prima lui declanșare. `DE_URMARIT.md` §13. |
| **1.0bis** | **ADR-081** — migrarea 058 (`provider_call_log.error_body`), apoi merge-ul `81006b0` | **luni 26 oct**, cod gata și testat pe branch | Deblochează **ADR-077** (1.3), oprit din 17 oct fiindcă motivul refuzului SFI nu putea fi citit. Ordinea e obligatorie: **migrare ÎNTÂI** — invers, scrierea în `provider_call_log` s-ar opri tăcut pentru toți providerii. `DE_URMARIT.md` §12. |
| **1.0ter** | 🔴 **`decision_feed` #13 — expirarea `xgboost_v1/dda4f7f3`** ȚINTEȘTE EXACT motorul din D-15 | `pending`, **TTL 2 noiembrie 08:28 UTC** | **Cuplaj nescris până pe 27 oct, găsit verificând starea deciziilor înainte de a programa urmărirea.** Aprobarea ei duce Challenger-ul în `REJECTED/expired`, iar Faza B antrenează un înlocuitor cu `training_run_id` NOU și **zero** rânduri în `challenger_evaluations` — deci **resetează la n=0 chiar măsurătoarea pe care declanșatorul D-15 o urmărește** (3/3 timp de 10 zile ȘI n ≥ 500). Două obiective care se bat: deblocarea antrenării familiei (ADR-057) contra păstrării artefactului pe care D-15 îl măsoară. Vezi §1.0ter. |
| **1.1** | **ADR-079** — ciclul de viață al unei decizii T3a (toate trei fețele din §2) | ✅ **ÎNCHIS 21 oct** — ACCEPTED (revizia 2), implementat, pe `main` (`e849088`) | **Cel mai mare risc deschis azi**: o aprobare de expirare se poate executa ca **promovare** de campion, fără ca nimeni să fi aprobat o promovare (§4.1 din ADR). Fereastra e de ordinul a 3 zile. |
| **1.1bis** | **`decision_feed` #8** — expirarea `blend_v1/174e7e17` | ✅ **ÎNCHIS 23 oct** — `withdrawn` de mecanismul ADR-079, exact cum s-a prezis | ⚠️ **Recomandarea mea de pe 20 oct dimineața era GREȘITĂ.** Ținta nu e înțepenită: 2 din 3 metrici semnificative, Δ acuratețe urcă monoton 0,98 → 2,33pp în 4 zile. Se rezolvă singură ~23 oct. `DE_URMARIT.md` §7. |
| **1.2** | **D-6 — două tabele de backup** | restante de **~30 de zile** peste termenul propriu | Mic, dar una (ADR-069, 72 kB) e singura tabelă din 62 **fără RLS**. Decizia e „se păstrează" / „se șterg"; dacă se păstrează, merită RLS. |
| **1.3** | **ADR-077** — criteriul de rutare SFI | propunere, recomandarea s-a **inversat** la măsurare | Zero cost acum (criteriul inert nu face rău). Dar ADR-ul stă deschis cu o recomandare greșită scrisă în el. |
| **1.4** | **ADR-075** — `CHECK` care face imposibilă supersedarea fără motiv | propunere | Mic. Monitorul prinde deja clasa (clasa 9, activă). |
| **1.5** | **D-14** — tabelă de audit `model_config` | decizie cerută | **Recomandarea mea: NU acum.** Reparația aplicată (skill + gardă) recuperează ce s-a pierdut. |
| **1.6** | **Punctul 5** — clasa de duplicate `openfootball` | ✅ **ÎNCHIS 21 oct** — măsurat, reparat în cod, cele 30 supersedate (run `39545095203`). Vezi §1.6bis | Golul era **exact 30 de rânduri**, nu 1893. Cauza: un defect de 1 linie în `normalize_team_name`. Nimic de decis. |
| **1.7** | **F3** — pornirea experimentului de value selection | ~**4 noiembrie** | Nimic nu pornește automat (ADR-002). |
| **1.8** | **Radarul vedea 15 competiții din 20** | ✅ **ÎNCHIS 21 oct** — fără nicio linie de cod nouă. Vezi §1.8bis | Cauza nu era la cote. Nimic de decis. |
| **1.9** | **`experiment_registry` contrazicea `model_champions`** | ✅ **ÎNCHIS 21 oct** — `ADR-080` ACCEPTED, implementat și backfill executat. Vezi §1.9bis | Riscul operațional era **ZERO**, verificat pe trei căi. Nimic de decis. |

### 🔴 §1.0ter — 27 oct: aprobarea deciziei #13 ar reseta măsurătoarea D-15. Cuplaj nescris, TTL 2 noiembrie

**Cum a ieșit la iveală**: nu dintr-un simptom, ci verificând starea deciziilor cu TTL înainte de a programa urmărirea benzii ADR-082. Întrebarea era „ce expiră și când"; răspunsul a arătat *pe ce* expiră.

**Cele două propuneri deschise**, ambele `expiry`, ambele pe `baseline_source = 'shadow_control'` (deci cifre corecte, post-ADR-072), ambele cu fereastra de evaluare încheiată 26 oct:

| # | Țintă | n | Acuratețe | Brier | Log-loss | Semnificative |
|---|---|---:|---|---|---|---:|
| **#13** | `xgboost_v1/dda4f7f3` | 347 | **true** (+5,19pp) | false | false | **1 / 3** |
| #12 | `blend_v1/174e7e17` | 500 | false | **true** | **true** | 2 / 3 |

**#13 țintește exact motorul din D-15** — cel care bate Oracle-ul SERVIT cu +5,76pp acuratețe și −0,0242 Brier (n=330, măsurat 26 oct, fără scurgere temporală).

**Cuplajul**: `continuous_learning._process_pair()` rulează Faza B (antrenare nouă) exclusiv când nu există Challenger activ. Comiterea unei expirări eliberează slotul, deci la prima rulare de după se naște un Challenger `xgboost_v1` NOU, cu `training_run_id` nou și **zero** rânduri în `challenger_evaluations` — tiparul deja observat și documentat la activarea ADR-072 (D-1, nota din 14 oct).

Declanșatorul D-15, aprobat explicit pe 26 oct, e **3/3 timp de 10 zile de evaluare consecutive ȘI `n` ≥ 500**. Seria se resetează la orice zi sub 3/3, iar `n` e cel de pe ultima zi. Deci:

> **Aprobarea #13 nu „expiră un Challenger slab" — resetează la n=0 ceasul pe care declanșatorul D-15 îl numără.**

**Ce NU e**: nu e un argument că #13 e greșită. Verdictul a oscilat măsurabil — 3/3 pe 23 oct, 2/3 pe 25 oct, **1/3 pe 26 oct** — și ADR-057 există fiindcă un Challenger blocat în `monitoring` oprește antrenarea întregii familii la nesfârșit, lucru care a costat deja 14 zile în august. Ambele obiective sunt legitime:

- **deblocarea antrenării familiei** (ADR-057) → aprobă expirarea, familia primește un model proaspăt antrenat pe date mai noi;
- **păstrarea artefactului pe care D-15 îl măsoară** → lasă-o să expire singură; ADR-079 o repropune după răcirea de 168 h, pe la **9 noiembrie**, iar între timp seria poate reporni.

**Ce se pierde și ce nu, dacă se lasă să expire**: nimic din evidență — verdictele din `challenger_evaluations` sunt imuabile și rămân. Se pierde doar slotul de antrenare, încă o săptămână.

**Nu recomand niciuna dintre variante fără ca proprietarul produsului să vadă cuplajul.** Aprobările din Decision Feed sunt actul OMULUI (ADR-002) — niciodată prin SQL în numele lui. Intrarea asta există ca să nu se aprobe #13 crezând că e o curățenie de rutină.

**Lecție de metodă**: un declanșator cablat (D-15, clasa 10 în `check_data_health`) numără o serie pe un `training_run_id`. Nimic nu verifică azi dacă acel `training_run_id` mai există. Clasa e mai largă decât cazul: **un declanșator care urmărește o entitate ștergibilă are nevoie și de o condiție despre existența ei**, altfel se resetează tăcut și arată identic cu „n-a atins pragul încă".

### ✅ §1.8bis — 21 oct: radarul vedea 15 din 20, iar cauza NU era la cote

Lipseau Conference League, HNL, Austria Bundesliga, Swiss Super League, Danish
Superliga. `oracle_api.py:1667` — `comps = competitions or list(ODDS_SPORT_KEYS.keys())`:
implicitul unei funcții centrale e „ligile acoperite de **The Odds API**" (16),
nu „ligile pe care le **urmărim**" (21), iar diferența e exact mulțimea celor 5.
Batch-ul ADR-056 o apela fără argument → acele ligi n-au avut niciodată rând
`control`, iar radarul cere predicția **înainte** de cote.

Dovada curată, aceeași zi și același tip de competiție: **15 oct, Europa League
18/18 cu `control`, Conference League 0/18.**

**Reparația exista din 15 oct** (`332ca74`) și a stat **inertă șase zile**,
fiindcă pe 17 oct cheia de cache a trecut de 255 de octeți și a omorât exact
etapa care ar fi beneficiat de ea. Două defecte independente, al doilea
mascându-l pe primul. **O reparație merge-uită nu e o reparație ajunsă în
efect.**

Verificat prin rulare manuală (`39601154972`): `fara_predictie` **31 → 0**,
`retinute` **120/120**, **20 de ligi**, `cote_din_fallback` **0 → 28** (prima
execuție în producție a punții scrise în septembrie pentru HNL).

**Două afirmații ale mele, infirmate de măsurătoare**, ambele părând să
confirme ipoteza corectă-ca-fapt a proprietarului produsului că „cele 5 citesc
cotele din altă tabelă". Detalii: `DE_URMARIT.md` §10.

### ✅ §1.9bis — 21 oct: analiza cerută înainte de ADR mi-a schimbat teza

Propusesem să leg `experiment_registry` de `model_champions`. **Analiza a
infirmat propunerea** — ar fi fost o dependență nouă către un strat superior,
ca să repar un simptom.

**Riscul operațional e ZERO**, verificat pe trei căi: nimic nu citește
`experiment_registry.status` în producție; poarta de promovare cere starea FSM
`SUCCEEDED` **și** verdictul imuabil din `challenger_evaluations`; iar calea de
propunere ia ținta din `get_active_challenger()`, care nu întoarce niciodată un
model promovat.

**Cauza reală**: `promote_experiment()`/`deprecate_experiment()` aveau **ZERO
apelanți de producție**, și niciun rând n-a purtat vreodată `promoted`.
Agravant: `8ac89c70` are ultima scriere shadow cu **13 minute** înainte de
propria promovare, deci evaluarea nocturnă recalcula la nesfârșit același
verdict pe date înghețate — cu `last_evaluated_at` împrospătat de fiecare dată.
**Rândul arăta proaspăt, măsurătoarea era de două luni.**

**Discovery Rule**: prima implementare a pus apelul în `promotion_service` și a
căzut pe o gardă **existentă** — *„Promotion execută, nu decide"* (ADR-019).
Garda avea dreptate, n-a fost ștearsă, cablarea s-a mutat în orchestrator.

**Executat**: ADR-080 ACCEPTED, `main` @ `51997c4`, 22 de teste, 9 mutații,
backfill de **un rând** cu precondițiile recitite din bază. Registrul acum:
`monitoring` 4 · **`promoted` 1** · `rejected` 1 · `insufficient_data` 1 —
**zero `candidate_for_promotion`**.

**Rămâne de verificat la prima rulare de noapte**: `last_evaluated_at` al
rândului `promoted` **nu trebuie să avanseze**.

### ✅ §1.6bis — MĂSURAT 2026-10-21: clasa `openfootball` e 30 de rânduri, și are o CAUZĂ RĂDĂCINĂ

§1.6 spunea: *„1893 de rânduri active; dacă rândurile nesufixate duplică și ele
— NEMĂSURAT. Ăsta e elementul real, nu cele 5 nume."* Măsurat read-only, cu
resolverul REAL (`mappings.normalize_team_name`), pe toate grupurile de
(zi, scor, competiție) care conțin un rând `openfootball` și unul din altă
sursă, ambele active: **343 de rânduri, 154 de grupuri.**

| Comparația | Duplicate reale |
|---|---:|
| cu `normalize_team_name` **actual** | **0** |
| cu reparația (vezi mai jos) | **30**, toate Champions League |

**Un „0" nu se raportează fără martor pozitiv.** L-am validat pe perechea
documentată în D-13 — Inter–Bayern, 16 apr 2025, id **3823** (`fd_524115`) +
id **130925** (`openfootball_…`). E **activă**, aceeași zi, aceeași competiție,
același scor 2-2 — și măsurătoarea cu resolverul actual **nu o vedea**. Fără
martor, aș fi raportat „zero duplicate, gol închis".

#### Cauza rădăcină, verificată linie cu linie (`mappings.py:1402`)

Ramura care dezbracă sufixul de țară caută forma **fără diacritice**, dar
aliasul e înregistrat **cu** diacritic:

```
'fc bayern münchen'  în ALIAS_TO_CANONICAL: True
'fc bayern munchen'  în ALIAS_TO_CANONICAL: False   ← ce caută codul
```

`uni = _unicode_normalize(cleaned)` elimină diacriticele ÎNAINTE de dezbrăcarea
sufixului, deci lookup-ul ratează exact numele care au nevoie de el. **52 din
977 de alias-uri au diacritice**, iar cele trei cluburi din D-13 „Clasa A" le au
toate: `FC Bayern München`, `Club Atlético de Madrid`, `ŠK Slovan Bratislava`.

**Deci D-13 avea cifra corectă (30) dar cauza greșită.** Scria că clasa e
*„invizibilă indexului unic PRIN CONSTRUCȚIE, fiindcă etichetele diferă"*. Nu e
prin construcție — e un defect localizat. Iar restul se închide: cele 129 de
grupuri candidate rămase sunt **coincidențe reale** (aceeași zi, același scor,
alte echipe), deci **rândurile `openfootball` nesufixate NU duplică**.

#### 🔴 Primul meu prototip de reparație era GREȘIT — prins măsurând, nu recitind

Varianta evidentă (dezbracă sufixul, renormalizează) schimba **toate 53** de
etichete cu sufix, nu 3: pentru cele 50 ASCII întorcea numele dezbrăcat **ca
ieșire** — `TNS (WAL)` → `TNS`, `Klaksvik (FAI)` → `Klaksvik`. Asta încalcă
direct ADR-058 §2.3, citat în chiar comentariul de deasupra codului: *„Sufixul
de tara e strict CHEIE DE CAUTARE, niciodata iesire"*. Ar fi redenumit tăcut
50 de cluburi.

Varianta corectă e **un candidat de căutare în plus**, iar raza de acțiune e
mărginită prin construcție (fixul stă în ramura gardată de „are sufix"):

| | |
|---|---:|
| etichete cu sufix verificate | 53 |
| **rezolvări care se schimbă** | **3** |
| nume NEsufixate atinse | **0** |

#### ✅ EXECUTAT 2026-10-21 — supersedarea celor 30 de rânduri

Reparația resolverului **nu** unifica retroactiv nimic — schimba rezolvarea de
aici înainte. Cele 30 de rânduri istorice cereau o operație separată, iar
**redenumirea era imposibilă structural** (ar viola
`idx_match_history_natural_key_canonical`): operația corectă e
**supersedarea**, precedentul fiind Rijeka–Dinamo Zagreb și cele 3 fantome din
16 oct.

**Aprobată explicit** și executată prin `identity_reconciliation_full.yml`
(`confirm: EXECUTE-FULL`), **run `39545095203`**, pe `main` @ `2b20f39`.
Verificat în bază după rulare: **30** marcate, **30/30** spre geamănul corect
`football_data`, **30/30** cu motiv + marcaj temporal, **0** rânduri canonice
atinse, **0** redenumiri, datele fizice păstrate 30/30. Total: 59.565 de
rânduri, **52.793 active**, **6772 supersedate** — 6742 + 30 se închide exact.

**Starea ÎNAINTE, ca punct de comparație**: 30/30 nemarcate pe ambele părți,
30/30 cu rezultat identic și aceeași zi — dovedit același meci, nu două.

Rollback, efect real și ce rămâne neatins: `DE_URMARIT` §9.

**Ordinea, cu precedentul D-13 Clasa B**: cod întâi, date după. Respectată —
`326afea` (resolver) și `2b20f39` erau pe `main` înainte de rulare.

---

### ✅ DECIZIE LUATĂ 2026-10-21 — `decision_feed` #6 se lasă să fie ORFANIZATĂ

**Nu e o acțiune, e o decizie de a NU acționa — consemnată tocmai ca să nu fie
citită ca defect** de cine vede `orphaned` săptămâna viitoare.

Starea: `approved` din 14 septembrie (consens, `agreement_score`, producător
ADR-033), TTL depășit din 21 septembrie, niciodată `committed`. Până la ADR-079
nu putea fi nici măcar **văzută** — `list_pending_decisions()` arată exclusiv
`pending`, deci dispăruse de pe ecran în secunda în care a fost aprobată.

**De ce orfanizarea e răspunsul CORECT, nu o renunțare.** Aseară recomandasem
„dacă vrei s-o închizi manual, trebuie înainte de următoarea rulare".
Reconsiderat: `orphaned` e **starea adevărată**. A fost aprobată și nicio linie
de cod nu a executat-o — exact definiția ADR-026 pentru eșec de producător. A o
marca „executată manual" ar fi o **afirmație falsă**: nu s-a comutat niciun
flag. Controlul manual din ADR-079 §2 e pentru a consemna ce ai făcut, nu pentru
a închide ce n-ai făcut.

**Bucla se vindecă singură, verificat în cod**: `orphaned` nu e în
`_OPEN_DECISION_STATUSES`, nici în `_STARI_PENTRU_RACIRE`. Deci la următoarea
rulare `consensus_validation`, dacă verdictul e în continuare `surface_worthy`,
se naște o **propunere nouă** — de data asta vizibilă, etichetată, și cu
avertismentul că nicio fază n-o execută. Sistemul te întreabă din nou, onest.

**Ce se întâmplă, și când**: prima rulare `night_sync` cu ADR-079 (așteptată
~07:20 UTC pe 21 oct, vezi `DE_URMARIT` §7) apelează sweep-ul, care trece #6 în
`orphaned` cu `resolved_by = 'sweep-adr-026'` și raportează
`stale_orphaned = 1`. **Un `orphaned` acolo e comportamentul proiectat, nu o
regresie.**

---

## 2. TIER 1 — bucla de decizie umană nu funcționează

**Ăsta e cel mai important lucru din document, și e și cauza tehnică a
problemei pe care ai ridicat-o**: lucrurile se pierd. Nu doar în conversație —
**și în sistem**.

**[ÎNCHIS 2026-10-21 — toate patru]** Erau trei defecte; **au fost patru**, iar
al patrulea (2.4, cel mai grav) a ieșit la iveală exact din repararea lui 2.3.
2.3 a fost livrat pe 20 oct; celelalte trei au intrat într-un singur document,
**`ADR-079-decision-lifecycle.md`** — ACCEPTED, revizia 2, **implementat și pe
`main`** (`3ff2f4d`, 21 oct). §0 arată de ce nu se puteau decide separat:
cablarea sweep-ului (2.2) *produce* defectul 2.4 dacă 2.4 nu e reparat întâi.

**Nu declar secțiunea verificată, doar implementată.** Codul n-a rulat încă
nicio dată — a intrat pe `main` la 03:26 UTC, iar prima rulare care îl prinde e
așteptată ~07:20 UTC pe 21 oct. Lista exactă de verificat: `DE_URMARIT` §8.
Până atunci, „merge" se sprijină pe 39 de teste și 13 mutații, nu pe producție.

**Două erori de proiectare ale mele au fost prinse la review-ul cerut explicit**
(„vezi dacă ai greșit ceva"), amândouă ar fi produs pagubă: reparația §4.1 ar fi
blocat permanent familia `blend_v1`, iar răcirea §3.2 ar fi fost inertă exact pe
`expired`. Detaliile, în ADR-079 §4.1.1 și §3.2.

### 2.1 Decizii care nu pot fi comise (D-8)

`learning_core/consensus_validation.py` produce propuneri, dar **nu are fază de
execuție**. `commit_decision()` e apelat exclusiv din `continuous_learning.py`.

Deci decizia **#6**, pe care ai aprobat-o pe **14 septembrie**, va rămâne
`approved` la infinit. Sistemul ți-a cerut o decizie pe care nu o poate duce la
capăt.

**De decis**: se implementează execuția, sau se oprește producerea de propuneri
pe care nimeni nu le poate comite. Cere ADR (schimbă responsabilitatea unei
componente).

### 2.2 Nimic nu semnalează o decizie uitată (D-5)

`automation_runs.sweep_stale_decisions()` implementează politica de TTL din
ADR-026. **Niciun workflow nu o apelează** — singurii apelanți sunt două teste.

Consecința e ambivalentă, și tocmai de asta trebuie decisă: azi ne avantajează
(decizia #7 a rămas aprobabilă mult după TTL), dar înseamnă că **#7 a stat 22 de
zile fără niciun semnal**, iar #6 e blocată de o lună.

**De decis**: se cablează sweep-ul (TTL-ul devine real, cu riscul de a expira
propuneri nevăzute), sau se înlocuiește TTL-ul cu o alertă. Ambele cer ADR.

### 2.3 Ecranul nu numește ce aprobi (D-11) — ✅ **REPARAT 20 oct**

Titlul era `[T3a] decizie #7 · run_id=786` — mut despre acțiune, lângă un buton
verde. A produs o confuzie reală: ai raportat „am promovat noul candidat", dar
ce aprobaseși era o **expirare**.

Acum titlul **și ambele butoane** numesc acțiunea și ținta:

```
[T3a] EXPIRARE Challenger · blend_v1/174e7e17 · n=301 · decizie #8
```

Deciziile de consens (#6) **n-au `decision_kind` deloc** — acolo apare
`FEL NECUNOSCUT (verdict: surface_worthy)`, niciodată gol și niciodată ghicit.
14 teste, 7 mutații prinse, calea de scriere neatinsă. Fără ADR (prezentare).

**Gol rămas în ea, găsit la o zi**: calea de promovare nu scrie niciodată
`decision_kind` (Faza C compensează cu un implicit), deci o propunere de
**promovare** — felul cu consecința cea mai mare — s-ar afișa ca
`FEL NECUNOSCUT`. O linie, în ADR-079 §4.3. A ieșit la iveală tocmai pentru că
2.3 a scos câmpul din adâncul unui `st.json` în titlu.

### 2.4 O decizie deschisă își poate schimba tăcut FELUL — 🔴 cel mai grav

`propose_decision()` suprascrie `evidence`-ul oricărei decizii **deschise** pe
același `target_key` — inclusiv una `approved`. Clasa e deja cunoscută și
numită în cod (garda `R3-Risk-1`), dar garda e aplicată pe **una din trei**
căi: rollback o are, expirarea doar parțial, **promovarea deloc**.

Fazele rulează A → … → C în **aceeași trecere**. Deci: aprobi #8 (expirare) →
Challenger-ul devine candidat → Faza A suprascrie `evidence`-ul lui #8 cu unul
de promovare → Faza C, câteva linii mai jos, **promovează campionul**. Ai
aprobat o expirare, sistemul execută o promovare. **Contrazice ADR-002.**

Singurul lucru care ține riscul închis azi e că #8 e `pending`, nu `approved`.
Scenariul pas cu pas și reparația (la nivelul invariantului, nu al
apelantului): **ADR-079 §4.1**.

> **Recomandarea mea pentru Tier 1**: 2.3 e livrată. 2.1, 2.2 și 2.4 sunt
> **ADR-079**, de aprobat ca un întreg — ordinea internă e fixată în el: 2.4
> întâi (singurul ireversibil), apoi 2.2, apoi 2.1.
>
> *(formularea anterioară, din 20 oct dimineața, păstrată ca istoric: „Rămân
> 2.1 și 2.2, de luat împreună, ca un singur ADR despre ciclul de viață al unei
> decizii". Era corectă ca direcție, dar nu știa de 2.4.)*

---

## 3. TIER 2 — calitatea datelor

Starea e **bună**, și merită spus: din 1699 de meciuri terminate în sezon,
**91,5% au xG real**, iar octombrie e **100% (340/340)**. Reparația ADR-076 plus
recuperarea au închis golul de 39 de zile.

### 3.1 Restanța de xG, pe luni (măsurat 20 oct)

| Lună | Terminate | Fără xG | Acoperire |
|---|---:|---:|---:|
| iulie | 146 | **53** | 63,7% |
| august | 679 | **85** | 87,5% |
| septembrie | 534 | 6 | 98,9% |
| octombrie | 340 | **0** | **100,0%** |

Cele 53 din iulie sunt în mare parte **structurale** (calificări europene, unde
Flashscore nu publică xG). Cele 85 din august sunt restanța genuin recuperabilă.

**De făcut**: încă o tranșă de `--recover-missing-stats` țintită pe august.
Ieftin, fără decizie — lista se recalculează din bază la fiecare rulare.

### 3.2 Detectorul de rupere PARȚIALĂ (D-12 §D-C)

Clasa 7 prinde „extragerea a murit complet", nu „3 categorii din 45 s-au
redenumit". Instrumentul e ieftin (`match_statistics_extended` e deja EAV).
**Dar linia de bază nu există**: pornit azi, ar compara cu golul de 39 de zile.

**De reluat ~2 noiembrie.**

### 3.3 Decuplarea înregistrării de servire de existența unui Challenger — ADR propriu

**Declanșator: DUPĂ ce ADR-082 §6.3 trece cu divergență zero.** Nu înainte, și
motivul e de metodă, nu de prudență — vezi mai jos.

**Golul, verificat în cod (2026-10-27)**: `oracle_engine._serving_record_if_enabled()`
are **exact două apeluri** (liniile 2392 și 2428), ambele în hook-urile de
Challenger, iar ambele adaptoare ies imediat dacă nu există Challenger activ.

> **Fără Challenger activ, ADR-073 nu persistă nicio înregistrare de servire.**

Fragilitatea e **preexistentă** ADR-082 — e adevărată azi — și anticipată de
`CLAUDE.md` D-2: *„ar rezolva și gaura de acoperire din ADR-072 D2, dacă
scrierea rândului `control` se decuplează de existența unui Challenger"*.

**De ce merită ADR propriu, nu un apendice la 082**: decuplarea închide **două**
goluri, nu unul. Al doilea e ADR-072 D2 — `flashscore_team_dna` are **0 rânduri
`control` din 989**, deci e singurul `candidate_for_promotion` pe care poarta
ADR-072 nu îl poate verifica. Schimbare de contract cu beneficiar propriu.

**Expunerea de azi e mărginită la o noapte, măsurat — nu nedefinit:**

| Măsurătoare | Valoare |
|---|---|
Challengeri activi | `174e7e17` + `dda4f7f3`, ambii `SUCCEEDED` |
Propuneri de expirare `pending` | deciziile **#12** și **#13**, expiră **2 nov** |
Condiția Fazei B (`_phase_b_train_new:555-562`) | `n_new >= 30`, numărat de la `created_at` al ultimului Challenger (**20 sept** pentru `174e7e17`) → sute de meciuri, prag depășit **cu certitudine** |
Ritm măsurat | **23,7** meciuri terminate/zi |
Momentul antrenării înlocuitorului | rularea **următoare** (`active_count` se citește la intrare — D-1, `automation_runs` id=1084) |
**Gol efectiv** | **o noapte · ~22 fixture-uri nereluabile din ~660/lună = 3,3%** |

Iar Faza 3 le **numără și le raportează** explicit (`fără înregistrare
ADR-073`), nu le sare tăcut.

**Scenariul blocant NU e cel intuitiv.** Un Challenger blocat (tiparul ADR-057)
e un Challenger **activ**, deci înregistrarea continuă să se scrie — acel caz e
*sigur*. Periculos e „nicio familie fără Challenger activ, pentru mult timp",
care cere expirare **plus** eșecul repetat al Fazei B — exclus de cifrele de mai
sus.

**Singura condiție care ar face-o imperativă**: o decizie de a retrage complet
Challengerii (de pildă după un V1 pe calea de servire, când ar părea
redundanți). Atunci ADR-073 s-ar opri definitiv, iar banda ADR-082 ar deveni
permanent neverificabilă.

**De ce NU se face în timpul ADR-082**: Faza 3 are un singur criteriu —
divergență zero între banda scrisă live și relurea pe intrările persistate.
Decuplarea ar schimba **cum se persistă chiar acele intrări**. O divergență
nenulă ar avea atunci **două cauze candidate**, exact ambiguitatea pe care
martorul de control există ca să o elimine. Nu se schimbă ce măsori, în timpul
măsurătorii.

---

## 4. TIER 3 — calitatea predicțiilor

**Afirmația cea mai importantă, și e contraintuitivă**: măsurat contra unui reper
extern pe 986 de meciuri, Oracle e **statistic indistinct de casele de pariuri
pe 97,5% din volum** (−1,98 pp, z = 1,35, nesemnificativ).

Asta schimbă ce înseamnă „mai bun". Două leviere au fost **măsurate și închise**:

- **Calibrarea** — erorile pe șase găleți sunt toate sub ~1,3σ. Recalibrarea
  n-ar aduce nimic.
- **Accidentările** — ar acționa exact pe meciurile unde nu se vede headroom.
  Plafonul „măsurat" de +16,67pp s-a dovedit artefact (oracolul nul câștigă mai
  mult). Deprioritizat cu motiv.

### 4.1 Singurul levier identificat cu dovezi: filtrul de formă în cupe

`supabase_client.py:372` — forma e filtrată pe competiție. Filtrul **se
păstrează** (măsurat: dispersia campionat→UCL e 2,0 ppm; o formă indiferentă la
competiție ar fi inversat ordinea Liverpool/PSV). Ce lipsește:

1. **legarea de sezon** — azi `lookback_days=365` trece peste granița de sezon;
2. **o cale de rezervă onestă** pentru echipele fără istoric european — formă
   domestică penalizată, marcată ca substitut, **niciodată constantă**.

**Cele două se decid împreună**: un fix care atinge doar sezonul mută 16 cluburi
mari din „date vechi" în „fără date" — ar înrăutăți situația. Cere ADR.

**Onest despre mărime**: forma 1 (constanta neutră) e deja închisă — zero meciuri
servite cu constantă după 20 august. Rămâne forma 2 (date reale dar vechi), a
cărei **pagubă nu e cuantificată**, fiindcă vechimea formei servite nu se
persistă nicăieri. Deci ăsta e un candidat de investigat, nu o reparație sigură.

### 4.2 F3 — value selection (~4 noiembrie)

Nu e despre acuratețea predicției, ci despre **ce pariezi**. Brațul care
guvernează, `market_floor_040`, e la **103/150** cu 3,07/zi; cele 8 săptămâni se
împlinesc ~31 oct. Condițiile se închid împreună.

Capcană consemnată: poarta numără **fixture-uri distincte per categorie**, nu
pariuri. Pe pariuri pare demult complet (1342) — nu e.

---

## 5. TIER 4 — igienă

| Ce | Măsurat | Acțiune |
|---|---|---|
| Rânduri `gate_validation_test` în `model_champions`/`challengers` | 3 „campioni activi" + 1 challenger, din 14 iulie | artefacte de test care poluează orice interogare de stare — de șters sau de marcat |
| `openfootball` | 2119 rânduri, **1893 active** | ✅ **ÎNCHIS 21 oct**: duplica exact **30**, toate din 3 etichete cu diacritic + sufix; cele nesufixate NU duplică. Cele 30 sunt **supersedate** (run `39545095203`). Vezi §1.6bis |
| Backup-uri | 9,77 MB + 72 kB, 59 de zile | §1.2 |
| `Din. Minsk (BLR)` | 2 rânduri, fără geamăn | lăsat deliberat, cu gardă |
| ~49 de cluburi văzute doar cu sufix | — | igienă de vocabular, nu reparație |

---

## 6. CE NU FACEM, ȘI DE CE

Lista asta există ca să nu se redeschidă din entuziasm.

- **Recalibrarea probabilităților** — măsurat, zero câștig.
- **Accidentările** — fără headroom vizibil; dacă se reia, ordinea e obligatorie:
  flag oprit → colector → backtest read-only → shadow → activare.
- **Mărirea pragului Team Profile 300→600** — n-ar ajuta; zgomotul depinde de xG
  per echipă, nu de mărimea setului. Reluare ~feb-mar 2027.
- **`weather_forecast`** — gol lăsat documentat prin decizie explicită.
- **Norvegia + Suedia** — martie 2027 (sezon apr-oct).
- **Tabela de audit `model_config`** — nu încă (§1.5).
- **Promovare automată** — contrazice ADR-002, cere ADR dedicat.

---

## 7. UNDE SUNT DETALIILE

Documentele astea rămân valabile **ca dovadă și istoric**. Ordinea de lucru e
aici, nu în ele.

| Document | Ce conține |
|---|---|
| `CLAUDE.md` §DECIZII | D-1…D-14, cu toată istoria fiecăreia |
| `PLAN_DECIZII_DESCHISE_2026-10-20.md` | analiza celor cinci decizii + §6.1-6.4, ce s-a executat |
| `DE_URMARIT.md` | semnale deschise, cu declanșatori |
| `ADR-07x` | deciziile individuale |
| `EUROPEAN_COMPETITION_FORM_FILTER_DEFECT.md` | §4.1, cu toate cifrele |

---

## 8. REGULI CARE NU SE ÎNCALCĂ

Repetate aici fiindcă se aplică la fiecare intrare de mai sus:

1. Nicio scriere pe Supabase fără SQL arătat + confirmare explicită.
2. Niciun push pe `main` fără aprobare **per push**.
3. `pytest tests/` verde pe `main` **înainte** de push.
4. Orice tabelă nouă: `GRANT` către `service_role` (obligatoriu de la 30 oct).
5. Descoperire nouă de contract → **Discovery Rule**: oprește-te și prezintă.
