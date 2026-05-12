import unittest

from src.tasks.DailyActivityAnalyzer import RegionBox
from src.tasks.DailyActivityModels import (
    ActivityCardCandidate,
    DailyActivityOutcome,
    DailyActivitySnapshot,
)
from src.tasks.DailyTask import DailyTask
from src.tasks.FlowResult import FlowResult


class TestDailyActivityOutcome(unittest.TestCase):
    def test_succeeded_outcome_converts_to_true_legacy_and_flow_result(self):
        outcome = DailyActivityOutcome.succeeded(
            "activity_handler_completed",
            mutation_performed=True,
            mutation_verified=True,
            details={"handler_key": "coffee"},
        )

        flow = FlowResult.from_outcome(outcome)

        self.assertTrue(outcome.succeeded)
        self.assertTrue(outcome.ok)
        self.assertIs(outcome.to_legacy_value(), True)
        self.assertTrue(flow.done)
        self.assertTrue(flow.mutated)
        self.assertTrue(flow.details["mutation_performed"])
        self.assertTrue(flow.details["mutation_verified"])

    def test_failed_outcome_converts_to_false_legacy_and_failed_flow_result(self):
        outcome = DailyActivityOutcome.failed(
            "post_verification_failed",
            mutation_performed=True,
            mutation_verified=False,
        )

        flow = FlowResult.from_outcome(outcome)

        self.assertTrue(outcome.failed)
        self.assertFalse(outcome.ok)
        self.assertIs(outcome.to_legacy_value(), False)
        self.assertTrue(flow.failed)
        self.assertEqual(flow.reason, "post_verification_failed")
        self.assertTrue(flow.details["mutation_performed"])
        self.assertFalse(flow.details["mutation_verified"])

    def test_skipped_outcome_converts_to_daily_task_skipped_sentinel(self):
        outcome = DailyActivityOutcome.skipped(
            "no_claimable_reward",
            skipped_sentinel=DailyTask.TASK_SKIPPED,
        )

        flow = FlowResult.from_outcome(outcome)

        self.assertTrue(outcome.skipped)
        self.assertTrue(outcome.is_skipped)
        self.assertIs(outcome.to_legacy_value(), DailyTask.TASK_SKIPPED)
        self.assertIs(flow.to_legacy_value(skipped_sentinel=DailyTask.TASK_SKIPPED), DailyTask.TASK_SKIPPED)
        self.assertTrue(flow.skipped)
        self.assertEqual(flow.reason, "no_claimable_reward")

    def test_dict_legacy_override_is_preserved(self):
        legacy = {"ok": True, "custom": "kept"}
        outcome = DailyActivityOutcome.succeeded(
            "dict_override",
            mutation_performed=False,
            mutation_verified=False,
            legacy_return=legacy,
        )

        flow = FlowResult.from_outcome(outcome)

        self.assertIs(flow.to_legacy_value(), legacy)

    def test_unknown_legacy_object_fails_with_type_name(self):
        result = FlowResult.from_legacy(object())

        self.assertTrue(result.failed)
        self.assertIn("unknown_legacy_result_type:object", result.reason)

    def test_snapshot_details_include_typed_boundary_fields(self):
        snapshot = DailyActivitySnapshot(
            screenshot_id="shot-1",
            panel_ready=True,
            cards=[
                ActivityCardCandidate(
                    card_key="coffee",
                    label="累计消耗10点都市活力",
                    box=RegionBox("card", 10, 20, 100, 40, confidence=0.93),
                    confidence=0.93,
                    source="test",
                    text="0/1",
                    state_tags=("前往",),
                )
            ],
            warnings=["low_contrast"],
            mutation_performed=True,
            mutation_verified=False,
            skipped_reason="",
            failure_reason="post_verification_failed",
        )

        details = snapshot.details()

        self.assertEqual(details["screenshot_id"], "shot-1")
        self.assertTrue(details["panel_ready"])
        self.assertEqual(details["cards"][0]["card_key"], "coffee")
        self.assertEqual(details["warnings"], ["low_contrast"])
        self.assertFalse(details["handler_completed"])
        self.assertFalse(details["task_completed"])
        self.assertTrue(details["mutation_performed"])
        self.assertFalse(details["mutation_verified"])
        self.assertEqual(details["failure_reason"], "post_verification_failed")

    def test_snapshot_does_not_mark_handler_only_action_as_task_completed(self):
        snapshot = DailyActivitySnapshot(
            handlers_completed=True,
            cards_claimed=0,
            mutation_performed=True,
            mutation_verified=True,
        )

        details = snapshot.details()

        self.assertTrue(details["handler_completed"])
        self.assertFalse(details["task_completed"])

    def test_snapshot_marks_task_completed_only_after_card_claim(self):
        snapshot = DailyActivitySnapshot(
            handlers_completed=True,
            cards_claimed=1,
            mutation_performed=True,
            mutation_verified=True,
        )

        details = snapshot.details()

        self.assertTrue(details["handler_completed"])
        self.assertTrue(details["task_completed"])


if __name__ == "__main__":
    unittest.main()
