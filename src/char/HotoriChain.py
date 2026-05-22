import time

from src.char.Hotori import Hotori


class HotoriChain(Hotori):
    STARTUP_CHAIN = [
        ("HotoriChain", "chain_e_start_chain"),
        ("ZeroChain", "chain_q_e_wait"),
        ("JiuyuanChain", "chain_intro_only"),
        ("NanallyChain", "chain_e_q_6s_swap"),
        ("JiuyuanChain", "chain_q_e_heavy"),
        ("HotoriChain", "chain_q_na"),
    ]
    WARMUP_CHAIN = [
        ("ZeroChain", "chain_nop"),
        ("JiuyuanChain", "chain_intro_only"),
        ("ZeroChain", "chain_e_only"),
        ("NanallyChain", "chain_intro_e_q_10s_swap"),
        ("JiuyuanChain", "chain_q_e_heavy"),
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.team_skill_records = {}
        self._chain_cycle = 0
        self._e_used = False
        self._e_lockdown = False

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
        self.task.chain_executor._pending_anchor = self
        return None

    def do_perform(self):
        self.wait_intro()
        if self._e_lockdown:
            self.continues_normal_attack(0.2)
            return
        if self._e_used:
            if self.ready_for_ultimate() and self.click_ultimate():
                self._e_used = False
                self.clear_team_skill_records()
                return
            self.continues_normal_attack(0.2)
            return
        self.task.chain_executor.loop(self._build_next_chain)

    def count_ultimate_priority(self):
        if not self.ultimate_available():
            return 0
        return 1

    def _confirm_skill_cd(self):
        start = time.time()
        while time.time() - start < 0.3:
            if self.has_cd("skill"):
                return True
            self.sleep(0.03)
        return False

    def chain_e_start_chain(self):
        self.logger.info(f"chain_e_start_chain: entering, has_intro={self.has_intro}")

        if self.has_intro:
            start = time.time()
            while time.time() - start < self.INTRO_MOTION_FREEZE_DURATION:
                clicked, _, _ = self.click_skill()
                if clicked:
                    self.logger.info("chain_e_start_chain: E cast during intro")
                    break
                self.click()
                self.sleep(0.1)

        fail_count = 0
        last_attempt = 0
        while True:
            self.task.sleep_check()

            if self.has_cd("skill"):
                self.logger.info("chain_e_start_chain: E already in CD, proceeding")
                self._e_used = True
                self._e_lockdown = True
                self.start_team_skill_window()
                self.sleep(0.1)
                self.task.chain_executor.step_complete()
                self._send_chain_key()
                self.switch_next_char()
                return

            now = time.time()
            if now - last_attempt < 0.5:
                self.sleep(0.05)
                continue

            available = self.skill_available()
            self.logger.debug(f"chain_e_start_chain: attempt {fail_count+1}, skill_available={available}")

            if available:
                clicked, _, _ = self.click_skill(time_out=1.5)
                if clicked:
                    if self._confirm_skill_cd():
                        self.logger.info(f"chain_e_start_chain: E cast confirmed via CD after {fail_count} failures")
                    elif self.skill_available():
                        self.logger.warning("chain_e_start_chain: E interrupted (skill still available), retrying")
                        fail_count += 1
                        last_attempt = now
                        self.sleep(0.05)
                        continue
                    else:
                        self.logger.info(f"chain_e_start_chain: E cast assumed (no CD but skill unavailable) after {fail_count} failures")
                    self._e_used = True
                    self._e_lockdown = True
                    self.start_team_skill_window()
                    self.sleep(0.1)
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
                        self.sleep(0.1)
                        self.task.chain_executor.step_complete()
                        self._send_chain_key()
                        self.switch_next_char()
                        return
            else:
                self.logger.debug("chain_e_start_chain: skill not available, waiting")

            last_attempt = now
            self.sleep(0.05)

    def chain_q_na(self):
        q_done = False
        if self.has_intro:
            start = time.time()
            while time.time() - start < self.INTRO_MOTION_FREEZE_DURATION:
                self.click()
                if self.ultimate_available() and self.click_ultimate(send_click=True):
                    q_done = True
                    break
                self.sleep(0.1)
        if not q_done:
            self.task.sleep(1)
            self.task._combat_settle.time = None
            while True:
                self.task.sleep_check()
                if self.ultimate_available():
                    if self.click_ultimate(send_click=True):
                        self.logger.info("chain_q_na Q done")
                        break
                self.click()
                self.sleep(0.1)
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
