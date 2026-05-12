import unittest
from unittest.mock import Mock

import numpy as np

from ok import Box
from src.Labels import Labels
from src.tasks.DailyTask import DailyTask


class TestDailyTaskMail(unittest.TestCase):
    def make_task(self):
        task = object.__new__(DailyTask)
        task.log_info = Mock()
        task.log_error = Mock()
        task.info_set = Mock()
        task.sleep = Mock()
        task.operate_click = Mock()
        return task

    def test_wait_mail_panel_rejects_generic_esc_panel(self):
        task = self.make_task()
        esc_panel = Mock(name="esc_option")
        esc_panel.name = Labels.esc_option.value
        task.wait_panel = Mock(return_value=esc_panel)

        result = DailyTask._wait_mail_panel(task)

        self.assertIsNone(result)
        task.wait_panel.assert_called_once_with(
            Labels.mail_panel,
            time_out=DailyTask.MAIL_PANEL_WAIT_TIMEOUT,
        )

    def test_click_mail_button_from_phone_menu_uses_detected_icon_center(self):
        task = self.make_task()
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        frame[900:940, 1650:1690] = 255
        panel = Box(1344, 108, 537, 885, name="mail_phone_menu")
        task.next_frame = Mock(return_value=frame)

        result = DailyTask._click_mail_button_from_phone_menu(task, panel)

        self.assertTrue(result)
        task.operate_click.assert_called_once_with(1670, 920, down_time=0.08)
        task.sleep.assert_called_once_with(1)

    def test_open_mail_panel_uses_phone_menu_and_verifies_mail_panel(self):
        task = self.make_task()
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        frame[900:940, 1650:1690] = 255
        panel = Box(1344, 108, 537, 885, name="mail_phone_menu")
        mail_panel = Mock(name="mail_panel")
        mail_panel.name = Labels.mail_panel.value
        task.openESCpanel = Mock(return_value=panel)
        task.next_frame = Mock(return_value=frame)
        task.wait_panel = Mock(return_value=mail_panel)

        result = DailyTask._open_mail_panel(task)

        self.assertIs(result, mail_panel)
        task.operate_click.assert_called_once_with(1670, 920, down_time=0.08)
        task.wait_panel.assert_called_once_with(
            Labels.mail_panel,
            time_out=DailyTask.MAIL_PANEL_WAIT_TIMEOUT,
        )

    def test_open_mail_panel_recovers_from_generic_esc_panel_when_mail_icon_visible(self):
        task = self.make_task()
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        frame[900:940, 1650:1690] = 255
        esc_panel = Mock(name="esc_option")
        esc_panel.name = Labels.esc_option.value
        mail_panel = Mock(name="mail_panel")
        mail_panel.name = Labels.mail_panel.value
        task.openESCpanel = Mock(return_value=esc_panel)
        task.next_frame = Mock(return_value=frame)
        task.wait_panel = Mock(return_value=mail_panel)

        result = DailyTask._open_mail_panel(task)

        self.assertIs(result, mail_panel)
        task.operate_click.assert_called_once_with(1670, 920, down_time=0.08)

    def test_open_mail_panel_reports_blocker_when_phone_menu_icon_missing(self):
        task = self.make_task()
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        panel = Box(1344, 108, 537, 885, name="mail_phone_menu")
        task.openESCpanel = Mock(return_value=panel)
        task.next_frame = Mock(return_value=frame)
        task.wait_panel = Mock()

        result = DailyTask._open_mail_panel(task)

        self.assertFalse(result)
        task.operate_click.assert_not_called()
        task.wait_panel.assert_not_called()
        task.info_set.assert_called_once_with(
            "邮件入口恢复失败",
            "phone_menu_mail_icon_not_found",
        )

    def test_claim_mail_returns_false_when_open_mail_panel_fails(self):
        task = self.make_task()
        task._open_mail_panel = Mock(return_value=False)

        result = DailyTask.claim_mail(task)

        self.assertFalse(result)
        task.operate_click.assert_not_called()
