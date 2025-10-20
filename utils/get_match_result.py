
# utils/get_match_result.py
from utils.Result import Result
import re
import unicodedata
from datetime import datetime
from typing import Optional, Dict, List
import requests

API_KEY = "123"
BASE = f"https://www.thesportsdb.com/api/v1/json/{API_KEY}"

# -----------------------
# Utilidades locales
# -----------------------
def _normalize(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[\s\.\-’'`_]+", "", s)

def slugify_team(name: str) -> str:
    cleaned = _normalize(name)
    aliases = {
        # España
        "realmadrid":"rma","fcbarcelona":"bar","barcelona":"bar","sevilla":"sev",
        "atleticodemadrid":"atm","atleticomadrid":"atm","valencia":"val","villarreal":"vil",
        "realbetis":"bet","girona":"gir","getafe":"get","realsociedad":"soc",
        "athleticclub":"ath","athleticbilbao":"ath","osasuna":"osa",
        "celtadevigo":"cel","celtavigo":"cel","rayovallecano":"ray","udlaspalmas":"lpa",
        "alaves":"ala","deportivoalaves":"ala","granadacf":"gra","realvalladolid":"rvad",
        "rcdmallorca":"mlr","cadiz":"cad","leganes":"leg","sportingdegijon":"spo","sportinggijon":"spo",
        # Inglaterra
        "manchesterunited":"mun","manchestercity":"mci","chelsea":"che","liverpool":"liv",
        "arsenal":"ars","tottenhamhotspur":"tot","newcastleunited":"new","westhamunited":"whu",
        "astonvilla":"avl","everton":"eve","leicestercity":"lei","brightonandhovealbion":"bha",
        "brentford":"bre","bournemouth":"bou","crystalpalace":"cry","fulham":"ful","wolverhamptonwanderers":"wol",
        "nottinghamforest":"for","ipswichtown":"ips","southampton":"sou",
        # Italia
        "juventus":"juv","internazionale":"int","inter":"int","acmilan":"mil","milan":"mil",
        "napoli":"nap","asroma":"rom","roma":"rom","sslazio":"laz","lazio":"laz",
        "atalanta":"ata","fiorentina":"fio","torino":"tor","bologna":"bol","genoa":"gen",
        "sampdoria":"sam","cagliari":"cag","empoli":"emp","udinese":"udi","monza":"mon","lecce":"lec","sassuolo":"sas",
        # Alemania
        "bayernmunchen":"bay","bayernmunich":"bay","borussiadortmund":"bvb","rbleipzig":"rbl",
        "bayerleverkusen":"lev","borussiamonchengladbach":"bmg","borussiamönchengladbach":"bmg",
        "vfbstuttgart":"vfb","vflwolfsburg":"wob","eintrachtfrankfurt":"sge","freiburg":"scf",
        "werderbremen":"svw","unionberlin":"uni","fcunionberlin":"uni","augsburg":"fca","koln":"fck","1fckoln":"fck",
        # Francia
        "parissaintgermain":"psg","psg":"psg","olympiquemarseille":"om","olympiquelyonnais":"lyo",
        "monaco":"mon","lille":"lil","nice":"nic","rennes":"ren","nantes":"nan","montpellier":"monp",
        "bordeaux":"gir","lens":"rcl","strasbourg":"rcs","toulouse":"tou","reims":"rei",
    }
    return aliases.get(cleaned, cleaned[:3] if len(cleaned) >= 3 else cleaned)

# Nombre "canónico" para buscar en TheSportsDB a partir de tu slug
NAME_BY_SLUG: Dict[str, List[str]] = {
    # España
    "bar": ["FC Barcelona", "Barcelona"],
    "rma": ["Real Madrid"],
    "sev": ["Sevilla", "Sevilla FC"],
    "atm": ["Atlético de Madrid", "Atletico Madrid"],
    "soc": ["Real Sociedad"],
    "ath": ["Athletic Club", "Athletic Bilbao"],
    "val": ["Valencia"],
    "vil": ["Villarreal"],
    "bet": ["Real Betis", "Betis"],
    "gir": ["Girona"],
    "get": ["Getafe"],
    "osa": ["Osasuna"],
    "cel": ["Celta Vigo", "Celta de Vigo"],
    "ray": ["Rayo Vallecano"],
    "lpa": ["Las Palmas"],
    "ala": ["Alavés", "Deportivo Alaves"],
    "mlr": ["Mallorca"],
    "cad": ["Cádiz", "Cadiz"],
    "leg": ["Leganes"],
    # Inglaterra (algunos)
    "liv": ["Liverpool"],
    "mci": ["Manchester City"],
    "mun": ["Manchester United"],
    "che": ["Chelsea"],
    "ars": ["Arsenal"],
    "tot": ["Tottenham", "Tottenham Hotspur"],
    # Italia (algunos)
    "juv": ["Juventus"],
    "int": ["Inter", "Internazionale"],
    "mil": ["AC Milan", "Milan"],
    "nap": ["Napoli"],
    "rom": ["Roma", "AS Roma"],
    "laz": ["Lazio"],
    # Alemania (algunos)
    "bay": ["Bayern Munich", "Bayern München", "FC Bayern"],
    "bvb": ["Borussia Dortmund"],
    # Francia (algunos)
    "psg": ["Paris Saint-Germain", "PSG"],
    "om":  ["Marseille", "Olympique Marseille"],
}

def _pick_name_for_slug(slug: str) -> List[str]:
    # Devuelve lista de nombres posibles para buscar
    if slug in NAME_BY_SLUG:
        return NAME_BY_SLUG[slug]
    # heurística fallback: capitaliza
    return [slug]

# -----------------------
# TheSportsDB helpers
# -----------------------
def _get_json(url: str, debug=False) -> Optional[dict]:
    try:
        r = requests.get(url, timeout=12)
        if debug:
            print(f"[TheSportsDB] GET {r.status_code} {url}")
        r.raise_for_status()
        return r.json()
    except Exception as e:
        if debug:
            print(f"[TheSportsDB] error: {e}")
        return None

def _search_event_candidates(home_names: List[str], away_names: List[str], date_iso: str, debug=False):
    """
    Intenta searchevents.php con distintas combinaciones de 'Home vs Away' y 'Away vs Home'.
    Filtra por fecha exacta (dateEvent == date_iso).
    """
    tried = set()
    for h in home_names:
        for a in away_names:
            for conj in ("vs", "v"):
                q = f"{h} {conj} {a}"
                if q in tried:
                    continue
                tried.add(q)
                url = f"{BASE}/searchevents.php?e={requests.utils.quote(q)}"
                data = _get_json(url, debug=debug)
                if not data or not data.get("event"):
                    continue
                for ev in data["event"]:
                    # Aseguramos fútbol y fecha
                    if ev.get("strSport") != "Soccer":
                        continue
                    if (ev.get("dateEvent") or "") != date_iso:
                        continue
                    yield ev

            # También probar invertido (por si la indexación está al revés)
            for conj in ("vs", "v"):
                q = f"{a} {conj} {h}"
                if q in tried:
                    continue
                tried.add(q)
                url = f"{BASE}/searchevents.php?e={requests.utils.quote(q)}"
                data = _get_json(url, debug=debug)
                if not data or not data.get("event"):
                    continue
                for ev in data["event"]:
                    if ev.get("strSport") != "Soccer":
                        continue
                    if (ev.get("dateEvent") or "") != date_iso:
                        continue
                    yield ev

def _events_by_day(date_iso: str, debug=False):
    """
    Fallback: eventsday.php (por fecha). Filtra luego por los equipos.
    Doc: /eventsday.php?d=YYYY-MM-DD&s=Soccer
    """
    url = f"{BASE}/eventsday.php?d={date_iso}&s=Soccer"
    data = _get_json(url, debug=debug)
    if not data or not data.get("events"):
        return []
    return data["events"]

def _match_event_for_teams(home_slug: str, away_slug: str, events: List[dict]) -> Optional[dict]:
    """
    Dada una lista de eventos (mismo día), intenta matchear por nombres normalizados y slugs.
    """
    def norm_team(s: str) -> str:
        # normaliza parecido a slugify_team, pero devolvemos slug
        return slugify_team(s or "")

    for ev in events:
        h = norm_team(ev.get("strHomeTeam") or "")
        a = norm_team(ev.get("strAwayTeam") or "")
        if h == home_slug and a == away_slug:
            return ev
    return None

# -----------------------
# API pública (compatible con tu proyecto)
# -----------------------
def get_match_result(slug: str, fecha: str, liga_hint: Optional[str] = None,
                     search_window_days: int = 0, proxies: Optional[Dict] = None,
                     debug: bool = False) -> Optional[Result]:
    """
    Usa TheSportsDB para obtener el resultado 'gH-gA' de un partido.
    - slug: 'home-away' con slugs cortos (ej. 'sev-bar')
    - fecha: 'dd/mm/aa'
    - liga_hint: ignorado aquí (TheSportsDB no lo necesita para esta búsqueda)
    - search_window_days: mantener 0 para fecha exacta (puedes subirlo si lo necesitas)
    Retorna utils.Result o None si no encuentra/ no hay marcador.
    """
    # Parseo fecha
    try:
        d = datetime.strptime(fecha, "%d/%m/%y")
    except ValueError:
        raise ValueError("La fecha debe ser dd/mm/aa (ej. '05/10/25').")
    date_iso = d.strftime("%Y-%m-%d")

    # Slugs
    parts = [p for p in re.split(r"[-–—_\s]+", slug.strip().lower()) if p]
    if len(parts) != 2:
        raise ValueError("Slug inválido. Usa 'local-visitante', p.ej. 'sev-bar'.")

    home_slug = slugify_team(parts[0])
    away_slug = slugify_team(parts[1])

    # 1) Intento principal: searchevents.php con combinaciones de nombres
    home_names = _pick_name_for_slug(home_slug)
    away_names = _pick_name_for_slug(away_slug)

    chosen = None
    for ev in _search_event_candidates(home_names, away_names, date_iso, debug=debug):
        chosen = ev
        break

    # 2) Fallback: eventsday.php y filtrado por equipos
    if not chosen:
        same_day = _events_by_day(date_iso, debug=debug)
        if same_day:
            chosen = _match_event_for_teams(home_slug, away_slug, same_day)

    if not chosen:
        if debug:
            print("[TheSportsDB] no se encontró evento para esa fecha/slug.")
        return None

    # 3) Extraer marcador
    gH = chosen.get("intHomeScore")
    gA = chosen.get("intAwayScore")

    # A veces partidos futuros/no disputados no traen score
    if gH is None or gA is None or str(gH) == "" or str(gA) == "":
        if debug:
            print("[TheSportsDB] evento encontrado, pero sin marcador (pendiente o faltante).")
        return None

    # 4) Construir Result con tus slugs y fecha original
    return Result(home_slug, away_slug, str(gH), str(gA), d)
