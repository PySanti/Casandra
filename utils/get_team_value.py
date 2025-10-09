# -*- coding: utf-8 -*-
# utils/get_team_value.py

import re
import random
import time
from datetime import datetime
from typing import Optional, List, Dict
import unicodedata
import json

import requests
from bs4 import BeautifulSoup

# ============================
# HTTP / Headers / Backoff
# ============================
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

# Reutilizamos una sola sesión para todo (TM + Wayback)
_S = requests.Session()

def _robust_get(url: str, max_retries=4, base_delay=1.4, debug=False) -> requests.Response:
    for i in range(max_retries):
        r = _S.get(url, headers=_headers(), timeout=30)
        if debug:
            print(f"[GET] {r.status_code} {url}")
        if r.status_code in (429,) or (500 <= r.status_code < 600):
            wait = base_delay * (2**i) + random.uniform(0, 1.0)
            if debug: print(f"[backoff] {r.status_code} -> sleep {wait:.1f}s")
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r
    raise RuntimeError(f"Max retries para {url}")

# ============================
# Wayback (Internet Archive)
# ============================

def _wayback_cdx(url: str, to_yyyymmdd: str, debug=False) -> Optional[str]:
    """Retorna el timestamp del snapshot más reciente <= to_yyyymmdd para esa URL, o None."""
    api = (
        "https://web.archive.org/cdx/search/cdx"
        f"?url={requests.utils.quote(url, safe='')}"
        f"&output=json&filter=statuscode:200&collapse=digest&to={to_yyyymmdd}"
    )
    try:
        resp = _S.get(api, headers=_headers(), timeout=30)
        if debug:
            print(f"[WB-CDX] {resp.status_code} {api}")
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        if debug: print(f"[WB-CDX][error] {e}")
        return None
    if not data or len(data) <= 1:
        return None
    # data[0] son headers; las filas siguientes contienen timestamp en [1]
    last = data[-1]
    ts = last[1] if len(last) > 1 else None
    return ts

def _wayback_available(url: str, to_yyyymmdd: str, debug=False) -> Optional[str]:
    """
    Fallback: usa archive.org/wayback/available para obtener el snapshot 'closest'.
    Solo aceptamos si el timestamp <= to_yyyymmdd.
    """
    api = (
        "https://archive.org/wayback/available"
        f"?url={requests.utils.quote(url, safe='')}&timestamp={to_yyyymmdd}"
    )
    try:
        r = _S.get(api, headers=_headers(), timeout=30)
        if debug:
            print(f"[WB-AV] {r.status_code} {api}")
        r.raise_for_status()
        data = r.json()
        c = data.get("archived_snapshots", {}).get("closest")
        if not c or not c.get("available"):
            return None
        ts = c.get("timestamp")  # 'YYYYMMDDhhmmss'
        if not ts:
            return None
        # Aceptamos solo si <= to_yyyymmdd
        if ts[:8] <= to_yyyymmdd:
            return ts
        return None
    except Exception as e:
        if debug: print(f"[WB-AV][error] {e}")
        return None

def _wayback_fetch(url: str, target_date: datetime, debug=False) -> Optional[requests.Response]:
    """
    Intenta recuperar una página archivada <= target_date.
    Primero CDX; si falla o no hay, prueba 'available'.
    """
    to_str = target_date.strftime("%Y%m%d")
    ts = _wayback_cdx(url, to_str, debug=debug)
    if not ts:
        ts = _wayback_available(url, to_str, debug=debug)
    if not ts:
        return None
    wb_url = f"https://web.archive.org/web/{ts}/{url}"
    try:
        r = _S.get(wb_url, headers=_headers(), timeout=35)
        if debug:
            print(f"[WB] {r.status_code} {wb_url}")
        r.raise_for_status()
        return r
    except Exception as e:
        if debug: print(f"[WB][error] {e}")
        return None

# ============================
# Normalización / Mapeos
# ============================
def _norm(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    return re.sub(r"[^a-z0-9]+", "", s)

# Slug -> candidatos de nombre como aparecen en Transfermarkt
TEAM_NAME_CANDIDATES: Dict[str, List[str]] = {
    # España
    "bar": ["FC Barcelona", "Barcelona"],
    "rma": ["Real Madrid"],
    "atm": ["Atlético Madrid", "Atletico Madrid"],
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
    "ala": ["Deportivo Alavés", "Deportivo Alaves", "Alavés", "Alaves"],
    "gra": ["Granada CF", "Granada"],
    "osa": ["CA Osasuna", "Osasuna"],
    # Inglaterra
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
    # Italia
    "juv": ["Juventus"],
    "int": ["Inter", "Inter Milan", "Internazionale"],
    "mil": ["AC Milan", "Milan"],
    "nap": ["SSC Napoli", "Napoli"],
    "rom": ["AS Roma", "Roma"],
    "laz": ["SS Lazio", "Lazio"],
    "ata": ["Atalanta"],
    "fio": ["Fiorentina"],
    # Alemania
    "bay": ["Bayern München", "Bayern Munich", "FC Bayern München"],
    "bvb": ["Borussia Dortmund"],
    "rbl": ["RB Leipzig"],
    "lev": ["Bayer Leverkusen"],
    "bmg": ["Borussia Mönchengladbach", "Borussia Monchengladbach", "Mönchengladbach", "Monchengladbach"],
    "vfb": ["VfB Stuttgart", "Stuttgart"],
    "wob": ["VfL Wolfsburg", "Wolfsburg"],
    # Francia
    "psg": ["Paris Saint-Germain", "Paris SG", "PSG"],
    "om":  ["Olympique de Marseille", "Marseille"],
    "lyo": ["Olympique Lyonnais", "Lyon"],
    "lil": ["LOSC Lille", "Lille"],
    "nic": ["OGC Nice", "Nice"],
    "ren": ["Stade Rennais", "Rennes"],
    "nan": ["FC Nantes", "Nantes"],
}

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
    return ["laliga","premier","seriea","bundesliga","ligue1"]

# Liga -> (code, path)
COMP = {
    "premier":   ("GB1", "premier-league"),
    "laliga":    ("ES1", "laliga"),
    "seriea":    ("IT1", "serie-a"),
    "bundesliga":("L1",  "bundesliga"),
    "ligue1":    ("FR1", "ligue-1"),
}

# ============================
# Parsing helpers
# ============================
_DATE_RE = re.compile(r"\b(\d{2}/\d{2}/\d{4})\b")

_VALUE_HEADER_PATTERNS = [
    # EN / ES
    "total market value", "market value", "valor de mercado total", "valor de mercado",
    # DE
    "gesamtmarktwert", "marktwert",
    # FR
    "valeur marchande", "valeur marchande totale",
    # IT
    "valore di mercato", "valore di mercato totale",
    # comodín
    "value", "valeur", "wert", "mercato",
]

def _parse_cutoff_dates(html: str) -> List[datetime]:
    seen = set(_DATE_RE.findall(html))
    out = []
    for d in seen:
        try:
            out.append(datetime.strptime(d, "%d/%m/%Y"))
        except ValueError:
            pass
    return sorted(out, reverse=True)

def _pick_best_date(available: List[datetime], target: datetime) -> Optional[datetime]:
    for d in available:
        if d <= target:
            return d
    return None

def _select_value_table(soup: BeautifulSoup) -> Optional[BeautifulSoup]:
    """Devuelve la <table> que contiene los valores de mercado por club."""
    tables = soup.select("table.items") or soup.find_all("table")
    for table in tables:
        thead_ths = table.select("thead th")
        if not thead_ths:
            continue
        header_txt = " ".join(th.get_text(" ", strip=True) for th in thead_ths).lower()
        if not any(k in header_txt for k in ("club", "equipo", "verein", "équipe", "squadra")):
            continue
        rows = table.select("tbody tr")
        euro_hits = 0
        for tr in rows[:12]:
            if "€" in tr.get_text() or "â‚¬" in tr.get_text():
                euro_hits += 1
        if euro_hits >= 3:
            return table
    return soup.select_one("table.items")

def _find_value_col_index(table: BeautifulSoup) -> Optional[int]:
    ths = table.select("thead th")
    if not ths:
        return None
    # 1) por encabezado
    for idx, th in enumerate(ths):
        txt = (th.get_text(" ", strip=True) or "").lower()
        if any(pat in txt for pat in _VALUE_HEADER_PATTERNS):
            return idx
    # 2) por símbolo €
    rows = table.select("tbody tr")
    for col in range(min(12, len(ths))):
        euros_count = 0
        for tr in rows[:10]:
            tds = tr.find_all("td")
            if col < len(tds):
                cell = tds[col].get_text(strip=True) or ""
                if "€" in cell or "â‚¬" in cell:
                    euros_count += 1
        if euros_count >= 4:
            return col
    return None

def _find_club_col_index(table: BeautifulSoup) -> Optional[int]:
    ths = table.select("thead th")
    if not ths:
        return None
    for idx, th in enumerate(ths):
        txt = (th.get_text(" ", strip=True) or "").lower()
        if any(k in txt for k in ("club", "equipo", "verein", "équipe", "squadra")):
            return idx
    return 1 if len(ths) > 1 else 0

def _find_value_for_team(table: BeautifulSoup, team_candidates: List[str]) -> Optional[str]:
    vcol = _find_value_col_index(table)
    ccol = _find_club_col_index(table)
    if vcol is None or ccol is None:
        return None
    cand = {_norm(x) for x in (team_candidates or [])}
    for tr in table.select("tbody tr"):
        tds = tr.find_all("td")
        if len(tds) <= max(vcol, ccol):
            continue
        club_text = tds[ccol].get_text(" ", strip=True)
        if _norm(club_text) not in cand:
            continue
        val = tds[vcol].get_text(strip=True)
        if not val:
            continue
        return val.replace("â‚¬", "€")
    return None

# ============================
# Core: live + wayback
# ============================
def _try_live_cutoff_value(lg: str, code: str, path: str, d: datetime, candidates: List[str], debug=False) -> Optional[str]:
    base = f"https://www.transfermarkt.com/{path}/marktwerteverein/wettbewerb/{code}"
    try:
        r = _robust_get(base, debug=debug)
    except Exception as e:
        if debug: print(f"[{lg}] live error {e}")
        return None

    avail = _parse_cutoff_dates(r.text)
    if not avail:
        if debug: print(f"[{lg}] sin fechas de corte (live)")
        return None

    best = _pick_best_date(avail, d)
    if not best:
        if debug: print(f"[{lg}] no hay fecha <= {d:%d/%m/%Y} (live)")
        return None

    best_iso = best.strftime("%Y-%m-%d")
    date_urls = [
        f"{base}/stichtag/{best_iso}/plus/",
        f"{base}/stichtag/{best_iso}/",
        base,
    ]

    for u in date_urls:
        try:
            rr = _robust_get(u, debug=debug)
        except Exception as e:
            if debug: print(f"[{lg}] fallo live {u}: {e}")
            continue
        soup = BeautifulSoup(rr.text, "html.parser")
        table = _select_value_table(soup)
        if not table:
            if debug: print(f"[{lg}] tabla no identificada (live)")
            continue
        val = _find_value_for_team(table, candidates)
        if val:
            if debug: print(f"[OK][live] {candidates[0]} -> {val}")
            return val
    if debug: print(f"[{lg}] no encontré club en live")
    return None

def _try_wayback_value(lg: str, code: str, path: str, d: datetime, candidates: List[str], debug=False) -> Optional[str]:
    base = f"https://www.transfermarkt.com/{path}/marktwerteverein/wettbewerb/{code}"

    # Intento A: snapshot de la página base
    r = _wayback_fetch(base, d, debug=debug)
    if r:
        soup = BeautifulSoup(r.text, "html.parser")
        table = _select_value_table(soup)
        if table:
            val = _find_value_for_team(table, candidates)
            if val:
                if debug: print(f"[OK][wb-base] {candidates[0]} -> {val}")
                return val

    # Intento B: snapshot en el mes exacto (YYYY-MM-01)
    month_iso = d.strftime("%Y-%m-01")
    for u in (f"{base}/stichtag/{month_iso}/plus/", f"{base}/stichtag/{month_iso}/"):
        r2 = _wayback_fetch(u, d, debug=debug)
        if not r2:
            continue
        soup = BeautifulSoup(r2.text, "html.parser")
        table = _select_value_table(soup)
        if table:
            val = _find_value_for_team(table, candidates)
            if val:
                if debug: print(f"[OK][wb-month] {candidates[0]} -> {val}")
                return val

    # Intento C: meses anteriores (hasta 240 meses = 20 años)
    year, month = d.year, d.month
    for k in range(1, 241):
        mm = month - k
        yy = year
        while mm <= 0:
            yy -= 1
            mm += 12
        stamp_iso = f"{yy:04d}-{mm:02d}-01"
        for u in (f"{base}/stichtag/{stamp_iso}/plus/", f"{base}/stichtag/{stamp_iso}/"):
            r3 = _wayback_fetch(u, d, debug=debug)
            if not r3:
                continue
            soup = BeautifulSoup(r3.text, "html.parser")
            table = _select_value_table(soup)
            if not table:
                continue
            val = _find_value_for_team(table, candidates)
            if val:
                if debug: print(f"[OK][wb-{yy}-{mm}] {candidates[0]} -> {val}")
                return val
    if debug: print(f"[{lg}] Wayback sin resultados útiles")
    return None

# ============================
# API principal
# ============================
def get_team_value(slug_equipo: str, fecha: str, debug: bool=False) -> Optional[str]:
    """
    Devuelve el valor de mercado del equipo (ej. '€1.11bn' o '€462.10m')
    para la fecha dada (dd/mm/aa), usando:
      1) Transfermarkt live (cut-off <= fecha), y si no existe,
      2) Wayback Machine (snapshot <= fecha, con barrido mensual hacia atrás hasta 20 años).
    """
    try:
        d = datetime.strptime(fecha.strip(), "%d/%m/%y")
    except ValueError:
        raise ValueError("La fecha debe ser dd/mm/aa (ej. '6/10/25').")

    slug = slug_equipo.lower().strip()
    candidates = TEAM_NAME_CANDIDATES.get(slug, [])
    if not candidates:
        if debug: print(f"[WARN] sin candidatos para slug '{slug}' — añade en TEAM_NAME_CANDIDATES")
        return None

    leagues = _guess_leagues(slug)

    for lg in leagues:
        code, path = COMP[lg]

        # 1) Live
        val = _try_live_cutoff_value(lg, code, path, d, candidates, debug=debug)
        if val:
            return val

        # 2) Wayback
        val = _try_wayback_value(lg, code, path, d, candidates, debug=debug)
        if val:
            return val

    if debug:
        print("No se pudo obtener el valor de mercado (sin cut-offs ni snapshots adecuados).")
    return None
