import time

from src.char.Zero import Zero


class ZeroChain(Zero):
    SWITCH_TIMEOUT = 1.0            # 切人超时
    Q_DEADLINE = 0.3                # Q释放截止
    E_TIMEOUT = 1.0                 # E释放超时
    E_CD_CONFIRM_TIMEOUT = 0.5      # E CD确认超时
    E_CD_CONFIRM_TICK = 0.03        # E CD确认轮询间隔
    Q_CD_CONFIRM_TIMEOUT = 0.5      # Q CD确认超时
    Q_CD_CONFIRM_TICK = 0.03        # Q CD确认轮询间隔
    CHAIN_NA_INTERVAL = 0.2         # 链内普攻间隔
    NA_DURATION = 0.3               # 普攻持续
    NA_TICK = 0.1                  # 普攻轮询间隔
    LOOP_TICK = 0.05                # 通用轮询间隔
    INTRO_LOOP_INTERVAL = 0.1       # 入场动画轮询间隔

    def do_perform(self):
        if self.task.chain_executor.active:
            self.continues_normal_attack(self.CHAIN_NA_INTERVAL)
            return
        self._do_perform_legacy()

    def _do_perform_legacy(self):
        self.wait_intro()
        self.click_ultimate()
        self.click_skill()
        self.continues_normal_attack(self.NA_DURATION, interval=self.NA_TICK)

    def _confirm_e_cd(self):
        start = time.time()
        while time.time() - start < self.E_CD_CONFIRM_TIMEOUT:
            if self.has_cd("skill"):
                return True
            self.sleep(self.E_CD_CONFIRM_TICK)
        return False

    def _confirm_q_cd(self):
        start = time.time()
        while time.time() - start < self.Q_CD_CONFIRM_TIMEOUT:
            if self.has_cd("ultimate"):
                return True
            self.sleep(self.Q_CD_CONFIRM_TICK)
        return False

    def chain_q_e_wait(self):
        wait_start = time.time()
        while time.time() - wait_start < self.SWITCH_TIMEOUT:
            self.task.sleep_check()
            if self.task.is_char_at_index(self.index):
                break
            self.sleep(self.LOOP_TICK)
        
        if self.has_intro:
            start = time.time()
            while time.time() - start < self.INTRO_MOTION_FREEZE_DURATION:
                self.click()
                if self.ultimate_available():
                    break
                self.sleep(self.INTRO_LOOP_INTERVAL)
        
        q_deadline = time.time() + self.Q_DEADLINE
        self.task.allow_ultimate_during_settle()
        while time.time() < q_deadline:
            self.task.sleep_check()
            self.click()
            if self.ultimate_available():
                if self.click_ultimate(send_click=True) and self._confirm_q_cd():
                    break
            self.sleep(self.LOOP_TICK)
        
        while True:
            self.task.sleep_check()
            clicked, _, _ = self.click_skill()
            if clicked and self._confirm_e_cd():
                self.task.chain_executor.step_complete()
                self._send_chain_key()
                self.switch_next_char()
                return
            self.click()
            self.sleep(self.LOOP_TICK)

    def chain_nop(self):
        wait_start = time.time()
        while time.time() - wait_start < self.SWITCH_TIMEOUT:
            self.task.sleep_check()
            if self.task.is_char_at_index(self.index):
                break
            self.sleep(self.LOOP_TICK)
        
        self.task.chain_executor.step_complete()
        self._send_chain_key()
        self.switch_next_char()

    def chain_e_only(self):
        wait_start = time.time()
        while time.time() - wait_start < self.SWITCH_TIMEOUT:
            self.task.sleep_check()
            if self.task.is_char_at_index(self.index):
                break
            self.sleep(self.LOOP_TICK)
        
        if self.has_intro:
            start = time.time()
            while time.time() - start < self.INTRO_MOTION_FREEZE_DURATION:
                self.click()
                if self.skill_available():
                    break
                self.sleep(self.INTRO_LOOP_INTERVAL)

        deadline = time.time() + self.E_TIMEOUT
        while time.time() < deadline:
            self.task.sleep_check()
            self.click()
            if self.skill_available():
                self.click_skill()
                if self._confirm_e_cd():
                    break
            self.sleep(self.LOOP_TICK)

        self.task.chain_executor.step_complete()
        self._send_chain_key()
        self.switch_next_char()
