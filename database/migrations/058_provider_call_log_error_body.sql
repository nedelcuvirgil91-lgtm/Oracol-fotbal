-- ============================================================================
-- 058_provider_call_log_error_body.sql  (ADR-081)
-- ============================================================================
-- Corpul raspunsului esuat devine INTEROGABIL, nu doar logat.
--
-- DE CE. `soccerfootballinfo` raspunde HTTP 400 pe 100% din apeluri din 11
-- octombrie (72 de apeluri, zero reusite). Motivul refuzului e in corpul
-- raspunsului, iar `_corp_diagnostic()` il calculeaza deja de pe 20 oct — dar
-- il scrie intr-un `logger.warning` pe care NU-L POATE CITI NIMENI: artefactul
-- `logs/` e blocat de politica de retea, iar coada log-ului prin API acopera
-- 58 de secunde dintr-o rulare de 73 de minute, cu apelurile SFI la inceput.
--
-- A patra instanta a clasei „calculat corect, cablat corect, niciodata citit",
-- dupa `step_durations_s`, raportul pe etape al lui night_sync, si artefactul
-- `logs/` promis din iulie.
--
-- NU CREEAZA NICIO TABELA, deci garda `tests/test_migration_grants.py` (pragul
-- 058) nu i se aplica — verificat explicit, nu presupus:
--   _RE_CREATE_TABLE.search("ALTER TABLE …") -> False
-- Tabela existenta isi pastreaza grant-urile, deci nici regula Supabase de la
-- 30 octombrie nu se aplica aici.
--
-- VOLUM, marginit de mecanisme care EXISTA deja: `_corp_diagnostic()`
-- trunchiaza la 400 de caractere, iar `cleanup_provider_call_log()` sterge
-- rândurile mai vechi de 9 zile, in fiecare noapte. La ritmul actual al SFI:
-- 9 esecuri/zi × 400 B × 9 zile ~ 32 kB.
--
-- Idempotenta: `IF NOT EXISTS` — rularea de doua ori nu schimba nimic.
-- ============================================================================

ALTER TABLE provider_call_log
    ADD COLUMN IF NOT EXISTS error_body text;

COMMENT ON COLUMN provider_call_log.error_body IS
    'ADR-081: corpul raspunsului, DOAR pe esec, trunchiat la 400 de caractere. '
    'NULL pe succes, prin garda din record_provider_call(). Cheia API nu poate '
    'ajunge aici: circula exclusiv in header-ul de CERERE.';
