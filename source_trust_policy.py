"""
================================================================================
FOOTBALL ORACLE — Source Trust Policy
================================================================================
Definirea initiala (Faza 1, ADR-025) a Source Trust Policy — politica
operationala, evolutiva, SEPARATA de contractul de identitate stabilit de
ADR-025. Poate fi schimbata in timp (ex. la adaugarea unui provider nou) fara
a redeschide ADR-025 sau ID-025-01.

Consumata exclusiv de algoritmul de selectie/merge (ID-025-01, Pasul 1 si
Pasul 3) prin interfata `SourceTrustProvider.get_rank()`, si doar pentru
conflicte reale intre surse (ambele au o valoare non-null diferita pentru
acelasi camp) — nu decide identitatea meciului, doar care valoare castiga
la un conflict de date.

Ordinea de mai jos reflecta completitudinea deja demonstrata empiric
(ADR-024): 100% din randurile football-data.org au shots/corners populate,
fata de 0% din import-ul istoric Kaggle.

Rezolvarea sursei unui rand (`resolve_source()`) e o componenta separata,
explicit inlocuibila (ID-025-01) — NU face parte din acest document, ramane
responsabilitatea motorului de reconciliere (ID-025-02).

--------------------------------------------------------------------------------
[EXTINS — F4.3, 2026-08-21] Trei surse noi: flashscore, tsdb, openfootball.
--------------------------------------------------------------------------------
De ce a fost nevoie: F3 (ADR-058) a extins vocabularul `ALIAS_TO_CANONICAL` cu
130 de rezolutii. `match_key()` — aceeasi functie folosita de descoperirea
ID-025-02 — produce acum 404 grupuri duplicate care in iulie erau invizibile.
Raportul Faza 2 ADR-025 isi notase singur conditia de expirare: normalizarea
"nu produce niciun grup suplimentar fata de gruparea bruta, PENTRU DATELE
CURENTE" (ADR025_PHASE2_DRY_RUN_REPORT_2026-07-16.md:36). Vocabularul s-a
schimbat, deci si datele. Toate cele 3 surse noi lipseau din acest registru,
iar regula "sursa necunoscuta exclude tot grupul" (Regula #8) ar fi exclus
403/403 grupuri.

Extinderea e sanctionata explicit de doua ori, nu presupusa: acest document
("poate fi schimbata in timp la adaugarea unui provider nou fara a redeschide
ADR-025 sau ID-025-01", mai sus) si ADR-025 §Consecinte ("Source Trust Policy
si regula exacta de selectie a randului canonic raman externalizate din acest
ADR — pot evolua fara un ADR nou, atat timp cat invariantul «exact un rand
canonic per meci» nu e incalcat").

Metoda de calibrare: identica celei din ADR-024 — completitudine MASURATA, nu
opinie. Masuratoare pe meciuri TERMINATE (`actual_result IS NOT NULL`; incluzand
fixture-urile viitoare ar dilua artificial sursele care descopera meciuri in
avans, flashscore/tsdb), Supabase `Prediction`, 2026-08-21:

  sursa              n_term   shots  corners  possess   xG    season  medie_non-NULL
  tsdb                   13   100%     100%     100%   100%      0%       69,1
  flashscore            444   99,8%    99,8%    99,8%  71,2%     0%       59,0
  football_data       7.534   48,4%    48,4%     1,9%   1,9%   100%       38,4
  openfootball        2.119      0%       0%       0%     0%   100%       25,0
  kaggle_historical  44.152      0%       0%       0%     0%    7,7%       24,1
  (odds_api n=2 si espn n=1 — sub pragul oricarei recalibrari, rang neschimbat)

Rationamentul per sursa noua:
  * flashscore -> rang 1. Foundation Data Layer (ADR-044): singura sursa cu xG
    real, posesie, evenimente si statistici de jucatori; SINGURA cu copii FK in
    cele 5 tabele derivate (`match_events`, `match_statistics_extended`,
    `player_match_stats`, `flashscore_match_context`,
    `flashscore_data_completeness`). Domina football_data pe orice dimensiune de
    detaliu al meciului (59,0 vs 38,4 coloane medii). Corpusul e mai mic azi
    (444 vs 7.534) fiindca sursa e recenta — dar rangul de incredere masoara
    completitudinea PER RAND, nu volumul acumulat; volumul creste monoton, iar
    directia e confirmata explicit de proprietarul produsului ca sursa primara
    de viitor. Argument contrar consemnat onest: 0% `season`.
  * tsdb -> rang 3, sub football_data. Profilul per rand e cel mai bun din tot
    corpusul (69,1), DAR pe n=13 meciuri terminate. Un esantion de 13 nu poate
    sustine aceeasi calibrare ca miile de randuri din ADR-024 — plasarea peste
    football_data ar fi exact tipul de inferenta din esantion mic pe care
    proiectul o respinge prin regula ("Verificat, nu presupus"). Peste espn/
    odds_api fiindca acolo masuratoarea e clara (69,1 vs 35,0/52,5) si fiindca
    tsdb e sursa de rezultate reala si activa pentru Romania SuperLiga, unde
    football-data.org nu acopera liga si Odds API nu are piata per-meci.
  * openfootball -> rang 6, imediat peste kaggle_historical. Practic identic cu
    kaggle pe continut (0% pe toate statisticile), 25,0 vs 24,1 coloane medii —
    diferenta e exclusiv `season` (100% vs 7,7%). Peste kaggle, dar sub orice
    sursa care aduce statistici reale.

Ordinea RELATIVA a celor 4 surse preexistente ramane NESCHIMBATA
(football_data < espn < odds_api < kaggle_historical) — calibrarea ADR-024 nu e
redeschisa, doar se insereaza surse noi intre valorile ei. Verificat mecanic:
nicio decizie istorica nu se inverseaza (cele 3.501 grupuri fd>kaggle si cele 3
grupuri World Cup espn>odds_api dau acelasi castigator sub rangurile noi).
Gardat de `tests/test_source_trust_policy.py::
test_preexisting_relative_order_is_preserved`.

Verificare mecanica a efectului pe cele 403 grupuri F4 (read-only, inainte de
scrierea acestui cod): sub rangurile de mai jos, selectia "rang minim" a
ID-025-01 produce ACELASI castigator ca o ipotetica politica
"completitudine -> FK -> rang -> id" pe 403 din 403 grupuri, zero divergente,
zero randuri cu sursa nerezolvata. Nu exista deci niciun motiv pentru o a doua
politica de selectie concurenta — ID-025-01 ramane neatins.
================================================================================
"""
from __future__ import annotations

# Rang de incredere per sursa — mai mic = mai de incredere (ID-025-01, Pasul 1).
# Valorile nu sunt contigue prin design: lasa loc de inserare pentru surse
# viitoare fara a renumerota (si fara a atinge ordinea relativa deja calibrata).
SOURCE_TRUST_RANK: dict[str, int] = {
    "flashscore": 1,          # [F4.3] Foundation Data Layer — vezi antet
    "football_data": 2,       # ADR-024 (era 1; ordinea relativa neschimbata)
    "tsdb": 3,                # [F4.3] cel mai complet per rand, dar n=13
    "espn": 4,                # ADR-024 (era 2)
    "odds_api": 5,            # ADR-024 (era 3)
    "openfootball": 6,        # [F4.3] ~= kaggle + `season`
    "kaggle_historical": 7,   # ADR-024 (era 4) — ramane cel mai putin de incredere
}

# Ordinea relativa a surselor calibrate de ADR-024, in forma verificabila
# automat. Extinderea registrului nu are voie sa o schimbe (vezi antet).
_ADR024_RELATIVE_ORDER: tuple[str, ...] = (
    "football_data", "espn", "odds_api", "kaggle_historical",
)


class SourceTrustProvider:
    """
    Interfata consumata de algoritmul de selectie (ID-025-01, Pasul 1):
    `SourceTrustProvider.get_rank(source: str) -> int | None`.
    """

    @staticmethod
    def get_rank(source: str) -> int | None:
        """Rangul de incredere al unei surse, sau None daca e necunoscuta."""
        return SOURCE_TRUST_RANK.get(source)
