
# -*- coding: utf-8 -*-
# utils/get_team_value.py

import re
import random
import time
from datetime import datetime
from typing import Optional, List, Dict, Tuple
import unicodedata

import requests
from bs4 import BeautifulSoup

# ============================
# HTTP / Headers / Backoff
# ============================
UA = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36",
]

def _headers():
    return {
        "User-Agent": random.choice(UA),
        "Accept-Language": "en-US,en;q=0.9,es;q=0.8,de;q=0.7,fr;q=0.7,it;q=0.7",
        "Referer": "https://www.transfermarkt.com/",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }

_S = requests.Session()

def _robust_get(url: str, max_retries=3, base_delay=1.2, debug=False) -> requests.Response:
    for i in range(max_retries):
        r = _S.get(url, headers=_headers(), timeout=25)
        if debug:
            print(f"[GET] {r.status_code} {url}")
        if r.status_code in (429,) or (500 <= r.status_code < 600):
            wait = base_delay * (2**i) + random.uniform(0, 0.8)
            if debug: print(f"[backoff] {r.status_code} -> sleep {wait:.1f}s")
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r
    raise RuntimeError(f"Max retries for {url}")

# ============================
# Wayback helpers (CDX + fetch)
# ============================
def _wayback_cdx(url: str, to_yyyymmdd: str, debug=False) -> Optional[str]:
    api = (
        "https://web.archive.org/cdx/search/cdx"
        f"?url={requests.utils.quote(url, safe='')}"
        f"&output=json&filter=statuscode:200&collapse=digest&to={to_yyyymmdd}"
    )
    try:
        r = _S.get(api, headers=_headers(), timeout=20)
        if debug: print(f"[WB-CDX] {r.status_code} {api}")
        r.raise_for_status()
        data = r.json()
        if not data or len(data) <= 1:
            return None
        return data[-1][1] if len(data[-1]) > 1 else None
    except Exception as e:
        if debug: print(f"[WB-CDX][err] {e}")
        return None

def _wayback_available(url: str, to_yyyymmdd: str, debug=False) -> Optional[str]:
    api = f"https://archive.org/wayback/available?url={requests.utils.quote(url, safe='')}&timestamp={to_yyyymmdd}"
    try:
        r = _S.get(api, headers=_headers(), timeout=20)
        if debug: print(f"[WB-AV] {r.status_code} {api}")
        r.raise_for_status()
        c = r.json().get("archived_snapshots", {}).get("closest")
        if not c or not c.get("available"):
            return None
        ts = c.get("timestamp")
        if ts and ts[:8] <= to_yyyymmdd:
            return ts
        return None
    except Exception as e:
        if debug: print(f"[WB-AV][err] {e}")
        return None

def _wayback_fetch(url: str, target: datetime, debug=False) -> Optional[requests.Response]:
    to_str = target.strftime("%Y%m%d")
    ts = _wayback_cdx(url, to_str, debug=debug) or _wayback_available(url, to_str, debug=debug)
    if not ts:
        return None
    wb = f"https://web.archive.org/web/{ts}/{url}"
    try:
        r = _S.get(wb, headers=_headers(), timeout=25)
        if debug: print(f"[WB] {r.status_code} {wb}")
        r.raise_for_status()
        return r
    except Exception as e:
        if debug: print(f"[WB][err] {e}")
        return None

# ============================
# Normalización / Mapeos
# ============================
def _norm(s: str) -> str:
    if not s: return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    return re.sub(r"[^a-z0-9]+", "", s)

TEAM_NAME_CANDIDATES: Dict[str, List[str]] = {
    # (igual que antes; recortado por brevedad)
    "bar": ["FC Barcelona", "Barcelona"],
    "rma": ["Real Madrid"],
    "atm": ["Atlético Madrid", "Atletico Madrid"],
    "sev": ["Sevilla FC", "Sevilla"],
    "soc": ["Real Sociedad"],
    "ath": ["Athletic Club", "Athletic Bilbao"],
    "bet": ["Real Betis"],
    "vil": ["Villarreal CF", "Villarreal"],
    "val": ["Valencia CF", "Valencia"],
    "cel": ["RC Celta de Vigo", "Celta de Vigo", "Celta Vigo"],
    "ray": ["Rayo Vallecano"],
    "gir": ["Girona FC", "Girona"],
    "get": ["Getafe CF", "Getafe"],
    "mlr": ["RCD Mallorca", "Mallorca"],
    "lpa": ["UD Las Palmas", "Las Palmas"],
    "ala": ["Deportivo Alavés", "Deportivo Alaves", "Alavés", "Alaves"],
    "gra": ["Granada CF", "Granada"],
    "osa": ["CA Osasuna", "Osasuna"],
    # …
}

def _guess_league_families(slug: str) -> List[str]:
    s = slug.lower()
    if s in {"bar","rma","atm","sev","soc","ath","bet","vil","val","cel","ray","gir","get","mlr","lpa","ala","gra","osa"}:
        return ["laliga"]
    # añade más si necesitas…
    return ["laliga","premier","seriea","bundesliga","ligue1"]

# ============================
# Familias y Tiers en Transfermarkt
# ============================
COMP_FAMILIES: Dict[str, List[Tuple[str, str]]] = {
    "premier": [("GB1", "premier-league"), ("GB2", "championship"), ("GB3", "league-one")],
    "laliga":  [("ES1", "laliga"), ("ES2", "laliga2"), ("ES3", "primera-division-rfef"), ("ES3", "segunda-division-b"), ("ES3","segundab")],
    "seriea":  [("IT1","serie-a"), ("IT2","serie-b"), ("IT3","serie-c")],
    "bundesliga":[("L1","bundesliga"), ("L2","2-bundesliga"), ("L3","3-liga")],
    "ligue1":  [("FR1","ligue-1"), ("FR2","ligue-2"), ("FR3","national")],
}

TM_DOMAINS = [
    "www.transfermarkt.com",
    "www.transfermarkt.us",
    "www.transfermarkt.de",
    "www.transfermarkt.co.uk",
]

# ============================
# Resolver ID y URLs correctas
# ============================
SLUG_TO_TMID: Dict[str, int] = {
    "bar": 131, "rma": 418, "atm": 13, "sev": 368, "soc": 681, "ath": 621, "bet": 150,
    "vil": 1050, "val": 1049,
    # añade más si usas otros equipos…
}

def _resolve_tm_id_from_league_tables(slug: str, debug=False) -> Optional[int]:
    candidates = TEAM_NAME_CANDIDATES.get(slug, [])
    slug_norm = _norm(slug)

    families = _guess_league_families(slug)
    for fam in families:
        tiers = COMP_FAMILIES.get(fam, [])
        for code, path in tiers:
            for dom in TM_DOMAINS:
                url = f"https://{dom}/{path}/marktwerteverein/wettbewerb/{code}"
                try:
                    r = _robust_get(url, debug=debug)
                except Exception as e:
                    if debug: print(f"[ID][{dom}][{fam}][{code}] error {e}")
                    continue
                soup = BeautifulSoup(r.text, "html.parser")
                table = soup.select_one("table.items") or soup.find("table")
                if not table:
                    continue
                for a in table.select("a[href*='/startseite/verein/']"):
                    name = a.get_text(" ", strip=True)
                    href = a.get("href", "")
                    # match exacto alias o heurístico
                    if candidates and _norm(name) in {_norm(x) for x in candidates}:
                        m = re.search(r"/startseite/verein/(\d+)/", href)
                        if m:
                            tm_id = int(m.group(1)); 
                            if debug: print(f"[ID] {name} -> {tm_id} ({fam} {code})")
                            return tm_id
                    if not candidates and slug_norm and slug_norm in _norm(name):
                        m = re.search(r"/startseite/verein/(\d+)/", href)
                        if m:
                            tm_id = int(m.group(1));
                            if debug: print(f"[ID-heur] {name} -> {tm_id} ({fam} {code})")
                            return tm_id
    return None

# === NUEVAS URLs de club (vigentes) para encontrar la serie/valor ===
def _club_candidate_urls(tm_id: int, year: int) -> List[str]:
    """
    Rutas actuales que suelen incluir la serie Highcharts de valor de mercado
    o, al menos, el “Total market value” impreso.
    """
    paths = [
        f"/startseite/verein/{tm_id}",                          # Home del club
        f"/datenfakten/verein/{tm_id}",                         # Datos/Facts
        f"/kader/verein/{tm_id}/saison_id/{year}/plus/1",       # Plantilla por temporada (detalle)
        f"/kader/verein/{tm_id}",                               # Plantilla (general)
    ]
    urls = []
    for dom in TM_DOMAINS:
        for p in paths:
            urls.append(f"https://{dom}{p}")
    return urls

# ============================
# Parser serie (Highcharts) + fallback “Total market value”
# ============================
# Highcharts: [ Date.UTC(y, m, d) , value ]  /  [ 1709760000000 , value ]
_PAIR_RE = re.compile(
    r"\[\s*(?:Date\.UTC\(\s*(\d{4})\s*,\s*(\d{1,2})\s*,\s*(\d{1,2})\s*\)|(\d{10,13}))\s*,\s*([0-9eE\+\-\.]+)\s*\]",
    re.MULTILINE
)

def _extract_series_points(html: str) -> List[Tuple[datetime, float]]:
    pts: List[Tuple[datetime, float]] = []
    for y, m, d, ts_ms, val in _PAIR_RE.findall(html):
        try:
            if ts_ms:
                ms = int(ts_ms)
                dt = datetime.utcfromtimestamp(ms / 1000.0) if len(ts_ms) == 13 else datetime.utcfromtimestamp(ms)
            else:
                dt = datetime(int(y), int(m) + 1, int(d))  # month 0..11
            v = float(val)
            pts.append((dt, v))
        except Exception:
            continue
    pts.sort(key=lambda x: x[0])
    return pts

def _pick_value_at_or_before(pts: List[Tuple[datetime, float]], target: datetime) -> Optional[float]:
    lo, hi = 0, len(pts) - 1
    best = None
    while lo <= hi:
        mid = (lo + hi) // 2
        if pts[mid][0] <= target:
            best = pts[mid]
            lo = mid + 1
        else:
            hi = mid - 1
    return None if best is None else best[1]

def _format_eur(value: float) -> str:
    if value >= 1_000_000_000:
        return f"€{value/1_000_000_000:.2f}bn"
    return f"€{value/1_000_000:.2f}m"

# Fallback: “Total market value” impreso en la página (no histórico, pero útil)
_TOTAL_VALUE_RE = re.compile(
    r"(Total\s+market\s+value|Gesamtmarktwert|Valor\s+de\s+mercado|Valeur\s+marchande).*?€\s?([\d\.\,]+)\s*(bn|m)?",
    re.IGNORECASE | re.DOTALL
)

def _extract_total_value_literal(html: str) -> Optional[str]:
    m = _TOTAL_VALUE_RE.search(html)
    if not m:
        return None
    num = m.group(2).replace(".", "").replace(",", ".")
    unit = (m.group(3) or "").lower()
    try:
        val = float(num)
    except Exception:
        return None
    # Si la página ya imprime en bn/m, respétalo
    if unit == "bn":
        return f"€{val:.2f}bn"
    if unit == "m" or unit == "":
        # muchas veces ya viene en “m”
        if unit == "m":
            return f"€{val:.2f}m"
        # si no hay unidad explícita, asumir millones si el número es grande
        if val > 1_000_000:  # por si viene crudo en euros (raro)
            return _format_eur(val)
        return f"€{val:.2f}m"
    return None

def _extract_value_from_club_pages(tm_id: int, target: datetime, debug=False) -> Optional[str]:
    """
    Intenta 1) serie histórica en páginas actuales; 2) literal de “Total market value”.
    Si live falla, intenta con Wayback respetando la fecha objetivo (mes/año).
    """
    year = target.year
    urls = _club_candidate_urls(tm_id, year)

    # LIVE
    for url in urls:
        try:
            r = _robust_get(url, debug=debug)
        except Exception:
            continue
        html = r.text
        # 1) Intentar serie
        pts = _extract_series_points(html)
        if pts:
            v = _pick_value_at_or_before(pts, target)
            if v is not None:
                if debug: print(f"[OK][HIST-LIVE] {url} -> {v}")
                return _format_eur(v)
        # 2) Fallback literal
        literal = _extract_total_value_literal(html)
        if literal:
            if debug: print(f"[OK][LITERAL-LIVE] {url} -> {literal}")
            return literal

    # WAYBACK (prueba mismas URLs)
    for url in urls:
        wb = _wayback_fetch(url, target, debug=debug)
        if not wb:
            continue
        html = wb.text
        pts = _extract_series_points(html)
        if pts:
            v = _pick_value_at_or_before(pts, target)
            if v is not None:
                if debug: print(f"[OK][HIST-WB] {url} -> {v}")
                return _format_eur(v)
        literal = _extract_total_value_literal(html)
        if literal:
            if debug: print(f"[OK][LITERAL-WB] {url} -> {literal}")
            return literal

    return None

# ============================
# Tablas por liga (fallback ya existente)
# ============================
def _select_value_table(soup: BeautifulSoup) -> Optional[BeautifulSoup]:
    tables = soup.select("table.items") or soup.find_all("table")
    for t in tables:
        ths = t.select("thead th")
        if not ths:
            continue
        header = " ".join(th.get_text(" ", strip=True) for th in ths).lower()
        if not any(k in header for k in ("club", "verein", "equipo", "équipe", "squadra")):
            continue
        euro_hits = 0
        for tr in t.select("tbody tr")[:12]:
            if "€" in tr.get_text() or "â‚¬" in tr.get_text():
                euro_hits += 1
        if euro_hits >= 3:
            return t
    return None

def _find_club_col_index(table: BeautifulSoup) -> Optional[int]:
    ths = table.select("thead th")
    if not ths:
        return None
    for idx, th in enumerate(ths):
        txt = (th.get_text(" ", strip=True) or "").lower()
        if any(k in txt for k in ("club", "verein", "equipo", "équipe", "squadra")):
            return idx
    return 1 if len(ths) > 1 else 0

def _date_header_candidates(d: datetime) -> List[str]:
    ddmmyyyy_slash = d.strftime("%d/%m/%Y")
    ddmmyyyy_dot   = d.strftime("%d.%m.%Y")
    month_en_short = d.strftime("%b %e, %Y").replace("  ", " ")
    month_en_long  = d.strftime("%B %e, %Y").replace("  ", " ")
    tokens = [
        f"value {month_en_short}", f"value {month_en_long}",
        f"as of {month_en_short}", f"as of {month_en_long}",
        f"valor {ddmmyyyy_slash}", f"valor de mercado {ddmmyyyy_slash}",
        f"wert {ddmmyyyy_dot}", f"marktwert {ddmmyyyy_dot}",
        f"valeur {ddmmyyyy_slash}",
        f"valore {ddmmyyyy_slash}",
    ]
    return [t.lower() for t in tokens]

def _find_value_col_index(table: BeautifulSoup, cutoff_date: Optional[datetime]=None) -> Optional[int]:
    ths = table.select("thead th")
    if not ths:
        return None
    if cutoff_date is not None:
        wanted = _date_header_candidates(cutoff_date)
        for idx, th in enumerate(ths):
            txt = (th.get_text(" ", strip=True) or "").lower()
            if any(w in txt for w in wanted):
                return idx
    generic_patterns = (
        "value", "valor", "marktwert", "valeur", "valore",
        "total market value", "valor de mercado"
    )
    generic_hits: List[int] = []
    for idx, th in enumerate(ths):
        txt = (th.get_text(" ", strip=True) or "").lower()
        if any(pat in txt for pat in generic_patterns):
            generic_hits.append(idx)
    if generic_hits:
        if cutoff_date is not None:
            for idx in generic_hits:
                t = (ths[idx].get_text(" ", strip=True) or "").lower()
                if not any(x in t for x in ("total market value", "gesamtmarktwert", "total")):
                    return idx
        return generic_hits[0]
    rows = table.select("tbody tr")
    for col in range(min(12, len(ths))):
        euros_count = 0
        for tr in rows[:10]:
            tds = tr.find_all("td")
            if col < len(tds):
                cell = (tds[col].get_text(" ", strip=True) or "")
                if "€" in cell or "â‚¬" in cell:
                    euros_count += 1
        if euros_count >= 4:
            return col
    return None

def _find_value_for_team(table: BeautifulSoup, team_candidates: List[str], cutoff_date: Optional[datetime]=None, slug_hint: Optional[str]=None) -> Optional[str]:
    vcol = _find_value_col_index(table, cutoff_date=cutoff_date)
    ccol = _find_club_col_index(table)
    if vcol is None or ccol is None:
        return None
    cand = {_norm(x) for x in team_candidates}
    slug_norm = _norm(slug_hint or "")
    for tr in table.select("tbody tr"):
        tds = tr.find_all("td")
        if len(tds) <= max(ccol, vcol):
            continue
        name = tds[ccol].get_text(" ", strip=True)
        name_norm = _norm(name)
        if cand and name_norm not in cand:
            continue
        if not cand and (not slug_norm or slug_norm not in name_norm):
            continue
        raw = tds[vcol].get_text(" ", strip=True)
        if raw:
            return raw.replace("â‚¬", "€")
    return None

def _try_league_tables_all_tiers(family: str, target: datetime, candidates: List[str], slug: str, debug=False) -> Optional[str]:
    cut_date = datetime(target.year, target.month, 1)
    cut_month = cut_date.strftime("%Y-%m-01")
    tiers = COMP_FAMILIES.get(family, [])
    suffixes = [f"/stichtag/{cut_month}/plus/", f"/stichtag/{cut_month}/", ""]
    # LIVE
    for code, path in tiers:
        for dom in TM_DOMAINS:
            base = f"https://{dom}/{path}/marktwerteverein/wettbewerb/{code}"
            for suf in suffixes:
                url = base + suf
                try:
                    r = _robust_get(url, debug=debug)
                except Exception:
                    continue
                soup = BeautifulSoup(r.text, "html.parser")
                table = _select_value_table(soup)
                if not table:
                    continue
                val = _find_value_for_team(table, candidates, cutoff_date=cut_date, slug_hint=slug)
                if val:
                    if debug: print(f"[OK][LIVE-LIGA]{family} {code} -> {val}")
                    return val
    # WAYBACK (±12 meses)
    def _month_back_iter(d: datetime, months: int):
        y, m = d.year, d.month
        for k in range(months+1):
            yy = y
            mm = m - k
            while mm <= 0:
                yy -= 1
                mm += 12
            yield yy, mm

    for code, path in tiers:
        for dom in TM_DOMAINS:
            base = f"https://{dom}/{path}/marktwerteverein/wettbewerb/{code}"
            for yy, mm in _month_back_iter(target, 12):
                month_iso = f"{yy:04d}-{mm:02d}-01"
                month_date = datetime(yy, mm, 1)
                for suf in (f"/stichtag/{month_iso}/plus/", f"/stichtag/{month_iso}/"):
                    url = base + suf
                    wb = _wayback_fetch(url, target, debug=debug)
                    if not wb:
                        continue
                    soup = BeautifulSoup(wb.text, "html.parser")
                    table = _select_value_table(soup)
                    if not table:
                        continue
                    val = _find_value_for_team(table, candidates, cutoff_date=month_date, slug_hint=slug)
                    if val:
                        if debug: print(f"[OK][WB-LIGA]{family} {code} {month_iso} -> {val}")
                        return val
    return None

# ============================
# API principal
# ============================
def get_team_value(slug_equipo: str, fecha: str, debug: bool=False) -> Optional[str]:
    """
    Devuelve el valor de mercado del equipo (ej. '€1.11bn' o '€462.10m')
    para la fecha dada (dd/mm/aa), cubriendo 1ª–3ª división en las 5 grandes ligas.
    Estrategia:
      1) Resolver TM ID (mapa o tablas 1–3).
      2) Intentar páginas vigentes del club (home/datos/kader) -> serie Highcharts o 'Total market value'.
      3) Fallback: tablas por liga (live; si no, Wayback ±12 meses).
    """
    try:
        target = datetime.strptime(fecha.strip(), "%d/%m/%y")
    except ValueError:
        raise ValueError("La fecha debe ser dd/mm/aa (ej. '06/10/05').")

    slug = slug_equipo.lower().strip()
    candidates = TEAM_NAME_CANDIDATES.get(slug, [])

    # 1) Resolver TM ID
    tm_id = SLUG_TO_TMID.get(slug)
    if tm_id is None:
        if debug: print("[ID] Resolviendo TM ID desde tablas 1–3…")
        tm_id = _resolve_tm_id_from_league_tables(slug, debug=debug)

    # 2) Páginas vigentes del club (serie o literal)
    if tm_id is not None:
        val = _extract_value_from_club_pages(tm_id, target, debug=debug)
        if val:
            return val

    # 3) Fallback: tablas por liga
    families = _guess_league_families(slug)
    for fam in families:
        val = _try_league_tables_all_tiers(fam, target, candidates, slug, debug=debug)
        if val:
            return val

    if debug:
        print("No se pudo obtener el valor de mercado (club pages y tablas por liga fallaron).")
    return None
