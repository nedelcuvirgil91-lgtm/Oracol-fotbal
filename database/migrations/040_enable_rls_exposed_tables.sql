-- =============================================================================
-- Football Oracle — Migration 040: Enable RLS on 12 exposed tables
-- =============================================================================
-- Master Repair Plan, Pasul 3, P1 — securitate Supabase. Aceste 12 tabele
-- aveau RLS dezactivat (semnalate ERROR de linter-ul oficial de securitate
-- Supabase, "rls_disabled_in_public"), deci vizibile prin API-ul public
-- PostgREST oricui ar avea cheia anon — nefolosita nicaieri in acest proiect,
-- dar tot o expunere reala.
--
-- DOAR ALTER TABLE ... ENABLE ROW LEVEL SECURITY, FARA politici noi —
-- acelasi tipar deja folosit pe ~40 alte tabele din proiect (match_history,
-- odds_history, model_config, scheduled_fixtures etc.): RLS activ, zero
-- politici, acces doar prin cheia service_role (BYPASSRLS in Postgres).
-- Verificat in cod (2026-08-03): singurul client Supabase din tot proiectul
-- e construit in supabase_client.py cu SUPABASE_SECRET_KEY — zero cheie
-- anon/publishable oriunde in cod. Activarea RLS aici nu schimba niciun
-- comportament al aplicatiei, doar inchide expunerea catre API-ul public.
--
-- Idempotent — ENABLE ROW LEVEL SECURITY pe un tabel deja activat e no-op.
-- =============================================================================

ALTER TABLE public.api_cache ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.api_provider_status ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.elo_ratings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.experiment_registry ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.league_provider_coverage ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.match_history_adr025_faza4_backup_20260716 ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.match_history_faza3_backup_20260715 ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.match_history_gate07_renorm_backup_20260716 ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.match_history_mov_activation_backup_20260715 ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.provider_metrics ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.shadow_predictions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.sync_status ENABLE ROW LEVEL SECURITY;
