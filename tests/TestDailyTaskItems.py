import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.tasks.DailyActivityAnalyzer import DailyActivityPage, DailyMilestoneReward, DailyTaskCard, RegionBox
from src.tasks.DailyTask import DailyTask
from src.tasks.DailyTaskItemRunner import DailyGiftDefaultRuntime, DailyTaskItemActionRunner, GiftDefaultSendResult
from scripts.run_daily_task_items import DailyTaskItemsValidationRunner


def open_result(detected=True):
    return SimpleNamespace(
        f1_panel_opened=True,
        daily_activity_panel_detected=detected,
        daily_tab_clicked=True,
        reason="ready" if detected else "panel_not_found",
    )


def analysis_for(page):
    return SimpleNamespace(page=page)


def card(
    title="每日登录1次",
    action="领取",
    state="claimable",
    *,
    row=True,
    button=True,
    confidence=1.0,
    x=100,
):
    return DailyTaskCard(
        title=title,
        progress_text="1/1" if action in {"领取", "完成"} else "0/1",
        action=action,
        button_text=action,
        state=state,
        box=RegionBox("daily_activity_task_card", x, 200, 220, 120, confidence=confidence) if row else None,
        action_box=RegionBox("daily_activity_button", x + 80, 280, 100, 36, confidence=confidence) if button else None,
    )


def milestone_page(*, claimable=False):
    rewards = []
    if claimable:
        rewards.append(DailyMilestoneReward(20, RegionBox("milestone_20", 410, 150, 56, 56), True, False))
    return DailyActivityPage(activity_score=100, milestone_rewards=rewards)


class FakeActions:
    width = 1280
    height = 720

    def __init__(self):
        self.clicks = []
        self.sleeps = []
        self.keys = []
        self.ensure_daily_main_calls = 0

    def click(self, x, y):
        self.clicks.append((x, y))

    def send_foreground_key(self, key, **kwargs):
        self.keys.append((key, kwargs))
        return True

    def sleep(self, seconds):
        self.sleeps.append(seconds)

    def next_frame(self):
        return None

    def ensure_daily_main(self):
        self.ensure_daily_main_calls += 1
        return True


class FakeFlow:
    def __init__(self, pages, *, detected=True):
        self.pages = list(pages)
        if isinstance(detected, (list, tuple)):
            self.detected_values = list(detected)
        else:
            self.detected_values = [detected]
        self.actions = FakeActions()
        self.snapshot = SimpleNamespace(screenshot_id="")
        self.recorded = []
        self._counter = 0
        self._analyze_calls = 0
        self._open_calls = 0
        self.activity_milestone_claim_calls = 0
        self.snapshot.reward_skip_reason = ""

    def open_activity_panel_result(self):
        index = min(self._open_calls, len(self.detected_values) - 1)
        self._open_calls += 1
        return open_result(self.detected_values[index])

    def analyze_daily_activity(self, panel_detected=True):
        index = min(self._analyze_calls, len(self.pages) - 1)
        self._analyze_calls += 1
        return analysis_for(self.pages[index])

    def record_daily_activity_analysis(self, analysis):
        self.recorded.append(analysis)
        self.snapshot.screenshot_id = self._new_screenshot_id("activity")

    def _new_screenshot_id(self, prefix):
        self._counter += 1
        return f"{prefix}-{self._counter}"

    def _ensure_current_screenshot_id(self, prefix="task_items"):
        if not self.snapshot.screenshot_id:
            self.snapshot.screenshot_id = self._new_screenshot_id(prefix)
        return self.snapshot.screenshot_id

    def claim_activity_milestone_rewards(self, page):
        self.activity_milestone_claim_calls += 1
        return bool(getattr(page, "claimable_milestones", []))


class FakeGiftRuntime:
    def __init__(self, result=None, *, page_reached=True):
        self.result = result or GiftDefaultSendResult(
            ok=True,
            reason="gift_send_clicked",
            mutation_performed=True,
            mutation_verified=False,
            handler_completed=True,
            selected_character="default_visible",
            selected_item="default_item",
            sent_total=1,
        )
        self.page_reached = page_reached
        self.send_calls = 0

    def verify_gift_page_reached(self):
        return self.page_reached

    def send_default_gift(self):
        self.send_calls += 1
        return self.result


class FakeOCRUI:
    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = 0

    def ocr_ui(self, *args, **kwargs):
        index = min(self.calls, len(self.pages) - 1)
        self.calls += 1
        return self.pages[index]


class FakeSession:
    def __init__(self, task, window=None):
        self.task = task
        self.window = window or {"width": 1280, "height": 720, "title": "HTGame", "hwnd": "1"}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class TestDailyTaskItemRunner(unittest.TestCase):
    def test_gift_phone_entry_uses_ocr_ji_yu_bbox_center(self):
        actions = FakeActions()
        flow = SimpleNamespace(
            actions=actions,
            ui=FakeOCRUI(
                [
                    [SimpleNamespace(name="羁遇", x=100, y=200, width=40, height=20, confidence=0.95)],
                    [
                        SimpleNamespace(name="羁遇", x=80, y=80, width=40, height=20, confidence=0.95),
                        SimpleNamespace(name="赠礼", x=900, y=120, width=40, height=20, confidence=0.95),
                    ],
                ]
            ),
        )
        runtime = DailyGiftDefaultRuntime(flow)

        result = runtime.enter_from_phone_menu()

        self.assertTrue(result["ok"])
        self.assertEqual(actions.keys[0][0], "esc")
        self.assertEqual(actions.clicks, [(120, 210)])
        self.assertEqual(result["entry_box"]["name"], "羁遇")

    def test_gift_phone_entry_ensures_world_before_source_open_esc_panel(self):
        events = []

        class Source:
            def openESCpanel(self):
                events.append("openESCpanel")
                return SimpleNamespace(name="esc_phone_menu", x=900, y=80, width=300, height=600, confidence=0.95)

        class Actions(FakeActions):
            def __init__(self):
                super().__init__()
                self.ui = SimpleNamespace(source=Source())

            def ensure_daily_main(self):
                events.append("ensure_daily_main")
                return True

        actions = Actions()
        flow = SimpleNamespace(
            actions=actions,
            ui=FakeOCRUI(
                [
                    [SimpleNamespace(name="羁遇", x=100, y=200, width=40, height=20, confidence=0.95)],
                    [
                        SimpleNamespace(name="羁遇", x=80, y=80, width=40, height=20, confidence=0.95),
                        SimpleNamespace(name="赠礼", x=900, y=120, width=40, height=20, confidence=0.95),
                    ],
                ]
            ),
        )
        runtime = DailyGiftDefaultRuntime(flow)

        result = runtime.enter_from_phone_menu()

        self.assertTrue(result["ok"])
        self.assertEqual(events, ["ensure_daily_main", "openESCpanel"])
        self.assertEqual(actions.clicks, [(120, 210)])

    def test_gift_phone_entry_retries_when_source_open_leaves_stale_panel(self):
        events = []

        class Source:
            def openESCpanel(self):
                events.append("openESCpanel")
                return SimpleNamespace(name="esc_phone_menu", x=900, y=80, width=300, height=600, confidence=0.95)

        class Actions(FakeActions):
            def __init__(self):
                super().__init__()
                self.ui = SimpleNamespace(source=Source())

            def ensure_daily_main(self):
                events.append("ensure_daily_main")
                return True

        actions = Actions()
        flow = SimpleNamespace(
            actions=actions,
            ui=FakeOCRUI(
                [
                    [SimpleNamespace(name="探索指南", x=50, y=30, width=120, height=30, confidence=0.99)],
                    [SimpleNamespace(name="羁遇", x=100, y=200, width=40, height=20, confidence=0.95)],
                    [
                        SimpleNamespace(name="羁遇", x=80, y=80, width=40, height=20, confidence=0.95),
                        SimpleNamespace(name="赠礼", x=900, y=120, width=40, height=20, confidence=0.95),
                    ],
                ]
            ),
        )
        runtime = DailyGiftDefaultRuntime(flow)

        result = runtime.enter_from_phone_menu()

        self.assertTrue(result["ok"])
        self.assertEqual(events, ["ensure_daily_main", "openESCpanel", "ensure_daily_main"])
        self.assertEqual([key for key, _kwargs in actions.keys], ["esc", "esc"])
        self.assertEqual(actions.clicks, [(120, 210)])
        self.assertEqual(result["open"]["attempts"][0]["method"], "openESCpanel")
        self.assertEqual(result["open"]["attempts"][1]["stale_panel_close"]["action"], "close_stale_panel_before_phone_menu_retry")

    def test_dry_run_does_not_click_and_records_evidence(self):
        flow = FakeFlow([DailyActivityPage(task_cards=[card(), card(title="赠送1次礼物", x=360)])])

        result = DailyTaskItemActionRunner(flow, dry_run=True).run()

        self.assertTrue(result["ok"])
        self.assertFalse(result["mutation_performed"])
        self.assertEqual(flow.actions.clicks, [])
        self.assertEqual(flow.actions.ensure_daily_main_calls, 1)
        self.assertEqual(result["preflight"], {"attempted": True, "ok": True, "reason": ""})
        item = result["items"][0]
        self.assertTrue(item["eligible"])
        self.assertEqual(item["action"], "领取")
        self.assertIsNotNone(item["row_evidence"])
        self.assertIsNotNone(item["button_evidence"])
        self.assertEqual(item["screenshot_id"], "activity-1")
        self.assertEqual(result["skipped"], [])
        self.assertEqual(result["blockers"], [])
        self.assertNotIn("gift_task_no_mutation", str(result))

    def test_real_run_clicks_gate_passed_safe_claim(self):
        before = DailyActivityPage(task_cards=[card()])
        after = DailyActivityPage(task_cards=[])
        flow = FakeFlow([before, after])

        result = DailyTaskItemActionRunner(flow, dry_run=False).run()

        self.assertTrue(result["ok"])
        self.assertEqual(flow.actions.clicks, [(230, 298)])
        self.assertTrue(result["mutation_performed"])
        self.assertTrue(result["mutation_verified"])
        self.assertTrue(result["task_completed"])
        action = result["actions"][0]
        self.assertEqual(action["target_point"], [230, 298])
        self.assertEqual(action["post_verification"]["post_action_result"], "task_reward_claimed")

    def test_low_confidence_does_not_click(self):
        flow = FakeFlow([DailyActivityPage(task_cards=[card(confidence=0.2)])])

        result = DailyTaskItemActionRunner(flow, dry_run=False).run()

        self.assertTrue(result["ok"])
        self.assertEqual(flow.actions.clicks, [])
        self.assertEqual(result["items"][0]["blocker_reason"], "low_confidence")

    def test_unknown_button_does_not_click(self):
        flow = FakeFlow([DailyActivityPage(task_cards=[card(action="unknown", state="unknown")])])

        result = DailyTaskItemActionRunner(flow, dry_run=False).run()

        self.assertEqual(flow.actions.clicks, [])
        self.assertEqual(result["items"][0]["blocker_reason"], "unknown_button")

    def test_panel_open_failure_retries_after_escape_recovery(self):
        flow = FakeFlow([DailyActivityPage(task_cards=[card()]), DailyActivityPage(task_cards=[])], detected=[False, True])

        result = DailyTaskItemActionRunner(flow, dry_run=False).run()

        self.assertTrue(result["ok"])
        self.assertEqual(flow.actions.keys[0][0], "esc")
        self.assertTrue(result["panel_recovery"]["attempted"])
        self.assertTrue(result["panel"]["daily_activity_panel_detected"])

    def test_no_task_cards_records_gift_absent_reason_and_reward_remaining_count(self):
        flow = FakeFlow([milestone_page()])

        result = DailyTaskItemActionRunner(flow, dry_run=False).run()

        self.assertTrue(result["ok"])
        self.assertFalse(result["mutation_performed"])
        self.assertEqual(result["skipped"], [{"reason": "task_list_roi_not_confirmed"}])
        self.assertEqual(result["gift"]["reason"], "gift_task_not_detected_current_daily_state")
        self.assertFalse(result["gift"]["detected"])
        self.assertEqual(result["gift"]["claimable_rewards_remaining"], 0)
        self.assertEqual(result["gift"]["claimable_rewards_reason"], "")

    def test_ambiguous_duplicate_row_does_not_click(self):
        flow = FakeFlow([DailyActivityPage(task_cards=[card(x=100), card(x=360)])])

        result = DailyTaskItemActionRunner(flow, dry_run=False).run()

        self.assertEqual(flow.actions.clicks, [])
        self.assertTrue(all(item["blocker_reason"] == "ambiguous_row_duplicate" for item in result["items"]))

    def test_unsafe_resource_and_battle_tasks_do_not_click(self):
        page = DailyActivityPage(
            task_cards=[
                card(title="累计消耗180点本性像素"),
                card(title="累计击败5个敌人", x=360),
            ]
        )
        flow = FakeFlow([page])

        result = DailyTaskItemActionRunner(flow, dry_run=False).run()

        self.assertEqual(flow.actions.clicks, [])
        reasons = [item["blocker_reason"] for item in result["items"]]
        self.assertEqual(reasons, ["resource_consuming_task_deferred", "battle_task_deferred"])
        self.assertFalse(result["mutation_performed"])

    def test_gift_task_is_not_blocked_as_no_mutation(self):
        item = card(title="赠送1次礼物", action="前往", state="go")
        flow = FakeFlow([DailyActivityPage(task_cards=[item])])

        result = DailyTaskItemActionRunner(flow, dry_run=True).run()

        self.assertTrue(result["items"][0]["eligible"])
        self.assertEqual(result["items"][0]["blocker_reason"], "")
        self.assertNotIn("gift_task_no_mutation", str(result))

    def test_gift_only_defers_non_gift_rows_but_keeps_gift_eligible(self):
        page = DailyActivityPage(
            task_cards=[
                card(title="每日登录1次"),
                card(title="赠送1次礼物", action="前往", state="go", x=360),
            ]
        )
        flow = FakeFlow([page])

        result = DailyTaskItemActionRunner(flow, dry_run=True, gift_only=True).run()

        self.assertEqual(result["items"][0]["blocker_reason"], "gift_only_mode_deferred")
        self.assertFalse(result["items"][0]["eligible"])
        self.assertEqual(result["items"][1]["blocker_reason"], "")
        self.assertTrue(result["items"][1]["eligible"])

    def test_gift_only_absent_task_reports_consumed_daily_state(self):
        flow = FakeFlow([DailyActivityPage(task_cards=[card(title="每日登录1次")])])

        result = DailyTaskItemActionRunner(flow, dry_run=True, gift_only=True).run()

        self.assertTrue(result["ok"])
        self.assertFalse(result["gift"]["detected"])
        self.assertEqual(result["gift"]["reason"], "daily_task_state_unavailable_because_already_consumed")

    def test_gift_real_run_enters_default_gift_flow_and_completes_task(self):
        gift = card(title="赠送1次礼物", action="前往", state="go")
        after = card(title="赠送1次礼物", action="领取", state="claimable")
        runtime = FakeGiftRuntime()
        flow = FakeFlow(
            [
                DailyActivityPage(task_cards=[gift]),
                DailyActivityPage(task_cards=[after]),
                DailyActivityPage(task_cards=[after]),
                DailyActivityPage(task_cards=[]),
                milestone_page(claimable=True),
                milestone_page(),
            ]
        )

        result = DailyTaskItemActionRunner(
            flow,
            dry_run=False,
            gift_runtime_factory=lambda flow: runtime,
        ).run()

        self.assertTrue(result["ok"])
        self.assertEqual(runtime.send_calls, 1)
        self.assertTrue(result["mutation_performed"])
        self.assertTrue(result["mutation_verified"])
        self.assertTrue(result["handler_completed"])
        self.assertTrue(result["task_completed"])
        self.assertEqual(result["gift"]["selected_character"], "default_visible")
        self.assertEqual(result["gift"]["selected_item"], "default_item")
        self.assertEqual(result["gift"]["sent_total"], 1)
        self.assertTrue(result["gift"]["task_reward_claimed"])
        self.assertEqual(result["gift"]["activity_rewards_claimed"], 1)
        self.assertEqual(result["gift"]["claimable_rewards_remaining"], 0)

    def test_gift_claimable_after_prior_send_claims_task_reward_without_resending(self):
        claimable = card(title="赠送1次礼物", action="领取", state="claimable")
        flow = FakeFlow(
            [
                DailyActivityPage(task_cards=[claimable]),
                DailyActivityPage(task_cards=[claimable]),
                DailyActivityPage(task_cards=[]),
                milestone_page(),
            ]
        )

        result = DailyTaskItemActionRunner(flow, dry_run=False).run()

        self.assertTrue(result["ok"])
        self.assertTrue(result["mutation_performed"])
        self.assertTrue(result["mutation_verified"])
        self.assertTrue(result["task_completed"])
        self.assertEqual(result["gift"]["sent_total"], 1)
        self.assertTrue(result["gift"]["task_reward_claimed"])
        self.assertEqual(result["gift"]["claimable_rewards_remaining"], 0)

    def test_gift_page_only_is_not_task_completed(self):
        gift = card(title="赠送1次礼物", action="前往", state="go")
        runtime = FakeGiftRuntime(
            GiftDefaultSendResult(
                ok=False,
                reason="gift_send_button_not_found",
                mutation_performed=False,
                mutation_verified=False,
                handler_completed=True,
                selected_character="default_visible",
            )
        )
        flow = FakeFlow([DailyActivityPage(task_cards=[gift])])

        result = DailyTaskItemActionRunner(
            flow,
            dry_run=False,
            gift_runtime_factory=lambda flow: runtime,
        ).run()

        self.assertTrue(result["ok"])
        self.assertTrue(result["handler_completed"])
        self.assertFalse(result["task_completed"])
        self.assertFalse(result["mutation_performed"])
        self.assertEqual(result["gift"]["reason"], "gift_send_button_not_found")

    def test_gift_send_without_task_verification_fails_completion(self):
        gift = card(title="赠送1次礼物", action="前往", state="go")
        runtime = FakeGiftRuntime()
        flow = FakeFlow([DailyActivityPage(task_cards=[gift]), DailyActivityPage(task_cards=[gift])])

        result = DailyTaskItemActionRunner(
            flow,
            dry_run=False,
            gift_runtime_factory=lambda flow: runtime,
        ).run()

        self.assertFalse(result["ok"])
        self.assertTrue(result["mutation_performed"])
        self.assertFalse(result["mutation_verified"])
        self.assertTrue(result["handler_completed"])
        self.assertFalse(result["task_completed"])
        self.assertEqual(result["gift"]["reason"], "gift_post_action_verification_failed")

    def test_gift_send_completed_but_reward_claim_not_verified_fails(self):
        gift = card(title="赠送1次礼物", action="前往", state="go")
        after = card(title="赠送1次礼物", action="领取", state="claimable")
        runtime = FakeGiftRuntime()
        flow = FakeFlow(
            [
                DailyActivityPage(task_cards=[gift]),
                DailyActivityPage(task_cards=[after]),
                DailyActivityPage(task_cards=[after]),
                DailyActivityPage(task_cards=[after]),
            ]
        )

        result = DailyTaskItemActionRunner(
            flow,
            dry_run=False,
            gift_runtime_factory=lambda flow: runtime,
        ).run()

        self.assertFalse(result["ok"])
        self.assertTrue(result["mutation_performed"])
        self.assertFalse(result["mutation_verified"])
        self.assertTrue(result["task_completed"])
        self.assertFalse(result["gift"]["task_reward_claimed"])
        self.assertEqual(result["gift"]["reason"], "gift_task_reward_still_claimable")

    def test_missing_row_or_button_does_not_click(self):
        page = DailyActivityPage(task_cards=[card(row=False), card(button=False, x=360)])
        flow = FakeFlow([page])

        result = DailyTaskItemActionRunner(flow, dry_run=False).run()

        self.assertEqual(flow.actions.clicks, [])
        self.assertEqual([item["blocker_reason"] for item in result["items"]], ["row_bbox_missing", "button_bbox_missing"])

    def test_stale_coordinates_rejected_after_scroll(self):
        item = card()
        flow = FakeFlow([DailyActivityPage(task_cards=[item])])
        runner = DailyTaskItemActionRunner(flow, dry_run=False)
        flow.record_daily_activity_analysis(analysis_for(DailyActivityPage(task_cards=[item])))
        record = runner._record_for_card(item, duplicate_keys=set())
        flow.snapshot.screenshot_id = "after_scroll"

        runner._execute_card(item, record)

        self.assertEqual(flow.actions.clicks, [])
        self.assertEqual(record.blocker_reason, "stale_screenshot_id")
        self.assertFalse(record.mutation_performed)

    def test_failed_post_verification_records_unverified_mutation(self):
        item = card()
        flow = FakeFlow([DailyActivityPage(task_cards=[item]), DailyActivityPage(task_cards=[item])])

        result = DailyTaskItemActionRunner(flow, dry_run=False).run()

        self.assertFalse(result["ok"])
        self.assertTrue(result["mutation_performed"])
        self.assertFalse(result["mutation_verified"])
        self.assertFalse(result["task_completed"])
        self.assertEqual(result["items"][0]["blocker_reason"], "post_verification_failed")

    def test_handler_completed_is_not_task_completed_for_go_action(self):
        item = card(title="每日登录1次", action="前往", state="go")
        flow = FakeFlow([DailyActivityPage(task_cards=[item]), DailyActivityPage(task_cards=[])])

        result = DailyTaskItemActionRunner(flow, dry_run=False, allow_go_actions=True).run()

        self.assertTrue(result["ok"])
        self.assertTrue(result["handler_completed"])
        self.assertFalse(result["task_completed"])
        self.assertTrue(result["mutation_performed"])
        self.assertTrue(result["mutation_verified"])

    def test_gift_box_text_prefers_ocr_text_over_generic_name(self):
        box = SimpleNamespace(name="generic_button", text="赠礼")

        self.assertEqual(DailyGiftDefaultRuntime._box_text(box), "赠礼")

    def test_progress_complete_does_not_treat_one_of_ten_as_done(self):
        self.assertFalse(DailyTaskItemActionRunner._progress_is_complete("1/10"))
        self.assertTrue(DailyTaskItemActionRunner._progress_is_complete("10/10"))

    def test_daily_task_facade_returns_runner_summary(self):
        task = object.__new__(DailyTask)
        flow = FakeFlow([DailyActivityPage(task_cards=[card()])])

        with patch("src.tasks.DailyTask.DailyActivityFlow.from_task", return_value=flow):
            result = DailyTask.run_daily_task_items(task, dry_run=True)

        self.assertTrue(result["ok"])
        self.assertIn("items", result)


class TestDailyTaskItemScriptRunner(unittest.TestCase):
    def test_script_dry_run_summary_is_non_mutating(self):
        task = object()
        flow = FakeFlow([DailyActivityPage(task_cards=[card()])])
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("scripts.run_daily_task_items.DailyActivityFlow.from_task", return_value=flow):
                runner = DailyTaskItemsValidationRunner(
                    "dry-run",
                    working_root=Path(temp_dir),
                    session_factory=lambda output_dir: FakeSession(task),
                    process_checker=lambda: True,
                    git_info_provider=lambda: {"git_branch": "b", "git_head": "h", "dirty": False},
                    timestamp_provider=lambda: "stamp",
                )

                summary = runner.run()

        self.assertTrue(summary["ok"])
        self.assertFalse(summary["dirty"])
        self.assertFalse(summary["mutation_performed"])
        self.assertFalse(summary["modules"]["gift"]["mutation_performed"])
        self.assertEqual(summary["items"][0]["action"], "领取")

    def test_script_expected_resolution_mismatch_stops_before_actions(self):
        task = object()
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("scripts.run_daily_task_items.DailyActivityFlow.from_task") as from_task:
                runner = DailyTaskItemsValidationRunner(
                    "dry-run",
                    working_root=Path(temp_dir),
                    session_factory=lambda output_dir: FakeSession(
                        task,
                        window={"width": 1280, "height": 720, "title": "HTGame", "hwnd": "1"},
                    ),
                    process_checker=lambda: True,
                    git_info_provider=lambda: {"git_branch": "b", "git_head": "h", "dirty": False},
                    timestamp_provider=lambda: "stamp",
                    expected_resolution=(1920, 1080),
                )

                summary = runner.run()

        self.assertFalse(summary["ok"])
        self.assertEqual(summary["expected_resolution"], {"width": 1920, "height": 1080})
        self.assertTrue(any("resolution_mismatch" in item for item in summary["errors"]))
        from_task.assert_not_called()

    def test_script_expected_resolution_match_runs_actions(self):
        task = object()
        flow = FakeFlow([DailyActivityPage(task_cards=[card()])])
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("scripts.run_daily_task_items.DailyActivityFlow.from_task", return_value=flow):
                runner = DailyTaskItemsValidationRunner(
                    "dry-run",
                    working_root=Path(temp_dir),
                    session_factory=lambda output_dir: FakeSession(
                        task,
                        window={"width": 1920, "height": 1080, "title": "HTGame", "hwnd": "1"},
                    ),
                    process_checker=lambda: True,
                    git_info_provider=lambda: {"git_branch": "b", "git_head": "h", "dirty": False},
                    timestamp_provider=lambda: "stamp",
                    expected_resolution=(1920, 1080),
                )

                summary = runner.run()

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["window"]["width"], 1920)
        self.assertEqual(summary["expected_resolution"], {"width": 1920, "height": 1080})
        self.assertEqual(summary["items"][0]["action"], "领取")

    def test_script_records_gift_summary_fields(self):
        task = object()
        runner_result = {
            "ok": True,
            "preflight": {"attempted": True, "ok": True, "reason": ""},
            "mutation_performed": True,
            "mutation_verified": True,
            "task_completed": True,
            "handler_completed": True,
            "items": [],
            "actions": [],
            "skipped": [],
            "blockers": [],
            "gift": {
                "detected": True,
                "mutation_performed": True,
                "mutation_verified": True,
                "selected_character": "default_visible",
                "selected_item": "default_item",
                "sent_total": 1,
                "task_reward_claimed": True,
                "activity_rewards_claimed": 1,
                "claimable_rewards_remaining": 0,
                "claimable_rewards_reason": "",
                "handler_completed": True,
                "task_completed": True,
                "reason": "",
            },
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("scripts.run_daily_task_items.DailyTaskItemActionRunner") as runner_cls:
                runner_cls.return_value.run.return_value = runner_result
                runner = DailyTaskItemsValidationRunner(
                    "real-run",
                    working_root=Path(temp_dir),
                    session_factory=lambda output_dir: FakeSession(task),
                    process_checker=lambda: True,
                    git_info_provider=lambda: {"git_branch": "b", "git_head": "h", "dirty": False},
                    timestamp_provider=lambda: "stamp",
                )

                summary = runner.run()

        self.assertTrue(summary["gift"]["mutation_verified"])
        self.assertEqual(summary["gift"]["sent_total"], 1)
        self.assertTrue(summary["modules"]["gift"]["mutation_performed"])
        self.assertTrue(summary["modules"]["gift"]["mutation_verified"])
        self.assertEqual(summary["modules"]["gift"]["selected_character"], "default_visible")
        self.assertTrue(summary["modules"]["gift"]["task_reward_claimed"])
        self.assertEqual(summary["modules"]["gift"]["claimable_rewards_remaining"], 0)


if __name__ == "__main__":
    unittest.main()
