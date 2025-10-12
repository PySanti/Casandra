from datetime import datetime
from utils.Match import Match
from utils.TeamData import TeamData
def get_match_features(slug, date, ligue):
    local_team, away_team = slug.split('-')
    match = Match(slug, date, ligue, 
                  TeamData(local_team),
                  TeamData(away_team),
        )
    match.set_teams_elo()
    #match.set_match_result()
    match.set_teams_value()
    match.set_performance_data()
    match.set_resting_days()
    return match





    
