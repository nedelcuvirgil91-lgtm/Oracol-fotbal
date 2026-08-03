# ADR-047 — Redenumire `dna_weight` → `base_weight`

**Status**: **APROBAT** — 2026-08-03, de proprietarul produsului, cu o completare obligatorie (§6.0, „Deployment Rule") adăugată explicit la aprobare.

**Data**: 2026-08-03

**Context declanșator**: EPIC „ML Activation & Oracle Evolution", Pasul 7 (`docs/00_GOVERNANCE/ML_ACTIVATION_IMPLEMENTATION_PLAN.md` §2.2/§6.2 pasul 7). Reclasificat explicit de Architecture Review (2026-08-03) ca necesitând ADR — versiunea inițială a planului marcase greșit acest pas ca „schimbare cosmetică, fără ADR"; investigația de mai jos confirmă că nu e cazul.

---

## 1. De ce `dna_weight` NU mai reflectă semantic rolul real al ponderii

Formula din `feature_engine.calibrate_xg()`:

```python
home_xg = home_offensive_rating * away_def_mod * baseline * (form_weight * home_form_mod + dna_weight) * home_advantage
away_xg = away_offensive_rating * home_def_mod * baseline * (form_weight * away_form_mod + dna_penalty) * away_penalty
```

`dna_weight` e o constantă adunată necondiționat la `form_weight * form_mod` — **nu e modulată de nicio valoare dinamică a echipei**, nu citește niciun semnal real de „ADN" al echipei. Numele e moștenit dintr-un design mai vechi (confirmat: nicio funcție din `feature_engine.py` nu leagă acest parametru de vreun calcul specific de identitate a echipei).

Mai grav — confirmat în `ORACLE_ENGINE_AUDIT.md` §6.2 — azi coexistă **trei concepte diferite**, toate purtând cuvântul „DNA" în proiect:

1. **UI „Team DNA"** (`app.py`) — cardul OFF/DEF/Formă/ELO, alimentat de `TeamProfile` — ACESTEA intră în predicție.
2. **`dna_weight`** (obiectul acestui ADR) — constantă în formulă, fără legătură cu niciun semnal „DNA" real.
3. **„Team DNA Flashscore"** (`home_flashscore_dna`) — xG real/posesie reală din Flashscore, PUR informativ, NU intră în predicție.

Riscul concret, nu ipotetic: orice dezvoltator (uman sau Claude Code, într-o sesiune viitoare) care citește `calibrate_xg(..., dna_weight=...)` poate presupune că Team DNA Flashscore (#3) alimentează deja formula de predicție prin acest parametru — fals. Numele induce o legătură care nu există în cod.

## 2. De ce `base_weight` e o denumire mai corectă

Analiza formulei: `form_weight * form_mod + dna_weight`, unde `form_mod ∈ [0.80, 1.20]` (`form_mod = 0.80 + form_score*0.40`). Cu valorile implicite (`form_weight=0.60`, `dna_weight=0.40`): `form_weight + dna_weight = 1.00` — cei doi parametri sunt **complementari**, formând o combinație ponderată care se centrează pe 1.0 când form_score e neutru (0.5 → form_mod=1.0 → `0.60*1.0+0.40=1.00`).

Rolul real al `dna_weight`: e **ponderea componentei de bază (non-formă)** din multiplicator — partea care rămâne fixă indiferent de forma recentă a echipei, complementară lui `form_weight`. `base_weight` numește exact acest rol, fără să sugereze o legătură inexistentă cu vreun semnal de „DNA" al echipei. Verificat: nu există în proiect niciun precedent de nume `base_weight` deja folosit cu alt sens (grep exhaustiv, zero coliziuni).

**Nicio schimbare de valoare sau comportament** — doar numele cheii, în toate locurile unde apare.

## 3. Confirmare — aceasta E o schimbare de contract, nu un detaliu de implementare

Verificat prin grep exhaustiv pe tot repo-ul (`dna_weight`, whole-word), **12 fișiere**, dintre care 6 de producție, 1 test, 1 fișier de date local, plus tabela Supabase live:

| Componentă | Ce anume | Tip modificare |
|---|---|---|
| `oracle_engine.py` | `DEFAULT_WEIGHTS["dna_weight"]` (global), `DEFAULT_LEAGUE_WEIGHTS`-equivalent (11 intrări per-ligă, linii 180-190), apel `calibrate_xg(dna_weight=lw["dna_weight"])` (linia 1205), un al doilea dict implicit (linia 2030, folosit pentru payload UI/config), cheie abreviată `"dna_w"` în payload-ul de explicabilitate (linia 2045) | Cod |
| `feature_engine.py` | Parametrul `dna_weight` din semnătura `calibrate_xg()`, folosit în formulă (liniile 141, 158-159); `resolve_league_weights()` — cheia din blend (linia 208) | Cod |
| `recalibration.py` | 8 referințe — logica de nudge adaptiv per-ligă citește/scrie `dna_weight` (liniile 73, 210, 233, 258, 267, 294, 300, 307) — **inertă azi** (`auto_recalibration_enabled=False`, confirmat Pasul 1), dar codul există și trebuie actualizat pentru corectitudine viitoare | Cod |
| `sync/bootstrap_league_learning.py` | Bootstrap al ponderilor per-ligă (linia 67) | Cod |
| `explainability.py` | Construcția payload-ului de shadow/explicabilitate (liniile 92, 151) | Cod |
| `app.py` | **UI Streamlit** — slider-ul de configurare ponderi (linia 875, label vizibil utilizatorului: `"dna_weight"`) și cheia de write-back în dict-ul de config (linia 884) | Cod + **UI vizibilă** |
| `tests/test_explainability.py` | Docstring + 3 asserții pe cheia `dna_weight` (liniile 27, 329, 388, 480) | Test |
| `weights.json` (local, fallback) | Cheie `dna_weight` la nivel global ȘI în fiecare din cele 11 intrări `league_weights[<ligă>]` (12 apariții totale) | **Date persistate local** |
| `model_weights` (Supabase, proiect `Prediction`, tabelă singleton `id=1`, coloană `data` jsonb) | Structură identică cu `weights.json` (confirmat anterior byte-identic) — aceeași cheie `dna_weight`, global + 11 ligi | **Date persistate LIVE, producție** |
| `docs/03_ENGINE/PREDICTOR_ROADMAP_V4.md` | Descrie parametrii reali ai `calibrate_xg()` — ar deveni stale dacă nu e actualizat | Documentație (stare curentă, nu istoric) |
| `docs/00_GOVERNANCE/{ARCHITECTURE_STATE,ML_ACTIVATION_IMPLEMENTATION_PLAN,ORACLE_ENGINE_AUDIT,ORACLE_VS_ML_REPORT}.md` | Mențiuni descriptive ale acestui EPIC | Documentație (proprie EPIC, nu istoric extern) |

**Nu există RPC/coloană SQL dedicată** — `model_weights.data` e o singură coloană `jsonb`, deci nu e nevoie de o migrare de schemă (`ALTER TABLE`), doar de o actualizare de conținut (`UPDATE ... SET data = ...`) pe rândul singleton.

**Concluzie**: acest lucru atinge o cheie dintr-o structură de date **persistată live în producție** (`model_weights`), citită și scrisă de cod de producție (inclusiv UI-ul editabil de utilizator, `app.py`). Per CLAUDE.md, „Orice schimbare de contract (model de date, responsabilitate, flux) trece printr-un ADR — nu prin editare tăcută" — se califică fără ambiguitate. Nu e un „detaliu de implementare" (ex. formatul unei erori) exceptat de `FROZEN_REGISTRY.md`.

## 4. Compatibilitate cu modelele deja existente

- **Modelele ML (XGBoost, `learning_core/`)**: **neafectate** — `dna_weight` nu apare deloc în `FEATURE_COLUMNS` (`ml_predictor.py`) și nu e citit de niciun cod din `learning_core/` (grep confirmat: zero rezultate). E o pondere internă a formulei Poisson a Oracle Engine, complet separată de stratul ML.
- **Valorile per-ligă deja calibrate** (ex. Bundesliga `dna_weight=0.35`, Champions League `0.45`): **preservate ca valori**, doar redenumite. Migrarea nu schimbă nicio valoare numerică — doar cheia sub care e stocată.
- **`sample_count` per-ligă**: neatins de acest ADR — rămâne 0 pentru toate ligile (Pasul 1, inert, `auto_recalibration_enabled=False`), independent de redenumire.

## 5. Impact asupra Champion/Guardian (Learning Core)

**Zero impact, confirmat.** `dna_weight` nu apare în `learning_core/` (grep exhaustiv pe director: zero rezultate). Champion Manager, Challenger FSM, Promotion Engine, Rollback Engine, Champion Guardian operează exclusiv pe modele ML (`model_champions`, `challengers`, `training_runs`) — complet independente de `model_weights` (config-ul static al Oracle Engine). Această redenumire nu atinge niciun contract Learning Core.

## 6. Strategia de migrare

### 6.0 Deployment Rule (adăugată obligatoriu la aprobare, 2026-08-03)

> Rename-ul e considerat o **modificare atomică**. Codul, `weights.json` și `model_weights` din Supabase trebuie migrate în aceeași sesiune de deployment. **Nu se acceptă stări intermediare** și **nu se introduc mecanisme temporare de compatibilitate** (`base_weight || dna_weight`).

Concret, în execuția din §6 de mai jos: pașii 1-5 (cod + `weights.json` + teste + doc) și pasul 6 (migrare Supabase) se execută în aceeași sesiune de lucru continuă, fără întrerupere între ele — nu se lasă commit-ul de cod mergeuit pe `main` pentru o perioadă nedeterminată înainte ca `model_weights` să fie migrat. Confirmă explicit ceea ce §6 (versiunea inițială a acestui ADR) intenționa deja („Nu se introduce niciun shim de compatibilitate dual-read"), dar o ridică la rangul de regulă obligatorie, nu doar recomandare motivată de simplitate. Dacă din orice motiv sesiunea se întrerupe între pasul 5 și pasul 6, task-ul rămâne explicit **neterminat** (conform regulii de proces a EPIC-ului, `ML_ACTIVATION_IMPLEMENTATION_PLAN.md` §7) — nu se consideră Pasul 7 închis, nu se trece la Pasul 8, până când migrarea Supabase nu e confirmată completă.

Ordinea contează — obiectivul e să minimizeze fereastra în care codul și datele persistate sunt inconsistente (cod așteaptă `base_weight`, date au încă `dna_weight`, sau invers → `w.get(cheie_nouă, default)` ar cădea silențios pe valoarea implicită 0.40, mascând valorile per-ligă deja calibrate — o aproximare silențioasă, exact ce Regula North Star #8 interzice).

1. **Cod, toate cele 6 fișiere de producție simultan** (`oracle_engine.py`, `feature_engine.py`, `recalibration.py`, `sync/bootstrap_league_learning.py`, `explainability.py`, `app.py`) — un singur commit, `dna_weight`→`base_weight` (și `dna_w`→`base_w` pentru cheia abreviată din explainability, pentru consecvență).
2. **`tests/test_explainability.py`** — actualizat în același commit (cheia din asserții).
3. **`weights.json`** — actualizat în același commit (12 apariții: 1 global + 11 per-ligă).
4. **`docs/03_ENGINE/PREDICTOR_ROADMAP_V4.md`** — actualizat în același commit (descrie starea curentă a `calibrate_xg()`).
5. **Regression completă** (`pytest tests/`) — verificare că nimic nu s-a rupt înainte de a atinge Supabase.
6. **Migrare `model_weights` (Supabase, live)** — pas SEPARAT, execuție explicită, DUPĂ ce pașii 1-5 sunt verificați verzi:
   - `SELECT data FROM model_weights WHERE id=1` (read-only, verificare stare curentă reală, nu presupusă din `weights.json`).
   - Construire noua valoare `data` — identică structural, cu `dna_weight`→`base_weight` peste tot (global + 11 ligi), toate celelalte chei/valori neschimbate.
   - **SQL-ul/operația exactă arătată explicit utilizatorului înainte de execuție** (regulă `supabase-safety`, fără excepție) — inclusiv diff-ul JSON before/after.
   - `UPDATE model_weights SET data = <noua_valoare>, updated_at = now() WHERE id=1` — o singură operație atomică, pe rândul singleton.
7. **Verificare finală live**: re-citire `model_weights` după scriere, confirmare că `resolve_league_weights()`/`calibrate_xg()` funcționează cu datele reale actualizate (nu doar cu `weights.json` local).

Nu se introduce niciun shim de compatibilitate dual-read (`w.get("base_weight", w.get("dna_weight", 0.40))`) — pașii 1-6 se execută în aceeași sesiune, fără fereastră de trafic concurent relevantă (proiect cu un singur dezvoltator, fără utilizatori concurenți pe Streamlit live în timpul migrării), deci un cut-over curat e mai simplu și evită cod mort permanent (consecvent cu practica „no defect, no rewrite" a proiectului — dar și „fără shim-uri de compatibilitate temporare" cerut de instrucțiunile Claude Code).

## 7. Strategia de rollback

- **Cod**: `git revert` pe commit-ul de redenumire — trivial, fără dependențe externe.
- **`weights.json`**: revenit automat odată cu `git revert` (fișier versionat).
- **`model_weights` (Supabase, live)**: înainte de scriere (pasul 6 de mai sus), se salvează explicit valoarea `data` curentă (JSON complet, afișat utilizatorului ca parte a confirmării pre-scriere) — rollback-ul înseamnă un al doilea `UPDATE model_weights SET data = <valoarea_salvată_pre-migrare> WHERE id=1`, aceeași disciplină `supabase-safety` (SQL arătat explicit înainte de execuție). Nu e nevoie de o tabelă de backup dedicată — o singură valoare JSON, ușor de păstrat în log-ul sesiunii/commit message.
- **Criteriu de declanșare rollback**: orice discrepanță găsită la regresie (Predictor Regression Suite) sau la verificarea funcțională post-migrare (pasul 7) care nu poate fi explicată ca artefact al redenumirii înseși.

## 8. Ce NU se schimbă

- Nicio valoare numerică (0.40 global, 0.35/0.45/etc. per-ligă) — doar numele cheii.
- Niciun comportament al `calibrate_xg()`, `compute_team_offdef_rating()`, `resolve_league_weights()` — formula rămâne identică matematic.
- `FEATURE_COLUMNS` (ML) — neatins.
- Learning Core / Champion / Challenger / Guardian — neatinse (§5).
- `sample_count` / inerția ponderilor per-ligă (Pasul 1) — neatinsă, independentă de această redenumire.

## 9. Decizie

Se aprobă redenumirea `dna_weight` → `base_weight` (și `dna_w` → `base_w` pentru cheia abreviată din explainability), executată atomic conform ordinii din §6, cu migrarea `model_weights` (Supabase) ca pas separat, explicit confirmat, DUPĂ ce codul + `weights.json` + teste sunt verzi local. Fără shim de compatibilitate permanent. Rollback posibil complet, fără pierdere de date, conform §7.

**Aprobat** — 2026-08-03, de proprietarul produsului, cu completarea Deployment Rule (§6.0). Implementarea urmează exact ordinea din §6, cu regresie + review înainte de commit, conform fluxului stabilit pentru acest EPIC.

## 10. Out of Scope / Discoveries During Implementation

**`recalibration_log.new_dna_w`** (descoperit 2026-08-03, în timpul implementării §6 pas 1 — grep pe `supabase_client.py` a scos la iveală o coloană SQL reală, nu doar un nume de variabilă Python).

Verificat live (read-only, `list_tables`): `public.recalibration_log` există în producție, cu o coloană reală `new_dna_w` (`numeric`, nullable), **0 rânduri** azi.

**Decizie explicită a proprietarului produsului**: `new_dna_w` **NU face parte din scopul acestui ADR**. Motivație:

- ADR-047 a fost aprobat pentru redenumirea contractului Oracle (`model_weights`, `weights.json`, codul Oracle Engine, UI) — nu pentru infrastructura de audit/logging.
- `recalibration_log` e infrastructură de audit/logging, nu participă la calculul predicției.
- `auto_recalibration_enabled = False` — mecanismul care ar scrie în această tabelă e inert azi.
- Tabela are 0 rânduri — nicio dată reală afectată de decizie, în niciun sens.
- Nu se extinde scopul unui ADR deja aprobat „din mers".

**Consecință concretă asupra implementării**: `recalibration.py` a fost corectat să producă în continuare cheia `"new_dna_w"` (nu `"new_base_w"`) în dict-ul trimis către `supabase_client.append_recalibration_log()`/`append_recalibration_log_batch()` — consistent cu coloana SQL neschimbată. Valoarea propriu-zisă citită pentru acea cheie (`lw.get("base_weight", 0.40)`) rămâne corect actualizată la noul nume de cheie din `model_weights`. `supabase_client.py` rămâne complet neatins.

**Nu se face**: `ALTER TABLE recalibration_log RENAME COLUMN new_dna_w TO new_base_w`. Nicio schimbare de schemă SQL ca parte a acestui ADR.

**Va fi tratată separat**: dacă mecanismul de recalibrare automată (`auto_recalibration_enabled`) va fi vreodată activat în viitor, redenumirea `recalibration_log.new_dna_w` (și orice altă curățare de nume asociată) va necesita propriul ADR dedicat — nu se presupune sau se decide implicit aici.
