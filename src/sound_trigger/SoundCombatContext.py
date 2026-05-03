import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from ok import Logger

from src.sound_trigger.DodgeCounterTrigger import DodgeCounterTrigger
from src.sound_trigger.SoundListener import SoundListener

logger = Logger.get_logger(__name__)


class SoundCombatContext:
    _instance = None
    _lock = threading.Lock()
    _combat_interrupt = threading.Event()
    _action_complete = threading.Event()
    _last_trigger_time = 0.0

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized"):
            return
        self._initialized = True

        self._listener: Optional[SoundListener] = None
        self._trigger: Optional[DodgeCounterTrigger] = None
        self._thread_pool: Optional[ThreadPoolExecutor] = None
        self._context_lock = threading.RLock()
        self._is_active = False
        self._config = {}
        self._enable_sound_trigger = True
        self._pending_task = None
        self._pending_config = None

    @classmethod
    def enter_priority(cls):
        cls._action_complete.clear()
        cls._combat_interrupt.set()
        cls._last_trigger_time = time.time()
        logger.info("SoundCombatContext: Combat interrupt signal sent, main thread should pause")

        if not hasattr(cls, '_clear_seq'):
            cls._clear_seq = 0
        cls._clear_seq += 1
        current_seq = cls._clear_seq

        def delayed_clear(seq):
            time.sleep(0.8)
            if cls._clear_seq == seq:
                cls._combat_interrupt.clear()
                cls._action_complete.set()
        threading.Thread(target=delayed_clear, args=(current_seq,), daemon=True).start()

    @classmethod
    def is_in_sound_action_window(cls, window=1.5):
        return time.time() - cls._last_trigger_time < window

    @classmethod
    def exit_priority(cls):
        cls._action_complete.set()
        logger.info("SoundCombatContext: Action complete")

    @classmethod
    def exit_priority_no_wait(cls):
        cls.exit_priority()

    @classmethod
    def should_interrupt_combat(cls):
        return cls._combat_interrupt.is_set()

    @classmethod
    def wait_for_resume(cls):
        if not cls._combat_interrupt.is_set():
            return
        logger.info("Main thread paused, waiting for sound action to complete...")
        while cls._combat_interrupt.is_set():
            time.sleep(0.01)
        logger.info("Main thread resumed")

    def setup(
        self,
        task,
        enable_sound_trigger: bool = True,
        sample_path: str = "./assets/sounds/dodge.wav",
        counter_attack_sample_path: str = "./assets/sounds/counter.wav",
        threshold: float = 0.13,
        counter_attack_threshold: float = 0.12,
        **kwargs,
    ):
        with self._context_lock:
            if self._is_active:
                return

            if self._pending_config is not None:
                enable_sound_trigger, threshold, counter_attack_threshold = self._pending_config

            self._enable_sound_trigger = enable_sound_trigger

            if not (0.0 <= threshold <= 1.0):
                raise ValueError("threshold must be between 0.0 and 1.0")
            if not (0.0 <= counter_attack_threshold <= 1.0):
                raise ValueError("counter_attack_threshold must be between 0.0 and 1.0")

            self._config = {
                "sample_path": sample_path,
                "counter_attack_sample_path": counter_attack_sample_path,
                "threshold": threshold,
                "counter_attack_threshold": counter_attack_threshold,
            }

            self._listener = SoundListener(
                sample_path=sample_path,
                counter_attack_sample_path=counter_attack_sample_path,
                threshold=threshold,
                counter_attack_threshold=counter_attack_threshold,
            )

            self._trigger = DodgeCounterTrigger(
                task=self._pending_task if self._pending_task is not None else task,
            )

            self._listener.on_dodge_triggered = self._on_dodge_triggered
            self._listener.on_counter_triggered = self._on_counter_triggered
            self._listener.is_computation_required = self._is_computation_required

            self._thread_pool = ThreadPoolExecutor(
                max_workers=2, thread_name_prefix="SoundCombat"
            )

            self._is_active = True
            logger.info("SoundCombatContext initialized")

    def enter(self):
        if not self._is_active or not self._listener:
            return False

        try:
            self._listener.start()
            logger.info("SoundCombatContext entered - listener started")
            return True
        except Exception as e:
            logger.error(f"Failed to enter SoundCombatContext: {e}")
            return False

    def exit(self):
        with self._context_lock:
            if not self._is_active:
                return

            try:
                if self._listener:
                    self._listener.stop()
                    self._listener = None
                if self._thread_pool:
                    self._thread_pool.shutdown(wait=False, cancel_futures=True)
                    self._thread_pool = None
                self._trigger = None
                self._is_active = False
                logger.info("SoundCombatContext exited and completely cleared")
            except Exception as e:
                logger.error(f"Error exiting SoundCombatContext: {e}")

    def _on_dodge_triggered(self):
        if self._trigger is None or self._trigger.task is None or self._trigger.task.paused:
            return
        if self._thread_pool is None:
            return
        try:
            self._thread_pool.submit(self._trigger.execute_dodge)
        except Exception as e:
            logger.error(f"Failed to submit dodge task: {e}")

    def _on_counter_triggered(self):
        if self._trigger is None or self._trigger.task is None or self._trigger.task.paused:
            return
        if self._thread_pool is None:
            return
        try:
            self._thread_pool.submit(self._trigger.execute_counter_attack)
        except Exception as e:
            logger.error(f"Failed to submit counter task: {e}")

    def update_task(self, task):
        with self._context_lock:
            self._pending_task = task
            if self._trigger:
                self._trigger.task = task

    def update_config(self, enable: bool, dodge_threshold: float, counter_threshold: float):
        with self._context_lock:
            self._pending_config = (enable, dodge_threshold, counter_threshold)
            self._enable_sound_trigger = enable
            if self._listener:
                self._listener.threshold = dodge_threshold
                self._listener.counter_attack_threshold = counter_threshold

    def _is_computation_required(self) -> bool:
        if not self._enable_sound_trigger:
            return False
        trigger = self._trigger
        if not trigger:
            return False
        task = trigger.task
        if not task:
            return False
        return not task.paused

    @property
    def is_active(self) -> bool:
        return self._is_active

    @property
    def listener(self) -> Optional[SoundListener]:
        return self._listener

    @property
    def trigger(self) -> Optional[DodgeCounterTrigger]:
        return self._trigger

    @property
    def thread_pool(self) -> Optional[ThreadPoolExecutor]:
        return self._thread_pool

    def shutdown(self):
        with self._context_lock:
            if not self._is_active:
                return

            self.exit()

            if self._thread_pool:
                self._thread_pool.shutdown(wait=False, cancel_futures=True)
                self._thread_pool = None

            self._listener = None
            self._trigger = None
            self._is_active = False
            self._config = {}
            self._pending_task = None
            self._pending_config = None
            logger.info("SoundCombatContext shutdown complete")

    def __del__(self):
        if self._is_active:
            self.shutdown()
