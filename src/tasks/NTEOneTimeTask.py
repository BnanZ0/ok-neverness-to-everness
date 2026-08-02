from ok import PostMessageInteraction, TaskDisabledException
from ok.device.intercation import PynputInteraction


class NTEOneTimeTask:

    def run(self, *args, **kwargs):
        if not self.scene.game_capture_ready() or not self.executor.connected():
            self.log_warning("Game launch or capture initialization is incomplete; skipping task")
            raise TaskDisabledException("Game capture is not ready")
        if isinstance(self.executor.interaction, PostMessageInteraction):
            self.executor.interaction.activate()
        elif isinstance(self.executor.interaction, PynputInteraction):
            self.bring_to_front()
        self.sleep(0.5)
        self.set_check_monthly_card()
        return super().run(*args, **kwargs)
