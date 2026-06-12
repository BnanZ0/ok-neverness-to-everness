from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Callable, Iterable

if TYPE_CHECKING:
    from src.char.BaseChar import BaseChar

    from .context import CombatContext


class Role(StrEnum):
    """角色战斗定位。

    `RoleProfile.role` 使用此枚举描述角色的大方向；实际站场偏好由
    `FieldPreference` 进一步控制。
    """

    SUB_DPS = "Sub DPS"
    MAIN_DPS = "Main DPS"
    SUPPORT = "Support"


class ActionTag(StrEnum):
    """动作意义标签。

    `ActionIntent.tags` 使用这些标签让 `CombatPlanner` 进行通用评分。
    标签只表达“动作价值和性质”，不要用它描述某个角色的专属机制。
    同一个 action 的 tags 是 set，重复标签不会重复加分。
    """

    DEFAULT_ACTION = "default_action"
    DAMAGE = "damage"
    ULTIMATE_ACTION = "ultimate_action"
    ARC_ACTION = "arc_action"
    SUPPORT = "support"
    COORDINATION = "coordination"
    SKILL_ACTION = "skill_action"
    FIELD_TIME = "field_time"
    LEGACY_COMBO = "legacy_combo"
    COORDINATION_FINISHER = "coordination_finisher"


class EntryChainPolicy(StrEnum):
    """动作执行后，本次入场是否继续尝试后续动作。"""

    CONTINUE = "continue"
    STOP_ON_SUCCESS = "stop_on_success"
    STOP = "stop"


class ActionSlot(StrEnum):
    """游戏动作槽位。

    `FollowupStep` 和 `ActionReservation` 优先使用槽位协调队友动作，
    例如请求某角色释放 `SKILL`，而不是依赖具体 action name 字符串。
    """

    SKILL = "skill"
    ULTIMATE = "ultimate"
    ARC = "arc"
    ENTRY_REACTION = "entry_reaction"
    FIELD_TIME = "field_time"
    LEGACY_COMBO = "legacy_combo"
    CUSTOM = "custom"


class FieldPreference(StrEnum):
    """Planner 用于站场评分的角色偏好。

    `RoleProfile.field_preference` 使用此枚举决定没有协作请求时谁更该站场。
    """

    MAIN_DPS = "main_dps"
    SUB_DPS = "sub_dps"
    SUPPORT = "support"
    SETUP_ONLY = "setup_only"


class FieldClaimLevel(StrEnum):
    """角色请求入场的强度等级。

    `FieldClaim` 使用此枚举表达“这次入场诉求有多强”。具体机制原因放在
    `FieldClaim.reason` 中，避免等级名称绑定某个角色机制。
    """

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


ACTION_TAG_SCORES = {
    ActionTag.DEFAULT_ACTION: 10,
    ActionTag.DAMAGE: 35,
    ActionTag.ULTIMATE_ACTION: 200,
    ActionTag.ARC_ACTION: 0,
    ActionTag.SUPPORT: 45,
    ActionTag.COORDINATION: 80,
    ActionTag.SKILL_ACTION: 75,
    ActionTag.FIELD_TIME: 40,
    ActionTag.LEGACY_COMBO: 45,
    ActionTag.COORDINATION_FINISHER: 160,
}


FIELD_CLAIM_SCORES = {
    FieldClaimLevel.LOW: 120,
    FieldClaimLevel.NORMAL: 240,
    FieldClaimLevel.HIGH: 420,
    FieldClaimLevel.CRITICAL: 700,
}


class _NeverExpires:
    """`reserve_actions(until=NEVER_EXPIRES)` 使用的永久生命周期 sentinel。"""

    def __repr__(self) -> str:
        return "NEVER_EXPIRES"


NEVER_EXPIRES = _NeverExpires()


@dataclass(slots=True)
class RoleProfile:
    """角色向 `CombatPlanner` 声明的基础战斗画像。

    由角色的 `describe_role()` 返回。`max_field_time` 会被 planner 用来生成
    内建的 `planner_field_time` 站场动作。

    `combat_start_priority` 只用于开战首切。大于 0 的角色会成为首切候选；
    数值越高越优先。普通战斗中的切人评分不会使用此字段。
    """

    role: Role = Role.SUB_DPS
    field_preference: FieldPreference = FieldPreference.SUB_DPS
    max_field_time: float = 1.5
    combat_start_priority: int = 0


@dataclass(slots=True)
class FieldClaim:
    """角色向 planner 声明“我应该被切进来”的理由。

    `FieldClaim` 不代表动作，也不替代 `ActionIntent`。它只抬高目标角色
    的普通入场评分；角色切入后仍由 planner 从 `ActionIntent` 中选择要执行的动作。
    """

    _source: int = -1
    level: FieldClaimLevel = FieldClaimLevel.NORMAL
    reason: str = ""
    expected_entry: "ExpectedEntry | None" = None

    @classmethod
    def low(
        cls,
        source: "BaseChar | str | None" = None,
        reason: str = "",
        expected_entry: "ExpectedEntry | None" = None,
    ) -> "FieldClaim":
        """声明低强度入场诉求。"""

        return cls._from_source(source, FieldClaimLevel.LOW, reason, expected_entry)

    @classmethod
    def normal(
        cls,
        source: "BaseChar | str | None" = None,
        reason: str = "",
        expected_entry: "ExpectedEntry | None" = None,
    ) -> "FieldClaim":
        """声明普通强度入场诉求。"""

        return cls._from_source(source, FieldClaimLevel.NORMAL, reason, expected_entry)

    @classmethod
    def high(
        cls,
        source: "BaseChar | str | None" = None,
        reason: str = "",
        expected_entry: "ExpectedEntry | None" = None,
    ) -> "FieldClaim":
        """声明高强度入场诉求。"""

        return cls._from_source(source, FieldClaimLevel.HIGH, reason, expected_entry)

    @classmethod
    def critical(
        cls,
        source: "BaseChar | str | None" = None,
        reason: str = "",
        expected_entry: "ExpectedEntry | None" = None,
    ) -> "FieldClaim":
        """声明最高强度入场诉求。"""

        return cls._from_source(source, FieldClaimLevel.CRITICAL, reason, expected_entry)

    @classmethod
    def _from_source(
        cls,
        source: "BaseChar | str | None",
        level: FieldClaimLevel,
        reason: str = "",
        expected_entry: "ExpectedEntry | None" = None,
    ) -> "FieldClaim":
        if isinstance(source, str) and not reason:
            reason = source
            source = None
        source_char = source
        source_id = source_char.index if source_char is not None else -1
        if source_char is not None and not reason:
            reason = cls.default_reason(source_char, level)
        return cls(
            _source=source_id,
            level=level,
            reason=reason,
            expected_entry=expected_entry,
        )

    @staticmethod
    def default_reason(source: "BaseChar", level: FieldClaimLevel) -> str:
        return f"{source} uses FieldClaim {level.value}"

    def ensure_source(self, char: "BaseChar") -> None:
        """如果 claim 未声明来源，使用当前发布 claim 的角色作为来源。"""

        if self._source < 0:
            self._source = char.index
        if not self.reason:
            self.reason = self.default_reason(char, self.level)

    def matches_char(self, char: "BaseChar") -> bool:
        """判断此 claim 是否属于目标角色。"""

        return char.index == self._source


@dataclass(slots=True)
class SwitchInGuard:
    """目标角色切入前的保护条件。

    由即将被切入的角色声明“现在是否适合让我进场”。这避免当前角色替目标角色
    判断入场时机，也让 guard 的语义稳定为“延迟目标入场”，而不是“阻止当前切出”。
    """

    delay_until: Callable[[], bool] | None = None
    timeout: float = 0.0
    reason: str = ""
    poll_interval: float = 0.05
    while_waiting: Callable[[], None] | None = None

    @classmethod
    def allow(cls) -> "SwitchInGuard":
        """允许立即切入。"""

        return cls()

    @classmethod
    def delay_until_ready(
        cls,
        condition: Callable[[], bool],
        timeout: float,
        reason: str = "",
        poll_interval: float = 0.05,
        while_waiting: Callable[[], None] | None = None,
    ) -> "SwitchInGuard":
        """延迟切入直到 `condition()` 为 True 或 timeout 到期。"""

        return cls(
            delay_until=condition,
            timeout=timeout,
            reason=reason,
            poll_interval=poll_interval,
            while_waiting=while_waiting,
        )

    def should_delay(self) -> bool:
        """返回当前是否仍需要延迟切入。"""

        return self.delay_until is not None and not self.delay_until()


@dataclass(slots=True)
class ActionResult:
    """一次动作执行后的标准结果。"""

    name: str = ""
    success: bool = True
    tags: set[ActionTag] = field(default_factory=set)
    slot: ActionSlot | None = None
    reason: str = ""


ActionExecutor = Callable[["CombatContext"], ActionResult | bool | None]
ActionPredicate = Callable[["CombatContext"], bool]


@dataclass(slots=True)
class ActionIntent:
    """角色声明给 `CombatPlanner` 的候选动作。"""

    tags: set[ActionTag]
    execute: ActionExecutor
    name: str = ""
    slot: ActionSlot | None = None
    reason: str = ""
    can_execute: ActionPredicate | None = None
    priority_ready: ActionPredicate | None = None
    chain_policy: EntryChainPolicy = EntryChainPolicy.CONTINUE

    def identity_key(self) -> str:
        """返回 planner 内部使用的动作身份。"""

        if self.name:
            return f"name:{self.name}"
        if self.slot is not None:
            if self.reason:
                return f"slot:{self.slot}|reason:{self.reason}"
            return f"slot:{self.slot}"
        tag_key = ",".join(sorted(str(tag) for tag in self.tags))
        return f"tags:{tag_key}|reason:{self.reason}"

    def display_name(self) -> str:
        """返回仅用于日志的人类可读动作名。"""

        if self.name:
            return self.name
        if self.slot is not None:
            return f"<{self.slot.value}>"
        if self.reason:
            return f"<{self.reason}>"
        return "<anonymous_action>"

    def is_allowed(self, context: "CombatContext") -> bool:
        """返回 planner 层是否允许该动作执行。"""

        if self.can_execute is None:
            return True
        return self.can_execute(context)

    def is_priority_ready(self, context: "CombatContext") -> bool:
        """返回该动作当前是否值得参与评分和切人。"""

        if not self.is_allowed(context):
            return False
        if self.priority_ready is None:
            return True
        return self.priority_ready(context)

    def run(self, context: "CombatContext") -> ActionResult:
        """执行动作并标准化为 `ActionResult`。"""

        result = self.execute(context)
        if isinstance(result, ActionResult):
            if not result.name and self.name:
                result.name = self.name
            if not result.tags:
                result.tags.update(self.tags)
            if result.slot is None:
                result.slot = self.slot
            action_result = result
        else:
            action_result = ActionResult(
                name=self.name,
                success=result is True,
                tags=set(self.tags),
                slot=self.slot,
            )
        return action_result


CombatIntent = ActionIntent | FieldClaim


def _display_result_name(result: ActionResult) -> str:
    if result.name:
        return result.name
    if result.slot is not None:
        return f"<{result.slot.value}>"
    if result.reason:
        return f"<{result.reason}>"
    return "<anonymous_action>"


@dataclass(slots=True)
class FollowupStep:
    """`CombatContext.request_route()` 中的一步协作要求。"""

    reason: str
    slot: ActionSlot | None = None
    required_tags: set[ActionTag] = field(default_factory=set)
    action_names: set[str] = field(default_factory=set)
    target_indices: set[int] = field(default_factory=set)
    target_names: set[str] = field(default_factory=set)
    requires_entry_reaction: bool = False
    optional: bool = False

    @classmethod
    def for_action(
        cls,
        target: "BaseChar",
        slot: ActionSlot,
        reason: str = "",
        optional: bool = False,
        required_tags: set[ActionTag] | None = None,
        action_names: set[str] | None = None,
    ) -> "FollowupStep":
        """创建“指定角色执行指定槽位动作”的 strict route 步骤。"""

        return cls(
            reason=reason or f"{target} {slot} followup",
            slot=slot,
            required_tags=required_tags or set(),
            action_names=action_names or set(),
            target_indices={target.index},
            optional=optional,
        )

    @classmethod
    def for_entry_reaction(
        cls,
        target: "BaseChar",
        reason: str = "",
    ) -> "FollowupStep":
        """创建“切入目标角色触发入场/环合反应”的 strict route 步骤。"""

        return cls(
            reason=reason or f"{target} entry reaction followup",
            slot=ActionSlot.ENTRY_REACTION,
            target_indices={target.index},
            requires_entry_reaction=True,
        )

    def matches_char(self, char: "BaseChar") -> bool:
        """判断角色是否符合此步骤的目标条件。"""

        if self.target_indices and char.index not in self.target_indices:
            return False
        if self.target_names:
            names = {char.name, str(getattr(char, "char_name", ""))}
            if not self.target_names.intersection(names):
                return False
        return True

    def wants(self, char: "BaseChar", action: ActionIntent | ActionResult) -> bool:
        """判断某角色动作是否满足此步骤。"""

        if self.requires_entry_reaction:
            return False
        if not self.matches_char(char):
            return False
        if self.action_names and action.name not in self.action_names:
            return False
        if self.slot is not None and action.slot != self.slot:
            return False
        if self.required_tags and not self.required_tags.intersection(action.tags):
            return False
        return bool(self.action_names or self.slot is not None or self.required_tags)

    def wants_entry_reaction(self, source_char: "BaseChar", target_char: "BaseChar") -> bool:
        """判断一次入场/环合反应是否满足此步骤。"""

        if not self.requires_entry_reaction:
            return False
        return self.matches_char(target_char)


@dataclass(slots=True)
class ActionReservation:
    """planner 层的动作保留。"""

    slots: set[ActionSlot]
    target_indices: set[int] = field(default_factory=set)
    target_names: set[str] = field(default_factory=set)

    @classmethod
    def for_action(
        cls,
        target: "BaseChar",
        slot: ActionSlot,
    ) -> "ActionReservation":
        """创建单一目标角色、单一动作槽位的保留。"""

        return cls(slots={slot}, target_indices={target.index})

    @classmethod
    def for_slots(
        cls,
        target: "BaseChar",
        slots: Iterable[ActionSlot],
    ) -> "ActionReservation":
        """创建单一目标角色、多个动作槽位的保留。"""

        return cls(slots=set(slots), target_indices={target.index})

    def matches_char(self, char: "BaseChar") -> bool:
        """判断角色是否是此保留的目标。"""

        if self.target_indices and char.index not in self.target_indices:
            return False
        if self.target_names:
            names = {char.name, str(getattr(char, "char_name", ""))}
            if not self.target_names.intersection(names):
                return False
        return True

    def reserves_action(self, char: "BaseChar", action: ActionIntent | ActionResult) -> bool:
        """判断此保留是否会阻止某角色动作。"""

        if not self.matches_char(char):
            return False
        return action.slot in self.slots


@dataclass(slots=True)
class SwitchDecision:
    """planner 的切人决策结果。

    `CombatPlanner.decide_switch()` 返回此类型，调用方根据 `target` 执行切人，
    并可用 `expected_entry` 记录切入后优先尝试的动作。
    """

    target: "BaseChar"
    reason: str
    priority: int
    has_intro: bool = False
    expected_entry: "ExpectedEntry | None" = None
    score_breakdown: str = ""


@dataclass(slots=True)
class ExpectedEntry:
    """切入目标角色后应优先尝试的动作期望。

    普通切人评分不会设置 expected entry；strict route 这类硬调度才会设置。
    """

    slot: ActionSlot | None = None
    action_name: str = ""

    @classmethod
    def from_action(cls, action: ActionIntent) -> "ExpectedEntry":
        """从 `ActionIntent` 创建切入期望。"""

        return cls(slot=action.slot, action_name=action.name)

    def matches(self, action: ActionIntent) -> bool:
        """判断动作是否符合此切入期望。"""

        if self.action_name and action.name != self.action_name:
            return False
        if self.slot is not None and action.slot != self.slot:
            return False
        return bool(self.action_name or self.slot is not None)
