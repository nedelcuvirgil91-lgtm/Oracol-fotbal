-- =============================================================================
-- Football Oracle — Migration 044: DROP tabele backup + POC eliminate
-- =============================================================================
-- Master Repair Plan, Pasul 3, punctul 6 — audit complet aprobat de
-- proprietarul produsului (2026-08-03). Cele 5 obiecte de mai jos:
--   - au fost exportate complet (CREATE TABLE + INSERT), verificate rand cu
--     rand contra sursei live (numar de randuri, coloane, suma de control pe
--     id, spot-check integral pe continut) si RESTORE-testate cu succes
--     intr-o baza Postgres 16 izolata (nu Supabase, nu productie) — vezi
--     docs/00_GOVERNANCE/archive/sql_backups/README.md;
--   - nu au nicio referinta in cod (.py), workflow-uri GitHub, view-uri,
--     functii/RPC-uri sau trigger-e — verificat direct, nu presupus;
--   - pentru cele 4 tabele backup: ADR-025 are verdict CLOSED, migratiile pe
--     care le protejau (Faza 3, MoV activation, Gate-07, Faza 4) sunt toate
--     inchise si verificate (convergenta/spot-check documentate in
--     rapoartele de migrare), conditiile explicite de pastrare ("fereastra
--     de stabilizare", "pana dupa Gate-08") sunt satisfacute;
--   - pentru flashscore_poc_full_tabs_test: POC incheiat, concluziile deja
--     codificate in docs/06_UDAL/FLASHSCORE_FIELD_MAPPING_MATRIX.md, dovada
--     bruta deja duplicata in docs/06_UDAL/poc_evidence/flashscore_full_tabs_poc/,
--     zero referinta in .sql/.ipynb/workflow-uri/documente de analiza active.
--
-- Tabelele UDAL/Flashscore ramase (player_match_stats, match_events,
-- scraper_selector_registry, acquisition_run_log, acquisition_dead_letter,
-- odds_fallback_flashscore, flashscore_acquisition_queue, upcoming_matches,
-- upcoming_lineups, upcoming_match_features) NU sunt atinse — au fie uz de
-- productie activ, fie acoperire explicita intr-un ADR/roadmap activ
-- (ADR-043 ACCEPTAT, Critical Path oficial M0->M4, ARCHITECTURE_STATE.md).
-- =============================================================================

DROP TABLE IF EXISTS match_history_faza3_backup_20260715;
DROP TABLE IF EXISTS match_history_mov_activation_backup_20260715;
DROP TABLE IF EXISTS match_history_gate07_renorm_backup_20260716;
DROP TABLE IF EXISTS match_history_adr025_faza4_backup_20260716;
DROP TABLE IF EXISTS flashscore_poc_full_tabs_test;
