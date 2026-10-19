# ADR-077 — Semnalul care decide dacă providerii de rezervă mai sunt întrebați

**Status**: PROPUNERE (2026-10-19) — cere aprobare explicită înainte de implementare
**Derivat din**: ADR-076 §2.3 și §6 D-A (descoperire în timpul investigației, Discovery Rule)
**Atinge**: contractul de rutare din ADR-045 (Single Owner) și criteriul din ADR-041
**Nu atinge**: nicio formulă, niciun motor de predicție, nicio coloană nouă

---

## 1. Context — calea Soccer Football Info e moartă, și nu de ieri

`sync/sync_match_statistics.py:119` e **singurul** apelant (verificat prin
grep) al lui `get_finished_matches_missing_stats()`, și o cere cu
`require_referee=True`. Criteriul acelui mod e `referee IS NULL`.

Măsurat read-only pe producție, 2026-10-19:

| Fereastră | `referee IS NULL` (criteriul de azi) | `home_shots IS NULL` | `home_possession IS NULL` | `home_xg_actual IS NULL` | total terminate |
|---|---:|---:|---:|---:|---:|
| 7 zile | **0** | 95 | 95 | 95 | 185 |
| 14 zile | **0** | 229 | 229 | 229 | 322 |
| 60 zile | **0** | 653 | 653 | 675 | 1208 |

**Zero pe fiecare fereastră.** Soccer Football Info nu primește niciun meci de
procesat, niciodată. Nu e o degradare recentă: `referee` e populat pe **100%**
din meciurile terminate (679/679 august, 534/534 septembrie, 232/232
octombrie), deci criteriul întoarce zero de când Flashscore a devenit al doilea
scriitor al câmpului.

### 1.1 De ce proxy-ul a fost corect, și când a încetat să fie

Docstring-ul funcției o spune explicit, și era adevărat când a fost scris:

> `require_referee` [ADAUGAT Sprint 1 Faza 1, ADR-041] — … `referee` e populat
> STRICT de acest adaptor, deci e semnalul corect de „lipsesc datele bogate"

La ADR-041, Soccer Football Info era singurul scriitor al lui `referee`, deci
`referee IS NULL` ⇔ „SFI n-a atins încă meciul" ⇔ „lipsesc datele bogate".
Echivalența era reală.

**ADR-044/045 au adus Flashscore ca al doilea scriitor al aceluiași câmp**
(`providers/flashscore/normalizer.py:533`, `"referee": info.get("Referee:")`),
iar nimeni — eu inclusiv, până la investigația ADR-076 — nu a revizitat
proxy-ul. De atunci, prima parte a echivalenței s-a rupt: `referee` scris
înseamnă „un provider a atins meciul", nu „datele bogate există".

**Un ADR a invalidat precondiția unui alt ADR, tăcut.** Asta e clasa de defect,
nu cifra. Nici ADR-041, nici ADR-044/045 nu greșesc în sine; ce lipsea e o
verificare care să prindă momentul în care un câmp-martor capătă al doilea
scriitor.

### 1.2 Cum s-a văzut

Deloc, 39 de zile. În septembrie-octombrie, extragerea statisticilor
Flashscore a fost moartă (ADR-076), dar extragerea arbitrului a continuat
impecabil — deci fiecare meci primea `referee`, dispărea din lista
providerilor de rezervă, și rămânea fără statistici. Plasa de siguranță
exista, era cablată, și nu putea să se declanșeze niciodată.

---

## 2. Decizie propusă

### Varianta recomandată: (ii) criteriul citește coloanele ȚINTĂ

`get_finished_matches_missing_stats()` primește un mod nou în care „lipsesc
datele" se citește din coloanele pe care sincronizarea chiar vrea să le
completeze — `home_shots IS NULL` (sau o combinație explicită) — în loc de un
câmp-martor.

**De ce (ii) și nu mutarea proxy-ului pe alt câmp**: un martor poate oricând să
capete al doilea scriitor, exact ce s-a întâmplat aici. O coloană-țintă nu
poate minți despre propria absență. Varianta (i) — „găsim un câmp pe care doar
SFI îl scrie" — ar reface același aranjament fragil și ar cere, la fiecare ADR
viitor care adaugă un scriitor, ca cineva să-și amintească de acest ADR.

Măsurat ca `home_shots` și `home_possession` dau cifre **identice** pe toate
cele trei ferestre (95/229/653), deci alegerea între ele nu schimbă nimic azi;
`home_xg_actual` diferă (675 vs 653 la 60 de zile) — cele 22 de meciuri în plus
sunt cazuri cu șuturi dar fără xG, tipic calificări de cupă unde Flashscore nu
publică xG. **Recomand `home_shots`**: e cel mai larg câmp comun celor doi
provideri, și nu cere SFI pentru meciuri la care golul e structural la sursă.

### 2.1 Consecința de volum, care face din asta o decizie și nu un fix

Azi SFI procesează **0** meciuri. După schimbare ar primi **~95 pe săptămână**.

Asta nu e un detaliu de implementare:

- e consum real de cotă la un provider extern, nemăsurat în regimul nou;
- e timp real adăugat într-un pas de pipeline care azi se termină instant
  (lista goală);
- **și o parte din cele 95 nu sunt recuperabile de nimeni** — meciuri din
  competiții pe care SFI nu le acoperă. Câte, **nu se știe**: nu există
  măsurătoare, pentru că nu s-a mai făcut niciun apel. Nu o estimez.

**Recomandare de etapizare**: prima rulare după schimbare cu un `limit` mic
(ex. 20) și raport, ca rata reală de succes a SFI să fie **măsurată** înainte de
a-i da 95 de meciuri pe săptămână. „Verificat, nu presupus" se aplică și
beneficiului, nu doar riscului.

### 2.2 Ce rămâne neatins, deliberat

- **`flashscore_data_completeness.has_stats` NU se schimbă.** Rămâne ce e
  documentat să fie: prezența paginii descărcate. Filtrul Single Owner care îl
  citește (`get_match_ids_with_complete_flashscore_stats`) devine însă
  redundant sub criteriul (ii): un meci care are `home_shots` scris nu mai
  intră în listă, indiferent de flag. **Propun să rămână pe loc**, ca a doua
  plasă, nu să fie șters în același pas — ștergerea unui filtru și schimbarea
  criteriului în același commit ar face imposibil de atribuit orice efect.
- Plafonul PostgREST: `get_match_ids_with_complete_flashscore_stats` folosește
  un singur `.in_(…)`, iar plafonul de 1000 a fost deja reparat de patru ori în
  proiect. Sub criteriul nou lista de intrare crește de la 0 la ~95-653, deci
  **intră în zona de risc**. De chunk-uit la 500 în același pas, cu test.

---

## 3. Verificare cerută

1. Test că modul nou citește coloana-țintă, nu martorul; și că modul vechi
   rămâne neschimbat pentru orice alt apelant (azi nu există, dar contractul e
   public).
2. Test de chunk-uire peste 500 de id-uri (clasa deja reparată de patru ori).
3. Mutații: criteriul inversat, chunk-ul scos, filtrul Single Owner lăsat să
   primească o listă mare.
4. **Pe date reale**: o rulare cu `limit=20`, cu raport pe rata de succes SFI
   per competiție. Starea „înainte": 0 meciuri procesate, de la cel puțin
   2026-08-01 (prima dată măsurabilă).

---

## 4. Consecințe

**Pozitive**: plasa de siguranță pentru statistici redevine funcțională după ce
a fost inertă de la activarea Flashscore FDL; clasa „câmp-martor cu al doilea
scriitor" dispare în locul ăsta, în loc să fie mutată.

**Negative, de acceptat conștient**: consum nou la un provider extern, cu rată
de succes necunoscută; și un pas de pipeline care azi costă zero va costa ceva.

**Ce NU rezolvă**: restanța istorică (ADR-076 D-B, decizie separată). Criteriul
nou privește fereastra de sincronizare zilnică, nu recuperarea retroactivă.

**Gol rămas deschis, mai larg decât acest ADR**: nimic nu detectează, azi, când
un ADR nou adaugă un al doilea scriitor pe un câmp folosit de altul ca martor.
`tests/test_canonical_feature_ownership.py` (ADR-036) impune owner unic pentru
`FEATURE_COLUMNS`, dar `referee` nu e în acel set. O gardă echivalentă pentru
câmpurile-martor ar fi reparația de clasă — **nu e în scopul acestui ADR**, dar
merită să nu rămână nescris.
