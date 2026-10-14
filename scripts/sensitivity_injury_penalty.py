"""
================================================================================
FOOTBALL ORACLE — Calea 0: cât POATE conta penalizarea de accidentări
================================================================================
Module: scripts/sensitivity_injury_penalty.py

STRICT read-only. Nu scrie nimic, nicăieri — nici în Supabase, nici pe disc.

ÎNTREBAREA, ȘI DE CE SE PUNE ÎNAINTE DE ORICE COLECTARE DE DATE
`oracle_engine.evaluate_match()` conține deja penalizarea de accidentări
(`injury_manager.apply_injury_penalty`), capabilă să taie până la 30% din xG
(`MAX_TOTAL_TEAM_IMPACT = 0.30`). Componenta e MOARTĂ: `freelf_lineup_snapshot`
are 0 rânduri, deci `get_freelf_lineup_snapshot()` întoarce mereu `None`.

Integrarea unei surse noi (Transfermarkt) ar costa un ADR, un POC, mapare de
identitate, cadență și gating. Întrebarea care trebuie să vină ÎNAINTEA acelui
cost: **care e plafonul teoretic al câștigului?** Dacă nici un oracol perfect de
accidentări n-ar aduce decât ~1pp, proiectul nu merită făcut, iar răspunsul
costă o oră în loc de trei luni.

DESCOPERIRE CARE SCHIMBĂ PRIORITATEA (2026-10-14, verificată în cod)
Penalizarea NU e gatată de niciun flag: `oracle_engine.py:1808` cere doar
`if self.injury_manager and DB_QUERIES_MODULE_AVAILABLE`, iar ambele sunt
`True` în producție. Deci scrierea PRIMULUI rând în `freelf_lineup_snapshot`
schimbă imediat xG-ul servit, pentru toate meciurile. Colectarea datelor *este*
schimbarea predicției. Un flag implicit oprit e precondiție tehnică, nu
formalitate de proces (North Star #1 și #3).

DE CE MĂSURĂTOAREA ASTA E EXACTĂ, NU APROXIMATIVĂ
Spre deosebire de `ablation_form_weighting.py` și `ablation_team_profile.py`,
care au putut pretinde doar validitate internă (intrările de la servire nu sunt
persistate — vezi D-2), aici lanțul e complet reproductibil din date stocate:

    oracle_engine.py:1869   ph, pd, pa, _ = self._poisson_model(home_xg, away_xg)
    oracle_engine.py:1946   prob_home_win=round(ph, 4), prob_draw=round(pd, 4), ...

Oracle NU blendează: comentariul din cod o spune explicit — „rb_ph/rb_pd/rb_pa
sunt identice cu ph/pd/pa finale", iar ML și Blend sunt motoare SEPARATE
(ADR-051/052), afișate, nu amestecate în probabilitățile Oracle. Monte Carlo e
ieșire proprie; de-vig servește doar calculul de edge.

Deci: xG penalizat -> Poisson -> probabilitatea servită. Tot lanțul.
`match_history.home_xg_pred`/`away_xg_pred` sunt exact intrările acelui pas, iar
rândul `control` din `shadow_predictions` e exact ieșirea.

ANCORA DE FIDELITATE E OBLIGATORIE, NU OPȚIONALĂ
Pasul 1 recalculează `poisson_model(home_xg_pred, away_xg_pred)` și îl compară
cu probabilitățile stocate. Dacă nu se reproduc, premisa de mai sus e falsă și
scriptul SE OPREȘTE — nu raportează cifre construite pe un lanț nedovedit.
Lecția vine din ablația formei (2/460 potriviri), unde premisa echivalentă s-a
dovedit falsă DUPĂ ce rezultatele fuseseră deja interpretate.

CE SE MĂSOARĂ
  A. SENSIBILITATE (fără nicio scurgere temporală, mecanică pură)
     Penalizare de 5/10/20/30% aplicată gazdei / oaspetelui / ambelor.
     Răspunde la: câte predicții se SCHIMBĂ efectiv? Dacă un tăiat de 30% mută
     2% din verdicte, cifra de „30% impact xG" e înșelătoare.

  B. PLAFONUL TEORETIC (foloseste DELIBERAT informația viitoare)
     Oracol perfect: per meci, se alege varianta care minimizează pierderea.
     E un plafon NEATINGIBIL prin construcție — niciun provider nu dă
     informație perfectă. Valoarea lui e asimetrică: un plafon MIC închide
     subiectul definitiv; unul mare nu dovedește că e atins.

  C. PLAFON CU RATĂ REALISTĂ
     Același oracol, dar limitat la o fracțiune din meciuri (implicit 35%) —
     aproximarea proporției reale de meciuri cu absențe notabile. Mai onest
     decât B, tot un plafon.

AVERTISMENT DE CITIRE, SCRIS AICI CA SĂ NU SE PIARDĂ
B și C NU sunt estimări ale câștigului real. Sunt limite superioare. Orice
raportare a lor ca „am câștiga Xpp" e o citire greșită.

Rulare:  python scripts/sensitivity_injury_penalty.py
Fără rețea? NU — citește din Supabase (read-only, nicio scriere).
"""
from __future__ import annotations

import argparse
import math
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.ablation_form_weighting import agrega, mcnemar, scor_per_meci, t_pereche  # noqa: E402

# Pragul de fidelitate: probabilitatile stocate sunt round(x, 4), deci eroarea
# de reproducere trebuie sa fie sub jumatatea ultimei zecimale.
_TOLERANTA_FIDELITATE = 1e-4
# Sub atata potrivire, premisa „servit = Poisson pur" e falsa si ne oprim.
_PRAG_POTRIVIRE = 0.98

_PAGINA = 1000
# Planseul din productie: injury_manager.apply_injury_penalty, linia 264.
_PLANSEU_XG = 0.20


# ════════════════════════════════════════════════════════════════════════
# Citire paginata (lectia de azi: PostgREST taie tacit la 1000)
# ════════════════════════════════════════════════════════════════════════

def _citeste_paginat(client, tabela: str, coloane: str, filtre) -> list[dict]:
    """Paginare keyset pe `id`. NU se reutilizeaza constructorul intre pagini —
    `.range()`/`.gt()` ADAUGA parametri, nu ii inlocuiesc (vezi
    tests/test_pagination_builder_reuse.py)."""
    randuri: list[dict] = []
    cursor = None
    while True:
        q = client.table(tabela).select(coloane)
        q = filtre(q)
        if cursor is not None:
            q = q.gt("id", cursor)
        res = q.order("id").limit(_PAGINA).execute()
        pagina = res.data or []
        randuri.extend(pagina)
        if len(pagina) < _PAGINA:
            return randuri
        cursor = pagina[-1]["id"]


def _incarca(sb) -> list[dict]:
    """Randurile `control` (= predictia SERVITA) alaturate cu xG-ul care le-a
    produs si cu rezultatul real."""
    client = sb.get_client()
    if client is None:
        raise RuntimeError("Supabase indisponibil")

    control = _citeste_paginat(
        client, "shadow_predictions",
        "id,fixture_id,prob_home,prob_draw,prob_away",
        lambda q: q.eq("experiment_group", "control")
                   .eq("processing_stage", "final")
                   .is_("invalidated_at", "null"),
    )
    # Dedup: mai multe experimente scriu rand `control` pentru acelasi meci,
    # cu aceleasi probabilitati (sunt predictia Oracle, nu a experimentului).
    pe_fixture: dict[str, dict] = {}
    for r in control:
        pe_fixture[r["fixture_id"]] = r

    istoric = _citeste_paginat(
        client, "match_history",
        "id,fixture_id,home_xg_pred,away_xg_pred,actual_result,"
        "actual_home_goals,actual_away_goals,league,kickoff_date",
        lambda q: q.not_.is_("actual_result", "null")
                   .not_.is_("home_xg_pred", "null")
                   .not_.is_("away_xg_pred", "null"),
    )

    out = []
    for m in istoric:
        c = pe_fixture.get(m["fixture_id"])
        if not c or not m.get("actual_result"):
            continue
        if m["actual_result"] not in ("H", "D", "A"):
            continue
        out.append({
            "fixture_id": m["fixture_id"],
            "servit": (float(c["prob_home"]), float(c["prob_draw"]), float(c["prob_away"])),
            "home_xg": float(m["home_xg_pred"]),
            "away_xg": float(m["away_xg_pred"]),
            "real": m["actual_result"],
            "goluri_gazda": m.get("actual_home_goals"),
            "goluri_oaspete": m.get("actual_away_goals"),
            "liga": m.get("league"),
            "data": m.get("kickoff_date"),
        })
    return out


# ════════════════════════════════════════════════════════════════════════
# Penalizarea, exact ca in productie
# ════════════════════════════════════════════════════════════════════════

def _penalizeaza(xg: float, procent: float) -> float:
    """`injury_manager.apply_injury_penalty`, linia 264:
        max(xg * (1 + penalty), 0.20)   cu penalty NEGATIV.
    `procent` e pozitiv aici (0.30 = taie 30%), convertit la semnul din cod."""
    if procent <= 0:
        return xg
    return max(xg * (1.0 - procent), _PLANSEU_XG)


def _variante(home_xg: float, away_xg: float, procent: float, poisson) -> dict:
    """Cele trei acțiuni posibile la o magnitudine dată, plus referința."""
    def probs(h, a):
        ph, pd, pa, _ = poisson(h, a)
        return (ph, pd, pa)
    return {
        "nimic":      probs(home_xg, away_xg),
        "gazda":      probs(_penalizeaza(home_xg, procent), away_xg),
        "oaspete":    probs(home_xg, _penalizeaza(away_xg, procent)),
        "ambele":     probs(_penalizeaza(home_xg, procent), _penalizeaza(away_xg, procent)),
    }


def _argmax(p: tuple[float, float, float]) -> str:
    return ("H", "D", "A")[max(range(3), key=lambda k: p[k])]


# ════════════════════════════════════════════════════════════════════════
# Pasul 1 — ANCORA DE FIDELITATE
# ════════════════════════════════════════════════════════════════════════

def ancora_fidelitate(date: list[dict], poisson) -> tuple[float, float, int]:
    """Reproduce probabilitatea SERVITA din xG-ul stocat. Intoarce
    (fractiune_potrivita, eroare_maxima, n)."""
    potriviri = 0
    err_max = 0.0
    for d in date:
        ph, pd, pa, _ = poisson(d["home_xg"], d["away_xg"])
        e = max(abs(ph - d["servit"][0]), abs(pd - d["servit"][1]), abs(pa - d["servit"][2]))
        err_max = max(err_max, e)
        if e <= _TOLERANTA_FIDELITATE:
            potriviri += 1
    return potriviri / max(len(date), 1), err_max, len(date)


# ════════════════════════════════════════════════════════════════════════
# main
# ════════════════════════════════════════════════════════════════════════

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rata-realista", type=float, default=0.35,
                    help="fractiunea de meciuri care ar primi penalizare (plafon C)")
    args = ap.parse_args()

    import supabase_client as sb
    from feature_engine import poisson_model

    if not sb.is_available():
        print("Supabase indisponibil — nimic de masurat.")
        return 1

    cfg = sb.load_config({"max_goals_poisson": 8})
    max_goals = int(cfg.get("max_goals_poisson", 8))
    poisson = lambda h, a: poisson_model(h, a, max_goals=max_goals)  # noqa: E731

    print("=" * 78)
    print("  CALEA 0 — plafonul penalizarii de accidentari")
    print("=" * 78)

    date = _incarca(sb)
    print(f"\n{len(date)} meciuri cu predictie servita + xG + rezultat real.")
    if len(date) < 100:
        print("Prea putine pentru orice concluzie. Ma opresc.")
        return 1

    # ── PASUL 1: ancora ────────────────────────────────────────────────
    print("\n" + "-" * 78)
    print("  PASUL 1 — ancora de fidelitate (OBLIGATORIE)")
    print("-" * 78)
    frac, err_max, n = ancora_fidelitate(date, poisson)
    print(f"  Probabilitatea servita reprodusa din xG stocat: {frac*100:.2f}% din {n}")
    print(f"  Eroare maxima absoluta: {err_max:.2e}  (toleranta {_TOLERANTA_FIDELITATE:.0e})")
    if frac < _PRAG_POTRIVIRE:
        print(f"\n  ⛔ OPRIRE. Sub {_PRAG_POTRIVIRE*100:.0f}% potrivire, premisa")
        print("     „probabilitatea servita = Poisson pur pe xG-ul stocat\" e FALSA.")
        print("     Orice cifra de mai jos ar fi construita pe un lant nedovedit.")
        print("     De investigat ce ALTCEVA intra in probabilitatea servita.")
        return 1
    print("  ✅ Lantul e reproductibil. Masuratorile de mai jos sunt EXACTE,")
    print("     nu doar valide intern.")

    referinta = [scor_per_meci(d["servit"], d["real"]) for d in date]
    acc_ref, ll_ref, br_ref = agrega(referinta)
    print(f"\n  Referinta (Oracle servit): acuratete {acc_ref:.4f} · "
          f"log-loss {ll_ref:.4f} · Brier {br_ref:.4f}")

    # ── PASUL 2: SENSIBILITATE ─────────────────────────────────────────
    print("\n" + "-" * 78)
    print("  PASUL 2 — SENSIBILITATE: cate predictii se schimba efectiv?")
    print("  (mecanica pura, ZERO informatie din viitor)")
    print("-" * 78)
    print(f"  {'penaliz.':>9} {'tinta':>9} {'verdicte mutate':>16} {'acuratete':>10} "
          f"{'log-loss':>9} {'Brier':>8}")
    for procent in (0.05, 0.10, 0.20, 0.30):
        for tinta in ("gazda", "oaspete", "ambele"):
            scoruri, mutate = [], 0
            for d in date:
                v = _variante(d["home_xg"], d["away_xg"], procent, poisson)
                if _argmax(v[tinta]) != _argmax(v["nimic"]):
                    mutate += 1
                scoruri.append(scor_per_meci(v[tinta], d["real"]))
            acc, ll, br = agrega(scoruri)
            print(f"  {procent*100:>7.0f}% {tinta:>9} {mutate:>8} ({mutate/len(date)*100:>4.1f}%) "
                  f"{acc:>10.4f} {ll:>9.4f} {br:>8.4f}")

    print("\n  Citire: aplicarea penalizarii pe TOATE meciurile e nerealista —")
    print("  coloana conteaza doar ca masura de sensibilitate. Daca „verdicte")
    print("  mutate\" e mic, cifra de 30% impact xG promite mai mult decat poate.")

    # ── PASUL 3: PLAFONUL TEORETIC ─────────────────────────────────────
    print("\n" + "-" * 78)
    print("  PASUL 3 — PLAFON TEORETIC (oracol perfect, FOLOSESTE VIITORUL)")
    print("-" * 78)
    print("  NU e o estimare a castigului. E limita superioara a ORICARUI")
    print("  ajustaj de forma asta, cu informatie perfecta despre absente.")
    print(f"\n  {'penaliz.':>9} {'acuratete':>10} {'delta':>8} {'log-loss':>9} {'delta':>9} "
          f"{'Brier':>8} {'delta':>9}")

    plafoane: dict[float, list] = {}
    for procent in (0.05, 0.10, 0.20, 0.30):
        cele_mai_bune = []
        for d in date:
            v = _variante(d["home_xg"], d["away_xg"], procent, poisson)
            # Oracol pe log-loss (metrica proprie, continua — nu acuratetea,
            # care e binara si ar supraestima prin noroc de granita).
            best = min(v.values(), key=lambda p: scor_per_meci(p, d["real"])[1])
            cele_mai_bune.append(scor_per_meci(best, d["real"]))
        plafoane[procent] = cele_mai_bune
        acc, ll, br = agrega(cele_mai_bune)
        print(f"  {procent*100:>7.0f}% {acc:>10.4f} {acc-acc_ref:>+8.4f} "
              f"{ll:>9.4f} {ll-ll_ref:>+9.4f} {br:>8.4f} {br-br_ref:>+9.4f}")

    # ── PASUL 4: PLAFON CU RATA REALISTA ───────────────────────────────
    rata = max(0.0, min(1.0, args.rata_realista))
    k = int(len(date) * rata)
    print("\n" + "-" * 78)
    print(f"  PASUL 4 — PLAFON la rata realista: doar {rata*100:.0f}% din meciuri "
          f"primesc penalizare ({k} din {len(date)})")
    print("-" * 78)
    print("  Se aleg meciurile cu cel mai mare castig potential — tot plafon,")
    print("  dar mai apropiat de o lume in care doar unele echipe au absente.")
    print(f"\n  {'penaliz.':>9} {'acuratete':>10} {'delta':>8} {'log-loss':>9} {'delta':>9} "
          f"{'McNemar b/c':>14} {'chi2':>7}")

    for procent in (0.10, 0.20, 0.30):
        castiguri = []
        for i, d in enumerate(date):
            v = _variante(d["home_xg"], d["away_xg"], procent, poisson)
            best = min(v.values(), key=lambda p: scor_per_meci(p, d["real"])[1])
            s_best = scor_per_meci(best, d["real"])
            castiguri.append((referinta[i][1] - s_best[1], i, s_best))
        castiguri.sort(key=lambda x: x[0], reverse=True)
        alese = {i for _, i, _ in castiguri[:k]}
        scor_prin_index = {i: s for _, i, s in castiguri}
        varianta = [scor_prin_index[i] if i in alese else referinta[i]
                    for i in range(len(date))]
        acc, ll, br = agrega(varianta)
        b, c, chi = mcnemar(varianta, referinta)
        print(f"  {procent*100:>7.0f}% {acc:>10.4f} {acc-acc_ref:>+8.4f} "
              f"{ll:>9.4f} {ll-ll_ref:>+9.4f} {b:>6}/{c:<7} {chi:>7.2f}")

    # ── CONCLUZIE ──────────────────────────────────────────────────────
    acc_plafon_30, ll_plafon_30, _ = agrega(plafoane[0.30])
    print("\n" + "=" * 78)
    print("  CE SE POATE SPUNE, SI CE NU")
    print("=" * 78)
    print(f"  Plafon absolut (oracol perfect, 30%): acuratete {acc_ref:.4f} -> "
          f"{acc_plafon_30:.4f} ({acc_plafon_30-acc_ref:+.4f})")
    print(f"                                        log-loss {ll_ref:.4f} -> "
          f"{ll_plafon_30:.4f} ({ll_plafon_30-ll_ref:+.4f})")
    print()
    print("  Plafonul e NEATINGIBIL: presupune ca stim perfect, inainte de meci,")
    print("  care echipa va fi afectata si cu cat. Niciun provider nu da asta.")
    print("  Valoarea lui e asimetrica — un plafon MIC inchide subiectul;")
    print("  unul mare NU dovedeste ca e atins.")
    print()
    print("  Reper extern, masurat separat pe 986 de meciuri: Oracle 0,4939 vs.")
    print("  favoritul casei de pariuri 0,5233 — decalaj de 2,94pp. Daca plafonul")
    print("  de sus nu acopera 2,94pp, accidentarile NU pot explica singure")
    print("  decalajul fata de piata.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
