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

BASELINE_PATH = Path(__file__).resolve().parent / "data_health_baseline.json"


def load_baseline(path: Path | None = None) -> dict:
    """Constatarile deja intelese, cu motivul fiecareia — vezi
    `data_health_baseline.json`. Fisier lipsa sau corupt => dictionar gol:
    monitorizarea degradeaza spre a raporta TOT, niciodata spre a tace.
    Un monitor care tace din cauza unei erori de configurare e mai rau decat
    unul zgomotos."""
    p = path or BASELINE_PATH
    try:
        import json
        date_ = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"  [ATENTIE] linia de baza nu a putut fi citita ({p.name}: {exc}) — "
              f"se raporteaza TOATE constatarile.")
        return {}
    return {k: v for k, v in date_.items() if not k.startswith("_")}


def split_known(randuri: list[dict], baseline_clasa: dict) -> tuple[list[dict], list[dict]]:
    """Imparte constatarile in (NOI, CUNOSCUTE), dupa `fixture_id` — functie
    pura. Doar cele NOI ridica alarma; cele cunoscute raman afisate integral,
    cu motivul lor, ca sa nu dispara din vedere (North Star #9)."""
    noi, cunoscute = [], []
    for r in randuri:
        (cunoscute if r.get("fixture_id") in baseline_clasa else noi).append(r)
    return noi, cunoscute

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


def build_home_stadiums(
    rows: list[dict], min_dovezi: int = 2, raport_dominanta: float = 2.0,
) -> dict[str, str]:
    """Stadionul „de acasă" al fiecărei echipe, dedus empiric — FUNCȚIE PURĂ.

    E cel mai frecvent stadion din meciurile în care echipa e gazdă, dar DOAR
    dacă e și DOMINANT. Două condiții, ambele obligatorii:

    - `min_dovezi` — cel puțin atâtea meciuri pe acel stadion. O singură
      apariție ar putea fi chiar rândul inversat pe care îl căutăm.
    - `raport_dominanta` — de câte ori trebuie să depășească stadionul
      următorul clasat. Exprimă direct „clar dominant, nu doar cel mai
      frecvent". Un prag pe PROCENT a fost încercat întâi și respins: chiar
      rândul inversat contribuie la numărătoarea gazdei și îi coboară ponderea
      sub prag, făcând cazul indetectabil — dovada se autosabota. Raportul e
      robust la asta, pentru că +1 pe locul doi contează mult mai puțin.

    [ADAUGAT 2026-08-24, la semnalarea proprietarului produsului] A doua
    condiție lipsea, iar fără ea „cel mai frecvent" nu e o dovadă de teren.
    Multe echipe joacă acasă pe stadioane diferite — verificat în date:
    FCSB (Arena Națională / Stadionul Steaua), Paris FC (Jean Bouin /
    Sébastien Charléty), Kairat Almaty (Almaty / Turkestan). Există și
    terenuri NEUTRE: PSG a jucat „acasă" la Budapesta (Supercupă), iar
    H. Beer Sheva chiar pe Giulești, în București — același stadion care e
    teren propriu pentru Rapid.

    Pentru o echipă cu 3 meciuri pe un stadion și 2 pe altul, „modalul" e o
    coincidență statistică, nu identitate. Astfel de echipe rămân în afara
    hărții — necunoscut, nu ghicit (Regula #8)."""
    frecventa: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in rows:
        echipa, stadion = r.get("home_team"), r.get("stadium")
        if echipa and stadion:
            frecventa[echipa][stadion] += 1
    rezultat: dict[str, str] = {}
    for echipa, stadioane in frecventa.items():
        ordonate = sorted(stadioane.items(), key=lambda kv: (-kv[1], kv[0]))
        stadion, n = ordonate[0]
        al_doilea = ordonate[1][1] if len(ordonate) > 1 else 0
        if n >= min_dovezi and n >= raport_dominanta * al_doilea:
            rezultat[echipa] = stadion
    return rezultat


def find_home_away_inversions(rows: list[dict], min_dovezi: int = 2) -> tuple[list[dict], int]:
    """Rânduri unde stadionul înregistrat aparține, empiric, echipei OASPETE —
    FUNCȚIE PURĂ. Întoarce (candidați, câte rânduri au putut fi judecate).

    [ADAUGAT 2026-08-23] Clasa a 5-a, după inversarea de teren Rennes-PSG:
    `normalizer._extract_team_names()` deducea gazda din ordinea DOM, iar o
    inversare contaminează ELO, formă, H2H și atribuirea xG pe părți. Aceea a
    ieșit la iveală DIN ÎNTÂMPLARE, printr-o coliziune de `fixture_id`; o
    inversare la prima și singura extragere nu declanșează nimic.

    Gardă obligatorie contra stadioanelor PARTAJATE (San Siro pentru Milan și
    Inter, Olimpico pentru Roma și Lazio): se semnalează doar dacă stadionul NU
    e și al gazdei. Fără ea, fiecare derby ar fi un fals pozitiv.

    Al doilea element din tuplu contează la fel de mult ca primul: „0 găsite"
    nu înseamnă nimic fără câte rânduri au putut fi verificate efectiv."""
    acasa = build_home_stadiums(rows, min_dovezi)
    candidati: list[dict] = []
    judecabile = 0
    for r in rows:
        stadion = r.get("stadium")
        gazda, oaspete = r.get("home_team"), r.get("away_team")
        # AMBELE echipe trebuie sa aiba teren propriu cunoscut si dominant.
        #
        # [CORECTAT 2026-08-24] Varianta anterioara cerea asta doar pentru
        # OASPETE. Daca gazda lipsea din harta, `acasa.get(gazda)` intorcea
        # None, care nu e egal cu stadionul, deci randul era SEMNALAT — adica
        # exact pe dos: se concluziona din stadion tocmai cand lipsea dovada
        # de teren pentru gazda. Un club care joaca pe stadioane diferite (sau
        # unul nou, sub prag) putea fi acuzat de inversare fara nicio baza.
        #
        # Numele raman identitatea; stadionul e cel mult indiciu coroborant,
        # si doar cand e stabil pentru ambele parti.
        if not stadion or not gazda or not oaspete:
            continue
        if gazda not in acasa or oaspete not in acasa:
            continue  # necunoscut, nu acuzatie (Regula #8)
        judecabile += 1
        if acasa[oaspete] != stadion:
            continue
        if acasa[gazda] == stadion:
            continue  # stadion partajat — nu e dovada de inversare
        candidati.append({
            "id": r.get("id"), "league": r.get("league"),
            "home_team": gazda, "away_team": oaspete,
            "stadium": stadion, "kickoff_date": (r.get("kickoff_date") or "")[:10],
            "stadion_asteptat_gazda": acasa.get(gazda),
        })
    return candidati, judecabile


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
    baseline = load_baseline()

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

    # [ADAUGAT 2026-08-25] Cele mai multe dintre aceste "fixture-uri stale" nu
    # sunt rezultate lipsa, ci meciuri AMANATE — o stare pe care modelul de
    # date nu o poate exprima azi. Verificat extern: 3 din 4 meciuri Flashscore
    # raportate erau amanate (CFR Cluj - U Cluj chiar reprogramat oficial pe 8
    # octombrie). Raportate ca "cer atentie", faceau monitorizarea permanent
    # rosie, iar un monitor permanent rosu nu mai e citit de nimeni.
    stale_noi, stale_cunoscute = split_known(stale, baseline.get("fixture_stale", {}))

    print(f"  1. FIXTURE-URI TRECUTE FĂRĂ REZULTAT")
    print(f"     recente (≤{STALE_DAYS} zile, probabil rundă în curs): {len(recent)}")
    print(f"     NOI, în competiții ACTIVE (cer atenție)           : {len(stale_noi)}")
    for r in sorted(stale_noi, key=lambda x: x.get("kickoff_date") or "")[:15]:
        print(f"       {(r.get('kickoff_date') or '')[:10]}  [{r.get('league')}]  "
              f"{r.get('home_team')} – {r.get('away_team')}  ({r.get('fixture_id')})")
    if stale_cunoscute:
        print(f"     CUNOSCUTE, cu motiv documentat (context, nu acțiune): {len(stale_cunoscute)}")
        for r in sorted(stale_cunoscute, key=lambda x: x.get("kickoff_date") or ""):
            intrare = baseline["fixture_stale"][r["fixture_id"]]
            marcaj = "✓ verificat" if intrare.get("verificat_extern") else "· neverificat"
            print(f"       {(r.get('kickoff_date') or '')[:10]}  [{r.get('league')}]  "
                  f"{r.get('home_team')} – {r.get('away_team')}  [{marcaj}]")
            print(f"           {intrare.get('motiv')}")
    if stale_incheiate:
        total_inch = sum(stale_incheiate.values())
        detalii = ", ".join(f"{lg} ({n})" for lg, n in sorted(stale_incheiate.items()))
        print(f"     în competiții ÎNCHEIATE (context, nu acțiune)     : {total_inch} — {detalii}")
    if stale_noi:
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

    # ── 5. Inversări de teren (gazdă/oaspete) ────────────────────────────
    #
    # Stadionul e populat practic doar pe rândurile Flashscore — ceea ce se
    # potrivește exact: bugul de inversare a fost al extractorului Flashscore,
    # restul corpusului nu a fost niciodată expus.
    stadion_rows = _fetch_all(
        client, "match_history", "id,league,home_team,away_team,stadium,kickoff_date",
        lambda q: q.is_("superseded_by", "null").not_.is_("stadium", "null"),
    )
    inversari, judecabile = find_home_away_inversions(stadion_rows)
    total_cu_stadion = len(stadion_rows)
    print(f"  5. INVERSĂRI DE TEREN (stadionul aparține echipei oaspete): {len(inversari)}")
    print(f"     verificabile: {judecabile} din {total_cu_stadion} rânduri cu stadion "
          f"({round(100.0 * judecabile / total_cu_stadion, 1) if total_cu_stadion else 0}%)")
    for c in inversari[:15]:
        print(f"       {c['kickoff_date']}  [{c['league']}]  {c['home_team']} – {c['away_team']}")
        print(f"          stadion: {c['stadium']!r}  ·  al gazdei ar fi: {c['stadion_asteptat_gazda']!r}")
    if inversari:
        findings += 1
        print("     (o inversare contaminează ELO, formă, H2H și atribuirea xG — "
              "verifică extern înainte de orice corecție, regula D3)")
    print(BAR)

    # ── 6. Rânduri de clasament sub formă NEcanonică ──────────────────────
    #
    # [ADĂUGAT 2026-08-26] Clasă găsită pe date reale, ca efect secundar al
    # reîmprospătării `captured_at`: 19 rânduri orfane, aceeași echipă sub
    # două nume („Heerenveen" lângă „SC Heerenveen", „Atl. Madrid" lângă
    # „Atletico Madrid"). Scrise ÎNAINTE de fixul de normalizare din
    # 2026-08-15; `UNIQUE(competition, team)` le ține separate, deci rândul
    # vechi nu se rescrie NICIODATĂ în loc — rămâne fantomă la nesfârșit,
    # cu cifre înghețate în trecut.
    #
    # Invariantul e exact și ieftin: scriitorul normalizează la fiecare
    # scriere, deci orice rând al cărui `team` diferă de forma canonică e,
    # prin construcție, un orfan. Se poate reactiva oricând se ADAUGĂ un
    # alias nou (o formă azi canonică devine mâine alias) — de aceea merită
    # monitorizat permanent, nu curățat o dată.
    #
    # [CORECTAT 2026-08-27 — defect găsit la PRIMA rulare reală a acestei
    # clase în CI] Versiunea inițială trata toate rândurile necanonice la
    # fel și afișa necondiționat „rândul canonic există separat". FALS
    # pentru cazul găsit azi: `Schalke` și `B. Monchengladbach` (Bundesliga)
    # sunt SINGURELE rânduri pentru acele echipe — nu există `Schalke 04`,
    # nu există `Borussia Monchengladbach`. Ștergerea lor, tratament corect
    # pentru cele 19 duplicate reale de ieri, ar fi ELIMINAT două echipe din
    # clasament.
    #
    # Cele două situații arată identic la detecție dar cer acțiuni OPUSE:
    #   - cu geamăn canonic  -> DUPLICAT, se șterge rândul vechi
    #   - fără geamăn        -> ÎNREGISTRARE UNICĂ sub nume greșit, se
    #                           REDENUMEȘTE; ștergerea pierde definitiv echipa
    #
    # De aceea se raportează separat, cu acțiunea recomandată per grup —
    # niciodată o singură etichetă pentru amândouă.
    duplicate: list[dict] = []
    unice: list[dict] = []
    try:
        from mappings import normalize_team_name

        standings = _fetch_all(
            client, "flashscore_standings_snapshot", "id,competition,team,captured_at",
            lambda q: q.order("id"),
        )
        # Perechile (competiție, echipă) EXISTENTE — baza pentru „are geamăn?".
        existente = {(r.get("competition"), r.get("team")) for r in standings}
        for r in standings:
            if not r.get("team"):
                continue
            canonic = normalize_team_name(r["team"])
            if canonic == r["team"]:
                continue
            if (r.get("competition"), canonic) in existente:
                duplicate.append(r)
            else:
                unice.append(r)
    except Exception as exc:
        print(f"  [ATENȚIE] clasa 6 nu a putut rula ({exc}) — se raportează ca necunoscută.")
        standings = []

    orfane = duplicate + unice
    print(f"  6. CLASAMENTE SUB FORMĂ NECANONICĂ: {len(orfane)}")
    if duplicate:
        print(f"     DUPLICATE (rândul canonic există separat) — de ȘTERS: {len(duplicate)}")
        for r in duplicate[:10]:
            print(f"       [{r.get('competition')}]  {r['team']!r} → "
                  f"{normalize_team_name(r['team'])!r}  (id={r.get('id')})")
    if unice:
        print(f"     SINGURUL rând al echipei — de REDENUMIT, NU de șters: {len(unice)}")
        for r in unice[:10]:
            print(f"       [{r.get('competition')}]  {r['team']!r} → "
                  f"{normalize_team_name(r['team'])!r}  (id={r.get('id')})")
        print("     (ștergerea acestora ar elimina echipa din clasament — "
              "nu există rând canonic care să o înlocuiască)")
    if orfane:
        findings += 1
    print(BAR)

    print(f"  Clase cu constatări: {findings}/6")
    print("  Verificare încheiată. ZERO scriere efectuată.")
    print(BAR)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
