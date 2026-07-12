# Contribuție — Football Oracle

## Principii de bază

1. **Nu presupune, verifică.** Orice afirmație despre comportamentul codului existent trebuie confirmată direct (rulare, citire de cod), nu dedusă din memorie sau documentație veche.
2. **Măsoară, nu estima.** Orice îmbunătățire propusă pentru model (feature nou, schimbare de algoritm) trebuie susținută de o măsurătoare reală (walk-forward validation, ablație), nu de intuiție.
3. **Documentele Frozen nu se editează direct.** Vezi `docs/00_GOVERNANCE/FROZEN_REGISTRY.md` — orice schimbare a unui document Frozen necesită un ADR nou.

## Convenții de cod

- Python 3.11+, type hints unde e rezonabil (`from __future__ import annotations` la fiecare fișier nou).
- Comentarii `[ADAUGAT]`/`[MODIFICAT]`/`[ELIMINAT]` pentru schimbări semnificative — păstrează istoricul deciziei, nu doar rezultatul.
- Nicio cheie API/secret hardcodat în cod nou — folosește `key_manager.py` sau variabile de mediu.
- Funcții noi cu responsabilitate unică, clar documentată în docstring — motivul din spate, nu doar ce face.

## Teste

- Orice feature nou sau modificare de logică vine cu teste, în `tests/`.
- Testele nu trebuie să depindă de rețea sau credențiale reale — folosește stub-uri (vezi `tests/_stubs/`, `tests/conftest.py`) pentru dependințe grele (xgboost, kagglehub).
- Rulează suita completă înainte de orice commit: `python tests/_run_tests.py`.
- Validarea temporală (walk-forward, nu `train_test_split` aleator) e obligatorie pentru orice schimbare care afectează antrenarea ML — scurgerea temporală umflă artificial metricile.

## Commit-uri

- Mesaj scurt, la subiect: `modul: ce s-a schimbat` (ex. `mappings: consolidare alias Dinamo Bucuresti`).
- Un commit = o schimbare logică, nu un amestec de modificări nelegate.

## Workflow GitHub

- `main` e branch-ul de producție — orice schimbare majoră trece prin verificare (teste + audit, dacă atinge arhitectura) înainte de commit direct sau merge.
- Modificările de schemă Supabase necesită **obligatoriu** un fișier nou în `database/migrations/`, numerotat secvențial (`00N_descriere.sql`) — nicio schimbare de schemă doar "live în Supabase", fără fișier corespunzător.
- GitHub Actions (`.github/workflows/`) rulează automatizarea oficială — preferă extinderea unui workflow existent (`daily.yml`) în locul creării unuia nou, dacă scopul se suprapune.

## Pentru schimbări care ating arhitectura (Engine vs. Service, contracte de date, flux de predicție)

Urmează disciplina deja stabilită în proiect:
1. Documentează ipoteza și criteriul obiectiv de succes, **înainte** de cod.
2. Prezintă: scopul modificării, impactul asupra arhitecturii, fișierele afectate, riscurile, planul de implementare.
3. Așteaptă aprobare explicită înainte de a scrie cod.
4. Dacă schimbarea devine permanentă și atinge un contract deja Frozen, închide-o printr-un ADR nou (vezi exemplele din `docs/00_GOVERNANCE/`).
