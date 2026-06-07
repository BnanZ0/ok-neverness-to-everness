import threading
import time
from dataclasses import dataclass
from functools import cache
from typing import TYPE_CHECKING, Optional

import cv2
import numpy as np
from ok import Box, Logger, find_color_rectangles

from src.Labels import Labels
from src.tasks.BaseNTETask import BaseNTETask
from src.utils import game_filters as gf
from src.utils import image_utils as iu

if TYPE_CHECKING:
    from src.char.BaseChar import BaseChar

logger = Logger.get_logger(__name__)


@dataclass
class CombatSettle:
    time: Optional[float] = None
    force: bool = False


class CombatCheck(BaseNTETask):
    # TARGET_MATCH_SCALES = (0.6, 0.7, 0.8, 0.9, 1.0)
    _LV_NORM_SIZE = 32
    _TARGET_MASK_REGIONS = [(0.020, 0.017, 0.145, 0.240)]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._in_animation = False
        self._in_combat = False
        self.skip_sleep_check = False
        self.sleep_check_interval = 0.2
        self.last_out_of_combat_time = 0
        self.out_of_combat_reason = ""
        self.target_enemy_time_out = 3
        self.switch_char_time_out = 5
        self.combat_end_condition = None
        self.target_enemy_error_notified = False
        self.cds = {}
        self.find_lv_future = None
        self._lv_async = None
        self._combat_settle = CombatSettle()
        self._combat_detect_miss_count = 0
        self.combat_detect_miss_required = 2
        self._target_template_cache_key = None
        self._target_match_templates = None
        self._bg_ocr_lock = threading.Lock()

    @property
    def in_animation(self):
        return self._in_animation

    @in_animation.setter
    def in_animation(self, value):
        self._in_animation = value
        if value:
            self._last_ultimate = time.time()

    def on_combat_check(self):
        return True

    def reset_to_false(self, reason=""):
        self.out_of_combat_reason = reason
        self.do_reset_to_false()
        return False

    def do_reset_to_false(self):
        self.cds = {}
        self._in_combat = False
        self._combat_settle = CombatSettle()
        self._combat_detect_miss_count = 0
        self.find_lv_future = None
        self._lv_async = None
        self.openvino_clear_cache()
        self.scene.set_not_in_combat()
        return False

    def get_current_char(self) -> "BaseChar":
        """
        获取当前角色。
        此方法必须由子类实现。
        """
        raise NotImplementedError("子类必须实现 get_current_char 方法")

    def load_chars(self) -> bool:
        """
        加载队伍中的角色信息。
        此方法必须由子类实现。
        """
        raise NotImplementedError("子类必须实现 load_chars 方法")

    def check_health_bar(self):
        return self.has_health_bar()

    def is_boss(self):
        def filter(image):
            return iu.binarize_bgr_by_brightness(image, threshold=180)

        box = self.box_of_screen(0.3582, 0.0215, 0.5000, 0.0569)
        is_boss = self.find_one(Labels.boss_lv_text, box=box, frame_processor=filter)
        return bool(is_boss)

    def target_enemy(self, wait=True, lv=True):
        if not wait:
            self.middle_click()
        else:
            logger.info(f"targeting enemy for {self.target_enemy_time_out}s")
            deadline = time.time() + self.target_enemy_time_out
            while time.time() < deadline:
                if self.combat_detect(lv=lv):
                    return True
                if self.is_in_team():
                    self.middle_click()
                    self.sleep(0.25)
                    self.next_frame()
                    if self.combat_detect(lv=lv):
                        return True
                self.next_frame()

    def has_health_bar(self):
        if self._find_red_health_bar():  # or self._find_boss_health_bar():
            return True
        return False

    def _find_red_health_bar(self, width=100):
        min_height = self.height_of_screen(4 / 1440)
        min_width = self.width_of_screen(width / 2560)
        # if self._in_combat:
        #     min_width = self.width_of_screen(100 / 2560)
        # else:
        #     min_width = self.width_of_screen(30 / 2560)
        max_height = min_height * 3
        max_width = self.width_of_screen(200 / 2560)

        # 还原原始的颜色过滤
        _frame = iu.filter_by_hsv(self.frame, enemy_health_hsv)
        boxes = find_color_rectangles(
            _frame,
            enemy_health_color_red,
            min_width,
            min_height,
            max_width,
            max_height,
            box=self.box_of_screen(0.0984, 0, 0.8961, 0.8944, name="health_bar"),
        )

        if len(boxes) > 0:
            self.draw_boxes("enemy_health_bar_red", boxes, color="blue")
            return True
        return False

    def _find_boss_health_bar(self):
        min_height = self.height_of_screen(9 / 2160)
        min_width = self.width_of_screen(100 / 3840)

        boxes = find_color_rectangles(
            self.frame,
            boss_health_color,
            min_width,
            min_height,
            box=self.box_of_screen(0.3277, 0.0507, 0.4980, 0.0701),
        )
        if len(boxes) == 1:
            self.draw_boxes("boss_health", boxes, color="blue")
            return True
        return False

    def in_combat(self, target=False):
        self.in_sleep_check = True
        try:
            return self.do_check_in_combat(target)
        except Exception as e:
            logger.error("do_check_in_combat", e)
        finally:
            self.in_sleep_check = False

    def do_check_in_combat(self, target):
        if self.in_animation:
            return True
        if self._in_combat:
            if self.get_current_char() is None:
                return self.reset_to_false(reason="current_char is None")
            if self.scene.in_combat() is not None:
                return self.scene.in_combat()
            if current_char := self.get_current_char():
                if current_char.skip_combat_check():
                    return self.scene.set_in_combat()
            if not self.on_combat_check():
                self.log_info("on_combat_check failed")
                return self.reset_to_false(reason="on_combat_check failed")
            if self.is_boss():
                return self.scene.set_in_combat()
            # else:
            #     frame = getattr(self, 'cache_frame', None)
            #     if frame is not None:
            #         cv2.imwrite(f"cache_frame_{int(time.time())}.png", frame)
            # if self.has_target():
            #     self.last_in_realm_not_combat = 0
            #     return self.scene.set_in_combat()
            if self.combat_end_condition is not None and self.combat_end_condition():
                return self.reset_to_false(reason="end condition reached")

            if self._combat_settle.time is not None:
                if self._combat_settle.force:
                    self.next_frame()
                combat_detect = self.async_combat_detect(
                    exhaustive=True, force=self._combat_settle.force
                )
                self._combat_settle.force = False
            else:
                combat_detect = self.async_combat_detect()

            if combat_detect is None:
                return self.scene.set_in_combat()
            elif combat_detect is True:
                self._combat_settle = CombatSettle()
                self._combat_detect_miss_count = 0
                return self.scene.set_in_combat()
            else:
                self._combat_detect_miss_count += 1
                if self._combat_detect_miss_count < self.combat_detect_miss_required:
                    return self.scene.set_in_combat()
                if self._combat_settle.time is None:
                    self._combat_settle.time = time.time() + 0.4
                if self._combat_settle.time > time.time():
                    if self.click(key="middle", action_name="retarget", interval=0.35):
                        self.openvino_clear_cache()

                        def delay_detect():
                            time.sleep(0.25)
                            self._combat_settle.force = True

                        self.thread_pool_executor.submit(delay_detect)
                    return self.scene.set_in_combat()

            if self.target_enemy(wait=True):
                self._combat_settle = CombatSettle()
                self._combat_detect_miss_count = 0
                self.find_lv_future = None
                self._lv_async = None
                self.openvino_clear_cache()
                logger.debug("retarget enemy succeeded")
                return self.scene.set_in_combat()
            if self.should_check_monthly_card() and self.handle_monthly_card():
                return self.scene.set_in_combat()
            logger.error("target_enemy failed, try recheck break out of combat")
            return self.reset_to_false(reason="target enemy failed")
        else:
            from src.tasks.trigger.AutoCombatTask import AutoCombatTask

            @cache
            def has_target():
                return self.openvino_detect_async(mask_regions=self._TARGET_MASK_REGIONS)

            @cache
            def has_lv():
                return bool(self.find_lv())

            @cache
            def has_health_bar():
                return self.has_health_bar()

            @cache
            def is_boss():
                return self.is_boss()

            # now = time.time()
            is_auto = self.config.get("自动目标") or not isinstance(self, AutoCombatTask)
            if target and not has_target():
                self.log_debug("try target")
                self.middle_click(after_sleep=0.1)

            in_combat = (is_boss() or has_lv() or has_health_bar()) and (is_auto or has_target())
            if in_combat:
                # self.log_info(f"enter combat cost1 {time.time() - now}")
                if is_boss():
                    self.middle_click()
                elif not has_target() and not self.target_enemy(wait=True, lv=False):
                    return False
                # self.log_info(f"enter combat cost2 {time.time() - now}")
                self._in_combat = self.load_chars()
                return self._in_combat

    def combat_detect(self, frame=None, target=True, lv=True):
        if lv and self.find_lv(frame=frame):
            return True
        if target and self.openvino_detect_sync(
            frame=frame, mask_regions=self._TARGET_MASK_REGIONS
        ):
            return True
        return False

    def find_lv_async(self, frame=None, force=False):
        ret = self._lv_async
        if force or self.find_lv_future is None:
            if self.find_lv_future is not None:
                self.find_lv_future.cancel()
            if frame is None:
                frame = self.frame
            self.find_lv_future = self.thread_pool_executor.submit(self.find_lv, frame=frame)

            def callback(f):
                if self.find_lv_future is not f:
                    return
                try:
                    self._lv_async = bool(f.result())
                except Exception:
                    self._lv_async = None

                if self.find_lv_future is f:
                    self.find_lv_future = None

            self.find_lv_future.add_done_callback(callback)
        return ret

    def async_combat_detect(self, target=True, lv=True, exhaustive=False, force=False):
        lv_ret = None
        target_ret = None
        frame = self.frame

        if lv:
            lv_ret = self.find_lv_async(frame=frame, force=force)
            if lv_ret:
                return True

        is_lv_false = not lv or lv_ret is False

        if target and (exhaustive or is_lv_false):
            target_ret = self.openvino_detect_async(
                frame=frame, force=force, mask_regions=self._TARGET_MASK_REGIONS
            )
            if target_ret:
                return True

        target_pending = target and (exhaustive or is_lv_false) and target_ret is None
        if lv_ret is None or target_pending:
            return None

        return False

    def find_lv(self, frame=None, threshold=0.7):
        if not self._init_lv_templates():
            return []

        if frame is None:
            frame = self.frame

        box = self.box_of_screen(0.1543, 0, 0.9070, 0.7, name="find_lv")
        self.draw_boxes(boxes=box, color="blue")
        roi = box.crop_frame(frame)
        binary = gf.isolate_lv_to_white(roi)

        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        scale = self.width / 2560.0
        min_area = (15 * scale) ** 2 * 0.8
        max_area = (20 * scale) ** 2 * 1.5

        L_candidates = []
        v_candidates = []

        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            area_bbox = w * h

            if not (min_area <= area_bbox <= max_area):
                continue

            # 提取实时特征
            solidity, cx, cy = self._extract_shape_fingerprint(cnt, x, y, w, h)
            aspect_ratio = w / float(h)

            # 匹配 L
            if (
                abs(solidity - self._lv_feat_L[0]) < 0.15
                and abs(cx - self._lv_feat_L[1]) < 0.15
                and abs(cy - self._lv_feat_L[2]) < 0.15
            ):
                iou = self._match_contour_iou(self._lv_norm_L, cnt, x, y, w, h)
                if (self._lv_aspect_L * 0.6 < aspect_ratio < self._lv_aspect_L * 1.5) and iou > 0.5:
                    area = cv2.countNonZero(binary[y : y + h, x : x + w])
                    L_candidates.append(
                        {"x": x, "y": y, "w": w, "h": h, "score": iou, "area": area}
                    )

            # 匹配 v
            elif (
                abs(solidity - self._lv_feat_v[0]) < 0.15
                and abs(cx - self._lv_feat_v[1]) < 0.15
                and abs(cy - self._lv_feat_v[2]) < 0.15
            ):
                iou = self._match_contour_iou(self._lv_norm_v, cnt, x, y, w, h)
                if (self._lv_aspect_v * 0.6 < aspect_ratio < self._lv_aspect_v * 1.5) and iou > 0.5:
                    area = cv2.countNonZero(binary[y : y + h, x : x + w])
                    v_candidates.append(
                        {"x": x, "y": y, "w": w, "h": h, "score": iou, "area": area}
                    )

        results: list[Box] = []
        for L in L_candidates:
            best_v = None
            min_gap = float("inf")

            for v in v_candidates:
                gap = v["x"] - (L["x"] + L["w"])
                y_diff = abs(v["y"] - L["y"])

                # 逻辑核心：v 在 L 的右侧，距离合理，且 Y 轴大致平齐
                if -(L["w"] * 0.5) <= gap <= (L["h"] * 1.5) and y_diff <= (L["h"] * 0.5):
                    if gap < min_gap:
                        min_gap = gap
                        best_v = v

            if best_v:
                conf = float((L["score"] + best_v["score"]) / 2.0)
                if conf < threshold:
                    continue
                box_x = L["x"]
                box_y = min(L["y"], best_v["y"])
                box_w = (best_v["x"] + best_v["w"]) - L["x"]
                box_h = max(L["y"] + L["h"], best_v["y"] + best_v["h"]) - box_y

                pair_crop = binary[box_y : box_y + box_h, box_x : box_x + box_w]
                pair_area = cv2.countNonZero(pair_crop)
                if pair_area <= 0 or (L["area"] + best_v["area"]) / pair_area < 0.82:
                    continue

                results.append(
                    Box(
                        x=int(box.x + box_x),
                        y=int(box.y + box_y),
                        width=int(box_w),
                        height=int(box_h),
                        confidence=conf,
                        name="lv",
                    )
                )
        if results:
            self.draw_boxes(Labels.lv, results, color="red")
            # self.screenshot("lv", frame, True)
        return results

    def _extract_shape_fingerprint(self, cnt, x, y, w, h):
        """提取形状的物理指纹：填充率和相对重心位置"""
        m = cv2.moments(cnt)
        if m["m00"] == 0:
            return 0.0, 0.5, 0.5
        solidity = cv2.contourArea(cnt) / float(w * h)
        cx = (m["m10"] / m["m00"] - x) / float(w)
        cy = (m["m01"] / m["m00"] - y) / float(h)
        return solidity, cx, cy

    def _render_contour_normalized(self, cnt, x, y, w, h):
        """将轮廓渲染到归一化尺寸的二值图上"""
        sz = self._LV_NORM_SIZE
        img = np.zeros((sz, sz), dtype=np.uint8)
        shifted = cnt.copy()
        shifted[:, :, 0] = ((cnt[:, :, 0] - x) * (sz - 1) / max(w - 1, 1)).astype(np.int32)
        shifted[:, :, 1] = ((cnt[:, :, 1] - y) * (sz - 1) / max(h - 1, 1)).astype(np.int32)
        cv2.drawContours(img, [shifted], -1, 255, cv2.FILLED)
        return img

    def _match_contour_iou(self, tpl_norm, cnt, x, y, w, h):
        """计算归一化二值图的 IoU 作为形状相似度"""
        cand = self._render_contour_normalized(cnt, x, y, w, h)
        intersection = cv2.countNonZero(cv2.bitwise_and(tpl_norm, cand))
        union = cv2.countNonZero(cv2.bitwise_or(tpl_norm, cand))
        return intersection / union if union > 0 else 0.0

    def _init_lv_templates(self):
        """初始化 LV 识别所需的模板特征数据"""
        # 如果已经初始化且分辨率没变，直接返回
        if hasattr(self, "_lv_feat_L") and getattr(self, "_lv_tpl_res", None) == (
            self.width,
            self.height,
        ):
            return True

        tpl_img = self.get_feature_by_name(Labels.lv).mat
        tpl_bin = gf.isolate_lv_to_white(tpl_img)

        contours, _ = cv2.findContours(tpl_bin, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        valid_cnts = [
            c for c in contours if cv2.boundingRect(c)[2] > 2 and cv2.boundingRect(c)[3] > 2
        ]
        valid_cnts.sort(key=lambda c: cv2.boundingRect(c)[0])

        if len(valid_cnts) < 2:
            self.log_error(f"[LV-Init] 模板切割失败，仅找到 {len(valid_cnts)} 个轮廓")
            return False

        # 提取 L 和 v 的标准指纹
        self._lv_tpl_res = (self.width, self.height)
        self._lv_cnt_L = valid_cnts[0]
        self._lv_cnt_v = valid_cnts[1]

        xl, yl, wl, hl = cv2.boundingRect(self._lv_cnt_L)
        self._lv_aspect_L = wl / float(hl)
        self._lv_feat_L = self._extract_shape_fingerprint(self._lv_cnt_L, xl, yl, wl, hl)
        self._lv_norm_L = self._render_contour_normalized(self._lv_cnt_L, xl, yl, wl, hl)

        xv, yv, wv, hv = cv2.boundingRect(self._lv_cnt_v)
        self._lv_aspect_v = wv / float(hv)
        self._lv_feat_v = self._extract_shape_fingerprint(self._lv_cnt_v, xv, yv, wv, hv)
        self._lv_norm_v = self._render_contour_normalized(self._lv_cnt_v, xv, yv, wv, hv)

        self.log_info("[LV-Init] 模板特征初始化完成")
        return True


enemy_health_hsv = iu.HSVRange((0, 190, 175), (179, 255, 255))

enemy_health_color_red = {
    "r": (210, 255),
    "g": (20, 80),
    "b": (20, 100),
}

boss_health_color = {
    "r": (215, 240),
    "g": (30, 60),
    "b": (50, 75),
}


def merge_images_vertically(img_list, bg_color=(255, 255, 255)):
    # 1. 找到所有图片中的最大宽度
    max_width = max(img.shape[1] for img in img_list)

    processed_imgs = []
    for img in img_list:
        _, w = img.shape[:2]
        if w < max_width:
            # 计算需要填充的宽度
            pad_width = max_width - w
            # 使用 cv2.copyMakeBorder 进行填充 (常数填充)
            # 这里的 bg_color 如果是灰度图传一个值(0)，如果是彩色传 (0,0,0)
            img = cv2.copyMakeBorder(img, 0, 0, 0, pad_width, cv2.BORDER_CONSTANT, value=bg_color)
        processed_imgs.append(img)

    # 2. 垂直合并
    return cv2.vconcat(processed_imgs)
