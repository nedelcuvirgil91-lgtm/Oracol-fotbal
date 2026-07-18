-- =============================================================================
-- Football Oracle — Migration 013: shadow_provider_recommendations (ADR-034 PR5)
-- =============================================================================
-- Implementează persistența Shadow Mode a Selection Engine-ului (ADR-034,
-- strat 5/6, PR5) — strict observațional, niciodată consumat de fluxul de
-- producție (Prediction Engine nu citește niciodată din această tabelă).
--
-- shadow_run_id grupează toate recomandările generate într-o singură
-- execuție (ex. o rulare get_matches_for_week()) — generat de
-- shadow_recorder.py, niciodată de provider_selector.py (domeniu,
-- atemporal prin construcție — Regula de Aur #4).
--
-- algorithm_version izolează rezultate produse de versiuni diferite ale
-- formulei de scor (provider_selector.ALGORITHM_VERSION) — evită
-- amestecarea lor la analiza criteriilor de ieșire din shadow mode.
--
-- Append-only (același tipar ca 012_consensus_validation.sql) — o
-- observație greșită nu se corectează, rămâne fapt istoric.
--
-- Idempotent: CREATE TABLE IF NOT EXISTS + CREATE OR REPLACE FUNCTION +
-- DROP TRIGGER IF EXISTS. Pur aditiv — nu atinge nicio tabelă existentă.
-- =============================================================================

CREATE TABLE IF NOT EXISTS shadow_provider_recommendations (
    id                     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    shadow_run_id          UUID NOT NULL,
    algorithm_version      INTEGER NOT NULL,
    observed_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    league                 TEXT NOT NULL,
    data_type              TEXT NOT NULL,
    current_provider       TEXT NOT NULL,
    current_score          DOUBLE PRECISION,
    recommended_provider   TEXT,
    recommended_score      DOUBLE PRECISION,
    decision_changed       BOOLEAN NOT NULL,
    component_deltas       JSONB
);

CREATE INDEX IF NOT EXISTS idx_shadow_provider_recommendations_run
    ON shadow_provider_recommendations (shadow_run_id);

CREATE INDEX IF NOT EXISTS idx_shadow_provider_recommendations_league
    ON shadow_provider_recommendations (league, observed_at);

ALTER TABLE shadow_provider_recommendations ENABLE ROW LEVEL SECURITY;

CREATE OR REPLACE FUNCTION shadow_provider_recommendations_append_only_guard()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'shadow_provider_recommendations: DELETE interzis in productie. Pentru mentenanta administrativa, dezactivati temporar triggerul (ALTER TABLE shadow_provider_recommendations DISABLE TRIGGER shadow_provider_recommendations_guard).';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'shadow_provider_recommendations: UPDATE interzis — tabela e strict append-only (id=%). O observatie shadow gresita nu se corecteaza, ramane fapt istoric.', OLD.id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS shadow_provider_recommendations_guard ON shadow_provider_recommendations;
CREATE TRIGGER shadow_provider_recommendations_guard
    BEFORE UPDATE OR DELETE ON shadow_provider_recommendations
    FOR EACH ROW
    EXECUTE FUNCTION shadow_provider_recommendations_append_only_guard();
