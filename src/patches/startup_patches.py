from __future__ import annotations

_PATCH_INSTALLED = False


def install_startup_patches():
    global _PATCH_INSTALLED
    if _PATCH_INSTALLED:
        return

    from src.patches.i18n_patch import install_i18n_patch
    from src.patches.task_tab_patch import install_task_tab_patch

    install_i18n_patch()
    install_task_tab_patch()
    _PATCH_INSTALLED = True
