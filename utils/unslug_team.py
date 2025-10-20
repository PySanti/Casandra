# utils/team_aliases.py
import json
import os
from typing import Optional, List

def unslug_team(slug: str, json_path: str = "./data/team_aliases.json") -> Optional[str]:
    """
    Dado un slug (p.ej. 'bar', 'rma', 'mci'), lee el archivo JSON y retorna
    el 'mejor nombre' (primer alias de la lista). Si no existe, devuelve None.
    """
    slug = (slug or "").strip().lower()
    if not slug:
        return None

    if not os.path.exists(json_path):
        raise FileNotFoundError(f"No se encontró el archivo de alias: {json_path}")

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    aliases: List[str] = data.get(slug, [])
    if not aliases:
        return None
    return aliases[0]
