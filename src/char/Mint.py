
from src.char.BaseChar import BaseChar
from src.combat.planner import FieldPreference, Role, RoleProfile


class Mint(BaseChar):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def describe_role(self):
        return RoleProfile(
            role=Role.SUB_DPS,
            field_preference=FieldPreference.SUB_DPS,
            max_field_time=1.0,
        )

    def combat_intents(self, context):
        return self.intents(
            self.click_ultimate_action(),
            self.click_skill_action(),
        )
