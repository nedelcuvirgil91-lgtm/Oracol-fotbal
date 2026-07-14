# Promotion Service Contract — componenta, nu Orchestrator-ul

**Status**: FROZEN (via ADR-019)
**Scope**: Contract normativ pentru componenta Python a Pasului 5

---

## Decizie: Promotion Service, nu Learning Orchestrator

Architecture Gate Review a semnalat corect că lipsa unui Learning Orchestrator ar putea bloca Promotion (cine scrie tranziția Challenger-ului, dacă nu Promotion Service?). Chief Architect a respins această concluzie explicit: un Orchestrator general, cu responsabilități multiple, construit acum doar pentru DOUĂ scrieri cuplate, ar încălca YAGNI.

**Decizie**: se construiește UN singur serviciu nou, cu UN singur use-case — `learning_core/promotion_service.py` (nescris încă — acest document e doar contractul, Pasul 5 e implementarea). Nu devine un Orchestrator general — nu capătă alte responsabilități (nu sechenționează Training Runner, nu sechenționează Shadow Evaluation, nu decide CÂND se rulează Comparison). Singura lui responsabilitate: execută exact evenimentul „Promote Challenger" descris în `PROMOTION_CONTRACT.md`, prin mecanismul descris în `ATOMICITY_CONTRACT.md`.

Dacă, în viitor, apare o a doua nevoie reală de coordonare a mai multor componente Learning Core (nu doar Promotion), ACEA nevoie — nu una ipotetică — va justifica un Orchestrator. Nu se construiește preventiv.

## Interfața publică (un singur punct de intrare)

```python
def promote_challenger(
    training_run_id: str, algorithm_family: str, league_scope: str, promoted_by: str,
) -> PromotionResult:
    ...
```

`PromotionResult` — un tip clar, niciodată o excepție necontrolată propagată către apelant: `status` (`"promoted"` | `"already_active"` | `"rejected"`), `reason` (motivul exact al respingerii, dacă `rejected`), `training_run_id`, `promoted_at`.

## Ownership

**Singurul owner al evenimentului „Promote Challenger"** e `promotion_service.py`. Nimeni altcineva nu apelează `client.rpc("promote_challenger", ...)` direct — la fel cum `challenger_manager.py` e singurul scriitor al `challengers` (ADR-016) și `model_artifact_storage.py` singurul care atinge bucket-ul `model-artifacts` (ADR — Pasul 1).

## Precondiții verificate de Promotion Service (nu de RPC — vezi diviziunea din `ATOMICITY_CONTRACT.md`)

Exact cele trei din `PROMOTION_CONTRACT.md`: Challenger `SUCCEEDED`, verdict `candidate_for_promotion` deja persistat imuabil, artefact re-validat prin încărcare reală. Fail-fast — la primul eșec, `PromotionResult(status="rejected", reason=...)`, zero apel RPC.

## Cine îl apelează

Exclusiv un declanșator manual, explicit — CLI sau acțiune UI viitoare (nescrisă încă), niciodată automat. Nu e wired în `sync/run_daily.py` — la fel ca `challenger_evaluation.py` (Pasul 4), rămâne izolat până la o decizie explicită separată de conectare (ex. „am nevoie să pot promova dintr-un Streamlit UI").

## Ce NU face Promotion Service

Identic cu secțiunea „Ce NU face Promotion" din `PROMOTION_CONTRACT.md` — nu calculează verdicte, nu antrenează, nu atinge Runtime, nu implementează Rollback, nu devine punct de coordonare pentru alte componente Learning Core.

## Testabilitate (cerință de design, nu implementare încă)

Ca toate componentele Learning Core anterioare (Pasul 1-4): teste fără rețea (RPC fabricat/mockuit), teste de gardă arhitecturală (AST — zero importatori neașteptați), test explicit de idempotență (a doua promovare a aceluiași `training_run_id` = no-op, nu eroare), test explicit al fiecărei precondiții eșuate (Challenger greșit, verdict greșit, artefact invalid) — fiecare trebuie să respingă, fără nicio scriere parțială.
