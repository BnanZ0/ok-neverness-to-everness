"""伊洛伊(Iloy)自动战斗逻辑单元测试."""

import unittest
from unittest.mock import MagicMock

from src.char.BaseChar import BaseChar, Element
from src.char.core.CharFactory import _build_char_instance
from src.char.core.CharRegistry import char_registry
from src.char.custom.CustomCharManager import CustomCharManager
from src.char.Iloy import Iloy
from src.char.Iroi import Iroi
from src.char.Mint import Mint
from src.char.Shinku import Shinku
from src.char.Zero import Zero
from src.combat.planner import ActionSlot, FieldPreference, Role


class TestableBase:
    """Testable mixin: fake clock, empty sleep, mock input methods."""

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
        self.heavy_attack_calls = 0
        self.heavy_attack_durations = []
        self.normal_attack_calls = 0

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

    def heavy_attack(self, duration):
        self.heavy_attack_calls += 1
        self.heavy_attack_durations.append(duration)
        self._fake_time += duration

    def normal_attack(self):
        self.normal_attack_calls += 1
        self._fake_time += 0.3

    def check_combat(self):
        pass


class TestableIloy(TestableBase, Iloy):
    __test__ = False

    def __init__(self, task=None, index=0, char_id="iloy"):
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
    """Create a fake 999-night team: Iloy + Mint + Shinku + Zero."""
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


class TestIloyFactory(unittest.TestCase):
    def test_registry_contains_iloy(self):
        self.assertIsNotNone(char_registry.get("builtin:iloy"))

    def test_registry_cls_is_iloy(self):
        self.assertIs(char_registry.get("builtin:iloy").char_cls, Iloy)

    def test_registry_cn_name(self):
        self.assertEqual(char_registry.get("builtin:iloy").cn_name, "伊洛伊")

    def test_registry_element_is_green(self):
        self.assertEqual(char_registry.get("builtin:iloy").element, Element.GREEN)

    def test_iloy_is_subclass_of_basechar(self):
        self.assertTrue(issubclass(Iloy, BaseChar))

    def test_upstream_iroi_id_uses_the_same_combat_logic(self):
        self.assertTrue(issubclass(Iroi, Iloy))
        self.assertIs(char_registry.get("builtin:iroi").char_cls, Iroi)

    def test_blank_impl_profile_falls_back_to_base_char(self):
        manager = MagicMock()
        manager.get_character_info_by_id.return_value = {
            "char_id": "saved_iloy",
            "char_name": "伊洛伊",
            "impl_id": "",
        }

        char = _build_char_instance(
            MagicMock(),
            2,
            "saved_iloy",
            1.0,
            manager,
            impl_id_override="",
        )

        self.assertIsInstance(char, BaseChar)

    def test_explicit_iloy_impl_binds_to_real_combat_class(self):
        manager = MagicMock()
        manager.get_character_info_by_id.return_value = {
            "char_id": "saved_iloy",
            "char_name": "伊洛伊",
            "impl_id": "builtin:iloy",
        }

        char = _build_char_instance(
            MagicMock(),
            2,
            "saved_iloy",
            1.0,
            manager,
            impl_id_override="builtin:iloy",
        )

        self.assertIsInstance(char, Iloy)
        self.assertEqual(char.impl_id, "builtin:iloy")

    def test_explicit_iroi_impl_uses_compatibility_class(self):
        manager = MagicMock()
        manager.get_character_info_by_id.return_value = {
            "char_id": "saved_iroi",
            "char_name": "Iroi",
            "impl_id": "builtin:iroi",
        }

        char = _build_char_instance(
            MagicMock(),
            2,
            "saved_iroi",
            1.0,
            manager,
            impl_id_override="builtin:iroi",
        )

        self.assertIsInstance(char, Iroi)


# =====================================================================
#  Role (non-team)
# =====================================================================


class TestIloyRoleNonTeam(unittest.TestCase):
    def setUp(self):
        self.char = TestableIloy()

    def test_role_is_sub_dps(self):
        self.assertEqual(self.char.describe_role().role, Role.SUB_DPS)

    def test_field_preference_is_sub_dps_when_not_in_team(self):
        self.assertEqual(
            self.char.describe_role().field_preference, FieldPreference.SUB_DPS
        )

    def test_max_field_time_is_zero(self):
        self.assertEqual(self.char.describe_role().max_field_time, 0)

    def test_combat_start_priority_is_zero_when_not_in_team(self):
        self.assertEqual(self.char.describe_role().combat_start_priority, 0)


# =====================================================================
#  Role (999-night team)
# =====================================================================


class TestIloyRoleInTeam(unittest.TestCase):
    def setUp(self):
        self.task, self.iloy, self.mint, self.shinku, self.zero = (
            make_999night_team()
        )

    def test_role_is_sub_dps_in_team(self):
        self.assertEqual(self.iloy.describe_role().role, Role.SUB_DPS)

    def test_field_preference_is_setup_only_in_team(self):
        self.assertEqual(
            self.iloy.describe_role().field_preference, FieldPreference.SETUP_ONLY
        )

    def test_max_field_time_is_zero_in_team(self):
        self.assertEqual(self.iloy.describe_role().max_field_time, 0)

    def test_combat_start_priority_is_100_in_team(self):
        self.assertEqual(self.iloy.describe_role().combat_start_priority, 100)


# =====================================================================
#  Combat plan
# =====================================================================


class TestIloyCombatPlan(unittest.TestCase):
    def setUp(self):
        self.char = TestableIloy()

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

    def test_heavy_attack_duration_is_2_5(self):
        self.assertEqual(Iloy.HEAVY_ATTACK_DURATION, 2.5)

    def _run_entry_non_team(self, skill_result, ultimate_result):
        plan = self.char.combat_plan(None)
        gen = plan.entry()
        next(gen)  # yield skill
        gen.send(skill_result)  # skill result
        with self.assertRaises(StopIteration):
            gen.send(ultimate_result)

    def test_heavy_attack_on_full_success(self):
        self._run_entry_non_team(skill_result=True, ultimate_result=True)
        self.assertEqual(self.char.heavy_attack_calls, 1)
        self.assertAlmostEqual(
            self.char.heavy_attack_durations[0], self.char.HEAVY_ATTACK_DURATION
        )

    def test_heavy_attack_on_skill_success_ultimate_fail(self):
        self._run_entry_non_team(skill_result=True, ultimate_result=False)
        self.assertEqual(self.char.heavy_attack_calls, 1)

    def test_no_heavy_attack_on_both_fail(self):
        self._run_entry_non_team(skill_result=False, ultimate_result=False)
        self.assertEqual(self.char.heavy_attack_calls, 0)

    def test_setup_team_does_not_normal_attack_when_e_and_q_are_unavailable(self):
        task = FakeTask()
        char = TestableIloy(task, 0)
        mint = Mint(task, 1, char_id="mint")
        shinku = Shinku(task, 2, char_id="shinku")
        zero = Zero(task, 3, char_id="zero")
        task.chars = [char, mint, shinku, zero]
        char._skill_available = False
        char._ultimate_available = False

        plan = char.combat_plan(None)
        flow = plan.entry()
        next(flow)
        flow.send(False)
        with self.assertRaises(StopIteration):
            flow.send(False)

        self.assertEqual(char.normal_attack_calls, 0)
        self.assertEqual(char.heavy_attack_calls, 0)


# =====================================================================
#  Skill cooldown
# =====================================================================


class TestIloySkillCooldown(unittest.TestCase):
    def setUp(self):
        self.char = TestableIloy()

    def test_skill_marks_cooldown_on_success(self):
        plan = self.char.combat_plan(None)
        skill_action = [a for a in plan.actions if "skill" in a.name][0]
        skill_action.execute(None)
        self.assertFalse(self.char._cooldowns.is_ready("skill"))

    def test_skill_cooldown_expires(self):
        self.char._cooldowns.mark_used("skill", 4.0, now=0.0)
        self.assertFalse(self.char._cooldowns.is_ready("skill", now=3.0))
        self.assertTrue(self.char._cooldowns.is_ready("skill", now=5.0))

    def test_on_combat_end_resets_cooldowns(self):
        self.char._cooldowns.mark_used("skill", 10.0, now=0.0)
        self.char.on_combat_end([])
        self.assertTrue(self.char._cooldowns.is_ready("skill"))


if __name__ == "__main__":
    unittest.main()
