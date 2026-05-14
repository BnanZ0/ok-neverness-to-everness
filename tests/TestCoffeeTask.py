import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from src.coffee import CoffeeFoodOption, CoffeeRuntime
from src.tasks.CoffeeTask import CoffeeTask


def _runtime_task(config=None):
    task = Mock()
    task.config = {"coffee_key_settle_seconds": 0, "coffee_dry_run": True}
    task.config.update(config or {})
    task.click = Mock()
    task.click_ui = Mock()
    task.send_key = Mock()
    task.swipe = Mock()
    task.scroll = Mock()
    task.sleep = Mock()
    task.operate = Mock(side_effect=lambda func, block=False: func())
    task.ocr_ui = Mock(return_value=[])
    task.frame = None
    task.next_frame = Mock(return_value=None)
    task.width = 2560
    task.height = 1600
    task.ui_point = lambda x, y: (int(task.width * x), int(task.height * y))
    return task


class TestCoffeeRuntime(unittest.TestCase):
    def test_same_price_ocr_conflict_is_rejected_for_fill_candidates(self):
        runtime = CoffeeRuntime(_runtime_task())
        current = [CoffeeFoodOption("生巧雪醇拿铁", price_value=34661)]
        unstable = CoffeeFoodOption("明治", price_value=34661, target="unstable")

        candidates = runtime._fill_product_candidates([unstable], [], "", conflict_options=current)

        self.assertEqual(candidates, [])
        self.assertIn("product_fill_same_price_conflict:明治", runtime.actions)

    def test_identity_price_category_dedupe_is_preserved(self):
        runtime = CoffeeRuntime(_runtime_task())
        options = [
            CoffeeFoodOption("鲜鱼套餐", price_value=100, category="主食"),
            CoffeeFoodOption("鮮魚套餐", price_value=100, category="主食"),
            CoffeeFoodOption("鲜鱼套餐", price_value=120, category="主食"),
        ]

        deduped = runtime._dedupe_food_options(options)

        self.assertEqual(
            [(item.identity, item.price_value) for item in deduped],
            [("鲜鱼套餐", 100), ("鲜鱼套餐", 120)],
        )

    def test_recent_supply_no_op_evidence_is_preserved(self):
        task = _runtime_task({"coffee_recent_supply_skip_seconds": 1800})
        runtime = CoffeeRuntime(task)
        runtime.current_business_seconds = Mock(return_value=60)
        runtime.find_text_box = Mock(side_effect=AssertionError("supply UI should not be touched for recent no-op"))

        ok, skip_reason, real_purchase = runtime.replenish_supply()

        self.assertTrue(ok)
        self.assertFalse(real_purchase)
        self.assertEqual(skip_reason, "supply_recently_active_not_needed")
        self.assertIn("supply_recently_active_not_needed:60", runtime.actions)

    def test_runtime_falls_back_to_task_ocr_when_ocr_ui_absent(self):
        box = SimpleNamespace(text="一咖舍")
        task = SimpleNamespace(
            ocr=Mock(return_value=[box]),
            frame=None,
            width=2560,
            height=1600,
            config={"coffee_dry_run": True},
        )

        runtime = CoffeeRuntime(task)
        result = runtime._task_ocr(0.02, 0.05, 0.98, 0.95, frame=None)

        self.assertEqual(result, [box])
        task.ocr.assert_called_once()

    def test_click_ui_falls_back_to_screen_click_when_task_lacks_click_ui(self):
        task = SimpleNamespace(
            click=Mock(),
            frame=None,
            width=2560,
            height=1600,
            config={"coffee_dry_run": False},
            operate=lambda func, block=False: func(),
            ui_point=lambda x, y: (int(2560 * x), int(1600 * y)),
        )

        runtime = CoffeeRuntime(task)
        runtime._click_ui(0.5, 0.25, "test_action", move=True)

        task.click.assert_called_once_with(1280, 400, after_sleep=1, move=True, down_time=0.01)
        self.assertIn("test_action", runtime.actions)

    def test_tycoon_ascii_marker_is_detected(self):
        runtime = CoffeeRuntime(_runtime_task())

        self.assertTrue(runtime._is_tycoon_texts(["CITY TYCOON"]))


class TestCoffeeTaskConfig(unittest.TestCase):
    def _task(self, config=None):
        task = object.__new__(CoffeeTask)
        task.config = config or {}
        return task

    def test_actions_requested_defaults_to_income_restock_buy(self):
        task = self._task(
            {
                CoffeeTask.CONF_COLLECT_INCOME: True,
                CoffeeTask.CONF_RESTOCK_GOODS: True,
                CoffeeTask.CONF_BUY_GOODS: True,
                CoffeeTask.CONF_OPTIMIZE_PRODUCTS: False,
            }
        )

        self.assertEqual(
            CoffeeTask._actions_requested(task),
            [
                CoffeeTask.CONF_COLLECT_INCOME,
                CoffeeTask.CONF_RESTOCK_GOODS,
                CoffeeTask.CONF_BUY_GOODS,
            ],
        )

    def test_supply_requested_requires_both_restock_and_buy(self):
        task = self._task({CoffeeTask.CONF_RESTOCK_GOODS: True, CoffeeTask.CONF_BUY_GOODS: False})
        self.assertFalse(CoffeeTask._supply_requested(task))

        task = self._task({CoffeeTask.CONF_RESTOCK_GOODS: True, CoffeeTask.CONF_BUY_GOODS: True})
        self.assertTrue(CoffeeTask._supply_requested(task))

    def test_apply_runtime_config_maps_keys(self):
        task = self._task(
            {
                CoffeeTask.CONF_PRODUCT_SLOTS: "3",
                CoffeeTask.CONF_RESTOCK_DURATION: "8h",
                CoffeeTask.CONF_PRICE_TABLE: "disabled",
                CoffeeTask.CONF_RESTOCK_GOODS: True,
                CoffeeTask.CONF_BUY_GOODS: True,
            }
        )

        CoffeeTask._apply_runtime_config(task)

        self.assertEqual(task.config["coffee_product_target_slots"], 3)
        self.assertEqual(task.config["coffee_max_supply_slots"], 3)
        self.assertEqual(task.config["coffee_supply_duration"], "8h")
        self.assertEqual(task.config["coffee_price_table"], "disabled")
        self.assertTrue(task.config["coffee_allow_pending_supply_completion"])

    def test_apply_runtime_config_auto_translates_to_24h(self):
        task = self._task(
            {
                CoffeeTask.CONF_PRODUCT_SLOTS: "auto",
                CoffeeTask.CONF_RESTOCK_DURATION: "auto",
                CoffeeTask.CONF_PRICE_TABLE: "auto",
            }
        )

        CoffeeTask._apply_runtime_config(task)

        self.assertEqual(task.config["coffee_product_target_slots"], 0)
        self.assertEqual(task.config["coffee_supply_duration"], "24小时")
        self.assertFalse(task.config["coffee_allow_pending_supply_completion"])

    def test_do_run_skips_when_no_actions_enabled(self):
        task = self._task(
            {
                CoffeeTask.CONF_COLLECT_INCOME: False,
                CoffeeTask.CONF_RESTOCK_GOODS: False,
                CoffeeTask.CONF_BUY_GOODS: False,
                CoffeeTask.CONF_OPTIMIZE_PRODUCTS: False,
            }
        )
        messages = []
        task.log_info = lambda message, *args, **kwargs: messages.append(("info", message))
        task.log_error = lambda message, *args, **kwargs: messages.append(("error", message))

        self.assertTrue(CoffeeTask.do_run(task))
        self.assertIn(("info", "一咖舍未启用任何动作"), messages)


if __name__ == "__main__":
    unittest.main()
