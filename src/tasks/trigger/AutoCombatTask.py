import time

from ok import Logger, TriggerTask
from qfluentwidgets import FluentIcon

from src.char.custom.CustomCharManager import CustomCharManager
from src.combat.BaseCombatTask import BaseCombatTask, CharDeadException, NotInCombatException
from src.team_axis import TeamAxisError, create_matching_team_axis

logger = Logger.get_logger(__name__)


class AutoCombatTask(BaseCombatTask, TriggerTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.default_config = {"_enabled": True}
        self.trigger_interval = 0.1
        self.name = "自动战斗"
        self.description = "受《异环》UI的特殊性影响, 部分场景下存在识别稳定性波动"
        self.icon = FluentIcon.CALORIES
        self.last_is_click = False
        self.default_config.update(
            {
                "自动目标": True,
            }
        )
        self.config_description = {
            "自动目标": "关闭时仅在中键选中敌人且画面识别到 'Lv' 文字时开启战斗",
        }
        self.op_index = 0
        self.origin_func = {}

    def create_fixed_team_axis(self):
        manager = CustomCharManager()
        fixed_team = manager.get_fixed_team()
        axis_config = manager.get_fixed_team_axis()
        if not fixed_team.get("enabled", False) or not axis_config.get("enabled", False):
            return None

        axis_id = axis_config.get("axis_id", "")
        axis = create_matching_team_axis(self, axis_id=axis_id)
        if axis is None:
            logger.warning(f"fixed team axis does not match current team: {axis_id}")
        return axis

    def run(self):
        ret = False
        team_axis = None
        if not self.scene.is_in_team(self.is_in_team):
            return

        combat_start = time.time()
        while self.in_combat():
            try:
                if not ret:
                    ret = True
                    team_axis = self.create_fixed_team_axis()
                    if team_axis:
                        self.log_info(f"启用专属队伍轴: {team_axis.name}")
                    else:
                        self.switch_to_combat_start_char()

                if team_axis:
                    team_axis.perform_next()
                else:
                    self.get_current_char(raise_exception=True).perform()
            except CharDeadException:
                self.log_error("Characters dead", notify=True)
                break
            except NotInCombatException as e:
                logger.info(f"auto_combat_task_out_of_combat {int(time.time() - combat_start)} {e}")
                break
            except TeamAxisError as e:
                self.log_error(f"专属队伍轴停止: {e}", notify=True)
                break
        if team_axis:
            team_axis.on_combat_end()
        if ret:
            self.combat_end()
