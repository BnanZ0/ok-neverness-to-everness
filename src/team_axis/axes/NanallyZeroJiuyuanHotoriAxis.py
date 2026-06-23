from __future__ import annotations

import time

import numpy as np

from src.Labels import Labels
from src.team_axis.BaseTeamAxis import BaseTeamAxis, TeamAxisError


class NanallyZeroJiuyuanHotoriAxis(BaseTeamAxis):
    """娜娜莉、零、九原、浔的完整记录循环轴。"""

    axis_id = "nanally_zero_jiuyuan_hotori"
    name = "娜娜莉・零・九原・浔固定轴"
    description = (
        "浔记录并复制九原 E、零 E 和娜娜莉入场技，按双娜娜莉站场循环执行。"
        "轴来自B站攻略up：打游戏的老二。视频：BV1DVdcBZEf2"
    )
    team_signature = (
        "char_nanally",
        "char_zero",
        "char_jiuyuan",
        "char_hotori",
    )
    team_labels = ("娜娜莉", "零", "九原", "浔")

    NANALLY_EFFECT_END_TIMEOUT = 15.0
    NANALLY_SKILL_WINDOW_TIMEOUT = 12.0
    NANALLY_CD_CONFIRM_SAMPLES = 3
    NANALLY_Q_READY_CONFIRM_SAMPLES = 2
    NANALLY_ENTRY_SETTLE_TIME = 1.0
    NANALLY_SKILL_TO_Q_DELAY = 0.7
    HOTORI_ULTIMATE_DURATION = 13.0
    JIUYUAN_MAX_FLOWERS_HEAVY_DURATION = 1.8
    PORTRAIT_PROGRESS_TIMEOUT = 8.0
    PORTRAIT_PROGRESS_DELTA = 0.002
    PORTRAIT_PROGRESS_RISE_SAMPLES = 2
    EXPECTED_CYCLE_TIMEOUT = 2.0

    opening_steps = (
        "浔：进度满后 E，开始记录",
        "九原：E 聚怪",
        "零：Q → E",
        "娜娜莉：等浔头像进度上涨后开 E；等 0.7 秒判断 Q，Q 可用则 Q → R",
        "九原：长按重击清花",
        "浔：Q 复制记录，持续平 A，Q 后 13 秒切九原",
        "九原：Q → E",
        "零：过场充满协奏，娜娜莉入场技后立刻切回零",
        "零：有 Q 则 Q → E，否则直接 E",
        "娜娜莉：切入等 1 秒开 E；Q 可用则等 0.7 秒后 Q → R，否则平 A 等 Q",
        "九原：长按重击清花",
        "浔：切回浔，本轮结束",
    )
    cycle_steps = opening_steps

    def run_opening(self):
        self._run_record_cycle()

    def run_cycle(self):
        self._run_record_cycle()

    def _run_record_cycle(self):
        self._open_hotori_record_window()
        self._record_jiuyuan_and_zero()
        self._first_nanally_field_time()
        self._hotori_replay_and_a10()
        self._jiuyuan_marked_combo()
        self._zero_nanally_bridge()
        self._second_nanally_field_time()
        self._finish_cycle()

    def _finish_cycle(self):
        self.switch_to("char_jiuyuan")
        self._clear_jiuyuan_flowers()
        self.switch_to("char_hotori")

    def _record_jiuyuan_and_zero(self):
        self.switch_to("char_jiuyuan")
        self._require_action("九原 E 聚怪", self.skill)

        self.switch_to("char_zero")
        self._run_zero_qe_if_ready("零第一次入场")
        self._wait_expected_cycle_full("零第一次 E 后")

    def _first_nanally_field_time(self):
        self.switch_to("char_nanally", wait_intro=False)
        self._wait_hotori_portrait_progress()
        self._run_nanally_eqr(wait_after_switch=False)
        self._wait_expected_cycle_full("娜娜莉第一套结束后")

        self.switch_to("char_jiuyuan")
        self._clear_jiuyuan_flowers()

    def _hotori_replay_and_a10(self):
        self.switch_to("char_hotori")
        ultimate_started_at = time.monotonic()
        self._require_action("浔 Q 复制记录", self.ultimate)
        self.call_current("clear_records")

        elapsed = time.monotonic() - ultimate_started_at
        remaining = max(0.0, self.HOTORI_ULTIMATE_DURATION - elapsed)
        if remaining > 0:
            self.normal_attack(remaining)

    def _jiuyuan_marked_combo(self):
        self.switch_to("char_jiuyuan")
        self._require_action("九原 Q", self.ultimate)
        self._require_action("九原 Q 后 E", self.skill)

    def _zero_nanally_bridge(self):
        # 浔复制的零 E 会在零入场时补满协奏；娜娜莉只完成入场技便立刻切回零。
        self.switch_to("char_zero")
        self._wait_expected_cycle_full("浔复制零 E 后")
        self.switch_to("char_nanally", wait_intro=False)
        self.switch_to("char_zero", wait_intro=False)

        self._run_zero_qe_if_ready("零第二次入场")
        self._wait_expected_cycle_full("零第二轮 E 后")

    def _run_zero_qe_if_ready(self, phase: str):
        """零的统一分支：Q 可用则 Q→E，否则直接 E。"""

        zero = self.current_char()
        if zero.ultimate_available():
            self._require_action(f"{phase} Q", self.ultimate)
        self._require_action(f"{phase} E", self.skill)

    def _second_nanally_field_time(self):
        self.switch_to("char_nanally", wait_intro=False)
        self._run_nanally_eqr()
        self._wait_expected_cycle_full("娜娜莉第二套结束后")

    def _open_hotori_record_window(self):
        self.switch_to("char_hotori")
        hotori = self.current_char()
        ready = self.task.wait_until(
            hotori.skill_available,
            time_out=15,
            raise_if_not_found=False,
        )
        if not ready:
            raise TeamAxisError("浔左下角进度未满，无法开启 E 记录")
        self._require_action("浔 E 开始记录", lambda: self.skill(time_out=3))
        self.call_current("start_records")

    def _run_nanally_eqr(self, wait_after_switch=True):
        if wait_after_switch:
            self.sleep(self.NANALLY_ENTRY_SETTLE_TIME)
        self._require_action("娜娜莉 E", self.skill)
        self.sleep(self.NANALLY_SKILL_TO_Q_DELAY)

        nanally = self.current_char()
        if not nanally.ultimate_available() and not self._wait_nanally_q_during_skill_window():
            return

        self._require_action("娜娜莉 Q", self.ultimate)
        nanally.click_arc()
        self._wait_nanally_effects_end()

    def _wait_nanally_q_during_skill_window(self):
        """持续平 A 等 Q；E 的有效窗口超时后放弃本轮 Q。"""

        nanally = self.current_char()
        q_ready_samples = 0

        def q_ready():
            nonlocal q_ready_samples
            if nanally.ultimate_available():
                q_ready_samples += 1
            else:
                q_ready_samples = 0
            return q_ready_samples >= self.NANALLY_Q_READY_CONFIRM_SAMPLES

        detected = self.task.wait_until(
            q_ready,
            time_out=self.NANALLY_SKILL_WINDOW_TIMEOUT,
            post_action=nanally.normal_attack,
            raise_if_not_found=False,
        )
        if not detected:
            self.task.log_debug("team axis Nanally Q not ready before E window ended; skip Q")
        return bool(detected)

    def _wait_nanally_effects_end(self):
        """持续平 A，直到娜娜莉 E、Q 连续多帧同时进入冷却。"""

        nanally = self.current_char()
        confirmed_samples = 0

        def both_effects_ended():
            nonlocal confirmed_samples
            both_on_cooldown = nanally.has_cd("skill") and nanally.has_cd("ultimate")
            confirmed_samples = confirmed_samples + 1 if both_on_cooldown else 0
            return confirmed_samples >= self.NANALLY_CD_CONFIRM_SAMPLES

        ended = self.task.wait_until(
            both_effects_ended,
            time_out=self.NANALLY_EFFECT_END_TIMEOUT,
            post_action=nanally.normal_attack,
            raise_if_not_found=False,
        )
        if not ended:
            raise TeamAxisError("娜娜莉 E、Q 持续状态结束识别超时")

    def _clear_jiuyuan_flowers(self):
        # 现有视觉判据只能识别有/无花，无法确认数量；按六朵花的最高档时长清空。
        self.call_current(
            "fire_bullets",
            duration=self.JIUYUAN_MAX_FLOWERS_HEAVY_DURATION,
        )

    def _wait_expected_cycle_full(self, reason: str):
        current = self.current_char()
        if current.is_cycle_full():
            return True
        ready = self.task.wait_until(
            current.is_cycle_full,
            time_out=self.EXPECTED_CYCLE_TIMEOUT,
            post_action=current.normal_attack,
            raise_if_not_found=False,
        )
        if not ready:
            self.task.log_debug(f"team axis expected concerto full but not detected: {reason}")
        return bool(ready)

    def _wait_hotori_portrait_progress(self):
        """等待浔头像外圈进度出现连续向上增长。"""

        scores: list[float] = []
        minimum = None
        rising_samples = 0

        def progress_started():
            nonlocal minimum, rising_samples
            score = self._hotori_portrait_progress_score()
            if score is None:
                return False

            scores.append(score)
            self.task.log_debug(f"team axis Hotori portrait upward score: {score:.4f}")
            minimum = score if minimum is None else min(minimum, score)
            if len(scores) < 2:
                return False

            increased = score > scores[-2] and score - minimum >= self.PORTRAIT_PROGRESS_DELTA
            rising_samples = rising_samples + 1 if increased else 0
            return rising_samples >= self.PORTRAIT_PROGRESS_RISE_SAMPLES

        detected = self.task.wait_until(
            progress_started,
            time_out=self.PORTRAIT_PROGRESS_TIMEOUT,
            raise_if_not_found=False,
        )
        if not detected:
            raise TeamAxisError("浔头像边进度条上涨识别超时")
        return bool(detected)

    def _hotori_portrait_progress_score(self) -> float | None:
        """返回浔头像两侧亮色进度的向上加权分数。"""

        hotori = self.get_char("char_hotori")
        label_name = f"box_char_{hotori.index + 1}"
        try:
            label = Labels(label_name)
            box = self.task.get_box_by_name(label)
            roi = box.crop_frame(self.task.frame)
        except (AttributeError, KeyError, TypeError, ValueError):
            return None

        if roi is None or roi.size == 0 or roi.ndim != 3:
            return None

        height, width = roi.shape[:2]
        edge_x = max(2, round(width * 0.18))
        side_edges = np.zeros((height, width), dtype=bool)
        side_edges[:, :edge_x] = True
        side_edges[:, width - edge_x :] = True

        channels = roi[:, :, :3].astype(np.int16)
        bright_neutral = (channels.min(axis=2) >= 185) & (
            channels.max(axis=2) - channels.min(axis=2) <= 55
        )
        side_size = int(np.count_nonzero(side_edges))
        if side_size == 0:
            return None

        # 越靠近头像上方权重越高。进度从底部沿两侧向上增长时，分数会持续增加。
        upward_weights = np.linspace(1.0, 0.1, height, dtype=np.float32)[:, None]
        weighted_progress = (bright_neutral & side_edges) * upward_weights
        return float(weighted_progress.sum() / side_size)

    @staticmethod
    def _require_action(label: str, action):
        if not action():
            raise TeamAxisError(f"固定轴动作失败：{label}")
