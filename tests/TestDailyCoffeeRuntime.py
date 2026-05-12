import unittest
from unittest.mock import Mock, call, patch

from src.tasks.DailyCoffeePlanner import CoffeeFoodOption, CoffeeShopState, CoffeeSupplySlot
from src.tasks.DailyCoffeeRuntime import CoffeeDetectedBox, DailyCoffeeRuntime
from src.tasks.DailyUIContext import TaskUIAdapter


class FakeBox:
    def __init__(self, text, x=0, y=0, width=10, height=10):
        self.text = text
        self.x = x
        self.y = y
        self.width = width
        self.height = height


class TestDailyCoffeeRuntime(unittest.TestCase):
    def make_task(self, config=None):
        task = Mock()
        task.config = {"coffee_key_settle_seconds": 0}
        task.config.update(config or {})
        task.click = Mock()
        task.click_ui = Mock()
        task.send_key = Mock()
        task.swipe = Mock()
        task.scroll = Mock()
        task.mouse_down = Mock()
        task.mouse_up = Mock()
        task.sleep = Mock()
        task.operate = Mock(side_effect=lambda func, block=False: func())
        task.ocr_ui = Mock(return_value=[])
        task.frame = "stale-frame"
        task.next_frame = Mock(return_value="fresh-frame")
        task._ensure_daily_main = None
        task.width = 2560
        task.height = 1600
        task.ui_point = lambda x, y: (int(task.width * x), int(task.height * y))
        return task

    def test_daily_card_entry_is_preferred_before_f5_fallback(self):
        task = self.make_task()
        card = Mock(action_box="daily-go")
        runtime = DailyCoffeeRuntime(task)
        runtime.wait_for_coffee_shop_panel = Mock(return_value=True)

        result = runtime.open_coffee_shop(card)

        self.assertTrue(result)
        task.click.assert_called_once_with("daily-go")
        task.send_key.assert_not_called()
        task.click_ui.assert_not_called()
        self.assertEqual(runtime.actions, ["enter_daily_coffee_card"])

    def test_runtime_accepts_task_ui_adapter(self):
        task = self.make_task()
        card = Mock(action_box="daily-go")
        runtime = DailyCoffeeRuntime(TaskUIAdapter(task))
        runtime.wait_for_coffee_shop_panel = Mock(return_value=True)

        result = runtime.open_coffee_shop(card)

        self.assertTrue(result)
        task.click.assert_called_once_with("daily-go")
        self.assertIsInstance(runtime.ui, TaskUIAdapter)

    def test_f5_fallback_opens_city_tycoon_and_selects_coffee(self):
        task = self.make_task()
        runtime = DailyCoffeeRuntime(task)
        runtime.is_coffee_shop_panel = Mock(return_value=False)
        runtime.wait_for_tycoon_panel = Mock(return_value=True)
        runtime.wait_for_coffee_shop_panel = Mock(return_value=True)

        result = runtime.open_coffee_shop()

        self.assertTrue(result)
        task.send_key.assert_called_once_with("f5", after_sleep=0)
        task.click_ui.assert_called_once_with(
            *DailyCoffeeRuntime.COFFEE_POINT_POSITION,
            after_sleep=1,
            move=True,
            down_time=0.01,
        )
        task.operate.assert_called_once()
        self.assertIn("wait_city_tycoon_transition", runtime.actions)

    def test_f5_silent_postmessage_failure_retries_with_foreground_key(self):
        task = self.make_task()
        task._send_foreground_key = Mock(return_value=True)
        runtime = DailyCoffeeRuntime(task)
        runtime.is_coffee_shop_panel = Mock(return_value=False)
        runtime.wait_for_tycoon_panel = Mock(side_effect=[False, True])
        runtime.wait_for_coffee_shop_panel = Mock(return_value=True)

        result = runtime.open_coffee_shop()

        self.assertTrue(result)
        task.send_key.assert_called_once_with("f5", after_sleep=0)
        task._send_foreground_key.assert_called_once_with("f5", after_sleep=0)
        self.assertIn("retry_open_city_tycoon_f5_foreground", runtime.actions)
        self.assertIn("open_city_tycoon_f5_foreground", runtime.actions)
        self.assertIn("wait_city_tycoon_transition", runtime.actions)

    def test_f5_fallback_tries_next_safe_entry_point_if_first_click_only_selects(self):
        task = self.make_task()
        runtime = DailyCoffeeRuntime(task)
        runtime.is_coffee_shop_panel = Mock(return_value=False)
        runtime.wait_for_tycoon_panel = Mock(return_value=True)
        runtime.wait_for_coffee_shop_panel = Mock(side_effect=[False, True])

        result = runtime.open_coffee_shop()

        self.assertTrue(result)
        self.assertEqual(task.click_ui.call_count, 2)
        self.assertEqual(task.operate.call_count, 2)
        self.assertIn("select_yikafei_from_tycoon_candidate:1", runtime.actions)
        self.assertIn("select_yikafei_from_tycoon_candidate:2", runtime.actions)

    def test_tycoon_panel_accepts_city_tycoon_ocr_variants(self):
        task = self.make_task()
        task.ocr_ui.return_value = [
            FakeBox("CTYTYCOON"),
            FakeBox("大亨等级"),
            FakeBox("一咖舍门"),
        ]
        runtime = DailyCoffeeRuntime(task)

        self.assertTrue(runtime.is_tycoon_panel())

    def test_f5_fallback_uses_tycoon_ocr_variant_before_selecting_coffee(self):
        task = self.make_task()
        task.ocr_ui.return_value = [
            FakeBox("CTYTYCOON"),
            FakeBox("大亨等级"),
            FakeBox("一咖舍门", x=1000, y=900, width=100, height=40),
        ]
        runtime = DailyCoffeeRuntime(task)
        runtime.wait_for_coffee_shop_panel = Mock(return_value=True)

        result = runtime.open_coffee_shop()

        self.assertTrue(result)
        task.send_key.assert_called_once_with("f5", after_sleep=0)
        task.click_ui.assert_not_called()
        task.click.assert_called_once_with(1050, 1120, after_sleep=1, move=True, down_time=0.01)
        task.operate.assert_called_once()

    def test_f5_key_settle_uses_wall_clock_sleep_not_executor_sleep(self):
        task = self.make_task({"coffee_key_settle_seconds": 0.25})
        task.sleep.side_effect = AssertionError("executor sleep must not be used for F5 settle")
        runtime = DailyCoffeeRuntime(task)

        with patch("src.tasks.DailyCoffeeRuntime.time.sleep") as sleep:
            runtime._send_key("f5", "open_city_tycoon_f5")

        task.send_key.assert_called_once_with("f5", after_sleep=0)
        task._send_foreground_key.assert_not_called()
        sleep.assert_called_once_with(0.25)

    def test_f5_foreground_retry_settle_uses_wall_clock_sleep_not_executor_sleep(self):
        task = self.make_task({"coffee_key_settle_seconds": 0.25})
        task._send_foreground_key = Mock(return_value=True)
        task.sleep.side_effect = AssertionError("executor sleep must not be used for foreground F5 settle")
        runtime = DailyCoffeeRuntime(task)

        with patch("src.tasks.DailyCoffeeRuntime.time.sleep") as sleep:
            runtime._send_foreground_key("f5", "open_city_tycoon_f5_foreground")

        task._send_foreground_key.assert_called_once_with("f5", after_sleep=0)
        sleep.assert_called_once_with(0.25)

    def test_ascii_tycoon_loading_text_alone_is_not_click_ready(self):
        task = self.make_task()
        task.ocr_ui.return_value = [FakeBox("GTYTYCOON")]
        runtime = DailyCoffeeRuntime(task)

        self.assertFalse(runtime.is_tycoon_panel())

    def test_select_coffee_from_tycoon_stops_after_candidate_succeeds(self):
        task = self.make_task()
        runtime = DailyCoffeeRuntime(task)
        runtime.wait_for_coffee_tycoon_label = Mock(return_value=None)
        runtime.wait_for_coffee_shop_panel = Mock(side_effect=[False, False, True])

        result = runtime.select_coffee_from_tycoon()

        self.assertTrue(result)
        self.assertEqual(task.click_ui.call_count, 3)
        self.assertEqual(task.operate.call_count, 3)
        third_point = DailyCoffeeRuntime.COFFEE_POINT_CANDIDATES[2]
        task.click_ui.assert_called_with(*third_point, after_sleep=1, move=True, down_time=0.01)
        self.assertNotIn("select_yikafei_from_tycoon_candidate:4", runtime.actions)

    def test_claim_income_does_not_escape_shop_without_popup(self):
        task = self.make_task()
        runtime = DailyCoffeeRuntime(task)
        runtime.find_text_box = Mock(
            side_effect=lambda text, region: "income-target" if text == "提取收益" else None
        )
        runtime.is_income_report_popup = Mock(return_value=False)
        runtime.find_button_text_box = Mock(return_value=None)
        runtime.close_popup = Mock()

        result = runtime.claim_income_if_present()

        self.assertTrue(result)
        self.assertIn("claim_income", runtime.actions)
        runtime.close_popup.assert_not_called()

    def test_claim_income_confirms_reward_popup_if_present(self):
        task = self.make_task()
        runtime = DailyCoffeeRuntime(task)
        runtime.find_text_box = Mock(
            side_effect=lambda text, region: "income-target" if text == "提取收益" else None
        )
        runtime.is_income_report_popup = Mock(return_value=True)
        runtime.find_button_text_box = Mock(return_value="ok-button")
        runtime.wait_for = Mock(return_value=True)

        result = runtime.claim_income_if_present()

        self.assertTrue(result)
        self.assertEqual(task.click.mock_calls, [call("income-target"), call("ok-button")])
        self.assertIn("confirm_income_popup", runtime.actions)

    def test_income_popup_dismisses_blank_close_overlay(self):
        task = self.make_task()
        runtime = DailyCoffeeRuntime(task)
        runtime.find_button_text_box = Mock(return_value="ok-button")
        runtime.is_income_report_popup = Mock(return_value=True)
        runtime.find_text_box = Mock(return_value="blank-overlay")
        runtime.wait_for = Mock(return_value=True)

        result = runtime.confirm_income_popup_if_present()

        self.assertTrue(result)
        self.assertIn("confirm_income_popup", runtime.actions)
        self.assertIn("dismiss_blank_close_overlay", runtime.actions)
        task.send_key.assert_called_once_with("esc", after_sleep=0)

    def test_income_popup_confirm_retries_until_popup_closes(self):
        task = self.make_task()
        runtime = DailyCoffeeRuntime(task)
        runtime.find_button_text_box = Mock(return_value="ok-button")
        runtime.is_income_report_popup = Mock(return_value=True)
        runtime.dismiss_blank_close_overlay_if_present = Mock(return_value=False)
        runtime.wait_for = Mock(side_effect=[False, True])

        result = runtime.confirm_income_popup_if_present()

        self.assertTrue(result)
        self.assertEqual(runtime.actions.count("confirm_income_popup"), 2)
        self.assertIn("income_popup_confirm_still_visible:1", runtime.actions)
        self.assertEqual(task.click.mock_calls, [call("ok-button"), call("ok-button")])

    def test_run_stops_if_income_popup_remains_after_claim(self):
        task = self.make_task()
        runtime = DailyCoffeeRuntime(task)
        runtime.open_coffee_shop = Mock(return_value=True)
        runtime.claim_income_if_present = Mock(return_value=True)
        runtime.is_income_report_popup = Mock(return_value=True)
        runtime.optimize_products = Mock()
        runtime.replenish_supply = Mock()

        result = runtime.run()

        self.assertFalse(result.ok)
        self.assertTrue(result.income_claimed)
        self.assertEqual(result.skip_reason, "营收报告弹窗未关闭，未进入商品/补货流程")
        self.assertIn("income_popup_not_closed_after_claim", runtime.actions)
        runtime.optimize_products.assert_not_called()
        runtime.replenish_supply.assert_not_called()

    def test_income_report_popup_is_not_coffee_shop_panel(self):
        task = self.make_task()
        task.ocr_ui.return_value = [
            FakeBox("营收报告"),
            FakeBox("「一咖舍」"),
            FakeBox("商品收入"),
            FakeBox("确定"),
        ]
        runtime = DailyCoffeeRuntime(task)

        self.assertFalse(runtime.is_coffee_shop_panel())

    def test_replenish_supply_selects_configured_fixed_duration_and_home_delivery(self):
        task = self.make_task({"coffee_supply_duration": "24h", "coffee_dry_run": True})
        runtime = DailyCoffeeRuntime(task)
        runtime.find_text_box = Mock(
            side_effect=lambda text, region: {
                "补货": "buy",
                "24小时": "duration-24h",
            }.get(text)
        )
        runtime.wait_for_supply_popup = Mock(return_value=True)
        runtime.wait_for_button_text_box = Mock(
            side_effect=lambda text, region, timeout=4: {
                "送货上门": "home-delivery",
                "确认": "confirm",
            }.get(text)
        )
        runtime.close_popup = Mock()

        result = runtime.replenish_supply()

        self.assertTrue(result.ok)
        self.assertFalse(result.real_purchase_performed)
        self.assertIn("select_supply_duration:24小时", runtime.actions)
        self.assertIn("select_home_delivery", runtime.actions)
        self.assertIn("confirm_home_delivery", runtime.actions)
        task.click.assert_not_called()

    def test_replenish_supply_retries_stable_supply_button_when_text_click_misses(self):
        task = self.make_task({"coffee_supply_duration": "24h"})
        runtime = DailyCoffeeRuntime(task)
        runtime.find_text_box = Mock(
            side_effect=lambda text, region: {
                "补货": "buy",
                "24小时": "duration-24h",
            }.get(text)
        )
        runtime.wait_for_supply_popup = Mock(side_effect=[False, True])
        runtime.finish_home_delivery_flow = Mock(return_value="")
        runtime.close_popup = Mock()

        result = runtime.replenish_supply()

        self.assertTrue(result.ok)
        self.assertIn("open_supply", runtime.actions)
        self.assertIn("open_supply_fallback_button", runtime.actions)
        task.click_ui.assert_any_call(
            *DailyCoffeeRuntime.COFFEE_SUPPLY_BUTTON_POSITION,
            after_sleep=1,
            move=True,
            down_time=0.01,
        )

    def test_replenish_supply_prefers_button_ocr_for_buy_click(self):
        task = self.make_task({"coffee_supply_duration": "24小时"})
        runtime = DailyCoffeeRuntime(task)
        supply_entry = FakeBox("补货", y=820)
        duration = FakeBox("24小时", y=610)
        title = FakeBox("原料库存补货", y=220)
        buy_button = FakeBox("补货", y=1260)
        runtime.find_text_box = Mock(
            side_effect=lambda text, region: {
                "补货": supply_entry,
                "24小时": duration,
            }.get(text)
        )
        runtime.wait_for_supply_popup = Mock(return_value=True)
        runtime.find_button_text_box = Mock(
            side_effect=lambda text, region: buy_button if text == "补货" else title
        )
        runtime.finish_home_delivery_flow = Mock(return_value="")
        runtime.close_popup = Mock()

        result = runtime.replenish_supply()

        self.assertTrue(result.ok)
        self.assertIn("buy_supply", runtime.actions)
        task.click.assert_any_call(
            buy_button,
            move=True,
            down_time=DailyCoffeeRuntime.COFFEE_SUPPLY_CLICK_DOWN_TIME,
            after_sleep=DailyCoffeeRuntime.COFFEE_SUPPLY_CLICK_SETTLE_SECONDS,
        )

    def test_replenish_supply_rejects_non_fixed_duration(self):
        task = self.make_task({"coffee_supply_duration": "2小时", "coffee_dry_run": True})
        runtime = DailyCoffeeRuntime(task)
        runtime.find_text_box = Mock(return_value="supply")
        runtime.wait_for_supply_popup = Mock(return_value=True)

        result = runtime.replenish_supply()

        self.assertFalse(result.ok)
        self.assertIn("补货时长必须是固定选项之一", result.skip_reason)
        self.assertNotIn("buy_supply", runtime.actions)

    def test_no_configured_duration_option_does_not_buy(self):
        task = self.make_task({"coffee_supply_duration": "24小时", "coffee_dry_run": True})
        runtime = DailyCoffeeRuntime(task)
        runtime.find_text_box = Mock(
            side_effect=lambda text, region: {
                "补货": "buy",
                "4小时": "duration-4h",
            }.get(text)
        )
        runtime.wait_for_supply_popup = Mock(return_value=True)

        result = runtime.replenish_supply()

        self.assertFalse(result.ok)
        self.assertEqual(result.skip_reason, "未检测到24小时补货选项，停止购买")
        self.assertNotIn("buy_supply", runtime.actions)

    def test_replenish_supply_missing_entry_is_safe_skip(self):
        task = self.make_task({"coffee_supply_duration": "24小时"})
        runtime = DailyCoffeeRuntime(task)
        runtime.find_text_box = Mock(return_value=None)

        result = runtime.replenish_supply()

        self.assertTrue(result.ok)
        self.assertFalse(result.real_purchase_performed)
        self.assertEqual(result.skip_reason, "supply_not_needed_or_not_found")
        self.assertIn("supply_not_needed_or_not_found", runtime.actions)
        self.assertNotIn("buy_supply", runtime.actions)

    def test_replenish_supply_does_not_count_blocked_purchase(self):
        task = self.make_task({"coffee_supply_duration": "24小时"})
        runtime = DailyCoffeeRuntime(task)
        runtime.find_text_box = Mock(
            side_effect=lambda text, region: {
                "补货": "buy",
                "24小时": "duration-24h",
            }.get(text)
        )
        runtime.wait_for_supply_popup = Mock(return_value=True)
        runtime.wait_for_button_text_box = Mock(
            side_effect=lambda text, region, timeout=4: {
                "送货上门": "home-delivery",
                "确认": "confirm",
            }.get(text)
        )
        runtime.wait_for_supply_blocker_text = Mock(return_value="方斯不足")
        runtime.close_popup = Mock()

        result = runtime.replenish_supply()

        self.assertFalse(result.ok)
        self.assertFalse(result.real_purchase_performed)
        self.assertIn("方斯不足", result.skip_reason)
        self.assertIn("buy_supply", runtime.actions)
        self.assertIn("select_home_delivery", runtime.actions)
        self.assertIn("confirm_home_delivery", runtime.actions)
        runtime.close_popup.assert_called_once()

    def test_find_button_text_box_prefers_exact_button_over_prompt(self):
        task = self.make_task()
        runtime = DailyCoffeeRuntime(task)
        prompt = FakeBox("确认花费644方斯（商品460，配送费184）让商家送货上门吗？", y=300)
        button = FakeBox("确认", y=900)
        runtime.ocr_region = Mock(return_value=[prompt, button])

        target = runtime.find_button_text_box("确认", DailyCoffeeRuntime.COFFEE_CONFIRM_REGION)

        self.assertIs(target, button)

    def test_replenish_supply_fails_when_confirm_window_remains(self):
        task = self.make_task({"coffee_supply_duration": "24小时"})
        runtime = DailyCoffeeRuntime(task)
        runtime.find_text_box = Mock(
            side_effect=lambda text, region: {
                "补货": "buy",
                "24小时": "duration-24h",
            }.get(text)
        )
        runtime.wait_for_supply_popup = Mock(return_value=True)
        runtime.wait_for_button_text_box = Mock(
            side_effect=lambda text, region, timeout=4: {
                "送货上门": "home-delivery",
                "确认": "confirm-button",
            }.get(text)
        )
        runtime.wait_for_supply_blocker_text = Mock(return_value="")
        runtime.find_button_text_box = Mock(return_value="confirm-button")
        runtime.close_popup = Mock()

        result = runtime.replenish_supply()

        self.assertFalse(result.ok)
        self.assertIn("确认窗口仍存在", result.skip_reason)
        runtime.close_popup.assert_called_once()

    def test_replenish_supply_reports_inventory_prompt_material_limit(self):
        task = self.make_task({"coffee_supply_duration": "24小时"})
        runtime = DailyCoffeeRuntime(task)
        runtime.find_text_box = Mock(
            side_effect=lambda text, region: {
                "补货": "buy",
                "24小时": "duration-24h",
            }.get(text)
        )
        runtime.wait_for_supply_popup = Mock(return_value=True)
        runtime.wait_for_button_text_box = Mock(
            side_effect=lambda text, region, timeout=4: {
                "送货上门": "home-delivery",
                "确认": "confirm-button",
            }.get(text)
        )
        runtime.wait_for_supply_blocker_text = Mock(return_value="缺少以下材料无法补满库存")
        runtime.close_popup = Mock()

        result = runtime.replenish_supply()

        self.assertFalse(result.ok)
        self.assertFalse(result.real_purchase_performed)
        self.assertIn("库存或材料限制", result.skip_reason)
        self.assertIn("缺少以下材料", result.skip_reason)
        self.assertIn("buy_supply", runtime.actions)
        self.assertIn("select_home_delivery", runtime.actions)
        self.assertIn("confirm_home_delivery", runtime.actions)
        runtime.close_popup.assert_called_once()

    def test_replenish_supply_falls_back_to_shorter_duration_after_material_blocker(self):
        task = self.make_task({"coffee_supply_duration": "24小时"})
        runtime = DailyCoffeeRuntime(task)
        runtime.find_text_box = Mock(
            side_effect=lambda text, region: {
                "补货": "buy",
                "24小时": "duration-24h",
                "4小时": "duration-4h",
            }.get(text)
        )
        runtime.wait_for_supply_popup = Mock(return_value=True)
        runtime.wait_for_supply_blocker_text = Mock(side_effect=["库存提示", "", ""])
        home_delivery_calls = {"count": 0}

        def find_delivery_button(text, region, timeout=4):
            if text == "送货上门":
                home_delivery_calls["count"] += 1
                return "home-delivery" if home_delivery_calls["count"] >= 2 else None
            if text == "确认" and home_delivery_calls["count"] >= 2:
                return "confirm"
            return None

        runtime.wait_for_button_text_box = Mock(side_effect=find_delivery_button)
        runtime.find_button_text_box = Mock(return_value=None)
        runtime.close_popup = Mock()

        result = runtime.replenish_supply()

        self.assertTrue(result.ok)
        self.assertTrue(result.real_purchase_performed)
        self.assertIn("supply_duration_blocked:24小时:补货确认后出现库存或材料限制: 库存提示", runtime.actions)
        self.assertIn("supply_duration_not_found:8小时", runtime.actions)
        self.assertIn("select_supply_duration:4小时", runtime.actions)
        self.assertEqual(runtime.actions.count("buy_supply"), 2)
        self.assertIn("select_home_delivery", runtime.actions)
        self.assertIn("confirm_home_delivery", runtime.actions)
        self.assertEqual(runtime.close_popup.call_count, 2)

    def test_replenish_supply_fails_when_delivery_confirm_button_missing(self):
        task = self.make_task({"coffee_supply_duration": "24小时"})
        runtime = DailyCoffeeRuntime(task)
        runtime.find_text_box = Mock(
            side_effect=lambda text, region: {
                "补货": "buy",
                "24小时": "duration-24h",
            }.get(text)
        )
        runtime.wait_for_supply_popup = Mock(return_value=True)
        runtime.wait_for_button_text_box = Mock(return_value=None)
        runtime.wait_for_supply_blocker_text = Mock(return_value="")
        runtime.wait_for_coffee_shop_panel = Mock(return_value=False)
        runtime.close_popup = Mock()

        result = runtime.replenish_supply()

        self.assertFalse(result.ok)
        self.assertIn("未检测到送货上门确认按钮", result.skip_reason)
        self.assertIn("buy_supply", runtime.actions)
        self.assertNotIn("select_home_delivery", runtime.actions)
        self.assertFalse(result.real_purchase_performed)
        runtime.close_popup.assert_called_once()

    def test_replenish_supply_skips_recently_active_shop_without_buying(self):
        task = self.make_task(
            {
                "coffee_supply_duration": "24小时",
                "coffee_recent_supply_skip_seconds": 300,
            }
        )
        task.ocr_ui.return_value = [FakeBox("累计营业时间"), FakeBox("00:03:38")]
        runtime = DailyCoffeeRuntime(task)
        runtime.find_text_box = Mock()

        result = runtime.replenish_supply()

        self.assertTrue(result.ok)
        self.assertEqual(result.skip_reason, "supply_recently_active_not_needed")
        self.assertFalse(result.real_purchase_performed)
        self.assertIn("supply_recently_active_not_needed:218", runtime.actions)
        runtime.find_text_box.assert_not_called()
        task.click.assert_not_called()

    def test_replenish_supply_default_recent_window_covers_post_validation_reentry(self):
        task = self.make_task({"coffee_supply_duration": "24小时"})
        task.ocr_ui.return_value = [FakeBox("累计营业时间"), FakeBox("00:12:58")]
        runtime = DailyCoffeeRuntime(task)
        runtime.find_text_box = Mock()

        result = runtime.replenish_supply()

        self.assertTrue(result.ok)
        self.assertEqual(result.skip_reason, "supply_recently_active_not_needed")
        self.assertFalse(result.real_purchase_performed)
        self.assertIn("supply_recently_active_not_needed:778", runtime.actions)
        runtime.find_text_box.assert_not_called()
        task.click.assert_not_called()

    def test_replenish_supply_force_purchase_ignores_recent_active_skip(self):
        task = self.make_task(
            {
                "coffee_supply_duration": "24小时",
                "coffee_recent_supply_skip_seconds": 300,
                "coffee_force_supply_purchase": True,
            }
        )
        task.ocr_ui.return_value = [FakeBox("累计营业时间"), FakeBox("00:03:38")]
        runtime = DailyCoffeeRuntime(task)
        runtime.find_text_box = Mock(return_value=None)

        result = runtime.replenish_supply()

        self.assertTrue(result.ok)
        self.assertEqual(result.skip_reason, "supply_not_needed_or_not_found")
        self.assertFalse(result.real_purchase_performed)
        self.assertIn("supply_recently_active_force_purchase:218", runtime.actions)
        self.assertNotIn("supply_recently_active_not_needed:218", runtime.actions)
        runtime.find_text_box.assert_called_once_with("补货", DailyCoffeeRuntime.COFFEE_LEFT_REGION)

    def test_replenish_supply_recent_window_requires_elapsed_time_evidence(self):
        task = self.make_task({"coffee_supply_duration": "24小时"})
        task.ocr_ui.return_value = [FakeBox("营业中"), FakeBox("00:12:58")]
        runtime = DailyCoffeeRuntime(task)
        runtime.find_text_box = Mock(return_value=None)

        result = runtime.replenish_supply()

        self.assertTrue(result.ok)
        self.assertEqual(result.skip_reason, "supply_not_needed_or_not_found")
        self.assertFalse(result.real_purchase_performed)
        self.assertNotIn("supply_recently_active_not_needed:778", runtime.actions)
        runtime.find_text_box.assert_called_once_with("补货", DailyCoffeeRuntime.COFFEE_LEFT_REGION)
        task.click.assert_not_called()

    def test_replenish_supply_retries_buy_once_when_prompt_missing_and_popup_stays(self):
        task = self.make_task({"coffee_supply_duration": "24小时"})
        runtime = DailyCoffeeRuntime(task)
        runtime.find_text_box = Mock(
            side_effect=lambda text, region: {
                "补货": "buy",
                "24小时": "duration-24h",
                "原料库存": "inventory-popup",
            }.get(text)
        )
        runtime.wait_for_supply_popup = Mock(return_value=True)
        runtime.wait_for_supply_blocker_text = Mock(return_value="")
        runtime.find_button_text_box = Mock(return_value=None)
        delivery_calls = {"count": 0}

        def wait_for_delivery_or_confirm(text, region, timeout=4):
            if text == "送货上门":
                delivery_calls["count"] += 1
                return "home-delivery" if delivery_calls["count"] >= 2 else None
            if text == "确认" and delivery_calls["count"] >= 2:
                return "confirm"
            return None

        runtime.wait_for_button_text_box = Mock(side_effect=wait_for_delivery_or_confirm)
        runtime.close_popup = Mock()

        result = runtime.replenish_supply()

        self.assertTrue(result.ok)
        self.assertTrue(result.real_purchase_performed)
        self.assertIn("buy_supply", runtime.actions)
        self.assertEqual(runtime.actions.count("buy_supply_retry_after_no_prompt"), 1)
        self.assertIn("select_home_delivery", runtime.actions)
        self.assertIn("confirm_home_delivery", runtime.actions)
        runtime.close_popup.assert_called_once()

    def test_replenish_supply_retry_still_fails_without_prompt_or_final_state(self):
        task = self.make_task({"coffee_supply_duration": "24小时"})
        runtime = DailyCoffeeRuntime(task)
        runtime.find_text_box = Mock(
            side_effect=lambda text, region: {
                "补货": "buy",
                "24小时": "duration-24h",
                "原料库存": "inventory-popup",
            }.get(text)
        )
        runtime.wait_for_supply_popup = Mock(return_value=True)
        runtime.wait_for_button_text_box = Mock(return_value=None)
        runtime.wait_for_supply_blocker_text = Mock(return_value="")
        runtime.find_button_text_box = Mock(return_value=None)
        runtime.wait_for_coffee_shop_panel = Mock(return_value=False)
        runtime.close_popup = Mock()

        result = runtime.replenish_supply()

        self.assertFalse(result.ok)
        self.assertIn("未检测到送货上门确认按钮", result.skip_reason)
        self.assertIn("buy_supply", runtime.actions)
        self.assertEqual(runtime.actions.count("buy_supply_retry_after_no_prompt"), 1)
        self.assertNotIn("select_home_delivery", runtime.actions)
        self.assertFalse(result.real_purchase_performed)
        runtime.close_popup.assert_called_once()

    def test_replenish_supply_verifies_success_without_delivery_prompt_from_final_shop_state(self):
        task = self.make_task({"coffee_supply_duration": "24小时"})
        runtime = DailyCoffeeRuntime(task)
        runtime.find_text_box = Mock(
            side_effect=lambda text, region: {
                "补货": "buy",
                "24小时": "duration-24h",
                "原料库存": None,
            }.get(text)
        )
        runtime.wait_for_supply_popup = Mock(return_value=True)
        runtime.wait_for_button_text_box = Mock(return_value=None)
        runtime.wait_for_supply_blocker_text = Mock(return_value="")
        runtime.wait_for_coffee_shop_panel = Mock(return_value=True)
        runtime.close_popup = Mock()

        result = runtime.replenish_supply()

        self.assertTrue(result.ok)
        self.assertTrue(result.real_purchase_performed)
        self.assertIn("buy_supply", runtime.actions)
        self.assertIn("supply_purchase_verified_without_delivery_prompt", runtime.actions)
        self.assertNotIn("select_home_delivery", runtime.actions)
        runtime.close_popup.assert_called_once()

    def test_replenish_supply_allows_home_delivery_without_second_confirm_when_prompt_closes(self):
        task = self.make_task({"coffee_supply_duration": "24小时"})
        runtime = DailyCoffeeRuntime(task)
        runtime.find_text_box = Mock(
            side_effect=lambda text, region: {
                "补货": "buy",
                "24小时": "duration-24h",
            }.get(text)
        )
        runtime.wait_for_supply_popup = Mock(return_value=True)
        runtime.wait_for_button_text_box = Mock(
            side_effect=lambda text, region, timeout=4: {
                "送货上门": "home-delivery",
                "确认": None,
            }.get(text)
        )
        runtime.wait_for_supply_blocker_text = Mock(return_value="")
        runtime.find_button_text_box = Mock(return_value=None)
        runtime.close_popup = Mock()

        result = runtime.replenish_supply()

        self.assertTrue(result.ok)
        self.assertTrue(result.real_purchase_performed)
        self.assertIn("select_home_delivery", runtime.actions)
        self.assertNotIn("confirm_home_delivery", runtime.actions)
        runtime.close_popup.assert_called_once()

    def test_ocr_region_uses_fresh_frame_when_available(self):
        task = self.make_task()
        runtime = DailyCoffeeRuntime(task)
        task.ocr_ui.return_value = [FakeBox("商品")]

        result = runtime.ocr_region(DailyCoffeeRuntime.COFFEE_PANEL_REGION)

        self.assertEqual(len(result), 1)
        task.next_frame.assert_called()
        task.ocr_ui.assert_called_with(*DailyCoffeeRuntime.COFFEE_PANEL_REGION, frame="fresh-frame")

    def test_challenge_result_claims_reward_for_coffee_delivery(self):
        task = self.make_task()
        runtime = DailyCoffeeRuntime(task)
        exit_button = FakeBox("退出", y=900)
        claim_button = FakeBox("领取", y=900)
        result_text = FakeBox("挑战成功", y=300)
        state = {"result_visible": True}

        def fake_ocr(*args, **kwargs):
            if state["result_visible"]:
                return [result_text, exit_button, claim_button]
            return []

        def fake_click(target):
            if target is claim_button:
                state["result_visible"] = False

        task.ocr_ui.side_effect = fake_ocr
        task.click.side_effect = fake_click
        runtime.is_coffee_shop_panel = Mock(return_value=False)
        runtime.wait_for_tycoon_panel = Mock(return_value=False)

        result = runtime.open_coffee_shop()

        self.assertFalse(result)
        self.assertIn("claim_coffee_challenge_reward", runtime.actions)
        self.assertTrue(runtime.pending_supply_completed)
        task.click.assert_any_call(claim_button)
        clicked_targets = [args[0] for args, _ in task.click.call_args_list]
        self.assertFalse(any(getattr(target, "text", "") == "退出" for target in clicked_targets))

    def test_open_coffee_shop_closes_existing_product_popup_before_detection(self):
        task = self.make_task()
        runtime = DailyCoffeeRuntime(task)
        runtime.complete_pending_supply_delivery_if_present = Mock(return_value=False)
        runtime.complete_coffee_challenge_if_present = Mock(return_value=False)
        runtime.find_text_box = Mock(
            side_effect=lambda text, region: "popup-title" if text == "商品列表" else None
        )
        runtime.wait_for_coffee_shop_panel = Mock(return_value=True)
        runtime.is_coffee_shop_panel = Mock(return_value=True)
        runtime.close_popup = Mock()

        result = runtime.open_coffee_shop()

        self.assertTrue(result)
        runtime.close_popup.assert_called_once()
        runtime.wait_for_coffee_shop_panel.assert_called_with(timeout=3)

    def test_optimize_products_edits_all_products_from_rightmost_current_slot(self):
        task = self.make_task({"coffee_product_scrolls": 0})
        runtime = DailyCoffeeRuntime(task)
        low_slot_target = FakeBox("low-slot", x=100, y=100, width=40, height=40)
        high_slot_target = FakeBox("high-slot", x=900, y=100, width=40, height=40)
        low = CoffeeFoodOption("low", price_value=10000, target="low-popup")
        current_high = CoffeeFoodOption("current-high", price_value=25000, target="current-high-popup")
        better = CoffeeFoodOption("better", price_value=30000, target="better-popup")
        state = CoffeeShopState(
            trend_category="饮料",
            slots=[
                CoffeeSupplySlot(
                    "low",
                    current_food_identity="low",
                    options=[CoffeeFoodOption("low", price_value=10000, target=low_slot_target)],
                    target=low_slot_target,
                ),
                CoffeeSupplySlot(
                    "current-high",
                    current_food_identity="current-high",
                    options=[CoffeeFoodOption("current-high", price_value=25000, target=high_slot_target)],
                    target=high_slot_target,
                ),
            ],
        )
        runtime.collect_shop_state = Mock(return_value=state)
        runtime.wait_for_product_popup = Mock(return_value=True)
        runtime.collect_product_options = Mock(return_value=[low, current_high, better])
        runtime.close_popup = Mock()

        runtime.optimize_products()

        task.click.assert_any_call(high_slot_target)
        self.assertIn("open_product_editor:current-high", runtime.actions)
        self.assertIn("deselect_product:low", runtime.actions)
        self.assertIn("select_product:better", runtime.actions)
        low_click_index = task.click.mock_calls.index(call("low-popup"))
        better_click_index = task.click.mock_calls.index(call("better-popup"))
        self.assertLess(low_click_index, better_click_index)
        self.assertEqual([option.identity for option in runtime.selected_options], ["better"])

    def test_optimize_products_retries_stable_rightmost_slot_when_text_click_misses(self):
        task = self.make_task({"coffee_product_scrolls": 0})
        runtime = DailyCoffeeRuntime(task)
        slot_target = FakeBox("slot", x=900, y=100, width=40, height=40)
        current = CoffeeFoodOption("current", price_value=25000, target="current-popup")
        state = CoffeeShopState(
            slots=[
                CoffeeSupplySlot(
                    "current",
                    current_food_identity="current",
                    options=[CoffeeFoodOption("current", price_value=25000, target=slot_target)],
                    target=slot_target,
                )
            ]
        )
        runtime.collect_shop_state = Mock(return_value=state)
        runtime.wait_for_product_popup = Mock(side_effect=[False, True])
        runtime.collect_product_options = Mock(return_value=[current])
        runtime.close_popup = Mock()

        runtime.optimize_products()

        self.assertIn("open_product_editor:current", runtime.actions)
        self.assertIn("open_product_editor_fallback_slot", runtime.actions)
        task.click_ui.assert_any_call(
            *DailyCoffeeRuntime.COFFEE_PRODUCT_EDITOR_ENTRY_FALLBACK_POSITION,
            after_sleep=1,
            move=True,
            down_time=0.01,
        )
        self.assertIn("product_switch_not_needed", runtime.actions)

    def test_optimize_products_scans_list_before_switching(self):
        task = self.make_task({"coffee_product_scrolls": 1})
        runtime = DailyCoffeeRuntime(task)
        slot_target = FakeBox("slot", x=900, y=100, width=40, height=40)
        low = CoffeeFoodOption("low", price_value=10000, target="low-popup")
        better = CoffeeFoodOption("better", price_value=30000, target="better-popup")
        state = CoffeeShopState(
            slots=[
                CoffeeSupplySlot(
                    "low",
                    current_food_identity="low",
                    options=[CoffeeFoodOption("low", price_value=10000, target=slot_target)],
                    target=slot_target,
                )
            ]
        )
        runtime.collect_shop_state = Mock(return_value=state)
        runtime.wait_for_product_popup = Mock(return_value=True)
        runtime.collect_product_options = Mock(return_value=[low, better])
        runtime.close_popup = Mock()

        runtime.optimize_products()

        self.assertIn("deselect_product:low", runtime.actions)
        self.assertIn("select_product:better", runtime.actions)
        self.assertIn("scroll_product_options", runtime.actions)
        self.assertIn("reset_product_options_scroll", runtime.actions)

    def test_optimize_products_uses_higher_scrolled_candidate(self):
        task = self.make_task({"coffee_product_scrolls": 1})
        runtime = DailyCoffeeRuntime(task)
        page = {"index": 0}
        slot_target = FakeBox("slot", x=900, y=100, width=40, height=40)
        current = CoffeeFoodOption("current", price_value=30000, target="current-popup")
        lower = CoffeeFoodOption("lower", price_value=20000, target="lower-popup")
        hidden_best = CoffeeFoodOption("hidden-best", price_value=42000, target="hidden-best-popup")
        state = CoffeeShopState(
            slots=[
                CoffeeSupplySlot(
                    "current",
                    current_food_identity="current",
                    options=[CoffeeFoodOption("current", price_value=30000, target=slot_target)],
                    target=slot_target,
                )
            ]
        )
        runtime.collect_shop_state = Mock(return_value=state)
        runtime.wait_for_product_popup = Mock(return_value=True)
        runtime.collect_product_options = Mock(
            side_effect=lambda: [current, lower] if page["index"] == 0 else [hidden_best]
        )

        def scroll_once(options=None, steps=None):
            runtime.actions.append("scroll_product_options")
            page["index"] = 1

        def reset_scroll(options=None, steps=None):
            runtime.actions.append("reset_product_options_scroll")
            page["index"] = 0

        runtime.scroll_product_options = Mock(side_effect=scroll_once)
        runtime.reset_product_options_scroll = Mock(side_effect=reset_scroll)
        runtime.close_popup = Mock()

        runtime.optimize_products()

        self.assertIn("product_best_candidates:hidden-best:42000", runtime.actions)
        self.assertIn("deselect_product:current", runtime.actions)
        self.assertIn("select_product:hidden-best", runtime.actions)
        current_click_index = task.click.mock_calls.index(call("current-popup"))
        hidden_click_index = task.click.mock_calls.index(call("hidden-best-popup"))
        self.assertLess(current_click_index, hidden_click_index)
        self.assertEqual([option.identity for option in runtime.selected_options], ["hidden-best"])

    def test_optimize_products_scans_to_bottom_before_ranking_candidates(self):
        task = self.make_task({"coffee_product_scrolls": 6})
        runtime = DailyCoffeeRuntime(task)
        page = {"index": 0}
        slot_target = FakeBox("slot", x=900, y=100, width=40, height=40)
        current = CoffeeFoodOption("current", price_value=30000, target="current-popup")
        page_one = CoffeeFoodOption("page-one", price_value=31000, target="page-one-popup")
        page_two = CoffeeFoodOption("page-two", price_value=32000, target="page-two-popup")
        bottom_best = CoffeeFoodOption("bottom-best", price_value=52000, target="bottom-best-popup")
        pages = {
            0: [current],
            1: [page_one],
            2: [page_two],
            3: [bottom_best],
        }
        state = CoffeeShopState(
            slots=[
                CoffeeSupplySlot(
                    "current",
                    current_food_identity="current",
                    options=[CoffeeFoodOption("current", price_value=30000, target=slot_target)],
                    target=slot_target,
                )
            ]
        )
        runtime.collect_shop_state = Mock(return_value=state)
        runtime.wait_for_product_popup = Mock(return_value=True)
        runtime.collect_product_options = Mock(side_effect=lambda: pages[min(page["index"], 3)])

        def scroll_down(options=None, steps=None):
            runtime.actions.append("scroll_product_options")
            page["index"] = min(page["index"] + 1, 3)

        def reset_to_top(options=None, steps=None):
            runtime.actions.append(f"reset_product_options_scroll:{steps}")
            page["index"] = 0

        runtime.scroll_product_options = Mock(side_effect=scroll_down)
        runtime.reset_product_options_scroll = Mock(side_effect=reset_to_top)
        runtime.close_popup = Mock()

        runtime.optimize_products()

        self.assertIn("product_scan_reached_bottom", runtime.actions)
        self.assertIn("product_best_candidates:bottom-best:52000", runtime.actions)
        self.assertGreaterEqual(runtime.scroll_product_options.call_count, 4)
        self.assertIn("deselect_product:current", runtime.actions)
        self.assertIn("select_product:bottom-best", runtime.actions)
        current_click_index = task.click.mock_calls.index(call("current-popup"))
        bottom_click_index = task.click.mock_calls.index(call("bottom-best-popup"))
        self.assertLess(current_click_index, bottom_click_index)
        self.assertEqual([option.identity for option in runtime.selected_options], ["bottom-best"])

    def test_product_scan_stops_after_bottom_price_page_repeats(self):
        task = self.make_task({"coffee_product_scrolls": 5})
        runtime = DailyCoffeeRuntime(task)
        page = {"index": 0}
        pages = {
            0: [CoffeeFoodOption("top", price_value=30000, target="top-popup")],
            1: [CoffeeFoodOption("middle", price_value=28000, target="middle-popup")],
            2: [CoffeeFoodOption("bottom-a", price_value=26114, target="bottom-a-popup")],
            3: [CoffeeFoodOption("bottom-name-ocr-variant", price_value=26114, target="bottom-b-popup")],
        }
        runtime.collect_product_options = Mock(side_effect=lambda: pages[min(page["index"], 3)])

        def scroll_down(options=None, steps=None):
            runtime.actions.append("scroll_product_options")
            page["index"] = min(page["index"] + 1, 3)

        def reset_to_top(options=None, steps=None):
            runtime.actions.append(f"reset_product_options_scroll:{steps}")
            page["index"] = 0

        runtime.scroll_product_options = Mock(side_effect=scroll_down)
        runtime.reset_product_options_scroll = Mock(side_effect=reset_to_top)

        options = runtime.collect_product_options_with_scroll()

        self.assertIn("product_scan_reached_bottom", runtime.actions)
        self.assertEqual(runtime.scroll_product_options.call_count, 3)
        self.assertIn("reset_product_options_scroll:3", runtime.actions)
        self.assertEqual([option.price_value for option in options], [30000, 28000, 26114, 26114])

    def test_optimize_products_fills_missing_target_slot_without_deselecting(self):
        task = self.make_task({"coffee_product_scrolls": 0, "coffee_product_target_slots": 4})
        runtime = DailyCoffeeRuntime(task)
        left = FakeBox("slot-left", x=600, y=100, width=40, height=40)
        middle = FakeBox("slot-middle", x=800, y=100, width=40, height=40)
        right = FakeBox("slot-right", x=1000, y=100, width=40, height=40)
        current_a = CoffeeFoodOption("烤椰拿铁", price_value=29037, target="current-a-popup")
        current_b = CoffeeFoodOption("苹果派", price_value=28550, target="current-b-popup")
        current_c = CoffeeFoodOption("焦糖可可千层", price_value=26114, target="current-c-popup")
        best_missing = CoffeeFoodOption("冰摩卡", price_value=30012, target="best-missing-popup")
        state = CoffeeShopState(
            trend_category="饮料",
            slots=[
                CoffeeSupplySlot(
                    "烤椰拿铁",
                    current_food_identity="烤椰拿铁",
                    options=[CoffeeFoodOption("烤椰拿铁", price_value=29037, target=left)],
                    target=left,
                ),
                CoffeeSupplySlot(
                    "苹果派",
                    current_food_identity="苹果派",
                    options=[CoffeeFoodOption("苹果派", price_value=28550, target=middle)],
                    target=middle,
                ),
                CoffeeSupplySlot(
                    "焦糖可可千层",
                    current_food_identity="焦糖可可千层",
                    options=[CoffeeFoodOption("焦糖可可千层", price_value=26114, target=right)],
                    target=right,
                ),
            ],
        )
        runtime.collect_shop_state = Mock(return_value=state)
        runtime.wait_for_product_popup = Mock(return_value=True)
        runtime.collect_product_options = Mock(return_value=[current_a, current_b, current_c, best_missing])
        runtime.find_empty_product_slot = Mock(return_value="empty-slot")
        runtime._verify_product_slot_count = Mock(return_value=True)
        runtime.close_popup = Mock()

        runtime.optimize_products()

        self.assertIn("select_product:冰摩卡", runtime.actions)
        self.assertIn("open_empty_product_slot", runtime.actions)
        self.assertFalse(any(action.startswith("deselect_product:") for action in runtime.actions))
        self.assertEqual([option.identity for option in runtime.selected_options], ["冰摩卡"])

    def test_optimize_products_targets_five_product_slots_when_configured(self):
        task = self.make_task({"coffee_product_scrolls": 0, "coffee_product_target_slots": 5})
        runtime = DailyCoffeeRuntime(task)
        targets = [
            FakeBox(f"slot-{index}", x=600 + index * 100, y=100, width=40, height=40)
            for index in range(4)
        ]
        current = [
            CoffeeFoodOption("苹果派", price_value=32171, target="apple-popup"),
            CoffeeFoodOption("抹茶熔岩慕斯", price_value=36155, target="matcha-popup"),
            CoffeeFoodOption("生巧雪醇拿铁", price_value=34661, target="latte-popup"),
            CoffeeFoodOption("风华琥珀", price_value=32669, target="amber-popup"),
        ]
        missing = CoffeeFoodOption("厚切新鲜牛", price_value=35906, target="steak-popup")
        state = CoffeeShopState(
            trend_category="主食",
            slots=[
                CoffeeSupplySlot(
                    option.identity,
                    current_food_identity=option.identity,
                    options=[CoffeeFoodOption(option.identity, price_value=option.price_value, target=target)],
                    target=target,
                )
                for option, target in zip(current, targets)
            ],
        )
        runtime.collect_shop_state = Mock(return_value=state)
        runtime.wait_for_product_popup = Mock(return_value=True)
        runtime.collect_product_options = Mock(return_value=[*current, missing])
        runtime.find_empty_product_slot = Mock(return_value="empty-slot")
        runtime._verify_product_slot_count = Mock(return_value=True)
        runtime.close_popup = Mock()

        runtime.optimize_products()

        self.assertIn("select_product:厚切新鲜牛", runtime.actions)
        self.assertIn("open_empty_product_slot", runtime.actions)
        self.assertFalse(any(action.startswith("deselect_product:") for action in runtime.actions))
        self.assertEqual([option.identity for option in runtime.selected_options], ["厚切新鲜牛"])

    def test_empty_product_slot_uses_detected_center_point_not_box_object(self):
        task = self.make_task({"coffee_product_scrolls": 0, "coffee_product_target_slots": 5})
        runtime = DailyCoffeeRuntime(task)
        targets = [
            FakeBox(f"slot-{index}", x=600 + index * 100, y=100, width=40, height=40)
            for index in range(4)
        ]
        current = [
            CoffeeFoodOption("苹果派", price_value=32171, target="apple-popup"),
            CoffeeFoodOption("抹茶熔岩慕斯", price_value=36155, target="matcha-popup"),
            CoffeeFoodOption("生巧雪醇拿铁", price_value=34661, target="latte-popup"),
            CoffeeFoodOption("风华琥珀", price_value=32669, target="amber-popup"),
        ]
        missing = CoffeeFoodOption("厚切新鲜牛", price_value=35906, target="steak-popup")
        empty_slot = CoffeeDetectedBox("empty_product_slot", x=1000, y=700, width=80, height=60)
        state = CoffeeShopState(
            slots=[
                CoffeeSupplySlot(
                    option.identity,
                    current_food_identity=option.identity,
                    options=[CoffeeFoodOption(option.identity, price_value=option.price_value, target=target)],
                    target=target,
                )
                for option, target in zip(current, targets)
            ],
        )
        runtime.collect_shop_state = Mock(return_value=state)
        runtime.wait_for_product_popup = Mock(return_value=True)
        runtime.collect_product_options = Mock(return_value=[*current, missing])
        runtime.find_empty_product_slot = Mock(return_value=empty_slot)
        runtime._verify_product_slot_count = Mock(return_value=True)
        runtime.close_popup = Mock()

        runtime.optimize_products()

        self.assertIn("open_empty_product_slot", runtime.actions)
        self.assertIn(call(1040, 730, after_sleep=1, move=True, down_time=0.01), task.click.mock_calls)
        self.assertNotIn(call(empty_slot), task.click.mock_calls)
        self.assertIn("select_product:厚切新鲜牛", runtime.actions)

    def test_fill_missing_slot_tries_next_ranked_candidate_in_same_popup(self):
        task = self.make_task({"coffee_product_scrolls": 0, "coffee_product_target_slots": 5})
        runtime = DailyCoffeeRuntime(task)
        targets = [
            FakeBox(f"slot-{index}", x=600 + index * 100, y=100, width=40, height=40)
            for index in range(4)
        ]
        current = [
            CoffeeFoodOption("苹果派", price_value=32171, target="apple-popup"),
            CoffeeFoodOption("抹茶熔岩慕斯", price_value=36155, target="matcha-popup"),
            CoffeeFoodOption("生巧雪醇拿铁", price_value=34661, target="latte-popup"),
            CoffeeFoodOption("风华琥珀", price_value=32669, target="amber-popup"),
        ]
        best_unmatched = CoffeeFoodOption("羊牛肉三明治", price_value=35906, target="stale-best-popup")
        next_visible = CoffeeFoodOption("金枪鱼三明治", price_value=31673, target="visible-next-popup")
        state = CoffeeShopState(
            slots=[
                CoffeeSupplySlot(
                    option.identity,
                    current_food_identity=option.identity,
                    options=[CoffeeFoodOption(option.identity, price_value=option.price_value, target=target)],
                    target=target,
                )
                for option, target in zip(current, targets)
            ],
        )
        runtime.collect_shop_state = Mock(return_value=state)
        runtime.wait_for_product_popup = Mock(return_value=True)
        runtime.collect_product_options_with_scroll = Mock(return_value=[*current, best_unmatched, next_visible])
        runtime.collect_product_options = Mock(return_value=[next_visible])
        runtime.find_empty_product_slot = Mock(return_value="empty-slot")
        runtime._verify_product_slot_count = Mock(return_value=True)
        runtime.close_popup = Mock()

        runtime.optimize_products()

        self.assertIn("select_product:金枪鱼三明治", runtime.actions)
        self.assertNotIn("select_product:羊牛肉三明治", runtime.actions)
        self.assertIn("open_empty_product_slot", runtime.actions)
        runtime.find_empty_product_slot.assert_called_once()
        self.assertEqual([option.identity for option in runtime.selected_options], ["金枪鱼三明治"])

    def test_visible_product_scan_forwards_price_fallback_to_matching(self):
        task = self.make_task({"coffee_product_scrolls": 0})
        runtime = DailyCoffeeRuntime(task)
        candidate = CoffeeFoodOption("OCR漂移原名", price_value=35906, category="主食")
        visible = CoffeeFoodOption(
            "识别成别名",
            price_value=35906,
            category="主食",
            target=FakeBox("359.06/h", x=500, y=500, width=90, height=38),
        )
        runtime.collect_product_options = Mock(return_value=[visible])

        selected = runtime._click_product_candidates_single_pass(
            [candidate],
            1,
            action="select_product",
            allow_price_fallback=True,
        )

        self.assertEqual(selected, [candidate])
        self.assertIn("select_product:识别成别名", runtime.actions)
        self.assertEqual(task.click.call_count, 1)

    def test_optimize_products_skips_short_fill_candidate_and_tries_next_safe_option(self):
        task = self.make_task({"coffee_product_scrolls": 0, "coffee_product_target_slots": 5})
        runtime = DailyCoffeeRuntime(task)
        targets = [
            FakeBox(f"slot-{index}", x=600 + index * 100, y=100, width=40, height=40)
            for index in range(4)
        ]
        current = [
            CoffeeFoodOption("苹果派", price_value=50000, target="current-a-popup"),
            CoffeeFoodOption("抹茶熔岩慕斯", price_value=49000, target="current-b-popup"),
            CoffeeFoodOption("生巧雪醇拿铁", price_value=48000, target="current-c-popup"),
            CoffeeFoodOption("风华琥珀", price_value=47000, target="current-d-popup"),
        ]
        short_ocr = CoffeeFoodOption("明治", price_value=46000, target="short-popup")
        safe_fill = CoffeeFoodOption("安全补位咖啡", price_value=45000, target="safe-popup")
        state = CoffeeShopState(
            slots=[
                CoffeeSupplySlot(
                    option.identity,
                    current_food_identity=option.identity,
                    options=[CoffeeFoodOption(option.identity, price_value=option.price_value, target=target)],
                    target=target,
                )
                for option, target in zip(current, targets)
            ],
        )
        runtime.collect_shop_state = Mock(return_value=state)
        runtime.wait_for_product_popup = Mock(return_value=True)
        runtime.collect_product_options = Mock(return_value=[*current, short_ocr, safe_fill])
        runtime.find_empty_product_slot = Mock(return_value="empty-slot")
        runtime._verify_product_slot_count = Mock(return_value=True)
        runtime.close_popup = Mock()

        runtime.optimize_products()

        self.assertIn("product_replacement_unstable:明治", runtime.actions)
        self.assertIn("select_product:安全补位咖啡", runtime.actions)
        self.assertFalse(any(action.startswith("deselect_product:") for action in runtime.actions))
        self.assertEqual([option.identity for option in runtime.selected_options], ["安全补位咖啡"])

    def test_optimize_products_skips_same_price_current_ocr_variant_when_filling(self):
        task = self.make_task({"coffee_product_scrolls": 0, "coffee_product_target_slots": 5})
        runtime = DailyCoffeeRuntime(task)
        targets = [
            FakeBox(f"slot-{index}", x=600 + index * 100, y=100, width=40, height=40)
            for index in range(4)
        ]
        current = [
            CoffeeFoodOption("明治厚切新", price_value=35906, target="beef-current-popup"),
            CoffeeFoodOption("抹茶熔岩慕斯", price_value=36155, target="matcha-popup"),
            CoffeeFoodOption("生巧雪醇拿铁", price_value=34661, target="latte-popup"),
            CoffeeFoodOption("风华琥珀", price_value=32669, target="amber-popup"),
        ]
        same_product_variant = CoffeeFoodOption("新鲜牛肉三明治", price_value=35906, target="variant-popup")
        next_safe = CoffeeFoodOption("焦糖可可千层", price_value=29681, target="caramel-popup")
        state = CoffeeShopState(
            slots=[
                CoffeeSupplySlot(
                    option.identity,
                    current_food_identity=option.identity,
                    options=[CoffeeFoodOption(option.identity, price_value=option.price_value, target=target)],
                    target=target,
                )
                for option, target in zip(current, targets)
            ],
        )
        runtime.collect_shop_state = Mock(return_value=state)
        runtime.wait_for_product_popup = Mock(return_value=True)
        runtime.collect_product_options = Mock(return_value=[*current, same_product_variant, next_safe])
        runtime.find_empty_product_slot = Mock(return_value="empty-slot")
        runtime._verify_product_slot_count = Mock(return_value=True)
        runtime.close_popup = Mock()

        runtime.optimize_products()

        self.assertIn("product_fill_same_price_conflict:新鲜牛肉三明治", runtime.actions)
        self.assertIn("select_product:焦糖可可千层", runtime.actions)
        self.assertNotIn("select_product:新鲜牛肉三明治", runtime.actions)
        self.assertFalse(any(action.startswith("deselect_product:") for action in runtime.actions))
        self.assertEqual([option.identity for option in runtime.selected_options], ["焦糖可可千层"])

    def test_optimize_products_fills_missing_slots_from_single_ranked_page_without_resets(self):
        task = self.make_task({"coffee_product_scrolls": 5, "coffee_product_target_slots": 5})
        runtime = DailyCoffeeRuntime(task)
        targets = [
            FakeBox(f"slot-{index}", x=600 + index * 100, y=100, width=40, height=40)
            for index in range(2)
        ]
        current = [
            CoffeeFoodOption("抹茶熔岩慕斯", price_value=36155, target="matcha-popup"),
            CoffeeFoodOption("厚切新鲜牛肉", price_value=35906, target="steak-popup"),
        ]
        fill = [
            CoffeeFoodOption("鲜牛肉三明治", price_value=35906, target="sandwich-popup"),
            CoffeeFoodOption("生巧雪醇拿铁", price_value=34661, target="latte-popup"),
            CoffeeFoodOption("风华琥珀", price_value=32669, target="amber-popup"),
            CoffeeFoodOption("苹果派", price_value=32171, target="apple-popup"),
        ]
        state = CoffeeShopState(
            slots=[
                CoffeeSupplySlot(
                    option.identity,
                    current_food_identity=option.identity,
                    options=[CoffeeFoodOption(option.identity, price_value=option.price_value, target=target)],
                    target=target,
                )
                for option, target in zip(current, targets)
            ],
        )
        runtime.collect_shop_state = Mock(return_value=state)
        runtime.wait_for_product_popup = Mock(return_value=True)
        runtime.collect_product_options_with_scroll = Mock(return_value=[*current, *fill])
        runtime.collect_product_options = Mock(return_value=[*current, *fill])
        runtime.find_empty_product_slot = Mock(return_value="empty-slot")
        runtime._verify_product_slot_count = Mock(return_value=True)
        runtime.close_popup = Mock(side_effect=lambda: runtime.actions.append("close_product_popup"))

        runtime.optimize_products()

        self.assertIn("product_fill_completed:3/3", runtime.actions)
        self.assertEqual(
            [option.identity for option in runtime.selected_options],
            ["生巧雪醇拿铁", "风华琥珀", "苹果派"],
        )
        self.assertEqual(
            task.click.mock_calls,
            [
                call(targets[1]),
                call("empty-slot"),
                call("latte-popup"),
                call("amber-popup"),
                call("apple-popup"),
            ],
        )
        self.assertEqual(
            [
                action
                for action in runtime.actions
                if action == "open_empty_product_slot"
                or action == "close_product_popup"
                or action.startswith("select_product:")
            ],
            [
                "close_product_popup",
                "open_empty_product_slot",
                "select_product:生巧雪醇拿铁",
                "select_product:风华琥珀",
                "select_product:苹果派",
                "close_product_popup",
            ],
        )
        self.assertIn("product_fill_same_price_conflict:鲜牛肉三明治", runtime.actions)
        self.assertFalse(any(action.startswith("deselect_product:") for action in runtime.actions))
        self.assertNotIn("reset_product_options_scroll", runtime.actions)
        task.scroll.assert_not_called()

    def test_optimize_products_treats_fuzzy_same_price_current_as_already_selected(self):
        task = self.make_task({"coffee_product_scrolls": 0, "coffee_product_target_slots": 5})
        runtime = DailyCoffeeRuntime(task)
        slot_target = FakeBox("slot", x=900, y=100, width=40, height=40)
        current = CoffeeFoodOption("享切新鲜牛肉三日", price_value=35906, target=None)
        same_current_candidate = CoffeeFoodOption("厚切新鲜牛肉", price_value=35906, target="steak-popup")
        safe_fill = CoffeeFoodOption("风华琥珀", price_value=32669, target="amber-popup")
        state = CoffeeShopState(
            slots=[
                CoffeeSupplySlot(
                    "享切新鲜牛肉三日",
                    current_food_identity="享切新鲜牛肉三日",
                    options=[CoffeeFoodOption("享切新鲜牛肉三日", price_value=35906, target=slot_target)],
                    target=slot_target,
                )
            ],
        )
        runtime.collect_shop_state = Mock(return_value=state)
        runtime.wait_for_product_popup = Mock(return_value=True)
        runtime.collect_product_options_with_scroll = Mock(return_value=[same_current_candidate, safe_fill])
        runtime.collect_product_options = Mock(return_value=[same_current_candidate, safe_fill])
        runtime.find_empty_product_slot = Mock(return_value="empty-slot")
        runtime.close_popup = Mock()

        runtime.optimize_products()

        self.assertNotIn("select_product:厚切新鲜牛肉", runtime.actions)
        self.assertIn("select_product:风华琥珀", runtime.actions)

    def test_optimize_products_does_not_replace_with_current_ocr_variants_when_full(self):
        task = self.make_task({"coffee_product_scrolls": 0, "coffee_product_target_slots": 5})
        runtime = DailyCoffeeRuntime(task)
        slot_targets = [
            FakeBox(f"slot-{index}", x=600 + index * 100, y=100, width=40, height=40)
            for index in range(5)
        ]
        current = [
            CoffeeFoodOption("厚切新鮮牛", price_value=35906, target="beef-current-popup"),
            CoffeeFoodOption("抹茶熔岩慕斯", price_value=36155, target="matcha-popup"),
            CoffeeFoodOption("生巧雪醇拿铁", price_value=34661, target="latte-popup"),
            CoffeeFoodOption("风华琥珀", price_value=32669, target="amber-popup"),
            CoffeeFoodOption("苹果派", price_value=32171, target="apple-popup"),
        ]
        prefixed_sandwich_variant = CoffeeFoodOption("i鲜牛肉三明治", price_value=35906, target="prefixed-sandwich-popup")
        fresh_sandwich_variant = CoffeeFoodOption("鲜牛肉三明治", price_value=35906, target="sandwich-popup")
        short_sandwich_variant = CoffeeFoodOption("肉三明治", price_value=35906, target="short-sandwich-popup")
        beef_variant = CoffeeFoodOption("厚切新鲜牛肉！", price_value=35906, target="beef-variant-popup")
        short_beef_variant = CoffeeFoodOption("厚切新鱼", price_value=35906, target="short-beef-popup")
        state = CoffeeShopState(
            slots=[
                CoffeeSupplySlot(
                    option.identity,
                    current_food_identity=option.identity,
                    options=[CoffeeFoodOption(option.identity, price_value=option.price_value, target=target)],
                    target=target,
                )
                for option, target in zip(current, slot_targets)
            ],
        )
        runtime.collect_shop_state = Mock(return_value=state)
        runtime.wait_for_product_popup = Mock(return_value=True)
        runtime.collect_product_options = Mock(
            return_value=[
                current[1],
                prefixed_sandwich_variant,
                fresh_sandwich_variant,
                short_sandwich_variant,
                beef_variant,
                short_beef_variant,
                current[2],
                current[3],
                current[4],
            ]
        )
        runtime.close_popup = Mock()

        runtime.optimize_products()

        self.assertIn("product_replacement_same_price_conflict:i鲜牛肉三明治", runtime.actions)
        self.assertIn("product_replacement_same_price_conflict:鲜牛肉三明治", runtime.actions)
        self.assertIn("product_replacement_same_price_conflict:肉三明治", runtime.actions)
        self.assertNotIn("select_product:鲜牛肉三明治", runtime.actions)
        self.assertNotIn("select_product:i鲜牛肉三明治", runtime.actions)
        self.assertNotIn("select_product:肉三明治", runtime.actions)
        self.assertNotIn("select_product:厚切新鲜牛肉！", runtime.actions)
        self.assertNotIn("select_product:厚切新鱼", runtime.actions)
        self.assertNotIn("deselect_product:苹果派", runtime.actions)
        self.assertNotIn("deselect_product:风华琥珀", runtime.actions)
        self.assertNotIn("deselect_product:生巧雪醇拿铁", runtime.actions)
        self.assertEqual(runtime.selected_options, [])

    def test_optimize_products_preserves_full_count_for_duplicate_current_ocr_with_different_prices(self):
        task = self.make_task({"coffee_product_scrolls": 0, "coffee_product_target_slots": 5})
        runtime = DailyCoffeeRuntime(task)
        slot_targets = [
            FakeBox(f"slot-{index}", x=600 + index * 100, y=100, width=40, height=40)
            for index in range(5)
        ]
        current = [
            CoffeeFoodOption("苹果派", price_value=32171, target="apple-popup"),
            CoffeeFoodOption("抹茶熔岩慕斯", price_value=36155, target="matcha-popup"),
            CoffeeFoodOption("台", price_value=34661, target="latte-slot-popup"),
            CoffeeFoodOption("台", price_value=35906, target="beef-slot-popup"),
            CoffeeFoodOption("风华琥珀", price_value=32669, target="amber-popup"),
        ]
        state = CoffeeShopState(
            trend_category="主食",
            slots=[
                CoffeeSupplySlot(
                    option.identity,
                    current_food_identity=option.identity,
                    options=[CoffeeFoodOption(option.identity, price_value=option.price_value, target=target)],
                    target=target,
                )
                for option, target in zip(current, slot_targets)
            ],
        )
        runtime.collect_shop_state = Mock(return_value=state)
        runtime.wait_for_product_popup = Mock(return_value=True)
        runtime.collect_product_options = Mock(
            return_value=[
                current[1],
                CoffeeFoodOption("厚切", price_value=35906, target="short-beef-popup"),
                CoffeeFoodOption("鲜牛肉三明治", price_value=35906, target="sandwich-popup"),
                CoffeeFoodOption("生巧雪醇拿铁", price_value=34661, target="latte-popup"),
                current[4],
                current[0],
                CoffeeFoodOption("金枪鱼三明治", price_value=31673, target="tuna-popup"),
            ]
        )
        runtime.find_empty_product_slot = Mock(return_value="empty-slot")
        runtime.close_popup = Mock()

        runtime.optimize_products()

        runtime.find_empty_product_slot.assert_not_called()
        self.assertIn("product_replacement_same_price_conflict:厚切", runtime.actions)
        self.assertIn("product_replacement_same_price_conflict:鲜牛肉三明治", runtime.actions)
        self.assertIn("product_replacement_same_price_conflict:生巧雪醇拿铁", runtime.actions)
        self.assertIn("product_switch_not_needed", runtime.actions)
        self.assertNotIn("product_fill_incomplete:0/1", runtime.actions)
        self.assertFalse(any(action.startswith("select_product:") for action in runtime.actions))
        self.assertFalse(any(action.startswith("deselect_product:") for action in runtime.actions))
        self.assertEqual(runtime.selected_options, [])

    def test_current_product_options_keeps_same_identity_with_different_prices(self):
        task = self.make_task()
        runtime = DailyCoffeeRuntime(task)
        slots = [
            CoffeeSupplySlot(
                "台",
                current_food_identity="台",
                options=[CoffeeFoodOption("台", price_value=34661)],
            ),
            CoffeeSupplySlot(
                "台",
                current_food_identity="台",
                options=[CoffeeFoodOption("台", price_value=35906)],
            ),
        ]

        current = runtime._current_product_options(slots, [])

        self.assertEqual([option.price_value for option in current], [34661, 35906])

    def test_protected_current_product_options_includes_popup_and_slot_options(self):
        task = self.make_task()
        runtime = DailyCoffeeRuntime(task)
        slots = [
            CoffeeSupplySlot(
                "台",
                current_food_identity="台",
                options=[CoffeeFoodOption("台", price_value=34661)],
            )
        ]
        current_options = [CoffeeFoodOption("抹茶熔岩慕斯", price_value=36155)]

        protected = runtime._protected_current_product_options(slots, current_options)

        self.assertEqual(
            {(option.identity, option.price_value) for option in protected},
            {("抹茶熔岩慕斯", 36155), ("台", 34661)},
        )

    def test_optimize_products_batches_multiple_replacements_in_single_popup(self):
        task = self.make_task({"coffee_product_scrolls": 0, "coffee_product_target_slots": 5})
        runtime = DailyCoffeeRuntime(task)
        slot_targets = [
            FakeBox(f"slot-{index}", x=600 + index * 100, y=100, width=40, height=40)
            for index in range(5)
        ]
        current = [
            CoffeeFoodOption("低价一", price_value=10000, target="low-one-popup"),
            CoffeeFoodOption("低价二", price_value=11000, target="low-two-popup"),
            CoffeeFoodOption("保留一", price_value=30000, target="keep-one-popup"),
            CoffeeFoodOption("保留二", price_value=31000, target="keep-two-popup"),
            CoffeeFoodOption("保留三", price_value=32000, target="keep-three-popup"),
        ]
        better = [
            CoffeeFoodOption("高价一", price_value=50000, target="high-one-popup"),
            CoffeeFoodOption("高价二", price_value=49000, target="high-two-popup"),
        ]
        state = CoffeeShopState(
            slots=[
                CoffeeSupplySlot(
                    option.identity,
                    current_food_identity=option.identity,
                    options=[CoffeeFoodOption(option.identity, price_value=option.price_value, target=target)],
                    target=target,
                )
                for option, target in zip(current, slot_targets)
            ],
        )
        runtime.collect_shop_state = Mock(return_value=state)
        runtime.wait_for_product_popup = Mock(return_value=True)
        runtime.collect_product_options = Mock(return_value=[*current, *better])
        runtime._verify_product_slot_count = Mock(return_value=True)
        runtime.close_popup = Mock(side_effect=lambda: runtime.actions.append("close_product_popup"))

        runtime.optimize_products()

        self.assertIn("deselect_product:低价一", runtime.actions)
        self.assertIn("deselect_product:低价二", runtime.actions)
        self.assertIn("select_product:高价一", runtime.actions)
        self.assertIn("select_product:高价二", runtime.actions)
        self.assertEqual(
            task.click.mock_calls,
            [
                call(slot_targets[-1]),
                call("low-one-popup"),
                call("low-two-popup"),
                call("high-one-popup"),
                call("high-two-popup"),
            ],
        )
        self.assertEqual(
            [
                action
                for action in runtime.actions
                if action == "close_product_popup"
                or action.startswith("deselect_product:")
                or action.startswith("select_product:")
            ],
            [
                "deselect_product:低价一",
                "deselect_product:低价二",
                "select_product:高价一",
                "select_product:高价二",
                "close_product_popup",
            ],
        )
        self.assertEqual([option.identity for option in runtime.selected_options], ["高价一", "高价二"])
        runtime._verify_product_slot_count.assert_called_once_with(5)

    def test_optimize_products_fails_when_replacement_does_not_verify_target_count(self):
        task = self.make_task({"coffee_product_scrolls": 0, "coffee_product_target_slots": 5})
        runtime = DailyCoffeeRuntime(task)
        slot_targets = [
            FakeBox(f"slot-{index}", x=600 + index * 100, y=100, width=40, height=40)
            for index in range(5)
        ]
        current = [
            CoffeeFoodOption("低价一", price_value=10000, target="low-one-popup"),
            CoffeeFoodOption("低价二", price_value=11000, target="low-two-popup"),
            CoffeeFoodOption("保留一", price_value=30000, target="keep-one-popup"),
            CoffeeFoodOption("保留二", price_value=31000, target="keep-two-popup"),
            CoffeeFoodOption("保留三", price_value=32000, target="keep-three-popup"),
        ]
        better = [
            CoffeeFoodOption("高价一", price_value=50000, target="high-one-popup"),
            CoffeeFoodOption("高价二", price_value=49000, target="high-two-popup"),
        ]
        state = CoffeeShopState(
            slots=[
                CoffeeSupplySlot(
                    option.identity,
                    current_food_identity=option.identity,
                    options=[CoffeeFoodOption(option.identity, price_value=option.price_value, target=target)],
                    target=target,
                )
                for option, target in zip(current, slot_targets)
            ],
        )
        runtime.collect_shop_state = Mock(return_value=state)
        runtime.wait_for_product_popup = Mock(return_value=True)
        runtime.collect_product_options = Mock(return_value=[*current, *better])
        runtime._verify_product_slot_count = Mock(return_value=False)
        runtime.close_popup = Mock()

        runtime.optimize_products()

        self.assertIn("deselect_product:低价一", runtime.actions)
        self.assertIn("select_product:高价一", runtime.actions)
        self.assertEqual(runtime.product_switch_error, "商品替换后未验证到5个商品")
        runtime._verify_product_slot_count.assert_called_once_with(5)

    def test_optimize_products_does_not_cancel_current_when_replacement_is_not_reachable(self):
        task = self.make_task({"coffee_product_scrolls": 0})
        runtime = DailyCoffeeRuntime(task)
        slot_target = FakeBox("slot", x=900, y=100, width=40, height=40)
        current = CoffeeFoodOption("苹果派", price_value=10000, target="current-popup")
        better = CoffeeFoodOption("冰摩卡", price_value=20000, target="better-popup")
        state = CoffeeShopState(
            slots=[
                CoffeeSupplySlot(
                    "苹果派",
                    current_food_identity="苹果派",
                    options=[CoffeeFoodOption("苹果派", price_value=10000, target=slot_target)],
                    target=slot_target,
                )
            ],
        )
        runtime.collect_shop_state = Mock(return_value=state)
        runtime.wait_for_product_popup = Mock(return_value=True)
        runtime.collect_product_options = Mock(side_effect=[[current, better], [current], [current]])
        runtime.close_popup = Mock()

        runtime.optimize_products()

        self.assertIn("select_product_not_visible:冰摩卡", runtime.actions)
        self.assertNotIn("deselect_product:苹果派", runtime.actions)
        self.assertFalse(runtime.product_switch_error)
        self.assertNotIn(call("current-popup"), task.click.mock_calls)

    def test_run_stops_if_product_switch_deselects_without_selecting(self):
        task = self.make_task({"coffee_product_scrolls": 0})
        runtime = DailyCoffeeRuntime(task)
        runtime.open_coffee_shop = Mock(return_value=True)
        runtime.claim_income_if_present = Mock(return_value=False)
        runtime.replenish_supply = Mock()

        def failed_optimize():
            runtime.actions.append("deselect_product:old")
            runtime.actions.append("select_product_not_found:new")
            runtime.product_switch_error = "商品替换失败: 已取消old但未能选择new"

        runtime.optimize_products = Mock(side_effect=failed_optimize)

        result = runtime.run()

        self.assertFalse(result.ok)
        self.assertIn("商品替换失败", result.skip_reason)
        runtime.replenish_supply.assert_not_called()

    def test_run_stops_when_product_editor_entry_is_missing(self):
        task = self.make_task({"coffee_product_scrolls": 0})
        runtime = DailyCoffeeRuntime(task)
        runtime.open_coffee_shop = Mock(return_value=True)
        runtime.claim_income_if_present = Mock(return_value=False)
        runtime.collect_shop_state = Mock(return_value=CoffeeShopState(slots=[]))
        runtime.replenish_supply = Mock()

        result = runtime.run()

        self.assertFalse(result.ok)
        self.assertEqual(result.skip_reason, "未检测到可编辑商品入口")
        runtime.replenish_supply.assert_not_called()

    def test_optimize_products_does_not_cancel_when_no_higher_price_exists(self):
        task = self.make_task({"coffee_product_scrolls": 0})
        runtime = DailyCoffeeRuntime(task)
        slot_target = FakeBox("slot", x=900, y=100, width=40, height=40)
        current = CoffeeFoodOption("current", price_value=30000, target="current-popup")
        lower = CoffeeFoodOption("lower", price_value=20000, target="lower-popup")
        state = CoffeeShopState(
            slots=[
                CoffeeSupplySlot(
                    "current",
                    current_food_identity="current",
                    options=[CoffeeFoodOption("current", price_value=30000, target=slot_target)],
                    target=slot_target,
                )
            ]
        )
        runtime.collect_shop_state = Mock(return_value=state)
        runtime.wait_for_product_popup = Mock(return_value=True)
        runtime.collect_product_options = Mock(return_value=[current, lower])
        runtime.close_popup = Mock()

        runtime.optimize_products()

        task.click.assert_called_once_with(slot_target)
        self.assertIn("product_switch_not_needed", runtime.actions)
        self.assertNotIn("deselect_product:current", runtime.actions)
        self.assertEqual(runtime.selected_options, [])

    def test_optimize_products_matches_current_product_by_unique_price_when_ocr_name_differs(self):
        task = self.make_task({"coffee_product_scrolls": 0})
        runtime = DailyCoffeeRuntime(task)
        slot_target = FakeBox("slot", x=900, y=100, width=40, height=40)
        popup_low = CoffeeFoodOption("西", price_value=11985, target="low-popup")
        popup_high = CoffeeFoodOption("冰摩卡", price_value=30012, target="high-popup")
        state = CoffeeShopState(
            slots=[
                CoffeeSupplySlot(
                    "西红柿煎蛋可颂",
                    current_food_identity="西红柿煎蛋可颂",
                    options=[CoffeeFoodOption("西红柿煎蛋可颂", price_value=11985, target=slot_target)],
                    target=slot_target,
                )
            ]
        )
        runtime.collect_shop_state = Mock(return_value=state)
        runtime.wait_for_product_popup = Mock(return_value=True)
        runtime.collect_product_options = Mock(return_value=[popup_low, popup_high])
        runtime.close_popup = Mock()

        runtime.optimize_products()

        self.assertIn("open_product_editor:西红柿煎蛋可颂", runtime.actions)
        self.assertIn("deselect_product:西", runtime.actions)
        self.assertIn("select_product:冰摩卡", runtime.actions)
        low_click_index = task.click.mock_calls.index(call("low-popup"))
        high_click_index = task.click.mock_calls.index(call("high-popup"))
        self.assertLess(low_click_index, high_click_index)
        self.assertEqual([option.identity for option in runtime.selected_options], ["冰摩卡"])

    def test_optimize_products_does_not_price_match_non_low_same_price_product(self):
        task = self.make_task({"coffee_product_scrolls": 0})
        runtime = DailyCoffeeRuntime(task)
        low_slot_target = FakeBox("low-slot", x=100, y=100, width=40, height=40)
        current_slot_target = FakeBox("current-slot", x=900, y=100, width=40, height=40)
        popup_low = CoffeeFoodOption("i红柿煎蛋可颂", price_value=11985, target="low-popup")
        wrong_same_price = CoffeeFoodOption("雪顶抹茶拿铁", price_value=26601, target="wrong-popup")
        better = CoffeeFoodOption("冰摩卡", price_value=30012, target="high-popup")
        state = CoffeeShopState(
            slots=[
                CoffeeSupplySlot(
                    "西红柿煎蛋可颂",
                    current_food_identity="西红柿煎蛋可颂",
                    options=[CoffeeFoodOption("西红柿煎蛋可颂", price_value=11985, target=low_slot_target)],
                    target=low_slot_target,
                ),
                CoffeeSupplySlot(
                    "焦糖可可千层",
                    current_food_identity="焦糖可可千层",
                    options=[CoffeeFoodOption("焦糖可可千层", price_value=26601, target=current_slot_target)],
                    target=current_slot_target,
                ),
            ]
        )
        runtime.collect_shop_state = Mock(return_value=state)
        runtime.wait_for_product_popup = Mock(return_value=True)
        runtime.collect_product_options = Mock(return_value=[popup_low, wrong_same_price, better])
        runtime.close_popup = Mock()

        runtime.optimize_products()

        self.assertIn("deselect_product:i红柿煎蛋可颂", runtime.actions)
        self.assertIn("select_product:冰摩卡", runtime.actions)
        self.assertNotIn("deselect_product:雪顶抹茶拿铁", runtime.actions)
        self.assertNotIn(call("wrong-popup"), task.click.mock_calls)

    def test_optimize_products_skips_short_replacement_when_same_price_current_exists(self):
        task = self.make_task({"coffee_product_scrolls": 0})
        runtime = DailyCoffeeRuntime(task)
        low_slot_target = FakeBox("low-slot", x=100, y=100, width=40, height=40)
        same_price_slot_target = FakeBox("same-price-slot", x=900, y=100, width=40, height=40)
        low_current = CoffeeFoodOption("西红柿煎蛋", price_value=30677, target="low-popup")
        same_price_current = CoffeeFoodOption("生巧雪醇拿铁", price_value=34661, target="same-price-popup")
        unstable_replacement = CoffeeFoodOption("明治", price_value=34661, target="unstable-popup")
        state = CoffeeShopState(
            slots=[
                CoffeeSupplySlot(
                    "西红柿煎蛋可颂",
                    current_food_identity="西红柿煎蛋可颂",
                    options=[CoffeeFoodOption("西红柿煎蛋可颂", price_value=30677, target=low_slot_target)],
                    target=low_slot_target,
                ),
                CoffeeSupplySlot(
                    "生巧雪醇拿铁",
                    current_food_identity="生巧雪醇拿铁",
                    options=[CoffeeFoodOption("生巧雪醇拿铁", price_value=34661, target=same_price_slot_target)],
                    target=same_price_slot_target,
                ),
            ]
        )
        runtime.collect_shop_state = Mock(return_value=state)
        runtime.wait_for_product_popup = Mock(return_value=True)
        runtime.collect_product_options = Mock(return_value=[low_current, same_price_current, unstable_replacement])
        runtime.close_popup = Mock()

        runtime.optimize_products()

        self.assertIn("product_replacement_same_price_conflict:明治", runtime.actions)
        self.assertIn("product_switch_not_needed", runtime.actions)
        self.assertNotIn("deselect_product:西红柿煎蛋", runtime.actions)
        self.assertNotIn(call("low-popup"), task.click.mock_calls)
        self.assertEqual(runtime.selected_options, [])

    def test_scroll_product_options_wheels_inside_product_list(self):
        task = self.make_task({"coffee_product_scrolls": 1})
        runtime = DailyCoffeeRuntime(task)

        runtime.scroll_product_options(steps=1)

        task.scroll.assert_called_once()
        x, y, count = task.scroll.call_args.args
        self.assertEqual((x, y), (int(task.width * 0.20), int(task.height * 0.58)))
        self.assertEqual(count, DailyCoffeeRuntime.COFFEE_PRODUCT_SCROLL_WHEEL_COUNT)
        task.swipe.assert_not_called()
        task.mouse_down.assert_not_called()
        task.mouse_up.assert_not_called()

    def test_scroll_product_options_converts_relative_ui_point_to_pixels(self):
        task = self.make_task({"coffee_product_scrolls": 1})
        task.ui_point = lambda x, y: (x, y)
        runtime = DailyCoffeeRuntime(task)

        runtime.scroll_product_options(steps=1)

        x, y, _ = task.scroll.call_args.args
        self.assertEqual((x, y), (int(task.width * 0.20), int(task.height * 0.58)))

    def test_scroll_product_options_uses_recognized_product_region(self):
        task = self.make_task({"coffee_product_scrolls": 1})
        runtime = DailyCoffeeRuntime(task)
        options = [
            CoffeeFoodOption("a", target=FakeBox("80/h", x=140, y=220, width=90, height=38)),
            CoffeeFoodOption("b", target=FakeBox("144/h", x=500, y=520, width=90, height=38)),
            CoffeeFoodOption("c", target=FakeBox("202/h", x=620, y=900, width=90, height=38)),
        ]

        runtime.scroll_product_options(options, steps=1)

        x, y, count = task.scroll.call_args.args
        self.assertGreater(x, int(task.width * DailyCoffeeRuntime.COFFEE_PRODUCT_POPUP_REGION[0]))
        self.assertLess(x, int(task.width * DailyCoffeeRuntime.COFFEE_PRODUCT_POPUP_REGION[2]))
        self.assertGreater(y, int(task.height * DailyCoffeeRuntime.COFFEE_PRODUCT_POPUP_REGION[1]))
        self.assertLess(y, int(task.height * DailyCoffeeRuntime.COFFEE_PRODUCT_POPUP_REGION[3]))
        self.assertEqual(count, DailyCoffeeRuntime.COFFEE_PRODUCT_SCROLL_WHEEL_COUNT)
        self.assertNotEqual((x, y), (512, 928))

    def test_scroll_product_options_ignores_edge_boxes_and_falls_back(self):
        task = self.make_task({"coffee_product_scrolls": 1})
        runtime = DailyCoffeeRuntime(task)
        options = [
            CoffeeFoodOption("edge-top", target=FakeBox("80/h", x=5, y=20, width=20, height=20)),
            CoffeeFoodOption("edge-right", target=FakeBox("90/h", x=920, y=700, width=20, height=20)),
        ]

        runtime.scroll_product_options(options, steps=1)

        x, y, _ = task.scroll.call_args.args
        self.assertEqual((x, y), (int(task.width * 0.20), int(task.height * 0.58)))

    def test_scroll_product_options_falls_back_without_recognized_region(self):
        task = self.make_task({"coffee_product_scrolls": 1})
        runtime = DailyCoffeeRuntime(task)

        runtime.scroll_product_options([], steps=1)

        x, y, _ = task.scroll.call_args.args
        self.assertEqual((x, y), (int(task.width * 0.20), int(task.height * 0.58)))

    def test_product_scrolls_promotes_legacy_single_scroll_to_full_scan(self):
        task = self.make_task({"coffee_product_scrolls": 1})
        runtime = DailyCoffeeRuntime(task)

        self.assertEqual(runtime._product_scrolls(), DailyCoffeeRuntime.COFFEE_PRODUCT_DEFAULT_SCAN_SCROLLS)

    def test_product_scrolls_keeps_zero_as_disabled_for_unit_paths(self):
        task = self.make_task({"coffee_product_scrolls": 0})
        runtime = DailyCoffeeRuntime(task)

        self.assertEqual(runtime._product_scrolls(), 0)


if __name__ == "__main__":
    unittest.main()
