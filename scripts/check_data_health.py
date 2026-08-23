"""
================================================================================
FOOTBALL ORACLE — Sănătatea datelor de meci (read-only, ADR-063)
================================================================================
Module: scripts/check_data_health.py

STRICT read-only. Nu scrie nimic, nicaieri.

DE CE EXISTA: toate cele patru clase de probleme de mai jos au fost gasite
2026-08-23 DIN INTAMPLARE, investigand altceva (de ce poarta Team Profile
arata 15/300). Nu exista nicio monitorizare pentru ele — deci cresteau tacut.
Acest script le face vizibile.

CE VERIFICA (patru clase distincte, fiecare cu propriul prag):

  1. FIXTURE-URI STALE — meciuri cu ora de start trecuta si fara rezultat,
     separate pe vechime. Cele recente sunt normale (runda in desfasurare);
     cele vechi sunt fie duplicate, fie meciuri amanate cu data invechita.

  2. DUPLICATE PE CHEIE NATURALA — doua randuri live pentru aceeasi
     (gazda, oaspete, zi). Reconcilierea de identitate ar trebui sa le
     prinda; ce apare aici a scapat.

  3. FORME ABREVIATE vs FORME LUNGI — clasa descoperita 2026-08-23:
     "Din. Zagreb" (Flashscore, 7 meciuri, ELO 1607) coexista cu
     "Dinamo Zagreb" (istoric, 18 meciuri, ELO 1563) — doua lanturi ELO
     paralele pentru acelasi club. Detectia D2/D3 de pana acum cerea ca
     cele doua nume sa se fi INTALNIT intr-un meci; aceste perechi nu s-au
     intalnit niciodata, deci erau invizibile.

  4. LIGI FARA DESCOPERIRE FLASHSCORE — alarma care inlocuieste plasa de
     siguranta data la o parte de ADR-063. Daca o liga urmarita nu are
     niciun meci viitor descoperit de Flashscore, trebuie sa se vada
     IMEDIAT, nu peste doua saptamani.

Utilizare:
    python scripts/check_data_health.py
Cod de iesire: 1 daca exista constatari care cer atentie umana, 0 altfel.
================================================================================
"""
from __future__ import annotations

import logging
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

BAR = "=" * 78

# Peste acest prag, un meci trecut fara rezultat nu mai e "runda in
# desfasurare" — e fie duplicat, fie amanare cu data invechita.
STALE_DAYS = 5

# Tipar de forma abreviata: un cuvant scurt urmat de punct si spatiu.
# Ex. "Din. Zagreb", "St. Mirren", "Lok. Zagreb".
_ABBREV = re.compile(r"^[A-Za-zĂÂÎȘȚăâîșț]{1,4}\. ")


def find_abbreviation_pairs(teams: list[str]) -> list[tuple[str, str]]:
    """Perechi (forma_abreviata, forma_lunga) candidate — FUNCTIE PURA.

    Regula: pentru un nume abreviat "X. Rest", cauta alt nume care se
    termina cu acelasi "Rest" SI incepe cu litera lui X. A doua conditie e
    esentiala: fara ea, "Din. Zagreb" ar fi imperecheat gresit cu
    "Lok. Zagreb" (ambele se termina in "Zagreb", dar sunt cluburi
    DIFERITE) — greseala pe care o scanare naiva chiar o face.

    Candidati, nu concluzii: fiecare pereche cere verificare umana inainte
    de orice unificare (regula D3, ADR-060)."""
    pairs: list[tuple[str, str]] = []
    for short in teams:
        m = _ABBREV.match(short or "")
        if not m:
            continue
        prefix = short[0].lower()
        rest = short[m.end():].strip().lower()
        if not rest:
            continue
        for other in teams:
            if not other or other == short:
                continue
            o = other.lower()
            if _ABBREV.match(other):
                continue  # nu imperechem doua abrevieri intre ele
            if o.endswith(rest) and o.startswith(prefix):
                pairs.append((short, other))
    return sorted(set(pairs))


def _fetch_all(client, table: str, columns: str, apply_filters) -> list[dict]:
    """Paginare cu `.order("id")` EXPLICIT inainte de `.range()` — fara
    ORDER BY, PostgREST/Postgres nu garanteaza ordine stabila intre cereri
    paginate (bug real reparat in aceasta sesiune, vezi ADR-059 Addendum)."""
    rows: list[dict] = []
    seen: set = set()
    page = 0
    while True:
        q = apply_filters(client.table(table).select(columns)).order("id")
        batch = q.range(page * 1000, page * 1000 + 999).execute()
        raw = batch.data or []
        for r in raw:
            if r.get("id") not in seen:
                seen.add(r.get("id"))
                rows.append(r)
        if len(raw) < 1000:
            break
        page += 1
    return rows


def main() -> int:
    import supabase_client as sb

    if not sb.is_available():
        print("EROARE: Supabase indisponibil (SUPABASE_URL / SUPABASE_SECRET_KEY).")
        return 1

    from database.queries import get_client
    from providers.flashscore.discovery import FLASHSCORE_TRACKED_COMPETITIONS

    client = get_client()
    if client is None:
        print("EROARE: client Supabase indisponibil.")
        return 1

    season_start = "2026-07-01"
    today = date.today()
    now = datetime.now(timezone.utc)
    findings = 0

    print(BAR)
    print("  SĂNĂTATEA DATELOR DE MECI (read-only, ADR-063)")
    print(f"  Sezon de la: {season_start}  ·  prag 'stale': {STALE_DAYS} zile")
    print(BAR)

    rows = _fetch_all(
        client, "match_history",
        "id,fixture_id,league,home_team,away_team,kickoff_date,actual_result",
        lambda q: q.is_("superseded_by", "null").gte("kickoff_date", season_start),
    )
    print(f"  Rânduri live în sezon: {len(rows)}")
    print(BAR)

    # ── 1. Fixture-uri stale ──────────────────────────────────────────────
    #
    # [CORECTAT — prima rulare reala, 2026-08-23] Competitiile INCHEIATE sunt
    # separate de cele active. Fara separare, World Cup 2026 (turneu terminat
    # in iulie) producea 19 din cele 31 de constatari — zgomot permanent, care
    # nu se va rezolva niciodata, sub care semnalul real (amanari, duplicate
    # in ligi active) ramanea ascuns. O competitie e considerata incheiata
    # daca nu mai are NICIUN meci programat in viitor.
    active_leagues = {
        r.get("league") for r in rows
        if (r.get("kickoff_date") or "")[:10] >= today.isoformat()
    }

    recent, stale, stale_incheiate = [], [], defaultdict(int)
    for r in rows:
        if r.get("actual_result") is not None:
            continue
        kd = (r.get("kickoff_date") or "")[:10]
        if not kd:
            continue
        try:
            d = datetime.strptime(kd, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if d >= now:
            continue
        if (now - d).days <= STALE_DAYS:
            recent.append(r)
        elif r.get("league") not in active_leagues:
            stale_incheiate[r.get("league")] += 1
        else:
            stale.append(r)

    print(f"  1. FIXTURE-URI TRECUTE FĂRĂ REZULTAT")
    print(f"     recente (≤{STALE_DAYS} zile, probabil rundă în curs): {len(recent)}")
    print(f"     VECHI în competiții ACTIVE (cer atenție)          : {len(stale)}")
    for r in sorted(stale, key=lambda x: x.get("kickoff_date") or "")[:15]:
        print(f"       {(r.get('kickoff_date') or '')[:10]}  [{r.get('league')}]  "
              f"{r.get('home_team')} – {r.get('away_team')}  ({r.get('fixture_id')})")
    if stale_incheiate:
        total_inch = sum(stale_incheiate.values())
        detalii = ", ".join(f"{lg} ({n})" for lg, n in sorted(stale_incheiate.items()))
        print(f"     în competiții ÎNCHEIATE (context, nu acțiune)     : {total_inch} — {detalii}")
    if stale:
        findings += 1
    print(BAR)

    # ── 2. Duplicate pe cheie naturală ───────────────────────────────────
    by_key: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        key = (r.get("home_team"), r.get("away_team"), (r.get("kickoff_date") or "")[:10])
        if all(key):
            by_key[key].append(r)
    dups = {k: v for k, v in by_key.items() if len(v) > 1}
    print(f"  2. DUPLICATE PE CHEIE NATURALĂ (gazdă, oaspete, zi): {len(dups)}")
    for k, v in list(dups.items())[:10]:
        print(f"       {k[2]}  {k[0]} – {k[1]}  ->  {[r.get('fixture_id') for r in v]}")
    if dups:
        findings += 1
    print(BAR)

    # ── 3. Forme abreviate vs forme lungi ────────────────────────────────
    #
    # [CORECTAT — prima rulare reala, 2026-08-23] Scaneaza TOT istoricul, nu
    # doar sezonul curent. Prima versiune filtra pe sezon si rata exact
    # problema pe care trebuie s-o vada: forma lunga traieste de obicei DOAR
    # in istoric (ex. "Dinamo Zagreb", 18 meciuri pana in 2025-01), iar cea
    # abreviata doar in sezonul curent ("Din. Zagreb", Flashscore). Cu filtru
    # de sezon, perechea devenea invizibila imediat ce ultimul rand istoric
    # iesea din fereastra — monitorizarea ar fi incetat sa raporteze tocmai
    # fragmentarea pe care a descoperit-o.
    #
    # Se aduc DOAR numele (2 coloane), nu randuri intregi — costul e
    # acceptabil pentru un job zilnic.
    all_name_rows = _fetch_all(
        client, "match_history", "id,home_team,away_team",
        lambda q: q.is_("superseded_by", "null"),
    )
    teams = sorted({t for r in all_name_rows for t in (r.get("home_team"), r.get("away_team")) if t})
    pairs = find_abbreviation_pairs(teams)
    print(f"  3. FORME ABREVIATE cu posibilă formă lungă: {len(pairs)}")
    print(f"     (scanat pe TOT istoricul: {len(all_name_rows)} rânduri, {len(teams)} nume distincte)")
    for short, long in pairs:
        n_s = sum(1 for r in all_name_rows if short in (r.get("home_team"), r.get("away_team")))
        n_l = sum(1 for r in all_name_rows if long in (r.get("home_team"), r.get("away_team")))
        print(f"       {short!r} ({n_s} rânduri)  vs  {long!r} ({n_l} rânduri)")
    if pairs:
        findings += 1
        print("     (candidați, NU concluzii — fiecare cere verificare umană, regula D3)")
    print(BAR)

    # ── 4. Ligi urmărite fără descoperire Flashscore ─────────────────────
    horizon = (today + timedelta(days=7)).isoformat()
    fs_future: set[str] = set()
    for r in rows:
        kd = (r.get("kickoff_date") or "")[:10]
        if not kd or kd < today.isoformat() or kd > horizon:
            continue
        if str(r.get("fixture_id") or "").startswith("flashscore_"):
            fs_future.add(r.get("league"))
    missing = sorted(set(FLASHSCORE_TRACKED_COMPETITIONS) - fs_future)
    print(f"  4. LIGI URMĂRITE FĂRĂ NICIUN MECI FLASHSCORE în următoarele 7 zile: {len(missing)}")
    for lg in missing:
        print(f"       {lg}")
    if missing:
        findings += 1
        print("     (normal pentru competiții în pauză sau neîncepute — verifică înainte de a acționa)")
    print(BAR)

    print(f"  Clase cu constatări: {findings}/4")
    print("  Verificare încheiată. ZERO scriere efectuată.")
    print(BAR)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
