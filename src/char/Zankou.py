from src.char.BaseChar import BaseChar
from src.combat.planner import CombatContext, Planner, RoleProfile
from src.Labels import Labels


class Zankou(BaseChar):
    cn_name = "残红"
    element = BaseChar.Element.WHITE

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def describe_role(self):
        return RoleProfile(
            role=Planner.Role.MAIN_DPS,
            field_preference=Planner.FieldPreference.MAIN_DPS,
        )

    def combat_plan(self, context):
        ultimate = self.click_ultimate_action()
        skill_combo = self.planner_action(
            tags=Planner.ActionTag.DEFAULT_ACTION,
            slot=Planner.ActionSlot.SKILL,
            execute=self.perform_skill_combo,
            name="zankou_skill",
            reason="skill action available",
            can_execute=lambda _: self.skill_available(),
            priority_ready=lambda _: self.skill_available(),
        )

        def entry():
            if not self.find_ult_purple():
                combo_result = yield skill_combo
                if combo_result:
                    self.task.wait_until(
                        self.find_ult_purple,
                        post_action=self.click_with_interval,
                        time_out=2,
                    )

            if self.find_ult_purple():
                yield ultimate
                self.task.wait_until(
                    self.ultimate_available, post_action=self.click_with_interval, time_out=2
                )
                yield ultimate.repeat_for_entry()

        return self.plan(skill_combo, ultimate, entry=entry)

    def perform_skill_combo(self, context: CombatContext):
        deadline = self.now() + 10
        to_find = [Labels.zankou_skill_gold, Labels.zankou_skill_purple]
        click_skill = False
        while self.now() < deadline:
            for feature in to_find:
                if self.task.find_one(feature):
                    if not self.skill_available() or not context.is_slot_available(
                        self,
                        slot=Planner.ActionSlot.SKILL,
                    ):
                        continue
                    if click_skill := self.click_skill():
                        if feature == Labels.zankou_skill_purple:
                            self.sleep(2)
                            return True
            if self.find_ult_purple():
                return click_skill
            self.sleep(0.1)
            self.click()
        return click_skill

    def find_ult_purple(self):
        return self.task.find_one(Labels.zankou_ult_purple)
