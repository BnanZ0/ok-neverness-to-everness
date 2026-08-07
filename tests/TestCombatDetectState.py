import unittest
from unittest.mock import Mock, patch

from src.char.Baicang import Baicang
from src.char.Chiz import Chiz
from src.char.Daphneel import Daphneel
from src.char.Hania import Hania
from src.char.Iloy import Iloy
from src.char.Sakiri import Sakiri
from src.char.Yi import Yi
from src.char.Zero import Zero
from src.combat.BaseCombatTask import BaseCombatTask
from src.combat.CombatCheck import (
    CombatCheck,
    CombatDetectPhase,
    CombatDetectPolicy,
    CombatDetectResult,
    CombatDetectState,
)


class TestCombatDetectState(unittest.TestCase):
    def setUp(self):
        self.task = object.__new__(CombatCheck)
        self.task.combat_detect_policy = CombatDetectPolicy(miss_required=3, uncertain_seconds=2)
        self.task.combat_detect_state = CombatDetectState()
        self.task.log_info = Mock()
        self.task.middle_click = Mock()
        self.task._turn_on_retarget = False

    @patch("src.combat.CombatCheck.time.time", side_effect=[10, 11, 12])
    def test_enters_uncertain_on_configured_miss_count(self, _time):
        miss = CombatDetectResult(False, "miss")

        self.assertIs(
            self.task._update_combat_detect_state(miss), CombatDetectPhase.IN_COMBAT
        )
        self.assertIs(
            self.task._update_combat_detect_state(miss), CombatDetectPhase.IN_COMBAT
        )
        self.assertIs(
            self.task._update_combat_detect_state(miss), CombatDetectPhase.UNCERTAIN
        )
        self.assertEqual(self.task.combat_detect_state.uncertain_until, 14)
        self.task.middle_click.assert_called_once_with()

    @patch("src.combat.CombatCheck.time.time", return_value=11)
    def test_detection_hit_leaves_uncertain_before_timeout(self, _time):
        self.task.combat_detect_state.uncertain_until = 12

        phase = self.task._update_combat_detect_state(CombatDetectResult(True, "target"))

        self.assertIs(phase, CombatDetectPhase.IN_COMBAT)
        self.assertFalse(self.task.combat_detect_uncertain)

    @patch("src.combat.CombatCheck.time.time", return_value=12)
    def test_uncertain_timeout_moves_to_final_retarget_for_pending_detection(self, _time):
        self.task.combat_detect_state.uncertain_until = 12

        phase = self.task._update_combat_detect_state(CombatDetectResult(None, "pending"))

        self.assertIs(phase, CombatDetectPhase.VERIFY_TARGET)

    def test_auto_abyss_target_loss_holds_position_without_retargeting(self):
        self.task.should_hold_position_on_target_loss = Mock(return_value=True)
        self.task.reset_to_false = Mock(return_value=False)
        self.task.target_enemy = Mock()

        result = self.task._recover_or_end_combat()

        self.assertFalse(result)
        self.task.target_enemy.assert_not_called()
        self.task.reset_to_false.assert_called_once_with()

    def test_non_abyss_target_loss_keeps_existing_retarget_behavior(self):
        self.task.should_hold_position_on_target_loss = Mock(return_value=False)
        self.task.target_enemy = Mock(return_value=True)
        self.task._set_in_combat = Mock(return_value=True)

        result = self.task._recover_or_end_combat()

        self.assertTrue(result)
        self.task.target_enemy.assert_called_once_with(wait=True, turn=False)
        self.task._set_in_combat.assert_called_once_with("retarget_enemy")

    def test_auto_dual_team_only_holds_for_abyss_rosters(self):
        task = object.__new__(BaseCombatTask)
        task._is_auto_team_selection_enabled = Mock(return_value=True)

        task.chars = [
            object.__new__(Baicang),
            object.__new__(Daphneel),
            object.__new__(Hania),
            object.__new__(Sakiri),
        ]
        self.assertTrue(task.should_hold_position_on_target_loss())

        task.chars = [
            object.__new__(Chiz),
            object.__new__(Zero),
            object.__new__(Iloy),
            object.__new__(Yi),
        ]
        self.assertTrue(task.should_hold_position_on_target_loss())

        task.chars = [object.__new__(Iloy), object.__new__(Zero)]
        self.assertFalse(task.should_hold_position_on_target_loss())


if __name__ == "__main__":
    unittest.main()
