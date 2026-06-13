# ============================================================================
# Per-template fingerprint tuning.
#
# DODGE uses NTE-Auto-Skill-Combo's proven, field-tested template bank and
# tunings verbatim (its `dodge_template_configs_v1`, the shipping default in
# src/dodge.rs): a two-template bank (dodge.wav + dodge3.wav) bundled under
# assets/sounds/fingerprint/. Because it is the same game cue and the same
# recordings + tunings, dodge needs no re-calibration.
#
# COUNTER (弹反) has NO reference: NTE-ASC never had a counter template. The
# config below is a PLACEHOLDER reusing ok-nte's counter.wav with generic
# defaults and MUST be re-calibrated with tools/calibrate_fingerprint.py against
# real captured combat audio before it can be trusted. Until then, prefer
# "Dodge All Attacks" so detection does not depend on the counter template.
# ============================================================================
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.sound_trigger.fingerprint.matcher import HOP_SIZE, Tuning

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


# ============================================================================
# Counter (弹反) detection is DISABLED by default.
#
# Unlike dodge, the counter template has NO reference tuning (NTE-Auto-Skill-Combo
# never had a counter template). The placeholder below is uncalibrated, so it
# would fire on poorly-separated / false cues. Rather than run an untrained
# detector, counter detection is off until its tuning is calibrated.
#
# TO ENABLE: calibrate counter_config()'s tuning + confidence with
# tools/calibrate_fingerprint.py against real combat audio containing parries,
# bake the result in below, then set COUNTER_ENABLED = True.
#
# Until then, "Dodge All Attacks" + the dodge bank cover attack avoidance.
# ============================================================================
COUNTER_ENABLED = False


def counter_config() -> FingerprintTemplateConfig:
    """PLACEHOLDER counter tuning — UNCALIBRATED, must be trained before use.

    See COUNTER_ENABLED above. Uses ok-nte's assets/sounds/counter.wav.
    """
    return FingerprintTemplateConfig(
        COUNTER,
        None,
        Tuning(prefix_ms=180, tolerance=2, votes=8, coverage=4, corr=0.08, psr=2.0),
    )
