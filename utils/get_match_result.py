# utils/get_match_result.py
from utils.Result import Result
import re
import time
import random
from datetime import datetime, timedelta
import unicodedata
import requests
import requests_cache
from bs4 import BeautifulSoup, Comment

# Cache 24h para no repetir peticiones
requests_cache.install_cache("fb_cache", expire_after=86400)

COMP_MAP = {
    "laliga": ("12", "La-Liga"),
    "premier": ("9", "Premier-League"),
    "seriea": ("11", "Serie-A"),
    "bundesliga": ("20", "Bundesliga"),
    "ligue1": ("13", "Ligue-1"),
    "ucl": ("8", "Champions-League"),
}

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

def _robust_get(url, max_retries=5, base_delay=1.5, debug=False):
    s = requests.Session()
    for i in range(max_retries):
        r = s.get(url, headers=_headers(), timeout=25, allow_redirects=True)
        if debug:
            code = r.status_code
            from_cache = getattr(r, "from_cache", False)
            print(f"[FBref] {code} {'(cache)' if from_cache else ''} {url}")
        if r.status_code == 429:
            ra = r.headers.get("Retry-After")
            if ra:
                try:
                    wait = int(ra)
                except ValueError:
                    wait = base_delay * (2 ** i) + random.uniform(0, 1.0)
            else:
                wait = base_delay * (2 ** i) + random.uniform(0, 1.0)
            if debug: print(f"[backoff] 429 -> sleep {wait:.1f}s")
            time.sleep(wait)
            continue
        if 500 <= r.status_code < 600:
            wait = base_delay * (2 ** i) + random.uniform(0, 1.0)
            if debug: print(f"[backoff] {r.status_code} -> sleep {wait:.1f}s")
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r
    raise RuntimeError(f"Max retries alcanzado para {url}")

def _pick_parser():
    try:
        import lxml  # noqa
        return "lxml"
    except Exception:
        return "html.parser"

def _normalize(s: str) -> str:
    norm = unicodedata.normalize("NFKD", s or "")
    cleaned = "".join(c for c in norm if not unicodedata.combining(c)).lower()
    return re.sub(r"[\s\.\-’'`_]+", "", cleaned)

def slugify_team(name: str) -> str:
    cleaned = _normalize(name)
    aliases = {
        # España (incluye Athletic y Sporting de Gijón)
        "realmadrid":"rma","fcbarcelona":"bar","barcelona":"bar","sevilla":"sev",
        "atleticodemadrid":"atm","atleticomadrid":"atm","valencia":"val","villarreal":"vil",
        "realbetis":"bet","girona":"gir","getafe":"get","realsociedad":"soc",
        "athleticclub":"ath","athleticbilbao":"ath","osasuna":"osa","celtadevigo":"cel","celtavigo":"cel",
        "rayovallecano":"ray","udlaspalmas":"lpa","alaves":"ala","deportivoalaves":"ala",
        "granadacf":"gra","realvalladolid":"rvad","rcdmallorca":"mlr","cadiz":"cad","leganes":"leg",
        "sportingdegijon":"spo","sportinggijon":"spo","realsporting":"spo",
        # Inglaterra (por si acaso)
        "manchesterunited":"mun","manchestercity":"mci","chelsea":"che","liverpool":"liv",
        "arsenal":"ars","tottenhamhotspur":"tot","newcastleunited":"new",
        # Italia
        "juventus":"juv","internazionale":"int","inter":"int","acmilan":"mil","milan":"mil","napoli":"nap",
        "roma":"rom","lazio":"laz","atalanta":"ata","fiorentina":"fio",
        # Alemania
        "bayernmunchen":"bay","bayernmunich":"bay","borussiadortmund":"bvb","rbleipzig":"rbl",
        "bayerleverkusen":"lev","borussiamonchengladbach":"bmg","borussiamönchengladbach":"bmg",
        # Francia
        "parissaintgermain":"psg","psg":"psg","olympiquemarseille":"om","olympiquelyonnais":"lyo",
        "monaco":"mon","lille":"lil","nice":"nic",
    }
    return aliases.get(cleaned, cleaned[:3] if len(cleaned) >= 3 else cleaned)

def get_match_result(slug: str, fecha: str, liga_hint = None,
                     search_window_days: int = 2, debug: bool = False):
    """
    Devuelve el resultado 'X-Y' en el MISMO orden del slug (home-away).
    - slug: 'bar-psg', 'ath-spo', etc. (acepta 'barcelona-realsociedad', etc.)
    - fecha: 'dd/mm/aa'
    - liga_hint: restringe búsqueda a 'laliga'|'premier'|'seriea'|'bundesliga'|'ligue1'|'ucl'
    - search_window_days: ventana ±N días
    """
    # 1) Fecha -> temporada FBref
    try:
        d = datetime.strptime(fecha, "%d/%m/%y")
    except ValueError:
        raise ValueError("La fecha debe ser dd/mm/aa (ej. '30/09/95').")
    temporada = d.year if d.month >= 7 else d.year - 1
    season_str = f"{temporada}-{temporada+1}"
    start, end = d - timedelta(days=search_window_days), d + timedelta(days=search_window_days)

    # 2) Normalizar slug
    parts = [p for p in re.split(r"[-–—_\s]+", slug.strip().lower()) if p]
    if len(parts) != 2:
        raise ValueError("Slug inválido. Usa 'local-visitante'.")
    target_home = slugify_team(parts[0])
    target_away = slugify_team(parts[1])

    # 3) Ligas a consultar (prioriza hint para evitar 429)
    order = []
    if liga_hint:
        hint = liga_hint.strip().lower()
        if hint not in COMP_MAP:
            raise ValueError("liga_hint inválida.")
        order.append(hint)
    else:
        # si no hay hint, intenta todas (más riesgo de 429)
        order = ["laliga", "premier", "seriea", "bundesliga", "ligue1", "ucl"]

    parser = _pick_parser()

    for key in order:
        comp_id, comp_slug = COMP_MAP[key]
        url = f"https://fbref.com/en/comps/{comp_id}/{season_str}/schedule/{season_str}-{comp_slug}-Scores-and-Fixtures"
        try:
            r = _robust_get(url, debug=debug)
        except Exception as e:
            if debug: print(f"[error] {e}")
            continue

        soup = BeautifulSoup(r.text, parser)

        def _iter_rows(s):
            for tr in s.select("table tbody tr"):
                yield tr

        rows = list(_iter_rows(soup))
        if not rows:
            # tablas comentadas
            for c in soup.find_all(string=lambda t: isinstance(t, Comment) and "<table" in t):
                sub = BeautifulSoup(c, parser)
                rows = list(_iter_rows(sub))
                if rows:
                    break

        found_same_day = False
        for tr in rows:
            home_td = tr.find("td", {"data-stat": "home_team"})
            away_td = tr.find("td", {"data-stat": "away_team"})
            date_td = tr.find("td", {"data-stat": "date"})
            score_td = tr.find("td", {"data-stat": "score"})
            if not (home_td and away_td and date_td):
                continue

            raw = (date_td.get_text(strip=True) or "")[:10]
            try:
                mdate = datetime.strptime(raw, "%Y-%m-%d")
            except Exception:
                continue

            if not (start <= mdate <= end):
                continue
            found_same_day = True

            h = slugify_team(home_td.get_text(strip=True))
            a = slugify_team(away_td.get_text(strip=True))
            if h == target_home and a == target_away:
                if not score_td:
                    if debug: print("[info] Partido encontrado sin marcador.")
                    return None
                score = score_td.get_text(strip=True)
                score = re.sub(r"\s*–\s*", "-", score)
                if debug: print(f"[FOUND] {key.upper()} {season_str} {h}-{a} {score}")
                return Result(*slug.split('-'),*score.split('-'))

        if debug and found_same_day:
            print(f"[HINT] Hubo partidos en {key} ±{search_window_days} días, pero no coincidió el slug.")

    if debug:
        print("No se encontró el resultado para ese partido/fecha.")
    return None
