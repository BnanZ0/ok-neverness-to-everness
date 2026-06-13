# ============================================================================
# Streaming, callback-driven fingerprint detector.
#
# Ported from NTE-Auto-Skill-Combo/scripts/simulate_dodge_runtime.py: the
# arm / re-arm / cooldown state machine and the HOP-aligned rolling analysis
# window are preserved exactly. Restructured from "process a whole pre-recorded
# array" into a live `feed(chunk)` interface that fires `on_detected` the moment
# a verified match is accepted, and uses a numpy ring instead of a deque of
# Python floats for throughput.
# ============================================================================
from __future__ import annotations

from typing import Callable, Optional

import numpy as np

from src.sound_trigger.fingerprint.matcher import (
    ANALYSIS_SAMPLE_RATE,
    FFT_SIZE,
    HASH_TIME_SPAN_FRAMES,
    HOP_SIZE,
    VERIFICATION_LAG_SAMPLES,
    TemplateData,
    Tuning,
    evaluate,
    extract_peaks,
    select_matches,
)


def _round_up(value: int, multiple: int) -> int:
    return ((value + multiple - 1) // multiple) * multiple


class FingerprintDetector:
    """Detects one template in a live mono float32 @48kHz stream.

    Mirrors ``simulate_dodge_runtime.simulate_runtime`` for a single template:
    a rolling window is kept HOP-aligned, evaluated on a fixed sample cadence,
    and ``on_detected(confidence)`` is fired once per accepted match subject to
    the arm/re-arm + cooldown gating.
    """

    def __init__(
        self,
        template: TemplateData,
        tuning: Tuning,
        *,
        threshold: float,
        rearm: float,
        cooldown_seconds: float,
        on_detected: Callable[[float], None],
        eval_step_samples: int = HOP_SIZE,
        label: str = "",
    ):
        self.template = template
        self.tuning = tuning
        self.threshold = threshold
        self.rearm = rearm
        self.cooldown_seconds = cooldown_seconds
        self.on_detected = on_detected
        self.label = label

        self.template_sample_count = len(template.samples)
        # Enough lookahead for the verifier lag search and the trailing FFT
        # frame span, identical to the reference runtime.
        self.analysis_sample_count = (
            self.template_sample_count
            + (2 * VERIFICATION_LAG_SAMPLES)
            + FFT_SIZE
            + (HASH_TIME_SPAN_FRAMES * HOP_SIZE)
        )
        self.eval_step_samples = max(1, int(eval_step_samples))

        self._buf = np.zeros(0, dtype=np.float32)
        self._pending: list = []
        self._stream_sample_count = 0
        self._window_start_sample = 0
        self._armed = True
        self._cooldown_until = -1.0
        self._last_match_sample: Optional[int] = None
        self._samples_since_eval = 0

    def reset(self) -> None:
        self._buf = np.zeros(0, dtype=np.float32)
        self._pending = []
        self._stream_sample_count = 0
        self._window_start_sample = 0
        self._armed = True
        self._cooldown_until = -1.0
        self._last_match_sample = None
        self._samples_since_eval = 0

    def feed(self, chunk: np.ndarray) -> None:
        if chunk is None or len(chunk) == 0:
            return
        # Buffer incoming chunks cheaply (list append); only materialize the
        # numpy window when an evaluation is actually due. Concatenating on every
        # capture packet would be O(window) per packet and dominate CPU.
        self._pending.append(np.ascontiguousarray(chunk, dtype=np.float32))
        n = len(chunk)
        self._stream_sample_count += n
        self._samples_since_eval += n

        # Evaluate on a fixed sample cadence (independent of capture packet size)
        # so the bank stays real-time.
        if self._samples_since_eval >= self.eval_step_samples:
            self._samples_since_eval = 0
            self._materialize_and_trim()
            if len(self._buf) >= self.template_sample_count:
                self._evaluate_once()

    def _materialize_and_trim(self) -> None:
        if self._pending:
            self._buf = np.concatenate((self._buf, *self._pending))
            self._pending = []
        self._trim_window()

    def _trim_window(self) -> None:
        while len(self._buf) > self.analysis_sample_count:
            excess = len(self._buf) - self.analysis_sample_count
            max_drop = max(0, len(self._buf) - self.template_sample_count)
            drop_samples = min(_round_up(excess, HOP_SIZE), max_drop)
            if drop_samples == 0:
                break
            self._buf = self._buf[drop_samples:]
            self._window_start_sample += drop_samples

    def _evaluate_once(self) -> None:
        now = self._stream_sample_count / ANALYSIS_SAMPLE_RATE
        window = self._buf
        candidates = evaluate(window, extract_peaks(window), self.template, self.tuning)
        matches = select_matches(candidates, self.threshold, self.cooldown_seconds)
        confidence = max((match.confidence for match in matches), default=0.0)

        if confidence <= self.rearm:
            self._armed = True

        if matches and self._armed and self._cooldown_until <= now:
            best = max(matches, key=lambda candidate: candidate.confidence)
            match_sample = self._window_start_sample + best.best_start_sample
            if (
                self._last_match_sample is not None
                and abs(self._last_match_sample - match_sample) < self.template_sample_count
            ):
                # Same physical event seen again within one template length.
                self._armed = False
            else:
                self._armed = False
                self._last_match_sample = match_sample
                self._cooldown_until = now + self.cooldown_seconds
                self.on_detected(best.confidence)
        elif matches and self._cooldown_until > now:
            self._armed = False
