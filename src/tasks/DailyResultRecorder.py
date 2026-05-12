from dataclasses import dataclass, field
from typing import Any

from src.tasks.DailyActivityModels import (
    ActionGateResult,
    ActivityHandleIntent,
    DailyActivityOutcome,
    DailyActivitySnapshot,
)


@dataclass
class DailyResultRecorder:
    snapshot: DailyActivitySnapshot | None = None
    intents: list[dict[str, Any]] = field(default_factory=list)
    gate_results: list[dict[str, Any]] = field(default_factory=list)
    outcomes: list[dict[str, Any]] = field(default_factory=list)

    def record_intent(self, intent: ActivityHandleIntent):
        self.intents.append(intent.to_dict())
        return intent

    def record_gate_result(self, result: ActionGateResult):
        self.gate_results.append(result.to_details())
        return result

    def record_outcome(self, outcome: DailyActivityOutcome):
        self.outcomes.append(outcome.to_details())
        return outcome

    def details(self):
        outcome = self.outcomes[-1] if self.outcomes else {}
        snapshot_details = self.snapshot.details() if self.snapshot is not None else {}
        mutation_performed = (
            outcome.get("mutation_performed")
            if "mutation_performed" in outcome
            else snapshot_details.get("mutation_performed")
        )
        mutation_verified = (
            outcome.get("mutation_verified")
            if "mutation_verified" in outcome
            else snapshot_details.get("mutation_verified")
        )
        return {
            "snapshot": snapshot_details,
            "intents": list(self.intents),
            "gate_results": list(self.gate_results),
            "outcomes": list(self.outcomes),
            "mutation_performed": bool(mutation_performed),
            "mutation_verified": bool(mutation_verified),
            "skipped_reason": str(
                outcome.get("skipped_reason")
                or snapshot_details.get("skipped_reason")
                or ""
            ),
            "failure_reason": str(
                outcome.get("failure_reason")
                or snapshot_details.get("failure_reason")
                or ""
            ),
        }
