# DATA_EXPANSION_PROGRAM_ROADMAP_2026-07-13.md — Football Oracle

**Status**: Master roadmap — zero implementare. Program permanent, succesor al Odds Infrastructure. Principiu: „Fiecare meci trebuie să devină din ce în ce mai bogat în informații." Fiecare sprint trebuie să răspundă: *am făcut baza mai bogată și modelul mai inteligent decât era înainte?* (Regula #21).

**Precondiție de intrare**: Odds Infrastructure v1.0 CLOSED (toate cele 4 etape, inclusiv vizibilitate în Streamlit — Regula #20).

---

## Metodologia de scorare

Fiecare item: **Valoare ML | Cost implementare | Disponibilitate sursă | Impact utilizator**, scală Mic/Mediu/Mare, justificată pe dovezi deja stabilite în proiect — nu presupuneri. Unde sursa nu e verificată în acest mediu, se spune explicit „neconfirmat", nu se estimează.

---

## Sprint 1 — Statistici de bază, Faza A (cele 6 ligi deja urmărite), sursă football-data.co.uk

**Câmpuri**: `HS/AS/HST/AST` (șuturi/pe poartă), `HC/AC` (cornere), `HY/AY/HR/AR` (cartonașe), `HF/AF` (faulturi), `Referee`. **Notă de verificare**: `Offside`/`Attendance` sunt menționate în `notes.txt` dar **absente din header-ul real verificat** (EPL 2025-26) — nu se includ până nu se reconfirmă pe sezonul țintă exact.

| Factor | Nivel | Justificare |
|---|---|---|
| Valoare ML | Mediu | Nedemonstrat — `PREDICTOR_ROADMAP_V4.md` a demonstrat doar că proxy-urile sintetice actuale sunt false, nu că datele reale ajută. Necesită ablație înainte de `FEATURE_COLUMNS`. |
| Cost | Mic-Mediu | Reutilizează exact pattern-ul de matching + writer construit la Odds Infrastructure Etapa 1 — al doilea caz de utilizare a aceluiași mecanism, nu unul nou. |
| Disponibilitate sursă | Mare | Verificată direct (audit + header real fetch-uit), nu presupusă. |
| Impact utilizator | Mic pe termen scurt, Mediu pe termen lung | Date brute, invizibile fără UI dedicat — alimentează Sprint 4 (Knowledge Features), care e vizibil. |

**Recomandare**: adaugă `source_hash` (analiza de mai sus) la migrarea acestui sprint — primul import structurat de date noi de la Odds, cost marginal minim.

## Sprint 2 — Feature-uri derivate, fără sursă externă nouă (poate rula în paralel cu Sprint 1)

**Ce**: formă ultimele 5/10 meciuri (parțial există — `FormTracker`, `FORM_WINDOW` deja optimizat prin experiment pe 760 meciuri EPL reale), statistici acasă/deplasare (`StandingsTracker` parțial există), rafinare eficiență ofensivă/defensivă.

| Factor | Nivel | Justificare |
|---|---|---|
| Valoare ML | Mediu-Mare | Se bazează pe cod deja parțial testat, nu pe ipoteză nouă. |
| Cost | Mic | Zero sursă externă — feature engineering pur peste `match_history` deja existent. |
| Disponibilitate sursă | Mare (n/a) | Internă, nu depinde de niciun provider extern. |
| Impact utilizator | Mic direct | Pregătește Sprint 4, nu produce el însuși valoare vizibilă imediată. |

## Sprint 3 — Expansiune Faza B (9 ligi noi), aceeași sursă

**Ligi**: Championship, Eredivisie, Primeira Liga, Belgian Pro League, Scottish Premiership, Greek Super League, Turkish Super Lig, Austria, Elveția.

**Descoperire nouă din acest roadmap** (verificată, nu presupusă): **toate cele 9** sunt deja confirmate acoperite de football-data.co.uk — 7 ca „main leagues" (E1, N1, P1, B1, SC0-3, T1, G1), 2 ca „extra leagues" (Austria, Elveția) — aceeași sursă deja integrată, zero cost de vetting nou.

| Factor | Nivel | Justificare |
|---|---|---|
| Valoare ML | **Risc, nu doar oportunitate** | `PERFORMANCE_LIMITER_AUDIT_2026-07-13.md` a demonstrat deja că volumul din ligi neurmărite **diluează** acuratețea (48,22% pe ligi urmărite vs. 45,86% pe neurmărite). Adăugarea oarbă ar repeta exact greșeala deja diagnosticată. |
| Cost | Mediu | 9× volumul de matching, dar pattern deja construit de două ori (Odds + Sprint 1). |
| Disponibilitate sursă | Mare | Verificată explicit mai sus. |
| Impact utilizator | Mediu | Extinde acoperirea vizibilă a aplicației. |

**Condiție obligatorie de intrare, nu opțională**: fiecare ligă nouă intră explicit în `BOOTSTRAP_LEAGUES` cu weighting propriu, **niciodată** aruncată în pool-ul nediferențiat existent — exact lecția din auditul de performanță.

## Sprint 4 — Knowledge Features generate de Oracle (nu importate)

League Strength Index, Home Advantage Index, Referee Strictness Index, Team Momentum, Team Volatility, League Volatility, Market Confidence, Closing Line Efficiency, Injury Impact, Tactical Stability, Prediction Confidence.

**Dependențe stricte, nu opționale**: Referee Strictness Index are nevoie de `Referee`+cartonașe (Sprint 1); Closing Line Efficiency are nevoie de `odds_history` complet (Odds Infrastructure); League Strength/Volatility Index au nevoie de multi-league (Sprint 3). **Nu poate începe înaintea lor.**

| Factor | Nivel | Justificare |
|---|---|---|
| Valoare ML | Mare (potențial) | Dar fiecare feature intră în model **doar prin ablație** — regulă deja stabilită, niciuna implicit. |
| Cost | Mediu-Mare | Logică de calcul nouă pentru fiecare index, nu doar import de date. |
| Disponibilitate sursă | N/A | Derivate din date deja capturate în sprint-urile anterioare. |
| Impact utilizator | Mare | Exact genul de „insight" pe care Sugestia Zilei/Value Bets îl pot expune vizibil — satisface direct Regula #20. |

---

## Amânat / neconfirmat — NU intră în roadmap-ul executabil încă

Enumerat explicit, nu ascuns, per disciplina „necunoscut rămâne necunoscut":

- **xG / xGA** — sursă candidată (Understat) **neauditată în acest mediu**. Necesită un audit de acces dedicat (similar celui făcut pentru football-data.co.uk) înainte de orice estimare fermă de cost sau disponibilitate.
- **Posesie, parade portar** — confirmat **absente** din football-data.co.uk (verificat direct pe header-ul real, nu pe `notes.txt`). Ar necesita API-Football statistics, a cărei fiabilitate rămâne nedemonstrată — Discovery Probe-ul dedicat s-a oprit explicit „până avem rezultate reale".
- **Stadion, spectatori** — absente din football-data.co.uk (Attendance menționat teoretic în `notes.txt`, dar absent din header-ul real verificat).
- **PPDA, presing, dueluri, recuperări, Field Tilt** și restul statisticilor avansate — necesită surse de nivel Opta/StatsBomb, tipic plătite. Nicio sursă gratuită confirmată. Nu intră în roadmap fără o sursă identificată și auditată.
- **Faza C** (Champions League, Europa League, Conference League) — confirmat **neacoperite** de football-data.co.uk (verificat explicit, absență pe 3 pagini distincte ale sursei). Nicio sursă alternativă identificată.
- **Faza D** (World Cup, EURO, Nations League, Copa America) — confirmat neacoperite de football-data.co.uk. Densitate de valoare mică per efort de integrare (turnee rare, la 2-4 ani).

---

## Ordinea recomandată

**Sprint 1 → Sprint 3 → Sprint 4, cu Sprint 2 rulabil în paralel cu Sprint 1** (independent, fără dependență de sursă externă). Fiecare sprint se închide individual (Regula #17 — read-only după închidere), cu propriul Snapshot, înainte de a trece la următorul. Niciun sprint din secțiunea „amânat" nu se deschide fără un audit de sursă dedicat, în stilul celui deja făcut pentru football-data.co.uk.
