import unittest

from src.tasks.DailyCoffeePlanner import (
    CoffeeFoodOption,
    CoffeeShopState,
    CoffeeSupplySlot,
    DailyCoffeePlanner,
)


def make_state(options, duration_options=None, trend_category="热销", slot_needs_supply=True):
    return CoffeeShopState(
        trend_category=trend_category,
        income_claim_target="income",
        supply_target="supply",
        slots=[
            CoffeeSupplySlot(
                identity="slot-1",
                options=options,
                needs_supply=slot_needs_supply,
                target="slot-1-target",
            )
        ],
        duration_options=duration_options or {"4小时": "duration-4h", "24小时": "duration-24h"},
        buy_target="buy",
        home_delivery_target="home-delivery",
        popup_close_target="popup-close",
    )


class TestDailyCoffeePlanner(unittest.TestCase):
    def test_supply_duration_choices_are_fixed_four_options(self):
        self.assertEqual(DailyCoffeePlanner.ALLOWED_DURATIONS, ("4小时", "8小时", "24小时", "72小时"))

    def test_trend_item_more_expensive_selects_trend_item(self):
        state = make_state(
            [
                CoffeeFoodOption("trend", price_value=120, category="热销", target="trend"),
                CoffeeFoodOption("normal", price_value=80, category="普通", target="normal"),
            ]
        )

        plan = DailyCoffeePlanner().build_plan(state)

        self.assertTrue(plan.can_execute)
        self.assertEqual(plan.selected_options[0].identity, "trend")

    def test_non_trend_item_more_expensive_selects_non_trend_item(self):
        state = make_state(
            [
                CoffeeFoodOption("trend", price_value=120, category="热销", target="trend"),
                CoffeeFoodOption("premium", price_value=180, category="普通", target="premium"),
            ]
        )

        plan = DailyCoffeePlanner().build_plan(state)

        self.assertTrue(plan.can_execute)
        self.assertEqual(plan.selected_options[0].identity, "premium")

    def test_price_unreadable_but_trend_readable_uses_trend_fallback(self):
        state = make_state(
            [
                CoffeeFoodOption("trend", category="热销", target="trend", visible_order=2),
                CoffeeFoodOption("normal", category="普通", target="normal", visible_order=1),
            ]
        )

        plan = DailyCoffeePlanner().build_plan(state)

        self.assertTrue(plan.can_execute)
        self.assertEqual(plan.selected_options[0].identity, "trend")

    def test_price_and_trend_unreadable_skips_risky_switching(self):
        state = make_state(
            [
                CoffeeFoodOption("unknown-a", target="a"),
                CoffeeFoodOption("unknown-b", target="b"),
            ],
            trend_category="",
        )

        plan = DailyCoffeePlanner().build_plan(state)

        self.assertFalse(plan.can_execute)
        self.assertEqual(plan.skip_reason, DailyCoffeePlanner.NO_SAFE_FOOD)
        self.assertFalse(any(action.kind == "buy_supply" for action in plan.actions))

    def test_configured_duration_must_be_selected_explicitly(self):
        state = make_state(
            [CoffeeFoodOption("food", price_value=100, target="food")],
            duration_options={"default": "default-duration", "4小时": "duration-4h", "24小时": "duration-24h"},
        )

        plan = DailyCoffeePlanner(target_duration="24h").build_plan(state)

        self.assertIn(
            ("select_supply_duration", "duration-24h"),
            [(action.kind, action.target) for action in plan.actions],
        )
        self.assertNotIn(
            ("select_supply_duration", "default-duration"),
            [(action.kind, action.target) for action in plan.actions],
        )

    def test_no_configured_duration_option_does_not_buy(self):
        state = make_state(
            [CoffeeFoodOption("food", price_value=100, target="food")],
            duration_options={"4h": "duration-4h"},
        )

        plan = DailyCoffeePlanner(target_duration="24小时").build_plan(state)

        self.assertFalse(plan.can_execute)
        self.assertEqual(plan.skip_reason, "未检测到24小时补货选项，停止购买")
        self.assertFalse(any(action.kind == "buy_supply" for action in plan.actions))

    def test_duration_must_be_one_of_fixed_options(self):
        state = make_state([CoffeeFoodOption("food", price_value=100, target="food")])

        plan = DailyCoffeePlanner(target_duration="2小时").build_plan(state)

        self.assertFalse(plan.can_execute)
        self.assertIn("补货时长必须是固定选项之一", plan.skip_reason)
        self.assertFalse(any(action.kind == "buy_supply" for action in plan.actions))

    def test_home_delivery_selected_after_purchase(self):
        state = make_state([CoffeeFoodOption("food", price_value=100, target="food")])

        plan = DailyCoffeePlanner().build_plan(state)
        kinds = [action.kind for action in plan.actions]

        self.assertLess(kinds.index("buy_supply"), kinds.index("select_home_delivery"))

    def test_popup_cleanup_action_is_present(self):
        state = make_state([CoffeeFoodOption("food", price_value=100, target="food")])

        plan = DailyCoffeePlanner().build_plan(state)

        self.assertEqual(plan.actions[-1].kind, "close_popup")
        self.assertEqual(plan.actions[-1].target, "popup-close")

    def test_already_supplied_slots_are_idempotent(self):
        state = make_state(
            [CoffeeFoodOption("food", price_value=100, target="food")],
            slot_needs_supply=False,
        )

        plan = DailyCoffeePlanner().build_plan(state)

        self.assertFalse(plan.can_execute)
        self.assertEqual(plan.skip_reason, DailyCoffeePlanner.NO_SAFE_SLOTS)
        self.assertEqual(plan.actions, [])


if __name__ == "__main__":
    unittest.main()
