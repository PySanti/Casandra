# utils/get_match_result.py
from utils.Result import Result
import re
import time
import random
import unicodedata
from datetime import datetime
from typing import Optional, Dict, List, Iterable, Set
import requests

API_KEY = "123"
BASE = f"https://www.thesportsdb.com/api/v1/json/{API_KEY}"

# -----------------------
# Utilidades locales
# -----------------------
UA = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36",
]
def _headers():
    return {
        "User-Agent": random.choice(UA),
        "Accept-Language": "en-US,en;q=0.9,es;q=0.8",
        "Referer": "https://www.thesportsdb.com/",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }

def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c))

def _norm(s: str) -> str:
    """Normalización fuerte: minúsculas, sin acentos, solo alfanumérico."""
    s = _strip_accents(s or "").lower()
    return re.sub(r"[^a-z0-9]+", "", s)

def _tokens(s: str) -> List[str]:
    s = _strip_accents(s or "").lower()
    return re.findall(r"[a-z0-9]+", s)

_WORDS_TO_DROP: Set[str] = {
    "fc","cf","afc","sfc","cfc","sc","ac","ud","cd","rcd","ssc","sv","vfl","vfb","rb",
    "as","ss","club","football","futbol","fútbol","calcio","deportivo","athletic",
    "sporting","hotspur","queens","racing","association","city","united","town",
    "real","de","la","el","los","las","clubul","futebol","futbolu","athletico",
    "athlético","sociedad","athletik","fk","sk","nk","bk","if","us","sd","sad"
}
def _tokens_clean(s: str) -> List[str]:
    return [t for t in _tokens(s) if t not in _WORDS_TO_DROP]

def _alias_variants_from_name(team_name: str) -> List[str]:
    """
    Genera variantes robustas del nombre de equipo:
      - original
      - sin paréntesis
      - sin palabras genéricas (FC, CF, Club, de, la…)
      - últimas palabras (ciudad/nombre distintivo)
      - reemplazos comunes (Bayern München->Bayern Munich, Inter Milan->Inter, etc.)
    """
    base = (team_name or "").strip()
    out: List[str] = []
    if not base:
        return out

    out.append(base)
    no_par = re.sub(r"\s*\([^)]*\)\s*", " ", base).strip()
    if no_par and no_par != base:
        out.append(no_par)

    base2 = re.sub(r"\s+", " ", no_par).strip()
    out.append(base2)

    toks = _tokens(base2)
    toks_clean = [t for t in toks if t not in _WORDS_TO_DROP]
    if toks_clean:
        out.append(" ".join(toks_clean))
        out.append(toks_clean[-1])
        if len(toks_clean) >= 2:
            out.append(" ".join(toks_clean[-2:]))

    # reemplazos frecuentes
    rep = [
        (r"\bmunich\b", "munchen"),
        (r"\bköln\b", "koln"),
        (r"\bkoln\b", "koln"),
        (r"\bmönchengladbach\b", "monchengladbach"),
        (r"\bmonchengladbach\b", "monchengladbach"),
        (r"\bsaint[- ]germain\b", "psg"),
        (r"\bmanchester city\b", "man city"),
        (r"\bmanchester united\b", "man united"),
        (r"\binter milan\b", "inter"),
        (r"\bfc barcelona\b", "barcelona"),
        (r"\breal madrid cf\b", "real madrid"),
    ]
    for pat, repl in rep:
        v = re.sub(pat, repl, base2, flags=re.IGNORECASE)
        if v.lower() != base2.lower():
            out.append(v)

    # deduplicar
    seen = set()
    uniq: List[str] = []
    for v in out:
        v2 = re.sub(r"\s+", " ", (v or "")).strip()
        if not v2:
            continue
        k = v2.lower()
        if k in seen:
            continue
        seen.add(k)
        uniq.append(v2)
    return uniq

def slugify_team(name: str) -> str:
    """Slug corto (3 letras aprox) a partir de un nombre cualquiera."""
    clean = _strip_accents(name or "").lower()
    clean = re.sub(r"[^a-z0-9\s]", "", clean)
    tokens = re.findall(r"[a-z0-9]+", clean)
    IGN = _WORDS_TO_DROP
    initials = [t[0] for t in tokens if t not in IGN]
    if len(initials) >= 2:
        return ("".join(initials)[:3]).lower()
    letters = re.sub(r"[^a-z0-9]+", "", clean)
    return letters[:3].lower()

# -----------------------
# HTTP helper con backoff
# -----------------------
def _robust_get_json(url: str, max_retries=3, base_delay=1.1, debug=False) -> Optional[dict]:
    s = requests.Session()
    for i in range(max_retries):
        try:
            r = s.get(url, headers=_headers(), timeout=20)
            if debug:
                print(f"[TSDB] {r.status_code:3d}  {url}")
            if r.status_code in (429,) or (500 <= r.status_code < 600):
                wait = base_delay * (2**i) + random.uniform(0, 0.8)
                if debug: print(f"[backoff] {r.status_code} -> sleep {wait:.1f}s")
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if i == max_retries - 1:
                if debug: print(f"[TSDB][err] {e} @ {url}")
            else:
                wait = base_delay * (2**i) + random.uniform(0, 0.6)
                if debug: print(f"[retry] {e} -> sleep {wait:.1f}s")
                time.sleep(wait)
                continue
    return None

# -----------------------
# TheSportsDB helpers
# -----------------------
def _resolve_team_id_by_name(name: str, debug=False) -> Optional[str]:
    """
    Resuelve idTeam intentando varias variantes del nombre.
    Retorna idTeam (string) o None.
    """
    variants = _alias_variants_from_name(name)
    for v in variants:
        url = f"{BASE}/searchteams.php?t={requests.utils.quote(v)}"
        data = _robust_get_json(url, debug=debug)
        if not data or not data.get("teams"):
            continue
        # Preferimos Soccer
        best = None
        for t in data["teams"]:
            if (t.get("strSport") or "").lower() != "soccer":
                continue
            # match por normalización fuerte
            cand = t.get("strTeam") or ""
            if _norm(cand) == _norm(name) or _norm(cand) == _norm(v):
                best = t; break
            # si no exacto, acepta el primero de soccer
            if best is None:
                best = t
        if not best:
            continue
        idt = best.get("idTeam")
        if idt:
            if debug: print(f"[TSDB] Team: {best.get('strTeam')} -> id={idt}")
            return idt
    return None

def _events_by_day(date_iso: str, debug=False) -> List[dict]:
    url = f"{BASE}/eventsday.php?d={date_iso}&s=Soccer"
    data = _robust_get_json(url, debug=debug)
    if not data or not data.get("events"):
        return []
    return data["events"]

def _match_event_by_ids(id_home: str, id_away: str, events: List[dict]) -> Optional[dict]:
    for ev in events:
        if ev.get("idHomeTeam") == id_home and ev.get("idAwayTeam") == id_away:
            return ev
    return None

def _match_event_by_names(home_name: str, away_name: str, events: List[dict]) -> Optional[dict]:
    # Fallback por nombres normalizados si no se consiguieron ids
    hn = _norm(home_name)
    an = _norm(away_name)
    for ev in events:
        eh = _norm(ev.get("strHomeTeam") or "")
        ea = _norm(ev.get("strAwayTeam") or "")
        if eh == hn and ea == an:
            return ev
    return None

def _search_event_candidates(home_names: List[str], away_names: List[str], date_iso: str, debug=False):
    tried = set()
    for h in home_names:
        for a in away_names:
            for conj in ("vs", "v"):
                q = f"{h} {conj} {a}"
                if q in tried: 
                    continue
                tried.add(q)
                url = f"{BASE}/searchevents.php?e={requests.utils.quote(q)}"
                data = _robust_get_json(url, debug=debug)
                if not data or not data.get("event"):
                    continue
                for ev in data["event"]:
                    if (ev.get("strSport") or "").lower() != "soccer":
                        continue
                    if (ev.get("dateEvent") or "") != date_iso:
                        continue
                    yield ev

# -----------------------
# API pública
# -----------------------
def get_match_result(teams_str: str, fecha: str, liga_hint: Optional[str] = None,
                     search_window_days: int = 0, proxies: Optional[Dict] = None,
                     debug: bool = False) -> Optional[Result]:
    """
    Obtiene el resultado 'gH-gA' de un partido usando TheSportsDB.
    ENTRADA (cambiado): teams_str es 'NombreLocal-NombreVisitante' (no slugs).
      Ej: 'Sevilla-Barcelona', 'Real Madrid-Barcelona', 'PSG-Marseille'
    fecha: 'dd/mm/aa' (fecha del partido)
    Retorna utils.Result con slugs derivados automáticamente de los nombres.
    """
    # 1) Parseo fecha
    try:
        d = datetime.strptime(fecha, "%d/%m/%y")
    except ValueError:
        raise ValueError("La fecha debe ser dd/mm/aa (ej. '05/10/25').")
    date_iso = d.strftime("%Y-%m-%d")

    # 2) Parseo equipos (nombres)
    parts = [p for p in re.split(r"[-–—_\s]+", (teams_str or "").strip()) if p]
    if len(parts) < 2:
        raise ValueError("Formato inválido. Usa 'Local-Visitante', p.ej. 'Sevilla-Barcelona'.")

    home_name = parts[0].strip()
    away_name = parts[1].strip()

    # 3) Resolver idTeam de ambos (esto reduce ambigüedad y llamadas posteriores)
    id_home = _resolve_team_id_by_name(home_name, debug=debug)
    id_away = _resolve_team_id_by_name(away_name, debug=debug)

    # 4) Obtener eventos del día y filtrar
    ev = None
    events = _events_by_day(date_iso, debug=debug)
    if events:
        if id_home and id_away:
            ev = _match_event_by_ids(id_home, id_away, events)
        if not ev:
            ev = _match_event_by_names(home_name, away_name, events)

    # 5) Fallback a búsqueda por "Home vs Away" si aún no se encontró
    if not ev:
        home_vars = _alias_variants_from_name(home_name)
        away_vars = _alias_variants_from_name(away_name)
        for cand in _search_event_candidates(home_vars, away_vars, date_iso, debug=debug):
            ev = cand
            break

    if not ev:
        if debug:
            print("[TSDB] No se encontró evento para esa fecha/equipos.")
        return None

    # 6) Extraer marcador
    gH = ev.get("intHomeScore")
    gA = ev.get("intAwayScore")
    if gH is None or gA is None or str(gH) == "" or str(gA) == "":
        if debug:
            print("[TSDB] Evento encontrado, pero sin marcador disponible.")
        return None

    # 7) Slugs derivados de nombres
    home_slug = slugify_team(home_name)
    away_slug = slugify_team(away_name)

    return Result(home_slug, away_slug, str(gH), str(gA), d)
