@dataclass
class MatchPrediction:
    fixture_id:        str
    home_team:         str
    away_team:         str
    league:            str
    kickoff_utc:       str
    kickoff_date:      str
    season:            int
    home_xg:           float
    away_xg:           float
    prob_home_win:     float
    prob_draw:         float
    prob_away_win:     float
    top_scores:        list[tuple[int, int, float]]
    bk_home_odds:      float
    bk_draw_odds:      float
    bk_away_odds:      float
    bookmaker_name:    str
    impl_home_pct:     float
    impl_draw_pct:     float
    impl_away_pct:     float
    edge_home_pct:     float
    edge_draw_pct:     float
    edge_away_pct:     float
    value_bets:        list[dict]
    weather_note:      str
    weather_penalty:   float
    kelly_stakes:      dict[str, float]
    home_profile:      TeamProfile | None
    away_profile:      TeamProfile | None
    h2h:               H2HRecord | None
    data_quality_home: str
    data_quality_away: str
    home_injury_report: Any | None
    away_injury_report: Any | None
    injury_note:        str
    home_xg_pre_injury: float
    away_xg_pre_injury: float
    # ── Monte Carlo & Confidence (default=0 pentru compatibilitate) ───────
    mc_prob_home:             float = 0.0
    mc_prob_draw:             float = 0.0
    mc_prob_away:             float = 0.0
    confidence_score:         float = 0.0
    confidence_label:         str   = ""
    mc_simulations:           int   = 0
    # ── Piețe speciale ────────────────────────────────────────────────────
    prob_over25:              float = 0.0
    prob_over15:              float = 0.0
    prob_under25:             float = 0.0
    prob_btts:                float = 0.0
    prob_clean_sheet_home:    float = 0.0
    prob_clean_sheet_away:    float = 0.0
    prob_double_chance_home:  float = 0.0
    prob_double_chance_away:  float = 0.0
    special_value_bets:       list  = field(default_factory=list)
