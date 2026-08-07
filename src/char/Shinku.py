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

_LOG_PREFIX = "[Shinku]"
SKILL_SHORT_TIMEOUT = 2.0
SKILL_REUSE_GUARD = 6.0


class Shinku(BaseChar):
    """真红 - 光系(WHITE)主C.

    999夜挂机队主C: E 积累桀骜斗志 -> Q 一段大(进入13s强化状态) ->
    先手强化E -> 5段强化普攻充能 -> 强化E循环 ->
    Q 二段大(三段突进) -> Q 三段大(龙喷收尾) -> 请求伊洛伊回场.

    核心设计:
    - Q 一段大后进入 ENHANCED_STATE_DURATION 秒强化状态
    - 先手释放强化小技能(E), 然后5段普攻充能补满E能量
    - 循环: 5段强化普攻 -> 强化E, 直至二段大可用
    - 强化状态最后约3秒二段大可用, 释放后接三段大(龙喷)
    - 999夜队无盈蓄回能, Q2可能延迟, 强化状态结束后额外等待
    - 强化小技能用 SkillCooldownModel 管理复用
    - 在 999 夜队中: MAIN_DPS, 强化爆发后 request_switch 到 Iloy
    - 不在 999 夜队中: MAIN_DPS, 退化为 Q -> 爆发 -> 普攻

    [EXTERNAL] 攻略来源: 925G(gonglue/319414) + BV1PsTW6fEve
    """

    cn_name = "真红"
    element = BaseChar.Element.WHITE
    MAX_FIELD_TIME = 0  # 禁止通用平A fallback
    # --- 强化状态参数 (925G + BV1PsTW6fEve, UNVERIFIED) ---
    ENHANCED_STATE_DURATION = 13.0  # 强化状态持续时间 (925G: 十三秒)
    SECOND_ULT_READY_AT = 10.0  # 二段大可用时间点 (最后约3秒)
    ENHANCED_SKILL_NORMALS = 5  # 攒满强化小技能所需普攻段数 (925G: 五段强化普攻充能)
    ENHANCED_SKILL_REUSE_GUARD = 2.0  # 强化小技能复用间隔 (5段普攻后能量补满)
    # --- 爆发循环参数 ---
    NORMAL_ATTACK_INTERVAL = 0.18
    POST_ULT_SLEEP = 0.5  # Q 动画后短暂等待
    POST_Q2_DELAY = 0.8  # Q2后等Q3可用的延迟
    EXTENDED_ULT_WAIT = 3.0  # 强化状态结束后额外等待Q2 (999夜队无盈蓄回能)
    FALLBACK_DURATION = 2.0  # Q 失败时普攻兜底时长
    ABYSS_OPENER_TIMEOUT = 20.0  # opener route 超时

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._cooldowns = SkillCooldownModel(now_fn=lambda: self._now())

    @staticmethod
    def is_999night_team(chars):
        from src.combat.team_strategies import is_999night_team

        return is_999night_team(chars)

    def describe_role(self):
        return RoleProfile(
            role=Role.MAIN_DPS,
            field_preference=FieldPreference.MAIN_DPS,
            max_field_time=self.MAX_FIELD_TIME,
        )

    def combat_plan(self, context: CombatContext):
        in_team = self.is_999night_team(self.task.chars)

        def _execute_skill(_ctx) -> bool:
            result = self.click_skill(time_out=SKILL_SHORT_TIMEOUT)
            if result:
                self._cooldowns.mark_used("skill", SKILL_REUSE_GUARD)
            return result

        skill = self.planner_action(
            tags={ActionTag.SKILL_ACTION},
            slot=ActionSlot.SKILL,
            execute=_execute_skill,
            name="shinku_skill",
            reason="shinku skill (prime burst / enhanced skill)",
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
            reason="shinku ultimate (enhanced state / burst)",
            can_execute=lambda _: self.ultimate_available(),
        )

        def entry():
            # E first (opener route step 5 or cycle)
            skill_result = yield skill
            if skill_result:
                self.logger.info(f"{_LOG_PREFIX} skill: prime burst")
                self.sleep(0.3)

            # Q -> enhanced state (opener route step 6 or cycle)
            ultimate_result = yield ultimate
            if ultimate_result:
                self.logger.info(f"{_LOG_PREFIX} enhanced state entered")
                self.sleep(self.POST_ULT_SLEEP)
                self._perform_burst(context)
            else:
                self.logger.info(f"{_LOG_PREFIX} ult failed, fallback attacks")
                self._fallback_attacks()

            if in_team:
                self._request_ily_return(context)

        return self.plan(skill, ultimate, entry=entry)

    def _perform_burst(self, context: CombatContext = None):
        """Q 一段大后的爆发输出窗口.

        攻略优化 (925G 完整五段强化普攻充能打法):
        Phase 1: 先手释放强化小技能(E)
        Phase 2: 5段强化普攻充能 -> 强化E -> 循环
        Phase 3: 二段大(Q2) + 三段大(Q3)龙喷收尾
        Phase 4: 强化状态结束但Q2未放时, 额外等待EXTENDED_ULT_WAIT秒

        999夜队无盈蓄回能, Q2可能延迟, Phase 4确保不漏Q2
        """
        self.logger.info(f"{_LOG_PREFIX} burst start")
        start = self._now()
        deadline = start + self.ENHANCED_STATE_DURATION
        normal_count = 0
        enhanced_skill_count = 0
        second_ult_done = False
        third_ult_done = False

        # Phase 1: 先手强化小技能 (攻略925G: Q1后先手释放强化E)
        if self.skill_available() and self._cooldowns.is_ready("enhanced_skill"):
            self.logger.info(f"{_LOG_PREFIX} phase 1: opening enhanced skill")
            if self.click_skill(time_out=SKILL_SHORT_TIMEOUT):
                self._cooldowns.mark_used(
                    "enhanced_skill", self.ENHANCED_SKILL_REUSE_GUARD
                )
                enhanced_skill_count += 1
            self.sleep(0.3)

        # Phase 2 + 3: 普攻充能循环 + 二段大窗口
        while self._now() < deadline:
            if not self.is_current_char:
                self.logger.info(f"{_LOG_PREFIX} burst end (not current char)")
                return
            if self.is_dead:
                self.logger.info(f"{_LOG_PREFIX} burst end (dead)")
                return

            self.check_combat()
            elapsed = self._now() - start

            # Phase 3: 二段大窗口 (最后约3秒)
            if not second_ult_done and elapsed >= self.SECOND_ULT_READY_AT:
                if self.ultimate_available():
                    self.logger.info(
                        f"{_LOG_PREFIX} second ult at elapsed={elapsed:.1f}s, "
                        f"enhanced_skills={enhanced_skill_count}"
                    )
                    second_ok = self.click_ultimate()
                    second_ult_done = True
                    self.sleep(self.POST_ULT_SLEEP)

                    # 三段大(龙喷)收尾
                    if second_ok:
                        self.sleep(self.POST_Q2_DELAY)
                        if self.ultimate_available():
                            self.logger.info(f"{_LOG_PREFIX} third ult (dragon breath)")
                            third_ok = self.click_ultimate()
                            if third_ok:
                                third_ult_done = True
                            self.sleep(self.POST_ULT_SLEEP)
                    break
                else:
                    self.logger.debug(
                        f"{_LOG_PREFIX} second ult window but not available, keep attacking"
                    )

            # Phase 2: 普攻 + 强化E充能循环
            self.normal_attack()
            self.sleep(self.NORMAL_ATTACK_INTERVAL)
            normal_count += 1

            # 5段普攻后释放强化E (攻略925G: 五段强化普攻自动补满小技能能量)
            if normal_count >= self.ENHANCED_SKILL_NORMALS:
                if self.skill_available() and self._cooldowns.is_ready("enhanced_skill"):
                    if context is not None and not context.can_execute_action(
                        self, slot=ActionSlot.SKILL
                    ):
                        self.logger.debug(
                            f"{_LOG_PREFIX} enhanced skill blocked by reservation"
                        )
                    else:
                        self.logger.info(
                            f"{_LOG_PREFIX} enhanced skill "
                            f"(charge #{enhanced_skill_count + 1})"
                        )
                        if self.click_skill(time_out=SKILL_SHORT_TIMEOUT):
                            self._cooldowns.mark_used(
                                "enhanced_skill", self.ENHANCED_SKILL_REUSE_GUARD
                            )
                            enhanced_skill_count += 1
                        normal_count = 0

        # Phase 4: 强化状态结束但Q2未放, 额外等待 (999夜队无盈蓄回能)
        if not second_ult_done:
            extended_deadline = deadline + self.EXTENDED_ULT_WAIT
            self.logger.info(
                f"{_LOG_PREFIX} enhanced state ended, waiting for Q2 "
                f"(max {self.EXTENDED_ULT_WAIT}s)"
            )
            while self._now() < extended_deadline:
                if not self.is_current_char or self.is_dead:
                    return
                self.check_combat()
                if self.ultimate_available():
                    self.logger.info(f"{_LOG_PREFIX} delayed second ult")
                    second_ok = self.click_ultimate()
                    second_ult_done = True
                    self.sleep(self.POST_ULT_SLEEP)
                    if second_ok:
                        self.sleep(self.POST_Q2_DELAY)
                        if self.ultimate_available():
                            self.logger.info(f"{_LOG_PREFIX} delayed third ult")
                            third_ok = self.click_ultimate()
                            if third_ok:
                                third_ult_done = True
                            self.sleep(self.POST_ULT_SLEEP)
                    break
                self.normal_attack()
                self.sleep(self.NORMAL_ATTACK_INTERVAL)

        self.logger.info(
            f"{_LOG_PREFIX} burst end (enhanced_skills={enhanced_skill_count}, "
            f"second_ult={'done' if second_ult_done else 'pending'}, "
            f"third_ult={'done' if third_ult_done else 'pending'})"
        )

    def _fallback_attacks(self):
        """Q 失败时的简单普攻兜底."""
        deadline = self._now() + self.FALLBACK_DURATION
        while self._now() < deadline:
            if not self.is_current_char or self.is_dead:
                return
            self.check_combat()
            self.normal_attack()
            self.sleep(self.NORMAL_ATTACK_INTERVAL)

    def _request_ily_return(self, context: CombatContext) -> None:
        """爆发完成后请求伊洛伊回场开始下一轮循环."""
        if context is None:
            return
        from src.char.Iloy import Iloy

        for char in self.task.chars:
            if isinstance(char, Iloy):
                context.request_switch(
                    char, reason="return Iloy after Shinku burst"
                )
                self.logger.info(f"{_LOG_PREFIX} requested Iloy return")
                return

    def _now(self):
        return time.monotonic()

    def on_combat_end(self, chars):
        """战后清理."""
        self._cooldowns.reset()
