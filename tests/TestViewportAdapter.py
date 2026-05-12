import unittest
from unittest.mock import Mock

import numpy as np

from src.tasks.BaseNTETask import BaseNTETask
from src.utils.viewport_adapter import (
    LAYOUT_PROFILE_NATIVE_16_9,
    LAYOUT_PROFILE_VIEWPORT_16_9,
    VIEWPORT_MODE_16_9_CENTER_CROP,
    VIEWPORT_MODE_NATIVE_16_9,
    VIEWPORT_MODE_NATIVE_SCREEN,
    classify_ui_layout_profile,
    make_16_9_viewport,
    make_auto_viewport,
)


class TestViewportAdapter(unittest.TestCase):
    def test_2560x1600_maps_to_centered_2560x1440_viewport(self):
        viewport = make_16_9_viewport(2560, 1600)

        self.assertEqual(viewport.left, 0)
        self.assertEqual(viewport.top, 80)
        self.assertEqual(viewport.width, 2560)
        self.assertEqual(viewport.height, 1440)
        self.assertEqual(viewport.mode, VIEWPORT_MODE_16_9_CENTER_CROP)

    def test_1920x1080_maps_to_full_viewport(self):
        viewport = make_16_9_viewport(1920, 1080)

        self.assertEqual(viewport.left, 0)
        self.assertEqual(viewport.top, 0)
        self.assertEqual(viewport.width, 1920)
        self.assertEqual(viewport.height, 1080)
        self.assertEqual(viewport.mode, VIEWPORT_MODE_NATIVE_16_9)

    def test_native_16_9_viewport_profile_stays_native_16_9(self):
        self.assertEqual(
            classify_ui_layout_profile(1920, 1080, VIEWPORT_MODE_NATIVE_16_9),
            LAYOUT_PROFILE_NATIVE_16_9,
        )

    def test_center_crop_viewport_profile_stays_viewport_16_9(self):
        self.assertEqual(
            classify_ui_layout_profile(2560, 1600, VIEWPORT_MODE_16_9_CENTER_CROP),
            LAYOUT_PROFILE_VIEWPORT_16_9,
        )

    def test_2560x1600_center_mapping(self):
        viewport = make_16_9_viewport(2560, 1600)

        x, y = viewport.ui_point_to_screen_relative(0.5, 0.5)

        self.assertAlmostEqual(x, 0.5, places=4)
        self.assertAlmostEqual(y, 0.5, places=4)

    def test_2560x1600_top_mapping(self):
        viewport = make_16_9_viewport(2560, 1600)

        _, y = viewport.ui_point_to_screen_relative(0.0, 0.0)

        self.assertAlmostEqual(y, 0.05, places=4)

    def test_2560x1600_bottom_mapping(self):
        viewport = make_16_9_viewport(2560, 1600)

        _, y = viewport.ui_point_to_screen_relative(1.0, 1.0)

        self.assertAlmostEqual(y, 0.95, places=4)

    def test_crop_active_frame(self):
        viewport = make_16_9_viewport(2560, 1600)
        frame = np.zeros((1600, 2560, 3), dtype=np.uint8)

        active_frame = viewport.crop_active_frame(frame)

        self.assertEqual(active_frame.shape[:2], (1440, 2560))

    def test_auto_viewport_keeps_letterboxed_16_9_area(self):
        frame = np.zeros((1600, 2560, 3), dtype=np.uint8)
        frame[80:1520, :] = 80

        viewport = make_auto_viewport(2560, 1600, frame=frame)

        self.assertEqual(viewport.mode, VIEWPORT_MODE_16_9_CENTER_CROP)
        self.assertEqual((viewport.left, viewport.top, viewport.width, viewport.height), (0, 80, 2560, 1440))

    def test_auto_viewport_uses_native_screen_when_fullscreen_edges_have_content(self):
        frame = np.zeros((1600, 2560, 3), dtype=np.uint8)
        frame[80:1520, :] = 80
        frame[:80, :, 0] = np.arange(2560, dtype=np.uint8)
        frame[1520:, :, 1] = np.arange(2560, dtype=np.uint8)

        viewport = make_auto_viewport(2560, 1600, frame=frame)

        self.assertEqual(viewport.mode, VIEWPORT_MODE_NATIVE_SCREEN)
        self.assertEqual((viewport.left, viewport.top, viewport.width, viewport.height), (0, 0, 2560, 1600))

    def test_missing_resolution_config_falls_back_to_auto_viewport(self):
        task = object.__new__(BaseNTETask)
        task.get_global_config = Mock(
            side_effect=RuntimeError("Can not find global config Resolution Adaptation Config")
        )

        config = BaseNTETask._optional_global_config(task, "Resolution Adaptation Config")

        self.assertIsNone(config)

    def test_click_ui_uses_pixel_coordinates_without_second_ratio_mapping(self):
        task = object.__new__(BaseNTETask)
        task._executor = Mock(method=Mock(width=2560, height=1600))
        task.click = Mock(return_value=True)

        result = BaseNTETask.click_ui(task, 0.0, 0.0, after_sleep=1)

        self.assertTrue(result)
        task.click.assert_called_once_with(0, 80, after_sleep=1)

    def test_box_of_ui_maps_to_active_viewport_pixels(self):
        task = object.__new__(BaseNTETask)
        task._executor = Mock(method=Mock(width=2560, height=1600))

        box = BaseNTETask.box_of_ui(task, 0.0, 0.0, 1.0, 1.0, name="ui")

        self.assertEqual((box.x, box.y, box.width, box.height), (0, 80, 2560, 1440))
        self.assertEqual(box.name, "ui")


if __name__ == "__main__":
    unittest.main()
