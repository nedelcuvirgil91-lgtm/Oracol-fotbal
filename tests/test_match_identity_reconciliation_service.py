"""
Teste pentru MatchIdentityReconciliationService (ADR-025, ID-025-01/02).
Fara retea, fara Supabase live — `process_group()` e pura (fara I/O), testata
direct cu dict-uri; `run()` foloseste un client fals in memorie.
"""
import pytest

import services.match_identity_reconciliation_service as svc
from services.match_identity_reconciliation_service import (
    FIXTURE_ID_PREFIX_TO_SOURCE,
    MatchIdentityReconciliationService, process_group, resolve_source,
)
from source_trust_policy import SourceTrustProvider


def _row(id, fixture_id, home="Team A", away="Team B", date="2026-01-01",
         result="H", hg=1, ag=0, **extra):
    base = {
        "id": id, "fixture_id": fixture_id, "home_team": home, "away_team": away,
        "kickoff_date": date, "actual_result": result,
        "actual_home_goals": hg, "actual_away_goals": ag,
    }
    base.update(extra)
    return base


# ── resolve_source ──────────────────────────────────────────────────────────

def test_resolve_source_known_prefixes():
    assert resolve_source("fd_12345") == "football_data"
    assert resolve_source("espn_999") == "espn"
    assert resolve_source("odds_abcdef") == "odds_api"
    assert resolve_source("kaggle_deadbeef") == "kaggle_historical"


def test_resolve_source_unknown_prefix_is_none():
    assert resolve_source("opta_123") is None
    assert resolve_source(None) is None
    assert resolve_source("") is None


# ── process_group: HARD CONFLICT ────────────────────────────────────────────

def test_hard_conflict_on_differing_result_excludes_group_no_side_effects():
    rows = [_row(1, "fd_1", result="H"), _row(2, "kaggle_1", result="A")]
    decision = process_group(rows)
    assert decision.excluded_reason == "hard_conflict"
    assert decision.canonical_id is None
    assert decision.data_gaps == {}
    assert decision.noncanonical == []


def test_hard_conflict_on_differing_goals_excludes_group():
    rows = [_row(1, "fd_1", hg=2), _row(2, "kaggle_1", hg=3)]
    decision = process_group(rows)
    assert decision.excluded_reason == "hard_conflict"


def test_null_hard_conflict_column_does_not_trigger_conflict():
    # World Cup 2026-style: ambele randuri au actual_result NULL (dormant).
    rows = [_row(1, "espn_1", result=None, hg=None, ag=None),
            _row(2, "odds_1", result=None, hg=None, ag=None)]
    decision = process_group(rows)
    assert decision.excluded_reason is None


# ── process_group: unknown source ───────────────────────────────────────────

def test_unknown_source_excludes_whole_group():
    rows = [_row(1, "fd_1"), _row(2, "opta_1")]
    decision = process_group(rows)
    assert decision.excluded_reason == "unknown_source"


# ── process_group: canonical selection ──────────────────────────────────────

def test_canonical_is_row_with_lowest_source_rank():
    rows = [_row(1, "kaggle_1"), _row(2, "fd_1")]
    decision = process_group(rows)
    assert decision.canonical_id == 2
    assert decision.canonical_source == "football_data"
    assert [n["id"] for n in decision.noncanonical] == [1]


def test_tiebreak_uses_lowest_id_at_equal_rank():
    # Rang egal (teoretic) — decis prin id minim, NU rangul de sursa.
    rows = [_row(20, "fd_b"), _row(10, "fd_a")]
    decision = process_group(rows)
    assert decision.canonical_id == 10


# ── process_group: observarea golurilor (Pasul 3, amendat de ADR-059) ───────
# Inainte de ADR-059 acest bloc verifica CONTOPIREA (Case 1-4 din ID-025-01).
# ADR-059 a eliminat contopirea: aceleasi patru situatii exista in continuare,
# dar rezultatul lor e un RAPORT, nu o scriere.

def test_canonical_value_present_produces_no_gap():
    """Fost "Case 1 — Writer Protection". Daca randul canonic are deja valoarea,
    nu exista gol de raportat."""
    rows = [
        _row(1, "fd_1", home_shots=10),
        _row(2, "kaggle_1", home_shots=99),
    ]
    decision = process_group(rows)
    assert "home_shots" not in decision.data_gaps


def test_missing_canonical_value_is_reported_as_gap_never_written():
    """Fost "Case 2". ADR-059: golul e raportat impreuna cu owner-ul care il
    poate regenera — dar NU se propune nicio valoare de scris. `data_gaps`
    mapeaza coloana -> owner, niciodata coloana -> valoare."""
    rows = [
        _row(1, "fd_1", home_shots=None),
        _row(2, "kaggle_1", home_shots=7),
    ]
    decision = process_group(rows)
    assert decision.data_gaps["home_shots"] == "stats_sync"
    # Invarianta centrala ADR-059: nicio valoare de date nu apare in decizie.
    assert 7 not in decision.data_gaps.values()
    assert not hasattr(decision, "merge_updates")


def test_gap_reported_once_regardless_of_how_many_rows_have_the_value():
    """Fost "Case 3 — SOFT CONFLICT". Sub ADR-059 conflictul de valori nu mai
    exista ca notiune: nu se alege nicio valoare, deci nu e nimic de arbitrat.
    Golul se raporteaza o singura data, cu owner-ul lui."""
    rows = [
        _row(1, "espn_1", home_shots=None),   # canonic
        _row(2, "odds_1", home_shots=11),
        _row(3, "kaggle_1", home_shots=9),
    ]
    decision = process_group(rows)
    assert decision.data_gaps == {"home_shots": "stats_sync"}


def test_no_gap_when_no_row_has_the_value():
    """Fost "Case 4"."""
    rows = [
        _row(1, "fd_1", home_shots=None),
        _row(2, "kaggle_1", home_shots=None),
    ]
    decision = process_group(rows)
    assert "home_shots" not in decision.data_gaps


def test_gap_owners_are_derived_per_column_family():
    """ADR-059 §Decizie 4: raportul spune CINE poate regenera fiecare gol.
    Cele patru familii de owneri, verificate pe cate un reprezentant."""
    rows = [
        _row(1, "fd_1", home_shots=None, home_elo=None, home_xg_pred=None, used_for_training=None),
        _row(2, "kaggle_1", home_shots=5, home_elo=1500, home_xg_pred=1.2, used_for_training=True),
    ]
    decision = process_group(rows)
    assert decision.data_gaps["home_shots"] == "stats_sync"
    assert decision.data_gaps["home_elo"] == "run_backfill"
    assert decision.data_gaps["home_xg_pred"] == "_cache_prediction"
    assert decision.data_gaps["used_for_training"] == "import_sources"


def test_superseded_reason_format():
    """Formatul exact al `superseded_reason` — contract de trasabilitate deja
    scris in productie (3.504 randuri, ADR-025 Faza 4).

    [ACTUALIZAT — F4.3] Rangurile concrete NU mai sunt codificate literal:
    registrul de incredere e declarat evolutiv prin design
    (`source_trust_policy.py`, ADR-025 §Consecinte), deci orice sursa noua
    inserata renumeroteaza legitim. Ce trebuie sa ramana stabil e STRUCTURA
    mesajului si identitatea randului canonic — acelea sunt verificate aici,
    cu rangurile citite din registru in loc de constante."""
    rows = [_row(1, "kaggle_04f4107f71d47331"), _row(2, "fd_497780")]
    decision = process_group(rows)
    reason = decision.noncanonical[0]["reason"]

    fd_rank = SourceTrustProvider.get_rank("football_data")
    kaggle_rank = SourceTrustProvider.get_rank("kaggle_historical")

    assert reason.startswith("duplicate_cross_provider: ")
    assert f"canonical=fd_497780 (rank={fd_rank})" in reason
    assert f"superseded=kaggle_04f4107f71d47331 (rank={kaggle_rank})" in reason
    # Randul canonic ramane cel de la football_data, indiferent de renumerotare.
    assert decision.canonical_id == 2


def test_idempotent_on_two_row_group_deterministic_regardless_of_input_order():
    a = [_row(1, "fd_1", home_shots=None), _row(2, "kaggle_1", home_shots=5)]
    b = list(reversed(a))
    assert process_group(a).canonical_id == process_group(b).canonical_id
    assert process_group(a).data_gaps == process_group(b).data_gaps


# ── run(): mod EXECUTE ──────────────────────────────────────────────────────
# [ADR-059] EXECUTE nu mai ridica NotImplementedError: e autorizat, fiindca
# suprafata lui de scriere s-a redus la 3 coloane de audit pe randul necanonic.
# Testele care conteaza acum nu mai sunt "refuza sa ruleze", ci "scrie EXACT
# ce are voie si nimic altceva".

def test_dry_run_is_the_default():
    """Un apel fara argumente nu are voie sa scrie. Daca cineva schimba
    vreodata implicitul, acest test pica inainte sa ajunga in productie."""
    import inspect
    sig = inspect.signature(MatchIdentityReconciliationService.run)
    assert sig.parameters["dry_run"].default is True


# ── run(): DRY-RUN orchestration with fake client ───────────────────────────

class _FakeTable:
    def __init__(self, rows):
        self._rows = rows
        self._filters = []
        self._order_col = None

    def select(self, cols):
        return self

    def is_(self, col, val):
        self._filters.append(("is_null", col))
        return self

    def in_(self, col, values):
        self._filters.append(("in", col, set(values)))
        return self

    def order(self, col, desc=False):
        # [ADR-059 Addendum, 2026-08-22] `_fetch_key_index()` cere acum
        # ordonare explicita inainte de `.range()` (fix pentru golul de
        # paginare instabila) — clientul fals trebuie sa o poata onora ca
        # testele existente, care exercita `run()` prin acest client, sa
        # ramana valide.
        self._order_col = col
        self._order_desc = desc
        return self

    def range(self, start, end):
        self._range = (start, end)
        return self

    def execute(self):
        rows = self._rows
        for f in self._filters:
            if f[0] == "is_null":
                rows = [r for r in rows if r.get(f[1]) is None]
            elif f[0] == "in":
                rows = [r for r in rows if r.get(f[1]) in f[2]]
        if self._order_col is not None:
            rows = sorted(rows, key=lambda r: r.get(self._order_col), reverse=self._order_desc)
        if hasattr(self, "_range"):
            start, end = self._range
            rows = rows[start:end + 1]

        class Res:
            pass
        res = Res()
        res.data = rows
        return res


class _FakeClient:
    def __init__(self, rows):
        self._rows = rows

    def table(self, name):
        assert name == "match_history"
        return _FakeTable(self._rows)


class _FakeSb:
    def __init__(self, rows):
        self._client = _FakeClient(rows)

    def get_client(self):
        return self._client


def test_run_dry_run_discovers_and_reports_duplicate_groups():
    rows = [
        _row(1, "fd_1", home="Alpha", away="Beta", date="2026-02-01", home_shots=None),
        _row(2, "kaggle_1", home="Alpha", away="Beta", date="2026-02-01", home_shots=8),
        _row(3, "fd_2", home="Gamma", away="Delta", date="2026-02-02"),  # unic, fara duplicat
    ]
    service = MatchIdentityReconciliationService(supabase_client=_FakeSb(rows))
    report = service.run(dry_run=True)

    assert report.total_groups == 1
    assert report.reconciled_groups == 1
    assert report.excluded_hard_conflict_count == 0
    assert report.excluded_unknown_source_count == 0
    assert report.columns_with_data_gap.get("home_shots") == 1
    assert report.canonical_rows_with_data_gap == 1
    assert report.gaps_by_owner.get("stats_sync") == 1
    # [ADR-059] In DRY-RUN nu se marcheaza nimic.
    assert report.rows_marked_superseded == 0


def test_run_dry_run_never_calls_update_or_rpc():
    rows = [
        _row(1, "fd_1", home="Alpha", away="Beta", date="2026-02-01"),
        _row(2, "kaggle_1", home="Alpha", away="Beta", date="2026-02-01"),
    ]

    class _NoWriteTable(_FakeTable):
        def update(self, *a, **kw):
            raise AssertionError("DRY-RUN nu trebuie sa apeleze niciodata update()")

        def upsert(self, *a, **kw):
            raise AssertionError("DRY-RUN nu trebuie sa apeleze niciodata upsert()")

    class _NoWriteClient(_FakeClient):
        def table(self, name):
            return _NoWriteTable(self._rows)

        def rpc(self, *a, **kw):
            raise AssertionError("DRY-RUN nu trebuie sa apeleze niciodata rpc()")

    class _NoWriteSb:
        def get_client(self):
            return _NoWriteClient(rows)

    service = MatchIdentityReconciliationService(supabase_client=_NoWriteSb())
    report = service.run(dry_run=True)
    assert report.total_groups == 1


# ── [F4.3] Extinderea registrului de surse ──────────────────────────────────
# Context: F3 (ADR-058) a extins vocabularul `ALIAS_TO_CANONICAL`, iar
# `match_key()` — folosit de descoperirea ID-025-02 — a inceput sa produca 404
# grupuri duplicate invizibile in iulie. Toate implicau surse absente din
# registru, deci regula "sursa necunoscuta exclude tot grupul" le-ar fi exclus
# pe toate 403 (cel de-al 404-lea e HARD CONFLICT, exclus corect si ramane asa).

def test_new_prefixes_resolve():
    assert resolve_source("flashscore_jFwdNbHj") == "flashscore"
    assert resolve_source("tsdb_2573295") == "tsdb"
    assert resolve_source("openfootball_champions_league_202425_x_vs_y_20250311") == "openfootball"


def test_every_live_fixture_prefix_resolves_to_a_ranked_source():
    """Invariantul care leaga cele doua registre: orice prefix pe care
    `resolve_source()` stie sa-l rezolve TREBUIE sa aiba si un rang. Un nume de
    sursa fara rang ar trece de Pasul 1 si ar exploda la sortarea din Pasul 2
    (`None` nu se compara cu `int`)."""
    for prefix, source in FIXTURE_ID_PREFIX_TO_SOURCE.items():
        assert SourceTrustProvider.get_rank(source) is not None, (
            f"Prefixul {prefix!r} -> sursa {source!r} nu are rang in "
            f"SOURCE_TRUST_RANK"
        )


def test_no_prefix_shadows_another():
    """`resolve_source()` itereaza dictionarul si intoarce prima potrivire.
    Daca un prefix ar fi prefixul altuia (ex. 'fd_' si 'fd_extra_'), rezolvarea
    ar depinde de ordinea de inserare — fragil si tacit."""
    prefixes = list(FIXTURE_ID_PREFIX_TO_SOURCE)
    for a in prefixes:
        for b in prefixes:
            if a != b:
                assert not b.startswith(a), f"Prefixul {b!r} e umbrit de {a!r}"


def test_f4_group_compositions_select_expected_canonical():
    """Cele patru compozitii de surse care apar efectiv in cele 403 grupuri F4
    (verificate live pe `match_history`, 2026-08-21), fiecare cu randul canonic
    asteptat sub registrul extins."""
    cases = [
        # (fixture_a, fixture_b, id-ul asteptat ca fiind canonic)
        ("flashscore_abc", "tsdb_123", 1),        # 6 grupuri
        ("fd_1", "openfootball_x", 1),            # 157 grupuri
        ("fd_1", "kaggle_x", 1),                  # 78 grupuri
        ("openfootball_x", "kaggle_y", 1),        # 162 grupuri
    ]
    for fx_a, fx_b, expected_canonical_id in cases:
        rows = [_row(1, fx_a), _row(2, fx_b)]
        decision = process_group(rows)
        assert decision.excluded_reason is None, (
            f"{fx_a} + {fx_b} a fost exclus: {decision.excluded_reason}"
        )
        assert decision.canonical_id == expected_canonical_id, (
            f"{fx_a} + {fx_b} -> canonic {decision.canonical_id}, "
            f"asteptat {expected_canonical_id}"
        )
        # Ordinea de intrare nu conteaza (determinism, Pasul 2).
        assert process_group(list(reversed(rows))).canonical_id == expected_canonical_id


def test_hard_conflict_still_excludes_liverpool_psg_shape():
    """Grupul cu scoruri contradictorii ramane exclus automat, nerezolvat de
    alegerea survivorului. Forma reala: openfootball 0-1 vs football_data 1-5
    (acesta din urma fiind scorul + departajarea, bug de import reparat separat
    la sursa in F4.5). Politica de merge e NULL-only prin constructie, deci
    alegerea unui survivor NU poate corecta un scor gresit non-NULL."""
    rows = [
        _row(130963, "openfootball_x", result="A", hg=0, ag=1),
        _row(3809, "fd_524100", result="A", hg=1, ag=5),
    ]
    decision = process_group(rows)
    assert decision.excluded_reason == "hard_conflict"
    assert decision.canonical_id is None


# ── reconciled_group_keys (monitorizare recurenta, 2026-08-22) ─────────────

def test_reconciled_group_keys_matches_reconciled_groups_count():
    rows = [
        _row(1, "fd_1", home="Alpha", away="Beta", date="2026-02-01"),
        _row(2, "kaggle_1", home="Alpha", away="Beta", date="2026-02-01"),
        _row(3, "fd_2", home="Gamma", away="Delta", date="2026-02-02"),
        _row(4, "kaggle_2", home="Gamma", away="Delta", date="2026-02-02"),
    ]
    sb = _FakeSb(rows)
    report = MatchIdentityReconciliationService(supabase_client=sb).run(dry_run=True)
    assert len(report.reconciled_group_keys) == report.reconciled_groups == 2
    assert "alpha||beta||2026-02-01" in report.reconciled_group_keys
    assert "gamma||delta||2026-02-02" in report.reconciled_group_keys


def test_reconciled_group_keys_excludes_hard_conflict_and_unknown_source():
    rows = [
        _row(1, "fd_1", home="A", away="B", date="2026-02-01", result="H"),
        _row(2, "kaggle_1", home="A", away="B", date="2026-02-01", result="A"),  # hard conflict
        _row(3, "fd_2", home="C", away="D", date="2026-02-02"),
        _row(4, "opta_1", home="C", away="D", date="2026-02-02"),  # unknown source
    ]
    sb = _FakeSb(rows)
    report = MatchIdentityReconciliationService(supabase_client=sb).run(dry_run=True)
    assert report.reconciled_group_keys == []


# ── target_keys (pilot precis, ADR-025 Faza 3) ──────────────────────────────

def test_target_keys_processes_only_matching_groups():
    rows = [
        _row(1, "fd_1", home="Alpha", away="Beta", date="2026-02-01"),
        _row(2, "kaggle_1", home="Alpha", away="Beta", date="2026-02-01"),
        _row(3, "fd_2", home="Gamma", away="Delta", date="2026-02-02"),
        _row(4, "kaggle_2", home="Gamma", away="Delta", date="2026-02-02"),
    ]
    sb = _FakeSb(rows)
    target = {"alpha||beta||2026-02-01"}
    report = MatchIdentityReconciliationService(supabase_client=sb).run(
        dry_run=True, target_keys=target,
    )
    assert report.reconciled_group_keys == ["alpha||beta||2026-02-01"]
    assert report.total_groups == 2  # descoperirea vede tot
    assert report.target_keys_not_found == []


def test_target_keys_reports_keys_not_found():
    rows = [
        _row(1, "fd_1", home="Alpha", away="Beta", date="2026-02-01"),
        _row(2, "kaggle_1", home="Alpha", away="Beta", date="2026-02-01"),
    ]
    sb = _FakeSb(rows)
    target = {"alpha||beta||2026-02-01", "nu||exista||2026-01-01"}
    report = MatchIdentityReconciliationService(supabase_client=sb).run(
        dry_run=True, target_keys=target,
    )
    assert report.target_keys_not_found == ["nu||exista||2026-01-01"]


def test_target_keys_excludes_hard_conflict_group_even_if_targeted():
    """Un pilot nu poate ocoli protectia HARD CONFLICT tintind explicit acel
    grup — grupul ramane exclus, iar cheia apare in `target_keys_not_found`."""
    rows = [
        _row(1, "fd_1", home="A", away="B", date="2026-02-01", result="H"),
        _row(2, "kaggle_1", home="A", away="B", date="2026-02-01", result="A"),
    ]
    sb = _FakeSb(rows)
    target = {"a||b||2026-02-01"}
    report = MatchIdentityReconciliationService(supabase_client=sb).run(
        dry_run=True, target_keys=target,
    )
    assert report.reconciled_group_keys == []
    assert report.target_keys_not_found == ["a||b||2026-02-01"]
    assert report.excluded_hard_conflict_count == 1


# ── Regresie: golul de paginare instabila (descoperit live, 2026-08-22) ─────
#
# `_fetch_key_index()` folosea `.range()` FARA `.order()` explicit — sub
# scriere concurenta pe productie (chiar in timpul unei reconcilieri de masa),
# PostgREST/Postgres nu garanteaza ordine stabila intre pagini succesive,
# deci acelasi rand fizic putea fi intors de doua ori, in doua pagini
# diferite. Efectul, daca ar fi ramas nereparat: un "grup" fals cu acelasi
# rand de doua ori -> randul devine canonic pentru sine insusi SI necanonic
# marcat superseded de sine insusi -> `superseded_by = id` (auto-referential)
# -> randul dispare din setul live fara sa fi existat vreodata un duplicat
# real. Verificat live pe productie ca NU s-a intamplat (0 randuri
# auto-referentiale dupa reconcilierea de 2.827 randuri) — dar cauza radacina
# tot trebuia reparata, plus o aparare in adancime la nivelul `process_group`.

def test_process_group_deduplica_acelasi_rand_fizic_vazut_de_doua_ori():
    """Simuleaza exact defectul de paginare: acelasi dict de rand apare de
    doua ori in lista primita de process_group(). Rezultatul NU are voie sa
    fie un grup "reconciliat" cu randul canonic pentru sine insusi."""
    row = _row(42, "fd_1", home="Alpha", away="Beta", date="2026-02-01")
    decision = process_group([row, dict(row)])  # copie separata, acelasi id
    assert decision.excluded_reason == "not_a_duplicate_after_dedup"
    assert decision.canonical_id is None
    assert decision.noncanonical == []


def test_process_group_deduplica_dar_pastreaza_duplicatul_real():
    """[A, A, B] (A vazut de doua ori din bug, B duplicat real) trebuie sa se
    reduca la [A, B] si sa produca o decizie normala, nu sa fie respins in
    intregime — bug-ul de paginare nu are voie sa ascunda un duplicat real."""
    a = _row(1, "fd_1", home="Alpha", away="Beta", date="2026-02-01")
    b = _row(2, "kaggle_1", home="Alpha", away="Beta", date="2026-02-01")
    decision = process_group([a, dict(a), b])
    assert decision.excluded_reason is None
    assert decision.canonical_id == 1  # football_data (rank mai mic) castiga
    assert [nc["id"] for nc in decision.noncanonical] == [2]


def test_run_nu_marcheaza_niciodata_un_rand_ca_superseded_de_sine_insusi():
    """Test de integrare prin `run()`: chiar daca `_fetch_key_index` ar
    intoarce (ipotetic) acelasi rand de doua ori intr-un grup, EXECUTE nu are
    voie sa produca `superseded_by == id`."""
    rows = [_row(7, "fd_1", home="Alpha", away="Beta", date="2026-02-01")]

    class _DuplicatingTable(_FakeTable):
        def execute(self):
            res = super().execute()
            if res.data:
                res.data = res.data + [dict(res.data[0])]  # simuleaza bug-ul
            return res

    class _DuplicatingClient(_FakeClient):
        def table(self, name):
            return _DuplicatingTable(self._rows)

    class _DuplicatingSb:
        def get_client(self):
            return _DuplicatingClient(rows)

    service = MatchIdentityReconciliationService(supabase_client=_DuplicatingSb())
    report = service.run(dry_run=False)

    assert report.reconciled_groups == 0
    assert report.rows_marked_superseded == 0
