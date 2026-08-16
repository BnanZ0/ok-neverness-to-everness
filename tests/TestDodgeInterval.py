import unittest
from unittest.mock import Mock, patch

from src.sound_trigger.DodgeCounterTrigger import DodgeCounterTrigger


class TestDodgeInterval(unittest.TestCase):
    """Rapid consecutive attacks must not be dropped by the dodge gate.

    Real combat logs show enemy attacks arriving 0.343s apart; the old 0.5s
    floor silently skipped the second dodge. The per-action gate is now 0.3s.
    """

    def setUp(self):
        self.dodge = Mock()
        self.trigger = DodgeCounterTrigger(task=None, dodge_action=self.dodge)

    def test_dodge_0343s_apart_is_not_dropped(self):
        with patch("src.sound_trigger.DodgeCounterTrigger.time.time", return_value=100.0):
            self.trigger.execute_dodge()
        with patch("src.sound_trigger.DodgeCounterTrigger.time.time", return_value=100.343):
            self.trigger.execute_dodge()
        self.assertEqual(self.dodge.call_count, 2)

    def test_dodge_echo_within_03s_is_still_gated(self):
        with patch("src.sound_trigger.DodgeCounterTrigger.time.time", return_value=100.0):
            self.trigger.execute_dodge()
        with patch("src.sound_trigger.DodgeCounterTrigger.time.time", return_value=100.2):
            self.trigger.execute_dodge()
        self.assertEqual(self.dodge.call_count, 1)


if __name__ == "__main__":
    unittest.main()
