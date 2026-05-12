from dataclasses import dataclass, field
from typing import Any

from src.tasks.DailyActionGate import DailyActionGate
from src.tasks.DailyActivityAnalyzer import DailyActivityPage, DailyTaskCard, RegionBox
from src.tasks.DailyActivityModels import ActionGateSpec


def _box_to_dict(box):
    if box is None:
        return None
    return {
        "name": str(getattr(box, "name", "") or ""),
        "x": int(getattr(box, "x", 0) or 0),
        "y": int(getattr(box, "y", 0) or 0),
        "width": int(getattr(box, "width", 0) or 0),
        "height": int(getattr(box, "height", 0) or 0),
        "confidence": float(getattr(box, "confidence", 1.0) or 0.0),
    }


@dataclass
class DailyTaskItemRecord:
    title: str = ""
    progress_text: str = ""
    action: str = ""
    button_text: str = ""
    state: str = ""
    eligible: bool = False
    skipped: bool = False
    blocker_reason: str = ""
    row_evidence: dict[str, Any] | None = None
    button_evidence: dict[str, Any] | None = None
    confidence: float = 0.0
    screenshot_id: str = ""
    gate_result: dict[str, Any] | None = None
    target_point: list[int] | None = None
    post_verification: dict[str, Any] = field(default_factory=dict)
    handler_completed: bool = False
    task_completed: bool = False
    mutation_performed: bool = False
    mutation_verified: bool = False
    selected_character: str = ""
    selected_item: str = ""
    sent_total: int = 0
    task_reward_claimed: bool = False
    activity_rewards_claimed: int = 0
    claimable_rewards_remaining: int | None = None
    claimable_rewards_reason: str = ""

    def to_dict(self):
        return {
            "title": self.title,
            "progress_text": self.progress_text,
            "action": self.action,
            "button_text": self.button_text,
            "state": self.state,
            "eligible": self.eligible,
            "skipped": self.skipped,
            "blocker_reason": self.blocker_reason,
            "row_evidence": self.row_evidence,
            "button_evidence": self.button_evidence,
            "confidence": self.confidence,
            "screenshot_id": self.screenshot_id,
            "gate_result": self.gate_result,
            "target_point": self.target_point,
            "post_verification": dict(self.post_verification),
            "handler_completed": self.handler_completed,
            "task_completed": self.task_completed,
            "mutation_performed": self.mutation_performed,
            "mutation_verified": self.mutation_verified,
            "selected_character": self.selected_character,
            "selected_item": self.selected_item,
            "sent_total": self.sent_total,
            "task_reward_claimed": self.task_reward_claimed,
            "activity_rewards_claimed": self.activity_rewards_claimed,
            "claimable_rewards_remaining": self.claimable_rewards_remaining,
            "claimable_rewards_reason": self.claimable_rewards_reason,
        }


@dataclass
class GiftDefaultSendResult:
    ok: bool = False
    reason: str = ""
    mutation_performed: bool = False
    mutation_verified: bool = False
    handler_completed: bool = False
    selected_character: str = ""
    selected_item: str = ""
    sent_total: int = 0
    actions: list[dict[str, Any]] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self):
        return {
            "ok": self.ok,
            "reason": self.reason,
            "mutation_performed": self.mutation_performed,
            "mutation_verified": self.mutation_verified,
            "handler_completed": self.handler_completed,
            "selected_character": self.selected_character,
            "selected_item": self.selected_item,
            "sent_total": self.sent_total,
            "actions": list(self.actions),
            "details": dict(self.details),
        }


class _ReliableClickContext:
    """Click adapter that keeps ActionGate validation but uses stable PC input."""

    def __init__(self, actions):
        self.actions = actions

    def click(self, x, y):
        x = int(x)
        y = int(y)

        def perform_click():
            click = getattr(self.actions, "click", None)
            if not callable(click):
                raise AttributeError("action context does not provide click()")
            try:
                return click(x, y, after_sleep=1, move=True, down_time=0.01)
            except TypeError:
                return click(x, y)

        operate = getattr(self.actions, "operate", None)
        if not callable(operate):
            ui = getattr(self.actions, "ui", None)
            operate = getattr(ui, "operate", None)
        if callable(operate) and operate(perform_click, block=True):
            return None
        return perform_click()


class DailyGiftDefaultRuntime:
    """Minimal default-character gift sender for the daily gift task."""

    GIFT_PAGE_MARKERS = ("羁遇", "赠礼")
    GIFT_GRID_MARKERS = ("角色喜爱", "今日还能赠送")
    PHONE_MENU_GIFT_ENTRY_TEXT = "羁遇"
    CONFIRM_TEXTS = ("确认", "确定")

    def __init__(self, flow, *, min_confidence: float = 0.7):
        self.flow = flow
        self.min_confidence = float(min_confidence)
        self.actions: list[dict[str, Any]] = []
        self._screenshot_counter = 0

    def verify_gift_page_reached(self):
        boxes = self._ocr_all()
        texts = self._texts(boxes)
        return all(any(marker in text for text in texts) for marker in self.GIFT_PAGE_MARKERS)

    def enter_from_phone_menu(self):
        open_details = self._open_phone_menu()
        boxes = self._ocr_all()
        entry_box = self._find_text_box(boxes, self.PHONE_MENU_GIFT_ENTRY_TEXT)
        if entry_box is None:
            retry_details = self._reopen_phone_menu_after_missing_entry()
            if retry_details.get("attempted"):
                boxes = self._ocr_all()
                entry_box = self._find_text_box(boxes, self.PHONE_MENU_GIFT_ENTRY_TEXT)
                open_details = {
                    "attempted": True,
                    "ok": bool(retry_details.get("ok")),
                    "method": str(retry_details.get("method") or open_details.get("method") or ""),
                    "reason": str(retry_details.get("reason") or ""),
                    "attempts": [open_details, retry_details],
                }
        if entry_box is None:
            return {
                "ok": False,
                "reason": "gift_phone_menu_entry_not_found",
                "open": open_details,
                "entry_box": None,
                "actions": [],
            }

        gate = self._click_with_gate(
            entry_box,
            recognized_ui="gift_phone_menu_entry_ji_yu",
            post_verification="gift_page_reached",
            verifier=self.verify_gift_page_reached,
        )
        return {
            "ok": bool(gate.get("verified")),
            "reason": "" if gate.get("verified") else gate.get("failure_reason") or gate.get("reject_reason") or "gift_page_not_reached",
            "open": open_details,
            "entry_box": _box_to_dict(entry_box),
            "actions": [gate],
        }

    def send_default_gift(self, *, direct_verify: bool = False):
        if not self.verify_gift_page_reached():
            return self._blocked("gift_page_not_reached")

        selected_character = self._selected_character_name() or "default_visible"
        if not self._ensure_gift_tab_selected():
            return self._blocked("gift_page_not_reached", selected_character=selected_character)

        item_box, selected_item = self._first_gift_item()
        if item_box is None:
            return self._blocked("gift_item_not_found", selected_character=selected_character)

        item_gate = self._click_with_gate(
            item_box,
            recognized_ui="gift_default_item",
            post_verification="gift_item_selected",
            verifier=lambda: self._send_button_box() is not None,
            target_offset=(0, -90),
        )
        if not item_gate.get("verified"):
            return self._blocked(
                item_gate.get("failure_reason") or item_gate.get("reject_reason") or "gift_item_not_found",
                selected_character=selected_character,
                selected_item=selected_item,
                actions=[item_gate],
            )

        send_box = self._send_button_box()
        if send_box is None:
            return self._blocked(
                "gift_send_button_not_found",
                selected_character=selected_character,
                selected_item=selected_item,
                actions=[item_gate],
            )

        send_gate = self._click_with_gate(
            send_box,
            recognized_ui="gift_send_button",
            post_verification="gift_send_clicked",
            verifier=lambda: True,
        )
        mutation_performed = bool(send_gate.get("executed"))
        if not mutation_performed:
            return GiftDefaultSendResult(
                ok=False,
                reason=send_gate.get("failure_reason") or send_gate.get("reject_reason") or "gift_send_button_not_found",
                mutation_performed=False,
                mutation_verified=False,
                handler_completed=True,
                selected_character=selected_character,
                selected_item=selected_item,
                sent_total=0,
                actions=[item_gate, send_gate],
            )

        confirm_gate = self._confirm_if_present()
        actions = [item_gate, send_gate]
        if confirm_gate:
            actions.append(confirm_gate)
            if not confirm_gate.get("executed"):
                return GiftDefaultSendResult(
                    ok=False,
                    reason=confirm_gate.get("failure_reason") or confirm_gate.get("reject_reason") or "gift_confirm_failed",
                    mutation_performed=True,
                    mutation_verified=False,
                    handler_completed=True,
                    selected_character=selected_character,
                    selected_item=selected_item,
                    sent_total=0,
                    actions=actions,
                )

        direct_details: dict[str, Any] = {}
        mutation_verified = False
        reason = "gift_send_clicked"
        if direct_verify:
            direct_details = self._verify_direct_send_completed()
            mutation_verified = bool(direct_details.get("verified"))
            reason = "gift_send_verified" if mutation_verified else str(
                direct_details.get("reason") or "gift_direct_post_verification_failed"
            )

        return GiftDefaultSendResult(
            ok=True if not direct_verify else mutation_verified,
            reason=reason,
            mutation_performed=True,
            mutation_verified=mutation_verified,
            handler_completed=True,
            selected_character=selected_character,
            selected_item=selected_item,
            sent_total=1,
            actions=actions,
            details=direct_details,
        )

    def _open_phone_menu(self):
        world = self._ensure_world_before_phone_menu()
        if world.get("attempted") and not world.get("ok"):
            return {
                "attempted": True,
                "ok": False,
                "method": "ensure_daily_main",
                "world": world,
                "reason": str(world.get("reason") or "phone_menu_world_not_ready"),
            }

        source = getattr(getattr(self.flow.actions, "ui", None), "source", None)
        opener = getattr(source, "openESCpanel", None)
        if callable(opener):
            try:
                panel = opener()
                self.flow.actions.sleep(1)
                self.flow.actions.next_frame()
                return {
                    "attempted": True,
                    "ok": True,
                    "method": "openESCpanel",
                    "panel": _box_to_dict(panel),
                    "world": world,
                    "reason": "",
                }
            except Exception as exc:
                fallback = self._open_phone_menu_by_key(ensure_world=False, world_details=world)
                fallback["openESCpanel_error"] = repr(exc)
                return fallback
        return self._open_phone_menu_by_key(ensure_world=False, world_details=world)

    def _reopen_phone_menu_after_missing_entry(self):
        close_result = self._send_escape_key("close_stale_panel_before_phone_menu_retry")
        retry = self._open_phone_menu_by_key(ensure_world=True)
        retry["stale_panel_close"] = close_result
        return retry

    def _ensure_world_before_phone_menu(self):
        ensure = getattr(self.flow.actions, "ensure_daily_main", None)
        if not callable(ensure):
            return {
                "attempted": False,
                "ok": None,
                "method": "",
                "reason": "ensure_daily_main_unavailable",
            }
        try:
            result = ensure()
            self.flow.actions.sleep(0.5)
            self.flow.actions.next_frame()
            ok = result is not False
            return {
                "attempted": True,
                "ok": ok,
                "method": "ensure_daily_main",
                "reason": "" if ok else "ensure_daily_main_returned_false",
            }
        except Exception as exc:
            return {
                "attempted": True,
                "ok": False,
                "method": "ensure_daily_main",
                "reason": repr(exc),
            }

    def _open_phone_menu_by_key(self, *, ensure_world: bool = True, world_details: dict[str, Any] | None = None):
        world = dict(world_details or {})
        if ensure_world:
            world = self._ensure_world_before_phone_menu()
            if world.get("attempted") and not world.get("ok"):
                return {
                    "attempted": True,
                    "ok": False,
                    "method": "ensure_daily_main",
                    "world": world,
                    "reason": str(world.get("reason") or "phone_menu_world_not_ready"),
                }

        last_error = ""
        key_result = self._send_escape_key("open_phone_menu")
        if key_result.get("ok"):
            return {
                "attempted": True,
                "ok": True,
                "method": str(key_result.get("method") or ""),
                "world": world,
                "reason": "",
            }
        last_error = str(key_result.get("reason") or "")

        return {
            "attempted": True,
            "ok": False,
            "method": "",
            "world": world,
            "reason": last_error or "phone_menu_open_method_unavailable",
        }

    def _send_escape_key(self, action: str):
        last_error = ""
        for name in ("send_foreground_key", "send_key"):
            sender = getattr(self.flow.actions, name, None)
            if not callable(sender):
                continue
            try:
                try:
                    sent = sender("esc", after_sleep=1)
                except TypeError:
                    sent = sender("esc")
                self.flow.actions.sleep(1)
                self.flow.actions.next_frame()
                if sent is False:
                    last_error = f"{name}:esc_key_not_accepted"
                    continue
                return {
                    "attempted": True,
                    "ok": True,
                    "method": name,
                    "action": action,
                    "reason": "",
                }
            except Exception as exc:
                last_error = repr(exc)
        return {
            "attempted": True,
            "ok": False,
            "method": "",
            "action": action,
            "reason": last_error or "phone_menu_open_method_unavailable",
        }

    def _verify_direct_send_completed(self):
        self.flow.actions.sleep(1)
        boxes = self._ocr_all()
        page_reached = all(any(marker in text for text in self._texts(boxes)) for marker in self.GIFT_PAGE_MARKERS)
        confirm_present = any(self._find_text_box(boxes, text, min_y_ratio=0.35) is not None for text in self.CONFIRM_TEXTS)
        verified = bool(page_reached and not confirm_present)
        return {
            "verified": verified,
            "post_action_result": "gift_send_observable" if verified else "gift_send_observable_not_confirmed",
            "reason": "" if verified else "gift_direct_post_verification_failed",
            "gift_page_reached": page_reached,
            "confirm_dialog_present": confirm_present,
        }

    def _ensure_gift_tab_selected(self):
        boxes = self._ocr_all()
        if self._has_gift_grid(boxes):
            return True
        tab = self._find_text_box(boxes, "赠礼", min_x_ratio=0.60, max_y_ratio=0.25)
        if tab is None:
            return False
        gate = self._click_with_gate(
            tab,
            recognized_ui="gift_tab",
            post_verification="gift_tab_selected",
            verifier=lambda: self._has_gift_grid(self._ocr_all()),
        )
        return bool(gate.get("verified"))

    def _selected_character_name(self):
        boxes = self._ocr_all()
        width = self.flow.actions.width
        height = self.flow.actions.height
        ignored = {"羁遇", "详细", "赠礼", "好感度", "资料", "互动", "角色喜爱"}
        candidates = []
        for box in boxes:
            text = self._box_text(box)
            if not text or text in ignored or any(ch.isdigit() for ch in text):
                continue
            x = int(getattr(box, "x", 0) or 0)
            y = int(getattr(box, "y", 0) or 0)
            box_width = int(getattr(box, "width", 0) or 0)
            box_height = int(getattr(box, "height", 0) or 0)
            if x < width * 0.45 or y < height * 0.15 or y > height * 0.35:
                continue
            candidates.append((box_height * box_width, text))
        if not candidates:
            return ""
        return max(candidates, key=lambda item: item[0])[1]

    def _first_gift_item(self):
        boxes = self._ocr_all()
        width = self.flow.actions.width
        height = self.flow.actions.height
        numeric = []
        for box in boxes:
            text = self._box_text(box)
            if not text.isdigit():
                continue
            x = int(getattr(box, "x", 0) or 0)
            y = int(getattr(box, "y", 0) or 0)
            if not (width * 0.50 <= x <= width * 0.88 and height * 0.38 <= y <= height * 0.72):
                continue
            value = int(text)
            confidence = float(getattr(box, "confidence", 1.0) or 0.0)
            if confidence < self.min_confidence:
                continue
            priority = 0 if value >= 300 else 1
            numeric.append((priority, y, x, box, text))
        if not numeric:
            return None, ""
        _, _, _, evidence, text = sorted(numeric, key=lambda item: item[:3])[0]
        item_box = RegionBox(
            "gift_item_affinity",
            int(getattr(evidence, "x", 0) or 0),
            int(getattr(evidence, "y", 0) or 0),
            max(1, int(getattr(evidence, "width", 1) or 1)),
            max(1, int(getattr(evidence, "height", 1) or 1)),
            confidence=float(getattr(evidence, "confidence", 1.0) or 0.0),
        )
        return item_box, f"affinity:{text}"

    def _send_button_box(self):
        boxes = self._ocr_all()
        candidates = []
        width = self.flow.actions.width
        height = self.flow.actions.height
        for box in boxes:
            text = self._box_text(box)
            if "赠送" not in text:
                continue
            x = int(getattr(box, "x", 0) or 0)
            y = int(getattr(box, "y", 0) or 0)
            if x < width * 0.55 or y < height * 0.70:
                continue
            candidates.append((y, x, box))
        if not candidates:
            return None
        return sorted(candidates, key=lambda item: (item[0], item[1]))[0][2]

    def _confirm_if_present(self):
        boxes = self._ocr_all()
        confirm = None
        for text in self.CONFIRM_TEXTS:
            confirm = self._find_text_box(boxes, text, min_y_ratio=0.35)
            if confirm is not None:
                break
        if confirm is None:
            return None
        return self._click_with_gate(
            confirm,
            recognized_ui="gift_confirm_button",
            post_verification="gift_confirm_clicked",
            verifier=lambda: True,
        )

    def _click_with_gate(
        self,
        evidence_box,
        *,
        recognized_ui: str,
        post_verification: str,
        verifier,
        target_offset: tuple[int, int] | None = None,
    ):
        screenshot_id = self._new_screenshot_id(recognized_ui)
        spec = ActionGateSpec(
            recognized_ui=recognized_ui,
            confidence=float(getattr(evidence_box, "confidence", 1.0) or 0.0),
            screenshot_id=screenshot_id,
            evidence_box=evidence_box,
            target_policy="center",
            target_offset=target_offset,
            min_confidence=self.min_confidence,
            post_verification=post_verification,
        )
        gate = DailyActionGate(
            viewport_width=self.flow.actions.width,
            viewport_height=self.flow.actions.height,
            current_screenshot_id=screenshot_id,
        ).evaluate(spec)
        details = gate.to_details()
        details["recognized_ui"] = recognized_ui
        details["post_verification"] = post_verification
        if not gate.allowed:
            self.actions.append(details)
            return details
        try:
            _ReliableClickContext(self.flow.actions).click(*gate.target_point)
            self.flow.actions.sleep(1)
            self.flow.actions.next_frame()
        except Exception as exc:
            details.update(
                {
                    "executed": False,
                    "verified": False,
                    "mutation_performed": False,
                    "mutation_verified": False,
                    "failure_reason": f"click_failed:{exc!r}",
                }
            )
            self.actions.append(details)
            return details
        verified = bool(verifier())
        details.update(
            {
                "executed": True,
                "verified": verified,
                "mutation_performed": True,
                "mutation_verified": verified,
                "failure_reason": "" if verified else "post_verification_failed",
                "after_screenshot_id": self._new_screenshot_id(f"after_{recognized_ui}"),
            }
        )
        self.actions.append(details)
        return details

    def _new_screenshot_id(self, prefix):
        self._screenshot_counter += 1
        return f"{prefix}-{self._screenshot_counter}"

    def _ocr_all(self):
        self.flow.actions.next_frame()
        result = self.flow.ui.ocr_ui(0, 0, 1, 1)
        return list(result or [])

    def _find_text_box(self, boxes, needle, *, min_x_ratio=0.0, max_y_ratio=1.0, min_y_ratio=0.0):
        width = self.flow.actions.width
        height = self.flow.actions.height
        candidates = []
        for box in boxes:
            text = self._box_text(box)
            if needle not in text:
                continue
            confidence = float(getattr(box, "confidence", 1.0) or 0.0)
            if confidence < self.min_confidence:
                continue
            x = int(getattr(box, "x", 0) or 0)
            y = int(getattr(box, "y", 0) or 0)
            if x < width * min_x_ratio or y > height * max_y_ratio or y < height * min_y_ratio:
                continue
            candidates.append((y, x, box))
        if not candidates:
            return None
        return sorted(candidates, key=lambda item: (item[0], item[1]))[0][2]

    def _has_gift_grid(self, boxes):
        texts = self._texts(boxes)
        return all(any(marker in text for text in texts) for marker in self.GIFT_GRID_MARKERS)

    def _texts(self, boxes):
        return [self._box_text(box) for box in boxes]

    @staticmethod
    def _box_text(box):
        return str(getattr(box, "text", "") or getattr(box, "name", "") or "").strip()

    @staticmethod
    def _blocked(reason, *, selected_character="", selected_item="", actions=None):
        return GiftDefaultSendResult(
            ok=False,
            reason=reason,
            mutation_performed=False,
            mutation_verified=False,
            handler_completed=bool(selected_character),
            selected_character=selected_character,
            selected_item=selected_item,
            sent_total=0,
            actions=list(actions or []),
        )


class DailyTaskItemActionRunner:
    """Runs the safe subset of F1 daily task item actions."""

    ACTIONS = {"前往", "完成", "领取"}
    MUTATING_ACTIONS = {"完成", "领取"}
    GIFT_KEYWORDS = ("赠送", "礼物")
    BATTLE_KEYWORDS = ("击败", "敌人", "极轨", "攻击", "战斗")
    RESOURCE_KEYWORDS = (
        "消耗",
        "本性像素",
        "都市",
        "强化",
        "提升",
        "弧盘",
        "购买",
        "买",
        "咖啡",
        "一咖舍",
        "补货",
    )

    def __init__(
        self,
        flow,
        *,
        dry_run: bool = True,
        min_confidence: float = 0.8,
        allow_go_actions: bool = False,
        max_actions: int = 1,
        gift_runtime_factory=None,
        gift_only: bool = False,
    ):
        self.flow = flow
        self.dry_run = bool(dry_run)
        self.min_confidence = float(min_confidence)
        self.allow_go_actions = bool(allow_go_actions)
        self.max_actions = int(max_actions or 1)
        self.gift_runtime_factory = gift_runtime_factory or (lambda flow: DailyGiftDefaultRuntime(flow))
        self.gift_only = bool(gift_only)
        self._last_verification: dict[str, Any] = {}

    def run(self):
        summary = self._empty_summary()
        summary["preflight"] = self._recover_world_before_panel()
        open_result = self.flow.open_activity_panel_result()
        summary["panel"] = self._panel_details(open_result)
        if not getattr(open_result, "daily_activity_panel_detected", False):
            summary["panel_recovery"] = self._recover_after_panel_open_failure(open_result)
            if summary["panel_recovery"].get("attempted"):
                open_result = self.flow.open_activity_panel_result()
                summary["panel"] = self._panel_details(open_result)
        if not getattr(open_result, "daily_activity_panel_detected", False):
            summary["ok"] = False
            summary["blockers"].append(open_result.reason or "daily_activity_panel_not_confirmed")
            return summary

        analysis = self.flow.analyze_daily_activity(panel_detected=True)
        self.flow.record_daily_activity_analysis(analysis)
        page = analysis.page or DailyActivityPage()
        summary["task_list_roi_confirmed"] = bool(page.task_cards or page.go_buttons or page.mission_claim_buttons)
        if not summary["task_list_roi_confirmed"]:
            summary["skipped"].append({"reason": "task_list_roi_not_confirmed"})
            self._populate_absent_gift_summary(summary, page)
            summary["ok"] = True
            return summary

        cards = list(page.task_cards)
        duplicate_keys = self._duplicate_keys(cards)
        records = [self._record_for_card(card, duplicate_keys=duplicate_keys) for card in cards]
        summary["items"] = [record.to_dict() for record in records]
        self._populate_record_summary(summary, records, page=page)
        if self.dry_run:
            summary["ok"] = True
            return summary

        executed = 0
        for index, (card, record) in enumerate(zip(cards, records)):
            if not record.eligible:
                continue
            if executed >= self.max_actions:
                record.skipped = True
                record.blocker_reason = "max_actions_reached"
                continue
            if executed:
                record.skipped = True
                record.blocker_reason = "stale_after_previous_action"
                continue
            self._execute_card(card, record)
            executed += 1
            if record.mutation_performed and not record.mutation_verified:
                summary["ok"] = False

        if summary["ok"] is None:
            summary["ok"] = True
        self._populate_record_summary(summary, records, page=page)
        return summary

    @staticmethod
    def _empty_summary():
        return {
            "ok": None,
            "preflight": {},
            "task_list_roi_confirmed": False,
            "items": [],
            "actions": [],
            "skipped": [],
            "blockers": [],
            "mutation_performed": False,
            "mutation_verified": False,
            "handler_completed": False,
            "task_completed": False,
        }

    @staticmethod
    def _panel_details(open_result):
        return {
            "f1_panel_opened": bool(getattr(open_result, "f1_panel_opened", False)),
            "daily_activity_panel_detected": bool(getattr(open_result, "daily_activity_panel_detected", False)),
            "daily_tab_clicked": bool(getattr(open_result, "daily_tab_clicked", False)),
            "reason": str(getattr(open_result, "reason", "") or ""),
        }

    def _recover_world_before_panel(self):
        ensure = getattr(self.flow.actions, "ensure_daily_main", None)
        if not callable(ensure):
            return {"attempted": False, "ok": None, "reason": "ensure_daily_main_unavailable"}
        try:
            return {"attempted": True, "ok": bool(ensure()), "reason": ""}
        except Exception as exc:
            return {"attempted": True, "ok": False, "reason": str(exc)}

    def _recover_after_panel_open_failure(self, open_result):
        reason = str(getattr(open_result, "reason", "") or "")
        sender = getattr(self.flow.actions, "send_foreground_key", None)
        sender_name = "send_foreground_key"
        if not callable(sender):
            sender = getattr(self.flow.actions, "send_key", None)
            sender_name = "send_key"
        if not callable(sender):
            return {"attempted": False, "ok": None, "reason": "panel_open_recovery_key_unavailable"}
        try:
            try:
                sender("esc", after_sleep=1)
            except TypeError:
                sender("esc")
            self.flow.actions.sleep(1)
            ensure = getattr(self.flow.actions, "ensure_daily_main", None)
            if callable(ensure):
                ensure()
            return {
                "attempted": True,
                "ok": True,
                "reason": reason or "daily_activity_panel_not_confirmed",
                "action": sender_name,
            }
        except Exception as exc:
            return {
                "attempted": True,
                "ok": False,
                "reason": f"panel_open_recovery_failed:{exc}",
                "action": sender_name,
            }

    def _populate_record_summary(self, summary, records, page: DailyActivityPage | None = None):
        summary["items"] = [record.to_dict() for record in records]
        summary["actions"] = [record.to_dict() for record in records if record.mutation_performed or record.handler_completed]
        summary["skipped"] = [
            {"title": record.title, "action": record.action, "reason": record.blocker_reason}
            for record in records
            if record.skipped and record.blocker_reason
        ]
        summary["blockers"] = [
            {"title": record.title, "action": record.action, "reason": record.blocker_reason}
            for record in records
            if (not record.eligible) and record.blocker_reason
        ]
        summary["mutation_performed"] = any(record.mutation_performed for record in records)
        summary["mutation_verified"] = bool(
            summary["mutation_performed"]
            and all(not record.mutation_performed or record.mutation_verified for record in records)
        )
        summary["handler_completed"] = any(record.handler_completed for record in records)
        summary["task_completed"] = any(record.task_completed for record in records)
        gift_records = [record for record in records if self._is_gift_task(record.title)]
        if gift_records:
            completed = next((record for record in gift_records if record.mutation_performed or record.task_completed), gift_records[0])
            summary["gift"] = {
                "detected": True,
                "mutation_performed": bool(completed.mutation_performed),
                "mutation_verified": bool(completed.mutation_verified),
                "selected_character": completed.selected_character,
                "selected_item": completed.selected_item,
                "sent_total": int(completed.sent_total or 0),
                "task_reward_claimed": bool(completed.task_reward_claimed),
                "activity_rewards_claimed": int(completed.activity_rewards_claimed or 0),
                "claimable_rewards_remaining": completed.claimable_rewards_remaining,
                "claimable_rewards_reason": completed.claimable_rewards_reason,
                "handler_completed": bool(completed.handler_completed),
                "task_completed": bool(completed.task_completed),
                "reason": completed.blocker_reason,
            }
        elif self.gift_only:
            self._populate_absent_gift_summary(summary, page or DailyActivityPage())

    def _populate_absent_gift_summary(self, summary, page: DailyActivityPage):
        remaining = len(getattr(page, "claimable_milestones", []) or [])
        reason = (
            "daily_task_state_unavailable_because_already_consumed"
            if self.gift_only
            else "gift_task_not_detected_current_daily_state"
        )
        summary["gift"] = {
            "detected": False,
            "mutation_performed": False,
            "mutation_verified": False,
            "selected_character": "",
            "selected_item": "",
            "sent_total": 0,
            "task_reward_claimed": False,
            "activity_rewards_claimed": 0,
            "claimable_rewards_remaining": remaining,
            "claimable_rewards_reason": "" if remaining == 0 else "claimable_activity_rewards_remain",
            "handler_completed": False,
            "task_completed": False,
            "reason": reason,
        }

    def _record_for_card(self, card: DailyTaskCard, *, duplicate_keys: set[tuple[str, str]]):
        title = str(getattr(card, "title", "") or "").strip()
        action = str(getattr(card, "action", "") or "").strip()
        row_box = getattr(card, "box", None)
        button_box = getattr(card, "action_box", None)
        row_evidence = _box_to_dict(row_box)
        button_evidence = _box_to_dict(button_box)
        confidence = min(
            float((row_evidence or {}).get("confidence", 0.0) or 0.0),
            float((button_evidence or {}).get("confidence", 0.0) or 0.0),
        )
        record = DailyTaskItemRecord(
            title=title,
            progress_text=str(getattr(card, "progress_text", "") or ""),
            action=action,
            button_text=str(getattr(card, "button_text", "") or ""),
            state=str(getattr(card, "state", "") or ""),
            row_evidence=row_evidence,
            button_evidence=button_evidence,
            confidence=confidence,
            screenshot_id=self.flow._ensure_current_screenshot_id("task_items"),
        )
        reason = self._blocked_reason(card, record, duplicate_keys)
        record.eligible = not reason
        record.skipped = bool(reason)
        record.blocker_reason = reason
        return record

    def _blocked_reason(self, card: DailyTaskCard, record: DailyTaskItemRecord, duplicate_keys: set[tuple[str, str]]):
        if not record.title:
            return "ambiguous_row_title_missing"
        if self.gift_only and not self._is_gift_task(record.title):
            return "gift_only_mode_deferred"
        if record.row_evidence is None:
            return "row_bbox_missing"
        if record.button_evidence is None:
            return "button_bbox_missing"
        if (record.title, record.action) in duplicate_keys:
            return "ambiguous_row_duplicate"
        if record.action not in self.ACTIONS:
            return "unknown_button"
        if str(getattr(card, "state", "") or "") == "unknown":
            return "task_state_unknown"
        if record.confidence < self.min_confidence:
            return "low_confidence"
        unsafe = self._unsafe_reason(record.title)
        if unsafe:
            return unsafe
        if self._is_gift_task(record.title) and record.action == "前往":
            return ""
        if record.action == "前往" and not self.allow_go_actions:
            return "go_action_deferred_no_completion_evidence"
        return ""

    def _unsafe_reason(self, title: str):
        if any(keyword in title for keyword in self.BATTLE_KEYWORDS):
            return "battle_task_deferred"
        if any(keyword in title for keyword in self.RESOURCE_KEYWORDS):
            return "resource_consuming_task_deferred"
        return ""

    def _is_gift_task(self, title: str):
        return all(keyword in str(title or "") for keyword in self.GIFT_KEYWORDS)

    @staticmethod
    def _duplicate_keys(cards):
        counts: dict[tuple[str, str], int] = {}
        for card in cards:
            key = (str(getattr(card, "title", "") or "").strip(), str(getattr(card, "action", "") or "").strip())
            counts[key] = counts.get(key, 0) + 1
        return {key for key, count in counts.items() if key[0] and count > 1}

    def _execute_card(self, card: DailyTaskCard, record: DailyTaskItemRecord):
        if self._is_gift_task(record.title) and record.action in {"前往", "领取"}:
            self._execute_gift_card(card, record)
            return

        spec = ActionGateSpec(
            recognized_ui=f"daily_task_item_{record.action}",
            confidence=record.confidence,
            screenshot_id=record.screenshot_id,
            evidence_box=getattr(card, "action_box", None),
            target_policy="center",
            min_confidence=self.min_confidence,
            post_verification=f"daily_task_item_{record.action}_verified",
        )
        self._last_verification = {}
        gate_result = DailyActionGate(
            viewport_width=self.flow.actions.width,
            viewport_height=self.flow.actions.height,
            current_screenshot_id=self.flow.snapshot.screenshot_id,
        ).execute_click(
            spec,
            self.flow.actions,
            verifier=lambda gate: self._verify_after_click(card, record),
        )
        record.gate_result = gate_result.to_details()
        record.target_point = record.gate_result.get("target_point")
        record.post_verification = dict(self._last_verification)
        record.mutation_performed = bool(gate_result.mutation_performed)
        record.mutation_verified = bool(record.mutation_performed and gate_result.mutation_verified)
        record.handler_completed = bool(gate_result.mutation_verified and record.action == "前往")
        record.task_completed = bool(record.mutation_verified and self._last_verification.get("task_completed"))
        if gate_result.reject_reason:
            record.skipped = True
            record.blocker_reason = gate_result.reject_reason
        elif gate_result.failure_reason:
            record.blocker_reason = gate_result.failure_reason

    def _execute_gift_card(self, card: DailyTaskCard, record: DailyTaskItemRecord):
        if record.action == "领取":
            self._execute_gift_reward_claim_only(card, record)
            return

        runtime = self.gift_runtime_factory(self.flow)
        entry_spec = ActionGateSpec(
            recognized_ui="daily_task_item_gift_go",
            confidence=record.confidence,
            screenshot_id=record.screenshot_id,
            evidence_box=getattr(card, "action_box", None),
            target_policy="center",
            min_confidence=self.min_confidence,
            post_verification="gift_page_reached",
        )
        self._last_verification = {}
        entry_gate = DailyActionGate(
            viewport_width=self.flow.actions.width,
            viewport_height=self.flow.actions.height,
            current_screenshot_id=self.flow.snapshot.screenshot_id,
        ).execute_click(
            entry_spec,
            _ReliableClickContext(self.flow.actions),
            verifier=lambda gate: self._verify_gift_page_entry(runtime),
        )
        record.gate_result = entry_gate.to_details()
        record.target_point = record.gate_result.get("target_point")
        record.post_verification = dict(self._last_verification)
        if entry_gate.reject_reason:
            record.skipped = True
            record.blocker_reason = entry_gate.reject_reason
            return
        if not entry_gate.verified:
            record.handler_completed = False
            record.blocker_reason = "gift_page_not_reached"
            return

        record.handler_completed = True
        send_result = runtime.send_default_gift()
        send_details = send_result.to_dict() if hasattr(send_result, "to_dict") else dict(send_result or {})
        record.selected_character = str(send_details.get("selected_character", "") or "")
        record.selected_item = str(send_details.get("selected_item", "") or "")
        record.sent_total = int(send_details.get("sent_total", 0) or 0)
        record.mutation_performed = bool(send_details.get("mutation_performed"))
        record.post_verification = {
            **record.post_verification,
            "gift_send": send_details,
        }
        if not record.mutation_performed:
            record.blocker_reason = str(send_details.get("reason") or "gift_send_button_not_found")
            return

        task_verification = self._verify_gift_task_completion(card)
        record.post_verification["task_status"] = task_verification
        record.task_completed = bool(task_verification.get("task_completed"))
        if not record.task_completed:
            record.mutation_verified = False
            record.blocker_reason = "gift_post_action_verification_failed"
            return

        reward_claim = self._claim_gift_task_reward(card)
        record.post_verification["task_reward_claim"] = reward_claim
        record.task_reward_claimed = bool(reward_claim.get("task_reward_claimed"))
        if record.task_reward_claimed:
            activity_rewards = self._claim_activity_rewards_until_stable()
            self._apply_activity_reward_details(record, activity_rewards)
            record.mutation_verified = True
            record.blocker_reason = ""
            record.skipped = False
            return

        record.mutation_verified = False
        record.blocker_reason = str(reward_claim.get("reason") or "gift_task_reward_claim_failed")

    def _execute_gift_reward_claim_only(self, card: DailyTaskCard, record: DailyTaskItemRecord):
        record.handler_completed = True
        record.task_completed = True
        record.sent_total = self._sent_total_from_progress(record.progress_text) or 1
        reward_claim = self._claim_gift_task_reward(card)
        record.gate_result = reward_claim.get("gate_result")
        record.target_point = (record.gate_result or {}).get("target_point")
        record.post_verification = {"task_reward_claim": reward_claim}
        record.mutation_performed = bool(reward_claim.get("mutation_performed"))
        record.task_reward_claimed = bool(reward_claim.get("task_reward_claimed"))
        if not record.task_reward_claimed:
            record.mutation_verified = False
            record.blocker_reason = str(reward_claim.get("reason") or "gift_task_reward_claim_failed")
            return

        activity_rewards = self._claim_activity_rewards_until_stable()
        self._apply_activity_reward_details(record, activity_rewards)
        record.mutation_verified = True
        record.blocker_reason = ""
        record.skipped = False

    def _claim_gift_task_reward(self, before_card: DailyTaskCard):
        open_result = self.flow.open_activity_panel_result()
        if not getattr(open_result, "daily_activity_panel_detected", False):
            return {
                "task_reward_claimed": False,
                "mutation_performed": False,
                "mutation_verified": False,
                "reason": "daily_activity_panel_not_confirmed_before_gift_claim",
            }
        analysis = self.flow.analyze_daily_activity(panel_detected=True)
        self.flow.record_daily_activity_analysis(analysis)
        page = analysis.page or DailyActivityPage()
        claim_card = self._find_gift_claim_card(before_card, page)
        if claim_card is None:
            return {
                "task_reward_claimed": False,
                "mutation_performed": False,
                "mutation_verified": False,
                "reason": "gift_task_claim_button_not_found",
            }

        evidence_box = getattr(claim_card, "action_box", None)
        screenshot_id = self.flow._ensure_current_screenshot_id("gift_task_claim")
        spec = ActionGateSpec(
            recognized_ui="daily_task_item_gift_claim",
            confidence=float(getattr(evidence_box, "confidence", 1.0) or 0.0) if evidence_box is not None else 0.0,
            screenshot_id=screenshot_id,
            evidence_box=evidence_box,
            target_policy="center",
            min_confidence=self.min_confidence,
            post_verification="gift_task_reward_claimed",
        )
        verification: dict[str, Any] = {}

        def verifier(gate):
            nonlocal verification
            verification = self._verify_gift_reward_claim_after_click(claim_card)
            return bool(verification.get("verified")), verification.get("after_screenshot_id", "")

        gate_result = DailyActionGate(
            viewport_width=self.flow.actions.width,
            viewport_height=self.flow.actions.height,
            current_screenshot_id=self.flow.snapshot.screenshot_id,
        ).execute_click(
            spec,
            _ReliableClickContext(self.flow.actions),
            verifier=verifier,
        )
        details = gate_result.to_details()
        task_reward_claimed = bool(gate_result.mutation_verified and verification.get("task_reward_claimed"))
        reason = ""
        if not task_reward_claimed:
            if gate_result.mutation_performed and verification.get("reason"):
                reason = str(verification.get("reason") or "")
            else:
                reason = gate_result.reject_reason or gate_result.failure_reason or "gift_task_reward_claim_failed"
        return {
            "task_reward_claimed": task_reward_claimed,
            "mutation_performed": bool(gate_result.mutation_performed),
            "mutation_verified": bool(gate_result.mutation_verified),
            "reason": reason,
            "gate_result": details,
            "post_verification": verification,
        }

    def _verify_gift_reward_claim_after_click(self, claim_card: DailyTaskCard):
        self.flow.actions.sleep(1)
        analysis = self.flow.analyze_daily_activity(panel_detected=True)
        self.flow.record_daily_activity_analysis(analysis)
        page = analysis.page or DailyActivityPage()
        still_claimable = any(
            self._same_task(claim_card, candidate) and str(getattr(candidate, "action", "") or "") == "领取"
            for candidate in page.task_cards
        )
        after_screenshot_id = self.flow.snapshot.screenshot_id
        claimed = not still_claimable
        return {
            "verified": claimed,
            "task_reward_claimed": claimed,
            "post_action_result": "gift_task_reward_claimed" if claimed else "gift_task_reward_still_claimable",
            "after_screenshot_id": after_screenshot_id,
            "reason": "" if claimed else "gift_task_reward_still_claimable",
        }

    def _claim_activity_rewards_until_stable(self, max_claims: int = 5):
        details = {
            "attempted": True,
            "claimed_count": 0,
            "claimable_rewards_remaining": 0,
            "reason": "",
        }
        open_result = self.flow.open_activity_panel_result()
        if not getattr(open_result, "daily_activity_panel_detected", False):
            details.update(
                {
                    "claimable_rewards_remaining": None,
                    "reason": "daily_activity_panel_not_confirmed_before_milestone_claim",
                }
            )
            return details

        analysis = self.flow.analyze_daily_activity(panel_detected=True)
        self.flow.record_daily_activity_analysis(analysis)
        page = analysis.page or DailyActivityPage()

        for _ in range(max_claims):
            remaining = len(page.claimable_milestones)
            details["claimable_rewards_remaining"] = remaining
            if remaining <= 0:
                details["reason"] = ""
                return details
            if not self.flow.claim_activity_milestone_rewards(page):
                details["reason"] = self.flow.snapshot.reward_skip_reason or "activity_milestone_claim_failed"
                details["claimable_rewards_remaining"] = remaining
                return details
            details["claimed_count"] += 1
            analysis = self.flow.analyze_daily_activity(panel_detected=True)
            self.flow.record_daily_activity_analysis(analysis)
            page = analysis.page or DailyActivityPage()

        details["claimable_rewards_remaining"] = len(page.claimable_milestones)
        if details["claimable_rewards_remaining"]:
            details["reason"] = "activity_milestone_claim_limit_reached"
        return details

    def _apply_activity_reward_details(self, record: DailyTaskItemRecord, details: dict[str, Any]):
        record.activity_rewards_claimed = int(details.get("claimed_count", 0) or 0)
        remaining = details.get("claimable_rewards_remaining")
        record.claimable_rewards_remaining = None if remaining is None else int(remaining)
        record.claimable_rewards_reason = str(details.get("reason", "") or "")
        record.post_verification["activity_rewards"] = dict(details)

    def _find_gift_claim_card(self, before_card: DailyTaskCard, page: DailyActivityPage):
        for candidate in page.task_cards:
            if self._same_task(before_card, candidate) and str(getattr(candidate, "action", "") or "") == "领取":
                return candidate
        for candidate in page.task_cards:
            if self._is_gift_task(str(getattr(candidate, "title", "") or "")) and str(getattr(candidate, "action", "") or "") == "领取":
                return candidate
        return None

    def _verify_gift_page_entry(self, runtime):
        self.flow.actions.sleep(1)
        reached = bool(runtime.verify_gift_page_reached())
        after_screenshot_id = self.flow._new_screenshot_id("after_gift_entry")
        self.flow.snapshot.screenshot_id = after_screenshot_id
        self._last_verification = {
            "verified": reached,
            "post_action_result": "gift_page_reached" if reached else "gift_page_not_reached",
            "handler_completed": reached,
            "task_completed": False,
            "after_screenshot_id": after_screenshot_id,
        }
        return reached, after_screenshot_id

    def _verify_gift_task_completion(self, before_card: DailyTaskCard):
        self.flow.actions.ensure_daily_main()
        open_result = self.flow.open_activity_panel_result()
        if not getattr(open_result, "daily_activity_panel_detected", False):
            return {
                "verified": False,
                "task_completed": False,
                "reason": "daily_activity_panel_not_confirmed_after_gift",
            }
        analysis = self.flow.analyze_daily_activity(panel_detected=True)
        self.flow.record_daily_activity_analysis(analysis)
        page = analysis.page or DailyActivityPage()
        matches = [candidate for candidate in page.task_cards if self._same_task(before_card, candidate)]
        if not matches:
            return {
                "verified": True,
                "task_completed": True,
                "post_action_result": "gift_task_card_vanished",
            }
        after = matches[0]
        before_progress = str(getattr(before_card, "progress_text", "") or "")
        after_progress = str(getattr(after, "progress_text", "") or "")
        after_action = str(getattr(after, "action", "") or "")
        progress_changed = bool(before_progress and after_progress and before_progress != after_progress)
        completed_progress = self._progress_is_complete(after_progress)
        action_changed = after_action and after_action != str(getattr(before_card, "action", "") or "")
        task_completed = bool(progress_changed or completed_progress or after_action in {"领取", "完成"} or action_changed)
        return {
            "verified": task_completed,
            "task_completed": task_completed,
            "post_action_result": "gift_task_state_changed" if task_completed else "gift_task_state_unchanged",
            "before_progress": before_progress,
            "after_progress": after_progress,
            "before_action": str(getattr(before_card, "action", "") or ""),
            "after_action": after_action,
        }

    def _verify_after_click(self, card: DailyTaskCard, record: DailyTaskItemRecord):
        self.flow.actions.sleep(1)
        analysis = self.flow.analyze_daily_activity(panel_detected=True)
        self.flow.record_daily_activity_analysis(analysis)
        after_screenshot_id = self.flow.snapshot.screenshot_id
        verification = self._post_verification(card, record, analysis.page if analysis else None)
        verification["after_screenshot_id"] = after_screenshot_id
        self._last_verification = verification
        return bool(verification.get("verified")), after_screenshot_id

    def _post_verification(self, card: DailyTaskCard, record: DailyTaskItemRecord, page: DailyActivityPage | None):
        page = page or DailyActivityPage()
        matches = [candidate for candidate in page.task_cards if self._same_task(card, candidate)]
        same_action = [candidate for candidate in matches if getattr(candidate, "action", "") == record.action]
        if record.action == "领取":
            verified = not same_action
            return {
                "verified": verified,
                "post_action_result": "task_reward_claimed" if verified else "still_claimable",
                "task_completed": verified,
                "handler_completed": False,
            }
        if record.action == "完成":
            changed_to_claimable = any(getattr(candidate, "action", "") == "领取" for candidate in matches)
            verified = changed_to_claimable or not same_action
            return {
                "verified": verified,
                "post_action_result": "task_state_changed" if verified else "state_unchanged",
                "task_completed": verified,
                "handler_completed": False,
            }
        verified = not bool(getattr(page, "task_cards", []))
        return {
            "verified": verified,
            "post_action_result": "target_page_entered" if verified else "still_on_task_list",
            "task_completed": False,
            "handler_completed": verified,
        }

    @staticmethod
    def _progress_is_complete(progress_text: str):
        value = str(progress_text or "").strip()
        if not value:
            return False
        if "/" not in value:
            return value.startswith("1")
        current, _, target = value.partition("/")
        try:
            return int(current) >= int(target)
        except ValueError:
            return value.startswith("1/")

    @staticmethod
    def _sent_total_from_progress(progress_text: str):
        value = str(progress_text or "").strip()
        if "/" in value:
            current, _, _ = value.partition("/")
            try:
                return int(current)
            except ValueError:
                return 0
        if value.startswith("1"):
            return 1
        return 0

    @staticmethod
    def _same_task(before, after):
        before_title = str(getattr(before, "title", "") or "").strip()
        after_title = str(getattr(after, "title", "") or "").strip()
        if before_title and after_title:
            return before_title == after_title
        before_box = getattr(before, "box", None)
        after_box = getattr(after, "box", None)
        if before_box is None or after_box is None:
            return False
        return (
            abs(int(getattr(before_box, "x", 0) or 0) - int(getattr(after_box, "x", 0) or 0)) <= 12
            and abs(int(getattr(before_box, "y", 0) or 0) - int(getattr(after_box, "y", 0) or 0)) <= 12
        )
