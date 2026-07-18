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
from dataclasses import dataclass

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
    "Brighton": ["Brighton & Hove Albion","Brighton and Hove Albion","Brighton FC","Brighton & Hove Albion FC"],
    "Chelsea": ["Chelsea FC","The Blues"],
    "Crystal Palace": ["Crystal Palace FC","Palace"],
    "Everton": ["Everton FC","The Toffees"],
    "Fulham": ["Fulham FC"],
    "Leicester City": ["Leicester City FC","Leicester"],
    "Liverpool": ["Liverpool FC","The Reds"],
    "Manchester City": ["Man City","Manchester City FC","MCFC"],
    "Manchester United": ["Man Utd","Man United","Manchester United FC","MUFC","Manchester Utd"],
    "Newcastle United": ["Newcastle","Newcastle United FC","NUFC"],
    "Nottingham Forest": ["Nott'm Forest","Nottm Forest","Forest","Nottingham Forest FC"],
    "Tottenham Hotspur": ["Tottenham","Spurs","Tottenham Hotspur FC","THFC"],
    "West Ham United": ["West Ham","West Ham United FC","WHU"],
    "Wolverhampton Wanderers": ["Wolves","Wolverhampton","Wolverhampton Wanderers FC"],
    "Real Madrid": ["Real Madrid CF","Madrid"],
    "FC Barcelona": ["Barcelona","Barça","Barca","FCB"],
    "Atletico Madrid": ["Atlético Madrid","Atletico de Madrid","ATM","Ath Madrid","Club Atlético de Madrid"],
    "Sevilla": ["Sevilla FC"],
    "Real Sociedad": ["Real Sociedad de Fútbol","Sociedad"],
    "Villarreal": ["Villarreal CF","Yellow Submarine"],
    "Athletic Club": ["Athletic Bilbao","Athletic Club de Bilbao","Ath Bilbao"],
    "Valencia": ["Valencia CF"],
    "Betis": ["Real Betis","Real Betis Balompié"],
    "Juventus": ["Juventus FC","Juve"],
    "Inter Milan": ["FC Internazionale","Internazionale","FCIM","Inter","FC Internazionale Milano"],
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
    "Eintracht Frankfurt": ["Frankfurt","SGE","Ein Frankfurt"],
    "Union Berlin": ["1. FC Union Berlin"],
    "Freiburg": ["SC Freiburg","Sport-Club Freiburg"],
    "Wolfsburg": ["VfL Wolfsburg"],
    "Paris Saint-Germain": ["PSG","Paris SG","Paris Saint Germain","Paris Saint-Germain FC"],
    "Marseille": ["Olympique de Marseille","OM"],
    "Lyon": ["Olympique Lyonnais","OL"],
    "Monaco": ["AS Monaco","ASM","AS Monaco FC"],
    "Lens": ["RC Lens","Racing Club de Lens"],
    "Lille": ["LOSC Lille","LOSC","Lille OSC"],
    "Rennes": ["Stade Rennais","Stade Rennais FC","Stade Rennais FC 1901"],
    "Nice": ["OGC Nice"],
    "FCSB": ["Fotbal Club FCSB","FC Steaua București","Steaua"],
    "CFR Cluj": ["Fotbal Club CFR 1907 Cluj","CFR 1907 Cluj"],
    "Rapid București": ["Rapid Bucharest","FC Rapid București","FC Rapid Bucuresti","Rapid Bucuresti"],
    "Universitatea Craiova": ["CS Universitatea Craiova","U Craiova","Univ. Craiova"],
    "Farul Constanța": ["FC Farul Constanța","Farul","Farul Constanta"],
    "Petrolul Ploiești": ["FC Petrolul Ploiești","Petrolul"],
    "Din. Bucuresti": ["Dinamo Bucuresti", "Dinamo București", "FC Dinamo București"],
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
    # ── Premier League — gap-uri demonstrate (backfill football-data.co.uk) ──
    "AFC Bournemouth": ["Bournemouth","Bournemouth FC"],
    "Burnley": ["Burnley FC"],
    "Ipswich Town": ["Ipswich","Ipswich Town FC"],
    "Luton Town": ["Luton","Luton Town FC"],
    "Sheffield United": ["Sheffield Utd","Sheffield United FC"],
    "Southampton": ["Southampton FC","Saints"],
    "Leeds United": ["Leeds","Leeds United FC"],
    "Sunderland": ["Sunderland AFC"],
    # ── Championship — pregatire roadmap (fara linie canonica live inca, cf. §) ──
    "Barnsley": ["Barnsley FC"],
    "Birmingham City": ["Birmingham","Birmingham City FC"],
    "Blackburn Rovers": ["Blackburn","Blackburn Rovers FC"],
    "Blackpool": ["Blackpool FC"],
    "Bolton Wanderers": ["Bolton","Bolton Wanderers FC"],
    "Bradford City": ["Bradford","Bradford City FC"],
    "Bristol City": ["Bristol City FC"],
    "Burton Albion": ["Burton","Burton Albion FC"],
    "Cardiff City": ["Cardiff","Cardiff City FC"],
    "Charlton Athletic": ["Charlton","Charlton Athletic FC"],
    "Colchester United": ["Colchester","Colchester United FC"],
    "Coventry City": ["Coventry","Coventry City FC"],
    "Crewe Alexandra": ["Crewe","Crewe Alexandra FC"],
    "Derby County": ["Derby","Derby County FC"],
    "Doncaster Rovers": ["Doncaster","Doncaster Rovers FC"],
    "Gillingham": ["Gillingham FC"],
    "Grimsby Town": ["Grimsby","Grimsby Town FC"],
    "Huddersfield Town": ["Huddersfield","Huddersfield Town FC"],
    "Hull City": ["Hull","Hull City FC","Hull City AFC"],
    "Middlesbrough": ["Middlesbrough FC"],
    "Millwall": ["Millwall FC"],
    "Milton Keynes Dons": ["MK Dons","Milton Keynes Dons FC"],
    "Norwich City": ["Norwich","Norwich City FC"],
    "Oxford United": ["Oxford","Oxford United FC"],
    "Peterborough United": ["Peterboro","Peterborough United FC","Peterborough"],
    "Plymouth Argyle": ["Plymouth","Plymouth Argyle FC"],
    "Portsmouth": ["Portsmouth FC","Pompey"],
    "Preston North End": ["Preston","Preston North End FC"],
    "Queens Park Rangers": ["QPR","Queens Park Rangers FC"],
    "Reading": ["Reading FC"],
    "Rotherham United": ["Rotherham","Rotherham United FC"],
    "Scunthorpe United": ["Scunthorpe","Scunthorpe United FC"],
    "Sheffield Wednesday": ["Sheffield Weds","Sheffield Wednesday FC"],
    "Southend United": ["Southend","Southend United FC"],
    "Stockport County": ["Stockport","Stockport County FC"],
    "Stoke City": ["Stoke","Stoke City FC"],
    "Swansea City": ["Swansea","Swansea City FC","Swansea City AFC"],
    "Tranmere Rovers": ["Tranmere","Tranmere Rovers FC"],
    "Walsall": ["Walsall FC"],
    "Watford": ["Watford FC"],
    "West Bromwich Albion": ["West Brom","West Bromwich Albion FC","WBA"],
    "Wigan Athletic": ["Wigan","Wigan Athletic FC"],
    "AFC Wimbledon": ["Wimbledon","AFC Wimbledon FC"],
    "Wycombe Wanderers": ["Wycombe","Wycombe Wanderers FC"],
    "Yeovil Town": ["Yeovil","Yeovil Town FC"],
    # ── La Liga ──
    "Deportivo Alaves": ["Alaves","Deportivo Alavés"],
    "UD Almeria": ["Almeria","UD Almería"],
    "Cadiz CF": ["Cadiz","Cádiz CF"],
    "Celta Vigo": ["Celta","RC Celta de Vigo"],
    "Elche CF": ["Elche"],
    "Espanyol": ["Espanol","RCD Espanyol de Barcelona"],
    "Getafe CF": ["Getafe"],
    "Girona FC": ["Girona"],
    "Granada CF": ["Granada"],
    "UD Las Palmas": ["Las Palmas"],
    "CD Leganes": ["Leganes","CD Leganés"],
    "Levante UD": ["Levante"],
    "RCD Mallorca": ["Mallorca"],
    "CA Osasuna": ["Osasuna"],
    "Real Oviedo": ["Oviedo"],
    "Real Valladolid": ["Valladolid","Real Valladolid CF"],
    "Rayo Vallecano": ["Vallecano","Rayo Vallecano de Madrid"],
    # ── Serie A ──
    "Bologna": ["Bologna FC 1909"],
    "Cagliari": ["Cagliari Calcio"],
    "Como": ["Como 1907"],
    "Cremonese": ["US Cremonese"],
    "Empoli": ["Empoli FC"],
    "Frosinone": ["Frosinone Calcio"],
    "Genoa": ["Genoa CFC"],
    "Lecce": ["US Lecce"],
    "Monza": ["AC Monza"],
    "Parma": ["Parma Calcio 1913"],
    "Salernitana": ["US Salernitana 1919"],
    "Sassuolo": ["US Sassuolo Calcio"],
    "Torino": ["Torino FC"],
    "Udinese": ["Udinese Calcio"],
    "Venezia": ["Venezia FC"],
    "Hellas Verona": ["Verona","Hellas Verona FC"],
    # ── Bundesliga ──
    "FC Augsburg": ["Augsburg"],
    "VfL Bochum": ["Bochum","VfL Bochum 1848"],
    "SV Darmstadt 98": ["Darmstadt"],
    "1. FC Koln": ["FC Koln","1. FC Köln"],
    "Hamburger SV": ["Hamburg"],
    "1. FC Heidenheim": ["Heidenheim","1. FC Heidenheim 1846"],
    "Hoffenheim": ["TSG 1899 Hoffenheim","TSG Hoffenheim"],
    "Borussia Monchengladbach": ["M'gladbach","MGladbach","Borussia Mönchengladbach","Gladbach"],
    "Mainz 05": ["Mainz","1. FSV Mainz 05"],
    "FC St. Pauli": ["St Pauli","FC St. Pauli 1910"],
    "VfB Stuttgart": ["Stuttgart"],
    "SV Werder Bremen": ["Werder Bremen"],
    # ── Ligue 1 ──
    "Angers SCO": ["Angers"],
    "AJ Auxerre": ["Auxerre"],
    "Stade Brestois": ["Brest","Stade Brestois 29"],
    "Clermont Foot": ["Clermont","Clermont Foot 63"],
    "Le Havre AC": ["Le Havre"],
    "FC Lorient": ["Lorient"],
    "FC Metz": ["Metz"],
    "Montpellier HSC": ["Montpellier"],
    "FC Nantes": ["Nantes"],
    "Stade de Reims": ["Reims"],
    "AS Saint-Etienne": ["St Etienne","AS Saint-Étienne"],
    "RC Strasbourg": ["Strasbourg","RC Strasbourg Alsace"],
    "Toulouse FC": ["Toulouse"],
    # ── Champions League / Europa League — forme multiple confirmate direct in match_history (provideri diferiti pentru aceeasi liga) ──
    "AC Sparta Praha": ["Sparta Praha","AC Sparta Prague"],
    "Besiktas": ["Besiktas JK"],
    "Young Boys": ["BSC Young Boys"],
    "Celtic": ["Celtic FC"],
    "Club Brugge": ["Club Brugge KV"],
    "Dynamo Kyiv": ["Dynamo Kiev","FC Dynamo Kyiv"],
    "FC Copenhagen": ["FC København","FC Kobenhavn"],
    "Porto": ["FC Porto"],
    "Red Bull Salzburg": ["FC Red Bull Salzburg"],
    "Bodo/Glimt": ["FK Bodø/Glimt","Bodo Glimt"],
    "Crvena Zvezda": ["FK Crvena Zvezda","Red Star Belgrade"],
    "Kairat Almaty": ["FK Kairat"],
    "Shakhtar Donetsk": ["FK Shakhtar Donetsk"],
    "Galatasaray": ["Galatasaray SK"],
    "Dinamo Zagreb": ["GNK Dinamo Zagreb"],
    "Malmo FF": ["Malmö FF"],
    "Olympiacos": ["PAE Olympiakos SFP","OLYMPIACOS PIRAEUS","Olympiakos"],
    "Paphos FC": [],
    "Qarabag": ["Qarabağ Ağdam FK","Qarabag Agdam"],
    "Royal Antwerp": ["Royal Antwerp FC","ANTWERP"],
    "Union Saint-Gilloise": ["Royale Union Saint-Gilloise"],
    "Slavia Praha": ["SK Slavia Praha"],
    "Slovan Bratislava": ["ŠK Slovan Bratislava"],
    "Sturm Graz": ["SK Sturm Graz"],
    "Benfica": ["Sport Lisboa e Benfica"],
    "Braga": ["Sporting Clube de Braga","SC BRAGA"],
    "Sporting CP": ["Sporting Clube de Portugal"],
    "Zenit Saint Petersburg": ["Zenit St Petersburg"],
    "Brondby": ["Brøndby IF"],
    "Ferencvaros": ["FERENCVAROSI TC","Ferencvárosi TC"],
    "Genk": ["KRC Genk"],
    "Legia Warszawa": ["Legia Warsaw"],
    "Lokomotiv Moscow": [],
    "Ludogorets": ["Ludogorets Razgrad"],
    "Rangers": ["Rangers FC"],
    "Rapid Vienna": ["SK Rapid Wien"],
    "Spartak Moscow": [],
    "Sheriff Tiraspol": [],
    "Midtjylland": ["FC MIDTJYLLAND"],
    # [ADAUGAT — P3.5 Faza 3, docs/03_ENGINE/P3_5_FAZA3_MIGRATION_PLAN_2026-07-15.md §4]
    # Singurele 2 din cele 176 de perechi raw->canonical (canonical_team_mapping.csv)
    # care nu se potriveau deja cu normalize_team_name() inainte de acest fix —
    # adaugate explicit ca sa nu se reintroduca fragmentarea dupa consolidarea Faza 3.
    "Colon Santa Fe": ["Colon Santa FE"],
    "Fenerbahce": ["FENERBAHCE"],
}

ALIAS_TO_CANONICAL: dict[str, str] = {}
for _canonical, _aliases in TEAM_ALIASES.items():
    ALIAS_TO_CANONICAL[_canonical.lower()] = _canonical
    for _alias in _aliases:
        ALIAS_TO_CANONICAL[_alias.lower()] = _canonical

# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
# [ADAUGAT] LEAGUE_PROVIDERS — SURSA CANONICĂ UNICĂ pentru toate mapările de
# competiții pe provideri externi. Vezi architecture/ADR-001-league-providers.md
# pentru motivația completă a acestei decizii.
#
# Înainte existau 5+ dicționare manuale separate (ODDS_SPORT_KEYS,
# FD_COMPETITIONS, ESPN_LEAGUE_SLUGS, TSDB_LEAGUE_IDS, FREE_LF_LEAGUE_IDS) +
# o a 6-a copie manuală, independentă, in sync/sync_results.py
# (COMPETITION_TO_LEAGUE) — care s-a desincronizat exact așa cum era de
# așteptat (lipseau Europa League și World Cup 2026, descoperit prin audit).
#
# De acum, toate dicționarele de mai jos sunt GENERATE din LEAGUE_PROVIDERS,
# nu scrise manual — o singură sursă de adevăr, imposibil de desincronizat.
#
# `provider_ids`: codul/ID-ul/slug-ul folosit de fiecare provider extern.
# `supported`: True (confirmat suportat), False (confirmat NEsuportat oficial,
#   verificat direct la sursă) sau "necunoscut" (neconfirmat încă — NU se
#   inventează niciodată o valoare aici doar ca să umplem golul).
#
# NOTĂ: "api_football" e inclus ca provider pt toate ligile, dar cu
# id=None/"necunoscut" peste tot — API-Football nu e încă integrat în cod,
# deci nu are sens verificat per-ligă până la integrarea reală (Etapa 6).
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class LeagueDefinition:
    name: str
    provider_ids: dict[str, str | int | None]
    supported: dict[str, bool | str]


LEAGUE_PROVIDERS: dict[str, LeagueDefinition] = {
    "Premier League": LeagueDefinition(
        name="Premier League",
        provider_ids={"football_data": "PL", "espn": "eng.1", "tsdb": "4328",
                       "odds": "soccer_epl", "freelf": 47, "api_football": None},
        supported={"football_data": True, "espn": True, "tsdb": True,
                    "odds": True, "freelf": True, "api_football": "necunoscut"},
    ),
    "La Liga": LeagueDefinition(
        name="La Liga",
        provider_ids={"football_data": "PD", "espn": "esp.1", "tsdb": "4335",
                       "odds": "soccer_spain_la_liga", "freelf": 87, "api_football": None},
        supported={"football_data": True, "espn": True, "tsdb": True,
                    "odds": True, "freelf": True, "api_football": "necunoscut"},
    ),
    "Serie A": LeagueDefinition(
        name="Serie A",
        provider_ids={"football_data": "SA", "espn": "ita.1", "tsdb": "4332",
                       "odds": "soccer_italy_serie_a", "freelf": 55, "api_football": None},
        supported={"football_data": True, "espn": True, "tsdb": True,
                    "odds": True, "freelf": True, "api_football": "necunoscut"},
    ),
    "Bundesliga": LeagueDefinition(
        name="Bundesliga",
        provider_ids={"football_data": "BL1", "espn": "ger.1", "tsdb": "4331",
                       "odds": "soccer_germany_bundesliga", "freelf": 54, "api_football": None},
        supported={"football_data": True, "espn": True, "tsdb": True,
                    "odds": True, "freelf": True, "api_football": "necunoscut"},
    ),
    "Ligue 1": LeagueDefinition(
        name="Ligue 1",
        provider_ids={"football_data": "FL1", "espn": "fra.1", "tsdb": "4334",
                       "odds": "soccer_france_ligue_one", "freelf": 53, "api_football": None},
        supported={"football_data": True, "espn": True, "tsdb": True,
                    "odds": True, "freelf": True, "api_football": "necunoscut"},
    ),
    "Champions League": LeagueDefinition(
        name="Champions League",
        provider_ids={"football_data": "CL", "espn": "uefa.champions", "tsdb": "4480",
                       "odds": "soccer_uefa_champs_league", "freelf": 42, "api_football": None},
        supported={"football_data": True, "espn": True, "tsdb": True,
                    "odds": True, "freelf": True, "api_football": "necunoscut"},
    ),
    "Europa League": LeagueDefinition(
        name="Europa League",
        # tsdb=4481 confirmat prin audit (lipsea inainte); football_data
        # ramane "necunoscut" - codul EL exista in catalogul general al
        # providerului, dar planul gratuit documentat public (12 competitii)
        # nu-l listeaza explicit - de verificat cu cheia reala a proiectului.
        provider_ids={"football_data": "EL", "espn": "uefa.europa", "tsdb": "4481",
                       "odds": "soccer_uefa_europa_league", "freelf": 73, "api_football": None},
        supported={"football_data": "necunoscut", "espn": True, "tsdb": True,
                    "odds": True, "freelf": True, "api_football": "necunoscut"},
    ),
    "Romania SuperLiga": LeagueDefinition(
        name="Romania SuperLiga",
        # api_football=283 ("Liga I") - league_id VERIFICAT LIVE 2026-07-17
        # prin /leagues?country=Romania (workflow_dispatch, run 29615697599,
        # nu presupus). "SuperLiga" e brandingul de sponsorizare al aceleiasi
        # competitii, nu o liga separata in date.
        #
        # supported["api_football"]="plan_restricted" — NU True, NU
        # "necunoscut". Providerul e configurat corect (cheie valida,
        # league_id corect) DAR planul Free API-Football blocheaza explicit
        # accesul la sezonul curent pe /fixtures. Verificat live, 4 apeluri
        # reale (nu presupus):
        #   GET /fixtures?league=283&season=2026&from=2026-07-17&to=2026-07-24
        #     -> HTTP 200, errors={"plan": "Free plans do not have access to
        #        this season, try from 2022 to 2024."}, response=[]
        #        (run 29616468120, payload brut confirmat in api_cache/Supabase)
        #   GET /fixtures?league=283&next=5
        #     -> HTTP 200, errors={"plan": "Free plans do not have access to
        #        the Next parameter."} (run 29616932623)
        #   GET /fixtures?league=283&date=2026-07-18 (fara season)
        #     -> HTTP 200, errors={"season": "The Season field is required."}
        #        - season ramane obligatoriu, nu ocoleste restrictia (run 29616932623)
        #   GET /fixtures?live=all
        #     -> functioneaza (8 meciuri live, alte ligi), dar acopera DOAR
        #        meciuri in desfasurare, inutilizabil pentru programul de
        #        meciuri viitoare (run 29616932623)
        # Niciun parametru documentat oficial nu ocoleste restrictia de sezon
        # pe planul Free. Confirmat si extern: documentatia oficiala
        # (api-football.com/pricing: "Free plans are limited in terms of
        # available seasons") si un caz independent (World Cup 2026, blog
        # Zenn.dev, 2026-06-08) raporteaza EXACT acelasi mesaj de eroare,
        # rezolvat de acel autor doar prin upgrade la plan platit.
        #
        # _covered() (football_providers.py) trateaza "plan_restricted" la
        # fel ca False - blocheaza apelul, 0 cereri irosite. Daca planul se
        # schimba (upgrade), un singur rand aici (True) reactiveaza fallback-ul
        # complet, fara nicio alta modificare de cod.
        # tsdb=4691 ("Romanian Liga I") — CORECTAT 2026-07-18, verificat live
        # (run GH Actions 29643951959): vechea valoare 4652 era 'Macedonian
        # First League' (lookupleague.php?id=4652 → Macedonia, dovada in log),
        # iar eventsnextleague.php?id=4691 a intors meciul real al zilei
        # ('Oțelul Galați' vs 'CFR Cluj', 2026-07-18 15:30) — nu presupus.
        provider_ids={"football_data": None, "espn": "rou.1", "tsdb": "4691",
                       "odds": "soccer_romania_1_liga", "freelf": None, "api_football": 283},
        supported={
            "football_data": False,  # CONFIRMAT: planul gratuit football-data.org
                                      # acopera exact 12 competitii publicate oficial,
                                      # Romania nu e printre ele
            "espn": True, "tsdb": True, "odds": True,
            "freelf": "necunoscut",
            "api_football": "plan_restricted",
        },
    ),
    "World Cup 2026": LeagueDefinition(
        name="World Cup 2026",
        provider_ids={"football_data": "WC", "espn": "fifa.world", "tsdb": "4429",
                       "odds": "soccer_fifa_world_cup", "freelf": 77, "api_football": None},
        supported={"football_data": True, "espn": True, "tsdb": True,
                    "odds": True, "freelf": True, "api_football": "necunoscut"},
    ),
    "MLS": LeagueDefinition(
        name="MLS",
        # MLS ramane exclus din BOOTSTRAP_LEAGUES (decizie deliberata,
        # aplicatia nu prevede acest campionat) - prezent aici doar pt
        # normalizare generala de nume, consistent cu LEAGUE_ALIASES.
        provider_ids={"football_data": None, "espn": "usa.1", "tsdb": "4346",
                       "odds": "soccer_usa_mls", "freelf": None, "api_football": None},
        supported={"football_data": False, "espn": True, "tsdb": True,
                    "odds": True, "freelf": False, "api_football": "necunoscut"},
    ),
    "Conference League": LeagueDefinition(
        name="Conference League",
        # Adaugat acum, integral, ca sa nu fie tratat separat ulterior.
        # tsdb=5071 si espn="uefa.europa.conf" confirmate prin audit direct.
        # odds: competitia exista confirmat la provider ("Soccer: UEFA Europa
        # Conference League" listata explicit), dar codul exact sport_key
        # nu a putut fi confirmat din surse publice - "necunoscut", nu inventat.
        provider_ids={"football_data": None, "espn": "uefa.europa.conf", "tsdb": "5071",
                       "odds": None, "freelf": None, "api_football": None},
        supported={
            "football_data": False,  # acelasi motiv ca Romania - nu e in cele 12 competitii gratuite
            "espn": True, "tsdb": True,
            "odds": "necunoscut", "freelf": "necunoscut", "api_football": "necunoscut",
        },
    ),
}

# ── Dictionare derivate — generate, NU scrise manual (elimina desincronizarea) ──
ODDS_SPORT_KEYS: dict[str, str] = {
    lg: d.provider_ids["odds"] for lg, d in LEAGUE_PROVIDERS.items()
    if d.provider_ids.get("odds") is not None
}
SPORT_KEY_TO_LEAGUE: dict[str, str] = {v: k for k, v in ODDS_SPORT_KEYS.items()}

FD_COMPETITIONS: dict[str, str] = {
    lg: d.provider_ids["football_data"] for lg, d in LEAGUE_PROVIDERS.items()
    if d.provider_ids.get("football_data") is not None
}

ESPN_LEAGUE_SLUGS: dict[str, str] = {
    lg: d.provider_ids["espn"] for lg, d in LEAGUE_PROVIDERS.items()
    if d.provider_ids.get("espn") is not None
}

TSDB_LEAGUE_IDS: dict[str, str] = {
    lg: d.provider_ids["tsdb"] for lg, d in LEAGUE_PROVIDERS.items()
    if d.provider_ids.get("tsdb") is not None
}

# Ligile pentru care API-Football poate fi folosit ca fallback — generat
# direct din LEAGUE_PROVIDERS, la fel ca dictionarele de mai sus. O liga
# noua devine eligibila DOAR prin completarea provider_ids["api_football"]
# aici, fara nicio modificare in oracle_api.py/football_providers.py.
API_FOOTBALL_LEAGUE_IDS: dict[str, int] = {
    lg: d.provider_ids["api_football"] for lg, d in LEAGUE_PROVIDERS.items()
    if d.provider_ids.get("api_football") is not None
}


def verify_league_coverage(bootstrap_leagues: list[str] | None = None) -> dict[str, list[str]]:
    """
    Audit automat — compară LEAGUE_PROVIDERS cu lista de ligi active
    (implicit BOOTSTRAP_LEAGUES) și raportează problemele, separat pe
    severitate. Gândit să ruleze în CI (vezi ADR-001).

    Returnează {"errors": [...], "warnings": [...]}. CI trebuie să eșueze
    DOAR pe "errors" (provideri obligatorii lipsă/neconfirmați) — "warnings"
    (provideri opționali încă neconfirmați, ex. freelf/api_football pt o
    ligă nouă) sunt tolerate temporar, nu blochează.

    Provideri obligatorii (cel puțin unul confirmat True, altfel liga nu
    poate intra deloc în bucla de învățare continuă): football_data, espn, tsdb.
    Provideri opționali: odds, freelf, api_football.
    """
    if bootstrap_leagues is None:
        from sync.bootstrap_league_learning import BOOTSTRAP_LEAGUES as bootstrap_leagues

    REQUIRED = ("football_data", "espn", "tsdb")
    OPTIONAL = ("odds", "freelf", "api_football")

    errors: list[str] = []
    warnings: list[str] = []

    for league in bootstrap_leagues:
        if league not in LEAGUE_PROVIDERS:
            errors.append(f"{league}: absentă complet din LEAGUE_PROVIDERS")
            continue
        supported = LEAGUE_PROVIDERS[league].supported
        if not any(supported.get(p) is True for p in REQUIRED):
            errors.append(
                f"{league}: niciun provider obligatoriu (football_data/espn/tsdb) "
                f"confirmat suportat — liga nu poate primi rezultate automate"
            )
        for p in REQUIRED:
            if supported.get(p) == "necunoscut":
                warnings.append(f"{league}/{p}: provider obligatoriu neconfirmat (nici True, nici False)")
        for p in OPTIONAL:
            if supported.get(p) == "necunoscut":
                warnings.append(f"{league}/{p}: provider opțional neconfirmat")

    return {"errors": errors, "warnings": warnings}


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
    lg: d.provider_ids["freelf"] for lg, d in LEAGUE_PROVIDERS.items()
    if d.provider_ids.get("freelf") is not None
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
    "Conference League": ["UECL", "UEFA Conference League", "UEFA Europa Conference League", "Europa Conference League"],
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
