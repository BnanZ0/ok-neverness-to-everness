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

_LOG_PREFIX = "[Zero]"
SKILL_SHORT_TIMEOUT = 2.0
SKILL_REUSE_GUARD = 6.0
STRICT_ROUTE_SKILL_WAIT = 1.5  # backoff seconds when strict route forces E on cooldown
STRICT_ROUTE_SKILL_STEP_TIMEOUT = 5.0  # expire route if E still unavailable after this


class Zero(BaseChar):
    """零 - 光系(WHITE)主角/辅助.

    通用辅助角色, 在多队伍中复用:
    - Chiz 深渊队: 元素反应链路中的光属性铺垫
    - 999夜挂机队: Q+E 铺垫后 request_switch(Shinku) 让真红入场爆发

    核心设计:
    - Q 提供光属性铺垫, E 触发元素环
    - should_use_skill 检查元素反应队友和 cycle 状态
    - E 用 SkillCooldownModel 防止过频释放
    - 在小吱深渊队和 999 夜队中: SETUP_ONLY + max_field_time=0
    - 其他队伍中: SUB_DPS + max_field_time=1.0 (原有行为)
    """

    cn_name = "零"
    element = BaseChar.Element.WHITE
    MAX_FIELD_TIME_DEFAULT = 1.0
    POST_ACTION_SLEEP = 0.3
    FALLBACK_DURATION = 1.5  # Q+E both failed: brief normal attacks
    NORMAL_ATTACK_INTERVAL = 0.18

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._cooldowns = SkillCooldownModel(now_fn=lambda: self._now())
        # strict route E 退避：记录首次强制尝试时间，超过步骤超时仍不可用则过期路线。
        self._strict_skill_attempt_start = 0.0

    @staticmethod
    def is_999night_team(chars):
        from src.combat.team_strategies import is_999night_team

        return is_999night_team(chars)

    @staticmethod
    def is_chiz_abyss_team(chars):
        from src.combat.team_strategies import is_chiz_abyss_team

        return is_chiz_abyss_team(chars)

    def describe_role(self):
        in_999night = self.is_999night_team(self.task.chars)
        in_chiz_abyss = self.is_chiz_abyss_team(self.task.chars)
        setup_only = in_999night or in_chiz_abyss
        return RoleProfile(
            role=Role.SUB_DPS,
            field_preference=(
                FieldPreference.SETUP_ONLY
                if setup_only
                else FieldPreference.SUB_DPS
            ),
            max_field_time=0 if setup_only else self.MAX_FIELD_TIME_DEFAULT,
        )

    def combat_plan(self, context: CombatContext):
        in_999night = self.is_999night_team(self.task.chars)

        ultimate = self.click_ultimate_action(
            can_execute=lambda _: self.ultimate_available(),
        )

        def _execute_skill(_ctx) -> bool:
            return self._execute_skill_with_backoff(_ctx)

        skill = self.planner_action(
            tags={ActionTag.SKILL_ACTION},
            slot=ActionSlot.SKILL,
            execute=_execute_skill,
            name="zero_skill",
            reason="zero skill (element ring prime)",
            can_execute=lambda ctx: (
                ctx.strict_route_wants_action(self, slot=ActionSlot.SKILL)
                or (
                    self.skill_available()
                    and self._cooldowns.is_ready("skill")
                    and self.should_use_skill(ctx)
                )
            ),
            priority_ready=lambda _: (
                self.skill_available()
                and self._cooldowns.is_ready("skill")
            ),
        )

        if in_999night:
            return self._plan_999night(context, ultimate, skill)

        return self.plan(ultimate, skill)

    def _plan_999night(self, context, ultimate, skill):
        def entry():
            ultimate_result = yield ultimate
            if ultimate_result:
                self.sleep(self.POST_ACTION_SLEEP)

            skill_result = yield skill
            if skill_result:
                self.sleep(self.POST_ACTION_SLEEP)

            if not ultimate_result and not skill_result:
                # Q and E both failed: brief normal attacks before switching
                self.logger.info(f"{_LOG_PREFIX} both Q and E failed, fallback attacks")
                self._fallback_attacks()

            self._request_shinku_return(context)

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

    def should_use_skill(self, context: CombatContext = None):
        return (
            not self.has_element_reaction_teammate()
            or not self.is_cycle_full()
            or (
                context is not None
                and context.strict_route_wants_action(self, slot=ActionSlot.SKILL)
            )
        )

    def _request_shinku_return(self, context: CombatContext) -> None:
        """999夜队: Q+E 完成后请求真红(Shinku)回场爆发."""
        if context is None:
            return
        from src.char.Shinku import Shinku

        for char in self.task.chars:
            if isinstance(char, Shinku):
                context.request_switch(
                    char, reason="return Shinku after Zero setup"
                )
                self.logger.info(f"{_LOG_PREFIX} requested Shinku return")
                return

    def _execute_skill_with_backoff(self, ctx) -> bool:
        """strict route 强制 E 时，若 E 在冷却中，退避等待；步骤超时则过期路线。

        不可用的强制动作不得以 ~0.1s 频率反复执行 OCR 和点击。这里在 strict
        route 强制 E 但 E 不可用时等待 STRICT_ROUTE_SKILL_WAIT，并在超过
        STRICT_ROUTE_SKILL_STEP_TIMEOUT 仍不可用时过期路线，让 planner 返回
        主 C，而非让辅助平 A 掩盖路线失败。
        """
        strict_route_forcing = ctx is not None and ctx.strict_route_wants_action(
            self, slot=ActionSlot.SKILL
        )
        if strict_route_forcing and not self.skill_available():
            now = self._now()
            if self._strict_skill_attempt_start <= 0:
                self._strict_skill_attempt_start = now
            elapsed = now - self._strict_skill_attempt_start
            if elapsed >= STRICT_ROUTE_SKILL_STEP_TIMEOUT:
                self.logger.info(
                    f"{_LOG_PREFIX} strict route skill unavailable for "
                    f"{elapsed:.1f}s, expiring route to return main DPS"
                )
                self._strict_skill_attempt_start = 0.0
                self._expire_strict_route(ctx)
                return False
            wait = min(
                STRICT_ROUTE_SKILL_WAIT,
                STRICT_ROUTE_SKILL_STEP_TIMEOUT - elapsed,
            )
            if wait > 0:
                self.logger.info(
                    f"{_LOG_PREFIX} strict route skill on cooldown, "
                    f"waiting {wait:.1f}s"
                )
                self.sleep(wait)
        else:
            self._strict_skill_attempt_start = 0.0
        result = self.click_skill(time_out=SKILL_SHORT_TIMEOUT)
        if result:
            self._cooldowns.mark_used("skill", SKILL_REUSE_GUARD)
            self._strict_skill_attempt_start = 0.0
        return result

    def _expire_strict_route(self, ctx) -> None:
        """过期当前 strict route，让 planner 返回主 C 而非继续等待不可用的 E。"""
        expire = getattr(ctx, "expire_strict_route", None)
        if expire is None:
            return
        expired = expire()
        if expired:
            self.logger.info(f"{_LOG_PREFIX} expired strict route after step timeout")

    def click_skill(self, *args, **kwargs):
        ret = super().click_skill(*args, **kwargs)
        if ret:
            if not self.task.wait_until(
                self.is_cycle_full,
                time_out=1.25,
                raise_if_not_found=False,
            ):
                self.logger.info(f"{_LOG_PREFIX} cycle not full after skill")
        return ret

    def _now(self):
        return time.monotonic()

    def on_combat_end(self, chars):
        """战后清理."""
        self._cooldowns.reset()
        self._strict_skill_attempt_start = 0.0
