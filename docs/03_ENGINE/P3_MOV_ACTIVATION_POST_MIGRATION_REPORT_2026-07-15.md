# P3 — Activarea V2_damped: Raport Post-Migrare

**Status**: Executat pe producție (Supabase, proiect `Prediction`). Continuă `P3_MOV_ACTIVATION_DESIGN_REVIEW_MIGRATION_PLAN_2026-07-15.md` (aprobat, Varianta A). Migrarea e completă și verificată.

---

## 1. Ce s-a executat

| Pas | Acțiune | Rezultat |
|---|---:|---|
| 0 | Snapshot backup (6 coloane) | `match_history_mov_activation_backup_20260715` — 53.409 rânduri |
| 1 | Reset controlat (6 coloane) | Confirmat: exact 53.409 rânduri, toate 6 coloane simultan `NULL` |
| 2-5 | `run_backfill()` — 4 rulări GitHub Actions succesive (Varianta A) | Vezi §2 |
| 6 | Verificări post-execuție | Vezi §3 |
| 7 | Verificare de convergență | CONVERGE = **True** — vezi §4 |

Total `match_history` la finalul migrării: **53.431** (nu 53.430 — vezi §5, cauză identificată, neatribuită migrării).

---

## 2. Istoricul complet al rulărilor `backfill.yml`

| Run | ID | Rânduri scrise | Durată | Conclusion |
|---|---|---:|---:|---|
| 1 | `#29435171525` | 14.799 | ~60min21s | `cancelled` (timeout) |
| 2 | `#29439536729` | 14.739 | ~60min22s | `cancelled` (timeout) |
| 3 | `#29443849636` | 17.519 | ~60min20s | `cancelled` (timeout) |
| 4 | `#29447880913` | 6.352 | ~27min10s | **`success`** |
| **Total** | — | **53.409** | **~208 min (~3h28min)** | — |

**Corecție explicită față de estimarea din Migration Plan**: planul estima „~3 rulări" pe baza throughput-ului mediu de la P3.5 (~5,59 rânduri/sec). Throughput-ul real măsurat aici a fost puțin mai mic (~2,55-4,86 rânduri/sec, variabil între rulări) — au fost necesare **4 rulări**, nu 3. Nicio eroare, doar o estimare puțin optimistă; Varianta A (rulări manuale repetate) a funcționat exact cum era proiectată — fiecare rulare succesivă a scris rândurile rămase, fără duplicare, fără pierdere, mulțumită Writer Protection (Regula #13).

Timp total, inclusiv reset + verificări: **~208 min migrare + ~5 min operațiuni SQL + ~2 min verificare convergență ≈ 3h35min**.

**Zero erori întâlnite** pe parcursul celor 4 rulări (spre deosebire de P3.5, unde un rând izolat necesitase o rulare suplimentară) — toate cele 4 rulări au scris exact rândurile așteptate, fără `Erori: N>0` în log.

---

## 3. Verificări post-execuție (Migration Plan §3.5)

| Verificare | Rezultat |
|---|---:|
| Rânduri cu `home_elo IS NULL OR away_elo IS NULL` (din 53.409) | **0** |
| Valori negative pe cele 6 coloane | **0** |
| Interval `home_elo`/`away_elo` | 1187 – 2021 (plauzibil, fără explozii numerice) |
| Rânduri cu `actual_result IS NOT NULL` | **53.409** (neschimbat) |

---

## 4. Verificare de convergență (Migration Plan §3.5.3)

Script temporar (`scripts/_mov_convergence_check_temp.py`, workflow `_mov_convergence_temp.yml`, run `#29450055001`, succes, ~90s) — walk-forward **read-only** pe `match_history` de producție, deja actualizat, **fără niciun override** (spre deosebire de `P3_REVALIDATION_POST_P3_5`, unde ELO era calculat în memorie; aici se citesc direct valorile scrise în DB).

| | Măsurat (producție, după activare) | Așteptat (`P3_REVALIDATION_POST_P3_5`, calcul in-memory) | Diferență absolută |
|---|---:|---:|---:|
| Accuracy | 0,4981 | 0,4992 | 0,0011 |
| Log Loss | 1,0124 | 1,0121 | 0,0003 |
| Brier Score | 0,6053 | 0,6051 | 0,0002 |

**CONVERGE (prag 0,01 absolut pe toate 3 metrici): True.**

Diferențele minuscule sunt consistente cu rotunjirea la scriere în DB (`round()` aplicat de `run_backfill()`) vs. precizia float64 păstrată în calculul in-memory al raportului de revalidare — nu indică nicio eroare de execuție.

---

## 5. Observație — rândul nou apărut în timpul migrării

La verificarea finală, `SELECT COUNT(*) FROM match_history` a arătat **53.431**, nu 53.430 (cifra urmărită pe tot parcursul sesiunii). Investigat înainte de a considera migrarea validă (per criteriul de stop din Migration Plan §3.6):

```
id=126710, home_team="England", away_team="Argentina", league="World Cup 2026",
kickoff_date="2026-07-15" (azi), actual_result=NULL, backfill_done=false
```

**Cauză identificată, nu migrarea**: un fixture nou (meci viitor/în desfășurare, fără rezultat încă) inserat de sincronizarea zilnică independentă (`sync/run_daily.py`, proces separat, neatins de această migrare) în cele ~3h35min cât a rulat activarea. Fiindcă `actual_result IS NULL`, acest rând **nu a fost niciodată în scope-ul migrării** (care a acoperit exact cele 53.409 rânduri cu rezultat, verificat identic înainte și după) — apariția lui e un eveniment normal de producție live, nu o anomalie a migrării.

---

## 6. Concluzie

- **Migrarea e completă și verificată**: toate cele 53.409 rânduri cu rezultat au acum `home_elo`, `away_elo`, `home_offensive_rating`, `home_defensive_rating`, `away_offensive_rating`, `away_defensive_rating` calculate cu formula MOV V2_damped (ADR-022).
- **Zero valori corupte, zero regresie de integritate** (rânduri, valori negative, interval plauzibil).
- **Convergență confirmată** cu cifrele deja publicate în `P3_REVALIDATION_POST_P3_5_2026-07-15.md` — diferențe sub 0,12pp pe toate 3 metrici.
- **Formula MOV V2_damped e acum activă în producție** pentru toate datele de antrenare ML — următoarea rulare reală de `MLPredictorEngine.train()` (retrain, decizie separată, neinclusă aici) va folosi automat ELO-ul actualizat.
- **Live serving rămâne neatins** — confirmat pe tot parcursul (Design Review §1.4).

## 7. Ce NU face acest document

- **Nu declanșează reantrenarea ML** (`retrain_ml` a rămas `false` pe toate cele 4 rulări) — decizie separată, ulterioară.
- **Nu deschide P4 (ELO Trend)** sau orice alt experiment din roadmap.
- **Se oprește aici**, așteptând următoarea instrucțiune explicită.
