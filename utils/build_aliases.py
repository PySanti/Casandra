import json
import re
import time
import random
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Tuple
import requests
from bs4 import BeautifulSoup, Comment
from unidecode import unidecode

# ---------------------------
# CONFIGURACIÓN DE LIGAS/DIVISIONES (FBref)
# ---------------------------
# FBref usa IDs de competición y slugs de temporada en "Scores & Fixtures".
# Para 3ª división ESP/ITA hay varias páginas (por grupos); las incluimos como lista.
FBREF_SOURCES = {
    "ENG": {  # Inglaterra
        "div1": ("9",  "Premier-League"),
        "div2": ("10", "Championship"),
        "div3": ("15", "League-One"),
    },
    "ESP": {  # España
        "div1": ("12", "La-Liga"),
        "div2": ("17", "Segunda-Division"),
        # 3ª: Primera Federación → grupos (no está en "comps" estándar; usamos URLs manuales si faltara)
        # FBref publica "Primera Federación" como "Primera-Federacion-Group-1/2" (puede variar de nombre);
        # incluimos fallback por URLs alternativas si cambian el slug.
        "div3_urls": [
            # Ejemplos de posibles rutas; si alguna 404, el scraper la ignora sin romper.
            "https://fbref.com/en/comps/290/{season}/schedule/{season}-Primera-Federacion-Group-1-Scores-and-Fixtures",
            "https://fbref.com/en/comps/291/{season}/schedule/{season}-Primera-Federacion-Group-2-Scores-and-Fixtures",
        ],
    },
    "ITA": {  # Italia
        "div1": ("11", "Serie-A"),
        "div2": ("18", "Serie-B"),
        # Serie C por grupos
        "div3_urls": [
            "https://fbref.com/en/comps/212/{season}/schedule/{season}-Serie-C-Group-A-Scores-and-Fixtures",
            "https://fbref.com/en/comps/213/{season}/schedule/{season}-Serie-C-Group-B-Scores-and-Fixtures",
            "https://fbref.com/en/comps/214/{season}/schedule/{season}-Serie-C-Group-C-Scores-and-Fixtures",
        ],
    },
    "GER": {  # Alemania
        "div1": ("20", "Bundesliga"),
        "div2": ("33", "2-Bundesliga"),
        "div3": ("34", "3-Liga"),
    },
    "FRA": {  # Francia
        "div1": ("13", "Ligue-1"),
        "div2": ("60", "Ligue-2"),
        "div3": ("70", "Championnat-National"),
    },
}

# ---------------------------
# UTILIDADES
# ---------------------------
UA_LIST = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0 Safari/537.36",
]

def headers():
    return {
        "User-Agent": random.choice(UA_LIST),
        "Accept-Language": "en-US,en;q=0.8,es;q=0.7",
        "Referer": "https://google.com",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }

def robust_get(url: str, attempts: int = 5, base_delay: float = 1.5):
    for i in range(attempts):
        resp = requests.get(url, headers=headers(), timeout=25)
        if resp.status_code == 429:
            # Respeta Retry-After si existe; si no, backoff exponencial con jitter.
            ra = resp.headers.get("Retry-After")
            if ra:
                try:
                    wait = int(ra)
                except ValueError:
                    wait = base_delay * (2 ** i) + random.uniform(0, 1.0)
            else:
                wait = base_delay * (2 ** i) + random.uniform(0, 1.0)
            continue
        if 500 <= resp.status_code < 600:
            continue
        resp.raise_for_status()
        return resp
    raise RuntimeError(f"No se pudo obtener {url} tras {attempts} intentos.")

def normalize(s: str) -> str:
    # sin acentos, minúsculas, sin puntuación/espacios
    s = unidecode(s or "")
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "", s)
    return s

def short_code_from_name(name: str) -> str:
    """Genera un código corto razonable (3 letras) para usar como clave canonical."""
    nrm = normalize(name)
    # reglas rápidas para habituales
    manual = {
        "realmadrid": "rma", "fcbarcelona": "bar", "barcelona": "bar", "atleticodemadrid": "atm",
        "manchestercity": "mci", "manchesterunited": "mun", "bayernmunchen": "bay", "bayernmunich": "bay",
        "borussiadortmund": "bvb", "juventus": "juv", "internazionale": "int", "inter": "int",
        "acmilan": "mil", "milan": "mil", "napoli": "nap", "parissaintgermain": "psg", "psg": "psg",
        "olympiquemarseille": "om", "olympiquelyonnais": "lyo", "monaco": "mon", "lyon": "lyo",
        "sevilla": "sev", "realsociedad": "soc", "villareal": "vil", "villarreal": "vil",
        "realbetis": "bet", "valencia": "val", "girona": "gir", "getafe": "get", "athleticbilbao": "ath",
    }
    if nrm in manual: return manual[nrm]
    return nrm[:3] if len(nrm) >= 3 else nrm

def expand_aliases(name: str) -> List[str]:
    """Genera variantes típicas del nombre del club."""
    base = name.strip()
    plain = unidecode(base)
    pieces = [base, plain]
    low = base.lower()
    # quitar/variar prefijos comunes
    variants = set()
    variants.add(low)
    variants.add(normalize(base))
    # añadir/remover siglas comunes
    for prefix in ["FC ", "CF ", "AC ", "AS ", "SC ", "RC ", "Real ", "Atletico ", "Athletic ", "UD ", "CD "]:
        if base.startswith(prefix):
            variants.add(normalize(base[len(prefix):]))
            variants.add(low[len(prefix):])
    # versiones con/ sin “FC/CF/AC/AS/SC” al inicio o fin
    for sig in ["FC", "CF", "AC", "AS", "SC", "RC", "UD", "CD", "US", "SV", "TSG", "VfB", "VfL", "1.", "1FC", "1. FC"]:
        variants.add(normalize(f"{sig} {base}"))
        variants.add(normalize(f"{base} {sig}"))
    # ciudad sola (si contiene espacio)
    parts = base.split()
    if len(parts) >= 2:
        variants.add(normalize(parts[-1]))  # última palabra (p.ej., "Granada CF" -> "granada")
    # apodos manuales
    nick = {
        "FC Barcelona": ["barca", "fcb"],
        "Real Madrid": ["rm", "r.madrid", "real"],
        "Atlético de Madrid": ["atleti", "atm"],
        "Manchester United": ["manutd", "man u", "mu"],
        "Manchester City": ["man city", "mcfc", "city"],
        "Bayern München": ["bayern", "fcbayern"],
        "Borussia Dortmund": ["dortmund", "bvb09", "bvb"],
        "Paris Saint-Germain": ["psg", "paris"],
        "Juventus": ["juve"],
        "Inter": ["inter milan"],
        "AC Milan": ["milan"],
        "Olympique de Marseille": ["marseille", "om"],
        "Olympique Lyonnais": ["lyon", "ol"],
    }
    if base in nick:
        for alt in nick[base]:
            variants.add(normalize(alt))
    return sorted({v for v in variants if v})

# ---------------------------
# SCRAPER DE PLANTILLAS DE EQUIPOS POR TABLA FIXTURES
# ---------------------------
def collect_teams_from_fbref_table(url: str) -> List[str]:
    """Devuelve una lista de nombres de equipos que aparecen en la tabla de fixtures de FBref."""
    try:
        resp = robust_get(url)
    except Exception:
        return []
    soup = BeautifulSoup(resp.text, "lxml")
    rows = soup.select("table tbody tr")
    if not rows:
        # tablas comentadas
        for c in soup.find_all(string=lambda t: isinstance(t, Comment) and "<table" in t):
            subsoup = BeautifulSoup(c, "lxml")
            rows = subsoup.select("table tbody tr")
            if rows:
                break
    teams = set()
    for tr in rows:
        h = tr.find("td", {"data-stat": "home_team"})
        a = tr.find("td", {"data-stat": "away_team"})
        if h: teams.add(h.get_text(strip=True))
        if a: teams.add(a.get_text(strip=True))
    return sorted(teams)

def fbref_schedule_url(comp_id: str, comp_slug: str, season: str) -> str:
    return f"https://fbref.com/en/comps/{comp_id}/{season}/schedule/{season}-{comp_slug}-Scores-and-Fixtures"

# ---------------------------
# BUILDER PRINCIPAL
# ---------------------------
def build_alias_pack(season_start_year: int) -> Dict[str, List[str]]:
    """
    Construye un paquete de aliases para ENG/ESP/ITA/GER/FRA en sus 1ª, 2ª y 3ª divisiones,
    para la temporada season_start_year-season_start_year+1 (e.g., 2025 -> '2025-2026').
    """
    season = f"{season_start_year}-{season_start_year+1}"
    aliases_map: Dict[str, set] = defaultdict(set)

    def add_team(name: str):
        code = short_code_from_name(name)
        for v in expand_aliases(name):
            aliases_map[code].add(v)

    # Recorre países y divisiones
    for nation, cfg in FBREF_SOURCES.items():
        # div1 y div2 por comp_id + slug
        for key in ("div1", "div2"):
            if key in cfg:
                comp_id, comp_slug = cfg[key]
                url = fbref_schedule_url(comp_id, comp_slug, season)
                teams = collect_teams_from_fbref_table(url)
                for t in teams:
                    add_team(t)
                # cortesía: no saturar
        # div3 puede venir como comp directo o como lista de URLs
        if "div3" in cfg:
            comp_id, comp_slug = cfg["div3"]
            url = fbref_schedule_url(comp_id, comp_slug, season)
            teams = collect_teams_from_fbref_table(url)
            for t in teams:
                add_team(t)
        if "div3_urls" in cfg:
            for raw in cfg["div3_urls"]:
                url = raw.format(season=season)
                teams = collect_teams_from_fbref_table(url)
                for t in teams:
                    add_team(t)

    # Convertir sets a listas ordenadas + añadir el propio código como alias de sí mismo
    final: Dict[str, List[str]] = {}
    for code, vals in aliases_map.items():
        vals.add(code)
        final[code] = sorted(vals)
    return final

def save_aliases_json(season_start_year: int, out_path: str = "aliases.json"):
    aliases = build_alias_pack(season_start_year)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(aliases, f, ensure_ascii=False, indent=2)
    print(f"[OK] Guardado {out_path} con {len(aliases)} códigos de equipo.")


