class Result:
    """
        Almacenara informacion acerca de resultados previos a un match
    """
    def __init__(self, local, away, local_goals, away_goals):
        self.local = local
        self.away = away
        self.away_goals = away_goals
        self.local_goals = local_goals
