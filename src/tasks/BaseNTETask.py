import ctypes
import inspect
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any, Callable, List

import cv2
import win32api
import win32con
import win32gui
import win32process
from ok import BaseTask, Box, CannotFindException, Logger, og, safe_get

from src.Labels import Labels
from src.scene.NTEScene import NTEScene
from src.scene.ScreenPosition import ScreenPosition
from src.tasks.CharUIMixin import CharUIMixin
from src.utils import image_utils as iu

logger = Logger.get_logger(__name__)
stamina_re = re.compile(r"(\d+)/(\d+)")


class BaseNTETask(CharUIMixin, BaseTask):
    DEFAULT_MOVE = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.scene: NTEScene | None = None
        self.key_config = self.get_global_config("Game Hotkey Config")
        self.monthly_card_config = self.get_global_config("Monthly Card Config")
        self.sound_config = self.get_global_config("Sound Trigger Config")
        self._logged_in = False
        self._rotated_template_cache = {}
        self.default_box = ScreenPosition(self)
        self._init_char_ui_state()
        self.next_monthly_card_start = 0
        self._last_interval_action_time = {}
        self._action_interval_lock = threading.Lock()

    def sync_config(self, config=None):
        """同步并保存配置"""
        target_config = config if config is not None else self.config
        if hasattr(target_config, "save_file"):
            target_config.save_file()
        self._refresh_config_ui(target_config)

    def _refresh_config_ui(self, config):
        """刷新指定配置对应的 UI 界面"""
        if not (hasattr(og, "app") and og.app.main_window):
            return

        vBoxLayout = og.app.main_window.onetime_tab.vBoxLayout
        for i in range(vBoxLayout.count()):
            widget = vBoxLayout.itemAt(i).widget()
            if widget and hasattr(widget, "config"):
                # 如果 widget 绑定的 config 对象是一致的，则刷新
                if widget.config is config:
                    widget.update_config()
                    break

    @property
    def thread_pool_executor(self) -> ThreadPoolExecutor | None:
        if og.my_app is None:
            return None
        return og.my_app.get_thread_pool_executor()

    def submit_periodic_task(self, delay, task, *args, **kwargs):
        """
        提交一个循环任务到线程池。
        如果要停止循环，任务函数应返回 False。

        :param task: 要执行的函数
        :param delay: 每次执行后的间隔时间（秒）
        :param args: 位置参数
        :param kwargs: 关键字参数
        """
        if og.my_app is None:
            return
        return og.my_app.submit_periodic_task(delay, task, *args, **kwargs)

    def _openvino_detect(self, frame, sync, box, threshold, force=False, mask_regions=None):
        if og.my_app is None:
            return []
        if box is None:
            box = self.box_of_screen(0.0840, 0.1326, 0.9030, 0.8694, name="openvino_box")
        self.draw_boxes(boxes=box, color="blue")
        if frame is None:
            frame = self.frame
        if sync:
            results = og.my_app.openvino_detect_sync(
                image=frame, box=box, threshold=threshold, mask_regions=mask_regions
            )
        else:
            results = og.my_app.openvino_detect_async(
                image=frame,
                box=box,
                threshold=threshold,
                force=force,
                mask_regions=mask_regions,
            )
        if results:
            self.draw_boxes(boxes=results, color="red")
        return results

    def openvino_detect_async(
        self, frame=None, box: Box = None, threshold=0.7, force=False, mask_regions=None
    ) -> List[Box]:
        """异步检测，返回结果可能为缓存值"""
        return self._openvino_detect(
            frame, False, box, threshold, force=force, mask_regions=mask_regions
        )

    def openvino_detect_sync(
        self, frame=None, box: Box = None, threshold=0.7, mask_regions=None
    ) -> List[Box]:
        """同步检测，会等待结果返回"""
        return self._openvino_detect(frame, True, box, threshold, mask_regions=mask_regions)

    def openvino_clear_cache(self):
        """清空缓存"""
        if og.my_app is None:
            return
        og.my_app.openvino_clear_cache()

    @property
    def main_viewport(self):
        return self.box_of_screen(0.0984, 0.1042, 0.8961, 0.8944, name="main_viewport")

    # fmt: off
    def click(self, x: int | Box | List[Box] = -1, y=-1, move_back=None, name=None,
              interval=-1, move=None, down_time=0.02, after_sleep=0, key='left',
              hcenter=False, vcenter=False, action_name=None) -> Any:
        if action_name is not None:
            if not self.check_action_interval(action_name, interval):
                return False
            interval = -1

        if move is None:
            move = self.DEFAULT_MOVE
        if move_back is None:
            move_back = move
        return super().click(
            x, y, move_back=move_back, name=name, interval=interval, move=move,
            down_time=down_time, after_sleep=after_sleep, key=key,
            hcenter=hcenter, vcenter=vcenter
        )

    def operate_click(self, x: int | Box | List[Box] = -1, y=-1, restore_cursor=True, name=None,
                      interval=-1, down_time=0.02, after_sleep=0, key='left',
                      hcenter=False, vcenter=False, action_name=None) -> Any:
        action_name = action_name or "operate_click"
        if not self.check_action_interval(action_name, interval):
            return False
        result = self.operate(
            lambda: self.click(
                x, y, name=name, interval=-1, move=True, down_time=down_time,
                after_sleep=0, key=key, hcenter=hcenter, vcenter=vcenter
            ),
            block=True,
            restore_cursor=restore_cursor,
        )
        self.sleep(after_sleep)
        return result

    def send_key(self, key, down_time=0.02, interval=-1, after_sleep=0, action_name=None) -> Any:
        if action_name is not None:
            if not self.check_action_interval(action_name, interval):
                return False
            interval = -1
        return super().send_key(
            key, down_time=down_time, interval=interval, after_sleep=after_sleep
        )
    # fmt: on

    def check_action_interval(self, action_name: Any, interval: float) -> bool:
        if interval <= 0:
            return True
        # action_name must be a stable identifier, not a dynamic value.
        with self._action_interval_lock:
            now = time.time()
            last_time = self._last_interval_action_time.get(action_name, 0)
            if now - last_time < interval:
                return False
            self._last_interval_action_time[action_name] = now
            return True

    def _get_interval_func_key(self, func: Callable):
        bound_func = getattr(func, "__func__", None)
        if bound_func is not None:
            return ("func_interval", id(getattr(func, "__self__", None)), bound_func)

        code = getattr(func, "__code__", None)
        if code is not None:
            return ("func_interval", code)

        try:
            hash(func)
        except TypeError:
            return ("func_interval", id(func))
        return ("func_interval", func)

    def run_with_interval(
        self,
        func: Callable,
        interval: float,
        *args,
        action_name=None,
        **kwargs,
    ) -> Any:
        """按函数自己的时间间隔执行，未到间隔时返回 False。"""
        action_name = action_name or self._get_interval_func_key(func)
        if not self.check_action_interval(action_name, interval):
            return False
        return func(*args, **kwargs)

    def operate(self, func: Callable, block=False, restore_cursor=True):
        from src.interaction.NTEInteraction import NTEInteraction

        if isinstance(self.executor.interaction, NTEInteraction):
            return self.executor.interaction.operate(func, block, restore_cursor=restore_cursor)
        else:
            return func()

    def move_mouse_relative(self, dx, dy):
        from src.interaction.NTEInteraction import NTEInteraction

        if isinstance(self.executor.interaction, NTEInteraction):
            self.bring_to_front(after_sleep=1)
            return self.executor.interaction.move_mouse_relative(dx, dy)

    def get_char_box(self, index: int):
        box = self.get_box_by_name(f"box_char_{index + 1}")
        if self._char_ui_offset:
            box = self._shift_char_ui_box(box)
        return box

    def get_base_char_element_box(self):
        return super().get_base_char_element_box()

    def is_in_team(self) -> Box | None:
        frame = self.frame
        if frame is None:
            self.log_warning("Received an empty or None frame. Skipping...")
            time.sleep(1)
            return
        box = self.find_one(
            Labels.health_bar_slash,
            mask_function=iu.mask_corners,
            horizontal_variance=0.01,
            vertical_variance=0.005,
            frame=frame,
        )
        # self.log_debug(f"is_in_team {box}")
        return box

    def in_team(self):
        if not self.is_in_team():
            return False, -1, 0

        if self.scene is not None:
            state, timestamp = self.scene.get_is_in_team_record()
            if state and (to_sleep := 0.5 - (time.time() - timestamp)) > 0:
                self.sleep(to_sleep)

        arr = self._update_char_ui_offset()

        # self.log_debug(f"in_team {arr}")
        current = self.get_current_char_index()
        exist_count = 0
        for i in range(len(arr)):
            if arr[i] is not None:
                exist_count += 1
            elif current == -1:
                current = i

        if current != -1 and arr[current] is None:
            exist_count += 1

        self._logged_in = True
        return True, current, exist_count

    def get_box_by_char_spacing(self, box: Box, index: int):
        return super().get_box_by_char_spacing(box, index)

    def is_char_at_index(self, index, threshold=0.5, frame=None):
        return super().is_char_at_index(index, threshold=threshold, frame=frame)

    def get_current_char_index(self):
        return super().get_current_char_index()

    def in_world(self) -> bool:
        frame = self.frame
        template_bgr = self.get_feature_by_name(Labels.mini_map_arrow).mat
        mat = self.box_of_screen(0.0691, 0.1083, 0.0949, 0.1493, name="in_world").crop_frame(frame)
        mat = iu.binarize_bgr_by_brightness(mat, threshold=200)
        res, _ = self._find_rotated_template(
            template_bgr,
            mat,
            threshold=0.75,
            cache_key=Labels.mini_map_arrow,
        )
        # self.log_debug(f"in_world {res}, cost {cost} ms")
        return len(res) == 1

    def _find_rotated_template(
        self,
        template,
        scene,
        threshold=0.75,
        angle_range=range(-180, 180, 5),
        min_non_zero=20,
        cache_key=None,
        template_angle=0,
    ):
        start_time = time.time()
        scene_mask = self._first_channel_mask(scene)
        if cv2.countNonZero(scene_mask) < min_non_zero:
            return [], (time.time() - start_time) * 1000

        best = None
        for angle, rotated_template in self._get_rotated_templates(
            template,
            angle_range=angle_range,
            min_non_zero=min_non_zero,
            cache_key=cache_key,
        ):
            th, tw = rotated_template.shape[:2]
            if th > scene_mask.shape[0] or tw > scene_mask.shape[1]:
                continue

            result = cv2.matchTemplate(scene_mask, rotated_template, cv2.TM_CCOEFF_NORMED)
            _, score, _, top_left = cv2.minMaxLoc(result)
            if best is None or score > best["score"]:
                best = {
                    "center": (top_left[0] + tw // 2, top_left[1] + th // 2),
                    "angle": self._normalize_angle(angle + template_angle),
                    "match_angle": angle,
                    "score": score,
                }

        if best is None or best["score"] < threshold:
            return [], (time.time() - start_time) * 1000

        best["score"] = round(best["score"], 3)
        return [best], (time.time() - start_time) * 1000

    def _get_rotated_templates(
        self,
        template,
        angle_range=range(-180, 180, 5),
        min_non_zero=20,
        cache_key=None,
    ):
        template_mask = self._trim_mask(self._first_channel_mask(template))
        angles = tuple(angle_range)
        template_key = (
            cache_key or id(template),
            template_mask.shape,
            cv2.countNonZero(template_mask),
            hash(template_mask.tobytes()),
            angles,
            min_non_zero,
        )
        cached = self._rotated_template_cache.get(template_key)
        if cached is not None:
            return cached

        templates = []
        for angle in angles:
            rotated = self._rotate_mask(template_mask, angle)
            rotated = self._trim_mask(rotated)
            if cv2.countNonZero(rotated) >= min_non_zero:
                templates.append((angle, rotated))

        self._rotated_template_cache[template_key] = templates
        return templates

    def _first_channel_mask(self, mat):
        if mat.ndim == 2:
            return mat
        return mat[:, :, 0]

    def _normalize_angle(self, angle):
        return (angle + 180) % 360 - 180

    def _rotate_mask(self, mask, angle):
        h, w = mask.shape[:2]
        center = (w / 2, h / 2)
        rotate_matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
        cos = abs(rotate_matrix[0, 0])
        sin = abs(rotate_matrix[0, 1])
        new_w = int(round(h * sin + w * cos))
        new_h = int(round(h * cos + w * sin))
        rotate_matrix[0, 2] += new_w / 2 - center[0]
        rotate_matrix[1, 2] += new_h / 2 - center[1]
        return cv2.warpAffine(
            mask,
            rotate_matrix,
            (new_w, new_h),
            flags=cv2.INTER_NEAREST,
            borderValue=0,
        )

    def _trim_mask(self, mask):
        points = cv2.findNonZero(mask)
        if points is None:
            return mask
        x, y, w, h = cv2.boundingRect(points)
        return mask[y : y + h, x : x + w]

    def _find_contours_from_first_channel(self, bgr):
        bin_mat = bgr[:, :, 0]
        contours, _ = cv2.findContours(bin_mat, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        return contours

    def _find_rotated_shape(self, target_contour, scene_contours, score_threshold=0.1):
        """
        target_contour: 要匹配的目标轮廓。
        scene_contours: 在场景中找到的候选轮廓。
        score_threshold: 越小越严格。通常 0.05-0.2 之间。
        """
        start_time = time.time()

        results = []
        for cnt in scene_contours:
            if cv2.contourArea(cnt) < 50:
                continue

            # 核心算法：比较两个形状的胡氏矩 (I1 模式最常用)
            # 返回值越小，匹配度越高（0 为完美匹配）
            score = cv2.matchShapes(target_contour, cnt, cv2.CONTOURS_MATCH_I1, 0.0)

            if score < score_threshold:
                # 计算重心和角度
                M = cv2.moments(cnt)
                if M["m00"] != 0:
                    cx = int(M["m10"] / M["m00"])
                    cy = int(M["m01"] / M["m00"])

                    # 使用最小外接矩形获取角度
                    rect = cv2.minAreaRect(cnt)
                    angle = rect[2]  # 得到角度

                    results.append({"center": (cx, cy), "angle": angle, "score": round(score, 3)})

        # 按分数升序排列（得分越低越好）
        results = sorted(results, key=lambda x: x["score"])
        return results, (time.time() - start_time) * 1000

    def in_team_and_world(self):
        in_team = self.is_in_team()
        in_world = self.in_world()
        return in_team and in_world

    def wait_in_team(self, time_out=30, raise_if_not_found=True, esc=False, settle_time=0):
        success = self.wait_until(
            self.is_in_team,
            time_out=time_out,
            raise_if_not_found=raise_if_not_found,
            post_action=lambda: self.back(after_sleep=2) if esc else None,
            settle_time=settle_time,
        )
        if success:
            self.sleep(0.1)
        return success

    def wait_in_team_and_world(self, time_out=30, raise_if_not_found=True, esc=False):
        success = self.wait_until(
            self.in_team_and_world,
            time_out=time_out,
            raise_if_not_found=raise_if_not_found,
            post_action=lambda: self.back(after_sleep=2) if esc else None,
        )
        if success:
            self.sleep(0.1)
        return success

    def set_pynput_interaction(self):
        self.bring_to_front()
        self.set_interaction(1)

    def set_post_interaction(self):
        self.set_interaction(0)

    def set_interaction(self, idx=0):
        """
        通过索引 (idx) 设置交互方法。
        会从配置的交互列表中读取指定索引的方法。
        """

        def get_name(m):
            return getattr(m, "__name__", str(m))

        methods: list = og.device_manager.windows_capture_config.get("interaction", [])
        available_options = [get_name(m) for m in methods]

        m = safe_get(methods, idx)
        if m is None:
            self.log_error(
                f"无法设置交互方式：索引 {idx} 越界。当前可用选择有: {available_options}"
            )
            return
        og.device_manager.set_interaction(m)
        self.log_info(f"已切换交互式方式: {get_name(m)}")

    def is_foreground(self):
        """
        检查窗口是否在最前端。
        """
        if not self.hwnd:
            return False
        return self.hwnd.is_foreground()

    def bring_to_front(self, after_sleep=0):
        """
        强制将窗口带到最前端。
        """
        if not self.hwnd:
            self.log_warning("bring_to_front skipped: hwnd_window unavailable")
            return False
        hwnd = self.hwnd.hwnd

        if self.is_foreground():
            self.log_info(f"bring_to_front {hwnd} already is foreground")
            return True

        self.log_info(f"try bring_to_front {hwnd}")

        current_thread_id = 0
        target_thread_id = 0
        foreground_thread_id = 0
        attached_target = False
        attached_foreground = False

        try:
            current_thread_id = win32api.GetCurrentThreadId()
            target_thread_id, _ = win32process.GetWindowThreadProcessId(hwnd)
            foreground_hwnd = win32gui.GetForegroundWindow()
            if foreground_hwnd:
                foreground_thread_id, _ = win32process.GetWindowThreadProcessId(foreground_hwnd)

            if target_thread_id and target_thread_id != current_thread_id:
                attached_target = bool(
                    ctypes.windll.user32.AttachThreadInput(
                        current_thread_id, target_thread_id, True
                    )
                )
            if (
                foreground_thread_id
                and foreground_thread_id != current_thread_id
                and foreground_thread_id != target_thread_id
            ):
                attached_foreground = bool(
                    ctypes.windll.user32.AttachThreadInput(
                        current_thread_id, foreground_thread_id, True
                    )
                )

            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.BringWindowToTop(hwnd)
            win32gui.SetForegroundWindow(hwnd)
            self.sleep(0.1)
            if self.is_foreground():
                self.log_info(f"bring_to_front {hwnd} succeeded")
                self.sleep(after_sleep)
                return True
            self.log_info(f"bring_to_front {hwnd} did not keep foreground")
            return False
        except Exception as e:
            logger.debug(f"bring_to_front failed: {e}")
            return False
        finally:
            if attached_foreground:
                ctypes.windll.user32.AttachThreadInput(
                    current_thread_id, foreground_thread_id, False
                )
            if attached_target:
                ctypes.windll.user32.AttachThreadInput(current_thread_id, target_thread_id, False)

    @property
    def interac_box(self):
        interac_box = self.get_box_by_name(Labels.interactable)
        interac_box = interac_box.copy(
            x_offset=-interac_box.width * 0.3,
            y_offset=-interac_box.height * 2.5,
            width_offset=interac_box.width * 0.6,
            height_offset=interac_box.height * 5,
            name="search_interac",
        )
        return interac_box

    def find_interac(self):
        return self.find_one(
            Labels.interactable,
            box=self.interac_box,
            threshold=0.7,
            mask_function=interac_mask,
            use_gray_scale=True,
        )

    def walk_until_interac(self, direction="w", time_out=10, raise_if_not_found=False):
        ret = False
        try:
            self.middle_click(after_sleep=0.2)
            self.send_key_down(direction)
            ret = bool(
                self.wait_until(
                    self.find_interac,
                    time_out=time_out,
                    raise_if_not_found=raise_if_not_found,
                )
            )
        finally:
            self.send_key_up(direction)
        return ret

    def find_traval_button(self):
        box = self.get_box_by_name(Labels.teleport)
        w = box.width - (box.x - self.width_of_screen(0.99))
        y = -box.width * 0.2
        box = box.copy(y_offset=y, width_offset=w, height_offset=-y)
        return self.find_one(Labels.teleport, box=box)

    def click_nearest_map_teleport(self, threshold=0.7, time_out=5):
        self.ensure_main()
        self.wait_until(
            lambda: self.find_one(Labels.map_city_tycoon_activities),
            time_out=10,
            pre_action=lambda: self.send_key("m", interval=2),
            raise_if_not_found=True,
        )
        to_find = [Labels.map_big_teleport, Labels.map_small_teleport]
        template_boxes = [self.get_box_by_name(label) for label in to_find]
        max_template_size = max(
            max(template_box.width, template_box.height) for template_box in template_boxes
        )
        step = max(max_template_size, self.width_of_screen(0.02), 1)
        center_x = self.width_of_screen(0.5)
        center_y = self.height_of_screen(0.5)
        max_radius = max(self.width, self.height)

        def find_teleport():
            radius = step
            while radius <= max_radius:
                x = max(0, center_x - radius)
                y = max(0, center_y - radius)
                to_x = min(self.width, center_x + radius)
                to_y = min(self.height, center_y + radius)
                box = Box(x=x, y=y, to_x=to_x, to_y=to_y, name="nearest_map_teleport")
                teleport = self.find_best_match_in_box(box, to_find, threshold=threshold)
                if teleport:
                    return teleport
                radius += step

        teleport = self.wait_until(find_teleport, time_out=time_out, raise_if_not_found=True)
        self.log_info(f"found nearest map teleport {teleport}")
        self.operate_click(teleport, action_name="click_nearest_map_teleport", interval=1)
        self.sleep(0.5)
        self.click_traval_button()
        return teleport

    def click_traval_button(self, travel_btn=None):
        if not isinstance(travel_btn, Box):
            travel_btn = self.wait_until(
                self.find_traval_button, time_out=10, raise_if_not_found=True
            )

        self.sleep(0.1)
        self.operate_click(travel_btn)
        self.sleep(1)

    def openF1panel(self):
        if hasattr(self, "reset_to_false"):
            self.reset_to_false("opening f1 panel")
        if self.in_team_and_world():
            self.send_key("f1", after_sleep=1)
            self.log_info("send f1 key to open the panel")

        result = self.wait_panel(Labels.f1_panel)
        if not result:
            self.log_error("can't find panel, make sure f1 is the hotkey for panel", notify=True)
            raise CannotFindException("can't find panel, make sure f1 is the hotkey for panel")
        self.sleep(0.5)
        return result

    def openF2panel(self):
        if hasattr(self, "reset_to_false"):
            self.reset_to_false("opening f2 panel")
        if self.in_team_and_world():
            self.send_key("f2", after_sleep=1)
            self.log_info("send f2 key to open the panel")

        result = self.wait_panel(Labels.f2_panel)
        if not result:
            self.log_error("can't find panel, make sure f2 is the hotkey for panel", notify=True)
            raise CannotFindException("can't find panel, make sure f2 is the hotkey for panel")
        self.sleep(0.5)
        return result

    def openF5panel(self):
        if hasattr(self, "reset_to_false"):
            self.reset_to_false("opening f5 panel")
        if self.in_team_and_world():
            self.send_key("f5", after_sleep=1)
            self.log_info("send f5 key to open the panel")

        result = self.wait_panel(Labels.f5_panel)
        if not result:
            self.log_error("can't find panel, make sure f5 is the hotkey for panel", notify=True)
            raise CannotFindException("can't find panel, make sure f5 is the hotkey for panel")
        self.sleep(0.5)
        return result

    def openESCpanel(self):
        if hasattr(self, "reset_to_false"):
            self.reset_to_false("opening esc panel")
        if self.in_team_and_world():
            self.send_key("esc", after_sleep=1)
            self.log_info("send esc key to open the panel")

        result = self.wait_panel(Labels.esc_option, box=Labels.box_all_esc_options, threshold=0.3)
        if not result:
            self.log_error("can't find panel, make sure esc is the hotkey for panel", notify=True)
            raise CannotFindException("can't find panel, make sure esc is the hotkey for panel")
        self.sleep(0.5)
        return result

    def wait_panel(self, feature, box=None, threshold=0.8, time_out=4.5):
        result = self.wait_until(
            lambda: self.find_one(feature, box=box, threshold=threshold),
            time_out=time_out,
            settle_time=0.5,
        )
        logger.info(f"found {feature} {result}")
        return result

    def ensure_main(self, esc=True, time_out=30):
        self.info_set("current task", f"wait main esc={esc}")
        if not self._logged_in:
            time_out = 600
        if not self.wait_until(
            lambda: self.is_main(esc=esc), time_out=time_out, raise_if_not_found=False
        ):
            raise Exception("Please start in game world and in team!")
        self.sleep(0.5)
        self.info_set("current task", None)

    def is_main(self, esc=True):
        if self.in_team_and_world():
            self._logged_in = True
            return True
        if self.handle_monthly_card():
            return True
        if self.wait_login():
            return True
        if esc:
            self.back(after_sleep=2)

    def find_monthly_card(self):
        return self.find_one(Labels.monthly_card)

    def should_check_monthly_card(self):
        if self.next_monthly_card_start > 0:
            if 0 < time.time() - self.next_monthly_card_start < 120:
                return True
        return False

    def handle_monthly_card(self):
        monthly_card = self.find_monthly_card()
        # self.screenshot('monthly_card1')
        if monthly_card is not None:
            # self.screenshot('monthly_card1')
            self.log_info("monthly_card found click")
            self.click(0.50, 0.89)
            self.sleep(2)
            # self.screenshot('monthly_card2')
            self.click(0.50, 0.89)
            self.sleep(2)
            self.wait_until(
                self.in_team_and_world,
                time_out=10,
                post_action=lambda: self.click(0.50, 0.89, after_sleep=1),
            )
            # self.screenshot('monthly_card3')
            self.set_check_monthly_card(next_day=True)
        # logger.debug(f'check_monthly_card {monthly_card}')
        return monthly_card is not None

    def set_check_monthly_card(self, next_day=False):
        if self.monthly_card_config.get("Check Monthly Card"):
            now = datetime.now()
            hour = self.monthly_card_config.get("Monthly Card Time")
            # Calculate the next 4 o'clock in the morning
            next_four_am = now.replace(hour=hour, minute=0, second=0, microsecond=0)
            if now >= next_four_am or next_day:
                next_four_am += timedelta(days=1)
            next_monthly_card_start_date_time = next_four_am - timedelta(seconds=30)
            # Subtract 1 minute from the next 4 o'clock in the morning
            self.next_monthly_card_start = next_monthly_card_start_date_time.timestamp()
            logger.info(
                "set next monthly card start time to {}".format(next_monthly_card_start_date_time)
            )
        else:
            self.next_monthly_card_start = 0

    def wait_login(self):
        if not self._logged_in:
            if self.in_team_and_world():
                return True
            self.handle_monthly_card()
            # texts = self.ocr(log=self.debug)
            # if login := self.find_boxes(
            #     texts, boundary=self.box_of_screen(0.3, 0.3, 0.7, 0.7), match="登录"
            # ):
            #     if not self.find_boxes(
            #         texts, boundary=self.box_of_screen(0.3, 0.3, 0.7, 0.7), match="+86"
            #     ):
            #         self.click(login, after_sleep=1)
            #         self.log_info("点击登录按钮!")
            #     return False
            # if agree := self.find_boxes(
            #     texts, boundary=self.box_of_screen(0.3, 0.3, 0.7, 0.7), match="同意"
            # ):
            #     self.log_debug(f"found agree {agree}")
            #     if self.find_boxes(
            #         texts, boundary=self.box_of_screen(0.3, 0.3, 0.7, 0.7),
            #         match=re.compile(r"\d{11}"),
            #     ):
            #         self.click(agree, after_sleep=1)
            #         self.log_info("点击同意按钮!")
            #     return False
            # if self.find_boxes(texts, match=re.compile("游戏即将重启")):
            #     self.log_info("游戏更新成功, 游戏即将重启")
            #     self.click(self.find_boxes(texts, match="确认"), after_sleep=60)
            #     result = self.start_device()
            #     self.log_info(f"start_device end {result}")
            #     self.sleep(30)
            #     return False

            # if start := self.find_boxes(
            #     texts, boundary="bottom_right", match=["开始游戏", re.compile("进入游戏")]
            # ):
            #     if not self.find_boxes(texts, boundary="bottom_right", match="登录"):
            #         self.click(start)
            #         self.log_info(f"点击开始游戏! {start}")
            #         return False

            if self.find_one(Labels.login_setting):
                self.log_info("found login_setting, bring_to_front and click")
                if not self.is_foreground():
                    self.bring_to_front()
                    self.sleep(3)
                self.operate_click(0.499, 0.865, after_sleep=3)
                return False

    def find_treasure(self):
        # now = time.time()
        result = self.find_one(
            Labels.treasure,
            box=self.main_viewport,
            threshold=0.7,
            use_gray_scale=True,
        )
        # if result:
        #     self.log_info(f"find_treasure conf {result.confidence}, cost {time.time() - now}s")
        return result

    def walk_to_treasure(self):
        if self.find_treasure():
            self.walk_to_box(self.find_treasure, end_condition=self.find_interac, y_offset=0.1)
            return True

    def walk_to_box(
        self, find_function, time_out=30, end_condition=None, y_offset=0.05, x_threshold=0.07
    ):
        start = time.time()
        while time.time() - start < time_out:
            if ended := self._do_walk_to_box(
                find_function,
                time_out=time_out - (time.time() - start),
                end_condition=end_condition,
                y_offset=y_offset,
                x_threshold=x_threshold,
            ):
                return ended

    @staticmethod
    def _resolve_target(result):
        """将 find_function 的返回值统一为单个目标或 None"""
        if isinstance(result, list):
            return result[0] if result else None
        return result

    def _calc_walk_direction(self, last_target, last_direction, y_offset, x_threshold, centered):
        """根据目标位置计算下一步移动方向，返回 (direction, centered)"""
        if last_target is None:
            return self.opposite_direction(last_direction), centered

        x, y = last_target.center()
        y = max(0, y - self.height_of_screen(y_offset))
        x_abs = abs(x - self.width_of_screen(0.5))
        threshold = 0.04 if not last_direction else x_threshold
        centered = x_abs <= self.width_of_screen(threshold)

        if not centered:
            direction = "d" if x > self.width_of_screen(0.5) else "a"
        else:
            if last_direction == "s":
                v_center = 0.45
            elif last_direction == "w":
                v_center = 0.6
            else:
                v_center = 0.5
            direction = "s" if y > self.height_of_screen(v_center) else "w"
        return direction, centered

    def _do_walk_to_box(
        self, find_function, time_out=30, end_condition=None, y_offset=0.05, x_threshold=0.07
    ):
        if find_function:
            self.wait_until(
                lambda: (not end_condition or end_condition()) or find_function(),
                raise_if_not_found=True,
                time_out=time_out,
            )
        last_direction = None
        start = time.time()
        ended = False
        last_target = None
        centered = False
        try:
            while time.time() - start < time_out:
                self.next_frame()
                if end_condition:
                    ended = end_condition()
                    if ended:
                        logger.info(f"_do_walk_to_box ended {ended}")
                        break
                target = self._resolve_target(find_function())
                if target:
                    last_target = target
                if last_target is None:
                    self.log_info("find_function not found, change to opposite direction")
                next_direction, centered = self._calc_walk_direction(
                    last_target, last_direction, y_offset, x_threshold, centered
                )
                if next_direction != last_direction:
                    if last_direction:
                        self.send_key_up(last_direction)
                        self.sleep(0.001)
                    last_direction = next_direction
                    if next_direction:
                        self.send_key_down(next_direction)
        finally:
            if last_direction:
                self.send_key_up(last_direction)
                self.sleep(0.001)
        return ended if end_condition else last_direction is not None

    def opposite_direction(self, direction):
        if direction == "w":
            return "s"
        elif direction == "s":
            return "w"
        elif direction == "a":
            return "d"
        elif direction == "d":
            return "a"
        else:
            return "w"

    def send_interac(self, handle_claim=True):
        if self.find_interac():
            self.send_key("f", after_sleep=0.8)
            if not handle_claim:
                return True
            if not self.handle_claim_button():
                return True

    def handle_claim_button(self):
        while self.wait_until(self.has_claim, raise_if_not_found=False, time_out=1.5):
            self.sleep(0.5)
            self.send_key("esc")
            self.sleep(0.5)
            logger.info("handle_claim_button found a claim reward")
        return True

    def has_claim(self):
        return not self.is_in_team() and self.find_all_claim()

    def find_all_claim(self) -> List[Box]:
        box = self.box_of_screen(0.2645, 0.6167, 0.7352, 0.6785, name="reward_area")
        return self.find_feature(Labels.claim_icon, box=box)

    def get_stamina(self):
        boxes = self.wait_ocr(0.814, 0.029, 0.898, 0.083, raise_if_not_found=False)
        if not boxes:
            self.screenshot("stamina_error")
            return -1
        current = 0
        for box in boxes:
            box.name = self._fix_stamina_ocr_slash(box.name)
            if match := stamina_re.search(box.name):
                current = int(match.group(1))
        self.info_set("当前体力", current)
        return current

    def _fix_stamina_ocr_slash(self, text):
        # 如果長度小於 4，說明數據本身不完整，直接返回原文字
        if len(text) < 4:
            return text

        numerator = text[:-4]
        maybe_slash = text[-4]
        denominator = text[-3:]

        # 如果倒數第 4 位被誤識成了 1、l 或 |
        if maybe_slash in ["1", "l", "|"]:
            return f"{numerator}/{denominator}"

        return text

    def retry_on_action(self, action: Callable, reset_action: Callable | None = None, attempt=3):
        result = None
        count = 0

        sig = inspect.signature(action)
        params = sig.parameters
        has_count_param = "count" in params or any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()
        )

        while not result and count <= attempt:
            count += 1
            if has_count_param:
                result = action(count=count)  # 建议用关键字传参更安全
            else:
                result = action()
            if not result and reset_action is not None:
                reset_action()
        return result

    def wait_click_confirm(
        self,
        action,
        range: tuple[float, float, float, float] | None = None,
        raise_if_not_found=True,
    ):
        if range is None:
            box = self.main_viewport
        else:
            box = self.box_of_screen(*range)
        button = self.wait_until(
            lambda: self.find_one(Labels.skip_quest_confirm, box=box),
            pre_action=action,
            settle_time=1,
            raise_if_not_found=raise_if_not_found,
        )
        if not button:
            return False
        result = self.wait_until(
            lambda: not self.find_one(Labels.skip_quest_confirm, box=box),
            pre_action=lambda: self.operate_click(button, interval=2),
            settle_time=1,
            raise_if_not_found=raise_if_not_found,
        )
        return bool(result)


def interac_mask(image):
    mask = iu.create_color_mask(image, interac_pink_color, to_bgr=False)
    dilated_mask = iu.morphology_mask(mask, to_bgr=False)
    return dilated_mask


interac_pink_color = {
    "r": (197, 221),
    "g": (71, 78),
    "b": (119, 133),
}
