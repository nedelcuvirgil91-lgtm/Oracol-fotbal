# Politica de securitate — Football Oracle

## Stare cunoscută (transparență, nu alarmă)

Acest proiect e, la acest moment, un instrument personal, într-un **repository privat**. Câteva decizii curente reflectă acest context și sunt documentate explicit aici, nu ascunse:

- **Chei API hardcodate în cod sursă**: `ODDS_API_KEY`, `WEATHER_API_KEY`, `RAPIDAPI_KEY` (în `oracle_api.py`) sunt încă valori literale în cod, nu variabile de mediu. Risc real, dar redus (repo privat) — migrare planificată către `key_manager.py`/secrets, neurgentă.
- **Row Level Security (RLS)**: activ pe unele tabele Supabase (inclusiv `odds_history`), fără policy-uri explicite — accesul se face exclusiv prin cheia `service_role` (`sb_secret_...`), care are `BYPASSRLS` prin design (confirmat din documentația oficială Supabase). Această cheie **nu trebuie expusă niciodată** client-side sau într-un repo public.
- **Fără migrări SQL pentru majoritatea tabelelor**: 15 din 16 tabele Supabase nu au încă schema versionată în `database/migrations/`. Nu e o vulnerabilitate, dar afectează reproductibilitatea completă a proiectului.

## Dacă acest proiect devine vreodată public

Înainte de orice tranziție spre un repository public:
1. **Rotește toate cheile API** existente (cele hardcodate azi trebuie considerate compromise odată ce istoricul git devine vizibil public — istoricul git păstrează permanent valorile vechi, chiar dacă sunt șterse ulterior din fișier).
2. Mută toate cheile în `key_manager.py`/secrets/variabile de mediu, fără excepție.
3. Verifică explicit că `SUPABASE_SECRET_KEY` nu apare nicăieri în istoricul de commit-uri.

## Raportare

Fiind un proiect personal, privat, nu există un proces formal de raportare externă a vulnerabilităților la acest moment. Orice observație de securitate se documentează direct ca issue în repository sau se discută direct cu deținătorul proiectului.
