from src.char.BaseChar import BaseChar
from src.combat.planner import FieldPreference, Role, RoleProfile


class Yi(BaseChar):
    """翳的深渊盈蓄队最小入场逻辑：Q 后接 E，完成铺垫即离场。"""

    cn_name = "翳"
    element = BaseChar.Element.YELLOW
    SKILL_SETTLE_DURATION = 0.4

    def describe_role(self):
        return RoleProfile(
            role=Role.SUB_DPS,
            field_preference=FieldPreference.SETUP_ONLY,
            max_field_time=0,
        )

    def combat_plan(self, context):
        return self.plan(
            self.click_ultimate_action(
                reason="yi ultimate setup",
                can_execute=lambda _: self.ultimate_available(),
            ),
            self.click_skill_action(
                reason="yi aspect setup",
                post_sleep=self.SKILL_SETTLE_DURATION,
                can_execute=lambda _: self.skill_available(),
            ),
        )
