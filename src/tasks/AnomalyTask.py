from ok import TaskDisabledException
from qfluentwidgets import FluentIcon

from src.combat.BaseCombatTask import BaseCombatTask
from src.Labels import Labels
from src.tasks.BaseNTETask import BaseNTETask
from src.tasks.NTEOneTimeTask import NTEOneTimeTask
from src.utils.i18n_format import register_i18n_format


class AnomalyTask(NTEOneTimeTask, BaseCombatTask):
    NAME = "异象界域"

    # --- 配置项键名 ---
    CONF_TASK_TYPE = "任务类型"
    CONF_EXP_TARGET = "具体奖励目标"
    CONF_ABILITY_ID = "异能材料序号"
    CONF_ARC_ID = "弧盘材料序号"
    CONF_CONSOLE_ID = "空幕序号"
    CONF_CYCLEB_TASK_MODE = "循环模式"
    CONF_CUSTOM_CYCLE = "循环序列"

    # --- 循环模式 ---
    CYCLE_NONE = "停用"
    CYCLE_SUB_TASK = "自动循环序号/目标"
    CYCLE_CUSTOM = "自定义循环"

    # --- 任务类型选项 ---
    TASK_EXP_COIN = "经验与甲硬币"
    TASK_ABILITY = "异能升级材料"
    TASK_ARC = "弧盘突破材料"
    TASK_CONSOLE = "空幕"

    # --- 经验子场景选项 ---
    EXP_CHAR = "角色经验"
    EXP_ARC = "弧盘经验"
    EXP_COIN = "甲硬币"

    # --- 任务配置结构 ---
    TASK_SUB_CONFIGS = {
        TASK_EXP_COIN: CONF_EXP_TARGET,
        TASK_ABILITY: CONF_ABILITY_ID,
        TASK_ARC: CONF_ARC_ID,
        TASK_CONSOLE: CONF_CONSOLE_ID,
    }
    TASK_TYPES = list(TASK_SUB_CONFIGS)

    # --- 任务 ID (1-based) ---
    EXP_COIN_ID_RANGE = (1, 3)
    ABILITY_ID_RANGE = (1, 5)
    ARC_ID_RANGE = (1, 5)
    CONSOLE_ID_RANGE = (1, 6)
    TASKS_ID_RANGE = {
        TASK_EXP_COIN: EXP_COIN_ID_RANGE,
        TASK_ABILITY: ABILITY_ID_RANGE,
        TASK_ARC: ARC_ID_RANGE,
        TASK_CONSOLE: CONSOLE_ID_RANGE,
    }

    TASK_ID_TO_CONFIG_VALUE = {
        TASK_EXP_COIN: {
            1: EXP_CHAR,
            2: EXP_ARC,
            3: EXP_COIN,
        },
    }
    EXP_TARGET_OPTIONS = list(TASK_ID_TO_CONFIG_VALUE[TASK_EXP_COIN].values())

    # --- 字串格式 ---
    CYCLE_CUSTOM_OPTION_FMT = "{task}: {id}"
    DESC_ID_RANGE_FMT = "选择列表中的第几个项目 ({}-{})"

    # --- 自定义循环选项 ---
    NUMERIC_ID_TASK_TYPES = [TASK_ABILITY, TASK_ARC, TASK_CONSOLE]
    CYCLE_OPTION_TO_TASK_ID = {}
    for _id, _option in TASK_ID_TO_CONFIG_VALUE[TASK_EXP_COIN].items():
        CYCLE_OPTION_TO_TASK_ID[_option] = (TASK_EXP_COIN, _id)
    for _task_type in NUMERIC_ID_TASK_TYPES:
        _min_id, _max_id = TASKS_ID_RANGE[_task_type]
        for _id in range(_min_id, _max_id + 1):
            _option = CYCLE_CUSTOM_OPTION_FMT.format(task=_task_type, id=_id)
            CYCLE_OPTION_TO_TASK_ID[_option] = (_task_type, _id)
    CYCLE_CUSTOM_OPTIONS = list(CYCLE_OPTION_TO_TASK_ID)
    del _id, _max_id, _min_id, _option, _task_type

    # --- 任务消耗体力 ---
    TASK_COST = 40

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = self.NAME
        self.description = "自动进行异象界域任务"
        self.icon = FluentIcon.FLAG
        self._outer_config = None
        self.setup_config(self)

    @classmethod
    def setup_config(cls, instance: "BaseNTETask", daily=False):
        """
        初始化配置。支持传入外部实例(如 DailyTask)来同步配置项。
        """
        config_updates = {
            cls.CONF_TASK_TYPE: cls.TASK_EXP_COIN,
            cls.CONF_EXP_TARGET: cls.EXP_CHAR,
            cls.CONF_ABILITY_ID: 1,
            cls.CONF_ARC_ID: 1,
            cls.CONF_CONSOLE_ID: 1,
            cls.CONF_CUSTOM_CYCLE: [],
        }
        if daily:
            config_updates[cls.CONF_CYCLEB_TASK_MODE] = cls.CYCLE_NONE
        instance.default_config.update(config_updates)

        instance.config_type.update(
            {
                cls.CONF_TASK_TYPE: {
                    "type": "drop_down",
                    "options": cls.TASK_TYPES,
                    "sub_configs": cls.TASK_SUB_CONFIGS,
                },
                cls.CONF_EXP_TARGET: {
                    "type": "drop_down",
                    "options": cls.EXP_TARGET_OPTIONS,
                },
                cls.CONF_CUSTOM_CYCLE: {
                    "options_available": cls.CYCLE_CUSTOM_OPTIONS,
                    "allow_duplication": False,
                },
                cls.CONF_CYCLEB_TASK_MODE: {
                    "type": "drop_down",
                    "options": [
                        cls.CYCLE_NONE,
                        cls.CYCLE_SUB_TASK,
                        cls.CYCLE_CUSTOM,
                    ],
                    "sub_configs": {
                        cls.CYCLE_CUSTOM: cls.CONF_CUSTOM_CYCLE,
                    },
                },
            }
        )
        description_update = {
            cls.CONF_TASK_TYPE: "选择要进行的任务类型",
            cls.CONF_EXP_TARGET: "选择经验与甲硬币任务的具体奖励目标",
            cls.CONF_ABILITY_ID: cls.DESC_ID_RANGE_FMT.format(*cls.ABILITY_ID_RANGE),
            cls.CONF_ARC_ID: cls.DESC_ID_RANGE_FMT.format(*cls.ARC_ID_RANGE),
            cls.CONF_CONSOLE_ID: cls.DESC_ID_RANGE_FMT.format(*cls.CONSOLE_ID_RANGE),
        }
        if daily:
            description_update[cls.CONF_CYCLEB_TASK_MODE] = "任务完成后自动切换至下一个项目"
        instance.config_description.update(description_update)
        if not daily:
            instance.add_claim_reward_count_config()

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
        self.open_f1_domain_page()

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
        btns = self.find_confirms(self.box_of_screen(0.925, 0.190, 0.982, 0.760))
        btn = min(btns, key=lambda x: x.y)
        self.operate_click(btn)
        self.click_traval_button()
        self.wait_in_team()

        stamina_units = stamina // self.TASK_COST
        if stamina_target is not None:
            target_units = (stamina_target + self.TASK_COST - 1) // self.TASK_COST
            stamina_units = min(stamina_units, target_units)
            self.info_set("体力消耗目标", stamina_target)
        reward_count = config.get(self.CONF_CLAIM_REWARD_COUNT, 0)
        if reward_count > 0:
            stamina_units = min(stamina_units, reward_count)
        double_count = stamina_units // 2
        single_count = stamina_units % 2
        self.log_info(f"双倍次数: {double_count}, 单倍次数: {single_count}")

        self.enter_anomaly_from_interac(idx)

        total_count = double_count + single_count
        completed_count = 0
        while completed_count < total_count:
            double = completed_count < double_count
            self.wait_until(lambda: self.find_one(Labels.in_domain), time_out=30)
            self.wait_in_team()
            self.sleep(1)
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
            settle_time=0.5,
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
            lambda: self.send_key("esc", interval=2),
            range=(0.619, 0.609, 0.709, 0.708),
            settle_time=0.4,
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
        """Return the selected sub-scene index, where index equals ID minus one."""
        return self.resolve_sub_id(config) - 1

    def resolve_sub_id(self, config: dict):
        """Return the selected task ID, normalizing and saving invalid config values."""
        task_type = config.get(self.CONF_TASK_TYPE)
        config_key = self.TASK_SUB_CONFIGS.get(task_type)
        task_id_range = self.TASKS_ID_RANGE.get(task_type)
        if config_key is None or task_id_range is None:
            self.log_warning("任务ID配置获取失败, 使用默认ID 1")
            return 1

        config_value = config.get(config_key)
        id_to_value = self.TASK_ID_TO_CONFIG_VALUE.get(task_type)
        task_id = (
            next((id for id, value in id_to_value.items() if value == config_value), config_value)
            if id_to_value
            else config_value
        )
        min_id, max_id = task_id_range
        if not isinstance(task_id, int):
            task_id = min_id
        valid_task_id = max(min_id, min(task_id, max_id))
        valid_value = (
            id_to_value.get(valid_task_id, valid_task_id) if id_to_value else valid_task_id
        )
        if config.get(config_key) != valid_value:
            config[config_key] = valid_value
            self.sync_config(config)
        return valid_task_id

    def set_task_type_and_id(self, config: dict, task_type: str, task_id: int):
        """Set a task type and its ID using the task's configured value mapping."""
        config_key = self.TASK_SUB_CONFIGS.get(task_type)
        task_id_range = self.TASKS_ID_RANGE.get(task_type)
        if config_key is None or task_id_range is None:
            self.log_warning("无法设置任务ID")
            return False
        min_id, max_id = task_id_range
        if not min_id <= task_id <= max_id:
            self.log_warning("无法设置任务ID")
            return False
        id_to_value = self.TASK_ID_TO_CONFIG_VALUE.get(task_type)
        config[self.CONF_TASK_TYPE] = task_type
        config[config_key] = id_to_value.get(task_id, task_id) if id_to_value else task_id
        return True

    def get_next_sub_idx(self, config: dict):
        """获取下一个子场景索引 (0-based)"""
        return self.get_next_sub_id(config) - 1

    def get_next_sub_id(self, config: dict):
        """获取下一个任务 ID (1-based)"""
        task_id = self.resolve_sub_id(config)
        task_type = config.get(self.CONF_TASK_TYPE)
        task_id_range = self.TASKS_ID_RANGE.get(task_type)
        if task_id_range is None:
            return 1
        min_id, max_id = task_id_range
        return min_id + (task_id - min_id + 1) % (max_id - min_id + 1)

    def shift_id(self, task: BaseNTETask):
        """Advance the daily task according to its configured cycle mode."""
        config = task.config
        if not config:
            return
        shift_handler = {
            self.CYCLE_SUB_TASK: self.shift_sub_task_id,
            self.CYCLE_CUSTOM: self.shift_custom_cycle,
        }.get(config.get(self.CONF_CYCLEB_TASK_MODE))
        if shift_handler:
            shift_handler(task)

    def shift_sub_task_id(self, task: BaseNTETask):
        """Advance to the next ID of the current task type."""
        task_type = task.config.get(self.CONF_TASK_TYPE)
        next_task_id = self.get_next_sub_id(task.config)
        if self.set_task_type_and_id(task.config, task_type, next_task_id):
            task.sync_config()

    def shift_custom_cycle(self, task: BaseNTETask):
        """Advance to the next user-selected custom-cycle option."""
        cycle: list = task.config.get(self.CONF_CUSTOM_CYCLE, [])
        if not cycle:
            task.log_warning("自定义任务循环为空, 不切换任务")
            return
        task_type = task.config.get(self.CONF_TASK_TYPE)
        task_id = self.get_sub_idx(task.config) + 1
        option = self.get_cycle_option(task_type, task_id)
        if option in cycle:
            current_index = cycle.index(option)
            next_option = cycle[(current_index + 1) % len(cycle)]
        else:
            next_option = cycle[0]
        next_task = self.CYCLE_OPTION_TO_TASK_ID.get(next_option)
        if next_task is None:
            task.log_warning("无法解析下一个自定义循环任务")
            return

        next_task_type, next_task_id = next_task
        if self.set_task_type_and_id(task.config, next_task_type, next_task_id):
            task.sync_config()
            task.log_info(f"下一个任务设为 {next_task_type} {next_task_id}")

    def get_cycle_option(self, task_type: str, task_id: int):
        """Return the custom-cycle label for a task ID, if it is available."""
        return next(
            (
                option
                for option, cycle_task in self.CYCLE_OPTION_TO_TASK_ID.items()
                if cycle_task == (task_type, task_id)
            ),
            None,
        )


register_i18n_format(
    AnomalyTask.DESC_ID_RANGE_FMT,
)
register_i18n_format(
    AnomalyTask.CYCLE_CUSTOM_OPTION_FMT,
    translated_fields=frozenset({"task"}),
    allowed_values={"task": AnomalyTask.NUMERIC_ID_TASK_TYPES},
    translate_template=False,
)
