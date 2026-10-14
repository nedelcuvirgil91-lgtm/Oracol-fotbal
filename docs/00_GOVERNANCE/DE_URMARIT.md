# De urmărit — listă vie

Un singur loc pentru „ce așteptăm, când, și ce înseamnă dacă nu vine". Se actualizează; nu e jurnal istoric.

Ultima actualizare: **2026-10-14, 21:40 UTC**.

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

## 1. Rularea `night_sync` 38620259384 — ADR-073, flagul oprit

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

**Contrapondere obligatorie**: `randuri` trebuie să **crească** (altfel rularea n-a scris nimic și testul e vid), iar `flashscore_team_dna` trebuie să rămână la zero goale (altfel am rupt canalul care funcționa).

**Dacă pică**: nu se activează nimic; se repară poarta întâi.

---

## 2. Cron-ul de la 02:00 UTC, 15 octombrie — efectul D-10

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

## 3. ~19-20 octombrie — primul verdict real pe baseline-ul corect

`blend_v1/174e7e17` trece pragul de 200 și produce primul `baseline_source = 'shadow_control'`.

Abia atunci ADR-072 e confirmat end-to-end, pe date reale.

**Până atunci, `baseline_source` NULL e CORECT, nu defect** — sub prag, verdictul iese pe return-ul devreme și câmpul nici nu se atașează.

**Proiecția „17 octombrie" din documentele anterioare e GREȘITĂ**, corectată aici: seria măsurată e 132 (12 oct) → 141 → 144 (13 oct) → **151** (14 oct), adică ~9,5/zi. De la 151 la 200 ies ~5 zile. Pauza internațională poate încetini.

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

---

## 5. Ce NU se urmărește, deliberat

- **Precizia predicțiilor** — nu există azi o pârghie identificată și dovedită **pe Oracle**. Dar vezi `COMPARATIE_MOTOARE_2026-10-14.md`: Blend bate Oracle semnificativ la Brier și log-loss (t = −2,82 / −3,08) pe 998 de meciuri comune, și e singurul statistic indistinct de piață (z = 1,34, față de 1,96 pentru Oracle). NU trece poarta North Star #2 (acuratețea e nesemnificativă, z = 1,54), deci nu e promovabil azi — dar e cea mai concretă direcție măsurată. Oracle e la −1,98pp de piață pe 97,5% din meciuri, **statistic nesemnificativ** (z=1,35). Calibrarea e închisă ca pârghie. Accidentările au coborât în prioritate: ar afecta exact meciurile unde nu se vede headroom.
- **Team Profile** — D-7 închisă, reluare justificată abia la ~16 meciuri cu xG per echipă, estimativ februarie-martie 2027.
- **`weather_forecast_cache`** — gol acceptat explicit (decizie din 28 august).
