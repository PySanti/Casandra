# utils/get_last_results.py
import re
import time
import random
from datetime import datetime, timedelta
from typing import List, Tuple, Optional
import unicodedata
from urllib.parse import quote
from utils.Result import Result

import requests
import requests_cache
from bs4 import BeautifulSoup, Comment

# ---- Cache 24h para no repetir peticiones ----
requests_cache.install_cache("fb_cache", expire_after=86400)

# ---- (Opcional) Mapa de competencias top-5 (no se usa en esta versión, pero lo dejamos por compat) ----
COMP_MAP = {
    "laliga": ("12", "La-Liga"),
    "premier": ("9", "Premier-League"),
    "seriea": ("11", "Serie-A"),
    "bundesliga": ("20", "Bundesliga"),
    "ligue1": ("13", "Ligue-1"),
}

# ---- UA rotativo / headers ----
UA = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0 Safari/537.36",
]
def _headers():
    return {
        "User-Agent": random.choice(UA),
        "Accept-Language": "en-US,en;q=0.9,es;q=0.8",
        "Referer": "https://google.com",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }

# ---- Parser HTML (fallback si no hay lxml) ----
def _pick_parser():
    try:
        import lxml  # noqa
        return "lxml"
    except Exception:
        return "html.parser"

# ---- Normalización / slugs de equipos ----
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

# ---- Deducción de liga probable por slug (se deja por compat, no se usa en esta versión) ----
def guess_leagues_for_slug(team_slug: str) -> List[str]:
    s = team_slug.lower()
    if s in {"bar","rma","sev","atm","val","vil","bet","gir","get","soc","ath","osa","cel","ray","lpa","ala","gra","rvad","mlr","cad","leg","spo"}:
        return ["laliga"]
    if s in {"liv","che","ars","mci","mun","tot","new","whu","avl","eve","lei","bha","bre","bou","cry","ful","wol","for","ips","sou"}:
        return ["premier"]
    if s in {"juv","int","mil","nap","rom","laz","ata","fio","tor","bol","gen","sam","cag","emp","udi","mon","lec","sas"}:
        return ["seriea"]
    if s in {"bay","bvb","rbl","lev","bmg","vfb","wob","sge","scf","svw","uni","fca","fck"}:
        return ["bundesliga"]
    if s in {"psg","om","lyo","mon","lil","nic","ren","nan","monp","gir","rcl","rcs","tou","rei"}:
        return ["ligue1"]
    return ["laliga", "premier", "seriea", "bundesliga", "ligue1"]

# ---- Rate limit local para evitar 429 ----
_LAST_CALL_TS = 0.0
_MIN_INTERVAL = 1.1  # segundos entre requests; puedes ajustar 0.7–1.5
def _polite_pause():
    global _LAST_CALL_TS
    now = time.monotonic()
    delta = _MIN_INTERVAL - (now - _LAST_CALL_TS)
    if delta > 0:
        time.sleep(delta + random.uniform(0, 0.15))
    _LAST_CALL_TS = time.monotonic()

# ---- GET robusto con caps de espera/presupuesto ----
def _robust_get(url: str, max_retries=3, base_delay=1.5, max_wait=15, total_budget=30, debug=False) -> requests.Response:
    """
    GET con:
      - rate limit local (_polite_pause)
      - backoff con límite de espera por intento (max_wait) y presupuesto total (total_budget)
      - respeta requests_cache si está habilitado
    """
    s = requests.Session()
    start = time.monotonic()
    for i in range(max_retries):
        _polite_pause()
        r = s.get(url, headers=_headers(), timeout=25, allow_redirects=True)
        if debug:
            code = r.status_code
            from_cache = getattr(r, "from_cache", False)
            print(f"[FBref] {code} {'(cache)' if from_cache else ''} {url}")
        if r.status_code == 429 or (500 <= r.status_code < 600):
            ra = r.headers.get("Retry-After")
            if ra:
                try:
                    wait = int(ra)
                except ValueError:
                    wait = base_delay * (2 ** i) + random.uniform(0, 1.0)
            else:
                wait = base_delay * (2 ** i) + random.uniform(0, 1.0)
            wait = min(wait, max_wait)
            elapsed = time.monotonic() - start
            if elapsed + wait > total_budget:
                if debug:
                    print(f"[backoff] presupuesto excedido ({elapsed:.1f}s + {wait:.1f}s) -> skip")
                break
            if debug:
                print(f"[backoff] {r.status_code} -> sleep {wait:.1f}s")
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r
    raise RuntimeError(f"Max retries o presupuesto agotado para {url}")

# ---- Resolución de URL del equipo vía buscador interno de FBref ----
def _find_team_base_url_via_search(query: str, parser: str, debug: bool=False) -> Optional[str]:
    """
    Usa el buscador interno de FBref para dar con la URL base del equipo (/en/squads/<id>/...).
    Generalmente 1 request; si el buscador redirige, r.url ya es la del equipo.
    """
    q = quote(query)
    url = f"https://fbref.com/en/search/search.fcgi?search={q}"
    try:
        r = _robust_get(url, debug=debug)
    except Exception as e:
        if debug: print(f"[search error] {e}")
        return None

    # Si la búsqueda redirige directamente al equipo:
    if "/en/squads/" in r.url:
        return r.url

    soup = BeautifulSoup(r.text, parser)
    for a in soup.find_all("a", href=True):
        h = a["href"]
        # Evitar jugadores / matchlogs; preferir página raíz del equipo
        if h.startswith("/en/squads/") and "/players/" not in h and "/matchlogs/" not in h:
            return "https://fbref.com" + h
    return None

def _resolve_team_base_url(slug_equipo: str, target_slug: str, parser: str, debug: bool=False) -> Optional[str]:
    """
    Resuelve la URL base del equipo usando el buscador con distintas variantes del query.
    No usa páginas de liga (evita 429 gigantes de /en/comps/...).
    """
    # 1) Intento con el slug tal cual (ej. 'bar')
    by_search = _find_team_base_url_via_search(slug_equipo, parser, debug)
    if by_search:
        return by_search

    # 2) Alias comunes por slug
    reverse_alias = {
        "bar": ["Barcelona", "FC Barcelona"],
        "rma": ["Real Madrid", "Real Madrid CF"],
        "sev": ["Sevilla", "Sevilla FC"],
        "atm": ["Atlético de Madrid", "Atletico Madrid"],
        "psg": ["Paris Saint-Germain", "PSG"],
        "liv": ["Liverpool", "Liverpool FC"],
        "che": ["Chelsea", "Chelsea FC"],
        "mci": ["Manchester City", "Man City"],
        "mun": ["Manchester United", "Man United"],
        "bvb": ["Borussia Dortmund"],
        "bay": ["Bayern Munich", "Bayern München", "FC Bayern"],
        "juv": ["Juventus"],
        "int": ["Inter", "Internazionale", "Inter Milan"],
        "mil": ["AC Milan", "Milan"],
        "nap": ["Napoli", "SSC Napoli"],
        "rom": ["AS Roma", "Roma"],
        "laz": ["Lazio", "SS Lazio"],
    }
    for q in reverse_alias.get(target_slug, []):
        by_search = _find_team_base_url_via_search(q, parser, debug)
        if by_search:
            return by_search

    # 3) Fallback: slug expandido como texto (p.ej., 'bar' -> 'barcelona')
    slug_to_text = {
        "bar": "barcelona",
        "rma": "real madrid",
        "sev": "sevilla",
        "atm": "atletico madrid",
    }
    txt = slug_to_text.get(target_slug)
    if txt:
        by_search = _find_team_base_url_via_search(txt, parser, debug)
        if by_search:
            return by_search

    return None

# ---- Principal ----
def get_previus_matches(slug_equipo: str, fecha: str, X: int, debug: bool=False) -> List[Result]:
    """
    Retorna los X resultados previos (antes de 'fecha' dd/mm/aa) del equipo (slug corto)
    en TODAS las competiciones, usando la página de 'Scores & Fixtures' del equipo en FBref.

    Salida: List[Result] con:
        Result(home_slug, away_slug, gH, gA, date_obj)
    """
    # --- Validaciones ---
    if not isinstance(X, int) or X <= 0:
        raise ValueError("X debe ser un entero > 0.")
    X = min(X, 10)  # tope solicitado

    try:
        d_cut = datetime.strptime(fecha, "%d/%m/%y")
    except ValueError:
        raise ValueError("La fecha debe ser dd/mm/aa (ej. '30/09/25').")

    target = slugify_team(slug_equipo)

    # Temporada "año-año+1" (cambio en julio) — solo para ordenar búsqueda de temporadas
    temporada_base = d_cut.year if d_cut.month >= 7 else d_cut.year - 1

    parser = _pick_parser()

    # ------------------------------------------------------------
    # 1) Resolver URL base del equipo SIN usar páginas de liga
    # ------------------------------------------------------------
    team_base = _resolve_team_base_url(slug_equipo, target, parser, debug)
    if not team_base:
        if debug: print("[team] no hallado (search intentos).")
        return []

    # ------------------------------------------------------------
    # 2) Hallar URLs de 'Scores & Fixtures' para temporadas cercanas
    # ------------------------------------------------------------
    def _find_scores_fixtures_urls(team_root_url: str, seasons: List[int]) -> List[str]:
        """
        Dado el root del equipo (/en/squads/<id>/ o una subpágina), localiza los enlaces
        a 'Scores & Fixtures' para las temporadas solicitadas (más reciente primero).
        """
        urls = []
        try:
            r = _robust_get(team_root_url, debug=debug)
        except Exception as e:
            if debug: print(f"[team_root error] {e}")
            return urls

        soup = BeautifulSoup(r.text, parser)

        a_tags = soup.find_all("a", href=True)
        hrefs = [(a.get_text(strip=True), a["href"]) for a in a_tags]

        def _to_abs(h: str) -> str:
            return "https://fbref.com" + h if h.startswith("/") else h

        for year in seasons:
            season_str = f"{year}-{year+1}"
            cand = None
            for text, h in hrefs:
                txt = (text or "").lower()
                href_l = h.lower()
                # Buscamos "Scores & Fixtures" o variantes, que contengan la temporada
                if "scores" in txt and "fixture" in txt and season_str in href_l:
                    cand = _to_abs(h); break
                # Fallback por patrones de href conocidos
                if season_str in href_l and ("matchlogs" in href_l or "schedule" in href_l):
                    cand = _to_abs(h); break
            if cand:
                urls.append(cand)

        # Fallback: si no hay temporada explícita, toma el primer "Scores & Fixtures"
        if not urls:
            for text, h in hrefs:
                txt = (text or "").lower()
                if "scores" in txt and "fixture" in txt:
                    urls.append(_to_abs(h))
                    break

        return urls

    # Intentamos temporada base y retrocedemos (limitar a 4 temporadas para bajar carga)
    seasons_to_try = [temporada_base - i for i in range(0, 4)]  # base..base-3
    team_sf_urls = _find_scores_fixtures_urls(team_base, seasons_to_try)
    if not team_sf_urls:
        if debug: print("[scores&fixtures] no encontrado")
        return []

    # ------------------------------------------------------------
    # 3) Parsear cada tabla de 'Scores & Fixtures' (todas comps) y recolectar previos a d_cut
    # ------------------------------------------------------------
    collected: List[Tuple[datetime, str, str]] = []  # (date, 'home-away', 'gH-gA')

    def _parse_scores_fixtures(url: str):
        nonlocal collected
        try:
            r = _robust_get(url, debug=debug)
        except Exception as e:
            if debug: print(f"[sf error] {e} @ {url}")
            return

        soup = BeautifulSoup(r.text, parser)

        def _iter_rows(s):
            for tr in s.select("table tbody tr"):
                yield tr

        rows = list(_iter_rows(soup))
        if not rows:
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

            # Fecha
            raw = (date_td.get_text(strip=True) or "")[:10]
            try:
                mdate = datetime.strptime(raw, "%Y-%m-%d")
            except Exception:
                continue

            if not (mdate < d_cut):
                continue  # solo previos

            # Equipos
            h_name = home_td.get_text(strip=True)
            a_name = away_td.get_text(strip=True)
            h = slugify_team(h_name)
            a = slugify_team(a_name)

            # Confirmar que uno de los dos es nuestro equipo objetivo
            if h != target and a != target:
                continue

            # Marcador
            score = score_td.get_text(strip=True)
            if not score:
                continue
            score = re.sub(r"\s*–\s*", "-", score)  # normaliza guion
            if not re.match(r"^\d+\s*-\s*\d+$", score):  # evitar "Postp", "AET", etc., si cambian formato
                continue

            collected.append((mdate, f"{h}-{a}", score))

    # Parseamos urls en orden (más recientes primero)
    for u in team_sf_urls:
        _parse_scores_fixtures(u)
        if len(collected) >= X:
            break

    # Si aún no alcanza X, intenta temporadas adicionales no cubiertas (por si faltó algún enlace)
    if len(collected) < X:
        extra_years = [y for y in seasons_to_try if all(str(y) not in u for u in team_sf_urls)]
        for y in extra_years:
            more_urls = _find_scores_fixtures_urls(team_base, [y])
            for u in more_urls:
                _parse_scores_fixtures(u)
                if len(collected) >= X:
                    break
            if len(collected) >= X:
                break

    # ------------------------------------------------------------
    # 4) Ordenar desc por fecha y cortar a X → construir Result
    # ------------------------------------------------------------
    collected.sort(key=lambda t: t[0], reverse=True)
    out: List[Result] = []
    for date_obj, match_slug, score in collected[:X]:
        h_slug, a_slug = match_slug.split("-")
        gH, gA = score.split("-")
        out.append(Result(h_slug, a_slug, gH, gA, date_obj))
    return out
