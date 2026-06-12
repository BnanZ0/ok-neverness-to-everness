"""Combat planner public API facade.

角色代码只应从这个 package facade 导入 planner 类型和 `CombatPlanner`：

    from src.combat.planner import ActionSlot, CombatPlanner, FieldClaim

这里的 `__all__` 是正式角色开发 API。内部实现拆在
`core/context/requests/state/types`，但这些文件名不作为角色开发 API。
"""

from .core import *  # noqa: F403
from .core import __all__  # noqa: F401
