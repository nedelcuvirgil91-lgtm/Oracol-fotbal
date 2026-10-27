# Audit de utilizare — `ODDS_API_KEY` (27 octombrie 2026)

> **STARE: INSTANTANEU**, datat prin construcție (clasa ISTORIC din `ADR-083`).
> Un audit răspunde la „cum era pe 27 octombrie", nu la „cum e azi". Dacă e
> nevoie de starea curentă, se remăsoară — nu se citește de aici.
>
> **Niciun secret nu a fost citit, afișat, mutat sau modificat.** Auditul se
> sprijină exclusiv pe cod, pe fișiere de workflow și pe `provider_call_log`.
> Nicio valoare de cheie nu apare în acest document.

**De ce există**: pe 27 octombrie, măsurând dacă punctul B din planul Odds API
(TTL 4h → 24h) merită făcut, am găsit **418 apeluri HTTP 401** către `/sports`
în 8 zile. 401 înseamnă *neautorizat*, nu *cotă epuizată* — iar în aceeași
fereastră **32 de apeluri au întors 200**. Regula proiectului interzice
atingerea unui secret fără audit scris, deci m-am oprit și l-am făcut.

---

## 1. Unde se citește cheia

| Element | Valoare |
|---|---|
| Variabila de mediu | `ODDS_API_KEY` |
| Punct unic de încărcare | `key_manager.py:28` (`PROVIDERS`), prin `_apply_env_overrides()` |
| Punct unic de consum | `key_manager.get_api_key_param("oddsapi")` |
| Consumatori în cod de producție | `oracle_api._validate_api_keys`, `_fetch_market`, `_fetch_events_odds_api`, `_fetch_scores_odds_api` |
| Valori literale în cod | **ZERO** — eliminate la R4.1 (`oracle_api.py:43`, comentariu care documentează eliminarea) |

## 2. Care workflow-uri o declară

**4 din 48.**

| Workflow | Declară `ODDS_API_KEY` | Observație |
|---|:--:|---|
| `daily.yml` | ✅ | Etapele 1-4, inclusiv `odds_persistence` |
| `night_sync.yml` | ✅ | Apelează `run_daily` ca etapă |
| `sync_pre_match_odds.yml` | ✅ | Flux dedicat de cote |
| `poc_new_leagues_provider_lookup.yml` | ✅ | POC, `workflow_dispatch` |
| celelalte **44** | ❌ | — |

**Absența NU e un defect în cele 44.** Verificat punctual: `live_sync.yml`
rulează `sync/run_live.py`, care **nu are nicio referință** la `oracle_api`,
`FootballOracleAPI` sau `get_matches_for_week` — deci nu atinge Odds API și
nu are nevoie de cheie. Afirmația anterioară din notele proiectului, că
„un workflow fără `ODDS_API_KEY` (`live_sync`) a scris 13 chei goale", **nu
se confirmă pe calea Odds API** și rămâne de reverificat la originea ei.

## 3. Cauza rădăcină a celor 418 × HTTP 401 — nu e un secret lipsă

Lanțul, verificat verigă cu verigă în cod:

1. `key_manager._get_active_key()` (liniile 216-226) întoarce **`None`** în
   două situații: cheia e în `exhausted_set`, **sau** `used >= limit`.
2. Un provider fără variabilă de mediu rămâne cu `keys: []` — bucla nu are
   peste ce itera, deci tot **`None`** (docstring-ul `_apply_env_overrides`
   o spune explicit).
3. `get_api_key_param()` (241-243) propagă `None`.
4. `_validate_api_keys()` punea acel `None` în `params={"apiKey": ...}`.
   **`requests` omite un parametru `None`** — deci cererea pleca spre
   `/sports` **fără `apiKey`**.
5. O cerere fără cheie primește **401 garantat**.
6. Nimic nu ținea minte eșecul între instanțe (`_odds_keys_validated` e
   per-instanță, iar o rulare de noapte creează mai multe
   `FootballOracleAPI()`), deci se repeta: **30-113 apeluri pe zi**.

**Contorul de utilizare e corect**: `_increment_usage` scrie per **lună**
(`self._usage.get("month", "")`, linia 212), cu write-through în Supabase, iar
`_load_usage` citește și local și din Supabase — deci limita e partajată între
rulări, cum trebuie pentru o cotă lunară.

**Deci cele două populații de răspunsuri se explică fără ipoteze despre
secrete**: 200-urile sunt apeluri făcute cât contorul era sub limită;
401-urile sunt apeluri făcute după, **fără cheie**, pe un endpoint gratuit.

## 4. Verdict

| Întrebare | Răspuns |
|---|---|
| Lipsește secretul din vreun workflow care are nevoie de el? | **NU**, pe cât s-a putut verifica |
| Cheia e invalidă sau expirată? | **NU există dovadă** în acest sens |
| Trebuie atins, rotit sau înlocuit vreun secret? | **NU** |
| Era cheltuială de credite? | **NU** — `/sports` e gratuit; 418 apeluri, zero credite |
| Ce era defect, atunci? | **Codul trimitea o cerere care nu putea reuși** |

**Concluzia care contează, și e opusă celei pe care am pornit**: nu era o
problemă de secrete, era o gardă lipsă. `key_manager.is_available(provider)`
exista din totdeauna, răspunde exact la întrebarea „am o cheie utilizabilă?"
și acoperă **ambele** cauze din §3 — doar că `_validate_api_keys` nu o
întreba.

## 5. Ce s-a reparat în aceeași zi

1. **Gardă de precondiție** — `_validate_api_keys` verifică
   `is_available("oddsapi")` și nu mai trimite nimic fără cheie utilizabilă.
2. **Întrerupător de circuit** — un 401 real (cheie prezentă, respinsă) se
   memorează 30 de minute, într-o categorie de cache proprie
   (`oddsapi_validation`), ca eșecul să nu se repete la fiecare instanță.
   **Marcajul nu e servit niciodată ca date** — distincția față de defectul
   reparat în `_fetch_odds` în aceeași zi, unde un eșec ajungea să fie
   returnat ca rezultat gol „legitim".

Absența unei chei **nu** scrie marcajul: e o precondiție neîndeplinită, nu un
eșec de validare. Altfel o cheie adăugată între timp ar rămâne neîncercată
30 de minute degeaba. Gardă dedicată pentru asta.

## 6. Rămas deschis, NEatins deliberat

- **`_active_sport_keys` e write-only** (`oracle_api.py:211` declarat,
  `545` atribuit, **citit nicăieri**). Efectul real al validării e exclusiv
  popularea lui `_dead_keys`. Nu l-am șters — e cod inert, nu greșit, iar
  ștergerea cere verificarea că nimic extern nu îl atinge.
- **Punctele B și C** din `BACKLOG.md` §3.4 — după **1 noiembrie** (reset de
  cotă), fiindcă un plafon pornit peste un provider epuizat nu poate fi
  verificat că funcționează.
- **Afirmația „500/500 credite consumate"** din notele anterioare nu a fost
  reconfirmată independent în acest audit. Contorul lunar partajat explică
  comportamentul, dar cifra exactă vine de la ultimul răspuns 200 și n-a fost
  remăsurată.
