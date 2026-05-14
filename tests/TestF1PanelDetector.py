import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np

from src.Labels import Labels
from src.tasks.F1PanelDetector import F1PanelDetector


class FakeF1PanelTask:
    def __init__(self, frame, *, label_match=True):
        self.frame = frame
        self.height, self.width = frame.shape[:2]
        self.log_info = Mock()
        self.panel = SimpleNamespace(name="f1_activity_panel")
        self.label_match = label_match

    def find_one(self, label):
        if label == Labels.f1_activity_panel and self.label_match:
            return self.panel
        return None


def fill_region(frame, region, color):
    height, width = frame.shape[:2]
    x1, y1, x2, y2 = region
    frame[int(height * y1) : int(height * y2), int(width * x1) : int(width * x2)] = color


class TestF1PanelDetector(unittest.TestCase):
    def _frame(self):
        return np.zeros((1080, 1920, 3), dtype=np.uint8)

    def test_explore_guide_template_match_is_rejected_when_daily_tab_is_not_selected(self):
        frame = self._frame()
        fill_region(frame, (0.035, 0.130, 0.120, 0.310), (230, 230, 230))
        fill_region(frame, F1PanelDetector.NATIVE_16_9_DAILY_PROGRESS_REGION, (180, 210, 80))
        task = FakeF1PanelTask(frame)

        result = F1PanelDetector(task).find_daily_activity_panel()

        self.assertIsNone(result)
        task.log_info.assert_called_once()

    def test_daily_selected_tab_region_accepts_activity_panel_template(self):
        frame = self._frame()
        fill_region(
            frame,
            F1PanelDetector.NATIVE_16_9_DAILY_SELECTED_TAB_REGION,
            (230, 230, 230),
        )
        fill_region(frame, F1PanelDetector.NATIVE_16_9_DAILY_PROGRESS_REGION, (180, 210, 80))
        task = FakeF1PanelTask(frame)

        result = F1PanelDetector(task).find_daily_activity_panel()

        self.assertIs(result, task.panel)
        task.log_info.assert_not_called()

    def test_daily_structure_can_detect_panel_without_template_match(self):
        frame = self._frame()
        fill_region(
            frame,
            F1PanelDetector.NATIVE_16_9_DAILY_SELECTED_TAB_REGION,
            (230, 230, 230),
        )
        fill_region(frame, F1PanelDetector.NATIVE_16_9_DAILY_PROGRESS_REGION, (180, 210, 80))
        task = FakeF1PanelTask(frame, label_match=False)

        result = F1PanelDetector(task).find_daily_activity_panel()

        self.assertIsNotNone(result)
        self.assertEqual(result.name, "native_16_9_daily_activity_panel")

    def test_open_result_preserves_explicit_failed_detection_reason(self):
        result = F1PanelDetector(FakeF1PanelTask(self._frame())).make_open_result(
            True,
            True,
            False,
            reason="daily_activity_panel_not_detected",
        )

        self.assertTrue(result.f1_panel_opened)
        self.assertTrue(result.daily_tab_clicked)
        self.assertFalse(result.daily_activity_panel_detected)
        self.assertEqual(result.reason, "daily_activity_panel_not_detected")


if __name__ == "__main__":
    unittest.main()
