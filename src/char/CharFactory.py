import math
from typing import TYPE_CHECKING

from typing_extensions import Any

from src.char.BaseChar import BaseChar, Element
from src.char.Chiz import Chiz
from src.char.Fadia import Fadia
from src.char.Hotori import Hotori
from src.char.Iroi import Iroi
from src.char.Jiuyuan import Jiuyuan
from src.char.Lacrimosa import Lacrimosa
from src.char.Mint import Mint
from src.char.Nanally import Nanally
from src.char.Sakiri import Sakiri
from src.char.Shinku import Shinku
from src.char.Zero import Zero

if TYPE_CHECKING:
    import numpy as np
    from ok import Box

    from src.char.custom.CustomCharManager import CustomCharManager
    from src.combat.BaseCombatTask import BaseCombatTask

char_dict: dict[str, dict[str, Any]] = {
    "char_default": {"cls": BaseChar},
    "char_zero": {"cls": Zero, "cn_name": "零", "element": Element.WHITE},
    "char_mint": {"cls": Mint, "cn_name": "薄荷", "element": Element.GREEN},
    "char_jiuyuan": {"cls": Jiuyuan, "cn_name": "九原", "element": Element.GREEN},
    "char_sakiri": {"cls": Sakiri, "cn_name": "早雾", "element": Element.RED},
    "char_nanally": {"cls": Nanally, "cn_name": "娜娜莉", "element": Element.GREEN},
    "char_hotori": {"cls": Hotori, "cn_name": "浔", "element": Element.WHITE},
    "char_chiz": {"cls": Chiz, "cn_name": "小吱", "element": Element.WHITE},
    "char_lacrimosa": {"cls": Lacrimosa, "cn_name": "安魂曲", "element": Element.PURPLE},
    "char_fadia": {"cls": Fadia, "cn_name": "法帝娅", "element": Element.BLUE},
    "char_shinku": {"cls": Shinku, "cn_name": "真红", "element": Element.WHITE},
    "char_iroi": {"cls": Iroi, "cn_name": "伊洛伊", "element": Element.GREEN},
}

char_names = char_dict.keys()


def _build_char_instance(
    task,
    index,
    match_id,
    sim,
    manager: "CustomCharManager",
    combo_id_override: str | None = None,
):
    from src.char.custom.CustomChar import CustomChar

    char_info = manager.get_character_info_by_id(match_id)
    match_name = char_info["char_name"] if char_info else "unknown"

    if combo_id_override is None:
        combo_id = char_info["combo_id"] if char_info else ""
    else:
        combo_id = combo_id_override

    if not combo_id:
        char_id = char_info["char_id"] if char_info else "unknown"
        instance = BaseChar(task, index, char_id=char_id, confidence=sim)
        instance.char_name = match_name
        return instance

    if manager.is_builtin_combo(combo_id) and combo_id in char_dict:
        cls = char_dict[combo_id].get("cls", BaseChar)
        instance: "BaseChar" = cls(task, index, char_id=match_id, confidence=sim)
        instance.char_name = match_name
        instance.combo_name = manager.get_combo_name(combo_id, with_builtin_prefix=True)
        instance.builtin = True
        instance.element = char_dict[combo_id].get("element", Element.DEFAULT)
    else:
        instance = CustomChar(task, index, char_id=match_id, combo_id=combo_id, confidence=sim)
        instance.char_name = match_name

    return instance


def get_char_by_id(
    task: "BaseCombatTask", index: int, char_id: str, confidence=1, combo_id: str | None = None
):
    from src.char.custom.CustomCharManager import CustomCharManager

    manager = CustomCharManager()
    if not char_id:
        return BaseChar(task, index, char_id="unknown", confidence=confidence)
    return _build_char_instance(
        task, index, char_id, confidence, manager, combo_id_override=combo_id
    )


def get_char_by_pos(task: "BaseCombatTask", box: "Box", index: int, old_char: BaseChar | None):
    # Retrieve CustomCharManager and test match
    from src.char.custom.CustomCharManager import CustomCharManager

    manager = CustomCharManager()
    cropped = box.crop_frame(task.frame)
    # Fast path check: if we already have an old_char, specifically test its matching only
    if old_char and old_char.confidence > 0.8:
        is_match, match_id, sim = manager.match_feature(
            task, cropped, target_char=old_char.char_id
        )
        if is_match and match_id == old_char.char_id:
            return _build_char_instance(task, index, match_id, sim, manager)

    # Perform Full DB Scan using the memory-cached match_feature
    is_match, match_id, sim = manager.match_feature(task, cropped)

    if is_match and match_id:
        return _build_char_instance(task, index, match_id, sim, manager)

    task.log_info(f"No match found for char {index + 1} set as default char")
    return BaseChar(task, index, char_id="unknown")


def get_char_feature_by_pos(
    task: "BaseCombatTask", index, frame=None, scale_box=1.0
) -> tuple["np.ndarray", int, int]:
    """
    Get the feature image of the character at the given position.

    Args:
        task: The combat task.
        index: The index of the character.

    Returns:
        A tuple containing the feature image, width, and height.
    """
    if frame is None:
        frame = task.frame
    box = task.get_char_box(index)
    if not math.isclose(scale_box, 1.0):
        box = box.scale(scale_box, scale_box)
    return box.crop_frame(frame), task.width, task.height


def is_float(s):
    try:
        float(s)
        return True
    except ValueError:
        return False
