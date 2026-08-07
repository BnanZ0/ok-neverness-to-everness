"""Extract concise abyss-team traces from an OKNTE log file."""

from __future__ import annotations

import argparse
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

ROUTE_MARKERS = ("Baicang abyss opener", "Chiz Yingxu abyss opener", "Chiz Yingxu abyss cycle")
TIMESTAMP_PATTERN = re.compile(r"^(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})")
LOCK_PATTERN = re.compile(r"strict route locked: (?P<route>.+?) / (?P<step>.+)$")
ACTION_PATTERN = re.compile(r"planner action (?P<char>\w+) -> (?P<action>[^,]+)")
SWITCH_PATTERN = re.compile(
    r"planner switch (?P<source>\w+) -> (?P<target>\w+).+?reason (?P<reason>.+)$"
)
KEEP_PATTERN = re.compile(r"planner keep (?P<char>\w+).+?reason (?P<reason>.+)$")
REACTION_PATTERN = re.compile(
    r"strict route completed entry reaction (?P<source>\w+) -> (?P<target>\w+):"
)
NOT_IN_TEAM_PATTERN = re.compile(r"\) not in team (?P<seconds>\d+(?:\.\d+)?)s$")
TEAM_HANDOFF_PATTERN = re.compile(
    r"队伍交接确认：(?P<source>.+?) -> (?P<target>.+)$"
)

# Enhanced reporting patterns
OPENER_LOCK_PATTERN = re.compile(r"strict route locked: (?P<route>.+? abyss opener)")
SKILL_FAILED_PATTERN = re.compile(
    r"planner action (?P<char>\w+) -> (?P<action>\w+)_(?:skill|ultimate), "
    r"tags \[\], reason unavailable"
)
AUTO_SWITCH_DEAD_PATTERN = re.compile(
    r"detected auto switch after death: (?P<dead>\w+) dead, "
    r"now active (?P<alive>\w+)"
)
SESSION_REBUILD_PATTERN = re.compile(r"combat session (?:started|rebuilt)")
READY_BUT_NOT_SWITCHED_PATTERN = re.compile(
    r"(?P<char>\w+).+(?:priority_ready|ready streak|available).+"
)


@dataclass(slots=True)
class TraceEvent:
    timestamp: str
    kind: str
    detail: str


@dataclass(slots=True)
class CharStats:
    """每名角色在一场 trace 内的统计。"""

    switch_in_count: int = 0
    skill_count: int = 0
    ultimate_count: int = 0
    arc_count: int = 0
    failed_action_count: int = 0
    ready_ticks: int = 0


@dataclass(slots=True)
class AbyssTrace:
    route: str
    started_at: str
    status: str = "pending"
    events: list[TraceEvent] = field(default_factory=list)
    char_stats: dict[str, CharStats] = field(default_factory=dict)
    opener_repeats: int = 0
    session_rebuilds: int = 0

    def add(self, timestamp: str, kind: str, detail: str) -> None:
        self.events.append(TraceEvent(timestamp, kind, detail))

    def action_sequence(self) -> list[str]:
        return [event.detail for event in self.events if event.kind == "action"]

    def reaction_sequence(self) -> list[str]:
        return [event.detail for event in self.events if event.kind == "reaction"]

    def sound_interrupt_count(self) -> int:
        return sum(event.kind == "sound" for event in self.events)

    def _char_stat(self, name: str) -> "CharStats":
        if name not in self.char_stats:
            self.char_stats[name] = CharStats()
        return self.char_stats[name]

    def diagnosis(self) -> list[str]:
        issues = []
        if self.status != "fulfilled":
            issues.append(f"route status is {self.status}")

        if "Baicang abyss opener" in self.route:
            returned = any(
                event.kind == "switch" and event.detail.startswith("Daphneel->Baicang")
                for event in self.events
            )
            if not returned:
                issues.append("no Daphneel->Baicang return switch recorded")

        if "Chiz Yingxu abyss" in self.route:
            action_counts = Counter(self.action_sequence())
            for action in ("Zero:Zero_skill", "Zero:Zero_ultimate", "Chiz:Chiz_ultimate"):
                if action_counts[action] >= 10:
                    issues.append(f"{action} retried {action_counts[action]} times")

            zero_waits = sum(
                event.kind == "wait" and event.detail.startswith("Zero:") for event in self.events
            )
            if zero_waits >= 5:
                issues.append(f"Zero held field for {zero_waits} strict-route wait ticks")

        if "Chiz Yingxu abyss cycle" in self.route:
            reactions = set(self.reaction_sequence())
            for required in ("Chiz->Iloy", "Zero->Yi"):
                if required not in reactions:
                    issues.append(f"missing reaction {required}")

        wait_count = sum(
            event.kind == "action" and "wait_for_strict_route_action" in event.detail
            for event in self.events
        )
        if wait_count >= 20:
            issues.append(f"strict route waited {wait_count} action ticks")
        sound_timeouts = sum(event.kind == "sound_timeout" for event in self.events)
        if sound_timeouts:
            issues.append(f"{sound_timeouts} sound actions discarded after timeout")
        team_gaps = [
            float(event.detail)
            for event in self.events
            if event.kind == "team_gap"
        ]
        if team_gaps and max(team_gaps) >= 2.0:
            issues.append(f"team UI unavailable for {max(team_gaps):.2f}s during route")

        # Enhanced: per-character failed-action retry frequency.
        for name, stat in self.char_stats.items():
            if stat.failed_action_count >= 20:
                issues.append(
                    f"{name} retried unavailable action {stat.failed_action_count} times"
                )

        # Enhanced: opener repeated for same team within one trace.
        if self.opener_repeats >= 1:
            issues.append(f"opener repeated {self.opener_repeats} times in one trace")

        # Enhanced: session rebuilt during what should be a continuous fight.
        if self.session_rebuilds >= 1:
            issues.append(
                f"combat session rebuilt {self.session_rebuilds} times during route"
            )

        # Enhanced: support ready many ticks but never switched in.
        for name, stat in self.char_stats.items():
            if (
                stat.ready_ticks >= 10
                and stat.switch_in_count == 0
                and stat.skill_count == 0
                and stat.ultimate_count == 0
            ):
                issues.append(
                    f"{name} ready {stat.ready_ticks} ticks but never switched in"
                )
        return issues


def _timestamp(line: str) -> str:
    match = TIMESTAMP_PATTERN.search(line)
    return match.group("timestamp") if match else "unknown-time"


def _is_target_route(route: str) -> bool:
    return any(marker in route for marker in ROUTE_MARKERS)


def parse_abyss_traces(lines: list[str]) -> list[AbyssTrace]:
    traces: list[AbyssTrace] = []
    current: AbyssTrace | None = None

    for line in lines:
        timestamp = _timestamp(line)
        lock = LOCK_PATTERN.search(line)
        if lock and _is_target_route(lock.group("route")):
            if current is not None:
                # Detect opener repeated within the same team before closing.
                opener_match = OPENER_LOCK_PATTERN.search(line)
                if (
                    opener_match
                    and current.route == opener_match.group("route")
                ):
                    current.opener_repeats += 1
                traces.append(current)
            current = AbyssTrace(lock.group("route"), timestamp)
            current.add(timestamp, "step", lock.group("step"))
            continue

        if current is None:
            continue

        team_gap = NOT_IN_TEAM_PATTERN.search(line)
        if team_gap:
            current.add(timestamp, "team_gap", team_gap.group("seconds"))
            continue

        handoff = TEAM_HANDOFF_PATTERN.search(line)
        if handoff:
            current.add(
                timestamp,
                "handoff",
                f"{handoff.group('source')}->{handoff.group('target')}",
            )
            continue

        action = ACTION_PATTERN.search(line)
        if action:
            char_name = action.group("char")
            action_name = action.group("action")
            current.add(timestamp, "action", f"{char_name}:{action_name}")
            stat = current._char_stat(char_name)
            if "_skill" in action_name:
                stat.skill_count += 1
            elif "_ultimate" in action_name:
                stat.ultimate_count += 1
            elif "_arc" in action_name:
                stat.arc_count += 1
            failed = SKILL_FAILED_PATTERN.search(line)
            if failed:
                stat.failed_action_count += 1
            continue

        reaction = REACTION_PATTERN.search(line)
        if reaction:
            current.add(
                timestamp,
                "reaction",
                f"{reaction.group('source')}->{reaction.group('target')}",
            )
            continue

        switch = SWITCH_PATTERN.search(line)
        if switch:
            detail = (
                f"{switch.group('source')}->{switch.group('target')} ({switch.group('reason')})"
            )
            current.add(timestamp, "switch", detail)
            current._char_stat(switch.group("target")).switch_in_count += 1
            if (
                current.status == "fulfilled"
                and "Baicang abyss opener" in current.route
                and switch.group("target") == "Baicang"
            ):
                traces.append(current)
                current = None
            continue

        keep = KEEP_PATTERN.search(line)
        if keep and "strict route" in keep.group("reason"):
            current.add(
                timestamp,
                "wait",
                f"{keep.group('char')}:{keep.group('reason')}",
            )
            continue

        if "strict route skips" in line:
            current.add(timestamp, "skip", line.split("strict route skips", 1)[1].strip())
            continue

        if "strict route deadline expired" in line:
            current.status = "expired"
            current.add(timestamp, "deadline", "route deadline expired")
            traces.append(current)
            current = None
            continue

        if "strict route fulfilled:" in line and current.route in line:
            current.status = "fulfilled"
            current.add(timestamp, "status", "route fulfilled")
            continue

        if "Combat sleep interrupted by sound action" in line:
            current.add(timestamp, "sound", "combat yielded to sound action")
            continue

        if "Sound action discarded after timeout" in line:
            current.add(timestamp, "sound_timeout", "sound action timed out")
            continue

        if "combat session started" in line or "combat session rebuilt" in line:
            current.session_rebuilds += 1
            continue

        dead_match = AUTO_SWITCH_DEAD_PATTERN.search(line)
        if dead_match:
            current.add(
                timestamp,
                "death",
                f"{dead_match.group('dead')} dead -> {dead_match.group('alive')}",
            )
            continue

        if "priority_ready" in line or "ready streak" in line:
            char_match = re.search(r"(\w+)", line)
            if char_match:
                current._char_stat(char_match.group(1)).ready_ticks += 1

        if "Executing dodge" in line or "Executing counter attack" in line:
            current.add(timestamp, "sound", line.rsplit(":", 1)[-1].strip())

    if current is not None:
        traces.append(current)
    return traces


def analyze_log(path: Path) -> list[AbyssTrace]:
    return parse_abyss_traces(path.read_text(encoding="utf-8", errors="replace").splitlines())


def format_trace_report(traces: list[AbyssTrace]) -> str:
    if not traces:
        return "No abyss team route traces found."

    sections = []
    for index, trace in enumerate(traces, start=1):
        actions = " -> ".join(trace.action_sequence()) or "none"
        reactions = " -> ".join(trace.reaction_sequence()) or "none"
        skips = sum(event.kind == "skip" for event in trace.events)
        switches = sum(event.kind == "switch" for event in trace.events)
        diagnosis = "; ".join(trace.diagnosis()) or "ok"
        char_stats_lines = []
        for name, stat in trace.char_stats.items():
            char_stats_lines.append(
                f"  {name}: switch_in={stat.switch_in_count}, "
                f"E={stat.skill_count}, Q={stat.ultimate_count}, "
                f"R={stat.arc_count}, failed={stat.failed_action_count}, "
                f"ready_ticks={stat.ready_ticks}"
            )
        char_stats = "\n".join(char_stats_lines) or "  (none)"
        sections.append(
            "\n".join(
                [
                    f"[{index}] {trace.route}",
                    f"start: {trace.started_at}",
                    f"status: {trace.status}",
                    f"actions: {actions}",
                    f"reactions: {reactions}",
                    f"switches: {switches}, optional_skips: {skips}, "
                    f"sound_events: {trace.sound_interrupt_count()}",
                    f"opener_repeats: {trace.opener_repeats}, "
                    f"session_rebuilds: {trace.session_rebuilds}",
                    f"char_stats:\n{char_stats}",
                    f"diagnosis: {diagnosis}",
                ]
            )
        )
    return "\n\n".join(sections)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log_path", type=Path, help="Path to ok-script.log")
    args = parser.parse_args()
    print(format_trace_report(analyze_log(args.log_path)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
