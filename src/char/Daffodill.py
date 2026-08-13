from src.char.BaseChar import BaseChar
from src.combat.planner import (
    ActionIntent,
    CombatContext,
)

SKILL_SHORT_TIMEOUT = 2.0


class Daffodill(BaseChar):
    """Daffodill - PURPLE burst character.

    SUB_DPS, SETUP_ONLY: Q first, then the burst window (E attempted at most once
    during the burst), then leave the field. Self-contained and independent of any
    specific team composition. Parry detection is not implemented; readiness is
    approximated through ultimate_available().
    """

    cn_name = "达芙蒂尔"
    element = BaseChar.Element.PURPLE
    ULT_BURST_DURATION = 1.5

    def combat_plan(self, context: CombatContext):
        ultimate = self.click_ultimate_action()
        skill = self.click_skill_action()

        def entry():
            ultimate_result = yield ultimate
            if ultimate_result:
                self._perform_burst(context, skill)
                return
            yield skill

        return self.plan(ultimate, skill, entry=entry)

    def _perform_burst(self, context: CombatContext, skill: ActionIntent):
        """Burst damage window after a successful Q (patterned on Chiz.perform_in_ult).

        - Attack continuously and probe whether E is available.
        - E is really attempted at most once: attempted is separated from used.
        - A reservation-blocked E does not consume the attempted quota.
        - The loop is time-boxed by ``ULT_BURST_DURATION``.
        """
        self.logger.info("burst start")
        deadline = self.now() + self.ULT_BURST_DURATION
        skill_used = False

        while self.now() < deadline:
            if not skill_used and context.is_action_allowed(self, skill):
                skill_used = self.click_skill()
            self.normal_attack()
            self.sleep(0.2)

        self.logger.info(f"burst end (skill used={skill_used})")
