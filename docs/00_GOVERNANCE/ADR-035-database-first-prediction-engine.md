# ADR-035 — Database-First Prediction Engine

**Status**: PROPUS — necesită aprobare explicită înainte de orice implementare

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

**Prediction Engine devine Database-First.** Ordinea de citire pentru orice
componentă a profilului de echipă (formă, goluri medii, ELO, H2H) devine:

    Supabase (match_history / elo_ratings)
        ↓ (doar dacă datele lipsesc sau sunt insuficiente)
    Provideri externi (FreeLF, Odds API, fd.org, TSDB)
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

- Formulele ML / xG / Poisson / Monte Carlo — problema demonstrată e de
  input, nu de model („garbage in → garbage out"); modelele nu se ating
  până când inputul nu e reparat și efectul măsurat.
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

## Dependencies

- ADR-023 (sursa canonică ELO) — executat, nu modificat.
- Auditul din 2026-07-19 (conversația de proiect) — sursa dovezilor;
  cifrele-cheie sunt transcrise în Context ca să rămână trasabile aici.
