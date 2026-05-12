import re
from typing import Callable, Iterable

from src.tasks.DailyActionGate import DailyActionGate
from src.tasks.DailyActivityAnalyzer import DailyActivityAnalyzer, DailyActivityPage, DailyActivityState, RegionBox
from src.tasks.DailyActivityModels import (
    ActionGateSpec,
    ActivityCardCandidate,
    ActivityHandleIntent,
    DailyActivityOutcome,
    DailyActivitySnapshot,
)
from src.tasks.DailyActivityRegistry import (
    DailyActivityHandlerRule,
    resolve_activity_handler_rule,
    title_contains,
    title_contains_all,
    title_contains_any,
)
from src.tasks.DailyCoffeePlanner import DailyCoffeeAnalyzer, DailyCoffeePlanner
from src.tasks.DailyCoffeeRuntime import DailyCoffeeRuntime
from src.tasks.DailyGiftPlanner import DailyGiftAnalyzer, DailyGiftPlanner
from src.tasks.DailyResultRecorder import DailyResultRecorder
from src.tasks.DailyUIContext import ReadOnlyUIContext, TaskUIAdapter
from src.tasks.F1PanelDetector import DailyPanelOpenResult, F1PanelDetector
from src.tasks.FlowResult import FlowResult
from src.utils.viewport_adapter import LAYOUT_PROFILE_NATIVE_16_9


def _noop(*args, **kwargs):
    return None


class DailyActivityActionContext:
    """Explicit mutation-capable surface for the daily activity flow."""

    def __init__(
        self,
        *,
        ui: TaskUIAdapter,
        config_getter: Callable[[], dict] | None = None,
        task_status_getter: Callable[[], dict] | None = None,
        info_set: Callable[..., object] | None = None,
        log_info: Callable[..., object] | None = None,
        log_warning: Callable[..., object] | None = None,
        open_f1_panel: Callable[[], object] | None = None,
        collect_daily_coffee_state: Callable[[], object] | None = None,
        collect_daily_gift_state: Callable[[], object] | None = None,
    ):
        self.ui = TaskUIAdapter.coerce(ui)
        self._config_getter = config_getter or (lambda: {})
        self._task_status_getter = task_status_getter or (lambda: {})
        self._info_set = info_set or _noop
        self._log_info = log_info or _noop
        self._log_warning = log_warning or _noop
        self._open_f1_panel = open_f1_panel
        self._collect_daily_coffee_state = collect_daily_coffee_state
        self._collect_daily_gift_state = collect_daily_gift_state

    @classmethod
    def from_task(cls, task):
        return cls(
            ui=TaskUIAdapter(task),
            config_getter=lambda: getattr(task, "config", {}) or {},
            task_status_getter=lambda: getattr(task, "task_status", {}) or {},
            info_set=getattr(task, "info_set", None),
            log_info=getattr(task, "log_info", None),
            log_warning=getattr(task, "log_warning", None),
            open_f1_panel=getattr(task, "openF1panel", None),
            collect_daily_coffee_state=getattr(task, "collect_daily_coffee_state", None),
            collect_daily_gift_state=getattr(task, "collect_daily_gift_state", None),
        )

    @property
    def config(self):
        return self._config_getter() or {}

    def completed_task_keys(self):
        status = self._task_status_getter() or {}
        return list(status.get("success", []) or [])

    def info_set(self, *args, **kwargs):
        return self._info_set(*args, **kwargs)

    def log_info(self, *args, **kwargs):
        return self._log_info(*args, **kwargs)

    def log_warning(self, *args, **kwargs):
        return self._log_warning(*args, **kwargs)

    def open_f1_panel(self):
        if not callable(self._open_f1_panel):
            raise AttributeError("Daily activity action context does not provide open_f1_panel()")
        return self._open_f1_panel()

    def ensure_daily_main(self):
        return self.ui.ensure_daily_main()

    def click(self, *args, **kwargs):
        return self.ui.click(*args, **kwargs)

    def click_ui(self, *args, **kwargs):
        return self.ui.click_ui(*args, **kwargs)

    def sleep(self, seconds):
        return self.ui.sleep(seconds)

    def next_frame(self):
        return self.ui.next_frame()

    def swipe(self, *args, **kwargs):
        return self.ui.swipe(*args, **kwargs)

    def send_key(self, *args, **kwargs):
        return self.ui.send_key(*args, **kwargs)

    def send_foreground_key(self, *args, **kwargs):
        return self.ui.send_foreground_key(*args, **kwargs)

    def ui_point(self, x, y):
        return self.ui.ui_point(x, y)

    @property
    def width(self):
        return self.ui.width

    @property
    def height(self):
        return self.ui.height

    def collect_daily_coffee_state(self):
        if callable(self._collect_daily_coffee_state):
            return self._collect_daily_coffee_state()
        return None

    def has_daily_coffee_state_collector(self):
        return callable(self._collect_daily_coffee_state)

    def collect_daily_gift_state(self):
        if callable(self._collect_daily_gift_state):
            return self._collect_daily_gift_state()
        return None

    def has_daily_gift_state_collector(self):
        return callable(self._collect_daily_gift_state)


class DailyActivityFlow:
    CONF_CLAIM_MAIL = "领取邮件"
    CONF_CLAIM_BP = "领取环期任务奖励"
    CONF_COMPLETE_DAILY = "完成每日活跃度"
    CONF_CLAIM_ACTIVITY = "领取活跃度奖励"

    DAILY_ACTIVITY_TAB_INDEX = 2
    DAILY_ACTIVITY_TAB_POSITION = (0.0551, 0.3275)
    NATIVE_16_9_DAILY_ACTIVITY_TAB_POSITION = (0.0551, 0.3810)
    DAILY_ACTIVITY_TAB_BOX_SIZE = (0.0900, 0.0700)
    MAX_ACTIVITY_MISSION_CLAIMS = 5
    MAX_ACTIVITY_CARD_SWIPES = 8
    DAILY_ACTIVITY_CARD_SWIPE_START = (0.78, 0.58)
    DAILY_ACTIVITY_CARD_SWIPE_END = (0.30, 0.58)
    DAILY_ACTIVITY_CARD_SWIPE_START_X_IN_BOX = 0.60
    DAILY_ACTIVITY_CARD_SWIPE_END_X_IN_BOX = 0.40
    DAILY_ACTIVITY_CARD_SWIPE_Y_IN_BOX = 0.47
    DAILY_ACTIVITY_CARD_RIGHT_EDGE_LIMIT = 0.88
    DAILY_ACTIVITY_MISSING_FEATURES = "任务条目/前往按钮/完成状态"
    ACTIVITY_REWARD_UNAVAILABLE = "未检测到可领取活跃度奖励"
    ACTIVITY_REWARD_DEFERRED_UNTIL_FULL = "活跃度未达到100，默认延后领取阶段奖励"
    ACTIVITY_SCORE_FULL = 100
    DAILY_PANEL_VERIFY_ATTEMPTS = 3
    DAILY_PANEL_VERIFY_RETRY_SLEEP = 0.5
    DAILY_ACTIVITY_TITLE_MARKERS = (
        "累计",
        "赠送",
        "释放",
        "击败",
        "消费",
        "消耗",
        "提升",
        "登录",
        "弧盘",
        "本性像素",
        "敌人",
        "极轨",
        "礼物",
        "方斯",
        "都市活力",
    )
    SIMPLE_ACTIVITY_ACTIONS = (CONF_CLAIM_MAIL, CONF_CLAIM_BP)
    ARC_ATTACK_ACTIVITY_KEY = "释放3次极轨攻击"
    COFFEE_ACTIVITY_KEY = "咖啡店补货"
    COFFEE_ACTIVITY_KEYWORDS = ("咖", "都市活力")
    GIFT_ACTIVITY_KEY = "赠礼"
    GIFT_ACTIVITY_KEYWORDS = ("赠送", "礼物")
    STRENGTHEN_ACTIVITY_KEY = "强化"
    STRENGTHEN_ACTIVITY_KEYWORDS = ("提升", "强化", "弧盘", "孤岛等级")
    RESOURCE_ACTIVITY_KEYWORDS = ("赠送", "礼物", "提升", "孤岛等级", "弧盘等级", "消耗", "本性像素")
    UNSUPPORTED_ACTIVITY_REASON = "未配置安全自动 handler，未点击前往"
    ACTIVITY_HANDLER_REGISTRY = (
        DailyActivityHandlerRule(
            handler_key=COFFEE_ACTIVITY_KEY,
            handler_name="_handle_coffee_activity",
            matcher=title_contains_any(*COFFEE_ACTIVITY_KEYWORDS),
            priority=10,
            default_blocked_reason="咖啡店补货需要稳定识别一咖舍、商品、固定补货时长和送货上门",
        ),
        DailyActivityHandlerRule(
            handler_key=GIFT_ACTIVITY_KEY,
            handler_name="_handle_gift_activity",
            matcher=title_contains_all(*GIFT_ACTIVITY_KEYWORDS),
            priority=20,
            default_blocked_reason="赠礼需要显式目标角色和可读赠礼计数",
        ),
        DailyActivityHandlerRule(
            handler_key=STRENGTHEN_ACTIVITY_KEY,
            handler_name="_handle_strengthen_activity",
            matcher=title_contains_any(*STRENGTHEN_ACTIVITY_KEYWORDS),
            priority=30,
            default_blocked_reason="强化类任务默认保守，未识别单次安全动作",
        ),
        DailyActivityHandlerRule(
            handler_key=ARC_ATTACK_ACTIVITY_KEY,
            handler_name="_handle_arc_attack_activity",
            matcher=title_contains(ARC_ATTACK_ACTIVITY_KEY),
            priority=40,
            default_blocked_reason="已有 handler 框架，但缺少安全战斗场景确认",
        ),
    )

    def __init__(
        self,
        read_context,
        action_context: DailyActivityActionContext,
        *,
        registry: Iterable[DailyActivityHandlerRule] | None = None,
        skipped_sentinel: object | None = None,
        method_overrides: dict[str, Callable] | None = None,
    ):
        self.ui = ReadOnlyUIContext.coerce(read_context)
        self.actions = action_context
        self.registry = tuple(registry or self.ACTIVITY_HANDLER_REGISTRY)
        self.skipped_sentinel = skipped_sentinel
        self.method_overrides = method_overrides or {}
        self.snapshot = DailyActivitySnapshot(remaining_tasks=[])
        self.result_recorder = DailyResultRecorder(self.snapshot)
        self._screenshot_counter = 0

    @classmethod
    def from_task(cls, task, *, registry=None, skipped_sentinel=None, method_overrides=None):
        return cls(
            ReadOnlyUIContext(task),
            DailyActivityActionContext.from_task(task),
            registry=registry,
            skipped_sentinel=skipped_sentinel,
            method_overrides=method_overrides,
        )

    def _override(self, name):
        override = self.method_overrides.get(name)
        return override if callable(override) else None

    def complete_daily_activities(self):
        self.actions.log_info("正在处理每日活跃度任务")
        self.snapshot.cards_claimed = 0
        self.snapshot.handlers_completed = False
        self.snapshot.failure_reason = ""
        self.snapshot.skipped_reason = ""
        open_result = self.open_activity_panel_result()
        if not open_result.f1_panel_opened:
            return FlowResult.fail(open_result.reason or "f1_panel_not_opened", details=self.snapshot.details())
        if not open_result.daily_activity_panel_detected:
            return FlowResult.skip(open_result.reason, details=self.snapshot.details())

        analysis = self.analyze_daily_activity(panel_detected=True)
        self.record_daily_activity_analysis(analysis)
        if analysis.state == DailyActivityState.PANEL_NOT_FOUND:
            return FlowResult.fail(analysis.reason, details=self.snapshot.details())
        if analysis.state == DailyActivityState.NO_ACTION_NEEDED:
            self.actions.log_info(analysis.reason)
            return FlowResult.skip(analysis.reason, details=self.snapshot.details())

        page = analysis.page or DailyActivityPage()
        handler_completed = self.execute_available_activity_handlers_across_pages(page)
        self.snapshot.handlers_completed = bool(handler_completed)
        if handler_completed:
            self.actions.log_info("已完成可安全自动处理的每日活跃度任务")
            refreshed_page = self.refresh_daily_activity_page_after_handlers()
            if refreshed_page is None:
                return FlowResult.success(
                    "activity_handler_completed",
                    mutated=True,
                    details=self.result_recorder.details(),
                )
            total_claimed, _ = self.claim_completed_activity_cards_until_stable(refreshed_page)
            self.snapshot.cards_claimed = total_claimed
            return FlowResult.success(
                "activity_handler_completed",
                mutated=True,
                details=self.result_recorder.details(),
            )

        total_claimed, page = self.claim_completed_activity_cards_until_stable(page)
        if self.snapshot.failure_reason:
            return FlowResult.fail(self.snapshot.failure_reason, details=self.result_recorder.details())
        self.snapshot.cards_claimed = total_claimed
        if total_claimed:
            return FlowResult.success("activity_cards_claimed", mutated=True, details=self.result_recorder.details())

        self.record_remaining_activity_tasks(page)
        completed_simple_actions = self.completed_simple_activity_actions()
        if completed_simple_actions:
            self.actions.info_set("每日活跃度已尝试动作", "/".join(completed_simple_actions))

        self.actions.info_set("每日活跃度缺失特征", self.DAILY_ACTIVITY_MISSING_FEATURES)
        self.actions.log_info(
            "未检测到可领取的每日活跃度任务；"
            f"自动完成具体任务仍缺少特征: {self.DAILY_ACTIVITY_MISSING_FEATURES}"
        )
        self.snapshot.skipped_reason = analysis.reason
        return FlowResult.skip(analysis.reason, details=self.result_recorder.details())

    def claim_activity_rewards(self):
        self.actions.log_info("正在领取活跃度奖励")
        open_result = self.open_activity_panel_result()
        if not open_result.f1_panel_opened:
            return FlowResult.fail(open_result.reason or "f1_panel_not_opened", details=self.snapshot.details())
        if not open_result.daily_activity_panel_detected:
            return FlowResult.skip(open_result.reason, details=self.snapshot.details())

        analysis = self.analyze_daily_activity(panel_detected=True)
        self.record_daily_activity_analysis(analysis)

        if not self.claim_activity_milestone_rewards(analysis.page):
            reason = self.snapshot.reward_skip_reason or self.ACTIVITY_REWARD_UNAVAILABLE
            self.actions.info_set("活跃度奖励状态", reason)
            self.actions.log_info(reason)
            if self.snapshot.failure_reason:
                return FlowResult.fail(self.snapshot.failure_reason, details=self.result_recorder.details())
            self.snapshot.skipped_reason = reason
            return FlowResult.skip(reason, details=self.result_recorder.details())
        return FlowResult.success("activity_milestone_claimed", mutated=True, details=self.result_recorder.details())

    def open_activity_panel(self):
        return self.open_activity_panel_result().daily_activity_panel_detected

    def open_activity_panel_result(self):
        override = self._override("open_activity_panel_result")
        if override is not None:
            return override()

        detector = F1PanelDetector(self.ui)
        f1_panel_opened = False
        daily_tab_clicked = False

        try:
            self.actions.open_f1_panel()
            f1_panel_opened = True
        except Exception:
            result = detector.make_open_result(False, False, False)
            self.record_daily_panel_open_result(result)
            return result

        self.actions.info_set("每日活跃度目标栏目", f"第{self.DAILY_ACTIVITY_TAB_INDEX}栏目")
        tab_target = self.daily_activity_tab_target_box()
        tab_outcome = self._execute_gated_click(
            recognized_ui="daily_activity_second_tab",
            evidence_box=tab_target,
            post_verification="daily_activity_panel_detected",
            success_reason="daily_activity_tab_opened",
            verifier=lambda gate: self._verify_daily_activity_panel_after_tab_click(),
        )
        self._apply_outcome_to_snapshot(tab_outcome)
        daily_tab_clicked = bool(tab_outcome.done)
        result = detector.make_open_result(f1_panel_opened, daily_tab_clicked)
        self.record_daily_panel_open_result(result)
        if not result.daily_activity_panel_detected:
            self.actions.log_info(result.reason)
        return result

    def record_daily_panel_open_result(self, result: DailyPanelOpenResult):
        self.snapshot.panel_ready = bool(result.daily_activity_panel_detected)
        if result.reason and not result.daily_activity_panel_detected:
            self.snapshot.record_warning(result.reason)
        self.actions.info_set("F1面板已打开", str(result.f1_panel_opened))
        self.actions.info_set("每日栏目已点击", str(result.daily_tab_clicked))
        self.actions.info_set("每日面板特征命中", str(result.daily_activity_panel_detected))
        self.actions.info_set("UI布局", result.layout_profile)
        if result.reason:
            self.actions.info_set("每日面板打开状态", result.reason)

    def refresh_daily_activity_page_after_handlers(self):
        open_result = self.open_activity_panel_result()
        if not open_result.f1_panel_opened:
            return None
        if not open_result.daily_activity_panel_detected:
            self.actions.log_info(open_result.reason)
            return None
        analysis = self.analyze_daily_activity(panel_detected=True)
        self.record_daily_activity_analysis(analysis)
        if analysis.state == DailyActivityState.PANEL_NOT_FOUND:
            return None
        return analysis.page or DailyActivityPage()

    def claim_completed_activity_cards_until_stable(self, page: DailyActivityPage):
        total_claimed = 0
        while total_claimed < self.MAX_ACTIVITY_MISSION_CLAIMS:
            claimed = self.claim_completed_activity_card_rewards(page)
            if not claimed:
                break

            total_claimed += claimed
            self.actions.log_info(f"已领取 {total_claimed} 个已完成的每日活跃度任务")
            refreshed = self.analyze_daily_activity(panel_detected=True)
            self.record_daily_activity_analysis(refreshed)
            page = refreshed.page or DailyActivityPage()
            self.record_remaining_activity_tasks(page)

        return total_claimed, page

    def analyze_daily_activity(self, panel_detected=None):
        override = self._override("analyze_daily_activity")
        if override is not None:
            return override(panel_detected=panel_detected)
        return DailyActivityAnalyzer(self.ui, enable_text_ocr=True).analyze(panel_detected=panel_detected)

    def record_daily_activity_analysis(self, analysis):
        override = self._override("record_daily_activity_analysis")
        if override is not None:
            override(analysis)
            self.snapshot.analysis = analysis
            return
        self.snapshot.analysis = analysis
        self.snapshot.panel_ready = bool(
            getattr(analysis, "panel_detected", False) and getattr(analysis, "daily_tab_detected", False)
        )
        self.actions.info_set("每日活跃度状态", analysis.state.value)
        self.actions.info_set("每日活跃度状态原因", analysis.reason)
        page = analysis.page
        if not page:
            return
        self.snapshot.screenshot_id = self._new_screenshot_id("activity")
        self.snapshot.cards = [ActivityCardCandidate.from_card(card) for card in page.task_cards]
        self.actions.info_set("每日活跃度分数", str(page.activity_score))
        self.actions.info_set("可领取阶段奖励", f"{page.milestone_claimable_values}")
        self.actions.info_set("未解锁阶段奖励", f"{page.milestone_locked_values}")
        self.actions.info_set("每日任务领取按钮数", str(len(page.mission_claim_buttons)))
        self.actions.info_set("每日任务前往按钮数", str(len(page.go_buttons)))

    def completed_simple_activity_actions(self):
        success = self.actions.completed_task_keys()
        return [key for key in self.SIMPLE_ACTIVITY_ACTIONS if key in success]

    def execute_available_activity_handlers(self, page: DailyActivityPage):
        override = self._override("execute_available_activity_handlers")
        if override is not None:
            return override(page)

        completed = 0
        for card in page.task_cards:
            if card.action != "前往":
                continue

            handler = self.activity_handler_for_card(card)
            if handler is None:
                continue

            result = handler(card)
            flow = FlowResult.from_legacy(
                result,
                skipped_sentinel=self.skipped_sentinel,
                skip_reason=getattr(card, "blocked_reason", "") or self.activity_block_reason(self.activity_card_title(card)),
            )
            if flow.done:
                completed += 1

        return completed > 0

    def execute_available_activity_handlers_across_pages(self, first_page: DailyActivityPage):
        override = self._override("execute_available_activity_handlers_across_pages")
        if override is not None:
            return override(first_page)

        completed = self.execute_available_activity_handlers(first_page)
        if completed:
            return True
        if not first_page.task_cards:
            return False

        page = first_page
        previous_fingerprint = self.daily_activity_page_fingerprint(page)
        seen_fingerprints = {previous_fingerprint}
        for swipe_index in range(self.MAX_ACTIVITY_CARD_SWIPES):
            if not self.swipe_daily_activity_cards(page):
                break

            refreshed = self.analyze_daily_activity(panel_detected=True)
            self.record_daily_activity_analysis(refreshed)
            page = refreshed.page or DailyActivityPage()
            fingerprint = self.daily_activity_page_fingerprint(page)
            if fingerprint == previous_fingerprint:
                self.actions.info_set("每日任务列表滑动状态", f"未移动:{swipe_index + 1}")
                break
            if fingerprint in seen_fingerprints:
                self.actions.info_set("每日任务列表滑动状态", f"重复:{swipe_index + 1}")
                break

            seen_fingerprints.add(fingerprint)
            previous_fingerprint = fingerprint
            if self.execute_available_activity_handlers(page):
                return True
            self.record_remaining_activity_tasks(page)

        return False

    def swipe_daily_activity_cards(self, page: DailyActivityPage | None = None):
        override = self._override("swipe_daily_activity_cards")
        if override is not None:
            return override(page)

        try:
            start, end = self.daily_activity_card_swipe_points(page)
            self.actions.swipe(start[0], start[1], end[0], end[1], duration=0.9, after_sleep=1)
            self.snapshot.screenshot_id = self._new_screenshot_id("after_scroll")
            return True
        except Exception as exc:
            self.actions.info_set("每日任务列表滑动状态", f"失败:{exc!r}")
            return False

    def daily_activity_card_swipe_points(self, page: DailyActivityPage | None = None):
        boxes = self.daily_activity_card_swipe_boxes(page)
        if len(boxes) < 2:
            return self.daily_activity_card_fallback_swipe_points()

        start_box = self.daily_activity_card_swipe_start_box(boxes)
        if start_box is None:
            return self.daily_activity_card_fallback_swipe_points()
        end_box = boxes[0]
        y = self.daily_activity_card_swipe_y(start_box, end_box)
        start = (
            int(start_box.x + start_box.width * self.DAILY_ACTIVITY_CARD_SWIPE_START_X_IN_BOX),
            y,
        )
        end = (
            int(end_box.x + end_box.width * self.DAILY_ACTIVITY_CARD_SWIPE_END_X_IN_BOX),
            y,
        )
        if start[0] <= end[0]:
            return self.daily_activity_card_fallback_swipe_points()
        return start, end

    @staticmethod
    def daily_activity_card_swipe_boxes(page: DailyActivityPage | None):
        if page is None:
            return []
        boxes = []
        for card in page.task_cards:
            box = getattr(card, "box", None)
            width = int(getattr(box, "width", 0) or 0)
            height = int(getattr(box, "height", 0) or 0)
            if width <= 0 or height <= 0:
                continue
            boxes.append(box)
        return sorted(boxes, key=lambda box: int(getattr(box, "x", 0) or 0) + int(getattr(box, "width", 0) or 0) / 2)

    def daily_activity_card_swipe_start_box(self, boxes):
        screen_width = int(self.actions.width or 0)
        if screen_width > 0:
            right_edge_limit = screen_width * self.DAILY_ACTIVITY_CARD_RIGHT_EDGE_LIMIT
            safe_boxes = [
                box
                for box in boxes[1:]
                if int(getattr(box, "x", 0) or 0) + int(getattr(box, "width", 0) or 0) / 2 <= right_edge_limit
            ]
            if safe_boxes:
                return safe_boxes[-1]
            return None
        return boxes[-1]

    def daily_activity_card_swipe_y(self, start_box, end_box):
        top = max(int(getattr(start_box, "y", 0) or 0), int(getattr(end_box, "y", 0) or 0))
        height = min(int(getattr(start_box, "height", 0) or 0), int(getattr(end_box, "height", 0) or 0))
        return int(top + height * self.DAILY_ACTIVITY_CARD_SWIPE_Y_IN_BOX)

    def daily_activity_card_fallback_swipe_points(self):
        return (
            self.actions.ui_point(*self.DAILY_ACTIVITY_CARD_SWIPE_START),
            self.actions.ui_point(*self.DAILY_ACTIVITY_CARD_SWIPE_END),
        )

    def daily_activity_tab_target_box(self):
        width = max(1, int(self.actions.width or 0))
        height = max(1, int(self.actions.height or 0))
        tab_position = self.daily_activity_tab_position()
        center_x = int(width * tab_position[0])
        center_y = int(height * tab_position[1])
        box_width = max(1, int(width * self.DAILY_ACTIVITY_TAB_BOX_SIZE[0]))
        box_height = max(1, int(height * self.DAILY_ACTIVITY_TAB_BOX_SIZE[1]))
        return RegionBox(
            "daily_activity_second_tab",
            max(0, int(center_x - box_width / 2)),
            max(0, int(center_y - box_height / 2)),
            box_width,
            box_height,
            confidence=1.0,
        )

    def daily_activity_tab_position(self):
        if self.ui.get_ui_layout_profile() == LAYOUT_PROFILE_NATIVE_16_9:
            return self.NATIVE_16_9_DAILY_ACTIVITY_TAB_POSITION
        return self.DAILY_ACTIVITY_TAB_POSITION

    @staticmethod
    def daily_activity_page_fingerprint(page: DailyActivityPage):
        return tuple(
            (
                card.title,
                card.progress_text,
                card.action,
                int(getattr(getattr(card, "box", None), "x", 0) or 0),
            )
            for card in page.task_cards
        )

    def activity_handler_for_card(self, card):
        title = self.activity_card_title(card)
        rule = self.activity_rule_for_title(title)
        if rule is not None:
            card.handler_key = rule.handler_key
            return getattr(self, rule.handler_name)
        return None

    def build_activity_handle_intent(self, card):
        title = self.activity_card_title(card)
        rule = self.activity_rule_for_title(title)
        candidate = ActivityCardCandidate.from_card(
            card,
            card_key=getattr(rule, "handler_key", "") or str(getattr(card, "handler_key", "") or title),
        )
        notes = []
        gate_spec = None
        if rule is None:
            notes.append(self.activity_block_reason(title))
        else:
            target = getattr(card, "action_box", None)
            card_box = getattr(card, "box", None)
            state = str(getattr(card, "state", "") or "").strip()
            if str(getattr(card, "action", "") or "") != "前往":
                notes.append(f"{rule.handler_key}动作不是前往，未点击")
            elif card_box is None:
                notes.append(f"{rule.handler_key}缺少任务卡片区域")
            elif state != "go":
                notes.append(f"{rule.handler_key}任务状态未确认:{state or 'unknown'}")
            elif target is None:
                notes.append(f"{rule.handler_key}缺少前往按钮坐标")
            else:
                screenshot_id = self._ensure_current_screenshot_id("activity_intent")
                gate_spec = ActionGateSpec(
                    recognized_ui=str(getattr(target, "name", "") or "daily_activity_go_button"),
                    confidence=float(getattr(target, "confidence", candidate.confidence or 1.0) or 0.0),
                    screenshot_id=screenshot_id,
                    evidence_box=target,
                    target_policy="center",
                    target_offset=None,
                    min_confidence=0.8,
                    post_verification=f"{rule.handler_key}_entered",
                )
        intent = ActivityHandleIntent(
            handler_key=getattr(rule, "handler_key", "") if rule is not None else "",
            candidate=candidate,
            priority=int(getattr(rule, "priority", 100)) if rule is not None else 100,
            action_kind=str(getattr(card, "action", "") or ""),
            gate_spec=gate_spec,
            notes=tuple(notes),
        )
        return self.result_recorder.record_intent(intent)

    def execute_activity_handle_intent(self, intent: ActivityHandleIntent, *, verifier=None):
        if intent.gate_spec is None:
            reason = intent.notes[0] if intent.notes else "activity_intent_missing_gate_spec"
            return DailyActivityOutcome.skipped(reason, mutation_performed=False, mutation_verified=False)
        result = DailyActionGate(
            viewport_width=self.actions.width,
            viewport_height=self.actions.height,
            current_screenshot_id=self.snapshot.screenshot_id,
        ).execute_click(intent.gate_spec, self.actions, verifier=verifier)
        self.result_recorder.record_gate_result(result)
        return self.result_recorder.record_outcome(
            result.to_outcome(success_reason=f"{intent.handler_key}_gate_verified")
        )

    def _handle_coffee_activity(self, card):
        if not self.actions.has_daily_coffee_state_collector():
            result = DailyCoffeeRuntime(self.actions.ui).run(card)
            self.record_coffee_runtime_result(result)
            if not result.ok:
                card.blocked_reason = result.skip_reason
                self.actions.info_set("每日活动handler", f"{self.COFFEE_ACTIVITY_KEY}: {result.skip_reason}")
                self.actions.log_info(result.skip_reason)
                return FlowResult.skip(result.skip_reason)
            self.actions.ensure_daily_main()
            return FlowResult.success("coffee_runtime_completed", mutated=True)
        if not self.enter_activity_card(card, self.COFFEE_ACTIVITY_KEY):
            return FlowResult.skip(getattr(card, "blocked_reason", "") or "coffee_entry_missing")

        state = DailyCoffeeAnalyzer(self.actions).analyze()
        plan = DailyCoffeePlanner(
            max_supply_slots=self.coffee_max_supply_slots(),
            target_duration=self.coffee_supply_duration(),
        ).build_plan(state)
        self.record_coffee_plan(plan)
        if not plan.can_execute:
            card.blocked_reason = plan.skip_reason
            self.actions.log_info(plan.skip_reason)
            return FlowResult.skip(plan.skip_reason)

        if not self.execute_activity_plan_actions(plan.actions, self.COFFEE_ACTIVITY_KEY):
            reason = getattr(card, "blocked_reason", "") or "coffee_plan_action_failed"
            return FlowResult.fail(reason)
        self.actions.ensure_daily_main()
        return FlowResult.success("coffee_plan_completed", mutated=True)

    def _handle_gift_activity(self, card):
        target_names = self.gift_target_names()
        if not target_names:
            reason = DailyGiftPlanner.NO_TARGETS
            card.blocked_reason = reason
            self.actions.info_set("每日活动handler", f"{self.GIFT_ACTIVITY_KEY}: {reason}")
            self.actions.log_info(reason)
            return FlowResult.skip(reason)
        if not self.actions.has_daily_gift_state_collector():
            reason = DailyGiftPlanner.NO_STATE
            card.blocked_reason = reason
            self.actions.info_set("每日活动handler", f"{self.GIFT_ACTIVITY_KEY}: {reason}")
            self.actions.log_info(reason)
            return FlowResult.skip(reason)
        if not self.enter_activity_card(card, self.GIFT_ACTIVITY_KEY):
            return FlowResult.skip(getattr(card, "blocked_reason", "") or "gift_entry_missing")

        state = DailyGiftAnalyzer(self.actions).analyze()
        required_count = self.activity_required_remaining(card, default=1)
        plan = DailyGiftPlanner(target_names=target_names, required_count=required_count).build_plan(state)
        self.record_gift_plan(plan)
        if not plan.can_execute:
            card.blocked_reason = plan.skip_reason
            self.actions.log_info(plan.skip_reason)
            return FlowResult.skip(plan.skip_reason)

        if not self.execute_activity_plan_actions(plan.actions, self.GIFT_ACTIVITY_KEY):
            reason = getattr(card, "blocked_reason", "") or "gift_plan_action_failed"
            return FlowResult.fail(reason)
        self.actions.ensure_daily_main()
        return FlowResult.success("gift_plan_completed", mutated=True)

    def _handle_strengthen_activity(self, card):
        reason = "强化类任务仅允许单次明确安全动作；当前缺少稳定识别，未消耗材料"
        card.blocked_reason = reason
        self.actions.info_set("每日活动handler", f"{self.STRENGTHEN_ACTIVITY_KEY}: {reason}")
        self.actions.log_info(reason)
        return FlowResult.skip(reason)

    def _handle_arc_attack_activity(self, card):
        reason = "释放3次极轨攻击需要战斗场景和目标确认，当前仅记录 handler，不自动战斗"
        card.blocked_reason = reason
        self.actions.info_set("每日活动handler", f"{self.ARC_ATTACK_ACTIVITY_KEY}: {reason}")
        self.actions.log_info(reason)
        return FlowResult.skip(reason)

    def enter_activity_card(self, card, handler_name):
        intent = self.build_activity_handle_intent(card)
        if intent.gate_spec is None:
            reason = intent.notes[0] if intent.notes else f"{handler_name}缺少前往按钮坐标，未执行"
            card.blocked_reason = reason
            self.actions.info_set("每日活动handler", f"{handler_name}: {reason}")
            self.actions.log_info(reason)
            return False
        self.actions.log_info(f"进入{handler_name}")
        outcome = self.execute_activity_handle_intent(
            intent,
            verifier=lambda gate: self._verify_activity_entry_after_click(),
        )
        self._apply_outcome_to_snapshot(outcome)
        if outcome.done:
            return True
        reason = outcome.failure_reason or outcome.skipped_reason or "activity_entry_unverified"
        card.blocked_reason = reason
        self.actions.info_set("每日活动handler", f"{handler_name}: {reason}")
        self.actions.log_info(reason)
        return False

    def execute_activity_plan_actions(self, actions, handler_name):
        for action in actions:
            if action.kind == "close_popup":
                if action.target is not None:
                    self.actions.click(action.target)
                    self.actions.sleep(1)
                else:
                    self.close_activity_reward_popup()
                continue

            if action.target is None:
                self.actions.log_warning(f"{handler_name}动作缺少安全目标: {action.kind}")
                return False
            self.actions.log_info(f"{handler_name}执行动作: {action.kind}")
            self.actions.click(action.target)
            self.actions.sleep(1)
        return True

    def record_coffee_plan(self, plan):
        self.actions.info_set("咖啡店补货计划", plan.skip_reason if not plan.can_execute else "ready")
        if plan.selected_options:
            self.actions.info_set(
                "咖啡店补货选择",
                "/".join(option.identity for option in plan.selected_options),
            )

    def record_coffee_runtime_result(self, result):
        self.actions.info_set("咖啡店运行计划", result.skip_reason if not result.ok else "ready")
        self.actions.info_set("咖啡店真实补货", str(bool(result.real_purchase_performed)))
        if result.selected_options:
            self.actions.info_set(
                "咖啡店补货选择",
                "/".join(option.identity for option in result.selected_options),
            )
        if result.selected_actions:
            self.actions.info_set("咖啡店执行动作", "/".join(result.selected_actions))

    def record_gift_plan(self, plan):
        self.actions.info_set("赠礼计划", plan.skip_reason if not plan.can_execute else "ready")
        if plan.selected_gifts:
            self.actions.info_set(
                "赠礼选择",
                "/".join(option.identity for option in plan.selected_gifts),
            )

    def activity_rule_for_title(self, title):
        return resolve_activity_handler_rule(title, self.registry)

    def activity_rule_for_key(self, handler_key):
        for rule in self.registry:
            if rule.handler_key == handler_key:
                return rule
        return None

    def activity_title_matches_handler(self, title, handler_key):
        rule = self.activity_rule_for_key(handler_key)
        return bool(rule and rule.matches(title))

    def coffee_max_supply_slots(self):
        try:
            return int(self.actions.config.get("coffee_max_supply_slots", 0))
        except (TypeError, ValueError):
            return 0

    def coffee_supply_duration(self):
        return DailyCoffeePlanner.normalize_duration(
            self.actions.config.get("coffee_supply_duration", "24小时")
        )

    def gift_target_names(self):
        raw = self.actions.config.get("gift_target_characters", "")
        if isinstance(raw, (list, tuple)):
            return [str(name).strip() for name in raw if str(name).strip()]
        normalized = str(raw).replace("，", ",").replace("；", ",").replace(";", ",")
        return [name.strip() for name in normalized.split(",") if name.strip()]

    @staticmethod
    def activity_required_remaining(card, default=1):
        progress = (getattr(card, "progress_text", "") or "").strip()
        match = re.search(r"(\d+)\s*/\s*(\d+)", progress)
        if match:
            current, target = int(match.group(1)), int(match.group(2))
            return max(0, target - current)

        title = (getattr(card, "title", "") or "").strip()
        match = re.search(r"(\d+)\s*次", title)
        if match:
            return max(0, int(match.group(1)))
        return default

    def record_remaining_activity_tasks(self, page: DailyActivityPage):
        override = self._override("record_remaining_activity_tasks")
        if override is not None:
            remaining = override(page)
            self.snapshot.remaining_tasks = list(remaining or [])
            return remaining

        remaining = self.remaining_activity_tasks(page)
        self.snapshot.remaining_tasks = remaining
        if remaining:
            self.actions.info_set("剩余未自动完成每日任务", "；".join(remaining))
        return remaining

    def remaining_activity_tasks(self, page: DailyActivityPage):
        remaining = []
        for index, card in enumerate(page.task_cards, start=1):
            if card.action != "前往":
                continue

            title = self.activity_card_title(card) or f"未知任务{index}"
            reason = card.blocked_reason or self.activity_block_reason(title)
            remaining.append(f"{title}: {reason}")
        return remaining

    def activity_block_reason(self, title):
        rule = self.activity_rule_for_title(title)
        if rule is not None and rule.default_blocked_reason:
            return rule.default_blocked_reason
        if any(keyword in title for keyword in self.RESOURCE_ACTIVITY_KEYWORDS):
            return "资源消耗类任务默认不自动"
        return self.UNSUPPORTED_ACTIVITY_REASON

    @staticmethod
    def activity_card_title(card):
        return (getattr(card, "title", "") or "").strip()

    def claim_completed_activity_card_rewards(self, page: DailyActivityPage, max_clicks=1):
        override = self._override("claim_completed_activity_card_rewards")
        if override is not None:
            if max_clicks == 1:
                return override(page)
            try:
                return override(page, max_clicks=max_clicks)
            except TypeError:
                return override(page)

        max_clicks = 1 if max_clicks is None else max_clicks
        claimed = 0
        claimable_cards = [
            card for card in page.claimable_task_cards if self._is_valid_daily_activity_card(card)
        ]

        for card in claimable_cards[:max_clicks]:
            target = getattr(card, "action_box", None)
            if target is None:
                continue
            title = self.activity_card_title(card) or f"已完成任务{claimed + 1}"
            self.actions.log_info(f"领取每日任务卡片奖励: {title}")
            outcome = self._execute_gated_click(
                recognized_ui=str(getattr(target, "name", "") or "daily_activity_claim_button"),
                evidence_box=target,
                post_verification="daily_activity_claim_button_vanished",
                success_reason="activity_card_reward_claimed",
                verifier=lambda gate, before=target: self._verify_activity_claim_after_click(before),
            )
            self._apply_outcome_to_snapshot(outcome)
            if outcome.failed:
                return claimed
            if outcome.done:
                claimed += 1

        if max_clicks > 1 and claimed == max_clicks and len(claimable_cards) > max_clicks:
            self.actions.log_warning("每日活跃度任务领取达到上限，可能仍有可领取项目")
        return claimed

    def claim_activity_milestone_rewards(self, page: DailyActivityPage | None):
        override = self._override("claim_activity_milestone_rewards")
        if override is not None:
            claimed = bool(override(page))
            if not claimed and not self.snapshot.reward_skip_reason:
                self.snapshot.reward_skip_reason = self.ACTIVITY_REWARD_UNAVAILABLE
            return claimed

        self.snapshot.reward_skip_reason = ""
        page = page or DailyActivityPage()
        claimable = page.claimable_milestones
        if not claimable:
            self.snapshot.reward_skip_reason = self.ACTIVITY_REWARD_UNAVAILABLE
            return False
        if not self.should_claim_activity_milestones(page):
            self.snapshot.reward_skip_reason = self.ACTIVITY_REWARD_DEFERRED_UNTIL_FULL
            self.actions.info_set("待领取阶段奖励", f"{page.milestone_claimable_values}")
            self.actions.log_info(
                f"{self.ACTIVITY_REWARD_DEFERRED_UNTIL_FULL}: "
                f"score={page.activity_score}, claimable={page.milestone_claimable_values}"
            )
            return False

        target = claimable[0].box
        outcome = self._execute_gated_click(
            recognized_ui=str(getattr(target, "name", "") or "daily_activity_milestone_reward"),
            evidence_box=target,
            post_verification="daily_activity_milestone_reward_state_changed",
            success_reason="activity_milestone_claimed",
            verifier=lambda gate, before=target: self._verify_activity_milestone_after_click(before),
        )
        self._apply_outcome_to_snapshot(outcome)
        if outcome.failed:
            self.snapshot.reward_skip_reason = outcome.failure_reason or "activity_milestone_verification_failed"
            return False
        if outcome.skipped:
            self.snapshot.reward_skip_reason = outcome.skipped_reason or "activity_milestone_gate_rejected"
            return False
        self.actions.log_info(
            "已点击一个顶部阶段奖励入口，"
            f"当前可领取阶段: {page.milestone_claimable_values}"
        )
        return True

    def close_activity_reward_popup(self):
        override = self._override("close_activity_reward_popup")
        if override is not None:
            return override()

        try:
            self.actions.send_key("esc", after_sleep=1)
            self.actions.log_info("已按 ESC 关闭活跃度奖励弹窗")
            return True
        except Exception as exc:
            self.actions.log_warning(f"关闭活跃度奖励弹窗失败，尝试前台 ESC fallback: {exc}")
            return self.actions.send_foreground_key("esc", after_sleep=1)

    def should_claim_activity_milestones(self, page: DailyActivityPage):
        if self.claim_partial_milestones_enabled():
            return True
        return page.activity_score is not None and page.activity_score >= self.ACTIVITY_SCORE_FULL

    def claim_partial_milestones_enabled(self):
        return bool(self.actions.config.get("claim_partial_milestones", False))

    def _new_screenshot_id(self, prefix: str):
        self._screenshot_counter += 1
        return f"{prefix}-{self._screenshot_counter}"

    def _ensure_current_screenshot_id(self, prefix: str = "activity"):
        if not self.snapshot.screenshot_id:
            self.snapshot.screenshot_id = self._new_screenshot_id(prefix)
        return self.snapshot.screenshot_id

    def _execute_gated_click(
        self,
        *,
        recognized_ui: str,
        evidence_box,
        post_verification: str,
        success_reason: str,
        verifier,
        min_confidence: float = 0.8,
    ):
        screenshot_id = self._ensure_current_screenshot_id("activity")
        confidence = float(getattr(evidence_box, "confidence", 1.0) or 0.0) if evidence_box is not None else 0.0
        spec = ActionGateSpec(
            recognized_ui=recognized_ui,
            confidence=confidence,
            screenshot_id=screenshot_id,
            evidence_box=evidence_box,
            target_policy="center",
            min_confidence=min_confidence,
            post_verification=post_verification,
        )
        gate_result = DailyActionGate(
            viewport_width=self.actions.width,
            viewport_height=self.actions.height,
            current_screenshot_id=self.snapshot.screenshot_id,
        ).execute_click(
            spec,
            self.actions,
            verifier=lambda gate: self._run_post_action_verifier(verifier, gate),
        )
        self.result_recorder.record_gate_result(gate_result)
        return self.result_recorder.record_outcome(gate_result.to_outcome(success_reason=success_reason))

    def _run_post_action_verifier(self, verifier, gate):
        self.actions.sleep(1)
        self.actions.next_frame()
        verification = verifier(gate)
        if isinstance(verification, (tuple, list)):
            verified = bool(verification[0]) if verification else False
        else:
            verified = bool(verification)
        after_screenshot_id = self._new_screenshot_id("after_action")
        self.snapshot.screenshot_id = after_screenshot_id
        return verified, after_screenshot_id

    def _apply_outcome_to_snapshot(self, outcome: DailyActivityOutcome):
        self.snapshot.mutation_performed = bool(self.snapshot.mutation_performed or outcome.mutation_performed)
        self.snapshot.mutation_verified = bool(self.snapshot.mutation_verified or outcome.mutation_verified)
        if outcome.skipped_reason:
            self.snapshot.skipped_reason = outcome.skipped_reason
        if outcome.failure_reason:
            self.snapshot.failure_reason = outcome.failure_reason

    def _verify_activity_claim_after_click(self, before_box):
        refreshed = self._refresh_activity_analysis_after_click()
        page = refreshed.page if refreshed is not None else None
        if page is None:
            return False
        return not any(
            self._same_box(before_box, getattr(card, "action_box", None))
            for card in page.claimable_task_cards
        )

    def _verify_activity_milestone_after_click(self, before_box):
        self.close_activity_reward_popup()
        refreshed = self._refresh_activity_analysis_after_click()
        page = refreshed.page if refreshed is not None else None
        if page is None:
            return False
        return not any(
            reward.claimable and self._same_box(before_box, getattr(reward, "box", None))
            for reward in page.claimable_milestones
        )

    def _verify_activity_entry_after_click(self):
        self.actions.next_frame()
        detector = F1PanelDetector(self.ui)
        entered = not bool(detector.find_daily_activity_panel())
        self.snapshot.screenshot_id = self._new_screenshot_id("after_entry")
        return entered, self.snapshot.screenshot_id

    def _verify_daily_activity_panel_after_tab_click(self):
        for attempt in range(self.DAILY_PANEL_VERIFY_ATTEMPTS):
            if F1PanelDetector(self.ui).find_daily_activity_panel():
                return True
            if self._daily_activity_page_content_visible():
                return True
            if attempt < self.DAILY_PANEL_VERIFY_ATTEMPTS - 1:
                self.actions.sleep(self.DAILY_PANEL_VERIFY_RETRY_SLEEP)
                self.actions.next_frame()
        return False

    def _daily_activity_page_content_visible(self):
        page = DailyActivityAnalyzer(self.ui, enable_text_ocr=True).analyze_page()
        return bool(
            getattr(page, "activity_score", None) is not None
            or any(self._is_valid_daily_activity_card(card) for card in getattr(page, "task_cards", None) or [])
        )

    @classmethod
    def _is_valid_daily_activity_card(cls, card):
        title = (getattr(card, "title", "") or "").strip()
        progress = (getattr(card, "progress_text", "") or "").strip()
        reward_points = getattr(card, "reward_points", None)
        button_text = (getattr(card, "button_text", "") or "").strip()
        action = (getattr(card, "action", "") or "").strip()
        if not title:
            return False
        if progress:
            return True
        if reward_points is not None:
            return True
        if action in {"领取", "完成", "前往"} and any(marker in title for marker in cls.DAILY_ACTIVITY_TITLE_MARKERS):
            return True
        return action in {"领取", "完成", "前往"} and button_text in {"领取", "完成", "前往"}

    def _refresh_activity_analysis_after_click(self):
        self.actions.next_frame()
        analysis = self.analyze_daily_activity(panel_detected=True)
        self.record_daily_activity_analysis(analysis)
        return analysis

    @staticmethod
    def _same_box(left, right, tolerance=12):
        if left is None or right is None:
            return False
        try:
            left_center = (
                int(getattr(left, "x", 0) or 0) + int(getattr(left, "width", 0) or 0) / 2,
                int(getattr(left, "y", 0) or 0) + int(getattr(left, "height", 0) or 0) / 2,
            )
            right_center = (
                int(getattr(right, "x", 0) or 0) + int(getattr(right, "width", 0) or 0) / 2,
                int(getattr(right, "y", 0) or 0) + int(getattr(right, "height", 0) or 0) / 2,
            )
        except (TypeError, ValueError):
            return False
        return (
            abs(left_center[0] - right_center[0]) <= tolerance
            and abs(left_center[1] - right_center[1]) <= tolerance
        )
