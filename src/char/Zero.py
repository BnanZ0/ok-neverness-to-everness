from src.char.BaseChar import BaseChar
from src.combat.planner import ActionSlot, CombatContext, FieldPreference, Role, RoleProfile


class Zero(BaseChar):
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
            self.click_skill_action(
                can_execute=self.should_use_skill,
            ),
        )
    
    def should_use_skill(self, context: CombatContext = None):
        return not self.is_cycle_full() or (
            context is not None
            and context.strict_route_wants_action(self, slot=ActionSlot.SKILL)
        )

    def click_skill(self, *args, **kwargs):
        ret = super().click_skill(*args, **kwargs)
        if ret:
            self.task.wait_until(self.is_cycle_full)
        return ret
