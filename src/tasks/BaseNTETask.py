import contextvars
import ctypes
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any, Callable, List, overload

import cv2
import numpy as np
import win32api
import win32con
import win32gui
import win32process

from ok import BaseTask, Box, CannotFindException, Logger, og, safe_get
from src.Labels import Labels
from src.scene.NTEScene import NTEScene
from src.scene.ScreenPosition import ScreenPosition
from src.utils import game_filters as gf
from src.utils import image_utils as iu
from src.utils.viewport_adapter import (
    MODE_AUTO_16_9_VIEWPORT,
    MODE_NATIVE_SCREEN,
    classify_ui_layout_profile,
    make_auto_viewport,
    make_native_viewport,
)

logger = Logger.get_logger(__name__)
stamina_re = re.compile(r"(\d+)[\s/\\|!Il／-]+\d+")


class BaseNTETask(BaseTask):
    DEFAULT_MOVE = False
    ESC_PANEL_THRESHOLD = 0.45
    _current_move = contextvars.ContextVar("current_move", default=None)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.scene: NTEScene | None = None
        self.key_config = self.get_global_config("Game Hotkey Config")
        self.monthly_card_config = self.get_global_config("Monthly Card Config")
        self.resolution_config = self._optional_global_config("Resolution Adaptation Config")
        self.sound_config = self.get_global_config("Sound Trigger Config")
        self._logged_in = False
        self.arrow_contour = {"contours": None, "shape": None}
        self.default_box = ScreenPosition(self)
        self.char_ui_offset = False
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
        og.my_app.submit_periodic_task(delay, task, *args, **kwargs)

    def _openvino_detect(self, frame, sync, box, threshold, force=False, mask_regions=None):
        if og.my_app is None:
            return []
        if box is None:
            box = self.box_of_screen(0.0840, 0.1326, 0.9176, 0.8694, name="openvino_box")
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
        self, frame=None, box: Box = None, threshold=0.6, force=False, mask_regions=None
    ) -> List[Box]:
        """异步检测，返回结果可能为缓存值"""
        return self._openvino_detect(
            frame, False, box, threshold, force=force, mask_regions=mask_regions
        )

    def openvino_detect_sync(
        self, frame=None, box: Box = None, threshold=0.5, mask_regions=None
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

    def _optional_global_config(self, option):
        try:
            return self.get_global_config(option)
        except RuntimeError as exc:
            if f"Can not find global config {option}" in str(exc):
                return None
            raise

    def get_ui_coordinate_mode(self):
        config = getattr(self, "resolution_config", None)
        if config is None:
            return MODE_AUTO_16_9_VIEWPORT

        mode = config.get("UI Coordinate Mode")
        if mode in (MODE_AUTO_16_9_VIEWPORT, MODE_NATIVE_SCREEN):
            return mode
        return MODE_AUTO_16_9_VIEWPORT

    def get_ui_viewport(self, frame=None):
        if frame is None:
            try:
                frame = self.frame
            except Exception:
                frame = None

        shape = getattr(frame, "shape", None)
        try:
            has_frame_shape = shape is not None and len(shape) >= 2
        except TypeError:
            has_frame_shape = False

        if has_frame_shape:
            height, width = shape[:2]
        else:
            frame = None
            width = self.width
            height = self.height

        if self.get_ui_coordinate_mode() == MODE_NATIVE_SCREEN:
            return make_native_viewport(width, height)
        return make_auto_viewport(width, height, frame=frame)

    def get_ui_layout_profile(self, frame=None):
        viewport = self.get_ui_viewport(frame=frame)
        return classify_ui_layout_profile(
            viewport.screen_width,
            viewport.screen_height,
            viewport.mode,
        )

    def active_ui_frame(self, frame=None):
        frame = self.frame if frame is None else frame
        return self.get_ui_viewport(frame=frame).crop_active_frame(frame)

    def ui_point(self, x: float, y: float, frame=None):
        return self.get_ui_viewport(frame=frame).ui_point_to_screen_relative(x, y)

    def click_ui(self, x, y=None, **kwargs):
        if y is None:
            return self.click(x, **kwargs)

        px, py = self.get_ui_viewport().ui_point_to_screen_pixel(x, y)
        return self.click(px, py, **kwargs)

    def box_of_ui(
        self,
        x,
        y,
        to_x=1.0,
        to_y=1.0,
        width=0.0,
        height=0.0,
        name=None,
        confidence=1.0,
        frame=None,
    ):
        if name is None:
            name = f"{x} {y} {width} {height}"

        box_x, box_y, box_width, box_height = self.get_ui_viewport(
            frame=frame
        ).ui_box_to_screen_pixel(x, y, to_x=to_x, to_y=to_y, width=width, height=height)
        return Box(box_x, box_y, box_width, box_height, name=name, confidence=confidence)

    def ocr_ui(self, x, y, to_x=1.0, to_y=1.0, width=0.0, height=0.0, **kwargs):
        frame = kwargs.get("frame")
        kwargs["box"] = self.box_of_ui(
            x, y, to_x=to_x, to_y=to_y, width=width, height=height, frame=frame
        )
        return self.ocr(**kwargs)

    # fmt: off
    @overload
    def click(self, x: int | Box | List[Box] = -1, y=-1, move_back=False, name=None, interval=-1,
              move=False, down_time=0.02, after_sleep=0, key='left', hcenter=False,
              vcenter=False, action_name=None) -> Any:
        ...
    # fmt: on

    def click(self, *args, action_name=None, **kwargs):
        if action_name is not None:
            interval = kwargs.get("interval", 0.1)
            if not self.check_action_interval(action_name, interval):
                return False
            kwargs["interval"] = -1

        current_move = self._current_move.get()
        token = None

        if current_move is None:
            token = self._current_move.set(kwargs.get("move", self.DEFAULT_MOVE))
            current_move = self._current_move.get()
        kwargs["move"] = current_move

        try:
            return super().click(*args, **kwargs)
        finally:
            if token is not None:
                self._current_move.reset(token)

    # fmt: off
    @overload
    def operate_click(self, x: int | Box | List[Box] = -1, y=-1, move_back=False, name=None,
                       interval=-1, down_time=0.02, key='left',
                       hcenter=False, vcenter=False, action_name=None) -> Any:
        ...
    # fmt: on

    def operate_click(self, *args, **kwargs):
        kwargs["move"] = True
        kwargs["after_sleep"] = 0
        return self.operate(lambda: self.click(*args, **kwargs), block=True)

    # fmt: off
    @overload
    def send_key(self, key, down_time=0.02, interval=-1, after_sleep=0, action_name=None) -> Any:
        ...
    # fmt: on

    def send_key(self, *args, action_name=None, **kwargs):
        if action_name is not None:
            interval = kwargs.get("interval", 0.1)
            if not self.check_action_interval(action_name, interval):
                return False
            kwargs["interval"] = -1
        return super().send_key(*args, **kwargs)

    def check_action_interval(self, action_name: str, interval: float) -> bool:
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

    def operate(self, func: Callable, block=False):
        from src.interaction.NTEInteraction import NTEInteraction

        if isinstance(self.executor.interaction, NTEInteraction):
            return self.executor.interaction.operate(func, block)
        else:
            return func()

    def get_char_box(self, index: int):
        box = self.get_box_by_name(f"box_char_{index + 1}")
        if self.char_ui_offset:
            box = self.shift_char_ui_box(box)
        return box

    def get_char_text_box(self, index: int):
        box = self.get_box_by_name(f"char_{index + 1}_text")
        return box

    def get_base_char_element_box(self):
        box = self.box_of_screen_scaled(
            2560, 1440, 2438, 335, width_original=29, height_original=29
        )
        box = self.shift_char_ui_box(box, expend=True)
        return box

    def is_in_team(self):
        box = self.find_one(
            Labels.health_bar_slash,
            mask_function=iu.mask_corners,
            horizontal_variance=0.01,
            vertical_variance=0.005,
        )
        result = box is not None
        # self.log_debug(f"is_in_team {box}")
        return result

    def shift_char_ui_box(self, box: Box, expend=False):
        """
        针对角色UI偏移的box修正
        :param box:
        :param expend: 是否扩展box
        :return:
        """
        offset = -9 * self.width / 2560
        width_offset = 0
        if expend:
            width_offset = -offset
        box = box.copy(x_offset=offset, width_offset=width_offset)
        return box

    def in_team(self):
        if not self.is_in_team():
            return False, -1, 0

        if self.scene is not None:
            state, timestamp = self.scene.get_is_in_team_record()
            if state and (to_sleep := 0.5 - (time.time() - timestamp)) > 0:
                self.sleep(to_sleep)

        arr = self.update_char_ui_offset()

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

    def update_char_ui_offset(self):
        # now = time.time()
        arr = self.multi_stage_char_match()
        results = [
            c.x < self.get_char_text_box(idx).x for idx, c in enumerate(arr) if c is not None
        ]

        if results:
            self.char_ui_offset = sum(results) > (len(results) / 2)
        else:
            self.char_ui_offset = False
        # logger.debug(f"update_char_ui_offset cost {time.time() - now:.3f}")
        return arr

    @property
    def char_vertical_spacing(self):
        return int(self.height * 176 / 1440)

    def get_box_by_char_spacing(self, box: Box, index: int):
        return box.copy(y_offset=index * self.char_vertical_spacing, name=f"{box.name}_{index}")

    def _get_char_template_data(self):
        """延迟加载并缓存模板掩码和覆盖面积"""
        if (
            not hasattr(self, "_char_template_cache")
            or self._char_template_cache.get("width") != self.width
            or self._char_template_cache.get("height") != self.height
        ):
            feature = self.get_feature_by_name(Labels.is_current_char)
            mat = feature.mat  # 原始二值化模板
            white_pixels = cv2.countNonZero(mat)

            # 仍然保留膨胀掩码用于过滤
            kernel = np.ones((5, 5), np.uint8)
            mask = cv2.dilate(feature.mat, kernel, iterations=1)

            self._char_template_cache = {
                "width": self.width,
                "height": self.height,
                "mat": mat,
                "mask": mask,
                "white_pixels": white_pixels,
            }

        cache = self._char_template_cache
        return cache["mat"], cache["mask"], cache["white_pixels"]

    def get_char_match_score(self, index, frame=None):
        """获取指定位置的匹配得分（基于模板匹配），分值越小越匹配"""
        template_mat, _, template_white_count = self._get_char_template_data()
        if template_white_count == 0:
            return 1.0
        if frame is None:
            frame = self.frame

        base_box = self.get_box_by_name(Labels.is_current_char)
        base_box = self.shift_char_ui_box(base_box, expend=True)
        box = self.get_box_by_char_spacing(base_box, index)
        # self.draw_boxes(boxes=box, color="blue")

        current_mat = gf.current_char_filter(box.crop_frame(frame), blur=True)

        # 全白检测：过滤后近乎全白说明不是有效弧形，直接排除
        total_pixels = current_mat.shape[0] * current_mat.shape[1]
        if total_pixels > 0 and cv2.countNonZero(current_mat) / total_pixels > 0.5:
            return 1.0

        # 滑动覆盖率匹配（允许 current_mat 尺寸 >= template_mat）
        # TM_CCORR 在二值图上 = 255*255 * 重叠白像素数，等价于原 bitwise_and 覆盖率但支持滑动
        th, tw = template_mat.shape[:2]
        ch, cw = current_mat.shape[:2]
        if ch >= th and cw >= tw:
            result = cv2.matchTemplate(current_mat, template_mat, cv2.TM_CCORR)
            _, max_val, _, _ = cv2.minMaxLoc(result)
            coverage = max_val / (template_white_count * 255 * 255)
            return 1.0 - coverage

        return 1.0

    def is_char_at_index(self, index, threshold=0.3, frame=None):
        """判断指定索引是否为当前角色"""
        score = self.get_char_match_score(index, frame=frame)
        new = f"idx {index} conf {score:.3f}"
        if self.info_get("current char") != new:
            self.info_set("current char", new)
        if score < threshold:
            return True

    def get_current_char_index(self):
        """扫描所有槽位，返回匹配度最高的索引"""
        best_score = 999
        best_idx = -1

        for i in range(4):
            score = self.get_char_match_score(i)
            if score < best_score:
                best_score = score
                best_idx = i

        if best_idx != -1:
            self.log_debug(f"current_char found at {best_idx} with score {best_score:.4f}")
        return best_idx

    def multi_stage_char_match(self):
        # 初始化 4 个结果为 None
        results = [None, None, None, None]

        # 定义对比度阶梯（从低到高）
        # 低对比度下匹配到的置信度通常更高
        contrast_steps = [0, 30, 60, 90]

        for c_val in contrast_steps:
            # 如果 4 个都找齐了，直接跳出大循环，节省计算时间
            if all(res is not None for res in results):
                break

            for i in range(4):
                # 只有还没找到的位置才进行匹配
                if results[i] is None:
                    # 构造处理函数
                    def process(image, current_c=c_val):
                        return iu.adjust_lightness_contrast_lab(
                            image, brightness=0, contrast=current_c
                        )

                    res = self.find_one(
                        f"char_{i + 1}_text",
                        threshold=0.7,
                        frame_processor=process,
                        mask_function=iu.mask_outside_white_rect,
                        horizontal_variance=0.005,
                    )

                    # 只要找到了，就存入结果，后续对比度级别不再处理这个索引
                    if res:
                        results[i] = res

        return results

    def in_world(self) -> bool:
        frame = self.frame
        if self.arrow_contour["shape"] != frame.shape[:2]:
            template_bgr = self.get_feature_by_name(Labels.mini_map_arrow).mat
            t_bin = template_bgr[:, :, 0]
            contours, _ = cv2.findContours(t_bin, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if not contours:
                raise ValueError("contours is None")
            self.arrow_contour["contours"] = max(contours, key=cv2.contourArea)
            self.arrow_contour["shape"] = frame.shape[:2]

        mat = self.box_of_screen(0.0691, 0.1083, 0.0949, 0.1493, name="in_world").crop_frame(frame)
        mat = iu.binarize_bgr_by_brightness(mat, threshold=200)
        res, cost = self._find_rotated_shape(mat)
        # self.log_debug(f"in_world {res}, cost {cost} ms")
        return len(res) == 1

    def _find_rotated_shape(self, scene_bgr, score_threshold=0.1):
        """
        score_threshold: 越小越严格。通常 0.05-0.2 之间。
        """
        start_time = time.time()
        s_bin = scene_bgr[:, :, 0]
        scene_contours, _ = cv2.findContours(s_bin, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        results = []
        for cnt in scene_contours:
            if cv2.contourArea(cnt) < 50:
                continue

            # 核心算法：比较两个形状的胡氏矩 (I1 模式最常用)
            # 返回值越小，匹配度越高（0 为完美匹配）
            score = cv2.matchShapes(self.arrow_contour["contours"], cnt, cv2.CONTOURS_MATCH_I1, 0.0)

            if score < score_threshold:
                # 计算重心和角度
                M = cv2.moments(cnt)
                if M["m00"] != 0:
                    cx = int(M["m10"] / M["m00"])
                    cy = int(M["m01"] / M["m00"])

                    # 使用最小外接矩形获取角度
                    rect = cv2.minAreaRect(cnt)
                    angle = rect[2]  # 得到角度

                    results.append({"center": (cx, cy), "angle": angle, "score": score})

        # 按分数升序排列（得分越低越好）
        results = sorted(results, key=lambda x: x["score"])
        return results, (time.time() - start_time) * 1000

    def in_team_and_world(self):
        in_team = self.is_in_team()
        in_world = self.in_world()
        return in_team and in_world

    def wait_in_team(self, time_out=30, raise_if_not_found=True, esc=False):
        success = self.wait_until(
            self.is_in_team,
            time_out=time_out,
            raise_if_not_found=raise_if_not_found,
            post_action=lambda: self.back(after_sleep=2) if esc else None,
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
        hwnd_window = self.hwnd
        if not hwnd_window:
            return False
        is_foreground = getattr(hwnd_window, "is_foreground", None)
        if not callable(is_foreground):
            return False
        try:
            return is_foreground() is True
        except Exception:
            return False

    def bring_to_front(self):
        """
        强制将窗口带到最前端。
        """
        if self.is_foreground():
            return

        hwnd_window = self.hwnd
        hwnd = getattr(hwnd_window, "hwnd", hwnd_window)
        if not hwnd:
            return

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
        except Exception as e:
            logger.debug(f"bring_to_front failed: {e}")
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
        return result

    def wait_panel(self, feature, box=None, threshold=0.8, time_out=4.5, settle_time=0.5):
        result = self.wait_until(
            lambda: self.find_one(feature, box=box, threshold=threshold),
            time_out=time_out,
            settle_time=settle_time,
        )
        logger.info(f"found {feature} {result}")
        return result

    def openESCpanel(self):
        if hasattr(self, "reset_to_false"):
            self.reset_to_false("opening esc panel")
        if self.in_team_and_world():
            self.send_key("esc", after_sleep=1)
            self.log_info("send esc key to open the panel")

        result = self._wait_esc_panel()
        if not result:
            self.log_info("未检测到 ESC 面板，尝试前台发送 ESC 键")
            if self._send_foreground_key("esc", after_sleep=1):
                result = self._wait_esc_panel()
        if not result:
            self.log_error("can't find panel, make sure esc is the hotkey for panel", notify=True)
            raise CannotFindException("can't find panel, make sure esc is the hotkey for panel")
        return result

    def _wait_esc_panel(self):
        result = self.wait_until(
            self._find_esc_panel,
            time_out=4.5,
            settle_time=0,
        )
        logger.info(f"found esc panel {result}")
        return result

    def _find_esc_panel(self):
        result = self.find_one(
            Labels.esc_option,
            box=Labels.box_all_esc_options,
            threshold=self.ESC_PANEL_THRESHOLD,
        )
        if result:
            return result
        return self._find_esc_phone_menu()

    def _find_esc_phone_menu(self):
        try:
            frame = self.frame
        except Exception:
            return None

        shape = getattr(frame, "shape", None)
        if shape is None or len(shape) < 2:
            return None

        height, width = shape[:2]
        if height <= 0 or width <= 0:
            return None

        panel_x1, panel_y1 = int(width * 0.70), int(height * 0.12)
        panel_x2, panel_y2 = int(width * 0.98), int(height * 0.93)
        bar_x1, bar_y1 = int(width * 0.70), int(height * 0.79)
        bar_x2, bar_y2 = int(width * 0.98), int(height * 0.93)

        panel = frame[panel_y1:panel_y2, panel_x1:panel_x2]
        bottom_bar = frame[bar_y1:bar_y2, bar_x1:bar_x2]
        if panel.size == 0 or bottom_bar.size == 0:
            return None

        panel_dark = self._dark_pixel_ratio(panel, threshold=90)
        bar_dark = self._dark_pixel_ratio(bottom_bar, threshold=90)
        if panel_dark < 0.55 or bar_dark < 0.55:
            return None

        confidence = min(1.0, (panel_dark + bar_dark) / 2)
        return Box(
            panel_x1,
            panel_y1,
            panel_x2 - panel_x1,
            panel_y2 - panel_y1,
            name="esc_phone_menu",
            confidence=confidence,
        )

    @staticmethod
    def _dark_pixel_ratio(frame, threshold=90):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        return float(np.mean(gray < threshold))

    @staticmethod
    def _hsv_pixel_ratio(frame, hue_min, hue_max, saturation_min=80, value_min=120):
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask = (
            (hsv[:, :, 0] >= hue_min)
            & (hsv[:, :, 0] <= hue_max)
            & (hsv[:, :, 1] >= saturation_min)
            & (hsv[:, :, 2] >= value_min)
        )
        return float(np.mean(mask))

    def _send_foreground_key(self, key, down_time=0.05, after_sleep=0):
        try:
            self.bring_to_front()
            hwnd_window = self.hwnd
            if hasattr(hwnd_window, "bring_to_front"):
                hwnd_window.bring_to_front()
            foreground = True
            if hasattr(hwnd_window, "is_foreground"):
                foreground = False
                for _ in range(5):
                    time.sleep(0.1)
                    if hwnd_window.is_foreground():
                        foreground = True
                        break
                    self.bring_to_front()
                    if hasattr(hwnd_window, "bring_to_front"):
                        hwnd_window.bring_to_front()
                if not foreground:
                    logger.debug(f"foreground key continuing without foreground confirmation: {key}")

            key_name = str(key).lower()
            sent = self._send_pydirect_key(key_name, down_time)
            if not sent:
                self._send_pynput_key(key_name, down_time)
            if after_sleep > 0:
                self.sleep(after_sleep)
            self.log_info(f"send foreground {key} key to open the panel")
            return True
        except Exception as e:
            logger.debug(f"send foreground key failed: {key} {e}")
            return False

    @staticmethod
    def _send_pydirect_key(key, down_time):
        try:
            import pydirectinput

            pydirectinput.FAILSAFE = False
            if hasattr(pydirectinput, "SendInput"):
                pydirectinput.SendInput.argtypes = [ctypes.c_uint, ctypes.c_void_p, ctypes.c_int]
            pydirectinput.keyDown(str(key))
            time.sleep(down_time)
            pydirectinput.keyUp(str(key))
            return True
        except Exception as e:
            logger.debug(f"pydirect foreground key failed: {key} {e}")
            return False

    @staticmethod
    def _send_pynput_key(key, down_time):
        from pynput import keyboard

        parsed_key = keyboard.Key.esc if key == "esc" else key
        controller = keyboard.Controller()
        controller.press(parsed_key)
        time.sleep(down_time)
        controller.release(parsed_key)
        return True

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
            texts = self.ocr(log=self.debug)
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

            if app_version := self.find_boxes(
                texts, match=re.compile(r"pp:[\d\.-]+", re.IGNORECASE)
            ):
                self.log_info(f"wait_login {app_version}")
                if not self.hwnd.is_foreground():
                    self.bring_to_front()
                    self.sleep(3)
                self.click(0.499, 0.865, after_sleep=3)
                return False

    def find_treasure(self):
        def mask(img):
            return iu.mask_corners(img, 0.5, 0.5, "all", to_bgr=False)
        return self.find_one(
            Labels.treasure, box=self.main_viewport, threshold=0.7, mask_function=mask,
            use_gray_scale=True
        )

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
        centered = centered or x_abs <= self.width_of_screen(threshold)

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
        boxes = self.wait_ocr(
            0.814, 0.029, 0.898, 0.083, raise_if_not_found=False, match=stamina_re
        )
        if not boxes:
            self.screenshot("stamina_error")
            return -1
        current = 0
        for box in boxes:
            if match := stamina_re.search(box.name):
                current = int(match.group(1))
        self.info_set("当前体力", current)
        return current


def interac_mask(image):
    mask = iu.create_color_mask(image, interac_pink_color, to_bgr=False)
    dilated_mask = iu.morphology_mask(mask, to_bgr=False)
    return dilated_mask


interac_pink_color = {
    "r": (197, 221),
    "g": (71, 78),
    "b": (119, 133),
}
