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


class Hania(BaseChar):
    """Hania - BLUE support.

    SUB_DPS, SETUP_ONLY: Q to deploy the enhanced domain, then E to deploy the
    companion, then leave the field. Self-contained and independent of any specific
    team composition; higher-level coordination is handled outside this file.
    """

    cn_name = "哈妮娅"
    element = BaseChar.Element.BLUE
    MAX_FIELD_TIME = 0  # forbid generic normal-attack fallback

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
                self.logger.info("enhanced domain active")
                self.sleep(0.3)
            skill_result = yield skill
            if skill_result:
                self.logger.info("companion deployed")
                self.sleep(0.3)

        return self.plan(ultimate, skill, entry=entry)

    def _execute_skill(self, context: CombatContext = None) -> bool:
        return self.click_skill(time_out=SKILL_SHORT_TIMEOUT)
