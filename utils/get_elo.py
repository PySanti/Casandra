# utils/get_team_elo.py
import csv
import io
import re
import time
import random
from datetime import datetime, timedelta
from typing import List, Tuple, Optional
import unicodedata
import requests

# ---------- Config ----------
UA = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36",
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
def _norm(s: str) -> str:
    if not s:
        return ""
    norm = unicodedata.normalize("NFKD", s)
    norm = "".join(c for c in norm if not unicodedata.combining(c))
    norm = norm.lower()
    norm = re.sub(r"[^a-z0-9]+", "", norm)
    return norm

# Mapa slug -> candidatos de nombre tal y como suelen aparecer en ClubElo
TEAM_NAME_CANDIDATES = {
    # España
    "bar": ["Barcelona", "FC Barcelona"],
    "rma": ["Real Madrid"],
    "atm": ["Atletico Madrid", "Atlético Madrid", "Atl Madrid"],
    "sev": ["Sevilla"],
    "soc": ["Real Sociedad"],
    "ath": ["Athletic Bilbao", "Athletic Club"],
    "bet": ["Real Betis"],
    "vil": ["Villarreal"],
    "val": ["Valencia"],
    "cel": ["Celta Vigo", "Celta de Vigo"],
    "ray": ["Rayo Vallecano"],
    "gir": ["Girona"],
    "get": ["Getafe"],
    "mlr": ["Mallorca", "RCD Mallorca"],
    "lpa": ["Las Palmas", "UD Las Palmas"],
    "ala": ["Alaves", "Deportivo Alaves", "Alavés", "Deportivo Alavés"],
    "gra": ["Granada"],
    "cad": ["Cadiz", "Cádiz"],
    "leg": ["Leganes", "Leganés"],
    "osa": ["Osasuna", "CA Osasuna"],
    "rvad": ["Real Valladolid", "Valladolid"],
    "spo": ["Sporting Gijon", "Sporting de Gijon", "Sporting de Gijón"],
    # Inglaterra
    "mci": ["Man City", "Manchester City"],
    "mun": ["Man United", "Manchester United"],
    "liv": ["Liverpool"],
    "ars": ["Arsenal"],
    "che": ["Chelsea"],
    "tot": ["Tottenham", "Tottenham Hotspur"],
    "new": ["Newcastle", "Newcastle United"],
    "whu": ["West Ham", "West Ham United"],
    "avl": ["Aston Villa"],
    "eve": ["Everton"],
    "lei": ["Leicester", "Leicester City"],
    "bha": ["Brighton", "Brighton & Hove Albion"],
    "bre": ["Brentford"],
    "bou": ["Bournemouth"],
    "cry": ["Crystal Palace"],
    "ful": ["Fulham"],
    "wol": ["Wolves", "Wolverhampton", "Wolverhampton Wanderers"],
    "for": ["Nottingham Forest"],
    "ips": ["Ipswich", "Ipswich Town"],
    "sou": ["Southampton"],
    "shu": ["Sheffield United"],
    "bur": ["Burnley"],
    # Italia
    "juv": ["Juventus"],
    "int": ["Inter", "Internazionale", "Inter Milan"],
    "mil": ["AC Milan", "Milan"],
    "nap": ["Napoli"],
    "rom": ["Roma", "AS Roma"],
    "laz": ["Lazio", "SS Lazio"],
    "ata": ["Atalanta"],
    "fio": ["Fiorentina"],
    "tor": ["Torino"],
    "bol": ["Bologna"],
    "gen": ["Genoa"],
    "sam": ["Sampdoria"],
    "cag": ["Cagliari"],
    "emp": ["Empoli"],
    "udi": ["Udinese"],
    "mon": ["Monza", "AS Monaco"],  # ojo: 'mon' puede colisionar con Monaco (FRA); si es francés usa 'ligue1'
    "lec": ["Lecce"],
    "sas": ["Sassuolo"],
    # Alemania
    "bay": ["Bayern", "Bayern Munchen", "Bayern München"],
    "bvb": ["Borussia Dortmund", "Dortmund"],
    "rbl": ["RB Leipzig"],
    "lev": ["Bayer Leverkusen"],
    "bmg": ["Borussia Monchengladbach", "Borussia Mönchengladbach", "Monchengladbach", "Mönchengladbach"],
    "vfb": ["VfB Stuttgart", "Stuttgart"],
    "wob": ["Wolfsburg", "VfL Wolfsburg"],
    "sge": ["Eintracht Frankfurt", "Frankfurt"],
    "scf": ["SC Freiburg", "Freiburg"],
    "svw": ["Werder Bremen", "Bremen"],
    "uni": ["Union Berlin", "1. FC Union Berlin"],
    "fca": ["Augsburg"],
    "fck": ["Koln", "Köln", "1. FC Koln", "1. FC Köln", "FC Koln", "FC Köln"],
    # Francia
    "psg": ["Paris SG", "Paris Saint-Germain", "PSG"],
    "om":  ["Marseille", "Olympique Marseille", "Olympique de Marseille"],
    "lyo": ["Lyon", "Olympique Lyonnais"],
    "lil": ["Lille", "LOSC Lille"],
    "nic": ["Nice", "OGC Nice"],
    "ren": ["Rennes", "Stade Rennais"],
    "nan": ["Nantes"],
    "monp":["Montpellier", "Montpellier HSC"],
    "gir": ["Bordeaux", "Girondins Bordeaux", "Girondins de Bordeaux"],
    "rcl": ["Lens", "RC Lens"],
    "rcs": ["Strasbourg", "RC Strasbourg"],
    "tou": ["Toulouse"],
    "rei": ["Reims", "Stade de Reims"],
}

# ---------- HTTP robusto con backoff ----------
def _robust_get(url: str, max_retries=5, base_delay=1.5, debug=False) -> requests.Response:
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

# ---------- Núcleo ----------
def _candidates_for_slug(slug: str) -> List[str]:
    s = slug.strip().lower()
    return TEAM_NAME_CANDIDATES.get(s, [])

def _parse_csv(text: str) -> List[dict]:
    # ClubElo API devuelve CSV en texto plano
    f = io.StringIO(text)
    reader = csv.DictReader(f)
    rows = []
    for row in reader:
        # normalizar claves posibles
        row_norm = {k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()}
        rows.append(row_norm)
    return rows

def _find_row_for_team(rows: List[dict], candidates: List[str]) -> Optional[dict]:
    cand_norm = {_norm(c) for c in candidates}
    for r in rows:
        club = r.get("Club") or r.get("club") or r.get("Team") or r.get("team")
        if not club:
            continue
        if _norm(club) in cand_norm:
            return r
    return None

def _extract_elo(row: dict) -> Optional[float]:
    for key in ("Elo", "elo", "EloRating", "Elo rating"):
        if key in row:
            val = row[key]
            try:
                return float(val)
            except Exception:
                pass
    return None

def get_team_elo(slug_equipo: str, fecha: str, back_days: int = 3, debug: bool=False) -> Optional[Tuple[int, int]]:
    """
    Devuelve (ranking, elo) del equipo (slug) en la fecha dada (dd/mm/aa).
    Si el club no aparece exactamente ese día, busca hacia atrás hasta `back_days`.
    Retorna None si no se encuentra.
    """
    # 1) Fecha -> YYYY-MM-DD
    try:
        d = datetime.strptime(fecha, "%d/%m/%y")
    except ValueError:
        raise ValueError("La fecha debe ser dd/mm/aa, ej. '28/09/25'.")

    candidates = _candidates_for_slug(slug_equipo)
    if not candidates:
        if debug:
            print(f"[WARN] No hay candidatos de nombre para slug '{slug_equipo}'. Amplía TEAM_NAME_CANDIDATES.")
        return None

    # 2) Intentar día exacto y hacia atrás
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

        # Convertir a floats y ordenar por Elo desc para calcular ranking
        scored = []
        for r in rows:
            elo = _extract_elo(r)
            if elo is None:
                continue
            scored.append((elo, r))
        if not scored:
            continue

        scored.sort(key=lambda t: t[0], reverse=True)  # Elo desc
        # Build ranking map: club -> rank
        rank_map = {}
        for idx, (_, r) in enumerate(scored, start=1):
            club = r.get("Club") or r.get("club") or r.get("Team") or r.get("team")
            if club:
                rank_map[_norm(club)] = idx

        # Buscar el club entre los candidatos
        row = _find_row_for_team([r for _, r in scored], candidates)
        if row:
            elo_val = _extract_elo(row)
            club_name = row.get("Club") or row.get("club") or row.get("Team") or row.get("team")
            rank = rank_map.get(_norm(club_name))
            if elo_val is not None and rank is not None:
                if debug:
                    print(f"[FOUND] {club_name} @ {day_str} -> rank={rank}, elo={int(round(elo_val))}")
                return (rank, int(round(elo_val)))

        if debug:
            print(f"[miss] {slug_equipo} no encontrado en {day_str}, sigo buscando...")

    if debug:
        print("No se encontró Elo/ranking para ese equipo en la ventana indicada.")
    return None

