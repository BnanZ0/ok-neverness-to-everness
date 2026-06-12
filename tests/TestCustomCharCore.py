import json
import os
import shutil
import unittest
import uuid
from unittest.mock import Mock, patch

from src.char.custom.CustomChar import CustomChar
from src.char.custom.CustomCharManager import DB_SCHEMA_VERSION, CustomCharManager

PREDEFINED_CHARACTER_REF = "builtin:char_zero"

class TestCustomCharCore(unittest.TestCase):
    def setUp(self):
        temp_root = os.path.join(os.getcwd(), "tests", ".tmp")
        os.makedirs(temp_root, exist_ok=True)
        self.temp_dir = os.path.join(temp_root, f"case_{uuid.uuid4().hex}")
        os.makedirs(self.temp_dir, exist_ok=True)
        self.db_path = os.path.join(self.temp_dir, "db.json")
        self.features_dir = os.path.join(self.temp_dir, "features")
        os.makedirs(self.features_dir, exist_ok=True)

        self.patchers = [
            patch("src.char.custom.CustomCharManager.CUSTOM_CHARS_DIR", self.temp_dir),
            patch("src.char.custom.CustomCharManager.DB_PATH", self.db_path),
            patch("src.char.custom.CustomCharManager.FEATURES_DIR", self.features_dir),
        ]
        for patcher in self.patchers:
            patcher.start()
        CustomCharManager._instance = None

    def tearDown(self):
        for patcher in self.patchers:
            patcher.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        CustomCharManager._instance = None

    def _write_db(self, data):
        with open(self.db_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def test_db_schema_migrates_legacy_combo_name(self):
        legacy = {
            "schema_version": 3,
            "combos": {"combo_old": "skill,wait(0.1)"},
            "characters": {
                "char_legacy": {
                    "combo_name": "combo_old",
                    "feature_ids": [],
                }
            },
            "features": {},
        }
        self._write_db(legacy)

        manager = CustomCharManager()
        self.assertEqual(manager.db["schema_version"], DB_SCHEMA_VERSION)
        raw = next(iter(manager.db["characters"].values()))
        self.assertEqual(raw["name"], "char_legacy")
        self.assertEqual(raw["combo_ref"], "combo_old")
        self.assertNotIn("combo_name", raw)

        info = manager.get_character_info("char_legacy")
        self.assertIsNotNone(info)
        self.assertEqual(info["combo_ref"], "combo_old")
        self.assertNotIn("combo_name", info)

    def test_db_schema_migrates_legacy_builtin_label(self):
        bootstrap = {
            "schema_version": DB_SCHEMA_VERSION,
            "combos": {},
            "characters": {},
            "features": {},
        }
        self._write_db(bootstrap)
        manager = CustomCharManager()
        legacy_builtin_label = manager.to_combo_label(PREDEFINED_CHARACTER_REF)

        legacy = {
            "schema_version": 3,
            "combos": {},
            "characters": {
                "char_builtin": {
                    "combo_name": legacy_builtin_label,
                    "feature_ids": [],
                }
            },
            "features": {},
        }
        self._write_db(legacy)
        CustomCharManager._instance = None

        manager = CustomCharManager()
        info = manager.get_character_info("char_builtin")
        self.assertIsNotNone(info)
        self.assertEqual(info["combo_ref"], PREDEFINED_CHARACTER_REF)
        self.assertNotIn("combo_name", info)

    def test_db_schema_remaps_custom_combo_key_conflicting_with_builtin(self):
        legacy = {
            "schema_version": 3,
            "combos": {
                PREDEFINED_CHARACTER_REF: "skill,wait(0.1)"
            },
            "characters": {
                "char_conflict": {
                    "combo_name": PREDEFINED_CHARACTER_REF,
                    "feature_ids": [],
                }
            },
            "features": {},
        }
        self._write_db(legacy)

        manager = CustomCharManager()
        remapped_key = f"{manager.CUSTOM_COMBO_PREFIX}{PREDEFINED_CHARACTER_REF}"

        self.assertNotIn(PREDEFINED_CHARACTER_REF, manager.db["combos"])
        self.assertIn(remapped_key, manager.db["combos"])
        self.assertEqual(manager.get_combo(remapped_key), "skill,wait(0.1)")

        info = manager.get_character_info("char_conflict")
        self.assertIsNotNone(info)
        self.assertEqual(info["combo_ref"], remapped_key)
        self.assertNotIn("combo_name", info)
        self.assertEqual(manager.get_combo(info["combo_ref"]), "skill,wait(0.1)")

    def test_validate_combo_syntax_reports_line_and_column(self):
        is_valid, error = CustomChar.validate_combo_syntax("skill,wait(0.5)")
        self.assertTrue(is_valid)
        self.assertIsNone(error)

        is_valid, error = CustomChar.validate_combo_syntax("skill(\nwait(0.5)")
        self.assertFalse(is_valid)
        self.assertIsNotNone(error)
        self.assertIn("line", error)
        self.assertIn("column", error)

    def test_validate_combo_rejects_unsupported_and_unknown(self):
        is_valid, error = CustomChar.validate_combo_syntax("wait(**data)")
        self.assertFalse(is_valid)
        self.assertIn("**kwargs", error or "")

        is_valid, error = CustomChar.validate_combo_syntax("not_a_command")
        self.assertFalse(is_valid)
        self.assertIn("unknown command", error or "")

    def test_validate_combo_supports_if_command(self):
        is_valid, error = CustomChar.validate_combo_syntax("if_(ultimate, skill)")
        self.assertTrue(is_valid)
        self.assertIsNone(error)

        is_valid, error = CustomChar.validate_combo_syntax("if_(ultimate, l_click(2))")
        self.assertTrue(is_valid)
        self.assertIsNone(error)

        is_valid, error = CustomChar.validate_combo_syntax("if_(ultimate, skill, wait(0.1))")
        self.assertTrue(is_valid)
        self.assertIsNone(error)

    def test_validate_combo_rejects_invalid_if_usage(self):
        is_valid, error = CustomChar.validate_combo_syntax("if_(wait, skill)")
        self.assertFalse(is_valid)
        self.assertIn("not enabled as if_ condition", error or "")

        is_valid, error = CustomChar.validate_combo_syntax("if_(ultimate)")
        self.assertFalse(is_valid)
        self.assertIn("at least 2", error or "")

        is_valid, error = CustomChar.validate_combo_syntax("if_(ultimate, skill, wait=0.1)")
        self.assertFalse(is_valid)
        self.assertIn("only supports positional", error or "")

    def test_if_runtime_executes_then_only_when_condition_is_true_bool(self):
        char = object.__new__(CustomChar)
        char.logger = Mock()
        state = {"then_count": 0}

        cond_true = ("ultimate", lambda self: True, [], {}, "ultimate")
        then_cmds = [
            ("skill", lambda self: state.__setitem__("then_count", state["then_count"] + 1), [], {}, "skill"),
            ("wait", lambda self: state.__setitem__("then_count", state["then_count"] + 1), [], {}, "wait(0.1)"),
        ]
        result = char._execute_if_command(cond_true, then_cmds)
        self.assertTrue(result)
        self.assertEqual(state["then_count"], 2)

        cond_false = ("ultimate", lambda self: False, [], {}, "ultimate")
        result = char._execute_if_command(cond_false, then_cmds)
        self.assertFalse(result)
        self.assertEqual(state["then_count"], 2)

    def test_if_runtime_treats_non_bool_condition_as_false(self):
        char = object.__new__(CustomChar)
        char.logger = Mock()
        state = {"then_count": 0}

        cond_non_bool = ("ultimate", lambda self: "yes", [], {}, "ultimate")
        then_cmds = [("skill", lambda self: state.__setitem__("then_count", state["then_count"] + 1), [], {}, "skill")]
        result = char._execute_if_command(cond_non_bool, then_cmds)

        self.assertFalse(result)
        self.assertEqual(state["then_count"], 0)
        char.logger.warning.assert_called_once()
        self.assertIn("non-bool", char.logger.warning.call_args[0][0])

    def test_validate_db_removes_missing_feature_assets_and_metadata(self):
        existing_fid = "feat_exists"
        missing_fid = "feat_missing"

        with open(os.path.join(self.features_dir, f"{existing_fid}.png"), "wb") as f:
            f.write(b"ok")

        legacy = {
            "schema_version": DB_SCHEMA_VERSION,
            "combos": {},
            "characters": {
                "char_a": {
                    "combo_ref": "",
                    "feature_ids": [existing_fid, missing_fid],
                }
            },
            "features": {
                existing_fid: {"width": 1920, "height": 1080},
                missing_fid: {"width": 1920, "height": 1080},
            },
        }
        self._write_db(legacy)

        manager = CustomCharManager()

        char_info = manager.get_character_info("char_a")
        self.assertIsNotNone(char_info)
        self.assertEqual(char_info["feature_ids"], [existing_fid])
        self.assertIn(existing_fid, manager.db["features"])
        self.assertNotIn(missing_fid, manager.db["features"])


if __name__ == "__main__":
    unittest.main()
