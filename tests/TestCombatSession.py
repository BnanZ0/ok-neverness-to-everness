import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from src.char.BaseChar import BaseChar
from src.combat.BaseCombatTask import BaseCombatTask, CombatSession, VisibleTeamMatch
from src.tasks.DSDFarmTask import DSDFarmTask


class TestCombatSession(unittest.TestCase):
    def _task(self):
        task = BaseCombatTask.__new__(BaseCombatTask)
        task.combat_session = None
        task.current_char = object()
        task.start_char = object()
        task.switch_calls = 0

        def switch_to_start():
            task.switch_calls += 1
            task.current_char = task.start_char

        task.switch_to_combat_start_char = switch_to_start
        task.get_current_char = lambda raise_exception=False: task.current_char
        task.click = lambda: None
        return task

    def test_begin_combat_session_switches_once_and_records_start_char(self):
        task = self._task()

        session = task.begin_combat_session()
        duplicate = task.begin_combat_session()

        self.assertIs(session, duplicate)
        self.assertEqual(task.switch_calls, 1)
        self.assertIs(session.start_char, task.start_char)
        self.assertGreater(session.combat_start, 0)

    def test_existing_session_is_reused(self):
        task = self._task()
        previous = task.begin_combat_session()

        current = task.begin_combat_session()

        self.assertIs(current, previous)
        self.assertEqual(task.switch_calls, 1)

    def test_first_engage_is_recorded_once_for_the_active_session(self):
        task = self._task()
        task.begin_combat_session()
        first = object()
        later = object()

        task.record_first_engage(first)
        task.record_first_engage(later)

        self.assertTrue(task.is_first_engage(first))
        self.assertFalse(task.is_first_engage(later))

    def test_first_engage_can_only_be_consumed_once(self):
        task = self._task()
        task.begin_combat_session()
        first = object()
        later = object()
        task.record_first_engage(first)

        self.assertTrue(task.consume_first_engage(first))
        self.assertFalse(task.consume_first_engage(first))
        self.assertFalse(task.consume_first_engage(later))
        self.assertTrue(task.is_first_engage(first))

    def test_base_char_delegates_first_engage_to_task_session(self):
        task = self._task()
        task.begin_combat_session()
        char = BaseChar.__new__(BaseChar)
        char.task = task
        task.record_first_engage(char)

        self.assertTrue(char.is_first_engage())
        self.assertTrue(char.consume_first_engage())
        self.assertFalse(char.consume_first_engage())

    def test_base_char_perform_records_first_engage_before_actions(self):
        task = Mock()
        char = BaseChar(task, index=0)
        char.planner_handles_arc = True
        char.switch_next_char = Mock()

        char.perform()

        task.record_first_engage.assert_called_once_with(char)
        task.combat_planner.perform_current_char.assert_called_once_with(char)

    def test_dsd_switching_config_can_be_set_before_combat_starts(self):
        task = DSDFarmTask.__new__(DSDFarmTask)
        task.config = {task.CONF_DONT_SWITCH: True}
        task.combat_session = None
        task.current_char = object()
        task.switch_to_combat_start_char = lambda: None
        task.get_current_char = lambda raise_exception=False: task.current_char
        task.click = lambda: None

        task.combat_session.switch_enabled = not task.config.get(
            task.CONF_DONT_SWITCH, False
        )
        session = task.begin_combat_session()
        self.assertFalse(session.switch_enabled)
        task.config[task.CONF_DONT_SWITCH] = False
        self.assertFalse(task.begin_combat_session().switch_enabled)

    def test_ultimate_usage_is_a_combat_session_policy(self):
        task = self._task()

        task.combat_session.use_ultimate = False

        self.assertFalse(task.begin_combat_session().use_ultimate)

    def test_same_abyss_binding_reuses_chars_and_planner_during_wave_gap(self):
        task = BaseCombatTask.__new__(BaseCombatTask)

        def _make_test_char(idx):
            c = SimpleNamespace(index=idx, is_current_char=False, is_dead=False)

            def switch_in(has_intro=False):
                c.is_current_char = True

            c.switch_in = switch_in
            return c

        chars = [_make_test_char(index) for index in range(4)]
        binding = VisibleTeamMatch(
            preset_id="team_chiz",
            preset_name="小吱盈蓄队",
            char_ids=tuple(f"char_{index}" for index in range(4)),
            slots=tuple(
                {"char_id": f"char_{index}", "combo_id": ""} for index in range(4)
            ),
        )
        route = object()
        task.chars = chars
        task._team_binding = binding
        task._pending_team_binding = None
        task._team_binding_blocked = False
        task._team_binding_last_check = 0.0
        task._combat_session = CombatSession(
            combat_start=time.time(),
            start_char=chars[0],
            last_active_at=time.monotonic(),
        )
        task.should_hold_position_on_target_loss = Mock(return_value=True)
        task.load_hotkey = Mock()
        task.in_team = Mock(return_value=(True, 2, 4))
        task.log_info = Mock()
        task._match_visible_team_preset = Mock(return_value=binding)
        task._do_load_char = Mock(side_effect=AssertionError("wave gap rebuilt team"))
        task.combat_planner = SimpleNamespace(
            state=SimpleNamespace(locked_route=route),
            reset=Mock(),
        )
        manager = Mock()
        manager.get_fixed_team.return_value = {"selection_mode": "auto"}
        manager.get_armed_team_preset.return_value = None

        with unittest.mock.patch(
            "src.combat.BaseCombatTask.CustomCharManager", return_value=manager
        ):
            loaded = BaseCombatTask.load_chars(task)

        self.assertTrue(loaded)
        self.assertIs(task.chars[0], chars[0])
        self.assertIs(task.combat_planner.state.locked_route, route)
        task.combat_planner.reset.assert_not_called()
        self.assertTrue(chars[2].is_current_char)

    def test_abyss_session_gap_timeout_requires_a_new_session(self):
        task = BaseCombatTask.__new__(BaseCombatTask)
        task._combat_session = CombatSession(
            combat_start=time.time(),
            start_char=object(),
            last_active_at=time.monotonic() - BaseCombatTask.ABYSS_SESSION_GAP_TIMEOUT - 0.01,
        )
        task._team_binding_blocked = False
        task._pending_team_binding = None
        task.should_hold_position_on_target_loss = Mock(return_value=True)

        self.assertFalse(task.can_preserve_combat_session())


if __name__ == "__main__":
    unittest.main()
