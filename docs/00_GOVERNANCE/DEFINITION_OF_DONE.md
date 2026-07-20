# DEFINITION OF DONE — Football Oracle

> **Definition of Done certifică realitatea proiectului, nu intențiile
> echipei. O bifă se marchează numai când condiția este îndeplinită în mod
> obiectiv. Excepțiile rămân nebifate și sunt documentate explicit până la
> rezolvare.**

**O fază nu este considerată închisă până când toate cele trei niveluri
(Engineering, Product și Governance) sunt complet bifate.**

O fază nu avansează deoarece dezvoltarea s-a oprit; avansează doar după ce
verificarea este încheiată și rezultatul ei este cunoscut.

## Cele trei niveluri

### Nivel 1 — Engineering DoD (Claude)

Verificabil automat, executat proaspăt la închidere (nu din memorie):

```
□ pytest tests/ verde — zero eșecuri NOI față de starea documentată a suitei
□ sync/run_daily.py --dry-run trece fără erori
□ security-review: fără secrete hardcodate noi în diff
□ architecture-review: orice dependență nouă între module are ADR
□ documentația actualizată (CLAUDE.md / docs relevante)
□ migrațiile Supabase (dacă există) idempotente, cu RLS
□ fără TODO-uri critice rămase în codul fazei
□ verificare live end-to-end a schimbării (nu doar teste unitare)
```

### Nivel 2 — Product DoD (utilizatorul)

Verificarea aplicației ca produs, fără automatizare:

```
□ Build-ul pornește fără erori
□ Dashboard-ul se încarcă
□ Meciurile sunt afișate corect
□ Cotele sunt afișate (unde providerul acoperă liga)
□ Predicțiile sunt generate
□ Nu există regresii vizibile pe celelalte ligi
□ „Reîncarcă meciuri" funcționează
□ Utilizatorul confirmă funcționalitatea
```

Ultima căsuță aparține întotdeauna utilizatorului — nimic nu se închide
fără confirmarea lui explicită.

### Nivel 3 — Governance DoD

Întrebarea: *poate proiectul să continue fără datorii de proces?*

```
□ Baseline creat (snapshot înghețat al fazei)
□ Frozen Registry actualizat
□ ADR-uri închise (nimic „în lucru" rămas nedecis)
□ Branch-uri curățate
□ Monitorizările oprite
□ Faza precedentă declarată oficial închisă
```

## Protocolul de raportare a verificării

Verificarea Product are exact trei rezultate valide, fiecare cu acțiune
clară și exclusivă — absența unei decizii este și ea o decizie validă:

- ✅ **Verificarea este încheiată. Totul funcționează.** → faza se închide.
- ⚠️ **Verificarea este încheiată. Am găsit problema: …** → faza rămâne
  deschisă; se rezolvă problema.
- ❓ **Verificarea nu este încă încheiată.** → proiectul rămâne deliberat
  în așteptare; nu se face nimic.

Niciuna dintre cele trei stări nu este „greșită". Nu există presiunea unui
„verdict pozitiv" — există doar raportarea rezultatului.

## Principiul „Nu trișăm DoD-ul"

Dacă o bifă nu este îndeplinită, nu se bifează. Nu există „aproape bifat".
O căsuță rămâne goală, cu excepția documentată explicit sub checklist,
până la rezolvare. Un document cu toate căsuțele verzi prin rotunjire
optimistă este mai periculos decât lipsa documentului.

## Fluxul de închidere

    Engineering → Product → Governance → Baseline → Next Phase

Fiecare fază închisă produce o **instanță completată** a acestui checklist,
inclusă în baseline-ul fazei (bifele reale, cu datele verificărilor) —
dovada permanentă a închiderii, nu doar declarația ei.

## Schimbarea acestui document

Acest document descrie procesul, nu o fază — rămâne viu, dar se modifică
DOAR printr-un ADR motivat de o problemă observată în utilizare, niciodată
din speculație sau „pare mai simplu". (Prima instanță reală: închiderea
Fazei 1, 2026-07-19 — procesul a fost validat pe un caz real înainte de a
fi adoptat ca regulă.)
