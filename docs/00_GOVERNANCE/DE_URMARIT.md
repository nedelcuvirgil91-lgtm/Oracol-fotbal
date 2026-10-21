# De urmărit — listă vie

Un singur loc pentru „ce așteptăm, când, și ce înseamnă dacă nu vine". Se actualizează; nu e jurnal istoric.

Ultima actualizare: **2026-10-21**. Ultimul element adăugat: **§8 — prima rulare
cu ADR-079 (~07:20 UTC), cu lista exactă de verificat** și ce e comportament
proiectat, nu regresie.

**Două semnale deschise, în ordinea în care se declanșează**: §8 (azi, ~07:20
UTC) și §7 (decizia #8, **~26-27 oct** — nu 23, vezi corecția din §7).

---

## Răspunsul scurt la întrebarea care revine: cine promovează un campion?

**Tu. Manual. Nimic nu e automat, și nimic nu s-a schimbat azi în privința asta.**

Verificat în cod, nu din memorie:

| Întrebare | Răspuns | Dovada |
|---|---|---|
| Există auto-promovare? | **NU** | `auto_promotion_enabled` apare într-un singur fișier, într-un comentariu care spune că e neimplementat. Zero apelanți. |
| Ce poate schimba campionul? | O singură funcție | `continuous_learning._phase_c_execute_approved()` → `promote_challenger()` |
| Ce o declanșează? | **Doar decizii deja aprobate de om** | `ar.list_approved_decisions_for_target()` — iterează exclusiv deciziile cu status `approved` |
| Reparația D-10 poate promova ceva? | **NU** | `shadow_testing.py` nu apelează `promote_challenger`, `propose_decision`, `model_champions` sau `write_run`. Scrie exclusiv în `experiment_registry`. |

**De ce nu ai ce aproba acum**: o propunere de promovare se naște doar la `verdict == "candidate_for_promotion"`, care cere `n ≥ 200` **și** Brier + log-loss + acuratețe *simultan* semnificative. Azi `xgboost_v1/dda4f7f3` e la **n = 0** (abia născut, după expirarea pe care ai aprobat-o pe 13 oct) și `blend_v1/174e7e17` la **n = 151**.

Deci feed-ul gol nu e o defecțiune și nu e autonomie — e consecința directă a aprobării tale: slotul blocat s-a eliberat, Challenger-ul nou s-a născut la zero, și acum acumulează meciuri.

**Când reapare o bară**: `blend_v1` trece de 200 pe ~19-20 oct. Dacă atunci bate Oracle simultan pe toate trei metricile, apare o propunere și o aprobi. Dacă nu, rămâne `monitoring` și nu apare nimic.

---

## 1. Rularea `night_sync` 38620259384 — ADR-073, flagul oprit — ✅ **POARTA A ȚINUT**

> **[VERIFICAT — 2026-10-14, 20:45 UTC]** Rulare **completă, `success`**, 87m29s (19:02:12 → 20:29:41).
>
> | Experiment | Grup | Rânduri ATINSE de rulare | cu `schema_version` |
> |---|---|---:|---:|
> | `blend_v1` | control | **150** | **0** |
> | `blend_v1` | treatment | 150 | 0 |
> | `xgboost_v1` | control | **150** | **0** |
> | `xgboost_v1` | treatment | 150 | 0 |
> | `flashscore_team_dna` | treatment | 150 | 0 (și `metadata_gol = 0` → canalul dovedit merge mai departe) |
>
> **750 de scrieri reale sub codul ADR-073, zero înregistrări atașate.** Flagul oprit se respectă.
>
> **CONTRAPONDEREA MEA ERA PROST FORMULATĂ, și era să citesc greșit rezultatul.** Scrisesem „`randuri` trebuie să CREASCĂ, altfel testul e vid". Totalurile au rămas **identice** (1299 / 1457 / 1167) — ceea ce, citit literal, ar fi însemnat „rularea n-a scris nimic".
>
> **Fals.** `log_shadow_prediction()` face `upsert` pe cheia compusă `(fixture_id, experiment_name, experiment_version, experiment_group, processing_stage)`. Batch-ul ADR-056 reprocesează aceeași fereastră de 7 zile în fiecare noapte, deci **rescrie** rândurile existente; totalul crește doar când intră fixture-uri NOI în fereastră. Semnalul corect că rularea a scris nu e numărul de rânduri, ci `prediction_time` avansat — **150 pe grup**, verificat separat.
>
> Lecția, în aceeași familie cu celelalte de azi: **o contrapondere formulată pe metrica greșită transformă o confirmare validă într-un fals negativ.** Criteriul corect e scris acum în interogarea de mai jos.

**Pornită**: 14 oct, 19:02 UTC, pe `9a8c0f6`. Check-in armat la 20:44 UTC.

**Ce dovedește**: că poarta flagului `serving_inputs_persistence_enabled` chiar ține. Contează, fiindcă `challenger_shadow_logging_enabled` și `blend_challenger_shadow_logging_enabled` sunt amândouă `true` — codul nou **se execută** la fiecare meci, și e inert exclusiv prin poartă.

**Criteriul, binar**: `cu_schema_version` rămâne **0** peste tot.

```sql
SELECT experiment_name, experiment_group, count(*) AS randuri,
       count(*) FILTER (WHERE feature_metadata = '{}'::jsonb) AS metadata_gol,
       count(*) FILTER (WHERE feature_metadata ? 'schema_version') AS cu_schema_version
FROM shadow_predictions GROUP BY 1,2 ORDER BY 1,2;
```

Referință măsurată înainte (14 oct ~19:00 UTC): `blend_v1` control **1299**, `xgboost_v1` control **1457**, ambele integral `{}`, zero `schema_version`. `flashscore_team_dna/treatment` **1167**, zero goale.

**Contrapondere — forma CORECTATĂ.** Nu „rândurile cresc" (scrierea e `upsert`, vezi nota de sus), ci „câte rânduri a atins efectiv rularea":

```sql
SELECT experiment_name, experiment_group,
       count(*) FILTER (WHERE prediction_time >= '<ora de start a rularii>') AS atinse_de_rulare,
       count(*) FILTER (WHERE prediction_time >= '<ora de start a rularii>'
                          AND feature_metadata ? 'schema_version') AS atinse_CU_schema_version
FROM shadow_predictions GROUP BY 1,2 ORDER BY 1,2;
```

`atinse_de_rulare` trebuie să fie **de ordinul sutelor**; `atinse_CU_schema_version` trebuie să fie **0**. Plus `flashscore_team_dna` rămâne la zero goale (altfel am rupt canalul care funcționa).

**Dacă pică**: nu se activează nimic; se repară poarta întâi.

> **[ACTIVAT — 2026-10-15, 04:19 UTC]** Flagul e `true` (boolean). Amprentă verificată: 36 → **37 chei**, `md5(data − cheia_nouă)` identică. Punctul ăsta e ÎNCHIS; ce urmează e §1bis.

---

## 1bis. Prima rulare cu flagul ADR-073 PORNIT — ✅ **VERIFICAT END-TO-END**

> **[CONFIRMAT — rularea `38697307312`, 15 oct, `schedule`, `success`, 97m39s, pe `ce999d7`]**
>
> | Experiment | Grup | Atinse | cu înregistrare |
> |---|---|---:|---:|
> | `blend_v1` | **control** | 159 | **159** ✅ |
> | `xgboost_v1` | **control** | 159 | **159** ✅ |
> | `blend_v1` | treatment | 159 | **0** ✅ |
> | `xgboost_v1` | treatment | 159 | **0** ✅ |
> | `flashscore_team_dna` | treatment | 159 | **0** ✅ (își păstrează metadatele proprii) |
>
> **REPRODUCEREA — testul care contează — e EXACTĂ.** Pe rândul real `flashscore_r5IEVWof`, `calibrate_xg(**oracle_inputs)` din înregistrarea stocată întoarce `home=1.3747, away=0.3278`, **identic** cu `oracle_outputs.{home,away}_xg_pre_injury`, la toleranță 1e-9. Înregistrarea conține cele 15 valori de intrare, ambele xG (pre și post), `xg_changed_after_injury_step: false`, `data_quality` proaspăt (`partial`/`partial`) și 20 de chei `ml_features`. **1175 de octeți** măsurat (estimasem 1065 — cu 10% mai mult).
>
> **D-2 e închisă complet.** Orice predicție servită de acum e descompozabilă până la intrările ei (North Star #9).

## 1ter. Istoric — verificarea inversă, înainte de confirmare

**Când**: următoarea rulare `night_sync`. Cron-ul de la 02:00 UTC pe 15 oct **nu rulase încă la 04:19** — tiparul documentat de throttling GitHub livrează slotul pe la ~07:00-09:00 UTC.

**Criteriile, toate patru:**

```sql
SELECT experiment_name, experiment_group,
       count(*) FILTER (WHERE prediction_time >= '<start rulare>') AS atinse,
       count(*) FILTER (WHERE prediction_time >= '<start rulare>'
                          AND feature_metadata ? 'schema_version') AS cu_inregistrare
FROM shadow_predictions GROUP BY 1,2 ORDER BY 1,2;
```

1. `cu_inregistrare` **> 0** pe `control` (`xgboost_v1`, `blend_v1`), cu `schema_version = 1`.
2. `treatment` rămâne la **`{}`** — înregistrarea Oracle n-are ce căuta pe rândul Challenger-ului.
3. `flashscore_team_dna` își păstrează metadatele proprii.
4. **Reproducerea**, pe un rând real: `calibrate_xg(**oracle_inputs)` trebuie să dea exact `oracle_outputs.{home,away}_xg_pre_injury`.

**Dacă (1) e 0**: poarta nu citește flagul în producție — se investighează înainte de orice altceva.

**Atribuire**: aceeași rulare aduce și efectul **D-10**. Cele două sunt independente observațional (tabele diferite: `experiment_registry` vs. `shadow_predictions.feature_metadata`), deci fiecare rămâne atribuibil fără ambiguitate.

---

## 2. Efectul D-10 — ✅ **MĂSURAT. Și predicția mea era pe jumătate GREȘITĂ.**

> **[MĂSURAT — rularea `38697307312`]** Toate cele **7 rânduri** sunt acum la `zile_vechime = 0`. D-10 funcționează: cele trei verdicte înghețate de 33-35 de zile s-au recalculat.
>
> | Experiment | ÎNAINTE (vechi de 33-35 zile) | DUPĂ |
> |---|---|---|
> | `flashscore_team_dna/v1` | **candidate_for_promotion**, n=551, **+2,90pp** | **monitoring**, n=1000, **+1,50pp** |
> | `xgboost_v1/e638c1dc` | monitoring, n=550, −0,18pp | monitoring, n=676, **−1,04pp** |
> | `blend_v1/8ac89c70` | **candidate_for_promotion**, n=378, **+5,29pp** | **candidate_for_promotion**, n=382, **+3,66pp** |
>
> **CE AM PREZIS GREȘIT**: scrisesem, în trei documente, că `blend_v1/8ac89c70` „ar trebui să NU mai fie `candidate_for_promotion`". **A rămas candidat.** Cifra lui s-a corectat exact cum trebuia (+5,29 → **+3,66pp**, identic cu ce măsurasem pe 13 oct contra baseline-ului proaspăt), dar **tot trece poarta**: Brier −0,0118 și log-loss −0,0194, toate trei simultan favorabile. Deci nu era o cifră umflată care se dezumflă sub prag — e un avantaj real, doar mai mic decât părea.
>
> **CE AM PREZIS CORECT, dar din motivul greșit**: `flashscore_team_dna/v1` a ieșit din statutul de candidat (+2,90 → +1,50pp). **Dar NU din cauza ADR-072** — el are 0 rânduri `control`, deci folosește în continuare baseline-ul înghețat (`match_history_frozen`). Scăderea vine din volum (n 551 → 1000), nu din schimbarea reperului. Iar fiindcă `flashscore_team_dna` **ESTE Oracle** (diferență maximă 0,000050 pe 1162 de fixture-uri), cei +1,50pp rămași sunt tot artefactul proaspăt-vs-înghețat, doar diluat.
>
> **Contradicția „campionul activ e candidat de promovat" PERSISTĂ**, acum cu o cifră corectă. Nu produce nicio propunere — `8ac89c70` e `PROMOTED`, nu Challenger activ, iar Faza C acționează doar pe decizii aprobate. Rămâne o inconsecvență de afișare, nu un risc.
>
> **Semnal NEÎNCHIS, de verificat mâine**: `flashscore_team_dna` arată `n = 1000` **fix**, iar rândurile eligibile numărate acum sunt **1022**. Cifra rotundă e semnătura plafonului PostgREST. **Verificat că nu e un plafon de cod**: `get_shadow_predictions()` e paginat keyset, `_read_match_history_for_fixtures()` lucrează pe bucăți de 500 (deci nicio cerere nu poate întoarce 1000), iar numitorul e corect (1022 distincte, zero invalidate, zero șiruri goale, zero baseline-uri lipsă). **Explicația probabilă**: 24 de meciuri din 13-15 octombrie au căpătat rezultat DUPĂ pasul de evaluare din aceeași rulare — ~exact decalajul. **Testul decisiv, la următoarea rulare**: dacă `n` sare la ~1030+, e creștere naturală și subiectul se închide; dacă rămâne **exact 1000**, e a cincea instanță a plafonului și se investighează.

## 2bis. Istoric — ce se aștepta înainte de măsurătoare

**Prima rulare cu `6be6ecd`.** Rularea de aseară e pe codul vechi, deci **nu** măsoară D-10.

**Criteriul**: `zile_vechime` devine **0 pe toate cele 7 rândurile**. Azi trei sunt la 32-34 de zile.

```sql
SELECT experiment_name, left(experiment_version, 8) AS versiune,
       status, n_matches_evaluated,
       round(delta_accuracy::numeric, 4) AS d_acuratete,
       (current_date - last_evaluated_at::date) AS zile_vechime
FROM experiment_registry ORDER BY last_evaluated_at;
```

**Schimbare de cifre de așteptat — scrisă ÎNAINTE să se întâmple, ca să nu fie citită ca regresie**: `blend_v1/8ac89c70` ar trebui să **nu mai fie `candidate_for_promotion`**. Cei +5,29pp ai lui au fost calculați pe baseline-ul înghețat, iar ADR-072 e activ acum. Contradicția „campionul activ e candidat de promovat" dispare pentru că numărul se corectează în jos. **Campionul rămâne campion** — nu există cale automată de rollback.

Al doilea de urmărit: `flashscore_team_dna/v1`, verdict înghețat de 34 de zile (+2,90pp). Reevaluarea lui e exact ce lipsea ca să poată fi comparat cu ablația negativă din 13 oct — până acum se compara o măsurătoare de ieri cu una de acum o lună. **Feature-ul rămâne NEPROMOVAT indiferent de rezultat** (D-7 e închisă pe baza ablației, nu a registrului).

---

## 2ter. 🔴 `n = 1000` FIX la `flashscore_team_dna` — DE VERIFICAT LA URMĂTOAREA RULARE

**Starea**: `experiment_registry` arată `n_matches_evaluated = 1000` **exact**, iar rândurile eligibile numărate independent sunt **1022**. Diferență: **22**.

**De ce merită urmărit și nu ignorat**: 1000 e exact plafonul implicit PostgREST („Max Rows"), iar acest proiect are deja **patru** instanțe reparate ale aceleiași capcane (`get_training_data`, `get_shadow_predictions`, `_read_match_history_for_fixtures`, `get_distinct_experiments`). O cifră rotundă fix la plafon nu se trece cu vederea.

**Ce am verificat deja (15 oct), și exclude un plafon de cod:**

| Verificare | Rezultat |
|---|---|
| `get_shadow_predictions()` paginat keyset pe `id` | ✅ corect, `ORDER BY` + `_PAGE_SIZE` |
| `_read_match_history_for_fixtures()` | ✅ bucăți de **500** → nicio cerere nu poate întoarce 1000 |
| `evaluate_experiment()` are vreun `limit`/slice? | ✅ **nu**, `n = len(eligible)`, fără plafon |
| Numitorul e corect? | ✅ **1022 distincte**, 0 invalidate, 0 șiruri goale, 0 baseline-uri lipsă, toate `v1` |

**Explicația probabilă, dar NEconfirmată**: **24 de meciuri** din 13-15 octombrie sunt eligibile acum — ~exact decalajul de 22. Pasul de evaluare rulează devreme în `night_sync` (în `run_daily`), iar rândurile shadow și rezultatele care sosesc mai târziu în aceeași rulare n-ar fi fost văzute. `flashscore_team_dna` e cel mai expus la asta, fiindcă loghează pe **fiecare** meci evaluat, nu doar pe fereastra unui Challenger.

### Testul decisiv, la următoarea rulare — binar, fără interpretare

```sql
SELECT experiment_name, left(experiment_version,8) AS versiune, n_matches_evaluated
FROM experiment_registry WHERE experiment_name = 'flashscore_team_dna';
```

| Rezultat | Verdict |
|---|---|
| `n` ≈ **1030+** | **Creștere naturală.** Subiectul se închide, nu era plafon. |
| `n` = **exact 1000** din nou | **A cincea instanță a plafonului.** Se investighează, cu prioritate — ar însemna o cale de citire pe care n-am găsit-o. |
| `n` între 1000 și 1030 | Neconcludent; se repetă măsurătoarea cu numitorul recalculat în același moment. |

**Important de reținut la interpretare**: numitorul (1022) trebuie **recalculat în momentul citirii**, nu refolosit — el însuși crește de la o zi la alta. Comparația corectă e `n` de azi contra eligibilelor de azi, nu contra celor de ieri.

**Nu e urgent**: chiar dacă ar fi un plafon, ar afecta un experiment care **nu e un motor** (`flashscore_team_dna` **ESTE** Oracle — diferență maximă 0,000050) și care e `monitoring`, nu candidat. Dar e un semnal de integritate, iar clasa asta a costat deja de patru ori.

---

## 3. **16-18 octombrie** — primul verdict real pe baseline-ul corect

`blend_v1/174e7e17` trece pragul de 200 și produce primul `baseline_source = 'shadow_control'`. Abia atunci ADR-072 e confirmat end-to-end, pe date reale.

**Până atunci, `baseline_source` NULL e CORECT, nu defect** — sub prag, verdictul iese pe return-ul devreme și câmpul nici nu se atașează.

### A TREIA corectare a aceleiași proiecții — și de ce greșesc repetat

| Când am spus-o | Proiecția | Pe ce se baza |
|---|---|---|
| 14 oct, dimineață | 17 octombrie | o extrapolare fără serie măsurată |
| 14 oct, seară | 19-20 octombrie | seria 132→141→144→151, ~9,5/zi |
| **15 oct** | **16-18 octombrie** | seria completă: 144 → 151 → 153 → **175** |

Seria reală a lui `blend_v1/174e7e17`: **144** (13 oct 21:08) → **151** (14 oct 05:30) → **153** (14 oct 20:29) → **175** (15 oct 08:50). Ultima rulare singură a adus **+22**, iar media pe 36 de ore e ~21/zi — de două ori ritmul pe care îl proiectasem cu o zi înainte.

**Cauza erorii mele, de reținut**: ritmul **nu e constant** și nu poate fi. Depinde de câte meciuri se joacă efectiv în fereastră — iar asta variază puternic între zile de weekend, zile de săptămână și pauze internaționale. Am tratat de două ori un proces neomogen ca pe unul liniar, și l-am extrapolat dintr-un segment nereprezentativ.

**Deci forma corectă a răspunsului nu e o dată, ci un interval cu driverul numit**: de la 175, mai sunt 25 de meciuri; la ritmul observat (9-22/zi, după volumul de meciuri) ies **1-3 zile**. Dacă nu apare până pe 18 octombrie, atunci merită verificat — nu înainte.

---

## 4. Fără dată — lucruri care nu se mișcă singure

| | Ce aștept | Ce înseamnă dacă nu vine |
|---|---|---|
| **Activarea ADR-073** | `UPDATE model_config`, după §1 verde | Nimic rău — intrările pur și simplu nu se persistă. Nu degradează nimic. |
| **`xgboost_v1/dda4f7f3`** | să ajungă la n ≥ 200 de la 0 | Săptămâni. Normal, nu blocaj. |
| **D-5** — `sweep_stale_decisions()` | nimic; nu e apelată de nicio linie de producție | Nicio decizie nu expiră singură. Azi ne avantajează; dar nimic nu semnalează o decizie uitată. |
| **D-8** — decizia #6 | nimic; va rămâne `approved` la infinit | `consensus_validation` nu are fază de execuție. **[CORECTAT 2026-10-14]** O descrisesem ca „capcană latentă" fiindcă `decision_kind` absent e tratat implicit ca `promotion`. **Greșit**: `continuous_learning.py:811-812` verifică explicit `training_run_id` și marchează `fail_decision_commit` dacă lipsește. E o decizie orfană, nu un pericol. |
| **D-6** — două backup-uri | nimic; revizuire restantă de ~3 săptămâni | Se păstrează sau se șterg; decizie, nu urgență. |
| **D-3** — consumatorii coloanelor înghețate | nimic; decizie necerută | — |
| **D-11** — Decision Feed nu numește acțiunea | nimic | Același ecran va servi și propuneri de promovare și de rollback. A produs deja o confuzie reală (13 oct). |
| ~~`Salzburg` ≡ `Red Bull Salzburg`~~ **✅ REZOLVAT 17 oct** | — | Canonic `Salzburg` (decizie proprietar produs). 26 de rânduri unificate atomic, 0 rămase cu forma lungă, 0 duplicate create. **Rămân deschise, NEverificate**: `Levski Sofia`/`PFC Levski Sofia` (a doua instanță, găsită pe parcurs), plus RB Leipzig și Bayer Leverkusen ca tipar plauzibil. **§3nonies**. |
| **ADR-075** — dubluri de identitate între provideri | ⏳ **AMÂNAT** până la poarta n≥200 (aceeași ca §3quater). Întâi investigația §8, apoi decizia. | PROPOSED, zero cod. Datele celor 3 cazuri sunt reparate; golul de **observare rapidă** rămâne. Monitorul le prinde deja, la ~6 zile, cu diagnostic manual — deci A e viteză, nu gol închis. Amânarea NU e din risc (A nu poate strica nimic), ci din §8: mecanismul nedeterminat ar putea indica altă reparație. Detalii: **§3octies**. |
| **ADR-074** — istoric de cote din Flashscore | aprobarea ta; apoi implementare **după** pragul F2 | PROPOSED, zero cod. Flashscore dă deja 5,53 case/meci vs. 1,57 la Odds API și acoperă UECL+HNL; singurul lucru care lipsește e mișcarea cotei, și aia e o limită de stocare (suprascriem, 7416 capturi din 7416), nu de provider. Fluxul colectează datele de 2×/zi și le aruncă. |
| **Campionate noi** (Austria, Elveția, Danemarca → apoi Norvegia, Suedia) | calendar complet în **§3quinquies** | Fereastra e ACUM, până la autorizarea F3 — nu „după F2". Analiza din 15 oct: 133 din 206 echipe de cupă n-au campionat urmărit. Precondiție: merge-ul din §3quater, altfel o ligă nouă neacoperită de Odds API ar cădea în aceeași capcană și ar fi adăugată pe jumătate, ca UECL în august. |

---

### Confirmat la check-in (14 oct, 20:45 UTC)

`blend_v1/174e7e17`: **151 → 153**. `xgboost_v1/dda4f7f3`: **0 → 2**. `baseline_source` **NULL pe ambele** — corect, ambele sub pragul de 200, verdictul iese pe return-ul devreme și câmpul nici nu se atașează.

**Proiecția ~19-20 oct se CONFIRMĂ**: seria 144 (13 oct, 21:08) → 151 (14 oct, 05:30) → **153** (14 oct, 20:29) dă ~9/zi peste 23 de ore. De la 153 la 200 ies ~5 zile.

---

## 3bis. D-9 — reprodus a TREIA oară, independent (14 oct, seara)

| | Rularea 38509946577 | Rularea 38620259384 |
|---|---:|---:|
| Apeluri `thesportsdb` | 486 | **502** |
| Peste 100 s | 13 | **14** |
| Eșecuri | 0 | **0** |
| Banda plafonului | 120.355–120.912 ms | **121.134–121.654 ms** |
| Amplitudinea benzii | 557 ms | **520 ms** |
| Timp în apelurile lente | 89% | **89,8%** (1701 s din 1895 s) |
| Restul apelurilor, medie | 393 ms | **397 ms** |

**Plafon determinist, confirmat a treia oară**: 14 apeluri se strâng într-o bandă de 520 ms în jurul a ~121,4 s, toate reușesc, iar restul de 488 răspund în 397 ms mediu. **28,4 minute din cele 87 ale rulării — 33%.**

Concluzia rămâne cea din D-10 §D-9: **micșorarea timeout-ului NU ajută** (`timeout=12` e între octeți, nu total) și ar tăia cereri bune. Fixul corect, dacă se face, e un buget de durată totală per cerere. **Nereparat — e o decizie, nu o investigație.**

---

## 3ter. **26-29 octombrie** — pragul de eșantion care deschide F3 (ADR-071)

Citit prima dată pe 15 octombrie, la cererea proprietarului produsului („hai să vedem ce profil câștigă la F2").

> ### ⚠️ CORECTURĂ DE ETICHETĂ — scrisă în aceeași zi, câteva ore mai târziu
>
> Titlul acestei secțiuni spunea inițial „**primul verdict F2** cu eșantion suficient". **Greșit, și greșeala era a mea.** Pragul de 150 de selecții nu produce un verdict F2 — e **condiția de intrare în F3**, iar ADR-071 spune explicit:
>
> > **F3, NEÎNCEPUT și NEAUTORIZAT**: minimum 8 săptămâni ȘI minimum 150 de selecții (numărate conform §16 — prima apariție), politică înghețată, zero scurgere temporală, fără ajustarea pragurilor pe parcurs.
>
> Și că F3 e blocat de o condiție care **nu e îndeplinită**: ~~cele 13 profile produc doar **7 seturi distincte de selecții**~~, iar „F3 nu poate porni până nu se măsoară pe mai multe zile și se colapsează brațele dovedit identice". (Duplicatul `shrunk_050` ≡ `market_floor_025`, amprenta `32ccbf4a`, redescoperit independent pe 15 oct, e una dintre instanțe.)
>
> > **[CORECTAT 2026-10-19 — „7 seturi distincte" era o măsurătoare de o singură zi și supraestima golul de șase ori.]** Testul corect e **amprenta**, nu setul observat: 13 profile → **12 amprente distincte**, exact **o** coliziune (`32ccbf4a`). Pe 36 de rulări comune, singura pereche identică în 100% din cazuri e tocmai aceea; următoarele sunt la 75%, deci distincte. **Deci duplicatul citat în paranteză nu e „una dintre instanțe" — e SINGURA.** Golul a fost reparat pe 19 oct (marcaj în raportul evaluatorului, nicio ștergere de profil) și golul 2 („evaluatorul nu există") era deja închis. Detaliile, cifrele și ce NU s-a făcut: `ADR-071` §Implementare. **Proiecția corectată**: brațul care întârzie e `market_floor_040` (99 de selecții decise, 3,07/zi) → pragul de 150 pe **toate** politicile cade pe **~3 noiembrie**, nu 26-29 octombrie; cele 8 săptămâni se împlinesc ~31 octombrie, deci cele două condiții se închid împreună.
>
> **Consecința practică e opusul celei pe care o scrisesem**: momentul potrivit pentru campionate noi nu e *după* pragul de 150, ci **înainte de autorizarea F3** — fiindcă F3 cere exact universul stabil pe care o ligă nouă l-ar tulbura. Vezi §3quinquies pentru calendar.
>
> Cifrele din tabelul de mai jos rămân valide — sunt date de colectare F2, corect măsurate. Doar eticheta „verdict" era greșită.

### Unde suntem: sub pragul de intrare, pe toate politicile

ADR-071 cere **150 de selecții decise** per politică (`PRAG_ESANTION_MINIM`). Niciuna dintre politicile de radar nu a ajuns: maximul e **124**. Raportul marchează `esantion_insuficient` pe toate.

| Profil | Decise | Reușită | Piața | ROI | ROI piață | Brier vs piață |
|---|---:|---:|---:|---:|---:|---|
| `shrunk_100` | 111 | 60,4% | 44,7% | **+27,7%** | −5,3% | 0,2304 vs 0,2397 ✓ |
| `market_floor_020` | 116 | 58,6% | 45,2% | +24,3% | −5,0% | ✓ |
| `ranker_prob_value` | 112 | 57,1% | 43,3% | +24,3% | −5,4% | ✓ |
| `shrunk_075` | 111 | 58,6% | 45,4% | +22,5% | −5,3% | ✓ |
| **`shrunk_050`** (activ) | 112 | 58,9% | 46,0% | +21,1% | −5,0% | 0,2338 vs 0,2380 ✓ |
| `market_only` (control) | 124 | 66,1% | 63,8% | −1,4% | −5,1% | ✗ |
| `legacy` | **665** | 30,4% | 28,3% | −2,5% | −5,1% | ✗ |

### Singurul rezultat CU eșantion suficient e un NU, și e util

`legacy` — comportamentul ecranului dinainte de ADR-071 §17, „sortează după edge relativ" — are **665 de selecții decise**, de patru ori pragul, și **cade**: +2,60pp peste controlul de piață, sub criteriul GO de +3pp, cu interval ±8,3pp (deci nedistins de zero). Cota medie 4,65, rata de reușită 30%.

**Avem putere statistică să spunem că vechiul selector nu bate piața.** Exact ce argumenta ADR-071 §2 — edge-ul relativ ridică outsiderii deasupra.

### De ce NU iau de bune cifrele mari, deși arată spectaculos

Verificat și rezistă: de-vig corect (cele trei probabilități însumează **exact 1,0000** pe 1172 de grupuri, marjă de casă 5,76%) · **zero** rânduri `leakage_suspect` · regula „prima apariție" aplicată, deci cotele nu sunt alese retroactiv · `shrunk_100` are z ≈ 3,3 pe rata de reușită.

Ce reține concluzia:

1. **Contrazice reperul extern.** Pe 986 de meciuri (14 oct), Oracle ia 0,4939 vs piața 0,5233 — Oracle e **mai slab** decât casele. Aici, pe ~112 meciuri selectate, pare să bată probabilitatea pieței cu 14pp. Nu e imposibil — selectorul alege tocmai subsetul unde modelul se abate cel mai mult — dar asta e **ipoteza pe care experimentul trebuie s-o dovedească**, nu una pe care are voie s-o presupună.
2. **E maximul a 12 politici aplicate aproape acelorași meciuri** — deci un rezultat citit în 12 feluri, nu 12 teste independente.
3. **112 < 150.** Pragul a fost pus exact pentru situația asta.

### Descoperire colaterală

`shrunk_050` și `market_floor_025` au aceeași amprentă (`32ccbf4a`) și cifre identice până la ultima zecimală — **aceeași politică sub două nume**. Experimentul are 12 politici distincte, nu 13. Cunoscut prin construcție (`value_selector_shadow.semantic_duplicates()` există tocmai pentru asta), nu un defect.

### Când, și ce înseamnă dacă nu vine

~3,3 selecții decise/zi, 112 acumulate → de la 112 la 150 ies **11-14 zile**, adică **26-29 octombrie**. **Interval, nu dată**: ritmul depinde de câte meciuri calificate are fiecare zi — exact variabila subestimată de trei ori la proiecția ADR-072.

Dacă nu vine la termen: nu e defect, e calendar fotbalistic. Semnal real ar fi ca numărul de **decise** să stagneze de la o săptămână la alta, ceea ce ar însemna că selecțiile nu mai primesc rezultat.

**Nimic nu se schimbă automat.** `shrunk_050` rămâne activ până la o decizie umană; schimbarea de profil e `UPDATE model_config`, arătat și confirmat explicit (North Star #6).

### Gol de proces, de reținut

Evaluatorul (`value_selector_evaluation.yml`) e `workflow_dispatch`-only, deliberat („o citire nu produce date, deci nu are motiv să ruleze automat"). Consecința reală: **a rulat o singură dată, pe 6 septembrie, ziua în care a fost construit, și apoi deloc 39 de zile** — până la întrebarea proprietarului produsului. Același tipar ca ADR-057: un mecanism corect pe care nimeni nu-l citește. **Nereparat** — dar dacă F2 se apropie de verdict, merită o cadență, chiar rară.

---

## 3quater. ✅ **MERGE FĂCUT (17 oct)** — reparația competițiilor e pe `main`

> **[ÎNCHIS 2026-10-17]** Merge aprobat explicit de proprietarul produsului și executat: `cb65111` → **`8b2fe2a`**, rebase pe `main` apoi fast-forward curat, istorie liniară. `pytest tests/` verde pe `main` **ÎNAINTE** de push: **3492 passed, 2 skipped**.
>
> **Poarta s-a deschis în aceeași dimineață**: `blend_v1/174e7e17` a atins **n = 204** cu **`baseline_source = 'shadow_control'`** (`challenger_evaluations` id=168, 17 oct 07:53:08), deci verdictul s-a născut cu universul VECHI și rămâne atribuibil — exact scopul pentru care merge-ul a fost ținut.
>
> **Verificat funcțional pe `main`, nu doar prin teste**: `TRACKED_COMPETITIONS` = **18**, `ODDS_SPORT_KEYS` = **16**, iar diferența e exact `['Conference League', 'HNL']`.
>
> **Două verificări de integritate ale merge-ului însuși**, fiindcă `main` avea deja cherry-pick-ul de pe 16 oct (`cb65111`), deci istoriile divergaseră:
> 1. Git a recunoscut singur commit-urile deja aplicate (`--cherry-pick` a exclus `29ac426` și `62b27b2`) — 10 commit-uri aduse, nu 12.
> 2. După rebase, `git diff 0aaf575 HEAD --stat` a ieșit **GOL** — deci rebase-ul nu a schimbat nicio linie de conținut, doar strămoșii. Verificat, nu presupus.
>
> Branch-ul a fost repus cu `--force-with-lease`; `main` nu a fost niciodată forțat.
>
> **CE AȘTEPTĂM ACUM** — cele 5 puncte din §„Ce se verifică la PRIMA rulare de noapte de după merge", mai jos, rămân valabile neschimbate. Prima rulare programată de după merge e cea de mâine dimineață (azi a rulat la 06:47, înainte de merge).
>
> **Ce NU repară merge-ul, și e corect așa** — măsurat pe 17 oct, înainte: din meciurile de sezon ale celor două ligi, doar **13** au rând `control` (2 din 147 Conference League trecute, 11 din 46 HNL trecute) — exact meciurile deschise manual în aplicație, fiindcă `app.py` pasa lista completă. Merge-ul acoperă imediat **31 de meciuri viitoare** (7 UECL + 24 HNL) și tot ce vine după. Cele ~180 de meciuri trecute rămân **definitiv** fără rând `control`: a le umple retroactiv ar însemna să generăm azi predicții pentru meciuri deja jucate, adică exact scurgerea temporală pe care North Star #7 interzice fără excepție. **Nu e o limitare de reparat, e o regulă respectată.**

### Istoric — de ce a fost ținut (păstrat ca atare)

> **Codul e gata, testat, pe branch. NU e pe `main`. Nu e din uitare — e sincronizare deliberată.**

### Ce s-a reparat

`log_challenger_shadow_for_week()` (batch-ul de noapte, ADR-056) chema `get_matches_for_week()` **fără `competitions`**, iar acela cădea pe `list(ODDS_SPORT_KEYS.keys())` — dicționar derivat care înseamnă „ligile acoperite de The Odds API", **16 din 18**.

Docstring-ul funcției promitea „evaluează **TOATE** meciurile descoperite". Codul acoperea 16 din 18.

**Costul măsurat, pe sezonul curent**: 198 de meciuri (**147 Conference League + 51 HNL**) fără niciun rând `control` — invizibile pentru radarul de value bets, absente din experimentul Challenger, neauditabile până la sursă (#9). Singurele 14 excepții erau meciuri deschise manual în aplicație, fiindcă `app.py` pasa lista completă. **De-asta a stat un sezon nedescoperit: pe ecran existau, în pipeline nu.**

Reparația: `mappings.TRACKED_COMPETITIONS` (derivat din `LEAGUE_PROVIDERS`, ADR-001), pasat explicit. Plus `value_selector_evaluation.py` raportează pe perioade, cu cutoff **dedus din date** (`detecteaza_cutoff()`), nu scris ca dată — exact ca să nu depindă de completarea unei constante la momentul potrivit.

**20 de teste noi, 8 mutații, toate prinse.** `pytest tests/`: 3474 passed, 2 skipped (3454 + 20, aritmetica se închide exact).

### DE CE nu e pe `main` — condiția de merge

**`blend_v1/174e7e17` e la n = 193, pragul e 200** *(actualizat 16 oct, după rularea `38895061622`; era 175 pe 15 oct)*. **Mai lipsesc 7 meciuri** — foarte probabil rularea de mâine dimineață. E la un pas de **primul verdict pe baseline-ul corectat ADR-072**, lucrul așteptat din 14 octombrie.

Reparația adaugă ~30 de meciuri pe săptămână în bazinul Challengerilor. Dacă intră acum, acel verdict se naște cu universul schimbat, și **nu se mai poate atribui**: baseline nou sau ligi noi? Două schimbări simultane, exact ce proiectul interzice.

> ### ✅ CONDIȚIE DE MERGE, verificabilă
>
> ```sql
> SELECT experiment_name, experiment_version, n_matches_evaluated, status
> FROM experiment_registry
> WHERE experiment_version LIKE '174e7e17%';
> ```
>
> **Când `n_matches_evaluated >= 200` ȘI există un rând în `challenger_evaluations` cu `baseline_source = 'shadow_control'` pentru acel `training_run_id` → se face merge pe `main`.**
>
> Dacă la 20 octombrie încă nu s-a întâmplat, se reverifică seria (poate ritmul a scăzut), nu se forțează.

### Ce se verifică la PRIMA rulare de noapte de după merge

1. `match_history.prob_home_pred` populat pentru Conference League și HNL (azi: **0 din 25**, respectiv **0 din 5** în fereastra de 7 zile).
2. Rânduri `control` în `shadow_predictions` pentru ambele ligi (azi: 0 și 2).
3. `home_data_quality` scris — azi e NULL pe 25/25 UECL, ceea ce face poarta radarului să dea `UNKNOWN`, deci nu selectează. Se închide singur.
4. Durata etapei „Challenger Shadow Batch": +19% așteptat (30 de meciuri peste 159). Marjă: ultima rulare 87 min din 180.
5. `detecteaza_cutoff()` întoarce run_id-ul primei rulări cu UECL/HNL — și raportul F2 capătă secțiunea `perioade`.

### Ce NU s-a atins deliberat

Ceilalți 5 apelanți care folosesc implicitul (`odds_persistence`, `weather_forecast`, `team_health`, `pre_match_odds`, unul intern). Reparația e chirurgicală, pe batch. Cotele ajungeau deja pentru ambele ligi pe calea Flashscore, care nu trece prin implicitul acela.

---

## 3quinquies. Calendarul campionatelor noi — fereastra e ACUM, nu „după F2"

Întrebarea proprietarului produsului, 15 oct: *„și campionate noi când mai putem adăuga? Așa nu stricăm mereu F2?"*

**Răspunsul scurt**: fereastra e deschisă **acum** și se închide când autorizăm F3. Nu peste luni.

> ### 📌 CÂND EXACT — întrebare pusă de două ori, deci răspunsul trebuie să fie o dată, nu un principiu
>
> **Imediat după primul verdict `baseline_source = 'shadow_control'`. Cel mai probabil 16 octombrie, în cel mai rău caz 19 octombrie.**
>
> Verificat, 15 oct: doar **doi** Challengeri sunt `EVALUATING` — `blend_v1/174e7e17` (n=175) și `xgboost_v1/dda4f7f3` (n=24). Restul sunt `REJECTED`/`PROMOTED` și nu mai sunt evaluați. Deci primul verdict pe baseline-ul corectat **trebuie** să vină de la `174e7e17`.
>
> Seria lui: 91 (11 oct) → 132 → 141 → 144 → 151 → 153 → 175 (15 oct) → **193** (16 oct). **Mai sunt 7.**
>
> *(Actualizat 16 oct. Între 15 și 16 n-a fost o rulare normală: cea de dimineață a fost anulată de incidentul TheSportsDB — §3septies — iar 193 vine din rularea manuală de după reparație.)*
>
> #### Confuzia care a făcut întrebarea să pară fără ieșire — și era a mea
>
> Amestecasem două sisteme diferite:
>
> | | Ce e | Blocant? |
> |---|---|---|
> | **Evaluarea Challenger** (ADR-072) | `174e7e17` atinge 200 și dă primul verdict pe baseline corect | **DA** — singurul blocaj real |
> | **F2 / F3** (ADR-071) | experimentul de politică al radarului | **NU** |
>
> **F2 nu blochează**: raportarea pe perioade (`detecteaza_cutoff()`) a fost construită azi exact ca să absoarbă lărgirea universului.
>
> **F3 nu e un termen care fugărește**: nu începe automat când „se termină F2". E o decizie, condiționată de o muncă neîncepută — colapsarea brațelor dovedit identice (13 profile → doar 7 seturi distincte de selecții). **Nicio tranziție automată, deci fereastra nu se poate închide din întâmplare.**
>
> Bucla „așteptăm F2 → începe F3 → deci niciodată" **nu există**. Singurul lucru care închide fereastra e decizia umană de a autoriza F3.

Motivul e cel din corectura de la §3ter: F3 cere *politică înghețată, fără ajustarea pragurilor pe parcurs, numărătoare curată de 150*. O ligă adăugată **în timpul** F3 strică exact asta. O ligă adăugată **înainte** e absorbită gratuit — numărătoarea care contează nici n-a început.

### Calendarul, derivat din distribuția lunară REALĂ a propriului istoric

| | Ian | Feb | Mar | Apr | Mai | Iun | Iul | Aug | Sep | Oct | Nov | Dec |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **Suedia** | 30 | 26 | 34 | **103** | **96** | 31 | **115** | **123** | **112** | **105** | 48 | 29 |
| **Norvegia** | 22 | 24 | 35 | **92** | **95** | 49 | **117** | **99** | 87 | **102** | 58 | 42 |
| Austria | 11 | 54 | 54 | 73 | 64 | 21 | 51 | 82 | 70 | 75 | 52 | 37 |
| Elveția | 49 | 55 | 46 | 66 | 75 | 26 | 70 | 47 | 54 | 75 | 44 | 48 |
| Danemarca | 21 | 49 | 52 | 72 | 67 | 21 | 85 | 85 | 64 | 67 | 43 | 29 |

Două regimuri, și dictează momente diferite:

- **Austria, Elveția, Danemarca** — calendar european cu pauză de iarnă. Adăugate acum, aduc meciuri imediat.
- **Suedia, Norvegia** — sezon aprilie–octombrie. Adăugate acum ar da ~3 săptămâni, apoi **cinci luni de tăcere**. Adăugate în **martie**, prind un sezon întreg din prima zi.

### Ordinea, cu motivul fiecărui pas

| Când | Ce | De ce atunci |
|---|---|---|
| ~~1-3 zile~~ **✅ FĂCUT 17 oct** | merge-ul din **§3quater** (`8b2fe2a`) | după primul verdict ADR-072, ca să nu confundăm cauzele — verdictul a venit în aceeași dimineață (n=204, `shadow_control`) |
| **🟡 URMĂTORUL PAS** | **Austria + Elveția + Danemarca**, ÎNTR-UN SINGUR LOT | fereastra pre-F3 e deschisă; un singur seam, nu trei. Precondiția (merge-ul) e îndeplinită. Cerut explicit de proprietarul produsului pe 17 oct: „să nu uiți și de adăugarea noilor campionate" |
| **martie 2027** | **Norvegia + Suedia** | să prindă sezonul de la început |
| după ambele | colapsarea brațelor identice (ADR-071 §F3) → **abia apoi** autorizarea F3 | F3 pornește pe univers stabil și pe politici genuin distincte |

**Aranjat așa, F3 nu se strică niciodată** — fiindcă nu începe decât după ce universul s-a așezat.

**Precondiție, nenegociabilă**: fiecare ligă intră cu slug Flashscore **verificat, niciodată ghicit** (precedentul e chiar Conference League, 5 august). Și fiecare intră în `LEAGUE_PROVIDERS`, deci automat în `TRACKED_COMPETITIONS` — nu mai există calea prin care o ligă e adăugată pe jumătate.

### ✅ Slug-uri Flashscore — VERIFICATE 2026-10-15, gata de folosit

Nivel B (titlul REAL generat de Flashscore, indexat — aceeași metodă cu care s-au adăugat ultimele 11 competiții). **Niciunul nu e ghicit din convenție.**

| Ligă | Slug | Titlul care îl confirmă |
|---|---|---|
| **Austria** | `("austria", "bundesliga")` | **✅ NIVEL A** — navigare live pe telefonul proprietarului produsului, 15 oct 21:07: `FOOTBALL > AUSTRIA > Bundesliga`, sezon 2026/2027, 31.07 → 22.05, etapa 9 cu meciuri reale (*SK Rapid–Hartberg* 16.10, *Salzburg–Altach* 18.10) |
| **Elveția** | `("switzerland", "super-league")` | **✅ NIVEL A** — navigare live, 15 oct 21:13: `FOOTBALL > SWITZERLAND > Super League`, sezon 2026/2027, 25.07 → 04.06, Round 11 (*Servette–Vaduz* 24.10, *Basel–Grasshoppers* 25.10) |
| **Danemarca** | `("denmark", "superliga")` | **✅ NIVEL A** — navigare live, 15 oct 21:12: `FOOTBALL > DENMARK > Superliga`, sezon 2026/2027, 24.07 → 03.06, Round 11 (*Horsens–Randers* 16.10, *FC Copenhagen–Aarhus* 18.10) |

**🔴 Capcană găsită la DOUĂ din trei, de reținut la implementare**: există și `austria/bundesliga-women`, și `switzerland/super-league-women` — competiții **diferite**, sub nume aproape identic. Plus `austria/admiral-bundesliga` (numele sponsorizat, arhivă 2021/22). Un slug ales „logic" putea nimeri campionatul feminin sau o arhivă moartă. Exact tiparul pentru care World Cup 2026 a fost EXCLUS (patru URL-uri conflictuale, Regula #8).

**Cât de reală e capcana — măsurat pe pagina live (Austria, 15 oct)**: bara laterală listează `Bundesliga`, `2. Liga`, `Regionalliga East/West/South/North`, `Regionalliga Play Offs`, `Burgenland`, `Karnten`, `Niederosterreich` și încă **9** ascunse sub „Show more" — peste **17 competiții austriece**, dintre care una singură e cea căutată. Sigla paginii spune „**ADMIRAL** Bundesliga", ceea ce explică varianta sponsorizată: numele comercial diferă de slug.

### ✅ Cotele 1X2 PER MECI — ÎNCHIS pentru Austria (nivel A, 15 oct 21:09)

Întâi lăsasem necunoscuta deschisă: pagina de competiție arăta „Winner Odds" cu trei case, dar acelea sunt cote la **câștigarea campionatului** — piață outright, nu ce folosim noi. Sursa reală a lui `odds_fallback_flashscore` e `/odds/?mid=X`, tab-ul de cote al **fiecărui meci** (`providers/flashscore/normalizer.py:960`).

Verificat pe meciul *SK Rapid – Hartberg* (16.10.2026, Round 9), pagină live:

| Casă | 1 | X | 2 |
|---|---:|---:|---:|
| Superbet | 1,27 | 5,90 | 8,10 |
| Unibet | 1,27 | 6,00 | 9,00 |
| Betano | 1,28 | 5,60 | 9,00 |
| MrBit | 1,26 | 6,33 | 8,50 |
| get's bet | 1,27 | 5,50 | 8,50 |
| NetBet | 1,22 | 5,50 | 7,70 |

**Șase case vizibile, plus „Show more".** Media măsurată a lui `odds_fallback_flashscore` peste toate ligile urmărite e **5,53 case/meci** — deci Austria e cel puțin la fel de bine acoperită ca ligile existente.

**Consecință: Austria NU are nevoie de cheie Odds API.** Lanțul de cote e complet pe calea Flashscore.

**Și structura întregului lanț e confirmată, nu doar cotele.** Tab-urile sunt `MATCH · ODDS · H2H · STANDINGS` — exact cele folosite la celelalte 17 competiții: `H2H` alimentează Level FS2 (forma echipelor fără campionat urmărit), `STANDINGS` alimentează `flashscore_standings_snapshot`, iar `ODDS` include `1X2 / OVER-UNDER / BTTS / DOUBLE CHANCE`. Breadcrumb `AUSTRIA > BUNDESLIGA · ROUND 9` confirmă legătura ligă↔meci folosită de Discovery.

**Danemarca, verificat identic** (*Horsens – Randers*, 16.10, Round 11): șase case cu 1X2 — Superbet 2,82/3,55/2,42 · Unibet 2,80/3,50/2,38 · Betano 2,80/3,60/2,40 · MrBit 2,75/3,60/2,36 · get's bet 2,77/3,40/2,38 · NetBet 2,75/3,51/2,32, plus „Show more".

**Elveția, verificat cu o nuanță care contează** (*Servette – Vaduz*, 24.10 — adică peste 9 zile): doar **4 din 6** case au cotat. Unibet și MrBit au căsuțele goale.

> **Nu e acoperire mai slabă, e alt moment al măsurării.** Tiparul e deja măsurat în propriile noastre date (15 oct): acoperirea cotelor crește spre fluier — **60,0% azi · 90,9% la +1 · 95,7% la +2**. O captură la 9 zile distanță arată mai puține case decât una la 1 zi, în orice ligă.
>
> Citită fără contextul ăsta, captura ar fi produs concluzia falsă „Elveția e mai slab acoperită". De aceea `sync_pre_match_odds` rulează 2×/zi — ca să prindă cotele când apar, nu o dată, devreme.

### Capcana competițiilor s-a confirmat în TOATE cele trei țări

| Țară | Competiții listate în bara laterală |
|---|---|
| Austria | `Bundesliga` · `2. Liga` · `Regionalliga East/West/South/North` · `Regionalliga Play Offs` · `Burgenland` · `Karnten` · `Niederosterreich` · **+9 ascunse** |
| Danemarca | `Superliga` · `1st/2nd/3rd Division` · `Betano Pokalen` (cupă) · **`A-Liga Women`** · **`B-Liga Women`** · `Danish Cup Women` |
| Elveția | `Super League` · `Challenge League` · `Promotion League` · `1.Liga Classic Group 1/2/3` · `1.Liga Classic Play Offs` · `Swiss Cup` · `1.Liga Classic Cup` · **`Super League Women`** · +1 |

În fiecare caz, o alegere „logică" avea mai multe ținte greșite decât corecte. Regula „verificat, nu ghicit" și-a plătit costul de trei ori.

**Detalii utile observate colateral** (pagina elvețiană de meci): secțiunea `MATCH INFORMATION` dă stadionul și capacitatea (*Stade de Genève*, 30.084), iar `FORM` dă poziția în clasament plus ultimele 5 rezultate (*Servette ?WLLWW, locul 6* · *Vaduz ?WLLWL, locul 10*) — exact ce alimentează cascada de formă.

### Observație colaterală, consemnată ca să nu fie redescoperită

Pagina de meci are „PREDICTED LINEUPS" cu filele `AVG. RATING · MARKET VALUE · AGE · HEIGHT`, și textul *„Official lineups expected 1 hour before kick-off"*.

A doua confirmă fereastra universală de ~1h documentată în august. Prima precizează un fapt din `CLAUDE.md`: acolo scrie că extracția noastră *„nu a colectat niciodată"* `market_value` — câmpul de care depinde formula de penalizare a accidentărilor. **Flashscore îl afișează**; lipsa e la noi, nu la sursă. Nu e o contradicție, e o precizare.

**NU redeschide calea accidentărilor** — aceea e închisă pentru alt motiv (Flashscore nu publică lista structurată a absenților, testat live pe 9 meciuri, 30 aug).

**Confirmare din conținut, nu doar din URL** — paginile listează meciuri reale din fereastra curentă: *Salzburg – Altach*, *LASK – Salzburg* (16-25 oct) · *Zurich – Luzern*, *Basel – Grasshoppers* (24-25 oct) · *Horsens – Randers*, *FC Copenhagen – Aarhus* (16-18 oct).

**Încrucișare independentă**: *FC Copenhagen*, *Aarhus*, *LASK*, *Salzburg* sunt exact cluburile pe care analiza cupelor din aceeași zi le identificase ca jucând în Europa fără campionat domestic urmărit. Două măsurători separate, același set.

**Risc rezidual, declarat**: nivelul B e mai slab decât A (navigare Playwright reală, imposibilă din sandbox). Riscul e strict la nivel de slug, nu de parser — acela e generic și dovedit pe 17 competiții. Se face o rulare `--dry-run` per ligă înainte de prima rulare live.

### ⛔ Ce rămâne NEverificat: cheile Odds API

Pentru niciuna dintre cele trei nu știm dacă The Odds API le acoperă. Nu se poate afla din sesiunea de dezvoltare: cheia nu e în container, iar răspunsul `/sports` **nu e în `api_cache`** (verificat, 0 rânduri). Cere un apel live `/sports?all=true` dintr-un workflow, cu cheia din secrete.

**Nu e blocant pentru predicții** — cotele ajung oricum prin `odds_fallback_flashscore`, care are 5,53 case/meci față de 1,57 la Odds API. Contează doar pentru a ști dacă liga apare și în `odds_history`.

---

## 3sexies. 🔴 O reparație declarată încheiată care NU și-a atins efectul — lecție de metodă

**ADR-071 §20, 6 septembrie**, descrie exact simptomul găsit pe 15 octombrie: HNL cu 0% în `odds_history`, cotele existând în `odds_fallback_flashscore`, meciuri *„excluse tăcut din radar și din F3 ca «fără cote», deși aveam cotele lor. 17% din setul experimentului, inclusiv o ligă întreagă."*

S-a reparat citirea cotelor (`_load_odds()` completează din fallback). S-a consemnat ca rezolvat.

**HNL a rămas la 0 în radar până pe 15 octombrie.** Măsurat pe fereastra 5 sep – 20 oct, adică strict DUPĂ acea reparație: **24 de meciuri, 24 cu cote în fallback, 0 în radar.** Cauza: lipsea cealaltă jumătate — rândul `control`, adică predicția însăși. Reparația acoperea cotele, nu predicția.

**Lecția, de aplicat la fiecare reparație de acum înainte**: o reparație se verifică prin **efectul observabil pe care îl promite**, nu prin faptul că modificarea a fost făcută. §20 promitea „HNL intră în radar". Nimeni n-a reverificat că intră. Defectul a rămas viu **39 de zile sub o etichetă de rezolvat** — mai greu de găsit decât dacă ar fi rămas nedocumentat, fiindcă documentul spunea că nu mai există.

Aceeași clasă cu: POC-ul API-Football declarat șters 34 de zile înainte de ștergerea efectivă · ADR-072 declarat „în producție" când era doar pe branch · `grep -c baseline_source → 7`, cifră pe care nicio comandă n-o întoarce.

**Verificarea cerută la merge-ul din §3quater** (punctele 1-3) e scrisă exact în forma asta: nu „am schimbat codul", ci „`prob_home_pred` e populat pentru UECL și HNL, azi 0 din 25 și 0 din 5".

---

## 3septies. ✅ **INCIDENT ÎNCHIS** — TheSportsDB a doborât `night_sync` (16 oct)

### Ce s-a întâmplat

Rularea `38864084314` a fost **ANULATĂ la plafonul de 180 de minute**, după 10 rulări consecutive de 80-105 min. Nu derivă graduală — salt brusc.

**Cauza, din `provider_call_log`**: TheSportsDB a trecut peste noapte de la 0-2 eșecuri/zi la **443 din 443**, HTTP **404** pe toate cele 4 rute `.php`. Codul nostru neatins (`main` la `dc34fff` din 15 oct).

Nu rețea (ar fi timeout), nu cotă (429), nu autentificare (403). URL-ul e `/api/v1/json/`**`3`** — cheia publică gratuită. O notă de versiune a unui proiect terț spune că TheSportsDB a oprit tier-ul gratuit; **neconfirmat oficial**, deci nu se citează ca fapt.

### Costul n-a fost eșecul, ci TIMPUL — și e D-9

Distribuția latențelor, strict bimodală:

| Latență | Apeluri |
|---|---:|
| sub 1 s | 327 (mediana 439 ms) |
| 1-20 s | **0** |
| 20-100 s | 110 |
| peste 100 s | 7 (maxim 120.480 ms) |

**117 apeluri (26%) au consumat 106 din cele 109 minute.** Exact D-9, diagnosticat pe 14 oct și nereparat: `timeout=12` pasat lui `requests` e timeout **între octeți**, nu total.

### Ce s-a măsurat înainte de orice propunere

Cerere explicită a proprietarului produsului: *„verifică, nu presupune"*, *„nu umple golurile din analiză prin deducere"*.

**1. Nivelul 4 al cascadei de formă (TheSportsDB) e atins de ZERO echipe.** Replicată condiția fiecărui nivel în SQL, pe cele **288 de perechi echipă-ligă** care joacă în următoarele 7 zile:

| Nivel | Echipe rezolvate |
|---|---:|
| Level DB (≥3 meciuri în ligă, 365 zile) | **256** (88,9%) |
| Level FS (clasamente Flashscore) | **32** |
| Level FS2 | 0 |
| rămân descoperite | **0** |
| **ajung la Level 4 (TSDB)** | **0** |

Rezervă onestă: o fereastră de 7 zile, nu un sezon. Dar marja e totală, nu la limită.

**2. Contribuția la descoperire e NEGATIVĂ, nu nulă.** Sezonul curent: Flashscore **1.817** rânduri, TSDB **29** (1,6%); ultima lună **623 vs 1**. Din cele 29, **15 n-au niciun rezultat** nici azi. Din cele 14 rămase, **13 au `home_xg_actual`** — câmp scris exclusiv de Flashscore — deci le văzuse și el.

**3. Mecanismul poluării, confirmat**: RPC-ul canonic face `COALESCE(existent, nou)`, deci cine creează rândul fixează **identitatea**. TSDB descoperă devreme, scrie `tsdb_*` cu grafia lui, Flashscore vine după și doar îmbogățește. Așa a apărut `Mjällby` lângă `Mjallby` — echipă cu **104 meciuri** în istoric sub cealaltă grafie.

### Reparația

`provider_kill_switch.py` — întrerupător **generic**, nu flag per provider: următoarea cădere nu va fi neapărat a lui TheSportsDB, iar un flag dedicat ar cere cod nou la fiecare incident, exact când nu e timp.

Poarta stă în `oracle_api._get()`, **punct unic** — toate cele 5 endpoint-uri trec prin el, deci unul adăugat mâine nu o poate ocoli. Plus scurt-circuit la nivel de etapă în `run_daily`.

`model_config.disabled_providers = ["thesportsdb"]`, activat 16 oct cu confirmare explicită. Amprentă verificată: 37 → **38 chei**, `md5(data − cheia_nouă)` **identică** (`573d54df5fa55df5865cb3b06def5614`).

**18 teste, 6 mutații, toate prinse.** `pytest tests/`: 3472 passed pe `main`.

### Rezultatul, măsurat pe rularea `38895061622`

| | Înainte | După |
|---|---:|---:|
| Durată | **180, anulată** | **47 min** |
| Apeluri `thesportsdb` | 443 (toate 404) | **0** |
| Meciuri în 7 zile | 153 | **153** |
| Cu predicție | 132 | **141** |
| `data_quality = live` | 122 | **131** |
| `data_quality = neutral` | 0 / 0 | **0 / 0** |
| Etapa 8 (Continuous Learning) | n-a apucat | **2 evaluări** |
| `n` pentru `174e7e17` | 183 | **193** |

**47 de minute, nu 80-105.** Rulările „normale" includeau deja cele ~26 de minute pe care D-9 le documenta ca pierdute pe acest provider chiar când funcționa. Fără el, rularea e **de două ori mai rapidă decât oricând în ultima lună**, iar calitatea a **crescut**, nu doar s-a păstrat.

### 🔴 Ce rămâne DESCHIS

1. **D-9 nereparat.** L-am **ocolit**, nu reparat. Următorul provider care cade face exact același lucru, iar întrerupătorul trebuie pornit **manual**. Reparația de fond rămâne un buget de durată totală per cerere — sau, mai ieftin și mai general, un întrerupător **automat** după N eșecuri consecutive într-o rulare. Azi nu există: `status_forcelist` nu include 404 și nu e niciun contor de eșecuri.
2. **TheSportsDB oprit, nu eliminat.** Codul e acolo, stins printr-o linie de configurație. Eliminarea definitivă scoate un provider din contractul de descoperire → **cere ADR** (regula #5). De făcut după o săptămână de rulări verzi.
3. **Resturile lui**: 15 rânduri fără rezultat, `Mjällby`/`Mjallby`, și ~~3 rânduri~~ **UN rând** SuperLiga care e meci de cupă etichetat greșit (`Petrolul – Afumați`, 2 oct). Nu se curăță nimic fără aprobare explicită.

   > **[CORECTAT 2026-10-16]** Scrisesem „3 rânduri". **Măsurat: unul.** Verificare: rânduri live SuperLiga din sezon cu o echipă absentă din clasamentul ligii (16 echipe, captură 15 oct) → **2 rezultate**, dintre care al doilea e `shadow-probe-d7954f76`, data-santinelă `2099-01-01`, artefact de diagnostic deja documentat în `CLAUDE.md` (`scripts/shadow_probe.py`, curățenie deliberat NEautomată) — **nu** un meci de cupă. Cifra „3" venea dintr-o numărare pe care n-am refăcut-o la scriere. `tsdb_2611284` e acum în `scripts/data_health_baseline.json`, cu motivul care distinge ce e STABILIT (Afumați nu e în clasament) de ce e doar plauzibil (că e Cupa României).

---

## 3octies. ✅ **Monitorul roșu a găsit o clasă de defect necunoscută** — dubluri de identitate între provideri (16 oct)

Declanșator: captură cu `check_data_health` roșu (rularea `38901865940`) și întrebarea „cum scăpăm de eroarea asta?".

**Răspunsul nu era „scădem pragul".** `CLAUDE.md` documentează că monitorul e „roșu zilnic prin design", iar tentația era să citesc asta ca explicație și să trec mai departe. Era greșit: raportul arăta **1 clasă din 6**, baseline-ul funcționa (7 amânări separate corect), iar cele 5 rânduri „NOI" erau **trei lucruri diferite**.

### Ce era, de fapt

| Rând | Diagnostic |
|---|---|
| `tsdb_2611284` Petrolul – Afumați, 2 oct | Etichetă de competiție greșită. Afumați nu e în clasamentul SuperLigii (16 echipe). → baseline, intrare **permanentă** |
| `odds_217a…` PSV – Heerenveen · `odds_eff2…` Galatasaray – Kasimpasa, 9 oct | Rândurile cu data **corectă**, fără rezultat — deși rezultatul era deja în propria noastră bază |
| `flashscore_plkwWY3D` 10 oct · `flashscore_ABvXMeTa` 10 oct · `flashscore_YiWPvQZg` 11 oct | **Placeholder-uri** din 7 septembrie, pentru aceleași trei meciuri |

Trei meciuri reale ocupau șase identități. Detectorul de duplicate nu le vedea: cheia lui e `(gazdă, oaspete, ZI)`, iar **ziua diferea** — invizibil prin construcție pentru singurul instrument care ar fi trebuit să le vadă.

### Care dată era corectă — și de ce a cerut TREI dovezi

Presupunerea obișnuită a proiectului („Flashscore are dreptate") e **falsă aici**:

1. Flashscore însuși, în tab-ul H2H (`flashscore_match_context`), dă toate trei pe **9 oct**: 2-2, 2-0, 3-1.
2. `home_xg_actual` are scriitor **unic** (Flashscore), și e populat pe rândul `odds` de 9 oct al lui Dortmund — deci Flashscore a scris acolo, nu pe rândul lui de 10 oct.
3. Aritmetica etapelor închide independent pe toate trei ligile (9 meciuri/etapă). 9 oct 2026 e **vineri**.

O singură dovadă n-ar fi fost de ajuns, și ăsta e exact argumentul contra automatizării (ADR-075 §5, opțiunea C respinsă).

### Cauza rădăcină — și unde NU e

`correct_flashscore_kickoff_if_mismatched()` (ADR-070) compară data scrapată cu cea stocată **pentru același `fixture_id`**. Odată ce alt provider a creat rândul cu data reală, `resolve_fixture_id()` întoarce `fixture_id`-ul ACELUIA, comparația dă egal, iar rândul placeholder **nu mai e vizitat de nimeni niciodată** (descoperirea privește doar înainte).

**Golul NU e în RPC.** Migrarea 049 are deja garda exactă — `reschedule_target_occupied`, rând nescris, vizibil. Diagnosticul meu inițial („trebuie un mecanism nou de supersedare") era greșit: **nu lipsește un mecanism de rezolvare, lipsește unul de observare.** Asta face problema mult mai mică decât părea.

### Ce s-a făcut

- **Date**: 3 placeholder-uri supersedate + 2 rezultate scrise, SQL arătat integral și confirmat explicit, gardă triplă pe fiecare instrucțiune, toate cinci atomic cu CTE-uri, `RETURNING` → exact 5 rânduri atinse, dovedit. Consemnat ca **excepție la ADR-036**, nu precedent (vezi ADR-075 §7).
- **Baseline**: `tsdb_2611284`, cherry-pick chirurgical pe `main` (`cb65111`, un fișier JSON, zero cod) — ca să NU se elibereze merge-ul din §3quater înainte de verdictul ADR-072.
- **Verificat**, nu presupus: replicarea logicii clasei 1 în SQL dă `NOU = 0`, total închis exact (27 = 0 recente + 8 cunoscute + 19 încheiate).

### ⏳ Decizie ADR-075 — **AMÂNATĂ EXPLICIT de proprietarul produsului (16 oct)**

`docs/00_GOVERNANCE/ADR-075-cross-provider-duplicate-identity.md`, **Proposed, zero cod**. Recomandare: **opțiunea A** (detector read-only). B = supliment, nu alternativă. C (supersedare automată) **respinsă**, cu precedentul migrării 049 citat.

> **Decizia de a nu decide, cu motivul exact.** Cuvintele proprietarului produsului: *„Nu știu ce decizie să iau... revenim după ce se împlinesc cele 200 de meciuri. Nu aș dori să stricăm ceva."*
>
> **Declanșator (ACELAȘI ca §3quater, deliberat):** `n_matches_evaluated >= 200` pentru `blend_v1/174e7e17` **ȘI** cel puțin un rând cu `baseline_source = 'shadow_control'`. Reminderul zilnic existent (10:47 Europe/Bucharest) a fost **extins** să aducă ambele puncte, în loc să se creeze un al doilea — două remindere pentru o singură poartă e exact felul în care unul începe să fie ignorat.

**Două precizări care trebuie repetate când subiectul revine, fiindcă prima e exact ce a produs ezitarea:**

1. **Opțiunea A nu poate strica nimic.** Zero scrieri, niciun scriitor nou, niciun contract atins, zero cod pe calea de predicție. Dovedit azi în practică: baseline-ul s-a dus pe `main` chirurgical (`cb65111`, un fișier JSON) fără să elibereze merge-ul din §3quater. Grija „să nu stricăm ceva" e legitimă în general, dar **nu se aplică la A** — iar faptul că a părut să se aplice e vina felului în care am împachetat A, B și C într-un singur ADR.
2. **Motivul REAL al amânării e ADR-075 §8**, nu riscul: nu s-a stabilit de ce colectarea Flashscore a ajuns la meciul Dortmund și nu la celelalte două. Dacă e o regulă de sărire pe care o controlăm noi, reparația corectă ar putea fi alta decât oricare dintre cele trei. **Deci ordinea corectă e: investigația §8 (read-only, nicio aprobare de scriere) → abia apoi decizia.** A alege între A/B/C înainte de §8 ar fi exact alegerea pe care proprietarul produsului a refuzat-o, pe bună dreptate.

**Ce mărginește costul așteptării — verificat, nu presupus:** monitorul `check_data_health` prinde **deja** această clasă. Pe 16 oct a prins **toate trei** cazurile, inclusiv pe cel al cărui geamăn canonic avea rezultat (`flashscore_plkwWY3D`). Prinde la ~6 zile după data meciului și cere diagnostic manual de fiecare dată — deci opțiunea A ar fi o **îmbunătățire de viteză și de claritate, nu închiderea unui gol**. Nu suntem orbi în timpul așteptării, doar lenți.

**Ce rămâne adevărat**: fără decizie, tiparul reapare la fiecare etapă descoperită devreme peste care alt provider scrie întâi — previzibil, nu accidental. Datele celor 3 cazuri sunt reparate; golul de **observare rapidă** rămâne deschis.

### Două lecții de metodă, ambele plătite în aceeași zi

**(a) Numărul de rânduri duplicate NU implică numărare dublă în statistică.** Raportasem că „F2 a numărat cele 3 meciuri dublu". **Greșit.** `rezultat_selectiei()` întoarce `None` la `actual_result` NULL, iar placeholder-urile n-au avut niciodată rezultat — deci cele 13 selecții de pe fiecare **n-au intrat niciodată în statisticile de selecții decise**, cele pe care se sprijină pragul F3 și ROI-ul. Dedup-ul pe `(policy_id, fixture_id)` plus poarta „fără rezultat = nedecis" filtrau deja fantomele. Afirmația de severitate venea din numărarea rândurilor, **înainte de a citi cum se consumă**.

Corolar util: scrierea de azi a **ajutat** F2 — a transformat 26 de selecții din nedecise în decise, cu rezultate reale pe selecții făcute înainte de meci.

**(b) „Protejăm F2" era atribuirea greșită, și confuzia era a mea.** Întrebat dacă așteptăm ca să protejăm F2, răspunsul corect e **nu**: așteptăm **primul verdict ADR-072** al lui `blend_v1/174e7e17` (n = 193, prag 200). F2 **nu blochează** — `detecteaza_cutoff()` a fost construit exact ca să absoarbă lărgirea universului. §3quinquies consemnează că amestecasem deja aceste două sisteme o dată, pe 15 oct; a doua instanță a venit din faptul că **eu** am scris „ca să protejăm F2" în mesajul anterior, iar proprietarul produsului l-a repetat. **O formulare greșită de-a mea devine convingerea lui în pasul următor** — motiv suficient să corectez atribuirea explicit, nu să confirm din politețe.

### Nedeterminat — nu se completează prin deducere

De ce colectarea Flashscore a ajuns la meciul Dortmund (`home_xg_actual` prezent) și **nu** la celelalte două (absent). Explică de ce unul avea rezultat și două nu, dar mecanismul nu a fost stabilit. **Contează pentru alegerea opțiunii**: dacă e o regulă de sărire pe care o controlăm noi, ar putea exista o reparație mai bună decât A, B sau C — una care duce rezultatul la rândul corect fără decizie umană. De investigat **înainte** de a implementa, nu după.

---

## 3nonies. ✅ **REZOLVAT (17 oct)** — `Salzburg` și `Red Bull Salzburg` erau același club

> **[ÎNCHIS 2026-10-17, în aceeași zi în care a fost găsit]** Decizie explicită a proprietarului produsului: canonic e forma **SCURTĂ**, `Salzburg`, cu argumentul *„important e cum vom colecta de acum înainte, nu cum a fost colectat"*.
>
> **Dovada care a închis discuția** a venit tot dintr-o captură: pagina de echipă Flashscore afișează `Salzburg` **în ambele competiții** — `AUSTRIA: Bundesliga` (Salzburg–Altach, 18.10) **și** `EUROPE: Europa League` (Celje–Salzburg, 22.10; Anderlecht–Salzburg, 05.11). Deci numele nu se schimbă cu competiția, iar Europa League e o competiție pe care o colectăm. Se potrivește cu istoricul: cele 110 rânduri `Salzburg` erau deja în `AUT | Europa League`, iar cele 23 `Red Bull Salzburg` **exclusiv** în Champions League, din `fd`/`kaggle`/`openfootball` — niciunul de la Flashscore.
>
> **Cod** (`7a72513`): `TEAM_ALIASES` — canonic `Salzburg`, cu `Red Bull Salzburg`, `FC Red Bull Salzburg`, `RB Salzburg` ca alias. Aliasul e necesar, nu cosmetic: `fd` (football-data.org) e **încă activ** în `sync_results` și ar rescrie forma lungă la următorul meci european.
>
> **Date**: 26 de rânduri, într-o singură instrucțiune atomică, cu `RETURNING` — `match_history` 12+11, `elo_ratings` 1, `scheduled_fixtures` 1, `tsdb_team_stats_snapshot` 1. Exact cifrele prezise. Verificat după: **0** rânduri rămase cu forma lungă pe toate cele 7 tabele, 133 de rânduri unificate peste 3 competiții, **0** duplicate pe cheia naturală create.
>
> **Cele 3 rânduri append-only n-au trebuit atinse** — erau deja pe forma scurtă. Asta a fost și argumentul decisiv al alegerii: forma lungă ar fi fost **imposibil** de dus la capăt.
>
> ### 🔴 Prima încercare n-a făcut NIMIC, și suita a rămas VERDE
>
> Adăugasem intrarea cu alias-uri lângă celelalte cluburi europene, fără să observ că mai jos exista deja `"Salzburg": []`. **Python păstrează ultima definiție a unei chei duplicate, fără eroare și fără avertisment** — deci harta inversă se construia din cea goală, iar `normalize_team_name("Red Bull Salzburg")` continua să întoarcă forma lungă. Niciun test n-a căzut.
>
> A ieșit la iveală doar fiindcă am verificat **rezultatul**, nu am presupus că editarea a avut efect. Scanat apoi tot fișierul prin AST: `TEAM_ALIASES` 389 de chei scrise / 388 unice — singurul duplicat era cel creat de mine, deci nu exista pierdere ascunsă dinainte.
>
> Două gărzi noi, una pentru cauză (chei duplicate, citite din SURSĂ prin AST — în dicționarul construit duplicatul e invizibil prin definiție) și una pentru efect (normalizarea chiar funcționează, pe toate cele 5 forme). Mutația care reintroduce duplicatul le doboară pe **amândouă**.
>
> ### Ce NU face, și rămâne deschis
>
> **Nu recalculează ELO retroactiv.** Identitatea e unificată, deci H2H găsește de acum cele 23 de meciuri de Champions League și ML vede un nume consecvent. Dar valorile `elo_after` din acele rânduri rămân cele calculate pe lanțul separat. Ratingul *curent* nu se schimbă — venea oricum din lanțul `Salzburg`, mai recent (2026-10-15 vs 2025-01-29). O recalculare completă e o discuție separată, **necerută**.
>
> **A doua instanță a clasei, găsită pe parcurs și NEreparată**: `scheduled_fixtures` are același meci de două ori — `Levski Sofia vs Red Bull Salzburg` și `PFC Levski Sofia vs Salzburg`, ambele 2026-09-17. Deci `Levski Sofia`/`PFC Levski Sofia` e o dublură proprie. Nereparată deliberat: ar fi fost extindere de scop fără verificarea ei.
>
> **Colateral util**: `Crvena Zvezda`/`Red Star Belgrade` — unul dintre candidații semnalați mai jos ca NEverificați — e **deja rezolvat** (`mappings.py:326`). RB Leipzig și Bayer Leverkusen rămân neverificați.

---

### Istoric — diagnosticul, păstrat ca atare

**Cum a ieșit la iveală** — merită reținut ca metodă: NU dintr-un monitor, ci dintr-o verificare colaterală. Proprietarul produsului a trimis capturi cu clasamentele celor trei campionate noi, iar din ele am putut compara numele reale de echipe cu istoricul nostru. `check_data_health` clasa 3 (forme abreviate) **nu** prinde cazul — a raportat 0 în aceeași zi. **A cincea oară** când observarea ecranului bate diagnosticul meu.

**Defect PREEXISTENT**, nelegat de adăugarea campionatelor; aceea doar l-a scos la suprafață.

### Amploarea, măsurată pe fiecare tabelă

| Tabelă | `Salzburg` | `Red Bull Salzburg` |
|---|---:|---:|
| `match_history` | 110 | 23 |
| `flashscore_match_context` | 32 | 0 |
| `shadow_predictions` | 17 | 0 |
| **`elo_ratings`** (ratingul CURENT) | **0** | **1** |
| **`elo_history`** | **96** | **0** |
| `flashscore_standings_snapshot` | 1 | 0 |
| `consensus_capture_samples` | 3 | 0 |

**Ruptura e în locul cel mai prost cu putință**: ratingul ELO curent există doar sub numele LUNG, iar toată istoria care l-ar justifica (96 de rânduri) e sub cel SCURT. Cele 23 de meciuri de Champions League formează un lanț ELO separat de cele 110 din campionat + Europa League, pentru același club.

### Ce face unificarea ușoară, și ce o complică

**Ușor, verificat**: zero coliziuni pe cheia naturală `(gazdă, oaspete, zi)` la redenumire, în oricare direcție. Niciun `UPDATE` n-ar eșua la mijloc — exact problema care a cerut grijă la unificarea din 23 august (coliziunea Rijeka–Dinamo Zagreb).

**🔴 Complicație, aceeași ca în august**: cele **3 rânduri din `consensus_capture_samples` NU pot fi atinse**. Tabela e strict append-only, impus de un trigger la nivel de bază de date — „o captură greșită nu se corectează, rămâne un fapt istoric". Orice monitorizare ulterioară trebuie să le **excludă**, nu să le raporteze ca rest necurățat. Identic cu cele 8 rânduri rămase abreviate după unificarea din august.

### Decizia cerută

Precedentul din **2026-08-23** (`Din. Zagreb`, `St. Mirren`, `St. Truiden`) a stabilit regula: **canonic e forma LUNGĂ, abrevierea devine alias**. Aplicată aici, ar însemna `Red Bull Salzburg` canonic, `Salzburg` alias — adică backfill pe **110 + 32 + 17 + 96 + 1 = 256 de rânduri**, plus o intrare în `TEAM_ALIASES`.

Dar regula aceea a fost stabilită pentru abrevieri (`Din.` → `Dinamo`). Aici forma scurtă e numele **geografic**, iar cea lungă conține numele **sponsorului** — nu e evident că precedentul se aplică mecanic. Flashscore însuși afișează `Salzburg` în clasamentul austriac (captură, 17 oct), deci forma scurtă e cea pe care o va scrie de acum înainte, zilnic.

**Nefăcut nimic deliberat.** Schimbarea identității unui club cere aprobare explicită — nu e o curățenie. Ambele variante sunt apărabile; decizia e a proprietarului produsului, nu mecanică.

**Impact cât timp rămâne nereparat**: ELO-ul lui Salzburg e calculat pe două serii care nu se întâlnesc. Afectează predicțiile pentru meciurile lui din cupele europene și din campionatul austriac nou adăugat. Nu e urgent — clubul are oricum ELO pe ambele lanțuri, deci nu cade pe `neutral-defaults` — dar e o valoare mai slabă decât ar putea fi.

**De verificat dacă mai există cazuri la fel**: căutarea de azi a fost punctuală (36 de echipe de pe trei ecrane). Un club care apare sub numele geografic într-o ligă și cu sponsor în alta e un tipar, nu un accident — RB Leipzig, Red Star/Crvena Zvezda, Bayer Leverkusen sunt candidați plauzibili, **NEverificați**.

---

## 4bis. De mâine, 15 octombrie — îmbunătățirea ML

**Punct de plecare: `ML_FUNDATIE_2026-10-15.md`.** Conține tot ce s-a măsurat pe 14 oct, ipoteza proprietarului produsului (istoric scurtat), grila de experiment 3×2, criteriul de succes stabilit înainte de rulare, și 6 capcane identificate.

Pe scurt, de ce: ML e la platou măsurat (acuratețe de validare 0,4834 → 0,4854 → 0,4853 în 5 săptămâni), fiindcă fiecare reantrenare adaugă **+1,0%** date noi. Iar distribuția pe care învață a derivat monoton din 2021.

Patru ipoteze, niciuna nu atinge Oracle: **H1** feature-uri de diferență · **H2** fereastră de istoric scurtată · **H3** ponderare după recență · **H4** eliminarea celor 4 feature-uri rare.

---

## 4ter. Slotul `value_selector_shadow` întârzie sistematic 5-10 ore (măsurat 15 oct)

**Context**: ecranul Top Value Bets a trecut pe **3 zile** (tab-uri Azi / Mâine / Poimâine, paginare per zi, `79a3604` pe `main`), iar colectorul de noapte pe `--days-ahead 3`. Verificând că zilele +1 și +2 chiar primesc rânduri, a ieșit la iveală altceva.

**Ora declarată e 09:40 UTC. Ora la care rularea chiar pornește, pe 6 zile consecutive:**

| Zi | Livrat | Întârziere |
|---|---|---:|
| 9 oct | 16:30 | 6h50m |
| 10 oct | 15:32 | 5h52m |
| 11 oct | 15:55 | 6h15m |
| 12 oct | 19:16 | **9h36m** |
| 13 oct | 17:06 | 7h26m |
| 14 oct | 14:38 | 4h58m |

**Vine în fiecare zi. Nu e abandonată niciodată.** E coada FIFO GitHub, fenomenul documentat în `CLAUDE.md` din august — dar până acum nu fusese măsurat pe acest workflow.

**Ce înseamnă practic, și de ce nu e urgent**: fereastra de `--days-ahead 3` acoperă de fapt **patru** zile calendaristice (azi..+3, fiindcă limita e `moment + timedelta(days=N)` cu filtru `<=`). A patra zi e exact marja care absoarbe întârzierea: ecranul are rânduri pentru toate cele trei zile afișate chiar și când rularea de azi n-a sosit încă. Alegerea s-a dovedit bună din alt motiv decât cel pentru care a fost făcută.

**Ce se degradează totuși**: prospețimea cotelor. Motivul de programare scris în antetul workflow-ului („09:40, DUPĂ `sync_pre_match_odds` de la 08:00, ca să fie cotele deja persistate") e corect ca intenție și fals în practică — rularea aterizează după-amiaza. **Nereparat deliberat**: mutarea orei declarate nu scurtează coada, iar fără măsurători pe mai multe săptămâni n-avem cum ști dacă ar ajuta. Aceeași disciplină ca la `live_sync` și `sync_pre_match_odds` în august — se măsoară întâi, se mută după.

**De urmărit**: dacă întârzierea depășește ~12 ore (adică rularea ajunge să nu mai prindă ziua pentru care colectează) sau dacă apare o zi cu **zero** livrare. Prima ar începe să conteze; a doua ar schimba diagnosticul din „întârziere" în „abandon".

### Lecția de metodă, plătită în aceeași zi

Afirmasem, și **apucasem să scriu într-un commit**, că slotul de azi „a fost ABANDONAT". Nefondat: verificasem la 13:33 UTC, adică **înainte de cea mai devreme oră la care rularea a sosit vreodată** (14:38). Din absența la un singur moment am dedus o stare terminală.

Proprietarul produsului a contestat („ba a rulat azi") și verificarea seriei i-a dat dreptate. **A treia instanță a aceleiași clase în trei zile** — un instantaneu citit ca o serie, exact eroarea din proiecția ADR-072, greșită de trei ori. Și a doua oară în aceeași zi când o concluzie a mea e răsturnată de observația proprietarului produsului asupra ecranului.

Corectura e scrisă *în* comentariul din workflow, nu înlocuită tacit — afirmația greșită e în istoricul git, deci cine o citește trebuie să dea și de dezmințire.

---

## 5. Ce NU se urmărește, deliberat

- **Precizia predicțiilor** — nu există azi o pârghie identificată și dovedită **pe Oracle**. Dar vezi `COMPARATIE_MOTOARE_2026-10-14.md`: Blend bate Oracle semnificativ la Brier și log-loss (t = −2,82 / −3,08) pe 998 de meciuri comune, și e singurul statistic indistinct de piață (z = 1,34, față de 1,96 pentru Oracle). NU trece poarta North Star #2 (acuratețea e nesemnificativă, z = 1,54), deci nu e promovabil azi — dar e cea mai concretă direcție măsurată. Oracle e la −1,98pp de piață pe 97,5% din meciuri, **statistic nesemnificativ** (z=1,35). Calibrarea e închisă ca pârghie. Accidentările au coborât în prioritate: ar afecta exact meciurile unde nu se vede headroom.
- **Team Profile** — D-7 închisă, reluare justificată abia la ~16 meciuri cu xG per echipă, estimativ februarie-martie 2027.
- **`weather_forecast_cache`** — gol acceptat explicit (decizie din 28 august).

---

## 6. Filtrul de formă în cupele europene — dovada cea mai tare de până acum, și prioritate SCĂZUTĂ (2026-10-19)

**Prioritizare explicită a proprietarului produsului, de respectat**: „competițiile
intercluburi nu-s atât de importante pentru mine, campionatele mă interesează
mai mult". Deci intrarea asta **nu se promovează singură în față** — e
documentată ca dovadă, nu ca sarcină următoare.

### Cazul

Sabah Baku – Borussia Dortmund, Champions League, 20 octombrie. Oracle:
**Sabah 56,3% / Dortmund 23,1%**. Piața: Dortmund la cota **1.33** (≈75%
implicit). Divergență de ~52 de puncte procentuale — cea mai mare măsurată în
proiect. Semnalată de proprietarul produsului **de pe ecran**, nu de vreun
monitor (a cincea oară când observarea ecranului bate diagnosticul meu).

### Mecanismul, măsurat linie cu linie

ELO-ul e CORECT și îi ordonează corect: Dortmund **1786**, Sabah **1588**.

| | Dortmund | Sabah Baku |
|---|---:|---:|
| multiplicator ofensiv din ELO | **1,2887** | 1,1603 |
| rating ofensiv FINAL (după blend) | **1,1303** | **1,4169** |

`compute_team_offdef_rating()` face `0,65 × statistici + 0,35 × ELO`, iar
`calibrate_xg()` **nu primește deloc ELO** — intră exclusiv prin acel blend.
Cele 35% nu pot răsturna cele 65%, iar ordinea se inversează.

**De ce statisticile mint aici**: filtrul e `.eq("league", league)`, deci
„ultimele 5 meciuri în Champions League". Dar:

- **Sabah** și-a făcut cifrele în **tururile preliminare** — 5-2 cu H. Beer
  Sheva, 4-0 cu Aarhus, 2-1 cu TNS, 2-0 cu KuPS. Total **12 goluri în 5 meciuri**
  = 2,4/meci, care **lovește plafonul de saturație** `min(avg_goals_for/2,0; 1,0)`
  și primește creditul ofensiv MAXIM posibil.
- **Dortmund** pe ale lui în **faza principală** — Inter, Atalanta, Villarreal,
  Bodo/Glimt. **6 goluri în 5 meciuri** = 1,2/meci, adică 60% din plafon. Trei
  din cele cinci sunt din **ianuarie-februarie, vechi de 8 luni**.

### A TREIA variantă a defectului, care nu era documentată

`EUROPEAN_COMPETITION_FORM_FILTER_DEFECT.md` descrie forma 1 (cădere pe
constante) și forma 2 (date reale dar vechi). Cazul ăsta le conține pe
amândouă, plus una nouă: **preliminariile și faza principală poartă aceeași
etichetă de competiție, dar sunt adversari incomparabili**. Filtrul care
trebuia să ajusteze la tăria adversarului face exact opusul — compară goluri
contra lui TNS cu goluri contra Interului, ca și cum ar fi același lucru.

### Cele două remedii NU sunt echivalente

1. **Repararea ferestrei** (filtru + legare de sezon + cale de rezervă, cele
   trei decise ÎMPREUNĂ, prin ADR) — atacă defectul.
2. **Mărirea `elo_blend_weight`** (0,35 → mai sus) — ar „rezolva" cazul, dar e
   **schimbare de model**, interzisă ca parte a unui fix de bug (regula din
   §Filosofia proiectului: orice modificare de parametru matematic e experiment
   de calibrare separat, cu aprobare proprie). Ar masca defectul reglând un
   buton.

**Recomandarea mea rămâne (1)** — dar dată fiind prioritizarea de mai sus, se
reia când campionatele domestice nu mai au nimic mai bun de oferit, nu acum.

### Colateral, de verificat când se ajunge aici

`Borussia Dortmund (GER)` există ca rând-fantomă cu ELO 1584, ultimul meci
**aprilie 2025** — a treia instanță a clasei de identitate duplicată, după
Salzburg (rezolvat) și `Levski Sofia`/`PFC Levski Sofia` (nereparat). Nu e
cauza acestui caz, dar e aceeași clasă.

---

## 7. 🔴 **~23 OCTOMBRIE** — decizia #8 se rezolvă singură, și până atunci NU se atinge (2026-10-20)

**Declanșatorul e o cifră, nu o dată**: `accuracy_significant` pe
`blend_v1/174e7e17`. Testul e binar, fără interpretare.

```sql
-- Starea deciziei + trendul tintei, intr-o singura citire
SELECT n_matches_evaluated AS n,
       round((delta_accuracy*100)::numeric,2) AS d_acc_pp, accuracy_significant,
       brier_significant, logloss_significant, verdict, evaluated_at::date AS zi
FROM challenger_evaluations
WHERE training_run_id = '174e7e17-347e-498e-912f-893a855f742b'
ORDER BY n_matches_evaluated DESC LIMIT 5;
```

### Ce așteptăm, și ce înseamnă fiecare rezultat

| Rezultat | Înseamnă | Acțiune |
|---|---|---|
| `accuracy_significant = true` | verdictul devine `candidate_for_promotion` | **NU aprobi #8** — întrebarea corectă devine promovarea. Dar vezi avertismentul de mai jos: azi, calea de promovare ar suprascrie tăcut #8. |
| rămâne `false`, Δ acuratețe **urcă** | încă nu, dar e pe drum | nu se atinge nimic |
| rămâne `false`, Δ acuratețe **scade** sub 2/3 semnificative | Challenger-ul s-a degradat | expirarea redevine justificată |

### Seria măsurată (de comparat, nu de reluat de la zero)

| n | Δ acuratețe | sig. | Brier sig. | log-loss sig. |
|---:|---:|:--:|:--:|:--:|
| 204 (17 oct) | +0,98pp | nu | nu | nu |
| 255 (18 oct) | +1,57pp | nu | nu | **DA** |
| 290 (19 oct) | +2,07pp | nu | **DA** | **DA** |
| **301 (20 oct)** | **+2,33pp** | nu | **DA** | **DA** |

Ritm ~27 meciuri/zi.

> **🔴 CORECȚIE, în aceeași zi (20 oct, seara) — estimarea „23-24 oct" era
> prea optimistă, și cifra pe care o citam era greșită.** Scrisesem că
> `8ac89c70` „a trecut toate trei la n=383". **Fals** — a trecut la **n=207**,
> de la prima evaluare (`challenger_evaluations`, 23 aug). 383 era `n`-ul lui
> din `experiment_registry` de AZI, adică de peste o lună mai târziu. Am
> confundat „unde a trecut" cu „unde e acum".
>
> **Reperul corect e mult mai puțin încurajator.** Punctele de trecere reale,
> pe toate seriile măsurate: `8ac89c70` la **207**, `4e17c737` la **329**,
> `6e7265c5` și `e638c1dc` **niciodată**. Deci `174e7e17`, la n=301, e încă
> în interval — dar dacă trece de **329** fără să atingă 3/3, iese din tot
> precedentul istoric.
>
> **Și precedentul direct e descurajant**: `4e17c737` a stat **13 din 15
> evaluări la exact 2/3, pe 14 zile**, a atins 3/3 o singură dată (n=329), a
> recăzut imediat și nu a mai revenit. Staționarea la 2/3 nu e o etapă spre
> promovare — e **starea de echilibru a unui Challenger mediocru** (Brier și
> log-loss sunt corelate între ele; acuratețea e metrica cu cel mai mult
> zgomot, plafonată la ~76% de remize).
>
> **Ce rămâne valabil**: #8 tot nu se atinge. Dar motivul se schimbă — nu
> „pentru că se rezolvă în 3 zile", ci **pentru că un verdict dat acum, în
> orice direcție, e luat în punctul cel mai puțin informativ al seriei.**
> Fereastra onestă e n≈450 (plafonul decis în ADR-079 §4.2), adică ~5-6 zile
> la ritmul măsurat: **26-27 octombrie**, exact la TTL.

### ⚠️ De ce #8 se lasă `pending`, deliberat — e o decizie, nu o amânare

Verificat în cod pe 20 octombrie, cele trei acțiuni posibile:

- **Aprobă** → `174e7e17` devine `REJECTED(expired)`, **stare terminală**, nu
  mai poate fi promovat niciodată. **Plus**: deschide calea prin care o
  promovare s-ar executa fără ca nimeni s-o fi aprobat (vezi ADR-079 §4.1).
- **Respinge** → `rejected` nu e stare „deschisă", deci rularea următoare
  propune #9, identică, în fiecare noapte cât `n ≥ 300`.
- **Nimic** → `pending` *este* stare deschisă, deci `propose_decision()`
  returnează #8 și `surface_decision()` refuză s-o reîmpingă. Zero zgomot.
  TTL-ul de 27 oct e inert, fiindcă `sweep_stale_decisions()` nu e cablată.

**A nu face nimic e singura acțiune care nu distruge nimic și nu generează
flux zilnic** — dar e un accident fericit, nu o proprietate proiectată.
ADR-079 o transformă în comportament intenționat.

### Legătura cu ADR-079 (PROPUNERE, cere aprobare)

`docs/00_GOVERNANCE/ADR-079-decision-lifecycle.md` acoperă toate trei fețele:
decizii care nu pot fi executate (#6, `approved` din 19 sept), nimic care
semnalează o decizie uitată (sweep necablat), și o decizie deschisă care își
poate schimba tăcut felul. **Până la aprobarea lui, riscul din §4.1 e activ**,
și singurul lucru care îl ține închis e faptul că #8 e `pending`, nu
`approved`.

### Gol găsit în propria reparație D-11, la o zi de la livrare

Calea de promovare (`continuous_learning._handle_candidate_for_promotion`)
**nu scrie niciodată `decision_kind`** — Faza C compensează cu un implicit
(`"promotion"`). Confirmat în date: decizia #3, promovarea lui `8ac89c70`
(23 aug), are câmpul NULL.

Deci o propunere de **promovare** — felul cu consecința cea mai mare — s-ar
afișa azi pe ecran ca **`FEL NECUNOSCUT`**, nu ca „PROMOVARE Champion".
Ecranul raportează fidel ce scrie în `evidence`; divergența e între ce scrie
și ce va executa codul. Reparația e o linie, în ADR-079 §4.3.

**De reținut ca metodă**: golul a ieșit la iveală pentru că D-11 a mutat
`decision_kind` din adâncul unui `st.json` în titlu. Cât era îngropat, nimeni
nu avea cum să observe că lipsește.

---

## 8. 🔴 **~07:20 UTC, 21 OCTOMBRIE** — prima rulare cu ADR-079. Nu a rulat încă NICIODATĂ.

ADR-079 a intrat pe `main` la **03:26 UTC pe 21 oct** (`3ff2f4d`). Ultima rulare
`night_sync` e **run 92, 20 oct 07:22**, pe `2d4092b` — dinainte de cod. Deci
totul despre ADR-079 se sprijină azi pe **39 de teste și 13 mutații**, nu pe
producție.

**De ce rularea de azi îl prinde, deși slotul e 02:00 și codul a intrat la
03:26**: din auditul propriu de throttling (29 aug) știm că
`created_at == run_started_at` în **20/20** de rulări — evenimentul însuși e
creat la **livrare**, nu la slot. Run 92: ambele la 07:22, adică 5h20m după
slot. Deci checkout-ul de azi se face pe `main`-ul de la ~07:20, cu ADR-079
inclus. **Dacă vreodată asta se schimbă (evenimentul creat la slot), prima
rulare cu ADR-079 ar fi cea de mâine** — de verificat `head_sha`, nu presupus.

### Ce se verifică, exact

| # | Verificare | Ce dovedește | Dacă nu apare |
|---|---|---|---|
| 1 | `summary.stale_orphaned = 1`, iar **#6** trece în `orphaned` cu `resolved_by = 'sweep-adr-026'` și `resolved_at` populat | §3.2 — sweep-ul e cablat **și** își datează rezolvarea | dacă `resolved_at` e NULL, defectul reparat la review s-a întors |
| 2 | **#8** rămâne `pending`; **zero** decizii noi pe `blend_v1\|all` | §4.1 + §4.2 — nimic nu se stivuiește, nimic nu se repropune | o decizie #9 = regula de trend nu s-a aplicat |
| 3 | `summary.expiry_skipped_trending = true` și `trend_significant_metrics = 2` | §4.2 — suprimarea e un **fapt consemnat**, nu absența unui fapt | tăcerea e exact defectul ADR-057 |
| 4 | orice propunere NOUĂ are `decision_kind` în `evidence` | §4.3 | absența = ecranul ar arăta `FEL NECUNOSCUT` |
| 5 | în aplicație: secțiunea „Aprobate, în așteptarea execuției" | §2 | — |

```sql
-- Verificarea 1+2+4, intr-o singura citire
SELECT d.id, d.status, d.resolved_by, d.resolved_at,
       r.producer, r.target_key, d.evidence->>'decision_kind' AS fel
FROM decision_feed d LEFT JOIN automation_runs r ON r.id = d.run_id
ORDER BY d.id;

-- Verificarea 3: rezumatul rularii de Continuous Learning
SELECT id, process_type, summary, created_at
FROM automation_runs
WHERE producer = 'ADR-030' AND created_at > '2026-10-21'
ORDER BY id DESC LIMIT 10;
```

### Ce e comportament PROIECTAT, nu regresie

- **#6 devine `orphaned`.** Decizie luată explicit pe 21 oct — vezi `BACKLOG`
  §1. `orphaned` e starea adevărată: aprobată, niciodată executată, eșec de
  producător (ADR-026). A o marca „executată manual" ar fi fost o afirmație
  falsă — nu s-a comutat niciun flag.
- **O propunere de consens NOUĂ, mai târziu.** `orphaned` nu e nici stare
  deschisă, nici în răcire, deci `consensus_validation` o poate repropune dacă
  verdictul rămâne `surface_worthy`. Asta e bucla care se vindecă, nu un
  duplicat.
- **Niciun rând nou în `challenger_evaluations` dacă `n` n-a crescut.**
  `UNIQUE (training_run_id, n_matches_evaluated)` + `ignore_duplicates` îl
  aruncă tăcut — mecanismul A2, cunoscut. Run 92 n-a produs niciun rând exact
  așa, la `n = 301` neschimbat. **Nu e un semn că evaluarea s-a oprit.**

### Ce rămâne deschis după rulare

- **Decizia #8** — nu se atinge până ~26-27 oct (plafonul n≈450, `DE_URMARIT` §7).
- **Discovery, de decis separat**: interogarea de idempotență din
  `propose_decision` citește `automation_runs` pe `target_key` **fără paginare**.
  Măsurat: maximul real **198** de rânduri, ~2/zi — plafonul PostgREST de 1000
  e la **~400 de zile**. A șasea instanță a clasei. Nereparat deliberat, cu
  comentariul la locul faptei; nu lărgesc scopul unui ADR aprobat din mers.
