-- ============================================================================
-- Migrarea 052 — `season` devine coloana canonica (ADR-066, decizia 1)
-- ============================================================================
-- Context verificat 2026-08-25, pe definitia LIVE a functiei (nu pe fisier):
-- niciunul dintre cele trei RPC-uri canonice nu cunostea coloana `season`.
--
--   _upsert_match_canonical_locked   cunoaste_season = false
--   upsert_match_canonical           cunoaste_season = false
--   upsert_matches_canonical         cunoaste_season = false
--
-- Consecinta: `providers/flashscore/persistence.py:129` pune de mult
-- `base["season"] = season` in payload-ul canonic, dar RPC-ul il ARUNCA tacit.
-- Toate cele 1.058 de randuri Flashscore din match_history au season NULL.
-- Acelasi blocaj face neverificabila afirmatia din CLAUDE.md ca "de acum,
-- orice meci nou de la football-data.org are season corect de la prima
-- scriere" — calea de scriere spune ca nu s-ar intampla.
--
-- Semantica: identica cu celelalte ~70 de coloane — COALESCE, non-distructiv.
-- O valoare deja scrisa nu se suprascrie niciodata; NULL-ul se completeaza.
-- Randurile istorice in format `YYYY-YY` raman neatinse (ADR-066 §4:
-- normalizarea lor e o decizie SEPARATA, nu face parte din acest ADR).
--
-- Ce NU face: nu deriva sezonul, nu-l ghiceste din calendar, nu face backfill.
-- Daca payload-ul nu contine `season`, coloana ramane NULL (North Star #8).
--
-- Idempotenta: CREATE OR REPLACE; re-rularea nu schimba nimic.
-- Restul corpului e IDENTIC cu migrarea 049 — fisierul a fost generat
-- programatic din ea (3 inserari punctuale), ca sa nu existe risc de
-- transcriere manuala. Corpul live a fost confirmat inainte ca byte-identical
-- cu 049 (md5 corp = 2e083d0112fe7a7f5b7c0a530977b147, 14.912 caractere).
-- ============================================================================

CREATE OR REPLACE FUNCTION _upsert_match_canonical_locked(p jsonb)
RETURNS jsonb AS $$
DECLARE
  v_home text := p->>'home_team';
  v_away text := p->>'away_team';
  v_date text := left(p->>'kickoff_date', 10);
  v_lock_key bigint;
  v_existing match_history%ROWTYPE;
  v_new_id bigint;
  v_fixture text;
  v_resched_id bigint;
  v_old_date text;
  v_old_home text;
  v_old_away text;
  v_rescheduled boolean := false;
BEGIN
  IF v_home IS NULL OR v_away IS NULL OR v_date IS NULL THEN
    RAISE EXCEPTION 'upsert_match_canonical: home_team/away_team/kickoff_date obligatorii (cheia naturala)';
  END IF;

  v_lock_key := hashtextextended(lower(trim(v_home)) || '||' || lower(trim(v_away)) || '||' || v_date, 0);
  PERFORM pg_advisory_xact_lock(v_lock_key);

  -- [ADAUGAT — migrarea 048] MECI REPROGRAMAT: acelasi fixture_id, alta data.
  -- Fara acest bloc, lookup-ul de mai jos (pe cheia naturala cu data NOUA) nu
  -- gaseste randul existent (are data VECHE), cade pe INSERT, iar INSERT-ul
  -- violeaza idx_match_history_fixture (UNIQUE pe fixture_id) -> intregul pas
  -- de sincronizare esueaza. Un singur meci reprogramat a blocat
  -- flashscore_weekly_fixtures.yml timp de 10 zile (Celta Vigo - Osasuna,
  -- mutat 2026-08-16 -> 2026-08-27).
  v_fixture := p->>'fixture_id';
  IF v_fixture IS NOT NULL THEN
    SELECT id, left(kickoff_date, 10), home_team, away_team
      INTO v_resched_id, v_old_date, v_old_home, v_old_away
    FROM match_history
    WHERE fixture_id = v_fixture AND superseded_by IS NULL
    LIMIT 1;

    -- [ADAUGAT — migrarea 049] IDENTITATE CONTRADICTORIE: acelasi fixture_id,
    -- alte echipe. Cazul real (2026-08-23, Ligue 1, mid=p2AX2W4D): Flashscore
    -- a extras acelasi meci ca "PSG - Rennes" pe 31 iulie si ca
    -- "Rennes - PSG" pe 23 august (inversare de teren, cauza reparata separat
    -- in normalizer). Cheia naturala nu mai gasea randul, functia cadea pe
    -- INSERT, iar INSERT-ul viola idx_match_history_fixture -> EXCEPTIE, si
    -- intregul pas de sincronizare esua.
    --
    -- Aici NU se alege un castigator intre doua afirmatii de identitate care
    -- se contrazic: care echipa e gazda e o decizie de identitate, verificata
    -- de om (regula D3), nu una mecanica. Se intoarce hard_conflict — rand
    -- NESCRIS, vizibil, trasabil — in loc de o exceptie care opreste tot.
    --
    -- Verificarea e INAINTEA oricarei scrieri (inclusiv inaintea UPDATE-ului
    -- de reprogramare de mai jos): altfel am muta data unui rand si am
    -- raporta apoi scrierea ca esuata, lasand o modificare partiala in urma.
    IF v_resched_id IS NOT NULL
       AND (lower(trim(v_old_home)) IS DISTINCT FROM lower(trim(v_home))
            OR lower(trim(v_old_away)) IS DISTINCT FROM lower(trim(v_away))) THEN
      RETURN jsonb_build_object('action','hard_conflict','id',v_resched_id,
                                'reason','fixture_identity_mismatch');
    END IF;

    IF v_resched_id IS NOT NULL AND v_old_date IS DISTINCT FROM v_date THEN
      -- Garda: data noua nu are voie sa fie deja ocupata de ALT rand live —
      -- altfel UPDATE-ul ar viola idx_match_history_natural_key_canonical.
      -- Raportat ca hard_conflict (rand nescris, vizibil), nu ca exceptie.
      IF EXISTS (
        SELECT 1 FROM match_history
        WHERE superseded_by IS NULL AND id <> v_resched_id
          AND lower(trim(home_team)) = lower(trim(v_home))
          AND lower(trim(away_team)) = lower(trim(v_away))
          AND left(kickoff_date, 10) = v_date
      ) THEN
        RETURN jsonb_build_object('action','hard_conflict','id',v_resched_id,
                                  'reason','reschedule_target_occupied');
      END IF;

      UPDATE match_history SET kickoff_date = (p->>'kickoff_date')
      WHERE id = v_resched_id;
      v_rescheduled := true;
      -- Randul are acum data noua, deci lookup-ul de mai jos il va GASI si
      -- ramura UPDATE obisnuita (COALESCE, non-distructiva) ruleaza normal.
    END IF;
  END IF;

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
    season = COALESCE(m.season, (p->>'season')),
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
    provider_raw_json = COALESCE(m.provider_raw_json, (p->'provider_raw_json'))
    WHERE m.id = v_existing.id;

    RETURN jsonb_build_object(
      'action', CASE WHEN v_rescheduled THEN 'reschedule' ELSE 'update' END,
      'id', v_existing.id);
  ELSE
    INSERT INTO match_history (fixture_id, home_team, away_team, kickoff_date, league, season, home_xg_pred, away_xg_pred, home_offensive_rating, home_defensive_rating, away_offensive_rating, away_defensive_rating, home_form_score, away_form_score, home_elo, away_elo, h2h_modifier, h2h_meetings, weather_penalty, home_data_quality, away_data_quality, prob_home_pred, prob_draw_pred, prob_away_pred, mc_prob_home, mc_prob_draw, mc_prob_away, actual_home_goals, actual_away_goals, actual_result, used_for_training, backfill_done, home_xg_actual, away_xg_actual, home_possession, away_possession, home_shots, away_shots, home_shots_on_target, away_shots_on_target, stats_source, home_fouls, away_fouls, home_corners, away_corners, home_yellow_cards, away_yellow_cards, home_red_cards, away_red_cards, home_ht_goals, away_ht_goals, home_corner_avg_recent, away_corner_avg_recent, home_card_avg_recent, away_card_avg_recent, home_foul_avg_recent, away_foul_avg_recent, home_shot_avg_recent, away_shot_avg_recent, home_elo_after, away_elo_after, home_shots_off_target, away_shots_off_target, home_offsides, away_offsides, home_penalties, away_penalties, home_substitutions, away_substitutions, home_lineup, away_lineup, home_manager, away_manager, referee, stadium, provider_raw_json)
    VALUES (
      (p->>'fixture_id'), (p->>'home_team'), (p->>'away_team'), (p->>'kickoff_date'), (p->>'league'), (p->>'season'),
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
      (p->'provider_raw_json')
    )
    RETURNING id INTO v_new_id;
    RETURN jsonb_build_object('action','insert','id',v_new_id);
  END IF;
END;
$$ LANGUAGE plpgsql;
