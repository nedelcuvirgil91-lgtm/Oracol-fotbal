-- =============================================================================
-- Football Oracle — Migration 043: backfill stats_source (3.501 randuri)
-- =============================================================================
-- Master Repair Plan, Pasul 3, P5.
--
-- MatchStatsBackfillService (services/match_stats_backfill_service.py,
-- provider="football-data.co.uk") era singurul dintre cei 4 writeri de
-- coloane brute de statistici (home_shots, home_fouls, home_corners,
-- home_yellow_cards, home_ht_goals etc.) care nu seta si `stats_source`
-- odata cu valorile - spre deosebire de freelivefootball,
-- soccerfootballinfo si flashscore, care o fac deja. Fix de cod aplicat
-- separat (commit 2bf9844) - previne recurenta, nu atinge randurile deja
-- scrise.
--
-- Verificat live inainte de executie:
--   - 3.501 randuri cu statistici populate si stats_source IS NULL, 100%
--     cu fixture_id prefixat `fd_` (football-data.org) - zero openfootball/
--     kaggle/flashscore.
--   - Zero suprapunere cu match_events (JOIN pe match_id) - tabela populata
--     exclusiv de normalizer-ul Flashscore.
--   - Zero suprapunere cu match_statistics_extended (JOIN pe match_id) -
--     tabela populata de FreeLF/Soccer Football Info.
-- Concluzie: toate cele 3.501 randuri provin, fara ambiguitate, din
-- backfill-ul istoric football-data.co.uk (sync/backfill_match_stats.py).
--
-- Idempotent (WHERE stats_source IS NULL) - un rand deja atribuit nu e
-- niciodata atins. stats_source NU e feature ML (nu apare in
-- ml_predictor.FEATURE_COLUMNS) - zero impact Predictor/ML.
-- =============================================================================

UPDATE match_history
SET stats_source = 'football-data.co.uk'
WHERE stats_source IS NULL
  AND (home_shots IS NOT NULL OR away_shots IS NOT NULL
       OR home_shots_on_target IS NOT NULL OR away_shots_on_target IS NOT NULL
       OR home_fouls IS NOT NULL OR away_fouls IS NOT NULL
       OR home_corners IS NOT NULL OR away_corners IS NOT NULL
       OR home_yellow_cards IS NOT NULL OR away_yellow_cards IS NOT NULL
       OR home_red_cards IS NOT NULL OR away_red_cards IS NOT NULL
       OR home_ht_goals IS NOT NULL OR away_ht_goals IS NOT NULL);

-- Rezultat live (2026-08-03): 3.501/3.501 randuri actualizate, 0 randuri
-- ramase cu statistici populate si stats_source NULL, total match_history
-- neschimbat (53.769) — nicio alta coloana atinsa.
