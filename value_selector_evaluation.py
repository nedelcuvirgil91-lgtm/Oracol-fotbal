"""
================================================================================
FOOTBALL ORACLE — Value Selector Evaluation (ADR-071 §16)
================================================================================
Module: value_selector_evaluation.py

Leaga selectiile persistate in `value_selector_shadow` de rezultatele reale din
`match_history.actual_result` si produce, per politica, cifrele care decid F3:
rata de reusita, rata implicita a pietei, ROI la miza plata, cota medie, Brier
si log-loss.

STRICT READ-ONLY fata de tot ce e upstream si fata de shadow. Nu scrie nimic,
nicaieri — nici macar in `value_selector_shadow`. Nu exista tabela de rezultate
si nu se creeaza una aici: ADR-071 nu prevede una, iar o tabela noua e o
schimbare de contract care cere decizie explicita (Discovery Rule, CLAUDE.md).
Pana atunci raportul e efemer, tiparit la fiecare rulare.

Doua reguli care nu se incalca:

1. **§16 — prima aparitie.** Cu `days_ahead=1`, acelasi meci apare in doua
   rulari consecutive, cu cote posibil diferite. Per `(policy_id, fixture_id)`
   conteaza EXCLUSIV rularea cu cel mai mic `run_id`. Aparitiile ulterioare
   raman in baza (nimic nu se sterge, §15) dar nu se numara a doua oara.
   Fara regula asta, "150 de selectii" nu inseamna nimic si rezultatul nu e
   auditabil retroactiv.

2. **Necunoscutul ramane necunoscut (Regula #8).** Un meci fara rezultat, sau
   cu un `actual_result` care nu e H/D/A (amanare, valoare straina), NU e o
   pierdere — e "in asteptare" si se contorizeaza separat. Nicio metrica nu se
   calculeaza pe el.

Cifrele NU sunt un verdict. Sub pragul de eșantion cerut de ADR-071 (150 de
selectii), raportul marcheaza explicit `esantion_insuficient` si nu declara
niciodata o politica invingatoare. Un ROI pe zece selectii e zgomot, nu semnal.
================================================================================
"""
from __future__ import annotations

import logging
import math
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Sequence

from value_selector_adapter import REZULTAT_PENTRU_SELECTIE

logger = logging.getLogger(__name__)

SHADOW_TABLE = "value_selector_shadow"

# Pragul de la care ADR-071 accepta ca o comparatie intre politici incepe sa
# aiba sens. Sub el, raportul refuza sa numeasca o castigatoare.
PRAG_ESANTION_MINIM = 150

# Limitele de siguranta pentru log-loss: o probabilitate exact 0 sau 1 ar da
# infinit. Taierea e simetrica si documentata, nu ascunsa.
_EPS = 1e-12


# ── Rezultatul unui meci ─────────────────────────────────────────────────────

def rezultat_selectiei(selection_code: str, actual_result: Any) -> bool | None:
    """`True` = selectia a castigat, `False` = a pierdut, `None` = necunoscut.

    `None` acopera doua situatii distincte, tratate identic DELIBERAT: meciul
    nu s-a jucat inca, sau `actual_result` are o valoare care nu e H/D/A
    (amanare, valoare straina de la un provider). In ambele cazuri raspunsul
    onest e "nu stim", niciodata "a pierdut"."""
    tinta = REZULTAT_PENTRU_SELECTIE.get(selection_code)
    if tinta is None:
        raise ValueError(f"cod de selectie necunoscut: {selection_code!r}")
    if actual_result is None:
        return None
    rezultat = str(actual_result).strip().upper()
    if rezultat not in set(REZULTAT_PENTRU_SELECTIE.values()):
        return None
    return rezultat == tinta


# ── §16: prima aparitie ──────────────────────────────────────────────────────

def pastreaza_prima_aparitie(randuri: Iterable[dict]) -> list[dict]:
    """Filtreaza la rularea cea mai veche in care apare fiecare pereche
    `(policy_id, fixture_id)`.

    `run_id` are formatul `YYYY-MM-DDTHH:MMZ`, deci ordonarea lexicografica
    coincide cu cea cronologica — proprietate pe care se bazeaza comparatia de
    aici si care e verificata prin test, ca sa nu se piarda tacit daca formatul
    se schimba vreodata.

    Intoarce TOATE randurile din acea rulare pentru perechea respectiva (cele
    trei selectii 1/X/2), nu doar cea aleasa: categorisirea se face mai tarziu,
    iar unele politici pot avea mai multe selectii marcate pe acelasi meci
    (`legacy` nu are `one_selection_per_match`)."""
    prima: dict[tuple[str, str], str] = {}
    for rand in randuri:
        cheie = (str(rand.get("policy_id")), str(rand.get("fixture_id")))
        run_id = str(rand.get("run_id") or "")
        curent = prima.get(cheie)
        if curent is None or run_id < curent:
            prima[cheie] = run_id
    return [
        r for r in randuri
        if prima.get((str(r.get("policy_id")), str(r.get("fixture_id"))))
        == str(r.get("run_id") or "")
    ]


# ── Metrici ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RezultatCategorie:
    """Cifrele unei categorii (Top sau Longshot) pentru o singura politica."""
    categorie: str
    selectii_totale: int
    in_asteptare: int
    decise: int
    reusite: int
    rata_reusita: float | None
    rata_implicita_piata: float | None
    diferenta_pp: float | None
    roi_miza_plata: float | None
    roi_piata_implicit: float | None
    diferenta_roi_pp: float | None
    cota_medie: float | None
    brier_model: float | None
    brier_piata: float | None
    log_loss_model: float | None
    log_loss_piata: float | None
    esantion_insuficient: bool


@dataclass(frozen=True)
class RezultatPolitica:
    policy_id: str
    policy_profile: str
    policy_family: str | None
    categorii: dict[str, RezultatCategorie]


def _medie(valori: Sequence[float]) -> float | None:
    return sum(valori) / len(valori) if valori else None


def _brier(probabilitati: Sequence[float], castiguri: Sequence[bool]) -> float | None:
    if not probabilitati:
        return None
    return sum((p - (1.0 if w else 0.0)) ** 2
               for p, w in zip(probabilitati, castiguri)) / len(probabilitati)


def _log_loss(probabilitati: Sequence[float], castiguri: Sequence[bool]) -> float | None:
    if not probabilitati:
        return None
    total = 0.0
    for p, w in zip(probabilitati, castiguri):
        p = min(max(p, _EPS), 1.0 - _EPS)
        total += -math.log(p) if w else -math.log(1.0 - p)
    return total / len(probabilitati)


def evalueaza_categorie(randuri: Sequence[dict], *, categorie: str,
                        rezultate: dict[str, Any]) -> RezultatCategorie:
    """Cifrele unei categorii. `rezultate` mapeaza `fixture_id` -> `actual_result`.

    `roi_piata_implicit` e controlul onest: ce ROI ar fi produs aceleasi
    selectii daca probabilitatea reala ar fi fost exact cea a pietei. E aproape
    intotdeauna negativ (marja casei), si tocmai de aceea e reperul corect —
    criteriul GO/NO-GO al ADR-071 cere depasirea lui cu 3 pp, nu depasirea
    lui zero."""
    in_asteptare = 0
    p_model: list[float] = []
    p_piata: list[float] = []
    cote: list[float] = []
    castiguri: list[bool] = []

    for rand in randuri:
        castigat = rezultat_selectiei(str(rand["selection_code"]),
                                      rezultate.get(str(rand["fixture_id"])))
        if castigat is None:
            in_asteptare += 1
            continue
        p_model.append(float(rand["model_probability"]))
        p_piata.append(float(rand["fair_probability"]))
        cote.append(float(rand["bk_odds"]))
        castiguri.append(castigat)

    decise = len(castiguri)
    reusite = sum(1 for c in castiguri if c)

    rata = (reusite / decise) if decise else None
    implicita = _medie(p_piata)
    roi = (_medie([o if c else 0.0 for o, c in zip(cote, castiguri)]) - 1.0) if decise else None
    # ROI-ul asteptat daca piata ar avea dreptate: E[cota * P_piata] - 1.
    roi_piata = (_medie([o * p for o, p in zip(cote, p_piata)]) - 1.0) if decise else None

    return RezultatCategorie(
        categorie=categorie,
        selectii_totale=len(randuri),
        in_asteptare=in_asteptare,
        decise=decise,
        reusite=reusite,
        rata_reusita=rata,
        rata_implicita_piata=implicita,
        diferenta_pp=None if (rata is None or implicita is None)
        else (rata - implicita) * 100.0,
        roi_miza_plata=roi,
        roi_piata_implicit=roi_piata,
        diferenta_roi_pp=None if (roi is None or roi_piata is None)
        else (roi - roi_piata) * 100.0,
        cota_medie=_medie(cote),
        brier_model=_brier(p_model, castiguri),
        brier_piata=_brier(p_piata, castiguri),
        log_loss_model=_log_loss(p_model, castiguri),
        log_loss_piata=_log_loss(p_piata, castiguri),
        esantion_insuficient=decise < PRAG_ESANTION_MINIM,
    )


def evalueaza(randuri: Sequence[dict], rezultate: dict[str, Any]) -> list[RezultatPolitica]:
    """Evalueaza toate politicile, dupa aplicarea regulii §16.

    Categoriile se numara pe flagurile persistate (`selected_top` /
    `selected_longshot`), nu pe `category`, pentru ca flagurile sunt sursa
    primara scrisa de selector; `category` e derivata lor. Coerenta celor doua
    e verificata separat, in auditul de date."""
    de_evaluat = pastreaza_prima_aparitie(randuri)

    pe_politica: dict[str, list[dict]] = {}
    for rand in de_evaluat:
        pe_politica.setdefault(str(rand["policy_id"]), []).append(rand)

    iesire: list[RezultatPolitica] = []
    for policy_id in sorted(pe_politica):
        randuri_politica = pe_politica[policy_id]
        primul = randuri_politica[0]
        top = [r for r in randuri_politica if r.get("selected_top")]
        longshot = [r for r in randuri_politica if r.get("selected_longshot")]
        iesire.append(RezultatPolitica(
            policy_id=policy_id,
            policy_profile=str(primul.get("policy_profile") or ""),
            policy_family=primul.get("policy_family"),
            categorii={
                "top": evalueaza_categorie(top, categorie="top", rezultate=rezultate),
                "longshot": evalueaza_categorie(longshot, categorie="longshot",
                                                rezultate=rezultate),
            },
        ))
    return iesire


# ── Citire (strict read-only) ────────────────────────────────────────────────

def _paginat(query_factory, *, dimensiune: int = 1000) -> list[dict]:
    """Citeste tot setul in pagini. Supabase limiteaza implicit numarul de
    randuri intoarse; fara paginare, o evaluare pe mai multe saptamani ar taia
    tacit datele si ar raporta cifre pe un subset, fara niciun semnal."""
    randuri: list[dict] = []
    start = 0
    while True:
        lot = (query_factory().range(start, start + dimensiune - 1).execute()).data or []
        randuri.extend(lot)
        if len(lot) < dimensiune:
            return randuri
        start += dimensiune


def incarca_selectii(*, run_id: str | None = None) -> list[dict]:
    """Randurile shadow relevante. `leakage_suspect` e exclus la sursa: o
    selectie despre care colectorul insusi a semnalat suspiciune de scurgere
    temporala nu are ce cauta intr-o masuratoare de performanta."""
    from database.queries import get_client

    client = get_client()
    if client is None:
        logger.warning("[ValueSelectorEval] fara client Supabase — nimic de citit.")
        return []

    def q():
        interogare = (
            client.table(SHADOW_TABLE)
            .select("run_id,policy_id,policy_profile,policy_family,fixture_id,"
                    "match_label,league,selection_code,model_probability,"
                    "fair_probability,bk_odds,selected_top,selected_longshot,"
                    "kickoff_utc")
            .eq("leakage_suspect", False)
            .order("id")
        )
        return interogare.eq("run_id", run_id) if run_id else interogare

    try:
        return _paginat(q)
    except Exception as exc:
        logger.warning("[ValueSelectorEval] citire %s esuata: %s", SHADOW_TABLE, exc)
        return []


def incarca_rezultate(fixture_ids: Sequence[str]) -> dict[str, Any]:
    """`fixture_id` -> `actual_result`. Citeste `match_history`, nu il modifica."""
    from database.queries import get_client

    client = get_client()
    if client is None or not fixture_ids:
        return {}

    rezultate: dict[str, Any] = {}
    unice = sorted(set(fixture_ids))
    for start in range(0, len(unice), 200):
        felie = unice[start:start + 200]
        try:
            randuri = (
                client.table("match_history")
                .select("fixture_id,actual_result")
                .in_("fixture_id", felie)
                .execute()
            ).data or []
        except Exception as exc:
            logger.warning("[ValueSelectorEval] citire match_history esuata: %s", exc)
            continue
        for rand in randuri:
            rezultate[str(rand.get("fixture_id"))] = rand.get("actual_result")
    return rezultate


# ── Orchestrare ──────────────────────────────────────────────────────────────

def run(*, run_id: str | None = None) -> dict:
    """Raportul complet. Nu scrie nimic — nici in shadow, nici altundeva."""
    selectii = incarca_selectii(run_id=run_id)
    if not selectii:
        return {"selectii_citite": 0, "politici": [], "avertisment":
                "niciun rand shadow citit (client absent, tabela goala sau filtru prea ingust)"}

    rezultate = incarca_rezultate([str(r["fixture_id"]) for r in selectii])
    politici = evalueaza(selectii, rezultate)

    fixture_unice = {str(r["fixture_id"]) for r in selectii}
    cu_rezultat = sum(1 for f in fixture_unice
                      if rezultat_selectiei("1", rezultate.get(f)) is not None)

    raport = {
        "run_id_filtru": run_id,
        "selectii_citite": len(selectii),
        "dupa_regula_primei_aparitii": len(pastreaza_prima_aparitie(selectii)),
        "rulari_distincte": len({str(r["run_id"]) for r in selectii}),
        "meciuri": len(fixture_unice),
        "meciuri_cu_rezultat": cu_rezultat,
        "meciuri_in_asteptare": len(fixture_unice) - cu_rezultat,
        "prag_esantion_minim": PRAG_ESANTION_MINIM,
        "politici": [
            {"policy_id": p.policy_id, "policy_profile": p.policy_profile,
             "policy_family": p.policy_family,
             "categorii": {k: asdict(v) for k, v in p.categorii.items()}}
            for p in politici
        ],
    }
    logger.info("[ValueSelectorEval] %d selectii, %d meciuri, %d cu rezultat",
                len(selectii), len(fixture_unice), cu_rezultat)
    return raport


if __name__ == "__main__":  # pragma: no cover
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Evaluarea selectiilor shadow (ADR-071 §16)")
    parser.add_argument("--run-id", default=None,
                        help="limiteaza la o singura rulare; implicit toate")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print(json.dumps(run(run_id=args.run_id), indent=2, ensure_ascii=False))
