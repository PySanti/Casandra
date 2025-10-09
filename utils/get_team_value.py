              
# utils/get_team_market_value.py
import re
import time
import random
from datetime import datetime
from typing import Optional, Tuple, List, Dict
import unicodedata

import requests
from bs4 import BeautifulSoup

# ----------------------------
# Config & helpers HTTP
# ----------------------------
UA = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36",
]

def _headers():
    return {
        "User-Agent": random.choice(UA),
        "Accept-Language": "en-US,en;q=0.9,es;q=0.8",
        "Referer": "https://www.transfermarkt.com/",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }

def _robust_get(url: str, max_retries=4, base_delay=1.4, debug=False) -> requests.Response:
    s = requests.Session()
    for i in range(max_retries):
        r = s.get(url, headers=_headers(), timeout=25)
        if debug:
            print(f"[TM] {r.status_code} {url}")
        # Backoff simple para 429/5xx
        if r.status_code in (429,) or (500 <= r.status_code < 600):
            wait = base_delay * (2**i) + random.uniform(0, 1.0)
            if debug: print(f"[backoff] {r.status_code} -> sleep {wait:.1f}s")
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r
    raise RuntimeError(f"Max retries para {url}")

# ----------------------------
# Normalización / mapeos
# ----------------------------
def _norm(s: str) -> str:
    if not s: return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    return re.sub(r"[^a-z0-9]+", "", s)

# Slug -> candidatos de nombre como aparecen en Transfermarkt
TEAM_NAME_CANDIDATES: Dict[str, List[str]] = {
    # ESP
    "bar": ["FC Barcelona", "Barcelona"],
    "rma": ["Real Madrid"],
    "atm": ["Atletico Madrid", "Atlético Madrid"],
    "sev": ["Sevilla FC", "Sevilla"],
    "soc": ["Real Sociedad"],
    "ath": ["Athletic Club", "Athletic Bilbao"],
    "bet": ["Real Betis"],
    "vil": ["Villarreal CF", "Villarreal"],
    "val": ["Valencia CF", "Valencia"],
    "cel": ["Celta de Vigo", "Celta Vigo"],
    "ray": ["Rayo Vallecano"],
    "gir": ["Girona FC", "Girona"],
    "get": ["Getafe CF", "Getafe"],
    "mlr": ["RCD Mallorca", "Mallorca"],
    "lpa": ["UD Las Palmas", "Las Palmas"],
    "ala": ["Deportivo Alaves", "Deportivo Alavés", "Alaves", "Alavés"],
    "gra": ["Granada CF", "Granada"],
    "osa": ["CA Osasuna", "Osasuna"],
    # ENG
    "mci": ["Manchester City", "Man City"],
    "mun": ["Manchester United", "Man United"],
    "liv": ["Liverpool FC", "Liverpool"],
    "ars": ["Arsenal FC", "Arsenal"],
    "che": ["Chelsea FC", "Chelsea"],
    "tot": ["Tottenham Hotspur", "Tottenham"],
    "new": ["Newcastle United", "Newcastle"],
    "whu": ["West Ham United", "West Ham"],
    "avl": ["Aston Villa"],
    "eve": ["Everton"],
    "lei": ["Leicester City", "Leicester"],
    "bha": ["Brighton & Hove Albion", "Brighton"],
    "bre": ["Brentford FC", "Brentford"],
    "bou": ["AFC Bournemouth", "Bournemouth"],
    "cry": ["Crystal Palace"],
    "ful": ["Fulham FC", "Fulham"],
    "wol": ["Wolverhampton Wanderers", "Wolves"],
    "for": ["Nottingham Forest"],
    # ITA
    "juv": ["Juventus"],
    "int": ["Inter", "Inter Milan", "Internazionale"],
    "mil": ["AC Milan", "Milan"],
    "nap": ["SSC Napoli", "Napoli"],
    "rom": ["AS Roma", "Roma"],
    "laz": ["SS Lazio", "Lazio"],
    "ata": ["Atalanta"],
    "fio": ["Fiorentina"],
    # GER
    "bay": ["Bayern Munich", "Bayern München", "FC Bayern München"],
    "bvb": ["Borussia Dortmund"],
    "rbl": ["RB Leipzig"],
    "lev": ["Bayer Leverkusen"],
    "bmg": ["Borussia Monchengladbach", "Borussia Mönchengladbach", "Monchengladbach", "Mönchengladbach"],
    "vfb": ["VfB Stuttgart", "Stuttgart"],
    "wob": ["VfL Wolfsburg", "Wolfsburg"],
    # FRA
    "psg": ["Paris Saint-Germain", "Paris SG", "PSG"],
    "om":  ["Olympique Marseille", "Marseille"],
    "lyo": ["Olympique Lyonnais", "Lyon"],
    "lil": ["LOSC Lille", "Lille"],
    "nic": ["OGC Nice", "Nice"],
    "ren": ["Stade Rennais", "Rennes"],
    "nan": ["FC Nantes", "Nantes"],
}

# Slug -> ligas probables (para no consultar 5 ligas si no hace falta)
def _guess_leagues(slug: str) -> List[str]:
    s = slug.lower()
    if s in {"bar","rma","atm","sev","soc","ath","bet","vil","val","cel","ray","gir","get","mlr","lpa","ala","gra","osa"}:
        return ["laliga"]
    if s in {"mci","mun","liv","ars","che","tot","new","whu","avl","eve","lei","bha","bre","bou","cry","ful","wol","for"}:
        return ["premier"]
    if s in {"juv","int","mil","nap","rom","laz","ata","fio"}:
        return ["seriea"]
    if s in {"bay","bvb","rbl","lev","bmg","vfb","wob"}:
        return ["bundesliga"]
    if s in {"psg","om","lyo","lil","nic","ren","nan"}:
        return ["ligue1"]
    # fallback: probar todas
    return ["laliga","premier","seriea","bundesliga","ligue1"]

# Liga -> (code, path)
COMP = {
    "premier":   ("GB1", "premier-league"),
    "laliga":    ("ES1", "laliga"),
    "seriea":    ("IT1", "serie-a"),
    "bundesliga":("L1",  "bundesliga"),
    "ligue1":    ("FR1", "ligue-1"),
}

# ----------------------------
# Parse helpers
# ----------------------------
def _parse_cutoff_dates(html: str) -> List[datetime]:
    # Captura todas las fechas dd/mm/YYYY que aparecen en la zona "Cut-off date"
    # y devuelve una lista única ordenada desc.
    dates = set(re.findall(r"\b(\d{2}/\d{2}/\d{4})\b", html))
    out = []
    for d in dates:
        try:
            out.append(datetime.strptime(d, "%d/%m/%Y"))
        except ValueError:
            pass
    return sorted(out, reverse=True)

def _pick_best_date(available: List[datetime], target: datetime) -> Optional[datetime]:
    # Elige la fecha disponible más reciente <= target; si no hay, None
    for d in available:
        if d <= target:
            return d
    return None

def _find_value_for_team(soup: BeautifulSoup, team_candidates: List[str], desired_date_str: str) -> Optional[str]:
    # Ubicar el índice de la columna 'Value <date>'
    ths = soup.select("table thead th")
    value_col = None
    for idx, th in enumerate(ths):
        txt = (th.get_text(" ", strip=True) or "")
        if txt.startswith("Value"):
            # Aseguramos que corresponda a la fecha deseada
            if desired_date_str in txt:
                value_col = idx
                break
    # Si no encontramos cabecera exacta, coger la primera col que empiece por 'Value'
    if value_col is None:
        for idx, th in enumerate(ths):
            txt = (th.get_text(" ", strip=True) or "")
            if txt.startswith("Value"):
                value_col = idx
                break
    if value_col is None:
        return None

    # Construir set normalizado de candidatos
    cand = {_norm(x) for x in (team_candidates or [])}

    # Recorrer filas y buscar el club
    for tr in soup.select("table tbody tr"):
        # El nombre del club suele estar enlazado a /startseite/verein/<id>/
        a = tr.select_one("td a[href*='/startseite/verein/']")
        if not a:
            continue
        club = a.get_text(strip=True)
        if _norm(club) not in cand:
            continue
        tds = tr.find_all("td")
        if value_col >= len(tds):
            continue
        val = tds[value_col].get_text(strip=True)
        if val:
            return val  # Ej. '€1.33bn' o '€462.10m'
    return None

# ----------------------------
# API principal
# ----------------------------
def get_team_value(slug_equipo: str, fecha: str, debug: bool=False) -> Optional[str]:
    """
    Retorna el valor de mercado del equipo (string como '€1.08bn' o '€462.10m')
    en la fecha dada (dd/mm/aa), usando la fecha de corte de Transfermarkt
    más cercana <= fecha.
    """
    # 1) parse fecha
    try:
        d = datetime.strptime(fecha, "%d/%m/%y")
    except ValueError:
        raise ValueError("La fecha debe ser dd/mm/aa (ej. '15/09/25').")

    # 2) candidatos de nombre
    team_slug = slug_equipo.lower().strip()
    candidates = TEAM_NAME_CANDIDATES.get(team_slug, [])
    if not candidates:
        if debug: print(f"[WARN] sin candidatos para slug '{team_slug}' — añade en TEAM_NAME_CANDIDATES")
        return None

    # 3) orden de ligas a consultar
    leagues = _guess_leagues(team_slug)

    for lg in leagues:
        code, path = COMP[lg]
        base = f"https://www.transfermarkt.com/{path}/marktwerteverein/wettbewerb/{code}"
        try:
            r = _robust_get(base, debug=debug)
        except Exception as e:
            if debug: print(f"[{lg}] error {e}")
            continue

        # 4) elegir fecha de corte
        avail = _parse_cutoff_dates(r.text)
        if not avail:
            if debug: print(f"[{lg}] no hay fechas de corte en página")
            continue
        best = _pick_best_date(avail, d)
        if not best:
            if debug: print(f"[{lg}] no hay fecha <= {d:%d/%m/%Y}; usando la más antigua no es válido -> skip")
            continue

        best_iso = best.strftime("%Y-%m-%d")
        best_ui  = best.strftime("%d/%m/%Y")
        # construimos URL con stichtag; varias páginas aceptan '/stichtag/YYYY-MM-DD/plus/'
        date_url_candidates = [
            f"{base}/stichtag/{best_iso}/plus/",
            f"{base}/stichtag/{best_iso}/",
            base  # fallback: quizá la página ya está en esa fecha por defecto
        ]

        page = None
        for u in date_url_candidates:
            try:
                rr = _robust_get(u, debug=debug)
                page = rr
                break
            except Exception as e:
                if debug: print(f"[{lg}] fallo en {u}: {e}")
                continue
        if not page:
            continue

        soup = BeautifulSoup(page.text, "html.parser")
        val = _find_value_for_team(soup, candidates, best_ui)
        if val:
            if debug: print(f"[OK] {candidates[0]} @ {best_ui} -> {val}")
            return val

        if debug: print(f"[{lg}] no encontré el club en la tabla para {best_ui}")

    # Si ninguna liga funcionó
    if debug: print("No se pudo obtener el valor de mercado.")
    return None
