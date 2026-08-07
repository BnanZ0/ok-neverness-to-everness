import json
import os
import re
import shutil
import uuid
from copy import deepcopy
from threading import Lock, RLock

from src.char.custom.CustomCharDbMigrator import CustomCharDbMigrator, MigrationContext

DB_SCHEMA_VERSION = 7
TEAM_SELECTION_MODES = {"manual", "auto"}
TEAM_PRESET_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


class CustomCharDb:
    """Process-wide owner of custom character persistence and current-schema invariants."""

    _instance = None
    _instance_lock = Lock()

    def __new__(cls, db_path: str, features_dir: str, context: MigrationContext, logger=None):
        with cls._instance_lock:
            if cls._instance is None or cls._instance.db_path != db_path:
                cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, db_path: str, features_dir: str, context: MigrationContext, logger=None):
        if getattr(self, "_initialized", False):
            return
        self.db_path = db_path
        self.features_dir = features_dir
        self.context = context
        self.logger = logger
        self._lock = RLock()
        self._data = self._default_data()
        self._initialized = True
        self.reload()

    @classmethod
    def reset_instance(cls):
        with cls._instance_lock:
            cls._instance = None

    @staticmethod
    def _as_text(value) -> str:
        return "" if value is None else str(value)

    @classmethod
    def _is_blank_text(cls, value) -> bool:
        return cls._as_text(value).strip() == ""

    @staticmethod
    def _default_fixed_team() -> dict:
        return {
            "enabled": False,
            "selection_mode": "manual",
            "active_preset_id": "",
            "armed_for_next_battle": "",
            "slots": [{"char_id": "", "impl_id": ""} for _ in range(4)],
            "presets": {},
        }

    @classmethod
    def _normalize_fixed_team_slot(cls, slot) -> dict:
        slot = slot if isinstance(slot, dict) else {}
        char_id = cls._as_text(slot.get("char_id", "")).strip()
        impl_id = cls._as_text(slot.get("impl_id", "")).strip()
        if cls._is_blank_text(char_id):
            char_id = ""
            impl_id = ""
        return {"char_id": char_id, "impl_id": impl_id}

    @classmethod
    def _normalize_team_slots(cls, slots) -> list[dict]:
        normalized = [cls._normalize_fixed_team_slot(None) for _ in range(4)]
        if isinstance(slots, list):
            for index in range(min(4, len(slots))):
                normalized[index] = cls._normalize_fixed_team_slot(slots[index])
        return normalized

    @classmethod
    def _is_complete_team_slots(cls, slots) -> bool:
        char_ids = [slot["char_id"] for slot in cls._normalize_team_slots(slots)]
        return all(char_ids) and len(set(char_ids)) == 4

    @classmethod
    def _normalize_team_preset(cls, preset, preset_id="") -> dict:
        preset = preset if isinstance(preset, dict) else {}
        name = cls._as_text(preset.get("name", "")).strip() or cls._as_text(preset_id).strip()
        return {
            "name": name,
            "slots": cls._normalize_team_slots(preset.get("slots", [])),
        }

    @classmethod
    def _normalize_fixed_team_config(cls, config) -> dict:
        normalized = cls._default_fixed_team()
        if not isinstance(config, dict):
            return normalized

        normalized["enabled"] = bool(config.get("enabled", False))
        mode = cls._as_text(config.get("selection_mode", "manual")).strip().lower()
        if mode in TEAM_SELECTION_MODES:
            normalized["selection_mode"] = mode
        normalized["slots"] = cls._normalize_team_slots(config.get("slots", []))

        raw_presets = config.get("presets", {})
        if isinstance(raw_presets, dict):
            for raw_preset_id, raw_preset in raw_presets.items():
                preset_id = cls._as_text(raw_preset_id).strip()
                if preset_id and TEAM_PRESET_ID_PATTERN.fullmatch(preset_id):
                    normalized["presets"][preset_id] = cls._normalize_team_preset(
                        raw_preset, preset_id
                    )

        active_id = cls._as_text(config.get("active_preset_id", "")).strip()
        armed_id = cls._as_text(config.get("armed_for_next_battle", "")).strip()
        if active_id in normalized["presets"]:
            normalized["active_preset_id"] = active_id
            normalized["slots"] = deepcopy(normalized["presets"][active_id]["slots"])
        elif active_id:
            normalized["enabled"] = False

        if armed_id in normalized["presets"]:
            normalized["armed_for_next_battle"] = armed_id
            normalized["active_preset_id"] = armed_id
            normalized["slots"] = deepcopy(normalized["presets"][armed_id]["slots"])
            normalized["enabled"] = True
        elif armed_id:
            normalized["enabled"] = False
        return normalized

    @classmethod
    def _default_data(cls) -> dict:
        return {
            "schema_version": DB_SCHEMA_VERSION,
            "combos": {},
            "characters": {},
            "features": {},
            "fixed_team": cls._default_fixed_team(),
        }

    @classmethod
    def _character_name_from_record(cls, char_id: str, char_data: dict) -> str:
        name = cls._as_text(char_data.get("name", "")).strip()
        if not cls._is_blank_text(name):
            return name
        fallback = cls._as_text(char_id).strip()
        return fallback if not cls._is_blank_text(fallback) else "unnamed"

    @classmethod
    def _unique_name(cls, name: str, used_names: set[str]) -> str:
        name = name.strip()
        if cls._is_blank_text(name):
            name = "unnamed"
        candidate = name
        suffix = 2
        while candidate in used_names:
            candidate = f"{name}_{suffix}"
            suffix += 1
        used_names.add(candidate)
        return candidate

    def _read_raw_data(self) -> dict:
        """Read JSON only; migration and normalization have separate responsibilities."""
        if not os.path.exists(self.db_path):
            return self._default_data()

        try:
            with open(self.db_path, "r", encoding="utf-8") as file:
                data = json.load(file)
            if isinstance(data, dict):
                return data
            if self.logger:
                self.logger.warning("Custom char DB root must be an object; using defaults")
        except Exception as error:
            if self.logger:
                self.logger.error("Failed to load custom char DB", error)
        return self._default_data()

    def _backup_before_migration(self) -> bool:
        """Preserve a pre-v7 source database once, before saving a migration."""
        if not os.path.exists(self.db_path):
            return True

        backup_path = f"{self.db_path}.pre-v7.bak"
        if os.path.exists(backup_path):
            return True

        try:
            shutil.copy2(self.db_path, backup_path)
            return True
        except Exception as error:
            if self.logger:
                self.logger.error("Failed to back up custom char DB before migration", error)
            return False

    def _save_locked(self):
        try:
            self._data["schema_version"] = DB_SCHEMA_VERSION
            db_dir = os.path.dirname(self.db_path)
            if db_dir:
                os.makedirs(db_dir, exist_ok=True)
            temp_path = f"{self.db_path}.tmp"
            with open(temp_path, "w", encoding="utf-8") as file:
                json.dump(self._data, file, indent=4, ensure_ascii=False)
            os.replace(temp_path, self.db_path)
            return True
        except Exception as error:
            if self.logger:
                self.logger.error("Failed to save custom char DB", error)
                return False
            raise

    def _commit_fixed_team_locked(self, fixed_team) -> bool:
        previous = deepcopy(self._data.get("fixed_team", self._default_fixed_team()))
        self._data["fixed_team"] = self._normalize_fixed_team_config(fixed_team)
        try:
            saved = self._save_locked()
        except Exception:
            self._data["fixed_team"] = previous
            raise
        if saved:
            return True
        self._data["fixed_team"] = previous
        return False

    def _normalize_current_data(self) -> bool:
        """Normalize the current v7 record shape without interpreting historical fields."""
        db = self._data
        modified = False

        if not isinstance(db.get("combos"), dict):
            db["combos"] = {}
            modified = True

        valid_combos = {}
        for combo_id, combo_data in db["combos"].items():
            combo_id = self._as_text(combo_id).strip()
            if self._is_blank_text(combo_id) or self.context.is_builtin_impl(combo_id):
                modified = True
                continue
            if isinstance(combo_data, dict):
                combo_name = self._as_text(combo_data.get("name", combo_id)).strip()
                content = self._as_text(combo_data.get("content", ""))
            else:
                combo_name = combo_id
                content = self._as_text(combo_data)
                modified = True
            if self._is_blank_text(combo_name):
                combo_name = combo_id
                modified = True
            valid_combos[combo_id] = {"name": combo_name, "content": content}
        if valid_combos != db["combos"]:
            db["combos"] = valid_combos
            modified = True

        if not isinstance(db.get("characters"), dict):
            db["characters"] = {}
            modified = True
        if not isinstance(db.get("features"), dict):
            db["features"] = {}
            modified = True

        fixed_team = self._normalize_fixed_team_config(db.get("fixed_team"))
        if fixed_team != db.get("fixed_team"):
            db["fixed_team"] = fixed_team
            modified = True

        used_names = set()
        for char_id, char_data in db["characters"].items():
            if not isinstance(char_data, dict):
                db["characters"][char_id] = {
                    "name": self._unique_name(self._as_text(char_id), used_names),
                    "impl_id": "",
                    "feature_ids": [],
                }
                modified = True
                continue

            char_name = self._unique_name(
                self._character_name_from_record(char_id, char_data), used_names
            )
            if char_data.get("name") != char_name:
                char_data["name"] = char_name
                modified = True

            impl_id = self._as_text(char_data.get("impl_id", "")).strip()
            if (
                impl_id
                and not self.context.is_builtin_impl(impl_id)
                and impl_id not in db["combos"]
            ):
                impl_id = ""
                modified = True
            if impl_id != char_data.get("impl_id", ""):
                char_data["impl_id"] = impl_id
                modified = True

            feature_ids = char_data.get("feature_ids", [])
            if not isinstance(feature_ids, list):
                feature_ids = []
                modified = True
            valid_feature_ids = []
            for feature_id in feature_ids:
                path = os.path.join(self.features_dir, f"{feature_id}.png")
                if os.path.exists(path):
                    valid_feature_ids.append(feature_id)
                else:
                    modified = True
            char_data["feature_ids"] = valid_feature_ids

        for feature_id in list(db["features"].keys()):
            path = os.path.join(self.features_dir, f"{feature_id}.png")
            if not os.path.exists(path):
                del db["features"][feature_id]
                modified = True

        fixed_team = self._normalize_fixed_team_config(db.get("fixed_team"))
        valid_char_ids = set(db["characters"])
        valid_combo_ids = set(db["combos"])
        slot_groups = [fixed_team["slots"]]
        slot_groups.extend(preset["slots"] for preset in fixed_team["presets"].values())
        for slots in slot_groups:
            for slot in slots:
                if slot["char_id"] and slot["char_id"] not in valid_char_ids:
                    slot["char_id"] = ""
                    slot["impl_id"] = ""
                    modified = True
                    continue
                impl_id = slot["impl_id"]
                if (
                    impl_id
                    and not self.context.is_builtin_impl(impl_id)
                    and impl_id not in valid_combo_ids
                ):
                    slot["impl_id"] = ""
                    modified = True

        active_id = fixed_team["active_preset_id"]
        if active_id:
            active_slots = fixed_team["presets"][active_id]["slots"]
            fixed_team["slots"] = deepcopy(active_slots)
            if not self._is_complete_team_slots(active_slots):
                fixed_team["enabled"] = False
                fixed_team["armed_for_next_battle"] = ""
        if fixed_team != db.get("fixed_team"):
            db["fixed_team"] = fixed_team
            modified = True

        return modified

    def save(self):
        with self._lock:
            return self._save_locked()

    def reload(self):
        with self._lock:
            self._data = self._read_raw_data()
            migration = CustomCharDbMigrator(self.context, DB_SCHEMA_VERSION).migrate(self._data)
            self._data = migration.db
            for diagnostic in migration.diagnostics:
                if self.logger:
                    self.logger.warning(diagnostic)
            if migration.needs_backup and not self._backup_before_migration():
                raise RuntimeError("Failed to create custom character database migration backup")
            if migration.modified:
                self._save_locked()
            if self._normalize_current_data():
                self._save_locked()

    def find_character_id_by_name(self, char_name: str) -> str | None:
        target = self._as_text(char_name).strip()
        if self._is_blank_text(target):
            return None
        with self._lock:
            for char_id, char_data in self._data["characters"].items():
                if (
                    isinstance(char_data, dict)
                    and self._character_name_from_record(char_id, char_data) == target
                ):
                    return char_id
        return None

    def _generate_character_id(self) -> str:
        while True:
            char_id = f"char_{uuid.uuid4().hex}"
            if char_id not in self._data["characters"]:
                return char_id

    def _generate_combo_id(self) -> str:
        while True:
            combo_id = f"combo_{uuid.uuid4().hex}"
            if combo_id not in self._data["combos"] and not self.context.is_builtin_impl(combo_id):
                return combo_id

    def find_combo_id_by_name(self, combo_name: str) -> str:
        combo_name = self._as_text(combo_name).strip()
        if self._is_blank_text(combo_name):
            return ""
        with self._lock:
            for combo_id, combo_data in self._data["combos"].items():
                if isinstance(combo_data, dict) and combo_data.get("name") == combo_name:
                    return combo_id
        return ""

    def add_combo(self, combo_name: str, content: str, combo_id: str | None = None) -> str:
        combo_name = self._as_text(combo_name).strip()
        if self._is_blank_text(combo_name):
            return ""
        with self._lock:
            combo_id = (
                combo_id or self.find_combo_id_by_name(combo_name) or self._generate_combo_id()
            )
            if self.context.is_builtin_impl(combo_id):
                return ""
            self._data["combos"][combo_id] = {"name": combo_name, "content": self._as_text(content)}
            self._save_locked()
            return combo_id

    def update_combo(self, combo_id: str, content: str, combo_name: str | None = None) -> bool:
        combo_id = self._as_text(combo_id)
        with self._lock:
            record = self._data["combos"].get(combo_id)
            if not isinstance(record, dict) or self.context.is_builtin_impl(combo_id):
                return False
            if combo_name is not None and not self._is_blank_text(combo_name):
                record["name"] = self._as_text(combo_name).strip()
            record["content"] = self._as_text(content)
            self._save_locked()
            return True

    def _remove_fixed_team_references_locked(self, *, char_id="", combo_id="") -> bool:
        fixed_team = self._normalize_fixed_team_config(self._data.get("fixed_team"))
        changed = False
        slot_groups = [fixed_team["slots"]]
        slot_groups.extend(preset["slots"] for preset in fixed_team["presets"].values())
        for slots in slot_groups:
            for slot in slots:
                if char_id and slot["char_id"] == char_id:
                    slot["char_id"] = ""
                    slot["impl_id"] = ""
                    changed = True
                elif combo_id and slot["impl_id"] == combo_id:
                    slot["impl_id"] = ""
                    changed = True

        active_id = fixed_team["active_preset_id"]
        if active_id:
            active_slots = fixed_team["presets"][active_id]["slots"]
            fixed_team["slots"] = deepcopy(active_slots)
            if not self._is_complete_team_slots(active_slots):
                fixed_team["enabled"] = False
                fixed_team["armed_for_next_battle"] = ""
        if changed:
            self._data["fixed_team"] = self._normalize_fixed_team_config(fixed_team)
        return changed

    def delete_combo(self, combo_id: str):
        combo_id = self._as_text(combo_id)
        with self._lock:
            deleted = self._data["combos"].pop(combo_id, None) is not None
            fixed_team_changed = self._remove_fixed_team_references_locked(combo_id=combo_id)
            if deleted or fixed_team_changed:
                self._save_locked()

    def has_custom_combo(self, combo_id: str) -> bool:
        with self._lock:
            return self._as_text(combo_id) in self._data["combos"]

    def has_impl_id(self, impl_id: str) -> bool:
        return self.context.is_builtin_impl(impl_id) or self.has_custom_combo(impl_id)

    def get_combo(self, combo_id: str) -> str:
        with self._lock:
            combo_data = self._data["combos"].get(self._as_text(combo_id))
            return (
                self._as_text(combo_data.get("content", "")) if isinstance(combo_data, dict) else ""
            )

    def get_custom_combo_name(self, combo_id: str) -> str:
        with self._lock:
            combo_data = self._data["combos"].get(self._as_text(combo_id))
            return (
                self._as_text(combo_data.get("name", combo_id))
                if isinstance(combo_data, dict)
                else ""
            )

    def get_custom_combo_items(self) -> list[tuple[str, str]]:
        with self._lock:
            return [
                (self._as_text(data.get("name", combo_id)), combo_id)
                for combo_id, data in self._data["combos"].items()
                if isinstance(data, dict)
            ]

    def create_character(self, char_name: str, impl_id: str) -> str:
        char_name = self._as_text(char_name).strip()
        impl_id = self._as_text(impl_id)
        if self._is_blank_text(char_name):
            return ""
        with self._lock:
            existing_id = self.find_character_id_by_name(char_name)
            if existing_id:
                return existing_id
            if impl_id and not self.has_impl_id(impl_id):
                impl_id = ""
            char_id = self._generate_character_id()
            self._data["characters"][char_id] = {
                "name": char_name,
                "impl_id": impl_id,
                "feature_ids": [],
            }
            self._save_locked()
            return char_id

    def update_character(self, char_id: str, char_name=None, impl_id=None) -> bool:
        with self._lock:
            record = self._data["characters"].get(char_id)
            if not isinstance(record, dict):
                return False
            if char_name is not None:
                char_name = self._as_text(char_name).strip()
                if self._is_blank_text(char_name):
                    return False
                existing_id = self.find_character_id_by_name(char_name)
                if existing_id and existing_id != char_id:
                    return False
                record["name"] = char_name
            if impl_id is not None:
                impl_id = self._as_text(impl_id)
                record["impl_id"] = impl_id if not impl_id or self.has_impl_id(impl_id) else ""
            self._save_locked()
            return True

    def delete_character(self, char_id: str) -> list[str]:
        with self._lock:
            record = self._data["characters"].pop(char_id, None)
            if not isinstance(record, dict):
                return []
            feature_ids = list(record.get("feature_ids", []))
            for feature_id in feature_ids:
                self._data["features"].pop(feature_id, None)
            self._remove_fixed_team_references_locked(char_id=char_id)
            self._save_locked()
            return feature_ids

    def add_feature(self, char_id: str, feature_id: str, width=0, height=0) -> bool:
        with self._lock:
            record = self._data["characters"].get(char_id)
            if not isinstance(record, dict):
                return False
            self._data["features"][feature_id] = {"width": width, "height": height}
            record.setdefault("feature_ids", []).append(feature_id)
            self._save_locked()
            return True

    def remove_feature(self, char_id: str, feature_id: str) -> bool:
        with self._lock:
            record = self._data["characters"].get(char_id)
            if not isinstance(record, dict) or feature_id not in record.get("feature_ids", []):
                return False
            record["feature_ids"].remove(feature_id)
            self._data["features"].pop(feature_id, None)
            self._save_locked()
            return True

    def get_feature_ids(self) -> list[str]:
        with self._lock:
            feature_ids = set(self._data["features"].keys())
            for char_data in self._data["characters"].values():
                if isinstance(char_data, dict):
                    feature_ids.update(char_data.get("feature_ids", []))
            return list(feature_ids)

    def get_feature_info(self, feature_id: str) -> dict:
        with self._lock:
            feature_info = self._data["features"].get(feature_id, {})
            return dict(feature_info) if isinstance(feature_info, dict) else {}

    def get_character_feature_snapshot(self) -> dict[str, list[str]]:
        with self._lock:
            return {
                char_id: list(char_data.get("feature_ids", []))
                for char_id, char_data in self._data["characters"].items()
                if isinstance(char_data, dict)
            }

    def get_character_records(self) -> dict[str, dict]:
        with self._lock:
            return {
                char_id: dict(char_data)
                for char_id, char_data in self._data["characters"].items()
                if isinstance(char_data, dict)
            }

    def get_character_record(self, char_id: str) -> dict | None:
        with self._lock:
            record = self._data["characters"].get(char_id)
            return dict(record) if isinstance(record, dict) else None

    def get_fixed_team(self) -> dict:
        with self._lock:
            fixed_team = self._normalize_fixed_team_config(self._data.get("fixed_team"))
            return deepcopy(fixed_team)

    def set_fixed_team(self, enabled: bool, slots) -> bool:
        with self._lock:
            fixed_team = self._normalize_fixed_team_config(self._data.get("fixed_team"))
            fixed_team.update(
                {
                    "enabled": bool(enabled),
                    "selection_mode": "manual",
                    "active_preset_id": "",
                    "armed_for_next_battle": "",
                    "slots": self._normalize_team_slots(slots),
                }
            )
            return self._commit_fixed_team_locked(fixed_team)

    def clear_fixed_team(self) -> bool:
        with self._lock:
            fixed_team = self._normalize_fixed_team_config(self._data.get("fixed_team"))
            fixed_team.update(
                {
                    "enabled": False,
                    "selection_mode": "manual",
                    "active_preset_id": "",
                    "armed_for_next_battle": "",
                    "slots": self._normalize_team_slots([]),
                }
            )
            return self._commit_fixed_team_locked(fixed_team)

    def get_team_presets(self) -> dict:
        with self._lock:
            fixed_team = self._normalize_fixed_team_config(self._data.get("fixed_team"))
            return deepcopy(fixed_team["presets"])

    def get_team_preset(self, preset_id: str) -> dict | None:
        preset_id = self._as_text(preset_id).strip()
        with self._lock:
            fixed_team = self._normalize_fixed_team_config(self._data.get("fixed_team"))
            preset = fixed_team["presets"].get(preset_id)
            return {"preset_id": preset_id, **deepcopy(preset)} if preset else None

    def set_team_preset(
        self,
        preset_id: str,
        name: str,
        slots,
        *,
        activate: bool = True,
    ) -> bool:
        preset_id = self._as_text(preset_id).strip()
        name = self._as_text(name).strip()
        normalized_slots = self._normalize_team_slots(slots)
        if (
            not TEAM_PRESET_ID_PATTERN.fullmatch(preset_id)
            or not name
            or not self._is_complete_team_slots(normalized_slots)
        ):
            return False

        with self._lock:
            fixed_team = self._normalize_fixed_team_config(self._data.get("fixed_team"))
            fixed_team["presets"][preset_id] = {
                "name": name,
                "slots": normalized_slots,
            }
            if activate:
                fixed_team["active_preset_id"] = preset_id
                fixed_team["slots"] = deepcopy(normalized_slots)
                fixed_team["enabled"] = False
                fixed_team["armed_for_next_battle"] = ""
            return self._commit_fixed_team_locked(fixed_team)

    def delete_team_preset(self, preset_id: str) -> bool:
        preset_id = self._as_text(preset_id).strip()
        with self._lock:
            fixed_team = self._normalize_fixed_team_config(self._data.get("fixed_team"))
            if preset_id not in fixed_team["presets"]:
                return False
            del fixed_team["presets"][preset_id]
            if fixed_team["active_preset_id"] == preset_id:
                fixed_team["active_preset_id"] = ""
                fixed_team["slots"] = self._normalize_team_slots([])
                fixed_team["enabled"] = False
            if fixed_team["armed_for_next_battle"] == preset_id:
                fixed_team["armed_for_next_battle"] = ""
                fixed_team["enabled"] = False
            return self._commit_fixed_team_locked(fixed_team)

    def arm_team_preset(self, preset_id: str) -> bool:
        preset_id = self._as_text(preset_id).strip()
        with self._lock:
            fixed_team = self._normalize_fixed_team_config(self._data.get("fixed_team"))
            preset = fixed_team["presets"].get(preset_id)
            if not preset or not self._is_complete_team_slots(preset["slots"]):
                return False
            fixed_team["selection_mode"] = "manual"
            fixed_team["active_preset_id"] = preset_id
            fixed_team["armed_for_next_battle"] = preset_id
            fixed_team["slots"] = deepcopy(preset["slots"])
            fixed_team["enabled"] = True
            return self._commit_fixed_team_locked(fixed_team)

    def set_team_selection_mode(self, mode: str) -> bool:
        mode = self._as_text(mode).strip().lower()
        if mode not in TEAM_SELECTION_MODES:
            return False
        with self._lock:
            fixed_team = self._normalize_fixed_team_config(self._data.get("fixed_team"))
            fixed_team["selection_mode"] = mode
            if mode == "auto":
                fixed_team["armed_for_next_battle"] = ""
                fixed_team["enabled"] = False
            return self._commit_fixed_team_locked(fixed_team)

    def get_armed_team_preset(self) -> dict | None:
        with self._lock:
            fixed_team = self._normalize_fixed_team_config(self._data.get("fixed_team"))
            preset_id = fixed_team["armed_for_next_battle"]
            preset = fixed_team["presets"].get(preset_id)
            return {"preset_id": preset_id, **deepcopy(preset)} if preset else None

    def consume_armed_team_preset(self, expected_preset_id: str = "") -> dict | None:
        with self._lock:
            fixed_team = self._normalize_fixed_team_config(self._data.get("fixed_team"))
            preset_id = fixed_team["armed_for_next_battle"]
            if expected_preset_id and preset_id != expected_preset_id:
                return None
            preset = fixed_team["presets"].get(preset_id)
            if not preset:
                return None
            result = {"preset_id": preset_id, **deepcopy(preset)}
            fixed_team["armed_for_next_battle"] = ""
            fixed_team["enabled"] = False
            return result if self._commit_fixed_team_locked(fixed_team) else None

    def match_team_preset(self, char_ids) -> str | None:
        normalized_ids = [self._as_text(char_id).strip() for char_id in char_ids]
        if len(normalized_ids) != 4 or not all(normalized_ids) or len(set(normalized_ids)) != 4:
            return None
        with self._lock:
            fixed_team = self._normalize_fixed_team_config(self._data.get("fixed_team"))
            target_set = set(normalized_ids)
            matches = []
            for preset_id, preset in fixed_team["presets"].items():
                preset_ids = [slot["char_id"] for slot in preset["slots"]]
                if len(set(preset_ids)) == 4 and set(preset_ids) == target_set:
                    matches.append(preset_id)
            return matches[0] if len(matches) == 1 else None

    def partial_preset_match_count(self, char_ids) -> int:
        normalized_ids = [self._as_text(char_id).strip() for char_id in char_ids if char_id]
        if not normalized_ids:
            return 0
        query_set = set(normalized_ids)
        with self._lock:
            fixed_team = self._normalize_fixed_team_config(self._data.get("fixed_team"))
            return sum(
                1
                for preset in fixed_team["presets"].values()
                if query_set <= {slot["char_id"] for slot in preset["slots"]}
            )
