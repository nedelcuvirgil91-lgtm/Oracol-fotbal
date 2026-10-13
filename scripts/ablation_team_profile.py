"""
================================================================================
FOOTBALL ORACLE — Ablație: eficiența de finalizare (Team Profile) ajută?
================================================================================
Module: scripts/ablation_team_profile.py

STRICT read-only. Nu scrie nimic, nicăieri — nici în Supabase, nici pe disc.

ÎNTREBAREA
`flashscore_team_dna.rolling_finishing_and_setpieces()` calculează de luni de
zile `goals_per_xg` (goluri reale / xG real, pe sume aliniate, fereastră de 5
meciuri). Feature-ul e ADITIV și NEPROMOVAT: azi nicio predicție nu depinde de
el. Pragul de 300 de meciuri evaluabile, cerut de ADR-062, a fost atins pe
2026-10-13. Întrebarea pe care pragul o deblochează: **adaugă informație
predictivă reală, sau e zgomot curat?**

CE SE ȘTIE DINAINTE (`docs/03_ENGINE/TEAM_PROFILE_FINISHING_EFFICIENCY.md`)
Corelația split-half a lui `goals_per_xg` măsurată pe 2026-08-23: **−0,10**.
Dar martorii presupuși stabili ieșeau și ei ≈0 (xG mediu 0,076, cornere 0,054),
deci măsurătoarea NU distingea „metrica e zgomot" de „eșantion prea mic".
Eroarea relativă a raportului: **±36% la 5 meciuri**, scade cu √(xG acumulat).
Dispersia observată între echipe (0,413) era integral explicabilă prin zgomot
de eșantionare.

Deci priorul e sceptic, iar ablația asta e felul onest de a-l testa: nu „arată
bine formula?", ci „prezice mai bine?".

CUM SE APLICĂ, DACĂ AR FI PROMOVAT
Ca multiplicator pe xG-ul ofensiv: o echipă care convertește la 1,2× xG ar
primi xG servit mai mare. Variantele testate includ CONTRACȚII spre 1,0
(`1 + k*(gpx-1)`) tocmai pentru că metrica e zgomotoasă — aplicarea brută a
unui semnal cu ±36% eroare ar injecta mai mult zgomot decât informație.
Contracția nu e un truc de ajustare: e răspunsul standard la un estimator
nesigur, iar dacă NICIO contracție nu ajută, concluzia e mai tare decât dacă
ar fi fost testată o singură variantă.

ZERO SCURGERE TEMPORALĂ
Fereastra fiecărei echipe se construiește exclusiv din meciuri cu
`kickoff_date` STRICT anterior meciului evaluat, în aceleași competiții pe care
le acceptă producția (`TEAM_PROFILE_EXCLUDED_LEAGUES` deja aplicată la
extragere). Un meci e evaluabil doar dacă AMBELE echipe au ≥5 meciuri
anterioare cu xG real — exact regula `count_matches_with_sufficient_history()`.

VALIDITATE INTERNĂ, NU REPRODUCERE A PRODUCȚIEI
Ca la `ablation_form_weighting.py`: intrările de la servire ale Oracle nu sunt
persistate nicăieri (ADR-036 — coloanele din `match_history` sunt feature-uri
ML scrise de backfill). Toate brațele pornesc deci din ACELAȘI substrat, iar
singura variabilă care diferă e multiplicatorul de finalizare. Asta răspunde
curat la „ajută semnalul?", nu la „bate numărul servit".

Utilizare:
    python scripts/ablation_team_profile.py --date <cale.csv>
================================================================================
"""
from __future__ import annotations

import argparse
import math
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.ablation_form_weighting import agrega, mcnemar, scor_per_meci, t_pereche

BAR = "=" * 80
FEREASTRA = 5          # TEAM_PROFILE_WINDOW
ETICHETE = {"H": 0, "D": 1, "A": 2}

BASELINES = {"HNL": 1.18, "MLS": 1.4, "La Liga": 1.2, "Ligue 1": 1.3, "Serie A": 1.25,
             "default": 1.25, "Super Lig": 1.45, "Bundesliga": 1.4, "Eredivisie": 1.49,
             "Primeira Liga": 1.28, "Premier League": 1.35, "Romania SuperLiga": 1.15,
             "Ekstraklasa": 1.25, "Jupiler Pro League": 1.25, "Scottish Premiership": 1.25}


# ════════════════════════════════════════════════════════════════════════
# Semnalul — exact formula din producție
# ════════════════════════════════════════════════════════════════════════

def eficienta_finalizare(istoric: list[dict]) -> dict | None:
    """`goals_per_xg` și `goals_per_shot_on_target` pe SUME ALINIATE, nu ca
    medie a rapoartelor — identic cu
    `flashscore_team_dna.rolling_finishing_and_setpieces()`.

    Media rapoartelor ar exploda la un meci cu 0 șuturi pe poartă și ar aduna
    golurile unui meci cu xG-ul altuia când unul din cele două lipsește.
    Perechea se ia doar când AMBELE valori există.
    """
    if len(istoric) < FEREASTRA:
        return None
    r = istoric[-FEREASTRA:]
    g_xg = [(m["goluri"], m["xg"]) for m in r if m["goluri"] is not None and m["xg"] is not None]
    g_sot = [(m["goluri"], m["sot"]) for m in r if m["goluri"] is not None and m["sot"] is not None]
    if not g_xg:
        return None
    suma_xg = sum(x for _, x in g_xg)
    suma_sot = sum(s for _, s in g_sot)
    return {
        "goals_per_xg": (sum(g for g, _ in g_xg) / suma_xg) if suma_xg > 0 else None,
        "goals_per_sot": (sum(g for g, _ in g_sot) / suma_sot) if suma_sot > 0 else None,
        "n": len(r),
    }


# ════════════════════════════════════════════════════════════════════════
# Variantele de multiplicator
# ════════════════════════════════════════════════════════════════════════

def _contracta(valoare: float | None, k: float, jos: float, sus: float) -> float:
    """`1 + k*(v-1)`, prins în [jos, sus]. `k=0` → 1,0 (niciun efect), `k=1` →
    semnalul brut. Prinderea e a doua linie de apărare: o echipă cu 2 goluri
    din 0,4 xG pe 5 meciuri ar da un multiplicator de 5, care ar strica
    predicția mai rău decât absența semnalului."""
    if valoare is None:
        return 1.0
    return max(jos, min(sus, 1.0 + k * (valoare - 1.0)))


def construieste_variante() -> dict:
    """REFERINȚA e producția de azi: niciun multiplicator, adică 1,0 peste tot.

    Contracțiile (k) merg de la aplicarea brută (1,0) spre aproape-nimic
    (0,15). Dacă semnalul e real, trebuie să existe un `k` la care ajută; dacă
    toate ies negative, rezultatul e robust, nu dependent de o alegere a mea."""
    v = {"REFERINȚĂ — fără ajustare (producție)": lambda s: 1.0}
    for k in (1.00, 0.75, 0.50, 0.30, 0.15):
        v[f"goals_per_xg, k={k:.2f}"] = (
            lambda s, k=k: _contracta(s.get("goals_per_xg"), k, 0.70, 1.40))
    v["goals_per_xg, k=0.50, prindere strânsă [0.85, 1.18]"] = (
        lambda s: _contracta(s.get("goals_per_xg"), 0.50, 0.85, 1.18))
    v["goals_per_sot, k=0.50"] = (
        lambda s: _contracta(s.get("goals_per_sot"), 0.50, 0.70, 1.40))
    return v


# ════════════════════════════════════════════════════════════════════════

def _f(x: str) -> float | None:
    try:
        return float(x)
    except (ValueError, TypeError):
        return None


def incarca(cale: Path) -> list[dict]:
    """Pozițiile sunt fixate de `concat_ws` din extragere, în ordinea:
    0 dată · 1 ligă · 2 gazdă · 3 oaspete · 4 rezultat · 5-6 goluri ·
    7-8 xG real · 9-10 șuturi pe poartă · 11-12 cornere ·
    13-16 ratinguri of/def · 17-18 form_score · 19 h2h · 20 întâlniri ·
    21 vreme · 22-23 data_quality.

    Comentariul ăsta există fiindcă prima versiune citea de la poziția 14 în
    sus — un decalaj de UNU, care punea `home_defensive_rating` în locul lui
    `home_offensive_rating`. Nu a aruncat nicio excepție: toate valorile erau
    numere plauzibile, iar ablația a rulat până la capăt și a produs un tabel
    care arăta normal. Singurul simptom a fost acuratețea de referință de
    0,3054 — sub ghicitul aleatoriu. Vezi garda din `main()`."""
    randuri = []
    for linie in cale.read_text(encoding="utf-8").splitlines():
        c = linie.split("|")
        randuri.append({
            "zi": date.fromisoformat(c[0]), "liga": c[1],
            "gazda": c[2], "oaspete": c[3], "real": c[4],
            "g_h": _f(c[5]), "g_a": _f(c[6]), "xg_h": _f(c[7]), "xg_a": _f(c[8]),
            "sot_h": _f(c[9]), "sot_a": _f(c[10]),
            "h_off": _f(c[13]), "h_def": _f(c[14]), "a_off": _f(c[15]), "a_def": _f(c[16]),
            "fs_h": _f(c[17]), "fs_a": _f(c[18]),
            "h2h": _f(c[19]) or 0.0, "meet": int(_f(c[20]) or 0), "wx": _f(c[21]) or 0.0,
            "dq_h": c[22] if len(c) > 22 else "", "dq_a": c[23] if len(c) > 23 else "",
        })
    randuri.sort(key=lambda r: r["zi"])
    return randuri


def main() -> int:
    p = argparse.ArgumentParser(description="Ablație Team Profile (read-only)")
    p.add_argument("--date", required=True, help="fișier cu extragerea read-only")
    args = p.parse_args()

    from feature_engine import calibrate_xg, poisson_model

    randuri = incarca(Path(args.date))
    print(BAR)
    print("  ABLAȚIE — eficiența de finalizare (Team Profile) îmbunătățește predicțiile?")
    print("  READ-ONLY. Zero scriere. Niciun parametru de producție atins.")
    print(BAR)
    print(f"\n  Meciuri terminate încărcate: {len(randuri)}")

    istoric: dict[str, list[dict]] = defaultdict(list)
    variante = construieste_variante()
    per_meci: dict[str, list] = {n: [] for n in variante}
    multiplicatori: list[tuple[float, float]] = []
    evaluabile = 0
    pierdute_filtre = 0

    # Procesare ZI CU ZI, nu meci cu meci — semantica „anterior" e STRICT pe zi
    # calendaristică, identică cu `count_matches_with_sufficient_history()` și
    # cu `as_of_date` din `get_team_recent_advanced_stats()`.
    #
    # Prima versiune adăuga fiecare meci în istoric imediat după evaluarea lui,
    # deci un meci de dimineață intra în istoricul unuia de seara din ACEEAȘI
    # zi. Două consecințe, ambele rele: o scurgere pe care producția o
    # interzice explicit, și o dependență tăcută de ordinea din interiorul
    # zilei — ordine pe care `kickoff_date` singur nici n-o determină.
    pe_zi: dict[date, list[dict]] = defaultdict(list)
    for r in randuri:
        pe_zi[r["zi"]].append(r)

    for zi in sorted(pe_zi):
        meciurile_zilei = pe_zi[zi]

        # ÎNTÂI se evaluează toate meciurile zilei, contra istoricului STRICT
        # anterior zilei.
        for r in meciurile_zilei:
            sh = eficienta_finalizare(istoric[r["gazda"]])
            sa = eficienta_finalizare(istoric[r["oaspete"]])
            if not (sh and sa):
                continue
            if r["h_off"] is None or r["a_off"] is None \
                    or r["dq_h"] == "neutral" or r["dq_a"] == "neutral":
                pierdute_filtre += 1
                continue
            evaluabile += 1
            baseline = BASELINES.get(r["liga"], BASELINES["default"])
            for nume, fn in variante.items():
                mh, ma = fn(sh), fn(sa)
                hxg, axg = calibrate_xg(
                    home_offensive_rating=r["h_off"], home_defensive_rating=r["h_def"],
                    away_offensive_rating=r["a_off"], away_defensive_rating=r["a_def"],
                    home_form_score=r["fs_h"], away_form_score=r["fs_a"],
                    baseline=baseline, form_weight=0.6, base_weight=0.4,
                    home_advantage=1.07, away_penalty=0.95, defensive_cap=2.5,
                    h2h_modifier=r["h2h"], h2h_meetings=r["meet"], weather_penalty=r["wx"])
                ph, pd_, pa, _ = poisson_model(hxg * mh, axg * ma, 8)
                per_meci[nume].append(scor_per_meci((ph, pd_, pa), r["real"]))
                if nume.startswith("goals_per_xg, k=1.00"):
                    multiplicatori.append((mh, ma))

        # ABIA ACUM intră meciurile zilei în istoric, pentru zilele următoare.
        for r in meciurile_zilei:
            for echipa, g, xg, sot in ((r["gazda"], r["g_h"], r["xg_h"], r["sot_h"]),
                                        (r["oaspete"], r["g_a"], r["xg_a"], r["sot_a"])):
                if xg is not None:
                    istoric[echipa].append({"goluri": g, "xg": xg, "sot": sot})

    print(f"  Evaluabile (ambele echipe cu ≥{FEREASTRA} meciuri anterioare cu xG): {evaluabile}")
    if pierdute_filtre:
        print(f"  Sărite suplimentar ({pierdute_filtre}): fără ratinguri stocate sau cu")
        print(f"    `data_quality = neutral` — Oracle emite acolo o constantă (ADR-065),")
        print(f"    deci un multiplicator peste ea n-ar măsura finalizarea, ci constanta.")
        print(f"  Contorul din aplicație ({evaluabile + pierdute_filtre}) NU aplică aceste")
        print(f"    două filtre — de aceea diferă de cifra pe care rulează testul.")
    if evaluabile < 30:
        print("\nEROARE: prea puține meciuri evaluabile pentru orice concluzie.")
        return 1

    # ── Cât de mult mișcă semnalul, înainte de a privi metricile ─────────
    if multiplicatori:
        toti = [m for pereche in multiplicatori for m in pereche]
        toti.sort()
        print("\n" + BAR)
        print("  AMPLOAREA SEMNALULUI (multiplicator brut, k=1,00)")
        print(BAR)
        print(f"  minim {toti[0]:.3f} · p25 {toti[len(toti)//4]:.3f} · "
              f"median {toti[len(toti)//2]:.3f} · p75 {toti[3*len(toti)//4]:.3f} · "
              f"maxim {toti[-1]:.3f}")
        departe = sum(1 for m in toti if abs(m - 1.0) > 0.10)
        print(f"  {departe}/{len(toti)} ({100.0*departe/len(toti):.0f}%) deviază cu peste 10% de la 1,0")
        print("  Dacă semnalul abia mișcă xG-ul, nici metricile n-au cum să se miște —")
        print("  un rezultat nul ar însemna «prea slab ca să conteze», nu «fals».")

    # ── Rezultate ───────────────────────────────────────────────────────
    ref_nume = next(n for n in variante if n.startswith("REFERINȚĂ"))
    ref = per_meci[ref_nume]

    # ── GARDA DE PLAUZIBILITATE ────────────────────────────────────────
    # Brațul de referință e formula Oracle fără ajustare. Nu poate reproduce
    # exact producția (intrările de la servire nu sunt persistate, ADR-036),
    # dar TREBUIE să fie în aceeași vecinătate: Oracle măsurat pe sezonul
    # curent dă 0,47-0,51 acuratețe.
    #
    # Garda există fiindcă lipsa ei a costat: o eroare de indexare cu UNU în
    # `incarca()` a dat 0,3054 — sub ghicitul aleatoriu pe trei rezultate
    # (0,333) și sub „pariază mereu gazda" (~0,45). N-a aruncat nicio
    # excepție, iar tabelul rezultat arăta perfect normal. Fără prag, aș fi
    # raportat delte calculate pe intrări amestecate.
    acc_ref = agrega(ref)[0]
    if not (0.40 <= acc_ref <= 0.60):
        print("\n" + BAR)
        print(f"  ⚠️  OPRIT — acuratețea brațului de referință e {acc_ref:.4f},")
        print("      în afara intervalului plauzibil [0,40 – 0,60].")
        print("      Oracle măsurat pe sezonul curent dă 0,47-0,51. O valoare sub")
        print("      0,40 înseamnă aproape sigur intrări amestecate (ordinea")
        print("      coloanelor la încărcare), nu un rezultat real.")
        print("      NICIO deltă de mai jos nu e interpretabilă. Se oprește aici.")
        print(BAR)
        return 1

    print("\n" + BAR)
    print(f"  REZULTATE — {evaluabile} meciuri")
    print(BAR)
    print(f"  {'Variantă':<48s} {'Acuratețe':>10s} {'Log-loss':>10s} {'Brier':>10s}")
    agr = {n: agrega(per_meci[n]) for n in variante}
    for n in variante:
        a = agr[n]
        print(f"  {n:<48s} {a[0]:>10.4f} {a[1]:>10.4f} {a[2]:>10.4f}")

    print("\n" + BAR)
    print("  DELTE față de producție, cu semnificație PERECHE")
    print("  acuratețe: + e mai bine · log-loss și Brier: − e mai bine")
    print(BAR)
    castigatoare = []
    for n in variante:
        if n == ref_nume:
            continue
        v = per_meci[n]
        d_br, t_br = t_pereche(v, ref, 0)
        d_ll, t_ll = t_pereche(v, ref, 1)
        b, c, chi = mcnemar(v, ref)
        d_acc = agr[n][0] - agr[ref_nume][0]
        toate_trei = d_acc > 0 and d_ll < 0 and d_br < 0
        if toate_trei:
            castigatoare.append(n)
        print(f"  {n:<48s} acc {d_acc:+.4f} (b={b}, c={c}, χ²={chi:.2f})")
        print(f"  {'':<48s} ll  {d_ll:+.4f} (|t|={abs(t_ll):.2f})   "
              f"brier {d_br:+.4f} (|t|={abs(t_br):.2f})"
              + ("   ← TOATE TREI mai bune" if toate_trei else ""))

    # ── Putere: ce efect am fi putut detecta ────────────────────────────
    import statistics
    dif = [per_meci[n][k][0] - ref[k][0] for n in variante if n != ref_nume
           for k in range(len(ref))][:len(ref)]
    sd = statistics.stdev(dif) if len(dif) > 1 and any(dif) else 0.0
    print("\n" + BAR)
    print("  PUTEREA TESTULUI — ce efect ar fi fost detectabil")
    print(BAR)
    if sd > 0:
        mde = 2.8 * sd / math.sqrt(evaluabile)
        print(f"  Cu n={evaluabile} și dispersia observată a diferențelor perechi,")
        print(f"  efectul minim detectabil pe Brier (80% putere, 5%) e ≈ {mde:.4f}.")
        print("  Un rezultat nul NU dovedește că semnalul e zero — dovedește doar")
        print("  că e sub pragul ăsta.")
    else:
        print("  Diferențe perechi nule — semnalul nu mișcă deloc predicțiile.")

    print("\n" + BAR)
    print("  CONCLUZIE")
    print(BAR)
    if castigatoare:
        print(f"  {len(castigatoare)} variantă/variante mai bune simultan pe toate trei:")
        for n in castigatoare:
            print(f"     · {n}")
        print("  North Star #2 e îndeplinit DOAR dacă diferențele sunt și semnificative.")
        print("  Chiar atunci: „un backtest favorabil nu e, singur, suficient pentru a")
        print("  schimba formula Oracle" + "\" (CLAUDE.md) — autorizează cel mult PROPUNEREA")
        print("  unui experiment de calibrare separat.")
    else:
        print("  NICIO variantă nu e mai bună simultan pe toate trei metricile.")
        print("  Feature-ul NU se promovează. Rezultatul e consecvent cu priorul")
        print("  măsurat în august (corelație split-half −0,10, eroare ±36% la 5 meciuri).")
    print(BAR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
