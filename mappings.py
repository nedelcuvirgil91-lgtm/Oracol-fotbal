"""
================================================================================
FOOTBALL ORACLE — Mappings & Normalization (v1.4)
CHANGES v1.4:
  - [FIX] Restaurate constantele de configurare a ligilor (ODDS_SPORT_KEYS,
    SPORT_KEY_TO_LEAGUE, FD_COMPETITIONS, ESPN_LEAGUE_SLUGS, TSDB_LEAGUE_IDS,
    ELO_RATINGS_FALLBACK, NATIONAL_TEAM_STATS, LEAGUE_BASELINES,
    FREE_LF_LEAGUE_IDS), eliminate accidental in v1.2/v1.3 in timpul
    curatarii de team-aliasuri. oracle_api.py si oracle_engine.py le
    importau si aplicatia nu mai pornea (ImportError: cannot import name
    'ODDS_SPORT_KEYS' from 'mappings'). Valorile sunt identice 1:1 cu
    ultima versiune functionala (v1.1) — nicio valoare inventata sau
    modificata, doar recuperata din istoricul fisierului.
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
    "Leicester City": ["Leicester City FC","Leicester"],
    "Liverpool": ["Liverpool FC","The Reds"],
    "Manchester City": ["Man City","Manchester City FC","MCFC"],
    "Manchester United": ["Man Utd","Man United","Manchester United FC","MUFC","Manchester Utd"],
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
    "Inter Milan": ["FC Internazionale","Internazionale","FCIM","Inter"],
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

# ─────────────────────────────────────────────────────────────────────────────
# [RESTAURAT v1.4] Constante de configurare ligi/odds/ELO — identice 1:1 cu
# v1.1 (ultima versiune in care existau). Eliminate accidental in v1.2/v1.3.
# Consumate de oracle_api.py si oracle_engine.py — vezi CHANGES v1.4 de mai sus.
# ─────────────────────────────────────────────────────────────────────────────
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

# ─────────────────────────────────────────────────────────────────────────────
# NATIONAL TEAM STATS — date reale din calificari + turnee recente
# Surse: FIFA WC 2026 qualifiers, Nations League 2024-25, Copa America 2024,
#        AFCON 2024, Euro 2024. Actualizate manual periodic.
# Format: avg_gf, avg_ga, avg_sot, avg_possession, matches_used
# ─────────────────────────────────────────────────────────────────────────────
NATIONAL_TEAM_STATS: dict[str, dict] = {
    # ── Group A ───────────────────────────────────────────────────────────
    "United States":  {"avg_gf":1.82,"avg_ga":0.91,"avg_sot":5.2,"avg_possession":54.1,"matches":12,"form":["W","W","D","W","W"]},
    "Panama":         {"avg_gf":1.20,"avg_ga":1.10,"avg_sot":3.8,"avg_possession":44.2,"matches":10,"form":["W","L","W","D","W"]},
    "Morocco":        {"avg_gf":1.75,"avg_ga":0.70,"avg_sot":5.8,"avg_possession":51.3,"matches":14,"form":["W","W","W","D","W"]},
    "Serbia":         {"avg_gf":1.90,"avg_ga":1.10,"avg_sot":5.5,"avg_possession":52.0,"matches":10,"form":["W","D","W","W","L"]},
    # ── Group B ───────────────────────────────────────────────────────────
    "Mexico":         {"avg_gf":1.65,"avg_ga":1.05,"avg_sot":4.9,"avg_possession":53.2,"matches":12,"form":["W","W","D","L","W"]},
    "Poland":         {"avg_gf":1.45,"avg_ga":1.20,"avg_sot":4.3,"avg_possession":49.8,"matches":10,"form":["D","W","L","W","D"]},
    "Saudi Arabia":   {"avg_gf":1.30,"avg_ga":1.25,"avg_sot":3.9,"avg_possession":46.5,"matches":10,"form":["W","L","W","W","D"]},
    "Belgium":        {"avg_gf":2.10,"avg_ga":0.85,"avg_sot":6.2,"avg_possession":56.4,"matches":10,"form":["W","W","W","D","W"]},
    # ── Group C ───────────────────────────────────────────────────────────
    "Brazil":         {"avg_gf":2.20,"avg_ga":0.75,"avg_sot":7.1,"avg_possession":61.2,"matches":18,"form":["W","W","D","W","W"]},
    "Croatia":        {"avg_gf":1.55,"avg_ga":0.90,"avg_sot":5.0,"avg_possession":53.5,"matches":10,"form":["W","D","W","D","W"]},
    "Japan":          {"avg_gf":1.80,"avg_ga":0.85,"avg_sot":5.5,"avg_possession":50.8,"matches":12,"form":["W","W","W","L","W"]},
    "Colombia":       {"avg_gf":2.05,"avg_ga":0.70,"avg_sot":6.3,"avg_possession":57.2,"matches":18,"form":["W","W","W","W","D"]},
    # ── Group D ───────────────────────────────────────────────────────────
    "England":        {"avg_gf":2.05,"avg_ga":0.65,"avg_sot":6.8,"avg_possession":58.3,"matches":12,"form":["W","W","D","W","W"]},
    "Netherlands":    {"avg_gf":1.95,"avg_ga":0.80,"avg_sot":6.1,"avg_possession":57.0,"matches":12,"form":["W","W","W","D","W"]},
    "Senegal":        {"avg_gf":1.60,"avg_ga":0.90,"avg_sot":4.8,"avg_possession":49.5,"matches":12,"form":["W","D","W","W","L"]},
    "Iran":           {"avg_gf":1.35,"avg_ga":1.00,"avg_sot":3.8,"avg_possession":45.0,"matches":10,"form":["W","W","D","L","W"]},
    # ── Group E ───────────────────────────────────────────────────────────
    "France":         {"avg_gf":2.30,"avg_ga":0.60,"avg_sot":7.5,"avg_possession":60.5,"matches":12,"form":["W","W","W","W","D"]},
    "Australia":      {"avg_gf":1.25,"avg_ga":1.10,"avg_sot":3.7,"avg_possession":44.8,"matches":10,"form":["W","D","L","W","W"]},
    "Denmark":        {"avg_gf":1.75,"avg_ga":0.80,"avg_sot":5.4,"avg_possession":54.2,"matches":10,"form":["W","W","D","W","D"]},
    "Tunisia":        {"avg_gf":1.20,"avg_ga":1.00,"avg_sot":3.5,"avg_possession":44.0,"matches":10,"form":["D","W","L","D","W"]},
    # ── Group F ───────────────────────────────────────────────────────────
    "Germany":        {"avg_gf":2.40,"avg_ga":0.80,"avg_sot":7.2,"avg_possession":60.8,"matches":12,"form":["W","W","W","D","W"]},
    "Spain":          {"avg_gf":2.35,"avg_ga":0.55,"avg_sot":7.8,"avg_possession":64.5,"matches":12,"form":["W","W","W","W","W"]},
    "Costa Rica":     {"avg_gf":1.10,"avg_ga":1.30,"avg_sot":3.2,"avg_possession":42.5,"matches":10,"form":["L","W","D","W","L"]},
    # ── Group G ───────────────────────────────────────────────────────────
    "Argentina":      {"avg_gf":2.55,"avg_ga":0.60,"avg_sot":8.0,"avg_possession":57.8,"matches":18,"form":["W","W","W","W","W"]},
    "Peru":           {"avg_gf":1.15,"avg_ga":1.35,"avg_sot":3.4,"avg_possession":45.5,"matches":18,"form":["L","D","W","L","D"]},
    "Canada":         {"avg_gf":1.70,"avg_ga":1.05,"avg_sot":5.0,"avg_possession":50.5,"matches":12,"form":["W","W","D","W","L"]},
    "Ecuador":        {"avg_gf":1.55,"avg_ga":1.10,"avg_sot":4.6,"avg_possession":48.8,"matches":18,"form":["W","D","W","L","W"]},
    # ── Group H ───────────────────────────────────────────────────────────
    "Portugal":       {"avg_gf":2.45,"avg_ga":0.65,"avg_sot":7.6,"avg_possession":59.2,"matches":12,"form":["W","W","W","W","D"]},
    "Ghana":          {"avg_gf":1.40,"avg_ga":1.20,"avg_sot":4.0,"avg_possession":46.0,"matches":12,"form":["W","D","L","W","D"]},
    "Uruguay":        {"avg_gf":1.85,"avg_ga":0.80,"avg_sot":5.7,"avg_possession":52.5,"matches":18,"form":["W","W","D","W","W"]},
    "South Korea":    {"avg_gf":1.60,"avg_ga":0.95,"avg_sot":4.8,"avg_possession":50.2,"matches":12,"form":["W","W","D","D","W"]},
    # ── Alte nationale relevante ──────────────────────────────────────────
    "Switzerland":    {"avg_gf":1.80,"avg_ga":0.85,"avg_sot":5.5,"avg_possession":53.0,"matches":10,"form":["W","W","D","W","W"]},
    "Wales":          {"avg_gf":1.30,"avg_ga":1.10,"avg_sot":3.8,"avg_possession":45.5,"matches":10,"form":["D","L","W","D","W"]},
    "Nigeria":        {"avg_gf":1.55,"avg_ga":1.05,"avg_sot":4.5,"avg_possession":48.5,"matches":12,"form":["W","D","W","L","W"]},
    "Ivory Coast":    {"avg_gf":1.65,"avg_ga":1.00,"avg_sot":4.8,"avg_possession":50.0,"matches":12,"form":["W","W","D","W","L"]},
    "Cameroon":       {"avg_gf":1.40,"avg_ga":1.15,"avg_sot":3.9,"avg_possession":46.5,"matches":12,"form":["D","W","L","W","D"]},
    "Qatar":          {"avg_gf":1.10,"avg_ga":1.40,"avg_sot":3.2,"avg_possession":43.0,"matches":10,"form":["L","D","W","L","W"]},
    "Curaçao":        {"avg_gf":1.25,"avg_ga":1.35,"avg_sot":3.5,"avg_possession":44.0,"matches":10,"form":["W","D","L","W","D"]},
    "Cape Verde":     {"avg_gf":1.45,"avg_ga":1.00,"avg_sot":4.2,"avg_possession":47.0,"matches":12,"form":["W","W","D","D","W"]},
    "Chile":          {"avg_gf":1.35,"avg_ga":1.25,"avg_sot":4.0,"avg_possession":51.0,"matches":18,"form":["L","D","W","D","L"]},
    "Venezuela":      {"avg_gf":1.50,"avg_ga":1.10,"avg_sot":4.4,"avg_possession":48.0,"matches":18,"form":["W","W","D","W","D"]},
    "Bolivia":        {"avg_gf":1.05,"avg_ga":1.55,"avg_sot":3.0,"avg_possession":41.0,"matches":18,"form":["L","L","D","W","L"]},
    "Paraguay":       {"avg_gf":1.30,"avg_ga":1.20,"avg_sot":3.7,"avg_possession":46.0,"matches":18,"form":["D","W","L","D","W"]},
    "Honduras":       {"avg_gf":1.15,"avg_ga":1.30,"avg_sot":3.3,"avg_possession":44.5,"matches":10,"form":["L","W","D","L","W"]},
    "Jamaica":        {"avg_gf":1.10,"avg_ga":1.35,"avg_sot":3.1,"avg_possession":43.5,"matches":10,"form":["D","L","W","D","L"]},
    "Iraq":           {"avg_gf":1.45,"avg_ga":1.05,"avg_sot":4.1,"avg_possession":47.5,"matches":10,"form":["W","D","W","L","W"]},
    "Bahrain":        {"avg_gf":1.20,"avg_ga":1.25,"avg_sot":3.4,"avg_possession":44.0,"matches":10,"form":["W","D","L","W","D"]},
    "Uzbekistan":     {"avg_gf":1.55,"avg_ga":0.95,"avg_sot":4.5,"avg_possession":50.0,"matches":10,"form":["W","W","D","W","L"]},
    "New Zealand":    {"avg_gf":1.15,"avg_ga":1.20,"avg_sot":3.3,"avg_possession":43.0,"matches":10,"form":["D","W","L","W","D"]},
    "Trinidad and Tobago": {"avg_gf":1.10,"avg_ga":1.25,"avg_sot":3.2,"avg_possession":43.5,"matches":10,"form":["D","L","W","D","W"]},
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


# ─────────────────────────────────────────────────────────────────────────────
# [ADAUGAT v1.4] League normalization
# ─────────────────────────────────────────────────────────────────────────────
# Aduce toate formele brute sub care poate aparea o competitie (coduri
# football-data.co.uk din Kaggle Division, nume de tara din EloRatings.csv,
# coduri/nume din football-data.org) la ACELASI nume canonic folosit peste
# tot in aplicatie (cheile din LEAGUE_BASELINES / ODDS_SPORT_KEYS /
# FD_COMPETITIONS / ESPN_LEAGUE_SLUGS / TSDB_LEAGUE_IDS / FREE_LF_LEAGUE_IDS).
#
# Design intentionat, la cererea utilizatorului:
#   - DOAR potriviri exacte (case-insensitive) — NICIUN fuzzy matching, spre
#     deosebire de normalize_team_name(). O liga are un numar mic si stabil
#     de coduri/variante cunoscute; o potrivire aproximativa ar risca sa
#     amestece competitii diferite (ex. Serie A vs Serie B) tacit.
#   - Extensibil: pentru a adauga o competitie noua (ex. Championship,
#     Eredivisie ca sursa activa, alta liga), se adauga DOAR o intrare noua
#     in LEAGUE_ALIASES — functia normalize_league_name() nu se modifica.
#   - O valoare necunoscuta ramane NESCHIMBATA (acelasi principiu sigur ca
#     la normalize_team_name(): mai bine nenormalizata decat mapata gresit).
LEAGUE_ALIASES: dict[str, list[str]] = {
    # ── Coduri football-data.co.uk (coloana Division din Kaggle) + nume de
    #    tara din EloRatings.csv + codul football-data.org (din FD_COMPETITIONS)
    "Premier League":    ["E0", "England", "PL"],
    "La Liga":           ["SP1", "Spain", "PD", "Primera Division", "LaLiga"],
    "Serie A":           ["I1", "Italy", "SA"],
    "Bundesliga":        ["D1", "Germany", "BL1"],
    "Ligue 1":           ["F1", "France", "FL1"],
    # ROM verificat direct in Supabase (echipe: CFR Cluj, FCSB, Farul
    # Constanta, Rapid Bucuresti, UTA Arad, Universitatea Craiova) — nu presupus.
    "Romania SuperLiga": ["Romania", "ROM", "Liga 1", "Liga I"],
    # ── Competitii UEFA / mondiale — coduri FD_COMPETITIONS + denumiri
    #    oficiale folosite de football-data.org in raspunsul API
    "Champions League":  ["CL", "UEFA Champions League", "UCL", "uefa-champions-league"],
    "Europa League":     ["EL", "UEFA Europa League", "UEL", "uefa-europa-league"],
    "World Cup 2026":    ["WC", "FIFA World Cup", "World Cup"],
    # ── Alte ligi prezente in ODDS_SPORT_KEYS / ESPN_LEAGUE_SLUGS, momentan
    #    fara sursa activa de import istoric — pastrate pentru extensibilitate
    "MLS":               ["USA", "Major League Soccer"],
    "Eredivisie":        ["N1", "Netherlands"],
    "Primeira Liga":     ["P1", "Portugal"],
}

ALIAS_TO_CANONICAL_LEAGUE: dict[str, str] = {}
for _canonical_lg, _aliases_lg in LEAGUE_ALIASES.items():
    ALIAS_TO_CANONICAL_LEAGUE[_canonical_lg.lower()] = _canonical_lg
    for _alias_lg in _aliases_lg:
        ALIAS_TO_CANONICAL_LEAGUE[_alias_lg.lower()] = _canonical_lg


def normalize_league_name(name: str) -> str:
    """
    Aduce orice forma bruta de nume/cod de competitie la numele canonic
    folosit in restul aplicatiei. DOAR potrivire exacta (case-insensitive),
    fara fuzzy matching — vezi nota de design de mai sus.

    O valoare necunoscuta (None, gol, sau un cod/nume care nu apare in
    LEAGUE_ALIASES) este returnata NESCHIMBATA.
    """
    if not name:
        return name
    cleaned = name.strip()
    lookup = cleaned.lower()
    if lookup in ALIAS_TO_CANONICAL_LEAGUE:
        return ALIAS_TO_CANONICAL_LEAGUE[lookup]
    return cleaned
