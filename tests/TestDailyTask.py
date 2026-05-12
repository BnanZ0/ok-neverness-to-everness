import inspect
import unittest
from unittest.mock import Mock, PropertyMock, call, patch

import numpy as np
from ok import CannotFindException

from src.Labels import Labels
from src.tasks.DailyActivityAnalyzer import (
    DailyActivityAnalysis,
    DailyActivityPage,
    DailyActivityState,
    DailyMilestoneReward,
    DailyTaskCard,
    RegionBox,
)
from src.tasks.BaseNTETask import BaseNTETask
from src.tasks.DailyCoffeePlanner import CoffeeFoodOption, CoffeeShopState, CoffeeSupplySlot
from src.tasks.DailyActivityFlow import DailyActivityFlow
from src.tasks.DailyGiftPlanner import DailyGiftPlanner, GiftCharacter, GiftOption, GiftPanelState
from src.tasks.DailyTask import DailyTask
from src.tasks.F1PanelDetector import DailyPanelOpenResult
from src.tasks.FlowResult import FlowResult
from src.tasks.MailClaimFlow import MailClaimFlow


def make_analysis(
    state=DailyActivityState.UNKNOWN,
    reason="缺少未完成/前往按钮/可领取状态特征",
    page=None,
):
    return DailyActivityAnalysis(
        state=state,
        panel_detected=state != DailyActivityState.PANEL_NOT_FOUND,
        daily_tab_detected=state != DailyActivityState.PANEL_NOT_FOUND,
        activity_full=state == DailyActivityState.NO_ACTION_NEEDED,
        all_daily_done=state == DailyActivityState.NO_ACTION_NEEDED,
        has_go_button=False,
        has_claimable_reward=state == DailyActivityState.HAS_CLAIMABLE_REWARD,
        no_claimable_reward=state != DailyActivityState.HAS_CLAIMABLE_REWARD,
        reason=reason,
        page=page,
    )


def make_open_result(detected=True, reason="每日活跃度面板已识别"):
    return DailyPanelOpenResult(
        f1_panel_opened=True,
        daily_tab_clicked=True,
        daily_activity_panel_detected=detected,
        layout_profile="native_16_9",
        reason=reason,
    )


class TestDailyTask(unittest.TestCase):
    def make_task(self):
        task = object.__new__(DailyTask)
        task.config = {"测试任务": True}
        task.task_status = {
            "success": [],
            "failed": [],
            "skipped": [],
            "pending": ["测试任务"],
        }
        task.current_task_key = None
        task.task_skip_reasons = {}
        task._ensure_daily_main = Mock()
        task.screenshot = Mock()
        task.log_info = Mock()
        return task

    def make_fake_activity_flow(self, *, complete_result=None, claim_result=None):
        flow = Mock()
        flow.snapshot.analysis = None
        flow.snapshot.cards_claimed = 0
        flow.snapshot.handlers_completed = False
        flow.snapshot.reward_skip_reason = ""
        flow.complete_daily_activities.return_value = complete_result
        flow.claim_activity_rewards.return_value = claim_result
        return flow

    def test_execute_task_records_runtime_skip(self):
        task = self.make_task()

        task.execute_task("测试任务", Mock(return_value=DailyTask.TASK_SKIPPED))

        self.assertEqual(task.task_status["success"], [])
        self.assertEqual(task.task_status["failed"], [])
        self.assertEqual(task.task_status["skipped"], ["测试任务"])
        self.assertEqual(task.task_status["pending"], [])
        self.assertIsNone(task.current_task_key)

    def test_execute_task_records_flow_result_skip_reason(self):
        task = self.make_task()

        task.execute_task("测试任务", Mock(return_value=FlowResult.skip("no work")))

        self.assertEqual(task.task_status["skipped"], ["测试任务"])
        self.assertEqual(task.task_skip_reasons["测试任务"], "no work")
        self.assertIsNone(task.current_task_key)

    def test_execute_task_resets_current_task_after_failure(self):
        task = self.make_task()

        task.execute_task("测试任务", Mock(return_value=False))

        self.assertEqual(task.task_status["failed"], ["测试任务"])
        self.assertIsNone(task.current_task_key)
        task.screenshot.assert_called_once_with("fail_测试任务")

    def test_execute_task_treats_failed_result_dict_as_failure(self):
        task = self.make_task()

        task.execute_task("测试任务", Mock(return_value={"ok": False, "reason": "failed"}))

        self.assertEqual(task.task_status["failed"], ["测试任务"])
        self.assertIsNone(task.current_task_key)
        task.screenshot.assert_called_once_with("fail_测试任务")

    def test_execute_task_treats_skipped_result_dict_as_skip(self):
        task = self.make_task()

        task.execute_task(
            "测试任务",
            Mock(return_value={"ok": True, "skipped": True, "reason": "no claimable"}),
        )

        self.assertEqual(task.task_status["skipped"], ["测试任务"])
        self.assertEqual(task.task_skip_reasons["测试任务"], "no claimable")

    def test_daily_task_activity_entrypoints_preserve_legacy_return_shapes(self):
        cases = [
            (FlowResult.success("done"), True),
            (FlowResult.fail("failed"), False),
            (FlowResult.skip("skipped"), DailyTask.TASK_SKIPPED),
        ]
        for flow_result, expected in cases:
            with self.subTest(expected=expected):
                task = object.__new__(DailyTask)
                task.task_skip_reasons = {}
                flow = self.make_fake_activity_flow(complete_result=flow_result)
                with patch("src.tasks.DailyTask.DailyActivityFlow.from_task", return_value=flow):
                    result = DailyTask.complete_daily_activities(task)
                self.assertIs(result, expected)

        payload = {"ok": True, "custom": "preserved"}
        task = object.__new__(DailyTask)
        task.task_skip_reasons = {}
        flow = self.make_fake_activity_flow(
            complete_result=FlowResult.success("dict", legacy_return=payload)
        )
        with patch("src.tasks.DailyTask.DailyActivityFlow.from_task", return_value=flow):
            result = DailyTask.complete_daily_activities(task)
        self.assertIs(result, payload)

    def test_daily_task_claim_activity_entrypoint_preserves_legacy_returns(self):
        task = object.__new__(DailyTask)
        task.task_skip_reasons = {}
        flow = self.make_fake_activity_flow(claim_result=FlowResult.fail("claim failed"))

        with patch("src.tasks.DailyTask.DailyActivityFlow.from_task", return_value=flow):
            result = DailyTask.claim_activity_rewards(task)

        self.assertFalse(result)
        flow.claim_activity_rewards.assert_called_once_with()

    def test_complete_daily_activities_skips_when_no_claimable_mission(self):
        task = object.__new__(DailyTask)
        task._open_activity_panel_result = Mock(return_value=make_open_result())
        task._analyze_daily_activity = Mock(return_value=make_analysis())
        task._record_daily_activity_analysis = Mock()
        task._execute_available_activity_handlers_across_pages = Mock(return_value=False)
        task._claim_completed_activity_card_rewards = Mock(return_value=0)
        task._record_remaining_activity_tasks = Mock(return_value=[])
        task.task_status = {"success": []}
        task.task_skip_reasons = {}
        task.info_set = Mock()
        task.log_info = Mock()

        result = DailyTask.complete_daily_activities(task)

        self.assertIs(result, DailyTask.TASK_SKIPPED)
        task.info_set.assert_called_once_with(
            "每日活跃度缺失特征",
            DailyTask.DAILY_ACTIVITY_MISSING_FEATURES,
        )
        self.assertEqual(
            task.task_skip_reasons["完成每日活跃度"],
            "缺少未完成/前往按钮/可领取状态特征",
        )

    def test_complete_daily_activities_skips_when_activity_done_by_analysis(self):
        task = object.__new__(DailyTask)
        task._open_activity_panel_result = Mock(return_value=make_open_result())
        task._analyze_daily_activity = Mock(
            return_value=make_analysis(DailyActivityState.NO_ACTION_NEEDED, "今日活跃度已完成")
        )
        task._record_daily_activity_analysis = Mock()
        task.task_skip_reasons = {}
        task.info_set = Mock()
        task.log_info = Mock()

        result = DailyTask.complete_daily_activities(task)

        self.assertIs(result, DailyTask.TASK_SKIPPED)
        self.assertEqual(task.task_skip_reasons["完成每日活跃度"], "今日活跃度已完成")
        task.log_info.assert_any_call("今日活跃度已完成")

    def test_open_activity_panel_clicks_daily_second_tab(self):
        task = object.__new__(DailyTask)
        task.openF1panel = Mock()
        task.click = Mock()
        task.click_ui = Mock()
        task.find_one = Mock(return_value=object())
        task.get_ui_layout_profile = Mock(return_value="native_16_9")
        task._executor = Mock(method=Mock(width=1920, height=1080))
        task.info_set = Mock()
        task.log_info = Mock()

        result = DailyTask._open_activity_panel(task)

        self.assertTrue(result)
        task.info_set.assert_any_call("每日活跃度目标栏目", "第2栏目")
        task.click.assert_called_once_with(105, 410)
        task.click_ui.assert_not_called()
        self.assertAlmostEqual(DailyActivityFlow.NATIVE_16_9_DAILY_ACTIVITY_TAB_POSITION[1], 0.3810)

    def test_open_activity_panel_keeps_native_16_10_daily_second_tab_ratio(self):
        task = object.__new__(DailyTask)
        task.openF1panel = Mock()
        task.click = Mock()
        task.click_ui = Mock()
        task.find_one = Mock(return_value=object())
        task.get_ui_layout_profile = Mock(return_value="native_16_10")
        task._executor = Mock(method=Mock(width=2560, height=1600))
        task.info_set = Mock()
        task.log_info = Mock()

        result = DailyTask._open_activity_panel(task)

        self.assertTrue(result)
        task.click.assert_called_once_with(141, 524)
        self.assertAlmostEqual(DailyTask.DAILY_ACTIVITY_TAB_POSITION[1], 0.3275)

    def test_complete_daily_activities_reports_completed_simple_actions(self):
        task = object.__new__(DailyTask)
        task._open_activity_panel_result = Mock(return_value=make_open_result())
        task._analyze_daily_activity = Mock(return_value=make_analysis())
        task._record_daily_activity_analysis = Mock()
        task._execute_available_activity_handlers_across_pages = Mock(return_value=False)
        task._claim_completed_activity_card_rewards = Mock(return_value=0)
        task._record_remaining_activity_tasks = Mock(return_value=[])
        task.task_status = {"success": ["领取邮件", "领取环期任务奖励"]}
        task.task_skip_reasons = {}
        task.info_set = Mock()
        task.log_info = Mock()

        result = DailyTask.complete_daily_activities(task)

        self.assertIs(result, DailyTask.TASK_SKIPPED)
        task.info_set.assert_has_calls(
            [
                call("每日活跃度已尝试动作", "领取邮件/领取环期任务奖励"),
                call("每日活跃度缺失特征", DailyTask.DAILY_ACTIVITY_MISSING_FEATURES),
            ]
        )

    def test_complete_daily_activities_does_not_blind_click_go_buttons(self):
        go_box = RegionBox("daily_activity_go_button", 720, 820, 220, 54)
        page = DailyActivityPage(
            activity_score=90,
            task_cards=[
                DailyTaskCard(title="累计消耗180点本性像素", action="前往", action_box=go_box),
                DailyTaskCard(title="赠送1次礼物", action="前往", action_box=go_box),
                DailyTaskCard(title="提升1次孤岛等级", action="前往", action_box=go_box),
            ],
            go_buttons=[go_box],
        )
        task = object.__new__(DailyTask)
        task._open_activity_panel_result = Mock(return_value=make_open_result())
        task._analyze_daily_activity = Mock(return_value=make_analysis(page=page))
        task._record_daily_activity_analysis = Mock()
        task.click = Mock()
        task.task_status = {"success": []}
        task.task_skip_reasons = {}
        task.info_set = Mock()
        task.log_info = Mock()

        result = DailyTask.complete_daily_activities(task)

        self.assertIs(result, DailyTask.TASK_SKIPPED)
        task.click.assert_not_called()
        task.info_set.assert_any_call(
            "剩余未自动完成每日任务",
            "累计消耗180点本性像素: 资源消耗类任务默认不自动；"
            "赠送1次礼物: 未配置赠礼目标角色，跳过赠礼；"
            "提升1次孤岛等级: 强化类任务仅允许单次明确安全动作；当前缺少稳定识别，未消耗材料",
        )

    def test_claim_completed_activity_card_rewards_clicks_only_claim_cards(self):
        first_claim = RegionBox(Labels.f1_activity_mission.value, 360, 830, 220, 54)
        second_claim = RegionBox(Labels.f1_activity_mission.value, 700, 830, 220, 54)
        go_box = RegionBox("daily_activity_go_button", 1040, 830, 220, 54)
        after_page = DailyActivityPage(
            task_cards=[
                DailyTaskCard(title="累计消耗10点都市活力", action="领取", action_box=second_claim),
                DailyTaskCard(title="赠送1次礼物", action="前往", action_box=go_box),
            ],
            mission_claim_buttons=[second_claim],
            go_buttons=[go_box],
        )
        page = DailyActivityPage(
            task_cards=[
                DailyTaskCard(title="释放3次极轨攻击", action="领取", action_box=first_claim),
                DailyTaskCard(title="累计消耗10点都市活力", action="领取", action_box=second_claim),
                DailyTaskCard(title="赠送1次礼物", action="前往", action_box=go_box),
            ],
            mission_claim_buttons=[first_claim, second_claim],
            go_buttons=[go_box],
        )
        task = object.__new__(DailyTask)
        task._executor = Mock(method=Mock(width=2560, height=1440))
        task.click = Mock()
        task.sleep = Mock()
        task.next_frame = Mock()
        task._analyze_daily_activity = Mock(return_value=make_analysis(page=after_page))
        task.info_set = Mock()
        task.log_info = Mock()

        claimed = DailyTask._claim_completed_activity_card_rewards(task, page)

        self.assertEqual(claimed, 1)
        task.click.assert_called_once_with(470, 857)
        self.assertEqual(task.sleep.call_count, 1)

    def test_complete_daily_activities_reanalyzes_after_claiming_cards_at_end(self):
        claim_box = RegionBox(Labels.f1_activity_mission.value, 360, 830, 220, 54)
        first_page = DailyActivityPage(
            activity_score=90,
            task_cards=[
                DailyTaskCard(title="释放3次极轨攻击", action="领取", action_box=claim_box),
            ],
            mission_claim_buttons=[claim_box],
        )
        refreshed_page = DailyActivityPage(
            activity_score=100,
            task_cards=[],
            milestone_rewards=[
                DailyMilestoneReward(
                    100,
                    RegionBox("daily_activity_milestone_100", 1640, 220, 70, 70),
                    claimable=True,
                    locked=False,
                ),
            ],
        )
        first_analysis = make_analysis(
            DailyActivityState.HAS_CLAIMABLE_REWARD,
            "检测到可领取每日任务奖励",
            first_page,
        )
        refreshed_analysis = make_analysis(page=refreshed_page)
        task = object.__new__(DailyTask)
        task._open_activity_panel_result = Mock(return_value=make_open_result())
        task._analyze_daily_activity = Mock(side_effect=[first_analysis, refreshed_analysis])
        task._record_daily_activity_analysis = Mock()
        task._claim_completed_activity_card_rewards = Mock(side_effect=[1, 0])
        task._claim_activity_milestone_rewards = Mock(return_value=True)
        task._execute_available_activity_handlers_across_pages = Mock(return_value=False)
        task._record_remaining_activity_tasks = Mock(return_value=[])
        task.task_status = {"success": []}
        task.task_skip_reasons = {}
        task.info_set = Mock()
        task.log_info = Mock()

        result = DailyTask.complete_daily_activities(task)

        self.assertTrue(result)
        self.assertEqual(task._analyze_daily_activity.call_count, 2)
        self.assertEqual(task._claim_completed_activity_card_rewards.call_args_list[0], call(first_page))
        task._record_daily_activity_analysis.assert_has_calls(
            [
                call(first_analysis),
                call(refreshed_analysis),
            ]
        )
        task._record_remaining_activity_tasks.assert_called_once_with(refreshed_page)
        task._claim_activity_milestone_rewards.assert_not_called()
        task._execute_available_activity_handlers_across_pages.assert_called_once_with(first_page)

    def test_complete_daily_activities_runs_handlers_before_claiming_cards(self):
        claim_box = RegionBox(Labels.f1_activity_mission.value, 360, 830, 220, 54)
        go_box = RegionBox("daily_activity_go_button", 720, 820, 220, 54)
        first_page = DailyActivityPage(
            activity_score=90,
            task_cards=[
                DailyTaskCard(title="累计消耗10点都市活力", action="前往", action_box=go_box),
                DailyTaskCard(title="每日登录1次", action="领取", action_box=claim_box),
            ],
            mission_claim_buttons=[claim_box],
            go_buttons=[go_box],
        )
        refreshed_page = DailyActivityPage(
            activity_score=100,
            task_cards=[
                DailyTaskCard(title="每日登录1次", action="领取", action_box=claim_box),
            ],
            mission_claim_buttons=[claim_box],
        )
        after_claim_page = DailyActivityPage(activity_score=100, task_cards=[])
        first_analysis = make_analysis(
            DailyActivityState.HAS_CLAIMABLE_REWARD,
            "检测到可领取每日任务奖励",
            first_page,
        )
        refreshed_analysis = make_analysis(page=refreshed_page)
        after_claim_analysis = make_analysis(page=after_claim_page)
        order = []

        task = object.__new__(DailyTask)
        task._open_activity_panel_result = Mock(return_value=make_open_result())
        task._analyze_daily_activity = Mock(side_effect=[first_analysis, refreshed_analysis, after_claim_analysis])
        task._record_daily_activity_analysis = Mock()
        task._execute_available_activity_handlers_across_pages = Mock(
            side_effect=lambda page: order.append("handler") or True
        )

        def claim_completed(page):
            if page is refreshed_page:
                order.append("claim")
                return 1
            return 0

        task._claim_completed_activity_card_rewards = Mock(side_effect=claim_completed)
        task._record_remaining_activity_tasks = Mock(return_value=[])
        task.task_status = {"success": []}
        task.task_skip_reasons = {}
        task.info_set = Mock()
        task.log_info = Mock()

        result = DailyTask.complete_daily_activities(task)

        self.assertTrue(result)
        self.assertEqual(order, ["handler", "claim"])
        self.assertEqual(task._open_activity_panel_result.call_count, 2)

    def test_complete_daily_activities_records_arc_attack_handler_without_combat(self):
        go_box = RegionBox("daily_activity_go_button", 720, 820, 220, 54)
        page = DailyActivityPage(
            activity_score=90,
            task_cards=[
                DailyTaskCard(title="释放3次极轨攻击", action="前往", action_box=go_box),
            ],
            go_buttons=[go_box],
        )
        task = object.__new__(DailyTask)
        task._open_activity_panel_result = Mock(return_value=make_open_result())
        task._analyze_daily_activity = Mock(return_value=make_analysis(page=page))
        task._record_daily_activity_analysis = Mock()
        task.click = Mock()
        task.task_status = {"success": []}
        task.task_skip_reasons = {}
        task.info_set = Mock()
        task.log_info = Mock()

        result = DailyTask.complete_daily_activities(task)

        self.assertIs(result, DailyTask.TASK_SKIPPED)
        task.click.assert_not_called()
        task.info_set.assert_any_call(
            "每日活动handler",
            "释放3次极轨攻击: 释放3次极轨攻击需要战斗场景和目标确认，当前仅记录 handler，不自动战斗",
        )
        task.info_set.assert_any_call(
            "剩余未自动完成每日任务",
            "释放3次极轨攻击: 释放3次极轨攻击需要战斗场景和目标确认，当前仅记录 handler，不自动战斗",
        )

    def test_activity_handler_routes_strategic_daily_titles(self):
        task = object.__new__(DailyTask)

        coffee = DailyTaskCard(title="累计消耗10点都市活力", action="前往")
        gift = DailyTaskCard(title="赠送1次礼物", action="前往")
        strengthen = DailyTaskCard(title="提升1次弧盘等级", action="前往")
        arc_attack = DailyTaskCard(title="释放3次极轨攻击", action="前往")

        self.assertEqual(
            DailyTask._activity_handler_for_card(task, coffee).__func__,
            DailyTask._handle_coffee_activity,
        )
        self.assertEqual(coffee.handler_key, DailyTask.COFFEE_ACTIVITY_KEY)
        self.assertEqual(
            DailyTask._activity_handler_for_card(task, gift).__func__,
            DailyTask._handle_gift_activity,
        )
        self.assertEqual(gift.handler_key, DailyTask.GIFT_ACTIVITY_KEY)
        self.assertEqual(
            DailyTask._activity_handler_for_card(task, strengthen).__func__,
            DailyTask._handle_strengthen_activity,
        )
        self.assertEqual(strengthen.handler_key, DailyTask.STRENGTHEN_ACTIVITY_KEY)
        self.assertEqual(
            DailyTask._activity_handler_for_card(task, arc_attack).__func__,
            DailyTask._handle_arc_attack_activity,
        )
        self.assertEqual(arc_attack.handler_key, DailyTask.ARC_ATTACK_ACTIVITY_KEY)

    def test_activity_handler_registry_supplies_default_block_reasons(self):
        task = object.__new__(DailyTask)

        self.assertEqual(
            DailyTask._activity_block_reason(task, "累计消耗10点都市活力"),
            "咖啡店补货需要稳定识别一咖舍、商品、固定补货时长和送货上门",
        )
        self.assertEqual(
            DailyTask._activity_block_reason(task, "释放3次极轨攻击"),
            "已有 handler 框架，但缺少安全战斗场景确认",
        )
        self.assertEqual(
            DailyTask._activity_block_reason(task, "累计消耗180点本性像素"),
            "资源消耗类任务默认不自动",
        )

    def test_execute_activity_handlers_across_pages_swipes_until_handler_page(self):
        first_page = DailyActivityPage(
            task_cards=[
                DailyTaskCard(
                    title="累计消耗180点本性像素",
                    action="前往",
                    box=RegionBox("card", 100, 500, 200, 300),
                )
            ]
        )
        second_page = DailyActivityPage(
            task_cards=[
                DailyTaskCard(
                    title="累计消耗10点都市活力",
                    action="前往",
                    box=RegionBox("card", 200, 500, 200, 300),
                )
            ]
        )
        task = object.__new__(DailyTask)
        task._execute_available_activity_handlers = Mock(side_effect=[False, True])
        task._swipe_daily_activity_cards = Mock(return_value=True)
        task._analyze_daily_activity = Mock(return_value=make_analysis(page=second_page))
        task._record_daily_activity_analysis = Mock()
        task._record_remaining_activity_tasks = Mock()
        task.info_set = Mock()

        result = DailyTask._execute_available_activity_handlers_across_pages(task, first_page)

        self.assertTrue(result)
        task._swipe_daily_activity_cards.assert_called_once_with(first_page)
        task._execute_available_activity_handlers.assert_has_calls([call(first_page), call(second_page)])
        task._record_daily_activity_analysis.assert_called_once()

    def test_execute_activity_handlers_across_pages_stops_when_swipe_does_not_move(self):
        page = DailyActivityPage(
            task_cards=[
                DailyTaskCard(
                    title="赠送1次礼物",
                    progress_text="0/1",
                    action="前往",
                    box=RegionBox("card", 100, 500, 200, 300),
                )
            ]
        )
        task = object.__new__(DailyTask)
        task._execute_available_activity_handlers = Mock(return_value=False)
        task._swipe_daily_activity_cards = Mock(return_value=True)
        task._analyze_daily_activity = Mock(return_value=make_analysis(page=page))
        task._record_daily_activity_analysis = Mock()
        task._record_remaining_activity_tasks = Mock()
        task.info_set = Mock()

        result = DailyTask._execute_available_activity_handlers_across_pages(task, page)

        self.assertFalse(result)
        task.info_set.assert_any_call("每日任务列表滑动状态", "未移动:1")
        task._record_remaining_activity_tasks.assert_not_called()

    def test_swipe_daily_activity_cards_uses_horizontal_card_list(self):
        class FakeDailyTask(DailyTask):
            @property
            def width(self):
                return 2560

        task = object.__new__(FakeDailyTask)
        task.swipe = Mock()
        page = DailyActivityPage(
            task_cards=[
                DailyTaskCard(box=RegionBox("card", 431, 692, 358, 528)),
                DailyTaskCard(box=RegionBox("card", 851, 692, 358, 528)),
                DailyTaskCard(box=RegionBox("card", 1271, 692, 358, 528)),
                DailyTaskCard(box=RegionBox("card", 1691, 692, 358, 528)),
                DailyTaskCard(box=RegionBox("card", 2111, 692, 358, 528)),
            ]
        )

        result = DailyTask._swipe_daily_activity_cards(task, page)

        self.assertTrue(result)
        task.swipe.assert_called_once_with(1905, 940, 574, 940, duration=0.9, after_sleep=1)

    def test_swipe_daily_activity_cards_falls_back_without_card_boxes(self):
        task = object.__new__(DailyTask)
        viewport = Mock()
        viewport.ui_point_to_screen_pixel.side_effect = [(1997, 928), (768, 928)]
        task.get_ui_viewport = Mock(return_value=viewport)
        task.swipe = Mock()

        result = DailyTask._swipe_daily_activity_cards(task, DailyActivityPage())

        self.assertTrue(result)
        viewport.ui_point_to_screen_pixel.assert_has_calls(
            [
                call(*DailyTask.DAILY_ACTIVITY_CARD_SWIPE_START),
                call(*DailyTask.DAILY_ACTIVITY_CARD_SWIPE_END),
            ]
        )
        task.swipe.assert_called_once_with(1997, 928, 768, 928, duration=0.9, after_sleep=1)

    def test_swipe_daily_activity_cards_falls_back_when_only_right_edge_card_is_available(self):
        class FakeDailyTask(DailyTask):
            @property
            def width(self):
                return 1000

        task = object.__new__(FakeDailyTask)
        viewport = Mock()
        viewport.ui_point_to_screen_pixel.side_effect = [(780, 580), (300, 580)]
        task.get_ui_viewport = Mock(return_value=viewport)
        task.swipe = Mock()
        page = DailyActivityPage(
            task_cards=[
                DailyTaskCard(box=RegionBox("card", 100, 300, 200, 300)),
                DailyTaskCard(box=RegionBox("card", 890, 300, 200, 300)),
            ]
        )

        result = DailyTask._swipe_daily_activity_cards(task, page)

        self.assertTrue(result)
        task.swipe.assert_called_once_with(780, 580, 300, 580, duration=0.9, after_sleep=1)

    def test_gift_handler_without_targets_does_not_enter_panel(self):
        card = DailyTaskCard(title="赠送1次礼物", action="前往", action_box=object())
        task = object.__new__(DailyTask)
        task.config = {"gift_target_characters": ""}
        task.info_set = Mock()
        task.log_info = Mock()
        task.click = Mock()

        result = DailyTask._handle_gift_activity(task, card)

        self.assertIs(result, DailyTask.TASK_SKIPPED)
        self.assertEqual(card.blocked_reason, DailyGiftPlanner.NO_TARGETS)
        task.click.assert_not_called()

    def test_coffee_handler_executes_safe_plan_actions(self):
        card = DailyTaskCard(
            title="累计消耗10点都市活力",
            action="前往",
            state="go",
            box=RegionBox("daily_activity_task_card", 640, 600, 360, 320),
            action_box=RegionBox("daily_activity_go_button", 720, 820, 220, 54),
        )
        state = CoffeeShopState(
            trend_category="热销",
            income_claim_target="income",
            supply_target="supply",
            slots=[
                CoffeeSupplySlot(
                    "slot-1",
                    options=[CoffeeFoodOption("best", price_value=200, category="热销", target="food")],
                    target="slot",
                )
            ],
            duration_options={"24小时": "duration-24h"},
            buy_target="buy",
            home_delivery_target="home-delivery",
        )
        task = object.__new__(DailyTask)
        task._executor = Mock(method=Mock(width=2560, height=1440))
        task.config = {"coffee_max_supply_slots": 0, "coffee_supply_duration": "24小时"}
        task.collect_daily_coffee_state = Mock(return_value=state)
        task.click = Mock()
        task.sleep = Mock()
        task.next_frame = Mock()
        task.find_one = Mock(return_value=None)
        task.get_ui_layout_profile = Mock(return_value="native_unknown")
        task.info_set = Mock()
        task.log_info = Mock()
        task._close_activity_reward_popup = Mock()
        task._ensure_daily_main = Mock()

        result = DailyTask._handle_coffee_activity(task, card)

        self.assertTrue(result)
        task.click.assert_has_calls(
            [
                call(830, 847),
                call("income"),
                call("supply"),
                call("slot"),
                call("food"),
                call("duration-24h"),
                call("buy"),
                call("home-delivery"),
            ]
        )
        task._close_activity_reward_popup.assert_called_once_with()
        task._ensure_daily_main.assert_called_once_with()

    def test_coffee_handler_without_collector_uses_runtime_entry(self):
        card = DailyTaskCard(title="累计消耗10点都市活力", action="前往", action_box="go-coffee")
        task = object.__new__(DailyTask)
        runtime_result = Mock(
            ok=True,
            skip_reason="",
            real_purchase_performed=True,
            selected_options=[],
            selected_actions=["enter_daily_coffee_card", "select_supply_duration:24小时"],
        )
        task.info_set = Mock()
        task.log_info = Mock()
        task._ensure_daily_main = Mock()

        with patch("src.tasks.DailyActivityFlow.DailyCoffeeRuntime") as runtime_cls:
            runtime_cls.return_value.run.return_value = runtime_result

            result = DailyTask._handle_coffee_activity(task, card)

        self.assertTrue(result)
        runtime_cls.return_value.run.assert_called_once_with(card)
        task._ensure_daily_main.assert_called_once_with()
        task.info_set.assert_any_call("咖啡店真实补货", "True")

    def test_gift_handler_executes_only_configured_target_plan(self):
        card = DailyTaskCard(
            title="赠送1次礼物",
            progress_text="0/1",
            action="前往",
            state="go",
            box=RegionBox("daily_activity_task_card", 640, 600, 360, 320),
            action_box=RegionBox("daily_activity_go_button", 720, 820, 220, 54),
        )
        state = GiftPanelState(
            daily_total_count=0,
            characters=[
                GiftCharacter("A", daily_count=0, gifts=[GiftOption("a-gift", 1, target="a-gift")], target="A"),
                GiftCharacter("B", daily_count=0, gifts=[GiftOption("b-gift", 1, target="b-gift")], target="B"),
            ],
            send_button_target="send",
        )
        task = object.__new__(DailyTask)
        task._executor = Mock(method=Mock(width=2560, height=1440))
        task.config = {"gift_target_characters": "B"}
        task.collect_daily_gift_state = Mock(return_value=state)
        task.click = Mock()
        task.sleep = Mock()
        task.next_frame = Mock()
        task.find_one = Mock(return_value=None)
        task.get_ui_layout_profile = Mock(return_value="native_unknown")
        task.info_set = Mock()
        task.log_info = Mock()
        task._close_activity_reward_popup = Mock()
        task._ensure_daily_main = Mock()

        result = DailyTask._handle_gift_activity(task, card)

        self.assertTrue(result)
        task.click.assert_has_calls(
            [
                call(830, 847),
                call("B"),
                call("b-gift"),
                call("send"),
            ]
        )
        self.assertNotIn(call("a-gift"), task.click.mock_calls)
        task._close_activity_reward_popup.assert_called_once_with()
        task._ensure_daily_main.assert_called_once_with()

    def test_gift_handler_without_collector_does_not_enter_panel(self):
        card = DailyTaskCard(title="赠送1次礼物", progress_text="0/1", action="前往", action_box="go-gift")
        task = object.__new__(DailyTask)
        task.config = {"gift_target_characters": "B"}
        task.info_set = Mock()
        task.log_info = Mock()
        task.click = Mock()

        result = DailyTask._handle_gift_activity(task, card)

        self.assertIs(result, DailyTask.TASK_SKIPPED)
        task.click.assert_not_called()

    def test_strengthen_handler_remains_conservative(self):
        card = DailyTaskCard(title="提升1次弧盘等级", action="前往", action_box=object())
        task = object.__new__(DailyTask)
        task.info_set = Mock()
        task.log_info = Mock()
        task.click = Mock()

        result = DailyTask._handle_strengthen_activity(task, card)

        self.assertIs(result, DailyTask.TASK_SKIPPED)
        self.assertIn("未消耗材料", card.blocked_reason)
        task.click.assert_not_called()

    def test_activity_required_remaining_uses_progress_then_title(self):
        self.assertEqual(
            DailyTask._activity_required_remaining(DailyTaskCard(title="赠送3次礼物", progress_text="1/3")),
            2,
        )
        self.assertEqual(
            DailyTask._activity_required_remaining(DailyTaskCard(title="赠送3次礼物", progress_text="")),
            3,
        )

    def test_daily_task_activity_helpers_delegate_to_flow_boundary(self):
        task = object.__new__(DailyTask)
        fake_flow = Mock()
        fake_flow.refresh_daily_activity_page_after_handlers.return_value = "page"
        fake_flow.claim_completed_activity_cards_until_stable.return_value = (1, "page")
        fake_flow.execute_available_activity_handlers.return_value = True
        fake_flow.execute_available_activity_handlers_across_pages.return_value = False
        fake_flow.swipe_daily_activity_cards.return_value = True
        fake_flow.daily_activity_card_swipe_points.return_value = ((10, 20), (1, 2))
        fake_flow.claim_completed_activity_card_rewards.return_value = 1

        with patch("src.tasks.DailyTask.DailyActivityFlow.from_task", return_value=fake_flow):
            self.assertEqual(DailyTask._refresh_daily_activity_page_after_handlers(task), "page")
            self.assertEqual(DailyTask._claim_completed_activity_cards_until_stable(task, "page"), (1, "page"))
            self.assertTrue(DailyTask._execute_available_activity_handlers(task, "page"))
            self.assertFalse(DailyTask._execute_available_activity_handlers_across_pages(task, "page"))
            self.assertTrue(DailyTask._swipe_daily_activity_cards(task, "page"))
            self.assertEqual(DailyTask._daily_activity_card_swipe_points(task, "page"), ((10, 20), (1, 2)))
            self.assertEqual(DailyTask._claim_completed_activity_card_rewards(task, "page"), 1)

        fake_flow.refresh_daily_activity_page_after_handlers.assert_called_once_with()
        fake_flow.claim_completed_activity_cards_until_stable.assert_called_once_with("page")
        fake_flow.execute_available_activity_handlers.assert_called_once_with("page")
        fake_flow.execute_available_activity_handlers_across_pages.assert_called_once_with("page")
        fake_flow.swipe_daily_activity_cards.assert_called_once_with("page")
        fake_flow.daily_activity_card_swipe_points.assert_called_once_with("page")
        fake_flow.claim_completed_activity_card_rewards.assert_called_once_with("page", max_clicks=1)

    def test_daily_activity_flow_collects_class_level_legacy_overrides(self):
        class OverrideTask(DailyTask):
            def _analyze_daily_activity(self, panel_detected=True):
                return make_analysis()

        task = object.__new__(OverrideTask)
        task.config = {}
        task.task_status = {}

        flow = DailyTask._daily_activity_flow(task)

        self.assertIn("analyze_daily_activity", flow.method_overrides)
        self.assertIs(flow.method_overrides["analyze_daily_activity"].__self__, task)

    def test_daily_task_removed_unused_visible_mission_legacy_helpers(self):
        self.assertFalse(hasattr(DailyTask, "_claim_visible_activity_missions"))
        self.assertFalse(hasattr(DailyTask, "_find_visible_activity_mission_claim_target"))
        self.assertFalse(hasattr(DailyTask, "_get_activity_reward_box"))
        source = inspect.getsource(DailyTask)
        self.assertNotIn("find_claimable_mission_buttons", source)

    def test_do_run_completes_daily_activity_before_reward_claims(self):
        task = object.__new__(DailyTask)
        task.config = {
            "领取邮件": True,
            "领取环期任务奖励": True,
            "完成每日活跃度": True,
            "领取活跃度奖励": True,
        }
        task.task_status = {"success": [], "failed": [], "skipped": [], "pending": []}
        task.current_task_key = None
        task.task_skip_reasons = {}
        task._ensure_daily_main = Mock()
        task.info_set = Mock()
        task.log_info = Mock()

        order = []
        task.claim_mail = Mock(side_effect=lambda: order.append("领取邮件") or True)
        task.claim_battle_pass_rewards = Mock(
            side_effect=lambda: order.append("领取环期任务奖励") or True
        )
        task.complete_daily_activities = Mock(
            side_effect=lambda: order.append("完成每日活跃度") or True
        )
        task.claim_activity_rewards = Mock(
            side_effect=lambda: order.append("领取活跃度奖励") or True
        )

        DailyTask.do_run(task)

        self.assertEqual(
            order,
            ["完成每日活跃度", "领取邮件", "领取活跃度奖励", "领取环期任务奖励"],
        )

    def test_ensure_daily_main_uses_world_features_without_login_ocr(self):
        task = object.__new__(DailyTask)
        task._logged_in = False
        task.wait_until = Mock(return_value=True)
        task.in_team_and_world = Mock()
        task.handle_monthly_card = Mock()
        task.back = Mock()
        task.sleep = Mock()
        task.info_set = Mock()

        result = DailyTask._ensure_daily_main(task)

        self.assertTrue(result)
        self.assertTrue(task._logged_in)
        task.wait_until.assert_called_once()
        _, kwargs = task.wait_until.call_args
        self.assertEqual(kwargs["time_out"], 30)
        self.assertFalse(kwargs["raise_if_not_found"])

    def test_claim_activity_rewards_skips_when_no_reward_available(self):
        task = object.__new__(DailyTask)
        task._open_activity_panel_result = Mock(return_value=make_open_result())
        task._analyze_daily_activity = Mock(return_value=make_analysis(page=DailyActivityPage(activity_score=90)))
        task._record_daily_activity_analysis = Mock()
        task.task_skip_reasons = {}
        task.info_set = Mock()
        task.log_info = Mock()

        result = DailyTask.claim_activity_rewards(task)

        self.assertIs(result, DailyTask.TASK_SKIPPED)
        task.info_set.assert_called_once_with(
            "活跃度奖励状态",
            DailyTask.ACTIVITY_REWARD_UNAVAILABLE,
        )
        self.assertEqual(
            task.task_skip_reasons["领取活跃度奖励"],
            DailyTask.ACTIVITY_REWARD_UNAVAILABLE,
        )
        task.log_info.assert_any_call(DailyTask.ACTIVITY_REWARD_UNAVAILABLE)

    def test_claim_activity_rewards_defers_top_milestone_before_full_score(self):
        first_box = RegionBox("daily_activity_milestone_20", 680, 220, 70, 70)
        second_box = RegionBox("daily_activity_milestone_40", 920, 220, 70, 70)
        page = DailyActivityPage(
            activity_score=90,
            milestone_rewards=[
                DailyMilestoneReward(20, first_box, claimable=True, locked=False),
                DailyMilestoneReward(40, second_box, claimable=True, locked=False),
                DailyMilestoneReward(100, RegionBox("daily_activity_milestone_100", 1640, 220, 70, 70), claimable=False, locked=True),
            ],
        )
        task = object.__new__(DailyTask)
        task._open_activity_panel_result = Mock(return_value=make_open_result())
        task._analyze_daily_activity = Mock(return_value=make_analysis(page=page))
        task._record_daily_activity_analysis = Mock()
        task.click = Mock()
        task.sleep = Mock()
        task._close_activity_reward_popup = Mock()
        task.config = {"claim_partial_milestones": False}
        task.task_skip_reasons = {}
        task.info_set = Mock()
        task.log_info = Mock()

        result = DailyTask.claim_activity_rewards(task)

        self.assertIs(result, DailyTask.TASK_SKIPPED)
        task.click.assert_not_called()
        task.sleep.assert_not_called()
        task.info_set.assert_any_call("待领取阶段奖励", "[20, 40]")
        task.info_set.assert_any_call(
            "活跃度奖励状态",
            DailyTask.ACTIVITY_REWARD_DEFERRED_UNTIL_FULL,
        )
        self.assertEqual(
            task.task_skip_reasons["领取活跃度奖励"],
            DailyTask.ACTIVITY_REWARD_DEFERRED_UNTIL_FULL,
        )

    def test_claim_activity_rewards_clicks_one_top_milestone_at_full_score(self):
        first_box = RegionBox("daily_activity_milestone_20", 680, 220, 70, 70)
        second_box = RegionBox("daily_activity_milestone_40", 920, 220, 70, 70)
        third_box = RegionBox("daily_activity_milestone_100", 1640, 220, 70, 70)
        after_page = DailyActivityPage(activity_score=100, milestone_rewards=[])
        page = DailyActivityPage(
            activity_score=100,
            milestone_rewards=[
                DailyMilestoneReward(20, first_box, claimable=True, locked=False),
                DailyMilestoneReward(40, second_box, claimable=True, locked=False),
                DailyMilestoneReward(100, third_box, claimable=True, locked=False),
            ],
        )
        task = object.__new__(DailyTask)
        task._open_activity_panel_result = Mock(return_value=make_open_result())
        task._analyze_daily_activity = Mock(side_effect=[make_analysis(page=page), make_analysis(page=after_page)])
        task._record_daily_activity_analysis = Mock()
        task._executor = Mock(method=Mock(width=2560, height=1440))
        task.click = Mock()
        task.sleep = Mock()
        task.next_frame = Mock()
        task._close_activity_reward_popup = Mock()
        task.config = {"claim_partial_milestones": False}
        task.task_skip_reasons = {}
        task.info_set = Mock()
        task.log_info = Mock()

        result = DailyTask.claim_activity_rewards(task)

        self.assertTrue(result)
        task.click.assert_called_once_with(715, 255)
        task.sleep.assert_called_once_with(1)
        task._close_activity_reward_popup.assert_called_once_with()

    def test_claim_activity_rewards_can_claim_partial_milestones_when_enabled(self):
        first_box = RegionBox("daily_activity_milestone_20", 680, 220, 70, 70)
        after_page = DailyActivityPage(activity_score=90, milestone_rewards=[])
        page = DailyActivityPage(
            activity_score=90,
            milestone_rewards=[
                DailyMilestoneReward(20, first_box, claimable=True, locked=False),
            ],
        )
        task = object.__new__(DailyTask)
        task._open_activity_panel_result = Mock(return_value=make_open_result())
        task._analyze_daily_activity = Mock(side_effect=[make_analysis(page=page), make_analysis(page=after_page)])
        task._record_daily_activity_analysis = Mock()
        task._executor = Mock(method=Mock(width=2560, height=1440))
        task.click = Mock()
        task.sleep = Mock()
        task.next_frame = Mock()
        task._close_activity_reward_popup = Mock()
        task.config = {"claim_partial_milestones": True}
        task.task_skip_reasons = {}
        task.info_set = Mock()
        task.log_info = Mock()

        result = DailyTask.claim_activity_rewards(task)

        self.assertTrue(result)
        task.click.assert_called_once_with(715, 255)
        task.sleep.assert_called_once_with(1)
        task._close_activity_reward_popup.assert_called_once_with()

    def test_close_activity_reward_popup_uses_esc_key(self):
        task = object.__new__(DailyTask)
        task.send_key = Mock()
        task.log_info = Mock()

        result = DailyTask._close_activity_reward_popup(task)

        self.assertTrue(result)
        task.send_key.assert_called_once_with("esc", after_sleep=1)
        task.log_info.assert_called_once_with("已按 ESC 关闭活跃度奖励弹窗")

    def test_close_activity_reward_popup_uses_foreground_fallback(self):
        task = object.__new__(DailyTask)
        task.send_key = Mock(side_effect=Exception("denied"))
        task.log_warning = Mock()
        task._send_foreground_key = Mock(return_value=True)

        result = DailyTask._close_activity_reward_popup(task)

        self.assertTrue(result)
        task.send_key.assert_called_once_with("esc", after_sleep=1)
        task._send_foreground_key.assert_called_once_with("esc", after_sleep=1)

    def test_daily_task_skips_when_16x10_template_missing(self):
        reason = (
            "当前分辨率为 2560x1600 native_16_10，F1 面板已打开并已点击每日第2栏目，"
            "但 f1_activity_panel 模板未命中；等待 16:10 面板检测适配。"
        )
        task = object.__new__(DailyTask)
        task._open_activity_panel_result = Mock(
            return_value=DailyPanelOpenResult(
                f1_panel_opened=True,
                daily_tab_clicked=True,
                daily_activity_panel_detected=False,
                layout_profile="native_16_10",
                reason=reason,
            )
        )
        task._analyze_daily_activity = Mock()
        task.task_skip_reasons = {}
        task.log_info = Mock()

        result = DailyTask.complete_daily_activities(task)

        self.assertIs(result, DailyTask.TASK_SKIPPED)
        self.assertEqual(task.task_skip_reasons["完成每日活跃度"], reason)
        task._analyze_daily_activity.assert_not_called()

    def test_open_esc_panel_does_not_wait_for_settle(self):
        task = object.__new__(DailyTask)
        task.reset_to_false = Mock()
        task.in_team_and_world = Mock(return_value=True)
        task.send_key = Mock()
        task.log_info = Mock()
        task._wait_esc_panel = Mock(return_value=object())
        task._send_foreground_key = Mock()

        DailyTask.openESCpanel(task)

        task._wait_esc_panel.assert_called_once()
        task._send_foreground_key.assert_not_called()

    def test_open_esc_panel_uses_foreground_key_fallback(self):
        task = object.__new__(DailyTask)
        task.reset_to_false = Mock()
        task.in_team_and_world = Mock(return_value=True)
        task.send_key = Mock()
        task.log_info = Mock()
        panel = object()
        task._wait_esc_panel = Mock(side_effect=[None, panel])
        task._send_foreground_key = Mock(return_value=True)

        result = DailyTask.openESCpanel(task)

        self.assertIs(result, panel)
        task._send_foreground_key.assert_called_once_with("esc", after_sleep=1)
        self.assertEqual(task._wait_esc_panel.call_count, 2)

    def test_open_f1_panel_uses_background_interaction_without_forcing_foreground(self):
        task = object.__new__(BaseNTETask)
        task.reset_to_false = Mock()
        task.in_team_and_world = Mock(return_value=True)
        task.send_key = Mock()
        task.wait_panel = Mock(return_value="f1_panel")
        task.log_info = Mock()
        task.log_error = Mock()
        task.bring_to_front = Mock()

        result = BaseNTETask.openF1panel(task)

        self.assertEqual(result, "f1_panel")
        task.send_key.assert_called_once_with("f1", after_sleep=1)
        task.bring_to_front.assert_not_called()

    def test_open_mail_panel_clicks_verified_mail_button_center(self):
        task = object.__new__(DailyTask)
        task.log_info = Mock()
        task.openESCpanel = Mock()
        task.click_ui = Mock()
        task.wait_panel = Mock(return_value=object())

        result = MailClaimFlow(task).open_mail_panel()

        self.assertTrue(result)
        task.openESCpanel.assert_called_once()
        task.click_ui.assert_called_once_with(
            *DailyTask.MAIL_BUTTON_POSITION,
            after_sleep=1,
            move=True,
            down_time=0.01,
        )
        task.wait_panel.assert_called_once_with(Labels.mail_panel, time_out=DailyTask.MAIL_PANEL_WAIT_TIMEOUT)

    def test_open_mail_panel_retries_lower_mail_button_when_first_click_misses(self):
        task = object.__new__(DailyTask)
        task.log_info = Mock()
        task.log_error = Mock()
        task.openESCpanel = Mock()
        task.click_ui = Mock()
        task.wait_panel = Mock(side_effect=[False, object()])

        result = MailClaimFlow(task).open_mail_panel()

        self.assertTrue(result)
        task.click_ui.assert_has_calls(
            [
                call(*DailyTask.MAIL_BUTTON_POSITION, after_sleep=1, move=True, down_time=0.01),
                call(*DailyTask.MAIL_BUTTON_RETRY_POSITION, after_sleep=1, move=True, down_time=0.01),
            ]
        )
        self.assertEqual(task.wait_panel.call_count, 2)

    def test_open_mail_panel_clicks_mail_icon_from_detected_phone_menu(self):
        panel = Mock(name="mail_phone_menu", x=1792, y=160, width=716, height=1312)
        panel.name = "mail_phone_menu"
        task = object.__new__(DailyTask)
        task.log_info = Mock()
        task.log_error = Mock()
        task.click = Mock()
        task.click_ui = Mock()
        task.wait_panel = Mock(return_value=object())
        flow = MailClaimFlow(task)
        flow.open_esc_panel_for_mail = Mock(return_value=panel)

        result = flow.open_mail_panel()

        self.assertTrue(result)
        task.click.assert_called_once_with(
            2225,
            1340,
            move=True,
            down_time=DailyTask.MAIL_PHONE_MENU_BUTTON_DOWN_TIME,
            after_sleep=DailyTask.MAIL_PHONE_MENU_CLICK_SLEEP,
        )
        task.click_ui.assert_not_called()

    def test_open_mail_panel_resolves_phone_menu_when_esc_template_matches_generic_option(self):
        esc_option = Mock(name="esc_option", x=1409, y=921, width=58, height=47)
        esc_option.name = "Labels.esc_option"
        phone_menu = Mock(name="mail_phone_menu", x=1344, y=108, width=537, height=885)
        phone_menu.name = "mail_phone_menu"
        task = object.__new__(DailyTask)
        task.log_info = Mock()
        task.log_error = Mock()
        task.click = Mock()
        task.click_ui = Mock()
        task.wait_panel = Mock(return_value=object())
        flow = MailClaimFlow(task)
        flow.open_esc_panel_for_mail = Mock(return_value=esc_option)
        flow.wait_mail_phone_menu = Mock(return_value=phone_menu)

        result = flow.open_mail_panel()

        self.assertTrue(result)
        flow.wait_mail_phone_menu.assert_called_once()
        task.log_info.assert_any_call("ESC 面板已打开手机菜单，切换为手机菜单区域识别邮件入口")
        task.click.assert_called_once_with(
            1668,
            904,
            move=True,
            down_time=DailyTask.MAIL_PHONE_MENU_BUTTON_DOWN_TIME,
            after_sleep=DailyTask.MAIL_PHONE_MENU_CLICK_SLEEP,
        )
        task.click_ui.assert_not_called()

    def test_click_mail_button_prefers_detected_envelope_icon(self):
        frame = np.zeros((1600, 2560, 3), dtype=np.uint8)
        frame[1318:1372, 2202:2268] = 255
        panel = Mock(name="mail_phone_menu", x=1792, y=160, width=716, height=1312)
        panel.name = "mail_phone_menu"
        task = object.__new__(DailyTask)
        task.log_info = Mock()
        task.next_frame = Mock(return_value=frame)
        task.click = Mock()

        result = MailClaimFlow(task).click_mail_button_from_phone_menu(panel)

        self.assertTrue(result)
        x, y = task.click.call_args.args
        self.assertGreaterEqual(x, 2202)
        self.assertLessEqual(x, 2268)
        self.assertGreaterEqual(y, 1318)
        self.assertLessEqual(y, 1372)
        task.click.assert_called_once_with(
            x,
            y,
            move=True,
            down_time=DailyTask.MAIL_PHONE_MENU_BUTTON_DOWN_TIME,
            after_sleep=DailyTask.MAIL_PHONE_MENU_CLICK_SLEEP,
        )

    def test_open_mail_panel_reopens_phone_menu_when_mail_icon_misses(self):
        panel = Mock(name="mail_phone_menu", x=1792, y=160, width=716, height=1312)
        panel.name = "mail_phone_menu"
        task = object.__new__(DailyTask)
        task.log_info = Mock()
        task.log_error = Mock()
        task.click = Mock()
        task.click_ui = Mock()
        task.wait_panel = Mock(side_effect=[False, object()])
        flow = MailClaimFlow(task)
        flow.open_esc_panel_for_mail = Mock(return_value=panel)

        result = flow.open_mail_panel()

        self.assertTrue(result)
        self.assertEqual(flow.open_esc_panel_for_mail.call_count, 2)
        self.assertEqual(task.click.call_count, 2)

    def test_open_mail_panel_retry_falls_back_when_second_panel_is_not_phone_menu(self):
        phone_panel = Mock(name="mail_phone_menu", x=1792, y=160, width=716, height=1312)
        phone_panel.name = "mail_phone_menu"
        generic_panel = Mock(name="esc_option", x=10, y=10, width=50, height=50)
        generic_panel.name = "esc_option"
        task = object.__new__(DailyTask)
        task.log_info = Mock()
        task.log_error = Mock()
        task.click = Mock()
        task.click_ui = Mock()
        task.wait_panel = Mock(side_effect=[False, object()])
        flow = MailClaimFlow(task)
        flow.open_esc_panel_for_mail = Mock(side_effect=[phone_panel, generic_panel])
        flow.wait_mail_phone_menu = Mock(return_value=None)

        result = flow.open_mail_panel()

        self.assertTrue(result)
        task.click.assert_called_once()
        task.click_ui.assert_called_once_with(
            *DailyTask.MAIL_BUTTON_RETRY_POSITION,
            after_sleep=1,
            move=True,
            down_time=0.01,
        )

    def test_open_mail_panel_retries_esc_panel_when_existing_panel_was_closed(self):
        task = object.__new__(DailyTask)
        task.log_info = Mock()
        task.log_error = Mock()
        task.openESCpanel = Mock(side_effect=[CannotFindException("first esc closed panel"), None])
        task.sleep = Mock()
        task.click_ui = Mock()
        task.wait_panel = Mock(return_value=object())

        result = MailClaimFlow(task).open_mail_panel()

        self.assertTrue(result)
        self.assertEqual(task.openESCpanel.call_count, 2)
        task.log_info.assert_any_call("首次打开 ESC 面板失败，重试一次")
        task.click_ui.assert_called_once_with(
            *DailyTask.MAIL_BUTTON_POSITION,
            after_sleep=1,
            move=True,
            down_time=0.01,
        )

    def test_open_mail_panel_clicks_recognized_esc_shortcut_when_hotkey_fails(self):
        esc_box = Mock(text="ESC", x=2300, y=126, width=84, height=28)
        task = object.__new__(DailyTask)
        task.openESCpanel = Mock(
            side_effect=[
                CannotFindException("first esc did not open menu"),
                CannotFindException("second esc did not open menu"),
            ]
        )
        task.sleep = Mock()
        task.log_info = Mock()
        task.ocr_ui = Mock(return_value=[esc_box])
        task.next_frame = Mock(return_value="fresh-frame")
        task._send_foreground_key = Mock(return_value=False)
        task.click = Mock()
        task._wait_esc_panel = Mock(return_value="esc-panel")
        flow = MailClaimFlow(task)
        flow.wait_mail_phone_menu = Mock(return_value=None)

        with patch.object(DailyTask, "height", new_callable=PropertyMock, return_value=1600):
            result = flow.open_esc_panel_for_mail()

        self.assertEqual(result, "esc-panel")
        task.ocr_ui.assert_called_once_with(*DailyTask.MAIL_ESC_SHORTCUT_REGION, frame="fresh-frame")
        task.click.assert_called_once_with(
            2342,
            68,
            move=True,
            down_time=DailyTask.MAIL_ESC_SHORTCUT_CLICK_DOWN_TIME,
            after_sleep=DailyTask.MAIL_ESC_SHORTCUT_CLICK_SLEEP,
        )
        task._wait_esc_panel.assert_called_once()

    def test_open_mail_panel_clicks_detected_esc_icon_when_text_ocr_misses(self):
        frame = np.zeros((1600, 2560, 3), dtype=np.uint8)
        frame[42:92, 2460:2500] = 255
        task = object.__new__(DailyTask)
        task.openESCpanel = Mock(
            side_effect=[
                CannotFindException("first esc did not open menu"),
                CannotFindException("second esc did not open menu"),
            ]
        )
        task.sleep = Mock()
        task.log_info = Mock()
        task.ocr_ui = Mock(return_value=[])
        task.next_frame = Mock(return_value=frame)
        task._send_foreground_key = Mock(return_value=False)
        task.box_of_ui = Mock(return_value=Mock(x=2390, y=16, width=140, height=140))
        task.click = Mock()
        task._wait_esc_panel = Mock(return_value="esc-panel")
        flow = MailClaimFlow(task)
        flow.wait_mail_phone_menu = Mock(return_value=None)

        result = flow.open_esc_panel_for_mail()

        self.assertEqual(result, "esc-panel")
        x, y = task.click.call_args.args
        self.assertGreaterEqual(x, 2460)
        self.assertLessEqual(x, 2500)
        self.assertGreaterEqual(y, 42)
        self.assertLessEqual(y, 92)
        task.click.assert_called_once()
        task._wait_esc_panel.assert_called_once()

    def test_open_mail_panel_accepts_phone_menu_when_esc_template_misses(self):
        frame = np.full((1600, 2560, 3), 210, dtype=np.uint8)
        frame[180:1460, 1820:2500] = 35
        frame[1260:1460, 1820:2500] = 55
        task = object.__new__(DailyTask)
        task.openESCpanel = Mock(
            side_effect=[
                CannotFindException("first esc did not open menu"),
                CannotFindException("second esc did not match template"),
            ]
        )
        task.sleep = Mock()
        task.log_info = Mock()
        task.next_frame = Mock(return_value=frame)
        task.wait_until = Mock(side_effect=lambda predicate, **kwargs: predicate())
        task._send_foreground_key = Mock()
        task.click = Mock()

        result = MailClaimFlow(task).open_esc_panel_for_mail()

        self.assertEqual(result.name, "mail_phone_menu")
        task._send_foreground_key.assert_not_called()
        task.click.assert_not_called()

    def test_claim_battle_pass_skips_reward_track_when_all_claim_not_visible(self):
        task = object.__new__(DailyTask)
        task.log_info = Mock()
        task.openF2panel = Mock()
        task.click_ui = Mock()
        task.click = Mock()
        task.sleep = Mock()
        task.info_set = Mock()
        task.ocr_ui = Mock(return_value=[])
        task._wait_battle_pass_mission_panel = Mock(return_value=object())

        result = DailyTask.claim_battle_pass_rewards(task)

        self.assertTrue(result["ok"])
        self.assertFalse(result["claimed"])
        self.assertFalse(result["reward_claimed"])
        self.assertTrue(result["skipped"])
        self.assertEqual(result["reason"], "no_claimable_periodic_reward")
        self.assertEqual(result["mission_claim_attempts"], 0)
        task.openF2panel.assert_called_once()
        task.click_ui.assert_has_calls(
            [
                call(*DailyTask.BATTLE_PASS_MISSION_TAB_POSITION),
                call(*DailyTask.BATTLE_PASS_REWARD_TAB_POSITION),
            ]
        )
        self.assertNotIn(call(*DailyTask.BATTLE_PASS_REWARD_POSITION), task.click_ui.mock_calls)
        task._wait_battle_pass_mission_panel.assert_called_once()

    def test_claim_battle_pass_clicks_ocr_mission_claim_before_reward_track(self):
        mission_target = RegionBox("领取", 1760, 420, 120, 70)
        task = object.__new__(DailyTask)
        task.log_info = Mock()
        task.openF2panel = Mock()
        task.click_ui = Mock()
        task.click = Mock()
        task.sleep = Mock()
        task._executor = Mock(method=Mock(width=2560, height=1440))
        task.next_frame = Mock()
        task.info_set = Mock()
        task.ocr_ui = Mock(side_effect=[[mission_target], [], [], []])
        task._wait_battle_pass_mission_panel = Mock(return_value=object())

        with patch.object(DailyTask, "frame", new_callable=PropertyMock, return_value=object()):
            result = DailyTask.claim_battle_pass_rewards(task)

        self.assertEqual(result["mission_claim_attempts"], 1)
        task.click.assert_called_once_with(1820, 455)
        self.assertLess(
            task.click_ui.mock_calls.index(call(*DailyTask.BATTLE_PASS_MISSION_TAB_POSITION)),
            task.click_ui.mock_calls.index(call(*DailyTask.BATTLE_PASS_REWARD_TAB_POSITION)),
        )

    def test_battle_pass_mission_claim_preserves_prior_success_when_later_gate_fails(self):
        task = object.__new__(DailyTask)
        task.info_set = Mock()
        target = RegionBox("领取", 100, 200, 80, 40)
        success_gate = Mock(
            allowed=True,
            verified=True,
            mutation_performed=True,
            reject_reason="",
            failure_reason="",
        )
        success_gate.to_details.return_value = {
            "allowed": True,
            "verified": True,
            "mutation_performed": True,
            "mutation_verified": True,
        }
        rejected_gate = Mock(
            allowed=False,
            verified=False,
            mutation_performed=False,
            reject_reason="low_confidence",
            failure_reason="",
        )
        rejected_gate.to_details.return_value = {
            "allowed": False,
            "verified": False,
            "mutation_performed": False,
            "mutation_verified": False,
        }
        task._find_battle_pass_text_box = Mock(side_effect=[target, target])
        task._execute_battle_pass_claim_gate = Mock(side_effect=[success_gate, rejected_gate])

        result = DailyTask._claim_visible_battle_pass_mission_rewards(task)

        self.assertEqual(result["claimed"], 1)
        self.assertTrue(result["mutation_performed"])
        self.assertTrue(result["mutation_verified"])
        self.assertEqual(result["failure_reason"], "low_confidence")

    def test_claim_battle_pass_ignores_already_claimed_mission_text(self):
        already_claimed = RegionBox("已领取", 1760, 420, 120, 70)
        task = object.__new__(DailyTask)
        task.log_info = Mock()
        task.openF2panel = Mock()
        task.click_ui = Mock()
        task.click = Mock()
        task.sleep = Mock()
        task.info_set = Mock()
        task.ocr_ui = Mock(side_effect=[[already_claimed], []])
        task._wait_battle_pass_mission_panel = Mock(return_value=object())

        with patch.object(DailyTask, "frame", new_callable=PropertyMock, return_value=object()):
            result = DailyTask.claim_battle_pass_rewards(task)

        self.assertTrue(result["ok"])
        self.assertFalse(result["claimed"])
        self.assertFalse(result["mutation_performed"])
        task.click.assert_not_called()

    def test_claim_battle_pass_verifies_when_claim_button_becomes_already_claimed(self):
        mission_target = RegionBox("领取", 1760, 420, 120, 70)
        already_claimed = RegionBox("已领取", 1760, 420, 120, 70)
        task = object.__new__(DailyTask)
        task.log_info = Mock()
        task.openF2panel = Mock()
        task.click_ui = Mock()
        task.click = Mock()
        task.sleep = Mock()
        task._executor = Mock(method=Mock(width=2560, height=1440))
        task.next_frame = Mock()
        task.info_set = Mock()
        task.ocr_ui = Mock(side_effect=[[mission_target], [already_claimed], [], []])
        task._wait_battle_pass_mission_panel = Mock(return_value=object())

        with patch.object(DailyTask, "frame", new_callable=PropertyMock, return_value=object()):
            result = DailyTask.claim_battle_pass_rewards(task)

        self.assertTrue(result["ok"])
        self.assertEqual(result["mission_claim_attempts"], 1)
        self.assertTrue(result["mutation_performed"])
        self.assertTrue(result["mutation_verified"])
        task.click.assert_called_once_with(1820, 455)

    def test_claim_battle_pass_prefers_ocr_all_claim_button(self):
        target = RegionBox("全部领取", 1200, 1340, 280, 70)
        task = object.__new__(DailyTask)
        task.log_info = Mock()
        task.openF2panel = Mock()
        task.click_ui = Mock()
        task.click = Mock()
        task.sleep = Mock()
        task._executor = Mock(method=Mock(width=2560, height=1440))
        task.next_frame = Mock()
        task.info_set = Mock()
        task.ocr_ui = Mock(side_effect=[[], [target], []])
        task._wait_battle_pass_mission_panel = Mock(return_value=object())

        with patch.object(DailyTask, "frame", new_callable=PropertyMock, return_value=object()):
            result = DailyTask.claim_battle_pass_rewards(task)

        self.assertTrue(result["reward_claimed"])
        task.click.assert_called_once_with(1340, 1375)
        self.assertNotIn(call(*DailyTask.BATTLE_PASS_REWARD_POSITION), task.click_ui.mock_calls)

    def test_find_battle_pass_mission_panel_prefers_existing_template(self):
        task = object.__new__(DailyTask)
        panel = object()
        task.find_one = Mock(return_value=panel)
        task._find_battle_pass_mission_panel_structure = Mock()

        result = DailyTask._find_battle_pass_mission_panel(task)

        self.assertIs(result, panel)
        task.find_one.assert_called_once_with(Labels.f2_mission_panel)
        task._find_battle_pass_mission_panel_structure.assert_not_called()

    def test_find_battle_pass_mission_panel_detects_selected_task_card(self):
        task = object.__new__(DailyTask)
        frame = np.full((1600, 2560, 3), 40, dtype=np.uint8)
        frame[432:624, 435:870] = (255, 0, 255)
        task.box_of_ui = Mock(return_value="mission_panel")

        with patch.object(DailyTask, "frame", new_callable=PropertyMock, return_value=frame):
            result = DailyTask._find_battle_pass_mission_panel_structure(task)

        self.assertEqual(result, "mission_panel")
        task.box_of_ui.assert_called_once()

    def test_find_battle_pass_mission_panel_rejects_unselected_page(self):
        task = object.__new__(DailyTask)
        frame = np.full((1600, 2560, 3), 40, dtype=np.uint8)

        with patch.object(DailyTask, "frame", new_callable=PropertyMock, return_value=frame):
            result = DailyTask._find_battle_pass_mission_panel_structure(task)

        self.assertIsNone(result)

    def test_wait_esc_panel_uses_stricter_threshold(self):
        task = object.__new__(BaseNTETask)
        task._find_esc_panel = Mock(return_value="panel")
        task.wait_until = Mock(return_value="panel")

        result = BaseNTETask._wait_esc_panel(task)

        self.assertEqual(result, "panel")
        condition = task.wait_until.call_args.args[0]
        self.assertEqual(condition(), "panel")
        self.assertEqual(task.wait_until.call_args.kwargs["settle_time"], 0)

    def test_find_esc_panel_prefers_existing_template(self):
        task = object.__new__(BaseNTETask)
        panel = object()
        task.find_one = Mock(return_value=panel)
        task._find_esc_phone_menu = Mock()

        result = BaseNTETask._find_esc_panel(task)

        self.assertIs(result, panel)
        task.find_one.assert_called_once_with(
            Labels.esc_option,
            box=Labels.box_all_esc_options,
            threshold=BaseNTETask.ESC_PANEL_THRESHOLD,
        )
        task._find_esc_phone_menu.assert_not_called()

    def test_find_esc_phone_menu_detects_dark_phone_panel(self):
        task = object.__new__(BaseNTETask)
        frame = np.full((1600, 2560, 3), 220, dtype=np.uint8)
        frame[192:1488, 1792:2508] = 60
        frame[1264:1488, 1792:2508] = 50

        with patch.object(BaseNTETask, "frame", new_callable=PropertyMock, return_value=frame):
            result = BaseNTETask._find_esc_phone_menu(task)

        self.assertIsNotNone(result)
        self.assertEqual(result.name, "esc_phone_menu")

    def test_find_esc_phone_menu_rejects_world_frame(self):
        task = object.__new__(BaseNTETask)
        frame = np.full((1600, 2560, 3), 220, dtype=np.uint8)

        with patch.object(BaseNTETask, "frame", new_callable=PropertyMock, return_value=frame):
            result = BaseNTETask._find_esc_phone_menu(task)

        self.assertIsNone(result)

    def test_send_foreground_key_attempts_direct_input_without_foreground_confirmation(self):
        task = object.__new__(BaseNTETask)
        hwnd_window = Mock()
        hwnd_window.is_foreground.return_value = False
        task.bring_to_front = Mock()
        task._send_pydirect_key = Mock(return_value=True)
        task._send_pynput_key = Mock()
        task.sleep = Mock()
        task.log_info = Mock()

        with (
            patch.object(BaseNTETask, "hwnd", new_callable=PropertyMock, return_value=hwnd_window),
            patch("src.tasks.BaseNTETask.time.sleep"),
        ):
            result = BaseNTETask._send_foreground_key(task, "esc", after_sleep=1)

        self.assertTrue(result)
        task._send_pydirect_key.assert_called_once_with("esc", 0.05)
        task._send_pynput_key.assert_not_called()
        task.sleep.assert_called_once_with(1)

    def test_bring_to_front_unwraps_hwnd_window_handle(self):
        task = object.__new__(BaseNTETask)
        hwnd_window = Mock(hwnd=12345)
        hwnd_window.is_foreground.side_effect = [False, True]
        task._executor = Mock(device_manager=Mock(hwnd_window=hwnd_window))

        with (
            patch("src.tasks.BaseNTETask.win32api.GetCurrentThreadId", return_value=1),
            patch(
                "src.tasks.BaseNTETask.win32process.GetWindowThreadProcessId",
                return_value=(1, 999),
            ) as get_thread,
            patch("src.tasks.BaseNTETask.win32gui.GetForegroundWindow", return_value=0),
            patch("src.tasks.BaseNTETask.win32gui.IsIconic", return_value=False),
            patch("src.tasks.BaseNTETask.win32gui.BringWindowToTop") as bring_top,
            patch("src.tasks.BaseNTETask.win32gui.SetForegroundWindow") as set_foreground,
        ):
            result = BaseNTETask.bring_to_front(task)

        self.assertTrue(result)
        get_thread.assert_called_once_with(12345)
        bring_top.assert_called_once_with(12345)
        set_foreground.assert_called_once_with(12345)

    def test_wait_panel_uses_custom_settle_time(self):
        task = object.__new__(BaseNTETask)
        task.find_one = Mock(return_value="panel")
        task.wait_until = Mock(return_value="panel")

        result = BaseNTETask.wait_panel(task, Labels.esc_option, settle_time=0)

        self.assertEqual(result, "panel")
        self.assertEqual(task.wait_until.call_args.kwargs["settle_time"], 0)


if __name__ == "__main__":
    unittest.main()
