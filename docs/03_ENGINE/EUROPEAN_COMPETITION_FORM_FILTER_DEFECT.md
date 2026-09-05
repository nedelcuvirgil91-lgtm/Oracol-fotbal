# European Competition Form-History Filtering Defect

**Status**: DIAGNOSTIC — defect confirmat, NEREPARAT, deliberat
**Data**: 2026-09-04
**Descoperit în**: auditul Top Value Bets (ADR-071), la investigarea celor 25 de meciuri în care egalul apărea ca rezultat cel mai probabil
**Decizie proprietar produs**: se documentează acum, se repară într-un task separat de arhitectură de date. Nu se aplică niciun fix local.

---

## 1. Simptomul observat

În setul curat de predicții (predicție dovedit anterioară loviturii de start), **25 de meciuri aveau egalul drept rezultat cel mai probabil al modelului**. Prima ipoteză — „modelul are o preferință pentru egaluri" — s-a dovedit falsă la prima verificare.

**Toate cele 25 au probabilități identice, la zecimală:**

```
1 = 34,1%      X = 37,0%      2 = 28,9%
```

Nu 25 de predicții asemănătoare. Aceeași predicție, de 25 de ori.

| Meci | ELO gazdă / oaspete | Istoric gazdă / oaspete | Predicție |
|---|---|---|---|
| Benfica – Aarhus | 1802 / 1597 | 352 / 111 | 34,1 / 37,0 / 28,9 |
| Omonia (CYP) – Lincoln Red Imps | 1501 / 1501 | 3 / 3 | 34,1 / 37,0 / 28,9 |
| Hearts – Benfica | 1576 / 1802 | 151 / 350 | 34,1 / 37,0 / 28,9 |
| Besiktas – Kauno Zalgiris (LTU) | 1661 / 1484 | 175 / 4 | 34,1 / 37,0 / 28,9 |
| Universitatea Craiova – Ararat-Armenia | 1696 / 1475 | 263 / 4 | 34,1 / 37,0 / 28,9 |

Benfica, cu ELO 1802 și 352 de meciuri în istoric, primește exact aceeași predicție ca Lincoln Red Imps, cu ELO 1501 și 3 meciuri. **Nu e o predicție — e o constantă.**

---

## 2. Cauza rădăcină

`supabase_client.get_team_recent_results()`, linia 372:

```python
res = (
    client.table("match_history")
    .select("home_team,away_team,actual_home_goals,actual_away_goals,"
            "actual_result,kickoff_date")
    .eq("league", league)                      # ← AICI
    .or_(f"home_team.eq.{team},away_team.eq.{team}")
    .not_.is_("actual_result", "null")
    .gte("kickoff_date", cutoff)
    .order("kickoff_date", desc=True)
    .limit(last_n)
    .execute()
)
```

Aceasta e sursa canonică Database-First a formei, folosită de `oracle_engine._build_profile()` (linia 1174) ca **primul** nivel al cascadei de 8 niveluri.

Filtrul `.eq("league", league)` cere ultimele 5 meciuri ale echipei **în aceeași competiție**. Pentru un meci de Europa League înseamnă „ultimele 5 meciuri ale lui Benfica în Europa League, în ultimele 365 de zile".

La începutul unei campanii europene, acel număr e zero. Cascada cade nivel cu nivel până la **Level 6 — Neutral defaults** (`oracle_engine.py:1467-1478`):

```python
off_rating = round(baseline * 0.65, 4)
def_rating = round(baseline, 4)
gf = ga = baseline
data_source = "neutral-defaults"
```

Ambele echipe primesc profile identice, construite din `league_baselines`, iar Poisson-ul produce mereu aceeași distribuție. Egalul iese pe primul loc pentru că e ordinea implicită a acelei constante — nu pentru că modelul „crede" ceva despre meci.

**Nu e o problemă de lipsă de istoric.** Istoricul există (Benfica: 352 de meciuri, Craiova: 263). E invizibil din cauza filtrului.

---

## 3. Impactul măsurat

### 3.1 Per competiție (`match_history`, toate predicțiile cu rezultat cunoscut, n=431)

| Competiție | predicții | `neutral` | valori distincte de `prob_draw` |
|---|---:|---:|---:|
| **Europa League** | 37 | **29 (78%)** | **13** |
| **Champions League** | 24 | **19 (79%)** | **7** |
| **Conference League** | 1 | **1 (100%)** | 1 |
| Premier League | 20 | 1 | 20 |
| Serie A | 20 | 0 | 20 |
| MLS | 61 | 0 | 58 |
| Romania SuperLiga | 41 | 0 | 40 |
| Ligue 1 | 19 | 0 | 19 |

Citirea coloanei a treia: în ligile domestice numărul de valori distincte ≈ numărul de meciuri (fiecare meci are predicția lui). În Champions League, **24 de meciuri împart 7 predicții**.

### 3.2 Pe setul curat, fără scurgere temporală (n=365)

- competiții europene: **61 de meciuri**, dintre care **48 pe date `neutral` (79%)**
- ligi domestice: 304 meciuri, dintre care 22 `neutral` (7%)

### 3.3 Calitatea predicțiilor afectate

Cele 25 de meciuri cu egal „lider" s-au terminat: **6 egaluri din 25 = 24%**, față de 37,0% pretins de constantă.

---

## 4. Impact asupra celorlalte componente

| Componentă | Impact | Verificat |
|---|---|---|
| **Forma / off-def rating** | Complet inert în cupele europene — profilele sunt valori implicite, identice pentru orice pereche de echipe | da, prin cele 25 de cazuri |
| **ELO** | Neatins ca date (`home_elo`/`away_elo` sunt corecte în `match_history`), dar **nefolosit** pe această cale: Level 6 se atinge doar când și multiplicatorii ELO lipsesc | da, prin cod (`oracle_engine.py:1454-1478`) |
| **Value Selector** | Ar fi promovat aceste constante drept „valoare" — un edge relativ mare față de o piață care prețuiește corect | da; de aceea ADR-071 impune poarta de calitate a datelor |
| **ML / Blend** | NEinvestigat aici — `FEATURE_COLUMNS` se alimentează din altă cale (`sync/backfill_features.py`). Nu se presupune nimic. | nu |
| **Shadow evaluation** | Cele 48 de predicții intră în evaluarea Challenger ca predicții obișnuite, deși sunt constante. Efectul asupra Brier/log-loss al campionului nu a fost cuantificat. | nu |

---

## 5. Ce s-a făcut ca protecție imediată (fără a atinge motorul)

ADR-071 impune ca stratul de selecție să **respingă** orice candidat construit pe `data_quality = neutral` — și explicit să **nu-l trateze ca „Longshot Value"**: un fallback nu e „valoare cu risc mai mare", e absența informației. Regula e testată (`tests/test_value_selector.py::test_T14_...`), inclusiv cu constanta reală 34,1 / 37,0 / 28,9 ca fixture.

Aceasta e o **plasă de siguranță în aval**, nu o reparație. Predicțiile constante continuă să fie produse, stocate și servite în restul aplicației.

---

## 6. Recomandare de remediere (task separat, NEÎNCEPUT)

**Nu se repară printr-un hack local.** Ștergerea filtrului `.eq("league", league)` din `get_team_recent_results()` ar schimba forma pentru **toți** consumatorii, inclusiv ligile domestice unde funcționează corect azi — o schimbare de contract, deci ADR propriu (regula #5).

Întrebarea reală de arhitectură, de decis explicit, nu implicit:

1. **Ce înseamnă „forma" unei echipe într-o competiție de cupă?** Ultimele 5 meciuri din acea cupă (azi, și e greșit), ultimele 5 meciuri indiferent de competiție, sau ultimele 5 din liga domestică plus cupele?
2. **Cum se tratează diferența de nivel între competiții?** Forma din liga domestică nu e direct comparabilă cu cea din Champions League — aceeași problemă ca lipsa ajustării la forța adversarului, deja documentată în auditul Top Value Bets §3/C3.
3. **Există un `Level` intermediar deja construit care ar trebui să prindă cazul?** `get_team_recent_form_context()` (`oracle_engine.py:1288`) NU e filtrat pe ligă și a fost adăugat pe 2026-08-10 exact pentru „cupele europene fără clasament". În cele 25 de cazuri nu a produs nimic — de investigat separat de ce.

Punctul 3 e cel mai promițător ca punct de plecare: există deja un nivel proiectat pentru acest scenariu, care nu se declanșează. Cauza acelei tăceri e necunoscută azi și **nu se presupune**.

---

## 7. Ce NU s-a atins

`supabase_client.py` · `oracle_engine.py` · `feature_engine.py` · ELO · ML · `match_history` (nicio predicție rescrisă) · niciun flag de producție. Documentul acesta e strict diagnostic.
