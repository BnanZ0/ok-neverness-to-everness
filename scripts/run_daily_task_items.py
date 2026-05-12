import argparse
import json
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from run_daily_real_validation import (  # noqa: E402
    RealOKSession,
    classify_exception,
    extract_window_info,
    get_git_info,
    htgame_process_exists,
    object_to_jsonable,
    parse_resolution,
    resolution_to_dict,
)
from src.tasks.DailyActivityFlow import DailyActivityFlow  # noqa: E402
from src.tasks.DailyTaskItemRunner import DailyTaskItemActionRunner  # noqa: E402


MODES = ("dry-run", "real-run")


def _now_timestamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _iso_now():
    return datetime.now().isoformat(timespec="seconds")


class DailyTaskItemsValidationRunner:
    def __init__(
        self,
        mode: str,
        *,
        command: str | None = None,
        working_root: Path | str = ROOT / "working",
        session_factory: Callable[[Path], Any] | None = None,
        process_checker: Callable[[], bool] = htgame_process_exists,
        git_info_provider: Callable[[], dict[str, Any]] | None = None,
        timestamp_provider: Callable[[], str] = _now_timestamp,
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
        self.expected_resolution = expected_resolution
        self.output_dir: Path | None = None
        self.summary: dict[str, Any] | None = None
        self._current_task = None

    def run(self):
        self.output_dir = self.working_root / f"daily_task_items_{self.timestamp_provider()}"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.summary = self._empty_summary()
        if self.expected_resolution is not None:
            self.summary["expected_resolution"] = resolution_to_dict(self.expected_resolution)
        self._artifact("summary_dir", self.output_dir)

        if not self.process_checker():
            self._error("window_not_found")
            self.summary["window"] = {"width": 0, "height": 0, "title": "", "hwnd": ""}
            return self._finish()

        try:
            with self.session_factory(self.output_dir) as session:
                self._current_task = session.task
                self.summary["window"] = extract_window_info(session)
                if not self.summary["window"]["width"] or not self.summary["window"]["height"]:
                    self._error("window_not_found")
                    return self._finish()
                if not self._window_matches_expected_resolution(self.summary["window"]):
                    expected = resolution_to_dict(self.expected_resolution)
                    actual = {
                        "width": self.summary["window"]["width"],
                        "height": self.summary["window"]["height"],
                    }
                    self._error(f"resolution_mismatch: expected {expected}, got {actual}")
                    return self._finish()
                before = self._screenshot("task_items_before")
                flow = DailyActivityFlow.from_task(session.task)
                result = DailyTaskItemActionRunner(flow, dry_run=self.mode == "dry-run").run()
                after = self._screenshot("task_items_after")
                self.summary["before_screenshot"] = before
                self.summary["after_screenshot"] = after
                self.summary["result"] = object_to_jsonable(result)
                self.summary["preflight"] = object_to_jsonable(result.get("preflight", {}))
                self.summary["ok"] = bool(result.get("ok"))
                self.summary["mutation_performed"] = bool(result.get("mutation_performed"))
                self.summary["mutation_verified"] = bool(result.get("mutation_verified"))
                self.summary["task_completed"] = bool(result.get("task_completed"))
                self.summary["handler_completed"] = bool(result.get("handler_completed"))
                self.summary["items"] = object_to_jsonable(result.get("items", []))
                self.summary["actions"] = object_to_jsonable(result.get("actions", []))
                self.summary["skipped"] = object_to_jsonable(result.get("skipped", []))
                self.summary["blockers"] = object_to_jsonable(result.get("blockers", []))
                self.summary["gift"] = object_to_jsonable(result.get("gift", {}))
        except Exception as exc:
            self._error(classify_exception(exc), exc)
        finally:
            self._current_task = None
        return self._finish()

    def _window_matches_expected_resolution(self, window: dict[str, Any]) -> bool:
        if self.expected_resolution is None:
            return True
        return (
            int(window.get("width") or 0),
            int(window.get("height") or 0),
        ) == self.expected_resolution

    def _empty_summary(self):
        git_info = self.git_info_provider()
        return {
            "git_branch": git_info.get("git_branch", ""),
            "git_head": git_info.get("git_head", ""),
            "dirty": bool(git_info.get("dirty", False)),
            "command": self.command,
            "mode": self.mode,
            "started_at": _iso_now(),
            "finished_at": "",
            "ok": False,
            "window": {"width": 0, "height": 0, "title": "", "hwnd": ""},
            "mutation_performed": False,
            "mutation_verified": False,
            "task_completed": False,
            "handler_completed": False,
            "preflight": {},
            "gift": {},
            "items": [],
            "actions": [],
            "skipped": [],
            "blockers": [],
            "warnings": [],
            "errors": [],
            "artifacts": [],
            "artifact_dir": str(self.output_dir),
            "modules": {
                "daily_task_items": {"mutation_performed": False},
                "daily_task": {"mutation_performed": False},
                "coffee": {"mutation_performed": False},
                "gift": {"mutation_performed": False},
            },
        }

    def _finish(self):
        self.summary["finished_at"] = _iso_now()
        self.summary["modules"]["daily_task_items"]["mutation_performed"] = bool(self.summary["mutation_performed"])
        self.summary["modules"]["daily_task"]["mutation_performed"] = bool(self.summary["mutation_performed"])
        gift = self.summary.get("gift") or {}
        self.summary["modules"]["gift"].update(
            {
                "mutation_performed": bool(gift.get("mutation_performed", False)),
                "mutation_verified": bool(gift.get("mutation_verified", False)),
                "sent_total": int(gift.get("sent_total", 0) or 0),
                "selected_character": str(gift.get("selected_character", "") or ""),
                "selected_item": str(gift.get("selected_item", "") or ""),
                "task_completed": bool(gift.get("task_completed", False)),
                "task_reward_claimed": bool(gift.get("task_reward_claimed", False)),
                "activity_rewards_claimed": int(gift.get("activity_rewards_claimed", 0) or 0),
                "claimable_rewards_remaining": gift.get("claimable_rewards_remaining"),
                "claimable_rewards_reason": str(gift.get("claimable_rewards_reason", "") or ""),
            }
        )
        summary_path = self.output_dir / "summary.json"
        summary_path.write_text(json.dumps(self.summary, ensure_ascii=False, indent=2), encoding="utf-8")
        self._artifact("summary_json", summary_path)
        return self.summary

    def _artifact(self, name: str, path: Path):
        self.summary["artifacts"].append({"name": name, "path": str(path)})

    def _error(self, code: str, exc: BaseException | None = None):
        message = code if exc is None else f"{code}: {exc}"
        self.summary["errors"].append(message)
        if exc is not None:
            trace_path = self.output_dir / f"{code}.traceback.txt"
            trace_path.write_text("".join(traceback.format_exception(exc)), encoding="utf-8")
            self._artifact(f"{code}_traceback", trace_path)

    def _screenshot(self, stem: str):
        task = self._current_task
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


def build_arg_parser():
    parser = argparse.ArgumentParser(description="Run Daily/F1 task-item dry-run or real-run validation.")
    parser.add_argument("--mode", choices=MODES, default="dry-run")
    parser.add_argument(
        "--expect-resolution",
        type=parse_resolution,
        default=None,
        help="Require the captured client resolution, for example 1920x1080. Does not resize the game window.",
    )
    parser.add_argument("--json", action="store_true", help="Print summary JSON to stdout.")
    return parser


def main(argv: list[str] | None = None):
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    command = " ".join([Path(sys.executable).name, *sys.argv])
    runner = DailyTaskItemsValidationRunner(
        args.mode,
        command=command,
        expected_resolution=args.expect_resolution,
    )
    summary = runner.run()
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"summary: {runner.output_dir / 'summary.json'}")
        print(f"ok: {summary['ok']}")
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
