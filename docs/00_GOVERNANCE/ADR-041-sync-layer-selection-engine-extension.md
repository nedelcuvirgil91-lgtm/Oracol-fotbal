# ADR-041 — Extinderea Selection Engine-ului (ADR-034) către Sync Layer

**[ACTUALIZAT 2026-07-28]** Faza 1 (inclusiv acest document) e deja pe `main`
— verificat direct (`git show origin/main:...`, conținut identic, commit
`384c545` „Close Sprint 1 Faza 1: ADR-041 + real orchestrator wiring for
Soccer Football Info"). Rândul de status de mai jos, scris la data redactării
ADR-ului, e depășit — păstrat neschimbat ca parte a documentului Frozen,
corectat aici doar ca notă de trasabilitate, per aceeași regulă aplicată
`ARCHITECTURE_STATE.md`/`ADR037_DEPLOYMENT_PLAN.md`.

**Status**: FROZEN — Faza 1 implementată, testată (1318 teste verzi, vezi
raportul de închidere Sprint 1), pe branch `claude/continua-faza-1-adr5-o52jat`,
nemerge-uit încă în `main`. Faza 2 rămâne document de referință, aprobată ca
direcție, neblocantă — nu se implementează acum. Devine contract normativ
pentru orice extensie viitoare a alegerii de provider în Sync Layer — nicio
modificare arhitecturală ulterioară decât printr-un ADR nou, per disciplina
aplicată ADR-034…040.

**Autor**: Claude, redactat la cererea explicită a proprietarului produsului,
în paralel cu implementarea Fazei 1 (nu înainte, nu după — decizie explicită:
"ADR-ul nu trebuie să blocheze Sprintul 1. Poate fi scris în paralel cu
implementarea").

**Data**: 2026-07-27.

**Companion**: `docs/00_GOVERNANCE/ADR-034-provider-capability-selection-architecture.md`
(Selection Engine original, neatins), `docs/00_GOVERNANCE/ADR-039-universal-synchronization-architecture-supabase-first.md`
(Sync Layer, neatins) — arhivă completă a designului (v1→v6, iterativ, cu
audit de provideri, estimare de consum, split Faza 1/Faza 2) există în
istoricul conversației Etapa C / Sprint 1; acest document transcrie decizia
finală, înghețată, nu procesul.

---

## Context

Football Oracle avea deja, prin **ADR-034**, un Selection Engine complet
(Provider Registry → Capability Registry → League Mapping v2 → Health
Monitor → scor ponderat pe 6 componente) — dar limitat la un singur
consumator: `oracle_api.py::get_matches_for_week()`, în **shadow mode**
(`selection_engine_shadow_enabled`, PR5), niciodată live.

**Etapa C, Sprint 1** a cerut adăugarea unui al doilea domeniu de date —
**Match Statistics** (posesie, xG, șuturi, cornere, faulturi, ofsaiduri,
cartonașe, penalty-uri, schimbări, lineup, manageri, arbitru, stadion) — cu
un nou provider candidat, **Soccer Football Info** (RapidAPI), verificat
live 2026-07-27 (Romania SuperLiga confirmat `important=true`; UEFA
Champions/Europa/Conference League + calificări confirmate pe calendarul
real; un meci complet verificat câmp cu câmp — Dinamo București 5-1 CS U
Craiova, 25.07.2026 — inclusiv un gol anulat VAR, identic cu o sursă
independentă de control).

Proprietarul produsului a stabilit, explicit și repetat, două cerințe care
inițial păreau în tensiune:

1. **Redundanță reală, niciun provider existent eliminat.** "Nu aprob
   eliminarea niciunei chei API existente... Obiectivul arhitecturii este
   redundanța, nu înlocuirea providerilor." — 8 provideri rămân toți
   funcționali, niciunul "mort".
2. **Nicio duplicare a Selection Engine-ului.** "Ai dreptate că nu trebuie
   să duplicăm Selection Engine-ul... Dacă `provider_selector.py` și
   `provider_health.py` sunt într-adevăr complet generice, atunci nu vreau
   un al doilea motor de selecție pentru Sync Layer."

Verificarea directă a codului (`provider_selector.py`, `provider_health.py`)
a confirmat: ambele module sunt deja generice, pure, fără nicio dependință
de `oracle_api.py` — construite corect pentru reutilizare de la început
(ADR-034, Regula de Aur #4/#5). Singurul lucru care lipsea era **integrarea
propriu-zisă** ca al doilea consumator, plus câteva extensii aditive
(politici LIVE/BACKFILL, versionare de ponderi, un singur punct de scriere
în `provider_metrics`) — nu o arhitectură nouă.

## Decizie

**Selection Engine-ul definit de ADR-034 se extinde către Sync Layer ca al
doilea consumator — nu se construiește un al doilea motor de scor.**

### 1. Reutilizare, nu duplicare

`sync_provider_manager.py` (modul nou) e punctul unic de decizie "ce
provider servește acest domeniu, pentru această ligă, acum" pentru Sync
Layer. Nu conține nicio logică proprie de scorare — deleagă integral la
`provider_selector.recommend_provider()` (ADR-034, neschimbat structural).

```
Sync Adapter (ex. sync/sync_match_statistics.py)
        │
        ▼
sync_provider_manager.choose_provider(domain, league, intent)
        │
        ├─ selection_engine_v2 == False (implicit) ──► lanț static de urgență
        │
        └─ selection_engine_v2 == True ──► provider_selector.recommend_provider()
                                             (ADR-034, NEATINS structural)
```

Piesele NOI, aditive, sunt strict:
- maparea `domeniu → (league, DataType)` (`_DOMAIN_TO_DATA_TYPE`);
- lanțul static de urgență, folosit doar când flagul e dezactivat sau
  Selection Engine-ul nu găsește niciun candidat eligibil
  (`_STATIC_FALLBACK_CHAINS`, accesat public prin `fallback_chain()`);
- alegerea presetului de ponderi LIVE/BACKFILL (§2 mai jos);
- un `priority_fn` injectabil, sursă de configurare externă pentru
  tie-breaker-ul `priority` (§4 mai jos).

Nimic din formula de scor, din `find_candidates()`, din `score_provider()`
sau din `recommend_provider()` nu a fost rescris. Verificare directă
(`git diff` pe `provider_selector.py`): singurele schimbări sunt (a) un
câmp nou `version: int = 1` pe `SelectionWeights`, cu valoare implicită — nu
schimbă niciun apel existent; (b) o a doua instanță de `SelectionWeights`
(date, nu cod — `SELECTION_WEIGHTS_BACKFILL`); (c) un parametru opțional
`priority_fn`, cu comportament implicit identic celui de dinainte. Nicio
linie din `compute_weighted_total()`, `find_candidates()`,
`score_provider()` (corpul funcției) sau `recommend_provider()` (corpul
funcției) nu a fost modificată structural.

### 2. Două preseturi de ponderi — LIVE și BACKFILL, formula neschimbată

Formula rămâne EXACT cea din ADR-034:

```
score = 0.40 · availability + 0.25 · coverage + 0.15 · reliability
      + 0.10 · quota        + 0.05 · latency  + 0.05 · priority
```

**Niciun coeficient al formulei, nicio componentă, nicio ordine de calcul nu
s-a schimbat.** Ce s-a adăugat sunt **date** — al doilea set de valori
pentru cele 6 ponderi, ales în funcție de scopul cererii:

| Pondere | LIVE (`SELECTION_WEIGHTS`, implicit) | BACKFILL (`SELECTION_WEIGHTS_BACKFILL`) |
|---|---|---|
| availability | 0.40 | 0.20 |
| coverage | 0.25 | 0.15 |
| reliability | 0.15 | 0.15 |
| quota | 0.10 | **0.40** |
| latency | 0.05 | **0.00** |
| priority | 0.05 | 0.10 |

**LIVE** rămâne calibrarea originală ADR-034 (folosită deja de
`oracle_api.py`, shadow mode, neatinsă) — privilegiază disponibilitatea și
acoperirea confirmată, latența contează puțin. **BACKFILL** inversează
priorități: cota rămasă devine componenta dominantă (0.40, cea mai mare din
toată formula), latența devine complet irelevantă (0.00) — motivat de
comportamentul cerut explicit: un backfill istoric mare nu trebuie să
epuizeze un provider premium rezervat pentru trafic LIVE; se redistribuie
natural spre providerul cu cotă mai mare, pe măsură ce starea reală de cotă
se actualizează între apeluri succesive (Health Monitor, deja existent,
neatins).

Selecția presetului se face prin `Intent` (`sync_provider_manager.Intent`,
enum `LIVE`/`BACKFILL`) — parametru explicit la `choose_provider()`, nu
dedus implicit. `sync/sync_match_statistics.py` (sincronizarea zilnică)
folosește `Intent.LIVE`.

### 3. Versionare de ponderi — reproductibilitate istorică

`SelectionWeights` capătă un câmp nou, `version: int = 1`, **distinct** de
`ALGORITHM_VERSION` (care versionează STRUCTURA formulei — numărul/
semnificația celor 6 componente, neschimbată aici). Fiecare preset
(`SELECTION_WEIGHTS`, `SELECTION_WEIGHTS_BACKFILL`, orice preset viitor) își
ține propria linie de versionare, incrementată DOAR manual, la o
recalibrare reală bazată pe date din shadow mode — niciodată dedusă din
git/commit (ar rupe Regula de Aur #4, determinism).

Scopul practic: `ProviderChoice.weights_name` + `ProviderChoice.weights_version`
sunt scrise alături de orice decizie de alegere — un consumator care
loghează perechea `(weights_name, weights_version)` poate reconstitui exact
ce calibrare a produs o decizie istorică, chiar dacă valorile presetului
respectiv se schimbă ulterior.

### 4. Priority ca valoare de configurare, nu cod

Tie-breaker-ul static `priority` (0.5, neutru pentru toți providerii) rămâne
implicit — dar `score_provider()`/`recommend_provider()` capătă un parametru
opțional `priority_fn: Callable[[str], float] | None`, exact tiparul deja
folosit pentru `health_fn`/`league_state_fn` (dependință injectabilă, Regula
de Aur #5). `provider_selector.py` **nu importă niciodată `supabase_client`**
(Dependency Direction, neschimbat) — citirea configurării externe trăiește
exclusiv în `sync_provider_manager._provider_priority_fn()`, care POATE
importa `supabase_client` (Sync Layer, nu Selection Engine pur).

Implicit (`priority_fn` neinjectat, sau cheia `provider_priority` absentă
din configurare) → 0.5 pentru toți, identic comportamentul de dinainte —
zero schimbare până la o configurare explicită (Regula #3, CLAUDE.md:
niciun comportament nou nu pornește implicit activ).

### 5. Owner + Fallback real, nu doar teoretic

`choose_provider()` întoarce UN singur candidat "cel mai bun" pentru o
pereche (domeniu, ligă). Asta nu e suficient pentru garanția de redundanță
cerută explicit — dacă providerul ales nu acoperă liga unui meci anume
(ex. Soccer Football Info nu are încă mapare pentru majoritatea ligilor,
doar Romania SuperLiga confirmată live), meciul nu trebuie să rămână
neprocesat.

`fallback_chain(domain)` expune public lanțul static COMPLET pentru un
domeniu. Adaptorul concret (`sync/sync_match_statistics.py`) construiește
ordinea reală de încercare — alegerea lui `choose_provider()` întâi, apoi
restul lanțului, fără duplicate — și încearcă fiecare provider, pe rând,
PÂNĂ CÂND unul produce efectiv date pentru acel meci specific. Niciun
provider existent nu devine inaccesibil doar pentru că nu e primul ales.

**Limită recunoscută explicit, Faza 1 — nu ascunsă**: gating-ul de buget la
nivel de orchestrator (`SyncTask.provider` → `RequestManager.should_request`)
se aplică STRICT primului provider din ordinea de încercare. Dacă acela are
cota epuizată, task-ul întreg e blocat de orchestrator înainte de a ajunge
la fallback. Fiecare adaptor/client își gatează totuși PROPRIUL buget intern
(`RequestManager`/`RateLimitManager`, neatins) — un provider din lanțul de
fallback interceptat DUPĂ ce task-ul a pornit rămâne protejat individual.
Gating de buget conștient de ÎNTREG lanțul de fallback la nivel de
orchestrator e Faza 2 (§Faza 2 mai jos).

### 6. Feature flag — rollback instant, fără schimbare de cod

`selection_engine_v2` (Supabase `model_config`, implicit `False` — Regula
#3, CLAUDE.md) controlează dacă `choose_provider()` folosește Selection
Engine-ul sau lanțul static direct. Tiparul e identic celui deja folosit de
`selection_engine_shadow_enabled` (ADR-034, PR5) —
`shadow_config.is_enabled()` — nimic nou inventat.

Dezactivarea flagului revine INSTANT la lanțul static de urgență, fără
rollback de cod, fără redeploy — cerință explicită a proprietarului produsului.

### 7. Punct unic de scriere în `provider_metrics`

Înainte de această extensie, `provider_metrics` era scris direct din
`oracle_api.py` și `football_providers.py`, fiecare cu propriul apel la
`supabase_client.record_provider_call()`. Cerință explicită: "Trebuie să
existe un singur punct de scriere a metricilor de provider, pentru toate
componentele (Oracle API, Sync Layer, Scheduler)... Nu trebuie să existe
două căi diferite."

`RequestManager.record_result(provider, endpoint, success, latency_ms)`
(metodă nouă) devine acest punct unic pentru orice cod NOU de Sync Layer —
`soccerfootballinfo_client.py` îl folosește exclusiv. Căile existente
(`oracle_api.py`, `football_providers.py`) rămân NEATINSE — "no defect, no
rewrite" (ADR-038, principiul 3): funcționează deja corect, nu se
rescriu fără un defect demonstrat. Orice cod NOU capătă automat aceeași
scriere, fără să reimplementeze un INSERT paralel.

### 8. Provider nou — redundanță, nu înlocuire

Soccer Football Info se înregistrează ca al **9-lea** provider (Provider
Registry, Capability Registry, `mappings.py`, `league_mapping.py`, key
manager — reutilizează cheia RapidAPI a FreeLF, cont confirmat comun).
Niciunul din cei 8 provideri existenți (API-Football, Odds API, WeatherAPI,
football-data.org, FreeLF, ESPN, TheSportsDB, SportAPI) nu e eliminat, nu e
dezactivat, nu-și pierde rolul — auditul complet per provider (owner/
domenii/limite/consum/verdict) trăiește în arhiva de design (§2 al
documentului v6, transcrisă parțial mai sus), nu se repetă aici.

## Faza 1 (Sprint 1 — obligatorie, IMPLEMENTATĂ)

Exact lista îngheţată în specificaţia Sprint 1 v6, §13:

1. ✅ Audit de schemă live + migrare aditivă `match_history` (15 coloane noi
   + `provider_raw_json`, `CREATE ... IF NOT EXISTS`, COALESCE-only în
   `upsert_match_canonical`).
2. ✅ Înregistrare Soccer Football Info — Provider Registry, Capability
   Registry, `mappings.py` (Romania SuperLiga), `league_mapping.py`.
3. ✅ Punct unic de scriere `provider_metrics` pentru Sync Layer
   (`RequestManager.record_result()`).
4. ✅ `SELECTION_WEIGHTS_BACKFILL` — al doilea preset, formula neatinsă,
   plus `SelectionWeights.version`.
5. ✅ Priority ca valoare de config, nu cod (`priority_fn` injectabil +
   `sync_provider_manager._provider_priority_fn()`).
6. ✅ `rate_limit_manager.py` — verificat: era deja complet generic per
   `provider` (zero cod hardcodat la API-Football); Soccer Football Info e
   pur și simplu al doilea utilizator real.
7. ✅ Adaptor Soccer Football Info — set complet de câmpuri
   (`soccerfootballinfo_match_statistics_adapter.py`) + resolver
   (`soccerfootballinfo_event_resolver.py`) + client
   (`soccerfootballinfo_client.py`) + `provider_raw_json`.
8. ✅ `database/queries.get_finished_matches_missing_stats()` extinsă
   (`require_referee`, opt-in, zero regresie pe apelanții existenți).
9. ✅ Teste — oglindă a suitei FreeLF deja scrise (39 teste noi pentru
   client/resolver/adaptor/`sync_provider_manager`), plus gardă AST extinsă
   (ADR-036: `SOCCERFOOTBALLINFO_ONLY_COLUMNS`, două teste noi de scope).
10. ✅ Wiring real — `sync/sync_match_statistics.py` folosește
    `choose_provider()` + `fallback_chain()` în loc de FreeLF hardcodat;
    `sync/run_daily.py` actualizat (Pasul 1/6).
11. ✅ Redactare ADR-041 (acest document) — în paralel, neblocant.

## Faza 2 (Sprint 1.1 / Sprint 2 — neblocantă, NEÎNCEPUTĂ)

Documentată explicit ca direcție aprobată, nu ca lucru de făcut acum:

1. Expunerea `last_success`/`last_failure` prin `ProviderHealth` (coloane
   deja scrise în `provider_metrics`, doar neexpuse azi de Health Monitor).
2. Health Score pe ferestre 24h/7 zile + breakdown 429/403/timeout —
   extensie reală a Health Monitor-ului (azi: doar stare cumulativă,
   all-time).
3. Cost estimat per provider.
4. Dashboard intern de monitorizare.
5. Analitice avansate.
6. Gating de buget la nivel de orchestrator conștient de ÎNTREG lanțul de
   fallback (§5 de mai sus — azi doar primul provider e gatat la nivel de
   task).

## Neblocant, dar nescopat unei faze — de reluat separat

- Test live scurt: API-Football Injuries pe sezonul curent (impactul
  restricției de sezon specific pe `/injuries`, neverificat separat de
  `/fixtures`).
- Decizie separată: owner Team Form — 3 surse candidate (FreeLF azi,
  football-data.org parțial, Soccer Football Info propus), aprobare
  explicită necesară, nu decisă unilateral aici.

## Consecințe

- **Pozitiv**: Selection Engine-ul ADR-034 devine, dovedit prin cod, cu
  adevărat reutilizabil — al doilea consumator real (Sync Layer) nu a cerut
  nicio schimbare a formulei, doar extensii aditive (preset nou, versionare,
  injectare de prioritate). Confirmă empiric premisa arhitecturală din
  ADR-034 (straturi independent testabile, generice).
- **Pozitiv**: redundanța cerută explicit e reală, nu doar declarată —
  `fallback_chain()` + retry per meci în `sync/sync_match_statistics.py`
  garantează că niciun provider existent nu devine inaccesibil.
- **Neutru**: flagul `selection_engine_v2` pornește dezactivat — în
  producție, azi, alegerea de provider se face prin lanțul static
  (`soccerfootballinfo` → `freelivefootball` → `sportapi` pentru Match
  Statistics), nu prin Selection Engine-ul propriu-zis. Activarea reală a
  flagului rămâne o decizie separată, ulterioară acestui ADR — infrastructura
  există, comportamentul implicit rămâne neschimbat (Regula #3).
- **Risc acceptat, documentat**: gating de buget doar pe primul provider al
  lanțului (§5) — un provider primar cu cota epuizată blochează întregul
  task, chiar dacă un fallback ar avea cotă disponibilă. Acceptabil pentru
  Faza 1 (SFI: ~200 req/zi, consum estimat 4-8 req/zi pentru scope-ul curent
  SuperLiga — marjă foarte largă); rezolvarea completă e Faza 2.
- **Cost real, numit**: `sportapi` apare în lanțul static ca al treilea
  fallback pentru `match_statistics`, dar nu are încă un adaptor concret
  implementat — sărit explicit la runtime (log, nu excepție), nu o gaură
  ascunsă. Devine un adaptor real doar la un caz de utilizare dovedit.

## Referințe

- `docs/00_GOVERNANCE/ADR-034-provider-capability-selection-architecture.md`
  — Selection Engine original, FROZEN, neatins structural.
- `docs/00_GOVERNANCE/ADR-039-universal-synchronization-architecture-supabase-first.md`
  — Sync Layer, FROZEN, neatins; principiul 1 (producția nu depinde de
  infrastructura de sincronizare) verificat explicit pentru codul acestui ADR
  (`soccerfootballinfo_*` nu sunt importate niciodată de `oracle_engine.py`/
  `app.py`/`oracle_api.py`).
- `docs/00_GOVERNANCE/ADR-036-canonical-feature-ownership.md` — disciplina de
  ownership unic de scriere, reaplicată integral noilor coloane
  (`SOCCERFOOTBALLINFO_ONLY_COLUMNS`, gărzi AST în
  `tests/test_canonical_feature_ownership.py`).
- `provider_selector.py`, `provider_health.py`, `sync_provider_manager.py` —
  codul normativ.

---

**FREEZE CONFIRMAT (Faza 1).** Formula de scor a Selection Engine-ului
(ADR-034) rămâne neschimbată. Extensiile de mai sus — preseturile LIVE/
BACKFILL, versionarea ponderilor, injectarea priorității, lanțul de
fallback runtime, punctul unic de scriere în `provider_metrics` — sunt
contractul normativ pentru orice consum viitor al Selection Engine-ului din
Sync Layer. Faza 2 rămâne direcție aprobată, neimplementată — orice
activare intră printr-o decizie separată, nu prin rescrierea acestui
document.
