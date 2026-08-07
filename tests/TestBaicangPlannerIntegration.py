"""白藏真实 Planner 集成测试。

使用真实 CombatPlanner.perform_current_char()，
只 mock 输入方法（click, sleep, skill_available），不 mock planner 决策。

参考 TestCombatPlanner.py 的 FakeTask 模式。
"""

import unittest
from unittest.mock import MagicMock

from src.combat.planner import (
    ActionSlot,
    CombatPlanner,
)


class FakeTask:
    """最小 task，满足 CombatPlanner 需求。"""

    def __init__(self):
        self.chars = []
        self.reaction_target = None
        # Baicang _checkpointed_dodge 的 R 检查会调用 send_arc_key -> send_key
        self.send_key = MagicMock()
        self.get_arc_key = MagicMock(return_value="r")

    def time_elapsed_accounting_for_freeze(self, start, intro_motion_freeze=False):
        return 999

    def find_element_ring_reaction_target(self, source_char):
        return self.reaction_target


class PlannerTestableBaicang:
    """构造一个行为受控但 combat_plan 真实的白藏。

    只覆盖输入方法，不覆盖决策逻辑。
    """

    @classmethod
    def create(
        cls,
        skill_result=True,
        ultimate_result=True,
        skill_available=True,
        ultimate_available=True,
        combat_active=True,
    ):
        from src.char.Baicang import Baicang

        task = FakeTask()
        char = Baicang(task, 0, char_id="baicang")
        char.is_current_char = True
        char.is_dead = False

        # 只 mock 输入方法
        char._fake_time = 0.0
        char._skill_calls = 0
        char._ultimate_calls = 0
        char._fallback_calls = 0
        char._normal_attack_calls = 0
        char._burst_called = False
        char._post_skill_dodge_called = False
        char._skill_result = skill_result
        char._ultimate_result = ultimate_result
        char._skill_available = skill_available
        char._ultimate_available = ultimate_available
        char._combat_active = combat_active

        def mock_now():
            return char._fake_time

        def mock_sleep(sec, sleep_check=True):
            char._fake_time += sec

        def mock_skill_available(check_color=True):
            return char._skill_available

        def mock_ultimate_available(check_color=True):
            return char._ultimate_available

        def mock_click_skill(**kwargs):
            char._skill_calls += 1
            return char._skill_result

        def mock_click_ultimate(**kwargs):
            char._ultimate_calls += 1
            return char._ultimate_result

        def mock_check_combat():
            if not char._combat_active:
                from src.combat.BaseCombatTask import NotInCombatException

                raise NotInCombatException("test")

        def mock_continues_right_click(duration, interval=0.1, direction_key=None):
            char._fallback_calls += 1
            char._fake_time += duration

        def mock_normal_attack():
            char._normal_attack_calls += 1
            char._fake_time += 0.18

        def mock_perform_burst(context=None, first_skill_succeeded=False):
            char._burst_called = True
            char._fake_time += 0.1

        def mock_post_skill_dodge():
            char._post_skill_dodge_called = True
            char._fake_time += 0.1

        def mock_click(*args, **kwargs):
            if kwargs.get("key") == "right":
                char._fallback_calls += 1
            interval = kwargs.get("interval", -1)
            if interval > 0:
                char._fake_time += interval

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
        char._post_skill_dodge = mock_post_skill_dodge
        char.task.click = MagicMock(side_effect=mock_click)
        char.logger = MagicMock()

        return char


class TestBaicangPlannerIntegration(unittest.TestCase):
    """用真实 CombatPlanner 验证 Baicang combat_plan 的 planner 语义。"""

    def _planner(self, chars):
        task = FakeTask()
        task.chars = chars
        planner = CombatPlanner(task)
        planner.reset(chars)
        return planner

    def test_skill_executed_when_ultimate_unavailable(self):
        """Q-first 设计: 大招不可用时, entry 落到 skill 并执行。"""
        char = PlannerTestableBaicang.create(
            skill_result=True,
            ultimate_result=False,
            skill_available=True,
            ultimate_available=False,
        )
        planner = self._planner([char])
        planner.perform_current_char(char)
        self.assertGreater(char._skill_calls, 0)

    def test_ultimate_after_skill_success(self):
        """skill 成功 + ultimate_available → history 中有 ultimate。"""
        char = PlannerTestableBaicang.create(
            skill_result=True,
            ultimate_result=True,
            skill_available=True,
            ultimate_available=True,
        )
        planner = self._planner([char])
        planner.perform_current_char(char)
        self.assertGreater(char._ultimate_calls, 0)

    def test_fallback_dodge_when_both_fail(self):
        """skill 失败 + ultimate 失败 → fallback_dodge 被执行。"""
        char = PlannerTestableBaicang.create(
            skill_result=False,
            ultimate_result=False,
            skill_available=False,
            ultimate_available=False,
        )
        planner = self._planner([char])
        planner.perform_current_char(char)
        self.assertGreater(char._normal_attack_calls, 0)

    def test_post_skill_dodge_on_e_only(self):
        """skill 成功 + ultimate 失败 → _post_skill_dodge 被调用，不调用 fallback。"""
        char = PlannerTestableBaicang.create(
            skill_result=True,
            ultimate_result=False,
            skill_available=True,
            ultimate_available=True,
        )
        planner = self._planner([char])
        planner.perform_current_char(char)
        self.assertTrue(char._post_skill_dodge_called)
        self.assertEqual(char._fallback_calls, 0)

    def test_burst_called_on_full_success(self):
        """skill 成功 + ultimate 成功 → _perform_burst 被调用。"""
        char = PlannerTestableBaicang.create(
            skill_result=True,
            ultimate_result=True,
            skill_available=True,
            ultimate_available=True,
        )
        planner = self._planner([char])
        planner.perform_current_char(char)
        self.assertTrue(char._burst_called)

    def test_no_field_time_fallback(self):
        """MAX_FIELD_TIME=0 → Planner 不生成通用平A fallback。"""
        from src.char.Baicang import Baicang

        # Baicang.MAX_FIELD_TIME 应为 0
        self.assertEqual(Baicang.MAX_FIELD_TIME, 0)

    def test_fallback_dodge_priority_ready_false(self):
        """fallback_dodge 的 priority_ready 为 False → Planner 不会因此切人。"""
        char = PlannerTestableBaicang.create()
        plan = char.combat_plan(None)
        fallback = [a for a in plan.actions if a.name == "baicang_dodge_fallback"]
        self.assertEqual(len(fallback), 1)
        self.assertFalse(fallback[0].priority_ready(None))

    def test_skill_action_has_skill_slot(self):
        """skill action 的 slot 为 SKILL → reservation 不冲突。"""
        char = PlannerTestableBaicang.create()
        plan = char.combat_plan(None)
        skill_action = [a for a in plan.actions if "skill" in a.name and "fallback" not in a.name]
        self.assertEqual(len(skill_action), 1)
        self.assertEqual(skill_action[0].slot, ActionSlot.SKILL)

    def test_no_crash_when_no_actions_available(self):
        """Baicang 无可用动作时 Planner 不崩溃。"""
        char = PlannerTestableBaicang.create(
            skill_result=False,
            ultimate_result=False,
            skill_available=False,
            ultimate_available=False,
        )
        char._skill_result = False
        char._ultimate_result = False
        planner = self._planner([char])
        # 不应抛异常
        planner.perform_current_char(char)
        # The conservative V1 fallback should keep dealing normal-attack damage.
        self.assertGreater(char._normal_attack_calls, 0)


if __name__ == "__main__":
    unittest.main()
