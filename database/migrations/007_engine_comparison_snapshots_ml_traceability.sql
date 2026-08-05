-- =============================================================================
-- Football Oracle — Migration 007: trasabilitate ML pe engine_comparison_snapshots
-- =============================================================================
-- Închide golul de trasabilitate identificat la auditul de conformitate
-- ADR-051/052 (2026-08-05): rândurile din engine_comparison_snapshots
-- (migrația 006) nu identificau CE model ML a produs ml_prob_home/draw/away
-- — imposibil de corelat performanța cu un training_run/versiune de algoritm
-- specifică (North Star #9, "orice rezultat trasabil complet pana la sursă").
--
-- Sursă: self.champion_diagnostic (oracle_engine.py, populat o singură dată
-- per proces de _resolve_champion(), fără al doilea apel către
-- champion_loader — vezi RUNTIME_CONTRACT.md). Populate doar când
-- ml_available=true — un training_run_id fără o predicție ML reală
-- atribuibilă ar fi o asociere înșelătoare, nu o stare necunoscută corectă
-- (Regula #8 CLAUDE.md).
--
-- Idempotent: poate fi rulat pe o bază de date goală sau re-rulat fără
-- eroare dacă obiectele există deja.
-- =============================================================================

ALTER TABLE engine_comparison_snapshots
    ADD COLUMN IF NOT EXISTS ml_training_run_id  TEXT,
    ADD COLUMN IF NOT EXISTS ml_algorithm_version TEXT;
