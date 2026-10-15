# De urmărit — listă vie

Un singur loc pentru „ce așteptăm, când, și ce înseamnă dacă nu vine". Se actualizează; nu e jurnal istoric.

Ultima actualizare: **2026-10-15, 16:10 UTC**.

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
| **ADR-074** — istoric de cote din Flashscore | aprobarea ta; apoi implementare **după** pragul F2 | PROPOSED, zero cod. Flashscore dă deja 5,53 case/meci vs. 1,57 la Odds API și acoperă UECL+HNL; singurul lucru care lipsește e mișcarea cotei, și aia e o limită de stocare (suprascriem, 7416 capturi din 7416), nu de provider. Fluxul colectează datele de 2×/zi și le aruncă. |
| **Campionate noi** (Austria, Danemarca, Elveția, Norvegia, Suedia) | nimic până după §3quater | Analiza din 15 oct: 133 din 206 echipe de cupă n-au campionat urmărit. **Dar nu se adaugă nimic înainte de merge-ul din §3quater** — o ligă nouă neacoperită de Odds API ar cădea în exact aceeași capcană și ar fi adăugată pe jumătate, ca UECL în august. Nordicele au bonus de calendar (mar-nov, acoperă iulie). |

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

## 3ter. **26-29 octombrie** — primul verdict F2 cu eșantion suficient (ADR-071)

Citit prima dată pe 15 octombrie, la cererea proprietarului produsului („hai să vedem ce profil câștigă la F2").

### Verdictul de azi: NU se poate declara un câștigător

ADR-071 cere **150 de selecții decise** per politică (`PRAG_ESANTION_MINIM`). Niciuna dintre politicile de radar nu a ajuns: maximul e **124**. Raportul oficial marchează `esantion_insuficient` pe toate.

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

## 3quater. 🔴 **MERGE ÎN AȘTEPTARE** — reparația competițiilor, scrisă dar NEmergeuită

> **Codul e gata, testat, pe branch. NU e pe `main`. Nu e din uitare — e sincronizare deliberată.**

### Ce s-a reparat

`log_challenger_shadow_for_week()` (batch-ul de noapte, ADR-056) chema `get_matches_for_week()` **fără `competitions`**, iar acela cădea pe `list(ODDS_SPORT_KEYS.keys())` — dicționar derivat care înseamnă „ligile acoperite de The Odds API", **16 din 18**.

Docstring-ul funcției promitea „evaluează **TOATE** meciurile descoperite". Codul acoperea 16 din 18.

**Costul măsurat, pe sezonul curent**: 198 de meciuri (**147 Conference League + 51 HNL**) fără niciun rând `control` — invizibile pentru radarul de value bets, absente din experimentul Challenger, neauditabile până la sursă (#9). Singurele 14 excepții erau meciuri deschise manual în aplicație, fiindcă `app.py` pasa lista completă. **De-asta a stat un sezon nedescoperit: pe ecran existau, în pipeline nu.**

Reparația: `mappings.TRACKED_COMPETITIONS` (derivat din `LEAGUE_PROVIDERS`, ADR-001), pasat explicit. Plus `value_selector_evaluation.py` raportează pe perioade, cu cutoff **dedus din date** (`detecteaza_cutoff()`), nu scris ca dată — exact ca să nu depindă de completarea unei constante la momentul potrivit.

**20 de teste noi, 8 mutații, toate prinse.** `pytest tests/`: 3474 passed, 2 skipped (3454 + 20, aritmetica se închide exact).

### DE CE nu e pe `main` — condiția de merge

**`blend_v1/174e7e17` e la n = 175, pragul e 200.** E la 1-3 zile de **primul verdict pe baseline-ul corectat ADR-072** — lucrul așteptat din 14 octombrie.

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
