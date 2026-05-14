import unittest

from src.tasks.DailyTask import DailyTask


class TestDailyCoffee(unittest.TestCase):
    def _task(self, config=None):
        task = object.__new__(DailyTask)
        task.config = config or {}
        task.clicks = []
        task.wait_until_calls = []
        task.info_messages = []
        task.error_messages = []

        task.openF5panel = lambda: None
        task.sleep = lambda seconds: None
        task.wait_panel = lambda label: True
        task.find_one = lambda label: True
        task.ensure_main = lambda: None
        task.retry_on_action = lambda action, reset_action=None: action()
        task.log_info = lambda message, *args, **kwargs: task.info_messages.append(message)
        task.log_error = lambda message, *args, **kwargs: task.error_messages.append(message)

        def operate_click(x, y, *args, **kwargs):
            task.clicks.append((round(float(x), 3), round(float(y), 3), dict(kwargs)))

        def wait_until(predicate, **kwargs):
            task.wait_until_calls.append(kwargs)
            pre_action = kwargs.get("pre_action")
            if callable(pre_action):
                pre_action()
            return bool(predicate())

        task.operate_click = operate_click
        task.wait_until = wait_until
        return task

    def test_claim_coffee_restock_enabled_by_default(self):
        task = self._task()

        self.assertTrue(DailyTask.claim_coffee(task))

        click_positions = [(x, y) for x, y, _ in task.clicks]
        self.assertIn((0.188, 0.877), click_positions)
        self.assertIn((0.115, 0.53), click_positions)
        self.assertIn((0.34, 0.785), click_positions)
        self.assertIn((0.717, 0.787), click_positions)
        self.assertIn((0.595, 0.776), click_positions)
        self.assertIn((0.6, 0.656), click_positions)
        self.assertEqual(len(task.wait_until_calls), 2)

    def test_claim_coffee_can_skip_restock_purchase(self):
        task = self._task({DailyTask.CONF_RESTOCK_COFFEE: False})

        self.assertTrue(DailyTask.claim_coffee(task))

        click_positions = [(x, y) for x, y, _ in task.clicks]
        self.assertIn((0.188, 0.877), click_positions)
        self.assertIn((0.072, 0.886), click_positions)
        self.assertNotIn((0.115, 0.53), click_positions)
        self.assertNotIn((0.34, 0.785), click_positions)
        self.assertNotIn((0.717, 0.787), click_positions)
        self.assertNotIn((0.595, 0.776), click_positions)
        self.assertNotIn((0.6, 0.656), click_positions)
        self.assertEqual(len(task.wait_until_calls), 1)
        self.assertIn("已跳过一咖舍补货", task.info_messages)


if __name__ == "__main__":
    unittest.main()
