import time

import win32api
import win32con
from ok import Logger, TriggerTask

from src.tasks.BaseNTETask import BaseNTETask

logger = Logger.get_logger(__name__)


class HeistTask(BaseNTETask, TriggerTask):
    CONF_PICK_KEY = "触发按键"
    CONF_USE_SCROLL = "使用滚轮加速拾取"
    CONF_QUICK_RUN = "切换角色快速奔跑"
    CONF_QUICK_RUN_CHAR_COUNT = "快速奔跑角色数量"
    SEND_KEY_INTERVAL = 0.2
    CHECK_INTERVAL = 0.01
    PICK_KEY_HOLD_INTERVAL = 0.35
    QUICK_RUN_HOLD_INTERVAL = 0.5
    QUICK_RUN_KEY_AFTER_SLEEP = 0.25
    QUICK_RUN_SHIFT_INTERVAL = 0.3
    QUICK_RUN_SHIFT_AFTER_SLEEP = 0.4
    KEY_MAP = {
        "space": win32con.VK_SPACE,
        "shift": win32con.VK_SHIFT,
        "ctrl": win32con.VK_CONTROL,
        "control": win32con.VK_CONTROL,
        "alt": win32con.VK_MENU,
        "esc": win32con.VK_ESCAPE,
        "escape": win32con.VK_ESCAPE,
        "tab": win32con.VK_TAB,
        "enter": win32con.VK_RETURN,
        "return": win32con.VK_RETURN,
        "backspace": win32con.VK_BACK,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.default_config = {"_enabled": False}
        self._submitted = False
        self._scroll_time = 0
        self._scroll_switch = False
        self._scroll_count = 0
        self._pick_key_pressed = False
        self._pick_key_down_time = 0
        self._shift_pressed = False
        self._shift_down_time = 0
        self._quick_running = False
        self._quick_run_index = 0
        self._quick_run_time = 0
        self._quick_run_step = 0
        self.name = "粉爪大劫案"
        self.description = "粉爪大劫案便利性功能"
        self.default_config.update(
            {
                self.CONF_PICK_KEY: "f",
                self.CONF_USE_SCROLL: True,
                self.CONF_QUICK_RUN: True,
                self.CONF_QUICK_RUN_CHAR_COUNT: 4,
            }
        )
        self.config_description.update(
            {
                self.CONF_PICK_KEY: "触发连点的按键 (按住生效)",
                self.CONF_USE_SCROLL: "触发连点将同步生效",
                self.CONF_QUICK_RUN: "按住Shift生效",
                self.CONF_QUICK_RUN_CHAR_COUNT: "切换角色数量",
            }
        )
        self._loop = True

    def run(self):
        if not self.scene.is_in_team(self.is_in_team):
            self._loop = False
            return
        self._loop = True
        if self._submitted:
            return
        self._submitted = True
        self.submit_periodic_task(self.CHECK_INTERVAL, self._spam_key_loop)

    def alternate_scroll(self, interval=0):
        if not self.config.get(self.CONF_USE_SCROLL):
            return
        if time.time() - self._scroll_time >= interval:
            time.sleep(0.01)
            if self._scroll_switch:
                self.scroll(0, 0, 1)
            else:
                self.scroll(0, 0, -1)
            self._scroll_time = time.time()
            self._scroll_count += 1
            if self._scroll_count >= 3:
                self._scroll_count = 0
                self._scroll_switch = not self._scroll_switch

    def _is_onetime_task_running(self):
        if self.executor.current_task in self.executor.onetime_tasks:
            return self.executor.current_task.running

    def _spam_key_loop(self):
        if not self.enabled or self._is_onetime_task_running():
            self._submitted = False
            return False

        if not self._loop or not self.is_foreground():
            self._reset_pick_key()
            self._reset_quick_run()
            return True

        self._handle_quick_run()
        self._handle_pick_key()
        return True

    def _handle_pick_key(self):
        key = self._get_pick_key()
        key_pressed = self._is_key_pressed(key)
        now = time.time()
        if not key_pressed:
            self._reset_pick_key()
            return

        if not self._pick_key_pressed:
            if self._pick_key_down_time == 0:
                self._pick_key_down_time = now
                return
            if now - self._pick_key_down_time < self.PICK_KEY_HOLD_INTERVAL:
                return
            self._scroll_switch = False
            self._scroll_count = 0
            self._pick_key_pressed = True

        self.send_key(key, interval=self.SEND_KEY_INTERVAL)
        time.sleep(0.001)
        self.alternate_scroll(interval=self.SEND_KEY_INTERVAL)

    def _reset_pick_key(self):
        self._pick_key_pressed = False
        self._pick_key_down_time = 0

    def _get_pick_key(self):
        return self.config.get(self.CONF_PICK_KEY)

    def _handle_quick_run(self):
        if not self.config.get(self.CONF_QUICK_RUN):
            self._reset_quick_run()
            return

        shift_pressed = self._is_key_pressed("shift")
        now = time.time()
        if shift_pressed and not self._shift_pressed:
            self._shift_down_time = now
        elif not shift_pressed:
            self._reset_quick_run()
            return

        self._shift_pressed = shift_pressed

        if not self._quick_running:
            if now - self._shift_down_time >= self.QUICK_RUN_HOLD_INTERVAL:
                self._quick_running = True
                self._quick_run_index = 0
                self._quick_run_time = 0
                self._quick_run_step = 0
                self.send_key_up("lshift")
            else:
                return

        try:
            char_count = int(self.config.get(self.CONF_QUICK_RUN_CHAR_COUNT))
        except (TypeError, ValueError):
            char_count = 4
        char_count = max(1, min(4, char_count))
        if now < self._quick_run_time:
            return

        if not self.is_foreground() or not self._is_key_pressed("shift"):
            self._reset_quick_run()
            return
        if self._quick_run_step == 0:
            key = str(self._quick_run_index % char_count + 1)
            self._quick_run_index += 1
            max_time = time.time() + 3
            deadline = time.time() + self.QUICK_RUN_KEY_AFTER_SLEEP
            while deadline > time.time() and time.time() < max_time:
                self.send_key(key, action_name="heist_task_run", interval=0.5)
                frame = self.frame
                if frame is not None:
                    deadline += 0.1
                    if self.is_char_at_index(int(key) - 1, frame=frame):
                        break
                time.sleep(0.05)
            self._quick_run_step = 1
            self._quick_run_time = time.time()
        elif self._quick_run_step == 1:
            self.send_key("lshift")
            self._quick_run_step = 2
            self._quick_run_time = time.time() + self.QUICK_RUN_SHIFT_INTERVAL
        else:
            self.send_key("lshift")
            self._quick_run_step = 0
            self._quick_run_time = time.time() + self.QUICK_RUN_SHIFT_AFTER_SLEEP

    def _reset_quick_run(self):
        self._shift_pressed = False
        self._shift_down_time = 0
        self._quick_running = False
        self._quick_run_index = 0
        self._quick_run_time = 0
        self._quick_run_step = 0

    def _is_key_pressed(self, key):
        vk_code = self._get_vk_code(key)
        return vk_code is not None and bool(win32api.GetAsyncKeyState(vk_code) & 0x8000)

    def _get_vk_code(self, key):
        if key is None:
            return None

        key = str(key).strip().lower()
        if not key:
            return None

        if key in self.KEY_MAP:
            return self.KEY_MAP[key]
        if key.startswith("f") and key[1:].isdigit():
            index = int(key[1:])
            if 1 <= index <= 12:
                return win32con.VK_F1 + index - 1
        if len(key) == 1:
            vk_code = win32api.VkKeyScan(key)
            if vk_code == -1:
                return None
            return vk_code & 0xFF

        return None
