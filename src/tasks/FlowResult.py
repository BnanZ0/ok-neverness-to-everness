from dataclasses import dataclass, field
from typing import Any, Literal


FlowStatus = Literal["done", "skipped", "failed"]


@dataclass(frozen=True)
class FlowResult:
    status: FlowStatus = "done"
    reason: str = ""
    mutated: bool = False
    details: dict[str, Any] = field(default_factory=dict)
    legacy_return: Any = None

    @property
    def ok(self):
        return self.status != "failed"

    @property
    def done(self):
        return self.status == "done"

    @property
    def skipped(self):
        return self.status == "skipped"

    @property
    def failed(self):
        return self.status == "failed"

    def __bool__(self):
        return self.ok

    def to_dict(self):
        return {
            "status": self.status,
            "ok": self.ok,
            "reason": self.reason,
            "mutated": self.mutated,
            "details": self.details,
        }

    def to_legacy_value(self, *, skipped_sentinel: object | None = None):
        if self.legacy_return is not None:
            return self.legacy_return
        if self.failed:
            return False
        if self.skipped:
            return skipped_sentinel
        return True

    @classmethod
    def success(
        cls,
        reason: str = "",
        mutated: bool = False,
        details: dict[str, Any] | None = None,
        *,
        legacy_return: Any = None,
    ):
        return cls(status="done", reason=reason, mutated=mutated, details=details or {}, legacy_return=legacy_return)

    @classmethod
    def skip(cls, reason: str = "", details: dict[str, Any] | None = None, *, legacy_return: Any = None):
        return cls(status="skipped", reason=reason, mutated=False, details=details or {}, legacy_return=legacy_return)

    @classmethod
    def fail(
        cls,
        reason: str = "",
        details: dict[str, Any] | None = None,
        *,
        legacy_return: Any = None,
        mutated: bool = False,
    ):
        return cls(status="failed", reason=reason, mutated=mutated, details=details or {}, legacy_return=legacy_return)

    @classmethod
    def from_outcome(cls, outcome: Any):
        status = str(getattr(outcome, "status", "") or "")
        details = dict(getattr(outcome, "details", {}) or {})
        mutation_performed = bool(getattr(outcome, "mutation_performed", False))
        mutation_verified = bool(getattr(outcome, "mutation_verified", False))
        skipped_reason = str(getattr(outcome, "skipped_reason", "") or "")
        failure_reason = str(getattr(outcome, "failure_reason", "") or "")
        reason = failure_reason if status == "failed" else skipped_reason
        if not reason:
            reason = str(details.get("reason", "") or "")

        details.update(
            {
                "mutation_performed": mutation_performed,
                "mutation_verified": mutation_verified,
                "skipped_reason": skipped_reason,
                "failure_reason": failure_reason,
            }
        )
        legacy_return = getattr(outcome, "legacy_return", None)
        if status in ("done", "success", "succeeded"):
            return cls.success(reason, mutated=mutation_performed, details=details, legacy_return=legacy_return)
        if status == "skipped":
            return cls.skip(reason, details=details, legacy_return=legacy_return)
        if status in ("failed", "failure"):
            return cls.fail(reason, details=details, legacy_return=legacy_return, mutated=mutation_performed)
        return cls.fail(f"unknown_outcome_status:{status or type(outcome).__name__}", details=details)

    @classmethod
    def from_legacy(
        cls,
        value: Any,
        *,
        skipped_sentinel: object | None = None,
        skip_reason: str = "",
        falsey_is_failed: bool = False,
    ):
        if isinstance(value, cls):
            if value.skipped and not value.reason and skip_reason:
                return cls.skip(skip_reason, details=value.details, legacy_return=value.legacy_return)
            return value

        if skipped_sentinel is not None and value is skipped_sentinel:
            return cls.skip(skip_reason)

        if value is False:
            return cls.fail()

        if value is True:
            return cls.success(mutated=True)

        if value is None:
            if falsey_is_failed:
                return cls.fail()
            return cls.success(mutated=False)

        if isinstance(value, dict):
            status = str(value.get("status") or "").strip().lower()
            ok = bool(value.get("ok", True))
            reason = str(value.get("reason") or "")
            mutated = cls._dict_mutated(value)
            details = dict(value)
            if status in ("failed", "failure"):
                return cls.fail(reason, details=details, mutated=mutated)
            if status == "skipped":
                return cls.skip(reason or skip_reason, details=details)
            if status in ("done", "success", "succeeded"):
                return cls.success(reason, mutated=mutated, details=details)
            if not ok:
                return cls.fail(reason, details=details, mutated=mutated)
            if bool(value.get("skipped")):
                return cls.skip(reason or skip_reason, details=details)
            return cls.success(reason, mutated=mutated, details=details)

        if hasattr(value, "ok"):
            ok = bool(getattr(value, "ok", False))
            reason = cls._object_reason(value)
            mutated = cls._object_mutated(value)
            if not ok:
                return cls.fail(reason)
            if reason:
                return cls.skip(reason)
            return cls.success(mutated=mutated)

        if falsey_is_failed and not value:
            return cls.fail()

        return cls.fail(f"unknown_legacy_result_type:{type(value).__name__}")

    @staticmethod
    def _dict_mutated(value: dict[str, Any]):
        return bool(
            value.get("mutated")
            or value.get("mutation_performed")
            or value.get("claimed")
            or value.get("task_completed")
            or value.get("cards_claimed")
            or value.get("milestone_claimed")
            or value.get("reward_claimed")
        )

    @staticmethod
    def _object_reason(value: Any):
        for attr in ("skip_reason", "reason"):
            text = str(getattr(value, attr, "") or "")
            if text:
                return text
        return ""

    @staticmethod
    def _object_mutated(value: Any):
        return bool(
            getattr(value, "mutated", False)
            or getattr(value, "mutation_performed", False)
            or getattr(value, "income_claimed", False)
            or getattr(value, "real_purchase_performed", False)
            or getattr(value, "selected_options", None)
        )
