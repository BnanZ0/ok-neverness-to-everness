import ctypes
import threading
import time

import win32api
import win32con
from ok import og
from ok.device.intercation import INPUT, MOUSEINPUT, PostMessageInteraction, SendInput
from ok.util.logger import Logger
from win32api import GetCursorPos, SetCursorPos

from src.interaction.keyboard_layout import QwertyPhysicalKeyMapper

logger = Logger.get_logger(__name__)


class NTEInteraction(PostMessageInteraction):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cursor_position = None
        self._operating = False
        self._input_lock = threading.RLock()
        self.user32 = ctypes.windll.user32
        self.qwerty_physical_key_mapper = QwertyPhysicalKeyMapper()
        self._disable_key_mapping = 0

    def send_key(self, *args, **kwargs):
        with self._input_lock:
            mapped_args, mapped_kwargs = self._map_key_args(args, kwargs)
            self._disable_key_mapping += 1
            try:
                return super().send_key(*mapped_args, **mapped_kwargs)
            finally:
                self._disable_key_mapping -= 1

    def send_key_down(self, *args, **kwargs):
        with self._input_lock:
            mapped_args, mapped_kwargs = self._map_key_args(args, kwargs)
            return super().send_key_down(*mapped_args, **mapped_kwargs)

    def send_key_up(self, *args, **kwargs):
        with self._input_lock:
            mapped_args, mapped_kwargs = self._map_key_args(args, kwargs)
            return super().send_key_up(*mapped_args, **mapped_kwargs)

    def scroll(self, *args, **kwargs):
        with self._input_lock:
            return super().scroll(*args, **kwargs)

    def _map_key_args(self, args, kwargs):
        if self._disable_key_mapping or not og.global_config.get_config("Game Hotkey Config").get(
            "Use QWERTY Physical Keys", False
        ):
            return args, kwargs

        if args:
            key = args[0]
        else:
            key = kwargs.get("key")

        mapped_key = self.qwerty_physical_key_mapper.map_key(key)
        if mapped_key is None:
            return args, kwargs

        if args:
            return (mapped_key, *args[1:]), kwargs

        mapped_kwargs = kwargs.copy()
        mapped_kwargs["key"] = mapped_key
        return args, mapped_kwargs

    def click(
        self, x=-1, y=-1, move_back=False, name=None, down_time=0.01, move=True, key="left"
    ):
        with self._input_lock:
            self.try_activate()
            if x < 0:
                x, y = round(self.capture.width * 0.5), round(self.capture.height * 0.5)

            should_restore = move and move_back and not self._operating
            if move:
                if should_restore:
                    self.cursor_position = GetCursorPos()
                abs_x, abs_y = self.capture.get_abs_cords(x, y)
                SetCursorPos((abs_x, abs_y))
                time.sleep(0.025)
            click_pos = win32api.MAKELONG(x, y)
            if key == "left":
                btn_down = win32con.WM_LBUTTONDOWN
                btn_mk = win32con.MK_LBUTTON
                btn_up = win32con.WM_LBUTTONUP
            elif key == "middle":
                btn_down = win32con.WM_MBUTTONDOWN
                btn_mk = win32con.MK_MBUTTON
                btn_up = win32con.WM_MBUTTONUP
            else:
                btn_down = win32con.WM_RBUTTONDOWN
                btn_mk = win32con.MK_RBUTTON
                btn_up = win32con.WM_RBUTTONUP
            self.post(btn_down, btn_mk, click_pos)
            time.sleep(down_time)
            self.post(btn_up, 0, click_pos)
            if should_restore:
                self._restore_cursor()

    def operate(self, fun, block=False, restore_cursor=True):
        with self._input_lock:
            result = None

            is_outer_operate = False
            if not self._operating:
                self.cursor_position = GetCursorPos()
                self._operating = True
                is_outer_operate = True

            if block:
                self.block_input()
            try:
                result = fun()
            except Exception as e:
                logger.error("operate exception", e)
            finally:
                if is_outer_operate:
                    self._operating = False
                    if restore_cursor:
                        self._restore_cursor()
                if block:
                    self.unblock_input()
            return result

    def _restore_cursor(self):
        time.sleep(0.025)
        try:
            SetCursorPos(self.cursor_position)
        except Exception as e:
            logger.error("restore cursor exception", e)

    def block_input(self):
        self.user32.BlockInput(True)

    def unblock_input(self):
        self.user32.BlockInput(False)

    def move_mouse_relative(self, dx, dy):
        """
        Moves the mouse cursor relative to its current position using user32.SendInput.

        Args:
            dx: The number of pixels to move the mouse horizontally.
                (positive for right, negative for left).
            dy: The number of pixels to move the mouse vertically.
                (positive for down, negative for up).
        """

        mi = MOUSEINPUT(dx, dy, 0, 1, 0, None)
        i = INPUT(0, mi)  # type=0 indicates a mouse event
        SendInput(1, ctypes.pointer(i), ctypes.sizeof(INPUT))
