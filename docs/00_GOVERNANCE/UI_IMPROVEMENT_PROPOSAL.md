# UI Improvement Proposal — Team DNA & Poisson vs. Monte Carlo

**Status**: PROPUNERE — nu implementată. Acest document nu autorizează nicio schimbare de cod prin el însuși.

**Autor**: Claude, la cererea proprietarului produsului.

**Data**: 2026-08-03.

**Scop**: EPIC „Functional Completion", Punctul 5 — „propune un plan de curățare și îmbunătățire a UI (Team DNA, explicații Poisson vs. Monte Carlo), fără modificarea logicii Predictorului." Document de propunere, nu de implementare — urmează exact mandatul din findings #8 și #10, `FUNCTIONAL_COMPLETION_MASTER_PLAN.md`.

**Garanție de scop, pentru ambele opțiuni recomandate mai jos**: nicio opțiune prezentată în acest document nu atinge `oracle_engine.py`, `feature_engine.py`, `ml_predictor.py` sau orice altă sursă de `home_xg`/`away_xg`/`ph`/`pd`/`pa`. Toate datele discutate aici sunt deja calculate și disponibile pe obiectul `MatchPrediction` primit de UI — propunerile sunt strict despre CE se afișează din ce există deja, nu despre CUM se calculează.

---

## Zona 1 — Team DNA Flashscore: câmpuri calculate, needeschise în UI

### Problema (finding #8, 🟡 Minor)

`flashscore_team_dna.py::build_team_dna()` calculează 12+ câmpuri per echipă, disponibile azi pe `pred.home_flashscore_dna`/`pred.away_flashscore_dna` (citite deja de `app.py:517`), dar `app.py` extrage explicit doar 7 din ele pentru afișare (`app.py:529-538`, expander „🛰 Statistici avansate (Flashscore)"):

| Sursă | Câmp | Afișat azi? |
|---|---|---|
| `advanced` | `avg_xg`, `avg_possession`, `avg_offsides`, `avg_goalkeeper_saves`, `avg_red_cards` | ✅ Da |
| `advanced` | `avg_goals_for`, `avg_goals_against` | ❌ **Nu** |
| `advanced` | `matches_sampled` | ❌ **Nu** |
| `player_ratings` | `avg_player_rating` | ✅ Da |
| `player_ratings` | `players_sampled` | ❌ **Nu** |
| `standings` | `rank` | ✅ Da (parțial) |
| `standings` | `played`, `won`, `drawn`, `lost`, `goals_for`, `goals_against`, `goal_diff`, `points` | ❌ **Nu** — 7 din 8 câmpuri de clasament lipsesc |

Date reale, colectate (request-uri Flashscore reale, plătite în cotă), calculate, dar invizibile utilizatorului final.

### Opțiuni

**Opțiunea A — Extinde tabelul `core_rows` existent, adaugă rândurile lipsă**
Adaugă `avg_goals_for`/`avg_goals_against`/`matches_sampled`/`players_sampled` ca rânduri suplimentare în același `st.dataframe()` de la `app.py:529-542`.
- Impact: efort minim (4 linii de cod), zero risc.
- Contra: amestecă statistici de performanță (goluri, posesie) cu metadate despre eșantion (`matches_sampled`) în același tabel — poate deruta („de ce apare un număr de meciuri lângă statistici per-meci?").

**Opțiunea B — Separă în 3 grupuri logice, distincte vizual (recomandat)**
1. Tabelul „Statistici avansate" existent, extins doar cu `avg_goals_for`/`avg_goals_against` (rămâne omogen — toate rânduri sunt „X per meci").
2. O linie `st.caption()` discretă, sub tabel, per echipă: „📊 {matches_sampled} meciuri / {players_sampled} evaluări de jucători eșantionate" — semnal de încredere a datelor, nu statistică de performanță, deci nu aparține tabelului de mai sus.
3. Un mini-tabel nou, „Clasament complet" (afișat doar dacă `standings` nu e `None` pentru cel puțin o echipă): `Loc / Jucate / V / E / Î / GM / GP / GD / Pct`, aceleași 2 coloane (echipa acasă/oaspeți) ca restul.
- Impact: efort mic-mediu (extinde `core_rows` + un `st.caption` + un al doilea `st.dataframe`), zero risc funcțional — pur afișare a unor câmpuri deja calculate.
- Motiv pentru recomandare: separă clar „cât de sigur e semnalul" (eșantion) de „ce spune semnalul" (statistici) de „unde e echipa în clasament azi" (context extern, nu derivat din formă recentă) — coerent cu disciplina „Predictorul rămâne neatins, aceasta e doar prezentare".

**Opțiunea C — Nicio schimbare**
Respinsă — contrazice direct mandatul explicit al Punctului 5.

### Riscuri (ambele opțiuni A/B)
- Zero risc funcțional — date deja calculate, deja pe obiectul `MatchPrediction`, deja verificate „niciodată aproximate" (`flashscore_team_dna.py`, docstring propriu).
- Singurul risc real: câmpurile pot fi `None` pentru echipe/meciuri unde Flashscore n-a colectat încă date suficiente — codul existent (`_v()` helper, `app.py:520-521`) deja gestionează asta cu „—", tipar de reutilizat identic pentru câmpurile noi.

---

## Zona 2 — Panoul „Poisson vs. Monte Carlo" fără notă explicativă

### Problema (finding #10, 🔵 Cosmetic)

`app.py:382-406` afișează două seturi de probabilități („P" = Poisson, „MC" = Monte Carlo) unul lângă altul, fără niciun text care să clarifice relația dintre ele — poate lăsa impresia greșită de „două motoare independente care ar trebui să dea rezultate diferite", când de fapt Monte Carlo e o simulare (10.000 de meciuri simulate din același `home_xg`/`away_xg`) menită să confirme rezultatul închis al formulei Poisson, nu să-l contrazică.

### Opțiuni

**Opțiunea A — `st.caption()` static, sub eticheta secțiunii (recomandat)**
Un rând de text, mereu vizibil, imediat sub `<span class="sub-label">Model comparison — Poisson vs Monte Carlo (10k sim)</span>` (`app.py:385`):

> *"Poisson = formulă matematică exactă. Monte Carlo = 10.000 de meciuri simulate din același xG, ca verificare independentă. Valorile ar trebui să fie foarte apropiate — o diferență mare ar semnala o eroare de calcul, nu o a doua opinie."*

- Impact: o linie de cod (`st.caption(...)`), zero risc, întotdeauna vizibil (fără click suplimentar).

**Opțiunea B — Tooltip/expander „ℹ️ Ce înseamnă asta?"**
Identic conceptual cu A, dar ascuns într-un `st.expander` mic sau tooltip nativ, pentru un panou mai curat vizual.
- Contra față de A: utilizatorul trebuie să interacționeze ca să vadă explicația — pentru un „gol de încredere" (confuzie despre ce arată datele), vizibilitatea implicită (Opțiunea A) pare mai potrivită decât ascunderea ei într-un click suplimentar.

**Opțiunea C — Nicio schimbare**
Respinsă — contrazice mandatul explicit al Punctului 5.

### Riscuri
- Zero — text static, fără nicio interacțiune cu date sau calcul.

---

## Recomandare finală

**Zona 1**: Opțiunea B (separare pe 3 grupuri logice).
**Zona 2**: Opțiunea A (`st.caption()` static, mereu vizibil).

Ambele sunt modificări STRICT de prezentare (`app.py`), zero atingere a `oracle_engine.py`/`feature_engine.py`/`ml_predictor.py`, zero schimbare a valorilor `home_xg`/`away_xg`/`ph`/`pd`/`pa` afișate sau calculate. Efort total estimat: mic (sub o oră de implementare + verificare vizuală manuală în browser, per disciplina „schimbări UI se testează în browser înainte de a fi raportate complete", CLAUDE.md).

## Aprobare

```
[ ] Aprobat de proprietarul produsului — data: __________
    [ ] Zona 1 — Opțiunea B / Opțiunea A / Nicio schimbare (bifează una)
    [ ] Zona 2 — Opțiunea A / Opțiunea B / Nicio schimbare (bifează una)
```

Până la bifare, nu se implementează nimic din acest document.
