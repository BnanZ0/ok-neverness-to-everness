"""战斗长动作与声音闪避/反击的公共抢占边界测试。"""

import unittest
from unittest.mock import MagicMock, patch

from src.char.BaseChar import BaseChar
from src.combat.BaseCombatTask import BaseCombatTask, SleepCheckSkip


class TestCombatSoundIntegration(unittest.TestCase):
    def _task(self):
        task = BaseCombatTask.__new__(BaseCombatTask)
        task.sleep_check_skip = SleepCheckSkip()
        task.in_animation = False
        task.log_info = MagicMock()
        task.check_combat = MagicMock()
        return task

    def test_sleep_checkpoint_executes_pending_sound_action(self):
        task = self._task()

        with patch("src.combat.BaseCombatTask.SoundCombatContext") as sound_context:
            sound_context.should_interrupt_combat.return_value = True

            task.sleep_check()

        sound_context.return_value.execute_pending_action.assert_called_once_with()
        sound_context.wait_for_resume.assert_called_once_with()
        task.check_combat.assert_called_once_with()

    def test_animation_defers_sound_action(self):
        task = self._task()
        task.in_animation = True

        with patch("src.combat.BaseCombatTask.SoundCombatContext") as sound_context:
            sound_context.should_interrupt_combat.return_value = True

            task.sleep_check()

        sound_context.return_value.execute_pending_action.assert_not_called()
        sound_context.wait_for_resume.assert_not_called()
        task.check_combat.assert_called_once_with()

    def test_sound_trigger_is_disabled_during_animation(self):
        task = self._task()
        task._in_combat = True

        self.assertTrue(task.can_sound_trigger())
        task.in_animation = True
        self.assertFalse(task.can_sound_trigger())
        task.in_animation = False
        task._in_combat = False
        self.assertFalse(task.can_sound_trigger())

    def test_action_rechecks_sound_checkpoint_immediately_before_key_send(self):
        task = MagicMock()
        task.ensure_team_binding.return_value = True
        task.is_in_team.return_value = True
        call_order = []
        task.sleep_check.side_effect = lambda: call_order.append("sleep_check")
        char = object.__new__(BaseChar)
        char.task = task
        char.logger = MagicMock()
        char.sleep = lambda *args, **kwargs: None
        ready = [True]

        def send_action():
            call_order.append("send")
            ready[0] = False
            return True

        result = char._try_available_action(
            "skill",
            lambda: ready[0],
            send_action,
            send_click=False,
            time_out=1,
        )

        self.assertTrue(result["clicked"])
        self.assertEqual(call_order, ["sleep_check", "send"])


if __name__ == "__main__":
    unittest.main()
