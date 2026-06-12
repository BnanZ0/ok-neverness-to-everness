from src.char.BaseChar import BaseChar
from src.combat.planner import FieldClaim, FieldPreference, Role, RoleProfile


class Lacrimosa(BaseChar):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def describe_role(self):
        return RoleProfile(
            role=Role.MAIN_DPS,
            field_preference=FieldPreference.MAIN_DPS,
            max_field_time=1.5,
        )

    def combat_intents(self, context):
        claims = []
        if self.time_elapsed_accounting_for_freeze(self.last_switch_time) > 2.5:
            claims.append(FieldClaim.normal("Lacrimosa wants short field time"))
        return self.intents(
            self.click_ultimate_action(),
            self.click_skill_action(),
            *claims,
        )
