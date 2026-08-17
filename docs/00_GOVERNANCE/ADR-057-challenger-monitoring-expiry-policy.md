# ADR-057 — Politică de expirare pentru Challenger-ul blocat în „monitoring"

**Status**: PROPUS — neimplementat, în așteptarea deciziei proprietarului produsului
**Data**: 2026-08-17
**Derivat din**: auditul final ADR-051/052 (Prioritatea #2)
**Nu modifică**: ADR-002 (om în buclă la promovare), North Star #2 (toate trei metricile simultan), ADR-016 (FSM), criteriile de promovare

---

## 1. Context — problema reală, verificată

`shadow_testing.evaluate_experiment()` produce exact trei verdicte:

| Verdict | Condiție | Tratare în `continuous_learning._phase_a_monitor_existing()` |
|---|---|---|
| `candidate_for_promotion` | Brier ȘI log-loss ȘI accuracy simultan semnificative | tranziție `SUCCEEDED` + propunere T3a (aprobare umană) |
| `rejected` | toate trei se mișcă simultan în direcția greșită | tranziție `REJECTED` (`verdict_negative`), automat |
| `monitoring` | **orice altceva** | doar se jurnalizează — **nicio tranziție** |

`monitoring` e cazul cel mai probabil statistic: e suficient ca o singură
metrică din trei să nu atingă semnificația, sau ca cele trei să se miște în
direcții mixte. Un Challenger în `monitoring` rămâne în stare non-terminală
**la nesfârșit**.

Consecința, prin invariantul „cel mult un Challenger activ" (ADR-016 §4,
index unic parțial în DB): cât timp acel Challenger rămâne activ, **Faza B
nu poate crea niciodată următorul Challenger**. Motorul ML nu mai poate
evolua deloc — nu printr-o eroare, ci prin absența unei reguli.

### Stare curentă (verificată live, 2026-08-17)

- Challenger activ: `xgboost_v1|all`, `training_run_id=e638c1dc-…`, creat 2026-08-05
- Evaluat: 119/200 meciuri (prag `MIN_MATCHES_FOR_EVALUATION`)
- Verdict curent: `insufficient_data` (sub prag — nu încă `monitoring`)
- **Problema nu s-a manifestat încă** — devine reală abia după atingerea celor 200

---

## 2. Ce permite deja contractul (constatare importantă)

Auditul a găsit că **FSM-ul anticipează deja acest caz**. ADR-016 §3
definește mulțimea închisă de motive de respingere:

```
{verdict_negative, expired, superseded, artifact_dead}
```

`expired` e deja: (a) în ADR-016, document Frozen; (b) în
`challenger_manager.VALID_REJECTION_REASONS`; (c) impus prin `CHECK` la
nivel de bază de date. Tranziția `EVALUATING → REJECTED` e deja legală în
`ALLOWED_TRANSITIONS`.

**Verificat prin grep exhaustiv**: niciun cod de producție nu emite vreodată
`expired` pentru un Challenger. Vocabularul există; declanșatorul nu.

Deci **nu lipsește mecanica — lipsește politica.**

---

## 3. Ce lipsește, exact

Nicio decizie arhitecturală existentă nu răspunde la:

1. **După cât timp** un Challenger în `monitoring` e considerat epuizat?
   (număr de meciuri suplimentare peste 200? zile calendaristice? ambele?)
2. **Cine decide** — automat (ca la `verdict_negative`) sau propunere T3a
   cu aprobare umană (ca la promovare)?
3. **Ce se întâmplă imediat după** — Faza B pornește următorul Challenger
   pe date noi, sau se așteaptă un semnal explicit?
4. **Cum se evită oscilația** — un prag prea agresiv ar putea ucide repetat
   Challengeri care ar fi devenit promovabili cu puțin mai multe date, iar
   fiecare Challenger nou resetează complet ceasul celor 200 de meciuri.

Punctul 4 e riscul material: un prag greșit nu produce o eroare vizibilă,
ci **degradare tăcută** a capacității de învățare.

---

## 4. Opțiuni

### Opțiunea A — expirare automată pe prag fix
`monitoring` + N meciuri suplimentare evaluate → `REJECTED(expired)` automat.
- ✅ Deblochează Faza B fără intervenție
- ❌ Decizie ireversibilă luată automat; prag ales fără dovadă empirică azi
- ❌ Ar putea fira în timpul perioadei de observație curente

### Opțiunea B — propunere T3a, aprobare umană (recomandată)
`monitoring` + N meciuri suplimentare → propunere în decision feed;
expirarea se execută în Faza C doar după aprobare.
- ✅ Consecvent cu tiparul deja folosit pentru promovare (ADR-002) și pentru
  rollback (ADR-037) — orice decizie ireversibilă trece prin om
- ✅ Zero risc de degradare tăcută
- ✅ Reutilizează integral infrastructura existentă (`propose_decision`,
  `surface_decision`, Faza C) — fără mecanism nou
- ❌ Necesită atenție umană periodică

### Opțiunea C — status quo
- ✅ Zero risc acum
- ❌ Blocaj garantat pe termen lung: primul `monitoring` oprește permanent
  evoluția ML

---

## 5. Recomandare

**Opțiunea B**, cu:
- prag inițial propus: **+100 meciuri** evaluate peste cele 200 (adică
  n ≥ 300 cu verdict încă `monitoring`) — valoare de pornire, nu dovedită
  empiric, de recalibrat după primul caz real observat;
- flag dedicat, implicit **OPRIT** (North Star #3), separat de
  `learning_core_enabled`;
- motiv de respingere `expired` (deja valid — fără schimbare de contract);
- criteriile de promovare **rămân absolut neschimbate**.

---

## 6. De ce NU s-a implementat în task-ul curent

Trei motive, în ordinea importanței:

1. **Politica e o decizie arhitecturală nouă, nespecificată** de niciun ADR
   existent. CLAUDE.md: „Orice schimbare de contract (model de date,
   responsabilitate, flux) trece printr-un ADR — nu prin editare tăcută."
   Faza A ar căpăta o a patra ramură de decizie și o responsabilitate nouă.
2. **Alegerea pragului are consecințe materiale** și nicio bază empirică
   azi (zero Challengeri au ajuns vreodată la 200 de meciuri, deci zero
   observații despre cât de des apare `monitoring` în realitate).
3. **Instrucțiune explicită a proprietarului produsului** pentru task-ul
   curent: „Perioada de observație trebuie să continue neschimbată." Orice
   politică de expirare activă ar putea, prin construcție, să atingă exact
   Challenger-ul aflat acum în observație.

Nu există **urgență**: problema devine reală abia după ce Challenger-ul
curent depășește 200 de meciuri ȘI primește `monitoring`. Până atunci,
decizia poate fi luată fără presiune.

---

## 7. Consecințe dacă se aprobă

- `continuous_learning._phase_a_monitor_existing()` capătă o ramură nouă,
  gatată de flag propriu, implicit oprit
- Zero modificări în `shadow_testing.py`, `promotion_service.py`,
  `challenger_manager.py` (vocabularul `expired` există deja)
- Zero modificări de schemă
- Teste noi: prag neatins → nicio acțiune; prag atins + flag oprit → nicio
  acțiune; prag atins + flag pornit → propunere T3a, niciodată expirare
  directă; expirarea eliberează invariantul „cel mult un Challenger activ"

## 8. Consecințe dacă se respinge (status quo)

Trebuie acceptat explicit, în scris, că primul verdict `monitoring`
oprește permanent evoluția ML până la o intervenție manuală — și că nu
există azi nicio alertă care să semnaleze acea stare.
