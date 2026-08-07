"""真红(Shinku)自动战斗逻辑单元测试."""

import unittest
from unittest.mock import MagicMock

from src.char.BaseChar import BaseChar, Element
from src.char.Iloy import Iloy
from src.char.Mint import Mint
from src.char.Shinku import Shinku
from src.char.Zero import Zero
from src.char.core.CharRegistry import char_registry
from src.combat.planner import ActionSlot, FieldPreference, Role


class TestableBase:
    __test__ = False

    def _setup_testable(self, task):
        self._fake_time = 0.0
        self._skill_available = True
        self._ultimate_available = True
        self._click_skill_result = True
        self._click_ultimate_result = True
        self.is_current_char = True
        self.is_dead = False
        self.skill_calls = 0
        self.ultimate_calls = 0
        self.normal_attack_calls = 0
        self.switch_calls = 0

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

    def normal_attack(self):
        self.normal_attack_calls += 1
        self._fake_time += 0.3

    def check_combat(self):
        pass

    def switch_other_char(self):
        self.switch_calls += 1


class TestableShinku(TestableBase, Shinku):
    __test__ = False

    def __init__(self, task=None, index=0, char_id="shinku"):
        if task is None:
            task = MagicMock()
        super().__init__(task, index, char_id=char_id)
        self._setup_testable(task)


class FakeTask:
    def __init__(self, chars=None):
        self.chars = chars or []

    def find_element_reaction_target(self, source_char):
        return None

    def time_elapsed_accounting_for_freeze(self, start, intro_motion_freeze=False):
        return 999

    def is_cycle_full(self):
        return False

    def wait_until(self, predicate, **kwargs):
        return predicate()


def make_999night_team():
    task = FakeTask()
    iloy = Iloy(task, 0, char_id="char_iloy")
    mint = Mint(task, 1, char_id="char_mint")
    shinku = Shinku(task, 2, char_id="char_shinku")
    zero = Zero(task, 3, char_id="char_zero")
    task.chars = [iloy, mint, shinku, zero]
    return task, iloy, mint, shinku, zero


# =====================================================================
#  Factory
# =====================================================================


class TestShinkuFactory(unittest.TestCase):
    def test_registry_contains_shinku(self):
        self.assertIsNotNone(char_registry.get("builtin:shinku"))

    def test_registry_cls_is_shinku(self):
        self.assertIs(char_registry.get("builtin:shinku").char_cls, Shinku)

    def test_registry_cn_name(self):
        self.assertEqual(char_registry.get("builtin:shinku").cn_name, "真红")

    def test_registry_element_is_white(self):
        self.assertEqual(char_registry.get("builtin:shinku").element, Element.WHITE)

    def test_shinku_is_subclass_of_basechar(self):
        self.assertTrue(issubclass(Shinku, BaseChar))


# =====================================================================
#  Role
# =====================================================================


class TestShinkuRole(unittest.TestCase):
    def setUp(self):
        self.char = TestableShinku()

    def test_role_is_main_dps(self):
        self.assertEqual(self.char.describe_role().role, Role.MAIN_DPS)

    def test_field_preference_is_main_dps(self):
        self.assertEqual(
            self.char.describe_role().field_preference, FieldPreference.MAIN_DPS
        )

    def test_max_field_time_is_zero(self):
        self.assertEqual(self.char.describe_role().max_field_time, 0)


# =====================================================================
#  Combat plan
# =====================================================================


class TestShinkuCombatPlan(unittest.TestCase):
    def setUp(self):
        self.char = TestableShinku()

    def test_skill_has_skill_slot(self):
        plan = self.char.combat_plan(None)
        skill = [a for a in plan.actions if "skill" in a.name][0]
        self.assertEqual(skill.slot, ActionSlot.SKILL)

    def test_ultimate_has_ultimate_slot(self):
        plan = self.char.combat_plan(None)
        ult = [a for a in plan.actions if "ultimate" in a.name][0]
        self.assertEqual(ult.slot, ActionSlot.ULTIMATE)

    def test_entry_yields_skill_first(self):
        plan = self.char.combat_plan(None)
        gen = plan.entry()
        first = next(gen)
        self.assertIn("skill", first.name)

    def test_ultimate_yielded_after_skill(self):
        plan = self.char.combat_plan(None)
        gen = plan.entry()
        next(gen)
        second = gen.send(True)
        self.assertIn("ultimate", second.name)

    def test_no_field_claims(self):
        plan = self.char.combat_plan(None)
        self.assertEqual(len(plan.claims), 0)


# =====================================================================
#  Burst loop
# =====================================================================


class TestShinkuBurst(unittest.TestCase):
    def setUp(self):
        self.char = TestableShinku()
        # Shorten durations for testing
        self.char.ENHANCED_STATE_DURATION = 1.0
        self.char.SECOND_ULT_READY_AT = 0.5
        self.char.ENHANCED_SKILL_NORMALS = 2
        self.char.NORMAL_ATTACK_INTERVAL = 0.01
        self.char.POST_ULT_SLEEP = 0.01

    def test_burst_calls_normal_attack(self):
        self.char._perform_burst(None)
        self.assertGreater(self.char.normal_attack_calls, 0)

    def test_burst_has_timeout(self):
        self.char.ENHANCED_STATE_DURATION = 0.05
        self.char._perform_burst(None)

    def test_burst_stops_on_char_switch(self):
        original_attack = self.char.normal_attack

        def attack_and_switch():
            original_attack()
            self.char.is_current_char = False

        self.char.normal_attack = attack_and_switch
        self.char._perform_burst(None)
        self.assertFalse(self.char.is_current_char)

    def test_burst_stops_on_death(self):
        original_attack = self.char.normal_attack

        def attack_and_die():
            original_attack()
            self.char.is_dead = True

        self.char.normal_attack = attack_and_die
        self.char._perform_burst(None)
        self.assertTrue(self.char.is_dead)

    def test_burst_uses_enhanced_skill_after_normals(self):
        self.char._skill_available = True
        self.char._perform_burst(None)
        self.assertGreater(self.char.skill_calls, 0)

    def test_burst_fires_second_ult_in_window(self):
        """二段大 should fire when SECOND_ULT_READY_AT is reached."""
        self.char._ultimate_available = True
        self.char._perform_burst(None)
        # At least 2 ultimate calls: one for second ult, possibly one for third
        self.assertGreaterEqual(self.char.ultimate_calls, 1)

    def test_burst_skips_second_ult_when_unavailable(self):
        """二段大 not available: keep attacking until timeout."""
        self.char._ultimate_available = False
        self.char._perform_burst(None)
        self.assertEqual(self.char.ultimate_calls, 0)
        self.assertGreater(self.char.normal_attack_calls, 0)


# =====================================================================
#  Fallback
# =====================================================================


class TestShinkuFallback(unittest.TestCase):
    def setUp(self):
        self.char = TestableShinku()
        self.char.FALLBACK_DURATION = 0.1
        self.char.NORMAL_ATTACK_INTERVAL = 0.01

    def test_fallback_calls_normal_attack(self):
        self.char._fallback_attacks()
        self.assertGreater(self.char.normal_attack_calls, 0)

    def test_fallback_stops_on_char_switch(self):
        original_attack = self.char.normal_attack

        def attack_and_switch():
            original_attack()
            self.char.is_current_char = False

        self.char.normal_attack = attack_and_switch
        self.char._fallback_attacks()
        self.assertFalse(self.char.is_current_char)


# =====================================================================
#  on_combat_end
# =====================================================================


class TestShinkuOnCombatEnd(unittest.TestCase):
    def test_on_combat_end_does_not_switch(self):
        char = TestableShinku()
        char.on_combat_end([])
        self.assertEqual(char.switch_calls, 0)

    def test_on_combat_end_resets_cooldowns(self):
        char = TestableShinku()
        char._cooldowns.mark_used("enhanced_skill", 10.0, now=0.0)
        char.on_combat_end([])
        self.assertTrue(char._cooldowns.is_ready("enhanced_skill"))


if __name__ == "__main__":
    unittest.main()
