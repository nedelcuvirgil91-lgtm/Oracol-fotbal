"""ADR-079 — ciclul de viață al unei decizii T3a.

DE CE EXISTĂ. Trei defecte independente compuneau același efect: bucla de
decizie umană nu funcționa. Cel mai grav e §4.1 — `propose_decision()`
suprascria `evidence`-ul oricărei decizii DESCHISE pe același `target_key`,
inclusiv una `approved`. Combinat cu ordinea fazelor (A → … → C în aceeași
trecere), o aprobare de EXPIRARE se putea executa ca PROMOVARE de campion,
fără ca nimeni să fi aprobat o promovare — contrazice direct ADR-002.

CE VERIFICĂ FIȘIERUL ĂSTA, pe secțiuni:
  §4.1  — o decizie `approved` nu se atinge, și refuzul se RAPORTEAZĂ
  §4.1.1 — felul diferă → se RETRAGE, nu se întoarce `None` tăcut
  §3.2  — răcirea după `rejected`/`expired`, și `resolved_at` scris de sweep
  §4.2  — regula de trend + plafonul, back-testată pe seriile REALE
  §4.3  — calea de promovare scrie `decision_kind` explicit
  §4.4  — contorul nu mai minte; `commit_decision` are gardă de stare

LECȚIA DE METODĂ care a modelat §6.2: defectul din §4.1.1 **nu e vizibil în
nicio funcție izolată**. Apare doar din compunerea regulii de trend cu regula
de fel, pe o serie reală de evaluări. De aceea testul central reconstituie
seria lui `blend_v1/4e17c737` pas cu pas, nu apelează funcții una câte una.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import automation_runs as ar
import learning_core.continuous_learning as cl
from tests.test_automation_runs import _FakeClient  # fals deja probat, cu .gte()


@pytest.fixture()
def client(monkeypatch):
    c = _FakeClient()
    monkeypatch.setattr(ar, "get_client", lambda: c)
    return c


def _acum(ore: float = 0.0) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=ore)).isoformat()


def _run(client, target_key: str) -> int:
    """Creează un `automation_run` real prin API-ul public, ca `target_key` să
    fie legat exact cum e în producție."""
    rid = ar.write_run("TEST", "pas", "T3a", target_key=target_key)
    assert rid is not None
    return rid


def _decizie(client, run_id: int, status: str, fel: str | None,
             resolved_at: str | None = None, **extra) -> int:
    """Inserează o decizie direct în store, ca să putem construi stări pe care
    API-ul public nu le atinge (ex. `expired`)."""
    store, next_id = client._tables.setdefault("decision_feed", ([], [1]))
    evidence = dict(extra)
    if fel is not None:
        evidence["decision_kind"] = fel
    rand = {"id": next_id[0], "run_id": run_id, "tier": "T3a",
            "status": status, "evidence": evidence, "resolved_at": resolved_at}
    next_id[0] += 1
    store.append(rand)
    return rand["id"]


def _citeste(client, decision_id: int) -> dict:
    store, _ = client._tables["decision_feed"]
    return next(r for r in store if r["id"] == decision_id)


# ════════════════════════════════════════════════════════════════════════════
# Felul deciziei — implicitul TREBUIE să fie cel al executantului
# ════════════════════════════════════════════════════════════════════════════

def test_felul_cade_pe_acelasi_implicit_ca_executantul():
    """Faza C face `evidence.get("decision_kind", "promotion")`. Dacă helper-ul
    ar cădea pe altceva, comparația de fel și execuția ar fi de acord pe hârtie
    și în dezacord în fapt — exact clasa D-11."""
    assert ar.fel_decizie({}) == "promotion"
    assert ar.fel_decizie(None) == "promotion"
    assert ar.fel_decizie({"decision_kind": None}) == "promotion"


def test_felul_se_normalizeaza_si_nu_se_inventeaza():
    assert ar.fel_decizie({"decision_kind": "  EXPIRY "}) == "expiry"
    assert ar.fel_decizie({"decision_kind": "rollback"}) == "rollback"
    # un fel nou se întoarce brut, nu mapat pe ceva plauzibil
    assert ar.fel_decizie({"decision_kind": "recalibration"}) == "recalibration"


@pytest.mark.parametrize("stricat", ["nu e dict", 42, [], 0.5])
def test_felul_nu_arunca_pe_evidence_stricat(stricat):
    assert ar.fel_decizie(stricat) == "promotion"


# ════════════════════════════════════════════════════════════════════════════
# §4.1 — o decizie APROBATĂ e înghețată
# ════════════════════════════════════════════════════════════════════════════

def test_aprobata_nu_se_suprascrie_si_refuzul_se_raporteaza(client):
    """Garda centrală a ADR-ului. Fără ea, o aprobare de expirare devine o
    promovare executată."""
    run_vechi = _run(client, "blend_v1|all")
    did = _decizie(client, run_vechi, "approved", "expiry",
                   training_run_id="174e7e17", n_matches_evaluated=301)

    run_nou = _run(client, "blend_v1|all")
    raport: dict = {}
    rezultat = ar.propose_decision(
        run_nou, tier="T3a", rollback_plan="x",
        evidence={"decision_kind": "promotion", "training_run_id": "174e7e17"},
        raport=raport,
    )

    assert rezultat is None, "nu se propune nimic peste o decizie aprobată"
    rand = _citeste(client, did)
    assert rand["evidence"]["decision_kind"] == "expiry", "evidence-ul aprobat a fost ATINS"
    assert rand["evidence"]["n_matches_evaluated"] == 301
    assert rand["status"] == "approved"
    assert raport["propunere_blocata_de_aprobata"]["fel_cerut"] == "promotion"
    assert raport["propunere_blocata_de_aprobata"]["fel_aprobat"] == "expiry"


def test_aprobata_de_ACELASI_fel_se_improspateaza_ca_inainte(client):
    """Contrapondere: refuzul e pe felul DIFERIT. Aceeași propunere trebuie să
    își poată împrospăta cifrele — altfel am rupt idempotența ADR-026."""
    run_vechi = _run(client, "blend_v1|all")
    did = _decizie(client, run_vechi, "pending", "expiry", n_matches_evaluated=301)

    run_nou = _run(client, "blend_v1|all")
    rezultat = ar.propose_decision(
        run_nou, tier="T3a", rollback_plan="x",
        evidence={"decision_kind": "expiry", "n_matches_evaluated": 348},
    )
    assert rezultat == did, "aceeași decizie, reutilizată"
    assert _citeste(client, did)["evidence"]["n_matches_evaluated"] == 348


# ════════════════════════════════════════════════════════════════════════════
# §4.1.1 — felul diferă: se RETRAGE, nu se întoarce None
# ════════════════════════════════════════════════════════════════════════════

def test_propunerea_deschisa_de_alt_fel_se_RETRAGE_nu_blocheaza(client):
    """Prima mea versiune întorcea `None` aici, ceea ce ar fi blocat familia
    permanent. Vezi ADR-079 §4.1.1."""
    run_vechi = _run(client, "blend_v1|all")
    vechea = _decizie(client, run_vechi, "pending", "promotion", training_run_id="4e17c737")

    run_nou = _run(client, "blend_v1|all")
    raport: dict = {}
    noua = ar.propose_decision(
        run_nou, tier="T3a", rollback_plan="x",
        evidence={"decision_kind": "expiry", "training_run_id": "4e17c737"},
        raport=raport,
    )

    assert noua is not None, "expirarea TREBUIE să poată fi propusă"
    assert noua != vechea, "e o decizie nouă, nu cea veche reetichetată"
    assert _citeste(client, vechea)["status"] == "withdrawn"
    assert _citeste(client, noua)["evidence"]["decision_kind"] == "expiry"
    assert raport["propunere_veche_retrasa"]["fel_vechi"] == "promotion"
    assert raport["propunere_veche_retrasa"]["reusit"] is True


def test_retragerea_scrie_resolved_at(client):
    """O retragere E o rezolvare. Fără câmpul ăsta, răcirea din §3.2 n-ar
    vedea-o — aceeași clasă ca marcajul înghețat din D-14."""
    run_id = _run(client, "t|all")
    did = _decizie(client, run_id, "pending", "promotion")
    assert ar.withdraw_decision(did, "motiv") is True
    rand = _citeste(client, did)
    assert rand["status"] == "withdrawn"
    assert rand["resolved_at"], "retragerea nu și-a datat propria rezolvare"
    assert rand["commit_error"] == "motiv"


def test_retragerea_NU_atinge_o_decizie_aprobata(client):
    """Altfel §4.1 ar fi ocolit pe altă ușă: numai omul desface ce a aprobat."""
    run_id = _run(client, "t|all")
    did = _decizie(client, run_id, "approved", "expiry")
    assert ar.withdraw_decision(did, "motiv") is False
    assert _citeste(client, did)["status"] == "approved"


def test_daca_retragerea_esueaza_NU_se_stivuieste_o_propunere_noua(client, monkeypatch):
    """Cursă: cineva schimbă starea între citire și scriere. Stivuirea e exact
    ce interzice garda `R3-Risk-1`."""
    run_vechi = _run(client, "blend_v1|all")
    _decizie(client, run_vechi, "pending", "promotion")
    monkeypatch.setattr(ar, "withdraw_decision", lambda did, reason: False)

    run_nou = _run(client, "blend_v1|all")
    assert ar.propose_decision(
        run_nou, tier="T3a", rollback_plan="x",
        evidence={"decision_kind": "expiry"},
    ) is None


# ════════════════════════════════════════════════════════════════════════════
# §3.2 — răcire, și `resolved_at` scris de sweep
# ════════════════════════════════════════════════════════════════════════════

def test_racire_dupa_respingere_recenta(client):
    run_vechi = _run(client, "blend_v1|all")
    _decizie(client, run_vechi, "rejected", "expiry", resolved_at=_acum(-2))

    run_nou = _run(client, "blend_v1|all")
    raport: dict = {}
    assert ar.propose_decision(
        run_nou, tier="T3a", rollback_plan="x",
        evidence={"decision_kind": "expiry"}, raport=raport,
    ) is None
    assert raport["propunere_in_racire"]["status_anterior"] == "rejected"


def test_racire_expira_dupa_fereastra(client):
    """Contraponderea care arată că răcirea e o FEREASTRĂ, nu un blocaj
    permanent — altfel o respingere ar interzice pe veci acel fel."""
    run_vechi = _run(client, "blend_v1|all")
    _decizie(client, run_vechi, "rejected", "expiry",
             resolved_at=_acum(-(ar.RACIRE_PROPUNERE_ORE + 1)))

    run_nou = _run(client, "blend_v1|all")
    assert ar.propose_decision(
        run_nou, tier="T3a", rollback_plan="x",
        evidence={"decision_kind": "expiry"},
    ) is not None


def test_racirea_e_pe_FEL_nu_pe_target(client):
    """O expirare respinsă nu trebuie să blocheze o PROMOVARE."""
    run_vechi = _run(client, "blend_v1|all")
    _decizie(client, run_vechi, "rejected", "expiry", resolved_at=_acum(-2))

    run_nou = _run(client, "blend_v1|all")
    assert ar.propose_decision(
        run_nou, tier="T3a", rollback_plan="x",
        evidence={"decision_kind": "promotion"},
    ) is not None


def test_sweep_scrie_resolved_at_altfel_racirea_e_inerta(client):
    """🔴 Defectul găsit la review. Sweep-ul scria NUMAI `status`, deci răcirea
    cheiată pe `resolved_at` n-ar fi văzut niciodată un `expired` — adică exact
    cazul pentru care răcirea există."""
    run_id = _run(client, "blend_v1|all")
    vechi = _decizie(client, run_id, "pending", "expiry")
    client._tables["decision_feed"][0][-1]["ttl_at"] = _acum(-200)

    expirate, orfanizate = ar.sweep_stale_decisions()
    assert expirate == 1 and orfanizate == 0
    rand = _citeste(client, vechi)
    assert rand["status"] == "expired"
    assert rand["resolved_at"], "sweep-ul nu a datat expirarea → răcirea e inertă"
    assert rand["resolved_by"] == "sweep-adr-026", (
        "o expirare automată nu trebuie să arate ca o decizie umană")


def test_racire_dupa_expirare_prin_sweep_END_TO_END(client):
    """Lanțul complet: sweep expiră → răcirea vede expirarea → nu se repropune.
    Ăsta e testul care ar fi căzut cu versiunea mea inițială."""
    run_id = _run(client, "blend_v1|all")
    _decizie(client, run_id, "pending", "expiry")
    client._tables["decision_feed"][0][-1]["ttl_at"] = _acum(-200)
    ar.sweep_stale_decisions()

    run_nou = _run(client, "blend_v1|all")
    raport: dict = {}
    assert ar.propose_decision(
        run_nou, tier="T3a", rollback_plan="x",
        evidence={"decision_kind": "expiry"}, raport=raport,
    ) is None
    assert raport["propunere_in_racire"]["status_anterior"] == "expired"


# ════════════════════════════════════════════════════════════════════════════
# §4.4 — gărzi de stare
# ════════════════════════════════════════════════════════════════════════════

def test_commit_decision_cere_starea_approved(client):
    run_id = _run(client, "t|all")
    did = _decizie(client, run_id, "pending", "expiry")
    assert ar.commit_decision(did) is False, "o decizie `pending` nu se comite"
    assert _citeste(client, did)["status"] == "pending"


def test_commit_decision_merge_din_approved(client):
    run_id = _run(client, "t|all")
    did = _decizie(client, run_id, "approved", "expiry")
    assert ar.commit_decision(did) is True
    assert _citeste(client, did)["status"] == "committed"


def test_fail_decision_commit_cere_approved(client):
    run_id = _run(client, "t|all")
    did = _decizie(client, run_id, "committed", "expiry")
    assert ar.fail_decision_commit(did, "eroare") is False
    assert _citeste(client, did)["status"] == "committed"


# ════════════════════════════════════════════════════════════════════════════
# §4.2 + §6.1 — regula de trend, BACK-TESTATĂ pe seriile REALE
#
# Cifrele vin din `challenger_evaluations`, măsurate pe producție 2026-10-20.
# NU sunt inventate pentru test: fiecare rând a existat.
#
# Testele de aici folosesc `automation_runs` REAL peste clientul fals, nu o
# dublură. Motivul e lecția D-10: o dublură care își rescrie propria logică
# poate divergea tăcut de implementarea reală, iar garda trece fără să
# dovedească nimic. Aici singurele lucruri falsificate sunt Supabase și FSM-ul
# Challenger-ului.
# ════════════════════════════════════════════════════════════════════════════

def _pregateste_cl(monkeypatch, client, *, expirari_pornite=True):
    monkeypatch.setattr(cl, "is_challenger_expiry_proposals_enabled",
                        lambda: expirari_pornite)
    monkeypatch.setattr(cl.challenger_manager, "transition",
                        lambda *a, **kw: None)


def _rezultat(n: int, semnificative: int) -> dict:
    """Un verdict cu exact `semnificative` metrici semnificative."""
    chei = ["brier_significant", "logloss_significant", "accuracy_significant"]
    return {"n_matches_evaluated": n,
            **{c: (i < semnificative) for i, c in enumerate(chei)}}


def _propuneri_de_fel(client, fel: str) -> list[dict]:
    store, _ = client._tables.get("decision_feed", ([], [1]))
    return [r for r in store if ar.fel_decizie(r.get("evidence")) == fel]


# n, metrici semnificative, se propune expirarea?, din ce serie reală
_SERII_REALE = [
    (311, 2, False, "4e17c737 — primul n peste prag, 2/3: se reține"),
    (320, 2, False, "4e17c737 — tot 2/3"),
    (385, 2, False, "4e17c737 — recăzut din 3/3, încă sub plafon"),
    (441, 2, False, "4e17c737 — ultimul sub plafon"),
    (457, 2, True,  "4e17c737 — peste plafon: staționarea nu mai reține"),
    (316, 0, True,  "6e7265c5 — 0/3, trendul nu se aplică (decizia #7 reală)"),
    (506, 0, True,  "e638c1dc — 0/3 pe toată seria (decizia #4 reală)"),
    (301, 2, False, "174e7e17 — CONTRAPONDEREA: aici greșeala a fost comisă"),
]


@pytest.mark.parametrize("n,semnificative,se_propune,motiv", _SERII_REALE)
def test_backtest_regula_de_trend_pe_serii_reale(
    client, monkeypatch, n, semnificative, se_propune, motiv
):
    _pregateste_cl(monkeypatch, client)
    run_id = _run(client, "blend_v1|all")

    cl._handle_monitoring_verdict(run_id, "174e7e17", "blend_v1|all",
                                  _rezultat(n, semnificative), {"expiry_proposed": 0})

    expirari = _propuneri_de_fel(client, "expiry")
    assert bool(expirari) is se_propune, motiv


def test_trendul_se_consemneaza_chiar_cand_reține_propunerea(client, monkeypatch):
    """Tăcerea e defectul pe care ADR-057 l-a plătit cu 14 zile. O suprimare
    trebuie să fie un FAPT consemnat, nu absența unui fapt."""
    _pregateste_cl(monkeypatch, client)
    run_id = _run(client, "blend_v1|all")
    cl._handle_monitoring_verdict(run_id, "174e7e17", "blend_v1|all",
                                  _rezultat(301, 2), {"expiry_proposed": 0})

    runs, _ = client._tables["automation_runs"]
    rezumat = next(r for r in runs if r["id"] == run_id)["summary"]
    assert rezumat["expiry_skipped_trending"] is True
    assert rezumat["trend_significant_metrics"] == 2
    assert rezumat["expiry_threshold_reached"] is True


def test_expirarea_propusa_duce_trendul_in_dovada(client, monkeypatch):
    """Dacă expirăm un Challenger care arăta bine pe 2 din 3, omul trebuie să
    vadă asta în momentul aprobării."""
    _pregateste_cl(monkeypatch, client)
    run_id = _run(client, "blend_v1|all")
    cl._handle_monitoring_verdict(run_id, "4e17c737", "blend_v1|all",
                                  _rezultat(457, 2), {"expiry_proposed": 0})

    (propunere,) = _propuneri_de_fel(client, "expiry")
    assert propunere["evidence"]["trend_significant_metrics"] == 2
    assert propunere["evidence"]["max_matches_for_trend_hold"] == 450
    assert propunere["evidence"]["training_run_id"] == "4e17c737"


# ════════════════════════════════════════════════════════════════════════════
# §6.2 — LANȚUL care prinde defectul găsit la review
#
# Defectul NU e vizibil în nicio funcție izolată. Apare doar din compunerea
# regulii de trend cu regula de fel, pe o serie reală. Un test pe funcție ar
# trece și cu defectul prezent.
# ════════════════════════════════════════════════════════════════════════════

def test_lantul_complet_4e17c737_promovare_trecatoare_apoi_expirare(client, monkeypatch):
    """Patru pași, reconstituiți din seria reală a lui `blend_v1/4e17c737`.

    Fără pasul 3 (retragerea), pasul 4 eșuează — și exact aceea e versiunea
    ADR-ului pe care am scris-o prima dată (§4.1.1)."""
    _pregateste_cl(monkeypatch, client)
    tinta, target = "4e17c737", "blend_v1|all"

    # ── Pasul 1: n=311, 2/3 → expirarea se reține (regula de trend)
    cl._handle_monitoring_verdict(_run(client, target), tinta, target,
                                  _rezultat(311, 2), {"expiry_proposed": 0})
    assert _propuneri_de_fel(client, "expiry") == []
    assert _propuneri_de_fel(client, "promotion") == []

    # ── Pasul 2: n=329, 3/3 → propunere de PROMOVARE, pending
    sumar = {"proposed": 0}
    cl._handle_candidate_for_promotion(_run(client, target), tinta, target,
                                       _rezultat(329, 3), sumar)
    promovari = _propuneri_de_fel(client, "promotion")
    assert len(promovari) == 1, "promovarea trebuie propusă la 3/3"
    id_promovare = promovari[0]["id"]
    assert promovari[0]["status"] == "pending"
    assert sumar["proposed"] == 1
    # §4.3 — felul e scris EXPLICIT, nu lăsat pe implicitul Fazei C
    assert promovari[0]["evidence"]["decision_kind"] == "promotion"

    # ── Pasul 3: n=385, recade la 2/3 → promovarea se RETRAGE imediat
    sumar3 = {"expiry_proposed": 0}
    cl._handle_monitoring_verdict(_run(client, target), tinta, target,
                                  _rezultat(385, 2), sumar3)
    assert _citeste(client, id_promovare)["status"] == "withdrawn", (
        "propunerea de promovare și-a pierdut premisa și trebuia retrasă ACUM, "
        "nu lăsată zile în fața omului")
    assert _propuneri_de_fel(client, "expiry") == [], "încă sub plafon"

    # ── Pasul 4: n=457, peste plafon → expirarea SE propune
    cl._handle_monitoring_verdict(_run(client, target), tinta, target,
                                  _rezultat(457, 2), {"expiry_proposed": 0})
    expirari = _propuneri_de_fel(client, "expiry")
    assert len(expirari) == 1, (
        "AICI cădea versiunea mea inițială: propunerea veche de promovare "
        "bloca expirarea permanent, iar familia rămânea înțepenită")
    assert expirari[0]["status"] == "pending"


def test_o_promovare_aprobata_de_om_NU_se_retrage_automat(client, monkeypatch):
    """Granița regulii de retragere. Dacă omul a aprobat promovarea, un verdict
    nou nu i-o desface — numai el poate (§4.1)."""
    _pregateste_cl(monkeypatch, client)
    target = "blend_v1|all"
    did = _decizie(client, _run(client, target), "approved", "promotion",
                   training_run_id="4e17c737")

    cl._handle_monitoring_verdict(_run(client, target), "4e17c737", target,
                                  _rezultat(457, 2), {"expiry_proposed": 0})

    assert _citeste(client, did)["status"] == "approved"
    # și expirarea nu se stivuiește peste ea
    assert _propuneri_de_fel(client, "expiry") == []


# ════════════════════════════════════════════════════════════════════════════
# §3.2 — sweep-ul e CABLAT în ciclu
# ════════════════════════════════════════════════════════════════════════════

def test_sweepul_e_apelat_de_run_cycle_si_raportat(monkeypatch):
    """Era implementat și neapelat de nicio linie de producție — doar două
    teste. Decizia #7 a stat 22 de zile fără niciun semnal."""
    apeluri = {"n": 0}

    def _sweep():
        apeluri["n"] += 1
        return (2, 1)

    monkeypatch.setattr(cl, "is_enabled", lambda: True)
    monkeypatch.setattr(cl.ar, "sweep_stale_decisions", _sweep)
    monkeypatch.setattr(cl.model_registry, "list_available", lambda: [])

    rezultat = cl.run_cycle()

    assert apeluri["n"] == 1, "sweep-ul trebuie apelat exact o dată pe ciclu"
    assert rezultat["stale_expired"] == 2
    assert rezultat["stale_orphaned"] == 1


# ════════════════════════════════════════════════════════════════════════════
# §4.4a — contorul nu minte
#
# Testul ăsta lipsea, și absența lui a ieșit la iveală prin MUTAȚIE, nu prin
# recitire: mutația „contorul necondiționat" trecea toate cele 33 de teste.
# O reparație fără gardă e o reparație care se poate întoarce tăcut.
# ════════════════════════════════════════════════════════════════════════════

def test_contorul_NU_numara_o_propunere_care_nu_s_a_facut(client, monkeypatch):
    """Idempotența întoarce o decizie deja DESCHISĂ, iar `surface_decision`
    refuză corect tranziția (nu mai e în `proposed`). Contorul creștea oricum,
    deci rapoartele de rulare numărau propuneri inexistente."""
    _pregateste_cl(monkeypatch, client)
    target = "blend_v1|all"
    # o propunere de expirare deja `pending` pe același target
    _decizie(client, _run(client, target), "pending", "expiry", n_matches_evaluated=441)

    sumar = {"expiry_proposed": 0}
    cl._handle_monitoring_verdict(_run(client, target), "4e17c737", target,
                                  _rezultat(457, 2), sumar)

    assert len(_propuneri_de_fel(client, "expiry")) == 1, "nu s-a creat una nouă"
    assert sumar["expiry_proposed"] == 0, (
        "propunerea era deja deschisă — contorul a raportat o propunere nouă "
        "care nu s-a făcut (ADR-079 §4.4a)")


def test_contorul_CRESTE_cand_propunerea_e_chiar_noua(client, monkeypatch):
    """Contraponderea: altfel testul de mai sus ar trece și dacă contorul n-ar
    crește niciodată."""
    _pregateste_cl(monkeypatch, client)
    target = "blend_v1|all"
    sumar = {"expiry_proposed": 0}
    cl._handle_monitoring_verdict(_run(client, target), "4e17c737", target,
                                  _rezultat(457, 2), sumar)
    assert len(_propuneri_de_fel(client, "expiry")) == 1
    assert sumar["expiry_proposed"] == 1


def test_contorul_de_promovare_la_fel(client, monkeypatch):
    _pregateste_cl(monkeypatch, client)
    target = "blend_v1|all"
    _decizie(client, _run(client, target), "pending", "promotion")

    sumar = {"proposed": 0}
    cl._handle_candidate_for_promotion(_run(client, target), "4e17c737", target,
                                       _rezultat(329, 3), sumar)
    assert sumar["proposed"] == 0


# ════════════════════════════════════════════════════════════════════════════
# §2 — deciziile APROBATE sunt vizibile, iar lista de executanți e impusă
# ════════════════════════════════════════════════════════════════════════════

def test_aprobatele_sunt_listate_cu_producator_si_marcaj_de_executie(client):
    """`list_pending_decisions()` arată exclusiv `pending`, deci o decizie
    aprobată dispărea de pe ecran. Decizia #6 a fost invizibilă o lună."""
    run_cl = ar.write_run("ADR-030", "promotion_candidate", "T3a", target_key="blend_v1|all")
    run_cons = ar.write_run("ADR-033", "consensus_surfacing_candidate", "T3a",
                            target_key="agreement_score")
    _decizie(client, run_cl, "approved", "expiry", training_run_id="174e7e17")
    _decizie(client, run_cons, "approved", None, verdict="surface_worthy", study_run_id=1216)
    _decizie(client, run_cl, "pending", "expiry")        # nu e aprobată
    _decizie(client, run_cl, "committed", "expiry")      # deja executată

    aprobate = ar.list_approved_awaiting_execution()
    assert len(aprobate) == 2, "exact cele `approved`, nimic altceva"
    dupa_producator = {d["producer"]: d for d in aprobate}
    assert dupa_producator["ADR-030"]["executata_de_cod"] is True
    assert dupa_producator["ADR-033"]["executata_de_cod"] is False, (
        "ADR-033 §Decision interzice modulului orice atingere a servirii, deci "
        "nicio fază nu poate executa decizia lui")
    assert dupa_producator["ADR-033"]["target_key"] == "agreement_score"


def test_lista_de_producatori_cu_executie_e_COMPLETA():
    """Gardă structurală, AST: orice modul de producție care apelează
    `commit_decision` trebuie să aibă `PRODUCER` în
    `PRODUCATORI_CU_EXECUTIE_AUTOMATA`.

    Fără ea, un executant nou ar face ca deciziile lui să primească butonul
    „confirm că am executat manual" — adică omul ar afirma un fapt despre ceva
    ce codul face oricum. Lista nu e documentație, e contract."""
    import ast as _ast
    from pathlib import Path as _Path

    # Exceptare NUMITĂ și justificată, nu o scăpare prin `producer is None`:
    # `app.py` nu e un producător, e suprafața prin care omul acționează. El
    # apelează `commit_decision` exclusiv prin controlul „confirm că am executat
    # manual" (ADR-079 §2), adică exact cazul în care NU există cod executant.
    # Orice ALT modul fără `PRODUCER` care ar executa decizii cade mai jos.
    _OMUL_NU_E_PRODUCATOR = {"app.py"}

    radacina = _Path(__file__).resolve().parent.parent
    vinovati = []
    for cale in radacina.rglob("*.py"):
        text = cale.read_text(encoding="utf-8")
        if ("tests" in cale.parts or cale.name == "automation_runs.py"
                or cale.name in _OMUL_NU_E_PRODUCATOR):
            continue
        arbore = _ast.parse(text)
        cheama_commit = any(
            isinstance(n, _ast.Call) and isinstance(n.func, _ast.Attribute)
            and n.func.attr == "commit_decision"
            for n in _ast.walk(arbore)
        )
        if not cheama_commit:
            continue
        producer = None
        for n in _ast.walk(arbore):
            if (isinstance(n, _ast.Assign) and len(n.targets) == 1
                    and isinstance(n.targets[0], _ast.Name)
                    and n.targets[0].id == "PRODUCER"
                    and isinstance(n.value, _ast.Constant)):
                producer = n.value.value
        if producer not in ar.PRODUCATORI_CU_EXECUTIE_AUTOMATA:
            vinovati.append(f"{cale.relative_to(radacina)}: PRODUCER={producer!r}")

    assert not vinovati, (
        "module care execută decizii dar nu sunt declarate în "
        "PRODUCATORI_CU_EXECUTIE_AUTOMATA:\n  " + "\n  ".join(vinovati))


def test_garda_de_producatori_NU_trece_vid():
    """Contrapondere: dacă niciun modul n-ar apela `commit_decision`, garda de
    mai sus ar trece fără să verifice nimic — capcana trecerii VIDE, plătită la
    garda GRANT. Aici cerem explicit că `app.py` sau un modul de learning
    chiar îl apelează."""
    import ast as _ast
    from pathlib import Path as _Path

    radacina = _Path(__file__).resolve().parent.parent
    apelanti = []
    for cale in radacina.rglob("*.py"):
        if "tests" in cale.parts or cale.name == "automation_runs.py":
            continue
        arbore = _ast.parse(cale.read_text(encoding="utf-8"))
        if any(isinstance(n, _ast.Call) and isinstance(n.func, _ast.Attribute)
               and n.func.attr == "commit_decision" for n in _ast.walk(arbore)):
            apelanti.append(cale.name)
    assert apelanti, "garda ar trece vid — nimeni nu apelează commit_decision"


def test_cel_mult_o_decizie_deschisa_per_target_invariantul_care_face_ordinea_sigura(client):
    """Invariantul pe care se sprijină ordinea din `propose_decision`
    (răcire ÎNAINTEA deciziei deschise).

    Cât timp una e deschisă, idempotența o returnează în loc să creeze alta —
    deci nu poate exista o a doua, pe același target și același fel, care să
    fie respinsă și să declanșeze răcirea peste cea deschisă. Testul ăsta
    documentează invariantul; fără el, ordinea e doar o presupunere."""
    target = "blend_v1|all"
    primul = ar.propose_decision(_run(client, target), tier="T3a", rollback_plan="x",
                                 evidence={"decision_kind": "expiry", "n_matches_evaluated": 311})
    al_doilea = ar.propose_decision(_run(client, target), tier="T3a", rollback_plan="x",
                                    evidence={"decision_kind": "expiry", "n_matches_evaluated": 320})
    al_treilea = ar.propose_decision(_run(client, target), tier="T3a", rollback_plan="x",
                                     evidence={"decision_kind": "expiry", "n_matches_evaluated": 329})

    assert primul == al_doilea == al_treilea, "trei cicluri, o singură decizie"
    store, _ = client._tables["decision_feed"]
    deschise = [r for r in store if r["status"] in ar._OPEN_DECISION_STATUSES]
    assert len(deschise) == 1, "invariantul e rupt — ordinea din propose_decision nu mai e sigură"
    assert deschise[0]["evidence"]["n_matches_evaluated"] == 329, "cifrele s-au împrospătat"
