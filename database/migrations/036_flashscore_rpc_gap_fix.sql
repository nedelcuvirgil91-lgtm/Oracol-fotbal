-- =============================================================================
-- Football Oracle — Migration 036: Flashscore RPC Gap Fix
-- =============================================================================
-- Gol real gasit prin citire de cod (nu presupus) in timpul implementarii
-- persist() pentru Foundation Data Layer: migratia 032 a adaugat coloanele
-- home/away_goalkeeper_saves, iar migratia 035 a adaugat attendance/capacity
-- pe match_history - dar NICIUNA nu a extins si RPC-ul canonic
-- `_upsert_match_canonical_locked` (upsert_match_canonical). Rezultat: aceste
-- 4 campuri nu puteau fi scrise NICIODATA prin owner-ul unic de scriere
-- (database.queries.upsert_match / upsert_match_and_get_id), indiferent de
-- payload - RPC-ul ignora tacit cheile necunoscute lui.
--
-- Pur aditiv fata de migratia 026 (ultima redefinire completa a functiei) -
-- adauga DOAR cele 4 COALESCE-uri lipsa, la INSERT si UPDATE, acelasi
-- contract (lock advisory pe cheia naturala, COALESCE-only la UPDATE -
-- niciun owner existent suprascris). Idempotent (CREATE OR REPLACE).
-- =============================================================================

CREATE OR REPLACE FUNCTION _upsert_match_canonical_locked(p jsonb)
RETURNS jsonb AS $$
DECLARE
  v_home text := p->>'home_team';
  v_away text := p->>'away_team';
  v_date text := left(p->>'kickoff_date', 10);
  v_lock_key bigint;
  v_existing match_history%ROWTYPE;
  v_new_id bigint;
BEGIN
  IF v_home IS NULL OR v_away IS NULL OR v_date IS NULL THEN
    RAISE EXCEPTION 'upsert_match_canonical: home_team/away_team/kickoff_date obligatorii (cheia naturala)';
  END IF;

  v_lock_key := hashtextextended(lower(trim(v_home)) || '||' || lower(trim(v_away)) || '||' || v_date, 0);
  PERFORM pg_advisory_xact_lock(v_lock_key);

  SELECT * INTO v_existing
  FROM match_history
  WHERE superseded_by IS NULL
    AND lower(trim(home_team)) = lower(trim(v_home))
    AND lower(trim(away_team)) = lower(trim(v_away))
    AND left(kickoff_date, 10) = v_date
  ORDER BY id
  LIMIT 1;

  IF FOUND THEN
    IF ( (p->>'actual_result') IS NOT NULL AND v_existing.actual_result IS NOT NULL
         AND (p->>'actual_result') IS DISTINCT FROM v_existing.actual_result )
       OR ( (p->>'actual_home_goals') IS NOT NULL AND v_existing.actual_home_goals IS NOT NULL
         AND (p->>'actual_home_goals')::integer IS DISTINCT FROM v_existing.actual_home_goals )
       OR ( (p->>'actual_away_goals') IS NOT NULL AND v_existing.actual_away_goals IS NOT NULL
         AND (p->>'actual_away_goals')::integer IS DISTINCT FROM v_existing.actual_away_goals )
    THEN
      RETURN jsonb_build_object('action','hard_conflict','id',v_existing.id);
    END IF;

    UPDATE match_history m SET
    league = COALESCE(m.league, (p->>'league')),
    home_xg_pred = COALESCE(m.home_xg_pred, (p->>'home_xg_pred')::numeric),
    away_xg_pred = COALESCE(m.away_xg_pred, (p->>'away_xg_pred')::numeric),
    home_offensive_rating = COALESCE(m.home_offensive_rating, (p->>'home_offensive_rating')::numeric),
    home_defensive_rating = COALESCE(m.home_defensive_rating, (p->>'home_defensive_rating')::numeric),
    away_offensive_rating = COALESCE(m.away_offensive_rating, (p->>'away_offensive_rating')::numeric),
    away_defensive_rating = COALESCE(m.away_defensive_rating, (p->>'away_defensive_rating')::numeric),
    home_form_score = COALESCE(m.home_form_score, (p->>'home_form_score')::numeric),
    away_form_score = COALESCE(m.away_form_score, (p->>'away_form_score')::numeric),
    home_elo = COALESCE(m.home_elo, (p->>'home_elo')::integer),
    away_elo = COALESCE(m.away_elo, (p->>'away_elo')::integer),
    h2h_modifier = COALESCE(m.h2h_modifier, (p->>'h2h_modifier')::numeric),
    h2h_meetings = COALESCE(m.h2h_meetings, (p->>'h2h_meetings')::integer),
    weather_penalty = COALESCE(m.weather_penalty, (p->>'weather_penalty')::numeric),
    home_data_quality = COALESCE(m.home_data_quality, (p->>'home_data_quality')),
    away_data_quality = COALESCE(m.away_data_quality, (p->>'away_data_quality')),
    prob_home_pred = COALESCE(m.prob_home_pred, (p->>'prob_home_pred')::numeric),
    prob_draw_pred = COALESCE(m.prob_draw_pred, (p->>'prob_draw_pred')::numeric),
    prob_away_pred = COALESCE(m.prob_away_pred, (p->>'prob_away_pred')::numeric),
    mc_prob_home = COALESCE(m.mc_prob_home, (p->>'mc_prob_home')::numeric),
    mc_prob_draw = COALESCE(m.mc_prob_draw, (p->>'mc_prob_draw')::numeric),
    mc_prob_away = COALESCE(m.mc_prob_away, (p->>'mc_prob_away')::numeric),
    actual_home_goals = COALESCE(m.actual_home_goals, (p->>'actual_home_goals')::integer),
    actual_away_goals = COALESCE(m.actual_away_goals, (p->>'actual_away_goals')::integer),
    actual_result = COALESCE(m.actual_result, (p->>'actual_result')),
    used_for_training = COALESCE(m.used_for_training, (p->>'used_for_training')::boolean),
    backfill_done = COALESCE(m.backfill_done, (p->>'backfill_done')::boolean),
    home_xg_actual = COALESCE(m.home_xg_actual, (p->>'home_xg_actual')::numeric),
    away_xg_actual = COALESCE(m.away_xg_actual, (p->>'away_xg_actual')::numeric),
    home_possession = COALESCE(m.home_possession, (p->>'home_possession')::numeric),
    away_possession = COALESCE(m.away_possession, (p->>'away_possession')::numeric),
    home_shots = COALESCE(m.home_shots, (p->>'home_shots')::integer),
    away_shots = COALESCE(m.away_shots, (p->>'away_shots')::integer),
    home_shots_on_target = COALESCE(m.home_shots_on_target, (p->>'home_shots_on_target')::integer),
    away_shots_on_target = COALESCE(m.away_shots_on_target, (p->>'away_shots_on_target')::integer),
    stats_source = COALESCE(m.stats_source, (p->>'stats_source')),
    home_fouls = COALESCE(m.home_fouls, (p->>'home_fouls')::integer),
    away_fouls = COALESCE(m.away_fouls, (p->>'away_fouls')::integer),
    home_corners = COALESCE(m.home_corners, (p->>'home_corners')::integer),
    away_corners = COALESCE(m.away_corners, (p->>'away_corners')::integer),
    home_yellow_cards = COALESCE(m.home_yellow_cards, (p->>'home_yellow_cards')::integer),
    away_yellow_cards = COALESCE(m.away_yellow_cards, (p->>'away_yellow_cards')::integer),
    home_red_cards = COALESCE(m.home_red_cards, (p->>'home_red_cards')::integer),
    away_red_cards = COALESCE(m.away_red_cards, (p->>'away_red_cards')::integer),
    home_ht_goals = COALESCE(m.home_ht_goals, (p->>'home_ht_goals')::integer),
    away_ht_goals = COALESCE(m.away_ht_goals, (p->>'away_ht_goals')::integer),
    home_corner_avg_recent = COALESCE(m.home_corner_avg_recent, (p->>'home_corner_avg_recent')::numeric),
    away_corner_avg_recent = COALESCE(m.away_corner_avg_recent, (p->>'away_corner_avg_recent')::numeric),
    home_card_avg_recent = COALESCE(m.home_card_avg_recent, (p->>'home_card_avg_recent')::numeric),
    away_card_avg_recent = COALESCE(m.away_card_avg_recent, (p->>'away_card_avg_recent')::numeric),
    home_foul_avg_recent = COALESCE(m.home_foul_avg_recent, (p->>'home_foul_avg_recent')::numeric),
    away_foul_avg_recent = COALESCE(m.away_foul_avg_recent, (p->>'away_foul_avg_recent')::numeric),
    home_shot_avg_recent = COALESCE(m.home_shot_avg_recent, (p->>'home_shot_avg_recent')::numeric),
    away_shot_avg_recent = COALESCE(m.away_shot_avg_recent, (p->>'away_shot_avg_recent')::numeric),
    home_elo_after = COALESCE(m.home_elo_after, (p->>'home_elo_after')::integer),
    away_elo_after = COALESCE(m.away_elo_after, (p->>'away_elo_after')::integer),
    home_shots_off_target = COALESCE(m.home_shots_off_target, (p->>'home_shots_off_target')::integer),
    away_shots_off_target = COALESCE(m.away_shots_off_target, (p->>'away_shots_off_target')::integer),
    home_offsides = COALESCE(m.home_offsides, (p->>'home_offsides')::integer),
    away_offsides = COALESCE(m.away_offsides, (p->>'away_offsides')::integer),
    home_penalties = COALESCE(m.home_penalties, (p->>'home_penalties')::integer),
    away_penalties = COALESCE(m.away_penalties, (p->>'away_penalties')::integer),
    home_substitutions = COALESCE(m.home_substitutions, (p->>'home_substitutions')::integer),
    away_substitutions = COALESCE(m.away_substitutions, (p->>'away_substitutions')::integer),
    home_lineup = COALESCE(m.home_lineup, (p->'home_lineup')),
    away_lineup = COALESCE(m.away_lineup, (p->'away_lineup')),
    home_manager = COALESCE(m.home_manager, (p->>'home_manager')),
    away_manager = COALESCE(m.away_manager, (p->>'away_manager')),
    referee = COALESCE(m.referee, (p->>'referee')),
    stadium = COALESCE(m.stadium, (p->>'stadium')),
    provider_raw_json = COALESCE(m.provider_raw_json, (p->'provider_raw_json')),
    home_goalkeeper_saves = COALESCE(m.home_goalkeeper_saves, (p->>'home_goalkeeper_saves')::integer),
    away_goalkeeper_saves = COALESCE(m.away_goalkeeper_saves, (p->>'away_goalkeeper_saves')::integer),
    attendance = COALESCE(m.attendance, (p->>'attendance')::integer),
    capacity = COALESCE(m.capacity, (p->>'capacity')::integer)
    WHERE m.id = v_existing.id;

    RETURN jsonb_build_object('action','update','id',v_existing.id);
  ELSE
    INSERT INTO match_history (fixture_id, home_team, away_team, kickoff_date, league, home_xg_pred, away_xg_pred, home_offensive_rating, home_defensive_rating, away_offensive_rating, away_defensive_rating, home_form_score, away_form_score, home_elo, away_elo, h2h_modifier, h2h_meetings, weather_penalty, home_data_quality, away_data_quality, prob_home_pred, prob_draw_pred, prob_away_pred, mc_prob_home, mc_prob_draw, mc_prob_away, actual_home_goals, actual_away_goals, actual_result, used_for_training, backfill_done, home_xg_actual, away_xg_actual, home_possession, away_possession, home_shots, away_shots, home_shots_on_target, away_shots_on_target, stats_source, home_fouls, away_fouls, home_corners, away_corners, home_yellow_cards, away_yellow_cards, home_red_cards, away_red_cards, home_ht_goals, away_ht_goals, home_corner_avg_recent, away_corner_avg_recent, home_card_avg_recent, away_card_avg_recent, home_foul_avg_recent, away_foul_avg_recent, home_shot_avg_recent, away_shot_avg_recent, home_elo_after, away_elo_after, home_shots_off_target, away_shots_off_target, home_offsides, away_offsides, home_penalties, away_penalties, home_substitutions, away_substitutions, home_lineup, away_lineup, home_manager, away_manager, referee, stadium, provider_raw_json, home_goalkeeper_saves, away_goalkeeper_saves, attendance, capacity)
    VALUES (
      (p->>'fixture_id'), (p->>'home_team'), (p->>'away_team'), (p->>'kickoff_date'), (p->>'league'),
      (p->>'home_xg_pred')::numeric, (p->>'away_xg_pred')::numeric,
      (p->>'home_offensive_rating')::numeric, (p->>'home_defensive_rating')::numeric,
      (p->>'away_offensive_rating')::numeric, (p->>'away_defensive_rating')::numeric,
      (p->>'home_form_score')::numeric, (p->>'away_form_score')::numeric,
      (p->>'home_elo')::integer, (p->>'away_elo')::integer,
      (p->>'h2h_modifier')::numeric, (p->>'h2h_meetings')::integer, (p->>'weather_penalty')::numeric,
      (p->>'home_data_quality'), (p->>'away_data_quality'),
      (p->>'prob_home_pred')::numeric, (p->>'prob_draw_pred')::numeric, (p->>'prob_away_pred')::numeric,
      (p->>'mc_prob_home')::numeric, (p->>'mc_prob_draw')::numeric, (p->>'mc_prob_away')::numeric,
      (p->>'actual_home_goals')::integer, (p->>'actual_away_goals')::integer, (p->>'actual_result'),
      COALESCE((p->>'used_for_training')::boolean, false), COALESCE((p->>'backfill_done')::boolean, false),
      (p->>'home_xg_actual')::numeric, (p->>'away_xg_actual')::numeric,
      (p->>'home_possession')::numeric, (p->>'away_possession')::numeric,
      (p->>'home_shots')::integer, (p->>'away_shots')::integer,
      (p->>'home_shots_on_target')::integer, (p->>'away_shots_on_target')::integer, (p->>'stats_source'),
      (p->>'home_fouls')::integer, (p->>'away_fouls')::integer,
      (p->>'home_corners')::integer, (p->>'away_corners')::integer,
      (p->>'home_yellow_cards')::integer, (p->>'away_yellow_cards')::integer,
      (p->>'home_red_cards')::integer, (p->>'away_red_cards')::integer,
      (p->>'home_ht_goals')::integer, (p->>'away_ht_goals')::integer,
      (p->>'home_corner_avg_recent')::numeric, (p->>'away_corner_avg_recent')::numeric,
      (p->>'home_card_avg_recent')::numeric, (p->>'away_card_avg_recent')::numeric,
      (p->>'home_foul_avg_recent')::numeric, (p->>'away_foul_avg_recent')::numeric,
      (p->>'home_shot_avg_recent')::numeric, (p->>'away_shot_avg_recent')::numeric,
      (p->>'home_elo_after')::integer, (p->>'away_elo_after')::integer,
      (p->>'home_shots_off_target')::integer, (p->>'away_shots_off_target')::integer,
      (p->>'home_offsides')::integer, (p->>'away_offsides')::integer,
      (p->>'home_penalties')::integer, (p->>'away_penalties')::integer,
      (p->>'home_substitutions')::integer, (p->>'away_substitutions')::integer,
      (p->'home_lineup'), (p->'away_lineup'),
      (p->>'home_manager'), (p->>'away_manager'),
      (p->>'referee'), (p->>'stadium'),
      (p->'provider_raw_json'),
      (p->>'home_goalkeeper_saves')::integer, (p->>'away_goalkeeper_saves')::integer,
      (p->>'attendance')::integer, (p->>'capacity')::integer
    )
    RETURNING id INTO v_new_id;
    RETURN jsonb_build_object('action','insert','id',v_new_id);
  END IF;
END;
$$ LANGUAGE plpgsql;
