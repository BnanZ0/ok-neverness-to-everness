import unittest
from unittest.mock import Mock

from src.tasks.DailyActionGate import DailyActionGate
from src.tasks.DailyActivityAnalyzer import RegionBox
from src.tasks.DailyActivityModels import ActionGateSpec


class TestDailyActionGate(unittest.TestCase):
    def make_spec(self, **overrides):
        payload = {
            "recognized_ui": "daily_go_button",
            "confidence": 0.91,
            "screenshot_id": "shot-1",
            "evidence_box": RegionBox("go", 100, 200, 80, 40, confidence=0.91),
            "target_policy": "center",
            "target_offset": None,
            "min_confidence": 0.8,
            "post_verification": "entered_target_page",
            "timeout_ms": 1500,
            "retry_count": 0,
            "staleness_budget_ms": 1000,
        }
        payload.update(overrides)
        return ActionGateSpec(**payload)

    def make_gate(self):
        return DailyActionGate(viewport_width=1280, viewport_height=720, current_screenshot_id="shot-1")

    def test_low_confidence_rejects_without_mutation(self):
        action = Mock()
        spec = self.make_spec(confidence=0.4)

        result = self.make_gate().execute_click(spec, action, verifier=Mock(return_value=True))

        self.assertFalse(result.allowed)
        self.assertEqual(result.reject_reason, "low_confidence")
        self.assertFalse(result.mutation_performed)
        action.click.assert_not_called()

    def test_out_of_bounds_evidence_rejects_without_click(self):
        action = Mock()
        spec = self.make_spec(evidence_box=RegionBox("go", 1250, 200, 80, 40))

        result = self.make_gate().execute_click(spec, action, verifier=Mock(return_value=True))

        self.assertFalse(result.allowed)
        self.assertEqual(result.reject_reason, "evidence_box_out_of_bounds")
        self.assertFalse(result.mutation_performed)
        action.click.assert_not_called()

    def test_target_derivation_failure_rejects_without_click(self):
        action = Mock()
        spec = self.make_spec(target_policy="unsupported")

        result = self.make_gate().execute_click(spec, action, verifier=Mock(return_value=True))

        self.assertFalse(result.allowed)
        self.assertEqual(result.reject_reason, "target_derivation_failed")
        self.assertFalse(result.mutation_performed)
        action.click.assert_not_called()

    def test_stale_screenshot_rejects_without_click(self):
        action = Mock()
        spec = self.make_spec(screenshot_id="old-shot")

        result = self.make_gate().execute_click(spec, action, verifier=Mock(return_value=True))

        self.assertFalse(result.allowed)
        self.assertEqual(result.reject_reason, "stale_screenshot_id")
        self.assertFalse(result.mutation_performed)
        action.click.assert_not_called()

    def test_click_emitted_but_verification_fails_records_unknown_mutation(self):
        action = Mock()
        spec = self.make_spec()

        result = self.make_gate().execute_click(spec, action, verifier=Mock(return_value=False))

        self.assertTrue(result.allowed)
        self.assertTrue(result.executed)
        self.assertFalse(result.verified)
        self.assertTrue(result.mutation_performed)
        self.assertFalse(result.mutation_verified)
        self.assertEqual(result.failure_reason, "post_verification_failed")
        action.click.assert_called_once_with(140, 220)

    def test_click_emitted_and_verified_records_verified_mutation(self):
        action = Mock()
        spec = self.make_spec(target_offset=(5, -10))

        result = self.make_gate().execute_click(spec, action, verifier=Mock(return_value=True))

        self.assertTrue(result.allowed)
        self.assertTrue(result.executed)
        self.assertTrue(result.verified)
        self.assertTrue(result.mutation_performed)
        self.assertTrue(result.mutation_verified)
        self.assertEqual(result.target_point, (145, 210))
        action.click.assert_called_once_with(145, 210)


if __name__ == "__main__":
    unittest.main()
