import importlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from ok import Box

from src.gifts import GiftDb

gift_manager_module = importlib.import_module("src.gifts.GiftManager")
GiftManager = gift_manager_module.GiftManager


class TestGiftManager(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name) / "gift_configs"
        self.patches = [
            patch.object(gift_manager_module, "GIFT_CONFIG_DIR", str(root)),
            patch.object(gift_manager_module, "FRAMES_DIR", str(root / "frames")),
            patch.object(gift_manager_module, "DB_PATH", str(root / "db.json")),
        ]
        for mocked in self.patches:
            mocked.start()
        GiftManager._instance = None
        self.manager = GiftManager()

    def tearDown(self):
        GiftManager._instance = None
        for mocked in reversed(self.patches):
            mocked.stop()
        self.temp_dir.cleanup()

    def test_create_profile_persists_full_frame_and_priority(self):
        frame = np.full((120, 240, 3), 37, dtype=np.uint8)
        profile_id = self.manager.create_profile("安魂曲", frame, [7, 2, 7, 15], target_count=9)

        profile = self.manager.get_profile(profile_id)
        self.assertEqual(profile["display_name"], "安魂曲")
        self.assertEqual(profile["selected_slots"], [7, 2])
        self.assertEqual(profile["target_count"], 3)
        self.assertNotIn("width", profile)
        self.assertNotIn("height", profile)
        self.assertTrue((Path(gift_manager_module.FRAMES_DIR) / f"{profile_id}.png").exists())
        self.assertTrue(np.array_equal(self.manager.load_frame(profile_id), frame))

        GiftManager._instance = None
        reloaded = GiftManager()
        self.assertEqual(reloaded.get_profile(profile_id), profile)

    def test_saved_frame_blacks_out_configured_blur_area(self):
        frame = np.full((20, 30, 3), 255, dtype=np.uint8)
        with patch.object(
            gift_manager_module.og,
            "config",
            {"blur_area": lambda _width, _height: Box(3, 5, 7, 4)},
        ):
            profile_id = self.manager.create_profile("角色", frame, [0])

        saved = self.manager.load_frame(profile_id)
        self.assertTrue(np.all(saved[5:9, 3:10] == 0))
        self.assertTrue(np.all(frame == 255))

    def test_delete_profile_removes_frame(self):
        profile_id = self.manager.create_profile("角色", np.zeros((20, 30, 3), dtype=np.uint8), [0])
        frame_path = Path(gift_manager_module.FRAMES_DIR) / f"{profile_id}.png"
        self.manager.delete_profile(profile_id)

        self.assertIsNone(self.manager.get_profile(profile_id))
        self.assertFalse(frame_path.exists())

    def test_capture_can_be_configured_inline_after_saving(self):
        profile_id = self.manager.create_profile(
            "未命名角色", np.zeros((20, 30, 3), dtype=np.uint8), []
        )
        self.assertEqual(self.manager.get_enabled_profiles(), {})

        self.manager.update_profile(profile_id, selected_slots=[4, 1, 4])
        self.assertEqual(self.manager.get_profile(profile_id)["selected_slots"], [4, 1])
        self.assertIn(profile_id, self.manager.get_enabled_profiles())

    def test_blocked_slots_cannot_be_selected(self):
        profile_id = self.manager.create_profile(
            "角色", np.zeros((20, 30, 3), dtype=np.uint8), [0, 1], blocked_slots=[1]
        )
        self.assertEqual(self.manager.get_profile(profile_id)["selected_slots"], [0])
        self.assertEqual(self.manager.get_profile(profile_id)["blocked_slots"], [1])

        self.manager.update_profile(profile_id, selected_slots=[1, 2])
        self.assertEqual(self.manager.get_profile(profile_id)["selected_slots"], [2])

    def test_invalid_database_is_recovered(self):
        db_path = Path(gift_manager_module.DB_PATH)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        db_path.write_text("{not valid json", encoding="utf-8")

        loaded = GiftDb.load_db(str(db_path))
        self.assertEqual(loaded, GiftDb.default_db())

    def test_slot_normalization_and_layout(self):
        self.assertEqual(GiftDb.normalize_slots([0, "1", 0, -1, 10, "bad"]), [0, 1])
