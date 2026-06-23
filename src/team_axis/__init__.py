"""Team-level combat axis support.

This package is intentionally isolated from the character combo system.  A
matching team axis owns the complete combat order and therefore does not call
``BaseChar.perform`` or the normal priority-based switcher.
"""

from src.team_axis.BaseTeamAxis import BaseTeamAxis, TeamAxisError
from src.team_axis.CustomTeamAxis import CustomTeamAxis, CustomTeamAxisDefinition
from src.team_axis.TeamAxisRegistry import (
    create_matching_team_axis,
    get_axis_class,
    get_axis_classes,
)

__all__ = [
    "BaseTeamAxis",
    "CustomTeamAxis",
    "CustomTeamAxisDefinition",
    "TeamAxisError",
    "create_matching_team_axis",
    "get_axis_class",
    "get_axis_classes",
]
