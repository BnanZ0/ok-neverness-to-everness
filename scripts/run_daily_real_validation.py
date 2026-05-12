from __future__ import annotations

import argparse
import copy
import json
import os
import subprocess
import sys
import threading
import time
import traceback
from contextlib import AbstractContextManager
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.tasks.DailyCoffeeRuntime import DailyCoffeeRuntime
from src.tasks.DailyActivityFlow import DailyActivityFlow
from src.tasks.FlowResult import FlowResult
from src.tasks.DailyTaskItemRunner import DailyGiftDefaultRuntime, DailyTaskItemActionRunner


MODES = ("daily-full", "coffee-only", "daily-task-only", "gift-only")
TASK_KEYS = ("mail", "periodic", "activity", "coffee", "gift")
SUBPROCESS_TIMEOUT_SECONDS = 5
MODE_TASKS = {
    "daily-full": ("coffee", "gift", "activity", "mail", "periodic"),
    "daily-task-only": ("activity", "mail", "periodic"),
    "coffee-only": ("coffee",),
    "gift-only": ("gift",),
}


def _now_timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _iso_now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def parse_resolution(value: str | None) -> tuple[int, int] | None:
    if not value:
        return None
    normalized = value.lower().replace("*", "x")
    parts = normalized.split("x")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("resolution must use WIDTHxHEIGHT, for example 1920x1080")
    try:
        width = int(parts[0])
        height = int(parts[1])
    except ValueError as exc:
        raise argparse.ArgumentTypeError("resolution width and height must be integers") from exc
    if width <= 0 or height <= 0:
        raise argparse.ArgumentTypeError("resolution width and height must be positive")
    return width, height


def resolution_to_dict(resolution: tuple[int, int] | None) -> dict[str, int] | None:
    if resolution is None:
        return None
    return {"width": int(resolution[0]), "height": int(resolution[1])}


def _run_git(args: list[str], cwd: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            text=True,
            capture_output=True,
            check=False,
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return ""
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def get_git_info(cwd: Path = ROOT) -> dict[str, Any]:
    branch = _run_git(["branch", "--show-current"], cwd)
    head = _run_git(["rev-parse", "--short", "HEAD"], cwd)
    dirty = bool(_run_git(["status", "--short"], cwd))
    return {"git_branch": branch, "git_head": head, "dirty": dirty}


def htgame_process_exists() -> bool:
    if sys.platform != "win32":
        return False
    try:
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "$p=Get-Process HTGame -ErrorAction SilentlyContinue; if($p){'1'}",
            ],
            text=True,
            capture_output=True,
            check=False,
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return False
    return completed.returncode == 0 and completed.stdout.strip() == "1"


def make_task_summary() -> dict[str, Any]:
    return {
        "mail": {
            "attempted": False,
            "ok": False,
            "claimed": False,
            "skipped": False,
            "reason": "",
        },
        "periodic": {
            "attempted": False,
            "ok": False,
            "claimed": False,
            "skipped": False,
            "reason": "",
        },
        "activity": {
            "attempted": False,
            "ok": False,
            "cards_claimed": 0,
            "no_claimable_reward": False,
            "skipped": False,
            "reason": "",
            "mutation_performed": False,
            "mutation_verified": False,
            "action_failed": False,
            "skipped_reason": "",
            "failure_reason": "",
        },
        "coffee": {
            "attempted": False,
            "ok": False,
            "income_claimed": False,
            "supply_purchased": False,
            "product_optimized": False,
            "deselect_product": [],
            "select_product": [],
            "skipped": False,
            "reason": "",
        },
        "gift": {
            "attempted": False,
            "ok": False,
            "mutation_performed": False,
            "mutation_verified": False,
            "handler_completed": False,
            "task_completed": False,
            "sent_total": 0,
            "selected_character": "",
            "selected_item": "",
            "task_reward_claimed": False,
            "activity_rewards_claimed": 0,
            "claimable_rewards_remaining": None,
            "claimable_rewards_reason": "",
            "daily_task_state_reason": "",
            "skipped": False,
            "reason": "",
        },
    }


def make_empty_summary(
    mode: str,
    command: str,
    output_dir: Path,
    git_info: dict[str, Any],
) -> dict[str, Any]:
    return {
        "git_branch": git_info.get("git_branch", ""),
        "git_head": git_info.get("git_head", ""),
        "dirty": bool(git_info.get("dirty", False)),
        "command": command,
        "mode": mode,
        "started_at": _iso_now(),
        "finished_at": "",
        "ok": False,
        "window": {
            "width": 0,
            "height": 0,
            "title": "",
            "hwnd": "",
        },
        "tasks": make_task_summary(),
        "actions": [],
        "artifacts": [],
        "warnings": [],
        "errors": [],
        "artifact_dir": str(output_dir),
    }


def classify_exception(exc: BaseException) -> str:
    text = f"{type(exc).__name__}: {exc}"
    if "PostMessage" in text:
        return "postmessage_failed"
    if isinstance(exc, PermissionError) or "拒绝访问" in text or "Access is denied" in text:
        return "permission_denied"
    return "exception"


def object_to_jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [object_to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): object_to_jsonable(item) for key, item in value.items()}
    if is_dataclass(value):
        return object_to_jsonable(asdict(value))
    if hasattr(value, "to_dict"):
        try:
            return object_to_jsonable(value.to_dict())
        except Exception:
            pass
    payload = {}
    for key in ("identity", "name", "category", "price_value", "price_text"):
        if hasattr(value, key):
            payload[key] = object_to_jsonable(getattr(value, key))
    if payload:
        return payload
    return str(value)


def extract_window_info(session: Any) -> dict[str, Any]:
    window = getattr(session, "window", None)
    if isinstance(window, dict):
        info = {
            "width": int(window.get("width") or 0),
            "height": int(window.get("height") or 0),
            "title": str(window.get("title") or ""),
            "hwnd": str(window.get("hwnd") or ""),
        }
        for key in (
            "client_width",
            "client_height",
            "capture_width",
            "capture_height",
            "window_width",
            "window_height",
        ):
            if key in window:
                info[key] = int(window.get(key) or 0)
        return info
    return {
        "width": int(getattr(window, "width", 0) or 0),
        "height": int(getattr(window, "height", 0) or 0),
        "title": str(getattr(window, "title", "") or ""),
        "hwnd": str(getattr(window, "hwnd", "") or ""),
    }


class RealOKSession(AbstractContextManager):
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.ok_app = None
        self.task = None
        self.window = {"width": 0, "height": 0, "title": "", "hwnd": ""}

    def __enter__(self):
        import ok

        from src.config import config as base_config
        from src.scene.NTEScene import NTEScene
        from src.tasks.DailyTask import DailyTask

        try:
            NTEScene.ocr_warm_up = lambda self: None
        except Exception:
            pass

        config = copy.deepcopy(base_config)
        config["debug"] = True
        config["use_gui"] = False
        config["config_folder"] = str(self.output_dir / "configs")
        config["screenshots_folder"] = str(self.output_dir / "screenshots")
        config["trigger_tasks"] = []
        config["wait_until_before_delay"] = 0
        config["wait_until_check_delay"] = 0
        config["wait_until_settle_time"] = 0
        config["analytics"] = None
        Path(config["config_folder"]).mkdir(parents=True, exist_ok=True)
        Path(config["screenshots_folder"]).mkdir(parents=True, exist_ok=True)

        self.ok_app = ok.OK(config)
        # The validation runner calls known-safe task methods directly. Keep
        # frame access out of the paused executor path while no onetime task is
        # enabled through the task thread.
        self.ok_app.task_executor.debug_mode = True
        self.ok_app.app.start_controller.do_start()
        self.ok_app.task_executor.debug_mode = True
        self.ok_app.task_executor.paused = False
        self._wait_for_interaction()
        self.task = self.ok_app.task_executor.get_task_by_class(DailyTask)
        if self.task is None:
            raise RuntimeError("DailyTask not found in OK task executor")
        self._configure_task()
        self.window = self._read_window()
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.ok_app is None:
            return False
        try:
            self.ok_app.task_executor.stop()
        except Exception:
            pass
        try:
            self.ok_app.quit()
        except Exception:
            pass
        return False

    def _wait_for_interaction(self):
        deadline = time.time() + 30
        executor = self.ok_app.task_executor
        while time.time() < deadline:
            if getattr(executor, "interaction", None) is not None:
                return
            time.sleep(0.2)
        raise RuntimeError("interaction_not_ready")

    def _configure_task(self):
        config = getattr(self.task, "config", None)
        if config is None:
            self.task.config = {}
            config = self.task.config
        config["coffee_supply_duration"] = "24小时"
        config["coffee_product_scrolls"] = DailyCoffeeRuntime.COFFEE_PRODUCT_DEFAULT_SCAN_SCROLLS
        config["coffee_product_target_slots"] = 5
        config["coffee_dry_run"] = False
        config["gift_target_characters"] = ""
        config["claim_partial_milestones"] = False

    def _read_window(self) -> dict[str, Any]:
        capture = getattr(getattr(self.ok_app, "device_manager", None), "capture_method", None)
        hwnd_window = getattr(capture, "hwnd_window", None)
        client_width = getattr(hwnd_window, "width", 0) or 0
        client_height = getattr(hwnd_window, "height", 0) or 0
        capture_width = getattr(capture, "width", 0) or 0
        capture_height = getattr(capture, "height", 0) or 0
        window_width = getattr(hwnd_window, "window_width", 0) or 0
        window_height = getattr(hwnd_window, "window_height", 0) or 0
        width = (
            client_width
            or capture_width
            or getattr(getattr(self.ok_app, "task_executor", None), "width", 0)
        )
        height = (
            client_height
            or capture_height
            or getattr(getattr(self.ok_app, "task_executor", None), "height", 0)
        )
        return {
            "width": int(width or 0),
            "height": int(height or 0),
            "client_width": int(client_width or 0),
            "client_height": int(client_height or 0),
            "capture_width": int(capture_width or 0),
            "capture_height": int(capture_height or 0),
            "window_width": int(window_width or 0),
            "window_height": int(window_height or 0),
            "title": str(
                getattr(hwnd_window, "hwnd_title", "")
                or getattr(hwnd_window, "title", "")
                or ""
            ),
            "hwnd": str(getattr(hwnd_window, "hwnd", "") or ""),
        }


class DailyRealValidationRunner:
    def __init__(
        self,
        mode: str,
        *,
        command: str | None = None,
        working_root: Path | str = ROOT / "working",
        session_factory: Callable[[Path], AbstractContextManager] | None = None,
        process_checker: Callable[[], bool] = htgame_process_exists,
        git_info_provider: Callable[[], dict[str, Any]] | None = None,
        timestamp_provider: Callable[[], str] = _now_timestamp,
        coffee_runtime_factory: Callable[[Any], Any] | None = None,
        gift_task_item_runner_factory: Callable[[Any], Any] | None = None,
        gift_runtime_factory: Callable[[Any], Any] | None = None,
        expected_resolution: tuple[int, int] | None = None,
    ):
        if mode not in MODES:
            raise ValueError(f"unsupported mode: {mode}")
        self.mode = mode
        self.command = command or " ".join(sys.argv)
        self.working_root = Path(working_root)
        self.session_factory = session_factory or (lambda output_dir: RealOKSession(output_dir))
        self.process_checker = process_checker
        self.git_info_provider = git_info_provider or (lambda: get_git_info(ROOT))
        self.timestamp_provider = timestamp_provider
        self.coffee_runtime_factory = coffee_runtime_factory
        self.gift_task_item_runner_factory = gift_task_item_runner_factory
        self.gift_runtime_factory = gift_runtime_factory
        self.expected_resolution = expected_resolution
        self.output_dir: Path | None = None
        self.summary: dict[str, Any] | None = None
        self._current_task: Any | None = None

    def run(self) -> dict[str, Any]:
        self.output_dir = self.working_root / f"daily_real_validation_{self.timestamp_provider()}"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.summary = make_empty_summary(
            self.mode,
            self.command,
            self.output_dir,
            self.git_info_provider(),
        )
        if self.expected_resolution is not None:
            self.summary["expected_resolution"] = resolution_to_dict(self.expected_resolution)
        self._artifact("summary_dir", self.output_dir)

        if not self.process_checker():
            self._mark_window_not_found()
            return self._finish()

        try:
            with self.session_factory(self.output_dir) as session:
                self.summary["window"] = extract_window_info(session)
                if not self.summary["window"]["width"] or not self.summary["window"]["height"]:
                    self._error("window_not_found")
                    self._skip_required_tasks("window_not_found")
                    return self._finish()
                if not self._window_matches_expected_resolution(self.summary["window"]):
                    expected = resolution_to_dict(self.expected_resolution)
                    actual = {
                        "width": self.summary["window"]["width"],
                        "height": self.summary["window"]["height"],
                    }
                    self._error(f"resolution_mismatch: expected {expected}, got {actual}")
                    self._skip_required_tasks("resolution_mismatch")
                    return self._finish()
                self._current_task = session.task
                try:
                    self._run_mode(session.task)
                finally:
                    self._current_task = None
        except Exception as exc:
            code = classify_exception(exc)
            self._error(code, exc)
            self._skip_unattempted_tasks(code)

        return self._finish()

    def _window_matches_expected_resolution(self, window: dict[str, Any]) -> bool:
        if self.expected_resolution is None:
            return True
        return (
            int(window.get("width") or 0),
            int(window.get("height") or 0),
        ) == self.expected_resolution

    def _run_mode(self, task: Any):
        if self.mode == "daily-full":
            self._enable_daily_full_mutation_requirements(task)
            self._run_coffee(task)
            self._run_gift_real_send(task, require_send=True)
            self._run_activity(task)
            self._run_mail(task)
            self._run_periodic(task)
            return
        if self.mode == "daily-task-only":
            self._run_daily_task_safe_path(task)
            return
        if self.mode == "coffee-only":
            self._run_coffee(task)
            return
        if self.mode == "gift-only":
            self._run_gift_real_send(task, require_send=True)

    @staticmethod
    def _enable_daily_full_mutation_requirements(task: Any):
        config = getattr(task, "config", None)
        if config is None:
            task.config = {}
            config = task.config
        config["coffee_force_supply_purchase"] = True

    def _run_daily_task_safe_path(self, task: Any):
        self._run_activity(task)
        self._run_mail(task)
        self._run_periodic(task)

    def _run_mail(self, task: Any):
        block = self.summary["tasks"]["mail"]
        block["attempted"] = True
        result, error = self._run_action(
            "mail",
            "DailyTask.claim_mail",
            lambda: self._call_after_world_ready(task, task.claim_mail),
        )
        if error:
            block.update({"ok": False, "reason": error})
            return
        flow = self._flow_result(task, result, "领取邮件", falsey_is_failed=True)
        if flow.skipped:
            block.update({"ok": True, "skipped": True, "reason": flow.reason})
            return
        if flow.failed:
            block.update({"ok": False, "reason": flow.reason or "claim_mail_returned_false"})
            return
        claimed = flow.mutated if isinstance(result, FlowResult) else bool(result)
        block.update({"ok": True, "claimed": bool(claimed)})

    def _run_periodic(self, task: Any):
        block = self.summary["tasks"]["periodic"]
        block["attempted"] = True
        result, error = self._run_action(
            "periodic",
            "DailyTask.claim_battle_pass_rewards",
            lambda: self._call_after_world_ready(task, task.claim_battle_pass_rewards),
        )
        if error:
            block.update({"ok": False, "reason": error})
            return
        flow = self._flow_result(task, result, "领取环期任务奖励", falsey_is_failed=True)
        if isinstance(result, dict):
            block.update(
                {
                    "ok": flow.ok,
                    "claimed": bool(result.get("claimed")),
                    "skipped": flow.skipped,
                    "reason": flow.reason,
                    "details": object_to_jsonable(result),
                }
            )
            if not block["ok"] and not block["reason"]:
                block["reason"] = "claim_battle_pass_rewards_returned_false"
            return
        if isinstance(result, FlowResult):
            block.update(
                {
                    "ok": flow.ok,
                    "claimed": bool(flow.mutated),
                    "skipped": flow.skipped,
                    "reason": flow.reason,
                    "details": object_to_jsonable(flow),
                }
            )
            if not block["ok"] and not block["reason"]:
                block["reason"] = "claim_battle_pass_rewards_returned_false"
            return
        if flow.skipped:
            block.update({"ok": True, "claimed": False, "skipped": True, "reason": flow.reason})
            return
        if flow.failed:
            block.update({"ok": False, "claimed": False, "reason": flow.reason or "claim_battle_pass_rewards_returned_false"})
            return
        block.update({"ok": True, "claimed": bool(result)})

    def _run_activity(self, task: Any):
        block = self.summary["tasks"]["activity"]
        block["attempted"] = True

        def activity_flow():
            self._ensure_world_ready(task)
            complete_result = task.complete_daily_activities()
            reward_result = task.claim_activity_rewards()
            complete_flow = self._flow_result(task, complete_result, "完成每日活跃度")
            reward_flow = self._flow_result(task, reward_result, "领取活跃度奖励")
            details_by_key = getattr(task, "_last_daily_activity_flow_details", {}) or {}
            complete_details = details_by_key.get("完成每日活跃度", {})
            reward_details = details_by_key.get("领取活跃度奖励", {})
            complete_payload = complete_details.get("details", {}) if isinstance(complete_details, dict) else {}
            reward_payload = reward_details.get("details", {}) if isinstance(reward_details, dict) else {}
            analysis = getattr(task, "_last_daily_activity_analysis", None)
            cards_claimed = int(getattr(task, "_last_daily_activity_cards_claimed", 0) or 0)
            handler_completed = bool(getattr(task, "_last_daily_activity_handlers_completed", False))
            snapshot = {}
            if isinstance(complete_payload, dict):
                snapshot = complete_payload.get("snapshot", {})
            if not isinstance(snapshot, dict):
                snapshot = {}
            if not cards_claimed and isinstance(complete_payload, dict):
                cards_claimed = int(complete_payload.get("cards_claimed") or 0)
            if not cards_claimed:
                cards_claimed = int(snapshot.get("cards_claimed") or 0)
            if not handler_completed and isinstance(complete_payload, dict):
                handler_completed = bool(complete_payload.get("handler_completed"))
            if not handler_completed:
                handler_completed = bool(snapshot.get("handler_completed"))
            task_completed = bool(
                cards_claimed
                or (complete_payload.get("task_completed") if isinstance(complete_payload, dict) else False)
                or snapshot.get("task_completed")
            )
            milestone_claimed = reward_result is True or (
                isinstance(reward_result, FlowResult) and reward_result.done and reward_result.mutated
            )
            no_claimable = (
                (
                    reward_flow.skipped
                    or bool(getattr(analysis, "no_claimable_reward", False))
                )
                and cards_claimed == 0
                and not milestone_claimed
                and not task_completed
                and not handler_completed
            )
            reason = (
                self._skip_reason(task, "领取活跃度奖励")
                or self._skip_reason(task, "完成每日活跃度")
                or getattr(analysis, "reason", "")
                or getattr(task, "_last_activity_reward_skip_reason", "")
                or ""
            )
            ok = complete_flow.ok and reward_flow.ok
            mutation_performed = bool(
                complete_flow.mutated
                or reward_flow.mutated
                or complete_flow.details.get("mutation_performed")
                or reward_flow.details.get("mutation_performed")
                or complete_payload.get("mutation_performed")
                or reward_payload.get("mutation_performed")
            )
            mutation_verified = bool(
                mutation_performed
                and ok
                and (
                    complete_flow.details.get("mutation_verified")
                    or reward_flow.details.get("mutation_verified")
                    or complete_payload.get("mutation_verified")
                    or reward_payload.get("mutation_verified")
                    or cards_claimed
                    or milestone_claimed
                    or task_completed
                )
            )
            failure_reason = str(
                complete_flow.details.get("failure_reason")
                or reward_flow.details.get("failure_reason")
                or complete_payload.get("failure_reason")
                or reward_payload.get("failure_reason")
                or (reason if not ok else "")
                or ""
            )
            skipped_reason = str(reason if no_claimable else "")
            return {
                "ok": ok,
                "handler_completed": handler_completed,
                "task_completed": task_completed,
                "cards_claimed": int(cards_claimed or 0),
                "milestone_claimed": milestone_claimed,
                "no_claimable_reward": no_claimable,
                "skipped": no_claimable,
                "reason": reason if (no_claimable or not ok) else "",
                "mutation_performed": mutation_performed,
                "mutation_verified": mutation_verified,
                "action_failed": bool(failure_reason),
                "skipped_reason": skipped_reason,
                "failure_reason": failure_reason,
                "analysis": object_to_jsonable(analysis),
                "details": {
                    "complete": object_to_jsonable(complete_details),
                    "reward": object_to_jsonable(reward_details),
                },
            }

        result, error = self._run_action("activity", "DailyTask.safe_activity_rewards", activity_flow)
        if error:
            block.update({"ok": False, "reason": error})
            return
        block["ok"] = bool(result.get("ok"))
        block["handler_completed"] = bool(result.get("handler_completed"))
        block["task_completed"] = bool(result.get("task_completed"))
        block["cards_claimed"] = int(result.get("cards_claimed") or 0)
        block["no_claimable_reward"] = bool(result.get("no_claimable_reward"))
        block["skipped"] = bool(result.get("skipped"))
        block["reason"] = str(result.get("reason") or "")
        block["mutation_performed"] = bool(result.get("mutation_performed"))
        block["mutation_verified"] = bool(result.get("mutation_verified"))
        block["action_failed"] = bool(result.get("action_failed"))
        block["skipped_reason"] = str(result.get("skipped_reason") or "")
        block["failure_reason"] = str(result.get("failure_reason") or "")
        if not block["ok"]:
            interaction_error = self._last_interaction_error()
            if interaction_error:
                block["reason"] = "postmessage_failed"
                block["failure_reason"] = "postmessage_failed"
                self._error(f"postmessage_failed: {interaction_error}")
        if result.get("analysis") is not None:
            block["analysis"] = result["analysis"]
        if result.get("details") is not None:
            block["details"] = object_to_jsonable(result["details"])

    def _run_coffee(self, task: Any):
        block = self.summary["tasks"]["coffee"]
        block["attempted"] = True

        def coffee_flow():
            factory = self.coffee_runtime_factory
            if factory is None:
                from src.tasks.DailyCoffeeRuntime import DailyCoffeeRuntime

                factory = DailyCoffeeRuntime
            runtime = factory(task)
            return runtime.run()

        result, error = self._run_action("coffee", "DailyCoffeeRuntime.run", coffee_flow)
        if error:
            block.update({"ok": False, "reason": error})
            return

        flow = FlowResult.from_legacy(result, falsey_is_failed=True)
        actions = list(getattr(result, "selected_actions", []) or [])
        selected_options = list(getattr(result, "selected_options", []) or [])
        block["ok"] = flow.ok
        block["income_claimed"] = bool(getattr(result, "income_claimed", False))
        block["supply_purchased"] = bool(getattr(result, "real_purchase_performed", False))
        block["product_optimized"] = bool(selected_options)
        block["deselect_product"] = [item for item in actions if item.startswith("deselect_product:")]
        block["select_product"] = [item for item in actions if item.startswith("select_product:")]
        block["products_selected"] = object_to_jsonable(selected_options)
        block["actions"] = actions
        skip_reason = flow.reason or str(getattr(result, "skip_reason", "") or "")
        reasons = [skip_reason] if skip_reason else []
        block["skipped"] = flow.skipped or bool(skip_reason and block["ok"])
        if block["ok"] and not block["product_optimized"] and "product_switch_not_needed" in actions:
            reasons.append("product_switch_not_needed")
        block["reason"] = "; ".join(reasons)
        if not block["ok"] and not block["reason"]:
            block["reason"] = "coffee_runtime_failed"
        if not block["ok"]:
            interaction_error = self._last_interaction_error()
            if interaction_error:
                block["reason"] = "postmessage_failed"
                self._error(f"postmessage_failed: {interaction_error}")
        for action in actions:
            mutation_performed = self._coffee_action_is_mutation(action, block)
            self._append_action(
                name="coffee_action",
                target=action,
                result="ok",
                mutation_performed=mutation_performed,
                mutation_verified=self._coffee_action_is_verified(action, block) if mutation_performed else False,
            )

    def _run_gift_real_send(self, task: Any, *, require_send: bool):
        block = self.summary["tasks"]["gift"]
        block["attempted"] = True

        result, error = self._run_action(
            "gift",
            "DailyTaskItemActionRunner.gift_only",
            lambda: self._gift_task_item_flow(task, require_send=require_send),
        )
        if error:
            block.update({"ok": False, "reason": error})
            return
        self._apply_gift_result(block, result, require_send=require_send)

    def _gift_task_item_flow(self, task: Any, *, require_send: bool) -> dict[str, Any]:
        self._ensure_world_ready(task)
        flow = DailyActivityFlow.from_task(task)
        factory = self.gift_task_item_runner_factory
        if factory is None:
            runner = DailyTaskItemActionRunner(
                flow,
                dry_run=False,
                max_actions=1,
                gift_only=True,
            )
        else:
            runner = factory(flow)
        result = dict(runner.run() or {})

        if require_send and not self._gift_result_has_verified_real_send(result):
            direct_result = self._run_direct_gift_real_send(flow, previous_result=result)
            return direct_result
        return result

    def _run_direct_gift_real_send(self, flow: DailyActivityFlow, *, previous_result: dict[str, Any]) -> dict[str, Any]:
        factory = self.gift_runtime_factory or (lambda current_flow: DailyGiftDefaultRuntime(current_flow))
        runtime = factory(flow)
        previous_gift = previous_result.get("gift") if isinstance(previous_result, dict) else {}
        previous_gift = previous_gift if isinstance(previous_gift, dict) else {}

        entry_result = runtime.enter_from_phone_menu()
        if not entry_result.get("ok"):
            return self._direct_gift_result(
                previous_result=previous_result,
                entry_result=entry_result,
                send_result={},
                reason=str(entry_result.get("reason") or "gift_phone_menu_entry_not_found"),
            )

        try:
            send_result_obj = runtime.send_default_gift(direct_verify=True)
        except TypeError:
            send_result_obj = runtime.send_default_gift()
        send_result = object_to_jsonable(send_result_obj)
        if not isinstance(send_result, dict):
            send_result = {}

        reason = str(send_result.get("reason") or "")
        if not send_result.get("mutation_verified"):
            reason = reason or "gift_direct_send_not_verified"
        return self._direct_gift_result(
            previous_result=previous_result,
            entry_result=entry_result,
            send_result=send_result,
            reason=reason,
            task_reward_claimed=bool(previous_gift.get("task_reward_claimed", False)),
            activity_rewards_claimed=int(previous_gift.get("activity_rewards_claimed", 0) or 0),
            claimable_rewards_remaining=previous_gift.get("claimable_rewards_remaining"),
            claimable_rewards_reason=str(previous_gift.get("claimable_rewards_reason", "") or ""),
        )

    def _direct_gift_result(
        self,
        *,
        previous_result: dict[str, Any],
        entry_result: dict[str, Any],
        send_result: dict[str, Any],
        reason: str,
        task_reward_claimed: bool = False,
        activity_rewards_claimed: int = 0,
        claimable_rewards_remaining: Any = None,
        claimable_rewards_reason: str = "",
    ) -> dict[str, Any]:
        previous_gift = previous_result.get("gift") if isinstance(previous_result, dict) else {}
        if not isinstance(previous_gift, dict):
            previous_gift = {}
        mutation_performed = bool(send_result.get("mutation_performed"))
        mutation_verified = bool(send_result.get("mutation_verified"))
        sent_total = int(send_result.get("sent_total", 0) or 0)
        ok = bool(mutation_performed and mutation_verified and sent_total == 1)
        daily_state_reason = "daily_task_state_unavailable_because_already_consumed"
        actions = []
        actions.extend(object_to_jsonable(entry_result.get("actions", [])) or [])
        actions.extend(object_to_jsonable(send_result.get("actions", [])) or [])
        return {
            "ok": ok,
            "preflight": object_to_jsonable(previous_result.get("preflight", {})),
            "mutation_performed": mutation_performed,
            "mutation_verified": mutation_verified,
            "handler_completed": bool(entry_result.get("ok") or send_result.get("handler_completed")),
            "task_completed": bool(previous_gift.get("task_completed", False)),
            "items": object_to_jsonable(previous_result.get("items", [])),
            "actions": actions,
            "skipped": object_to_jsonable(previous_result.get("skipped", [])),
            "blockers": object_to_jsonable(previous_result.get("blockers", [])),
            "daily_task_state_reason": daily_state_reason,
            "task_item_result": object_to_jsonable(previous_result),
            "gift": {
                "detected": bool(entry_result.get("ok")),
                "mutation_performed": mutation_performed,
                "mutation_verified": mutation_verified,
                "selected_character": str(send_result.get("selected_character", "") or ""),
                "selected_item": str(send_result.get("selected_item", "") or ""),
                "sent_total": sent_total,
                "task_reward_claimed": task_reward_claimed,
                "activity_rewards_claimed": int(activity_rewards_claimed or 0),
                "claimable_rewards_remaining": claimable_rewards_remaining,
                "claimable_rewards_reason": claimable_rewards_reason,
                "handler_completed": bool(entry_result.get("ok") or send_result.get("handler_completed")),
                "task_completed": bool(previous_gift.get("task_completed", False)),
                "reason": reason or ("gift_real_send_verified" if ok else "gift_real_send_failed"),
                "daily_task_state_reason": daily_state_reason,
                "entry": object_to_jsonable(entry_result),
                "send": object_to_jsonable(send_result),
            },
        }

    @staticmethod
    def _gift_result_has_verified_real_send(result: dict[str, Any]) -> bool:
        gift = result.get("gift") if isinstance(result, dict) else {}
        if not isinstance(gift, dict):
            return False
        return bool(
            gift.get("mutation_performed")
            and gift.get("mutation_verified")
            and int(gift.get("sent_total", 0) or 0) == 1
            and str(gift.get("selected_item", "") or "")
        )

    def _apply_gift_result(self, block: dict[str, Any], result: dict[str, Any], *, require_send: bool):
        gift = result.get("gift") if isinstance(result, dict) else {}
        if not isinstance(gift, dict):
            gift = {}
        mutation_performed = bool(result.get("mutation_performed") or gift.get("mutation_performed"))
        mutation_verified = bool(result.get("mutation_verified") or gift.get("mutation_verified"))
        sent_total = int(gift.get("sent_total", 0) or 0)
        real_send_verified = bool(
            mutation_performed
            and mutation_verified
            and sent_total == 1
            and str(gift.get("selected_item", "") or "")
        )
        ok = bool(result.get("ok"))
        if require_send:
            ok = bool(ok and real_send_verified)
        block.update(
            {
                "ok": ok,
                "mutation_performed": mutation_performed,
                "mutation_verified": mutation_verified,
                "handler_completed": bool(result.get("handler_completed") or gift.get("handler_completed")),
                "task_completed": bool(result.get("task_completed") or gift.get("task_completed")),
                "sent_total": sent_total,
                "selected_character": str(gift.get("selected_character", "") or ""),
                "selected_item": str(gift.get("selected_item", "") or ""),
                "task_reward_claimed": bool(gift.get("task_reward_claimed", False)),
                "activity_rewards_claimed": int(gift.get("activity_rewards_claimed", 0) or 0),
                "claimable_rewards_remaining": gift.get("claimable_rewards_remaining"),
                "claimable_rewards_reason": str(gift.get("claimable_rewards_reason", "") or ""),
                "daily_task_state_reason": str(
                    gift.get("daily_task_state_reason")
                    or result.get("daily_task_state_reason")
                    or ""
                ),
                "skipped": False,
                "reason": str(gift.get("reason") or result.get("reason") or ""),
                "details": object_to_jsonable(result),
            }
        )
        if require_send and not real_send_verified and not block["reason"]:
            block["reason"] = "gift_real_send_not_verified"

    def _run_action(self, name: str, target: str, func: Callable[[], Any]) -> tuple[Any, str | None]:
        self.summary["current_action"] = name
        self._write_partial_summary()
        watchdog = self._start_action_watchdog(name)
        before = self._screenshot(f"{name}_before")
        try:
            result = func()
        except Exception as exc:
            watchdog.cancel()
            after = self._screenshot(f"{name}_after_error")
            code = self._classify_action_exception(exc)
            self._error(code, exc)
            self._append_action(
                name=name,
                target=target,
                before_screenshot=before,
                after_screenshot=after,
                result=f"{code}: {exc}",
                mutation_performed=False,
            )
            self._write_partial_summary()
            return None, code
        watchdog.cancel()
        after = self._screenshot(f"{name}_after")
        self._append_action(
            name=name,
            target=target,
            before_screenshot=before,
            after_screenshot=after,
            result=object_to_jsonable(result),
            mutation_performed=self._default_mutation_for(name, result),
            mutation_verified=self._default_mutation_verified_for(name, result),
        )
        self._write_partial_summary()
        return result, None

    def _start_action_watchdog(self, name: str) -> threading.Timer:
        seconds = {
            "mail": 90,
            "periodic": 90,
            "activity": 150,
            "coffee": 300,
        }.get(name, 60)

        def abort():
            code = f"{name}_timeout"
            self._error(code)
            block = self.summary["tasks"].get(name)
            if block is not None:
                block["attempted"] = True
                block["ok"] = False
                block["reason"] = code
            self.summary["finished_at"] = _iso_now()
            self.summary["ok"] = False
            self._write_partial_summary()
            os._exit(124)

        timer = threading.Timer(seconds, abort)
        timer.daemon = True
        timer.start()
        return timer

    def _classify_action_exception(self, exc: BaseException) -> str:
        interaction_error = self._last_interaction_error()
        if interaction_error:
            if "拒绝访问" in interaction_error or "Access is denied" in interaction_error:
                return "postmessage_failed"
            return "interaction_failed"
        return classify_exception(exc)

    def _last_interaction_error(self) -> str:
        task = getattr(self, "_current_task", None)
        executor = getattr(task, "_executor", None)
        interaction = getattr(executor, "interaction", None)
        return str(getattr(interaction, "last_post_error", "") or "")

    def _default_mutation_for(self, name: str, result: Any) -> bool:
        if isinstance(result, FlowResult):
            return result.mutated
        if isinstance(result, dict) and "mutation_performed" in result:
            return bool(result.get("mutation_performed"))
        if name == "gift":
            return False
        if name == "activity" and isinstance(result, dict):
            return bool(
                result.get("handler_completed")
                or result.get("task_completed")
                or result.get("cards_claimed")
                or result.get("milestone_claimed")
            )
        if name == "periodic" and isinstance(result, dict):
            return bool(result.get("claimed"))
        if name == "coffee":
            return bool(
                getattr(result, "income_claimed", False)
                or getattr(result, "real_purchase_performed", False)
                or getattr(result, "selected_options", None)
            )
        return bool(result)

    def _default_mutation_verified_for(self, name: str, result: Any) -> bool:
        if isinstance(result, dict) and "mutation_verified" in result:
            return bool(result.get("mutation_verified"))
        mutation_performed = self._default_mutation_for(name, result)
        if not mutation_performed:
            return False
        if isinstance(result, FlowResult):
            return bool(result.ok)
        if name == "activity" and isinstance(result, dict):
            return bool(result.get("ok"))
        if name == "periodic" and isinstance(result, dict):
            return bool(result.get("ok") and result.get("claimed"))
        if name == "coffee":
            return bool(getattr(result, "ok", False))
        return bool(result)

    def _flow_result(
        self,
        task: Any,
        result: Any,
        key: str = "",
        *,
        falsey_is_failed: bool = False,
    ) -> FlowResult:
        skipped_sentinel = getattr(task, "TASK_SKIPPED", None) if hasattr(task, "TASK_SKIPPED") else None
        return FlowResult.from_legacy(
            result,
            skipped_sentinel=skipped_sentinel,
            skip_reason=self._skip_reason(task, key) if key else "",
            falsey_is_failed=falsey_is_failed,
        )

    def _coffee_action_is_mutation(self, action: str, block: dict[str, Any]) -> bool:
        if action in {"claim_income", "buy_supply", "buy_supply_retry_after_no_prompt", "confirm_home_delivery"}:
            return True
        if action.startswith("deselect_product:"):
            return True
        if action.startswith("select_product:"):
            return bool(block.get("product_optimized"))
        return False

    def _coffee_action_is_verified(self, action: str, block: dict[str, Any]) -> bool:
        if action == "claim_income":
            return bool(block.get("income_claimed"))
        if action in {"buy_supply", "buy_supply_retry_after_no_prompt", "confirm_home_delivery"}:
            return bool(block.get("supply_purchased"))
        if action.startswith("select_product:"):
            return bool(block.get("product_optimized"))
        if action.startswith("deselect_product:"):
            return bool(block.get("ok") and block.get("product_optimized"))
        return False

    def _call_after_world_ready(self, task: Any, func: Callable[[], Any]) -> Any:
        self._ensure_world_ready(task)
        return func()

    def _ensure_world_ready(self, task: Any):
        if self._is_world_ready(task):
            return True
        if self._close_panels_before_world_check(task):
            return True
        ensure = getattr(task, "_ensure_daily_main", None)
        if callable(ensure):
            try:
                return ensure()
            except Exception:
                self._close_panels_before_world_check(task, attempts=2)
                if self._is_world_ready(task):
                    return True
                raise
        return self._is_world_ready(task)

    def _is_world_ready(self, task: Any) -> bool:
        checker = getattr(task, "in_team_and_world", None)
        if not callable(checker):
            return False
        try:
            return bool(checker())
        except Exception:
            return False

    def _close_panels_before_world_check(self, task: Any, *, attempts: int = 1):
        for _ in range(max(1, int(attempts or 1))):
            if self._is_world_ready(task):
                return True
            sender = getattr(task, "_send_foreground_key", None)
            if callable(sender):
                try:
                    sender("esc", after_sleep=1)
                except TypeError:
                    sender("esc")
                continue
            sender = getattr(task, "send_key", None)
            if callable(sender):
                try:
                    sender("esc", after_sleep=1)
                except TypeError:
                    sender("esc")
                continue
            back = getattr(task, "back", None)
            if callable(back):
                try:
                    back(after_sleep=1)
                except TypeError:
                    back()
        return self._is_world_ready(task)

    def _is_task_skipped(self, task: Any, result: Any) -> bool:
        if isinstance(result, FlowResult):
            return result.skipped
        return hasattr(task, "TASK_SKIPPED") and result is getattr(task, "TASK_SKIPPED")

    def _skip_reason(self, task: Any, key: str) -> str:
        return str(getattr(task, "task_skip_reasons", {}).get(key, "") or "")

    def _screenshot(self, stem: str) -> str | None:
        task = getattr(self, "_current_task", None)
        if task is None:
            return None
        executor = getattr(task, "_executor", None)
        frame = getattr(executor, "_frame", None)
        if frame is None:
            method = getattr(executor, "method", None)
            getter = getattr(method, "get_frame", None)
            if callable(getter):
                try:
                    frame = getter()
                except Exception as exc:
                    self.summary["warnings"].append(f"screenshot_frame_failed:{stem}:{exc}")
                    frame = None
        if frame is None:
            return None
        path = self.output_dir / f"{stem}.png"
        try:
            import cv2

            cv2.imwrite(str(path), frame)
            self._artifact(stem, path)
            return str(path)
        except Exception as exc:
            self.summary["warnings"].append(f"screenshot_failed:{stem}:{exc}")
            return None

    def _append_action(
        self,
        *,
        name: str,
        target: str,
        before_screenshot: str | None = None,
        after_screenshot: str | None = None,
        result: Any = None,
        mutation_performed: bool = False,
        mutation_verified: bool | None = None,
    ):
        if mutation_verified is None:
            mutation_verified = bool(mutation_performed)
        self.summary["actions"].append(
            {
                "name": name,
                "target": target,
                "before_screenshot": before_screenshot,
                "after_screenshot": after_screenshot,
                "result": object_to_jsonable(result),
                "mutation_performed": bool(mutation_performed),
                "mutation_verified": bool(mutation_verified),
            }
        )

    def _artifact(self, name: str, path: Path):
        self.summary["artifacts"].append({"name": name, "path": str(path)})

    def _error(self, code: str, exc: BaseException | None = None):
        if exc is None:
            message = code
        else:
            message = f"{code}: {exc}"
        self.summary["errors"].append(message)
        if exc is not None:
            trace_path = self.output_dir / f"{code}.traceback.txt"
            trace_path.write_text("".join(traceback.format_exception(exc)), encoding="utf-8")
            self._artifact(f"{code}_traceback", trace_path)

    def _mark_window_not_found(self):
        self._error("window_not_found")
        self.summary["window"] = {"width": 0, "height": 0, "title": "", "hwnd": ""}
        self._skip_required_tasks("window_not_found")

    def _skip_required_tasks(self, reason: str):
        for key in MODE_TASKS[self.mode]:
            block = self.summary["tasks"][key]
            block["attempted"] = False
            block["ok"] = False
            block["skipped"] = True
            block["reason"] = reason

    def _skip_unattempted_tasks(self, reason: str):
        for key in MODE_TASKS[self.mode]:
            block = self.summary["tasks"][key]
            if not block["attempted"]:
                block["skipped"] = True
                block["reason"] = reason

    def _finish(self) -> dict[str, Any]:
        self.summary.pop("current_action", None)
        self.summary["finished_at"] = _iso_now()
        self._apply_mode_completion_gates()
        self.summary["ok"] = self._overall_ok()
        summary_path = self.output_dir / "summary.json"
        summary_path.write_text(
            json.dumps(self.summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._artifact("summary_json", summary_path)
        summary_path.write_text(
            json.dumps(self.summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return self.summary

    def _write_partial_summary(self):
        if not self.output_dir or self.summary is None:
            return
        summary_path = self.output_dir / "summary.json"
        summary_path.write_text(
            json.dumps(self.summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _apply_mode_completion_gates(self):
        if self.mode != "daily-full":
            return
        failures: list[str] = []
        activity = self.summary["tasks"]["activity"]
        coffee = self.summary["tasks"]["coffee"]
        gift = self.summary["tasks"]["gift"]

        if activity.get("attempted") and activity.get("ok") and not self._daily_full_activity_complete(activity):
            self._record_daily_full_activity_deferred(activity)

        if (
            self._daily_activity_has_incomplete_task(activity, "任意消费1次方斯")
            and not coffee.get("supply_purchased")
        ):
            failures.append("daily_full_fangsi_consumption_not_verified")
            coffee.setdefault("completion_failures", []).append("daily_full_fangsi_consumption_not_verified")

        if not self._daily_full_gift_verified(gift):
            failures.append("daily_full_gift_real_send_not_verified")
            gift.setdefault("completion_failures", []).append("daily_full_gift_real_send_not_verified")

        for failure in failures:
            if failure not in self.summary["errors"]:
                self.summary["errors"].append(failure)

    def _record_daily_full_activity_deferred(self, activity: dict[str, Any]):
        warning = "daily_full_activity_not_complete_deferred"
        activity.setdefault("completion_warnings", []).append(warning)
        if warning not in self.summary["warnings"]:
            self.summary["warnings"].append(warning)

    @staticmethod
    def _daily_full_activity_complete(activity: dict[str, Any]) -> bool:
        if not activity.get("attempted") or not activity.get("ok"):
            return False
        if activity.get("task_completed"):
            return True
        analysis = activity.get("analysis")
        if not isinstance(analysis, dict):
            return False
        if analysis.get("activity_full") or analysis.get("all_daily_done"):
            return True
        page = analysis.get("page")
        if isinstance(page, dict):
            try:
                return int(page.get("activity_score", 0) or 0) >= 100
            except (TypeError, ValueError):
                return False
        return False

    @staticmethod
    def _daily_full_gift_verified(gift: dict[str, Any]) -> bool:
        return bool(
            gift.get("mutation_performed")
            and gift.get("mutation_verified")
            and int(gift.get("sent_total", 0) or 0) == 1
            and str(gift.get("selected_item", "") or "")
        )

    @classmethod
    def _daily_activity_has_incomplete_task(cls, activity: dict[str, Any], title_fragment: str) -> bool:
        for card in cls._daily_activity_task_cards(activity):
            title = str(card.get("title") or card.get("label") or card.get("card_key") or "")
            if title_fragment not in title:
                continue
            progress = str(card.get("progress_text") or card.get("text") or "")
            if cls._progress_is_incomplete(progress):
                return True
            state = str(card.get("state") or "")
            action = str(card.get("action") or card.get("button_text") or "")
            if state == "go" or action == "前往":
                return True
        return False

    @staticmethod
    def _progress_is_incomplete(progress: str) -> bool:
        if "/" not in progress:
            return False
        left, right = progress.split("/", 1)
        try:
            return int(left.strip()) < int(right.strip())
        except ValueError:
            return False

    @staticmethod
    def _daily_activity_task_cards(activity: dict[str, Any]) -> list[dict[str, Any]]:
        analysis = activity.get("analysis")
        if isinstance(analysis, dict):
            page = analysis.get("page")
            if isinstance(page, dict):
                cards = page.get("task_cards")
                if isinstance(cards, list):
                    return [card for card in cards if isinstance(card, dict)]
        return []

    def _overall_ok(self) -> bool:
        if self.summary["errors"]:
            return False
        for action in self.summary["actions"]:
            if action.get("mutation_performed") and not action.get("mutation_verified"):
                return False
        for key in MODE_TASKS[self.mode]:
            block = self.summary["tasks"][key]
            if not block.get("attempted"):
                return False
            if block.get("action_failed"):
                return False
            if block.get("mutation_performed") and not block.get("mutation_verified"):
                return False
            if self.mode == "gift-only" and key == "gift":
                if not (
                    block.get("mutation_performed")
                    and block.get("mutation_verified")
                    and int(block.get("sent_total", 0) or 0) == 1
                    and str(block.get("selected_item", "") or "")
                ):
                    return False
            if key == "activity" and block.get("no_claimable_reward"):
                continue
            if not block.get("ok"):
                return False
        return True


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run real-machine DailyTask validation and write summary.json.")
    parser.add_argument("--mode", choices=MODES, default="daily-full")
    parser.add_argument(
        "--expect-resolution",
        type=parse_resolution,
        default=None,
        help="Require the captured client resolution, for example 1920x1080. Does not resize the game window.",
    )
    parser.add_argument("--json", action="store_true", help="Print summary JSON to stdout.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    command = " ".join([Path(sys.executable).name, *sys.argv])
    runner = DailyRealValidationRunner(args.mode, command=command, expected_resolution=args.expect_resolution)
    summary = runner.run()
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"summary: {runner.output_dir / 'summary.json'}")
        print(f"ok: {summary['ok']}")
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
