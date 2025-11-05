# -*- coding: utf-8 -*-
# utils/get_previus_matches.py
"""
Obtiene los X partidos previos a una fecha (dd/mm/aa) para un club.
Estrategia por capas y de bajo consumo de requests:

PRIMARIO -> TheSportsDB v1
  1) searchteams.php (resuelve idTeam; cache en disco).
  2) eventsseason.php (SOLO temporada de corte; si falta, 1 temporada anterior).
  3) Si aún faltan, eventslast.php para completar.
  * Filtra SIEMPRE por fecha < cutoff y por eventos con marcador.

FALLBACK -> FBref (solo páginas del equipo)
  4) fbref search -> URL base /en/squads/<id>/...
  5) “Scores & Fixtures” SOLO de la(s) temporada(s) necesaria(s)
  * Parse robusto del <table> (incluye tablas comentadas).
  * Sin visitar páginas gigantes de competiciones (reduce 429).

Devuelve: List[utils.Result.Result] con (home_slug, away_slug, gH, gA, date_obj),
ordenados del más reciente al más antiguo, y exactamente X elementos (si es posible).

Requisitos:
- utils.Result.Result
- utils.team_aliases.unslug_team
"""

from __future__ import annotations

import os
import re
import json
import time
import random
import unicodedata
from datetime import datetime
from typing import Optional, List, Dict, Tuple, Iterable

import requests
import requests_cache
from bs4 import BeautifulSoup, Comment

from utils.Result import Result
from utils.unslug_team import unslug_team

# -------------------------------------------------------------------
# Configuración general
# -------------------------------------------------------------------
# TheSportsDB
TSDB_API_KEY = "123"
TSDB_BASE = f"https://www.thesportsdb.com/api/v1/json/{TSDB_API_KEY}"

# HTTP
REQ_TIMEOUT = 15
HTTP_CACHE_NAME = "sports_http_cache"
HTTP_CACHE_TTL = 86400  # 24h

# TSDB: límites conservadores para evitar 429
RATE_MIN_INTERVAL = 0.45   # seg entre requests
TSDB_MAX_SEASONS = 2       # temporada de corte + 1 anterior
EVENTSLAST_ENABLE = True   # usar eventslast como complemento (1 request)

# FBref
FBREF_SEARCH_BASE = "https://fbref.com/en/search/search.fcgi?search="
FBREF_ROOT = "https://fbref.com"

# Cachés persistentes pequeñas
DATA_DIR = "./data"
os.makedirs(DATA_DIR, exist_ok=True)
TSDB_TEAM_CACHE = os.path.join(DATA_DIR, "tsdb_teams_cache.json")
FBREF_TEAM_CACHE = os.path.join(DATA_DIR, "fbref_teams_cache.json")

# Inicializa caché HTTP (GET) 24h
requests_cache.install_cache(HTTP_CACHE_NAME, expire_after=HTTP_CACHE_TTL)

# -------------------------------------------------------------------
# Utilidades de normalización / slugs
# -------------------------------------------------------------------
def _normalize(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[\s\.\-’'`_]+", "", s)

def slugify_team(name: str) -> str:
    cleaned = _normalize(name)
    aliases = {
        # España
        "elche":"el",
        "realmadrid":"rma","fcbarcelona":"bar","barcelona":"bar","sevilla":"sev",
        "atleticodemadrid":"atm","atleticomadrid":"atm","valencia":"val","villarreal":"vil",
        "realbetis":"bet","girona":"gir","getafe":"get","realsociedad":"soc",
        "athleticclub":"ath","athleticbilbao":"ath","osasuna":"osa",
        "celtadevigo":"cel","celtavigo":"cel","rayovallecano":"ray","udlaspalmas":"lpa",
        "alaves":"ala","deportivoalaves":"ala","granadacf":"gra","realvalladolid":"rvad",
        "rcdmallorca":"mlr","cadiz":"cad","leganes":"leg","sportingdegijon":"spo","sportinggijon":"spo",
        # Inglaterra
        "manchesterunited":"mun","manchestercity":"mci","chelsea":"che","liverpool":"liv",
        "arsenal":"ars","tottenhamhotspur":"tot","newcastleunited":"new","westhamunited":"whu",
        "astonvilla":"avl","everton":"eve","leicestercity":"lei","brightonandhovealbion":"bha",
        "brentford":"bre","bournemouth":"bou","crystalpalace":"cry","fulham":"ful","wolverhamptonwanderers":"wol",
        "nottinghamforest":"for","ipswichtown":"ips","southampton":"sou",
        # Italia
        "juventus":"juv","internazionale":"int","inter":"int","acmilan":"mil","milan":"mil",
        "napoli":"nap","asroma":"rom","roma":"rom","sslazio":"laz","lazio":"laz",
        "atalanta":"ata","fiorentina":"fio","torino":"tor","bologna":"bol","genoa":"gen",
        "sampdoria":"sam","cagliari":"cag","empoli":"emp","udinese":"udi","monza":"mon","lecce":"lec","sassuolo":"sas",
        # Alemania
        "bayernmunchen":"bay","bayernmunich":"bay","borussiadortmund":"bvb","rbleipzig":"rbl",
        "bayerleverkusen":"lev","borussiamonchengladbach":"bmg","borussiamönchengladbach":"bmg",
        "vfbstuttgart":"vfb","vflwolfsburg":"wob","eintrachtfrankfurt":"sge","freiburg":"scf",
        "werderbremen":"svw","unionberlin":"uni","fcunionberlin":"uni","augsburg":"fca","koln":"fck","1fckoln":"fck",
        # Francia
        "parissaintgermain":"psg","psg":"psg","olympiquemarseille":"om","olympiquelyonnais":"lyo",
        "monaco":"mon","lille":"lil","nice":"nic","rennes":"ren","nantes":"nan","montpellier":"monp",
        "bordeaux":"gir","lens":"rcl","strasbourg":"rcs","toulouse":"tou","reims":"rei",
    }
    return aliases.get(cleaned, cleaned[:3] if len(cleaned) >= 3 else cleaned)

# -------------------------------------------------------------------
# Helpers comunes (HTTP)
# -------------------------------------------------------------------
_UA = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36",
]
def _headers():
    return {
        "User-Agent": random.choice(_UA),
        "Accept-Language": "en-US,en;q=0.9,es;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Referer": "https://google.com",
    }

_LAST_TS = 0.0
def _polite_pause():
    global _LAST_TS
    now = time.monotonic()
    delta = RATE_MIN_INTERVAL - (now - _LAST_TS)
    if delta > 0:
        time.sleep(delta + random.uniform(0, 0.12))
    _LAST_TS = time.monotonic()

def _get_json(url: str, debug=False, max_retries=2, total_budget=6.0) -> Optional[dict]:
    """
    GET JSON con rate-limit local y backoff breve ante 429/5xx.
    Nunca excede 'total_budget' por llamada.
    """
    start = time.monotonic()
    attempt = 0
    while True:
        _polite_pause()
        try:
            r = requests.get(url, headers=_headers(), timeout=REQ_TIMEOUT)
            if debug:
                code = r.status_code
                from_cache = getattr(r, "from_cache", False)
                print(f"[TSDB] {code} {'(cache)' if from_cache else ''} {url}")
            r.raise_for_status()
            return r.json()
        except requests.HTTPError as he:
            status = getattr(he.response, "status_code", None)
            if status in (429, 500, 502, 503, 504) and attempt < max_retries:
                wait = 1.1 + 0.9 * random.random()
                if time.monotonic() - start + wait > total_budget:
                    if debug: print("[TSDB] presupuesto excedido; abort.")
                    return None
                if debug: print(f"[TSDB] backoff {wait:.1f}s")
                time.sleep(wait)
                attempt += 1
                continue
            if debug:
                print(f"[TSDB][err] {he} @ {url}")
            return None
        except Exception as e:
            if debug:
                print(f"[TSDB][err] {e} @ {url}")
            return None

def _robust_get(url: str, debug=False, max_retries=2, base_delay=1.2, total_budget=8.0) -> Optional[requests.Response]:
    """
    GET HTML plano con backoff y rate-limit.
    """
    start = time.monotonic()
    for i in range(max_retries + 1):
        _polite_pause()
        try:
            r = requests.get(url, headers=_headers(), timeout=REQ_TIMEOUT, allow_redirects=True)
            if debug:
                code = r.status_code
                from_cache = getattr(r, "from_cache", False)
                print(f"[GET] {code} {'(cache)' if from_cache else ''} {url}")
            if r.status_code in (429,) or (500 <= r.status_code < 600):
                wait = min(base_delay * (2 ** i) + random.uniform(0, 0.6), 6.0)
                if time.monotonic() - start + wait > total_budget:
                    if debug: print("[GET] presupuesto excedido; abort.")
                    return None
                if debug: print(f"[backoff] {r.status_code} -> sleep {wait:.1f}s")
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r
        except Exception as e:
            if debug: print(f"[GET-err] {e} @ {url}")
            time.sleep(min(base_delay * (2 ** i) + random.uniform(0, 0.5), 4.0))
    return None

def _pick_parser() -> str:
    try:
        import lxml  # noqa
        return "lxml"
    except Exception:
        return "html.parser"

# -------------------------------------------------------------------
# Persistencia simple (TSDB / FBref)
# -------------------------------------------------------------------
def _load_json(path: str) -> dict:
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def _save_json(path: str, data: dict) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

# -------------------------------------------------------------------
# TheSportsDB capa primaria
# -------------------------------------------------------------------
def _tsdb_resolve_team(slug_equipo: str, debug=False) -> Optional[Tuple[str, str]]:
    """
    Resuelve (idTeam, strTeam) en TSDB usando el nombre canónico via unslug_team.
    Cache persistente: data/tsdb_teams_cache.json
    """
    cache = _load_json(TSDB_TEAM_CACHE)
    s = slug_equipo.strip().lower()
    if s in cache and cache[s] and len(cache[s]) == 2:
        return cache[s][0], cache[s][1]

    name = unslug_team(s) or s  # mejor nombre desde JSON de alias, o el slug si no hay
    url = f"{TSDB_BASE}/searchteams.php?t={requests.utils.quote(name)}"
    data = _get_json(url, debug=debug)
    teams = (data or {}).get("teams") or []
    if not teams:
        # Intento extra: a veces conviene quitar prefijos 'FC', 'CF', etc.
        name2 = re.sub(r"^(fc|cf|sc|ac|club)\s+", "", name, flags=re.I).strip()
        if name2 and name2 != name:
            url2 = f"{TSDB_BASE}/searchteams.php?t={requests.utils.quote(name2)}"
            data2 = _get_json(url2, debug=debug)
            teams = (data2 or {}).get("teams") or []

    if not teams:
        return None

    # Elegir mejor match por normalización
    target = _normalize(name)
    best = None
    for t in teams:
        nm = t.get("strTeam") or ""
        if _normalize(nm) == target:
            best = t
            break
    if not best:
        best = teams[0]

    if best and best.get("idTeam"):
        out = (best["idTeam"], best.get("strTeam") or name)
        cache[s] = [out[0], out[1]]
        _save_json(TSDB_TEAM_CACHE, cache)
        return out
    return None

def _season_str_for_date(d: datetime) -> str:
    year = d.year if d.month >= 7 else d.year - 1
    return f"{year}-{year+1}"

def _parse_tsdb_event(ev: dict) -> Optional[Tuple[datetime, str, str, str]]:
    """
    Retorna (fecha, 'home-away', 'gH-gA', idEvent) si tiene marcador.
    """
    try:
        date_iso = (ev.get("dateEvent") or "").strip()
        if not date_iso:
            return None
        mdate = datetime.strptime(date_iso, "%Y-%m-%d")
        h = slugify_team(ev.get("strHomeTeam") or "")
        a = slugify_team(ev.get("strAwayTeam") or "")
        gH = ev.get("intHomeScore")
        gA = ev.get("intAwayScore")
        if gH is None or gA is None or str(gH) == "" or str(gA) == "":
            return None
        score = f"{int(gH)}-{int(gA)}"
        ide = str(ev.get("idEvent") or f"{h}-{a}-{date_iso}")
        return (mdate, f"{h}-{a}", score, ide)
    except Exception:
        return None

def _tsdb_collect_previous(id_team: str, cutoff: datetime, need: int, debug=False) -> List[Tuple[datetime, str, str]]:
    """
    Toma SOLO temporadas pertinentes (temporada del cutoff y 1 anterior) y opcionalmente eventslast.
    Devuelve lista de (fecha, slugMatch, score) ordenada desc, recortada a 'need'.
    """
    pool: Dict[str, Tuple[datetime, str, str]] = {}
    seasons: List[str] = []

    season_now = _season_str_for_date(cutoff)
    try:
        y0 = int(season_now.split("-")[0])
    except Exception:
        y0 = cutoff.year

    for i in range(TSDB_MAX_SEASONS):
        seasons.append(f"{y0 - i}-{y0 - i + 1}")

    # 1) temporadas clave
    for s in seasons:
        if len(pool) >= need:
            break
        url = f"{TSDB_BASE}/eventsseason.php?id={id_team}&s={requests.utils.quote(s)}"
        data = _get_json(url, debug=debug)
        rows = (data or {}).get("events") or []
        for ev in rows:
            pr = _parse_tsdb_event(ev)
            if not pr:
                continue
            mdate, ms, sc, ide = pr
            if mdate >= cutoff:
                continue
            if ide not in pool:
                pool[ide] = (mdate, ms, sc)
        # no seguimos si ya completamos
        if len(pool) >= need:
            break

    # 2) eventslast (solo si falta completar y está activado)
    if EVENTSLAST_ENABLE and len(pool) < need:
        url = f"{TSDB_BASE}/eventslast.php?id={id_team}"
        data = _get_json(url, debug=debug)
        rows = (data or {}).get("results") or (data or {}).get("events") or []
        for ev in rows:
            pr = _parse_tsdb_event(ev)
            if not pr:
                continue
            mdate, ms, sc, ide = pr
            if mdate >= cutoff:
                continue
            if ide not in pool:
                pool[ide] = (mdate, ms, sc)

    # Orden desc y recorte
    out = sorted(pool.values(), key=lambda t: t[0], reverse=True)[:need]
    return out

# -------------------------------------------------------------------
# FBref fallback (solo páginas del equipo)
# -------------------------------------------------------------------
def _fbref_resolve_team_root(team_name: str, debug=False) -> Optional[str]:
    """
    Devuelve la URL base '/en/squads/<id>/' del equipo buscando por nombre.
    Cache: data/fbref_teams_cache.json
    """
    cache = _load_json(FBREF_TEAM_CACHE)
    key = _normalize(team_name)
    if key in cache:
        return cache[key]

    parser = _pick_parser()
    url = f"{FBREF_SEARCH_BASE}{requests.utils.quote(team_name)}"
    r = _robust_get(url, debug=debug)
    if not r:
        return None

    # Si redirige directo a /en/squads/...
    if "/en/squads/" in r.url:
        cache[key] = r.url
        _save_json(FBREF_TEAM_CACHE, cache)
        return r.url

    soup = BeautifulSoup(r.text, parser)
    for a in soup.find_all("a", href=True):
        h = a["href"]
        if h.startswith("/en/squads/") and "/players/" not in h and "/matchlogs/" not in h:
            absu = FBREF_ROOT + h
            cache[key] = absu
            _save_json(FBREF_TEAM_CACHE, cache)
            return absu
    return None

def _fbref_find_scores_fixtures_urls(team_root_url: str, seasons: Iterable[int], debug=False) -> List[str]:
    """
    Desde la home del equipo, localiza los enlaces a 'Scores & Fixtures' para las temporadas requeridas.
    """
    urls: List[str] = []
    parser = _pick_parser()
    r = _robust_get(team_root_url, debug=debug)
    if not r:
        return urls

    soup = BeautifulSoup(r.text, parser)
    a_tags = soup.find_all("a", href=True)
    hrefs = [(a.get_text(strip=True), a["href"]) for a in a_tags]

    def _to_abs(h: str) -> str:
        return FBREF_ROOT + h if h.startswith("/") else h

    for year in seasons:
        season_str = f"{year}-{year+1}"
        cand = None
        for text, h in hrefs:
            txt = (text or "").lower()
            href_l = h.lower()
            if "scores" in txt and "fixture" in txt and season_str in href_l:
                cand = _to_abs(h); break
            if season_str in href_l and ("schedule" in href_l or "matchlogs" in href_l):
                cand = _to_abs(h); break
        if cand:
            urls.append(cand)

    # Fallback: si no hubiera temporada explícita, primer "Scores & Fixtures"
    if not urls:
        for text, h in hrefs:
            txt = (text or "").lower()
            if "scores" in txt and "fixture" in txt:
                urls.append(_to_abs(h))
                break
    return urls

def _fbref_parse_scores_fixtures(url: str, cutoff: datetime, debug=False) -> List[Tuple[datetime, str, str]]:
    """
    Parse de la tabla de 'Scores & Fixtures' de una temporada concreta.
    Devuelve lista de (fecha, 'home-away', 'gH-gA') solo con partidos < cutoff con score.
    """
    out: List[Tuple[datetime, str, str]] = []
    parser = _pick_parser()
    r = _robust_get(url, debug=debug)
    if not r:
        return out
    soup = BeautifulSoup(r.text, parser)

    def _iter_rows(s):
        for tr in s.select("table tbody tr"):
            yield tr

    rows = list(_iter_rows(soup))
    if not rows:
        # Tablas comentadas
        for c in soup.find_all(string=lambda t: isinstance(t, Comment) and "<table" in t):
            sub = BeautifulSoup(c, parser)
            rows = list(_iter_rows(sub))
            if rows:
                break

    for tr in rows:
        date_td = tr.find("td", {"data-stat": "date"})
        home_td = tr.find("td", {"data-stat": "home_team"})
        away_td = tr.find("td", {"data-stat": "away_team"})
        score_td = tr.find("td", {"data-stat": "score"})
        if not (date_td and home_td and away_td and score_td):
            continue

        raw = (date_td.get_text(strip=True) or "")[:10]
        try:
            mdate = datetime.strptime(raw, "%Y-%m-%d")
        except Exception:
            continue
        if not (mdate < cutoff):
            continue

        h = slugify_team(home_td.get_text(strip=True))
        a = slugify_team(away_td.get_text(strip=True))
        score = score_td.get_text(strip=True)
        if not score:
            continue
        score = re.sub(r"\s*–\s*", "-", score)
        if not re.match(r"^\d+\s*-\s*\d+$", score):
            continue

        out.append((mdate, f"{h}-{a}", score))
    return out

def _fbref_collect_previous(team_name: str, cutoff: datetime, need: int, debug=False) -> List[Tuple[datetime, str, str]]:
    """
    Recolecta desde FBref solo la(s) temporada(s) pertinentes (corte y anterior como mucho).
    """
    root = _fbref_resolve_team_root(team_name, debug=debug)
    if not root:
        return []

    base_year = cutoff.year if cutoff.month >= 7 else cutoff.year - 1
    seasons = [base_year, base_year - 1]  # corte y 1 anterior
    urls = _fbref_find_scores_fixtures_urls(root, seasons, debug=debug)
    pool: List[Tuple[datetime, str, str]] = []
    for u in urls:
        pool.extend(_fbref_parse_scores_fixtures(u, cutoff, debug=debug))
        if len(pool) >= need:
            break

    pool.sort(key=lambda t: t[0], reverse=True)
    return pool[:need]

# -------------------------------------------------------------------
# API principal
# -------------------------------------------------------------------
def get_previus_matches(slug_equipo: str, fecha: str, X: int, debug: bool=False) -> List[Result]:
    """
    Retorna los X partidos previos (antes de 'fecha' dd/mm/aa') para el equipo (slug corto),
    cruzando todas las competiciones. Ordenados del más reciente al más antiguo.

    Prioriza TheSportsDB (pocas llamadas) y cae a FBref si falta completar.
    """
    # Validaciones
    if not isinstance(X, int) or X <= 0:
        raise ValueError("X debe ser un entero > 0.")
    X = min(X, 10)  # tope razonable

    try:
        cutoff = datetime.strptime(fecha, "%d/%m/%y")
    except ValueError:
        raise ValueError("La fecha debe ser dd/mm/aa (ej. '20/10/25').")

    team_slug = (slug_equipo or "").strip().lower()
    if not team_slug:
        return []

    # -------------------------
    # 1) Capa TSDB (rápida)
    # -------------------------
    out_rows: List[Tuple[datetime, str, str]] = []
    tsdb_team = _tsdb_resolve_team(team_slug, debug=debug)
    if tsdb_team:
        id_team, team_name = tsdb_team
        if debug: print(f"[TSDB] Team: {team_name} -> id={id_team}")
        try:
            ts_rows = _tsdb_collect_previous(id_team, cutoff, X, debug=debug)
            out_rows.extend(ts_rows)
        except Exception as e:
            if debug: print(f"[TSDB][collect err] {e}")

    # Si ya tenemos suficientes, devolvemos
    out_rows.sort(key=lambda t: t[0], reverse=True)
    out_rows = out_rows[:X]

    # -------------------------
    # 2) Fallback FBref (completar si faltan)
    # -------------------------
    if len(out_rows) < X:
        # nombre canónico para FBref
        canon_name = unslug_team(team_slug) or team_slug
        try:
            fb_rows = _fbref_collect_previous(canon_name, cutoff, X - len(out_rows), debug=debug)
            out_rows.extend(fb_rows)
            # de-duplicar por (fecha, slugMatch)
            seen = set()
            dedup: List[Tuple[datetime, str, str]] = []
            for dt, ms, sc in sorted(out_rows, key=lambda t: t[0], reverse=True):
                key = (dt.date().isoformat(), ms)
                if key in seen:
                    continue
                seen.add(key)
                dedup.append((dt, ms, sc))
            out_rows = dedup[:X]
        except Exception as e:
            if debug: print(f"[FBref][collect err] {e}")

    # Construcción de Result
    out: List[Result] = []
    for dt, ms, sc in out_rows:
        try:
            h, a = ms.split("-")
            gH, gA = sc.split("-")
            out.append(Result(h, a, gH, gA, dt))
        except Exception:
            continue

    return out
