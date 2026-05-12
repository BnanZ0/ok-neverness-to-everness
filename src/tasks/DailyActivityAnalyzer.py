from dataclasses import dataclass, field
from enum import Enum
import re

import cv2
import numpy as np

from ok import Box

from src.Labels import Labels
from src.tasks.F1PanelDetector import F1PanelDetector
from src.tasks.DailyUIContext import ReadOnlyUIContext


def _extract_progress_text(text):
    value = str(text or "")
    for start, char in enumerate(value):
        if not char.isdigit():
            continue
        index = start
        current = []
        while index < len(value) and value[index].isdigit():
            current.append(value[index])
            index += 1
        while index < len(value) and value[index].isspace():
            index += 1
        if index >= len(value) or value[index] != "/":
            continue
        index += 1
        while index < len(value) and value[index].isspace():
            index += 1
        target = []
        while index < len(value) and value[index].isdigit():
            target.append(value[index])
            index += 1
        if target:
            return f"{''.join(current)}/{''.join(target)}"
    return ""


def _is_progress_text(text):
    normalized = str(text or "").replace(" ", "")
    return bool(normalized and _extract_progress_text(text) == normalized)


def _is_signed_integer_text(text):
    normalized = str(text or "").replace(" ", "")
    if normalized.startswith("+"):
        normalized = normalized[1:]
    return bool(normalized and normalized.isdigit())


def _extract_reward_points(text):
    value = str(text or "")
    for start, char in enumerate(value):
        if char != "+":
            continue
        index = start + 1
        while index < len(value) and value[index].isspace():
            index += 1
        digits = []
        while index < len(value) and value[index].isdigit() and len(digits) < 3:
            digits.append(value[index])
            index += 1
        if digits:
            return int("".join(digits))
    return None


class DailyActivityState(str, Enum):
    UNKNOWN = "unknown"
    PANEL_NOT_FOUND = "panel_not_found"
    DAILY_TAB_OPENED = "daily_tab_opened"
    ACTIVITY_FULL = "activity_full"
    ALL_DAILY_DONE = "all_daily_done"
    HAS_GO_BUTTON = "has_go_button"
    HAS_CLAIMABLE_REWARD = "has_claimable_reward"
    NO_CLAIMABLE_REWARD = "no_claimable_reward"
    NO_ACTION_NEEDED = "no_action_needed"


@dataclass
class RegionBox:
    name: str
    x: int
    y: int
    width: int
    height: int
    confidence: float = 1.0


def _box_to_dict(box):
    if box is None:
        return None
    return {
        "name": str(getattr(box, "name", "")),
        "x": int(getattr(box, "x", 0)),
        "y": int(getattr(box, "y", 0)),
        "width": int(getattr(box, "width", 0)),
        "height": int(getattr(box, "height", 0)),
        "confidence": float(getattr(box, "confidence", 1.0)),
    }


@dataclass
class DailyMilestoneReward:
    value: int
    box: object
    claimable: bool
    locked: bool

    def to_dict(self):
        return {
            "value": self.value,
            "box": _box_to_dict(self.box),
            "claimable": self.claimable,
            "locked": self.locked,
        }


@dataclass
class DailyTaskCard:
    title: str = ""
    progress_text: str = ""
    reward_points: int | None = None
    action: str = ""
    button_text: str = ""
    state: str = "unknown"
    box: object | None = None
    action_box: object | None = None
    handler_key: str = ""
    blocked_reason: str = ""

    def to_dict(self):
        return {
            "title": self.title,
            "progress_text": self.progress_text,
            "reward_points": self.reward_points,
            "action": self.action,
            "button_text": self.button_text,
            "state": self.state,
            "box": _box_to_dict(self.box),
            "action_box": _box_to_dict(self.action_box),
            "handler_key": self.handler_key,
            "blocked_reason": self.blocked_reason,
        }


@dataclass
class DailyActivityPage:
    activity_score: int | None = None
    milestone_rewards: list[DailyMilestoneReward] = field(default_factory=list)
    task_cards: list[DailyTaskCard] = field(default_factory=list)
    mission_claim_buttons: list = field(default_factory=list)
    go_buttons: list = field(default_factory=list)

    @property
    def claimable_milestones(self):
        return [reward for reward in self.milestone_rewards if reward.claimable]

    @property
    def locked_milestones(self):
        return [reward for reward in self.milestone_rewards if reward.locked]

    @property
    def claimable_task_cards(self):
        return [card for card in self.task_cards if card.action == "领取"]

    @property
    def go_task_cards(self):
        return [card for card in self.task_cards if card.action == "前往"]

    @property
    def milestone_claimable_values(self):
        return [reward.value for reward in self.claimable_milestones]

    @property
    def milestone_locked_values(self):
        return [reward.value for reward in self.locked_milestones]

    def to_dict(self):
        return {
            "activity_score": self.activity_score,
            "milestone_rewards": [reward.to_dict() for reward in self.milestone_rewards],
            "milestone_claimable": self.milestone_claimable_values,
            "milestone_locked": self.milestone_locked_values,
            "task_cards": [card.to_dict() for card in self.task_cards],
            "mission_claim_buttons": [_box_to_dict(button) for button in self.mission_claim_buttons],
            "go_buttons": [_box_to_dict(button) for button in self.go_buttons],
        }


@dataclass
class DailyActivityAnalysis:
    state: DailyActivityState
    panel_detected: bool
    daily_tab_detected: bool
    activity_full: bool
    all_daily_done: bool
    has_go_button: bool
    has_claimable_reward: bool
    no_claimable_reward: bool
    reason: str = ""
    page: DailyActivityPage | None = None

    def to_dict(self):
        payload = {
            "state": self.state.value,
            "panel_detected": self.panel_detected,
            "daily_tab_detected": self.daily_tab_detected,
            "activity_full": self.activity_full,
            "all_daily_done": self.all_daily_done,
            "has_go_button": self.has_go_button,
            "has_claimable_reward": self.has_claimable_reward,
            "no_claimable_reward": self.no_claimable_reward,
            "reason": self.reason,
        }
        if self.page is not None:
            payload.update(self.page.to_dict())
        return payload


class DailyActivityAnalyzer:
    """Read-only state analyzer for the F1 daily activity tab."""

    DONE_REASON = "今日活跃度已完成"
    UNKNOWN_REASON = "缺少未完成/前往按钮/可领取状态特征"
    ACTIVITY_REWARD_REGION = (0.3427, 0.2009, 0.5292, 0.0454)
    COMPLETED_REWARD_MARKERS = 5
    MIN_MARKER_AREA = 80
    CLAIM_BUTTON_REGION = (0.1400, 0.5600, 0.9300, 0.9000)
    MIN_CLAIM_BUTTON_WIDTH_RATIO = 0.055
    MAX_CLAIM_BUTTON_WIDTH_RATIO = 0.160
    MIN_CLAIM_BUTTON_HEIGHT_RATIO = 0.020
    MAX_CLAIM_BUTTON_HEIGHT_RATIO = 0.075
    MIN_CLAIM_BUTTON_AREA = 350
    PINK_HSV_LOWER = np.array([145, 80, 120], dtype=np.uint8)
    PINK_HSV_UPPER = np.array([175, 255, 255], dtype=np.uint8)
    BLUE_HSV_LOWER = np.array([90, 65, 100], dtype=np.uint8)
    BLUE_HSV_UPPER = np.array([125, 255, 255], dtype=np.uint8)
    WHITE_HSV_LOWER = np.array([0, 0, 175], dtype=np.uint8)
    WHITE_HSV_UPPER = np.array([179, 70, 255], dtype=np.uint8)
    MILESTONE_VALUES = (20, 40, 60, 80, 100)
    MILESTONE_CENTER_X_RATIOS = (0.356, 0.482, 0.606, 0.730, 0.855)
    MILESTONE_CENTER_Y_RATIO = 0.253
    MILESTONE_BOX_WIDTH_RATIO = 0.045
    MILESTONE_BOX_HEIGHT_RATIO = 0.070
    MIN_BLUE_GIFT_RATIO = 0.020
    PROGRESS_REGION = (0.250, 0.215, 0.855, 0.265)
    PROGRESS_START_X_RATIO = 0.252
    PROGRESS_END_X_RATIO = 0.855
    TASK_CARD_REGION = (0.150, 0.325, 0.930, 0.800)
    GO_BUTTON_REGION = (0.1400, 0.6500, 0.9300, 0.9000)
    MIN_GO_BUTTON_WIDTH_RATIO = 0.055
    MAX_GO_BUTTON_WIDTH_RATIO = 0.180
    MIN_GO_BUTTON_HEIGHT_RATIO = 0.020
    MAX_GO_BUTTON_HEIGHT_RATIO = 0.075
    MIN_GO_BUTTON_AREA = 300

    def __init__(self, ui_context, enable_text_ocr=False):
        self.ui = ReadOnlyUIContext.coerce(ui_context)
        self.enable_text_ocr = enable_text_ocr

    def analyze(self, frame=None, panel_detected=None):
        frame = self.ui.frame if frame is None else frame
        panel_detected = self._detect_panel() if panel_detected is None else bool(panel_detected)
        daily_tab_detected = panel_detected

        if not panel_detected:
            return DailyActivityAnalysis(
                state=DailyActivityState.PANEL_NOT_FOUND,
                panel_detected=False,
                daily_tab_detected=False,
                activity_full=False,
                all_daily_done=False,
                has_go_button=False,
                has_claimable_reward=False,
                no_claimable_reward=False,
                reason="未检测到每日活跃度面板",
            )

        page = self.analyze_page(frame)
        has_claimable_reward = bool(page.mission_claim_buttons)
        activity_full = self._detect_activity_full(frame)
        all_daily_done = activity_full
        has_go_button = bool(page.go_buttons)
        no_claimable_reward = not has_claimable_reward

        if has_claimable_reward:
            state = DailyActivityState.HAS_CLAIMABLE_REWARD
            reason = "检测到可领取每日任务奖励"
        elif activity_full or all_daily_done:
            state = DailyActivityState.NO_ACTION_NEEDED
            reason = self.DONE_REASON
        else:
            state = DailyActivityState.UNKNOWN
            reason = self.UNKNOWN_REASON

        return DailyActivityAnalysis(
            state=state,
            panel_detected=panel_detected,
            daily_tab_detected=daily_tab_detected,
            activity_full=activity_full,
            all_daily_done=all_daily_done,
            has_go_button=has_go_button,
            has_claimable_reward=has_claimable_reward,
            no_claimable_reward=no_claimable_reward,
            reason=reason,
            page=page,
        )

    def analyze_page(self, frame=None):
        frame = self.ui.frame if frame is None else frame
        mission_claim_buttons = self.find_claimable_mission_buttons(frame)
        go_buttons = self.find_go_buttons(frame)
        page = DailyActivityPage(
            activity_score=self.detect_activity_score(frame),
            milestone_rewards=self.find_milestone_rewards(frame),
            mission_claim_buttons=mission_claim_buttons,
            go_buttons=go_buttons,
        )
        page.task_cards = self.find_task_cards(frame, mission_claim_buttons, go_buttons)
        return page

    def _detect_panel(self):
        return bool(F1PanelDetector(self.ui).find_daily_activity_panel())

    def _detect_claimable_reward(self, frame):
        return bool(self.find_claimable_mission_buttons(frame))

    def find_claimable_mission_buttons(self, frame=None):
        frame = self.ui.frame if frame is None else frame
        if frame is None:
            return []

        shape = getattr(frame, "shape", None)
        if shape is None or len(shape) < 2:
            return []

        height, width = shape[:2]
        search_box = self._claim_button_search_box(width, height)
        crop = self._crop(frame, search_box)
        if crop.size == 0:
            return []

        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, self.PINK_HSV_LOWER, self.PINK_HSV_UPPER)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 9), np.uint8))
        count, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)

        buttons = []
        min_width = width * self.MIN_CLAIM_BUTTON_WIDTH_RATIO
        max_width = width * self.MAX_CLAIM_BUTTON_WIDTH_RATIO
        min_height = height * self.MIN_CLAIM_BUTTON_HEIGHT_RATIO
        max_height = height * self.MAX_CLAIM_BUTTON_HEIGHT_RATIO

        for index in range(1, count):
            x, y, box_width, box_height, area = stats[index]
            if area < self.MIN_CLAIM_BUTTON_AREA:
                continue
            if not (min_width <= box_width <= max_width):
                continue
            if not (min_height <= box_height <= max_height):
                continue

            buttons.append(
                Box(
                    int(search_box.x + x),
                    int(search_box.y + y),
                    int(box_width),
                    int(box_height),
                    name=Labels.f1_activity_mission.value,
                    confidence=1.0,
                )
            )

        return sorted(buttons, key=lambda box: (box.y, box.x))

    def find_milestone_rewards(self, frame=None):
        frame = self.ui.frame if frame is None else frame
        if frame is None:
            return []

        shape = getattr(frame, "shape", None)
        if shape is None or len(shape) < 2:
            return []

        height, width = shape[:2]
        rewards = []
        for value, center_x_ratio in zip(self.MILESTONE_VALUES, self.MILESTONE_CENTER_X_RATIOS):
            box = self._milestone_box(width, height, value, center_x_ratio)
            crop = self._crop(frame, box)
            claimable = self._blue_pixel_ratio(crop) >= self.MIN_BLUE_GIFT_RATIO
            rewards.append(
                DailyMilestoneReward(
                    value=value,
                    box=box,
                    claimable=claimable,
                    locked=not claimable,
                )
            )
        return rewards

    def detect_activity_score(self, frame=None):
        frame = self.ui.frame if frame is None else frame
        score = self._detect_activity_score_from_ocr(frame)
        if score is not None:
            return score
        return self._detect_activity_score_from_progress(frame)

    def find_go_buttons(self, frame=None):
        frame = self.ui.frame if frame is None else frame
        if frame is None:
            return []

        shape = getattr(frame, "shape", None)
        if shape is None or len(shape) < 2:
            return []

        height, width = shape[:2]
        search_box = self._go_button_search_box(width, height)
        crop = self._crop(frame, search_box)
        if crop.size == 0:
            return []

        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, self.WHITE_HSV_LOWER, self.WHITE_HSV_UPPER)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 11), np.uint8))
        count, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)

        buttons = []
        min_width = width * self.MIN_GO_BUTTON_WIDTH_RATIO
        max_width = width * self.MAX_GO_BUTTON_WIDTH_RATIO
        min_height = height * self.MIN_GO_BUTTON_HEIGHT_RATIO
        max_height = height * self.MAX_GO_BUTTON_HEIGHT_RATIO

        for index in range(1, count):
            x, y, box_width, box_height, area = stats[index]
            if area < self.MIN_GO_BUTTON_AREA:
                continue
            if not (min_width <= box_width <= max_width):
                continue
            if not (min_height <= box_height <= max_height):
                continue

            buttons.append(
                Box(
                    int(search_box.x + x),
                    int(search_box.y + y),
                    int(box_width),
                    int(box_height),
                    name="daily_activity_go_button",
                    confidence=1.0,
                )
            )

        return sorted(buttons, key=lambda box: (box.y, box.x))

    def find_task_cards(self, frame=None, mission_claim_buttons=None, go_buttons=None):
        frame = self.ui.frame if frame is None else frame
        mission_claim_buttons = list(mission_claim_buttons or self.find_claimable_mission_buttons(frame))
        go_buttons = list(go_buttons or self.find_go_buttons(frame))
        ocr_boxes = self._ocr_boxes(self.TASK_CARD_REGION, frame)
        cards = []

        for action, action_box in [
            *[("领取", button) for button in mission_claim_buttons],
            *[("前往", button) for button in go_buttons],
        ]:
            card_box = self._task_card_box_for_action(action_box, frame)
            texts = self._texts_in_card(ocr_boxes, card_box, action_box)
            button_text = self._button_text_for_action_box(ocr_boxes, action_box)
            resolved_action = self._resolve_button_action(action, button_text)
            title = self._select_task_title(texts, action)
            cards.append(
                DailyTaskCard(
                    title=title,
                    progress_text=self._select_progress_text(texts),
                    reward_points=self._select_reward_points(texts),
                    action=resolved_action,
                    button_text=button_text,
                    state=self._task_card_state_for_action(resolved_action),
                    box=card_box,
                    action_box=action_box,
                )
            )

        return sorted(cards, key=lambda card: (getattr(card.action_box, "y", 0), getattr(card.action_box, "x", 0)))

    @staticmethod
    def _task_card_state_for_action(action):
        if action == "领取":
            return "claimable"
        if action == "前往":
            return "go"
        if action == "完成":
            return "completable"
        return "unknown"

    @staticmethod
    def _resolve_button_action(detected_action, button_text):
        text = str(button_text or "").strip()
        if "领取" in text:
            return "领取"
        if "完成" in text:
            return "完成"
        if "前往" in text:
            return "前往"
        if text:
            return "unknown"
        return detected_action

    def _claim_button_search_box(self, width, height):
        x, y, to_x, to_y = self.CLAIM_BUTTON_REGION
        return RegionBox(
            name="daily_activity_claim_button_region",
            x=int(width * x),
            y=int(height * y),
            width=int(width * (to_x - x)),
            height=int(height * (to_y - y)),
        )

    def _go_button_search_box(self, width, height):
        x, y, to_x, to_y = self.GO_BUTTON_REGION
        return RegionBox(
            name="daily_activity_go_button_region",
            x=int(width * x),
            y=int(height * y),
            width=int(width * (to_x - x)),
            height=int(height * (to_y - y)),
        )

    def _milestone_box(self, width, height, value, center_x_ratio):
        box_width = max(1, int(width * self.MILESTONE_BOX_WIDTH_RATIO))
        box_height = max(1, int(height * self.MILESTONE_BOX_HEIGHT_RATIO))
        center_x = int(width * center_x_ratio)
        center_y = int(height * self.MILESTONE_CENTER_Y_RATIO)
        return Box(
            int(center_x - box_width / 2),
            int(center_y - box_height / 2),
            box_width,
            box_height,
            name=f"daily_activity_milestone_{value}",
            confidence=1.0,
        )

    def _detect_activity_score_from_ocr(self, frame):
        boxes = self._ocr_boxes((0.120, 0.150, 0.285, 0.300), frame)
        text = " ".join(self._box_text(box) for box in boxes)
        matches = [int(match) for match in re.findall(r"\b([0-9]{1,3})\b", text)]
        matches = [value for value in matches if 0 <= value <= 100]
        if not matches:
            return None
        return max(matches)

    def _detect_activity_score_from_progress(self, frame):
        if frame is None:
            return None

        shape = getattr(frame, "shape", None)
        if shape is None or len(shape) < 2:
            return None

        height, width = shape[:2]
        x, y, to_x, to_y = self.PROGRESS_REGION
        progress_box = RegionBox(
            name="daily_activity_progress_region",
            x=int(width * x),
            y=int(height * y),
            width=int(width * (to_x - x)),
            height=int(height * (to_y - y)),
        )
        crop = self._crop(frame, progress_box)
        if crop.size == 0:
            return None

        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        cyan_mask = cv2.inRange(
            hsv,
            np.array([80, 70, 90], dtype=np.uint8),
            np.array([110, 255, 255], dtype=np.uint8),
        )
        ys, xs = np.where(cyan_mask > 0)
        if len(xs) < 20:
            return None

        max_x = progress_box.x + int(np.percentile(xs, 98))
        start_x = width * self.PROGRESS_START_X_RATIO
        end_x = width * self.PROGRESS_END_X_RATIO
        if end_x <= start_x:
            return None
        score = (max_x - start_x) / (end_x - start_x) * 100
        score = int(round(max(0, min(100, score)) / 10) * 10)
        return score

    def _ocr_boxes(self, region, frame):
        if not self.enable_text_ocr:
            return []

        x, y, to_x, to_y = region
        try:
            result = self.ui.ocr_ui(x, y, to_x=to_x, to_y=to_y, frame=frame)
        except Exception:
            return []
        if result is None or isinstance(result, (str, bytes)):
            return []
        try:
            return list(result)
        except TypeError:
            return []

    @staticmethod
    def _box_text(box):
        text = getattr(box, "text", None)
        if text:
            return str(text)
        return str(getattr(box, "name", ""))

    def _texts_in_card(self, boxes, card_box, action_box):
        if not boxes or card_box is None or action_box is None:
            return []

        action_center_y = getattr(action_box, "y", 0) + getattr(action_box, "height", 0) / 2
        left = getattr(card_box, "x", 0)
        right = left + getattr(card_box, "width", 0)
        top = getattr(card_box, "y", 0)
        bottom = getattr(card_box, "y", 0) + getattr(card_box, "height", 0)
        texts = []

        for box in boxes:
            box_center_x = getattr(box, "x", 0) + getattr(box, "width", 0) / 2
            box_center_y = getattr(box, "y", 0) + getattr(box, "height", 0) / 2
            if not (left <= box_center_x <= right):
                continue
            if not (top <= box_center_y <= min(bottom, action_center_y + 20)):
                continue
            text = self._box_text(box).strip()
            if text:
                texts.append(text)
        return texts

    def _button_text_for_action_box(self, boxes, action_box):
        if not boxes or action_box is None:
            return ""
        left = getattr(action_box, "x", 0) - 8
        right = getattr(action_box, "x", 0) + getattr(action_box, "width", 0) + 8
        top = getattr(action_box, "y", 0) - 8
        bottom = getattr(action_box, "y", 0) + getattr(action_box, "height", 0) + 8
        texts = []
        for box in boxes:
            center_x = getattr(box, "x", 0) + getattr(box, "width", 0) / 2
            center_y = getattr(box, "y", 0) + getattr(box, "height", 0) / 2
            if not (left <= center_x <= right and top <= center_y <= bottom):
                continue
            text = self._box_text(box).strip()
            if text:
                texts.append(text)
        return "".join(texts)

    @staticmethod
    def _select_task_title(texts, action):
        ignored = {"前往", "完成", "领取", "daily_activity_go_button", Labels.f1_activity_mission.value}
        candidates = []
        for text in texts:
            cleaned = text.strip()
            if not cleaned or cleaned in ignored:
                continue
            if _is_progress_text(cleaned):
                continue
            if _is_signed_integer_text(cleaned):
                continue
            if cleaned.startswith("+") and any(char.isdigit() for char in cleaned):
                continue
            candidates.append(cleaned)
        return max(candidates, key=len) if candidates else ""

    @staticmethod
    def _select_progress_text(texts):
        for text in texts:
            progress = _extract_progress_text(text)
            if progress:
                return progress
        return ""

    @staticmethod
    def _select_reward_points(texts):
        for text in texts:
            points = _extract_reward_points(text)
            if points is not None:
                return points
        return None

    def _task_card_box_for_action(self, action_box, frame):
        if action_box is None:
            return None
        shape = getattr(frame, "shape", None)
        width = int(shape[1]) if shape is not None and len(shape) >= 2 else self.ui.width
        height = int(shape[0]) if shape is not None and len(shape) >= 2 else self.ui.height
        card_width = max(int(width * 0.140), int(getattr(action_box, "width", 0) * 1.35))
        card_height = max(int(height * 0.330), int(getattr(action_box, "height", 0) * 5))
        x = int(getattr(action_box, "x", 0) + getattr(action_box, "width", 0) / 2 - card_width / 2)
        y = int(getattr(action_box, "y", 0) + getattr(action_box, "height", 0) - card_height)
        return RegionBox(
            name="daily_activity_task_card",
            x=max(0, x),
            y=max(0, y),
            width=card_width,
            height=card_height,
        )

    def _blue_pixel_ratio(self, frame):
        if frame is None or frame.size == 0:
            return 0.0
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, self.BLUE_HSV_LOWER, self.BLUE_HSV_UPPER)
        return float(np.count_nonzero(mask)) / float(mask.size)

    def _detect_activity_full(self, frame):
        if frame is None:
            return False

        reward_box = self._get_reward_box()
        reward_frame = self._crop(frame, reward_box)
        if reward_frame.size == 0:
            return False

        return self._count_completed_reward_markers(reward_frame) >= self.COMPLETED_REWARD_MARKERS

    def _get_reward_box(self):
        x, y, w, h = self.ACTIVITY_REWARD_REGION
        box = self.ui.box_of_ui(
            x,
            y,
            width=w,
            height=h,
            name=Labels.box_f1_activity_reward.value,
        )
        if box is not None:
            return box

        box = self.ui.get_box_by_name(Labels.box_f1_activity_reward)
        if box is not None:
            return box

        width = self.ui.width
        height = self.ui.height
        return RegionBox(
            name=str(Labels.box_f1_activity_reward),
            x=int(width * x),
            y=int(height * y),
            width=int(width * w),
            height=int(height * h),
        )

    @staticmethod
    def _crop(frame, box):
        x = max(0, int(getattr(box, "x", 0)))
        y = max(0, int(getattr(box, "y", 0)))
        width = max(0, int(getattr(box, "width", 0)))
        height = max(0, int(getattr(box, "height", 0)))
        return frame[y : y + height, x : x + width]

    def _count_completed_reward_markers(self, reward_frame):
        hsv = cv2.cvtColor(reward_frame, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, self.PINK_HSV_LOWER, self.PINK_HSV_UPPER)
        count, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
        components = 0
        for index in range(1, count):
            if stats[index, cv2.CC_STAT_AREA] >= self.MIN_MARKER_AREA:
                components += 1
        return components
