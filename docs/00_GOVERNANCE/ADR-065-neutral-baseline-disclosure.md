# ADR-065 — Divulgarea meciurilor cu baseline neutru în evaluarea Challenger

**Status**: Accepted (2026-08-23)
**Atinge contractul**: `shadow_testing.evaluate_experiment()`,
`learning_core/challenger_evaluation.py`, tabela `challenger_evaluations`
**Nu atinge**: criteriul de promovare (North Star #2), pragurile statistice,
`MIN_MATCHES_FOR_EVALUATION`

---

## Context

Oracle Engine produce o predicție și atunci când nu are date despre echipe.
Starea e marcată corect și explicit: `home_data_quality = 'neutral'`,
`away_data_quality = 'neutral'`, iar UI-ul afișează eticheta
(`app.py:590,603`). Nu se aproximează nimic tăcut — Regula #8 e respectată.

Consecința matematică: cu toate intrările la valori neutre,
`feature_engine.calibrate_xg()` produce **aceeași valoare pentru orice meci**
din acea competiție. Verificat: Champions League — 18 rânduri, o singură
valoare (0,8672); Europa League — 26 de rânduri, o singură valoare (0,7835).
Raportul casă/deplasare e identic în ambele (1,1264 = `home_advantage /
away_penalty`).

**Golul**: `shadow_testing.evaluate_experiment()` **nu consultă
`data_quality`**. Meciurile complet neutrale intră în comparația
Challenger ca și cum baseline-ul ar fi fost informat.

Asta nu e o simetrie inofensivă. Pentru acele meciuri baseline-ul Oracle e o
**constantă**, în timp ce experimentul (ML sau blend) poate avea ELO și alte
feature-uri reale. Comparația nu e „ambii orbi" — e „baseline orb, experiment
posibil nu".

### Măsurat (2026-08-23, read-only, calcul replicat)

Populația de evaluare: **43 din 235 de meciuri (18,3%)** au ambele echipe
neutrale — 129 de rânduri shadow din 703.

**`xgboost_v1` / `all` (`e638c1dc…`, EVALUATING):**

| Populație | n | Brier | Log-loss | Acuratețe |
|---|---|---|---|---|
| Toate | 234 | 0,6465 → 0,6329 | 1,0725 → 1,0514 | 0,4444 → **0,4615** |
| Fără neutrale | 191 | 0,6432 → 0,6324 | 1,0688 → 1,0511 | **0,4660** → 0,4450 |
| Doar neutrale | 43 | 0,6609 → 0,6350 | 1,0890 → 1,0528 | 0,3488 → **0,5349** |

Acuratețea **își inversează semnul**. Tot avantajul vine din meciurile cu
baseline orb.

**`blend_v1` / `all` (`8ac89c70…`, PROMOVAT):** toate cele trei metrici rămân
favorabile și fără neutrale (Brier 0,6432→0,6091, log-loss 1,0688→1,0193,
acuratețe 0,4660→0,5079). **Promovarea din 2026-08-22 a fost solidă.**
Problema nu e retroactivă — e prospectivă.

---

## Decizie

**Se adaugă un diagnostic, nu se schimbă criteriul.**

Fiecare verdict de evaluare raportează, pe lângă metricile pe populația
completă, **deltele celor trei metrici recalculate pe subsetul informat** —
meciurile în care baseline-ul a avut date reale (nu ambele echipe `neutral`).

Patru câmpuri noi pe `challenger_evaluations`:

| Câmp | Rol |
|---|---|
| `n_matches_informed` | câte meciuri au avut baseline informat |
| `delta_brier_informed` | delta Brier pe acel subset |
| `delta_logloss_informed` | delta log-loss pe acel subset |
| `delta_accuracy_informed` | delta acuratețe pe acel subset |

Decision Feed le afișează lângă verdict, ca omul care aprobă să vadă dacă
avantajul se păstrează sau dispare când baseline-ul nu mai e orb.

### Ce NU se face, și de ce

**Nu se exclud meciurile neutrale din evaluare.** `MIN_MATCHES_FOR_EVALUATION
= 200` (`learning_core/continuous_learning.py:69`), iar populația informată e
**191**. Un filtru mecanic ar produce `insufficient_data` — adică **niciun**
verdict — până la acumularea a ~9 meciuri în plus. Ar bloca Learning Core
pentru o problemă de divulgare.

**Nu se coboară pragul** ca să acomodeze filtrul. Ar însemna modificarea unui
prag statistic pentru a face loc unei alte schimbări — exact tiparul refuzat
în aceeași zi la pragul de eșec al `run_foundation_data_layer.py`.

**Nu se schimbă criteriul de promovare.** North Star #2 rămâne neatins:
Brier + log-loss + acuratețe simultan semnificativ mai bune, pe populația
completă. Diagnosticul informează omul, nu decide în locul lui — exact
repartiția pe care ADR-002 o cere.

**Nu se persistă un al doilea verdict.** `get_latest_challenger_evaluation()`
întoarce un singur rând per Challenger; un al doilea rând ar face „ultimul"
ambiguu. Cheia `UNIQUE (training_run_id, n_matches_evaluated)` ar fi permis-o
tehnic, dar ar fi rupt consumatorul. Un verdict, un rând, diagnostic atașat.

---

## Consecințe

**Pozitive**

- Un avantaj care vine exclusiv din meciuri cu baseline orb devine **vizibil
  înainte de aprobare**, nu descoperit ulterior. Cazul concret există deja:
  `xgboost_v1`.
- Nu se blochează nimic, nu se schimbă niciun prag, nu se atinge criteriul.
- Diagnosticul e aditiv: verdictele istorice rămân valabile și comparabile
  (câmpurile noi sunt `NULL` pentru ele — necunoscut, nu zero).

**Negative, acceptate**

- Patru coloane în plus pe o tabelă de guvernanță. Cost real, mic față de
  alternativa de a aproba promovări pe baze pe care datele nu le susțin.
- Diagnosticul poate fi ignorat de un om grăbit. Acceptat deliberat:
  alternativa (blocare automată) mută decizia din mâna omului, contra ADR-002.
- Subsetul informat poate fi prea mic pentru semnificație statistică. De aceea
  se raportează **delte**, nu verdicte — o delta e citibilă chiar și când un
  test de semnificație nu e concludent, iar `n_matches_informed` e afișat
  alături ca să nu fie citită fără context.

**Ce rămâne deschis**

- Dacă subsetul informat va arăta sistematic contrar celui complet pentru mai
  mulți Challengeri la rând, întrebarea „ce populație definește criteriul"
  devine legitimă — și cere un ADR propriu, nu o extindere tacită a acestuia.
- Pragul `MIN_MATCHES_FOR_EVALUATION` rămâne neschimbat și nediscutat aici.
