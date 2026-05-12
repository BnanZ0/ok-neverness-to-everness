from dataclasses import dataclass

from ok import Box

from src.Labels import Labels
from src.tasks.DailyUIContext import ReadOnlyUIContext
from src.utils.viewport_adapter import LAYOUT_PROFILE_NATIVE_16_9, LAYOUT_PROFILE_NATIVE_16_10


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


@dataclass
class FeatureProbeBox:
    name: str
    x: int
    y: int
    width: int
    height: int
    confidence: float = 1.0


class F1PanelDetector:
    """Detect and probe F1 daily panel state without executing daily actions."""

    NATIVE_16_10_DAILY_SELECTED_TAB_REGION = (0.035, 0.300, 0.120, 0.365)
    NATIVE_16_10_DAILY_PROGRESS_REGION = (0.130, 0.270, 0.360, 0.470)
    NATIVE_16_10_DAILY_CONTENT_REGION = (0.400, 0.130, 0.970, 0.870)
    NATIVE_16_10_DAILY_PANEL_REGION = (0.100, 0.120, 0.980, 0.900)
    NATIVE_16_9_DAILY_SELECTED_TAB_REGION = (0.035, 0.130, 0.120, 0.310)
    NATIVE_16_9_DAILY_PROGRESS_REGION = (0.130, 0.270, 0.360, 0.470)
    NATIVE_16_9_DAILY_CONTENT_REGION = (0.400, 0.130, 0.970, 0.870)
    NATIVE_16_9_DAILY_PANEL_REGION = (0.030, 0.090, 0.980, 0.930)
    MIN_DAILY_TAB_WHITE_RATIO = 0.04
    MIN_DAILY_PROGRESS_CYAN_RATIO = 0.02
    MIN_DAILY_CONTENT_WHITE_RATIO = 0.02
    PROBE_LABELS = (
        Labels.f1_panel,
        Labels.f1_activity_panel,
        Labels.f1_activity_mission,
        Labels.box_f1_activity_reward,
    )
    PROBE_THRESHOLDS = (0.85, 0.8, 0.75, 0.7, 0.65)
    PROBE_REGION_DEFINITIONS = {
        "default_search": None,
        "full_screen": (0.0, 0.0, 1.0, 1.0),
        "f1_main_panel": (0.02, 0.05, 0.98, 0.95),
        "left_tabs": (0.0, 0.12, 0.18, 0.90),
        "right_content": (0.18, 0.10, 0.98, 0.95),
        "top_bar": (0.0, 0.0, 1.0, 0.16),
    }

    def __init__(self, ui_context):
        self.ui = ReadOnlyUIContext.coerce(ui_context)

    def layout_profile(self):
        return self.ui.get_ui_layout_profile()

    def make_open_result(
        self,
        f1_panel_opened,
        daily_tab_clicked,
        daily_activity_panel_detected=None,
    ):
        layout_profile = self.layout_profile()
        if daily_activity_panel_detected is None:
            daily_activity_panel_detected = bool(self.find_daily_activity_panel())

        if daily_activity_panel_detected:
            reason = "每日活跃度面板已识别"
        elif f1_panel_opened and daily_tab_clicked:
            width = self.ui.width
            height = self.ui.height
            reason = (
                f"当前分辨率为 {width}x{height} {layout_profile}，F1 面板已打开并已点击每日第2栏目，"
                "但 f1_activity_panel 模板和结构检测未命中。"
            )
        elif not f1_panel_opened:
            reason = "未检测到 F1 面板"
        else:
            reason = "已打开 F1 面板，但未确认每日第2栏目点击"

        return DailyPanelOpenResult(
            f1_panel_opened=bool(f1_panel_opened),
            daily_tab_clicked=bool(daily_tab_clicked),
            daily_activity_panel_detected=bool(daily_activity_panel_detected),
            layout_profile=layout_profile,
            reason=reason,
        )

    def find_f1_panel(self):
        return self._find_label_with_native_fallback(Labels.f1_panel)

    def find_daily_activity_panel(self):
        result = self._find_label_with_native_fallback(Labels.f1_activity_panel)
        if result:
            return result
        result = self.find_native_16_10_daily_activity_panel()
        if result:
            return result
        return self.find_native_16_9_daily_activity_panel()

    def find_native_16_10_daily_activity_panel(self):
        probe = self._probe_native_16_10_daily_structure()
        if not probe.get("matched"):
            return None

        x, y, width, height = probe["box"]
        return Box(
            x,
            y,
            width,
            height,
            name="native_16_10_daily_activity_panel",
            confidence=probe.get("confidence", 1.0),
        )

    def find_native_16_9_daily_activity_panel(self):
        probe = self._probe_native_16_9_daily_structure()
        if not probe.get("matched"):
            return None

        x, y, width, height = probe["box"]
        return Box(
            x,
            y,
            width,
            height,
            name="native_16_9_daily_activity_panel",
            confidence=probe.get("confidence", 1.0),
        )

    def probe_features(self):
        probe = {
            self._label_name(label): {
                region_name: self._probe_label_in_region(label, region_name, region)
                for region_name, region in self.PROBE_REGION_DEFINITIONS.items()
            }
            for label in self.PROBE_LABELS
        }
        probe["native_16_10_daily_panel"] = {
            "structure": self._probe_native_16_10_daily_structure()
        }
        probe["native_16_9_daily_panel"] = {
            "structure": self._probe_native_16_9_daily_structure()
        }
        return probe

    def probe_boxes(self, probe):
        boxes = []
        for label_name, regions in probe.items():
            for region_name, result in regions.items():
                if not result.get("matched") or "box" not in result:
                    continue
                x, y, width, height = result["box"]
                boxes.append(
                    FeatureProbeBox(
                        name=f"probe_{label_name}_{region_name}",
                        x=x,
                        y=y,
                        width=width,
                        height=height,
                        confidence=result.get("confidence", 1.0),
                    )
                )
        return boxes

    def _find_label_with_native_fallback(self, label):
        result = self.ui.find_one(label)
        if result:
            return result

        if self.layout_profile() != "native_16_10":
            return None

        region_name = "top_bar" if label == Labels.f1_panel else "f1_main_panel"
        search_box = self._make_region_box(region_name, self.PROBE_REGION_DEFINITIONS[region_name])
        return self.ui.find_one(label, box=search_box, threshold=0.75)

    def _probe_label_in_region(self, label, region_name, region):
        box = None if region is None else self._make_region_box(region_name, region)
        for threshold in self.PROBE_THRESHOLDS:
            try:
                result = self.ui.find_one(label, box=box, threshold=threshold)
            except Exception as exc:
                return {
                    "matched": False,
                    "error": str(exc),
                }
            if result:
                return {
                    "matched": True,
                    "threshold": threshold,
                    "box": self._box_pixels(result),
                    "confidence": getattr(result, "confidence", None),
                }

        return {
            "matched": False,
        }

    def _probe_native_16_10_daily_structure(self):
        if self.layout_profile() != LAYOUT_PROFILE_NATIVE_16_10:
            return {
                "matched": False,
                "reason": "layout is not native_16_10",
            }

        f1_panel = self.find_f1_panel()
        if not f1_panel:
            return {
                "matched": False,
                "reason": "f1_panel anchor not found",
            }

        frame = self._current_frame()
        if frame is None:
            return {
                "matched": False,
                "reason": "frame is unavailable",
            }

        selected_tab_white_ratio = self._color_ratio(
            frame,
            self.NATIVE_16_10_DAILY_SELECTED_TAB_REGION,
            lambda b, g, r: (b > 190) & (g > 190) & (r > 190),
        )
        progress_cyan_ratio = self._color_ratio(
            frame,
            self.NATIVE_16_10_DAILY_PROGRESS_REGION,
            lambda b, g, r: (b > 120) & (g > 170) & (r < 140),
        )
        content_white_ratio = self._color_ratio(
            frame,
            self.NATIVE_16_10_DAILY_CONTENT_REGION,
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
            "thresholds": {
                "selected_tab_white_ratio": self.MIN_DAILY_TAB_WHITE_RATIO,
                "progress_cyan_ratio": self.MIN_DAILY_PROGRESS_CYAN_RATIO,
                "content_white_ratio": self.MIN_DAILY_CONTENT_WHITE_RATIO,
            },
        }
        if matched:
            result["box"] = self._box_pixels(
                self._make_region_box(
                    "native_16_10_daily_activity_panel",
                    self.NATIVE_16_10_DAILY_PANEL_REGION,
                )
            )
            result["confidence"] = min(
                1.0,
                selected_tab_white_ratio / self.MIN_DAILY_TAB_WHITE_RATIO,
            )
        else:
            result["reason"] = "native_16_10 daily structure not matched"
        return result

    def _probe_native_16_9_daily_structure(self):
        if self.layout_profile() != LAYOUT_PROFILE_NATIVE_16_9:
            return {
                "matched": False,
                "reason": "layout is not native_16_9",
            }

        f1_panel_anchor_found = bool(self.find_f1_panel())

        frame = self._current_frame()
        if frame is None:
            return {
                "matched": False,
                "reason": "frame is unavailable",
            }

        selected_tab_white_ratio = self._color_ratio(
            frame,
            self.NATIVE_16_9_DAILY_SELECTED_TAB_REGION,
            lambda b, g, r: (b > 190) & (g > 190) & (r > 190),
        )
        progress_cyan_ratio = self._color_ratio(
            frame,
            self.NATIVE_16_9_DAILY_PROGRESS_REGION,
            lambda b, g, r: (b > 120) & (g > 170) & (r < 160),
        )
        content_white_ratio = self._color_ratio(
            frame,
            self.NATIVE_16_9_DAILY_CONTENT_REGION,
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
            "f1_panel_anchor_found": f1_panel_anchor_found,
            "selected_tab_white_ratio": selected_tab_white_ratio,
            "progress_cyan_ratio": progress_cyan_ratio,
            "content_white_ratio": content_white_ratio,
            "thresholds": {
                "selected_tab_white_ratio": self.MIN_DAILY_TAB_WHITE_RATIO,
                "progress_cyan_ratio": self.MIN_DAILY_PROGRESS_CYAN_RATIO,
                "content_white_ratio": self.MIN_DAILY_CONTENT_WHITE_RATIO,
            },
        }
        if matched:
            result["box"] = self._box_pixels(
                self._make_region_box(
                    "native_16_9_daily_activity_panel",
                    self.NATIVE_16_9_DAILY_PANEL_REGION,
                )
            )
            result["confidence"] = min(
                1.0,
                selected_tab_white_ratio / self.MIN_DAILY_TAB_WHITE_RATIO,
            )
        else:
            result["reason"] = "native_16_9 daily structure not matched"
        return result

    def _current_frame(self):
        return self.ui.frame

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

    def _make_region_box(self, name, region):
        x, y, to_x, to_y = region
        box = self.ui.box_of_ui(x, y, to_x=to_x, to_y=to_y, name=name)
        if box is not None:
            return box

        width = self.ui.width
        height = self.ui.height
        return Box(
            int(width * x),
            int(height * y),
            int(width * (to_x - x)),
            int(height * (to_y - y)),
            name=name,
            confidence=1.0,
        )

    @staticmethod
    def _box_pixels(box):
        return [
            int(getattr(box, "x", 0)),
            int(getattr(box, "y", 0)),
            int(getattr(box, "width", 0)),
            int(getattr(box, "height", 0)),
        ]

    @staticmethod
    def _label_name(label):
        return getattr(label, "value", str(label))
