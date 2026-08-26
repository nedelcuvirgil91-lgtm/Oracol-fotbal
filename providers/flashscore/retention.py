"""
================================================================================
FOOTBALL ORACLE — Retenție Foundation Data Layer (ADR-069)
================================================================================
Module: providers/flashscore/retention.py

DE CE EXISTĂ, SEPARAT DE `season_cleanup.py`. ADR-044 a stabilit politica —
6 sezoane, cel curent plus 5 istorice — iar `season_cleanup.py` o calculează
grupând pe coloana `season`. Măsurat pe producție (2026-08-26), acea cheie nu
poate acționa niciodată: `flashscore_match_context` are `season = NULL` pe toate
cele 12.573 de rânduri, iar completarea coloanei s-a dovedit onestă doar în
proporție de 29,6% (restul: amicale, care NU aparțin unui sezon, plus rânduri
fără corespondent canonic).

ADR-069 mută cheia pe **data REALĂ a rândului**, păstrând numărătoarea pe
SEZOANE (decizie explicită a proprietarului produsului: un sezon iese întreg
sau deloc, niciodată tăiat la mijloc de an calendaristic).

`season_cleanup.py` rămâne neatins — raportul lui despre distribuția sezoanelor
e în continuare informativ și onest. Acest modul nu-l înlocuiește, îi adaugă
mecanismul care poate efectiv acționa.

CE NU FOLOSEȘTE, DELIBERAT: `captured_at`. Un rând capturat pe 2026-07-30
descrie un meci din 1967 — `captured_at` spune când am văzut NOI pagina, nu la
ce sezon aparține faptul. Retenția pe `captured_at` ar șterge după vechimea
colectării noastre, complet nelegat de vechimea meciului.

SCOPE, moștenit neschimbat din ADR-044: EXCLUSIV tabelele Foundation Data
Layer. NICIODATĂ `match_history`/`match_events`/`player_match_stats` (istoricul
ML, cu adâncimea lui deliberată), NICIODATĂ `odds_history` (Frozen, ADR-005/
006/010).

ȘTERGEREA PORNEȘTE STINSĂ (North Star #3) — `fdl_retention_delete_enabled`,
absent implicit din `model_config`.
================================================================================
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

logger = logging.getLogger("FootballOracle.Flashscore.Retention")

# Moștenit din ADR-044, neschimbat de ADR-069: sezonul curent + 5 istorice.
RETENTION_SEASON_COUNT = 6

FLAG_DELETE_ENABLED = "fdl_retention_delete_enabled"

# ADR-069, decizia 1 — data care decide, per tabelă. Tabelele absente de aici
# NU au retenție: `flashscore_raw_extraction` are data doar în slug-ul
# `match_ref`, iar `flashscore_standings_snapshot` e un snapshot al
# clasamentului curent și nu descrie un meci. Ambele cer decizie proprie, nu
# una moștenită tacit (ADR-069, decizia 5).
RETENTION_DATE_SOURCES: dict[str, str] = {
    "flashscore_match_context": "meeting_date",
}

# ADR-069, decizia 5 — ștergerea se rulează întâi și numai pe tabela care are
# efectiv ce șterge. Celelalte cinci tabele Foundation Data Layer conțin
# exclusiv sezonul curent (cel mai vechi meci descris: 2026-07-14, verificat
# live) — cod de ștergere pentru ele ar fi cod care nu se execută niciodată.
RETENTION_DELETE_SCOPE: tuple[str, ...] = ("flashscore_match_context",)


# ── nucleu pur, fără I/O ─────────────────────────────────────────────────────

def _minus_years(d: date, years: int) -> date:
    """29 februarie minus N ani nu există în anii nebisecți. Se coboară la 28
    februarie — direcția SIGURĂ: pragul devine cu o zi mai VECHI, deci se
    păstrează un rând în plus, niciodată se șterge unul în plus."""
    try:
        return d.replace(year=d.year - years)
    except ValueError:
        return d.replace(year=d.year - years, day=28)


def compute_retention_threshold(
    season_starts: list[str], seasons_kept: int = RETENTION_SEASON_COUNT,
) -> str | None:
    """Pragul de retenție, ancorat în date REALE (ADR-069, decizia 3).

    `season_starts` = `competition_season.start_date` pentru sezonul curent al
    fiecărei competiții urmărite (ADR-067) — starturi OBSERVATE de pe hub-ul
    Flashscore, nu o regulă calendaristică inventată.

    Pragul = **cel mai devreme start observat, minus (seasons_kept - 1) ani**.
    Un rând mai vechi decât atât e în afara ferestrei de retenție în ORICE
    competiție urmărită, nu doar în a lui — de aceea nu e nevoie de o hartă
    cod->competiție pentru cele 51 de coduri distincte din
    `flashscore_match_context`, și nu se aproximează apartenența niciunui rând
    la vreun sezon (North Star #8).

    Conservatorism deliberat (ADR-069, decizia 4): rândurile dintre acest prag
    global și pragul propriu al competiției lor rămân neatinse. Costul măsurat
    pe producție: 40 de rânduri din 12.573.

    Fără niciun start de sezon cunoscut întoarce `None` — „nu știu unde e
    pragul" NU degenerează niciodată într-un prag implicit; fără prag, nimic nu
    devine candidat la ștergere."""
    if seasons_kept < 1:
        raise ValueError("seasons_kept trebuie sa fie >= 1")
    valide: list[date] = []
    for s in season_starts:
        if not s:
            continue
        try:
            valide.append(date.fromisoformat(str(s)[:10]))
        except ValueError:
            logger.warning("[Retention] start de sezon neparsabil, ignorat: %r", s)
    if not valide:
        return None
    return _minus_years(min(valide), seasons_kept - 1).isoformat()


def partition_by_retention(
    rows: list[dict], threshold: str | None, date_key: str,
) -> dict[str, list[dict]]:
    """Împarte rândurile în (candidati, pastrate, fara_data) — funcție pură.

    `fara_data` e o categorie PROPRIE, niciodată contopită cu vreuna dintre
    celelalte: un rând fără dată are vechime NECUNOSCUTĂ, iar necunoscutul nu
    se aproximează și cu atât mai puțin nu se șterge (North Star #8). Măsurat:
    311 rânduri din 12.573 sunt în această situație.

    `threshold = None` (niciun calendar cunoscut) => zero candidați. Absența
    reperului nu autorizează nicio ștergere."""
    candidati: list[dict] = []
    pastrate: list[dict] = []
    fara_data: list[dict] = []
    for r in rows:
        brut = r.get(date_key)
        if not brut:
            fara_data.append(r)
            continue
        d = str(brut)[:10]
        try:
            date.fromisoformat(d)
        except ValueError:
            # O dată neparsabilă e tot o vechime necunoscută, nu una veche.
            fara_data.append(r)
            continue
        if threshold is not None and d < threshold:
            candidati.append(r)
        else:
            pastrate.append(r)
    return {"candidati": candidati, "pastrate": pastrate, "fara_data": fara_data}


def verify_integrity(
    inainte: int, sterse: int, dupa: int, fara_data_inainte: int, fara_data_dupa: int,
) -> dict[str, Any]:
    """Integrity Check — pasul 6 din fluxul ADR-044, funcție pură.

    Două invariante, verificate separat ca să spună lucruri DIFERITE când cad:
      1. aritmetica: `dupa == inainte - sterse` — s-a șters exact ce trebuia,
         nici un rând în plus prins de un filtru prea larg;
      2. rândurile fără dată sunt INTACTE — clasa protejată n-a fost atinsă.

    Întoarce raport, nu bool: un `False` fără motiv nu spune nimănui ce s-a
    stricat (North Star #9)."""
    asteptat = inainte - sterse
    aritmetica_ok = dupa == asteptat
    protejate_ok = fara_data_dupa == fara_data_inainte
    return {
        "ok": aritmetica_ok and protejate_ok,
        "aritmetica_ok": aritmetica_ok,
        "randuri_protejate_intacte": protejate_ok,
        "randuri_inainte": inainte,
        "randuri_sterse": sterse,
        "randuri_dupa": dupa,
        "randuri_dupa_asteptat": asteptat,
        "fara_data_inainte": fara_data_inainte,
        "fara_data_dupa": fara_data_dupa,
    }


# ── I/O ──────────────────────────────────────────────────────────────────────

def delete_enabled() -> bool:
    """`fdl_retention_delete_enabled` din `model_config`. IMPLICIT `False` —
    North Star #3, niciun flag nou nu pornește activ.

    Fallback-ul la eroare e tot `False`, spre deosebire de
    `discovery_live_cascade_enabled` (ADR-063, fallback `True`): acolo
    degradarea tăcută ar fi însemnat MAI PUȚINE meciuri descoperite; aici ar
    însemna ȘTERGERE pe o citire de config eșuată. Direcția sigură e opusă."""
    try:
        from supabase_client import load_config
        valoare = load_config(default={}).get(FLAG_DELETE_ENABLED)
        return valoare is True
    except Exception as exc:
        logger.warning("[Retention] citirea %s a esuat, stergerea ramane OPRITA: %s",
                       FLAG_DELETE_ENABLED, exc)
        return False


def load_season_starts() -> list[str]:
    """`competition_season.start_date` — starturile REALE observate (ADR-067).
    O eroare întoarce listă goală, ceea ce duce la prag `None`, ceea ce duce la
    zero candidați: lanțul degradează spre a NU șterge."""
    try:
        from database.queries import get_client
        client = get_client()
        if client is None:
            return []
        res = client.table("competition_season").select("start_date").execute()
        return [r["start_date"] for r in (res.data or []) if r.get("start_date")]
    except Exception as exc:
        logger.warning("[Retention] citirea calendarelor a esuat: %s", exc)
        return []


def build_retention_report(tables: tuple[str, ...] | None = None) -> dict[str, Any]:
    """Discovery + Validation + Cleanup Report (pașii 1-3 din ADR-044), pe
    cheia de dată din ADR-069. STRICT read-only — nicio ștergere aici,
    indiferent de flag."""
    from database.queries import get_client

    tinte = tables if tables is not None else tuple(RETENTION_DATE_SOURCES)
    raport: dict[str, Any] = {
        "generat_la": datetime.now().astimezone().isoformat(),
        "politica": f"{RETENTION_SEASON_COUNT} sezoane (curent + {RETENTION_SEASON_COUNT - 1} istorice)",
        "cheie": "data reala a randului (ADR-069), niciodata `season`, niciodata `captured_at`",
        "tabele": {},
        "tabele_esuate": [],
        "delete_activat": delete_enabled(),
        "delete_executat": False,
    }

    starts = load_season_starts()
    prag = compute_retention_threshold(starts)
    raport["starturi_de_sezon_cunoscute"] = len(starts)
    raport["prag"] = prag
    if prag is None:
        raport["nota"] = ("niciun start de sezon cunoscut — fara reper nu exista "
                          "candidati, niciodata un prag implicit")

    client = get_client()
    if client is None:
        raport["error"] = "supabase_unavailable"
        return raport

    for tabela in tinte:
        cheie = RETENTION_DATE_SOURCES.get(tabela)
        if not cheie:
            continue
        try:
            res = client.table(tabela).select(f"id,{cheie}").execute()
            randuri = res.data or []
        except Exception as exc:
            logger.warning("[Retention] %s: interogare esuata, exclusa din raport: %s", tabela, exc)
            raport["tabele_esuate"].append(tabela)
            continue
        p = partition_by_retention(randuri, prag, cheie)
        raport["tabele"][tabela] = {
            "cheie_de_data": cheie,
            "total": len(randuri),
            "candidati": len(p["candidati"]),
            "pastrate": len(p["pastrate"]),
            "fara_data": len(p["fara_data"]),
            "id_uri_candidate": [r["id"] for r in p["candidati"] if r.get("id") is not None],
        }
    return raport


def execute_retention(
    dry_run: bool = True, tables: tuple[str, ...] = RETENTION_DELETE_SCOPE,
) -> dict[str, Any]:
    """Fluxul complet ADR-044: Discovery -> Validation -> Cleanup Report ->
    Backup -> Delete -> Integrity Check -> Final Report.

    TREI porți independente înainte de orice `DELETE`, toate trebuie deschise:
      1. `dry_run=False` — cerut explicit de apelant;
      2. `fdl_retention_delete_enabled is True` în `model_config`;
      3. backup-ul a REUȘIT — un backup eșuat oprește ștergerea, nu o
         însoțește cu un avertisment.

    Poarta 3 e cea care lipsește cel mai des din implementările de retenție:
    fără ea, prima ștergere pe care ai vrea s-o poți întoarce e exact cea
    pentru care n-ai backup."""
    raport = build_retention_report(tables=tables)
    raport["dry_run"] = dry_run

    if dry_run:
        raport["motiv_fara_stergere"] = "dry_run"
        return raport
    if not raport.get("delete_activat"):
        raport["motiv_fara_stergere"] = f"{FLAG_DELETE_ENABLED} nu e activat"
        return raport
    if not any(t.get("candidati") for t in raport["tabele"].values()):
        raport["motiv_fara_stergere"] = "niciun candidat"
        return raport

    from providers.flashscore.backup import run_backup
    backup = run_backup()
    raport["backup"] = backup
    if not backup.get("ok"):
        raport["motiv_fara_stergere"] = "backup esuat — stergerea NU se executa fara el"
        return raport

    from database.queries import get_client
    client = get_client()
    if client is None:
        raport["motiv_fara_stergere"] = "supabase_unavailable"
        return raport

    for tabela, info in raport["tabele"].items():
        ids = info.get("id_uri_candidate") or []
        if not ids:
            continue
        cheie = RETENTION_DATE_SOURCES[tabela]
        try:
            inainte = len(client.table(tabela).select("id").execute().data or [])
            fara_data_inainte = info["fara_data"]
            # Stergere pe ID-uri EXPLICITE, niciodata pe conditia de data.
            # Filtrul a fost deja evaluat si raportat mai sus; re-evaluarea lui
            # in DELETE ar putea prinde randuri aparute intre timp, pe care
            # nimeni nu le-a vazut in raport si care nu sunt in backup.
            client.table(tabela).delete().in_("id", ids).execute()
            dupa_randuri = client.table(tabela).select(f"id,{cheie}").execute().data or []
            dupa = len(dupa_randuri)
            fara_data_dupa = len([r for r in dupa_randuri if not r.get(cheie)])
        except Exception as exc:
            logger.error("[Retention] %s: stergere esuata: %s", tabela, exc)
            info["stergere"] = {"ok": False, "error": str(exc)}
            continue
        info["stergere"] = {"ok": True, "randuri_vizate": len(ids)}
        info["integritate"] = verify_integrity(
            inainte=inainte, sterse=len(ids), dupa=dupa,
            fara_data_inainte=fara_data_inainte, fara_data_dupa=fara_data_dupa,
        )
        raport["delete_executat"] = True

    return raport
