# Test case
import unittest

from ok.test.TaskTestCase import TaskTestCase

from src.combat.BaseCombatTask import BaseCombatTask
from src.config import config


class TestBackendUlt(TaskTestCase):
    task_class = BaseCombatTask

    config = config

    def ultimate_available(self, index):
        result = self.task.ultimate_available(index)
        self.logger.info(f'ultimate_available: {result}')
        return result

    def test_ultimate_available(self):
        cases = [
            ("tests/images/backend_ult/01.png", [True, True, True, False]), # light 1080p
            ("tests/images/backend_ult/02.png", [False, True, True, True]), # normal 1080p
            ("tests/images/backend_ult/03.png", [True, True, True, False]), # light 1440p
            ("tests/images/backend_ult/04.png", [False, True, True, True]), # normal 1440p
        ]
        for image, expected in cases:
            self.logger.info(f"image {image}")
            self.set_image(image)
            for i, should_be_available in enumerate(expected):
                with self.subTest(image=image, index=i):
                    self.assertEqual(bool(self.ultimate_available(i)), should_be_available)

if __name__ == '__main__':
    unittest.main()
