import unittest

from src.combat.BaseCombatTask import BaseCombatTask


class TestCanSoundTrigger(unittest.TestCase):
    """BaseCombatTask.can_sound_trigger gates audio dodge/counter.

    During an ultimate/skill animation the game does not accept a dodge
    input, so firing one wastes the reaction; outside combat there is
    nothing to dodge. The gate must reflect exactly that.
    """

    def setUp(self):
        self.task = object.__new__(BaseCombatTask)

    def _gate(self, in_combat, in_animation):
        self.task._in_combat = in_combat
        object.__setattr__(self.task, "_in_animation", in_animation)
        return self.task.can_sound_trigger()

    def test_allows_during_active_combat(self):
        self.assertTrue(self._gate(in_combat=True, in_animation=False))

    def test_rejects_during_animation(self):
        self.assertFalse(self._gate(in_combat=True, in_animation=True))

    def test_rejects_out_of_combat(self):
        self.assertFalse(self._gate(in_combat=False, in_animation=False))
        self.assertFalse(self._gate(in_combat=False, in_animation=True))


if __name__ == "__main__":
    unittest.main()
