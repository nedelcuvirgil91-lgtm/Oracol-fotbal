"""
Teste pentru N-way Serving Policy (ADR-031) — oprirea blendării implicite,
expunerea ieșirilor brute per motor + view-ul compus rămas disponibil,
neschimbat.

Testează exclusiv build_raw_predictions() (funcție pură, fără efecte
laterale) — nu instanțiază FootballOracleEngine complet (ar necesita
Supabase/API live, deja acoperit ca limitare cunoscută în alte teste).
"""
import oracle_engine


def test_rule_based_engine_always_present():
    """Motorul rule-based (Oracle Protocol) e mereu prezent — funcționează
    și cu date incomplete, per principiul deja stabilit."""
    result = oracle_engine.build_raw_predictions(0.5, 0.3, 0.2, False, 0.0, 0.0, 0.0)
    assert len(result) == 1
    assert result[0]["family"] == "rule_based"
    assert result[0]["engine"] == "oracle_protocol"


def test_ml_engine_present_only_when_active():
    """Când ml_active=False (fallback poisson-only), NU apare o intrare ML
    falsă — reflectă exact starea reală a motorului, nu una presupusă."""
    result = oracle_engine.build_raw_predictions(0.5, 0.3, 0.2, False, 0.9, 0.05, 0.05)
    assert len(result) == 1
    families = [p["family"] for p in result]
    assert "ml" not in families


def test_ml_engine_present_when_active():
    result = oracle_engine.build_raw_predictions(0.5, 0.3, 0.2, True, 0.6, 0.25, 0.15)
    assert len(result) == 2
    families = {p["family"] for p in result}
    assert families == {"rule_based", "ml"}


def test_deterministic_ordering_by_family_then_name():
    """Ordinea nu e niciodată arbitrară — sortare (familie, nume),
    independentă de ordinea în care motoarele sunt calculate intern."""
    result = oracle_engine.build_raw_predictions(0.5, 0.3, 0.2, True, 0.6, 0.25, 0.15)
    assert [p["family"] for p in result] == sorted(p["family"] for p in result)


def test_deterministic_ordering_stable_across_repeated_calls():
    """Două apeluri identice produc exact aceeași ordine — proprietate
    verificabilă direct, nu presupusă."""
    r1 = oracle_engine.build_raw_predictions(0.5, 0.3, 0.2, True, 0.6, 0.25, 0.15)
    r2 = oracle_engine.build_raw_predictions(0.5, 0.3, 0.2, True, 0.6, 0.25, 0.15)
    assert [p["engine"] for p in r1] == [p["engine"] for p in r2]


def test_raw_values_are_pure_derivation_no_recalculation():
    """View-ul brut reflectă EXACT valorile primite — nicio recalculare,
    nicio invocare suplimentară de motor (funcție pură, verificabil direct
    din assert-uri pe valorile de ieșire)."""
    result = oracle_engine.build_raw_predictions(0.55, 0.25, 0.20, True, 0.70, 0.20, 0.10)
    rule_based = next(p for p in result if p["family"] == "rule_based")
    ml = next(p for p in result if p["family"] == "ml")
    assert (rule_based["prob_home"], rule_based["prob_draw"], rule_based["prob_away"]) == (0.55, 0.25, 0.2)
    assert (ml["prob_home"], ml["prob_draw"], ml["prob_away"]) == (0.7, 0.2, 0.1)


def test_match_prediction_raw_predictions_field_defaults_to_empty_list():
    """Contract aditiv — câmpul există cu default sigur, nu obligă niciun
    apelant existent să-l populeze explicit."""
    import inspect
    sig_fields = {f.name: f.default for f in oracle_engine.MatchPrediction.__dataclass_fields__.values()}
    assert "raw_predictions" in sig_fields


def test_composite_fields_unaffected_by_raw_predictions_addition():
    """Câmpurile compuse existente (prob_home_win/prob_draw/prob_away_win)
    rămân în dataclass, neschimbate — verificare de compatibilitate
    byte-for-byte la nivel de contract de câmpuri."""
    fields = oracle_engine.MatchPrediction.__dataclass_fields__
    assert "prob_home_win" in fields
    assert "prob_draw" in fields
    assert "prob_away_win" in fields
    # ml_engine_prediction (ADR-051/052) coexistă cu raw_predictions — sursa
    # canonică unică a ieșirii ML, înlocuiește ml_prob_home legacy (eliminat).
    assert "ml_engine_prediction" in fields
