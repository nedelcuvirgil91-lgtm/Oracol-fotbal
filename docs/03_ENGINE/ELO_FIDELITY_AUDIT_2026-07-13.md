# ELO_FIDELITY_AUDIT_2026-07-13.md — Football Oracle

**Status**: Măsurătoare pe date reale — zero cod scris, zero fișier modificat, zero patch propus. Răspunde la întrebarea finală din `ELO_CANONICAL_SOURCE_AUDIT_2026-07-13.md`: poate `ELOTracker`, AȘA CUM E IMPLEMENTAT ȘI ALIMENTAT AZI, să înlocuiască sursa live?
**Metodă**: am rulat local, azi, replay-ul complet `ELOTracker` (formulă identică cu `sync/backfill_features.py`) peste toate cele 53.409 meciuri reale din `match_history`, și l-am comparat cap la cap cu singura sursă „live" accesibilă. Fiecare cifră din acest document e calculată direct, nu citată.

---

## 0. O clarificare metodologică obligatorie, descoperită în timpul acestui audit

**Nu am putut obține un rezultat live real de la eloratings.net.** Singura „valoare live" accesibilă e rândul cache-uit în Supabase (`api_cache`, `provider="eloratings"`, `cache_key="elo_ratings"`) — l-am citit direct și **e identic, valoare cu valoare, cu `ELO_RATINGS_FALLBACK` din `mappings.py`**. În plus, `provider_metrics` are **zero rânduri** pentru providerul `eloratings` — nicio dovadă, nicăieri accesibilă mie, că scraping-ul real a reușit vreodată. Concluzie: **nu compar ELOTracker cu „ELO live real" — compar ELOTracker cu fallback-ul hardcodat, singura valoare demonstrabil folosită azi** (fie ca fallback ocazional, fie — dat fiind că n-am nicio dovadă de scraping reușit — posibil ca valoare *de facto* permanentă). Semnalez asta explicit, nu presupun că fallback-ul reprezintă adevărul extern.

---

## 1. Eșantionul disponibil — nu „toate echipele", ci toate cele demonstrabil comparabile

`ELO_RATINGS_FALLBACK` are 64 de intrări. Din acestea, **doar 16 (25%) există în `ELOTracker`** după replay complet peste tot `match_history` — restul de 48 lipsesc, verificat direct, nu estimat:

**Toate cele 48 lipsă sunt echipe naționale** (Argentina, Franța, Anglia, Brazilia, Spania... toate cele 48). **Niciun club nu lipsește din cele testabile care apar și în fallback.**

**Cauza, demonstrată**: `match_history` (sursa de antrenare, 53.409 rânduri) conține aproape exclusiv meciuri de club (ligile urmărite: Premier League, La Liga, Serie A, Bundesliga, Ligue 1, Romania SuperLiga + cupe europene) — zero meciuri de echipă națională procesate de replay. `ELOTracker`, azi, **nu poate produce, structural, niciun rating pentru nicio echipă națională** — nu e o chestiune de precizie, e o chestiune de acoperire zero.

**Consecință directă pentru „grupare pe echipe naționale vs. cluburi"**: comparația e posibilă **doar** pentru cluburi (16/16 din eșantion). Pentru echipele naționale, **nu pot demonstra nimic** — nu există date de comparat, nu presupun o valoare.

**Consecință pentru „campionate importante vs. restul"**: cele 16 cluburi comparabile aparțin exclusiv ligilor mari (Premier League, La Liga, Serie A, Bundesliga, Ligue 1) — fiindcă `ELO_RATINGS_FALLBACK` însuși conține doar cluburi de top. **Nu există nicio echipă „minoră" în fallback cu care să compar** — nu pot demonstra nimic despre comportamentul `ELOTracker` pe campionate secundare (ex. Romania SuperLiga) față de „live", din lipsă de o valoare de referință acolo.

---

## 2. Rezultatele complete — toate cele 16 echipe comparabile

| Echipă | Live/Fallback | ELOTracker | Diferență | Diferență % | Meciuri în tracker |
|---|---:|---:|---:|---:|---:|
| Atletico Madrid | 1890 | 1531 | −359 | −19,0% | 10 |
| Tottenham Hotspur | 1875 | 1575 | −300 | −16,0% | 280 |
| Chelsea | 1908 | 1618 | −290 | −15,2% | 290 |
| Liverpool | 1932 | 1673 | −259 | −13,4% | 305 |
| AC Milan | 1885 | 1658 | −227 | −12,0% | 288 |
| Juventus | 1895 | 1697 | −198 | −10,4% | 294 |
| Napoli | 1880 | 1701 | −179 | −9,5% | 290 |
| Manchester City | 1950 | 1782 | −168 | −8,6% | 312 |
| Real Madrid | 1945 | 1781 | −164 | −8,4% | 320 |
| Borussia Dortmund | 1885 | 1724 | −161 | −8,5% | 286 |
| Manchester United | 1900 | 1742 | −158 | −8,3% | 284 |
| Inter Milan | 1898 | 1791 | −107 | −5,6% | 160 |
| FC Barcelona | 1928 | 1827 | −101 | −5,2% | 314 |
| Paris Saint-Germain | 1920 | 1828 | −92 | −4,8% | 158 |
| Arsenal | 1915 | 1847 | −68 | −3,6% | 309 |
| Bayern Munich | 1940 | 1909 | −31 | −1,6% | 291 |

### Statistici agregate (n=16)
- **Medie diferență (semnată)**: −178,9
- **Medie diferență absolută**: 178,9
- **Mediană**: 166,0
- **Deviație standard (semnată)**: 87,5
- **Percentila 95 (absolută)**: 300,0
- **Diferență maximă**: 359 (Atletico Madrid, −19,0%)
- **Medie % diferență absolută**: 9,40%
- **Mediană % diferență absolută**: 8,58%

---

## 3. Aleatoriu sau sistematic?

**Sistematic, demonstrat fără echivoc**: `ELOTracker < Live` în **16 din 16 cazuri (100%)**. Zero excepții, zero semn opus. O eroare aleatorie ar produce un amestec de semne, cu medie apropiată de zero — nu e cazul aici.

## 4. Cauza — demonstrată, nu presupusă

Am verificat traiectoria reală a ratingului `ELOTracker`, an cu an, pentru 4 echipe:

| Echipă | Sfârșit 2023 | Sfârșit 2026 | Live/Fallback |
|---|---:|---:|---:|
| Bayern Munich | 1818 (117 meciuri) | 1909 (291 meciuri) | 1940 |
| Arsenal | 1687 (126 meciuri) | 1847 (309 meciuri) | 1915 |
| Real Madrid | 1824 (131 meciuri) | 1781 (320 meciuri) | 1945 |
| Atletico Madrid | 1531 (10 meciuri) | 1531 (10 meciuri) | 1890 |

**Cauza rădăcină, demonstrată prin distribuția reală a datelor**: am numărat meciurile din `match_history` pe an — **500 de meciuri în 2000, apoi un gol complet între 2001 și 2020 (zero meciuri), apoi 6.757 în 2021, crescând până la 13.570 în 2023**. `ELOTracker` pornește FIECARE echipă la 1.500 (neutru) și **acumulează informație doar din meciurile pe care le vede** — dacă un club de elită are, efectiv, doar ~5 ani de meciuri reale în fereastra replay-ului (2021-2026), nu 25, formula K=32/40 nu are matematic suficiente meciuri ca să urce ratingul de la 1.500 la ~1.900-1.950 (diferență 400-450 puncte), mai ales că majoritatea meciurilor unui club de top sunt victorii AȘTEPTATE (câștig marginal mic per meci, prin construcția formulei `K × (scor_real − scor_așteptat)`).

**Nu e produsă de K-factor sau home advantage ca valori greșite în sine** — sunt parametri standard, verificați identici cu formula folosită și de `sync/calculate_elo.py`. **E produsă de combinația (start la 1.500) + (fereastră reală de replay mult mai scurtă decât cariera reală a echipei)** — un „cold start" sever, nu un bug de parametru.

Caz special, semnalat separat: **Atletico Madrid are doar 10 meciuri în tot replay-ul** — anormal de puțin pentru un club din La Liga din 2021 încoace (celelalte cluburi din La Liga din eșantion au 280-320). E un indiciu de problemă de acoperire/normalizare specifică acestui nume de echipă în `match_history`, distinctă de cauza generală — **nu pot demonstra exact mecanismul** (nume alternativ nenormalizat? gol de import specific unei ligi/perioade?) fără o investigație separată, dedicată.

## 5. Offset constant sau divergență progresivă în timp?

**Nu pot demonstra un răspuns complet** — am o singură valoare live/fallback (fără serie temporală reală de la eloratings.net), deci nu pot compara „decalajul azi" cu „decalajul acum un an" pe date live.

**Ce pot demonstra**: traiectoria PROPRIE a `ELOTracker` (2023→2026, tabelul de la §4) arată **convergență, nu divergență** — decalajul se ÎNGUSTEAZĂ pe măsură ce se acumulează meciuri (Bayern: de la −122 la −31; Arsenal: de la −228 la −68), cu excepția Real Madrid (decalaj ușor CRESCUT, 1824→1781, posibil din cauza unei perioade recente sub formă slabă reflectată corect de un ELO reactiv — sau posibil zgomot pe eșantion mic de 4 echipe). Nu e un offset constant (deviația standard de 87,5 e prea mare față de media 178,9 ca să fie o constantă aditivă simplă) — e o convergență parțială, dependentă de câte meciuri reale a văzut fiecare echipă.

---

## 6. Verdict final

## **B. Există diferențe suficient de mari încât ELOTracker, în forma și cu datele de azi, NU poate deveni sursă canonică.**

**Argumentare, strict pe dovezi**:

1. **Acoperire zero pentru echipe naționale** — 48/64 (75%) din eșantionul de referință e complet neacoperit, nu parțial imprecis. O sursă canonică pentru un proiect care urmărește explicit „World Cup 2026" nu poate avea acoperire zero pe exact acest tip de competiție.
2. **Eroare sistematică, mare, pe cluburi**: medie 9,4% (până la 19% pentru cazuri individuale), 100% în aceeași direcție (subestimare). O eroare de această magnitudine, la promovare directă în producție, ar distorsiona sistematic orice predicție care se bazează pe ELO — exact motorul principal al modelului azi (confirmat în `PREDICTOR_ROADMAP_V4.md`: ELO domină importanța feature-urilor de 15-20×).
3. **Cauza e demonstrată și structurală, nu un parametru greșit ușor de ajustat**: fereastra reală de date (efectiv ~5 ani denși, cu un gol de 20 de ani în istoricul disponibil) e insuficientă pentru ca formula standard de Elo să conveargă la valori realiste pentru echipe cu pedigree de zeci de ani. Corectarea NU e o simplă recalibrare de K-factor — ar necesita fie un istoric de antrenare mult mai lung/complet, fie o inițializare informată (nu 1.500 neutru pentru toată lumea), fie o strategie explicită de reconciliere cu o sursă externă la pornire.

**Ce NU infirmă acest verdict**: concluzia arhitecturală anterioară (`ELO_CANONICAL_SOURCE_AUDIT_2026-07-13.md`) — că Kaggle e structural incapabil să servească vreodată predicții viitoare — **rămâne valabilă**. Acest audit nu spune „Kaggle ar fi mai bun" — spune că **niciuna dintre cele două variante, în forma de azi, nu e gata să fie singura sursă de adevăr**. Metodologia de replay rămâne singura DIRECȚIONAL corectă pe termen lung (poate acoperi trecut + viitor, e testabilă prin Champion/Challenger) — dar implementarea și datele de azi nu trec testul de fidelitate.

**Nu propun aici nicio soluție** (interzis explicit) — doar constat, cu dovezi: în forma actuală, `ELOTracker` nu poate înlocui sursa live fără o schimbare semnificativă fie de date (istoric mai lung/complet), fie de metodă (inițializare informată), fie de scop (rămâne o sursă complementară, nu unica).
