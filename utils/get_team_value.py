# -*- coding: utf-8 -*-
"""
get_team_value.py (v4) — official team name only (no candidates)

Función pública:
    get_team_value(team_name: str, year: int, debug: bool = False) -> dict

- Recibe el **nombre oficial completo del equipo** (p. ej. "FC Barcelona").
- **No** busca múltiples candidatos: intenta resolver **exactamente ese nombre** en Transfermarkt
  (comparación normalizada por acentos y palabras vacías como "FC", "CF", etc.).
- Una vez resuelto el club (id + slug + URL de portada), intenta extraer la serie histórica
  de valor de plantilla ("Kaderwert") **desde la portada**. Si no aparece allí, prueba URLs
  alternativas de historial.
- Devuelve el valor (M€) correspondiente al AÑO (1995–2025). Si no hay punto del año,
  usa el más cercano o interpola alrededor del 30 de junio.

Requisitos: requests, beautifulsoup4
"""
from __future__ import annotations

import datetime as _dt
import json as _json
import re as _re
import time as _time
import unicodedata as _unicodedata
from dataclasses import dataclass as _dataclass
from typing import List, Tuple, Optional, Dict, Any

import requests as _requests
from bs4 import BeautifulSoup as _BS
from urllib.parse import quote as _quote, urljoin as _urljoin

_BASE = "https://www.transfermarkt.com"


@_dataclass
class _Club:
    name: str
    id: int
    url: str        # /<slug>/startseite/verein/<id>
    slug: str


class _Http:
    def __init__(self, timeout: int = 20, retries: int = 3, backoff: float = 0.8, debug: bool = False):
        self.session = _requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9,es;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Connection": "keep-alive",
        })
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff
        self.debug = debug

    def get(self, url: str, **kwargs) -> _requests.Response:
        last_exc = None
        for attempt in range(self.retries):
            try:
                if self.debug:
                    print(f"[HTTP] GET {url}")
                resp = self.session.get(url, timeout=self.timeout, **kwargs)
                if resp.status_code in (429, 503):
                    if self.debug:
                        print(f"[HTTP] status={resp.status_code}, retry backoff {self.backoff*(attempt+1):.1f}s")
                    _time.sleep(self.backoff * (attempt + 1))
                    continue
                resp.raise_for_status()
                return resp
            except Exception as e:
                last_exc = e
                if self.debug:
                    print(f"[HTTP] error attempt {attempt+1}: {e}")
                _time.sleep(self.backoff * (attempt + 1))
        if last_exc:
            raise last_exc
        raise RuntimeError("HTTP error without exception?")


_STOPWORDS = {
    "fc","cf","club","de","futbol","fútbol","sociedad","deportiva","sd","ca","sc","ac",
    "cd","ud","sad","s.a.d.","afc","c.f.","f.c.","u.d.","s.c.","s.d.","c.d.","clubesportiu",
    "clubesportivo","clubesportivo","sporting","athletic","club", "sociedaddeportiva"
}

def _normalize_name(s: str) -> str:
    s = s.lower().strip()
    s = _unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not _unicodedata.combining(ch))
    tokens = [t for t in _re.split(r"[^a-z0-9]+", s) if t]
    tokens = [t for t in tokens if t not in _STOPWORDS]
    return " ".join(tokens)


def _resolve_club_by_official_name(team_name: str, http: _Http) -> _Club:
    """
    Resuelve exactamente el club cuyo nombre normalizado coincide con el nombre pedido.
    Si no hay match exacto, lanza error.
    """
    if not team_name or not team_name.strip():
        raise ValueError("team_name vacío.")

    norm_target = _normalize_name(team_name)
    search_url = f"{_BASE}/schnellsuche/ergebnis/schnellsuche?query={_quote(team_name.strip())}"
    r = http.get(search_url)
    soup = _BS(r.text, "html.parser")

    matches: List[_Club] = []
    for a in soup.select('a[href*="/startseite/verein/"]'):
        href = a.get("href", "")
        m = _re.search(r"/([^/]+)/startseite/verein/(\d+)", href)
        if not m:
            continue
        slug, cid = m.group(1), int(m.group(2))
        name = a.get_text(strip=True) or team_name
        n = _normalize_name(name)
        if n == norm_target:
            matches.append(_Club(name=name, id=cid, url=_urljoin(_BASE, href), slug=slug))

    # Si no hubo coincidencia exacta, intentar coincidencia "muy cercana" (startswith) pero única
    if not matches:
        close: List[_Club] = []
        for a in soup.select('a[href*="/startseite/verein/"]'):
            href = a.get("href", "")
            m = _re.search(r"/([^/]+)/startseite/verein/(\d+)", href)
            if not m:
                continue
            slug, cid = m.group(1), int(m.group(2))
            name = a.get_text(strip=True) or team_name
            n = _normalize_name(name)
            if n.startswith(norm_target) or norm_target.startswith(n):
                close.append(_Club(name=name, id=cid, url=_urljoin(_BASE, href), slug=slug))
        # Si hay exactamente uno, lo tomamos; si hay varios, pedimos exactitud
        if len(close) == 1:
            matches = close

    if not matches:
        raise LookupError(
            f"No encontré un club con nombre oficial exactamente '{team_name}'. "
            f"Por favor usa el nombre completo tal cual aparece en Transfermarkt."
        )
    # Si hay múltiples con exactamente el mismo normalizado, elegimos aquel cuyo slug contiene
    # algún token del nombre (por estabilidad) y que no parezca filial.
    def is_reserve(slug: str) -> bool:
        sl = slug.lower()
        return any(x in sl for x in ["-ii", "-b", "-u19", "-u17", "-u23", "reserves", "juvenil", "aufgel"])

    preferred = sorted(matches, key=lambda c: (is_reserve(c.slug), -len(c.slug)))[0]
    if http.debug:
        print(f"[DEBUG] club resuelto: {preferred.name} (id={preferred.id}, slug={preferred.slug}) -> {preferred.url}")
    return preferred


def _parse_series_from_html(html: str) -> List[Tuple[_dt.date, float]]:
    patterns = [
        _re.compile(r'name\s*:\s*["\']Kaderwert["\'].*?data\s*:\s*(\[.*?\])', _re.DOTALL),
        _re.compile(r'name\s*:\s*["\']Squad value["\'].*?data\s*:\s*(\[.*?\])', _re.DOTALL),
        _re.compile(r'data\s*:\s*(\[\s*\[.*?\]\s*(?:,\s*\[.*?\]\s*)*\])', _re.DOTALL),
    ]
    m = None
    for pat in patterns:
        m = pat.search(html)
        if m:
            break
    if not m:
        return []
    data_raw = m.group(1)
    cleaned = _re.sub(r"\s+", " ", data_raw).replace("'", '"')
    try:
        arr = _json.loads(cleaned)
    except Exception:
        pairs = _re.findall(r"\[(\d{9,}),\s*(\d+(?:\.\d+)?)\]", data_raw)
        arr = [[int(ts), float(val)] for ts, val in pairs]

    out: List[Tuple[_dt.date, float]] = []
    for item in arr:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            ts_ms, val = item[0], item[1]
        elif isinstance(item, dict):
            ts_ms = item.get("x") or item.get("ts") or item.get("timestamp")
            val = item.get("y") or item.get("value")
        else:
            continue
        if ts_ms is None or val is None:
            continue
        try:
            d = _dt.datetime.utcfromtimestamp(int(ts_ms)/1000.0).date()
            out.append((d, float(val)))
        except Exception:
            continue
    out.sort(key=lambda x: x[0])
    return out


def _pick_value_for_year(series: List[Tuple[_dt.date, float]], year: int) -> Tuple[_dt.date, float, str]:
    if not series:
        raise ValueError("Serie vacía.")
    inside = [(d, v) for (d, v) in series if d.year == year]
    if inside:
        d, v = inside[-1]
        return d, v, "year_last_point"
    target = _dt.date(year, 6, 30)
    if target <= series[0][0]:
        return series[0][0], series[0][1], "nearest_start"
    if target >= series[-1][0]:
        return series[-1][0], series[-1][1], "nearest_end"
    lo, hi = 0, len(series) - 1
    while lo <= hi:
        mid = (lo + hi)//2
        if series[mid][0] < target:
            lo = mid + 1
        else:
            hi = mid - 1
    prev_dt, prev_val = series[hi]
    next_dt, next_val = series[lo]
    d_prev = abs((target - prev_dt).days)
    d_next = abs((next_dt - target).days)
    if d_prev == d_next and prev_dt != next_dt:
        total = (next_dt - prev_dt).days
        alpha = (target - prev_dt).days/total if total > 0 else 0.0
        interp = prev_val + alpha*(next_val - prev_val)
        return target, float(interp), "interpolated"
    return (prev_dt, prev_val, "nearest_prev") if d_prev < d_next else (next_dt, next_val, "nearest_next")


def get_team_value(team_name: str, year: int, debug: bool = False) -> Dict[str, Any]:
    """
    Obtiene el valor de mercado (M€) de un equipo para un AÑO (1995–2025),
    recibiendo el **nombre oficial del equipo** (no slug).

    - Resuelve el club por coincidencia exacta del nombre normalizado.
    - Intenta extraer la serie desde la **portada** del club.
    - Si no aparece, prueba URLs de historial conocidas (con y sin slug).
    - No itera sobre "candidatos"; falla si el nombre no coincide exactamente.

    Retorna:
        dict: team_resolved, team_id, year_requested, date_matched, value_eur_millions,
              method, club_home_url, series_source_url
    """
    if not isinstance(year, int) or year < 1995 or year > 2025:
        raise ValueError("El parámetro 'year' debe estar entre 1995 y 2025.")

    http = _Http(debug=debug)
    club = _resolve_club_by_official_name(team_name, http)

    # 1) Intentar extraer la serie desde la portada del club
    r = http.get(club.url)
    series = _parse_series_from_html(r.text)
    series_source_url = club.url

    # 2) Si falla, probar rutas alternativas conocidas (algunos clubs no exponen el gráfico en portada)
    if not series:
        alt_urls = [
            f"{_BASE}/{club.slug}/marktwertentwicklung/verein/{club.id}",
            f"{_BASE}/marktwertentwicklung/verein/{club.id}",  # sin slug
            f"{_BASE}/{club.slug}/historie/verein/{club.id}",  # por si cambian estructura
        ]
        for u in alt_urls:
            try:
                r2 = http.get(u)
                s2 = _parse_series_from_html(r2.text)
                if s2:
                    series = s2
                    series_source_url = u
                    break
            except Exception as e:
                if debug:
                    print(f"[DEBUG] alternativa fallida: {u} -> {e}")
                continue

    if not series:
        raise RuntimeError("No fue posible encontrar la serie histórica de valor para este club.")

    matched_date, value, method = _pick_value_for_year(series, year)
    return {
        "team_resolved": club.name,
        "team_id": club.id,
        "year_requested": year,
        "date_matched": matched_date.isoformat(),
        "value_eur_millions": float(value),
        "method": method,
        "club_home_url": club.url,
        "series_source_url": series_source_url,
    }


if __name__ == "__main__":
    tests = [
        ("FC Barcelona", 2005, True),
        ("Real Madrid CF", 2015, True),
        ("Manchester City FC", 2020, True),
        ("Club Atlético River Plate", 2010, True),
    ]
    for name, y, dbg in tests:
        try:
            out = get_team_value(name, y, debug=dbg)
            print(f"{name} @ {y} -> {out['value_eur_millions']} M€ "
                  f"(fecha {out['date_matched']} método={out['method']})  fuente: {out['series_source_url']}")
        except Exception as e:
            print(f"Error con {name} @ {y}: {e}")
