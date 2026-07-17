---
name: test-coverage-guard
description: Verifică suita pytest tests/ rămâne verde și că niciun test nou nu introduce dependență de rețea live sau de Supabase live. Se invocă automat, pre-commit, pentru orice diff care atinge cod de producție sau teste.
---

# test-coverage-guard

## Scop

Plasa de siguranță cea mai ieftină și cea mai generală din nucleu — prinde regresii introduse de orice altă schimbare, înainte să ajungă la review uman. Cele 82 de teste existente rulează azi fără nicio dependință de rețea; costul de a păstra această proprietate e mic comparativ cu costul unei regresii nedetectate sau al unei suite de teste care devine, treptat, nesigură/lentă/flaky.

## Când se declanșează

Automat, pre-commit, pentru orice diff care atinge cod de producție (orice `.py` din afara `tests/`) sau fișiere din `tests/`.

## Verificare obligatorie înainte de orice commit

1. **Rulează `pytest tests/ -q`** — trebuie să rămână verde (82/82 la data acestui skill; numărul crește pe măsură ce se adaugă teste, nu scade fără justificare explicită).
2. **Niciun test nou nu face apel de rețea real** — fără `requests.get`/`requests.post` către API-uri externe live, fără client Supabase real conectat la `Prediction`. Testele existente demonstrează deja tiparul corect (mock-uri/fixtures).
3. **Un test eliminat sau dezactivat** (`@pytest.mark.skip`, ștergere) necesită justificare explicită în commit — nu se elimină tăcut un test care pică, doar ca să treacă suita.

## Reguli de respectat

- `CLAUDE.md`, secțiunea „Regulile testelor".
- README, secțiunea despre `tests/` — „fără dependință de rețea".

## Fișiere de cunoscut

`tests/` (toate fișierele — `test_devig.py`, `test_ml_walk_forward.py`, `test_oracle_engine_compat.py`, `test_odds_persistence_service.py`, `test_odds_persistence_integration.py`).

## Dacă declanșează un conflict de arhitectură

Dacă un test nou pare să necesite acces la Supabase live ca să fie util (ex. testarea unei migrări reale), asta e semn că testul respectiv aparține unei categorii diferite (verificare manuală, via `supabase-safety`), nu suitei `pytest tests/` — nu se adaugă la suita automată doar ca să existe formal.

## Obligatoriu / Opțional

**Obligatoriu**, pre-commit, pentru orice diff care atinge cod de producție sau teste.
