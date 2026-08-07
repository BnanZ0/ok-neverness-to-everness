"""Sound trigger wiring regression tests.

Locks in two fixes:
1. The listener's own shared 0.5s gate is bypassed (is_allow_successive_trigger=True) so the
   per-action gates in DodgeCounterTrigger are the single authority. The old shared gate silently
   dropped a second attack sound within 0.5s and starved the counter channel.
2. "Dodge All Attacks" defaults to False so the counter sound (enemy charging/vulnerable state)
   triggers a counter attack instead of being rerouted into a dodge. Dodge keeps priority because
   the dodge score is always evaluated first.
"""

import unittest
from unittest.mock import MagicMock, patch

from src.sound_trigger.SoundCombatContext import SoundCombatContext


class TestSoundTriggerWiring(unittest.TestCase):
    def setUp(self):
        # SoundCombatContext is a singleton; isolate each test with a fresh instance.
        self._saved_instance = SoundCombatContext._instance
        SoundCombatContext._instance = None

    def tearDown(self):
        SoundCombatContext._instance = self._saved_instance

    def test_config_default_enables_counter(self):
        from src.config import sound_trigger_config_option

        self.assertFalse(sound_trigger_config_option.default_config["Dodge All Attacks"])

    def test_setup_enables_successive_trigger(self):
        with (
            patch("src.sound_trigger.SoundListener.SoundListener") as listener_cls,
            patch("src.sound_trigger.SoundCombatContext.DodgeCounterTrigger"),
        ):
            ctx = SoundCombatContext()
            ctx.setup(MagicMock())

        self.assertTrue(listener_cls.call_args.kwargs.get("is_allow_successive_trigger"))

    def test_apply_sound_config_defaults_counter_on(self):
        from src.combat.BaseCombatTask import BaseCombatTask

        task = MagicMock()
        task.sound_config = {"Enable Sound Trigger": True}
        with patch("src.combat.BaseCombatTask.SoundCombatContext") as ctx_cls:
            BaseCombatTask._apply_sound_config(task)

        # update_config(enable, dodge_all_attacks, dodge_thresh, counter_thresh)
        args = ctx_cls.return_value.update_config.call_args[0]
        self.assertTrue(args[0])  # enable
        self.assertFalse(args[1])  # dodge_all_attacks -> counter enabled


if __name__ == "__main__":
    unittest.main()
