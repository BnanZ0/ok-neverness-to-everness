import inspect
import unittest
from unittest.mock import Mock, call, patch

from src.tasks.DailyActivityAnalyzer import (
    DailyActivityAnalysis,
    DailyActivityPage,
    DailyActivityState,
    DailyTaskCard,
    RegionBox,
)
from src.tasks.DailyActivityFlow import DailyActivityActionContext, DailyActivityFlow
from src.tasks.DailyActivityModels import ActivityHandleIntent, DailyActivityOutcome
from src.tasks.DailyTask import DailyTask
from src.tasks.DailyUIContext import ReadOnlyUIContext, TaskUIAdapter
from src.tasks.F1PanelDetector import DailyPanelOpenResult
from src.tasks.FlowResult import FlowResult


def make_open_result(detected=True, reason="每日活跃度面板已识别"):
    return DailyPanelOpenResult(
        f1_panel_opened=True,
        daily_tab_clicked=True,
        daily_activity_panel_detected=detected,
        layout_profile="native_16_9",
        reason=reason,
    )


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


class FakeTask:
    width = 2560
    height = 1440
    frame = None

    def __init__(self):
        self.config = {"gift_target_characters": ""}
        self.task_status = {"success": []}
        self.click = Mock()
        self.click_ui = Mock()
        self.swipe = Mock()
        self.sleep = Mock()
        self.next_frame = Mock()
        self.send_key = Mock()
        self._send_foreground_key = Mock()
        self.openF1panel = Mock()
        self.info_set = Mock()
        self.log_info = Mock()
        self.log_warning = Mock()

    def get_ui_layout_profile(self):
        return "native_16_9"

    def get_ui_viewport(self):
        return self

    def ui_point_to_screen_pixel(self, x, y):
        return int(self.width * x), int(self.height * y)

    def find_one(self, *args, **kwargs):
        return None

    def box_of_ui(self, *args, **kwargs):
        return None

    def get_box_by_name(self, *args, **kwargs):
        return None

    def ocr_ui(self, *args, **kwargs):
        return []

    def _ensure_daily_main(self):
        return True


class TestDailyActivityFlow(unittest.TestCase):
    def make_flow(self, task=None, **overrides):
        task = task or FakeTask()
        return DailyActivityFlow(
            ReadOnlyUIContext(task),
            DailyActivityActionContext.from_task(task),
            method_overrides=overrides,
            skipped_sentinel=DailyTask.TASK_SKIPPED,
        ), task

    def test_flow_does_not_hold_daily_task_directly(self):
        flow, _ = self.make_flow()

        self.assertFalse(hasattr(flow, "task"))
        self.assertIsInstance(flow.ui, ReadOnlyUIContext)
        self.assertIsInstance(flow.actions.ui, TaskUIAdapter)

    def test_daily_task_complete_entry_returns_legacy_skip(self):
        task = object.__new__(DailyTask)
        task.task_skip_reasons = {}
        fake_flow = Mock()
        fake_flow.snapshot.analysis = None
        fake_flow.snapshot.cards_claimed = 0
        fake_flow.snapshot.handlers_completed = False
        fake_flow.snapshot.reward_skip_reason = ""
        fake_flow.complete_daily_activities.return_value = FlowResult.skip("no claimable")

        with patch("src.tasks.DailyTask.DailyActivityFlow.from_task", return_value=fake_flow):
            result = DailyTask.complete_daily_activities(task)

        self.assertIs(result, DailyTask.TASK_SKIPPED)
        self.assertEqual(task.task_skip_reasons[DailyTask.CONF_COMPLETE_DAILY], "no claimable")

    def test_registry_matching_stays_in_daily_activity_registry(self):
        flow, _ = self.make_flow()
        coffee = DailyTaskCard(title="累计消耗10点都市活力", action="前往")
        gift = DailyTaskCard(title="赠送1次礼物", action="前往")
        unknown = DailyTaskCard(title="每日登录1次", action="前往")

        self.assertEqual(flow.activity_handler_for_card(coffee).__name__, "_handle_coffee_activity")
        self.assertEqual(coffee.handler_key, DailyActivityFlow.COFFEE_ACTIVITY_KEY)
        self.assertEqual(flow.activity_handler_for_card(gift).__name__, "_handle_gift_activity")
        self.assertEqual(gift.handler_key, DailyActivityFlow.GIFT_ACTIVITY_KEY)
        self.assertIsNone(flow.activity_handler_for_card(unknown))

    def test_registry_resolve_does_not_emit_mutation_actions(self):
        flow, task = self.make_flow()

        rule = flow.activity_rule_for_title("累计消耗10点都市活力")

        self.assertEqual(rule.handler_key, DailyActivityFlow.COFFEE_ACTIVITY_KEY)
        task.click.assert_not_called()
        task.click_ui.assert_not_called()
        task.swipe.assert_not_called()
        task.send_key.assert_not_called()

    def test_build_activity_handle_intent_is_read_only(self):
        go_box = RegionBox("daily_activity_go_button", 720, 820, 220, 54, confidence=0.94)
        card = DailyTaskCard(
            title="累计消耗10点都市活力",
            action="前往",
            state="go",
            box=RegionBox("daily_activity_task_card", 640, 600, 360, 320),
            action_box=go_box,
        )
        flow, task = self.make_flow()
        flow.snapshot.screenshot_id = "shot-1"

        intent = flow.build_activity_handle_intent(card)

        self.assertIsInstance(intent, ActivityHandleIntent)
        self.assertEqual(intent.handler_key, DailyActivityFlow.COFFEE_ACTIVITY_KEY)
        self.assertEqual(intent.candidate.card_key, DailyActivityFlow.COFFEE_ACTIVITY_KEY)
        self.assertEqual(intent.gate_spec.screenshot_id, "shot-1")
        self.assertEqual(intent.gate_spec.evidence_box, go_box)
        task.click.assert_not_called()
        task.click_ui.assert_not_called()
        task.swipe.assert_not_called()
        task.send_key.assert_not_called()

    def test_execute_activity_handle_intent_goes_through_action_gate(self):
        go_box = RegionBox("daily_activity_go_button", 720, 820, 220, 54, confidence=0.94)
        card = DailyTaskCard(
            title="累计消耗10点都市活力",
            action="前往",
            state="go",
            box=RegionBox("daily_activity_task_card", 640, 600, 360, 320),
            action_box=go_box,
        )
        flow, task = self.make_flow()
        flow.snapshot.screenshot_id = "shot-1"
        intent = flow.build_activity_handle_intent(card)

        outcome = flow.execute_activity_handle_intent(intent, verifier=Mock(return_value=False))

        self.assertIsInstance(outcome, DailyActivityOutcome)
        self.assertTrue(outcome.is_failed)
        self.assertTrue(outcome.mutation_performed)
        self.assertFalse(outcome.mutation_verified)
        self.assertEqual(outcome.failure_reason, "post_verification_failed")
        task.click.assert_called_once_with(830, 847)

    def test_gated_click_refreshes_frame_before_post_verifier(self):
        events = []
        flow, task = self.make_flow()
        flow.snapshot.screenshot_id = "shot-1"
        task.sleep.side_effect = lambda seconds: events.append(f"sleep:{seconds}")
        task.next_frame.side_effect = lambda: events.append("next_frame")

        outcome = flow._execute_gated_click(
            recognized_ui="daily_activity_second_tab",
            evidence_box=RegionBox("daily_activity_second_tab", 90, 390, 30, 40, confidence=0.95),
            post_verification="daily_activity_panel_detected",
            success_reason="daily_activity_tab_opened",
            verifier=lambda gate: events.append("verifier") or True,
        )

        self.assertTrue(outcome.done)
        self.assertEqual(events, ["sleep:1", "next_frame", "verifier"])

    def test_gated_click_uses_first_tuple_value_from_post_verifier(self):
        flow, task = self.make_flow()
        flow.snapshot.screenshot_id = "shot-1"

        outcome = flow._execute_gated_click(
            recognized_ui="daily_activity_second_tab",
            evidence_box=RegionBox("daily_activity_second_tab", 90, 390, 30, 40, confidence=0.95),
            post_verification="daily_activity_panel_detected",
            success_reason="daily_activity_tab_opened",
            verifier=lambda gate: (False, "inner-after-id"),
        )

        self.assertTrue(outcome.is_failed)
        self.assertTrue(outcome.mutation_performed)
        self.assertFalse(outcome.mutation_verified)
        self.assertEqual(outcome.failure_reason, "post_verification_failed")

    def test_daily_panel_verifier_retries_until_detector_matches(self):
        flow, task = self.make_flow()
        detector = Mock()
        detector.find_daily_activity_panel.side_effect = [False, False, True]
        analyzer = Mock()
        analyzer.analyze_page.return_value = DailyActivityPage()

        with patch("src.tasks.DailyActivityFlow.F1PanelDetector", return_value=detector), patch(
            "src.tasks.DailyActivityFlow.DailyActivityAnalyzer",
            return_value=analyzer,
        ):
            verified = flow._verify_daily_activity_panel_after_tab_click()

        self.assertTrue(verified)
        self.assertEqual(task.sleep.mock_calls, [call(0.5), call(0.5)])
        self.assertEqual(task.next_frame.call_count, 2)

    def test_daily_panel_verifier_accepts_activity_content_when_template_misses(self):
        flow, task = self.make_flow()
        detector = Mock()
        detector.find_daily_activity_panel.return_value = False
        analyzer = Mock()
        analyzer.analyze_page.return_value = DailyActivityPage(
            task_cards=[
                DailyTaskCard(
                    title="赠送1次礼物",
                    progress_text="0/1",
                    action="前往",
                    action_box=RegionBox("daily_activity_go_button", 720, 820, 220, 54),
                )
            ],
            go_buttons=[RegionBox("daily_activity_go_button", 720, 820, 220, 54)],
        )

        with patch("src.tasks.DailyActivityFlow.F1PanelDetector", return_value=detector), patch(
            "src.tasks.DailyActivityFlow.DailyActivityAnalyzer",
            return_value=analyzer,
        ):
            verified = flow._verify_daily_activity_panel_after_tab_click()

        self.assertTrue(verified)
        task.sleep.assert_not_called()
        task.next_frame.assert_not_called()

    def test_daily_panel_verifier_rejects_button_only_content(self):
        flow, task = self.make_flow()
        detector = Mock()
        detector.find_daily_activity_panel.return_value = False
        analyzer = Mock()
        analyzer.analyze_page.return_value = DailyActivityPage(
            task_cards=[
                DailyTaskCard(
                    title="342.87/h",
                    action="领取",
                    action_box=RegionBox("f1_activity_mission", 360, 830, 220, 54),
                )
            ],
            mission_claim_buttons=[RegionBox("f1_activity_mission", 360, 830, 220, 54)],
        )

        with patch("src.tasks.DailyActivityFlow.F1PanelDetector", return_value=detector), patch(
            "src.tasks.DailyActivityFlow.DailyActivityAnalyzer",
            return_value=analyzer,
        ):
            verified = flow._verify_daily_activity_panel_after_tab_click()

        self.assertFalse(verified)
        self.assertEqual(task.sleep.call_count, 2)
        self.assertEqual(task.next_frame.call_count, 2)

    def test_scroll_invalidates_old_activity_coordinates(self):
        go_box = RegionBox("daily_activity_go_button", 720, 820, 220, 54, confidence=0.94)
        card = DailyTaskCard(
            title="累计消耗10点都市活力",
            action="前往",
            state="go",
            box=RegionBox("daily_activity_task_card", 640, 600, 360, 320),
            action_box=go_box,
        )
        flow, task = self.make_flow()
        flow.snapshot.screenshot_id = "shot-before-scroll"
        intent = flow.build_activity_handle_intent(card)

        self.assertTrue(flow.swipe_daily_activity_cards(DailyActivityPage(task_cards=[
            DailyTaskCard(box=RegionBox("card", 431, 692, 358, 528)),
            DailyTaskCard(box=RegionBox("card", 851, 692, 358, 528)),
        ])))
        outcome = flow.execute_activity_handle_intent(intent, verifier=Mock(return_value=True))

        self.assertTrue(outcome.skipped)
        self.assertEqual(flow.result_recorder.gate_results[-1]["reject_reason"], "stale_screenshot_id")
        task.click.assert_not_called()

    def test_task_item_intent_requires_row_button_state_and_confidence(self):
        flow, task = self.make_flow()
        flow.snapshot.screenshot_id = "shot-1"

        missing_row = DailyTaskCard(
            title="累计消耗10点都市活力",
            action="前往",
            state="go",
            action_box=RegionBox("daily_activity_go_button", 720, 820, 220, 54, confidence=0.94),
        )
        ambiguous_state = DailyTaskCard(
            title="累计消耗10点都市活力",
            action="前往",
            state="unknown",
            box=RegionBox("daily_activity_task_card", 640, 600, 360, 320),
            action_box=RegionBox("daily_activity_go_button", 720, 820, 220, 54, confidence=0.94),
        )
        low_confidence = DailyTaskCard(
            title="累计消耗10点都市活力",
            action="前往",
            state="go",
            box=RegionBox("daily_activity_task_card", 640, 600, 360, 320),
            action_box=RegionBox("daily_activity_go_button", 720, 820, 220, 54, confidence=0.4),
        )

        missing_row_intent = flow.build_activity_handle_intent(missing_row)
        ambiguous_intent = flow.build_activity_handle_intent(ambiguous_state)
        low_confidence_intent = flow.build_activity_handle_intent(low_confidence)
        low_outcome = flow.execute_activity_handle_intent(low_confidence_intent, verifier=Mock(return_value=True))

        self.assertIsNone(missing_row_intent.gate_spec)
        self.assertIn("缺少任务卡片区域", missing_row_intent.notes[0])
        self.assertIsNone(ambiguous_intent.gate_spec)
        self.assertIn("任务状态未确认", ambiguous_intent.notes[0])
        self.assertFalse(low_outcome.mutation_performed)
        self.assertEqual(flow.result_recorder.gate_results[-1]["reject_reason"], "low_confidence")
        task.click.assert_not_called()

    def test_claim_card_verification_failure_records_unverified_mutation(self):
        claim_box = RegionBox("f1_activity_mission", 360, 830, 220, 54, confidence=0.94)
        page = DailyActivityPage(
            task_cards=[
                DailyTaskCard(
                    title="每日登录1次",
                    progress_text="1/1",
                    action="领取",
                    state="claimable",
                    box=RegionBox("daily_activity_task_card", 280, 620, 360, 320),
                    action_box=claim_box,
                )
            ],
            mission_claim_buttons=[claim_box],
        )
        flow, task = self.make_flow(
            analyze_daily_activity=Mock(return_value=make_analysis(DailyActivityState.HAS_CLAIMABLE_REWARD, page=page)),
        )
        flow.snapshot.screenshot_id = "shot-1"

        claimed = flow.claim_completed_activity_card_rewards(page)

        self.assertEqual(claimed, 0)
        self.assertTrue(flow.snapshot.mutation_performed)
        self.assertFalse(flow.snapshot.mutation_verified)
        self.assertEqual(flow.snapshot.failure_reason, "post_verification_failed")
        task.click.assert_called_once_with(470, 857)

    def test_claim_card_skips_candidate_without_task_evidence(self):
        claim_box = RegionBox("f1_activity_mission", 360, 830, 220, 54, confidence=0.94)
        page = DailyActivityPage(
            task_cards=[
                DailyTaskCard(
                    title="342.87/h",
                    action="领取",
                    state="claimable",
                    box=RegionBox("daily_activity_task_card", 280, 620, 360, 320),
                    action_box=claim_box,
                )
            ],
            mission_claim_buttons=[claim_box],
        )
        flow, task = self.make_flow()
        flow.snapshot.screenshot_id = "shot-1"

        claimed = flow.claim_completed_activity_card_rewards(page)

        self.assertEqual(claimed, 0)
        self.assertFalse(flow.snapshot.mutation_performed)
        task.click.assert_not_called()

    def test_unmatched_activity_card_is_skipped_with_reason(self):
        go_box = RegionBox("daily_activity_go_button", 720, 820, 220, 54)
        page = DailyActivityPage(
            activity_score=90,
            task_cards=[DailyTaskCard(title="每日登录1次", action="前往", action_box=go_box)],
            go_buttons=[go_box],
        )
        flow, task = self.make_flow(
            open_activity_panel_result=Mock(return_value=make_open_result()),
            analyze_daily_activity=Mock(return_value=make_analysis(page=page)),
            claim_completed_activity_card_rewards=Mock(return_value=0),
        )

        result = flow.complete_daily_activities()

        self.assertTrue(result.skipped)
        self.assertEqual(result.reason, "缺少未完成/前往按钮/可领取状态特征")
        task.click.assert_not_called()
        self.assertEqual(
            flow.snapshot.remaining_tasks,
            ["每日登录1次: 未配置安全自动 handler，未点击前往"],
        )

    def test_gift_handler_without_targets_is_no_mutation_skip(self):
        card = DailyTaskCard(title="赠送1次礼物", progress_text="0/1", action="前往", action_box="go-gift")
        flow, task = self.make_flow()

        result = flow._handle_gift_activity(card)

        self.assertTrue(result.skipped)
        self.assertFalse(result.mutated)
        self.assertEqual(result.reason, "未配置赠礼目标角色，跳过赠礼")
        task.click.assert_not_called()

    def test_flow_result_preserves_dict_fields_and_unknown_types_fail(self):
        result = FlowResult.from_legacy(
            {
                "ok": True,
                "skipped": True,
                "reason": "no reward",
                "mutation_performed": False,
                "custom": "kept",
            }
        )

        self.assertTrue(result.skipped)
        self.assertEqual(result.details["custom"], "kept")
        unknown = FlowResult.from_legacy(object())
        self.assertTrue(unknown.failed)
        self.assertIn("unknown_legacy_result_type", unknown.reason)

    def test_daily_activity_flow_does_not_import_anomaly_task(self):
        source = inspect.getsource(DailyActivityFlow)

        self.assertNotIn("AnomalyTask", source)


if __name__ == "__main__":
    unittest.main()
