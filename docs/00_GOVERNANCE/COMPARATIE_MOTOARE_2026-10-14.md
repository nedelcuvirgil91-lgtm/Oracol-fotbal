# Comparație între motoare — 2026-10-14

Măsurătoare read-only, pe **998 de meciuri terminate** unde Oracle, ML și Blend au toate trei o predicție. Comparație **împerecheată** (același set pentru toți), nu medii pe ferestre diferite.

**Baseline-ul Oracle e rândul `control` din `shadow_predictions`**, niciodată `match_history.prob_*_pred` (înghețat prin `COALESCE` — ADR-072). Rândurile-santinelă `2099-01-01` excluse.

---

## 1. Clasamentul

| Loc | Model | n | Acuratețe | Brier | Log-loss |
|---|---|---:|---:|---:|---:|
| — | *Piața (cote de închidere)* | 987 | *0,5228* | *0,5852* | *0,9834* |
| **1** | **Blend** | 998 | **0,5070** | **0,5991** | **1,0043** |
| 2 | Oracle | 998 | 0,4940 | 0,6057 | 1,0154 |
| 3 | ML (XGBoost) | 998 | 0,4699 | 0,6099 | 1,0184 |
| — | *Mereu gazda* | 998 | *0,4429* | *1,1142* | *19,24* |

Ordinea e **identică pe toate trei metricile** — nu e un artefact al alegerii metricii.

## 2. Semnificație statistică — fără ea, tabelul de mai sus e doar o ordine

| Comparație | Acuratețe (McNemar) | Brier | Log-loss |
|---|---|---|---|
| **Blend vs Oracle** | 42 / 29, **z = 1,54 → NEsemnificativ** | −0,0065, **t = −2,82 ✅** | −0,0112, **t = −3,08 ✅** |
| Blend vs ML | 82 / 45, **z = 3,28 ✅ semnificativ** | — | — |
| Oracle vs ML | 108 / 84, z = 1,73 → NEsemnificativ | — | — |
| Piața vs Blend | 89 / 72, **z = 1,34 → NEsemnificativ** | — | — |
| Piața vs Oracle | 124 / 95, **z = 1,96 → exact la prag** | — | — |

### Ce înseamnă, exact

**Blend bate Oracle pe 2 metrici din 3, semnificativ — dar NU pe acuratețe.** Conform North Star #2 (dovadă simultană pe metrici multiple), asta **nu** e suficient pentru promovare. Nu e o formalitate: diferența de acuratețe (+1,3pp) poate fi zgomot, în timp ce îmbunătățirea de calibrare (Brier, log-loss) e reală.

**Blend bate ML clar și semnificativ** (z = 3,28). Combinarea Oracle+ML e mai bună decât ML singur — nu e un compromis, e un câștig.

**ML singur e cel mai slab dintre cele trei**, și nu semnificativ sub Oracle (z = 1,73).

**Blend închide decalajul față de piață.** Oracle e **exact la pragul** de semnificație față de case (z = 1,96); Blend nu mai e (z = 1,34). Adică Blend e statistic indistinct de casele de pariuri pe acest set.

---

## 3. `flashscore_team_dna` NU e un motor — e Oracle

Verificat direct: pe **1162 de fixture-uri comune**, probabilitățile lui diferă de rândul `control` (Oracle servit) cu **maximum 0,000050**, media 0,000024 — pur rotunjire la a 5-a zecimală.

Cauza, în cod: `oracle_engine.py:2008` loghează `prob_home=ph, prob_draw=pd, prob_away=pa` — **predicția finală a Oracle**. Experimentul capturează Team DNA ca `feature_metadata`, nu propune o predicție alternativă. Comentariul din cod o spune explicit.

### Consecința, care contează pentru D-7

Cei **`+2,90pp`** din `experiment_registry` pentru `flashscore_team_dna/v1` au fost calculați contra baseline-ului **înghețat**. Deci măsurau **Oracle-proaspăt vs. Oracle-înghețat** — **100% artefactul ADR-072**, zero efect de feature.

**Nu există nicio tensiune cu ablația negativă din 13 octombrie.** Cele două cifre nu măsurau același lucru: ablația a măsurat feature-ul (negativ), registrul a măsurat vechimea baseline-ului (pozitiv). Concluzia D-7 — feature NEPROMOVAT — rămâne, iar acum are un motiv mai curat: cifra care părea s-o contrazică nu era despre feature.

Asta explică și de ce `flashscore_team_dna` e singurul experiment cu **0 rânduri `control`**: nu are nevoie de baseline, fiindcă *este* baseline-ul.

---

## 4. Rezerve, scrise explicit

- **„Blend" și „ML" cumulează versiuni active în perioade diferite** — `blend_v1` are 3 (`8ac89c70`, `4e17c737`, `174e7e17`), `xgboost_v1` are 2. E comparația familiei pe un an de date, nu a unui model unic. Per versiune, dispersia e mare (vezi §5).
- **NU e poarta formală de promovare.** Aceea evaluează un singur Challenger, pe fereastra lui, cu prag de n și test propriu. Tabelul de aici e o privire de ansamblu, nu un verdict de promovare.
- **Oracle e ce se servește.** Blend e afișat alături, nu servit — `pred.prob_home_win` rămâne Poisson-ul Oracle. Deci „Blend e mai bun" descrie un potențial, nu ce primește utilizatorul azi.
- Piața are 987 din 998 (11 meciuri fără cote de închidere).

## 5. Per versiune — de unde vine dispersia

| Model | versiune | n | Δ acuratețe vs Oracle | Δ Brier | Δ log-loss |
|---|---|---:|---:|---:|---:|
| blend_v1 | `8ac89c70` | 383 | **+3,66pp** | −0,0118 | −0,0196 |
| blend_v1 | `174e7e17` | 151 | +1,32pp | −0,0018 | −0,0032 |
| blend_v1 | `4e17c737` | 596 | −0,34pp | −0,0046 | −0,0078 |
| xgboost_v1 | `e638c1dc` | 677 | −1,03pp | +0,0012 | −0,0009 |
| xgboost_v1 | `6e7265c5` | 468 | −1,71pp | −0,0047 | −0,0096 |

**Niciun Challenger nu bate Oracle pe toate trei simultan, în propria lui fereastră.** `8ac89c70` e cel mai aproape — și e campionul `blend_v1` promovat pe 23 august.

Observație: **toate** versiunile de Blend au Brier și log-loss mai bune decât Oracle, inclusiv cea cu acuratețe mai slabă. Blend câștigă consecvent la **calibrare**, inconsecvent la **a nimeri rezultatul**.

---

## 6. Concluzia în trei rânduri

1. **Blend > Oracle > ML**, pe toate trei metricile, pe același set de 998 de meciuri.
2. Avantajul Blend e **real la calibrare** (Brier, log-loss — semnificativ) și **nedovedit la acuratețe** (z = 1,54). Deci nu trece poarta North Star #2.
3. `flashscore_team_dna` nu e un al patrulea motor; e Oracle, iar cei +2,90pp ai lui erau artefactul ADR-072.
