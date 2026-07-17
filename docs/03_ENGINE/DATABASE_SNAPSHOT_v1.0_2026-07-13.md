# DATABASE_SNAPSHOT_v1.0 — Football Oracle

**Baseline de referință — nu audit, nu raport.** Commit: `25b9166` (main). Data: 2026-07-13T17:54Z.

| Tabelă | Rânduri |
|---|---:|
| `match_history` | 53.430 (53.409 cu rezultat real) |
| `odds_history` | 8 |
| `shadow_predictions` | 0 |
| `elo_history` | 39.575 |
| `elo_ratings` | 239 |
| `experiment_registry` | 0 |

**ELO/rating**: 53.409 / 53.409 rânduri eligibile (`actual_result IS NOT NULL`) — toate cele 10 coloane complete.

**Stare componente:**
- ✅ ELO Infrastructure v1.0 — CLOSED
- ▶ Odds Infrastructure — NEXT

**Versiune schemă**: niciun identificator formal (nicio tabelă/coloană de schema-version în proiect) — commit-ul git de mai sus e singura referință de versiune disponibilă.
