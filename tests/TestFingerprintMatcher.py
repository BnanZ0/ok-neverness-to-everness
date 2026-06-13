"""Tests for the spectral-fingerprint dodge/counter detection engine.

Self-contained: needs only numpy + scipy and ok-nte's own dodge/counter WAVs.
Does not import the `ok` framework or the capture/listener layers, so it runs in
a minimal environment.
"""
import unittest
from pathlib import Path

import numpy as np

from src.sound_trigger.fingerprint import matcher as fp
from src.sound_trigger.fingerprint.runtime import FingerprintDetector
from src.sound_trigger.fingerprint.templates import (
    BANK_SUBDIR,
    COUNTER,
    COUNTER_ENABLED,
    DODGE,
    counter_config,
    dodge_bank_configs,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DODGE_WAV = REPO_ROOT / "assets" / "sounds" / "dodge.wav"
COUNTER_WAV = REPO_ROOT / "assets" / "sounds" / "counter.wav"
BANK_DIR = REPO_ROOT / "assets" / "sounds" / BANK_SUBDIR

ACCEPT_THRESHOLD = 79.5
ACCEPT_COOLDOWN = 0.05


class TestTemplateLoading(unittest.TestCase):
    def test_wavs_exist(self):
        self.assertTrue(DODGE_WAV.exists(), DODGE_WAV)
        self.assertTrue(COUNTER_WAV.exists(), COUNTER_WAV)

    def test_load_template_produces_fingerprint(self):
        template = fp.load_template(DODGE_WAV, fp.Tuning())
        self.assertGreater(len(template.peaks), 0)
        self.assertGreater(len(template.samples), fp.FFT_SIZE)
        self.assertIsNotNone(template.verifier)
        # Verifier is unit-norm whitened.
        self.assertAlmostEqual(float(np.linalg.norm(template.verifier)), 1.0, places=4)


class TestMatcherSelfMatch(unittest.TestCase):
    """A template's own audio must match itself with high, verified confidence."""

    def _self_match(self, wav: Path):
        tuning = fp.Tuning()
        template = fp.load_template(wav, tuning)
        # The full trimmed source contains the template prefix at the start.
        stream = fp.trim_silence(fp.load_analysis_samples(wav))
        candidates = fp.evaluate(stream, fp.extract_peaks(stream), template, tuning)
        self.assertTrue(candidates, f"no candidates for {wav.name}")
        top = candidates[0]
        self.assertTrue(top.verified, f"{wav.name} top candidate not verified: {top}")
        self.assertGreaterEqual(top.confidence, ACCEPT_THRESHOLD)
        # Best alignment should be at/near the start of the stream.
        self.assertLess(top.best_start_sample, 4 * fp.HOP_SIZE)

    def test_dodge_self_match(self):
        self._self_match(DODGE_WAV)

    def test_counter_self_match(self):
        self._self_match(COUNTER_WAV)


class TestMatcherNegative(unittest.TestCase):
    def test_white_noise_no_match(self):
        tuning = fp.Tuning()
        template = fp.load_template(DODGE_WAV, tuning)
        rng = np.random.default_rng(1234)
        noise = (rng.standard_normal(fp.ANALYSIS_SAMPLE_RATE) * 0.1).astype(np.float32)
        candidates = fp.evaluate(noise, fp.extract_peaks(noise), template, tuning)
        accepted = fp.select_matches(candidates, ACCEPT_THRESHOLD, ACCEPT_COOLDOWN)
        self.assertEqual(accepted, [], "white noise produced an accepted match")

    def test_silence_no_match(self):
        tuning = fp.Tuning()
        template = fp.load_template(DODGE_WAV, tuning)
        silence = np.zeros(fp.ANALYSIS_SAMPLE_RATE, dtype=np.float32)
        candidates = fp.evaluate(silence, fp.extract_peaks(silence), template, tuning)
        accepted = fp.select_matches(candidates, ACCEPT_THRESHOLD, ACCEPT_COOLDOWN)
        self.assertEqual(accepted, [])


class TestStreamingRuntime(unittest.TestCase):
    def _make_detector(self, wav: Path, fired: list):
        tuning = fp.Tuning()
        template = fp.load_template(wav, tuning)
        return FingerprintDetector(
            template,
            tuning,
            threshold=ACCEPT_THRESHOLD,
            rearm=73.0,
            cooldown_seconds=ACCEPT_COOLDOWN,
            on_detected=lambda conf: fired.append(conf),
            eval_step_samples=fp.HOP_SIZE,
        )

    def _stream_with_one_event(self, wav: Path) -> np.ndarray:
        cue = fp.trim_silence(fp.load_analysis_samples(wav))
        gap = np.zeros(fp.ANALYSIS_SAMPLE_RATE, dtype=np.float32)  # 1s of silence
        return np.concatenate([gap, cue, gap]).astype(np.float32)

    def test_fires_once_for_single_event(self):
        fired = []
        detector = self._make_detector(DODGE_WAV, fired)
        stream = self._stream_with_one_event(DODGE_WAV)
        chunk = fp.HOP_SIZE
        for offset in range(0, len(stream), chunk):
            detector.feed(stream[offset : offset + chunk])
        self.assertEqual(len(fired), 1, f"expected exactly one detection, got {len(fired)}")
        self.assertGreaterEqual(fired[0], ACCEPT_THRESHOLD)

    def test_no_fire_on_silence(self):
        fired = []
        detector = self._make_detector(DODGE_WAV, fired)
        silence = np.zeros(3 * fp.ANALYSIS_SAMPLE_RATE, dtype=np.float32)
        chunk = fp.HOP_SIZE
        for offset in range(0, len(silence), chunk):
            detector.feed(silence[offset : offset + chunk])
        self.assertEqual(fired, [])

    def test_reset_clears_state(self):
        fired = []
        detector = self._make_detector(DODGE_WAV, fired)
        stream = self._stream_with_one_event(DODGE_WAV)
        chunk = fp.HOP_SIZE
        for offset in range(0, len(stream), chunk):
            detector.feed(stream[offset : offset + chunk])
        detector.reset()
        self.assertEqual(detector._window_start_sample, 0)
        self.assertEqual(len(detector._buf), 0)
        # After reset, the same stream fires again.
        fired.clear()
        for offset in range(0, len(stream), chunk):
            detector.feed(stream[offset : offset + chunk])
        self.assertEqual(len(fired), 1)


class TestTemplateConfigs(unittest.TestCase):
    def test_dodge_bank_present(self):
        bank = dodge_bank_configs()
        self.assertEqual(len(bank), 2)
        self.assertEqual({cfg.wav for cfg in bank}, {"dodge.wav", "dodge3.wav"})
        for cfg in bank:
            self.assertEqual(cfg.name, DODGE)
            self.assertGreater(cfg.threshold, cfg.rearm)
            self.assertEqual(cfg.cooldown_seconds, cfg.cooldown_ms / 1000.0)

    def test_counter_config_placeholder(self):
        cfg = counter_config()
        self.assertEqual(cfg.name, COUNTER)
        self.assertIsNone(cfg.wav)
        self.assertGreater(cfg.threshold, cfg.rearm)

    def test_counter_disabled_by_default(self):
        # Counter template is uncalibrated -> must stay off until trained.
        self.assertFalse(COUNTER_ENABLED)


class TestDodgeBank(unittest.TestCase):
    """The bundled NTE-ASC dodge bank loads and self-matches with its v1 tuning."""

    def test_bank_wavs_exist(self):
        for cfg in dodge_bank_configs():
            self.assertTrue((BANK_DIR / cfg.wav).exists(), BANK_DIR / cfg.wav)

    def test_bank_templates_self_match(self):
        for cfg in dodge_bank_configs():
            wav = BANK_DIR / cfg.wav
            template = fp.load_template(wav, cfg.tuning)
            stream = fp.trim_silence(fp.load_analysis_samples(wav))
            candidates = fp.evaluate(stream, fp.extract_peaks(stream), template, cfg.tuning)
            self.assertTrue(candidates, f"no candidates for bank template {cfg.wav}")
            self.assertTrue(candidates[0].verified, f"{cfg.wav} not verified")
            self.assertGreaterEqual(candidates[0].confidence, ACCEPT_THRESHOLD)


class TestActivationStructLayout(unittest.TestCase):
    """ctypes layout of the WASAPI activation params (needs comtypes)."""

    def test_struct_sizes(self):
        try:
            import ctypes

            from src.sound_trigger.capture import process_loopback as pl
        except Exception as exc:  # comtypes/psutil not installed in this env
            self.skipTest(f"capture deps unavailable: {exc}")
        self.assertEqual(ctypes.sizeof(pl.AUDIOCLIENT_ACTIVATION_PARAMS), 12)
        self.assertEqual(ctypes.sizeof(pl.AUDIOCLIENT_PROCESS_LOOPBACK_PARAMS), 8)
        self.assertEqual(pl.AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK, 1)


if __name__ == "__main__":
    unittest.main()
