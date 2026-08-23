# ADR-062 — Poarta de pregătire Team Profile măsoară disponibilitatea reală, nu meciurile din sezon

**Status**: Accepted (2026-08-23, aprobat explicit de proprietarul produsului: „aprob, corectează poarta")
**Autor**: Claude (arhitect principal, sesiune delegată explicit)
**Înlocuiește parțial**: decizia de prag din `docs/03_ENGINE/TEAM_PROFILE_FINISHING_EFFICIENCY.md` §5 (2026-08-18) — nu valoarea pragului (rămâne 300), ci **ce anume numără**.

## Context

`TEAM_PROFILE_TEST_THRESHOLD = 300` a fost stabilit (2026-08-15, redus 400→300 la 2026-08-18) ca poartă pentru testul de ablație al eficienței de finalizare. `get_finishing_data_readiness()` îl alimenta numărând **meciurile terminate din sezonul curent, în ligile domestice**.

Verificat live la 2026-08-23, înainte de a începe ablația: numărătoarea era la 298/300 — poarta urma să se deschidă în ore. Dar o măsurătoare suplimentară, făcută înainte de a acționa, a arătat că numără **cantitatea greșită**:

| Istoric xG anterior, ambele echipe | Meciuri din cele 298 |
|---|---|
| ≥1 meci | 190 (63,8%) |
| ≥3 meciuri | 68 (22,8%) |
| **≥5 meciuri (fereastra reală de producție)** | **15 (5,0%)** |

Formula de producție (`oracle_engine._build_flashscore_dna`, `last_n=5` → `rolling_finishing_and_setpieces`) are nevoie, pentru fiecare meci evaluat walk-forward, ca **ambele** echipe să aibă deja 5 meciuri anterioare cu xG real. La nivel de echipă: 210 echipe urmărite, medie 2,84 meciuri cu xG fiecare, maxim 7; doar 51/210 (24%) ajunseseră la 5.

Poarta s-ar fi deschis, deci, semnalând „pregătit pentru test" într-un moment în care doar 15 meciuri erau efectiv evaluabile. Nu e o eroare de implementare — pragul a fost stabilit corect pentru întrebarea de atunci („avem destule meciuri în sezon?"), care s-a dovedit a fi o întrebare diferită de cea care contează („avem destul istoric per echipă?").

### Verificări suplimentare care au însoțit descoperirea (context, nu decizie a acestui ADR)

Măsurători de stabilitate test-retest pe datele curente, prezentate proprietarului produsului: corelație split-half ≈ **−0,10** pentru `goals_per_xg` (două metode independente de împărțire, 32 respectiv 61 de echipe). Dar și martorii presupuși stabili (xG mediu 0,076, cornere 0,054, șuturi pe poartă −0,056) ies ≈ 0 — deci măsurătoarea **nu poate distinge** „metrica e zgomot" de „eșantionul e prea mic ca să măsoare orice". Istoric mai adânc nu există: xG real începe la 2026-05-02, 531 de rânduri în total, maxim 7 meciuri per echipă.

Ce se poate afirma riguros e doar aritmetica de eșantionare: eroarea relativă a raportului `goluri/xG` scade cu √(xG acumulat) — ±46% la 3 meciuri, ±36% la 5, ±20% abia la ~16. Dispersia observată între echipe (0,413) e integral explicată de zgomotul de eșantionare.

Pe baza acestor cifre, proprietarul produsului a evaluat explicit varianta de a reduce fereastra 5→3 (ar fi dat 68 de meciuri evaluabile în loc de 15, cu ≈2,7× mai multă putere statistică netă) și a decis, după prezentarea pro/contra: **se rămâne la 5**, planul inițial neschimbat. Acest ADR nu schimbă fereastra.

## Decizie

1. **`TEAM_PROFILE_TEST_THRESHOLD` rămâne 300.** Se schimbă exclusiv cantitatea numărată.
2. **Cheie nouă, `evaluable_matches`**, devine cifra care guvernează poarta: numărul de meciuri în care AMBELE echipe au deja ≥`TEAM_PROFILE_WINDOW` meciuri ANTERIOARE cu xG real. Cheile vechi (`finished_total`, `shots_on_target`, `xg`) rămân în răspuns, dar strict ca **context informativ** — nu se șterg, ca să rămână vizibil contrastul dintre cele două cantități.
3. **`count_matches_with_sufficient_history(rows, window)`** — funcție PURĂ, fără I/O, testabilă direct (tiparul deja folosit de `summarize()`, `classify()`, `truth_from_score()`).
4. **`TEAM_PROFILE_WINDOW = 5`** — constantă nouă, explicită. Trebuie să rămână identică cu `oracle_engine._build_flashscore_dna(last_n=...)`; divergența e prinsă de un test dedicat care citește direct semnătura funcției de producție (`inspect.signature`), nu lăsată pe seama atenției umane.
5. **Semantica „anterior" e STRICT pe zi calendaristică** (`kickoff_date <`), identică cu `as_of_date` introdus în aceeași sesiune pentru `get_team_recent_advanced_stats()`. Meciurile din aceeași zi nu se numără unele pentru altele: altfel un meci ar putea intra în propriul istoric (scurgere directă), iar ordinea în interiorul unei zile — nedeterminată de `kickoff_date` singur — ar schimba tăcut rezultatul. Implementarea procesează zi cu zi: evaluează întâi toate meciurile zilei contra istoricului strict anterior, abia apoi adaugă contribuțiile zilei.
6. **Un meci fără xG real nu construiește istoric** — nu ajută formula, deci nu se numără (Regula #8: nu se aproximează o stare lipsă). xG parțial (doar o parte) contribuie doar părții care îl are.
7. **UI**: bara de progres urmărește `evaluable_matches`, cu `finished_total` afișat dedesubt ca context explicit.

## Ce NU schimbă acest ADR

- Fereastra `last_n=5` — decizie explicită a proprietarului produsului, reconfirmată azi după analiza 3-vs-5.
- Formula (`rolling_finishing_and_setpieces`, `_sum_ratio`) — neatinsă.
- `FEATURE_COLUMNS` (ML) — neatins. Feature-ul rămâne NEPROMOVAT.
- `TEAM_PROFILE_EXCLUDED_LEAGUES` — neschimbată.
- Nicio scriere în Supabase — doar citiri.
- Nu declanșează testul de ablație; doar face ca poarta care îl autorizează să măsoare corect.

## Consecințe

- Poarta se va deschide semnificativ mai târziu decât ar fi făcut-o (estimare pe date: ~5-6 săptămâni, finalul lui septembrie, față de „azi-mâine") — dar când o va face, testul va fi efectiv posibil.
- Costul acceptat conștient: o întârziere reală, în schimbul evitării unui test rulat pe 15 meciuri, care ar fi produs zgomot cu aparență de rezultat — exact ce interzice „Filosofia proiectului" (un backtest favorabil nu e, singur, suficient).
- Aducerea rândurilor (necesară fiindcă „ambele echipe au ≥N anterioare" nu e exprimabil printr-un singur `count` PostgREST — ar cere LATERAL JOIN, indisponibil) e paginată cu `.order("id")` explicit înainte de `.range()`, aplicând direct lecția bug-ului de paginare găsit în aceeași sesiune (ADR-059, Addendum).

## Jurnal de execuție

Executat 2026-08-23.

**Fișiere modificate**: `database/queries.py` (constanta `TEAM_PROFILE_WINDOW`, funcția pură `count_matches_with_sufficient_history()`, `get_finishing_data_readiness()` extinsă cu `evaluable_matches` + paginare ordonată), `app.py` (bara urmărește cifra nouă, cea veche afișată ca context), `tests/test_database_queries_flashscore_team_dna.py` (3 teste actualizate pe forma nouă + 1 test nou pe paginarea ordonată).

**Fișier nou**: `tests/test_team_profile_readiness_gate.py` — 15 teste pe funcția pură.

**Teste de mutație** (nu doar teste care trec) — fiecare gardă critică verificată că prinde regresia reală, aplicând mutația în cod și confirmând eșecul:

| Mutație aplicată | Prinsă de |
|---|---|
| „ambele echipe" → „oricare echipă" (`and`→`or`) | 2 teste |
| meciurile din aceeași zi se numără unele pentru altele (o singură trecere, increment pe loc) | 1 test |
| xG lipsă contribuie totuși la istoric | 2 teste |

**Validare contra datelor reale**: interogare SQL de referință, independentă de implementarea Python (subinterogări corelate, trunchiere pe zi), pe producția reală → **15 meciuri evaluabile**, exact cifra pe care trebuie s-o producă noua poartă.

**Rulare completă**: `pytest tests/` — **2.605 passed, 2 skipped** (2.589 + 16 noi/actualizate), nicio regresie.
