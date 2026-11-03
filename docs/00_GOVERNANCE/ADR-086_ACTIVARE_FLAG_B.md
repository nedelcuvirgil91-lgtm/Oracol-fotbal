# ADR-086 — protocol de activare pentru `local_cache_fsm_guard_enabled` (Decizia B)

**Stare: PREGĂTIT, NEEXECUTAT.** Scris 2026-11-03, după livrarea codului
(`ca3b813` pe `main`). Precedent de formă: `ADR-082_VERIFICARI_PRE_ACTIVARE.md`.

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
| 3 | **o rulare de noapte cu flagul OPRIT, comportament identic** | ⛔ **NEÎNDEPLINITĂ** — codul a ajuns pe `main` la ~15:00, 3 nov |
| 4 | amprenta `model_config` măsurată **imediat înainte** | pregătită, §2 |

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

- **2026-11-03** — protocol scris, nimic executat. Condiția 3 din §1 e
  neîndeplinită prin construcție (codul a ajuns pe `main` în aceeași zi).
  Ancora din §2 măsurată read-only. §6 adaugă o remăsurare care **restrânge**
  riscul declarat în ADR-086 §4.2: două dintre cele trei căi sunt dovedit
  neafectate.
