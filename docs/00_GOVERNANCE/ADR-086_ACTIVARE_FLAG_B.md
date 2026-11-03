# ADR-086 — protocol de activare pentru `local_cache_fsm_guard_enabled` (Decizia B)

**Stare: ✅ EXECUTAT — flag ACTIV în producție din 2026-11-03, 20:34:49 UTC.**
Scris 2026-11-03, după livrarea codului (`ca3b813` pe `main`); executat în
aceeași zi, după ce condiția 3 din §1 a fost îndeplinită de rularea manuală
`night_sync` **112** (`automation_runs` id=**1537**). Precedent de formă:
`ADR-082_VERIFICARI_PRE_ACTIVARE.md`. Jurnalul execuției: §9.

**Nu se rulează nimic din §3 până §1 e bifat integral.**

---

## §0. Ce face flagul, în două propoziții

Cu el activ, `local_model_cache.load_latest_trained_model_or_none()` **sare
artefactele al căror Challenger e `REJECTED`** și trece la candidatul următor.
Regula e **negativă** — *un artefact respins nu servește* — niciodată pozitivă
(„doar un campion servește"), fiindcă aceea ar opri ML-ul azi și ar contrazice
ADR-051.

---

## §1. Precondiții — toate, înainte de orice scriere

| # | condiție | stare la 2026-11-03 |
|---|---|:-:|
| 1 | `pytest tests/` verde pe `main` | ✅ **4202 passed, 2 skipped** (4170 + 31 + 1, aritmetica se închide exact) |
| 2 | mutații rulate și prinse | ✅ **13/13**, ADR-086 §9.5 |
| 3 | **o rulare de noapte cu flagul OPRIT, comportament identic** | ✅ **ÎNDEPLINITĂ** — rularea **112**, `automation_runs` id=1537, 19:10:01 → 20:11:54, `completed`, 9/9 etape, `critice_esuate = []` |
| 4 | amprenta `model_config` măsurată **imediat înainte** | ✅ remăsurată 20:3x — **41 / false /** `29793d1b…ec25`, identică cu ancora din §2 |

### §1.1 De ce condiția 3 nu e formalitate — precedentul datat

B adaugă un apel nou (`is_fsm_guard_enabled()` → `sb.load_config()`) **în calea
de pornire a motorului**, iar aceea e exact calea exercitată de etapa
**Challenger Shadow Batch**. Pe **17 octombrie** un nume de fișier de cache a
omorât exact acea etapă **patru nopți la rând**, iar `night_sync` a raportat
verde. O rulare care confirmă că nu s-a rupt nimic costă o noapte.

### §1.2 🔴 Ce NU verifică rularea de la noapte — spus înainte, ca să nu fie citit greșit mâine

**Ambele sloturi de familie sunt ocupate** (`174e7e17` blend `SUCCEEDED`,
`dda4f7f3` xgboost `SUCCEEDED`), deci **Faza B nu antrenează** → **Decizia A nu
va fi exercitată.** Rularea confirmă strict:

- etapa Challenger Shadow Batch a rulat (durată în banda ~1000 s, **nu 2 s**);
- s-au scris rânduri noi în `shadow_predictions`;
- artefactul servit e în continuare `dda4f7f3`.

**O rulare verde NU e dovadă pentru A.** Dovada pentru A vine abia la prima
antrenare cerută de `blend_v1` — `DE_URMARIT.md` §21.

---

## §2. Măsurătoarea „înainte" — read-only, se rulează DIN NOU imediat înainte

**Nu se refolosesc cifrele de mai jos ca așteptare.** D-14: lanțul de amprente
`model_config` s-a rupt deja o dată (o cheie adăugată între 15 și 19 oct, care
**nu va fi niciodată numită**), deci se **re-ancorează** la fiecare scriere, nu
se reconstituie.

```sql
-- PRE-FLIGHT, read-only
SELECT (SELECT count(*) FROM jsonb_object_keys(data)) AS total_chei,
       (data ? 'local_cache_fsm_guard_enabled')       AS flag_prezent,
       md5(data::text)                                 AS md5_integral,
       updated_at::text                                AS updated_at
FROM model_config WHERE id = 1;
```

**Ancora măsurată 2026-11-03, 15:1x UTC** (de comparat, nu de presupus):

| câmp | valoare |
|---|---|
| `total_chei` | **41** |
| `flag_prezent` | **false** |
| `md5_integral` | **`29793d1b4ab1d281cb27765eb880ec25`** |
| `updated_at` | `2026-11-02 17:30:03.259717+00` (activarea ADR-037 R4) |

**Dacă pre-flight-ul de mâine dă altceva decât 41 / false** — s-a strecurat o
scriere neconsemnată între timp, exact clasa D-14. **Se oprește** și se
investighează, nu se activează.

---

## §3. SQL-ul de activare — de arătat și confirmat explicit înainte de rulare

```sql
UPDATE model_config
SET data = data || '{"local_cache_fsm_guard_enabled": true}'::jsonb,
    updated_at = now()
WHERE id = 1;
```

**Trei detalii care nu sunt cosmetice:**

1. **Valoarea e `true` boolean, nu șirul `"true"`.** `is_fsm_guard_enabled()`
   face `bool(cfg.get(...))`, iar `bool("false")` e `True` — deci un șir ar
   activa garda indiferent de conținut. Aceeași atenție ca la ADR-072.
2. **`updated_at = now()` e OBLIGATORIU** — remediul D-14, varianta 1. Fiecare
   activare de până la 19 oct a omis coloana, iar `updated_at` a stat înghețat
   la 6 septembrie prin **trei** scrieri consecutive. Câmpul care ar fi ancorat
   lanțul exista și era ignorat.
3. **`data || …` adaugă, nu înlocuiește** — `data = '{...}'` ar șterge celelalte
   41 de chei.

### §3.1 Canalul de rulare

`ALTER`/`UPDATE` au trecut prin MCP pe 3 noiembrie, deci canalul merge pentru
instrucțiuni neclasificate ca distructive. Dacă totuși se blochează pe
confirmarea proprie a serverului Supabase (dialog care nu ajunge în acest
mediu), se rulează de proprietarul produsului în **SQL Editor** — constatare
operațională consemnată în `CLAUDE.md` D-6.

---

## §4. Verificarea de după scriere — amprentă, nu „pare bine"

```sql
-- AMPRENTA, read-only, imediat după UPDATE
SELECT (SELECT count(*) FROM jsonb_object_keys(data))                      AS total_chei,
       data -> 'local_cache_fsm_guard_enabled'                             AS valoare_flag,
       jsonb_typeof(data -> 'local_cache_fsm_guard_enabled')               AS tipul_valorii,
       md5((data - 'local_cache_fsm_guard_enabled')::text)                 AS md5_fara_cheia_noua,
       updated_at::text                                                     AS updated_at
FROM model_config WHERE id = 1;
```

**Ce trebuie să se vadă, exact:**

| câmp | așteptat |
|---|---|
| `total_chei` | **42** (41 + 1) |
| `valoare_flag` | `true` |
| `tipul_valorii` | **`boolean`** — dacă apare `string`, s-a scris șirul; se corectează |
| `md5_fara_cheia_noua` | **identic cu `md5_integral` din pre-flight** → exact o cheie adăugată, **zero chei existente atinse** |
| `updated_at` | **mișcat**, aproximativ momentul rulării |

---

## §5. Verificarea de comportament — și limita ei, declarată

```sql
-- artefactul servit trebuie sa rămână dda4f7f3
WITH cu_artefact AS (
  SELECT t.training_run_id, t.created_at
  FROM training_runs t
  WHERE t.algorithm_name='xgboost_v1' AND t.league_scope='all' AND t.status='trained'
    AND EXISTS (SELECT 1 FROM storage.objects o JOIN storage.buckets b ON b.id=o.bucket_id
                WHERE b.name='model-artifacts' AND o.name = t.training_run_id||'.json')
)
SELECT a.training_run_id, a.created_at::text, c.algorithm_family, c.state,
       (c.state = 'REJECTED') AS ar_fi_sarit_de_garda
FROM cu_artefact a LEFT JOIN challengers c ON c.training_run_id = a.training_run_id
ORDER BY a.created_at DESC;
```

**Primul rând trebuie să fie `dda4f7f3`, cu `ar_fi_sarit_de_garda = false`.**
Activarea lui B **nu trebuie să schimbe nimic azi** — Challengerul lui nu e
terminal, deci garda nu are ce exclude. **O schimbare la activare înseamnă că
garda prinde altceva decât credem**, și se revine imediat (§7).

### §5.1 🔴 NU există martor pozitiv end-to-end în producție, prin construcție

Trebuie spus, nu ocolit: cele trei artefacte `REJECTED` (`e638c1dc`,
`4e17c737`, `6e7265c5`) **nu sunt oricum selectate**, fiindcă `dda4f7f3` e mai
recent și valid — iar bucla **se întoarce la primul candidat valid**. Deci garda
nu va emite nicio linie de log și nu va sări nimic. **Un „totul e în ordine" de
mâine e compatibil și cu o gardă complet inertă.**

Martorul se descompune în două jumătăți, fiecare verificabilă:

| jumătate | cum se verifică | stare |
|---|---|:-:|
| **datele** — cele trei artefacte sunt chiar `REJECTED` | interogarea din §5, coloana `ar_fi_sarit_de_garda` | de rulat |
| **logica** — funcția le clasifică drept descalificate | `tests/test_adr086_artifact_governance.py`, 31 de teste, **13 mutații** (M5 inversarea gărzii doboară 9 teste; M6 `PROMOTED` adăugat doboară 2) | ✅ |

**Corectitudinea gărzii se sprijină pe suita de teste, nu pe o observație de
producție** — iar asta e o limită reală, nu un detaliu. Primul martor pozitiv
genuin apare abia când un artefact respins devine cel mai recent cu artefact,
adică exact scenariul din §6.

---

## §6. Când riscul lui B devine real — fereastra e cunoscută

Propunerea de expirare pentru `dda4f7f3` (`decision_feed` #13) a fost
`expired` prin sweep pe **2 noiembrie** și **revine ~9 noiembrie**. Dacă e
aprobată și comisă, iar Faza B nu apucă să antreneze înlocuitorul, atunci cu B
activ cache-ul nu mai are niciun candidat → **ML se oprește, se servește
Oracle-only**.

**Costul acelei stări, remăsurat în cod pe 3 noiembrie** — și e mult mai mic
decât îl descria ADR-086 §4.2, care numea consecința fără să numească
consumatorul:

| consumator | afectat de B? | dovada |
|---|:-:|---|
| probabilitățile **servite** | **NU** | `_get_ml_engine_prediction` e **read-only** față de `ph`/`pd_`/`pa` — scris în propriul docstring, `oracle_engine.py:2632` |
| evaluarea **Challengerilor** (poarta de promovare) | **NU** | adaptoarele de shadow încarcă artefactul **direct**, `model_artifact_storage.load_model_artifact(training_run_id)` — **nu** prin `local_model_cache` |
| `engine_comparison_snapshots` (ADR-052) | **DA** | trece prin `self.ml` |

**Deci cazul cel mai rău al lui B nu atinge nici predicțiile servite, nici
poarta de promovare.** Costul e exact unul: **canalul de măsurare al lui D-17
rămâne gol** până când Faza B antrenează un înlocuitor.

**Și argumentul se întoarce în favoarea activării.** Cu B **oprit**, un
`dda4f7f3` respins ar continua să alimenteze snapshot-urile ADR-052 — adică am
măsura ansamblul **pe un artefact pe care guvernanța l-a retras**, exact clasa
„ce se evaluează nu e ce se servește", cu un nivel mai sus. Un gol în date e
onest; date dintr-un artefact retras induc în eroare. **North Star #8 tranșează:
golul e preferabil.**

---

## §7. Revenire

```sql
UPDATE model_config
SET data = data || '{"local_cache_fsm_guard_enabled": false}'::jsonb,
    updated_at = now()
WHERE id = 1;
```

Garda se oprește **la următoarea construcție de motor**, fără deploy. Flagul se
pune pe `false`, **nu se șterge cheia** — o cheie ștearsă ar face lanțul de
amprente să scadă, iar „42 → 41" ar arăta identic cu o scriere neconsemnată
(D-14). Rândurile scrise între timp nu se ating.

---

## §8. Condiții de OPRIRE — orice una dintre ele anulează activarea

1. Pre-flight-ul dă altceva decât **41 chei / `flag_prezent = false`**.
2. Etapa Challenger Shadow Batch a eșuat sau a durat ~secunde în loc de ~1000 s.
3. `md5(data − cheia_nouă)` **diferă** de `md5_integral` din pre-flight.
4. `jsonb_typeof` întoarce **`string`** în loc de `boolean`.
5. Artefactul servit **nu** mai e `dda4f7f3` imediat după activare.

---

## §9. Jurnal

- **2026-11-03, ~15:00** — protocol scris, nimic executat. Condiția 3 din §1 e
  neîndeplinită prin construcție (codul a ajuns pe `main` în aceeași zi).
  Ancora din §2 măsurată read-only. §6 adaugă o remăsurare care **restrânge**
  riscul declarat în ADR-086 §4.2: două dintre cele trei căi sunt dovedit
  neafectate.

- **2026-11-03, 19:10 → 20:11 — rularea 112 închide condiția 3.** Pornită
  manual pe `head_sha = 31a9a17`, verificat ÎNAINTE de pornire că include
  `ca3b813`. Rândul de audit: `automation_runs` id=**1537**,
  `target_key = 2026-11-03` (al treilea rând al zilei, deci regula „Reuse" din
  ADR-026 a creat corect un rând nou, nu a refolosit unul încheiat),
  `github_run_id = 41700468157`, durată **61,9 min**, `status = completed`,
  9/9 etape, `critice_esuate = []`.

  **Verificarea decisivă — trecută**: etapa **Challenger Shadow Batch**
  `durata_s = 1959,9`, `ok: true`, `critic: true`. Apelul nou
  `is_fsm_guard_enabled()` → `sb.load_config()` din calea de pornire a
  motorului **nu a rupt nimic** — exact calea pe care un nume de fișier de
  cache a omorât patru nopți la rând pe 17 octombrie, cu `night_sync` verde
  (§1.1).

  **Scrieri proaspete**: **200 de rânduri atinse per bandă**, `prediction_time`
  avansat la **20:11:2x** pe toate cele 7 benzi vii — `xgboost_v1/dda4f7f3`
  (control + treatment), `blend_v1/174e7e17` (control + treatment),
  `blend_v1/8ac89c70` (champion + control), `flashscore_team_dna/v1`. Benzile
  înghețate au rămas înghețate, corect: `8ac89c70` treatment (23 aug, campion
  promovat), `4e17c737` (19 sep), `6e7265c5` (13 oct), `e638c1dc` (6 sep) —
  toate `REJECTED`. **Semnalul corect e `prediction_time` avansat, nu totalul
  de rânduri** (scrierea e `upsert`, batch-ul reprocesează aceeași fereastră).

  **Artefactul servit**: în continuare **`dda4f7f3`** — 721 instantanee în
  `engine_comparison_snapshots`, ultimul la **20:11:26**.

  **Ce NU a validat, repetat ca în §1.2**: ambele sloturi de familie erau
  `SUCCEEDED`, deci **Faza B nu a antrenat** → **Decizia A rămâne
  neexercitată în producție**. Dovada pentru A vine abia la prima antrenare
  cerută de `blend_v1` (`DE_URMARIT.md` §21).

  **Două durate sub banda obișnuită, notate fără alarmă**: etapa 5 Flashscore
  **373,9 s** (banda 6,7–15,3 min) și `team_stats_tsdb` **0,0 s**. Cauza e
  cunoscută și nu e un defect: a fost **a treia rulare a zilei pe aceeași
  dată**, deci Delta Sync a sărit meciurile colectate de cele dinainte. Nu se
  citește ca îmbunătățire și nu se compară cu banda istorică.

- **2026-11-03, 20:34:49 — FLAG ACTIVAT**, cu aprobare explicită a
  proprietarului produsului, după pre-flight-ul §2 **remăsurat** (nu
  refolosit): **41 chei / `flag_prezent = false` /**
  `md5_integral = 29793d1b4ab1d281cb27765eb880ec25` /
  `updated_at = 2026-11-02 17:30:03` — identic cu ancora, deci nicio scriere
  nu se strecurase între timp (clasa D-14 verificată, nu presupusă).

  **Amprenta de după, §4, se închide exact**: `total_chei` **41 → 42**;
  `valoare_flag` `true` cu `jsonb_typeof = boolean` (**nu** `string`);
  `md5(data − 'local_cache_fsm_guard_enabled')` =
  **`29793d1b4ab1d281cb27765eb880ec25`**, **identic** cu `md5_integral` din
  pre-flight → exact o cheie adăugată, **zero chei existente atinse**;
  `updated_at` **2026-11-02 17:30:03 → 2026-11-03 20:34:49** (remediul D-14,
  varianta 1, în efect a doua oară după ADR-037 R4).

  **Niciuna din cele cinci condiții de oprire din §8 nu a fost atinsă.**

  **Jumătatea „datele" din §5.1 e acum bifată cu date reale**, nu presupusă:
  interogarea §5 dă `dda4f7f3` primul candidat cu
  `ar_fi_sarit_de_garda = false`, iar cele trei artefacte `REJECTED`
  (`6e7265c5`, `4e17c737`, `e638c1dc`) sunt chiar `REJECTED`. Harta pe care
  garda citește e cea pe care codul o presupune.

  **🔴 Limita rămâne cea declarată ÎNAINTE de activare, și se repetă aici ca să
  nu fie citită greșit mai târziu: garda e INERTĂ azi.** `dda4f7f3` e cel mai
  recent artefact valid, bucla se oprește la el, deci nimic nu va fi sărit și
  nicio linie de log nu va apărea. **Un „totul e în ordine" la rularea
  următoare e compatibil și cu o gardă complet moartă** — corectitudinea ei se
  sprijină pe cele 31 de teste și 13 mutații (§5.1, jumătatea „logica"), nu pe
  o observație de producție. Primul martor pozitiv genuin apare abia în
  scenariul §6, adică dacă `dda4f7f3` devine `REJECTED` (propunerea
  `decision_feed` #13 revine ~**9 noiembrie**).
