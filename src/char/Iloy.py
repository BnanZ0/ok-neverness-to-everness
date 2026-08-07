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

_LOG_PREFIX = "[Iloy]"
SKILL_SHORT_TIMEOUT = 2.0


class Iloy(BaseChar):
    """伊洛伊 - 绿系(GREEN)辅助/治疗。

    999夜挂机队核心辅助: E 聚怪+治疗+ATK buff -> Q 进入梦境 ->
    长按重击(三段蓄力+清明梦连招) -> 请求真红回场.

    核心设计:
    - 三段蓄力+清明梦是一次连续长按, 不松手, 用一次 heavy_attack(duration)
    - Q 梦境状态下重击不消耗能量, 所以 Q 后直接长按即可
    - E 是核心生存手段(回血), 用 SkillCooldownModel 防止过频释放
    - 在 999 夜队中: SETUP_ONLY + combat_start_priority=100 (开场优先),
      完成后 request_switch 到 Mint, 形成循环链 Iloy->Mint->Zero->Shinku->Iloy
    - 在小吱深渊队中: SETUP_ONLY + combat_start_priority=100 (开场聚怪+治疗),
      由 strict route 驱动切换, 不走 request_switch 链
    - 不在上述队伍中: SUB_DPS, 行为退化为基础 E->Q->重击

    [EXTERNAL] 攻略来源: BV11Xgm6BEyG
    """

    cn_name = "伊洛伊"
    element = BaseChar.Element.GREEN

    MAX_FIELD_TIME = 0  # 禁止通用平A fallback
    HEAVY_ATTACK_DURATION = 2.5  # UNVERIFIED - 三段蓄力+清明梦连续长按时长
    SKILL_SETTLE_DURATION = 1.0  # allow gather, healing and the ATK buff to land
    SKILL_REUSE_GUARD = 8.0  # E 复用间隔, 防止过频释放
    SKILL_RETRY_DELAY = 4.0  # E 失败后重试延迟
    ABYSS_OPENER_TIMEOUT = 20.0  # opener route 超时
    FALLBACK_DURATION = 1.5  # E+Q both failed: brief normal attacks
    NORMAL_ATTACK_INTERVAL = 0.18

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._cooldowns = SkillCooldownModel(now_fn=lambda: self._now())

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
        in_chiz = self.is_chiz_abyss_team(self.task.chars)
        is_opener = in_999night or in_chiz
        return RoleProfile(
            role=Role.SUB_DPS,
            field_preference=(
                FieldPreference.SETUP_ONLY if is_opener else FieldPreference.SUB_DPS
            ),
            combat_start_priority=100 if is_opener else 0,
            max_field_time=self.MAX_FIELD_TIME,
        )

    def combat_plan(self, context: CombatContext):
        in_team = self.is_999night_team(self.task.chars) or self.is_chiz_abyss_team(
            self.task.chars
        )

        def _execute_skill(_ctx) -> bool:
            result = self.click_skill(time_out=SKILL_SHORT_TIMEOUT)
            if result:
                self._cooldowns.mark_used("skill", self.SKILL_REUSE_GUARD)
                self.sleep(self.SKILL_SETTLE_DURATION)
            return result

        skill = self.planner_action(
            tags={ActionTag.SKILL_ACTION},
            slot=ActionSlot.SKILL,
            execute=_execute_skill,
            name="iloy_skill",
            reason="iloy skill (gather + heal + ATK buff)",
            can_execute=lambda ctx: (
                not in_team
                or ctx.strict_route_wants_action(self, slot=ActionSlot.SKILL)
                or (self.skill_available() and self._cooldowns.is_ready("skill"))
            ),
            priority_ready=lambda _: (
                self.skill_available() and (not in_team or self._cooldowns.is_ready("skill"))
            ),
        )
        ultimate = self.click_ultimate_action(
            reason="iloy ultimate (dream state)",
            can_execute=lambda _: self.ultimate_available(),
        )

        def entry():
            skill_result = yield skill
            if skill_result:
                self.logger.info(f"{_LOG_PREFIX} skill: gather + heal + buff")
            else:
                self.logger.info(f"{_LOG_PREFIX} skill failed, continuing")

            ultimate_result = yield ultimate
            if ultimate_result:
                self.logger.info(f"{_LOG_PREFIX} dream state active, heavy attack")
                if self.is_current_char and not self.is_dead:
                    self.heavy_attack(self.HEAVY_ATTACK_DURATION)
            elif skill_result:
                self.logger.info(f"{_LOG_PREFIX} ult failed, heavy attack with skill buff")
                if self.is_current_char and not self.is_dead:
                    self.heavy_attack(self.HEAVY_ATTACK_DURATION)
            else:
                self.logger.info(
                    f"{_LOG_PREFIX} both skill and ult failed, no normal-attack fallback"
                )

            if in_team:
                self._request_mint_return(context)

        return self.plan(skill, ultimate, entry=entry)

    def _request_mint_return(self, context: CombatContext) -> None:
        """完成后请求薄荷(Mint)回场进行部署."""
        if context is None:
            return
        from src.char.Mint import Mint

        for char in self.task.chars:
            if isinstance(char, Mint):
                context.request_switch(
                    char, reason="return Mint after Iloy setup"
                )
                self.logger.info(f"{_LOG_PREFIX} requested Mint return")
                return

    def _fallback_attacks(self):
        """E+Q both failed: brief normal attacks to avoid empty-cycle."""
        deadline = self._now() + self.FALLBACK_DURATION
        while self._now() < deadline:
            if not self.is_current_char or self.is_dead:
                return
            self.check_combat()
            self.normal_attack()
            self.sleep(self.NORMAL_ATTACK_INTERVAL)

    def click_ultimate(self, send_click=True, wait_if_no_cd=0):
        """Hold the input through the dream-state ultimate animation."""
        result = False
        try:
            result = super().click_ultimate(
                send_click=send_click,
                wait_if_no_cd=wait_if_no_cd,
            )
            if result:
                self.sleep(0.7)
            return result
        finally:
            if result:
                self.task.mouse_up()

    def _wait_ultimate_unfreeze(self, start, click=False):
        self.task.mouse_down()
        return super()._wait_ultimate_unfreeze(start=start, click=click)

    def _now(self):
        return time.monotonic()

    def on_combat_end(self, chars):
        """战后清理."""
        self._cooldowns.reset()
