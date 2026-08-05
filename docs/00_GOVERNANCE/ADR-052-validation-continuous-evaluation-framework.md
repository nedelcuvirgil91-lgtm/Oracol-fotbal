# ADR-052 — Validation & Continuous Evaluation Framework

**Status**: PROPOSED — document-only, per instrucțiune explicită a proprietarului produsului. Nicio linie de cod nu e autorizată de acest ADR.
**Tip**: ADR de viziune/proces, derivat din ADR-051 — nu o decizie tehnică punctuală, nu o implementare.
**Precedent direct**: ADR-051 (Three Independent Engines Vision, ACCEPTED) — acest ADR completează ciclul de viață pe care ADR-051 l-a lăsat deliberat neformalizat („poziția de lider e mereu doar un fapt empiric curent, verificabil" — ADR-052 definește CUM se verifică).
**Fundament tehnic deja existent, reutilizat ca atare, neschimbat**: `blend_engine.py` (`BlendEngine.predict(outputs: list[EngineOutput])`, deja generic pe număr de motoare, deja acceptă N intrări fără nicio schimbare), `oracle_engine._get_ml_engine_prediction()`/`_get_blend_engine_prediction()` (Phase 1/5, ADR-051), `shadow_testing.evaluate_experiment()` (metodologie Brier/Log-loss/Accuracy simultan, deja existentă, deja folosită de Challenger FSM).

---

## 1. Contextul

ADR-051 a stabilit principiul: trei motoare independente, permanent comparabile, niciunul primar prin construcție — „poziția de lider e mereu doar un fapt empiric curent". Dar ADR-051 însuși, explicit, la §5, nu a decis MECANISMUL prin care acel fapt empiric se produce și se verifică: „Nu decide forma tehnică prin care UI va expune cele trei predicții separat... rămâne a unui Implementation Plan viitor, dedicat."

`ML_IMPLEMENTATION_ROADMAP.md` (Phase 1-5) a dus execuția până la afișarea independentă a celor trei voci (Oracle, ML, Blend) — dar a lăsat, explicit, marcat, nerezolvat (§8, punctul 7): conectarea reală ML→Blend, și orice infrastructură care ar produce, sistematic, dovada empirică cerută de ADR-051 pentru a decide vreodată dacă un motor „depășește" altul.

Acest ADR completează exact acel gol — **fără să implementeze nimic din el**. E documentul de referință pentru integrarea completă Oracle–ML–Blend, perioada de observație care urmează, colectarea automată a rezultatelor, analiza periodică, și deciziile ulterioare de îmbunătățire.

## 2. Decizia

### 2.1 Arhitectura finală a celor trei motoare

- **Oracle** produce propria predicție — neschimbat, cod existent, neatins.
- **ML** produce propria predicție — neschimbat, cod existent (Phase 1), neatins.
- **Blend** consumă rezultatele Oracle ȘI ML, conform regulilor deja definite de ADR-051 §2.3 („combină informația... în mod inteligent") și deja implementate, neschimbate, în `blend_engine.py` (`WeightedAverageStrategy`, V1 — media ponderată, deja generică pe orice număr de `EngineOutput`) — și produce propria predicție.
- **UI** afișează simultan toate trei — deja adevărat din Phase 5.

**Precizare obligatorie, per instrucțiune explicită a proprietarului produsului**: acest ADR **nu modifică algoritmul Blend** (`WeightedAverageStrategy` rămâne exact cum e) — conectarea lipsă e strict la nivelul orchestratorului (`oracle_engine.py`), care azi construiește un singur `EngineOutput` pentru `self.blend.predict()`; completarea cu al doilea `EngineOutput` (ML) e o schimbare de wiring, nu de algoritm. **Acest ADR nu scrie acel cod** — vezi §5.

### 2.2 Perioada de validare (Validation Period)

Începe DUPĂ implementarea completă a integrării de mai sus (§2.1) — nu în paralel, nu înainte. Nu e experiment (nu testează dacă ceva „ar trebui" să existe — cele trei motoare există deja, decis prin ADR-051). Nu e dezvoltare (nu se scrie cod de model în această perioadă). E faza în care sistemul, deja complet, produce date reale, pe trafic real, pentru evaluare — condiția necesară ca „faptul empiric curent" din ADR-051 să fie verificabil, nu presupus.

### 2.3 Colectare automată

Pentru fiecare meci evaluat, sistemul trebuie să permită păstrarea, împreună:
- predicția Oracle;
- predicția ML;
- predicția Blend;
- rezultatul real (când devine cunoscut);
- metadatele necesare comparației (identitate meci, ligă, dată, orice altă informație necesară trasabilității — North Star #9).

**Acest ADR nu decide** schema exactă, tabela, formatul de fișier sau mecanismul de scriere — vezi §5.

### 2.4 Analize periodice

Documentul reafirmă necesitatea unor analize **zilnice**, **săptămânale**, și **lunare** (dacă volumul de date o justifică) — care compară performanța celor trei motoare între ele, pe fereastra de timp relevantă.

**Obiectivul acestor analize**, explicit: să permită identificarea —
- unde ML depășește Oracle;
- unde Oracle rămâne superior;
- dacă Blend aduce valoare reală (nu doar o medie neutră a celorlalte două);
- unde ML necesită recalibrare;
- unde e necesar un nou ciclu de antrenare;
- dacă sunt necesare modificări viitoare — la orice motor.

Metodologia de comparație rămâne cea deja stabilită de proiect (Brier + Log-loss + Accuracy, simultan, niciodată o singură metrică — North Star #2, `shadow_testing.evaluate_experiment()`) — acest ADR nu introduce o metodologie nouă, o extinde la o cadență periodică formalizată.

### 2.5 Rolul lui Claude

Claude **nu ia decizii automat**. Claude analizează rapoartele produse de sistem (§2.3-2.4) și oferă recomandări argumentate, pe bază de date. **Decizia finală aparține întotdeauna proprietarului produsului** — consecvent cu North Star #2 (dovadă statistică, niciodată intuiție) și cu regula deja existentă a proiectului (promovare exclusiv umană, niciodată automată, ADR-002).

## 3. Regula obligatorie

**Nicio modificare a algoritmilor (Oracle, ML, sau strategia de combinare Blend) nu se face fără dovezi rezultate din perioada de validare** — extensie directă a North Star #2 la ciclul de îmbunătățire continuă. O recomandare Claude, oricât de bine argumentată, nu autorizează singură o schimbare — rămâne recomandare, nu decizie.

## 4. Relația cu ADR-051

Acest ADR e derivat din ADR-051. **Nu îl înlocuiește. Nu îl modifică.** Reafirmă explicit, neschimbat:
- **Oracle rămâne independent** — nu consumă ML sau Blend ca intrare.
- **ML rămâne independent** — nu consumă Oracle sau Blend ca intrare (regula deja aplicată, ablație reală, `FEATURE_COLUMNS`).
- **Blend rămâne independent ca identitate de motor** — consumă Oracle+ML doar la nivelul combinării finale (§2.1), nu devine parte a antrenării vreunuia dintre celelalte două.
- **Validarea se bazează pe date reale** — nu pe presupuneri, nu pe intuiție (North Star #2, #8).

Completează ADR-051 exact la punctul unde acela s-a oprit deliberat: definește ciclul de validare și îmbunătățire continuă, fără să atingă niciuna din deciziile deja luate acolo.

## 5. Ce NU decide/autorizează acest ADR

Consecvent cu instrucțiunea explicită a proprietarului produsului:

- **Nicio modificare de cod.** Nu conectează efectiv ML la Blend în `oracle_engine.py` — acel pas (adăugarea celui de-al doilea `EngineOutput` în `_get_blend_engine_prediction()`) rămâne un Implementation Blueprint viitor, dedicat, mirror al tiparului deja folosit pentru Phase 1 (`PHASE1_IMPLEMENTATION_BLUEPRINT.md`).
- **Nu decide schema/tabela/formatul** pentru colectarea automată (§2.3) — rămâne o decizie tehnică viitoare, separată.
- **Nu decide mecanismul** analizelor periodice (§2.4) — cron, GitHub Actions, script manual, sau altceva — rămâne o decizie tehnică viitoare, separată.
- **Nu redeschide `RUNTIME_CONTRACT.md`** — dacă conectarea ML→Blend la nivel de servire live ridică o întrebare similară celei deja rezolvate pentru Phase 1 (citire Champion pentru un al doilea consumator), acea întrebare se tratează separat, la momentul Implementation Blueprint-ului relevant, nu presupusă aici.
- **Nu schimbă nimic din ce rulează azi în producție** — flag-urile existente (`ml_engine_display_enabled`, `blend_engine_display_enabled`) rămân neschimbate; acest document nu le atinge.

## 6. Documente care trebuie actualizate pentru a referenția ADR-052

| Document | Ce trebuie adăugat |
|---|---|
| `docs/04_LEARNING_CORE/ML_IMPLEMENTATION_ROADMAP.md` | §8, punctul 7 (conectarea ML→Blend, azi marcată „rămâne complet neprogramată") — actualizare care să refere ADR-052 ca document care formalizează, la nivel de principiu, acest gol; conectarea efectivă rămâne un Implementation Blueprint viitor, separat. |
| `CLAUDE.md` | Secțiunea „Viziune pe termen lung — trei motoare independente (ADR-051...)" — o mențiune adițională că ciclul de validare/îmbunătățire continuă e formalizat acum de ADR-052, fără să schimbe conținutul deja existent acolo. |
| `blend_engine.py`, `oracle_engine.py`, `tests/test_blend_engine.py`, `tests/test_blend_engine_orchestration.py` | **Gol pre-existent, descoperit acum, nu introdus de acest ADR**: aceste patru fișiere conțin deja referințe în comentarii/docstring-uri la „ADR-051/ADR-052, Vision Shift" — scrise într-o sesiune anterioară, anticipând un ADR-052 care ar fi urmat să formalizeze arhitectura Blend Engine însăși. Acel document nu a fost niciodată scris (verificat: `docs/00_GOVERNANCE/` nu conținea niciun fișier `ADR-052*` înainte de acest document). Numărul 052 e acum folosit aici pentru un subiect diferit (Validation Framework). **Flagat explicit, nerezolvat aici** — proprietarul produsului decide dacă acele comentarii de cod se corectează (ar deveni o modificare de cod, în afara scopului acestui ADR document-only) sau rămân, cu înțelesul „ADR-052" reinterpretat de acest document. |
| `docs/00_GOVERNANCE/FROZEN_REGISTRY.md` | Niciuna — ADR-052 nu e un document Frozen, e un ADR de viziune, ca ADR-051. |

## 7. Consecințe

- **Pozitive**: închide golul explicit lăsat de ADR-051 §5 și de roadmap §8 punctul 7 — proiectul are acum un document de referință pentru ce înseamnă „dovadă empirică" în practică, nu doar în principiu. Oferă un cadru pentru orice recomandare viitoare de recalibrare/reantrenare, ancorat în date, nu în intuiție.
- **Negative/costuri acceptate**: creează, ca și ADR-051, o listă de pași de implementare care nu există încă (§5) — acceptat explicit, nu ascuns. Descoperă un gol de trasabilitate pre-existent (§6, referințele „ADR-052" deja din cod) — semnalat, nerezolvat, decizie lăsată proprietarului produsului.
- **Amânate, deliberat**: toată implementarea tehnică (wiring ML→Blend, schema de colectare, mecanismul analizelor periodice) — subiectul unor Implementation Blueprint-uri viitoare, dedicate, separate, exact tiparul deja aplicat cu succes pentru Phase 1.

---

**Status**: **PROPOSED** — document-only, per instrucțiune explicită a proprietarului produsului. Nicio modificare de cod în acest pas.
