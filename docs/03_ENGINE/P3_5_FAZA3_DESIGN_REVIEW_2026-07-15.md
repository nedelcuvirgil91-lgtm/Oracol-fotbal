# P3.5 — Faza 3: Design Review — Consolidarea istoricului de identitate a echipelor

**Status**: Document de proiectare — zero cod scris, zero migrare rulată, zero rând din `match_history` atins. Precondiție explicită, cerută de Chief Architect, înainte de orice implementare a Faza 3 din `TEAM_IDENTITY_AUDIT.md`. Acest document demonstrează, pe bază de cod citat exact, concluzia „Writer Protection blochează recalcularea" din revizuirea de arhitectură anterioară, apoi proiectează strategia de reset controlat cerută explicit: identificare exactă a coloanelor afectate, scop exact al reset-ului, reutilizare 100% a `run_backfill()`, **zero modificare a Regulei #13**.

**Bază de plecare**: `docs/03_ENGINE/TEAM_IDENTITY_AUDIT.md` (Faza 1-4, 137 echipe canonice, 10.835 apariții „orfane", 10,1% din volum), `docs/03_ENGINE/canonical_team_mapping.csv` (288 rânduri, sursa de adevăr pentru maparea raw→canonical), revizuirea de arhitectură anterioară din această sesiune (verificare Writer Protection).

---

## 1. Demonstrația riguroasă: Writer Protection blochează recalcularea

### 1.1 Mecanismul exact, citat din sursă

`sync/backfill_features.py:110-113`:
```python
def _missing_feature_columns(match: dict) -> list[str]:
    """Subsetul din FEATURE_COLUMNS ale căror valori curente sunt NULL
    pentru acest rând. Listă goală == rând complet, de sărit fără UPDATE."""
    return [col for col in FEATURE_COLUMNS if match.get(col) is None]
```

Punctul de scriere efectivă, `sync/backfill_features.py:892-919`:
```python
missing = _missing_feature_columns(match)
if missing:
    computed = { "home_elo": home_elo, ... }   # calculat ÎNTOTDEAUNA, indiferent de completitudine
    features = {col: computed[col] for col in missing if computed[col] is not None}
```

`computed[col]` reflectă STAREA CURENTĂ a tracker-ului (deci ar fi corect, pe un istoric consolidat) — dar `col` ajunge în payload-ul de scriere DOAR dacă era deja `NULL`. **O coloană deja populată nu e niciodată reevaluată, indiferent cât de diferit ar calcula tracker-ul valoarea.** Verificat, nu presupus.

### 1.2 De ce trackerele AR calcula corect pe date consolidate

Toate tracker-ele relevante sunt `dict`-uri cheiate pe stringul brut citit din rând, nu pe un ID canonic separat:

| Tracker | Coloane produse | Cheie internă | Citat |
|---|---|---|---|
| `ELOTracker` | `home_elo`, `away_elo` | `dict[str, float]`, cheie = `team: str` | `sync/backfill_features.py:225` |
| `FormTracker` | `home_form_score`, `away_form_score` | `dict[str, list]`, cheie = `team: str` | `sync/backfill_features.py:277` |
| `H2HTracker` | `h2h_modifier`, `h2h_meetings` | `dict[tuple, list]`, cheie = `(min(home,away), max(home,away))` — **pereche de STRING-uri**, nu ID-uri | `sync/backfill_features.py:478,481-482` |
| `CornerCardTracker` | `home_corner_avg_recent`, `away_corner_avg_recent`, `home_card_avg_recent`, `away_card_avg_recent` | `dict[str, list]`, cheie = `team: str` | `sync/backfill_features.py:427` (clasă), tipar identic cu `FoulsTracker` |
| `FoulsTracker` | `home_foul_avg_recent`, `away_foul_avg_recent` | `dict[str, list]`, cheie = `team: str` | `sync/backfill_features.py:364` |
| `ShotCountTracker` | `home_shot_avg_recent`, `away_shot_avg_recent` | `dict[str, list]`, cheie = `team: str` | `sync/backfill_features.py:392` |

Apelul din buclă, `sync/backfill_features.py:858-859`:
```python
home = match.get("home_team", "")
away = match.get("away_team", "")
```

**Corecție față de analiza anterioară**: lista completă de coloane afectate NU e cea de 10 coloane citată în revizuirea precedentă (ELO + 4 perechi `*_avg_recent`), ci **toate cele 18 coloane din `FEATURE_COLUMNS`** (`sync/backfill_features.py:87-107`) — inclusiv `home_offensive_rating`/`home_defensive_rating`/`away_offensive_rating`/`away_defensive_rating` (derivate din `elo_before` + `form_tracker` + `shots_tracker`, prin `team_pre_match_rating()`, `sync/backfill_features.py:695-735`) și `h2h_modifier`/`h2h_meetings` (H2HTracker, afectat identic, plus un risc suplimentar: cheia lui e o PERECHE de string-uri, deci o singură echipă fragmentată corupe istoricul H2H al TUTUROR adversarilor ei, nu doar al ei însăși).

**Verdict §1**: concluzia anterioară e ✅ confirmată și acum **completată** — scopul recalculării e mai larg decât s-a estimat inițial.

---

## 2. Identificarea EXACTĂ a coloanelor derivate afectate

Toate cele 18 coloane din `FEATURE_COLUMNS` (`sync/backfill_features.py:87-107`):

```
home_elo, away_elo,
home_form_score, away_form_score,
home_offensive_rating, home_defensive_rating, away_offensive_rating, away_defensive_rating,
h2h_modifier, h2h_meetings,
home_corner_avg_recent, away_corner_avg_recent,
home_card_avg_recent, away_card_avg_recent,
home_foul_avg_recent, away_foul_avg_recent,
home_shot_avg_recent, away_shot_avg_recent
```

Nu există altă coloană derivată prin tracker în afara acestei liste — `_missing_feature_columns()` operează exclusiv pe `FEATURE_COLUMNS`, deci acest set e complet și verificabil direct din constanta sursă.

---

## 3. Scopul EXACT al reset-ului — nu doar rândurile cu nume schimbat

### 3.1 Eroarea la care aș fi ajuns cu o proiectare naivă

Instinctul evident ar fi: „resetează doar rândurile unde `home_team`/`away_team` se schimbă la rescrierea canonică". **Această regulă e insuficientă și ar produce staleness silențioasă.**

Exemplu concret, din structura reală a `canonical_team_mapping.csv`: Manchester United apare sub 3 variante (`Man Utd`, 153 meciuri; `Manchester United FC`, presupus; `Manchester United`, forma deja canonică — vezi rândurile Atletico Madrid/Inter din CSV pentru tiparul exact, linia 2-7). Un meci **Arsenal (acasă) vs. Manchester United (deplasare)**, unde `away_team` era DEJA scris corect ca `"Manchester United"` înainte de Faza 3 — stringul lui NU se schimbă la rescriere. Dar `away_shot_avg_recent` al acelui rând reflectă istoricul lui Manchester United calculat de `ShotCountTracker` ÎNAINTE de consolidare — adică fără cele 153 de meciuri jucate sub `"Man Utd"`. După consolidare, istoricul corect al lui Manchester United include acele meciuri. **Rândul Arsenal-Manchester United trebuie resetat, deși niciun string din el nu s-a schimbat.**

### 3.2 Regula corectă de scop

Reset pe **toate rândurile unde `home_team` SAU `away_team` (evaluate DUPĂ rescrierea la forma canonică, pasul care precede reset-ul) sunt egale cu oricare din cele 137 de nume canonice afectate** din `canonical_team_mapping.csv` — nu doar rândurile al căror string s-a modificat literal. Această regulă:

- Prinde automat cazul de mai sus (Arsenal vs. Manchester United), pentru că după rescriere `away_team = "Manchester United"` intră direct în filtru.
- Prinde automat cazurile H2H — orice adversar (afectat sau nu) al unei echipe fragmentate are propriul `h2h_modifier`/`h2h_meetings` corupt, dar rândul lui va conține deja numele canonic al echipei fragmentate în `home_team`/`away_team`, deci intră în același filtru simplu.
- NU atinge meciuri complet neafectate (ex. Arsenal vs. Chelsea, ambele deja stabile) — filtrul rămâne minimal, nu resetează tot `match_history`.

### 3.3 De ce ordinea operațiilor contează

Rescrierea `home_team`/`away_team` la forma canonică TREBUIE să preceadă reset-ul coloanelor derivate — altfel filtrul `WHERE home_team IN (...)` nu poate prinde rândurile care încă poartă variante brute (`"Man Utd"`), doar pe cele deja canonice.

---

## 4. Strategia de reset controlat — propunere, nerulată

### 4.1 SQL propus (arătat, nu executat)

**Pasul A — rescrierea identității** (deja conceptual acoperit de audit, mecanismul exact — `UPDATE` per-mapare sau un singur `UPDATE ... CASE`, folosind exact `normalize_team_name()` din `mappings.py`, aceeași funcție deja folosită de Faza 1 la scriere — rămâne detaliat separat, în planul de migrare final, nu în acest document).

**Pasul B — reset controlat, DUPĂ Pasul A**:
```sql
UPDATE match_history
SET home_elo = NULL, away_elo = NULL,
    home_form_score = NULL, away_form_score = NULL,
    home_offensive_rating = NULL, home_defensive_rating = NULL,
    away_offensive_rating = NULL, away_defensive_rating = NULL,
    h2h_modifier = NULL, h2h_meetings = NULL,
    home_corner_avg_recent = NULL, away_corner_avg_recent = NULL,
    home_card_avg_recent = NULL, away_card_avg_recent = NULL,
    home_foul_avg_recent = NULL, away_foul_avg_recent = NULL,
    home_shot_avg_recent = NULL, away_shot_avg_recent = NULL
WHERE home_team = ANY(:canonical_names_afectate)
   OR away_team = ANY(:canonical_names_afectate);
```
unde `:canonical_names_afectate` = lista celor 137 de nume canonice din `canonical_team_mapping.csv` unde a existat o consolidare reală (excluzând rândurile unde `raw_name = canonical_name`, care nu reprezintă fragmentare).

**Pasul C — reutilizare 100% `run_backfill()`, zero cod nou**:
```bash
python sync/backfill_features.py --dry-run     # verificare: câte rânduri intră în "missing" acum
python sync/backfill_features.py               # scriere reală
```
Motivul pentru care acest pas e suficient, demonstrat din cod: bucla principală din `run_backfill()` procesează **toate** rândurile din `all_matches` în ordine cronologică, indiferent dacă un rând anume are nevoie de scriere — actualizarea stării tracker-elor e necondiționată (`sync/backfill_features.py:923`: „Actualizăm starea tracker-elor (indiferent dacă meciul era deja procesat)"). Asta înseamnă că tracker-ele vor parcurge corect ÎNTREGUL istoric consolidat (Pasul A deja aplicat), indiferent care rânduri au fost resetate la Pasul B — iar `_missing_feature_columns()` va scrie valorile proaspăt calculate EXACT în rândurile resetate (acum `NULL`), lăsând neatinse rândurile echipelor neafectate (care rămân `NOT NULL`, deci sărite, corect — valorile lor nu erau greșite).

**Zero modificare a Regulei #13** — `_missing_feature_columns()` rămâne exact cum e azi. Reset-ul de la Pasul B nu ocolește garda, ci îi creează precondiția (`NULL`) pe care garda deja o gestionează corect.

### 4.2 De ce NU o variantă alternativă (flag de forțare pe `run_backfill()`)

O alternativă ar fi un parametru `force=True` pe `run_backfill()`/`_missing_feature_columns()` care să ignore gating-ul. Resping explicit această variantă: ar slăbi exact invariantul care protejează restul sistemului de suprascrieri accidentale (motivul pentru care Regula #13 există în primul rând, precedent `BACKFILL_NON_DESTRUCTIVE_STRATEGY_2026-07-12.md`) — și ar introduce cod nou, netestat, într-un fișier deja validat prin 380+ teste. Reset-ul controlat (Pasul B) atinge același rezultat cu zero cod nou și zero risc asupra gărzii existente.

---

## 5. Ordinea exactă a operațiilor (propunere, de aprobat)

1. Confirmare Faza 2 (perioadă de observație) încheiată — precondiție deja stabilită în decizia originală P3.5.
2. Plan de migrare Faza 3 complet, cu SQL exact pentru Pasul A (rescriere identitate) — document separat, nescris încă.
3. **Raport „înainte"**: `SELECT` complet (snapshot) al tuturor rândurilor afectate (identificate prin `canonical_team_mapping.csv`) — home_team, away_team, toate cele 18 coloane derivate — salvat înainte de orice scriere. Servește atât ca dovadă „ce se schimbă" (cerută explicit în decizia originală P3.5), cât și ca bază de rollback.
4. Execuție Pasul A (rescriere identitate) — arătat explicit înainte de rulare, per `supabase-safety`.
5. Execuție Pasul B (reset controlat, SQL de mai sus) — arătat explicit înainte de rulare.
6. `python sync/backfill_features.py --dry-run` — verificare număr de rânduri „missing" (trebuie să corespundă cu rândurile resetate la Pasul B, nu mai mult, nu mai puțin).
7. `python sync/backfill_features.py` — scriere reală.
8. **Raport „după"** + verificare de consistență (extensie a sanity check-ului deja folosit la P7.1): (a) numărul total de rânduri din `match_history` neschimbat (pur UPDATE, zero INSERT/DELETE); (b) zero valori negative/NaN/infinite pe cele 18 coloane; (c) eșantion de comparație înainte/după pentru echipele afectate — valorile TREBUIE să difere (dovadă că reset+recompute a avut efect real, nu doar cosmetic); (d) eșantion de comparație pentru echipe NEAFECTATE — valorile TREBUIE să rămână identice (dovadă de zero coliziune).
9. `pytest tests/ -q` — 100% verde, fără regresie.
10. **Abia apoi** — reevaluarea P3 (MOV), condiționată de o îmbunătățire măsurabilă a fidelității ELO, cu metodologia deja stabilită în `P3_0_DESIGN_REVIEW_ELO_MOV_2026-07-15.md` §3, rulată pe Replay A proaspăt (nu reciclat).

---

## 6. Plan de rollback

- Raportul „înainte" (pasul 3 de mai sus) conține toate valorile originale — restaurabil printr-un `UPDATE` invers, dacă Pasul B/C produce rezultate neașteptate.
- `normalize_team_name()` e determinist și idempotent — o reluare completă a Faza 3 de la zero (dacă ceva eșuează la jumătate) e sigură, fără risc de stare parțial coruptă dincolo de „unele rânduri au coloane derivate `NULL` temporar" — o stare deja cunoscută și sigură (identică cu o coloană nou-adăugată, precedent P7.1).
- Nicio scriere din acest plan nu atinge `actual_result`/`actual_home_goals`/`actual_away_goals` — rezultatele rămân neatinse pe tot parcursul.

## 7. Ce NU decide acest document

- SQL-ul exact pentru Pasul A (rescrierea `home_team`/`away_team`) — rămâne partea „sensibilă" menționată în decizia originală P3.5, de detaliat separat, cu lista completă a celor 137 de mapări.
- Lista finală, exactă, a celor 137 de nume canonice pentru clauza `WHERE` — se extrage direct din `canonical_team_mapping.csv`, filtrat pe rânduri unde `raw_name != canonical_name`.
- Dacă fidelitatea ELO se îmbunătățește suficient pentru a redeschide P3 — decizie separată, ulterioară, pe baza rezultatelor reale.
- Nimic din acest document nu autorizează execuția — rămâne strict design, în așteptarea aprobării exprese.
