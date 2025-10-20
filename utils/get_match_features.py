from datetime import datetime
from utils.Match import Match
from utils.TeamData import TeamData
def get_match_features(slug, date, ligue):
    local_team, away_team = slug.split('-')
    match = Match(slug, date, ligue, 
                  TeamData(local_team),
                  TeamData(away_team),
        )
#    print("Buscando data de performance")
#    match.set_performance_data()
    print("Buscando elos de equipos")
    match.set_teams_elo()
    print("Buscando resultado del encuentro")
    match.set_match_result()
    print("Buscando valores de equipos")
    match.set_teams_value()
#    print("Calculando dias de descanso")
#    match.set_resting_days()
    return match





    
