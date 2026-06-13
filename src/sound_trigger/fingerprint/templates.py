# ============================================================================
# Per-template fingerprint tuning.
#
# DODGE uses NTE-Auto-Skill-Combo's proven, field-tested template bank and
# tunings verbatim (its `dodge_template_configs_v1`, the shipping default in
# src/dodge.rs): a two-template bank (dodge.wav + dodge3.wav) bundled under
# assets/sounds/fingerprint/. Because it is the same game cue and the same
# recordings + tunings, dodge needs no re-calibration.
#
# COUNTER (弹反) has no NTE-ASC reference (that project never had a counter
# template), so it reuses ok-nte's counter.wav with a baseline tuning. Its
# acceptance threshold is user-configurable ("Counter Confidence") and can be
# refined with tools/calibrate_fingerprint.py against captured parry audio.
#
# Template fingerprints are cached on disk (load_cached_template) so the peak /
# hash / index computation runs once instead of on every startup.
# ============================================================================
from __future__ import annotations

import hashlib
import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.sound_trigger.fingerprint.matcher import HOP_SIZE, TemplateData, Tuning, load_template

# Logical cue names routed to dodge vs counter-attack actions.
DODGE = "dodge"
COUNTER = "counter"

# Bank-level acceptance, shared across templates (NTE-ASC config.rs defaults).
DEFAULT_CONFIDENCE = 79.5
DEFAULT_REARM = 73.0
DEFAULT_COOLDOWN_MS = 50

# Subdirectory under assets/sounds/ holding the bundled dodge bank WAVs.
BANK_SUBDIR = "fingerprint"

# Samples between window evaluations. Each evaluate() costs ~15-25 ms in pure
# Python and the bank runs one per template, so evaluating every HOP (~10 ms)
# cannot keep real time (the consumer lags and analyses increasingly stale
# audio). ~64 ms keeps the whole 3-template bank comfortably real-time (~0.6x on
# a worst-case dense-combat fixture) while still catching every event; the added
# detection jitter is negligible next to the combat action-dispatch latency.
DEFAULT_EVAL_STEP_SAMPLES = 6 * HOP_SIZE


@dataclass(frozen=True)
class FingerprintTemplateConfig:
    name: str  # logical cue: DODGE or COUNTER
    wav: Optional[str]  # bundled filename under assets/sounds/fingerprint/, or None to use the external path
    tuning: Tuning
    threshold: float = DEFAULT_CONFIDENCE
    rearm: float = DEFAULT_REARM
    cooldown_ms: int = DEFAULT_COOLDOWN_MS
    eval_step_samples: int = DEFAULT_EVAL_STEP_SAMPLES

    @property
    def cooldown_seconds(self) -> float:
        return self.cooldown_ms / 1000.0


def dodge_bank_configs() -> list[FingerprintTemplateConfig]:
    """NTE-ASC dodge_template_configs_v1 (the shipping default), verbatim."""
    return [
        FingerprintTemplateConfig(
            DODGE,
            "dodge.wav",
            Tuning(prefix_ms=220, tolerance=2, votes=8, coverage=3, corr=0.074, psr=2.0),
        ),
        FingerprintTemplateConfig(
            DODGE,
            "dodge3.wav",
            Tuning(prefix_ms=120, tolerance=2, votes=8, coverage=4, corr=0.115, psr=2.0),
        ),
    ]


# Counter (弹反) detection. NTE-ASC has no counter reference, so the tuning below
# is a baseline derived from the dodge defaults; it self-matches counter.wav and
# was observed firing on real counter cues in-game at ~90 confidence. Its
# acceptance threshold is user-configurable ("Counter Confidence", default 79.5);
# refine the gates with tools/calibrate_fingerprint.py against captured parry
# audio if false positives appear.
COUNTER_ENABLED = True


def counter_config() -> FingerprintTemplateConfig:
    """Baseline counter tuning. Uses ok-nte's assets/sounds/counter.wav."""
    return FingerprintTemplateConfig(
        COUNTER,
        None,
        Tuning(prefix_ms=180, tolerance=2, votes=8, coverage=4, corr=0.08, psr=2.0),
    )


# Bump when the fingerprint algorithm or TemplateData layout changes so stale
# on-disk caches are invalidated.
FINGERPRINT_CACHE_VERSION = 1


def _cache_key(wav_path: Path, tuning: Tuning) -> str:
    try:
        stat = wav_path.stat()
        signature = (FINGERPRINT_CACHE_VERSION, int(stat.st_mtime_ns), stat.st_size, repr(tuning))
    except OSError:
        signature = (FINGERPRINT_CACHE_VERSION, repr(tuning))
    return hashlib.sha1(repr(signature).encode("utf-8")).hexdigest()


def load_cached_template(wav_path, tuning: Tuning) -> TemplateData:
    """`load_template` with an on-disk cache of the computed fingerprint.

    Mirrors the project's existing next-to-asset caching (the legacy engine's
    `.npy` files): the expensive peak/hash/index/verifier computation runs once
    and is reused across runs. Any cache miss, version mismatch, corruption or
    IO error (e.g. a read-only asset dir) silently falls back to recomputing.
    """
    wav_path = Path(wav_path)
    cache_path = wav_path.with_name(wav_path.name + ".fpcache")
    key = _cache_key(wav_path, tuning)
    try:
        if cache_path.exists():
            with open(cache_path, "rb") as handle:
                blob = pickle.load(handle)
            if isinstance(blob, dict) and blob.get("key") == key:
                return blob["template"]
    except Exception:
        pass  # corrupt / incompatible cache -> recompute
    template = load_template(wav_path, tuning)
    try:
        with open(cache_path, "wb") as handle:
            pickle.dump({"key": key, "template": template}, handle, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:
        pass  # read-only location etc. -> skip caching
    return template
