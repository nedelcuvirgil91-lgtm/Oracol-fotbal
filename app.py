"""
================================================================================
FOOTBALL ORACLE — v3.0  |  Sport Dashboard UI
================================================================================
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

import supabase_client as sb

st.set_page_config(
    page_title="Football Oracle",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=Oswald:wght@400;500;600;700&display=swap');
:root {
    --bg:#0d0f14; --surface:#13161d; --card:#181c25; --border:#252a36; --blit:#2e3545;
    --accent:#00c2ff; --accent2:#ff3d57; --accent3:#00e676; --amber:#ffb300;
    --t1:#f0f2f7; --t2:#8892a4; --t3:#4a5568;
    --inter:'Inter',sans-serif; --oswald:'Oswald',sans-serif;
}
*,*::before,*::after{box-sizing:border-box;}
html,body,[class*="css"]{background:var(--bg)!important;color:var(--t1)!important;font-family:var(--inter)!important;}
#MainMenu,footer,header,[data-testid="stToolbar"],[data-testid="collapsedControl"]{visibility:hidden!important;}
.block-container{padding:0!important;max-width:100%!important;}
section[data-testid="stSidebar"]{display:none!important;}
.topbar{display:flex;align-items:center;justify-content:space-between;background:var(--surface);border-bottom:2px solid var(--accent);padding:.6rem 1.5rem;position:sticky;top:0;z-index:100;}
.topbar-logo{font-family:var(--oswald);font-size:1.4rem;font-weight:700;color:var(--accent);letter-spacing:.06em;text-transform:uppercase;}
.topbar-sub{font-family:var(--inter);font-size:.65rem;color:var(--t3);letter-spacing:.12em;text-transform:uppercase;}
.topbar-time{font-family:var(--oswald);font-size:1rem;color:var(--t2);}
.section-bar{display:flex;align-items:center;gap:.75rem;background:var(--surface);border-bottom:1px solid var(--border);padding:.5rem 1.5rem;}
.section-bar-title{font-family:var(--oswald);font-size:1rem;font-weight:600;color:var(--t1);letter-spacing:.05em;text-transform:uppercase;}
.section-bar-pill{background:var(--accent);color:#000;font-size:.6rem;font-weight:700;padding:.15rem .5rem;border-radius:20px;letter-spacing:.06em;}
.comp-card{background:var(--card);border:1.5px solid var(--border);border-radius:10px;padding:.9rem .6rem;text-align:center;transition:all .18s ease;}
.comp-card.active{border-color:var(--accent);background:rgba(0,194,255,.08);box-shadow:0 0 0 1px var(--accent),0 4px 16px rgba(0,194,255,.2);}
.comp-icon{font-size:1.6rem;margin-bottom:.3rem;}
.comp-name{font-family:var(--oswald);font-size:.72rem;font-weight:500;color:var(--t1);letter-spacing:.04em;text-transform:uppercase;line-height:1.2;}
.comp-count{font-size:.6rem;color:var(--t2);margin-top:.2rem;}
[data-testid="stTabs"] [role="tablist"]{background:var(--surface)!important;border-bottom:1px solid var(--border)!important;border-radius:0!important;padding:0 1.5rem!important;gap:0!important;}
[data-testid="stTabs"] [role="tab"]{font-family:var(--oswald)!important;font-size:.8rem!important;font-weight:500!important;letter-spacing:.05em!important;color:var(--t2)!important;padding:.65rem 1rem!important;border:none!important;border-bottom:3px solid transparent!important;border-radius:0!important;background:transparent!important;}
[data-testid="stTabs"] [role="tab"][aria-selected="true"]{color:var(--accent)!important;border-bottom-color:var(--accent)!important;background:transparent!important;}
.match-row{display:flex;align-items:center;background:var(--card);border:1px solid var(--border);border-radius:8px;margin:.35rem 1.5rem;padding:.65rem 1rem;gap:.75rem;}
.match-time{font-family:var(--oswald);font-size:.85rem;color:var(--t2);min-width:44px;text-align:center;}
.match-teams{flex:1;}
.match-home{font-family:var(--inter);font-size:.88rem;font-weight:600;color:var(--t1);line-height:1.5;}
.match-away{font-family:var(--inter);font-size:.82rem;font-weight:400;color:var(--t2);}
.match-odds{display:flex;gap:.3rem;}
.odd-pill{font-family:var(--oswald);font-size:.78rem;font-weight:600;padding:.22rem .45rem;border-radius:5px;background:var(--surface);border:1px solid var(--border);min-width:38px;text-align:center;}
.odd-pill.home{color:#4a9eff;} .odd-pill.draw{color:var(--amber);} .odd-pill.away{color:var(--accent2);}
.match-src{font-size:.58rem;color:var(--t3);text-transform:uppercase;letter-spacing:.06em;}
.prob-row{display:flex;align-items:center;gap:.75rem;margin:.3rem 0;}
.prob-label{font-size:.72rem;color:var(--t2);min-width:90px;text-align:right;}
.prob-bar-outer{flex:1;background:var(--border);border-radius:3px;height:6px;overflow:hidden;}
.prob-bar-inner{height:100%;border-radius:3px;}
.prob-pct{font-family:var(--oswald);font-size:.8rem;font-weight:600;min-width:44px;text-align:right;}
.odds-grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:.5rem;}
.odds-cell{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:.6rem .5rem;text-align:center;}
.odds-cell-label{font-size:.58rem;color:var(--t3);text-transform:uppercase;letter-spacing:.08em;margin-bottom:.15rem;}
.odds-cell-val{font-family:var(--oswald);font-size:1.35rem;font-weight:700;color:var(--t1);}
.odds-cell-model{font-size:.62rem;color:var(--t2);margin-top:.1rem;}
.odds-cell-edge{font-family:var(--oswald);font-size:.72rem;font-weight:600;margin-top:.12rem;}
.edge-pos{color:var(--accent3);} .edge-neg{color:var(--accent2);}
.vbet{display:flex;align-items:center;justify-content:space-between;background:rgba(0,230,118,.07);border:1px solid rgba(0,230,118,.25);border-radius:8px;padding:.6rem 1rem;margin:.35rem 0;}
.vbet-sel{font-family:var(--oswald);font-size:.88rem;font-weight:600;color:var(--accent3);}
.vbet-detail{font-size:.7rem;color:var(--t2);margin-top:.08rem;}
.vbet-edge{font-family:var(--oswald);font-size:1.1rem;font-weight:700;color:var(--accent3);}
.score-chip{font-family:var(--oswald);font-size:.76rem;padding:.22rem .55rem;border-radius:5px;border:1px solid var(--border);background:var(--card);color:var(--t2);display:inline-block;margin:.15rem;}
.score-chip.top{border-color:var(--amber);color:var(--amber);background:rgba(255,179,0,.08);}
.dna-grid{display:grid;grid-template-columns:1fr 1fr;gap:.5rem;}
.dna-box{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:.6rem .8rem;}
.dna-box-title{font-size:.62rem;color:var(--t3);text-transform:uppercase;letter-spacing:.1em;margin-bottom:.35rem;}
.dna-stat{display:flex;justify-content:space-between;font-size:.74rem;margin:.12rem 0;}
.dna-stat-k{color:var(--t2);} .dna-stat-v{color:var(--t1);font-weight:600;font-family:var(--oswald);}
.dq-live{color:var(--accent3);font-size:.63rem;} .dq-elo{color:var(--amber);font-size:.63rem;} .dq-neutral{color:var(--accent2);font-size:.63rem;}
.xg-block{display:flex;align-items:center;justify-content:space-evenly;padding:.5rem 1.5rem 0;}
.xg-team{text-align:center;}
.xg-label{font-size:.62rem;color:var(--t2);text-transform:uppercase;letter-spacing:.1em;margin-bottom:.2rem;}
.xg-val{font-family:var(--oswald);font-size:2.2rem;font-weight:700;line-height:1;}
.xg-val.home{color:#4a9eff;} .xg-val.away{color:var(--amber);}
.xg-vs{font-family:var(--oswald);font-size:1rem;color:var(--t3);}
.sub-label{font-size:.6rem;color:var(--t3);text-transform:uppercase;letter-spacing:.12em;display:block;padding:0 1.5rem;margin:.6rem 0 .25rem;}
.stButton>button{font-family:var(--oswald)!important;font-size:.82rem!important;font-weight:600!important;letter-spacing:.06em!important;text-transform:uppercase!important;border-radius:6px!important;border:1.5px solid var(--accent)!important;background:rgba(0,194,255,.08)!important;color:var(--accent)!important;transition:all .18s!important;}
.stButton>button:hover{background:rgba(0,194,255,.18)!important;box-shadow:0 0 16px rgba(0,194,255,.25)!important;}
[data-testid="stMetric"]{background:var(--card)!important;border:1px solid var(--border)!important;border-radius:8px!important;padding:.75rem 1rem!important;}
[data-testid="stMetricValue"]{font-family:var(--oswald)!important;font-size:1.5rem!important;font-weight:700!important;color:var(--accent)!important;}
[data-testid="stMetricLabel"]{font-family:var(--inter)!important;font-size:.62rem!important;color:var(--t2)!important;text-transform:uppercase!important;letter-spacing:.08em!important;}
.stAlert{border-radius:6px!important;font-family:var(--inter)!important;font-size:.8rem!important;}
::-webkit-scrollbar{width:4px;height:4px;} ::-webkit-scrollbar-track{background:var(--bg);} ::-webkit-scrollbar-thumb{background:var(--blit);border-radius:10px;}
</style>
""", unsafe_allow_html=True)

BASE_DIR       = Path(__file__).parent
PORTFOLIO_PATH = BASE_DIR / "portfolio.csv"
CONFIG_PATH    = BASE_DIR / "config.json"
WEIGHTS_PATH   = BASE_DIR / "weights.json"
RECAL_LOG_PATH = BASE_DIR / "recalibration_log.csv"
PREDICTIONS_DIR= BASE_DIR / "predictions"

COMPETITIONS_META = [
    {"key":"World Cup 2026",    "icon":"🏆","label":"World Cup",       "color":"#ffb300"},
    {"key":"Champions League",  "icon":"⭐","label":"UCL",             "color":"#00c2ff"},
    {"key":"Premier League",    "icon":"🏴","label":"Premier League", "color":"#9b59b6"},
    {"key":"La Liga",           "icon":"🇪🇸","label":"La Liga",         "color":"#e74c3c"},
    {"key":"Serie A",           "icon":"🇮🇹","label":"Serie A",         "color":"#2ecc71"},
    {"key":"Bundesliga",        "icon":"🇩🇪","label":"Bundesliga",      "color":"#e67e22"},
    {"key":"Ligue 1",           "icon":"🇫🇷","label":"Ligue 1",         "color":"#3498db"},
    {"key":"Europa League",     "icon":"🟠","label":"Europa League",   "color":"#e67e22"},
    {"key":"Romania SuperLiga", "icon":"🇷🇴","label":"SuperLiga",       "color":"#e74c3c"},
]

@st.cache_resource(show_spinner=False)
def load_engine():
    try:
        from oracle_engine import FootballOracleEngine
        return FootballOracleEngine()
    except Exception as exc:
        return str(exc)

@st.cache_resource(show_spinner=False)
def load_apifootball_provider():
    # Sigur de cache-uit: verificat ca ApiFootballProvider nu tine nicio
    # stare per-cerere (doar key_manager/cache partajate + o sesiune HTTP
    # lazy) - vezi football_providers.py. Acelasi tipar ca load_engine().
    from football_providers import ApiFootballProvider
    return ApiFootballProvider()

def _load_json(path):
    if not path.exists(): return {}
    try: return json.loads(path.read_text(encoding="utf-8"))
    except: return {}

def _save_json(path, data):
    path.write_text(json.dumps(data, indent=4), encoding="utf-8")

def _prob_bar(label, prob, color):
    pct = prob * 100
    return f'<div class="prob-row"><div class="prob-label">{label}</div><div class="prob-bar-outer"><div class="prob-bar-inner" style="width:{min(pct,100):.1f}%;background:{color};"></div></div><div class="prob-pct" style="color:{color};">{pct:.1f}%</div></div>'

def _odds_cell(label, odds, model_pct, edge):
    od = f"{odds:.2f}" if odds > 1 else "—"
    ec = "edge-pos" if edge > 0 else "edge-neg"
    es = f"+{edge:.1f}%" if edge > 0 else f"{edge:.1f}%"
    return f'<div class="odds-cell"><div class="odds-cell-label">{label}</div><div class="odds-cell-val">{od}</div><div class="odds-cell-model">Model {model_pct:.1f}%</div><div class="odds-cell-edge {ec}">{es}</div></div>'

def _dq(dq, note):
    cls = {"live":"dq-live","elo":"dq-elo","neutral":"dq-neutral"}.get(dq,"dq-neutral")
    ic  = {"live":"✅","elo":"🟡","neutral":"⚠️"}.get(dq,"⚠️")
    return f'<span class="{cls}">{ic} {note[:38]}</span>'

# ── TOP BAR ──────────────────────────────────────────────────────────────────
now = datetime.now(timezone.utc)
st.markdown(f"""
<div class="topbar">
  <div><div class="topbar-logo">⚽ Football Oracle</div><div class="topbar-sub">Prediction &amp; Value Betting Terminal v3.0</div></div>
  <div class="topbar-time">{now.strftime("%a %d %b %Y · %H:%M")} UTC</div>
</div>""", unsafe_allow_html=True)

engine_obj = load_engine()
if isinstance(engine_obj, str):
    st.error(f"⚠️ Engine offline: {engine_obj}"); st.stop()
engine = engine_obj

# ── NAV ──────────────────────────────────────────────────────────────────────
if "nav" not in st.session_state: st.session_state["nav"] = "matches"
cn1, cn2, cn3 = st.columns(3)
with cn1:
    if st.button("⚽  MECIURI", use_container_width=True): st.session_state["nav"] = "matches"; st.rerun()
with cn2:
    if st.button("📊  PORTFOLIO", use_container_width=True): st.session_state["nav"] = "portfolio"; st.rerun()
with cn3:
    if st.button("⚙️  SETĂRI", use_container_width=True): st.session_state["nav"] = "settings"; st.rerun()
nav = st.session_state["nav"]

# ═════════════════════════════════════════════════════════════════════════════
# VIEW 1 — MECIURI
# ═════════════════════════════════════════════════════════════════════════════

# ─────────────────────────────────────────────────────────────────────────────
# MATCH CARD
# ─────────────────────────────────────────────────────────────────────────────
def _render_match_card(match: dict, engine) -> None:
    home    = match["home_team"]; away = match["away_team"]
    ko_utc  = match.get("kickoff_utc","")
    ko_time = ko_utc[11:16] if len(ko_utc) > 16 else "TBA"
    fid     = match.get("fixture_id","?")
    src     = match.get("source","")
    is_demo = str(src).startswith("demo")
    bk_h    = float(match.get("home_odds") or 0)
    bk_d    = float(match.get("draw_odds") or 0)
    bk_a    = float(match.get("away_odds") or 0)
    has_odds= bk_h > 0

    odds_html = ""
    if has_odds:
        odds_html = f'<div class="match-odds"><div class="odd-pill home">{bk_h:.2f}</div><div class="odd-pill draw">{bk_d:.2f}</div><div class="odd-pill away">{bk_a:.2f}</div></div>'
    demo_badge = ' <span style="font-size:.58rem;color:#4a9eff;background:rgba(74,158,255,.12);border:1px solid #4a9eff33;border-radius:3px;padding:.08rem .25rem;">DEMO</span>' if is_demo else ""

    st.markdown(f"""
    <div class="match-row">
        <div class="match-time">{ko_time}</div>
        <div class="match-teams">
            <div class="match-home">{home}{demo_badge}</div>
            <div class="match-away">{away}</div>
        </div>
        {odds_html}
        <div class="match-src">{src}</div>
    </div>""", unsafe_allow_html=True)

    ca, cb = st.columns([4, 1])
    with ca:
        if st.button(f"🔮 Analizează — {home} vs {away}", key=f"btn_{fid}", use_container_width=True):
            with st.spinner(f"Analiză {home} vs {away}..."):
                pred = engine.evaluate_match(match)
            if pred is None:
                st.error("Analiză eșuată — date insuficiente."); return
            st.session_state[f"pred_{fid}"] = pred
    with cb:
        if st.button("✕", key=f"close_{fid}", help="Închide"):
            if f"pred_{fid}" in st.session_state: del st.session_state[f"pred_{fid}"]

    pred = st.session_state.get(f"pred_{fid}")
    if pred is None: return

    # ── xG ────────────────────────────────────────────────────────────────
    inj_home = f'<div style="font-size:.58rem;color:var(--accent2);">▼ {pred.home_xg-pred.home_xg_pre_injury:+.3f} accidentări</div>' if abs(pred.home_xg - pred.home_xg_pre_injury) > 0.01 else ""
    inj_away = f'<div style="font-size:.58rem;color:var(--accent2);">▼ {pred.away_xg-pred.away_xg_pre_injury:+.3f} accidentări</div>' if abs(pred.away_xg - pred.away_xg_pre_injury) > 0.01 else ""
    st.markdown(f"""
    <div class="xg-block">
        <div class="xg-team"><div class="xg-label">{home}</div><div class="xg-val home">{pred.home_xg:.3f}</div><div style="font-size:.58rem;color:var(--t3);">xG</div>{inj_home}</div>
        <div class="xg-vs">VS</div>
        <div class="xg-team"><div class="xg-label">{away}</div><div class="xg-val away">{pred.away_xg:.3f}</div><div style="font-size:.58rem;color:var(--t3);">xG</div>{inj_away}</div>
    </div>""", unsafe_allow_html=True)

    # ── Probabilități ─────────────────────────────────────────────────────
    st.markdown('<span class="sub-label">Probabilități</span>', unsafe_allow_html=True)
    st.markdown(
        '<div style="padding:0 1.5rem;">'
        + _prob_bar(f"🏠 {home[:14]}", pred.prob_home_win, "#4a9eff")
        + _prob_bar("Egal",            pred.prob_draw,     "#ffb300")
        + _prob_bar(f"✈️ {away[:14]}", pred.prob_away_win, "#ff3d57")
        + "</div>", unsafe_allow_html=True
    )

    # ── Scoruri ───────────────────────────────────────────────────────────
    st.markdown('<span class="sub-label">Scoruri probabile</span>', unsafe_allow_html=True)
    sc_html = '<div style="padding:0 1.5rem;">'
    for i,(hg,ag,p) in enumerate(pred.top_scores[:6]):
        sc_html += f'<span class="score-chip {"top" if i==0 else ""}">{hg}–{ag} <small>({p:.1f}%)</small></span>'
    sc_html += "</div>"
    st.markdown(sc_html, unsafe_allow_html=True)

    # ── Cote & Edge ───────────────────────────────────────────────────────
    if has_odds:
        st.markdown(f'<span class="sub-label">Cote — {pred.bookmaker_name}</span>', unsafe_allow_html=True)
        st.markdown(
            f'<div class="odds-grid" style="padding:0 1.5rem;">'
            + _odds_cell("ACASĂ",    pred.bk_home_odds, pred.prob_home_win*100, pred.edge_home_pct)
            + _odds_cell("EGAL",     pred.bk_draw_odds, pred.prob_draw*100,     pred.edge_draw_pct)
            + _odds_cell("OASPEȚI",  pred.bk_away_odds, pred.prob_away_win*100, pred.edge_away_pct)
            + "</div>", unsafe_allow_html=True
        )

    # ── Monte Carlo vs Poisson comparison ───────────────────────────────
    mc_home = getattr(pred, "mc_prob_home", None)
    if mc_home is not None:
        st.markdown('<span class="sub-label">Model comparison — Poisson vs Monte Carlo (10k sim)</span>', unsafe_allow_html=True)
        mc_draw = pred.mc_prob_draw; mc_away = pred.mc_prob_away
        st.markdown(f"""
        <div style="padding:0 1.5rem;">
            <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:.4rem;margin-bottom:.4rem;">
                <div style="background:var(--card);border:1px solid var(--border);border-radius:6px;padding:.4rem;text-align:center;">
                    <div style="font-size:.55rem;color:var(--t3);text-transform:uppercase;">Acasă</div>
                    <div style="font-family:var(--oswald);font-size:.9rem;color:#4a9eff;">P {pred.prob_home_win*100:.1f}%</div>
                    <div style="font-family:var(--oswald);font-size:.9rem;color:#4a9effaa;">MC {mc_home*100:.1f}%</div>
                </div>
                <div style="background:var(--card);border:1px solid var(--border);border-radius:6px;padding:.4rem;text-align:center;">
                    <div style="font-size:.55rem;color:var(--t3);text-transform:uppercase;">Egal</div>
                    <div style="font-family:var(--oswald);font-size:.9rem;color:var(--amber);">P {pred.prob_draw*100:.1f}%</div>
                    <div style="font-family:var(--oswald);font-size:.9rem;color:#ffb300aa;">MC {mc_draw*100:.1f}%</div>
                </div>
                <div style="background:var(--card);border:1px solid var(--border);border-radius:6px;padding:.4rem;text-align:center;">
                    <div style="font-size:.55rem;color:var(--t3);text-transform:uppercase;">Oaspeți</div>
                    <div style="font-family:var(--oswald);font-size:.9rem;color:var(--accent2);">P {pred.prob_away_win*100:.1f}%</div>
                    <div style="font-family:var(--oswald);font-size:.9rem;color:#ff3d57aa;">MC {mc_away*100:.1f}%</div>
                </div>
            </div>
        </div>""", unsafe_allow_html=True)

    # ── Piețe speciale ────────────────────────────────────────────────────
    over25 = getattr(pred, "prob_over25", None)
    if over25 is not None:
        st.markdown('<span class="sub-label">Piețe speciale</span>', unsafe_allow_html=True)
        btts   = pred.prob_btts
        u25    = pred.prob_under25
        over15 = pred.prob_over15
        cs_h   = pred.prob_clean_sheet_home
        cs_a   = pred.prob_clean_sheet_away
        dc_h   = pred.prob_double_chance_home
        dc_a   = pred.prob_double_chance_away

        def _market_pill(label, prob, color="#4a9eff"):
            pct = prob * 100
            bg = "rgba(0,194,255,.08)" if color=="#4a9eff" else "rgba(0,230,118,.08)" if color=="var(--accent3)" else "rgba(255,179,0,.08)"
            return f'''<div style="background:{bg};border:1px solid {color}33;border-radius:7px;padding:.45rem .6rem;text-align:center;">
                <div style="font-size:.58rem;color:var(--t2);text-transform:uppercase;letter-spacing:.07em;">{label}</div>
                <div style="font-family:var(--oswald);font-size:1.05rem;font-weight:700;color:{color};">{pct:.1f}%</div>
            </div>'''

        st.markdown(f"""
        <div style="padding:0 1.5rem;">
            <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:.4rem;margin-bottom:.4rem;">
                {_market_pill("Over 2.5", over25, "#00e676")}
                {_market_pill("Under 2.5", u25, "#ff3d57")}
                {_market_pill("Over 1.5", over15, "#00c2ff")}
                {_market_pill("BTTS Da", btts, "#ffb300")}
            </div>
            <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:.4rem;">
                {_market_pill("CS Acasă", cs_h, "#4a9eff")}
                {_market_pill("CS Oaspeți", cs_a, "#4a9eff")}
                {_market_pill("DC 1X", dc_h, "#9b59b6")}
                {_market_pill("DC X2", dc_a, "#9b59b6")}
            </div>
        </div>""", unsafe_allow_html=True)

    # ── Value bets piețe speciale ─────────────────────────────────────────
    special_vbets = getattr(pred, "special_value_bets", [])
    if special_vbets:
        st.markdown('<span class="sub-label">🎯 Value Bets — Piețe Speciale</span>', unsafe_allow_html=True)
        for vb in special_vbets:
            st.markdown(f"""
            <div class="vbet" style="margin:0 1.5rem .3rem;">
                <div><div class="vbet-sel">{vb["rating"]} {vb["market"]} @ {vb["bk_odds"]:.2f}</div>
                <div class="vbet-detail">Model {vb["model_prob_pct"]:.1f}%</div></div>
                <div class="vbet-edge">+{vb["edge_pct"]:.1f}%</div>
            </div>""", unsafe_allow_html=True)

    # ── Value bets 1X2 ────────────────────────────────────────────────────
    if pred.value_bets:
        st.markdown('<span class="sub-label">🎯 Value Bets</span>', unsafe_allow_html=True)
        for vb in pred.value_bets:
            kelly = pred.kelly_stakes.get(vb["selection"], 0.0)
            lc1, lc2 = st.columns([5,1])
            with lc1:
                st.markdown(f"""
                <div class="vbet" style="margin:0 1.5rem .3rem;">
                    <div><div class="vbet-sel">{vb['rating']} {vb['selection']} @ {vb['bk_odds']:.2f}</div>
                    <div class="vbet-detail">Model {vb['model_prob_pct']:.1f}% · Kelly €{kelly:.2f}{vb.get('confidence_note','')}</div></div>
                    <div class="vbet-edge">+{vb['edge_pct']:.1f}%</div>
                </div>""", unsafe_allow_html=True)
            with lc2:
                if st.button("📌", key=f"log_{fid}_{vb['selection'].replace(' ','_')}"):
                    engine.log_bet(str(fid), f"{home} vs {away}", "1X2",
                                   vb["selection"], vb["bk_odds"],
                                   kelly if kelly>0 else float(engine.config.get("stake_default",10)), "")
                    st.toast(f"✅ {vb['selection']} @ {vb['bk_odds']:.2f}", icon="📌")

    # ── Team DNA ──────────────────────────────────────────────────────────
    if pred.home_profile and pred.away_profile:
        st.markdown('<span class="sub-label">Team DNA</span>', unsafe_allow_html=True)
        hp = pred.home_profile; ap = pred.away_profile
        st.markdown(f"""
        <div class="dna-grid" style="padding:0 1.5rem;">
            <div class="dna-box"><div class="dna-box-title">{home}</div>
                {_dq(hp.data_quality, hp.data_quality_note)}<br>
                <div class="dna-stat"><span class="dna-stat-k">OFF</span><span class="dna-stat-v">{hp.offensive_rating:.3f}</span></div>
                <div class="dna-stat"><span class="dna-stat-k">DEF</span><span class="dna-stat-v">{hp.defensive_rating:.3f}</span></div>
                <div class="dna-stat"><span class="dna-stat-k">Formă</span><span class="dna-stat-v">{"".join(hp.form_results[-5:]) or "N/A"}</span></div>
                <div class="dna-stat"><span class="dna-stat-k">ELO</span><span class="dna-stat-v">{hp.elo_rating or "—"}</span></div>
                <div class="dna-stat"><span class="dna-stat-k">Sursă</span><span class="dna-stat-v" style="font-size:.6rem;">{hp.data_source}</span></div>
            </div>
            <div class="dna-box"><div class="dna-box-title">{away}</div>
                {_dq(ap.data_quality, ap.data_quality_note)}<br>
                <div class="dna-stat"><span class="dna-stat-k">OFF</span><span class="dna-stat-v">{ap.offensive_rating:.3f}</span></div>
                <div class="dna-stat"><span class="dna-stat-k">DEF</span><span class="dna-stat-v">{ap.defensive_rating:.3f}</span></div>
                <div class="dna-stat"><span class="dna-stat-k">Formă</span><span class="dna-stat-v">{"".join(ap.form_results[-5:]) or "N/A"}</span></div>
                <div class="dna-stat"><span class="dna-stat-k">ELO</span><span class="dna-stat-v">{ap.elo_rating or "—"}</span></div>
                <div class="dna-stat"><span class="dna-stat-k">Sursă</span><span class="dna-stat-v" style="font-size:.6rem;">{ap.data_source}</span></div>
            </div>
        </div>""", unsafe_allow_html=True)

    # ── H2H ───────────────────────────────────────────────────────────────
    if pred.h2h and pred.h2h.meetings > 0:
        st.markdown(f'<div style="padding:.3rem 1.5rem;"><span class="sub-label">Head to Head</span><div style="font-size:.78rem;color:var(--t2);background:var(--card);border:1px solid var(--border);border-radius:6px;padding:.45rem .75rem;">{pred.h2h.summary}</div></div>', unsafe_allow_html=True)

    # ── Vreme ─────────────────────────────────────────────────────────────
    if pred.weather_penalty > 0:
        st.warning(f"🌧️ {pred.weather_note}")

    st.markdown('<div style="height:.4rem;"></div>', unsafe_allow_html=True)
    st.markdown('<hr style="border:none;border-top:1px solid var(--border);margin:.3rem 1.5rem;">', unsafe_allow_html=True)




if nav == "matches":

    # Fetch all
    if "all_matches" not in st.session_state or st.session_state.get("force_reload"):
        with st.spinner("📡 Se încarcă meciurile..."):
            all_matches = engine.api.get_matches_for_week(
                days_ahead=7,
                competitions=[c["key"] for c in COMPETITIONS_META]
            )
        st.session_state["all_matches"] = all_matches
        st.session_state["force_reload"] = False
    else:
        all_matches = st.session_state["all_matches"]

    comp_counts = {}
    for m in all_matches:
        lg = m.get("league",""); comp_counts[lg] = comp_counts.get(lg,0) + 1

    if "selected_comp" not in st.session_state:
        st.session_state["selected_comp"] = "World Cup 2026"

    # ── Competition cards ─────────────────────────────────────────────────
    st.markdown('<div class="section-bar"><div class="section-bar-title">Selectează competiția</div></div>', unsafe_allow_html=True)
    cols = st.columns(len(COMPETITIONS_META))
    for i, comp in enumerate(COMPETITIONS_META):
        key = comp["key"]
        cnt = comp_counts.get(key, 0)
        is_active = st.session_state["selected_comp"] == key
        ac = "active" if is_active else ""
        border_style = f"border-color:{comp['color']};box-shadow:0 0 0 1px {comp['color']},0 4px 16px {comp['color']}33;" if is_active else ""
        with cols[i]:
            st.markdown(f"""
            <div class="comp-card {ac}" style="{border_style}">
                <div class="comp-icon">{comp['icon']}</div>
                <div class="comp-name">{comp['label']}</div>
                <div class="comp-count">{cnt}</div>
            </div>""", unsafe_allow_html=True)
            if st.button("▶", key=f"c_{key}", use_container_width=True, help=comp["label"]):
                st.session_state["selected_comp"] = key
                st.rerun()

    sel = st.session_state["selected_comp"]
    cm  = next((c for c in COMPETITIONS_META if c["key"] == sel), COMPETITIONS_META[0])
    filtered = [m for m in all_matches if m.get("league") == sel]

    st.markdown(f'<div class="section-bar" style="margin-top:.4rem;"><div class="section-bar-title">{cm["icon"]} {cm["label"]}</div><div class="section-bar-pill">{len(filtered)} meciuri</div></div>', unsafe_allow_html=True)

    if not filtered:
        st.info(f"Niciun meci pentru {sel} în următoarele 7 zile.")
        if st.button("🔄 Reîncarcă"): st.session_state["force_reload"]=True; del st.session_state["all_matches"]; st.rerun()
        st.stop()

    today      = date.today()
    date_range = [(today + timedelta(days=i)) for i in range(7)]
    active_dates = [d for d in date_range if any(m.get("kickoff_date","") == d.isoformat() for m in filtered)]
    if not active_dates: st.info("Niciun meci."); st.stop()

    def _tab_label(d):
        cnt = sum(1 for m in filtered if m.get("kickoff_date","") == d.isoformat())
        if d == today: return f"🔴 Azi ({cnt})"
        if d == today+timedelta(1): return f"Mâine ({cnt})"
        return f"{d.strftime('%a %d/%m')} ({cnt})"

    tabs = st.tabs([_tab_label(d) for d in active_dates])

    for tab, target_date in zip(tabs, active_dates):
        with tab:
            day_matches = sorted(
                [m for m in filtered if m.get("kickoff_date","") == target_date.isoformat()],
                key=lambda x: x.get("kickoff_utc","")
            )
            for match in day_matches:
                _render_match_card(match, engine)

    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("🔄 Reîncarcă meciuri"):
        st.session_state["force_reload"] = True
        if "all_matches" in st.session_state: del st.session_state["all_matches"]
        st.rerun()


# ═════════════════════════════════════════════════════════════════════════════
# VIEW 2 — PORTFOLIO
# ═════════════════════════════════════════════════════════════════════════════
elif nav == "portfolio":
    st.markdown('<div class="section-bar"><div class="section-bar-title">📊 Portfolio & Analytics</div></div>', unsafe_allow_html=True)
    df = None
    if PORTFOLIO_PATH.exists():
        try:
            df = pd.read_csv(PORTFOLIO_PATH)
            if df.empty: df = None
        except: df = None

    if df is not None:
        settled = df[df["Result"].isin(["W","L"])]
        total=len(settled); wins=len(settled[settled["Result"]=="W"])
        wr=wins/total*100 if total>0 else 0
        staked=settled["Stake"].sum() if total>0 else 0
        pnl=settled["PnL"].sum() if total>0 else 0
        roi=pnl/staked*100 if staked>0 else 0
        pending=len(df[df["Result"]=="PENDING"])
        m1,m2,m3,m4,m5=st.columns(5)
        m1.metric("Pariuri",total); m2.metric("Win rate",f"{wr:.1f}%")
        m3.metric("Mizat",f"€{staked:.2f}"); m4.metric("P&L",f"€{pnl:+.2f}",delta=f"{roi:+.1f}%"); m5.metric("Pending",pending)
        if total>=2:
            sc=settled.copy().reset_index(drop=True); sc["Cumul PnL"]=sc["PnL"].cumsum(); sc["#"]=sc.index+1
            st.line_chart(sc.set_index("#")[["Cumul PnL"]],color="#00c2ff",height=160)
        st.dataframe(df,use_container_width=True,height=260)
    else:
        st.info("📭 Niciun pariu înregistrat.")

    st.markdown("---")
    with st.form("manual_bet"):
        st.markdown("**Adaugă pariu manual**")
        c1,c2,c3=st.columns(3)
        with c1: mb_m=st.text_input("Meci",placeholder="Argentina vs Croatia"); mb_mk=st.selectbox("Piață",["1X2","BTTS","Over 2.5","Handicap","Altul"])
        with c2: mb_s=st.text_input("Selecție",placeholder="Home Win"); mb_o=st.number_input("Cotă",min_value=1.01,value=2.00,step=0.05)
        with c3: mb_st=st.number_input("Miză (€)",min_value=0.1,value=10.0,step=0.5); mb_r=st.selectbox("Rezultat",["PENDING","W","L","V"]); mb_fi=st.text_input("Fixture ID",value="manual")
        if st.form_submit_button("📌 Înregistrează",use_container_width=True):
            if mb_m and mb_s:
                engine.log_bet(mb_fi or "manual",mb_m,mb_mk,mb_s,mb_o,mb_st,"" if mb_r=="PENDING" else mb_r)
                st.success(f"✅ {mb_m} | {mb_s} @ {mb_o:.2f}"); st.rerun()

    if df is not None:
        pending_df=df[df["Result"]=="PENDING"]
        if not pending_df.empty:
            st.markdown("---")
            with st.form("update_bet"):
                st.markdown("**Actualizează pariu**")
                row_idx=st.selectbox("Pariu",pending_df.index.tolist(),format_func=lambda i:f"#{i} {pending_df.loc[i,'Match']} — {pending_df.loc[i,'Selection']}")
                new_res=st.selectbox("Rezultat nou",["W","L","V"])
                # [FIX v1.1] League Learning nu mai depinde de Portfolio — recalibrarea
                # ponderilor se face automat, pentru TOATE meciurile, prin
                # sync/sync_results.py (job zilnic), nu prin confirmarea manuală a
                # unui pariu. Portfolio rămâne doar jurnal de pariuri: câmpurile de
                # scor + checkbox-ul "Recalibrare automată" au fost eliminate.
                if st.form_submit_button("✅ Actualizează",use_container_width=True):
                    full=pd.read_csv(PORTFOLIO_PATH)
                    ov=float(full.loc[row_idx,"Odds"]); sv=float(full.loc[row_idx,"Stake"])
                    pnl_v=round(sv*(ov-1),2) if new_res=="W" else (-round(sv,2) if new_res=="L" else 0.0)
                    full.at[row_idx,"Result"]=new_res; full.at[row_idx,"PnL"]=pnl_v; full.to_csv(PORTFOLIO_PATH,index=False)
                    st.success(f"✅ #{row_idx} → {new_res}  P&L=€{pnl_v:+.2f}")
                    st.rerun()


# ═════════════════════════════════════════════════════════════════════════════
# VIEW 3 — SETĂRI
# ═════════════════════════════════════════════════════════════════════════════
elif nav == "settings":
    st.markdown('<div class="section-bar"><div class="section-bar-title">⚙️ Setări model</div></div>', unsafe_allow_html=True)
    t1,t2,t3,t4=st.tabs(["🎛 Weights","⚡ Config","🧠 League Learning","🔍 Diagnostics"])
    with t1:
        # [REPARAT] Inainte citea direct din weights.json, ignorand Supabase
        # complet - arata valori vechi cand Supabase e sursa reala activa.
        # Acum citeste din engine.weights (deja incarcat corect, Supabase-
        # first, cu weights.json doar fallback - vezi FootballOracleEngine.__init__).
        w = engine.weights
        if not w:
            st.warning("Ponderi indisponibile (nici Supabase, nici weights.json local).")
        else:
            with st.form("wf"):
                wc1,wc2=st.columns(2)
                with wc1:
                    nfw=st.slider("form_weight",.05,.95,float(w.get("form_weight",.60)),.05)
                    ndw=st.slider("dna_weight",.05,.95,float(w.get("dna_weight",.40)),.05)
                    ngw=st.slider("goals_weight",.05,.80,float(w.get("goals_weight",.45)),.05)
                    nsow=st.slider("shots_ot_weight",.05,.60,float(w.get("shots_ot_weight",.30)),.05)
                    npw=st.slider("possession_weight",.05,.50,float(w.get("possession_weight",.25)),.05)
                with wc2:
                    nha=st.slider("home_advantage",1.00,1.20,float(w.get("home_advantage",1.07)),.01)
                    nap=st.slider("away_penalty",0.80,1.00,float(w.get("away_penalty",0.95)),.01)
                    nel=st.slider("elo_blend_weight",.10,.60,float(w.get("elo_blend_weight",.35)),.05)
                if st.form_submit_button("💾 Salvează",use_container_width=True):
                    w.update({"form_weight":nfw,"dna_weight":ndw,"goals_weight":ngw,"shots_ot_weight":nsow,"possession_weight":npw,"home_advantage":nha,"away_penalty":nap,"elo_blend_weight":nel})
                    # [REPARAT] Supabase (model_weights) e SURSA CANONICA -
                    # se scrie acolo daca e activ. weights.json local se
                    # actualizeaza mereu, DAR doar ca fallback/oglinda pt
                    # modul offline - nu mai e niciodata sursa principala.
                    engine.weights = w
                    saved_remote = engine.use_supabase and sb.save_weights(w)
                    _save_json(WEIGHTS_PATH, w)
                    if engine.use_supabase and not saved_remote:
                        st.error("⚠️ Salvare Supabase eșuată — s-a păstrat doar local (fallback), NU e sincronizat pe cloud.")
                    elif saved_remote:
                        st.success("✅ Salvat în Supabase (sursa canonică) + local (fallback).")
                    else:
                        st.warning("✅ Salvat doar local — Supabase indisponibil, NU e sursa activă acum.")
    with t2:
        # [REPARAT] Identic cu t1 - citeste din engine.config (deja incarcat
        # corect, Supabase-first), nu direct din config.json.
        cfg = engine.config
        if not cfg:
            st.warning("Config indisponibil (nici Supabase, nici config.json local).")
        else:
            with st.form("cf"):
                cc1,cc2=st.columns(2)
                with cc1:
                    nt=st.number_input("value_bet_threshold_pct",1.0,30.0,float(cfg.get("value_bet_threshold_pct",5.0)),.5)
                    nmg=st.number_input("max_goals_poisson",5,15,int(cfg.get("max_goals_poisson",8)),1)
                    nln=st.number_input("last_n_fixtures",3,10,int(cfg.get("last_n_fixtures",5)),1)
                with cc2:
                    nsd=st.number_input("stake_default (€)",1.0,1000.0,float(cfg.get("stake_default",10.0)),1.0)
                    nkf=st.slider("kelly_fraction",.05,1.0,float(cfg.get("kelly_fraction",.25)),.05)
                    nlr=st.slider("learning_rate",.01,.20,float(cfg.get("recalibration_learning_rate",.05)),.01)
                if st.form_submit_button("💾 Salvează",use_container_width=True):
                    cfg.update({"value_bet_threshold_pct":round(nt,1),"max_goals_poisson":int(nmg),"last_n_fixtures":int(nln),"stake_default":round(nsd,2),"kelly_fraction":round(nkf,2),"recalibration_learning_rate":round(nlr,3)})
                    engine.config = cfg
                    saved_remote = engine.use_supabase and sb.save_config(cfg)
                    _save_json(CONFIG_PATH, cfg)
                    if engine.use_supabase and not saved_remote:
                        st.error("⚠️ Salvare Supabase eșuată — s-a păstrat doar local (fallback).")
                    elif saved_remote:
                        st.success("✅ Salvat în Supabase (sursa canonică) + local (fallback).")
                    else:
                        st.warning("✅ Salvat doar local — Supabase indisponibil.")
    with t3:
        ldf=engine.get_league_learning_stats()
        st.dataframe(ldf,use_container_width=True,hide_index=True) if not ldf.empty else st.info("Fără date de calibrare.")
    with t4:
        mods=[("mappings.py","mappings"),("cache_manager.py","cache_manager"),("key_manager.py","key_manager"),("injury_manager.py","injury_manager"),("oracle_api.py","oracle_api"),("oracle_engine.py","oracle_engine")]
        mc1,mc2=st.columns(2)
        for i,(fn,mod) in enumerate(mods):
            col=mc1 if i%2==0 else mc2
            try: __import__(mod); col.success(f"✅ {fn}")
            except ImportError: col.error(f"❌ {fn}")
        st.markdown("---")
        if st.button("🗑️ Clear cache complet"):
            engine.api.clear_cache(); st.cache_resource.clear()
            if "all_matches" in st.session_state: del st.session_state["all_matches"]
            st.toast("Cache șters!",icon="🗑️")

        st.markdown("---")
        st.caption("⚠️ TEMPORAR — validare live API-Football (injuries/coaches). De eliminat după confirmare.")
        if st.button("🔍 Testează API-Football (Arsenal, team_id=42)"):
            import time as _time
            fp = load_apifootball_provider()
            # raspuns BRUT, nefiltrat de normalizare - folosim chei de cache
            # unice (cu timestamp) ca sa ocolim orice cache vechi si sa vedem
            # exact ce raspunde API-ul acum
            nonce = str(int(_time.time()))
            with st.spinner("Apelez /coachs (raw)..."):
                raw_coachs = fp._get("coachs", {"team": 42}, "coaches", f"diag_coachs_{nonce}")
            st.write("**Răspuns BRUT /coachs:**", raw_coachs)
            with st.spinner("Apelez /injuries (raw)..."):
                raw_injuries = fp._get("injuries", {"team": 42}, "injuries", f"diag_injuries_{nonce}")
            st.write("**Răspuns BRUT /injuries:**", raw_injuries)
            if raw_coachs is None and raw_injuries is None:
                st.error("Ambele None — HTTP nu a fost ok (vezi log-urile pt cod status exact).")

        st.markdown(f'<div style="font-size:.7rem;color:var(--t3);margin-top:.5rem;">Python {sys.version[:6]} · Football Oracle v3.0</div>',unsafe_allow_html=True)
