class ChainExecutor:
    def __init__(self, task):
        self.task = task
        self.steps = []
        self.current_index = 0
        self.active = False
        self._builder = None
        self._pending_anchor = None
        self._chain_start_time = 0
        self._last_step_time = 0

    @property
    def target(self):
        if not self.active or self.current_index >= len(self.steps):
            return None, None
        char, method = self.steps[self.current_index]
        if char is not None and 0 <= char.index < len(self.task.chars):
            char = self.task.chars[char.index] or char
        return char, method

    def reset(self):
        self.active = False
        self.steps = []
        self.current_index = 0
        self._builder = None
        self._pending_anchor = None

    def loop(self, builder):
        import time
        self._builder = builder
        steps = builder()
        self._chain_start_time = time.time()
        self._last_step_time = time.time()
        self._start(steps)
        first_char, first_method = self.steps[0]
        current_char = self.task.get_current_char(raise_exception=False)
        if current_char != first_char:
            self.task.switch_to_char(first_char)
        self.task.log_info(f"chain step 0: {first_char.__class__.__name__}.{first_method} will be executed by perform")


    def _start(self, steps):
        self.steps = steps
        self.current_index = 0
        self.active = True
        first_char, first_method = steps[0]
        first_char._chain_method = first_method
        names = [(c.__class__.__name__, m) for c, m in steps]
        self.task.log_info(f"start_chain with {len(steps)} steps: {names}")

    def step_complete(self):
        import time
        now = time.time()
        if self.active and self._last_step_time > 0:
            wait_time = now - self._last_step_time
            if wait_time > 0.1:
                self.task.add_freeze_duration(self._last_step_time, wait_time)
        self._last_step_time = now

        self.current_index += 1
        hotori = next((c for c in self.task.chars if c is not None and c.__class__.__name__ == "HotoriChain"), None)

        if hotori and getattr(hotori, 'team_skill_window_start', 0) > 0:
            hotori.update_team_skill_records()

        if self.current_index >= len(self.steps):
            if self._builder:
                next_steps = self._builder()
                if next_steps:
                    self.task.log_info("chain cycle complete, building next")
                    self._start(next_steps)
                    return
                self._builder = None
            self.active = False
            self.task.log_info("chain finished, waiting for anchor restart")
            return
        next_char, next_method = self.steps[self.current_index]
        next_char._chain_method = next_method
        self.task.log_info(
            f"chain step {self.current_index}: -> {next_char.__class__.__name__}.{next_method}"
        )
