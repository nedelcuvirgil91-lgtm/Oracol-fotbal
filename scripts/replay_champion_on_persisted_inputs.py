"""Relurea campionului promovat pe intrările de la servire persistate (ADR-073).
STRICT READ-ONLY.

CLASA ACESTUI SCRIPT, și de ce NU e un POC (corectat 2026-10-27, după ce
`tests/test_poc_isolation.py` garda 4 a prins eroarea): l-am numit întâi
`_poc_replay_champion_temp.py`, iar garda a căzut corect. În proiectul ăsta
`_poc_*` denumește o clasă precisă — validarea unei surse sau chei EXTERNE noi,
care n-are voie să atingă baza, și căreia niciun workflow nu-i dă credențiale
(CLAUDE.md §chei API, aplicat de 5 ori). Scriptul de aici e opusul: o analiză a
datelor NOASTRE, care fără credențiale nu are ce măsura — clasa
`scripts/ablation_form_weighting.py` și `scripts/sensitivity_injury_penalty.py`,
care stau pe `main` cu o gardă dedicată de read-only.

Numele vechi afirma o categorie din care nu face parte. Garda n-a dat un fals
pozitiv; a prins o eroare de încadrare. Nu se păstrează ca POC temporar și nu
se șterge după rulare: devine instrumentul cu care se validează banda nouă din
P6.0-a (replay-ul e martorul contra căruia scriitorul nou trebuie să se
potrivească).

ÎNTREBAREA (P6, Pasul 2): campionul `blend_v1/8ac89c70`, promovat pe 23 august
și ÎNGHEȚAT de atunci, mai e mai bun decât Oracle-ul servit AZI?

ÎNTREBAREA (P6, Pasul 2): campionul `blend_v1/8ac89c70`, promovat pe 23 august
și ÎNGHEȚAT de atunci, mai e mai bun decât Oracle-ul servit AZI?

Nu se poate răspunde din date existente: rândurile lui de shadow se opresc pe
23 august, cu 13 minute înainte de promovare (394 control + 394 treatment, zero
în 65 de zile — `log_shadow_for_active_challenger` nu loghează decât pentru un
Challenger ACTIV, iar un model promovat nu mai e Challenger). Dar ADR-073
persistă, din 15 octombrie, intrările exacte de la servire — deci predicția lui
se poate RECONSTRUI offline, pe 332 de meciuri deja terminate.

════════════════════════════════════════════════════════════════════════════
CE CITEȘTE (tot, exhaustiv) — și NU SCRIE NIMIC
════════════════════════════════════════════════════════════════════════════
  · `shadow_predictions`  — rânduri `control` cu `feature_metadata.schema_version`
                            (dau `oracle_probs` + `ml_features`) și rânduri
                            `treatment` ale martorului (dau probabilitățile
                            logate live, cu care se compară relurea)
  · `match_history`       — DOAR `fixture_id, kickoff_date, actual_result`
  · `training_runs`       — prin `sb.get_training_run()`, pentru `samples_used`
  · Supabase Storage, bucket `model-artifacts` — artefactele `.json`, descărcate
                            într-un `TemporaryDirectory` auto-curățat

  ZERO scrieri: niciun `insert`/`update`/`upsert`, nicio migrare, niciun flag
  atins, nimic în `model_champions`/`decision_feed`/`automation_runs`. Nu
  importă `oracle_engine` (construcția lui rezolvă campioni, încarcă cache și
  loghează), nu atinge `cache_manager`, nu scrie pe disc în afara stdout.

════════════════════════════════════════════════════════════════════════════
DE CE TREI FAZE, ȘI DE CE FAZA 1 ESTE O POARTĂ
════════════════════════════════════════════════════════════════════════════
Faza 2 produce cifra care ne interesează. Dar o cifră dintr-o relure
nevalidată e o corelație, nu o măsurătoare — exact greșeala pe care sonda SFI
a arătat-o săptămâna asta: fără martor de control, primul rezultat plauzibil
pare o confirmare.

Martorul există și e exact: Challengerul ACTIV `blend_v1/174e7e17` are, pe
ACELEAȘI meciuri, rânduri `treatment` logate LIVE *și* înregistrarea ADR-073 pe
rândul `control`. Deci relurea lui trebuie să reproducă ce s-a logat atunci. Nu
reproduce ⇒ metoda e greșită, iar Faza 2 NU se execută. Niciun rezultat
„parțial" nu se raportează ca atare.

PRECONDIȚIE VERIFICATĂ ÎNAINTE (SQL, read-only, 2026-10-27): pe toate cele 512
meciuri comune, rândul `control` e IDENTIC între `blend_v1` și `xgboost_v1` —
0 probabilități diferite, 0 `ml_features` diferite, divergență maximă 0,0e-10.
De asta relurea campionului poate folosi rândul `control` al martorului:
`control` e Oracle-ul servit, nu o proprietate a familiei. Faza 0 reverifică
asta pe exact rândurile citite, ca precondiția să nu rămână o notă de istoric.

NOTĂ despre o ambiguitate deja documentată (ADR-073 D2): `ml_features`
conține `home_xg_pred`/`away_xg_pred`, care înseamnă lucruri diferite după
apelant (pre- vs post-penalizare de accidentări). IRELEVANT aici: niciunul
dintre cele două nu e în `FEATURE_COLUMNS`, deci nu intră în predicție.
Verificat, nu presupus — Faza 0 listează cheile folosite efectiv.

════════════════════════════════════════════════════════════════════════════
Read-only impus, nu promis: `tests/test_replay_champion_readonly.py`.
════════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

# Rulat ca `python scripts/replay_champion_on_persisted_inputs.py`, `sys.path[0]`
# e `scripts/`, nu rădăcina — deci `import supabase_client` cade cu
# ModuleNotFoundError. Idiomul de mai jos e cel folosit de toate celelalte
# scripturi din folder (`ablation_*`, `check_*`, `analyze_*`, `audit_*`).
# Prima rulare (40517516913) a eșuat în 0 secunde exact pe asta.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

MARTOR = "174e7e17-347e-498e-912f-893a855f742b"   # Challenger blend_v1 ACTIV
CAMPION = "8ac89c70-8727-459f-aa42-08a2edd16431"  # campionul promovat 23 aug
FAMILIE = "blend_v1"

# Poarta Fazei 1. Generoasă deliberat (acoperă drumul float -> JSON -> numeric
# -> float), dar divergența REALĂ se raportează mereu: dacă iese 1e-15 știm că
# e identic bit cu bit, iar dacă iese 1e-3 știm că e ceva în neregulă chiar
# dacă poarta ar trece.
TOLERANTA = 1e-6

_PAGINA = 1000
_REZULTATE = ("H", "D", "A")


# ── Citiri paginate (plafonul PostgREST de 1000 — a cincea instanță a fost
#    reparată azi în `get_champion_served_outcomes`; nu mai scriem cod nou care
#    să calce pe ea) ──────────────────────────────────────────────────────────

def _citeste_tot(client, tabela: str, coloane: str, filtre) -> list[dict]:
    randuri: list[dict] = []
    cursor = None
    while True:
        q = client.table(tabela).select(coloane)
        q = filtre(q)
        if cursor is not None:
            q = q.gt("id", cursor)
        pagina = (q.order("id").limit(_PAGINA).execute()).data or []
        randuri.extend(pagina)
        if len(pagina) < _PAGINA:
            return randuri
        cursor = pagina[-1]["id"]


def _shadow(client, versiune: str, grup: str) -> list[dict]:
    return _citeste_tot(
        client, "shadow_predictions",
        "id,fixture_id,prob_home,prob_draw,prob_away,feature_metadata",
        lambda q: (q.eq("experiment_name", FAMILIE)
                    .eq("experiment_version", versiune)
                    .eq("experiment_group", grup)
                    .eq("processing_stage", "final")),
    )


def _rezultate(client, fixture_ids: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for i in range(0, len(fixture_ids), 500):
        bucata = fixture_ids[i:i + 500]
        for r in _citeste_tot(
            client, "match_history", "id,fixture_id,kickoff_date,actual_result",
            lambda q, b=bucata: q.in_("fixture_id", b),
        ):
            out[r["fixture_id"]] = r
    return out


# ── Statistică (fără scipy — t pereche calculat explicit, ca în restul
#    proiectului) ────────────────────────────────────────────────────────────

def _brier(ph, pd_, pa, o) -> float:
    t = {"H": (1, 0, 0), "D": (0, 1, 0), "A": (0, 0, 1)}[o]
    return (ph - t[0]) ** 2 + (pd_ - t[1]) ** 2 + (pa - t[2]) ** 2


def _logloss(ph, pd_, pa, o) -> float:
    return -math.log(max({"H": ph, "D": pd_, "A": pa}[o], 1e-12))


def _corect(ph, pd_, pa, o) -> float:
    prezis = _REZULTATE[max(range(3), key=lambda i: (ph, pd_, pa)[i])]
    return 1.0 if prezis == o else 0.0


def _t_pereche(dif: list[float]) -> float | None:
    """t pe diferențele (oracle − campion). Semnul se interpretează la
    raportare, per metrică — nu aici (lecția panoului de verdict: acuratețea
    vrea mai mare, Brier/log-loss vor mai mic)."""
    n = len(dif)
    if n < 2:
        return None
    m = sum(dif) / n
    var = sum((x - m) ** 2 for x in dif) / (n - 1)
    # `var <= 0` NU e suficient, și asta a fost prins de propria gardă înainte
    # ca scriptul să ruleze o dată: pe diferențe identice, aritmetica float dă
    # ~1e-33, nu exact 0, deci poarta nu se declanșa și `t` ieșea 1,02e16 —
    # certitudine absolută dintr-un eșantion care n-are nicio dispersie de
    # măsurat. Pragul e RELATIV la scara diferențelor, nu absolut: un prag fix
    # ar respinge un eșantion real cu diferențe mici, legitime.
    sd = math.sqrt(var)
    if sd <= 1e-12 * max(1.0, abs(m)):
        return None
    return m / (sd / math.sqrt(n))


def _metrici(pereche: list[tuple]) -> dict:
    """`pereche`: [(oracle_probs, model_probs, rezultat), ...]"""
    br_o, br_m, ll_o, ll_m, ac_o, ac_m = [], [], [], [], [], []
    for (oh, od, oa), (mh, md, ma), o in pereche:
        br_o.append(_brier(oh, od, oa, o)); br_m.append(_brier(mh, md, ma, o))
        ll_o.append(_logloss(oh, od, oa, o)); ll_m.append(_logloss(mh, md, ma, o))
        ac_o.append(_corect(oh, od, oa, o)); ac_m.append(_corect(mh, md, ma, o))
    n = len(pereche)
    med = lambda v: sum(v) / n
    return {
        "n": n,
        "brier_oracle": med(br_o), "brier_model": med(br_m),
        "brier_t": _t_pereche([a - b for a, b in zip(br_o, br_m)]),
        "logloss_oracle": med(ll_o), "logloss_model": med(ll_m),
        "logloss_t": _t_pereche([a - b for a, b in zip(ll_o, ll_m)]),
        "acc_oracle": med(ac_o), "acc_model": med(ac_m),
        "acc_t": _t_pereche([a - b for a, b in zip(ac_o, ac_m)]),
    }


def _verdict(delta_favorabil: bool, t: float | None) -> str:
    if t is None:
        return "— (nedeterminabil)"
    if abs(t) < 1.96:
        return "❔ incert (|t| < 1,96)"
    return "✅ dovedit mai bun" if delta_favorabil else "❌ dovedit mai slab"


def _memoizeaza_citirile() -> None:
    """`predict_with_blend_challenger` reîncarcă artefactul din Storage la
    FIECARE apel (`load_model_artifact`, fără cache) și recitește rândul din
    `training_runs`. Pentru 512 + 2×332 apeluri asta ar fi ~1176 de descărcări
    — lent și fragil la o rețea care clipește o dată.

    Se memoizează EXCLUSIV cele două citiri, care sunt idempotente prin
    construcție: artefactul e adresat de un `training_run_id` imuabil, iar
    rândul de `training_runs` al unei rulări încheiate nu se mai schimbă.

    Calea de predicție rămâne NEATINSĂ: `predict_with_blend_challenger` e
    apelată exact cum o apelează producția, cu aceeași matematică, același
    `FEATURE_COLUMNS`, aceeași calibrare. Dacă aș fi rescris predicția aici ca
    să evit descărcările, martorul din Faza 1 ar fi validat rescrierea mea, nu
    codul de producție — adică exact opusul scopului lui."""
    from learning_core import calibration_artifact_storage, model_artifact_storage
    import supabase_client as sb

    for modul, nume in ((model_artifact_storage, "load_model_artifact"),
                        (calibration_artifact_storage, "load_calibration_artifact"),
                        (sb, "get_training_run")):
        original = getattr(modul, nume)
        memo: dict = {}

        def inveliti(arg, _o=original, _m=memo):
            if arg not in _m:
                _m[arg] = _o(arg)
            return _m[arg]

        setattr(modul, nume, inveliti)


def main() -> int:
    import supabase_client as sb
    from ml_predictor import FEATURE_COLUMNS
    from learning_core.blend_challenger_shadow import predict_with_blend_challenger

    _memoizeaza_citirile()

    client = sb.get_client()
    if client is None:
        print("OPRIT: Supabase indisponibil (lipsesc credențialele).")
        return 1

    print("=" * 78)
    print("RELURE CAMPION — READ-ONLY. Nimic nu se scrie.")
    print("=" * 78)

    # ── FAZA 0 — precondiții ────────────────────────────────────────────────
    control_martor = _shadow(client, MARTOR, "control")
    control_martor = [r for r in control_martor
                      if (r.get("feature_metadata") or {}).get("schema_version") is not None]
    live_martor = {r["fixture_id"]: r for r in _shadow(client, MARTOR, "treatment")}

    print(f"\n### FAZA 0 — precondiții")
    print(f"  rânduri control cu înregistrare ADR-073 : {len(control_martor)}")
    print(f"  rânduri treatment live ale martorului   : {len(live_martor)}")
    if not control_martor:
        print("  OPRIT: nicio înregistrare de la servire — relurea e imposibilă.")
        return 1

    lipsa: dict[str, int] = {}
    for r in control_martor:
        mlf = (r["feature_metadata"] or {}).get("ml_features") or {}
        for c in FEATURE_COLUMNS:
            if c not in mlf:
                lipsa[c] = lipsa.get(c, 0) + 1
    print(f"  FEATURE_COLUMNS cerute ({len(FEATURE_COLUMNS)}): toate prezente? "
          f"{'DA' if not lipsa else 'NU → ' + str(lipsa)}")
    if lipsa:
        print("  OPRIT: o cheie lipsă devine NaN, apoi 0.0 — ar produce cifre")
        print("         plauzibile și false, exact ce încercăm să evităm.")
        return 1

    # Precondiția „control e Oracle-ul servit, nu o proprietate a familiei",
    # reverificată pe rândurile chiar citite, nu doar în istoricul analizei.
    ctrl_x = {r["fixture_id"]: r for r in _citeste_tot(
        client, "shadow_predictions",
        "id,fixture_id,prob_home,prob_draw,prob_away",
        lambda q: (q.eq("experiment_name", "xgboost_v1")
                    .eq("experiment_group", "control")
                    .eq("processing_stage", "final")),
    )}
    div, comune = 0.0, 0
    for r in control_martor:
        alt = ctrl_x.get(r["fixture_id"])
        if alt is None:
            continue
        comune += 1
        div = max(div, abs(float(r["prob_home"]) - float(alt["prob_home"])))
    print(f"  control identic între familii: {comune} meciuri comune, "
          f"divergență maximă P(1) = {div:.2e}")
    if div > TOLERANTA:
        print("  OPRIT: rândul `control` DIFERĂ între familii — nu mai e Oracle-ul")
        print("         servit, deci nu poate ține locul celui absent al campionului.")
        return 1

    rez = _rezultate(client, [r["fixture_id"] for r in control_martor])
    terminate = [r for r in control_martor
                 if (rez.get(r["fixture_id"]) or {}).get("actual_result") in _REZULTATE]
    print(f"  din care meciuri TERMINATE (scorabile)  : {len(terminate)}")

    # ── FAZA 1 — martor de control: relurea reproduce ce s-a logat live? ────
    print(f"\n### FAZA 1 — martor de control ({FAMILIE}/{MARTOR[:8]}, Challenger ACTIV)")
    print("  Relurea trebuie să reproducă probabilitățile logate LIVE.")
    difs, reluate, fara_live, esuate = [], 0, 0, 0
    for r in control_martor:
        viu = live_martor.get(r["fixture_id"])
        if viu is None:
            fara_live += 1
            continue
        probs = predict_with_blend_challenger(
            oracle_probs=(float(r["prob_home"]), float(r["prob_draw"]), float(r["prob_away"])),
            features=(r["feature_metadata"] or {}).get("ml_features") or {},
            training_run_id=MARTOR,
        )
        if probs is None:
            esuate += 1
            continue
        reluate += 1
        difs.append(max(abs(probs[0] - float(viu["prob_home"])),
                        abs(probs[1] - float(viu["prob_draw"])),
                        abs(probs[2] - float(viu["prob_away"]))))

    print(f"  reluate: {reluate} · fără rând live: {fara_live} · relure eșuată: {esuate}")
    if esuate and not reluate:
        print("  OPRIT: nicio relure n-a reușit — artefact absent din bucket sau")
        print("         `predict_with_blend_challenger` a eșuat. NU se trage nicio")
        print("         concluzie despre campion.")
        return 1
    if not difs:
        print("  OPRIT: niciun meci cu martor — Faza 2 n-ar putea fi validată.")
        return 1

    print(f"  divergență maximă : {max(difs):.3e}")
    print(f"  divergență medie  : {sum(difs) / len(difs):.3e}")
    print(f"  peste toleranța {TOLERANTA:.0e}: {sum(1 for d in difs if d > TOLERANTA)} / {len(difs)}")
    if max(difs) > TOLERANTA:
        print("\n  ⛔ POARTA NU TRECE. Metoda de relure nu reproduce ce s-a logat")
        print("     live, deci orice cifră despre campion ar fi un artefact al")
        print("     metodei. FAZA 2 NU SE EXECUTĂ — deliberat.")
        return 2
    print("  ✅ poarta trece — relurea reproduce logarea live.")

    # ── FAZA 2 — campionul, pe meciurile terminate ──────────────────────────
    print(f"\n### FAZA 2 — campionul promovat ({FAMILIE}/{CAMPION[:8]}, înghețat 23 aug)")
    pereche_campion, pereche_martor, esec_c = [], [], 0
    for r in terminate:
        o = rez[r["fixture_id"]]["actual_result"]
        oracle = (float(r["prob_home"]), float(r["prob_draw"]), float(r["prob_away"]))
        mlf = (r["feature_metadata"] or {}).get("ml_features") or {}
        pc = predict_with_blend_challenger(oracle_probs=oracle, features=mlf,
                                            training_run_id=CAMPION)
        if pc is None:
            esec_c += 1
        else:
            pereche_campion.append((oracle, pc, o))
        pm = predict_with_blend_challenger(oracle_probs=oracle, features=mlf,
                                            training_run_id=MARTOR)
        if pm is not None:
            pereche_martor.append((oracle, pm, o))

    if not pereche_campion:
        print(f"  OPRIT: relurea campionului a eșuat pe toate cele {len(terminate)}")
        print("         meciurile (probabil artefactul lui nu mai e în bucket).")
        print("         Constatare în sine, NU un eșec al analizei — de raportat.")
        return 1
    if esec_c:
        print(f"  ATENȚIE: {esec_c} meciuri fără relure reușită — excluse, nu aproximate.")

    for eticheta, p in (("CAMPION  8ac89c70 (înghețat 23 aug)", pereche_campion),
                        ("MARTOR   174e7e17 (Challenger activ)", pereche_martor)):
        if not p:
            continue
        m = _metrici(p)
        print(f"\n  ── {eticheta} · n = {m['n']} ──")
        print(f"    Brier     Oracle {m['brier_oracle']:.4f} | model {m['brier_model']:.4f} "
              f"| t {m['brier_t'] if m['brier_t'] is None else round(m['brier_t'], 2)} "
              f"→ {_verdict(m['brier_model'] < m['brier_oracle'], m['brier_t'])}")
        print(f"    Log-loss  Oracle {m['logloss_oracle']:.4f} | model {m['logloss_model']:.4f} "
              f"| t {m['logloss_t'] if m['logloss_t'] is None else round(m['logloss_t'], 2)} "
              f"→ {_verdict(m['logloss_model'] < m['logloss_oracle'], m['logloss_t'])}")
        print(f"    Acuratețe Oracle {m['acc_oracle']:.4f} | model {m['acc_model']:.4f} "
              f"| t {m['acc_t'] if m['acc_t'] is None else round(m['acc_t'], 2)} "
              f"→ {_verdict(m['acc_model'] > m['acc_oracle'], m['acc_t'])}")

    print("\n" + "=" * 78)
    print("Cifrele de mai sus NU declanșează nimic. Promovarea, retragerea sau")
    print("cablarea unei căi de servire rămân decizii umane explicite (ADR-002).")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
