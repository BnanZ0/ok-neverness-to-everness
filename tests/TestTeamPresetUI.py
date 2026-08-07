import unittest
from unittest.mock import Mock, patch

from src.ui.TeamManagerTab import TeamManagerTab


class TestTeamPresetUI(unittest.TestCase):
    @staticmethod
    def _slots():
        return [
            {"char_id": f"char_{index}", "combo_id": ""} for index in range(4)
        ]

    def _tab(self):
        tab = Mock()
        tab.manager = Mock()
        tab._show_bar = Mock()
        tab.refresh_fixed_team_state = Mock()
        tab.tr_preset_incomplete = "incomplete"
        tab.tr_preset_save_failed = "save failed"
        tab.tr_preset_saved = "saved"
        tab.tr_preset_arm_failed = "arm failed"
        tab.tr_preset_armed = "armed"
        return tab

    def test_preset_save_failure_is_reported_as_error(self):
        tab = self._tab()
        slots = self._slots()
        tab._selected_team_preset = Mock(return_value=("team_a", "Team A"))
        tab._collect_fixed_team_slots = Mock(return_value=(slots, 4))
        tab.manager.set_team_preset.return_value = False

        TeamManagerTab.on_save_team_preset(tab)

        tab.manager.set_team_preset.assert_called_once_with(
            "team_a", "Team A", slots, activate=True
        )
        tab._show_bar.assert_called_once_with("", "save failed", success=False)
        tab.refresh_fixed_team_state.assert_not_called()

    def test_successful_preset_save_does_not_update_global_character_defaults(self):
        tab = self._tab()
        slots = self._slots()
        tab._selected_team_preset = Mock(return_value=("team_a", "Team A"))
        tab._collect_fixed_team_slots = Mock(return_value=(slots, 4))
        tab.manager.set_team_preset.return_value = True

        with patch("src.ui.TeamManagerTab.char_manager_signals") as signals:
            TeamManagerTab.on_save_team_preset(tab)

        tab._collect_fixed_team_slots.assert_called_once_with(
            persist=True,
            update_character_default=False,
        )
        tab.refresh_fixed_team_state.assert_called_once()
        signals.refresh_tab.emit.assert_called_once()
        tab._show_bar.assert_called_once_with("saved", "Team A")

    def test_arm_failure_does_not_show_success(self):
        tab = self._tab()
        tab._selected_team_preset = Mock(return_value=("team_a", "Team A"))
        tab.manager.arm_team_preset.return_value = False

        TeamManagerTab.on_arm_team_preset(tab)

        tab._show_bar.assert_called_once_with("", "arm failed", success=False)
        tab.refresh_fixed_team_state.assert_not_called()

    def test_auto_dual_team_toggle_persists_mode_and_refreshes(self):
        tab = self._tab()
        tab.auto_dual_team_check = Mock()
        tab.manager.set_team_selection_mode.return_value = True

        TeamManagerTab.on_auto_dual_team_toggled(tab, True)

        tab.manager.set_team_selection_mode.assert_called_once_with("auto")
        tab.refresh_fixed_team_state.assert_called_once()
        tab._show_bar.assert_not_called()

    def test_auto_dual_team_toggle_restores_checkbox_after_save_failure(self):
        tab = self._tab()
        tab.auto_dual_team_check = Mock()
        tab.manager.set_team_selection_mode.return_value = False

        TeamManagerTab.on_auto_dual_team_toggled(tab, True)

        tab.auto_dual_team_check.setChecked.assert_called_once_with(False)
        tab._show_bar.assert_called_once_with("", "save failed", success=False)


if __name__ == "__main__":
    unittest.main()
