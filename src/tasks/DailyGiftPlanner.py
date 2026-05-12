from dataclasses import dataclass, field


@dataclass
class GiftOption:
    identity: str
    inventory: int
    base_affinity: int = 0
    bonus_affinity: int = 0
    has_bonus_marker: bool = False
    visible_order: int = 0
    target: object | None = None


@dataclass
class GiftCharacter:
    name: str
    daily_count: int | None
    daily_limit: int = 3
    gifts: list[GiftOption] = field(default_factory=list)
    target: object | None = None


@dataclass
class GiftPanelState:
    daily_total_count: int | None
    daily_total_limit: int = 10
    characters: list[GiftCharacter] = field(default_factory=list)
    send_button_target: object | None = None
    popup_close_target: object | None = None


@dataclass
class GiftPlanAction:
    kind: str
    target: object | None = None
    character_name: str = ""
    gift_identity: str = ""
    reason: str = ""


@dataclass
class GiftPlanResult:
    can_execute: bool
    actions: list[GiftPlanAction] = field(default_factory=list)
    selected_gifts: list[GiftOption] = field(default_factory=list)
    skip_reason: str = ""


class DailyGiftAnalyzer:
    """Gift panel state adapter.

    Without a task-level collector, gifting is skipped instead of attempting
    blind UI loops.
    """

    def __init__(self, task):
        self.task = task

    def analyze(self):
        collector = getattr(self.task, "collect_daily_gift_state", None)
        if callable(collector):
            return collector()
        return None

    def can_analyze(self):
        return callable(getattr(self.task, "collect_daily_gift_state", None))


class DailyGiftPlanner:
    NO_TARGETS = "未配置赠礼目标角色，跳过赠礼"
    NO_STATE = "未能稳定识别赠礼界面"
    UNREADABLE_DAILY_COUNTER = "赠礼每日总计数不可读，跳过赠礼"
    DAILY_CAP_REACHED = "赠礼每日总上限已达到"
    REQUIREMENT_DONE = "赠礼活跃度需求已满足"
    NO_SEND_BUTTON = "未检测到赠礼确认按钮，跳过赠礼"
    NO_SAFE_GIFTS = "未找到可安全赠送的礼物"

    def __init__(self, target_names=None, required_count=1):
        self.target_names = [name.strip() for name in (target_names or []) if str(name).strip()]
        self.required_count = max(0, int(required_count or 0))

    def build_plan(self, state: GiftPanelState | None):
        if not self.target_names:
            return GiftPlanResult(False, skip_reason=self.NO_TARGETS)
        if state is None:
            return GiftPlanResult(False, skip_reason=self.NO_STATE)
        if self.required_count <= 0:
            return GiftPlanResult(False, skip_reason=self.REQUIREMENT_DONE)
        if state.daily_total_count is None:
            return GiftPlanResult(False, skip_reason=self.UNREADABLE_DAILY_COUNTER)
        if state.daily_total_count >= state.daily_total_limit:
            return GiftPlanResult(False, skip_reason=self.DAILY_CAP_REACHED)
        if state.send_button_target is None:
            return GiftPlanResult(False, skip_reason=self.NO_SEND_BUTTON)

        remaining_total = min(
            self.required_count,
            max(0, state.daily_total_limit - state.daily_total_count),
        )
        actions = []
        selected = []
        characters = self._target_characters(state.characters)

        for character in characters:
            if remaining_total <= 0:
                break
            if character.daily_count is None:
                continue
            character_remaining = max(0, character.daily_limit - character.daily_count)
            if character_remaining <= 0:
                continue

            gifts = self.rank_gifts(character.gifts)
            if not gifts:
                continue

            if character.target is not None:
                actions.append(GiftPlanAction("select_character", character.target, character_name=character.name))

            for gift in gifts:
                if remaining_total <= 0 or character_remaining <= 0:
                    break
                send_count = min(int(gift.inventory), remaining_total, character_remaining)
                for _ in range(send_count):
                    actions.append(
                        GiftPlanAction(
                            "select_gift",
                            gift.target,
                            character_name=character.name,
                            gift_identity=gift.identity,
                        )
                    )
                    actions.append(
                        GiftPlanAction(
                            "send_gift",
                            state.send_button_target,
                            character_name=character.name,
                            gift_identity=gift.identity,
                        )
                    )
                    selected.append(gift)
                    remaining_total -= 1
                    character_remaining -= 1

        if not selected:
            return GiftPlanResult(False, skip_reason=self.NO_SAFE_GIFTS)

        if state.popup_close_target is not None:
            actions.append(GiftPlanAction("close_popup", state.popup_close_target))
        else:
            actions.append(GiftPlanAction("close_popup"))

        return GiftPlanResult(True, actions=actions, selected_gifts=selected)

    def _target_characters(self, characters):
        by_name = {character.name: character for character in characters}
        return [by_name[name] for name in self.target_names if name in by_name]

    @staticmethod
    def rank_gifts(gifts):
        return sorted(
            [gift for gift in gifts if int(gift.inventory) > 0],
            key=lambda gift: (
                not bool(gift.has_bonus_marker),
                -int(gift.bonus_affinity or 0),
                -int(gift.base_affinity or 0),
                int(gift.visible_order),
            ),
        )
