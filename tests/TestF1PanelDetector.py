import json
import unittest

import numpy as np

from src.Labels import Labels
from src.tasks.DailyUIContext import ReadOnlyUIContext
from src.tasks.F1PanelDetector import DailyPanelOpenResult, F1PanelDetector
from src.utils.viewport_adapter import (
    VIEWPORT_MODE_16_9_CENTER_CROP,
    VIEWPORT_MODE_NATIVE_SCREEN,
    classify_ui_layout_profile,
)


class FakeBox:
    def __init__(self, name, x=10, y=20, width=30, height=40, confidence=0.9):
        self.name = name
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.confidence = confidence


class FakeDetectorTask:
    width = 2560
    height = 1600

    def __init__(
        self,
        layout_profile="native_16_10",
        frame=None,
        template_fallback=True,
        f1_default=True,
        width=None,
        height=None,
    ):
        self.layout_profile = layout_profile
        self.frame = frame
        self.template_fallback = template_fallback
        self.f1_default = f1_default
        self.calls = []
        if width is not None:
            self.width = width
        if height is not None:
            self.height = height

    def get_ui_layout_profile(self):
        return self.layout_profile

    def box_of_ui(self, x, y, to_x=1.0, to_y=1.0, name=None):
        return FakeBox(
            name,
            x=int(self.width * x),
            y=int(self.height * y),
            width=int(self.width * (to_x - x)),
            height=int(self.height * (to_y - y)),
        )

    def find_one(self, label, box=None, threshold=0.8):
        box_name = getattr(box, "name", "default_search")
        self.calls.append((label, box_name, threshold))
        if (
            self.template_fallback
            and label == Labels.f1_activity_panel
            and box_name == "f1_main_panel"
            and threshold <= 0.75
        ):
            return FakeBox(label.value, confidence=0.76)
        if label == Labels.f1_panel and box_name == "default_search" and self.f1_default:
            return FakeBox(label.value, confidence=0.9)
        if label == Labels.f1_panel and box_name == "top_bar" and threshold <= 0.75:
            return FakeBox(label.value, confidence=0.9)
        return None


def make_native_16_10_daily_frame():
    frame = np.zeros((1600, 2560, 3), dtype=np.uint8)
    frame[480:584, 90:307] = (35, 35, 35)
    frame[500:565, 115:230] = (230, 230, 230)
    frame[432:752, 333:922] = (20, 45, 40)
    frame[470:510, 360:850] = (180, 220, 70)
    frame[208:1392, 1024:2483] = (35, 35, 35)
    frame[260:1320, 1100:2400] = (230, 230, 230)
    return frame


def make_native_16_10_guide_frame():
    frame = make_native_16_10_daily_frame()
    frame[480:584, 90:307] = 0
    frame[500:565, 115:230] = 0
    frame[336:464, 90:307] = (35, 35, 35)
    frame[360:445, 115:230] = (230, 230, 230)
    return frame


def make_native_16_9_daily_frame():
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    frame[140:335, 67:230] = (35, 35, 35)
    frame[160:315, 83:145] = (230, 230, 230)
    frame[292:508, 250:691] = (20, 45, 40)
    frame[330:490, 280:670] = (180, 220, 70)
    frame[140:940, 768:1862] = (35, 35, 35)
    frame[190:900, 820:1800] = (230, 230, 230)
    return frame


class TestF1PanelDetector(unittest.TestCase):
    def test_layout_profile_2560x1600_is_native_16_10(self):
        self.assertEqual(
            classify_ui_layout_profile(2560, 1600, VIEWPORT_MODE_NATIVE_SCREEN),
            "native_16_10",
        )

    def test_layout_profile_2560x1440_is_native_16_9(self):
        self.assertEqual(
            classify_ui_layout_profile(2560, 1440, VIEWPORT_MODE_NATIVE_SCREEN),
            "native_16_9",
        )

    def test_layout_profile_letterbox_is_viewport_16_9(self):
        self.assertEqual(
            classify_ui_layout_profile(2560, 1600, VIEWPORT_MODE_16_9_CENTER_CROP),
            "viewport_16_9",
        )

    def test_open_result_can_distinguish_panel_and_daily_detection(self):
        result = DailyPanelOpenResult(
            f1_panel_opened=True,
            daily_tab_clicked=True,
            daily_activity_panel_detected=False,
            layout_profile="native_16_10",
            reason="template missing",
        )

        self.assertTrue(result.f1_panel_opened)
        self.assertTrue(result.daily_tab_clicked)
        self.assertFalse(result.daily_activity_panel_detected)
        self.assertEqual(result.to_dict()["layout_profile"], "native_16_10")

    def test_native_16_10_detector_uses_fallback_search_region(self):
        task = FakeDetectorTask()

        result = F1PanelDetector(task).find_daily_activity_panel()

        self.assertTrue(result)
        self.assertIn((Labels.f1_activity_panel, "default_search", 0.8), task.calls)
        self.assertIn((Labels.f1_activity_panel, "f1_main_panel", 0.75), task.calls)

    def test_native_16_10_daily_structure_detects_panel_when_template_missing(self):
        task = FakeDetectorTask(
            frame=make_native_16_10_daily_frame(),
            template_fallback=False,
        )

        result = F1PanelDetector(task).find_daily_activity_panel()

        self.assertTrue(result)
        self.assertEqual(result.name, "native_16_10_daily_activity_panel")

    def test_detector_accepts_read_only_ui_context(self):
        task = FakeDetectorTask(
            frame=make_native_16_10_daily_frame(),
            template_fallback=False,
        )
        context = ReadOnlyUIContext(task)

        result = F1PanelDetector(context).find_daily_activity_panel()

        self.assertTrue(result)
        self.assertEqual(result.name, "native_16_10_daily_activity_panel")

    def test_native_16_10_daily_structure_requires_selected_daily_tab(self):
        frame = make_native_16_10_daily_frame()
        frame[480:584, 90:307] = 0
        task = FakeDetectorTask(frame=frame, template_fallback=False)

        result = F1PanelDetector(task).find_daily_activity_panel()

        self.assertIsNone(result)

    def test_native_16_10_daily_structure_rejects_guide_tab(self):
        task = FakeDetectorTask(
            frame=make_native_16_10_guide_frame(),
            template_fallback=False,
        )

        result = F1PanelDetector(task).find_daily_activity_panel()

        self.assertIsNone(result)

    def test_native_16_9_daily_structure_detects_current_guide_panel(self):
        task = FakeDetectorTask(
            layout_profile="native_16_9",
            frame=make_native_16_9_daily_frame(),
            template_fallback=False,
            width=1920,
            height=1080,
        )

        result = F1PanelDetector(task).find_daily_activity_panel()

        self.assertTrue(result)
        self.assertEqual(result.name, "native_16_9_daily_activity_panel")

    def test_native_16_9_daily_structure_does_not_require_f1_template_anchor(self):
        task = FakeDetectorTask(
            layout_profile="native_16_9",
            frame=make_native_16_9_daily_frame(),
            template_fallback=False,
            f1_default=False,
            width=1920,
            height=1080,
        )

        result = F1PanelDetector(task).find_daily_activity_panel()

        self.assertTrue(result)
        self.assertEqual(result.name, "native_16_9_daily_activity_panel")

    def test_native_16_9_daily_structure_requires_selected_top_tab(self):
        frame = make_native_16_9_daily_frame()
        frame[140:335, 67:230] = 0
        task = FakeDetectorTask(
            layout_profile="native_16_9",
            frame=frame,
            template_fallback=False,
            width=1920,
            height=1080,
        )

        result = F1PanelDetector(task).find_daily_activity_panel()

        self.assertIsNone(result)

    def test_native_16_10_f1_panel_fallback_uses_top_bar(self):
        task = FakeDetectorTask(f1_default=False)

        result = F1PanelDetector(task).find_f1_panel()

        self.assertTrue(result)
        self.assertIn((Labels.f1_panel, "top_bar", 0.75), task.calls)

    def test_capture_json_records_feature_probe(self):
        task = FakeDetectorTask()

        probe = F1PanelDetector(task).probe_features()

        self.assertIn("f1_activity_panel", probe)
        self.assertIn("native_16_10_daily_panel", probe)
        self.assertIn("native_16_9_daily_panel", probe)
        self.assertIn("full_screen", probe["f1_activity_panel"])
        json.dumps(probe, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()
