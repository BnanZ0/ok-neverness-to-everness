from src.char.BaseChar import BaseChar
from src.combat.planner import CombatContext, Planner, RoleProfile


class Jiuyuan(BaseChar):
    cn_name = "九原"
    element = BaseChar.Element.GREEN
    SKILL_SETTLE_DURATION = 1.2

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def describe_role(self):
        return RoleProfile(
            role=Planner.Role.SUB_DPS,
            field_preference=Planner.FieldPreference.SUB_DPS,
            combat_start_priority=0,
            max_field_time=1.0,
        )

    def combat_plan(self, context):
        ultimate = self.click_ultimate_action()

        def _execute_skill(_):
            return self.click_skill(post_sleep=self.SKILL_SETTLE_DURATION)

        skill = self.planner_action(
            tags={Planner.ActionTag.SKILL_ACTION},
            slot=Planner.ActionSlot.SKILL,
            execute=_execute_skill,
            name=f"{self}_skill",
            reason="Jiuyuan skill with grouping settle",
            can_execute=lambda _: self.skill_available(),
            priority_ready=lambda _: self.skill_available(),
        )
        bullets = self.planner_action(
            tags=Planner.ActionTag.DEFAULT_ACTION,
            execute=self.fire_bullets,
        )

        def entry():
            skill_result = yield skill
            yield ultimate
            if not skill_result:
                yield bullets

        return self.plan(ultimate, skill, bullets, entry=entry)

    def fire_bullets(self, context: CombatContext = None):
        if context.has_strict_route():
            return
        box = self.task.box_of_screen(
            0.4191, 0.8799, 0.4348, 0.9076, name="jiuyuan_bullet", hcenter=True
        )
        if not self.has_bullets(box):
            return
        self.heavy_attack()
        return True

    def has_bullets(self, box):
        pct = self.task.calculate_color_percentage(bullet_color, box)
        return pct > 0.1


bullet_color = {
    "r": (97, 253),
    "g": (101, 181),
    "b": (168, 255),
}
