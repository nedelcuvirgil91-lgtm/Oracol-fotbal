-- ============================================================================
-- Migrarea 051 — diagnostic pe subsetul informat (ADR-065)
-- ============================================================================
-- Context: `shadow_testing.evaluate_experiment()` nu consulta `data_quality`.
-- Meciurile in care Oracle a fost complet ORB (ambele echipe
-- data_quality='neutral') intra in comparatia Challenger ca si cum baseline-ul
-- ar fi fost informat. Pentru ele Oracle emite o CONSTANTA (verificat: Champions
-- League 18 randuri / o singura valoare 0,8672; Europa League 26 / 0,7835), in
-- timp ce experimentul poate avea ELO real. Comparatia nu e "ambii orbi".
--
-- Masurat 2026-08-23: 43 din 235 de meciuri (18,3%). La Challenger-ul activ
-- xgboost_v1 acuratetea isi INVERSEAZA semnul intre cele doua populatii
-- (+1,7 pp cu neutralele, -2,1 pp fara). Campionul promovat blend_v1 trece
-- testul -- toate trei metricile raman favorabile si fara ele.
--
-- Decizie (ADR-065): se adauga un DIAGNOSTIC, nu se schimba criteriul de
-- promovare. Nu se exclud meciurile neutrale (MIN_MATCHES_FOR_EVALUATION=200,
-- populatia informata e 191 -- un filtru mecanic ar bloca evaluarea), nu se
-- coboara pragul, nu se persista un al doilea verdict
-- (get_latest_challenger_evaluation intoarce un singur rand).
--
-- Se raporteaza DELTE, nu semnificatie: subsetul poate fi prea mic pentru un
-- test concludent, iar o delta ramane citibila. n_matches_informed merge
-- alaturi ca delta sa nu fie citita fara context.
--
-- Verdictele ISTORICE raman NULL pe aceste coloane -- necunoscut, nu zero
-- (Regula #8): nu au fost calculate cu aceasta separare.
--
-- Idempotenta: ADD COLUMN IF NOT EXISTS. Re-rularea nu schimba nimic.
-- Nu se atinge cheia UNIQUE (training_run_id, n_matches_evaluated), nu se
-- atinge RLS, niciun rand existent nu isi schimba comportamentul.
-- ============================================================================

ALTER TABLE challenger_evaluations
  ADD COLUMN IF NOT EXISTS n_matches_informed integer,
  ADD COLUMN IF NOT EXISTS delta_brier_informed numeric,
  ADD COLUMN IF NOT EXISTS delta_logloss_informed numeric,
  ADD COLUMN IF NOT EXISTS delta_accuracy_informed numeric;

COMMENT ON COLUMN challenger_evaluations.n_matches_informed IS
  'ADR-065: cate meciuri din fereastra au avut baseline INFORMAT (nu ambele '
  'echipe data_quality=neutral). NULL pentru verdictele dinaintea ADR-065.';

COMMENT ON COLUMN challenger_evaluations.delta_brier_informed IS
  'ADR-065: delta Brier recalculata doar pe subsetul informat. Diagnostic — '
  'NU intra in criteriul de promovare, care ramane definit pe populatia '
  'completa (North Star #2).';

COMMENT ON COLUMN challenger_evaluations.delta_logloss_informed IS
  'ADR-065: delta log-loss pe subsetul informat. Diagnostic, nu criteriu.';

COMMENT ON COLUMN challenger_evaluations.delta_accuracy_informed IS
  'ADR-065: delta acuratete pe subsetul informat. Metrica la care semnul s-a '
  'inversat in masuratoarea din 2026-08-23 — de citit intotdeauna impreuna cu '
  'n_matches_informed.';
