-- =============================================================================
-- Football Oracle — Migration 042: SECURITY DEFINER view fix + explicit
-- search_path pentru 15 functii
-- =============================================================================
-- Master Repair Plan, Pasul 3, P1 — securitate Supabase (linter oficial
-- Supabase, get_advisors(security)).
--
-- (A) public.migration_gate_status (ERROR, security_definer_view): view
-- creat fara `security_invoker`, ruleaza implicit cu privilegiile
-- proprietarului, ocolind RLS-ul utilizatorului care interogheaza (RLS
-- activat, fara politici, pe equivalence_evaluations - vezi migratia 040).
-- Verificat in cod: singurul loc care citeste acest view e
-- database.queries.get_migration_gate_status_row(), prin acelasi client
-- Supabase unic (SUPABASE_SECRET_KEY / service_role, BYPASSRLS). Comutarea
-- la security_invoker nu schimba comportamentul aplicatiei - service_role
-- ignora RLS indiferent de aceasta setare - doar inchide expunerea
-- teoretica catre un eventual client anon/public, nefolosit nicaieri azi.
--
-- (B) 15 functii cu search_path mutabil (WARN, function_search_path_mutable):
-- verificat direct definitia fiecareia (pg_get_functiondef) - toate
-- plpgsql, NICIUNA SECURITY DEFINER, niciuna nu refera vreo functie/tabela
-- din alt schema (auth.*, storage.*, extensions.* etc.) - toate rezolva
-- nume neprefixate exclusiv in public. Fixarea explicita a search_path nu
-- schimba rezolutia niciunui nume (deja rezolvau implicit in public) - e
-- hardening standard impotriva unui atac teoretic de tip search_path
-- hijacking, nu o schimbare de comportament.
-- =============================================================================

ALTER VIEW public.migration_gate_status SET (security_invoker = true);

ALTER FUNCTION public.odds_history_immutability_guard() SET search_path = public, pg_temp;
ALTER FUNCTION public.model_champions_immutability_guard() SET search_path = public, pg_temp;
ALTER FUNCTION public.promote_challenger(text, text) SET search_path = public, pg_temp;
ALTER FUNCTION public.upsert_match_canonical(jsonb) SET search_path = public, pg_temp;
ALTER FUNCTION public._upsert_match_canonical_locked(jsonb) SET search_path = public, pg_temp;
ALTER FUNCTION public.upsert_matches_canonical(jsonb) SET search_path = public, pg_temp;
ALTER FUNCTION public.upsert_odds_snapshot(text, text, numeric, numeric, numeric, timestamptz, text, text, text, text, text) SET search_path = public, pg_temp;
ALTER FUNCTION public.automation_runs_transition_guard() SET search_path = public, pg_temp;
ALTER FUNCTION public.decision_feed_transition_guard() SET search_path = public, pg_temp;
ALTER FUNCTION public.consensus_capture_samples_append_only_guard() SET search_path = public, pg_temp;
ALTER FUNCTION public.consensus_validation_verdicts_append_only_guard() SET search_path = public, pg_temp;
ALTER FUNCTION public.shadow_provider_recommendations_append_only_guard() SET search_path = public, pg_temp;
ALTER FUNCTION public.rollback_champion(text, text, text, text, text) SET search_path = public, pg_temp;
ALTER FUNCTION public.upsert_scheduled_fixture_merge(text, text, date, text, text, timestamptz, text, text, text, text, text, text, text, text, text, text, text, text, text, text, text, text, text) SET search_path = public, pg_temp;
ALTER FUNCTION public.upsert_freelf_lineup_snapshot_merge(text, text, date, text, boolean, text, jsonb, boolean, text, jsonb) SET search_path = public, pg_temp;
