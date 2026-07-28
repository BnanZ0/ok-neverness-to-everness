import unittest

from PySide6.QtWidgets import QApplication, QDialog, QPushButton

from src.ui.util import _CloseDelayGuard


class CloseDelayGuardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_cancel_bypasses_the_confirmation_delay(self):
        dialog = QDialog()
        dialog.yesButton = QPushButton("OK", dialog)
        dialog.cancelButton = QPushButton("Cancel", dialog)
        dialog.yesButton.clicked.connect(dialog.accept)
        dialog.cancelButton.clicked.connect(dialog.reject)
        finished_results = []
        dialog.finished.connect(finished_results.append)

        guard = _CloseDelayGuard(2, dialog)
        guard.start()

        self.assertFalse(dialog.yesButton.isEnabled())
        self.assertTrue(dialog.cancelButton.isEnabled())
        dialog.cancelButton.click()
        self.assertEqual(finished_results, [QDialog.DialogCode.Rejected])

    def test_confirmation_is_enabled_when_the_delay_expires(self):
        dialog = QDialog()
        dialog.yesButton = QPushButton("OK", dialog)
        dialog.cancelButton = QPushButton("Cancel", dialog)
        guard = _CloseDelayGuard(2, dialog)
        guard.start()

        guard._tick()
        self.assertFalse(dialog.yesButton.isEnabled())
        self.assertEqual(dialog.yesButton.text(), "OK (1)")

        guard._tick()
        self.assertTrue(dialog.yesButton.isEnabled())
        self.assertEqual(dialog.yesButton.text(), "OK")
