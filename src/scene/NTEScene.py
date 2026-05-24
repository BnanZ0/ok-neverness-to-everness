import time

from ok import BaseScene, Logger

logger = Logger.get_logger(__name__)


class NTEScene(BaseScene):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._is_in_team = None
        self._in_combat = None
        self.cd_refreshed = False
        self._ocr_warm_up = False
        self._is_in_team_record = {"state": None, "timestamp": 0}
        self._scene_frame = None

    def reset(self):
        self._is_in_team = None
        self._in_combat = None
        self._scene_frame = None
        self.cd_refreshed = False

    def in_combat(self):
        return self._in_combat

    def set_in_combat(self):
        self._in_combat = True
        return True

    def set_not_in_combat(self):
        self._in_combat = False
        return False

    def is_in_team(self, fun):
        if self._is_in_team is None:
            self._is_in_team = fun()
            if self._is_in_team is not self._is_in_team_record.get("state"):
                self._is_in_team_record["state"] = self._is_in_team
                self._is_in_team_record["timestamp"] = time.time()
        return self._is_in_team

    def get_is_in_team_record(self):
        return self._is_in_team_record["state"], self._is_in_team_record["timestamp"]

    def scene_frame(self, frame):
        if self._scene_frame is None:
            self._scene_frame = frame
        return self._scene_frame
