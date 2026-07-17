-- =============================================================================
-- Football Oracle — Migration 005: Promotion (Pasul 5, Implementation Contract)
-- =============================================================================
-- Implementeaza contractele inghetate prin ADR-019 (Pasul 4.5):
--   - docs/04_LEARNING_CORE/PROMOTION_CONTRACT.md
--   - docs/04_LEARNING_CORE/ATOMICITY_CONTRACT.md
--
-- Doua obiecte noi:
--   1. Trigger de imuabilitate pe model_champions (hibrid — o singura
--      mutatie permisa per rand: activ -> istoric), simetric cu
--      odds_history_immutability_guard (001_odds_history.sql).
--   2. Functia promote_challenger(...) — evenimentul de domeniu
--      "Promote Challenger", cu doua efecte cuplate (model_champions +
--      challengers) intr-o singura tranzactie Postgres. Urmeaza exact
--      precedentul deja existent upsert_odds_snapshot() (001_odds_history.sql),
--      deja apelat prin client.rpc() din services/odds_persistence_service.py.
--
-- Promotion executa, nu decide (PROMOTION_CONTRACT.md) — functia re-verifica
-- DOAR precondii structurale (Challenger exista si e SUCCEEDED), nu
-- recalculeaza nicio statistica/prag. Verdictul (candidate_for_promotion)
-- e deja verificat de Promotion Service, in Python, inainte de acest apel
-- (learning_core/promotion_service.py) — vezi ATOMICITY_CONTRACT.md pentru
-- diviziunea exacta a responsabilitatilor.
--
-- Idempotent: poate fi rulat pe o baza de date goala sau re-rulat fara
-- eroare — acelasi tipar ca migrarile anterioare (CREATE OR REPLACE FUNCTION,
-- DROP TRIGGER IF EXISTS + CREATE TRIGGER).
--
-- Nu atinge nicio tabela existenta structural (doar adauga triggerul pe
-- model_champions) — pur aditiv fata de schema.
-- =============================================================================

-- ── Trigger de imuabilitate — model_champions ────────────────────────────────
-- Decizie explicita (PROMOTION_CONTRACT.md, "Imuabilitatea model_champions"):
-- hibrid, nu pur append-only. Un rand permite EXACT o mutatie in viata lui —
-- tranzitia de la activ (superseded_at IS NULL) la istoric (superseded_at/
-- superseded_by completate) — dupa care devine permanent imuabil. DELETE
-- interzis necondiționat, ca la odds_history.
CREATE OR REPLACE FUNCTION model_champions_immutability_guard()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'model_champions: DELETE interzis in productie. Pentru mentenanta administrativa, dezactivati temporar triggerul (ALTER TABLE model_champions DISABLE TRIGGER model_champions_guard).';
    END IF;

    -- Rand deja istoric — complet imuabil, nicio coloana nu se mai poate schimba.
    IF OLD.superseded_at IS NOT NULL THEN
        RAISE EXCEPTION 'model_champions: randul (training_run_id=%) este deja istoric (superseded_at setat) — imuabil definitiv.', OLD.training_run_id;
    END IF;

    -- Rand activ — singura mutatie permisa e tranzitia catre istoric
    -- (superseded_at/superseded_by). Orice alta coloana ramane imuabila.
    IF NEW.id IS DISTINCT FROM OLD.id THEN
        RAISE EXCEPTION 'model_champions: coloana id este imuabila.';
    END IF;
    IF NEW.algorithm_family IS DISTINCT FROM OLD.algorithm_family THEN
        RAISE EXCEPTION 'model_champions: coloana algorithm_family este imuabila.';
    END IF;
    IF NEW.algorithm_version IS DISTINCT FROM OLD.algorithm_version THEN
        RAISE EXCEPTION 'model_champions: coloana algorithm_version este imuabila.';
    END IF;
    IF NEW.league_scope IS DISTINCT FROM OLD.league_scope THEN
        RAISE EXCEPTION 'model_champions: coloana league_scope este imuabila.';
    END IF;
    IF NEW.training_run_id IS DISTINCT FROM OLD.training_run_id THEN
        RAISE EXCEPTION 'model_champions: coloana training_run_id este imuabila.';
    END IF;
    IF NEW.promoted_at IS DISTINCT FROM OLD.promoted_at THEN
        RAISE EXCEPTION 'model_champions: coloana promoted_at este imuabila.';
    END IF;
    IF NEW.promoted_by IS DISTINCT FROM OLD.promoted_by THEN
        RAISE EXCEPTION 'model_champions: coloana promoted_by este imuabila.';
    END IF;

    -- superseded_at/superseded_by raman singurele mutabile pe randul activ —
    -- fara restrictie suplimentara aici; promote_challenger() de mai jos e
    -- singurul apelant care le seteaza, o singura data.
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS model_champions_guard ON model_champions;
CREATE TRIGGER model_champions_guard
    BEFORE UPDATE OR DELETE ON model_champions
    FOR EACH ROW
    EXECUTE FUNCTION model_champions_immutability_guard();


-- ── promote_challenger — evenimentul de domeniu "Promote Challenger" ────────
-- O singura tranzactie Postgres (implicita, in interiorul functiei plpgsql):
-- fie ambele efecte se aplica, fie niciunul. Vezi ATOMICITY_CONTRACT.md
-- pentru diagrama completa a secventei (Python face preconditiile +
-- validarea artefactului INAINTE de acest apel).
--
-- Returneaza:
--   'promoted'       — ambele efecte aplicate cu succes.
--   'already_active' — idempotenta: training_run_id e deja campionul activ.
--   RAISE EXCEPTION  — orice preconditie structurala esuata (Challenger
--                       inexistent / nu e SUCCEEDED / cursa concurenta
--                       pierduta) — Promotion Service (Python) prinde
--                       exceptia si o mapeaza la PromotionResult(status=
--                       "rejected", reason=...).
CREATE OR REPLACE FUNCTION promote_challenger(
    p_training_run_id TEXT,
    p_promoted_by     TEXT
) RETURNS TEXT AS $$
DECLARE
    v_state                   TEXT;
    v_algorithm_family        TEXT;
    v_league_scope            TEXT;
    v_algorithm_version       TEXT;
    v_active_training_run_id  TEXT;
BEGIN
    -- Lock pe randul Challenger — apara impotriva unei a doua promovari
    -- concurente pentru acelasi training_run_id.
    SELECT state, algorithm_family, league_scope
    INTO v_state, v_algorithm_family, v_league_scope
    FROM challengers
    WHERE training_run_id = p_training_run_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'promote_challenger: niciun Challenger gasit pentru training_run_id=%', p_training_run_id;
    END IF;

    IF v_state = 'PROMOTED' THEN
        -- Idempotenta: daca training_run_id e deja campionul activ, no-op.
        SELECT training_run_id INTO v_active_training_run_id
        FROM model_champions
        WHERE algorithm_family = v_algorithm_family
          AND league_scope = v_league_scope
          AND superseded_at IS NULL;

        IF v_active_training_run_id = p_training_run_id THEN
            RETURN 'already_active';
        END IF;

        RAISE EXCEPTION 'promote_challenger: Challenger % este deja PROMOTED dar nu mai este campionul activ curent — stare neasteptata.', p_training_run_id;
    END IF;

    IF v_state <> 'SUCCEEDED' THEN
        RAISE EXCEPTION 'promote_challenger: Challenger % nu este in starea SUCCEEDED (stare curenta: %).', p_training_run_id, v_state;
    END IF;

    SELECT algorithm_version INTO v_algorithm_version
    FROM training_runs
    WHERE training_run_id = p_training_run_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'promote_challenger: niciun training_run gasit pentru training_run_id=%', p_training_run_id;
    END IF;

    -- Efectul 1/2: supersedeaza campionul activ curent, daca exista.
    UPDATE model_champions
    SET superseded_at = now(), superseded_by = p_training_run_id
    WHERE algorithm_family = v_algorithm_family
      AND league_scope = v_league_scope
      AND superseded_at IS NULL;

    -- Efectul 2/2 (a): insereaza campionul nou, activ.
    INSERT INTO model_champions (
        algorithm_family, algorithm_version, league_scope,
        training_run_id, promoted_at, promoted_by
    ) VALUES (
        v_algorithm_family, v_algorithm_version, v_league_scope,
        p_training_run_id, now(), p_promoted_by
    );

    -- Efectul 2/2 (b): inchide ciclul de viata al Challenger-ului.
    UPDATE challengers
    SET state = 'PROMOTED', terminal_at = now()
    WHERE training_run_id = p_training_run_id AND state = 'SUCCEEDED';

    RETURN 'promoted';
END;
$$ LANGUAGE plpgsql;
