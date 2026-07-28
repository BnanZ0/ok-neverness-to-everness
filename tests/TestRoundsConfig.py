import unittest

from src.tasks.BaseNTETask import BaseNTETask, RoundState


class TestRoundsConfig(unittest.TestCase):
    def _make_task(self):
        task = object.__new__(BaseNTETask)
        task.name = "测试任务"
        task.config = {task.CONF_ROUNDS: "3"}
        task._round_state = RoundState()
        task.info = {}
        task.logs = []
        task.info_set = lambda key, value: task.info.__setitem__(key, value)
        task.log_info = lambda message, **kwargs: task.logs.append(("info", message, kwargs))
        task.log_error = lambda message: task.logs.append(("error", message, {}))
        return task

    def test_round_lifecycle_updates_shared_info_and_logs(self):
        task = self._make_task()

        task.start_rounds()
        self.assertEqual(task.info[task.INFO_SUCCESS_COUNT], 0)
        self.assertEqual(task.info[task.INFO_FAILED_COUNT], 0)

        self.assertTrue(task.begin_round())
        task.add_success()
        self.assertTrue(task.begin_round())
        task.add_failed("目标未找到")
        task.finish_rounds()

        self.assertEqual(task.info[task.INFO_ROUND], "2 / 3")
        self.assertEqual(task.info[task.INFO_SUCCESS_COUNT], 1)
        self.assertEqual(task.info[task.INFO_FAILED_COUNT], 1)
        self.assertEqual(task.info[task.INFO_FAILED_REASON], "目标未找到")
        self.assertIn(("info", "第 1 轮: 开始", {}), task.logs)
        self.assertIn(("error", "第 2 轮: 失败：目标未找到", {}), task.logs)
        self.assertEqual(task.logs[-1], ("info", "测试任务结束，成功 1/3", {"notify": True}))

    def test_begin_round_updates_a_changed_round_limit_without_resetting_counts(self):
        task = self._make_task()
        task.config[task.CONF_ROUNDS] = 0
        task.start_rounds()
        self.assertTrue(task.begin_round())
        task.add_success()
        task.config[task.CONF_ROUNDS] = 5
        self.assertTrue(task.begin_round())

        self.assertEqual(task.info[task.INFO_ROUND], "2 / 5")
        self.assertEqual(task.info[task.INFO_SUCCESS_COUNT], 1)

    def test_begin_round_reuses_the_active_round(self):
        task = self._make_task()

        task.start_rounds()
        self.assertTrue(task.begin_round())
        task.config[task.CONF_ROUNDS] = 1

        self.assertTrue(task.begin_round())
        self.assertEqual(task.current_round, 1)
        self.assertEqual(task.info[task.INFO_ROUND], "1 / 1")


if __name__ == "__main__":
    unittest.main()
