# docs/00_GOVERNANCE/FROZEN_REGISTRY.md

## Purpose
Acest document reprezintă registrul oficial al tuturor specificațiilor tehnice și arhitecturale care au atins stadiul de *Implementation Readiness* și au fost declarate *Frozen*.

## Frozen Documents

| Document | Version | ADR | Status | Frozen Date |
| :--- | :--- | :--- | :--- | :--- |
| ARCHITECTURE.md | 1.0.0 | Frozen via ADR-007 | FROZEN | 2026-07-10 |
| DATABASE_SPEC.md | 1.0.0 | Frozen via ADR-008 | FROZEN | 2026-07-10 |
| PIPELINE_SPEC.md | 1.0.0 | Frozen via ADR-009 | FROZEN | 2026-07-10 |
| ENGINE_SPEC.md | 1.0.0 | — | FROZEN | 2026-07-11 |
| CONFIG_SPEC.md | 1.0.0 | — | FROZEN | 2026-07-11 |
| ODDS_PERSISTENCE_DESIGN.md | 1.0.0 | Frozen via ADR-005; Clarified by ADR-006; Extended by ADR-010 (historical backfill + provenance) | FROZEN | 2026-07-11 |
| docs/04_LEARNING_CORE/RUNTIME_CONTRACT.md | 1.0.0 | Frozen via ADR-019 | FROZEN | 2026-07-14 |
| docs/04_LEARNING_CORE/PROMOTION_CONTRACT.md | 1.0.0 | Frozen via ADR-019; Clarified by ADR-019 addendum (E2E) | FROZEN | 2026-07-14 |
| docs/04_LEARNING_CORE/ATOMICITY_CONTRACT.md | 1.0.0 | Frozen via ADR-019; Clarified by ADR-019 addendum (E2E) | FROZEN | 2026-07-14 |
| docs/04_LEARNING_CORE/PROMOTION_SERVICE_CONTRACT.md | 1.0.0 | Frozen via ADR-019; Clarified by ADR-019 addendum (E2E) | FROZEN | 2026-07-14 |
| docs/00_GOVERNANCE/BASELINE_FAZA1_2026-07.md | 1.0.0 | Snapshot istoric, aprobat de utilizator la închiderea Fazei 1. Regim special: nu se modifică în practică; modificabil DOAR printr-un ADR care documentează o eroare factuală (nu o evoluție a proiectului). O fază nouă primește un baseline nou. | FROZEN | 2026-07-19 |

## Not Yet Frozen

| Document | Status | Motiv |
| :--- | :--- | :--- |
| API_SPEC.md | CHANGES REQUIRED / DRAFT | Decizii lipsă (protocol, autentificare, versionare API) — nespecificate în niciun document Frozen existent; nu se inventează. |

## Frozen Rule
Un document marcat ca *FROZEN* nu poate fi modificat decât în situații excepționale, susținute de un nou ADR (Architecture Decision Record). Redeschiderea unui document este permisă exclusiv dacă auditul unui document dependent relevă o contradicție tehnică demonstrabilă și imposibil de reconciliat cu specificația deja înghețată.

## Change Policy
* **Motivație validă pentru un ADR nou:** schimbări care ating **modelul de date**, **contractele dintre componente**, **responsabilitățile componentelor**, sau **fluxul arhitectural**. Contradicții tehnice demonstrabile (erori de flux, imposibilitatea implementării unor constrângeri, blocaje de integritate) intră automat aici.
* **Nu necesită ADR** — detalii de implementare care nu ating niciuna din categoriile de mai sus (ex: formatul exact al unei erori de provider, ora exactă a unui cron, un mesaj de log) — acestea aparțin documentației de implementare sau comentariilor din cod, nu guvernanței de arhitectură.
* **Motivație invalidă:** Preferințele subiective, stilul, optimizările sau "cum aș fi făcut eu" nu reprezintă motive valide pentru redeschiderea unui document.
* **Proces:** Orice modificare necesită aprobarea auditorului și înregistrarea unui nou ADR care explică impactul asupra componentelor existente. Editarea directă a unui document Frozen, fără ADR corespunzător, nu este permisă — vezi ADR-005 pentru contextul exact al acestei clarificări.

## Maintenance Rule
TRACEABILITY_MATRIX.md nu introduce cerințe noi. Orice modificare a acestui document trebuie să rezulte exclusiv din modificarea unui document sursă aprobat prin ADR.

*Acest document este pur informativ, reflectând trasabilitatea cerințelor stabilite prin procesele de audit anterioare.*
