"""
================================================================================
FOOTBALL ORACLE — Sync Orchestrator (R4.1, ADR-038)
================================================================================
Punct unic de decizie pentru "ce endpoint ruleaza, cand, de ce, cu ce
prioritate, sub ce buget, cu ce dependinte, cu ce politica de retry" (R4.1
Step 5) — infrastructura GENERICA, provider-agnostica (Step 7), FARA nicio
logica specifica de endpoint cablata inca. Fixtures/statistics/injuries/
lineups/standings/H2H/odds raman R4.2, aprobare separata — acest modul nu
inregistreaza niciun task real, doar mecanismul care le va guverna.

Invariant central, cerut explicit de misiune: "No synchronization code
should schedule itself independently." Orice cod viitor de sincronizare
(R4.2) TREBUIE sa se inregistreze aici ca SyncTask — orchestratorul decide
daca/cand ruleaza, nu task-ul insusi.

Decizia de rulare (`should_run`) verifica, in ordine:
    1. Dependinte — toate task-urile din `depends_on` trebuie sa fi rulat cu
       succes in ACEASTA rulare (un run e o unitate, nu istoric persistat).
    2. Coverage — doar daca `coverage_required=True`, prin coverage_cache
       (§2/§4 audit) — "necunoscut" NU inseamna "suportat", blocheaza.
    3. Buget/rate-limit — prin Request Manager (care delega la Rate Limit
       Manager, header-e reale) — "ar trebui sa existe cererea?" (§4/§16).
Prioritatea (P1-P5, audit §5) decide DOAR ordinea de incercare intre
task-uri altfel eligibile — nu inlocuieste niciuna din verificarile de mai
sus. Politica de retry ramane cea deja existenta la nivel HTTP
(urllib3.Retry, football_providers.py) — orchestratorul nu reincearca
singur un task esuat in aceeasi rulare (retry global e follow-up R4.2, nu
inventat aici fara caz de utilizare).
================================================================================
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Callable

logger = logging.getLogger("FootballOracle.SyncOrchestrator")


class Priority(IntEnum):
    """P1 = cea mai inalta prioritate (audit §5: injuries/coaches pentru
    meciuri din urmatoarele 48h, consumatorul real de azi) ... P5 = cea mai
    joasa (reference data, verificata rar)."""
    P1 = 1
    P2 = 2
    P3 = 3
    P4 = 4
    P5 = 5


@dataclass
class SyncTask:
    """Descriere GENERICA a unei unitati de sincronizare — niciun camp nu
    presupune API-Football sau vreun alt provider anume (Step 7). `run` e
    orice callable fara argumente — implementarea reala (R4.2) o va furniza,
    acest modul nu o cunoaste."""
    name: str
    provider: str
    priority: Priority
    run: Callable[[], object]
    coverage_required: bool = False
    league_id_canonical: str | None = None       # necesar doar daca coverage_required
    api_football_league_id: int | None = None    # idem
    season: int | None = None                    # idem
    depends_on: tuple[str, ...] = field(default_factory=tuple)


@dataclass
class SyncTaskResult:
    task_name: str
    ran: bool
    reason: str
    error: str | None = None


class SyncOrchestrator:
    def __init__(self, request_manager=None):
        if request_manager is None:
            from request_manager import get_request_manager
            request_manager = get_request_manager()
        self._request_manager = request_manager
        self._tasks: dict[str, SyncTask] = {}

    def register_task(self, task: SyncTask) -> None:
        self._tasks[task.name] = task

    def unregister_task(self, name: str) -> None:
        self._tasks.pop(name, None)

    def tasks(self) -> list[SyncTask]:
        return list(self._tasks.values())

    def _coverage_ok(self, task: SyncTask) -> bool:
        if not task.coverage_required:
            return True
        if task.league_id_canonical is None or task.api_football_league_id is None or task.season is None:
            logger.warning(
                "[SyncOrchestrator] %s: coverage_required=True dar campurile de liga lipsesc — blocat, nu presupun.",
                task.name,
            )
            return False
        from coverage_cache import get_cached_coverage
        entry = get_cached_coverage(task.league_id_canonical, task.api_football_league_id, task.season)
        if entry is None:
            return False  # necunoscut -> nu incercam, nu presupunem suportat (Regula #8)
        return entry.get("fixtures_supported") not in ("False", "plan_restricted")

    def should_run(self, task_name: str, succeeded_this_run: set[str] | None = None) -> tuple[bool, str]:
        task = self._tasks.get(task_name)
        if task is None:
            return False, "task necunoscut"
        succeeded_this_run = succeeded_this_run or set()
        missing_deps = [d for d in task.depends_on if d not in succeeded_this_run]
        if missing_deps:
            return False, f"dependinte neindeplinite: {missing_deps}"
        if not self._coverage_ok(task):
            return False, "coverage nesuportata sau necunoscuta"
        if not self._request_manager.should_request(task.provider):
            return False, "buget epuizat"
        return True, "eligibil"

    def run_pending(self) -> list[SyncTaskResult]:
        """Ruleaza task-urile inregistrate — algoritm greedy, in pasade
        repetate: la fiecare pas, alege task-ul eligibil cu prioritatea cea
        mai inalta dintre cele ramase, il ruleaza, actualizeaza setul de
        succese, apoi reincepe de la cea mai inalta prioritate ramasa. Asta
        garanteaza ca un lant de dependinte se respecta corect, chiar daca
        task-ul dependent are prioritate mai inalta decat cel de care
        depinde (§Step 5 — "dependencies" e un criteriu real, nu doar
        ordonare dupa prioritate bruta). Cand niciun task ramas nu mai
        devine eligibil (buget epuizat, coverage nesuportata, dependinta
        esuata), restul sunt raportate blocate, cu motivul curent — fara
        bucla infinita. Fail-safe: o eroare intr-un task nu opreste restul
        (Regula #8 — sincronizare partiala e mai buna decat oprire
        completa), dar orice task care depinde de unul esuat ramane
        corect blocat (nu se adauga la `succeeded`)."""
        results: list[SyncTaskResult] = []
        succeeded: set[str] = set()
        remaining: dict[str, SyncTask] = dict(self._tasks)

        while remaining:
            progressed = False
            for task in sorted(remaining.values(), key=lambda t: (int(t.priority), t.name)):
                eligible, reason = self.should_run(task.name, succeeded_this_run=succeeded)
                if not eligible:
                    continue
                del remaining[task.name]
                progressed = True
                try:
                    task.run()
                    succeeded.add(task.name)
                    results.append(SyncTaskResult(task_name=task.name, ran=True, reason="executat"))
                except Exception as exc:
                    logger.error("[SyncOrchestrator] %s a esuat: %s", task.name, exc)
                    results.append(SyncTaskResult(task_name=task.name, ran=False, reason="eroare in executie", error=str(exc)))
                break  # reincepe pasada de la cea mai inalta prioritate ramasa
            if not progressed:
                # Tot ce a ramas e definitiv blocat in aceasta rulare.
                for task in sorted(remaining.values(), key=lambda t: (int(t.priority), t.name)):
                    _, reason = self.should_run(task.name, succeeded_this_run=succeeded)
                    results.append(SyncTaskResult(task_name=task.name, ran=False, reason=reason))
                break
        return results


_orch_instance: SyncOrchestrator | None = None


def get_sync_orchestrator() -> SyncOrchestrator:
    global _orch_instance
    if _orch_instance is None:
        _orch_instance = SyncOrchestrator()
    return _orch_instance
