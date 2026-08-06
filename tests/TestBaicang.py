"""BaiCang (白藏) character tests.

Verifies the class metadata required by the upstream CharRegistry and the
combat_plan entry branching, using a lightweight FakeTask so no heavy OCR /
template / model runtime is loaded. Mirrors the FakeTask pattern in
TestCombatPlanner.py.
"""

import unittest
from unittest.mock import MagicMock

from src.char.Baicang import Baicang
from src.char.BaseChar import BaseChar, Element
from src.char.core.CharRegistry import char_registry
from src.combat.planner import ActionSlot, FieldPreference, Role


class FakeTask:
    def __init__(self):
        self.chars = []
        self.reaction_target = None

    def time_elapsed_accounting_for_freeze(self, start, intro_motion_freeze=False):
        return 999

    def find_element_ring_reaction_target(self, source_char):
        return self.reaction_target


class TestableBaicang(Baicang):
    """Baicang subclass with a fake clock, empty sleep, and mocked inputs."""

    __test__ = False

    def __init__(self, index=0):
        super().__init__(FakeTask(), index, char_id="baicang")
        self._fake_time = 0.0
        self._skill_available = False
        self._ultimate_available = False
        self._click_skill_result = True
        self._click_ultimate_result = True
        self._combat_active = True
        self.skill_calls = 0
        self.ultimate_calls = 0
        self.fallback_calls = 0
        self.burst_calls = 0
        self.post_skill_calls = 0
        self.task.click = MagicMock()

    def _now(self):
        return self._fake_time

    def sleep(self, sec, sleep_check=True):
        self._fake_time += sec

    def skill_available(self, check_color=True):
        return self._skill_available

    def ultimate_available(self, check_color=True):
        return self._ultimate_available

    def click_skill(self, **kwargs):
        self.skill_calls += 1
        return self._click_skill_result

    def click_ultimate(self, **kwargs):
        self.ultimate_calls += 1
        return self._click_ultimate_result

    def check_combat(self):
        if not self._combat_active:
            from src.combat.BaseCombatTask import NotInCombatException

            raise NotInCombatException("test: not in combat")

    def continues_right_click(self, duration, interval=0.1, direction_key=None):
        self.fallback_calls += 1
        self._fake_time += duration

    def normal_attack(self):
        self._fake_time += 0.18

    def heavy_attack(self, duration=0.6):
        self._fake_time += duration

    def _perform_burst(self, context=None):
        self.burst_calls += 1
        self._fake_time += 0.1

    def _post_skill_dodge(self):
        self.post_skill_calls += 1
        self._fake_time += 0.1


class TestBaicangMetadata(unittest.TestCase):
    def test_class_metadata(self):
        self.assertEqual(Baicang.cn_name, "白藏")
        self.assertEqual(Baicang.en_name, "Baicang")
        self.assertEqual(Baicang.element, Element.RED)

    def test_registry_contains_baicang(self):
        char_registry.ensure_scanned()
        impl = char_registry.get("builtin:baicang")
        self.assertIsNotNone(impl)
        self.assertIs(impl.char_cls, Baicang)
        self.assertEqual(impl.cn_name, "白藏")
        self.assertEqual(impl.element, Element.RED)

    def test_is_main_dps(self):
        char = TestableBaicang()
        profile = char.describe_role()
        self.assertEqual(profile.role, Role.MAIN_DPS)
        self.assertEqual(profile.field_preference, FieldPreference.MAIN_DPS)
        self.assertEqual(profile.max_field_time, 0)

    def test_is_basechar_subclass(self):
        self.assertTrue(issubclass(Baicang, BaseChar))


class TestBaicangCombatPlan(unittest.TestCase):
    def setUp(self):
        self.char = TestableBaicang()

    def _first_entry_action(self):
        plan = self.char.combat_plan(None)
        gen = plan.entry()
        return next(gen)

    def test_ultimate_entry_yielded_first(self):
        self.char._skill_available = True
        self.char._ultimate_available = True
        action = self._first_entry_action()
        self.assertIn("ultimate", action.name)

    def test_skill_yielded_after_ultimate_fails(self):
        self.char._skill_available = True
        self.char._ultimate_available = True
        plan = self.char.combat_plan(None)
        gen = plan.entry()
        first = next(gen)
        self.assertIn("ultimate", first.name)
        second = gen.send(False)  # Q fails
        self.assertIn("skill", second.name)

    def test_burst_called_on_ultimate_success(self):
        self.char._skill_available = False
        self.char._ultimate_available = True
        plan = self.char.combat_plan(None)
        gen = plan.entry()
        action = next(gen)
        self.assertIn("ultimate", action.name)
        # send(True) resumes the entry generator; the burst then returns, so the
        # generator raises StopIteration. That is the expected "finished" signal.
        with self.assertRaises(StopIteration):
            gen.send(True)  # Q succeeds
        self.assertEqual(self.char.burst_calls, 1)

    def test_post_skill_called_on_e_only(self):
        self.char._skill_available = True
        self.char._ultimate_available = True
        plan = self.char.combat_plan(None)
        gen = plan.entry()
        next(gen)  # ultimate
        # send(False) resumes and also yields the next action (skill).
        skill_action = gen.send(False)  # Q fails
        self.assertIn("skill", skill_action.name)
        with self.assertRaises(StopIteration):
            gen.send(True)  # E succeeds
        self.assertEqual(self.char.post_skill_calls, 1)

    def test_skill_action_slot(self):
        plan = self.char.combat_plan(None)
        skill_action = [a for a in plan.actions if a.name == "baicang_skill"]
        self.assertEqual(len(skill_action), 1)
        self.assertEqual(skill_action[0].slot, ActionSlot.SKILL)

    def test_fallback_dodge_priority_ready_false(self):
        plan = self.char.combat_plan(None)
        fallback = [a for a in plan.actions if a.name == "baicang_dodge_fallback"]
        self.assertEqual(len(fallback), 1)
        self.assertFalse(fallback[0].priority_ready(None))


class BurstHarnessBaicang(Baicang):
    """Burst-loop harness: fake clock plus a heavy_combo that jumps past the deadline.

    Drives the real ``_perform_burst`` loop so regression tests can assert that no
    arc key or second-skill is sent once the burst deadline has passed.
    """

    __test__ = False

    def __init__(self, index=0):
        super().__init__(FakeTask(), index, char_id="baicang")
        self._fake_time = 0.0
        self._skill_available = True
        self._combat_active = True
        self.is_current_char = True
        self.is_dead = False
        self.arc_key_calls = 0
        self.skill_click_calls = 0
        self.switch_during_combo = False
        self.death_during_combo = False

    def _now(self):
        return self._fake_time

    def sleep(self, sec, sleep_check=True):
        self._fake_time += sec

    def skill_available(self, check_color=True):
        return self._skill_available

    def check_combat(self):
        if not self._combat_active:
            from src.combat.BaseCombatTask import NotInCombatException

            raise NotInCombatException("test: not in combat")

    def _heavy_combo(self):
        # Run one combo that jumps the fake clock past the whole burst window,
        # optionally switching char / dying mid-way. In all cases the state or
        # deadline check after the combo must stop the loop before R or a
        # second E can fire.
        if self.switch_during_combo:
            self.is_current_char = False
        if self.death_during_combo:
            self.is_dead = True
        self._fake_time += self.ULT_FIELD_DURATION + 1.0

    def send_arc_key(self, after_sleep=0, interval=-1, down_time=0.01):
        self.arc_key_calls += 1

    def click_skill(self, **kwargs):
        self.skill_click_calls += 1
        return True


class TestBaicangDeadlineCheck(unittest.TestCase):
    def test_no_arc_or_second_skill_after_deadline(self):
        char = BurstHarnessBaicang()
        char._perform_burst(context=None)
        self.assertEqual(char.arc_key_calls, 0)
        self.assertEqual(char.skill_click_calls, 0)

    def test_no_arc_or_second_skill_after_char_switch(self):
        char = BurstHarnessBaicang()
        char.switch_during_combo = True
        char._perform_burst(context=None)
        self.assertEqual(char.arc_key_calls, 0)
        self.assertEqual(char.skill_click_calls, 0)

    def test_no_arc_or_second_skill_after_death(self):
        char = BurstHarnessBaicang()
        char.death_during_combo = True
        char._perform_burst(context=None)
        self.assertEqual(char.arc_key_calls, 0)
        self.assertEqual(char.skill_click_calls, 0)


if __name__ == "__main__":
    unittest.main()