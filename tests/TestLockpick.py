# Test case
import time
import unittest

from ok.test.TaskTestCase import TaskTestCase

from src.config import config
from src.tasks.AutoHeistTask import AutoHeistTask


class TestOcrLv(TaskTestCase):
    task_class = AutoHeistTask

    config = config

    def test_lock_pick_1(self):
        # Create a BattleReport object
        self.set_image('tests/images/lock_pick/01.png')
        start_time = time.time()
        result = self.task.is_lock_pick_active()
        self.logger.info(f'test_lock_pick_1: {result} {time.time() - start_time:.2f}s')
        self.assertEqual(result, True)

    def test_lock_pick_2(self):
        self.set_image('tests/images/lock_pick/02.png')
        start_time = time.time()
        result = self.task.is_lock_pick_active()
        self.logger.info(f'test_lock_pick_2: {result} {time.time() - start_time:.2f}s')
        self.assertEqual(result, True)

    def test_lock_pick_3(self):
        self.set_image('tests/images/lock_pick/03.png')
        start_time = time.time()
        result = self.task.is_lock_pick_active()
        self.logger.info(f'test_lock_pick_3: {result} {time.time() - start_time:.2f}s')
        self.assertEqual(result, True)

if __name__ == '__main__':
    unittest.main()
