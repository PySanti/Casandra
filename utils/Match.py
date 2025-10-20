from utils.get_elo import get_team_elo
from datetime import datetime
from utils.get_match_result import get_match_result
from utils.get_previews_matches import get_previus_matches
from utils.get_team_value import get_team_value
from utils.CONSTANTS import LOCAL, AWAY, PREVIUS_MATCHES_CONSIDERED

DEBUG = True

class Match:
    def __init__(self,slug, date,  comp, local_data, away_data) -> None:
        self.match_slug = slug
        self.date = date
        self.comp = comp
        self.teams_data = [local_data,away_data]
    def set_teams_elo(self):
        for team in self.teams_data:
            elo = get_team_elo(team.name, self.date, debug=DEBUG)
            print(f'{team.name} : {elo}')
            team.elo = elo
    def set_performance_data(self):
        for team in self.teams_data:
            team.previus_results = get_previus_matches(team.name, self.date, PREVIUS_MATCHES_CONSIDERED, debug=DEBUG)
            print(f"Mostrando previus results de {team.name}")
            print(  team.previus_results)
            team.set_previus_performance()
    def set_resting_days(self):
        for team in self.teams_data:
            team.dd = int((datetime.strptime(self.date, "%d/%m/%y") - team.previus_results[0].date).days)
    def set_match_result(self):
        if match_result:=get_match_result(self.match_slug, self.date, self.comp, debug=DEBUG):
            self.teams_data[LOCAL].scored_goals = match_result.local_goals
            self.teams_data[AWAY].scored_goals = match_result.away_goals
    def set_teams_value(self):
        for team in self.teams_data:
            team.vmt = get_team_value(team.name, self.date, debug=DEBUG)
    def __str__(self):
        return f"""

        Match : {self.match_slug}
        Date : {self.date}
        Competition : {self.comp}


                Local   
            {self.teams_data[LOCAL]}


                Away   
            {self.teams_data[AWAY]}
        """
