from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .requests import (
    RequestCallback,
    RequestDeadline,
    RequestLifetime,
    _Request,
    _ReservationRequest,
    _RouteRequest,
    _SwitchRequest,
    _TagRequest,
    request_counts_as_active,
    request_reserves_action,
)
from .state import CombatState, _IntentSet
from .types import (
    NEVER_EXPIRES,
    ActionReservation,
    ActionResult,
    ActionSlot,
    ActionTag,
    FollowupStep,
)

if TYPE_CHECKING:
    from src.char.BaseChar import BaseChar
    from src.combat.BaseCombatTask import BaseCombatTask


@dataclass(slots=True)
class CombatContext:
    """角色动作执行时收到的 planner 上下文。

    `ActionIntent.execute` 会收到此对象。角色可用它查询 strict route、检查
    planner 是否允许某槽位动作、或向 `CombatPlanner` 发布协作请求。
    """

    task: "BaseCombatTask"
    _state: CombatState
    current_char: "BaseChar"
    _published_requests: list[_Request] = field(default_factory=list)
    _intent_cache: dict[int, _IntentSet] | None = None

    @property
    def chars(self) -> list["BaseChar"]:
        """当前 planner 管理的队伍角色列表。"""

        return self._state.chars

    def has_active_request(self) -> bool:
        """返回当前是否存在未完成的协作请求或 strict route。"""

        self._state.prune()
        return bool(
            self._state.locked_route
            or any(request_counts_as_active(request) for request in self._state.active_requests)
        )

    def has_strict_route(self) -> bool:
        """返回当前是否存在正在锁定执行的 strict route。"""

        self._state.prune()
        return self._state.locked_route is not None

    def strict_route_wants_action(
        self,
        char: "BaseChar",
        slot: ActionSlot | None = None,
        action_name: str = "",
        tags: set[ActionTag] | None = None,
    ) -> bool:
        """查询当前 strict route 是否正在请求指定角色动作。"""

        request = self._state.locked_route
        if request is None:
            return False
        step = request.current_step()
        if step is None:
            return False
        action = ActionResult(name=action_name, tags=set(tags or set()), slot=slot)
        return step.wants(char, action)

    def can_execute_action(
        self,
        char: "BaseChar",
        action_name: str = "",
        tags: set[ActionTag] | None = None,
        slot: ActionSlot | None = None,
    ) -> bool:
        """查询 planner 是否允许指定角色动作执行。"""

        self._state.prune()
        action = ActionResult(name=action_name, tags=set(tags or set()), slot=slot)
        request = self._state.locked_route
        if request is not None:
            step = request.current_step()
            if step is not None and step.wants(char, action):
                return True
        for active_request in self._state.active_requests:
            if request_reserves_action(active_request, char, action):
                return False
        return True

    def request_route(
        self,
        steps: list[FollowupStep],
        reason: str = "",
        until: RequestDeadline | None = None,
        return_to_source: bool = False,
        on_done: RequestCallback | None = None,
        on_expired: RequestCallback | None = None,
    ) -> None:
        """发布固定顺序协作路线。"""

        if not steps:
            return
        self._publish_request(
            _RouteRequest(
                reason=reason or f"{self.current_char} route request",
                _source=self.current_char.index,
                until=until,
                return_to_source=return_to_source,
                on_done=on_done,
                on_expired=on_expired,
                steps=steps,
            )
        )

    def request_route_window(
        self,
        steps: list[FollowupStep],
        holds: list[ActionReservation],
        reason: str = "",
        *,
        until: RequestDeadline,
        return_to_source: bool = False,
        on_done: RequestCallback | None = None,
        on_expired: RequestCallback | None = None,
        on_holds_expired: RequestCallback | None = None,
    ) -> None:
        """发布固定路线，并让指定保留持续到同一个窗口结束。"""

        self.request_route(
            steps,
            reason=reason,
            until=until,
            return_to_source=return_to_source,
            on_done=on_done,
            on_expired=on_expired,
        )
        self.reserve_actions(
            holds,
            reason=f"{reason or self.current_char} window reservations",
            until=until,
            on_expired=on_holds_expired,
        )

    def reserve_actions(
        self,
        reservations: list[ActionReservation],
        reason: str = "",
        *,
        until: RequestLifetime,
        on_expired: RequestCallback | None = None,
    ) -> None:
        """发布纯动作保留请求。"""

        if not reservations:
            return
        if until is None:
            raise ValueError("reserve_actions() requires until=callable or until=NEVER_EXPIRES")
        if until is NEVER_EXPIRES and on_expired is not None:
            raise ValueError("reserve_actions(until=NEVER_EXPIRES) cannot use on_expired")
        self._publish_request(
            _ReservationRequest(
                reason=reason or f"{self.current_char} action reservation",
                _source=self.current_char.index,
                until=until,
                on_expired=on_expired,
                reservations=reservations,
            )
        )

    def request_switch(
        self,
        target: "BaseChar",
        reason: str = "",
        until: RequestDeadline | None = None,
        on_done: RequestCallback | None = None,
        on_expired: RequestCallback | None = None,
    ) -> None:
        """请求下一次普通调度优先切给目标角色。

        这是纯切人请求，不要求目标执行指定动作，也不会打断当前角色的动作链。
        strict route、entry reaction、环合反应仍拥有更高优先级；若它们先发生，
        此请求会保留到后续普通调度，直到切到目标或 `until()` 过期。
        """

        if target is None:
            return
        self._publish_request(
            _SwitchRequest(
                reason=reason or f"{self.current_char} requests switch to {target}",
                _source=self.current_char.index,
                until=until,
                on_done=on_done,
                on_expired=on_expired,
                target_index=target.index,
            )
        )

    def request_tags(
        self,
        tags: set[ActionTag],
        count: int = 1,
        reason: str = "",
        until: RequestDeadline | None = None,
        avoid_source: bool = True,
        return_to_source: bool = False,
        on_done: RequestCallback | None = None,
        on_expired: RequestCallback | None = None,
    ) -> None:
        """发布按动作标签寻找队友的通用协作请求。

        这是高级逃生口。普通协作优先使用 `request_route()` 或
        `request_route_window()` 明确指定“谁做什么槽位”；只有当需求确实是
        “任意队友完成某类通用动作”时才使用 tag request。
        """

        if not tags or count <= 0:
            return
        self._publish_request(
            _TagRequest(
                reason=reason or f"{self.current_char} tag request",
                _source=self.current_char.index,
                until=until,
                return_to_source=return_to_source,
                on_done=on_done,
                on_expired=on_expired,
                required_tags=set(tags),
                count=count,
                avoid_source=avoid_source,
            )
        )

    def _publish_request(self, request: _Request | None) -> None:
        """在当前动作执行期间发布新的内部协作请求。"""

        if request is not None:
            self._published_requests.append(request)

    def _consume_published_requests(self) -> list[_Request]:
        """取出并清空本次动作发布的协作请求。"""

        requests = list(self._published_requests)
        self._published_requests.clear()
        return requests
