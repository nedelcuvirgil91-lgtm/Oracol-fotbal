---
name: supabase-safety
description: Gardă obligatorie, automată, înainte de orice operație Supabase cu efect de scriere (execute_sql, apply_migration, delete_branch, reset_branch, pause_project, restore_project sau orice alt apel mcp__Supabase__* care nu e strict citire) pe proiectul live "Prediction". Se invocă fără excepție, nu doar la cerere — nu există operație de scriere Supabase "prea mică" pentru acest control.
---

# supabase-safety

## Scop

Football Oracle nu are un mediu Supabase de staging — proiectul conectat prin MCP (`Prediction`, `eu-central-1`) e producție reală. `execute_sql` și `apply_migration` scriu direct, fără preview automat, și nu pot fi anulate ca un `git revert`. Acest skill există ca să nu se piardă niciodată acest fapt din vedere.

## Când se declanșează

Automat, înainte de **orice** apel către un tool `mcp__Supabase__*` care nu e strict de citire. Tool-uri exclusiv de citire (nu necesită acest skill): `list_tables`, `list_projects`, `list_migrations`, `list_extensions`, `get_project`, `get_project_url`, `get_publishable_keys`, `get_logs`, `get_advisors`, `get_cost`, `search_docs`.

Tool-uri care **necesită** acest skill înainte de apel: `execute_sql`, `apply_migration`, `create_branch`, `merge_branch`, `rebase_branch`, `reset_branch`, `delete_branch`, `deploy_edge_function`, `pause_project`, `restore_project`, `create_project`.

## Verificare obligatorie înainte de orice apel de scriere

1. **Arată utilizatorului SQL-ul/operația exactă** înainte de execuție — nu rezuma, nu parafraza. Utilizatorul trebuie să vadă exact ce se scrie.
2. **Pentru schimbări de schemă riscante** (DDL, migrări noi): ia în calcul `create_branch` pentru testare izolată, în loc de scriere directă pe `Prediction`. Dacă alegi scriere directă, spune explicit de ce branch-ul nu e necesar în acest caz.
3. **Pentru orice operație distructivă** (`delete_branch`, `reset_branch`, `pause_project`, `DROP`/`DELETE` în SQL): cere confirmare explicită, separată, chiar dacă utilizatorul a aprobat deja etapa în general — o aprobare de etapă nu e o aprobare per-operație distructivă.
4. **Verifică schema existentă** (`list_tables`) înainte de orice migrare care atinge o tabelă deja existentă — nu presupune structura curentă.

## Reguli de respectat (din CLAUDE.md)

- Regula North Star #6: nicio scriere directă pe date live fără confirmare explicită, vizibilă, a exact ce se scrie.
- Orice tabelă nouă: idempotentă (`CREATE TABLE IF NOT EXISTS`), RLS activ, scriere doar prin `service_role` — vezi `database/migrations/001_odds_history.sql` ca precedent de stil.
- Scriere atomică (`INSERT ... ON CONFLICT`), niciodată check-then-act.

## Fișiere de cunoscut

`database/migrations/001_odds_history.sql` (singurul precedent real de migrare din repo), `database/queries.py`, `supabase_client.py`.

## Dacă declanșează un conflict de arhitectură

Dacă operația cerută ar necesita o schimbare de schemă care atinge un contract deja documentat (ex. o tabelă care servește un flux descris într-un ADR), oprește-te și cere un ADR nou înainte de a scrie — nu proceda unilateral. Vezi `frozen-doc-guard` pentru cazul specific al documentelor Frozen.

## Obligatoriu / Opțional

**Obligatoriu, fără excepție.** Nu există mod de a dezactiva acest skill pentru o operație individuală.
