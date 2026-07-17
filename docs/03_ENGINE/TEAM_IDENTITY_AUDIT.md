# TEAM_IDENTITY_AUDIT.md — Football Oracle

**Status**: Audit de date — zero scriere în Supabase, zero modificare de cod de producție. P3.5 din `ML_EVOLUTION_ROADMAP.md`, deschis direct de descoperirea din P3.1 (discrepanțe uriașe per-echipă în comparația de fidelitate ELO, până la 241 de puncte pentru echipe de top).
**Scop, strict delimitat** (cerință explicită Chief Architect): 4 faze — inventariere, clasificare, măsurarea impactului, livrabil. Fără reparare acum. Criteriul de succes: răspuns clar la 3 întrebări — câte identități duplicate există, cât de mult afectează istoricul/ELO, există o mapare canonică suficient de sigură pentru a rerula P3.

---

## Rezumat — descoperirea centrală

**`TEAM_ALIASES` (`mappings.py`, 272 intrări canonice, `normalize_team_name()`) există deja și acoperă corect majoritatea covârșitoare a cazurilor găsite.** Nu a fost nevoie să se construiască o mapare de la zero — problema nu e lipsa unei surse de adevăr, e că **acea sursă de adevăr nu e aplicată consecvent la scriere**.

Verificat direct, nu presupus: `sync/import_historical.py` (importul istoric bulk, Kaggle/football-data.co.uk) apelează `normalize_team_name()` la fiecare rând scris. **Niciunul dintre writer-ii sincronizării zilnice curente nu o apelează**: `sync/sources/football_data.py`, `sync/sources/football_data_co_uk.py`, `sync/sources/kaggle.py`, `sync/sources/openfootball.py`, `sync/sync_results.py` — toate scriu `home_team`/`away_team` direct din răspunsul API-ului sursă, brut. `database/queries.py` (`upsert_matches_bulk`) e un upsert generic, fără nicio normalizare internă — presupune că apelantul a normalizat deja.

**Consecință directă pentru `ELOTracker`** (`sync/backfill_features.py`): tratează fiecare string literal ca o echipă distinctă (dict keyed pe `home`/`away` brut, fără nicio normalizare la citire). O echipă cu istoric scris parțial de importul istoric (normalizat) și parțial de sincronizarea zilnică (brut) apare ca **două sau mai multe echipe separate**, fiecare pornind propriul rating de la 1.500, împărțind între ele meciurile care ar trebui să contribuie la un singur istoric continuu.

---

## Faza 1 — Inventarierea identităților

Surse interogate direct (Supabase, `Prediction`, read-only):

| Sursă | Nume unice distincte | Observație |
|---|---:|---|
| `match_history` (home_team + away_team) | 1.111 | 106.860 apariții totale |
| `elo_history` | 667 | sursă unică (`kaggle`), mult mai puțin fragmentată — vezi §5 |
| `mappings.TEAM_ALIASES` | 272 intrări canonice | sursa #1, cea mai de încredere (deja existentă) |

Sursele externe #2-#5 din ordinea ta de încredere (Kaggle, API-Football, football-data.co.uk, Sofascore/FotMob) **nu au fost interogate direct ca surse separate** — informația lor relevantă e deja materializată în `match_history` (rândurile scrise de fiecare provider) și în `TEAM_ALIASES` (construit istoric din exact aceste surse, conform comentariilor din `mappings.py`). Re-interogarea lor separată n-ar fi adăugat informație nouă pentru acest audit — decizie de scop, nu omisiune.

---

## Faza 2 — Clasificarea diferențelor

**146 cazuri confirmate, toate categoria „Alias" (aceeași echipă, nume diferit)** — două subseturi, ambele cu dovadă directă:

1. **129 cazuri**: canonicul din `TEAM_ALIASES` ȘI cel puțin un alias listat apar amândoi, literal, ca stringuri distincte în `match_history` — dovadă directă că maparea există, dar nu a fost aplicată la scriere pentru acele rânduri.
2. **17 cazuri noi**, negăsite în `TEAM_ALIASES`: duplicate case-insensitive (`RANGERS`/`Rangers`, `GALATASARAY`/`Galatasaray`, `BENFICA`/`Benfica`, `CELTIC`/`Celtic` etc.) — tipar consistent cu comentariul deja existent în `mappings.py` linia 285 („Champions League / Europa League — forme multiple confirmate direct în match_history, provideri diferiți") — un al treilea provider (probabil de date de cupe europene) scrie nume ALL-CAPS, nedetectat până acum de `TEAM_ALIASES`.

**Verificare exhaustivă a restului**: după eliminarea celor 146 cazuri confirmate, au rămas 729 de nume neexplicate. Rulate prin `normalize_team_name()` (funcția deja existentă — unicode-fold + strip prefix/sufix `FC`/`CF`/`AC` etc.) pentru clustering automat: **zero clustere noi găsite** — nicio pereche suplimentară de nume care s-ar normaliza la aceeași valoare. Cele 729 sunt, cu încredere rezonabilă (nu verificare manuală individuală, în afara scopului stabilit), echipe genuin distincte.

**Categoriile „Redenumire oficială", „Diacritice/punctuație pure" (ca ambiguitate separată de alias), „Echipe diferite (nu se unesc)" și „Caz incert"**: **nicio instanță găsită prin verificarea automată** din acest audit. Asta nu e o garanție absolută (redenumirile reale — ex. un club retrogradat și rebrand-uit — n-ar produce neapărat un tipar de string detectabil automat), dar cele 146 cazuri găsite acoperă exhaustiv tot ce e detectabil mecanic din datele disponibile azi. Verificare manuală suplimentară, caz-cu-caz, rămâne posibilă dar explicit în afara scopului acestei runde (risc exact pe care l-ai semnalat — „proiect fără sfârșit de curățare de date").

**Promovări/retrogradări**: aplicat exact principiul tău — nu tratate ca schimbare de identitate. Nu a fost nevoie de nicio decizie specială aici; `TEAM_ALIASES` deja nu leagă identitatea de ligă (o echipă își păstrează numele canonic indiferent de competiție), iar cele 146 cazuri găsite sunt toate variante de NUME, nu confuzii între echipe diferite din ligi diferite.

---

## Faza 3 — Măsurarea impactului

**Metrică**: pentru fiecare echipă cu ≥2 variante confirmate, „impact" = total meciuri − meciurile variantei dominante (adică meciurile „rătăcite" într-o variantă minoritară, care ar fi trebuit să contribuie la istoricul principal).

```
137 echipe canonice afectate
288 rânduri variantă-echipă (multe echipe au 2-3 variante)
10.835 apariții meci „ratacite" in variante minoritare
= 10,1% din toate cele 106.860 aparitii home/away din match_history
```

**Distribuția impactului NU e concentrată — descoperire importantă, contrazice ipoteza „primele 20 rezolvă 95%"**: top 20 cazuri acoperă doar **25,1%** din impactul total; top 30 doar **36,1%**. Motivul: aproape toate echipele mari afectate au un impact similar ca magnitudine (120-160 meciuri „rătăcite" fiecare — Atletico Madrid 160, Real Madrid 155, Inter Milan 155, Arsenal 153, PSG 148, Manchester City 144, Bayern Munich 142...). Nu există un „vârf" dominant de câteva alias-uri responsabile de majoritatea problemei — problema e lată, nu ascuțită.

**Top 15, pentru context** (lista completă, toate cele 137 echipe, e în `canonical_team_mapping.csv`):

| # | Echipă | Impact (meciuri) | Variante |
|---|---|---:|---|
| 1 | Atletico Madrid | 160 | "Atletico Madrid"=10, "Ath Madrid"=153, "Club Atlético de Madrid"=150 |
| 2 | Real Madrid | 155 | "Real Madrid"=165, "Real Madrid CF"=155 |
| 3 | Inter Milan | 155 | "Inter"=152, "Inter Milan"=8, "FC Internazionale Milano"=147 |
| 4 | Arsenal | 153 | "Arsenal"=156, "Arsenal FC"=153 |
| 5 | Paris Saint-Germain | 148 | "Paris Saint-Germain"=158, "Paris Saint-Germain FC"=148 |
| 6 | Manchester City | 144 | "Manchester City"=168, "Manchester City FC"=144 |
| 7 | Bayern Munich | 142 | "Bayern Munich"=149, "FC Bayern München"=142 |
| 8 | Liverpool | 136 | "Liverpool"=169, "Liverpool FC"=136 |
| 9 | Atalanta | 136 | "Atalanta"=164, "Atalanta BC"=136 |
| 10 | Juventus | 134 | "Juventus"=160, "Juventus FC"=134 |
| 11 | Newcastle United | 132 | "Newcastle United"=156, "Newcastle United FC"=132 |
| 12 | Real Sociedad | 130 | "Sociedad"=152, "Real Sociedad de Fútbol"=122, "Real Sociedad"=8 |
| 13 | Napoli | 130 | "Napoli"=160, "SSC Napoli"=130 |
| 14 | Aston Villa | 126 | "Aston Villa"=155, "Aston Villa FC"=126 |
| 15 | Chelsea | 124 | "Chelsea"=166, "Chelsea FC"=124 |

**Legătură directă cu P3.1**: cele 4 echipe cu discrepanțele cele mai mari găsite acolo (Manchester United −192, Inter Milan −241, Bayern Munich −127, Tottenham −81) apar toate în lista confirmată aici, cu exact același mecanism.

---

## Faza 4 — Livrabil

- **`docs/03_ENGINE/TEAM_IDENTITY_AUDIT.md`** — acest document.
- **`docs/03_ENGINE/canonical_team_mapping.csv`** — 288 rânduri, toate cele 137 echipe afectate: `raw_name, canonical_name, match_count, category, in_team_aliases_py, is_dominant_variant, team_total_matches, team_impact_matches`. Coloana `in_team_aliases_py` distinge cele 2 subseturi din Faza 2 (`yes` = deja acoperit, doar neaplicat; `no_add_to_team_aliases` = cele 17 cazuri noi, de adăugat).

**Nicio scriere în `match_history`/`elo_history`. Nicio modificare a `TEAM_ALIASES`/`normalize_team_name()`. Nicio schimbare de cod.**

---

## Răspuns direct la cele 3 întrebări (criteriul de succes P3.5)

1. **Câte identități duplicate există?** 137 echipe canonice, 146 perechi/grupuri de variante (129 deja acoperite de `TEAM_ALIASES` dar neaplicate, 17 noi, negăsite până acum).
2. **Cât de mult afectează istoricul și ELO?** 10.835 apariții de meci (10,1% din tot volumul `match_history`), distribuite relativ uniform pe cele 137 echipe (nu concentrate în câteva alias-uri) — inclusiv un număr mare de echipe mari, exact cele mai influente pentru ELO (Real Madrid, Arsenal, PSG, Man City, Bayern, Liverpool, Juventus).
3. **Există o mapare canonică suficient de sigură pentru a rerula P3?** Da — `TEAM_ALIASES` existent + cele 17 completări noi identificate acoperă exhaustiv (verificat prin clustering automat, zero cazuri rămase) tot ce se poate detecta mecanic. Nu e nevoie de o mapare nouă construită de la zero — e nevoie ca maparea deja existentă să fie aplicată consecvent.

---

## Cauza rădăcină — nu doar simptomul

Nu e o problemă de date fără sursă de reparare — e o problemă de **wiring**: `normalize_team_name()` există, e testat implicit (folosit deja de `oracle_api.py`, `oracle_engine.py`, `sync/import_historical.py`, `services/odds_backfill_service.py`), dar sincronizarea zilnică (`sync/sources/*.py`, calea care alimentează `match_history` cu meciuri noi în fiecare zi) nu-l apelează niciodată.

**Nu propun aici implementarea fix-ului** (în afara scopului explicit al acestei runde) — doar constat, cu dovezi, unde e gaura: fiecare writer din `sync/sources/` care scrie `home_team`/`away_team` direct din payload-ul API, fără să treacă prin `normalize_team_name()` mai întâi.

---

## Ce NU tratează acest document

- Nu repară `match_history` (nicio scriere, cerință explicită).
- Nu modifică `sync/sources/*.py` sau orice alt cod de producție (deși gaura de wiring e identificată precis, aplicarea fix-ului e un pas separat, ulterior, de decis explicit).
- Nu investighează manual, caz-cu-caz, cele 729 de nume „genuin distincte" — verificate doar prin clustering automat, nu prin revizuire umană individuală.
- Nu reinterogează sursele externe (Kaggle/API-Football/football-data.co.uk/Sofascore/FotMob) separat — informația lor e deja reflectată în `match_history`.
- Nu re-rulează P3 — asta rămâne un pas separat, ulterior, condiționat explicit de rezolvarea acestui audit (per decizia ta anterioară).
