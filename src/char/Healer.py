from src.char.BaseChar import BaseChar
from src.combat.planner import ActionTag, FieldPreference, Role, RoleProfile


class Healer(BaseChar):
    def describe_role(self):
        return RoleProfile(
            role=Role.SUPPORT,
            field_preference=FieldPreference.SUPPORT,
            max_field_time=0.5,
        )

    def combat_intents(self, context):
        return self.intents(
            self.click_ultimate_action(
                tags={ActionTag.ULTIMATE_ACTION, ActionTag.SUPPORT},
                reason="support ultimate available",
            ),
            self.click_skill_action(
                tags={ActionTag.SKILL_ACTION, ActionTag.SUPPORT},
                reason="support skill available",
            ),
            (
                self.planner_action(
                    name="healer_refresh",
                    tags={ActionTag.SUPPORT},
                    execute=self._execute_refresh_action,
                    reason="support has been off field too long",
                )
                if self.time_elapsed_accounting_for_freeze(self.last_perform) > 20
                else None
            )
        )


    def _execute_refresh_action(self, context=None):
        self.continues_normal_attack(0.5, click_skill_if_ready_and_return=True)
        return True
