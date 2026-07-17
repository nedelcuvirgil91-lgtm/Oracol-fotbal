# ADR-022 — ELO Margin of Victory (MOV), formula FiveThirtyEight-style, constante V2_damped

**Status**: Accepted
**Data**: 2026-07-15

## Context

`ELOTracker` (`sync/backfill_features.py`) folosea, din primul commit, exclusiv rezultatul categorial (H/D/A) la actualizarea ratingului — un 5-0 și un 1-0 produceau identică actualizare. P3 (`ML_EVOLUTION_ROADMAP.md`) a testat introducerea unui multiplicator de diferență de goluri (Margin of Victory), precedat obligatoriu de un Design Review de alegere a formulei (`P3_0_DESIGN_REVIEW_ELO_MOV_2026-07-15.md`, Accepted).

**Runda 1 + P3.1** (date fragmentate, înainte de P3.5): toate variantele testate (V1-V5) arătau un compromis intern — o axă de fidelitate (eroare relativă vs. `ELO_RATINGS_FALLBACK`) se îmbunătățea, cealaltă (Spearman rank correlation) se înrăutățea, simultan la fiecare variantă. Niciun candidat nu atingea pragul de Accuracy (+0,3pp). Verdict: **Inconclusive** — semnal real, dar insuficient, motiv semnalat explicit: fragmentarea identității echipelor (`match_history` conținea 137 echipe sub 313 variante de nume neconsolidate) corupea probabil comparațiile de fidelitate mai mult decât orice alegere de formulă.

**P3.5** (Team Identity Audit & Historical Normalization, `docs/03_ENGINE/P3_5_FAZA3_POST_MIGRATION_REPORT_2026-07-15.md`) a consolidat istoricul — 137 echipe, 19.797 rânduri cu toate cele 18 `FEATURE_COLUMNS` recalculate pe identitate unificată, executat și verificat pe producție.

**P3 Revalidation** (`docs/03_ENGINE/P3_REVALIDATION_POST_P3_5_2026-07-15.md`), rulată imediat după, pe exact aceeași metodologie/formulă/constante (nemodificate), a măsurat efectul: eroarea de fidelitate a Replay A (control) a scăzut de la 11,23% la 6,84% (−39% relativ) — cea mai mare îmbunătățire de fidelitate ELO din tot proiectul. **V1_baseline și V2_damped îmbunătățesc acum simultan ambele axe de fidelitate** (eroare absolută ȘI Spearman rank correlation) — compromisul care produsese verdictul Inconclusive a dispărut.

## Decizie

**P3 se închide ca Accepted.** Formula aleasă: **FiveThirtyEight-style** (§1, `P3_0_DESIGN_REVIEW_ELO_MOV_2026-07-15.md`):

```
multiplier(gd, elo_diff) = ln(gd+1) × c / (d·elo_diff + c)     dacă gd ≥ 1
multiplier = 1.0                                                dacă gd = 0
```

unde `gd` = diferența absolută de goluri, `elo_diff` = rating câștigător − rating învins (semnat, folosind ratingurile pre-meci, home advantage inclus).

**Constante alese: V2_damped — c=4,4, d=0,0005.**

Justificare, exclusiv pe cifre măsurate (`P3_REVALIDATION_POST_P3_5_2026-07-15.md` §2, §7):

| Metrică | Replay A (control) | V2_damped |
|---|---:|---:|
| Eroare fidelitate (mean_abs_pct_diff vs. referință) | 6,84% | **6,10%** (cea mai bună dintre toate 5 variante) |
| Spearman rank correlation vs. referință | 0,6608 | **0,7005** (cea mai bună dintre toate 5 variante) |
| Stabilitate sezon-cu-sezon (yoy_std) | 70,54 | 70,63 (practic neschimbată) |
| Accuracy walk-forward | 0,4967 | 0,4992 (+0,25pp — cea mai apropiată de pragul +0,3pp dintre toate 5) |
| Log Loss / Brier | 1,0138 / 0,6061 | 1,0121 / 0,6051 (ambele mai bune) |

**V1_baseline** (c=2,2, d=0,001 — constantele nemodificate din `P3_0_DESIGN_REVIEW`) satisface același criteriu (ambele axe de fidelitate îmbunătățite) cu o marjă mai mică — rămâne fallback documentat, nu ales ca implicit.

**Criteriul de succes folosit — identic, neschimbat, din P3.0 §6:**
```
(fidelitatea ELO crește — eroare relativă vs. referință scade ȘI/SAU Spearman rank correlation crește)
                              SAU
(predictorul crește clar — Accuracy ≥+0,3pp FĂRĂ regres simultan pe Log Loss ȘI Brier)
```
V2_damped îndeplinește prima ramură (disjuncție), simultan pe ambele sub-condiții — fără regres pe ramura de predictor (Accuracy/Log Loss/Brier toate mai bune, doar sub pragul strict de +0,3pp). Criteriul de abandon („fidelitatea scade ȘI câștigul de predictor e marginal") nu se aplică.

## Consecințe

1. **Schimbare de contract, nu doar de cod**: semnificația `match_history.home_elo`/`away_elo` (și, în cascadă, `home/away_offensive_rating`/`defensive_rating`, calculate din ELO via `team_pre_match_rating()`) se schimbă pentru TOATE rândurile — nu doar cele 19.797 afectate de P3.5, ci toate cele 53.430, fiindcă formula de actualizare ELO se schimbă la fiecare meci din replay, nu doar la echipele fragmentate.
2. **Implementare necesară**: `ELOTracker.process_match()` (`sync/backfill_features.py`) primește goluri (deja disponibile la punctul de apel, neconectate azi) și aplică multiplicatorul MOV cu constantele V2_damped (tratate ca hiperparametri numiți, nu magic numbers). Al doilea apelant (`sync/bootstrap_league_learning.py`) se actualizează identic — un singur loc de adevăr pentru formulă, nu duplicare.
3. **Producție NU se atinge automat de acest ADR** — codul poate fi comis fără nicio scriere pe Supabase (Writer Protection, Regula #13, garantează că o coloană deja populată nu e niciodată suprascrisă implicit). Activarea reală a noii formule pe `match_history` cere un Migration Plan separat (reset controlat + re-backfill, aceeași arhitectură dovedită la P3.5 Faza 3), cu propriul raport de impact și aprobare explicită — **nu implicit prin acest ADR**.
4. **Live serving neafectat**: confirmat în `P3_5_FAZA3_MIGRATION_PLAN_2026-07-15.md` §7 (Impact Matrix) și reconfirmat aici — `oracle_engine.py._build_profile()` obține ELO live din `oracle_api.get_elo_rating()` (sursă externă/cache), nu din `ELOTracker`/`match_history.home_elo`. Schimbarea afectează exclusiv datele de antrenare ML (`ml_predictor.py`).
5. **V3/V4/V5 rămân închise, nu se retestează** — V3/V5 păstrează același compromis intern deja documentat de două ori; V4 confirmă și agravează regresia deja cunoscută (instabilitate numerică nouă, demonstrată: rating Inter Milan 4040 pe date consolidate).
6. **P4 (ELO Trend) rămâne Planned, dar acum condiționat de implementarea efectivă a acestui ADR** (ELO Trend citește `elo_history`, care ar trebui populat pe baza noii formule, nu pe cea veche).

## Referințe

- `docs/03_ENGINE/P3_0_DESIGN_REVIEW_ELO_MOV_2026-07-15.md` — alegerea formulei, criteriul de succes.
- `docs/03_ENGINE/P3_REVALIDATION_POST_P3_5_2026-07-15.md` — toate cifrele, cele 8 secțiuni.
- `docs/03_ENGINE/P3_5_FAZA3_POST_MIGRATION_REPORT_2026-07-15.md` — precondiția de date (consolidare identitate echipe).
- `docs/03_ENGINE/ML_EVOLUTION_ROADMAP.md` — istoricul complet P1-P10.
