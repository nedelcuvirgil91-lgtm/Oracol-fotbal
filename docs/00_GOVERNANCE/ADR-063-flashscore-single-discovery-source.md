# ADR-063 — Flashscore e sursa unică de descoperire a meciurilor

**Status**: Accepted (2026-08-23, aprobat explicit de proprietarul produsului)
**Autor**: Claude (arhitect principal, sesiune delegată explicit)
**Declanșator**: audit de duplicate pornit de la o întrebare a proprietarului produsului („de ce avem doar 15 echipe cu 5 meciuri?"), care a scos la iveală o clasă de poluare recurentă provenită din surse secundare de descoperire.

## Context

`oracle_api.get_matches_for_week()` e Database-First (ADR-053): interoghează întâi `match_history`, iar o **cascadă live cu 6 provideri** rulează DOAR pentru ligile fără niciun rând în fereastra cerută („gaură reală"):

1. Odds API · 2. Free Live Football · 3. football-data.org · 4. ESPN · 5. TheSportsDB · 6. API-Football

Când cascada descoperă un meci, `oracle_engine._cache_prediction()` creează un rând în `match_history` cu `fixture_id` purtând prefixul sursei. Dacă aceeași partidă e descoperită și de Flashscore, dar cu **alt nume de echipă** sau **altă dată**, rezultă două rânduri canonice pentru un singur meci real — duplicat permanent, invizibil pentru reconcilierea de identitate (care cheie pe `(gazdă, oaspete, dată)`).

### Măsurători care au motivat decizia (verificate live, 2026-08-23)

**Acoperire** — Flashscore acoperă **15 din cele 16 ligi prezise** (`ODDS_SPORT_KEYS`); singura neacoperită e `World Cup 2026`, turneu deja încheiat. Flashscore acoperă în plus Conference League și HNL.

**Contribuție reală în sezonul curent** (rânduri create, `kickoff_date >= 2026-07-01`):

| Sursă | Rânduri | Ligi | Acoperire unică |
|---|---|---|---|
| flashscore | 938 | 17 | — |
| tsdb | 22 | 5 | **zero** (toate 5 deja la Flashscore) |
| odds | 18 | 2 | 17 × World Cup 2026 (încheiat) |
| espn | 4 | 1 | 4 × World Cup 2026 (încheiat) |

**Dovada decisivă că sursele secundare nu aduc informație**: din cele 15 rânduri `tsdb_*` din Romania SuperLiga, **13 au `home_xg_actual` populat**. `oracle_api._parse_tsdb_event()` nu scrie niciun câmp de xG (verificat direct în cod), iar singurul scriitor al coloanei e `providers/flashscore/normalizer.py`. Deci Flashscore a văzut acele meciuri și le-a îmbogățit pe rândurile deja create de TSDB, potrivindu-le pe cheia naturală. **Sursa secundară nu descoperă meciuri pe care Flashscore nu le vede — doar câștigă uneori cursa de a crea rândul primul.**

**Costul poluării**: 3 duplicate confirmate din 22 de rânduri TSDB (13,6%), fiecare cerând investigație manuală și corecție supervizată:

| Duplicat | Perechea reală | Cauză |
|---|---|---|
| `tsdb_2502947` „Corvinul Hunedoara" – Csíkszereda, 20 iul | `flashscore_dx4pgX44` „Corvinul" – Csíkszereda, 3-0 | variantă de nume |
| `tsdb_2502971` Petrolul – Oțelul, **7 aug** | `flashscore_bNX27rsC` Petrolul – Oțelul, **9 aug**, 1-0 | dată diferită |
| `tsdb_2482525` Rijeka – „Dinamo Zagreb", 8 aug | `flashscore_W4Nlhbwh` Rijeka – „Din. Zagreb" | variantă de nume |

Verificat că normalizarea NU rezolvă problema: `normalize_team_name("Corvinul Hunedoara")` → `"Corvinul Hunedoara"`, `normalize_team_name("Din. Zagreb")` → `"Din. Zagreb"` — alias-urile lipsesc. Argumentul proprietarului produsului, acceptat: întreținerea unui vocabular de alias-uri pentru N surse e o muncă recurentă nelimitată, iar cazul cu dată diferită nu s-ar rezolva nici cu vocabular complet.

## Decizie

1. **Flashscore e sursa unică autorizată să creeze rânduri noi în `match_history`** pentru ligile urmărite.
2. Cascada live cu 6 provideri devine **gatată de un flag nou**, `discovery_live_cascade_enabled`, **implicit `True`** — deci merge-ul acestui ADR nu schimbă nimic la deploy (North Star #3: niciun flag nou nu modifică singur comportamentul). Oprirea efectivă e o operație separată, explicită, pe `model_config`.
3. **Codul cascadei NU se șterge.** Reactivarea trebuie să fie un `UPDATE` de o linie, nu un deploy — Flashscore e un scraper, cu o excepție dedicată (`FlashscoreProtectionDetected`) care confirmă că blocarea e un scenariu real.
4. Când cascada e oprită, fluxul cade natural pe fallback-ul deja existent către `scheduled_fixtures` (`oracle_api.py`, linia ~1600) — care e tot o sursă Flashscore. Plasa de siguranță rămâne, dar din aceeași sursă.

## Ce NU schimbă acest ADR

- **Odds API rămâne neatins ca furnizor de cote.** Verificat: atașarea cotelor se face DUPĂ cascadă, prin `_attach_odds()` / `_attach_primary_odds_from_history()` / `_attach_flashscore_odds_fallback()` (liniile 1610-1612) — complet independentă de descoperire.
- API-Football rămâne neatins ca sursă de accidentări (`team_health_snapshot`).
- Importurile istorice (kaggle, football-data.org, openfootball) — inactive de luni de zile, neatinse.
- Reconcilierea de identitate (ADR-059) și vocabularul (`mappings.py`) — neschimbate.
- Nicio ștergere de secret sau variabilă de mediu (regula „nicio curățenie preventivă" din `CLAUDE.md`).

## Consecințe

- Poluarea prin duplicate din surse secundare se oprește la sursă, nu se tratează după fapt.
- Se pierde descoperirea pentru `World Cup 2026` — acceptat: turneul e încheiat. Dacă reapare o competiție neacoperită de Flashscore, decizia se reevaluează (flag-ul e acolo).
- Riscul concentrării pe un singur scraper e acceptat conștient, compensat prin: (a) flag de reactivare instantă, (b) fallback intern pe `scheduled_fixtures`, (c) alarmă nouă de monitorizare care semnalează o ligă urmărită rămasă fără descoperire Flashscore.

## Jurnal de execuție

Executat 2026-08-23.

**Faza 1 — flag + gating**: `discovery_live_cascade_enabled` (implicit `True`), `oracle_api._live_cascade_enabled()` + gate în `_fetch_live_week_matches()`. Codul cascadei neatins. 8 teste noi, verificate prin mutație (fallback `True`→`False` prins de 3 teste; scurtcircuitarea gate-ului înaintea providerilor, de alte 2).

**Faza 2 — curățarea duplicatelor**: executate 2 din 3, cu confirmare explicită separată.

| Rând marcat | Superseded de | Dovadă |
|---|---|---|
| 126718 `tsdb_2502947` „Corvinul Hunedoara" | 126756 `flashscore_dx4pgX44` (3-0, xG 2,81) | varianta de nume apare EXCLUSIV pe rândul duplicat (1 din 10 apariții) |
| 127060 `tsdb_2502971` Petrolul–Oțelul 7 aug | 131039 `flashscore_bNX27rsC` 9 aug (1-0, xG 1,39) | aceleași echipe, aceeași partidă tur |

Al treilea (HNL, Rijeka–Zagreb) **oprit deliberat** per Discovery Rule: superseding-ul cerea o decizie de vocabular care nu era în planul aprobat — vezi mai jos.

**Descoperire în afara scopului aprobat (Discovery Rule, prezentată proprietarului produsului)**: o clasă întreagă de fragmentare, invizibilă până acum. Formele abreviate Flashscore coexistă cu forme lungi istorice, pentru același club:

| Formă abreviată | Formă lungă | Efect măsurat |
|---|---|---|
| `Din. Zagreb` (7 meciuri, ELO **1607**) | `Dinamo Zagreb` (18 meciuri, ELO **1563**) | două lanțuri ELO paralele; cel nou a pornit de la 1500, ignorând 18 meciuri de istoric — ~63 puncte, peste pragul „material" de 50 din `measure_elo_divergence.py` |
| `St. Mirren` | `St Mirren` | diferă doar prin punct |
| `St. Truiden` | `St Truiden` | diferă doar prin punct |
| `St. Gilloise` | `Union Saint-Gilloise` | de verificat |

Detecția D2/D3 de până acum (ADR-060) cerea ca cele două nume să se fi ÎNTÂLNIT într-un meci; aceste perechi nu s-au întâlnit niciodată, deci erau structural invizibile. Decizie a proprietarului produsului: forma canonică e cea lungă (`Dinamo Zagreb`). Unificarea propriu-zisă rămâne un pas separat, cu verificare per pereche.

**Faza 3 — monitorizare**: `scripts/check_data_health.py` + `check_data_health.yml` (zilnic 07:30 UTC, oră verificată liberă de coliziuni). Patru clase raportate, fiecare găsită azi din întâmplare: fixture-uri stale, duplicate pe cheie naturală, forme abreviate, și ligi urmărite fără descoperire Flashscore (alarma care înlocuiește plasa de siguranță). 11 teste pe funcția pură de detecție.

Notabil: primul test de mutație pe garda anti-împerechere-greșită **a eșuat** — testul trecea din alt motiv decât cel intenționat (`Lok. Zagreb` era sărit ca fiind el însuși abreviere, nu datorită potrivirii pe inițială). Garda era netestată. Corectat cu un caz în care forma concurentă NU e abreviere (`Lokomotiva Zagreb`), reverificat prin mutație.

**Faza 4 — două defecte ale monitorizării, găsite la PRIMA rulare pe date reale** (nu la testarea unitară — motiv pentru care rularea imediată contra producției e parte din proces, nu opțională):

- *Clasa 3 filtra pe sezonul curent* și rata exact fragmentarea pe care trebuia s-o vadă: forma lungă trăiește de obicei DOAR în istoric, cea abreviată doar în sezonul curent. Concret: perechea Zagreb apărea doar fiindcă duplicatul HNL necurățat lăsase un rând `Dinamo Zagreb` în sezon — la curățarea lui, monitorizarea ar fi încetat să raporteze fragmentarea reală. Corectat: scanează tot istoricul (doar cele 2 coloane de nume).
- *Clasa 1 nu separa competițiile încheiate*: World Cup 2026 producea 19 din 31 de constatări — zgomot permanent sub care semnalul real rămânea ascuns. Corectat: o competiție fără niciun meci viitor programat e raportată ca o linie de context.

**Rezultatul rulării corectate** (`run 32645956334`): clasa 1 separă corect (20 în competiții încheiate vs. semnalul real din ligile active); clasa 2 = **0 duplicate pe cheie naturală**; clasa 3 găsește acum **3 perechi**, nu 1:

| Formă abreviată | Formă lungă |
|---|---|
| `Din. Zagreb` (13) | `Dinamo Zagreb` (19) |
| `St. Mirren` (7) | `St Mirren` (**147**) |
| `St. Truiden` (6) | `St Truiden` (**149**) |

**Precizare importantă**: această clasă NU e cauzată de cascadă. `St Mirren` (147) vine din importurile istorice, `St. Mirren` (7) e forma Flashscore — fragmentare între Flashscore și date istorice, nu între surse de descoperire. Oprirea cascadei nu o previne; rămâne un gol separat, acum vizibil și monitorizat.

**Faza 5 — oprirea efectivă a cascadei** (2026-08-23 14:43 UTC, confirmare explicită separată, per `supabase-safety`): `UPDATE model_config SET data = jsonb_set(data, '{discovery_live_cascade_enabled}', 'false') WHERE id = 1`. Verificat în același apel că restul configurației rămâne neatinsă (`learning_core_enabled: true`, `blend_v1_champion_display_enabled: true`, `flashscore_limit_per_league_automated: 50`). Reversibil instant prin `'true'`, fără deploy.

Ordinea a fost respectată deliberat: monitorizarea activă și verificată pe date reale ÎNAINTE de a da la o parte plasa de siguranță.

**Rulare completă**: `pytest tests/` — **2.627 passed, 2 skipped**.

---

## AMENDAMENT (2026-08-23, câteva ore după acceptare) — decizia inițială a fost PREA LARGĂ

Proprietarul produsului a ridicat o obiecție arhitecturală corectă, care a schimbat concluzia: **descoperirea meciurilor și colectarea datelor sunt două probleme diferite, iar acest ADR le-a tratat ca pe una singură.**

Verificat în cod, după obiecție:

| Mecanism | Ce face | Poate CREA rânduri? | Poluează? |
|---|---|---|---|
| `oracle_api._fetch_live_week_matches()` | descoperă meciuri **viitoare** | **Da** | da — sursa celor 3 duplicate |
| `sync/sync_results.py` | colectează **rezultate** ale meciurilor jucate | **Nu** — `update_results_in_supabase()` face doar `.update()` pe rânduri existente, potrivite pe cheia naturală; dacă nu găsește → `not_found += 1`, `continue` | nu poate |

**Consecință**: obiectivul „Flashscore se ocupă de colectarea datelor" era **deja satisfăcut de arhitectură** — sursele secundare de rezultate nu pot crea rânduri, deci nu pot polua. Nu era nimic de oprit acolo.

Iar cascada oprită e exact cea unde redundanța e utilă: dacă Flashscore ratează un meci viitor, alt provider îl completează, iar acoperirea rămâne totală. Costul măsurat (3 duplicate în 2 luni) e acum prins de monitorizarea din Faza 3, care raportează 0 duplicate pe cheie naturală.

**Cascada a fost REACTIVATĂ** (2026-08-23 14:58 UTC): `discovery_live_cascade_enabled` → `true`.

**Ce rămâne valabil din acest ADR**: flag-ul, gating-ul, testele, monitorizarea, curățarea duplicatelor și întregul audit al providerilor. Mecanismul de oprire există și e testat — dacă redundanța la descoperire devine vreodată un cost net, se oprește cu o linie de config.

**Ce s-a dovedit greșit**: presupunerea că sursa duplicatelor e „colectarea de date". Am pornit de la simptom (`fixture_id` de la surse secundare) și n-am verificat că descoperirea și colectarea sunt mecanisme distincte — verificarea era la o comandă distanță.

### Riscul concret creat de oprire, descoperit imediat după

La verificarea propriei schimbări (nu la o rulare programată), s-a constatat că `flashscore_weekly_fixtures.yml` — **singurul** workflow care descoperă meciuri VIITOARE — eșuase pe 17 și 20 august; ultima rulare reușită: **13 august**. `night_sync` nu acoperă acest gol: descoperă din `/results/`, iar `/fixtures/` e doar fallback care nu se încearcă niciodată când `/results/` are conținut (comentariu explicit în `discovery.py`).

Dovada că plasa chiar era folosită: singurul meci Europa League din următoarele 7 zile venise din **TSDB** — exact sursa oprită.

Auditul de acoperire („Flashscore acoperă 15/16 ligi") fusese făcut pe date **istorice**; nu verificasem că descoperirea de fixture-uri VIITOARE funcționează în prezent. Informația era disponibilă — `CLAUDE.md` documentează eșecul din 17 august.

**Reparat prin migrarea 048** (vezi `database/migrations/048_upsert_canonical_handle_reschedule.sql`).
