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

_LOG_PREFIX = "[Baicang]"


class Baicang(BaseChar):
    """Baicang main DPS. Q burst uses the Method-2 heavy combo (点按两次再长按).

    The burst chains heavy combos: tap normal attack twice, long-press for the
    charged back-jump talisman throw, then walk forward briefly to reset the combo
    before the weak 4th/5th normal hits. This uses the normal-attack key only, so it
    needs no dodge key and no mouse steering (target-lock keeps Baicang facing the
    enemy). Sound-triggered dodge/counter stays owned by BaseCombatTask. The combo
    mechanic and its timings are transcribed from an external guide (BV1Wy9bBWESK)
    and are NOT yet recording-verified; see docs/research/baicang.md for the source
    and the parameters that still need live measurement.
    """

    cn_name = "白藏"
    element = BaseChar.Element.RED

    MAX_FIELD_TIME = 0
    ULT_FIELD_DURATION = 12.0
    MIN_FIELD_TIME = 4.0
    FALLBACK_DODGE_DURATION = 1.5
    NORMAL_ATTACK_INTERVAL = 0.18
    ATTACK_SLICE_DURATION = 0.36
    DODGE_CLICK_INTERVAL = 0.12
    DODGE_SLICE_DURATION = 0.12
    SKILL_CHECK_INTERVAL = 0.8
    SKILL_CHECK_INTERVAL_BURST = 0.4  # faster E check inside burst to avoid missing the window
    SECOND_SKILL_MODE = "execute"  # disabled | observe | execute
    SKILL_READY_STREAK_THRESHOLD = 2
    SKILL_SHORT_TIMEOUT = 2.0
    DEFAULT_DIRECTION_KEY = None
    # Method-2 heavy combo (guide BV1Wy9bBWESK, "点按两次再长按"): tap normal attack twice,
    # then long-press (heavy) for the charged back-jump talisman throw, then walk forward
    # briefly to reset the combo before the weak 4th/5th normal hits. Uses the normal-attack
    # key only, so it needs NO dodge key and NO mouse steering (target-lock keeps Baicang
    # facing the enemy); BURST_DIRECTION_KEY is just the forward walk for the reset.
    # The earlier dodge-roll approach was live-confirmed broken (holding shift = sprint, zero
    # damage, and needs real-time mouse steering). All timings below UNVERIFIED, calibrate live.
    BURST_DIRECTION_KEY = "w"  # forward walk used for the combo reset
    HEAVY_TAP_COUNT = 2  # normal-attack taps before the heavy long-press
    HEAVY_TAP_INTERVAL = 0.18  # gap between the two taps
    # Long-press duration -> charged back-jump talisman throw. 0.6 charged only intermittently in
    # live play (2026-07-22); 0.9 adds margin above the charge threshold so it fires every combo.
    # Still UNVERIFIED -- if it over-holds or still mis-fires, tune live (try 0.8 / 1.0 / 1.2).
    HEAVY_HOLD_DURATION = 0.9
    WALK_RESET_DURATION = 0.4  # forward walk to reset the normal-attack combo
    ARC_CHECK_INTERVAL = 20.0  # keep R aligned with the weapon skill cooldown
    POST_SKILL_DODGE_DURATION = 1.0
    ABYSS_OPENER_TIMEOUT = 24.0

    @staticmethod
    def is_abyss_team(chars):
        from src.combat.team_strategies import is_baicang_abyss_team

        return is_baicang_abyss_team(chars)

    @classmethod
    def request_abyss_return(cls, context: CombatContext, chars, reason: str) -> None:
        """目标队辅助完成动作后显式请求白藏回场，即使白藏 E/Q 正在冷却。"""
        if context is None or not cls.is_abyss_team(chars):
            return
        baicang = next(char for char in chars if isinstance(char, cls))
        context.request_switch(baicang, reason=reason)

    def combat_policies(self, context: CombatContext) -> None:
        return None

    def describe_role(self):
        return RoleProfile(
            role=Role.MAIN_DPS,
            field_preference=FieldPreference.MAIN_DPS,
            max_field_time=self.MAX_FIELD_TIME,
        )

    def combat_plan(self, context: CombatContext):
        skill = self.planner_action(
            tags={ActionTag.SKILL_ACTION},
            slot=ActionSlot.SKILL,
            execute=lambda ctx: self.click_skill(time_out=self.SKILL_SHORT_TIMEOUT),
            name="baicang_skill",
            reason="baicang skill",
            can_execute=lambda _: self.skill_available(),
            priority_ready=lambda _: self.skill_available(),
        )
        ultimate = self.click_ultimate_action(
            reason="baicang ultimate",
            can_execute=lambda _: self.ultimate_available(),
        )
        fallback_dodge = self.planner_action(
            tags={ActionTag.DEFAULT_ACTION, ActionTag.DAMAGE},
            execute=lambda ctx: self._execute_fallback_dodge(),
            name="baicang_dodge_fallback",
            reason="baicang fallback dodge",
            priority_ready=lambda ctx: False,
        )

        def entry():
            ultimate_result = yield ultimate
            if ultimate_result:
                self._perform_burst(context)
                return

            skill_result = yield skill
            if skill_result:
                self._post_skill_dodge()
            else:
                yield fallback_dodge

        return self.plan(skill, ultimate, fallback_dodge, entry=entry)

    def _perform_burst(self, context: CombatContext = None):
        """Q 成功后的爆发输出循环: 第二套手法重击连招。

        攻略 BV1Wy9bBWESK, 见 docs/research/baicang.md。

        - 每轮: 点按普攻两下 → 长按重击(后跳丢符) → 往前走一段重置连招, 避开低伤的第四五段普攻
        - 全程只用普攻键, 不依赖闪避键, 也不需要鼠标实时转向 (锁定目标保证白藏朝向敌人)
        - 循环受 ``ULT_FIELD_DURATION`` 限时
        - 每轮后检查: deadline、is_current_char、is_dead、check_combat
        - R 每 ARC_CHECK_INTERVAL 释放; E 冷却好后按 streak 释放
        """
        self.logger.info(f"{_LOG_PREFIX} burst start")
        start = self._now()
        deadline = start + self.ULT_FIELD_DURATION

        track_second_skill = self.SECOND_SKILL_MODE != "disabled"
        ready_streak = 0
        last_check = start

        while self._now() < deadline:
            if not self.is_current_char:
                self.logger.info(f"{_LOG_PREFIX} burst end (not current char)")
                return
            if self.is_dead:
                self.logger.info(f"{_LOG_PREFIX} burst end (dead)")
                return

            self._heavy_combo()
            self.check_combat()

            # Use the shared global R cooldown (_last_default_arc_time) so burst
            # and normal state share one R timer. Previously last_arc started from
            # burst start, so with ULT_FIELD_DURATION=12s < ARC_CHECK_INTERVAL=20s
            # the burst-branch R never fired. Now a R cast in normal state before
            # the burst counts toward the cooldown, and a R cast in burst counts
            # for the next normal-state window.
            if self._now() - self._last_default_arc_time >= self.ARC_CHECK_INTERVAL:
                self._last_default_arc_time = self._now()
                self.send_arc_key(action_name=("baicang_burst_arc", self.index))

            if not track_second_skill:
                continue
            if self._now() - last_check < self.SKILL_CHECK_INTERVAL_BURST:
                continue

            last_check = self._now()
            if self.skill_available():
                ready_streak += 1
                if ready_streak == 1:
                    self.logger.info(
                        f"{_LOG_PREFIX} skill ready streak="
                        f"{ready_streak}/{self.SKILL_READY_STREAK_THRESHOLD}"
                    )
            else:
                if ready_streak > 0:
                    self.logger.debug(f"{_LOG_PREFIX} skill streak reset (was {ready_streak})")
                ready_streak = 0
                continue

            if ready_streak < self.SKILL_READY_STREAK_THRESHOLD:
                continue

            if self.SECOND_SKILL_MODE == "execute":
                if self._try_second_skill(context):
                    ready_streak = 0  # allow E to fire again after next cooldown
            else:
                self.logger.info(f"{_LOG_PREFIX} skill armed (observe mode)")
                ready_streak = 0

        self.logger.info(f"{_LOG_PREFIX} burst end")

    def _heavy_combo(self):
        """第二套手法一轮: 点按普攻 HEAVY_TAP_COUNT 下 → 长按重击(后跳丢符) → 往前走一段重置。

        长按重击用 ``heavy_attack`` (mouse_down/up), 点按用 ``normal_attack``。每步前后检查
        is_current_char/is_dead, 切人或死亡时立即停止。
        """
        for _ in range(self.HEAVY_TAP_COUNT):
            if not self.is_current_char or self.is_dead:
                return
            self.normal_attack()
            self.sleep(self.HEAVY_TAP_INTERVAL)
        if not self.is_current_char or self.is_dead:
            return
        self.heavy_attack(duration=self.HEAVY_HOLD_DURATION)
        if not self.is_current_char or self.is_dead:
            return
        self._walk_forward_reset()

    def _walk_forward_reset(self):
        """往前走一小段, 重置普攻连招段数, 避免打出低伤害的第四五段。方向键在 finally 中释放。"""
        key = self.BURST_DIRECTION_KEY or self.DEFAULT_DIRECTION_KEY
        if key is None:
            return
        self.task.send_key_down(key)
        try:
            self.sleep(self.WALK_RESET_DURATION)
        finally:
            self.task.send_key_up(key)

    def _try_second_skill(self, context: CombatContext = None):
        """参考 Nanally._try_skill_during_ultimate: 检查 reservation 后发送第二 E。"""
        if context is not None and not context.can_execute_action(self, slot=ActionSlot.SKILL):
            self.logger.info(f"{_LOG_PREFIX} second skill blocked by reservation")
            return False

        self.logger.info(f"{_LOG_PREFIX} second skill armed")
        clicked = self.click_skill(time_out=self.SKILL_SHORT_TIMEOUT)
        if clicked:
            self.logger.info(f"{_LOG_PREFIX} second skill executed")
        else:
            self.logger.info(f"{_LOG_PREFIX} second skill click failed")
        return clicked

    def _post_skill_dodge(self):
        """Legacy method name: execute normal attacks after an E-only entry."""
        self.logger.info(f"{_LOG_PREFIX} post-skill normal attacks")
        self._checkpointed_dodge(self.POST_SKILL_DODGE_DURATION)

    def _execute_fallback_dodge(self):
        """Legacy method name: bounded normal attacks when Q/E are unavailable."""
        if self.is_dead or not self.is_current_char:
            self.logger.info(f"{_LOG_PREFIX} fallback attacks skipped (dead or not current)")
            return False

        self.logger.info(f"{_LOG_PREFIX} fallback normal attacks")
        self._checkpointed_dodge(self.FALLBACK_DODGE_DURATION)

        if not self.is_current_char or self.is_dead:
            self.logger.info(f"{_LOG_PREFIX} fallback dodge ended (char changed or dead)")
            return False

        return True

    def _checkpointed_dodge(self, duration) -> bool:
        """Legacy method name: normal attacks with frequent sound-check checkpoints."""
        deadline = self._now() + max(duration, 0)
        direction_key = self.DEFAULT_DIRECTION_KEY
        try:
            if direction_key is not None:
                self.task.send_key_down(direction_key)
                self.sleep(0.01)
            while self._now() < deadline:
                if not self.is_current_char or self.is_dead:
                    return False
                # Periodic R during field time, sharing the same global R
                # cooldown as burst. _last_default_arc_time persists across
                # fallbacks so the ~20s cadence accumulates over multiple short
                # fallback windows.
                if self._now() - self._last_default_arc_time >= self.ARC_CHECK_INTERVAL:
                    self._last_default_arc_time = self._now()
                    self.send_arc_key(action_name=("baicang_field_arc", self.index))
                remaining = deadline - self._now()
                self._normal_attack_slice(min(self.ATTACK_SLICE_DURATION, remaining))
                self.sleep(0.01)
                self.check_combat()
        finally:
            if direction_key is not None:
                self.task.send_key_up(direction_key)
        return self.is_current_char and not self.is_dead

    def _normal_attack_slice(self, duration):
        if duration <= 0:
            return
        deadline = self._now() + duration
        while self._now() < deadline:
            if not self.is_current_char or self.is_dead:
                return
            self.normal_attack()
            remaining = deadline - self._now()
            if remaining > 0:
                self.sleep(min(self.NORMAL_ATTACK_INTERVAL, remaining))

    def _right_click_burst(self, duration):
        """持续右键点击 ``duration`` 秒，不管理方向键。"""
        if duration <= 0:
            return
        interval = self.DODGE_CLICK_INTERVAL
        start = self._now()
        while self._now() - start < duration:
            if not self.is_current_char or self.is_dead:
                return
            self.click(interval=interval, key="right")

    def _now(self):
        """可 patch 的时钟，供测试覆盖。"""
        return time.monotonic()

    def on_combat_end(self, chars):
        """战斗结束后清理。"""
        pass