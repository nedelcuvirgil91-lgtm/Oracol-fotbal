# ADR-058 — Identitate canonică de echipă: vocabular unic, normalizare la fiecare writer

**Status**: PROPUS (F1 livrat; F2 livrat; **F3 BLOCAT** până la GO explicit)
**Data**: 2026-08-21
**Derivat din**: auditul de identitate 2026-08-20/21 (artefacte: `docs/00_GOVERNANCE/identity_audit_F0/`)
**Nu modifică**: ADR-002 (om în buclă) · ADR-016 (FSM) · ADR-025 (upsert canonic) · ADR-036 (Canonical Feature Ownership) · ADR-053 (Database-First) · criteriile de promovare

---

## 1. Context

### 1.1 Ipoteza inițială a fost INFIRMATĂ

Presupunerea de pornire — „writer-ul Flashscore nu normalizează" — este **falsă**.
Lanțul real, verificat linie cu linie:

```
providers/flashscore/normalizer.py::_extract_team_names()   (nume BRUT)
  → normalize_match_statistics()
  → providers/flashscore/persistence.py:135
  → database/queries.py:2037  upsert_match_and_get_id()
        payload = _strip_none_values(_normalize_team_fields(row))   ← NORMALIZEAZĂ
  → RPC upsert_match_canonical
  → match_history
```

Wiring-ul a fost deja reparat la P3.5 (`docs/03_ENGINE/TEAM_IDENTITY_AUDIT.md`,
2026-07-15, 137 echipe fragmentate). Nu s-a regresat.

### 1.2 Cauza reală

`mappings.py:968-991` — `normalize_team_name()` returnează inputul
**neschimbat** (linia 991) când nu găsește potrivire exactă în
`ALIAS_TO_CANONICAL`. Comportament **deliberat**: fuzzy prefix-matching a fost
eliminat la v1.2 (`mappings.py:982-990`) după 141+ fuziuni greșite
(„Paris FC" → „Paris Saint-Germain").

> **Root cause: vocabular incomplet, nu mecanică lipsă.**
> 781 alias-uri / 281 cluburi canonice vs. **1.252 nume distincte** în `match_history`.

### 1.3 Problema este sistemică, nu specifică Flashscore

| Sursă | Prima apariție | Nume cu sufix |
|---|---|---|
| openfootball | **2024-09-17** | 38 |
| Flashscore FDL | 2026-07-14 | 147 |

Ambele trec **prin** normalizare. Kaggle/historical și football-data.org
contribuie cu vocabulare proprii (`For Sittard` vs. `Fortuna Sittard`,
`Heerenveen` vs. `SC Heerenveen`).

### 1.4 Impact măsurat în producție — nu cosmetic

| Club | ELO servit (lanț rupt) | ELO real (lanț canonic) | Eroare |
|---|---|---|---|
| Zwolle | 1503 | 1448 | **+55** |
| Heerenveen | 1523 | 1556 | −33 |

~88 puncte de distorsiune relativă într-un singur meci. ELO intră în
`_elo_to_multiplier()` (`oracle_engine.py:1061-1062`, `elo_blend_weight=0.35`)
→ predicție → value bet afișat (`ELITE Home Win @ 1.58, Model 77,2%, +30,1%`).

Cascada `_build_profile()` cade de la Level DB la Level FS când echipa are
< `MIN_DB_MATCHES=3` meciuri sub numele fragmentat (Heerenveen: 2 vs. 32 reale).

### 1.5 Un writer fără normalizare

`upsert_match_context()` (`database/queries.py:2212-2229`) persistă
`home_team`/`away_team`/`subject_team` fără normalizare. `persistence.py:154-156`
îi transmite numele **brute**, fiindcă `_normalize_team_fields()` copiază rândul
(`queries.py:55`, `out = dict(row)`) și nu mutează `base`.
Consumator afectat: `get_team_recent_form_context()` = Level FS2 al cascadei.

---

## 2. Decizie

1. **Un club = exact un șir canonic.** `mappings.TEAM_ALIASES` e sursa unică de
   adevăr pentru vocabular. Nicio tabelă Supabase, niciun serviciu și niciun
   fișier de configurare nu dețin o hartă paralelă. *(Respins explicit:
   `team_identity_alias` ca tabelă persistentă — ar crea a doua sursă de adevăr,
   nu ar fi testabilă fără rețea și nu ar trece prin review.)*

2. **Orice writer care persistă un nume de echipă trece prin
   `normalize_team_name()`**, la punctul unic de scriere, nu în fiecare sursă.
   Impus prin gardă AST, nu prin convenție.

3. **Sufixul de țară `(CCC)` e o transformare structurală de CĂUTARE, niciodată
   o ieșire.** Se aplică exact ca `_STRIP_SUFFIXES`/`_STRIP_PREFIXES`
   (`mappings.py:959-963`): dacă forma dezbrăcată nu e cunoscută, numele
   original rămâne **neschimbat**. **Fuzzy matching rămâne interzis.**

4. **Nicio fuziune fără dovadă.** Potrivirea de șiruri nu e dovadă. Dovada =
   aceeași ligă + complementaritate temporală sau explicație de sursă + zero
   auto-confruntări + niciun al treilea club care poate revendica numele.

5. **Listele se generează mecanic.** F3 consumă
   `docs/00_GOVERNANCE/identity_audit_F0/class_a_bases.csv`, niciodată o listă
   transcrisă dintr-un raport. *(Trei erori de numărare manuală au fost deja
   produse și corectate — vezi §5.)*

---

## 3. Domeniu de aplicare

### 3.1 CE face acest ADR

- F1: acest document
- F2: normalizare la `upsert_match_context()`, `log_shadow_prediction()`,
  `save_consensus_capture_sample()` + teste + gardă AST
- F3 (**blocat**): regula de sufix + clasa A2 + cele 54 baze canonice

### 3.2 CE NU face

- ❌ Nicio reconciliere a datelor istorice
- ❌ Nicio deduplicare
- ❌ Niciun rebuild ELO/formă/H2H/`BACKFILL_COLUMNS`
- ❌ Nicio decizie ML, re-antrenare, promovare sau rollback
- ❌ Nicio migrare de schemă, niciun trigger, niciun flag

Toate → **ADR-059**.

---

## 4. Out-of-Scope Discoveries

Per **Discovery Rule** (CLAUDE.md): descoperiri făcute în timpul implementării,
neidentificate în scopul aprobat. Documentate, **neatinse**.

### D1 — 208 meciuri duplicate ascunse de fragmentare

Azi: **0** chei naturale duplicate. După fuziunea clasei A: **208** grupuri în
coliziune, 208 rânduri surplus.

Exemplu: `SC Heerenveen — Feyenoord, 2025-05-18, Eredivisie` există de două ori
(`fd_499297` + `kaggle_9fcbb525661fb1a8`), sub vocabulare diferite.

**Implicație**: ELO procesează același meci de două ori; datasetul ML îl conține
de două ori. **Un `UPDATE` de nume NU e suficient pentru reconciliere.**

`DELETE` e structural imposibil: **5 tabele** referențiază `match_history.id` cu
`delete_rule = NO ACTION` (`flashscore_data_completeness`,
`flashscore_match_context`, `match_events`, `match_statistics_extended`,
`player_match_stats`) + auto-referința `superseded_by`.

→ **ADR-059/F4.** Cere: alegerea rândului survivor, păstrarea provenance-ului,
mecanism reversibil.

### D2 — F3 nu este read-only în efect (fereastra de duplicare)

`normalize_team_name()` se aplică **și la citire** (`oracle_engine.py:1035`).
Un alias nou schimbă instantaneu ambele capete.

Verificat prin citirea sursei live a RPC-ului (`pg_get_functiondef`):
```sql
SELECT * INTO v_existing FROM match_history
WHERE superseded_by IS NULL
  AND lower(trim(home_team)) = lower(trim(v_home))    -- potrivire EXACTĂ
  ...
IF FOUND THEN ... UPDATE ... ELSE ... INSERT ...
```
`'nottingham'` ≠ `'nottingham forest'` → **NOT FOUND → INSERT rând nou**.
`hard_conflict` **nu** se declanșează (se verifică doar când un rând E găsit).

Verificat prin citirea `oracle_api.get_matches_for_week()` (liniile 1530-1534):
lista Level-DB e folosită **ca atare**; `seen_keys` previne doar duplicatele
*surselor ulterioare*. Nu există dedup pe lista din `match_history` la niciun
pas (1580-1588).

→ **50 rânduri** ar produce duplicate observabile în UI, și dublare de
`shadow_predictions` (Challenger).

**`superseded_by` NU e aplicabil**: e FK către rândul care înlocuiește; la
momentul F3 succesorul **nu există încă**. Nu poți marca un rând ca înlocuit
înainte ca înlocuitorul să existe.

### D3 — fixture de test în producție

```
fixture_id: shadow-probe-d2b0d9e2   kickoff_date: 2099-01-01   (1 rând)
```
Al treilea set de fixture-uri de test găsit în producție, după
`gate_validation_test` (`challengers`/`model_champions`/`training_runs`/
`challenger_evaluations`, 2026-07-14). Provine din `scripts/shadow_probe.py`.

→ **ADR-059.** Neatins.

---

## 5. Corecții ale auditului manual

Trei erori produse prin numărare/transcriere manuală, toate descoperite prin
re-verificare mecanică:

| # | Mărime | Manual | Real |
|---|---|---|---|
| E1 | rânduri orfane viitoare | 85 | **50** |
| E1b | rânduri terminate afectate | 843 | **878** |
| E2 | baze deja canonice | 25 | **31** |
| E3 | perechi cu bază existentă | 84 | **85** |

Consecință normativă → Decizia §2.5.

---

## 6. Consecințe

### Dacă F3 se aprobă
- ✅ Orice meci nou intră corect, indiferent de sursă
- ✅ Level DB redevine funcțional pentru cluburile fragmentate (Heerenveen: 2 → 34 meciuri)
- ✅ ELO servit se corectează **fără nicio scriere în DB** (citirea se re-rutează)
- ⚠️ Se deschide fereastra D2 — **necesită mecanism de închidere aprobat separat**
- ⚠️ Cele 878 rânduri terminate rămân sub identități vechi până la F4

### Dacă F3 se respinge (status quo)
Trebuie acceptat explicit, în scris, că:
- ELO-ul servit rămâne distorsionat (±55 puncte măsurat) și intră în value bets
- Fiecare sezon nou adaugă variante noi (Flashscore descoperă continuu)
- Datasetul ML acumulează contaminare derivată

### Ce NU se schimbă în niciun caz
`match_history` · `shadow_predictions` · `consensus_capture_samples` ·
`training_runs` · `model_champions` · `challengers` · `elo_ratings` ·
`elo_history` · cele 20 `BACKFILL_COLUMNS` · `oracle_engine.py` ·
`ml_predictor.py` · `sync/backfill_features.py` · `learning_core/*` ·
orice workflow · orice migrare · orice trigger.

---

## 7. Stare de implementare

| Fază | Stare |
|---|---|
| F0 — inventar + artefacte mecanice | ✅ livrat (`identity_audit_F0/`) |
| F1 — acest ADR | ✅ livrat |
| F2 — hardening writeri | ✅ livrat |
| V5 — traseu duplicare → UI | ✅ verificat (§4/D2) |
| V6 — comportament RPC | ✅ verificat (§4/D2) |
| **F3 — vocabular** | 🔴 **BLOCAT** — cere GO explicit + mecanism pentru D2 |
| F4 — reconciliere + rebuild | ⛔ ADR-059, neînceput |
