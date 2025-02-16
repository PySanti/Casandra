import requests  
from utils.read_api_keys import read_api_keys

API_KEYS = read_api_keys("./secrets.json")

def obtener_partidos_jornada(competicion_id, temporada, jornada):  
    # Define la URL de la API para obtener los partidos de la competición específica  
    url = f"https://api.football-data.org/v4/competitions/{competicion_id}/matches"  
    
    # Define los headers, incluyendo la clave de API  
    headers = {  
        'X-Auth-Token':  API_KEYS["FOOTBALL-DATA_API_KEY"] # Reemplaza con tu clave de API  
    }  
    
    # Define los parámetros de la solicitud  
    params = {  
        'season': temporada,  
        'matchday': jornada  
    }  
    
    # Realiza la solicitud a la API  
    response = requests.get(url, headers=headers, params=params)  

    # Verifica que la solicitud fue exitosa  
    if response.status_code != 200:  
        print(f"Error {response.status_code}: No se pudo acceder a la API.")  
        return []  

    # Procesa la respuesta JSON  
    datos = response.json()  
    partidos = []  

    # Extrae información de los partidos  
    for partido in datos.get('matches', []):  
        partido_info = {  
            'equipo_local': partido['homeTeam']['name'],  
            'equipo_visitante': partido['awayTeam']['name'],  
            'fecha': partido['utcDate'],  
            'estado': partido['status']  
        }  
        partidos.append(partido_info)  

    return partidos  

# Ejemplo de uso  
competicion_id = "PL"  # ID de la competición (ejemplo: Premier League)  
temporada = "2023"  # Temporada  
jornada = 23  # Jornada  

partidos = obtener_partidos_jornada(competicion_id, temporada, jornada)  
print(partidos)
