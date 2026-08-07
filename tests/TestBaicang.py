"""白藏(Baicang)自动战斗逻辑单元测试。

使用 mock 隔离键鼠输入，只验证动作选择、调用次数和异常处理。
结构参考 TestCombatPlanner.py 的 TestableChar 模式。
"""

import unittest
from unittest.mock import MagicMock, patch

from src.char.Baicang import Baicang
from src.char.BaseChar import BaseChar, Element
from src.char.core.CharRegistry import char_registry
from src.combat.BaseCombatTask import NotInCombatException
from src.combat.planner import ActionSlot, FieldPreference, Role


class TestableBaicang(Baicang):
    """Baicang 子类：使用假时钟、空 sleep，覆盖所有输入方法。"""

    __test__ = False

    def __init__(self, task=None, index=0, char_id="baicang"):
        if task is None:
            task = MagicMock()
        super().__init__(task, index, char_id=char_id)
        self._fake_time = 0.0
        self._skill_available = False
        self._ultimate_available = False
        self._click_skill_result = True
        self._click_ultimate_result = True
        self._combat_active = True
        self._mock_burst = False
        self.skill_calls = 0
        self.ultimate_calls = 0
        self.check_combat_calls = 0
        self.fallback_calls = 0
        self.post_skill_dodge_calls = 0
        self.switch_calls = 0
        self._skill_available_sequence = None
        self._skill_available_seq_idx = 0

        def mock_click(*args, **kwargs):
            interval = kwargs.get("interval", -1)
            if interval > 0:
                self._fake_time += interval

        self.task.click.side_effect = mock_click

    def _now(self):
        return self._fake_time

    def sleep(self, sec, sleep_check=True):
        self._fake_time += sec

    def skill_available(self, check_color=True):
        if self._skill_available_sequence is not None:
            if self._skill_available_seq_idx < len(self._skill_available_sequence):
                val = self._skill_available_sequence[self._skill_available_seq_idx]
                self._skill_available_seq_idx += 1
                return val
            return False
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
        self.check_combat_calls += 1
        if not self._combat_active:
            raise NotInCombatException("test: not in combat")

    def continues_right_click(self, duration, interval=0.1, direction_key=None):
        self.fallback_calls += 1
        self._fake_time += duration

    def switch_other_char(self):
        self.switch_calls += 1

    def _post_skill_dodge(self):
        self.post_skill_dodge_calls += 1
        self._fake_time += self.POST_SKILL_DODGE_DURATION

    def _perform_burst(self, context=None):
        if self._mock_burst:
            self._fake_time += self.ULT_FIELD_DURATION
            return
        super()._perform_burst(context)


class TestBaicangFactory(unittest.TestCase):
    def test_registry_contains_baicang(self):
        self.assertIsNotNone(char_registry.get("builtin:baicang"))

    def test_registry_cls_is_baicang(self):
        self.assertIs(char_registry.get("builtin:baicang").char_cls, Baicang)

    def test_registry_cn_name(self):
        self.assertEqual(char_registry.get("builtin:baicang").cn_name, "白藏")

    def test_registry_element_is_red(self):
        self.assertEqual(char_registry.get("builtin:baicang").element, Element.RED)

    def test_baicang_is_subclass_of_basechar(self):
        self.assertTrue(issubclass(Baicang, BaseChar))


class TestBaicangRole(unittest.TestCase):
    def setUp(self):
        self.char = TestableBaicang()

    def test_role_is_main_dps(self):
        self.assertEqual(self.char.describe_role().role, Role.MAIN_DPS)

    def test_field_preference_is_main_dps(self):
        self.assertEqual(self.char.describe_role().field_preference, FieldPreference.MAIN_DPS)

    def test_max_field_time_is_zero(self):
        """GPT5.6 MAJOR 3: max_field_time=0 禁止通用平A fallback。"""
        self.assertEqual(self.char.describe_role().max_field_time, 0)

    def test_combat_start_priority_is_zero(self):
        self.assertEqual(self.char.describe_role().combat_start_priority, 0)


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
        self.char._mock_burst = True
        plan = self.char.combat_plan(None)
        gen = plan.entry()
        first = next(gen)
        self.assertIn("ultimate", first.name)
        second = gen.send(False)  # Q fails
        self.assertIn("skill", second.name)

    def test_fallback_dodge_when_both_fail(self):
        self.char._skill_available = False
        self.char._ultimate_available = False
        plan = self.char.combat_plan(None)
        gen = plan.entry()
        first = next(gen)
        self.assertIn("ultimate", first.name)
        second = gen.send(False)  # Q fails
        self.assertIn("skill", second.name)
        third = gen.send(False)  # E fails
        self.assertEqual(third.name, "baicang_dodge_fallback")

    def test_fallback_dodge_when_skill_fails_and_ultimate_unavailable(self):
        self.char._skill_available = True
        self.char._ultimate_available = False
        self.char._click_skill_result = False
        plan = self.char.combat_plan(None)
        gen = plan.entry()
        first = next(gen)
        self.assertIn("ultimate", first.name)
        second = gen.send(False)  # Q fails
        self.assertIn("skill", second.name)
        third = gen.send(False)  # E fails
        self.assertEqual(third.name, "baicang_dodge_fallback")

    def test_perform_burst_called_on_ultimate_success(self):
        self.char._skill_available = True
        self.char._ultimate_available = True
        self.char._mock_burst = True
        before_time = self.char._fake_time
        plan = self.char.combat_plan(None)
        gen = plan.entry()
        next(gen)  # yield ultimate
        with self.assertRaises(StopIteration):
            gen.send(True)  # Q success → burst → return
        self.assertGreater(self.char._fake_time, before_time)

    def test_fallback_dodge_not_attract_switching(self):
        plan = self.char.combat_plan(None)
        fallback = [a for a in plan.actions if a.name == "baicang_dodge_fallback"][0]
        self.assertFalse(fallback.priority_ready(None))

    def test_skill_action_has_skill_slot(self):
        plan = self.char.combat_plan(None)
        skill_action = [a for a in plan.actions if "skill" in a.name and "fallback" not in a.name][
            0
        ]
        self.assertEqual(skill_action.slot, ActionSlot.SKILL)

    def test_ultimate_action_has_ultimate_slot(self):
        plan = self.char.combat_plan(None)
        ult_action = [a for a in plan.actions if "ultimate" in a.name][0]
        self.assertEqual(ult_action.slot, ActionSlot.ULTIMATE)

    def test_no_field_claim(self):
        """GPT5.6 BLOCKER 2: 删除无条件 FieldClaim.high。"""
        self.char._ultimate_available = True
        plan = self.char.combat_plan(None)
        self.assertEqual(len(plan.claims), 0)

    def test_default_direction_key_is_none(self):
        """GPT5.6 MAJOR 5: 第一轮实机默认不按方向键。"""
        self.assertIsNone(Baicang.DEFAULT_DIRECTION_KEY)

    def test_post_skill_dodge_on_e_only(self):
        """Q 失败但 E 成功时有短右键输出。"""
        self.char._skill_available = True
        self.char._ultimate_available = True
        self.char._click_skill_result = True
        self.char._click_ultimate_result = False
        plan = self.char.combat_plan(None)
        gen = plan.entry()
        next(gen)  # yield ultimate
        gen.send(False)  # Q fails → yield skill
        with self.assertRaises(StopIteration):
            gen.send(True)  # E success → post_skill_dodge
        self.assertGreater(self.char.post_skill_dodge_calls, 0)

    def test_first_skill_uses_short_timeout(self):
        """GPT5.6 MAJOR 2: 第一 E 使用短 timeout。"""
        plan = self.char.combat_plan(None)
        skill_action = [a for a in plan.actions if "skill" in a.name and "fallback" not in a.name][
            0
        ]
        skill_action.execute(None)
        self.assertEqual(self.char.skill_calls, 1)


class TestBaicangBurst(unittest.TestCase):
    def setUp(self):
        self.char = TestableBaicang()
        self.char._mock_burst = False
        self.char._ultimate_available = True
        self.char._skill_available = True
        self.char.is_current_char = True
        self.char.is_dead = False

    def test_burst_has_timeout(self):
        self.char.ULT_FIELD_DURATION = 0.05
        self.char._perform_burst(None)

    def test_burst_returns_on_char_switch(self):
        calls = {"n": 0}

        def combo_with_switch():
            calls["n"] += 1
            self.char.is_current_char = False

        self.char._heavy_combo = combo_with_switch
        self.char.ULT_FIELD_DURATION = 5.0
        self.char._perform_burst(None)
        self.assertEqual(calls["n"], 1)  # loop exited right after the switch

    def test_burst_returns_on_death(self):
        calls = {"n": 0}

        def combo_with_death():
            calls["n"] += 1
            self.char.is_dead = True

        self.char._heavy_combo = combo_with_death
        self.char.ULT_FIELD_DURATION = 5.0
        self.char._perform_burst(None)
        self.assertEqual(calls["n"], 1)  # loop exited right after death

    def test_not_in_combat_stops_burst(self):
        self.char._combat_active = False
        with self.assertRaises(NotInCombatException):
            self.char._perform_burst(None)

    def test_burst_runs_heavy_combo(self):
        """第二套手法: 点按普攻(click) + 长按重击(mouse_down/up) + 往前走(w)重置, 结束后释放 w。"""
        self.char._skill_available = False
        self.char.ULT_FIELD_DURATION = 0.5
        self.char._perform_burst(None)
        self.char.task.click.assert_called()  # normal-attack taps
        self.char.task.mouse_down.assert_called()  # heavy long-press
        self.char.task.mouse_up.assert_called()
        self.char.task.send_key_down.assert_any_call("w")  # walk-forward reset
        self.char.task.send_key_up.assert_any_call("w")

    def test_burst_combo_without_direction_key(self):
        """无方向键时仍打重击连招, 但跳过走位重置, 不按任何方向键。"""
        self.char._skill_available = False
        self.char.BURST_DIRECTION_KEY = None
        self.char.DEFAULT_DIRECTION_KEY = None
        self.char.ULT_FIELD_DURATION = 0.5
        self.char._perform_burst(None)
        self.char.task.mouse_down.assert_called()  # heavy still runs
        pressed = [c.args[0] for c in self.char.task.send_key_down.call_args_list]
        self.assertNotIn("w", pressed)

    def test_heavy_combo_sequence_tap_tap_heavy_walk(self):
        """第二套手法顺序: 点按普攻两下 → 长按重击 → 往前走重置。"""
        order = []
        self.char.normal_attack = lambda: order.append("tap")
        self.char.heavy_attack = lambda duration=0.6: order.append("heavy")
        self.char._walk_forward_reset = lambda: order.append("walk")
        self.char._heavy_combo()
        self.assertEqual(order, ["tap", "tap", "heavy", "walk"])

    def test_heavy_combo_stops_before_heavy_on_switch(self):
        """点按过程中切人, 不再执行长按重击与走位。"""
        order = []

        def tap_and_switch():
            order.append("tap")
            self.char.is_current_char = False

        self.char.normal_attack = tap_and_switch
        self.char.heavy_attack = lambda duration=0.6: order.append("heavy")
        self.char._walk_forward_reset = lambda: order.append("walk")
        self.char._heavy_combo()
        self.assertNotIn("heavy", order)
        self.assertNotIn("walk", order)

    def test_burst_does_not_call_click_skill_directly(self):
        self.char._skill_available = False
        self.char.SECOND_SKILL_MODE = "disabled"
        self.char.ULT_FIELD_DURATION = 0.05
        self.char._perform_burst(None)
        self.assertEqual(self.char.skill_calls, 0)

    def test_right_click_burst_no_direction_key(self):
        self.char._right_click_burst(0.3)
        self.char.task.send_key_down.assert_not_called()
        self.char.task.send_key_up.assert_not_called()

    def test_right_click_burst_stops_on_char_switch(self):
        """_right_click_burst 内部检查 is_current_char。"""
        self.char.ULT_FIELD_DURATION = 0.05
        self.char.is_current_char = False
        self.char._right_click_burst(0.3)
        self.char.task.click.assert_not_called()


class TestBaicangSecondSkill(unittest.TestCase):
    def setUp(self):
        self.char = TestableBaicang()
        self.char._mock_burst = False
        self.char._ultimate_available = True
        self.char._skill_available = True
        self.char.is_current_char = True
        self.char.is_dead = False
        self.char.SECOND_SKILL_MODE = "execute"
        self.char.SKILL_CHECK_INTERVAL = 0.1

    def test_skill_fires_when_ready_streak_reached(self):
        """E 就绪并连续确认后释放; 随后冷却(序列转 False)不再放。"""
        self.char._skill_available_sequence = [
            True, True, False, False, False, False, False, False, False, False
        ]
        self.char._perform_burst(None)
        self.assertEqual(self.char.skill_calls, 1)

    def test_skill_can_fire_again_after_cooldown(self):
        """E 放完进入冷却, 冷却结束后再次就绪可再放一次。"""
        self.char._skill_available_sequence = [
            True, True, False, False, False, True, True, False, False, False
        ]
        self.char._perform_burst(None)
        self.assertEqual(self.char.skill_calls, 2)

    def test_observation_mode_no_click(self):
        self.char.SECOND_SKILL_MODE = "observe"
        self.char._skill_available_sequence = [False, True, True, True, True, True, True]
        self.char._perform_burst(None)
        self.assertEqual(self.char.skill_calls, 0)

    def test_disabled_mode_no_tracking(self):
        self.char.SECOND_SKILL_MODE = "disabled"
        self.char._skill_available_sequence = [True, True, True, True, True, True, True, True]
        self.char._perform_burst(None)
        self.assertEqual(self.char.skill_calls, 0)

    def test_skill_tracked_without_pre_q_skill(self):
        """Q-first 设计: 爆发开始时 E 直接就绪也能释放, 不依赖前置 E。"""
        self.char._skill_available_sequence = [
            True, True, False, False, False, False, False, False
        ]
        self.char._perform_burst(None)
        self.assertEqual(self.char.skill_calls, 1)

    def test_single_frame_glitch_no_trigger(self):
        self.char._skill_available_sequence = [True, False, False, False, False, False, False]
        self.char._perform_burst(None)
        self.assertEqual(self.char.skill_calls, 0)

    def test_streak_break_prevents_premature_fire(self):
        """单次就绪后被冷却打断, 不会提前放; 重新连续就绪才放。"""
        self.char._skill_available_sequence = [
            True, False, False, True, True, False, False, False, False
        ]
        self.char._perform_burst(None)
        self.assertEqual(self.char.skill_calls, 1)

    def test_skill_fires_repeatedly_when_continuously_ready(self):
        """E 持续就绪(无冷却)时按节流派放多次。"""
        self.char._skill_available_sequence = [
            True, True, True, True, True, True, False, False, False, False
        ]
        self.char._perform_burst(None)
        self.assertEqual(self.char.skill_calls, 3)


class TestBaicangFallbackDodge(unittest.TestCase):
    def setUp(self):
        self.char = TestableBaicang()
        self.char.is_current_char = True
        self.char.is_dead = False

    def test_fallback_returns_true_when_active(self):
        result = self.char._execute_fallback_dodge()
        self.assertTrue(result)

    def test_fallback_uses_checkpointed_right_click(self):
        self.char._execute_fallback_dodge()
        self.assertGreater(self.char.task.click.call_count, 0)

    def test_checkpointed_dodge_yields_to_sound_checks(self):
        sleep_calls = []
        original_sleep = self.char.sleep

        def recording_sleep(duration, sleep_check=True):
            sleep_calls.append((duration, sleep_check))
            original_sleep(duration, sleep_check)

        self.char.sleep = recording_sleep

        self.char._checkpointed_dodge(0.4)

        self.assertGreaterEqual(len(sleep_calls), 2)
        self.assertTrue(all(sleep_check for _, sleep_check in sleep_calls))

    def test_fallback_returns_false_when_dead(self):
        self.char.is_dead = True
        result = self.char._execute_fallback_dodge()
        self.assertFalse(result)
        self.assertEqual(self.char.fallback_calls, 0)

    def test_fallback_returns_false_when_not_current(self):
        self.char.is_current_char = False
        result = self.char._execute_fallback_dodge()
        self.assertFalse(result)
        self.assertEqual(self.char.fallback_calls, 0)


class TestBaicangOnCombatEnd(unittest.TestCase):
    def test_on_combat_end_does_not_crash(self):
        """GPT5.6 MAJOR 6: on_combat_end 不再调用 switch_other_char。"""
        char = TestableBaicang()
        char.on_combat_end([])
        self.assertEqual(char.switch_calls, 0)


class TestBaicangNow(unittest.TestCase):
    def test_now_returns_time(self):
        char = Baicang.__new__(Baicang)
        with patch("src.char.Baicang.time.monotonic", return_value=42.5):
            self.assertEqual(char._now(), 42.5)

    def test_now_is_patchable(self):
        char = TestableBaicang()
        char._fake_time = 99.0
        self.assertEqual(char._now(), 99.0)


if __name__ == "__main__":
    unittest.main()
