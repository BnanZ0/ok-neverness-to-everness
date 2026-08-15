from __future__ import annotations

from functools import wraps

_PATCH_INSTALLED = False


def install_task_tab_patch():
    global _PATCH_INSTALLED
    if _PATCH_INSTALLED:
        return

    from ok import og
    from ok.gui.tasks.OneTimeTaskTab import OneTimeTaskTab

    original_refresh_ui = OneTimeTaskTab.refresh_ui

    @wraps(original_refresh_ui)
    def refresh_ui_without_hidden_tasks(self):
        original_tasks = og.executor.onetime_tasks
        og.executor.onetime_tasks = [
            task
            for task in original_tasks
            if getattr(task, "show_in_task_tab", True)
        ]
        try:
            return original_refresh_ui(self)
        finally:
            og.executor.onetime_tasks = original_tasks

    OneTimeTaskTab.refresh_ui = refresh_ui_without_hidden_tasks
    _PATCH_INSTALLED = True
