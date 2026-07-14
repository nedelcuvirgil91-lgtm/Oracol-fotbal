# Atomicity Contract — Promotion ca o singură tranzacție

**Status**: FROZEN (via ADR-019)
**Scope**: Contract normativ pentru mecanismul tehnic al Pasului 5 (Promotion)

---

## Constatarea de la Architecture Gate Review

Toate scrierile Supabase folosite de Learning Core până acum, fără nicio excepție (`training_runs`, `challengers`, `challenger_evaluations`, `model_config`, `model_weights` etc.), sunt apeluri PostgREST single-table (`client.table(...).insert()/.update()/.upsert()`) — fiecare, propriul request HTTP, propria tranzacție Postgres, independentă de oricare alta. Clientul Python Supabase (`supabase-py`/`postgrest-py`) **nu compune** mai multe asemenea apeluri într-o singură tranzacție atomică.

„Promote Challenger" (vezi `PROMOTION_CONTRACT.md`) cere DOUĂ scrieri cuplate — supersedarea campionului vechi + inserarea celui nou, ȘI tranziția Challenger-ului la `PROMOTED` — ca UN singur fapt, niciodată observabil parțial. Compunerea a trei apeluri `.execute()` separate (UPDATE campion vechi, INSERT campion nou, UPDATE challenger) NU satisface această cerință — un crash între oricare două dintre ele ar lăsa o stare intermediară reală, persistată.

## Decizie arhitecturală

**Promotion e o singură tranzacție Postgres.** Mecanismul necesar pentru asta e o **funcție Postgres (RPC)**, apelată printr-un singur `client.rpc("promote_challenger", {...}).execute()` din Promotion Service.

Acesta nu e „infrastructură în plus" sau un tipar nou introdus de dragul lui — e mecanismul minim necesar pentru a respecta un invariant deja acceptat (Contract #5, stabilit înainte de Pasul 1). **Corecție de acuratețe** (verificat, nu presupus — o afirmație anterioară din acest document, „primul asemenea obiect din proiect", era greșită): RPC NU e un tipar nou pentru proiect — `upsert_odds_snapshot` (`database/migrations/001_odds_history.sql:96-128`, apelat din `services/odds_persistence_service.py:197` și `services/odds_backfill_service.py:211`) e deja o funcție Postgres, deja apelată prin `client.rpc(...)`, exact pentru același motiv (o scriere care trebuie să rămână atomică, cu clauze care nu pot fi exprimate sigur prin `.upsert()` simplu). E primul precedent REAL, nu un tipar inventat pentru Learning Core — Promotion Service urmează acest precedent deja testat în producție, nu introduce unul nou.

## Ce e invariant aici, și ce e doar mecanism (adăugat la aprobarea Pasului 5)

RPC-ul (`promote_challenger`, `database/migrations/005_promotion.sql`) e implementarea tranzacțională ALEASĂ pentru acest invariant — nu invariantul însuși. Distincția contează dacă vreodată infrastructura se schimbă (altă bază de date, alt client, o versiune viitoare de Supabase cu tranzacții multi-statement expuse direct clientului):

> **Ce trebuie păstrat, necondiționat**: „Promote Challenger" e o singură unitate atomică — ambele efecte (`model_champions` + `challengers`) se aplică împreună, sau niciunul.
>
> **Ce NU trebuie păstrat, dacă infrastructura permite altceva mai simplu**: mecanismul concret (o funcție Postgres). Dacă un viitor client Supabase ar expune tranzacții multi-statement direct, sau dacă infrastructura de bază de date s-ar schimba complet, mecanismul se poate înlocui — atâta timp cât noua implementare satisface exact aceeași proprietate observabilă (secțiunea „Ce garantează acest mecanism" de mai jos), nu structura ei internă.

Orice înlocuire viitoare a mecanismului rămâne, totuși, o schimbare de contract (modifică „cum se produce" un invariant deja înghețat) — trece printr-un ADR nou, per regula standard din `FROZEN_REGISTRY.md`, nu printr-o editare tăcută a acestui document.

## Diviziunea muncii: Python (Promotion Service) vs. RPC (Postgres)

Nu tot ce ține de „Promote Challenger" intră în funcția Postgres — doar partea care CERE atomicitate transacțională. Restul (validarea artefactului, citirea verdictului imuabil) rămâne în Python, ÎNAINTE de a invoca RPC-ul — exact ordinea cerută de Contract #5 („validează artefactul ÎNAINTE de tranzacție"):

```
Promotion Service (Python)
  │
  ├─ 1. Citește Challenger (challengers) — verifică state == 'SUCCEEDED'
  ├─ 2. Citește verdict (challenger_evaluations) — verifică 'candidate_for_promotion'
  ├─ 3. Încarcă și validează artefactul (model_artifact_storage.load_model_artifact)
  │      — eșec aici ÎNSEAMNĂ zero scriere, oprire completă, niciun apel RPC
  │
  └─ 4. UN singur apel: client.rpc("promote_challenger", {
         training_run_id, algorithm_family, league_scope, promoted_by
       }).execute()
         │
         ▼
       promote_challenger(...)  [funcție Postgres, o singură tranzacție]
         ├─ verifică din nou (server-side) că challenger e SUCCEEDED
           — apărare împotriva unei curse între pasul 1 (Python) și apelul RPC
         ├─ dacă training_run_id e deja campionul activ → no-op, succes (idempotență)
         ├─ UPDATE model_champions SET superseded_at=now(), superseded_by=...
           WHERE algorithm_family=... AND league_scope=... AND superseded_at IS NULL
         ├─ INSERT INTO model_champions (..., training_run_id, promoted_by, ...)
         ├─ UPDATE challengers SET state='PROMOTED', terminal_at=now()
           WHERE training_run_id=... AND state='SUCCEEDED'
         └─ COMMIT (implicit — funcția reușește complet, sau nimic din ea nu se aplică)
```

Validarea artefactului (pasul 3) rămâne în Python și NU intră în funcția Postgres — o funcție SQL nu poate deserializa un model XGBoost. Aceasta e exact granița „ce cere atomicitate reală la nivel de date" (pașii 3-4 din secvența RPC) vs. „ce e doar o precondiție de citit dinainte" (pașii 1-3 din Python).

## Ce garantează acest mecanism

- **Atomicitate reală**: funcția rulează într-o singură tranzacție Postgres — fie toate cele trei scrieri (supersedare + insert + tranziție challenger) se aplică, fie niciuna.
- **Crash safety, colaps la două cazuri**: „înainte de commit" (nimic schimbat — starea de dinaintea promovării, exact ca și cum apelul n-ar fi avut loc) sau „după commit" (ambele efecte vizibile simultan). Nu există o a treia stare intermediară observabilă de niciun cititor extern (inclusiv Runtime, atunci când va citi Champion).
- **Idempotență**: verificată SERVER-SIDE, în aceeași tranzacție — nu doar în Python (unde o cursă între citire și apelul RPC ar putea produce un fals negativ).

## Ce NU decide acest document

Nu scrie codul SQL al funcției — asta e implementare, parte a Pasului 5 propriu-zis, nu a Pasului 4.5. Nu decide numele exact al parametrilor RPC dincolo de schița de mai sus (detaliu de implementare, nu contract arhitectural — vezi `FROZEN_REGISTRY.md`, Change Policy).
