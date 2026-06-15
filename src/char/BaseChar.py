import time
from enum import StrEnum
from typing import TYPE_CHECKING, Callable

from ok import Logger

from src import text_white_color
from src.combat.planner import (
    ActionExecutor,
    ActionIntent,
    ActionPredicate,
    ActionSlot,
    ActionTag,
    CombatContext,
    EntryChainPolicy,
    FieldClaim,
    FieldPreference,
    Role,
    RoleProfile,
    SwitchInGuard,
)
from src.Labels import Labels
from src.utils import game_filters as gf

if TYPE_CHECKING:
    from src.combat.BaseCombatTask import BaseCombatTask

SKILL_TIME_OUT = 15


class Element(StrEnum):
    """定义角色元素枚举。"""

    DEFAULT = "Default"  # 默认/未知元素
    BLUE = "Blue"  # 蓝
    GREEN = "Green"  # 绿
    RED = "Red"  # 红
    PURPLE = "Purple"  # 紫
    YELLOW = "Yellow"  # 黄
    WHITE = "White"  # 白


class BaseChar:
    """角色基类，定义了游戏角色的通用属性和行为。"""

    INTRO_MOTION_FREEZE_DURATION = 1.5

    def __init__(self, task, index, char_name=None, confidence=1):
        """初始化角色基础属性。

        Args:
            task (BaseCombatTask): 所属的战斗任务对象。
            index (int): 角色在队伍中的索引 (0, 1, 2)。
            char_name (str, optional): 角色名称。默认为 None。
        """
        self.task: "BaseCombatTask" = task
        self.char_name = char_name
        self.builtin_key = None
        self.index = index
        self.last_switch_time = -1
        self.last_ultimate = -1
        self.has_intro = False
        self.is_current_char = False
        self._ultimate_available = False
        self._skill_available = False
        self.last_perform = 0
        self.last_skill_time = -1
        self.last_outro_time = -1
        self.confidence = confidence
        self.logger = Logger.get_logger(self.name)
        self.cycle_start_time = 0.0
        self.combo_label = "default"
        self.element = Element.DEFAULT
        self.planner_handles_arc = False

    def cycle_start(self):
        self.cycle_start_time = time.time()

    def cycle_sleep(self, duration=0.1):
        to_sleep = duration - (time.time() - self.cycle_start_time)
        if to_sleep > 0.05:
            self.check_combat()
        self.sleep(duration - (time.time() - self.cycle_start_time))

    def skip_combat_check(self):
        """是否在某些操作中跳过战斗状态检查。

        Returns:
            bool: 如果跳过则返回 True。
        """
        return False

    @property
    def name(self):
        """获取角色类名作为其名称。

        Returns:
            str: 角色类名字符串。
        """
        return f"{self.__class__.__name__}"

    def __eq__(self, other):
        """比较两个角色对象是否相同 (基于名称和索引)。"""
        if isinstance(other, BaseChar):
            return self.name == other.name and self.index == other.index
        return False

    def perform(self):
        """执行当前角色的主要战斗行动序列。"""
        self.last_perform = time.time()
        if self.has_intro:
            self.add_intro_motion_freeze(self.last_perform)
            self.wait_intro()
        self._try_default_arc_click()

        self.task.combat_planner.perform_current_char(self)
        self.logger.debug(f"set current char false {self.index}")
        self.task.refresh_cd()
        self.switch_next_char()

    def _try_default_arc_click(self):
        if not self.planner_handles_arc:
            self.click_arc()

    def add_intro_motion_freeze(self, start):
        self.add_freeze_duration(start, self.INTRO_MOTION_FREEZE_DURATION, freeze_time=-100)

    def wait_intro(self, time_out=-1, click=True):
        """等待角色入场动画结束。

        Args:
            time_out (float, optional): 等待超时时间 (秒)。默认为 1.2。
            click (bool, optional): 等待期间是否持续点击。默认为 True。
        """
        if time_out < 0:
            time_out = self.INTRO_MOTION_FREEZE_DURATION

        if self.has_intro:
            self.logger.info(f"wait intro {time_out}s")
            if click:
                self.continues_normal_attack(time_out)
            else:
                self.sleep(time_out)
            self.logger.info("wait intro end")

    def click_with_interval(self, interval=0.1):
        """以指定间隔执行点击操作。

        Args:
            interval (float, optional): 点击间隔。默认为 0.1。
        """
        self.click(interval=interval)

    @property
    def click(self):
        """执行一次点击操作 (代理到 task.click)。"""
        return self.task.click

    @property
    def send_key(self):
        """发送按键 (代理到 task.send_key)。"""
        return self.task.send_key

    def describe_role(self):
        return RoleProfile(role=Role.SUB_DPS, field_preference=FieldPreference.SUB_DPS)

    def switch_in_guard(
        self,
        context: CombatContext,
        from_char: "BaseChar",
        has_intro: bool,
    ) -> SwitchInGuard:
        """声明当前角色是否允许被切入。

        默认立即允许。特殊角色若需要等自身状态或前置动作稳定后再进场，可返回
        `SwitchInGuard.delay_until_ready(...)`。
        """

        return SwitchInGuard.allow()

    def combat_intents(self, context: CombatContext) -> list[ActionIntent | FieldClaim]:
        """声明角色交给 planner 的战斗意图。

        一个入口同时返回 `ActionIntent` 和 `FieldClaim`。前者表达“进场后做什么”，
        后者表达“为什么应该被切进来”。

        规则:
            - 这里只声明动作和入场诉求，不要调用 `context.request_route()`、
              `reserve_actions()` 或 `request_tags()`。
            - 普通进场会按这里的声明顺序尝试 allowed action。
            - 切人评分会从该角色 ready actions 中挑最高分 action 代表角色参赛。

        Args:
            context: planner 上下文，仅用于查询，不应用来发布一次性请求。

        Returns:
            `ActionIntent` / `FieldClaim` 列表。可用 `self.intents(...)` 过滤 None。
        """

        return self.intents(
            self.click_ultimate_action("base_ultimate"),
            self.click_skill_action("base_skill"),
        )

    def combat_policies(self, context: CombatContext) -> None:
        """声明随队伍生命周期生效的 planner 策略。

        这里适合发布常驻 reservation 这类长期策略。普通角色通常不需要覆盖。
        `combat_intents()` 应保持为动作/入场诉求声明，不要在评分扫描时发布请求。

        planner reset 当前队伍后会调用此方法。适合发布由队伍组成决定的长期规则，
        不适合发布“本次 Q/E 成功后才出现”的临时窗口。

        Args:
            context: 可用于 `reserve_actions()` 等长期策略发布。
        """

        return None

    def intents(self, *intents) -> list[ActionIntent | FieldClaim]:
        """过滤空意图并返回列表。

        用法:
            return self.intents(action_or_none, claim_or_none)
        """

        return [intent for intent in intents if intent is not None]

    def click_arc_action(
        self,
        name: str | None = None,
        tags: set[ActionTag] | None = None,
        reason: str = "arc action available",
        can_execute=None,
        priority_ready: ActionPredicate | None = None,
        after_execute: Callable[[CombatContext, bool], bool | None] | None = None,
        chain_policy: EntryChainPolicy = EntryChainPolicy.CONTINUE,
    ):
        """创建一个 弧盘 动作声明。

        Args:
            name: 动作名。默认 `"{角色名}_arc"`，用于日志和高级精确匹配。
            tags: 动作标签。默认 `{ActionTag.ARC_ACTION}`。
            reason: 切人/执行日志理由。
            can_execute: 额外硬限制；slot reservation 由 planner 统一检查。
            priority_ready: 只用于切人评分。默认永远不因为 arc 主动切人。
            after_execute: 执行成功后的回调，(context, is_current) -> bool，返回 True 表示
                           可以立即进入下一个 allowed action。
            chain_policy: 该 action 之后是否允许执行下一个 allowed action。

        Returns:
            `ActionIntent`。
        """

        name = name or f"{self.__str__()}_arc"
        action_tags = tags or {ActionTag.ARC_ACTION}

        return self.planner_action(
            tags=action_tags,
            slot=ActionSlot.ARC,
            execute=lambda context: self._execute_click_action(
                context,
                click=lambda: self.click_arc(),
                after_execute=after_execute,
            ),
            name=name,
            reason=reason,
            can_execute=can_execute,
            priority_ready=priority_ready or (lambda _: False),
            chain_policy=chain_policy,
        )

    def click_ultimate_action(
        self,
        name: str | None = None,
        tags: set[ActionTag] | None = None,
        reason: str = "ultimate action available",
        can_execute=None,
        after_execute: Callable[[CombatContext, bool], bool | None] | None = None,
        chain_policy: EntryChainPolicy = EntryChainPolicy.CONTINUE,
    ):
        """创建一个 Q 动作声明。

        Args:
            name: 动作名。默认 `"{角色名}_ultimate"`，用于日志和高级精确匹配。
            tags: 动作标签。默认 `{ActionTag.ULTIMATE_ACTION}`。
            reason: 切人/执行日志理由。
            can_execute: 额外硬限制；slot reservation 由 planner 统一检查。
            after_execute: Q 点击后执行的角色内后处理，参数为 `(context, success)`。
                返回 bool 时会覆盖动作最终成功状态；返回 None 时保留点击结果。
            chain_policy: 动作结束后是否继续本次入场。

        Behavior:
            - 自动设置 `slot=ActionSlot.ULTIMATE`。
            - `priority_ready` 自动使用 `self.ultimate_available()`。
            - `execute` 调用 `self.click_ultimate()`。
            - `click_ultimate()` 后调用 `after_execute(context, success)`。
            - planner 会自动用 `slot=ULTIMATE` 检查 reservation。
        """

        name = name or f"{self.__str__()}_ultimate"
        action_tags = tags or {ActionTag.ULTIMATE_ACTION}

        return self.planner_action(
            tags=action_tags,
            slot=ActionSlot.ULTIMATE,
            execute=lambda context: self._execute_click_action(
                context,
                click=lambda: self.click_ultimate(),
                after_execute=after_execute,
            ),
            name=name,
            reason=reason,
            can_execute=can_execute,
            priority_ready=lambda _: self.ultimate_available(),
            chain_policy=chain_policy,
        )

    def click_skill_action(
        self,
        name: str | None = None,
        tags: set[ActionTag] | None = None,
        reason: str = "skill action available",
        down_time: float = 0.01,
        can_execute=None,
        after_execute: Callable[[CombatContext, bool], bool | None] | None = None,
        chain_policy: EntryChainPolicy = EntryChainPolicy.CONTINUE,
    ):
        """创建一个 E 动作声明。

        Args:
            name: 动作名。默认 `"{角色名}_skill"`，用于日志和高级精确匹配。
            tags: 动作标签。默认 `{ActionTag.SKILL_ACTION}`。
            reason: 切人/执行日志理由。
            down_time: 传给 `click_skill(down_time=...)` 的按下时间。
            can_execute: 额外硬限制；slot reservation 由 planner 统一检查。
            after_execute: E 点击后执行的角色内后处理，参数为 `(context, success)`。
                返回 bool 时会覆盖动作最终成功状态；返回 None 时保留点击结果。
            chain_policy: 动作结束后是否继续本次入场。

        Behavior:
            - 自动设置 `slot=ActionSlot.SKILL`。
            - `priority_ready` 自动使用 `self.skill_available()`。
            - `execute` 调用 `self.click_skill(...)`。
            - `click_skill()` 后调用 `after_execute(context, success)`。
            - planner 会自动用 `slot=SKILL` 检查 reservation。
        """

        name = name or f"{self.__str__()}_skill"
        action_tags = tags or {ActionTag.SKILL_ACTION}

        return self.planner_action(
            tags=action_tags,
            slot=ActionSlot.SKILL,
            execute=lambda context: self._execute_click_action(
                context,
                click=lambda: self.click_skill(down_time=down_time),
                after_execute=after_execute,
            ),
            name=name,
            reason=reason,
            can_execute=can_execute,
            priority_ready=lambda _: self.skill_available(),
            chain_policy=chain_policy,
        )

    def _execute_click_action(
        self,
        context: CombatContext,
        click: Callable[[], bool],
        after_execute: Callable[[CombatContext, bool], bool | None] | None = None,
    ):
        success = click()
        if after_execute is not None:
            override = after_execute(context, success)
            if isinstance(override, bool):
                return override
        return success

    def planner_action(
        self,
        tags: set[ActionTag] | ActionTag,
        execute: ActionExecutor,
        name: str | None = None,
        slot: ActionSlot | None = None,
        reason: str = "",
        can_execute: ActionPredicate | None = None,
        priority_ready: ActionPredicate | None = None,
        chain_policy: EntryChainPolicy = EntryChainPolicy.CONTINUE,
    ):
        """创建一个交给 `CombatPlanner` 调度的动作声明。

        `name` 是高级精确匹配用的动作名；普通自定义动作不传时保持空字串。
        动作真正执行多久由 `execute` 自己负责；长时间动作应在 `execute` 内完成。

        Args:
            tags: 动作标签集合。推荐写 `{ActionTag.X}`；传单个 tag 时会被包装成 set。
            execute: 接收 `CombatContext` 的执行函数。只有严格返回 True 才算成功；
                False/None/无 return 都算失败。可手写返回 `ActionResult`。
            name: 高级动作名和日志名。普通动作可以不传。
            slot: 动作槽位。需要被 route/reservation 匹配时应设置。
            reason: 日志和切人理由。
            can_execute: 额外 planner 层硬限制；False 时不执行也不评分。
            priority_ready: 只用于切人评分；False 不代表已在场时不能尝试。
            chain_policy: 动作结束后是否继续本次入场。

        Returns:
            `ActionIntent`。

        Note:
            只要 `slot` 不为 None，`CombatPlanner` 会自动检查 reservation。
            开发者传入的 `can_execute` 只表达额外机制限制，不需要重复写
            `context.can_execute_action(...)`。
        """

        if not isinstance(tags, set):
            tags = {tags}

        return ActionIntent(
            name=name or "",
            tags=tags,
            slot=slot,
            execute=execute,
            reason=reason,
            can_execute=can_execute,
            priority_ready=priority_ready,
            chain_policy=chain_policy,
        )

    def has_cd(self, box_name):
        """检查指定技能是否在冷却中 (代理到 task.has_cd)。

        Args:
            box_name (str): 技能UI区域名称。

        Returns:
            bool: 如果在冷却则返回 True。
        """
        return self.task.has_cd(box_name)

    def is_available(self, percent, box_name):
        """判断技能是否可用 (基于UI百分比和冷却状态)。

        Args:
            percent (float): 技能UI白色像素百分比。
            box_name (str): 技能UI区域名称。

        Returns:
            bool: 如果可用则返回 True。
        """
        return percent == 0 or not self.has_cd(box_name)

    def switch_out(self):
        """角色被切换下场时的状态更新。"""
        self.last_switch_time = time.time()
        self.is_current_char = False
        self.has_intro = False

    def __repr__(self):
        """返回角色类名作为其字符串表示。"""
        return self.__class__.__name__

    def switch_next_char(self, post_action=None, free_intro=False):
        """切换到下一个角色 (代理到 task.switch_next_char)。

        Args:
            post_action (callable, optional): 切换后执行的动作。默认为 None。
            free_intro (bool, optional): 是否强制认为拥有入场技。默认为 False。
        """
        self.has_intro = False
        self._ultimate_available = self.ultimate_available()
        self.task.switch_next_char(self, post_action=post_action, free_intro=free_intro)

    def sleep(self, sec, sleep_check=True):
        try:
            if not sleep_check:
                self.task.skip_sleep_check = True
            self.task.sleep(sec)
        finally:
            self.task.skip_sleep_check = False

    def alert_skill_failed(self):
        self.task.log_error(
            "Click skill failed, check if the keybinding is correct in ok-ww settings!", notify=True
        )
        self.task.screenshot("click_skill too long, breaking")

    def _try_available_action(
        self,
        action_type,
        available,
        send_action,
        send_click=True,
        time_out=SKILL_TIME_OUT,
        has_animation=False,
    ):
        start = time.time()
        result = {
            "clicked": False,
            "action_time": 0,
            "animation_start": 0,
            "animation_pending_start": 0,
            "status": "unavailable",
            "timed_out": False,
        }

        while True:
            status = self._check_available_action_result(
                action_type,
                result,
                start,
                time_out,
                available,
                has_animation=has_animation,
            )
            if status != "continue":
                result["status"] = status
                return result

            if available():
                self.logger.debug(f"{action_type} available click/send")
                action_time = time.time()
                sent = send_action()
                if send_click:
                    self.sleep(0.001, sleep_check=False)
                    self.click(action_name=f"{action_type}_click", interval=0.5)
                if sent is not False:
                    result["clicked"] = True
                    result["action_time"] = action_time

            self.sleep(0.01)

    def _check_available_action_result(
        self,
        action_type,
        result,
        start,
        time_out,
        available,
        has_animation=False,
    ):
        now = time.time()
        elapsed = now - start

        if elapsed > time_out:
            result["timed_out"] = True
            return "timeout"

        if has_animation:
            if not self.task.is_in_team():
                if result["animation_start"] == 0:
                    self.task.in_animation = True
                    result["animation_start"] = result["action_time"] or now

                return "animation"
            elif result["animation_start"] != 0:
                self.task.in_animation = False
                result["animation_start"] = 0

        if self.task.is_in_team() and not available():
            waiting_for_animation = (
                has_animation and result["clicked"] and result["animation_start"] == 0
            )
            if waiting_for_animation:
                result["animation_pending_start"] = result["animation_pending_start"] or now
                if now - result["animation_pending_start"] < 0.5:
                    return "continue"
            self.logger.debug(f"{action_type} not available break")
            return "released" if result["clicked"] else "unavailable"
        result["animation_pending_start"] = 0
        return "continue"

    def click_ultimate(self, send_click=True, wait_if_no_cd=0):
        """尝试释放终结技。

        Args:
            send_click (bool, optional): 进入动画后是否发送普通点击。默认为 False。
            wait_if_no_cd (float, optional): 如果技能冷却已完成, 等待多少秒。默认为 0。

        Returns:
            bool: 如果成功释放则返回 True。
        """
        if not self.task.use_ultimate:
            return False

        if self.ultimate_available():
            if self.task.combat_detect_uncertain:
                self.logger.info("click_ultimate blocked by combat_detect_uncertain")
            while self.task.combat_detect_uncertain:
                self.click_with_interval()
                self.sleep(0.1)
        else:
            self._wait_for_ultimate_ready(wait_if_no_cd)

        self.logger.debug("click_ultimate start")
        if not self.task.in_animation:
            result = self._try_available_action(
                "ultimate",
                self.ultimate_available,
                lambda: self.send_ultimate_key(action_name="ultimate_send", interval=0.2),
                send_click=send_click,
                has_animation=True,
            )
        else:
            result = {
                "clicked": True,
                "action_time": time.time(),
                "animation_start": 0,
                "status": "animation",
                "timed_out": False,
            }

        return self._finish_ultimate_action(result, send_click)

    def _finish_ultimate_action(self, result, send_click):
        if result.get("timed_out"):
            self.alert_skill_failed()
            self.task.raise_not_in_combat("too long clicking a ultimate")

        if result["status"] == "animation":
            self.logger.debug("not in_team successfully casted ultimate")
        elif not result["clicked"]:
            return False
        elif result["status"] != "animation":
            self.logger.error("clicked ultimate but no effect")
            return False

        clicked = result["clicked"]
        start = result["animation_start"] or time.time()
        ultimate_animation_click = (
            (lambda: self.click(action_name="ultimate_click", interval=0.25))
            if send_click
            else None
        )
        animated = self._wait_action_animation(
            start=start,
            timeout=7,
            on_wait=ultimate_animation_click,
        )
        clicked = clicked or animated

        duration = self._wait_ultimate_unfreeze(start)
        self._ultimate_available = False
        if clicked:
            self.logger.info(f"click_ultimate end {duration}")
        return clicked

    def _wait_for_ultimate_ready(self, wait_if_no_cd):
        deadline = time.time() + wait_if_no_cd
        while not self.has_cd("ultimate") and time.time() < deadline:
            self.sleep(0.1)

    def _wait_ultimate_unfreeze(self, start):
        self.logger.debug("waiting for time unfrozen")
        self.task.wait_until(
            lambda: self.has_cd("ultimate"), post_action=self.click_with_interval, time_out=2
        )
        box_ultimate = self.task.get_box_by_name(Labels.box_ultimate)
        snapshot = box_ultimate.crop_frame(self.task.frame)
        processed_snapshot = gf.isolate_cd_to_black(snapshot)

        def condition():
            if not self.task.find_one(
                Labels.box_ultimate,
                template=processed_snapshot,
                box=box_ultimate,
                frame_processor=gf.isolate_cd_to_black,
                threshold=0.7,
            ):
                self.logger.info("ultimate unfreeze cause cd changed")
                return True
            elif not self.available("ultimate", check_cd=False):
                self.logger.info("ultimate unfreeze cause ultimate not available")
                return True

        self.task.wait_until(
            condition,
            time_out=10,
            post_action=self.click_with_interval,
        )
        duration = time.time() - start
        self.add_freeze_duration(start, duration)
        return duration

    def click_skill(
        self,
        down_time=0.01,
        post_sleep=0,
        has_animation=False,
        send_click=True,
        time_out=0,
    ):
        """尝试释放技能。

        Args:
            down_time (float, optional): 按键按下的持续时间。默认为 0.01。
            post_sleep (float, optional): 释放技能后的休眠时间。默认为 0。
            has_animation (bool, optional): 技能是否有释放动画。默认为 False。
            send_click (bool, optional): 在释放技能前是否发送普通点击。默认为 True。
            time_out (float, optional): 技能释放的超时时间。默认为 0。
        Returns:
            bool: 是否成功点击。
        """
        self.logger.debug("click_skill start")
        the_time_out = SKILL_TIME_OUT if time_out == 0 else time_out
        result = self._try_available_action(
            "skill",
            self.skill_available,
            lambda: self.send_skill_key(
                down_time=down_time, action_name="skill_send", interval=0.2
            ),
            send_click=send_click,
            time_out=the_time_out,
            has_animation=has_animation,
        )
        if result["timed_out"] and time_out == 0:
            self.alert_skill_failed()
        clicked, duration, animated = self._finish_skill_action(result, post_sleep)
        self.logger.debug(
            f"click_skill end clicked {clicked} duration {duration} animated {animated}"
        )
        return clicked

    def _finish_skill_action(self, result, post_sleep=0):
        clicked = result["clicked"]
        skill_click_time = result["action_time"]
        animation_start = result["animation_start"]
        if animation_start > 0:
            self._wait_action_animation(
                start=animation_start,
                timeout=6,
            )
            self.add_freeze_duration(animation_start, time.time() - animation_start)
        if clicked:
            self.last_skill_time = skill_click_time
            self.sleep(post_sleep)
        duration = time.time() - skill_click_time if skill_click_time != 0 else 0
        return clicked, duration, animation_start > 0

    def _wait_action_animation(
        self,
        start,
        timeout,
        on_wait=None,
    ):
        animated = False
        timeout_start = start
        try:
            while not self.task.is_in_team():
                self.task.in_animation = True
                animated = True
                if on_wait is not None:
                    on_wait()
                if timeout_start > 0 and time.time() - timeout_start > timeout:
                    self.task.raise_not_in_combat("animation too long")
                self.sleep(0.005, sleep_check=False)
        finally:
            self.task.in_animation = False
        return animated

    def click_arc(self):
        self.send_arc_key()
        return True

    def send_skill_key(self, after_sleep=0, interval=-1, down_time=0.01, action_name=None):
        """发送技能按键。

        Args:
            after_sleep (float, optional): 发送后的休眠时间。默认为 0。
            interval (float, optional): 按键按下和释放的间隔。默认为 -1 (使用默认值)。
            down_time (float, optional): 按键按下的持续时间。默认为 0.01。
        """
        self._skill_available = False
        return self.send_key(
            self.get_skill_key(),
            interval=interval,
            down_time=down_time,
            after_sleep=after_sleep,
            action_name=action_name,
        )

    def send_arc_key(self, after_sleep=0, interval=-1, down_time=0.01):
        """发送弧盘技能的按键。

        Args:
            after_sleep (float, optional): 发送后的休眠时间。默认为 0。
            interval (float, optional): 按键按下和释放的间隔。默认为 -1 (使用默认值)。
            down_time (float, optional): 按键按下的持续时间。默认为 0.01。
        """
        self.send_key(
            self.get_arc_key(), interval=interval, down_time=down_time, after_sleep=after_sleep
        )

    def send_ultimate_key(self, after_sleep=0, interval=-1, down_time=0.01, action_name=None):
        """发送终结技按键。

        Args:
            after_sleep (float, optional): 发送后的休眠时间。默认为 0。
            interval (float, optional): 按键按下和释放的间隔。默认为 -1 (使用默认值)。
            down_time (float, optional): 按键按下的持续时间。默认为 0.01。
        """
        self._ultimate_available = False
        return self.send_key(
            self.get_ultimate_key(),
            interval=interval,
            down_time=down_time,
            after_sleep=after_sleep,
            action_name=action_name,
        )

    def check_combat(self):
        """检查战斗状态 (代理到 task.check_combat)。"""
        self.task.check_combat()

    def reset_state(self):
        """重置角色的战斗相关状态 (如入场技标记)。"""
        self.has_intro = False
        self._ultimate_available = False
        self._skill_available = False

    def on_combat_end(self, chars):
        """当战斗结束时, 角色可能需要执行的特定清理逻辑。

        Args:
            chars (list[BaseChar]): 队伍中所有角色的列表。
        """
        pass

    @property
    def add_freeze_duration(self):
        """添加冻结持续时间 (代理到 task.add_freeze_duration)。"""
        return self.task.add_freeze_duration

    @property
    def time_elapsed_accounting_for_freeze(self):
        """计算扣除冻结时间后经过的时间 (代理到 task.time_elapsed_accounting_for_freeze)。"""
        return self.task.time_elapsed_accounting_for_freeze

    def get_ultimate_key(self):
        """获取终结技按键 (代理到 task.get_ultimate_key)。"""
        return self.task.get_ultimate_key()

    def get_skill_key(self):
        """获取技能按键 (代理到 task.get_skill_key)。"""
        return self.task.get_skill_key()

    def get_arc_key(self):
        """获取弧盘技能按键 (代理到 task.get_arc_key)。"""
        return self.task.get_arc_key()

    def skill_available(self, check_color=True):
        """判断技能是否可用。

        Args:
            check_color (bool, optional): 是否检查技能UI颜色(是否点亮)。默认为 True。

        Returns:
            bool: 如果可用则返回 True。
        """
        return self.available("skill", check_color=check_color)

    def available(self, box, check_color=True, check_cd=True):
        if self.is_current_char:
            return self.task.available(box, check_color=check_color, check_cd=check_cd)
        else:
            if box == "ultimate":
                return self.task.ultimate_available(self.index)
            return not self.task.has_cd(box, self.index)

    def is_cycle_full(self):
        """判断当前环合是否已满 (代理到 task.is_cycle_full)。"""
        return self.task.is_cycle_full()

    def ultimate_available(self, check_color=True):
        """判断终结技是否可用。

        Returns:
            bool: 如果可用则返回 True。
        """
        return self.available("ultimate", check_color=check_color)

    def __str__(self):
        """返回角色类名作为其字符串表示。"""
        return self.__repr__()

    def normal_attack_until_can_switch(self):
        """普通攻击直到可以切人。"""
        self.click()
        while self.time_elapsed_accounting_for_freeze(self.last_perform) < 1.1:
            self.click(interval=0.1)

    def wait_switch_cd(self):
        since_last_switch = self.time_elapsed_accounting_for_freeze(self.last_perform)
        if since_last_switch < 1:
            self.logger.debug(f"wait_switch_cd {since_last_switch}")
            self.continues_normal_attack(1 - since_last_switch)

    def continues_normal_attack(
        self,
        duration: float,
        interval: float = 0.1,
        after_sleep: float = 0,
        click_skill_if_ready_and_return: bool = False,
        until_cycle_full: bool = False,
    ):
        """持续进行普通攻击一段时间。

        Args:
            duration (float): 持续时间 (秒)。
            interval (float, optional): 每次攻击的间隔时间。默认为 0.1。
            click_skill_if_ready_and_return (bool, optional): 如果技能可用,
                是否立即释放并返回。默认为 False。
            until_cycle_full (bool, optional): 是否持续攻击直到协奏值满。默认为 False。
        """
        start = time.time()
        while time.time() - start < duration:
            if click_skill_if_ready_and_return and self.skill_available():
                return self.click_skill()
            # if until_cycle_full and self.is_cycle_full():
            #     return
            self.click()
            self.sleep(interval)
        self.sleep(after_sleep)

    def continues_click(self, key, duration, interval=0.1):
        """持续发送指定按键一段时间。

        Args:
            key (str): 要发送的按键。
            duration (float): 持续时间 (秒)。
            interval (float, optional): 每次发送按键的间隔。默认为 0.1。
        """
        start = time.time()
        while time.time() - start < duration:
            self.send_key(key, interval=interval)

    def continues_right_click(self, duration, interval=0.1, direction_key=None):
        """持续进行鼠标右键点击操作一段时间，可选同时按住方向键。

        Args:
            duration (float): 持续时间 (秒)。
            interval (float, optional): 每次发送按键的间隔。默认为 0.1。
            direction_key (str, optional): 如果指定，则在点击期间同时按下此键
                （如 'w'、'a'、's'、'd'）。
        """
        try:
            if direction_key is not None:
                self.task.send_key_down(direction_key)
                self.sleep(0.1)
            start = time.time()
            while time.time() - start < duration:
                self.click(interval=interval, key="right")
        finally:
            if direction_key is not None:
                self.task.send_key_up(direction_key)

    def normal_attack(self):
        """执行一次普通攻击。"""
        self.logger.debug("normal attack")
        self.check_combat()
        self.click()

    def heavy_attack(self, duration=0.6):
        """执行一次重攻击。

        Args:
            duration (float, optional): 重攻击按键按下的持续时间。默认为 0.6。
        """
        self.check_combat()
        self.logger.debug("heavy attack start")
        try:
            self.task.mouse_down()
            self.sleep(duration)
        finally:
            self.task.mouse_up()
        self.sleep(0.01)
        self.logger.debug("heavy attack end")

    def current_skill(self):
        """获取当前技能UI白色像素百分比。"""
        return self.task.calculate_color_percentage(
            text_white_color, self.task.get_box_by_name("box_skill")
        )

    def current_ultimate(self):
        """获取当前终结技UI白色像素百分比。"""
        return self.task.calculate_color_percentage(
            text_white_color, self.task.get_box_by_name("box_ultimate")
        )

    def check_outro(self):
        """协奏入场时判断延奏来源

        Returns:
            string:非协奏入场返回'null'，否则范围角色名如'char_sanhua'
        """
        if not self.has_intro:
            return "null"
        time = 0
        outro = "null"
        for char in self.task.chars:
            if char == self:
                continue
            elif char.last_switch_time > time:
                time = char.last_switch_time
                outro = char.char_name
        self.logger.info(f"erned outro from {outro}")
        return outro

    def is_first_engage(self):
        """判断角色是否为触发战斗时的登场角色。"""
        result = 0 <= self.last_perform - self.task.combat_start < 0.1
        if result:
            self.logger.info("first engage")
        return result
