# ADR-003 — Cache persistent pe 2 niveluri + quota persistentă

## Status
Acceptat, neimplementat încă (următoarea etapă de lucru).

## Context

Proiectul rulează din multiple contexte independente (telefon, PC, GitHub
Actions, Streamlit Cloud), fiecare cu propriul disc local. Două mecanisme
existente țin stare doar local, per-instanță:
- `cache_manager.py` — cache de răspunsuri API, TTL per categorie, doar în
  memorie/disc local al procesului curent.
- `key_manager.py` — quota de request-uri (`requests_today`, per provider),
  persistată într-un fișier JSON local (`CACHE_DIR/key_usage.json`).

Niciuna din cele două nu e comună între instanțe. Adăugarea unui al doilea
provider activ (API-Football) pe lângă Free Live Football, fără cache
comun, ar dubla request-urile pentru aceeași informație doar pentru că
rulează din contexte diferite.

## Decizie

**Nivel 1 (local, neschimbat)**: `cache_manager.py` rămâne cache-ul de
proces, TTL scurt, evită request-uri repetate în aceeași sesiune.

**Nivel 2 (Supabase, nou, sursă comună)**: tabel `api_cache`
(`provider`, `category`, `cache_key`, `payload_json`, `etag`,
`source_latency_ms`, `http_status`, `expires_at`). Cheia unică e
`(provider, category, cache_key)` — păstrează trasabilitatea sursei — dar
**citirea pentru decizia "mai trebuie un request?" ignoră `provider`**:
dacă există ORICE răspuns valid pentru `(category, cache_key)`, indiferent
cine l-a produs, nu se face un request nou. `cache_key` se construiește din
identificatori canonici proprii proiectului (`normalize_league_name`,
`fixture_id`), niciodată din ID-ul nativ al unui provider — altfel cache-ul
nu e cu adevărat agnostic de sursă.

**Quota** (`api_provider_status`, separat de `api_cache` — cicluri de viață
diferite): `provider`, `api_key_label`, `month` ('YYYY-MM' — ciclul real din
`key_manager.py`, care e **lunar**, nu zilnic cum presupusesem inițial),
`used`, `quota_limit`. Actualizat din header-ele răspunsului real
(`x-ratelimit-requests-remaining` etc.) și prin `record_request()` deja
existent, nu prin polling separat pe `/status` — acel endpoint apelat doar
la pornire, la eroare de rate-limit, sau diagnostic manual. La încărcare,
se ia **maximul** dintre valoarea locală și cea din Supabase (nu
suprascriere) — evită pierderea incrementărilor făcute de alte instanțe
sau, invers, a celor făcute local înainte ca Supabase să fi fost disponibil.

**Acoperire per provider** (`league_provider_coverage`): persistată,
actualizată o dată/zi, nu verificată live la fiecare decizie.

**Observabilitate** (`provider_metrics`): `calls`, `cache_hits`,
`cache_misses`, `errors`, `avg_latency_ms`, `last_success`, `last_failure`,
`consecutive_failures` — permite reguli simple de fallback
("`consecutive_failures >= 5` → treci pe backup") fără mecanism nou.

## Regula obligatorie

Înainte de orice request HTTP către un provider extern: verifică întâi
`api_cache` (Supabase), apoi cache-ul local, abia apoi request real. Niciun
request nou dacă informația există deja, indiferent de instanța/dispozitivul
care a produs-o.

## Consecințe

- Cost: 4 tabele Supabase noi, migrare treptată a `key_manager.py`/
  `cache_manager.py` să scrie și în Supabase.
- Beneficiu: adăugarea unui provider nou (Sofascore, FBref etc.) nu
  multiplică request-urile — se lovește de același cache comun.
