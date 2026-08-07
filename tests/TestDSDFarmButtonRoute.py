import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

from ok import TaskDisabledException

from src.tasks.BaseNTETask import BaseNTETask
from src.tasks.DSDFarmTask import DSDFarmTask
from src.tasks.NTEOneTimeTask import NTEOneTimeTask


class TestButtonFarmRoute(unittest.TestCase):
    def make_task(self, reached_combat):
        task = DSDFarmTask.__new__(DSDFarmTask)
        task.BUTTON_FARM_RUN_SLOT = 3
        task.BUTTON_FARM_RUN_TIMEOUT = 8.0
        task.BUTTON_FARM_BONFIRE_BOX = (0.10, 0.30, 0.60, 0.95)
        task._switch_to_slot = MagicMock()
        task.wait_until = MagicMock(return_value=reached_combat)
        task.deside_combat_action = MagicMock()
        task.log_warning = MagicMock()
        task.log_info = MagicMock()
        task.log_error = MagicMock()
        task.sleep = MagicMock()
        task.middle_click = MagicMock()
        task.send_key_down = MagicMock()
        task.send_key = MagicMock()
        task.send_key_up = MagicMock()
        task.box_of_screen = MagicMock(return_value=object())
        task.teleport_to_bonfire = MagicMock(return_value=True)
        task.ensure_teleport = MagicMock(return_value=True)
        task.dodge_only_mode = False
        task._abort = False
        return task

    def test_button_route_arcs_left_without_releasing_w(self):
        """location_4 must hold W continuously, add A for the arc, never release W mid-turn.

        Releasing W before pressing A would cause the character to strafe
        sideways instead of arcing forward-left through the doorway.
        """
        task = self.make_task(reached_combat=True)

        task.location_4()

        task._switch_to_slot.assert_called_once_with(3)
        task.middle_click.assert_called_once()
        task.send_key_down.assert_any_call("w")
        task.send_key_down.assert_any_call("a")
        task.send_key_up.assert_any_call("a")
        task.deside_combat_action.assert_called_once()
        task.log_warning.assert_not_called()
        task.box_of_screen.assert_called_once_with(0.10, 0.30, 0.60, 0.95)
        self.assertFalse(task.dodge_only_mode)

        # Verify call order: w down -> ... -> a down -> a up (NO w up between them)
        calls = task.send_key_down.call_args_list
        ups = task.send_key_up.call_args_list
        w_down_idx = next(i for i, c in enumerate(calls) if c == call("w"))
        a_down_idx = next(i for i, c in enumerate(calls) if c == call("a"))
        a_up_idx = next(i for i, c in enumerate(ups) if c == call("a"))
        # W must be pressed BEFORE A
        self.assertLess(w_down_idx, a_down_idx, "W must be pressed before A for the arc turn")
        # W must NOT be released between pressing W and releasing A
        w_up_calls = [i for i, c in enumerate(ups) if c == call("w")]
        for wui in w_up_calls:
            self.assertFalse(
                w_down_idx < wui < a_up_idx,
                "W must NOT be released before A is released (continuous forward motion)"
            )

    def test_button_route_resets_after_a_missed_combat(self):
        task = self.make_task(reached_combat=False)

        task.location_4()

        task.deside_combat_action.assert_not_called()
        task.log_warning.assert_called_once()
        task.ensure_teleport.assert_called_once()
        self.assertFalse(task.dodge_only_mode)

    def test_button_route_sets_dodge_only_during_run_and_combat(self):
        """dodge_only_mode must be True during run AND during combat, False after."""
        task = self.make_task(reached_combat=True)

        captured = {}

        def capture_during_combat():
            captured["during_combat"] = task.dodge_only_mode

        task.deside_combat_action = capture_during_combat

        original_wait = task.wait_until

        def capture_during_wait(*args, **kwargs):
            captured["during_walk"] = task.dodge_only_mode
            return original_wait(*args, **kwargs)

        task.wait_until = capture_during_wait

        task.location_4()

        self.assertTrue(captured["during_walk"])
        self.assertTrue(captured["during_combat"])
        self.assertFalse(task.dodge_only_mode)

    def test_button_route_resets_dodge_only_after_missed_combat(self):
        """dodge_only_mode must still be reset even when combat is missed."""
        task = self.make_task(reached_combat=False)

        captured = {}

        def capture_during_missed():
            captured["during_missed"] = task.dodge_only_mode

        original_warning = task.log_warning

        def capture_warning(*args, **kwargs):
            captured["during_missed"] = task.dodge_only_mode
            return original_warning(*args, **kwargs)

        task.log_warning = capture_warning

        task.location_4()

        # During the missed-combat log, dodge_only_mode is still True
        self.assertTrue(captured["during_missed"])
        # But after location_4 returns, it is False
        self.assertFalse(task.dodge_only_mode)

    def test_button_route_uses_strict_teleport_for_reset(self):
        """Reset teleport must use fail-fast params and pass zoom='mid'."""
        task = self.make_task(reached_combat=True)

        task.location_4()

        task.ensure_teleport.assert_called_once()
        args, kwargs = task.ensure_teleport.call_args
        self.assertFalse(kwargs["fallback_on_spot"])
        self.assertEqual(kwargs["max_retries"], 3)
        self.assertFalse(kwargs["recover_position"])
        # The lambda should pass zoom='mid' to teleport_to_bonfire
        args[0]()
        task.teleport_to_bonfire.assert_called_once_with(
            task.box_of_screen.return_value, threshold=0.6, zoom="mid"
        )

    def test_button_route_logs_error_when_reset_teleport_fails(self):
        task = self.make_task(reached_combat=True)
        task.ensure_teleport = MagicMock(return_value=False)
        task._abort = False

        task.location_4()

        task.log_error.assert_called_once()
        self.assertTrue(task._abort)

    def test_button_route_does_not_abort_on_successful_teleport(self):
        """Successful reset teleport must not set _abort."""
        task = self.make_task(reached_combat=True)
        task._abort = False

        task.location_4()

        self.assertFalse(task._abort)

    def test_do_run_aborts_after_teleport_failure(self):
        """do_run must stop when location_4 sets _abort=True.

        Simulates a full round: find_interac succeeds, combat starts,
        deside_action() runs location_4() which fails teleport and sets
        _abort.  do_run must break instead of starting round 2.
        """
        task = DSDFarmTask.__new__(DSDFarmTask)
        task.locations = ["loc0", "loc1", "loc2", "loc3", "loc4"]
        task.config = {task.CONF_LOCATION: "loc4", task.CONF_USE_ULT: True}
        task.do_teleport_on_spot = False
        task._abort = False
        task.deside_map_zoom = MagicMock()
        task._teleport_to_configured_start = MagicMock(return_value=True)
        task.start_rounds = MagicMock()
        task.begin_round = MagicMock(return_value=True)
        task.add_success = MagicMock()
        task.add_failed = MagicMock()
        task.finish_rounds = MagicMock()
        task._keep_game_window_alive = MagicMock()
        task.wait_until = MagicMock(return_value=True)
        task.find_interac = MagicMock(return_value=True)
        task.log_info = MagicMock()
        task.log_error = MagicMock()
        task.sleep = MagicMock()
        task.next_frame = MagicMock()
        task.send_interac = MagicMock()
        task.operate_click = MagicMock()
        task.ensure_main = MagicMock()
        task.send_key = MagicMock()

        round_counter = {"value": 0}

        def fake_deside_action():
            round_counter["value"] += 1
            if round_counter["value"] == 1:
                task._abort = True

        task.deside_action = fake_deside_action
        task.do_run()

        self.assertEqual(round_counter["value"], 1)
        task.log_error.assert_called_once()
        task.add_failed.assert_called_once_with("route teleport failed")
        task.add_success.assert_not_called()
        task.finish_rounds.assert_called_once()

    def test_farm_dodges_once_without_forced_direction(self):
        task = self.make_task(reached_combat=True)

        task._dodge_without_direction()
        task._dodge_without_direction()

        self.assertEqual(task.send_key.call_args_list, [call("lshift"), call("lshift")])
        task.send_key_down.assert_not_called()
        task.send_key_up.assert_not_called()

    def test_stopped_farm_task_cannot_receive_sound_actions(self):
        task = DSDFarmTask.__new__(DSDFarmTask)
        task._in_combat = True
        task.in_animation = False

        task.running = True
        self.assertTrue(task.can_sound_trigger())

        task.running = False
        self.assertFalse(task.can_sound_trigger())

    def test_disable_releases_keys_via_interaction_not_send_key_up(self):
        """disable() must call interaction.send_key_up directly, not BaseTask.send_key_up.

        BaseTask.send_key_up calls executor.reset_scene() and check_enabled(),
        which are unsafe to invoke from the GUI thread (the thread that calls
        disable()) because they read and mutate executor-internal state.
        """
        task = DSDFarmTask.__new__(DSDFarmTask)
        task._stop_requested = False
        task.log_warning = MagicMock()
        # "executor" is a read-only property; patch it at class level.
        mock_executor = MagicMock()

        with (
            patch.object(DSDFarmTask, "executor", mock_executor),
            patch("src.tasks.DSDFarmTask.SoundCombatContext") as context_cls,
            patch.object(BaseNTETask, "disable") as base_disable,
        ):
            task.disable()

        self.assertTrue(task._stop_requested)
        context_cls.return_value.clear_task_if.assert_called_once_with(task)
        mock_executor.interaction.send_key_up.assert_has_calls(
            [call("w"), call("a"), call("s"), call("d"), call("lshift")]
        )
        base_disable.assert_called_once_with()

    def test_stop_signal_is_not_retried_as_a_route_failure(self):
        task = DSDFarmTask.__new__(DSDFarmTask)
        task.do_teleport_on_spot = False
        task.config = {task.CONF_USE_ULT: True}
        task.locations = ["loc0", "loc1", "loc2", "loc3", "loc4", "loc5"]
        task.deside_map_zoom = MagicMock()
        task._teleport_to_configured_start = MagicMock(return_value=True)
        task.start_rounds = MagicMock()
        task.begin_round = MagicMock(return_value=True)
        task._keep_game_window_alive = MagicMock()
        task.wait_until = MagicMock(side_effect=TaskDisabledException())
        task.find_interac = MagicMock()
        task.log_info = MagicMock()
        task.sleep = MagicMock()

        with self.assertRaises(TaskDisabledException):
            task.do_run()

        task.log_info.assert_not_called()
        task.sleep.assert_not_called()

    def test_button_farm_skips_initial_teleport(self):
        """Button farm must skip the initial teleport.

        The user should manually teleport to the target bonfire before
        starting.  Standing on the bonfire causes the character icon to
        cover it on the map, leading to wrong selection or repeated
        map-open/map-close retries.
        """
        task = DSDFarmTask.__new__(DSDFarmTask)
        task.locations = ["loc0", "loc1", "loc2", "loc3", "loc4", "loc5"]
        task.config = {task.CONF_LOCATION: "loc4"}
        task.log_info = MagicMock()
        task.log_error = MagicMock()
        task.box_of_screen = MagicMock()
        task.ensure_teleport = MagicMock()
        task.ensure_main = MagicMock()

        result = task._teleport_to_configured_start()

        self.assertTrue(result)
        task.log_info.assert_called_once()
        task.ensure_teleport.assert_not_called()
        task.box_of_screen.assert_not_called()
        task.ensure_main.assert_not_called()
        task.log_error.assert_not_called()

    def test_non_button_farm_locations_skip_start_teleport(self):
        """Non-button-farm locations must also return True (no start teleport)."""
        task = DSDFarmTask.__new__(DSDFarmTask)
        task.locations = ["loc0", "loc1", "loc2", "loc3", "loc4", "loc5"]
        task.config = {task.CONF_LOCATION: "loc0"}
        task.log_info = MagicMock()

        result = task._teleport_to_configured_start()

        self.assertTrue(result)

    def test_button_farm_skips_map_zoom_in_do_run(self):
        """Button farm must skip deside_map_zoom (default zoom is medium)."""
        task = DSDFarmTask.__new__(DSDFarmTask)
        task.locations = ["loc0", "loc1", "loc2", "loc3", "loc4", "loc5"]
        task.config = {task.CONF_LOCATION: "loc4", task.CONF_USE_ULT: True}
        task.do_teleport_on_spot = False
        task.deside_map_zoom = MagicMock()
        task._teleport_to_configured_start = MagicMock(return_value=True)
        task.start_rounds = MagicMock()
        task.begin_round = MagicMock(return_value=True)
        task._keep_game_window_alive = MagicMock()
        task.wait_until = MagicMock(side_effect=TaskDisabledException())
        task.find_interac = MagicMock()
        task.log_info = MagicMock()
        task.sleep = MagicMock()

        with self.assertRaises(TaskDisabledException):
            task.do_run()

        task.deside_map_zoom.assert_not_called()

    def test_teleport_to_bonfire_sets_zoom(self):
        """teleport_to_bonfire with zoom='mid' clicks the mid zoom button."""
        task = DSDFarmTask.__new__(DSDFarmTask)
        task.ensure_main = MagicMock()
        task.open_map = MagicMock()
        task.operate_click = MagicMock()
        task.sleep = MagicMock()
        task.find_feature = MagicMock(return_value=[])
        task.click_traval_button = MagicMock(return_value=True)
        task.log_info = MagicMock()
        task.default_box = MagicMock()
        # box=MagicMock() is passed so main_viewport is never accessed;
        # no need to mock the read-only property.

        task.teleport_to_bonfire(box=MagicMock(), threshold=0.6, zoom="mid")

        # The zoom click at (0.050, 0.527) should have been made
        self.assertIn(call(0.050, 0.527), task.operate_click.call_args_list)

    def test_teleport_to_bonfire_without_zoom_skips_zoom_click(self):
        """teleport_to_bonfire without zoom must not click any zoom button."""
        task = DSDFarmTask.__new__(DSDFarmTask)
        task.ensure_main = MagicMock()
        task.open_map = MagicMock()
        task.operate_click = MagicMock()
        task.sleep = MagicMock()
        task.find_feature = MagicMock(return_value=[])
        task.click_traval_button = MagicMock(return_value=True)
        task.log_info = MagicMock()
        task.default_box = MagicMock()

        task.teleport_to_bonfire(box=MagicMock(), threshold=0.6)

        task.operate_click.assert_not_called()

    def test_ensure_teleport_catches_fun_exceptions(self):
        """ensure_teleport should catch exceptions from fun() and retry."""
        task = DSDFarmTask.__new__(DSDFarmTask)
        task.team_dead = False
        task._keep_game_window_alive = MagicMock()
        task.ensure_main = MagicMock()
        task.sleep = MagicMock()
        task.send_key = MagicMock()
        task.log_warning = MagicMock()
        task.teleport_on_spot = MagicMock(return_value=False)

        call_count = 0

        def flaky_fun():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise RuntimeError("map open failed")
            return True

        result = task.ensure_teleport(flaky_fun, max_retries=3, recover_position=False)

        self.assertTrue(result)
        self.assertEqual(call_count, 2)

    def test_ensure_teleport_re_raises_task_disabled(self):
        """ensure_teleport must re-raise TaskDisabledException without retrying."""
        task = DSDFarmTask.__new__(DSDFarmTask)
        task.team_dead = False
        task._keep_game_window_alive = MagicMock()
        task.ensure_main = MagicMock()
        task.sleep = MagicMock()
        task.send_key = MagicMock()
        task.log_warning = MagicMock()
        task.teleport_on_spot = MagicMock()

        def failing_fun():
            raise TaskDisabledException()

        with self.assertRaises(TaskDisabledException):
            task.ensure_teleport(failing_fun, max_retries=3, recover_position=False)

    def test_task_exit_always_releases_sound_ownership(self):
        task = DSDFarmTask.__new__(DSDFarmTask)
        task.sleep_check_skip = SimpleNamespace(all=False)
        task.do_run = MagicMock()

        with (
            patch.object(NTEOneTimeTask, "run", side_effect=TaskDisabledException()),
            patch("src.tasks.DSDFarmTask.SoundCombatContext") as context_cls,
        ):
            task.run()

        self.assertFalse(task.sleep_check_skip.all)
        context_cls.return_value.clear_task_if.assert_called_once_with(task)


if __name__ == "__main__":
    unittest.main()
