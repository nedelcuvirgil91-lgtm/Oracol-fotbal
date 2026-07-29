-- =============================================================================
-- Football Oracle — Migration 033: match_events idempotency key
-- =============================================================================
-- Corectie gasita in timpul planificarii M0 (R-Sync-FLASH-01): match_events
-- (migratia 032) nu avea nicio cheie unica - un INSERT simplu ar crea
-- duplicate la fiecare rerulare a persist(), incalcand cerinta explicita
-- de idempotenta 100% (M0, punctul 2).
--
-- player_name devine NOT NULL (pentru 'goal'/'yellow_card'/'red_card' e
-- jucatorul; pentru 'substitution' e jucatorul care iese) - fara el, un
-- eveniment nu poate fi identificat unic si nici nu are sens ML (eveniment
-- fara jucator asociat). Tabela e goala (0 randuri, verificat live) -
-- schimbarea e sigura, fara migrare de date.
--
-- Cheie naturala: (match_id, team, minute, event_type, player_name) -
-- INSERT ... ON CONFLICT ... DO UPDATE pe aceasta cheie, in persist(),
-- garanteaza rezultat identic la 1/2/10 rulari pe aceleasi date.
-- =============================================================================

ALTER TABLE match_events
  ALTER COLUMN player_name SET NOT NULL,
  ADD CONSTRAINT match_events_natural_key
    UNIQUE (match_id, team, minute, event_type, player_name);
