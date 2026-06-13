import re
import time
from threading import Lock, Thread
from typing import List

import cv2
import numpy as np
from ok import Box, Logger, safe_get

from src import text_white_color
from src.char.BaseChar import BaseChar, Element
from src.char.CharFactory import get_char_by_name, get_char_by_pos
from src.char.custom.CustomCharManager import CustomCharManager
from src.char.Healer import Healer
from src.combat.CombatCheck import CombatCheck
from src.combat.planner import CombatPlanner
from src.Labels import Labels
from src.sound_trigger.SoundCombatContext import SoundCombatContext
from src.utils import game_filters as gf
from src.utils import image_utils as iu

logger = Logger.get_logger(__name__)
cd_regex = re.compile(r"\d{1,2}\.\d")


class NotInCombatException(Exception):
    """未处于战斗状态异常。"""

    pass


class CharDeadException(NotInCombatException):
    """角色死亡异常。"""

    pass


class BaseCombatTask(CombatCheck):
    """基础战斗任务类，封装了游戏"鸣潮"中角色自动化操作的通用逻辑。"""

    hot_key_verified = False  # 热键是否已验证
    freeze_durations = []  # 记录冻结/卡肉的持续时间

    element_ring = (
        Element.WHITE,
        Element.GREEN,
        Element.RED,
        Element.PURPLE,
        Element.BLUE,
        Element.YELLOW,
    )
    element_ring_index = {element: index for index, element in enumerate(element_ring)}
    target_elements = (
        Element.BLUE,
        Element.GREEN,
        Element.RED,
        Element.PURPLE,
        Element.YELLOW,
        Element.WHITE,
    )
    _element_template_cache = {}
    _element_template_cache_lock = Lock()
    _element_template_preheat_started = False

    def __init__(self, *args, **kwargs):
        """初始化战斗任务。

        Args:
            *args: 传递给父类的参数。
            **kwargs: 传递给父类的关键字参数。
        """
        super().__init__(*args, **kwargs)
        self.chars: list[BaseChar] = []
        self.mouse_pos = None  # 当前鼠标位置
        self.combat_start = 0  # 战斗开始时间戳

        self.add_text_fix({"Ｅ": "e"})
        self.use_ultimate = True
        self.vibrate_chars_index: list[int] = []
        self.chars_slot_mat = [None, None, None, None]
        self.element_ring_reaction_counts = {}
        self.combat_planner = CombatPlanner(self)
        self.clear_element_ring_reactions()
        self.preheat_element_template_cache_async()
        CustomCharManager().preheat_feature_cache_async()

    @staticmethod
    def _process_template_transparency(img):
        if img is None:
            return None
        if len(img.shape) == 2:
            return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        if img.shape[2] == 4:
            b, g, r, a = cv2.split(img)
            black_bg = np.zeros_like(img[:, :, :3])
            alpha_factor = a.astype(float) / 255.0
            alpha_factor = cv2.merge([alpha_factor, alpha_factor, alpha_factor])

            foreground = cv2.merge([b, g, r]).astype(float)
            background = black_bg.astype(float)

            final_img = cv2.add(
                cv2.multiply(foreground, alpha_factor),
                cv2.multiply(background, 1.0 - alpha_factor),
            )
            return final_img.astype(np.uint8)
        return img

    @staticmethod
    def _preprocess_element_template_image(image):
        return iu.binarize_bgr_by_adaptive_center(image)

    @classmethod
    def _load_element_template(cls, element):
        raw_template = cv2.imread(f"assets/esper_icons/{element.value}.png", cv2.IMREAD_UNCHANGED)
        if raw_template is None:
            return None

        h, w = raw_template.shape[:2]
        raw_template = cls._process_template_transparency(raw_template)
        if raw_template is None:
            return None

        element_scale = 0.5
        raw_template = cv2.resize(
            raw_template,
            (int(w * element_scale), int(h * element_scale)),
            interpolation=cv2.INTER_NEAREST,
        )
        template_bin = cls._preprocess_element_template_image(raw_template)
        _, mask = cv2.threshold(template_bin, 127, 255, cv2.THRESH_BINARY)
        kernel = np.ones((30, 30), np.uint8)
        mask = cv2.dilate(mask, kernel, iterations=1)
        return raw_template, mask

    @classmethod
    def build_element_template_cache(cls):
        with cls._element_template_cache_lock:
            if cls._element_template_cache:
                return

        built_cache = {}
        for element in cls.target_elements:
            template_data = cls._load_element_template(element)
            if template_data is not None:
                built_cache[element] = template_data

        with cls._element_template_cache_lock:
            if not cls._element_template_cache:
                cls._element_template_cache = built_cache

    @classmethod
    def _preheat_element_template_cache_worker(cls):
        try:
            cls.build_element_template_cache()
            logger.debug(f"preheated {len(cls._element_template_cache)} element templates")
        except Exception as e:
            logger.error("Failed to preheat element templates", e)

    @classmethod
    def preheat_element_template_cache_async(cls):
        with cls._element_template_cache_lock:
            if cls._element_template_preheat_started or cls._element_template_cache:
                return
            cls._element_template_preheat_started = True
        Thread(
            target=cls._preheat_element_template_cache_worker,
            name="element-template-cache-preheat",
            daemon=True,
        ).start()

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

    def clear_element_ring_reactions(self):
        self.element_ring_reaction_counts = {
            (self.element_ring[i], self.element_ring[(i + 1) % len(self.element_ring)]): 0
            for i in range(len(self.element_ring))
        }

    def record_element_ring_reaction(self, char_a: "BaseChar", char_b: "BaseChar") -> bool:
        if char_a is None or char_b is None:
            return False
        pair = self._get_element_ring_pair(char_a.element, char_b.element)
        if pair is None:
            return False
        self.element_ring_reaction_counts[pair] = self.element_ring_reaction_counts.get(pair, 0) + 1
        return True

    def find_element_ring_reaction_target(self, source_char: "BaseChar") -> "BaseChar | None":
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
        previous_count = self.element_ring_reaction_counts.get(previous_pair, 0)
        next_count = self.element_ring_reaction_counts.get(next_pair, 0)
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
            self.freeze_durations = [
                item for item in self.freeze_durations if item[0] > current_time - 60
            ]
            self.freeze_durations.append((start, duration, freeze_time))

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
        for freeze_start, duration, freeze_time in self.freeze_durations:
            if start < freeze_start:
                if intro_motion_freeze:
                    if freeze_time == -100:
                        freeze_time = 0
                elif freeze_time == -100:
                    continue
                if duration < freeze_time:
                    duration = freeze_time
                to_minus += duration
        if to_minus != 0:
            self.run_with_interval(
                lambda: self.log_debug(f"time_elapsed_accounting_for_freeze to_minus {to_minus}"),
                0.5,
            )
        return time.time() - start - to_minus

    def refresh_cd(self):
        if self.scene.cd_refreshed:
            return
        index = self.get_current_char().index
        cds = self.cds.get(index)
        if cds is None:
            cds = {}
            self.cds[index] = cds
        cds["time"] = time.time()
        cds["skill"] = 0
        cds["ultimate"] = 0
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
        logger.error(message)
        if self.reset_to_false(reason=message):
            logger.error(f"reset to false failed: {message}")
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

    def combat_once(self, wait_combat_time=200, raise_if_not_found=True):
        """执行一次完整的战斗流程。

        Args:
            wait_combat_time (int, optional): 等待进入战斗状态的超时时间 (秒)。默认为 200。
            raise_if_not_found (bool, optional): 如果未找到战斗状态是否抛出异常。默认为 True。
        """
        self.wait_until(
            self.in_combat, time_out=wait_combat_time, raise_if_not_found=raise_if_not_found
        )
        self.load_chars()
        self.switch_to_combat_start_char()
        self.info["Combat Count"] = self.info.get("Combat Count", 0) + 1
        try:
            while self.in_combat():
                logger.debug(f"combat_once loop {self.chars}")
                self.get_current_char().perform()
        except CharDeadException as e:
            raise e
        except NotInCombatException as e:
            logger.info(f"combat_once out of combat break {e}")
        self.combat_end()
        self.wait_in_team_and_world(time_out=10, raise_if_not_found=False)

    def _get_char_log_name(self, char: "BaseChar"):
        from src.char.custom.CustomChar import CustomChar

        if type(char) in (BaseChar, CustomChar):
            return char.char_name
        else:
            return char.name

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
        switch_to.is_current_char = True
        switch_to.has_intro = has_intro

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
        current_char_name = self._get_char_log_name(current_char) if current_char else "None"
        switch_to.has_intro = has_intro
        intro_replanned = False
        start_time = time.time()
        start_frame = self.frame
        health_snapshot = self._capture_active_health_snapshot(start_frame)
        switch_key_sent_at = 0
        last_index_check = 0

        logger.info(
            f"{log_prefix} {current_char_name} -> {self._get_char_log_name(switch_to)}, "
            f"has_intro {has_intro}"
        )

        while True:
            self.check_combat()
            current_time = time.time()
            switch_to_name = self._get_char_log_name(switch_to)
            frame = self.frame

            detected_reason, last_index_check = self._switch_detection_reason(
                switch_to,
                health_snapshot,
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

            intro_ready = current_char is not None and (free_intro or current_char.is_cycle_full())
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
                    switch_to_name = self._get_char_log_name(switch_to)
                    logger.info(
                        f"{log_prefix} updated target to {switch_to_name}, "
                        f"has_intro {switch_to.has_intro}"
                    )

            if not self.is_in_team(frame=frame):
                logger.info(
                    f"not in world while switching {current_char_name} -> {switch_to_name},"
                    f" {current_time - start_time}"
                )
                if current_time - start_time > self.switch_char_time_out:
                    self.raise_not_in_combat(
                        f"switch too long failed {current_char_name} -> {switch_to_name},"
                        f" {current_time - start_time}"
                    )
                self.sleep(0.01)
                continue

            self.click(action_name="switch_char_click", interval=0.25)
            self.sleep(0.001)
            self.send_key(switch_to.index + 1, action_name="switch_char_send", interval=0.25)
            if switch_key_sent_at <= 0:
                switch_key_sent_at = current_time

            if current_time - start_time > time_out:
                if self.debug:
                    self.screenshot(f"switch_not_detected_{current_char_name}_to_{switch_to_name}")
                self.raise_not_in_combat(f"{log_prefix} failed {switch_to_name}")

            self.sleep(0.01)

        if has_intro and current_char:
            if self.record_element_ring_reaction(current_char, switch_to):
                self.combat_planner.record_entry_reaction(current_char, switch_to)
        self.combat_planner.record_switch(switch_to)

        if post_action:
            logger.debug(f"post_action {post_action}")
            post_action(switch_to, has_intro)

        logger.info(f"{log_prefix} end {(time.time() - start_time):.3f}s")

    def _capture_active_health_snapshot(self, frame):
        """截取当前出场角色血条颜色快照，用于快速判断切人是否已经发生。"""

        box = self.is_in_team(frame=frame)
        if box is None:
            return
        health_box = box.copy(x_offset=box.width, width_offset=box.width * 3)
        cropped = health_box.crop_frame(frame)
        snapshot = iu.create_color_mask(cropped, char_health_color, to_bgr=False)
        return snapshot

    def _active_health_changed(self, snapshot, frame):
        """判断当前出场血条是否已经不同于切人前快照。"""

        if snapshot is None:
            return None

        def frame_processor(cv):
            return iu.create_color_mask(cv, char_health_color, to_bgr=False)

        box = self.is_in_team(frame=frame)
        if box is None:
            return None
        health_box = box.copy(x_offset=box.width, width_offset=box.width * 3).scale(1.1)
        if self.find_one(
            "health_snapshot",
            template=snapshot,
            box=health_box,
            frame=frame,
            frame_processor=frame_processor,
        ):
            return False
        return True

    def _switch_detection_reason(
        self,
        switch_to: "BaseChar",
        health_snapshot,
        frame,
        switch_key_sent_at,
        current_time,
        last_index_check,
        start_time,
        time_out,
    ):
        if switch_key_sent_at > 0 and current_time - switch_key_sent_at >= 0.04:
            if self._active_health_changed(health_snapshot, frame) is True:
                return "active health change", last_index_check

        if current_time - last_index_check < 0.35:
            return None, last_index_check

        use_index_fallback = (
            health_snapshot is None
            or switch_key_sent_at <= 0
            or current_time - switch_key_sent_at > 0.45
            or current_time - start_time > max(time_out - 0.75, time_out * 0.8)
        )
        if not use_index_fallback:
            return None, last_index_check

        last_index_check = current_time
        if self.is_char_at_index(switch_to.index, frame=frame):
            return "char index fallback", last_index_check
        return None, last_index_check

    def switch_next_char(self, current_char: "BaseChar", post_action=None, free_intro=False):
        """切换到下一个最优角色。

        Args:
            current_char (BaseChar): 当前角色对象。
            post_action (callable, optional): 切换后执行的动作 (回调函数)。默认为 None。
            free_intro (bool, optional): 是否强制认为拥有入场技 (通常在协奏值满时)。默认为 False。
        """
        if self.team_size <= 1:
            self.click(action_name="switch_char_click", interval=0.1)
            return

        decision = self.combat_planner.decide_switch(
            current_char,
            free_intro=free_intro,
        )
        switch_to = decision.target
        has_intro = decision.has_intro
        if switch_to is None or switch_to == current_char:
            current_char.click_with_interval()
            self.run_with_interval(
                lambda: logger.debug(
                    f"planner keeps current char {current_char}: {decision.reason}"
                ),
                0.5,
                action_name=("planner_keep_current", current_char.index, decision.reason),
            )
            return

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

    def switch_to_combat_start_char(self):
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
            time_out=self.switch_char_time_out,
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
        SoundCombatContext().clear_task_if(self)

        current_char = self.get_current_char(raise_exception=False)
        if current_char:
            self.get_current_char().on_combat_end(self.chars)

    def sleep_check(self):
        if self.skip_sleep_check:
            return

        if SoundCombatContext.should_interrupt_combat():
            self.log_info("Combat sleep interrupted by sound action")
            SoundCombatContext().execute_pending_action()
            SoundCombatContext.wait_for_resume()

        if self._in_combat:
            self.next_frame()
            if not self.in_combat():
                self.raise_not_in_combat("sleep check not in combat")

    def _apply_sound_config(self):
        if self.sound_config:
            enable = self.sound_config.get("Enable Sound Trigger", True)
            dodge_all_attacks = self.sound_config.get("Dodge All Attacks", True)
            dodge_thresh = self.sound_config.get("Dodge Threshold", 0.13)
            counter_thresh = self.sound_config.get("Counter Attack Threshold", 0.12)
            dodge_thresh = np.clip(dodge_thresh, 0.0, 1.0)
            counter_thresh = np.clip(counter_thresh, 0.0, 1.0)
            SoundCombatContext().update_config(
                enable, dodge_all_attacks, dodge_thresh, counter_thresh
            )
        SoundCombatContext().update_task(self)

    def check_combat(self):
        """检查当前是否处于战斗状态, 如果不是则抛出异常。"""
        if self._in_combat and not self.in_combat():
            # if self.debug:
            #     self.screenshot('not_in_combat_calling_check_combat')
            self.raise_not_in_combat("combat check not in combat")

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

    def _do_load_char(self, index: int, fixed_slots) -> "BaseChar":
        fixed_slot = safe_get(fixed_slots, index)
        fixed_char_name = ""
        fixed_combo_ref = ""
        if isinstance(fixed_slot, dict):
            fixed_char_name = str(fixed_slot.get("char_name", "") or "").strip()
            fixed_combo_ref = str(fixed_slot.get("combo_ref", "") or "").strip()

        if fixed_char_name:
            self.log_debug(
                f"load_chars use fixed slot {index + 1}: {fixed_char_name} {fixed_combo_ref}"
            )
            return get_char_by_name(
                self, index, fixed_char_name, confidence=1, combo_ref=fixed_combo_ref
            )

        box_scaled = self.get_char_box(index).scale(1.1, 1.1)

        return get_char_by_pos(self, box_scaled, index, safe_get(self.chars, index))

    def load_chars(self) -> bool:
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

        self.clear_element_ring_reactions()
        fixed_team = CustomCharManager().get_fixed_team()
        fixed_slots = fixed_team.get("slots", []) if fixed_team.get("enabled", False) else []
        new_chars = []
        indices_to_detect = []
        for i in range(count):
            char = self._do_load_char(i, fixed_slots)
            new_chars.append(char)
            if char.element is Element.DEFAULT:
                indices_to_detect.append(i)

        if indices_to_detect:
            detected_elements = self.load_chars_element(indices_to_detect)
            for i in indices_to_detect:
                new_chars[i].element = detected_elements.get(i, Element.DEFAULT)

        elements = [char.element for char in new_chars]
        self.chars = new_chars
        self.combat_planner.reset(self.chars)
        self.info_set("char elements", elements)

        healer_count = 0
        self.info_set("chars", [])
        for char in self.chars:
            if char is not None:
                char.reset_state()
                if isinstance(char, Healer):
                    healer_count += 1
                if char.index == current_index:
                    char.is_current_char = True
                else:
                    char.is_current_char = False
                name = char.char_name
                conf = char.confidence
                elem = char.element
                self.log_info(f"load char success {char} {name} {conf:.2f} {elem}")
                self.info_add_to_list("chars", f"{char.char_name}: {char.combo_label}")

        if self.team_size > 0:
            self.combat_start = time.time()
            ret = True
            self._apply_sound_config()
        logger.debug(f"load_chars cost {time.perf_counter() - now:.3f}s")
        return ret

    def load_chars_element(self, indices: List[int]) -> dict:
        results = {}
        self.build_element_template_cache()

        base_box = self.get_base_char_element_box()

        _frame = self.frame
        # self.screenshot("load_chars_element", _frame)

        for i in indices:
            base_scale = 8
            scale = base_scale * 1440 / self.height
            current_box = self.get_box_by_char_spacing(base_box, i)
            crop_img = current_box.crop_frame(_frame)
            crop_h, crop_w = crop_img.shape[:2]
            crop_resized = cv2.resize(
                crop_img,
                (int(crop_w * scale), int(crop_h * scale)),
                interpolation=cv2.INTER_NEAREST,
            )
            # iu.show_images([crop_resized, crop_img], [f"crop_resized_{i}", f"crop_img_{i}"])

            best_element = Element.DEFAULT
            max_score = -1.0

            for element in self.target_elements:
                template_data = self._element_template_cache.get(element)
                if template_data is None:
                    continue
                template_img, template_mask = template_data

                match_score = 0
                if crop_resized is not None and template_img is not None:
                    res = cv2.matchTemplate(
                        crop_resized, template_img, cv2.TM_CCOEFF_NORMED, mask=template_mask
                    )
                    res[np.isinf(res)] = 0
                    _, match_score, _, _ = cv2.minMaxLoc(res)

                if match_score > max_score:
                    max_score = match_score
                    best_element = element

            current_box.confidence = max_score
            current_box.name = best_element.name
            results[i] = best_element
            self.draw_boxes(boxes=current_box, color="red")
            self.log_debug(
                f"char_{i + 1} identified as {best_element.name} (score: {max_score:.4f})"
            )

        return results

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
                self.send_key_down("lshift")
            ret = bool(
                self.wait_until(
                    self.in_combat,
                    time_out=time_out,
                    raise_if_not_found=raise_if_not_found,
                )
            )
            self.sleep(delay)
        finally:
            if run:
                self.send_key_up("lshift")
                self.sleep(0.1)
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


char_health_color = {
    "r": (160, 210),
    "g": (160, 210),
    "b": (160, 210),
}
