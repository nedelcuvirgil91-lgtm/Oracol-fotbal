-- ============================================================================
-- Migrarea 054 — calendarul sezonului unei competitii (ADR-067)
-- ============================================================================
-- Datele exista deja: `parse_season_from_hub()` le extrage la fiecare rulare
-- de Discovery, din pagina de hub care oricum e descarcata (cost de retea
-- ZERO). Verificat pe Ligue 1: 2026/2027, 21.08 -> 06.06. Pana acum se
-- ARUNCAU — intervalul traia doar cat tinea bucla de persistare.
--
-- DE CE E NEVOIE, concret: ADR-066 P3 derivase startul sezonului din
-- `match_history` (sezonul celui mai recent meci -> prima lui zi). Verificat pe
-- date reale in aceeasi zi, pentru Premier League intorcea 2025-08-15 —
-- startul sezonului TRECUT, fiindca football_data nu mai scrie din 2026-08-04
-- iar meciurile noi n-au inca eticheta. Alegerea reala nu e "tabela noua vs
-- nimic", ci "fapt stocat de la provider vs inferenta fragila din acoperirea
-- propriei baze de date".
--
-- Scriitor UNIC: Discovery (ADR-036 — o coloana, un owner). Nimeni altcineva.
-- Cititor: oracle_engine._current_season_start_date(), treapta 1 din 3.
--
-- Idempotent (CREATE TABLE IF NOT EXISTS), RLS activ, scriere doar prin
-- service_role — aceeasi disciplina ca 001_odds_history.sql.
-- ============================================================================

CREATE TABLE IF NOT EXISTS competition_season (
  id          bigserial PRIMARY KEY,
  competition text        NOT NULL,
  season      text        NOT NULL,
  start_date  date,
  end_date    date,
  source      text        NOT NULL DEFAULT 'flashscore_hub',
  observed_at timestamptz NOT NULL DEFAULT now(),
  created_at  timestamptz NOT NULL DEFAULT now()
);

-- Cheia naturala: o competitie are exact un rand per sezon.
CREATE UNIQUE INDEX IF NOT EXISTS idx_competition_season_natural
  ON competition_season (competition, season);

-- Interogarea principala: "ce sezon al acestei ligi contine ziua de azi?"
CREATE INDEX IF NOT EXISTS idx_competition_season_lookup
  ON competition_season (competition, start_date, end_date);

COMMENT ON TABLE  competition_season IS
  'ADR-067. Calendarul real al sezonului, declarat de provider (hub Flashscore), nu dedus. Scriitor unic: Discovery.';
COMMENT ON COLUMN competition_season.competition IS
  'Numele canonic al ligii, trecut prin mappings.normalize_league_name().';
COMMENT ON COLUMN competition_season.season IS
  'Eticheta canonica YYYY-YYYY (ADR-066 §4).';
COMMENT ON COLUMN competition_season.start_date IS
  'Prima zi a sezonului, de la provider. NULL daca bara de progres lipseste de pe hub (cazul /fixtures/) — necunoscut, niciodata ghicit (North Star #8).';
COMMENT ON COLUMN competition_season.end_date IS
  'Ultima zi a sezonului, de la provider. NULL in aceleasi conditii ca start_date.';
COMMENT ON COLUMN competition_season.observed_at IS
  'Cand a fost vazut ultima oara pe hub. Face INVECHIREA vizibila: daca Flashscore isi schimba clasele hash-uite ale barei, tabela inceteaza sa se actualizeze, iar asta trebuie sa se vada — nu sa treaca tacut.';

ALTER TABLE competition_season ENABLE ROW LEVEL SECURITY;

-- Scriere exclusiv prin service_role; nicio politica de scriere pentru anon.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname = 'public' AND tablename = 'competition_season'
      AND policyname = 'competition_season_service_role_all'
  ) THEN
    CREATE POLICY competition_season_service_role_all
      ON competition_season FOR ALL TO service_role
      USING (true) WITH CHECK (true);
  END IF;
END $$;
