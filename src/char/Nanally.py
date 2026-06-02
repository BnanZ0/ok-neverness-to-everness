import time

from src.char.BaseChar import BaseChar


class Nanally(BaseChar):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def do_perform(self):
        self.wait_intro()
        skill = self.click_skill()[0]
        if self.ultimate_available() and skill:
            self.sleep(0.6)
        if self.click_ultimate():
            self.perform_in_ult()

    def perform_in_ult(self):
        start = time.time()
        while (elapsed := time.time() - start) < 6:
            if elapsed > 1 and not self.ultimate_available(False):
                break
            self.normal_attack()
            self.sleep(0.2)

    def do_fast_perform(self):
        self.wait_intro()
        self.click_skill()
