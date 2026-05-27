import time

from src.char.Jiuyuan import Jiuyuan


class JiuyuanChain(Jiuyuan):
    def do_perform(self):
        if self.task.chain_executor.active:
            self.continues_normal_attack(0.2)
            return
        self.wait_intro()
        self.click_ultimate()
        if self.click_skill()[0]:
            self.continues_normal_attack(1.4)
            self.sleep(0.1)
        self.fire_bullets()

    def chain_intro_only(self):
        wait_start = time.time()
        while time.time() - wait_start < 1.0:
            self.task.sleep_check()
            if self.task.is_char_at_index(self.index):
                break
            self.sleep(0.05)
        
        if self.has_intro:
            start = time.time()
            while time.time() - start < self.INTRO_MOTION_FREEZE_DURATION:
                self.click()
                if self.skill_available() or self.ultimate_available():
                    break
                self.sleep(0.1)

        self.task.chain_executor.step_complete()
        self._send_chain_key()
        self.switch_next_char()

    def chain_q_e_heavy(self):
        if self.has_intro:
            start = time.time()
            while time.time() - start < self.INTRO_MOTION_FREEZE_DURATION:
                self.click()
                if self.ultimate_available():
                    break
                self.sleep(0.1)
        q_deadline = time.time() + 0.3
        self.task._combat_settle.time = None
        while time.time() < q_deadline:
            self.task.sleep_check()
            self.click()
            if self.ultimate_available():
                if self.click_ultimate(send_click=True):
                    break
            self.sleep(0.05)
        while True:
            self.task.sleep_check()
            clicked, _, _ = self.click_skill()
            if clicked:
                self.sleep(1.3)
                self.task.mouse_down()
                self.sleep(0.6)
                self.task.mouse_up()
            self.task.chain_executor.step_complete()
            self._send_chain_key()
            self.switch_next_char()
            return
