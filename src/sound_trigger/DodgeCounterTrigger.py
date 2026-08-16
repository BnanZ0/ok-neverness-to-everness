# ============================================================================
# This file is derived from the ZZZSoundTrigger project.
# Original Author: ImLaoBJie
# Repository: https://github.com/ImLaoBJie/ZZZSoundTrigger
# License: GNU General Public License v3.0 (GPL-3.0)
#
# This file has been modified for integration into the ok-nte project.
# ============================================================================

import threading
import time
from typing import Callable, Optional

from ok import Logger

logger = Logger.get_logger(__name__)

class DodgeCounterTrigger:
    def __init__(
        self,
        task,
        dodge_action: Optional[Callable] = None,
        counter_action: Optional[Callable] = None,
    ):
        self.task = task
        self.set_actions(dodge_action, counter_action)

        self._is_executing = False
        self._execute_lock = threading.Lock()
        self._last_dodge_time = 0.0
        self._last_counter_time = 0.0
        # Min gap between dodges. Log analysis: real attacks can come 0.343s apart
        # (a dodge at that gap was skipped by the old 0.5s floor and the char got hit),
        # while other dodges were >=0.509s apart. 0.3s catches rapid consecutive attacks;
        # an occasional extra dodge on a sound echo is acceptable versus missing a real one.
        self._min_dodge_interval = 0.3
        self._min_counter_interval = 1.0

    def set_actions(
        self,
        dodge_action: Optional[Callable] = None,
        counter_action: Optional[Callable] = None,
    ):
        self.dodge_action = dodge_action or self._default_dodge_action
        self.counter_action = counter_action or self._default_counter_action

    def execute_dodge(self):
        now = time.time()
        if now - self._last_dodge_time < self._min_dodge_interval:
            logger.debug(f"Dodge skipped, too soon: {now - self._last_dodge_time:.3f}s")
            return

        with self._execute_lock:
            if self._is_executing:
                return
            self._is_executing = True

        try:
            logger.info("Executing dodge")
            self.dodge_action()
            self._last_dodge_time = now
            logger.info(f"Dodge executed successfully at {now:.3f}")
        except Exception as e:
            logger.error("Dodge execution error", e)
        finally:
            self._is_executing = False

    def execute_counter_attack(self):
        now = time.time()
        if now - self._last_counter_time < self._min_counter_interval:
            return

        with self._execute_lock:
            if self._is_executing:
                return
            self._is_executing = True

        try:
            logger.info("Executing counter attack")
            self.counter_action()
            self._last_counter_time = now
            logger.info(f"Counter attack executed successfully at {now:.3f}")
        except Exception as e:
            logger.error("Counter execution error", e)
        finally:
            self._is_executing = False

    def _default_dodge_action(self):
        logger.info("Dodge sequence: Left Shift")
        try:
            self.task.send_key_down("d")
            time.sleep(0.02)
            self.task.send_key("lshift")
            time.sleep(0.02)
        finally:
            self.task.send_key_up("d")
            time.sleep(0.02)
        self.task.send_key("lshift")
        time.sleep(0.02)

    def _default_counter_action(self):
        logger.info("Counter attack sequence: Left mouse")
        self.task.click()
        time.sleep(0.02)
