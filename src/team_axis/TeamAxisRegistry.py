from __future__ import annotations

import importlib
import inspect
import pkgutil

from ok import Logger

from src.char.custom.CustomCharManager import CustomCharManager
from src.team_axis.BaseTeamAxis import BaseTeamAxis
from src.team_axis.CustomTeamAxis import CustomTeamAxis, CustomTeamAxisDefinition

_axis_classes: list[type[BaseTeamAxis]] | None = None
logger = Logger.get_logger(__name__)
AxisDefinition = type[BaseTeamAxis] | CustomTeamAxisDefinition


def _discover_axis_classes() -> list[type[BaseTeamAxis]]:
    """Discover axis modules so adding an axis does not require editing a registry."""
    from src.team_axis import axes

    discovered = []
    prefix = f"{axes.__name__}."
    for module_info in pkgutil.iter_modules(axes.__path__, prefix):
        try:
            module = importlib.import_module(module_info.name)
        except Exception as error:
            logger.error(f"Failed to load team axis module: {module_info.name}", error)
            continue
        for _, candidate in inspect.getmembers(module, inspect.isclass):
            if (
                candidate is not BaseTeamAxis
                and issubclass(candidate, BaseTeamAxis)
                and candidate.__module__ == module.__name__
            ):
                discovered.append(candidate)
    return sorted(discovered, key=lambda cls: cls.priority, reverse=True)


def _axis_label(axis_class: AxisDefinition | None) -> str:
    if axis_class is None:
        return ""
    return getattr(axis_class, "axis_id", getattr(axis_class, "__name__", str(axis_class)))


def _load_custom_axis_definitions() -> list[CustomTeamAxisDefinition]:
    manager = CustomCharManager()
    custom_axes = []
    for axis_id, axis_config in manager.get_custom_team_axes().items():
        try:
            custom_axes.append(CustomTeamAxis.build_definition(axis_config))
        except Exception as error:
            logger.error(f"Failed to load custom team axis: {axis_id}", error)
    return custom_axes


def get_axis_classes() -> list[AxisDefinition]:
    global _axis_classes
    if _axis_classes is None:
        _axis_classes = _discover_axis_classes()
    axes = list(_axis_classes)
    axes.extend(_load_custom_axis_definitions())
    return sorted(axes, key=lambda axis: axis.priority, reverse=True)


def get_axis_class(axis_id: str) -> AxisDefinition | None:
    """Return one registered axis by its stable configuration id."""
    axis_id = str(axis_id or "").strip()
    for axis_class in get_axis_classes():
        if axis_class.axis_id == axis_id:
            return axis_class
    return None


def create_matching_team_axis(task, axis_id: str = "") -> BaseTeamAxis | None:
    """Create the highest-priority axis matching the exact ordered team."""
    axis_classes = [get_axis_class(axis_id)] if axis_id else get_axis_classes()
    for axis_class in axis_classes:
        if axis_class is None:
            continue
        try:
            matches = axis_class.matches(task.chars)
        except Exception as error:
            logger.error(f"Failed to match team axis: {_axis_label(axis_class)}", error)
            continue
        if not matches:
            continue

        try:
            if isinstance(axis_class, CustomTeamAxisDefinition):
                return axis_class.create(task)
            return axis_class(task)
        except Exception as error:
            logger.error(f"Failed to create team axis: {_axis_label(axis_class)}", error)
    return None


def clear_registry_cache():
    """Test/development helper used after adding an axis module at runtime."""
    global _axis_classes
    _axis_classes = None
