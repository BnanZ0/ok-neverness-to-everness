import unittest
from enum import Enum, auto

from ok import TaskDisabledException, WaitFailedException

from src.scene_flow import SceneFlow, StepPolicy


class Step(Enum):
    A = auto()
    B = auto()
    C = auto()
    GUARD = auto()


class TestSceneFlow(unittest.TestCase):
    def test_next_limits_dispatch_and_completed_action_is_not_replayed(self):
        state = {"scene": Step.A, "calls": []}

        def handle_a():
            state["calls"].append("A")

        def refresh():
            if state["calls"] == ["A"]:
                state["scene"] = Step.B

        def handle_b():
            state["calls"].append("B")
            state["scene"] = Step.C

        flow = SceneFlow().before_step(refresh)
        flow.step(Step.A, lambda: state["scene"] is Step.A, handle_a, next=(Step.B,))
        flow.step(Step.B, lambda: state["scene"] is Step.B, handle_b, next=(Step.C,))
        flow.step(Step.C, lambda: state["scene"] is Step.C, lambda: None, next=(Step.C,))

        self.assertTrue(flow.run(lambda: state["scene"] is Step.C, start=Step.A, poll_interval=0))
        self.assertEqual(state["calls"], ["A", "B"])

    def test_self_loop_routes_after_max_attempts(self):
        state = {"scene": Step.A, "calls": 0, "failures": []}

        def route(failure):
            state["failures"].append(failure)
            state["scene"] = Step.B
            return Step.B

        flow = SceneFlow()
        flow.step(
            Step.A,
            lambda: state["scene"] is Step.A,
            lambda: state.update(calls=state["calls"] + 1),
            next=(Step.A,),
            policy=StepPolicy(max_attempts=2),
            on_failure=route,
        )
        flow.step(Step.B, lambda: state["scene"] is Step.B, lambda: None, next=(Step.B,))

        self.assertTrue(flow.run(lambda: state["scene"] is Step.B, start=Step.A, poll_interval=0))
        self.assertEqual(state["calls"], 2)
        self.assertEqual(state["failures"][0].reason, "step retry limit reached")

    def test_action_results_are_ignored(self):
        state = {"scene": Step.A}
        flow = SceneFlow()
        flow.step(
            Step.A,
            lambda: state["scene"] is Step.A,
            lambda: state.update(scene=Step.B) or True,
            next=(Step.B,),
        )
        flow.step(Step.B, lambda: state["scene"] is Step.B, lambda: None, next=(Step.B,))

        self.assertTrue(flow.run(lambda: state["scene"] is Step.B, start=Step.A, poll_interval=0))

    def test_transition_retries_without_global_recovery(self):
        state = {"scene": Step.A, "actions": 0, "transitions": 0, "recoveries": 0}

        def action_a():
            state["actions"] += 1
            state["scene"] = None

        def transition_to_b():
            state["transitions"] += 1
            if state["transitions"] == 2:
                state["scene"] = Step.B

        flow = SceneFlow()
        flow.step(
            Step.A,
            lambda: state["scene"] is Step.A,
            action_a,
            next=(Step.B,),
            transition=flow.transition(transition_to_b, interval=0, timeout=1),
        )
        flow.step(Step.B, lambda: state["scene"] is Step.B, lambda: None, next=(Step.B,))
        flow.recovery(lambda: state.update(recoveries=state["recoveries"] + 1), grace=5)

        self.assertTrue(flow.run(lambda: state["scene"] is Step.B, start=Step.A, poll_interval=0))
        self.assertEqual(state["actions"], 1)
        self.assertEqual(state["transitions"], 2)
        self.assertEqual(state["recoveries"], 0)

    def test_guard_preserves_the_pending_target(self):
        state = {"scene": Step.GUARD, "calls": []}

        def guard():
            state["calls"].append("guard")
            state["scene"] = Step.A

        def handle_a():
            state["calls"].append("A")
            state["scene"] = Step.B

        flow = SceneFlow()
        flow.guard(Step.GUARD, lambda: state["scene"] is Step.GUARD, guard)
        flow.step(Step.A, lambda: state["scene"] is Step.A, handle_a, next=(Step.B,))
        flow.step(Step.B, lambda: state["scene"] is Step.B, lambda: None, next=(Step.B,))

        self.assertTrue(flow.run(lambda: state["scene"] is Step.B, start=Step.A, poll_interval=0))
        self.assertEqual(state["calls"], ["guard", "A"])

    def test_interrupt_replan_does_not_consume_an_attempt(self):
        state = {"scene": Step.A, "interrupt": False, "calls": 0}

        def handle_a():
            state["calls"] += 1
            if state["calls"] == 1:
                state["interrupt"] = True
                flow.safe_point()
            state["scene"] = Step.B

        def dismiss_interrupt():
            state["interrupt"] = False

        flow = SceneFlow()
        flow.step(
            Step.A,
            lambda: state["scene"] is Step.A,
            handle_a,
            next=(Step.A, Step.B),
            policy=StepPolicy(max_attempts=1),
        )
        flow.step(Step.B, lambda: state["scene"] is Step.B, lambda: None, next=(Step.B,))
        flow.interrupt(lambda: state["interrupt"], dismiss_interrupt)

        self.assertTrue(flow.run(lambda: state["scene"] is Step.B, start=Step.A, poll_interval=0))
        self.assertEqual(state["calls"], 2)

    def test_recovery_waits_for_its_grace_and_propagates_task_disable(self):
        state = {"scene": None, "frames": 0, "recoveries": 0}

        def refresh():
            state["frames"] += 1
            if state["frames"] == 3:
                state["scene"] = Step.A

        flow = SceneFlow().before_step(refresh)
        flow.step(Step.A, lambda: state["scene"] is Step.A, lambda: None, next=(Step.A,))
        flow.recovery(lambda: state.update(recoveries=state["recoveries"] + 1), grace=10)

        self.assertTrue(flow.run(lambda: state["scene"] is Step.A, start=Step.A, poll_interval=0))
        self.assertEqual(state["recoveries"], 0)

        disabled = SceneFlow().propagate(TaskDisabledException)
        disabled.step(
            Step.A,
            lambda: True,
            lambda: (_ for _ in ()).throw(TaskDisabledException()),
            next=(Step.A,),
        )
        with self.assertRaises(TaskDisabledException):
            disabled.run(lambda: False, start=Step.A, poll_interval=0)

    def test_wait_failure_routes_when_the_step_cannot_retry(self):
        state = {"scene": Step.A, "failure": None}

        def fail_a():
            state["scene"] = None
            raise WaitFailedException("action failed")

        def route(failure):
            state["failure"] = failure
            state["scene"] = Step.B
            return Step.B

        flow = SceneFlow()
        flow.step(
            Step.A,
            lambda: state["scene"] is Step.A,
            fail_a,
            next=(Step.B,),
            on_failure=route,
        )
        flow.step(Step.B, lambda: state["scene"] is Step.B, lambda: None, next=(Step.B,))

        self.assertTrue(flow.run(lambda: state["scene"] is Step.B, start=Step.A, poll_interval=0))
        self.assertEqual(state["failure"].reason, "action failed")


if __name__ == "__main__":
    unittest.main()
