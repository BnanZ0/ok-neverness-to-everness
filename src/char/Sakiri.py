from src.char.BaseChar import BaseChar
from src.combat.planner import Planner, RoleProfile
from src.combat.skill_cooldown import SkillCooldownModel


class Sakiri(BaseChar):
    cn_name = "早雾"
    element = BaseChar.Element.RED
    SKILL_HOLD_DURATION = 0.8
    SKILL_SETTLE_DURATION = 1.2
    GATHER_REUSE_INTERVAL = 10.0  # minimum seconds between re-gather attempts
    # Minimum seconds between ultimate casts while looping in the Baicang team. The opener route
    # fires Sakiri's Q once for the initial suppress + team ATK buff; without this, nothing ever
    # re-cast it, so the 30% ATK buff fell off for the rest of a long boss fight. With it, Sakiri
    # re-ults a few times per fight (whenever the ultimate is off CD AND this interval has passed)
    # instead of hogging field time from the main DPS. Tune lower for more buff uptime, higher to
    # keep Sakiri off field more. The opener step bypasses this via strict_route_wants_action
    # (the interval starts ready, so the opener Q still fires immediately).
    ULT_REUSE_INTERVAL = 18.0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._cooldowns = SkillCooldownModel(now_fn=lambda: self._now())

    def describe_role(self):
        from src.combat.team_strategies import is_baicang_abyss_team

        in_baicang_team = is_baicang_abyss_team(self.task.chars)
        return RoleProfile(
            role=Planner.Role.SUB_DPS,
            field_preference=(
                Planner.FieldPreference.SETUP_ONLY
                if in_baicang_team
                else Planner.FieldPreference.SUB_DPS
            ),
            combat_start_priority=100 if in_baicang_team else 0,
            max_field_time=0 if in_baicang_team else 1.0,
        )

    def _gather_reuse_ready(self) -> bool:
        """True when enough time has passed to allow a re-gather outside the opener route."""
        return self._cooldowns.is_ready("gather")

    def _ult_reuse_ready(self) -> bool:
        """True when enough time has passed to allow a loop re-cast of the ultimate."""
        return self._cooldowns.is_ready("ultimate")

    def _execute_ultimate(self, _context) -> bool:
        result = self.click_ultimate()
        if result:
            self._cooldowns.mark_used("ultimate", self.ULT_REUSE_INTERVAL)
        return result

    def combat_plan(self, context):
        from src.combat.team_strategies import is_baicang_abyss_team

        in_baicang_team = is_baicang_abyss_team(self.task.chars)

        def _execute_gather(_):
            result = self.click_skill(
                down_time=self.SKILL_HOLD_DURATION,
                post_sleep=self.SKILL_SETTLE_DURATION,
            )
            if result:
                self._cooldowns.mark_used("gather", self.GATHER_REUSE_INTERVAL)
            return result

        skill = self.planner_action(
            tags={Planner.ActionTag.SKILL_ACTION},
            slot=Planner.ActionSlot.SKILL,
            execute=_execute_gather,
            name=f"{self}_skill",
            reason="Sakiri hold skill for grouping",
            can_execute=lambda ctx: (
                not in_baicang_team
                or ctx.strict_route_wants_action(
                    self,
                    slot=Planner.ActionSlot.SKILL,
                )
                or (self.skill_available() and self._gather_reuse_ready())
            ),
            priority_ready=lambda _: self.skill_available() and self._gather_reuse_ready(),
        )

        # In the Baicang team the ultimate fires on the opener route step, then again in the loop
        # only once it is off CD AND ULT_REUSE_INTERVAL has elapsed (so the team ATK buff returns a
        # few times per fight). priority_ready carries the same interval gate so Sakiri does not
        # attract a switch just to find her ultimate still on cooldown.
        ultimate = self.planner_action(
            tags={Planner.ActionTag.ULTIMATE_ACTION},
            slot=Planner.ActionSlot.ULTIMATE,
            execute=self._execute_ultimate,
            name=f"{self}_ultimate",
            reason="Sakiri ultimate suppresses and buffs team ATK",
            can_execute=lambda ctx: (
                not in_baicang_team
                or ctx.strict_route_wants_action(
                    self,
                    slot=Planner.ActionSlot.ULTIMATE,
                )
                or self._ult_reuse_ready()
            ),
            priority_ready=lambda _: self.ultimate_available()
            and (not in_baicang_team or self._ult_reuse_ready()),
        )
        return self.plan(ultimate, skill)

    def _now(self):
        import time

        return time.monotonic()
