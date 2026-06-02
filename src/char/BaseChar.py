import time  # noqa
from enum import IntEnum, StrEnum  # noqa
from typing import Any, Union, Optional, List  # noqa

import cv2  # noqa
import numpy as np  # noqa

from ok import Config, Logger, Box  # noqa
from src import text_white_color  # noqa
from src.Labels import Labels
from src.utils import game_filters as gf

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.combat.BaseCombatTask import BaseCombatTask

SKILL_TIME_OUT = 15


class Priority(IntEnum):
    """定义切换角色的优先级枚举。"""

    MIN = -999999999  # 最低优先级
    SWITCH_CD = -1000  # 切换冷却中
    CURRENT_CHAR = -100  # 当前角色
    CURRENT_CHAR_PLUS = CURRENT_CHAR + 1  # 当前角色稍高优先级 (特殊情况)
    SKILL_AVAILABLE = 100  # 有可用技能
    BASE_MINUS_1 = -1
    BASE = 0
    MAX = 9999999999  # 最高优先级
    FAST_SWITCH = MAX - 100  # 快速切换优先级 (例如应对特殊机制)


class Role(StrEnum):
    """定义角色定位枚举。"""

    DEFAULT = "Default"  # 默认/未知定位
    SUB_DPS = "Sub DPS"  # 副输出
    MAIN_DPS = "Main DPS"  # 主输出
    HEALER = "Healer"  # 治疗者


class Element(StrEnum):
    """定义角色元素枚举。"""

    DEFAULT = "Default"  # 默认/未知元素
    BLUE = "Blue"  # 蓝
    GREEN = "Green"  # 绿
    RED = "Red"  # 红
    PURPLE = "Purple"  # 紫
    YELLOW = "Yellow"  # 黄
    WHITE = "White"  # 白


role_values = list(Role)


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
        self.priority = Priority.BASE
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
        self.start_combat = False
        self.confidence = confidence
        self.logger = Logger.get_logger(self.name)
        self.cycle_start_time = 0.0
        self.combo_label = "default"
        self.element = Element.DEFAULT

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
        if self.need_fast_perform():
            self.do_fast_perform()
        else:
            self.do_perform()
        self.logger.debug(f"set current char false {self.index}")
        self.switch_next_char()

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

    def do_perform(self):
        """执行角色的标准战斗行动。"""
        if self.has_intro:
            self.logger.debug("has_intro wait click 1.2 sec")
            self.continues_normal_attack(1.2, click_skill_if_ready_and_return=True)
        self.click_arc()
        self.click_ultimate()
        if self.click_skill()[0]:
            return
        self.continues_normal_attack(0.3)

    def do_fast_perform(self):
        """执行角色的快速战斗行动 (通常在需要快速切换时)。"""
        self.do_perform()

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
        animation_min_duration=0,
        release_check=None,
    ):
        start = time.time()
        result = {
            "clicked": False,
            "action_time": 0,
            "animation_start": 0,
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
                animation_min_duration=animation_min_duration,
                release_check=release_check,
            )
            if status != "continue":
                result["status"] = status
                return result

            if available():
                self.logger.debug(f"{action_type} available click/send")
                if send_click:
                    self.click(action_name=f"{action_type}_click", interval=0.25)
                    self.sleep(0.001, sleep_check=False)
                sent = send_action()
                if sent is not False and not result["clicked"]:
                    result["clicked"] = True
                    result["action_time"] = time.time()

            self.task.next_frame()

    def _check_available_action_result(
        self,
        action_type,
        result,
        start,
        time_out,
        available,
        has_animation=False,
        animation_min_duration=0,
        release_check=None,
    ):
        now = time.time()
        elapsed = now - start
        if elapsed > time_out:
            result["timed_out"] = True
            self.task.in_animation = False
            return "timeout"
        if self.task.in_animation and elapsed > 6:
            self.task.in_animation = False
            return "animation_timeout"
        if has_animation and not self.task.is_in_team():
            self.task.in_animation = True
            result["animation_start"] = result["animation_start"] or now
            return "animation"

        self.check_combat()
        if release_check and release_check():
            return "released"
        if not available() and (not has_animation or elapsed > animation_min_duration):
            self.logger.debug(f"{action_type} not available break")
            return "released" if result["clicked"] else "unavailable"
        return "continue"

    def click_ultimate(self, send_click=True, wait_if_cd_ready=0.1):
        """尝试释放终结技。

        Args:
            send_click (bool, optional): 进入动画后是否发送普通点击。默认为 False。
            wait_if_cd_ready (float, optional): 如果技能冷却即将完成, 等待多少秒。默认为 0。

        Returns:
            bool: 如果成功释放则返回 True。
        """
        if not self.task.use_ultimate:
            return False

        if self.ultimate_available():
            if self.task._combat_settle.time is not None:
                self.logger.info("click_ultimate blocked by combat_detect_settle")
            while self.task._combat_settle.time is not None:
                self.task.next_frame()
                self.check_combat()
                self.click_with_interval()
                self.sleep(0.1)

        self.logger.debug("click_ultimate start")
        if not self.task.in_animation:
            result = self._try_available_action(
                "ultimate",
                self.ultimate_available,
                lambda: self.send_ultimate_key(action_name="ultimate_send", interval=0.25),
                send_click=send_click,
                has_animation=True,
                release_check=lambda: not self.task.is_in_team(),
            )
        else:
            result = {
                "clicked": True,
                "action_time": time.time(),
                "animation_start": 0,
                "status": "animation",
                "timed_out": False,
            }

        return self._finish_ultimate_action(result, send_click, wait_if_cd_ready)

    def _finish_ultimate_action(self, result, send_click, wait_if_cd_ready):
        if result.get("timed_out"):
            self.alert_skill_failed()
            self.task.raise_not_in_combat("too long clicking a ultimate")

        if result["status"] == "animation":
            self.logger.debug("not in_team successfully casted ultimate")
        elif result["clicked"]:
            if self.task.wait_until(
                lambda: not self.task.is_in_team(),
                time_out=0.4,
                post_action=self.click_with_interval,
            ):
                self.task.in_animation = True
                self.logger.debug("not in_team successfully casted ultimate")
            else:
                self.task.in_animation = False
                self.logger.error("clicked ultimate but no effect")
                return False
        elif not self._wait_for_ultimate_ready(wait_if_cd_ready):
            return False

        clicked = result["clicked"]
        start = result["animation_start"] or time.time()
        while not self.task.is_in_team():
            self.task.in_animation = True
            clicked = True
            if send_click:
                self.click(action_name="ultimate_click", interval=0.25)
            if time.time() - start > 7:
                self.task.in_animation = False
                self.task.raise_not_in_combat(
                    "too long a ultimate, the boss was killed by the ultimate"
                )
            self.task.next_frame()

        duration = self._wait_ultimate_unfreeze(start)
        self.task.in_animation = False
        self._ultimate_available = False
        if clicked:
            self.logger.info(f"click_ultimate end {duration}")
        return clicked

    def _wait_for_ultimate_ready(self, wait_if_cd_ready):
        start = time.time()
        while not self.has_cd("ultimate") and time.time() - start < wait_if_cd_ready:
            self.send_ultimate_key(after_sleep=0.05, action_name="ultimate_send", interval=0.25)
            if self.task.wait_until(lambda: not self.task.is_in_team(), time_out=0.1):
                self.task.in_animation = True
                self.logger.debug("not in_team successfully casted ultimate")
                return True
        return self.task.in_animation

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
        duration = time.time() - start - 0.1
        self.add_freeze_duration(start, duration)
        return duration

    def click_skill(
        self,
        down_time=0.01,
        post_sleep=0,
        has_animation=False,
        send_click=True,
        animation_min_duration=0,
        time_out=0,
    ):
        """尝试释放技能。

        Args:
            down_time (float, optional): 按键按下的持续时间。默认为 0.01。
            post_sleep (float, optional): 释放技能后的休眠时间。默认为 0。
            has_animation (bool, optional): 技能是否有释放动画。默认为 False。
            send_click (bool, optional): 在释放技能前是否发送普通点击。默认为 True。
            animation_min_duration (float, optional): 动画的最短持续时间。默认为 0。
            time_out (float, optional): 技能释放的超时时间。默认为 0。
        Returns:
            tuple: (是否成功点击 (bool), 技能持续时间 (float), 是否检测到动画 (bool))。
        """
        self.logger.debug("click_skill start")
        the_time_out = SKILL_TIME_OUT if time_out == 0 else time_out
        result = self._try_available_action(
            "skill",
            self.skill_available,
            lambda: self.send_skill_key(
                down_time=down_time, action_name="skill_send", interval=0.25
            ),
            send_click=send_click,
            time_out=the_time_out,
            has_animation=has_animation,
            animation_min_duration=animation_min_duration,
        )
        if result["timed_out"] and time_out == 0:
            self.alert_skill_failed()
        clicked, duration, animated = self._finish_skill_action(result, post_sleep, has_animation)
        self.logger.debug(
            f"click_skill end clicked {clicked} duration {duration} animated {animated}"
        )
        return clicked, duration, animated

    def _finish_skill_action(self, result, post_sleep=0, has_animation=False):
        clicked = result["clicked"]
        skill_click_time = result["action_time"]
        animation_start = result["animation_start"]
        if animation_start > 0:
            self._wait_skill_animation(animation_start, skill_click_time)
        self.task.in_animation = False
        if clicked:
            self.last_skill_time = skill_click_time
            if has_animation:  # sleep if there will be an animation like Jinhsi
                self.sleep(0.2, sleep_check=False)
            self.sleep(post_sleep)
        duration = time.time() - skill_click_time if skill_click_time != 0 else 0
        if animation_start > 0:
            self.add_freeze_duration(skill_click_time, time.time() - animation_start)
        return clicked, duration, animation_start > 0

    def _wait_skill_animation(self, animation_start, skill_click_time):
        while not self.task.is_in_team():
            self.task.in_animation = True
            if skill_click_time > 0 and time.time() - skill_click_time > 6:
                self.task.in_animation = False
                self.logger.error("skill animation too long, breaking")
                break
            self.task.next_frame()
            self.check_combat()

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

    def get_switch_priority(self, current_char, has_intro):
        """获取切换到此角色的优先级。

        Args:
            current_char (BaseChar): 当前场上角色。
            has_intro (bool): 当前场上角色是否拥有入场技。

        Returns:
            Priority: 优先级数值。
        """
        priority = self.do_get_switch_priority(current_char, has_intro)
        if (
            priority < Priority.MAX
            and self.time_elapsed_accounting_for_freeze(self.last_switch_time) < 0.9
            and not has_intro
        ):
            return Priority.SWITCH_CD
        else:
            return priority

    def do_get_switch_priority(self, current_char, has_intro=False):
        """计算切换到此角色的基础优先级 (不考虑切换CD)。

        Args:
            current_char (BaseChar): 当前场上角色。
            has_intro (bool): 当前场上角色是否拥有入场技。

        Returns:
            int: 优先级数值。
        """
        priority = self.priority
        if self.count_ultimate_priority() and self.ultimate_available():
            priority += self.count_ultimate_priority()
        if self.count_skill_priority() and self.skill_available():
            priority += self.count_skill_priority()
        if priority > self.priority:
            priority += Priority.SKILL_AVAILABLE
        priority += self.count_base_priority()
        return priority

    def count_base_priority(self):
        """计算角色的基础优先级值。"""
        return 0

    def count_ultimate_priority(self):
        """计算终结技技能对切换优先级的贡献值。"""
        return 1

    def count_skill_priority(self):
        """计算技能对切换优先级的贡献值。"""
        return 10

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
        if direction_key is not None:
            self.task.send_key_down(direction_key)
            self.task.next_frame()
        start = time.time()
        while time.time() - start < duration:
            self.click(interval=interval, key="right")
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

    def need_fast_perform(self):
        """判断是否需要执行快速行动序列 (通常为了快速切换给高优先级队友)。

        Returns:
            bool: 如果需要则返回 True。
        """
        current_char = self.task.get_current_char(raise_exception=False)
        for char in self.task.chars:
            if char != current_char:
                if char.need_fast_perform_entry(current_char):
                    self.logger.info(f"In fast perform entry with {char}")
                    return True
                priority = char.do_get_switch_priority(current_char, has_intro=False)
                if priority >= Priority.FAST_SWITCH:
                    self.logger.info(f"In lock with {char}")
                    return True
        return False

    def need_fast_perform_entry(self, current_char) -> bool:
        return False

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

    def wait_switch(self):
        """检查是否要暂缓切人。"""
        return False

    def switch_other_char(self):
        from src.char.Healer import Healer

        target_index = (self.index + 1) % len(self.task.chars)
        for char in self.task.chars:
            if char and isinstance(char, Healer) and char.index != self.index:
                target_index = char.index
                break
        next_char = str(target_index + 1)

        from src.tasks.trigger.AutoCombatTask import AutoCombatTask

        if isinstance(self.task, AutoCombatTask):
            self.logger.debug("AutoCombatTask, skip switch_other_char")
            return
        self.logger.debug(
            f"{self.char_name} on_combat_end {self.index} switch next char: {next_char}"
        )
        start = time.time()
        while time.time() - start < 6:
            self.task.load_chars()
            current_char = self.task.get_current_char(raise_exception=False)
            if current_char and current_char.name != self.name:
                break
            else:
                self.send_key(next_char)
            self.sleep(0.2, sleep_check=False)
        self.logger.debug(f"switch_other_char on_combat_end {self.index} switch end")
