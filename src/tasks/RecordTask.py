import threading
import time
from collections.abc import Callable, Iterable
from typing import Any

import win32gui
from ok import Logger, og
from ok.util.config import Config
from pynput import mouse
from PySide6.QtCore import Qt
from qfluentwidgets import InfoBar, InfoBarPosition

from src.tasks.BaseNTETask import BaseNTETask
from src.ui.util import show_dialog_and_wait

logger = Logger.get_logger(__name__)

RECORD_CLICK_OVERLAY_KEY = "nte_record_click_overlay"
DEFAULT_RECORD_INSTRUCTION = "Record operations"
RECORD_CONFIG_FOLDER = "configs/records"
RECORD_OPERATIONS_KEY = "operations"
SCROLL_MERGE_INTERVAL = 0.35
NOTIFICATION = (
    "No recorded operations were found. Please wait for the recording prompt, "
    "then follow the instructions carefully to record your actions."
)


class RecordTask(BaseNTETask):
    """Base task for recording and replaying user mouse operations."""

    CONF_RESET_RECORD = "重置记录"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.record_config = Config(
            self.__class__.__name__,
            {RECORD_OPERATIONS_KEY: []},
            folder=RECORD_CONFIG_FOLDER,
        )
        self.default_config.update(
            {
                self.CONF_RESET_RECORD: self.CONF_RESET_RECORD,
            }
        )
        self.config_type.update(
            {
                self.CONF_RESET_RECORD: {"type": "button", "callback": self.reset_record},
            }
        )
        self.config_description.update(
            {
                self.CONF_RESET_RECORD: "清空已记录的操作",
            }
        )
        self.tr(NOTIFICATION)

    def run(self):
        operations = self.load_recorded_operations()
        if not operations:
            self.show_notification()

    def show_notification(self):
        show_dialog_and_wait(self.tr(self.name), self.tr(NOTIFICATION), close_delay_seconds=2)

    def reset_record(self, *args, **kwargs):
        self.record_config[RECORD_OPERATIONS_KEY] = []
        self.log_info("record reset")
        self._show_record_reset_info()

    def _show_record_reset_info(self):
        parent = self._record_info_bar_parent()
        if parent is None:
            return
        InfoBar.success(
            title=self.tr("Updated successfully"),
            content=self.tr("Record has been reset"),
            orient=Qt.Orientation.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=1500,
            parent=parent,
        )

    def _record_info_bar_parent(self):
        app = getattr(og, "app", None)
        main_window = getattr(app, "main_window", None)
        if main_window is not None:
            return main_window.window()
        return None

    def load_recorded_operations(self) -> list[dict[str, Any]]:
        operations = self.record_config.get(RECORD_OPERATIONS_KEY, [])
        if not isinstance(operations, list):
            return []
        return [operation for operation in operations if isinstance(operation, dict)]

    def save_recorded_operations(self, operations: list[dict[str, Any]]) -> None:
        self.record_config[RECORD_OPERATIONS_KEY] = operations

    def has_recorded_operations(self) -> bool:
        return bool(self.load_recorded_operations())

    def record_or_replay_operations(
        self,
        count: int,
        instruction_text: str | Callable[[int, int], str] | None = None,
        **kwargs,
    ) -> list[dict[str, Any]]:
        operations = self.load_recorded_operations()
        if operations:
            self.replay_recorded_operations(operations)
            return operations
        self.bring_to_front()
        return self.record_operations(count, instruction_text, **kwargs)

    def record_operations(
        self,
        count: int,
        instruction_text: str | Callable[[int, int], str] | None = None,
        *,
        buttons: Iterable[str] = ("left",),
        timeout: float | None = None,
        target_window_only: bool = True,
        include_scroll: bool = True,
        overlay_key: str = RECORD_CLICK_OVERLAY_KEY,
    ) -> list[dict[str, Any]]:
        """
        Record mouse clicks and scrolls, then save them for this task class.

        Continuous scroll events are merged into one operation.
        """
        operations = self._record_mouse_operations(
            count,
            instruction_text,
            buttons=buttons,
            timeout=timeout,
            target_window_only=target_window_only,
            include_scroll=include_scroll,
            overlay_key=overlay_key,
        )
        self.save_recorded_operations(operations)
        return operations

    def replay_recorded_operations(
        self,
        operations: list[dict[str, Any]] | None = None,
        *,
        respect_delays: bool = True,
    ) -> None:
        operations = operations if operations is not None else self.load_recorded_operations()
        previous_operation = None
        for operation in operations:
            if not isinstance(operation, dict):
                continue
            if respect_delays:
                delay = self._operation_delay(operation, previous_operation)
                self.sleep(delay)

            op_type = operation.get("type")
            if op_type == "click":
                self.operation_click(
                    operation["x"],
                    operation["y"],
                    key=operation.get("button", "left"),
                    down_time=operation.get("down_time", 0.02),
                    restore_cursor=False,
                )
            elif op_type == "scroll":
                count = int(operation.get("count", 0))
                if count == 0:
                    continue
                self.scroll(
                    int(operation["x"] * self.width),
                    int(operation["y"] * self.height),
                    count,
                )
            previous_operation = operation

    def operation_click(self, *args, **kwargs):
        return self.operate_click(*args, **kwargs)

    def _operation_delay(
        self,
        operation: dict[str, Any],
        previous_operation: dict[str, Any] | None = None,
    ) -> float:
        if previous_operation is None:
            return 0.0
        try:
            previous_end = previous_operation.get("end_time", previous_operation.get("time"))
            return max(0.0, float(operation["time"]) - float(previous_end))
        except (TypeError, ValueError, KeyError):
            return max(0.0, float(operation.get("delay", 0)))

    def _record_mouse_operations(
        self,
        count: int,
        instruction_text: str | Callable[[int, int], str] | None = None,
        *,
        buttons: Iterable[str] = ("left",),
        timeout: float | None = None,
        target_window_only: bool = True,
        include_scroll: bool = True,
        overlay_key: str = RECORD_CLICK_OVERLAY_KEY,
    ) -> list[dict[str, Any]]:
        if count <= 0:
            return []

        allowed_buttons = {button.lower() for button in buttons}
        if not allowed_buttons:
            allowed_buttons = {"left"}

        operations: list[dict[str, Any]] = []
        records_lock = threading.Lock()
        finished = threading.Event()
        down_times: dict[str, float] = {}
        started_at = time.time()
        last_operation_end_time: float | None = None
        target_hwnd = self._record_target_hwnd()
        pending_scroll: dict[str, Any] = {}

        overlay_view = self.get_overlay_view()
        self._draw_record_click_overlay(
            overlay_view,
            operations,
            records_lock,
            count,
            instruction_text,
            overlay_key,
        )

        def append_operation(
            operation: dict[str, Any],
            event_time: float,
            end_time: float | None = None,
        ):
            nonlocal last_operation_end_time
            if len(operations) >= count:
                return
            end_time = event_time if end_time is None else end_time
            delay = 0.0
            if last_operation_end_time is not None:
                delay = max(0.0, event_time - last_operation_end_time)
            operation["index"] = len(operations) + 1
            operation["delay"] = round(delay, 4)
            operations.append(operation)
            last_operation_end_time = end_time
            self.log_info(f"record operation {operation['index']}/{count}: {operation}")
            if len(operations) >= count:
                finished.set()

        def flush_pending_scroll(force=False):
            if not pending_scroll:
                return
            now = time.time()
            if not force and now - pending_scroll["last_time"] < SCROLL_MERGE_INTERVAL:
                return
            operation = dict(pending_scroll["operation"])
            pending_scroll.clear()
            if int(operation.get("count", 0)) == 0:
                return
            append_operation(operation, operation["time"], operation.get("end_time", now))

        def on_click(screen_x, screen_y, button, pressed):
            button_name = self._record_button_name(button)
            if button_name not in allowed_buttons:
                return

            now = time.time()
            if pressed:
                down_times[button_name] = now
                return

            down_start_time = down_times.pop(button_name, now)
            down_time = now - down_start_time
            try:
                click = self._build_operation_record(
                    "click",
                    screen_x,
                    screen_y,
                    button_name,
                    down_time,
                    target_hwnd,
                    target_window_only,
                    event_time=down_start_time,
                )
            except Exception as e:
                logger.warning(f"record click failed: {e}")
                return
            if click is None:
                return
            click["end_time"] = now
            click["duration"] = click["down_time"]

            with records_lock:
                flush_pending_scroll(force=True)
                append_operation(click, down_start_time, now)

        def on_scroll(screen_x, screen_y, _dx, dy):
            if not include_scroll:
                return
            count_delta = int(dy)
            if count_delta == 0:
                return
            now = time.time()
            try:
                scroll = self._build_operation_record(
                    "scroll",
                    screen_x,
                    screen_y,
                    "scroll",
                    0,
                    target_hwnd,
                    target_window_only,
                    event_time=now,
                )
            except Exception as e:
                logger.warning(f"record scroll failed: {e}")
                return
            if scroll is None:
                return

            with records_lock:
                if len(operations) >= count:
                    return
                if pending_scroll:
                    operation = pending_scroll["operation"]
                    operation["count"] += count_delta
                    operation["x"] = scroll["x"]
                    operation["y"] = scroll["y"]
                    operation["end_time"] = now
                    operation["duration"] = round(now - operation["time"], 4)
                    pending_scroll["last_time"] = now
                    return
                scroll["count"] = count_delta
                scroll["end_time"] = now
                scroll["duration"] = 0.0
                pending_scroll["operation"] = scroll
                pending_scroll["last_time"] = now

        listener = mouse.Listener(on_click=on_click, on_scroll=on_scroll)
        listener.start()

        try:
            self.log_info(f"recording {count} operation(s)")
            while not finished.is_set():
                if timeout is not None and time.time() - started_at >= timeout:
                    raise TimeoutError(
                        f"record operations timed out after {timeout}s "
                        f"({len(operations)}/{count} operation(s) recorded)"
                    )
                with records_lock:
                    flush_pending_scroll()
                if self._record_exit_requested():
                    break
                time.sleep(0.05)
        finally:
            with records_lock:
                flush_pending_scroll(force=True)
            listener.stop()
            self._clear_record_click_overlay(overlay_view, overlay_key)

        with records_lock:
            return [dict(operation) for operation in operations]

    def _record_target_hwnd(self):
        device_manager = getattr(og, "device_manager", None)
        hwnd_window = getattr(device_manager, "hwnd_window", None)
        return getattr(hwnd_window, "hwnd", None) if hwnd_window else None

    def _record_button_name(self, button) -> str:
        if button == mouse.Button.right:
            return "right"
        if button == mouse.Button.middle:
            return "middle"
        return "left"

    def _build_operation_record(
        self,
        op_type: str,
        screen_x: int,
        screen_y: int,
        button: str,
        down_time: float,
        target_hwnd,
        target_window_only: bool,
        event_time: float | None = None,
    ) -> dict[str, Any] | None:
        pixel_x, pixel_y, width, height = self._screen_to_record_window_coords(
            screen_x,
            screen_y,
            target_hwnd,
        )
        if width <= 0 or height <= 0:
            return None

        inside = 0 <= pixel_x <= width and 0 <= pixel_y <= height
        if target_window_only and not inside:
            return None

        normalized_x = self._normalize_record_coord(pixel_x, width)
        normalized_y = self._normalize_record_coord(pixel_y, height)
        record = {
            "type": op_type,
            "button": button,
            "x": normalized_x,
            "y": normalized_y,
            "pixel_x": int(round(pixel_x)),
            "pixel_y": int(round(pixel_y)),
            "screen_x": int(round(screen_x)),
            "screen_y": int(round(screen_y)),
            "width": int(round(width)),
            "height": int(round(height)),
            "down_time": round(max(0.0, down_time), 4),
            "time": time.time() if event_time is None else event_time,
        }
        if op_type == "scroll":
            record.pop("down_time", None)
            record.pop("button", None)
            record["count"] = 0
        return record

    def _screen_to_record_window_coords(self, screen_x: int, screen_y: int, target_hwnd):
        device_manager = getattr(og, "device_manager", None)
        hwnd_window = getattr(device_manager, "hwnd_window", None)
        if hwnd_window is not None and getattr(hwnd_window, "hwnd", None) == target_hwnd:
            left = hwnd_window.x + getattr(hwnd_window, "real_x_offset", 0)
            top = hwnd_window.y + getattr(hwnd_window, "real_y_offset", 0)
            width = getattr(hwnd_window, "real_width", 0) or getattr(hwnd_window, "width", 0)
            height = getattr(hwnd_window, "real_height", 0) or getattr(hwnd_window, "height", 0)
            return screen_x - left, screen_y - top, width, height

        if target_hwnd:
            client_left, client_top = win32gui.ClientToScreen(target_hwnd, (0, 0))
            _left, _top, right, bottom = win32gui.GetClientRect(target_hwnd)
            return screen_x - client_left, screen_y - client_top, right - _left, bottom - _top

        width = getattr(device_manager, "width", 0)
        height = getattr(device_manager, "height", 0)
        return screen_x, screen_y, width, height

    def _normalize_record_coord(self, value: float, size: float) -> float:
        if size <= 0:
            return 0.0
        return round(max(0.0, min(1.0, value / size)), 4)

    def _draw_record_click_overlay(
        self,
        overlay_view,
        records: list[dict[str, Any]],
        records_lock: threading.Lock,
        count: int,
        instruction_text: str | Callable[[int, int], str] | None,
        overlay_key: str,
    ) -> None:
        if overlay_view is None:
            return

        def paint_callback(painter, widget):
            import win32api
            from PySide6.QtCore import QPoint, QRect, QRectF, Qt
            from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPen

            scaling = getattr(widget, "scaling", None)
            if not scaling:
                screen = QGuiApplication.primaryScreen()
                scaling = screen.devicePixelRatio() if screen else 1

            screen_x, screen_y = win32api.GetCursorPos()
            mouse_pos = widget.mapFromGlobal(
                QPoint(int(screen_x / scaling), int(screen_y / scaling))
            )
            mx = mouse_pos.x()
            my = mouse_pos.y()

            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            pen = QPen(QColor(0, 255, 180, 220))
            pen.setWidth(1)
            pen.setStyle(Qt.DashLine)
            painter.setPen(pen)
            painter.drawLine(0, my, widget.width(), my)
            painter.drawLine(mx, 0, mx, widget.height())

            with records_lock:
                snapshot = [dict(record) for record in records]

            pen.setStyle(Qt.SolidLine)
            pen.setWidth(2)
            pen.setColor(QColor(255, 80, 80, 230))
            painter.setPen(pen)
            for record in snapshot:
                px = int(record["x"] * widget.width())
                py = int(record["y"] * widget.height())
                painter.drawLine(px - 6, py, px + 6, py)
                painter.drawLine(px, py - 6, px, py + 6)
                painter.drawText(px + 8, py - 8, str(record["index"]))

            text = self._record_instruction_text(instruction_text, len(snapshot), count)
            if text:
                font = QFont()
                font.setPointSize(10)
                painter.setFont(font)
                metrics = painter.fontMetrics()
                padding = 6
                offset_x = max(1, round(widget.width() * 14 / 1280))
                offset_y = max(1, round(widget.height() * 14 / 720))
                text_rect = metrics.boundingRect(QRect(0, 0, 360, 1000), Qt.TextWordWrap, text)
                box_width = min(max(text_rect.width() + padding * 2, 120), widget.width())
                box_height = text_rect.height() + padding * 2
                box_x = min(max(0, mx + offset_x), max(0, widget.width() - box_width))
                box_y = min(max(0, my + offset_y), max(0, widget.height() - box_height))

                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(0, 0, 0, 170))
                painter.drawRoundedRect(QRectF(box_x, box_y, box_width, box_height), 4, 4)
                painter.setPen(QPen(QColor(255, 255, 255, 235), 1))
                painter.drawText(
                    QRectF(
                        box_x + padding,
                        box_y + padding,
                        box_width - padding * 2,
                        box_height - padding * 2,
                    ),
                    Qt.TextWordWrap,
                    text,
                )

        overlay_view.draw(overlay_key, paint_callback, duration=None)

    def _record_instruction_text(
        self,
        instruction_text: str | Callable[[int, int], str] | None,
        recorded_count: int,
        total_count: int,
    ) -> str:
        progress = f"{recorded_count}/{total_count}"
        if callable(instruction_text):
            text = instruction_text(recorded_count, total_count)
        else:
            text = instruction_text or DEFAULT_RECORD_INSTRUCTION
        return f"{text}\n{progress}"

    def _clear_record_click_overlay(self, overlay_view, overlay_key: str) -> None:
        if overlay_view is None:
            return
        clear_draw = getattr(overlay_view, "clear_draw", None)
        if callable(clear_draw):
            clear_draw(overlay_key)

    def _record_exit_requested(self) -> bool:
        try:
            return bool(self.exit_is_set())
        except Exception:
            return False
