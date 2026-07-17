# BACKFILL_NON_DESTRUCTIVE_STRATEGY_2026-07-12.md — Football Oracle

**Status**: Proiectare + analiză de risc — **zero cod scris, zero fișier de producție modificat**. Continuă direct `DATA_PIPELINE_INVESTIGATION_2026-07-12.md` (cauza) — acest document răspunde la „poate fi reparat, și cum, cu ce riscuri".
**Concluzie principală, pe scurt**: **da, `sync/backfill_features.py` poate fi făcut non-destructiv**, cu o schimbare de design clară (verificare NULL per-coloană, nu per-rând), dar există un risc structural real, nerezolvabil doar prin acest fix, pe care îl detaliez la §3.4 — completarea coloanelor derivate (`offensive_rating`/`defensive_rating`) tot ar folosi intern ELO-ul recalculat, nu ELO-ul real stocat, chiar dacă ELO-ul stocat rămâne neatins.

---

## 1. De ce codul de azi e destructiv (verificat, nu presupus)

`run_backfill()` (`sync/backfill_features.py:650-683`) are un singur punct de decizie: `if not match.get("backfill_done")`. Dacă adevărat, scrie **toate cele 10 coloane simultan**, necondiționat de valorile lor curente:

```python
if not match.get("backfill_done"):
    features = {
        "home_elo": home_elo, "away_elo": away_elo,               # din ELOTracker (replay intern)
        "home_form_score": home_form, "away_form_score": away_form,
        "home_offensive_rating": home_off, "home_defensive_rating": home_def,
        "away_offensive_rating": away_off, "away_defensive_rating": away_def,
        "h2h_modifier": h2h_mod, "h2h_meetings": h2h_meet,
    }
    pending_updates.append((match["id"], features))
```

`fetch_all_matches()` (`:75-112`) nu citește deloc cele 10 coloane — doar `backfill_done`. **Codul de azi n-are de unde să știe dacă `home_elo` are deja o valoare reală (din Kaggle) înainte s-o suprascrie.** Asta e mecanismul exact al riscului semnalat de tine.

Constatare pozitivă, verificată: scriptul **nu atinge niciodată** `actual_result`/`actual_home_goals`/`actual_away_goals` — nici azi. Cerința #3 (nu rescrie rezultate) e deja satisfăcută de designul curent, fără nicio schimbare necesară.

---

## 2. Strategia — fezabilă, cu o schimbare de granularitate

### 2.1 Schimbarea centrală: gating per-coloană, nu per-rând

- `fetch_all_matches()` trebuie extins să citească și cele 10 coloane (plus `backfill_done`, păstrat doar ca indicator agregat pentru raportare, nu ca decizie de scriere).
- Pentru fiecare rând, `features` nu mai e un dict fix — devine construit dinamic: **doar cheile ale căror valoare curentă e `None` intră în dict**. O coloană deja populată nu apare niciodată în payload-ul de UPDATE.
- Consecință directă: `home_elo`/`away_elo` nu sunt cazuri speciale — sunt acoperite automat de regula generală „scrie doar dacă NULL". Nu e nevoie de o excepție dedicată pentru ele — cerința #2 e un caz particular al cerinței #1.
- Rând complet deja populat (toate 10 non-null) → payload gol → **se sare peste rând complet, fără niciun apel de UPDATE** (păstrează beneficiul de performanță al lui `backfill_done` de azi, pentru rândurile deja complete).

### 2.2 Idempotență (cerința #4)

Cu regula NULL-only: rulare 1 completează ce lipsește; rulare 2, **fără date noi introduse între timp**, găsește aceleași coloane deja populate (identic cu ce ar fi scris oricum, din același replay determinist) → nu scrie nimic → stare finală identică. Idempotent, demonstrabil prin construcție, nu doar prin testare.

### 2.3 Reluare oricând, fără risc (cerința #5)

Scrierea e deja incrementală (`batch_size`, commit progresiv) — o întrerupere pierde cel mult batch-ul curent (nescriind, nu corupând). Cu regula NULL-only, reluarea nu mai depinde deloc de exact unde s-a oprit rularea anterioară — orice rulare nouă recalculează replay-ul determinist de la început și scrie doar ce încă lipsește. Mai robust decât mecanismul actual bazat pe `backfill_done`, nu doar la fel de robust.

---

## 3. Riscuri identificate — complet, inclusiv unul pe care implementarea simplă NU îl rezolvă

### 3.1 Risc rezolvat de design: suprascrierea ELO real cu ELO replay
Rezolvat direct de regula NULL-only (§2.1). Nivel de risc rezidual: **zero**, dacă implementarea respectă strict regula.

### 3.2 Risc structural, NEREZOLVAT de acest fix: ordinea cronologică între rulări
`ELOTracker`/`FormTracker`/`H2HTracker` reconstruiesc starea prin replay cronologic peste **toate** meciurile din `fetch_all_matches()`, în ordinea `kickoff_date, id`. Dacă între două rulări apar rânduri noi **mai vechi cronologic** decât rânduri deja completate (ex: un import istoric suplimentar, dintr-o ligă/sezon nou adăugat), a doua rulare ar calcula un ELO/formă diferit pentru meciurile de după acel punct — dar, fiind deja populate, nu le-ar rescrie (protejate de §2.1). Rezultat: valori **înghețate la starea primei rulări**, nu neapărat cele mai corecte posibile cu tot istoricul disponibil azi. Nu e un bug al fix-ului — e o limitare structurală a oricărui backfill incremental cu stare replay-uită. Singura soluție completă ar fi o rulare integrală, de la zero, de fiecare dată când apare istoric nou mai vechi decât ce există deja — cost mult mai mare, decizie separată, nu implicită.

### 3.3 Risc de granularitate parțială pe rând: elo completat separat de rating
Verificat cu date reale: intervalul ELO din `match_history` (Kaggle) e 1103-2141, medie 1524, deviație 161 — compatibil ca ordin de mărime cu un ELO standard „start 1500" (exact familia de metodologie folosită de `ELOTracker`, `INITIAL_ELO=1500`). **Nu pot demonstra însă că parametrii exacți coincid** (K-factor, home advantage) — Kaggle nu documentează metodologia exactă a coloanei `HomeElo`/`AwayElo` din sursă. Risc real, dar moderat (nu „scale complet incompatibile", cum ar fi fost cazul dacă intervalele nu se suprapuneau deloc).

### 3.4 Risc structural cel mai important, nerezolvat de simpla adăugare a verificării NULL: `offensive_rating`/`defensive_rating` folosesc intern ELO-ul din replay, NICIODATĂ ELO-ul real stocat

Verificat direct în cod: `team_pre_match_rating()` (`sync/backfill_features.py:503-568`) calculează `elo_before = round(elo_tracker.get_elo(team))` — **exclusiv din tracker-ul intern (replay, pornește de la 1500)** — și îl folosește ca `elo_offensive_multiplier`/`elo_defensive_multiplier` în `compute_team_offdef_rating()`, care determină `home_offensive_rating`/`home_defensive_rating`.

**Consecință**: chiar dacă regula NULL-only (§2.1) garantează că `home_elo` STOCAT nu e niciodată suprascris, completarea lui `home_offensive_rating` pentru un rând care are deja ELO real (Kaggle) tot va folosi ELO-ul din replay-ul intern pentru calculul ratingului — nu ELO-ul real din coloana `home_elo`. Cele două valori (ELO stocat vs. ELO folosit intern la calculul ratingului) pot diverge, silențios, fără nicio eroare vizibilă. E o inconsistență de-al doilea nivel, mai greu de observat decât o simplă suprascriere de coloană — dar la fel de reală.

**Nu propun implementare pentru asta** (interzis explicit de cerința ta) — doar semnalez: rezolvarea completă ar necesita ca `team_pre_match_rating()` să primească opțional un ELO real cunoscut (dacă există în DB pentru acel rând) și să-l prefere față de tracker — o schimbare de semnătură de funcție, nu doar de gating la scriere. Decizie separată.

### 3.5 Risc operațional: cost și vizibilitate
Rularea completă (fără scope de ligă) peste 53.409 rânduri — pur calcul Python, ieftin (secunde, nu minute) — dar scrierea (network, Supabase) rămâne costul dominant, proporțional cu numărul de coloane efectiv lipsă (nu cu numărul de rânduri). Recomand rulare cu `--dry-run` (deja suportat) înainte de orice rulare reală, pentru a vedea exact câte celule s-ar completa, nu doar câte rânduri.

### 3.6 Risc de testare: nimic din codul actual nu verifică azi non-destructivitatea
Nu există niciun test care să confirme că o rulare a doua oară nu schimbă nimic, sau că o coloană populată rămâne neatinsă. Orice implementare viitoare ar trebui însoțită de teste explicite pentru exact cele 5 cerințe ale tale (fiecare verificabilă mecanic, fără rețea: null-only, elo neatins, rezultate neatinse, idempotență pe 2 rulări simulate, reluare sigură după o „întrerupere" simulată).

---

## 4. Răspuns direct la întrebarea ta

**Da, `sync/backfill_features.py` poate fi făcut non-destructiv**, printr-o schimbare de design clară și limitată (gating per-coloană în loc de per-rând, extinderea `SELECT`-ului din `fetch_all_matches()`), care satisface mecanic cerințele #1, #2, #3 (deja satisfăcută), #4 și #5. Riscul de la §3.2 (ordine cronologică între rulări) e structural și nu poate fi eliminat doar prin acest fix — trebuie acceptat explicit sau rezolvat separat, cu cost mai mare (rulare completă de fiecare dată). Riscul de la §3.4 (rating calculat din ELO replay, nu din ELO real stocat) e cel mai important de reținut — e o inconsistență pe care simpla verificare NULL n-o rezolvă, doar o face mai puțin vizibilă.

Aștept decizia ta înainte de orice implementare.
