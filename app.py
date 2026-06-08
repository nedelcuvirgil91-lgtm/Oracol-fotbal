"""
================================================================================
FOOTBALL ORACLE — Elite Personal Trading Terminal
================================================================================
Module  : app.py
Run     : streamlit run app.py
Depends : oracle_engine.py, oracle_api.py
          pip install streamlit pandas numpy scipy requests
================================================================================
"""

from __future__ import annotations

import json
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

# ─────────────────────────────────────────────────────────────────────────────
# PAGE CONFIG  (must be first Streamlit call)
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Football Oracle",
    page_icon="🔮",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────────────────────
# GLOBAL CSS — Dark terminal aesthetic, amber accents, monospace precision
# ─────────────────────────────────────────────────────────────────────────────
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@300;400;500;600&family=IBM+Plex+Sans:wght@300;400;500;600;700&display=swap');

    /* ── Root palette ── */
    :root {
        --bg-base:      #0a0c10;
        --bg-panel:     #0f1218;
        --bg-card:      #141820;
        --bg-hover:     #1a2030;
        --border:       #1e2535;
        --border-lit:   #2a3550;
        --amber:        #f5a623;
        --amber-dim:    #b87518;
        --amber-glow:   rgba(245,166,35,0.12);
        --green:        #00d17a;
        --green-dim:    rgba(0,209,122,0.12);
        --red:          #ff4757;
        --red-dim:      rgba(255,71,87,0.12);
        --blue:         #4a9eff;
        --blue-dim:     rgba(74,158,255,0.10);
        --text-primary: #e8eaf0;
        --text-secondary:#8892a4;
        --text-muted:   #4a5568;
        --mono:         'IBM Plex Mono', monospace;
        --sans:         'IBM Plex Sans', sans-serif;
    }

    /* ── Global reset ── */
    html, body, [class*="css"] {
        background-color: var(--bg-base) !important;
        color: var(--text-primary) !important;
        font-family: var(--sans) !important;
    }

    /* ── Hide Streamlit chrome ── */
    #MainMenu, footer, header { visibility: hidden; }
    .block-container { padding: 1.5rem 2rem 3rem !important; max-width: 100% !important; }

    /* ── Sidebar ── */
    [data-testid="stSidebar"] {
        background: var(--bg-panel) !important;
        border-right: 1px solid var(--border) !important;
    }
    [data-testid="stSidebar"] * { font-family: var(--mono) !important; }

    /* ── Sidebar radio as nav pills ── */
    [data-testid="stSidebar"] .stRadio > div {
        gap: 0 !important;
        flex-direction: column !important;
    }
    [data-testid="stSidebar"] .stRadio label {
        display: block !important;
        padding: 0.65rem 1rem !important;
        border-radius: 6px !important;
        margin: 2px 0 !important;
        font-size: 0.85rem !important;
        font-weight: 500 !important;
        letter-spacing: 0.02em !important;
        cursor: pointer !important;
        transition: all 0.15s ease !important;
        color: var(--text-secondary) !important;
        border: 1px solid transparent !important;
    }
    [data-testid="stSidebar"] .stRadio label:hover {
        background: var(--amber-glow) !important;
        color: var(--amber) !important;
        border-color: var(--amber-dim) !important;
    }

    /* ── Metric cards ── */
    [data-testid="stMetric"] {
        background: var(--bg-card) !important;
        border: 1px solid var(--border) !important;
        border-radius: 10px !important;
        padding: 1.1rem 1.3rem !important;
        position: relative !important;
        overflow: hidden !important;
    }
    [data-testid="stMetric"]::before {
        content: '';
        position: absolute;
        top: 0; left: 0;
        width: 3px; height: 100%;
        background: var(--amber);
        border-radius: 10px 0 0 10px;
    }
    [data-testid="stMetricLabel"] {
        font-family: var(--mono) !important;
        font-size: 0.7rem !important;
        letter-spacing: 0.1em !important;
        text-transform: uppercase !important;
        color: var(--text-secondary) !important;
    }
    [data-testid="stMetricValue"] {
        font-family: var(--mono) !important;
        font-size: 1.6rem !important;
        font-weight: 600 !important;
        color: var(--amber) !important;
    }
    [data-testid="stMetricDelta"] { font-family: var(--mono) !important; font-size: 0.75rem !important; }

    /* ── Buttons ── */
    .stButton > button {
        font-family: var(--mono) !important;
        font-size: 0.8rem !important;
        font-weight: 600 !important;
        letter-spacing: 0.08em !important;
        text-transform: uppercase !important;
        border-radius: 6px !important;
        transition: all 0.2s ease !important;
        border: 1px solid var(--border-lit) !important;
        background: var(--bg-card) !important;
        color: var(--text-primary) !important;
    }
    .stButton > button:hover {
        border-color: var(--amber) !important;
        color: var(--amber) !important;
        box-shadow: 0 0 12px var(--amber-glow) !important;
    }

    /* ── Primary (Oracle Run) button ── */
    .oracle-btn > button {
        background: linear-gradient(135deg, #1a1200, #2d1f00) !important;
        border: 1px solid var(--amber-dim) !important;
        color: var(--amber) !important;
        font-size: 0.9rem !important;
        padding: 0.6rem 1.4rem !important;
        width: 100% !important;
        box-shadow: 0 0 20px rgba(245,166,35,0.15) !important;
    }
    .oracle-btn > button:hover {
        box-shadow: 0 0 35px rgba(245,166,35,0.30) !important;
        border-color: var(--amber) !important;
    }

    /* ── Expander ── */
    [data-testid="stExpander"] {
        background: var(--bg-card) !important;
        border: 1px solid var(--border) !important;
        border-radius: 10px !important;
        margin-bottom: 0.75rem !important;
        overflow: hidden !important;
    }
    [data-testid="stExpander"]:hover { border-color: var(--border-lit) !important; }
    [data-testid="stExpander"] summary {
        font-family: var(--mono) !important;
        font-size: 0.88rem !important;
        padding: 0.85rem 1.1rem !important;
        color: var(--text-primary) !important;
    }

    /* ── Success / Warning / Error / Info ── */
    .stAlert { border-radius: 8px !important; border-left-width: 3px !important; font-family: var(--mono) !important; font-size: 0.8rem !important; }

    /* ── Progress bar ── */
    .stProgress > div > div { background-color: var(--amber) !important; border-radius: 4px !important; }
    .stProgress > div { background-color: var(--border) !important; border-radius: 4px !important; }

    /* ── Dataframe / table ── */
    [data-testid="stDataFrame"] {
        border: 1px solid var(--border) !important;
        border-radius: 8px !important;
        overflow: hidden !important;
    }
    .dataframe { font-family: var(--mono) !important; font-size: 0.78rem !important; }

    /* ── Input widgets ── */
    .stTextInput input, .stNumberInput input, .stSelectbox select {
        background: var(--bg-card) !important;
        border: 1px solid var(--border-lit) !important;
        border-radius: 6px !important;
        color: var(--text-primary) !important;
        font-family: var(--mono) !important;
        font-size: 0.85rem !important;
    }
    .stMultiSelect > div {
        background: var(--bg-card) !important;
        border: 1px solid var(--border-lit) !important;
        border-radius: 6px !important;
    }

    /* ── Divider ── */
    hr { border-color: var(--border) !important; margin: 1.5rem 0 !important; }

    /* ── Custom card component ── */
    .match-card {
        background: var(--bg-card);
        border: 1px solid var(--border);
        border-radius: 12px;
        padding: 1.2rem 1.5rem;
        margin-bottom: 1rem;
        transition: border-color 0.2s;
    }
    .match-card:hover { border-color: var(--border-lit); }

    .value-pill {
        display: inline-block;
        padding: 0.2rem 0.7rem;
        border-radius: 20px;
        font-family: var(--mono);
        font-size: 0.72rem;
        font-weight: 600;
        letter-spacing: 0.05em;
        margin-right: 0.4rem;
    }
    .pill-elite { background: rgba(245,166,35,0.2); color: #f5a623; border: 1px solid #f5a62355; }
    .pill-high  { background: rgba(255,71,87,0.15); color: #ff4757; border: 1px solid #ff475733; }
    .pill-medium{ background: rgba(0,209,122,0.12); color: #00d17a; border: 1px solid #00d17a33; }
    .pill-low   { background: rgba(74,158,255,0.12);color: #4a9eff; border: 1px solid #4a9eff33; }

    .stat-chip {
        display: inline-block;
        background: var(--bg-hover);
        border: 1px solid var(--border);
        border-radius: 6px;
        padding: 0.25rem 0.6rem;
        font-family: var(--mono);
        font-size: 0.75rem;
        color: var(--text-secondary);
        margin-right: 0.4rem;
        margin-bottom: 0.3rem;
    }
    .stat-chip span { color: var(--text-primary); font-weight: 600; }

    .section-label {
        font-family: var(--mono);
        font-size: 0.65rem;
        letter-spacing: 0.15em;
        text-transform: uppercase;
        color: var(--text-muted);
        margin-bottom: 0.4rem;
    }

    .amber { color: var(--amber) !important; }
    .green { color: var(--green) !important; }
    .red   { color: var(--red)   !important; }
    .muted { color: var(--text-secondary) !important; font-family: var(--mono); font-size: 0.8rem; }

    /* ── Sidebar brand ── */
    .brand-mark {
        font-family: var(--mono);
        font-size: 1.1rem;
        font-weight: 600;
        color: var(--amber);
        letter-spacing: 0.08em;
        padding: 0.3rem 0;
    }
    .brand-sub {
        font-family: var(--mono);
        font-size: 0.65rem;
        color: var(--text-muted);
        letter-spacing: 0.12em;
        text-transform: uppercase;
    }
    .sidebar-divider {
        border: none;
        border-top: 1px solid var(--border);
        margin: 1rem 0;
    }

    /* ── Score badge ── */
    .score-badge {
        display: inline-block;
        background: var(--bg-hover);
        border: 1px solid var(--border-lit);
        border-radius: 6px;
        padding: 0.3rem 0.8rem;
        font-family: var(--mono);
        font-size: 0.82rem;
        color: var(--text-secondary);
        margin: 0.15rem;
    }
    .score-badge.top1 {
        border-color: var(--amber-dim);
        color: var(--amber);
        background: var(--amber-glow);
    }

    /* ── Scrollbar ── */
    ::-webkit-scrollbar { width: 5px; height: 5px; }
    ::-webkit-scrollbar-track { background: var(--bg-base); }
    ::-webkit-scrollbar-thumb { background: var(--border-lit); border-radius: 10px; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ─────────────────────────────────────────────────────────────────────────────
# PATHS & CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────
BASE_DIR       = Path(__file__).parent
PORTFOLIO_PATH = BASE_DIR / "portfolio.csv"
CONFIG_PATH    = BASE_DIR / "config.json"
WEIGHTS_PATH   = BASE_DIR / "weights.json"

LEAGUES: dict[str, int] = {
    "🇷🇴  Romania SuperLiga":  283,
    "🇮🇹  Serie A":             135,
    "🏴󠁧󠁢󠁥󠁮󠁧󠁿  Premier League":       39,
    "🇪🇸  La Liga":             140,
    "🇩🇪  Bundesliga":           78,
    "🇫🇷  Ligue 1":              61,
    "🇳🇱  Eredivisie":           88,
    "🇵🇹  Primeira Liga":        94,
}

LEAGUE_CITIES: dict[int, str] = {
    283: "Bucharest", 135: "Rome", 39: "London",
    140: "Madrid",     78: "Berlin", 61: "Paris",
    88:  "Amsterdam",  94: "Lisbon",
}

# ─────────────────────────────────────────────────────────────────────────────
# ENGINE — cached singleton
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_resource(show_spinner=False)
def load_engine():
    """Load FootballOracleEngine once per session."""
    try:
        from oracle_engine import FootballOracleEngine
        return FootballOracleEngine()
    except Exception as exc:
        return str(exc)


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _load_portfolio() -> pd.DataFrame | None:
    if not PORTFOLIO_PATH.exists():
        return None
    try:
        df = pd.read_csv(PORTFOLIO_PATH)
        if df.empty:
            return None
        return df
    except Exception:
        return None


def _load_json_file(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _rating_pill(rating: str) -> str:
    r = rating.lower()
    if "elite" in r:
        return f'<span class="value-pill pill-elite">{rating}</span>'
    if "high" in r:
        return f'<span class="value-pill pill-high">{rating}</span>'
    if "medium" in r:
        return f'<span class="value-pill pill-medium">{rating}</span>'
    return f'<span class="value-pill pill-low">{rating}</span>'


def _form_badge(result: str) -> str:
    colours = {"W": "#00d17a", "D": "#f5a623", "L": "#ff4757"}
    c = colours.get(result.upper(), "#8892a4")
    return (
        f'<span style="display:inline-block;width:22px;height:22px;line-height:22px;'
        f'text-align:center;border-radius:4px;background:{c}22;border:1px solid {c}55;'
        f'color:{c};font-family:var(--mono);font-size:0.7rem;font-weight:700;'
        f'margin-right:3px">{result.upper()}</span>'
    )


def _prob_bar_row(label: str, prob: float, colour: str) -> str:
    pct = prob * 100
    bar_w = max(int(pct * 2), 2)   # scale to max 200px for 100%
    return f"""
    <div style="display:flex;align-items:center;gap:10px;margin:5px 0;">
        <div style="width:80px;font-family:var(--mono);font-size:0.75rem;
                    color:var(--text-secondary);text-align:right;">{label}</div>
        <div style="flex:1;background:#1e2535;border-radius:4px;height:8px;overflow:hidden;">
            <div style="width:{min(pct,100):.1f}%;background:{colour};
                        height:100%;border-radius:4px;transition:width 0.4s;"></div>
        </div>
        <div style="width:52px;font-family:var(--mono);font-size:0.8rem;
                    color:{colour};font-weight:600;">{pct:.1f}%</div>
    </div>"""


def _match_header_html(home: str, away: str, kickoff: str) -> str:
    ko = kickoff[:16].replace("T", " ") if kickoff else "TBA"
    return f"""
    <div style="display:flex;justify-content:space-between;align-items:center;
                margin-bottom:0.2rem;">
        <div>
            <span style="font-family:var(--mono);font-size:1.05rem;
                         font-weight:600;color:var(--text-primary);">
                {home}
            </span>
            <span style="font-family:var(--mono);font-size:0.85rem;
                         color:var(--text-muted);margin:0 0.6rem;">vs</span>
            <span style="font-family:var(--mono);font-size:1.05rem;
                         font-weight:600;color:var(--text-primary);">
                {away}
            </span>
        </div>
        <div style="font-family:var(--mono);font-size:0.72rem;
                    color:var(--text-muted);letter-spacing:0.05em;">
            ⏱ {ko}
        </div>
    </div>"""


def _xg_chip(label: str, val: float, home: bool = True) -> str:
    colour = "#4a9eff" if home else "#f5a623"
    return f"""
    <div style="text-align:center;background:#141820;border:1px solid #1e2535;
                border-radius:8px;padding:0.5rem 0.8rem;">
        <div style="font-family:var(--mono);font-size:0.6rem;color:#8892a4;
                    letter-spacing:0.1em;text-transform:uppercase;">{label}</div>
        <div style="font-family:var(--mono);font-size:1.4rem;font-weight:600;
                    color:{colour};">{val:.3f}</div>
        <div style="font-family:var(--mono);font-size:0.6rem;color:#4a5568;">xG</div>
    </div>"""


# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown(
        '<div class="brand-mark">⚡ FOOTBALL ORACLE</div>'
        '<div class="brand-sub">Elite Intelligence Terminal · v4.0</div>',
        unsafe_allow_html=True,
    )
    st.markdown('<hr class="sidebar-divider">', unsafe_allow_html=True)

    nav = st.radio(
        "NAVIGATION",
        options=[
            "🔮  Today's Oracle Predictions",
            "📊  Portfolio & Analytics",
            "⚙️  Model Calibration",
        ],
        label_visibility="collapsed",
    )

    st.markdown('<hr class="sidebar-divider">', unsafe_allow_html=True)

    # Live clock
    now = datetime.utcnow()
    st.markdown(
        f'<div style="font-family:var(--mono);font-size:0.7rem;color:var(--text-muted);">'
        f'UTC  {now.strftime("%Y-%m-%d")}<br>'
        f'<span style="font-size:1rem;color:var(--amber);font-weight:600;">'
        f'{now.strftime("%H:%M:%S")}</span></div>',
        unsafe_allow_html=True,
    )

    st.markdown('<hr class="sidebar-divider">', unsafe_allow_html=True)

    # Engine status
    engine_obj = load_engine()
    if isinstance(engine_obj, str):
        st.error(f"Engine error:\n{engine_obj}")
        engine = None
    else:
        engine = engine_obj
        st.markdown(
            '<div style="font-family:var(--mono);font-size:0.7rem;">'
            '<span style="color:#00d17a;">●</span>'
            ' Engine  <span style="color:#00d17a;">ONLINE</span></div>',
            unsafe_allow_html=True,
        )

    st.markdown('<br>', unsafe_allow_html=True)
    st.caption("Private single-user build. All data processed in-memory.")


# ─────────────────────────────────────────────────────────────────────────────
# PAGE HEADER UTILITY
# ─────────────────────────────────────────────────────────────────────────────

def _page_header(icon: str, title: str, subtitle: str = "") -> None:
    st.markdown(
        f"""
        <div style="margin-bottom:1.8rem;">
            <div style="font-family:var(--mono);font-size:0.65rem;
                        letter-spacing:0.18em;color:var(--text-muted);
                        text-transform:uppercase;margin-bottom:0.3rem;">
                Football Oracle Terminal
            </div>
            <div style="font-family:'IBM Plex Mono',monospace;font-size:1.6rem;
                        font-weight:600;color:var(--amber);letter-spacing:0.03em;">
                {icon}  {title}
            </div>
            {'<div style="font-family:var(--mono);font-size:0.82rem;color:var(--text-secondary);margin-top:0.3rem;">'+subtitle+'</div>' if subtitle else ''}
            <div style="height:2px;background:linear-gradient(90deg,var(--amber-dim),transparent);
                        margin-top:0.8rem;border-radius:2px;"></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ═════════════════════════════════════════════════════════════════════════════
# VIEW 1 — TODAY'S ORACLE PREDICTIONS
# ═════════════════════════════════════════════════════════════════════════════

if nav == "🔮  Today's Oracle Predictions":
    _page_header(
        "🔮", "TODAY'S ORACLE PREDICTIONS",
        f"Poisson model · xG calibration · Value bet detection  —  {date.today().isoformat()}"
    )

    if not engine:
        st.error("Engine offline. Check oracle_engine.py and oracle_api.py are in the same directory.")
        st.stop()

    # ── League selector ───────────────────────────────────────────────────
    st.markdown("#### SELECT LEAGUES")
    col_l, col_r = st.columns([3, 1])
    with col_l:
        selected_labels = st.multiselect(
            "Choose leagues to scan",
            options=list(LEAGUES.keys()),
            default=["🇷🇴  Romania SuperLiga", "🇮🇹  Serie A"],
            label_visibility="collapsed",
        )
    with col_r:
        threshold_override = st.number_input(
            "Edge threshold %",
            min_value=1.0, max_value=30.0,
            value=float(engine.config.get("value_bet_threshold_pct", 5.0)),
            step=0.5,
            help="Minimum edge % to flag a value bet",
        )

    selected_ids = [LEAGUES[l] for l in selected_labels]

    st.markdown('<br>', unsafe_allow_html=True)

    # ── RUN button ────────────────────────────────────────────────────────
    st.markdown('<div class="oracle-btn">', unsafe_allow_html=True)
    run_oracle = st.button("⚡  RUN ORACLE INTELLIGENCE", use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)

    # ── Execution ─────────────────────────────────────────────────────────
    if run_oracle:
        if not selected_ids:
            st.warning("Select at least one league before running.")
            st.stop()

        # Override threshold dynamically
        engine.config["value_bet_threshold_pct"] = threshold_override

        with st.spinner("📡  Scanning live fixtures …"):
            fixtures_raw = engine.api.get_fixtures_for_today(selected_ids)

        if not fixtures_raw:
            st.info(
                "No fixtures found for today in the selected leagues. "
                "Try again later or add more leagues."
            )
            st.stop()

        st.success(f"Found **{len(fixtures_raw)}** fixture(s) for today. Running analysis…")
        st.markdown("---")

        predictions_store = []   # accumulate for session state

        for idx, fix in enumerate(fixtures_raw):
            fixture_id   = fix["fixture"]["id"]
            kickoff      = fix["fixture"]["date"]
            home_name    = fix["teams"]["home"]["name"]
            away_name    = fix["teams"]["away"]["name"]
            home_id      = fix["teams"]["home"]["id"]
            away_id      = fix["teams"]["away"]["id"]
            league_id    = fix["league"]["id"]
            league_name  = fix["league"]["name"]
            match_name   = f"{home_name} vs {away_name}"
            city         = LEAGUE_CITIES.get(league_id, fix.get("fixture", {}).get("venue", {}).get("city", "Unknown"))

            expander_label = (
                f"{'⚡' if True else '  '}  {home_name}  ·  {away_name}  "
                f"  |  {league_name}  |  {kickoff[11:16]} UTC"
            )

            with st.expander(expander_label, expanded=(idx == 0)):
                # Header
                st.markdown(
                    _match_header_html(home_name, away_name, kickoff),
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f'<div class="muted">🏟 {city}  ·  League ID {league_id}  ·  Fixture ID {fixture_id}</div>',
                    unsafe_allow_html=True,
                )
                st.markdown('<br>', unsafe_allow_html=True)

                                with st.spinner(f"Analysing {match_name} …"):
                    pred = engine.evaluate_match(
                        fixture_id   = fixture_id,
                        home_team_id = home_id,
                        away_team_id = away_id,
                        league_id    = league_id,
                        city         = city,
                        match_name   = match_name,
                        season       = 2026,  # Setați fix pe 2026 pentru toate
                    )


                if pred is None:
                    st.error("Analysis failed — insufficient historical data for one or both teams.")
                    continue

                predictions_store.append(pred)

                # ── xG row ────────────────────────────────────────────────
                st.markdown('<div class="section-label">Expected Goals (xG)</div>', unsafe_allow_html=True)
                xg_c1, xg_c2, xg_c3 = st.columns([2, 1, 2])
                with xg_c1:
                    st.markdown(_xg_chip(home_name, pred.home_xg, home=True), unsafe_allow_html=True)
                with xg_c2:
                    st.markdown(
                        '<div style="text-align:center;padding-top:0.8rem;'
                        'font-family:var(--mono);font-size:0.9rem;color:var(--text-muted);">vs</div>',
                        unsafe_allow_html=True
                    )
                with xg_c3:
                    st.markdown(_xg_chip(away_name, pred.away_xg, home=False), unsafe_allow_html=True)

                st.markdown('<br>', unsafe_allow_html=True)

                # ── Probability bars ──────────────────────────────────────
                st.markdown('<div class="section-label">Poisson Probability Model</div>', unsafe_allow_html=True)
                prob_html = (
                    _prob_bar_row("Home Win", pred.prob_home_win, "#4a9eff")
                    + _prob_bar_row("Draw",    pred.prob_draw,     "#f5a623")
                    + _prob_bar_row("Away Win", pred.prob_away_win, "#ff4757")
                )
                st.markdown(prob_html, unsafe_allow_html=True)

                st.markdown('<br>', unsafe_allow_html=True)

                # ── Top predicted scores ──────────────────────────────────
                st.markdown('<div class="section-label">Top Predicted Scorelines</div>', unsafe_allow_html=True)
                score_html = ""
                for i, (hg, ag, pct) in enumerate(pred.top_scores[:6]):
                    css_class = "score-badge top1" if i == 0 else "score-badge"
                    score_html += f'<span class="{css_class}">{hg}-{ag} <small>({pct:.1f}%)</small></span>'
                st.markdown(score_html, unsafe_allow_html=True)

                st.markdown('<br>', unsafe_allow_html=True)

                # ── Bookmaker odds & edge ─────────────────────────────────
                st.markdown(
                    f'<div class="section-label">Bookmaker Odds — {pred.bookmaker_name}</div>',
                    unsafe_allow_html=True
                )
                odds_c1, odds_c2, odds_c3 = st.columns(3)
                for col, label, bk_odds, model_pct, edge_pct in [
                    (odds_c1, "HOME WIN",  pred.bk_home_odds, pred.prob_home_win * 100, pred.edge_home_pct),
                    (odds_c2, "DRAW",      pred.bk_draw_odds, pred.prob_draw     * 100, pred.edge_draw_pct),
                    (odds_c3, "AWAY WIN",  pred.bk_away_odds, pred.prob_away_win * 100, pred.edge_away_pct),
                ]:
                    with col:
                        edge_colour = "#00d17a" if edge_pct > 0 else "#ff4757"
                        odds_display = f"{bk_odds:.2f}" if bk_odds > 1 else "N/A"
                        st.markdown(
                            f"""
                            <div style="background:var(--bg-hover);border:1px solid var(--border);
                                        border-radius:8px;padding:0.7rem;text-align:center;">
                                <div style="font-family:var(--mono);font-size:0.6rem;
                                            letter-spacing:0.1em;color:var(--text-muted);">{label}</div>
                                <div style="font-family:var(--mono);font-size:1.3rem;
                                            font-weight:600;color:var(--text-primary);">{odds_display}</div>
                                <div style="font-family:var(--mono);font-size:0.7rem;
                                            color:var(--text-secondary);">Model {model_pct:.1f}%</div>
                                <div style="font-family:var(--mono);font-size:0.75rem;
                                            color:{edge_colour};font-weight:600;">
                                    Edge {'+' if edge_pct>0 else ''}{edge_pct:.1f}%
                                </div>
                            </div>""",
                            unsafe_allow_html=True,
                        )

                # ── Weather note ──────────────────────────────────────────
                if pred.weather_applied:
                    st.warning(f"🌧  {pred.weather_note}")
                else:
                    st.markdown(
                        f'<div class="muted" style="margin-top:0.6rem;">{pred.weather_note}</div>',
                        unsafe_allow_html=True,
                    )

                st.markdown('<br>', unsafe_allow_html=True)

                # ── VALUE BETS ────────────────────────────────────────────
                if pred.value_bets:
                    st.markdown('<div class="section-label">🎯 Value Bets Detected</div>', unsafe_allow_html=True)
                    for vb in pred.value_bets:
                        sel       = vb["selection"]
                        edge      = vb["edge_pct"]
                        rating    = vb["rating"]
                        bk_odds_v = vb["bk_odds"]
                        model_p   = vb["model_prob_pct"]
                        kelly     = pred.kelly_stakes.get(sel, 0.0)

                        vb_col1, vb_col2 = st.columns([3, 1])
                        with vb_col1:
                            st.success(
                                f"{rating}  **{sel}**  @  **{bk_odds_v:.2f}**  |  "
                                f"Edge: **+{edge:.1f}%**  |  Model: {model_p:.1f}%  |  "
                                f"Kelly stake: **€{kelly:.2f}**"
                            )
                        with vb_col2:
                            log_key = f"log_{fixture_id}_{sel.replace(' ','_')}"
                            if st.button(f"📌 Log Bet", key=log_key):
                                engine.log_bet(
                                    fixture_id = fixture_id,
                                    match_name  = match_name,
                                    market     = vb["market"],
                                    selection  = sel,
                                    odds       = bk_odds_v,
                                    stake      = kelly if kelly > 0 else float(engine.config.get("stake_default", 10.0)),
                                    result     = "",
                                )
                                st.toast(f"✅  Bet logged → {match_name} | {sel}", icon="📌")
                else:
                    st.info("No value bets detected above the edge threshold for this fixture.")

                st.markdown("---")

        if not predictions_store:
            st.warning("Analysis complete — no predictions generated. Check API quotas.")


# ═════════════════════════════════════════════════════════════════════════════
# VIEW 2 — PORTFOLIO & ANALYTICS
# ═════════════════════════════════════════════════════════════════════════════

elif nav == "📊  Portfolio & Analytics":
    _page_header(
        "📊", "PORTFOLIO & ANALYTICS",
        "Track your bets, measure edge, and monitor bankroll growth."
    )

    df = _load_portfolio()

    # ── Top metrics ───────────────────────────────────────────────────────
    if df is not None and not df.empty:
        settled   = df[df["Result"].isin(["W", "L"])]
        total     = len(settled)
        wins      = len(settled[settled["Result"] == "W"])
        win_rate  = wins / total * 100 if total > 0 else 0.0
        staked    = settled["Stake"].sum() if total > 0 else 0.0
        net_pnl   = settled["PnL"].sum()   if total > 0 else 0.0
        roi       = net_pnl / staked * 100 if staked > 0 else 0.0
        pending   = len(df[df["Result"] == "PENDING"])

        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("SETTLED BETS",  total)
        m2.metric("WIN RATE",      f"{win_rate:.1f}%")
        m3.metric("TOTAL STAKED",  f"€{staked:.2f}")
        m4.metric("NET P&L",       f"€{net_pnl:+.2f}", delta=f"{roi:+.1f}% ROI")
        m5.metric("PENDING",       pending)

        st.markdown('<br>', unsafe_allow_html=True)

        # ── Cumulative PnL chart ─────────────────────────────────────────
        if total >= 2:
            st.markdown("#### BANKROLL CURVE")
            settled_sorted = settled.copy().reset_index(drop=True)
            settled_sorted["Cumulative PnL"] = settled_sorted["PnL"].cumsum()
            settled_sorted["Bet #"] = settled_sorted.index + 1

            chart_df = settled_sorted.set_index("Bet #")[["Cumulative PnL"]]
            st.line_chart(chart_df, color="#f5a623", height=220)

        st.markdown('<br>', unsafe_allow_html=True)

        # ── Full bet table ───────────────────────────────────────────────
        st.markdown("#### FULL BET HISTORY")

        def _style_result(val: str) -> str:
            if val == "W":   return "color:#00d17a;font-weight:700"
            if val == "L":   return "color:#ff4757;font-weight:700"
            if val == "PENDING": return "color:#f5a623"
            return ""

        def _style_pnl(val: float) -> str:
            if isinstance(val, (int, float)):
                return "color:#00d17a" if val > 0 else ("color:#ff4757" if val < 0 else "")
            return ""

        styled = (
            df.style
            .applymap(_style_result,  subset=["Result"])
            .applymap(_style_pnl,     subset=["PnL"])
            .format({"Odds": "{:.2f}", "Stake": "€{:.2f}", "PnL": "€{:+.2f}"})
        )
        st.dataframe(styled, use_container_width=True, height=320)

        # ── Win/Loss breakdown per market ────────────────────────────────
        if "Market" in df.columns and total >= 3:
            st.markdown("#### PERFORMANCE BY MARKET")
            grp = (
                settled.groupby("Market")
                .agg(Bets=("Result","count"), Wins=("Result", lambda x: (x=="W").sum()),
                     PnL=("PnL","sum"), Staked=("Stake","sum"))
                .reset_index()
            )
            grp["Win %"] = (grp["Wins"] / grp["Bets"] * 100).round(1)
            grp["ROI %"] = (grp["PnL"] / grp["Staked"] * 100).round(1)
            st.dataframe(grp, use_container_width=True)

    else:
        st.info("📭  No settled bets found in `portfolio.csv` yet.  Run the Oracle and log some bets first.")

    # ── Manual bet logger ─────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### ✏️  MANUAL BET ENTRY")

    with st.form("manual_bet_form"):
        fc1, fc2, fc3 = st.columns(3)
        with fc1:
            mb_match = st.text_input("Match Name", placeholder="Juventus vs Inter")
            mb_market = st.selectbox("Market", ["1X2", "BTTS", "Over 2.5", "Asian Handicap", "Other"])
        with fc2:
            mb_sel    = st.text_input("Selection", placeholder="Home Win")
            mb_odds   = st.number_input("Odds", min_value=1.01, max_value=100.0, value=2.00, step=0.05)
        with fc3:
            mb_stake  = st.number_input("Stake (€)", min_value=0.1, value=10.0, step=0.5)
            mb_result = st.selectbox("Result", ["PENDING", "W", "L", "V"])
            mb_fix_id = st.number_input("Fixture ID (optional)", min_value=0, value=0, step=1)

        submitted = st.form_submit_button("📌  LOG BET", use_container_width=True)
        if submitted:
            if not mb_match or not mb_sel:
                st.error("Match name and selection are required.")
            else:
                if engine:
                    engine.log_bet(
                        fixture_id = int(mb_fix_id),
                        match_name  = mb_match,
                        market     = mb_market,
                        selection  = mb_sel,
                        odds       = mb_odds,
                        stake      = mb_stake,
                        result     = "" if mb_result == "PENDING" else mb_result,
                    )
                    st.success(f"✅  Bet logged: {mb_match} | {mb_sel} @ {mb_odds:.2f}")
                    st.rerun()
                else:
                    st.error("Engine offline.")

    # ── Update pending bet status ─────────────────────────────────────────
    pending_df = None
    if df is not None:
        pending_df = df[df["Result"] == "PENDING"]

    if pending_df is not None and not pending_df.empty:
        st.markdown("---")
        st.markdown("#### 🔄  UPDATE PENDING BETS")
        st.dataframe(pending_df[["Date","Match","Selection","Odds","Stake"]], use_container_width=True)

        with st.form("update_pending_form"):
            row_idx = st.selectbox(
                "Select row index to update",
                options=pending_df.index.tolist(),
                format_func=lambda i: f"#{i}  {pending_df.loc[i,'Match']}  —  {pending_df.loc[i,'Selection']}",
            )
            new_result = st.selectbox("New Result", ["W", "L", "V"])
            update_submitted = st.form_submit_button("✅  UPDATE RESULT", use_container_width=True)

            if update_submitted:
                full_df = pd.read_csv(PORTFOLIO_PATH)
                odds_val  = float(full_df.loc[row_idx, "Odds"])
                stake_val = float(full_df.loc[row_idx, "Stake"])
                if new_result == "W":
                    pnl = round(stake_val * (odds_val - 1), 2)
                elif new_result == "L":
                    pnl = round(-stake_val, 2)
                else:
                    pnl = 0.0
                full_df.at[row_idx, "Result"] = new_result
                full_df.at[row_idx, "PnL"]    = pnl
                full_df.to_csv(PORTFOLIO_PATH, index=False)
                st.success(f"Updated row #{row_idx} → Result={new_result}  PnL=€{pnl:+.2f}")
                st.rerun()


# ═════════════════════════════════════════════════════════════════════════════
# VIEW 3 — MODEL CALIBRATION
# ═════════════════════════════════════════════════════════════════════════════

elif nav == "⚙️  Model Calibration":
    _page_header(
        "⚙️", "MODEL CALIBRATION",
        "Inspect and edit the mathematical weights that drive Oracle predictions."
    )

    if not engine:
        st.error("Engine offline.")
        st.stop()

    tab1, tab2 = st.tabs(["🎛  Weights", "⚡  Config"])

    with tab1:
        st.markdown("#### MODEL WEIGHTS  (`weights.json`)")
        st.caption("These multipliers control xG calibration and team rating formulas.")
        weights = _load_json_file(WEIGHTS_PATH)

        if not weights:
            st.warning("weights.json not found. Run the engine once to generate defaults.")
        else:
            # Editable fields
            with st.form("weights_form"):
                wc1, wc2 = st.columns(2)

                with wc1:
                    st.markdown("**Form & DNA**")
                    new_fw  = st.slider("form_weight",  0.0, 1.0, float(weights.get("form_weight",  0.6)),  0.05)
                    new_dw  = st.slider("dna_weight",   0.0, 1.0, float(weights.get("dna_weight",   0.4)),  0.05)
                    st.markdown("**Offensive Rating**")
                    new_gw  = st.slider("goals_weight", 0.0, 1.0, float(weights.get("goals_weight", 0.45)), 0.05)
                    new_sow = st.slider("shots_ot_weight",  0.0, 1.0, float(weights.get("shots_ot_weight", 0.3)), 0.05)
                    new_pw  = st.slider("possession_weight",0.0, 1.0, float(weights.get("possession_weight",0.25)),0.05)

                with wc2:
                    st.markdown("**Caps**")
                    new_ocap = st.number_input("offensive_cap", 1.0, 6.0, float(weights.get("offensive_cap", 3.5)), 0.1)
                    new_dcap = st.number_input("defensive_cap", 0.5, 5.0, float(weights.get("defensive_cap", 2.5)), 0.1)

                    st.markdown("**League Baselines (avg goals/team)**")
                    baselines = weights.get("league_baselines", {})
                    new_baselines = {}
                    for league_label, lid in LEAGUES.items():
                        key = str(lid)
                        default_val = float(baselines.get(key, baselines.get("default", 1.25)))
                        short_label = league_label.split("  ")[-1]
                        new_baselines[key] = st.number_input(
                            short_label, 0.5, 2.5, default_val, 0.05,
                            key=f"bl_{lid}"
                        )
                    new_baselines["default"] = float(baselines.get("default", 1.25))

                save_weights = st.form_submit_button("💾  SAVE WEIGHTS", use_container_width=True)
                if save_weights:
                    weights.update({
                        "form_weight":       round(new_fw,  2),
                        "dna_weight":        round(new_dw,  2),
                        "goals_weight":      round(new_gw,  2),
                        "shots_ot_weight":   round(new_sow, 2),
                        "possession_weight": round(new_pw,  2),
                        "offensive_cap":     round(new_ocap,1),
                        "defensive_cap":     round(new_dcap,1),
                        "league_baselines":  new_baselines,
                    })
                    WEIGHTS_PATH.write_text(json.dumps(weights, indent=4), encoding="utf-8")
                    engine.weights = weights   # hot-reload into engine
                    st.success("✅  weights.json saved and engine reloaded.")

            # Raw JSON viewer
            with st.expander("📄  Raw JSON — weights.json", expanded=False):
                st.code(json.dumps(_load_json_file(WEIGHTS_PATH), indent=4), language="json")

    with tab2:
        st.markdown("#### ENGINE CONFIG  (`config.json`)")
        st.caption("Runtime thresholds, Poisson settings, and portfolio defaults.")
        config = _load_json_file(CONFIG_PATH)

        if not config:
            st.warning("config.json not found. Run the engine once to generate defaults.")
        else:
            with st.form("config_form"):
                cc1, cc2 = st.columns(2)
                with cc1:
                    new_threshold = st.number_input(
                        "value_bet_threshold_pct",
                        min_value=1.0, max_value=30.0,
                        value=float(config.get("value_bet_threshold_pct", 5.0)), step=0.5,
                    )
                    new_max_goals = st.number_input(
                        "max_goals_poisson",
                        min_value=5, max_value=15,
                        value=int(config.get("max_goals_poisson", 8)), step=1,
                    )
                    new_last_n = st.number_input(
                        "last_n_fixtures",
                        min_value=3, max_value=10,
                        value=int(config.get("last_n_fixtures", 5)), step=1,
                    )
                with cc2:
                    new_stake = st.number_input(
                        "stake_default (€)",
                        min_value=1.0, max_value=1000.0,
                        value=float(config.get("stake_default", 10.0)), step=1.0,
                    )
                    new_kelly = st.slider(
                        "kelly_fraction",
                        0.05, 1.0,
                        float(config.get("kelly_fraction", 0.25)), 0.05,
                    )
                    new_weather_pen = st.slider(
                        "weather_xg_penalty",
                        0.0, 0.3,
                        float(config.get("weather_xg_penalty", 0.08)), 0.01,
                    )

                save_config = st.form_submit_button("💾  SAVE CONFIG", use_container_width=True)
                if save_config:
                    config.update({
                        "value_bet_threshold_pct": round(new_threshold, 1),
                        "max_goals_poisson":       int(new_max_goals),
                        "last_n_fixtures":         int(new_last_n),
                        "stake_default":           round(new_stake, 2),
                        "kelly_fraction":          round(new_kelly, 2),
                        "weather_xg_penalty":      round(new_weather_pen, 3),
                    })
                    CONFIG_PATH.write_text(json.dumps(config, indent=4), encoding="utf-8")
                    engine.config = config   # hot-reload
                    st.success("✅  config.json saved and engine reloaded.")

            with st.expander("📄  Raw JSON — config.json", expanded=False):
                st.code(json.dumps(_load_json_file(CONFIG_PATH), indent=4), language="json")

        # ── System diagnostics ────────────────────────────────────────────
        st.markdown("---")
        st.markdown("#### 🔍  SYSTEM DIAGNOSTICS")
        diag_c1, diag_c2, diag_c3 = st.columns(3)
        with diag_c1:
            df_p = _load_portfolio()
            rows = len(df_p) if df_p is not None else 0
            st.markdown(
                f'<div class="stat-chip">portfolio.csv  <span>{rows} rows</span></div>',
                unsafe_allow_html=True,
            )
        with diag_c2:
            cfg_ok = CONFIG_PATH.exists()
            wgt_ok = WEIGHTS_PATH.exists()
            st.markdown(
                f'<div class="stat-chip">config.json  <span>{"✅" if cfg_ok else "❌"}</span></div>'
                f'<div class="stat-chip">weights.json  <span>{"✅" if wgt_ok else "❌"}</span></div>',
                unsafe_allow_html=True,
            )
        with diag_c3:
            st.markdown(
                f'<div class="stat-chip">Engine  <span>{"✅ ONLINE" if engine else "❌ OFFLINE"}</span></div>',
                unsafe_allow_html=True,
            )
            st.markdown(
                f'<div class="stat-chip">Python  <span>{sys.version[:6]}</span></div>',
                unsafe_allow_html=True,
            )
