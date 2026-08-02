import unittest
from unittest.mock import Mock

from ok import TaskDisabledException

from src.tasks.NTEOneTimeTask import NTEOneTimeTask


class _BaseTask:
    def run(self, *args, **kwargs):
        self.base_run_called = True


class _OneTimeTask(NTEOneTimeTask, _BaseTask):
    def __init__(self, game_capture_ready, connected):
        self.scene = Mock()
        self.scene.game_capture_ready.return_value = game_capture_ready
        self.executor = Mock()
        self.executor.connected.return_value = connected
        self.executor.interaction = None
        self.log_warning = Mock()
        self.sleep = Mock()
        self.set_check_monthly_card = Mock()
        self.base_run_called = False


class TestNTEOneTimeTask(unittest.TestCase):
    def test_skips_task_when_game_capture_is_not_ready(self):
        task = _OneTimeTask(game_capture_ready=False, connected=True)

        with self.assertRaisesRegex(TaskDisabledException, "Game capture is not ready"):
            task.run()

        task.log_warning.assert_called_once()
        self.assertFalse(task.base_run_called)

    def test_skips_task_when_game_capture_connection_is_lost(self):
        task = _OneTimeTask(game_capture_ready=True, connected=False)

        with self.assertRaisesRegex(TaskDisabledException, "Game capture is not ready"):
            task.run()

        self.assertFalse(task.base_run_called)

    def test_runs_when_game_capture_is_ready_and_connected(self):
        task = _OneTimeTask(game_capture_ready=True, connected=True)

        task.run()

        self.assertTrue(task.base_run_called)
        task.set_check_monthly_card.assert_called_once()
