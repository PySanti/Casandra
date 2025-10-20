# -*- coding: utf-8 -*-
# utils/get_previus_matches.py
"""
Obtiene los X partidos previos a una fecha (dd/mm/aa) para un club
desde TheSportsDB V1, cruzando todas las competiciones, evitando 429.

Estrategia:
  1) searchteams.php (con caché en disco para idTeam)
  2) eventslast.php?id={idTeam}
  3) eventsseason.php?id={idTeam}&s=YYYY-YYYY (temporada de la fecha y previas) hasta llenar X
  4) SIN eventsday.php (se elimina el barrido diario que dispara 429)

Devuelve: List[utils.Result.Result] con (home_slug, away_slug, gH, gA, date_obj).
"""

import re
import os
import json
import time
import random
import unicodedata
from datetime import datetime
from typing import Optional, List, Dict, Tuple

import requests
import requests_cache

from utils.Result import Result

# -------------------------------------------------------------------
# Config
# -------------------------------------------------------------------
API_KEY = "123"
BASE = f"https://www.thesportsdb.com/api/v1/json/{API_KEY}"
REQ_TIMEOUT = 15
RATE_MIN_INTERVAL = 0.35   # segundos entre requests (muy conservador)
MAX_X = 10
MAX_SEASONS_BACK = 6       # tope de temporadas a mirar hacia atrás
HTTP_CACHE_NAME = "tsdb_cache"
HTTP_CACHE_TTL = 86400     # 24h

# Cache local para idTeam (persistente en disco)
TEAM_ID_CACHE_FILE = "tsdb_teams_cache.json"
_team_cache: Dict[str, Tuple[str, str]] = {}   # slug -> (idTeam, strTeam)

# Cache HTTP 24h
requests_cache.install_cache(HTTP_CACHE_NAME, expire_after=HTTP_CACHE_TTL)

# -------------------------------------------------------------------
# HTTP helpers con rate-limit y backoff corto para 429
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
        "Referer": "https://www.thesportsdb.com/",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }

_LAST_TS = 0.0
def _polite_pause():
    global _LAST_TS
    now = time.monotonic()
    delta = RATE_MIN_INTERVAL - (now - _LAST_TS)
    if delta > 0:
        time.sleep(delta + random.uniform(0, 0.05))
    _LAST_TS = time.monotonic()

def _get_json(url: str, debug=False, max_retries=2, total_budget=6.0) -> Optional[dict]:
    """
    GET JSON con:
      - rate limit local
      - backoff muy corto específico para 429
      - presupuesto total por llamada para no bloquear
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
            if status == 429 and attempt < max_retries:
                # Backoff corto y aleatorio (1.2–2.2s) pero respetando presupuesto total
                wait = 1.2 + random.uniform(0, 1.0)
                if time.monotonic() - start + wait > total_budget:
                    if debug: print("[TSDB][429] presupuesto excedido, abort.")
                    return None
                if debug: print(f"[TSDB][429] backoff {wait:.1f}s")
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

# -------------------------------------------------------------------
# Normalización / slugs
# -------------------------------------------------------------------
def _normalize(s: str) -> str:
    norm = unicodedata.normalize("NFKD", s or "")
    cleaned = "".join(c for c in norm if not unicodedata.combining(c)).lower()
    return re.sub(r"[\s\.\-’'`_]+", "", cleaned)

def slugify_team(name: str) -> str:
    cleaned = _normalize(name)
    aliases = {
        # España
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

# Nombres canónicos para buscar en TheSportsDB a partir del slug
NAME_BY_SLUG: Dict[str, List[str]] = {
    "bar": ["FC Barcelona", "Barcelona"],
    "rma": ["Real Madrid"],
    "sev": ["Sevilla", "Sevilla FC"],
    "atm": ["Atlético de Madrid", "Atletico Madrid"],
    "soc": ["Real Sociedad"],
    "ath": ["Athletic Club", "Athletic Bilbao"],
    "bet": ["Real Betis"],
    "vil": ["Villarreal", "Villarreal CF"],
    "val": ["Valencia", "Valencia CF"],
    "cel": ["Celta Vigo", "Celta de Vigo"],
    "ray": ["Rayo Vallecano"],
    "gir": ["Girona", "Girona FC"],
    "get": ["Getafe", "Getafe CF"],
    "mlr": ["Mallorca", "RCD Mallorca"],
    "lpa": ["Las Palmas", "UD Las Palmas"],
    "ala": ["Alaves", "Deportivo Alavés", "Deportivo Alaves"],
    "gra": ["Granada", "Granada CF"],
    "osa": ["Osasuna", "CA Osasuna"],
}

def _pick_names_for_slug(slug: str) -> List[str]:
    if slug in NAME_BY_SLUG:
        return NAME_BY_SLUG[slug]
    return [slug]

# -------------------------------------------------------------------
# Caché en disco para idTeam
# -------------------------------------------------------------------
def _load_team_cache():
    global _team_cache
    if _team_cache:
        return
    if os.path.exists(TEAM_ID_CACHE_FILE):
        try:
            with open(TEAM_ID_CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                # form: {slug: [idTeam, strTeam]}
                _team_cache = {k: (v[0], v[1]) for k, v in data.items() if isinstance(v, list) and len(v) == 2}
        except Exception:
            _team_cache = {}

def _save_team_cache():
    if not _team_cache:
        return
    try:
        with open(TEAM_ID_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({k: [v[0], v[1]] for k, v in _team_cache.items()}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

# -------------------------------------------------------------------
# Resolución de idTeam (con caché persistente)
# -------------------------------------------------------------------
def _resolve_team_id(slug_equipo: str, debug: bool=False) -> Optional[Tuple[str, str]]:
    _load_team_cache()
    target_slug = slugify_team(slug_equipo)
    if target_slug in _team_cache:
        return _team_cache[target_slug]

    candidates = _pick_names_for_slug(target_slug)
    for name in candidates:
        url = f"{BASE}/searchteams.php?t={requests.utils.quote(name)}"
        data = _get_json(url, debug=debug)
        if not data or not data.get("teams"):
            continue
        best = None
        for t in data["teams"]:
            nm = t.get("strTeam") or ""
            if slugify_team(nm) == target_slug:
                best = t
                break
        if not best:
            best = data["teams"][0]
        if best and best.get("idTeam"):
            id_team = best["idTeam"]
            str_team = best.get("strTeam") or name
            _team_cache[target_slug] = (id_team, str_team)
            _save_team_cache()
            return id_team, str_team
    return None

# -------------------------------------------------------------------
# Recolectores de eventos
# -------------------------------------------------------------------
def _parse_event_row(ev: dict) -> Optional[Tuple[datetime, str, str, str]]:
    """
    Convierte un evento TSDB a (fecha, 'home-away', 'gH-gA', idEvent).
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
        ide = str(ev.get("idEvent") or f"{h}-{a}-{mdate.date().isoformat()}")
        return (mdate, f"{h}-{a}", score, ide)
    except Exception:
        return None

def _collect_from_eventslast(id_team: str, cutoff: datetime, need: int, debug=False) -> Dict[str, Tuple[datetime, str, str]]:
    pool: Dict[str, Tuple[datetime, str, str]] = {}
    url = f"{BASE}/eventslast.php?id={id_team}"
    data = _get_json(url, debug=debug)
    rows = (data or {}).get("results") or (data or {}).get("events") or []
    parsed = []
    for ev in rows or []:
        pr = _parse_event_row(ev)
        if not pr:
            continue
        mdate, ms, sc, ide = pr
        if mdate < cutoff:
            parsed.append((mdate, ms, sc, ide))
    parsed.sort(key=lambda t: t[0], reverse=True)
    for mdate, ms, sc, ide in parsed:
        if ide not in pool:
            pool[ide] = (mdate, ms, sc)
        if len(pool) >= need:
            break
    return pool

def _season_str_for_date(d: datetime) -> str:
    year = d.year if d.month >= 7 else d.year - 1
    return f"{year}-{year+1}"

def _collect_from_eventsseason(id_team: str, season: str, cutoff: datetime, need: int, debug=False) -> Dict[str, Tuple[datetime, str, str]]:
    """
    Recolecta una temporada concreta, corta en cuanto junta 'need'.
    """
    pool: Dict[str, Tuple[datetime, str, str]] = {}
    url = f"{BASE}/eventsseason.php?id={id_team}&s={requests.utils.quote(season)}"
    data = _get_json(url, debug=debug)
    rows = (data or {}).get("events") or []
    parsed = []
    for ev in rows:
        pr = _parse_event_row(ev)
        if not pr:
            continue
        mdate, ms, sc, ide = pr
        if mdate < cutoff:
            parsed.append((mdate, ms, sc, ide))
    parsed.sort(key=lambda t: t[0], reverse=True)
    for mdate, ms, sc, ide in parsed:
        if ide not in pool:
            pool[ide] = (mdate, ms, sc)
        if len(pool) >= need:
            break
    return pool

# -------------------------------------------------------------------
# API principal
# -------------------------------------------------------------------
def get_previus_matches(slug_equipo: str, fecha: str, X: int, debug: bool=False) -> List[Result]:
    """
    Retorna los X resultados previos (antes de 'fecha' dd/mm/aa') para el equipo (slug corto),
    cruzando todas las competiciones disponibles en TSDB V1. Sin eventsday.php.
    """
    # Validaciones
    if not isinstance(X, int) or X <= 0:
        raise ValueError("X debe ser un entero > 0.")
    X = min(X, MAX_X)

    try:
        cutoff = datetime.strptime(fecha, "%d/%m/%y")
    except ValueError:
        raise ValueError("La fecha debe ser dd/mm/aa (ej. '30/09/25').")

    team_slug = slugify_team(slug_equipo)

    # 1) Resolver idTeam (con caché persistente)
    resolved = _resolve_team_id(slug_equipo, debug=debug)
    if not resolved:
        if debug: print("[TSDB] No se pudo resolver idTeam para", slug_equipo)
        return []
    id_team, team_name = resolved
    if debug: print(f"[TSDB] Team: {team_name} -> id={id_team}")

    collected: Dict[str, Tuple[datetime, str, str]] = {}

    # 2) eventslast (1 request)
    need = X
    part = _collect_from_eventslast(id_team, cutoff, need, debug=debug)
    collected.update(part)
    if len(collected) >= X:
        rows = sorted(collected.values(), key=lambda t: t[0], reverse=True)[:X]
        return [Result(ms.split("-")[0], ms.split("-")[1], *sc.split("-"), dt) for dt, ms, sc in rows]

    # 3) seasons: actual y hacia atrás hasta MAX_SEASONS_BACK o completar X
    season_now = _season_str_for_date(cutoff)
    try:
        y0 = int(season_now.split("-")[0])
    except Exception:
        y0 = cutoff.year

    seasons = [f"{y0-i}-{y0-i+1}" for i in range(0, MAX_SEASONS_BACK)]
    for s in seasons:
        need = X - len(collected)
        if need <= 0:
            break
        part = _collect_from_eventsseason(id_team, s, cutoff, need, debug=debug)
        collected.update(part)

    # 4) Ordenar y cortar (sin fallback de días para evitar 429)
    rows = sorted(collected.values(), key=lambda t: t[0], reverse=True)[:X]
    out: List[Result] = []
    for dt, ms, sc in rows:
        h, a = ms.split("-")
        gH, gA = sc.split("-")
        out.append(Result(h, a, gH, gA, dt))
    return out
