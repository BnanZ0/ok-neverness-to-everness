from src.tasks.DailyActivityModels import ActionGateResult, ActionGateSpec


class DailyActionGate:
    """Recognition-driven guard for DailyActivity mutation actions."""

    def __init__(self, *, viewport_width: int, viewport_height: int, current_screenshot_id: str = ""):
        self.viewport_width = int(viewport_width or 0)
        self.viewport_height = int(viewport_height or 0)
        self.current_screenshot_id = current_screenshot_id or ""

    def evaluate(self, spec: ActionGateSpec):
        if not spec.recognized_ui:
            return ActionGateResult.rejected("recognized_ui_missing", before_screenshot_id=spec.screenshot_id)
        if not spec.screenshot_id:
            return ActionGateResult.rejected("screenshot_id_missing", before_screenshot_id=spec.screenshot_id)
        if self.current_screenshot_id and spec.screenshot_id != self.current_screenshot_id:
            return ActionGateResult.rejected("stale_screenshot_id", before_screenshot_id=spec.screenshot_id)
        if float(spec.confidence or 0.0) < float(spec.min_confidence or 0.0):
            return ActionGateResult.rejected("low_confidence", before_screenshot_id=spec.screenshot_id)
        if self.viewport_width <= 0 or self.viewport_height <= 0:
            return ActionGateResult.rejected("invalid_viewport", before_screenshot_id=spec.screenshot_id)

        box = self._box_geometry(spec.evidence_box)
        if box is None:
            return ActionGateResult.rejected("evidence_box_missing", before_screenshot_id=spec.screenshot_id)
        x, y, width, height = box
        if width <= 0 or height <= 0:
            return ActionGateResult.rejected("evidence_box_invalid", before_screenshot_id=spec.screenshot_id)
        if x < 0 or y < 0 or x + width > self.viewport_width or y + height > self.viewport_height:
            return ActionGateResult.rejected("evidence_box_out_of_bounds", before_screenshot_id=spec.screenshot_id)

        target = self._target_point(spec, box)
        if target is None:
            return ActionGateResult.rejected("target_derivation_failed", before_screenshot_id=spec.screenshot_id)
        if not self._point_in_viewport(target):
            return ActionGateResult.rejected(
                "target_point_out_of_bounds",
                before_screenshot_id=spec.screenshot_id,
                target_point=target,
            )

        return ActionGateResult.allowed_result(before_screenshot_id=spec.screenshot_id, target_point=target)

    def execute_click(self, spec: ActionGateSpec, action_context, *, verifier=None):
        gate = self.evaluate(spec)
        if not gate.allowed:
            return gate

        click = getattr(action_context, "click", None)
        if not callable(click):
            return ActionGateResult.rejected(
                "action_context_click_missing",
                before_screenshot_id=spec.screenshot_id,
                target_point=gate.target_point,
            )

        x, y = gate.target_point
        try:
            click(x, y)
        except Exception as exc:
            return ActionGateResult(
                allowed=True,
                executed=False,
                verified=False,
                mutation_performed=False,
                mutation_verified=False,
                failure_reason=f"click_failed:{exc!r}",
                before_screenshot_id=spec.screenshot_id,
                target_point=gate.target_point,
            )

        after_screenshot_id = self.current_screenshot_id or spec.screenshot_id
        if verifier is None:
            return ActionGateResult.executed_result(
                verified=False,
                before_screenshot_id=spec.screenshot_id,
                after_screenshot_id=after_screenshot_id,
                target_point=gate.target_point,
                failure_reason="post_verification_missing",
            )

        try:
            verification = verifier(gate)
        except Exception as exc:
            return ActionGateResult.executed_result(
                verified=False,
                before_screenshot_id=spec.screenshot_id,
                after_screenshot_id=after_screenshot_id,
                target_point=gate.target_point,
                failure_reason=f"post_verification_error:{exc!r}",
            )

        if isinstance(verification, (tuple, list)):
            verified = bool(verification[0]) if verification else False
            if len(verification) > 1 and verification[1]:
                after_screenshot_id = str(verification[1])
        else:
            verified = bool(verification)

        return ActionGateResult.executed_result(
            verified=verified,
            before_screenshot_id=spec.screenshot_id,
            after_screenshot_id=after_screenshot_id,
            target_point=gate.target_point,
            failure_reason="" if verified else "post_verification_failed",
        )

    @staticmethod
    def _box_geometry(box):
        if box is None:
            return None
        if isinstance(box, (tuple, list)) and len(box) == 4:
            x, y, width, height = box
            return int(x), int(y), int(width), int(height)
        try:
            return (
                int(getattr(box, "x")),
                int(getattr(box, "y")),
                int(getattr(box, "width")),
                int(getattr(box, "height")),
            )
        except (AttributeError, TypeError, ValueError):
            return None

    @staticmethod
    def _target_point(spec: ActionGateSpec, box):
        x, y, width, height = box
        policy = (spec.target_policy or "").strip().lower()
        offset = spec.target_offset
        if policy in ("center", "box_center", "evidence_center"):
            target_x = x + width / 2
            target_y = y + height / 2
            if offset is not None:
                if len(offset) != 2:
                    return None
                target_x += float(offset[0])
                target_y += float(offset[1])
            return int(round(target_x)), int(round(target_y))
        if policy in ("top_left", "evidence_top_left"):
            target_x = x
            target_y = y
            if offset is not None:
                if len(offset) != 2:
                    return None
                target_x += float(offset[0])
                target_y += float(offset[1])
            return int(round(target_x)), int(round(target_y))
        if policy == "offset":
            if offset is None or len(offset) != 2:
                return None
            return int(round(x + float(offset[0]))), int(round(y + float(offset[1])))
        return None

    def _point_in_viewport(self, point):
        x, y = point
        return 0 <= x < self.viewport_width and 0 <= y < self.viewport_height
