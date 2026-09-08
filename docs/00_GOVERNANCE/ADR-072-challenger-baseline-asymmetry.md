# ADR-072 — Baseline-ul Oracle din poarta de promovare e înghețat, nu cel servit

## Status

**PROPOSED** — 2026-09-08. Cere aprobarea explicită a proprietarului produsului înainte de orice implementare.

Descoperit în timpul analizei critice a opțiunilor de persistare a intrărilor de la servire (discuție 2026-09-08). **Nu a fost căutat** — a ieșit la iveală verificând de ce o coloană `jsonb` nouă pe `match_history` ar îngheța.

## Context

### Ce face azi poarta de promovare

`shadow_testing.evaluate_experiment()` — funcția care decide dacă un Challenger e mai bun decât Oracle — compară două lucruri (`shadow_testing.py:484-485`):

```python
bp = (mh["prob_home_pred"], mh["prob_draw_pred"], mh["prob_away_pred"])   # baseline Oracle
ep = (shadow["prob_home"], shadow["prob_draw"], shadow["prob_away"])      # Challenger
```

`ep` vine din `shadow_predictions` — rând rescris de `log_shadow_prediction()` prin `upsert ... on_conflict`, deci **împrospătat în fiecare noapte** până la lovitura de start.

`bp` vine din `match_history` — coloane scrise prin RPC-ul canonic, care folosește `COALESCE(m.existent, p->nou)` (migrarea `053_upsert_canonical_restore_lost_columns.sql`, liniile 143-165). Semantica e **first-writer-wins**: odată ce coloana are o valoare ne-nulă, RPC-ul nu o mai poate actualiza niciodată.

Batch-ul de shadow (ADR-056) evaluează meciurile descoperite pentru **următoarele 7 zile**. Deci `prob_*_pred` se scriu la prima evaluare — cu până la o săptămână înainte de meci, cu cel mai slab profil disponibil — și rămân înghețate acolo.

**Comparația e asimetrică: Challenger proaspăt contra Oracle vechi de până la 7 zile.**

### Că diverg efectiv — măsurat, nu dedus

Pe 847 de perechi (același `fixture_id`, aceeași fereastră) între coloanele înghețate și rândurile `control` împrospătate:

| | |
|---|---:|
| perechi comparate | 847 |
| identice (<0,001) | 293 |
| **divergente peste 1pp** | **462** |
| divergență medie | 4,35pp |
| divergență maximă | **70,97pp** |

### Cât de mult contează — Oracle e handicapat, măsurat

Pe 468 de meciuri terminate din sezon (ligi domestice, profil informat):

| Oracle | Acuratețe | Log-loss | Brier |
|---|---:|---:|---:|
| baseline folosit azi la promovare (înghețat) | 0,4679 | 1,0413 | 0,6245 |
| ce servește Oracle de fapt (`control`, împrospătat) | **0,5107** | **1,0081** | **0,6021** |

Oracle real e mai bun pe **toate trei** metricile. Baseline-ul folosit îl subestimează cu **4,3 puncte procentuale** de acuratețe.

### Efectul asupra verdictelor REALE — aici e paguba

Recalculând deltele fiecărui Challenger contra ambelor baseline-uri, pe aceleași meciuri:

| Experiment | n | Δacc vs. ÎNGHEȚAT | Δacc vs. PROASPĂT | Δlog-loss vs. ÎNGHEȚAT | Δlog-loss vs. PROASPĂT |
|---|---:|---:|---:|---:|---:|
| `blend_v1 / 4e17c737` | 285 | **+0,0316** | **−0,0105** | −0,0433 | −0,0008 |
| `blend_v1 / 8ac89c70` | 376 | +0,0505 | +0,0346 | −0,0391 | −0,0177 |
| `xgboost_v1 / e638c1dc` | 543 | −0,0018 | −0,0313 | **−0,0134** | **+0,0143** |
| `xgboost_v1 / 6e7265c5` | 14 | 0,0000 | −0,1429 | −0,1302 | −0,0389 |

**Semnul se inversează în două cazuri, pe metrici diferite:**

- `blend_v1 / 4e17c737` pare că bate Oracle cu **+3,2pp** acuratețe; contra Oracle-ului real **pierde cu 1,1pp**.
- `xgboost_v1 / e638c1dc` pare mai bun la log-loss (−0,0134); contra Oracle-ului real e **mai slab** (+0,0143).

Baseline-ul înghețat **flatează sistematic Challenger-ul** în toate cele patru cazuri, fără excepție. Nu e zgomot — e o direcție unică, explicabilă mecanic: baseline-ul e o predicție făcută cu mai puțină informație.

### De ce e o încălcare de principiu, nu doar o imprecizie

- **North Star #2** — „promovarea cere dovadă statistică simultană pe metrici multiple". Dovada e produsă contra unui adversar handicapat, deci nu e dovada cerută.
- **North Star #9** — „orice rezultat trasabil complet până la sursă". Niciun rând din `challenger_evaluations` sau `experiment_registry` nu spune contra cărui baseline a fost calculat. Verdictele vechi și cele noi ar fi indistingibile.
- **ADR-002** — omul în buclă aprobă promovări pe baza acestor cifre. Cifrele îl induc în eroare într-o direcție constantă.

### Cauza probabilă — origine istorică, nu decizie

Nu există niciun comentariu sau ADR care să justifice alegerea `match_history` ca baseline. Explicația plauzibilă: rândurile `control` sunt mai recente (primele din 5-7 august 2026, ADR-056) decât mecanismul de evaluare, care avea nevoie de o sursă de baseline când ele încă nu existau.

Precedent deliberat: după episodul `.eq("league", league)` (`EUROPEAN_COMPETITION_FORM_FILTER_DEFECT.md` §8), regula e să nu declarăm defect ceva ce ar putea codifica o intenție necunoscută. **Aici s-a verificat**: docstring-ul lui `evaluate_experiment()` nu menționează alegerea, iar nicio regulă de domeniu nu justifică compararea unui model proaspăt cu unul vechi de 7 zile.

## Decizie

### D1 — Baseline-ul devine rândul `control` împrospătat

`evaluate_experiment()` folosește ca baseline rândurile `shadow_predictions` cu `experiment_group='control'`, `processing_stage='final'`, `invalidated_at IS NULL`, potrivite pe `(fixture_id, experiment_name, experiment_version)`.

`match_history` rămâne necesar în JOIN pentru `actual_result` și pentru `home/away_data_quality` (subsetul informat, ADR-065) — **nu** pentru probabilități.

### D2 — Sursa se decide PER EXPERIMENT, niciodată amestecată

Un verdict calculat pe baseline-uri mixte (unele proaspete, unele înghețate) e neinterpretabil. Regula:

- dacă **fiecare** meci `treatment` eligibil are un rând `control` pereche → sursă `shadow_control`;
- altfel → sursă `match_history_frozen` pentru **toate** meciurile, cu `WARNING` explicit în log.

Motivul concret, măsurat: `flashscore_team_dna / v1` are **711 rânduri `treatment` și 0 `control`**. O comutare necondiționată i-ar distruge complet evaluarea. Cu regula de mai sus rămâne funcțional, pe baseline-ul vechi, **etichetat ca atare** — nu tăcut.

Acoperirea pe experimentele de Challenger e completă azi, verificat: `xgboost_v1/e638c1dc` 682/682, `blend_v1/4e17c737` 439/439, `blend_v1/8ac89c70` 393/393, `xgboost_v1/6e7265c5` 167/167. **Zero meciuri pierdute prin comutare.**

### D3 — Sursa se ÎNREGISTREAZĂ, altfel n-am rezolvat trasabilitatea

Coloană nouă `baseline_source TEXT` (nullable, aditivă) pe `challenger_evaluations` și pe `experiment_registry`. Valori: `shadow_control` | `match_history_frozen`.

`NULL` pe rândurile existente înseamnă, prin construcție, `match_history_frozen` — se documentează, nu se completează retroactiv.

Fără D3, D1 ar repara cifrele dar ar lăsa exact golul de trasabilitate care a permis problema.

### D4 — Gatat de un flag nou, implicit OPRIT

`challenger_baseline_from_control_enabled`, implicit `False` (North Star #3). Activarea în producție e o decizie separată, cu confirmare explicită.

### D5 — Verdictele istorice NU se rescriu

Rândurile existente din `challenger_evaluations` rămân neatinse. Sunt fapte istorice despre ce s-a calculat atunci, nu pretenții despre adevăr — aceeași disciplină ca la `consensus_capture_samples` (append-only) și la ADR-060 (coloane derivate anulate, niciodată permutate).

Consecință acceptată conștient: seria `n_matches_evaluated` va avea o discontinuitate la activare. E preferabilă unei rescrieri care ar șterge dovada că problema a existat.

### D6 — Ce NU se face

**Nu se dezgheață `match_history.prob_*_pred`.** Ar cere schimbarea semanticii `COALESCE` în `_upsert_match_canonical_locked` — funcția atinsă de migrările 008, 036, 042, 048, 053, cea mai păzită cale de scriere din proiect, cu consumatori pe care acest ADR nu i-a auditat. Respins ca disproporționat față de problema rezolvată.

## Consecințe

### Pozitive

- Poarta de promovare compară două modele evaluate în același moment, cu aceeași informație. Asimetria dispare complet.
- Fiecare verdict viitor spune contra cărui baseline a fost calculat.
- Zero pierdere de acoperire pe experimentele de Challenger active (verificat, D2).
- Zero atingere a `match_history`, a RPC-ului canonic sau a vreunei căi de predicție live.

### Negative, acceptate

- **Verdictele devin mai severe.** Toate cele patru Challengere măsurate arată mai slab contra Oracle-ului real. `blend_v1/4e17c737` trece din „bate Oracle" în „pierde la acuratețe". E corectarea unei erori, nu o înrăutățire a sistemului — dar trebuie spus clar, fiindcă schimbă concluzii deja comunicate.
- **O afirmație existentă din `CLAUDE.md` devine imprecisă**: „azi: Oracle" ca lider empiric rămâne valabil, dar orice referire la blend ca depășind Oracle e dependentă de versiune (`8ac89c70` încă bate Oracle real: +3,5pp acuratețe, −0,018 log-loss; `4e17c737` nu). De actualizat printr-un amendament, nu tacit.
- **Discontinuitate în seria de evaluări** la activare (D5).
- **Gaura de acoperire rămâne**: dacă nicio familie n-are Challenger activ, rândurile `control` nu se scriu, iar D2 cade pe baseline-ul înghețat. Nu se rezolvă aici — se rezolvă prin decuplarea scrierii rândului `control` de existența unui Challenger, care e subiectul ADR-ului separat despre persistarea intrărilor de la servire.

### Descoperire în afara scopului, NEtratată aici (Discovery Rule)

`learning_core/champion_guardian.py` (liniile 253, 302, 318) și `prediction_evaluation.py` citesc **aceleași coloane înghețate** pentru a evalua sănătatea campionului activ și pentru raportarea de acuratețe a Oracle. Sunt afectate de aceeași staleness.

**Nu se extind în acest ADR.** Sunt consumatori distincți, cu semantici proprii neanalizate — pentru `prediction_evaluation.py` s-ar putea chiar argumenta că predicția „așa cum a fost văzută de utilizator" e cea corectă de raportat. Prezentate explicit proprietarului produsului ca descoperire, pentru decizie separată: în afara scopului, amendament, sau ADR nou.

## Verificare cerută înainte de activare

1. `pytest tests/` verde, inclusiv teste noi pentru: rezoluția sursei per experiment, refuzul amestecării, fallback-ul pe `flashscore_team_dna`, înregistrarea `baseline_source`.
2. Mutații verificate pe fiecare gardă (minim: sursa forțată la `shadow_control` fără acoperire completă; `baseline_source` nescris; potrivirea pe `fixture_id` fără `experiment_version`).
3. O rulare cu flagul oprit care demonstrează comportament **identic** cu cel de azi.
4. Migrarea coloanelor `baseline_source` arătată în SQL exact și confirmată explicit înainte de rulare (North Star #6, `supabase-safety`).

## Referințe

- `shadow_testing.py:425-510` — `evaluate_experiment()`, locul comparației.
- `database/migrations/053_upsert_canonical_restore_lost_columns.sql:143-165` — semantica `COALESCE` first-writer-wins.
- `oracle_engine.py:2109-2118` — comentariul care documenta deja capcana înghețării, pentru alt set de coloane.
- ADR-056 — batch-ul de shadow care evaluează cu 7 zile înainte.
- ADR-065 — subsetul informat, neschimbat de acest ADR.
- ADR-002 — omul în buclă la promovare.
