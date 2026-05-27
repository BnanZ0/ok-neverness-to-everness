import time
from src.char.Nanally import Nanally

class NanallyChain(Nanally):
    HANDOFF_MARGIN = 2.0        # 九原交接提前量
    NANALLY_STAY_TIME = 1.2     # 娜娜莉循环时长
    HOTORI_STEAL_TIME = 0.8     # 浔循环时长
    SWITCH_TIMEOUT = 1.0        # 切人超时
    INITIAL_E_TIMEOUT = 2.0     # 开场等E超时
    INITIAL_Q_TIMEOUT = 1.0     # E后等Q超时
    EQ_MIN_INTERVAL = 0.5       # E→Q最小间隔
    LOOP_TICK = 0.05            # 通用轮询间隔
    E_CD_CONFIRM_TIMEOUT = 0.5  # E CD确认超时
    E_CD_CONFIRM_TICK = 0.03    # E CD确认轮询间隔

    def do_perform(self):
        if self.task.chain_executor.active:
            self.continues_normal_attack(0.2)
            return
        self.wait_intro()
        self.click_skill()
        self.click_ultimate()

    def _confirm_e_cd(self):
        start = time.time()
        while time.time() - start < self.E_CD_CONFIRM_TIMEOUT:
            if self.has_cd("skill"):
                return True
            self.sleep(self.E_CD_CONFIRM_TICK)
        return False

    def _try_initial_e_release(self):
        _last_e_time = 0
        if not self.has_cd("skill"):
            e_deadline = time.time() + self.INITIAL_E_TIMEOUT
            while time.time() < e_deadline:
                self.task.sleep_check()
                if self.skill_available() and self.click_skill() and self._confirm_e_cd():
                    _last_e_time = time.time()
                    self.logger.info("Nanally E released for copy")
                    break
                self.click()
                self.sleep(self.LOOP_TICK)
        else:
            self.logger.info("Nanally E in CD, skip initial release, entering standby directly")
        return _last_e_time

    def _try_q_after_e(self, last_e_time):
        if last_e_time > 0:
            q_deadline = time.time() + self.INITIAL_Q_TIMEOUT
            while time.time() < q_deadline:
                self.task.sleep_check()
                if self.ultimate_available() and time.time() - last_e_time >= self.EQ_MIN_INTERVAL:
                    self.task.allow_ultimate_during_settle()
                    if self.click_ultimate():
                        self.logger.info("Nanally Q released after E")
                        break
                self.click()
                self.sleep(self.LOOP_TICK)

    def _standby_loop_iteration(self, hotori, last_e_time):
        nanally_start = time.time()
        while time.time() - nanally_start < self.NANALLY_STAY_TIME:
            self.task.sleep_check()
            if hotori and hotori.time_to_next_burst() <= self.HANDOFF_MARGIN:
                return last_e_time, True

            if self.task.is_char_at_index(self.index):
                if self.skill_available() and self.click_skill() and self._confirm_e_cd():
                    last_e_time = time.time()
                if self.ultimate_available() and time.time() - last_e_time >= self.EQ_MIN_INTERVAL:
                    self.task.allow_ultimate_during_settle()
                    self.click_ultimate()
                self.click()
            else:
                self.click()
                nanally_key = self._get_char_key("NanallyChain")
                if nanally_key:
                    self.task.send_key(nanally_key)
            self.sleep(self.LOOP_TICK)

        handoff = hotori and hotori.time_to_next_burst() <= self.HANDOFF_MARGIN
        return last_e_time, handoff

    def _switch_to_hotori_and_back(self, hotori):
        hotori_key = self._get_char_key("HotoriChain")
        if hotori_key:
            self.task.send_key(hotori_key)
            switch_start = time.time()
            while not self.task.is_char_at_index(hotori.index) and time.time() - switch_start < self.SWITCH_TIMEOUT:
                self.task.sleep_check()
                self.click()
                self.sleep(self.LOOP_TICK)

            if self.task.is_char_at_index(hotori.index):
                hotori_start = time.time()
                while time.time() - hotori_start < self.HOTORI_STEAL_TIME:
                    self.task.sleep_check()
                    hotori.click()
                    hotori.sleep(self.LOOP_TICK)
                    self.task.next_frame()

        nanally_key = self._get_char_key("NanallyChain")
        if nanally_key:
            self.task.send_key(nanally_key)
            switch_back_start = time.time()
            while not self.task.is_char_at_index(self.index) and time.time() - switch_back_start < self.SWITCH_TIMEOUT:
                self.task.sleep_check()
                self.click()
                self.sleep(self.LOOP_TICK)

    def chain_dynamic_standby(self):
        wait_start = time.time()
        while time.time() - wait_start < self.SWITCH_TIMEOUT:
            self.task.sleep_check()
            if self.task.is_char_at_index(self.index):
                break
            self.sleep(self.LOOP_TICK)
            

        hotori = next((c for c in self.task.chars if c.__class__.__name__ == "HotoriChain"), None)
        if not hotori:
            hotori = next((c for c in self.task.chars if hasattr(c, 'name') and c.name == "Hotori"), None)
        _last_e_time = self._try_initial_e_release()
        self._try_q_after_e(_last_e_time)

        while True:
            self.task.sleep_check()
            if hotori and hotori.time_to_next_burst() <= self.HANDOFF_MARGIN:
                self.logger.info("Nanally bail, handing off to Jiuyuan")
                self.task.chain_executor.step_complete()
                self._send_chain_key()
                self.switch_next_char()
                return

            _last_e_time, handoff = self._standby_loop_iteration(hotori, _last_e_time)

            if handoff:
                continue

            self._switch_to_hotori_and_back(hotori)