# ============================================================================
# System-wide loopback capture via the `soundcard` library (fallback source).
#
# Device-resolution logic (strict loopback match -> name match -> fuzzy match
# -> soundcard fuzzy fallback) and default-speaker change handling are ported
# from the existing SoundListener so behaviour matches the legacy engine; the
# only differences are: capture at 48 kHz, deliver mono float32 chunks, and run
# behind the AudioCaptureSource producer interface.
# ============================================================================
from __future__ import annotations

import time
import warnings

import numpy as np
import soundcard as sc
from ok import Logger

from src.sound_trigger.capture.base import AudioCaptureSource, PushFn
from src.sound_trigger.fingerprint.matcher import ANALYSIS_SAMPLE_RATE

warnings.filterwarnings("ignore", message="data discontinuity in recording")

logger = Logger.get_logger(__name__)


class SystemLoopbackSource(AudioCaptureSource):
    used_sr = ANALYSIS_SAMPLE_RATE
    used_channel = 2
    # ~10 ms blocks keep capture latency low and align well with the detector's
    # HOP-sized evaluation cadence.
    chunk_frames = ANALYSIS_SAMPLE_RATE // 100

    @property
    def name(self) -> str:
        return "system-loopback"

    def _produce(self, push: PushFn) -> None:
        logger.info("Initializing system audio loopback device...")
        current_speaker_name = None

        while not self._stop.is_set():
            default_speaker = sc.default_speaker()
            default_speaker_name = str(default_speaker.name)
            if default_speaker_name != current_speaker_name:
                logger.info(f"Default speaker: {default_speaker_name}")
                current_speaker_name = default_speaker_name

            loopback = self._get_loopback_microphone(default_speaker)
            if loopback is None:
                logger.warning(
                    "No strict loopback device found for default speaker, "
                    f"falling back to soundcard fuzzy matching: {default_speaker_name}"
                )
                try:
                    loopback = sc.get_microphone(
                        id=default_speaker_name, include_loopback=True
                    )
                except Exception as exc:
                    logger.warning(f"Fallback audio device lookup failed: {exc}")
                    if self._stop.wait(1.0):
                        return
                    continue

            logger.info(f"Using loopback device: {loopback.name}")
            recorder = loopback.recorder(
                samplerate=self.used_sr, channels=self.used_channel
            )
            with recorder as audio_recorder:
                logger.info("System loopback capture started")
                self._mark_ready()
                while not self._stop.is_set():
                    if str(sc.default_speaker().name) != current_speaker_name:
                        logger.info("Default speaker changed, switching loopback device")
                        break
                    data = audio_recorder.record(numframes=self.chunk_frames)
                    push(_to_mono_float32(data))

    @staticmethod
    def _get_loopback_microphone(speaker):
        speaker_id = getattr(speaker, "id", None)
        speaker_name = str(getattr(speaker, "name", ""))

        loopbacks = [
            microphone
            for microphone in sc.all_microphones(include_loopback=True)
            if getattr(microphone, "isloopback", False)
        ]

        for microphone in loopbacks:
            if getattr(microphone, "id", None) == speaker_id:
                return microphone

        for microphone in loopbacks:
            if str(getattr(microphone, "name", "")) == speaker_name:
                return microphone

        normalized_speaker_name = SystemLoopbackSource._normalize_device_name(speaker_name)
        for microphone in loopbacks:
            normalized_microphone_name = SystemLoopbackSource._normalize_device_name(
                str(getattr(microphone, "name", ""))
            )
            if normalized_speaker_name and (
                normalized_speaker_name in normalized_microphone_name
                or normalized_microphone_name in normalized_speaker_name
            ):
                return microphone

        return None

    @staticmethod
    def _normalize_device_name(device_name: str) -> str:
        normalized_name = device_name.casefold().strip()
        for prefix in ("monitor of ",):
            if normalized_name.startswith(prefix):
                normalized_name = normalized_name[len(prefix) :]
        return normalized_name


def _to_mono_float32(samples: np.ndarray) -> np.ndarray:
    array = np.asarray(samples, dtype=np.float32)
    if array.ndim == 2:
        array = array.mean(axis=1)
    return np.ascontiguousarray(array, dtype=np.float32)
