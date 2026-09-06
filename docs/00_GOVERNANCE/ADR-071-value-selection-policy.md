# ADR-071 — Value Selection Policy (Candidate vs Actionable)

**Status**: PROPUS — F1+F2 scrise, testate și pe `main`. Colectarea shadow e ACTIVĂ în producție din 2026-09-06; selectorul NU servește nimic live, UI neatins (`value_selector_v1_enabled` absent).
**Data**: 2026-09-04 · **Actualizat**: 2026-09-06 (decizia §16 + stadiul F2)
**Înlocuiește**: nimic. **Amendează**: nimic. ADR-043 (cascada de cote) și ADR-056 (shadow batch) rămân neschimbate — F2 le va folosi, nu le va modifica.

---

## Context

Ecranul „Top Value Bets" a fost auditat pe date reale, fără scurgere temporală: predicții din `shadow_predictions` cu `prediction_time` dovedit anterior loviturii de start, cote de deschidere din `odds_history` capturate înainte de start, rezultate din `match_history`. Set curat: **364 de meciuri / 1092 de selecții**, 5 aug – 4 sep 2026.

**Ce s-a măsurat:**

| | |
|---|---|
| Selecții admise de regula actuală | 447 din 1092 (**41%**) |
| Probabilitate medie a modelului | 39,4% |
| Probabilitate medie „fair" a pieței | 27,5% |
| **Rată reală de reușită** | **27,5%** |
| ROI la miză plată | **−10,2%** |

Realitatea coincide cu piața, nu cu modelul. Rezultatul e stabil: negativ în ambele jumătăți ale perioadei și pe toate cele trei tipuri de selecție.

Calitatea modelului vs. piață, pe același set: Brier **0,6239** vs **0,5818**; log-loss **1,0427** vs **0,9797**; acuratețe **46,4%** vs **51,9%**. Modelul e măsurabil mai slab decât cota — deci diferența model−piață nu e informație, e eroare, iar sortarea după mărimea ei selectează exact acolo unde modelul greșește cel mai mult.

**Cauza structurală**, în cod: `oracle_engine.py:1593` calculează `edge = (p − f)/f × 100` — edge **relativ**, normalizat la o probabilitate mică. Un outsider la cotă 10 cu +21 pp de eroare absolută produce +214%; un favorit la cotă 1,6 cu +8 pp produce +13%. Ordonarea descrescătoare după această mărime (`value_dashboard.py:66`) nu poate decât să scoată outsiderii deasupra. Nu există nicio altă poartă: nici prag de probabilitate, nici plafon de cotă, nici gate de calitate a datelor, nici deduplicare pe meci.

**Intenția de produs, formulată explicit de proprietarul produsului**: Top Value Bets e un **radar de meciuri**, nu un sistem de recomandare a pariului. Din toate meciurile zilei, semnalează 3-5 pe care omul să le investigheze manual. Decizia de a paria și execuția se fac integral în afara aplicației.

---

## Decizie

**1. Se separă VALUE de ACTIONABILITY.** „Valoare" descrie un candidat: modelul e mai optimist decât piața. „Acționabilitate" descrie o decizie de produs: merită atenția utilizatorului. Sunt două mărimi distincte, care nu se confundă niciodată într-un singur număr.

**2. Edge-ul relativ nu mai e criteriu de filtrare sau de ordonare.** Rămâne afișat ca diagnostic, alături de diferența absolută în puncte procentuale.

**3. Filtrarea se face prin porți explicite**, evaluate în ordinea conceptuală:

```
VALID → DATA QUALITY → PLAUSIBILITY → PROBABILITY → VALUE → ACTIONABILITY
```

Portile: validitatea cotei · piață deschisă · prospețimea cotei · prospețimea predicției · calitatea datelor · istoric minim · **rangul în meci** · **plauzibilitatea de piață** · prag de probabilitate · valoare pozitivă · valoare absolută minimă · plafon de cotă.

**4. H/X/A sunt simetrice structural, nu declarativ.** Nicio poartă și niciun scor nu inspectează tipul selecției. Impus prin construcție: `value_selector.py` nu conține niciun literal de selecție, iar maparea celor trei rezultate trăiește exclusiv în `value_selector_adapter.py`. Verificat prin gardă AST.

Simetria înseamnă *aceeași regulă*, nu *cotă egală de rezultate în listă*. Un egal cu probabilitate și valoare suficiente intră exact ca o gazdă. Faptul că modelul actual produce rar un egal drept rezultat lider e o proprietate a modelului, raportată separat.

**5. Plauzibilitatea are două componente, ambele necesare, niciuna suficientă:**
- **rangul în meci** — selecția trebuie să fie rezultatul cel mai probabil al modelului pentru acel meci;
- **plauzibilitatea de piață** — probabilitatea „fair" a pieței pentru acea selecție trebuie să depășească un prag.

Măsurat: rangul în meci elimină 10 din cele 14 selecții pe care regula actuală le producea în ziua auditată, inclusiv toate cazurile semnalate de proprietarul produsului. Dar **nu e suficient**: „Frosinone bate Juventus" (model 61,9%, piață 12,5%) și „Telstar 1963 bate Ajax" (model 44,1%, piață 21,0%) trec rangul. Când modelul contrazice piața asupra rezultatului lider, rata reală e **25-29%, plată, indiferent cât de mare e valoarea pretinsă** (n=113).

**6. Ordonarea nu se face pe EV.** Măsurat: un ranker pe EV promovează activ exact divergențele extreme (probabilitate mare pretinsă × cotă mare), adică reproduce patologia edge-ului relativ într-o altă formă. EV rămâne metrică de diagnostic și variantă experimentală în F2, niciodată ranker implicit.

**7. Ordonarea nu presupune că `model_p` e calibrat.** Măsurat: la 0,75 prezis, realitatea e 0,53. Ordonarea folosește o probabilitate contractată către piață, `p_shr = w·p + (1−w)·f`. `w` e parametru al politicii, nu constantă: familia {1,00 · 0,75 · 0,50 · 0,25 · 0,00} se compară prospectiv în F2.

**8. Datele insuficiente resping, niciodată „longshot".** Un candidat pe `data_quality = neutral` merge la Respinse. „Longshot Value" înseamnă strict *valoare reală cu probabilitate mai mică*, nu *nu știm nimic despre echipele astea*. Motivul concret: constanta de fallback documentată în `docs/03_ENGINE/EUROPEAN_COMPETITION_FORM_FILTER_DEFECT.md`.

**9. Unitatea radarului e MECIUL.** Maximum 5 meciuri pe zi, maximum o selecție per meci, zero completare artificială: dacă trec 3, se afișează 3; dacă trec 0, lista e goală.

**10. Politica e versionată și înghețabilă.** `policy_id = "{profil}@v1:{sha1(praguri)[:8]}"`. Orice schimbare de prag, pondere sau ranker schimbă id-ul — ceea ce face verificabilă mecanic regula „politica rămâne înghețată pe durata F3": dacă `policy_id` se schimbă la mijlocul experimentului, numărătoarea se resetează.

**11. Nicio valoare de prag nu e aprobată de acest ADR.** Pragurile din `value_selector_config.F2_PROFILES` sunt de pornire, alese ca să acopere intervalul cerut la testare. ROI-ul retrospectiv nu e criteriu de selecție a politicii — măsurat, e ne-monoton (23,1 / 6,5 / 19,8 / 9,4 / 16,1), deci zgomot.

**12. Piețele speciale sunt în afara scopului V1.** `oracle_engine._special_value_bets()` rămâne neatins, inclusiv inconsistența cunoscută (edge calculat pe probabilitatea brută, nu de-vigată). Fază separată.

**13. Kelly nu apare în Top Value Bets.** Poate rămâne în detaliul meciului, exprimat ca procent din bancă, niciodată ca sumă în euro fără o bancă reală declarată de utilizator.

**14. Prospețimea cotei rămâne `UNKNOWN` în V1.** Timestamp-ul capturii există în `odds_history` și e folosit de `database/queries.py:2129-2131` ca să aleagă cea mai recentă casă de pariuri, dar e aruncat înainte de a ajunge la apelant. Propagarea lui ar atinge fișiere din afara scopului V1. Poarta există, primește `None`, raportează `UNKNOWN` — niciodată `PASS` — și numărul de cazuri se contorizează în shadow. Nu se aproximează (Regula #8).

**15. Nimic nu se șterge.** Fiecare candidat respins rămâne vizibil, cu motivul, în categoria Respinse/Diagnostic.

**16. Identitatea unei selecții în F3 = PRIMA apariție** (decizie proprietar produs, 2026-09-06, varianta (a) din trei prezentate).

Cu `days_ahead=1`, colectarea zilnică vede același meci în două rulări consecutive, cu `run_id` diferit și decizii posibil diferite — cotele se mișcă între cele două momente. Fără o regulă, „150 de selecții" e o mărime ambiguă și rezultatul F3 devine neauditabil retroactiv.

**Regula**: pentru fiecare pereche `(policy_id, fixture_id)`, selecția care contează la numărătoare și la evaluare e cea din **cel mai mic `run_id`** în care acel meci apare. Aparițiile ulterioare rămân persistate — nimic nu se șterge (§15) — dar nu se numără de două ori.

Motivul alegerii, nu doar alegerea:
- e singura variantă care **nu poate fi contaminată de mișcarea pieței**: cu cât selecția e mai aproape de fluier, cu atât cota încorporează mai multă informație, iar un radar care „câștigă" pentru că a așteptat piața nu demonstrează nimic despre model;
- e **consecventă cu lanțul deja construit**: `_load_predictions()` alege deja cea mai VECHE predicție de control per fixture, din același motiv;
- varianta (c) — fiecare rulare ca observație independentă — a fost respinsă pentru că observațiile *nu sunt* independente (același meci, aceeași predicție de bază), deci ar umfla artificial eșantionul și ar face statistica înșelătoare.

Regula e **de evaluare, nu de colectare**: colectorul continuă să scrie toate aparițiile. Deduplicarea se aplică în evaluatorul de rezultate, care nu e încă implementat (vezi „Implementare — stadiu").

---

## Ce NU decide acest ADR

- Nu repară modelul. Supra-dispersia, saturația `g_norm` la 2 goluri/meci, lipsa ajustării la forța adversarului, ELO comprimat la pondere 0,35 și defectul de filtrare pe competiție rămân documentate și predate ca task-uri separate, cu ADR și backtest proprii.
- Nu promite profit. Se demonstrează reducerea variației și eliminarea categoriilor care pierd sistematic; **nu** că vreo politică nouă e profitabilă.
- Nu activează nimic. Toate flagurile pornesc inerte (North Star #3).

---

## Consecințe

**Pozitive**
- Lista devine scurtă și explicabilă: ~3,7-4,6 sugestii/zi față de ~15 azi, fiecare cu motivul afișat.
- Drawdown-ul maxim măsurat scade de la 25,0 la 4,5 unități — proprietate structurală (cotă medie 5,96 vs 2,26), nu dependentă de eșantion.
- Categoriile care pierd sistematic dispar din lista principală: egalurile pe date de fallback (17,9% real vs 21,2% al pieței) și clasa `neutral` (19,5% vs 22,9%).
- Fiecare decizie devine auditabilă: poartă cu poartă, motiv cu motiv, persistat în F2.

**Negative, acceptate conștient**
- Radarul devine ancorat în piață: nu va semnala niciodată o „surpriză" pe care piața o prețuiește ca improbabilă. Dat fiind că modelul e măsurabil mai slab decât cota, e o ancorare rațională — dar e o limitare reală, nu un efect secundar neintenționat.
- Volumul mic înseamnă că F3 are nevoie de timp: la ritmul măsurat, cele 150 de selecții cer 9-13 săptămâni, nu 8.
- Un ecran cu 0 sugestii într-o zi e un rezultat valid, nu un defect — trebuie explicat în UI.

**Neutre**
- Contractul de ieșire al `value_dashboard.collect_value_bets()` rămâne neschimbat în F1; noul selector trăiește în module separate și nu e cablat nicăieri.

---

## Implementare — stadiu

**F1, făcut**: `value_selector.py` (nucleu pur), `value_selector_adapter.py` (mapare 1X2), `value_selector_config.py` (flaguri inerte + profile F2), `tests/test_value_selector.py`, `tests/test_value_selector_purity.py`. 78 de teste noi, 9 mutații verificate, `pytest tests/` verde (3013 passed, 2 skipped).

**F2, FĂCUT — infrastructură + prima rulare reală**: `value_selector_shadow.py` (colector read-only), migrarea 055, `value_selector_shadow.yml` (cron zilnic 09:40 UTC), 55 de teste de colector. Prima rulare reală: `run_id 2026-09-05T15:52Z`, 74 de meciuri × 3 selecții × 13 profile = **2886 de rânduri**, audit post-scriere complet trecut (0 duplicate, 0 leakage, H/X/A complet pe toate cele 962 de perechi, edge-uri recalculate independent în SQL cu 0 abateri, amprente artefact↔DB identice pe 74/74 fixture-uri).

Colectarea zilnică e **ACTIVĂ din 2026-09-06** — `value_selector_shadow_logging_enabled = true` în `model_config` (aprobare explicită proprietar produs). `value_selector_v1_enabled` rămâne **absent**, deci UI-ul e neatins și lista Top Value Bets arată exact ce arăta înainte.

**F2 rămâne NEÎNCHISĂ.** Infrastructura funcționează și datele sunt corecte semantic, dar asta nu înseamnă „experiment valid". Două goluri, ambele blocante pentru F3:

1. **Putere experimentală insuficientă, măsurată** (2026-09-06): cele 13 profile produc, pe setul Top, doar **7 seturi distincte de selecții**. `market_floor_020/025/030/035` și `shrunk_050` dau **exact aceleași 10 selecții, în aceeași ordine**; `market_floor_040` ≡ `shrunk_025` și `ranker_prob_value` ≡ `shrunk_100` (același set, altă ordonare). Cauza e structurală: o selecție care e deja lider de model și trece pragul de 3 pp edge absolut are tipic `fair_p` ∈ [0,40 · 0,60], deci un prag de plauzibilitate de 0,20-0,35 nu are ce tăia — abia 0,40 începe să muște. Pragul **nu e inert în general**: pe granița Longshot/Rejected discriminează clar (30/34/42/50/57). Măsurat pe o singură zi, deci nu e o condamnare — dar F3 nu poate porni până nu se măsoară pe mai multe zile și se colapsează brațele dovedit identice.
2. **Evaluatorul de rezultate nu există**: nimic nu leagă `value_selector_shadow` de `match_history.actual_result` ca să producă rată de reușită / ROI / Brier per politică. Fără el, colectarea adună rânduri pe care nimeni nu le poate scora.

**F3, NEÎNCEPUT și NEAUTORIZAT**: minimum 8 săptămâni ȘI minimum 150 de selecții (numărate conform §16 — prima apariție), politică înghețată, zero scurgere temporală, fără ajustarea pragurilor pe parcurs. Nu poate începe înainte de închiderea celor două goluri de mai sus.

**F4, NEÎNCEPUT**: activare, doar dacă trec simultan toate criteriile GO/NO-GO stabilite de proprietarul produsului — incluzând „ROI > controlul de piață corespunzător + 3 pp", nu „ROI > 0".
