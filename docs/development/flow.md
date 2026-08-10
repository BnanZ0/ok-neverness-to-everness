# Flow 作者指南

`Flow` 是任务的反应式场景监督器。它在中断、节点动作失败和未知画面后重新观察屏幕, 不恢复旧调用栈。

它不负责业务点击、路线规划或跨任务页面导航。节点 action 继续使用任务原有的 `wait_until`、`wait_click_confirm` 和输入 helper。

## 最小接入

`BaseNTETask` 已为每个 Task 单例创建 `self.flow`, 刷新帧, 注册月卡中断, 并让 Flow 运行期间的 `wait_until()` 自动成为安全点。任务只需要声明自己的场景:

```python
class Node(Enum):
    READY = "ready"
    RESULT = "result"
    TEAM = "team"

def _configure_flow(self):
    self.flow.node(Node.RESULT, self.has_result, self._on_result)
    self.flow.node(Node.READY, self.is_ready, self._on_ready)
    self.flow.node(Node.TEAM, self.is_in_team, self._enter_task)
    self.flow.fallback(self._press_escape_for_recovery, timeout=360)
```

在任务入口中运行它:

```python
completed = self.flow.loop(
    lambda: self._session.is_finished,
    on_error=self._handle_flow_error,
    poll_interval=0.1,
)
```

## 节点 action 契约

- detector 必须是无副作用的当前画面判断。优先级只用于 detector 同时命中时的消歧, 默认按注册顺序。
- action 可能在画面持续可见时重复执行。它必须幂等, 或使用已有的 `interval` / `wait_until` 节流, 不能假定每次 action 都会立刻切换页面。
- action 的返回值不参与转移判断; Flow 只根据下一次画面检测决定下一步。
- 可恢复的业务失败抛出既有异常, 通常是 `WaitFailedException`。Flow 刷新画面后先检查原节点: 原节点仍在才交给 `on_error`; 原节点消失就直接重新分类。
- 自定义高频循环中调用 `self.flow.safe_point()`。它发现中断会抛出 `FlowReplan`; 如 action 需要记录本轮状态, 记录后必须继续抛出它。

```python
try:
    self._control_until_finished()
except FlowReplan:
    session.interrupted_control_round = session.round_index
    raise
```

不要在任务代码中调用 Flow 的内部中断检查。普通等待已经自动检查; 自定义循环只使用 `safe_point()`。

## 中断与恢复语义

- 中断 handler 返回非 `False` 表示已处理。Flow 丢弃旧调用栈, 先观察原节点。
- 原节点在中断后暂时未匹配时, Flow 最多等待 3 秒; 期间重新匹配则继续原节点, 超时后才全量分类。
- handler 返回 `False` 表示处理失败。Flow 不会继续旧 action, 而是立即执行 fallback, 不会重复执行该 handler 后才恢复。
- 允许 handler 返回 `False` 的 Flow 必须注册 fallback; 否则 `loop()` 会失败而不是冒险继续旧 action。
- 未识别画面会先容忍 5 秒; 之后反复执行 fallback; 达到任务配置的 fallback timeout 才失败。
- `TaskDisabledException` 是控制流, 会直接离开 Flow, 不会被恢复逻辑吞掉。
