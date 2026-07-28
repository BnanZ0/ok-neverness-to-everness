import unittest
from unittest.mock import patch

from ok import WaitFailedException

from src.flow import Flow, FlowReplan
from src.tasks.BaseNTETask import RoundState
from src.tasks.FishingTask import FishingSession, FishingTask, RestockPhase


class TestFishingFlow(unittest.TestCase):
    @staticmethod
    def _set_round_state(task, total=0, index=1, success_count=0, failed_count=0):
        task._round_state = RoundState(total, index, success_count, failed_count)
        task.config = {task.CONF_ROUNDS: total}

    def _task_with_flow(self, state):
        task = object.__new__(FishingTask)
        task.flow = Flow()
        task.has_success_overlay = lambda: state["node"] is FishingTask.Node.RESULT
        task.is_playing_fish = lambda: state["node"] is FishingTask.Node.CONTROL
        task.is_waiting_bite = lambda: state["node"] is FishingTask.Node.WAITING_BITE
        task.is_ready_to_cast = lambda: state["node"] is FishingTask.Node.READY
        task.is_in_team = lambda: state["node"] is FishingTask.Node.TEAM
        task.is_sell_menu = lambda: state["node"] is FishingTask.Node.SELL_MENU
        task.is_fish_hold = lambda: state["node"] is FishingTask.Node.FISH_HOLD
        task.is_bait_shop = lambda: state["node"] is FishingTask.Node.BAIT_SHOP
        task._enter_fishing_from_interaction = lambda: state.__setitem__(
            "node", FishingTask.Node.READY
        )
        task._press_escape_for_recovery = lambda: state.__setitem__(
            "node", FishingTask.Node.TEAM
        )
        task._on_ready = lambda: state.__setitem__(
            "node", FishingTask.Node.WAITING_BITE
        )
        task._on_waiting_bite = lambda: state.__setitem__("node", FishingTask.Node.CONTROL)
        task._on_control = lambda: state.__setitem__("node", FishingTask.Node.RESULT)
        task._on_result = lambda: state.__setitem__(
            "node", FishingTask.Node.READY
        )
        task._on_sell_menu = lambda: state.__setitem__("node", FishingTask.Node.FISH_HOLD)
        task._on_fish_hold = lambda: state.__setitem__("node", FishingTask.Node.BAIT_SHOP)
        task._on_bait_shop = lambda: state.__setitem__("node", FishingTask.Node.READY)
        FishingTask._configure_flow(task)
        return task

    def test_monthly_card_can_resume_on_the_same_fishing_node(self):
        state = {"node": FishingTask.Node.READY, "monthly_card": True}
        task = self._task_with_flow(state)

        def dismiss_monthly_card():
            state["monthly_card"] = False
            return True

        task.flow.interrupt(lambda: state["monthly_card"], dismiss_monthly_card, priority=1000)

        self.assertIs(task.flow.checkpoint(), FishingTask.Node.READY)

    def test_monthly_card_can_resume_on_a_later_fishing_node(self):
        state = {"node": FishingTask.Node.READY, "monthly_card": True}
        task = self._task_with_flow(state)

        def dismiss_monthly_card():
            state["monthly_card"] = False
            state["node"] = FishingTask.Node.WAITING_BITE
            return True

        task.flow.interrupt(lambda: state["monthly_card"], dismiss_monthly_card, priority=1000)

        self.assertIs(task.flow.checkpoint(), FishingTask.Node.WAITING_BITE)

    def test_failed_monthly_card_close_falls_back_to_fishing_recovery(self):
        state = {"node": FishingTask.Node.READY, "monthly_card": False}
        task = self._task_with_flow(state)
        task._on_ready = lambda: (
            state.__setitem__("monthly_card", True),
            task.flow.safe_point(),
        )
        task.flow.interrupt(lambda: state["monthly_card"], lambda: False, priority=1000)

        def dismiss_to_team():
            state["monthly_card"] = False
            state["node"] = FishingTask.Node.TEAM

        task.flow.fallback(dismiss_to_team, grace=0)

        self.assertTrue(
            task.flow.loop(lambda: state["node"] is FishingTask.Node.READY, poll_interval=0)
        )
        self.assertIs(state["node"], FishingTask.Node.READY)

    def test_fishing_round_is_driven_by_reactive_node_handlers(self):
        state = {"node": FishingTask.Node.READY, "rounds": 0}
        task = self._task_with_flow(state)
        task.flow = Flow()

        def finish_round():
            state["rounds"] += 1
            state["node"] = FishingTask.Node.READY

        task._on_result = finish_round
        FishingTask._configure_flow(task)

        self.assertTrue(task.flow.loop(lambda: state["rounds"] == 1, poll_interval=0))
        self.assertIs(state["node"], FishingTask.Node.READY)

    def test_restock_screens_use_the_same_reactive_flow(self):
        state = {"node": FishingTask.Node.SELL_MENU, "completed": False}
        task = self._task_with_flow(state)
        task.flow = Flow()

        def complete_restock():
            state["node"] = FishingTask.Node.READY
            state["completed"] = True

        task._on_bait_shop = complete_restock
        FishingTask._configure_flow(task)

        self.assertTrue(task.flow.loop(lambda: state["completed"], poll_interval=0))
        self.assertIs(state["node"], FishingTask.Node.READY)

    def test_restock_return_context_does_not_reopen_the_fish_hold(self):
        task = object.__new__(FishingTask)
        session = FishingSession(restock_phase=RestockPhase.OPEN_BAIT_MENU)
        task._fishing_session = session
        task._return_to_fishing_ready = lambda: "returning"

        self.assertEqual(task._on_sell_menu(), "returning")

    def test_ready_opens_bait_interface_after_sale_returns_to_ready(self):
        task = object.__new__(FishingTask)
        session = FishingSession(restock_phase=RestockPhase.OPEN_BAIT_MENU)
        task._fishing_session = session
        self._set_round_state(task, total=1, index=0)
        task.info_get = lambda _key: None
        task.info_set = lambda _key, _value: None
        task.log_info = lambda _message: None
        task._set_stage = lambda _stage: None
        calls = []
        task._open_bait_interface = lambda: calls.append("opening bait")

        task._on_ready()

        self.assertEqual(calls, ["opening bait"])

    def test_control_interruption_tracks_the_round_without_changing_pending_result_semantics(self):
        task = object.__new__(FishingTask)
        session = FishingSession()
        task._fishing_session = session
        self._set_round_state(task, index=3)
        task._set_stage = lambda _stage: None
        task.log_info = lambda _message: None

        def interrupted_control():
            raise FlowReplan()

        task.control_until_finish = interrupted_control

        with self.assertRaises(FlowReplan):
            task._on_control()

        self.assertIsNone(session.awaiting_result_round)
        self.assertEqual(session.interrupted_control_round, 3)
        self.assertEqual(session.cast_attempts, 0)

    def test_control_failure_does_not_create_a_pending_result(self):
        task = object.__new__(FishingTask)
        session = FishingSession(cast_attempts=2)
        task._fishing_session = session
        self._set_round_state(task, index=3)
        task._set_stage = lambda _stage: None
        task.log_info = lambda _message: None
        task.control_until_finish = lambda: (_ for _ in ()).throw(WaitFailedException())

        with self.assertRaises(WaitFailedException):
            task._on_control()

        self.assertIsNone(session.awaiting_result_round)
        self.assertIsNone(session.interrupted_control_round)
        self.assertEqual(session.cast_attempts, 2)

    def test_completed_control_resets_recovery_attempts(self):
        task = object.__new__(FishingTask)
        session = FishingSession(recovery_attempts=2)
        task._fishing_session = session
        self._set_round_state(task, index=3)
        task._set_stage = lambda _stage: None
        task.log_info = lambda _message: None
        task.control_until_finish = lambda: None

        task._on_control()

        self.assertEqual(session.awaiting_result_round, 3)
        self.assertEqual(session.recovery_attempts, 0)

    def test_waiting_bite_keeps_the_previous_result_pending(self):
        task = object.__new__(FishingTask)
        session = FishingSession(awaiting_result_round=5)
        task._fishing_session = session
        self._set_round_state(task, index=5)
        task._set_stage = lambda _stage: None
        sent_keys = []
        task.send_key = lambda key, **_kwargs: sent_keys.append(key)

        task._on_waiting_bite()

        self.assertEqual(task._round_state.failed_count, 0)
        self.assertEqual(session.awaiting_result_round, 5)
        self.assertEqual(sent_keys, ["f"])

    def test_next_control_records_a_missing_previous_result(self):
        task = object.__new__(FishingTask)
        session = FishingSession(awaiting_result_round=5)
        task._fishing_session = session
        self._set_round_state(task, index=5)
        task._set_stage = lambda _stage: None
        task.info_set = lambda _key, _value: None
        task.log_error = lambda _message: None
        task.log_info = lambda _message: None
        task.log_warning = lambda _message: None
        task.control_until_finish = lambda: (_ for _ in ()).throw(WaitFailedException())

        with self.assertRaises(WaitFailedException):
            task._on_control()

        self.assertEqual(task._round_state.failed_count, 1)
        self.assertEqual(task.current_round, 5)
        self.assertIsNone(session.awaiting_result_round)

    def test_restock_retries_are_independent_from_round_retries(self):
        task = object.__new__(FishingTask)
        session = FishingSession(restock_phase=RestockPhase.OPEN_SELL_MENU)
        task._fishing_session = session
        dismissals = []
        round_recoveries = []
        task._press_escape_for_recovery = lambda: dismissals.append(True)
        task._recover_failed_round = lambda current: round_recoveries.append(current)
        task.log_warning = lambda _message: None

        for _ in range(task.RESTOCK_RETRY_LIMIT):
            self.assertTrue(task._handle_flow_error(WaitFailedException()))

        self.assertEqual(len(dismissals), task.RESTOCK_RETRY_LIMIT)
        self.assertEqual(session.restock_retry_count, 3)
        self.assertEqual(round_recoveries, [])

        self.assertTrue(task._handle_flow_error(WaitFailedException()))

        self.assertEqual(len(round_recoveries), 1)
        self.assertIs(session.restock_phase, RestockPhase.NONE)
        self.assertEqual(session.restock_retry_count, 0)

    def test_completed_sale_only_retries_scene_recovery(self):
        task = object.__new__(FishingTask)
        task._fishing_session = FishingSession(restock_phase=RestockPhase.OPEN_BAIT_MENU)
        recoveries = []
        task.find_one = lambda _label: self.fail("sale must not be submitted twice")
        task._press_escape_for_recovery = lambda: recoveries.append(True)

        task._sell_and_return()

        self.assertEqual(recoveries, [True])

    def test_completed_purchase_only_retries_scene_recovery(self):
        task = object.__new__(FishingTask)
        task._fishing_session = FishingSession(restock_phase=RestockPhase.CONFIRM_BAIT)
        recoveries = []
        task._press_escape_for_recovery = lambda: recoveries.append(True)

        task._buy_bait_and_return()

        self.assertEqual(recoveries, [True])

    def test_scene_recovery_uses_a_flow_safe_point_for_monthly_card(self):
        task = object.__new__(FishingTask)
        task.flow = type(
            "FlowStub",
            (),
            {"safe_point": lambda _self: (_ for _ in ()).throw(FlowReplan())},
        )()
        task._clear_bar_key_if_hold_mode = lambda: None
        task._set_stage = lambda _stage: None
        task.next_frame = lambda: None
        task.is_ready_to_cast = lambda: False

        with self.assertRaises(FlowReplan):
            task._return_to_fishing_ready()

    def test_control_exits_after_the_fish_start_prompt_returns(self):
        task = object.__new__(FishingTask)
        task.flow = type("FlowStub", (), {"safe_point": lambda _self: None})()
        task.detect_fishing_bar_state = lambda: {}
        task.is_valid_bar_state = lambda _state: False
        task._clear_bar_key_if_hold_mode = lambda: None
        task.has_success_overlay = lambda: False
        task.has_fish_start = lambda: True
        task.sleep = lambda _seconds: None
        task.log_warning = lambda _message: None

        with patch(
            "src.tasks.FishingTask.time.time",
            side_effect=[0, 0, 2, 2, 2, 2, 8, 8, 8],
        ):
            task.control_until_finish()


if __name__ == "__main__":
    unittest.main()
