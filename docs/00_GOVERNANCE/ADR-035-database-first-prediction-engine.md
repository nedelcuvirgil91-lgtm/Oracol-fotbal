# ADR-035 — Database-First Prediction Engine

**Status**: APROBAT — 2026-07-19, aprobat de utilizator (rev.3, după două
runde de ajustări cerute la review). Implementarea D1–D4 autorizată strict
în Ordinea de execuție de mai jos.

**Data**: 2026-07-19

**Contextul care l-a declanșat**: auditul complet al fluxului de date pentru
meciul Petrolul Ploiești – Dinamo București (19.07.2026), cerut de utilizator
după ce predicția aplicației (64.5% Petrolul) a contrazis piața reală
(Dinamo favorit, cote 2.18–2.20 la 5 case).

## Context

Auditul (rulări de cod + interogări SQL read-only pe proiectul `Prediction`,
2026-07-19) a demonstrat, cu dovezi, patru constatări:

1. **P0 — Motorul ignoră baza proprie de date.** `match_history` conține
   1.977 meciuri Romania SuperLiga (ultimul: chiar ziua auditului),
   `home_elo_after` populat pe 1.975, plus tabela `elo_ratings` actualizată
   de sync cu 2 zile înainte (Petrolul 1459, Dinamo 1609) și 38–40 meciuri
   terminate per echipă în ultimul an. Cascada `_build_profile()`
   (`oracle_engine.py:652-771`) NU are niciun nivel care să citească aceste
   date — a construit profilul din 1 (unu) meci TheSportsDB per echipă.
2. **P0 — Două sisteme care nu comunică.** Data Layer (Supabase) și
   Prediction Layer există amândouă; Prediction Layer citește însă exclusiv
   Provider Layer. Cititorul `database/queries.get_elo_ratings()` există și
   nu e apelat de nimeni din calea live. ADR-023 (Canonical Live ELO
   Snapshot) a decis deja direcția pentru ELO; Phase 6 („Oracle Switch")
   nu a fost niciodată executată.
3. **P1 — Etichetare înșelătoare a calității datelor.** `DATA_QUALITY_LIVE`
   („✅✅ Date live — statistici reale") se acordă pentru eșantioane de 1 meci
   cu `shots_on_goal = goluri × 3.5` (sintetic) și `possession = 50.0`
   (hardcodat) — `oracle_api.py`, `get_team_last_events_tsdb()`.
4. **P1 — Gol de import, nu de citire, pentru statisticile de meci.**
   Cornere/șuturi/faulturi/cartonașe/goluri la pauză: 0/1.977 rânduri
   populate pentru România (comparativ: La Liga 760/1.140) — pipeline-ul de
   import istoric nu a adus aceste coloane pentru România.

Consecința compusă, demonstrată pe cazul real: predicție construită aproape
exclusiv din fallback-uri, contrazicând simultan piața și propriile date.

## Decizie

**Prediction Engine devine Database-First.** Clarificare arhitecturală
explicită (cerută la aprobare): **providerii rămân sursa de adevăr pentru
ACHIZIȚIA datelor; Supabase devine sursa canonică pentru Prediction Engine
DUPĂ sincronizare.** Supabase nu înlocuiește providerii — înlocuiește doar
accesul DIRECT al Prediction Engine-ului la provideri. Ordinea arhitecturală
a fluxului de date este:

    Providers (achiziție — sursa de adevăr externă)
        ↓
    Sync Pipeline (sync/run_daily.py — aduce datele în casă)
        ↓
    Supabase (sursa canonică INTERNĂ — match_history / elo_ratings)
        ↓
    Prediction Engine

Prediction Engine utilizează Supabase ca sursă canonică în regim normal.
Apelul direct către provideri este permis doar atunci când datele lipsesc
sau sunt insuficiente, conform politicii de fallback de mai jos — ADR-ul
definește fluxul normal, fără să interzică excepțiile legitime (de exemplu,
un meci nou care încă nu a fost sincronizat).

## Principiul de proiectare

**Niciun provider extern nu poate avea prioritate asupra unei informații
deja sincronizate și validate în baza canonică Supabase.**

Această propoziție sintetizează filosofia Database-First și este criteriul
de arbitraj pentru orice situație neacoperită explicit de acest ADR.

Pentru CITIRILE Prediction Engine-ului (formă, goluri medii, ELO, H2H),
ordinea de fallback devine:

    Supabase (sursa canonică internă)
        ↓ (doar dacă datele lipsesc sau sunt insuficiente pentru echipa/liga cerută)
    Provideri externi, apel direct (FreeLF, Odds API, fd.org, TSDB) — excepție, nu regulă
        ↓ (doar dacă și providerii eșuează)
    Fallback sintetic — etichetat EXPLICIT ca atare, niciodată ca „date reale"

Concret, patru schimbări de contract:

- **D1 (P0)**: `_build_profile()` primește un nivel nou, PRIMUL în cascadă,
  care citește forma/gf/ga din `match_history` (meciuri cu `actual_result`
  populat, aceeași disciplină anti-scurgere temporală ca ML-ul).
- **D2 (P0)**: ELO-ul de club se citește din sursa canonică decisă deja de
  ADR-023 — acest ADR nu redecide sursa, ci execută conectarea pe calea de
  servire (echivalentul Phase 6/„Oracle Switch" pentru profil + ML features).
  `eloratings.net` rămâne doar pentru naționale.
- **D3 (P0)**: `_build_h2h()` primește `match_history` ca primă sursă,
  înaintea FreeLF/Odds API.
- **D4 (P1)**: `data_quality` nu mai poate raporta „LIVE — statistici reale"
  pentru eșantioane sintetice sau sub un prag minim de meciuri; fallback-ul
  rămâne permis, dar etichetat onest.

Separat de acest ADR (task de pipeline, nu de arhitectură): backfill-ul
statisticilor de meci pentru România (P1, constatarea 4).

## Ce NU se schimbă (explicit, la cererea arhitectului)

- Formulele ML / xG / Poisson / Monte Carlo — **nu se modifică în această
  serie de PR-uri, fără excepție**. Problema demonstrată e de input, nu de
  model („garbage in → garbage out"); obiectivul seriei D1–D4 este exclusiv
  repararea fluxului de date către Prediction Engine. Orice ajustare de
  model vine ulterior, separat, măsurată pe inputul reparat.
- Rolul providerilor în achiziție — Sync Pipeline continuă să colecteze de
  la provideri exact ca azi; acest ADR nu atinge sincronizarea.
- ADR-034 / Selection Engine — rămâne în shadow mode, neatins; acel sistem
  alege PROVIDERUL pentru fixtures, acest ADR decide SURSA datelor de profil.
- ADR-023 — rămâne autoritatea pentru sursa canonică ELO; ADR-035 doar îl
  execută pe calea de servire.

## Consecințe

- Predicțiile pentru ligile cu istoric bogat în DB (toate cele 9) încetează
  să depindă de disponibilitatea providerilor externi la momentul cererii.
- Costul: fiecare `evaluate_match()` adaugă citiri Supabase (mitigabil prin
  cache-ul existent, decizie de implementare, nu de contract).
- Criteriu de succes măsurabil, nu impresie: re-rularea cazului
  Petrolul–Dinamo după implementare trebuie să arate profiluri construite
  din zeci de meciuri (nu 1), ELO real (nu None/1500-1500) și H2H populat;
  direcția predicției față de piață NU e criteriu de acceptare (piața nu e
  ground truth), dar divergențele extreme cauzate de input fabricat trebuie
  să dispară.
- Implementarea se face în PR-uri mici (D1–D4 separate), fiecare cu teste
  fail-before/pass-after și verificare live, conform Definition of Done.

## Ordinea de execuție (obligatorie — nu se sare peste ea)

1. ✅ Închiderea Fazei 1 (pe scope-ul ei declarat: pipeline fixtures) — 2026-07-19.
2. ✅ Baseline Faza 1 (`BASELINE_FAZA1_2026-07.md`, Frozen) — cu secțiunea
   Known Limitations — 2026-07-19, PR #29.
3. ✅ `DEFINITION_OF_DONE.md` — 2026-07-19, PR #29.
4. ✅ Aprobarea finală a acestui ADR — 2026-07-19 (rev.3).
5. ✅ **Implementare D1 + verificare — FINALIZAT 2026-07-20, PR #30
   (merged `ddf376a`).** Level DB (`match_history`) devine primul nivel
   în `_build_profile()`. Verificat live: cazul central (Petrolul–Dinamo,
   `data_source=supabase-history`, ≥3 meciuri reale) + regresie zero pe
   Premier League/La Liga/Bundesliga/Champions League/World Cup 2026.
   Gardă statică permanentă (`test_oracle_engine_single_profile_construction_point.py`):
   `TeamProfile()` construit într-un singur loc, TSDB apelat exclusiv din
   `_build_profile()`. Review arhitectural: APPROVED FOR MERGE (9 criterii
   verificate cu dovezi din cod/date live — respectarea ADR-035, principiul
   Database-First, unicitatea punctului de construire, integritatea
   cascadei, zero regresii pe cele 9 ligi, ADR-023 neatins, zero atingere
   ML/Poisson/MC/Selection Engine, o singură datorie tehnică minoră
   corectată înainte de merge — docstring).
6. ✅ **Implementare D2 + verificare — FINALIZAT 2026-07-20, PR #32
   (merged `d94d332`).** Execută Phase 6 („Oracle Switch") din ADR-023:
   `database.queries.get_latest_team_elo()` (nouă, bulk-fetch + cache,
   globală per club, fără filtru de ligă) devine sursa PRIMARĂ pentru ELO
   în `_build_profile()`; `oracle_api.get_elo_rating()` rămâne fallback,
   singura sursă reală pentru echipele fără meciuri de club sincronizate
   (naționale). Verificat live: DB câștigă în toate cazurile în care
   există — inclusiv acolo unde diferă de provider (Arsenal 1931 vs 1915,
   Real Madrid 1849 vs 1945, Bayern 1992 vs 1940, PSG 1939 vs 1920);
   Franța cade corect pe fallback; Petrolul 1481/Dinamo 1640 au ELO real.
   Temporal Integrity Review: future leakage exclus structural
   (`actual_result IS NOT NULL`); self-leakage (B→B) clasificat **Known
   Product Contract Gap**, pre-existent, comun D1/D2, în afara scope-ului.
   Decizie separată `elo_source` pe `TeamProfile`: AMÂNAT (D4/ADR dedicat).
7. ✅ **Implementare D3 + verificare — FINALIZAT 2026-07-20 (implementare
   `e0a80f2`, PR #34).** H2H devine Database-First:
   `database.queries.get_h2h_from_history()` (nouă, în `database/queries.py`
   — Decizia 4) întoarce RÂNDURI BRUTE ale confruntărilor directe, globale
   per pereche de cluburi (fără filtru de ligă — Decizia 1, consecvent cu
   ELO-ul global D2). `oracle_engine._build_h2h()` primește un nivel DB
   PRIMAR care recalculează bilanțul din `actual_result`/`actual_home_goals`/
   `actual_away_goals` (Decizia 2 — niciodată coloanele precalculate
   `h2h_modifier`/`h2h_meetings`, contaminate de scrieri concurente), cu
   prag minim 3 confruntări (Decizia 3, `MIN_H2H_MEETINGS`); sub prag →
   cascada FreeLF/Odds existentă, neschimbată. Verificat live: 6 perechi
   reale (Petrolul–Dinamo 8 conf. `-0.0375`, Rapid–Dinamo 10 conf. `0.075`,
   Real Madrid–Atletico 10 conf. `0.03`, Arsenal–Chelsea 10 conf. `0.075`,
   etc.), toate din DB, recalculate global. Temporal Integrity: future/
   replay leakage exclus structural (aceeași gardă ca D1/D2); self-leakage
   = același Known Product Contract Gap, nu nou. Gardă AST extinsă
   (unicitatea punctului de citire H2H). Ce NU s-a implementat: cursa de
   scriere `FEATURE_COLUMNS`/`COALESCE` — documentată separat ca task
   **D3.5 — Feature Canonicalization** (`D3.5-FEATURE_CANONICALIZATION_TASK.md`),
   NEATINSĂ în D3 (Decizia 5).
8. ✅ **Implementare D4 + verificare — FINALIZAT 2026-07-20, PR #37
   (merged `4ba8bb2`).** Honest Data Quality Labeling: `data_quality` nu mai
   raportează „statistici reale" pentru eșantioane sintetice/subțiri.
   Taxonomie finală **LIVE / PARTIAL / ELO / NEUTRAL**; nivel nou `PARTIAL`
   pentru surse agregat/hardcodat/proxy/sintetice (national, freelf,
   scores-api, standings-fd, thesportsdb). `_classify_data_quality()` devine
   PUNCT UNIC de decizie (cele 9 atribuiri inline din `_build_profile`
   eliminate; derivare o singură dată la construcție); LIVE doar pentru
   `supabase-history` cu n≥3 (plasă de siguranță aliniată `MIN_DB_MATCHES`,
   nu prag numeric nou). Text LIVE reformulat: „Date reale — meciuri
   terminate" (definiția A: date din meciuri reale, chiar dacă posesie/
   șuturi folosesc fallback). UI (Stage 2): badge `PARTIAL` (clasă/icon/
   culoare), iconul furnizat exclusiv de `_dq`, note fără emoji (dublu-emoji
   curățat). Gardă AST: `DATA_QUALITY_LIVE` doar în clasificator. Value Bets
   NEATINS → zero schimbare comportamentală; zero migrare (nefolosită de
   ML). Fără ADR nou (execută contractul D4 din ADR-035, ca D1/D3).
   Verificat: 12 teste noi, suită 729 passed, zero regresii, cazul central
   Petrolul–Dinamo (1 meci TSDB) nu mai e „statistici reale".
9. ✅ **Seria Database-First (ADR-035, D1–D4) — ÎNCHISĂ 2026-07-20.** Abia
   acum începe Learning Core (Faza următoare): Challenger Runner →
   Promotion Engine → Champion Manager.

## Dependencies

- ADR-023 (sursa canonică ELO) — executat, nu modificat.
- Auditul din 2026-07-19 (conversația de proiect) — sursa dovezilor;
  cifrele-cheie sunt transcrise în Context ca să rămână trasabile aici.
