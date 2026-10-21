"""
================================================================================
FOOTBALL ORACLE — automation_runs.py (ADR-026)
================================================================================
Substratul comun de raportare pentru orice proces autonom — generalizarea
tiparului deja dovedit `sync_status` la scara întregii serii vNext.

Implementează exact contractul înghețat prin ADR-026:
docs/00_GOVERNANCE/ADR-026-automation-runs-decision-feed.md

Două state machine-uri, independente, legate prin run_id:
  - automation_runs: execuție (queued -> running -> completed|failed|skipped)
  - decision_feed:   decizie T3a/T3b (proposed -> pending -> approved|rejected|
                      expired|withdrawn; approved -> committed|commit_failed|
                      orphaned; T3b: flagged -> acknowledged -> resolved)

Regula de escaladare la incertitudine (ADR-026 §Tiering) și regula de
rollback ca precondiție structurală (Blueprint, principiul #9) sunt
responsabilitatea apelantului (fiecare ADR producător) — acest modul impune
doar contractul mecanic (stări, tranziții, idempotency), nu logica de
clasificare pe tier.

Niciun apel din acest modul nu atinge vreodată stare canonică de business
(match_history, model_champions etc.) — exclusiv jurnal + poartă de aprobare,
per Ownership din ADR-026.
================================================================================
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from database.queries import get_client

logger = logging.getLogger("FootballOracle.AutomationRuns")

_OPEN_RUN_STATUSES = ("queued", "running")
_OPEN_DECISION_STATUSES = ("proposed", "pending", "approved")

# ════════════════════════════════════════════════════════════════════════════
# [ADR-079] Felul unei decizii, si de ce are un IMPLICIT
#
# Calea de promovare nu a scris niciodata `decision_kind` in `evidence`, iar
# Faza C compenseaza cu un implicit codat: `evidence.get("decision_kind",
# "promotion")` (`continuous_learning.py`). Confirmat in date: decizia #3,
# promovarea lui 8ac89c70 (23 aug), are campul NULL.
#
# Helper-ul de mai jos trebuie sa cada pe ACELASI implicit ca executantul.
# Daca ar intoarce altceva (ex. „necunoscut"), comparatia de fel si executia ar
# fi de acord pe hartie si in dezacord in fapt — exact clasa D-11, unde ecranul
# spunea una si codul facea alta.
#
# ADR-079 §4.3 repara sursa (calea de promovare scrie felul explicit), dar
# implicitul RAMANE pentru randurile istorice. Ele sunt toate `committed`, deci
# nu mai apar in nicio comparatie — dar un implicit tacit nu se sterge pe
# baza unei presupuneri despre ce exista in baza.
_FEL_DECIZIE_IMPLICIT = "promotion"

# Starile terminale care declanseaza racirea din §3.2: o decizie respinsa de om
# sau expirata de sweep nu se repropune imediat.
_STARI_PENTRU_RACIRE = ("rejected", "expired")

# Identic cu `_T3A_DECISION_TTL_HOURS` din `continuous_learning`, DELIBERAT: o a
# doua constanta de timp ar trebui justificata separat, si nu poate fi.
RACIRE_PROPUNERE_ORE = 168.0

# Cine a rezolvat o decizie prin sweep — distinct de un nume de om, ca o
# expirare automata sa nu arate niciodata ca o decizie umana.
_REZOLVAT_DE_SWEEP = "sweep-adr-026"


def fel_decizie(evidence: Any) -> str:
    """Felul normalizat al unei decizii, din `evidence`.

    Niciodata gol: cade pe `_FEL_DECIZIE_IMPLICIT`, acelasi pe care il
    foloseste Faza C la executie. Vezi comentariul de mai sus."""
    if not isinstance(evidence, dict):
        return _FEL_DECIZIE_IMPLICIT
    fel = str(evidence.get("decision_kind") or "").strip().lower()
    return fel or _FEL_DECIZIE_IMPLICIT


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ════════════════════════════════════════════════════════════════════════════
# automation_runs — execuție
# ════════════════════════════════════════════════════════════════════════════

def write_run(
    producer: str,
    process_type: str,
    tier: str,
    target_key: str | None = None,
) -> int | None:
    """
    Creează o rulare nouă (status='queued'), sau reutilizează una existentă
    dacă un run e deja queued/running pentru aceeași (producer, process_type,
    target_key) — regula de idempotency „reuse" din ADR-026 §Idempotency.

    Returnează run_id-ul (nou sau reutilizat), sau None la eroare de client.
    """
    client = get_client()
    if client is None:
        logger.error("[AutomationRuns] Supabase indisponibil — write_run refuzat")
        return None

    if target_key:
        try:
            existing = (
                client.table("automation_runs")
                .select("id")
                .eq("producer", producer)
                .eq("process_type", process_type)
                .eq("target_key", target_key)
                .in_("status", list(_OPEN_RUN_STATUSES))
                .limit(1)
                .execute()
            )
            if existing.data:
                run_id = existing.data[0]["id"]
                logger.info(
                    "[AutomationRuns] rulare deja in curs pentru %s/%s/%s (run_id=%s) — reutilizata, nicio rulare noua",
                    producer, process_type, target_key, run_id,
                )
                return run_id
        except Exception as exc:
            logger.error("[AutomationRuns] verificare idempotency esuata: %s", exc)
            return None

    try:
        res = (
            client.table("automation_runs")
            .insert({
                "producer":     producer,
                "process_type": process_type,
                "tier":         tier,
                "target_key":   target_key,
                "status":       "queued",
            })
            .execute()
        )
        return res.data[0]["id"] if res.data else None
    except Exception as exc:
        logger.error("[AutomationRuns] write_run esuat: %s", exc)
        return None


def start_run(run_id: int) -> bool:
    """queued -> running."""
    return _transition_run(run_id, {"status": "running", "started_at": _now_iso()})


def complete_run(run_id: int, summary: dict[str, Any] | None = None) -> bool:
    """running -> completed."""
    payload: dict[str, Any] = {"status": "completed", "completed_at": _now_iso()}
    if summary is not None:
        payload["summary"] = summary
    return _transition_run(run_id, payload)


def fail_run(run_id: int, error_detail: str,
             summary: dict[str, Any] | None = None) -> bool:
    """running -> failed.

    `summary` e opțional și implicit `None`, deci apelanții existenți sunt
    neatinși. Există fiindcă altfel defalcarea s-ar pierde exact pe rulările
    unde contează cel mai mult: una eșuată n-ar păstra nimic în afară de
    `error_detail`, iar motivul eșecului s-ar putea citi doar din log — adică
    din sursa care se taie la ~5000 de linii.
    """
    payload: dict[str, Any] = {
        "status": "failed", "completed_at": _now_iso(), "error_detail": error_detail,
    }
    if summary is not None:
        payload["summary"] = summary
    return _transition_run(run_id, payload)


def skip_run(run_id: int, skip_reason: str) -> bool:
    """queued -> skipped. Rezultat legitim (precondiții neîndeplinite sau
    stare identică, nimic de raportat), nu o eroare."""
    return _transition_run(run_id, {
        "status": "skipped", "completed_at": _now_iso(), "skip_reason": skip_reason,
    })


def _transition_run(run_id: int, payload: dict[str, Any]) -> bool:
    client = get_client()
    if client is None:
        return False
    try:
        client.table("automation_runs").update(payload).eq("id", run_id).execute()
        return True
    except Exception as exc:
        logger.error("[AutomationRuns] tranzitie run_id=%s esuata: %s", run_id, exc)
        return False


# ════════════════════════════════════════════════════════════════════════════
# decision_feed — decizie (T3a / T3b)
# ════════════════════════════════════════════════════════════════════════════

def propose_decision(
    run_id: int,
    tier: str,
    rollback_plan: str | None = None,
    evidence: dict[str, Any] | None = None,
    correction_method: str | None = None,
    ttl_hours: float | None = None,
    raport: dict[str, Any] | None = None,
) -> int | None:
    """
    Creează o decizie nouă (status='proposed'), sau actualizează dovada unei
    decizii deja deschise pentru aceeași cheie (regula de idempotency „new
    run, decizie reutilizată" din ADR-026 §Idempotency).

    tier='T3a' necesită rollback_plan (impus și la nivel de schema — vezi
    migrarea 011, constrângerea decision_feed_t3a_requires_rollback).

    [ADR-079] Idempotența NU mai e orbă la felul deciziei. Patru ramuri:

      - există una `approved` → **refuz**, `None`. Ce a aprobat omul e
        înghețat; suprascrierea e calea prin care o aprobare de expirare se
        execută ca promovare de campion (§4.1, contrazice ADR-002).
      - există una `proposed`/`pending` de **alt fel** → se **retrage**
        (`withdraw_decision`) și se creează cea nouă. Un `None` aici ar bloca
        familia permanent — vezi §4.1.1, unde prima mea variantă greșea.
      - există una de **același fel** → se actualizează `evidence`
        (comportamentul dinainte, legitim: împrospătează cifrele).
      - una de același fel a fost `rejected`/`expired` în ultimele
        `RACIRE_PROPUNERE_ORE` → **refuz**, `None` (§3.2, răcire).

    `raport`: dict opțional în care se scrie motivul unui refuz sau al unei
    retrageri, ca apelantul să-l poată pune în `summary`-ul rulării. Fără el,
    un refuz ar fi indistinct de „n-a fost nimic de propus" — adică tăcere,
    exact defectul pe care ADR-057 l-a plătit cu 14 zile.
    """
    if tier == "T3a" and not rollback_plan:
        raise ValueError("propose_decision: T3a necesita rollback_plan (precondiție structurală)")

    client = get_client()
    if client is None:
        logger.error("[AutomationRuns] Supabase indisponibil — propose_decision refuzat")
        return None

    try:
        run = client.table("automation_runs").select("target_key").eq("id", run_id).limit(1).execute()
        target_key = run.data[0]["target_key"] if run.data else None
    except Exception as exc:
        logger.error("[AutomationRuns] citire target_key pentru run_id=%s esuata: %s", run_id, exc)
        target_key = None

    fel_nou = fel_decizie(evidence)

    if target_key:
        try:
            # [ADR-079, Discovery] Interogarea asta NU e paginata. Masurat
            # 2026-10-20: maximul real e 198 de randuri
            # (`production_champion|all`), ~2/zi din 17 iulie — plafonul
            # PostgREST de 1000 e la ~400 de zile. Nu e rupt azi; se va rupe
            # tacit, si atunci idempotenta ar rata deciziile al caror `run_id`
            # nu intra in prima pagina. Lasat NEREPARAT deliberat: e o
            # descoperire in afara scopului ADR-079, de decis separat
            # (Discovery Rule), nu o largire tacita.
            sibling_runs = (
                client.table("automation_runs")
                .select("id")
                .eq("target_key", target_key)
                .execute()
            )
            sibling_run_ids = [r["id"] for r in (sibling_runs.data or [])]

            # ── ORDINEA de aici e deliberata, si e sigura doar prin invariantul
            # „cel mult o decizie DESCHISA per target" (pe care chiar functia
            # asta il impune). Racirea se verifica INAINTEA deciziei deschise.
            #
            # Intrebarea evidenta: n-ar putea racirea sa refuze improspatarea
            # unei propuneri deschise de acelasi fel? Ar insemna sa coexiste o
            # deschisa si una respinsa recent, pe acelasi target si acelasi fel.
            # NU se poate: cat timp una e deschisa, idempotenta o returneaza in
            # loc sa creeze alta, deci nu exista a doua care sa fie respinsa.
            # Dupa respingere, racirea blocheaza crearea celei noi — exact ce
            # vrem. Verificat prin test (`test_cel_mult_o_decizie_deschisa...`).
            #
            # Daca invariantul s-ar rupe vreodata (insert manual, producator
            # care ocoleste functia), consecinta e BENIGNA si acum VIZIBILA: o
            # propunere deschisa ar afisa cifre neimprospatate, iar D-11 pune
            # cifrele in titlu, deci vechimea se vede.
            #
            # ── §3.2 — racire: o decizie de ACELASI fel, respinsa de om sau
            # expirata de sweep recent, nu se repropune imediat. Fara asta,
            # „Respinge" si expirarea automata produc un flux zilnic de
            # propuneri identice (`rejected`/`expired` nu sunt stari deschise,
            # deci garda de idempotenta de mai jos nu le vede).
            if sibling_run_ids:
                limita = (datetime.now(timezone.utc)
                          - timedelta(hours=RACIRE_PROPUNERE_ORE)).isoformat()
                recente = (
                    client.table("decision_feed")
                    .select("id,status,evidence,resolved_at")
                    .in_("run_id", sibling_run_ids)
                    .in_("status", list(_STARI_PENTRU_RACIRE))
                    .gte("resolved_at", limita)
                    .execute()
                )
                for rand in (recente.data or []):
                    if fel_decizie(rand.get("evidence")) != fel_nou:
                        continue
                    logger.info(
                        "[AutomationRuns] propunere %r pentru target_key=%s sarita — "
                        "decizia #%s a fost %s la %s, in ultimele %g ore (racire ADR-079 §3.2)",
                        fel_nou, target_key, rand.get("id"), rand.get("status"),
                        rand.get("resolved_at"), RACIRE_PROPUNERE_ORE,
                    )
                    if raport is not None:
                        raport["propunere_in_racire"] = {
                            "fel": fel_nou, "target_key": target_key,
                            "decizie_anterioara": rand.get("id"),
                            "status_anterior": rand.get("status"),
                        }
                    return None

            existing = (
                client.table("decision_feed")
                .select("id,status,evidence")
                .in_("run_id", sibling_run_ids)
                .in_("status", list(_OPEN_DECISION_STATUSES))
                .limit(1)
                .execute()
                if sibling_run_ids else None
            )
            if existing and existing.data:
                rand = existing.data[0]
                decision_id = rand["id"]
                status_vechi = rand.get("status")
                fel_vechi = fel_decizie(rand.get("evidence"))

                # ── §4.1 — o decizie APROBATA e INGHETATA. Suprascrierea
                # `evidence`-ului ei e calea prin care o aprobare de expirare
                # se executa ca promovare de campion (contrazice ADR-002).
                # Nu se atinge, si NU se tace: omul a aprobat un continut
                # anume, iar faptul ca producatorul voia altceva e un semnal.
                if status_vechi == "approved":
                    logger.error(
                        "[AutomationRuns] propunere %r pentru target_key=%s REFUZATA — "
                        "decizia #%s e deja APROBATA (fel %r) si nu se suprascrie. "
                        "Ce a aprobat omul nu se schimba sub el (ADR-079 §4.1).",
                        fel_nou, target_key, decision_id, fel_vechi,
                    )
                    if raport is not None:
                        raport["propunere_blocata_de_aprobata"] = {
                            "fel_cerut": fel_nou, "fel_aprobat": fel_vechi,
                            "decizie": decision_id, "target_key": target_key,
                        }
                    return None

                # ── §4.1.1 — felul difera: propunerea veche e un REST, nu un
                # obstacol. Se RETRAGE explicit si se creeaza cea noua. Un
                # `return None` aici ar bloca familia permanent (vezi ADR).
                if fel_vechi != fel_nou:
                    motiv = (f"retrasa de ADR-079 §4.1: producatorul propune acum "
                             f"{fel_nou!r}, premisa propunerii {fel_vechi!r} nu mai e valabila")
                    retras = withdraw_decision(decision_id, motiv)
                    logger.info(
                        "[AutomationRuns] decizia #%s (%r, %s) retrasa=%s pentru target_key=%s "
                        "— se propune %r in locul ei",
                        decision_id, fel_vechi, status_vechi, retras, target_key, fel_nou,
                    )
                    if raport is not None:
                        raport["propunere_veche_retrasa"] = {
                            "decizie": decision_id, "fel_vechi": fel_vechi,
                            "fel_nou": fel_nou, "reusit": retras,
                        }
                    if not retras:
                        # Retragerea a eșuat (cursă: altcineva i-a schimbat
                        # starea între citire și scriere). NU se creează una
                        # nouă peste ea — ar fi exact stivuirea pe care
                        # `R3-Risk-1` interzice.
                        logger.error(
                            "[AutomationRuns] retragerea deciziei #%s a esuat — nu se stivuieste "
                            "o propunere %r peste ea", decision_id, fel_nou,
                        )
                        return None
                    # cade mai jos, la INSERT-ul propunerii noi
                else:
                    update_payload: dict[str, Any] = {}
                    if evidence is not None:
                        update_payload["evidence"] = evidence
                    if update_payload:
                        client.table("decision_feed").update(update_payload).eq("id", decision_id).execute()
                    logger.info(
                        "[AutomationRuns] decizie deschisa deja existenta pentru target_key=%s (decision_id=%s, fel %r) — actualizata, nu duplicata",
                        target_key, decision_id, fel_nou,
                    )
                    return decision_id
        except Exception as exc:
            logger.error("[AutomationRuns] verificare idempotency decizie esuata: %s", exc)
            return None

    ttl_at = None
    if ttl_hours is not None:
        ttl_at = (datetime.now(timezone.utc) + timedelta(hours=ttl_hours)).isoformat()

    try:
        res = (
            client.table("decision_feed")
            .insert({
                "run_id":            run_id,
                "tier":              tier,
                "status":            "proposed",
                "evidence":          evidence,
                "rollback_plan":     rollback_plan,
                "correction_method": correction_method,
                "ttl_at":            ttl_at,
            })
            .execute()
        )
        return res.data[0]["id"] if res.data else None
    except Exception as exc:
        logger.error("[AutomationRuns] propose_decision esuata: %s", exc)
        return None


def surface_decision(decision_id: int) -> bool:
    """proposed -> pending (devine vizibil in Decision Feed).

    [REPARAT 2026-09-06] Tranzitia era neconditionata, iar docstring-ul de mai
    sus descria un contract pe care codul nu-l impunea. Consecinta, observata
    live: `propose_decision()` e idempotenta pe `target_key` si intoarce
    decizia deja DESCHISA daca exista — iar `_OPEN_DECISION_STATUSES` include
    `approved`. Deci un producator care propune la fiecare ciclu primea inapoi
    id-ul unei decizii DEJA APROBATE de om, o "surfacea", si o dadea inapoi in
    `pending`. Aprobarea omului era anulata tacit de urmatoarea rulare
    periodica, iar Faza C nu mai gasea nimic de executat.

    S-a manifestat pe calea de expirare (ADR-057), unde nu exista nicio
    tranzitie FSM care sa opreasca repropunerea. Calea de promovare era
    protejata accidental (tranzitia SUCCEEDED esueaza la a doua incercare si
    iese inainte de propunere), iar cea de rollback e azi inactiva
    (`champion_guardian_proposals_enabled=False`) — dar ambele aveau aceeasi
    capcana sub ele.

    Fix la nivelul invariantului, nu al unui apelant: `surface_decision` face
    de acum o tranzitie CONDITIONATA, care se aplica exclusiv unei decizii
    aflate inca in `proposed`. O decizie aprobata, respinsa, comisa sau
    retrasa NU mai poate fi impinsa inapoi in `pending` de nimeni."""
    return _transition_decision(decision_id, {"status": "pending"}, from_status="proposed")


def approve_decision(decision_id: int, resolved_by: str) -> bool:
    """pending -> approved. Exclusiv acțiune umană."""
    return _transition_decision(decision_id, {
        "status": "approved", "resolved_by": resolved_by, "resolved_at": _now_iso(),
    })


def reject_decision(decision_id: int, resolved_by: str) -> bool:
    """pending -> rejected. Exclusiv acțiune umană, terminal."""
    return _transition_decision(decision_id, {
        "status": "rejected", "resolved_by": resolved_by, "resolved_at": _now_iso(),
    })


def commit_decision(decision_id: int) -> bool:
    """approved -> committed. Exclusiv apelat de subsistemul proprietar,
    după scriere reușită pe stare canonică. Terminal, imuabil.

    [ADR-079 §4.4b] `from_status="approved"` adăugat. `surface_decision` a
    fost întărită pe 6 septembrie exact pentru clasa asta, iar aici rămăsese
    fără gardă — deci o decizie putea fi comisă din ORICE stare. Nu era atins
    azi (Faza C iterează doar liste de `approved`), dar asimetria e aceeași
    care a costat o dată."""
    return _transition_decision(decision_id, {"status": "committed"},
                                from_status="approved")


def fail_decision_commit(decision_id: int, error_detail: str) -> bool:
    """approved -> commit_failed. Re-intră obligatoriu în vizibilitate activă
    — nu se pierde silențios. Gardă de stare: vezi `commit_decision`."""
    return _transition_decision(decision_id, {
        "status": "commit_failed", "commit_error": error_detail,
    }, from_status="approved")


def withdraw_decision(decision_id: int, reason: str) -> bool:
    """proposed/pending -> withdrawn. Procesul originator, dacă condiția
    s-a rezolvat singură.

    [ADR-079] Până azi: **zero apelanți, nici măcar în teste** — cod mort de la
    scriere, deși e exact mecanismul de care §4.1.1 are nevoie. Două schimbări:

    1. `resolved_at`/`resolved_by` se scriu. O retragere ESTE o rezolvare, iar
       răcirea din §3.2 se sprijină pe acel câmp. Fără asta, aceeași clasă ca
       marcajul înghețat (D-14): o tranziție care uită să-și datoreze propria
       rezolvare.
    2. Tranziția e **condiționată**, încercată pe `pending` apoi pe
       `proposed`. Necondiționat, ar putea retrage o decizie `approved` — adică
       exact ce §4.1 interzice, pe altă ușă.
    """
    payload = {
        "status": "withdrawn", "commit_error": reason,
        "resolved_by": "producer-withdraw", "resolved_at": _now_iso(),
    }
    for stare in ("pending", "proposed"):
        if _transition_decision(decision_id, payload, from_status=stare):
            return True
    return False


def acknowledge_signal(decision_id: int, resolved_by: str) -> bool:
    """T3b: flagged -> acknowledged."""
    return _transition_decision(decision_id, {
        "status": "acknowledged", "resolved_by": resolved_by,
    })


def resolve_signal(decision_id: int) -> bool:
    """T3b: acknowledged -> resolved."""
    return _transition_decision(decision_id, {"status": "resolved", "resolved_at": _now_iso()})


def _transition_decision(decision_id: int, payload: dict[str, Any],
                          from_status: str | None = None) -> bool:
    """`from_status` face tranzitia CONDITIONATA: `UPDATE ... WHERE id=? AND
    status=?`, deci o singura operatie atomica, fara check-then-act (regula de
    proiect pentru orice scriere). Intoarce False daca decizia nu mai era in
    starea asteptata — nu ridica exceptie: apelantul afla ca n-a schimbat
    nimic, iar starea reala ramane cea pe care o pusese altcineva (tipic: omul
    care a aprobat). Fara `from_status`, comportamentul e cel dinainte."""
    client = get_client()
    if client is None:
        return False
    try:
        q = client.table("decision_feed").update(payload).eq("id", decision_id)
        if from_status is not None:
            q = q.eq("status", from_status)
        res = q.execute()
        if from_status is not None and not (res.data or []):
            logger.info(
                "[AutomationRuns] tranzitie decision_id=%s sarita — nu mai era in starea %r "
                "(o stare ulterioara, pusa de altcineva, nu se suprascrie)",
                decision_id, from_status,
            )
            return False
        return True
    except Exception as exc:
        logger.error("[AutomationRuns] tranzitie decision_id=%s esuata: %s", decision_id, exc)
        return False


# ════════════════════════════════════════════════════════════════════════════
# Staleness sweep (ADR-026 §Staleness Policy)
# ════════════════════════════════════════════════════════════════════════════

def sweep_stale_decisions() -> tuple[int, int]:
    """
    Tranziții automate de staleness — NICIODATĂ echivalente cu o aprobare
    sau respingere tacită (regula North Star #6):
      - pending, ttl_at depășit  -> expired
      - approved, ttl_at depășit -> orphaned (producer failure — vezi
        ADR-026 §State Machines, extensia Producer Failure)

    Returnează (nr_expirate, nr_orfanizate).

    [ADR-079 §3.2] Scrie acum și `resolved_at`/`resolved_by`. Înainte scria
    **numai** `status`, iar răcirea din §3.2 se cheie pe `resolved_at` — deci
    regula ar fi fost inertă exact pe `expired`, adică pe singura stare pe care
    sweep-ul o produce. Aș fi cablat sweep-ul crezând că fluxul zilnic de
    propuneri e oprit, fiind oprit doar pe calea care nu-l producea.

    `resolved_by` e `'sweep-adr-026'`, niciodată un nume de om: o expirare
    automată nu trebuie să arate ca o decizie umană (North Star #6).
    """
    client = get_client()
    if client is None:
        return (0, 0)

    now = _now_iso()
    expired = orphaned = 0
    try:
        res = (
            client.table("decision_feed")
            .update({"status": "expired",
                     "resolved_by": _REZOLVAT_DE_SWEEP, "resolved_at": now})
            .eq("status", "pending")
            .lt("ttl_at", now)
            .execute()
        )
        expired = len(res.data or [])
    except Exception as exc:
        logger.error("[AutomationRuns] sweep expired esuat: %s", exc)

    try:
        res = (
            client.table("decision_feed")
            .update({"status": "orphaned",
                     "resolved_by": _REZOLVAT_DE_SWEEP, "resolved_at": now})
            .eq("status", "approved")
            .lt("ttl_at", now)
            .execute()
        )
        orphaned = len(res.data or [])
    except Exception as exc:
        logger.error("[AutomationRuns] sweep orphaned esuat: %s", exc)

    return (expired, orphaned)


# ════════════════════════════════════════════════════════════════════════════
# Citire — Activity Log / Decision Feed (L7, strict read-only)
# ════════════════════════════════════════════════════════════════════════════

def list_recent_runs(limit: int = 50) -> list[dict[str, Any]]:
    """Activity Log — tot ce sistemul a făcut singur, cele mai recente
    rulări, indiferent de tier/status. Pasiv, interogabil, nu cere nimic."""
    client = get_client()
    if client is None:
        return []
    try:
        res = (
            client.table("automation_runs")
            .select("*")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return res.data or []
    except Exception as exc:
        logger.error("[AutomationRuns] list_recent_runs esuat: %s", exc)
        return []


def list_approved_decisions_for_target(target_key: str) -> list[dict[str, Any]]:
    """Decizii T3a `approved`, neexecutate încă, pentru o cheie de target
    dată — folosit de faza C (execuție) a orchestratorilor decuplați
    (ex. ADR-030): la fiecare rulare, verifică propriile decizii aprobate
    de om dar încă necomise, și le finalizează. Fără coadă/scheduler nou —
    aceeași rulare periodică idempotentă acoperă și acest caz."""
    client = get_client()
    if client is None:
        return []
    try:
        runs = (
            client.table("automation_runs")
            .select("id")
            .eq("target_key", target_key)
            .execute()
        )
        run_ids = [r["id"] for r in (runs.data or [])]
        if not run_ids:
            return []
        res = (
            client.table("decision_feed")
            .select("*")
            .in_("run_id", run_ids)
            .eq("status", "approved")
            .execute()
        )
        return res.data or []
    except Exception as exc:
        logger.error("[AutomationRuns] list_approved_decisions_for_target esuat: %s", exc)
        return []


# ════════════════════════════════════════════════════════════════════════════
# D-11 — Decision Feed trebuie sa NUMEASCA actiunea pe care o aprobi
#
# DE CE EXISTA (2026-10-20). Titlul ecranului era
# `f"[{tier}] decizie #{id} · run_id={run_id}"` — nu numea NICIODATA actiunea.
# Omul vedea `[T3a] decizie #7 · run_id=786`, un `st.json` brut, si un buton
# VERDE „✅ Aprobă". `decision_kind` aparea doar ingropat in JSON.
#
# A produs deja o confuzie REALA: proprietarul produsului a raportat „am
# promovat noul candidat din Streamlit". Verificat — nu se promovase nimic;
# aprobase o EXPIRARE. Impresia era produsa de interfata, nu de memorie.
#
# De ce e guvernanta, nu cosmetica: ADR-002 face aprobarea umana SINGURA cale
# de promovare si rollback. Un titlu mut plus un buton verde transforma
# consimtamantul informat in consimtamant PREZUMAT. Aici consecinta a fost
# benigna (expirarea era justificata independent), dar acelasi ecran va servi
# si propuneri de PROMOVARE si de ROLLBACK.
#
# Functia e PURA — nicio citire din baza — tocmai ca sa fie testabila fara
# Streamlit si fara Supabase.
# ════════════════════════════════════════════════════════════════════════════

# Fel cunoscut -> eticheta afisata. Un fel NEcunoscut NU primeste eticheta
# inventata: se afiseaza brut, cu majuscule, ca sa fie vizibil ca e nou.
_ETICHETE_FEL: dict[str, str] = {
    "expiry": "EXPIRARE Challenger",
    "promotion": "PROMOVARE Champion",
    "rollback": "ROLLBACK Champion",
    "surfacing": "SCOATERE LA SUPRAFAȚĂ",
}

FEL_NECUNOSCUT = "FEL NECUNOSCUT"


def rezuma_decizia(d: dict[str, Any]) -> dict[str, str]:
    """Descompune o decizie in `actiune` / `tinta` / `cifra` / `titlu`.

    NU INVENTEAZA NIMIC (Regula #8). Masurat pe productie, exista DOUA forme
    de `evidence`, fundamental diferite:

      - expirare (#8): `decision_kind='expiry'`, `training_run_id`,
        `n_matches_evaluated`
      - consens (#6): NICIUN `decision_kind` — are `verdict='surface_worthy'`,
        `study_run_id`, `n_samples_evaluated`

    Pentru a doua, `verdict` NU e tratat ca si cum ar fi un fel de decizie: se
    afiseaza etichetat ca verdict. Daca lipsesc amandoua, actiunea e
    `FEL NECUNOSCUT` — explicit, niciodata ghicita si niciodata goala."""
    dovada = d.get("evidence")
    if not isinstance(dovada, dict):
        dovada = {}

    fel = str(dovada.get("decision_kind") or "").strip()
    if fel:
        actiune = _ETICHETE_FEL.get(fel.lower(), fel.upper())
    else:
        verdict = str(dovada.get("verdict") or "").strip()
        actiune = f"{FEL_NECUNOSCUT} (verdict: {verdict})" if verdict else FEL_NECUNOSCUT

    tinta = ""
    run_antrenare = str(dovada.get("training_run_id") or "").strip()
    if run_antrenare:
        familie = str(dovada.get("algorithm_family") or "").strip()
        scurt = run_antrenare[:8]
        tinta = f"{familie}/{scurt}" if familie else scurt
    elif dovada.get("study_run_id") is not None:
        tinta = f"studiu #{dovada['study_run_id']}"

    cifra = ""
    for cheie, forma in (("n_matches_evaluated", "n={}"),
                         ("n_samples_evaluated", "n={}")):
        if dovada.get(cheie) is not None:
            cifra = forma.format(dovada[cheie])
            break

    parti = [f"[{d.get('tier') or '?'}]", actiune]
    if tinta:
        parti.append(f"· {tinta}")
    if cifra:
        parti.append(f"· {cifra}")
    parti.append(f"· decizie #{d.get('id')}")

    return {"actiune": actiune, "tinta": tinta, "cifra": cifra,
            "titlu": " ".join(parti)}


# [ADR-079 §2] Producătorii ale căror decizii aprobate sunt executate de COD.
#
# Azi există exact unul: `continuous_learning._phase_c_execute_approved()` e
# singurul apelant de `commit_decision()` în producție, și rulează exclusiv pe
# `target_key` de forma `familie|ligă`, adică pe deciziile ADR-030.
#
# Deciziile ADR-033 (studiul de consens, `target_key = metric_name`) NU sunt
# revendicate de nicio fază — și nici nu pot fi, fiindcă ADR-033 §Decision
# interzice modulului orice atingere a servirii. Acțiunea lor reală e
# comutarea unui flag, operație umană în acest proiect. De aceea ele primesc
# un control manual de închidere, iar celelalte nu.
#
# Lista e impusă de o gardă AST (`tests/test_decision_lifecycle.py`): orice
# modul cu `PRODUCER` care apelează `commit_decision` trebuie să fie aici. Un
# producător nou cu executant propriu cade automat, nu tăcut.
PRODUCATORI_CU_EXECUTIE_AUTOMATA = ("ADR-030",)


def list_approved_awaiting_execution() -> list[dict[str, Any]]:
    """[ADR-079 §2] Decizii `approved` care încă n-au fost comise, cu
    producătorul și `target_key` atașate.

    DE CE EXISTĂ: `list_pending_decisions()` arată **exclusiv** `pending`, deci
    o decizie aprobată dispare de pe ecran în secunda în care omul o aprobă.
    Pentru deciziile executate de cod e corect — Faza C le preia la următoarea
    rulare. Pentru cele pe care nicio fază nu le revendică (consensul, ADR-033)
    înseamnă că omul a aprobat ceva și **nu mai are nicio urmă a cererii**:
    exact cazul deciziei #6, `approved` din 14 septembrie, invizibilă o lună.

    Nu e paginată deliberat: `decision_feed` are 6 rânduri după 3 luni, iar
    `approved`-neexecutat e o stare patologică prin definiție — dacă vreodată
    trec de o pagină, problema e aceea, nu interogarea."""
    client = get_client()
    if client is None:
        return []
    try:
        res = (
            client.table("decision_feed")
            .select("*")
            .eq("status", "approved")
            .order("created_at", desc=False)
            .execute()
        )
        decizii = res.data or []
        if not decizii:
            return []
        run_ids = [d["run_id"] for d in decizii if d.get("run_id") is not None]
        meta: dict[int, dict[str, Any]] = {}
        if run_ids:
            runs = (
                client.table("automation_runs")
                .select("id,producer,target_key")
                .in_("id", run_ids)
                .execute()
            )
            meta = {r["id"]: r for r in (runs.data or [])}
        for d in decizii:
            r = meta.get(d.get("run_id"), {})
            d["producer"] = r.get("producer")
            d["target_key"] = r.get("target_key")
            d["executata_de_cod"] = r.get("producer") in PRODUCATORI_CU_EXECUTIE_AUTOMATA
        return decizii
    except Exception as exc:
        logger.error("[AutomationRuns] list_approved_awaiting_execution esuat: %s", exc)
        return []


def list_open_decisions_for_target(target_key: str) -> list[dict[str, Any]]:
    """[ADR-079] Toate deciziile DESCHISE (`proposed`/`pending`/`approved`)
    pentru o cheie de target, cu status și `evidence`.

    Necesară pentru §4.1.1: un producător care produce un verdict nou trebuie
    să poată **retrage** o propunere deschisă al cărei fel nu mai corespunde,
    chiar și când el însuși nu propune nimic (cazul regulii de trend, §4.2 —
    altfel propunerea veche rămâne în fața omului zile întregi).

    Diferită de `list_approved_decisions_for_target` prin exact asta: aceea
    răspunde la „ce am de executat", asta la „ce stă deschis pe target"."""
    client = get_client()
    if client is None:
        return []
    try:
        runs = (
            client.table("automation_runs")
            .select("id")
            .eq("target_key", target_key)
            .execute()
        )
        run_ids = [r["id"] for r in (runs.data or [])]
        if not run_ids:
            return []
        res = (
            client.table("decision_feed")
            .select("id,status,evidence,tier,run_id")
            .in_("run_id", run_ids)
            .in_("status", list(_OPEN_DECISION_STATUSES))
            .execute()
        )
        return res.data or []
    except Exception as exc:
        logger.error("[AutomationRuns] list_open_decisions_for_target esuat pentru %s: %s",
                     target_key, exc)
        return []


def list_pending_decisions() -> list[dict[str, Any]]:
    """Decision Feed — exclusiv elementele care chiar așteaptă o decizie
    umană (status='pending'). Gol implicit, per design."""
    client = get_client()
    if client is None:
        return []
    try:
        res = (
            client.table("decision_feed")
            .select("*")
            .eq("status", "pending")
            .order("created_at", desc=False)
            .execute()
        )
        return res.data or []
    except Exception as exc:
        logger.error("[AutomationRuns] list_pending_decisions esuat: %s", exc)
        return []
