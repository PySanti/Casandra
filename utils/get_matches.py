import os
import unicodedata
import requests
from datetime import datetime
from typing import List, Tuple
from dotenv import load_dotenv
import os


def get_matches_list(liga: str, temporada: int, jornada: int) -> List[Tuple[str, str]]:
    """
    Devuelve una lista de tuplas (slug_partido, fecha_dd/mm/aa) para la liga, temporada y jornada dadas.

    Parámetros
    ----------
    liga : str
        Una de: 'laliga', 'seriea', 'ligue1', 'premier', 'bundesliga'
    temporada : int
        Año de inicio de la temporada (p. ej., 2024 para la temporada 2024-2025).
    jornada : int
        Número de jornada (matchday), entero >= 1.

    Retorna
    -------
    List[Tuple[str, str]]
        Lista como: [('sev-bar', '05/10/25'), ...]
    
    Requisitos
    ----------
    - Variable de entorno FOOTBALL_DATA_API_TOKEN con tu token de https://www.football-data.org/
    - requests (pip install requests)
    """
    load_dotenv()

    token = os.getenv("FOOTBALL_DATA_API_TOKEN")
    if not token:
        raise RuntimeError("Falta FOOTBALL_DATA_API_TOKEN en el entorno.")

    # Mapear la liga pedida a los códigos de competición de football-data
    comp_map = {
        "laliga": "PD",         # Spain – Primera División
        "premier": "PL",        # England – Premier League
        "seriea": "SA",         # Italy – Serie A
        "bundesliga": "BL1",    # Germany – Bundesliga
        "ligue1": "FL1",        # France – Ligue 1
    }
    key = liga.strip().lower()
    if key not in comp_map:
        raise ValueError("Liga no soportada. Usa: laliga, seriea, ligue1, premier, bundesliga.")

    competition = comp_map[key]

    url = f"https://api.football-data.org/v4/competitions/{competition}/matches"
    params = {
        "season": temporada,   # Año de inicio de la temporada
        "matchday": jornada
    }
    headers = {"X-Auth-Token": token}

    resp = requests.get(url, params=params, headers=headers, timeout=30)
    if resp.status_code == 403:
        raise PermissionError("Token inválido o sin permisos en football-data.org.")
    resp.raise_for_status()

    data = resp.json()
    matches = data.get("matches", [])

    def slugify_team(name: str) -> str:
        # Normaliza, quita acentos/diacríticos y espacios, toma 3 primeras letras
        norm = unicodedata.normalize("NFKD", name)
        cleaned = "".join(c for c in norm if not unicodedata.combining(c))
        cleaned = cleaned.lower().replace(" ", "").replace(".", "").replace("-", "")
        # Ajustes rápidos para casos comunes
        aliases = {
            "sevilla": "sev",
            "barcelona": "bar",
            "realmadird": "rma",  # por si hubiese errores de nombre
            "realMadrid".lower(): "rma",
        }
        if cleaned in aliases:
            return aliases[cleaned]
        return cleaned[:3] if len(cleaned) >= 3 else cleaned

    result: List[Tuple[str, str]] = []
    for m in matches:
        home = m["homeTeam"]["shortName"] or m["homeTeam"]["name"]
        away = m["awayTeam"]["shortName"] or m["awayTeam"]["name"]

        # A veces shortName no está; usa name como respaldo
        home_name = home or m["homeTeam"]["name"]
        away_name = away or m["awayTeam"]["name"]

        home_slug = slugify_team(home_name)
        away_slug = slugify_team(away_name)

        # Fecha UTC → 'dd/mm/aa'
        utc = m.get("utcDate")
        if not utc:
            # Si no hay fecha, omite o coloca vacío; aquí preferimos omitir
            continue
        dt = datetime.fromisoformat(utc.replace("Z", "+00:00"))
        date_str = dt.strftime("%d/%m/%y")

        result.append((f"{home_slug}-{away_slug}", date_str))

    return result
