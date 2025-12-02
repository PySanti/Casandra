from datetime import datetime
from utils.Match import Match
from utils.TeamData import TeamData
from utils.unslug_team import unslug_team
def get_match_features(match_slug, date, ligue):
    '''
        El match slug contendra el nombre completo de los equipos

        'barcelona-real madrid'
    '''
    local_team, away_team = match_slug.split("-")
    match = Match(match_slug, date, ligue, 
                  TeamData(local_team),
                  TeamData(away_team),
        )
    print("Buscando data de performance")
    match.set_performance_data()
    print("Buscando elos de equipos")
    match.set_teams_elo()
    print("Buscando resultado del encuentro")
    match.set_match_result()
    print("Buscando valores de equipos")
    match.set_teams_value()
#    print("Calculando dias de descanso")
#    match.set_resting_days()
    return match





    
