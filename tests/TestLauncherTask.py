import unittest
from unittest.mock import Mock, call, patch

import win32con
from ok import TaskDisabledException

from src import LAUNCHER_EXE
from src.tasks.LauncherTask import LauncherButtonState, LauncherTask


class TestLauncherTask(unittest.TestCase):
    def _make_task(self):
        task = object.__new__(LauncherTask)
        task.log_info = Mock()
        task.log_warning = Mock()
        task.log_info_gated = Mock()
        task.sleep = Mock()
        return task

    def test_hidden_launcher_is_shown_before_capture(self):
        task = self._make_task()

        with (
            patch("src.tasks.LauncherTask.win32gui.IsIconic", side_effect=[False, False]),
            patch("src.tasks.LauncherTask.win32gui.IsWindowVisible", side_effect=[False, True]),
            patch("src.tasks.LauncherTask.win32gui.ShowWindow") as show_window,
        ):
            self.assertTrue(task._restore_window_if_minimized(123, "NTEGame.exe"))

        show_window.assert_called_once_with(123, 5)

    def test_capture_stops_when_launcher_cannot_be_shown(self):
        task = self._make_task()
        task.capture_config = Mock()
        task._ensure_launcher_visible = Mock(return_value=False)

        with self.assertRaisesRegex(TaskDisabledException, "Launcher window is not visible"):
            task._capture_launcher()

    def test_start_game_does_not_accept_hidden_launcher_before_click(self):
        task = self._make_task()
        task._find_process = Mock(return_value=None)
        task._ensure_launcher_visible = Mock(return_value=True)
        task._launcher_button_state = Mock(return_value=(LauncherButtonState.START, "start_button"))
        task._is_launcher_hidden_or_minimized = Mock(return_value=True)
        task.box_of_screen = Mock()
        task.find_one = Mock(return_value=None)
        task.click = Mock()

        with patch("src.tasks.LauncherTask.time.time", side_effect=[0, 0, 0]):
            self.assertTrue(task._click_start_game())

        task.click.assert_called_once_with("start_button", after_sleep=2)

    def test_small_launcher_window_restores_every_ten_seconds_then_uses_timeout_path(self):
        task = self._make_task()
        task._find_process = Mock(return_value={"pid": 1})
        task._find_window_for_process = Mock(return_value=123)
        task._restore_window_if_minimized = Mock()
        task._get_window_size = Mock(return_value=(200, 200))

        with patch("src.tasks.LauncherTask.time.time", side_effect=[0, 0, 10, 120]):
            self.assertFalse(task._wait_for_process(LAUNCHER_EXE))

        task._restore_window_if_minimized.assert_called_with(
            123, LAUNCHER_EXE, force=True
        )

    def test_force_restore_minimizes_before_restoring(self):
        task = self._make_task()

        with (
            patch("src.tasks.LauncherTask.win32gui.IsIconic", side_effect=[False, False]),
            patch("src.tasks.LauncherTask.win32gui.IsWindowVisible", side_effect=[True, True]),
            patch("src.tasks.LauncherTask.win32gui.ShowWindow") as show_window,
        ):
            self.assertTrue(task._restore_window_if_minimized(123, "NTEGame.exe", force=True))

        show_window.assert_has_calls(
            [call(123, win32con.SW_MINIMIZE), call(123, win32con.SW_RESTORE)]
        )
        task.sleep.assert_called_once_with(0.2)
