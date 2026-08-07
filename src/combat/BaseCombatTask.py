import re
import time
from bisect import bisect_right
from contextlib import contextmanager
from dataclasses import dataclass, fields
from enum import Enum

import cv2
import numpy as np
from ok import Box, Logger, safe_get

from src import text_white_color
from src.char.BaseChar import BaseChar, Element
from src.char.core.CharFactory import (
    get_char_by_id,
    get_char_by_pos,
    get_char_feature_by_pos,
)
from src.char.custom.CustomCharManager import CustomCharManager
from src.combat.CombatCheck import CombatCheck
from src.combat.planner import CombatPlanner
from src.Labels import Labels
from src.sound_trigger.SoundCombatContext import ACTION_UNSET, SoundCombatContext
from src.tasks.mixin.CharUIMixin import CharElementUIMixin
from src.utils import game_filters as gf
from src.utils import image_utils as iu

logger = Logger.get_logger(__name__)
cd_regex = re.compile(r"\d{1,2}\.\d")


class NotInCombatException(Exception):
    """未处于战斗状态异常。"""

    pass


@dataclass
class SleepCheckSkip:
    sound_combat_context: bool = False
    check_combat: bool = False

    @property
    def all(self) -> bool:
        return all(getattr(self, field.name) for field in fields(self))

    @all.setter
    def all(self, value: bool):
        for field in fields(self):
            setattr(self, field.name, value)


class TeamSurvivalStatus(Enum):
    NO_DEATHS = 1  # 无人死亡
    DEAD = 2  # 死亡
    WIPED = 3  # 团灭


@dataclass(frozen=True)
class VisibleTeamMatch:
    """A complete, unique mapping from the visible HUD slots to one preset."""

    preset_id: str
    preset_name: str
    char_ids: tuple[str, ...]
    slots: tuple[dict, ...]


@dataclass
class CombatSession:
    """一次实际战斗的生命周期状态。"""

    combat_start: float
    switch_enabled: bool = True
    use_ultimate: bool = True
    start_char: "BaseChar | None" = None
    first_engage_char: "BaseChar | None" = None
    first_engage_consumed: bool = False
    last_active_at: float = 0.0
    pause_logged: bool = False


class BaseCombatTask(CharElementUIMixin, CombatCheck):
    """基础战斗任务类，封装了游戏"鸣潮"中角色自动化操作的通用逻辑。"""

    hot_key_verified = False  # 热键是否已验证
    FREEZE_DURATION_RETENTION_SECONDS = 20 * 60
    STRICT_TEAM_MATCH_THRESHOLD = 0.65
    TEAM_BINDING_CHECK_INTERVAL = 0.25
    PARTIAL_RECOGNITION_RETRIES = 4
    PARTIAL_RECOGNITION_RETRY_INTERVAL = 0.18
    LIVE_BINDING_RETRIES = 3
    LIVE_BINDING_RETRY_INTERVAL = 0.12
    ABYSS_SESSION_GAP_TIMEOUT = 6.0
    ABYSS_PRESET_IDS = frozenset(
        {
            "team_baicang_speed",
            "team_chiz",
            "team_999night",
        }
    )

    element_reactions = (
        "创生",
        "覆纹",
        "浊燃",
        "黯星",
        "浸染",
        "延滞",
    )

    element_ring = (
        Element.WHITE,
        Element.GREEN,
        Element.RED,
        Element.PURPLE,
        Element.BLUE,
        Element.YELLOW,
    )
    element_ring_index = {element: index for index, element in enumerate(element_ring)}

    def __init__(self, *args, **kwargs):
        """初始化战斗任务。

        Args:
            *args: 传递给父类的参数。
            **kwargs: 传递给父类的关键字参数。
        """
        super().__init__(*args, **kwargs)
        self.sleep_check_skip = SleepCheckSkip()
        self.sleep_check_interval = 0.1
        self.chars: list[BaseChar] = []
        self.mouse_pos = None  # 当前鼠标位置
        self._combat_session: CombatSession | None = None

        self.add_text_fix({"Ｅ": "e"})
        self.vibrate_chars_index: list[int] = []
        self.chars_slot_mat = [None, None, None, None]
        self.element_reaction_counts = {}
        self._strict_team_last_error = ""
        self.active_team_preset_id = ""
        self._team_binding: VisibleTeamMatch | None = None
        self._pending_team_binding: VisibleTeamMatch | None = None
        self._team_binding_last_check = 0.0
        self._team_binding_blocked = False
        self.combat_planner = CombatPlanner(self)
        self.clear_element_reactions()
        self.preheat_element_template_cache_async()
        CustomCharManager().preheat_feature_cache_async()

    @property
    def combat_session(self) -> CombatSession:
        """返回当前战斗会话, 必要时按默认策略创建。"""

        if self._combat_session is None:
            self._combat_session = CombatSession(combat_start=time.time())
        return self._combat_session

    @combat_session.setter
    def combat_session(self, value: CombatSession | None) -> None:
        self._combat_session = value

    def begin_combat_session(self) -> CombatSession:
        """初始化本场战斗, 执行一次首切并记录实际首发角色。

        此方法是战斗开始阶段唯一的副作用入口。首发角色已记录时直接复用。
        """

        session = self.combat_session
        session.last_active_at = time.monotonic()
        session.pause_logged = False
        if session.start_char is None:
            session.combat_start = time.time()
            self.click()
            self.switch_to_combat_start_char()
            session.start_char = self.get_current_char(raise_exception=False)
            logger.info(f"combat session started, start char: {session.start_char}")
        return session

    def touch_combat_session(self) -> None:
        """Refresh the activity clock without rebuilding the session."""

        session = getattr(self, "_combat_session", None)
        if session is None:
            return
        session.last_active_at = time.monotonic()
        session.pause_logged = False

    def can_preserve_combat_session(self) -> bool:
        """Return whether a short target/HUD gap may reuse the live Abyss plan."""

        session = getattr(self, "_combat_session", None)
        if session is None or session.start_char is None:
            return False
        if not self.should_hold_position_on_target_loss():
            return False
        if getattr(self, "_team_binding_blocked", False):
            return False
        if getattr(self, "_pending_team_binding", None) is not None:
            return False
        last_active_at = session.last_active_at or time.monotonic()
        return time.monotonic() - last_active_at <= self.ABYSS_SESSION_GAP_TIMEOUT

    def note_combat_session_pause(self) -> None:
        """Record a transient Abyss gap once, keeping planner state untouched."""

        session = getattr(self, "_combat_session", None)
        if session is None or session.pause_logged:
            return
        session.pause_logged = True
        logger.info(
            "combat session paused for short Abyss gap; preserving bound team, "
            "character objects and planner state"
        )

    def record_first_engage(self, char: "BaseChar") -> None:
        """记录本场首次实际执行战斗逻辑的角色。"""

        session = self.combat_session
        if session.first_engage_char is None:
            session.first_engage_char = char
            logger.info(f"combat first engage: {char}")

    def is_first_engage(self, char: "BaseChar") -> bool:
        """返回角色是否为本场第一个实际执行战斗逻辑的角色。"""

        return self.combat_session.first_engage_char is char

    def consume_first_engage(self, char: "BaseChar") -> bool:
        """仅在本场首次登场角色首次消费时返回 ``True``。"""

        session = self.combat_session
        if session.first_engage_consumed or session.first_engage_char is not char:
            return False
        session.first_engage_consumed = True
        return True

    @property
    def team_size(self):
        """获取当前队伍人数。

        Returns:
            int: 当前队伍中的角色数量。
        """
        return len(self.chars)

    def get_next_char_index(self):
        """获取下一个角色的索引。

        Returns:
            int: 下一个角色的索引。
        """
        current_index = self.get_current_char().index
        next_index = (current_index + 1) % len(self.chars)
        return next_index

    def get_longest_idle_char_index(self) -> int:
        """获取最久没有登场角色的索引。

        Returns:
            int: 角色的索引。如果没有角色，返回 -1。
        """
        if not self.chars:
            return -1
        min_time = float("inf")
        min_index = -1
        for char in self.chars:
            if char.last_switch_time < min_time:
                min_time = char.last_switch_time
                min_index = char.index
        return min_index

    def _get_element_ring_pair(self, element_a: Element, element_b: Element):
        index_a = self.element_ring_index.get(element_a)
        index_b = self.element_ring_index.get(element_b)
        if index_a is None or index_b is None or index_a == index_b:
            return None
        ring_size = len(self.element_ring)
        if (index_a + 1) % ring_size == index_b:
            return element_a, element_b
        if (index_b + 1) % ring_size == index_a:
            return element_b, element_a
        return None

    def clear_element_reactions(self):
        self.element_reaction_counts = {
            (self.element_ring[i], self.element_ring[(i + 1) % len(self.element_ring)]): 0
            for i in range(len(self.element_ring))
        }
        self._update_element_reaction_info()

    def _update_element_reaction_info(self):
        if not self.debug:
            return
        reaction_info = []
        for index, reaction_name in enumerate(self.element_reactions):
            pair = (
                self.element_ring[index],
                self.element_ring[(index + 1) % len(self.element_ring)],
            )
            count = self.element_reaction_counts.get(pair, 0)
            if count > 0:
                reaction_info.append(f"{reaction_name}: {count}")
        self.info_set("环合反应", reaction_info)

    def record_element_reaction(self, char_a: "BaseChar", char_b: "BaseChar") -> bool:
        if char_a is None or char_b is None:
            return False
        pair = self._get_element_ring_pair(char_a.element, char_b.element)
        if pair is None:
            return False
        self.element_reaction_counts[pair] = self.element_reaction_counts.get(pair, 0) + 1

        self._update_element_reaction_info()
        return True

    def find_element_reaction_target(self, source_char: "BaseChar") -> "BaseChar | None":
        if source_char is None:
            return None
        source_element_index = self.element_ring_index.get(source_char.element)
        if source_element_index is None:
            return None

        ring_size = len(self.element_ring)
        previous_element = self.element_ring[(source_element_index - 1) % ring_size]
        next_element = self.element_ring[(source_element_index + 1) % ring_size]

        previous_target = None
        next_target = None
        for char in self.chars:
            if char is None or char.index == source_char.index:
                continue
            if char.element == previous_element and (
                previous_target is None or char.last_switch_time < previous_target.last_switch_time
            ):
                previous_target = char
            elif char.element == next_element and (
                next_target is None or char.last_switch_time < next_target.last_switch_time
            ):
                next_target = char

        if previous_target is None:
            return next_target
        if next_target is None:
            return previous_target

        previous_pair = self._get_element_ring_pair(source_char.element, previous_target.element)
        next_pair = self._get_element_ring_pair(source_char.element, next_target.element)
        previous_count = self.element_reaction_counts.get(previous_pair, 0)
        next_count = self.element_reaction_counts.get(next_pair, 0)
        if previous_count <= next_count:
            return previous_target
        return next_target

    def add_freeze_duration(self, start, duration=-1.0, freeze_time=0.1):
        """添加冻结持续时间。用于精确计算技能冷却等。

        Args:
            start (float): 冻结开始时间。
            duration (float, optional): 冻结持续时间。如果为-1.0, 则根据当前时间计算。默认为 -1.0。
            freeze_time (float, optional): 认为发生冻结的最小持续时间。默认为 0.1。
        """
        if duration < 0:
            duration = time.time() - start
        if start > 0 and duration > freeze_time:
            current_time = time.time()
            while (
                self.freeze_durations
                and self.freeze_durations[0][0]
                <= current_time - self.FREEZE_DURATION_RETENTION_SECONDS
            ):
                self.freeze_durations.popleft()
            freeze_duration = (start, duration, freeze_time)
            if not self.freeze_durations or start >= self.freeze_durations[-1][0]:
                self.freeze_durations.append(freeze_duration)
                return

            records = list(self.freeze_durations)
            insert_at = bisect_right(records, start, key=lambda item: item[0])
            records.insert(insert_at, freeze_duration)
            self.freeze_durations.clear()
            self.freeze_durations.extend(records)

    def time_elapsed_accounting_for_freeze(self, start, intro_motion_freeze=False):
        """计算扣除冻结时间后经过的时间。

        Args:
            start (float): 开始时间戳。
            intro_motion_freeze (bool, optional): 是否考虑角色入场动画的特殊冻结。默认为 False。

        Returns:
            float: 扣除冻结后实际经过的时间 (秒)。
        """
        if start < 0:
            return 10000
        to_minus = 0
        for freeze_start, duration, freeze_time in reversed(self.freeze_durations):
            if freeze_start <= start:
                break
            if intro_motion_freeze:
                if freeze_time == -100:
                    freeze_time = 0
            elif freeze_time == -100:
                continue
            if duration < freeze_time:
                duration = freeze_time
            to_minus += duration
        if to_minus != 0:
            self.log_debug_gated(f"time_elapsed_accounting_for_freeze to_minus {to_minus}")
        return time.time() - start - to_minus

    def refresh_cd(self):
        if self.scene.cd_refreshed:
            return
        index = self.get_current_char().index
        cds = self.cds.get(index)
        if cds is None:
            cds = {}
            self.cds[index] = cds
        # Preserve previous CD values when OCR fails to read them.
        # Instead of resetting to 0 (which falsely reports "available"),
        # decay the last known CD by elapsed time so remaining CD stays accurate.
        old_time = cds.get("time")
        new_time = time.time()
        if old_time is not None:
            elapsed = self.time_elapsed_accounting_for_freeze(old_time)
            cds["skill"] = max(0, cds.get("skill", 0) - elapsed)
            cds["ultimate"] = max(0, cds.get("ultimate", 0) - elapsed)
        else:
            cds["skill"] = 0
            cds["ultimate"] = 0
        cds["time"] = new_time
        texts = self.ocr(
            0.8594, 0.8847, 0.9578, 0.9139, frame_processor=gf.isolate_cd_to_black, match=cd_regex
        )
        for text in texts:
            cd = convert_cd(text)
            if text.x < self.width_of_screen(0.89):
                cds["skill"] = cd
            elif text.x > self.width_of_screen(0.925):
                cds["ultimate"] = cd
        self.scene.cd_refreshed = True
        # self.log_debug(f"cd refreshed: {cds} {time.time() - cds['time']}")

    def get_cd(self, box_name, char_index=None):
        self.refresh_cd()
        if char_index is None:
            char_index = self.get_current_char().index
        if cds := self.cds.get(char_index):
            time_elapsed = self.time_elapsed_accounting_for_freeze(cds["time"])
            return cds[box_name] - time_elapsed
        else:
            return 0

    def revive_action(self):
        # TODO: 復活邏輯
        pass

    def raise_not_in_combat(self, message, exception_type=None):
        """抛出未在战斗状态的异常。

        Args:
            message (str): 异常信息。
            exception_type (Exception, optional): 要抛出的异常类型。默认为 NotInCombatException。
        """
        logger.warning(message)
        if exception_type is None:
            exception_type = NotInCombatException
        raise exception_type(message)

    def available(self, name, check_color=True, check_cd=True):
        """检查指定名称的技能或动作是否可用 (通过颜色百分比和冷却时间判断)。

        Args:
            name (str): 技能或动作的名称 (例如 'skill', 'ultimate')。

        Returns:
            bool: 如果可用则返回 True, 否则 False。
        """
        if check_color:
            current = self.box_highlighted(name)
        else:
            current = 1
        if current > 0 and (not check_cd or not self.has_cd(name)):
            return True

    def box_highlighted(self, name):
        current = self.calculate_color_percentage(
            text_white_color, self.get_box_by_name(f"box_{name}")
        )
        if current > 0:
            current = 1
        else:
            current = 0
        return current

    def combat_once(
        self,
        wait_combat_time=200,
        max_combat_time=1200,
        raise_if_not_found=True,
        retarget_turn=True,
    ):
        """执行一次完整的战斗流程。

        Args:
            wait_combat_time (int, optional): 等待进入战斗状态的超时时间 (秒)。默认为 200。
            raise_if_not_found (bool, optional): 如果未找到战斗状态是否抛出异常。默认为 True。
        """
        self.wait_until(
            self.in_combat, time_out=wait_combat_time, raise_if_not_found=raise_if_not_found
        )
        try:
            self.begin_combat_session()
            self.info["Combat Count"] = self.info.get("Combat Count", 0) + 1
            with self.retarget_turn_policy(enable=retarget_turn):
                deadline = time.time() + max_combat_time
                while self.in_combat():
                    logger.debug(f"combat_once loop {self.chars}")
                    self.get_current_char(raise_exception=True).perform()
                    if time.time() > deadline:
                        self.raise_not_in_combat(
                            f"Combat maximum duration of {max_combat_time}s reached."
                        )
        except NotInCombatException as e:
            logger.info(f"combat_once out of combat break {e}")
        finally:
            team_status = (
                TeamSurvivalStatus.DEAD
                if any(char is not None and char.is_dead for char in self.chars)
                else TeamSurvivalStatus.NO_DEATHS
            )
            if self.can_preserve_combat_session():
                self.note_combat_session_pause()
            else:
                self.combat_end()

        if not self.wait_in_team(time_out=5, raise_if_not_found=False):
            team_status = TeamSurvivalStatus.WIPED

        return team_status

    def _decide_switch_to(
        self,
        current_char: "BaseChar",
        free_intro=False,
        require_intro=False,
    ):
        decision = self.combat_planner.decide_switch(
            current_char,
            free_intro=free_intro,
            require_intro=require_intro,
        )
        return decision.target, decision.has_intro

    def _wait_switch_in_guard(
        self,
        current_char: "BaseChar",
        switch_to: "BaseChar",
        has_intro: bool,
    ) -> None:
        guard = self.combat_planner.switch_in_guard(current_char, switch_to, has_intro)
        if not guard.should_delay():
            return

        start_time = time.time()
        reason = guard.reason or f"{switch_to} switch in guard"
        logger.info(f"switch in delayed: {reason}")
        while guard.should_delay() and time.time() - start_time < guard.timeout:
            self.check_combat()
            if guard.while_waiting is None:
                current_char.click_with_interval()
            else:
                guard.while_waiting()
            self.sleep(max(guard.poll_interval, 0.01))

        if guard.should_delay():
            logger.warning(
                f"switch in guard timeout after {time.time() - start_time:.2f}s: {reason}"
            )
        else:
            logger.info(f"switch in guard released after {time.time() - start_time:.2f}s: {reason}")

    def _set_current_char(self, current_char: "BaseChar | None", switch_to: "BaseChar", has_intro):
        self.in_animation = False
        if current_char:
            current_char.switch_out()
            if has_intro:
                current_char.last_outro_time = time.time()
        # switch_in updates actual_switch_in_time (only on real switch-in),
        # is_current_char, has_intro. actual_switch_in_time is the basis for
        # MIN_FIELD_TIME / MAX_FIELD_TIME windows and must not be reset by perform.
        switch_to.switch_in(has_intro=has_intro)

    def _switch_to_char(
        self,
        switch_to: "BaseChar",
        current_char: "BaseChar | None" = None,
        has_intro=False,
        post_action=None,
        free_intro=False,
        retry_intro=False,
        log_prefix="switch char",
        time_out=10,
    ):
        if not self.ensure_team_binding():
            logger.info(f"{log_prefix} cancelled while team binding changes")
            return False
        current_char_name = current_char.ufn_name if current_char else "None"
        switch_to.has_intro = has_intro
        intro_replanned = False
        start_time = time.time()
        self.scene.clear_health_snapshot()
        switch_key_sent_at = 0
        last_index_check = 0

        logger.info(
            f"{log_prefix} {current_char_name} -> {switch_to.ufn_name}, has_intro {has_intro}"
        )

        with self.skip_sleep_checks() as skip:
            skip.check_combat = True

            while True:
                current_time = time.time()
                elapsed = current_time - start_time
                switch_to_name = switch_to.ufn_name
                frame = self.next_frame()

                if self.is_in_team(frame=frame):
                    self.check_combat()
                else:
                    info = f"{log_prefix} not in team {elapsed}s"
                    if elapsed > 5:
                        self.raise_not_in_combat(info)

                    if self._mark_dead_char_if_detected(switch_to):
                        return

                    self.log_info_gated(info)
                    self.sleep(0.01)
                    continue
                if self.scene.health_snapshot() is None:
                    self.is_health_changed(frame)

                detected_reason, last_index_check = self._switch_detection_reason(
                    switch_to,
                    frame,
                    switch_key_sent_at,
                    current_time,
                    last_index_check,
                    start_time,
                    time_out,
                )
                if detected_reason:
                    logger.info(f"{log_prefix} detected by {detected_reason}")
                    self._set_current_char(current_char, switch_to, has_intro)
                    break

                intro_ready = current_char is not None and (
                    free_intro or current_char.is_cycle_full()
                )
                if retry_intro and not has_intro and not intro_replanned and intro_ready:
                    intro_replanned = True
                    new_switch_to, new_has_intro = self._decide_switch_to(
                        current_char,
                        free_intro,
                        require_intro=True,
                    )
                    if new_has_intro and new_switch_to != current_char:
                        if not self.combat_planner.has_strict_route(current_char):
                            self._wait_switch_in_guard(current_char, new_switch_to, new_has_intro)
                        switch_to = new_switch_to
                        has_intro = new_has_intro
                        switch_to.has_intro = True
                        switch_to_name = switch_to.ufn_name
                        logger.info(
                            f"{log_prefix} updated target to {switch_to_name}, "
                            f"has_intro {switch_to.has_intro}"
                        )

                if not self.ensure_team_binding():
                    logger.info(f"{log_prefix} cancelled while team binding changes")
                    return False
                self.send_key(
                    switch_to.index + 1,
                    action_name="switch_char_send",
                    interval=0.15,
                    down_time=0.05,
                )
                self.sleep(0.001)
                self.click(action_name="switch_char_click", interval=0.3)
                if switch_key_sent_at <= 0:
                    switch_key_sent_at = current_time

                if elapsed > time_out:
                    if self.debug:
                        self.screenshot(
                            f"switch_not_detected_{current_char_name}_to_{switch_to_name}"
                        )
                    switch_to.mark_dead(f"switch char timeout {time_out}s")
                    return

                self.sleep(0.01)

        if has_intro and current_char:
            if self.record_element_reaction(current_char, switch_to):
                self.combat_planner.record_entry_reaction(current_char, switch_to)
        self.combat_planner.record_switch(switch_to)

        if post_action:
            logger.debug(f"post_action {post_action}")
            post_action(switch_to, has_intro)

        logger.info(f"{log_prefix} end {(time.time() - start_time):.3f}s")
        return True

    def _mark_dead_char_if_detected(self, switch_to: "BaseChar"):
        if self.find_confirm(self.box_of_screen(0.655, 0.694, 0.709, 0.787, hcenter=True)):
            switch_to.mark_dead("not in team while revive confirm is visible")
            self.ensure_main(in_world=False)
            return True
        return False

    def _switch_detection_reason(
        self,
        switch_to: "BaseChar",
        frame,
        switch_key_sent_at,
        current_time,
        last_index_check,
        start_time,
        time_out,
    ):
        if switch_key_sent_at > 0 and current_time - switch_key_sent_at >= 0.04:
            if self.is_health_changed(frame) is True:
                return "active health change", last_index_check

        if current_time - last_index_check < 0.35:
            return None, last_index_check

        use_index_fallback = (
            self.scene.health_snapshot() is None
            or switch_key_sent_at <= 0
            or current_time - switch_key_sent_at > 0.45
            or current_time - start_time > max(time_out - 0.75, time_out * 0.8)
        )
        if not use_index_fallback:
            return None, last_index_check

        last_index_check = current_time
        if self.is_char_at_index(switch_to.index, frame=frame, char_count=self.team_size):
            return "char index fallback", last_index_check
        return None, last_index_check

    def switch_next_char(self, current_char: "BaseChar", post_action=None, free_intro=False):
        """切换到下一个最优角色。

        Args:
            current_char (BaseChar): 当前角色对象。
            post_action (callable, optional): 切换后执行的动作 (回调函数)。默认为 None。
            free_intro (bool, optional): 是否强制认为拥有入场技 (通常在协奏值满时)。默认为 False。
        """
        if not self.combat_session.switch_enabled or self.team_size <= 1:
            self.click(action_name="switch_char_click", interval=0.1)
            return

        decision = self.combat_planner.decide_switch(
            current_char,
            free_intro=free_intro,
        )
        switch_to = decision.target
        has_intro = decision.has_intro
        if switch_to is None or switch_to == current_char:
            fallback_target = None
            if not self.combat_planner.has_strict_route(current_char):
                from src.combat.team_strategies import abyss_setup_exit_target

                fallback_target = abyss_setup_exit_target(current_char, self.chars)
            if fallback_target is None:
                from src.combat.team_strategies import is_abyss_setup_only_char

                if is_abyss_setup_only_char(current_char, self.chars):
                    current_char.check_combat()
                    current_char.sleep(0.05)
                    return
                current_char.click_with_interval()
                self.run_with_interval(
                    lambda: logger.debug(
                        f"planner keeps current char {current_char}: {decision.reason}"
                    ),
                    0.5,
                    action_name=("planner_keep_current", current_char.index, decision.reason),
                )
                return
            switch_to = fallback_target
            has_intro = False
            logger.info(
                f"planner exits setup-only {current_char} -> {switch_to}: "
                "no normal-attack fallback in abyss team"
            )

        if not self.combat_planner.has_strict_route(current_char):
            self._wait_switch_in_guard(current_char, switch_to, has_intro)
            current_char.wait_switch_cd()

        self.combat_planner.expect_entry_action(switch_to, decision.expected_entry)
        self._switch_to_char(
            switch_to,
            current_char=current_char,
            has_intro=has_intro,
            post_action=post_action,
            free_intro=free_intro,
            retry_intro=True,
            log_prefix=f"planner switch_next_char ({decision.reason})",
        )

    def switch_other_char(self, current_char: "BaseChar"):
        from src.tasks.trigger.AutoCombatTask import AutoCombatTask

        if isinstance(self, AutoCombatTask):
            current_char.logger.debug("AutoCombatTask, skip switch_other_char")
            return
        if not self.combat_session.switch_enabled:
            current_char.logger.debug("combat character switching disabled by task policy")
            return
        target = next(
            (
                char
                for char in self.chars
                if char and char.index != current_char.index and not char.is_dead
            ),
            None,
        )
        if target is None:
            current_char.logger.info("No living teammate available after combat")
            return

        next_char = str(target.index + 1)
        current_char.logger.debug(
            f"{current_char.ufn_name} on_combat_end {current_char.index} "
            f"switch next char: {next_char}"
        )
        start = time.time()
        while time.time() - start < 6:
            in_team, current_index, _ = self.in_team()
            if in_team and current_index != current_char.index:
                for char in filter(None, self.chars):
                    char.is_current_char = char.index == current_index
                break
            self.send_key(next_char)
            current_char.sleep(0.2, False)
        current_char.logger.debug(
            f"switch_other_char on_combat_end {current_char.index} switch end"
        )

    def switch_to_combat_start_char(self):
        if not self.combat_session.switch_enabled:
            logger.info("combat start switch disabled by task policy")
            return

        current_char = self.get_current_char(raise_exception=False)
        decision = self.combat_planner.decide_combat_start_char(current_char)
        switch_to = decision.target
        if switch_to is None:
            return
        if current_char == switch_to:
            logger.info(f"combat start char already current {switch_to}")
            return

        self._switch_to_char(
            switch_to,
            current_char=current_char,
            has_intro=decision.has_intro,
            log_prefix=f"planner combat start ({decision.reason})",
        )

    def get_ultimate_key(self):
        """获取终结技技能的按键。

        Returns:
            str: 终结技技能的按键字符串。
        """
        return self.key_config["Ultimate Key"]

    def get_skill_key(self):
        """获取技能的按键。

        Returns:
            str: 技能的按键字符串。
        """
        return self.key_config["Skill Key"]

    def get_arc_key(self):
        """获取弧盘技能的按键。

        Returns:
            str: 弧盘技能的按键字符串。
        """
        return self.key_config["Arc Key"]

    def has_skill_cd(self):
        """检查技能是否在冷却中。

        Returns:
            bool: 如果在冷却中则返回 True, 否则 False。
        """
        return self.has_cd("skill")

    def has_ult_cd(self):
        """检查终结技技能是否在冷却中。

        Returns:
            bool: 如果在冷却中则返回 True, 否则 False。
        """
        return self.has_cd("ultimate")

    def has_cd(self, box_name, char_index=None):
        """检查指定UI区域是否处于冷却状态 (通过检测特定颜色的点和数字)。

        Args:
            box_name (str): UI区域的名称 (例如 'skill', 'ultimate')。

        Returns:
            bool: 如果在冷却中则返回 True, 否则 False。
        """
        return self.get_cd(box_name, char_index) > 0

    def get_current_char(self, raise_exception=False) -> "BaseChar":
        """获取当前操作的角色对象。

        Args:
            raise_exception (bool, optional): 如果找不到当前角色是否抛出异常。默认为 False。

        Returns:
            BaseChar: 当前角色对象 (`BaseChar`) 或 None。
        """
        for char in self.chars:
            if char and char.is_current_char:
                return char
        if raise_exception:
            self.screenshot("get_current_char_failed")
            self.raise_not_in_combat("can find current char!!")
        return None

    def combat_end(self):
        """战斗结束时调用的清理方法。"""
        try:
            self.reset_to_false()
            SoundCombatContext().clear_task_if(self)

            current_char = self.get_current_char(raise_exception=False)
            if current_char:
                try:
                    self.get_current_char().on_combat_end(self.chars)
                except Exception as e:
                    self.log_error(f"{current_char.ufn_name} on_combat_end error", e)

            self._clear_dead_chars()
        finally:
            self.combat_session = None

    def _clear_dead_chars(self):
        for char in self.chars:
            if char is not None:
                char.clear_dead()

    def _wrap_wait_until_action(self, action):
        def wrapped_action():
            if action is not None:
                action()
            self.sleep(0.001)

        return wrapped_action

    def wait_until(
        self,
        condition,
        time_out=0,
        pre_action=None,
        post_action=None,
        settle_time=-1,
        raise_if_not_found=False,
    ):
        return super().wait_until(
            condition,
            time_out=time_out,
            pre_action=self._wrap_wait_until_action(pre_action),
            post_action=post_action,
            settle_time=settle_time,
            raise_if_not_found=raise_if_not_found,
        )

    @contextmanager
    def skip_sleep_checks(self):
        old_values = {
            field.name: getattr(self.sleep_check_skip, field.name)
            for field in fields(self.sleep_check_skip)
        }
        try:
            yield self.sleep_check_skip
        finally:
            for check, old_value in old_values.items():
                setattr(self.sleep_check_skip, check, old_value)

    def sleep_check(self):
        if (
            not self.sleep_check_skip.sound_combat_context
            and not self.in_animation
            and SoundCombatContext.should_interrupt_combat()
        ):
            self.log_info("Combat sleep interrupted by sound action")
            SoundCombatContext().execute_pending_action()
            SoundCombatContext.wait_for_resume()

        if not self.sleep_check_skip.check_combat:
            self.check_combat()

    def can_sound_trigger(self) -> bool:
        """Reject audio reactions while the game cannot accept a dodge input."""
        return bool(self._in_combat and not self.in_animation)

    def _apply_sound_config(self, dodge_action=ACTION_UNSET, counter_action=ACTION_UNSET):
        sound_context = SoundCombatContext()
        if self.sound_config:
            enable = self.sound_config.get("Enable Sound Trigger", True)
            dodge_all_attacks = self.sound_config.get("Dodge All Attacks", False)
            dodge_thresh = self.sound_config.get("Dodge Threshold", 0.13)
            counter_thresh = self.sound_config.get("Counter Attack Threshold", 0.12)
            dodge_thresh = np.clip(dodge_thresh, 0.0, 1.0)
            counter_thresh = np.clip(counter_thresh, 0.0, 1.0)
            sound_context.update_config(enable, dodge_all_attacks, dodge_thresh, counter_thresh)
        sound_context.update_task(self, dodge_action=dodge_action, counter_action=counter_action)

    def check_combat(self):
        """检查当前是否处于战斗状态, 如果不是则抛出异常。"""
        if self._in_combat:
            if not self.in_combat():
                # if self.debug:
                #     self.screenshot('not_in_combat_calling_check_combat')
                self.raise_not_in_combat("combat check not in combat")

    def in_combat(self):
        with self.skip_sleep_checks() as skip:
            skip.check_combat = True
            return super().in_combat()

    def set_key(self, key, box):
        best = self.find_best_match_in_box(box, ["t", "e", "r", "q"], threshold=0.7)
        logger.debug(f"set_key best match {key}: {best}")
        if best and best.name != self.key_config[key]:
            self.key_config[key] = best.name
            self.log_info(f"set_key {key} to {best.name}")

    def load_hotkey(self):
        """加载游戏内技能热键。"""
        for key, value in self.key_config.items():
            self.info_set(key, value)
        return self.key_config

    def has_char(self, char_cls):
        for char in self.chars:
            if isinstance(char, char_cls):
                return char

    def _report_strict_team_error(self, message: str):
        if message != self._strict_team_last_error:
            self._strict_team_last_error = message
            self.log_error(f"队伍预设校验失败：{message}", notify=True)
        else:
            logger.debug(f"strict team preset still blocked: {message}")

    def _verify_armed_team(self, armed_preset: dict, count: int, manager) -> bool:
        preset_name = armed_preset.get("name") or armed_preset.get("preset_id") or "未命名"
        slots = armed_preset.get("slots", [])
        if count != 4:
            self._report_strict_team_error(f"{preset_name}要求四人队伍，当前识别到{count}人")
            return False
        if not isinstance(slots, list):
            slots = []
        expected_ids = [
            slot.get("char_id", "") if isinstance(slot, dict) else "" for slot in slots[:4]
        ]
        if len(expected_ids) != 4 or not all(expected_ids) or len(set(expected_ids)) != 4:
            self._report_strict_team_error(f"{preset_name}必须保存四名不同角色")
            return False

        frame = self.frame
        for index, expected_char_id in enumerate(expected_ids):
            feature_mat, _, _ = get_char_feature_by_pos(self, index, frame=frame)
            expected_info = manager.get_character_info_by_id(expected_char_id)
            expected_name = expected_info["char_name"] if expected_info else expected_char_id
            if feature_mat is None or feature_mat.size <= 0:
                self._report_strict_team_error(
                    f"{preset_name}的{index + 1}号位未截取到头像，期望{expected_name}"
                )
                return False

            matched, actual_char_id, confidence = manager.match_feature(
                self,
                feature_mat,
                threshold=self.STRICT_TEAM_MATCH_THRESHOLD,
            )
            if not matched or actual_char_id != expected_char_id:
                actual_info = manager.get_character_info_by_id(actual_char_id or "")
                actual_name = actual_info["char_name"] if actual_info else "未识别"
                self._report_strict_team_error(
                    f"{preset_name}的{index + 1}号位期望{expected_name}，"
                    f"实际{actual_name}（{confidence:.2f}）"
                )
                return False

        self._strict_team_last_error = ""
        self.log_info(f"队伍预设校验通过：{preset_name}")
        return True

    @staticmethod
    def _slots_in_visible_order(preset: dict, char_ids: tuple[str, ...]) -> tuple[dict, ...] | None:
        preset_slots = preset.get("slots", []) if isinstance(preset, dict) else []
        by_char_id = {
            slot.get("char_id", ""): slot
            for slot in preset_slots
            if isinstance(slot, dict) and slot.get("char_id", "")
        }
        if len(by_char_id) != 4 or any(char_id not in by_char_id for char_id in char_ids):
            return None
        return tuple(
            {
                "char_id": char_id,
                "impl_id": by_char_id[char_id].get("impl_id", ""),
            }
            for char_id in char_ids
        )

    def _match_visible_team_preset(self, count: int, manager) -> VisibleTeamMatch | None:
        """Identify every HUD slot and resolve exactly one saved four-member preset."""
        if count != 4:
            self._report_strict_team_error(f"自动双队要求四人队伍, 当前识别到{count}人")
            return None

        frame = self.frame
        char_ids: list[str] = []
        for index in range(4):
            feature_mat, _, _ = get_char_feature_by_pos(self, index, frame=frame)
            if feature_mat is None or feature_mat.size <= 0:
                self._report_strict_team_error(f"自动双队的{index + 1}号位未截取到头像")
                return None
            matched, char_id, confidence = manager.match_feature(
                self,
                feature_mat,
                threshold=self.STRICT_TEAM_MATCH_THRESHOLD,
            )
            if not matched or not char_id:
                self._report_strict_team_error(
                    f"自动双队的{index + 1}号位无法高置信识别（{confidence:.2f}）"
                )
                return None
            char_ids.append(char_id)

        visible_ids = tuple(char_ids)
        preset_id = manager.match_team_preset(visible_ids)
        if not preset_id:
            self._report_strict_team_error("当前四人头像未唯一匹配任何已保存深渊预设")
            return None
        preset = manager.get_team_preset(preset_id)
        slots = self._slots_in_visible_order(preset, visible_ids)
        if not preset or slots is None:
            self._report_strict_team_error(f"深渊预设{preset_id}缺少完整槽位映射")
            return None

        self._strict_team_last_error = ""
        return VisibleTeamMatch(
            preset_id=preset_id,
            preset_name=preset.get("name") or preset_id,
            char_ids=visible_ids,
            slots=slots,
        )

    def _probe_visible_team(self, count: int, manager) -> tuple[VisibleTeamMatch | None, int]:
        """Probe HUD slots and return (full_match, partial_preset_count).

        full_match is the same result as _match_visible_team_preset when all four
        slots are confidently identified and uniquely match a saved preset.

        partial_preset_count > 0 means the confidently identified subset belongs
        to at least one saved abyss profile, so the caller should hold input and
        retry rather than falling back to generic detection.
        """
        if count != 4:
            return None, 0

        frame = self.frame
        confident_ids: list[str] = []
        all_confident = True
        for index in range(4):
            feature_mat, _, _ = get_char_feature_by_pos(self, index, frame=frame)
            if feature_mat is None or feature_mat.size <= 0:
                all_confident = False
                continue
            matched, char_id, confidence = manager.match_feature(
                self,
                feature_mat,
                threshold=self.STRICT_TEAM_MATCH_THRESHOLD,
            )
            if matched and char_id:
                confident_ids.append(char_id)
            else:
                all_confident = False

        if all_confident and len(confident_ids) == 4:
            full_match = self._match_visible_team_preset(count, manager)
            if full_match is not None:
                return full_match, 0
            # All four matched individually but no unique preset — treat as unknown.
            return None, 0

        # Partial recognition: check if the confident subset belongs to a saved preset.
        if confident_ids:
            partial_count = manager.partial_preset_match_count(confident_ids)
            return None, partial_count

        return None, 0

    def _stabilize_partial_recognition(self, count: int, manager) -> VisibleTeamMatch | None:
        """Retry full recognition for a short window after a partial known match.

        Returns a complete VisibleTeamMatch if the HUD stabilizes within the retry
        budget, or None if recognition never completes (caller should fail closed).
        """
        for attempt in range(self.PARTIAL_RECOGNITION_RETRIES):
            self.sleep(self.PARTIAL_RECOGNITION_RETRY_INTERVAL)
            match = self._match_visible_team_preset(count, manager)
            if match is not None:
                self.log_info(
                    f"自动双队：稳定帧第{attempt + 1}次重试成功绑定 {match.preset_name}"
                )
                return match
        self.log_info("自动双队：稳定窗口内未完成识别, 拒绝通用回退")
        return None

    def _stabilize_live_team_binding(self, manager) -> VisibleTeamMatch | None:
        """Wait briefly for combat HUD occlusion to clear without sending old inputs."""
        for attempt in range(self.LIVE_BINDING_RETRIES):
            self.sleep(self.LIVE_BINDING_RETRY_INTERVAL)
            in_team, current_index, count = self.in_team()
            if not in_team:
                continue
            match = self._match_visible_team_preset(count, manager)
            if match is not None:
                self.log_info(
                    f"自动双队：战斗遮挡第{attempt + 1}次重试恢复 {match.preset_name}"
                )
                return match
        self.log_info("自动双队：战斗遮挡窗口内未恢复, 继续暂停旧队伍输入")
        return None

    def _record_team_binding(self, match: VisibleTeamMatch | None) -> None:
        self._team_binding = match
        self._pending_team_binding = None
        self._team_binding_last_check = time.monotonic()
        self._team_binding_blocked = False
        if match is not None:
            self.active_team_preset_id = match.preset_id
            self.log_info(
                f"队伍绑定：{match.preset_name} / 槽位 {' -> '.join(match.char_ids)}"
            )

    def _block_stale_team_inputs(self, message: str) -> bool:
        """Stop stale combat input once; a new explicit team load clears this state."""
        if not getattr(self, "_team_binding_blocked", False):
            self._team_binding_blocked = True
            self._pending_team_binding = None
            self.combat_planner.reset([])
            self._report_strict_team_error(message)
        return False

    def team_binding_is_blocked(self) -> bool:
        return bool(getattr(self, "_team_binding_blocked", False))

    def _is_auto_team_selection_enabled(self) -> bool:
        return CustomCharManager().get_fixed_team().get("selection_mode") == "auto"

    def should_hold_position_on_target_loss(self) -> bool:
        """Keep Abyss teams still between waves instead of searching for enemies."""
        if not self._is_auto_team_selection_enabled():
            return False

        from src.combat.team_strategies import is_baicang_abyss_team, is_chiz_abyss_team

        return is_baicang_abyss_team(self.chars) or is_chiz_abyss_team(self.chars)

    def ensure_team_binding(self, *, force: bool = False) -> bool:
        """Prevent stale actions and rebind after a stable abyss roster transition.

        A false result tells the caller to abandon its current character object.
        This is necessary because a successful rebind replaces the team objects
        and clears planner routes owned by the previous abyss half.
        """
        binding = getattr(self, "_team_binding", None)
        if self.team_binding_is_blocked():
            return False
        if binding is None or self.in_animation:
            return True

        now = time.monotonic()
        last_check = getattr(self, "_team_binding_last_check", 0.0)
        if not force and now - last_check < self.TEAM_BINDING_CHECK_INTERVAL:
            return True
        self._team_binding_last_check = now

        in_team, current_index, count = self.in_team()
        if not in_team:
            self._report_strict_team_error("队伍界面暂不可用, 已暂停旧队伍输入")
            return False

        manager = CustomCharManager()
        visible = self._match_visible_team_preset(count, manager)
        if visible is None:
            # 阵亡后三人 HUD：已绑定深渊队且有角色死亡时，保留原队伍继续战斗，
            # 不得因死亡头像无法高置信匹配而永久停机。真实换队仍走稳定帧确认。
            if (
                count < 4
                and binding is not None
                and any(c is not None and c.is_dead for c in self.chars)
            ):
                self.log_info(
                    f"已绑定深渊队且有阵亡角色，HUD {count}人，保留原队伍继续战斗"
                )
                return True
            visible = self._stabilize_live_team_binding(manager)
            if visible is None:
                return False
        if visible == binding:
            self._pending_team_binding = None
            # 检测主 C 阵亡后的游戏自动换人：HUD current_index 与脚本记录不符时，
            # 标记原角色死亡并同步 is_current_char。仅在同队情况下触发，避免误判换队。
            if current_index >= 0:
                self._sync_current_after_auto_switch(current_index)
            return True

        if not self._is_auto_team_selection_enabled():
            return self._block_stale_team_inputs(
                f"当前队伍已从{binding.preset_name}变为{visible.preset_name}, "
                "未启用自动双队, 已停止旧策略输入"
            )

        # One transition frame is not enough to rebuild a live combat plan.
        # Keep every old input blocked until the next complete frame agrees.
        if getattr(self, "_pending_team_binding", None) != visible:
            self._pending_team_binding = visible
            self.log_info(f"检测到队伍交接候选：{visible.preset_name}, 等待稳定确认")
            return False

        self.log_info(f"队伍交接确认：{binding.preset_name} -> {visible.preset_name}")
        if not self.load_chars(visible_match=visible):
            self._report_strict_team_error("队伍交接重绑失败, 已停止旧策略输入")
        return False

    def _sync_current_after_auto_switch(self, current_index: int) -> None:
        """检测主动角色阵亡后的游戏自动换人，同步 current_index 并标记原角色死亡。

        游戏在主动角色阵亡后会自动切到下一个存活角色，但脚本的 is_current_char
        仍指死亡角色，导致后续 perform 持续操作死亡角色。这里通过 HUD
        current_index 与脚本记录对比检测自动换人，仅在同队（visible == binding）
        情况下触发，避免误判真实上下半场换队。

        剩余三名角色继续战斗；由死亡主 C 持有的 strict route 被丢弃，planner
        重新为存活角色规划。真实换队仍由 ensure_team_binding 的稳定帧确认保护。
        """
        chars = [c for c in self.chars if c is not None]
        if not chars:
            return
        current = next((c for c in chars if c.is_current_char), None)
        if current is None or current.index == current_index:
            return
        new_current = next((c for c in chars if c.index == current_index), None)
        if new_current is None or new_current.is_dead:
            return
        if not current.is_dead:
            current.mark_dead(
                f"auto switch detected after death (HUD index {current_index})"
            )
            self.log_info(
                f"detected auto switch after death: {current.char_name} dead, "
                f"now active {new_current.char_name}"
            )
        for c in chars:
            c.is_current_char = c.index == current_index
        # 丢弃由死亡角色持有的 strict route，避免 planner 永久等待死亡目标。
        planner = getattr(self, "combat_planner", None)
        state = getattr(planner, "state", None) if planner is not None else None
        locked_route = getattr(state, "locked_route", None) if state is not None else None
        if locked_route is not None:
            try:
                locked_route.close()
            except Exception:
                pass
            if state is not None:
                state.locked_route = None
            self.log_info(
                f"discarded strict route held by dead char: {current.char_name}"
            )

    def _do_load_char(self, index: int, fixed_slots) -> "BaseChar":
        fixed_slot = safe_get(fixed_slots, index)
        fixed_char_id = ""
        fixed_impl_id = ""
        strict_binding = getattr(self, "_strict_char_binding", False)
        if strict_binding and not isinstance(fixed_slot, dict):
            self._report_strict_team_error(
                f"深渊预设第{index + 1}号位缺少固定角色绑定"
            )
            return None
        if isinstance(fixed_slot, dict):
            fixed_char_id = fixed_slot.get("char_id", "")
            fixed_impl_id = fixed_slot.get("impl_id", "")
            if strict_binding and not fixed_char_id:
                self._report_strict_team_error(
                    f"深渊预设第{index + 1}号位缺少角色ID"
                )
                return None
            if fixed_char_id:
                char_info = CustomCharManager().get_character_info_by_id(fixed_char_id)
                if not char_info:
                    if strict_binding:
                        self._report_strict_team_error(
                            f"深渊预设第{index + 1}号位角色资料不存在：{fixed_char_id}"
                        )
                        return None
                    self.logger.warning(f"Fixed char {index} not found: {fixed_char_id}")
                    fixed_char_id = ""
                    fixed_impl_id = ""
                else:
                    fixed_char_name = char_info["char_name"]
                    self.logger.info(
                        f"Using fixed char {index}: {fixed_char_name} {fixed_impl_id}"
                    )
                    return get_char_by_id(
                        self,
                        index,
                        fixed_char_id,
                        confidence=1,
                        impl_id=fixed_impl_id,
                    )

        box_scaled = self.get_char_box(index).scale(1.1, 1.1)

        return get_char_by_pos(self, box_scaled, index, safe_get(self.chars, index))

    def load_chars(self, visible_match: VisibleTeamMatch | None = None) -> bool:
        """加载队伍中的角色信息。"""
        ret = False
        now = time.perf_counter()
        self.load_hotkey()
        in_team, current_index, count = self.in_team()
        if not in_team or current_index == -1:
            return ret

        if count > 4:
            logger.warning(f"char count {count} larger than 4, set to 4")
            count = 4
        self.log_info(f"load_chars count {count} current_index {current_index}")

        manager = CustomCharManager()
        fixed_team = manager.get_fixed_team()
        armed_preset = manager.get_armed_team_preset()
        auto_selection = fixed_team.get("selection_mode") == "auto"
        existing_binding = getattr(self, "_team_binding", None)
        if auto_selection and existing_binding is not None:
            # Once a known Abyss roster is bound, a transiently hidden HUD slot
            # must never rebuild the planner as a three-member generic party.
            if count != 4:
                self.log_info(
                    "自动双队：已绑定深渊队但当前 HUD 未完整显示四人，保留原队伍并等待恢复"
                )
                return False
            if visible_match is None:
                visible_match = self._match_visible_team_preset(count, manager)
                if visible_match is None:
                    visible_match = self._stabilize_live_team_binding(manager)
                if visible_match is None:
                    self.log_info("自动双队：已绑定深渊队的 HUD 未稳定，保留原队伍并暂停输入")
                    return False
        if auto_selection:
            visible_match = visible_match or self._match_visible_team_preset(count, manager)
            if visible_match is None:
                # Probe whether the partially recognized slots belong to a saved abyss profile.
                _, partial_count = self._probe_visible_team(count, manager)
                if partial_count > 0:
                    # A known abyss roster is partially visible; hold input and retry
                    # for a short stabilization window before failing closed.
                    self.log_info(
                        f"自动双队：部分识别已知深渊阵容({partial_count}个预设匹配), 等待稳定帧"
                    )
                    visible_match = self._stabilize_partial_recognition(count, manager)
                    if visible_match is None:
                        return False
                    fixed_slots = visible_match.slots
                else:
                    # A new non-abyss battle still uses OKNTE's ordinary character detection.
                    # Strict failure applies after a saved abyss team has been bound.
                    auto_selection = False
                    fixed_slots = []
            else:
                fixed_slots = visible_match.slots
        elif armed_preset:
            if not self._verify_armed_team(armed_preset, count, manager):
                return False
            fixed_slots = armed_preset["slots"]
        else:
            fixed_slots = fixed_team.get("slots", []) if fixed_team.get("enabled", False) else []

        if (
            auto_selection
            and existing_binding is not None
            and visible_match is not None
            and visible_match != existing_binding
        ):
            if getattr(self, "_pending_team_binding", None) != visible_match:
                self._pending_team_binding = visible_match
                self.log_info(
                    f"detected Abyss team transition candidate: {visible_match.preset_name}; "
                    "waiting for a stable frame"
                )
                return False
            self._pending_team_binding = None

        # A short combat-state/HUD gap must not create a fresh set of character
        # objects. Reusing them preserves locked-route progress and prevents
        # the same Abyss half from publishing its opener again.
        if (
            auto_selection
            and visible_match is not None
            and visible_match == getattr(self, "_team_binding", None)
            and self.can_preserve_combat_session()
        ):
            for char in self.chars:
                if char is not None:
                    if char.index == current_index:
                        char.switch_in()
                    else:
                        char.is_current_char = False
            self._team_binding_last_check = time.monotonic()
            self._pending_team_binding = None
            self.log_info(
                f"combat session resumed, preserving team {visible_match.preset_name} "
                "and planner state"
            )
            return True

        if getattr(self, "_combat_session", None) is not None:
            logger.info(
                "rebuilding combat session after Abyss team change or session timeout"
            )
            self._combat_session = None

        self.clear_element_reactions()
        new_chars = []
        indices_to_detect = []
        self._strict_char_binding = bool(
            auto_selection
            and visible_match is not None
            and visible_match.preset_id in self.ABYSS_PRESET_IDS
        )
        try:
            for i in range(count):
                char = self._do_load_char(i, fixed_slots)
                if char is None:
                    return False
                new_chars.append(char)
                if char.element is Element.DEFAULT:
                    indices_to_detect.append(i)
        finally:
            self._strict_char_binding = False

        if indices_to_detect:
            detected_elements = self.load_chars_element(indices_to_detect)
            for i in indices_to_detect:
                new_chars[i].element = detected_elements.get(i, Element.DEFAULT)

        elements = [char.element for char in new_chars]

        if auto_selection:
            self.active_team_preset_id = visible_match.preset_id
            self.log_info(f"自动双队选择：{visible_match.preset_name}")
        elif armed_preset:
            consumed = manager.consume_armed_team_preset(armed_preset["preset_id"])
            if not consumed:
                self._report_strict_team_error("无法安全消费下一场武装状态，请重新保存预设")
                return False
            self.active_team_preset_id = consumed["preset_id"]
            self.log_info(f"队伍预设已用于本场：{consumed['name']}")
        else:
            self.active_team_preset_id = (
                fixed_team.get("active_preset_id", "") if fixed_team.get("enabled", False) else ""
            )

        self.chars = new_chars
        self.combat_planner.reset(self.chars)
        self.info_set("char elements", elements)

        self.info_set("chars", [])
        for char in self.chars:
            if char is not None:
                char.reset_state()
                if char.index == current_index:
                    char.switch_in()
                else:
                    char.is_current_char = False
                name = char.ufn_name
                conf = char.confidence
                elem = char.element
                self.log_info(f"load char success {char} {name} {conf:.2f} {elem}")
                self.info_add_to_list("chars", f"{char.ufn_name}: {char.impl_id or 'BaseChar'}")

        if self.team_size > 0:
            ret = True
            self._team_binding_blocked = False
            self._apply_sound_config()
            if auto_selection:
                self._record_team_binding(visible_match)
            elif armed_preset:
                self._record_team_binding(
                    VisibleTeamMatch(
                        preset_id=armed_preset["preset_id"],
                        preset_name=armed_preset.get("name") or armed_preset["preset_id"],
                        char_ids=tuple(slot["char_id"] for slot in armed_preset["slots"]),
                        slots=tuple(armed_preset["slots"]),
                    )
                )
        logger.debug(f"load_chars cost {time.perf_counter() - now:.3f}s")
        return ret

    def is_cycle_full(self) -> bool:
        img = self.box_of_screen_scaled(
            2560, 1440, 944, 1316, width_original=66, height_original=66
        ).crop_frame(self.frame)
        h, w = img.shape[:2]
        side = h

        # 1. 预处理：灰度化 + 二值化
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)

        # 2. 构造环形掩模 (Mask) —— 进一步排除干扰
        # 环厚度约 12%，我们可以只看这个半径范围内的像素
        mask = np.zeros((h, w), dtype=np.uint8)
        center = (w // 2, h // 2)
        outer_r = side // 2
        inner_r = int(outer_r * (1 - 0.15))  # 稍微多给一点余量，取15%
        cv2.circle(mask, center, outer_r, 255, -1)
        cv2.circle(mask, center, inner_r, 0, -1)

        # 应用掩模，只保留环形区域
        ring_only = cv2.bitwise_and(thresh, thresh, mask=mask)

        # 3. 取样区定义 (核心：对比顶部和底部)
        # 取顶部中心 10%x10% 的区域，以及底部中心同样的区域
        roi_size = int(side * 0.1)
        margin = int(side * 0.02)  # 避开最边缘可能存在的黑边

        # 顶部采样区 (12点钟方向)
        top_roi = ring_only[
            margin : margin + roi_size, (w // 2 - roi_size // 2) : (w // 2 + roi_size // 2)
        ]

        # 底部采样区 (6点钟方向)
        bottom_roi = ring_only[
            (h - margin - roi_size) : (h - margin),
            (w // 2 - roi_size // 2) : (w // 2 + roi_size // 2),
        ]

        # 4. 计算白色像素密度
        top_density = np.sum(top_roi == 255)
        bottom_density = np.sum(bottom_roi == 255)

        # 5. 精准判断逻辑
        # 如果满了，top_density 应该和 bottom_density 非常接近
        # 如果没满（有缺口），top_density 会显著低于 bottom_density
        if bottom_density == 0:
            return False  # 防止除以0

        ratio = top_density / bottom_density

        # 阈值建议：如果 ratio > 0.9，认为已经满了
        # “差一点点”的时候，由于缺口正好在顶部，这个 ratio 会瞬间降到 0.5 以下甚至更低
        is_full = ratio > 0.9

        return is_full

    def walk_until_combat(
        self, direction="w", time_out=10, run=False, delay=0, raise_if_not_found=False
    ):
        ret = False
        try:
            self.middle_click(after_sleep=0.2)
            self.send_key_down(direction)
            if run:
                self.sleep(0.1)
                self.send_key("lshift")
            ret = bool(
                self.wait_until(
                    self.in_combat,
                    time_out=time_out,
                    raise_if_not_found=raise_if_not_found,
                )
            )
            self.sleep(delay)
        finally:
            self.send_key_up(direction)
        return ret

    def ultimate_available(self, index) -> Box | None:
        def mask_function(image):
            return iu.mask_corners(image, ratio_w=0.5, ratio_h=0.5, corners="all")

        def overlap_confidence(x, y, template, search_area, mask):
            height, width = template.shape[:2]
            hit = search_area[y : y + height, x : x + width]
            if hit.shape[:2] != template.shape[:2]:
                return 0.0

            active = mask > 0
            template_active = (template > 0) & active
            hit_active = (hit > 0) & active
            template_count = template_active.sum()
            hit_count = hit_active.sum()
            if template_count == 0 or hit_count == 0:
                return 0.0

            intersection = np.logical_and(template_active, hit_active).sum()
            precision = intersection / hit_count
            recall = intersection / template_count
            return min(precision, recall)

        def find_best_overlap(template, search_area, mask, search_box):
            template_height, template_width = template.shape[:2]
            search_height, search_width = search_area.shape[:2]
            if template_height > search_height or template_width > search_width:
                return None

            best_confidence = 0.0
            best_x = 0
            best_y = 0
            for y in range(search_height - template_height + 1):
                for x in range(search_width - template_width + 1):
                    confidence = overlap_confidence(x, y, template, search_area, mask)
                    if confidence > best_confidence:
                        best_confidence = confidence
                        best_x = x
                        best_y = y

            return Box(
                search_box.x + best_x,
                search_box.y + best_y,
                template_width,
                template_height,
                best_confidence,
                Labels.ult_ready,
            )

        box = self.get_box_by_name(Labels.ult_ready)
        box = self._shift_char_ui_box(box, expend=True)
        target_box = self.get_box_by_char_spacing(box, index).scale(1.1)
        self.draw_boxes(boxes=target_box, color="blue")

        feature = self.get_feature_by_name(Labels.ult_ready).mat
        mask = mask_function(feature)
        # image = target_box.scale(1.1).crop_frame(self.frame)

        # iu.show_images([feature, image], ["feature", "image"])
        search_area = gf.ultimate_ready_filter(target_box.crop_frame(self.frame))
        ret = find_best_overlap(feature, search_area, mask, target_box)
        conf = ret.confidence if ret else -1
        if ret and ret.confidence >= 0.7:
            ret.name = str(index)
            self.draw_boxes(boxes=ret, color="red")
        else:
            ret = None
        self.log_info("char:{}, ult:{}, conf:{}".format(index, bool(ret), conf))
        # self.run_with_interval(
        #     lambda: self.log_info(
        #         "char:{}, ult:{}, conf:{}".format(index, bool(ret), conf)
        #     ),
        #     interval=1,
        #     action_name="ultimate_available",
        # )
        return ret


def convert_cd(text):
    """
    Strips a string to only keep the first part that matches the regex pattern.
    Args:
      text: The input string.
      pattern: The regex pattern to match.
    Returns:
      The first matching substring, or None if no match is found.
    """
    try:
        return float(text.name)
    except ValueError:
        match = re.search(cd_regex, text.name)
        if match:
            return float(match.group(0))
        else:
            return 1
