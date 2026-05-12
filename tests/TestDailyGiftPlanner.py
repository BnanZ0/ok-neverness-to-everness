import unittest

from src.tasks.DailyGiftPlanner import (
    DailyGiftPlanner,
    GiftCharacter,
    GiftOption,
    GiftPanelState,
)


def make_state(characters, daily_total_count=0):
    return GiftPanelState(
        daily_total_count=daily_total_count,
        daily_total_limit=10,
        characters=characters,
        send_button_target="send",
        popup_close_target="popup-close",
    )


class TestDailyGiftPlanner(unittest.TestCase):
    def test_specified_character_target_is_used(self):
        state = make_state(
            [
                GiftCharacter("A", daily_count=0, gifts=[GiftOption("a-gift", 1, target="a-gift")], target="A"),
                GiftCharacter("B", daily_count=0, gifts=[GiftOption("b-gift", 1, target="b-gift")], target="B"),
            ]
        )

        plan = DailyGiftPlanner(target_names=["B"], required_count=1).build_plan(state)

        self.assertTrue(plan.can_execute)
        self.assertEqual(plan.selected_gifts[0].identity, "b-gift")
        self.assertIn(("select_character", "B"), [(action.kind, action.target) for action in plan.actions])

    def test_character_already_at_three_is_skipped(self):
        state = make_state(
            [GiftCharacter("A", daily_count=3, gifts=[GiftOption("gift", 1, target="gift")], target="A")]
        )

        plan = DailyGiftPlanner(target_names=["A"], required_count=1).build_plan(state)

        self.assertFalse(plan.can_execute)
        self.assertEqual(plan.skip_reason, DailyGiftPlanner.NO_SAFE_GIFTS)

    def test_bonus_marker_gift_is_preferred(self):
        state = make_state(
            [
                GiftCharacter(
                    "A",
                    daily_count=0,
                    gifts=[
                        GiftOption("plain", 1, base_affinity=100, visible_order=1, target="plain"),
                        GiftOption("bonus", 1, base_affinity=20, has_bonus_marker=True, visible_order=2, target="bonus"),
                    ],
                    target="A",
                )
            ]
        )

        plan = DailyGiftPlanner(target_names=["A"], required_count=1).build_plan(state)

        self.assertEqual(plan.selected_gifts[0].identity, "bonus")

    def test_higher_bonus_affinity_is_preferred(self):
        state = make_state(
            [
                GiftCharacter(
                    "A",
                    daily_count=0,
                    gifts=[
                        GiftOption("low", 1, bonus_affinity=10, has_bonus_marker=True, visible_order=1, target="low"),
                        GiftOption("high", 1, bonus_affinity=30, has_bonus_marker=True, visible_order=2, target="high"),
                    ],
                    target="A",
                )
            ]
        )

        plan = DailyGiftPlanner(target_names=["A"], required_count=1).build_plan(state)

        self.assertEqual(plan.selected_gifts[0].identity, "high")

    def test_zero_inventory_is_skipped(self):
        state = make_state(
            [
                GiftCharacter(
                    "A",
                    daily_count=0,
                    gifts=[
                        GiftOption("empty", 0, has_bonus_marker=True, target="empty"),
                        GiftOption("available", 1, target="available"),
                    ],
                    target="A",
                )
            ]
        )

        plan = DailyGiftPlanner(target_names=["A"], required_count=1).build_plan(state)

        self.assertEqual(plan.selected_gifts[0].identity, "available")

    def test_daily_total_is_capped_at_ten(self):
        state = make_state(
            [
                GiftCharacter(
                    "A",
                    daily_count=0,
                    gifts=[GiftOption("gift", 5, target="gift")],
                    target="A",
                )
            ],
            daily_total_count=9,
        )

        plan = DailyGiftPlanner(target_names=["A"], required_count=5).build_plan(state)

        self.assertEqual(len([action for action in plan.actions if action.kind == "send_gift"]), 1)

    def test_stops_at_required_activity_count(self):
        state = make_state(
            [
                GiftCharacter(
                    "A",
                    daily_count=0,
                    gifts=[GiftOption("gift", 5, target="gift")],
                    target="A",
                )
            ]
        )

        plan = DailyGiftPlanner(target_names=["A"], required_count=1).build_plan(state)

        self.assertEqual(len([action for action in plan.actions if action.kind == "send_gift"]), 1)

    def test_unreadable_counters_do_not_cause_blind_gifting(self):
        unreadable_daily = make_state(
            [GiftCharacter("A", daily_count=0, gifts=[GiftOption("gift", 1, target="gift")], target="A")],
            daily_total_count=None,
        )
        unreadable_character = make_state(
            [GiftCharacter("A", daily_count=None, gifts=[GiftOption("gift", 1, target="gift")], target="A")]
        )

        daily_plan = DailyGiftPlanner(target_names=["A"], required_count=1).build_plan(unreadable_daily)
        character_plan = DailyGiftPlanner(target_names=["A"], required_count=1).build_plan(unreadable_character)

        self.assertFalse(daily_plan.can_execute)
        self.assertFalse(character_plan.can_execute)
        self.assertFalse(any(action.kind == "send_gift" for action in daily_plan.actions))
        self.assertFalse(any(action.kind == "send_gift" for action in character_plan.actions))

    def test_popup_cleanup_action_is_present(self):
        state = make_state(
            [GiftCharacter("A", daily_count=0, gifts=[GiftOption("gift", 1, target="gift")], target="A")]
        )

        plan = DailyGiftPlanner(target_names=["A"], required_count=1).build_plan(state)

        self.assertEqual(plan.actions[-1].kind, "close_popup")
        self.assertEqual(plan.actions[-1].target, "popup-close")

    def test_completed_requirement_is_idempotent(self):
        state = make_state(
            [GiftCharacter("A", daily_count=0, gifts=[GiftOption("gift", 1, target="gift")], target="A")]
        )

        plan = DailyGiftPlanner(target_names=["A"], required_count=0).build_plan(state)

        self.assertFalse(plan.can_execute)
        self.assertEqual(plan.skip_reason, DailyGiftPlanner.REQUIREMENT_DONE)
        self.assertEqual(plan.actions, [])


if __name__ == "__main__":
    unittest.main()
