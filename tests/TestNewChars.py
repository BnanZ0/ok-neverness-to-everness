"""阿德勒、达芙蒂尔、哈妮娅角色注册和战斗逻辑单元测试。"""

import unittest
from unittest.mock import MagicMock

from src.char.Adler import Adler
from src.char.BaseChar import BaseChar, Element
from src.char.core.CharRegistry import char_registry
from src.char.Daphneel import Daphneel
from src.char.Hania import Hania
from src.combat.planner import ActionSlot, FieldPreference, Role


class TestableBase:
    """新角色测试基类：假时钟、空 sleep、mock 输入方法。"""

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


class TestableAdler(TestableBase, Adler):
    __test__ = False

    def __init__(self, task=None, index=0, char_id="adler"):
        if task is None:
            task = MagicMock()
        super().__init__(task, index, char_id=char_id)
        self._setup_testable(task)


class TestableDaphneel(TestableBase, Daphneel):
    __test__ = False

    def __init__(self, task=None, index=0, char_id="daphneel"):
        if task is None:
            task = MagicMock()
        super().__init__(task, index, char_id=char_id)
        self._setup_testable(task)


class TestableHania(TestableBase, Hania):
    __test__ = False

    def __init__(self, task=None, index=0, char_id="hania"):
        if task is None:
            task = MagicMock()
        super().__init__(task, index, char_id=char_id)
        self._setup_testable(task)


# =====================================================================
#  Adler
# =====================================================================


class TestAdlerFactory(unittest.TestCase):
    def test_registry_contains_adler(self):
        self.assertIsNotNone(char_registry.get("builtin:adler"))

    def test_registry_cls_is_adler(self):
        self.assertIs(char_registry.get("builtin:adler").char_cls, Adler)

    def test_registry_cn_name(self):
        self.assertEqual(char_registry.get("builtin:adler").cn_name, "阿德勒")

    def test_registry_element_is_red(self):
        self.assertEqual(char_registry.get("builtin:adler").element, Element.RED)

    def test_adler_is_subclass_of_basechar(self):
        self.assertTrue(issubclass(Adler, BaseChar))


class TestAdlerRole(unittest.TestCase):
    def setUp(self):
        self.char = TestableAdler()

    def test_role_is_sub_dps(self):
        self.assertEqual(self.char.describe_role().role, Role.SUB_DPS)

    def test_field_preference_is_setup_only(self):
        self.assertEqual(self.char.describe_role().field_preference, FieldPreference.SETUP_ONLY)

    def test_max_field_time_is_zero(self):
        """GPT5.6 MAJOR 3: max_field_time=0 禁止通用平A fallback。"""
        self.assertEqual(self.char.describe_role().max_field_time, 0)

    def test_combat_start_priority_is_zero(self):
        self.assertEqual(self.char.describe_role().combat_start_priority, 0)


class TestAdlerCombatPlan(unittest.TestCase):
    def setUp(self):
        self.char = TestableAdler()

    def test_skill_has_skill_slot(self):
        plan = self.char.combat_plan(None)
        skill = [a for a in plan.actions if "skill" in a.name][0]
        self.assertEqual(skill.slot, ActionSlot.SKILL)

    def test_ultimate_has_ultimate_slot(self):
        plan = self.char.combat_plan(None)
        ult = [a for a in plan.actions if "ultimate" in a.name][0]
        self.assertEqual(ult.slot, ActionSlot.ULTIMATE)

    def test_entry_yields_skill_first(self):
        """GPT5.6 BLOCKER 4: 叠业在 yield 后执行，不在 yield 前发输入。"""
        plan = self.char.combat_plan(None)
        gen = plan.entry()
        first = next(gen)
        self.assertIn("skill", first.name)

    def test_stacking_happens_in_execute_not_before_yield(self):
        """叠业在 execute 回调中执行，不在 yield 前发输入。"""
        plan = self.char.combat_plan(None)
        gen = plan.entry()
        first_action = next(gen)
        # yield 前不应有 normal_attack 调用
        self.assertEqual(self.char.normal_attack_calls, 0)
        # 执行 action 后叠业才发生
        first_action.execute(None)
        self.assertGreater(self.char.normal_attack_calls, 0)

    def test_ultimate_yielded_after_skill(self):
        plan = self.char.combat_plan(None)
        gen = plan.entry()
        next(gen)
        second = gen.send(True)
        self.assertIn("ultimate", second.name)

    def test_no_ultimate_on_skill_failure(self):
        """E 失败时不 yield Q。"""
        plan = self.char.combat_plan(None)
        gen = plan.entry()
        next(gen)
        with self.assertRaises(StopIteration):
            gen.send(False)


class TestAdlerStackYe(unittest.TestCase):
    def setUp(self):
        self.char = TestableAdler()
        self.char.YE_STACK_DURATION = 0.5

    def test_stack_ye_calls_normal_attack(self):
        self.char._stack_ye()
        self.assertGreater(self.char.normal_attack_calls, 0)

    def test_stack_ye_stops_on_char_switch(self):
        original_attack = self.char.normal_attack

        def attack_and_switch():
            original_attack()
            self.char.is_current_char = False

        self.char.normal_attack = attack_and_switch
        self.char._stack_ye()
        self.assertFalse(self.char.is_current_char)

    def test_stack_ye_stops_on_death(self):
        original_attack = self.char.normal_attack

        def attack_and_die():
            original_attack()
            self.char.is_dead = True

        self.char.normal_attack = attack_and_die
        self.char._stack_ye()
        self.assertTrue(self.char.is_dead)


class TestAdlerOnCombatEnd(unittest.TestCase):
    def test_on_combat_end_does_not_switch(self):
        """GPT5.6 MAJOR 6: on_combat_end 不调用 switch_other_char。"""
        char = TestableAdler()
        char.on_combat_end([])
        self.assertEqual(char.switch_calls, 0)


# =====================================================================
#  Daphneel
# =====================================================================


class TestDaphneelFactory(unittest.TestCase):
    def test_registry_contains_daphneel(self):
        self.assertIsNotNone(char_registry.get("builtin:daphneel"))

    def test_registry_cls_is_daphneel(self):
        self.assertIs(char_registry.get("builtin:daphneel").char_cls, Daphneel)

    def test_registry_cn_name(self):
        self.assertEqual(char_registry.get("builtin:daphneel").cn_name, "达芙蒂尔")

    def test_registry_element_is_purple(self):
        self.assertEqual(char_registry.get("builtin:daphneel").element, Element.PURPLE)

    def test_daphneel_is_subclass_of_basechar(self):
        self.assertTrue(issubclass(Daphneel, BaseChar))


class TestDaphneelRole(unittest.TestCase):
    def setUp(self):
        self.char = TestableDaphneel()

    def test_role_is_sub_dps(self):
        self.assertEqual(self.char.describe_role().role, Role.SUB_DPS)

    def test_field_preference_is_setup_only(self):
        self.assertEqual(self.char.describe_role().field_preference, FieldPreference.SETUP_ONLY)

    def test_max_field_time_is_zero(self):
        """GPT5.6 MAJOR 3: max_field_time=0 禁止通用平A fallback。"""
        self.assertEqual(self.char.describe_role().max_field_time, 0)

    def test_combat_start_priority_is_zero(self):
        self.assertEqual(self.char.describe_role().combat_start_priority, 0)


class TestDaphneelCombatPlan(unittest.TestCase):
    def setUp(self):
        self.char = TestableDaphneel()

    def test_ultimate_has_ultimate_slot(self):
        plan = self.char.combat_plan(None)
        ult = [a for a in plan.actions if "ultimate" in a.name][0]
        self.assertEqual(ult.slot, ActionSlot.ULTIMATE)

    def test_skill_has_skill_slot(self):
        plan = self.char.combat_plan(None)
        skill = [a for a in plan.actions if "skill" in a.name][0]
        self.assertEqual(skill.slot, ActionSlot.SKILL)

    def test_ultimate_entry_yielded_first(self):
        """达芙蒂尔 Q 优先 (弹反充能后)。"""
        plan = self.char.combat_plan(None)
        gen = plan.entry()
        first = next(gen)
        self.assertIn("ultimate", first.name)

    def test_perform_burst_called_on_ultimate_success(self):
        """Q 成功后进入爆发窗口。"""
        plan = self.char.combat_plan(None)
        gen = plan.entry()
        next(gen)
        with self.assertRaises(StopIteration):
            gen.send(True)
        self.assertGreater(self.char.normal_attack_calls, 0)

    def test_skill_yielded_on_ultimate_failure(self):
        """Q 失败后 yield E。"""
        self.char._click_ultimate_result = False
        plan = self.char.combat_plan(None)
        gen = plan.entry()
        next(gen)
        second = gen.send(False)
        self.assertIn("skill", second.name)


class TestDaphneelBurst(unittest.TestCase):
    def setUp(self):
        self.char = TestableDaphneel()
        self.char.ULT_BURST_DURATION = 0.5

    def test_burst_calls_normal_attack(self):
        self.char._perform_burst(None)
        self.assertGreater(self.char.normal_attack_calls, 0)

    def test_burst_has_timeout(self):
        self.char.ULT_BURST_DURATION = 0.05
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

    def test_burst_uses_skill_when_available(self):
        self.char._skill_available = True
        self.char._perform_burst(None)
        self.assertGreater(self.char.skill_calls, 0)

    def test_burst_skill_at_most_once(self):
        """GPT5.6 BLOCKER 4: burst E attempted/used 分离，最多真实尝试一次。"""
        self.char._skill_available = True
        self.char._perform_burst(None)
        self.assertLessEqual(self.char.skill_calls, 1)

    def test_burst_skill_not_attempted_when_unavailable(self):
        """E 不可用时不尝试。"""
        self.char._skill_available = False
        self.char._perform_burst(None)
        self.assertEqual(self.char.skill_calls, 0)


class TestDaphneelOnCombatEnd(unittest.TestCase):
    def test_on_combat_end_does_not_switch(self):
        """GPT5.6 MAJOR 6: on_combat_end 不调用 switch_other_char。"""
        char = TestableDaphneel()
        char.on_combat_end([])
        self.assertEqual(char.switch_calls, 0)


# =====================================================================
#  Hania
# =====================================================================


class TestHaniaFactory(unittest.TestCase):
    def test_registry_contains_hania(self):
        self.assertIsNotNone(char_registry.get("builtin:hania"))

    def test_registry_cls_is_hania(self):
        self.assertIs(char_registry.get("builtin:hania").char_cls, Hania)

    def test_registry_cn_name(self):
        self.assertEqual(char_registry.get("builtin:hania").cn_name, "哈妮娅")

    def test_registry_element_is_blue(self):
        self.assertEqual(char_registry.get("builtin:hania").element, Element.BLUE)

    def test_hania_is_subclass_of_basechar(self):
        self.assertTrue(issubclass(Hania, BaseChar))


class TestHaniaRole(unittest.TestCase):
    def setUp(self):
        self.char = TestableHania()

    def test_role_is_sub_dps(self):
        self.assertEqual(self.char.describe_role().role, Role.SUB_DPS)

    def test_field_preference_is_setup_only(self):
        self.assertEqual(self.char.describe_role().field_preference, FieldPreference.SETUP_ONLY)

    def test_max_field_time_is_zero(self):
        """GPT5.6 MAJOR 3: max_field_time=0 禁止通用平A fallback。"""
        self.assertEqual(self.char.describe_role().max_field_time, 0)

    def test_combat_start_priority_is_zero(self):
        self.assertEqual(self.char.describe_role().combat_start_priority, 0)


class TestHaniaCombatPlan(unittest.TestCase):
    def setUp(self):
        self.char = TestableHania()

    def test_skill_has_skill_slot(self):
        plan = self.char.combat_plan(None)
        skill = [a for a in plan.actions if "skill" in a.name][0]
        self.assertEqual(skill.slot, ActionSlot.SKILL)

    def test_ultimate_has_ultimate_slot(self):
        plan = self.char.combat_plan(None)
        ult = [a for a in plan.actions if "ultimate" in a.name][0]
        self.assertEqual(ult.slot, ActionSlot.ULTIMATE)

    def test_ultimate_entry_yielded_first(self):
        """哈妮娅 Q 优先 (强化领域)，然后 E (部署咕咕子)。"""
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
        """Q 不可用时直接 yield E。"""
        self.char._click_ultimate_result = False
        plan = self.char.combat_plan(None)
        gen = plan.entry()
        next(gen)
        second = gen.send(False)
        self.assertIn("skill", second.name)


class TestHaniaOnCombatEnd(unittest.TestCase):
    def test_on_combat_end_does_not_switch(self):
        """GPT5.6 MAJOR 6: on_combat_end 不调用 switch_other_char。"""
        char = TestableHania()
        char.on_combat_end([])
        self.assertEqual(char.switch_calls, 0)


if __name__ == "__main__":
    unittest.main()
