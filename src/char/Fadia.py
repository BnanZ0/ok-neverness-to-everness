
from src.char.BaseChar import BaseChar
from src.combat.planner import EntryChainPolicy, FieldPreference, Role, RoleProfile


class Fadia(BaseChar):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def describe_role(self):
        return RoleProfile(
            role=Role.SUB_DPS,
            field_preference=FieldPreference.SUB_DPS,
        )

    def combat_intents(self, context):
        return self.intents(
            self.click_ultimate_action(chain_policy=EntryChainPolicy.STOP_ON_SUCCESS),
            self.click_skill_action(),
        )
