# utils/get_last_results.py
import re
import time
import random
from datetime import datetime, timedelta
from typing import List, Tuple, Optional
import unicodedata

import requests
import requests_cache
from bs4 import BeautifulSoup, Comment

# ---- Cache 24h para no repetir peticiones ----
requests_cache.install_cache("fb_cache", expire_after=86400)

# ---- Competencias soportadas (top-5) ----
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

# ---- Deducción de liga probable por slug de equipo (para reducir 429) ----
def guess_leagues_for_slug(team_slug: str) -> List[str]:
    s = team_slug.lower()
    # Grupos rápidos por códigos típicos
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
    # Si no se reconoce, intentar todas (orden moderado)
    return ["laliga", "premier", "seriea", "bundesliga", "ligue1"]

# ---- GET robusto con Retry-After / backoff ----
def _robust_get(url: str, max_retries=5, base_delay=1.5, debug=False) -> requests.Response:
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

# ---- Principal ----
def get_previus_matches(slug_equipo: str, fecha: str, X: int, debug: bool=False) -> List[Tuple[str, str]]:
    """
    Retorna los X resultados previos (antes de 'fecha') para el equipo dado.
    Formato: [( 'home-away', 'gH-gA' ), ...]
      - 'home-away' usa los slugs normalizados (3 letras aprox) por cada equipo.
      - 'gH-gA' respeta el orden home-away (tal como aparece en FBref).
    NOTA: Busca en la liga doméstica más probable (top-5). Si no reconoce la liga del equipo, intenta todas.
    """
    # Validaciones
    if not isinstance(X, int) or X <= 0:
        raise ValueError("X debe ser un entero > 0.")
    try:
        d = datetime.strptime(fecha, "%d/%m/%y")
    except ValueError:
        raise ValueError("La fecha debe ser dd/mm/aa (ej. '30/09/95').")

    # Temporada FBref
    temporada = d.year if d.month >= 7 else d.year - 1
    season_str = f"{temporada}-{temporada+1}"

    # Slug objetivo
    target = slugify_team(slug_equipo)

    # Orden de ligas a consultar
    leagues_order = guess_leagues_for_slug(target)

    parser = _pick_parser()
    collected: List[Tuple[datetime, str, str]] = []  # (date, 'home-away', 'gH-gA')

    for key in leagues_order:
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
            # tablas envueltas en comentarios
            for c in soup.find_all(string=lambda t: isinstance(t, Comment) and "<table" in t):
                sub = BeautifulSoup(c, parser)
                rows = list(_iter_rows(sub))
                if rows:
                    break

        for tr in rows:
            home_td = tr.find("td", {"data-stat": "home_team"})
            away_td = tr.find("td", {"data-stat": "away_team"})
            date_td = tr.find("td", {"data-stat": "date"})
            score_td = tr.find("td", {"data-stat": "score"})
            if not (home_td and away_td and date_td and score_td):
                continue

            # Fecha fila
            raw = (date_td.get_text(strip=True) or "")[:10]
            try:
                mdate = datetime.strptime(raw, "%Y-%m-%d")
            except Exception:
                continue

            # Solo partidos ANTES de la fecha dada (estricto)
            if not (mdate < d):
                continue

            h_name = home_td.get_text(strip=True)
            a_name = away_td.get_text(strip=True)
            h = slugify_team(h_name)
            a = slugify_team(a_name)

            # ¿Participa el equipo?
            if h != target and a != target:
                continue

            score = score_td.get_text(strip=True)
            if not score:
                # partido sin marcador (TBD) → omitir
                continue
            score = re.sub(r"\s*–\s*", "-", score)  # “–” → “-”
            match_slug = f"{h}-{a}"
            collected.append((mdate, match_slug, score))

        # Si ya tenemos suficientes, no hace falta consultar más ligas
        if len(collected) >= X:
            break

    # Ordenar por fecha descendente y cortar a X
    collected.sort(key=lambda t: t[0], reverse=True)
    out = [(slug, score) for _, slug, score in collected[:X]]
    return out

