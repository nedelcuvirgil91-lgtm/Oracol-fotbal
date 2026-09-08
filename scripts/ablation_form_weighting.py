"""
================================================================================
FOOTBALL ORACLE — Ablație: cum ar trebui ponderată forma recentă?
================================================================================
Module: scripts/ablation_form_weighting.py

STRICT read-only. Nu scrie nimic, nicăieri — nici în Supabase, nici pe disc.
Nu atinge `weights.json`, `model_config`, nicio predicție stocată.

ÎNTREBAREA, pusă de proprietarul produsului (2026-09-08):

    „Forma ultimului meci nu ar trebui să fie așa mare. Ar trebui ca forma
    ultimelor 3 meciuri să fie cea care contează. Constanța ar trebui
    premiată — poate o echipă câștigă un meci norocos și apoi pierde 3
    meciuri consecutive."

Observația e corectă aritmetic. `feature_engine.compute_form_score()` ponderează
exponențial (`2**i`), deci pe 5 meciuri ponderile sunt 1, 2, 4, 8, 16 din 31:
**ultimul meci singur decide 51,6% din scorul de formă**, iar cel mai vechi 3,2%.
Exemplul dat se verifică: o echipă cu `L, L, L, W` (victoria cea mai recentă)
primește form_score = 8/15 = **0,533** — peste medie, deși a pierdut 3 din 4.

── CE MĂSOARĂ, EXACT ─────────────────────────────────────────────────────
Se schimbă O SINGURĂ variabilă: funcția care transformă șirul W/D/L în
`form_score`. Tot restul e ținut FIX la valorile pe care Oracle chiar le-a
folosit — `home/away_offensive_rating`, `home/away_defensive_rating`,
`h2h_modifier`, `h2h_meetings`, ponderile, baseline-ul ligii — citite din
`match_history`, nu recalculate.

Asta izolează curat întrebarea pusă. Ce NU acoperă (limită onestă, §4 din
raport): ratingurile ofensive/defensive sunt derivate din ACEEAȘI fereastră de
5 meciuri (`oracle_engine.py:1481-1490`), deci un experiment care ar schimba și
fereastra ratingurilor ar măsura altceva. Aici se măsoară strict multiplicatorul
de formă.

── ZERO SCURGERE TEMPORALĂ ───────────────────────────────────────────────
Fiecare variantă recalculează `form_score` exclusiv din meciuri cu
`kickoff_date` STRICT anterior meciului evaluat, cu același filtru de
competiție și aceeași fereastră de 365 de zile ca
`supabase_client.get_team_recent_results()` — funcția reală de producție.

── ANCORA DE FIDELITATE (fără ea, nimic din raport nu e credibil) ─────────
Înainte de orice comparație, varianta „referință" recalculează predicția
folosind `form_score`-ul STOCAT și verifică dacă reproduce `home_xg_pred` și
`prob_home_pred` din bază. Dacă rata de reproducere nu e ~100%, lanțul e
infidel, iar raportul o spune în clar și NU pretinde concluzii.

Utilizare:
    python scripts/ablation_form_weighting.py
    python scripts/ablation_form_weighting.py --k-consistenta 0.5
================================================================================
"""
from __future__ import annotations

import argparse
import logging
import math
import statistics
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s")

BAR = "=" * 78

# Aceleași competiții excluse ca la Team Profile: acolo unde filtrul pe
# competiție al formei e el însuși defect (vezi
# docs/03_ENGINE/EUROPEAN_COMPETITION_FORM_FILTER_DEFECT.md), am măsura două
# schimbări deodată. Se rămâne pe ligile domestice, unde filtrul funcționează.
COMPETITII_EXCLUSE = ("Champions League", "Europa League", "Conference League", "World Cup 2026")

VALORI_REZULTAT = {"W": 1.0, "D": 0.4, "L": 0.0}  # oglindește feature_engine._FORM_RESULT_VALUES
ETICHETE = {"H": 0, "D": 1, "A": 2}
LOOKBACK_ZILE = 365  # identic cu get_team_recent_results()


# ════════════════════════════════════════════════════════════════════════
# Variantele de ponderare — funcții PURE, ușor de citit și de contestat
# ════════════════════════════════════════════════════════════════════════

def _medie_ponderata(rezultate: list[str], ponderi: list[float]) -> float:
    """`rezultate` în ordine cronologică, cel mai RECENT ultimul — aceeași
    convenție ca `feature_engine.compute_form_score()`.

    `round(..., 4)` NU e cosmetic: producția rotunjește (`compute_form_score`,
    ultima linie), iar fără el varianta de referință ar diferi de funcția reală
    la a cincea zecimală. Diferența e neglijabilă numeric (mută multiplicatorul
    cu ~1e-5), dar o referință care nu reproduce EXACT producția face toate
    deltele raportate să fie față de o formulă care nu rulează nicăieri.
    Găsit de testul de fidelitate, nu prin citire."""
    if not rezultate:
        return 0.0
    total = sum(ponderi) or 1.0
    return round(
        sum(VALORI_REZULTAT.get(r, 0.4) * p for r, p in zip(rezultate, ponderi)) / total, 4)


def exponential(rezultate: list[str], fereastra: int) -> float:
    """Formula ACTUALĂ din producție, restrânsă la ultimele `fereastra`."""
    r = rezultate[-fereastra:]
    return _medie_ponderata(r, [2 ** i for i in range(len(r))])


def egal(rezultate: list[str], fereastra: int) -> float:
    """Medie simplă — fiecare meci din fereastră contează la fel."""
    r = rezultate[-fereastra:]
    return _medie_ponderata(r, [1.0] * len(r))


def liniar(rezultate: list[str], fereastra: int) -> float:
    """Recență mai blândă: ponderi 1, 2, 3… în loc de 1, 2, 4, 8…"""
    r = rezultate[-fereastra:]
    return _medie_ponderata(r, [float(i + 1) for i in range(len(r))])


def consistenta(rezultate: list[str], fereastra: int, k: float) -> float:
    """Medie simplă PENALIZATĂ cu dispersia — «constanța e premiată».

    Două echipe cu aceeași medie primesc scoruri diferite: `W W W` (dispersie
    0) rămâne sus, `W L W` (dispersie mare) coboară. Rezultatul e prins în
    [0, 1], ca orice `form_score` — `calibrate_xg()` presupune intervalul ăsta.
    """
    r = rezultate[-fereastra:]
    if not r:
        return 0.0
    valori = [VALORI_REZULTAT.get(x, 0.4) for x in r]
    medie = sum(valori) / len(valori)
    disp = statistics.pstdev(valori) if len(valori) > 1 else 0.0
    return round(max(0.0, min(1.0, medie - k * disp)), 4)


def construieste_variante(k: float) -> dict:
    return {
        "REFERINȚĂ — exponențial, 5 (producție)": lambda r: exponential(r, 5),
        "exponențial, ultimele 3":                lambda r: exponential(r, 3),
        "egal, ultimele 3":                       lambda r: egal(r, 3),
        "egal, ultimele 5":                       lambda r: egal(r, 5),
        "liniar, ultimele 5":                     lambda r: liniar(r, 5),
        f"consistență, 3 (k={k})":                lambda r: consistenta(r, 3, k),
        f"consistență, 5 (k={k})":                lambda r: consistenta(r, 5, k),
    }


# ════════════════════════════════════════════════════════════════════════

def _ca_data(v) -> date | None:
    try:
        return date.fromisoformat(str(v).strip()[:10])
    except (ValueError, TypeError):
        return None


def _rezultat_pentru(rand: dict, echipa: str) -> str | None:
    r = rand.get("actual_result")
    if r not in ("H", "D", "A"):
        return None
    acasa = rand.get("home_team") == echipa
    if r == "D":
        return "D"
    if r == "H":
        return "W" if acasa else "L"
    return "L" if acasa else "W"


def _metrici(perechi: list[tuple[tuple[float, float, float], str]]) -> dict:
    """Aceleași trei metrici ca peste tot în proiect (North Star #2)."""
    n = len(perechi)
    if n == 0:
        return {"n": 0}
    brier = logloss = corecte = 0.0
    for (ph, pd, pa), real in perechi:
        idx = ETICHETE[real]
        p = (ph, pd, pa)
        brier += sum((p[i] - (1.0 if i == idx else 0.0)) ** 2 for i in range(3))
        logloss += -math.log(max(p[idx], 1e-10))
        corecte += 1.0 if max(range(3), key=lambda i: p[i]) == idx else 0.0
    return {"n": n, "brier": brier / n, "log_loss": logloss / n, "acuratete": corecte / n}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ablație: ponderarea formei recente (read-only)")
    parser.add_argument("--k-consistenta", type=float, default=0.5,
                        help="cât de tare penalizează dispersia (implicit 0.5)")
    parser.add_argument("--sezon-de-la", default="2026-07-01")
    args = parser.parse_args()

    import supabase_client as sb
    from feature_engine import calibrate_xg, poisson_model

    if not sb.is_available():
        print("EROARE: Supabase indisponibil (SUPABASE_URL / SUPABASE_SECRET_KEY).")
        return 1

    weights = sb.load_weights() if hasattr(sb, "load_weights") else {}
    if not weights:
        import json
        weights = json.loads(Path("weights.json").read_text(encoding="utf-8"))
    cfg = sb.load_config({"max_goals_poisson": 8})
    max_goals = int(cfg.get("max_goals_poisson", 8))
    baselines = weights.get("league_baselines", {})

    print(BAR)
    print("  ABLAȚIE — cum ar trebui ponderată forma recentă?")
    print("  READ-ONLY. Zero scriere. Nicio pondere de producție atinsă.")
    print(BAR)

    client = sb.get_client()
    randuri: list[dict] = []
    cursor = None
    while True:
        q = (client.table("match_history")
             .select("fixture_id,league,home_team,away_team,kickoff_date,actual_result,"
                     "home_offensive_rating,home_defensive_rating,away_offensive_rating,"
                     "away_defensive_rating,home_form_score,away_form_score,h2h_modifier,"
                     "h2h_meetings,home_xg_pred,away_xg_pred,prob_home_pred,prob_draw_pred,"
                     "prob_away_pred,home_data_quality,away_data_quality,weather_penalty")
             .not_.is_("actual_result", "null").is_("superseded_by", "null"))
        if cursor is not None:
            q = q.gt("fixture_id", cursor)
        page = (q.order("fixture_id").limit(1000).execute()).data or []
        randuri.extend(page)
        if len(page) < 1000:
            break
        cursor = page[-1]["fixture_id"]

    for r in randuri:
        r["_data"] = _ca_data(r.get("kickoff_date"))
    randuri = [r for r in randuri if r["_data"] is not None]
    randuri.sort(key=lambda r: r["_data"])

    # Istoric per (echipă, competiție) — exact cheia pe care o folosește
    # get_team_recent_results() prin `.eq("league", league)`.
    istoric: dict[tuple[str, str], list[tuple[date, str]]] = defaultdict(list)
    for r in randuri:
        for echipa in (r.get("home_team"), r.get("away_team")):
            rez = _rezultat_pentru(r, echipa)
            if echipa and rez:
                istoric[(echipa, r.get("league") or "")].append((r["_data"], rez))

    def rezultate_inainte(echipa: str, liga: str, moment: date) -> list[str]:
        limita = moment - timedelta(days=LOOKBACK_ZILE)
        anterioare = [(d, x) for d, x in istoric[(echipa, liga)] if limita <= d < moment]
        anterioare.sort(key=lambda t: t[0])
        return [x for _, x in anterioare[-5:]]  # cel mai recent ULTIMUL

    inceput = _ca_data(args.sezon_de_la)
    evaluabile = [
        r for r in randuri
        if r["_data"] >= inceput
        and (r.get("league") or "") not in COMPETITII_EXCLUSE
        and r.get("home_offensive_rating") is not None
        and r.get("away_offensive_rating") is not None
        and r.get("home_form_score") is not None
        and r.get("prob_home_pred") is not None
        and r.get("home_data_quality") != "neutral"
        and r.get("away_data_quality") != "neutral"
    ]
    print(f"\n  Meciuri terminate în bază: {len(randuri)}")
    print(f"  Eligibile (sezon, ligi domestice, profil informat, predicție stocată): "
          f"{len(evaluabile)}\n")
    if not evaluabile:
        print("EROARE: niciun meci eligibil.")
        return 1

    def prezice(r: dict, fs_home: float, fs_away: float) -> tuple[float, float, float, float, float]:
        liga = r.get("league") or ""
        w = weights
        baseline = float(baselines.get(liga, baselines.get("default", 1.25)))
        hxg, axg = calibrate_xg(
            home_offensive_rating=float(r["home_offensive_rating"]),
            home_defensive_rating=float(r["home_defensive_rating"]),
            away_offensive_rating=float(r["away_offensive_rating"]),
            away_defensive_rating=float(r["away_defensive_rating"]),
            home_form_score=fs_home, away_form_score=fs_away,
            baseline=baseline,
            form_weight=float(w.get("form_weight", 0.6)),
            base_weight=float(w.get("base_weight", 0.4)),
            home_advantage=float(w.get("home_advantage", 1.07)),
            away_penalty=float(w.get("away_penalty", 0.95)),
            defensive_cap=float(w.get("defensive_cap", 2.5)),
            h2h_modifier=float(r.get("h2h_modifier") or 0.0),
            h2h_meetings=int(r.get("h2h_meetings") or 0),
            weather_penalty=float(r.get("weather_penalty") or 0.0),
        )
        ph, pd, pa, _ = poisson_model(hxg, axg, max_goals)
        return ph, pd, pa, hxg, axg

    # ── Ancora de fidelitate ──────────────────────────────────────────────
    print(BAR)
    print("  ANCORĂ DE FIDELITATE — reconstrucția reproduce ce a servit Oracle?")
    print(BAR)
    xg_ok = prob_ok = 0
    for r in evaluabile:
        ph, pd, pa, hxg, axg = prezice(r, float(r["home_form_score"]), float(r["away_form_score"]))
        if abs(hxg - float(r["home_xg_pred"])) < 0.005 and abs(axg - float(r["away_xg_pred"])) < 0.005:
            xg_ok += 1
        if abs(ph - float(r["prob_home_pred"])) < 0.005 and abs(pa - float(r["prob_away_pred"])) < 0.005:
            prob_ok += 1
    n = len(evaluabile)
    print(f"  xG reprodus:           {xg_ok}/{n}  ({100.0*xg_ok/n:.1f}%)")
    print(f"  Probabilități reproduse: {prob_ok}/{n}  ({100.0*prob_ok/n:.1f}%)")
    if prob_ok < 0.95 * n:
        print("\n  ⚠️  RECONSTRUCȚIA NU E FIDELĂ (<95%). Rezultatele de mai jos NU susțin")
        print("      nicio concluzie — lanțul reprodus diferă de cel servit în producție.")
        print("      Cauza trebuie găsită înainte de a interpreta orice deltă.")
    else:
        print("\n  Reconstrucție fidelă — deltele de mai jos sunt atribuibile EXCLUSIV")
        print("  schimbării de ponderare a formei.")

    # ── Comparația variantelor ───────────────────────────────────────────
    variante = construieste_variante(args.k_consistenta)
    rezultate: dict[str, list] = {nume: [] for nume in variante}
    fara_istoric = 0

    for r in evaluabile:
        liga = r.get("league") or ""
        ist_h = rezultate_inainte(r["home_team"], liga, r["_data"])
        ist_a = rezultate_inainte(r["away_team"], liga, r["_data"])
        if not ist_h or not ist_a:
            fara_istoric += 1
            continue
        for nume, fn in variante.items():
            ph, pd, pa, _, _ = prezice(r, fn(ist_h), fn(ist_a))
            rezultate[nume].append(((ph, pd, pa), r["actual_result"]))

    print("\n" + BAR)
    print(f"  REZULTATE — {len(evaluabile) - fara_istoric} meciuri "
          f"({fara_istoric} sărite: fără istoric anterior pentru ambele echipe)")
    print(BAR)
    print(f"  {'Variantă':<34s} {'Acuratețe':>10s} {'Log-loss':>10s} {'Brier':>10s}")

    referinta = None
    rand_final: list[tuple[str, dict]] = []
    for nume in variante:
        m = _metrici(rezultate[nume])
        if not m.get("n"):
            continue
        rand_final.append((nume, m))
        if nume.startswith("REFERINȚĂ"):
            referinta = m
        print(f"  {nume:<34s} {m['acuratete']:>10.4f} {m['log_loss']:>10.4f} {m['brier']:>10.4f}")

    if referinta:
        print("\n" + BAR)
        print("  DELTE față de formula actuală")
        print("  acuratețe: + e mai bine · log-loss și Brier: − e mai bine")
        print(BAR)
        for nume, m in rand_final:
            if nume.startswith("REFERINȚĂ"):
                continue
            toate_trei = (m["acuratete"] > referinta["acuratete"]
                          and m["log_loss"] < referinta["log_loss"]
                          and m["brier"] < referinta["brier"])
            marcaj = "  ← toate trei mai bune" if toate_trei else ""
            print(f"  {nume:<34s} "
                  f"acc {m['acuratete'] - referinta['acuratete']:+.4f}   "
                  f"ll {m['log_loss'] - referinta['log_loss']:+.4f}   "
                  f"brier {m['brier'] - referinta['brier']:+.4f}{marcaj}")

    print("\n" + BAR)
    print("  Ablație încheiată. ZERO scriere efectuată.")
    print("  ATENȚIE la interpretare:")
    print("   · 7 variante testate pe un singur sezon — cea mai bună poate fi")
    print("     cea mai norocoasă. Se raportează TOATE, nu doar câștigătoarea.")
    print("   · North Star #2: doar o variantă mai bună simultan pe toate trei")
    print("     metricile e candidată; oricare alta NU e.")
    print("   · Chiar și atunci: 'un backtest favorabil nu e, singur, suficient")
    print("     pentru a schimba formula Oracle' (CLAUDE.md). Rezultatul aici")
    print("     autorizează cel mult PROPUNEREA unui experiment de calibrare.")
    print(BAR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
