-- Migration 046: subject_team pe flashscore_match_context
--
-- Adaugă coloana subject_team (numele echipei căreia îi aparține o
-- secțiune recent_form_home/recent_form_away, extras direct din textul
-- header-ului "Last matches: <echipă>" la scraping) — necesară pentru a
-- identifica corect secțiunea unei echipe fără să presupunem poziția
-- home/away a fiecărui rând individual (verificat live 2026-08-10: o
-- echipă apare pe ambele părți în rânduri diferite ale propriei secțiuni,
-- reflectând corect meciurile ei reale acasă/deplasare).
--
-- NULL pentru rândurile deja existente (h2h_overall nu are un subiect
-- unic; recent_form_home/away vechi rămân NULL până la o resincronizare
-- naturală — niciun backfill forțat, consistent cu Regula #8).

ALTER TABLE flashscore_match_context ADD COLUMN IF NOT EXISTS subject_team TEXT;
