import time

import numpy as np

from src.char.BaseChar import BaseChar, Priority
from src.utils import image_utils as iu


class Hotori(BaseChar):
    TEAM_SKILL_WINDOW = 5
    MAX_TEAM_SKILL_RECORDS = 3
    ULT_ATTACK_DURATION = 6

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.start_combat = True
        self.team_skill_window_start = 0

    def do_perform(self):
        self.wait_intro()

        if self.can_ultimate_with_records():
            if self.click_ultimate():
                self.clear_team_skill_records()
            else:
                self.continues_normal_attack(0.2)
            return

        if self.has_team_skill_records():
            self.continues_normal_attack(0.2)
            return

        if self.waiting_for_team_skills():
            self.continues_normal_attack(0.2)
            return

        if self.click_skill(time_out=1.5)[0]:
            self.start_team_skill_window()

    def do_get_switch_priority(self, current_char, has_intro=False):
        if self.waiting_for_team_skills():
            return Priority.MIN
        return super().do_get_switch_priority(current_char, has_intro)

    def need_fast_perform_entry(self, current_char) -> bool:
        return self.waiting_for_team_skills()

    def start_team_skill_window(self):
        self.team_skill_window_start = (
            self.last_skill_time if self.last_skill_time > 0 else time.time()
        )

    def clear_team_skill_records(self):
        self.team_skill_window_start = 0

    def required_team_skill_records(self):
        return min(self.MAX_TEAM_SKILL_RECORDS, max(0, len(self.task.chars) - 1))

    def team_skill_window_elapsed(self):
        return self.time_elapsed_accounting_for_freeze(self.team_skill_window_start)

    def expire_team_skill_window(self):
        self.team_skill_window_start = 0

    def ready_for_ultimate(self):
        required = self.required_team_skill_records()
        return required > 0 and self.count_team_skill_records() >= required

    def has_team_skill_records(self):
        return self.count_team_skill_records()

    def count_team_skill_records(self):

        def is_dark(img):
            white_count = np.sum(img == 255)
            black_count = np.sum(img == 0)
            # self.logger.info(f"white {white_count}, black {black_count}")
            return black_count > white_count

        # fmt: off
        box_1 = self.task.box_of_screen(
            0.430, 0.910, 0.435, 0.915,
            name="skill_record_1",
        )
        box_2 = self.task.box_of_screen(
            0.445, 0.903, 0.453, 0.908,
            name="skill_record_1",
        )
        box_3 = self.task.box_of_screen(
            0.464, 0.904, 0.471, 0.909,
            name="skill_record_1",
        )
        # fmt: on
        count = 0
        _frame = self.task.frame
        for box in [box_1, box_2, box_3]:
            roi = box.crop_frame(_frame)
            roi = iu.binarize_bgr_by_brightness(roi, 240, to_bgr=False)
            # iu.show_images(roi)
            if is_dark(roi):
                break
            count += 1
        return count

    def can_ultimate_with_records(self):
        return self.ready_for_ultimate() or (
            self.has_team_skill_records() and not self.waiting_for_team_skills()
        )

    def waiting_for_team_skills(self):
        if self.team_skill_window_start <= 0 or self.ready_for_ultimate():
            return False
        if self.team_skill_window_elapsed() > self.TEAM_SKILL_WINDOW:
            self.expire_team_skill_window()
            return False
        return True

    def reset_state(self):
        super().reset_state()
        self.clear_team_skill_records()

    def on_combat_end(self, chars):
        self.clear_team_skill_records()

    # def skill_available(self, check_color=True):
    #     available = super().skill_available(check_color=check_color)
    #     box = self.task.box_of_screen(0.3590, 0.9299, 0.3641, 0.9444,
    #                                   name="hotori_skill_available")
    #     color_percent = self.task.calculate_color_percentage(text_white_color, box)
    #     # self.logger.debug(f"skill color {color_percent}")
    #     if color_percent > 0.4 and available:
    #         return True

    def _wait_ultimate_unfreeze(self, start):
        self.logger.debug("waiting for time unfrozen")
        self.task.in_animation = False
        self.task.wait_until(lambda: self.available("ultimate"), time_out=0.5)
        try:
            self.task.wait_until(
                lambda: not self.available("ultimate"),
                time_out=13,
                post_action=self.click_with_interval,
                pre_action=self.check_combat,
            )
        finally:
            duration = time.time() - start - 0.1
            self.add_freeze_duration(start, duration)
        return duration
