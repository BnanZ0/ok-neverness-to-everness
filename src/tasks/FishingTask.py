import time
from enum import Enum

import cv2
import numpy as np
from ok import TaskDisabledException, WaitFailedException
from qfluentwidgets import FluentIcon

from src import text_white_color
from src.Labels import Labels
from src.tasks.BaseNTETask import BaseNTETask
from src.tasks.NTEOneTimeTask import NTEOneTimeTask
from src.utils import image_utils as iu


class RestockState(Enum):
    BUY_BAIT = "buy bait"
    SELL_FISH = "sell fish"


class FishingTask(NTEOneTimeTask, BaseNTETask):
    CONF_ROUNDS = "循环次数"
    CONF_CONTROL_MODE = "控条模式"
    CONF_TAP_MULTIPLIER = "点按时长倍率"
    CONF_AUTO_BUY_BAIT = "自动补饵卖鱼"

    MODE_HOLD = "长按"
    MODE_TAP = "点按"

    ENTER_SCENE_TIMEOUT = 5
    MACHINE_TIMEOUT = 20
    ENTER_CONTROL_TIMEOUT = 10
    CONTROL_TIMEOUT = 30
    RESTOCK_RETRY_LIMIT = 3
    FISHING_RETRY_LIMIT = 3
    STALLED_BAIT_SECONDS = 5

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
                self.CONF_AUTO_BUY_BAIT: True,
            }
        )
        self.config_description.update(
            {
                self.CONF_CONTROL_MODE: f"{self.MODE_HOLD}：平滑流畅, 易过冲\n"
                f"{self.MODE_TAP}: 安全较慢, 防过冲",
                self.CONF_TAP_MULTIPLIER: "点按模式专用。用于微调每次按键的持续时间",
                self.CONF_AUTO_BUY_BAIT: "抛竿失败时，补充默认鱼饵并出售鱼获后重试",
            }
        )
        self.config_type.update(
            {
                self.CONF_CONTROL_MODE: {
                    "type": "drop_down",
                    "options": [self.MODE_HOLD, self.MODE_TAP],
                    "sub_configs": {
                        self.MODE_TAP: self.CONF_TAP_MULTIPLIER,
                    },
                },
            }
        )
        self._morph_kernel = np.ones((3, 3), dtype=np.uint8)
        self._last_bar_log_time = 0.0
        self._last_direction = None
        self._bar_active_key = None
        self.add_exit_after_config()

    def run(self):
        super().run()
        try:
            return self.do_run()
        except TaskDisabledException:
            raise
        except Exception as e:
            self.screenshot("fishing_unexpected_exception")
            self.log_error("FishingTask error", e)
            raise

    def do_run(self):
        self.reset_runtime_state()
        self._publish_config_info()
        self.ensure_fishing_scene()
        self.run_fishing_state_machine()

    def monthly_card_check(self):
        if self.should_check_monthly_card():
            self._set_stage("check monthly card")
            if self.handle_monthly_card():
                return True

    def run_fishing_state_machine(self):
        target_rounds = self._configured_rounds()
        round_index = 1
        success_count = 0
        failed_count = 0
        pending_success_round = None
        retry_count = 0
        try_cast_count = 0
        machine_start = None
        self.log_info(f"开始自动钓鱼，共 {target_rounds} 轮")

        while success_count + failed_count < target_rounds:
            round_text = f"{round_index}/{target_rounds}"
            if self.info_get("轮次") != round_text:
                self.info_set("轮次", round_text)
                self.info_set("成功次数", success_count)
                self.info_set("失败次数", failed_count)

            try:
                self.next_frame()

                if self.has_success_overlay():
                    self._set_stage("is success")
                    machine_start = None
                    if pending_success_round is not None:
                        self.log_info(f"第 {pending_success_round} 轮钓鱼成功")
                        success_count += 1
                        pending_success_round = None
                        round_index += 1
                    self.ensure_fishing_scene()
                    retry_count = 0
                    continue

                if self.monthly_card_check():
                    retry_count = 0
                    continue

                if self.is_fish_biting():
                    self._set_stage("is bite")
                    machine_start = None
                    if pending_success_round is not None:
                        failed_count += 1
                        self.info_set("失败原因", "下一轮咬钩前未检测到成功面板")
                        self.log_error(f"第 {pending_success_round} 轮钓鱼失败：未检测到成功面板")
                        pending_success_round = None
                        round_index += 1
                        if success_count + failed_count >= target_rounds:
                            continue

                    self.log_info("鱼儿咬钩")
                    self.enter_control_bar()
                    retry_count = 0
                    continue

                if self.is_playing_fish():
                    self._set_stage("control bar")
                    machine_start = None
                    self.control_until_finish()
                    pending_success_round = round_index
                    try_cast_count = 0
                    retry_count = 0
                    continue

                if self.is_ready_to_cast():
                    machine_start = None
                    if try_cast_count >= 4:
                        if not self.config.get(self.CONF_AUTO_BUY_BAIT, True):
                            self.capture_cast_failure_info()
                            self.log_warning("未检测到进入抛竿状态")
                            raise WaitFailedException()
                        self.log_warning("未检测到可用鱼饵，开始买饵补货")
                        self.run_restock_state_machine()
                        try_cast_count = 0
                        retry_count = 0

                if self.is_ready_to_cast():
                    self._set_stage("cast rod")
                    if self.send_key("f", interval=2, action_name="cast_rod_f"):
                        try_cast_count += 1

                if machine_start is None:
                    machine_start = time.time()
                elif time.time() - machine_start > self.MACHINE_TIMEOUT:
                    if self.is_waiting_bite():
                        self.log_warning("等待鱼儿咬钩超时")
                    else:
                        self.log_warning("状态机运行超时")
                    raise WaitFailedException()

                self.sleep(0.1)
            except WaitFailedException:
                retry_count += 1
                if retry_count > self.FISHING_RETRY_LIMIT:
                    failed_count += 1
                    self.info_set("失败原因", "状态轮询连续失败")
                    self.screenshot(f"fishing_round_failed_{round_index}")
                    self.log_error(f"第 {round_index} 轮钓鱼失败：状态轮询连续失败")
                    round_index += 1
                    retry_count = 0
                    try_cast_count = 0
                    machine_start = None
                else:
                    self.info_set("失败原因", "钓鱼状态轮询失败")
                self.ensure_fishing_scene("钓鱼")

        self.info_set("当前阶段", "任务结束")
        self.info_set("成功次数", success_count)
        self.info_set("失败次数", failed_count)
        self.log_info(
            f"自动钓鱼结束，成功 {success_count}/{target_rounds}",
            notify=True,
        )

    def enter_control_bar(self):
        self._set_stage("control bar")
        self.wait_until(
            lambda: not self.has_fish_start(),
            pre_action=lambda: self.send_key("f", interval=2, action_name="bite_f"),
            time_out=self.ENTER_CONTROL_TIMEOUT,
            raise_if_not_found=True,
        )
        self.log_info("进入溜鱼状态")

    def control_until_finish(self):
        start_check_time = time.time() + 1
        deadline = time.time() + self.CONTROL_TIMEOUT
        bait_visible_since = 0
        try:
            while time.time() < deadline:
                state = self.detect_fishing_bar_state()
                if self.is_valid_bar_state(state):
                    self.apply_bar_control(state)
                else:
                    self._clear_bar_key_if_hold_mode()

                if time.time() > start_check_time:
                    self.monthly_card_check()
                    if self.has_success_overlay():
                        return
                    if self.has_fish_start():
                        if bait_visible_since == 0:
                            bait_visible_since = time.time()
                        elif time.time() - bait_visible_since > self.STALLED_BAIT_SECONDS:
                            return
                    else:
                        bait_visible_since = 0

                self.sleep(0.01)
                if time.time() > deadline:
                    self.log_warning("溜鱼状态超时")
                    raise WaitFailedException()
        finally:
            self._clear_bar_key_if_hold_mode()

    def run_restock_state_machine(self):
        state_order = [RestockState.BUY_BAIT, RestockState.SELL_FISH]
        retry_by_state = {state: 0 for state in state_order}
        state_index = 0

        while state_index < len(state_order):
            state = state_order[state_index]
            self._set_stage(state.value)
            try:
                if state is RestockState.BUY_BAIT:
                    self.buy_bait()
                elif state is RestockState.SELL_FISH:
                    self.sell_fish()
                state_index += 1
            except WaitFailedException:
                retry_by_state[state] += 1
                self.ensure_fishing_scene("买饵补货")
                if retry_by_state[state] > self.RESTOCK_RETRY_LIMIT:
                    raise

    def buy_bait(self):
        self.wait_click_confirm(lambda: self.send_key("e", interval=2))
        interface = self.wait_strict(self.current_bait_interface, time_out=10)
        if interface == "fish_start":
            self.log_info("默认鱼饵可用")
            return
        if interface is None:
            self.log_warning("未进入购买鱼饵页面")
            raise WaitFailedException()

        self.wait_strict(
            lambda: self.find_one(Labels.default_fish_bait_big),
            pre_action=self.click_default_bait,
            time_out=10,
        )

        def buy_action():
            self.operate_click(0.9520, 0.8812)
            self.sleep(1)
            self.operate_click(0.8715, 0.9542)
            self.sleep(1)

        self.wait_click_confirm(buy_action)
        self.ensure_fishing_scene()
        self.wait_click_confirm(lambda: self.send_key("e", interval=2))

    def sell_fish(self):
        self.wait_strict(
            lambda: self.find_one(Labels.fish_sell),
            pre_action=lambda: self.send_key("q", interval=2),
            time_out=10,
        )
        self.wait_strict(
            lambda: self.find_one(Labels.fish_hold),
            pre_action=lambda: self.operate_click(
                0.076,
                0.386,
                interval=2,
            ),
            time_out=10,
        )

        if self.find_one(Labels.fish_one_click_sell):
            if not self.wait_click_confirm(
                lambda: self.operate_click(0.556, 0.898, interval=2), raise_if_not_found=False
            ):
                self.log_info("一键出售未完成，可能当前鱼获不可出售，跳过出售")
        else:
            self.log_info("鱼舱内没有可出售鱼获，跳过出售")
        self.ensure_fishing_scene()

    def ensure_fishing_scene(self, workflow_name: str | None = None):
        self._clear_bar_key_if_hold_mode()
        if workflow_name:
            self.screenshot(f"fishing_{workflow_name}_wait_failed")
            self.log_warning(f"[{workflow_name}]流程等待超时，执行恢复操作")

        self._set_stage("恢复钓鱼界面")
        deadline = time.time() + 60
        while True:
            self.next_frame()
            if self.is_ready_to_cast():
                self.log_info("已回到钓鱼准备界面")
                return

            self.monthly_card_check()

            if self.is_in_team():
                break

            self.send_key("esc", interval=2, action_name="recover_fishing_scene")
            self.sleep(0.1)
            if time.time() > deadline:
                self.log_warning("恢复钓鱼准备界面超时")
                raise WaitFailedException()

        if self.has_fish_start():
            self.log_info("已回到钓鱼准备界面")
            return

        self.enter_fishing_from_interac()

        self._set_stage("等待钓鱼准备界面")
        self.wait_strict(self.has_fish_start, time_out=self.ENTER_SCENE_TIMEOUT)
        self.log_info("成功进入钓鱼场景")

    def enter_fishing_from_interac(self):
        self._set_stage("寻找钓鱼交互点")
        self.wait_strict(self.find_interac, time_out=self.ENTER_SCENE_TIMEOUT)

        box = self.box_of_screen(0.927, 0.827, 0.975, 0.912)
        btn = self.wait_strict(
            lambda: self.find_one(Labels.skip_quest_confirm, box=box),
            post_action=lambda: self.send_key("f", interval=2),
        )

        def action():
            box = self.box_of_screen(0.656, 0.618, 0.700, 0.699)
            if btn := self.find_one(Labels.skip_quest_confirm, box=box):
                self.operate_click(btn, action_name="extra_confirm", interval=2)

        self.wait_strict(
            self.has_fish_start,
            pre_action=lambda: self.operate_click(btn, action_name="start_fish", interval=2),
            post_action=action,
            time_out=30,
        )

    def current_bait_interface(self):
        if self.has_fish_start():
            return "fish_start"
        if self.find_one(Labels.fish_shop):
            return "fish_shop"
        return None

    def find_default_bait(self):
        box = self.box_of_screen(0.025, 0.118, 0.344, 0.516)
        return self.find_one(Labels.default_fish_bait, box=box, threshold=0.8)

    def click_default_bait(self):
        box = self.find_default_bait()
        if box:
            self.operate_click(box, interval=1)
            return True
        return False

    def wait_click_confirm(self, action, range=None, raise_if_not_found=True):
        if range is None:
            range=(0.641, 0.610, 0.713, 0.698)
        return super().wait_click_confirm(
            action=action, range=range, raise_if_not_found=raise_if_not_found
        )

    def wait_strict(
        self,
        condition,
        time_out=0,
        pre_action=None,
        post_action=None,
    ):
        return self.wait_until(
            condition,
            time_out=time_out,
            pre_action=pre_action,
            post_action=post_action,
            settle_time=1,
            raise_if_not_found=True,
        )

    def capture_cast_failure_info(self):
        self.send_key("f")
        text = self.ocr(0.4090, 0.4778, 0.5914, 0.5188, frame=self.frame)
        self.log_error("未检测到进入抛竿状态", notify=True)
        if text:
            self.log_warning(f"检测到文字: {text}")

    def apply_bar_control(self, state: dict):
        mode = self.config.get(self.CONF_CONTROL_MODE, self.MODE_HOLD)
        if mode == self.MODE_TAP:
            self.apply_bar_control_discrete(state)
        else:
            self.apply_bar_control_hold(state)

    def apply_bar_control_hold(self, state: dict):
        now = time.time()
        pointer_center, pointer_width, zone_center, zone_width = self._bar_metrics(state)
        error = pointer_center - zone_center
        abs_error = abs(error)
        deadzone = max(2, int(pointer_width * 3))

        if abs_error <= deadzone:
            self._set_bar_key(None)
            if now - self._last_bar_log_time > 1:
                self.log_debug(f"指针已锁定中心: pointer={pointer_center}, target={zone_center}")
                self._last_bar_log_time = now
            return

        key = "d" if error < 0 else "a"
        self._set_bar_key(key)

    def apply_bar_control_discrete(self, state: dict):
        now = time.time()
        pointer_center, _, zone_center, zone_width = self._bar_metrics(state)
        dist_from_center = pointer_center - zone_center
        abs_dist = abs(dist_from_center)

        if abs_dist <= max(2, int(zone_width * 0.08)):
            if now - self._last_bar_log_time > 0.5:
                self.log_debug(f"指针已锁定中心: pointer={pointer_center}, target={zone_center}")
                self._last_bar_log_time = now
            return

        key = "d" if dist_from_center < 0 else "a"
        ratio = min(1.0, abs_dist / (zone_width / 2))
        curve = ratio * ratio * (3 - 2 * ratio)
        hold = 0.01 + curve * 0.18

        if key != self._last_direction:
            hold *= 0.6
        self._last_direction = key

        multiplier = float(self.config.get(self.CONF_TAP_MULTIPLIER, 1.0))
        hold = min(0.2, max(0.01, hold * multiplier))
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
            max(1, int(state["pointer_width"])),
            int(state["zone_center"]),
            max(1, int(state["zone_width"])),
        )

    def is_valid_bar_state(self, state):
        if state is None:
            return False
        zone_left = int(state.get("zone_left", 0))
        zone_right = int(state.get("zone_right", 0))
        pointer_center = int(state.get("pointer_center", -1))
        pointer_width = int(state.get("pointer_width", -1))
        image_width = max(1, int(state.get("image_width", 1)))
        zone_width = max(0, int(state.get("zone_width", zone_right - zone_left)))
        ratio = zone_width / image_width
        if not (0.05 <= ratio <= 0.55):
            return False
        if not (0 <= pointer_center < image_width):
            return False
        if pointer_width < 0:
            return False

        edge_zone = zone_left <= 1 or zone_right >= image_width - 2
        if edge_zone and abs(pointer_center - int((zone_left + zone_right) / 2)) > int(
            image_width * 0.38
        ):
            return False
        return True

    def detect_fishing_bar_state(self):
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

        pointer_center, pointer_width = self._detect_pointer_center(yellow_mask)
        zone = self._detect_control_zone(green_mask)
        if zone is None:
            return None

        zone_left, zone_right = zone
        zone_width = zone_right - zone_left
        return {
            "zone_left": zone_left,
            "zone_right": zone_right,
            "zone_center": zone_left + zone_width // 2,
            "zone_width": zone_width,
            "image_width": int(image.shape[1]),
            "pointer_center": pointer_center,
            "pointer_width": pointer_width,
            "in_zone": zone_left <= pointer_center <= zone_right,
        }

    def _detect_pointer_center(self, yellow_mask):
        yellow_contours, _ = cv2.findContours(
            yellow_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        if not yellow_contours:
            return -1, -1
        yellow_max_contour = max(yellow_contours, key=cv2.contourArea)
        px, _, pw, _ = cv2.boundingRect(yellow_max_contour)
        return px + pw // 2, pw

    @staticmethod
    def _detect_control_zone(green_mask):
        green_contours, _ = cv2.findContours(green_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        candidates = []
        for contour in green_contours:
            x, y, w, h = cv2.boundingRect(contour)
            if w >= 5 and h >= 5:
                candidates.append((x, y, w, h, w * h))
        if not candidates:
            return None

        candidates.sort(key=lambda item: item[4], reverse=True)
        top_candidates = sorted(candidates[:2], key=lambda item: item[0])

        zone_left = top_candidates[0][0]
        if len(top_candidates) == 1:
            zone_right = top_candidates[0][0] + top_candidates[0][2]
        else:
            zone_right = max(
                top_candidates[0][0] + top_candidates[0][2],
                top_candidates[1][0] + top_candidates[1][2],
            )
        return zone_left, zone_right

    def is_playing_fish(self):
        cond1 = not self.has_fish_bait() and not self.has_fish_start()
        cond2 = self.is_valid_bar_state(self.detect_fishing_bar_state())
        return cond1 and cond2

    def is_ready_to_cast(self):
        return self.has_fish_bait() and self.has_fish_start()

    def is_waiting_bite(self):
        return not self.has_fish_bait() and self.has_fish_start()

    def has_success_overlay(self):
        return self.find_one(Labels.fising_sucess)

    def has_fish_start(self):
        def frame_process(img):
            return iu.create_color_mask(img, text_white_color)

        return self.find_one(Labels.fish_start, frame_processor=frame_process)

    def has_fish_bait(self):
        def frame_process(img):
            return iu.create_color_mask(img, text_white_color)

        return self.find_one(Labels.fish_bait, frame_processor=frame_process)

    def is_fish_biting(self):
        box = self.box_of_screen(0.9023, 0.8562, 0.9488, 0.9403, name="fishing_bite_indicator")
        image = box.crop_frame(self.frame)
        if image is None or image.size == 0:
            return False

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
            return False

        blue_pixels_ratio = blue_pixels / total_circle_pixels
        return blue_pixels_ratio > 0.07

    def handle_monthly_card(self):
        monthly_card = self.find_monthly_card()
        if monthly_card is not None:
            self._clear_bar_key_if_hold_mode()
            self.log_info("monthly_card found click")
            self.click(0.50, 0.89)
            self.sleep(2)
            self.click(0.50, 0.89)
            self.sleep(2)
            if self.find_monthly_card() is None:
                self.set_check_monthly_card(next_day=True)
            else:
                self.log_warning("monthly_card close failed")
        return monthly_card is not None

    def reset_runtime_state(self):
        self._set_bar_key(None)
        self._last_bar_log_time = 0.0
        self._last_direction = None
        self._bar_active_key = None

    def _configured_rounds(self):
        return max(1, int(self.config.get(self.CONF_ROUNDS, 1)))

    def _publish_config_info(self):
        self.info_set("控条模式", self.config.get(self.CONF_CONTROL_MODE, self.MODE_HOLD))
        self.info_set(
            "自动补饵卖鱼",
            "开启" if self.config.get(self.CONF_AUTO_BUY_BAIT, True) else "关闭",
        )
        self.info_set("轮次", "")
        self.info_set("成功次数", 0)
        self.info_set("失败次数", 0)
        self.info_set("当前阶段", "")
        self.info_set("失败原因", "")

    def _set_stage(self, stage: str):
        if self.info_get("当前阶段") != stage:
            self.info_set("当前阶段", stage)


fishing_bite_blue_color = {
    "r": (30, 35),
    "g": (120, 130),
    "b": (250, 255),
}
