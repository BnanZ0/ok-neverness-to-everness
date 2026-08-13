from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from src.tasks.AnomalyHunter import AnomalyHunter
from src.tasks.AnomalyTask import AnomalyTask
from src.tasks.BaseNTETask import BaseNTETask
from src.tasks.daily.DailyPlanTask import (
    DailyPlanTask,
    plan_has_active_tasks,
    selected_plan_tasks,
    selection_is_complete,
    start_plan_tasks,
)


class TestDailyPlanConfig(unittest.TestCase):
    def _plan_task(self, items):
        task = object.__new__(DailyPlanTask)
        task.config = {DailyPlanTask.CONF_ITEMS: items}
        return task

    def test_normalize_appends_missing_items_and_keeps_defaults(self):
        task = self._plan_task([{"id": "daily_claim", "enabled": False}])

        items = task.normalize_items()

        self.assertEqual(items[0], {"id": "daily_claim", "enabled": False})
        self.assertEqual(len(items), len(task.entries_by_id()))
        self.assertIn({"id": "daily_anomaly", "enabled": True}, items)

    def test_normalize_keeps_first_enabled_task_in_exclusive_group(self):
        task = self._plan_task(
            [
                {"id": "daily_anomaly_hunter", "enabled": True},
                {"id": "daily_anomaly", "enabled": True},
            ]
        )

        items = task.normalize_items()
        enabled = {item["id"] for item in items if item["enabled"]}

        self.assertIn("daily_anomaly_hunter", enabled)
        self.assertNotIn("daily_anomaly", enabled)

    def test_anomaly_plan_entries_use_the_original_task_classes(self):
        entries = DailyPlanTask.entries_by_id()

        self.assertIs(entries["daily_anomaly"].task_class, AnomalyTask)
        self.assertIs(entries["daily_anomaly_hunter"].task_class, AnomalyHunter)

    def test_daily_task_config_is_saved_in_the_plan_without_changing_normal_config(self):
        plan_task = self._plan_task([])
        plan_task.config[DailyPlanTask.CONF_TASK_CONFIGS] = {}
        normal_config = {"领取邮件": True}
        candidate = SimpleNamespace(
            config=normal_config,
            default_config={"领取邮件": True},
            config_description={},
            config_type={},
        )

        config = plan_task.daily_task_config("daily_claim", candidate)
        config["领取邮件"] = False

        self.assertEqual(normal_config, {"领取邮件": True})
        self.assertEqual(
            plan_task.config[DailyPlanTask.CONF_TASK_CONFIGS]["daily_claim"],
            {"领取邮件": False},
        )

    def test_daily_anomaly_schema_hides_normal_reward_count(self):
        plan_task = self._plan_task([])
        candidate = SimpleNamespace(
            default_config={BaseNTETask.CONF_CLAIM_REWARD_COUNT: 0},
            config_description={BaseNTETask.CONF_CLAIM_REWARD_COUNT: "normal"},
            config_type={},
        )

        schema = plan_task.daily_task_schema("daily_anomaly", candidate)

        self.assertEqual(next(iter(schema.default_config)), AnomalyTask.CONF_STAMINA_TARGET)
        self.assertIn(AnomalyTask.CONF_CYCLEB_TASK_MODE, schema.default_config)
        self.assertNotIn(BaseNTETask.CONF_CLAIM_REWARD_COUNT, schema.default_config)
        self.assertNotIn(BaseNTETask.CONF_CLAIM_REWARD_COUNT, schema.config_description)

    def test_daily_anomaly_config_normalizes_existing_field_order(self):
        plan_task = self._plan_task([])
        plan_task.config[DailyPlanTask.CONF_TASK_CONFIGS] = {
            "daily_anomaly": {
                AnomalyTask.CONF_TASK_TYPE: AnomalyTask.TASK_EXP_COIN,
                AnomalyTask.CONF_STAMINA_TARGET: 120,
            }
        }
        candidate = SimpleNamespace(
            default_config={BaseNTETask.CONF_CLAIM_REWARD_COUNT: 0},
            config_description={},
            config_type={},
        )

        plan_task.daily_task_config("daily_anomaly", candidate)

        saved = plan_task.config[DailyPlanTask.CONF_TASK_CONFIGS]["daily_anomaly"]
        self.assertEqual(next(iter(saved)), AnomalyTask.CONF_STAMINA_TARGET)
        self.assertEqual(saved[AnomalyTask.CONF_STAMINA_TARGET], 120)

    def test_daily_anomaly_cycle_is_saved_to_the_plan_config(self):
        task = object.__new__(DailyPlanTask)
        task.config = {DailyPlanTask.CONF_TASK_CONFIGS: {}}
        task.task_status = {"success": [], "failed": [], "skipped": [], "pending": ["daily_anomaly"]}
        task.current_task_key = None
        task._active_plan_task = None
        task.sleep_check_interval = 1
        task.info_set = Mock()
        task.log_info = Mock()
        task.log_error = Mock()
        task.log_warning = Mock()
        task.screenshot = Mock()
        task.ensure_main = Mock()
        normal_config = {BaseNTETask.CONF_CLAIM_REWARD_COUNT: 3}
        observed = {}

        def shift_id(active_task):
            observed["config"] = active_task.config
            active_task.config[AnomalyTask.CONF_CYCLEB_TASK_MODE] = AnomalyTask.CYCLE_SUB_TASK

        child = SimpleNamespace(
            name="异象界域",
            enabled=False,
            running=False,
            sleep_check_interval=1,
            config=normal_config,
            default_config={BaseNTETask.CONF_CLAIM_REWARD_COUNT: 0},
            config_description={BaseNTETask.CONF_CLAIM_REWARD_COUNT: "normal"},
            config_type={},
            do_run=Mock(return_value=True),
            shift_id=shift_id,
        )
        task.task_for_id = Mock(return_value=child)

        task._execute_plan_item({"id": "daily_anomaly", "enabled": True})

        self.assertIs(child.config, normal_config)
        self.assertIsNot(observed["config"], normal_config)
        self.assertIn(
            AnomalyTask.CONF_CYCLEB_TASK_MODE,
            task.config[DailyPlanTask.CONF_TASK_CONFIGS]["daily_anomaly"],
        )
        self.assertNotIn(
            BaseNTETask.CONF_CLAIM_REWARD_COUNT,
            task.config[DailyPlanTask.CONF_TASK_CONFIGS]["daily_anomaly"],
        )

    def test_selected_tasks_follow_persisted_order(self):
        first = Mock(enabled=False, running=False)
        second = Mock(enabled=False, running=False)
        task = self._plan_task(
            [
                {"id": "daily_claim", "enabled": True},
                {"id": "coffee", "enabled": True},
            ]
        )
        task.task_for_id = Mock(side_effect=[first, second, *[Mock() for _ in range(8)]])

        selected = selected_plan_tasks(task)

        self.assertEqual(selected[:2], [first, second])

    def test_selected_tasks_skip_tasks_unavailable_in_the_current_language(self):
        task = self._plan_task(
            [
                {"id": entry.task_id, "enabled": entry.task_id == "coffee"}
                for entry in DailyPlanTask.entries_by_id().values()
            ]
        )
        task.task_for_id = Mock(return_value=None)

        self.assertEqual(selected_plan_tasks(task), [])

    def test_full_selection_accepts_one_choice_per_exclusive_group(self):
        entries = DailyPlanTask.entries_by_id()
        items = [
            {
                "id": entry.task_id,
                "enabled": entry.exclusive_group is None or entry.task_id == "daily_anomaly",
            }
            for entry in entries.values()
        ]

        self.assertTrue(selection_is_complete(items, entries))

        for item in items:
            if item["id"] == "daily_anomaly":
                item["enabled"] = False

        self.assertFalse(selection_is_complete(items, entries))

    def test_enabling_an_exclusive_item_disables_its_peer(self):
        task = self._plan_task(
            [
                {"id": "daily_anomaly", "enabled": True},
                {"id": "daily_anomaly_hunter", "enabled": False},
            ]
        )

        items = task.set_item_enabled("daily_anomaly_hunter", True)

        enabled = {item["id"] for item in items if item["enabled"]}
        self.assertIn("daily_anomaly_hunter", enabled)
        self.assertNotIn("daily_anomaly", enabled)

    def test_select_all_only_changes_tasks_available_in_the_current_language(self):
        task = self._plan_task(
            [
                {"id": "daily_claim", "enabled": False},
                {"id": "gift", "enabled": True},
            ]
        )
        task.task_for_id = Mock(side_effect=lambda task_id: None if task_id == "gift" else Mock())

        items = task.set_all_available_items_selected(False)

        self.assertFalse(next(item for item in items if item["id"] == "daily_claim")["enabled"])
        self.assertTrue(next(item for item in items if item["id"] == "gift")["enabled"])


class TestDailyPlanStart(unittest.TestCase):
    def test_starts_daily_plan_task_through_the_standard_controller(self):
        plan_task = Mock(enabled=False, running=False)
        controller = Mock()
        controller.do_start.return_value = True

        started = start_plan_tasks(controller, plan_task)

        self.assertTrue(started)
        controller.do_start.assert_called_once_with(plan_task)

    def test_daily_plan_do_run_executes_selected_tasks_in_order_and_records_results(self):
        task = object.__new__(DailyPlanTask)
        task.scene = Mock()
        task.normalize_items = Mock(
            return_value=[
                {"id": "daily_claim", "enabled": True},
                {"id": "coffee", "enabled": True},
                {"id": "gift", "enabled": False},
            ]
        )
        task.log_info = Mock()
        task.log_warning = Mock()
        task.log_error = Mock()
        task.screenshot = Mock()
        task.info_set = Mock()
        task.ensure_main = Mock()
        task.current_task_key = None
        task._active_plan_task = None
        task.sleep_check_interval = 1
        task.config = {DailyPlanTask.CONF_TASK_CONFIGS: {}}
        first = Mock(name="领取", enabled=False, running=False)
        second = Mock(name="一咖舍", enabled=False, running=False)
        for child in (first, second):
            child.sleep_check_interval = 1
            child.config = {}
            child.default_config = {}
            child.config_description = {}
            child.config_type = {}
        first.do_run.return_value = True
        second.do_run.return_value = False
        task.task_for_id = Mock(
            side_effect=lambda task_id: {"daily_claim": first, "coffee": second}.get(task_id)
        )

        result = task.do_run()

        self.assertFalse(result)
        self.assertEqual(task.task_status["success"], ["daily_claim"])
        self.assertEqual(task.task_status["failed"], ["coffee"])
        self.assertEqual(task.task_status["skipped"], ["gift"])
        self.assertEqual(task.ensure_main.call_count, 3)
        first.do_run.assert_called_once_with()
        second.do_run.assert_called_once_with()

    def test_active_task_context_delegates_sleep_checks(self):
        task = object.__new__(DailyPlanTask)
        task._active_plan_task = None
        task.sleep_check_interval = 1
        task.config = {DailyPlanTask.CONF_TASK_CONFIGS: {}}
        normal_config = {"normal": True}
        child = SimpleNamespace(
            sleep_check_interval=0.2,
            sleep_check=Mock(),
            config=normal_config,
            default_config={"daily": True},
            config_description={},
            config_type={},
        )

        with task._active_task_context("daily_claim", child):
            self.assertIs(task._active_plan_task, child)
            self.assertEqual(task.sleep_check_interval, 0.2)
            self.assertIsNot(child.config, normal_config)
            task.sleep_check()

        child.sleep_check.assert_called_once_with()
        self.assertIsNone(task._active_plan_task)
        self.assertEqual(task.sleep_check_interval, 1)
        self.assertIs(child.config, normal_config)

    def test_daily_plan_do_run_skips_already_active_tasks(self):
        task = object.__new__(DailyPlanTask)
        task.scene = Mock()
        task.normalize_items = Mock(return_value=[{"id": "daily_claim", "enabled": True}])
        task.log_info = Mock()
        task.log_warning = Mock()
        active = Mock(enabled=True, running=False)
        task.task_for_id = Mock(return_value=active)

        result = task.do_run()

        self.assertFalse(result)
        task.task_for_id.assert_called_once_with("daily_claim")

    def test_active_task_detection(self):
        self.assertTrue(plan_has_active_tasks([SimpleNamespace(enabled=True, running=False)]))
        self.assertTrue(plan_has_active_tasks([SimpleNamespace(enabled=False, running=True)]))
        self.assertFalse(plan_has_active_tasks([SimpleNamespace(enabled=False, running=False)]))
