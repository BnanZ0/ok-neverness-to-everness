import unittest

from src.tasks.DailyActivityAnalyzer import RegionBox
from src.tasks.DailyActivityModels import (
    ActionGateResult,
    ActionGateSpec,
    ActivityCardCandidate,
    ActivityHandleIntent,
    DailyActivityOutcome,
    DailyActivitySnapshot,
)
from src.tasks.DailyResultRecorder import DailyResultRecorder


class TestDailyResultRecorder(unittest.TestCase):
    def test_recorder_details_include_snapshot_intent_gate_and_outcome(self):
        candidate = ActivityCardCandidate(
            card_key="coffee",
            label="累计消耗10点都市活力",
            box=RegionBox("card", 10, 20, 100, 40, confidence=0.93),
            confidence=0.93,
            source="unit",
            text="0/1",
            state_tags=("前往",),
        )
        snapshot = DailyActivitySnapshot(
            screenshot_id="shot-1",
            panel_ready=True,
            cards=[candidate],
        )
        intent = ActivityHandleIntent(
            handler_key="coffee",
            candidate=candidate,
            priority=10,
            action_kind="前往",
            gate_spec=ActionGateSpec(
                recognized_ui="daily_go_button",
                confidence=0.93,
                screenshot_id="shot-1",
                evidence_box=RegionBox("go", 100, 200, 80, 40),
            ),
        )
        gate_result = ActionGateResult.executed_result(
            verified=False,
            before_screenshot_id="shot-1",
            after_screenshot_id="shot-2",
            target_point=(140, 220),
            failure_reason="post_verification_failed",
        )
        outcome = DailyActivityOutcome.failed(
            "post_verification_failed",
            mutation_performed=True,
            mutation_verified=False,
        )

        recorder = DailyResultRecorder(snapshot)
        recorder.record_intent(intent)
        recorder.record_gate_result(gate_result)
        recorder.record_outcome(outcome)

        details = recorder.details()

        self.assertEqual(details["snapshot"]["screenshot_id"], "shot-1")
        self.assertEqual(details["intents"][0]["handler_key"], "coffee")
        self.assertTrue(details["gate_results"][0]["mutation_performed"])
        self.assertEqual(details["outcomes"][0]["failure_reason"], "post_verification_failed")
        self.assertTrue(details["mutation_performed"])
        self.assertFalse(details["mutation_verified"])
        self.assertEqual(details["failure_reason"], "post_verification_failed")


if __name__ == "__main__":
    unittest.main()
