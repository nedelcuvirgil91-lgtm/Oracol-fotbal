# CHIEF_ARCHITECT_DIRECTIVE_v1.0.md — Football Oracle

**Status**: Direcție permanentă a proiectului, stabilită de Arhitectul Șef la 2026-07-13. Nu e o sarcină punctuală — e filosofia după care se evaluează orice decizie tehnică viitoare. Orice implementare trebuie verificată împotriva acestor reguli.

---

## Misiunea proiectului

Football Oracle **nu** este un site de scoruri, **nu** e un agregator de cote, **nu** e un predictor simplu de 1X2.

Football Oracle trebuie să devină un sistem inteligent care:
- colectează date istorice;
- colectează date live înaintea meciului;
- colectează date live după terminarea meciului;
- învață continuu;
- își îmbunătățește modelele;
- explică utilizatorului de ce recomandă un pariu;
- identifică valoarea reală din piață.

**Scop final**: cel mai inteligent asistent pentru pariuri sportive construit pe date reale.

---

## Principiul 1 — Cele trei motoare

Tot ce se implementează trebuie să servească unul dintre acestea:

1. **Prediction Engine** — produce probabilități.
2. **Value Engine** — compară probabilitatea modelului cu cea a bookmakerului, calculează EV, identifică value bets.
3. **Learning Engine** — învață permanent; fiecare meci terminat trebuie să îmbunătățească modelul; nu există modele statice.

## Principiul 2 — Trei tipuri de date, niciodată amestecate

- **A — Date istorice** (scop: antrenare ML): Elo, Formă, Shots, Corners, Cards, Goals, Odds etc.
- **B — Date pre-match live** (scop: predicția meciului): accidentări, suspendări, lot, formă actuală, odds live, weather, referee, lineups etc.
- **C — Date post-match** (scop: învățare): xG, shots, cards, corners, fouls, player ratings etc. **Nu** influențează predicția meciului deja început — intră doar în baza istorică.

## Principiul 3 — Învățare continuă, pipeline obligatoriu

```
Meci nou → Date live → Predicție → Meci terminat → Date complete →
Feature update → Retraining → Model nou → Validare → Deploy
```

## Principiul 4 — Orice sursă nouă se clasifică

A (necesară imediat) / B (utilă) / C (interesantă) / D (nu aduce valoare).

## Principiul 5 — Zero funcții decorative

Fiecare funcție trebuie să îmbunătățească acuratețea **sau** experiența utilizatorului **sau** viteza aplicației. Dacă nu face niciuna, nu se implementează.

## Principiul 6 — Fiecare sprint livrează ceva vizibil

Nu se acceptă sprinturi doar cu refactorizare. Fiecare sprint conține minimum una din: feature nou, sursă nouă, ML mai bun, UI mai bun, viteză mai bună, explicații mai bune.

## Principiul 7 — Prediction Marketplace

Nu doar 1X2/Over/Under — orice piață pentru care există suficiente date: Double Chance, Draw No Bet, Asian Handicap, Over/Under, BTTS, Correct Score, HT/FT, First Goal, Last Goal, Win to Nil, Goals per Team, Corners, Team Corners, Cards, Team Cards, Penalty, Clean Sheet, Goal Range, și orice piață justificată statistic.

## Principiul 8 — Explainability

Utilizatorul trebuie să înțeleagă *de ce*, nu doar „Prediction 78%". Exemple de factori explicați: Home Elo, Last 5 Form, Shot Dominance, Corner Dominance, Defensive Stability, Odds Drift etc.

## Principiul 9 — Nu ghicim

Verificăm. Nu presupunem — măsurăm. Nu implementăm — validăm. Orice afirmație trebuie demonstrată prin date.

## Principiul 10 — Sincronizare elvețiană

Toate componentele evoluează sincron. Nu un predictor excelent cu un Learning Engine slab; nu o bază de date excelentă cu un UI inutil; nu ML bun fără explainability.

---

## Mod de lucru obligatoriu, per task

1. Analizează.
2. Verifică.
3. Descoperă riscurile.
4. Propune soluția.
5. Așteaptă aprobare dacă modifică arhitectura.
6. Implementează.
7. Testează.
8. Demonstrează rezultatul.
9. Actualizează documentația.

---

## Prioritatea actuală (2026-07-13)

Nu adăugarea a sute de funcții. În ordine:

1. Predictor mai bun.
2. Learning Engine funcțional.
3. Pipeline complet istoric → live → post-match → ML.
4. Exploatarea tuturor datelor existente înainte de introducerea unor surse noi.
5. Livrare continuă de îmbunătățiri vizibile.

---

## Notă de sinteză (adăugată la persistarea documentului)

Maparea pe starea actuală a proiectului, la data adoptării:

| Motor | Modul actual | Stare |
|---|---|---|
| Prediction Engine | `oracle_engine.py` | Funcțional |
| Value Engine | de-vig + value betting din `oracle_engine.py` | Parțial — EV nedemonstrabil pe majoritatea ligilor fără cote istorice reale (motivul Odds Infrastructure) |
| Learning Engine | `shadow_testing.py` + Learning Core | Parțial — Promotion Engine, Champion Manager, promovare automată **neimplementate** (vezi „Current Implementation Status" din `CLAUDE.md`) |

Acest document nu înlocuiește `CLAUDE.md` — îl completează ca strat de filosofie/prioritizare permanentă. Orice contradicție aparentă între cele două se rezolvă în favoarea disciplinei deja stabilite în `CLAUDE.md` (ADR-uri, Frozen docs, regulile de arhitectură #1-23), nu prin suprascriere tăcută.
