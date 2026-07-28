import unittest
from enum import Enum, auto
from unittest.mock import patch

from ok import BaseTask, TaskDisabledException

from src.flow import Flow, FlowConfigurationError
from src.tasks.BaseNTETask import BaseNTETask


class Node(Enum):
    A = auto()
    B = auto()
    C = auto()


class TestFlow(unittest.TestCase):
    def test_node_keys_must_be_enum_members(self):
        with self.assertRaises(FlowConfigurationError):
            Flow().node("A", lambda: True)

    def test_duplicate_node_is_rejected(self):
        flow = Flow().node(Node.A, lambda: True)
        with self.assertRaises(FlowConfigurationError):
            flow.node(Node.A, lambda: True)

    def test_interrupt_reclassifies_after_screen_changes(self):
        state = {"value": Node.A, "monthly_card": True}

        def dismiss_monthly_card():
            state["monthly_card"] = False
            state["value"] = Node.B

        flow = (
            Flow()
            .node(Node.A, lambda: state["value"] is Node.A)
            .node(Node.B, lambda: state["value"] is Node.B)
            .interrupt(lambda: state["monthly_card"], dismiss_monthly_card, priority=100)
        )

        self.assertIs(flow.checkpoint(), Node.B)

    def test_checkpoint_failed_interrupt_runs_fallback(self):
        state = {"value": Node.A, "monthly_card": True}

        def recover_from_interrupt():
            state["value"] = Node.B

        flow = (
            Flow()
            .node(Node.A, lambda: state["value"] is Node.A)
            .node(Node.B, lambda: state["value"] is Node.B)
            .interrupt(lambda: state["monthly_card"], lambda: False)
            .fallback(recover_from_interrupt)
        )

        self.assertIs(flow.checkpoint(), Node.B)

    def test_failed_interrupt_stops_the_old_action_and_uses_fallback(self):
        state = {"value": Node.A, "monthly_card": False, "fallbacks": 0, "handlers": 0}

        def handle_a():
            state["monthly_card"] = True
            flow.safe_point()

        def recover_from_interrupt():
            state["fallbacks"] += 1
            state["monthly_card"] = False
            state["value"] = Node.B

        def fail_to_dismiss_interrupt():
            state["handlers"] += 1
            return False

        flow = (
            Flow()
            .node(Node.A, lambda: state["value"] is Node.A, handle_a)
            .node(Node.B, lambda: state["value"] is Node.B)
            .interrupt(lambda: state["monthly_card"], fail_to_dismiss_interrupt)
            .fallback(recover_from_interrupt, grace=0)
        )

        self.assertTrue(flow.loop(lambda: state["value"] is Node.B, poll_interval=0))
        self.assertEqual(state["fallbacks"], 1)
        self.assertEqual(state["handlers"], 1)

    def test_failed_interrupt_without_fallback_stops_the_flow(self):
        state = {"monthly_card": False, "actions": 0}

        def handle_a():
            state["actions"] += 1
            state["monthly_card"] = True
            flow.safe_point()

        flow = (
            Flow()
            .node(Node.A, lambda: True, handle_a)
            .interrupt(lambda: state["monthly_card"], lambda: False)
        )

        self.assertFalse(flow.loop(lambda: False, poll_interval=0))
        self.assertEqual(state["actions"], 1)

    def test_interrupted_node_waits_three_seconds_before_reclassification(self):
        state = {"value": Node.A, "monthly_card": False, "b_actions": 0}

        def interrupt_a():
            state["value"] = Node.B
            state["monthly_card"] = True
            flow.safe_point()

        def handle_b():
            state["b_actions"] += 1
            state["value"] = Node.C

        flow = (
            Flow()
            .node(Node.A, lambda: state["value"] is Node.A, interrupt_a)
            .node(Node.B, lambda: state["value"] is Node.B, handle_b)
            .node(Node.C, lambda: state["value"] is Node.C)
            .interrupt(
                lambda: state["monthly_card"],
                lambda: state.__setitem__("monthly_card", False),
            )
        )

        with patch("src.flow.time.monotonic", side_effect=[0, 1, 2.9, 3]):
            self.assertTrue(flow.loop(lambda: state["value"] is Node.C, poll_interval=0))

        self.assertEqual(state["b_actions"], 1)

    def test_loop_dispatches_the_action_of_the_visible_node(self):
        state = {"value": Node.A, "actions": []}

        def handle_a():
            state["actions"].append(Node.A)
            state["value"] = Node.B

        def handle_b():
            state["actions"].append(Node.B)
            state["value"] = Node.C

        flow = (
            Flow()
            .node(Node.A, lambda: state["value"] is Node.A, handle_a)
            .node(Node.B, lambda: state["value"] is Node.B, handle_b)
            .node(Node.C, lambda: state["value"] is Node.C)
        )

        self.assertTrue(flow.loop(lambda: state["value"] is Node.C, poll_interval=0))
        self.assertEqual(state["actions"], [Node.A, Node.B])

    def test_loop_retries_fallback_until_a_node_is_visible(self):
        state = {"value": None, "attempts": 0}

        def dismiss_unknown_screen():
            state["attempts"] += 1
            if state["attempts"] == 2:
                state["value"] = Node.A

        flow = Flow().node(Node.A, lambda: state["value"] is Node.A).fallback(
            dismiss_unknown_screen,
            grace=0,
        )

        self.assertTrue(flow.loop(lambda: state["value"] is Node.A, poll_interval=0))
        self.assertEqual(state["attempts"], 2)

    def test_fallback_waits_for_the_unknown_scene_grace_period(self):
        state = {"value": None, "attempts": 0}

        def dismiss_unknown_screen():
            state["attempts"] += 1
            state["value"] = Node.A

        flow = Flow().node(Node.A, lambda: state["value"] is Node.A).fallback(
            dismiss_unknown_screen,
            grace=5,
        )

        with patch("src.flow.time.monotonic", side_effect=[100, 104.9, 105]):
            self.assertTrue(flow.loop(lambda: state["value"] is Node.A, poll_interval=0))

        self.assertEqual(state["attempts"], 1)

    def test_fallback_uses_a_five_second_grace_period_by_default(self):
        state = {"value": None, "attempts": 0}

        def dismiss_unknown_screen():
            state["attempts"] += 1
            state["value"] = Node.A

        flow = Flow().node(Node.A, lambda: state["value"] is Node.A).fallback(
            dismiss_unknown_screen,
        )

        with patch("src.flow.time.monotonic", side_effect=[100, 104.9, 105]):
            self.assertTrue(flow.loop(lambda: state["value"] is Node.A, poll_interval=0))

        self.assertEqual(state["attempts"], 1)

    def test_fallback_grace_must_fit_inside_the_recovery_timeout(self):
        with self.assertRaises(FlowConfigurationError):
            Flow().fallback(timeout=5, grace=5)

    def test_failure_of_the_same_node_uses_its_recovery_handler(self):
        state = {"value": Node.A, "recoveries": 0}

        def fail_a():
            raise RuntimeError("still on A")

        def recover(error):
            self.assertEqual(str(error), "still on A")
            state["recoveries"] += 1
            state["value"] = Node.B
            return True

        flow = Flow().node(Node.A, lambda: state["value"] is Node.A, fail_a).node(
            Node.B,
            lambda: state["value"] is Node.B,
        )

        self.assertTrue(flow.loop(lambda: state["value"] is Node.B, on_error=recover, poll_interval=0))
        self.assertEqual(state["recoveries"], 1)

    def test_failure_replans_when_the_failed_node_disappeared(self):
        state = {"value": Node.A, "recoveries": 0, "handled_b": 0}

        def fail_after_transition():
            state["value"] = Node.B
            raise RuntimeError("A is stale")

        def handle_b():
            state["handled_b"] += 1
            state["value"] = Node.C

        def recover(_error):
            state["recoveries"] += 1
            return True

        flow = (
            Flow()
            .node(Node.A, lambda: state["value"] is Node.A, fail_after_transition)
            .node(Node.B, lambda: state["value"] is Node.B, handle_b)
            .node(Node.C, lambda: state["value"] is Node.C)
        )

        self.assertTrue(flow.loop(lambda: state["value"] is Node.C, on_error=recover, poll_interval=0))
        self.assertEqual(state["recoveries"], 0)
        self.assertEqual(state["handled_b"], 1)

    def test_interrupt_wins_over_recovery_after_a_node_failure(self):
        state = {"value": Node.A, "monthly_card": False, "recoveries": 0}

        def fail_a():
            state["monthly_card"] = True
            raise RuntimeError("monthly card appeared")

        def dismiss_monthly_card():
            state["monthly_card"] = False
            state["value"] = Node.B

        def recover(_error):
            state["recoveries"] += 1
            return True

        flow = (
            Flow()
            .node(Node.A, lambda: state["value"] is Node.A, fail_a)
            .node(Node.B, lambda: state["value"] is Node.B)
            .interrupt(lambda: state["monthly_card"], dismiss_monthly_card, priority=100)
        )

        self.assertTrue(flow.loop(lambda: state["value"] is Node.B, on_error=recover, poll_interval=0))
        self.assertEqual(state["recoveries"], 0)

    def test_interrupt_reenters_the_same_node_when_its_scene_is_still_visible(self):
        state = {"value": Node.A, "monthly_card": False, "a_actions": 0}

        def dismiss_monthly_card():
            state["monthly_card"] = False
            return True

        def handle_a():
            state["a_actions"] += 1
            if state["a_actions"] == 1:
                state["monthly_card"] = True
                flow.safe_point()
            state["value"] = Node.B

        flow = (
            Flow()
            .node(Node.A, lambda: state["value"] is Node.A, handle_a)
            .node(Node.B, lambda: state["value"] is Node.B)
            .interrupt(lambda: state["monthly_card"], dismiss_monthly_card)
        )

        self.assertTrue(flow.loop(lambda: state["value"] is Node.B, poll_interval=0))
        self.assertEqual(state["a_actions"], 2)

    def test_propagated_task_control_exception_skips_recovery(self):
        state = {"recoveries": 0}

        def disable_task():
            raise TaskDisabledException()

        def recover(_error):
            state["recoveries"] += 1
            return True

        flow = Flow().node(Node.A, lambda: True, disable_task).propagate(TaskDisabledException)

        with self.assertRaises(TaskDisabledException):
            flow.loop(lambda: False, on_error=recover, poll_interval=0)

        self.assertEqual(state["recoveries"], 0)

    def test_wait_until_interrupt_abandons_the_old_condition_and_replans(self):
        state = {"value": Node.A, "monthly_card": True, "wait_condition_called": 0}
        task = object.__new__(BaseNTETask)
        task.flow = Flow()

        def dismiss_monthly_card():
            state["monthly_card"] = False
            state["value"] = Node.B
            return True

        def wait_for_old_screen():
            state["wait_condition_called"] += 1
            return False

        def fake_wait_until(_self, condition, **_kwargs):
            return condition()

        def handle_a():
            BaseNTETask.wait_until(task, wait_for_old_screen)

        def handle_b():
            state["value"] = Node.C

        task.flow.node(Node.A, lambda: state["value"] is Node.A, handle_a)
        task.flow.node(Node.B, lambda: state["value"] is Node.B, handle_b)
        task.flow.node(Node.C, lambda: state["value"] is Node.C)
        task.flow.interrupt(lambda: state["monthly_card"], dismiss_monthly_card)

        with patch.object(BaseTask, "wait_until", fake_wait_until):
            self.assertTrue(task.flow.loop(lambda: state["value"] is Node.C, poll_interval=0))

        self.assertEqual(state["wait_condition_called"], 0)


if __name__ == "__main__":
    unittest.main()
