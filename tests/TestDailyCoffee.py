import unittest
from unittest.mock import MagicMock

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


class TestDailyCoffeeLocaleGate(unittest.TestCase):
    """BnanZ0 PR #86 反馈: 仅在 zh_CN 下暴露一咖舍自动化给 UI."""

    def _patch_locale(self, name=None, *, raise_exc=False, missing_app=False, missing_locale=False):
        from unittest.mock import MagicMock

        from ok import og

        original_app = getattr(og, "app", None)
        if missing_app:
            og.app = None
            return original_app

        app = MagicMock()
        if missing_locale:
            del app.locale
        else:
            if raise_exc:
                app.locale.name.side_effect = RuntimeError("locale unavailable")
            else:
                app.locale.name.return_value = name
        og.app = app
        return original_app

    def _restore_app(self, original_app):
        from ok import og

        og.app = original_app

    def _instantiate(self):
        # 真实 __init__ 路径覆盖 locale 检测 + AnomalyTask.setup_config 等.
        # 提供最小 executor / app mock 以满足 BaseTask.__init__ 签名.
        executor = MagicMock()
        executor.onetime_tasks = []
        executor.trigger_tasks = []
        ctor_app = MagicMock()
        return DailyTask(executor=executor, app=ctor_app)

    def test_zh_cn_locale_exposes_auto_coffee_mode(self):
        original = self._patch_locale("zh_CN")
        try:
            task = self._instantiate()
            self.assertIn(DailyTask.CONF_COFFEE_TASK, task.default_config)
            self.assertEqual(
                DailyTask.COFFEE_MODE_NONE,
                task.default_config[DailyTask.CONF_COFFEE_TASK],
            )
            self.assertEqual(
                [
                    DailyTask.COFFEE_MODE_NONE,
                    DailyTask.COFFEE_MODE_CLAIM_AND_RESTOCK,
                    DailyTask.COFFEE_MODE_AUTO,
                ],
                task.config_type[DailyTask.CONF_COFFEE_TASK]["options"],
            )
        finally:
            self._restore_app(original)

    def test_non_zh_cn_locale_hides_auto_coffee_mode(self):
        original = self._patch_locale("en_US")
        try:
            task = self._instantiate()
            self.assertNotIn(DailyTask.COFFEE_MODE_AUTO, task.default_config)
            self.assertNotIn(DailyTask.COFFEE_MODE_AUTO, task.config_description)
            self.assertEqual(
                [DailyTask.COFFEE_MODE_NONE, DailyTask.COFFEE_MODE_CLAIM_AND_RESTOCK],
                task.config_type[DailyTask.CONF_COFFEE_TASK]["options"],
            )
        finally:
            self._restore_app(original)

    def test_missing_locale_attribute_hides_toggle(self):
        # ``og.app`` 存在但没有 ``locale`` 属性 (例如某些 headless 环境).
        # 守卫要求 hasattr(app, "locale") 才会调用 ``locale.name()``.
        original = self._patch_locale(missing_locale=True)
        try:
            task = self._instantiate()
            self.assertNotIn(DailyTask.COFFEE_MODE_AUTO, task.default_config)
            self.assertNotIn(
                DailyTask.COFFEE_MODE_AUTO,
                task.config_type[DailyTask.CONF_COFFEE_TASK]["options"],
            )
        finally:
            self._restore_app(original)

    def test_locale_call_raising_does_not_raise_and_hides_toggle(self):
        original = self._patch_locale(raise_exc=True)
        try:
            task = self._instantiate()
            self.assertNotIn(DailyTask.COFFEE_MODE_AUTO, task.default_config)
            self.assertNotIn(
                DailyTask.COFFEE_MODE_AUTO,
                task.config_type[DailyTask.CONF_COFFEE_TASK]["options"],
            )
        finally:
            self._restore_app(original)

    def test_dropdown_mode_selects_restock_task(self):
        task = TestDailyCoffee()._task(
            {DailyTask.CONF_COFFEE_TASK: DailyTask.COFFEE_MODE_AUTO}
        )  # noqa: SLF001 - reuse stub helper

        entry = DailyTask._coffee_task_entry(task)

        self.assertIsNotNone(entry)
        key, enabled, func = entry
        self.assertEqual(DailyTask.COFFEE_MODE_AUTO, key)
        self.assertTrue(enabled)
        self.assertEqual(DailyTask.run_coffee_task.__name__, func.__name__)

    def test_old_bool_config_does_not_select_restock_task(self):
        task = TestDailyCoffee()._task(
            {"运行一咖舍自动化": True}
        )  # noqa: SLF001

        self.assertIsNone(DailyTask._coffee_task_entry(task))

    def test_dropdown_mode_none_skips_coffee_task(self):
        task = TestDailyCoffee()._task(
            {DailyTask.CONF_COFFEE_TASK: DailyTask.COFFEE_MODE_NONE}
        )  # noqa: SLF001 - reuse stub helper

        self.assertIsNone(DailyTask._coffee_task_entry(task))

    def test_claim_coffee_runtime_still_restocks(self):
        original = self._patch_locale("en_US")
        try:
            task = TestDailyCoffee()._task({})  # noqa: SLF001 - reuse stub helper
            self.assertNotIn(DailyTask.COFFEE_MODE_AUTO, task.config)
            self.assertTrue(DailyTask.claim_coffee(task))
            click_positions = [(x, y) for x, y, _ in task.clicks]
            self.assertIn((0.115, 0.53), click_positions)
            self.assertIn((0.34, 0.785), click_positions)
        finally:
            self._restore_app(original)


if __name__ == "__main__":
    unittest.main()
