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

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

from src.sound_trigger.fingerprint.matcher import HOP_SIZE, TemplateData, Tuning, load_template

# stdlib logging (not ok's Logger) keeps this module dependency-free / testable.
_log = logging.getLogger(__name__)

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
    # Plain signature string, stored inside the cache and compared on load — a
    # staleness check, not a security/crypto use (so no hashing needed).
    try:
        stat = wav_path.stat()
        return repr((FINGERPRINT_CACHE_VERSION, int(stat.st_mtime_ns), stat.st_size, repr(tuning)))
    except OSError:
        return repr((FINGERPRINT_CACHE_VERSION, repr(tuning)))


def load_cached_template(wav_path, tuning: Tuning) -> TemplateData:
    """`load_template` with an on-disk cache of the computed fingerprint.

    Mirrors the project's existing next-to-asset caching (the legacy engine's
    `.npy` files): the expensive peak/hash/index/verifier computation runs once
    and is reused across runs. Stored as a plain `.npz` (loaded with
    allow_pickle=False — no pickle). Any cache miss, version mismatch, corruption
    or IO error (e.g. a read-only asset dir) silently falls back to recomputing.
    """
    wav_path = Path(wav_path)
    cache_path = wav_path.with_name(wav_path.name + ".fpcache.npz")
    key = _cache_key(wav_path, tuning)
    try:
        if cache_path.exists():
            with np.load(cache_path, allow_pickle=False) as data:
                if str(data["key"].item()) == key:
                    return _template_from_cache(data)
    except Exception as exc:  # corrupt / incompatible cache -> recompute
        _log.debug("fingerprint cache read failed for %s (%s); recomputing", cache_path.name, exc)
    template = load_template(wav_path, tuning)
    try:
        _write_template_cache(cache_path, key, template)
    except Exception as exc:  # read-only location etc. -> skip caching
        _log.debug("fingerprint cache write failed for %s (%s); skipping", cache_path.name, exc)
    return template


def _write_template_cache(cache_path: Path, key: str, template: TemplateData) -> None:
    meta = {
        "peaks": template.peaks,
        "index": [[list(bins), frames] for bins, frames in template.index.items()],
        "source_seconds": template.source_seconds,
        "trimmed_seconds": template.trimmed_seconds,
        "has_verifier": template.verifier is not None,
    }
    verifier = template.verifier if template.verifier is not None else np.zeros(0, dtype=np.float32)
    np.savez(
        str(cache_path),
        key=np.array(key),
        samples=template.samples,
        verifier=verifier,
        meta=np.array(json.dumps(meta)),
    )


def _template_from_cache(data) -> TemplateData:
    meta = json.loads(str(data["meta"].item()))
    peaks = [[(int(b), int(q)) for b, q in frame] for frame in meta["peaks"]]
    index = {
        (int(k[0]), int(k[1]), int(k[2])): [int(x) for x in frames]
        for k, frames in meta["index"]
    }
    return TemplateData(
        samples=data["samples"],
        peaks=peaks,
        index=index,
        source_seconds=float(meta["source_seconds"]),
        trimmed_seconds=float(meta["trimmed_seconds"]),
        verifier=data["verifier"] if meta["has_verifier"] else None,
    )
