"""薄荷(Mint)自动战斗逻辑单元测试."""

import unittest
from unittest.mock import MagicMock

from src.char.BaseChar import BaseChar, Element
from src.char.core.CharRegistry import char_registry
from src.char.Iloy import Iloy
from src.char.Mint import Mint
from src.char.Shinku import Shinku
from src.char.Zero import Zero
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

    def check_combat(self):
        pass

    def switch_other_char(self):
        self.switch_calls += 1


class TestableMint(TestableBase, Mint):
    __test__ = False

    def __init__(self, task=None, index=0, char_id="mint"):
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


class TestMintFactory(unittest.TestCase):
    def test_registry_contains_mint(self):
        self.assertIsNotNone(char_registry.get("builtin:mint"))

    def test_registry_cls_is_mint(self):
        self.assertIs(char_registry.get("builtin:mint").char_cls, Mint)

    def test_registry_cn_name(self):
        self.assertEqual(char_registry.get("builtin:mint").cn_name, "薄荷")

    def test_registry_element_is_green(self):
        self.assertEqual(char_registry.get("builtin:mint").element, Element.GREEN)

    def test_mint_is_subclass_of_basechar(self):
        self.assertTrue(issubclass(Mint, BaseChar))


# =====================================================================
#  Role (non-team)
# =====================================================================


class TestMintRoleNonTeam(unittest.TestCase):
    def setUp(self):
        self.char = TestableMint()

    def test_role_is_sub_dps(self):
        self.assertEqual(self.char.describe_role().role, Role.SUB_DPS)

    def test_field_preference_is_sub_dps_when_not_in_team(self):
        self.assertEqual(
            self.char.describe_role().field_preference, FieldPreference.SUB_DPS
        )

    def test_max_field_time_is_zero(self):
        self.assertEqual(self.char.describe_role().max_field_time, 0)


# =====================================================================
#  Role (999-night team)
# =====================================================================


class TestMintRoleInTeam(unittest.TestCase):
    def setUp(self):
        self.task, self.iloy, self.mint, self.shinku, self.zero = (
            make_999night_team()
        )

    def test_role_is_sub_dps_in_team(self):
        self.assertEqual(self.mint.describe_role().role, Role.SUB_DPS)

    def test_field_preference_is_setup_only_in_team(self):
        self.assertEqual(
            self.mint.describe_role().field_preference, FieldPreference.SETUP_ONLY
        )

    def test_max_field_time_is_zero_in_team(self):
        self.assertEqual(self.mint.describe_role().max_field_time, 0)


# =====================================================================
#  Combat plan
# =====================================================================


class TestMintCombatPlan(unittest.TestCase):
    def setUp(self):
        self.char = TestableMint()

    def test_ultimate_has_ultimate_slot(self):
        plan = self.char.combat_plan(None)
        ult = [a for a in plan.actions if "ultimate" in a.name][0]
        self.assertEqual(ult.slot, ActionSlot.ULTIMATE)

    def test_skill_has_skill_slot(self):
        plan = self.char.combat_plan(None)
        skill = [a for a in plan.actions if "skill" in a.name][0]
        self.assertEqual(skill.slot, ActionSlot.SKILL)

    def test_entry_yields_ultimate_first(self):
        plan = self.char.combat_plan(None)
        gen = plan.entry()
        first = next(gen)
        self.assertIn("ultimate", first.name)

    def test_skill_yielded_after_ultimate(self):
        plan = self.char.combat_plan(None)
        gen = plan.entry()
        next(gen)
        second = gen.send(True)
        self.assertIn("skill", second.name)

    def test_skill_yielded_on_ultimate_failure(self):
        self.char._click_ultimate_result = False
        plan = self.char.combat_plan(None)
        gen = plan.entry()
        next(gen)
        second = gen.send(False)
        self.assertIn("skill", second.name)

    def test_no_field_claims(self):
        plan = self.char.combat_plan(None)
        self.assertEqual(len(plan.claims), 0)


# =====================================================================
#  Skill cooldown
# =====================================================================


class TestMintSkillCooldown(unittest.TestCase):
    def setUp(self):
        self.char = TestableMint()

    def test_skill_marks_cooldown_on_success(self):
        plan = self.char.combat_plan(None)
        skill_action = [a for a in plan.actions if "skill" in a.name][0]
        skill_action.execute(None)
        self.assertFalse(self.char._cooldowns.is_ready("skill"))

    def test_skill_cooldown_expires(self):
        self.char._cooldowns.mark_used("skill", 6.0, now=0.0)
        self.assertFalse(self.char._cooldowns.is_ready("skill", now=5.0))
        self.assertTrue(self.char._cooldowns.is_ready("skill", now=7.0))


# =====================================================================
#  on_combat_end
# =====================================================================


class TestMintOnCombatEnd(unittest.TestCase):
    def test_on_combat_end_does_not_switch(self):
        char = TestableMint()
        char.on_combat_end([])
        self.assertEqual(char.switch_calls, 0)

    def test_on_combat_end_resets_cooldowns(self):
        char = TestableMint()
        char._cooldowns.mark_used("skill", 10.0, now=0.0)
        char.on_combat_end([])
        self.assertTrue(char._cooldowns.is_ready("skill"))


if __name__ == "__main__":
    unittest.main()
