# Arhivă SQL — tabele backup + POC eliminate din Supabase

Master Repair Plan, Pasul 3, punctul 6. Cele 5 fișiere din acest director sunt
export-uri SQL complete (`CREATE TABLE IF NOT EXISTS` + `INSERT`, în loturi de
200 rânduri) ale celor 5 obiecte eliminate din proiectul Supabase `Prediction`
(`eu-central-1`) după auditul complet aprobat de proprietarul produsului
(2026-08-03) — vezi migrația `database/migrations/044_drop_backup_and_poc_tables.sql`
pentru DROP-ul efectiv și justificarea per tabelă.

## Conținut

| Fișier | Tabelă originală | Rânduri | Motiv eliminare |
|---|---|---:|---|
| `export_match_history_faza3_backup_20260715.sql` | `match_history_faza3_backup_20260715` | 19.797 | Snapshot pre-migrare Faza 3 (ADR-025), migrare închisă și verificată |
| `export_match_history_mov_activation_backup_20260715.sql` | `match_history_mov_activation_backup_20260715` | 53.409 | Snapshot pre-migrare MoV activation, validat prin convergență |
| `export_match_history_gate07_renorm_backup_20260716.sql` | `match_history_gate07_renorm_backup_20260716` | 5.403 | Snapshot pre-renormalizare nume (ADR-025 Gate-07), ADR-025 CLOSED |
| `export_match_history_adr025_faza4_backup_20260716.sql` | `match_history_adr025_faza4_backup_20260716` | 53.432 | Snapshot pre-reconciliere Faza 4 (ADR-025), Gate-08/Gate-09 finalizate |
| `export_flashscore_poc_full_tabs_test.sql` | `flashscore_poc_full_tabs_test` | 7 | POC încheiat (1 meci), concluzii deja codificate în `docs/06_UDAL/FLASHSCORE_FIELD_MAPPING_MATRIX.md`; dovadă brută duplicată deja în `docs/06_UDAL/poc_evidence/flashscore_full_tabs_poc/` |

## Verificare de integritate (2026-08-03)

Pentru fiecare export, înainte de eliminarea tabelei sursă:
- rândurile exportate == rândurile live din Supabase (numărătoare exactă);
- coloanele din `CREATE TABLE` generat == `information_schema.columns` live;
- sumă de control (`sum(id)`, `min(id)`, `max(id)`) identică între export și sursă;
- spot-check integral pe conținut (toate coloanele unui rând, inclusiv text/numeric/boolean/timestamp/`NULL`) — identic byte-cu-byte.

**Test de restore** — fiecare fișier a fost executat cu succes (`psql -v ON_ERROR_STOP=1`)
într-o bază de date Postgres 16 locală, complet izolată (nu Supabase, nu producție),
creată exclusiv pentru acest test și ștearsă imediat după. Toate cele 5 `CREATE TABLE`
+ seturile de `INSERT` au rulat fără nicio eroare, iar numărul de rânduri restaurate
a fost identic cu exportul, pentru toate cele 5 obiecte.

## Restaurare (dacă va fi vreodată necesară)

```bash
psql -h <host> -U <user> -d <db> -v ON_ERROR_STOP=1 -f export_<tabela>.sql
```

Fiecare fișier e independent și complet (creează tabela dacă nu există, apoi
inserează toate rândurile) — nu necesită alt fișier din acest director pentru
a fi restaurat individual.
