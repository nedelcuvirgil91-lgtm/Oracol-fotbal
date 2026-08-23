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

Se completează pe măsură ce fazele avansează.
