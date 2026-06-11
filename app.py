"""
================================================================================
FOOTBALL ORACLE — Elite Terminal UI (Hybrid Edition v2.0)
================================================================================
Module  : app.py
Run     : streamlit run app.py
Layout  : Tabs Azi / Mâine / Săptămână  +  Portfolio  +  Calibration
Changes : World Cup 2026 prioritizat, MLS adăugat, ESPN source, demo mode
================================================================================
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

# ─────────────────────────────────────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Football Oracle",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────────────────────
# CSS
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@300;400;500;600&family=IBM+Plex+Sans:wght@300;400;500;600;700&display=swap');
:root {
    --bg:     #0a0c10; --panel: #0f1218; --card:  #141820; --hover: #1a2030;
    --border: #1e2535; --blit:  #2a3550;
    --amber:  #f5a623; --adim:  #b87518; --aglow: rgba(245,166,35,0.12);
    --green:  #00d17a; --red:   #ff4757; --blue:  #4a9eff;
    --t1: #e8eaf0;     --t2: #8892a4;    --tm: #4a5568;
    --mono: 'IBM Plex Mono', monospace;
    --sans: 'IBM Plex Sans', sans-serif;
}
html,body,[class*="css"]{ background:var(--bg)!important; color:var(--t1)!important; font-family:var(--sans)!important; }
#MainMenu,footer,header{ visibility:hidden; }
.block-container{ padding:1.5rem 2rem 3rem!important; max-width:100%!important; }

[data-testid="stSidebar"]{ background:var(--panel)!important; border-right:1px solid var(--border)!important; }
[data-testid="stSidebar"] *{ font-family:var(--mono)!important; }
[data-testid="stSidebar"] .stRadio>div{ gap:0!important; flex-direction:column!important; }
[data-testid="stSidebar"] .stRadio label{
    display:block!important; padding:.65rem 1rem!important; border-radius:6px!important;
    margin:2px 0!important; font-size:.85rem!important; font-weight:500!important;
    cursor:pointer!important; color:var(--t2)!important; border:1px solid transparent!important; transition:all .15s!important;
}
[data-testid="stSidebar"] .stRadio label:hover{ background:var(--aglow)!important; color:var(--amber)!important; border-color:var(--adim)!important; }

[data-testid="stMetric"]{ background:var(--card)!important; border:1px solid var(--border)!important; border-radius:10px!important; padding:1.1rem 1.3rem!important; position:relative!important; overflow:hidden!important; }
[data-testid="stMetric"]::before{ content:''; position:absolute; top:0; left:0; width:3px; height:100%; background:var(--amber); border-radius:10px 0 0 10px; }
[data-testid="stMetricLabel"]{ font-family:var(--mono)!important; font-size:.7rem!important; letter-spacing:.1em!important; text-transform:uppercase!important; color:var(--t2)!important; }
[data-testid="stMetricValue"]{ font-family:var(--mono)!important; font-size:1.6rem!important; font-weight:600!important; color:var(--amber)!important; }

.stButton>button{ font-family:var(--mono)!important; font-size:.8rem!important; font-weight:600!important; letter-spacing:.08em!important; text-transform:uppercase!important; border-radius:6px!important; border:1px solid var(--blit)!important; background:var(--card)!important; color:var(--t1)!important; transition:all .2s!important; }
.stButton>button:hover{ border-color:var(--amber)!important; color:var(--amber)!important; box-shadow:0 0 12px var(--aglow)!important; }
.oracle-btn>button{ background:linear-gradient(135deg,#1a1200,#2d1f00)!important; border:1px solid var(--adim)!important; color:var(--amber)!important; font-size:.9rem!important; width:100%!important; box-shadow:0 0 20px rgba(245,166,35,.15)!important; }
.oracle-btn>button:hover{ box-shadow:0 0 35px rgba(245,166,35,.3)!important; }

[data-testid="stExpander"]{ background:var(--card)!important; border:1px solid var(--border)!important; border-radius:10px!important; margin-bottom:.75rem!important; }
[data-testid="stExpander"]:hover{ border-color:var(--blit)!important; }
[data-testid="stExpander"] summary{ font-family:var(--mono)!important; font-size:.88rem!important; padding:.85rem 1.1rem!important; color:var(--t1)!important; }
.stAlert{ border-radius:8px!important; border-left-width:3px!important; font-family:var(--mono)!important; font-size:.8rem!important; }
[data-testid="stDataFrame"]{ border:1px solid var(--border)!important; border-radius:8px!important; }

.stTextInput input,.stNumberInput input{ background:var(--card)!important; border:1px solid var(--blit)!important; border-radius:6px!important; color:var(--t1)!important; font-family:var(--mono)!important; }
.stMultiSelect>div,.stSelectbox>div{ background:var(--card)!important; border:1px solid var(--blit)!important; border-radius:6px!important; }
hr{ border-color:var(--border)!important; margin:1.5rem 0!important; }

[data-testid="stTabs"] [role="tablist"]{ gap:4px!important; background:var(--panel)!important; padding:4px!important; border-radius:8px!important; border:1px solid var(--border)!important; }
[data-testid="stTabs"] [role="tab"]{ font-family:var(--mono)!important; font-size:.75rem!important; padding:.4rem .8rem!important; border-radius:6px!important; color:var(--t2)!important; border:none!important; }
[data-testid="stTabs"] [role="tab"][aria-selected="true"]{ background:var(--aglow)!important; color:var(--amber)!important; border:1px solid var(--adim)!important; }

.score-badge{ display:inline-block; background:var(--hover); border:1px solid var(--blit); border-radius:6px; padding:.3rem .8rem; font-family:var(--mono); font-size:.82rem; color:var(--t2); margin:.15rem; }
.score-badge.top1{ border-color:var(--adim); color:var(--amber); background:var(--aglow); }
.section-label{ font-family:var(--mono); font-size:.65rem; letter-spacing:.15em; text-transform:uppercase; color:var(--tm); margin-bottom:.4rem; }
.stat-chip{ display:inline-block; background:var(--hover); border:1px solid var(--border); border-radius:6px; padding:.25rem .6rem; font-family:var(--mono); font-size:.75rem; color:var(--t2); margin-right:.4rem; margin-bottom:.3rem; }
.stat-chip span{ color:var(--t1); font-weight:600; }
.muted{ color:var(--t2)!important; font-family:var(--mono); font-size:.8rem; }
.day-header{ font-family:var(--mono); font-size:.7rem; letter-spacing:.15em; text-transform:uppercase; color:var(--tm); padding:.3rem 0; border-bottom:1px solid var(--border); margin-bottom:.6rem; }
.match-row-badge{ display:inline-block; background:var(--hover); border:1px solid var(--border); border-radius:4px; padding:.1rem .4rem; font-family:var(--mono); font-size:.65rem; color:var(--t2); margin-left:.4rem; }
.value-tag{ display:inline-block; border-radius:4px; padding:.15rem .5rem; font-family:var(--mono); font-size:.65rem; font-weight:600; letter-spacing:.04em; }
.vt-elite{ background:rgba(245,166,35,.2); color:#f5a623; border:1px solid #f5a62355; }
.vt-high { background:rgba(255,71,87,.15);  color:#ff4757; border:1px solid #ff475733; }
.vt-med  { background:rgba(0,209,122,.12);  color:#00d17a; border:1px solid #00d17a33; }
.vt-low  { background:rgba(74,158,255,.12); color:#4a9eff; border:1px solid #4a9eff33; }
::-webkit-scrollbar{ width:5px; height:5px; }
::-webkit-scrollbar-track{ background:var(--bg); }
::-webkit-scrollbar-thumb{ background:var(--blit); border-radius:10px; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# PATHS
# ─────────────────────────────────────────────────────────────────────────────
BASE_DIR        = Path(__file__).parent
PORTFOLIO_PATH  = BASE_DIR / "portfolio.csv"
CONFIG_PATH     = BASE_DIR / "config.json"
WEIGHTS_PATH    = BASE_DIR / "weights.json"
RECAL_LOG_PATH  = BASE_DIR / "recalibration_log.csv"
PREDICTIONS_DIR = BASE_DIR / "predictions"

# ── UPDATED: World Cup 2026 + MLS adăugate, ordine prioritizată ──
COMPETITION_OPTIONS = [
    "World Cup 2026",
    "Premier League", "La Liga", "Serie A", "Bundesliga", "Ligue 1",
    "Champions League", "Europa League",
    "Romania SuperLiga", "MLS",
]

# ─────────────────────────────────────────────────────────────────────────────
# ENGINE SINGLETON
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_resource(show_spinner=False)
def load_engine():
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
        return df if not df.empty else None
    except Exception:
        return None

def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _save_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=4), encoding="utf-8")

def _prob_bar(label: str, prob: float, colour: str) -> str:
    pct = prob * 100
    return f"""
    <div style="display:flex;align-items:center;gap:10px;margin:5px 0;">
        <div style="width:80px;font-family:var(--mono);font-size:.75rem;color:var(--t2);text-align:right;">{label}</div>
        <div style="flex:1;background:#1e2535;border-radius:4px;height:8px;overflow:hidden;">
            <div style="width:{min(pct,100):.1f}%;background:{colour};height:100%;border-radius:4px;"></div>
        </div>
        <div style="width:52px;font-family:var(--mono);font-size:.8rem;color:{colour};font-weight:600;">{pct:.1f}%</div>
    </div>"""

def _xg_chip(label: str, val: float, home: bool) -> str:
    c = "#4a9eff" if home else "#f5a623"
    return f"""
    <div style="text-align:center;background:#141820;border:1px solid #1e2535;border-radius:8px;padding:.5rem .8rem;">
        <div style="font-family:var(--mono);font-size:.6rem;color:#8892a4;letter-spacing:.1em;text-transform:uppercase;">{label}</div>
        <div style="font-family:var(--mono);font-size:1.4rem;font-weight:600;color:{c};">{val:.3f}</div>
        <div style="font-family:var(--mono);font-size:.6rem;color:#4a5568;">xG</div>
    </div>"""

def _odds_box(label: str, odds: float, model_pct: float, edge: float) -> str:
    ec = "#00d17a" if edge > 0 else "#ff4757"
    od = f"{odds:.2f}" if odds > 1 else "N/A"
    return f"""
    <div style="background:var(--hover);border:1px solid var(--border);border-radius:8px;padding:.7rem;text-align:center;">
        <div style="font-family:var(--mono);font-size:.6rem;letter-spacing:.1em;color:var(--tm);">{label}</div>
        <div style="font-family:var(--mono);font-size:1.3rem;font-weight:600;color:var(--t1);">{od}</div>
        <div style="font-family:var(--mono);font-size:.7rem;color:var(--t2);">Model {model_pct:.1f}%</div>
        <div style="font-family:var(--mono);font-size:.75rem;color:{ec};font-weight:600;">Edge {'+' if edge>0 else ''}{edge:.1f}%</div>
    </div>"""

def _page_header(icon: str, title: str, sub: str = "") -> None:
    sub_h = f'<div style="font-family:var(--mono);font-size:.82rem;color:var(--t2);margin-top:.3rem;">{sub}</div>' if sub else ""
    st.markdown(f"""
    <div style="margin-bottom:1.8rem;">
        <div style="font-family:var(--mono);font-size:.65rem;letter-spacing:.18em;color:var(--tm);text-transform:uppercase;margin-bottom:.3rem;">Football Oracle Terminal</div>
        <div style="font-family:'IBM Plex Mono',monospace;font-size:1.6rem;font-weight:600;color:var(--amber);letter-spacing:.03em;">{icon}  {title}</div>
        {sub_h}
        <div style="height:2px;background:linear-gradient(90deg,var(--adim),transparent);margin-top:.8rem;border-radius:2px;"></div>
    </div>""", unsafe_allow_html=True)

def _vt_class(rating: str) -> str:
    r = rating.lower()
    if "elite" in r: return "vt-elite"
    if "high"  in r: return "vt-high"
    if "medium"in r: return "vt-med"
    return "vt-low"

def _render_match_card(match: dict, engine, idx: int) -> None:
    """Render one match expander with full analysis."""
    home    = match["home_team"]
    away    = match["away_team"]
    league  = match.get("league", "")
    ko_utc  = match.get("kickoff_utc", "")
    ko_time = ko_utc[11:16] if len(ko_utc) > 16 else "TBA"
    fid     = match.get("fixture_id", str(idx))
    has_odds= bool(match.get("home_odds"))
    src     = match.get("source", "")

    # Demo badge
    is_demo = str(src).startswith("demo")
    demo_tag = " 🔵DEMO" if is_demo else ""

    odds_indicator = "📊" if has_odds else "📋"
    label = f"⚽  {home}  vs  {away}  |  {league}  |  {ko_time} UTC  {odds_indicator}{demo_tag}"

    with st.expander(label, expanded=False):

        # ── Header ────────────────────────────────────────────────────────
        st.markdown(f"""
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:.5rem;">
            <div>
                <span style="font-family:var(--mono);font-size:1.05rem;font-weight:600;color:var(--t1);">{home}</span>
                <span style="font-family:var(--mono);font-size:.85rem;color:var(--tm);margin:0 .6rem;">vs</span>
                <span style="font-family:var(--mono);font-size:1.05rem;font-weight:600;color:var(--t1);">{away}</span>
            </div>
            <div style="font-family:var(--mono);font-size:.72rem;color:var(--tm);">⏱ {ko_time} UTC</div>
        </div>
        <div class="muted">🏆 {league}  ·  🔌 {src}  ·  ID: {fid}</div>
        """, unsafe_allow_html=True)

        if is_demo:
            st.info("🔵  Date demo — sursele live sunt temporar indisponibile (între sezoane). Modelul Poisson funcționează normal.")

        if not has_odds:
            st.info("ℹ️  Cote indisponibile momentan — analiza folosește doar probabilitățile modelului.")

        st.markdown('<br>', unsafe_allow_html=True)

        # ── ANALYSE button ────────────────────────────────────────────────
        btn_key = f"analyse_{fid}_{idx}"
        if st.button("🔮  ANALYSE THIS MATCH", key=btn_key, use_container_width=True):
            with st.spinner(f"Analysing {home} vs {away} …"):
                pred = engine.evaluate_match(match)

            if pred is None:
                st.error("Analysis failed — insufficient data.")
                return

            st.session_state[f"pred_{fid}"] = pred

        pred = st.session_state.get(f"pred_{fid}")
        if pred is None:
            st.markdown(
                '<div class="muted">Click \'ANALYSE THIS MATCH\' pentru a rula modelul Oracle.</div>',
                unsafe_allow_html=True,
            )
            return

        # ── xG ────────────────────────────────────────────────────────────
        st.markdown('<div class="section-label">Expected Goals (xG)</div>', unsafe_allow_html=True)
        xc1, xc2, xc3 = st.columns([2, 1, 2])
        with xc1:
            st.markdown(_xg_chip(home, pred.home_xg, True), unsafe_allow_html=True)
        with xc2:
            st.markdown('<div style="text-align:center;padding-top:.8rem;font-family:var(--mono);font-size:.9rem;color:var(--tm);">vs</div>', unsafe_allow_html=True)
        with xc3:
            st.markdown(_xg_chip(away, pred.away_xg, False), unsafe_allow_html=True)

        # Team DNA
        if pred.home_profile and pred.away_profile:
            st.markdown('<br><div class="section-label">Team DNA</div>', unsafe_allow_html=True)
            dc1, dc2 = st.columns(2)
            with dc1:
                hp = pred.home_profile
                st.markdown(
                    f'<div class="stat-chip">OFF <span>{hp.offensive_rating:.3f}</span></div>'
                    f'<div class="stat-chip">DEF <span>{hp.defensive_rating:.3f}</span></div>'
                    f'<div class="stat-chip">Form <span>{"".join(hp.form_results[-5:]) or "N/A"}</span></div>'
                    f'<div class="stat-chip">Source <span>{hp.data_source}</span></div>',
                    unsafe_allow_html=True,
                )
            with dc2:
                ap = pred.away_profile
                st.markdown(
                    f'<div class="stat-chip">OFF <span>{ap.offensive_rating:.3f}</span></div>'
                    f'<div class="stat-chip">DEF <span>{ap.defensive_rating:.3f}</span></div>'
                    f'<div class="stat-chip">Form <span>{"".join(ap.form_results[-5:]) or "N/A"}</span></div>'
                    f'<div class="stat-chip">Source <span>{ap.data_source}</span></div>',
                    unsafe_allow_html=True,
                )

        st.markdown('<br>', unsafe_allow_html=True)

        # ── Probabilities ─────────────────────────────────────────────────
        st.markdown('<div class="section-label">Poisson Probability Model</div>', unsafe_allow_html=True)
        st.markdown(
            _prob_bar("Home Win", pred.prob_home_win, "#4a9eff")
            + _prob_bar("Draw",    pred.prob_draw,     "#f5a623")
            + _prob_bar("Away Win",pred.prob_away_win, "#ff4757"),
            unsafe_allow_html=True,
        )

        # ── Top scores ────────────────────────────────────────────────────
        st.markdown('<br><div class="section-label">Top Predicted Scorelines</div>', unsafe_allow_html=True)
        sc_html = "".join(
            f'<span class="score-badge {"top1" if i==0 else ""}">{hg}-{ag} <small>({p:.1f}%)</small></span>'
            for i, (hg, ag, p) in enumerate(pred.top_scores[:6])
        )
        st.markdown(sc_html, unsafe_allow_html=True)

        st.markdown('<br>', unsafe_allow_html=True)

        # ── Odds & Edge ───────────────────────────────────────────────────
        st.markdown(f'<div class="section-label">Bookmaker Odds — {pred.bookmaker_name}</div>', unsafe_allow_html=True)
        oc1, oc2, oc3 = st.columns(3)
        with oc1: st.markdown(_odds_box("HOME WIN",  pred.bk_home_odds, pred.prob_home_win*100, pred.edge_home_pct), unsafe_allow_html=True)
        with oc2: st.markdown(_odds_box("DRAW",      pred.bk_draw_odds, pred.prob_draw*100,     pred.edge_draw_pct), unsafe_allow_html=True)
        with oc3: st.markdown(_odds_box("AWAY WIN",  pred.bk_away_odds, pred.prob_away_win*100, pred.edge_away_pct), unsafe_allow_html=True)

        # ── Weather ───────────────────────────────────────────────────────
        if pred.weather_penalty > 0:
            st.warning(pred.weather_note)
        else:
            st.markdown(f'<div class="muted" style="margin-top:.6rem;">{pred.weather_note}</div>', unsafe_allow_html=True)

        st.markdown('<br>', unsafe_allow_html=True)

        # ── Value Bets ────────────────────────────────────────────────────
        if pred.value_bets:
            st.markdown('<div class="section-label">🎯 Value Bets Detected</div>', unsafe_allow_html=True)
            for vb in pred.value_bets:
                sel   = vb["selection"]
                edge  = vb["edge_pct"]
                rat   = vb["rating"]
                bkod  = vb["bk_odds"]
                modp  = vb["model_prob_pct"]
                kelly = pred.kelly_stakes.get(sel, 0.0)

                vc1, vc2 = st.columns([3, 1])
                with vc1:
                    st.success(
                        f'**{rat}**  {sel}  @  **{bkod:.2f}**  |  '
                        f'Edge: **+{edge:.1f}%**  |  Model: {modp:.1f}%  |  '
                        f'Kelly: **€{kelly:.2f}**'
                    )
                with vc2:
                    if st.button("📌 Log", key=f"log_{fid}_{sel.replace(' ','_')}"):
                        engine.log_bet(
                            fixture_id = str(fid),
                            match_name = f"{home} vs {away}",
                            market     = "1X2",
                            selection  = sel,
                            odds       = bkod,
                            stake      = kelly if kelly > 0 else float(engine.config.get("stake_default",10)),
                            result     = "",
                        )
                        st.toast(f"✅ Logged: {sel} @ {bkod:.2f}", icon="📌")
        else:
            st.info("No value bets above threshold.")

        st.markdown("---")


# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(
        '<div style="font-family:var(--mono);font-size:1.1rem;font-weight:600;color:var(--amber);letter-spacing:.08em;">⚡ FOOTBALL ORACLE</div>'
        '<div style="font-family:var(--mono);font-size:.65rem;color:var(--tm);letter-spacing:.12em;text-transform:uppercase;">Hybrid Intelligence Terminal v2.0</div>',
        unsafe_allow_html=True,
    )
    st.markdown('<hr style="border-color:#1e2535;margin:1rem 0;">', unsafe_allow_html=True)

    nav = st.radio("NAV", [
        "⚽  Meciuri Săptămână",
        "📊  Portfolio & Analytics",
        "⚙️  Model Calibration",
    ], label_visibility="collapsed")

    st.markdown('<hr style="border-color:#1e2535;margin:1rem 0;">', unsafe_allow_html=True)

    st.markdown('<div style="font-family:var(--mono);font-size:.7rem;color:var(--tm);letter-spacing:.1em;text-transform:uppercase;margin-bottom:.4rem;">LIGI ACTIVE</div>', unsafe_allow_html=True)
    selected_comps = st.multiselect(
        "Competitions",
        COMPETITION_OPTIONS,
        # ── UPDATED: World Cup 2026 + MLS ca default (sezoane active acum) ──
        default=["World Cup 2026", "Romania SuperLiga", "MLS"],
        label_visibility="collapsed",
    )

    st.markdown('<hr style="border-color:#1e2535;margin:1rem 0;">', unsafe_allow_html=True)

    now = datetime.now(timezone.utc)
    st.markdown(
        f'<div style="font-family:var(--mono);font-size:.7rem;color:var(--tm);">UTC {now.strftime("%Y-%m-%d")}<br>'
        f'<span style="font-size:1rem;color:var(--amber);font-weight:600;">{now.strftime("%H:%M:%S")}</span></div>',
        unsafe_allow_html=True,
    )
    st.markdown('<hr style="border-color:#1e2535;margin:1rem 0;">', unsafe_allow_html=True)

    engine_obj = load_engine()
    if isinstance(engine_obj, str):
        st.error(f"Engine error: {engine_obj}")
        engine = None
    else:
        engine = engine_obj
        st.markdown(
            '<div style="font-family:var(--mono);font-size:.7rem;">'
            '<span style="color:#00d17a;">●</span> Engine <span style="color:#00d17a;">ONLINE</span></div>',
            unsafe_allow_html=True,
        )
        # ── UPDATED: surse actuale v2.0 ──
        st.markdown(
            '<div style="font-family:var(--mono);font-size:.65rem;color:var(--tm);margin-top:.5rem;">'
            '🌍 The Odds API (WC 2026)<br>🔗 football-data.org<br>📺 ESPN public API<br>🔗 TheSportsDB<br>🔵 Demo mode<br>🌤 WeatherAPI</div>',
            unsafe_allow_html=True,
        )

    st.markdown('<br>', unsafe_allow_html=True)

    if engine and st.button("🔄  Clear Cache", use_container_width=True):
        engine.api.clear_cache()
        st.cache_resource.clear()
        st.toast("Cache cleared!", icon="🔄")


# ═════════════════════════════════════════════════════════════════════════════
# VIEW 1 — MECIURI SĂPTĂMÂNĂ
# ═════════════════════════════════════════════════════════════════════════════

if nav == "⚽  Meciuri Săptămână":
    _page_header(
        "⚽", "MECIURI SĂPTĂMÂNĂ",
        "World Cup 2026 · Cote reale · Analiză Poisson · Value Bets"
    )

    if not engine:
        st.error("Engine offline. Verifică oracle_engine.py și oracle_api.py.")
        st.stop()

    # ── Load matches ──────────────────────────────────────────────────────
    load_key = "week_matches"
    if load_key not in st.session_state or st.session_state.get("force_reload"):
        with st.spinner("📡  Fetching meciuri (toate sursele) …"):
            all_matches = engine.get_week_matches(
                days_ahead=7, competitions=selected_comps or None
            )
        st.session_state[load_key] = all_matches
        st.session_state["force_reload"] = False
    else:
        all_matches = st.session_state[load_key]

    if not all_matches:
        st.warning(
            "⚠️  Nu s-au găsit meciuri. Încearcă să selectezi **World Cup 2026** sau **MLS** din sidebar — "
            "acestea sunt ligile active în iunie 2026."
        )
        col_rl, _ = st.columns([1, 3])
        with col_rl:
            if st.button("🔄  Reload Data"):
                st.session_state["force_reload"] = True
                st.rerun()
        st.stop()

    # ── Demo mode banner ──────────────────────────────────────────────────
    demo_count = sum(1 for m in all_matches if str(m.get("source","")).startswith("demo"))
    live_count = len(all_matches) - demo_count
    if demo_count > 0:
        st.info(
            f"🔵  **{demo_count} meciuri demo** + **{live_count} meciuri live**  ·  "
            f"Ligile europene sunt între sezoane (iunie). "
            f"Modelul Poisson funcționează normal pe toate meciurile."
        )

    # ── Build date tabs ───────────────────────────────────────────────────
    today      = date.today()
    date_range = [(today + timedelta(days=i)) for i in range(7)]

    tab_labels = []
    for d in date_range:
        cnt = sum(1 for m in all_matches if m.get("kickoff_date","") == d.isoformat())
        if d == today:
            tab_labels.append(f"🔴 Azi ({cnt})")
        elif d == today + timedelta(days=1):
            tab_labels.append(f"Mâine ({cnt})")
        else:
            tab_labels.append(f"{d.strftime('%a %d/%m')} ({cnt})")

    tabs = st.tabs(tab_labels)

    for tab, target_date in zip(tabs, date_range):
        with tab:
            day_matches = [
                m for m in all_matches
                if m.get("kickoff_date","") == target_date.isoformat()
            ]

            if not day_matches:
                st.markdown(
                    f'<div class="muted" style="padding:1rem 0;">Nu există meciuri programate pentru {target_date.strftime("%A, %d %B %Y")}.</div>',
                    unsafe_allow_html=True,
                )
                continue

            leagues_in_day: dict[str, list[dict]] = {}
            for m in day_matches:
                lg = m.get("league", "Other")
                leagues_in_day.setdefault(lg, []).append(m)

            for lg, lg_matches in sorted(leagues_in_day.items()):
                st.markdown(
                    f'<div class="day-header">🏆 {lg}  ·  {len(lg_matches)} meci(uri)</div>',
                    unsafe_allow_html=True,
                )
                for i, match in enumerate(
                    sorted(lg_matches, key=lambda x: x.get("kickoff_utc",""))
                ):
                    _render_match_card(match, engine, idx=hash(match["fixture_id"]))

    st.markdown('<br>', unsafe_allow_html=True)
    col_rl, _ = st.columns([1, 3])
    with col_rl:
        if st.button("🔄  Reload All Matches", use_container_width=True):
            st.session_state["force_reload"] = True
            st.rerun()


# ═════════════════════════════════════════════════════════════════════════════
# VIEW 2 — PORTFOLIO & ANALYTICS
# ═════════════════════════════════════════════════════════════════════════════

elif nav == "📊  Portfolio & Analytics":
    _page_header("📊", "PORTFOLIO & ANALYTICS", "Track bets · P&L · Auto-recalibration")

    df = _load_portfolio()

    if df is not None and not df.empty:
        settled  = df[df["Result"].isin(["W","L"])]
        total    = len(settled)
        wins     = len(settled[settled["Result"]=="W"])
        wr       = wins/total*100 if total>0 else 0
        staked   = settled["Stake"].sum() if total>0 else 0
        pnl      = settled["PnL"].sum()   if total>0 else 0
        roi      = pnl/staked*100         if staked>0 else 0
        pending  = len(df[df["Result"]=="PENDING"])

        m1,m2,m3,m4,m5 = st.columns(5)
        m1.metric("SETTLED BETS", total)
        m2.metric("WIN RATE",    f"{wr:.1f}%")
        m3.metric("STAKED",      f"€{staked:.2f}")
        m4.metric("NET P&L",     f"€{pnl:+.2f}", delta=f"{roi:+.1f}% ROI")
        m5.metric("PENDING",     pending)

        if total >= 2:
            st.markdown("#### BANKROLL CURVE")
            sc = settled.copy().reset_index(drop=True)
            sc["Cumul PnL"] = sc["PnL"].cumsum()
            sc["Bet #"]     = sc.index + 1
            st.line_chart(sc.set_index("Bet #")[["Cumul PnL"]], color="#f5a623", height=200)

        st.markdown("#### FULL BET HISTORY")
        def _sr(v):
            if v=="W": return "color:#00d17a;font-weight:700"
            if v=="L": return "color:#ff4757;font-weight:700"
            if v=="PENDING": return "color:#f5a623"
            return ""
        def _sp(v):
            if isinstance(v,(int,float)): return "color:#00d17a" if v>0 else ("color:#ff4757" if v<0 else "")
            return ""
        try:
            styled = (
                df.style.applymap(_sr, subset=["Result"]).applymap(_sp, subset=["PnL"])
                .format({"Odds":"{:.2f}","Stake":"€{:.2f}","PnL":"€{:+.2f}"})
            )
            st.dataframe(styled, use_container_width=True, height=300)
        except Exception:
            st.dataframe(df, use_container_width=True, height=300)
    else:
        st.info("📭  Nu există pariuri înregistrate. Rulează Oracle și logează primul pariu.")

    # ── Manual entry ──────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### ✏️  MANUAL BET ENTRY")
    with st.form("manual_form"):
        fc1,fc2,fc3 = st.columns(3)
        with fc1:
            mb_m  = st.text_input("Meci", placeholder="Argentina vs Croatia")
            mb_mk = st.selectbox("Market", ["1X2","BTTS","Over 2.5","Handicap","Other"])
        with fc2:
            mb_s  = st.text_input("Selecție", placeholder="Home Win")
            mb_o  = st.number_input("Cotă", min_value=1.01, max_value=100.0, value=2.00, step=0.05)
        with fc3:
            mb_st = st.number_input("Miză (€)", min_value=0.1, value=10.0, step=0.5)
            mb_r  = st.selectbox("Rezultat", ["PENDING","W","L","V"])
            mb_fi = st.text_input("Fixture ID (opțional)", value="manual")
        if st.form_submit_button("📌  LOG BET", use_container_width=True):
            if mb_m and mb_s and engine:
                engine.log_bet(mb_fi or "manual", mb_m, mb_mk, mb_s, mb_o, mb_st,
                               "" if mb_r=="PENDING" else mb_r)
                st.success(f"✅  Logat: {mb_m} | {mb_s} @ {mb_o:.2f}")
                st.rerun()

    # ── Update pending + Recalibration ────────────────────────────────────
    pending_df = None
    if df is not None:
        pending_df = df[df["Result"]=="PENDING"]

    if pending_df is not None and not pending_df.empty:
        st.markdown("---")
        st.markdown("#### 🔄  UPDATE PENDING  +  🧠 AUTO-RECALIBRATION")

        st.dataframe(
            pending_df[["Date","Match","Selection","Odds","Stake","FixtureID"]],
            use_container_width=True
        )

        with st.form("update_form"):
            row_idx = st.selectbox(
                "Selecție pariu",
                pending_df.index.tolist(),
                format_func=lambda i: f"#{i}  {pending_df.loc[i,'Match']}  —  {pending_df.loc[i,'Selection']}"
            )
            new_res = st.selectbox("Rezultat nou", ["W","L","V"])
            st.markdown("**🧠 Recalibrare automată**")
            rc1,rc2,rc3 = st.columns([1,1,2])
            with rc1: ah = st.number_input("Goluri Acasă", 0, 20, 0, 1)
            with rc2: aa = st.number_input("Goluri Deplasare", 0, 20, 0, 1)
            with rc3: do_rc = st.checkbox("Rulează recalibrarea", value=True)

            if st.form_submit_button("✅  UPDATE", use_container_width=True):
                full = pd.read_csv(PORTFOLIO_PATH)
                ov   = float(full.loc[row_idx,"Odds"])
                sv   = float(full.loc[row_idx,"Stake"])
                fid  = str(full.loc[row_idx,"FixtureID"])
                pnl_v = round(sv*(ov-1),2) if new_res=="W" else (-round(sv,2) if new_res=="L" else 0.0)
                full.at[row_idx,"Result"] = new_res
                full.at[row_idx,"PnL"]    = pnl_v
                full.to_csv(PORTFOLIO_PATH, index=False)
                st.success(f"✅  Row #{row_idx} → {new_res}  PnL=€{pnl_v:+.2f}")

                if do_rc and engine and fid and fid != "manual":
                    with st.spinner("🧠  Recalibrare …"):
                        rc_res = engine.update_weights_from_result(fid, int(ah), int(aa))
                    status = rc_res.get("status","error")
                    if status == "stable":
                        st.info(f"🟢  Model precis (eroare={rc_res.get('combined_error','?'):.3f}) — fără ajustări.")
                    elif status == "recalibrated":
                        st.success(f"🧠  Recalibrat!  Eroare combinată: {rc_res['combined_error']:.3f}")
                        st.caption(rc_res.get("reason",""))
                        if rc_res.get("adjustments"):
                            adj = pd.DataFrame([
                                {"Weight":k,"Old":v["old"],"Delta":f"{v['delta']:+.4f}","New":v["new"]}
                                for k,v in rc_res["adjustments"].items()
                            ])
                            st.dataframe(adj, use_container_width=True, hide_index=True)
                    else:
                        st.warning(rc_res.get("message","Prediction cache nu există."))
                st.rerun()

    if RECAL_LOG_PATH.exists():
        st.markdown("---")
        st.markdown("#### 🧠  RECALIBRATION HISTORY")
        rc_df = pd.read_csv(RECAL_LOG_PATH)
        st.dataframe(rc_df.tail(15), use_container_width=True)


# ═════════════════════════════════════════════════════════════════════════════
# VIEW 3 — MODEL CALIBRATION
# ═════════════════════════════════════════════════════════════════════════════

elif nav == "⚙️  Model Calibration":
    _page_header("⚙️", "MODEL CALIBRATION", "Weights · Config · Diagnostice")

    if not engine:
        st.error("Engine offline.")
        st.stop()

    t1, t2, t3, t4 = st.tabs(["🎛  Weights", "⚡  Config", "🧠  League Learning", "🔍  Diagnostics"])

    with t1:
        st.markdown("#### MODEL WEIGHTS  (`weights.json`)")
        w = _load_json(WEIGHTS_PATH)
        if not w:
            st.warning("weights.json lipsă. Rulează engine-ul odată pentru a-l genera.")
        else:
            with st.form("w_form"):
                wc1, wc2 = st.columns(2)
                with wc1:
                    st.markdown("**Form & DNA**")
                    nfw  = st.slider("form_weight",  .05,.95, float(w.get("form_weight",.60)), .05)
                    ndw  = st.slider("dna_weight",   .05,.95, float(w.get("dna_weight", .40)), .05)
                    st.markdown("**Offensive Rating**")
                    ngw  = st.slider("goals_weight",     .05,.80, float(w.get("goals_weight",.45)),     .05)
                    nsow = st.slider("shots_ot_weight",  .05,.60, float(w.get("shots_ot_weight",.30)),  .05)
                    npw  = st.slider("possession_weight",.05,.50, float(w.get("possession_weight",.25)),.05)
                with wc2:
                    st.markdown("**Adjustments**")
                    nha  = st.slider("home_advantage", 1.00, 1.20, float(w.get("home_advantage",1.07)), .01)
                    nap  = st.slider("away_penalty",   0.80, 1.00, float(w.get("away_penalty",  0.95)), .01)
                    st.markdown("**League Baselines (xG/team)**")
                    bl   = w.get("league_baselines", {})
                    nbl  = {}
                    for lg in ["World Cup 2026","Premier League","La Liga","Serie A","Bundesliga",
                               "Ligue 1","Champions League","Romania SuperLiga","MLS"]:
                        nbl[lg] = st.number_input(lg, .5, 2.5, float(bl.get(lg, bl.get("default",1.25))), .05, key=f"bl_{lg}")
                    nbl["default"] = float(bl.get("default",1.25))

                if st.form_submit_button("💾  SAVE WEIGHTS", use_container_width=True):
                    w.update({
                        "form_weight":       nfw,
                        "dna_weight":        ndw,
                        "goals_weight":      ngw,
                        "shots_ot_weight":   nsow,
                        "possession_weight": npw,
                        "home_advantage":    nha,
                        "away_penalty":      nap,
                        "league_baselines":  nbl,
                    })
                    _save_json(WEIGHTS_PATH, w)
                    engine.weights = w
                    st.success("✅  Salvat și reîncărcat.")

            with st.expander("📄  Raw JSON"):
                st.code(json.dumps(_load_json(WEIGHTS_PATH), indent=4), language="json")

    with t2:
        st.markdown("#### ENGINE CONFIG  (`config.json`)")
        cfg = _load_json(CONFIG_PATH)
        if not cfg:
            st.warning("config.json lipsă.")
        else:
            with st.form("cfg_form"):
                cc1,cc2 = st.columns(2)
                with cc1:
                    nt  = st.number_input("value_bet_threshold_pct", 1.0,30.0, float(cfg.get("value_bet_threshold_pct",5.0)), .5)
                    nmg = st.number_input("max_goals_poisson",        5,15,     int(cfg.get("max_goals_poisson",8)),           1)
                    nln = st.number_input("last_n_fixtures",          3,10,     int(cfg.get("last_n_fixtures",5)),             1)
                with cc2:
                    nsd = st.number_input("stake_default (€)", 1.0,1000.0, float(cfg.get("stake_default",10.0)),  1.0)
                    nkf = st.slider("kelly_fraction",     .05,1.0,  float(cfg.get("kelly_fraction",.25)),           .05)
                    nlr = st.slider("learning_rate",      .01,.20,  float(cfg.get("recalibration_learning_rate",.05)),.01)
                    nmd = st.slider("max_delta",          .05,.30,  float(cfg.get("recalibration_max_delta",.15)),   .01)
                if st.form_submit_button("💾  SAVE CONFIG", use_container_width=True):
                    cfg.update({
                        "value_bet_threshold_pct":    round(nt,1),
                        "max_goals_poisson":          int(nmg),
                        "last_n_fixtures":            int(nln),
                        "stake_default":              round(nsd,2),
                        "kelly_fraction":             round(nkf,2),
                        "recalibration_learning_rate":round(nlr,3),
                        "recalibration_max_delta":    round(nmd,3),
                    })
                    _save_json(CONFIG_PATH, cfg)
                    engine.config = cfg
                    st.success("✅  Salvat.")
            with st.expander("📄  Raw JSON"):
                st.code(json.dumps(_load_json(CONFIG_PATH), indent=4), language="json")

    with t3:
        st.markdown("#### 🧠  LEAGUE LEARNING STATUS")
        st.caption("Fiecare ligă își calibrează propriii parametri independent.")

        if engine:
            league_df = engine.get_league_learning_stats()
            if not league_df.empty:
                def _conf_colour(val):
                    pct = int(val.replace("%",""))
                    if pct >= 80: return "color:#00d17a;font-weight:700"
                    if pct >= 40: return "color:#f5a623;font-weight:600"
                    return "color:#ff4757"
                def _delta_colour(val):
                    if isinstance(val, float):
                        return "color:#00d17a" if val > 0 else ("color:#ff4757" if val < 0 else "")
                    return ""
                try:
                    styled_df = (
                        league_df.style
                        .applymap(_conf_colour, subset=["Confidence"])
                        .applymap(_delta_colour, subset=["Δ form_w","Δ goals_w","Δ home_adv"])
                        .format({"Δ form_w":"{:+.4f}","Δ goals_w":"{:+.4f}","Δ home_adv":"{:+.4f}"})
                    )
                    st.dataframe(styled_df, use_container_width=True, hide_index=True)
                except Exception:
                    st.dataframe(league_df, use_container_width=True, hide_index=True)

                if league_df["Samples"].sum() > 0:
                    st.markdown("#### Samples per League")
                    chart_df = league_df.set_index("League")[["Samples"]]
                    st.bar_chart(chart_df, color="#f5a623", height=180)

                st.markdown("""
**Interpretare:**
- **Confidence 0-40%** → pesi globali dominanti (puține date)
- **Confidence 40-80%** → blend global + ligă
- **Confidence 80-100%** → liga și-a calibrat propriile pattern-uri
- **Δ home_adv > 0** → avantajul acasă e mai mare decât media în această ligă
- **Δ goals_w > 0** → golurile sunt un predictor mai puternic decât media
                """)
            else:
                st.info("📭  Nu există date de calibrare per ligă încă. Introdu rezultate reale din Portfolio.")
        else:
            st.error("Engine offline.")

    with t4:
        st.markdown("#### 🔍  DIAGNOSTICS")
        d1,d2,d3,d4 = st.columns(4)
        with d1:
            p = _load_portfolio()
            st.markdown(f'<div class="stat-chip">portfolio.csv <span>{len(p) if p is not None else 0} rows</span></div>', unsafe_allow_html=True)
        with d2:
            pc = len(list(PREDICTIONS_DIR.glob("*.json"))) if PREDICTIONS_DIR.exists() else 0
            st.markdown(f'<div class="stat-chip">Cached preds <span>{pc}</span></div>', unsafe_allow_html=True)
        with d3:
            for fn in ["config.json","weights.json","recalibration_log.csv"]:
                ok = (BASE_DIR/fn).exists()
                st.markdown(f'<div class="stat-chip">{fn} <span>{"✅" if ok else "❌"}</span></div>', unsafe_allow_html=True)
        with d4:
            st.markdown(f'<div class="stat-chip">Engine <span>{"✅ ONLINE" if engine else "❌"}</span></div>', unsafe_allow_html=True)
            st.markdown(f'<div class="stat-chip">Python <span>{sys.version[:6]}</span></div>', unsafe_allow_html=True)

        st.markdown("---")
        st.markdown("#### 📡  DATA SOURCES STATUS v2.0")
        st.markdown("""
| Sursă | Rol | Status |
|---|---|---|
| The Odds API /events | Meciuri + WC 2026 | 0 credite · activ |
| The Odds API /odds | Cote H/D/A | 500 req/lună · cache 4h |
| football-data.org | Ligi majore | 10 req/min · gratuit |
| ESPN public API | WC 2026 + ligi | Fără cheie · activ |
| TheSportsDB | Fallback general | Gratuit · activ |
| Demo mode | Între sezoane | Automat când < 3 meciuri |
| WeatherAPI | Penalizare xG meteo | Gratuit · activ |
""")
        st.markdown("---")
        st.markdown("#### 🔑  API KEYS")
        st.code("""
The Odds API       : b0e2ab9bcda1d9f4c5ddfe1063c81cd7
football-data.org  : 3934542be32c47f88a194f9eec0f44a1
WeatherAPI         : 48a5b54b8ced45cc924153231263005
ESPN               : (no key needed)
TheSportsDB        : (no key needed)
        """, language="text")

        # ── Dead keys info ────────────────────────────────────────────────
        if engine and hasattr(engine.api, '_dead_keys') and engine.api._dead_keys:
            st.markdown("#### ⚠️  Sport Keys offline această sesiune")
            st.markdown(
                " · ".join(f"`{k}`" for k in engine.api._dead_keys) +
                "\n\n*Acestea returnează 404 (sezon terminat). Se reactivează automat la Clear Cache.*"
            )
