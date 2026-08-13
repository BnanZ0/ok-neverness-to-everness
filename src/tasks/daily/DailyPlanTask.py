from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass

from ok import TaskDisabledException
from qfluentwidgets import FluentIcon

from src.tasks.AnomalyHunter import AnomalyHunter
from src.tasks.AnomalyTask import AnomalyTask
from src.tasks.BaseNTETask import BaseNTETask
from src.tasks.daily.CinemaDateTask import CinemaDateTask
from src.tasks.daily.CoffeeTask import CoffeeTask
from src.tasks.daily.DailyClaimTask import DailyClaimTask
from src.tasks.daily.FountainTask import FountainTask
from src.tasks.daily.FurnitureTask import FurnitureTask
from src.tasks.daily.GiftTask import GiftTask
from src.tasks.NTEOneTimeTask import NTEOneTimeTask


@dataclass(frozen=True)
class DailyPlanEntry:
    task_id: str
    task_class: type
    enabled_by_default: bool = False
    exclusive_group: str | None = None
    daily_config: bool = False


DAILY_PLAN_ENTRIES = (
    DailyPlanEntry("daily_anomaly", AnomalyTask, True, "daily_anomaly", True),
    DailyPlanEntry("daily_anomaly_hunter", AnomalyHunter, False, "daily_anomaly", True),
    DailyPlanEntry("coffee", CoffeeTask),
    DailyPlanEntry("daily_claim", DailyClaimTask, True),
    DailyPlanEntry("cinema_date", CinemaDateTask),
    DailyPlanEntry("fountain", FountainTask),
    DailyPlanEntry("furniture", FurnitureTask),
    DailyPlanEntry("gift", GiftTask),
)


def selected_plan_tasks(plan_task):
    tasks = []
    for item in plan_task.normalize_items():
        if not item["enabled"]:
            continue
        if task := plan_task.task_for_id(item["id"]):
            tasks.append(task)
    return tasks


def plan_has_active_tasks(tasks):
    return any(task.enabled or task.running for task in tasks)


def start_plan_tasks(start_controller, plan_task):
    return start_controller.do_start(plan_task)


def selection_is_complete(items, entries):
    if not items:
        return False
    enabled_groups = set()
    for item in items:
        entry = entries[item["id"]]
        if entry.exclusive_group:
            if item["enabled"]:
                enabled_groups.add(entry.exclusive_group)
        elif not item["enabled"]:
            return False
    return all(
        entry.exclusive_group is None or entry.exclusive_group in enabled_groups
        for entry in entries.values()
    )


@dataclass
class _DailyTaskSchema:
    default_config: dict
    config_description: dict
    config_type: dict


class _DailyTaskConfig(dict):
    """A task config view persisted under the daily plan's config file."""

    def __init__(self, plan_task, task_id, task, default_config):
        self.plan_task = plan_task
        self.task_id = task_id
        self.task = task
        self.default = deepcopy(default_config)
        values = deepcopy(self.default)
        stored = plan_task.config.get(plan_task.CONF_TASK_CONFIGS, {})
        stored_values = stored.get(task_id) if isinstance(stored, dict) else None
        if isinstance(stored_values, dict):
            for key, value in stored_values.items():
                if key in values and isinstance(value, type(values[key])):
                    values[key] = deepcopy(value)
        super().__init__(values)
        if isinstance(stored_values, dict) and list(stored_values) != list(self):
            self.save_file()

    def get_default(self, key):
        return self.default.get(key)

    def has_user_config(self):
        return any(not key.startswith("_") for key in self)

    def __setitem__(self, key, value):
        if self.get(key) == value:
            return
        super().__setitem__(key, value)
        self.save_file()

    def update(self, *args, **kwargs):
        values = dict(*args, **kwargs)
        if all(self.get(key) == value for key, value in values.items()):
            return
        super().update(values)
        self.save_file()

    def reset_to_default(self):
        if dict(self) == self.default:
            return
        super().clear()
        super().update(deepcopy(self.default))
        self.save_file()

    def save_file(self):
        task_configs = self.plan_task.config.get(self.plan_task.CONF_TASK_CONFIGS, {})
        task_configs = deepcopy(task_configs) if isinstance(task_configs, dict) else {}
        task_configs[self.task_id] = deepcopy(dict(self))
        self.plan_task.config[self.plan_task.CONF_TASK_CONFIGS] = task_configs


class DailyPlanTask(NTEOneTimeTask, BaseNTETask):
    CONF_ITEMS = "计划任务"
    CONF_TASK_CONFIGS = "任务设置"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "日常任务"
        self.icon = FluentIcon.CALENDAR
        self.visible = False
        self.task_status = {"success": [], "failed": [], "skipped": [], "pending": []}
        self.current_task_key = None
        self._active_plan_task = None
        self.default_config[self.CONF_ITEMS] = self.default_items()
        self.default_config[self.CONF_TASK_CONFIGS] = {}
        self.config_description[self.CONF_ITEMS] = "日常任务中的任务顺序和启用状态"
        self.config_type[self.CONF_ITEMS] = {"hidden": True}
        self.config_type[self.CONF_TASK_CONFIGS] = {"hidden": True}

    @staticmethod
    def default_items():
        return [
            {"id": entry.task_id, "enabled": entry.enabled_by_default}
            for entry in DAILY_PLAN_ENTRIES
        ]

    @staticmethod
    def entries_by_id():
        return {entry.task_id: entry for entry in DAILY_PLAN_ENTRIES}

    def on_create(self):
        self.normalize_items()

    def normalize_items(self):
        entries = self.entries_by_id()
        raw_items = self.config.get(self.CONF_ITEMS, [])
        raw_item_list = raw_items if isinstance(raw_items, list) else []
        normalized = []
        seen = set()
        for item in raw_item_list:
            if not isinstance(item, dict):
                continue
            task_id = item.get("id")
            if task_id not in entries or task_id in seen:
                continue
            normalized.append({"id": task_id, "enabled": bool(item.get("enabled", False))})
            seen.add(task_id)
        for entry in DAILY_PLAN_ENTRIES:
            if entry.task_id not in seen:
                normalized.append({"id": entry.task_id, "enabled": entry.enabled_by_default})

        enabled_groups = set()
        for item in normalized:
            entry = entries[item["id"]]
            if item["enabled"] and entry.exclusive_group:
                if entry.exclusive_group in enabled_groups:
                    item["enabled"] = False
                else:
                    enabled_groups.add(entry.exclusive_group)
        if raw_items != normalized:
            self.config[self.CONF_ITEMS] = deepcopy(normalized)  # pyright: ignore[reportOptionalSubscript]
        return normalized

    def set_items(self, items):
        self.config[self.CONF_ITEMS] = deepcopy(items)  # pyright: ignore[reportOptionalSubscript]
        return self.normalize_items()

    def set_item_enabled(self, task_id, enabled):
        entries = self.entries_by_id()
        if task_id not in entries:
            return self.normalize_items()

        items = self.normalize_items()
        for item in items:
            if item["id"] == task_id:
                item["enabled"] = enabled
            elif enabled and entries[task_id].exclusive_group:
                other = entries[item["id"]]
                if other.exclusive_group == entries[task_id].exclusive_group:
                    item["enabled"] = False
        return self.set_items(items)

    def set_all_available_items_selected(self, selected):
        items = self.normalize_items()
        available_ids = {item["id"] for item in items if self.task_for_id(item["id"]) is not None}
        if not selected:
            return self.set_items(
                [
                    {
                        "id": item["id"],
                        "enabled": False if item["id"] in available_ids else item["enabled"],
                    }
                    for item in items
                ]
            )

        entries = self.entries_by_id()
        selected_groups = {
            entries[item["id"]].exclusive_group: item["id"]
            for item in items
            if item["id"] in available_ids
            and item["enabled"]
            and entries[item["id"]].exclusive_group
        }
        assigned_groups = set()
        for item in items:
            if item["id"] not in available_ids:
                continue
            group = entries[item["id"]].exclusive_group
            if not group:
                item["enabled"] = True
            elif group not in assigned_groups:
                item["enabled"] = selected_groups.get(group, item["id"]) == item["id"]
                assigned_groups.add(group)
            else:
                item["enabled"] = False
        return self.set_items(items)

    def set_available_item_order(self, ordered_task_ids):
        items = self.normalize_items()
        available_ids = {item["id"] for item in items if self.task_for_id(item["id"]) is not None}
        if set(ordered_task_ids) != available_ids or len(ordered_task_ids) != len(available_ids):
            return items

        items_by_id = {item["id"]: item for item in items}
        hidden_by_position = [[] for _ in range(len(ordered_task_ids) + 1)]
        visible_position = 0
        for item in items:
            if item["id"] in available_ids:
                visible_position += 1
            else:
                hidden_by_position[visible_position].append(item)

        reordered = []
        for index, task_id in enumerate(ordered_task_ids):
            reordered.extend(hidden_by_position[index])
            reordered.append(items_by_id[task_id])
        reordered.extend(hidden_by_position[-1])
        return self.set_items(reordered)

    def reset_items(self):
        return self.set_items(self.default_items())

    def task_for_id(self, task_id):
        return self.get_task_by_class(self.entries_by_id()[task_id].task_class)

    def daily_task_schema(self, task_id, task):
        entry = self.entries_by_id()[task_id]
        setup_config = getattr(entry.task_class, "setup_config", None)
        if callable(setup_config):
            schema = _DailyTaskSchema({}, {}, {})
            setup_config(schema, daily=entry.daily_config)
            return schema
        return _DailyTaskSchema(
            deepcopy(task.default_config),
            deepcopy(task.config_description),
            deepcopy(task.config_type),
        )

    def daily_task_config(self, task_id, task, schema=None):
        if schema is None:
            schema = self.daily_task_schema(task_id, task)
        return _DailyTaskConfig(self, task_id, task, schema.default_config)

    @contextmanager
    def daily_task_card_context(self, task_id, task):
        schema = self.daily_task_schema(task_id, task)
        original_config = task.config
        original_default = task.default_config
        original_description = task.config_description
        original_type = task.config_type
        task.config = self.daily_task_config(task_id, task, schema)
        task.default_config = schema.default_config
        task.config_description = schema.config_description
        task.config_type = schema.config_type
        try:
            yield task
        finally:
            task.config = original_config
            task.default_config = original_default
            task.config_description = original_description
            task.config_type = original_type

    def run(self):
        super().run()
        try:
            self.do_run()
        except TaskDisabledException:
            raise
        except Exception as error:
            self.screenshot("daily_plan_unexpected_exception")
            if self.current_task_key:
                self.info_set("当前失败任务", self.current_task_key)
            self._print_result()
            self.log_error("DailyPlanTask error", error)
            raise

    def do_run(self) -> bool:
        self.scene.set_logged_in(False)
        items = self.normalize_items()
        selected = [item for item in items if item["enabled"]]
        if not selected:
            self.log_info("日常任务没有已选任务，跳过执行")
            return True
        tasks = [self.task_for_id(item["id"]) for item in selected]
        if plan_has_active_tasks([task for task in tasks if task is not None]):
            self.log_warning("日常任务中的任务已在运行或排队，跳过重复入队")
            return False
        self._reset_task_status(items)
        self.log_info("开始执行日常任务")
        for item in items:
            self._execute_plan_item(item)
        self.ensure_main()
        self._print_result()
        self.log_info("结束执行日常任务", notify=True)
        return not self.task_status["failed"]

    def _execute_plan_item(self, item):
        task_id = item["id"]
        self.task_status["pending"].remove(task_id)
        task = self.task_for_id(task_id)
        if not item["enabled"]:
            self.task_status["skipped"].append(task_id)
            return
        if task is None:
            self.task_status["skipped"].append(task_id)
            self.log_info(f"任务不支持当前语言，跳过: {task_id}")
            return

        self.current_task_key = task_id
        self.info_set("当前任务", task.name)
        self.log_info(f"开始任务: {task.name}")
        self.ensure_main()
        try:
            with self._active_task_context(task_id, task):
                result = task.do_run()
                entry = self.entries_by_id()[task_id]
                if result and entry.daily_config and (shift_id := getattr(task, "shift_id", None)):
                    shift_id(task)
        except TaskDisabledException:
            raise
        except Exception as error:
            self.log_error(f"任务运行失败: {task.name}", error)
            result = False

        if not result:
            self.task_status["failed"].append(task_id)
            self.screenshot(f"daily_plan_fail_{task_id}")
            self.log_info(f"任务失败: {task.name}")
            return

        self.task_status["success"].append(task_id)
        self.current_task_key = None
        self.log_info(f"任务完成: {task.name}")

    def _reset_task_status(self, items):
        self.task_status = {
            "success": [],
            "failed": [],
            "skipped": [],
            "pending": [item["id"] for item in items],
        }

    def _print_result(self):
        self.info_set("success", f"{self.task_status['success']}")
        self.info_set("failed", f"{self.task_status['failed']}")
        self.info_set("skipped", f"{self.task_status['skipped']}")

    @contextmanager
    def _active_task_context(self, task_id, task):
        previous_task = self._active_plan_task
        previous_interval = self.sleep_check_interval
        original_config = task.config
        self._active_plan_task = task
        self.sleep_check_interval = task.sleep_check_interval
        task.config = self.daily_task_config(task_id, task)
        try:
            yield task
        finally:
            task.config = original_config
            self._active_plan_task = previous_task
            self.sleep_check_interval = previous_interval

    def sleep_check(self):
        if self._active_plan_task is not None:
            return self._active_plan_task.sleep_check()
        return super().sleep_check()
