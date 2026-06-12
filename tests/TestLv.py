# Test case
import unittest

from ok.test.TaskTestCase import TaskTestCase

from src.combat.CombatCheck import CombatCheck
from src.config import config


class TestOcrLv(TaskTestCase):
    task_class = CombatCheck

    config = config

    def test_enemy_lv_text(self):
        # Create a BattleReport object
        self.set_image('tests/images/03.png')
        result = self.task.find_lv()
        self.logger.info(f'enemy_lv_text: {result}')
        self.assertEqual(len(result), 2)

    def test_boss_lv_text(self):
        self.set_image('tests/images/04.png')
        result = self.task.is_boss()
        self.logger.info(f'test test_boss_lv_text: {result}')
        self.assertEqual(result, True)

if __name__ == '__main__':
    unittest.main()
