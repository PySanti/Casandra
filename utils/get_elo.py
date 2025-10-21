# utils/get_elo.py
import csv
import io
import re
import time
import random
from datetime import datetime, timedelta
from typing import List, Tuple, Optional, Iterable, Dict, Set
import unicodedata
import requests

# ---------- Config ----------
UA = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36",
]
def _headers():
    return {
        "User-Agent": random.choice(UA),
        "Accept-Language": "en-US,en;q=0.9,es;q=0.8",
        "Referer": "https://clubelo.com/",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }

# ---------- Normalización ----------
_WORDS_TO_DROP: Set[str] = {
    # genéricos multi-idioma
    "fc","cf","afc","sfc","cfc","sc","ac","ud","cd","rcd","ssc","sv","vfl","vfb","rb",
    "as","ss","club","football","futbol","fútbol","calcio","deportivo","athletic",
    "sporting","hotspur","queens","racing","association","city","united","town",
    "real","de","la","el","los","las","clubul","futebol","futbolu","athletico",
    "athlético","sociedad","athletik","fk","sk","nk","bk","if","us","sd","sad"
}

def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c))

def _norm(s: str) -> str:
    """Normalización fuerte: sin acentos, minúsculas, solo alfanumérico."""
    s = _strip_accents(s or "").lower()
    return re.sub(r"[^a-z0-9]+", "", s)

def _tokens(s: str) -> List[str]:
    """Tokens alfanuméricos sin acentos y en minúscula."""
    s = _strip_accents(s or "").lower()
    return re.findall(r"[a-z0-9]+", s)

def _tokens_clean(s: str) -> List[str]:
    """Tokens eliminando palabras genéricas."""
    toks = _tokens(s)
    return [t for t in toks if t not in _WORDS_TO_DROP]

def _token_set(s: str) -> Set[str]:
    return set(_tokens_clean(s))

def _jaccard(a: Iterable[str], b: Iterable[str]) -> float:
    A, B = set(a), set(b)
    if not A and not B:
        return 0.0
    inter = len(A & B)
    union = len(A | B)
    return inter / union if union else 0.0

# --- Alias heurísticos desde nombre libre ---
def _alias_variants_from_name(team_name: str) -> List[str]:
    """
    Genera variantes útiles del nombre recibido:
    - original
    - sin paréntesis, colapsar espacios
    - tokens con/sin genéricos
    - últimas DOS palabras (evitar la última sola)
    - algunos reemplazos frecuentes
    """
    base = (team_name or "").strip()
    out: List[str] = []
    if not base:
        return out

    # 1) original
    out.append(base)

    # 2) sin paréntesis
    no_par = re.sub(r"\s*\([^)]*\)\s*", " ", base).strip()
    if no_par and no_par != base:
        out.append(no_par)

    # 3) colapsar espacios
    base2 = re.sub(r"\s+", " ", no_par).strip()
    out.append(base2)

    # 4) variantes tokenizadas
    toks = _tokens(base2)
    toks_clean = [t for t in toks if t not in _WORDS_TO_DROP]
    if toks_clean:
        out.append(" ".join(toks_clean))

    out.append(" ".join(_tokens(base2)))   # solo tokens simples
    out.append(" ".join(toks_clean))       # sin genéricos (dedupe abajo)

    # 5) últimas DOS palabras (no una) para evitar colisiones por un único token
    if len(toks_clean) >= 2:
        out.append(" ".join(toks_clean[-4:]))

    # 6) reemplazos frecuentes
    rep = [
        (r"\bmunich\b", "munchen"),
        (r"\bkoln\b", "koln"),
        (r"\bköln\b", "koln"),
        (r"\bmonchengladbach\b", "monchengladbach"),
        (r"\bmönchengladbach\b", "monchengladbach"),
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

    # deduplicar preservando orden
    seen = set()
    uniq: List[str] = []
    for v in out:
        v2 = re.sub(r"\s+", " ", v).strip()
        if not v2:
            continue
        key = v2.lower()
        if key in seen:
            continue
        seen.add(key)
        uniq.append(v2)
    return uniq

# ---------- HTTP robusto con backoff ----------
def _robust_get(url: str, max_retries=5, base_delay=1.2, debug=False) -> requests.Response:
    s = requests.Session()
    for i in range(max_retries):
        r = s.get(url, headers=_headers(), timeout=25)
        if debug:
            print(f"[ClubElo] GET {r.status_code} {url}")
        if r.status_code == 429:
            ra = r.headers.get("Retry-After")
            if ra and ra.isdigit():
                wait = int(ra)
            else:
                wait = base_delay * (2 ** i) + random.uniform(0, 0.8)
            if debug: print(f"[backoff] 429 -> sleep {wait:.1f}s")
            time.sleep(wait)
            continue
        if 500 <= r.status_code < 600:
            wait = base_delay * (2 ** i) + random.uniform(0, 0.8)
            if debug: print(f"[backoff] {r.status_code} -> sleep {wait:.1f}s")
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r
    raise RuntimeError(f"Max retries alcanzado para {url}")

# ---------- CSV helpers ----------
def _parse_csv(text: str) -> List[dict]:
    f = io.StringIO(text)
    reader = csv.DictReader(f)
    rows = []
    for row in reader:
        rows.append({(k or "").strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()})
    return rows

def _extract_elo(row: dict) -> Optional[float]:
    for key in ("Elo", "elo", "EloRating", "Elo rating"):
        if key in row and row[key] not in (None, ""):
            try:
                return float(row[key])
            except Exception:
                pass
    return None

def _row_club_name(row: dict) -> Optional[str]:
    for k in ("Club", "club", "Team", "team"):
        if k in row and row[k]:
            return row[k]
    return None

# ---------- Matching ----------
def _best_row_for_team(rows: List[dict], name_variants: List[str], debug: bool=False) -> Optional[dict]:
    """
    Coincidencia estricta para evitar falsos positivos:
      1) exacto por _norm
      2) v_tok ⊆ c_tok (subconjunto de tokens)
      3) prefijo/sufijo SOLO si ambos tienen ≥2 tokens y v_tok ⊆ c_tok
      4) Jaccard >= 0.67 y |intersección| >= 2
    (No hay fallback 'mejor>=0.5')
    """
    if not rows or not name_variants:
        return None

    # Preprocesar filas
    clubs: List[Tuple[dict, str, str, Set[str]]] = []  # (row, club_raw, club_norm, club_tokset)
    for r in rows:
        c = _row_club_name(r)
        if not c:
            continue
        club_norm = _norm(c)
        club_tok = _token_set(c)
        clubs.append((r, c, club_norm, club_tok))

    # Precompute variants normalized/tokens
    variants_norm = [(_norm(v), _token_set(v), v) for v in name_variants if v]

    # 1) Exacto por _norm
    for r, c, c_norm, _ in clubs:
        for vn, _, _orig in variants_norm:
            if c_norm and vn and c_norm == vn:
                if debug: print(f"[match-exact] '{c}' == '{_orig}'")
                return r

    # 2) Subconjunto de tokens: todos los tokens del query están en el club
    subset_candidates: List[Tuple[int, dict]] = []  # (len(c_tok), row) para preferir club con más detalle
    for r, c, _, c_tok in clubs:
        for _, v_tok, _orig in variants_norm:
            if v_tok and v_tok.issubset(c_tok):
                subset_candidates.append((len(c_tok), r))
                if debug: print(f"[match-subset] '{c}' ⊇ query_tokens")
                break
    if subset_candidates:
        subset_candidates.sort(key=lambda t: t[0], reverse=True)  # preferir el más específico
        return subset_candidates[0][1]

    # 3) Prefijo/sufijo PERO solo si ambos tienen ≥2 tokens y v_tok ⊆ c_tok
    for r, c, c_norm, c_tok in clubs:
        if len(c_tok) < 2:
            continue
        for vn, v_tok, _orig in variants_norm:
            if len(v_tok) < 2 or not c_norm or not vn:
                continue
            if v_tok.issubset(c_tok) and (c_norm.startswith(vn) or vn.startswith(c_norm)):
                if debug: print(f"[match-prefix-subset] '{c}' ~ subset+prefix")
                return r

    # 4) Jaccard robusto: requiere bastante solapamiento de tokens
    for r, c, _, c_tok in clubs:
        for _, v_tok, _orig in variants_norm:
            inter = len(c_tok & v_tok)
            score = _jaccard(c_tok, v_tok)
            if inter >= 2 and score >= 0.67:
                if debug: print(f"[match-jaccard>=0.67 & inter>=2] '{c}' -> {score:.2f}")
                return r

    # Sin match estricto -> None
    if debug:
        print("[no-match] Rechazado para evitar falsos positivos.")
    return None

# ---------- API principal ----------
def get_team_elo(team_name: str, fecha: str, back_days: int = 3, debug: bool=False) -> Optional[Tuple[int, int]]:
    """
    Devuelve (ranking, elo) del equipo (por NOMBRE) en la fecha dada 'dd/mm/aa'.
    Usa matching estricto para no confundir equipos diferentes que comparten una palabra.
    """
    # 1) Fecha -> YYYY-MM-DD
    try:
        d = datetime.strptime(fecha, "%d/%m/%y")
    except ValueError:
        raise ValueError("La fecha debe ser dd/mm/aa, ej. '28/09/25'.")

    # 2) Variantes de nombre
    variants = _alias_variants_from_name(team_name)
    if debug:
        print(f"[ELO] Variantes '{team_name}': {variants[:6]}{' ...' if len(variants)>6 else ''}")
    if not variants:
        return None

    # 3) Buscar día exacto y hacia atrás
    for delta in range(0, back_days + 1):
        day = d - timedelta(days=delta)
        day_str = day.strftime("%Y-%m-%d")
        url = f"http://api.clubelo.com/{day_str}"

        try:
            resp = _robust_get(url, debug=debug)
        except Exception as e:
            if debug: print(f"[error] {e}")
            continue

        rows = _parse_csv(resp.text)
        if not rows:
            continue

        # conservar solo filas con Elo válido
        scored = []
        for r in rows:
            elo = _extract_elo(r)
            if elo is None:
                continue
            scored.append((elo, r))
        if not scored:
            continue

        # ranking por Elo descendente
        scored.sort(key=lambda t: t[0], reverse=True)
        rank_map: Dict[str, int] = {}
        flat_rows: List[dict] = []
        for idx, (elo_val, r) in enumerate(scored, start=1):
            club = _row_club_name(r)
            if club:
                rank_map[_norm(club)] = idx
            flat_rows.append(r)

        # matching robusto (estricto)
        row = _best_row_for_team(flat_rows, variants, debug=debug)
        if row:
            elo_val = _extract_elo(row)
            club_name = _row_club_name(row) or team_name
            rank = rank_map.get(_norm(club_name))
            if elo_val is not None and rank is not None:
                if debug:
                    print(f"[FOUND] {club_name} @ {day_str} -> rank={rank}, elo={int(round(elo_val))}")
                return (rank, int(round(elo_val)))

        if debug:
            print(f"[miss] '{team_name}' no encontrado en {day_str}, sigo {delta+1}/{back_days}…")

    if debug:
        print("No se encontró Elo/ranking para ese equipo en la ventana indicada.")
    return None
