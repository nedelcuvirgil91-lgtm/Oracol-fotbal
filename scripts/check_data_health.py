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

CE VERIFICA (unsprezece clase distincte, fiecare cu propriul prag — numarul
creste prin decizie, nu prin construcție; cifra de aici a spus "sapte" si dupa
ce ajunsesem la zece, corectata 2026-11-02):

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

  5-6. INVERSARI DE TEREN si CLASAMENTE SUB FORMA NECANONICA — vezi
     comentariile de la fiecare clasa, in `main()`.

  7. EXTRAGEREA FLASHSCORE A INCETAT SA PRODUCA (ADR-076, adaugata
     2026-10-17) — zero randuri noi in `match_statistics_extended` /
     `player_match_stats`, desi s-au jucat meciuri. Clasa asta exista
     pentru ca lipsa ei a costat 39 de zile de tacere si 693 de meciuri
     fara xG real. Pragul e ZERO ABSOLUT, nu un procent — motivul, in
     comentariul clasei.

  11. MECIURI TERMINATE FARA STATISTICI (ADR-085, adaugata 2026-11-02) —
     meciuri jucate acum mai mult de 3 zile, in competitii urmarite, cu
     `home_shots IS NULL`. Prag ZERO ABSOLUT. Separa doua clase prin
     `referee`: NULL = Delta Sync n-a lasat Flashscore sa ajunga (ADR-085),
     prezent = extragerea e rupta (ADR-076). Au remedii DIFERITE, deci se
     raporteaza separat.

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
from collections.abc import Sequence
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

BAR = "=" * 78

# Peste acest prag, un meci trecut fara rezultat nu mai e "runda in
# desfasurare" — e fie duplicat, fie amanare cu data invechita.
STALE_DAYS = 5

BASELINE_PATH = Path(__file__).resolve().parent / "data_health_baseline.json"


# ── SEVERITATE: care constatare COLOREAZA jobul ──────────────────────────────
#
# DE CE EXISTA. `main()` intorcea `1 if findings else 0`, deci ORICARE dintre
# cele 11 clase facea jobul rosu. Masurat 2026-11-09: rosu 8 zile din 8
# (rularile 77-84, toate `schedule`, toate complete), iar pe 8 noiembrie trageau
# 5 clase — si NICIUNA nu era informatie noua: clasa 4 trage pe pauza
# internationala, iar propriul ei text spune "normal pentru competitii in
# pauza"; clasa 1 avea 1 element nou printre 27 cunoscute; clasele 8, 9 si 11
# sunt reziduuri documentate (ADR-078, ADR-075 §8, ADR-076).
#
# Consecinta e structurala, nu estetica: un cod de iesire care nu se poate
# schimba nu transporta informatie. Clasa 10 — declansatorul D-15, singura a
# carei constatare ar fi o VESTE care cere decizie umana — e inecata PRIN
# CONSTRUCTIE: un declansator ATINS ar adauga o constatare la un job deja rosu.
# Detectorul ruleaza impecabil si semnalul nu poate ajunge.
#
# E OGLINDA unui defect deja reparat aici. `night_sync` era verde prin
# constructie ("verde-mereu te antrenează sa nu te uiti") si a primit pe
# 2026-10-21 exact tiparul de mai jos. Aceeasi boala, cu semnul schimbat:
# "rosu-mereu te antreneaza sa ignori" — pe care ACEST script o are deja
# documentata despre el insusi, din 29 august, si nereparata pana acum.
#
# IMPLICIT `False`, DELIBERAT (North Star #3 aplicat la ceva ce nu e flag de
# produs): nicio clasa nu coloreaza jobul decat marcata EXPLICIT la locul ei.
# Lista creste prin DECIZIE, nu prin constructie — iar
# `tests/test_data_health_severity.py` cade daca devine majoritara, fiindca
# atunci mecanismul ar fi redevenit pe furis un `exit 1` global.
#
# CE E CRITIC AZI, ales pe datele de 8 noiembrie, nu presupus:
#   · clasa 10 — declansator de servire atins (D-15). Prin constructie se
#     numara constatare DOAR la declansare, deci nu poate deveni zgomot.
#   · clasa 11, DOAR sub-clasa `delta_sync`. Masurat: 0 azi. Un rand nou acolo
#     inseamna ca reparatia ADR-085 a regresat — veste noua. Sub-clasa
#     `extragere` (7 randuri azi, MLS septembrie) e reziduul cunoscut al penei
#     ADR-076 si NU coloreaza; cele doua au cauze si remedii OPUSE, motiv
#     pentru care clasa 11 le separa deja prin `referee`.
# Pe datele de 8 noiembrie, jobul ar fi fost VERDE — corect: nu se intamplase
# nimic nou.

def constata(registru: list[tuple[int, bool]], clasa: int, *,
             critic: bool = False) -> None:
    """Inregistreaza o constatare. `critic=True` coloreaza jobul.

    Implicit False: o clasa noua adaugata fara sa se gandeasca nimeni la
    severitate NU poate face jobul rosu din greseala."""
    registru.append((clasa, critic))


def clase_critice(registru: Sequence[tuple[int, bool]]) -> list[int]:
    """Functie PURA — ce clase CRITICE au constatat ceva.

    Pura ca sa fie testabila fara Supabase, fara retea si fara o rulare de
    productie; `night_sync.etape_critice_esuate()` are acelasi rol."""
    return sorted({clasa for clasa, critic in registru if critic})


def cod_de_iesire(registru: Sequence[tuple[int, bool]]) -> int:
    """PURA. Jobul e rosu DOAR pentru clase critice.

    O constatare necritica se RAPORTEAZA (se vede in log, integral), dar nu
    atinge culoarea — altfel am reconstrui exact `exit 1` global."""
    return 1 if clase_critice(registru) else 0


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


# ════════════════════════════════════════════════════════════════════════════
# CLASA 10 — declansatorul de servire (D-15, aprobat 2026-10-26)
#
# Praguri ca CONSTANTE, nu literale imprastiate: daca proprietarul produsului
# schimba declansatorul, se schimba intr-un loc si garda il citeste de acolo.
_PRAG_ZILE_3_DIN_3 = 10
_PRAG_N_DECLANSATOR = 500
# Zile de evaluare LIPSA tolerate in interiorul seriei. Peste atat, seria e
# SUSPECTA si nu declanseaza: altfel o pana prelungita de `night_sync` ar putea
# „conserva" o serie buna peste o perioada in care nu ne-am uitat deloc.
_MAX_ZILE_LIPSA_IN_SERIE = 2


def serie_3_din_3(randuri: list[dict]) -> list[dict]:
    """[D-15] Starea declansatorului, per Challenger. Functie PURA — nicio
    citire, niciun I/O, deci testabila fara Supabase si fara o rulare de noapte.

    Conventiile sunt cele APROBATE pe 2026-10-26 (DE_URMARIT §15), si fiecare
    exista fiindca un declansator care se poate interpreta SE VA interpreta
    exact in ziua in care e in joc:

      1. o „zi" = o data UTC cu cel putin o evaluare cu verdict; daca o data are
         MAI MULTE randuri (s-a intamplat: 17 oct, `174e7e17`), conteaza ULTIMA
         (cel mai mare `evaluated_at`);
      2. zilele LIPSA sunt NEUTRE — nu conteaza si nu reseteaza. Daca
         `night_sync` a esuat, modelul nu s-a inrautatit, doar nu ne-am uitat.
         DAR peste `_MAX_ZILE_LIPSA_IN_SERIE` goluri calendaristice in
         interiorul seriei, aceasta e marcata `suspecta` si NU declanseaza;
      3. orice zi sub 3/3 RESETEAZA seria la zero — nu se cumuleaza;
      4. `n` se cere pe ULTIMA zi a seriei (`n` creste monoton, deci acolo e
         constrangerea care leaga).

    Seria se numara de la ziua cea mai RECENTA inapoi. Distinctia nu e
    academica: pe 26 oct `dda4f7f3` avusese doua zile 3/3 (23-24 oct), dar 25
    oct le rupsese — seria CURENTA era 0, nu 2. Raportasem gresit „2 zile"
    tocmai citind „au existat doua zile" in loc de „seria curenta are doua"."""
    pe_challenger: dict[tuple[str, str], dict[date, dict]] = defaultdict(dict)
    for r in randuri:
        cheie = (r.get("algorithm_family") or "?", r.get("training_run_id") or "?")
        brut = r.get("evaluated_at") or ""
        try:
            zi = datetime.fromisoformat(str(brut).replace("Z", "+00:00")).date()
        except ValueError:
            continue
        anterior = pe_challenger[cheie].get(zi)
        # Conventia 1 — la mai multe randuri pe aceeasi zi, castiga ULTIMUL.
        if anterior is None or str(brut) > str(anterior.get("evaluated_at") or ""):
            pe_challenger[cheie][zi] = r

    iesire: list[dict] = []
    for (familie, run_id), pe_zi in pe_challenger.items():
        zile = sorted(pe_zi.keys(), reverse=True)
        if not zile:
            continue
        ultima = pe_zi[zile[0]]
        sem_ultima = _semnificative(ultima)

        serie = 0
        for zi in zile:
            if _semnificative(pe_zi[zi]) < 3:
                break          # conventia 3 — reseteaza
            serie += 1

        # Conventia 2 — goluri calendaristice in interiorul seriei.
        lipsa = 0
        if serie >= 2:
            intindere = (zile[0] - zile[serie - 1]).days + 1
            lipsa = intindere - serie
        suspecta = lipsa > _MAX_ZILE_LIPSA_IN_SERIE

        n_curent = ultima.get("n_matches_evaluated") or 0
        iesire.append({
            "algorithm_family": familie,
            "training_run_id": run_id,
            "ultima_zi": zile[0],
            "sem_ultima_zi": sem_ultima,
            "n_curent": int(n_curent),
            "serie": serie,
            "zile_lipsa": lipsa,
            "suspecta": suspecta,
            # Conventia 4 — `n` pe ULTIMA zi a seriei.
            "declansat": (serie >= _PRAG_ZILE_3_DIN_3
                          and int(n_curent) >= _PRAG_N_DECLANSATOR
                          and not suspecta),
        })
    iesire.sort(key=lambda d: (-d["serie"], -d["n_curent"]))
    return iesire


def _semnificative(rand: dict) -> int:
    """Cate dintre cele TREI metrici sunt semnificative simultan. Un camp
    lipsa/NULL conteaza ca NEsemnificativ — niciodata aproximat in favoarea
    declansarii (Regula #8, si directia conservatoare e cea corecta aici:
    greseala ieftina e sa NU declansezi, nu sa declansezi degeaba)."""
    return sum(1 for cheie in ("accuracy_significant", "brier_significant",
                               "logloss_significant")
               if rand.get(cheie) is True)


# [ADR-085 §7, etapa 4] Câte zile după fluier are voie un meci să rămână fără
# statistici înainte să fie o constatare. Măsurat, nu ales: latența reală de
# colectare în săptămânile sănătoase e 0,82 zile medie / 1,67 maxim (ADR-085
# §1.2), iar pe săptămâna 19 oct a fost 0,90 / 1,67. Trei zile lasă marjă
# pentru o rulare de noapte sărită sau întârziată de coada GitHub, fără să
# tolereze un gol real.
_PRAG_ZILE_FARA_STATISTICI = 3


def meciuri_fara_statistici(
    randuri: list[dict], azi: date, prag_zile: int = _PRAG_ZILE_FARA_STATISTICI,
) -> dict:
    """[ADR-085 §7, etapa 4] Meciuri TERMINATE, într-o competiție urmărită,
    mai vechi de `prag_zile`, rămase fără statistici (`home_shots IS NULL`).

    Funcție PURĂ — fără I/O, testabilă fără Supabase și fără o rulare de noapte,
    aceeași convenție ca `serie_3_din_3`.

    DE CE EXISTĂ CLASA: golul reparat de ADR-085 a fost **tăcut**. Nimic nu l-a
    semnalat — nici un test, nici o alertă, nici o privire pe ecran. Etapa 5 a
    lui `night_sync` raporta `ok: true` în 6 minute în loc de 15-23, fiindcă
    sărea exact meciurile care aveau nevoie de colectare. L-a găsit o întrebare
    întâmplătoare a proprietarului produsului, 7 zile mai târziu.

    Și defectul nu era unic: s-a trezit fiindcă o reparație a NOASTRĂ
    (`9202d82`, parametrul `d` al SFI) a făcut un scriitor concurent să
    funcționeze. Orice reparație viitoare la `results`, `odds_recent_results`
    sau SFI poate retrezi același tipar. Fără clasa asta, l-am descoperi din nou
    din întâmplare.

    PRAGUL E ZERO ABSOLUT, nu un procent — aceeași alegere ca la clasa 7
    (ADR-076) și pentru același motiv: un procent pe un numitor mare rămâne
    verde cât timp golul e mic, iar un gol mic care crește e exact ce vrem să
    prindem din prima zi. 23 de meciuri din 2057 sunt 1,1% — ar fi trecut
    neobservate sub orice prag procentual rezonabil.

    SEPARĂ CELE DOUĂ CLASE prin `referee`, fiindcă au cauze și remedii
    DIFERITE, iar martorul le distinge curat (verificat pe producție, ADR-085
    §1.3 și §7.1):
      - `referee IS NULL`  -> tabul summary nu a fost parsat niciodată = clasa
        ADR-085 (Delta Sync). Remediul e recolectarea.
      - `referee NOT NULL` -> summary parsat, tabul de statistici gol = clasa
        ADR-076 (extragere ruptă). Remediul e la selectori, iar recolectarea nu
        ajută.
    A le raporta împreună ar trimite pe pistă greșită exact persoana care se
    uită la raport."""
    gol_delta_sync: list[dict] = []
    gol_extragere: list[dict] = []
    for r in randuri:
        brut = (r.get("kickoff_date") or "")[:10]
        if not brut:
            continue
        try:
            zi = date.fromisoformat(brut)
        except ValueError:
            continue
        if (azi - zi).days < prag_zile:
            continue
        if r.get("home_shots") is not None:
            continue
        ținta = gol_extragere if r.get("referee") is not None else gol_delta_sync
        ținta.append({
            "league": r.get("league"),
            "kickoff_date": brut,
            "home_team": r.get("home_team"),
            "away_team": r.get("away_team"),
        })
    cheie = lambda x: (x["kickoff_date"], x["league"] or "")
    return {
        "delta_sync": sorted(gol_delta_sync, key=cheie),
        "extragere": sorted(gol_extragere, key=cheie),
        "total": len(gol_delta_sync) + len(gol_extragere),
    }


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

    from database.queries import (get_challenger_significance_days, get_client,
                                 get_supersede_without_reason,
                                 get_team_identity_drift)
    from providers.flashscore.discovery import FLASHSCORE_TRACKED_COMPETITIONS

    client = get_client()
    if client is None:
        print("EROARE: client Supabase indisponibil.")
        return 1

    season_start = "2026-07-01"
    today = date.today()
    now = datetime.now(timezone.utc)
    constatari: list[tuple[int, bool]] = []
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
        constata(constatari, 1)
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
        constata(constatari, 2)
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
        constata(constatari, 3)
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
        constata(constatari, 4)
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
        constata(constatari, 5)
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
        constata(constatari, 6)
    print(BAR)

    # ── 7. EXTRAGEREA FLASHSCORE A ÎNCETAT SĂ PRODUCĂ (ADR-076) ───────────
    #
    # Clasa asta există pentru că lipsa ei a costat 39 de zile. Extragerea
    # statisticilor a murit tăcut pe 8-9 septembrie 2026 (și a doua, roster-ul,
    # pe ~22), iar NIMIC nu a semnalat: `flashscore_data_completeness.has_stats`
    # măsoară prezența paginii descărcate, nu succesul extragerii din ea (prin
    # decizie documentată), iar în aval un dicționar gol și un meci nejucat
    # produc exact aceeași scriere — `COALESCE(existent, nou)` în RPC-ul
    # canonic. Rezultat: 693 de meciuri fără xG real, 691 dintre ele marcate
    # „acoperit", deci cu providerii de rezervă săriți (ADR-045).
    #
    # PRAGUL E ZERO ABSOLUT, DELIBERAT. Acoperirea xG variază legitim între
    # ligi (54-76% istoric), deci orice prag procentual ar fi o cifră inventată
    # de mine, care ar produce fie alarme false, fie tăcere. „Niciun rând nou,
    # deși s-au jucat meciuri" nu e ambiguu — și ar fi declanșat pe 11
    # septembrie, nu pe 17 octombrie.
    #
    # LIMITA, scrisă explicit: asta prinde o rupere TOTALĂ. O rupere parțială
    # (3 categorii din 45 redenumite) trece neobservată; instrumentul pentru
    # ea e altul, și e în afara scopului ADR-076 (§4.1).
    FEREASTRA_ZILE = 3
    # Sub atât, fereastra poate fi legitim goală (pauză internațională), deci
    # nu se afirmă nici „defect", nici „sănătos" — North Star #8.
    MIN_MECIURI_PENTRU_VERDICT = 10

    prag_zi = (today - timedelta(days=FEREASTRA_ZILE)).isoformat()
    meciuri_recente = [
        r for r in rows
        if r.get("actual_result") and (r.get("kickoff_date") or "")[:10] >= prag_zi
    ]
    SONDE = (
        ("match_statistics_extended", "captured_at", "statistici de meci"),
        ("player_match_stats", "created_at", "aliniamente/jucători"),
    )
    print(f"  7. EXTRAGEREA FLASHSCORE (ultimele {FEREASTRA_ZILE} zile)")
    print(f"     meciuri terminate în fereastră: {len(meciuri_recente)}")
    if len(meciuri_recente) < MIN_MECIURI_PENTRU_VERDICT:
        print(f"     INSUFICIENTE DATE pentru verdict (prag {MIN_MECIURI_PENTRU_VERDICT}) "
              "— nu se afirmă nici defect, nici sănătate.")
    else:
        for tabela, coloana, rol in SONDE:
            try:
                res = (client.table(tabela).select("id")
                       .gte(coloana, prag_zi).limit(1).execute())
                scrieri = len(res.data or [])
            except Exception as exc:
                print(f"     [ATENȚIE] sonda {tabela} nu a putut rula ({exc}) "
                      "— se raportează ca necunoscută.")
                continue
            if scrieri:
                print(f"     OK   {tabela} ({rol}) — scrie")
            else:
                print(f"     ⛔ ZERO rânduri noi în {tabela} ({rol}) de la {prag_zi}, "
                      f"deși s-au jucat {len(meciuri_recente)} meciuri.")
                print("        Semnătura ADR-076: extragerea nu mai potrivește "
                      "markup-ul Flashscore. Verifică log-ul pentru "
                      "'STRUCTURA SCHIMBATA'.")
                constata(constatari, 7)
    print(BAR)

    # ── 8. UN ID FLASHSCORE CU DOUĂ ETICHETE (ADR-078, Faza 0) ────────────
    #
    # Flashscore are UN identificator stabil per club (`/team/<slug>/<id>/`),
    # dar scrie etichete diferite după tipul paginii: header-ul de calificare
    # dă `Levski Sofia (BUL)`, iar widget-ul de formă recentă al ACELUIAȘI
    # provider dă `Levski Sofia`. Ancorând identitatea pe etichetă, am ajuns
    # cu 13 cluburi având două lanțuri ELO paralele și 330 de rânduri sub
    # forma cu sufix — descoperit abia pe 19 octombrie, din întrebarea
    # proprietarului produsului despre ELO-ul Borussiei, nu din vreun monitor.
    #
    # PRAGUL E ZERO ABSOLUT: un singur id cu două nume e deja răspunsul, nu un
    # indiciu. Nu există aici variație legitimă de acoperire pe care un prag
    # procentual ar trebui să o tolereze.
    #
    # LIMITA: clasa vede doar ce s-a CAPTAT. Cât timp flagul
    # `flashscore_team_identity_capture_enabled` e oprit, tabela e goală și
    # verificarea nu afirmă nimic — North Star #8, nu „sănătos".
    print("  8. IDENTITATEA DE ECHIPĂ FLASHSCORE (ADR-078)")
    try:
        total = (client.table("flashscore_team_identity")
                 .select("id", count="exact").limit(1).execute())
        randuri_captate = total.count or 0
    except Exception as exc:
        randuri_captate = None
        print(f"     [ATENȚIE] tabela nu a putut fi citită ({exc}) — "
              "se raportează ca necunoscută (migrarea 057 aplicată?).")
    if randuri_captate == 0:
        print("     INSUFICIENTE DATE — nicio etichetă captată încă "
              "(flag oprit sau prima rulare). Nu se afirmă nimic.")
    elif randuri_captate:
        drift = get_team_identity_drift()
        print(f"     etichete captate: {randuri_captate}")
        if not drift:
            print("     OK   fiecare id Flashscore apare sub exact un nume")
        else:
            print(f"     ⛔ {len(drift)} id-uri Flashscore apar sub MAI MULTE nume:")
            for d in drift[:15]:
                print(f"        {d['flashscore_team_id']} "
                      f"({d.get('team_slug') or '?'}) -> {d['nume']}")
            if len(drift) > 15:
                print(f"        … și încă {len(drift) - 15}")
            print("        Același club sub două identități: lanț ELO despicat, "
                  "H2H despicat. Vezi ADR-078.")
            constata(constatari, 8)
    print(BAR)

    # ════════════════════════════════════════════════════════════════════
    # CLASA 9 — supersedare fără motiv și fără marcaj (ADR-075 §8, 2026-10-20)
    #
    # De ce există. Cele trei rânduri placeholder Flashscore din cazul ADR-075
    # au fost marcate `superseded_by` cu `superseded_reason` ȘI `superseded_at`
    # NULL. Combinația e unică: 3 din 6742 de rânduri supersedate.
    #
    # ATENȚIE la cifră — clasa asta raportează 4, nu 3, și e corect:
    # filtrul e `superseded_reason IS NULL` (un rând scos din setul live fără
    # să spună DE CE nu e trasabil, indiferent dacă poartă marcaj de timp),
    # pe când „cele 3" din ADR sunt subsetul cu AMBELE câmpuri NULL. Al
    # patrulea (`id=130978`, Rijeka–Dinamo Zagreb) e IDENTIFICAT și benign:
    # `superseded_at = 2026-08-23 19:41:11`, supersedarea manuală documentată
    # în CLAUDE.md la unificarea formelor abreviate. Rămâne raportat oricum —
    # îi lipsește motivul scris. Vezi ADR-075 §8, „PRECIZARE 2026-10-20".
    # Verificat
    # că NIMIC din sistem nu o poate produce — `match_identity_reconciliation
    # _service._mark_superseded()` scrie mereu toate trei coloanele, iar RPC-ul
    # canonic `_upsert_match_canonical_locked` doar CITEȘTE `superseded_by`
    # (fără atribuire, fără SQL dinamic, fără `jsonb_populate_record`).
    # Singurele funcții din bază care scriu un `superseded_by` lucrează pe
    # `model_champions`, altă tabelă.
    #
    # Deci a fost o scriere din AFARA sistemului — iar singurul câmp care ar
    # fi putut-o data e exact cel NULL. Cine și când: necunoscut, și nu se
    # deduce (Regula #8).
    #
    # Clasa asta nu repară nimic retroactiv. Face următoarea astfel de
    # scriere VIZIBILĂ în loc de tăcută — direct North Star #9.
    #
    # PRAGUL E ZERO ABSOLUT: un rând scos din setul live fără să spună de ce
    # e deja o pierdere de trasabilitate, nu un indiciu statistic.
    print("  9. SUPERSEDARE FĂRĂ MOTIV (ADR-075 §8)")
    n_orfane, exemple = get_supersede_without_reason()
    if n_orfane is None:
        print("     [ATENȚIE] interogarea nu a putut fi făcută — se raportează "
              "ca NECUNOSCUTĂ, nu ca sănătoasă (Regula #8).")
    elif n_orfane == 0:
        print("     OK   fiecare rând supersedat spune de ce")
    elif n_orfane:
        print(f"     ⛔ {n_orfane} rânduri supersedate FĂRĂ `superseded_reason`:")
        for r in exemple:
            print(f"        id={r['id']} {r.get('fixture_id')} "
                  f"{r.get('home_team')} - {r.get('away_team')} "
                  f"{r.get('kickoff_date')} -> superseded_by={r.get('superseded_by')}")
        if n_orfane > len(exemple):
            print(f"        … și încă {n_orfane - len(exemple)}")
        print("        Un rând scos din setul live fără motiv nu e trasabil. "
              "Niciun scriitor din cod poate produce asta — vezi ADR-075 §8.")
        constata(constatari, 9)
    print(BAR)

    # ════════════════════════════════════════════════════════════════════
    # CLASA 10 — declanșatorul de servire (D-15, aprobat 2026-10-26)
    #
    # DE CE EXISTĂ. `xgboost_v1/dda4f7f3` bate Oracle-ul SERVIT cu +5,76pp
    # acuratețe și −0,0242 Brier (n = 330, 9 ligi din 10 nenule, fără scurgere
    # temporală — `DE_URMARIT` §15). Declanșatorul aprobat deschide discuția
    # despre un ADR pentru calea de servire: 3/3 pe 10 zile consecutive ȘI
    # n ≥ 500.
    #
    # DE CE E CABLAT AICI și nu lăsat în document. ADR-057 a trăit exact așa —
    # un declanșator scris într-un document — iar condiția lui s-a împlinit pe
    # 23 august și a fost descoperită pe 6 septembrie: 14 zile fără nicio
    # antrenare, găsite dintr-o întrebare întâmplătoare. Clasa asta e reparația
    # acelei clase de eșec, nu a unui defect de date.
    #
    # SEMANTICĂ INVERSĂ FAȚĂ DE CELELALTE NOUĂ, deliberat: aici o constatare NU
    # e un defect — e o veste bună care cere decizie umană. Raportul o spune
    # explicit, ca nimeni să nu „repare" un declanșator atins.
    #
    # PRAGUL: seria se AFIȘEAZĂ mereu (deci 0 → 7 → 10 se vede acumulând, ca
    # avertisment din timp), dar se NUMĂRĂ constatare DOAR la declanșare. Altfel
    # clasa ar fi roșie în fiecare zi în care un Challenger e la 3/3 de câteva
    # zile — exact boala „roșu-mereu te antrenează să ignori" pe care acest
    # proiect o are deja documentată la `check_data_health` însuși.
    print("  10. DECLANȘATOR DE SERVIRE (D-15) — 3/3 × "
          f"{_PRAG_ZILE_3_DIN_3} zile ȘI n ≥ {_PRAG_N_DECLANSATOR}")
    randuri_sem = get_challenger_significance_days()
    if randuri_sem is None:
        print("     [ATENȚIE] interogarea nu a putut fi făcută — se raportează "
              "ca NECUNOSCUTĂ, nu ca neatinsă (Regula #8).")
    else:
        stari = serie_3_din_3(randuri_sem)
        if not stari:
            print("     (niciun Challenger cu verdict în fereastră)")
        for s in stari:
            eticheta = f"{s['algorithm_family']}/{s['training_run_id'][:8]}"
            semn = "*** DECLANȘAT ***" if s["declansat"] else ""
            suspect = "  ⚠️ serie SUSPECTĂ (zile lipsă: " \
                      f"{s['zile_lipsa']})" if s["suspecta"] else ""
            print(f"     {eticheta:28} serie 3/3 = {s['serie']:>2} · "
                  f"azi {s['sem_ultima_zi']}/3 · n = {s['n_curent']:>4} "
                  f"({s['ultima_zi']}){semn}{suspect}")
        declansati = [s for s in stari if s["declansat"]]
        if declansati:
            print("     ⛔ DECLANȘATOR ATINS — NU e un defect. Cere decizie "
                  "umană: se deschide discuția despre un ADR pentru calea de "
                  "servire (D-15). Nimic nu pornește automat (ADR-002).")
            constata(constatari, 10, critic=True)
    print(BAR)

    # ── 11. MECIURI TERMINATE FĂRĂ STATISTICI (ADR-085, etapa 4) ────────────
    #
    # Clasa asta există pentru că golul reparat de ADR-085 a fost TĂCUT, iar
    # etapa care îl producea raporta `ok: true`. Vezi docstring-ul lui
    # `meciuri_fara_statistici` pentru motivul complet și pentru de ce pragul e
    # ZERO ABSOLUT, nu procentual.
    print(f"  11. MECIURI TERMINATE FĂRĂ STATISTICI (> {_PRAG_ZILE_FARA_STATISTICI} zile, "
          "ligi urmărite) — prag ZERO")
    try:
        from providers.flashscore.discovery import (
            FLASHSCORE_TRACKED_COMPETITIONS as _TRACKED,
        )
        prag_data = (date.today() - timedelta(days=90)).isoformat()
        randuri_stat = _fetch_all(
            client, "match_history",
            "id,league,kickoff_date,home_team,away_team,home_shots,referee",
            lambda q: (q.gte("kickoff_date", prag_data)
                        .not_.is_("actual_result", "null")
                        .in_("league", list(_TRACKED))),
        )
    except Exception as exc:
        randuri_stat = None
        logger.warning("[Health] clasa 11 — interogarea a eșuat: %s", exc)
    if randuri_stat is None:
        print("     [ATENȚIE] interogarea nu a putut fi făcută — se raportează "
              "ca NECUNOSCUTĂ, nu ca zero (Regula #8).")
    else:
        gol = meciuri_fara_statistici(randuri_stat, date.today())
        print(f"     verificate: {len(randuri_stat)} meciuri terminate, "
              f"{len(_TRACKED)} competiții urmărite, fereastră 90 zile")
        if gol["total"] == 0:
            print("     ✅ ZERO meciuri fără statistici.")
        else:
            for eticheta, lista, explicatie in (
                ("DELTA SYNC (ADR-085)", gol["delta_sync"],
                 "summary NEparsat (`referee` NULL) — Flashscore n-a ajuns "
                 "niciodată la meci. Remediul: recolectare "
                 "(`--recover-missing-stats`)."),
                ("EXTRAGERE (ADR-076)", gol["extragere"],
                 "summary parsat, tab de statistici GOL (`referee` prezent) — "
                 "recolectarea NU ajută; se verifică selectorii."),
            ):
                if not lista:
                    continue
                print(f"     ⛔ {len(lista)} × {eticheta} — {explicatie}")
                for m in lista[:10]:
                    print(f"        {m['kickoff_date']}  [{m['league']}]  "
                          f"{m['home_team']} – {m['away_team']}")
                if len(lista) > 10:
                    print(f"        … și încă {len(lista) - 10}")
            # Critic DOAR pe `delta_sync`: un rand nou acolo inseamna ca
            # reparatia ADR-085 a regresat. `extragere` e reziduul cunoscut
            # al penei ADR-076 — se raporteaza, nu coloreaza.
            constata(constatari, 11, critic=bool(gol["delta_sync"]))
    print(BAR)

    critice = clase_critice(constatari)
    print(f"  Clase cu constatări: {len(constatari)}/11")
    if critice:
        print(f"  ⛔ CLASE CRITICE cu constatări: {critice}")
        print("     Jobul e ROȘU din cauza LOR, nu a celorlalte. Cere decizie.")
    else:
        print("  ✅ Nicio clasă CRITICĂ — jobul rămâne VERDE.")
        print("     Constatările de mai sus, dacă există, sunt reziduuri cunoscute:")
        print("     se raportează integral, dar nu colorează. Vezi §SEVERITATE.")
    print("  Verificare încheiată. ZERO scriere efectuată.")
    print(BAR)
    return cod_de_iesire(constatari)


if __name__ == "__main__":
    raise SystemExit(main())
