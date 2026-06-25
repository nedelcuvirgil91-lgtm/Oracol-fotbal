"""
================================================================================
FOOTBALL ORACLE — Mappings & Normalization (v1.1)
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
    "Saudi Arabia": ["KSA","Saudi","Al-Saudia"],
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
    "Inter Milan": ["Inter","FC Internazionale","Internazionale","FCIM"],
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
    "Union Berlin": ["1. FC Union Berlin","Union"],
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
    "Rapid București": ["Rapid Bucharest","FC Rapid București","Rapid"],
    "Universitatea Craiova": ["CS Universitatea Craiova","U Craiova"],
    "Farul Constanța": ["FC Farul Constanța","Farul"],
    "Petrolul Ploiești": ["FC Petrolul Ploiești","Petrolul"],
    "Dinamo București": ["FC Dinamo București","Dinamo"],
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

ODDS_SPORT_KEYS: dict[str, str] = {
    "World Cup 2026":    "soccer_fifa_world_cup",
    "Premier League":    "soccer_epl",
    "La Liga":           "soccer_spain_la_liga",
    "Serie A":           "soccer_italy_serie_a",
    "Bundesliga":        "soccer_germany_bundesliga",
    "Ligue 1":           "soccer_france_ligue_one",
    "Champions League":  "soccer_uefa_champs_league",
    "Europa League":     "soccer_uefa_europa_league",
    "Romania SuperLiga": "soccer_romania_1_liga",
    "MLS":               "soccer_usa_mls",
    "Eredivisie":        "soccer_netherlands_eredivisie",
    "Primeira Liga":     "soccer_portugal_primeira_liga",
}

SPORT_KEY_TO_LEAGUE: dict[str, str] = {v: k for k, v in ODDS_SPORT_KEYS.items()}

FD_COMPETITIONS: dict[str, str] = {
    "Premier League": "PL", "La Liga": "PD", "Serie A": "SA",
    "Bundesliga": "BL1", "Ligue 1": "FL1", "Champions League": "CL",
    "Europa League": "EL", "World Cup 2026": "WC",
}

ESPN_LEAGUE_SLUGS: dict[str, str] = {
    "World Cup 2026": "fifa.world", "Premier League": "eng.1",
    "La Liga": "esp.1", "Serie A": "ita.1", "Bundesliga": "ger.1",
    "Ligue 1": "fra.1", "Champions League": "uefa.champions",
    "Europa League": "uefa.europa", "MLS": "usa.1", "Romania SuperLiga": "rou.1",
}

TSDB_LEAGUE_IDS: dict[str, str] = {
    "Premier League": "4328", "La Liga": "4335", "Serie A": "4332",
    "Bundesliga": "4331", "Ligue 1": "4334", "Champions League": "4480",
    "Romania SuperLiga": "4652", "World Cup 2026": "4429", "MLS": "4346",
}

ELO_RATINGS_FALLBACK: dict[str, int] = {
    "Argentina": 2141, "France": 2085, "England": 2065, "Brazil": 2062,
    "Spain": 2052, "Belgium": 2040, "Portugal": 2038, "Netherlands": 2034,
    "Germany": 2024, "Croatia": 2006, "Italy": 1998, "Uruguay": 1985,
    "Colombia": 1978, "United States": 1975, "Mexico": 1972, "Denmark": 1968,
    "Switzerland": 1964, "Morocco": 1952, "Japan": 1948, "Senegal": 1942,
    "South Korea": 1936, "Australia": 1928, "Ecuador": 1920, "Canada": 1918,
    "Poland": 1915, "Serbia": 1912, "Tunisia": 1905, "Iran": 1898,
    "Saudi Arabia": 1890, "Ghana": 1885, "Cameroon": 1882, "Costa Rica": 1875,
    "Peru": 1870, "Nigeria": 1868, "Qatar": 1850, "Panama": 1830,
    "Honduras": 1815, "Bolivia": 1808, "Paraguay": 1812, "Jamaica": 1780,
    "Curaçao": 1745, "Cape Verde": 1820, "New Zealand": 1738, "Bahrain": 1720,
    "Iraq": 1715, "Venezuela": 1800, "Chile": 1835, "Ivory Coast": 1870,
    "Manchester City": 1950, "Real Madrid": 1945, "Bayern Munich": 1940,
    "Liverpool": 1932, "FC Barcelona": 1928, "Paris Saint-Germain": 1920,
    "Arsenal": 1915, "Chelsea": 1908, "Manchester United": 1900,
    "Juventus": 1895, "Inter Milan": 1898, "AC Milan": 1885,
    "Atletico Madrid": 1890, "Borussia Dortmund": 1885, "Napoli": 1880,
    "Tottenham Hotspur": 1875,
}

LEAGUE_BASELINES: dict[str, float] = {
    "Premier League": 1.35, "La Liga": 1.20, "Serie A": 1.25,
    "Bundesliga": 1.40, "Ligue 1": 1.30, "Champions League": 1.20,
    "Europa League": 1.15, "Romania SuperLiga": 1.15,
    "World Cup 2026": 1.25, "MLS": 1.40, "default": 1.25,
}

FREE_LF_LEAGUE_IDS: dict[str, int] = {
    "World Cup 2026": 77, "Premier League": 47, "Champions League": 42,
    "La Liga": 87, "Bundesliga": 54, "Europa League": 73,
    "Ligue 1": 53, "Serie A": 55,
}

_STRIP_SUFFIXES = [
    " football club"," fc"," cf"," sc"," sv"," ac"," bc",
    " afc"," fk"," sk"," bk"," if"," hk"," gd"," united"," city",
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
    candidates = [canon for alias, canon in ALIAS_TO_CANONICAL.items() if alias.startswith(stripped) and len(stripped) >= 5]
    unique = list(set(candidates))
    if len(unique) == 1: return unique[0]
    return cleaned

# [FIX v1.1] — guard None pentru home/away
def match_key(home: str, away: str, kickoff_date: str) -> str:
    h = normalize_team_name(home or "").lower()
    a = normalize_team_name(away or "").lower()
    d = (kickoff_date or "")[:10]
    return f"{h}||{a}||{d}"
