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
        execute_action: Optional[Callable] = None,
        counter_execute_action: Optional[Callable] = None,
    ):
        self.task = task
        self.execute_action = execute_action or self._default_dodge_action
        self.counter_execute_action = counter_execute_action or self._default_counter_action

        self._is_executing = False
        self._execute_lock = threading.Lock()
        self._last_dodge_time = 0.0
        self._last_counter_time = 0.0
        self._min_dodge_interval = 0.5
        self._min_counter_interval = 1.0

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
            self.execute_action()
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
            self.counter_execute_action()
            self._last_counter_time = now
            logger.info(f"Counter attack executed successfully at {now:.3f}")
        except Exception as e:
            logger.error("Counter execution error", e)
        finally:
            self._is_executing = False

    def _default_dodge_action(self):
        logger.info("Dodge sequence: Left Shift")
        self.task.send_key("lshift")
        time.sleep(0.02)
        self.task.send_key("lshift")
        time.sleep(0.02)

    def _default_counter_action(self):
        logger.info("Counter attack sequence: Left mouse")
        self.task.click()
        time.sleep(0.02)
