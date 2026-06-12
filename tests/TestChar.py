# Test case
import unittest

from ok.test.TaskTestCase import TaskTestCase

from src.config import config
from src.tasks.trigger.AutoCombatTask import AutoCombatTask


class TestAutoCombatTask(TaskTestCase):
    task_class = AutoCombatTask

    config = config

    def test_in_team1(self):
        # Create a BattleReport object
        self.set_image('tests/images/01.png')
        in_team, current_index, count = self.task.in_team()
        self.logger.info(f'test1 in_team: {in_team}, current_index: {current_index}, count: {count}')
        self.assertEqual(in_team, True)

    def test_in_team2(self):
        # Create a BattleReport object
        self.set_image('tests/images/02.png')
        in_team, current_index, count = self.task.in_team()
        self.logger.info(f'test2 in_team: {in_team}, current_index: {current_index}, count: {count}')
        self.assertEqual(in_team, True)



if __name__ == '__main__':
    unittest.main()
