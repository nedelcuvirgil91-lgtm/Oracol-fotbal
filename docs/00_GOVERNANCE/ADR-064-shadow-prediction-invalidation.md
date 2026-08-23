# ADR-064 — Invalidarea predicțiilor shadow făcute sub o identitate greșită

**Status**: Accepted (2026-08-23)
**Derivat din**: Discovery Rule (CLAUDE.md), în timpul remedierii inversării de teren Flashscore
**Atinge contractul**: `shadow_testing.evaluate_experiment()`, tabela `shadow_predictions`

---

## Context

Pe 2026-08-23, o inversare tăcută de teren în extragerea Flashscore
(`normalizer._extract_team_names()` deducea gazda din ordinea DOM) a produs
un rând `match_history` cu gazda și oaspetele schimbate între ele: Ligue 1,
`fixture_id=flashscore_p2AX2W4D`, scris pe 31 iulie ca „Paris Saint-Germain –
Rennes", când în realitate meciul se juca la Roazhon Park, deci Rennes era
gazdă (verificat extern, surse multiple independente).

Cauza rădăcină a fost reparată separat, iar rândul a fost corectat sub
ADR-060. Dar corecția a scos la iveală un al doilea efect, care **nu era în
scopul acelei intervenții**: pe baza orientării greșite se generaseră deja
**5 rânduri în `shadow_predictions`** — `blend_v1`, `xgboost_v1`,
`flashscore_team_dna` — toate cu `prob_home` atribuit echipei greșite.

Conform Discovery Rule, descoperirea a fost prezentată explicit
proprietarului produsului, care a ales crearea unui ADR dedicat.

### De ce nu e o simplă curățenie de 5 rânduri

**Contaminarea evaluării e inversată, nu zgomotoasă.** `evaluate_experiment()`
punctează `shadow.predicted_outcome` contra `match_history.actual_result`,
unde „H" înseamnă *victoria gazdei din `match_history`*. Dacă rândul canonic e
corectat iar predicția rămâne orientată invers, o predicție „PSG câștigă" e
punctată drept corectă exact când **Rennes** câștigă. Nu adaugă zgomot — adaugă
semnal fals, sistematic.

**Excluderea de azi e accidentală.** Cele 5 rânduri sunt în acest moment
ignorate de evaluare doar pentru că join-ul cere
`match_history.prob_home_pred IS NOT NULL`, iar corecția ADR-060 a anulat acele
coloane. Orice backfill viitor al predicțiilor le re-armează tăcut.

**Nu există niciun mecanism de invalidare.** Verificat direct în cod:
`evaluate_experiment()` filtrează exclusiv pe `processing_stage='final'` și
`experiment_group='treatment'`. Coloana `error_message` există, dar **nu e
citită niciodată**. O predicție intrată în tabelă nu poate fi scoasă din
evaluare prin niciun mijloc, în afară de ștergere.

**Cazul se va repeta.** Migrarea 049 întoarce `hard_conflict` cu
`reason='fixture_identity_mismatch'` ori de câte ori un provider raportează
alte echipe pentru un `fixture_id` cunoscut. Fiecare astfel de conflict poate
lăsa în urmă predicții shadow făcute sub identitatea greșită.

---

## Decizie

**1. O predicție făcută sub o identitate greșită nu se corectează — se
invalidează.**

Nu se rescrie și nu i se permută probabilitățile. Modelul aplică avantajul
terenului propriu, deci o permutare `prob_home ↔ prob_away` **nu** e
echivalentă cu o recalculare pe orientarea corectă: ar fabrica o predicție care
nu a fost făcută niciodată. Același raționament aplicat deja coloanelor
derivate din `match_history` la corecția ADR-060.

Nu se poate nici recalcula retroactiv: predicția ar folosi feature-uri de azi
pentru un moment din trecut, încălcând disciplina walk-forward (North Star #7).

**2. Nu se șterge.** Rândul rămâne în tabelă, marcat. Ștergerea ar rupe
trasabilitatea completă până la sursă (North Star #9): sistemul chiar a produs
acea predicție, iar faptul rămâne parte din istoric.

**3. Mecanismul e explicit, nu implicit.** Două coloane noi pe
`shadow_predictions`:

| Coloană | Rol |
|---|---|
| `invalidated_at timestamptz` | momentul invalidării; `NULL` = rând valid |
| `invalidation_reason text` | de ce — niciodată gol când `invalidated_at` e setat |

`evaluate_experiment()` exclude rândurile cu `invalidated_at IS NOT NULL`.

**4. Invalidarea rămâne o acțiune supravegheată, nu automată.** Nu se
declanșează singură dintr-un `hard_conflict`. Motiv: a decide că o predicție e
invalidă înseamnă a decide că identitatea sub care a fost făcută e greșită —
exact tipul de judecată pe care ADR-002 îl ține în mâna omului, și pe care
migrarea 049 refuză deliberat să o automatizeze. Se expune o funcție
explicită, apelată deliberat.

**5. O stare necunoscută nu devine invalidare.** Dacă nu se poate stabili că
identitatea a fost greșită, rândul rămâne valid și problema rămâne raportată,
nu „rezolvată" printr-o invalidare preventivă (North Star #8).

---

## Consecințe

**Pozitive**

- Excluderea devine intenționată și explicită, nu un efect secundar al unui
  `NULL` din altă tabelă. Un backfill viitor al `prob_*_pred` nu mai re-armează
  predicții inversate.
- Corpusul de evaluare Challenger capătă o poartă de calitate pe care nu o
  avea. Relevant direct: `blend_v1` e familia Campionului promovat.
- Auditul rămâne complet — se vede ce a prezis sistemul *și* că acea predicție
  a fost invalidată, cu motiv.

**Negative, acceptate**

- Două coloane în plus pe o tabelă fierbinte. Cost real, considerat mic față
  de alternativa (semnal fals sistematic în evaluare).
- Invalidarea manuală poate rămâne în urma descoperirii. Acceptat deliberat:
  o invalidare automată greșită scoate din evaluare predicții valide, ceea ce e
  mai grav și mai greu de observat decât întârzierea.
- Un rând invalidat scade `n_matches_evaluated`. Corect: acel meci chiar nu are
  o predicție evaluabilă.

**Ce NU face acest ADR**

- Nu detectează inversările de orientare. Detecția e o problemă separată
  (rămâne deschisă: o inversare la prima și singura extragere e invizibilă).
- Nu invalidează nimic automat.
- Nu schimbă criteriile de promovare (North Star #2 rămâne neatins).

---

## Verificare

Aplicarea concretă asupra celor 5 rânduri identificate se face separat, cu SQL
arătat integral și aprobare explicită, sub aceleași condiții ca ADR-060 —
nu ca parte tacită a acestui ADR.
