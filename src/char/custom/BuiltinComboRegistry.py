import re

from ok import og


class BuiltinComboRegistry:
    REF_PREFIX = "builtin:"
    _KEY_PATTERN = re.compile(r"\(([^)]+)\)\s*$")

    @classmethod
    def _get_builtin_entries(cls) -> dict:
        # Late import to avoid module cycles.
        from src.char.CharFactory import char_dict
        return {
            k: v for k, v in char_dict.items() 
            if k != "char_default" and not k.startswith("char_chain_")
        }

    @classmethod
    def _legacy_prefix(cls) -> str:
        app = getattr(og, "app", None)
        if app and hasattr(app, "tr"):
            return f"{app.tr('[内置代码]')} "
        return "[内置代码] "

    @classmethod
    def _locale_name(cls) -> str:
        app = getattr(og, "app", None)
        if app and hasattr(app, "locale"):
            try:
                return app.locale.name()
            except Exception:
                return ""
        return ""

    @classmethod
    def make_ref(cls, builtin_key: str) -> str:
        return f"{cls.REF_PREFIX}{builtin_key}"

    @classmethod
    def ref_to_key(cls, combo_ref: str) -> str | None:
        if not combo_ref:
            return None
        value = combo_ref.strip()
        if value.startswith(cls.REF_PREFIX):
            key = value[len(cls.REF_PREFIX) :].strip()
            return key or None
        return None

    @classmethod
    def is_builtin_ref(cls, combo_ref: str) -> bool:
        key = cls.ref_to_key(combo_ref)
        return bool(key and key in cls._get_builtin_entries())

    @classmethod
    def _legacy_label_to_ref(cls, label: str) -> str | None:
        if not label:
            return None

        entries = cls._get_builtin_entries()
        prefix = cls._legacy_prefix()
        if not label.startswith(prefix):
            return None

        match = cls._KEY_PATTERN.search(label)
        if match:
            key = match.group(1).strip()
            if key in entries:
                return cls.make_ref(key)

        key = label.replace(prefix, "", 1).strip()
        if key in entries:
            return cls.make_ref(key)

        # Fallback: resolve by generated label only when mapping is unambiguous.
        matched_refs = [
            combo_ref for combo_ref, combo_label in cls.iter_builtin_pairs() if combo_label == label
        ]
        if len(matched_refs) == 1:
            return matched_refs[0]
        return None

    @classmethod
    def to_ref(cls, value: str) -> str:
        if not value:
            return ""
        value = value.strip()
        key = cls.ref_to_key(value)
        if key:
            return cls.make_ref(key)

        legacy_ref = cls._legacy_label_to_ref(value)
        if legacy_ref:
            return legacy_ref

        matched_refs = [ref for ref, label in cls.iter_builtin_pairs() if value == label]
        if len(matched_refs) == 1:
            return matched_refs[0]

        return value

    @classmethod
    def _has_cn_name_collision(cls, key: str, entries: dict) -> bool:
        meta = entries.get(key)
        if not isinstance(meta, dict):
            return False
        cn_name = meta.get("cn_name")
        if not cn_name:
            return False

        same_name_count = 0
        for entry in entries.values():
            if isinstance(entry, dict) and entry.get("cn_name") == cn_name:
                same_name_count += 1
                if same_name_count > 1:
                    return True
        return False

    @classmethod
    def _label_for_key(cls, key: str) -> str:
        entries = cls._get_builtin_entries()
        if key not in entries:
            return key

        prefix = cls._legacy_prefix()
        meta = entries[key]
        locale = cls._locale_name()
        if isinstance(meta, dict):
            if locale == "zh_CN" and meta.get("cn_name"):
                if cls._has_cn_name_collision(key, entries):
                    return f"{prefix}{meta['cn_name']} ({key})"
                return f"{prefix}{meta['cn_name']}"
            else:
                label = meta['cls'].__name__
                return f"{prefix}{label}"
        return f"{prefix}{key}"

    @classmethod
    def to_label(cls, value: str) -> str:
        combo_ref = cls.to_ref(value)
        key = cls.ref_to_key(combo_ref)
        if not key:
            return value
        if key not in cls._get_builtin_entries():
            return value

        return cls._label_for_key(key)

    @classmethod
    def iter_builtin_pairs(cls) -> list[tuple[str, str]]:
        pairs = []
        for key in cls._get_builtin_entries().keys():
            combo_ref = cls.make_ref(key)
            pairs.append((combo_ref, cls._label_for_key(key)))
        return pairs
