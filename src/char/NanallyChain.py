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

    def chain_e_q_6s_swap(self):
        self.task.suppress_dodge()
        q_casted = False

        hotori = next((c for c in self.task.chars if c.__class__.__name__ == "HotoriChain"), None)
        skip_e = hotori and hotori.team_skill_window_elapsed() > 5

        if skip_e:
            self.task.unsuppress_dodge()
        else:
            self.logger.info(f"chain_e_q_6s_swap: trying to cast E, skip_e={skip_e}")
            e_deadline = time.time() + 5
            while time.time() < e_deadline:
                self.task.sleep_check()
                if not self.task.is_char_at_index(self.index):
                    self.click()
                    self.sleep(0.01)
                    continue

                clicked, _, _ = self.click_skill()
                if clicked:
                    self.logger.info("chain_e_q_6s_swap: E cast success")
                    cd_start = time.time()
                    while time.time() - cd_start < 2:
                        self.task.sleep_check()
                        self.click()
                        if self.has_cd("skill"):
                            break
                        self.sleep(0.05)
                    self.click()
                    self.sleep(0.3)
                    if self.ultimate_available() and self.task.is_char_at_index(self.index):
                        self.task._combat_settle.time = None
                        self.click_ultimate()
                        q_casted = True
                    self.task.unsuppress_dodge()
                    break
                self.click()
                self.sleep(0.05)
            else:
                self.logger.info("chain_e_q_6s_swap: E cast timeout")
                self.task.unsuppress_dodge()

        total_start = time.time()
        total_deadline = total_start + 15
        last_log = 0

        for i in range(3):
            na_start = time.time()
            while time.time() - na_start < 1.2 and time.time() < total_deadline:
                if not q_casted and self.ultimate_available() and self.task.is_char_at_index(self.index):
                    self.task._combat_settle.time = None
                    self.click_ultimate()
                    q_casted = True
                    na_start = time.time()

                self.click()
                self.sleep(0.1)
                self.task.next_frame()

                now = time.time()
                if now - last_log >= 2:
                    self.logger.debug(f"chain_e_q_6s NA running, elapsed={now - total_start:.1f}s")
                    last_log = now

            if time.time() >= total_deadline:
                break

            hotori_key = self._get_char_key("HotoriChain")
            hotori_ok = False
            if hotori_key:
                self.task.send_key(hotori_key)

            if hotori:
                switch_deadline = time.time() + 1.0
                while (not self.task.is_char_at_index(hotori.index)
                       and time.time() < switch_deadline
                       and time.time() < total_deadline):
                    self.click()
                    self.sleep(0.01)
                if self.task.is_char_at_index(hotori.index):
                    hotori_ok = True

            if time.time() >= total_deadline:
                break

            if hotori_ok:
                hotori_start = time.time()
                while time.time() - hotori_start < 0.8 and time.time() < total_deadline:
                    hotori.click()
                    hotori.sleep(0.1)
                    self.task.next_frame()

                    now = time.time()
                    if now - last_log >= 2:
                        self.logger.debug(f"chain_e_q_6s NA running, elapsed={now - total_start:.1f}s")
                        last_log = now

            if time.time() >= total_deadline or i >= 2:
                break

            nanally_key = self._get_char_key("NanallyChain")
            if nanally_key:
                self.task.send_key(nanally_key)

            switch_deadline = time.time() + 1.0
            while (not self.task.is_char_at_index(self.index)
                   and time.time() < switch_deadline
                   and time.time() < total_deadline):
                self.click()
                self.sleep(0.01)

        self.task.chain_executor.step_complete()
        self._send_chain_key()
        self.switch_next_char()

    def chain_intro_e_q_10s_swap(self):
        if self.has_intro:
            start = time.time()
            while time.time() - start < self.INTRO_MOTION_FREEZE_DURATION:
                self.click()
                if self.skill_available():
                    break
                self.sleep(0.1)

        total_deadline = time.time() + 12
        e_casted = False
        e_cast_time = 0
        hotori = next((c for c in self.task.chars if c.__class__.__name__ == "HotoriChain"), None)

        while time.time() + 1.5 < total_deadline:
            na_start = time.time()
            while time.time() - na_start < 1.2 and time.time() < total_deadline:
                self.click()
                if not e_casted and self.skill_available() and self.task.is_char_at_index(self.index):
                    self.task.suppress_dodge()
                    clicked, _, _ = self.click_skill()
                    self.task.unsuppress_dodge()
                    if clicked:
                        e_casted = True
                        e_cast_time = time.time()
                if self.ultimate_available() and self.task.is_char_at_index(self.index) and (
                    not e_casted or time.time() - e_cast_time > 0.3
                ):
                    q_anim_start = time.time()
                    self.task._combat_settle.time = None
                    self.click_ultimate()
                    total_deadline += time.time() - q_anim_start
                self.sleep(0.1)

            if time.time() >= total_deadline:
                break

            hotori_key = self._get_char_key("HotoriChain")
            hotori_ok = False
            if hotori_key:
                self.task.send_key(hotori_key)

            if hotori:
                switch_deadline = time.time() + 1.0
                while (not self.task.is_char_at_index(hotori.index)
                       and time.time() < switch_deadline
                       and time.time() < total_deadline):
                    self.click()
                    self.sleep(0.01)
                if self.task.is_char_at_index(hotori.index):
                    hotori_ok = True

            if time.time() >= total_deadline:
                break

            if hotori_ok:
                hotori_start = time.time()
                while time.time() - hotori_start < 0.8 and time.time() < total_deadline:
                    hotori.click()
                    hotori.sleep(0.1)
                    self.task.next_frame()

            if time.time() + 2.5 >= total_deadline:
                break

            nanally_key = self._get_char_key("NanallyChain")
            if nanally_key:
                self.task.send_key(nanally_key)

            switch_deadline = time.time() + 1.0
            while (not self.task.is_char_at_index(self.index)
                   and time.time() < switch_deadline
                   and time.time() < total_deadline):
                self.click()
                self.sleep(0.01)

        self.task.chain_executor.step_complete()
        self._send_chain_key()
        self.switch_next_char()
