# ADR-082 — Verificări pre-activare, cu rezultate

**Cerute explicit de proprietarul produsului, 2026-10-27**, înainte de
activarea în producție: *„aceste verificări sunt deja în mare parte prevăzute
în ADR. Aș dori ca rezultatele lor să fie documentate înainte de activarea în
producție."*

**Starea flagului la scrierea acestui document**: `champion_shadow_logging_enabled`
**ABSENT** din `model_config` (= implicit `False`). Nimic nu e activat.
Toate măsurătorile de mai jos sunt read-only.

---

## V1. Perechea control–champion e completă și corect asociată

**Cerința**: *„documentul explică de ce e necesar rândul `control`, dar
implementarea trebuie să demonstreze că fiecare pereche e completă și corect
asociată."*

Demonstrat prin **6 teste** (`tests/test_champion_shadow_lane.py` §9), nu prin
text:

| Proprietate | Test | Rezultat |
|---|---|---|
| Exact un rând `champion` și exact unul `control`, nimic în plus | `test_perechea_e_completa_EXACT_un_champion_si_EXACT_un_control` | ✅ |
| Cele două împart EXACT cheia de împerechere `(fixture_id, experiment_name, experiment_version, processing_stage)` | `test_perechea_e_CORECT_ASOCIATA_pe_toata_cheia_de_impereche` | ✅ |
| Diferă **doar** prin grup și probabilități — ligă/echipe/kickoff/xG identice | `test_perechea_difera_DOAR_prin_grup_si_probabilitati` | ✅ |
| Probabilitățile **nu se inversează** între rânduri | `test_probabilitatile_nu_se_INVERSEAZA_intre_cele_doua_randuri` | ✅ |
| O pereche incompletă **nu raportează succes** | `test_perechea_e_ATOMICA_logic_ambele_sau_niciunul` | ✅ |
| Banda se scrie **prima**, ca un orfan să fie detectabil | `test_banda_se_scrie_PRIMA_ca_un_orfan_sa_fie_detectabil` | ✅ |

**Două decizii care merită explicate, fiindcă nu sunt evidente:**

**(a) Inversarea e cel mai periculos defect posibil aici.** Campionul scris pe
rândul `control` și invers ar trece orice test de numărare, ar produce o
pereche completă *și* corect asociată — și ar inversa verdictul de sănătate.
De aceea testul folosește valori deliberat distincte (0,55/0,28/0,17 vs
0,50/0,30/0,20), imposibil de confundat.

**(b) Ordinea de scriere nu e indiferentă.** Dacă `control` s-ar scrie primul
și banda ar eșua, rămâne un rând `control` orfan — **indistingibil** de cele
scrise legitim de Challenger pentru aceeași versiune. Invers, un rând
`champion` orfan e imediat detectabil: grupul există doar aici. Banda se scrie
prima, impus de test.

**Limită declarată, nu ascunsă**: atomicitatea e **logică, nu
tranzacțională** — două `upsert`-uri separate nu pot fi atomice în PostgREST.
Dacă al doilea eșuează, adaptorul întoarce `False` și rămâne un rând `champion`
orfan. Detectabil prin interogare (un `champion` fără `control` pe aceeași
cheie), și benign: gardianul citește banda, iar perechea lipsă nu produce o
metrică falsă, doar un rând neevaluabil.

---

## V2. Inventarul COMPLET al consumatorilor `experiment_group`

**Cerința**: *„noul grup trebuie să nu afecteze accidental rapoarte, evaluări
sau alte procese care presupun numai `control` și `treatment`."*

Toate cele **7 atingeri** ale tabelei `shadow_predictions` din codul de
producție (`tests/` și `scripts/` excluse), fiecare clasificată:

| # | Locul | Ce face | Vede grupul nou? |
|---|---|---|---|
| 1 | `shadow_testing.py:115` | `upsert` — scriitorul generic; grupul vine de la apelant | n/a (scriitor) |
| 2 | `shadow_testing.py:254` | `invalidate_shadow_predictions` — invalidează **toate** rândurile unui `fixture_id`, indiferent de grup | **DA, și e CORECT** — vezi mai jos |
| 3 | `shadow_testing.py:183` | `get_shadow_predictions` — filtrul pe grup se aplică doar dacă nu e `None` | **NU** — vezi mai jos |
| 4 | `shadow_testing.py:461` | citirea rândurilor `control` pentru împerechere — `.eq(…, "control")` explicit | NU |
| 5 | `shadow_testing.py:827` | `get_distinct_experiments` — enumeră `(name, version)`, agnostic la grup | **DA, fără efect** — vezi mai jos |
| 6 | `value_selector_shadow.py:365` | radarul — `.eq(…, EXPERIMENT_GROUP)` = `"control"` | NU |
| 7 | `supabase_client.py:1201` | sursa gardianului (nouă) — `.eq(…, "champion")` explicit | DA (intenționat) |

### Cele trei cazuri care cereau analiză, nu doar bifă

**#3 — `get_shadow_predictions` cu `experiment_group=None`** era singurul risc
real: un apelant care nu filtrează ar primi și rândurile `champion`.
**Măsurat: are EXACT UN apelant de producție** — `shadow_testing.py:546`, în
`evaluate_experiment` — iar acela pasează `experiment_group="treatment"`
**explicit**, și re-filtrează a doua oară în Python (linia 550). Toți ceilalți
apelanți sunt în `tests/`.

> **Concluzie: zero consumatori de producție văd grupul nou neintenționat.**

**#5 — `get_distinct_experiments`** enumeră perechile `(experiment_name,
experiment_version)` fără filtru de grup, iar rezultatul alimentează
`evaluate_all_active_experiments`. Grupul nou **nu adaugă nicio pereche**:
`blend_v1/8ac89c70` e deja în set, prin cele 394 de rânduri `treatment`
istorice ale campionului. Evaluarea generică îl atinge deja astăzi și va
continua să-l atingă, pe aceleași rânduri vechi — **zero schimbare**.

**#2 — `invalidate_shadow_predictions`** invalidează toate rândurile unui
`fixture_id`, deci și banda. **E corect prin construcție, nu o scăpare**:
ADR-064 invalidează predicții făcute sub o identitate greșită (ex. inversarea
teren propriu/deplasare). Dacă identitatea unui meci a fost greșită, predicția
campionului pentru el e la fel de invalidă. Iar sursa gardianului filtrează
`invalidated_at IS NULL`, deci rândurile invalidate sunt excluse din evaluare
— verificat în `test_sursa_noua_e_paginata_si_nu_intoarce_parcursul_partial`.

**Asimetrie declarată**: `evaluate_experiment` **nu** evaluează banda
`'champion'` (citește `treatment`). Corect — un campion nu e un candidat de
promovat (ADR-080) — dar e o proprietate de reținut, nu un defect.

---

## V3. Volumul real, MĂSURAT pe producție

**Cerința**: *„documentul recunoaște că vor exista două rânduri suplimentare
per meci servit. Impactul trebuie măsurat înainte de activare."*

| Măsurătoare | Valoare |
|---|---:|
| Rând serializat **fără** `feature_metadata` (ce scrie banda) | **785 octeți** |
| Rând serializat **cu** înregistrarea ADR-073, pentru comparație | 1980 octeți |
| `shadow_predictions` azi | 8563 rânduri · **10 080 kB** |
| Fixture-uri distincte, istoric (`blend_v1`/`control`) | 1541 |
| Fixture-uri **noi** în ultimele 30 de zile | 662 → **22,1/zi** |

**Creșterea proiectată**: scrierea e `upsert` pe cheia compusă, deci rândurile
**nu** se acumulează per rulare — se acumulează per **fixture nou**.

```
2 rânduri × 785 octeți            = 1570 octeți per fixture
1570 × 22,1 fixture-uri/zi        ≈ 34,7 kB/zi
                                  ≈ 1,04 MB/lună
```

**Decizia de a NU scrie `feature_metadata` pe bandă e validată de cifră, nu de
argument**: cu înregistrarea ADR-073 pe ambele rânduri, volumul ar fi fost
`2 × 1980 × 22,1 ≈ 87,5 kB/zi ≈ 2,6 MB/lună` — **de 2,5× mai mult**, pentru o
informație măsurat identică (rândul `control` e identic bit cu bit între
familii, pe toate cele 512 meciuri comune).

**Restanță semnalată, nu rezolvată aici**: `shadow_predictions` **nu are
politică de retenție** (gol deja consemnat la ADR-073). Cele ~1 MB/lună se
acumulează la nesfârșit. Nu e blocant la scara actuală — tabela are 10 MB după
peste două luni — dar intră pe lista de urmărit, nu se uită.

---

## V4. Ordinea de activare: gardianul nu poate raporta pe o bandă subțire

**Cerința**: *„nicio activare a Guardianului înainte ca banda să aibă
suficiente rezultate reale și verificabile."*

**Corecție de premisă**: ADR-082 §2.4 a **eliminat** al doilea flag în timpul
scrierii, deci nu mai există „testarea flagurilor separat" ca sarcină — există
**un singur flag** (pentru bandă), iar schimbarea de sursă a gardianului e
necondiționată. Cerința rămâne însă valabilă în fond, și e acum **impusă
structural, nu procedural**:

| Stare | `n` | Verdict | Persistă? | Poate declanșa rollback? |
|---|---:|---|---|---|
| bandă goală (azi, flag oprit) | 0 | `insufficient_data` | **NU** | NU |
| bandă sub prag (1-29) | <30 | `insufficient_data` | da (fapt real) | **NU** |
| bandă peste prag | ≥30 | se calculează | da | da |

Verificat prin test: `test_banda_goala_da_insufficient_data_si_NU_persista` și
`test_banda_sub_prag_nu_recomanda_rollback` (acesta confirmă și că
`brier_live is None` — nicio metrică nu se calculează sub prag).

> **Deci gardianul nu poate raporta nimic despre o bandă subțire, oricând ar
> fi activat.** Protecția nu mai depinde de a respecta o ordine — ceea ce e
> mai bine, fiindcă o ordine se uită (precedentul ADR-057: 14 zile fără
> antrenare, fiindcă nimeni nu s-a uitat când condiția s-a împlinit).

**Ordinea rămâne totuși recomandată**, pentru alt motiv: activarea benzii
întâi dă ~22 de fixture-uri/zi, deci pragul de 30 se atinge în **~2 zile**, iar
cele 332 de meciuri comparabile ale relurii se refac în ~2 săptămâni.

---

## V5. Verdictul gardianului, ÎNAINTE vs DUPĂ schimbarea sursei

**Cerința**: *„diferențele trebuie explicate prin corectarea sursei de date,
nu confundate cu o degradare a modelului."*

Ambele cifre sunt reproduse read-only, replicând exact `_live_metrics()`.

### Sursa VECHE — ce ar fi raportat gardianul azi

Fereastra: `match_history.prob_*_pred`, `kickoff_date >= 2026-08-23`, **n = 1135**

| | |
|---|---:|
| Brier live | **0,6109** |
| Log-loss live | 1,0231 |
| Acuratețe live | 0,4952 |
| baseline de promovare | 0,6225 |
| prag de alarmă (×1,10) | 0,6848 |
| `baseline_deviation_flag` | **false** |

### Sursa NOUĂ — campionul propriu

Proxy exact: relurea validată (rularea `40518633429`, Faza 1 divergență
**0,000e+00** pe 512/512 — deci relurea reproduce bit cu bit ce va scrie
banda), pe **n = 332** meciuri terminate.

| | Oracle (aceeași fereastră) | **Campion** |
|---|---:|---:|
| Brier | 0,6100 | **0,5960** |
| Log-loss | 1,0198 | **0,9977** |
| Acuratețe | 0,4970 | 0,5151 |

### Explicația diferenței — și ce NU e

**Verdictul nu se schimbă azi: `healthy` în ambele cazuri.** 0,6109 și 0,5960
sunt amândouă sub pragul de 0,6848. Asta e important de spus explicit, ca
schimbarea să nu fie citită ca un eveniment.

**Ce se schimbă e marja**, și în direcția bună:

```
sursa veche : 0,6848 − 0,6109 = 0,0739 de marjă până la alarmă
sursa nouă  : 0,6848 − 0,5960 = 0,0888 de marjă
→ +20,2% mai mult spațiu înainte de o alarmă
```

**Diferența e corectarea unei atribuiri, dovedit, nu o schimbare de
performanță.** Trei argumente independente:

1. **Modelul nu s-a schimbat.** `8ac89c70` e înghețat din 23 august — nu s-a
   reantrenat, nu s-a recalibrat, artefactul e același. O cifră care se mișcă
   fără ca modelul să se miște nu poate fi o schimbare de performanță.
2. **Pe ACEEAȘI fereastră, diferența persistă**: Oracle 0,6100 vs campion
   0,5960 pe exact aceleași 332 de meciuri, `t = 3,07`. Deci nu e un artefact
   al lungimii ferestrei (0,6109 pe 1135 vs 0,6100 pe 332 — practic identice,
   ceea ce arată că fereastra nu distorsionează).
3. **Direcția e cea prezisă de analiza din ADR-082 §1.3**, scrisă înainte de
   măsurătoare: Oracle e mai slab decât campionul, deci substituția împingea
   spre **alarmă falsă**. Confirmat: marja era cu 20% mai mică decât e în
   realitate.

**Ce rămâne NEverificabil azi, declarat**: sursa veche și cea nouă nu pot fi
comparate pe ferestre identice pentru dimensiunea „trend" (split 50/50), fiindcă
banda nu există încă. Se reface la prima evaluare de după acumularea a ≥30 de
rânduri, iar diferența se raportează atunci — cu aceeași regulă: se explică,
nu se presupune.

---

## Ce rămâne de făcut înainte de activare

Toate cele cinci verificări cerute sunt **făcute și documentate**. Rămân doi
pași care, prin natura lor, cer o rulare reală:

1. **O rulare de noapte cu flagul OPRIT**, care confirmă comportament identic:
   zero rânduri cu `experiment_group = 'champion'`. (ADR-082 §6.1)
2. **Martorul de control după activare**: banda live trebuie să coincidă cu
   relurea din `scripts/replay_champion_on_persisted_inputs.py`. Divergența
   acceptată e cea deja măsurată la Faza 1 — **zero**. (ADR-082 §6.3)

`UPDATE model_config` se arată și se confirmă explicit înainte de rulare
(North Star #6), cu amprenta `md5(data − cheia_nouă)` înainte și după, plus
`updated_at = now()` (recomandarea D-14).
