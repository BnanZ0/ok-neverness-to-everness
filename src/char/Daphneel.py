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


class Daphneel(BaseChar):
    """Daphneel - PURPLE burst character.

    SUB_DPS, SETUP_ONLY: Q first, then the burst window (E attempted at most once
    during the burst), then leave the field. Self-contained and independent of any
    specific team composition. Parry detection is not implemented; readiness is
    approximated through ultimate_available().
    """

    cn_name = "达芙蒂尔"
    element = BaseChar.Element.PURPLE
    MAX_FIELD_TIME = 0  # forbid generic normal-attack fallback; only enter when Q/E ready
    ULT_BURST_DURATION = 1.5
    BURST_ATTACK_INTERVAL = 0.2

    def describe_role(self):
        return RoleProfile(
            role=Role.SUB_DPS,
            field_preference=FieldPreference.SETUP_ONLY,
            max_field_time=self.MAX_FIELD_TIME,
        )

    def combat_plan(self, context: CombatContext):
        ultimate = self.click_ultimate_action()
        skill = self.planner_action(
            tags={ActionTag.SKILL_ACTION},
            slot=ActionSlot.SKILL,
            execute=self._execute_skill,
            priority_ready=lambda _: self.skill_available(),
        )

        def entry():
            ultimate_result = yield ultimate
            if ultimate_result:
                self.logger.info("burst executed")
                self._perform_burst(context)
                return
            yield skill

        return self.plan(ultimate, skill, entry=entry)

    def _execute_skill(self, context: CombatContext = None) -> bool:
        return self.click_skill(time_out=SKILL_SHORT_TIMEOUT)

    def _perform_burst(self, context: CombatContext = None):
        """Burst damage window after a successful Q (patterned on Chiz.perform_in_ult).

        - Attack continuously and probe whether E is available.
        - E is really attempted at most once: attempted is separated from used.
        - A reservation-blocked E does not consume the attempted quota.
        - The loop is time-boxed by ``ULT_BURST_DURATION``.
        """
        self.logger.info("burst start")
        start = self._now()
        deadline = start + self.ULT_BURST_DURATION
        skill_attempted = False
        skill_used = False

        while self._now() < deadline:
            if not self.is_current_char:
                self.logger.info("burst end (not current char)")
                return
            if self.is_dead:
                self.logger.info("burst end (dead)")
                return

            self.check_combat()

            if not skill_attempted and self.skill_available():
                blocked = not self._try_skill_during_burst(context)
                if blocked:
                    # reservation blocked -- do not consume the attempted quota; may wait briefly
                    self.logger.debug("skill blocked by reservation, will retry")
                else:
                    skill_attempted = True
                    skill_used = True

            self.normal_attack()
            self.sleep(self.BURST_ATTACK_INTERVAL)

        self.logger.info(f"burst end (attempted={skill_attempted}, used={skill_used})")

    def _try_skill_during_burst(self, context: CombatContext = None):
        """Check the reservation before releasing E.

        Returns:
            True if the skill was executed (success or fail).
            False if blocked by a reservation (not attempted).
        """
        if context is not None and not context.can_execute_action(self, slot=ActionSlot.SKILL):
            return False

        self.logger.info("skill during burst")
        self._execute_skill(context)
        return True

    def _now(self):
        return time.monotonic()
