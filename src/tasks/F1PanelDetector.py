from dataclasses import dataclass

from ok import Box

from src.Labels import Labels


LAYOUT_PROFILE_NATIVE_16_9 = "native_16_9"
LAYOUT_PROFILE_NATIVE_UNKNOWN = "native_unknown"


@dataclass
class DailyPanelOpenResult:
    f1_panel_opened: bool
    daily_tab_clicked: bool
    daily_activity_panel_detected: bool
    layout_profile: str
    reason: str = ""

    def to_dict(self):
        return {
            "f1_panel_opened": self.f1_panel_opened,
            "daily_tab_clicked": self.daily_tab_clicked,
            "daily_activity_panel_detected": self.daily_activity_panel_detected,
            "layout_profile": self.layout_profile,
            "reason": self.reason,
        }


class F1PanelDetector:
    """识别真正的 F1 每日活跃面板，并拒绝 F1 内其他页面误判。"""

    NATIVE_16_9_DAILY_SELECTED_TAB_REGION = (0.035, 0.330, 0.120, 0.430)
    NATIVE_16_9_DAILY_PROGRESS_REGION = (0.130, 0.270, 0.360, 0.470)
    NATIVE_16_9_DAILY_CONTENT_REGION = (0.400, 0.130, 0.970, 0.870)
    NATIVE_16_9_DAILY_PANEL_REGION = (0.030, 0.090, 0.980, 0.930)
    MIN_DAILY_TAB_WHITE_RATIO = 0.04
    MIN_DAILY_PROGRESS_CYAN_RATIO = 0.02
    MIN_DAILY_CONTENT_WHITE_RATIO = 0.02

    def __init__(self, task):
        self.task = task

    def wait_daily_activity_panel(self, time_out=4.5):
        waiter = getattr(self.task, "wait_until", None)
        if not callable(waiter):
            return self.find_daily_activity_panel()
        return waiter(
            self.find_daily_activity_panel,
            time_out=time_out,
            settle_time=0.5,
        )

    def make_open_result(
        self,
        f1_panel_opened,
        daily_tab_clicked,
        daily_activity_panel_detected=None,
        reason="",
    ):
        if daily_activity_panel_detected is None:
            daily_activity_panel_detected = bool(self.find_daily_activity_panel())
        if daily_activity_panel_detected:
            reason = "每日活跃度面板已识别"
        elif not reason:
            reason = "未确认当前页面是每日活跃度面板"
        return DailyPanelOpenResult(
            f1_panel_opened=bool(f1_panel_opened),
            daily_tab_clicked=bool(daily_tab_clicked),
            daily_activity_panel_detected=bool(daily_activity_panel_detected),
            layout_profile=self.layout_profile(),
            reason=reason,
        )

    def find_daily_activity_panel(self):
        label_match = self._find_label(Labels.f1_activity_panel)
        structure = self.probe_daily_activity_structure()
        if structure.get("matched"):
            return label_match or self._box_for_region(
                structure.get("box_name", "native_daily_activity_panel"),
                structure["panel_region"],
                confidence=structure.get("confidence", 1.0),
            )
        if label_match:
            self._log_info(
                "检测到活跃面板模板，但每日活跃页签或内容结构未命中，"
                "忽略可能的 F1 非日常页面误识别"
            )
        return None

    def probe_daily_activity_structure(self):
        profile = self.layout_profile()
        if profile == LAYOUT_PROFILE_NATIVE_16_9:
            return self._probe_daily_structure(
                selected_tab_region=self.NATIVE_16_9_DAILY_SELECTED_TAB_REGION,
                progress_region=self.NATIVE_16_9_DAILY_PROGRESS_REGION,
                content_region=self.NATIVE_16_9_DAILY_CONTENT_REGION,
                panel_region=self.NATIVE_16_9_DAILY_PANEL_REGION,
                box_name="native_16_9_daily_activity_panel",
            )
        return {
            "matched": False,
            "reason": f"unsupported layout profile: {profile}",
        }

    def layout_profile(self):
        getter = getattr(self.task, "get_ui_layout_profile", None)
        if callable(getter):
            profile = getter()
            if profile:
                return profile

        width, height = self._screen_size()
        if width <= 0 or height <= 0:
            return LAYOUT_PROFILE_NATIVE_UNKNOWN
        ratio = width / height
        if abs(ratio - (16 / 9)) < 0.02:
            return LAYOUT_PROFILE_NATIVE_16_9
        return LAYOUT_PROFILE_NATIVE_UNKNOWN

    def _probe_daily_structure(
        self,
        *,
        selected_tab_region,
        progress_region,
        content_region,
        panel_region,
        box_name,
    ):
        frame = self._current_frame()
        if frame is None:
            return {
                "matched": False,
                "reason": "frame is unavailable",
            }

        selected_tab_white_ratio = self._color_ratio(
            frame,
            selected_tab_region,
            lambda b, g, r: (b > 190) & (g > 190) & (r > 190),
        )
        progress_cyan_ratio = self._color_ratio(
            frame,
            progress_region,
            lambda b, g, r: (b > 120) & (g > 170) & (r < 160),
        )
        content_white_ratio = self._color_ratio(
            frame,
            content_region,
            lambda b, g, r: (b > 190) & (g > 190) & (r > 190),
        )
        matched = (
            selected_tab_white_ratio >= self.MIN_DAILY_TAB_WHITE_RATIO
            and (
                progress_cyan_ratio >= self.MIN_DAILY_PROGRESS_CYAN_RATIO
                or content_white_ratio >= self.MIN_DAILY_CONTENT_WHITE_RATIO
            )
        )
        result = {
            "matched": matched,
            "selected_tab_white_ratio": selected_tab_white_ratio,
            "progress_cyan_ratio": progress_cyan_ratio,
            "content_white_ratio": content_white_ratio,
            "panel_region": panel_region,
            "box_name": box_name,
            "thresholds": {
                "selected_tab_white_ratio": self.MIN_DAILY_TAB_WHITE_RATIO,
                "progress_cyan_ratio": self.MIN_DAILY_PROGRESS_CYAN_RATIO,
                "content_white_ratio": self.MIN_DAILY_CONTENT_WHITE_RATIO,
            },
        }
        if matched:
            result["confidence"] = min(
                1.0,
                selected_tab_white_ratio / self.MIN_DAILY_TAB_WHITE_RATIO,
            )
        else:
            result["reason"] = "daily activity structure not matched"
        return result

    def _find_label(self, label):
        finder = getattr(self.task, "find_one", None)
        if not callable(finder):
            return None
        return finder(label)

    def _current_frame(self):
        try:
            return getattr(self.task, "frame", None)
        except Exception:
            return None

    def _screen_size(self):
        width = int(getattr(self.task, "width", 0) or 0)
        height = int(getattr(self.task, "height", 0) or 0)
        if width > 0 and height > 0:
            return width, height
        frame = self._current_frame()
        shape = getattr(frame, "shape", None)
        if shape is not None and len(shape) >= 2:
            return int(shape[1]), int(shape[0])
        return width, height

    def _box_for_region(self, name, region, confidence=1.0):
        width, height = self._screen_size()
        x, y, to_x, to_y = region
        return Box(
            int(width * x),
            int(height * y),
            int(width * (to_x - x)),
            int(height * (to_y - y)),
            name=name,
            confidence=confidence,
        )

    @staticmethod
    def _color_ratio(frame, region, mask_factory):
        shape = getattr(frame, "shape", None)
        if shape is None or len(shape) < 2:
            return 0.0

        height, width = shape[:2]
        x1, y1, x2, y2 = region
        left = max(0, min(width, int(width * x1)))
        top = max(0, min(height, int(height * y1)))
        right = max(0, min(width, int(width * x2)))
        bottom = max(0, min(height, int(height * y2)))
        if right <= left or bottom <= top:
            return 0.0

        crop = frame[top:bottom, left:right]
        if crop.size == 0:
            return 0.0

        b = crop[:, :, 0]
        g = crop[:, :, 1]
        r = crop[:, :, 2]
        return float(mask_factory(b, g, r).mean())

    def _log_info(self, message):
        logger = getattr(self.task, "log_info", None)
        if callable(logger):
            logger(message)
