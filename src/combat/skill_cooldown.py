"""Internal skill cooldown tracking by simulation.

Off-field characters' skill cooldowns cannot be read reliably from the HUD (the
small portrait cooldowns defeat the bundled OCR). Instead we model cooldowns
ourselves: when a character successfully casts a skill we stamp the moment, and
readiness is simply ``now >= stamp + cooldown``. No screen reading required.

This is the foundation the scatter-triggered gather feature uses to know whether
a gather character (Sakiri / Iloy) can actually cast right now. It is pure
logic with an injectable clock so it unit tests without a game or ``time`` patch.

Caveats (recording-unverified):
- Cooldown durations must be supplied per skill; constellation/buff reductions
  are not modelled unless the caller passes the reduced value.
- A stamp should only be recorded on a *successful* cast, otherwise readiness
  drifts. Callers own that decision.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class SkillCooldownModel:
    """Per-slot cooldown ledger keyed by an arbitrary slot name (e.g. "skill")."""

    now_fn: callable = time.monotonic
    _ready_at: dict[str, float] = field(default_factory=dict)

    def mark_used(self, slot: str, cooldown: float, now: float | None = None) -> None:
        """Record a successful cast; the slot is busy for ``cooldown`` seconds."""

        stamp = self.now_fn() if now is None else now
        self._ready_at[slot] = stamp + max(0.0, cooldown)

    def is_ready(self, slot: str, now: float | None = None) -> bool:
        """True if the slot was never used or its cooldown has elapsed."""

        ready_at = self._ready_at.get(slot)
        if ready_at is None:
            return True
        current = self.now_fn() if now is None else now
        return current >= ready_at

    def remaining(self, slot: str, now: float | None = None) -> float:
        """Seconds left on cooldown (0.0 when ready or never used)."""

        ready_at = self._ready_at.get(slot)
        if ready_at is None:
            return 0.0
        current = self.now_fn() if now is None else now
        return max(0.0, ready_at - current)

    def reset(self, slot: str | None = None) -> None:
        """Clear one slot or the whole ledger."""

        if slot is None:
            self._ready_at.clear()
        else:
            self._ready_at.pop(slot, None)
