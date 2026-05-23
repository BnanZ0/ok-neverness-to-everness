import time

from src.heist_path.HeistPath import HeistPath
from src.heist_path.LobbyGotoLG1Path import LobbyGotoLG1Path
from src.heist_path.LG1GotoLG2Path import LG1GotoLG2Path
from src.heist_path.LG2Path import LG2Path

class HeistPathA(HeistPath):
    def run_path(self):
        LobbyGotoLG1Path(self).run_path()
        self.wait_team_ui_settle()
        self.check_current_floor(1)
        LG1GotoLG2Path(self).run_path()
        self.wait_team_ui_settle()
        self.check_current_floor(2)
        LG2Path(self).run_path()