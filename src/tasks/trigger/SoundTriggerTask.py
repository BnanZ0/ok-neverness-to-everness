from ok import Logger, TriggerTask

from src.sound_trigger.SoundCombatContext import SoundCombatContext
from src.tasks.BaseNTETask import BaseNTETask

logger = Logger.get_logger(__name__)


class SoundTriggerTask(BaseNTETask, TriggerTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.default_config = {"_enabled": False}
        self.trigger_interval = 0.1
        self.name = "声音闪避反击"
        self.description = "未处于自动战斗时, 响应声音闪避或反击"
        self._sound_trigger_allowed = False
        self._sound_config_enabled = True

    def run(self):
        context = SoundCombatContext()
        self._apply_sound_config(context)
        if self._is_onetime_task_running():
            self._sound_trigger_allowed = False
            context.clear_task_if(self)
            return

        if not self._sound_config_enabled:
            self._sound_trigger_allowed = False
            context.clear_task_if(self)
            return

        if self.scene.in_combat():
            self._sound_trigger_allowed = False
            context.clear_task_if(self)
            return

        in_team = self.scene.is_in_team(self.is_in_team)
        self._sound_trigger_allowed = bool(in_team)
        if not in_team:
            context.clear_task_if(self)
            return

        context.update_task(self)
        if context.should_interrupt_combat() and context.is_bound_to(self):
            self.log_info("SoundTriggerTask executing pending sound action")
            context.execute_pending_action()
            context.wait_for_resume()

    def can_sound_trigger(self):
        return (
            self.enabled
            and self._sound_config_enabled
            and self._sound_trigger_allowed
            and not self._is_onetime_task_running()
        )

    def _is_onetime_task_running(self):
        if self.executor.current_task in self.executor.onetime_tasks:
            return self.executor.current_task.running
        return False

    def _apply_sound_config(self, context):
        if not self.sound_config:
            return
        enable = self.sound_config.get("Enable Sound Trigger", True)
        self._sound_config_enabled = bool(enable)
        dodge_all_attacks = self.sound_config.get("Dodge All Attacks", True)
        dodge_thresh = self._clip_threshold(self.sound_config.get("Dodge Threshold"), 0.13)
        counter_thresh = self._clip_threshold(
            self.sound_config.get("Counter Attack Threshold"), 0.12
        )
        context.update_config(enable, dodge_all_attacks, dodge_thresh, counter_thresh)

    @staticmethod
    def _clip_threshold(value, default):
        try:
            value = float(value)
        except (TypeError, ValueError):
            value = default
        return max(0.0, min(1.0, value))
