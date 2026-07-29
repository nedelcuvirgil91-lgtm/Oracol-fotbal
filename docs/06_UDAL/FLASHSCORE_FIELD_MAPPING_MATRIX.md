# Flashscore Field Mapping Matrix — Flashscore field → Supabase table → Supabase column

**Scop**: matrice completă, verificată direct în cod (`providers/flashscore/normalizer.py`) și în fixture-ul real (`docs/06_UDAL/poc_evidence/flashscore_full_tabs_poc/`), pentru fiecare informație documentată în `UDAL_FLASHSCORE_FULL_TABS_POC_REPORT.md`. Fiecare rând NEmapat are un motiv EXACT — evidență de cod/DOM, nu „nu există sursă curată" generic.

**Corectură importantă găsită în timpul construirii acestei matrici** (secțiunea 0) — un caz exact de genul cerut: informație prezentă real în POC, afirmată anterior ca neextractibilă, dovedită acum falsă.

---

## 0. Corectură — timeline-ul de evenimente (goluri/cartonașe/schimbări) ESTE extractibil

`providers/flashscore/normalizer.py` afirmă azi, în docstring-ul modulului (linia 31-33):

> „match_events: DOAR substitutii (...) goluri/cartonase NU au minut vizibil in structura verificata — deferred, nu ghicit."

**Această afirmație e falsă, demonstrat acum direct pe fixture-ul `summary.html`.** Există un container `.smv__participantRow` (21 de rânduri pe acest meci) cu structură complet curată:

```html
<div class="smv__participantRow smv__homeParticipant">
  <div class="smv__incident">
    <div class="smv__timeBox">8'</div>
    <div class="smv__incidentIcon">
      <svg data-testid="wcl-icon-incidents-goal-soccer">...</svg>
    </div>
    <a class="smv__playerName">Soro A.</a>
    <div class="smv__assist">( Pop A. )</div>
  </div>
</div>
```

Verificat pe toate cele 21 de incidente reale ale acestui meci:

| Tip eveniment | Identificare | Câte pe acest meci |
|---|---|---|
| Gol | `[data-testid="wcl-icon-incidents-goal-soccer"]` | 4 |
| Penalty gol | `[data-testid="wcl-icon-incidents-penalty-goal"]` | 1 |
| Cartonaș galben | `svg.card-ico.yellowCard-ico` | 3 |
| Cartonaș roșu | `svg.card-ico.redCard-ico` | 1 |
| Schimbare | `[data-testid="wcl-icon-incidents-substitution"]` | 10 |
| VAR | `[data-testid="wcl-icon-incidents-var"]` | 1 |
| **Total** | | **20** (+1 rând fără icon = 21, de investigat separat) |

Fiecare rând are: **minut** (`.smv__timeBox`, inclusiv prelungiri „45+6'"), **echipă** (`smv__homeParticipant`/`smv__awayParticipant`), **jucător** (`.smv__playerName`). Pentru goluri: **assist** (`.smv__assist`, text între paranteze). Pentru schimbări: **jucătorul care intră** (`.smv__playerName`) ȘI **jucătorul care iese** (`[class*="incidentSubOut"]`) — mai complet decât sursa folosită azi (tab-ul Lineups). Pentru cartonașe: **motivul** (`.smv__subIncident`, ex. „(Foul)", „(Unsportsmanlike conduct)").

**De ce nu e mapat azi**: nu din lipsă de sursă — sursa există, e curată, verificată acum pe date reale. E neimplementat pentru că afirmația din docstring (bazată pe o inspecție anterioară insuficientă, posibil pe un widget diferit — „Match Momentum", care e într-adevăr un grafic) a fost generalizată greșit la întregul timeline de evenimente, care e text structurat, nu grafic. Corecție de făcut: `normalize_match_events()` ar trebui rescrisă să citească din `.smv__participantRow` (tab Summary), nu din tab-ul Lineups — ar acoperi `event_type IN ('goal','yellow_card','red_card','substitution')` complet (toate 4 din CHECK-ul constrângerii `match_events`, migrația 032), plus `related_player_name` pentru assist la goluri (azi folosit doar pentru schimbări).

---

## 1. Matricea completă

### Tab „Sumar" (summary)

| Câmp Flashscore | Tabelă Supabase | Coloană | Status |
|---|---|---|---|
| Referee | `match_history` | `referee` | ✅ MAPAT |
| Venue | `match_history` | `stadium` | ✅ MAPAT |
| Capacity | `match_history` | `capacity` | ✅ MAPAT |
| Attendance | `match_history` | `attendance` | ✅ MAPAT |
| Nume echipe | `match_history` | `home_team`/`away_team` | ✅ MAPAT |
| Data/ora meciului | `match_history` | `kickoff_date` | ✅ MAPAT |
| Top Stats widget (5 categorii) | — | — | ✅ ACOPERIT — subsumat de tab-ul Statistics (36 categorii, aceleași etichete, sursă preferată) |
| **Scor final** (`.detailScore__wrapper`, ex. „5 - 1") | `match_history` | `actual_home_goals`/`actual_away_goals` | ❌ **NEMAPAT — coloane deja existente (migrația 008), element DOM clar și unic, pur și simplu neinclus în `normalize_match_statistics()`. Nu e lipsă de sursă.** |
| **Scor la pauză** (perechea etichetă/valoare „1st Half"/„2 - 0") | `match_history` | `home_ht_goals`/`away_ht_goals` | ❌ **NEMAPAT — coloane deja existente (migrația 008), pattern etichetă/valoare identic cu Referee/Venue (deja folosit), pur și simplu neinclus.** |
| Scor a doua repriză („2nd Half"/„3 - 1") | — | — | ❌ NEMAPAT — nicio coloană dedicată în schemă pentru „scor doar a doua repriză" (diferit de scorul final) — gol de schemă, nu de extracție; valoare marginală (derivabilă din final − pauză) |
| Breadcrumb țară („Romania") | — | — | ❌ NEMAPAT — nicio coloană dedicată; valoare redundantă cu liga |
| Breadcrumb competiție+rundă („Superliga - Round 2") | `match_history` | `league` (parțial) | ❌ NEMAPAT — `league` EXISTĂ ca și coloană, dar valoarea brută Flashscore („Superliga") necesită reconciliere cu taxonomia canonică de ligi (`mappings.py`, ADR-001, „sursă canonică unică pentru ligi") înainte de scriere — pas de integrare real, neînceput, NU o simplă copiere de text. Numărul de rundă („Round 2") nu are nicio coloană azi — gol de schemă. |
| **Timeline evenimente** (goluri/cartonașe/schimbări/VAR, `.smv__participantRow`) | `match_events` | `minute`, `event_type`, `player_name`, `related_player_name`, `team` | ❌ **NEMAPAT — vezi secțiunea 0. Sursă reală, curată, demonstrată — corectură a unei afirmații anterioare greșite din normalizer.py.** |

### Tab „Statistici" (stats)

| Câmp Flashscore | Tabelă Supabase | Coloană | Status |
|---|---|---|---|
| Expected goals (xG) | `match_history` | `home_xg_actual`/`away_xg_actual` | ✅ MAPAT |
| Ball possession | `match_history` | `home_possession`/`away_possession` | ✅ MAPAT |
| Total shots | `match_history` | `home_shots`/`away_shots` | ✅ MAPAT |
| Shots on target | `match_history` | `home_shots_on_target`/`away_shots_on_target` | ✅ MAPAT |
| Corner kicks | `match_history` | `home_corners`/`away_corners` | ✅ MAPAT |
| Fouls | `match_history` | `home_fouls`/`away_fouls` | ✅ MAPAT |
| Yellow cards (agregat pe meci) | `match_history` | `home_yellow_cards`/`away_yellow_cards` | ✅ MAPAT |
| Red cards (agregat pe meci) | `match_history` | `home_red_cards`/`away_red_cards` | ✅ MAPAT |
| Offsides | `match_history` | `home_offsides`/`away_offsides` | ✅ MAPAT |
| Goalkeeper saves | `match_history` | `home_goalkeeper_saves`/`away_goalkeeper_saves` | ✅ MAPAT |
| Celelalte 26 categorii (xGOT, Big chances, Passes, shots off/inside/outside box, hit woodwork, headed goals, touches in box, accurate through passes, free kicks, long passes, passes in final third, crosses, xA, throw ins, tackles, duels won, clearances, interceptions, errors leading to shot/goal, xGOT faced, goals prevented, goal kicks) | `match_statistics_extended` (EAV) | `stat_key`/`stat_label`/`home_value_raw`/`away_value_raw`/`home_value_numeric`/`away_value_numeric` | ✅ MAPAT (câte un rând per categorie per meci) |

### Tab „Formații" (lineups)

| Câmp Flashscore | Tabelă Supabase | Coloană | Status |
|---|---|---|---|
| Nume jucător | `player_match_stats` | `player_name` | ✅ MAPAT |
| Număr tricou | `player_match_stats` | `shirt_number` | ✅ MAPAT |
| Echipă (home/away) | `player_match_stats` | `team` | ✅ MAPAT |
| Schimbări (din acest tab, `wcl-lineupsParticipantsSubstitution-*`) | `match_events` | `minute`/`player_name`/`related_player_name` | ✅ MAPAT (sursă azi — de înlocuit cu timeline-ul din Summary, mai complet, vezi §0) |
| Marcaje de rol „(G)"/„(C)" (goalkeeper/căpitan) | — | — | ❌ NEMAPAT — niciun câmp `is_captain`/flag dedicat în schemă; poziția „Goalkeeper" e deja acoperită separat prin tab-ul Player Stats (`position`) |

### Tab „Statistici jucători" (player_stats)

| Câmp Flashscore | Tabelă Supabase | Coloană | Status |
|---|---|---|---|
| Rating | `player_match_stats` | `rating` | ✅ MAPAT |
| Poziție | `player_match_stats` | `position` | ✅ MAPAT |
| Total shots | `player_match_stats_extended` (EAV) | `stat_key='total_shots'` | ✅ MAPAT |
| Expected goals (xG) | `player_match_stats_extended` | `stat_key='xg'` | ✅ MAPAT |
| Accurate passes | `player_match_stats_extended` | `stat_key='accurate_passes'` | ✅ MAPAT |
| Touches | `player_match_stats_extended` | `stat_key='touches'` | ✅ MAPAT |
| Touches in opposition box | `player_match_stats_extended` | `stat_key='touches_in_opposition_box'` | ✅ MAPAT |
| Successful dribbles | `player_match_stats_extended` | `stat_key='successful_dribbles'` | ✅ MAPAT |
| Duels | `player_match_stats_extended` | `stat_key='duels'` | ✅ MAPAT |

### Tab „Cote" (odds)

| Câmp Flashscore | Tabelă Supabase | Coloană | Status |
|---|---|---|---|
| Bookmaker + cotă curentă (home/draw/away) | `flashscore_raw_extraction` | `raw_extracted` (jsonb, tab_name='odds') | ⚠️ PARȚIAL — RAW mapat (dovadă păstrată), CANONIC nemapat |
| Bookmaker + cotă curentă → `odds_fallback_flashscore` (ADR-043) | `odds_fallback_flashscore` | `fixture_id`/`bookmaker`/`home`/`draw`/`away` | ❌ **NEMAPAT — NU lipsă de date: tabela cere `fixture_id` IDENTIC cu cel folosit de The Odds API (identitate cross-provider), pe care Flashscore nu-l oferă. Scrierea cu o cheie greșită/inventată ar rupe silențios regula de fallback a Predictorului (ADR-043) — rezoluția identității rămâne task separat, documentat deja de ADR-043 ca „ulterior".** |
| Mișcare cotă (atribut `title`, ex. „2.63 » 2.50" — opening vs curent) | — | — | ❌ NEMAPAT — decizie de SCOP explicită (ADR-043: „cotele Flashscore sunt fallback, nu sursa de CLV/market-drift, nuanța opening/closing nu e critică aici, doar valoarea cea mai recentă contează"), nu gol tehnic — elementul există și e extractibil. |

### Tab „H2H"

| Câmp Flashscore | Tabelă Supabase | Coloană | Status |
|---|---|---|---|
| Categorie (H2H overall / formă recentă acasă / formă recentă oaspete) | `flashscore_match_context` | `category` | ✅ MAPAT |
| Data întâlnirii | `flashscore_match_context` | `meeting_date` | ✅ MAPAT |
| Cod competiție (`.h2h__event`, ex. „SL") | `flashscore_match_context` | `competition_code` | ✅ MAPAT |
| Echipe | `flashscore_match_context` | `home_team`/`away_team` | ✅ MAPAT |
| Scor | `flashscore_match_context` | `home_score`/`away_score` | ✅ MAPAT |
| Ordine cronologică | `flashscore_match_context` | `meeting_order` | ✅ MAPAT |

### Tab „Clasamente" (standings)

| Câmp Flashscore | Tabelă Supabase | Coloană | Status |
|---|---|---|---|
| Rang | `flashscore_standings_snapshot` | `rank` | ✅ MAPAT |
| Echipă | `flashscore_standings_snapshot` | `team` | ✅ MAPAT |
| Jucate/Câștigate/Egal/Pierdute | `flashscore_standings_snapshot` | `played`/`won`/`drawn`/`lost` | ✅ MAPAT |
| Gol marcate/primite/diferență | `flashscore_standings_snapshot` | `goals_for`/`goals_against`/`goal_diff` | ✅ MAPAT |
| Puncte | `flashscore_standings_snapshot` | `points` | ✅ MAPAT |
| **48 insigne de formă recentă** (`.wcl-badgeform_AKaAR` + clasă rezultat `wcl-win_8x-jp`/etc., secvență ordonată per echipă) | — | — | ❌ **NEMAPAT — gol de SCHEMĂ, nu de extracție. Elementul e real, extractibil (clasă CSS determinist per rezultat W/D/L), dar `flashscore_standings_snapshot` nu are nicio coloană pentru el azi (ex. `recent_form JSONB`). Nicio migrare făcută pentru asta încă.** |

---

## 2. Rezumat — câte câmpuri distincte, per status

| Status | Număr | Exemple |
|---|---|---|
| ✅ MAPAT complet | 39 | toate statisticile de bază + extinse, roster, player stats, H2H, standings de bază |
| ❌ NEMAPAT — pur neimplementat, sursă curată confirmată (fix simplu) | 3 | scor final, scor la pauză, timeline evenimente (goluri/cartonașe/schimbări/VAR) |
| ❌ NEMAPAT — gol de SCHEMĂ (coloană lipsă, nu extracție) | 2 | formă recentă standings, scor a doua repriză |
| ❌ NEMAPAT — necesită integrare/reconciliere reală (nu simplă extracție) | 2 | ligă canonică (breadcrumb → `mappings.py`), rundă |
| ❌ NEMAPAT — blocat de rezoluție de identitate cross-provider (nu lipsă de date) | 1 | cotă canonică (`odds_fallback_flashscore`, ADR-043) |
| ❌ NEMAPAT — decizie explicită de scop (ADR-043) | 1 | mișcare cotă (opening vs curent) |
| ❌ NEMAPAT — fără coloană dedicată, valoare marginală | 1 | marcaje rol jucător (G/C) |

**Cel mai important de acționat**: cele 3 din categoria „pur neimplementat, sursă confirmată" — scorul final și scorul la pauză au coloane deja existente și un singur element DOM de citit; timeline-ul de evenimente corectează o afirmație greșită din codul actual și ar completa `match_events` (azi doar substituții) cu goluri/cartonașe reale.
