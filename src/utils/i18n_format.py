from __future__ import annotations

import re
from dataclasses import dataclass
from re import Pattern
from string import Formatter


@dataclass(frozen=True)
class I18nFormatRule:
    template: str
    pattern: Pattern[str]
    positional_fields: tuple[str, ...] = ()
    translated_fields: frozenset[str] = frozenset()
    allowed_values: tuple[tuple[str, frozenset[str]], ...] = ()
    translate_template: bool = True


_FORMAT_RULES: list[I18nFormatRule] = []


def register_i18n_format(
    template: str,
    *,
    translated_fields: frozenset[str] = frozenset(),
    allowed_values: dict[str, list[str]] | None = None,
    translate_template: bool = True,
):
    pattern, positional_fields = _compile_template_pattern(template)
    rule = I18nFormatRule(
        template=template,
        pattern=pattern,
        positional_fields=positional_fields,
        translated_fields=translated_fields,
        allowed_values=tuple(
            (field, frozenset(values)) for field, values in (allowed_values or {}).items()
        ),
        translate_template=translate_template,
    )
    if rule not in _FORMAT_RULES:
        _FORMAT_RULES.append(rule)


def match_i18n_format(text: str):
    for rule in _FORMAT_RULES:
        if match := rule.pattern.fullmatch(text):
            if all(match[field] in values for field, values in rule.allowed_values):
                return rule, match
    return None


def _compile_template_pattern(template: str):
    pattern_parts = []
    positional_fields = []
    known_fields = set()
    formatter = Formatter()

    for literal, field_name, _, _ in formatter.parse(template):
        pattern_parts.append(re.escape(literal))
        if field_name is None:
            continue
        if field_name:
            if not field_name.isidentifier():
                raise ValueError(f"Unsupported i18n format field: {field_name}")
            name = field_name
        else:
            name = f"__pos_{len(positional_fields)}"
            positional_fields.append(name)
        if name in known_fields:
            pattern_parts.append(f"(?P={name})")
        else:
            pattern_parts.append(f"(?P<{name}>.+?)")
            known_fields.add(name)

    return re.compile("".join(pattern_parts)), tuple(positional_fields)
