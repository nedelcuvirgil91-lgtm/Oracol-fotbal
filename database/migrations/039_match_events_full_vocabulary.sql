-- =============================================================================
-- Football Oracle — Migration 039: match_events, vocabular complet de evenimente
-- =============================================================================
-- "TASK APROBAT" (corectie oversight-uri M1): timeline-ul complet de
-- evenimente (goluri/autogoluri/penalty/penalty ratat/cartonase galbene si
-- rosii/al doilea galben/schimbari/VAR) e extractibil robust din tab-ul
-- Summary (`.smv__participantRow`) - vezi providers/flashscore/normalizer.py,
-- normalize_match_events(). CHECK-ul vechi (migratia 032) permitea doar
-- ('goal','yellow_card','red_card','substitution') - insuficient.
--
-- VAR: un eveniment real (verificat pe fixture, "Goal Disallowed - handball")
-- NU are jucator asociat (decizie la nivel de meci, nu de jucator) -
-- player_name (NOT NULL din migratia 033) devine incompatibil. Solutie:
-- player_name ramane NOT NULL dar cu DEFAULT '' (sentinel explicit "nu se
-- aplica", nu NULL ambiguu - evita coliziuni de unicitate silentioase la
-- rerulari, PostgREST on_conflict cere coloane literale, nu expresii
-- COALESCE). Coloana noua `detail` (text liber - motiv cartonas, ex.
-- "(Foul)", sau text decizie VAR, ex. "Goal Disallowed - handball") intra
-- si ea in cheia naturala, pentru identitate unica fara jucator.
--
-- Tabela era goala (0 randuri, verificat live inainte de aceasta migrare) -
-- schimbarea e sigura, fara migrare de date.
-- =============================================================================

ALTER TABLE match_events
  ALTER COLUMN player_name SET DEFAULT '',
  ADD COLUMN IF NOT EXISTS detail TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS season TEXT;

ALTER TABLE match_events DROP CONSTRAINT IF EXISTS match_events_natural_key;
ALTER TABLE match_events
  ADD CONSTRAINT match_events_natural_key
    UNIQUE (match_id, team, minute, event_type, player_name, detail);

ALTER TABLE match_events DROP CONSTRAINT IF EXISTS match_events_event_type_check;
ALTER TABLE match_events
  ADD CONSTRAINT match_events_event_type_check
    CHECK (event_type IN (
      'goal', 'own_goal', 'penalty_goal', 'penalty_missed',
      'yellow_card', 'red_card', 'second_yellow_card',
      'substitution', 'var'
    ));
