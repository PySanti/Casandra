import numpy as np
class TeamData:
    """
        Almacena informacion de local o visitante dentro de un registro
    """
    def __init__(self, team_name):
        self.name = team_name
        self.elo = None
        self.previus_resuls = []

        # resting days
        self.dd = None

        # if available
        self.scored_goals = None

        # market value
        self.vmt = None

        # previus avg goals
        self.pgm = []

        # recent avg conceeded goals
        self.pge = []

        # recent avg points (3 for win, 1 for draw, 0 for loss)
        self.pp = []

    def __str__(self):
        return f"""
            Name :  {self.slug}
            ELO  :  {self.elo}
            Scored : {self.scored_goals}
            MV : {self.vmt}
            PGM : {self.pgm}
            PGE : {self.pge}
            PP : {self.pp}
        """

    def set_previus_performance(self):
        for r in self.previus_resuls:
            self.pgm.append(r.local_goals if r.local == self.slug else r.away_goals)
            self.pge.append(r.local_goals if r.local != self.slug else r.away_goals)
            if (r.local_goals > r.away_goals and r.local == self.slug) or (r.local_goals < r.away_goals and r.away == self.slug):
                self.pp.append(3)
            elif (r.local_goals == r.away_goals):
                self.pp.append(1)
            else:
                self.pp.append(0)
        self.pgm = np.mean(self.pgm)
        self.pge = np.mean(self.pge)
        self.pp = np.mean(self.pp)

