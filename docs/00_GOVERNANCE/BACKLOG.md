# BACKLOG — singura listă

**Fără dată în nume, deliberat.** Fiecare „BACKLOG_2026-10-13", „PLAN_POST_…",
„STARE_…_SEARA" a fost scris ca să fie *cel actual* și a devenit în câteva zile
încă un loc în care să cauți. Documentul ăsta se **actualizează**, nu se
dublează. Dacă apare un al doilea backlog cu dată în nume, e un simptom.

**Ultima măsurare completă: 2026-10-20.** Totul de mai jos e verificat atunci,
read-only, nu reluat din memorie. Unde o cifră e veche, scrie cât e de veche.

**Cum se folosește**: §1 e ce te așteaptă pe TINE (se citește prima, e singurul
loc unde se pierd lucrurile). §2-§5 e munca, ordonată după valoare reală. §6 e
ce NU facem și de ce — ca să nu se redeschidă. §7 sunt documentele de detaliu;
ele rămân valabile ca dovadă, dar **ordinea de lucru e aici, nu acolo**.

---

## 1. ⚠️ DECIZII CARE TE AȘTEAPTĂ

Nimic din lista asta nu avansează fără tine. Ordinea e după cât costă amânarea.

| # | Ce | Stare | Costul amânării |
|---|---|---|---|
| **1.1** | **`decision_feed` #8** — expirarea Challenger-ului `blend_v1/174e7e17` | `pending`, **creată azi**, TTL 27 oct | Blochează antrenarea unui `blend_v1` nou. Exact scenariul care a costat 14 zile în august. |
| **1.2** | **D-6 — două tabele de backup** | restante de **~30 de zile** peste termenul propriu | Mic, dar una (ADR-069, 72 kB) e singura tabelă din 62 **fără RLS**. Decizia e „se păstrează" / „se șterg"; dacă se păstrează, merită RLS. |
| **1.3** | **ADR-077** — criteriul de rutare SFI | propunere, recomandarea s-a **inversat** la măsurare | Zero cost acum (criteriul inert nu face rău). Dar ADR-ul stă deschis cu o recomandare greșită scrisă în el. |
| **1.4** | **ADR-075** — `CHECK` care face imposibilă supersedarea fără motiv | propunere | Mic. Monitorul prinde deja clasa (clasa 9, activă). |
| **1.5** | **D-14** — tabelă de audit `model_config` | decizie cerută | **Recomandarea mea: NU acum.** Reparația aplicată (skill + gardă) recuperează ce s-a pierdut. |
| **1.6** | **Punctul 5** — clasa de duplicate `openfootball` | nemăsurat | 1893 de rânduri active; dacă duplică, afectează setul de antrenare. **Se măsoară întâi, read-only.** |
| **1.7** | **F3** — pornirea experimentului de value selection | ~**4 noiembrie** | Nimic nu pornește automat (ADR-002). |

**`decision_feed` #6** stă `approved` din **14 septembrie** și **nu poate fi
comisă de niciun cod** — vezi §2.1. Nu e o decizie care te așteaptă; e un defect.

---

## 2. TIER 1 — bucla de decizie umană nu funcționează

**Ăsta e cel mai important lucru din document, și e și cauza tehnică a
problemei pe care ai ridicat-o**: lucrurile se pierd. Nu doar în conversație —
**și în sistem**. Trei defecte independente compun același efect.

### 2.1 Decizii care nu pot fi comise (D-8)

`learning_core/consensus_validation.py` produce propuneri, dar **nu are fază de
execuție**. `commit_decision()` e apelat exclusiv din `continuous_learning.py`.

Deci decizia **#6**, pe care ai aprobat-o pe **14 septembrie**, va rămâne
`approved` la infinit. Sistemul ți-a cerut o decizie pe care nu o poate duce la
capăt.

**De decis**: se implementează execuția, sau se oprește producerea de propuneri
pe care nimeni nu le poate comite. Cere ADR (schimbă responsabilitatea unei
componente).

### 2.2 Nimic nu semnalează o decizie uitată (D-5)

`automation_runs.sweep_stale_decisions()` implementează politica de TTL din
ADR-026. **Niciun workflow nu o apelează** — singurii apelanți sunt două teste.

Consecința e ambivalentă, și tocmai de asta trebuie decisă: azi ne avantajează
(decizia #7 a rămas aprobabilă mult după TTL), dar înseamnă că **#7 a stat 22 de
zile fără niciun semnal**, iar #6 e blocată de o lună.

**De decis**: se cablează sweep-ul (TTL-ul devine real, cu riscul de a expira
propuneri nevăzute), sau se înlocuiește TTL-ul cu o alertă. Ambele cer ADR.

### 2.3 Ecranul nu numește ce aprobi (D-11)

`app.py:1531` — titlul e `[T3a] decizie #7 · run_id=786`. **Nu numește niciodată
acțiunea.** `decision_kind` apare doar îngropat într-un `st.json` brut, lângă un
buton verde „✅ Aprobă".

A produs deja o confuzie reală: ai raportat „am promovat noul candidat", dar
ce aprobaseși era o **expirare**. Consecința a fost benignă atunci. Același
ecran va servi și propuneri de **promovare** și de **rollback**.

**Cost**: mic, strict prezentare, probabil fără ADR. **Valoare: mare** — e
singurul punct unde ADR-002 (aprobarea umană) atinge efectiv un om.

> **Recomandarea mea pentru Tier 1**: 2.3 întâi (ieftin, închide un risc de
> guvernanță), apoi 2.1 și 2.2 împreună, ca un singur ADR despre ciclul de viață
> al unei decizii — sunt aceeași problemă văzută din trei unghiuri.

---

## 3. TIER 2 — calitatea datelor

Starea e **bună**, și merită spus: din 1699 de meciuri terminate în sezon,
**91,5% au xG real**, iar octombrie e **100% (340/340)**. Reparația ADR-076 plus
recuperarea au închis golul de 39 de zile.

### 3.1 Restanța de xG, pe luni (măsurat 20 oct)

| Lună | Terminate | Fără xG | Acoperire |
|---|---:|---:|---:|
| iulie | 146 | **53** | 63,7% |
| august | 679 | **85** | 87,5% |
| septembrie | 534 | 6 | 98,9% |
| octombrie | 340 | **0** | **100,0%** |

Cele 53 din iulie sunt în mare parte **structurale** (calificări europene, unde
Flashscore nu publică xG). Cele 85 din august sunt restanța genuin recuperabilă.

**De făcut**: încă o tranșă de `--recover-missing-stats` țintită pe august.
Ieftin, fără decizie — lista se recalculează din bază la fiecare rulare.

### 3.2 Detectorul de rupere PARȚIALĂ (D-12 §D-C)

Clasa 7 prinde „extragerea a murit complet", nu „3 categorii din 45 s-au
redenumit". Instrumentul e ieftin (`match_statistics_extended` e deja EAV).
**Dar linia de bază nu există**: pornit azi, ar compara cu golul de 39 de zile.

**De reluat ~2 noiembrie.**

---

## 4. TIER 3 — calitatea predicțiilor

**Afirmația cea mai importantă, și e contraintuitivă**: măsurat contra unui reper
extern pe 986 de meciuri, Oracle e **statistic indistinct de casele de pariuri
pe 97,5% din volum** (−1,98 pp, z = 1,35, nesemnificativ).

Asta schimbă ce înseamnă „mai bun". Două leviere au fost **măsurate și închise**:

- **Calibrarea** — erorile pe șase găleți sunt toate sub ~1,3σ. Recalibrarea
  n-ar aduce nimic.
- **Accidentările** — ar acționa exact pe meciurile unde nu se vede headroom.
  Plafonul „măsurat" de +16,67pp s-a dovedit artefact (oracolul nul câștigă mai
  mult). Deprioritizat cu motiv.

### 4.1 Singurul levier identificat cu dovezi: filtrul de formă în cupe

`supabase_client.py:372` — forma e filtrată pe competiție. Filtrul **se
păstrează** (măsurat: dispersia campionat→UCL e 2,0 ppm; o formă indiferentă la
competiție ar fi inversat ordinea Liverpool/PSV). Ce lipsește:

1. **legarea de sezon** — azi `lookback_days=365` trece peste granița de sezon;
2. **o cale de rezervă onestă** pentru echipele fără istoric european — formă
   domestică penalizată, marcată ca substitut, **niciodată constantă**.

**Cele două se decid împreună**: un fix care atinge doar sezonul mută 16 cluburi
mari din „date vechi" în „fără date" — ar înrăutăți situația. Cere ADR.

**Onest despre mărime**: forma 1 (constanta neutră) e deja închisă — zero meciuri
servite cu constantă după 20 august. Rămâne forma 2 (date reale dar vechi), a
cărei **pagubă nu e cuantificată**, fiindcă vechimea formei servite nu se
persistă nicăieri. Deci ăsta e un candidat de investigat, nu o reparație sigură.

### 4.2 F3 — value selection (~4 noiembrie)

Nu e despre acuratețea predicției, ci despre **ce pariezi**. Brațul care
guvernează, `market_floor_040`, e la **103/150** cu 3,07/zi; cele 8 săptămâni se
împlinesc ~31 oct. Condițiile se închid împreună.

Capcană consemnată: poarta numără **fixture-uri distincte per categorie**, nu
pariuri. Pe pariuri pare demult complet (1342) — nu e.

---

## 5. TIER 4 — igienă

| Ce | Măsurat | Acțiune |
|---|---|---|
| Rânduri `gate_validation_test` în `model_champions`/`challengers` | 3 „campioni activi" + 1 challenger, din 14 iulie | artefacte de test care poluează orice interogare de stare — de șters sau de marcat |
| `openfootball` | 2119 rânduri, **1893 active** | se **măsoară** dacă cele nesufixate duplică (§1.6) |
| Backup-uri | 9,77 MB + 72 kB, 59 de zile | §1.2 |
| `Din. Minsk (BLR)` | 2 rânduri, fără geamăn | lăsat deliberat, cu gardă |
| ~49 de cluburi văzute doar cu sufix | — | igienă de vocabular, nu reparație |

---

## 6. CE NU FACEM, ȘI DE CE

Lista asta există ca să nu se redeschidă din entuziasm.

- **Recalibrarea probabilităților** — măsurat, zero câștig.
- **Accidentările** — fără headroom vizibil; dacă se reia, ordinea e obligatorie:
  flag oprit → colector → backtest read-only → shadow → activare.
- **Mărirea pragului Team Profile 300→600** — n-ar ajuta; zgomotul depinde de xG
  per echipă, nu de mărimea setului. Reluare ~feb-mar 2027.
- **`weather_forecast`** — gol lăsat documentat prin decizie explicită.
- **Norvegia + Suedia** — martie 2027 (sezon apr-oct).
- **Tabela de audit `model_config`** — nu încă (§1.5).
- **Promovare automată** — contrazice ADR-002, cere ADR dedicat.

---

## 7. UNDE SUNT DETALIILE

Documentele astea rămân valabile **ca dovadă și istoric**. Ordinea de lucru e
aici, nu în ele.

| Document | Ce conține |
|---|---|
| `CLAUDE.md` §DECIZII | D-1…D-14, cu toată istoria fiecăreia |
| `PLAN_DECIZII_DESCHISE_2026-10-20.md` | analiza celor cinci decizii + §6.1-6.4, ce s-a executat |
| `DE_URMARIT.md` | semnale deschise, cu declanșatori |
| `ADR-07x` | deciziile individuale |
| `EUROPEAN_COMPETITION_FORM_FILTER_DEFECT.md` | §4.1, cu toate cifrele |

---

## 8. REGULI CARE NU SE ÎNCALCĂ

Repetate aici fiindcă se aplică la fiecare intrare de mai sus:

1. Nicio scriere pe Supabase fără SQL arătat + confirmare explicită.
2. Niciun push pe `main` fără aprobare **per push**.
3. `pytest tests/` verde pe `main` **înainte** de push.
4. Orice tabelă nouă: `GRANT` către `service_role` (obligatoriu de la 30 oct).
5. Descoperire nouă de contract → **Discovery Rule**: oprește-te și prezintă.
