from dataclasses import dataclass
from typing import Callable, Iterable


TitleMatcher = Callable[[str], bool]


@dataclass(frozen=True)
class DailyActivityHandlerRule:
    """Route a daily activity card title to a safe handler method."""

    handler_key: str
    handler_name: str
    matcher: TitleMatcher
    priority: int = 100
    default_blocked_reason: str = ""

    def matches(self, title: str) -> bool:
        return self.matcher((title or "").strip())


def title_contains_any(*keywords: str) -> TitleMatcher:
    needles = tuple(keyword for keyword in keywords if keyword)

    def matcher(title: str) -> bool:
        return any(keyword in title for keyword in needles)

    return matcher


def title_contains_all(*keywords: str) -> TitleMatcher:
    needles = tuple(keyword for keyword in keywords if keyword)

    def matcher(title: str) -> bool:
        return all(keyword in title for keyword in needles)

    return matcher


def title_contains(text: str) -> TitleMatcher:
    def matcher(title: str) -> bool:
        return text in title

    return matcher


def resolve_activity_handler_rule(
    title: str,
    rules: Iterable[DailyActivityHandlerRule],
) -> DailyActivityHandlerRule | None:
    for rule in sorted(rules, key=lambda item: item.priority):
        if rule.matches(title):
            return rule
    return None
