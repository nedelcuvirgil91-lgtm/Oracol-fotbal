"""
================================================================================
FOOTBALL ORACLE — Value Selector Shadow Runner (ADR-071, faza F2)
================================================================================
Module: value_selector_shadow.py

Colectare prospectiva, fara niciun efect asupra productiei. Ruleaza cele 13
profile de politica in PARALEL pe aceleasi intrari si persista TOATE deciziile
— acceptate, longshot si respinse — in `value_selector_shadow`.

Ce NU face, deliberat:
  - nu apeleaza Oracle Engine si nu declanseaza nicio predictie noua;
  - nu scrie in `match_history`, `shadow_predictions`, `odds_history` sau in
    orice alta tabela existenta;
  - nu schimba nimic in UI, nu promoveaza, nu face rollback, nu reantreneaza;
  - nu alege un castigator si nu ajusteaza praguri pe parcurs.

De ce citeste predictii STOCATE, nu recalculate (decizie de design, cu cost
asumat): singura sursa cu `prediction_time` dovedit anterior loviturii de start
e `shadow_predictions` (append-only, scrisa nocturn de Challenger Shadow Batch,
ADR-056). `match_history.prob_*_pred` e suprascris la fiecare `evaluate_match()`,
deci nu poate dovedi cand a fost facuta predictia. A recalcula acum ar insemna
sa invocam motorul (interzis in F2) si ar declansa scrieri in `match_history`
prin `_cache_prediction()`.

Costul asumat: predictia are in medie ~57 h la momentul evaluarii, mai veche
decat cea pe care ar vedea-o un utilizator care deschide aplicatia in ziua
meciului. Costul NU se ascunde — se masoara: `prediction_freshness_s` e
persistat per candidat, iar poarta de prospetime a predictiei isi da verdictul
pe el.

Campuri necunoscute in V1, ramase explicit necunoscute (Regula #8):
  - `odds_freshness_s` — timestamp-ul capturii cotei nu e propagat (ADR-071 §14);
  - `matches_analysed` — nu e persistat nicaieri azi.
Ambele produc verdictul `UNKNOWN` la portile lor, niciodata `PASS`.
================================================================================
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Sequence

from value_selector import (
    SelectionCandidate,
    SelectorPolicy,
    select_by_day,
    to_shadow_rows,
)
from value_selector_adapter import candidates_from_prediction
from value_selector_config import F2_PROFILES, is_shadow_logging_enabled

logger = logging.getLogger("FootballOracle.ValueSelectorShadow")

SHADOW_TABLE = "value_selector_shadow"
EXPERIMENT_NAME = "blend_v1"
EXPERIMENT_GROUP = "control"
PROCESSING_STAGE = "final"


# ── Familii de politici (deduplicare analitica) ──────────────────────────────

def policy_families(profiles: dict[str, SelectorPolicy]) -> dict[str, str]:
    """Mapeaza fiecare profil la o FAMILIE, grupand profilele semantic identice.

    Doua profile cu aceeasi amprenta de praguri sunt acelasi experiment sub doua
    nume (ex. `shrunk_050` si `market_floor_025`, ambele `32ccbf4a`: centrul
    comun al celor doua grile). `policy_id` ramane distinct pentru trasabilitate,
    dar la analiza F3 familia e unitatea corecta de numarare — altfel acelasi
    experiment ar cantari dublu.

    Numele familiei e cel al primului profil in ordine alfabetica, ca sa fie
    stabil intre rulari, nu dependent de ordinea dictionarului."""
    pe_amprenta: dict[str, list[str]] = {}
    for nume, politica in profiles.items():
        pe_amprenta.setdefault(politica.fingerprint(), []).append(nume)
    familii: dict[str, str] = {}
    for membri in pe_amprenta.values():
        familie = sorted(membri)[0]
        for nume in membri:
            familii[nume] = familie
    return familii


def semantic_duplicates(profiles: dict[str, SelectorPolicy]) -> dict[str, list[str]]:
    """Doar grupurile cu mai mult de un membru — ce trebuie marcat explicit in
    raportul F3 ca fiind acelasi experiment."""
    pe_amprenta: dict[str, list[str]] = {}
    for nume, politica in profiles.items():
        pe_amprenta.setdefault(politica.fingerprint(), []).append(nume)
    return {amprenta: sorted(membri) for amprenta, membri in pe_amprenta.items()
            if len(membri) > 1}


# ── Vederi minimale peste randurile din baza de date ─────────────────────────
# Adaptorul existent citeste `MatchPrediction` prin getattr. Ii dam un obiect cu
# exact aceleasi atribute, ca maparea celor trei rezultate 1X2 sa traiasca
# intr-un singur loc (`value_selector_adapter`), nu duplicata aici.

@dataclass(frozen=True)
class _ProfileView:
    data_quality: str | None
    matches_analysed: int | None


@dataclass(frozen=True)
class _PredictionView:
    fixture_id: str
    home_team: str
    away_team: str
    league: str
    kickoff_utc: str
    bookmaker_name: str | None
    prob_home_win: float
    prob_draw: float
    prob_away_win: float
    bk_home_odds: float
    bk_draw_odds: float
    bk_away_odds: float
    fair_home_pct: float
    fair_draw_pct: float
    fair_away_pct: float
    home_profile: _ProfileView
    away_profile: _ProfileView


def _devig(oh: float, od: float, oa: float) -> tuple[float, float, float]:
    """De-vig proportional — aceeasi conventie ca `oracle_engine`, reimplementata
    aici pentru ca modulul sa nu importe motorul. Echivalenta e fixata printr-un
    test dedicat, ca sa nu se desincronizeze tacit."""
    total = 1.0 / oh + 1.0 / od + 1.0 / oa
    if total <= 0:
        return 0.0, 0.0, 0.0
    return (1.0 / oh) / total, (1.0 / od) / total, (1.0 / oa) / total


def prediction_view_from_row(row: dict) -> _PredictionView | None:
    """Construieste vederea din randul deja imbinat (predictie + cote + meci).
    Intoarce `None` daca lipseste orice element necesar — nicio candidatura
    partiala, nicio aproximare."""
    try:
        oh = float(row["odds_home"]); od = float(row["odds_draw"]); oa = float(row["odds_away"])
        ph = float(row["prob_home"]); pd = float(row["prob_draw"]); pa = float(row["prob_away"])
    except (KeyError, TypeError, ValueError):
        return None
    if min(oh, od, oa) <= 1.0:
        return None

    fh, fd, fa = _devig(oh, od, oa)
    return _PredictionView(
        fixture_id=str(row.get("fixture_id") or ""),
        home_team=str(row.get("home_team") or ""),
        away_team=str(row.get("away_team") or ""),
        league=str(row.get("league") or ""),
        kickoff_utc=str(row.get("kickoff_utc") or ""),
        bookmaker_name=row.get("bookmaker"),
        prob_home_win=ph, prob_draw=pd, prob_away_win=pa,
        bk_home_odds=oh, bk_draw_odds=od, bk_away_odds=oa,
        fair_home_pct=fh * 100.0, fair_draw_pct=fd * 100.0, fair_away_pct=fa * 100.0,
        home_profile=_ProfileView(row.get("home_data_quality"), None),
        away_profile=_ProfileView(row.get("away_data_quality"), None),
    )


def candidates_from_rows(rows: Sequence[dict], *, evaluated_at: datetime) -> list[SelectionCandidate]:
    """Randuri imbinate -> candidaturi, cu varstele calculate fata de
    `evaluated_at` (INJECTAT, nu citit din ceas aici)."""
    out: list[SelectionCandidate] = []
    for row in rows:
        view = prediction_view_from_row(row)
        if view is None:
            continue
        kickoff = _parse_ts(row.get("kickoff_utc"))
        predicted = _parse_ts(row.get("prediction_time"))
        seconds_to_kickoff = None if kickoff is None else (kickoff - evaluated_at).total_seconds()
        prediction_age_s = None if predicted is None else (evaluated_at - predicted).total_seconds()
        out.extend(candidates_from_prediction(
            view,
            prediction_age_s=prediction_age_s,
            odds_age_s=None,           # necunoscut in V1 — ADR-071 §14
            seconds_to_kickoff=seconds_to_kickoff,
        ))
    return out


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip().replace("Z", "+00:00")
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed = datetime.fromisoformat(text[:19])
        except ValueError:
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


# ── Maparea la coloanele tabelei ─────────────────────────────────────────────

def to_db_rows(payload: Sequence[dict], *, policy: SelectorPolicy, family: str) -> list[dict]:
    """Traduce payload-ul pur produs de `value_selector.to_shadow_rows()` in
    randurile tabelei. Functie pura — testabila fara baza de date."""
    rows: list[dict] = []
    for item in payload:
        category = item["category"]
        rows.append({
            "run_id": item["run_id"],
            "evaluated_at": item["evaluated_at"],
            "policy_id": item["policy_id"],
            "policy_profile": item["policy_profile"],
            "policy_family": family,
            "policy_fingerprint": policy.fingerprint(),
            "ranker_id": item["ranker_id"],
            "shrinkage_w": item["shrinkage_w"],
            "fixture_id": item["fixture_id"],
            "match_label": item["match_label"],
            "league": item["league"],
            "kickoff_utc": item["kickoff_utc"] or None,
            "market": item["market"],
            "selection_code": item["selection_code"],
            "model_probability": item["model_p"],
            "fair_probability": item["fair_p"],
            "bk_odds": item["bk_odds"],
            "bookmaker": item["bookmaker"],
            "absolute_edge_pp": item["e_abs_pp"],
            "relative_edge_pct": item["e_rel_pct"],
            "p_shr": item["p_shr"],
            "ev_raw": item["ev_raw"],
            "ev_shr": item["ev_shr"],
            "rank_in_match": item["rank_in_match"],
            "actionability_score": item["actionability_score"],
            "rank_in_day": item["rank_in_day"],
            "category": category,
            "selected_top": category == "top",
            "selected_longshot": category == "longshot",
            "rejected": category == "rejected",
            "gate_verdicts": item["gate_results"],
            "gate_details": item.get("gate_details") or {},
            "rejection_reasons": item["rejection_reasons"],
            "data_quality": item["data_quality"],
            "matches_analysed": item["matches_analysed"],
            "prediction_freshness_s": item["prediction_age_s"],
            "odds_freshness_s": item["odds_age_s"],
            "seconds_to_kickoff": item["seconds_to_kickoff"],
            "leakage_suspect": item["leakage_suspect"],
        })
    return rows


# ── Citire (read-only) ───────────────────────────────────────────────────────

def load_inputs(*, days_ahead: int = 1,
                now: datetime | None = None) -> tuple[list[dict], dict[str, int]]:
    """Meciurile din fereastra ceruta, imbinate cu cea mai VECHE predictie de
    control si cu cotele persistate. Strict read-only.

    Doua garzi de scurgere temporala, aplicate la SURSA, nu doar la evaluare:
      1. meciul trebuie sa fie inca in viitor la momentul evaluarii — filtrul de
         baza de date e pe DATA (ieftin, indexat), dar comparatia fina se face
         pe momentul exact, altfel un meci de azi-dimineata ar intra in set si
         ar produce `leakage_suspect=true`;
      2. predictia trebuie sa fie anterioara loviturii de start.

    Intoarce (randuri, contoare) — contoarele explica exact cate meciuri au fost
    excluse si de ce, ca diferenta dintre ce exista si ce s-a evaluat sa nu fie
    niciodata o cifra neexplicata."""
    from database.queries import get_client

    contoare = {"gasite": 0, "deja_incepute": 0, "fara_predictie": 0,
                "fara_cote": 0, "predictie_dupa_kickoff": 0, "retinute": 0}

    client = get_client()
    if client is None:
        logger.warning("[ValueSelectorShadow] fara client Supabase — nimic de citit.")
        return [], contoare

    moment = now or datetime.now(timezone.utc)
    limita = moment + timedelta(days=days_ahead)

    try:
        meciuri = (
            client.table("match_history")
            .select("fixture_id,home_team,away_team,league,kickoff_date,"
                    "home_data_quality,away_data_quality")
            .gte("kickoff_date", moment.date().isoformat())
            .lte("kickoff_date", limita.date().isoformat() + "T23:59:59")
            .not_.is_("fixture_id", "null")
            .execute()
        ).data or []
    except Exception as exc:
        logger.warning("[ValueSelectorShadow] citire match_history esuata: %s", exc)
        return [], contoare

    contoare["gasite"] = len(meciuri)
    fixture_ids = [m["fixture_id"] for m in meciuri if m.get("fixture_id")]
    if not fixture_ids:
        return [], contoare

    predictii = _load_predictions(client, fixture_ids)
    cote = _load_odds(client, fixture_ids)

    randuri: list[dict] = []
    for meci in meciuri:
        fid = meci["fixture_id"]
        kickoff = _parse_ts(meci.get("kickoff_date"))
        # Garda 1: meciul trebuie sa fie inca in viitor. Filtrul de mai sus e pe
        # DATA, deci un meci de azi-dimineata ar trece de el.
        if kickoff is None or kickoff <= moment:
            contoare["deja_incepute"] += 1
            continue
        predictie = predictii.get(fid)
        if not predictie:
            contoare["fara_predictie"] += 1
            continue
        cota = cote.get(fid)
        if not cota:
            contoare["fara_cote"] += 1
            continue
        predicted = _parse_ts(predictie.get("prediction_time"))
        # Garda 2: predictia trebuie sa fie anterioara loviturii de start.
        if predicted is None or predicted >= kickoff:
            contoare["predictie_dupa_kickoff"] += 1
            continue
        contoare["retinute"] += 1
        randuri.append({
            "fixture_id": fid,
            "home_team": meci.get("home_team"),
            "away_team": meci.get("away_team"),
            "league": meci.get("league"),
            "kickoff_utc": meci.get("kickoff_date"),
            "home_data_quality": meci.get("home_data_quality"),
            "away_data_quality": meci.get("away_data_quality"),
            "prediction_time": predictie.get("prediction_time"),
            "prob_home": predictie.get("prob_home"),
            "prob_draw": predictie.get("prob_draw"),
            "prob_away": predictie.get("prob_away"),
            "odds_home": cota.get("home"),
            "odds_draw": cota.get("draw"),
            "odds_away": cota.get("away"),
            "bookmaker": cota.get("bookmaker"),
        })
    return randuri, contoare


def _load_predictions(client, fixture_ids: Sequence[str]) -> dict[str, dict]:
    """Cea mai VECHE predictie de control per fixture — cea mai apropiata de
    momentul in care informatia a devenit disponibila prima data."""
    try:
        rows = (
            client.table("shadow_predictions")
            .select("id,fixture_id,prediction_time,prob_home,prob_draw,prob_away")
            .eq("experiment_name", EXPERIMENT_NAME)
            .eq("experiment_group", EXPERIMENT_GROUP)
            .eq("processing_stage", PROCESSING_STAGE)
            .in_("fixture_id", list(fixture_ids))
            .is_("invalidated_at", "null")
            .execute()
        ).data or []
    except Exception as exc:
        logger.warning("[ValueSelectorShadow] citire shadow_predictions esuata: %s", exc)
        return {}

    # Ordonare explicita inainte de alegere: Supabase nu garanteaza ordinea
    # randurilor, iar la egalitate de `prediction_time` "primul intalnit" ar
    # depinde de acea ordine. Cheia secundara `id` face alegerea reproductibila.
    best: dict[str, dict] = {}
    for row in sorted(rows, key=lambda r: (str(r.get("prediction_time") or ""), r.get("id") or 0)):
        fid = row.get("fixture_id")
        if fid and fid not in best:
            best[fid] = row
    return best


def _load_odds(client, fixture_ids: Sequence[str]) -> dict[str, dict]:
    """Cote persistate: `opening_*` preferat (capturat cel mai devreme, deci
    cel mai sigur anterior startului), cu `closing_*` doar ca rezerva.

    Cand un meci are cote de la mai multe case, alegerea trebuie sa fie
    REPRODUCTIBILA: Supabase nu garanteaza ordinea randurilor, deci "prima casa
    intalnita" ar putea diferi intre doua rulari pe aceleasi date. Se ordoneaza
    explicit dupa `id` (cheia primara) inainte de alegere."""
    try:
        rows = (
            client.table("odds_history")
            .select("id,fixture_id,bookmaker,opening_home,opening_draw,opening_away,"
                    "closing_home,closing_draw,closing_away")
            .in_("fixture_id", list(fixture_ids))
            .execute()
        ).data or []
    except Exception as exc:
        logger.warning("[ValueSelectorShadow] citire odds_history esuata: %s", exc)
        return {}

    best: dict[str, dict] = {}
    for row in sorted(rows, key=lambda r: r.get("id") or 0):
        fid = row.get("fixture_id")
        if not fid or fid in best:
            continue
        home = row.get("opening_home") or row.get("closing_home")
        draw = row.get("opening_draw") or row.get("closing_draw")
        away = row.get("opening_away") or row.get("closing_away")
        if not (home and draw and away):
            continue
        best[fid] = {"home": home, "draw": draw, "away": away,
                     "bookmaker": row.get("bookmaker")}
    return best


# ── Scriere (exclusiv in tabela proprie) ─────────────────────────────────────

def persist_rows(rows: Sequence[dict]) -> int:
    """Upsert atomic pe cheia naturala. Scrie DOAR in `value_selector_shadow`."""
    if not rows:
        return 0
    from database.queries import get_client

    client = get_client()
    if client is None:
        logger.warning("[ValueSelectorShadow] fara client Supabase — nimic persistat.")
        return 0

    scrise = 0
    for start in range(0, len(rows), 500):
        lot = list(rows[start:start + 500])
        try:
            client.table(SHADOW_TABLE).upsert(
                lot, on_conflict="run_id,policy_id,fixture_id,selection_code"
            ).execute()
            scrise += len(lot)
        except Exception as exc:
            logger.warning("[ValueSelectorShadow] upsert esuat pentru %d randuri: %s",
                           len(lot), exc)
    return scrise


# ── Orchestrare ──────────────────────────────────────────────────────────────

def build_rows_for_all_profiles(candidates: Sequence[SelectionCandidate], *,
                                run_id: str, evaluated_at: datetime,
                                profiles: dict[str, SelectorPolicy] | None = None) -> list[dict]:
    """Ruleaza toate profilele pe ACELEASI candidaturi si intoarce randurile de
    persistat. Functie pura — nicio citire, nicio scriere."""
    profiles = profiles if profiles is not None else F2_PROFILES
    familii = policy_families(profiles)
    stamp = evaluated_at.isoformat()

    rows: list[dict] = []
    for nume, politica in profiles.items():
        for _zi, rezultat in select_by_day(candidates, politica).items():
            payload = to_shadow_rows(rezultat, run_id=run_id, evaluated_at=stamp,
                                     policy=politica)
            rows.extend(to_db_rows(payload, policy=politica, family=familii[nume]))
    return rows


def run(*, days_ahead: int = 1, now: datetime | None = None, dry_run: bool = False,
        force: bool = False) -> dict:
    """Punctul de intrare al rularii. Gatat de
    `value_selector_shadow_logging_enabled` — implicit OPRIT (North Star #3).

    `dry_run=True` face tot calculul si raporteaza, dar nu scrie nimic.

    `force=True` ocoleste DOAR verificarea flagului, pentru o rulare manuala
    unica, autorizata explicit. Nu schimba nimic altceva: nu activeaza niciun
    flag, nu atinge configuratia, nu deblocheaza UI-ul. Calea programata
    (cron) NU il foloseste niciodata — invariant verificat prin test, ca o
    rulare automata sa nu poata ocoli gate-ul din greseala."""
    if not (force or is_shadow_logging_enabled()):
        logger.info("[ValueSelectorShadow] flag oprit — nicio colectare.")
        return {"enabled": False, "candidates": 0, "rows": 0, "persisted": 0}

    moment = now or datetime.now(timezone.utc)
    run_id = moment.strftime("%Y-%m-%dT%H:%MZ")

    randuri_brute, contoare = load_inputs(days_ahead=days_ahead, now=moment)
    candidaturi = candidates_from_rows(randuri_brute, evaluated_at=moment)
    rows = build_rows_for_all_profiles(candidaturi, run_id=run_id, evaluated_at=moment)

    persistate = 0 if dry_run else persist_rows(rows)
    raport = {
        "enabled": True,
        "forced": force,
        "evaluated_at": moment.isoformat(),
        "input_counters": contoare,
        "run_id": run_id,
        "matches": len(randuri_brute),
        "candidates": len(candidaturi),
        "profiles": len(F2_PROFILES),
        "families": len(set(policy_families(F2_PROFILES).values())),
        "rows": len(rows),
        "persisted": persistate,
        "dry_run": dry_run,
        "top": sum(1 for r in rows if r["selected_top"]),
        "longshot": sum(1 for r in rows if r["selected_longshot"]),
        "rejected": sum(1 for r in rows if r["rejected"]),
        "leakage_suspect": sum(1 for r in rows if r["leakage_suspect"]),
        "verdicts": _verdict_counts(rows),
    }
    logger.info("[ValueSelectorShadow] %s", raport)
    return raport


def _verdict_counts(rows: Sequence[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        for verdict in (row.get("gate_verdicts") or {}).values():
            counts[verdict] = counts.get(verdict, 0) + 1
    return counts


if __name__ == "__main__":  # pragma: no cover
    import argparse
    import json

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Value Selector Shadow (ADR-071 F2)")
    parser.add_argument("--days-ahead", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--force", action="store_true",
        help="ocoleste DOAR verificarea flagului, pentru o rulare manuala "
             "autorizata explicit; nu activeaza niciun flag")
    args = parser.parse_args()
    print(json.dumps(run(days_ahead=args.days_ahead, dry_run=args.dry_run,
                         force=args.force), indent=2, ensure_ascii=False))
