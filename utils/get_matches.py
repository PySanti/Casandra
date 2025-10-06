import re
import unicodedata
from datetime import datetime
from typing import List, Tuple
import requests
from bs4 import BeautifulSoup, Comment

# ---------- Utils ----------
def _slugify_team(name: str) -> str:
    norm = unicodedata.normalize("NFKD", name or "")
    cleaned = "".join(c for c in norm if not unicodedata.combining(c)).lower()
    cleaned = re.sub(r"[\s\.\-’'`]+", "", cleaned)
    aliases = {
        "realmadrid":"rma","fcbarcelona":"bar","barcelona":"bar","sevilla":"sev",
        "atleticodemadrid":"atm","atleticomadrid":"atm","valencia":"val","villarreal":"vil",
        "realbetis":"bet","girona":"gir","getafe":"get","realsociedad":"soc",
        "athleticbilbao":"ath","osasuna":"osa","celtavigo":"cel","rayovallecano":"ray",
        "manchesterunited":"mun","manchestercity":"mci","chelsea":"che","liverpool":"liv",
        "arsenal":"ars","tottenhamhotspur":"tot","newcastleunited":"new",
        "juventus":"juv","internazionale":"int","inter":"int","acmilan":"mil","milan":"mil",
        "napoli":"nap","roma":"rom","lazio":"laz","atalanta":"ata","fiorentina":"fio",
        "bayernmunchen":"bay","bayernmunich":"bay","borussiadortmund":"bvb",
        "rbleipzig":"rbl","bayerleverkusen":"lev","borussiamgladbach":"bmg",
        "parissaintgermain":"psg","psg":"psg","olympiquemarseille":"om","olympiquelyonnais":"lyo",
        "monaco":"mon","lille":"lil","nice":"nic",
    }
    return aliases.get(cleaned, cleaned[:3] if len(cleaned) >= 3 else cleaned)

def _pick_parser():
    try:
        import lxml  # noqa
        return "lxml"
    except Exception:
        return "html.parser"

def _headers():
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept-Language": "en-US,en;q=0.9,es;q=0.8",
        "Referer": "https://google.com",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }

# ---------- Fuente 1: FBref ----------
def _from_fbref(liga: str, temporada: int, jornada: int, debug=False) -> List[Tuple[str, str]]:
    comp_id_map = {
        "laliga": ("12", "La-Liga"),
        "premier": ("9", "Premier-League"),
        "seriea": ("11", "Serie-A"),
        "bundesliga": ("20", "Bundesliga"),
        "ligue1": ("13", "Ligue-1"),
    }
    comp_id, comp_slug = comp_id_map[liga]
    season_slug = f"{temporada}-{temporada+1}"
    url = f"https://fbref.com/en/comps/{comp_id}/{season_slug}/schedule/{season_slug}-{comp_slug}-Scores-and-Fixtures"

    resp = requests.get(url, headers=_headers(), timeout=30)
    if debug: print(f"[FBref] GET {resp.status_code} {url}")
    resp.raise_for_status()

    parser = _pick_parser()
    soup = BeautifulSoup(resp.text, parser)

    def _find_rows(s: BeautifulSoup):
        rows = []
        for table in s.select("table"):
            for tr in table.select("tbody tr"):
                # debe tener equipos y fecha
                has_home = tr.find(attrs={"data-stat": "home_team"}) is not None
                has_away = tr.find(attrs={"data-stat": "away_team"}) is not None
                has_date = tr.find(attrs={"data-stat": "date"}) is not None
                if has_home and has_away and has_date:
                    rows.append(tr)
        return rows

    rows = _find_rows(soup)

    # Descomentar tablas si no hay filas visibles
    if not rows:
        if debug: print("[FBref] No rows in DOM, scanning HTML comments…")
        for c in soup.find_all(string=lambda t: isinstance(t, Comment)):
            if "<table" in c and ("data-stat" in c or "Scores and Fixtures" in c):
                subsoup = BeautifulSoup(c, parser)
                test = _find_rows(subsoup)
                if test:
                    rows = test
                    soup = subsoup
                    break

    if not rows:
        if debug: print("[FBref] Still no rows.")
        return []

    def _extract_matchweek(tr):
        # Busca jornada en varias llaves y en td o th
        for key in ("round", "week", "gameweek", "wk"):
            cell = tr.find("td", {"data-stat": key}) or tr.find("th", {"data-stat": key})
            if cell:
                m = re.search(r"(\d+)", cell.get_text(" ", strip=True))
                if m:
                    return int(m.group(1))
        # fallback: a veces aparece en notes: "Matchweek 6", "Week 6"
        notes = tr.find(attrs={"data-stat": "notes"})
        if notes:
            m = re.search(r"(?:Matchweek|Week|Jornada)\s*(\d+)", notes.get_text(" ", strip=True), flags=re.I)
            if m:
                return int(m.group(1))
        return None

    out: List[Tuple[str, str]] = []
    for tr in rows:
        mw = _extract_matchweek(tr)
        if mw != jornada:
            continue

        home_td = tr.find(attrs={"data-stat": "home_team"})
        away_td = tr.find(attrs={"data-stat": "away_team"})
        date_td = tr.find(attrs={"data-stat": "date"})
        if not (home_td and away_td and date_td):
            continue

        home_name = home_td.get_text(strip=True)
        away_name = away_td.get_text(strip=True)
        raw_date = date_td.get_text(strip=True)[:10]  # YYYY-MM-DD en FBref

        # Parseo de fecha robusto (algunas filas pueden no tener fecha aún → se omiten)
        dt = None
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y"):
            try:
                dt = datetime.strptime(raw_date, fmt)
                break
            except Exception:
                pass
        if not dt:
            continue

        out.append((f"{_slugify_team(home_name)}-{_slugify_team(away_name)}", dt.strftime("%d/%m/%y")))

    if debug: print(f"[FBref] Found {len(out)} matches for MW {jornada}")
    return out

# ---------- Fuente 2: worldfootball (respaldo) ----------
def _from_worldfootball(liga: str, temporada: int, jornada: int, debug=False) -> List[Tuple[str, str]]:
    comp_map = {
        "laliga": "esp-primera-division",
        "premier": "eng-premier-league",
        "seriea": "ita-serie-a",
        "bundesliga": "bundesliga",
        "ligue1": "fra-ligue-1",
    }
    comp = comp_map[liga]
    season_str = f"{temporada}-{temporada+1}"
    url = f"https://www.worldfootball.net/schedule/{comp}-{season_str}-spieltag/{jornada}/"

    headers = _headers()
    headers.update({
        "Referer": f"https://www.worldfootball.net/all_matches/{comp}-{season_str}/",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Upgrade-Insecure-Requests": "1",
    })

    resp = requests.get(url, headers=headers, timeout=30)
    if debug: print(f"[WFootball] GET {resp.status_code} {url}")
    if resp.status_code == 403:
        if debug: print("[WFootball] 403 Forbidden (bloqueo).")
        return []
    resp.raise_for_status()

    parser = _pick_parser()
    soup = BeautifulSoup(resp.text, parser)
    tables = soup.select("table.standard_tabelle")
    if not tables:
        if debug: print("[WFootball] No tables.")
        return []

    out: List[Tuple[str, str]] = []
    for table in tables:
        print(tables)
        for tr in table.select("tr"):
            tds = tr.find_all("td")
            if len(tds) < 3:
                continue

            team_links = tr.select("td a[href*='/teams/']")
            if len(team_links) >= 2:
                home_name = team_links[0].get_text(strip=True)
                away_name = team_links[1].get_text(strip=True)
            else:
                text = " ".join(td.get_text(" ", strip=True) for td in tds)
                if " - " not in text:
                    continue
                parts = re.split(r"\s-\s", text)
                if len(parts) < 2:
                    continue
                home_name = parts[0].strip()
                away_name = parts[1].strip().split(" ")[0]

            # fecha
            raw_date = None
            for cand in tds[:2]:
                txt = cand.get_text(" ", strip=True)
                m = re.search(r"\d{1,2}[\/\.\-]\d{1,2}[\/\.\-]\d{2,4}", txt)
                if m:
                    raw_date = m.group(0)
                    break
            if not raw_date:
                continue

            date_norm = raw_date.replace(".", "/").replace("-", "/")
            fmt = "%d/%m/%Y" if re.search(r"/\d{4}$", date_norm) else "%d/%m/%y"
            try:
                dt = datetime.strptime(date_norm, fmt)
            except Exception:
                continue

            out.append((f"{_slugify_team(home_name)}-{_slugify_team(away_name)}", dt.strftime("%d/%m/%y")))

    if debug: print(f"[WFootball] Found {len(out)} matches for MW {jornada}")
    return out

# ---------- API pública ----------
def get_matches_list(liga: str, temporada: int, jornada: int, debug: bool=False) -> List[Tuple[str, str]]:
    """
    Devuelve [(slug_partido, 'dd/mm/aa'), ...] para:
      liga: 'laliga'|'premier'|'seriea'|'bundesliga'|'ligue1'
      temporada: año de inicio (1994..2025)
      jornada: número de jornada (>=1)
    """
    key = (liga or "").strip().lower()
    if key not in {"laliga","premier","seriea","bundesliga","ligue1"}:
        raise ValueError("Liga no soportada. Usa: laliga, premier, seriea, bundesliga, ligue1.")
    if not isinstance(temporada, int) or temporada < 1994 or temporada > 2025:
        raise ValueError("Temporada fuera de rango. Usa año de inicio 1994..2025.")
    if not isinstance(jornada, int) or jornada < 1:
        raise ValueError("La jornada debe ser un entero >= 1.")

    # 1) FBref (primario)
    try:
        res = _from_fbref(key, temporada, jornada, debug=debug)
        if res:
            return res
    except:
        # 2) worldfootball (respaldo; puede devolver [] si hay 403)
        return _from_worldfootball(key, temporada, jornada, debug=debug)
