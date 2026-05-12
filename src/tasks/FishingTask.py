import time

import cv2
import numpy as np
from ok import Box, TaskDisabledException
from qfluentwidgets import FluentIcon

from src import text_white_color
from src.Labels import Labels
from src.tasks.BaseNTETask import BaseNTETask
from src.tasks.NTEOneTimeTask import NTEOneTimeTask
from src.utils import image_utils as iu


class FishingTask(NTEOneTimeTask, BaseNTETask):
    # --- 配置项键名 ---
    CONF_ROUNDS = "循环次数"
    CONF_CONTROL_MODE = "控条模式"
    CONF_TAP_MULTIPLIER = "点按时长倍率"
    CONF_USE_ESC = "使用ESC"
    CONF_AUTO_BUY_BAIT = "自动补饵卖鱼"

    # --- 配置选项值 ---
    MODE_HOLD = "长按"
    MODE_TAP = "点按"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "自动钓鱼"
        self.description = "自动完成一轮或多轮钓鱼"
        self.icon = FluentIcon.SYNC
        self.default_config.update(
            {
                self.CONF_ROUNDS: 1,
                self.CONF_CONTROL_MODE: self.MODE_HOLD,
                self.CONF_TAP_MULTIPLIER: 1.0,
                self.CONF_USE_ESC: False,
                self.CONF_AUTO_BUY_BAIT: True,
            }
        )
        self.config_description.update(
            {
                self.CONF_CONTROL_MODE: f"{self.MODE_HOLD}：平滑流畅, 易过冲\n"
                f"{self.MODE_TAP}: 安全较慢, 防过冲",
                self.CONF_TAP_MULTIPLIER: "点按模式专用。用于微调每次按键的持续时间",
                self.CONF_USE_ESC: "开启后优先通过 ESC 键关闭成功界面，避免后台抢占鼠标。\n"
                "若游戏运行不流畅，可能因按键响应延迟导致误退出钓鱼场景",
                self.CONF_AUTO_BUY_BAIT: "首次抛竿失败时，补充默认鱼饵并出售鱼获",
            }
        )
        self.config_type.update(
            {
                self.CONF_CONTROL_MODE: {
                    "type": "drop_down",
                    "options": [self.MODE_HOLD, self.MODE_TAP],
                },
            }
        )
        self._last_bar_log_time = 0.0
        self._morph_kernel = np.ones((3, 3), dtype=np.uint8)
        self._bar_active_key = None
        self._last_direction = None
        self._monthly_card_pause_time = 0.0
        self.sleep_check_interval = 1
        self.add_exit_after_config()

    def run(self):
        super().run()
        try:
            return self.do_run()
        except TaskDisabledException:
            pass
        except Exception as e:
            self.log_error("FishingTask error", e)
            raise

    def sleep_check(self):
        if self.should_check_monthly_card():
            start = time.time()
            if self.handle_monthly_card():
                self._monthly_card_pause_time += time.time() - start

    def do_run(self):
        self.reset_runtime_state()
        if not self.enter_fishing_scene():
            raise TaskDisabledException("进入失败或未在钓鱼场景")
        rounds = max(1, int(self.config.get(self.CONF_ROUNDS, 1)))
        self.log_info(f"开始自动钓鱼，共 {rounds} 轮")
        success_count = 0
        for index in range(rounds):
            self.log_info(f"开始第 {index + 1}/{rounds} 轮钓鱼")
            if self.run_once(index + 1):
                success_count += 1
            else:
                self.log_error(f"第 {index + 1} 轮钓鱼失败")
                # 失败后重置状态继续下一轮，避免“设置2轮只跑1轮”
                self.reset_runtime_state()
        self.info_set("Fishing Success Count", success_count)
        self.log_info(f"自动钓鱼结束，成功 {success_count}/{rounds}", notify=True)

    def run_once(self, round_index: int) -> bool:
        if not self.close_success_overlay():
            self.screenshot("close_success_overlay_timeout")
            raise TaskDisabledException("关闭成功界面失败")

        if not self.cast_rod():
            raise TaskDisabledException("未检测到进入抛竿状态")

        if not self.wait_bite():
            self.screenshot(f"fishing_bite_timeout_{round_index}")
            return False

        return self.control_until_finish()

    def enter_fishing_scene(self) -> bool:
        """检测并进入钓鱼准备界面"""
        ENTER_SCENE_TIMEOUT = 5
        if self.is_fish_start_exist() or self.is_success_overlay():
            self.log_info("已在钓鱼准备界面")
            return True

        if self.wait_until_pause_aware(
            self.find_interac,
            time_out=ENTER_SCENE_TIMEOUT,
        ):
            box = self.box_of_screen(0.9094, 0.8278, 0.9746, 0.9104)

            # 尝试通过 F 交互打开面板
            if not self.wait_until_pause_aware(
                lambda: self.find_one(Labels.skip_quest_confirm, box=box) is not None,
                pre_action=lambda: self.send_key(
                    "f",
                    interval=1.5,
                    action_name="enter_panel_f",
                ),
                time_out=ENTER_SCENE_TIMEOUT,
            ):
                self.log_error("未检测到钓鱼面板入口")
                return False

            self.operate_click(box)
            self.sleep(1.5)

        if not self.wait_until_pause_aware(
            self.is_fish_start_exist,
            time_out=ENTER_SCENE_TIMEOUT,
        ):
            self.log_error("进入钓鱼场景后未检测到可抛竿状态")
            return False

        self.log_info("成功进入钓鱼场景")
        return True

    def cast_rod(self) -> bool:
        """执行抛竿操作并等待进入等待状态"""
        self.log_info("执行抛竿操作")
        if self.wait_cast_rod(7.5):
            return True

        if not self.config.get(self.CONF_AUTO_BUY_BAIT, True):
            self.log_warning("首次抛竿超时，已关闭自动补饵卖鱼，结束任务")
            return self.cast_rod_failed()

        self.log_warning("首次抛竿超时，切换默认鱼饵后重试")
        if not self.change_to_default_bait():
            return self.cast_rod_failed()
        self.sell_fish()
        if self.wait_cast_rod(10):
            return True

        return self.cast_rod_failed()

    def cast_rod_failed(self) -> bool:
        self.send_key("f")
        frame = self.frame
        self.screenshot("fishing_cast_timeout", frame=frame)
        text = self.ocr(0.4090, 0.4778, 0.5914, 0.5188, frame=frame)
        self.log_error("未检测到进入抛竿状态", notify=True)
        if text:
            self.log_warning(f"检测到文字: {text}")
        return False

    def wait_cast_rod(self, time_out: float) -> bool:
        return bool(
            self.wait_until_pause_aware(
                self.is_cast_rod_done,
                pre_action=lambda: self.send_key(
                    "f",
                    interval=1.5,
                    action_name="cast_rod_f",
                ),
                post_action=lambda: self.close_success_overlay_once(
                    "抛竿时检测到成功面板, 尝试关闭"
                ),
                time_out=time_out,
            )
        )

    def is_cast_rod_done(self) -> bool:
        return (
            not self.is_success_overlay()
            and not self.is_fish_bait_exist()
            and self.is_fish_start_exist()
        )

    def wait_bite(self) -> bool:
        """等待鱼儿咬钩"""
        self.log_info("等待鱼儿咬钩")
        if self.wait_until_pause_aware(
            self.is_fishing_bite,
            time_out=20,
        ):
            self.log_info("鱼儿咬钩")
            if not self.wait_until_pause_aware(
                lambda: not self.is_fish_start_exist(),
                pre_action=lambda: self.send_key(
                    "f",
                    interval=2,
                    action_name="bite_f",
                ),
                time_out=10,
            ):
                self.log_error("未检测到进入溜鱼状态")
                return False
            self.log_info("进入溜鱼状态")
            return True
        else:
            self.log_error("等待鱼儿咬钩超时")
            return False

    def control_until_finish(self) -> bool:
        """实时检测拉力条状态并自动控条直到钓鱼结束"""
        start_check_time = time.time() + 1
        deadline = time.time() + 30
        failed_time = 0
        try:
            while time.time() < deadline:
                state = self.detect_fishing_bar_state()
                if self.is_valid_bar_state(state):
                    self.apply_bar_control(state)
                else:
                    self._clear_bar_key_if_hold_mode()

                if time.time() > start_check_time:
                    if self.is_fish_bait_exist():
                        if failed_time == 0:
                            failed_time = time.time()
                    else:
                        failed_time = 0

                    if failed_time != 0 and time.time() - failed_time > 5:
                        self.log_error("疑似脱钩或失败")
                        return False

                    if self.is_success_overlay():
                        return True

                self.sleep(0.01)
                pause_time = self.consume_monthly_card_pause_time()
                if pause_time > 0:
                    deadline += pause_time
                    start_check_time += pause_time
                    if failed_time != 0:
                        failed_time += pause_time
            self.log_error("控条阶段超时")
            return False
        finally:
            self._clear_bar_key_if_hold_mode()

    def apply_bar_control(self, state: dict):
        mode = self.config.get(self.CONF_CONTROL_MODE, self.MODE_HOLD)
        if mode == self.MODE_TAP:
            self.apply_bar_control_discrete(state)
        else:
            self.apply_bar_control_hold(state)

    def apply_bar_control_hold(self, state: dict):
        """长按模式 (默认)"""
        now = time.time()
        pointer, zone_center, zone_width = self._bar_metrics(state)
        error = pointer - zone_center
        abs_error = abs(error)

        deadzone = max(2, int(zone_width * 0.08))

        if abs_error <= deadzone:
            self._set_bar_key(None)
            if now - self._last_bar_log_time > 1:
                self.log_debug(f"指针已锁定中心: pointer={pointer}, target={zone_center}")
                self._last_bar_log_time = now
            return

        key = "d" if error < 0 else "a"
        self._set_bar_key(key)

    def apply_bar_control_discrete(self, state: dict):
        """点按模式"""
        now = time.time()
        pointer, zone_center, zone_width = self._bar_metrics(state)
        dist_from_center = pointer - zone_center
        abs_dist = abs(dist_from_center)

        if abs_dist <= max(2, int(zone_width * 0.08)):
            if now - self._last_bar_log_time > 0.5:
                self.log_debug(f"指针已锁定中心: pointer={pointer}, target={zone_center}")
                self._last_bar_log_time = now
            return

        key = "d" if dist_from_center < 0 else "a"
        ratio = min(1.0, abs_dist / (zone_width / 2))
        curve = ratio * ratio * (3 - 2 * ratio)
        hold = 0.01 + curve * 0.18

        # 方向变化削弱
        if key != self._last_direction:
            hold *= 0.6

        self._last_direction = key

        # 倍率
        multiplier = float(self.config.get(self.CONF_TAP_MULTIPLIER, 1.0))
        hold *= multiplier

        # 限制
        hold = min(0.2, max(0.01, hold))

        self.send_key(key, down_time=hold)

    def _set_bar_key(self, key):
        if key == self._bar_active_key:
            return

        if self._bar_active_key is not None:
            self.send_key_up(self._bar_active_key)
            self._bar_active_key = None

        if key is not None:
            self.send_key_down(key)
            self._bar_active_key = key

    def _clear_bar_key_if_hold_mode(self):
        if self.config.get(self.CONF_CONTROL_MODE, self.MODE_HOLD) == self.MODE_HOLD:
            self._set_bar_key(None)

    def _bar_metrics(self, state: dict):
        return (
            int(state["pointer_center"]),
            int(state["zone_center"]),
            max(1, int(state["zone_width"])),
        )

    def is_valid_bar_state(self, state) -> bool:
        if state is None:
            return False
        zone_left = int(state.get("zone_left", 0))
        zone_right = int(state.get("zone_right", 0))
        pointer_center = int(state.get("pointer_center", -1))
        image_width = max(1, int(state.get("image_width", 1)))
        zone_width = max(0, int(state.get("zone_width", zone_right - zone_left)))
        ratio = zone_width / image_width
        if not (0.05 <= ratio <= 0.55):
            return False
        if not (0 <= pointer_center < image_width):
            return False
        # 过滤明显误检：绿区贴边且指针又远离，通常不是有效拉力条
        edge_zone = zone_left <= 1 or zone_right >= image_width - 2
        if edge_zone and abs(pointer_center - int((zone_left + zone_right) / 2)) > int(
            image_width * 0.38
        ):
            return False
        return True

    def is_success_overlay(self) -> bool:
        return self.find_one(Labels.fising_sucess)

    def close_success_overlay(self):
        if self.is_success_overlay():
            self.log_info("检测到成功面板，尝试关闭")
        elif self.is_fish_start_exist():
            self.log_info("已在可抛竿状态")
            return True

        if self.wait_until_pause_aware(
            lambda: not self.is_success_overlay(),
            pre_action=self.close_success_overlay_once,
            time_out=20,
        ):
            self.log_info("关闭成功面板")
        else:
            self.log_error("关闭成功面板超时")
            return False
        if self.wait_until_pause_aware(self.is_fish_start_exist, time_out=5):
            self.log_info("进入可抛竿状态")
            self.sleep(0.5)
        else:
            self.log_error("未进入可抛竿状态")
            return False
        return True

    def close_success_overlay_once(self, log_message=None):
        if not self.is_success_overlay():
            return False
        closed = self.do_close_success_overlay()
        if not closed:
            return False
        if log_message:
            self.log_info(log_message)
        return True

    def do_close_success_overlay(self):
        """执行关闭成功面板的具体操作"""
        if self.config.get(self.CONF_USE_ESC):
            return self.send_key(
                "esc",
                interval=2,
                action_name="close_success_overlay",
            )
        return self.operate_click(
            0.12,
            0.88,
            interval=2,
            action_name="close_success_overlay",
        )

    def sleep_briefly(self):
        self.sleep(0.1)

    def wait_until_pause_aware(
        self,
        condition,
        time_out=5,
        pre_action=None,
        post_action=None,
    ):
        deadline = time.time() + time_out
        while True:
            if pre_action is not None:
                pre_action()
            result = condition()
            if result:
                return result
            if post_action is not None:
                post_action()
            self.sleep_briefly()
            deadline += self.consume_monthly_card_pause_time()
            if time.time() > deadline:
                return None

    def consume_monthly_card_pause_time(self) -> float:
        pause_time = self._monthly_card_pause_time
        self._monthly_card_pause_time = 0.0
        return pause_time

    def reset_runtime_state(self):
        self._set_bar_key(None)
        self._last_bar_log_time = 0.0
        self._last_direction = None
        self._bar_active_key = None
        self._monthly_card_pause_time = 0.0

    def detect_fishing_bar_state(self):
        """通过色值检测当前拉力条和指针的位置状态"""
        box = self.box_of_screen(0.3164, 0.0646, 0.6875, 0.0743, name="fishing_bar")
        image = box.crop_frame(self.frame)
        if image is None or image.size == 0:
            return None

        green_mask = iu.filter_by_hsv(
            image, iu.HSVRange((50, 150, 160), (160, 220, 255)), return_mask=True
        )
        yellow_mask = iu.filter_by_hsv(
            image, iu.HSVRange((20, 60, 195), (55, 200, 255)), return_mask=True
        )

        green_mask = cv2.morphologyEx(green_mask, cv2.MORPH_OPEN, self._morph_kernel)
        green_mask = cv2.morphologyEx(green_mask, cv2.MORPH_CLOSE, self._morph_kernel)
        yellow_mask = cv2.morphologyEx(yellow_mask, cv2.MORPH_OPEN, self._morph_kernel)
        yellow_mask = cv2.morphologyEx(yellow_mask, cv2.MORPH_CLOSE, self._morph_kernel)

        yellow_contours, _ = cv2.findContours(
            yellow_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        if yellow_contours:
            yellow_max_contour = max(yellow_contours, key=cv2.contourArea)
            px, _, pw, _ = cv2.boundingRect(yellow_max_contour)
            pointer_center = px + pw // 2
        else:
            pointer_center = -1

        green_contours, _ = cv2.findContours(green_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        green_candidates = []
        for contour in green_contours:
            x, y, w, h = cv2.boundingRect(contour)
            if w >= 5 and h >= 5:
                area = w * h
                green_candidates.append((x, y, w, h, area))

        if not green_candidates:
            return None

        green_candidates.sort(key=lambda item: item[4], reverse=True)

        top_2_candidates = green_candidates[:2]

        top_2_candidates.sort(key=lambda item: item[0])

        if len(top_2_candidates) == 1:
            zone_left = top_2_candidates[0][0]
            zone_right = top_2_candidates[0][0] + top_2_candidates[0][2]
        else:
            zone_left = top_2_candidates[0][0]
            zone_right = max(
                top_2_candidates[0][0] + top_2_candidates[0][2],
                top_2_candidates[1][0] + top_2_candidates[1][2],
            )
        zone_w = zone_right - zone_left

        return {
            "zone_left": zone_left,
            "zone_right": zone_right,
            "zone_center": zone_left + zone_w // 2,
            "zone_width": zone_w,
            "image_width": int(image.shape[1]),
            "pointer_center": pointer_center,
            "in_zone": zone_left <= pointer_center <= zone_right,
        }

    def is_fish_start_exist(self):
        """
        检测开始钓鱼按钮是否存在
        """
        def frame_process(img):
            return iu.create_color_mask(img, text_white_color)
        return self.find_one(Labels.fish_start, frame_processor=frame_process)

    # def is_success_text_exist(self):
    #     """检测界面是否出现“成功”字样（通过黑白像素占比判断）"""
    #     box = self.box_of_screen(0.4434, 0.8938, 0.5566, 0.9181, name="success_text")
    #     white_text = self.calculate_color_percentage(text_white_color, box)
    #     black_border = self.calculate_color_percentage(text_black_color, box)
    #     # self.log_debug(f"white_text: {white_text}, black_border: {black_border}")
    #     return white_text > 0.2 and black_border > 0.2

    def is_fish_bait_exist(self):
        """
        检测鱼饵是否存在
        """
        return self.find_one(Labels.fish_bait)

    def is_fishing_bite(self):
        """检测右下角鱼儿咬钩指示器中心圆外区域（蓝色像素占比判断）"""
        box = self.box_of_screen(0.9023, 0.8562, 0.9488, 0.9403, name="fishing_bite_indicator")
        image = box.crop_frame(self.frame)

        blue_mask = iu.create_color_mask(image, fishing_bite_blue_color, to_bgr=False)

        h, w = blue_mask.shape[:2]
        center = (w // 2, h // 2)
        max_radius = min(h, w) // 2
        target_radius = int(max_radius * 0.7)

        circle_mask = np.ones((h, w), dtype="uint8")
        cv2.circle(circle_mask, center, target_radius, 0, -1)

        masked_blue = cv2.bitwise_and(blue_mask, circle_mask)

        blue_pixels = int(cv2.countNonZero(masked_blue))

        total_circle_pixels = int(cv2.countNonZero(circle_mask))

        if total_circle_pixels == 0:
            return 0.0

        blue_pixels_ratio = blue_pixels / total_circle_pixels

        return blue_pixels_ratio > 0.07

    def find_default_bait(self):
        box = self.box_of_screen(0.0602, 0.2306, 0.313, 0.2597)
        image = box.crop_frame(self.frame)
        mask = iu.create_color_mask(image, default_bait_color, to_bgr=False)
        mask = iu.morphology_mask(mask, closing=True, to_bgr=False)
        num_labels, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        if num_labels <= 1:
            return None
        max_i = max(enumerate(stats[1:, cv2.CC_STAT_AREA]), key=lambda x: x[1])[0] + 1
        x = stats[max_i, cv2.CC_STAT_LEFT]
        y = stats[max_i, cv2.CC_STAT_TOP]
        w = stats[max_i, cv2.CC_STAT_WIDTH]
        h = stats[max_i, cv2.CC_STAT_HEIGHT]
        return Box(box.x + x, box.y + y, w, h, name="default_bait")

    def click_default_bait(self):
        box = self.find_default_bait()
        if box:
            self.operate_click(box)
            return
        self.operate_click(0.0758, 0.2236)

    def sell_fish(self):
        self.send_key("q")  # 背包
        self.sleep(1)
        self.operate_click(0.076, 0.386)  # 点击鱼仓
        self.sleep(1)
        self.operate_click(0.556, 0.898)  # 一键出售
        self.sleep(1)
        self.operate_click(0.609, 0.656)  # 确认出售
        self.sleep(2)
        self.back_to_fishing_scene()

    def buy_bait(self):
        self.click_default_bait()
        self.sleep(0.25)
        self.operate_click(0.9520, 0.8812)  # 拉满数量
        self.sleep(0.25)
        self.operate_click(0.8715, 0.9542)  # 购买
        self.sleep(1)
        self.operate_click(0.609, 0.661)  # 确认购买
        self.sleep(2)
        self.back_to_fishing_scene()

    def back_to_fishing_scene(self):
        self.wait_until_pause_aware(
            self.is_fish_start_exist,
            post_action=lambda: self.send_key(
                "esc", action_name="back_to_fishing_scene", interval=2
            ),
            time_out=10,
        )

    def change_to_default_bait(self):
        def choose_bait():
            self.send_key("e")
            self.sleep(2)
            self.operate_click(0.613, 0.655)
            self.sleep(1)
            self.operate_click(0.613, 0.655)

        choose_bait()
        if self.wait_until_pause_aware(
            self.is_fish_start_exist,
            time_out=2,
        ):
            return True
        self.buy_bait()
        choose_bait()
        return bool(
            self.wait_until_pause_aware(
                self.is_fish_start_exist,
                time_out=2,
            )
        )

    def handle_monthly_card(self):
        monthly_card = self.find_monthly_card()
        # self.screenshot('monthly_card1')
        if monthly_card is not None:
            self._clear_bar_key_if_hold_mode()
            # self.screenshot('monthly_card1')
            self.log_info("monthly_card found click")
            self.click(0.50, 0.89)
            self.sleep(2)
            # self.screenshot('monthly_card2')
            self.click(0.50, 0.89)
            self.sleep(2)
            # self.screenshot('monthly_card3')
            if self.find_monthly_card() is None:
                self.set_check_monthly_card(next_day=True)
            else:
                self.log_warning("monthly_card close failed")
        # logger.debug(f'check_monthly_card {monthly_card}')
        return monthly_card is not None


fishing_bite_blue_color = {
    "r": (30, 35),
    "g": (120, 130),
    "b": (250, 255),
}

# text_white_color = {
#     "r": (210, 255),
#     "g": (210, 255),
#     "b": (210, 255),
# }

text_black_color = {
    "r": (0, 10),
    "g": (0, 10),
    "b": (0, 10),
}

default_bait_color = {
    "r": (140, 255),
    "g": (40, 140),
    "b": (100, 190),
}
