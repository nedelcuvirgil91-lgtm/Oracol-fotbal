-- ============================================================================
-- 047 — validation_analysis_reports: metrici pe INTERSECȚIA COMUNĂ
-- ============================================================================
-- Context: auditul ADR-051/052 (2026-08-17) a găsit că metricile existente
-- sunt calculate fiecare pe PROPRIUL subset disponibil al motorului — corect
-- pentru "cât de bine se descurcă fiecare pe ce a putut prezice", dar NU
-- strict comparabile între motoare. Dovadă live, raportul săptămânal
-- 2026-08-03..09: oracle_n=25 vs. ml_n=24 (meciul HNL `flashscore_vBz3Ufoo`
-- n-avea predicție ML) — deci "ML Brier 0.6705 < Oracle Brier 0.6960"
-- compară medii pe eșantioane diferite.
--
-- Decizie: NU se elimină nimic. Se ADAUGĂ un al doilea set de metrici,
-- calculat pe intersecția unde TOATE cele trei motoare au predicție
-- utilizabilă — ca să putem răspunde simultan la ambele întrebări:
--   (A) coloanele fără sufix — fiecare motor pe subsetul lui propriu;
--   (B) coloanele `*_common` — toate trei pe EXACT aceleași meciuri.
--
-- Aditiv și backward-compatible prin construcție: toate coloanele sunt
-- nullable, fără DEFAULT care să rescrie rânduri, fără constrângeri noi.
-- Rândurile istorice (7 rapoarte, 07-13 august 2026) rămân neatinse, cu
-- `NULL` pe coloanele noi — stare corectă și onestă ("nu s-a calculat
-- atunci"), niciodată recalculată retroactiv (Regula #8: nicio stare
-- necunoscută nu se aproximează).
--
-- Convenție de nume: `logloss` (nu `log_loss`), consecvent cu coloanele
-- deja existente în această tabelă (`oracle_logloss` etc.) — o a doua
-- convenție în aceeași tabelă ar fi fost o capcană de mentenanță.
--
-- Idempotentă: `IF NOT EXISTS` pe fiecare coloană.
-- ============================================================================

ALTER TABLE validation_analysis_reports
    ADD COLUMN IF NOT EXISTS n_matches_common integer,

    ADD COLUMN IF NOT EXISTS oracle_brier_common    double precision,
    ADD COLUMN IF NOT EXISTS oracle_logloss_common  double precision,
    ADD COLUMN IF NOT EXISTS oracle_accuracy_common double precision,

    ADD COLUMN IF NOT EXISTS ml_brier_common    double precision,
    ADD COLUMN IF NOT EXISTS ml_logloss_common  double precision,
    ADD COLUMN IF NOT EXISTS ml_accuracy_common double precision,

    ADD COLUMN IF NOT EXISTS blend_brier_common    double precision,
    ADD COLUMN IF NOT EXISTS blend_logloss_common  double precision,
    ADD COLUMN IF NOT EXISTS blend_accuracy_common double precision;

COMMENT ON COLUMN validation_analysis_reports.n_matches_common IS
    'Meciuri unde TOATE cele 3 motoare (Oracle/ML/Blend) au predicție utilizabilă. Diferența față de oracle_n/ml_n/blend_n = măsura incomparabilității subseturilor proprii.';
