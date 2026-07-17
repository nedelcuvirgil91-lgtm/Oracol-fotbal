# ADR-011 — match_history: cornere, faulturi, cartonașe, scor la pauză

**Status**: Accepted
**Affects**: schema `match_history` (extindere aditivă de coloane)
**Authority**: Principal Software Architect

---

## Context

`docs/05_DATA_AUDIT/DATASET_CAPABILITY_AUDIT_2026-07-13.md` a demonstrat că sursa deja descărcată (`football-data.co.uk`, deja folosită pentru backfill-ul de cote și pentru șuturi/șuturi pe poartă — vezi Task 1, PR anterior) conține și cornere, faulturi, cartonașe galbene/roșii și scorul la pauză, cu completitudine 75-100% pentru Premier League/La Liga/Serie A/Bundesliga/Ligue 1 — auditul a clasificat aceste coloane drept „B — necesită modificări mici" (spre deosebire de șuturi, care erau „A", coloane deja existente).

`match_history` nu are azi nicio coloană pentru cornere, faulturi, cartonașe sau scor la pauză — infrastructura de backfill (`MatchStatsBackfillService`, `sync/sources/football_data_co_uk.py:fetch_football_data_co_uk_match_stats`) le extrage deja din sursă, dar nu are unde să le scrie.

## Decision

1. **Schema `match_history` se extinde aditiv, cu 10 coloane noi**, fără să atingă nicio coloană existentă:
   - `home_fouls`, `away_fouls` (integer)
   - `home_corners`, `away_corners` (integer)
   - `home_yellow_cards`, `away_yellow_cards` (integer)
   - `home_red_cards`, `away_red_cards` (integer)
   - `home_ht_goals`, `away_ht_goals` (integer) — scorul la pauză, informație complet nouă (nicio coloană existentă nu o acoperă)

2. **Backfill non-destructiv, gating per-coloană NULL**, identic cu tiparul deja validat pentru șuturi (`MatchStatsBackfillService`, `STAT_GROUPS["match_events"]`) — o coloană deja populată nu e niciodată atinsă.

3. **Zero coloană nouă în `ml_predictor.FEATURE_COLUMNS`** la acest pas — populate rămân disponibile pentru feature engineering viitor, dar promovarea la feature ML activ necesită dovadă de ablație separată (regulă deja stabilită, `CLAUDE.md`: „Feature nou în FEATURE_COLUMNS doar cu dovadă de ablație").

4. **Scorul la pauză (`home_ht_goals`/`away_ht_goals`) nu poate fi folosit ca predictor direct pentru meciul curent** — la momentul predicției, meciul nu a început, deci HT-ul lui nu există încă (scurgere temporală evidentă, Regula #7). Valoare legitimă doar ca sursă istorică pentru feature-uri agregate pe meciuri TRECUTE ale unei echipe (ex. „tendință de a întoarce scorul").

## Rationale

Aceleași 10 coloane sunt deja extrase de importer (`_MATCH_STATS_FIELDS`, adăugat odată cu Task 1) — infrastructura de extragere nu se schimbă, doar ținta de scriere. Motivație identică cu ADR-010: exploatăm complet o sursă deja descărcată înainte de a introduce una nouă (Principiul 4 din `CHIEF_ARCHITECT_DIRECTIVE_v1.0.md`).

## Consequences

- Odată populate, aceste coloane devin candidați legitimi pentru feature engineering (cornere/cartonașe ca proxy de agresivitate/control al jocului) — dar rămân „date disponibile", nu „feature-uri active", până la ablație.
- Explainability/Streamlit pot afișa aceste statistici direct (fapt istoric, nu predicție) fără nicio restricție de scurgere temporală — spre deosebire de folosirea lor ca input ML.
- Orice sursă viitoare de statistici de meci (Knowledge Engine — xG, posesie, PPDA) urmează același tipar: coloane aditive pe `match_history`, backfill non-destructiv, promovare la feature ML doar prin ablație.
