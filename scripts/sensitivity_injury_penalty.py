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

LANȚUL E REPRODUCTIBIL — DAR NU CONTRA PREDICȚIEI SERVITE

    oracle_engine.py:1869   ph, pd, pa, _ = self._poisson_model(home_xg, away_xg)
    oracle_engine.py:1946   prob_home_win=round(ph, 4), prob_draw=round(pd, 4), ...

Oracle NU blendează: comentariul din cod o spune explicit — „rb_ph/rb_pd/rb_pa
sunt identice cu ph/pd/pa finale", iar ML și Blend sunt motoare SEPARATE
(ADR-051/052), afișate, nu amestecate în probabilitățile Oracle. Monte Carlo e
ieșire proprie; de-vig servește doar calculul de edge. Deci xG -> Poisson ->
probabilitate e tot lanțul.

**[CORECTAT 2026-10-14, de ancora acestui script]** Prima versiune ancora contra
rândului `control` din `shadow_predictions` (= predicția SERVITĂ) și a eșuat:
**26,98% potrivire, eroare maximă 0,710.** Scriptul s-a oprit, exact cum
trebuia, fără să producă nicio cifră.

Cauza, găsită după: `home_xg_pred`/`away_xg_pred` sunt înghețate prin
`COALESCE(m.existent, p->nou)` (migrarea 008, linii 71-72, reconfirmat în 026 și
036) — **exact ca `prob_*_pred`**. Deci xG-ul și probabilitățile din
`match_history` formează o pereche ÎNGHEȚATĂ CONSISTENTĂ, scrisă la prima
atingere a meciului (batch-ul ADR-056, până la 7 zile înainte). Rândul `control`,
în schimb, se împrospătează în fiecare noapte prin `upsert`.

Dovada numerică a identificării: **268** de meciuri au `control` identic cu
`match_history.prob_home_pred`, iar **269** reproduc prin Poisson. Aceeași
populație — cele la care nimic nu s-a schimbat între prima și ultima scriere.

E ACEEAȘI CLASĂ CA ADR-072, într-un loc nou. Acolo era `prob_*_pred` înghețat
contra Challenger-ului proaspăt; aici e perechea (xG, probabilitate) înghețată
contra predicției servite. Și e a doua confirmare, independentă, a lui D-2:
fără intrări persistate SINCRON cu ieșirile, nici măcar măsurarea nu se poate
face contra a ce vede utilizatorul.

CE SE MĂSOARĂ DECI, ȘI CE SE PIERDE
Ancora țintește perechea înghețată: `poisson_model(home_xg_pred, away_xg_pred)`
contra `match_history.prob_*_pred`. Internă, exactă, pe toate meciurile.

Se pierde: nivelul ABSOLUT al acurateței de referință e cel înghețat (~0,4679
măsurat în ADR-072), nu cel servit (~0,5107) — deci cu ~4,3pp pesimist.
NU se pierde: **deltele**, care sunt singurul lucru ce contează aici.
Sensibilitatea unei distribuții Poisson la un tăiat de 30% din xG nu depinde de
instantaneul din care provine xG-ul, iar rezultatele meciurilor sunt reale.

ANCORA E OBLIGATORIE ȘI OPREȘTE SCRIPTUL
Lecția vine din ablația formei (2/460 potriviri), unde premisa echivalentă s-a
dovedit falsă DUPĂ ce rezultatele fuseseră deja interpretate. Azi a prins o
premisă greșită a mea ÎNAINTE de orice cifră — a doua oară în aceeași zi când
o verificare scrisă înainte de măsurătoare a prevenit un raport fals.

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
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# `mcnemar` si `t_pereche` NU se importa deliberat: niciun test de semnificatie
# nu se aplica unui oracol care, prin construcție, nu poate pierde un meci pe
# care il cistiga (vezi explicatia tiparita la Pasul 4). Un import nefolosit ar
# sugera ca testul exista si doar nu s-a afisat.
from scripts.ablation_form_weighting import agrega, scor_per_meci  # noqa: E402

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
        "id,fixture_id,home_xg_pred,away_xg_pred,"
        "prob_home_pred,prob_draw_pred,prob_away_pred,actual_result,"
        "actual_home_goals,actual_away_goals,league,kickoff_date",
        lambda q: q.not_.is_("actual_result", "null")
                   .not_.is_("home_xg_pred", "null")
                   .not_.is_("away_xg_pred", "null")
                   .not_.is_("prob_home_pred", "null"),
    )

    out = []
    for m in istoric:
        if m.get("actual_result") not in ("H", "D", "A"):
            continue
        c = pe_fixture.get(m["fixture_id"])
        out.append({
            "fixture_id": m["fixture_id"],
            # Reperul ANCORAT: perechea ÎNGHEȚATĂ, consistenta cu xG-ul stocat.
            "inghetat": (float(m["prob_home_pred"]), float(m["prob_draw_pred"]),
                         float(m["prob_away_pred"])),
            # Predictia SERVITA, doar ca sa putem raporta cat de mult divergeaza.
            # Lipsa ei nu invalideaza nimic — nu e reperul.
            "servit": ((float(c["prob_home"]), float(c["prob_draw"]), float(c["prob_away"]))
                       if c else None),
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

def ancora_fidelitate(date: list[dict], poisson, cheie: str) -> tuple[float, float, int]:
    """Reproduce probabilitatea stocata sub `cheie` din xG-ul stocat. Intoarce
    (fractiune_potrivita, eroare_maxima, n_comparabile).

    `cheie='inghetat'` e reperul real (pereche consistenta cu xG-ul).
    `cheie='servit'` se raporteaza doar ca diagnostic al divergentei."""
    potriviri = 0
    err_max = 0.0
    n = 0
    for d in date:
        ref = d.get(cheie)
        if ref is None:
            continue
        n += 1
        ph, pd, pa, _ = poisson(d["home_xg"], d["away_xg"])
        e = max(abs(ph - ref[0]), abs(pd - ref[1]), abs(pa - ref[2]))
        err_max = max(err_max, e)
        if e <= _TOLERANTA_FIDELITATE:
            potriviri += 1
    return potriviri / max(n, 1), err_max, n


# ════════════════════════════════════════════════════════════════════════
# main
# ════════════════════════════════════════════════════════════════════════

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rata-realista", type=float, default=0.35,
                    help="fractiunea de meciuri care ar primi penalizare (plafon C)")
    ap.add_argument("--permutari", type=int, default=20,
                    help="cate permutari pentru oracolul nul (Pasul 5)")
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
    frac_i, err_i, n_i = ancora_fidelitate(date, poisson, "inghetat")
    frac_s, err_s, n_s = ancora_fidelitate(date, poisson, "servit")
    print(f"  Reper ANCORAT — `match_history.prob_*_pred` (pereche inghetata, "
          f"consistenta cu xG-ul stocat):")
    print(f"    reprodus din xG: {frac_i*100:6.2f}% din {n_i}   "
          f"eroare max {err_i:.2e}  (toleranta {_TOLERANTA_FIDELITATE:.0e})")
    print(f"  Diagnostic — randul `control` (predictia SERVITA, improspatata nocturn):")
    print(f"    reprodus din xG: {frac_s*100:6.2f}% din {n_s}   eroare max {err_s:.2e}")
    print(f"\n  Divergenta dintre cele doua e ADR-072 intr-un loc nou: xG-ul si")
    print(f"  probabilitatile din match_history sunt inghetate IMPREUNA")
    print(f"  (COALESCE, migrarea 008), iar predictia servita se improspateaza.")

    if frac_i < _PRAG_POTRIVIRE:
        print(f"\n  ⛔ OPRIRE. Sub {_PRAG_POTRIVIRE*100:.0f}% potrivire pe reperul")
        print("     INGHETAT, premisa „probabilitate = Poisson pur pe xG-ul stocat\"")
        print("     e falsa chiar si pentru perechea consistenta. Orice cifra de mai")
        print("     jos ar fi construita pe un lant nedovedit. De investigat ce")
        print("     ALTCEVA intra in probabilitate.")
        return 1
    print("\n  ✅ Lantul e reproductibil pe reperul inghetat. Sensibilitatea si")
    print("     plafoanele de mai jos sunt EXACTE pe acel instantaneu.")
    print("     LIMITA, de citit odata cu cifrele: nivelul ABSOLUT al acuratetei")
    print("     de referinta e cel inghetat (~0,4679 masurat in ADR-072), cu ~4,3pp")
    print("     mai pesimist decat cel servit (~0,5107). DELTELE se transfera —")
    print("     sensibilitatea unei Poisson la un taiat de xG nu depinde de")
    print("     instantaneul din care vine xG-ul, iar rezultatele sunt reale.")

    referinta = [scor_per_meci(d["inghetat"], d["real"]) for d in date]
    acc_ref, ll_ref, br_ref = agrega(referinta)
    print(f"\n  Referinta (Oracle INGHETAT): acuratete {acc_ref:.4f} · "
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
    print("\n  NICIUN test de semnificatie nu se aplica aici, si merita spus de ce:")
    print("  oracolul alege doar variante cel puțin la fel de bune ca referinta,")
    print("  deci NU poate pierde un meci pe care il cistiga. In McNemar, `b`")
    print("  (referinta a nimerit si varianta nu) iese mereu 0 prin CONSTRUCTIE,")
    print("  iar chi2 devine o cifra mare care nu testeaza nimic. Prima versiune")
    print("  a acestui script o tiparea — era inselatoare, a fost scoasa.")
    print(f"\n  {'penaliz.':>9} {'acuratete':>10} {'delta':>8} {'log-loss':>9} {'delta':>9}")

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
        print(f"  {procent*100:>7.0f}% {acc:>10.4f} {acc-acc_ref:>+8.4f} "
              f"{ll:>9.4f} {ll-ll_ref:>+9.4f}")

    # ── PASUL 5: ORACOLUL NUL ──────────────────────────────────────────
    print("\n" + "-" * 78)
    print("  PASUL 5 — ORACOLUL NUL: cat din plafon e PUR ZGOMOT exploatat?")
    print("-" * 78)
    print("  Acelasi oracol, pe rezultate PERMUTATE aleator. Relatia xG<->rezultat")
    print("  e rupta, deci orice castig ramas e strict capacitatea de")
    print("  supraInvatare a unei alegeri 4-ale cu informatie din viitor.")
    print("  Plafonul CORECTAT = plafonul real − castigul pe zgomot.")
    print()
    print("  Fara aceasta masuratoare, plafonul de la Pasii 3-4 e necitibil:")
    print("  nu s-ar sti cat din el e semnal si cat e artefact de potrivire.")

    rng = random.Random(20261014)   # sămânță fixă — reproductibil (regula ML)
    n_perm = args.permutari

    # Probabilitatile NU depind de rezultat, deci se precalculeaza o data si
    # se refolosesc la toate permutarile. Fara asta, pasul ar fi de n_perm ori
    # mai scump degeaba.
    print(f"\n  Precalculez variantele pentru {len(date)} meciuri...")
    cache: dict[float, list[list[tuple]]] = {}
    for procent in (0.05, 0.10, 0.20, 0.30):
        cache[procent] = [list(_variante(d["home_xg"], d["away_xg"], procent, poisson).values())
                          for d in date]

    reale = [d["real"] for d in date]
    print(f"  Rulez {n_perm} permutari...\n")
    print(f"  {'penaliz.':>9} {'plafon real':>12} {'zgomot mediu':>13} {'±sd':>7} "
          f"{'PLAFON CORECTAT':>16}")

    for procent in (0.05, 0.10, 0.20, 0.30):
        variante_meci = cache[procent]
        # Plafonul real, recalculat din cache — trebuie sa iasa IDENTIC cu
        # Pasul 3; daca nu, cache-ul e greșit si s-ar vedea imediat.
        best_real = [min(variante_meci[i], key=lambda p: scor_per_meci(p, reale[i])[1])
                     for i in range(len(date))]
        real_acc = agrega([scor_per_meci(best_real[i], reale[i])
                           for i in range(len(date))])[0]

        nule = []
        for _ in range(n_perm):
            amestecate = reale[:]
            rng.shuffle(amestecate)
            ref_nul = [scor_per_meci(date[i]["inghetat"], amestecate[i])
                       for i in range(len(date))]
            acc_ref_nul = agrega(ref_nul)[0]
            best_nul = []
            for i in range(len(date)):
                b = min(variante_meci[i], key=lambda p: scor_per_meci(p, amestecate[i])[1])
                best_nul.append(scor_per_meci(b, amestecate[i]))
            nule.append(agrega(best_nul)[0] - acc_ref_nul)

        zgomot = sum(nule) / len(nule)
        sd = statistics.stdev(nule) if len(nule) > 1 else 0.0
        delta_real = real_acc - acc_ref
        print(f"  {procent*100:>7.0f}% {delta_real:>+12.4f} {zgomot:>+13.4f} {sd:>7.4f} "
              f"{delta_real - zgomot:>+16.4f}")

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
