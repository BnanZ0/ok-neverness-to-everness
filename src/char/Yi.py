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


class Yi(BaseChar):
    """Yi - YELLOW sub DPS setup.

    Casts Q then E to complete the aspect setup, then leaves the field.
    Self-contained and independent of any specific team composition.
    """

    cn_name = "翳"
    element = BaseChar.Element.YELLOW
    SKILL_SETTLE_DURATION = 0.4

    def describe_role(self):
        return RoleProfile(
            role=Role.SUB_DPS,
            field_preference=FieldPreference.SETUP_ONLY,
            max_field_time=0,
        )

    def combat_plan(self, context: CombatContext):
        skill = self.planner_action(
            tags={ActionTag.SKILL_ACTION},
            slot=ActionSlot.SKILL,
            execute=lambda ctx: self._cast_skill_with_settle(),
            priority_ready=lambda _: self.skill_available(),
        )
        ultimate = self.click_ultimate_action()
        return self.plan(skill, ultimate)

    def _cast_skill_with_settle(self):
        result = self.click_skill(time_out=SKILL_SHORT_TIMEOUT)
        if result:
            self.sleep(self.SKILL_SETTLE_DURATION)
        return result
