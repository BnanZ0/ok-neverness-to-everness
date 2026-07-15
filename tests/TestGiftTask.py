import unittest
from types import SimpleNamespace

import numpy as np
from ok import Box

from src.tasks.GiftTask import GiftTask


class TestGiftTask(unittest.TestCase):
    def test_layout_boxes_are_derived_from_full_frame_size(self):
        task = object.__new__(GiftTask)
        task._executor = SimpleNamespace(frame=np.zeros((100, 200, 3), dtype=np.uint8))
        frame = np.zeros((200, 400, 3), dtype=np.uint8)
        resized = GiftTask.resize_captured_frame(task, frame)
        task.box_of_screen = lambda x, y, to_x, to_y, name: Box(
            round(x * 200),
            round(y * 100),
            round((to_x - x) * 200),
            round((to_y - y) * 100),
            name=name,
        )
        name_box = GiftTask.get_name_box(task)
        gift_boxes = GiftTask.get_gift_boxes(task)
        self.assertEqual(
            (name_box.x, name_box.y, name_box.width, name_box.height), (105, 17, 45, 7)
        )
        self.assertEqual(resized.shape[:2], (100, 200))
        self.assertEqual(len(gift_boxes), 10)
        self.assertEqual(gift_boxes[0].name, "gift_slot_0")
        self.assertGreater(gift_boxes[-1].x, gift_boxes[0].x)
        self.assertEqual(gift_boxes[0].crop_frame(frame).shape[:2], (4, 10))
        task.get_gift_boxes = lambda: gift_boxes
        badge_boxes = GiftTask.get_unlimit_gift_boxes(task)
        self.assertEqual(len(badge_boxes), 10)
        self.assertLess(badge_boxes[0].x, gift_boxes[0].x)
        self.assertLess(badge_boxes[0].y, gift_boxes[0].y)

    def test_character_match_delegates_template_matching_to_find_one(self):
        task = object.__new__(GiftTask)
        frame = np.full((100, 200, 3), 100, dtype=np.uint8)
        task.manager = SimpleNamespace(load_frame=lambda _profile: frame)
        task._executor = SimpleNamespace(frame=frame)
        task.get_name_box = lambda: Box(0, 0, 45, 7, name="gift_character_name")
        task._report = lambda _message: None
        calls = []
        task.find_one = lambda *args, **kwargs: calls.append((args, kwargs)) or Box(0, 0, 1, 1)

        profile_id = GiftTask._match_current_profile(
            task, {"profile": {"display_name": "角色", "frame_id": "frame"}}
        )

        self.assertEqual(profile_id, "profile")
        self.assertEqual(len(calls), 1)
        ((call_args, call_kwargs),) = calls
        self.assertEqual(call_args, ("gift_name_profile",))
        self.assertEqual(call_kwargs["box"].name, "gift_character_name")
        self.assertEqual(call_kwargs["template"].shape[:2], (7, 45))

    def test_give_profile_respects_target_and_global_limit(self):
        task = object.__new__(GiftTask)
        task._report = lambda _message: None
        task.sleep = lambda _seconds: None
        task.screenshot = lambda _name: None
        remaining = [3]
        task._read_character_gift_remaining = lambda: remaining[0]
        task._find_gift_box = lambda _profile: object()
        attempts = []
        task._give_once = lambda _box, previous: (
            attempts.append(previous) or (remaining.__setitem__(0, remaining[0] - 1) or True)
        )
        profile = {"display_name": "角色", "target_count": 3, "selected_slots": [0]}
        summary = {"success": 0, "skipped": [], "failed": []}

        GiftTask._give_profile(task, "profile", profile, summary)
        self.assertEqual(summary["success"], 3)
        self.assertEqual(attempts, [3, 2, 1])
        self.assertEqual(summary["processed_profiles"], {"profile"})

        attempts.clear()
        capped = {"success": GiftTask.MAX_TOTAL_GIFTS, "skipped": [], "failed": []}
        GiftTask._give_profile(task, "profile", profile, capped)
        self.assertEqual(attempts, [])

    def test_give_profile_does_not_count_unchanged_counter(self):
        task = object.__new__(GiftTask)
        task._report = lambda _message: None
        task.screenshot = lambda _name: None
        task._read_character_gift_remaining = lambda: 3
        task._find_gift_box = lambda _profile: object()
        task._give_once = lambda _box, _previous: False
        summary = {"success": 0, "skipped": [], "failed": []}

        GiftTask._give_profile(
            task,
            "profile",
            {"display_name": "角色", "target_count": 1, "selected_slots": [0]},
            summary,
        )
        self.assertEqual(summary["success"], 0)
        self.assertEqual(len(summary["failed"]), 1)

    def test_give_profile_does_not_click_when_character_already_reached_target(self):
        task = object.__new__(GiftTask)
        task._report = lambda _message: None
        task.screenshot = lambda _name: None
        task._read_character_gift_remaining = lambda: 1
        task._find_gift_box = lambda _profile: self.fail(
            "must not search gifts at the configured target"
        )
        task._give_once = lambda _box, _previous: self.fail(
            "must not click at the configured target"
        )
        summary = {"success": 0, "skipped": [], "failed": []}

        GiftTask._give_profile(
            task,
            "profile",
            {"display_name": "角色", "target_count": 1, "selected_slots": [0]},
            summary,
        )

        self.assertEqual(summary["success"], 0)
        self.assertEqual(summary["skipped"], ["角色: 已达赠送目标 2/1"])

    def test_sidebar_scan_rechecks_only_fifth_slot_after_small_scrolls(self):
        task = object.__new__(GiftTask)
        task.MAX_SIDEBAR_PAGES = 1
        task._scroll_sidebar_to_top = lambda: None
        task.sleep = lambda _seconds: None
        clicked_slots = []
        task.operate_click = lambda _x, y, interval=None: clicked_slots.append(y)
        task._match_current_profile = lambda _profiles: None
        task._give_profile = lambda _profile_id, _profile, _summary: None
        task._executor = SimpleNamespace(frame=np.zeros((1, 1, 3), dtype=np.uint8))
        task._sidebar_box = lambda: Box(0, 0, 1, 1)
        task._sidebar_unchanged = lambda _snapshot: False

        scroll_count = [0]
        task.operate = lambda callback, block: callback()
        task.scroll = lambda *_args: scroll_count.__setitem__(0, scroll_count[0] + 1)

        GiftTask._scan_character_list(
            task,
            {"unmatched": {"display_name": "未匹配"}},
            {"success": 0, "skipped": [], "failed": []},
        )

        expected_clicked_slots = list(GiftTask.CHARACTER_SLOT_YS)
        expected_clicked_slots.extend(
            [GiftTask.CHARACTER_SLOT_YS[-1]] * GiftTask.SIDEBAR_SCROLLS_PER_CHARACTER
        )
        self.assertEqual(clicked_slots, expected_clicked_slots)
