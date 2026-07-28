"""Framework-independent supervisor for reactive task scene flows."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any


Detector = Callable[[], bool]
Action = Callable[[], Any]
ErrorHandler = Callable[[Exception], bool]


class FlowConfigurationError(ValueError):
    """Raised when a task declares an invalid Flow."""


class FlowReplan(Exception):
    """Leave the current task action and classify the screen again."""


@dataclass(frozen=True)
class _Node:
    key: Enum
    detector: Detector
    action: Action | None
    priority: int
    order: int


@dataclass(frozen=True)
class _Interrupt:
    detector: Detector
    handler: Action
    priority: int
    order: int


@dataclass(frozen=True)
class _Fallback:
    action: Action | None
    timeout: float
    grace: float


class Flow:
    """Reclassify scenes after interrupts and recoverable node failures.

    Flow deliberately does not perform input, sleep-heavy UI waiting, or task
    business actions.  Node handlers keep using their task's existing helpers
    for verified interactions.  A handler either completes, or raises its
    normal task exception; Flow then observes the screen again instead of
    resuming its call stack.
    """

    DEFAULT_RECOVERY_TIMEOUT = 60.0
    DEFAULT_FALLBACK_GRACE = 5.0
    DEFAULT_POLL_INTERVAL = 0.05
    INTERRUPTED_NODE_GRACE = 3.0

    def __init__(self) -> None:
        self._nodes: dict[Enum, _Node] = {}
        self._interrupts: list[_Interrupt] = []
        self._fallback: _Fallback | None = None
        self._before_step: Action | None = None
        self._order = 0
        self._run_depth = 0
        self._handling_interrupt = False
        self._interrupt_recovery_pending = False
        self._passthrough_exceptions: tuple[type[BaseException], ...] = ()

    @property
    def active(self) -> bool:
        """Whether a Flow loop currently owns task-level recovery."""
        return self._run_depth > 0

    @property
    def handling_interrupt(self) -> bool:
        """Whether an interrupt handler is running its own task actions."""
        return self._handling_interrupt

    def node(
        self,
        key: Enum,
        detector: Detector,
        action: Action | None = None,
        *,
        priority: int = 0,
    ) -> "Flow":
        self._require_key(key)
        if key in self._nodes:
            raise FlowConfigurationError(f"Flow node is already registered: {key!r}")
        self._require_callable(detector, "detector")
        if action is not None:
            self._require_callable(action, "node action")
        self._nodes[key] = _Node(key, detector, action, priority, self._next_order())
        return self

    def before_step(self, action: Action) -> "Flow":
        """Register the task's frame-refresh hook."""
        self._require_callable(action, "before-step action")
        self._before_step = action
        return self

    def propagate(self, *exception_types: type[BaseException]) -> "Flow":
        """Let task-control exceptions leave Flow without recovery or replanning."""
        if not exception_types:
            raise FlowConfigurationError("Flow requires at least one exception type to propagate")
        for exception_type in exception_types:
            if not isinstance(exception_type, type) or not issubclass(exception_type, BaseException):
                raise FlowConfigurationError("Flow propagated exceptions must inherit BaseException")
        self._passthrough_exceptions += exception_types
        return self

    def interrupt(
        self,
        detector: Detector,
        handler: Action,
        *,
        priority: int = 0,
    ) -> "Flow":
        self._require_callable(detector, "interrupt detector")
        self._require_callable(handler, "interrupt handler")
        self._interrupts.append(_Interrupt(detector, handler, priority, self._next_order()))
        return self

    def fallback(
        self,
        action: Action | None = None,
        *,
        timeout: float = DEFAULT_RECOVERY_TIMEOUT,
        grace: float = DEFAULT_FALLBACK_GRACE,
    ) -> "Flow":
        if action is not None:
            self._require_callable(action, "fallback action")
        if timeout <= 0:
            raise FlowConfigurationError("Flow fallback timeout must be greater than zero")
        if grace < 0 or grace >= timeout:
            raise FlowConfigurationError("Flow fallback grace must be non-negative and less than timeout")
        self._fallback = _Fallback(action, timeout, grace)
        return self

    def safe_point(self) -> None:
        """Stop the current action when a global interrupt is visible.

        Call this inside custom polling loops.  Ordinary ``BaseNTETask``
        ``wait_until`` calls are already safe points while Flow is active.
        """
        if self._check_interrupts():
            raise FlowReplan()

    def checkpoint(self) -> Enum | None:
        """Process one interrupt and classify the screen outside a Flow loop."""
        if not self._interrupt_recovery_pending:
            self._check_interrupts()
        if self._interrupt_recovery_pending:
            if not self._recover_interrupt_failure(on_error=None):
                return None
        return self.classify()

    def _check_interrupts(self) -> bool:
        """Handle one highest-priority interrupt and report whether one was visible."""
        if self._handling_interrupt:
            return False
        for interrupt in sorted(self._interrupts, key=lambda item: (-item.priority, item.order)):
            if interrupt.detector():
                self._handling_interrupt = True
                try:
                    self._interrupt_recovery_pending = interrupt.handler() is False
                    return True
                finally:
                    self._handling_interrupt = False
        return False

    def classify(self) -> Enum | None:
        """Return the highest-priority scene currently visible to the task."""
        self._validate()
        for node in self._ordered_nodes():
            if node.detector():
                return node.key
        return None

    def loop(
        self,
        until: Callable[[], bool],
        *,
        on_error: ErrorHandler | None = None,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
    ) -> bool:
        """Dispatch visible node handlers until *until* is true.

        Global interrupts always win.  When a node action fails, Flow refreshes
        the screen and first checks that same node only.  If it disappeared,
        Flow skips the old node's recovery and starts a fresh classification on
        the next step; this prevents a stale failure from corrupting a later
        scene.
        """
        self._validate()
        self._require_callable(until, "loop condition")
        if on_error is not None:
            self._require_callable(on_error, "loop error handler")
        if poll_interval < 0:
            raise FlowConfigurationError("Flow loop poll interval cannot be negative")

        self._run_depth += 1
        try:
            unknown_since: float | None = None
            interrupted_node: Enum | None = None
            interrupted_node_missing_since: float | None = None
            while not until():
                self._run_before_step()
                if self._interrupt_recovery_pending:
                    interrupted_node = None
                    interrupted_node_missing_since = None
                    if not self._recover_interrupt_failure(on_error):
                        return False
                    self._wait(poll_interval)
                    continue

                if self._check_interrupts():
                    if self._interrupt_recovery_pending:
                        interrupted_node = None
                        interrupted_node_missing_since = None
                        if not self._recover_interrupt_failure(on_error):
                            return False
                    else:
                        interrupted_node_missing_since = None
                    self._wait(poll_interval)
                    continue

                if interrupted_node is not None:
                    if self._nodes[interrupted_node].detector():
                        current = interrupted_node
                        interrupted_node_missing_since = None
                    else:
                        now = time.monotonic()
                        if interrupted_node_missing_since is None:
                            interrupted_node_missing_since = now
                        if now - interrupted_node_missing_since < self.INTERRUPTED_NODE_GRACE:
                            self._wait(poll_interval)
                            continue
                        current = self.classify()
                else:
                    current = self.classify()
                interrupted_node = None
                interrupted_node_missing_since = None
                if current is None:
                    now = time.monotonic()
                    if unknown_since is None:
                        unknown_since = now
                    if now - unknown_since >= self._fallback_timeout():
                        return False
                    if now - unknown_since >= self._fallback_grace():
                        try:
                            if not self._run_fallback_action():
                                return False
                        except FlowReplan:
                            pass
                        except Exception as error:
                            if self._must_propagate(error):
                                raise
                            if not self._handle_error(error, on_error):
                                raise
                    self._wait(poll_interval)
                    continue

                unknown_since = None
                action = self._nodes[current].action
                if action is not None:
                    try:
                        action()
                    except FlowReplan:
                        interrupted_node = current
                        self._wait(poll_interval)
                        continue
                    except Exception as error:
                        if self._must_propagate(error):
                            raise
                        self._run_before_step()
                        if self._check_interrupts():
                            interrupted_node = current
                            interrupted_node_missing_since = None
                            self._wait(poll_interval)
                            continue
                        if not self._nodes[current].detector():
                            self._wait(poll_interval)
                            continue
                        if not self._handle_error(error, on_error):
                            raise
                self._wait(poll_interval)

            return True
        finally:
            self._run_depth -= 1

    @staticmethod
    def _handle_error(error: Exception, on_error: ErrorHandler | None) -> bool:
        return on_error is not None and on_error(error)

    def _run_before_step(self) -> None:
        if self._before_step is not None:
            self._before_step()

    def _run_fallback_action(self) -> bool:
        if self._fallback is None:
            return False
        return self._fallback.action is None or self._fallback.action() is not False

    def _recover_interrupt_failure(self, on_error: ErrorHandler | None) -> bool:
        """Run the task's immediate generic recovery after an interrupt failure."""
        self._interrupt_recovery_pending = False
        if self._fallback is None:
            return False
        try:
            return self._run_fallback_action()
        except FlowReplan:
            return True
        except Exception as error:
            if self._must_propagate(error):
                raise
            if not self._handle_error(error, on_error):
                raise
            return True

    def _fallback_timeout(self) -> float:
        return self._fallback.timeout if self._fallback is not None else 0

    def _fallback_grace(self) -> float:
        return self._fallback.grace if self._fallback is not None else 0

    def _must_propagate(self, error: Exception) -> bool:
        return isinstance(error, self._passthrough_exceptions)

    def _ordered_nodes(self) -> list[_Node]:
        return sorted(self._nodes.values(), key=lambda item: (-item.priority, item.order))

    def _validate(self) -> None:
        if not self._nodes:
            raise FlowConfigurationError("Flow requires at least one registered node")
    def _next_order(self) -> int:
        order = self._order
        self._order += 1
        return order

    @staticmethod
    def _wait(poll_interval: float) -> None:
        if poll_interval > 0:
            time.sleep(poll_interval)

    @staticmethod
    def _require_key(key: object) -> None:
        if not isinstance(key, Enum):
            raise FlowConfigurationError("Flow node keys must be Enum members")

    @staticmethod
    def _require_callable(value: object, name: str) -> None:
        if not callable(value):
            raise FlowConfigurationError(f"Flow {name} must be callable")
