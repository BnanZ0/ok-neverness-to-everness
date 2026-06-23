from src.char.BaseChar import BaseChar
from src.combat.planner import (
    ActionTag,
    CombatContext,
    EntryChainPolicy,
    FieldPreference,
    Role,
    RoleProfile,
)


class Jiuyuan(BaseChar):
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
            self.click_skill_action(chain_policy=EntryChainPolicy.STOP_ON_SUCCESS),
            self.planner_action(
                tags=ActionTag.DEFAULT_ACTION,
                execute=self.fire_bullets,
            ),
        )

    def fire_bullets(self, context: CombatContext = None, duration=0.6):
        if context is not None and context.has_strict_route():
            return
        box = self.task.box_of_screen(
            0.4191, 0.8799, 0.4348, 0.9076, name="jiuyuan_bullet", hcenter=True
        )
        if not self.has_bullets(box):
            return
        self.heavy_attack(duration=duration)
        return True

    def has_bullets(self, box):
        pct = self.task.calculate_color_percentage(bullet_color, box)
        # self.logger.debug(f"Jiuyuan has_bullets {pct}")
        return pct > 0.1


bullet_color = {
    "r": (97, 253),
    "g": (101, 181),
    "b": (168, 255),
}
