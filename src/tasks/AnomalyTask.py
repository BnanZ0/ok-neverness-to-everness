from ok import TaskDisabledException, og
from qfluentwidgets import FluentIcon

from src.combat.BaseCombatTask import BaseCombatTask
from src.Labels import Labels
from src.tasks.BaseNTETask import BaseNTETask
from src.tasks.NTEOneTimeTask import NTEOneTimeTask


class AnomalyTask(NTEOneTimeTask, BaseCombatTask):
    # --- 配置项键名 ---
    CONF_TASK_TYPE = "任务类型"
    CONF_EXP_TARGET = "具体奖励目标"
    CONF_ABILITY_ID = "异能材料序号"
    CONF_ARC_ID = "弧盘材料序号"
    CONF_CONSOLE_ID = "空幕序号"

    ABILITY_IDX_RANGE = (1, 5)
    ARC_IDX_RANGE = (1, 5)
    CONSOLE_IDX_RANGE = (1, 6)

    # --- 任务类型选项 ---
    TASK_EXP_COIN = "经验与甲硬币"
    TASK_ABILITY = "异能升级材料"
    TASK_ARC = "弧盘突破材料"
    TASK_CONSOLE = "空幕"

    # --- 经验子场景选项 ---
    EXP_CHAR = "角色经验"
    EXP_ARC = "弧盘经验"
    EXP_COIN = "甲硬币"
    EXP_ALL = [EXP_CHAR, EXP_ARC, EXP_COIN]

    TASK_COST = 40

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "异象界域"
        self.description = "自动进行异象界域任务"
        self.icon = FluentIcon.FLAG
        self._outer_config = None
        self.setup_config(self)

    @classmethod
    def setup_config(cls, instance: "BaseNTETask"):
        """
        初始化配置。支持传入外部实例（如 DailyTask）来同步配置项。
        """
        instance.default_config.update(
            {
                cls.CONF_TASK_TYPE: cls.TASK_EXP_COIN,
                cls.CONF_EXP_TARGET: cls.EXP_CHAR,
                cls.CONF_ABILITY_ID: 1,
                cls.CONF_ARC_ID: 1,
                cls.CONF_CONSOLE_ID: 1,
            }
        )

        instance.config_type.update(
            {
                cls.CONF_TASK_TYPE: {
                    "type": "drop_down",
                    "options": [
                        cls.TASK_EXP_COIN,
                        cls.TASK_ABILITY,
                        cls.TASK_ARC,
                        cls.TASK_CONSOLE,
                    ],
                    "sub_configs": {
                        cls.TASK_EXP_COIN: cls.CONF_EXP_TARGET,
                        cls.TASK_ABILITY: cls.CONF_ABILITY_ID,
                        cls.TASK_ARC: cls.CONF_ARC_ID,
                        cls.TASK_CONSOLE: cls.CONF_CONSOLE_ID,
                    },
                },
                cls.CONF_EXP_TARGET: {
                    "type": "drop_down",
                    "options": cls.EXP_ALL,
                },
            }
        )
        fmt = og.app.tr("选择列表中的第几个项目 ({}-{})")
        instance.config_description.update(
            {
                cls.CONF_TASK_TYPE: "选择要进行的任务类型",
                cls.CONF_EXP_TARGET: "选择经验与甲硬币任务的具体奖励目标",
                cls.CONF_ABILITY_ID: fmt.format(*cls.ABILITY_IDX_RANGE),
                cls.CONF_ARC_ID: fmt.format(*cls.ARC_IDX_RANGE),
                cls.CONF_CONSOLE_ID: fmt.format(*cls.CONSOLE_IDX_RANGE),
            }
        )

    def run(self):
        super().run()
        try:
            self.do_run()
        except TaskDisabledException:
            pass
        except Exception as e:
            self.log_error("AnomalyTask Error", e)

    def do_run(self, config=None, stamina_target=None):
        if config is None:
            config = self.config
        task_type = config.get(self.CONF_TASK_TYPE)
        idx = self.get_sub_idx(config)

        # 记录当前执行状态
        self.info_set("任务类型", task_type)
        if task_type == self.TASK_EXP_COIN:
            self.info_set("奖励目标", config.get(self.CONF_EXP_TARGET))
        else:
            self.info_set("项目序号", f"第 {idx + 1} 个项目")

        self.log_info(f"开始任务: {task_type}, 目标索引: {idx + 1}")

        # 共同操作 1
        self.ensure_main()
        self.log_info("打开F1面板并选择对应功能")
        self.openF1panel()

        box = self.box_of_screen(0.785, 0.022, 0.814, 0.076, name="stamina_icon")
        self.wait_until(
            lambda: self.find_one(Labels.stamina_icon, box=box),
            pre_action=lambda: self.operate_click(0.0563, 0.4924, interval=0.5),
            settle_time=0.5,
            time_out=10,
        )

        self.sleep(0.5)

        # 不同操作 1: 选择任务类型
        self.log_info(f"切换至任务页签: {task_type}")
        if task_type == self.TASK_EXP_COIN:
            self.operate_click(0.1703, 0.1528)
        elif task_type == self.TASK_ABILITY:
            self.operate_click(0.2977, 0.1528)
        elif task_type == self.TASK_ARC:
            self.operate_click(0.4211, 0.1528)
        elif task_type == self.TASK_CONSOLE:
            self.operate_click(0.5422, 0.1528)

        self.sleep(0.5)

        stamina = self.get_stamina()

        if stamina < self.TASK_COST:
            self.log_warning("体力不足，退出任务", notify=True)
            return False

        # 共同操作 2
        self.log_info("正在传送至目标地点")
        self.operate_click(0.9168, 0.2903)
        self.click_traval_button()
        self.wait_in_team_and_world()

        stamina_units = stamina // self.TASK_COST
        if stamina_target is not None:
            target_units = (stamina_target + self.TASK_COST - 1) // self.TASK_COST
            stamina_units = min(stamina_units, target_units)
            self.info_set("体力消耗目标", stamina_target)
        double_count = stamina_units // 2
        single_count = stamina_units % 2
        self.log_info(f"双倍次数: {double_count}, 单倍次数: {single_count}")

        self.enter_anomaly_from_interac(idx)

        total_count = double_count + single_count
        completed_count = 0
        while completed_count < total_count:
            double = completed_count < double_count
            self.wait_in_team()
            self.sleep(2)
            if not self.do_combat_and_claim(double):
                self.log_warning("本次未成功领取奖励，退出副本后重试当前目标")
                self.exit_anomaly()
                self.enter_anomaly_from_interac(idx, retry=True)
                continue
            completed_count += 1
            self.sleep(2)
            if completed_count < total_count:
                self.operate_click(0.621, 0.864)
        self.operate_click(0.381, 0.861)
        self.log_info("任务执行完毕")
        return True

    def enter_anomaly_from_interac(self, idx, retry=False):
        self.log_info("寻路至交互点并触发交互")
        direction = "s" if retry else "w"
        self.walk_until_interac(direction=direction, raise_if_not_found=True)
        self.wait_until(
            lambda: not self.find_interac(),
            post_action=lambda: self.send_interac(handle_claim=False),
            time_out=10,
        )

        self.wait_until(lambda: self.find_one(Labels.stamina_icon), settle_time=0.5, time_out=10)

        # 不同操作 2: 选择对应序号的项目
        self.log_info(f"选择项目序号: {idx + 1}")
        self.click_sub_idx(idx)
        self.sleep(0.25)

        # 共同操作 3
        self.log_info("进入副本并等待")
        self.wait_until(
            lambda: not self.find_one(Labels.stamina_icon),
            pre_action=lambda: self.operate_click(0.8008, 0.9042),
            time_out=10,
        )

    def exit_anomaly(self):
        self.wait_click_confirm(
            lambda: self.send_key("esc", interval=2), range=(0.6629, 0.6167, 0.6988, 0.6965)
        )
        self.wait_in_team_and_world()

    def do_combat_and_claim(self, double: bool):
        self.log_info("开始执行战斗流程")
        self.walk_until_combat(run=True, delay=1)
        self.combat_once()

        self.log_info("战斗结束，正在前往领取奖励")

        def action(count):
            self.walk_to_treasure()
            self.send_interac(handle_claim=False)
            claims = self.find_all_claim()
            self.log_info(f"发现 {len(claims)} 个领取奖励")
            if not claims:
                self.log_warning("未找到领取奖励按钮")
                key = "a" if count % 2 else "d"
                self.send_key(key, down_time=0.5, after_sleep=1)
                self.next_frame()
                return False
            return claims

        claims = self.retry_on_action(action)
        if not claims:
            return False

        if double:
            box = max(claims, key=lambda x: x.x)
        else:
            box = min(claims, key=lambda x: x.x)
        btn = box.copy(x_offset=box.width * 3)
        self.operate_click(btn)
        return True

    def click_sub_idx(self, idx):
        y = 0.1715 + idx * (0.2806 - 0.1715)
        self.operate_click(0.0852, y)

    def get_sub_idx(self, config: dict):
        """根据任务类型从对应的配置项中获取项目索引"""
        task_type = config.get(self.CONF_TASK_TYPE)
        if task_type == self.TASK_EXP_COIN:
            target = config.get(self.CONF_EXP_TARGET)
            return self.EXP_ALL.index(target) if target in self.EXP_ALL else 0
        elif task_type == self.TASK_ABILITY:
            return self._config_validate(config, self.ABILITY_IDX_RANGE, self.CONF_ABILITY_ID) - 1
        elif task_type == self.TASK_ARC:
            return self._config_validate(config, self.ARC_IDX_RANGE, self.CONF_ARC_ID) - 1
        elif task_type == self.TASK_CONSOLE:
            return self._config_validate(config, self.CONSOLE_IDX_RANGE, self.CONF_CONSOLE_ID) - 1
        return 0

    def _config_validate(self, config: dict, range: tuple[int, int], key: str):
        """验证配置项的值"""
        min_idx, max_idx = range
        val = config.get(key, 1)
        valid_val = max(min_idx, min(val, max_idx))
        if val != valid_val:
            config[key] = valid_val
            self.sync_config(config)
        return valid_val

    def get_next_sub_idx(self, config: dict):
        """获取下一个子场景索引 (0-based)"""
        idx = self.get_sub_idx(config)
        task_type = config.get(self.CONF_TASK_TYPE)
        if task_type == self.TASK_EXP_COIN:
            return (idx + 1) % 3

        ranges = {
            self.TASK_ABILITY: self.ABILITY_IDX_RANGE,
            self.TASK_ARC: self.ARC_IDX_RANGE,
            self.TASK_CONSOLE: self.CONSOLE_IDX_RANGE,
        }
        if task_type in ranges:
            r = ranges[task_type]
            return (idx + 1) % (r[1] - r[0] + 1)
        return 0
