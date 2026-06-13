# ============================================================================
# Audio capture sources for the fingerprint detector.
#
# Each source delivers mono float32 chunks at 48 kHz (matcher.ANALYSIS_SAMPLE_RATE)
# via a bounded queue filled by an internal producer thread.
#
#   - ProcessLoopbackSource: WASAPI per-process loopback (captures ONLY the
#     game's audio, like NTE-Auto-Skill-Combo). Primary.
#   - SystemLoopbackSource:  system-wide loopback via the `soundcard` library.
#     Fallback when per-process capture is unavailable or fails to start.
#
# `create_capture_source` builds the requested source and transparently falls
# back to system loopback.
# ============================================================================
from __future__ import annotations

from typing import Optional

from ok import Logger

from src.sound_trigger.capture.base import AudioCaptureSource

logger = Logger.get_logger(__name__)

MODE_PROCESS = "process"
MODE_SYSTEM = "system"


def create_capture_source(
    mode: str = MODE_PROCESS,
    *,
    process_name: Optional[str] = None,
) -> AudioCaptureSource:
    """Build a (not-yet-started) capture source for `mode`.

    The caller invokes `.start()`; if it returns False it may build a
    `MODE_SYSTEM` source instead — the listener owns the fallback decision.
    """
    if mode == MODE_PROCESS and process_name:
        from src.sound_trigger.capture.process_loopback import ProcessLoopbackSource

        return ProcessLoopbackSource(process_name=process_name)

    from src.sound_trigger.capture.system_loopback import SystemLoopbackSource

    return SystemLoopbackSource()


__all__ = [
    "AudioCaptureSource",
    "create_capture_source",
    "MODE_PROCESS",
    "MODE_SYSTEM",
]
