import re
import time

from src.char.BaseChar import BaseChar
from src.combat.planner import CombatContext, Planner, RoleProfile


class Chiz(BaseChar):
    cn_name = "小吱"
    element = BaseChar.Element.WHITE
    ABYSS_ROUTE_TIMEOUT = 35.0
    ULT_FIELD_DURATION = 8.0
    MIN_FIELD_TIME = 4.0
    SKILL_SHORT_TIMEOUT = 2.0
    SKILL_CHAIN_MAX_USES = 3
    # During the 8s ultimate E's CD is fast and charges regenerate, so allow more casts than
    # the normal chain's 3; skill_available() (charges/CD) and the min interval still gate each
    # cast, this cap just stops the old limit from wasting regenerated charges.
    ULT_SKILL_MAX_USES = 8
    SKILL_CHAIN_NORMAL_ATTACKS = 2
    SKILL_CHAIN_ATTACK_INTERVAL = 0.35
    SKILL_CHAIN_MIN_E_INTERVAL = 0.6
    # Minimum yellow gauge percentage to consider E; below this the reading is noise. With the
    # calibrated yellow range the gate reads ~0.06-0.12 whenever the golden gauge is up during
    # the ultimate, so E is cast whenever a charge is ready (skill_available) rather than only at
    # rare peak-brightness moments.
    SKILL_GAUGE_MIN_YELLOW = 0.02

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @staticmethod
    def is_abyss_team(chars):
        from src.combat.team_strategies import is_chiz_abyss_team

        return is_chiz_abyss_team(chars)

    def _request_yingxu_route(self, context: CombatContext, opener: bool) -> None:
        from src.combat.team_strategies import request_chiz_route

        request_chiz_route(context, opener=opener)

    def describe_role(self):
        return RoleProfile(
            role=Planner.Role.MAIN_DPS,
            field_preference=Planner.FieldPreference.MAIN_DPS,
        )

    def combat_plan(self, context):
        ultimate = self.click_ultimate_action(
            can_execute=lambda _: self.ultimate_available(),
        )
        skill = self.planner_action(
            tags={
                Planner.ActionTag.SKILL_ACTION,
                Planner.ActionTag.ROUTE_WAIT_ACTION,
            },
            slot=Planner.ActionSlot.SKILL,
            execute=self.perform_skill_chain,
            name="Chiz_skill_chain",
            reason="chiz three-stage skill chain",
            can_execute=lambda _: self.skill_available(),
            priority_ready=lambda _: self.skill_available(),
        )

        def entry():
            ultimate_result = yield ultimate
            if ultimate_result:
                if self.perform_in_ult(context):
                    self._request_yingxu_route(context, opener=False)
                return
            yield skill

        return self.plan(ultimate, skill, entry=entry)

    def perform_skill_chain(self, context: CombatContext = None) -> bool:
        used = 0
        for _ in range(self.SKILL_CHAIN_MAX_USES):
            if not self._perform_skill_setup_attacks():
                break
            if not self.is_current_char or self.is_dead or not self.skill_available():
                break
            if context is not None and not context.can_execute_action(
                self,
                slot=Planner.ActionSlot.SKILL,
            ):
                break
            if not self._send_single_skill("chain", used + 1):
                break
            used += 1
        self.logger.info(f"[Chiz] skill chain used {used}/{self.SKILL_CHAIN_MAX_USES}")
        return used > 0

    def _perform_skill_setup_attacks(self) -> bool:
        for _ in range(self.SKILL_CHAIN_NORMAL_ATTACKS):
            if not self.is_current_char or self.is_dead:
                return False
            self.click_with_interval()
            self.sleep(self.SKILL_CHAIN_ATTACK_INTERVAL)
        return self.is_current_char and not self.is_dead

    def perform_in_ult(self, context: CombatContext = None) -> bool:
        box = self.task.box_of_screen(0.487, 0.775, 0.514, 0.798, name="percentage")
        self.task.wait_ocr(
            box=box,
            match=re.compile(r"-?\d+%", re.IGNORECASE),
            time_out=2,
            raise_if_not_found=False,
        )
        deadline = self._now() + self.ULT_FIELD_DURATION
        skill_uses = 0
        last_skill_at = float("-inf")
        while self._now() < deadline:
            if not self.is_current_char or self.is_dead:
                return False
            self.check_combat()
            red_pct = self.task.calculate_color_percentage(red_pct_color, box)
            yellow_pct = self.task.calculate_color_percentage(yellow_pct_color, box)
            if (
                skill_uses < self.ULT_SKILL_MAX_USES
                and self._now() - last_skill_at >= self.SKILL_CHAIN_MIN_E_INTERVAL
                and yellow_pct >= self.SKILL_GAUGE_MIN_YELLOW
                and yellow_pct > red_pct
                and self.skill_available()
                and (
                    context is None
                    or context.can_execute_action(self, slot=Planner.ActionSlot.SKILL)
                )
            ):
                if self._send_single_skill("ultimate", skill_uses + 1):
                    skill_uses += 1
                    last_skill_at = self._now()
                    self.logger.info(
                        f"[Chiz] ultimate skill gate accepted "
                        f"(yellow={yellow_pct:.3f}, red={red_pct:.3f}, use={skill_uses})"
                    )
            self.click_with_interval()
            self.sleep(0.1)
        self.logger.info(f"[Chiz] ultimate skill uses {skill_uses}/{self.ULT_SKILL_MAX_USES}")
        return self.is_current_char and not self.is_dead

    def _send_single_skill(self, phase: str, use_number: int) -> bool:
        if not self.is_current_char or self.is_dead:
            return False
        return bool(
            self.send_skill_key(
                action_name=("chiz_single_skill", self.index, phase, use_number),
            )
        )

    def _now(self):
        return time.monotonic()


# Coral-red gauge text shown when the 金谷 percentage is negative (do NOT cast E). Calibrated
# from recording frames: the negative text measures about R211 G110 B130 (span R181-247,
# G71-132, B98-169). The old narrow range (R250-255, G115-125, B115-120) detected none of it,
# so red_pct was always 0 and the yellow>red gate only worked by accident (yellow was also 0).
# Separated from the yellow range by green (yellow G>=185, red G<=145) so a pixel matches only one.
red_pct_color = {
    "r": (175, 255),
    "g": (60, 145),
    "b": (90, 175),
}

# Golden gauge (金谷) above Chiz's HP bar during her ultimate. Range calibrated from
# recording frames: the gauge text measures about R234 G236 B149 (span R191-251, G188-252,
# B99-169). The old narrow range (R250-255, B120-125) missed it and read 0, keeping the gate
# shut. This range still excludes the white waveform (B~255) and dark green badge (low R).
yellow_pct_color = {
    "r": (185, 255),
    "g": (185, 255),
    "b": (95, 175),
}
