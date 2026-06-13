# ============================================================================
# Fingerprint-based sound listener (drop-in replacement for SoundListener).
#
# Exposes the SAME public surface that SoundCombatContext relies on:
#   __init__(sample_path, counter_attack_sample_path, threshold,
#            counter_attack_threshold, ...)
#   .start() / .stop()
#   .on_dodge_triggered / .on_counter_triggered / .is_computation_required
#   .threshold / .counter_attack_threshold
#
# Internally it runs a WASAPI per-process capture (falling back to system
# loopback) and feeds the stream to a dodge template BANK (NTE-ASC's proven
# dodge.wav + dodge3.wav) plus a counter detector, routing accepted matches to
# the corresponding callback.
# ============================================================================
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import List, Optional, Tuple

from ok import Logger

from src.sound_trigger.capture import MODE_PROCESS, MODE_SYSTEM, create_capture_source
from src.sound_trigger.fingerprint.runtime import FingerprintDetector
from src.sound_trigger.fingerprint.templates import (
    BANK_SUBDIR,
    COUNTER_ENABLED,
    FingerprintTemplateConfig,
    counter_config,
    dodge_bank_configs,
    load_cached_template,
)

Entry = Tuple[FingerprintTemplateConfig, FingerprintDetector]

logger = Logger.get_logger(__name__)

DEFAULT_GAME_PROCESS = "HTGame.exe"


class FingerprintSoundListener:
    log_interval_seconds = 10.0

    def __init__(
        self,
        sample_path: str,
        counter_attack_sample_path: str,
        threshold: float = 0.13,
        counter_attack_threshold: float = 0.12,
        *,
        capture_mode: str = MODE_PROCESS,
        process_name: str = DEFAULT_GAME_PROCESS,
        dodge_confidence: Optional[float] = None,
        counter_confidence: Optional[float] = None,
        **_ignored,
    ):
        self.sample_path = sample_path
        self.counter_attack_sample_path = counter_attack_sample_path
        # Kept for interface compatibility with the legacy listener; the
        # fingerprint engine gates on confidence (see dodge/counter_confidence).
        self.threshold = threshold
        self.counter_attack_threshold = counter_attack_threshold

        self.capture_mode = capture_mode
        self.process_name = process_name or DEFAULT_GAME_PROCESS

        self.on_dodge_triggered = None
        self.on_counter_triggered = None
        self.is_computation_required = None

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._source = None
        self._source_is_process = False
        self._fallback_to_system = False
        self._needs_reset = False
        self._last_log = 0.0

        # Dodge uses NTE-ASC's bundled template bank under assets/sounds/fingerprint/,
        # resolved relative to the (legacy) dodge sample path's directory.
        self._bank_dir = Path(sample_path).parent / BANK_SUBDIR
        self._dodge_entries: List[Entry] = []
        self._counter_entry: Optional[Entry] = None
        self._load_detectors(dodge_confidence, counter_confidence)

    # -- template / detector setup ----------------------------------------

    def _load_detectors(
        self, dodge_confidence: Optional[float], counter_confidence: Optional[float]
    ) -> None:
        for cfg in dodge_bank_configs():
            wav = self._bank_dir / cfg.wav
            try:
                detector = self._build_detector(wav, cfg, self._on_dodge, dodge_confidence)
                self._dodge_entries.append((cfg, detector))
            except Exception as exc:
                logger.error(f"Failed to load dodge fingerprint template {wav}: {exc}")
        if not self._dodge_entries:
            logger.error("No dodge fingerprint templates loaded")

        if self.counter_attack_sample_path and COUNTER_ENABLED:
            cfg = counter_config()
            try:
                detector = self._build_detector(
                    self.counter_attack_sample_path, cfg, self._on_counter, counter_confidence
                )
                self._counter_entry = (cfg, detector)
            except Exception as exc:
                logger.error(f"Failed to load counter fingerprint template: {exc}")
        elif self.counter_attack_sample_path:
            logger.info(
                "Counter fingerprint detection disabled (template not yet calibrated); "
                "dodge bank + 'Dodge All Attacks' cover attack avoidance"
            )

    @staticmethod
    def _build_detector(
        wav_path,
        config: FingerprintTemplateConfig,
        on_detected,
        confidence_override: Optional[float],
    ) -> FingerprintDetector:
        template = load_cached_template(wav_path, config.tuning)
        threshold = config.threshold if confidence_override is None else float(confidence_override)
        rearm = _rearm_for(config, threshold)
        return FingerprintDetector(
            template,
            config.tuning,
            threshold=threshold,
            rearm=rearm,
            cooldown_seconds=config.cooldown_seconds,
            on_detected=on_detected,
            eval_step_samples=config.eval_step_samples,
            label=f"{config.name}:{Path(str(wav_path)).stem}",
        )

    def apply_confidence(
        self, dodge_confidence: Optional[float], counter_confidence: Optional[float]
    ) -> None:
        if dodge_confidence is not None:
            for cfg, detector in self._dodge_entries:
                detector.threshold = float(dodge_confidence)
                detector.rearm = _rearm_for(cfg, float(dodge_confidence))
        if counter_confidence is not None and self._counter_entry is not None:
            cfg, detector = self._counter_entry
            detector.threshold = float(counter_confidence)
            detector.rearm = _rearm_for(cfg, float(counter_confidence))

    # -- detection callbacks ----------------------------------------------

    def _on_dodge(self, confidence: float) -> None:
        logger.info(f"Dodge TRIGGERED! confidence: {confidence:.1f}")
        if self.on_dodge_triggered:
            self.on_dodge_triggered()

    def _on_counter(self, confidence: float) -> None:
        logger.info(f"Counter attack TRIGGERED! confidence: {confidence:.1f}")
        if self.on_counter_triggered:
            self.on_counter_triggered()

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        if self._running:
            logger.warning("FingerprintSoundListener already running")
            return
        if not self._dodge_entries and self._counter_entry is None:
            logger.error("No fingerprint templates loaded; listener will not start")
            return
        self._running = True
        self._thread = threading.Thread(target=self._consume_loop, daemon=True)
        self._thread.start()
        logger.info("FingerprintSoundListener started successfully")

    def stop(self) -> None:
        logger.info(f"FingerprintSoundListener stop called, running: {self._running}")
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._source is not None:
            self._source.stop()
            self._source = None
        logger.info("FingerprintSoundListener stopped")

    # -- capture loop ------------------------------------------------------

    def _ensure_source(self):
        if self._source is not None and self._source.is_alive():
            return self._source

        if self._source is not None:
            # The current source died (its producer thread exited unexpectedly).
            # A per-process source that dies means activation genuinely failed,
            # so pin to system loopback for the rest of the session.
            if self._source_is_process:
                logger.warning(
                    "Per-process capture stopped unexpectedly; "
                    "falling back to system loopback for this session"
                )
                self._fallback_to_system = True
            self._source.stop()
            self._source = None

        want_process = self.capture_mode == MODE_PROCESS and not self._fallback_to_system
        if want_process:
            source = create_capture_source(MODE_PROCESS, process_name=self.process_name)
            # Register before start() so a concurrent stop() can signal it and
            # start()'s readiness wait returns promptly.
            self._source = source
            self._source_is_process = True
            if source.start():
                logger.info(f"Using audio capture source: {source.name}")
                self._needs_reset = True
                return source
            logger.warning(
                f"Per-process capture unavailable ({source.error or 'no signal'}); "
                "falling back to system loopback"
            )
            source.stop()
            self._source = None
            self._fallback_to_system = True

        source = create_capture_source(MODE_SYSTEM)
        self._source = source
        self._source_is_process = False
        if source.start():
            logger.info(f"Using audio capture source: {source.name}")
            self._needs_reset = True
            return source

        logger.error("No audio capture source could be started")
        source.stop()
        self._source = None
        return None

    def _consume_loop(self) -> None:
        try:
            while self._running:
                source = self._ensure_source()
                if source is None:
                    if self._stop_wait(0.5):
                        return
                    continue

                chunk = source.read(timeout=0.2)
                if chunk is None:
                    continue

                if self.is_computation_required and not self.is_computation_required():
                    self._needs_reset = True
                    continue

                if self._needs_reset:
                    self._reset_detectors()
                    self._needs_reset = False

                for _, detector in self._dodge_entries:
                    detector.feed(chunk)
                if self._counter_entry is not None:
                    self._counter_entry[1].feed(chunk)
        except Exception as exc:
            logger.error("FingerprintSoundListener consume loop error", exc)
        finally:
            self._running = False
            logger.info("Fingerprint audio listener stopped")

    def _reset_detectors(self) -> None:
        for _, detector in self._dodge_entries:
            detector.reset()
        if self._counter_entry is not None:
            self._counter_entry[1].reset()

    def _stop_wait(self, seconds: float) -> bool:
        deadline = time.time() + seconds
        while self._running and time.time() < deadline:
            time.sleep(0.05)
        return not self._running


def _rearm_for(config: FingerprintTemplateConfig, threshold: float) -> float:
    gap = max(0.0, config.threshold - config.rearm)
    return max(0.0, threshold - gap)
