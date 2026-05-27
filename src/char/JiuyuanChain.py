import time

from src.char.Jiuyuan import Jiuyuan


class JiuyuanChain(Jiuyuan):
    SWITCH_TIMEOUT = 1.0            # 切人超时
    Q_DEADLINE = 0.3                # Q释放截止
    E_POST_CAST_WAIT = 1.3          # E后等待重击
    HEAVY_CHARGE_TIME = 0.6         # 重击蓄力时间
    CHAIN_NA_INTERVAL = 0.2         # 链内普攻间隔
    NA_DURATION = 0.3               # 普攻持续
    NA_POST_PAUSE = 0.1             # 普攻后暂停
    LOOP_TICK = 0.05                # 通用轮询间隔
    INTRO_LOOP_INTERVAL = 0.1       # 入场动画轮询间隔
    E_CD_CONFIRM_TIMEOUT = 0.5      # E CD确认超时
    E_CD_CONFIRM_TICK = 0.03        # E CD确认轮询间隔
    Q_CD_CONFIRM_TIMEOUT = 0.5      # Q CD确认超时
    Q_CD_CONFIRM_TICK = 0.03        # Q CD确认轮询间隔

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

    def do_perform(self):
        if self.task.chain_executor.active:
            self.continues_normal_attack(self.CHAIN_NA_INTERVAL)
            return
        self.wait_intro()
        self.click_ultimate()
        if self.click_skill()[0]:
            self.continues_normal_attack(self.NA_DURATION)
            self.sleep(self.NA_POST_PAUSE)
        self.fire_bullets()

    def chain_intro_only(self):
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
                if self.skill_available() or self.ultimate_available():
                    break
                self.sleep(self.INTRO_LOOP_INTERVAL)

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
                self.sleep(self.INTRO_LOOP_INTERVAL)
        q_deadline = time.time() + self.Q_DEADLINE
        self.task._combat_settle.time = None
        while time.time() < q_deadline:
            self.task.sleep_check()
            self.click()
            if self.ultimate_available():
                if self.click_ultimate(send_click=True):
                    if self._confirm_q_cd():
                        break
                    self.logger.warning("chain_q_e_heavy: Q clicked but CD not detected, retrying")
            self.sleep(self.LOOP_TICK)
        while True:
            self.task.sleep_check()
            clicked, _, _ = self.click_skill()
            if clicked and self._confirm_e_cd():
                self.sleep(self.E_POST_CAST_WAIT)
                self.task.mouse_down()
                self.sleep(self.HEAVY_CHARGE_TIME)
                self.task.mouse_up()
            self.task.chain_executor.step_complete()
            self._send_chain_key()
            self.switch_next_char()
            return
