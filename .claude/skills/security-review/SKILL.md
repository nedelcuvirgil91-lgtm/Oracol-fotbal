---
name: security-review
description: Verifică orice fișier nou sau modificat pentru secrete hardcodate noi și pentru RLS activ pe orice tabelă Supabase nouă. Se invocă automat, pre-commit, pentru orice diff, și e obligatoriu înainte de orice release.
---

# security-review (variantă de proiect — Football Oracle)

## Scop

Blochează repetarea unui gol deja confirmat în acest repo: `oracle_api.py` conține azi 3 chei API hardcodate (`ODDS_API_KEY`, `WEATHER_API_KEY`, `RAPIDAPI_KEY`), documentate ca risc cunoscut, neurgent, în `CLAUDE.md` și `CHANGELOG.md`. Acest skill nu le elimină automat — dar garantează că nu se mai adaugă o a patra cheie hardcodată în loc să se repare problema existentă.

## Când se declanșează

Automat, pre-commit, pentru orice fișier nou sau modificat. Obligatoriu, explicit, înainte de orice release (`release-audit`, când va fi implementat).

## Verificare obligatorie înainte de orice commit

1. **Grep pentru pattern de secret** pe orice fișier nou/modificat: șiruri literale de 20+ caractere alfanumerice, în ghilimele, atribuite unei variabile cu nume care sugerează cheie/secret/token (`_KEY`, `_TOKEN`, `_SECRET`, `password`).
2. **Nu semnalează din nou** cele 3 chei deja cunoscute din `oracle_api.py` ca „descoperire nouă" — sunt deja documentate în `CLAUDE.md`, secțiunea „Goluri cunoscute". Le tratează ca risc activ doar dacă utilizatorul cere explicit migrarea lor.
3. **Orice tabelă Supabase nouă**: verifică `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` prezent în migrare, fără policy publică pentru `anon`/`authenticated` (accesul rămâne exclusiv prin `service_role`).
4. **Niciun fișier de test sau script temporar** nu conține chei reale, nici măcar pentru exemplu — folosește valori evident false (`"test-key-placeholder"`).

## Reguli de respectat

- `SECURITY.md` (politica de securitate deja existentă a proiectului).
- North Star #6 (indirect): o cheie hardcodată e o formă de scriere necontrolată de secret în cod versionat.

## Fișiere de cunoscut

`oracle_api.py` (locul golului cunoscut), `key_manager.py` (mecanismul corect, deja existent, pentru chei gestionate — `footballdata` e deja migrat aici ca precedent), `SECURITY.md`.

## Dacă declanșează un conflict de arhitectură

Migrarea celor 3 chei existente din `oracle_api.py` în `key_manager.py` nu e o schimbare de contract arhitectural (tiparul există deja, aplicat pentru `footballdata`) — nu necesită ADR. Dacă totuși utilizatorul cere o schimbare mai amplă a modului de gestionare a secretelor (ex. un vault extern), asta ar fi un contract nou → oprire, cere ADR.

## Obligatoriu / Opțional

**Obligatoriu** pre-commit; **obligatoriu** pre-release.
