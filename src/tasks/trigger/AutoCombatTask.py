import time

from ok import Logger, TriggerTask
from PySide6.QtCore import QObject, Signal
from qfluentwidgets import FluentIcon

from src.char.CharFactory import get_char_feature_by_pos
from src.char.custom.CustomCharManager import CustomCharManager
from src.combat.BaseCombatTask import BaseCombatTask, CharDeadException, NotInCombatException
from src.combat.ChainLoader import ChainLoader


class ScannerSignals(QObject):
    scan_done = Signal(list, str)


scanner_signals = ScannerSignals()

logger = Logger.get_logger(__name__)


class AutoCombatTask(BaseCombatTask, TriggerTask):
    txt_team_not_exist = "队伍不存在"
    txt_team_not_enough = "队伍人数少于2人"

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
        if self._app is not None:
            self.tr(self.txt_team_not_exist)
            self.tr(self.txt_team_not_enough)

    def run(self):
        ret = False
        if not self.scene.is_in_team(self.is_in_team):
            return

        manager = CustomCharManager()
        fixed_team = manager.get_fixed_team()
        team_strategy = fixed_team.get("team_strategy", "NONE")
        chain_builder = None

        combat_start = time.time()
        while self.in_combat():
            try:
                if not ret:
                    ret = True
                    if team_strategy == "NONE":
                        has_residual_chain = any(
                            c.__class__.__name__.endswith("Chain") for c in self.chars if c
                        )
                        if has_residual_chain:
                            self.log_info("检测到残留的 Chain 类角色，重新加载基础角色配置。")
                            self.load_chars()
                    self.switch_to_combat_start_char()
                
                if team_strategy != "NONE" and self.chain_executor:
                    if not self.chain_executor.active:
                        chain_builder = ChainLoader.load_strategy(self, team_strategy)
                        if chain_builder:
                            self.log_info(f"启用连携策略：{team_strategy}")
                            self.chain_executor.reset()
                            self.chain_executor.loop(chain_builder)
                
                if self.chain_executor and self.chain_executor.active:
                    current_char, _ = self.chain_executor.target
                    if current_char:
                        current_char.perform()
                    else:
                        self.get_current_char().perform()
                else:
                    self.get_current_char().perform()
            except CharDeadException:
                self.log_error("Characters dead", notify=True)
                break
            except NotInCombatException as e:
                logger.info(f"auto_combat_task_out_of_combat {int(time.time() - combat_start)} {e}")
                ret = False
                if self.chain_executor:
                    self.chain_executor.reset()
                break
        if ret:
            self.combat_end()

    def scan_team(self):
        self.log_info("开始扫描当前队伍...")
        in_team, _, count = self.in_team()
        if not in_team or count == 0:
            scanner_signals.scan_done.emit([], self.tr(self.txt_team_not_exist))
            self.log_info("队伍不存在, 扫描结束")
            return
        if count < 2:
            scanner_signals.scan_done.emit([], self.tr(self.txt_team_not_enough))
            self.log_info("队伍人数少于2人, 扫描结束")
            return

        manager = CustomCharManager()
        results = []
        frame = self.frame
        for i in range(count):
            feature_mat, w, h = get_char_feature_by_pos(self, i, frame=frame)
            if feature_mat is not None and feature_mat.size > 0:
                is_match, match_name, confidence = manager.match_feature(self, feature_mat)
                name = match_name if is_match else None
                results.append(
                    {"index": i, "mat": feature_mat, "width": w, "height": h, "match": name}
                )
                self.log_debug(f"char_{i + 1}: {name}, confidence={confidence:.2f}")
        scanner_signals.scan_done.emit(results, "")
        self.log_info("扫描完成！")
