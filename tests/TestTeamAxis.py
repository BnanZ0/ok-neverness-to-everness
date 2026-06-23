import unittest
from unittest.mock import Mock, patch

from src.tasks.trigger.AutoCombatTask import AutoCombatTask
from src.team_axis.axes.NanallyZeroJiuyuanHotoriAxis import NanallyZeroJiuyuanHotoriAxis
from src.team_axis.BaseTeamAxis import BaseTeamAxis
from src.team_axis.CustomTeamAxis import CustomTeamAxis, CustomTeamAxisDefinition
from src.team_axis.TeamAxisRegistry import (
    clear_registry_cache,
    create_matching_team_axis,
    get_axis_class,
)


class FakeChar:
    def __init__(self, builtin_key):
        self.builtin_key = builtin_key


class FakeTask:
    def __init__(self, keys):
        self.chars = [FakeChar(key) for key in keys]
        self.events = []

    def check_combat(self):
        self.events.append("check")

    def log_info(self, message):
        self.events.append(message)

    def log_debug(self, message):
        self.events.append(message)


class LifecycleAxis(BaseTeamAxis):
    team_signature = ("a", "b", "c", "d")

    def run_opening(self):
        self.task.events.append("opening")

    def run_cycle(self):
        self.task.events.append("cycle")


class RotationChar:
    ULT_ATTACK_DURATION = 6

    def __init__(self, builtin_key, ultimate_ready=True):
        self.builtin_key = builtin_key
        self.index = 0
        self._ultimate_ready = ultimate_ready

    def skill_available(self):
        return True

    def ultimate_available(self):
        return self._ultimate_ready

    def is_cycle_full(self):
        return True

    def click_arc(self):
        self.task.events.append(f"{self.builtin_key}:R")
        return True


class RotationTask:
    def __init__(self, zero_ultimate_ready=True):
        keys = ("char_nanally", "char_zero", "char_jiuyuan", "char_hotori")
        self.chars = [
            RotationChar(key, zero_ultimate_ready if key == "char_zero" else True) for key in keys
        ]
        for index, char in enumerate(self.chars):
            char.index = index
            char.task = self
        self.events = []

    def wait_until(self, condition, **_kwargs):
        return condition()

    def log_debug(self, message):
        self.events.append(f"debug:{message}")


class CommandChar:
    def __init__(self, builtin_key):
        self.builtin_key = builtin_key
        self.index = 0
        self.has_intro = False
        self.last_perform = 0

    def wait_switch_cd(self):
        self.task.events.append(f"{self.builtin_key}:switch_cd")

    def is_cycle_full(self):
        return True

    def wait_intro(self):
        self.task.events.append(f"{self.builtin_key}:intro")

    def click_skill(self, down_time=0.01):
        self.task.events.append(f"{self.builtin_key}:skill:{down_time}")
        return True

    def click_ultimate(self):
        self.task.events.append(f"{self.builtin_key}:ultimate")
        return True

    def click_arc(self):
        self.task.events.append(f"{self.builtin_key}:arc")
        return True

    def normal_attack(self):
        self.task.events.append(f"{self.builtin_key}:normal")

    def continues_normal_attack(self, duration):
        self.task.events.append(f"{self.builtin_key}:normal:{duration}")

    def sleep(self, duration):
        self.task.events.append(f"{self.builtin_key}:sleep:{duration}")

    def send_key(self, key, down_time=None):
        self.task.events.append(f"{self.builtin_key}:key:{key}:{down_time}")


class CommandTask:
    def __init__(self, keys=("a", "b", "c", "d")):
        self.chars = [CommandChar(key) for key in keys]
        for index, char in enumerate(self.chars):
            char.index = index
            char.task = self
        self.current = None
        self.events = []

    def get_current_char(self, raise_exception=False):
        return self.current

    def _switch_to_char(self, target, **_kwargs):
        self.current = target
        self.events.append(f"switch:{target.builtin_key}")

    def check_combat(self):
        self.events.append("check")

    def log_info(self, message):
        self.events.append(f"info:{message}")

    def log_debug(self, message):
        self.events.append(f"debug:{message}")


class RotationAxis(NanallyZeroJiuyuanHotoriAxis):
    def __init__(self, task):
        super().__init__(task)
        self._current = None

    def switch_to(self, builtin_key, wait_intro=True):
        self._current = self.get_char(builtin_key)
        self.task.events.append(f"switch:{builtin_key}:{wait_intro}")
        return self._current

    def current_char(self):
        return self._current

    def skill(self, **_kwargs):
        self.task.events.append(f"{self._current.builtin_key}:E")
        return True

    def ultimate(self, **_kwargs):
        self.task.events.append(f"{self._current.builtin_key}:Q")
        return True

    def normal_attack(self, duration, interval=0.1):
        self.task.events.append(f"{self._current.builtin_key}:A:{duration:.1f}")

    def sleep(self, duration):
        self.task.events.append(f"{self._current.builtin_key}:sleep:{duration:.1f}")

    def call_current(self, method_name, *_args, **_kwargs):
        self.task.events.append(f"{self._current.builtin_key}:{method_name}")
        return True

    def _wait_hotori_portrait_progress(self):
        self.task.events.append("wait:hotori_portrait")
        return True

    def _wait_nanally_effects_end(self):
        self.task.events.append("wait:nanally_eq_cooldown")
        return True


class TestTeamAxis(unittest.TestCase):
    def setUp(self):
        clear_registry_cache()

    def tearDown(self):
        clear_registry_cache()

    def test_ordered_team_match_is_exact(self):
        chars = [FakeChar(key) for key in ("a", "b", "c", "d")]
        self.assertTrue(LifecycleAxis.matches(chars))

        reordered = [FakeChar(key) for key in ("b", "a", "c", "d")]
        self.assertFalse(LifecycleAxis.matches(reordered))

    def test_opening_runs_once_then_cycles(self):
        task = FakeTask(("a", "b", "c", "d"))
        axis = LifecycleAxis(task)

        axis.perform_next()
        axis.perform_next()
        axis.perform_next()

        self.assertEqual(task.events.count("opening"), 1)
        self.assertEqual(task.events.count("cycle"), 2)
        self.assertEqual(axis.cycle_count, 2)

    def test_registry_finds_fixed_four_character_axis(self):
        task = FakeTask(("char_nanally", "char_zero", "char_jiuyuan", "char_hotori"))
        axis = create_matching_team_axis(task)
        self.assertIsInstance(axis, NanallyZeroJiuyuanHotoriAxis)

    def test_registry_selects_axis_by_stable_id(self):
        axis_id = NanallyZeroJiuyuanHotoriAxis.axis_id
        task = FakeTask(("char_nanally", "char_zero", "char_jiuyuan", "char_hotori"))

        self.assertIs(get_axis_class(axis_id), NanallyZeroJiuyuanHotoriAxis)
        self.assertIsInstance(
            create_matching_team_axis(task, axis_id), NanallyZeroJiuyuanHotoriAxis
        )
        self.assertIsNone(create_matching_team_axis(task, "missing-axis"))

    def test_registry_does_not_match_other_order(self):
        task = FakeTask(("char_hotori", "char_nanally", "char_zero", "char_jiuyuan"))
        self.assertIsNone(create_matching_team_axis(task))

    def test_custom_team_axis_syntax_uses_position_prefixes(self):
        is_valid, error = CustomTeamAxis.validate_axis_syntax(
            "p1_skill, if_(p2_ultimate, p3_l_click(0.2), p4_wait(0.1))"
        )
        self.assertTrue(is_valid)
        self.assertIsNone(error)

        is_valid, error = CustomTeamAxis.validate_axis_syntax("skill")
        self.assertFalse(is_valid)
        self.assertIn("unknown command", error or "")

    def test_custom_team_axis_command_examples_keep_nested_commas(self):
        command_examples = {
            command.name: command.example
            for command in CustomTeamAxis.get_command_definitions()
        }

        self.assertEqual(command_examples["p1_walk"], "p1_walk(w, 0.2)")
        self.assertEqual(command_examples["p2_skill"], "p2_skill, p2_skill(0.5)")

    def test_custom_team_axis_executes_position_commands(self):
        definition = CustomTeamAxisDefinition(
            axis_id="custom_team_axis:test",
            name="test",
            description="",
            content="p2_skill(0.5), if_(p3_ultimate, p4_l_click(2)), p1_wait(0.1)",
            team_signature=("a", "b", "c", "d"),
        )
        task = CommandTask()
        axis = CustomTeamAxis(task, definition)

        axis.run_opening()

        self.assertIn("switch:b", task.events)
        self.assertIn("b:skill:0.5", task.events)
        self.assertIn("switch:c", task.events)
        self.assertIn("c:ultimate", task.events)
        self.assertIn("switch:d", task.events)
        self.assertIn("d:normal:2", task.events)
        self.assertIn("switch:a", task.events)
        self.assertIn("a:sleep:0.1", task.events)

    def test_registry_loads_custom_team_axis_from_manager(self):
        axis_id = "custom_team_axis:registry_test"
        manager = Mock()
        manager.get_custom_team_axes.return_value = {
            axis_id: {
                "axis_id": axis_id,
                "name": "registry test",
                "description": "",
                "content": "p1_skill",
                "team_signature": ["a", "b", "c", "d"],
                "enabled": True,
            }
        }
        task = CommandTask()

        with patch("src.team_axis.TeamAxisRegistry.CustomCharManager", return_value=manager):
            axis_definition = get_axis_class(axis_id)
            self.assertIsInstance(axis_definition, CustomTeamAxisDefinition)
            self.assertIsInstance(create_matching_team_axis(task, axis_id), CustomTeamAxis)

    def test_registry_skips_malformed_custom_team_axis_config(self):
        good_axis_id = "custom_team_axis:good_registry_test"
        manager = Mock()
        manager.get_custom_team_axes.return_value = {
            "custom_team_axis:bad_registry_test": {
                "axis_id": "custom_team_axis:bad_registry_test",
                "team_signature": None,
            },
            good_axis_id: {
                "axis_id": good_axis_id,
                "name": "good registry test",
                "description": "",
                "content": "p1_skill",
                "team_signature": ["a", "b", "c", "d"],
                "enabled": True,
            },
        }

        with (
            patch("src.team_axis.TeamAxisRegistry.CustomCharManager", return_value=manager),
            patch("src.team_axis.TeamAxisRegistry.logger") as logger_mock,
        ):
            axis_definition = get_axis_class(good_axis_id)
            self.assertIsInstance(axis_definition, CustomTeamAxisDefinition)
            logger_mock.error.assert_called_once()

    def test_auto_combat_only_creates_enabled_fixed_team_axis(self):
        task = object.__new__(AutoCombatTask)
        task.chars = [
            FakeChar(key) for key in ("char_nanally", "char_zero", "char_jiuyuan", "char_hotori")
        ]
        manager = Mock()
        manager.get_fixed_team.return_value = {"enabled": True}
        manager.get_fixed_team_axis.return_value = {
            "enabled": True,
            "axis_id": NanallyZeroJiuyuanHotoriAxis.axis_id,
        }

        with patch("src.tasks.trigger.AutoCombatTask.CustomCharManager", return_value=manager):
            axis = task.create_fixed_team_axis()
            self.assertIsInstance(axis, NanallyZeroJiuyuanHotoriAxis)

            manager.get_fixed_team.return_value = {"enabled": False}
            self.assertIsNone(task.create_fixed_team_axis())

    @patch(
        "src.team_axis.axes.NanallyZeroJiuyuanHotoriAxis.time.monotonic",
        side_effect=(100.0, 100.0),
    )
    def test_fixed_axis_opening_matches_requested_rotation(self, _monotonic):
        task = RotationTask(zero_ultimate_ready=True)
        axis = RotationAxis(task)

        axis.run_opening()

        self.assertEqual(
            task.events,
            [
                "switch:char_hotori:True",
                "char_hotori:E",
                "char_hotori:start_records",
                "switch:char_jiuyuan:True",
                "char_jiuyuan:E",
                "switch:char_zero:True",
                "char_zero:Q",
                "char_zero:E",
                "switch:char_nanally:False",
                "wait:hotori_portrait",
                "char_nanally:E",
                "char_nanally:sleep:0.7",
                "char_nanally:Q",
                "char_nanally:R",
                "wait:nanally_eq_cooldown",
                "switch:char_jiuyuan:True",
                "char_jiuyuan:fire_bullets",
                "switch:char_hotori:True",
                "char_hotori:Q",
                "char_hotori:clear_records",
                "char_hotori:A:13.0",
                "switch:char_jiuyuan:True",
                "char_jiuyuan:Q",
                "char_jiuyuan:E",
                "switch:char_zero:True",
                "switch:char_nanally:False",
                "switch:char_zero:False",
                "char_zero:Q",
                "char_zero:E",
                "switch:char_nanally:False",
                "char_nanally:sleep:1.0",
                "char_nanally:E",
                "char_nanally:sleep:0.7",
                "char_nanally:Q",
                "char_nanally:R",
                "wait:nanally_eq_cooldown",
                "switch:char_jiuyuan:True",
                "char_jiuyuan:fire_bullets",
                "switch:char_hotori:True",
            ],
        )

    @patch(
        "src.team_axis.axes.NanallyZeroJiuyuanHotoriAxis.time.monotonic",
        side_effect=(100.0, 100.0),
    )
    def test_fixed_axis_cycle_restarts_with_hotori_skill(self, _monotonic):
        task = RotationTask(zero_ultimate_ready=True)
        axis = RotationAxis(task)

        axis.run_cycle()

        self.assertEqual(
            task.events[:3],
            [
                "switch:char_hotori:True",
                "char_hotori:E",
                "char_hotori:start_records",
            ],
        )
        self.assertEqual(
            task.events[-3:],
            [
                "switch:char_jiuyuan:True",
                "char_jiuyuan:fire_bullets",
                "switch:char_hotori:True",
            ],
        )
        self.assertEqual(task.events.count("char_hotori:E"), 1)

    def test_zero_second_entry_skips_unavailable_ultimate(self):
        task = RotationTask(zero_ultimate_ready=False)
        axis = RotationAxis(task)

        axis._zero_nanally_bridge()

        self.assertNotIn("char_zero:Q", task.events)
        self.assertIn("char_zero:E", task.events)

    def test_zero_first_entry_skips_unavailable_ultimate(self):
        task = RotationTask(zero_ultimate_ready=False)
        axis = RotationAxis(task)

        axis._record_jiuyuan_and_zero()

        self.assertNotIn("char_zero:Q", task.events)
        self.assertIn("char_zero:E", task.events)

    def test_nanally_waits_for_three_consecutive_dual_cooldown_samples(self):
        states = iter(
            [
                (False, False),
                (True, True),
                (True, False),
                (True, True),
                (True, True),
                (True, True),
            ]
        )
        normal_attacks = []
        nanally = Mock()
        nanally.state = (False, False)
        nanally.has_cd.side_effect = lambda name: nanally.state[name == "ultimate"]
        nanally.normal_attack.side_effect = lambda: normal_attacks.append("A")

        task = Mock()

        def wait_until(condition, post_action=None, **_kwargs):
            for state in states:
                nanally.state = state
                if condition():
                    return True
                post_action()
            return False

        task.wait_until.side_effect = wait_until
        axis = object.__new__(NanallyZeroJiuyuanHotoriAxis)
        axis.task = task
        axis.current_char = lambda: nanally

        axis._wait_nanally_effects_end()

        self.assertEqual(normal_attacks, ["A"] * 5)

    def test_nanally_skips_q_when_skill_ends_first(self):
        nanally = Mock()
        nanally.ultimate_available.return_value = False
        axis = object.__new__(NanallyZeroJiuyuanHotoriAxis)
        axis.current_char = lambda: nanally
        axis.skill = Mock(return_value=True)
        axis.ultimate = Mock(return_value=True)
        axis.sleep = Mock()
        axis._wait_nanally_q_during_skill_window = Mock(return_value=False)
        axis._wait_nanally_effects_end = Mock()

        axis._run_nanally_eqr()

        axis.skill.assert_called_once_with()
        axis.ultimate.assert_not_called()
        nanally.click_arc.assert_not_called()
        axis._wait_nanally_effects_end.assert_not_called()

    def test_nanally_casts_qr_when_q_is_ready_before_skill_ends(self):
        nanally = Mock()
        nanally.ultimate_available.return_value = False
        axis = object.__new__(NanallyZeroJiuyuanHotoriAxis)
        axis.current_char = lambda: nanally
        axis.skill = Mock(return_value=True)
        axis.ultimate = Mock(return_value=True)
        axis.sleep = Mock()
        axis._wait_nanally_q_during_skill_window = Mock(return_value=True)
        axis._wait_nanally_effects_end = Mock()

        axis._run_nanally_eqr()

        axis.ultimate.assert_called_once_with()
        nanally.click_arc.assert_called_once_with()
        axis._wait_nanally_effects_end.assert_called_once_with()

    def test_nanally_detects_q_lighting_after_skill_without_using_skill_cd(self):
        nanally = Mock()
        nanally.ultimate_available.side_effect = (False, True, True)
        normal_attacks = []
        nanally.normal_attack.side_effect = lambda: normal_attacks.append("A")
        task = Mock()

        def wait_until(condition, post_action=None, **_kwargs):
            for _ in range(3):
                if condition():
                    return True
                post_action()
            return False

        task.wait_until.side_effect = wait_until
        axis = object.__new__(NanallyZeroJiuyuanHotoriAxis)
        axis.task = task
        axis.current_char = lambda: nanally

        self.assertTrue(axis._wait_nanally_q_during_skill_window())
        nanally.has_cd.assert_not_called()
        self.assertEqual(normal_attacks, ["A", "A"])

    def test_first_nanally_waits_for_consecutive_hotori_progress_rise(self):
        task = Mock()

        def wait_until(condition, **_kwargs):
            for _ in range(4):
                if condition():
                    return True
            return False

        task.wait_until.side_effect = wait_until
        axis = object.__new__(NanallyZeroJiuyuanHotoriAxis)
        axis.task = task
        axis._hotori_portrait_progress_score = Mock(side_effect=(0.100, 0.101, 0.104, 0.108))

        self.assertTrue(axis._wait_hotori_portrait_progress())

    def test_jiuyuan_flower_clear_uses_six_flower_hold_duration(self):
        jiuyuan = Mock()
        axis = object.__new__(NanallyZeroJiuyuanHotoriAxis)
        axis.current_char = lambda: jiuyuan

        axis._clear_jiuyuan_flowers()

        jiuyuan.fire_bullets.assert_called_once_with(duration=1.8)


if __name__ == "__main__":
    unittest.main()
