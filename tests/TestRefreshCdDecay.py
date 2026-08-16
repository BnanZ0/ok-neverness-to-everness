import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.combat.BaseCombatTask import BaseCombatTask


class TestRefreshCdDecay(unittest.TestCase):
    """refresh_cd must not reset CDs to 0 when OCR reads nothing.

    An OCR miss used to wipe the recorded cooldown, falsely reporting the
    skill/ultimate as available and desynchronising the combat rotation.
    The fix decays the last known CD by the elapsed time instead.
    """

    def setUp(self):
        self.task = object.__new__(BaseCombatTask)
        self.task.scene = SimpleNamespace(cd_refreshed=False)
        self.task.cds = {}
        self.task.get_current_char = Mock(return_value=SimpleNamespace(index=0))
        self.task.ocr = Mock(return_value=[])
        self.task.width_of_screen = Mock(side_effect=lambda ratio: ratio * 2560)
        self.elapsed_mock = Mock(return_value=0.0)
        self.task.time_elapsed_accounting_for_freeze = self.elapsed_mock

    def _refresh(self, now):
        with patch("src.combat.BaseCombatTask.time.time", return_value=now):
            self.task.refresh_cd()

    def test_ocr_failure_decays_previous_cd(self):
        self.task.cds[0] = {"skill": 8.0, "ultimate": 30.0, "time": 100.0}
        self.elapsed_mock.return_value = 5.0

        self._refresh(now=105.0)

        cds = self.task.cds[0]
        self.assertEqual(cds["skill"], 3.0)
        self.assertEqual(cds["ultimate"], 25.0)
        self.assertEqual(cds["time"], 105.0)

    def test_decay_floors_at_zero(self):
        self.task.cds[0] = {"skill": 8.0, "ultimate": 30.0, "time": 100.0}
        self.elapsed_mock.return_value = 40.0

        self._refresh(now=140.0)

        cds = self.task.cds[0]
        self.assertEqual(cds["skill"], 0)
        self.assertEqual(cds["ultimate"], 0)

    def test_first_refresh_defaults_to_zero(self):
        self._refresh(now=100.0)

        cds = self.task.cds[0]
        self.assertEqual(cds["skill"], 0)
        self.assertEqual(cds["ultimate"], 0)
        self.assertEqual(cds["time"], 100.0)

    def test_ocr_success_overrides_decayed_value(self):
        self.task.cds[0] = {"skill": 8.0, "ultimate": 30.0, "time": 100.0}
        self.elapsed_mock.return_value = 5.0
        # x=2000 < 0.89*2560 -> skill region
        self.task.ocr.return_value = [SimpleNamespace(name="6.5", x=2000)]

        self._refresh(now=105.0)

        cds = self.task.cds[0]
        self.assertEqual(cds["skill"], 6.5)
        self.assertEqual(cds["ultimate"], 25.0)

    def test_skips_when_already_refreshed(self):
        self.task.scene.cd_refreshed = True

        self.task.refresh_cd()

        self.task.ocr.assert_not_called()
        self.assertEqual(self.task.cds, {})


if __name__ == "__main__":
    unittest.main()
