import time

from src.char.BaseChar import BaseChar
from src.combat.planner import (
    ActionSlot,
    ActionTag,
    CombatContext,
    FieldPreference,
    Role,
    RoleProfile,
)

SKILL_SHORT_TIMEOUT = 2.0


class Adler(BaseChar):
    """Adler - RED survival support.

    SUB_DPS, SETUP_ONLY: stack YE on entry, cast E (shield), then Q and leave the field.
    YE stacking and E are merged into a single SKILL action so the planner checks
    reservations before executing. Game mechanics are self-contained; no team coupling.
    """

    cn_name = "阿德勒"
    element = BaseChar.Element.RED
    MAX_FIELD_TIME = 0  # forbid generic normal-attack fallback
    YE_STACK_DURATION = 1.5
    YE_ATTACK_INTERVAL = 0.2

    def describe_role(self):
        return RoleProfile(
            role=Role.SUB_DPS,
            field_preference=FieldPreference.SETUP_ONLY,
            max_field_time=self.MAX_FIELD_TIME,
        )

    def combat_plan(self, context: CombatContext):
        skill = self.planner_action(
            tags={ActionTag.SKILL_ACTION},
            slot=ActionSlot.SKILL,
            execute=lambda ctx: self._stack_ye_then_skill(),
            priority_ready=lambda _: self.skill_available(),
        )
        ultimate = self.click_ultimate_action()

        def entry():
            skill_result = yield skill
            if skill_result:
                self.logger.info("shield deployed")
                self.sleep(0.5)
                yield ultimate
            else:
                self.logger.info("setup skill failed, skipping ultimate")

        return self.plan(skill, ultimate, entry=entry)

    def _stack_ye_then_skill(self):
        """Combined YE stacking + E cast, run after the planner SKILL reservation check."""
        self._stack_ye()
        return self.click_skill(time_out=SKILL_SHORT_TIMEOUT)

    def _stack_ye(self):
        """Quick normal attacks to build YE stacks on entry.

        Charged aimed shots grant 2 stacks per hit, normal attacks 1 per hit.
        Normal attacks are used here for reliability; switch to charged shots after
        live calibration.
        """
        self.logger.info("stacking ye")
        start = self._now()
        while self._now() - start < self.YE_STACK_DURATION:
            if not self.is_current_char:
                return
            if self.is_dead:
                return
            self.check_combat()
            self.normal_attack()
            self.sleep(self.YE_ATTACK_INTERVAL)

    def _now(self):
        return time.monotonic()
