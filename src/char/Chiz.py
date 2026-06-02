
import re
import time

from src.char.BaseChar import BaseChar


class Chiz(BaseChar):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def do_perform(self):
        self.wait_intro()
        if self.click_ultimate():
            self.perform_in_ult()
        self.click_skill()
    
    def perform_in_ult(self):
        box = self.task.box_of_screen(0.487, 0.775, 0.514, 0.798, name="percentage")
        self.task.wait_ocr(box=box, match=re.compile(r"-?\d+%", re.IGNORECASE))
        deadline = time.time() + 8
        while time.time() < deadline:
            red_pct = self.task.calculate_color_percentage(red_pct_color, box)
            yellow_pct = self.task.calculate_color_percentage(yellow_pct_color, box)
            if yellow_pct > red_pct:
                self.send_skill_key()
            self.click_with_interval()
            self.sleep(0.1)

    def do_fast_perform(self):
        self.wait_intro()
        start = time.time()
        while time.time() - start < 1:
            self.send_skill_key()
            self.sleep(0.1)


red_pct_color = {
    "r": (250, 255),
    "g": (115, 125),
    "b": (115, 120),
}

yellow_pct_color = {
    "r": (250, 255),
    "g": (230, 240),
    "b": (120, 125),
}