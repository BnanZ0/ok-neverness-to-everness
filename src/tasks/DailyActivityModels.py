from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal


DailyActivityOutcomeStatus = Literal["done", "skipped", "failed"]


class _OutcomeStatusFactory:
    def __init__(self, status: str, factory_name: str):
        self.status = status
        self.factory_name = factory_name

    def __get__(self, instance, owner):
        if instance is None:
            return getattr(owner, self.factory_name)
        return instance.status == self.status


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def _box_to_dict(box):
    if box is None:
        return None
    return {
        "name": str(getattr(box, "name", "")),
        "x": int(getattr(box, "x", 0) or 0),
        "y": int(getattr(box, "y", 0) or 0),
        "width": int(getattr(box, "width", 0) or 0),
        "height": int(getattr(box, "height", 0) or 0),
        "confidence": float(getattr(box, "confidence", 1.0) or 0.0),
    }


@dataclass(frozen=True)
class ActivityCardCandidate:
    card_key: str = ""
    label: str = ""
    box: object | None = None
    confidence: float = 0.0
    source: str = ""
    text: str = ""
    state_tags: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_card(cls, card, *, card_key: str = "", source: str = "daily_activity_card"):
        title = str(getattr(card, "title", "") or "").strip()
        action = str(getattr(card, "action", "") or "").strip()
        state = str(getattr(card, "state", "") or "").strip()
        box = getattr(card, "box", None) or getattr(card, "action_box", None)
        confidence = float(getattr(box, "confidence", 1.0) or 0.0) if box is not None else 0.0
        state_tags = tuple(tag for tag in (action, state) if tag)
        return cls(
            card_key=card_key or str(getattr(card, "handler_key", "") or title),
            label=title,
            box=box,
            confidence=confidence,
            source=source,
            text=str(getattr(card, "progress_text", "") or ""),
            state_tags=state_tags,
        )

    def to_dict(self):
        return {
            "card_key": self.card_key,
            "label": self.label,
            "box": _box_to_dict(self.box),
            "confidence": self.confidence,
            "source": self.source,
            "text": self.text,
            "state_tags": list(self.state_tags),
        }


@dataclass(frozen=True)
class ActionGateSpec:
    recognized_ui: str = ""
    confidence: float = 0.0
    screenshot_id: str = ""
    evidence_box: object | None = None
    target_policy: str = "center"
    target_offset: tuple[float, float] | None = None
    min_confidence: float = 0.8
    post_verification: str = ""
    timeout_ms: int = 1500
    retry_count: int = 0
    staleness_budget_ms: int = 1000

    def to_dict(self):
        return {
            "recognized_ui": self.recognized_ui,
            "confidence": self.confidence,
            "screenshot_id": self.screenshot_id,
            "evidence_box": _box_to_dict(self.evidence_box),
            "target_policy": self.target_policy,
            "target_offset": list(self.target_offset) if self.target_offset is not None else None,
            "min_confidence": self.min_confidence,
            "post_verification": self.post_verification,
            "timeout_ms": self.timeout_ms,
            "retry_count": self.retry_count,
            "staleness_budget_ms": self.staleness_budget_ms,
        }


@dataclass(frozen=True)
class ActionGateResult:
    allowed: bool = False
    executed: bool = False
    verified: bool = False
    mutation_performed: bool = False
    mutation_verified: bool = False
    reject_reason: str = ""
    failure_reason: str = ""
    before_screenshot_id: str = ""
    after_screenshot_id: str = ""
    target_point: tuple[int, int] | None = None

    @classmethod
    def rejected(cls, reason: str, *, before_screenshot_id: str = "", target_point=None):
        return cls(
            allowed=False,
            executed=False,
            verified=False,
            mutation_performed=False,
            mutation_verified=False,
            reject_reason=reason,
            before_screenshot_id=before_screenshot_id,
            target_point=target_point,
        )

    @classmethod
    def allowed_result(cls, *, before_screenshot_id: str, target_point: tuple[int, int]):
        return cls(
            allowed=True,
            executed=False,
            verified=False,
            mutation_performed=False,
            mutation_verified=False,
            before_screenshot_id=before_screenshot_id,
            target_point=target_point,
        )

    @classmethod
    def executed_result(
        cls,
        *,
        verified: bool,
        before_screenshot_id: str,
        after_screenshot_id: str,
        target_point: tuple[int, int],
        failure_reason: str = "",
    ):
        return cls(
            allowed=True,
            executed=True,
            verified=verified,
            mutation_performed=True,
            mutation_verified=verified,
            failure_reason=failure_reason,
            before_screenshot_id=before_screenshot_id,
            after_screenshot_id=after_screenshot_id,
            target_point=target_point,
        )

    def to_details(self):
        return {
            "allowed": self.allowed,
            "executed": self.executed,
            "verified": self.verified,
            "mutation_performed": self.mutation_performed,
            "mutation_verified": self.mutation_verified,
            "reject_reason": self.reject_reason,
            "failure_reason": self.failure_reason,
            "before_screenshot_id": self.before_screenshot_id,
            "after_screenshot_id": self.after_screenshot_id,
            "target_point": list(self.target_point) if self.target_point is not None else None,
        }

    def to_outcome(self, *, success_reason: str = "action_verified"):
        if not self.allowed:
            return DailyActivityOutcome.skipped(
                self.reject_reason,
                mutation_performed=False,
                mutation_verified=False,
                details=self.to_details(),
            )
        if self.executed and self.verified:
            return DailyActivityOutcome.succeeded(
                success_reason,
                mutation_performed=True,
                mutation_verified=True,
                details=self.to_details(),
            )
        return DailyActivityOutcome.failed(
            self.failure_reason or "post_verification_failed",
            mutation_performed=self.mutation_performed,
            mutation_verified=False,
            details=self.to_details(),
        )


@dataclass(frozen=True)
class ActivityHandleIntent:
    handler_key: str = ""
    candidate: ActivityCardCandidate | None = None
    priority: int = 100
    action_kind: str = ""
    gate_spec: ActionGateSpec | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self):
        return {
            "handler_key": self.handler_key,
            "candidate": self.candidate.to_dict() if self.candidate is not None else None,
            "priority": self.priority,
            "action_kind": self.action_kind,
            "gate_spec": self.gate_spec.to_dict() if self.gate_spec is not None else None,
            "notes": list(self.notes),
        }


@dataclass
class DailyActivitySnapshot:
    screenshot_id: str = ""
    captured_at: str = field(default_factory=_utc_now_iso)
    panel_ready: bool = False
    cards: list[ActivityCardCandidate] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    debug_artifacts: list[str] = field(default_factory=list)
    analysis: object | None = None
    cards_claimed: int = 0
    handlers_completed: bool = False
    remaining_tasks: list[str] | None = None
    reward_skip_reason: str = ""
    mutation_performed: bool = False
    mutation_verified: bool = False
    skipped_reason: str = ""
    failure_reason: str = ""

    def record_warning(self, warning: str):
        if warning:
            self.warnings.append(str(warning))

    def details(self):
        handler_completed = bool(self.handlers_completed)
        task_completed = bool(self.cards_claimed)
        return {
            "screenshot_id": self.screenshot_id,
            "captured_at": self.captured_at,
            "panel_ready": self.panel_ready,
            "cards": [card.to_dict() for card in self.cards],
            "warnings": list(self.warnings),
            "debug_artifacts": list(self.debug_artifacts),
            "analysis": self.analysis,
            "cards_claimed": int(self.cards_claimed or 0),
            "handler_completed": handler_completed,
            "task_completed": task_completed,
            "remaining_tasks": list(self.remaining_tasks or []),
            "reward_skip_reason": self.reward_skip_reason,
            "mutation_performed": bool(self.mutation_performed),
            "mutation_verified": bool(self.mutation_verified),
            "skipped_reason": self.skipped_reason,
            "failure_reason": self.failure_reason,
        }


@dataclass(frozen=True)
class DailyActivityOutcome:
    status: DailyActivityOutcomeStatus
    mutation_performed: bool = False
    mutation_verified: bool = False
    skipped_reason: str = ""
    failure_reason: str = ""
    legacy_return: Any = None
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self):
        return self.status != "failed"

    @property
    def done(self):
        return self.status == "done"

    @property
    def reason(self):
        if self.status == "failed":
            return self.failure_reason
        if self.status == "skipped":
            return self.skipped_reason
        return str(self.details.get("reason", "") or "")

    @property
    def is_skipped(self):
        return self.status == "skipped"

    @property
    def is_failed(self):
        return self.status == "failed"

    @classmethod
    def _make_succeeded(
        cls,
        reason: str = "",
        *,
        mutation_performed: bool = False,
        mutation_verified: bool = False,
        details: dict[str, Any] | None = None,
        legacy_return: Any = True,
    ):
        payload = dict(details or {})
        if reason:
            payload.setdefault("reason", reason)
        return cls(
            status="done",
            mutation_performed=mutation_performed,
            mutation_verified=mutation_verified,
            legacy_return=legacy_return,
            details=payload,
        )

    @classmethod
    def _make_skipped(
        cls,
        reason: str = "",
        *,
        mutation_performed: bool = False,
        mutation_verified: bool = False,
        details: dict[str, Any] | None = None,
        legacy_return: Any = None,
        skipped_sentinel: Any = None,
    ):
        return cls(
            status="skipped",
            mutation_performed=mutation_performed,
            mutation_verified=mutation_verified,
            skipped_reason=reason,
            legacy_return=skipped_sentinel if skipped_sentinel is not None else legacy_return,
            details=dict(details or {}),
        )

    @classmethod
    def _make_failed(
        cls,
        reason: str = "",
        *,
        mutation_performed: bool = False,
        mutation_verified: bool = False,
        details: dict[str, Any] | None = None,
        legacy_return: Any = False,
    ):
        return cls(
            status="failed",
            mutation_performed=mutation_performed,
            mutation_verified=mutation_verified,
            failure_reason=reason,
            legacy_return=legacy_return,
            details=dict(details or {}),
        )

    succeeded = _OutcomeStatusFactory("done", "_make_succeeded")
    skipped = _OutcomeStatusFactory("skipped", "_make_skipped")
    failed = _OutcomeStatusFactory("failed", "_make_failed")

    def to_details(self):
        payload = dict(self.details)
        payload.update(
            {
                "mutation_performed": self.mutation_performed,
                "mutation_verified": self.mutation_verified,
                "skipped_reason": self.skipped_reason,
                "failure_reason": self.failure_reason,
            }
        )
        return payload

    def to_legacy_value(self, *, skipped_sentinel: Any = None):
        if self.legacy_return is not None:
            return self.legacy_return
        if self.status == "failed":
            return False
        if self.status == "skipped":
            return skipped_sentinel
        return True
