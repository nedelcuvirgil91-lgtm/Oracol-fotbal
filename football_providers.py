"""
================================================================================
FOOTBALL ORACLE — Provideri de date externe (v1.0)
================================================================================
Module: football_providers.py

Interfață GENERICĂ pentru orice provider de date suplimentare (injuries,
coaches, player stats etc.) — API-Football e DOAR primul adaptor concret,
nu o integrare punctuală. Orice provider viitor (SofaScore, FBref etc.)
implementează aceeași interfață `FootballDataProvider`, fără să schimbe
nimic în `FootballOracleEngine`.

Model normalizat intern (Injury, CoachInfo): indiferent de la ce provider
vine informația, motorul primește aceeași structură — schimbarea
providerului în viitor înseamnă un adaptor nou, nu logică de predicție
rescrisă.

Ordinea OBLIGATORIE a oricărei cereri (vezi metoda `_get` de mai jos):
    health check (key_manager) → coverage check (LEAGUE_PROVIDERS)
    → L1 cache → L2 cache (Supabase, prin cache_manager)
    → HTTP request → actualizare cache → actualizare provider_metrics
Nicio cerere HTTP nu se face înainte de primele patru verificări.

[IMPORTANT — scope etapa curentă] NU se aplică asupra xG/probabilităților
și NU e conectat încă la FootballOracleEngine — doar colectare, normalizare,
cache. Integrarea în pipeline-ul de predicție e etapa următoare.
================================================================================
"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

from cache_manager import get_cache
from key_manager import get_key_manager
from request_manager import get_request_manager  # [ADAUGAT R4.1]

logger = logging.getLogger("FootballOracle.Providers")


# ════════════════════════════════════════════════════════════════════════════
# MODEL NORMALIZAT INTERN — comun tuturor providerilor
# ════════════════════════════════════════════════════════════════════════════

@dataclass
class Injury:
    player_name: str
    team_name: str
    injury_type: str          # "Injury" | "Suspension" | "necunoscut"
    reason: str
    player_id: str | None = None
    fixture_id: str | None = None
    source_provider: str = "necunoscut"


@dataclass
class CoachInfo:
    coach_id: str
    name: str
    team_name: str
    appointed_date: str | None = None   # data începerii mandatului curent
    nationality: str | None = None
    source_provider: str = "necunoscut"


# ════════════════════════════════════════════════════════════════════════════
# INTERFAȚA GENERICĂ — orice provider viitor implementează asta
# ════════════════════════════════════════════════════════════════════════════

class FootballDataProvider(ABC):
    """FootballOracleEngine consumă DOAR această interfață — nu cunoaște
    endpoint-uri, URL-uri sau headere HTTP ale niciunui provider concret."""

    @abstractmethod
    def get_injuries(self, team_name: str, team_id: int | str, league: str, season: int | None = None) -> list[Injury]:
        ...

    @abstractmethod
    def get_coaches(self, team_name: str, team_id: int | str, league: str) -> list[CoachInfo]:
        ...

    def get_player_stats(self, *args, **kwargs):
        """Placeholder — NU implementat în această etapă (interzis explicit)."""
        raise NotImplementedError("get_player_stats — nu e în scopul acestei etape")

    def get_team_stats(self, *args, **kwargs):
        """Placeholder — NU implementat în această etapă (interzis explicit)."""
        raise NotImplementedError("get_team_stats — nu e în scopul acestei etape")


# ════════════════════════════════════════════════════════════════════════════
# ApiFootballProvider — primul adaptor concret
# ════════════════════════════════════════════════════════════════════════════

class ApiFootballProvider(FootballDataProvider):
    """
    Adaptor pentru API-Football (api-sports.io v3).

    [NOTĂ DE INCERTITUDINE — raportată explicit, nu ascunsă] Structura
    exactă a răspunsului `/injuries` NU a fost confirmată dintr-un payload
    real (spre deosebire de `/coachs`, confirmat exact din documentația
    oficială). Presupunerea de mai jos (obiecte `player`/`team`/`fixture`
    separate, câmpuri `type`/`reason`) urmează convenția folosită consecvent
    de API-Football în TOATE celelalte endpoint-uri verificate (`/coachs`,
    `/fixtures/headtohead`) — dar parsarea e defensivă (`.get()` peste tot,
    niciodată acces direct care ar arunca excepție) și logează un avertisment
    dacă forma nu se potrivește, tocmai pentru cazul în care presupunerea
    se dovedește greșită la primul apel real.
    """

    PROVIDER_ID = "apifootball"
    BASE_URL = "https://v3.football.api-sports.io"

    def __init__(self, key_manager=None, cache=None, request_manager=None):
        self._key_manager = key_manager or get_key_manager()
        self._cache = cache or get_cache()
        self._session = None  # lazy — nu deschidem conexiuni la import
        # [ADAUGAT R4.1] Request Manager — RAM cache (L0) + dedup in-flight +
        # gating de buget real (header-e), infasoara _get() fara sa-i schimbe
        # comportamentul existent (L1/L2, coverage, retry HTTP) — vezi
        # request_manager.py.
        self._request_manager = request_manager or get_request_manager()

    def _get_session(self):
        if self._session is None:
            from requests import Session
            from requests.adapters import HTTPAdapter
            from urllib3.util.retry import Retry
            # [REPARAT] Aceeasi configurare de retry ca oracle_api.py._build_session()
            # - inainte sesiunea asta nu avea deloc retry, inconsistent cu restul.
            s = Session()
            r = Retry(total=3, backoff_factor=0.5,
                      status_forcelist=(429, 500, 502, 503, 504),
                      allowed_methods=["GET"], raise_on_status=False)
            a = HTTPAdapter(max_retries=r)
            s.mount("https://", a); s.mount("http://", a)
            self._session = s
        return self._session

    # ── Health + coverage — verificate ÎNAINTE de orice altceva ──────────
    def _healthy(self) -> bool:
        return self._key_manager.is_available(self.PROVIDER_ID)

    def _covered(self, league: str, category: str) -> bool:
        from mappings import LEAGUE_PROVIDERS
        league_def = LEAGUE_PROVIDERS.get(league)
        if league_def is None:
            return False
        # False explicit -> nu incercam. True sau "necunoscut" -> incercam
        # (necunoscut nu blocheaza, doar nu era inca confirmat la audit).
        # "plan_restricted" -> nu incercam: provider/cheie/ID confirmate
        # corecte, dar planul curent (Free) blocheaza explicit accesul la
        # sezonul curent - confirmat live, nu presupus (vezi comentariul
        # din mappings.py, Romania SuperLiga). Tratat la fel ca False, ca
        # sa nu iroseasca cereri pe un apel garantat sa esueze.
        state = league_def.supported.get(category)
        return state is not False and state != "plan_restricted"

    def _get(self, path: str, params: dict, cache_category: str, cache_key: str) -> dict | None:
        # 1. health check
        if not self._healthy():
            logger.debug("[ApiFootball] provider indisponibil (fara cheie activa) — sar peste %s", path)
            return None

        # 2. coverage check — facut de apelant (get_injuries/get_coaches),
        # ca sa poata folosi liga corecta din context; _get ramane generic.

        # [ADAUGAT R4.1] 3a. L0 — RAM cache (Request Manager), inaintea
        # oricarei citiri de disk/Supabase - deduplica cererile identice din
        # acelasi ciclu de evaluare/batch (audit §4/§7, gol confirmat: "Nu
        # exista azi — cache_manager.py are doar disk (L1) + Supabase (L2)").
        ram_hit = self._request_manager.get_ram(self.PROVIDER_ID, cache_category, cache_key)
        if ram_hit is not None:
            return ram_hit

        # 3b+4. L1 + L2 cache (ambele deja gestionate de CacheManager.get())
        cached = self._cache.get_raw(cache_category, cache_key)
        if cached is not None:
            self._request_manager.set_ram(self.PROVIDER_ID, cache_category, cache_key, cached)
            return cached

        # [ADAUGAT R4.1] Gating de buget real (header-e de raspuns anterioare,
        # daca exista) — "ar trebui sa existe cererea?" (audit §4/§16).
        # Fail-open pana la primul raspuns real cu header-e citite.
        if not self._request_manager.should_request(self.PROVIDER_ID):
            return None

        # [ADAUGAT R4.1] Dedup in-flight — daca alt apelant e deja in curs
        # pentru exact aceeasi cheie, nu duplicam cererea HTTP. Defensiv
        # (executia curenta e single-threaded), dar corect si ieftin.
        acquired = self._request_manager.try_acquire_inflight(self.PROVIDER_ID, cache_category, cache_key)
        if not acquired:
            logger.debug("[ApiFootball] cerere deja in curs pentru %s/%s — sar peste duplicat", cache_category, cache_key)
            return None

        try:
            # 5. HTTP request — abia acum, dupa TOATE verificarile de mai sus
            headers = self._key_manager.get_headers(self.PROVIDER_ID)
            if headers is None:
                return None

            start = time.monotonic()
            success = False
            data = None
            response_headers = None
            status_code = None
            caught_exc = None
            try:
                session = self._get_session()
                r = session.get(f"{self.BASE_URL}/{path}", headers=headers, params=params, timeout=12)
                success = r.ok
                status_code = r.status_code
                response_headers = r.headers
                if success:
                    data = r.json()
                else:
                    logger.warning("[ApiFootball] HTTP %s pentru %s", r.status_code, path)
            except Exception as exc:
                logger.error("[ApiFootball] Eroare request %s: %s", path, exc)
                caught_exc = exc
            latency_ms = (time.monotonic() - start) * 1000

            self._key_manager.record_request(self.PROVIDER_ID)
            # [ADAUGAT R4.1] Buget real din header-ele oficiale de raspuns
            # (audit §5/§7) — sursa de adevar mai precisa decat aproximarea
            # lunara existenta in key_manager.py, neatinsa.
            if response_headers is not None:
                self._request_manager.record_response_headers(self.PROVIDER_ID, response_headers)

            # [ADAUGAT ADR-041 Faza 2, Sprint 1.1 #3] breakdown 429/403/
            # timeout/5xx — clasificare doar la esec, punct unic reutilizat.
            failure_reason = None
            if not success:
                from provider_call_classification import classify_failure
                status_code, failure_reason = classify_failure(status_code, exc=caught_exc)

            # 7. actualizare provider_metrics
            try:
                import supabase_client as _sb
                _sb.record_provider_call(self.PROVIDER_ID, path, success, latency_ms,
                                          http_status=status_code, failure_reason=failure_reason)
            except Exception:
                pass

            # 6. actualizare cache (doar la succes real)
            if success and data is not None:
                self._cache.set(cache_category, cache_key, data, provider=self.PROVIDER_ID)
                self._request_manager.set_ram(self.PROVIDER_ID, cache_category, cache_key, data)

            return data
        finally:
            self._request_manager.release_inflight(self.PROVIDER_ID, cache_category, cache_key)

    # ── Rezolvare ID echipă (necesar pentru get_injuries/get_coaches) ────
    def resolve_team_id(self, team_name: str) -> int | None:
        """
        API-Football identifică echipele prin ID-ul lui numeric propriu,
        diferit de ID-urile FreeLF/ESPN/football-data.org deja folosite în
        proiect — nu exista nicaieri altundeva o mapare nume->ID pt acest
        provider, de aceea rezolvarea se face live, prin `/teams?search=`.

        [NOTĂ DE INCERTITUDINE] Structura `/teams` NU a fost confirmată
        dintr-un payload real (aceeași limitare ca la `/injuries`) — parsare
        defensivă, cache-uit pe termen lung (720h) fiindcă ID-urile de
        echipă nu se schimbă practic niciodată, deci un rezultat greșit
        cache-uit ar persista mult — motiv în plus să fie validat live cât
        mai curând posibil.
        """
        if not self._healthy():
            return None
        cache_key = f"team_id:{team_name.strip().lower()}"
        raw = self._get("teams", {"search": team_name}, "teams", cache_key)
        if not raw or not raw.get("response"):
            return None
        first = raw["response"][0]
        if not isinstance(first, dict):
            logger.warning("[ApiFootball] /teams — element neasteptat (nu e dict): %r", first)
            return None
        team_obj = first.get("team") or {}
        team_id = team_obj.get("id")
        if team_id is None:
            logger.warning(
                "[ApiFootball] /teams — nu s-a gasit 'team.id' in raspuns pt %r, "
                "structura reala difera de presupunere: %r", team_name, first
            )
            return None
        try:
            return int(team_id)
        except (TypeError, ValueError):
            return None

    # ── Injuries ──────────────────────────────────────────────────────────
    def get_injuries(self, team_name: str, team_id: int | str, league: str, season: int | None = None) -> list[Injury]:
        # [REPARAT] Descoperit live: API-Football intoarce HTTP 200 cu
        # {"errors":{"season":"The Season field is required."}} daca lipseste
        # 'season' - nu era documentat/confirmat inainte, gasit direct din
        # payload-ul real cache-uit in productie.
        if not self._covered(league, "api_football"):
            return []
        if season is None:
            from datetime import date as _date
            season = _date.today().year
        cache_key = f"{league}:{team_id}:injuries:{season}"
        raw = self._get("injuries", {"team": team_id, "season": season}, "injuries", cache_key)
        if not raw or "response" not in raw:
            if raw and raw.get("errors"):
                logger.warning("[ApiFootball] /injuries a intors erori: %r", raw["errors"])
            return []
        results = []
        for item in raw["response"]:
            injury = self._normalize_injury(item, team_name)
            if injury is not None:
                results.append(injury)
        return results

    def _normalize_injury(self, item: dict, team_name_fallback: str) -> Injury | None:
        if not isinstance(item, dict):
            logger.warning("[ApiFootball] /injuries — element neașteptat (nu e dict): %r", item)
            return None
        player = item.get("player") or {}
        team = item.get("team") or {}
        fixture = item.get("fixture") or {}
        injury_type = item.get("type") or player.get("type")
        reason = item.get("reason") or player.get("reason")
        if injury_type is None and reason is None:
            logger.warning(
                "[ApiFootball] /injuries — nici 'type' nici 'reason' găsite, "
                "structura reală diferă de presupunere — verifică payload-ul brut: %r", item
            )
        return Injury(
            player_name=player.get("name", "necunoscut"),
            team_name=team.get("name", team_name_fallback),
            injury_type=injury_type or "necunoscut",
            reason=reason or "necunoscut",
            player_id=str(player["id"]) if player.get("id") is not None else None,
            fixture_id=str(fixture["id"]) if fixture.get("id") is not None else None,
            source_provider=self.PROVIDER_ID,
        )

    # ── Fixtures — fallback generic, orice ligă cu provider_ids["api_football"]
    #    setat în mappings.py (nu doar Romania SuperLiga) ────────────────
    def get_fixtures(self, league: str, league_id: int, date_from: str, date_to: str, season: int) -> list[dict]:
        """
        Fixtures viitoare pentru o ligă, prin /fixtures?league=&season=&from=&to=.
        Generic — orice ligă cu provider_ids["api_football"] completat în
        mappings.py devine eligibilă automat, fără nicio schimbare aici.
        Folosit DOAR ca fallback (ultimul, înainte de demo mode) pentru
        ligi fără acoperire suficientă la ceilalți provideri, niciodată ca
        sursă primară — vezi ordinea din oracle_api.get_matches_for_week().
        Același mecanism (_get) ca get_injuries/get_coaches: health check
        -> coverage check -> cache L1+L2 -> HTTP -> cache+metrics update.
        """
        if not self._covered(league, "api_football"):
            return []
        cache_key = f"{league}:{league_id}:fixtures:{date_from}:{date_to}:{season}"
        raw = self._get(
            "fixtures",
            {"league": league_id, "season": season, "from": date_from, "to": date_to},
            "matches", cache_key,
        )
        if not raw or "response" not in raw:
            if raw and raw.get("errors"):
                logger.warning("[ApiFootball] /fixtures a intors erori: %r", raw["errors"])
            return []
        results = []
        for item in raw["response"]:
            fx = self._normalize_fixture(item, league, season)
            if fx is not None:
                results.append(fx)
        return results

    def _normalize_fixture(self, item: dict, league: str, season: int) -> dict | None:
        if not isinstance(item, dict):
            logger.warning("[ApiFootball] /fixtures — element neasteptat (nu e dict): %r", item)
            return None
        from mappings import normalize_team_name

        fixture = item.get("fixture") or {}
        teams = item.get("teams") or {}
        home_team = teams.get("home") or {}
        away_team = teams.get("away") or {}
        home = normalize_team_name(home_team.get("name", "") or "")
        away = normalize_team_name(away_team.get("name", "") or "")
        if not home or not away:
            logger.warning(
                "[ApiFootball] /fixtures — echipe lipsa/necompletate, structura "
                "reala difera de presupunere: %r", item
            )
            return None
        kickoff_utc = fixture.get("date", "") or ""
        fixture_id = fixture.get("id")
        if fixture_id is None:
            logger.warning(
                "[ApiFootball] /fixtures — 'fixture.id' lipsa, structura reala "
                "difera de presupunere, meci ignorat: %r", item
            )
            return None
        return {
            "fixture_id":    f"apifootball_{fixture_id}",
            "home_team":     home, "away_team": away,
            "home_team_id":  f"apifootball_{home_team.get('id', '')}",
            "away_team_id":  f"apifootball_{away_team.get('id', '')}",
            "kickoff_utc":   kickoff_utc,
            "kickoff_date":  kickoff_utc[:10] if kickoff_utc else "",
            "league":        league, "season": season,
            "venue_city":    (fixture.get("venue") or {}).get("city", "") or "",
            "status":        "scheduled", "coverage_level": "",
            "home_odds":     None, "draw_odds": None, "away_odds": None,
            "odds_source":   None, "source": self.PROVIDER_ID,
        }

    # ── Coaches — structură confirmată exact din documentație ────────────
    def get_coaches(self, team_name: str, team_id: int | str, league: str) -> list[CoachInfo]:
        # [REPARAT R4.1] Defect real confirmat prin audit (§16, §4): singurul
        # apel din get_injuries()/get_fixtures() care NU verifica _covered()
        # inainte de HTTP - o cerere se putea declansa pentru o liga marcata
        # explicit nesuportata, consumand cota zilnica fara rost. Aliniat
        # acum la exact acelasi tipar deja folosit de get_injuries().
        if not self._covered(league, "api_football"):
            return []
        cache_key = f"team:{team_id}:coaches"
        raw = self._get("coachs", {"team": team_id}, "coaches", cache_key)
        if not raw or "response" not in raw:
            return []
        return [self._normalize_coach(item, team_name) for item in raw["response"]]

    def _normalize_coach(self, item: dict, team_name_fallback: str) -> CoachInfo:
        team = item.get("team") or {}
        appointed_date = None
        for stint in item.get("career") or []:
            if stint.get("end") is None:
                appointed_date = stint.get("start")
                break
        return CoachInfo(
            coach_id=str(item.get("id", "necunoscut")),
            name=item.get("name", "necunoscut"),
            team_name=team.get("name", team_name_fallback),
            appointed_date=appointed_date,
            nationality=item.get("nationality"),
            source_provider=self.PROVIDER_ID,
        )
