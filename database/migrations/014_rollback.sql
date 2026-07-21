-- =============================================================================
-- Football Oracle — Migration 014: Rollback (Stage R1, Rollback Engine)
-- =============================================================================
-- Implementeaza mecanismul de rollback din:
--   - docs/00_GOVERNANCE/ADR-037-learning-core-rollback-and-champion-guardian.md
--   - docs/04_LEARNING_CORE/CHAMPION_GUARDIAN_IMPLEMENTATION.md (§11, R1)
--   - docs/04_LEARNING_CORE/R1_IMPLEMENTATION_CHECKLIST.md (R1.1)
--
-- Un singur obiect nou:
--   - Functia rollback_champion(...) — evenimentul de domeniu "Rollback
--     Champion", APPEND-ONLY: retrage campionul activ (degradat) si reactiveaza
--     predecesorul lui printr-un RAND NOU activ. Doua efecte cuplate pe
--     model_champions, intr-o singura tranzactie Postgres. Urmeaza exact
--     precedentul promote_challenger() (005_promotion.sql).
--
-- Rollback executa, nu decide (ADR-037) — functia re-verifica DOAR precondii
-- structurale (campion activ exista; predecesor exista; predecesorul e cel
-- asteptat). Decizia (sanatate/verdict) e in afara acestui apel. Validarea
-- artefactului predecesorului ramane in Python (Rollback Service, R1.4),
-- INAINTE de acest apel — SQL nu poate deserializa un model XGBoost
-- (vezi ATOMICITY_CONTRACT.md pentru diviziunea Python vs. RPC).
--
-- Compare-and-Swap Guard (audit pre-R1, modificarea 1): functia primeste
-- p_expected_predecessor_training_run_id, deriva predecesorul server-side sub
-- lock, si REFUZA (predecessor_mismatch) daca difera — elimina TOCTOU-ul dintre
-- validarea in Python si executia RPC. Acelasi tipar ca gardii compare-and-swap
-- deja existente (challenger_manager, update_challenger_state).
--
-- Model champions cu DOI scriitori autorizati (Promotion + Rollback),
-- coordonati NU prin owner unic, ci prin: tranzactia atomica de mai jos +
-- indexul partial unic idx_model_champions_active_unique (un singur activ) +
-- triggerul de imuabilitate model_champions_guard (005) + lock FOR UPDATE.
--
-- NU atinge triggerul de imuabilitate (005) — designul append-only respecta
-- exact singura mutatie pe care el o permite (activ -> istoric prin
-- superseded_at/superseded_by). NU atinge challengers (ambele randuri implicate
-- sunt deja terminale PROMOTED). NU modifica nicio tabela structural.
--
-- Idempotent: CREATE OR REPLACE FUNCTION — poate fi rulat sau re-rulat fara
-- eroare, acelasi tipar ca migrarile anterioare. Pur aditiv fata de schema.
-- =============================================================================

-- ── rollback_champion — evenimentul de domeniu "Rollback Champion" ──────────
-- Returneaza:
--   'rolled_back'    — predecesorul a fost reactivat ca nou campion activ.
--   'already_active' — idempotenta (stare-tinta): campionul activ ESTE deja
--                       p_expected_predecessor_training_run_id (rollback deja
--                       aplicat) — no-op, nicio a doua scriere.
--   RAISE EXCEPTION  — orice precondiie structurala esuata:
--                       * niciun campion activ;
--                       * no_predecessor (campionul activ nu are predecesor);
--                       * predecessor_mismatch (garda CAS: starea s-a schimbat
--                         concurent) — Rollback Service (Python) prinde
--                         exceptia si o mapeaza la RollbackResult(status=
--                         "rejected", reason=...), operatorul reia cu starea
--                         actuala.
CREATE OR REPLACE FUNCTION rollback_champion(
    p_algorithm_family                     TEXT,
    p_league_scope                         TEXT,
    p_expected_predecessor_training_run_id TEXT,
    p_reason                               TEXT,
    p_rolled_back_by                       TEXT
) RETURNS TEXT AS $$
DECLARE
    v_active_training_run_id       TEXT;
    v_predecessor_training_run_id  TEXT;
    v_predecessor_algorithm_version TEXT;
BEGIN
    -- Motiv din setul inchis de sase (ADR-037 §4). Validare structurala,
    -- nu decizionala — motivul e furnizat de apelant, nu recalculat aici.
    IF p_reason NOT IN ('regression', 'artifact_missing', 'model_error',
                        'data_error', 'operator', 'emergency') THEN
        RAISE EXCEPTION 'rollback_champion: motiv invalid: % (asteptat unul din regression|artifact_missing|model_error|data_error|operator|emergency)', p_reason;
    END IF;

    -- Garda explicita NULL (audit pre-R1, finding 4b) — INAINTE de orice logica
    -- CAS. Un expected_predecessor NULL ar ocoli TACIT garda compare-and-swap de
    -- mai jos prin logica trivalenta SQL (v_pred <> NULL => NULL => IF nu se
    -- declanseaza), reactivand un predecesor fara protectie. Defense-in-depth
    -- cerut de ATOMICITY_CONTRACT (re-verificare structurala server-side) — nu ne
    -- bazam pe Python. Zero scriere, fara fallback, fara comportament implicit.
    IF p_expected_predecessor_training_run_id IS NULL THEN
        RAISE EXCEPTION 'rollback_champion: expected_predecessor_training_run_id este NULL — garda compare-and-swap nu poate fi evaluata; apel invalid, zero scriere.';
    END IF;

    -- Lock pe campionul activ — apara impotriva unei a doua operatii concurente
    -- (rollback sau promovare) pentru aceeasi (algorithm_family, league_scope).
    SELECT training_run_id
    INTO v_active_training_run_id
    FROM model_champions
    WHERE algorithm_family = p_algorithm_family
      AND league_scope = p_league_scope
      AND superseded_at IS NULL
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'rollback_champion: niciun campion activ pentru (%, %) — nimic de retras.', p_algorithm_family, p_league_scope;
    END IF;

    -- Idempotenta (stare-tinta): campionul activ e deja predecesorul asteptat.
    -- Rollback-ul si-a atins deja tinta — no-op garantat, nicio a doua scriere.
    IF v_active_training_run_id = p_expected_predecessor_training_run_id THEN
        RETURN 'already_active';
    END IF;

    -- Deriva predecesorul SERVER-SIDE, sub lock: randul pe care campionul activ
    -- l-a supersedat (superseded_by = training_run-ul campionului activ). In R1
    -- exista cel mult un asemenea rand (un training_run e activ o singura data).
    -- Intr-un scenariu VIITOR de reactivare (chained rollback, out-of-R1-scope),
    -- acelasi training_run poate fi "supersedor" de mai multe ori => mai multe
    -- randuri. ORDER BY superseded_at DESC LIMIT 1 alege DETERMINIST predecesorul
    -- IMEDIAT (cel mai recent supersedat), consecvent cu ADR-037 §3
    -- ("predecesorul imediat") si corect si dupa activarea chained rollback.
    -- Fara ORDER BY, SELECT INTO ar lua tacit un rand arbitrar (contra Regulii
    -- #8, "Never approximate"); STRICT ar da doar eroare la ambiguitate, in loc
    -- de alegerea corecta — de aceea aleasa aceasta varianta (audit finding 8/2).
    SELECT training_run_id
    INTO v_predecessor_training_run_id
    FROM model_champions
    WHERE algorithm_family = p_algorithm_family
      AND league_scope = p_league_scope
      AND superseded_by = v_active_training_run_id
    ORDER BY superseded_at DESC
    LIMIT 1;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'rollback_champion: no_predecessor — campionul activ % nu are predecesor (a fost primul campion); nimic de revenit.', v_active_training_run_id;
    END IF;

    -- Garda Compare-and-Swap: predecesorul derivat trebuie sa fie EXACT cel
    -- asteptat (cel al carui artefact a fost validat in Python inainte de apel).
    -- Daca difera, starea s-a schimbat concurent (ex. o promovare intre citirea
    -- Python si acest apel) — se refuza, ZERO scriere. Acelasi tipar ca
    -- update_challenger_state(expected_current_state=...).
    IF v_predecessor_training_run_id <> p_expected_predecessor_training_run_id THEN
        RAISE EXCEPTION 'rollback_champion: predecessor_mismatch — asteptat %, gasit % (stare schimbata concurent). Reia operatia cu starea actuala.', p_expected_predecessor_training_run_id, v_predecessor_training_run_id;
    END IF;

    -- algorithm_version al predecesorului, pentru randul nou activ.
    SELECT algorithm_version
    INTO v_predecessor_algorithm_version
    FROM training_runs
    WHERE training_run_id = v_predecessor_training_run_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'rollback_champion: niciun training_run pentru predecesor % — istoric inconsistent, nu se aproximeaza.', v_predecessor_training_run_id;
    END IF;

    -- Efectul 1/2: supersedeaza campionul activ (degradat). Singura mutatie
    -- permisa de triggerul de imuabilitate (005): activ -> istoric, atingand
    -- exclusiv superseded_at/superseded_by. superseded_by pointeaza catre
    -- predecesorul care il inlocuieste (trasabilitate a evenimentului de rollback).
    UPDATE model_champions
    SET superseded_at = now(),
        superseded_by = v_predecessor_training_run_id
    WHERE algorithm_family = p_algorithm_family
      AND league_scope = p_league_scope
      AND superseded_at IS NULL;

    -- Efectul 2/2: reactiveaza predecesorul printr-un RAND NOU, activ (append-only
    -- — nu se reactiveaza randul istoric, pe care triggerul l-ar bloca). Acelasi
    -- training_run_id reapare legitim; indexul partial unic garanteaza un singur
    -- activ per (algorithm_family, league_scope). promoted_by marcheaza explicit
    -- provenienta de rollback + motivul + cine (audit).
    INSERT INTO model_champions (
        algorithm_family, algorithm_version, league_scope,
        training_run_id, promoted_at, promoted_by
    ) VALUES (
        p_algorithm_family, v_predecessor_algorithm_version, p_league_scope,
        v_predecessor_training_run_id, now(),
        'rollback:' || p_reason || ':' || p_rolled_back_by
    );

    RETURN 'rolled_back';
END;
$$ LANGUAGE plpgsql;
