# ADR-059 — Reconcilierea identității este o operație de identitate, nu de date

**Status**: Approved — 2026-08-21
**Decide**: ce are voie să scrie reconcilierea istorică a identității (ID-025-01, Pasul 3).
**Relație cu ADR-025**: amendează un pas al strategiei aprobate acolo. Nu atinge Decizia (D + A), nu atinge invariantul.
**Relație cu ADR-036**: îl aplică fără excepție.

---

## Context

ADR-025 (Approved / Architecture Frozen, 2026-07-16) a stabilit reconcilierea istorică drept operație care „completează NULL-uri **și** marchează" (§Rollback Strategy). Pasul 3 din ID-025-01 copiază, câmp cu câmp, valori de pe rândul necanonic pe cel canonic, monoton (NULL → valoare, niciodată invers), pe cele 52 de coloane din `MERGE_COLUMNS`.

ADR-036 / D3.5 (Canonical Feature Ownership, 2026-07-20 — **la patru zile după**) a stabilit că fiecare coloană canonică din `match_history` are **un owner unic de scriere**. Cele două contracte nu au fost niciodată confruntate.

Dry-run-ul F4 rulat pe date reale (GitHub Actions run `32536869017`, 2026-08-21, cod real `process_group()`, zero scriere) a materializat conflictul: din 404 grupuri descoperite, 403 reconciliabile, merge-ul ar scrie **66 de valori pe 6 rânduri canonice, în 11 coloane** — toate cele 11 fiind ieșiri de predicție deținute de `_cache_prediction`.

### Verificare: nu există „subset sigur"

S-a verificat dacă `MERGE_COLUMNS` poate fi restrâns doar la coloane fără owner. Derivat mecanic din cod (nu din memorie), toate cele 52 au owner:

| Owner | Coloane | Sursa verificării |
|---|---|---|
| `run_backfill` | 21 (cele 20 `BACKFILL_COLUMNS` + `backfill_done`) | `sync/backfill_features.py`, `BACKFILL_COLUMNS` + linia 197 |
| sync de statistici | 19 (`*_shots`, `*_corners`, `*_possession`, `*_xg_actual`, cartonașe, faulturi, `*_ht_goals`, `stats_source`) | scriitorii de statistici |
| `_cache_prediction` | 11 (`*_xg_pred`, `prob_*_pred`, `mc_prob_*`, `weather_penalty`, `*_data_quality`) | `oracle_engine.py`, ADR-036 Stage 1 |
| writerii de import | 1 (`used_for_training`) | `sync/sources/openfootball.py:193`, `football_data.py:242` |

**Mulțimea coloanelor fără owner este vidă.** Pasul 3 nu poate supraviețui în nicio formă redusă.

### Argumentul de corectitudine (mai important decât cel de guvernanță)

Orice valoare aflată pe un rând necanonic a fost calculată **sub identitatea fragmentată**. `ELOTracker.ratings`, `FormTracker.history` și `H2HTracker.history` sunt dicționare cheiate pe șirul cu numele echipei; două grafii ale aceluiași club produc două lanțuri independente. Demonstrat empiric pe date live: `"Zwolle"` și `"PEC Zwolle"` au rulat lanțuri ELO paralele 2021→2025, cu divergențe de 1-15 puncte per meci; `"Liverpool"` = 1960 vs `"Liverpool FC (ENG)"` = 1615 în același meci.

Copierea unei astfel de valori pe rândul canonic nu doar încalcă ownership-ul — **o cimentează**: atât RPC-ul `_upsert_match_canonical_locked` cât și `run_backfill` sunt NULL-only, deci o valoare greșită ajunsă acolo blochează definitiv recalculul corect al owner-ului legitim.

Dry-run-ul din 2026-08-21 a raportat 0 completări de ELO — dar aceasta e o proprietate a datelor de azi, nu o garanție structurală. Cu alte rânduri, mâine, ar completa.

## Decizie

**Reconcilierea istorică a identității marchează. Nu contopește.**

1. **Pasul 3 (merge non-destructiv) se elimină din ID-025-01.** Reconcilierea nu scrie nicio coloană de date, pe niciun rând.
2. **Singurele coloane pe care reconcilierea are voie să le scrie sunt `superseded_by` / `superseded_at` / `superseded_reason`, exclusiv pe rândul NECANONIC.** Rândul canonic nu e atins de niciun octet.
3. **Reconcilierea devine owner unic al acestor trei coloane de audit** — o adăugire la modelul ADR-036, nu o excepție de la el.
4. **Diferența de date se raportează, nu se scrie.** Cele 52 de coloane rămân inspectate, iar raportul indică pentru fiecare grup ce coloane are rândul necanonic și nu are canonicul, **împreună cu owner-ul care le poate regenera**. Reconcilierea observă; owner-ul acționează.

### Ce se pierde, exact

Efectul întreg observat al Pasului 3 pe datele reale e scrierea în coloane deținute de `_cache_prediction`. Nimic altceva. Deci costul eliminării e exact acela:

- **Feature-uri și ELO** — pierdere zero. Rândurile canonice le au deja, iar `run_backfill` e oricum scriitor NULL-only și le completează la următoarea rulare, **din owner-ul legitim, calculate pe seria unificată**. Mai corect decât o copie.
- **Statistici** — pierdere zero pe setul actual; recuperabile prin re-sincronizare, de la owner.
- **Ieșiri de predicție** — singura pierdere reală: 6 meciuri trecute rămân fără înregistrarea predicției pe rândul canonic. Dintre ele doar 2 au și xG real, deci impactul practic asupra eșantionului de validare xG e de **2 meciuri**.

Rândurile necanonice nu se șterg niciodată — datele rămân integral prezente și trasabile prin `superseded_by`. „Pierderea" e strict despre ce se vede pe rândul canonic.

Dacă acele predicții sunt vreodată necesare pe rândul canonic, calea corectă e ca `_cache_prediction` — owner-ul — să reevalueze meciurile. Operație explicită, deținută, separată; niciodată efect secundar al reconcilierii.

## Consecințe

- Reconcilierea are o suprafață de scriere fixă și minimă: 3 coloane de audit, un singur rând per grup. Zero suprapunere cu orice owner, pentru orice coloană, **acum și în viitor** — regula nu trebuie re-judecată la fiecare coloană nouă adăugată în `match_history`.
- Rollback-ul devine trivial: reconcilierea nu mută niciun octet de date, deci anularea e ștergerea marcajului. Nu mai există „valoare completată care trebuie reconstituită".
- Modul EXECUTE devine substanțial mai puțin riscant decât presupunea ADR-025 — de aceea implementarea lui e autorizată prin acest ADR, execuția rămânând gatată separat (pilot înainte de rulare completă, conform Phase Gate ADR-025).
- Raportul ID-025-02 își schimbă semantica: `columns_populated` (ce s-ar scrie) devine `columns_with_data_gap` (ce lipsește și cine îl deține). Numărul rămâne informativ; sensul se schimbă din „plan de scriere" în „listă de sarcini pentru owneri".
- ADR-025 §Rollback Strategy, fraza „D nu șterge niciodată, ci doar completează NULL-uri și marchează", este amendată de acest ADR pentru reconcilierea istorică. Mecanismul D la **scriere** (RPC-ul, unde fiecare writer completează NULL-urile propriilor coloane) rămâne complet neschimbat — acolo nu există doi scriitori, fiecare writer scrie ce deține.

## Gol rămas deschis, deliberat

`idx_match_history_natural_key_canonical` operează pe `(home_team, away_team, kickoff_date)` **brut**. Writerii normalizează la scriere, deci intrările noi converg; rândurile istorice scrise sub un vocabular mai vechi rămân literal diferite, iar indexul nu le poate vedea ca echivalente. **Orice extindere viitoare de vocabular reintroduce fragmentarea, tăcut** — s-a întâmplat deja de două ori (F3 pe 2026-08-21 dimineața, apoi TSDB în noaptea aceleiași zile).

Acest ADR nu rezolvă golul. Îl consemnează ca necesitând un mecanism de detecție recurentă (rularea periodică a descoperirii DRY-RUN, care e read-only și ieftină), propus separat — adăugarea unui job automat e o decizie a proprietarului produsului.

### Addendum — 2026-08-22: detecția recurentă, implementată

Aprobat explicit de proprietarul produsului („adăugarea unui job automat e decizia ta"). **Golul structural rămâne deschis** (indexul e în continuare orb la vocabular) — s-a închis doar golul de *detecție*: latența maximă până la observarea unei recurențe scade de la „nedeterminat, doar prin investigație manuală" la 24h.

Opțiuni verificate, nu presupuse:

- **Index funcțional / trigger care apelează `normalize_team_name()` în SQL** — respinsă. Ar cere reproducerea integrală a vocabularului (~350 aliasuri + regula de sufix de țară) ca funcție `IMMUTABLE` PL/pgSQL — a doua sursă de adevăr pentru identitate, exact contradicția pe care ADR-058 a demonstrat-o costisitoare (v1.2, 141+ fuziuni false). Ar fi soluția structurală corectă *dacă* proiectul decide vreodată să mute rezolvarea identității în stratul de bază de date — decizie arhitecturală separată, proprie, nu o extensie tacită a acestui ADR.
- **Redescoperire periodică, read-only, diffată pe SET de chei față de un baseline git-committed** — aleasă. Reutilizează 100% motorul deja aprobat și verificat pe date reale de două ori (`MatchIdentityReconciliationService.run(dry_run=True)`); zero schemă nouă, zero risc de scriere; compararea pe SET (nu pe număr) prinde exact cazul unde un grup vechi dispare în aceeași rulare în care unul nou apare, fără ca numărul total să semnaleze nimic.

Implementare: `scripts/check_identity_drift.py` (verificare + `--emit-baseline`), `docs/00_GOVERNANCE/identity_drift_baseline.json` (baseline mecanic, niciodată editat de mână), `.github/workflows/identity_drift_check.yml` (cron zilnic 05:30 UTC + `workflow_dispatch`). Job-ul devine roșu în Actions la orice grup/conflict nou — tiparul deja folosit în tot proiectul, fără infrastructură nouă de notificare. Bump-ul baseline-ului rămâne deliberat neautomat: o decizie umană, comisă explicit după investigare.

## Referințe

- ADR-025 — Match Identity Implementation Strategy (Approved / Architecture Frozen)
- ADR-036 / D3.5 — Canonical Feature Ownership
- ADR-058 — Canonical Team Identity (F0-F3 + F2.5)
- `docs/03_ENGINE/ID-025-01` / `ID-025-02` — specificațiile amendate de acest ADR
- `docs/00_GOVERNANCE/F4-IDENTITY-RECONCILIATION-READINESS.md` — dovezile care au dus la acest ADR
- GitHub Actions run `32536869017` — dry-run pe date reale, cod real, zero scriere
