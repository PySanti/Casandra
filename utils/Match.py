class Match:

    def __init__(self,date, local, away, comp, local_elo, away_elo) -> None:
        self.date = date
        self.local = local
        self.away = away
        self.comp = comp
        self.local_elo = local_elo
        self.away_elo = away_elo
        self.local_previus_results = []
        self.away_previus_results = []

        # recent avg goals, local
        self.pgml = None

        # recent avg conceeded goals, local
        self.pgel = None

        # recent avg goals, away
        self.pgmv = None

        # recent avg conceeded goals, away
        self.pgev = None

        # recent avg points (3 for win, 1 for draw, 0 for loss) local
        self.ppl = None

        # recent avg points (3 for win, 1 for draw, 0 for loss) away
        self.ppv = None

        # resting days local
        self.dd_l = None

        # resting days away
        self.dd_v = None

        # market value local
        self.vmtl = None

        # market value away
        self.vmtv = None


        # if available
        self.local_goals = None
        self.away_goals = None

    def set_performance_data(self):
        pass
