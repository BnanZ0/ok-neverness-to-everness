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

_LOG_PREFIX = "[Adler]"
SKILL_SHORT_TIMEOUT = 2.0


class Adler(BaseChar):
    """阿德勒 - 咒系(RED)生存辅助。

    SUB_DPS, SETUP_ONLY: 入场叠业→E开盾→Q→切出。
    叠业+E 合并为单个 SKILL action，确保 planner 先检查 reservation。
    详细游戏机制见 docs/research/adler.md。
    """

    cn_name = "阿德勒"
    element = BaseChar.Element.RED
    MAX_FIELD_TIME = 0  # 禁止通用平A fallback
    YE_STACK_DURATION = 1.5
    YE_ATTACK_INTERVAL = 0.2

    def describe_role(self):
        return RoleProfile(
            role=Role.SUB_DPS,
            field_preference=FieldPreference.SETUP_ONLY,
            max_field_time=self.MAX_FIELD_TIME,
        )

    def combat_plan(self, context: CombatContext):
        skill = self.planner_action(
            tags={ActionTag.SKILL_ACTION},
            slot=ActionSlot.SKILL,
            execute=lambda ctx: self._stack_ye_then_skill(),
            name="adler_setup_skill",
            reason="adler stack ye + skill (shield)",
            priority_ready=lambda _: self.skill_available(),
        )
        ultimate = self.click_ultimate_action(reason="adler ultimate (AoE burst)")

        def entry():
            skill_result = yield skill
            if skill_result:
                self.logger.info(f"{_LOG_PREFIX} shield deployed")
                self.sleep(0.5)
                yield ultimate
            else:
                self.logger.info(f"{_LOG_PREFIX} setup skill failed, skipping ultimate")

        return self.plan(skill, ultimate, entry=entry)

    def _stack_ye_then_skill(self):
        """叠业→E 的合成执行，在 planner SKILL reservation 检查通过后调用。"""
        self._stack_ye()
        return self.click_skill(time_out=SKILL_SHORT_TIMEOUT)

    def _stack_ye(self):
        """入场快速普攻积累"业"层数。

        [EXTERNAL] 蓄力瞄准射击+2层/次，普攻+1层/次。
        此处使用普攻快速叠层，实机校准后可改为蓄力。
        """
        self.logger.info(f"{_LOG_PREFIX} stacking ye")
        start = self._now()
        while self._now() - start < self.YE_STACK_DURATION:
            if not self.is_current_char:
                return
            if self.is_dead:
                return
            self.check_combat()
            self.normal_attack()
            self.sleep(self.YE_ATTACK_INTERVAL)

    def _now(self):
        return time.monotonic()

    def on_combat_end(self, chars):
        """战后清理。不用于战斗内切人。"""
        pass
