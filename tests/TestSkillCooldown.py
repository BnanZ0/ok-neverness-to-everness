"""SkillCooldownModel unit tests (pure timer logic with injected clock)."""

import unittest

from src.combat.skill_cooldown import SkillCooldownModel


class TestSkillCooldownModel(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.model = SkillCooldownModel(now_fn=lambda: self.now)

    def test_unused_slot_is_ready(self):
        self.assertTrue(self.model.is_ready("skill"))
        self.assertEqual(self.model.remaining("skill"), 0.0)

    def test_slot_busy_right_after_cast(self):
        self.model.mark_used("skill", 10.0)
        self.assertFalse(self.model.is_ready("skill"))
        self.assertAlmostEqual(self.model.remaining("skill"), 10.0)

    def test_slot_ready_after_cooldown(self):
        self.model.mark_used("skill", 10.0)
        self.now = 110.0
        self.assertTrue(self.model.is_ready("skill"))
        self.assertEqual(self.model.remaining("skill"), 0.0)

    def test_partial_elapsed(self):
        self.model.mark_used("skill", 10.0)
        self.now = 104.0
        self.assertFalse(self.model.is_ready("skill"))
        self.assertAlmostEqual(self.model.remaining("skill"), 6.0)

    def test_independent_slots(self):
        self.model.mark_used("skill", 10.0)
        self.model.mark_used("ultimate", 20.0)
        self.now = 112.0
        self.assertTrue(self.model.is_ready("skill"))
        self.assertFalse(self.model.is_ready("ultimate"))

    def test_recast_extends_cooldown(self):
        self.model.mark_used("skill", 10.0)
        self.now = 105.0
        self.model.mark_used("skill", 10.0)  # recast at 105 -> ready at 115
        self.now = 112.0
        self.assertFalse(self.model.is_ready("skill"))
        self.assertAlmostEqual(self.model.remaining("skill"), 3.0)

    def test_negative_cooldown_clamped(self):
        self.model.mark_used("skill", -5.0)
        self.assertTrue(self.model.is_ready("skill"))

    def test_explicit_now_overrides_clock(self):
        self.model.mark_used("skill", 10.0, now=50.0)
        self.assertTrue(self.model.is_ready("skill", now=60.0))
        self.assertFalse(self.model.is_ready("skill", now=55.0))

    def test_reset_single_slot(self):
        self.model.mark_used("skill", 10.0)
        self.model.mark_used("ultimate", 10.0)
        self.model.reset("skill")
        self.assertTrue(self.model.is_ready("skill"))
        self.assertFalse(self.model.is_ready("ultimate"))

    def test_reset_all(self):
        self.model.mark_used("skill", 10.0)
        self.model.mark_used("ultimate", 10.0)
        self.model.reset()
        self.assertTrue(self.model.is_ready("skill"))
        self.assertTrue(self.model.is_ready("ultimate"))


if __name__ == "__main__":
    unittest.main()
