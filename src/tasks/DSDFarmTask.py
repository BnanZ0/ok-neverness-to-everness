import time

import cv2
import numpy as np
from ok import TaskDisabledException
from qfluentwidgets import FluentIcon

from src.combat.BaseCombatTask import BaseCombatTask, NotInCombatException
from src.Labels import Labels
from src.sound_trigger.SoundCombatContext import SoundCombatContext
from src.tasks.BaseNTETask import Box
from src.tasks.NTEOneTimeTask import NTEOneTimeTask

SPACE = "&nbsp;" * 4 + "-"

# ruff: noqa: E501
INST = (
    "手动传送一次目标篝火后不要转动视角，直接开始任务。\n\n"
    "巧克力火山-底层最左边的篝火\n"
    f"{SPACE}火山有两层!!! 目标是*底层*整个地图最靠左的篝火\n"
    f"{SPACE}这个篝火只有二周目以后才能到达, 推荐在这里刷到100级\n"
    f"{SPACE}跟跑视频: https://b23.tv/qsEVcDO\n\n"
    "赤龙古堡-龙之高塔室外篝火\n"
    f"{SPACE}龙之高塔只有两个篝火，室外旁边有棵树的篝火\n"
    f"{SPACE}推荐三周目才来这里, 主要目的是刷纽扣\n\n"
    "赤龙古堡-残丝长巷篝火\n"
    f"{SPACE}残丝长巷附近只有三个篝火，唯一在室内的篝火\n"
    f"{SPACE}推荐三周目才来这里, 主要目的是刷纽扣\n\n"
    "烬火大道-右侧第一个篝火\n"
    f"{SPACE}烬火大道地图右侧的第一个传送点, 传送后点击篝火休息然后一直走即可\n"
    f"{SPACE}推荐三周目才来这里, 主要目的是刷纽扣\n\n"
    "刷纽扣点\n"
    f"{SPACE}传送后直走到头左转即可遇到怪, 不需要攻击只靠辅助闪避\n"
    f"{SPACE}敌人会自己死掉, 推荐开启声音触发闪避功能"
)

EN_INST = (
    "After manually teleporting to the target checkpoint, do not rotate the camera. Start the task immediately.\n\n"
    "Chocolate Volcano - Leftmost Checkpoint on the Bottom Layer\n"
    f"{SPACE}The volcano has two layers!!! The target is the leftmost checkpoint on the *Bottom Layer*.\n"
    f"{SPACE}This checkpoint is only accessible in New Game+ (NG+). Recommended for grinding to Lv.100.\n"
    f"{SPACE}Video Guide: https://b23.tv/qsEVcDO\n\n"
    "Red Dragon Castle - Dragon Tower (Outdoor Checkpoint)\n"
    f"{SPACE}There are only two checkpoints in the Dragon Tower; choose the outdoor one next to a tree.\n"
    f"{SPACE}Recommended for NG++ (3rd playthrough), mainly for farming Buttons.\n\n"
    "Red Dragon Castle - Silken Alley Checkpoint\n"
    f"{SPACE}There are only three checkpoints near Silken Alley; this is the only indoor one.\n"
    f"{SPACE}Recommended for NG++ (3rd playthrough), mainly for farming Buttons.\n\n"
    "Ember Avenue - First Checkpoint on the Right\n"
    f"{SPACE}The first teleport point on the right side of the Ember Avenue map. Rest at the bonfire then walk forward.\n"
    f"{SPACE}Recommended for NG++ (3rd playthrough), mainly for farming Buttons.\n\n"
    "Button Farm Spot\n"
    f"{SPACE}Walk forward then turn left to find enemies. Uses auto-dodge only, no attacking needed.\n"
    f"{SPACE}Enemies die on their own. Enable sound trigger dodge."
)


class DSDFarmTask(NTEOneTimeTask, BaseCombatTask):
    CONF_LOCATION = "位置"
    CONF_USE_ULT = "使用终结技"
    CONF_DONT_SWITCH = "战斗时不切人"
    CONF_MAX_COMBAT_TIME = "战斗时长上限"
    CONF_WAIT_FULL_DURATION = "战斗后等待至时长上限"
    CONF_DODGE_ONLY = "辅助闪避(不攻击)"
    BUTTON_FARM_RUN_SLOT = 3
    BUTTON_FARM_COMBAT_SLOT = 4
    BUTTON_FARM_RUN_TIMEOUT = 8.0
    # Bonfire search region for the button-farm checkpoint on the map.
    # Must cover the bonfire icon but exclude other nearby teleport points.
    BUTTON_FARM_BONFIRE_BOX = (0.10, 0.30, 0.60, 0.95)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "九百九十九夜"
        self.description = "挂机刷经验"
        self.icon = FluentIcon.FLAG
        _locale = self.get_app_locale()
        self.instructions = INST if _locale and "zh" in _locale else EN_INST
        self.locations = [
            "巧克力火山-底层最左边的篝火",
            "赤龙古堡-龙之高塔室外篝火",
            "赤龙古堡-残丝长巷篝火",
            "烬火大道-右侧第一个篝火",
            "刷纽扣点",
        ]
        self.add_rounds_config()
        self.default_config.update(
            {
                self.CONF_LOCATION: self.locations[0],
                self.CONF_USE_ULT: True,
                self.CONF_DONT_SWITCH: False,
                self.CONF_MAX_COMBAT_TIME: 1200,
                self.CONF_WAIT_FULL_DURATION: False,
                self.CONF_DODGE_ONLY: False,
            }
        )

        self.config_type.update(
            {
                self.CONF_LOCATION: {
                    "type": "drop_down",
                    "options": self.locations,
                },
            }
        )
        self.combat_detect_policy.miss_required = 3
        self.combat_detect_policy.uncertain_seconds = 2
        self.do_teleport_on_spot = False
        self.team_dead = False
        self.dodge_only_mode = False
        self._stop_requested = False
        self._abort = False

    def disable(self):
        """Stop this task immediately, before its worker observes cancellation.

        One-time task cancellation is delivered on the next framework action.
        Clear the shared sound owner and release held movement keys here so the
        brief interval before that action cannot produce another dodge or run.

        Key release goes through interaction.send_key_up directly, bypassing
        BaseTask.send_key_up which calls executor.reset_scene() and
        check_enabled() -- those are unsafe to invoke from the GUI thread
        (the thread that calls disable()) because they read and mutate
        executor-internal state (_frame, scene, current_task) that the
        executor thread may be using at the same moment.
        """
        self._stop_requested = True
        SoundCombatContext().clear_task_if(self)
        try:
            for key in ("w", "a", "s", "d", "lshift"):
                self.executor.interaction.send_key_up(key)
        except Exception as error:
            self.log_warning("button farm: failed to release a movement key", error)
        super().disable()

    def run(self):
        self._stop_requested = False
        self.sleep_check_skip.all = True
        try:
            super().run()
            self.do_run()
        except TaskDisabledException:
            pass
        except Exception as e:
            self.log_error("DSDFarmTask Error", e)
        finally:
            self.sleep_check_skip.all = False
            # Never leave a stopped one-time task as the global sound input
            # owner; otherwise real-time monitoring can execute stale farm
            # actions after this task has stopped.
            SoundCombatContext().clear_task_if(self)

    def do_run(self):
        self.do_teleport_on_spot = False
        self._abort = False
        if not self._is_button_farm_location():
            self.deside_map_zoom()
        if not self._teleport_to_configured_start():
            return
        self.start_rounds()
        while self.begin_round():
            self._keep_game_window_alive()
            interac_found = False
            for _attempt in range(3):
                try:
                    self.wait_until(
                        self.find_interac,
                        time_out=10,
                        raise_if_not_found=True,
                    )
                    interac_found = True
                    break
                except TaskDisabledException:
                    raise
                except Exception:
                    self.log_info(f"find_interac attempt {_attempt + 1} failed, retrying")
                    self.sleep(2)
                    if _attempt < 2:
                        self.send_key("w", down_time=0.5)
                        self.sleep(0.5)
                        self.send_key("s", down_time=0.5)
                        self.sleep(0.5)
            if not interac_found:
                self.log_error("find_interac failed after 3 attempts, stopping")
                self.add_failed("find_interac failed")
                break
            combat_started = False
            for _attempt in range(3):
                try:
                    self.wait_until(
                        lambda: not self.is_in_team(),
                        pre_action=lambda: self.send_interac(handle_claim=False),
                        time_out=10,
                        raise_if_not_found=True,
                    )
                    combat_started = True
                    break
                except TaskDisabledException:
                    raise
                except Exception:
                    self.log_info(f"enter combat attempt {_attempt + 1} failed, retrying")
                    self.sleep(2)
                    if _attempt < 2:
                        self.ensure_main()
            if not combat_started:
                self.log_error("failed to enter combat after 3 attempts, stopping")
                self.add_failed("failed to enter combat")
                break
            self.sleep(2)
            self.operate_click(0.057, 0.218)
            self.sleep(0.5)
            self.ensure_main()
            if self.do_teleport_on_spot:
                self.sleep(0.5)
                self.teleport_on_spot()
                self.ensure_main()
            self.deside_action()
            if self._abort:
                self.log_error("task aborted: route teleport failed")
                self.add_failed("route teleport failed")
                break
            self.next_frame()
            self.add_success()
        self.finish_rounds()

    def _keep_game_window_alive(self):
        """Bring the game window to front to prevent Windows from minimizing it
        during long idle sessions."""
        try:
            self.bring_to_front(after_sleep=0.5)
        except TaskDisabledException:
            raise
        except Exception:
            pass

    def sleep_check(self):
        super().sleep_check()
        if self.check_monthly_card():
            self.handle_monthly_card()

    def can_sound_trigger(self) -> bool:
        """Fail closed immediately after this one-time task stops."""
        return bool(
            not getattr(self, "_stop_requested", False)
            and getattr(self, "running", False)
            and super().can_sound_trigger()
        )

    def _teleport_to_configured_start(self) -> bool:
        """Put routes with a fixed spawn point at that point before round one."""
        if not self._is_button_farm_location():
            return True

        # Button farm: skip the initial teleport.
        #
        # The instruction tells the user to manually teleport to the target
        # bonfire before starting.  If we also teleport, two problems occur:
        #
        # 1. When the character is standing ON the target bonfire, the
        #    character arrow icon on the map covers the bonfire icon.
        #    find_feature then either misses it (retrying 3 times, each
        #    opening and closing the map) or matches a *nearby* bonfire
        #    and teleports the character to the wrong spot.
        #
        # 2. deside_map_zoom() and the teleport each open the map
        #    separately ("opens map twice").  The user's default zoom is
        #    already medium, so the zoom-setting pass is redundant.
        #
        # The loop teleport at the end of location_4 still works because
        # after combat the character is NOT on the bonfire.
        self.log_info("button farm: skipping initial teleport (user positions manually)")
        return True

    def _button_farm_bonfire_box(self) -> Box:
        """Map region containing the button-farm bonfire from the reference run."""
        return self.box_of_screen(*self.BUTTON_FARM_BONFIRE_BOX)

    def _button_farm_ensure_teleport(self, box: Box) -> bool:
        """Teleport to the button-farm bonfire; fail fast without movement recovery.

        Unlike the default ensure_teleport, this does NOT fall back to
        teleport_on_spot (map center) or send S/W movement keys to recover.
        A wrong spawn point is worse than stopping the task, because the
        character could end up in an unknown area and run into walls.

        zoom='mid' is set inside teleport_to_bonfire so that a single map
        open both adjusts zoom and clicks the bonfire, avoiding the previous
        'open map twice' issue (once for zoom, once for teleport).
        """
        return self.ensure_teleport(
            lambda: self.teleport_to_bonfire(box, threshold=0.6, zoom="mid"),
            fallback_on_spot=False,
            max_retries=3,
            recover_position=False,
        )

    def _is_button_farm_location(self) -> bool:
        """True when the selected location is the dedicated button-farm preset.

        Only ``刷纽扣点`` (the last entry in ``self.locations``) uses the
        dodge-only route.  Other entries have their own route methods
        (location_0 through location_3) and must not be affected by
        button-farm-specific skips (initial teleport, map zoom).
        """
        return self.config.get(self.CONF_LOCATION) in self.locations[4:]

    def deside_map_zoom(self):
        location = self.config.get(self.CONF_LOCATION, None)
        if location == self.locations[0]:
            self.map_zoom(zoom="max")
        elif location == self.locations[1]:
            self.map_zoom(zoom="mid")
        elif location == self.locations[2]:
            self.map_zoom(zoom="mid")
        elif location == self.locations[3]:
            self.map_zoom(zoom="mid")
        elif self._is_button_farm_location():
            self.map_zoom(zoom="mid")

    def deside_action(self):
        self.do_teleport_on_spot = False
        location = self.config.get(self.CONF_LOCATION, None)

        if location == self.locations[0]:
            self.location_0()
        elif location == self.locations[1]:
            self.location_1()
        elif location == self.locations[2]:
            self.location_2()
        elif location == self.locations[3]:
            self.location_3()
        elif self._is_button_farm_location():
            self.location_4()

    def location_0(self):
        if self.walk_until_combat(run=True, delay=1):
            self.deside_combat_action()
        self.sleep(0.5)
        self.ensure_teleport(lambda: self.teleport_to_nearest_bonfire())

    def location_1(self):
        self.send_key_down("w")
        self.sleep(0.37)
        self.send_key_down("lshift")
        self.sleep(0.12)
        self.send_key_up("lshift")
        self.sleep(4.11)
        self.send_key_up("w")
        self.sleep(0.51)
        self.send_key_down("s")
        self.sleep(0.40)
        self.send_key_up("s")
        self.sleep(0.18)
        self.send_key_down("d")
        self.sleep(0.36)
        self.send_key_down("w")
        self.sleep(0.5)
        for _ in range(5):
            self.send_key_down("d")
            self.sleep(0.5)
            self.send_key_up("d")
            self.sleep(0.8)
        self.sleep(2)
        self.send_key_up("w")
        if self.wait_until(self.in_combat, time_out=10):
            self.deside_combat_action()
        self.sleep(0.5)
        box = self.box_of_screen(0.498, 0.102, 0.931, 0.827)
        self.ensure_teleport(lambda: self.teleport_to_top_bonfire(box))

    def location_2(self):
        self.send_key_down("w")
        self.sleep(0.20)
        self.send_key("lshift")
        self.sleep(2.80)
        self.send_key_down("a")
        self.sleep(0.10)
        self.send_key_up("w")
        self.sleep(2.10)
        self.send_key_up("a")
        if self.wait_until(self.in_combat, time_out=10):
            self.deside_combat_action()
        self.sleep(0.5)
        box = self.box_of_screen(0.410, 0.234, 0.560, 0.556)
        self.do_teleport_on_spot = True
        self.ensure_teleport(lambda: self.teleport_to_top_bonfire(box))

    def location_3(self):
        ret = False
        try:
            self.middle_click(after_sleep=0.2)
            self.send_key_down("w")
            self.sleep(0.1)
            self.send_key("lshift")
            self.sleep(0.3)
            for _ in range(4):
                self.send_key("a", down_time=0.18)
                self.sleep(0.35)
            ret = bool(self.wait_until(self.in_combat, time_out=10))
            self.sleep(1)
        finally:
            self.send_key_up("w")
        if ret:
            self.deside_combat_action()
        self.sleep(0.5)
        box = self.box_of_screen(0.10, 0.50, 0.50, 0.95)
        self.ensure_teleport(lambda: self.teleport_to_bonfire(box, threshold=0.6))

    def location_4(self):
        """Button farm route: switch to slot 3, sprint straight then arc left into courtyard.

        After leaving the bonfire, sprint straight (W) for ~1.4s down the short
        corridor, then ADD A while still holding W (W+A diagonal) to arc left
        through the doorway into the courtyard. Release A once through, keep
        holding W to run up to enemies. W is NEVER released during the turn --
        releasing W would cause the character to strafe sideways in place
        instead of moving forward through the doorway.
        """
        self._switch_to_slot(self.BUTTON_FARM_RUN_SLOT)
        self.dodge_only_mode = True
        ret = False
        try:
            self.middle_click(after_sleep=0.2)
            self.send_key_down("w")
            self.sleep(0.1)
            self.send_key("lshift")
            self.sleep(0.3)
            # Sprint straight down the corridor (W only).
            # Corridor is short; ~1.4s brings us to the doorway on the left.
            self.sleep(1.4)
            # Add left while KEEPING W held -- forward-left diagonal through doorway.
            self.send_key_down("a")
            self.sleep(0.7)
            self.send_key_up("a")
            # Continue forward (W stays held) into the courtyard to find enemies.
            ret = bool(self.wait_until(self.in_combat, time_out=10))
            self.sleep(1)
        finally:
            self.send_key_up("w")
        # dodge_only_mode must stay True through combat so that
        # deside_combat_action() routes into _dodge_only_combat().
        # Reset it only after combat (or missed-combat handling) finishes.
        try:
            if ret:
                self.deside_combat_action()
            else:
                self.log_warning("button farm route missed combat, resetting at checkpoint")
        finally:
            self.dodge_only_mode = False
        self.sleep(0.5)
        box = self._button_farm_bonfire_box()
        if not self._button_farm_ensure_teleport(box):
            self.log_error("button farm reset teleport failed, aborting task")
            self._abort = True

    def _walk_with_stuck_check(self, time_out=6):
        """Walk forward until combat starts or character gets stuck.

        Returns:
            bool: True if combat was detected.
        """
        deadline = time.monotonic() + time_out
        prev_frame = None
        stuck_count = 0
        recovery_count = 0
        while time.monotonic() < deadline:
            if self.in_combat():
                return True
            self.sleep(0.5)
            current_frame = self.frame.copy() if self.frame is not None else None
            if prev_frame is not None and current_frame is not None:
                if self._is_stuck(prev_frame, current_frame):
                    stuck_count += 1
                    if stuck_count >= 3:
                        # Alternate recovery direction: first try right,
                        # then left on the next stuck event. This handles
                        # corridors where the wall can be on either side.
                        recovery_count += 1
                        direction = "d" if recovery_count % 2 == 1 else "a"
                        self.log_info(f"stuck detected, adjusting direction: {direction}")
                        self.send_key_up("w")
                        self.send_key("s", down_time=0.3)
                        self.send_key(direction, down_time=0.3)
                        self.sleep(0.2)
                        self.send_key_down("w")
                        stuck_count = 0
                        prev_frame = None
                        continue
                else:
                    stuck_count = 0
            prev_frame = current_frame
        return False

    def _is_stuck(self, prev_frame, current_frame) -> bool:
        """Detect if the character is stuck by comparing center screen frames.

        If the center region pixel change is below 1%, the character
        is considered not moving.  The threshold is higher than the
        original 0.5% to avoid false positives in dark corridors where
        uniform walls produce minimal frame difference even when moving.
        """
        try:
            h, w = current_frame.shape[:2]
            y1, y2 = int(h * 0.3), int(h * 0.7)
            x1, x2 = int(w * 0.3), int(w * 0.7)
            curr_crop = current_frame[y1:y2, x1:x2]
            prev_crop = prev_frame[y1:y2, x1:x2]
            diff = cv2.absdiff(curr_crop, prev_crop)
            gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
            _, thresh = cv2.threshold(gray, 25, 255, cv2.THRESH_BINARY)
            ratio = float(np.count_nonzero(thresh)) / thresh.size
            return ratio < 0.01
        except Exception:
            return False

    def _switch_to_slot(self, slot: int, verify: bool = True):
        """Switch to the given party slot (1-based) by pressing the number key.

        When verify=True (default), retries until in_team() confirms the
        switch.  When verify=False, just sends the key without checking --
        used in combat where in_team() may not be reliable.
        """
        key = str(slot)
        target_index = slot - 1
        try:
            if verify:
                in_team, current_index, _ = self.in_team()
                if not in_team:
                    self.log_info(f"_switch_to_slot({slot}): not in team, sending key only")
                    self.send_key(key, after_sleep=0.3)
                    return
                if current_index == target_index:
                    return
                self.log_info(f"_switch_to_slot({slot}): switching from slot {current_index + 1}")
                deadline = time.time() + 5
                while time.time() < deadline:
                    self.send_key(key, after_sleep=0.2)
                    in_team, current_index, _ = self.in_team()
                    if in_team and current_index == target_index:
                        self.log_info(f"_switch_to_slot({slot}): ok")
                        return
                    self.sleep(0.2)
                self.log_warning(f"_switch_to_slot({slot}): timed out")
            else:
                self.log_info(f"_switch_to_slot({slot}): sending key {key} (no verify)")
                self.send_key(key, after_sleep=0.3)
        except Exception as e:
            self.log_error(f"_switch_to_slot({slot}) error", e)

    def ensure_teleport(
        self,
        fun,
        fallback_on_spot=True,
        max_retries=5,
        recover_position=True,
    ):
        origin_fun = None
        if self.team_dead:
            origin_fun = fun
            fun = self.teleport_on_spot
        switch = False
        for _attempt in range(max_retries):
            self._keep_game_window_alive()
            try:
                if fun():
                    return True
            except TaskDisabledException:
                raise
            except Exception as e:
                self.log_warning(f"teleport attempt {_attempt + 1} error: {e}")
            self.ensure_main()
            if recover_position:
                self.sleep(0.5)
                key = "w" if switch else "s"
                self.send_key(key, down_time=3)
                switch = not switch
            if origin_fun:
                fun = origin_fun
        self.log_warning(f"ensure_teleport failed after {max_retries} retries")
        return self.teleport_on_spot() if fallback_on_spot else False

    def deside_combat_action(self):
        dodge_only = getattr(self, "dodge_only_mode", False) or self.config.get(
            self.CONF_DODGE_ONLY, False
        )
        if dodge_only:
            self._dodge_only_combat()
            return

        with self.skip_sleep_checks() as skip:
            skip.all = False
            max_combat_time = self.config.get(self.CONF_MAX_COMBAT_TIME, 1200)

            session = self.combat_session
            session.switch_enabled = not self.config.get(
                self.CONF_DONT_SWITCH, False
            )
            session.use_ultimate = self.config.get(self.CONF_USE_ULT, True)
            start_combat = time.time()
            self.combat_once(max_combat_time=max_combat_time)
            self.team_dead = False
            while not self.is_in_team():
                self.team_dead = True
                self.operate_click(0.501, 0.777, after_sleep=0.5)
                self.send_key("esc", after_sleep=2)
                self.next_frame()
            if self.team_dead:
                return
            if self.config.get(self.CONF_WAIT_FULL_DURATION):
                remaining_time = max_combat_time - (time.time() - start_combat)
                if remaining_time > 0:
                    self.log_info(
                        f"combat ended early, waiting {remaining_time:.1f}s to fill duration"
                    )
                    end_time = time.time() + remaining_time
                    while time.time() < end_time:
                        self._keep_game_window_alive()
                        self.sleep(min(30, end_time - time.time()))

    def _dodge_only_combat(self, max_time=1200):
        """辅助闪避模式: 不攻击, 仅靠声音触发闪避系统自动闪避.

        run() sets sleep_check_skip.all = True, which disables both
        sound-triggered dodge and combat-end detection.  We must
        re-enable them here, otherwise the character never dodges
        and never exits the loop after combat ends.

        - sound_combat_context=False  -> sleep_check triggers dodge on attack audio
        - check_combat=False         -> sleep_check raises NotInCombatException when combat ends
        """
        self.log_info("dodge-only combat start")
        self.wait_until(self.in_combat, time_out=200, raise_if_not_found=False)
        # Enter combat -> switch to the configured survivor.
        self._switch_to_slot(self.BUTTON_FARM_COMBAT_SLOT, verify=False)
        self._apply_sound_config(dodge_action=self._dodge_without_direction)
        with self.skip_sleep_checks() as skip:
            skip.all = False
            try:
                deadline = time.time() + max_time
                while time.time() < deadline:
                    self.sleep(0.1)
            except NotInCombatException:
                self.log_info("dodge-only combat end (combat finished)")
            except TaskDisabledException:
                raise
            except Exception as e:
                self.log_error("dodge-only combat error", e)
            finally:
                self.combat_end()

        self.wait_in_team(time_out=60, settle_time=1, raise_if_not_found=False)
        self.click(key="middle")
        self.sleep(1)

    def _dodge_without_direction(self):
        """Dodge once without forcing a camera-relative movement direction.

        The farm begins beside walls, so even alternating A/D directions can
        put the first dodge straight into geometry. Let the game's current
        lock-on or facing decide the dodge vector and never add side movement.
        """
        self.log_info("farm dodge: Left Shift (no forced direction)")
        self.send_key("lshift")

    def map_zoom(self, zoom="max"):
        self.ensure_main()
        self.open_map()
        if zoom == "max":
            self.operate_click(0.050, 0.378)
        elif zoom == "mid":
            self.operate_click(0.050, 0.527)
        self.sleep(1)
        self.ensure_main()

    def open_map(self):
        self._keep_game_window_alive()
        self.wait_until(
            lambda: self.find_one(Labels.map_zoom_in),
            time_out=30,
            pre_action=lambda: self.send_key("m", interval=2),
            raise_if_not_found=True,
        )
        self.sleep(1)

    def teleport_to_nearest_bonfire(self, threshold=0.7, time_out=10):
        self.ensure_main()
        self.open_map()
        to_find = [Labels.bonfire_teleport]
        template_boxes = [self.get_box_by_name(label) for label in to_find]
        max_template_size = max(
            max(template_box.width, template_box.height) for template_box in template_boxes
        )
        step = max(max_template_size, self.width_of_screen(0.02), 1)
        center_x = self.width_of_screen(0.5)
        center_y = self.height_of_screen(0.5)
        max_radius = max(self.width, self.height)

        def find_teleport():
            radius = step
            while radius <= max_radius:
                x = max(0, center_x - radius)
                y = max(0, center_y - radius)
                to_x = min(self.width, center_x + radius)
                to_y = min(self.height, center_y + radius)
                box = Box(x=x, y=y, to_x=to_x, to_y=to_y, name="nearest_map_teleport")
                teleport = self.find_best_match_in_box(box, to_find, threshold=threshold)
                if teleport:
                    return teleport
                radius += step

        teleport = self.wait_until(find_teleport, time_out=time_out, raise_if_not_found=True)
        self.log_info(f"found nearest map teleport {teleport}")
        self.operate_click(teleport, action_name="click_nearest_map_teleport")
        self.sleep(0.5)
        return self.click_traval_button(raise_if_not_found=False)
    
    def teleport_to_bonfire(self, box: Box = None, threshold=0.7, order=1, zoom=None):
        self.ensure_main()
        self.open_map()
        if zoom:
            if zoom == "max":
                self.operate_click(0.050, 0.378)
            elif zoom == "mid":
                self.operate_click(0.050, 0.527)
            self.sleep(1)
        if not box:
            box = self.main_viewport

        teleports = self.find_feature(Labels.bonfire_teleport, box=box, threshold=threshold)
        if not teleports:
            return False

        self.log_info(f"found map teleports {teleports}")

        teleports.sort(key=lambda tp: tp.center_distance(self.default_box.center))

        if len(teleports) >= order:
            teleport = teleports[order - 1]
        else:
            teleport = teleports[-1]

        self.operate_click(teleport, action_name="click_map_teleport")
        self.sleep(0.5)
        return self.click_traval_button(raise_if_not_found=False)

    def teleport_to_top_bonfire(self, box: Box, threshold=0.7):
        self.ensure_main()
        self.open_map()

        teleports = self.find_feature(Labels.bonfire_teleport, box=box, threshold=threshold)
        if not teleports:
            return False

        self.log_info(f"found map teleports {teleports}")

        teleport = min(teleports, key=lambda teleport: teleport.y)
        self.operate_click(teleport, action_name="click_map_teleport")
        self.sleep(0.5)
        return self.click_traval_button(raise_if_not_found=False)

    def teleport_on_spot(self):
        self.ensure_main()
        self.open_map()
        self.operate_click(0.5, 0.5, action_name="click_map_teleport")
        self.sleep(0.5)
        return self.click_traval_button(raise_if_not_found=False)
