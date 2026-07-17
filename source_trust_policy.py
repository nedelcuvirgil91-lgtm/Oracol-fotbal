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
================================================================================
"""
from __future__ import annotations

# Rang de incredere per sursa — mai mic = mai de incredere (ID-025-01, Pasul 1).
SOURCE_TRUST_RANK: dict[str, int] = {
    "football_data": 1,
    "espn": 2,
    "odds_api": 3,
    "kaggle_historical": 4,
}


class SourceTrustProvider:
    """
    Interfata consumata de algoritmul de selectie (ID-025-01, Pasul 1):
    `SourceTrustProvider.get_rank(source: str) -> int | None`.
    """

    @staticmethod
    def get_rank(source: str) -> int | None:
        """Rangul de incredere al unei surse, sau None daca e necunoscuta."""
        return SOURCE_TRUST_RANK.get(source)
