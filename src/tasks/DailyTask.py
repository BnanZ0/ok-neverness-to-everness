import re
from datetime import datetime
from typing import Callable, List, Tuple

from ok import TaskDisabledException
from qfluentwidgets import FluentIcon

from src.Labels import Labels
from src.tasks.DailyActionGate import DailyActionGate
from src.tasks.DailyActivityModels import ActionGateSpec
from src.tasks.DailyActivityRegistry import resolve_activity_handler_rule
from src.tasks.AnomalyTask import AnomalyTask
from src.tasks.BaseNTETask import BaseNTETask
from src.tasks.DailyActivityAnalyzer import DailyActivityPage
from src.tasks.DailyActivityFlow import DailyActivityFlow
from src.tasks.DailyCoffeeRuntime import DailyCoffeeRuntime
from src.tasks.DailyTaskItemRunner import DailyTaskItemActionRunner
from src.tasks.F1PanelDetector import DailyPanelOpenResult
from src.tasks.FlowResult import FlowResult
from src.tasks.MailClaimFlow import MailClaimFlow
from src.tasks.NTEOneTimeTask import NTEOneTimeTask


class DailyTask(NTEOneTimeTask, BaseNTETask):
    """日常任务执行器"""

    # --- 配置项键名 ---
    CONF_CLAIM_MAIL = "领取邮件"
    CONF_COMPLETE_DAILY = "完成每日活跃度"
    CONF_CLAIM_ACTIVITY = "领取活跃度奖励"
    CONF_CLAIM_BP = "领取环期任务奖励"
    CONF_AUTO_CYCLE_SUB_TASK = "自动循环项目"
    DAILY_STAMINA_TARGET = 180

    DEFAULT_MOVE = True
    TASK_SKIPPED = object()
    DAILY_ACTIVITY_TAB_INDEX = DailyActivityFlow.DAILY_ACTIVITY_TAB_INDEX
    DAILY_ACTIVITY_TAB_POSITION = DailyActivityFlow.DAILY_ACTIVITY_TAB_POSITION
    ACTIVITY_TAB_POSITION = DAILY_ACTIVITY_TAB_POSITION
    MAIL_BUTTON_POSITION = (0.8707, 0.85)
    MAIL_BUTTON_RETRY_POSITION = (0.8707, 0.875)
    MAIL_ESC_SHORTCUT_REGION = (0.80, 0.02, 0.99, 0.16)
    MAIL_ESC_ICON_REGION = (0.935, 0.015, 0.99, 0.10)
    MAIL_ESC_SHORTCUT_ICON_OFFSET_RATIO = 0.045
    MAIL_ESC_SHORTCUT_CLICK_DOWN_TIME = 0.04
    MAIL_ESC_SHORTCUT_CLICK_SLEEP = 1.2
    MAIL_PHONE_MENU_BUTTON_DOWN_TIME = 0.08
    MAIL_PHONE_MENU_CLICK_SLEEP = 2.0
    MAIL_PHONE_MENU_MAIL_BUTTON_RATIO = (0.605, 0.90)
    MAIL_PHONE_MENU_MAIL_ICON_REGION = (0.50, 0.83, 0.72, 0.97)
    MAIL_PHONE_MENU_MAIL_ICON_THRESHOLD = 135
    MAIL_PHONE_MENU_MAIL_ICON_MIN_AREA = 160
    MAIL_PANEL_WAIT_TIMEOUT = 8
    BATTLE_PASS_REWARD_POSITION = (0.6934, 0.8229)
    BATTLE_PASS_MISSION_TAB_POSITION = (0.0570, 0.3451)
    BATTLE_PASS_REWARD_TAB_POSITION = (0.0570, 0.2333)
    BATTLE_PASS_MISSION_CLAIM_REGION = (0.70, 0.18, 0.96, 0.78)
    BATTLE_PASS_CLAIM_POSITION = (0.8777, 0.7195)
    BATTLE_PASS_REWARD_BUTTON_REGION = (0.50, 0.74, 0.83, 0.88)
    MAX_ACTIVITY_MISSION_CLAIMS = DailyActivityFlow.MAX_ACTIVITY_MISSION_CLAIMS
    MAX_ACTIVITY_CARD_SWIPES = DailyActivityFlow.MAX_ACTIVITY_CARD_SWIPES
    DAILY_ACTIVITY_CARD_SWIPE_START = DailyActivityFlow.DAILY_ACTIVITY_CARD_SWIPE_START
    DAILY_ACTIVITY_CARD_SWIPE_END = DailyActivityFlow.DAILY_ACTIVITY_CARD_SWIPE_END
    DAILY_ACTIVITY_CARD_SWIPE_START_X_IN_BOX = DailyActivityFlow.DAILY_ACTIVITY_CARD_SWIPE_START_X_IN_BOX
    DAILY_ACTIVITY_CARD_SWIPE_END_X_IN_BOX = DailyActivityFlow.DAILY_ACTIVITY_CARD_SWIPE_END_X_IN_BOX
    DAILY_ACTIVITY_CARD_SWIPE_Y_IN_BOX = DailyActivityFlow.DAILY_ACTIVITY_CARD_SWIPE_Y_IN_BOX
    DAILY_ACTIVITY_CARD_RIGHT_EDGE_LIMIT = DailyActivityFlow.DAILY_ACTIVITY_CARD_RIGHT_EDGE_LIMIT
    DAILY_ACTIVITY_MISSING_FEATURES = DailyActivityFlow.DAILY_ACTIVITY_MISSING_FEATURES
    ACTIVITY_REWARD_UNAVAILABLE = DailyActivityFlow.ACTIVITY_REWARD_UNAVAILABLE
    ACTIVITY_REWARD_DEFERRED_UNTIL_FULL = DailyActivityFlow.ACTIVITY_REWARD_DEFERRED_UNTIL_FULL
    ACTIVITY_SCORE_FULL = DailyActivityFlow.ACTIVITY_SCORE_FULL
    SIMPLE_ACTIVITY_ACTIONS = DailyActivityFlow.SIMPLE_ACTIVITY_ACTIONS
    ARC_ATTACK_ACTIVITY_KEY = DailyActivityFlow.ARC_ATTACK_ACTIVITY_KEY
    COFFEE_ACTIVITY_KEY = DailyActivityFlow.COFFEE_ACTIVITY_KEY
    COFFEE_ACTIVITY_KEYWORDS = DailyActivityFlow.COFFEE_ACTIVITY_KEYWORDS
    GIFT_ACTIVITY_KEY = DailyActivityFlow.GIFT_ACTIVITY_KEY
    GIFT_ACTIVITY_KEYWORDS = DailyActivityFlow.GIFT_ACTIVITY_KEYWORDS
    STRENGTHEN_ACTIVITY_KEY = DailyActivityFlow.STRENGTHEN_ACTIVITY_KEY
    STRENGTHEN_ACTIVITY_KEYWORDS = DailyActivityFlow.STRENGTHEN_ACTIVITY_KEYWORDS
    RESOURCE_ACTIVITY_KEYWORDS = DailyActivityFlow.RESOURCE_ACTIVITY_KEYWORDS
    UNSUPPORTED_ACTIVITY_REASON = DailyActivityFlow.UNSUPPORTED_ACTIVITY_REASON
    ACTIVITY_HANDLER_REGISTRY = DailyActivityFlow.ACTIVITY_HANDLER_REGISTRY

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "日常任务"
        self.description = "不支持从OK启动游戏"
        self.icon = FluentIcon.CAR
        self.support_schedule_task = False
        self.task_status = {"success": [], "failed": [], "skipped": [], "pending": []}
        self.task_skip_reasons = {}

        AnomalyTask.setup_config(self)
        self.default_config.update(
            {
                self.CONF_CLAIM_MAIL: True,
                self.CONF_CLAIM_BP: True,
                self.CONF_COMPLETE_DAILY: True,
                self.CONF_CLAIM_ACTIVITY: True,
                self.CONF_AUTO_CYCLE_SUB_TASK: False,
                "claim_partial_milestones": False,
                "coffee_max_supply_slots": 0,
                "coffee_supply_duration": "24小时",
                "coffee_product_scrolls": DailyCoffeeRuntime.COFFEE_PRODUCT_DEFAULT_SCAN_SCROLLS,
                "coffee_product_target_slots": 4,
                "coffee_dry_run": False,
                "gift_target_characters": "",
            }
        )
        self.config_description.update(
            {
                self.CONF_AUTO_CYCLE_SUB_TASK: "任务完成后自动切换至下一个项目",
            }
        )
        self.current_task_key = None
        self.add_exit_after_config()

    def run(self):
        super().run()
        try:
            self.do_run()
        except TaskDisabledException:
            pass
        except Exception as e:
            self._handle_exception(e)

    def do_run(self):
        """执行日常任务主流程"""
        self.log_info("开始执行日常任务")

        tasks: List[Tuple[str, Callable]] = [
            (self.CONF_COMPLETE_DAILY, self.complete_daily_activities),
            (self.CONF_CLAIM_MAIL, self.claim_mail),
            (self.CONF_CLAIM_ACTIVITY, self.claim_activity_rewards),
            (self.CONF_CLAIM_BP, self.claim_battle_pass_rewards),
        ]

        self._reset_task_status(tasks)

        for key, func in tasks:
            self.execute_task(key, func)

        self._ensure_daily_main()
        self._print_result()
        self.log_info("结束执行日常任务", notify=True)

    def execute_task(self, key, func):
        """执行单个子任务。

        Args:
            key (str): 任务名称
            func (Callable): 任务执行函数

        根据配置决定是否跳过，并记录执行结果。
        """

        self.task_status["pending"].remove(key)

        # 开关控制
        if not self.config.get(key, False):
            self._mark_skipped(key, "配置已关闭")
            return

        self.current_task_key = key
        self.log_info(f"开始任务: {key}")

        self._ensure_daily_main()

        result = func()
        flow_result = FlowResult.from_legacy(
            result,
            skipped_sentinel=self.TASK_SKIPPED,
            skip_reason=self.task_skip_reasons.get(key, ""),
        )

        if flow_result.failed:
            self.task_status["failed"].append(key)
            self.screenshot(f"fail_{key}")
            self.log_info(f"任务失败: {key}")
            self.current_task_key = None
            return

        if flow_result.skipped:
            self._mark_skipped(key, flow_result.reason or self.task_skip_reasons.get(key, ""))
            self.log_info(f"任务跳过: {key}")
            self.current_task_key = None
            return

        self.task_status["success"].append(key)
        self.log_info(f"任务完成: {key}")
        self.current_task_key = None

    def _reset_task_status(self, tasks):
        """重置任务状态。

        Args:
            tasks (list): [(key, func)] 任务列表
        """
        self.task_status = {
            "success": [],
            "failed": [],
            "skipped": [],
            "pending": [t[0] for t in tasks],
        }
        self.task_skip_reasons = {}

    def _set_skip_reason(self, key, reason):
        if reason:
            self.task_skip_reasons[key] = reason

    def _mark_skipped(self, key, reason=""):
        self.task_status["skipped"].append(key)
        self._set_skip_reason(key, reason)

    def _ensure_daily_main(self):
        """回到已登录的主界面，避免 DailyTask 误走登录页 OCR 检测。"""
        self.info_set("current task", "wait daily main esc=True")
        if self.wait_until(
            lambda: self.in_team_and_world() or self.handle_monthly_card(),
            time_out=30,
            raise_if_not_found=False,
            post_action=lambda: self.back(after_sleep=2),
        ):
            self._logged_in = True
            self.sleep(0.5)
            self.info_set("current task", "in daily main")
            return True

        raise Exception("Please start in game world and in team!")

    def _print_result(self):
        """输出任务执行结果。"""
        self.info_set("success", f"{self.task_status['success']}")
        self.info_set("failed", f"{self.task_status['failed']}")
        self.info_set("skipped", f"{self.task_status['skipped']}")
        if self.task_skip_reasons:
            self.info_set("skip_reasons", f"{self.task_skip_reasons}")

    def _handle_exception(self, e):
        """处理执行异常并记录状态。

        Args:
            e (Exception): 捕获到的异常
        """
        self.screenshot(f"{datetime.now().strftime('%Y%m%d')}_exception")

        if self.current_task_key:
            self.info_set("当前失败任务", self.current_task_key)
        self._print_result()
        raise e

    def claim_mail(self):
        """领取邮件"""
        return MailClaimFlow(self).claim()

    def _daily_activity_flow(self):
        override_map = {
            "_open_activity_panel_result": "open_activity_panel_result",
            "_analyze_daily_activity": "analyze_daily_activity",
            "_record_daily_activity_analysis": "record_daily_activity_analysis",
            "_execute_available_activity_handlers": "execute_available_activity_handlers",
            "_execute_available_activity_handlers_across_pages": "execute_available_activity_handlers_across_pages",
            "_swipe_daily_activity_cards": "swipe_daily_activity_cards",
            "_claim_completed_activity_card_rewards": "claim_completed_activity_card_rewards",
            "_record_remaining_activity_tasks": "record_remaining_activity_tasks",
            "_claim_activity_milestone_rewards": "claim_activity_milestone_rewards",
            "_close_activity_reward_popup": "close_activity_reward_popup",
        }
        method_overrides = {
            flow_name: self.__dict__[legacy_name]
            for legacy_name, flow_name in override_map.items()
            if callable(self.__dict__.get(legacy_name))
        }
        return DailyActivityFlow.from_task(
            self,
            registry=self.ACTIVITY_HANDLER_REGISTRY,
            skipped_sentinel=self.TASK_SKIPPED,
            method_overrides=method_overrides,
        )

    def _apply_daily_activity_flow_snapshot(self, flow: DailyActivityFlow):
        snapshot = flow.snapshot
        self._last_daily_activity_analysis = snapshot.analysis
        self._last_daily_activity_cards_claimed = int(snapshot.cards_claimed or 0)
        self._last_daily_activity_handlers_completed = bool(snapshot.handlers_completed)
        self._last_activity_reward_skip_reason = snapshot.reward_skip_reason
        self._last_daily_activity_result_details = flow.result_recorder.details()

    def _activity_flow_result_to_legacy(self, key, result: FlowResult, flow: DailyActivityFlow):
        self._apply_daily_activity_flow_snapshot(flow)
        details_by_key = getattr(self, "_last_daily_activity_flow_details", None)
        if not isinstance(details_by_key, dict):
            details_by_key = {}
            self._last_daily_activity_flow_details = details_by_key
        details_by_key[key] = result.to_dict()
        if result.skipped:
            self._set_skip_reason(key, result.reason)
        return result.to_legacy_value(skipped_sentinel=self.TASK_SKIPPED)

    def _activity_handler_flow_result_to_legacy(self, result):
        flow_result = FlowResult.from_legacy(
            result,
            skipped_sentinel=self.TASK_SKIPPED,
        )
        if flow_result.failed:
            return False
        if flow_result.skipped:
            return self.TASK_SKIPPED
        return True

    def _open_activity_panel(self):
        """打开 F1 每日活跃度面板。"""
        return self._daily_activity_flow().open_activity_panel()

    def _open_activity_panel_result(self):
        """打开 F1 每日第二栏目，并区分 F1 面板打开与每日页模板命中。"""
        return self._daily_activity_flow().open_activity_panel_result()

    def _record_daily_panel_open_result(self, result: DailyPanelOpenResult):
        return self._daily_activity_flow().record_daily_panel_open_result(result)

    def complete_daily_activities(self):
        """执行操作完成每日活跃度"""
        flow = self._daily_activity_flow()
        result = flow.complete_daily_activities()
        return self._activity_flow_result_to_legacy(self.CONF_COMPLETE_DAILY, result, flow)

    def _refresh_daily_activity_page_after_handlers(self):
        return self._daily_activity_flow().refresh_daily_activity_page_after_handlers()

    def _claim_completed_activity_cards_until_stable(self, page: DailyActivityPage):
        return self._daily_activity_flow().claim_completed_activity_cards_until_stable(page)

    def _analyze_daily_activity(self, panel_detected=None):
        return self._daily_activity_flow().analyze_daily_activity(panel_detected=panel_detected)

    def _record_daily_activity_analysis(self, analysis):
        flow = self._daily_activity_flow()
        result = flow.record_daily_activity_analysis(analysis)
        self._last_daily_activity_analysis = flow.snapshot.analysis
        return result

    def _completed_simple_activity_actions(self):
        """返回本轮已经执行过、可能贡献每日活跃度的简单动作。"""
        return self._daily_activity_flow().completed_simple_activity_actions()

    def _execute_available_activity_handlers(self, page: DailyActivityPage):
        """执行有明确安全 handler 的每日任务，不直接点击“前往”按钮。"""
        return self._daily_activity_flow().execute_available_activity_handlers(page)

    def _execute_available_activity_handlers_across_pages(self, first_page: DailyActivityPage):
        return self._daily_activity_flow().execute_available_activity_handlers_across_pages(first_page)

    def run_daily_task_items(self, *, dry_run=True):
        flow = self._daily_activity_flow()
        return DailyTaskItemActionRunner(flow, dry_run=dry_run).run()

    def _swipe_daily_activity_cards(self, page: DailyActivityPage | None = None):
        return self._daily_activity_flow().swipe_daily_activity_cards(page)

    def _daily_activity_card_swipe_points(self, page: DailyActivityPage | None = None):
        return self._daily_activity_flow().daily_activity_card_swipe_points(page)

    @staticmethod
    def _daily_activity_card_swipe_boxes(page: DailyActivityPage | None):
        return DailyActivityFlow.daily_activity_card_swipe_boxes(page)

    def _daily_activity_card_swipe_start_box(self, boxes):
        return self._daily_activity_flow().daily_activity_card_swipe_start_box(boxes)

    def _daily_activity_card_swipe_y(self, start_box, end_box):
        return self._daily_activity_flow().daily_activity_card_swipe_y(start_box, end_box)

    def _daily_activity_card_fallback_swipe_points(self):
        return self._daily_activity_flow().daily_activity_card_fallback_swipe_points()

    @staticmethod
    def _daily_activity_page_fingerprint(page: DailyActivityPage):
        return DailyActivityFlow.daily_activity_page_fingerprint(page)

    def _activity_handler_for_card(self, card):
        flow = self._daily_activity_flow()
        handler = flow.activity_handler_for_card(card)
        if handler is None:
            return None
        return getattr(self, handler.__name__)

    def _handle_coffee_activity(self, card):
        return self._activity_handler_flow_result_to_legacy(
            self._daily_activity_flow()._handle_coffee_activity(card)
        )

    def shift_idx(self, task):
        """切换任务索引"""
        if self.config.get(self.CONF_AUTO_CYCLE_SUB_TASK):
            if isinstance(task, AnomalyTask):
                task_type = self.config.get(task.CONF_TASK_TYPE)
                next_idx = task.get_next_sub_idx(self.config)
                if task_type == task.TASK_EXP_COIN:
                    self.config[task.CONF_EXP_TARGET] = task.EXP_ALL[next_idx]
                else:
                    conf_key = {
                        task.TASK_ABILITY: task.CONF_ABILITY_ID,
                        task.TASK_ARC: task.CONF_ARC_ID,
                        task.TASK_CONSOLE: task.CONF_CONSOLE_ID,
                    }.get(task_type)
                    if conf_key:
                        self.config[conf_key] = int(next_idx + 1)
            self.sync_config()

    def _handle_gift_activity(self, card):
        return self._activity_handler_flow_result_to_legacy(
            self._daily_activity_flow()._handle_gift_activity(card)
        )

    def _handle_strengthen_activity(self, card):
        return self._activity_handler_flow_result_to_legacy(
            self._daily_activity_flow()._handle_strengthen_activity(card)
        )

    def _handle_arc_attack_activity(self, card):
        return self._activity_handler_flow_result_to_legacy(
            self._daily_activity_flow()._handle_arc_attack_activity(card)
        )

    def _enter_activity_card(self, card, handler_name):
        return self._daily_activity_flow().enter_activity_card(card, handler_name)

    def _execute_activity_plan_actions(self, actions, handler_name):
        return self._daily_activity_flow().execute_activity_plan_actions(actions, handler_name)

    def _record_coffee_plan(self, plan):
        return self._daily_activity_flow().record_coffee_plan(plan)

    def _record_coffee_runtime_result(self, result):
        return self._daily_activity_flow().record_coffee_runtime_result(result)

    def _record_gift_plan(self, plan):
        return self._daily_activity_flow().record_gift_plan(plan)

    @classmethod
    def _activity_rule_for_title(cls, title):
        return resolve_activity_handler_rule(title, cls.ACTIVITY_HANDLER_REGISTRY)

    @classmethod
    def _activity_rule_for_key(cls, handler_key):
        for rule in cls.ACTIVITY_HANDLER_REGISTRY:
            if rule.handler_key == handler_key:
                return rule
        return None

    @classmethod
    def _activity_title_matches_handler(cls, title, handler_key):
        rule = cls._activity_rule_for_key(handler_key)
        return bool(rule and rule.matches(title))

    @classmethod
    def _is_coffee_activity_title(cls, title):
        return cls._activity_title_matches_handler(title, cls.COFFEE_ACTIVITY_KEY)

    @classmethod
    def _is_gift_activity_title(cls, title):
        return cls._activity_title_matches_handler(title, cls.GIFT_ACTIVITY_KEY)

    @classmethod
    def _is_strengthen_activity_title(cls, title):
        return cls._activity_title_matches_handler(title, cls.STRENGTHEN_ACTIVITY_KEY)

    def _coffee_max_supply_slots(self):
        return self._daily_activity_flow().coffee_max_supply_slots()

    def _coffee_supply_duration(self):
        return self._daily_activity_flow().coffee_supply_duration()

    def _gift_target_names(self):
        return self._daily_activity_flow().gift_target_names()

    @staticmethod
    def _activity_required_remaining(card, default=1):
        return DailyActivityFlow.activity_required_remaining(card, default=default)

    def _record_remaining_activity_tasks(self, page: DailyActivityPage):
        return self._daily_activity_flow().record_remaining_activity_tasks(page)

    def _remaining_activity_tasks(self, page: DailyActivityPage):
        return self._daily_activity_flow().remaining_activity_tasks(page)

    def _activity_block_reason(self, title):
        return self._daily_activity_flow().activity_block_reason(title)

    @staticmethod
    def _activity_card_title(card):
        return DailyActivityFlow.activity_card_title(card)

    def _claim_completed_activity_card_rewards(self, page: DailyActivityPage, max_clicks=1):
        """领取当前页已完成任务卡片的奖励，不点击“前往”或顶部阶段奖励。"""
        return self._daily_activity_flow().claim_completed_activity_card_rewards(page, max_clicks=max_clicks)

    def claim_activity_rewards(self):
        """领取活跃度奖励"""
        flow = self._daily_activity_flow()
        result = flow.claim_activity_rewards()
        return self._activity_flow_result_to_legacy(self.CONF_CLAIM_ACTIVITY, result, flow)

    def _claim_activity_milestone_rewards(self, page: DailyActivityPage | None):
        flow = self._daily_activity_flow()
        result = flow.claim_activity_milestone_rewards(page)
        self._last_activity_reward_skip_reason = flow.snapshot.reward_skip_reason
        return result

    def _close_activity_reward_popup(self):
        return self._daily_activity_flow().close_activity_reward_popup()

    def _should_claim_activity_milestones(self, page: DailyActivityPage):
        return self._daily_activity_flow().should_claim_activity_milestones(page)

    def _claim_partial_milestones_enabled(self):
        return self._daily_activity_flow().claim_partial_milestones_enabled()

    def claim_battle_pass_rewards(self):
        """领取环期任务奖励"""
        self.log_info("正在领取环期任务奖励")
        self.openF2panel()
        self.click_ui(*self.BATTLE_PASS_MISSION_TAB_POSITION)
        if not self._wait_battle_pass_mission_panel():
            self.log_error("无法找到环期任务面板")
            return False
        mission_result = self._claim_visible_battle_pass_mission_rewards()
        self._open_battle_pass_reward_track()
        reward_result = self._claim_battle_pass_unlocked_rewards()
        mission_claim_attempts = int(mission_result.get("claimed") or 0)
        reward_claimed = bool(reward_result.get("claimed"))
        claimed = bool(mission_claim_attempts or reward_claimed)
        failure_reason = str(mission_result.get("failure_reason") or reward_result.get("failure_reason") or "")
        ok = not failure_reason
        return {
            "ok": ok,
            "claimed": claimed,
            "mission_claim_attempts": mission_claim_attempts,
            "reward_claimed": reward_claimed,
            "skipped": not claimed,
            "reason": failure_reason or ("" if claimed else "no_claimable_periodic_reward"),
            "mutation_performed": bool(
                mission_result.get("mutation_performed") or reward_result.get("mutation_performed")
            ),
            "mutation_verified": bool(
                mission_result.get("mutation_verified") or reward_result.get("mutation_verified")
            ),
            "action_failed": bool(failure_reason),
            "details": {
                "mission": mission_result,
                "reward_track": reward_result,
            },
        }

    def _claim_visible_battle_pass_mission_rewards(self):
        attempts = 0
        gate_results = []
        while attempts < self.MAX_ACTIVITY_MISSION_CLAIMS:
            target = self._find_battle_pass_text_box("领取", self.BATTLE_PASS_MISSION_CLAIM_REGION)
            if target is None:
                break
            gate_result = self._execute_battle_pass_claim_gate(
                target,
                needle="领取",
                region=self.BATTLE_PASS_MISSION_CLAIM_REGION,
                post_verification="battle_pass_mission_claim_button_vanished",
            )
            gate_results.append(gate_result.to_details())
            if not gate_result.allowed:
                self.info_set("环期任务领取失败", gate_result.reject_reason)
                return {
                    "claimed": attempts,
                    "mutation_performed": False,
                    "mutation_verified": False,
                    "failure_reason": gate_result.reject_reason,
                    "gate_results": gate_results,
                }
            if not gate_result.verified:
                reason = gate_result.failure_reason or "battle_pass_mission_claim_unverified"
                self.info_set("环期任务领取失败", reason)
                return {
                    "claimed": attempts,
                    "mutation_performed": True,
                    "mutation_verified": False,
                    "failure_reason": reason,
                    "gate_results": gate_results,
                }
            attempts += 1
        self.info_set("环期任务页领取点击数", str(attempts))
        return {
            "claimed": attempts,
            "mutation_performed": bool(attempts),
            "mutation_verified": bool(attempts),
            "failure_reason": "",
            "gate_results": gate_results,
        }

    def _open_battle_pass_reward_track(self):
        self.click_ui(*self.BATTLE_PASS_REWARD_TAB_POSITION)
        self.sleep(0.5)

    def _claim_battle_pass_unlocked_rewards(self):
        target = self._find_battle_pass_text_box("全部领取", self.BATTLE_PASS_REWARD_BUTTON_REGION)
        if target is not None:
            gate_result = self._execute_battle_pass_claim_gate(
                target,
                needle="全部领取",
                region=self.BATTLE_PASS_REWARD_BUTTON_REGION,
                post_verification="battle_pass_reward_all_claim_button_vanished",
                sleep_seconds=1,
            )
            if gate_result.verified:
                return {
                    "claimed": True,
                    "mutation_performed": True,
                    "mutation_verified": True,
                    "failure_reason": "",
                    "gate_results": [gate_result.to_details()],
                }
            reason = gate_result.reject_reason or gate_result.failure_reason or "battle_pass_reward_claim_unverified"
            self.info_set("环期轨道奖励领取失败", reason)
            return {
                "claimed": False,
                "mutation_performed": bool(gate_result.mutation_performed),
                "mutation_verified": False,
                "failure_reason": reason,
                "gate_results": [gate_result.to_details()],
            }

        self.info_set("环期轨道奖励领取", "未识别到全部领取，跳过")
        return {
            "claimed": False,
            "mutation_performed": False,
            "mutation_verified": False,
            "failure_reason": "",
            "gate_results": [],
        }

    def _execute_battle_pass_claim_gate(self, target, *, needle, region, post_verification, sleep_seconds=0.5):
        screenshot_id = self._next_battle_pass_screenshot_id("battle_pass")
        spec = ActionGateSpec(
            recognized_ui=str(getattr(target, "name", "") or needle),
            confidence=float(getattr(target, "confidence", 1.0) or 0.0),
            screenshot_id=screenshot_id,
            evidence_box=target,
            target_policy="center",
            min_confidence=0.8,
            post_verification=post_verification,
        )
        gate = DailyActionGate(
            viewport_width=self._battle_pass_viewport_width(),
            viewport_height=self._battle_pass_viewport_height(),
            current_screenshot_id=screenshot_id,
        )
        return gate.execute_click(
            spec,
            self,
            verifier=lambda result: self._verify_battle_pass_claim_after_click(
                target,
                needle=needle,
                region=region,
                sleep_seconds=sleep_seconds,
            ),
        )

    def _verify_battle_pass_claim_after_click(self, before_box, *, needle, region, sleep_seconds):
        self.sleep(sleep_seconds)
        next_frame = getattr(self, "next_frame", None)
        if callable(next_frame):
            try:
                next_frame()
            except Exception:
                pass
        after_box = self._find_battle_pass_text_box(needle, region)
        verified = not self._same_gate_box(before_box, after_box)
        return verified, self._next_battle_pass_screenshot_id("battle_pass_after")

    def _next_battle_pass_screenshot_id(self, prefix):
        counter = int(getattr(self, "_battle_pass_gate_counter", 0) or 0) + 1
        self._battle_pass_gate_counter = counter
        return f"{prefix}-{counter}"

    def _battle_pass_viewport_width(self):
        width = int(getattr(self, "width", 0) or 0)
        if width:
            return width
        shape = getattr(getattr(self, "frame", None), "shape", None)
        return int(shape[1]) if shape is not None and len(shape) >= 2 else 0

    def _battle_pass_viewport_height(self):
        height = int(getattr(self, "height", 0) or 0)
        if height:
            return height
        shape = getattr(getattr(self, "frame", None), "shape", None)
        return int(shape[0]) if shape is not None and len(shape) >= 2 else 0

    @staticmethod
    def _same_gate_box(left, right, tolerance=12):
        if left is None or right is None:
            return False
        left_center = (
            int(getattr(left, "x", 0) or 0) + int(getattr(left, "width", 0) or 0) / 2,
            int(getattr(left, "y", 0) or 0) + int(getattr(left, "height", 0) or 0) / 2,
        )
        right_center = (
            int(getattr(right, "x", 0) or 0) + int(getattr(right, "width", 0) or 0) / 2,
            int(getattr(right, "y", 0) or 0) + int(getattr(right, "height", 0) or 0) / 2,
        )
        return (
            abs(left_center[0] - right_center[0]) <= tolerance
            and abs(left_center[1] - right_center[1]) <= tolerance
        )

    def _find_battle_pass_text_box(self, needle, region):
        for box in self._battle_pass_ocr_region(region):
            if self._battle_pass_claim_text_matches(self._battle_pass_box_text(box), needle):
                return box
        return None

    @staticmethod
    def _battle_pass_claim_text_matches(text, needle):
        normalized = re.sub(r"\s+", "", str(text or ""))
        expected = re.sub(r"\s+", "", str(needle or ""))
        if not normalized or not expected:
            return False
        if "已领取" in normalized or "已全部领取" in normalized:
            return False
        if expected == "领取":
            return normalized in {"领取", "领取奖励"}
        if expected == "全部领取":
            return normalized == "全部领取"
        return normalized == expected

    def _battle_pass_ocr_region(self, region):
        try:
            result = self.ocr_ui(*region, frame=self.frame)
        except Exception:
            return []
        if result is None or isinstance(result, (str, bytes)):
            return []
        try:
            return list(result)
        except TypeError:
            return []

    @staticmethod
    def _battle_pass_box_text(box):
        text = getattr(box, "text", None)
        return str(text if text else getattr(box, "name", "")).strip()

    def _wait_battle_pass_mission_panel(self):
        result = self.wait_until(
            self._find_battle_pass_mission_panel,
            time_out=4.5,
            settle_time=0,
        )
        if result:
            self.log_info(f"found battle pass mission panel {result}")
        return result

    def _find_battle_pass_mission_panel(self):
        result = self.find_one(Labels.f2_mission_panel)
        if result:
            return result
        return self._find_battle_pass_mission_panel_structure()

    def _find_battle_pass_mission_panel_structure(self):
        try:
            frame = self.frame
        except Exception:
            return None

        shape = getattr(frame, "shape", None)
        if shape is None or len(shape) < 2:
            return None

        height, width = shape[:2]
        if height <= 0 or width <= 0:
            return None

        x1, y1 = int(width * 0.17), int(height * 0.27)
        x2, y2 = int(width * 0.34), int(height * 0.39)
        selected_card = frame[y1:y2, x1:x2]
        if selected_card.size == 0:
            return None

        pink_ratio = self._hsv_pixel_ratio(
            selected_card,
            hue_min=140,
            hue_max=175,
            saturation_min=80,
            value_min=120,
        )
        if pink_ratio < 0.03:
            return None

        return self.box_of_ui(
            0.16,
            0.25,
            to_x=0.95,
            to_y=0.78,
            name="f2_mission_panel_structure",
            confidence=min(1.0, pink_ratio * 4),
        )
