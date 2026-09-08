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

── LIMITA FUNDAMENTALĂ, DESCOPERITĂ LA PRIMA RULARE (2026-09-08) ─────────
Prima versiune a acestui script pretindea că ține fix „exact ce a folosit
Oracle", citind `home/away_offensive_rating`, `home/away_defensive_rating` și
`home/away_form_score` din `match_history`. **Premisa era falsă**, iar ancora de
fidelitate a demascat-o: reconstrucția reproducea xG-ul servit în **2 din 460**
de meciuri (0,4%).

Cauza nu e un bug — e ADR-036 (Canonical Feature Ownership): acele coloane sunt
**feature-uri ML**, al căror unic scriitor e `sync/backfill_features.py`, nu
intrările pe care motorul le-a folosit la servire. Ele se calculează prin alt
lanț (`FormTracker` fără filtru de competiție, formă implicită 0,5 în loc de
0,0, ratinguri din ELO×medii pe fereastra proprie), deci diferă structural de
`oracle_engine._build_profile()`.

**Consecință de trasabilitate, notată explicit (North Star #9)**: intrările de
la servire ale Oracle NU SUNT PERSISTATE NICĂIERI. Verificat pe ambii candidați
— `match_history` stochează doar IEȘIRILE (`home/away_xg_pred`,
`prob_*_pred`), iar `shadow_predictions.feature_metadata` e `{}` pentru
`xgboost_v1` și `blend_v1` (populat doar pentru `flashscore_team_dna`, cu alte
câmpuri). Nicio analiză offline nu poate, azi, reproduce sau audita o predicție
Oracle până la intrările ei.

── CE MĂSOARĂ, ATUNCI ────────────────────────────────────────────────────
O ablație cu validitate INTERNĂ, nu o reproducere a producției. Toate brațele
— referința ȘI variantele — pornesc din ACELAȘI substrat de ratinguri, h2h,
ponderi și baseline (citite din `match_history`), iar singura variabilă care
diferă între ele e funcția care transformă șirul W/D/L în `form_score`.

Asta răspunde curat la întrebarea pusă („o fereastră de 3, cu constanța
premiată, e mai bună decât exponențialul pe 5?"), fiindcă comparația e între
brațe identice în tot restul. Ce NU poate răspunde: „ar fi bătut numărul pe
care Oracle chiar l-a servit" — pentru asta ar fi nevoie de intrările de la
servire, care nu există. Predicțiile reale stocate se raportează separat, ca
BENCHMARK EXTERN, exact ca să nu se confunde cele două lucruri.

── ZERO SCURGERE TEMPORALĂ ───────────────────────────────────────────────
Fiecare variantă recalculează `form_score` exclusiv din meciuri cu
`kickoff_date` STRICT anterior meciului evaluat, cu același filtru de
competiție și aceeași fereastră de 365 de zile ca
`supabase_client.get_team_recent_results()` — funcția reală de producție.

── SEMNIFICAȚIE, NU DOAR MEDII ───────────────────────────────────────────
Brațele prezic ACELEAȘI meciuri, deci diferențele sunt PERECHE: McNemar pentru
acuratețe, t pereche pentru log-loss și Brier. O eroare standard nepereche ar
supraestima grosolan incertitudinea. Se raportează în plus subgrupul exact al
ipotezei — meciurile cu «victorie recentă după ≥2 înfrângeri» — fiindcă o medie
pe tot sezonul diluează un tipar care apare rar.

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
    """`k` e valoarea „principală" de penalizare a dispersiei, dar se testează
    și 0,25 / 1,00 în jurul ei — altfel o concluzie ar depinde de un `k` ales
    de mine, iar un rezultat slab n-ar putea fi distins de un `k` prost ales.

    Sufixul „, ales" pe brațele lui `k` NU e decorativ: fără el, un `k` egal cu
    0.25 sau 1.00 ar produce chei identice cu brațele fixe, iar dict-ul ar
    colapsa TĂCUT de la 13 la 11 brațe — două variante ar dispărea din raport
    fără niciun semnal. Găsit prin test, nu prin citire."""
    return {
        "REFERINȚĂ — exponențial 5 (producție)": lambda r: exponential(r, 5),
        "exponențial 3":                         lambda r: exponential(r, 3),
        "egal 3":                                lambda r: egal(r, 3),
        "egal 4":                                lambda r: egal(r, 4),
        "egal 5":                                lambda r: egal(r, 5),
        "liniar 3":                              lambda r: liniar(r, 3),
        "liniar 5":                              lambda r: liniar(r, 5),
        "consistență 3 (k=0.25)":                lambda r: consistenta(r, 3, 0.25),
        f"consistență 3 (k={k}, ales)":          lambda r: consistenta(r, 3, k),
        "consistență 3 (k=1.00)":                lambda r: consistenta(r, 3, 1.00),
        "consistență 5 (k=0.25)":                lambda r: consistenta(r, 5, 0.25),
        f"consistență 5 (k={k}, ales)":          lambda r: consistenta(r, 5, k),
        "consistență 5 (k=1.00)":                lambda r: consistenta(r, 5, 1.00),
    }


def victorie_dupa_infrangeri(sir: list[str]) -> bool:
    """Subgrupul EXACT al ipotezei: «poate o echipă câștigă un meci norocos și
    apoi pierde 3 meciuri consecutive» — aici în forma observabilă înainte de
    meci: ultimul rezultat e W, dar cel puțin 2 din cele 3 dinainte sunt L.

    Există fiindcă o medie pe tot sezonul diluează un tipar rar: dacă
    exponențialul chiar greșește, greșește AICI, nu peste tot."""
    return len(sir) >= 4 and sir[-1] == "W" and sum(1 for x in sir[-4:-1] if x == "L") >= 2


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


def scor_per_meci(p: tuple[float, float, float], real: str) -> tuple[float, float, float]:
    """(Brier, log-loss, corect) pentru UN meci. Per meci, nu agregat, fiindcă
    testele de semnificație de mai jos sunt PERECHE și au nevoie de diferența
    meci cu meci, nu de două medii."""
    i = ETICHETE[real]
    brier = sum((p[k] - (1.0 if k == i else 0.0)) ** 2 for k in range(3))
    logloss = -math.log(max(p[i], 1e-10))
    corect = 1.0 if max(range(3), key=lambda k: p[k]) == i else 0.0
    return brier, logloss, corect


def agrega(v: list[tuple[float, float, float]]) -> tuple[float, float, float]:
    """(acuratețe, log-loss, Brier) — ordinea în care se și afișează."""
    n = len(v) or 1
    return (sum(x[2] for x in v) / n, sum(x[1] for x in v) / n, sum(x[0] for x in v) / n)


def t_pereche(varianta: list, referinta: list, idx: int) -> tuple[float, float]:
    """t pe diferențele PERECHE (variantă − referință) per meci.

    Perechea contează: ambele brațe prezic exact aceleași meciuri, deci o eroare
    standard nepereche ar include varianța dintre meciuri — care se anulează —
    și ar supraestima grosolan incertitudinea."""
    d = [varianta[k][idx] - referinta[k][idx] for k in range(len(varianta))]
    if not d:
        return 0.0, 0.0
    medie = sum(d) / len(d)
    sd = statistics.stdev(d) if len(d) > 1 else 0.0
    if not sd:
        return medie, 0.0
    return medie, medie / (sd / math.sqrt(len(d)))


def mcnemar(varianta: list, referinta: list) -> tuple[int, int, float]:
    """Pentru acuratețe, unde diferența e binară. `b` = referința a nimerit și
    varianta nu; `c` = invers. Doar meciurile pe care brațele NU sunt de acord
    poartă informație — restul se anulează."""
    b = sum(1 for k in range(len(varianta)) if referinta[k][2] == 1 and varianta[k][2] == 0)
    c = sum(1 for k in range(len(varianta)) if referinta[k][2] == 0 and varianta[k][2] == 1)
    chi = ((abs(b - c) - 1) ** 2 / (b + c)) if (b + c) > 0 else 0.0
    return b, c, chi


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

    # ── Bază de reconstrucție: cât de departe e de ce a servit Oracle ────
    # NU e o „ancoră de fidelitate" care poate trece: intrările de la servire nu
    # sunt persistate nicăieri (vezi docstring). Rata de mai jos se măsoară și se
    # afișează oricum, ca nimeni să nu creadă vreodată că studiul reproduce
    # producția — și ca o eventuală persistare viitoare a intrărilor să se vadă
    # imediat aici, prin salt la ~100%.
    print(BAR)
    print("  BAZA DE RECONSTRUCȚIE — cât reproduce din ce a servit Oracle?")
    print(BAR)
    xg_ok = prob_ok = 0
    for r in evaluabile:
        ph, pd, pa, hxg, axg = prezice(r, float(r["home_form_score"]), float(r["away_form_score"]))
        if abs(hxg - float(r["home_xg_pred"])) < 0.005 and abs(axg - float(r["away_xg_pred"])) < 0.005:
            xg_ok += 1
        if abs(ph - float(r["prob_home_pred"])) < 0.005 and abs(pa - float(r["prob_away_pred"])) < 0.005:
            prob_ok += 1
    n = len(evaluabile)
    print(f"  xG reprodus:             {xg_ok}/{n}  ({100.0*xg_ok/n:.1f}%)")
    print(f"  Probabilități reproduse: {prob_ok}/{n}  ({100.0*prob_ok/n:.1f}%)")
    if prob_ok < 0.95 * n:
        print("\n  Rată mică — AȘTEPTATĂ, nu un defect. Coloanele de ratinguri și formă")
        print("  din `match_history` sunt feature-uri ML scrise de `backfill_features.py`")
        print("  (ADR-036), nu intrările folosite de `oracle_engine._build_profile()`.")
        print("  Studiul de mai jos are validitate INTERNĂ (brațe identice în tot")
        print("  restul), NU e o reproducere a producției. Vezi benchmark-ul extern.")
    else:
        print("\n  Reconstrucție fidelă — intrările de la servire par acum persistate.")

    # ── Comparația variantelor ───────────────────────────────────────────
    variante = construieste_variante(args.k_consistenta)
    per_meci: dict[str, list] = {nume: [] for nume in variante}
    oracle_real: list = []          # benchmark extern: ce a prezis Oracle EFECTIV
    subgrup: list[int] = []         # indici ai meciurilor din subgrupul ipotezei
    fara_istoric = 0

    for r in evaluabile:
        liga = r.get("league") or ""
        ist_h = rezultate_inainte(r["home_team"], liga, r["_data"])
        ist_a = rezultate_inainte(r["away_team"], liga, r["_data"])
        if not ist_h or not ist_a:
            fara_istoric += 1
            continue
        real = r["actual_result"]
        p_h = float(r["prob_home_pred"])
        p_a = float(r["prob_away_pred"])
        oracle_real.append(scor_per_meci((p_h, max(0.0, 1.0 - p_h - p_a), p_a), real))
        if victorie_dupa_infrangeri(ist_h) or victorie_dupa_infrangeri(ist_a):
            subgrup.append(len(oracle_real) - 1)
        for nume, fn in variante.items():
            ph, pd, pa, _, _ = prezice(r, fn(ist_h), fn(ist_a))
            per_meci[nume].append(scor_per_meci((ph, pd, pa), real))

    m = len(oracle_real)
    if m == 0:
        print("\nEROARE: niciun meci cu istoric anterior pentru ambele echipe.")
        return 1

    print("\n" + BAR)
    print(f"  BENCHMARK EXTERN — ce a prezis Oracle EFECTIV (prob_*_pred stocate), n={m}")
    print(BAR)
    a_ext = agrega(oracle_real)
    print(f"  acuratețe {a_ext[0]:.4f}   log-loss {a_ext[1]:.4f}   Brier {a_ext[2]:.4f}")
    print("  Singura cifră din raport care descrie producția reală. NU e comparabilă")
    print("  direct cu tabelul de mai jos — alt substrat de intrări, nu alt braț.")

    print("\n" + BAR)
    print(f"  ABLAȚIE INTERNĂ — {m} meciuri ({fara_istoric} sărite: fără istoric anterior)")
    print("  Toate brațele: aceleași ratinguri, h2h, ponderi, baseline. Diferă DOAR")
    print("  funcția care transformă W/D/L în form_score.")
    print(BAR)
    print(f"  {'Variantă':<40s} {'Acuratețe':>10s} {'Log-loss':>10s} {'Brier':>10s}")
    agr = {nume: agrega(per_meci[nume]) for nume in variante}
    for nume in variante:
        a = agr[nume]
        print(f"  {nume:<40s} {a[0]:>10.4f} {a[1]:>10.4f} {a[2]:>10.4f}")

    ref_nume = next((n_ for n_ in variante if n_.startswith("REFERINȚĂ")), None)
    if ref_nume:
        ref = per_meci[ref_nume]
        print("\n" + BAR)
        print("  DELTE față de formula actuală, cu semnificație PERECHE")
        print("  acuratețe: + e mai bine · log-loss și Brier: − e mai bine")
        print("  |t| > 1,96 ≈ semnificativ la 5% · McNemar: b = referința a nimerit și")
        print("  varianta nu, c = invers; χ² > 3,84 ≈ semnificativ")
        print(BAR)
        castigatoare = []
        for nume in variante:
            if nume == ref_nume:
                continue
            v = per_meci[nume]
            d_br, t_br = t_pereche(v, ref, 0)
            d_ll, t_ll = t_pereche(v, ref, 1)
            b, c, chi = mcnemar(v, ref)
            d_acc = agr[nume][0] - agr[ref_nume][0]
            toate_trei = d_acc > 0 and d_ll < 0 and d_br < 0
            if toate_trei:
                castigatoare.append(nume)
            print(f"  {nume:<40s} acc {d_acc:+.4f} (b={b}, c={c}, χ²={chi:.2f})")
            print(f"  {'':<40s} ll  {d_ll:+.4f} (|t|={abs(t_ll):.2f})   "
                  f"brier {d_br:+.4f} (|t|={abs(t_br):.2f})"
                  + ("   ← TOATE TREI mai bune" if toate_trei else ""))

        # ── Subgrupul exact al ipotezei ──────────────────────────────────
        print("\n" + BAR)
        print(f"  SUBGRUP — «victorie recentă după ≥2 înfrângeri»: {len(subgrup)} din {m} meciuri")
        print("  Dacă ponderarea exponențială chiar greșește, greșește AICI. O medie pe")
        print("  tot sezonul ar dilua un tipar rar până la invizibilitate.")
        print(BAR)
        if subgrup:
            print(f"  {'Variantă':<40s} {'Acuratețe':>10s} {'Log-loss':>10s} {'Brier':>10s}")
            for nume in variante:
                a = agrega([per_meci[nume][k] for k in subgrup])
                print(f"  {nume:<40s} {a[0]:>10.4f} {a[1]:>10.4f} {a[2]:>10.4f}")
            a = agrega([oracle_real[k] for k in subgrup])
            print(f"  {'(Oracle real, stocat — benchmark extern)':<40s} "
                  f"{a[0]:>10.4f} {a[1]:>10.4f} {a[2]:>10.4f}")
        else:
            print("  Niciun meci în subgrup — ipoteza nu e testabilă pe acest eșantion.")

    print("\n" + BAR)
    print("  Ablație încheiată. ZERO scriere efectuată.")
    print("  ATENȚIE la interpretare:")
    print(f"   · {len(variante) - 1} variante testate pe un singur sezon — cea mai bună")
    print("     poate fi cea mai norocoasă. Se raportează TOATE, nu doar câștigătoarea.")
    print("   · Validitate INTERNĂ, nu reproducere a producției (vezi baza de")
    print("     reconstrucție de mai sus și docstring-ul modulului).")
    print("   · North Star #2: doar o variantă mai bună simultan pe toate trei")
    print("     metricile e candidată; oricare alta NU e.")
    print("   · Chiar și atunci: 'un backtest favorabil nu e, singur, suficient")
    print("     pentru a schimba formula Oracle' (CLAUDE.md). Rezultatul aici")
    print("     autorizează cel mult PROPUNEREA unui experiment de calibrare.")
    print(BAR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
