from dataclasses import dataclass, field


@dataclass
class CoffeeFoodOption:
    identity: str
    price_value: int | None = None
    category: str = ""
    trend_match: bool = False
    visible_order: int = 0
    target: object | None = None


@dataclass
class CoffeeSupplySlot:
    identity: str
    options: list[CoffeeFoodOption] = field(default_factory=list)
    current_food_identity: str = ""
    needs_supply: bool = True
    safe: bool = True
    target: object | None = None


@dataclass
class CoffeeShopState:
    trend_category: str = ""
    income_claim_target: object | None = None
    supply_target: object | None = None
    slots: list[CoffeeSupplySlot] = field(default_factory=list)
    duration_options: dict[str, object] = field(default_factory=dict)
    buy_target: object | None = None
    home_delivery_target: object | None = None
    delivery_confirm_target: object | None = None
    popup_close_target: object | None = None


@dataclass
class CoffeePlanAction:
    kind: str
    target: object | None = None
    slot_identity: str = ""
    food_identity: str = ""
    reason: str = ""


@dataclass
class CoffeePlanResult:
    can_execute: bool
    actions: list[CoffeePlanAction] = field(default_factory=list)
    selected_options: list[CoffeeFoodOption] = field(default_factory=list)
    skip_reason: str = ""


class DailyCoffeeAnalyzer:
    """Coffee shop state adapter.

    Runtime UI recognition is intentionally exposed through an optional task
    hook so the strategy can stay testable and skip safely when no detector is
    available.
    """

    def __init__(self, task):
        self.task = task

    def analyze(self):
        collector = getattr(self.task, "collect_daily_coffee_state", None)
        if callable(collector):
            return collector()
        return None

    def can_analyze(self):
        return callable(getattr(self.task, "collect_daily_coffee_state", None))


class DailyCoffeePlanner:
    ALLOWED_DURATIONS = ("4小时", "8小时", "24小时", "72小时")
    NO_STATE = "未能稳定识别咖啡店补货界面"
    NO_SAFE_SLOTS = "未检测到需要补货的安全槽位"
    NO_SAFE_FOOD = "价格和趋势均不可读，跳过高风险切换"
    NO_BUY_TARGET = "未检测到补货购买按钮，停止购买"
    NO_HOME_DELIVERY = "未检测到送货上门选项，停止购买"

    def __init__(self, max_supply_slots=0, target_duration="24小时"):
        self.max_supply_slots = max(0, int(max_supply_slots or 0))
        self.target_duration = self.normalize_duration(target_duration or "24小时")

    @property
    def no_duration_reason(self):
        return f"未检测到{self.target_duration}补货选项，停止购买"

    @property
    def invalid_duration_reason(self):
        allowed = "/".join(self.ALLOWED_DURATIONS)
        return f"补货时长必须是固定选项之一: {allowed}"

    def build_plan(self, state: CoffeeShopState | None):
        if state is None:
            return CoffeePlanResult(False, skip_reason=self.NO_STATE)
        if not self.is_allowed_duration(self.target_duration):
            return CoffeePlanResult(False, skip_reason=self.invalid_duration_reason)

        slots = [slot for slot in state.slots if slot.safe and slot.needs_supply]
        if self.max_supply_slots:
            slots = slots[: self.max_supply_slots]
        if not slots:
            return CoffeePlanResult(False, skip_reason=self.NO_SAFE_SLOTS)

        selected = []
        for slot in slots:
            option = self.best_option(slot.options, state.trend_category)
            if option is None:
                return CoffeePlanResult(False, skip_reason=self.NO_SAFE_FOOD)
            selected.append((slot, option))

        duration_target = self._duration_target(state.duration_options, self.target_duration)
        if duration_target is None:
            return CoffeePlanResult(False, skip_reason=self.no_duration_reason)
        if state.buy_target is None:
            return CoffeePlanResult(False, skip_reason=self.NO_BUY_TARGET)
        if state.home_delivery_target is None:
            return CoffeePlanResult(False, skip_reason=self.NO_HOME_DELIVERY)

        actions = []
        if state.income_claim_target is not None:
            actions.append(CoffeePlanAction("claim_income", state.income_claim_target))
        if state.supply_target is not None:
            actions.append(CoffeePlanAction("open_supply", state.supply_target))

        selected_options = []
        for slot, option in selected:
            selected_options.append(option)
            if slot.target is not None:
                actions.append(CoffeePlanAction("select_slot", slot.target, slot_identity=slot.identity))
            if slot.current_food_identity != option.identity:
                actions.append(
                    CoffeePlanAction(
                        "select_food",
                        option.target,
                        slot_identity=slot.identity,
                        food_identity=option.identity,
                    )
                )

        actions.append(CoffeePlanAction("select_supply_duration", duration_target, reason=self.target_duration))
        actions.append(CoffeePlanAction("buy_supply", state.buy_target))
        actions.append(CoffeePlanAction("select_home_delivery", state.home_delivery_target))
        if state.delivery_confirm_target is not None:
            actions.append(CoffeePlanAction("confirm_delivery", state.delivery_confirm_target))
        if state.popup_close_target is not None:
            actions.append(CoffeePlanAction("close_popup", state.popup_close_target))
        else:
            actions.append(CoffeePlanAction("close_popup"))

        return CoffeePlanResult(True, actions=actions, selected_options=selected_options)

    @classmethod
    def best_option(cls, options, trend_category=""):
        options = list(options or [])
        priced = [option for option in options if option.price_value is not None]
        if priced:
            return sorted(
                priced,
                key=lambda option: (
                    -int(option.price_value),
                    not cls._matches_trend(option, trend_category),
                    int(option.visible_order),
                ),
            )[0]

        if trend_category:
            trend_options = [option for option in options if cls._matches_trend(option, trend_category)]
            if trend_options:
                return sorted(trend_options, key=lambda option: int(option.visible_order))[0]

        return None

    @staticmethod
    def _matches_trend(option, trend_category):
        if option.trend_match:
            return True
        return bool(trend_category and option.category and option.category == trend_category)

    @staticmethod
    def _duration_target(duration_options, target_duration):
        normalized = DailyCoffeePlanner.normalize_duration(target_duration)
        if not DailyCoffeePlanner.is_allowed_duration(normalized):
            return None
        for key, value in duration_options.items():
            if DailyCoffeePlanner.normalize_duration(key) == normalized:
                return value
        return None

    @staticmethod
    def normalize_duration(duration):
        text = str(duration or "").strip().lower().replace(" ", "")
        aliases = {
            "4h": "4小时",
            "4hour": "4小时",
            "4小时": "4小时",
            "8h": "8小时",
            "8hour": "8小时",
            "8小时": "8小时",
            "24h": "24小时",
            "24hour": "24小时",
            "24小时": "24小时",
            "72h": "72小时",
            "72hour": "72小时",
            "72小时": "72小时",
        }
        return aliases.get(text, text)

    @staticmethod
    def is_allowed_duration(duration):
        return DailyCoffeePlanner.normalize_duration(duration) in DailyCoffeePlanner.ALLOWED_DURATIONS

    @staticmethod
    def _one_hour_target(duration_options):
        return DailyCoffeePlanner._duration_target(duration_options, "1小时")
