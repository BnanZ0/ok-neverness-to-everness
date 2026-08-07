import os
import shutil
import unittest
import uuid
from unittest.mock import patch

from src.char.custom.CustomCharDb import CustomCharDb
from src.char.custom.CustomCharManager import CustomCharManager


class TestTeamPresetPersistence(unittest.TestCase):
    def setUp(self):
        temp_root = os.path.join(os.getcwd(), "tests", ".tmp")
        os.makedirs(temp_root, exist_ok=True)
        self.temp_dir = os.path.join(temp_root, f"preset_{uuid.uuid4().hex}")
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
        self._reset_singletons()

    def tearDown(self):
        self._reset_singletons()
        for patcher in self.patchers:
            patcher.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @staticmethod
    def _reset_singletons():
        CustomCharManager._instance = None
        CustomCharDb.reset_instance()

    @staticmethod
    def _create_team(manager, prefix="team"):
        slots = []
        for index in range(4):
            char_id = manager.create_character(f"{prefix}_{index}", "")
            slots.append({"char_id": char_id, "impl_id": ""})
        return slots

    def test_named_preset_is_persistent_and_arm_is_one_shot(self):
        manager = CustomCharManager()
        slots = self._create_team(manager)

        self.assertTrue(manager.set_team_preset("team_speed", "Speed", slots, activate=True))
        self.assertTrue(manager.arm_team_preset("team_speed"))
        armed = manager.get_armed_team_preset()
        self.assertEqual(armed["preset_id"], "team_speed")
        self.assertEqual(armed["slots"], slots)

        consumed = manager.consume_armed_team_preset("team_speed")
        self.assertEqual(consumed["preset_id"], "team_speed")
        self.assertIsNone(manager.consume_armed_team_preset("team_speed"))
        after = manager.get_fixed_team()
        self.assertFalse(after["enabled"])
        self.assertEqual(after["armed_for_next_battle"], "")

        self._reset_singletons()
        reloaded = CustomCharManager()
        self.assertEqual(reloaded.get_team_preset("team_speed")["slots"], slots)

    def test_auto_mode_matches_only_one_unique_roster(self):
        manager = CustomCharManager()
        slots = self._create_team(manager)
        char_ids = [slot["char_id"] for slot in slots]
        self.assertTrue(manager.set_team_preset("team_a", "A", slots))
        self.assertTrue(manager.set_team_selection_mode("auto"))
        self.assertEqual(manager.get_fixed_team()["selection_mode"], "auto")
        self.assertEqual(manager.match_team_preset(list(reversed(char_ids))), "team_a")

        self.assertTrue(manager.set_team_preset("team_b", "B", list(reversed(slots))))
        self.assertIsNone(manager.match_team_preset(char_ids))
        self.assertEqual(manager.partial_preset_match_count(char_ids[:2]), 2)

    def test_deleting_character_disarms_incomplete_active_preset(self):
        manager = CustomCharManager()
        slots = self._create_team(manager)
        self.assertTrue(manager.set_team_preset("team_cleanup", "Cleanup", slots))
        self.assertTrue(manager.arm_team_preset("team_cleanup"))

        manager.delete_character(slots[0]["char_id"])

        fixed_team = manager.get_fixed_team()
        preset = manager.get_team_preset("team_cleanup")
        self.assertFalse(fixed_team["enabled"])
        self.assertEqual(fixed_team["armed_for_next_battle"], "")
        self.assertEqual(preset["slots"][0], {"char_id": "", "impl_id": ""})

    def test_failed_preset_write_rolls_back_memory(self):
        manager = CustomCharManager()
        slots = self._create_team(manager)
        before = manager.get_fixed_team()

        with patch.object(manager._db, "_save_locked", return_value=False):
            saved = manager.set_team_preset("team_safe", "Safe", slots)

        self.assertFalse(saved)
        self.assertEqual(manager.get_fixed_team(), before)


if __name__ == "__main__":
    unittest.main()
