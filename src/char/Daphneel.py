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

_LOG_PREFIX = "[Daphneel]"
SKILL_SHORT_TIMEOUT = 2.0
SKILL_RETRY_DELAY = 4.0
SKILL_REUSE_GUARD = 6.0


class Daphneel(BaseChar):
    """达芙蒂尔 - 暗系(PURPLE)爆发角色。

    Q 优先 → Q 后爆发窗口 → burst 内 E 最多尝试一次。
    弹反检测当前未实现，依赖 ultimate_available() 间接判断。
    详细游戏机制见 docs/research/daphneel.md。
    """

    cn_name = "达芙蒂尔"
    element = BaseChar.Element.PURPLE
    MAX_FIELD_TIME = 0  # 禁止通用平A fallback；只有 Q/E 就绪时入场
    ULT_BURST_DURATION = 1.5
    BURST_ATTACK_INTERVAL = 0.2

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._skill_ready_after = 0.0

    def describe_role(self):
        return RoleProfile(
            role=Role.SUB_DPS,
            field_preference=FieldPreference.SETUP_ONLY,
            max_field_time=self.MAX_FIELD_TIME,
        )

    def combat_plan(self, context: CombatContext):
        ultimate = self.click_ultimate_action(
            reason="daphneel ultimate (burst)",
            can_execute=lambda _: self.ultimate_available(),
        )
        skill = self.planner_action(
            tags={ActionTag.SKILL_ACTION},
            slot=ActionSlot.SKILL,
            execute=self._execute_skill,
            name="daphneel_skill",
            reason="daphneel skill",
            can_execute=lambda _: self._skill_ready(),
            priority_ready=lambda _: self._skill_ready(),
        )

        def entry():
            ultimate_result = yield ultimate
            if ultimate_result:
                self.logger.info(f"{_LOG_PREFIX} burst executed")
                self._perform_burst(context)
                self._request_baicang_return(context)
                return
            yield skill
            self._request_baicang_return(context)

        return self.plan(ultimate, skill, entry=entry)

    def _execute_skill(self, context: CombatContext = None) -> bool:
        clicked = self.click_skill(time_out=SKILL_SHORT_TIMEOUT)
        if clicked:
            self._skill_ready_after = self._now() + SKILL_REUSE_GUARD
            self.logger.info(
                f"{_LOG_PREFIX} skill reuse guarded for {SKILL_REUSE_GUARD:.1f}s"
            )
        else:
            self._skill_ready_after = self._now() + SKILL_RETRY_DELAY
            self.logger.info(f"{_LOG_PREFIX} skill retry suppressed for {SKILL_RETRY_DELAY:.1f}s")
        return clicked

    def _skill_ready(self) -> bool:
        return self._now() >= self._skill_ready_after and self.skill_available()

    def _request_baicang_return(self, context: CombatContext = None) -> None:
        from src.char.Baicang import Baicang

        Baicang.request_abyss_return(
            context,
            self.task.chars,
            reason="return Baicang after Daphneel burst",
        )

    def _perform_burst(self, context: CombatContext = None):
        """Q 成功后的爆发输出窗口 (参考 Chiz.perform_in_ult)。

        - 持续普攻输出，检测 E 是否可用
        - E 最多真实尝试一次：attempted 分离 used
        - reservation blocked 不消耗 attempted 配额
        - 循环受 ``ULT_BURST_DURATION`` 限时
        """
        self.logger.info(f"{_LOG_PREFIX} burst start")
        start = self._now()
        deadline = start + self.ULT_BURST_DURATION
        skill_attempted = False
        skill_used = False

        while self._now() < deadline:
            if not self.is_current_char:
                self.logger.info(f"{_LOG_PREFIX} burst end (not current char)")
                return
            if self.is_dead:
                self.logger.info(f"{_LOG_PREFIX} burst end (dead)")
                return

            self.check_combat()

            if not skill_attempted and self.skill_available():
                blocked = not self._try_skill_during_burst(context)
                if blocked:
                    # reservation blocked — 不消耗 attempted 配额，可有限等待
                    self.logger.debug(f"{_LOG_PREFIX} skill blocked by reservation, will retry")
                else:
                    skill_attempted = True
                    skill_used = True

            self.normal_attack()
            self.sleep(self.BURST_ATTACK_INTERVAL)

        self.logger.info(
            f"{_LOG_PREFIX} burst end (attempted={skill_attempted}, used={skill_used})"
        )

    def _try_skill_during_burst(self, context: CombatContext = None):
        """检查 reservation 后释放 E。

        Returns:
            True if skill was executed (success or fail).
            False if blocked by reservation (not attempted).
        """
        if context is not None and not context.can_execute_action(self, slot=ActionSlot.SKILL):
            return False

        self.logger.info(f"{_LOG_PREFIX} skill during burst")
        self._execute_skill(context)
        return True

    def _now(self):
        return time.monotonic()

    def on_combat_end(self, chars):
        """战后清理。不用于战斗内切人。"""
        self._skill_ready_after = 0.0
