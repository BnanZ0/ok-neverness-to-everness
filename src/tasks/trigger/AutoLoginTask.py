from ok import Logger, TriggerTask
from qfluentwidgets import FluentIcon

from src.tasks.BaseNTETask import BaseNTETask

logger = Logger.get_logger(__name__)


class AutoLoginTask(BaseNTETask, TriggerTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.default_config = {'_enabled': True}
        self.trigger_interval = 5
        self.name = "自动登录游戏"
        self.description = "游戏启动后自动登录游戏"
        self.icon = FluentIcon.ACCEPT

    def run(self):
        if self._logged_in:
            pass
        elif self.scene.is_in_team(self.is_in_team):
            self._logged_in = True
        else:
            self.wait_login()