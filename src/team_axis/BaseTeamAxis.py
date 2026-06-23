from __future__ import annotations

import time
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from src.char.BaseChar import BaseChar
    from src.combat.BaseCombatTask import BaseCombatTask


class TeamAxisError(RuntimeError):
    """Raised when a team axis cannot safely continue."""


class BaseTeamAxis:
    """Base class for a complete, ordered multi-character combat axis.

    Subclasses implement one opening rotation and one repeatable rotation.
    Character ``perform()`` methods are deliberately not used here because
    they always hand control back to the normal priority-based switcher.
    """

    name: ClassVar[str] = "Unnamed Team Axis"
    axis_id: ClassVar[str] = ""
    description: ClassVar[str] = ""
    team_signature: ClassVar[tuple[str, ...]] = ()
    team_labels: ClassVar[tuple[str, ...]] = ()
    opening_steps: ClassVar[tuple[str, ...]] = ()
    cycle_steps: ClassVar[tuple[str, ...]] = ()
    enabled: ClassVar[bool] = True
    priority: ClassVar[int] = 0

    def __init__(self, task: "BaseCombatTask"):
        self.task = task
        self.opening_finished = False
        self.cycle_count = 0
        self._chars_by_builtin_key = {
            char.builtin_key: char
            for char in task.chars
            if char is not None and getattr(char, "builtin_key", None)
        }

    @classmethod
    def matches(cls, chars: list["BaseChar"]) -> bool:
        """Return whether the ordered team slots exactly match this axis."""
        actual = tuple(getattr(char, "builtin_key", None) for char in chars)
        return cls.matches_signature(actual)

    @classmethod
    def matches_signature(cls, signature) -> bool:
        """Return whether an ordered builtin-key signature matches this axis."""
        if not cls.enabled or not cls.team_signature:
            return False
        return tuple(signature) == cls.team_signature

    def perform_next(self):
        """Run the opening once, then one complete loop per call."""
        self.task.check_combat()
        if not self.opening_finished:
            self.task.log_info(f"team axis opening start: {self.name}")
            self.run_opening()
            self.opening_finished = True
            self.task.log_info(f"team axis opening end: {self.name}")
        else:
            self.task.log_debug(f"team axis cycle {self.cycle_count + 1}: {self.name}")
            self.run_cycle()
            self.cycle_count += 1
        self.task.check_combat()

    def run_opening(self):
        """Execute the one-time opening rotation."""
        raise NotImplementedError

    def run_cycle(self):
        """Execute one complete repeatable rotation."""
        raise NotImplementedError

    def on_combat_end(self):
        """Optional cleanup hook for stateful axes."""

    def get_char(self, builtin_key: str) -> "BaseChar":
        char = self._chars_by_builtin_key.get(builtin_key)
        if char is None:
            raise TeamAxisError(f"team axis character is missing: {builtin_key}")
        return char

    def current_char(self) -> "BaseChar":
        char = self.task.get_current_char(raise_exception=False)
        if char is None:
            raise TeamAxisError("team axis cannot identify the current character")
        return char

    def switch_to(self, builtin_key: str, wait_intro=True) -> "BaseChar":
        """Force a switch without consulting normal character priorities."""
        target = self.get_char(builtin_key)
        return self.switch_to_char(target, wait_intro=wait_intro)

    def switch_to_char(self, target: "BaseChar", wait_intro=True) -> "BaseChar":
        """Force a switch to a concrete character instance."""
        current = self.task.get_current_char(raise_exception=False)

        if current != target:
            has_intro = False
            if current is not None:
                current.wait_switch_cd()
                has_intro = current.is_cycle_full()

            # This is the only intentional dependency on the existing switch
            # implementation. Keeping it here makes future rebases localized.
            self.task._switch_to_char(
                target,
                current_char=current,
                has_intro=has_intro,
                retry_intro=False,
                log_prefix=f"team axis {self.name}",
            )

            target.last_perform = time.time()
            if target.has_intro:
                target.add_intro_motion_freeze(target.last_perform)
        elif target.last_perform <= 0:
            target.last_perform = time.time()

        if wait_intro:
            target.wait_intro()
        return target

    def skill(self, **kwargs) -> bool:
        return self.current_char().click_skill(**kwargs)

    def ultimate(self, **kwargs) -> bool:
        return self.current_char().click_ultimate(**kwargs)

    def normal_attack(self, duration: float, interval: float = 0.1):
        self.current_char().continues_normal_attack(duration, interval=interval)

    def heavy_attack(self, duration: float = 0.6):
        self.current_char().heavy_attack(duration)

    def sleep(self, duration: float):
        self.current_char().sleep(duration)

    def call_current(self, method_name: str, *args, **kwargs):
        """Call an optional character-specific primitive such as fire_bullets."""
        char = self.current_char()
        method = getattr(char, method_name, None)
        if method is None or not callable(method):
            raise TeamAxisError(f"{char} does not support action: {method_name}")
        return method(*args, **kwargs)
