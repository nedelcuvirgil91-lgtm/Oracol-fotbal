# Model Artifact Storage — Contract (Pasul 1, Implementation Contract)

**Status**: Implementat parțial (persistență izolată, zero scriitori activi)
**Affects**: `learning_core/model_artifact_storage.py`, bucket Supabase Storage `model-artifacts`
**Authority**: Principal Software Architect, aprobat explicit de proprietarul produsului

Acest document nu este un ADR — nu schimbă nicio decizie de arhitectură deja
înghețată. El declară explicit contractul unui modul deja implementat, la
cererea Chief Architect, ca precondiție pentru închiderea Pasului 1. Orice
schimbare ulterioară a acestui contract (format, naming, ownership) trece
prin ADR nou, ca orice alt contract din proiect.

---

## 1. Stabilitatea formatului artefactului

- **Format persistat**: JSON nativ XGBoost (`model.save_model(path)` /
  `XGBClassifier().load_model(path)`), nu pickle. Ales explicit pentru
  robustețe cross-version, la decizia arhitecturală anterioară acestui pas.
- **Formatul este parte din contract.** Orice artefact deja persistat trebuie
  să rămână citibil de orice cititor viitor (Challenger Manager, Shadow,
  Promotion, Runtime-prin-Champion). Formatul nu e un detaliu de
  implementare — e o interfață binară între scriitor și cititori, potențial
  separați în timp de luni.
- **Nu poate fi schimbat fără migrare.** O schimbare de format (ex. trecere
  la un alt serializator, la o schemă diferită de fișier) face ilizibile
  toate artefactele deja persistate, cu excepția unui pas explicit de
  migrare care le rescrie. Conform CLAUDE.md („orice schimbare de contract
  ... trece printr-un ADR"), o asemenea schimbare necesită ADR dedicat,
  niciodată editare tăcută.
- **Versiunea XGBoost NU este verificată la load — doar presupusă.** Codul
  actual (`load_model_artifact`) nu citește, nu stochează și nu compară
  niciun câmp de versiune XGBoost. Se bazează integral pe compatibilitatea
  internă a formatului JSON nativ XGBoost între versiuni (motivul original
  pentru care a fost ales în locul pickle-ului). Instalarea curentă:
  `xgboost==3.2.0` (pin minim în `requirements.txt`: `xgboost>=2.0.0`).
  **Limitare reală, acceptată azi, nu ascunsă**: dacă o versiune viitoare de
  XGBoost ar deveni cu adevărat incompatibilă cu formatul unui artefact
  vechi, eșecul de `load_model()` e prins de `except Exception` generic din
  `load_model_artifact()` și întoarce `None` — indistinguibil, din
  perspectiva apelantului, de „artefact lipsă" sau „artefact corupt". Nu
  există azi un mecanism de a distinge aceste cazuri. Acceptat ca gol
  cunoscut pentru Pasul 1; o verificare explicită de versiune (stocată la
  save, comparată la load) rămâne un candidat pentru un pas ulterior, nu
  implementată preventiv.

## 2. Naming Convention

Cheia Storage exactă, azi:

```
model-artifacts/
    <training_run_id>.json
```

unde `<training_run_id>` e UUID-ul generat de `ml_predictor._record_training_run()`
(`str(uuid.uuid4())`), identic cu `training_run_id` din tabela `training_runs`.
Structură **plată** — fără prefix de `algorithm_family`/`league_scope` în
cale. Implementare exactă: `_artifact_path()` din
`learning_core/model_artifact_storage.py`.

**De ce e suficient azi**: `training_run_id` e deja unic global (constrângere
`UNIQUE` în `training_runs`), deci nu există coliziune posibilă. Metadatele
de discriminare (`algorithm_family`, `algorithm_version`, `league_scope`)
există deja, complet, în rândul `training_runs` corespunzător — orice
cititor care are `training_run_id` poate obține acele metadate printr-un
singur query, fără să le fi duplicat în calea de Storage.

**Declarat explicit, nu implicit**: acest naming e considerat parte a
contractului Pasului 1, nu un detaliu accidental. O schimbare la structură
ierarhică (`algorithm_family/league_scope/training_run_id.json`) ar fi
posibilă fără a rupe cititorii existenți (fiindcă azi nu există niciun
cititor real, per secțiunea 3), dar dacă are loc, trebuie declarată la fel
de explicit — nu introdusă tăcut odată cu Pasul 2+.

## 3. Ownership

**Owner-ul persistenței Model Artifact este Challenger Manager** — consistent
cu Varianta B, deja aleasă și înghețată în designul domeniului. **Amendat
prin ADR-048 (Pasul 9, EPIC „ML Activation & Oracle Evolution")**: fluxul
descris inițial aici (`train() → compare() → DACĂ îmbunătățire simultană →
persist() → devine Challenger`) a fost scris înainte ca Challenger FSM-ul
(ADR-016) și Orchestratorul (ADR-030) să fi fost efectiv implementate — nu
corespunde arhitecturii reale, construite ulterior. Fluxul real:

Persistarea are loc imediat după o antrenare reușită (`status == "trained"`),
ca parte a `continuous_learning._phase_b_train_new()` (Faza B, Orchestrator),
**înainte** de `challenger_manager.create_challenger()` (D2, ADR-048) — nu
există un pas de comparație separat înainte de creare; comparația reală
(verdict statistic) are loc ulterior, pe durata stării `EVALUATING`, pe baza
traficului live acumulat în `shadow_predictions`. Vezi ADR-048 pentru
justificarea completă, Failure Matrix-ul (§4) și invariantul de sistem INV-1
(§5) garantate de această ordine.

**Training Runner nu scrie niciodată artefacte.** Responsabilitatea lui se
oprește la a produce modelul antrenat (în memorie) și metricile
(`training_runs`, deja implementat prin ADR-015). Persistarea fizică a
artefactului e strict a Orchestratorului (`continuous_learning.py`), invocat
conform contractului Learning Orchestrator deja înghețat — niciodată
component-la-component direct (`challenger_manager.py` nu apelează
`save_model_artifact()`, per D1, ADR-048).

**Istoric — stare la închiderea Pasului 1** (păstrat ca înregistrare, nu mai
reflectă starea curentă): verificat atunci explicit (`grep -rn
model_artifact_storage`), zero componente apelau `save_model_artifact()` sau
`load_model_artifact()` — modulul era complet izolat. **Primul scriitor real
a fost introdus prin ADR-048/Pasul 9** — `continuous_learning._phase_b_train_new()`,
respectând regula de ownership de mai sus de la primul rând de cod scris, nu
retroactiv prin corectarea unui scriitor greșit deja existent.

## 4. Garbage Collection

**Nu există GC în Pasul 1. Acceptat deliberat.** Dacă proiectul s-ar opri
definitiv la Pasul 1, artefactele s-ar acumula nelimitat în bucket-ul
`model-artifacts`, fără nicio ștergere automată — cost de stocare crescător,
fără plafon.

Azi acest scenariu e pur ipotetic: cu zero scriitori activi (secțiunea 3),
bucket-ul e gol și rămâne gol până la primul apel real din Challenger
Manager. Declarația de mai sus e valabilă pentru momentul în care scrierile
încep, nu pentru starea curentă.

Curățarea (politică de retenție, ștergere la respingerea unui Challenger,
limită per `algorithm_family`, etc.) rămâne o decizie separată, explicită,
printr-un ADR ulterior — nu implementată preventiv, per regula „nu construim
infrastructură pentru viitor".

## 5. Atomicitatea locală (nu Contract #5 — acela vizează Promotion)

Verificat direct în cod, ambele funcții:

```python
with tempfile.TemporaryDirectory() as tmpdir:
    tmp_path = Path(tmpdir) / "model.json"
    model.save_model(str(tmp_path))          # scriere locală
    raw_bytes = tmp_path.read_bytes()
# ↑ tmpdir șters aici, la ieșirea din `with` — garantat, chiar dacă
#   save_model() ridică excepție în interiorul blocului.

client.storage.from_(BUCKET_NAME).upload(...)  # ↓ rulează DUPĂ ce tmpdir
                                                 #   a fost deja șters
```

**Nu există leak.** `tempfile.TemporaryDirectory()` garantează ștergerea
directorului temporar la ieșirea din blocul `with`, indiferent de succes sau
excepție în interior — echivalentul unui `finally`. În plus, prin construcție,
apelul de `upload()` către Storage rulează **strict după** ce directorul
temporar a fost deja distrus (bytes-ii sunt deja citiți în memorie,
`raw_bytes`, înainte de ieșirea din `with`) — deci nu există nicio fereastră
în care un eșec de upload (timeout de rețea, Storage indisponibil) ar putea
lăsa în urmă un fișier temporar orfan. Simetric la `load_model_artifact()`:
`tmp_path.write_bytes(raw_bytes)` și `model.load_model(...)` rulează ambele
în interiorul aceluiași `with`, cu aceeași garanție de curățare la ieșire,
succes sau eșec.

---

## Ce rămâne, explicit, nedecis (nu ascuns)

- Structura ierarhică de naming (dacă va fi vreodată necesară) — nedecisă,
  nu blocantă azi.
- Verificare explicită de versiune XGBoost la load — gol cunoscut, acceptat.
- Politică de Garbage Collection — gol cunoscut, acceptat, deferată la ADR
  ulterior.

Niciuna dintre acestea nu contrazice vreun contract deja înghețat
(Champion/Challenger/Learning Orchestrator/Contract #5 de atomicitate a
Promotion-ului) — sunt goluri delimitate, în afara scopului Pasului 1.
