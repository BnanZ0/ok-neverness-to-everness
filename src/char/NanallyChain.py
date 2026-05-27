import time

from src.char.Nanally import Nanally


class NanallyChain(Nanally):
    def do_perform(self):
        if self.task.chain_executor.active:
            self.continues_normal_attack(0.2)
            return
        self.wait_intro()
        self.click_skill()
        self.click_ultimate()

    def chain_dynamic_standby(self):
        hotori = next((c for c in self.task.chars if c.__class__.__name__ == "HotoriChain"), None)
        _last_e_time = 0

        if not self.has_cd("skill"):
            e_deadline = time.time() + 2.0
            while time.time() < e_deadline:
                self.task.sleep_check()
                if self.skill_available():
                    if self.click_skill():
                        _last_e_time = time.time()
                        self.logger.info("Nanally E released for copy")
                        break
                self.click()
                self.sleep(0.05)

            if _last_e_time > 0:
                q_deadline = time.time() + 1.0
                while time.time() < q_deadline:
                    self.task.sleep_check()
                    if self.ultimate_available() and time.time() - _last_e_time >= 0.4:
                        self.task._combat_settle.time = None
                        self.click_ultimate()
                        self.logger.info("Nanally Q released after E")
                        break
                    self.click()
                    self.sleep(0.05)
        else:
            self.logger.info("Nanally E in CD, skip initial release, entering standby directly")

        while True:
            self.task.sleep_check()

            if hotori and hotori.time_to_next_burst() <= 2.0:
                self.logger.info("Nanally bail, handing off to Jiuyuan")
                self.task.chain_executor.step_complete()
                self._send_chain_key()
                self.switch_next_char()
                return

            nanally_start = time.time()
            while time.time() - nanally_start < 1.2:
                self.task.sleep_check()

                if hotori and hotori.time_to_next_burst() <= 2.0:
                    break

                if self.task.is_char_at_index(self.index):
                    if self.skill_available():
                        if self.click_skill():
                            _last_e_time = time.time()
                    if self.ultimate_available() and time.time() - _last_e_time >= 0.4:
                        self.task._combat_settle.time = None
                        self.click_ultimate()
                    self.click()
                else:
                    self.click()
                    nanally_key = self._get_char_key("NanallyChain")
                    if nanally_key:
                        self.task.send_key(nanally_key)

                self.sleep(0.05)

            if hotori and hotori.time_to_next_burst() <= 2.0:
                continue

            hotori_key = self._get_char_key("HotoriChain")
            if hotori_key:
                self.task.send_key(hotori_key)

                switch_start = time.time()
                while not self.task.is_char_at_index(hotori.index) and time.time() - switch_start < 1.0:
                    self.task.sleep_check()
                    self.click()
                    self.sleep(0.05)

                if self.task.is_char_at_index(hotori.index):
                    hotori_start = time.time()
                    while time.time() - hotori_start < 0.8:
                        self.task.sleep_check()
                        hotori.click()
                        hotori.sleep(0.1)
                        self.task.next_frame()

            nanally_key = self._get_char_key("NanallyChain")
            if nanally_key:
                self.task.send_key(nanally_key)

                switch_back_start = time.time()
                while not self.task.is_char_at_index(self.index) and time.time() - switch_back_start < 1.0:
                    self.task.sleep_check()
                    self.click()
                    self.sleep(0.05)
