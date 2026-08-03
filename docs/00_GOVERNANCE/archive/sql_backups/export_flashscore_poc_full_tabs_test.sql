-- Export complet, Football Oracle, backup cleanup (Pasul 3, punctul 6)
-- Sursa: Supabase proiect Prediction, tabela flashscore_poc_full_tabs_test

CREATE TABLE IF NOT EXISTS "flashscore_poc_full_tabs_test" (
    "id" BIGINT,
    "match_ref" TEXT,
    "tab_name" TEXT,
    "http_status" INTEGER,
    "content_length" INTEGER,
    "distinct_testid_count" INTEGER,
    "extracted_summary" JSONB,
    "fetched_at" TIMESTAMPTZ
);

INSERT INTO "flashscore_poc_full_tabs_test" ("id", "match_ref", "tab_name", "http_status", "content_length", "distinct_testid_count", "extracted_summary", "fetched_at") VALUES
(1, 'dinamo_univ_craiova_2026-07-25', 'summary', 200, 1211862, 78, '{"info_fields": {"Venue:": "Stadionul Arcul de Triumf (Bucharest)", "Referee:": "Kovacs I. (Rou)", "Capacity:": "8 207", "Attendance:": "7 128"}, "top_stats_count": 5, "top_stats_sample": {"Big chances": ["6", "2"], "Total shots": ["18", "9"], "Ball possession": ["47%", "53%"], "Expected goals (xG)": ["3.41", "0.88"], "Touches in opposition box": ["35", "12"]}}'::jsonb, '2026-07-29 09:28:00.950745+00'),
(2, 'dinamo_univ_craiova_2026-07-25', 'stats', 200, 1153319, 45, '{"categories": ["Expected goals (xG)", "Ball possession", "Total shots", "Shots on target", "Big chances", "Corner kicks", "Passes", "Yellow cards", "Red cards", "xG on target (xGOT)", "Shots off target", "Blocked shots", "Shots inside the box", "Shots outside the box", "Hit the woodwork", "Headed goals", "Touches in opposition box", "Accurate through passes", "Offsides", "Free kicks", "Long passes", "Passes in final third", "Crosses", "Expected assists (xA)", "Throw ins", "Fouls", "Tackles", "Duels won", "Clearances", "Interceptions", "Errors leading to shot", "Errors leading to goal", "Goalkeeper saves", "xGOT faced", "Goals prevented", "Goal kicks"], "sample_values": {"Passes": ["85%(314/371)", "87%(366/423)"], "Red cards": ["0", "1"], "Big chances": ["6", "2"], "Total shots": ["18", "9"], "Corner kicks": ["8", "1"], "Yellow cards": ["2", "1"], "Ball possession": ["47%", "53%"], "Shots on target": ["7", "5"], "Expected goals (xG)": ["3.41", "0.88"], "xG on target (xGOT)": ["3.60", "1.81"]}, "total_categories": 36}'::jsonb, '2026-07-29 09:28:00.950745+00'),
(3, 'dinamo_univ_craiova_2026-07-25', 'lineups', 200, 1247622, 59, '{"sample": [{"team": "home", "player_name": "Bellaarouch A.", "shirt_number": 36}, {"team": "home", "player_name": "Irimia D.", "shirt_number": 20}, {"team": "home", "player_name": "Pascual M.", "shirt_number": 44}], "away_count": 23, "home_count": 23, "total_players_listed": 46}'::jsonb, '2026-07-29 09:28:00.950745+00'),
(4, 'dinamo_univ_craiova_2026-07-25', 'player_stats', 200, 1234003, 48, '{"note": "randuri combinate ambele echipe, sortate desc dupa rating - fara coloana de echipa in tabel, necesita join dupa nume cu roster-ul din lineups", "columns": ["ALL", "RatingRating", "Total shotsTotal shots", "Expected goals (xG)Expected goals (xG)", "Accurate passesAccurate passes", "TouchesTouches", "Touches in opposition boxTouches in opposition box", "Successful dribblesSuccessful dribbles", "DuelsDuels"], "total_rows": 32, "sample_rows": [["Pop A. Striker", "8.7", "4", "0.85", "12/17 (71%)", "25", "6", "1/1 (100%)", "6"], ["Armstrong D. Winger", "8.5", "2", "0.22", "7/9 (78%)", "21", "1", "1/2 (50%)", "4"], ["Soro A. Midfielder", "8.4", "1", "0.17", "35/43 (81%)", "53", "2", "1/1 (100%)", "6"], ["Musi A. Striker", "7.9", "2", "0.94", "13/17 (76%)", "29", "5", "0/1 (0%)", "7"], ["Bellaarouch A. Goalkeeper", "7.7", "-", "-", "38/44 (86%)", "61", "-", "-", "1"]]}'::jsonb, '2026-07-29 09:28:00.950745+00'),
(5, 'dinamo_univ_craiova_2026-07-25', 'odds', 200, 1097665, 38, '{"sample_odds": ["2.50", "3.10", "2.60", "2.55", "3.10", "2.60"], "bookmakers_sample": ["bet365", "Unibet", "William Hill", "1xBet", "BetMGM", "Betfred", "Midnite", "Betway"], "decimal_odds_found": 9}'::jsonb, '2026-07-29 09:28:00.950745+00'),
(6, 'dinamo_univ_craiova_2026-07-25', 'h2h', 200, 1145545, 47, '{"score_cells": 30, "sample_scores": ["5", "1", "1", "0", "1", "3"], "participant_rows": 30, "sample_participants": ["Dinamo Bucuresti", "Univ. Craiova", "Petrolul", "Dinamo Bucuresti", "Dinamo Bucuresti", "Farul Constanta"]}'::jsonb, '2026-07-29 09:28:00.950745+00'),
(7, 'dinamo_univ_craiova_2026-07-25', 'standings', 200, 1114023, 36, '{"note": "structura custom (class tableCellParticipant__name), nu testid wcl-table standard", "teams_found": 16, "sample_teams_in_order": ["FCSB", "FC Rapid Bucuresti", "Otelul", "CFR Cluj", "Dinamo Bucuresti", "Farul Constanta"]}'::jsonb, '2026-07-29 09:28:00.950745+00');

