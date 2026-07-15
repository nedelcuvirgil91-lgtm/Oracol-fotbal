# P3.5 — Faza 3: Migration Plan Final — Consolidarea istoricului de identitate a echipelor

**Status**: Migration Plan — zero cod scris, zero migrare rulată, zero rând din `match_history` atins. Continuă `P3_5_FAZA3_DESIGN_REVIEW_2026-07-15.md` (aprobat). Conține SQL-ul complet (arătat, nerulat), raportul de impact (măsurat direct pe producție, read-only) și planul de rollback. Execuția rămâne condiționată de aprobarea explicită a acestui document.

**Notă de rigoare**: toate cifrele de mai jos sunt măsurate direct prin `SELECT`-uri read-only pe `match_history` (proiectul `Prediction`), nu estimate din CSV. Pe parcursul verificării am prins și corectat o discrepanță reală (19.617 vs. 19.797 la numărul de rânduri de resetat, cauzată de o eroare de transcriere într-o interogare de verificare anterioară) — cifra finală (19.797) e confirmată printr-o a doua interogare, construită independent, verificată byte-cu-byte înainte de rulare. Detaliu în §5.

---

## 1. SQL complet — Pasul A: consolidarea celor 137 de echipe (176 perechi raw→canonical)

Sursă: `docs/03_ENGINE/canonical_team_mapping.csv`, toate rândurile unde `raw_name != canonical_name`. Verificat: 174 din 176 perechi coincid exact cu `mappings.normalize_team_name()` (sursa deja folosită de Faza 1 la scriere) — vezi excepția explicită din §4.

Două `UPDATE`-uri separate (home/away), pattern identic cu backfill-ul `shot_avg_recent` din P7.1 (deja validat operațional în acest proiect):

```sql
-- Pasul A.1 — home_team
UPDATE match_history AS m
SET home_team = v.canonical_name
FROM (VALUES
  ('1. FC Heidenheim 1846', '1. FC Heidenheim'),
  ('1. FC Köln', '1. FC Koln'),
  ('1. FC Union Berlin', 'Union Berlin'),
  ('1. FSV Mainz 05', 'Mainz 05'),
  ('AC Monza', 'Monza'),
  ('ACF Fiorentina', 'Fiorentina'),
  ('AFC Ajax', 'Ajax'),
  ('ANTWERP', 'Royal Antwerp'),
  ('AS Monaco FC', 'Monaco'),
  ('AS Saint-Étienne', 'AS Saint-Etienne'),
  ('Alaves', 'Deportivo Alaves'),
  ('Almeria', 'UD Almeria'),
  ('Angers', 'Angers SCO'),
  ('Antwerp', 'Royal Antwerp'),
  ('Arsenal FC', 'Arsenal'),
  ('Aston Villa FC', 'Aston Villa'),
  ('Atalanta BC', 'Atalanta'),
  ('Ath Bilbao', 'Athletic Club'),
  ('Ath Madrid', 'Atletico Madrid'),
  ('Augsburg', 'FC Augsburg'),
  ('Auxerre', 'AJ Auxerre'),
  ('BENFICA', 'Benfica'),
  ('BESIKTAS', 'Besiktas'),
  ('BRONDBY', 'Brondby'),
  ('BSC YOUNG BOYS', 'Young Boys'),
  ('BSC Young Boys', 'Young Boys'),
  ('Bayer 04 Leverkusen', 'Bayer Leverkusen'),
  ('Bochum', 'VfL Bochum'),
  ('Bologna FC 1909', 'Bologna'),
  ('Borussia Mönchengladbach', 'Borussia Monchengladbach'),
  ('Bournemouth', 'AFC Bournemouth'),
  ('Brentford FC', 'Brentford'),
  ('Brest', 'Stade Brestois'),
  ('Brighton & Hove Albion FC', 'Brighton'),
  ('Burnley FC', 'Burnley'),
  ('CD Leganés', 'CD Leganes'),
  ('CELTIC', 'Celtic'),
  ('CLUB BRUGGE', 'Club Brugge'),
  ('Cadiz', 'Cadiz CF'),
  ('Cagliari Calcio', 'Cagliari'),
  ('Celta', 'Celta Vigo'),
  ('Celtic FC', 'Celtic'),
  ('Chelsea FC', 'Chelsea'),
  ('Clermont', 'Clermont Foot'),
  ('Clermont Foot 63', 'Clermont Foot'),
  ('Club Atlético de Madrid', 'Atletico Madrid'),
  ('Club Brugge KV', 'Club Brugge'),
  ('Colon Santa FE', 'Colon Santa Fe'),
  ('Como 1907', 'Como'),
  ('Crystal Palace FC', 'Crystal Palace'),
  ('Cádiz CF', 'Cadiz CF'),
  ('Darmstadt', 'SV Darmstadt 98'),
  ('Deportivo Alavés', 'Deportivo Alaves'),
  ('Ein Frankfurt', 'Eintracht Frankfurt'),
  ('Elche', 'Elche CF'),
  ('Empoli FC', 'Empoli'),
  ('Espanol', 'Espanyol'),
  ('Everton FC', 'Everton'),
  ('FC Bayern München', 'Bayern Munich'),
  ('FC Internazionale Milano', 'Inter Milan'),
  ('FC Koln', '1. FC Koln'),
  ('FC København', 'FC Copenhagen'),
  ('FC MIDTJYLLAND', 'Midtjylland'),
  ('FC PORTO', 'Porto'),
  ('FC Porto', 'Porto'),
  ('FC St. Pauli 1910', 'FC St. Pauli'),
  ('FENERBAHCE', 'Fenerbahce'),
  ('FK Bodø/Glimt', 'Bodo/Glimt'),
  ('Feyenoord Rotterdam', 'Feyenoord'),
  ('Frosinone Calcio', 'Frosinone'),
  ('Fulham FC', 'Fulham'),
  ('GALATASARAY', 'Galatasaray'),
  ('GENK', 'Genk'),
  ('Galatasaray SK', 'Galatasaray'),
  ('Genoa CFC', 'Genoa'),
  ('Getafe', 'Getafe CF'),
  ('Girona', 'Girona FC'),
  ('Granada', 'Granada CF'),
  ('Hamburg', 'Hamburger SV'),
  ('Heidenheim', '1. FC Heidenheim'),
  ('Hellas Verona FC', 'Hellas Verona'),
  ('Inter', 'Inter Milan'),
  ('Ipswich', 'Ipswich Town'),
  ('Ipswich Town FC', 'Ipswich Town'),
  ('Juventus FC', 'Juventus'),
  ('LOKOMOTIV MOSCOW', 'Lokomotiv Moscow'),
  ('Las Palmas', 'UD Las Palmas'),
  ('Le Havre', 'Le Havre AC'),
  ('Leeds', 'Leeds United'),
  ('Leeds United FC', 'Leeds United'),
  ('Leganes', 'CD Leganes'),
  ('Leicester', 'Leicester City'),
  ('Leicester City FC', 'Leicester City'),
  ('Levante', 'Levante UD'),
  ('Lille OSC', 'Lille'),
  ('Liverpool FC', 'Liverpool'),
  ('Lorient', 'FC Lorient'),
  ('Luton', 'Luton Town'),
  ('Luton Town FC', 'Luton Town'),
  ('M''gladbach', 'Borussia Monchengladbach'),
  ('MALMO FF', 'Malmo FF'),
  ('MGladbach', 'Borussia Monchengladbach'),
  ('Mainz', 'Mainz 05'),
  ('Mallorca', 'RCD Mallorca'),
  ('Manchester City FC', 'Manchester City'),
  ('Manchester United FC', 'Manchester United'),
  ('Metz', 'FC Metz'),
  ('Montpellier', 'Montpellier HSC'),
  ('Nantes', 'FC Nantes'),
  ('Newcastle United FC', 'Newcastle United'),
  ('Nottingham Forest FC', 'Nottingham Forest'),
  ('OGC Nice', 'Nice'),
  ('OLYMPIACOS PIRAEUS', 'Olympiacos'),
  ('Olympiakos', 'Olympiacos'),
  ('Olympique Lyonnais', 'Lyon'),
  ('Olympique de Marseille', 'Marseille'),
  ('Osasuna', 'CA Osasuna'),
  ('Oviedo', 'Real Oviedo'),
  ('PAE Olympiakos SFP', 'Olympiacos'),
  ('Paris Saint-Germain FC', 'Paris Saint-Germain'),
  ('Parma Calcio 1913', 'Parma'),
  ('RANGERS', 'Rangers'),
  ('RC Celta de Vigo', 'Celta Vigo'),
  ('RC Strasbourg Alsace', 'RC Strasbourg'),
  ('RCD Espanyol de Barcelona', 'Espanyol'),
  ('Racing Club de Lens', 'Lens'),
  ('Rayo Vallecano de Madrid', 'Rayo Vallecano'),
  ('Real Betis Balompié', 'Betis'),
  ('Real Madrid CF', 'Real Madrid'),
  ('Real Sociedad de Fútbol', 'Real Sociedad'),
  ('Real Valladolid CF', 'Real Valladolid'),
  ('Reims', 'Stade de Reims'),
  ('Royal Antwerp FC', 'Royal Antwerp'),
  ('SC BRAGA', 'Braga'),
  ('SC Freiburg', 'Freiburg'),
  ('SK Sturm Graz', 'Sturm Graz'),
  ('SPARTAK MOSCOW', 'Spartak Moscow'),
  ('SS Lazio', 'Lazio'),
  ('SSC Napoli', 'Napoli'),
  ('STURM GRAZ', 'Sturm Graz'),
  ('Sevilla FC', 'Sevilla'),
  ('Sheffield United FC', 'Sheffield United'),
  ('Sociedad', 'Real Sociedad'),
  ('Southampton FC', 'Southampton'),
  ('Sport Lisboa e Benfica', 'Benfica'),
  ('Sporting Clube de Braga', 'Braga'),
  ('St Etienne', 'AS Saint-Etienne'),
  ('St Pauli', 'FC St. Pauli'),
  ('Stade Brestois 29', 'Stade Brestois'),
  ('Stade Rennais FC 1901', 'Rennes'),
  ('Strasbourg', 'RC Strasbourg'),
  ('Stuttgart', 'VfB Stuttgart'),
  ('Sunderland AFC', 'Sunderland'),
  ('TSG 1899 Hoffenheim', 'Hoffenheim'),
  ('Torino FC', 'Torino'),
  ('Tottenham Hotspur FC', 'Tottenham Hotspur'),
  ('Toulouse', 'Toulouse FC'),
  ('UD Almería', 'UD Almeria'),
  ('US Cremonese', 'Cremonese'),
  ('US Lecce', 'Lecce'),
  ('US Salernitana 1919', 'Salernitana'),
  ('US Sassuolo Calcio', 'Sassuolo'),
  ('Udinese Calcio', 'Udinese'),
  ('Univ. Craiova', 'Universitatea Craiova'),
  ('Valencia CF', 'Valencia'),
  ('Valladolid', 'Real Valladolid'),
  ('Vallecano', 'Rayo Vallecano'),
  ('Venezia FC', 'Venezia'),
  ('Verona', 'Hellas Verona'),
  ('VfL Bochum 1848', 'VfL Bochum'),
  ('VfL Wolfsburg', 'Wolfsburg'),
  ('Villarreal CF', 'Villarreal'),
  ('Werder Bremen', 'SV Werder Bremen'),
  ('West Ham United FC', 'West Ham United'),
  ('Wimbledon', 'AFC Wimbledon'),
  ('Wolverhampton Wanderers FC', 'Wolverhampton Wanderers')
) AS v(raw_name, canonical_name)
WHERE m.home_team = v.raw_name;

-- Pasul A.2 — away_team (aceeași listă de perechi)
UPDATE match_history AS m
SET away_team = v.canonical_name
FROM (VALUES
  /* ... identic cu lista de mai sus (176 perechi) ... */
) AS v(raw_name, canonical_name)
WHERE m.away_team = v.raw_name;
```

*(Lista completă a celor 176 de perechi e identică în ambele UPDATE-uri — omisă a doua oară aici pentru lizibilitate; fișierul de execuție va conține ambele liste complete, verificate byte-cu-byte înainte de rulare, exact disciplina din §5.)*

---

## 2. SQL complet — Pasul B: reset controlat (18 coloane, DUPĂ Pasul A)

```sql
WITH echipe_afectate(nume) AS (
  VALUES
  ('1. FC Heidenheim'), ('1. FC Heidenheim 1846'), ('1. FC Koln'), ('1. FC Köln'),
  ('1. FC Union Berlin'), ('1. FSV Mainz 05'), ('AC Monza'), ('ACF Fiorentina'),
  ('AFC Ajax'), ('AFC Bournemouth'), ('AFC Wimbledon'), ('AJ Auxerre'), ('ANTWERP'),
  ('AS Monaco FC'), ('AS Saint-Etienne'), ('AS Saint-Étienne'), ('Ajax'), ('Alaves'),
  ('Almeria'), ('Angers'), ('Angers SCO'), ('Antwerp'), ('Arsenal'), ('Arsenal FC'),
  ('Aston Villa'), ('Aston Villa FC'), ('Atalanta'), ('Atalanta BC'), ('Ath Bilbao'),
  ('Ath Madrid'), ('Athletic Club'), ('Atletico Madrid'), ('Augsburg'), ('Auxerre'),
  ('BENFICA'), ('BESIKTAS'), ('BRONDBY'), ('BSC YOUNG BOYS'), ('BSC Young Boys'),
  ('Bayer 04 Leverkusen'), ('Bayer Leverkusen'), ('Bayern Munich'), ('Benfica'),
  ('Besiktas'), ('Betis'), ('Bochum'), ('Bodo/Glimt'), ('Bologna'), ('Bologna FC 1909'),
  ('Borussia Monchengladbach'), ('Borussia Mönchengladbach'), ('Bournemouth'), ('Braga'),
  ('Brentford'), ('Brentford FC'), ('Brest'), ('Brighton'), ('Brighton & Hove Albion FC'),
  ('Brondby'), ('Burnley'), ('Burnley FC'), ('CA Osasuna'), ('CD Leganes'),
  ('CD Leganés'), ('CELTIC'), ('CLUB BRUGGE'), ('Cadiz'), ('Cadiz CF'), ('Cagliari'),
  ('Cagliari Calcio'), ('Celta'), ('Celta Vigo'), ('Celtic'), ('Celtic FC'), ('Chelsea'),
  ('Chelsea FC'), ('Clermont'), ('Clermont Foot'), ('Clermont Foot 63'),
  ('Club Atlético de Madrid'), ('Club Brugge'), ('Club Brugge KV'), ('Colon Santa FE'),
  ('Colon Santa Fe'), ('Como'), ('Como 1907'), ('Cremonese'), ('Crystal Palace'),
  ('Crystal Palace FC'), ('Cádiz CF'), ('Darmstadt'), ('Deportivo Alaves'),
  ('Deportivo Alavés'), ('Ein Frankfurt'), ('Eintracht Frankfurt'), ('Elche'),
  ('Elche CF'), ('Empoli'), ('Empoli FC'), ('Espanol'), ('Espanyol'), ('Everton'),
  ('Everton FC'), ('FC Augsburg'), ('FC Bayern München'), ('FC Copenhagen'),
  ('FC Internazionale Milano'), ('FC Koln'), ('FC København'), ('FC Lorient'),
  ('FC MIDTJYLLAND'), ('FC Metz'), ('FC Nantes'), ('FC PORTO'), ('FC Porto'),
  ('FC St. Pauli'), ('FC St. Pauli 1910'), ('FENERBAHCE'), ('FK Bodø/Glimt'),
  ('Fenerbahce'), ('Feyenoord'), ('Feyenoord Rotterdam'), ('Fiorentina'), ('Freiburg'),
  ('Frosinone'), ('Frosinone Calcio'), ('Fulham'), ('Fulham FC'), ('GALATASARAY'),
  ('GENK'), ('Galatasaray'), ('Galatasaray SK'), ('Genk'), ('Genoa'), ('Genoa CFC'),
  ('Getafe'), ('Getafe CF'), ('Girona'), ('Girona FC'), ('Granada'), ('Granada CF'),
  ('Hamburg'), ('Hamburger SV'), ('Heidenheim'), ('Hellas Verona'), ('Hellas Verona FC'),
  ('Hoffenheim'), ('Inter'), ('Inter Milan'), ('Ipswich'), ('Ipswich Town'),
  ('Ipswich Town FC'), ('Juventus'), ('Juventus FC'), ('LOKOMOTIV MOSCOW'),
  ('Las Palmas'), ('Lazio'), ('Le Havre'), ('Le Havre AC'), ('Lecce'), ('Leeds'),
  ('Leeds United'), ('Leeds United FC'), ('Leganes'), ('Leicester'), ('Leicester City'),
  ('Leicester City FC'), ('Lens'), ('Levante'), ('Levante UD'), ('Lille'), ('Lille OSC'),
  ('Liverpool'), ('Liverpool FC'), ('Lokomotiv Moscow'), ('Lorient'), ('Luton'),
  ('Luton Town'), ('Luton Town FC'), ('Lyon'), ('M''gladbach'), ('MALMO FF'),
  ('MGladbach'), ('Mainz'), ('Mainz 05'), ('Mallorca'), ('Malmo FF'),
  ('Manchester City'), ('Manchester City FC'), ('Manchester United'),
  ('Manchester United FC'), ('Marseille'), ('Metz'), ('Midtjylland'), ('Monaco'),
  ('Montpellier'), ('Montpellier HSC'), ('Monza'), ('Nantes'), ('Napoli'),
  ('Newcastle United'), ('Newcastle United FC'), ('Nice'), ('Nottingham Forest'),
  ('Nottingham Forest FC'), ('OGC Nice'), ('OLYMPIACOS PIRAEUS'), ('Olympiacos'),
  ('Olympiakos'), ('Olympique Lyonnais'), ('Olympique de Marseille'), ('Osasuna'),
  ('Oviedo'), ('PAE Olympiakos SFP'), ('Paris Saint-Germain'), ('Paris Saint-Germain FC'),
  ('Parma'), ('Parma Calcio 1913'), ('Porto'), ('RANGERS'), ('RC Celta de Vigo'),
  ('RC Strasbourg'), ('RC Strasbourg Alsace'), ('RCD Espanyol de Barcelona'),
  ('RCD Mallorca'), ('Racing Club de Lens'), ('Rangers'), ('Rayo Vallecano'),
  ('Rayo Vallecano de Madrid'), ('Real Betis Balompié'), ('Real Madrid'),
  ('Real Madrid CF'), ('Real Oviedo'), ('Real Sociedad'), ('Real Sociedad de Fútbol'),
  ('Real Valladolid'), ('Real Valladolid CF'), ('Reims'), ('Rennes'), ('Royal Antwerp'),
  ('Royal Antwerp FC'), ('SC BRAGA'), ('SC Freiburg'), ('SK Sturm Graz'),
  ('SPARTAK MOSCOW'), ('SS Lazio'), ('SSC Napoli'), ('STURM GRAZ'), ('SV Darmstadt 98'),
  ('SV Werder Bremen'), ('Salernitana'), ('Sassuolo'), ('Sevilla'), ('Sevilla FC'),
  ('Sheffield United'), ('Sheffield United FC'), ('Sociedad'), ('Southampton'),
  ('Southampton FC'), ('Spartak Moscow'), ('Sport Lisboa e Benfica'),
  ('Sporting Clube de Braga'), ('St Etienne'), ('St Pauli'), ('Stade Brestois'),
  ('Stade Brestois 29'), ('Stade Rennais FC 1901'), ('Stade de Reims'), ('Strasbourg'),
  ('Sturm Graz'), ('Stuttgart'), ('Sunderland'), ('Sunderland AFC'),
  ('TSG 1899 Hoffenheim'), ('Torino'), ('Torino FC'), ('Tottenham Hotspur'),
  ('Tottenham Hotspur FC'), ('Toulouse'), ('Toulouse FC'), ('UD Almeria'),
  ('UD Almería'), ('UD Las Palmas'), ('US Cremonese'), ('US Lecce'),
  ('US Salernitana 1919'), ('US Sassuolo Calcio'), ('Udinese'), ('Udinese Calcio'),
  ('Union Berlin'), ('Univ. Craiova'), ('Universitatea Craiova'), ('Valencia'),
  ('Valencia CF'), ('Valladolid'), ('Vallecano'), ('Venezia'), ('Venezia FC'),
  ('Verona'), ('VfB Stuttgart'), ('VfL Bochum'), ('VfL Bochum 1848'), ('VfL Wolfsburg'),
  ('Villarreal'), ('Villarreal CF'), ('Werder Bremen'), ('West Ham United'),
  ('West Ham United FC'), ('Wimbledon'), ('Wolfsburg'), ('Wolverhampton Wanderers'),
  ('Wolverhampton Wanderers FC'), ('Young Boys')
)
UPDATE match_history
SET home_elo = NULL, away_elo = NULL,
    home_form_score = NULL, away_form_score = NULL,
    home_offensive_rating = NULL, home_defensive_rating = NULL,
    away_offensive_rating = NULL, away_defensive_rating = NULL,
    h2h_modifier = NULL, h2h_meetings = NULL,
    home_corner_avg_recent = NULL, away_corner_avg_recent = NULL,
    home_card_avg_recent = NULL, away_card_avg_recent = NULL,
    home_foul_avg_recent = NULL, away_foul_avg_recent = NULL,
    home_shot_avg_recent = NULL, away_shot_avg_recent = NULL
WHERE home_team IN (SELECT nume FROM echipe_afectate)
   OR away_team IN (SELECT nume FROM echipe_afectate);
```

Cele 313 nume = uniunea `raw_name` ∪ `canonical_name` din `canonical_team_mapping.csv`, pentru cele 137 de echipe cu consolidare reală — motivul includerii formei canonice (nu doar variantele brute) e demonstrat în design review (§3.2 din `P3_5_FAZA3_DESIGN_REVIEW_2026-07-15.md`, cazul Arsenal-Manchester United).

---

## 3. Raport de impact (măsurat pe producție, read-only, 2026-07-15)

| Metrică | Valoare |
|---|---:|
| Total rânduri `match_history` | **53.430** |
| Rânduri cu string rescris literal (Pasul A) | **12.247** (22,9%) |
| Rânduri de resetat (Pasul B, scop complet) | **19.797** (37,1%) |
| Echipe canonice implicate | **137** |
| Perechi raw→canonical de rescris | **176** |

### Lista echipelor implicate — top 20 după impact, restul în `canonical_team_mapping.csv`

| Echipă canonică | Meciuri totale | Meciuri „orfane" (impact) |
|---|---:|---:|
| Atletico Madrid | 313 | 160 |
| Inter Milan | 307 | 155 |
| Real Madrid | 320 | 155 |
| Arsenal | 309 | 153 |
| Paris Saint-Germain | 306 | 148 |
| Manchester City | 312 | 144 |
| Bayern Munich | 291 | 142 |
| Atalanta | 300 | 136 |
| Liverpool | 305 | 136 |
| Juventus | 294 | 134 |
| Newcastle United | 288 | 132 |
| Napoli | 290 | 130 |
| Real Sociedad | 282 | 130 |
| Aston Villa | 281 | 126 |
| Bayer Leverkusen | 271 | 124 |
| Chelsea | 290 | 124 |
| Tottenham Hotspur | 280 | 124 |
| Eintracht Frankfurt | 262 | 123 |
| Athletic Club | 274 | 122 |
| Bologna | 274 | 122 |
| **Total (toate cele 137)** | **31.299** | **10.835** |

Lista completă (toate cele 137, cu toate variantele brute): `docs/03_ENGINE/canonical_team_mapping.csv` — sursă unică de adevăr, nu duplicată aici.

### Estimare timp pentru re-backfill (Pasul C)

Bazată pe **log-uri reale** de rulare `run_backfill()` pe producție (2026-07-13, păstrate din sesiunea de backfill inițial ADR-011/ADR-012):

- Dry-run pe tot `match_history` (53.409 rânduri la momentul respectiv, 10 coloane): **24,2 secunde** total (citire + calcul, zero scriere).
- Rulare reală, rată observată la scriere: ~50 rânduri / 8-12 secunde (batch_size implicit 50) ≈ **4,2-6,25 rânduri/secundă**.

Pentru Faza 3 (19.797 rânduri de scris, 18 coloane — mai multe decât cele 10 din log-ul de referință, dar costul per-rând e dominat de round-trip-ul de rețea per batch, nu de numărul de coloane calculate):

```
19.797 rânduri / ~5 rânduri/secundă ≈ 3.960 secunde ≈ 66 minute (scriere)
+ ~30-60 secunde (citire completă + calcul tracker pentru toate cele 53.430 rânduri)
──────────────────────────────────────────────────────────────
Estimare totală: ~45-70 minute pentru run_backfill() complet (dry-run + real)
```

Notă onestă: estimarea e extrapolată din log-uri reale, nu teoretică — dar condițiile de rețea/încărcare pot varia. Recomand rulare cu monitorizare activă (log progres la fiecare 50 rânduri, deja implementat), nu „fire and forget".

---

## 4. Decizie REZOLVATĂ — 2 excepții față de `mappings.normalize_team_name()`

**Status: rezolvat.** Utilizatorul a ales varianta (a) din decizia de mai jos. `Colon Santa Fe` și `Fenerbahce` au fost adăugate în `mappings.TEAM_ALIASES` (`mappings.py`, secțiunea „Champions League / Europa League"), cu aliasurile `Colon Santa FE`/`FENERBAHCE`. Verificat direct:

```
normalize_team_name('Colon Santa FE') -> 'Colon Santa Fe'
normalize_team_name('FENERBAHCE')     -> 'Fenerbahce'
```

`pytest tests/` — 387 teste, toate verzi după modificare (niciun test existent nu depindea de comportamentul vechi, neschimbat, al acestor 2 nume). Modificarea e pur aditivă în `TEAM_ALIASES` — nu atinge nicio altă intrare. Cu acest fix, Pasul A din §1 și `normalize_team_name()` sunt acum aliniate 100% pentru toate cele 176 de perechi — nu mai există risc de reintroducere a fragmentării pe aceste 2 nume la sincronizări viitoare.

Argumentarea originală a deciziei (păstrată pentru trasabilitate):

Verificare încrucișată a celor 176 perechi din Pasul A față de `mappings.normalize_team_name()` (sursa deja folosită de Faza 1 la scriere) a găsit **2 nepotriviri**:

| raw_name | canonical_name (propus, CSV) | `normalize_team_name()` returnează azi |
|---|---|---|
| `Colon Santa FE` | `Colon Santa Fe` | `Colon Santa FE` (neschimbat) |
| `FENERBAHCE` | `Fenerbahce` | `FENERBAHCE` (neschimbat) |

Ambele corespund exact rândurilor marcate `in_team_aliases_py=no_add_to_team_aliases` în `canonical_team_mapping.csv` (audit-ul original P3.5 le-a identificat, dar a decis explicit să nu le adauge în `mappings.TEAM_ALIASES`). Confirmat: niciuna nu apare azi în `mappings.py`.

**Consecință dacă rulăm Pasul A ca atare, fără completare**: cele 2 nume s-ar rescrie o singură dată (istoric), dar `normalize_team_name()` tot nu le-ar recunoaște pentru scrieri VIITOARE — orice sursă nouă care produce din nou `"Colon Santa FE"`/`"FENERBAHCE"` ar reintroduce fragmentarea, chiar și cu Faza 1 activă.

**Decizie necesară**: (a) adăugăm cele 2 perechi în `mappings.TEAM_ALIASES` ca parte din scopul Faza 3 (mic, justificat de aceeași dovadă de audit), sau (b) le excludem explicit din Pasul A, rămân „cunoscute, neconsolidate" — impact minor (40+6=46 apariții din 10.835 total, 0,4%). Recomand (a), dar rămâne decizia ta explicită, nu presupunere.

---

## 5. Notă de metodologie — discrepanța prinsă și corectată

La construirea acestui plan, o primă interogare de verificare (construită prin transcriere manuală a array-ului SQL) a raportat 19.617 rânduri de resetat. O a doua interogare, construită independent (stil CTE, verificată byte-cu-byte prin `Read` înainte de trimitere) a raportat 19.797. Diferența (180 rânduri) a fost investigată: sursa Python care generează ambele liste produce EXACT aceleași 313 nume (verificat prin diff programatic, zero diferență) — deci discrepanța nu era în date, ci într-o eroare de transcriere a primei interogări, corectată. **19.797 e cifra finală, confirmată.** Consemnat aici explicit — exact disciplina „verificat, nu presupus" a proiectului, aplicată și propriei mele lucrări.

---

## 6. Plan de rollback complet

1. **Raport „înainte"** (obligatoriu, înainte de orice scriere): `SELECT` complet al celor 19.797 rânduri afectate — `fixture_id`, `home_team`, `away_team`, toate cele 18 coloane derivate — salvat ca artefact (fișier/tabel temporar), nu doar afișat. Reprezintă starea de restaurat.
2. **Migrare aditivă-reversibilă**: Pasul A (rescriere nume) și Pasul B (reset la NULL) sunt ambele `UPDATE`-uri simple, fără `DELETE`/`INSERT` — numărul total de rânduri din `match_history` rămâne 53.430 pe tot parcursul, verificabil oricând.
3. **Restaurare, dacă e necesară**: din raportul „înainte" (pasul 1), un `UPDATE` invers (aceeași tehnică VALUES-join) poate restaura exact `home_team`/`away_team` și toate cele 18 coloane la starea pre-Faza-3, rând cu rând.
4. **Reluare sigură după eșec parțial**: `normalize_team_name()`/mapping-ul e determinist — o reluare completă a Pasului A e idempotentă (rescrierea unui rând deja canonic e un no-op, `WHERE m.home_team = v.raw_name` nu mai găsește nimic de schimbat). Pasul B (reset) e de asemenea idempotent (a seta NULL peste NULL e no-op). Pasul C (`run_backfill()`) e non-destructiv prin design (Regula #13) — o reluare după întrerupere continuă corect, fără duplicare.
5. **Nicio scriere nu atinge** `actual_result`/`actual_home_goals`/`actual_away_goals` pe tot parcursul (Pașii A, B, C) — rezultatele rămân sursa de adevăr neatinsă.
6. **Criteriu de „stop" în timpul execuției**: dacă verificarea de consistență post-Pas-C (extensia sanity check-ului P7.1: zero valori negative/NaN/infinite, eșantion înainte/după pentru echipe afectate vs. neafectate) eșuează, execuția se oprește înainte de a considera Faza 3 „finalizată" — raportul „înainte" rămâne disponibil pentru restaurare completă.

---

## 7. Impact Matrix — cele 18 coloane din `FEATURE_COLUMNS`

Clarificarea cerută înainte de execuție. Fiecare rând e verificat direct pe codul din `sync/backfill_features.py` (nu pe presupunere) — citate exacte de linie. Concluzie generală, verificată prin grep încrucișat în `oracle_engine.py`: **niciuna din cele 18 coloane nu e citită de fluxul de servire live** (`_build_profile`/`_build_ml_features` din `oracle_engine.py` își calculează propriile ELO/formă/H2H/statistici din `oracle_api` live + stare internă proprie, independent de `match_history`). Cele 18 coloane sunt consumate EXCLUSIV de `ml_predictor._fetch_training_dataframe()` (antrenare) — deci fereastra de ~45-70 min în care aceste coloane sunt `NULL` în timpul re-backfill-ului **nu afectează predicțiile live în niciun fel** (Regula North Star #10 — servirea live nu depinde de infrastructura de învățare — confirmată intactă de acest audit, nu doar presupusă).

### A. Obligatoriu reset — output direct al unui tracker cheiat pe string de echipă (12 coloane)

Fiecare din aceste 12 coloane e citită dintr-un `dict[str, ...]` al cărui cheie e literal `match.get("home_team")`/`match.get("away_team")` (linia 858-859) — o singură echipă fragmentată în 2 string-uri produce 2 intrări separate în dict, cu istorie disjunctă.

| Coloană | Tracker + linie | Justificare |
|---|---|---|
| `home_elo`, `away_elo` | `ELOTracker.ratings: dict[str, float]` (:225), `get_elo()` (:228-229) | Rating stocat direct pe string-ul echipei; `"Man Utd"` și `"Manchester United"` acumulează 2 istorii ELO complet separate. |
| `home_form_score`, `away_form_score` | `FormTracker.history: dict[str, list]` (:277), `calculate_form_score()` (:282-292) | Fereastră glisantă de 10 meciuri, cheiată identic pe string brut. |
| `home_corner_avg_recent`, `away_corner_avg_recent` | `CornerCardTracker.corners: dict[str, list]` (:438, :441-443) | Medie glisantă, cheiată pe echipă. |
| `home_card_avg_recent`, `away_card_avg_recent` | `CornerCardTracker.cards: dict[str, list]` (:439, :445-447) | Idem, dict separat în aceeași clasă. |
| `home_foul_avg_recent`, `away_foul_avg_recent` | `FoulsTracker.history: dict[str, list]` (:374, :376-380) | Medie glisantă, cheiată pe echipă. |
| `home_shot_avg_recent`, `away_shot_avg_recent` | `ShotCountTracker.history: dict[str, list]` (:409, :411-415) | Cea mai recentă pereche (ADR-021, P7.1, aceeași zi) — dar mecanismul e identic: dict cheiat pe string brut. |

**Verdict: toate 12 trebuie resetate. Fără excepție — nu există variantă în care un string fragmentat NU corupe cheia dict-ului.**

### B. Derivate automat — compunere din starea categoriei A, fără tracker propriu (4 coloane)

| Coloană | Mecanism | Justificare |
|---|---|---|
| `home_offensive_rating`, `home_defensive_rating`, `away_offensive_rating`, `away_defensive_rating` | `team_pre_match_rating()` (:695-762), apelată per meci (:870-875) | Nu au propriul dict persistent — se recalculează la fiecare apel din `elo_tracker.get_elo(team)` (:726), `form_tracker.get_form(team)` (:734) și `shots_tracker.get_avg_shots_on_target(team)` (:742) — toate 3 cheiate pe echipă (categoria A). Mecanismul de calcul „se auto-corectează" automat ODATĂ ce Pasul A rescrie numele — dar **valoarea deja STOCATĂ** în `match_history` a fost calculată în trecut cu ELO/formă/SOT fragmentate și rămâne stale. Writer Protection (Regula #13) tot o protejează de suprascriere dacă nu e explicit `NULL` — deci reset SQL obligatoriu, chiar dacă „vinovăția" e moștenită, nu primară. |

**Verdict: toate 4 trebuie resetate — derivarea automată explică DE CE vor fi corecte după re-backfill, nu scutește de reset explicit.**

### C. Verificare specială — structură diferită de cheie, risc suplimentar de verificat (2 coloane)

| Coloană | Mecanism | Risc specific |
|---|---|---|
| `h2h_modifier`, `h2h_meetings` | `H2HTracker.history: dict[tuple, list]`, cheie **PERECHE** `(min(home,away), max(home,away))` (:480-482, :508) | Singura coloană cheiată pe 2 string-uri simultan, nu pe unul. Consecințe verificate în cod: (1) `get_h2h_before()` (:496-497) compară `h == home`/`h == away` cu numele CURENTE la apel, nu cu ordinea din cheie — orientarea (avantaj home/away) NU se corupe la un swap al ordinii alfabetice după canonicalizare, verificat direct în cod, nu presupus; (2) corectitudinea completă depinde STRICT ca Pasul A să se fi terminat 100% înainte de re-backfill — dacă o singură parte a unei perechi rămâne nerescrisă la momentul re-backfill-ului, cheia pereche nu găsește istoricul deja consolidat al celeilalte părți, iar cele 2 seturi de istoric rămân separate SILENȚIOS (fără eroare, fără log) — deci ordinea strictă A → reset → C nu e opțională aici, cum e (parțial) tolerantă la celelalte 16 coloane. |

**Verdict: trebuie resetate, plus o verificare suplimentară post-execuție** — spot-check pe `h2h_meetings` pentru o pereche cunoscută cu istoric fragmentat (ex. un meci Porto vs. o echipă din lista de 176) pentru a confirma empiric, nu doar teoretic, că numărul de întâlniri crește după consolidare față de valoarea pre-Faza-3.

### Concluzia Impact Matrix

**Toate cele 18 coloane trebuie invalidate. Nu există nicio coloană din `FEATURE_COLUMNS` care poate fi exclusă din Pasul B fără a lăsa o stare stale, silențioasă, needetectabilă prin niciun mecanism existent (Writer Protection nu detectează valori „greșite dar nu NULL" — le protejează neschimbate).** Scope-ul de 313 nume / 19.797 rânduri din §2-3 rămâne corect și complet — confirmat, nu doar reafirmat.

---

## 8. Ce NU decide acest document

- Execuția propriu-zisă — acest document arată SQL-ul exact, nu îl rulează.
- Reevaluarea P3 (MOV) — condiționată de rezultatul Faza 3, pas separat, ulterior, cu metodologia deja stabilită.
