from datetime import datetime
from utils.Match import Match
from utils.get_elo import get_team_elo
from utils.get_match_result import get_match_result
from utils.get_previews_matches import get_previus_matches
from utils.get_team_value import get_team_value

def get_match_features(slug, date, ligue):
    local_team, away_team = slug.split('-')

    # teams elo
    local_elo = get_team_elo(local_team, date)
    away_elo = get_team_elo(away_team, date)

    match = Match(date, local_team, away_team, ligue, local_elo, away_elo)

    match.local_previus_results = get_previus_matches(local_team, date, 5)
    match.away_previus_results = get_previus_matches(away_team, date, 5)

    match.dd_l = int((datetime.strptime(date, "%d/%m/%y") - match.local_previus_results[0].date).days)
    match.dd_v = int((datetime.strptime(date, "%d/%m/%y") - match.local_previus_results[0].date).days)

    # match result if resolved

    if match_result:=get_match_result(slug, date, ligue):
        match.local_goals = match_result.local_goals
        match.away_goals = match_result.away_goals

    # teams value (need to cache per season)

    print('elo encontrado')
    match.vmtl = get_team_value(local_team, date)
    match.vmtv = get_team_value(away_team, date)

    # resting days as int


    return match





    
