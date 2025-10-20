# -*- coding: utf-8 -*-
# utils/get_team_value.py
"""
Obtiene el valor de mercado de un equipo (Transfermarkt) en una fecha dada.
Entrada:
  - slug_equipo: str  (p.ej., 'sev', 'bar', 'mci', 'psg' ...)
  - fecha: 'dd/mm/aa'
  - liga:  hint ['laliga'|'premier'|'seriea'|'bundesliga'|'ligue1'] o ''/None
Salida:
  - str con formato '€X.XXm' o '€X.XXbn' (o None si no se puede determinar)
Cobertura:
  - Top-5 ligas europeas (1ª, 2ª y 3ª división)
  - Fechas 1995–2025 (vía páginas vigentes y Wayback Machine)
Estrategia:
  1) Resolver tm_id a partir del slug (caché + scraping de tablas 1–3)
  2) Intentar páginas del club (varias rutas y dominios):
       - Serie Highcharts (histórico exacto) o literal "Total market value"
       - Si no hay versión viva, intentar Wayback ≤ 24 meses atrás
  3) Fallback: tablas por liga (live; si no, Wayback por mes) y localizar el club
  4) Cachear por (slug|YYYYMM)
"""

import re
import os
import json
import random
import time
from datetime import datetime
from typing import Optional, List, Dict, Tuple
import unicodedata

import requests
from bs4 import BeautifulSoup

# ============================
# Config y cachés
# ============================
UA = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36",
]

TM_DOMAINS = [
    "www.transfermarkt.com",
    "www.transfermarkt.us",
    "www.transfermarkt.de",
    "www.transfermarkt.co.uk",
]

TMID_CACHE_FILE = "tm_id_cache.json"        # { slug: tm_id }
VALUE_CACHE_FILE = "value_cache.json"       # { "<slug>|YYYYMM": "€xxx" }
_TMID_CACHE: Dict[str, int] = {}
_VALUE_CACHE: Dict[str, str] = {}

# ============================
# HTTP / Headers / Backoff
# ============================
def _headers():
    return {
        "User-Agent": random.choice(UA),
        "Accept-Language": "en-US,en;q=0.9,es;q=0.8,de;q=0.7,fr;q=0.7,it;q=0.7",
        "Referer": "https://www.transfermarkt.com/",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }

_S = requests.Session()

# rate limit local suave
_LAST_CALL_TS = 0.0
_MIN_INTERVAL = 0.9
def _polite_pause():
    global _LAST_CALL_TS
    now = time.monotonic()
    delta = _MIN_INTERVAL - (now - _LAST_CALL_TS)
    if delta > 0:
        time.sleep(0)
    _LAST_CALL_TS = time.monotonic()

def _robust_get(url: str, max_retries=4, base_delay=1.4, debug=False) -> requests.Response:
    last_exc = None
    for i in range(max_retries):
        try:
            _polite_pause()
            r = _S.get(url, headers=_headers(), timeout=25, allow_redirects=True)
            if debug:
                print(f"[GET] {r.status_code} {url}")
            # 404 u otros 4xx (salvo 429) no sirven reintentar: salir
            if r.status_code == 404:
                return r  # que el caller decida
            if r.status_code == 429 or (500 <= r.status_code < 600):
                wait = base_delay * (2**i) + random.uniform(0, 0.9)
                if debug: print(f"[backoff] {r.status_code} -> sleep {wait:.1f}s")
                time.sleep(0)
                continue
            r.raise_for_status()
            return r
        except Exception as e:
            last_exc = e
            wait = base_delay * (2**i) + random.uniform(0, 0.6)
            if debug: print(f"[GET-err] {e} -> sleep {wait:.1f}s")
            time.sleep(0)
    if last_exc:
        raise last_exc
    raise RuntimeError(f"Max retries for {url}")

# ============================
# Wayback helpers (CDX + fetch) — hasta 24 meses atrás
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
    except Exception:
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
    except Exception:
        return None

def _wayback_fetch(url: str, target: datetime, debug=False, months_back=24) -> Optional[requests.Response]:
    y, m = target.year, target.month
    for k in range(months_back + 1):
        yy = y
        mm = m - k
        while mm <= 0:
            yy -= 1
            mm += 12
        ts_try = f"{yy:04d}{mm:02d}28"  # fin de mes aprox
        ts = _wayback_cdx(url, ts_try, debug=debug) or _wayback_available(url, ts_try, debug=debug)
        if not ts:
            continue
        wb = f"https://web.archive.org/web/{ts}/{url}"
        try:
            _polite_pause()
            r = _S.get(wb, headers=_headers(), timeout=25)
            if debug: print(f"[WB] {r.status_code} {wb}")
            r.raise_for_status()
            return r
        except Exception as e:
            if debug: print(f"[WB-err] {e} {wb}")
            continue
    return None

# ============================
# Normalización y utilidades
# ============================
def _norm(s: str) -> str:
    if not s: return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    return re.sub(r"[^a-z0-9]+", "", s)

def _normalize(s: str) -> str:
    norm = unicodedata.normalize("NFKD", s or "")
    cleaned = "".join(c for c in norm if not unicodedata.combining(c)).lower()
    return re.sub(r"[\s\.\-’'`_]+", "", cleaned)

def slugify_team(name: str) -> str:
    cleaned = _normalize(name)
    aliases = {
        # Atajos frecuentes (solo unos pocos; el matching usa heurísticas)
        "realmadrid":"rma","fcbarcelona":"bar","barcelona":"bar","sevilla":"sev",
        "atleticodemadrid":"atm","valencia":"val","villarreal":"vil","realbetis":"bet",
        "realsociedad":"soc","athleticclub":"ath","athleticbilbao":"ath","osasuna":"osa",
        "celtadevigo":"cel","rayovallecano":"ray","udlaspalmas":"lpa","alaves":"ala",
        "granadacf":"gra","rcdmallorca":"mlr",
        "parissaintgermain":"psg","rbleipzig":"rbl",
        "borussiadortmund":"bvb","bayernmunchen":"bay","bayernmunich":"bay",
        "olympiquemarseille":"om","olympiquelyonnais":"lyo",
    }
    return aliases.get(cleaned, cleaned[:3] if len(cleaned) >= 3 else cleaned)

def _initials_slug(name: str) -> str:
    tokens = re.findall(r"[A-Za-zÀ-ÿ0-9]+", name or "")
    IGNORE = {"fc","cf","sc","ac","ud","cd","rcd","ssc","sv","vfl","vfb","rb","as","ss",
              "ks","ofk","fk","pfc","afc","sk","nk","bk","if","us","sd","deportivo","club",
              "real","athletic","sporting","hotspur","queens","rangers","city","united","town"}
    initials = []
    for t in tokens:
        t_clean = _norm(t)
        if not t_clean or t_clean in IGNORE:
            continue
        initials.append(t_clean[0])
    if not initials:
        for t in tokens:
            if t.isdigit():
                initials.append(t[0])
    return "".join(initials)[:3]

# ============================
# Familias y Tiers (1ª/2ª/3ª)
# ============================
COMP_FAMILIES: Dict[str, List[Tuple[str, str]]] = {
    "premier":   [("GB1", "premier-league"), ("GB2", "championship"), ("GB3", "league-one")],
    "laliga":    [("ES1", "laliga"), ("ES2", "laliga2"),
                  ("ES3", "primera-division-rfef"), ("ES3", "segunda-division-b"), ("ES3", "segundab")],
    "seriea":    [("IT1","serie-a"), ("IT2","serie-b"), ("IT3","serie-c")],
    "bundesliga":[("L1","bundesliga"), ("L2","2-bundesliga"), ("L3","3-liga")],
    "ligue1":    [("FR1","ligue-1"), ("FR2","ligue-2"), ("FR3","national")],
}

def _guess_league_families_by_slug(slug: str) -> List[str]:
    s = slug.lower()
    if s in {"bar","rma","atm","sev","soc","ath","bet","vil","val","cel","ray","gir","get","mlr","lpa","ala","gra","osa"}:
        return ["laliga"]
    if s in {"mci","mun","liv","ars","che","tot","new","whu","avl","eve","bha","bre","bou","cry","ful","wol","for","qpr","lee","nor","ips","lei","sou","shf","wba"}:
        return ["premier"]
    if s in {"juv","int","mil","nap","rom","laz","ata","fio","tor","bol","gen","sam","cag","emp","udi","par","pal","bre"}:
        return ["seriea"]
    if s in {"bay","bvb","rbl","lev","bmg","vfb","wob","sge","svw","scf","fca","kol","m05"}:
        return ["bundesliga"]
    if s in {"psg","om","lyo","lil","nic","ren","nan","rcl","rcs","tou","rei","aux","met"}:
        return ["ligue1"]
    # fallback: probar todas
    return ["laliga","premier","seriea","bundesliga","ligue1"]

def _families_from_hint_or_slug(liga_hint: Optional[str], slug: str) -> List[str]:
    if liga_hint:
        hint = liga_hint.strip().lower()
        if hint in COMP_FAMILIES:
            return [hint]
    return _guess_league_families_by_slug(slug)

# ============================
# Resolver tm_id (caché + scraping)
# ============================
SLUG_TO_TMID: Dict[str, int] = {
    # algunos más comunes para acelerar
    "bar": 131, "rma": 418, "atm": 13, "sev": 368, "soc": 681, "ath": 621, "bet": 150,
    "vil": 1050, "val": 1049, "psg": 583, "bvb": 16, "bay": 27, "mci": 281, "mun": 985, "liv": 31,
}

def _load_tmid_cache():
    global _TMID_CACHE
    if _TMID_CACHE:
        return
    if os.path.exists(TMID_CACHE_FILE):
        try:
            with open(TMID_CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    _TMID_CACHE = {k: int(v) for k, v in data.items()}
        except Exception:
            _TMID_CACHE = {}

def _save_tmid_cache():
    if not _TMID_CACHE:
        return
    try:
        with open(TMID_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(_TMID_CACHE, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def _slug_matches_name(slug: str, name: str) -> bool:
    s = slug.lower().strip()
    name_norm = _norm(name)
    # heurística amplia: iniciales, slug en nombre, slugify(nombre) o coincidencia leve
    if s == _initials_slug(name):
        return True
    if s and s in name_norm:
        return True
    if s == slugify_team(name):
        return True
    # tolera pequeños desajustes (p.ej., "bilbao" vs "athleticbilbao")
    if len(s) >= 3 and s[:3] in name_norm:
        return True
    return False

def _resolve_tm_id_from_league_tables(slug: str, families: List[str], debug=False) -> Optional[int]:
    _load_tmid_cache()
    if slug in _TMID_CACHE:
        return _TMID_CACHE[slug]

    for fam in families:
        tiers = COMP_FAMILIES.get(fam, [])
        for code, path in tiers:  # 1ª, 2ª y 3ª
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
                    if not _slug_matches_name(slug, name):
                        continue
                    href = a.get("href", "")
                    m = re.search(r"/startseite/verein/(\d+)/", href)
                    if m:
                        tm_id = int(m.group(1))
                        if debug: print(f"[ID] {name} -> {tm_id} ({fam} {code})")
                        _TMID_CACHE[slug] = tm_id
                        _save_tmid_cache()
                        return tm_id
    return None

# ============================
# Rutas de club (múltiples) para datos
# ============================
def _club_candidate_urls(tm_id: int, year: int) -> List[str]:
    """
    Prioriza rutas que NO requieren el segmento de nombre.
    Deja 'startseite' y 'datenfakten' al final con un stub neutral.
    """
    id_only_paths = [
        # históricas/analíticas que suelen contener la serie Highcharts
        f"/verein/{tm_id}/marktwertentwicklung",
        f"/verein/{tm_id}/historie/marktwertverein",
        f"/verein/{tm_id}/historie/marktwertentwicklung",
        f"/profil/verein/{tm_id}/marktwert",
        # plantillas por temporada (normalmente no requieren nombre)
        f"/kader/verein/{tm_id}/saison_id/{year}/plus/1",
        f"/kader/verein/{tm_id}",
    ]
    # Rutas que normalmente requieren el nombre. Usamos un stub 'club' para reducir 404.
    name_dependent_paths = [
        f"/club/startseite/verein/{tm_id}",
        f"/club/datenfakten/verein/{tm_id}",
    ]

    urls = []
    for dom in TM_DOMAINS:
        for p in id_only_paths:
            urls.append(f"https://{dom}{p}")
        for p in name_dependent_paths:
            urls.append(f"https://{dom}{p}")
    return urls

# ============================
# Parsers de valores (serie + literales)
# ============================
# Serie Highcharts: [Date.UTC(y,m,d), value] o [timestamp_ms, value]
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

# Literales multi-idioma: bn/m, Mio., Mrd., etc.
_LITERAL_BLOCK_RE = re.compile(
    r"(Total\s*market\s*value|Gesamtmarktwert|Valor\s*de\s*mercado|Valeur\s*marchande|Valore\s*di\s*mercato)[^€]*€\s*([0-9\.\,]+)\s*(bn|m|mio\.?|mrd\.?)?",
    re.IGNORECASE | re.DOTALL
)

def _extract_total_value_literal(html: str) -> Optional[str]:
    m = _LITERAL_BLOCK_RE.search(html)
    if not m:
        return None
    raw_num = m.group(2).strip()
    unit = (m.group(3) or "").lower().replace(" ", "")

    # normaliza 1.234,56 -> 1234.56
    num = raw_num.replace(".", "").replace(",", ".")
    try:
        val = float(num)
    except Exception:
        return None

    if unit in ("bn", "mrd", "mrd."):
        return f"€{val:.2f}bn"
    if unit in ("m", "mio", "mio."):
        return f"€{val:.2f}m"

    if val >= 1_000_000_000:
        return _format_eur(val)
    if val >= 1_000_000:
        return _format_eur(val)
    return f"€{val:.2f}m"

def _extract_value_from_html(html: str, target: datetime) -> Optional[str]:
    # 1) Serie
    pts = _extract_series_points(html)
    if pts:
        v = _pick_value_at_or_before(pts, target)
        if v is not None:
            return _format_eur(v)
    # 2) Literal directo
    lit = _extract_total_value_literal(html)
    if lit:
        return lit
    # 3) Fallback: parseo de texto global con BS
    try:
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(" ", strip=True)
        lit = _extract_total_value_literal(text)
        if lit:
            return lit
    except Exception:
        pass
    return None

# ============================
# Extracción por club (live + wayback)
# ============================
def _extract_value_from_club_pages(tm_id: int, target: datetime, debug=False) -> Optional[str]:
    year = max(min(target.year, 2025), 1995)
    urls = _club_candidate_urls(tm_id, year)

    # LIVE
    for url in urls:
        try:
            r = _robust_get(url, debug=debug)
            val = _extract_value_from_html(r.text, target)
            if val:
                if debug: print(f"[OK][LIVE] {url} -> {val}")
                return val
        except Exception:
            continue

    # WAYBACK (≤24 meses atrás)
    for url in urls:
        wb = _wayback_fetch(url, target, debug=debug, months_back=24)
        if not wb:
            continue
        val = _extract_value_from_html(wb.text, target)
        if val:
            if debug: print(f"[OK][WB] {url} -> {val}")
            return val

    return None

# ============================
# Tablas por liga (fallback)
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
        for tr in t.select("tbody tr")[:15]:
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
    generic_patterns = ("value","valor","marktwert","valeur","valore","total market value","valor de mercado")
    generic_hits: List[int] = []
    for idx, th in enumerate(ths):
        txt = (th.get_text(" ", strip=True) or "").lower()
        if any(pat in txt for pat in generic_patterns):
            generic_hits.append(idx)
    if generic_hits:
        if cutoff_date is not None:
            for idx in generic_hits:
                t = (ths[idx].get_text(" ", strip=True) or "").lower()
                if not any(x in t for x in ("total market value","gesamtmarktwert","total")):
                    return idx
        return generic_hits[0]
    rows = table.select("tbody tr")
    for col in range(min(12, len(ths))):
        euros_count = 0
        for tr in rows[:12]:
            tds = tr.find_all("td")
            if col < len(tds):
                cell = (tds[col].get_text(" ", strip=True) or "")
                if "€" in cell or "â‚¬" in cell:
                    euros_count += 1
        if euros_count >= 4:
            return col
    return None

def _find_value_for_team(table: BeautifulSoup, slug: str, cutoff_date: Optional[datetime]=None) -> Optional[str]:
    vcol = _find_value_col_index(table, cutoff_date=cutoff_date)
    ccol = _find_club_col_index(table)
    if vcol is None or ccol is None:
        return None
    for tr in table.select("tbody tr"):
        tds = tr.find_all("td")
        if len(tds) <= max(ccol, vcol):
            continue
        name = tds[ccol].get_text(" ", strip=True)
        # comprobar matching por slug (iniciales, slugify, contains…)
        if not _slug_matches_name(slug, name):
            continue
        raw = tds[vcol].get_text(" ", strip=True)
        if raw:
            txt = raw.replace("â‚¬", "€")
            lit = _extract_total_value_literal(f"Total market value € {txt}")
            if lit:
                return lit
    return None

def _try_league_tables_all_tiers(families: List[str], target: datetime, slug: str, debug=False) -> Optional[str]:
    cut_date = datetime(target.year, target.month, 1)
    cut_month = cut_date.strftime("%Y-%m-01")
    suffixes = [f"/stichtag/{cut_month}/plus/", f"/stichtag/{cut_month}/", ""]

    # LIVE primero
    for fam in families:
        tiers = COMP_FAMILIES.get(fam, [])
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
                    val = _find_value_for_team(table, slug, cutoff_date=cut_date)
                    if val:
                        if debug: print(f"[OK][LIVE-LIGA]{fam} {code} -> {val}")
                        return val

    # WAYBACK por meses (hasta 24m atrás)
    def _month_back_iter(d: datetime, months: int):
        y, m = d.year, d.month
        for k in range(months+1):
            yy = y
            mm = m - k
            while mm <= 0:
                yy -= 1
                mm += 12
            yield yy, mm

    for fam in families:
        tiers = COMP_FAMILIES.get(fam, [])
        for code, path in tiers:
            for dom in TM_DOMAINS:
                base = f"https://{dom}/{path}/marktwerteverein/wettbewerb/{code}"
                for yy, mm in _month_back_iter(target, 24):
                    month_iso = f"{yy:04d}-{mm:02d}-01"
                    month_date = datetime(yy, mm, 1)
                    for suf in (f"/stichtag/{month_iso}/plus/", f"/stichtag/{month_iso}/"):
                        url = base + suf
                        wb = _wayback_fetch(url, target, debug=debug, months_back=0)  # ese mismo mes si existe
                        if not wb:
                            continue
                        soup = BeautifulSoup(wb.text, "html.parser")
                        table = _select_value_table(soup)
                        if not table:
                            continue
                        val = _find_value_for_team(table, slug, cutoff_date=month_date)
                        if val:
                            if debug: print(f"[OK][WB-LIGA]{fam} {code} {month_iso} -> {val}")
                            return val
    return None

# ============================
# Caché de valores (slug+YYYYMM)
# ============================
def _load_value_cache():
    global _VALUE_CACHE
    if _VALUE_CACHE:
        return
    if os.path.exists(VALUE_CACHE_FILE):
        try:
            with open(VALUE_CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    _VALUE_CACHE = {k: str(v) for k, v in data.items()}
        except Exception:
            _VALUE_CACHE = {}

def _save_value_cache():
    if not _VALUE_CACHE:
        return
    try:
        with open(VALUE_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(_VALUE_CACHE, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def _cache_key(slug: str, dt: datetime) -> str:
    return f"{slug}|{dt.strftime('%Y%m')}"

# ============================
# API principal
# ============================
def get_team_value(slug_equipo: str, fecha: str, liga: Optional[str] = None, debug: bool=False) -> Optional[str]:
    """
    Devuelve el valor de mercado del equipo (p.ej., '€1.11bn' o '€462.10m')
    para la fecha (dd/mm/aa), soportando 1ª–3ª división de las 5 grandes ligas y 1995–2025.

    Parámetros:
      - slug_equipo: str (p.ej. 'sev', 'bar', 'mci', 'psg')
      - fecha: 'dd/mm/aa'
      - liga: 'laliga'|'premier'|'seriea'|'bundesliga'|'ligue1' o None/'' (hint para acotar scraping)
      - debug: bool

    Retorna:
      - str ('€X.XXm' / '€X.XXbn') o None si no se puede determinar.
    """
    try:
        target = datetime.strptime(fecha.strip(), "%d/%m/%y")
    except ValueError:
        raise ValueError("La fecha debe ser dd/mm/aa (ej. '06/10/05').")

    # limitar rango “útil” por si la fecha se sale
    if target.year < 1995:
        target = datetime(1995, max(target.month, 1), 1)
    if target.year > 2025:
        target = datetime(2025, min(target.month, 12), 28)

    slug = (slug_equipo or "").lower().strip()
    if not slug or len(slug) < 2:
        raise ValueError("slug_equipo inválido.")

    _load_value_cache()
    ck = _cache_key(slug, target)
    if ck in _VALUE_CACHE:
        return _VALUE_CACHE[ck]

    # familias a consultar (por hint o heurística de slug)
    families = _families_from_hint_or_slug(liga, slug)

    # 1) Resolver tm_id: mapa rápido -> caché -> scraping por ligas (1–3)
    _load_tmid_cache()
    tm_id = SLUG_TO_TMID.get(slug) or _TMID_CACHE.get(slug)
    if tm_id is None:
        tm_id = _resolve_tm_id_from_league_tables(slug, families, debug=debug)

    # 2) Páginas del club (live + wayback)
    if tm_id is not None:
        val = _extract_value_from_club_pages(tm_id, target, debug=debug)
        if val:
            _VALUE_CACHE[ck] = val
            _save_value_cache()
            return val

    # 3) Fallback: tablas por liga (live + wayback)
    val = _try_league_tables_all_tiers(families, target, slug, debug=debug)
    if val:
        _VALUE_CACHE[ck] = val
        _save_value_cache()
        return val

    if debug:
        print("No se pudo obtener el valor de mercado (club pages + tablas por liga fallaron).")
    return None
