from ok import TaskDisabledException
from qfluentwidgets import FluentIcon

from src.combat.BaseCombatTask import BaseCombatTask
from src.Labels import Labels
from src.tasks.BaseNTETask import BaseNTETask
from src.tasks.NTEOneTimeTask import NTEOneTimeTask


class AnomalyHunter(NTEOneTimeTask, BaseCombatTask):
    # --- 配置项键名 ---
    CONF_HUNTER_TARGET = "追猎目标"
    CONF_STAMINA_TARGET = "体力消耗目标"

    # --- 追猎目标选项 ---
    TARGET_SOUND_KING = "音霸魔王"
    TARGET_HEADLESS_RIDER = "无首铁驭"
    TARGET_SERENITY = "塞润尼缇"
    TARGET_BLACK_BOOK = "黑之书"
    TARGET_SEA_PRISONER = "海囚"
    TARGET_NEST_BIRD = "围巢鸟"
    TARGET_SPOTTED_BUTTERFLY = "斑蝶"
    HUNTER_TARGETS = [
        TARGET_SOUND_KING,
        TARGET_HEADLESS_RIDER,
        TARGET_SERENITY,
        TARGET_BLACK_BOOK,
        TARGET_SEA_PRISONER,
        TARGET_NEST_BIRD,
        TARGET_SPOTTED_BUTTERFLY,
    ]

    DEFAULT_TREASURE_FEATURES = [
        Labels.boss_treasure,
    ]
    BOSS_TREASURE_THRESHOLD = 0.65
    BOSS_TREASURE_ONCE_SEARCH_TIME = 2
    BOSS_TREASURE_WALK_TIMEOUT = 15

    TASK_COST = 60
    MAX_CONSECUTIVE_FAILURES = 3
    HUNTER_TAB_X = 0.912
    HUNTER_TAB_Y = 0.152
    HUNTER_TRAVEL_X = 0.867
    HUNTER_TRAVEL_Y_START = 0.262
    HUNTER_NEXT_PAGE_TRAVEL_Y_START = 0.468
    HUNTER_TRAVEL_Y_STEP = 0.148
    HUNTER_FIRST_PAGE_SIZE = 4
    DIRECT_WALK_TARGETS = {TARGET_SOUND_KING, TARGET_SERENITY}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "异象追猎"
        self.description = "自动进行异象追猎任务"
        self.icon = FluentIcon.FLAG
        self._outer_config = None
        self.setup_config(self)

    @classmethod
    def setup_config(cls, instance: "BaseNTETask"):
        """初始化异象追猎配置。"""
        instance.default_config.update(
            {
                cls.CONF_HUNTER_TARGET: cls.TARGET_SOUND_KING,
                cls.CONF_STAMINA_TARGET: 0,
            }
        )

        instance.config_type.update(
            {
                cls.CONF_HUNTER_TARGET: {
                    "type": "drop_down",
                    "options": cls.HUNTER_TARGETS,
                }
            }
        )
        instance.config_description.update(
            {
                cls.CONF_HUNTER_TARGET: "选择要挑战的异象追猎目标",
                cls.CONF_STAMINA_TARGET: "设置为0则使用当前全部体力；每次消耗60体力",
            }
        )

    def run(self):
        super().run()
        try:
            self.do_run()
        except TaskDisabledException:
            pass
        except Exception as e:
            self.log_error("AnomalyHunter Error", e)

    def do_run(self, config=None, stamina_target=None):
        if config is None:
            config = self.config

        target = self.normalize_target(config.get(self.CONF_HUNTER_TARGET, self.TARGET_SOUND_KING))
        target_idx = self.get_target_idx(target)
        stamina_target = self.get_stamina_target(config, stamina_target)
        self.info_set("追猎目标", target)
        self.log_info(f"开始异象追猎任务: {target}, 目标索引: {target_idx}")

        self.open_hunter_page()
        stamina = self.get_stamina()

        if stamina < self.TASK_COST:
            self.log_warning("体力不足，退出异象追猎任务", notify=True)
            return False

        stamina_units = stamina // self.TASK_COST
        if stamina_target > 0:
            target_units = (stamina_target + self.TASK_COST - 1) // self.TASK_COST
            stamina_units = min(stamina_units, target_units)
            self.info_set("体力消耗目标", stamina_target)

        if stamina_units <= 0:
            self.log_warning("没有可执行的异象追猎目标，退出任务", notify=True)
            return False

        self.info_set("计划次数", stamina_units)
        success_count = 0
        failed_count = 0
        consecutive_failures = 0
        attempt_count = 0
        while success_count < stamina_units:
            attempt_count += 1
            self.info_set("当前目标", target)
            self.info_set("当前次数", f"{success_count + 1} / {stamina_units}")
            self.info_set("尝试次数", attempt_count)
            self.log_info(f"准备挑战异象追猎目标: {target}")

            self.start_hunter_attempt(target, target_idx, reopen_page=attempt_count > 1)

            self.wait_in_team()
            self.sleep(1)
            if self.do_combat_and_claim():
                success_count += 1
                consecutive_failures = 0
            else:
                failed_count += 1
                consecutive_failures += 1
                self.log_warning(f"异象追猎连续失败 {consecutive_failures}/{self.MAX_CONSECUTIVE_FAILURES}")
                if consecutive_failures >= self.MAX_CONSECUTIVE_FAILURES:
                    self.log_warning("连续失败已达上限，将传送最近的电话亭传送点", notify=True)
                    break

            self.sleep(2)
            self.log_info("当前异象追猎任务完成！")

        self.log_info("异象追猎任务完成，尝试传送到最近的电话亭")
        self.sleep(1)
        self.click_nearest_map_teleport()
        self.sleep(2)
        self.log_warning(f"异象追猎执行结果: 成功次数={success_count}, 失败次数={failed_count}，共计消耗体力={success_count*self.TASK_COST}")
        return True

    def start_hunter_attempt(self, target: str, target_idx: int, reopen_page=False):
        target = self.normalize_target(target)
        if reopen_page:
            self.open_hunter_page()
        self.travel_to_hunter_target(target_idx)
        self.enter_hunter(target)

    def open_hunter_page(self):
        self.ensure_main()
        self.log_info("打开F1面板并切换至异象追猎页签")
        self.open_f1_domain_page()
        self.sleep(0.5)
        self.operate_click(self.HUNTER_TAB_X, self.HUNTER_TAB_Y)
        self.sleep(0.5)

    def get_stamina_target(self, config: dict, stamina_target=None) -> int:
        if stamina_target is None:
            stamina_target = config.get(self.CONF_STAMINA_TARGET, 0)
        try:
            return max(0, int(stamina_target))
        except (TypeError, ValueError):
            return 0

    def normalize_target(self, target: str) -> str:
        if target not in self.HUNTER_TARGETS:
            self.log_warning(f"未知追猎目标: {target}，默认执行第一个目标")
            return self.TARGET_SOUND_KING
        return target

    def get_target_idx(self, target: str):
        target = self.normalize_target(target)
        return self.HUNTER_TARGETS.index(target)

    def travel_to_hunter_target(self, target_idx: int):
        self.log_info(f"正在选择第 {target_idx} 个异象追猎目标并前往传送")
        page_idx = target_idx
        y_start = self.HUNTER_TRAVEL_Y_START
        if target_idx >= self.HUNTER_FIRST_PAGE_SIZE:
            self.turn_to_next_hunter_page()
            page_idx = target_idx - self.HUNTER_FIRST_PAGE_SIZE
            y_start = self.HUNTER_NEXT_PAGE_TRAVEL_Y_START

        y = y_start + page_idx * self.HUNTER_TRAVEL_Y_STEP
        self.operate_click(self.HUNTER_TRAVEL_X, y)
        self.click_traval_button()
        self.wait_in_team_and_world()

    def turn_to_next_hunter_page(self):
        self.log_info("异象追猎目标位于下一页，执行翻页")
        self.operate(
            lambda: self.scroll_relative(0.5, 0.5, -40),
            block=True,
        )
        self.sleep(0.5)

    def enter_hunter(self, target: str):
        if target in self.DIRECT_WALK_TARGETS:
            self.walk_forward_to_hunter()
            return

        if target == self.TARGET_HEADLESS_RIDER:
            direction = ("w", "d")
        elif target == self.TARGET_SPOTTED_BUTTERFLY:
            direction = ("s",)
        else:
            direction = ("w",)
        self.enter_hunter_from_interac(direction_keys=direction)

    def walk_forward_to_hunter(self):
        self.log_info("当前目标无需交互，向前寻路进入副本")
        entered = self.walk_until_hunter_entered(
            direction_keys=("w",), time_out=3, raise_if_not_found=False
        )
        if not entered:
            self.log_warning("向前寻路未确认进入状态，继续交给战斗流程处理")

    def enter_hunter_from_interac(self, direction_keys=("w",)):
        self.log_info("寻路至异象追猎交互点并进入副本")
        self.walk_until_interac_by_keys(direction_keys=direction_keys, raise_if_not_found=True)
        self.wait_until(
            lambda: not self.find_interac(),
            post_action=lambda: self.send_interac(handle_claim=False),
            time_out=5,
            settle_time=0.5,
        )

    def walk_until_interac_by_keys(self, direction_keys=("w",), time_out=10, raise_if_not_found=False):
        ret = False
        try:
            self.middle_click(after_sleep=0.2)
            for key in direction_keys:
                self.send_key_down(key)
            ret = bool(
                self.wait_until(
                    self.find_interac,
                    time_out=time_out,
                    raise_if_not_found=raise_if_not_found,
                )
            )
        finally:
            for key in direction_keys:
                self.send_key_up(key)
        return ret

    def walk_until_hunter_entered(self, direction_keys=("w",), time_out=10, raise_if_not_found=False):
        ret = False
        try:
            self.middle_click(after_sleep=0.2)
            for key in direction_keys:
                self.send_key_down(key)
            ret = bool(
                self.wait_until(
                    lambda: self.find_one(Labels.in_domain) or not self.is_in_team(),
                    time_out=time_out,
                    raise_if_not_found=raise_if_not_found,
                )
            )
        finally:
            for key in direction_keys:
                self.send_key_up(key)
        return ret

    def prepare_bosstreasure_search(self, middle_click_sleep=2):
        self.send_key("a", after_sleep=0.2)
        self.middle_click(after_sleep=middle_click_sleep)

    def find_bosstreasure_in_view(self):
        for feature_name in self.get_bosstreasure_features():
            result = self.find_one(
                feature_name=feature_name,
                box=self.main_viewport,
                threshold=self.BOSS_TREASURE_THRESHOLD,
                use_gray_scale=True,
            )
            if result:
                return result

    def find_bosstreasure_once(self):
        self.prepare_bosstreasure_search()
        return self.wait_until(
            self.find_bosstreasure_in_view,
            time_out=self.BOSS_TREASURE_ONCE_SEARCH_TIME,
            settle_time=0.2,
            raise_if_not_found=False,
        )

    def find_bosstreasure(self):
        for attempt in range(1, 5):
            self.log_warning(f"Boss宝箱查找次数：{attempt}/4")
            self.prepare_bosstreasure_search()
            result = self.find_bosstreasure_in_view()
            if result:
                return result

    def has_bosstreasure(self, check_once=False):
        finder = self.find_bosstreasure_once if check_once else self.find_bosstreasure
        return bool(finder())

    def walk_to_bosstreasure(self, check_once=False):
        if self.has_bosstreasure(check_once=check_once):
            self.log_warning("前往BOSS宝箱中")
            reached_interac = self.walk_to_box(
                self.find_bosstreasure_in_view,
                time_out=self.BOSS_TREASURE_WALK_TIMEOUT,
                end_condition=self.find_interac,
                y_offset=0.1,
                x_threshold=0.15,
            )
            if reached_interac:
                return True
            self.log_warning("前往BOSS宝箱超时，判定为失败")
        return False

    def get_bosstreasure_features(self):
        return list(self.DEFAULT_TREASURE_FEATURES)

    def is_claim_btn_ready(self):
        return self.find_confirm(
            box=self.main_viewport,
            threshold=0.7,
        )

    def exit_reward_interaction(self):
        self.send_key("esc")
        self.sleep(1)
        self.operate_click(0.609, 0.659, after_sleep=2)

    def do_combat_and_claim(self):
        pending_reward_ready = False
        self.log_info("战斗前检查是否有上次未领取的BOSS宝箱")
        pending_reward_ready = self.has_bosstreasure(check_once=True)
        self.send_key("d", after_sleep=0.2)
        self.middle_click(after_sleep=0.6)
        if pending_reward_ready:
            self.log_info("发现BOSS宝箱，跳过战斗")
        else:
            self.log_info("未发现BOSS宝箱，调用战斗模块")
            self.walk_until_combat(run=True, delay=1)
            self.combat_once()

        self.log_info("调用领取BOSS宝箱模块")
        claimed_reward = False

        def action(count):
            nonlocal pending_reward_ready, claimed_reward
            reward_found = bool(self.find_interac())
            if not reward_found:
                reward_found = self.walk_to_bosstreasure(check_once=pending_reward_ready)
            pending_reward_ready = False

            claimed_reward = bool(reward_found)
            if reward_found:
                self.log_info("发现宝箱，正在领取交互中")
                self.send_interac(handle_claim=False)
                if self.wait_until(self.is_claim_btn_ready, raise_if_not_found=False, time_out=5):
                    self.log_info("发现奖励领取页面，领取奖励")
                    # self.log_warning("测试提示：领取成功")
                    self.operate_click(0.609, 0.659, after_sleep=2)
                else:
                    claimed_reward = False
                    self.log_warning("未能进入领取奖励界面，退出当前环境交互中")
                    self.exit_reward_interaction()
            else:
                self.log_warning("领取奖励失败，退出当前环境交互中")
                self.exit_reward_interaction()
            return True

        if not self.retry_on_action(action):
            return False
        return claimed_reward
