# ADR-045 — Single Owner per categorie de date (Data Ownership Model)

**Status**: **APROBAT** (2026-08-03, confirmat prin commit-ul de merge `2345f84` — „Aprobat explicit de proprietarul produsului pentru scriere directa pe main"). Secțiunea „Ce autorizează acest ADR să se implementeze imediat" (cele 4 puncte de Sync Layer — Statistics/Fixtures/H2H/Standings) a fost implementată integral în Pasul 1 al Master Repair Plan (commit `2363158`, merge-uit pe `main` la 2026-08-03). Secțiunea „Ce NU autorizează acest ADR" (repointarea consumatorului din Oracle Engine pentru Standings/H2H) rămâne, deliberat, neimplementată — cere propriul task separat, cu aprobare și testare de non-regresie proprii, verificat 2026-08-10: niciun asemenea task nu a fost încă deschis.

**Autor**: Claude, la cererea proprietarului produsului.

**Data**: 2026-08-03.

**Companion**: rezultă direct din doi audituri complete de proiect (audit general + audit read-only Supabase, 2026-08-03), din Master Repair Plan (sinteza celor două audituri, grupată P0-P6) și din analiza dedicată „Pasul 1 — Single Owner per categorie de date" (aceeași sesiune). ADR-044 (`flashscore-foundation-data-layer.md`) rămâne baza tehnică neschimbată — acest ADR nu modifică schema sau Data Trust Layer-ul descris acolo, doar formalizează cine e responsabil de fiecare categorie de date la nivel de flux de colectare.

---

## Context

Auditul complet al proiectului (2026-08-03) a găsit, verificat direct din cod și din date live în Supabase, mai multe cazuri concrete în care aceeași categorie de date e colectată de mai mulți provideri fără o regulă explicită de prioritate:

- **H2H**: 4 surse paralele — calcul intern din `match_history` (primar în cascada `_build_h2h()`), `freelf_h2h_snapshot`, date derivate din `odds_api_recent_results` (comentate în cod ca „ADR-039 sursă canonică", deși nu e nici măcar primul nivel folosit), și `flashscore_match_context` (canonic, scris, dar **complet orfan** — niciodată citit de cascada reală).
- **Standings**: 3 tabele paralele (`flashscore_standings_snapshot`, `footballdata_team_form_snapshot`, `freelf_team_form_snapshot`) pentru un concept practic identic.
- **Statistics**: Soccer Football Info, FreeLF și Flashscore toate scriu aceleași coloane de bază din `match_history` prin COALESCE (fără corupere de date), dar fără nicio verificare „există deja date complete?" înainte de a apela un provider suplimentar.
- **Fixtures**: Sync Layer (6 provideri, `scheduled_fixtures`) și discovery-ul propriu al Flashscore (`providers/flashscore/discovery.py`) descoperă independent aceleași meciuri, pentru cele 9 competiții pe care Flashscore le urmărește, fără să comunice între ele.

Aceste patru cazuri sunt sursa directă a apelurilor API redundante identificate în audit, contrar principiului explicit al proprietarului produsului: „cota zilnică e critică, nu accept pipeline-uri care interoghează inutil providerii live".

## Principiul nou de arhitectură

**Un tip de informație are UN SINGUR Owner.** Restul providerilor pentru aceeași categorie devin explicit fallback, niciodată surse paralele necoordonate. E interzis ca aceeași categorie de date să fie colectată simultan de mai mulți provideri fără o justificare documentată (scop diferit, acoperire disjunctă). Acest principiu se aplică nu doar celor 12 categorii listate mai jos, ci oricărei categorii noi introduse în viitor — orice provider nou trebuie să declare explicit dacă devine Owner pentru o categorie existentă (necesită acest ADR revizuit) sau doar fallback (nu necesită).

**Flashscore devine providerul principal oriunde poate acoperi complet o categorie** — motivul tehnic fiind Delta Sync-ul real (`is_flashscore_match_already_collected`), care face rulările frecvente ieftine prin design, spre deosebire de restul providerilor API, care re-interoghează integral la fiecare rulare. Limita reală a acestui principiu: Flashscore acoperă azi doar 9 competiții (`FLASHSCORE_TRACKED_COMPETITIONS` — Romania SuperLiga, Champions League, Premier League, La Liga, Serie A, Bundesliga, Ligue 1, Europa League, MLS), exclude deliberat Campionatul Mondial 2026 (identitate URL ambiguă) și nu include Conference League. Pentru orice categorie/ligă în afara acestei acoperiri, Owner-ul rămâne providerul API relevant, neschimbat.

## Decizie — Matricea Owner/Fallback

| # | Categorie | Owner | Fallback | Notă |
|---|---|---|---|---|
| 1 | Fixtures (descoperire meciuri) | **Sync Layer** (6 provideri, priorități P2→P5 neschimbate) | — | Flashscore rămâne DOAR îmbogățire pentru meciurile deja descoperite, nu sursă de descoperire — acoperire parțială (8/9 competiții din `COMPETITIONS_META`, fără Cupa Mondială) |
| 2 | Results (scoruri finale, `actual_result`) | **Dual, pe domenii disjuncte**: `sync/sync_results.py` (football-data.org→Odds API→SFI) pentru ligile acoperite; **Flashscore, explicit** pentru Romania SuperLiga + calificări UEFA (unde football-data.org nu acoperă deloc) | — | Nu mai e „secundar" pentru aceste două competiții — e singurul owner funcțional real, documentat ca atare |
| 3 | Standings (clasament) | **Flashscore** (cel mai complet: rank/won/drawn/lost/goals/points) | football-data.org doar pentru ligile în afara celor 8 acoperite de Flashscore | FreeLF eliminat din acest rol (cotă cronic epuizată, tabel gol azi) |
| 4 | Statistics (corners/shots/possession/cards/fouls/xG) | **Flashscore** (singurul cu date extinse, `match_statistics_extended`, EAV) | Soccer Football Info pentru ligile neacoperite de Flashscore; FreeLF ultimă instanță | |
| 5 | Lineups | **Owner dual, pe scop, nu conflict**: FreeLF = Pre-Match (confirmat, fereastra 4h); Flashscore = Post-Match/Roster | — | Scopuri disjuncte cronologic — nu se elimină niciunul |
| 6 | Player Ratings | **Flashscore** | — | Deja Single Owner, neschimbat |
| 7 | H2H | **Flashscore** (nivel 1, pentru cele 8-9 competiții acoperite) | Cascada existentă neschimbată pentru restul: DB (`match_history`-derived) → FreeLF → Odds API | |
| 8 | Events (cronologie meci) | **Flashscore** | — | Deja Single Owner, neschimbat |
| 9 | Odds | **The Odds API** (canonic, Frozen — ADR-005/006) | — | Flashscore rămâne blocat RAW-only, deliberat (ADR-043, identitate `fixture_id` cross-provider nerezolvată) |
| 10 | Weather | **WeatherAPI** | — | Deja Single Owner, Flashscore nu colectează date meteo |
| 11 | Injuries | **FreeLF** (absențe implicite din lot confirmat — singurul semnal care influențează azi predicția servită) | API-Football rămâne complementar/observațional (shadow-logat, `apifootball_injuries_coaches`) | Deja configurat corect azi |
| 12 | Coaches | **API-Football** | — | Deja Single Owner, Flashscore nu colectează |

## Ce autorizează acest ADR să se implementeze imediat (după aprobare)

**Doar Sync Layer** — modificări izolate care nu ating nicio tabelă citită azi de Oracle Engine în formula servită:

1. **Statistics** (#4) — adaugă o verificare „Flashscore are deja date complete pentru acest meci?" (`flashscore_data_completeness`/`match_statistics_extended`) înainte ca `sync_match_statistics.py` să apeleze Soccer Football Info/FreeLF.
2. **Fixtures** (#1) — `providers/flashscore/discovery.py` citește `scheduled_fixtures` pentru meciurile deja descoperite acolo, în loc să re-caute independent, pentru cele 8 competiții comune.
3. **H2H** (#7, doar partea Sync Layer) — `sync/sync_h2h_freelf.py` sare peste meciurile din competițiile unde `flashscore_match_context` are deja context complet.
4. **Standings** (#3, doar partea Sync Layer) — `sync/sync_team_form_footballdata.py` sare peste ligile acoperite complet de `flashscore_standings_snapshot`.

## Ce NU autorizează acest ADR — rămâne task separat, cu aprobare separată

Repointarea efectivă a **consumatorului** din Oracle Engine (`_build_profile()` pentru Standings §3, `_build_h2h()` pentru H2H §7) către noul Owner Flashscore **nu e autorizată de acest ADR**. Motiv: orice schimbare acolo poate modifica `form_score`/`h2h_modifier` folosite în calibrarea xG servită — cere propriul task, cu testare explicită de non-regresie, exact disciplina deja aplicată la integrarea Team DNA (Faza 3). Până la acel task separat, **niciun sync existent nu se oprește** — chiar dacă Owner-ul „de drept" devine Flashscore pentru Standings/H2H, sincronizarea football-data.org/FreeLF pentru aceste categorii **continuă neschimbată**, ca să nu înghețe tacit datele pe care Predictorul le citește azi (Regula #8 — nicio stare necunoscută nu se aproximează).

Predictorul, ML-ul și Streamlit-ul rămân complet neatinse de acest ADR.

## Consecințe

**Pozitive**:
- Elimină 4 clase concrete de apeluri API redundante, fără nicio schimbare de comportament al Predictorului.
- Închide ambiguitatea „cine e sursa de adevăr" pentru H2H și Standings, unde existau azi 3-4 pretenții necoordonate.
- Stabilește o regulă reutilizabilă pentru orice provider nou introdus în viitor.

**Negative/costuri**:
- Owner-ul Flashscore pentru Standings/H2H rămâne „pe hârtie" până la task-ul separat de repointare a Oracle Engine — o perioadă în care decizia formală și comportamentul real al sistemului nu coincid complet (documentat explicit aici, nu ascuns).
- Discovery-ul Flashscore repointat la `scheduled_fixtures` (#1) introduce o dependență nouă: dacă Sync Layer nu găsește un meci, Flashscore nu-l va găsi nici el (pierdere de acoperire posibilă față de discovery-ul independent de azi) — necesită verificare de non-regresie înainte de activare.

## Aprobare

```
[x] Aprobat de proprietarul produsului — data: 2026-08-03
```

Confirmat prin commit-ul de merge `2345f84` pe `main` (2026-08-03): „Aprobat explicit de proprietarul produsului pentru scriere directa pe main". Checkbox-ul a rămas nebifat în acest document până la 2026-08-10 — gol de sincronizare a documentației, nu de aprobare reală; corectat acum, retroactiv, la cererea proprietarului produsului.

Matricea Owner/Fallback e azi APROBATĂ integral. Implementarea rămâne parțială, deliberat: cele 4 modificări de Sync Layer autorizate direct (Statistics/Fixtures/H2H/Standings) sunt live pe `main`; repointarea consumatorului Oracle Engine pentru Standings/H2H (explicit NEautorizată de acest ADR, vezi secțiunea de mai sus) rămâne un task separat, neînceput.

---

## Addendum 3 — repointarea consumatorului Oracle Engine (Standings + H2H), 2026-08-10

**Aprobat explicit de proprietarul produsului** ("mergi și nu te opri până nu termini") — task-ul separat cerut mai sus în document ("Ce NU autorizează acest ADR") a fost deschis, cu testare de non-regresie proprie, exact disciplina cerută.

**Corectare a unei cifre stale**: textul original (2026-08-03) spune „Flashscore acoperă azi doar 9 competiții"/„8 competiții" — verificat live la 2026-08-10, `FLASHSCORE_TRACKED_COMPETITIONS` are azi **14 ligi** (Primeira Liga/Eredivisie/Super Lig/HNL adăugate 2026-08-04, Conference League 2026-08-05, toate ULTERIOARE redactării acestui ADR). Campionatul Mondial rămâne exclus deliberat (identitate URL ambiguă), neschimbat.

### H2H (#7) — NICIO schimbare de cod, confirmat necesară

Investigație înainte de implementare: `flashscore_match_context` (categoria `h2h_overall`) se scrie DOAR pentru meciuri deja JUCATE (enrichment post-meci) — rulările automate au oprit deja explicit scraping-ul pentru meciuri viitoare (Pasul 1, mai sus în acest document). Pentru un meci viitor de prezis, acest tabel nu are niciun rând legat de el — nu poate fi citit direct în `_build_h2h()`.

În schimb, `database.queries.get_h2h_from_history()` (Level DB, citit PRIMUL în `_build_h2h()`) interoghează `match_history` fără niciun filtru de `source`/`fixture_id`/provider — rândurile scrise de Flashscore pentru cele 14 competiții tracked (Faza 2/3, `persist_match_foundation_data()`) sunt deja incluse identic cu orice alt provider. **H2H e deja, de facto, Flashscore-primar pentru acele competiții, prin cascada DB existentă** — cascada rămâne EXACT cum spune rândul #7: DB → FreeLF → Odds API, neschimbată.

Dovadă mecanică, nu doar afirmație: `tests/test_database_queries_h2h_canonical.py` — `test_query_has_no_source_or_fixture_id_filter()` (interogarea nu filtrează după sursă) + `test_flashscore_sourced_rows_returned_identically_to_any_other_provider()` (un rând cu `fixture_id="flashscore_..."` e întors identic cu orice alt provider).

### Standings (#3) — implementat, nivel nou în `_build_profile()`

**Blocaj găsit înainte de implementare**: `flashscore_standings_snapshot` persista doar totaluri de sezon (won/drawn/lost), fără nicio secvență cronologică — `feature_engine.compute_form_score()` cere explicit ordine cronologică (cel mai recent ULTIM). O aproximare (ex. „mereu W", tiparul deja existent la FreeLF) ar fi încălcat Regula #8.

**Rezolvare**: pagina de clasament Flashscore are o coloană FORM cu bagde-uri per echipă (`data-testid="wcl-badgeForm-{win,draw,lose,unknown}"`), confirmată live prin POC izolat (2026-08-10) — ordine DOM = ordine cronologică reală, cel mai vechi primul. Confirmat independent și pe fixture-ul deja existent în proiect (`docs/06_UDAL/poc_evidence/flashscore_full_tabs_poc/standings.html`) — tab-ul de clasament relativ la meci și pagina directă de ligă randează identic structural.

**Implementare**:
- Migrația 045 (`database/migrations/045_flashscore_standings_form.sql`) — `flashscore_standings_snapshot.form TEXT[]`.
- `providers/flashscore/normalizer.py::_extract_standings_form()` — extrage secvența W/D/L (badge-urile „unknown"/„?" excluse explicit, nu sunt un rezultat real), cablată în `normalize_standings()`.
- `database/queries.py::get_standings_snapshot()` — selectează și `form`.
- `oracle_engine.py::_build_profile()` — nivel nou „Level FS", între Level DB/Level -1 (național) și Level 0+1 (FreeLF): citește `get_team_standings_row()`, folosește `form` reală pentru `results` (nu placeholder sintetic). Nu se activează dacă `form` e goală — cascada continuă la FreeLF/football-data, nu se aproximează cu date insuficiente.
- Nu s-a atins nimic din fluxul de fetch existent (nicio pagină nouă vizitată) — doar extragere suplimentară din HTML deja fetch-uit.

Teste: `tests/test_providers_flashscore_foundation_data_layer.py` (extracție `form`, contra fixture real + cazuri sintetice de robustețe), `tests/test_oracle_engine_flashscore_standings.py` (7 teste — prioritate față de FreeLF, ordine cronologică păstrată până la `compute_form_score()`, degradare fără excepție, Level DB câștigă și Flashscore nu mai e interogat deloc când DB are deja destule meciuri).

Suită completă după implementare: vezi commit-ul acestei modificări pentru numărul exact de teste trecute.
