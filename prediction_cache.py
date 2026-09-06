"""
================================================================================
FOOTBALL ORACLE — Cache de predicții partajat între sesiuni
================================================================================
Module: prediction_cache.py

Cache-ul de predicții din `app.py` trăiește în `st.session_state`, adică în
memoria UNEI sesiuni de browser. O sesiune nouă — alt tab, alt dispozitiv,
aplicația adormită și redeschisă — pornește cu cache-ul gol și recalculează
de la zero fiecare meci, deși un alt vizitator tocmai plătise acel calcul.

Modulul ăsta ține logica unui cache cu expirare, PUR: dicționarul și ceasul
sunt injectate, nu importate. `app.py` îi dă un dicționar partajat la nivel de
proces (`st.cache_resource`) și `time.time()`. Aici nu se importă Streamlit și
nu se citește ceasul — de aceea se poate testa exact, fără a aștepta secunde.

De ce un dicționar propriu și nu `st.cache_data`: acela serializează prin
pickle, iar `MatchPrediction` conține câmpuri `Any` (rapoartele de accidentări)
care nu sunt garantat serializabile. Un obiect care refuză pickle ar transforma
o optimizare într-o eroare la runtime, în producție. Aici obiectele se
păstrează ca atare.

Consecință acceptată conștient: valorile sunt PARTAJATE, nu copiate. Un apelant
care ar modifica o predicție întoarsă de aici ar afecta ce vede altcineva.
Predicțiile sunt tratate ca imuabile peste tot în UI (se citesc, nu se scriu),
deci e sigur — dar e o proprietate de respectat, nu un accident.
================================================================================
"""
from __future__ import annotations

from typing import Any

# Câte predicții se păstrează cel mult. La depășire se elimină întâi cele mai
# vechi. Plafonul există ca dicționarul partajat să nu crească nemărginit
# într-un proces care rulează săptămâni întregi.
CAPACITATE_IMPLICITA = 500


def citeste(depozit: dict, cheie: str, *, acum: float, ttl: float) -> Any | None:
    """Valoarea, dacă există și nu a expirat. O intrare expirată se șterge la
    citire — altfel un meci nemaicerut niciodată ar ocupa loc la nesfârșit."""
    intrare = depozit.get(cheie)
    if intrare is None:
        return None
    scris_la, valoare = intrare
    if acum - scris_la > ttl:
        depozit.pop(cheie, None)
        return None
    return valoare


def scrie(depozit: dict, cheie: str, valoare: Any, *, acum: float,
          ttl: float, capacitate: int = CAPACITATE_IMPLICITA) -> None:
    """Scrie și face curățenie. `None` NU se memorează: o analiză eșuată nu are
    voie să blocheze reîncercarea pentru toată durata TTL-ului."""
    if valoare is None:
        return
    depozit[cheie] = (acum, valoare)
    curata(depozit, acum=acum, ttl=ttl)
    _taie_la_capacitate(depozit, capacitate)


def curata(depozit: dict, *, acum: float, ttl: float) -> int:
    """Elimină intrările expirate. Întoarce câte au fost eliminate."""
    expirate = [k for k, (scris_la, _) in depozit.items() if acum - scris_la > ttl]
    for k in expirate:
        depozit.pop(k, None)
    return len(expirate)


def _taie_la_capacitate(depozit: dict, capacitate: int) -> None:
    if capacitate <= 0 or len(depozit) <= capacitate:
        return
    # Cele mai vechi ies primele. Ordonarea e pe marcajul de scriere, nu pe
    # ordinea de inserare — o rescriere reîmprospătează intrarea.
    dupa_varsta = sorted(depozit.items(), key=lambda kv: kv[1][0])
    for cheie, _ in dupa_varsta[:len(depozit) - capacitate]:
        depozit.pop(cheie, None)


def goleste(depozit: dict) -> int:
    """Golire completă — folosită de butonul „Recalculează tot". Întoarce câte
    intrări au fost eliminate."""
    n = len(depozit)
    depozit.clear()
    return n
