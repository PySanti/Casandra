# utils/get_last_results.py
import re
import time
import random
from datetime import datetime, timedelta
from typing import List, Tuple, Optional
import unicodedata
from utils.Result import Result

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

    # Temporada "año-año+1" según tu lógica (cambia de temporada en julio)
    temporada_base = d_cut.year if d_cut.month >= 7 else d_cut.year - 1

    parser = _pick_parser()

    # ------------------------------------------------------------
    # 1) Descubrir la URL base del equipo en FBref a partir de alguna liga probable
    #    (tomamos el primer match de ese equipo en la tabla de la liga y leemos el href del <a>)
    # ------------------------------------------------------------
    def _find_team_base_url() -> Optional[str]:
        leagues_order = guess_leagues_for_slug(target)
        season_str = f"{temporada_base}-{temporada_base+1}"

        for key in leagues_order:
            comp_id, comp_slug = COMP_MAP[key]
            url = f"https://fbref.com/en/comps/{comp_id}/{season_str}/schedule/{season_str}-{comp_slug}-Scores-and-Fixtures"
            try:
                r = _robust_get(url, debug=debug)
            except Exception as e:
                if debug: print(f"[error liga] {e}")
                continue

            soup = BeautifulSoup(r.text, parser)

            # Algunas tablas vienen comentadas; función que itera tbody/tr de la primera tabla válida
            def _iter_rows(s):
                for tr in s.select("table tbody tr"):
                    yield tr

            rows = list(_iter_rows(soup))
            if not rows:
                # Buscar tablas dentro de comentarios
                for c in soup.find_all(string=lambda t: isinstance(t, Comment) and "<table" in t):
                    sub = BeautifulSoup(c, parser)
                    rows = list(_iter_rows(sub))
                    if rows:
                        break

            for tr in rows:
                home_td = tr.find("td", {"data-stat": "home_team"})
                away_td = tr.find("td", {"data-stat": "away_team"})
                if not (home_td and away_td):
                    continue

                h_name = home_td.get_text(strip=True)
                a_name = away_td.get_text(strip=True)
                h = slugify_team(h_name)
                a = slugify_team(a_name)

                if h != target and a != target:
                    continue

                # Tomamos el link del equipo que coincida
                td = home_td if h == target else away_td
                a_tag = td.find("a", href=True)
                if not a_tag:
                    continue
                href = a_tag["href"]  # típicamente "/en/squads/<TEAM_ID>/"
                if href.startswith("/"):
                    href = "https://fbref.com" + href
                # Normalizamos a la URL base (sin temporada) para luego buscar "Scores & Fixtures"
                # Si ya viene con temporada, igual la usamos como base.
                return href
        return None

    team_base = _find_team_base_url()
    if not team_base:
        if debug: print("[team] no hallado en ligas top-5; intentará todas igualmente.")
        # Como fallback: intentar todas ligas (ya lo hace guess_leagues_for_slug); si no, no hay forma estable de deducir URL
        return []

    # ------------------------------------------------------------
    # 2) Hallar la(s) URL(s) de "Scores & Fixtures" para el equipo y temporadas relevantes
    #    Preferimos la temporada_base y, si no completamos X, miramos temporadas anteriores.
    # ------------------------------------------------------------
    def _find_scores_fixtures_urls(team_root_url: str, seasons: List[int]) -> List[str]:
        """
        Dado el root del equipo (/en/squads/<id>/ o una subpágina), localiza los enlaces
        a 'Scores & Fixtures' para las temporadas solicitadas (más reciente primero).
        """
        urls = []
        # Primero, si la URL ya es de temporada y contiene 'Scores and Fixtures', úsala directamente.
        # Si no, abrimos la base y buscamos enlaces.
        try:
            r = _robust_get(team_root_url, debug=debug)
        except Exception as e:
            if debug: print(f"[team_root error] {e}")
            return urls

        soup = BeautifulSoup(r.text, parser)

        # Buscar enlaces que apunten a 'Scores and Fixtures' (texto o href) y contengan la temporada
        a_tags = soup.find_all("a", href=True)
        hrefs = [(a.get_text(strip=True), a["href"]) for a in a_tags]

        def _to_abs(h: str) -> str:
            return "https://fbref.com" + h if h.startswith("/") else h

        for year in seasons:
            season_str = f"{year}-{year+1}"
            # Heurísticas: texto "Scores & Fixtures" o "Scores and Fixtures", y/o href con 'matchlogs'/'schedule'
            cand = None
            for text, h in hrefs:
                txt = (text or "").lower()
                if "scores" in txt and "fixture" in txt and season_str in h:
                    cand = _to_abs(h); break
                if season_str in h and ("matchlogs" in h or "schedule" in h):
                    cand = _to_abs(h); break
            if cand:
                urls.append(cand)

        # Si no encontró nada con temporada explícita, como fallback toma el primer "Scores & Fixtures"
        if not urls:
            for text, h in hrefs:
                txt = (text or "").lower()
                if "scores" in txt and "fixture" in txt:
                    urls.append(_to_abs(h))
                    break

        return urls

    # Intentamos temporada base y vamos retrocediendo hasta reunir X (por ejemplo, 5 temporadas máx)
    seasons_to_try = [temporada_base - i for i in range(0, 6)]  # base, base-1, ..., base-5
    team_sf_urls = _find_scores_fixtures_urls(team_base, seasons_to_try)
    if not team_sf_urls:
        # A veces la base ya es una página de temporada; probamos directo un patrón adicional:
        # No forzamos patrón fijo para evitar romper si FBref cambia; respetamos heurística anterior.
        if debug: print("[scores&fixtures] no encontrado")
        return []

    # ------------------------------------------------------------
    # 3) Parsear cada tabla de 'Scores & Fixtures' (todas las comps) y recolectar previos a d_cut
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

        # Función genérica para capturar rows
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

            # Confirma que uno de los dos es nuestro equipo objetivo (por si la página mezcla cosas)
            if h != target and a != target:
                continue

            # Marcador
            score = score_td.get_text(strip=True)
            if not score:
                continue
            score = re.sub(r"\s*–\s*", "-", score)  # normaliza guion
            # Evitar filas tipo "Postp" o sin formato "x-y"
            if not re.match(r"^\d+\s*-\s*\d+$", score):
                continue

            collected.append((mdate, f"{h}-{a}", score))

    # Parseamos urls en orden (más recientes primero según cómo las encontramos)
    for u in team_sf_urls:
        _parse_scores_fixtures(u)
        if len(collected) >= X:
            break

    # Si aún no alcanza X, intenta temporadas anteriores adicionales (si no estaban ya en team_sf_urls)
    if len(collected) < X:
        extra_years = [y for y in seasons_to_try if all(str(y) not in u for u in team_sf_urls)]
        for y in extra_years:
            # Re-descubrir URL de esa temporada concreta (por si faltó)
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

