"""
================================================================================
FOOTBALL ORACLE — Value Betting Dashboard: agregare (v0.2)
================================================================================
Module: value_dashboard.py

Două căi, aceeași semnătură și același tip de ieșire:

**Calea moștenită (implicită).** Agregă value bets DEJA calculate
(`MatchPrediction.value_bets` + `special_value_bets`, produse de
`oracle_engine.evaluate_match()`, deja filtrate peste `value_bet_threshold_pct`)
și le sortează descrescător după edge relativ. Nu recalculează nimic.

**Calea de radar (ADR-071 §17, gatată de `value_selector_v1_enabled`).** Trece
aceleași predicții prin `value_selector`, care aplică porțile explicite și
întoarce cel mult 5 MECIURI pe zi, unul singur per meci. Nu recalculează
nicio probabilitate și nu atinge nimic din ce a produs Oracle — filtrează
strict după ce motorul și-a terminat treaba.

Invariant de produs (ADR-071 §17): Top Value Bets e un RADAR, nu un sistem de
pariere. Nu produce niciodată mărimea mizei, Kelly, sumă în euro, bancă sau
execuție. `kelly_stake` e `None` pe calea de radar — DELIBERAT, nu din lipsă
de date.

Singura impuritate e citirea flagului, la intrarea în `collect_value_bets()`.
Ambele căi de calcul (`_collect_legacy`, `collect_radar_bets`) rămân funcții
pure, cu politica injectată — deci testabile fără Supabase.

Sursa predicțiilor (cache de sesiune vs. calcul nou) rămâne responsabilitatea
apelantului (`app.py`), neatins de această schimbare.
================================================================================
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ValueBetRow:
    fixture_id:     str
    home_team:      str
    away_team:      str
    league:         str
    kickoff_utc:    str
    market:         str
    selection:      str
    edge_pct:       float
    model_prob_pct: float
    bk_odds:        float
    rating:         str
    kelly_stake:    float | None  # None — nu e calculat azi pentru piețe speciale


def collect_value_bets(predictions: list) -> list[ValueBetRow]:
    """Punctul de intrare al ecranului. Cu flagul stins — comportamentul de
    dinaintea ADR-071, bit cu bit (invariant verificat prin test)."""
    if _radar_activ():
        try:
            from value_selector_config import build_policy
            return collect_radar_bets(predictions, build_policy())
        except Exception as exc:
            # Un radar care crapă nu are voie să golească ecranul: căderea pe
            # calea moștenită păstrează utilizatorul cu lista de dinainte, nu
            # cu o pagină goală și un mesaj de eroare.
            logger.warning("[ValueDashboard] radarul a esuat, revin la lista "
                           "clasica: %s", exc)
    return _collect_legacy(predictions)


def _radar_activ() -> bool:
    """Singurul punct de I/O din modul. Orice eroare de citire înseamnă
    „stins" — un flag necitit nu activează niciodată nimic (North Star #3)."""
    try:
        from value_selector_config import is_enabled
        return is_enabled()
    except Exception as exc:
        logger.warning("[ValueDashboard] flagul radarului nu a putut fi citit "
                       "(raman pe lista clasica): %s", exc)
        return False


# ── Calea moștenită ──────────────────────────────────────────────────────────

def _collect_legacy(predictions: list) -> list[ValueBetRow]:
    """Extrage toate value bets deja calculate din `predictions` (listă de
    MatchPrediction, `None` ignorat — meciuri care au eșuat la analiză),
    sortate descrescător după edge_pct. Nu aplică niciun prag nou — pragul
    (`value_bet_threshold_pct`) a fost deja aplicat de evaluate_match()."""
    rows: list[ValueBetRow] = []
    for pred in predictions:
        if pred is None:
            continue
        for vb in (pred.value_bets or []):
            selection = vb.get("selection", "?")
            rows.append(ValueBetRow(
                fixture_id=pred.fixture_id, home_team=pred.home_team, away_team=pred.away_team,
                league=pred.league, kickoff_utc=pred.kickoff_utc,
                market=vb.get("market", "1X2"), selection=selection,
                edge_pct=float(vb.get("edge_pct", 0.0)), model_prob_pct=float(vb.get("model_prob_pct", 0.0)),
                bk_odds=float(vb.get("bk_odds", 0.0)), rating=vb.get("rating", ""),
                kelly_stake=(pred.kelly_stakes or {}).get(selection),
            ))
        for vb in (pred.special_value_bets or []):
            rows.append(ValueBetRow(
                fixture_id=pred.fixture_id, home_team=pred.home_team, away_team=pred.away_team,
                league=pred.league, kickoff_utc=pred.kickoff_utc,
                market=vb.get("market", "?"), selection=vb.get("market", "?"),
                edge_pct=float(vb.get("edge_pct", 0.0)), model_prob_pct=float(vb.get("model_prob_pct", 0.0)),
                bk_odds=float(vb.get("bk_odds", 0.0)), rating=vb.get("rating", ""),
                kelly_stake=None,
            ))
    rows.sort(key=lambda r: r.edge_pct, reverse=True)
    return rows


# ── Calea de radar (ADR-071 §17) ─────────────────────────────────────────────

def collect_radar_bets(predictions: list, policy) -> list[ValueBetRow]:
    """Cel mult `policy.top_n_matches` meciuri pe zi, unul per meci. Funcție
    pură: politica e injectată, nu citită din configurație.

    Ordinea e cea produsă de selector (`rank_in_day`), NU sortarea după edge
    relativ — exact mecanismul care scotea outsiderii deasupra (ADR-071 §2).
    Edge-ul relativ rămâne afișat, ca diagnostic.

    Piețele speciale (Over/Under, BTTS) NU apar aici: sunt în afara scopului
    V1 (ADR-071 §12), iar câteva rânduri de piețe speciale ar dilua o listă de
    cinci meciuri. Rămân o fază separată, nu o omisiune."""
    from value_selector import select_by_day
    from value_selector_adapter import candidates_from_prediction

    dupa_fixture = {}
    candidaturi = []
    for pred in predictions:
        if pred is None:
            continue
        ale_meciului = candidates_from_prediction(pred)
        if not ale_meciului:
            continue  # piață incompletă — nicio candidatură parțială
        dupa_fixture[str(getattr(pred, "fixture_id", ""))] = pred
        candidaturi.extend(ale_meciului)

    rows: list[ValueBetRow] = []
    for _zi_grup, rezultat in select_by_day(candidaturi, policy).items():
        for ales in rezultat.top:
            candidat = ales.candidate
            pred = dupa_fixture.get(candidat.fixture_id)
            if pred is None:
                continue
            rows.append(ValueBetRow(
                fixture_id=candidat.fixture_id,
                home_team=getattr(pred, "home_team", ""),
                away_team=getattr(pred, "away_team", ""),
                league=candidat.league,
                kickoff_utc=candidat.kickoff_utc,
                market=candidat.market,
                selection=candidat.selection_label,
                edge_pct=round(ales.metrics.e_rel_pct, 2),
                model_prob_pct=round(candidat.model_p * 100.0, 2),
                bk_odds=candidat.bk_odds,
                # Diferența absolută față de piață, în puncte procentuale — mărimea
                # pe care ADR-071 §2 o pune în locul edge-ului relativ. Nu e o notă
                # de valoare, e cât de mult se abate modelul de la cotă.
                rating=f"{ales.metrics.e_abs_pp:+.1f} pp vs piață",
                # Invariantul de radar: niciodată mărime de miză (ADR-071 §17).
                kelly_stake=None,
            ))
    return rows


# ── Radarul citit din shadow (ADR-071 §18) ───────────────────────────────────

SHADOW_TABLE = "value_selector_shadow"


@dataclass
class RadarZi:
    """Rezultatul unei citiri de radar pentru o zi, paginat.

    `total_meciuri` e numărul de meciuri CALIFICATE — cele care au trecut toate
    porțile — nu numărul de meciuri ale zilei. Ecranul îl afișează ca să se
    vadă cât mai e de răsfoit, și ca „încă 5" să nu pară nesfârșit."""
    randuri: list[ValueBetRow]
    calculat_la: str
    total_meciuri: int
    pagina: int
    pagini: int


def radar_din_shadow(zi_iso: str, *, pagina: int = 0,
                     marime: int = 5) -> RadarZi | None:
    """Radarul unei zile, citit din `value_selector_shadow` — calculat deja de
    colectorul de noapte, nu recalculat acum.

    `None` înseamnă „nu am ce servi": radar inactiv, fără client Supabase, fără
    rânduri pentru ziua cerută, sau orice eroare de citire. Apelantul cade
    atunci pe calculul live, care rămâne neschimbat — un ecran gol ar fi mai
    rău decât unul lent.

    **Paginarea nu coboară niciodată ștacheta.** Pagina 2 conține exact
    meciurile care au trecut TOATE porțile și au fost tăiate doar de plafonul
    de 5 (`outranked_top_n`) — nu candidați respinși, readuși ca să umple
    pagina. Când setul calificat se termină, se revine la prima pagină; nu se
    inventează sugestii.

    Ordinea reproduce fidel `value_selector._sort_key`: scor descrescător,
    apoi valoare absolută descrescătoare, apoi identitate stabilă. De aceea
    pagina 2 înseamnă cu adevărat „locurile 6-10", nu un alt set arbitrar.

    Se servește rularea CEA MAI RECENTĂ care acoperă ziua, nu prima. Diferență
    deliberată față de §16, care guvernează EVALUAREA: acolo prima apariție e
    singura necontaminată de mișcarea pieței; aici utilizatorul are nevoie de
    cotele cele mai proaspete.

    Strict READ-ONLY: două `SELECT`-uri, zero scrieri."""
    if not _radar_activ():
        return None
    try:
        from database.queries import get_client
        from value_selector_config import build_policy

        client = get_client()
        if client is None:
            return None

        policy_id = build_policy().policy_id
        randuri = (
            client.table(SHADOW_TABLE)
            .select("run_id,fixture_id,league,kickoff_utc,market,selection_code,"
                    "model_probability,fair_probability,bk_odds,relative_edge_pct,"
                    "absolute_edge_pp,actionability_score,selected_top,rejection_reasons")
            .eq("policy_id", policy_id)
            .gte("kickoff_utc", f"{zi_iso}T00:00:00")
            .lt("kickoff_utc", f"{zi_iso}T23:59:59.999999")
            .execute()
        ).data or []
        if not randuri:
            return None

        # O zi poate fi acoperită de mai multe rulări (fereastra colectorului e
        # de 24h, deci se suprapune). Se păstrează doar cea mai recentă.
        ultima = max(str(r.get("run_id") or "") for r in randuri)
        randuri = [r for r in randuri if str(r.get("run_id") or "") == ultima]

        calificate = [r for r in randuri
                      if r.get("selected_top")
                      or "outranked_top_n" in (r.get("rejection_reasons") or [])]
        if not calificate:
            return None

        calificate.sort(key=lambda r: (
            -float(r.get("actionability_score") or 0.0),
            -float(r.get("absolute_edge_pp") or 0.0),
            str(r.get("fixture_id") or ""),
            str(r.get("selection_code") or ""),
        ))
        # Un meci apare o singură dată, oricâte selecții ale lui s-ar califica —
        # invariantul „o selecție per meci" al politicii (ADR-071 §9).
        vazute: set[str] = set()
        unice = []
        for r in calificate:
            fid = str(r.get("fixture_id") or "")
            if fid in vazute:
                continue
            vazute.add(fid)
            unice.append(r)

        marime = max(1, int(marime))
        pagini = max(1, (len(unice) + marime - 1) // marime)
        pagina = int(pagina) % pagini          # se reia de la capăt, nu se blochează
        felie = unice[pagina * marime:(pagina + 1) * marime]

        echipe = _echipe_pentru(client, [str(r["fixture_id"]) for r in felie])
        etichete = {"1": "Home Win", "X": "Draw", "2": "Away Win"}

        iesire: list[ValueBetRow] = []
        for r in felie:
            gazda, oaspete = echipe.get(str(r["fixture_id"]), ("", ""))
            iesire.append(ValueBetRow(
                fixture_id=str(r["fixture_id"]),
                home_team=gazda, away_team=oaspete,
                league=str(r.get("league") or ""),
                kickoff_utc=str(r.get("kickoff_utc") or ""),
                market=str(r.get("market") or "1X2"),
                selection=etichete.get(str(r.get("selection_code")), "?"),
                edge_pct=round(float(r.get("relative_edge_pct") or 0.0), 2),
                model_prob_pct=round(float(r.get("model_probability") or 0.0) * 100.0, 2),
                bk_odds=float(r.get("bk_odds") or 0.0),
                rating=f"{float(r.get('absolute_edge_pp') or 0.0):+.1f} pp vs piață",
                # Invariantul de radar (ADR-071 §17): niciodată mărime de miză.
                kelly_stake=None,
            ))
        return RadarZi(randuri=iesire, calculat_la=ultima, total_meciuri=len(unice),
                       pagina=pagina, pagini=pagini)
    except Exception as exc:
        logger.warning("[ValueDashboard] radarul din shadow nu a putut fi citit "
                       "(cad pe calculul live): %s", exc)
        return None


def _echipe_pentru(client, fixture_ids: list[str]) -> dict[str, tuple[str, str]]:
    """`fixture_id` -> (gazdă, oaspete), citite din `match_history`.

    De ce o interogare în plus și nu despicarea lui `match_label`: eticheta e
    „Gazdă - Oaspete", dar numele de echipe conțin ele însele liniuțe —
    „Beveren - Oud-Heverlee Leuven" e un caz real din date. O despicare pe
    separator ar produce tăcut echipe greșite."""
    if not fixture_ids:
        return {}
    iesire: dict[str, tuple[str, str]] = {}
    unice = sorted(set(fixture_ids))
    for start in range(0, len(unice), 200):
        felie = unice[start:start + 200]
        randuri = (
            client.table("match_history")
            .select("fixture_id,home_team,away_team")
            .in_("fixture_id", felie)
            .execute()
        ).data or []
        for r in randuri:
            iesire[str(r.get("fixture_id"))] = (str(r.get("home_team") or ""),
                                                str(r.get("away_team") or ""))
    return iesire


# ── Afișarea orei ────────────────────────────────────────────────────────────

FUS_ORAR_AFISARE = "Europe/Bucharest"


def ora_locala(kickoff: str, fus: str = FUS_ORAR_AFISARE) -> str:
    """`HH:MM` în fusul de afișare, dintr-un marcaj ISO.

    Datele sunt corecte în bază — stocate în UTC — dar ecranul le arăta ca
    atare, fără etichetă, iar un meci de la 15:30 ora României apărea ca 12:30.
    Nu era o eroare de date, ci una de citire: raportată ca „ora de începere
    greșită", pentru că exact așa arăta.

    Acceptă și marcaje cu fus explicit (`...+00:00`), și naive — pe cele naive
    le tratează ca UTC, ceea ce e adevărat pentru tot ce scrie pipeline-ul.
    Orice intrare pe care nu o poate interpreta întoarce `"TBA"`: mai bine
    spune „nu știu" decât să afișeze o oră inventată (Regula #8)."""
    from datetime import datetime, timezone

    text = (kickoff or "").strip()
    if len(text) < 16:
        return "TBA"
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return "TBA"
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        return moment.astimezone(ZoneInfo(fus)).strftime("%H:%M")
    except Exception:
        # Fus indisponibil (bază de date de fusuri lipsă în imagine): se arată
        # ora UTC, corectă, în loc să cadă ecranul.
        return moment.astimezone(timezone.utc).strftime("%H:%M")
