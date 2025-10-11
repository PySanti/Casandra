from datetime import datetime
class Result:
    """
        Almacenara informacion acerca de resultados previos a un match
    """
    def __init__(self, local, away, local_goals, away_goals, date):
        self.local = local
        self.away = away
        self.away_goals = away_goals
        self.local_goals = local_goals
        self.date = date

    def __str__(self) -> str:
        return f"""
            {self.date}
            {self.local} : {self.local_goals}
            {self.away} : {self.away_goals}
        """
