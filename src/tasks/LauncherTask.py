import os
import re
import time
from enum import Enum

import psutil
import win32con
import win32gui
import win32process
from ok import TaskDisabledException, og
from ok.gui.Communicate import communicate
from ok.util.process import execute, is_admin
from qfluentwidgets import FluentIcon

from src.interaction.NTEInteraction import NTEInteraction
from src.Labels import Labels
from src.tasks.BaseNTETask import BaseNTETask

GAME_EXE = "HTGame.exe"
LAUNCHER_EXE = "NTEGame.exe"
GAME_CAPTURE_CONFIG = {
    "windows": {
        "exe": GAME_EXE,
        "hwnd_class": "UnrealWindow",
        "interaction": NTEInteraction,
        "capture_method": [
            "WGC",
            "BitBlt_RenderFull",
        ],
    },
}


class LauncherButtonState(Enum):
    START = "start"
    READY_OTHER = "ready_other"
    NOT_READY = "not_ready"


LAUNCHER_CAPTURE_CONFIG = {
    "windows": {
        "exe": LAUNCHER_EXE,
        "hwnd_class": "Qt51517QWindowOwnDC",
        "top_hwnd_class": ["Qt51517QWindowToolSaveBitsOwnDC"],
        "interaction": "PostMessage",
        "capture_method": [
            "WGC",
            "BitBlt_RenderFull",
        ],
    },
}


class LauncherTask(BaseNTETask):
    CONF_PATH = "Launcher Path"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "Start Game"
        self.icon = FluentIcon.SYNC
        self.default_config.update({self.CONF_PATH: ""})
        self.enable_after_start = True  # auto run after start
        self.visible = False  # False to hide from the UI

    def run(self):
        self.log_info("Launcher task started")
        if not self._check_admin():
            return

        game_proc = self._find_process(GAME_EXE)
        self.log_info(f"Game process check: {self._format_process(game_proc)}")
        if game_proc:
            self.log_info("Game is already running; preparing game capture")
            self._update_launcher_path_from_game(game_proc.get("exe"))
            self._wait_for_game_and_capture(time_out=120, settle_window=False)
            return

        launcher_proc = self._find_process(LAUNCHER_EXE)
        self.log_info(f"Launcher process check: {self._format_process(launcher_proc)}")
        if launcher_proc:
            self.log_info("Launcher is already running; preparing launcher capture")
            self._update_launcher_path(launcher_proc.get("exe"))
            if not self._wait_for_process(LAUNCHER_EXE):
                raise TaskDisabledException("Timed out waiting for launcher window")
            self._capture_launcher()
            if not self._click_start_game():
                raise TaskDisabledException("Timed out waiting for launcher to minimize")
            self._wait_for_game_and_capture()
            return

        launcher_path = self._get_launcher_path()
        if not launcher_path:
            self.log_error("Launcher path was not found in config or registry")
            raise TaskDisabledException(
                "Launcher path not found. Please set Launcher Path to NTEGame.exe"
            )

        self.log_info(f"Starting launcher from configured path: {launcher_path}")
        if not execute(launcher_path):
            self.log_error(f"Failed to start launcher from path: {launcher_path}")
            raise TaskDisabledException(f"Invalid launcher path: {launcher_path}")

        self.log_info("Game did not appear directly; waiting for launcher process")
        if not self._wait_for_process(LAUNCHER_EXE, settle_window=True):
            self.log_error("Timed out waiting for launcher process")
            raise TaskDisabledException("Timed out waiting for launcher process")

        launcher_proc = self._find_process(LAUNCHER_EXE)
        self.log_info(f"Launcher process after start: {self._format_process(launcher_proc)}")
        if launcher_proc:
            self._update_launcher_path(launcher_proc.get("exe"))
        self._capture_launcher()
        if not self._click_start_game():
            raise TaskDisabledException("Timed out waiting for launcher to minimize")
        self._wait_for_game_and_capture()

    def _capture_game(self):
        self.log_info(f"Switching capture to game window: {GAME_CAPTURE_CONFIG}")
        self.executor.device_manager.ensure_capture(GAME_CAPTURE_CONFIG)
        self.log_info("Game capture is ready; activating game window")

    def _capture_launcher(self):
        self.log_info(f"Switching capture to launcher window: {LAUNCHER_CAPTURE_CONFIG}")
        self._log_task_state("before launcher ensure_capture")
        self.executor.device_manager.ensure_capture(LAUNCHER_CAPTURE_CONFIG)
        self._log_task_state("after launcher ensure_capture")
        self.log_info("Launcher capture is ready; activating launcher window")

    def _log_task_state(self, point):
        current_task = getattr(self.executor, "current_task", None)
        self.log_info(
            f"Launcher task state at {point}: "
            f"enabled={self._enabled}, "
            f"running={self.running}, "
            f"paused={self.paused}, "
            f"executor_paused={getattr(self.executor, 'paused', None)}, "
            f"is_current_task={current_task is self}, "
            f"current_task={current_task}"
        )

    def _click_start_game(self, time_out=120):
        self.log_info(f"Looking for launcher Start Game button for up to {time_out}s")
        deadline = time.time() + time_out
        last_log_time = 0
        last_update_click_time = 0
        ready_other_count = 0
        update_in_progress = False
        start_click_pending = False
        while time.time() < deadline:
            loop_start = time.time()
            if self._find_process(GAME_EXE):
                self.log_info(
                    "Game process appeared while checking launcher; treating launch as successful"
                )
                return True

            if self._is_launcher_minimized():
                self.log_info("Launcher window is minimized; Start Game click succeeded")
                return True

            try:
                button_state, button = self._launcher_button_state()
            except AttributeError as e:
                self.log_warning(
                    f"Launcher frame was unavailable while checking launcher button {e}"
                )
                if self._is_launcher_minimized():
                    self.log_info("treating as success")
                    return True
                else:
                    self.sleep(1)
                    if update_in_progress:
                        deadline = self._extend_deadline_for_update(deadline, loop_start)
                    continue

            if button_state == LauncherButtonState.START:
                ready_other_count = 0
                update_in_progress = False
                self._click_launcher_start_button(button)
                start_click_pending = True
                if self._is_launcher_minimized():
                    self.log_info("Launcher minimized after Start Game click")
                    return True
                self.log_info(
                    "Launcher is not minimized after click; will check and click again if needed"
                )
                continue

            if start_click_pending and self._is_launcher_minimized():
                self.log_info("Launcher minimized after Start Game click")
                return True

            if button_state == LauncherButtonState.READY_OTHER:
                if update_in_progress:
                    self.log_info(
                        "Launcher button is ready while update is in progress; "
                        "waiting for Start Game button"
                    )
                    self.sleep(1)
                    deadline = self._extend_deadline_for_update(deadline, loop_start)
                    continue

                ready_other_count += 1
                now = time.time()
                if ready_other_count < 2:
                    self.log_info(
                        "Launcher button is ready but Start Game was not detected; "
                        "confirming before clicking possible update button"
                    )
                elif now - last_update_click_time >= 10:
                    self.log_info(
                        "Launcher button is ready but Start Game was not detected; "
                        "clicking it as a possible update button"
                    )
                    self.click(button, after_sleep=2)
                    last_update_click_time = now
                    update_in_progress = True
                else:
                    self.log_info(
                        "Launcher button is ready but Start Game was not detected; "
                        "waiting for update flow to finish"
                    )
                self.sleep(1)
                if update_in_progress:
                    deadline = self._extend_deadline_for_update(deadline, loop_start)
                continue

            ready_other_count = 0
            if update_in_progress:
                self.sleep(1)
                deadline = self._extend_deadline_for_update(deadline, loop_start)
                continue

            now = time.time()
            if now - last_log_time >= 5:
                self.log_info("Launcher Start Game button not found yet")
                last_log_time = now
            self.sleep(1)
        self.log_warning("Launcher did not minimize after Start Game attempts")
        return False

    def _launcher_button_state(self):
        start_button = self._find_launcher_start_button()
        if start_button:
            return LauncherButtonState.START, start_button

        is_ready, button = self._launcher_button_ready()
        if is_ready:
            return LauncherButtonState.READY_OTHER, button

        return LauncherButtonState.NOT_READY, None

    def _extend_deadline_for_update(self, deadline, start_time):
        return deadline + time.time() - start_time

    def _find_launcher_start_button(self):
        return self.find_one(
            Labels.launcher_start_game,
            horizontal_variance=0.1,
            vertical_variance=0.1,
            threshold=0.85,
        )

    def _click_launcher_start_button(self, start_button):
        self.log_info(f"Found launcher Start Game button: {start_button}")
        self.click(start_button, after_sleep=2)
        if not self._is_launcher_minimized():
            self.click(0.5269, 0.6122, after_sleep=2)  # close popup

    def _launcher_button_ready(self):
        box = self.box_of_screen(0.8137, 0.8678, 0.8387, 0.9022, name="launcher_button")
        per = self.calculate_color_percentage(launcher_btn_ready_color, box)
        self.log_info(f"launcher_button color {per}")
        return per > 0.8, box

    def _is_launcher_minimized(self):
        launcher_proc = self._find_process(LAUNCHER_EXE)
        if not launcher_proc:
            return False
        launcher_hwnd = self._find_window_for_process(
            launcher_proc,
            hwnd_class=LAUNCHER_CAPTURE_CONFIG["windows"]["hwnd_class"],
            require_title=True,
        )
        if not launcher_hwnd:
            return False
        return bool(win32gui.IsIconic(launcher_hwnd) or not win32gui.IsWindowVisible(launcher_hwnd))

    def _wait_for_game_and_capture(self, time_out=600, settle_window=True):
        self.log_info(f"Waiting for game process for up to {time_out}s")
        if not self._wait_for_process(GAME_EXE, time_out=time_out, settle_window=settle_window):
            self.log_error("Timed out waiting for game process")
            raise TaskDisabledException("Timed out waiting for game process")
        self.log_info("Game process found; switching capture to game")
        self._capture_game()
        time_out = 10
        deadline = time.time() + time_out
        while time.time() < deadline:
            if not self.executor.connected():
                self.log_info("executor not connected try refresh")
                self.executor.device_manager.refresh()
                time.sleep(1.5)
            else:
                break
        else:
            self.log_warning(
                f"try refresh timeout {time_out}s, executor connect {self.executor.connected()}"
            )
            return

        resolution_error = og.app.start_controller.check_resolution()
        if resolution_error:
            self.log_error(f"resolution_error: {resolution_error}")
            raise TaskDisabledException(f"Resolution Error: {resolution_error}")

    def _wait_for_process(self, exe_name, time_out=120, settle_window=False):
        self.log_info(
            f"Waiting for process and window {exe_name} for up to {time_out}s "
            f"(settle_window={settle_window})"
        )
        start = time.time()
        last_log_second = -1
        while time.time() - start < time_out:
            proc = self._find_process(exe_name)
            if proc:
                hwnd = self._find_window_for_process(proc)
                if hwnd:
                    self._restore_window_if_minimized(hwnd, exe_name)
                    size = self._get_window_size(hwnd)
                    if not self._is_usable_window_size(size):
                        elapsed = int(time.time() - start)
                        if elapsed != last_log_second and elapsed > 0 and elapsed % 10 == 0:
                            self.log_info(
                                f"Window for {exe_name} exists but is too small; "
                                f"hwnd={hwnd}, size={size[0]}x{size[1]}, elapsed={elapsed}s"
                            )
                            last_log_second = elapsed
                        self.sleep(1)
                        continue

                    if settle_window:
                        if not self._wait_for_window_size_to_settle(
                            hwnd, exe_name, start, time_out
                        ):
                            return False
                        size = self._get_window_size(hwnd)

                    self.log_info(
                        f"Found process and window {exe_name}: "
                        f"{self._format_process(proc)}, hwnd={hwnd}, size={size[0]}x{size[1]}"
                    )
                    return True

            elapsed = int(time.time() - start)
            if elapsed != last_log_second and elapsed > 0 and elapsed % 10 == 0:
                if proc:
                    self.log_info(
                        f"Process {exe_name} exists, waiting for window; elapsed={elapsed}s"
                    )
                else:
                    self.log_info(f"Still waiting for {exe_name}; elapsed={elapsed}s")
                last_log_second = elapsed
            self.sleep(1)
        self.log_warning(f"Process/window {exe_name} was not found within {time_out}s")
        return False

    def _find_process(self, exe_name):
        exe_name = exe_name.lower()
        for proc in psutil.process_iter(["pid", "name", "exe"]):
            try:
                name = proc.info.get("name") or ""
                if name.lower() == exe_name:
                    return proc.info
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return None

    def _find_window_for_process(self, proc_info, hwnd_class=None, require_title=False):
        pid = proc_info.get("pid")
        if not pid:
            return 0

        matches = []

        def callback(hwnd, _):
            if not win32gui.IsWindow(hwnd) or not win32gui.IsWindowEnabled(hwnd):
                return True
            try:
                _, window_pid = win32process.GetWindowThreadProcessId(hwnd)
            except Exception:
                return True
            if window_pid != pid:
                return True
            if hwnd_class and win32gui.GetClassName(hwnd) != hwnd_class:
                return True
            if require_title and not win32gui.GetWindowText(hwnd):
                return True

            matches.append(hwnd)
            return True

        win32gui.EnumWindows(callback, None)
        if not matches:
            return 0

        visible = [hwnd for hwnd in matches if win32gui.IsWindowVisible(hwnd)]
        return visible[0] if visible else matches[0]

    def _get_window_size(self, hwnd):
        try:
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            return max(0, right - left), max(0, bottom - top)
        except Exception as e:
            self.log_debug(f"Failed to get window size for hwnd={hwnd}: {e}")
            return 0, 0

    def _is_usable_window_size(self, size):
        width, height = size
        return width > 200 and height > 200

    def _wait_for_window_size_to_settle(self, hwnd, exe_name, wait_start, time_out, settle_time=8):
        self.log_info(f"Waiting for {exe_name} window size to settle for {settle_time}s")
        stable_start = time.time()
        last_size = self._get_window_size(hwnd)
        last_log_time = 0

        while time.time() - wait_start < time_out:
            if not win32gui.IsWindow(hwnd):
                self.log_warning(f"Window for {exe_name} disappeared while settling; hwnd={hwnd}")
                return False

            self._restore_window_if_minimized(hwnd, exe_name)
            size = self._get_window_size(hwnd)
            if not self._is_usable_window_size(size):
                stable_start = time.time()
            elif size != last_size:
                self.log_info(
                    f"Window size for {exe_name} changed while settling: "
                    f"{last_size[0]}x{last_size[1]} -> {size[0]}x{size[1]}"
                )
                stable_start = time.time()
                last_size = size
            elif time.time() - stable_start >= settle_time:
                self.log_info(f"Window size for {exe_name} settled at {size[0]}x{size[1]}")
                return True

            now = time.time()
            if now - last_log_time >= 2:
                stable_for = max(0, now - stable_start)
                self.log_info(
                    f"Waiting for {exe_name} window to settle; "
                    f"size={size[0]}x{size[1]}, stable_for={stable_for:.1f}s/{settle_time}s"
                )
                last_log_time = now
            self.sleep(0.5)

        self.log_warning(f"Timed out while waiting for {exe_name} window size to settle")
        return False

    def _restore_window_if_minimized(self, hwnd, exe_name):
        if win32gui.IsIconic(hwnd):
            self.log_info(f"Window for {exe_name} is minimized; restoring hwnd={hwnd}")
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)

    def _get_launcher_path(self):
        configured_path = self.config.get(self.CONF_PATH, "").strip()
        self.log_info(f"Configured Launcher Path: {configured_path or '<empty>'}")
        launcher_path = configured_path
        launcher_path = self._extract_launcher_path(launcher_path)
        if launcher_path:
            self.log_info(f"Using Launcher Path from config: {launcher_path}")
            self._update_launcher_path(launcher_path)
            return launcher_path

        if configured_path:
            self.log_warning(
                f"Configured Launcher Path does not exist; clearing it: {configured_path}"
            )
            self.config[self.CONF_PATH] = ""  # type: ignore

        self.log_info("Launcher Path config is empty or invalid; checking Windows registry")
        launcher_path = self._find_launcher_path_from_registry()
        if launcher_path:
            self.log_info(f"Using Launcher Path from registry: {launcher_path}")
            self._update_launcher_path(launcher_path)
            return launcher_path

        self.log_warning("Launcher Path could not be resolved")
        return ""

    def _update_launcher_path(self, path):
        if path and os.path.basename(path).lower() == LAUNCHER_EXE.lower() and os.path.exists(path):
            old_path = self.config.get(self.CONF_PATH, "")
            if old_path != path:
                self.log_info(f"Updating Launcher Path config: {path}")
                self.config[self.CONF_PATH] = path  # type: ignore
            else:
                self.log_info(f"Launcher Path config is already current: {path}")
        elif path:
            self.log_warning(f"Skip updating Launcher Path; path is not valid: {path}")

    def _update_launcher_path_from_game(self, game_path):
        if not game_path:
            self.log_warning("Game process path is unavailable; cannot derive launcher path")
            return

        path = os.path.abspath(game_path)
        self.log_info(f"Trying to derive launcher path from game path: {path}")
        parts = path.split(os.sep)
        lowered = [part.lower() for part in parts]
        if "client" in lowered:
            client_index = lowered.index("client")
            root = os.sep.join(parts[:client_index])
            launcher_path = os.path.join(root, "NTELauncher", LAUNCHER_EXE)
            self.log_info(f"Derived launcher path candidate: {launcher_path}")
            self._update_launcher_path(launcher_path)
        else:
            self.log_warning(f"Could not derive launcher path from game path: {path}")

    def _find_launcher_path_from_registry(self):
        try:
            import winreg
        except ImportError:
            self.log_warning("winreg is unavailable; registry lookup skipped")
            return ""

        self.log_info("Scanning Windows uninstall registry keys for NTE launcher")
        roots = [winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE]
        uninstall_keys = [
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
            r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
        ]
        views = [0, winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY]

        for root in roots:
            for key_path in uninstall_keys:
                for view in views:
                    launcher_path = self._scan_uninstall_registry(root, key_path, view, winreg)
                    if launcher_path:
                        self.log_info(f"Found launcher path in registry: {launcher_path}")
                        return launcher_path
        self.log_warning("No launcher path found in registry")
        return ""

    def _scan_uninstall_registry(self, root, key_path, view, winreg):
        try:
            with winreg.OpenKey(root, key_path, 0, winreg.KEY_READ | view) as key:
                subkey_count = winreg.QueryInfoKey(key)[0]
                for index in range(subkey_count):
                    try:
                        subkey_name = winreg.EnumKey(key, index)
                        with winreg.OpenKey(key, subkey_name) as subkey:
                            launcher_path = self._launcher_path_from_registry_values(subkey, winreg)
                            if launcher_path:
                                return launcher_path
                    except OSError:
                        continue
        except OSError:
            self.log_debug(f"Registry key unavailable: root={root}, key={key_path}, view={view}")
            return ""
        return ""

    def _launcher_path_from_registry_values(self, subkey, winreg):
        values = {}
        for name in ("DisplayName", "InstallLocation", "DisplayIcon", "UninstallString"):
            try:
                values[name] = str(winreg.QueryValueEx(subkey, name)[0])
            except OSError:
                values[name] = ""

        combined = " ".join(values.values()).lower()
        if not any(token in combined for token in ("neverness", "ntegame", "ntelauncher")):
            return ""

        self.log_info(f"Potential NTE registry entry found: {values.get('DisplayName')}")
        for value in values.values():
            launcher_path = self._extract_launcher_path(value)
            if launcher_path:
                return launcher_path

        install_location = values.get("InstallLocation", "").strip().strip('"')
        for base in (install_location, os.path.dirname(install_location)):
            launcher_path = self._launcher_path_from_install_root(base)
            if launcher_path:
                return launcher_path
        return ""

    def _extract_launcher_path(self, value):
        if not value:
            return ""

        match = re.search(r'"?([a-zA-Z]:\\[^"]*?NTEGame\.exe)"?', value)
        if match and os.path.exists(match.group(1)):
            return match.group(1)

        path = value.strip().strip('"')
        if os.path.basename(path).lower() == LAUNCHER_EXE.lower() and os.path.exists(path):
            return path

        return self._launcher_path_from_install_root(path)

    def _launcher_path_from_install_root(self, path):
        if not path:
            return ""
        candidates = [
            os.path.join(path, "NTELauncher", LAUNCHER_EXE),
            os.path.join(path, LAUNCHER_EXE),
        ]
        for candidate in candidates:
            if os.path.exists(candidate):
                return candidate
        return ""

    def _format_process(self, proc_info):
        if not proc_info:
            return "not found"
        name = proc_info.get("name") or "<unknown>"
        exe = proc_info.get("exe") or "<path unavailable>"
        return f"name={name}, exe={exe}"

    def _check_admin(self):
        if not is_admin():
            communicate.starting_emulator.emit(
                True,
                "PC version requires admin privileges, Please restart this app with admin privileges!",  # noqa: E501
                0,
            )
            communicate.restart_admin.emit()
            return False
        return True


launcher_btn_ready_color = {
    "r": (215, 225),
    "g": (215, 225),
    "b": (215, 225),
}
