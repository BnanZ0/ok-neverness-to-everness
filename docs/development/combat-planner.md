# Combat Planner 开发指南

> **提示**：角色的具体代码实现可在 [`src/char`](../../src/char) 目录中找到。

Planner 是队伍大脑。角色只声明一个 `CombatPlan`：

- `actions`：planner 可见的动作目录，用于切人评分、route/request/reservation 匹配。
- `claims`：`FieldClaim` 入场诉求，用于表达“我现在应该被切进来”。
- `entry`：普通入场后的 Python generator 动作流。未提供时默认按 `actions` 顺序执行。

公开导入入口固定使用：

```python
from src.combat.planner import ActionSlot, CombatContext, FieldClaim, Planner, RoleProfile
```

`src.combat.planner` 只导出正式开发 API。角色代码不要直接导入
`planner/core.py`、`planner/requests.py`、`planner/state.py` 等内部模块。

## 快速入口

普通角色通常只需要覆盖 `describe_role()` 和 `combat_plan(context)`：

```python
def describe_role(self):
    return RoleProfile(
        role=Planner.Role.SUB_DPS,
        field_preference=Planner.FieldPreference.SUB_DPS,
        max_field_time=1.5,
    )

def combat_plan(self, context: CombatContext):
    return self.plan(
        self.click_ultimate_action(),
        self.click_skill_action(),
    )
```

复杂动作顺序用同一个 plan 里的 action 变量写 entry flow。一个 action 在一次 entry 中只能
执行一次；有限次的额外执行使用 `repeat_for_entry()`：

```python
def combat_plan(self, context: CombatContext):
    skill = self.click_skill_action(reason="skill available")
    ultimate = self.click_ultimate_action(reason="ultimate available")

    def entry():
        skill_result = yield skill
        if skill_result and self.ultimate_available():
            self.sleep(0.6)

        ultimate_result = yield ultimate
        if ultimate_result:
            yield skill.repeat_for_entry()

    return self.plan(skill, ultimate, entry=entry)
```

`yield action` 会把 action 交给 planner 执行。planner 完成 reservation/can_execute
检查、执行、记录 result、推进 request 后，把 `ActionResult` 送回 generator。
`bool(ActionResult)` 等于 `result.success`，所以可以直接写：

```python
a = yield action_a
b = yield action_b

if a and b:
    yield action_c

if a and not b:
    yield fallback_action
```

## CombatPlan

角色通过 `self.plan(*actions, claims=None, entry=None)` 创建 `CombatPlan`：

```python
def combat_plan(self, context):
    setup = self.planner_action(...)
    claims = []
    if self.should_claim_field():
        claims.append(FieldClaim.high(reason="burst window"))

    return self.plan(setup, claims=claims)
```

规则：

- 创建 plan 时只声明动作和入场诉求，不要发送输入。
- 不要在创建 plan 时调用 `context.request_route()`、`reserve_actions()` 或
  `request_tags()`；这些一次性请求应在 action execute 中发布，或在 entry flow
  收到成功 result 后发布。
- `actions` 是评分和协作匹配目录；`entry` 是普通入场执行流程。
- `claims` 可以传多个独立入场理由；它们不会叠加分数，planner 只取当前匹配角色的最高优先级 claim。
- strict route、expected entry、active request 的硬调度优先于普通 entry flow。
- 普通 entry flow 最多执行 `MAX_ACTIONS_PER_ENTRY` 个动作。
- 同一个 action 在同一次入场中只会真实执行一次。

## ActionIntent

`ActionIntent` 表达“角色进场后可以尝试做什么”。不要把一次普攻、等待、连点等
内部细节拆成很多 action；这些应写在一个 action 的 `execute` 内。

字段：

- `tags: set[ActionTag]`：动作意义和评分依据。
- `execute: Callable[[CombatContext], ActionResult | bool | None]`：真正执行动作。
- `name: str = ""`：高级精确匹配和日志名。
- `slot: ActionSlot | None = None`：动作槽位。协作路线和 reservation 优先用 slot 匹配。
- `reason: str = ""`：planner 日志和切人理由。
- `can_execute: Callable[[CombatContext], bool] | None`：planner 层硬限制。
- `priority_ready: Callable[[CombatContext], bool] | None`：只用于切人评分。

`action.repeat_for_entry()` 返回一个可在同一次 entry 中再次 `yield` 的动作副本。
它保留原 action 的执行、slot、标签和 `can_execute` 限制，并为每次调用自动生成独立
的 entry 去重结果。因此它适合 `Q -> E -> 再尝试一次 E` 这类有限 entry flow；副本通常
只在 entry flow 中 yield，不应加入 `CombatPlan.actions`。

每次 `yield` 都会计入单次 entry 的动作上限。不要在需要持续运行的长时间循环中 yield
它；此类循环应在调用已有动作 helper 前，先通过
`context.is_action_allowed(self, action)` 检查完整 action 权限。这样循环保持由角色代码
控制，同时仍遵守 planner 的 `can_execute` 和 reservation 规则。

如果 action 设置了 `slot`，planner 会自动通过 `context.is_slot_available(...)`
检查 reservation。开发者传入的 `can_execute` 只需要表达额外机制限制。需要在 entry
flow 外预查询完整 action 时，使用 `context.is_action_allowed(self, action)`；它同时检查
`can_execute` 和 slot reservation。普通或有限 entry 动作仍直接 `yield action`。

`execute` 返回规则：

- 返回 `True`：成功。
- 返回 `False` / `None` / 没写 `return`：失败。
- 返回 `ActionResult`：使用 `ActionResult.success`。
- 返回 `1`、`"ok"` 这类 truthy 值不会被当成成功。

普通角色不需要手写 `ActionResult`。只有需要自定义 result name/tags/slot/reason
时才手写。

## ActionTag

`ActionTag` 表达动作意义和评分，不能表达某个角色专属机制。

常用标签：

- `ULTIMATE_ACTION`：Q。
- `SKILL_ACTION`：E。
- `ARC_ACTION`：弧盘动作，评分为 0。
- `SUPPORT`：辅助/治疗/增益类动作。
- `COORDINATION`：发布协作路线或窗口的动作。
- `COORDINATION_FINISHER`：协作完成后的收尾动作。
- `FIELD_TIME`：planner 内建站场动作，角色不应自己声明。
- `LEGACY_COMBO`：旧出招表动作。
- `DEFAULT_ACTION`：低价值兜底入口。

切人评分不会累加同一角色所有 action；planner 只挑该角色当前最高分的 ready
action 代表该角色参赛。tag 不控制普通入场流程；普通入场由 `CombatPlan.entry`
控制。

## ActionSlot

`ActionSlot` 是协作匹配用的动作槽位，比 action name 更推荐。

常用槽位：

- `SKILL`：E。
- `ULTIMATE`：Q。
- `ARC`：弧盘。
- `ENTRY_REACTION`：入场/环合反应，不是按键 action。
- `FIELD_TIME`：planner 内建站场。
- `LEGACY_COMBO`：旧出招表。
- `CUSTOM`：特殊动作。

协作和保留尽量写：

```python
FollowupStep.for_action(zero, ActionSlot.SKILL)
ActionReservation.for_action(nanally, ActionSlot.SKILL)
context.is_slot_available(self, ActionSlot.SKILL)
```

## BaseChar Helper

### 开战会话与首次登场

`BaseCombatTask.begin_combat_session()` 是战斗正式开始时的统一入口。它会创建公开的
`task.combat_session`, 调用首切决策并记录实际首发角色; `CombatPlanner` 只负责决定首切
目标, 不执行输入或管理会话。`CombatSession.combat_start` 是本场战斗进入时刻;
`use_ultimate` 与 `switch_enabled` 是本场固定的战斗策略。

`BaseChar.perform()` 开始时会记录本场第一个实际执行战斗逻辑的角色。角色逻辑可用：

```python
if self.is_first_engage():
    # 本场首次实际登场的角色
    ...

if self.consume_first_engage():
    # 全场仅成功一次
    ...
```

`is_first_engage()` 在本场战斗内稳定; `consume_first_engage()` 全场仅返回一次 `True`。
两者都不依赖首切耗时或时间窗口。`task.combat_session` 在首次读取时会创建默认会话;
任务若需要禁止首切和后续切人, 应在调用 `begin_combat_session()` 前设置
`task.combat_session.switch_enabled = False`, 不要在运行期替换切人方法。

### click_ultimate_action

```python
self.click_ultimate_action(
    name=None,
    tags=None,
    reason="ultimate action available",
    can_execute=None,
)
```

- 自动设置 `slot=ActionSlot.ULTIMATE`。
- 默认 `tags={ActionTag.ULTIMATE_ACTION}`。
- 默认 `name=f"{角色名}_ultimate"`。
- `can_execute` 默认包含 `self.ultimate_available()`；传入的额外条件会与之合并。
- `priority_ready` 自动使用 `self.ultimate_available()`。
- `execute` 调用 `self.click_ultimate()`。

### click_skill_action

```python
self.click_skill_action(
    name=None,
    tags=None,
    reason="skill action available",
    down_time=0.01,
    can_execute=None,
)
```

- 自动设置 `slot=ActionSlot.SKILL`。
- 默认 `tags={ActionTag.SKILL_ACTION}`。
- 默认 `name=f"{角色名}_skill"`。
- `can_execute` 默认包含 `self.skill_available()`；传入的额外条件会与之合并。
- `priority_ready` 自动使用 `self.skill_available()`。
- `execute` 调用 `self.click_skill(down_time=down_time)`。

### planner_action

```python
self.planner_action(
    tags={ActionTag.SKILL_ACTION},
    execute=self.some_action,
    name=None,
    slot=None,
    reason="",
    can_execute=None,
    priority_ready=None,
)
```

用于创建自定义 action。长动作应在 `execute` 内完成。

## FieldClaim

`FieldClaim` 表达“我应该被切进来”，不是动作。它只抬高目标角色的普通入场评分；
角色切入后仍由 planner 从 `actions`、strict route/request 或 `entry` 中选择动作。

```python
def combat_plan(self, context):
    claims = []
    if self.has_burst_window():
        claims.append(
            FieldClaim.high(
                reason="burst window active",
                expected_entry=ExpectedEntry(slot=ActionSlot.ULTIMATE),
            )
        )
    return self.plan(self.click_ultimate_action(), claims=claims)
```

使用建议：

- 只是 Q/E 可用，不需要 FieldClaim；action 本身会参与评分。
- 需要“之后抢回场”时用 FieldClaim。
- 抢回场后需要优先做某动作时，加 `expected_entry`。
- 多个 FieldClaim 适合表达多个独立机制入口；planner 不累加 claim 分，只选择最高等级的匹配 claim。

## combat_policies

`combat_policies(context)` 用于随队伍生命周期长期生效的策略。planner reset 当前队伍
时会调用。适合发布常驻 reservation，不适合发布“本次 Q/E 成功后才出现”的临时窗口。

```python
def combat_policies(self, context: CombatContext):
    context.reserve_actions(
        [ActionReservation.for_action(zero, ActionSlot.SKILL)],
        reason="reserve Zero skill",
        until=Planner.NEVER_EXPIRES,
    )
```

## 协作请求

协作请求必须在 action 执行成功后发布，或者在 `combat_policies()` 里发布长期策略。

```python
def combat_plan(self, context):
    setup = self.click_skill_action()

    def entry():
        setup_result = yield setup
        if setup_result:
            context.request_route(
                [FollowupStep.for_action(zero, ActionSlot.SKILL, reason="Zero E")],
                reason="setup route",
            )

    return self.plan(setup, entry=entry)
```

常用 API：

- `context.request_route(...)`：固定顺序协作路线。
- `context.request_switch(...)`：请求下一次普通调度切给某角色。
- `context.request_role(...)`：请求下一次普通调度切给某个队伍定位的角色；多个
  匹配角色时按普通切人评分选择。它不指定动作，也不打断当前 entry flow。
- `context.reserve_actions(...)`：保留队友动作。
- `context.request_tags(...)`：请求一定数量的 tag 动作。

`request_role(Planner.Role.SUPPORT)` 请求的是角色的静态队伍定位；
`request_tags({Planner.ActionTag.SUPPORT})` 请求的是任意支援类动作。前者适合
“让任一辅助角色进场”，后者适合“让任一队友完成一次治疗/增益动作”。

```python
context.request_role(Planner.Role.SUPPORT, reason="need a support role")
```

## 行为摘要

- 切人评分与普通 entry 执行分离。
- 评分使用 `actions` 中最高分 ready action，再叠加 `FieldClaim`、request 和站场偏好分。
- 当前角色普通入场执行由 `entry` 控制；未写 entry 时按 `actions` 顺序执行。
- `priority_ready=False` 只降低切人吸引力，不是硬阻止。
- `can_execute=False` 是硬阻止；被阻止的 entry action 会得到失败 result，不会真实执行。
- strict route、expected entry、active request 优先于普通 entry flow。
- `ActionResult.tags` 不控制 entry flow。
