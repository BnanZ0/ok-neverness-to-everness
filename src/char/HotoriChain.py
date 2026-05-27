import time

from src.char.custom.BuiltinComboRegistry import BuiltinComboRegistry
from src.char.custom.CustomCharManager import CustomCharManager
from src.char.Hotori import Hotori


class HotoriChain(Hotori):
    STARTUP_CHAIN = [
        ("HotoriChain", "chain_e_start_chain"),
        ("ZeroChain", "chain_q_e_wait"),
        ("JiuyuanChain", "chain_intro_only"),
        ("NanallyChain", "chain_dynamic_standby"),
        ("JiuyuanChain", "chain_q_e_heavy"),
        ("HotoriChain", "chain_q_na"),
    ]
    WARMUP_CHAIN = [
        ("ZeroChain", "chain_nop"),
        ("JiuyuanChain", "chain_intro_only"),
        ("ZeroChain", "chain_e_only"),
        ("NanallyChain", "chain_dynamic_standby"),
        ("JiuyuanChain", "chain_q_e_heavy"),
    ]
    STARTUP_DURATION = 15.0         # 启动轴时长
    WARMUP_DURATION = 20.0          # 暖机轴时长
    SWITCH_TIMEOUT = 1.0            # 切人超时
    E_RETRY_INTERVAL = 1.0          # E重试间隔
    E_CLICK_TIMEOUT = 0.5           # E点击超时
    CD_CONFIRM_TIMEOUT = 0.5        # CD确认超时
    CD_CONFIRM_TICK = 0.03          # CD确认轮询间隔
    POST_ACTION_PAUSE = 0.1         # 动作后暂停
    CHAIN_NA_INTERVAL = 0.2         # 链内普攻间隔
    Q_PRE_SLEEP = 1.0               # Q前等待
    Q_RECOVERY_MARGIN = 0.3         # Q恢复余量
    LOOP_TICK = 0.05                # 通用轮询间隔
    INTRO_LOOP_INTERVAL = 0.1       # 入场动画轮询间隔

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.team_skill_records = {}
        self._chain_cycle = 0
        self._e_used = False
        self._e_lockdown = False

    def current_axis(self):
        if self._e_cast_time >= self._q_cast_time:
            return "STARTUP"
        return "WARMUP"

    def time_to_next_burst(self):
        axis = self.current_axis()
        if axis == "STARTUP":
            if self._e_cast_time <= 0:
                return 999
            elapsed = self.time_elapsed_accounting_for_freeze(self._e_cast_time)
            return max(0.0, self.STARTUP_DURATION - elapsed)
        else:
            if self._q_cast_time <= 0:
                return 999
            elapsed = self.time_elapsed_accounting_for_freeze(self._q_cast_time)
            return max(0.0, self.WARMUP_DURATION - elapsed)

    def is_anchor(self) -> bool:
        return True

    def _get_teammate(self, cls_name):
        for c in self.task.chars:
            if c is not None and c.__class__.__name__ == cls_name:
                return c
        return None

    def _build_steps(self, axis_type):
        chain_def = self.STARTUP_CHAIN if axis_type == "startup" else self.WARMUP_CHAIN
        steps = []
        for cls_name, method in chain_def:
            char = self._get_teammate(cls_name)
            if char is None and cls_name == self.__class__.__name__:
                char = self
            if char:
                steps.append((char, method))
            else:
                self.logger.warning(f"Chain step skipped: {cls_name}.{method} (char not found)")
        return steps

    def _build_next_chain(self):
        if self._chain_cycle == 0:
            self._chain_cycle = 1
            return self._build_steps("startup")
        if self._chain_cycle == 1:
            self._chain_cycle = 2
            return self._build_steps("warmup")
        self._chain_cycle = 0
        self.task.chain_executor.set_axis_anchor(self)
        return None

    def do_perform(self):
        self.wait_intro()
        ft = CustomCharManager().get_fixed_team()
        if not ft.get("enabled", False):
            Hotori.do_perform(self)
            return
        slots = ft.get("slots", [])
        if len(slots) < 4:
            Hotori.do_perform(self)
            return
        chain_keys = ["char_chain_hotori", "char_chain_zero", "char_chain_jiuyuan", "char_chain_nanally"]
        for i, slot in enumerate(slots):
            key = CustomCharManager().get_builtin_key(slot.get("combo_ref", ""))
            if key != chain_keys[i]:
                Hotori.do_perform(self)
                return
        if self._e_lockdown:
            self.continues_normal_attack(self.CHAIN_NA_INTERVAL)
            return
        if self._e_used:
            if self.ready_for_ultimate() and self.click_ultimate():
                self._e_used = False
                self.clear_team_skill_records()
                return
            self.continues_normal_attack(self.CHAIN_NA_INTERVAL)
            return
        if self._chain_cycle == 0 and self._q_cast_time > 0 and self.time_to_next_burst() > self.Q_RECOVERY_MARGIN:
            self.continues_normal_attack(self.CHAIN_NA_INTERVAL)
            return
        self.task.chain_executor.loop(self._build_next_chain)

    def count_ultimate_priority(self):
        if not self.ultimate_available():
            return 0
        return 1

    def _confirm_skill_cd(self):
        start = time.time()
        while time.time() - start < self.CD_CONFIRM_TIMEOUT:
            if self.has_cd("skill"):
                return True
            self.sleep(self.CD_CONFIRM_TICK)
        return False

    def _confirm_q_cd(self):
        start = time.time()
        while time.time() - start < self.CD_CONFIRM_TIMEOUT:
            if self.has_cd("ultimate"):
                return True
            self.sleep(self.CD_CONFIRM_TICK)
        return False

    def chain_e_start_chain(self):
        self.logger.info(f"chain_e_start_chain: entering, has_intro={self.has_intro}")
        wait_start = time.time()
        while time.time() - wait_start < self.SWITCH_TIMEOUT:
            self.task.sleep_check()
            if self.task.is_char_at_index(self.index):
                break
            self.sleep(self.LOOP_TICK)

        if self.has_intro:
            start = time.time()
            while time.time() - start < self.INTRO_MOTION_FREEZE_DURATION:
                clicked, _, _ = self.click_skill()
                if clicked:
                    self.logger.info("chain_e_start_chain: E cast during intro")
                    break
                self.click()
                self.sleep(self.INTRO_LOOP_INTERVAL)

        fail_count = 0
        last_attempt = 0
        while True:
            self.task.sleep_check()

            if self.has_cd("skill"):
                self.logger.info("chain_e_start_chain: E already in CD, proceeding")
                self._e_used = True
                self._e_lockdown = True
                self.start_team_skill_window()
                self.sleep(self.POST_ACTION_PAUSE)
                self.task.chain_executor.step_complete()
                self._send_chain_key()
                self.switch_next_char()
                return

            now = time.time()
            if now - last_attempt < self.E_RETRY_INTERVAL:
                self.sleep(self.LOOP_TICK)
                continue

            available = self.skill_available()
            self.logger.debug(f"chain_e_start_chain: attempt {fail_count+1}, skill_available={available}")

            if available:
                clicked, _, _ = self.click_skill(time_out=self.E_CLICK_TIMEOUT)
                if clicked:
                    if self._confirm_skill_cd():
                        self.logger.info(f"chain_e_start_chain: E cast confirmed via CD after {fail_count} failures")
                    elif self.skill_available():
                        self.logger.warning("chain_e_start_chain: E interrupted (skill still available), retrying")
                        fail_count += 1
                        last_attempt = now
                        self.sleep(self.LOOP_TICK)
                        continue
                    else:
                        self.sleep(0.3)
                        if self.has_cd("skill"):
                            self.logger.info(f"chain_e_start_chain: CD confirmed after wait (ddg/interrupted) after {fail_count} failures")
                        elif self.skill_available():
                            self.logger.warning("chain_e_start_chain: skill recovered after wait, retrying")
                            fail_count += 1
                            last_attempt = now
                            self.sleep(self.LOOP_TICK)
                            continue
                        else:
                            self.logger.info(f"chain_e_start_chain: E cast assumed after wait ({fail_count} failures)")
                    self._e_used = True
                    self._e_lockdown = True
                    self.start_team_skill_window()
                    self.sleep(self.POST_ACTION_PAUSE)
                    self.task.chain_executor.step_complete()
                    self._send_chain_key()
                    self.switch_next_char()
                    return
                else:
                    fail_count += 1
                    self.logger.warning(f"chain_e_start_chain: E click failed ({fail_count} consecutive)")
                    if self.has_cd("skill"):
                        self.logger.info("chain_e_start_chain: E CD detected after failed click, proceeding")
                        self._e_used = True
                        self._e_lockdown = True
                        self.start_team_skill_window()
                        self.sleep(self.POST_ACTION_PAUSE)
                        self.task.chain_executor.step_complete()
                        self._send_chain_key()
                        self.switch_next_char()
                        return
            else:
                self.logger.debug("chain_e_start_chain: skill not available, waiting")

            last_attempt = now
            self.sleep(self.LOOP_TICK)

    def chain_q_na(self):
        wait_start = time.time()
        while time.time() - wait_start < self.SWITCH_TIMEOUT:
            self.task.sleep_check()
            if self.task.is_char_at_index(self.index):
                break
            self.sleep(self.LOOP_TICK)
        
        q_done = False
        if self.has_intro:
            start = time.time()
            while time.time() - start < self.INTRO_MOTION_FREEZE_DURATION:
                self.click()
                if self.ultimate_available() and self.click_ultimate(send_click=True) and self._confirm_q_cd():
                    q_done = True
                    self._q_cast_time = time.time()
                    break
                self.sleep(self.INTRO_LOOP_INTERVAL)
        if not q_done:
            self.task.sleep(self.Q_PRE_SLEEP)
            self.task.allow_ultimate_during_settle()
            while True:
                self.task.sleep_check()
                if self.ultimate_available():
                    if self.click_ultimate(send_click=True) and self._confirm_q_cd():
                        self._q_cast_time = time.time()
                        break
                self.click()
                self.sleep(self.INTRO_LOOP_INTERVAL)
        self._e_used = False
        self.clear_team_skill_records()
        self.task.chain_executor.step_complete()
        self._send_chain_key()
        self.switch_next_char()


    def start_team_skill_window(self):
        self.team_skill_window_start = (
            self.last_skill_time if self.last_skill_time > 0 else time.time()
        )
        self.team_skill_records.clear()
        self._e_cast_time = time.time()

    def clear_team_skill_records(self):
        self.team_skill_window_start = 0
        self.team_skill_records.clear()

    def required_team_skill_records(self):
        return min(self.MAX_TEAM_SKILL_RECORDS, max(0, len(self.task.chars) - 1))

    def team_skill_window_elapsed(self):
        return self.time_elapsed_accounting_for_freeze(self.team_skill_window_start)

    def expire_team_skill_window(self):
        elapsed = self.team_skill_window_elapsed()
        self.logger.info(
            f"team skill window expired after {elapsed:.1f}s "
            f"records={{{','.join(str(k) for k in self.team_skill_records)}}}"
        )
        self.clear_team_skill_records()

    def update_team_skill_records(self):
        if self.team_skill_window_start <= 0:
            return
        if self.ready_for_ultimate():
            return

        if self.team_skill_window_elapsed() > self.TEAM_SKILL_WINDOW:
            self.expire_team_skill_window()
            return

        for char in self.task.chars:
            if char is None or char == self:
                continue
            if self.team_skill_window_start <= char.last_skill_time:
                prev_time = self.team_skill_records.get(char.index)
                if prev_time == char.last_skill_time:
                    continue
                self.team_skill_records[char.index] = char.last_skill_time
                self.logger.info(
                    f"record team skill {char} {len(self.team_skill_records)}/"
                    f"{self.required_team_skill_records()}"
                )
                if self.ready_for_ultimate():
                    return

    def ready_for_ultimate(self):
        required = self.required_team_skill_records()
        return required > 0 and len(self.team_skill_records) >= required

    def has_team_skill_records(self):
        return len(self.team_skill_records) > 0

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
        self._e_used = False
        self._e_lockdown = False
        self._chain_cycle = 0

    def on_combat_end(self, chars):
        self.clear_team_skill_records()

    def on_chain_step_complete(self):
        super().on_chain_step_complete()
        ce = self.task.chain_executor
        if ce.active and ce.current_index >= len(ce.steps) and self._chain_cycle == 2:
            self._e_lockdown = False
            self.logger.info("Hotori E lock auto-released for next startup")
