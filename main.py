from utils.get_elo import get_team_elo
from utils.get_matches import get_matches_list
from utils.get_match_result import get_match_result
from utils.build_aliases import save_aliases_json
from utils.get_previews_matches import get_previus_matches


print(get_previus_matches('bar', '06/10/95', 5, debug=True))
print(get_team_elo('liv','6/10/25',5,debug=True))
