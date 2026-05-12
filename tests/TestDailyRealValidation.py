import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from scripts.run_daily_real_validation import (
    DailyRealValidationRunner,
    TASK_KEYS,
    extract_window_info,
    parse_resolution,
)
from src.tasks.FlowResult import FlowResult


class FakeSession:
    def __init__(self, task, window=None):
        self.task = task
        self.window = window or {"width": 2560, "height": 1600, "title": "HTGame", "hwnd": "1234"}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeTask:
    TASK_SKIPPED = object()
    MAX_ACTIVITY_MISSION_CLAIMS = 5

    def __init__(self):
        self.calls = []
        self.config = {}
        self.task_skip_reasons = {}
        self.activity_cards_claimed = 0
        self.activity_no_claimable = True
        self.activity_reason = "no claimable reward"
        self.activity_panel_detected = True
        self.mail_result = True
        self.periodic_result = True

    def _ensure_daily_main(self):
        self.calls.append("ensure")

    def claim_mail(self):
        self.calls.append("mail")
        if isinstance(self.mail_result, BaseException):
            raise self.mail_result
        return self.mail_result

    def claim_battle_pass_rewards(self):
        self.calls.append("periodic")
        return self.periodic_result

    def _open_activity_panel_result(self):
        self.calls.append("open_activity")
        return SimpleNamespace(
            f1_panel_opened=True,
            daily_activity_panel_detected=self.activity_panel_detected,
            reason="activity panel ready" if self.activity_panel_detected else "daily panel not found",
        )

    def _analyze_daily_activity(self, panel_detected=True):
        self.calls.append("analyze_activity")
        return SimpleNamespace(
            no_claimable_reward=self.activity_no_claimable,
            reason=self.activity_reason,
            page=SimpleNamespace(),
            to_dict=lambda: {
                "no_claimable_reward": self.activity_no_claimable,
                "reason": self.activity_reason,
            },
        )

    def _record_daily_activity_analysis(self, analysis):
        self.calls.append("record_activity")

    def _claim_completed_activity_card_rewards(self, page, max_clicks=5):
        self.calls.append("claim_activity_cards")
        return self.activity_cards_claimed

    def _claim_activity_milestone_rewards(self, page):
        self.calls.append("claim_activity_milestone")
        return False

    def complete_daily_activities(self):
        self.calls.append("complete_daily")
        open_result = self._open_activity_panel_result()
        if not open_result.daily_activity_panel_detected:
            self.task_skip_reasons["完成每日活跃度"] = open_result.reason
            return self.TASK_SKIPPED
        analysis = self._analyze_daily_activity(panel_detected=True)
        self._record_daily_activity_analysis(analysis)
        self._last_daily_activity_analysis = analysis
        self._last_daily_activity_handlers_completed = False
        self._last_daily_activity_cards_claimed = self._claim_completed_activity_card_rewards(
            analysis.page,
            max_clicks=self.MAX_ACTIVITY_MISSION_CLAIMS,
        )
        if self._last_daily_activity_cards_claimed:
            return True
        self.task_skip_reasons["完成每日活跃度"] = self.activity_reason
        return self.TASK_SKIPPED

    def claim_activity_rewards(self):
        self.calls.append("claim_activity_rewards")
        if self.activity_no_claimable:
            self.task_skip_reasons["领取活跃度奖励"] = self.activity_reason
            return self.TASK_SKIPPED
        return True


class PanelRecoveryTask(FakeTask):
    def __init__(self):
        super().__init__()
        self.world_checks = [False, False, True]

    def in_team_and_world(self):
        self.calls.append("world_check")
        if self.world_checks:
            return self.world_checks.pop(0)
        return True

    def _send_foreground_key(self, key, **kwargs):
        self.calls.append(f"foreground:{key}")
        return True


class VerifiedActivityTask(FakeTask):
    def complete_daily_activities(self):
        self.calls.append("complete_daily")
        self._last_daily_activity_analysis = SimpleNamespace(
            no_claimable_reward=False,
            reason="activity card claimed",
            to_dict=lambda: {"reason": "activity card claimed"},
        )
        self._last_daily_activity_handlers_completed = False
        self._last_daily_activity_cards_claimed = 1
        self._last_daily_activity_flow_details = {
            "完成每日活跃度": {
                "status": "done",
                "ok": True,
                "reason": "activity_cards_claimed",
                "mutated": True,
                "details": {
                    "mutation_performed": True,
                    "mutation_verified": True,
                    "gate_results": [
                        {
                            "allowed": True,
                            "executed": True,
                            "verified": True,
                            "mutation_performed": True,
                            "mutation_verified": True,
                        }
                    ],
                },
            }
        }
        return True

    def claim_activity_rewards(self):
        self.calls.append("claim_activity_rewards")
        self.task_skip_reasons["领取活跃度奖励"] = "no claimable reward"
        return self.TASK_SKIPPED


class RewardOverwriteActivityTask(FakeTask):
    def complete_daily_activities(self):
        self.calls.append("complete_daily")
        self._last_daily_activity_analysis = SimpleNamespace(
            no_claimable_reward=False,
            reason="handler completed",
            to_dict=lambda: {"reason": "handler completed"},
        )
        self._last_daily_activity_handlers_completed = True
        self._last_daily_activity_cards_claimed = 1
        self._last_daily_activity_flow_details = {
            "完成每日活跃度": {
                "status": "done",
                "ok": True,
                "reason": "activity_handler_completed",
                "mutated": True,
                "details": {
                    "cards_claimed": 1,
                    "task_completed": True,
                    "mutation_performed": True,
                    "mutation_verified": True,
                },
            }
        }
        return True

    def claim_activity_rewards(self):
        self.calls.append("claim_activity_rewards")
        self._last_daily_activity_cards_claimed = 0
        self._last_daily_activity_handlers_completed = False
        self._last_daily_activity_flow_details["领取活跃度奖励"] = {
            "status": "skipped",
            "ok": True,
            "reason": "活跃度未达到100，默认延后领取阶段奖励",
            "mutated": False,
            "details": {"skipped_reason": "活跃度未达到100，默认延后领取阶段奖励"},
        }
        self.task_skip_reasons["领取活跃度奖励"] = "活跃度未达到100，默认延后领取阶段奖励"
        return self.TASK_SKIPPED


class HandlerOnlyActivityTask(FakeTask):
    def complete_daily_activities(self):
        self.calls.append("complete_daily")
        self._last_daily_activity_analysis = SimpleNamespace(
            no_claimable_reward=False,
            reason="handler action verified",
            to_dict=lambda: {"reason": "handler action verified"},
        )
        self._last_daily_activity_handlers_completed = True
        self._last_daily_activity_cards_claimed = 0
        self._last_daily_activity_flow_details = {
            "完成每日活跃度": {
                "status": "done",
                "ok": True,
                "reason": "activity_handler_completed",
                "mutated": True,
                "details": {
                    "handler_completed": True,
                    "task_completed": False,
                    "cards_claimed": 0,
                    "mutation_performed": True,
                    "mutation_verified": True,
                },
            }
        }
        return True

    def claim_activity_rewards(self):
        self.calls.append("claim_activity_rewards")
        self._last_daily_activity_flow_details["领取活跃度奖励"] = {
            "status": "skipped",
            "ok": True,
            "reason": "活跃度未达到100，默认延后领取阶段奖励",
            "mutated": False,
            "details": {"skipped_reason": "活跃度未达到100，默认延后领取阶段奖励"},
        }
        self.task_skip_reasons["领取活跃度奖励"] = "活跃度未达到100，默认延后领取阶段奖励"
        return self.TASK_SKIPPED


class FullActivityTask(FakeTask):
    def complete_daily_activities(self):
        self.calls.append("complete_daily")
        self._last_daily_activity_analysis = SimpleNamespace(
            no_claimable_reward=False,
            reason="activity full",
            to_dict=lambda: {
                "activity_full": True,
                "all_daily_done": True,
                "page": {"activity_score": 100, "task_cards": []},
            },
        )
        self._last_daily_activity_handlers_completed = True
        self._last_daily_activity_cards_claimed = 1
        self._last_daily_activity_flow_details = {
            "完成每日活跃度": {
                "status": "done",
                "ok": True,
                "reason": "activity_handler_completed",
                "mutated": True,
                "details": {
                    "handler_completed": True,
                    "task_completed": True,
                    "cards_claimed": 1,
                    "mutation_performed": True,
                    "mutation_verified": True,
                },
            }
        }
        return True

    def claim_activity_rewards(self):
        self.calls.append("claim_activity_rewards")
        return True


class IncompleteDailyFullActivityTask(FakeTask):
    def complete_daily_activities(self):
        self.calls.append("complete_daily")
        cards = [
            {
                "title": "任意消费1次方斯",
                "progress_text": "0/1",
                "reward_points": 20,
                "action": "前往",
                "state": "go",
            },
            {
                "title": "赠送1次礼物",
                "progress_text": "0/1",
                "reward_points": 20,
                "action": "前往",
                "state": "go",
            },
        ]
        self._last_daily_activity_analysis = SimpleNamespace(
            no_claimable_reward=True,
            reason="activity score below 100",
            to_dict=lambda: {
                "activity_full": False,
                "all_daily_done": False,
                "page": {"activity_score": 50, "task_cards": cards},
            },
        )
        self._last_daily_activity_handlers_completed = True
        self._last_daily_activity_cards_claimed = 0
        self._last_daily_activity_flow_details = {
            "完成每日活跃度": {
                "status": "done",
                "ok": True,
                "reason": "activity_handler_completed",
                "mutated": True,
                "details": {
                    "handler_completed": True,
                    "task_completed": False,
                    "cards_claimed": 0,
                    "mutation_performed": True,
                    "mutation_verified": True,
                },
            }
        }
        return True

    def claim_activity_rewards(self):
        self.calls.append("claim_activity_rewards")
        self.task_skip_reasons["领取活跃度奖励"] = "活跃度未达到100，默认延后领取阶段奖励"
        return self.TASK_SKIPPED


class UnverifiedActivityMutationTask(FakeTask):
    def complete_daily_activities(self):
        self.calls.append("complete_daily")
        self._last_daily_activity_analysis = SimpleNamespace(
            no_claimable_reward=True,
            reason="post verification failed",
            to_dict=lambda: {"reason": "post verification failed"},
        )
        self._last_daily_activity_handlers_completed = False
        self._last_daily_activity_cards_claimed = 0
        self._last_daily_activity_flow_details = {
            "完成每日活跃度": {
                "status": "done",
                "ok": True,
                "reason": "daily_activity_tab_opened",
                "mutated": True,
                "details": {
                    "mutation_performed": True,
                    "mutation_verified": False,
                    "failure_reason": "post_verification_failed",
                },
            }
        }
        return FlowResult.success(
            "daily_activity_tab_opened",
            mutated=True,
            details={
                "mutation_performed": True,
                "mutation_verified": False,
                "failure_reason": "post_verification_failed",
            },
        )

    def claim_activity_rewards(self):
        self.calls.append("claim_activity_rewards")
        self.task_skip_reasons["领取活跃度奖励"] = "no claimable reward"
        return self.TASK_SKIPPED


class FakeCoffeeRuntime:
    def __init__(self, task):
        self.task = task

    def run(self):
        self.task.calls.append("coffee")
        return SimpleNamespace(
            ok=True,
            skip_reason="",
            income_claimed=True,
            real_purchase_performed=True,
            selected_options=[
                SimpleNamespace(identity="better-drink", price_value=300.12, name="better")
            ],
            selected_actions=[
                "claim_income",
                "open_product_editor:old-drink",
                "deselect_product:old-drink",
                "select_product:better-drink",
                "open_supply",
                "buy_supply",
                "confirm_home_delivery",
            ],
        )


class NoConsumptionCoffeeRuntime:
    def __init__(self, task):
        self.task = task

    def run(self):
        self.task.calls.append("coffee")
        return SimpleNamespace(
            ok=True,
            skip_reason="",
            income_claimed=True,
            real_purchase_performed=False,
            selected_options=[],
            selected_actions=[
                "claim_income",
                "supply_recently_active_not_needed:23",
                "product_switch_not_needed",
            ],
        )


class FailedProductSwitchCoffeeRuntime:
    def __init__(self, task):
        self.task = task

    def run(self):
        self.task.calls.append("coffee")
        return SimpleNamespace(
            ok=False,
            skip_reason="商品替换失败: 已取消old但未能选择new",
            income_claimed=False,
            real_purchase_performed=False,
            selected_options=[],
            selected_actions=[
                "open_product_editor:old",
                "deselect_product:old",
                "select_product_not_found:new",
            ],
        )


class FailedSupplyVerificationCoffeeRuntime:
    def __init__(self, task):
        self.task = task

    def run(self):
        self.task.calls.append("coffee")
        return SimpleNamespace(
            ok=False,
            skip_reason="24小时补货未完成: 未检测到送货上门确认按钮，未验证补货成功",
            income_claimed=True,
            real_purchase_performed=False,
            selected_options=[],
            selected_actions=[
                "claim_income",
                "open_supply",
                "select_supply_duration:24小时",
                "buy_supply",
                "buy_supply_retry_after_no_prompt",
                "supply_duration_blocked:24小时:未检测到送货上门确认按钮，未验证补货成功",
            ],
        )


class FakeGiftTaskItemRunner:
    def __init__(self, result=None):
        self.result = result or {
            "ok": True,
            "preflight": {"attempted": True, "ok": True, "reason": ""},
            "mutation_performed": False,
            "mutation_verified": False,
            "handler_completed": False,
            "task_completed": False,
            "items": [],
            "actions": [],
            "skipped": [],
            "blockers": [],
            "gift": {
                "detected": False,
                "mutation_performed": False,
                "mutation_verified": False,
                "selected_character": "",
                "selected_item": "",
                "sent_total": 0,
                "task_reward_claimed": False,
                "activity_rewards_claimed": 0,
                "claimable_rewards_remaining": 0,
                "claimable_rewards_reason": "",
                "handler_completed": False,
                "task_completed": False,
                "reason": "daily_task_state_unavailable_because_already_consumed",
            },
        }

    def run(self):
        return self.result


class FakeDirectGiftRuntime:
    def __init__(self, flow, *, verified=True):
        self.flow = flow
        self.verified = verified

    def enter_from_phone_menu(self):
        return {
            "ok": True,
            "reason": "",
            "entry_box": {"name": "羁遇", "x": 100, "y": 200, "width": 40, "height": 20, "confidence": 0.95},
            "actions": [
                {
                    "recognized_ui": "gift_phone_menu_entry_ji_yu",
                    "executed": True,
                    "verified": True,
                    "mutation_performed": True,
                    "mutation_verified": True,
                }
            ],
        }

    def send_default_gift(self, *, direct_verify=False):
        return {
            "ok": bool(self.verified),
            "reason": "gift_send_verified" if self.verified else "gift_direct_post_verification_failed",
            "mutation_performed": True,
            "mutation_verified": bool(self.verified),
            "handler_completed": True,
            "selected_character": "default_visible",
            "selected_item": "affinity:300",
            "sent_total": 1,
            "actions": [
                {
                    "recognized_ui": "gift_send_button",
                    "executed": True,
                    "verified": bool(self.verified),
                    "mutation_performed": True,
                    "mutation_verified": bool(self.verified),
                }
            ],
            "details": {"direct_verify": direct_verify},
        }


class NoSendDirectGiftRuntime:
    def __init__(self, flow):
        self.flow = flow

    def enter_from_phone_menu(self):
        return {"ok": False, "reason": "gift_phone_menu_entry_not_found", "actions": []}


def make_runner(
    mode,
    task=None,
    process_exists=True,
    window=None,
    expected_resolution=None,
    gift_task_result=None,
    gift_runtime_factory=None,
):
    temp = tempfile.TemporaryDirectory()
    task = task or FakeTask()

    def gift_task_factory(flow):
        task.calls.append("gift_task_items")
        return FakeGiftTaskItemRunner(gift_task_result)

    runner = DailyRealValidationRunner(
        mode,
        working_root=Path(temp.name) / "working",
        session_factory=lambda output_dir: FakeSession(task, window=window),
        process_checker=lambda: process_exists,
        git_info_provider=lambda: {"git_branch": "test", "git_head": "abc123", "dirty": False},
        timestamp_provider=lambda: "20260505_010203",
        coffee_runtime_factory=FakeCoffeeRuntime,
        gift_task_item_runner_factory=gift_task_factory,
        gift_runtime_factory=gift_runtime_factory or (lambda flow: FakeDirectGiftRuntime(flow)),
        command=f"test --mode {mode}",
        expected_resolution=expected_resolution,
    )
    runner._tempdir = temp
    runner._fake_task = task
    return runner


class TestDailyRealValidation(unittest.TestCase):
    def test_parse_resolution_accepts_x_and_star(self):
        self.assertEqual(parse_resolution("1920x1080"), (1920, 1080))
        self.assertEqual(parse_resolution("1920*1080"), (1920, 1080))

    def test_extract_window_info_preserves_resolution_details(self):
        session = FakeSession(
            FakeTask(),
            window={
                "width": 1920,
                "height": 1080,
                "title": "HTGame",
                "hwnd": "1234",
                "client_width": 1920,
                "client_height": 1080,
                "capture_width": 1920,
                "capture_height": 1080,
                "window_width": 1935,
                "window_height": 1117,
            },
        )

        info = extract_window_info(session)

        self.assertEqual(info["width"], 1920)
        self.assertEqual(info["height"], 1080)
        self.assertEqual(info["client_width"], 1920)
        self.assertEqual(info["capture_width"], 1920)
        self.assertEqual(info["window_width"], 1935)

    def test_expected_resolution_mismatch_skips_tasks_without_running(self):
        task = FakeTask()
        runner = make_runner(
            "daily-task-only",
            task,
            window={"width": 1280, "height": 720, "title": "HTGame", "hwnd": "1234"},
            expected_resolution=(1920, 1080),
        )

        summary = runner.run()

        self.assertFalse(summary["ok"])
        self.assertTrue(any("resolution_mismatch" in item for item in summary["errors"]))
        self.assertEqual(summary["expected_resolution"], {"width": 1920, "height": 1080})
        self.assertTrue(summary["tasks"]["activity"]["skipped"])
        self.assertEqual(summary["tasks"]["activity"]["reason"], "resolution_mismatch")
        self.assertEqual(task.calls, [])

    def test_expected_resolution_match_allows_tasks_to_run(self):
        task = FakeTask()
        runner = make_runner(
            "daily-task-only",
            task,
            window={"width": 1920, "height": 1080, "title": "HTGame", "hwnd": "1234"},
            expected_resolution=(1920, 1080),
        )

        summary = runner.run()

        self.assertTrue(summary["ok"])
        self.assertIn("ensure", task.calls)

    def test_world_ready_recovery_closes_panel_before_ensure(self):
        task = PanelRecoveryTask()
        runner = make_runner("daily-task-only", task)

        self.assertTrue(runner._ensure_world_ready(task))

        self.assertIn("foreground:esc", task.calls)
        self.assertNotIn("ensure", task.calls)

    def test_daily_full_dispatches_daily_task_coffee_and_gift(self):
        task = FakeTask()
        task.activity_cards_claimed = 1
        runner = make_runner("daily-full", task)

        summary = runner.run()

        self.assertTrue(summary["tasks"]["mail"]["attempted"])
        self.assertTrue(summary["tasks"]["periodic"]["attempted"])
        self.assertTrue(summary["tasks"]["activity"]["attempted"])
        self.assertTrue(summary["tasks"]["coffee"]["attempted"])
        self.assertTrue(summary["tasks"]["gift"]["attempted"])
        self.assertIn("mail", task.calls)
        self.assertIn("periodic", task.calls)
        self.assertIn("claim_activity_cards", task.calls)
        self.assertIn("coffee", task.calls)
        self.assertIn("gift_task_items", task.calls)
        self.assertLess(task.calls.index("coffee"), task.calls.index("complete_daily"))
        self.assertLess(task.calls.index("gift_task_items"), task.calls.index("complete_daily"))
        self.assertLess(task.calls.index("complete_daily"), task.calls.index("claim_activity_rewards"))
        self.assertLess(task.calls.index("claim_activity_rewards"), task.calls.index("mail"))
        self.assertLess(task.calls.index("mail"), task.calls.index("periodic"))

    def test_daily_full_fails_without_gift_consumption_but_defers_incomplete_activity(self):
        runner = make_runner(
            "daily-full",
            IncompleteDailyFullActivityTask(),
            gift_runtime_factory=lambda flow: NoSendDirectGiftRuntime(flow),
        )
        runner.coffee_runtime_factory = NoConsumptionCoffeeRuntime

        summary = runner.run()

        self.assertFalse(summary["ok"])
        self.assertNotIn("daily_full_activity_not_complete", summary["errors"])
        self.assertIn("daily_full_activity_not_complete_deferred", summary["warnings"])
        self.assertIn("daily_full_fangsi_consumption_not_verified", summary["errors"])
        self.assertIn("daily_full_gift_real_send_not_verified", summary["errors"])
        coffee = summary["tasks"]["coffee"]
        gift = summary["tasks"]["gift"]
        activity = summary["tasks"]["activity"]
        self.assertTrue(coffee["ok"])
        self.assertFalse(coffee["supply_purchased"])
        self.assertFalse(gift["mutation_performed"])
        self.assertFalse(gift["mutation_verified"])
        self.assertEqual(gift["sent_total"], 0)
        self.assertFalse(activity["task_completed"])
        self.assertIn("daily_full_activity_not_complete_deferred", activity["completion_warnings"])

    def test_daily_full_allows_incomplete_activity_when_required_mutations_verified(self):
        runner = make_runner("daily-full", IncompleteDailyFullActivityTask())

        summary = runner.run()

        self.assertTrue(summary["ok"])
        self.assertNotIn("daily_full_activity_not_complete", summary["errors"])
        self.assertIn("daily_full_activity_not_complete_deferred", summary["warnings"])
        self.assertTrue(summary["tasks"]["coffee"]["supply_purchased"])
        self.assertTrue(summary["tasks"]["gift"]["mutation_verified"])
        self.assertFalse(summary["tasks"]["activity"]["task_completed"])

    def test_daily_full_requires_direct_gift_send_when_task_runner_does_not_send(self):
        runner = make_runner("daily-full", FullActivityTask())

        summary = runner.run()

        self.assertTrue(summary["ok"])
        gift = summary["tasks"]["gift"]
        self.assertTrue(gift["mutation_performed"])
        self.assertTrue(gift["mutation_verified"])
        self.assertEqual(gift["sent_total"], 1)
        self.assertEqual(gift["selected_item"], "affinity:300")

    def test_daily_full_sets_force_supply_purchase_config(self):
        task = FullActivityTask()
        runner = make_runner("daily-full", task)

        runner.run()

        self.assertTrue(task.config["coffee_force_supply_purchase"])

    def test_gift_only_runs_direct_real_send_when_daily_state_consumed(self):
        runner = make_runner(
            "gift-only",
            gift_runtime_factory=lambda flow: FakeDirectGiftRuntime(flow),
        )

        summary = runner.run()

        gift = summary["tasks"]["gift"]
        self.assertTrue(gift["attempted"])
        self.assertTrue(gift["ok"])
        self.assertTrue(gift["mutation_performed"])
        self.assertTrue(gift["mutation_verified"])
        self.assertEqual(gift["sent_total"], 1)
        self.assertEqual(gift["selected_item"], "affinity:300")
        self.assertEqual(gift["daily_task_state_reason"], "daily_task_state_unavailable_because_already_consumed")
        self.assertTrue(summary["actions"][0]["mutation_performed"])
        self.assertTrue(summary["actions"][0]["mutation_verified"])

    def test_gift_only_fails_without_verified_real_send(self):
        runner = make_runner(
            "gift-only",
            gift_runtime_factory=lambda flow: FakeDirectGiftRuntime(flow, verified=False),
        )

        summary = runner.run()

        self.assertFalse(summary["ok"])
        gift = summary["tasks"]["gift"]
        self.assertTrue(gift["mutation_performed"])
        self.assertFalse(gift["mutation_verified"])
        self.assertEqual(gift["reason"], "gift_direct_post_verification_failed")

    def test_daily_full_allows_verified_gift_mutation(self):
        gift_task_result = {
            "ok": True,
            "preflight": {"attempted": True, "ok": True, "reason": ""},
            "mutation_performed": True,
            "mutation_verified": True,
            "handler_completed": True,
            "task_completed": True,
            "items": [],
            "actions": [],
            "skipped": [],
            "blockers": [],
            "gift": {
                "detected": True,
                "mutation_performed": True,
                "mutation_verified": True,
                "selected_character": "default_visible",
                "selected_item": "affinity:300",
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
        task = FullActivityTask()
        runner = make_runner("daily-full", task, gift_task_result=gift_task_result)

        summary = runner.run()

        self.assertTrue(summary["ok"])
        gift = summary["tasks"]["gift"]
        self.assertTrue(gift["mutation_performed"])
        self.assertTrue(gift["mutation_verified"])
        self.assertEqual(gift["sent_total"], 1)

    def test_no_window_outputs_window_not_found(self):
        runner = make_runner("daily-full", process_exists=False)

        summary = runner.run()

        self.assertFalse(summary["ok"])
        self.assertIn("window_not_found", summary["errors"])
        self.assertEqual(summary["window"]["width"], 0)
        self.assertTrue(summary["tasks"]["mail"]["skipped"])

    def test_permission_error_is_recorded(self):
        task = FakeTask()
        task.mail_result = OSError(5, "PostMessage", "access denied")
        runner = make_runner("daily-task-only", task)

        summary = runner.run()

        self.assertFalse(summary["ok"])
        self.assertTrue(any("postmessage_failed" in item for item in summary["errors"]))
        self.assertEqual(summary["tasks"]["mail"]["reason"], "postmessage_failed")

    def test_no_claimable_reward_is_not_failure(self):
        runner = make_runner("daily-task-only")

        summary = runner.run()

        self.assertTrue(summary["ok"])
        activity = summary["tasks"]["activity"]
        self.assertTrue(activity["ok"])
        self.assertTrue(activity["no_claimable_reward"])
        self.assertTrue(activity["skipped"])

    def test_coffee_product_optimization_enters_summary(self):
        runner = make_runner("coffee-only")

        summary = runner.run()

        coffee = summary["tasks"]["coffee"]
        self.assertTrue(coffee["ok"])
        self.assertTrue(coffee["income_claimed"])
        self.assertTrue(coffee["supply_purchased"])
        self.assertTrue(coffee["product_optimized"])
        self.assertEqual(coffee["deselect_product"], ["deselect_product:old-drink"])
        self.assertEqual(coffee["select_product"], ["select_product:better-drink"])

    def test_summary_schema_fields_are_complete(self):
        runner = make_runner("daily-full")

        summary = runner.run()

        for key in (
            "git_branch",
            "git_head",
            "dirty",
            "command",
            "mode",
            "started_at",
            "finished_at",
            "ok",
            "window",
            "tasks",
            "actions",
            "artifacts",
            "warnings",
            "errors",
        ):
            self.assertIn(key, summary)
        self.assertEqual(set(TASK_KEYS), set(summary["tasks"].keys()))

    def test_actions_record_mutation_performed(self):
        runner = make_runner("coffee-only")

        summary = runner.run()

        self.assertTrue(summary["actions"])
        self.assertTrue(all("mutation_performed" in action for action in summary["actions"]))
        self.assertTrue(all("mutation_verified" in action for action in summary["actions"]))

    def test_activity_summary_records_mutation_verification_details(self):
        runner = make_runner("daily-task-only", VerifiedActivityTask())

        summary = runner.run()

        activity = summary["tasks"]["activity"]
        self.assertTrue(activity["ok"])
        self.assertTrue(activity["mutation_performed"])
        self.assertTrue(activity["mutation_verified"])
        self.assertFalse(activity["action_failed"])
        self.assertEqual(activity["cards_claimed"], 1)
        self.assertIn("complete", activity["details"])
        activity_action = next(action for action in summary["actions"] if action["name"] == "activity")
        self.assertTrue(activity_action["mutation_performed"])
        self.assertTrue(activity_action["mutation_verified"])

    def test_unverified_activity_mutation_fails_summary(self):
        runner = make_runner("daily-task-only", UnverifiedActivityMutationTask())

        summary = runner.run()

        activity = summary["tasks"]["activity"]
        self.assertFalse(summary["ok"])
        self.assertTrue(activity["action_failed"])
        self.assertTrue(activity["mutation_performed"])
        self.assertFalse(activity["mutation_verified"])
        activity_action = next(action for action in summary["actions"] if action["name"] == "activity")
        self.assertTrue(activity_action["mutation_performed"])
        self.assertFalse(activity_action["mutation_verified"])

    def test_activity_summary_preserves_completed_details_after_reward_skip(self):
        runner = make_runner("daily-task-only", RewardOverwriteActivityTask())

        summary = runner.run()

        activity = summary["tasks"]["activity"]
        self.assertTrue(activity["ok"])
        self.assertEqual(activity["cards_claimed"], 1)
        self.assertTrue(activity["task_completed"])
        self.assertTrue(activity["mutation_performed"])
        self.assertTrue(activity["mutation_verified"])

    def test_activity_summary_does_not_turn_handler_action_into_task_completion(self):
        runner = make_runner("daily-task-only", HandlerOnlyActivityTask())

        summary = runner.run()

        activity = summary["tasks"]["activity"]
        self.assertTrue(activity["ok"])
        self.assertTrue(activity["handler_completed"])
        self.assertFalse(activity["task_completed"])
        self.assertEqual(activity["cards_claimed"], 0)
        self.assertFalse(activity["no_claimable_reward"])
        self.assertTrue(activity["mutation_performed"])
        self.assertTrue(activity["mutation_verified"])

    def test_action_summary_uses_structured_periodic_mutation_fields(self):
        task = FakeTask()
        task.periodic_result = {
            "ok": False,
            "claimed": False,
            "skipped": False,
            "reason": "post_verification_failed",
            "mutation_performed": True,
            "mutation_verified": False,
            "action_failed": True,
        }
        runner = make_runner("daily-task-only", task)

        summary = runner.run()

        periodic_action = next(action for action in summary["actions"] if action["name"] == "periodic")
        self.assertTrue(periodic_action["mutation_performed"])
        self.assertFalse(periodic_action["mutation_verified"])

    def test_skipped_periodic_reward_is_not_recorded_as_mutation(self):
        task = FakeTask()
        task.periodic_result = {
            "ok": True,
            "claimed": False,
            "mission_claim_attempts": 0,
            "reward_claimed": False,
            "skipped": True,
            "reason": "no_claimable_periodic_reward",
        }
        runner = make_runner("daily-task-only", task)

        summary = runner.run()

        periodic_action = next(action for action in summary["actions"] if action["name"] == "periodic")
        self.assertFalse(periodic_action["mutation_performed"])
        self.assertTrue(summary["tasks"]["periodic"]["skipped"])

    def test_flow_result_periodic_skip_is_not_recorded_as_mutation(self):
        task = FakeTask()
        task.periodic_result = FlowResult.skip("no_claimable_periodic_reward")
        runner = make_runner("daily-task-only", task)

        summary = runner.run()

        periodic = summary["tasks"]["periodic"]
        periodic_action = next(action for action in summary["actions"] if action["name"] == "periodic")
        self.assertTrue(periodic["ok"])
        self.assertTrue(periodic["skipped"])
        self.assertEqual(periodic["reason"], "no_claimable_periodic_reward")
        self.assertFalse(periodic_action["mutation_performed"])

    def test_flow_result_mail_failure_uses_result_reason(self):
        task = FakeTask()
        task.mail_result = FlowResult.fail("mail_panel_missing")
        runner = make_runner("daily-task-only", task)

        summary = runner.run()

        self.assertFalse(summary["ok"])
        self.assertFalse(summary["tasks"]["mail"]["ok"])
        self.assertEqual(summary["tasks"]["mail"]["reason"], "mail_panel_missing")

    def test_failed_coffee_deselect_is_recorded_as_mutation(self):
        runner = make_runner("coffee-only")
        runner.coffee_runtime_factory = FailedProductSwitchCoffeeRuntime

        summary = runner.run()

        self.assertFalse(summary["ok"])
        action = next(item for item in summary["actions"] if item["target"] == "deselect_product:old")
        self.assertTrue(action["mutation_performed"])
        self.assertFalse(action["mutation_verified"])
        self.assertEqual(summary["tasks"]["coffee"]["reason"], "商品替换失败: 已取消old但未能选择new")

    def test_failed_coffee_supply_purchase_is_unverified_mutation(self):
        runner = make_runner("coffee-only")
        runner.coffee_runtime_factory = FailedSupplyVerificationCoffeeRuntime

        summary = runner.run()

        self.assertFalse(summary["ok"])
        self.assertFalse(summary["tasks"]["coffee"]["ok"])
        buy_action = next(item for item in summary["actions"] if item["target"] == "buy_supply")
        self.assertTrue(buy_action["mutation_performed"])
        self.assertFalse(buy_action["mutation_verified"])
        retry_action = next(item for item in summary["actions"] if item["target"] == "buy_supply_retry_after_no_prompt")
        self.assertTrue(retry_action["mutation_performed"])
        self.assertFalse(retry_action["mutation_verified"])
        claim_action = next(item for item in summary["actions"] if item["target"] == "claim_income")
        self.assertTrue(claim_action["mutation_performed"])
        self.assertTrue(claim_action["mutation_verified"])

    def test_coffee_result_schema_matches_between_coffee_only_and_daily_full(self):
        coffee_only = make_runner("coffee-only").run()["tasks"]["coffee"]
        daily_full = make_runner("daily-full").run()["tasks"]["coffee"]

        self.assertEqual(set(coffee_only.keys()), set(daily_full.keys()))

    def test_working_path_is_git_ignored(self):
        gitignore = Path(".gitignore").read_text(encoding="utf-8")

        self.assertIn("working/", gitignore)
