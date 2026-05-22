import time

from src.char.Zero import Zero


class ZeroChain(Zero):
    def do_perform(self):
        if self.task.chain_executor.active:
            self.continues_normal_attack(0.2)
            return
        self._do_perform_legacy()

    def _do_perform_legacy(self):
        self.wait_intro()
        self.click_ultimate()
        self.click_skill()
        self.continues_normal_attack(0.5, interval=0.01)

    def chain_q_e_wait(self):
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
                self.task.chain_executor.step_complete()
                self._send_chain_key()
                self.switch_next_char()
                return
            self.click()
            self.sleep(0.05)

    def chain_nop(self):
        self.task.chain_executor.step_complete()
        self._send_chain_key()
        self.switch_next_char()

    def chain_e_only(self):
        if self.has_intro:
            start = time.time()
            while time.time() - start < self.INTRO_MOTION_FREEZE_DURATION:
                self.click()
                if self.skill_available():
                    break
                self.sleep(0.1)

        deadline = time.time() + 5
        while time.time() < deadline:
            self.task.sleep_check()
            self.click()
            if self.skill_available():
                self.click_skill()
                break
            self.sleep(0.05)

        self.task.chain_executor.step_complete()
        self._send_chain_key()
        self.switch_next_char()
