# ADR-073 — Persistarea intrărilor de la servire, pe rândul `control`

## Status

**PROPOSED** — 2026-10-14, aprobat explicit de proprietarul produsului pentru implementare („Atunci aprob", după o explicație completă a scopului).

Implementat în cod pe branch-ul `claude/continua-faza-1-adr5-o52jat`. Flagul `serving_inputs_persistence_enabled` e **ABSENT din `model_config`** (= `False`), deci comportamentul în producție e **neschimbat** până la o activare separată, cu confirmare explicită (North Star #3).

Derivat din decizia în așteptare **D-2** (CLAUDE.md), deschisă pe 2026-09-08, reîncadrată pe 2026-10-13 și reverificată pe 2026-10-14.

## Context

### Golul

Oracle construiește, pentru fiecare meci, un set de intrări: ratinguri ofensive/defensive, `form_score`, ELO, H2H, plus ponderile per ligă și baseline-ul ligii. Din ele iese xG, apoi probabilitățile servite. **Se păstrează doar ieșirile.**

Intrările există corect în memorie — `oracle_engine._build_ml_features()` le construiește (linia 1703), `_cache_prediction()` le scrie în `predictions/*.json` (linia 2105). Dar `predictions/` e `.gitignore`-uit (linia 72) și trăiește pe un runner GitHub care se distruge la finalul workflow-ului. **Se calculează corect și dispar.**

Măsurat pe producție (2026-10-14):

| Loc | Ce conține |
|---|---|
| `match_history` | doar IEȘIRI (`prob_*_pred`, `*_xg_pred`, `mc_prob_*`) — nicio coloană de intrări |
| `shadow_predictions.feature_metadata`, `xgboost_v1` | `{}` pe **1307 + 1307** rânduri |
| `shadow_predictions.feature_metadata`, `blend_v1` | `{}` pe **1298 + 1298** rânduri |
| `shadow_predictions.feature_metadata`, `flashscore_team_dna` | **populat pe 1167 din 1167** |

**Nicio predicție Oracle nu poate fi auditată azi până la intrările ei** — încălcare directă a North Star #9 („orice rezultat trasabil complet până la sursă").

### Cât de mică e cauza

Datele nu trebuie construite. Se aruncă la ultima linie:

- `oracle_engine._log_challenger_shadow()` (linia 2212) construiește `ml_features` și le pasează mai departe ca `features`.
- `learning_core/challenger_shadow.py` linia **111** le folosește efectiv, pentru predicția Challenger-ului.
- Liniile **118** și **126** — ambele apeluri `log_shadow_prediction()` — **nu pasează `feature_metadata`**.
- Identic în `learning_core/blend_challenger_shadow.py`, liniile **131** și **139**.

Golul se materializează în `shadow_testing.log_shadow_prediction()`, linia 127: `"feature_metadata": feature_metadata or {}`.

Parametrul `feature_metadata` **există deja** în semnătura funcției (linia 77) și e **dovedit în producție** de `flashscore_team_dna`, care îl populează prin `oracle_engine.py:2009` (1167/1167 rânduri). Nu se construiește un canal nou — se cablează unul existent acolo unde lipsește.

### De ce rândul `control`, și nu `match_history`

Opțiunea de a adăuga o coloană `jsonb` pe `match_history` a fost **analizată și respinsă**. RPC-ul canonic folosește `COALESCE(m.existent, p->nou)` (migrarea 053, liniile 143-165), deci semantica e first-writer-wins: coloana ar îngheța la prima scriere — cu până la 7 zile înainte de meci, prin batch-ul ADR-056 — și ar arunca tăcut fiecare îmbunătățire ulterioară a profilului.

**Exact mecanismul care a produs ADR-072.** Ar fi fost a cincea instanță măsurată a aceleiași clase în acest proiect.

Rândul `control` din `shadow_predictions` se rescrie prin `upsert ... on_conflict` la fiecare rulare (linia 130), deci reflectă mereu ultima stare — și, de la activarea ADR-072 pe 2026-10-14, e **rândul pe care poarta de promovare citește baseline-ul**. Intrările pe rândul care decide promovări = înregistrare completă într-un singur loc.

## Două descoperiri făcute în timpul implementării

Planul preliminar (`BACKLOG_2026-10-13.md` §2) spunea că `ml_features` plus „baseline-ul ligii și cele 5 ponderi" ar fi suficient pentru reproducere. **Verificarea în cod a arătat că nu e.** Ambele descoperiri sunt consemnate aici explicit, nu absorbite tacit (Discovery Rule).

### D1 — `defensive_cap` nu e o pondere per ligă, iar setul necesar are nouă valori din trei surse

`oracle_engine._calibrate_xg()` (liniile 1536-1558) adună parametrii din **trei** locuri distincte:

| Parametru | Sursă | Linia |
|---|---|---|
| `baseline` | `weights["league_baselines"][league]`, fallback `"default"`, apoi `1.25` | 1537-1538 |
| `form_weight`, `base_weight`, `home_advantage`, `away_penalty` | `resolve_league_weights(self.weights, league)` | 1539 |
| `defensive_cap` | ponderile **GLOBALE**, `w.get("defensive_cap", 2.5)` | 1540 |
| `h2h_modifier`, `h2h_meetings` | obiectul `H2HRecord` | 1555-1556 |
| `weather_penalty` | calculat separat în `evaluate_match` | 1557 |

Deci „cele 5 ponderi" era o numărătoare greșită: `defensive_cap` nu trece prin `resolve_league_weights()` deloc. Înregistrarea stochează **valorile rezolvate efectiv pasate lui `calibrate_xg()`**, nu o referință la configurație — altfel o recalibrare viitoare ar face reproducerea imposibilă retroactiv.

Agravant verificat: `resolve_league_weights()` întoarce azi 100% ponderile globale, fiindcă `sample_count` e 0 pentru toate ligile (docstring, liniile 186-194). Asta se poate schimba în ziua în care `auto_recalibration_enabled` se activează — moment în care o înregistrare care stochează doar „ligă + dată" devine inutilă.

### D2 — `ml_features["home_xg_pred"]` înseamnă două lucruri diferite, după cine îl construiește

`_build_ml_features()` primește xG-ul ca argument, iar cei doi apelanți îi dau valori diferite:

| Apelant | Ce pasează | Linia |
|---|---|---|
| `_cache_prediction()` | `pred.home_xg_pre_injury` — **înainte** de penalizarea de accidentări | 2100 |
| `_log_challenger_shadow()` | `home_xg` — **după** penalizare | 2213 |

Penalizarea de accidentări se aplică **între** `calibrate_xg()` și Poisson (liniile 1831-1833). Azi cele două valori coincid, fiindcă `freelf_lineup_snapshot` are 0 rânduri și `apply_injury_penalty()` nu se apelează niciodată — **de aceea ambiguitatea a trecut neobservată.**

Consecința e directă și se aplică gărzii de reproducere: o gardă care recalculează `calibrate_xg()` din înregistrare obține xG **pre**-accidentări, în timp ce coloanele `home_xg`/`away_xg` ale rândului `shadow_predictions` sunt **post**. Ar trece azi și ar cădea exact în ziua în care accidentările se cablează — iar partea greșită ar fi garda, nu datele.

**Nu se repară aici** (ar fi o schimbare de comportament într-un task de trasabilitate). Se tratează prin construcție: înregistrarea stochează explicit ambele xG și starea penalizării, iar garda verifică etape numite, nu presupune că lanțul are un singur pas.

## Decizie

### 1. Structura înregistrării

`oracle_engine._build_serving_record()` — funcție **pură**, fără I/O — produce un dict cu `schema_version`, pe cinci secțiuni:

```
schema_version      1
ml_features         exact dict-ul pasat Challenger-ului (nemodificat)
oracle_inputs       cele nouă valori pasate lui calibrate_xg(), rezolvate
oracle_outputs      home/away_xg_pre_injury, home/away_xg servit, injury_applied
data_quality        home/away — PROASPĂT, nu înghețat
captured_at         ISO 8601 UTC
```

`oracle_inputs` include și cele șase intrări de profil (ratinguri, `form_score`) deși sunt deja în `ml_features` — **deliberat**: `calibrate_xg()` are propria ei vedere asupra lor, iar o gardă de reproducere trebuie să citească dintr-un singur loc, fără să presupună că cele două vederi coincid.

`data_quality` e inclus pentru un motiv concret, plătit în aceeași zi: pe 2026-10-14 am partiționat un rezultat măsurat pe `match_history.home_data_quality` — coloană înghețată prin `COALESCE` — comparată cu predicția SERVITĂ, care se împrospătează nocturn. Am raportat „59-76% din decalaj vine din cascada de formă"; partiția corectă dă **34%**. Un `data_quality` proaspăt, pe același rând cu predicția, ar fi făcut acea eroare imposibilă.

### 2. Doar pe rândul `control`

Rândul `treatment` descrie Challenger-ul, nu Oracle. Intrările Oracle pe un rând de Challenger ar fi o afirmație falsă despre cine a produs ce.

Cele două apeluri `log_shadow_prediction()` din fiecare adapter rămân simetrice în orice altă privință; se adaugă un parametru nou, **opțional**, pasat exclusiv apelului `control`.

### 3. Flag propriu, implicit oprit

`serving_inputs_persistence_enabled`, citit de `oracle_engine`, **nu** de adaptoare — ca adaptoarele să rămână fără cunoaștere de configurație, și ca flagul oprit să însemne zero cost (dict-ul nici nu se construiește). Nu reutilizează `challenger_shadow_logging_enabled`: scrierea intrărilor e o decizie separată de logarea shadow.

### 4. Gardă de reproducere

`tests/test_serving_inputs_persistence.py` recalculează `feature_engine.calibrate_xg()` **exclusiv** din `oracle_inputs` și verifică egalitatea cu `oracle_outputs["home_xg_pre_injury"]` / `away_xg_pre_injury`, la toleranță `1e-9`.

Garda verifică etapa pe care înregistrarea pretinde că o acoperă (intrări → xG pre-accidentări), **nu** lanțul până la probabilitatea servită — acela trece prin penalizarea de accidentări, pe care înregistrarea o raportează ca stare (`injury_applied`), nu o reproduce. O gardă care ar pretinde altceva ar fi falsă, nu mai strictă.

Contrapondere obligatorie: o mutație care schimbă o valoare din `oracle_inputs` trebuie să facă garda să cadă. Fără ea, garda ar putea trece fiindcă reproduce o tautologie.

### 5. Ce NU face acest ADR

- Nu schimbă nicio predicție servită, nicio formulă, niciun parametru matematic.
- Nu adaugă nicio sursă de date externă.
- Nu rescrie retroactiv cele ~2600 de rânduri cu `feature_metadata` gol — ar fi fabricație. Rămân goale, cunoscut, nu ascuns.
- Nu repară D2 (ambiguitatea pre/post accidentări din `_build_ml_features`) — o consemnează și o ocolește prin construcție.
- Nu decuplează scrierea rândului `control` de existența unui Challenger activ (vezi „Consecințe").

## Consecințe

### Pozitive

- Orice predicție servită de la activare încolo devine descompozabilă până la intrările ei (#9).
- `data_quality` proaspăt pe același rând cu predicția — face imposibilă clasa de eroare de partiționare comisă pe 2026-10-14.
- Vechimea formei servite („forma 2", CLAUDE.md §Goluri) devine **măsurabilă** pentru prima dată. Azi nu e cuantificabilă deloc.
- Ablațiile viitoare pot pretinde validitate externă, nu doar internă.

### Negative, acceptate

- **Volum — cifra din plan era greșită, corectată prin măsurare.** `BACKLOG_2026-10-13.md` §2 estima „~1,8 MB". Măsurat efectiv pe un rând realist (statistici avansate populate, nu `None`, altfel măsurătoarea subestimează), serializat ca `jsonb` fără spații: **1065 de octeți**. Deci:

  | | |
  |---|---:|
  | cele 2605 rânduri `control` de azi (`blend_v1` 1298 + `xgboost_v1` 1307) | **2,65 MB** |
  | în continuare, la ~90 de meciuri/zi × 2 rânduri `control` | **~5,5 MB/lună** |

  De trei ori estimarea inițială, și **crește nemărginit**: `shadow_predictions` nu are nicio politică de retenție. Nu e un blocaj la scara de azi (tabela are 6377 de rânduri), dar e un cost recurent asumat conștient, nu o notă de subsol. Dacă devine o problemă, pârghia e retenția pe rândurile `control` ale meciurilor vechi, nu reducerea înregistrării.
- Înregistrarea e o a doua reprezentare a unor valori care există și în `ml_features`. Acceptat deliberat (vezi Decizia 1) — redundanța e în serviciul gărzii.
- Gol de acoperire rămas: rândul `control` se scrie doar când există un Challenger activ pentru familia respectivă. Un meci servit fără niciun Challenger activ nu primește înregistrare. Decuplarea ar rezolva și gaura de acoperire din ADR-072 §D2 (`flashscore_team_dna`, 0 rânduri `control` din 989), **dar e o schimbare de contract proprie** și nu se bundle-uiește aici.

## Stare de execuție — implementat, NEACTIVAT (2026-10-14)

| Element | Stare | Dovadă |
|---|---|---|
| `_resolve_xg_params()` — punct unic de rezolvare | ✅ | `oracle_engine.py`, apelat de `_calibrate_xg` ȘI `_build_serving_record` |
| `_build_serving_record()` — funcție pură | ✅ | zero I/O |
| `_serving_record_if_enabled()` — poarta flagului | ✅ | citită în Oracle Engine, nu în adaptoare |
| Cablarea pe rândul `control`, ambele adaptoare | ✅ | `challenger_shadow.py`, `blend_challenger_shadow.py` |
| Flag în `model_config` | ⛔ **ABSENT (= `False`)** | comportament în producție **neschimbat** |
| `pytest tests/` | ✅ **3427 passed, 2 skipped** | 35 de teste noi |
| **Echivalența numerică a căii de predicție** | ✅ **729.000 de combinații, 0 divergențe** | vezi mai jos |

### Calea de predicție e dovedită neutră, nu presupusă

Refactorizarea lui `_calibrate_xg()` atinge calea de predicție, deci se verifică funcțional, nu doar prin teste unitare (regula din CLAUDE.md §Regulile testelor).

Codul de dinainte (`git show HEAD:oracle_engine.py`) a fost încărcat ca modul separat și rulat în paralel cu cel nou, pe **ponderile reale din `weights.json`** (11 baseline-uri, 11 ligi cu ponderi proprii, plus o ligă inexistentă pentru ramura `default`), peste o grilă de 729.000 de combinații de ratinguri ofensive/defensive, `form_score`, H2H (inclusiv sub și peste pragul `meetings >= 2`) și penalizare de vreme.

**Zero divergențe. xG-ul servit e identic bit cu bit.**

Separat, reproducerea a fost verificată și prin ocolul complet prin JSON (serializare `jsonb` → deserializare → `calibrate_xg`), nu doar în memorie.

### Nouă mutații rulate, toate prinse — două au arătat defecte reale în gărzi

| # | Mutație | Prinsă de |
|---|---|---|
| M1 | `defensive_cap` scos din `_resolve_xg_params` | garda de semnătură + contraponderea |
| M2 | înregistrarea pasată și pe rândul `treatment` | garda „doar `control`" |
| M3 | rezolvarea duplicată inline în `_build_serving_record` | garda de punct unic |
| M4 | poarta flagului ștearsă complet | garda de zero cost — **după întărire** |
| M4b | flagul negat invers | garda de zero cost + cea de flag pornit |
| M4c | implicit `True` în loc de `False` | garda North Star #3 |
| M5 | `ml_features` aliasat în loc de copiat | garda de aliasing |
| M6 | adaptorul citește flagul, în cod | garda AST + cea de „doar `control`" |
| M7 | xG servit stocat ca pre-accidentări | garda etapei de accidentări |

**M4 NU a fost prinsă la prima rulare** — am șters complet poarta flagului și toate cele 35 de teste au trecut. Cauza: garda patcha `_build_serving_record` cu o funcție care ridica `AssertionError`, dar `_serving_record_if_enabled` are un `except Exception` deliberat, iar `AssertionError` **este** o `Exception` — deci era prinsă, funcția întorcea `None`, exact valoarea așteptată. **Plasa de siguranță a codului anula garda testului.** Reparată prin contor, pe care niciun `except` nu-l poate înghiți.

**Garda AST a fost necesară din același motiv recurent**: prima versiune a verificării „adaptoarele nu citesc flagul" căuta numele flagului ca text și a căzut pe **propriul meu docstring**, cel care explica tocmai că adaptorul nu-l citește. A **treia** instanță a acestei clase în proiect, după garda `pipefail` (`test_workflow_log_artifacts.py`, 27 aug, reparată prin `_doar_cod()`) și garda de nume de secrete (`test_poc_isolation.py`, 14 oct). Reparată prin structură, nu prin excepție de interpretat.

### Verificare cerută înainte de activare

1. `pytest tests/` verde, inclusiv garda de reproducere și contraponderea ei prin mutație.
2. O rulare de noapte cu flagul **oprit**, care confirmă comportament identic — `feature_metadata` rămâne `{}`, verdictele neschimbate.
3. `UPDATE model_config` arătat exact și confirmat explicit (North Star #6).
4. La prima rulare de după activare: `feature_metadata` populat pe rândurile `control` ale `xgboost_v1`/`blend_v1`, `{}` pe `treatment`, iar `schema_version = 1`.
