# REST_DAYS_VALIDATION.md — Football Oracle

## Scop

Testez explicit ipoteza "Rest Days aduce semnal independent" încercând s-o resping, cu date reale (53.409 meciuri), nu presupuneri. Fără cod de producție — doar analiză.

---

## 1. E informația deja absorbită de ELO?

**Testat direct**: corelație `home_rest_days` ↔ `home_elo` pe 51.024 meciuri (unde rest_days era calculabil, cu filtrare la ≤30 zile — peste asta e pauză de sezon, nu odihnă).

```
Corelație rest_days ↔ ELO:        -0.0559   (neglijabilă)
```

**Răspuns**: **Nu**, nu e absorbită de ELO. Corelația e practic zero — ELO nu "știe" nimic despre cât de recent a jucat o echipă.

## 2. E corelat puternic cu Form Score?

```
Corelație rest_days ↔ form_score:  -0.1015   (slabă)
```

**Răspuns**: Corelație slabă, direcție logică (program încărcat → formă ușor mai slabă), dar departe de coliniaritate reală (ar necesita >0.7-0.8 pentru o problemă practică).

## 3. Multicoliniaritate?

Cu ambele corelații sub 0.11, **nu există risc practic de multicoliniaritate** cu feature-urile deja folosite.

## 4. Efect diferit pe ligi?

**Nu am testat exhaustiv per ligă** — gol real, semnalat explicit, nu ascuns. Cu doar 9.694 meciuri în subsetul "odihnă scurtă" din tot setul, o spargere pe 10+ ligi ar lăsa unele cu prea puține exemple pentru o concluzie fiabilă. Dacă there's un motiv real să credem că anumite ligi (echipe cu program european + domestic congestionat) ar avea efect mai mare, ar merita un test dedicat, separat — nu presupun nimic aici.

## 5. Literatură academică — efect asupra REZULTATULUI, nu doar asupra performanței fizice

Verificat acum (nu din memorie): majoritatea studiilor de fixture congestion măsoară **performanță fizică** (distanță parcursă, sprinturi, risc de accidentare) — <cite index="4-1">un studiu observă un declin de 7-14% în distanța de intensitate mare la al doilea meci dintr-o serie de trei, comparat cu primul (jucat cu 3 zile înainte) și al treilea (la 4 zile distanță)</cite> — dar efectul asupra **rezultatului final** (victorie/egal/înfrângere) e mult mai puțin consistent documentat.

Un studiu specific pe rezultat chiar există: <cite index="5-1">un studiu din 2012 (antrenorul Raymond Verheijen) a arătat că echipele cu doar 2 zile de pregătire aveau șanse cu 40% mai mici să câștige următorul meci, față de echipele cu 3 zile</cite> — un efect notabil, dacă real. Însă alte studii <cite index="4-1">nu au găsit nicio diferență între meciuri jucate la interval scurt la jucători spanioli de elită</cite> (deși acel studiu specific a fost evaluat ca fiind de calitate scăzută în review-ul sistematic).

**Observație utilă**: pragul deja folosit în `rest_days_modifier()` (4 zile) coincide cu definiția academică standard de "fixture congestion" — <cite index="7-1">"minimum două meciuri succesive, cu o perioadă de recuperare sub 96 de ore"</cite> (exact 4 zile). Cine a scris funcția a ales un prag fundamentat, nu arbitrar — asta nu dovedește că feature-ul ajută modelul de predicție, dar arată că designul e corect calibrat.

**Concluzie literatură**: efectul e real fiziologic, dar **mixt și inconsistent** la nivel de rezultat direct — exact genul de semnal slab care ar putea să nu supraviețuiască zgomotului unui model agregat.

## 6. Testul decisiv — ablație reală, pe date reale, walk-forward

Am adăugat `rest_days` (atât ca valoare continuă, cât și în forma **exactă** deja construită — indicator binar sub pragul de 4 zile) peste `ELO + form_score` (cele mai importante feature-uri deja confirmate), pe **același subset** de 50.402 meciuri, comparație corectă:

```
ELO + form (baseline, fără rest_days):              acc=0.4667  logloss=1.0458  brier=0.6286
ELO + form + rest_days (valoare continuă):           acc=0.4658  logloss=1.0462  brier=0.6290
ELO + form + prag-binar odihnă scurtă (<4 zile):     acc=0.4660  logloss=1.0459  brier=0.6287
```

**Rezultat măsurat, nu estimat**: adăugarea rest_days **nu îmbunătățește nimic** — de fapt, toate cele trei metrici sunt marginal mai slabe (probabil zgomot de fold, dar cert nu o îmbunătățire).

## Cum am valida, dacă totuși s-ar implementa

Nu propun implementare acum, dar dacă s-ar relua: (a) test dedicat per ligă, cu prag de eșantion minim per ligă; (b) test de interacțiune (rest_days × calitatea adversarului, nu doar efect aditiv); (c) shadow testing în timp real, pe meciuri viitoare, nu doar backtest istoric.

---

## Verdict

### **NU**

Nu pentru că feature-ul "n-are sens" teoretic — are, și literatura confirmă un mecanism fiziologic real. Dar testul direct, pe 50.000+ meciuri reale, cu exact designul deja construit în cod, arată **zero câștig măsurabil, posibil chiar o mică regresie**. Corelațiile slabe cu ELO/form confirmă că informația *există* independent — dar a exista independent nu înseamnă automat că ajută modelul agregat să prezică mai bine rezultatul.

Nu implementez. Recomand realocarea efortului către următorul candidat din roadmap (#3 sau #4 — injuries/schimbare antrenor, ambele deja colectate, doar neactivate), sau spre alte ipoteze de feature engineering, nu spre rafinarea acestuia (interacțiuni, per-ligă) fără un motiv nou, concret, de-a încerca din nou.
