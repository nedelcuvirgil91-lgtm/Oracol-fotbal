# Stare la 2026-10-14, seara — ce s-a făcut, ce se urmărește, ce rămâne

Document de lucru, nu ADR. Scris în timp ce rula `night_sync` **38620259384**, ca să nu se piardă contextul.

Celelalte două documente rămân valabile și NU sunt duplicate aici:
- `BACKLOG_2026-10-13.md` — lista completă, ordonată după cost real măsurat.
- `PLAN_POST_NIGHT_SYNC_2026-10-14.md` — arborele de decizie pentru rularea **38509946577** (de dimineață). Secțiunea §„Corecții" de mai jos îi corectează o proiecție.

---

## 1. Ce s-a lucrat azi după-amiază — ADR-073, complet

**Starea**: cod pe `main` (`15f7c38`, apoi `9a8c0f6` pentru documentație), **flag OPRIT**, deci producția e neschimbată.

Golul închis: intrările pe care Oracle le folosește la servire se calculau corect și se aruncau. `match_history` ține doar ieșiri; `shadow_predictions.feature_metadata` era `{}` pe toate rândurile `control`. Nicio predicție nu putea fi auditată până la intrările ei (North Star #9).

Cauza era **un parametru**: `challenger_shadow.py:111` folosește `features` pentru predicția Challenger-ului, dar niciunul dintre cele două apeluri `log_shadow_prediction()` nu pasa `feature_metadata`. Identic în `blend_challenger_shadow.py`.

### Trei cifre din planul preliminar care erau GREȘITE

| | În `BACKLOG` §2 | Real, măsurat |
|---|---|---|
| „cele 5 ponderi" | 5, per ligă | **9 valori, din 3 surse.** `defensive_cap` NU trece prin `resolve_league_weights()` — vine din ponderile globale (`oracle_engine.py:1540`) |
| volum | ~1,8 MB | **1065 octeți/rând** → 2,8 MB pe rândurile existente, **~5,5 MB/lună** în continuare |
| `ml_features["home_xg_pred"]` | o valoare | **două** — `_cache_prediction` pasează xG **pre**-accidentări (linia 2100), `_log_challenger_shadow` pe cel **post** (linia 2213) |

A treia e cea care contează. Penalizarea de accidentări stă **între** `calibrate_xg()` și Poisson. Azi pre și post coincid, fiindcă `freelf_lineup_snapshot` e goală — de aceea ambiguitatea a trecut neobservată luni de zile. O gardă de reproducere care ar fi presupus egalitatea ar fi trecut azi și ar fi căzut exact în ziua în care accidentările se cablează, iar partea greșită ar fi fost garda. Înregistrarea stochează ambele xG explicit, plus `xg_changed_after_injury_step`.

### Calea de predicție — dovedită, nu declarată

Refactorizarea lui `_calibrate_xg` atinge calea de predicție. Codul de dinainte (`git show HEAD:oracle_engine.py`) a fost încărcat ca modul separat și rulat în paralel cu cel nou, pe ponderile REALE din `weights.json`, peste **729.000 de combinații**: **zero divergențe, xG servit identic bit cu bit.**

### Două gărzi erau defecte, nu codul

Din 9 mutații, toate prinse — dar două doar **după** ce mutația a arătat că garda e oarbă:

- **M4 (poarta flagului ștearsă complet) a trecut nedetectată.** Garda folosea `AssertionError`, pe care `except Exception` din `_serving_record_if_enabled` îl înghițea, întorcând exact `None`-ul așteptat. **Plasa de siguranță a codului anula garda testului.** Reparată prin contor.
- Garda „adaptoarele nu citesc flagul" căuta numele ca text și a căzut pe **propriul docstring** care explica tocmai că nu-l citește. **A treia** instanță a clasei, după `pipefail` (27 aug) și numele de secrete (14 oct dimineața). Reparată prin AST.
- Colateral: un test care **trecea** nu dovedea nimic — patcha `FootballOracleEngine` în loc de fixtura `_Engine`, care copiază metodele la definirea clasei.

`pytest tests/`: **3427 passed, 2 skipped** (35 de teste noi).

---

## 2. Ce se verifică la terminarea rulării 38620259384

Pornită manual 14 oct **19:02 UTC**, pe `9a8c0f6c`. Prima rulare cu codul ADR-073 pe `main` și flagul oprit. Check-in programat 20:44 UTC.

### Criteriul principal — binar, nu depinde de niciun prag

`cu_schema_version` trebuie să rămână **0** peste tot.

```sql
SELECT experiment_name, experiment_group, count(*) AS randuri,
       count(*) FILTER (WHERE feature_metadata = '{}'::jsonb) AS metadata_gol,
       count(*) FILTER (WHERE feature_metadata ? 'schema_version') AS cu_schema_version,
       max(prediction_time) AS ultima_scriere
FROM shadow_predictions GROUP BY 1,2 ORDER BY 1,2;
```

**Stare de referință, măsurată ÎNAINTE (14 oct ~19:00 UTC):**

| experiment | grup | rânduri | `{}` | cu `schema_version` |
|---|---|---:|---:|---:|
| `blend_v1` | control | 1299 | 1299 | **0** |
| `blend_v1` | treatment | 1299 | 1299 | 0 |
| `xgboost_v1` | control | 1457 | 1457 | **0** |
| `xgboost_v1` | treatment | 1457 | 1457 | 0 |
| `flashscore_team_dna` | treatment | 1167 | **0** | 0 |

**Verdict**: fie și un singur rând cu `schema_version` înseamnă că poarta nu ține → se repară înainte de orice discuție de activare.

**Contrapondere obligatorie, altfel testul e vid**: `randuri` trebuie să **crească** (dovadă că rularea a scris efectiv), iar `flashscore_team_dna/treatment` trebuie să rămână la `metadata_gol = 0`. Dacă acela ar cădea la zero, ar însemna că am rupt canalul care funcționa, nu că poarta e etanșă.

**De ce contează că flagul chiar ține**: `challenger_shadow_logging_enabled` și `blend_challenger_shadow_logging_enabled` sunt AMBELE `true` în producție. Codul modificat **se execută** la fiecare meci. Singurul lucru care-l ține inert e poarta.

### Secundar, în aceeași rulare

- **ADR-072**: `baseline_source` rămâne NULL cât timp `n < 200`. **NULL sub prag e CORECT**, nu defect.
- **D-9**: a doua rulare cu instrumentarea HTTP. Artefactul `logs/` nu se poate descărca din containerul sesiunii (`blob.core.windows.net` blocat de politica de rețea), deci se măsoară din `provider_call_log`. Referință: 486 apeluri `thesportsdb`, 13 peste 100 s (120.355-120.912 ms), zero eșecuri, 89% din timp în 2,7% din apeluri.

---

## 3. Corecții la proiecții anterioare

**Primul `baseline_source = 'shadow_control'` NU e pe 17 octombrie.** Proiecția din `PLAN_POST_NIGHT_SYNC_2026-10-14.md` era optimistă.

Seria reală a lui `blend_v1/174e7e17`: **132** (12 oct) → **141** (13 oct, 10:31) → **144** (13 oct, 21:08) → **151** (14 oct, 08:51). Aproximativ **9,5/zi**. De la 151 la pragul de 200 ies ~5 zile → **19-20 octombrie**, și pauza internațională poate încetini.

Pentru `xgboost_v1/dda4f7f3` (născut la expirarea #7, `n = 0`) termenul e mult mai lung.

Corecția se notează, nu doar se înlocuiește cifra: altfel pe 17 octombrie absența lui `'shadow_control'` ar fi citită ca defect, și s-ar porni o investigație inutilă. Exact tiparul estimării Team Profile din august („finalul lui septembrie", corectată abia în octombrie).

---

## 4. Decision Feed gol — verificat, e normal, dar lanțul merită scris

Întrebare proprietar produs, de pe ecran: *„Nu mai există bara pentru promovarea altui champion. E normal?"*

**Da.** `app.py:1527` afișează exclusiv `status = 'pending'`. Starea reală a tabelei, toate cele 5 rânduri:

| id | status | fel | țintă | creată | rezolvată |
|---|---|---|---|---|---|
| 3 | `committed` | **promovare** | `8ac89c70` | 23 aug | 23 aug |
| 4 | `committed` | expirare | `e638c1dc` | 6 sep | 6 sep |
| 5 | `committed` | expirare | `4e17c737` | 10 sep | 19 sep |
| 6 | `approved` | **(absent ⇒ promovare)** | — | 14 sep | 19 sep |
| 7 | `committed` | expirare | `6e7265c5` | 21 sep | **13 oct** |

Zero `pending` ⇒ feed gol. Corect.

**O bară de promovare a existat exact o dată**: decizia **#3**, 23 august, pentru `blend_v1/8ac89c70` — care E campionul activ de azi.

**Bara aprobată pe 13 octombrie era #7, o EXPIRARE**, nu o promovare (D-11).

### De ce nu poate apărea una nouă acum — mecanic, nu defect

O promovare se propune exclusiv când `verdict == "candidate_for_promotion"` (`continuous_learning.py:251`), ceea ce cere `n ≥ 200` **și** Brier + log-loss + acuratețe *simultan* semnificative. Azi:

- `xgboost_v1/dda4f7f3` → **n = 0** (abia născut, după expirarea #7)
- `blend_v1/174e7e17` → **n = 151**

Ambele `insufficient_data`. Feed-ul gol e **consecința așteptată** a aprobării expirării: slotul blocat s-a eliberat, Challenger-ul nou s-a născut la zero, și acum trebuie să acumuleze.

### Două observații colaterale, NEtratate deliberat

**(a) Campionul activ a fost promovat pe baseline-ul ÎNGHEȚAT.** Dovada deciziei #3 conține `accuracy_baseline: 0.4348` — banda Oracle-ului înghețat (0,4679 măsurat), nu a celui real (0,5107). Deci `delta_accuracy: +7,73pp` e produsă de comparația pe care ADR-072 o corectează. Intră în avertismentul standing („orice cifră dinainte de 14 oct rămâne de recalculat"), dar merită spus explicit că se aplică **campionului care servește acum**. Nu e un motiv de rollback — e un motiv să nu se citeze acel `+7,73pp` ca fapt.

**(b) Decizia #6 nu are `decision_kind`, iar codul tratează absența drept „promotion"** (`continuous_learning.py:800`: `evidence.get("decision_kind", "promotion")`). Evidența ei e `surface_worthy` / `agreement_score`, fără niciun `training_run_id`. D-8 spune corect că nu poate fi comisă — `commit_decision()` e apelat exclusiv din `continuous_learning`, iar `consensus_validation` nu are fază de execuție. Dar combinația „decizie de consens + implicit promovare + țintă absentă" e o capcană latentă, nu doar o decizie orfană.

**Discrepanță minoră găsită**: `CLAUDE.md` D-8 spune `study_run_id: 1072`; valoarea reală în tabelă e **1104**.

---

## 5. Ce mai e de făcut, în ordinea în care are sens

### Imediat, dependent de rularea curentă

1. **Verificarea de la §2** — flagul ADR-073 ține sau nu.
2. Dacă ține: o a doua rulare nu e necesară. Urmează `UPDATE model_config` pentru activare, **arătat și confirmat explicit** (North Star #6).

### Următoarele 5-7 zile, fără acțiune din partea noastră

3. `blend_v1/174e7e17` trece de 200 pe ~19-20 oct → primul verdict real pe baseline-ul `control` (`baseline_source = 'shadow_control'`). Abia atunci ADR-072 e confirmat end-to-end.

### Datorie de guvernanță, neschimbată, niciuna urgentă

| | Ce | De ce nu s-a făcut |
|---|---|---|
| **D-3** | consumatorii coloanelor înghețate (`champion_guardian`, `prediction_evaluation`) | decizie necerută; pentru `prediction_evaluation` se poate argumenta că predicția „așa cum a văzut-o utilizatorul" e cea corectă |
| **D-5** | `sweep_stale_decisions()` nu e apelată de nicio linie de producție | ambele variante schimbă contractul ADR-026 ⇒ cer ADR |
| **D-6** | două backup-uri cu revizuire restantă (9,77 MB + 72 kB) | nu se șterge nimic fără aprobare explicită |
| **D-8** | `consensus_validation` fără fază de execuție ⇒ #6 orfană pe veci | vezi §4(b) — acum are și o capcană latentă în plus |
| **D-10** | evaluarea generică vede 2 experimente din 6 (plafon PostgREST) | **schimbă cifre pe care se iau decizii**; nu se repară înainte de a decide ce se face cu D-7 |
| **D-11** | Decision Feed nu numește acțiunea aprobată | atinge calea de aprobare umană (ADR-002) |

**Niciuna nu schimbă o predicție.** D-10 și D-11 sunt cele cu cea mai mare valoare per efort: D-10 fiindcă azi sistemul afirmă simultan că `blend_v1/8ac89c70` e `candidate_for_promotion` ȘI `PROMOTED` ȘI campion activ; D-11 fiindcă același ecran va servi și propuneri de promovare și de rollback, iar §4 arată că confuzia s-a produs deja o dată.

### Precizie a predicțiilor — reîncadrat azi, nimic urgent

Reperul extern (`CLAUDE.md` §„Reperul extern") arată Oracle la **−1,98pp de piață pe 97,5% din meciuri, statistic nesemnificativ** (z=1,35). Calibrarea e închisă ca pârghie (erori sub ~1,3σ pe șase găleți). Accidentările au coborât în prioritate: ar afecta exact meciurile unde nu se vede headroom. Cascada de formă e închisă în mare parte (FS2 acoperă 57/57 meciuri de cupă viitoare).

**Nu există azi o pârghie de precizie identificată și dovedită.** Asta e o concluzie măsurată, nu o lipsă de idei — și e de reținut înainte de a porni un proiect mare pe intuiție.
