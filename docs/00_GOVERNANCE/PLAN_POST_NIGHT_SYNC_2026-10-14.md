# PLAN — ce se face după rularea `night_sync` 38509946577

**Scris 2026-10-14, ~04:30 UTC, în timp ce rularea încă merge.** Scopul e să existe
un punct unic de reluare dacă sesiunea se închide, contextul se pierde, sau pur și
simplu trece o zi. Nu duplică `BACKLOG_2026-10-13.md` — îl **ancorează în starea de
după activarea ADR-072**, cu cifrele de referință măsurate ÎNAINTE de rulare, ca
diferența să fie citibilă și nu reconstruită din memorie.

**Regula care guvernează tot documentul**: fiecare cifră de aici a fost măsurată, nu
estimată. Unde o proiecție e proiecție, scrie explicit.

---

## 1. Ce e rularea

| | |
|---|---|
| ID | **38509946577** |
| Declanșare | `workflow_dispatch` (manual), **nu** cron |
| Start | **2026-10-14 04:09:31 UTC** |
| Commit | `f21e5ac` (`main`) |
| `timeout-minutes` | 180 |
| Bloc `concurrency:` | **nu există** — două rulări *pot* se suprapune |
| Durată așteptată | ~100 min (rulările recente: 102, 126, 100, 111 min) |

**Trei lucruri intră în producție pentru prima dată în ea:**

1. **ADR-072 activ** — flagul `challenger_baseline_from_control_enabled` = `true`
   (boolean), scris pe 14 oct cu confirmare explicită.
2. **Instrumentarea HTTP** (`4417a8e`) — `_RetryCuJurnal` + `_raporteaza_daca_lenta()`.
3. **Fixul de paginare acumulativă** (`4897093`) — `_constructor()` în
   `backfill_features`.

**De ce a fost pornită manual și nu am aștepat cron-ul**: `schedule` suferă de o
coadă GitHub de ~7h (slotul de 02:00 livrat la 08:18 pe 10 oct → 08:35 → 08:56 →
09:11 pe 13 oct), iar `workflow_dispatch` pornește instant. Verificat că așteptarea
n-ar fi adus nimic: cele 15 meciuri de 14 oct au **0 rezultate** (se joacă seara),
deci între 04:09 și ~09:11 nu se termină niciun meci, iar `n` n-ar fi crescut.

**Rularea programată poate ateriza separat pe la ~09:11 UTC.** E inofensivă:
scrierea canonică e serializată de `pg_advisory_xact_lock`, toate tabelele au UNIQUE
+ `upsert`, iar suprapunerea reală din august a produs 0 dubluri. Verdictul ei va fi
probabil aruncat ca duplicat dacă `n` n-a crescut între timp — **normal, nu defect**.

---

## 2. Starea de referință, înregistrată ÎNAINTE de rulare

Fără tabelul asta, „s-a schimbat ceva?" devine o întrebare la care se răspunde din
memorie.

### 2.1 Flagul

| | |
|---|---|
| Chei în `model_config.data` | 35 → **36** |
| `md5(data)` fără cheia nouă | `0a169486d0bc26105443f6a0ab640d5c` — **identică** înainte/după |
| Valoarea | boolean `true` (nu șirul `"true"`) |
| Citit de | `shadow_testing.is_baseline_from_control_enabled()` → `bool(...)` |
| Flaguri vecine, neatinse | `challenger_expiry_proposals_enabled` `true`, `flashscore_kickoff_correction_enabled` `true`, `learning_core_enabled` `true`, `champion_guardian_enabled` ABSENT, `fdl_retention_delete_enabled` ABSENT |

### 2.2 `challenger_evaluations`

**113 rânduri, 0 cu `baseline_source`.** Ultima evaluare: 2026-10-13 21:09:08.

| Challenger | `n` înregistrat | Eligibile măsurate acum | Stare |
|---|---:|---:|---|
| `blend_v1/174e7e17` | 144 | **151** | `EVALUATING` — singurul activ |
| `xgboost_v1/6e7265c5` | 461 | 468 | `REJECTED`/`expired` — nu se mai evaluează |

### 2.3 `experiment_registry` — deltele de dinainte, pentru comparație

| Experiment | Status | `n` | Δ acuratețe | Δ log-loss | Δ Brier | Ultima evaluare |
|---|---|---:|---:|---:|---:|---|
| `xgboost_v1/6e7265c5` | `monitoring` | 461 | −0,01735 | −0,02472 | −0,01661 | 13 oct 21:09 |
| `blend_v1/174e7e17` | `insufficient_data` | 144 | NULL | NULL | NULL | 13 oct 21:08 |
| `blend_v1/4e17c737` | `monitoring` | 596 | +0,01174 | −0,03221 | −0,02010 | 13 oct 20:29 |
| `blend_v1/8ac89c70` | `candidate_for_promotion` | 378 | +0,05291 | −0,04019 | −0,02544 | **12 sept** |
| `xgboost_v1/e638c1dc` | `monitoring` | 550 | −0,00182 | −0,01571 | −0,00793 | **10 sept** |
| `flashscore_team_dna/v1` | `candidate_for_promotion` | 551 | +0,02904 | −0,02759 | −0,01820 | **10 sept** |

**Toate cu `baseline_source` NULL** — toate calculate pe baseline-ul ÎNGHEȚAT, deci
toate optimiste. Vezi §9 pentru tensiunea de la `flashscore_team_dna`.

### 2.4 Pragurile care decid (valori citite din cod, nu din memorie)

| Constantă | Valoare | Unde |
|---|---:|---|
| `MIN_MATCHES_FOR_EVALUATION` | **200** | `learning_core/continuous_learning.py:69` |
| `MIN_MATCHES_FOR_EXPIRY` | 300 | `learning_core/continuous_learning.py:78` |
| `MIN_SAMPLES_TO_TRAIN` | 30 | `ml_predictor.py:37` |

### 2.5 D-2 — starea `feature_metadata`

| Experiment / braț | Rânduri | Gol (`{}`/NULL) | Populat |
|---|---:|---:|---:|
| `blend_v1` control | 1298 | **1298** | 0 |
| `blend_v1` treatment | 1298 | **1298** | 0 |
| `xgboost_v1` control | 1307 | **1307** | 0 |
| `xgboost_v1` treatment | 1307 | **1307** | 0 |
| `flashscore_team_dna` treatment | 1167 | 0 | **1167** |

Ultimul rând e cel care contează pentru încadrare: canalul e **dovedit în producție**,
1167 rânduri adânc.

---

## 3. ⚠️ Descoperirea care schimbă așteptarea: `baseline_source` NU apare în această rulare

**Scrisesem la 04:11 că aștept `baseline_source = 'shadow_control'`. E greșit, și ar
fi dus la raportarea unui defect inexistent.** Corectat după citire de cod, înainte
ca verificarea să ruleze.

În `shadow_testing.evaluate_experiment()`:

- la **~linia 592**: `if n < min_matches:` → `_update_registry(..., status="insufficient_data", n_matches_evaluated=n)` și `return {"status": "insufficient_data", "n_matches_evaluated": n}`;
- la **linia 682**: `if baseline_din_control_pornit: result["baseline_source"] = baseline_source`.

Linia 682 e **după** `return`-ul de la 592. Deci **un verdict `insufficient_data` nu
poartă deloc câmpul `baseline_source`**, oricât de pornit ar fi flagul.

Singurul Challenger activ, `blend_v1/174e7e17`, ajunge la **n ≈ 151 < 200**, deci
rămâne `insufficient_data`. Challenger-ul `xgboost_v1` nou se naște în această rulare
cu `n` aproape zero. Rezultat:

> **Această rulare va produce ZERO valori de `baseline_source`, și asta e
> comportamentul CORECT.** Un `NULL` aici nu e dovadă că flagul nu e citit.

**Partea bună, care nu e evidentă**: rezoluția sursei se face **înaintea** pragului
(comentariul din cod o spune explicit: „ca decizia să depindă strict de acoperire, nu
de câte meciuri s-au adunat"), deci `_read_control_baselines()` **se execută** și în
rulările sub prag. Dacă citirea rândurilor `control` ar fi stricată, s-ar vedea în log
ca `[ShadowTesting] citirea rândurilor control a eșuat` — un canal de verificare real,
chiar fără verdict complet.

### Când apare primul `'shadow_control'` — proiecție măsurată, nu estimată

Din rândurile `shadow_predictions` ale lui `174e7e17` care așteaptă rezultat:

| După meciurile din | Devin eligibile | `n` cumulat proiectat |
|---|---:|---:|
| 14 oct | 15 | 172 |
| 15 oct | 27 | **199** ← sub prag cu UNU |
| 16 oct | 10 | **209** ← trece |
| 17 oct | 45 | 254 |
| 18 oct | 36 | 290 |
| 19-20 oct | 16 | 306 (total rânduri existente) |

**Primul verdict cu `baseline_source = 'shadow_control'`: rularea de 17 octombrie.**
Cea de 16 oct aterizează la ~199 — la un meci de prag, deci dacă apare orice fixture
nou sau un rezultat întârziat, se poate întâmpla cu o zi mai devreme. Proiecția
presupune că toate cele 15/27/10 primesc `actual_result` ȘI `prob_home_pred`.

---

## 4. Ce se verifică la finalul rulării

### 4.1 Rândul nou de evaluare — **n = 151**

```sql
SELECT training_run_id, n_matches_evaluated, evaluated_at, verdict, baseline_source
FROM challenger_evaluations ORDER BY evaluated_at DESC LIMIT 6;
```

- **n = 151, verdict `insufficient_data`, `baseline_source` NULL** → corect, mergem înainte.
- **n ≠ 151** → explicabil (rezultate sosite între timp). Nu e defect, dar se spune de ce.
- **rândul LIPSEȘTE și `n` a rămas 144** → **problemă reală**: verdictul a fost aruncat
  tăcut pe `UNIQUE (training_run_id, n_matches_evaluated)` + `ignore_duplicates`.
  Exact amendamentul A2. De raportat, nu de trecut cu vederea.

### 4.2 Faza B — Challenger `xgboost_v1` NOU

```sql
SELECT algorithm_family, left(training_run_id,8), state, rejection_reason, created_at
FROM challengers ORDER BY created_at DESC LIMIT 6;
```

**Predicție falsificabilă**: `_count_finished_matches('all', since=<created_at al
6e7265c5>)` = **485 meciuri** (măsurat: `actual_result IS NOT NULL AND kickoff_date >
'2026-09-06T18:34:44'`) contra pragului **30**. Deci Faza B **trebuie** să antreneze.
Dacă nu apare un `xgboost_v1` nou, e un defect, nu o așteptare.

Unde se caută motivul, dacă lipsește: `automation_runs`, `process_type` în
(`threshold_check`, `training_run`), `target_key = 'xgboost_v1|all'`. Raportează
mesajul exact, nu o ipoteză.

**Notă de precizie, fără impact azi**: `_count_finished_matches()` face un singur
`q.execute()` fără `.range()` → e **nepaginat**, deci plafonat tăcut la 1000 de
PostgREST (a treia instanță a capcanei). Inofensiv contra unui prag de 30, dar cifra
din mesajul logat devine falsă peste 1000. De reparat când se atinge, nu preventiv.

### 4.3 D-9 — punctul cel mai informativ al rulării

Descarcă **artefactul `logs/`** (API-ul GitHub întoarce doar ultimele ~5.000 de linii;
`night_sync` produce peste 100.000 — artefactul are tot). Caută `[HTTP-lent]` și
`[HTTP-retry]`.

**Întrebarea care decide, și singura care contează**: un `[HTTP-lent]` de ~120 s are
linii `[HTTP-retry]` imediat înaintea lui?

| Răspuns | Interpretare | Remediu |
|---|---|---|
| **DA** | bugetul de reîncercări e consumat, ultima reușește | timeout mai mic **scurtează**, fără pierdere de date |
| **NU** | o singură cerere care primește octeți prea rar ca să declanșeze timeout-ul `requests` (care măsoară **între** octeți, nu total) | timeout mai mic **NU ajută** și ar tăia cereri bune |

Datele de bază, măsurate: **96 de apeluri/săptămână** se termină între **120.160 și
122.699 ms** (abatere standard **577 ms** → plafon determinist, nu lentoare de rețea)
și **toate reușesc**. Aceleași endpoint-uri răspund normal în 343-508 ms. Bugetul
teoretic: `timeout=12` × 4 încercări + backoff ≈ **51,5 s**, nu 120 — de unde
întrebarea.

> **Niciun timeout nu se schimbă fără ca datele să fie arătate și decizia aprobată
> explicit.** Toate cele 96 de apeluri REUȘESC — o „optimizare" greșită aici
> transformă latență în pierdere de date.

### 4.4 Fixul de paginare

În log, URL-urile `match_history` emise de `backfill_features` nu trebuie să mai aibă
parametri duplicați (`offset=0&offset=1000&offset=2000...`). Înainte de fix, o rulare
reală ajunsese la **24 de perechi la offset=23000**.

### 4.5 Durata, pe etape

Raportul `step_durations_s`. Referință: 102 min ieri. De verificat dacă fixul de
paginare a scurtat ceva măsurabil (nu e garantat — câștigul e în lungimea URL-ului și
în eliminarea unei bucle infinite potențiale, nu neapărat în timp).

---

## 5. Ce devine posibil după — și ce rămâne blocat

### 5.1 ADR-073 / D-2 — reparația e un parametru

**Poarta reală rămasă**: confirmarea că poarta de promovare citește efectiv rândul
`control`, adică primul `baseline_source = 'shadow_control'`. Conform §3, **aceea e
rularea de 17 octombrie**, nu asta.

Până atunci, ADR-073 **nu se începe** — altfel am scrie intrările pe un rând despre
care încă nu avem dovada că decide ceva.

Diagnosticul, reverificat în cod 2026-10-14:

- `learning_core/challenger_shadow.py`: linia **111** folosește `features` pentru
  predicția Challenger-ului; liniile **118** și **126** (ambele `log_shadow_prediction()`)
  **nu pasează `feature_metadata`**.
- `learning_core/blend_challenger_shadow.py`: identic, liniile **131** și **139**.
- Golul se materializează în `shadow_testing.log_shadow_prediction()`:
  `"feature_metadata": feature_metadata or {}`.

Planul P1-P6: `BACKLOG_2026-10-13.md` §2. Punctul netrivial rămâne **P2**:
`ml_features` **nu e suficient** — lipsesc `baseline`-ul ligii și cele 5 ponderi
(`form_weight`, `base_weight`, `home_advantage`, `away_penalty`, `defensive_cap`),
deci reproducerea ar eșua dacă ponderile se schimbă. Descoperire de contract → intră
în ADR, nu se adaugă tăcut.

**Consecință pentru P6, de reținut**: scrierea e un `upsert` care rescrie, deci după
activarea flagului ADR-073 `feature_metadata` se populează de la sine **doar** pentru
meciurile încă reevaluate noaptea (fereastra ADR-056, 7 zile înainte). Meciurile deja
jucate rămân `{}`, și e corect — intrările de atunci nu mai există, iar recalcularea
lor azi ar fabrica o înregistrare, nu ar recupera una. Deci **testul de reproducere
din P5 nu are date reale imediat după activare**; are nevoie de câteva nopți de
acumulare. De planificat ca atare, altfel P6 pare eșuat când e doar prematur.

### 5.2 Promovări — ce se poate și ce nu

Niciun verdict existent nu e o bază validă de promovare: toate cele 6 rânduri din
§2.3 au `baseline_source` NULL, deci toate sunt calculate contra Oracle-ului înghețat
— care, măsurat pe 468 de meciuri, are **0,4679 acuratețe față de 0,5107 real**, un
handicap de **4,3pp** exact în comparația care decide promovările. Semnul se
inversează în **2 din 5** cazuri verificate.

**Regula operațională**: înainte de a aproba orice promovare pe o cifră mai veche de
14 octombrie, verdictul se **recalculează contra rândurilor `control`, read-only**.
Cele 113 rânduri vechi nu se rescriu retroactiv (ADR-072 §Consecințe — ar șterge
dovada că problema a existat).

---

## 6. Deciziile restante — ce decizie se cere, de la cine

| # | Subiect | Stare verificată 2026-10-14 | Decizia cerută |
|---|---|---|---|
| **D-3** | Consumatorii coloanelor înghețate: `champion_guardian.py` (253, 302, 318) și `prediction_evaluation.py` citesc aceleași `prob_*_pred` înghețate | NEtratați în ADR-072, deliberat | în afara scopului / amendament / ADR nou. Pentru `prediction_evaluation.py` se poate argumenta că predicția „așa cum a văzut-o utilizatorul" e cea corectă de raportat |
| **D-5** | `sweep_stale_decisions()` nu e apelată de nicio linie de producție — politica de staleness ADR-026 e cod mort | singurii apelanți: două teste | se cablează sweep-ul (TTL devine real, cu riscul de a auto-expira propuneri nevăzute) SAU se elimină TTL-ul și se înlocuiește cu o alertă. Ambele schimbă contractul ADR-026 → ADR |
| **D-6** | Două backup-uri cu revizuire programată depășită: `match_history_backfill_backup_20260822` (9,77 MB, termen ~21 sept) și `flashscore_match_context_retention_backup_20260826` (72 kB, ~25 sept) | zero referințe în cod, zero impact Oracle | „se păstrează mai departe" SAU „se șterg". **Niciodată curățenie tăcută** |
| **D-8** | `consensus_validation.py` nu are fază de execuție; `commit_decision()` e apelat exclusiv din `continuous_learning.py` | decizia **#6** e `approved` din 14 sept, **TTL depășit cu 22 zile și 12 ore**, imposibil de comis de orice cod existent | se implementează faza de execuție SAU se oprește producerea de decizii pe care nimeni nu le poate comite |

**D-4 e închisă în partea principală** (decizia #7 comisă, `6e7265c5` →
`REJECTED`/`expired`, campionul neatins), dar **efectul nu e încă dovedit** — asta se
confirmă prin §4.2. Coada ei (decizia #6) nu e o variantă a lui D-4: cauza e D-8.

---

## 7. Precizie — singura categorie care schimbă predicțiile servite

Nimic din §4-§6 nu schimbă o predicție. Concluzia de arhitect formulată pe 13
octombrie, pe dovezi, rămâne: **partea de modelare e tunată, pârghiile rămase sunt
toate pe date.** Cinci ablații consecutive, toate negative — ponderarea formei (13
variante), calibrarea xG, fereastra de antrenare ML, 6 feature-uri prin permutation
importance, Team Profile.

**Pârghia #1, neatinsă: accidentările.** `freelf_lineup_snapshot` are **0 rânduri**,
`team_health_snapshot` 188 echipe cu **0 accidentări**. Componenta poate ajusta xG-ul
cu până la **30%** (`MAX_TOTAL_TEAM_IMPACT = 0.30`) și e moartă de peste o lună —
fiecare meci e prezis ca și cum toate echipele ar avea lotul complet.

Calea verificată live și deschisă: **Transfermarkt prin Playwright standard** (același
tipar deja folosit în producție pentru Flashscore), cu coloana „Market value"
confirmată prezentă — exact câmpul pe care formula de penalizare îl cere și pe care
Flashscore nu-l publică. Dovada: rulările GitHub Actions `33372482351`, `33372940106`.

**Integrarea nu e planificată** — cere ADR pentru sursă nouă de date, mapare
Transfermarkt↔echipe canonice, cadență, gating. Amânată prin decizie explicită, de
reluat ca discuție proprie.

---

## 8. Tensiune nerezolvată, de lămurit înainte de orice decizie pe Team Profile

`flashscore_team_dna/v1` e `candidate_for_promotion` în `experiment_registry`, cu
**Δ acuratețe +2,90pp**, n=551. Dar **ablația rulată pe 13 octombrie a fost
NEGATIVĂ**: nicio variantă mai bună simultan pe toate trei metricile, cu degradare
**monotonă în doză** (log-loss +0,0543 la aplicare brută, |t| = 3,58).

**Nu afirm că se contrazic** — pot măsura lucruri diferite: experimentul shadow
loghează o predicție produsă de feature-ul Team DNA, iar ablația a simulat aplicarea
unui multiplicator de contracție peste xG-ul Oracle. Construcțiile diferă.

**Dar diferența trebuie lămurită explicit înainte de orice promovare**, nu rezolvată
prin alegerea cifrei convenabile. Agravant: `flashscore_team_dna` e singurul
`candidate_for_promotion` cu **0 rânduri `control` din 989**, deci singurul pe care
ADR-072 **nu îl poate verifica** — cade corect pe `match_history_frozen` (D2
funcționează), dar cifra lui rămâne produsă de baseline-ul care, în 4 din 5 cazuri
măsurate, flatează challenger-ul.

---

## 9. Ce NU se face

- **Nu se declară defect** pe `baseline_source` NULL în această rulare (§3).
- **Nu se schimbă niciun timeout** înainte de a citi liniile `[HTTP-retry]` și de a
  arăta datele (§4.3).
- **Nu se aprobă nicio promovare** pe o cifră calculată contra baseline-ului înghețat
  fără recalculare read-only (§5.2).
- **Nu se șterge niciun backup** fără decizie explicită (D-6).
- **Nu se începe ADR-073** înainte de primul `'shadow_control'` (§5.1).
- **Nu se aprobă nicio decizie din Decision Feed prin SQL.** Aprobarea e actul omului
  (ADR-002); se face din interfață, niciodată în numele lui.
- **Nu se rescriu retroactiv** cele 113 rânduri de evaluare vechi.
- **Niciun commit sau push fără cerere.** Branch de lucru:
  `claude/continua-faza-1-adr5-o52jat`; `main` are deploy automat pe Streamlit Cloud.

---

## 10. Lecția de metodă din chiar scrierea acestui document

Documentul a început ca o transcriere a check-in-ului programat la 06:15. Scriindu-l,
a ieșit la iveală că **punctul 1 al acelui check-in era greșit** — aștepta
`baseline_source = 'shadow_control'` într-o rulare în care e structural imposibil să
apară (§3). Dacă nu l-aș fi scris, verificarea de la 06:15 ar fi găsit `NULL`, l-ar fi
citit ca „flagul nu e citit", și aș fi pornit să repar un lucru nestricat — exact
tiparul alarmei false din 26 august (clasamente „învechite" cu 16-21 de zile, unde
timestamp-ul mințea și datele erau corecte).

**Regula generalizabilă**: o așteptare scrisă înainte de măsurătoare e verificabilă;
una ținută în cap nu e. Costul de a scrie „aștept X" explicit e că se poate dovedi
greșită — și ăsta e exact beneficiul.

Declanșatorul de check-in (`trig_01MR7GTvmRESD9iPJQuag8Um`) a fost corectat la 04:24,
înainte să pornească.
