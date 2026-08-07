"""四角色真实 Planner 仿真测试。

使用真实 CombatPlanner，构造四人队伍，验证轮转逻辑。
只 mock 输入方法（click, sleep, skill_available），不 mock planner 决策。

参考 TestCombatPlanner.py 的 FakeTask 模式。
"""

import unittest
from unittest.mock import MagicMock

from src.char.Adler import Adler
from src.char.Baicang import Baicang
from src.char.Daphneel import Daphneel
from src.char.Hania import Hania
from src.combat.BaseCombatTask import NotInCombatException
from src.combat.planner import (
    ActionSlot,
    CombatPlanner,
    FieldPreference,
)


class FakeTask:
    """最小 task，满足 CombatPlanner 需求。"""

    def __init__(self):
        self.chars = []
        self.reaction_target = None
        # Baicang _checkpointed_dodge R 检查需要 send_key 和 get_arc_key
        from unittest.mock import MagicMock
        self.send_key = MagicMock()
        self.get_arc_key = MagicMock(return_value="r")

    def time_elapsed_accounting_for_freeze(self, start, intro_motion_freeze=False):
        return 999

    def find_element_ring_reaction_target(self, source_char):
        return self.reaction_target


def make_testable(char_cls, index, **kwargs):
    """创建一个行为受控但 combat_plan 真实的角色。"""
    task = FakeTask()
    char = char_cls(task, index, char_id=f"char_{index}")
    char.is_current_char = False
    char.is_dead = False

    char._fake_time = 0.0
    char._skill_available = kwargs.get("skill_available", True)
    char._ultimate_available = kwargs.get("ultimate_available", True)
    char._skill_result = kwargs.get("skill_result", True)
    char._ultimate_result = kwargs.get("ultimate_result", True)
    char._combat_active = True
    char.skill_calls = 0
    char.ultimate_calls = 0
    char.normal_attack_calls = 0
    char.fallback_calls = 0
    char._burst_called = False

    def mock_now():
        return char._fake_time

    def mock_sleep(sec, sleep_check=True):
        char._fake_time += sec

    def mock_skill_available(check_color=True):
        return char._skill_available

    def mock_ultimate_available(check_color=True):
        return char._ultimate_available

    def mock_click_skill(**kw):
        char.skill_calls += 1
        return char._skill_result

    def mock_click_ultimate(**kw):
        char.ultimate_calls += 1
        return char._ultimate_result

    def mock_check_combat():
        if not char._combat_active:
            raise NotInCombatException("test")

    def mock_continues_right_click(duration, interval=0.1, direction_key=None):
        char.fallback_calls += 1
        char._fake_time += duration

    def mock_normal_attack():
        char.normal_attack_calls += 1
        char._fake_time += 0.3

    def mock_click(*args, **kwargs):
        if kwargs.get("key") == "right":
            char.fallback_calls += 1
        interval = kwargs.get("interval", -1)
        if interval > 0:
            char._fake_time += interval

    def mock_perform_burst(context=None, first_skill_succeeded=False):
        char._burst_called = True
        char._fake_time += 0.1

    char._now = mock_now
    char.sleep = mock_sleep
    char.skill_available = mock_skill_available
    char.ultimate_available = mock_ultimate_available
    char.click_skill = mock_click_skill
    char.click_ultimate = mock_click_ultimate
    char.check_combat = mock_check_combat
    char.continues_right_click = mock_continues_right_click
    char.normal_attack = mock_normal_attack
    char._perform_burst = mock_perform_burst
    char.task.click = MagicMock(side_effect=mock_click)
    char.logger = MagicMock()

    return char


class TestTeamSimulation(unittest.TestCase):
    """四角色真实 Planner 仿真。"""

    def _make_team(self, **overrides):
        """创建四人队伍：哈妮娅(0), 阿德勒(1), 达芙蒂尔(2), 白藏(3)。"""
        chars = [
            make_testable(
                Hania,
                0,
                **{
                    k.replace("hania_", ""): v
                    for k, v in overrides.items()
                    if k.startswith("hania_")
                },
            ),
            make_testable(
                Adler,
                1,
                **{
                    k.replace("adler_", ""): v
                    for k, v in overrides.items()
                    if k.startswith("adler_")
                },
            ),
            make_testable(
                Daphneel,
                2,
                **{
                    k.replace("daphneel_", ""): v
                    for k, v in overrides.items()
                    if k.startswith("daphneel_")
                },
            ),
            make_testable(
                Baicang,
                3,
                **{
                    k.replace("baicang_", ""): v
                    for k, v in overrides.items()
                    if k.startswith("baicang_")
                },
            ),
        ]
        task = FakeTask()
        task.chars = chars
        planner = CombatPlanner(task)
        planner.reset(chars)
        return planner, chars

    def _set_current(self, chars, index):
        for i, c in enumerate(chars):
            c.is_current_char = i == index

    # ---- 单角色独立验证 ----

    def test_hania_q_then_e(self):
        """哈妮娅单独执行：Q 优先 → E。"""
        planner, chars = self._make_team()
        self._set_current(chars, 0)
        planner.perform_current_char(chars[0])
        self.assertGreater(chars[0].ultimate_calls, 0)

    def test_adler_skill_then_ultimate(self):
        """阿德勒单独执行：叠业+E → Q。"""
        planner, chars = self._make_team()
        self._set_current(chars, 1)
        planner.perform_current_char(chars[1])
        self.assertGreater(chars[1].skill_calls, 0)

    def test_daphneel_ultimate_first(self):
        """达芙蒂尔单独执行：Q 优先 → burst。"""
        planner, chars = self._make_team()
        self._set_current(chars, 2)
        planner.perform_current_char(chars[2])
        self.assertGreater(chars[2].ultimate_calls, 0)

    def test_baicang_ultimate_first(self):
        """白藏单独执行：Q 优先 → burst。"""
        planner, chars = self._make_team()
        self._set_current(chars, 3)
        planner.perform_current_char(chars[3])
        self.assertGreater(chars[3].ultimate_calls, 0)

    # ---- 全角色无可用动作 ----

    def test_all_unavailable_no_crash(self):
        """四角色都无可用动作时 Planner 不崩溃。"""
        planner, chars = self._make_team(
            hania_skill_available=False,
            hania_ultimate_available=False,
            adler_skill_available=False,
            adler_ultimate_available=False,
            daphneel_skill_available=False,
            daphneel_ultimate_available=False,
            baicang_skill_available=False,
            baicang_ultimate_available=False,
        )
        for i in range(4):
            self._set_current(chars, i)
            planner.perform_current_char(chars[i])

    # ---- 角色属性验证 ----

    def test_all_max_field_time_zero(self):
        """GPT5.6 MAJOR 3: 所有角色 max_field_time=0。"""
        planner, chars = self._make_team()
        for char in chars:
            self.assertEqual(char.describe_role().max_field_time, 0)

    def test_supports_are_setup_only(self):
        """辅助角色 field_preference=SETUP_ONLY。"""
        planner, chars = self._make_team()
        self.assertEqual(chars[0].describe_role().field_preference, FieldPreference.SETUP_ONLY)
        self.assertEqual(chars[1].describe_role().field_preference, FieldPreference.SETUP_ONLY)

    def test_baicang_is_main_dps_and_daphneel_is_setup_only(self):
        """白藏长期站场，达芙蒂尔只做爆发短切。"""
        planner, chars = self._make_team()
        self.assertEqual(chars[2].describe_role().field_preference, FieldPreference.SETUP_ONLY)
        self.assertEqual(chars[3].describe_role().field_preference, FieldPreference.MAIN_DPS)

    # ---- 动作 slot 验证 ----

    def test_all_skill_actions_have_skill_slot(self):
        """所有角色的 skill action 的 slot 为 SKILL。"""
        planner, chars = self._make_team()
        for char in chars:
            plan = char.combat_plan(None)
            skill_actions = [
                a for a in plan.actions if "skill" in a.name and "fallback" not in a.name
            ]
            for a in skill_actions:
                self.assertEqual(a.slot, ActionSlot.SKILL, f"{char} skill slot mismatch")

    def test_all_ultimate_actions_have_ultimate_slot(self):
        """所有角色的 ultimate action 的 slot 为 ULTIMATE。"""
        planner, chars = self._make_team()
        for char in chars:
            plan = char.combat_plan(None)
            ult_actions = [a for a in plan.actions if "ultimate" in a.name]
            for a in ult_actions:
                self.assertEqual(a.slot, ActionSlot.ULTIMATE, f"{char} ultimate slot mismatch")

    def test_no_field_claims_across_team(self):
        """GPT5.6 BLOCKER 2: 四角色都不声明 FieldClaim。"""
        planner, chars = self._make_team()
        for char in chars:
            plan = char.combat_plan(None)
            self.assertEqual(len(plan.claims), 0, f"{char} has FieldClaim")

    # ---- 失败路径 ----

    def test_baicang_fallback_on_all_fail(self):
        """白藏 Q/E 都失败时执行 fallback_dodge。"""
        planner, chars = self._make_team(
            baicang_skill_available=False,
            baicang_ultimate_available=False,
            baicang_skill_result=False,
            baicang_ultimate_result=False,
        )
        self._set_current(chars, 3)
        planner.perform_current_char(chars[3])
        self.assertGreater(chars[3].normal_attack_calls, 0)

    def test_adler_no_ultimate_on_skill_fail(self):
        """阿德勒 E 失败时不执行 Q。"""
        planner, chars = self._make_team(
            adler_skill_result=False,
        )
        self._set_current(chars, 1)
        planner.perform_current_char(chars[1])
        self.assertEqual(chars[1].ultimate_calls, 0)


if __name__ == "__main__":
    unittest.main()
