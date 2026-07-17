---
name: walk-forward-validation
description: Verifică orice cod nou sau modificat de antrenare a unui model (ML sau statistic) respectă disciplina walk-forward (expanding window), fără scurgere temporală. Se invocă automat, pre-commit, pe orice fișier care antrenează un model pe date istorice.
---

# walk-forward-validation

## Scop

Fotbalul e o serie temporală, nu un dataset static — o scurgere temporală (antrenare pe „viitor" față de segmentul de test) invalidează silențios orice evaluare ulterioară, fără să producă o eroare vizibilă. Disciplina walk-forward e deja centrală în `ml_predictor.py`; acest skill garantează că rămâne așa la orice schimbare viitoare, în orice fișier nou de antrenare.

## Când se declanșează

Automat, pre-commit, pe orice fișier care conține logică de antrenare (`.fit()`, `train_test_split`, sau echivalent) pe date istorice de meciuri.

## Verificare obligatorie înainte de orice modificare

1. **Datele sunt sortate cronologic explicit** înainte de orice split — vezi `ml_predictor.train()`: sortare explicită după `kickoff_date` cu avertisment dacă lipsește coloana.
2. **Niciun `train_test_split` aleator** pe date de meciuri — split-ul trebuie să fie temporal (expanding window), exact tiparul din `ml_predictor._walk_forward_validate()`: fold k antrenează *doar* pe segmentele `[0, k)`, validează *doar* pe segmentul `k`, niciodată pe date „din viitor" față de antrenare.
3. **`random_state` fixat explicit** pentru orice model nou antrenat (precedent: `random_state=42` în `ml_predictor.py`).
4. **Modelul final de producție** se antrenează pe tot istoricul disponibil — walk-forward e strict pentru evaluare onestă, nu pentru selecția datelor de antrenare finale (distincție explicită deja documentată în `ml_predictor.train()`).

## Reguli de respectat

- North Star #7: zero scurgere temporală în orice proces de învățare, fără excepție, indiferent de algoritm.
- `CLAUDE.md`, secțiunea „Regulile ML".

## Fișiere de cunoscut

`ml_predictor.py` (`_walk_forward_validate()`, `train()` — implementarea de referință), `tests/test_ml_walk_forward.py`.

## Dacă declanșează un conflict de arhitectură

Dacă noul cod de antrenare aparține unui algoritm complet nou (nu o modificare la XGBoost existent), verifică dacă adăugarea lui presupune un contract nou de tip „Model Registry"/„Learning Core" — dacă da, acela e un pas de implementare separat, ulterior, nu parte din acest skill. Nu extinde scope-ul acestui skill la orchestrare de experimente — doar la corectitudinea antrenării în sine.

## Obligatoriu / Opțional

**Obligatoriu**, pe orice fișier de antrenare.
