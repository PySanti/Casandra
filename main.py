from utils import get_previews_matches
from utils.get_match_features import get_match_features
from utils.get_match_result import get_match_result
from utils.get_team_value import get_team_value
from utils.get_elo import get_team_elo
from utils.get_previews_matches import get_previus_matches

for r in get_previus_matches('barcelona','1/10/25',5, debug=True):
    print(r)
