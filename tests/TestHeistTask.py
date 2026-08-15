import unittest

import win32con

from src.tasks.trigger.HeistTask import HeistTask


class TestHeistTask(unittest.TestCase):
    def test_repeat_shift_down_does_not_suppress_release_when_initial_down_was_forwarded(self):
        task = object.__new__(HeistTask)
        task.physical_keys_pressed = {win32con.VK_LSHIFT}
        task.suppressed_keys = set()
        task._is_active = lambda: True
        task._suppressed_trigger_keys = lambda: set(task.SHIFT_KEYS)

        self.assertFalse(task._should_suppress(win32con.WM_KEYDOWN, win32con.VK_LSHIFT, True))
        self.assertFalse(task._should_suppress(win32con.WM_KEYUP, win32con.VK_LSHIFT))

    def test_repeat_of_suppressed_shift_down_stays_suppressed_until_release(self):
        task = object.__new__(HeistTask)
        task.physical_keys_pressed = {win32con.VK_LSHIFT}
        task.suppressed_keys = {win32con.VK_LSHIFT}
        task._is_active = lambda: True
        task._suppressed_trigger_keys = lambda: set(task.SHIFT_KEYS)

        self.assertTrue(task._should_suppress(win32con.WM_KEYDOWN, win32con.VK_LSHIFT, True))
        self.assertTrue(task._should_suppress(win32con.WM_KEYUP, win32con.VK_LSHIFT))
        self.assertNotIn(win32con.VK_LSHIFT, task.suppressed_keys)


if __name__ == "__main__":
    unittest.main()
