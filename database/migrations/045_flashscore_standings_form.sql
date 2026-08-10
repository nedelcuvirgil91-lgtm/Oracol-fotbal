-- ═══════════════════════════════════════════════════════════════════════
-- Migration 045 — flashscore_standings_snapshot.form (ADR-045, Owner Standings)
-- ═══════════════════════════════════════════════════════════════════════
-- Coloana FORM din pagina de clasament Flashscore (confirmată live, POC
-- izolat 2026-08-10 + fixture existent flashscore_full_tabs_poc/
-- standings.html) — secvență cronologică reală (cel mai vechi primul, cel
-- mai recent ultimul), 'W'/'D'/'L', extrasă din badge-urile
-- data-testid="wcl-badgeForm-{win,draw,lose}" (badge-urile "unknown", "?",
-- excluse — nu sunt un rezultat real, ci un slot de rundă neîncă jucată).
-- Rezolvă blocajul de ordine cronologică pentru noul nivel Standings din
-- oracle_engine._build_profile() — vezi ADR-045, addendum 2026-08-10.

ALTER TABLE flashscore_standings_snapshot ADD COLUMN IF NOT EXISTS form TEXT[];
