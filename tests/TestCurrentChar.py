# Test case
import unittest
from pathlib import Path

from ok.test.TaskTestCase import TaskTestCase

from src.config import config
from src.tasks.trigger.AutoCombatTask import AutoCombatTask


class TestCurrentChar(TaskTestCase):
    task_class = AutoCombatTask

    config = config

    def assert_current_char(self, image, expected_index):
        if not Path(image).exists():
            self.skipTest(f"{image} not found")

        self.set_image(image)
        self.logger.info(f"target {image}")
        self.task.in_team()
        self.assertEqual(self.task.get_current_char_index(), expected_index)
        for index in range(4):
            result = self.task.is_char_at_index(index)
            self.assertEqual(
                result is True,
                index == expected_index,
                f"{image} index={index} scores={self.task._get_char_match_scores()}",
            )

    def test_current_char_temp_images(self):
        cases = [
            ("tests/images/02.png", 1),
            ("tests/images/01.png", 2),
            ("tests/images/current_char/current_0.png", 0),
            ("tests/images/current_char/current_1.png", 1),
            ("tests/images/current_char/current_2_covered.png", 2),
            ("tests/images/current_char/current_2_light.png", 2),
            ("tests/images/current_char/current_2_similar_back.png", 2),
            ("tests/images/current_char/current_2_low_conf.png", 2),
            ("tests/images/current_char/current_3_light_2.png", 3),
        ]
        for image, expected_index in cases:
            with self.subTest(image=image):
                self.assert_current_char(image, expected_index)

if __name__ == '__main__':
    unittest.main()
