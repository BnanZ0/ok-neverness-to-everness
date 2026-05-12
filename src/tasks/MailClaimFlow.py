import cv2
import numpy as np
from ok import Box, CannotFindException

from src.Labels import Labels


class MailClaimFlow:
    """Mail claim UI flow extracted from DailyTask.

    The flow intentionally delegates UI operations to the owning task so the
    existing input, OCR, viewport, logging, and wait behavior stay unchanged.
    """

    def __init__(self, task):
        self.task = task

    def __getattr__(self, name):
        return getattr(self.task, name)

    def claim(self):
        """领取邮件"""
        self.log_info("正在领取邮件奖励")
        self.open_mail_panel()
        self.click_ui(0.1289, 0.9299)
        self.sleep(1)
        return True

    def open_mail_panel(self):
        """打开mail panel。"""
        self.log_info("正在打开邮件面板")
        panel = self.resolve_mail_phone_menu(self.open_esc_panel_for_mail())
        clicked_phone_mail = self.click_mail_button_from_phone_menu(panel)
        if not clicked_phone_mail:
            self.click_ui(*self.MAIL_BUTTON_POSITION, after_sleep=1, move=True, down_time=0.01)
        result = self.wait_panel(Labels.mail_panel, time_out=self.MAIL_PANEL_WAIT_TIMEOUT)
        if not result:
            if clicked_phone_mail:
                self.log_info("邮件图标点击后未检测到邮件面板，重新打开手机菜单重试一次")
                panel = self.resolve_mail_phone_menu(self.open_esc_panel_for_mail())
                self.click_mail_button_from_phone_menu(panel)
            else:
                self.click_ui(*self.MAIL_BUTTON_RETRY_POSITION, after_sleep=1, move=True, down_time=0.01)
            result = self.wait_panel(Labels.mail_panel, time_out=self.MAIL_PANEL_WAIT_TIMEOUT)
        if not result:
            self.log_error("无法找到邮件面板", notify=True)
            raise CannotFindException("can't find mail panel")
        return result

    def resolve_mail_phone_menu(self, panel):
        if self.is_phone_menu_box(panel):
            return panel
        try:
            phone_menu = self.wait_mail_phone_menu()
        except Exception:
            phone_menu = None
        if phone_menu:
            self.log_info("ESC 面板已打开手机菜单，切换为手机菜单区域识别邮件入口")
            return phone_menu
        return panel

    def click_mail_button_from_phone_menu(self, panel):
        if not self.is_phone_menu_box(panel):
            return False
        target = self.find_mail_icon_from_phone_menu(panel)
        if target is not None:
            x = self.box_center_x(target)
            y = self.box_center_y(target)
            self.log_info("识别到手机菜单底栏信封图标，点击图标中心")
        else:
            x = getattr(panel, "x", 0) + getattr(panel, "width", 0) * self.MAIL_PHONE_MENU_MAIL_BUTTON_RATIO[0]
            y = getattr(panel, "y", 0) + getattr(panel, "height", 0) * self.MAIL_PHONE_MENU_MAIL_BUTTON_RATIO[1]
            self.log_info("识别到手机菜单，未分离信封图标，使用底栏邮件入口兜底点")
        self.click(
            int(x),
            int(y),
            move=True,
            down_time=self.MAIL_PHONE_MENU_BUTTON_DOWN_TIME,
            after_sleep=self.MAIL_PHONE_MENU_CLICK_SLEEP,
        )
        return True

    def find_mail_icon_from_phone_menu(self, panel):
        frame = self.mail_current_frame()
        shape = getattr(frame, "shape", None)
        if shape is None or len(shape) < 2:
            return None

        panel_x = int(getattr(panel, "x", 0))
        panel_y = int(getattr(panel, "y", 0))
        panel_w = int(getattr(panel, "width", 0))
        panel_h = int(getattr(panel, "height", 0))
        if panel_w <= 0 or panel_h <= 0:
            return None

        rx1, ry1, rx2, ry2 = self.MAIL_PHONE_MENU_MAIL_ICON_REGION
        x1 = max(0, panel_x + int(panel_w * rx1))
        y1 = max(0, panel_y + int(panel_h * ry1))
        x2 = min(shape[1], panel_x + int(panel_w * rx2))
        y2 = min(shape[0], panel_y + int(panel_h * ry2))
        if x2 <= x1 or y2 <= y1:
            return None

        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return None

        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        mask = (gray > self.MAIL_PHONE_MENU_MAIL_ICON_THRESHOLD).astype(np.uint8)
        kernel = np.ones((3, 3), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)
        count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
        candidates = []
        for label in range(1, count):
            area = int(stats[label, cv2.CC_STAT_AREA])
            width = int(stats[label, cv2.CC_STAT_WIDTH])
            height = int(stats[label, cv2.CC_STAT_HEIGHT])
            if area < self.MAIL_PHONE_MENU_MAIL_ICON_MIN_AREA or width < 20 or height < 14:
                continue
            x = int(stats[label, cv2.CC_STAT_LEFT])
            y = int(stats[label, cv2.CC_STAT_TOP])
            candidates.append((area, Box(x1 + x, y1 + y, width, height, name="mail_phone_menu_mail_icon")))
        if not candidates:
            return None
        return max(candidates, key=lambda item: item[0])[1]

    @staticmethod
    def is_phone_menu_box(panel):
        return getattr(panel, "name", "") in {"mail_phone_menu", "esc_phone_menu"}

    def open_esc_panel_for_mail(self):
        last_error = None
        try:
            return self.openESCpanel()
        except CannotFindException as e:
            last_error = e
            self.log_info("首次打开 ESC 面板失败，重试一次")
            self.sleep(0.8)

        try:
            return self.openESCpanel()
        except CannotFindException as e:
            last_error = e

        result = self.wait_mail_phone_menu()
        if result:
            return result

        foreground_key = getattr(self, "_send_foreground_key", None)
        if callable(foreground_key) and foreground_key(
            "esc",
            down_time=self.MAIL_ESC_SHORTCUT_CLICK_DOWN_TIME * 3,
            after_sleep=self.MAIL_ESC_SHORTCUT_CLICK_SLEEP,
        ):
            result = self._wait_esc_panel()
            if result:
                return result
            result = self.wait_mail_phone_menu()
            if result:
                return result

        if self.click_visible_esc_shortcut():
            result = self._wait_esc_panel()
            if result:
                return result
            result = self.wait_mail_phone_menu()
            if result:
                return result

        raise last_error

    def click_visible_esc_shortcut(self):
        target = self.find_visible_esc_shortcut()
        if target is not None:
            target_x = self.box_center_x(target)
            height = self.screen_height_from_box(target)
            target_y = max(0, self.box_center_y(target) - height * self.MAIL_ESC_SHORTCUT_ICON_OFFSET_RATIO)
            self.log_info("识别到右上 ESC 文本，点击图标区域打开菜单")
            self.click(
                int(target_x),
                int(target_y),
                move=True,
                down_time=self.MAIL_ESC_SHORTCUT_CLICK_DOWN_TIME,
                after_sleep=self.MAIL_ESC_SHORTCUT_CLICK_SLEEP,
            )
            return True

        icon = self.find_visible_esc_icon()
        if icon is None:
            self.log_info("未识别到右上 ESC 入口，跳过点击")
            return False

        self.log_info("识别到右上 ESC 图标，点击图标中心打开菜单")
        self.click(
            int(self.box_center_x(icon)),
            int(self.box_center_y(icon)),
            move=True,
            down_time=self.MAIL_ESC_SHORTCUT_CLICK_DOWN_TIME,
            after_sleep=self.MAIL_ESC_SHORTCUT_CLICK_SLEEP,
        )
        return True

    def find_visible_esc_shortcut(self):
        for box in self.mail_ocr_region(self.MAIL_ESC_SHORTCUT_REGION):
            if "ESC" in self.mail_box_text(box).upper().replace(" ", ""):
                return box
        return None

    def find_visible_esc_icon(self):
        frame = self.mail_current_frame()
        shape = getattr(frame, "shape", None)
        if shape is None or len(shape) < 2:
            return None

        region = self.box_of_ui(*self.MAIL_ESC_ICON_REGION, frame=frame)
        x1 = max(0, int(getattr(region, "x", 0)))
        y1 = max(0, int(getattr(region, "y", 0)))
        x2 = min(shape[1], x1 + int(getattr(region, "width", 0)))
        y2 = min(shape[0], y1 + int(getattr(region, "height", 0)))
        if x2 <= x1 or y2 <= y1:
            return None

        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return None

        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        mask = (gray > 185).astype(np.uint8)
        count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
        candidates = []
        for label in range(1, count):
            area = int(stats[label, cv2.CC_STAT_AREA])
            width = int(stats[label, cv2.CC_STAT_WIDTH])
            height = int(stats[label, cv2.CC_STAT_HEIGHT])
            if area < 80 or width < 8 or height < 8:
                continue
            x = int(stats[label, cv2.CC_STAT_LEFT])
            y = int(stats[label, cv2.CC_STAT_TOP])
            candidates.append((area, x + width, Box(x1 + x, y1 + y, width, height, name="mail_esc_icon")))
        if not candidates:
            return None
        return sorted(candidates, reverse=True)[0][-1]

    def wait_mail_phone_menu(self):
        return self.wait_until(
            self.find_mail_phone_menu_structure,
            time_out=4.5,
            settle_time=0,
            raise_if_not_found=False,
        )

    def find_mail_phone_menu_structure(self):
        frame = self.mail_current_frame()
        shape = getattr(frame, "shape", None)
        if shape is None or len(shape) < 2:
            return None

        height, width = shape[:2]
        panel_x1, panel_y1 = int(width * 0.70), int(height * 0.10)
        panel_x2, panel_y2 = int(width * 0.98), int(height * 0.92)
        bar_x1, bar_y1 = int(width * 0.70), int(height * 0.78)
        bar_x2, bar_y2 = int(width * 0.98), int(height * 0.92)
        panel = frame[panel_y1:panel_y2, panel_x1:panel_x2]
        bottom_bar = frame[bar_y1:bar_y2, bar_x1:bar_x2]
        if panel.size == 0 or bottom_bar.size == 0:
            return None

        panel_dark = self._dark_pixel_ratio(panel, threshold=105)
        bar_dark = self._dark_pixel_ratio(bottom_bar, threshold=120)
        if panel_dark < 0.22 or bar_dark < 0.18:
            return None
        return Box(
            panel_x1,
            panel_y1,
            panel_x2 - panel_x1,
            panel_y2 - panel_y1,
            name="mail_phone_menu",
            confidence=min(1.0, (panel_dark + bar_dark) / 2),
        )

    def mail_ocr_region(self, region):
        frame = self.mail_current_frame()
        try:
            result = self.ocr_ui(*region, frame=frame)
        except Exception:
            return []
        if result is None or isinstance(result, (str, bytes)):
            return []
        try:
            return list(result)
        except TypeError:
            return []

    def mail_current_frame(self):
        next_frame = getattr(self, "next_frame", None)
        if callable(next_frame):
            try:
                return next_frame()
            except Exception:
                pass
        try:
            return self.frame
        except Exception:
            return None

    @staticmethod
    def mail_box_text(box):
        text = getattr(box, "text", None)
        return str(text if text else getattr(box, "name", "")).strip()

    @staticmethod
    def box_center_x(box):
        return getattr(box, "x", 0) + getattr(box, "width", 0) / 2

    @staticmethod
    def box_center_y(box):
        return getattr(box, "y", 0) + getattr(box, "height", 0) / 2

    def screen_height_from_box(self, box):
        height = getattr(self, "height", 0) or 0
        if height:
            return height
        frame = getattr(self, "frame", None)
        shape = getattr(frame, "shape", None)
        if shape is not None and len(shape) >= 2 and shape[0] > 0:
            return shape[0]
        return max(1, self.box_center_y(box))
