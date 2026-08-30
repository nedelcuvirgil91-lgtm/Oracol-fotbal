# ADR-070 — Corectarea datei de start pe rânduri Flashscore deja scrise

**Status**: Accepted (2026-08-30, aprobat explicit de proprietarul produsului — „aprob")
**Autor**: Claude (arhitect principal, sesiune delegată explicit)
**Declanșator**: proprietarul produsului a raportat că meciuri reale de azi (Romania SuperLiga, 30 august) nu apăreau în aplicație, deși existau meciuri jucate azi verificate personal.
**Atinge contractul**: al doilea scriitor pe `match_history.kickoff_date`/`league` (ADR-036, Canonical Feature Ownership)
**Nu atinge**: `_upsert_match_canonical_locked` (migrarea 048 rămâne mecanismul, refolosit ca atare), `discovery_live_cascade_enabled` (ADR-063), sursele de descoperire (Flashscore rămâne singura sursă)

---

## Context

`match_history` conține rânduri scrise de Flashscore Foundation Data Layer cu
**dată placeholder**, nu data reală confirmată. Motivul: Flashscore publică o
etapă întreagă cu ~2-3 săptămâni înainte, cu o oră generică (de obicei 17:00)
pentru toate meciurile deodată — orele reale, confirmate per meci, apar abia
cu câteva zile înainte de fluier.

### Cazul concret, verificat live (2026-08-30)

Etapa Romania SuperLiga din 28-31 august a fost descoperită de Flashscore pe
**10 august**, cu toate cele 8 meciuri scrise cu `kickoff_date = 2026-08-29
17:00:00` — identic, pentru toate. Verificat prin surse externe independente
(căutare web, 4+ site-uri de pariuri/presă sportivă):

| Meci | Dată înregistrată | Dată reală confirmată |
|---|---|---|
| Farul Constanța – Botoșani | 29 august, 17:00 | **30 august, 13:00 UTC** (16:00 RO) |
| FCSB – UTA Arad | 29 august, 17:00 | **30 august, 18:00 UTC** (21:00 RO) |
| Rapid – Universitatea Craiova | 29 august, 17:00 | **31 august** (data exactă neconfirmată încă) |

Consecință directă: cele două meciuri de azi (30 august) erau invizibile în
aplicație — `oracle_api.get_matches_for_week()` (Database-First, ADR-053) le
arăta cu data de ieri, deja trecută, fără rezultat — o predicție Oracle
înainte de fluier era imposibilă.

### De ce nu se corectează singur (mecanismul existent, verificat)

Delta Sync are deja, din 5 august, o regulă corectă: un meci fără
`actual_result`, cu `kickoff_date` clar în trecut, NU se sare la nesfârșit —
se reîncearcă (`database.queries.is_flashscore_match_already_collected()`).
Iar `flashscore_weekly_fixtures.yml` (singurul workflow dedicat descoperirii
de meciuri VIITOARE prin Flashscore) rulează de 2 ori/săptămână (luni, joi) și
folosește exact acest mecanism.

Problema e strict de **cadență, nu de mecanism**: ultima rulare înainte de
etapa curentă a fost **joi, 27 august, 06:56 UTC** — moment în care data
înregistrată greșit (29 august) era ÎNCĂ în viitor, deci Delta Sync a
considerat starea „normală" și a sărit meciurile. Următoarea rulare
programată: **luni, 31 august** — după ce ambele meciuri de azi s-ar fi jucat
deja. Runda cade structural între cele două verificări.

### De ce NU se folosește TSDB ca sursă de corectare (opțiune respinsă)

Măsurat deja în ADR-063, pe date reale: TSDB are **0% acoperire unică** — din
22 de meciuri aduse de TSDB în sezonul curent, toate 22 erau deja văzute de
Flashscore. TSDB nu descoperă niciodată ce Flashscore nu vede, doar câștigă
uneori cursa de a scrie primul rândul. Folosirea lui ca sursă de corectare a
datei ar fi introdus o a doua sursă de adevăr nedovedită, fără nicio garanție
de acoperire completă — exact riscul semnalat explicit de proprietarul
produsului înainte de acceptarea acestui ADR.

## Decizie

**Flashscore rămâne singura sursă — doar verificat mai des.**

`providers/flashscore/pre_match_odds.py` vizitează deja `/fixtures/` pentru
toate cele 17 ligi urmărite, **de 2 ori/zi** (08:00 și 20:00 UTC, cron
`sync_pre_match_odds.yml`) — de 7× mai des decât `flashscore_weekly_
fixtures.yml`. Extrage deja, per meci, data confirmată curentă
(`normalize_upcoming_match()`), dar azi o folosește STRICT ca să decidă
fereastra de cote (ADR-043), fără s-o compare cu `match_history`.

1. **Funcție nouă**, `database.queries.correct_flashscore_kickoff_if_mismatched()`
   — citește rândul existent pe `fixture_id`, compară doar componenta de
   dată (`YYYY-MM-DD`) cu ce a extras Flashscore acum. Corectează DOAR dacă:
   (a) rândul există, (b) `actual_result IS NULL` (niciodată un meci deja
   jucat — ar rescrie istoric fals), (c) data diferă.
2. **Scriere prin RPC-ul deja existent**, `upsert_match()` →
   `upsert_match_canonical` → ramura de reprogramare din migrarea 048
   (`_upsert_match_canonical_locked`) — **NU e un writer nou**, e ACELAȘI
   mecanism deja dovedit live (Celta Vigo–Osasuna), invocat dintr-un loc nou.
   `COALESCE` non-destructiv pe restul coloanelor — payload minim
   (fixture_id, home_team, away_team, league, kickoff_date), nimic altceva
   nu se atinge.
3. **Flag nou**, `flashscore_kickoff_correction_enabled`, implicit `False`
   (North Star #3) — `flashscore_kickoff_correction_config.py`, tipar identic
   `flashscore_odds_fallback_config.py` (ADR-043). Activarea e o operație
   separată, explicită, pe `model_config`, cu SQL arătat înainte (regula
   `supabase-safety`).
4. **`persist_week_odds()` rulează corecția pentru FIECARE meci descoperit**,
   indiferent dacă are cotă găsită sau nu — corectarea datei e independentă
   de disponibilitatea cotelor (un meci fără cotă publicată încă tot poate
   avea o dată greșit înregistrată).

## Ce NU schimbă acest ADR

- Nicio sursă nouă de descoperire — Flashscore rămâne singura.
- `discovery_live_cascade_enabled` (ADR-063) neatins — TSDB rămâne activ doar
  ca plasă de siguranță pentru ligi complet absente din `match_history`, nu
  ca sursă de corectare a datei.
- `flashscore_weekly_fixtures.yml` neatins — rămâne mecanismul de fond,
   2×/săptămână, pentru descoperirea de meciuri complet noi.
- Migrarea 048 / `_upsert_match_canonical_locked` — refolosită identic, nicio
  modificare de schemă sau de RPC.
- Niciun meci cu `actual_result` deja scris nu poate fi atins — corecția
  citește explicit acest gardă înainte de orice scriere.

## Consecințe

**Pozitive**
- Fereastra de eroare scade de la „până la 2× durata dintre rulările
  săptămânale" (poate depăși durata unei etape întregi) la „până la 12 ore"
  (cadența `sync_pre_match_odds.yml`).
- Zero sursă nouă, zero risc de duplicat sau conflict de identitate — RPC-ul
  deja are garda `hard_conflict` pentru cazul în care data nouă e deja
  ocupată de alt rând.
- Corectarea beneficiază automat toate cele 4 fluxuri care apelează
  `get_matches_for_week()` (odds_persistence, weather_forecast, team_health,
  Challenger Shadow Batch), nu doar servirea live din `app.py`.

**Negative, acceptate**
- Al doilea loc care poate scrie `kickoff_date`/`league` pe `match_history`
  (ADR-036) — mitigat prin reutilizarea RPC-ului existent (nicio semantică
  nouă de scriere) și prin flag implicit oprit.
- Nu acoperă cazul în care Flashscore însuși n-a actualizat încă ora reală
  la momentul rulării `pre_match_odds.py` (ex. o etapă anunțată cu mai puțin
  de 12h înainte de prima verificare) — rămâne un gol rezidual, mai mic
  decât cel actual, nu eliminat complet.

## Jurnal de execuție

De completat după implementare + activare.
