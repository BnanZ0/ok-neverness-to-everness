# ============================================================================
# Common base for audio capture sources.
#
# A source runs a producer thread that pushes mono float32 @48kHz chunks into a
# bounded queue. `start()` blocks briefly until the source confirms it is live
# (or fails), so the listener can decide whether to fall back to another source.
# ============================================================================
from __future__ import annotations

import queue
import threading
import time
from abc import ABC, abstractmethod
from typing import Callable, Optional

import numpy as np
from ok import Logger

from src.sound_trigger.fingerprint.matcher import ANALYSIS_SAMPLE_RATE

logger = Logger.get_logger(__name__)

PushFn = Callable[[np.ndarray], None]


class AudioCaptureSource(ABC):
    sample_rate = ANALYSIS_SAMPLE_RATE

    def __init__(self, queue_max: int = 64):
        self._queue: "queue.Queue[np.ndarray]" = queue.Queue(maxsize=queue_max)
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._failed = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._error: Optional[BaseException] = None

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def _produce(self, push: PushFn) -> None:
        """Capture loop: push(chunk) mono float32 @48kHz until `self._stop` set.

        Call `self._mark_ready()` once capture is confirmed live. Raising before
        `_mark_ready()` signals a fatal init failure and triggers fallback.
        """

    # -- lifecycle ---------------------------------------------------------

    def start(self, ready_timeout: float = 5.0) -> bool:
        if self._thread is not None:
            return self._ready.is_set()
        self._thread = threading.Thread(
            target=self._run, name=f"AudioCapture-{self.name}", daemon=True
        )
        self._thread.start()

        deadline = time.time() + ready_timeout
        while time.time() < deadline:
            if self._ready.is_set():
                return True
            if self._failed.is_set():
                return False
            if self._stop.is_set():
                # stop() was requested while we were still coming up.
                return self._ready.is_set()
            time.sleep(0.02)
        return self._ready.is_set()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def read(self, timeout: float = 0.5) -> Optional[np.ndarray]:
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def error(self) -> Optional[BaseException]:
        return self._error

    # -- internals ---------------------------------------------------------

    def _mark_ready(self) -> None:
        self._ready.set()

    def _push(self, chunk: np.ndarray) -> None:
        if chunk is None or len(chunk) == 0:
            return
        chunk = np.ascontiguousarray(chunk, dtype=np.float32)
        # Bounded latency: keep the NEWEST chunk, dropping oldest until it fits.
        # Single producer per source, so this terminates quickly.
        while True:
            try:
                self._queue.put_nowait(chunk)
                return
            except queue.Full:
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    # Consumer drained concurrently; a retry will now succeed.
                    pass

    def _run(self) -> None:
        try:
            self._produce(self._push)
        except BaseException as exc:  # noqa: BLE001 - report and fall back
            self._error = exc
            logger.error(f"Audio capture source '{self.name}' failed: {exc}")
        finally:
            # Unblock any start() still waiting on readiness.
            self._failed.set()
