"""
================================================================================
FOOTBALL ORACLE — Mappings & Normalization (v1.3)
CHANGES v1.3:
  - [FIX] Eliminate din _STRIP_SUFFIXES suffixele generice " fc", " cf",
    " united", " city" — aceeasi clasa de risc ca fuzzy-matching-ul eliminat
    in v1.2 (o echipa necunoscuta terminata in "FC"/"United"/"City" putea
    fi trunchiata gresit si coincide accidental, dupa stripping, cu un alias
    existent). Restul suffixelor (" football club", " sc", " sv", " ac",
    " bc", " afc", " fk", " sk", " bk", " if", " hk", " gd") raman
    neschimbate — risc considerat mai mic, decizie separata, neinclusa
    in acest pas.
  - _STRIP_PREFIXES ("fc ","cf ","ac ","sc ","fk ","sk ","afc ") NU a fost
    atins in acest pas. Are aceeasi clasa de risc ca suffixele de mai sus
    (ex. "FC Vreo Echipa Necunoscuta" -> "Vreo Echipa Necunoscuta" ar putea
    coincide accidental cu un alias existent), dar ramane decizie separata,
    la cerere explicita — nu s-a schimbat nimic aici deocamdata.
CHANGES v1.2:
  - [FIX] Eliminat fuzzy prefix-matching din normalize_team_name() — cauza
    coliziunii "Paris FC" -> "Paris Saint-Germain" (si a altor 140+ cazuri
    similare identificate printr-un scan sistemic). O echipa necunoscuta
    ramane acum nemodificata, in loc sa fie unita gresit cu alt club.
  - [DATA] Eliminate aliasuri single-word ambigue care se suprapuneau cu
    cluburi reale din ligile urmarite (Champions/Europa League, MLS):
    "Saudi" (era țară, nu club), "Inter" (coliziune cu Inter Miami/MLS),
    "Union" (coliziune cu Union Saint-Gilloise), "Rapid" (coliziune cu
    Rapid Wien), "Dinamo" (coliziune cu Dinamo Zagreb/Kyiv). Aliasurile
    complete si fara ambiguitate raman neschimbate.
================================================================================
"""
from __future__ import annotations
import re, unicodedata

TEAM_ALIASES: dict[str, list[str]] = {
    "United States": ["USA","US","U.S.A.","United States of America","USMNT"],
    "Serbia": ["Serbia national football team"],
    "Panama": ["Panama national football team"],
    "Morocco": ["Maroc","Al-Maghrib"],
    "Mexico": ["México","Mexiko","MEX"],
    "Poland": ["Polska","POL"],
    "Saudi Arabia": ["KSA","Al-Saudia"],
    "Belgium": ["Belgique","België","BEL"],
    "Brazil": ["Brasil","BRA"],
    "Croatia": ["Hrvatska","CRO"],
    "Japan": ["JPN","Nihon"],
    "Colombia": ["Colombia national football team","COL"],
    "England": ["ENG","England national football team"],
    "Netherlands": ["Holland","Nederland","NED","The Netherlands"],
    "Senegal": ["SEN"],
    "Iran": ["IR Iran","Islamic Republic of Iran","IRN"],
    "France": ["FRA","Les Bleus"],
    "Australia": ["AUS","Socceroos"],
    "Denmark": ["DEN","Danmark"],
    "Tunisia": ["TUN"],
    "Germany": ["Deutschland","GER","BRD"],
    "Spain": ["España","ESP","La Roja"],
    "Costa Rica": ["CRC"],
    "Argentina": ["ARG","La Albiceleste"],
    "Peru": ["Perú","PER"],
    "Canada": ["CAN"],
    "Ecuador": ["ECU"],
    "Portugal": ["POR","FPF"],
    "Ghana": ["GHA","Black Stars"],
    "Uruguay": ["URU","La Celeste"],
    "South Korea": ["Korea Republic","Korea DPR","Republic of Korea","KOR","Korea","South Korea national football team"],
    "Curaçao": ["Curacao","CUW","Curaçao national football team"],
    "Cape Verde": ["Cabo Verde","CPV","Cape Verde Islands"],
    "New Zealand": ["NZL","All Whites"],
    "Bolivia": ["BOL"],
    "Paraguay": ["PAR"],
    "Venezuela": ["VEN"],
    "Chile": ["CHL"],
    "Honduras": ["HON"],
    "Jamaica": ["JAM"],
    "Trinidad and Tobago": ["TTO","Trinidad & Tobago"],
    "Bahrain": ["BHR"],
    "Iraq": ["IRQ"],
    "United Arab Emirates": ["UAE","Emirati"],
    "Uzbekistan": ["UZB"],
    "Switzerland": ["Schweiz","Suisse","Svizzera","SUI"],
    "Wales": ["Cymru","WAL"],
    "Cameroon": ["CMR"],
    "Qatar": ["QAT"],
    "Ivory Coast": ["Côte d'Ivoire","Cote d'Ivoire","CIV"],
    "Nigeria": ["NGA","Super Eagles"],
    "Arsenal": ["Arsenal FC","The Gunners"],
    "Aston Villa": ["Aston Villa FC","Villa"],
    "Brentford": ["Brentford FC"],
    "Brighton": ["Brighton & Hove Albion","Brighton and Hove Albion","Brighton FC"],
    "Chelsea": ["Chelsea FC","The Blues"],
    "Crystal Palace": ["Crystal Palace FC","Palace"],
    "Everton": ["Everton FC","The Toffees"],
    "Fulham": ["Fulham FC"],
    "Liverpool": ["Liverpool FC","The Reds"],
    "Manchester City": ["Man City","Manchester City FC","MCFC"],
    "Manchester United": ["Man Utd","Man United","Manchester United FC","MUFC"],
    "Newcastle United": ["Newcastle","Newcastle United FC","NUFC"],
    "Nottingham Forest": ["Nott'm Forest","Nottm Forest","Forest"],
    "Tottenham Hotspur": ["Tottenham","Spurs","Tottenham Hotspur FC","THFC"],
    "West Ham United": ["West Ham","West Ham United FC","WHU"],
    "Wolverhampton Wanderers": ["Wolves","Wolverhampton","Wolverhampton Wanderers FC"],
    "Real Madrid": ["Real Madrid CF","Madrid"],
    "FC Barcelona": ["Barcelona","Barça","Barca","FCB"],
    "Atletico Madrid": ["Atlético Madrid","Atletico de Madrid","ATM"],
    "Sevilla": ["Sevilla FC"],
    "Real Sociedad": ["Real Sociedad de Fútbol"],
    "Villarreal": ["Villarreal CF","Yellow Submarine"],
    "Athletic Club": ["Athletic Bilbao","Athletic Club de Bilbao"],
    "Valencia": ["Valencia CF"],
    "Betis": ["Real Betis","Real Betis Balompié"],
    "Juventus": ["Juventus FC","Juve"],
    "Inter Milan": ["FC Internazionale","Internazionale","FCIM"],
    "AC Milan": ["Milan","AC Milan","Associazione Calcio Milan"],
    "Napoli": ["SSC Napoli","S.S.C. Napoli"],
    "AS Roma": ["Roma","A.S. Roma"],
    "Lazio": ["SS Lazio","S.S. Lazio"],
    "Atalanta": ["Atalanta BC"],
    "Fiorentina": ["ACF Fiorentina"],
    "Bayern Munich": ["FC Bayern München","FC Bayern Munich","Bayern","FCB München"],
    "Borussia Dortmund": ["Dortmund","BVB","BVB 09"],
    "RB Leipzig": ["Leipzig","Rasenballsport Leipzig"],
    "Bayer Leverkusen": ["Leverkusen","Bayer 04 Leverkusen"],
    "Eintracht Frankfurt": ["Frankfurt","SGE"],
    "Union Berlin": ["1. FC Union Berlin"],
    "Freiburg": ["SC Freiburg","Sport-Club Freiburg"],
    "Wolfsburg": ["VfL Wolfsburg"],
    "Paris Saint-Germain": ["PSG","Paris SG","Paris Saint Germain"],
    "Marseille": ["Olympique de Marseille","OM"],
    "Lyon": ["Olympique Lyonnais","OL"],
    "Monaco": ["AS Monaco","ASM"],
    "Lens": ["RC Lens"],
    "Lille": ["LOSC Lille","LOSC"],
    "Rennes": ["Stade Rennais","Stade Rennais FC"],
    "Nice": ["OGC Nice"],
    "FCSB": ["Fotbal Club FCSB","FC Steaua București","Steaua"],
    "CFR Cluj": ["Fotbal Club CFR 1907 Cluj","CFR 1907 Cluj"],
    "Rapid București": ["Rapid Bucharest","FC Rapid București"],
    "Universitatea Craiova": ["CS Universitatea Craiova","U Craiova"],
    "Farul Constanța": ["FC Farul Constanța","Farul"],
    "Petrolul Ploiești": ["FC Petrolul Ploiești","Petrolul"],
    "Dinamo București": ["FC Dinamo București"],
    "UTA Arad": ["FC UTA Arad","UTA"],
    "Inter Miami": ["Inter Miami CF","Club Internacional de Fútbol Miami"],
    "LA Galaxy": ["Los Angeles Galaxy"],
    "NYCFC": ["New York City FC","New York City Football Club"],
    "Seattle Sounders": ["Seattle Sounders FC"],
    "Portland Timbers": ["Portland Timbers FC"],
    "Atlanta United": ["Atlanta United FC"],
    "Toronto FC": ["TFC","Toronto Football Club"],
    "Club de Foot Montréal": ["CF Montréal","CF Montreal","Impact de Montréal"],
    "San Jose Earthquakes": ["SJ Earthquakes"],
    "Orlando City": ["Orlando City SC"],
    "Feyenoord": ["Feyenoord Rotterdam","Feyenoord FC"],
    "Ajax": ["AFC Ajax","Ajax Amsterdam"],
    "PSV": ["PSV Eindhoven","PSV Eindhoven FC"],
}

ALIAS_TO_CANONICAL: dict[str, str] = {}
for _canonical, _aliases in TEAM_ALIASES.items():
    ALIAS_TO_CANONICAL[_canonical.lower()] = _canonical
    for _alias in _aliases:
        ALIAS_TO_CANONICAL[_alias.lower()] = _canonical

# [FIX v1.3] " fc", " cf", " united", " city" eliminate — vezi CHANGES v1.3.
_STRIP_SUFFIXES = [
    " football club"," sc"," sv"," ac"," bc",
    " afc"," fk"," sk"," bk"," if"," hk"," gd",
]
_STRIP_PREFIXES = ["fc ","cf ","ac ","sc ","fk ","sk ","afc "]

def _unicode_normalize(name: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", name) if unicodedata.category(c) != "Mn")

def normalize_team_name(name: str) -> str:
    if not name: return name
    cleaned = name.strip()
    lookup = cleaned.lower()
    if lookup in ALIAS_TO_CANONICAL: return ALIAS_TO_CANONICAL[lookup]
    uni = _unicode_normalize(cleaned)
    lookup = uni.lower()
    if lookup in ALIAS_TO_CANONICAL: return ALIAS_TO_CANONICAL[lookup]
    stripped = uni.lower()
    for suffix in _STRIP_SUFFIXES:
        if stripped.endswith(suffix): stripped = stripped[:-len(suffix)].strip(); break
    for prefix in _STRIP_PREFIXES:
        if stripped.startswith(prefix): stripped = stripped[len(prefix):].strip(); break
    if stripped in ALIAS_TO_CANONICAL: return ALIAS_TO_CANONICAL[stripped]
    # [FIX v1.2] Elimin fuzzy prefix-matching ("alias.startswith(stripped)").
    # Era responsabil pentru coliziuni sistemice: orice echipa NECUNOSCUTA a
    # carei denumire, dupa stripping de sufixe generice, se intampla sa fie
    # un prefix al unui alias existent, era mapata GRESIT la acel alias
    # (ex: "Paris FC" -> "Paris Saint-Germain"). Scanul sistemic a identificat
    # 141+ astfel de coliziuni potentiale.
    # Fara potrivire exacta (alias explicit sau alias dupa strip suffix/
    # prefix), o echipa necunoscuta ramane NEmodificata — mai bine sa nu fie
    # normalizata deloc, decat sa fie unita gresit cu alt club.
    return cleaned

def match_key(home: str, away: str, kickoff_date: str) -> str:
    h = normalize_team_name(home or "").lower()
    a = normalize_team_name(away or "").lower()
    d = (kickoff_date or "")[:10]
    return f"{h}||{a}||{d}"
