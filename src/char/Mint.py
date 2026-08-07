import time

from src.char.BaseChar import BaseChar
from src.combat.planner import (
    ActionSlot,
    ActionTag,
    CombatContext,
    FieldPreference,
    Role,
    RoleProfile,
)
from src.combat.skill_cooldown import SkillCooldownModel

_LOG_PREFIX = "[Mint]"
SKILL_SHORT_TIMEOUT = 2.0
SKILL_REUSE_GUARD = 6.0
SKILL_RETRY_DELAY = 4.0


class Mint(BaseChar):
    """薄荷 - 辅助/副C.

    999夜挂机队辅助: Q 强化领域 -> E 部署离场伤害 -> 请求零回场铺垫.
    保持简单结构, 队伍协调由上层配置决定.

    核心设计:
    - Q 先放 (强化领域), E 后放 (部署离场伤害)
    - E 用 SkillCooldownModel 防止过频释放
    - 在 999 夜队中: SETUP_ONLY + max_field_time=0
    - 不在 999 夜队中: SUB_DPS, 行为退化为 Q -> E
    - 完成后 request_switch 到 Zero (主角), 让零铺垫后切真红爆发
    """

    cn_name = "薄荷"
    element = BaseChar.Element.GREEN
    MAX_FIELD_TIME = 0  # 禁止通用平A fallback
    POST_ACTION_SLEEP = 0.3  # Q/E 动画后短暂等待
    FALLBACK_DURATION = 1.5  # Q+E both failed: brief normal attacks
    NORMAL_ATTACK_INTERVAL = 0.18

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._cooldowns = SkillCooldownModel(now_fn=lambda: self._now())

    @staticmethod
    def is_999night_team(chars):
        from src.combat.team_strategies import is_999night_team

        return is_999night_team(chars)

    def describe_role(self):
        in_team = self.is_999night_team(self.task.chars)
        return RoleProfile(
            role=Role.SUB_DPS,
            field_preference=(
                FieldPreference.SETUP_ONLY if in_team else FieldPreference.SUB_DPS
            ),
            max_field_time=self.MAX_FIELD_TIME,
        )

    def combat_plan(self, context: CombatContext):
        in_team = self.is_999night_team(self.task.chars)

        ultimate = self.click_ultimate_action(
            reason="mint ultimate (enhanced domain)",
            can_execute=lambda _: self.ultimate_available(),
        )

        def _execute_skill(_ctx) -> bool:
            result = self.click_skill(time_out=SKILL_SHORT_TIMEOUT)
            if result:
                self._cooldowns.mark_used("skill", SKILL_REUSE_GUARD)
            return result

        skill = self.planner_action(
            tags={ActionTag.SKILL_ACTION},
            slot=ActionSlot.SKILL,
            execute=_execute_skill,
            name="mint_skill",
            reason="mint skill (deploy off-field damage)",
            can_execute=lambda ctx: (
                not in_team
                or ctx.strict_route_wants_action(self, slot=ActionSlot.SKILL)
                or (self.skill_available() and self._cooldowns.is_ready("skill"))
            ),
            priority_ready=lambda _: (
                self.skill_available() and (not in_team or self._cooldowns.is_ready("skill"))
            ),
        )

        def entry():
            ultimate_result = yield ultimate
            if ultimate_result:
                self.logger.info(f"{_LOG_PREFIX} enhanced domain active")
                self.sleep(self.POST_ACTION_SLEEP)
            else:
                self.logger.info(f"{_LOG_PREFIX} ult failed, continuing")

            skill_result = yield skill
            if skill_result:
                self.logger.info(f"{_LOG_PREFIX} off-field damage deployed")
                self.sleep(self.POST_ACTION_SLEEP)

            if not ultimate_result and not skill_result:
                # Q and E both failed: brief normal attacks before switching
                self.logger.info(f"{_LOG_PREFIX} both Q and E failed, fallback attacks")
                self._fallback_attacks()

            if in_team:
                self._request_zero_return(context)

        return self.plan(ultimate, skill, entry=entry)

    def _fallback_attacks(self):
        """Q+E both failed: brief normal attacks to avoid empty-cycle."""
        deadline = self._now() + self.FALLBACK_DURATION
        while self._now() < deadline:
            if not self.is_current_char or self.is_dead:
                return
            self.check_combat()
            self.normal_attack()
            self.sleep(self.NORMAL_ATTACK_INTERVAL)

    def _request_zero_return(self, context: CombatContext) -> None:
        """完成后请求零(Zero)回场进行光属性铺垫."""
        if context is None:
            return
        from src.char.Zero import Zero

        for char in self.task.chars:
            if isinstance(char, Zero):
                context.request_switch(
                    char, reason="return Zero after Mint setup"
                )
                self.logger.info(f"{_LOG_PREFIX} requested Zero return")
                return

    def _now(self):
        return time.monotonic()

    def on_combat_end(self, chars):
        """战后清理."""
        self._cooldowns.reset()
