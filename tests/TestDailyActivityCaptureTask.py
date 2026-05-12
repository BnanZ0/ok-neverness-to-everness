import json
import os
import tempfile
import unittest
from unittest.mock import ANY, Mock, call

import numpy as np

from src.tasks.DailyActivityAnalyzer import DailyActivityAnalysis, DailyActivityState
from src.tasks.DailyTask import DailyTask
from src.tasks.F1PanelDetector import DailyPanelOpenResult
from src.tasks.debug.DailyActivityCaptureTask import DailyActivityCaptureTask


class FakeBox:
    def __init__(self, name, x=1, y=2, width=3, height=4, confidence=0.9):
        self.name = name
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.confidence = confidence


class TestDailyActivityCaptureTask(unittest.TestCase):
    def make_task(self, save_regions=True, save_ocr=False):
        task = object.__new__(DailyActivityCaptureTask)
        task.config = {
            "保存候选区域标注": save_regions,
            "保存OCR结果": save_ocr,
        }
        task.screenshot = Mock()
        task.clear_box = Mock()
        task.draw_boxes = Mock()
        task.ocr = Mock(return_value=[FakeBox("ocr_text")])
        task.info_set = Mock()
        task._write_capture_metadata = Mock(return_value="logs/daily_activity_capture/id.json")
        task._candidate_region_boxes = Mock(return_value=[FakeBox("daily_task_list")])
        task.get_box_by_name = Mock(return_value=FakeBox("box_f1_activity_reward", 10, 10, 80, 20))
        task._executor = Mock(method=Mock(width=160, height=120))
        return task

    def test_capture_current_activity_panel_saves_clean_and_region_screenshots(self):
        task = self.make_task()
        frame = np.zeros((120, 160, 3), dtype=np.uint8)

        with tempfile.TemporaryDirectory() as temp_dir:
            task.CAPTURE_FOLDER = temp_dir
            result = DailyActivityCaptureTask._capture_current_activity_panel(task, frame)
            metadata_image_paths = task._write_capture_metadata.call_args.args[3]
            self.assertTrue(os.path.exists(metadata_image_paths["clean"]))
            self.assertTrue(os.path.exists(metadata_image_paths["raw"]))
            self.assertTrue(os.path.exists(metadata_image_paths["active"]))
            self.assertTrue(os.path.exists(metadata_image_paths["regions"]))

        self.assertTrue(result)
        self.assertEqual(task.screenshot.call_count, 2)
        self.assertEqual(
            task.screenshot.call_args_list[0],
            call(ANY, frame=frame),
        )
        self.assertEqual(
            task.screenshot.call_args_list[1],
            call(ANY, frame=frame, show_box=True),
        )
        task.draw_boxes.assert_called_once_with(
            "daily_activity_candidate_regions",
            [task._candidate_region_boxes.return_value[0]],
            color="blue",
        )
        task._write_capture_metadata.assert_called_once_with(
            ANY,
            [task._candidate_region_boxes.return_value[0]],
            [],
            metadata_image_paths,
            True,
            ANY,
            ANY,
            ANY,
        )

    def test_capture_current_activity_panel_can_include_ocr_boxes(self):
        task = self.make_task(save_ocr=True)
        frame = np.zeros((120, 160, 3), dtype=np.uint8)

        with tempfile.TemporaryDirectory() as temp_dir:
            task.CAPTURE_FOLDER = temp_dir
            DailyActivityCaptureTask._capture_current_activity_panel(task, frame)
            metadata_image_paths = task._write_capture_metadata.call_args.args[3]
            self.assertTrue(os.path.exists(metadata_image_paths["clean"]))
            self.assertTrue(os.path.exists(metadata_image_paths["active"]))
            self.assertTrue(os.path.exists(metadata_image_paths["regions"]))
            self.assertTrue(task._write_capture_metadata.call_args.args[4])

        task.ocr.assert_called_once_with(frame=frame, log=True)
        task.draw_boxes.assert_has_calls(
            [
                call(
                    "daily_activity_candidate_regions",
                    [task._candidate_region_boxes.return_value[0]],
                    color="blue",
                ),
                call("daily_activity_ocr", [task.ocr.return_value[0]], color="green"),
            ]
        )

    def test_capture_current_activity_panel_records_panel_detection_result(self):
        task = self.make_task()
        frame = np.zeros((120, 160, 3), dtype=np.uint8)

        with tempfile.TemporaryDirectory() as temp_dir:
            task.CAPTURE_FOLDER = temp_dir
            DailyActivityCaptureTask._capture_current_activity_panel(
                task,
                frame,
                panel_detected=False,
            )

        self.assertFalse(task._write_capture_metadata.call_args.args[4])
        self.assertIsInstance(task._write_capture_metadata.call_args.args[5], DailyActivityAnalysis)
        self.assertIsInstance(task._write_capture_metadata.call_args.args[6], DailyPanelOpenResult)
        self.assertIsInstance(task._write_capture_metadata.call_args.args[7], dict)
        task.info_set.assert_any_call("每日活跃度面板特征命中", "False")

    def test_box_to_dict_handles_box_shape(self):
        box = FakeBox("region", x=10, y=20, width=30, height=40, confidence=0.75)

        self.assertEqual(
            DailyActivityCaptureTask._box_to_dict(box),
            {
                "name": "region",
                "x": 10,
                "y": 20,
                "width": 30,
                "height": 40,
                "confidence": 0.75,
            },
        )

    def test_capture_task_reuses_daily_activity_constants(self):
        self.assertEqual(
            DailyActivityCaptureTask.DAILY_ACTIVITY_TAB_INDEX,
            DailyTask.DAILY_ACTIVITY_TAB_INDEX,
        )
        self.assertEqual(
            DailyActivityCaptureTask.DAILY_ACTIVITY_TAB_POSITION,
            DailyTask.DAILY_ACTIVITY_TAB_POSITION,
        )

    def test_capture_metadata_records_daily_second_tab_target(self):
        task = object.__new__(DailyActivityCaptureTask)
        task._executor = Mock(method=Mock(width=2560, height=1600))

        with tempfile.TemporaryDirectory() as temp_dir:
            task.CAPTURE_NAME_PREFIX = os.path.join(temp_dir, "daily_activity_capture")
            metadata_path = DailyActivityCaptureTask._write_capture_metadata(
                task,
                "capture",
                [],
                [],
                {
                    "clean": "raw.png",
                    "raw": "raw.png",
                    "active": "active.png",
                    "regions": "regions.png",
                },
                True,
                DailyActivityAnalysis(
                    state=DailyActivityState.NO_ACTION_NEEDED,
                    panel_detected=True,
                    daily_tab_detected=True,
                    activity_full=True,
                    all_daily_done=True,
                    has_go_button=False,
                    has_claimable_reward=False,
                    no_claimable_reward=True,
                    reason="今日活跃度已完成",
                ),
                DailyPanelOpenResult(
                    f1_panel_opened=True,
                    daily_tab_clicked=True,
                    daily_activity_panel_detected=True,
                    layout_profile="native_16_10",
                    reason="每日活跃度面板已识别",
                ),
                {
                    "f1_activity_panel": {
                        "full_screen": {
                            "matched": True,
                            "threshold": 0.75,
                            "box": [10, 20, 30, 40],
                            "confidence": 0.8,
                        }
                    }
                },
            )

            with open(metadata_path, encoding="utf-8") as f:
                metadata = json.load(f)

        self.assertEqual(metadata["schema_version"], 3)
        self.assertEqual(metadata["resolution"], {"width": 2560, "height": 1600})
        self.assertEqual(metadata["viewport"]["mode"], "16_9_center_crop")
        self.assertEqual(metadata["viewport"]["top"], 80)
        self.assertEqual(metadata["viewport"]["height"], 1440)
        self.assertEqual(metadata["layout_profile"], "native_16_10")
        self.assertTrue(metadata["open_result"]["f1_panel_opened"])
        self.assertTrue(metadata["feature_probe"]["f1_activity_panel"]["full_screen"]["matched"])
        self.assertEqual(metadata["capture_files"]["raw"], "raw.png")
        self.assertEqual(metadata["capture_files"]["active"], "active.png")
        self.assertEqual(metadata["target_tab"]["name"], "daily")
        self.assertEqual(metadata["target_tab"]["display_name"], "每日")
        self.assertEqual(metadata["target_tab"]["index"], 2)
        self.assertEqual(metadata["analysis"]["state"], "no_action_needed")
        self.assertEqual(
            metadata["target_tab"]["position"],
            {
                "x": DailyTask.DAILY_ACTIVITY_TAB_POSITION[0],
                "y": DailyTask.DAILY_ACTIVITY_TAB_POSITION[1],
            },
        )


if __name__ == "__main__":
    unittest.main()
