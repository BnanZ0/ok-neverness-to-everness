from typing import TYPE_CHECKING

from src.char.CharFactory import get_char_feature_by_pos
from src.char.custom.CustomCharManager import CustomCharManager

if TYPE_CHECKING:
    from src.combat.BaseCombatTask import BaseCombatTask


class TeamScanError(Exception):
    pass


class TeamScanner:
    txt_team_not_exist = "队伍不存在"
    txt_team_not_enough = "队伍人数少于2人"

    def __init__(self, manager: CustomCharManager | None = None):
        self.manager = manager or CustomCharManager()

    def scan(self, task: "BaseCombatTask"):
        in_team, _, count = task.in_team()
        if not in_team or count == 0:
            raise TeamScanError(task.tr(self.txt_team_not_exist))
        if count < 2:
            raise TeamScanError(task.tr(self.txt_team_not_enough))

        results = []
        frame = task.frame
        for i in range(count):
            feature_mat, w, h = get_char_feature_by_pos(task, i, frame=frame)
            if feature_mat is None or feature_mat.size <= 0:
                continue

            is_match, match_name, confidence = self.manager.match_feature(task, feature_mat)
            name = match_name if is_match else None
            results.append(
                {
                    "index": i,
                    "mat": feature_mat,
                    "width": w,
                    "height": h,
                    "match": name,
                    "confidence": confidence,
                }
            )
        return results
