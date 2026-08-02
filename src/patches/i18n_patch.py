from __future__ import annotations

from functools import wraps

from src.utils.i18n_format import match_i18n_format

_PATCH_INSTALLED = False


def _translate_key(self, key, original_tr):
    if isinstance(key, str) and (matched_format := match_i18n_format(key)):
        rule, match = matched_format
        if self.to_translate is not None:
            self.to_translate.discard(key)
        values = match.groupdict()
        for field in rule.translated_fields:
            values[field] = _translate_key(self, values[field], original_tr)
        template = original_tr(self, rule.template) if rule.translate_template else rule.template
        args = [values[field] for field in rule.positional_fields]
        return template.format(*args, **values)

    translated = original_tr(self, key)
    if self.to_translate is not None and isinstance(key, str) and key.strip().isdigit():
        self.to_translate.discard(key)
    return translated


def _wrap_tr(original_tr):
    @wraps(original_tr)
    def tr_with_format_rules(self, key):
        return _translate_key(self, key, original_tr)

    return tr_with_format_rules


def install_i18n_patch():
    global _PATCH_INSTALLED
    if _PATCH_INSTALLED:
        return

    from ok import App, HeadlessApp

    App.tr = _wrap_tr(App.tr)
    HeadlessApp.tr = _wrap_tr(HeadlessApp.tr)
    _PATCH_INSTALLED = True
