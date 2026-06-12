from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Iterable

from ok import Logger

from .requests import (
    _Request,
    _RouteRequest,
    request_complete_action,
    request_complete_entry_reaction,
    request_complete_switch,
    request_fulfilled,
)
from .types import (
    ActionIntent,
    ActionResult,
    ExpectedEntry,
    FieldClaim,
    _display_result_name,
)

if TYPE_CHECKING:
    from src.char.BaseChar import BaseChar


logger = Logger.get_logger("planner")


@dataclass(slots=True)
class CombatState:
    """`CombatPlanner` 的运行状态容器。

    保存队伍角色、协作请求、严格路线锁以及切入动作期望。通常由
    `CombatPlanner` 管理，角色代码不应直接修改。
    """

    chars: list["BaseChar"] = field(default_factory=list)
    active_requests: list[_Request] = field(default_factory=list)
    locked_route: _RouteRequest | None = None
    pending_entry_expectations: dict[int, ExpectedEntry] = field(default_factory=dict)

    def reset(self, chars: Iterable["BaseChar"]) -> None:
        """用当前队伍重置 planner 状态。"""

        self.chars = [char for char in chars if char is not None]
        self.active_requests.clear()
        self.locked_route = None
        self.pending_entry_expectations.clear()

    def prune(self) -> None:
        """清理过期请求，并处理 strict route 的过期锁定行为。"""

        now = time.time()
        active_requests = []
        for request in self.active_requests:
            if request.expired(now):
                request.notify_expired()
                continue
            active_requests.append(request)
        self.active_requests = active_requests
        if self.locked_route is not None and self.locked_route.expired(now):
            step = self.locked_route.current_step()
            step_reason = step.reason if step is not None else "route completed"
            logger.warning(
                f"strict route deadline expired, route unlocked: "
                f"{self.locked_route.reason} / {step_reason}"
            )
            self.locked_route.notify_expired()
            self.locked_route = None

    def add_requests(self, requests: Iterable[_Request]) -> None:
        """加入角色新发布的协作请求。"""

        for request in requests:
            if request_fulfilled(request) and not request.return_to_source:
                continue
            if isinstance(request, _RouteRequest) and request.steps:
                self.locked_route = request
                step = request.current_step()
                step_reason = step.reason if step is not None else "no step"
                logger.info(f"strict route locked: {request.reason} / {step_reason}")
                continue
            self.active_requests.append(request)

    def record_action(self, char: "BaseChar", result: ActionResult) -> None:
        """记录一次角色动作，并推进相关协作请求。"""

        for request in self.active_requests:
            request_complete_action(request, char, result)
        self.active_requests = [
            request
            for request in self.active_requests
            if not request_fulfilled(request)
            or (request.return_to_source and char.index != request._source)
        ]
        if self.locked_route is None:
            return

        step = self.locked_route.current_step()
        if self.locked_route.complete_step(char, result):
            result_name = _display_result_name(result)
            step_reason = step.reason if step is not None else result_name
            logger.info(
                f"strict route completed step {char}: "
                f"{self.locked_route.reason} / {step_reason} -> {result_name}"
            )
            if self.locked_route.fulfilled():
                self.fulfill_locked_route()

    def record_entry_reaction(self, source_char: "BaseChar", target_char: "BaseChar") -> None:
        """记录一次入场/环合反应，并推进相关协作请求。"""

        for request in self.active_requests:
            request_complete_entry_reaction(request, source_char, target_char)
        if self.locked_route is None:
            return

        step = self.locked_route.current_step()
        if self.locked_route.complete_entry_reaction(source_char, target_char):
            step_reason = step.reason if step is not None else "entry reaction"
            logger.info(
                f"strict route completed entry reaction {source_char} -> {target_char}: "
                f"{self.locked_route.reason} / {step_reason}"
            )
            if self.locked_route.fulfilled():
                self.fulfill_locked_route()

    def record_switch(self, target_char: "BaseChar") -> None:
        """记录一次实际切人，并消费匹配的 switch request。"""

        active_requests = []
        for request in self.active_requests:
            if request_complete_switch(request, target_char):
                request.notify_fulfilled()
                logger.info(f"switch request fulfilled: {request.reason}")
                continue
            active_requests.append(request)
        self.active_requests = active_requests

    def fulfill_locked_route(self) -> None:
        """完成当前 strict route，并按配置清除或转为返回发起者请求。"""

        if self.locked_route is None:
            return
        self.locked_route.notify_fulfilled()
        if not self.locked_route.return_to_source:
            logger.info(f"strict route fulfilled: {self.locked_route.reason}")
            self.locked_route = None
            return
        self.active_requests.append(self.locked_route)
        logger.info(f"strict route fulfilled: {self.locked_route.reason}")
        self.locked_route = None

    def char_by_index(self, index: int) -> "BaseChar | None":
        """按队伍 index 查找角色。"""

        for char in self.chars:
            if char.index == index:
                return char
        return None

    def set_pending_entry_expectation(
        self, char: "BaseChar", expected_entry: ExpectedEntry | None
    ) -> None:
        """登记某角色下次切入后应优先尝试的动作。"""

        if expected_entry is not None:
            self.pending_entry_expectations[char.index] = expected_entry

    def pop_pending_entry_expectation(self, char: "BaseChar") -> ExpectedEntry | None:
        """取出并清除某角色的切入动作期望。"""

        return self.pending_entry_expectations.pop(char.index, None)


@dataclass(slots=True)
class _IntentSet:
    """一次 planner 决策内缓存的角色意图快照。"""

    actions: list[ActionIntent] = field(default_factory=list)
    claims: list[FieldClaim] = field(default_factory=list)
